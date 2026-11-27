// Official weather: "Tiempo hoy (AEMET)", off by default. A small chip under each city (sky icon + max / min) from the
// AEMET municipal forecast, relayed by the live Worker (GET /weather, see docs/DATA_CONTRACTS.md "Weather").
// The forecast is shown as AEMET issued it (never altered), with its "elaborado" time and the credit "© AEMET".
// Chips are a screen-space overlay drawn under the banners (z < 100); hover goes through a hit-only static layer that
// answers from the rectangles of the last draw. While the layer is on and the tab is visible the page polls every
// 30 min, one request at a time, and keeps the last data on error.
import { liveUrl } from "../live/config.js";
import { esc, int } from "../../format.js";

const EVERY_MS = 30 * 60 * 1000;
const TIMEOUT_MS = 20000;
const NOTE_BOTTOM = 64; // same baseline as the live note (px)
const LEVEL_COLOR = { amarillo: "#e0a020", naranja: "#e8741a", rojo: "#d64545" };
const isNum = (n) => typeof n === "number" && Number.isFinite(n);
const AEMET_URL = "https://www.aemet.es/es/nota_legal";

// AEMET sky code ("11", "12n", ...) -> emoji; null when unknown (the chip then shows text only).
export function skyIcon(code) {
  if (code == null) return null;
  const n = Number(String(code).replace(/n$/i, ""));
  if (!Number.isInteger(n)) return null;
  if (n === 11) return "☀️";
  if (n === 12) return "🌤️";
  if (n === 13) return "⛅";
  if (n >= 14 && n <= 17) return "☁️";
  if ((n >= 23 && n <= 26) || (n >= 43 && n <= 46)) return "🌧️";
  if (n >= 51 && n <= 64) return "⛈️";
  if ((n >= 33 && n <= 36) || (n >= 71 && n <= 74)) return "🌨️";
  if (n >= 81 && n <= 83) return "🌫️";
  return null;
}

const madridDay = (d = new Date()) => d.toLocaleDateString("sv-SE", { timeZone: "Europe/Madrid" }); // YYYY-MM-DD
const deg = (n) => `${int(n)}°`;

// Day entry for today and for tomorrow (null when missing). A stale payload whose first day is older than today is
// still shown, but then `late` is true so the tooltip names the date instead of saying nothing.
export function pickDays(days, today = madridDay()) {
  const list = Array.isArray(days) ? days.filter((d) => d && typeof d === "object") : [];
  let i = list.findIndex((d) => d.date === today);
  let late = false;
  if (i < 0) { i = list.length ? 0 : -1; late = i >= 0; }
  return { day: i >= 0 ? list[i] : null, next: i >= 0 ? list[i + 1] || null : null, late };
}

export function chipText(day) {
  if (!day) return "";
  if (!isNum(day.tmax) && !isNum(day.tmin)) return "";
  return `${isNum(day.tmax) ? deg(day.tmax) : "–"} / ${isNum(day.tmin) ? deg(day.tmin) : "–"}`;
}

// "Despejado · máx. 14 °C, mín. 3 °C · lluvia 20 % · viento NE 15 km/h" (plain text; missing parts are left out)
export function dayLine(d) {
  if (!d) return "";
  const parts = [];
  if (d.sky_text) parts.push(d.sky_text);
  const t = [];
  if (isNum(d.tmax)) t.push(`máx. ${int(d.tmax)} °C`);
  if (isNum(d.tmin)) t.push(`mín. ${int(d.tmin)} °C`);
  if (t.length) parts.push(t.join(", "));
  if (isNum(d.rain_prob)) parts.push(`lluvia ${int(d.rain_prob)} %`);
  if (isNum(d.wind_kmh)) parts.push(`viento ${d.wind_dir ? `${d.wind_dir} ` : ""}${int(d.wind_kmh)} km/h`);
  else if (d.wind_dir) parts.push(`viento ${d.wind_dir}`);
  return parts.join(" · ");
}

export function fmtElaborado(iso) {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return null;
  return new Date(t).toLocaleString("es-ES", { timeZone: "Europe/Madrid", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });
}

export function weatherTip(city, entry, today = madridDay()) {
  const name = esc(entry?.name || city.name);
  const { day, next, late } = pickDays(entry?.days, today);
  const rows = [];
  const first = dayLine(day);
  if (first) rows.push(`<b>${name}</b> · ${late && day?.date ? `${esc(day.date)}: ` : ""}${esc(first)}`);
  else rows.push(`<b>${name}</b> · <span class="muted">sin predicción de AEMET</span>`);
  const second = dayLine(next);
  if (second) rows.push(`Mañana: ${esc(second)}`);
  const el = fmtElaborado(entry?.elaborado);
  if (el) rows.push(`<span class="muted">Predicción de AEMET elaborada el ${esc(el)}</span>`);
  return rows.join("<br>");
}

