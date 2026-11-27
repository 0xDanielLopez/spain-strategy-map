// Front page: full-screen map of real municipal boundaries (canvas), side panel, data chips and optional point and live layers.
import { loadProjection } from '../js/geo/projection.js';
import { liveUrl } from '../js/ext/live/config.js';

const NF0 = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 0, useGrouping: 'always' });
const NF1 = new Intl.NumberFormat('es-ES', { minimumFractionDigits: 1, maximumFractionDigits: 1, useGrouping: 'always' });
const NA = 'sin dato';
const NOUN = { income: 'renta', age_mean: 'edad media', growth: 'crecimiento', density: 'densidad', elderly: 'mayores de 65', foreign: 'población extranjera', household: 'personas por hogar', poverty: 'población bajo el umbral de pobreza', higher_education: 'estudios superiores', non_primary: 'viviendas no principales', tourist: 'viviendas turísticas', born_abroad: 'nacidos en el extranjero', immigration: 'llegadas desde el extranjero', crime_rate: 'infracciones penales' };
const SHORT = { income: 'Renta', age_mean: 'Edad', growth: 'Crecimiento', density: 'Densidad', tourist: 'Viv. turísticas', foreign: 'Extranjeros', elderly: 'Mayores de 65', household: 'Tamaño del hogar', poverty: 'Pobreza', higher_education: 'Estudios superiores', non_primary: 'Viv. no principales', born_abroad: 'Nacidos fuera', immigration: 'Llegadas', crime_rate: 'Infracciones' };
const MAIN = ['income', 'age_mean', 'growth', 'density', 'tourist', 'foreign'];
const PHRASE = {
  income: ['Más renta que', 'Menos renta que'], age_mean: ['Población más envejecida que', 'Población más joven que'], growth: ['Crece más que', 'Crece menos que'],
  density: ['Más densidad que', 'Menos densidad que'], elderly: ['Más personas de 65 años o más que', 'Menos personas de 65 años o más que'],
  foreign: ['Más población extranjera que', 'Menos población extranjera que'], household: ['Hogares más grandes que', 'Hogares más pequeños que'],
  poverty: ['Más población bajo el umbral de pobreza que', 'Menos población bajo el umbral de pobreza que'], higher_education: ['Más población con estudios superiores que', 'Menos población con estudios superiores que'] };
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const norm = (s) => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
const isNum = (v) => v != null && !Number.isNaN(v);
const $ = (id) => document.getElementById(id);
const css = (n, fb) => getComputedStyle(document.documentElement).getPropertyValue(n).trim() || fb;

let D, ROWS, PROJ_P = null, N, COL = {}, IND = [], IND_BY = {}, PROV = {}, CODES = [], IDX = {}, CENT, SW, SH, YEARS, LAST;
function fmt(v, key) {
  if (!isNum(v)) return NA;
  const f = IND_BY[key].format; let s;
  if (f === 'eur') s = NF0.format(v) + ' €'; else if (f === 'years') s = NF1.format(v) + ' años';
  else if (f === 'pct') s = NF1.format(v) + ' %'; else if (f === 'int') s = NF0.format(v); else s = NF1.format(v);
  if (key === 'growth' && v > 0) s = '+' + s;
  if (key === 'density') s += ' hab./km²';
  if (key === 'household') s += ' personas';
  return s;
}
function fmtS(v, key) { // compact, for the legend
  if (!isNum(v)) return NA; const f = IND_BY[key].format;
  if (f === 'eur') return NF0.format(v) + ' €'; if (key === 'density' || f === 'int') return NF0.format(v);
  if (f === 'pct') return (key === 'growth' && v > 0 ? '+' : '') + NF1.format(v) + ' %'; return NF1.format(v);
}
const cache = {};
// Income can be shown for any year 2015-2024 (series); every other indicator is a single snapshot.
const yearOn = (key) => key === 'income' && st.yi < LAST;
function val(i, key) {
  if (yearOn(key)) { const s = D.series.munis[CODES[i]]; const v = s ? s[st.yi] : null; return isNum(v) ? v : null; }
  return ROWS[i][COL[key]];
}
function values(key) {
  const ck = 'v' + key + (yearOn(key) ? st.yi : '');
  if (cache[ck]) return cache[ck];
  const a = new Float64Array(N);
  for (let i = 0; i < N; i++) { const v = val(i, key); a[i] = v == null ? NaN : v; }
  return (cache[ck] = a);
}
const sortedVals = (key) => { const ck = 's' + key + (yearOn(key) ? st.yi : ''); return cache[ck] || (cache[ck] = Float64Array.from(values(key).filter((v) => !Number.isNaN(v))).sort()); };
// Breaks come from the latest snapshot and stay fixed while the year changes, so colours are comparable across years.
function breaks(key) {
  if (cache['b' + key]) return cache['b' + key];
  const c = COL[key], s = Float64Array.from(ROWS.map((r) => r[c]).filter(isNum)).sort(), n = s.length;
  return (cache['b' + key] = [0.2, 0.4, 0.6, 0.8].map((p) => s[Math.floor(p * n)]));
}
function nationOf(key) {
  if (yearOn(key)) { const v = D.series.nation[st.yi]; return { value: isNum(v) ? v : null, q: null }; }
  return D.nation[key] || { value: null, q: null };
}
function quantiles(key) {
  const n = nationOf(key); if (n.q) return n.q;
  const s = sortedVals(key), at = (p) => s[Math.min(s.length - 1, Math.floor(p * s.length))];
  return [0.025, 0.25, 0.5, 0.75, 0.975].map(at);
}
function lessCount(s, v) { let lo = 0, hi = s.length; while (lo < hi) { const m = (lo + hi) >> 1; if (s[m] < v) lo = m + 1; else hi = m; } return lo; }
function coverage(key) {
  if (cache['c' + key] == null) { let a = 0, all = 0; for (const r of ROWS) { const p = r[COL.population] || 0; all += p; if (isNum(r[COL[key]])) a += p; } cache['c' + key] = all ? a / all : 1; }
  return cache['c' + key];
}
const partial = (key) => coverage(key) < 0.9;
const isPartial = partial;
const nWithData = (key) => ROWS.reduce((n, r) => n + (isNum(r[COL[key]]) ? 1 : 0), 0);
const natWord = (key) => (isPartial(key) ? `media de los ${NF0.format(nWithData(key))} municipios con dato` : 'media de España');
const NatWord = (key) => { const w = natWord(key); return w[0].toUpperCase() + w.slice(1); };
const unitTail = (key) => { const i = IND_BY[key]; return i && i.format === 'dec1' && key !== 'household' && i.unit ? ' ' + i.unit : ''; };
function sentenceFor(key, v) {
  if (!isNum(v)) return 'No hay dato para comparar este municipio.';
  const s = sortedVals(key), t = Math.round((10 * lessCount(s, v)) / s.length);
  const noun = NOUN[key]; const ph = PHRASE[key] || ['Más ' + noun + ' que', 'Menos ' + noun + ' que'];
  const tail = s.length / N < 0.9 ? ` entre los ${NF0.format(s.length)} municipios con dato` : '';
  if (t >= 5) return `${ph[0]} ${t >= 10 ? 'casi todos los municipios' : t + ' de cada 10 municipios'}${tail}.`;
  return `${ph[1]} ${t <= 0 ? 'casi todos los municipios' : 10 - t + ' de cada 10 municipios'}${tail}.`;
}
function stripHTML(key, v) {
  if (!isNum(v)) return `<div class="strip strip-na"><span>${NA}</span></div>`;
  const q = quantiles(key), s = sortedVals(key);
  const T = key === 'density' ? (x) => Math.log10(Math.max(x, 0) + 1) : (x) => x;
  const lo = Math.min(T(s[Math.floor(s.length * 0.01)]), T(q[0])), hi = Math.max(T(s[Math.floor(s.length * 0.99)]), T(q[4]));
  const pos = (x) => Math.max(0, Math.min(100, ((T(x) - lo) / (hi - lo)) * 100));
  return `<div class="strip" role="img" aria-label="${esc(sentenceFor(key, v))}"><span class="b95" style="left:${pos(q[0])}%;width:${pos(q[4]) - pos(q[0])}%"></span><span class="b50" style="left:${pos(q[1])}%;width:${pos(q[3]) - pos(q[1])}%"></span><span class="med" style="left:${pos(q[2])}%"></span><span class="dot" style="left:${pos(v)}%"></span></div>`;
}

