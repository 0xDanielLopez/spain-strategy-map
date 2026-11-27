// "España, municipio a municipio": simple interface. ES module, no dependencies.
// State lives in location.hash: i = indicator, m = municipality code, y = year, h = highlighted municipality.

const NF0 = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 0, useGrouping: 'always' });
const NF1 = new Intl.NumberFormat('es-ES', { minimumFractionDigits: 1, maximumFractionDigits: 1, useGrouping: 'always' });
const NA = 'sin dato';
// Short noun phrase per indicator for headings; unknown keys fall back to the lower-cased label.
const NOUN = { income: 'renta', age_mean: 'edad media', growth: 'crecimiento', density: 'densidad', elderly: 'mayores de 65', foreign: 'población extranjera', household: 'personas por hogar', poverty: 'población bajo el umbral de pobreza', higher_education: 'estudios superiores', non_primary: 'viviendas no principales', tourist: 'viviendas turísticas', born_abroad: 'nacidos en el extranjero', immigration: 'llegadas desde el extranjero', crime_rate: 'infracciones penales' };
const nounOf = (ind) => NOUN[ind.key] || String(ind.label).toLowerCase();
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const norm = (s) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
const isNum = (v) => v != null && !Number.isNaN(v);

function fmt(v, key, f) {
  if (!isNum(v)) return NA;
  f = f || IND_BY[key].format;
  let s;
  if (f === 'eur') s = NF0.format(v) + ' €';
  else if (f === 'years') s = NF1.format(v) + ' años';
  else if (f === 'pct') s = NF1.format(v) + ' %';
  else if (f === 'int') s = NF0.format(v);
  else s = NF1.format(v);
  if (key === 'growth' && v > 0) s = '+' + s;
  if (key === 'density') s += ' hab./km²';
  if (key === 'household') s += ' personas';
  return s;
}
const signed = (n) => (n >= 0 ? '+' : '−') + NF0.format(Math.abs(n));

/* ---------- data ---------- */
let D, ROWS, N, COL = {}, IND = [], IND_BY = {}, PROV = {}, CODES = [], IDX = {}, CENT, SW, SH, YEARS, LAST;
const cache = { vals: {}, sorted: {}, breaks: {}, z: null };

function prepare(data) {
  D = data; ROWS = D.munis.rows; N = ROWS.length;
  D.munis.cols.forEach((c, i) => (COL[c] = i));
  IND = D.indicators; IND.forEach((i) => (IND_BY[i.key] = i));
  D.provinces.forEach((p) => (PROV[p.code] = p));
  CODES = ROWS.map((r) => r[0]); CODES.forEach((c, i) => (IDX[c] = i));
  CENT = D.munis_centroid; SW = D.shapes.w; SH = D.shapes.h;
  YEARS = D.series.years; LAST = YEARS.length - 1;
}

function values(key, yi) {
  const ck = key + '|' + yi;
  if (cache.vals[ck]) return cache.vals[ck];
  const a = new Float64Array(N);
  if (key === 'income' && yi !== LAST) {
    for (let i = 0; i < N; i++) { const s = D.series.munis[CODES[i]]; const v = s ? s[yi] : null; a[i] = v == null ? NaN : v; }
  } else {
    const c = COL[key];
    for (let i = 0; i < N; i++) { const v = ROWS[i][c]; a[i] = v == null ? NaN : v; }
  }
  return (cache.vals[ck] = a);
}
// Share of Spain's population that lives in municipalities with a value for this indicator.
// Under 90 % the figure is not "Spain's mean" (crime rate: only the larger municipalities), and the page says so.
const _cover = {};
function popCoverage(key) {
  if (_cover[key] == null) {
    let a = 0, all = 0; const c = COL[key], pc = COL.population;
    for (const r of ROWS) { const pop = r[pc] || 0; all += pop; if (isNum(r[c])) a += pop; }
    _cover[key] = all ? a / all : 1;
  }
  return _cover[key];
}
const isPartial = (key) => popCoverage(key) < 0.9;
const nWithData = (key) => ROWS.reduce((n, r) => n + (isNum(r[COL[key]]) ? 1 : 0), 0);
const natWord = (key) => (isPartial(key) ? `media de los ${NF0.format(nWithData(key))} municipios con dato` : 'media de España');
const NatWord = (key) => { const s = natWord(key); return s[0].toUpperCase() + s.slice(1); };
// Rates per 1,000 inhabitants carry no unit in fmt(): add it where a bare number would be unclear.
const unitTail = (key) => { const i = IND_BY[key]; return i && i.format === 'dec1' && key !== 'household' && i.unit ? ' ' + i.unit : ''; };
function sortedVals(key, yi) {
  const ck = key + '|' + yi;
  if (cache.sorted[ck]) return cache.sorted[ck];
  return (cache.sorted[ck] = Float64Array.from(values(key, yi).filter((v) => !Number.isNaN(v))).sort());
}
// Same colour breaks for every year: quintiles of the latest values.
function breaks(key) {
  if (cache.breaks[key]) return cache.breaks[key];
  const s = sortedVals(key, LAST), n = s.length;
  return (cache.breaks[key] = [0.2, 0.4, 0.6, 0.8].map((p) => s[Math.floor(p * n)]));
}
function bucketOf(v, b) {
  if (Number.isNaN(v)) return 5;
  let k = 0; for (let i = 0; i < 4; i++) if (v >= b[i]) k++;
  return k;
}
function lessCount(s, v) {
  let lo = 0, hi = s.length;
  while (lo < hi) { const m = (lo + hi) >> 1; if (s[m] < v) lo = m + 1; else hi = m; }
  return lo;
}
const yearOf = (key, yi) => (key === 'income' ? YEARS[yi] : IND_BY[key].year);
const natValue = (key, yi) => (key === 'income' && yi !== LAST ? D.series.nation[yi] : D.nation[key] ? D.nation[key].value : null);
function provValue(code, key, yi) {
  if (key === 'income' && yi !== LAST) { const s = D.series.provinces[code]; return s ? s[yi] : null; }
  const p = PROV[code]; return p ? p.values[key] : null;
}
function sourceOf(key, yi) {
  const s = IND_BY[key].source;
  return key === 'income' && yi !== LAST ? s.replace(/\d{4}\s*$/, String(YEARS[yi])) : s;
}

/* ---------- geometry ---------- */
let PATHS, BBOX, CANARY;
function prepareGeometry() {
  PATHS = new Array(N); BBOX = new Float32Array(N * 4);
  const re = /-?\d+(?:\.\d+)?/g;
  for (let i = 0; i < N; i++) {
    const d = D.shapes.munis[CODES[i]];
    if (!d) { PATHS[i] = null; BBOX.set([1e9, 1e9, -1e9, -1e9], i * 4); continue; }
    PATHS[i] = new Path2D(d);
    const nums = d.match(re); let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    for (let k = 0; k + 1 < nums.length; k += 2) {
      const x = +nums[k], y = +nums[k + 1];
      if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
    }
    BBOX.set([x0, y0, x1, y1], i * 4);
  }
  const a = D.provinces_bbox['35'], b = D.provinces_bbox['38'], pad = 8;
  CANARY = [Math.min(a[0], b[0]) - pad, Math.min(a[1], b[1]) - pad, Math.max(a[2], b[2]) + pad, Math.max(a[3], b[3]) + pad];
}

