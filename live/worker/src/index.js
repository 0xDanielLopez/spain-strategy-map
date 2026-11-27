import { trainsFrom, flightsFrom } from "./transform.js";

const UA = "spain-strategy-map/1.0 (open-source map project)";
const TIMEOUT_MS = 8000;
const GOOD_TTL_S = 6 * 3600;
const BROWSER_MAX_AGE = 15;

const R = "https://gtfsrt.renfe.com/";
const ADSB = [
  "https://api.adsb.lol/v2/lat/40.2/lon/-3.7/dist/250",
  "https://api.adsb.lol/v2/lat/41.3/lon/2.6/dist/160",
  "https://api.adsb.lol/v2/lat/28.4/lon/-15.6/dist/180",
];

async function getJson(url) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(url, {
      headers: { "User-Agent": UA, Accept: "application/json" },
      signal: ctl.signal,
    });
    if (!res.ok) throw new Error(`upstream ${res.status}`);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

const ROUTES = {
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
    fresh: 25,
    async build() {
      // One circle at a time: adsb.lol rate-limits bursts.
      const ok = [], errs = [];
      for (const url of ADSB) {
        try { ok.push(await getJson(url)); } catch (e) { errs.push(String(e && e.message || e)); }
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
    pending = cfg.build().finally(() => inflight.delete(route));
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