const st = { key: 'income', sel: null, yi: 0, layers: { airports: false, ports: false, heritage: false, trains: false } };
const LAYER_KEYS = ['airports', 'ports', 'heritage', 'trains'];
const LAYER_DEF = { airports: ['✈️', 'Aeropuertos', '✈︎'], ports: ['⚓', 'Puertos', '⚓︎'], heritage: ['🏛️', 'Patrimonio Mundial', '🏛︎'], trains: ['🚆', 'Trenes en directo', ''] };
const hasPoints = (k) => !!(D.points && Array.isArray(D.points[k]) && D.points[k].length);
const hasTrains = () => !!(D.shapes && D.shapes.from_world && isNum(D.shapes.from_world.s));
const phone = () => matchMedia('(max-width:760px)').matches;
let PATHS, BBOX, CANARY, colors, palette = [];
const map = $('map'), cv = $('cv'), cvt = $('cvt'), gB = cv.getContext('2d'), gT = cvt.getContext('2d'), ov = $('ov'), tip = $('tip');
let W = 0, H = 0, dpr = 1, raf = 0;
const view = { k: 1, cx: 500, cy: 460 };
function pads() {
  if (phone()) { const open = $('panel').classList.contains('open'); return { l: 0, r: 0, t: 40, b: (open ? H * 0.45 - 20 : 48) + 110 }; }
  return { l: 0, r: 384, t: 4, b: 128 };
}
function frame() { const p = pads(); const fw = W - p.l - p.r, fh = H - p.t - p.b; return { ox: p.l + fw / 2, oy: p.t + fh / 2, s0: Math.min(fw / SW, fh / SH) }; }
const scale = () => frame().s0 * view.k;
function toScreen(x, y) { const f = frame(), s = f.s0 * view.k; return [(x - view.cx) * s + f.ox, (y - view.cy) * s + f.oy]; }
function toMap(px, py) { const f = frame(), s = f.s0 * view.k; return [(px - f.ox) / s + view.cx, (py - f.oy) / s + view.cy]; }
function clamp() {
  view.k = Math.max(1, Math.min(60, view.k));
  view.cx = Math.max(0, Math.min(SW, view.cx)); view.cy = Math.max(0, Math.min(SH, view.cy));
  if (view.k === 1) { view.cx = SW / 2; view.cy = SH / 2; }
}
function setT(g) { const f = frame(), s = f.s0 * view.k; g.setTransform(dpr * s, 0, 0, dpr * s, dpr * (f.ox - view.cx * s), dpr * (f.oy - view.cy * s)); }
function visible(i) {
  const o = i * 4, [x0, y0] = toScreen(BBOX[o], BBOX[o + 1]), [x1, y1] = toScreen(BBOX[o + 2], BBOX[o + 3]);
  return x1 >= -2 && x0 <= W + 2 && y1 >= -2 && y0 <= H + 2;
}
function drawBase() {
  gB.setTransform(dpr, 0, 0, dpr, 0, 0); gB.clearRect(0, 0, W, H); setT(gB);
  const s = scale(); gB.lineJoin = 'round';
  const groups = palette.map(() => []);
  for (let i = 0; i < N; i++) if (PATHS[i] && visible(i)) groups[colors[i]].push(i);
  const edge = view.k >= 3 ? 'rgba(255,255,255,.75)' : null;
  groups.forEach((list, k) => {
    gB.fillStyle = palette[k]; gB.strokeStyle = edge || palette[k]; gB.lineWidth = edge ? 0.5 / s : 0.6 / s;
    list.forEach((i) => { gB.fill(PATHS[i]); gB.stroke(PATHS[i]); });
  });
  gB.fillStyle = 'rgba(255,255,255,.5)'; gB.fillRect(CANARY[0], CANARY[1], CANARY[2] - CANARY[0], CANARY[3] - CANARY[1]);
  gB.strokeStyle = css('--muted', '#5b6b68'); gB.lineWidth = 1 / s; gB.strokeRect(CANARY[0], CANARY[1], CANARY[2] - CANARY[0], CANARY[3] - CANARY[1]);
  gB.fillStyle = css('--muted', '#5b6b68'); gB.font = '600 ' + 11 / s + 'px system-ui, sans-serif'; gB.textBaseline = 'top';
  gB.fillText('Canarias', CANARY[0] + 5 / s, CANARY[1] + 4 / s);
}
let hover = null;
function outline(i, w, color) {
  const s = scale(); gT.lineJoin = 'round';
  gT.lineWidth = (w + 2.5) / s; gT.strokeStyle = '#fff'; gT.stroke(PATHS[i]);
  gT.lineWidth = w / s; gT.strokeStyle = color; gT.stroke(PATHS[i]);
  const o = i * 4, sw = (BBOX[o + 2] - BBOX[o]) * s, sh = (BBOX[o + 3] - BBOX[o + 1]) * s;
  if (Math.max(sw, sh) < 14) {
    const c = CENT[CODES[i]]; if (!c) return;
    gT.beginPath(); gT.arc(c[0], c[1], 10 / s, 0, 6.2832); gT.lineWidth = 4 / s; gT.strokeStyle = '#fff'; gT.stroke();
    gT.lineWidth = 2.2 / s; gT.strokeStyle = color; gT.stroke();
  }
}
function drawTop() {
  gT.setTransform(dpr, 0, 0, dpr, 0, 0); gT.clearRect(0, 0, W, H); setT(gT);
  if (hover != null && hover !== st.sel && PATHS[hover]) outline(hover, 1.4, css('--ink', '#16211f'));
  if (st.sel != null && PATHS[st.sel]) outline(st.sel, 2.4, css('--b', '#b45309'));
  drawTrains();
}
/* city labels */
let LABELS = [], MARKS = [];
const MAX_LABELS = 90;
function labelLimit() { const k = view.k; return Math.round(k <= 1 ? 14 : k <= 2 ? 14 + (k - 1) * 26 : k <= 4 ? 40 + (k - 2) * 25 : 90); }
function buildLabels() {
  const top = ROWS.map((r, i) => [r[4] || 0, i]).sort((a, b) => b[0] - a[0]).slice(0, MAX_LABELS).map((x) => x[1]);
  LABELS = top.map((i) => {
    const el = document.createElement('button'); el.className = 'pill'; el.type = 'button'; ov.appendChild(el);
    el.addEventListener('click', () => select(CODES[i]));
    return { i, el, w: 0 };
  });
}
function updateLabels() {
  const key = st.key, b = breaks(key);
  LABELS.forEach((L) => {
    const v = val(L.i, key), k = !isNum(v) ? 5 : bucketOf(v, b);
    L.el.innerHTML = `<i style="background:${palette[k]}"></i>${esc(ROWS[L.i][1])}<span>· ${esc(fmt(v, key))}</span>`;
    L.el.style.display = ''; L.w = L.el.offsetWidth; L.el.classList.toggle('on', st.sel === L.i);
  });
}
function bucketOf(v, b) { if (!isNum(v)) return 5; let k = 0; for (let i = 0; i < 4; i++) if (v >= b[i]) k++; return k; }
function overlapsUi(x0, y0, x1, y1) {
  const m = map.getBoundingClientRect();
  for (const el of [document.querySelector('.dock'), $('panel'), $('note'), $('layers')]) {
    if (!el || el.hidden) continue; const r = el.getBoundingClientRect(); if (!r.width) continue;
    if (x1 > r.left - m.left && x0 < r.right - m.left && y1 > r.top - m.top && y0 < r.bottom - m.top) return true;
  }
  return false;
}
function placeLabels() {
  const placed = [], limit = labelLimit(); let shown = 0;
  LABELS.forEach((L) => {
    const c = CENT[CODES[L.i]]; let show = false, x = 0, y = 0;
    if (c && shown < limit) {
      [x, y] = toScreen(c[0], c[1]); y -= 20; const hw = L.w / 2 + 2, hh = 14;
      show = x > hw && y > hh && x < W - hw && y < H - hh && !overlapsUi(x - hw, y - 12, x + hw, y + 12);
      if (show) for (const q of placed) if (Math.abs(q.x - x) < q.hw + hw && Math.abs(q.y - y) < 14 + hh) { show = false; break; }
      if (show) { placed.push({ x, y, hw }); shown++; }
    }
    L.el.style.display = show ? '' : 'none';
    if (show) L.el.style.transform = `translate(${Math.round(x - L.w / 2)}px,${Math.round(y - 12)}px)`;
  });
}
/* layers */
function buildMarks() {
  for (const kind of ['airports', 'ports', 'heritage']) {
    if (!hasPoints(kind)) continue;
    for (const p of D.points[kind]) {
      if (!isNum(p.x) || !isNum(p.y)) continue;
      const el = document.createElement('div'); el.className = 'mk pt pt-' + kind; el.textContent = LAYER_DEF[kind][2]; el.style.display = 'none';
      el.tabIndex = -1; el.setAttribute('role', 'img'); el.setAttribute('aria-label', p.name);
      const html = `<b>${esc(p.name)}</b>${p.city ? `<span>${esc(p.city)}</span>` : ''}`;
      const show = () => { const r = el.getBoundingClientRect(), m = map.getBoundingClientRect(); showTip(html, r.left - m.left + 14, r.top - m.top + 14); };
      el.addEventListener('mouseenter', show); el.addEventListener('click', (e) => { e.stopPropagation(); show(); });
      el.addEventListener('mouseleave', () => { tip.hidden = true; });
      ov.appendChild(el); MARKS.push({ kind, x: p.x, y: p.y, el });
    }
  }
}
function showTip(html, x, y) {
  tip.innerHTML = html; tip.hidden = false;
  tip.style.left = Math.max(4, Math.min(x, W - tip.offsetWidth - 4)) + 'px'; tip.style.top = Math.max(4, Math.min(y, H - tip.offsetHeight - 4)) + 'px';
}
function placeMarks() {
  for (const m of MARKS) {
    if (!st.layers[m.kind]) { m.el.style.display = 'none'; continue; }
    const [x, y] = toScreen(m.x, m.y);
    const out = x < 0 || y < 0 || x > W || y > H || (!phone() && x > W - 372);
    m.el.style.display = out ? 'none' : ''; m.el.style.transform = `translate(${x}px,${y}px)`;
  }
}
/* live trains (Renfe, through the public relay); positions are projected with the shared lon/lat module, then mapped into the box */
const TRAIN_EVERY = 30000;
const T = { items: [], err: false, loading: false, timer: 0, busy: false, updated: 0 };
const HHMM = (ms) => new Date(ms).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
function toBox(wx, wy) {
  const sh = D.shapes, bb = sh.canarias_world_bbox, can = sh.from_world_canarias;
  const f = can && Array.isArray(bb) && wx >= bb[0] && wx <= bb[2] && wy >= bb[1] && wy <= bb[3] ? can : sh.from_world;
  return [f.s * wx + f.dx, f.s * wy + f.dy];
}
function trainChip() {
  const el = $('note');
  if (!st.layers.trains) { el.hidden = true; return; }
  el.hidden = false;
  el.textContent = T.err ? 'No llegan los datos de trenes ahora.' : T.loading ? 'Cargando trenes…' : `${NF0.format(T.items.length)} trenes ahora · ${HHMM(T.updated)} · Renfe (CC BY 4.0)`;
}
async function pollTrains() {
  T.timer = 0; if (!st.layers.trains || document.hidden || T.busy) return;
  T.busy = true; const ctl = new AbortController(), kill = setTimeout(() => ctl.abort(), 15000);
  try {
    if (!PROJ_P) PROJ_P = loadProjection(new URL('../data/projection.json', import.meta.url).href);
    const proj = await PROJ_P;
    const r = await fetch(`${liveUrl()}/trains`, { signal: ctl.signal, cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json(); if (!Array.isArray(d.trains)) throw new Error('bad payload');
    const out = [];
    for (const t of d.trains) {
      if (!isNum(t.lat) || !isNum(t.lon) || proj.hidden(t.lon, t.lat)) continue;
      const [wx, wy] = proj.project(t.lon, t.lat), [x, y] = toBox(wx, wy);
      if (isNum(x) && isNum(y)) out.push({ x, y, t });
    }
    T.items = out; T.err = false; T.updated = Date.parse(d.updated) || Date.now();
  } catch (_) { T.items = []; T.err = true; }
  finally { clearTimeout(kill); T.busy = false; T.loading = false; }
  trainChip(); schedule(true);
  if (st.layers.trains && !document.hidden && !T.timer) T.timer = setTimeout(pollTrains, TRAIN_EVERY);
}
function setTrains(on) {
  st.layers.trains = on; clearTimeout(T.timer); T.timer = 0;
  if (on) { T.loading = true; T.items = []; T.err = false; trainChip(); pollTrains(); } else { T.items = []; trainChip(); schedule(true); }
}
document.addEventListener('visibilitychange', () => { if (!st.layers.trains) return; clearTimeout(T.timer); T.timer = 0; if (!document.hidden) pollTrains(); });
const lateTrain = (t) => isNum(t.delay) && t.delay >= 300;
function drawTrains() {
  if (!st.layers.trains || !T.items.length) return;
  gT.setTransform(dpr, 0, 0, dpr, 0, 0);
  for (const it of T.items) {
    const [x, y] = toScreen(it.x, it.y);
    if (x < -8 || y < -8 || x > W + 8 || y > H + 8 || (!phone() && x > W - 372)) continue;
    gT.beginPath(); gT.arc(x, y, 4.5, 0, 6.2832); gT.fillStyle = lateTrain(it.t) ? '#d98a0b' : '#0f766e'; gT.fill(); gT.lineWidth = 1.5; gT.strokeStyle = '#fff'; gT.stroke();
  }
  gT.setTransform(dpr, 0, 0, dpr, 0, 0);
}
function trainAt(px, py) {
  if (!st.layers.trains) return null; let best = null, bd = 100;
  for (const it of T.items) { const [x, y] = toScreen(it.x, it.y), d = (x - px) ** 2 + (y - py) ** 2; if (d < bd) { bd = d; best = it; } }
  return best;
}
function trainTip(t) {
  const kind = t.net === 'ld' ? 'Larga distancia' : 'Cercanías', name = t.label || t.trip;
  const d = t.delay, delay = !isNum(d) ? 'retraso sin dato' : d < 60 ? 'a su hora' : `${NF0.format(Math.round(d / 60))} min de retraso`;
  return `<b>${esc(name ? kind + ' ' + name : kind)}</b><span>${esc(delay)}</span>`;
}
function redraw() { drawBase(); drawTop(); placeLabels(); placeMarks(); }
function schedule(full) { if (raf) return; raf = requestAnimationFrame(() => { raf = 0; if (full) redraw(); else { drawTop(); } }); }
function resize() {
  const w = map.clientWidth, h = map.clientHeight; if (!w || !colors) return;
  dpr = Math.min(window.devicePixelRatio || 1, 2); W = w; H = h;
  [cv, cvt].forEach((c) => { c.width = Math.round(W * dpr); c.height = Math.round(H * dpr); c.style.width = W + 'px'; c.style.height = H + 'px'; });
  clamp(); redraw();
}
/* hit test */
const probe = document.createElement('canvas').getContext('2d');
function hitAt(px, py) {
  const [x, y] = toMap(px, py);
  for (let i = 0; i < N; i++) { const o = i * 4; if (x < BBOX[o] || x > BBOX[o + 2] || y < BBOX[o + 1] || y > BBOX[o + 3] || !PATHS[i]) continue; if (probe.isPointInPath(PATHS[i], x, y)) return i; }
  let best = -1, bd = 144;
  for (let i = 0; i < N; i++) { const c = CENT[CODES[i]]; if (!c) continue; const q = toScreen(c[0], c[1]), dx = q[0] - px, dy = q[1] - py, dd = dx * dx + dy * dy; if (dd < bd) { bd = dd; best = i; } }
  return best;
}
function zoomAt(k, px, py) {
  const [mx, my] = toMap(px, py); view.k = k; clamp();
  const f = frame(), s = f.s0 * view.k; view.cx = mx - (px - f.ox) / s; view.cy = my - (py - f.oy) / s; clamp();
}
const ptrs = new Map(); let g = null, pinch = null;
const rel = (e) => { const r = cvt.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
cvt.addEventListener('pointerdown', (e) => {
  const p = rel(e); ptrs.set(e.pointerId, p); try { cvt.setPointerCapture(e.pointerId); } catch (_) {}
  if (ptrs.size === 1) g = { x: p[0], y: p[1], cx: view.cx, cy: view.cy, moved: false };
  else if (ptrs.size === 2) { const [a, b] = [...ptrs.values()]; const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]; pinch = { d: Math.hypot(a[0] - b[0], a[1] - b[1]) || 1, k: view.k, mid, mp: toMap(mid[0], mid[1]) }; if (g) g.moved = true; }
});
cvt.addEventListener('pointermove', (e) => {
  const p = rel(e); if (ptrs.has(e.pointerId)) ptrs.set(e.pointerId, p);
  if (ptrs.size === 2 && pinch) {
    const [a, b] = [...ptrs.values()]; const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    view.k = pinch.k * (Math.hypot(a[0] - b[0], a[1] - b[1]) / pinch.d); clamp();
    const f = frame(), s = f.s0 * view.k; view.cx = pinch.mp[0] - (mid[0] - f.ox) / s; view.cy = pinch.mp[1] - (mid[1] - f.oy) / s; clamp(); schedule(true); return;
  }
  if (g && ptrs.size === 1 && (e.pointerType !== 'mouse' || (e.buttons & 1))) {
    const dx = p[0] - g.x, dy = p[1] - g.y; if (Math.abs(dx) + Math.abs(dy) > 6) g.moved = true;
    if (g.moved && view.k > 1) { const s = scale(); view.cx = g.cx - dx / s; view.cy = g.cy - dy / s; clamp(); hover = null; tip.hidden = true; schedule(true); }
    return;
  }
  if (e.pointerType === 'mouse') {
    const tr = trainAt(p[0], p[1]);
    if (tr) { if (hover != null) { hover = null; schedule(false); } cvt.style.cursor = 'pointer'; showTip(trainTip(tr.t), p[0] + 14, p[1] + 14); return; }
    const i = hitAt(p[0], p[1]), h = i >= 0 ? i : null;
    if (h !== hover) { hover = h; cvt.style.cursor = h == null ? 'default' : 'pointer'; schedule(false); }
    if (h == null) tip.hidden = true; else {
      showTip(`<b>${esc(ROWS[h][1])}</b><span>${esc(SHORT[st.key])}: ${esc(fmt(val(h, st.key), st.key) + unitTail(st.key))}</span>`, p[0] + 14, p[1] + 14);
    }
  }
});
const endp = (e) => {
  const p = rel(e), was = ptrs.size; ptrs.delete(e.pointerId);
  if (was === 2) { pinch = null; g = null; return; } if (!g) return;
  const tap = !g.moved && Math.abs(p[0] - g.x) + Math.abs(p[1] - g.y) <= 6; g = null;
  if (e.type === 'pointercancel' || !tap) return;
  const tr = trainAt(p[0], p[1]); if (tr) { showTip(trainTip(tr.t), p[0] + 14, p[1] + 14); return; }
  const i = hitAt(p[0], p[1]); if (i >= 0) select(CODES[i]);
};
cvt.addEventListener('pointerup', endp); cvt.addEventListener('pointercancel', endp);
cvt.addEventListener('pointerleave', (e) => { if (e.pointerType === 'mouse') { hover = null; tip.hidden = true; schedule(false); } });
cvt.addEventListener('wheel', (e) => { e.preventDefault(); const p = rel(e); zoomAt(view.k * (e.deltaY < 0 ? 1.25 : 0.8), p[0], p[1]); redraw(); }, { passive: false });
document.querySelector('.zoom').addEventListener('click', (e) => {
  const b = e.target.closest('[data-z]'); if (!b) return; const z = b.dataset.z; const f = frame();
  if (z === 'reset') { view.k = 1; clamp(); } else zoomAt(view.k * (z === 'in' ? 1.8 : 1 / 1.8), f.ox, f.oy); redraw();
});
new ResizeObserver(resize).observe(map);

/* indicator */
function setIndicator(key) {
  st.key = key; if (key !== 'income') { st.yi = LAST; stopPlay(); }
  const b = breaks(key), v = values(key);
  palette = [1, 2, 3, 4, 5].map((n) => css('--seq-' + n, '#888')).concat([css('--nodata', '#d6d2c8')]);
  colors = new Uint8Array(N); for (let i = 0; i < N; i++) colors[i] = Number.isNaN(v[i]) ? 5 : bucketOf(v[i], b);
  renderBar(); renderLegend(); renderNat(); renderYear(); updateLabels(); renderPanel();
  cvt.setAttribute('aria-label', `Mapa de España por municipios: ${IND_BY[key].label}${yearOn(key) ? ', ' + YEARS[st.yi] : ''}. Pulsa un municipio para abrir su ficha.`);
  if (W) redraw();
  if (!playT) writeHash();
}
function renderBar() {
  const mainBtns = MAIN.map((k) => `<button class="chip${st.key === k ? ' on' : ''}" data-k="${k}">${IND_BY[k].icon} ${SHORT[k]}</button>`).join('');
  const other = !MAIN.includes(st.key);
  $('bar').innerHTML = mainBtns + `<button class="chip${other ? ' on' : ''}" id="more" aria-expanded="false">${other ? IND_BY[st.key].icon + ' ' + SHORT[st.key] : 'Más datos'} ▾</button>`;
}
function renderLegend() {
  const key = st.key, b = breaks(key), f = (v) => fmtS(v, key);
  const labs = [`< ${f(b[0])}`, `${f(b[0])} a ${f(b[1])}`, `${f(b[1])} a ${f(b[2])}`, `${f(b[2])} a ${f(b[3])}`, `≥ ${f(b[3])}`, NA];
  const unit = key === 'density' ? ' hab./km²' : key === 'household' ? ' personas' : key === 'age_mean' ? ' años' : unitTail(key);
  $('legend').innerHTML = labs.map((t, k) => `<li><i style="background:${palette[k]}"></i>${esc(t)}${k === 4 ? esc(unit) : ''}</li>`).join('');
}
function renderNat() {
  const key = st.key, nv = nationOf(key).value;
  const pop = ROWS.reduce((s, r) => s + (r[4] || 0), 0) / 1e6;
  $('nat').innerHTML = `<span><b>${NF1.format(pop)} M</b> habitantes</span><span><b>${NF0.format(N)}</b> municipios</span><span title="${esc(natWord(key))}">${esc(SHORT[key])}${yearOn(key) ? ' ' + YEARS[st.yi] : ''}: <b>${esc(fmt(nv, key) + unitTail(key))}</b> · ${esc(isPartial(key) ? `media de ${NF0.format(nWithData(key))}` : natWord(key))}</span>`;
}
/* year control (income only) */
let playT = 0;
function stopPlay() { clearInterval(playT); playT = 0; const b = $('play'); if (b) { b.textContent = '▶'; b.setAttribute('aria-label', 'Reproducir los años'); } }
function renderYear() {
  const on = st.key === 'income'; $('yr').hidden = !on; if (!on) return;
  $('yrbig').textContent = YEARS[st.yi]; $('yrr').value = String(st.yi);
}
function setYear(yi) { st.yi = yi; setIndicator('income'); }
function togglePlay() {
  if (playT) { stopPlay(); return; }
  if (st.yi >= LAST) st.yi = -1;
  $('play').textContent = '❚❚'; $('play').setAttribute('aria-label', 'Parar');
  const step = () => { if (st.yi >= LAST) { stopPlay(); return; } st.yi++; const keep = playT; setIndicator('income'); playT = keep; if (st.yi >= LAST) stopPlay(); };
  step(); playT = setInterval(step, 1000);
}
/* panel */
function trendHTML(code) {
  const s = D.series.munis[code], n = D.series.nation; if (!s || s.filter(isNum).length < 2) return '';
  const w = 300, h = 90, x0 = 8, x1 = w - 8, y0 = 26, y1 = h - 22;
  const all = s.concat(n).filter(isNum), lo = Math.min(...all), hi = Math.max(...all);
  const X = (i) => x0 + (i * (x1 - x0)) / (YEARS.length - 1), Y = (v) => y1 - ((v - lo) / (hi - lo || 1)) * (y1 - y0);
  const line = (a) => { let d = '', pen = false; a.forEach((v, i) => { if (!isNum(v)) { pen = false; return; } d += (pen ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(v).toFixed(1); pen = true; }); return d; };
  const li = s.length - 1 - [...s].reverse().findIndex(isNum), fi = s.findIndex(isNum);
  return `<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="Renta por persona de ${YEARS[0]} a ${YEARS[LAST]}"><path d="${line(n)}" fill="none" stroke="#a9bdb8" stroke-width="2" stroke-dasharray="4 3"/><path d="${line(s)}" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linejoin="round"/><circle cx="${X(li)}" cy="${Y(s[li])}" r="4" fill="var(--accent)" stroke="#fff" stroke-width="2"/><text x="${x0}" y="${h - 6}">${YEARS[fi]}</text><text x="${x1}" y="${h - 6}" text-anchor="end">${YEARS[li]}</text><text x="${X(li) - 8}" y="${Y(s[li]) - 8}" text-anchor="end" style="fill:var(--ink);font-weight:600">${esc(NF0.format(s[li]))} €</text></svg><div class="cap">Renta por persona ${YEARS[fi]}-${YEARS[li]}. Línea discontinua: media de España.</div>`;
}
function renderPanel() {
  const key = st.key, ind = IND_BY[key], body = $('pbody'), tt = $('ptitle');
  if (st.sel == null) {
    tt.textContent = 'España de un vistazo';
    const nv = nationOf(key).value;
    const head = key === 'income' && !yearOn(key) && D.findings && D.findings.income ? D.findings.income[0] : `${ind.label}: ${natWord(key)}, ${fmt(nv, key)}${unitTail(key)}${yearOn(key) ? ' en ' + YEARS[st.yi] : ''}`.replace(/\.?$/, '.');
    const list = D.provinces.map((p) => ({ n: p.name, v: p.values[key] })).filter((x) => isNum(x.v)).sort((a, b) => b.v - a.v);
    const hi = list.slice(0, 5), lo = list.slice(-5).reverse(), mx = Math.max(...list.map((x) => Math.abs(x.v))) || 1;
    const rows = (a, cls) => a.map((x) => `<li class="row"><span>${esc(x.n)}</span><div class="track ${cls}"><i style="width:${Math.max(3, Math.abs(x.v) / mx * 100)}%"></i></div><span class="row-v">${esc(fmt(x.v, key))}</span></li>`).join('');
    const lists = partial(key) || yearOn(key) ? (partial(key) ? `<p class="cap">Este dato solo existe para ${esc(NF0.format(nWithData(key)))} municipios, no para todos. Por eso no hay lista de provincias.</p>` : '') : `<div class="bars"><h3>Las 5 provincias con más</h3><ul>${rows(hi, 'hi')}</ul><h3>Las 5 con menos</h3><ul>${rows(lo, 'lo')}</ul></div>`;
    body.innerHTML = `<div class="eyebrow">${ind.icon} ${esc(SHORT[key])}</div><h2 class="p-h">${esc(head)}</h2><p class="p-sub">Haz clic en un municipio o en una etiqueta para ver su ficha.</p>${lists}`;
    $('pcar').textContent = '▴'; renderAttr(); return;
  }
  const r = ROWS[st.sel], code = r[0], p = PROV[r[2]], v = val(st.sel, key), nat = nationOf(key).value;
  tt.textContent = r[1];
  const others = ['income', 'age_mean', 'growth', 'density'].filter((k) => k !== key).slice(0, 2);
  body.innerHTML = `<button class="x" id="xbtn" aria-label="Volver a España de un vistazo">×</button>
  <h2 class="name">${esc(r[1])}</h2><p class="meta">${esc(p ? p.name : '')} · <b>${esc(NF0.format(r[4] || 0))}</b> habitantes</p>
  <h3 class="m-lab">${ind.icon} ${esc(ind.label)}</h3><div class="m-val${isNum(v) ? '' : ' miss'}">${esc(fmt(v, key) + (isNum(v) ? unitTail(key) : ''))}</div>
  <p class="m-sent">${esc(sentenceFor(key, v))}</p>${stripHTML(key, v)}<p class="cap">El punto es este municipio. La barra es donde están casi todos.</p>
  <ul class="kv"><li><span>${esc(NatWord(key))}</span><b>${esc(fmt(nat, key) + unitTail(key))}</b></li>${others.map((k) => `<li><span>${esc(SHORT[k])}</span><b>${esc(fmt(val(st.sel, k), k) + unitTail(k))}</b></li>`).join('')}</ul>
  ${trendHTML(code)}<a class="full" id="fullbtn" href="municipio.html#m=${esc(code)}&i=${esc(key)}">Ver ficha completa</a>`;
  $('xbtn').onclick = () => select(null); renderAttr();
}
function renderAttr() {
  const pts = LAYER_KEYS.some((k) => k !== 'trains' && st.layers[k]);
  $('attr').textContent = [D.meta && D.meta.sources, pts && D.meta && D.meta.points_sources].filter(Boolean).join(' ');
}
function select(code) {
  st.sel = code == null ? null : IDX[code]; hover = null;
  if (st.sel != null) {
    const c = CENT[CODES[st.sel]]; if (c) { view.k = 4; view.cx = c[0]; view.cy = c[1]; clamp(); }
    if (phone()) $('panel').classList.add('open');
  }
  updateLabels(); renderPanel(); resize(); writeHash();
}
/* state in the hash: m = municipality, i = indicator, ly = layers */
let booting = true;
function writeHash() {
  if (booting) return;
  const p = new URLSearchParams();
  if (st.sel != null) p.set('m', CODES[st.sel]);
  if (st.key !== 'income' || st.sel != null) p.set('i', st.key);
  const ly = LAYER_KEYS.filter((k) => st.layers[k]); if (ly.length) p.set('ly', ly.join(','));
  const h = p.toString();
  try { history.replaceState(null, '', location.pathname + location.search + (h ? '#' + h : '')); } catch (_) { /* sandboxed frame */ }
}
function layerAvail(k) { return k === 'trains' ? hasTrains() : hasPoints(k); }
function applyHash() {
  const p = new URLSearchParams(location.hash.replace(/^#/, '')), i = p.get('i'), m = p.get('m'), ly = (p.get('ly') || '').split(',');
  const key = i && IND_BY[i] ? i : 'income';
  if (key !== st.key) setIndicator(key);
  for (const k of LAYER_KEYS) {
    const on = ly.includes(k) && layerAvail(k); const cb = document.querySelector(`#lmenu [data-l="${k}"]`); if (cb) cb.checked = on;
    if (k === 'trains') { if (on !== st.layers.trains) setTrains(on); } else st.layers[k] = on;
  }
  renderAttr(); placeMarks();
  if (m && IDX[m] != null) { if (st.sel !== IDX[m]) select(m); } else if (!m && st.sel != null) { st.sel = null; updateLabels(); renderPanel(); redraw(); }
}
window.addEventListener('hashchange', applyHash);

/* search */
function search(q) {
  const nq = norm(q.trim()); if (!nq) return []; const out = [];
  ROWS.forEach((r, i) => { const n = norm(r[1]); let rank = 9; if (n.startsWith(nq)) rank = 0; else if (n.includes(' ' + nq) || n.includes('-' + nq) || n.includes('/' + nq)) rank = 1; else if (n.includes(nq)) rank = 2; if (rank < 9) out.push([rank, -(r[4] || 0), i]); });
  return out.sort((a, b) => a[0] - b[0] || a[1] - b[1]).slice(0, 8).map((x) => x[2]);
}
const input = $('q'), qlist = $('q-list'); let results = [];
input.addEventListener('input', () => {
  results = search(input.value);
  if (!input.value.trim()) { qlist.hidden = true; return; }
  qlist.innerHTML = results.length ? results.map((i) => `<li data-i="${i}"><b>${esc(ROWS[i][1])}</b><span>${esc(PROV[ROWS[i][2]] ? PROV[ROWS[i][2]].name : '')}</span></li>`).join('') : '<li class="muted">No encontramos ese municipio</li>';
  qlist.hidden = false;
});
input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && results.length) { qlist.hidden = true; input.value = ''; select(CODES[results[0]]); input.blur(); } if (e.key === 'Escape') qlist.hidden = true; });
qlist.addEventListener('pointerdown', (e) => { const li = e.target.closest('li[data-i]'); if (li) { e.preventDefault(); qlist.hidden = true; input.value = ''; select(CODES[+li.dataset.i]); } });
/* bar, menus, layers */
$('bar').addEventListener('click', (e) => {
  const b = e.target.closest('.chip'); if (!b) return;
  if (b.id === 'more') {
    const m = $('mmenu'); const open = m.hidden;
    if (open) {
      m.innerHTML = IND.filter((i) => !MAIN.includes(i.key)).map((i) => `<button class="it${st.key === i.key ? ' on' : ''}" data-k="${i.key}">${i.icon} ${esc(SHORT[i.key])}</button>`).join('');
      m.hidden = false; const r = b.getBoundingClientRect(); m.style.left = Math.max(8, Math.min(innerWidth - m.offsetWidth - 8, r.right - m.offsetWidth)) + 'px'; m.style.top = (r.top - m.offsetHeight - 8) + 'px';
    } else m.hidden = true; b.setAttribute('aria-expanded', String(open)); return;
  }
  $('mmenu').hidden = true; setIndicator(b.dataset.k);
});
$('mmenu').addEventListener('click', (e) => { const b = e.target.closest('[data-k]'); if (!b) return; $('mmenu').hidden = true; setIndicator(b.dataset.k); });
$('layers').addEventListener('click', () => { const m = $('lmenu'); m.hidden = !m.hidden; $('layers').setAttribute('aria-expanded', String(!m.hidden)); });
$('lmenu').addEventListener('change', (e) => { const l = e.target.dataset.l; if (!l) return; if (l === 'trains') setTrains(e.target.checked); else st.layers[l] = e.target.checked; tip.hidden = true; renderAttr(); placeMarks(); updateLabelsPlace(); writeHash(); });
function updateLabelsPlace() { placeLabels(); }
const mm = $('moremenu');
$('moreb').addEventListener('click', () => { mm.hidden = !mm.hidden; $('moreb').setAttribute('aria-expanded', String(!mm.hidden)); });
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  mm.hidden = true; $('moreb').setAttribute('aria-expanded', 'false'); $('mmenu').hidden = true; $('lmenu').hidden = true; $('layers').setAttribute('aria-expanded', 'false'); qlist.hidden = true; tip.hidden = true;
  if (st.sel != null) select(null);
});
document.addEventListener('click', (e) => {
  if (!e.target.closest('#moreb') && !e.target.closest('#moremenu')) { mm.hidden = true; $('moreb').setAttribute('aria-expanded', 'false'); }
  if (!e.target.closest('#more') && !e.target.closest('#mmenu')) $('mmenu').hidden = true;
  if (!e.target.closest('#layers') && !e.target.closest('#lmenu')) { $('lmenu').hidden = true; $('layers').setAttribute('aria-expanded', 'false'); }
  if (!e.target.closest('.search')) qlist.hidden = true;
});
$('yrr').addEventListener('input', (e) => { stopPlay(); setYear(+e.target.value); });
$('play').addEventListener('click', togglePlay);
$('phead').addEventListener('click', () => { const p = $('panel'); p.classList.toggle('open'); $('pcar').textContent = p.classList.contains('open') ? '▾' : '▴'; resize(); });
window.addEventListener('resize', () => resize());