/* ---------- map component (canvas) ---------- */
const css = (n, fb) => getComputedStyle(document.documentElement).getPropertyValue(n).trim() || fb;

function createMap(wrap, opt) {
  const cvB = document.createElement('canvas'), cvT = document.createElement('canvas');
  cvB.className = 'cv'; cvT.className = 'cv';
  const tip = document.createElement('div'); tip.className = 'tip'; tip.hidden = true;
  const zoom = document.createElement('div'); zoom.className = 'zoom';
  zoom.innerHTML = '<button type="button" data-z="in" aria-label="Acercar el mapa">+</button><button type="button" data-z="out" aria-label="Alejar el mapa">−</button><button type="button" data-z="reset" class="zoom-all">Toda<br>España</button>';
  wrap.append(cvB, cvT, tip, zoom);
  cvT.setAttribute('role', 'img');
  cvT.setAttribute('aria-label', opt.label || 'Mapa de España');
  const gB = cvB.getContext('2d'), gT = cvT.getContext('2d');
  const m = { colors: new Uint8Array(N), palette: ['#ddd'], sel: null, hover: null, sticky: null, pin: false, group: null };
  const view = { k: 1, cx: SW / 2, cy: SH / 2 };
  let W = 0, H = 0, dpr = 1, raf = 0;

  const scale = () => (W / SW) * view.k;
  const toScreen = (x, y) => { const s = scale(); return [(x - view.cx) * s + W / 2, (y - view.cy) * s + H / 2]; };
  const toMap = (px, py) => { const s = scale(); return [(px - W / 2) / s + view.cx, (py - H / 2) / s + view.cy]; };
  function clamp() {
    view.k = Math.max(1, Math.min(60, view.k));
    const hw = SW / view.k / 2, hh = SH / view.k / 2;
    view.cx = Math.max(hw, Math.min(SW - hw, view.cx));
    view.cy = Math.max(hh, Math.min(SH - hh, view.cy));
    if (view.k === 1) { view.cx = SW / 2; view.cy = SH / 2; }
    cvT.style.touchAction = view.k > 1 ? 'none' : 'pan-y';
  }
  const apply = (g, d) => { const s = scale(); g.setTransform(d * s, 0, 0, d * s, d * (W / 2 - view.cx * s), d * (H / 2 - view.cy * s)); };
  const visible = (i) => {
    const s = scale(), b = BBOX, o = i * 4;
    const x0 = (b[o] - view.cx) * s + W / 2, x1 = (b[o + 2] - view.cx) * s + W / 2;
    const y0 = (b[o + 1] - view.cy) * s + H / 2, y1 = (b[o + 3] - view.cy) * s + H / 2;
    return x1 >= -2 && x0 <= W + 2 && y1 >= -2 && y0 <= H + 2;
  };

  function drawBase() {
    gB.setTransform(dpr, 0, 0, dpr, 0, 0); gB.clearRect(0, 0, W, H);
    apply(gB, dpr);
    const s = scale(); gB.lineJoin = 'round';
    const groups = m.palette.map(() => []);
    for (let i = 0; i < N; i++) if (PATHS[i] && visible(i)) groups[m.colors[i]].push(i);
    const edge = view.k >= 3 ? 'rgba(255,255,255,.75)' : null;
    groups.forEach((list, k) => {
      gB.fillStyle = m.palette[k]; gB.strokeStyle = edge || m.palette[k];
      gB.lineWidth = edge ? 0.5 / s : 0.6 / s;
      list.forEach((i) => { gB.fill(PATHS[i]); gB.stroke(PATHS[i]); });
    });
    const muted = css('--muted', '#5b6b68');
    gB.strokeStyle = muted; gB.lineWidth = 1 / s;
    gB.strokeRect(CANARY[0], CANARY[1], CANARY[2] - CANARY[0], CANARY[3] - CANARY[1]);
    gB.fillStyle = muted; gB.font = '600 ' + 11 / s + 'px system-ui, sans-serif'; gB.textBaseline = 'top';
    gB.fillText('Canarias', CANARY[0] + 5 / s, CANARY[1] + 4 / s);
  }

  function outline(i, w, color) {
    const s = scale();
    gT.lineJoin = 'round';
    gT.lineWidth = (w + 2.5) / s; gT.strokeStyle = '#fff'; gT.stroke(PATHS[i]);
    gT.lineWidth = w / s; gT.strokeStyle = color; gT.stroke(PATHS[i]);
    const o = i * 4, sw = (BBOX[o + 2] - BBOX[o]) * s, sh = (BBOX[o + 3] - BBOX[o + 1]) * s;
    if (Math.max(sw, sh) < 12) {
      const c = CENT[CODES[i]];
      if (c) {
        gT.beginPath(); gT.arc(c[0], c[1], 9 / s, 0, 6.2832);
        gT.lineWidth = 3.5 / s; gT.strokeStyle = '#fff'; gT.stroke();
        gT.lineWidth = 2 / s; gT.strokeStyle = color; gT.stroke();
      }
    }
  }
  function drawPin(i) {
    const c = CENT[CODES[i]]; if (!c) return;
    const [px, py] = toScreen(c[0], c[1]);
    gT.setTransform(dpr, 0, 0, dpr, 0, 0);
    const accent = css('--accent', '#0f766e'), u = Math.max(1.3, Math.min(2, W / 260));
    gT.save(); gT.translate(px, py); gT.beginPath();
    gT.moveTo(0, 0); gT.bezierCurveTo(-5 * u, -8 * u, -9 * u, -12 * u, -9 * u, -18 * u);
    gT.arc(0, -18 * u, 9 * u, Math.PI, 0); gT.bezierCurveTo(9 * u, -12 * u, 5 * u, -8 * u, 0, 0); gT.closePath();
    gT.fillStyle = accent; gT.fill(); gT.lineWidth = 2; gT.strokeStyle = '#fff'; gT.stroke();
    gT.beginPath(); gT.arc(0, -18 * u, 3.4 * u, 0, 6.2832); gT.fillStyle = '#fff'; gT.fill();
    gT.restore();
  }
  function drawTop() {
    gT.setTransform(dpr, 0, 0, dpr, 0, 0); gT.clearRect(0, 0, W, H);
    apply(gT, dpr);
    const ink = css('--ink', '#16211f'), accent = css('--accent', '#0f766e');
    if (m.group) {
      gT.fillStyle = m.group.color; gT.strokeStyle = m.group.color; gT.lineWidth = 0.5 / scale();
      m.group.list.forEach((i) => { if (PATHS[i] && visible(i)) { gT.fill(PATHS[i]); gT.stroke(PATHS[i]); } });
    }
    if (m.pin && m.sel != null) {
      gT.fillStyle = accent; gT.strokeStyle = accent; gT.lineWidth = 1 / scale();
      gT.fill(PATHS[m.sel]); gT.stroke(PATHS[m.sel]);
      gT.beginPath(); const c = CENT[CODES[m.sel]];
      if (c) { gT.arc(c[0], c[1], 10 / scale(), 0, 6.2832); gT.lineWidth = 2.5 / scale(); gT.strokeStyle = accent; gT.stroke(); }
    }
    if (m.hover != null && m.hover !== m.sel && PATHS[m.hover]) outline(m.hover, 1.4, ink);
    if (!m.pin && m.sel != null && PATHS[m.sel]) outline(m.sel, 2.2, ink);
    if (m.pin && m.sel != null) drawPin(m.sel);
  }
  function redraw() { drawBase(); drawTop(); placeSticky(); }
  function schedule(full) {
    if (raf) return;
    raf = requestAnimationFrame(() => { raf = 0; if (full) redraw(); else { drawTop(); placeSticky(); } });
  }

  function resize() {
    const w = wrap.clientWidth; if (!w) return;
    const h = Math.round(w * SH / SW), d = Math.min(window.devicePixelRatio || 1, 2);
    if (w === W && h === H && d === dpr) return;
    W = w; H = h; dpr = d; wrap.style.height = h + 'px';
    [cvB, cvT].forEach((c) => { c.width = Math.round(W * dpr); c.height = Math.round(H * dpr); c.style.width = W + 'px'; c.style.height = H + 'px'; });
    redraw();
  }

  /* hit test: bounding boxes first, then exact path test in map space */
  const probe = document.createElement('canvas').getContext('2d');
  function hitAt(px, py) {
    const [x, y] = toMap(px, py);
    for (let i = 0; i < N; i++) {
      const o = i * 4;
      if (x < BBOX[o] || x > BBOX[o + 2] || y < BBOX[o + 1] || y > BBOX[o + 3] || !PATHS[i]) continue;
      if (probe.isPointInPath(PATHS[i], x, y)) return i;
    }
    let best = -1, bd = 100;
    for (let i = 0; i < N; i++) {
      const c = CENT[CODES[i]]; if (!c) continue;
      const q = toScreen(c[0], c[1]), dx = q[0] - px, dy = q[1] - py, dd = dx * dx + dy * dy;
      if (dd < bd) { bd = dd; best = i; }
    }
    return best;
  }

  /* tooltip */
  function showTip(i, px, py, sticky) {
    if (i == null) { tip.hidden = true; return; }
    tip.innerHTML = opt.tip(i) + (sticky ? '<button type="button" class="tip-go">Ver ficha →</button>' : '');
    tip.classList.toggle('tip-sticky', !!sticky);
    tip.hidden = false;
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    let x = px + 14, y = py + 14;
    if (x + tw > W - 4) x = px - tw - 14;
    if (y + th > H - 4) y = py - th - 14;
    tip.style.left = Math.max(4, x) + 'px'; tip.style.top = Math.max(4, y) + 'px';
  }
  function placeSticky() {
    if (m.sticky == null) return;
    const c = CENT[CODES[m.sticky]]; if (!c) return;
    const q = toScreen(c[0], c[1]);
    showTip(m.sticky, q[0], q[1] - 16, true);
  }

  /* zoom and pan */
  function zoomAt(k, px, py) {
    const [mx, my] = toMap(px, py);
    view.k = k; clamp();
    const s = scale(); view.cx = mx - (px - W / 2) / s; view.cy = my - (py - H / 2) / s; clamp();
  }
  zoom.addEventListener('click', (e) => {
    const b = e.target.closest('[data-z]'); if (!b) return;
    const z = b.getAttribute('data-z');
    if (z === 'reset') { view.k = 1; clamp(); } else zoomAt(view.k * (z === 'in' ? 1.8 : 1 / 1.8), W / 2, H / 2);
    redraw();
  });
  const ptrs = new Map(); let g = null, pinch = null;
  const rel = (e) => { const r = cvT.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  cvT.addEventListener('pointerdown', (e) => {
    const p = rel(e); ptrs.set(e.pointerId, p);
    try { cvT.setPointerCapture(e.pointerId); } catch (_) { /* not critical */ }
    if (ptrs.size === 1) g = { x: p[0], y: p[1], cx: view.cx, cy: view.cy, moved: false, touch: e.pointerType !== 'mouse' };
    else if (ptrs.size === 2) {
      const [a, b] = [...ptrs.values()]; const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
      pinch = { d: Math.hypot(a[0] - b[0], a[1] - b[1]) || 1, k: view.k, mid, mp: toMap(mid[0], mid[1]) };
      if (g) g.moved = true;
    }
  });
  cvT.addEventListener('pointermove', (e) => {
    const p = rel(e);
    if (ptrs.has(e.pointerId)) ptrs.set(e.pointerId, p);
    if (ptrs.size === 2 && pinch) {
      const [a, b] = [...ptrs.values()]; const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
      view.k = pinch.k * (Math.hypot(a[0] - b[0], a[1] - b[1]) / pinch.d); clamp();
      const s = scale(); view.cx = pinch.mp[0] - (mid[0] - W / 2) / s; view.cy = pinch.mp[1] - (mid[1] - H / 2) / s; clamp();
      schedule(true); return;
    }
    if (g && ptrs.size === 1 && (e.pointerType !== 'mouse' || (e.buttons & 1))) {
      const dx = p[0] - g.x, dy = p[1] - g.y;
      if (Math.abs(dx) + Math.abs(dy) > 6) g.moved = true;
      if (g.moved && view.k > 1) {
        const s = scale(); view.cx = g.cx - dx / s; view.cy = g.cy - dy / s; clamp();
        m.hover = null; if (m.sticky == null) tip.hidden = true;
        schedule(true);
      }
      return;
    }
    if (e.pointerType === 'mouse' && m.sticky == null) {
      const i = hitAt(p[0], p[1]);
      const h = i >= 0 ? i : null;
      if (h !== m.hover) { m.hover = h; cvT.style.cursor = h == null ? 'default' : 'pointer'; schedule(false); }
      showTip(h, p[0], p[1], false);
    }
  });
  const end = (e) => {
    const p = rel(e), was = ptrs.size; ptrs.delete(e.pointerId);
    if (was === 2) { pinch = null; g = null; return; }
    if (!g) return;
    const tap = !g.moved && Math.abs(p[0] - g.x) + Math.abs(p[1] - g.y) <= 6; const touch = g.touch; g = null;
    if (e.type === 'pointercancel' || !tap) return;
    const i = hitAt(p[0], p[1]);
    if (i < 0) { m.sticky = null; tip.hidden = true; schedule(false); return; }
    if (touch && opt.twoStep && m.sticky !== i) { m.sticky = i; m.hover = i; schedule(false); return; }
    opt.pick(CODES[i]);
  };
  cvT.addEventListener('pointerup', end);
  cvT.addEventListener('pointercancel', end);
  cvT.addEventListener('pointerleave', (e) => {
    if (e.pointerType === 'mouse' && m.sticky == null) { m.hover = null; tip.hidden = true; schedule(false); }
  });
  tip.addEventListener('click', (e) => { if (e.target.closest('.tip-go') && m.sticky != null) opt.pick(CODES[m.sticky]); });
  cvT.addEventListener('wheel', (e) => {
    if (!(e.ctrlKey || e.metaKey)) return;
    e.preventDefault(); const p = rel(e);
    zoomAt(view.k * (e.deltaY < 0 ? 1.25 : 0.8), p[0], p[1]); redraw();
  }, { passive: false });

  const ro = new ResizeObserver(() => resize()); ro.observe(wrap);
  resize();
  return {
    setColors(colors, palette) { m.colors = colors; m.palette = palette; if (W) redraw(); },
    setGroup(list, color) { m.group = { list, color }; },
    setSelected(i, pin) { m.sel = i; m.pin = !!pin; m.sticky = null; if (W) redraw(); },
    sticky(i) { m.sticky = i; m.hover = i; if (W) { drawTop(); placeSticky(); } },
    focus(i, k) {
      const c = CENT[CODES[i]]; if (!c) return;
      view.k = k; view.cx = c[0]; view.cy = c[1]; clamp(); if (W) redraw();
    },
    setLabel(t) { cvT.setAttribute('aria-label', t); },
    redraw,
    destroy() { ro.disconnect(); if (raf) cancelAnimationFrame(raf); wrap.innerHTML = ''; },
  };
}

/* ---------- search ---------- */
const SEARCH = { index: null };
function buildSearchIndex() {
  SEARCH.index = ROWS.map((r, i) => {
    const mt = /^(.*) \((.+)\)$/.exec(r[1]);
    return { i, n: norm(r[1]), alt: mt ? norm(mt[2] + ' ' + mt[1]) : '' };
  });
}
function search(q) {
  const nq = norm(q.trim()); if (!nq) return [];
  const out = [];
  for (const e of SEARCH.index) {
    let rank = 9;
    if (e.n.startsWith(nq) || (e.alt && e.alt.startsWith(nq))) rank = 0;
    else if (e.n.includes(' ' + nq) || e.n.includes('-' + nq) || e.n.includes('/' + nq)) rank = 1;
    else if (e.n.includes(nq) || (e.alt && e.alt.includes(nq))) rank = 2;
    if (rank < 9) out.push([rank, -(ROWS[e.i][4] || 0), e.i]);
  }
  out.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  return out.slice(0, 8).map((x) => x[2]);
}
function setupSearch() {
  const input = document.getElementById('q'), list = document.getElementById('q-list');
  let results = [], active = -1;
  function paint() {
    if (!input.value.trim()) { list.hidden = true; input.setAttribute('aria-expanded', 'false'); return; }
    if (!results.length) list.innerHTML = '<li class="sg-empty" role="presentation">No encontramos ese municipio</li>';
    else list.innerHTML = results.map((i, n) => {
      const r = ROWS[i], p = PROV[r[2]];
      return `<li role="option" id="q-opt${n}" data-i="${i}" aria-selected="${n === active}" class="${n === active ? 'on' : ''}"><b>${esc(r[1])}</b><span>${esc(p ? p.name : '')}</span></li>`;
    }).join('');
    list.hidden = false; input.setAttribute('aria-expanded', 'true');
    if (active >= 0) input.setAttribute('aria-activedescendant', 'q-opt' + active); else input.removeAttribute('aria-activedescendant');
  }
  function close() { results = []; active = -1; list.hidden = true; input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant'); }
  function choose(i) { close(); input.value = ''; input.blur(); go({ m: CODES[i], i: state.key }); }
  input.addEventListener('input', () => { results = search(input.value); active = results.length ? 0 : -1; paint(); });
  input.addEventListener('focus', () => { if (input.value) { results = search(input.value); active = results.length ? 0 : -1; paint(); } });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (!results.length) return; e.preventDefault();
      active = (active + (e.key === 'ArrowDown' ? 1 : results.length - 1)) % results.length; paint();
    } else if (e.key === 'Enter') { if (active >= 0) { e.preventDefault(); choose(results[active]); } }
    else if (e.key === 'Escape') { close(); }
  });
  list.addEventListener('pointerdown', (e) => { const li = e.target.closest('li[data-i]'); if (li) { e.preventDefault(); choose(+li.dataset.i); } });
  document.addEventListener('click', (e) => { if (!e.target.closest('.search')) close(); });
}

