// Live layers: "Trenes en directo" (Renfe) and "Vuelos en directo" (adsb.lol), both off by default.
// A relay (config.js) adds CORS to the two feeds. While a layer is on and the tab is visible the app polls it
// (trains every 20 s, flights every 30 s, one request at a time per layer). On error the last data stays and the
// note says "sin datos en directo ahora". Markers are drawn as a world-space overlay (not in the cached map, so
// new data costs one redraw); hover goes through a hit-only static layer, which draws nothing.
import { liveUrl, ENABLED } from "./config.js";
import { loadProjection } from "../../geo/projection.js";
import { esc, int } from "../../format.js";

const ATTRIBUTION = ["Trenes: Renfe (CC BY 4.0)", "Vuelos: adsb.lol (ODbL)"].filter((_, i) => ENABLED[["trains", "flights"][i]]).join(" · ");
const FEEDS = {
  trains: { path: "trains", key: "trains", every: 20000, label: "Trenes en directo", short: "Trenes", icon: "🚆", title: "Posición de los trenes de Renfe (Cercanías y Larga distancia), cada 20 s" },
  flights: { path: "flights", key: "flights", every: 30000, label: "Vuelos en directo", short: "Vuelos", icon: "✈️", title: "Aviones comerciales en vuelo sobre España (adsb.lol), cada 30 s" },
};
const TIMEOUT_MS = 15000;
const AIRLINE = /^[A-Z]{3}\d/; // callsign: 3 letters + digits, never a registration or a hex id
const isNum = (n) => typeof n === "number" && Number.isFinite(n);

const COLOR = { ok: "#2e9e5b", late: "#e0a020", bad: "#d64545", none: "#8a8f98", plane: "#2b4c7e" };
function delayClass(d) {
  if (!isNum(d)) return "none";
  if (d <= 60) return "ok";
  return d <= 300 ? "late" : "bad";
}

export const trainTip = (t) => {
  const kind = t.net === "ld" ? "Larga distancia" : "Cercanías";
  const name = t.label || t.trip;
  const d = t.delay;
  const delay = !isNum(d) ? "retraso desconocido" : d <= 60 ? "a su hora" : `${int(Math.round(d / 60))} min de retraso`;
  return [kind, name ? esc(name) : null, delay].filter(Boolean).join(" · ");
};
export const flightTip = (f) => {
  const parts = [`<b>${esc(f.id)}</b>`];
  if (f.type) parts.push(esc(f.type));
  if (isNum(f.alt_ft)) parts.push(`${int(Math.round((f.alt_ft * 0.3048) / 100) * 100)} m`);
  if (isNum(f.gs_kt)) parts.push(`${int(f.gs_kt * 1.852)} km/h`);
  return parts.join(" · ");
};