async function boot() {
  const r = await fetch(new URL('../data/simple.json', import.meta.url)); D = await r.json();
  ROWS = D.munis.rows; N = ROWS.length; D.munis.cols.forEach((c, i) => (COL[c] = i));
  IND = D.indicators; IND.forEach((i) => (IND_BY[i.key] = i)); D.provinces.forEach((p) => (PROV[p.code] = p));
  CODES = ROWS.map((r) => r[0]); CODES.forEach((c, i) => (IDX[c] = i));
  CENT = D.munis_centroid; SW = D.shapes.w; SH = D.shapes.h; YEARS = D.series.years; LAST = YEARS.length - 1;
  PATHS = new Array(N); BBOX = new Float32Array(N * 4); const re = /-?\d+(?:\.\d+)?/g;
  for (let i = 0; i < N; i++) {
    const d = D.shapes.munis[CODES[i]]; if (!d) { PATHS[i] = null; BBOX.set([1e9, 1e9, -1e9, -1e9], i * 4); continue; }
    PATHS[i] = new Path2D(d); const nums = d.match(re); let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    for (let k = 0; k + 1 < nums.length; k += 2) { const x = +nums[k], y = +nums[k + 1]; if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
    BBOX.set([x0, y0, x1, y1], i * 4);
  }
  const a = D.provinces_bbox['35'], b = D.provinces_bbox['38'], pad = 8;
  CANARY = [Math.min(a[0], b[0]) - pad, Math.min(a[1], b[1]) - pad, Math.max(a[2], b[2]) + pad, Math.max(a[3], b[3]) + pad];
  buildLabels(); buildMarks(); buildLayerMenu(); st.yi = LAST; setIndicator('income'); resize(); applyHash(); booting = false; writeHash();
}
function buildLayerMenu() {
  const items = LAYER_KEYS.filter(layerAvail);
  $('lmenu').innerHTML = items.map((k) => `<label><input type="checkbox" data-l="${k}"> ${LAYER_DEF[k][0]} ${LAYER_DEF[k][1]}</label>`).join('');
  $('layers').hidden = !items.length;
}
boot().catch(() => { document.body.insertAdjacentHTML('beforeend', '<p class="fatal">No se pudieron cargar los datos. Prueba de nuevo en un rato.</p>'); });