/* ---------- routing ---------- */
const state = { key: 'income', yi: 0, evo: false };
let current = null; // { destroy() }

function parseHash() {
  const p = new URLSearchParams(location.hash.replace(/^#/, ''));
  return { i: p.get('i'), m: p.get('m'), y: p.get('y'), h: p.get('h') };
}
function hashFor(o) {
  const p = new URLSearchParams();
  if (o.m) p.set('m', o.m);
  if (o.i) p.set('i', o.i);
  if (o.y) p.set('y', o.y);
  if (o.h) p.set('h', o.h);
  const s = p.toString(); return s ? '#' + s : '';
}
function go(o) {
  const h = hashFor(o);
  if (h === location.hash || (!h && !location.hash)) route(); else location.hash = h;
}
function replaceHash(o) { history.replaceState(null, '', location.pathname + location.search + hashFor(o)); }

function route() {
  const h = parseHash();
  if (current) { current.destroy(); current = null; }
  if (h.i && IND_BY[h.i]) state.key = h.i;
  const root = document.getElementById('app');
  root.innerHTML = '';
  window.scrollTo(0, 0);
  if (h.m && IDX[h.m] != null) { document.title = ROWS[IDX[h.m]][1] + ' | España, municipio a municipio'; current = showCard(root, h.m); }
  else {
    document.title = 'España, municipio a municipio';
    const y = +h.y; const yi = YEARS.indexOf(y);
    state.evo = state.key === 'income' && yi >= 0; state.yi = state.evo ? yi : LAST;
    current = showHome(root, h.h && IDX[h.h] != null ? h.h : null);
  }
}

/* ---------- home ---------- */
const EXPLORE = [
  ['🏙️', 'Mapas de ciudad', 'estrategia.html?scope=sevilla', 'Sevilla, Madrid, Barcelona y Las Palmas por secciones censales'],
  ['🕒', 'Años 2015-2024', 'estrategia.html#lens=income&y=2015', 'Renta, edad y hogares año a año'],
  ['⚖️', 'Comparar municipios', 'estrategia.html#advisor=compare&a=41091&b=29067', 'Parecidos y cara a cara'],
  ['🚆', 'En directo', 'estrategia.html', 'Trenes de Renfe y tiempo de AEMET'],
  ['🔎', 'Transparencia', 'estrategia.html#advisor=transparency', 'Seguridad, boletines y contratación'],
  ['🗺️', 'Capas del mapa', 'estrategia.html', 'Puertos, aeropuertos, energía y patrimonio'],
];
function showHome(root, highlight) {
  const ind0 = () => IND_BY[state.key];
  root.innerHTML = `
    <div class="layout">
      <section class="hero" id="find" aria-live="polite"></section>
      <section class="mapcol" aria-labelledby="map-title">
        <div class="maphead">
          <div class="maptitle"><span class="ico" id="map-ico" aria-hidden="true"></span><div><h2 id="map-title"></h2><p class="bench" id="bench"></p></div></div>
          <div class="actions">
            <button type="button" class="btn" id="btn-ind" aria-expanded="false" aria-controls="picker">Cambiar indicador</button>
            <button type="button" class="btn" id="btn-evo" aria-pressed="false" aria-controls="evo">Ver evolución</button>
          </div>
        </div>
        <div class="legend" id="legend"></div>
        <div class="picker" id="picker" hidden></div>
        <div class="evo" id="evo" hidden>
          <button type="button" class="play" id="play" aria-label="Reproducir">▶</button>
          <div class="evo-body"><div class="evo-year" id="evo-year"></div>
            <input type="range" id="range" min="0" max="${LAST}" step="1" aria-label="Año">
            <div class="evo-ticks"><span>${YEARS[0]}</span><span>${YEARS[LAST]}</span></div></div>
        </div>
        <div class="map" id="map"></div>
        <p class="src" id="src"></p>
      </section>
      <aside class="side" id="side" aria-label="Provincias con más y con menos"></aside>
    </div>
    <section class="explore" aria-labelledby="ex-h">
      <h2 class="h2" id="ex-h">Más para explorar</h2>
      <p class="note">Estas piezas siguen, por ahora, en el mapa de estrategia.</p>
      <div class="ex-grid">${EXPLORE.map((e) => `<a class="ex-card" href="${e[2]}"><span class="ex-t"><span aria-hidden="true">${e[0]}</span> ${e[1]}</span><span class="ex-d">${e[3]}</span></a>`).join('')}</div>
    </section>`;
  const $ = (id) => root.querySelector('#' + id);
  let timer = null, hl = highlight != null ? IDX[highlight] : null;

  const map = createMap($('map'), {
    twoStep: true,
    label: '',
    tip: (i) => {
      const v = values(state.key, state.yi)[i], r = ROWS[i];
      return `<b>${esc(r[1])}</b><span>${esc(ind0().label)}: ${fmt(v, state.key)}</span>`;
    },
    pick: (code) => go({ m: code, i: state.key }),
  });
  const palette = () => [1, 2, 3, 4, 5].map((n) => css('--seq-' + n, '#888')).concat([css('--nodata', '#d6d2c8')]);

  function paintMap() {
    const b = breaks(state.key), vals = values(state.key, state.yi), c = new Uint8Array(N);
    for (let i = 0; i < N; i++) c[i] = bucketOf(vals[i], b);
    map.setColors(c, palette());
    const nat = natValue(state.key, state.yi);
    map.setLabel(`Mapa de España por municipios: ${ind0().label}, ${yearOf(state.key, state.yi)}. ${NatWord(state.key)}: ${fmt(nat, state.key)}${unitTail(state.key)}. Toca un municipio para abrir su ficha. También puedes usar el buscador.`);
  }

  function renderFind() {
    const ind = ind0(), F = D.findings && D.findings[state.key];
    let h;
    if (F && F.length && state.yi === LAST) {
      h = `<p class="eyebrow">Lo que dicen los datos</p><h1 class="find-h">${esc(F[0])}</h1><ul class="bullets">${F.slice(1, 3).map((t) => `<li>${esc(t)}</li>`).join('')}</ul>`;
    } else if (state.key === 'income') {
      const n0 = D.series.nation[0], n1 = D.series.nation[state.yi];
      h = `<p class="eyebrow">Evolución</p><h1 class="find-h">En ${YEARS[state.yi]}, cada persona tenía de media ${fmt(n1, 'income')} netos al año.</h1><ul class="bullets"><li>En ${YEARS[0]} eran ${fmt(n0, 'income')}.</li><li>${state.yi === 0 ? 'Es el primer año de la serie.' : `Desde ${YEARS[0]} la renta ha subido un ${NF1.format((n1 / n0 - 1) * 100)} %.`}</li></ul>`;
    } else {
      const n = D.nation[state.key];
      h = `<p class="eyebrow">Para situarte</p><h1 class="find-h"><span aria-hidden="true">${ind.icon}</span> ${esc(ind.label)}: ${natWord(state.key)}, ${fmt(n.value, state.key)}${unitTail(state.key)}</h1><ul class="bullets"><li>El municipio mediano: <b>${fmt(n.median, state.key)}</b></li><li>Dato de ${yearOf(state.key, state.yi)}. ${esc(sourceOf(state.key, state.yi))}</li></ul>`;
    }
    $('find').innerHTML = h;
  }
  function renderHead() {
    const ind = ind0(), nat = natValue(state.key, state.yi);
    $('map-ico').textContent = ind.icon; $('map-title').textContent = ind.label;
    $('bench').textContent = `${NatWord(state.key)}: ${fmt(nat, state.key)}${unitTail(state.key)} · ${yearOf(state.key, state.yi)}`;
    $('btn-evo').hidden = state.key !== 'income';
    $('src').textContent = `Fuente: ${sourceOf(state.key, state.yi)}. Límites municipales: Eurostat GISCO, © EuroGeographics (uso no comercial).`;
  }
  function renderLegend() {
    const b = breaks(state.key), k = state.key;
    const labs = [`menos de ${fmt(b[0], k)}`, `${fmt(b[0], k)} a ${fmt(b[1], k)}`, `${fmt(b[1], k)} a ${fmt(b[2], k)}`, `${fmt(b[2], k)} a ${fmt(b[3], k)}`, `${fmt(b[3], k)} o más`];
    let h = '<div class="leg-axis" aria-hidden="true"><span>menos</span><i></i><span>más</span></div><ul class="leg-row">';
    labs.forEach((t, n) => (h += `<li><i style="background:var(--seq-${n + 1})"></i><span>${t}</span></li>`));
    h += '<li><i class="nodata"></i><span>sin dato</span></li></ul>';
    const miss = N - sortedVals(k, state.yi).length;
    h += `<p class="note">Cada color agrupa a una quinta parte de los municipios con dato.${miss / N > 0.05 ? ` Sin dato: ${NF0.format(miss)} municipios.` : ''}</p>`;
    $('legend').innerHTML = h;
  }
  function renderSide() {
    const k = state.key, yi = state.yi;
    const ps = D.provinces.map((p) => ({ code: p.code, name: p.name, v: provValue(p.code, k, yi) })).filter((p) => isNum(p.v)).sort((a, b) => b.v - a.v);
    const top = ps.slice(0, 5), bot = ps.slice(-5).reverse(), nat = natValue(k, yi);
    const all = top.concat(bot).map((p) => p.v).concat([nat, 0]);
    const lo = Math.min(...all), hi = Math.max(...all), span = (hi - lo) * 1.04 || 1;
    const pos = (v) => Math.max(0, Math.min(100, ((v - lo) / span) * 100));
    const noun = nounOf(ind0());
    if (isPartial(k)) {
      // A province's mean could rest on one or two municipalities: do not rank provinces on partial data.
      const share = Math.round(popCoverage(k) * 10);
      $('side').innerHTML = `<p class="nat"><span>Solo hay dato de <b>${NF0.format(nWithData(k))} municipios</b>, donde viven ${share} de cada 10 personas.</span></p><p class="src">Por eso aquí no se comparan provincias. Toca un municipio coloreado para ver su dato.</p>`;
      return;
    }
    const group = (title, list, cls) => `<div class="bars"><h3>${title}</h3>${list.map((p) => {
      const a = pos(0), b = pos(p.v);
      return `<div class="row"><span class="row-n">${esc(p.name)}</span><span class="track" style="--np:${pos(nat).toFixed(2)}%"><i class="${cls}" style="left:${Math.min(a, b).toFixed(2)}%;width:${Math.max(Math.abs(b - a), 0.6).toFixed(2)}%"></i></span><span class="row-v">${fmt(p.v, k)}</span></div>`;
    }).join('')}</div>`;
    $('side').innerHTML = `<p class="nat"><span class="nat-mark" aria-hidden="true"></span>La línea marca la media de España: <b>${fmt(nat, k)}</b></p>` +
      group('Las 5 provincias con más ' + noun, top, 'top') +
      group('Las 5 con menos ' + noun, bot, 'bot') +
      `<p class="src">Media de los municipios de cada provincia, ponderada por población.</p>`;
  }
  function renderEvo() {
    $('evo').hidden = !(state.evo && state.key === 'income');
    $('btn-evo').setAttribute('aria-pressed', String(state.evo));
    $('btn-evo').textContent = state.evo ? 'Ocultar evolución' : 'Ver evolución';
    $('evo-year').textContent = YEARS[state.yi]; $('range').value = state.yi;
    $('play').textContent = timer ? '❚❚' : '▶'; $('play').setAttribute('aria-label', timer ? 'Pausar' : 'Reproducir');
  }
  function syncHash() { replaceHash({ i: state.key, y: state.evo && state.key === 'income' ? YEARS[state.yi] : null, h: highlight }); }
  function refresh() { paintMap(); renderHead(); renderFind(); renderLegend(); renderSide(); renderEvo(); syncHash(); }
  function stop() { if (timer) { clearInterval(timer); timer = null; } }

  // indicator picker
  const picker = $('picker');
  function buildPicker() {
    picker.innerHTML = IND.map((o) => `<button type="button" class="chip${o.key === state.key ? ' on' : ''}" data-k="${o.key}" aria-pressed="${o.key === state.key}"><span aria-hidden="true">${o.icon}</span> ${esc(o.label)}</button>`).join('');
  }
  $('btn-ind').addEventListener('click', () => {
    const open = picker.hidden; if (open) buildPicker();
    picker.hidden = !open; $('btn-ind').setAttribute('aria-expanded', String(open));
  });
  picker.addEventListener('click', (e) => {
    const b = e.target.closest('[data-k]'); if (!b) return;
    state.key = b.dataset.k; stop();
    if (state.key !== 'income') { state.evo = false; state.yi = LAST; }
    picker.hidden = true; $('btn-ind').setAttribute('aria-expanded', 'false'); refresh();
  });
  // evolution
  $('btn-evo').addEventListener('click', () => {
    state.evo = !state.evo; stop(); if (!state.evo) state.yi = LAST; refresh();
  });
  $('range').addEventListener('input', () => { stop(); state.yi = +$('range').value; refresh(); });
  $('play').addEventListener('click', () => {
    if (timer) { stop(); renderEvo(); return; }
    if (state.yi >= LAST) { state.yi = 0; refresh(); }
    timer = setInterval(() => {
      if (state.yi >= LAST) { stop(); renderEvo(); return; }
      state.yi++; refresh();
    }, 800);
    renderEvo();
  });

  refresh();
  if (hl != null) {
    map.setSelected(hl, false);
    map.focus(hl, 4);
    map.sticky(hl);
  }
  return { destroy() { stop(); map.destroy(); } };
}

/* ---------- municipality card ---------- */
const MEASURES = ['income', 'age_mean', 'growth'];
const PHRASE = {
  income: ['Más renta que', 'Menos renta que'],
  age_mean: ['Población más envejecida que', 'Población más joven que'],
  growth: ['Crece más que', 'Crece menos que'],
  density: ['Más densidad de población que', 'Menos densidad de población que'],
  elderly: ['Más personas de 65 años o más que', 'Menos personas de 65 años o más que'],
  foreign: ['Más población extranjera que', 'Menos población extranjera que'],
  household: ['Más personas por hogar que', 'Menos personas por hogar que'],
  poverty: ['Más población bajo el umbral de pobreza que', 'Menos población bajo el umbral de pobreza que'],
  higher_education: ['Más población con estudios superiores que', 'Menos población con estudios superiores que'],
};
function sentenceFor(key, v) {
  if (!isNum(v)) return 'No hay dato para comparar este municipio.';
  const s = sortedVals(key, LAST), t = Math.round((10 * lessCount(s, v)) / s.length);
  const noun = nounOf(IND_BY[key] || { key, label: key });
  const ph = PHRASE[key] || ['Más ' + noun + ' que', 'Menos ' + noun + ' que'];
  const tail = s.length / N < 0.9 ? ` entre los ${NF0.format(s.length)} municipios con dato` : '';
  if (t >= 5) return `${ph[0]} ${t >= 10 ? 'casi todos los municipios' : t + ' de cada 10 municipios'}${tail}.`;
  return `${ph[1]} ${t <= 0 ? 'casi todos los municipios' : 10 - t + ' de cada 10 municipios'}${tail}.`;
}
function stripHTML(key, v, name) {
  if (!isNum(v)) return `<div class="strip strip-na"><span>${NA}</span></div>`;
  const q = D.nation[key].q, s = sortedVals(key, LAST);
  const T = key === 'density' ? (x) => Math.log10(Math.max(x, 0) + 1) : (x) => x;
  const lo = Math.min(T(s[Math.floor(s.length * 0.01)]), T(q[0])), hi = Math.max(T(s[Math.floor(s.length * 0.99)]), T(q[4]));
  const pos = (x) => Math.max(0, Math.min(100, ((T(x) - lo) / (hi - lo)) * 100));
  return `<div class="strip" role="img" aria-label="${esc(sentenceFor(key, v))}">
    <span class="b95" style="left:${pos(q[0])}%;width:${pos(q[4]) - pos(q[0])}%"></span>
    <span class="b50" style="left:${pos(q[1])}%;width:${pos(q[3]) - pos(q[1])}%"></span>
    <span class="med" style="left:${pos(q[2])}%"></span>
    <span class="dot" style="left:${pos(v)}%"></span></div>`;
}
function measureHTML(ind, row) {
  const key = ind.key, v = row[COL[key]], p = PROV[row[2]], nat = D.nation[key];
  const pv = p ? p.values[key] : null;
  const yr = key === 'growth' ? '2021 a 2026' : String(ind.year);
  return `<article class="measure">
    <h3 class="m-lab"><span aria-hidden="true">${ind.icon}</span> ${esc(ind.label)}</h3>
    <div class="m-val${isNum(v) ? '' : ' miss'}">${fmt(v, key)}</div>
    <div class="m-yr">${yr}</div>
    <p class="m-sent">${esc(sentenceFor(key, v))}</p>
    ${stripHTML(key, v)}
    <ul class="m-bench"><li><span>${NatWord(key)}</span><b>${fmt(nat.value, key)}</b></li>${isPartial(key) ? '' : `<li><span>Media de la provincia de ${esc(p ? p.name : '')}</span><b>${fmt(pv, key)}</b></li>`}</ul>
  </article>`;
}

// Similar municipalities: nearest by z-score distance over all indicators (density in log10),
// among places with 20 % to 500 % of the population of the chosen one.
function zTable() {
  if (cache.z) return cache.z;
  const keys = IND.map((i) => i.key), z = keys.map(() => new Float32Array(N));
  keys.forEach((k, j) => {
    const c = COL[k], T = k === 'density' ? (x) => Math.log10(Math.max(x, 0.1)) : (x) => x;
    let sum = 0, n = 0;
    for (let i = 0; i < N; i++) { const v = ROWS[i][c]; if (isNum(v)) { sum += T(v); n++; } }
    const mean = sum / n; let ss = 0;
    for (let i = 0; i < N; i++) { const v = ROWS[i][c]; if (isNum(v)) ss += (T(v) - mean) ** 2; }
    const sd = Math.sqrt(ss / n) || 1;
    for (let i = 0; i < N; i++) { const v = ROWS[i][c]; z[j][i] = isNum(v) ? (T(v) - mean) / sd : NaN; }
  });
  return (cache.z = z);
}
const similarCache = {};
function similarTo(code) {
  if (similarCache[code]) return similarCache[code];
  const i0 = IDX[code], pop = ROWS[i0][4], z = zTable();
  if (!isNum(pop)) return (similarCache[code] = []);
  const out = [];
  for (let i = 0; i < N; i++) {
    const p = ROWS[i][4];
    if (i === i0 || !isNum(p) || p < pop * 0.2 || p > pop * 5) continue;
    let s = 0, n = 0;
    for (let j = 0; j < z.length; j++) { const a = z[j][i0], b = z[j][i]; if (a === a && b === b) { s += (a - b) ** 2; n++; } }
    if (n >= 5) out.push([Math.sqrt(s / n), i]);
  }
  out.sort((a, b) => a[0] - b[0]);
  return (similarCache[code] = out.slice(0, 5).map((x) => x[1]));
}

function changeHTML(row) {
  const a = D.series.munis[row[0]] || [], b = D.series.nation, name = row[1];
  const first = (arr) => arr.findIndex(isNum), last = (arr) => { for (let i = arr.length - 1; i >= 0; i--) if (isNum(arr[i])) return i; return -1; };
  const ha = a.filter(isNum).length >= 2;
  const head = `<h2 class="h2">📈 Cómo ha cambiado</h2>`;
  if (!ha) return `${head}<p class="note">No hay serie de renta para ${esc(name)}: ${NA}.</p>`;
  const W = 420, H = 230, L = 50, R = 74, T = 14, B = 28;
  const all = a.concat(b).filter(isNum);
  let lo = Math.min(...all), hi = Math.max(...all); const pad = (hi - lo) * 0.12 || 500; lo = Math.max(0, lo - pad); hi += pad;
  const x = (i) => L + (i / (YEARS.length - 1)) * (W - L - R), y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const path = (arr) => { let d = '', pen = false; arr.forEach((v, i) => { if (!isNum(v)) { pen = false; return; } d += (pen ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(v).toFixed(1); pen = true; }); return d; };
  const step = hi - lo > 6000 ? 2000 : 1000; let grid = '';
  for (let gv = Math.ceil(lo / step) * step; gv <= hi; gv += step) grid += `<line x1="${L}" x2="${W - R}" y1="${y(gv)}" y2="${y(gv)}" class="gl"/><text x="${L - 6}" y="${y(gv) + 4}" text-anchor="end" class="ax">${NF0.format(gv)}</text>`;
  const xt = [0, 5, 9].map((i) => `<text x="${x(i)}" y="${H - 8}" text-anchor="${i === 0 ? 'start' : i === 9 ? 'end' : 'middle'}" class="ax">${YEARS[i]}</text>`).join('');
  const la = last(a), lb = last(b); let ya = y(a[la]), yb = y(b[lb]);
  if (Math.abs(ya - yb) < 15) { const mid = (ya + yb) / 2; if (ya <= yb) { ya = mid - 8; yb = mid + 8; } else { ya = mid + 8; yb = mid - 8; } }
  const end = (arr, i, yy, cls) => `<circle cx="${x(i)}" cy="${y(arr[i])}" r="4" class="${cls}f"/><text x="${x(i) + 8}" y="${yy + 4}" class="endl ${cls}t">${fmt(arr[i], 'income')}</text>`;
  const delta = (arr) => { const i0 = first(arr), i1 = last(arr); return i1 > i0 ? { d: arr[i1] - arr[i0], p: (arr[i1] / arr[i0] - 1) * 100, y0: YEARS[i0] } : null; };
  const da = delta(a), db = delta(b);
  const bl = (cls, who, d) => d ? `<li><i class="sw ${cls}"></i><span><b>${who}:</b> ${signed(d.d)} € desde ${d.y0} (${signed(d.p)} %)</span></li>` : '';
  return `${head}<p class="note">${esc(IND_BY.income.label)}, ${YEARS[0]} a ${YEARS[LAST]}.</p>
    <div class="key"><span><i class="sw swa"></i>${esc(name)}</span><span><i class="sw swb"></i>Media de España</span></div>
    <svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Renta por persona de ${YEARS[0]} a ${YEARS[LAST]}: ${esc(name)} frente a la media de España">
      ${grid}${xt}<path d="${path(b)}" class="ln lnb"/><path d="${path(a)}" class="ln lna"/>${end(b, lb, yb, 'b')}${end(a, la, ya, 'a')}</svg>
    <ul class="bul">${bl('swa', esc(name), da)}${bl('swb', 'Media de España', db)}</ul>
    <p class="src">${esc(IND_BY.income.source.replace(/\d{4}\s*$/, YEARS[0] + ' a ' + YEARS[LAST]))}. Euros por persona al año.</p>`;
}

function showCard(root, code) {
  const i0 = IDX[code], row = ROWS[i0], p = PROV[row[2]], name = row[1];
  const sameProv = []; for (let i = 0; i < N; i++) if (ROWS[i][2] === row[2]) sameProv.push(i);
  const sim = similarTo(code), EXTRA = IND.filter((i) => !MEASURES.includes(i.key)).length;
  root.innerHTML = `
    <p class="back-wrap"><a class="back" href="${hashFor({ i: state.key, h: code }) || '#'}">← Ver el mapa de España</a></p>
    <header class="card-head">
      <p class="eyebrow">Tu municipio</p>
      <h1 class="name">${esc(name)}</h1>
      <ul class="meta"><li>Provincia de ${esc(p ? p.name : '')}</li><li>${esc(p ? p.ccaa_name : '')}</li><li><b>${isNum(row[4]) ? NF0.format(row[4]) : NA}</b> habitantes <span class="muted">(2026)</span></li></ul>
    </header>
    <section aria-labelledby="mh">
      <h2 class="h2" id="mh">Lo principal</h2>
      <div class="legend-strip" aria-label="Cómo leer las barras">
        <span><i class="lg lg-wide"></i>9 de cada 10 municipios</span><span><i class="lg lg-mid"></i>la mitad central</span>
        <span><i class="lg lg-med"></i>municipio mediano</span><span><i class="lg lg-dot"></i><b>${esc(name)}</b></span>
      </div>
      <div class="measures">${MEASURES.map((k) => measureHTML(IND_BY[k], row)).join('')}</div>
      <button type="button" class="more" id="more" aria-expanded="false" aria-controls="extra"><span id="more-l">Ver ${EXTRA} indicadores más</span> <span id="more-a" aria-hidden="true">▾</span></button>
      <div class="measures extra" id="extra" hidden>${IND.filter((i) => !MEASURES.includes(i.key)).map((i) => measureHTML(i, row)).join('')}</div>
    </section>
    <div class="lower">
      <section class="panel" aria-labelledby="wh">
        <h2 class="h2" id="wh">📍 Dónde está</h2>
        <div class="map loc" id="loc"></div>
        <p class="note"><b>${esc(name)}</b>, en la provincia de ${esc(p ? p.name : '')} (zona más oscura).</p>
        <p class="note muted">Toca el mapa para elegir otro municipio.</p>
        <p class="src">Límites municipales: Eurostat GISCO, © EuroGeographics (uso no comercial).</p>
      </section>
      <section class="panel" id="change">${changeHTML(row)}</section>
      <section class="panel" aria-labelledby="sh">
        <h2 class="h2" id="sh">🧩 Se parecen a ${esc(name)}</h2>
        ${sim.length ? `<p class="note">Municipios de tamaño parecido con indicadores parecidos.</p><div class="chips">${sim.map((i) => `<a class="chip sim" href="#m=${CODES[i]}&i=${state.key}"><b>${esc(ROWS[i][1])}</b><span>${esc(PROV[ROWS[i][2]] ? PROV[ROWS[i][2]].name : '')}</span></a>`).join('')}</div>` : `<p class="note">No hay municipios comparables: ${NA}.</p>`}
        <p class="note"><a href="estrategia.html#advisor=compare&a=${esc(code)}">Comparar con otro municipio</a></p>
        <h2 class="h2 share-h">🔗 Comparte</h2>
        <button type="button" class="btn" id="copy">Copiar enlace</button>
        <p class="note muted" id="copymsg" role="status"></p>
      </section>
    </div>
    <p class="back-wrap"><a class="back" href="${hashFor({ i: state.key, h: code }) || '#'}">← Ver el mapa de España</a></p>`;
  const $ = (id) => root.querySelector('#' + id);
  $('more').addEventListener('click', () => {
    const open = $('extra').hidden; $('extra').hidden = !open;
    $('more').setAttribute('aria-expanded', String(open)); $('more-l').textContent = open ? `Ocultar los ${EXTRA} indicadores` : `Ver ${EXTRA} indicadores más`; $('more-a').textContent = open ? '▴' : '▾';
  });
  const map = createMap($('loc'), {
    twoStep: false,
    label: `Mapa de España con la ubicación de ${name}. Toca para elegir otro municipio.`,
    tip: (i) => `<b>${esc(ROWS[i][1])}</b>`,
    pick: (c) => go({ m: c, i: state.key }),
  });
  const colors = new Uint8Array(N); // 0 = every other place, 1 = same province
  sameProv.forEach((i) => (colors[i] = 1));
  map.setColors(colors, [css('--line', '#dfe5e2'), css('--prov', '#a9bdb8')]);
  map.setSelected(i0, true);
  $('copy').addEventListener('click', () => {
    const done = (ok) => {
      $('copy').textContent = ok ? 'Enlace copiado' : 'Copiar enlace';
      $('copymsg').textContent = ok ? 'Listo. Pégalo donde quieras.' : 'No se pudo copiar. Copia la dirección del navegador.';
      setTimeout(() => { $('copy').textContent = 'Copiar enlace'; }, 2200);
    };
    try { navigator.clipboard.writeText(location.href).then(() => done(true), () => done(false)); } catch (_) { done(false); }
  });
  return { destroy() { map.destroy(); } };
}

/* ---------- boot ---------- */
async function boot() {
  const app = document.getElementById('app');
  try {
    const res = await fetch(new URL('../data/simple.json', import.meta.url)); // next to this script's folder, wherever the page lives
    if (!res.ok) throw new Error('http ' + res.status);
    prepare(await res.json());
  } catch (err) {
    app.innerHTML = '<p class="loading">No se han podido cargar los datos. Recarga la página.</p>';
    return;
  }
  state.yi = LAST;
  prepareGeometry(); buildSearchIndex(); setupSearch();
  const f = document.getElementById('foot-src');
  // Sources text from the data builder, with the geometry credit normalised to the full attribution (never duplicated).
  const src = String(D.meta.sources || '').replace(/\s*Límites municipales:[^.]*\.?(?:\s*©[^.]*\.)?/, '').trim();
  f.textContent = (src ? src + ' ' : '') + 'Límites municipales: Eurostat GISCO, © EuroGeographics (uso no comercial).';
  window.addEventListener('hashchange', route);
  route();
}
boot();
