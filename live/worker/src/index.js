import { trainsFrom, flightsFrom } from "./transform.js";
import { parseForecast, parseWarnings } from "./weather.js";
import { CITIES } from "./cities.js";

const UA = "spain-strategy-map/1.0 (open-source map project)";
const TIMEOUT_MS = 8000;
const GOOD_TTL_S = 6 * 3600;
const BROWSER_MAX_AGE = 15;

const R = "https://gtfsrt.renfe.com/";
// Four circles of 250 nm (the API's maximum radius): west, east and south of the peninsula (the east one reaches the
// Balearics) and the Canaries. Requests are metered per key: 4 circles every 6 minutes = 960 a day.
const ADSB = [
  "https://api.adsb.lol/v2/lat/40.6/lon/-6.6/dist/250",
  "https://api.adsb.lol/v2/lat/40.4/lon/0.6/dist/250",
  "https://api.adsb.lol/v2/lat/37.9/lon/-3.6/dist/250",
  "https://api.adsb.lol/v2/lat/28.4/lon/-15.6/dist/250",
];
const FLIGHTS_FRESH_S = 360;

async function getJson(url, extra = {}) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(url, {
      headers: { "User-Agent": UA, Accept: "application/json", ...extra },
      signal: ctl.signal,
    });
    if (!res.ok) throw new Error(`upstream ${res.status}`);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

const AEMET_FORECAST = "https://www.aemet.es/xml/municipios/localidad_";
const AEMET_WARNINGS = "https://www.aemet.es/documentos_d/eltiempo/prediccion/avisos/rss/CAP_AFAE_wah_RSS.xml";
const WEATHER_CONCURRENCY = 6;

async function getText(url, encoding) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(url, {
      headers: { "User-Agent": UA, Accept: "application/xml, text/xml" },
      signal: ctl.signal,
    });
    if (!res.ok) throw new Error(`upstream ${res.status}`);
    const buf = await res.arrayBuffer();
    return new TextDecoder(encoding).decode(buf);
  } finally {
    clearTimeout(timer);
  }
}

async function buildWeather() {
  const cities = {};
  let ok = 0;
  let next = 0;
  async function worker() {
    while (next < CITIES.length) {
      const c = CITIES[next++];
      const entry = { ine: c.ine, name: c.name, elaborado: null, days: [] };
      try {
        const f = parseForecast(await getText(AEMET_FORECAST + c.ine + ".xml", "iso-8859-15"));
        if (f.days.length) {
          entry.elaborado = f.elaborado;
          entry.days = f.days;
          ok++;
        }
      } catch (_) {
        /* city stays with days: [] */
      }
      cities[c.id] = entry;
    }
  }
  const warningsP = getText(AEMET_WARNINGS, "utf-8").then(parseWarnings).catch(() => ({ warnings: [], warnings_total: null }));
  await Promise.all(Array.from({ length: WEATHER_CONCURRENCY }, worker));
  if (ok * 2 < CITIES.length) throw new Error(`aemet: only ${ok}/${CITIES.length} cities answered`);
  const w = await warningsP;
  return {
    updated: new Date().toISOString(),
    source: "AEMET",
    stale: false,
    cities,
    warnings: w.warnings,
    warnings_total: w.warnings_total,
  };
}

const ROUTES = {
  "/weather": {
    fresh: 1800,
    build: buildWeather,
  },
  "/trains": {
    fresh: 25, // Renfe sends max-age=30
    async build() {
      const [pc, pl, tc, tl] = await Promise.all([
        getJson(R + "vehicle_positions.json"),
        getJson(R + "vehicle_positions_LD.json"),
        getJson(R + "trip_updates.json").catch(() => null), // delays are optional
        getJson(R + "trip_updates_LD.json").catch(() => null),
      ]);
      return trainsFrom(pc, pl, tc, tl);
    },
  },
  "/flights": {
    fresh: FLIGHTS_FRESH_S,
    async build(env) {
      // The key is a Worker secret (wrangler secret put ADSB_LOL_KEY), never in the repo. Without it adsb.lol counts
      // requests per IP, and Workers share theirs.
      const key = env && env.ADSB_LOL_KEY ? { "x-api-key": env.ADSB_LOL_KEY } : {};
      // One circle at a time: adsb.lol rate-limits bursts.
      const ok = [], errs = [];
      for (const url of ADSB) {
        try { ok.push(await getJson(url, key)); } catch (e) { errs.push(String(e && e.message || e)); }
      }
      if (!ok.length) throw new Error("all adsb circles failed: " + errs.join("; "));
      return flightsFrom(ok);
    },
  },
};