export function install(app) {
  const st = { on: false, data: null, err: false, got: 0, timer: 0, busy: false, open: false };
  const cities = app.data.cities;
  const g = () => app.w.grid;
  let drawn = { cam: null, rects: [] };

  // --- polling -------------------------------------------------------------------------------------------------
  async function poll() {
    st.timer = 0;
    if (!st.on || document.hidden) return;
    if (!st.busy) {
      st.busy = true;
      const ctl = new AbortController();
      const kill = setTimeout(() => ctl.abort(), TIMEOUT_MS);
      try {
        const r = await fetch(`${liveUrl()}/weather`, { signal: ctl.signal, cache: "no-store" });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        if (!d || typeof d.cities !== "object" || d.cities === null) throw new Error("bad payload");
        st.data = d;
        st.got = Date.now();
        st.err = false;
      } catch {
        st.err = true; // keep the last data
      } finally {
        clearTimeout(kill);
        st.busy = false;
      }
      app.requestDraw();
      render();
    }
    schedule();
  }
  function schedule() {
    if (st.timer || !st.on || document.hidden) return;
    st.timer = setTimeout(poll, EVERY_MS);
  }
  function stop() {
    clearTimeout(st.timer);
    st.timer = 0;
  }
  function setOn(v) {
    st.on = !!v;
    stop();
    if (st.on) poll();
    else st.open = false;
    render();
    app.requestDraw();
  }
  document.addEventListener("visibilitychange", () => {
    if (!st.on) return;
    stop();
    if (!document.hidden) {
      if (Date.now() - st.got > EVERY_MS) poll();
      else schedule();
    }
  });

  const entryOf = (id) => st.data?.cities?.[id] || null;

  // --- chips: screen-space overlay under the banners ------------------------------------------------------------
  app.registerOverlay({
    id: "weather", z: 96, space: "screen",
    draw(ctx, cam) {
      drawn = { cam: { x: cam.x, y: cam.y, scale: cam.scale, w: cam.w, h: cam.h }, rects: [] };
      if (!st.on || !st.data) return;
      const grid = g();
      const Rpx = grid.R * cam.scale;
      const small = Rpx < 8;
      const fs = small ? 9 : 10.5, h = small ? 13 : 15;
      ctx.font = `600 ${fs}px -apple-system, system-ui, sans-serif`;
      ctx.textBaseline = "middle";
      const placed = [];
      for (const city of cities) {
        const e = entryOf(city.id);
        if (!e) continue;
        const { day } = pickDays(e.days);
        const icon = skyIcon(day?.sky);
        const txt = chipText(day);
        if (!icon && !txt) continue;
        const [sx, sy] = city.cell != null ? cam.toScreen(grid.cx(city.cell), grid.cy(city.cell)) : cam.toScreen(city.x, city.y);
        if (sx < -60 || sy < -40 || sx > cam.w + 60 || sy > cam.h + 40) continue;
        const iw = icon ? fs + 2 : 0;
        const w = Math.ceil(iw + (txt ? ctx.measureText(txt).width : 0) + (icon && txt ? 3 : 0) + 8);
        const r = { x: Math.round(sx - w / 2), y: Math.round(sy + Math.max(5, Rpx * 0.45)), w, h, id: city.id };
        if (placed.some((p) => r.x < p.x + p.w + 3 && p.x < r.x + r.w + 3 && r.y < p.y + p.h + 2 && p.y < r.y + r.h + 2)) continue;
        placed.push(r);
        ctx.fillStyle = "rgba(14,18,26,0.78)";
        ctx.strokeStyle = "rgba(255,255,255,0.35)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(r.x + 0.5, r.y + 0.5, w, h, 4); else ctx.rect(r.x + 0.5, r.y + 0.5, w, h);
        ctx.fill();
        ctx.stroke();
        let x = r.x + 4;
        const cy = r.y + h / 2 + 0.5;
        if (icon) {
          ctx.fillStyle = "#fff";
          ctx.fillText(icon, x, cy);
          x += iw + 3;
        }
        if (txt) {
          ctx.fillStyle = "#f2efe6";
          ctx.fillText(txt, x, cy);
        }
      }
      drawn.rects = placed;
    },
  });

  // --- hover: hit-only static layer, answers from the rectangles of the last draw ---------------------------------
  const cityOf = new Map(cities.map((c) => [c.id, c]));
  app.registerStaticLayer({
    id: "weather-hit", z: 92,
    visible: () => st.on && !!st.data,
    sig: () => "weather-hit",
    draw() {},
    hit(x, y) {
      const c = drawn.cam;
      if (!c) return null;
      const sx = (x - c.x) * c.scale + c.w / 2, sy = (y - c.y) * c.scale + c.h / 2;
      const r = drawn.rects.find((q) => sx >= q.x - 1 && sx <= q.x + q.w + 1 && sy >= q.y - 1 && sy <= q.y + q.h + 1);
      return r ? { id: r.id } : null;
    },
    tooltip: (h) => {
      const city = cityOf.get(h.id);
      return city ? weatherTip(city, entryOf(h.id)) : null;
    },
  });

  // --- note: credit + warnings (DOM), stacked above the live note ----------------------------------------------
  const el = document.createElement("div");
  el.id = "weather-note";
  el.style.cssText = `position:fixed;right:8px;bottom:${NOTE_BOTTOM}px;z-index:21;max-width:min(92vw,420px);padding:4px 8px;border-radius:6px;font-size:11px;line-height:1.35;text-align:right;background:rgba(255,255,255,0.85);color:#3a3f47`;
  el.hidden = true;
  document.body.appendChild(el);
  el.addEventListener("click", (ev) => {
    if (ev.target.closest("[data-warn-toggle]")) {
      st.open = !st.open;
      render();
    }
  });
  let clock = 0;
  const btn = "font:inherit;color:#1d4f91;background:none;border:0;padding:0;cursor:pointer;text-decoration:underline";
  function place() {
    const live = document.getElementById("live-note");
    const lift = live && !live.hidden ? live.offsetHeight + 4 : 0;
    el.style.bottom = `${NOTE_BOTTOM + lift}px`;
  }
  function render() {
    if (!st.on) {
      el.hidden = true;
      clearInterval(clock);
      clock = 0;
      return;
    }
    const d = st.data;
    const lines = [];
    const total = isNum(d?.warnings_total) ? d.warnings_total : Array.isArray(d?.warnings) ? d.warnings.length : 0;
    let head = `Tiempo: <a href="${AEMET_URL}" target="_blank" rel="noopener" style="color:inherit">© AEMET</a>`;
    if (total > 0) head += ` · <button type="button" data-warn-toggle style="${btn}" aria-expanded="${st.open}">${int(total)} ${total === 1 ? "aviso activo" : "avisos activos"}</button>`;
    lines.push(head);
    if (!d && !st.err) lines.push("cargando");
    if (st.err || d?.stale) lines.push(`<span style="opacity:.75">sin datos de AEMET ahora</span>`);
    let list = "";
    if (st.open && Array.isArray(d?.warnings) && d.warnings.length) {
      const items = d.warnings.map((w) => {
        const col = LEVEL_COLOR[w.level] || "#8a8f98";
        const lvl = w.level ? `<b style="color:${col}">${esc(w.level)}</b> ` : "";
        const title = w.link && /^https:\/\/www\.aemet\.es\//.test(w.link)
          ? `<a href="${esc(w.link)}" target="_blank" rel="noopener" style="color:#1d4f91">${esc(w.title)}</a>`
          : esc(w.title);
        return `<li style="margin:2px 0;padding-left:6px;border-left:3px solid ${col}">${lvl}${title}${w.area ? ` <span style="opacity:.75">(${esc(w.area)})</span>` : ""}</li>`;
      });
      const more = total > d.warnings.length ? `<div style="opacity:.75">y ${int(total - d.warnings.length)} más en aemet.es</div>` : "";
      list = `<div style="margin-top:4px;max-height:40vh;overflow:auto;text-align:left"><ul style="margin:0;padding:0;list-style:none">${items.join("")}</ul>${more}</div>`;
    }
    el.innerHTML = lines.join("<br>") + list;
    el.hidden = false;
    place();
    if (!clock) clock = setInterval(place, 1000);
  }

  app.ui.addMapToggle({
    id: "weather", label: "Tiempo hoy (AEMET)", icon: "⛅", title: "Predicción oficial de hoy para cada ciudad (AEMET), se actualiza cada 30 min", default: false,
    get: () => st.on,
    set: (v) => setOn(v),
  });
  app.weather = { state: st, forecast: (id) => entryOf(id) };
}