export function install(app) {
  const st = {};
  for (const id of Object.keys(FEEDS)) st[id] = { on: false, items: [], pts: [], updated: null, got: 0, err: false, stale: false, timer: 0, busy: false };
  let proj = null, projFailed = false;
  const g = () => app.w.grid;

  // Items with their map position, skipping what the inset hides (or lies outside every region we can place).
  function place(id) {
    const s = st[id];
    s.pts = [];
    if (!proj) return;
    for (const it of s.items) {
      if (!isNum(it.lat) || !isNum(it.lon) || proj.hidden(it.lon, it.lat)) continue;
      const [x, y] = proj.project(it.lon, it.lat);
      s.pts.push({ x, y, it });
    }
  }

  async function poll(id) {
    const s = st[id], f = FEEDS[id];
    s.timer = 0;
    if (!s.on || document.hidden) return;
    if (!s.busy) {
      s.busy = true;
      const ctl = new AbortController();
      const kill = setTimeout(() => ctl.abort(), TIMEOUT_MS);
      try {
        const r = await fetch(`${liveUrl()}/${f.path}`, { signal: ctl.signal, cache: "no-store" });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        const list = d?.[f.key];
        if (!Array.isArray(list)) throw new Error("bad payload");
        s.items = id === "flights" ? list.filter((x) => typeof x.id === "string" && AIRLINE.test(x.id)) : list;
        s.updated = Date.parse(d.updated) || Date.now();
        s.got = Date.now();
        s.stale = !!d.stale;
        s.err = false;
        place(id);
      } catch {
        s.err = true; // keep the last data
      } finally {
        clearTimeout(kill);
        s.busy = false;
      }
      app.requestDraw();
      note();
    }
    schedule(id);
  }
  function schedule(id) {
    const s = st[id];
    if (s.timer || !s.on || document.hidden) return;
    s.timer = setTimeout(() => poll(id), FEEDS[id].every);
  }
  function stop(id) {
    clearTimeout(st[id].timer);
    st[id].timer = 0;
  }
  function setOn(id, v) {
    const s = st[id];
    s.on = !!v;
    if (s.on) {
      stop(id);
      poll(id);
    } else {
      stop(id);
    }
    note();
    app.requestDraw();
  }
  document.addEventListener("visibilitychange", () => {
    for (const id of Object.keys(st)) {
      if (!st[id].on) continue;
      if (document.hidden) stop(id);
      else { stop(id); poll(id); }
    }
    note();
  });

  loadProjection().then((p) => {
    proj = p;
    for (const id of Object.keys(st)) place(id);
    app.requestDraw();
  }, (err) => {
    projFailed = true;
    console.warn("live layers: projection.json failed to load", err);
    note();
  });

  // --- drawing: world-space overlay (km), sizes in css px / scale -----------------------------------------------
  const roundRect = (ctx, x, y, w, h, r) => {
    if (ctx.roundRect) { ctx.beginPath(); ctx.roundRect(x, y, w, h, r); }
    else { ctx.beginPath(); ctx.rect(x, y, w, h); }
  };
  app.registerOverlay({
    id: "live", z: 95, space: "world",
    draw(ctx, cam) {
      const px = 1 / cam.scale;
      const vx0 = cam.x - cam.w / 2 * px - 20 * px, vx1 = cam.x + cam.w / 2 * px + 20 * px;
      const vy0 = cam.y - cam.h / 2 * px - 20 * px, vy1 = cam.y + cam.h / 2 * px + 20 * px;
      ctx.lineWidth = 1 * px;
      ctx.strokeStyle = "rgba(255,255,255,0.9)";
      if (st.trains.on) {
        for (const p of st.trains.pts) {
          if (p.x < vx0 || p.x > vx1 || p.y < vy0 || p.y > vy1) continue;
          const ld = p.it.net === "ld";
          const h = (ld ? 3.6 : 2.4) * px;
          ctx.fillStyle = COLOR[delayClass(p.it.delay)];
          roundRect(ctx, p.x - h, p.y - h, 2 * h, 2 * h, h * 0.6);
          ctx.fill();
          ctx.stroke();
        }
      }
      if (st.flights.on) {
        ctx.fillStyle = COLOR.plane;
        for (const p of st.flights.pts) {
          if (p.x < vx0 || p.x > vx1 || p.y < vy0 || p.y > vy1) continue;
          if (!isNum(p.it.alt_ft)) continue; // on the ground
          ctx.save();
          ctx.translate(p.x, p.y);
          const L = 5 * px;
          ctx.beginPath();
          if (isNum(p.it.track)) {
            ctx.rotate((p.it.track * Math.PI) / 180);
            ctx.moveTo(0, -L);
            ctx.lineTo(L * 0.7, L * 0.8);
            ctx.lineTo(0, L * 0.4);
            ctx.lineTo(-L * 0.7, L * 0.8);
            ctx.closePath();
          } else {
            ctx.arc(0, 0, L * 0.6, 0, Math.PI * 2);
          }
          ctx.fill();
          ctx.stroke();
          ctx.restore();
        }
      }
    },
  });

  // --- hover: a static layer that draws nothing, only answers hit() and tooltip() ----------------------------------
  const TOL_PX = 9;
  app.registerStaticLayer({
    id: "live-hit", z: 90, minRpx: 4,
    visible: () => st.trains.on || st.flights.on,
    sig: () => "live-hit",
    draw() {},
    hit(x, y, Rpx) {
      const tol = (TOL_PX * g().R) / Rpx;
      let best = null, bd = tol * tol;
      const scan = (id, kind) => {
        if (!st[id].on) return;
        for (const p of st[id].pts) {
          if (kind === "flight" && !isNum(p.it.alt_ft)) continue;
          const d = (p.x - x) ** 2 + (p.y - y) ** 2;
          if (d < bd) { bd = d; best = { kind, data: p.it }; }
        }
      };
      scan("trains", "train");
      scan("flights", "flight");
      return best;
    },
    tooltip: (h) => (h.kind === "train" ? trainTip(h.data) : flightTip(h.data)),
  });

  // --- note: attribution + age (a DOM element, so the clock does not redraw the map) --------------------------------
  const el = document.createElement("div");
  el.id = "live-note";
  el.setAttribute("aria-live", "off");
  el.style.cssText = "position:fixed;right:8px;bottom:64px;z-index:20;max-width:min(92vw,420px);padding:4px 8px;border-radius:6px;font-size:11px;line-height:1.35;text-align:right;pointer-events:none;background:rgba(255,255,255,0.85);color:#3a3f47";
  el.hidden = true;
  document.body.appendChild(el);
  let clock = 0;
  function note() {
    const ids = Object.keys(st).filter((id) => st[id].on);
    if (!ids.length) {
      el.hidden = true;
      clearInterval(clock);
      clock = 0;
      return;
    }
    const now = Date.now();
    const lines = ids.map((id) => {
      const s = st[id];
      if (projFailed) return `${FEEDS[id].short}: sin datos en directo ahora`;
      if (!s.got) return s.err ? `${FEEDS[id].short}: sin datos en directo ahora` : `${FEEDS[id].short}: cargando`;
      const age = Math.max(0, Math.round((now - s.updated) / 1000));
      const ago = age < 120 ? `${age} s` : `${Math.round(age / 60)} min`;
      const bad = s.err || s.stale ? ` · <span style="opacity:.75">sin datos en directo ahora</span>` : "";
      return `${FEEDS[id].short}: actualizado hace ${ago}${bad}`;
    });
    el.innerHTML = `${lines.join("<br>")}<br><span style="opacity:.75">${esc(ATTRIBUTION)}</span>`;
    el.hidden = false;
    if (!clock) clock = setInterval(note, 1000);
  }

  for (const [id, f] of Object.entries(FEEDS)) {
    if (!ENABLED[id]) continue;
    app.ui.addMapToggle({
      id: `live-${id}`, label: f.label, icon: f.icon, title: f.title, default: false,
      get: () => st[id].on,
      set: (v) => setOn(id, v),
    });
  }
  app.live = { state: st };
}