// Two layers: the Cache API (shared per data centre) and a per-isolate map.
// The Cache API is a no-op on some hostnames (workers.dev among them), so the
// map keeps the relay working there; each isolate then refreshes on its own.
const memory = new Map(); // key -> { at, body }
const inflight = new Map(); // route -> Promise<body>

const cacheKey = (kind, route) => new Request(`https://live-cache.invalid/${kind}${route}`);

async function readCache(kind, route, maxAgeS) {
  const mem = memory.get(kind + route);
  if (mem && Date.now() - mem.at < maxAgeS * 1000) return mem.body;
  try {
    const hit = await caches.default.match(cacheKey(kind, route));
    if (hit) {
      const at = Number(hit.headers.get("X-Stored-At")) || 0;
      if (Date.now() - at < maxAgeS * 1000) return await hit.json();
    }
  } catch (_) {
    /* cache unavailable */
  }
  return null;
}

function writeCache(ctx, route, body, freshS) {
  const at = Date.now();
  memory.set("fresh" + route, { at, body });
  memory.set("good" + route, { at, body });
  const mk = (ttl) =>
    new Response(JSON.stringify(body), {
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": `public, max-age=${ttl}`,
        "X-Stored-At": String(at),
      },
    });
  try {
    ctx.waitUntil(
      Promise.all([
        caches.default.put(cacheKey("fresh", route), mk(freshS)),
        caches.default.put(cacheKey("good", route), mk(GOOD_TTL_S)),
      ]).catch(() => {}),
    );
  } catch (_) {
    /* ignore */
  }
}

function corsHeaders(request, env) {
  const origin = request.headers.get("Origin");
  const allowed = String(env.ALLOWED_ORIGINS || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const h = {
    Vary: "Origin",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Expose-Headers": "X-Live-Stale",
    "Access-Control-Max-Age": "86400",
  };
  if (origin && allowed.includes(origin)) h["Access-Control-Allow-Origin"] = origin;
  return h;
}

function json(body, status, request, env, extra = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": status === 200 ? `public, max-age=${BROWSER_MAX_AGE}` : "no-store",
      ...corsHeaders(request, env),
      ...extra,
    },
  });
}

async function serve(route, request, env, ctx) {
  const cfg = ROUTES[route];
  const fresh = await readCache("fresh", route, cfg.fresh);
  if (fresh) return json(fresh, 200, request, env);

  let pending = inflight.get(route);
  if (!pending) {
    pending = cfg.build(env).finally(() => inflight.delete(route));
    inflight.set(route, pending);
  }
  try {
    const body = await pending;
    writeCache(ctx, route, body, cfg.fresh);
    return json(body, 200, request, env);
  } catch (err) {
    const good = await readCache("good", route, GOOD_TTL_S);
    if (good) {
      return json({ ...good, stale: true }, 200, request, env, { "X-Live-Stale": "1" });
    }
    return json({ error: "upstream unavailable", detail: String(err && err.message || err).slice(0, 200) }, 502, request, env);
  }
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const route = url.pathname.replace(/\/+$/, "") || "/";
    if (!ROUTES[route]) return json({ error: "not found" }, 404, request, env);
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(request, env) });
    }
    if (request.method !== "GET" && request.method !== "HEAD") {
      return json({ error: "method not allowed" }, 405, request, env, { Allow: "GET, OPTIONS" });
    }
    return serve(route, request, env, ctx);
  },
};
