// Comparar: "Municipios parecidos" (the 8 municipalities most like one, by standardised INE indicators) and
// "Cara a cara" (two municipalities, indicator by indicator). Built on the explorer data (counties.json).
// Hash: #advisor=compare&a=<INE code>[&b=<INE code>]  (with b, the head-to-head tool opens).
import { esc, fin, el } from "../core/util.js";
import { fmtValue, int, count3 } from "../core/fmt.js";
import { section, segmented } from "../core/view.js";
import { rowsHighlight } from "../core/data.js";

const PROV = {
  "01": "Álava", "02": "Albacete", "03": "Alicante", "04": "Almería", "05": "Ávila", "06": "Badajoz", "07": "Illes Balears", "08": "Barcelona", "09": "Burgos", "10": "Cáceres",
  "11": "Cádiz", "12": "Castellón", "13": "Ciudad Real", "14": "Córdoba", "15": "A Coruña", "16": "Cuenca", "17": "Girona", "18": "Granada", "19": "Guadalajara", "20": "Gipuzkoa",
  "21": "Huelva", "22": "Huesca", "23": "Jaén", "24": "León", "25": "Lleida", "26": "La Rioja", "27": "Lugo", "28": "Madrid", "29": "Málaga", "30": "Murcia",
  "31": "Navarra", "32": "Ourense", "33": "Asturias", "34": "Palencia", "35": "Las Palmas", "36": "Pontevedra", "37": "Salamanca", "38": "Santa Cruz de Tenerife", "39": "Cantabria", "40": "Segovia",
  "41": "Sevilla", "42": "Soria", "43": "Tarragona", "44": "Teruel", "45": "Toledo", "46": "Valencia", "47": "Valladolid", "48": "Bizkaia", "49": "Zamora", "50": "Zaragoza", "51": "Ceuta", "52": "Melilla",
};
// The indicators of the comparison. log: shown on a log scale in the bars and standardised on log10.
const IND = [
  { key: "population", label: "Habitantes", format: "int", log: true },
  { key: "density", label: "Densidad", format: "int", unit: "hab./km²", log: true },
  { key: "growth", label: "Crecimiento 2021-2026", format: "signed" },
  { key: "age_mean", label: "Edad media", format: "years" },
  { key: "elderly", label: "Mayores de 65", format: "pct" },
  { key: "foreign", label: "Nacionalidad extranjera", format: "pct" },
  { key: "household", label: "Tamaño del hogar", format: "float", unit: "personas" },
  { key: "income", label: "Renta por persona", format: "eur" },
  { key: "poverty", label: "Bajo el umbral de pobreza", format: "pct" },
  { key: "higher_education", label: "Estudios superiores", format: "pct" },
  { key: "housing_km2", label: "Viviendas por km²", format: "int", unit: "viv./km²", log: true, derived: true },
  { key: "non_primary", label: "Viviendas no principales", format: "pct" },
  { key: "tourist", label: "Viviendas turísticas", format: "pct" },
];
const MIN_SHARED = 6, N_SIMILAR = 8, Z_CAP = 3.5;
const A_COL = "#d9a441", B_COL = "#5aa9d6";

const norm = (s) => String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
const raw = (r, k) => {
  if (k === "housing_km2") return fin(r.v.dwellings_total) && fin(r.v.land_km2) && r.v.land_km2 > 0 ? r.v.dwellings_total / r.v.land_km2 : null;
  const v = r.v[k];
  return fin(v) ? v : null;
};
const fmtInd = (ind, v) => (!fin(v) ? "Sin dato" : fmtValue(ind.format, v, ind.unit) + (ind.format === "int" && ind.unit ? ` ${ind.unit}` : ind.key === "household" ? " personas" : ""));

let CACHE = null; // per counties level: z-scores and medians, computed once
function stats(counties) {
  if (CACHE?.level === counties) return CACHE;
  const rows = counties.rows, n = rows.length, K = IND.length;
  const x = new Float64Array(n * K).fill(NaN); // transformed values (log10 where asked)
  const medians = {};
  IND.forEach((ind, j) => {
    const vals = [];
    rows.forEach((r, i) => {
      let v = raw(r, ind.key);
      if (v == null) return;
      if (ind.log) { if (v <= 0) return; v = Math.log10(v); }
      x[i * K + j] = v;
      vals.push(raw(r, ind.key));
    });
    vals.sort((a, b) => a - b);
    medians[ind.key] = vals.length ? (vals.length % 2 ? vals[(vals.length - 1) / 2] : (vals[vals.length / 2 - 1] + vals[vals.length / 2]) / 2) : null;
    // z-score over every municipality that has the indicator
    let s = 0, c = 0;
    for (let i = 0; i < n; i++) { const v = x[i * K + j]; if (!Number.isNaN(v)) { s += v; c++; } }
    const m = s / c;
    let q = 0;
    for (let i = 0; i < n; i++) { const v = x[i * K + j]; if (!Number.isNaN(v)) q += (v - m) ** 2; }
    const sd = Math.sqrt(q / c) || 1;
    for (let i = 0; i < n; i++) { const v = x[i * K + j]; if (!Number.isNaN(v)) x[i * K + j] = Math.max(-Z_CAP, Math.min(Z_CAP, (v - m) / sd)); }
  });
  const index = new Map(rows.map((r, i) => [r.key, i]));
  CACHE = { level: counties, z: x, K, medians, index };
  return CACHE;
}

function similar(counties, row) {
  const { z, K, index } = stats(counties);
  const i0 = index.get(row.key);
  const mine = [];
  for (let j = 0; j < K; j++) if (!Number.isNaN(z[i0 * K + j])) mine.push(j);
  if (mine.length < MIN_SHARED) return { list: [], have: mine.length };
  const out = [];
  const rows = counties.rows;
  for (let i = 0; i < rows.length; i++) {
    if (i === i0) continue;
    let s = 0, c = 0;
    for (const j of mine) { const b = z[i * K + j]; if (Number.isNaN(b)) continue; const d = z[i0 * K + j] - b; s += d * d; c++; }
    if (c < MIN_SHARED) continue;
    out.push({ i, d: Math.sqrt(s / c), c });
  }
  out.sort((a, b) => a.d - b.d);
  const list = out.slice(0, N_SIMILAR).map((o) => {
    const diffs = [];
    for (const j of mine) { const b = z[o.i * K + j]; if (!Number.isNaN(b)) diffs.push({ j, d: Math.abs(z[i0 * K + j] - b) }); }
    diffs.sort((a, b) => a.d - b.d);
    return { row: rows[o.i], score: Math.round(100 * Math.exp(-o.d)), shared: o.c, close: diffs.slice(0, 3).map((x) => IND[x.j]), far: diffs[diffs.length - 1] ? IND[diffs[diffs.length - 1].j] : null };
  });
  return { list, have: mine.length };
}

const CSS = `
.cmp-search { position: relative; flex: 0 0 auto; min-width: 150px; }
.cmp-search input { width: 100%; box-sizing: border-box; font: inherit; font-size: 12.5px; color: var(--ink); background: #101a24; border: 1px solid rgba(201,164,92,.45); border-radius: 4px; padding: 5px 8px; }
.cmp-search input:focus { outline: none; border-color: var(--gold-bright); }
.cmp-res { position: absolute; z-index: 20; left: 0; right: 0; top: 100%; margin: 2px 0 0; padding: 2px; list-style: none; background: #101a24; border: 1px solid var(--gold); border-radius: 4px; max-height: 240px; overflow: auto; }
.cmp-res[hidden] { display: none; }
.cmp-res li { padding: 4px 8px; font-size: 12.5px; cursor: pointer; display: flex; justify-content: space-between; gap: 8px; }
.cmp-res li:hover, .cmp-res li[aria-selected=true] { background: rgba(201,164,92,.18); }
.cmp-res .s { color: var(--ink-dim); font-size: 11.5px; white-space: nowrap; }
.cmp-slot { display: flex; flex-direction: column; gap: 3px; flex: 1 1 150px; min-width: 0; }
.cmp-slot .tag { font-size: 11px; letter-spacing: .06em; text-transform: uppercase; color: var(--c); }
.cmp-slot .cur { font-size: 12px; color: var(--ink-dim); min-height: 16px; }
.cmp-slot .cur b { color: var(--ink); font-weight: normal; font-size: 13.5px; }
.cmp-list { list-style: none; margin: 8px 0 0; padding: 0; display: grid; gap: 6px; }
.cmp-item { display: grid; grid-template-columns: 1fr 44px; gap: 2px 8px; text-align: left; width: 100%; font: inherit; color: var(--ink); cursor: pointer; padding: 7px 9px; border-radius: 5px; background: rgba(0,0,0,.22); border: 1px solid rgba(201,164,92,.22); }
.cmp-item:hover { border-color: var(--gold); }
.cmp-item .nm { font-size: 13.5px; } .cmp-item .nm i { font-style: normal; color: var(--ink-dim); font-size: 11.5px; }
.cmp-item .sc { grid-row: span 2; align-self: center; text-align: right; font-family: var(--serif); font-size: 20px; color: var(--gold-bright); line-height: 1; }
.cmp-item .sc small { display: block; font-family: inherit; font-size: 9.5px; color: var(--ink-dim); letter-spacing: .04em; }
.cmp-item .why { font-size: 11.5px; color: var(--ink-dim); } .cmp-item .why b { color: var(--ink); font-weight: normal; }
.cmp-scorebar { height: 3px; border-radius: 2px; background: rgba(255,255,255,.1); margin-top: 3px; grid-column: 1; } .cmp-scorebar i { display: block; height: 100%; background: var(--gold); border-radius: 2px; }
.cmp-table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 12px; table-layout: fixed; }
.cmp-table th { font-weight: normal; text-align: left; color: var(--ink-dim); padding: 6px 4px 2px; font-size: 11.5px; }
.cmp-table td { padding: 0 4px 6px; vertical-align: top; }
.cmp-vals { display: flex; justify-content: space-between; gap: 8px; font-variant-numeric: tabular-nums; }
.cmp-vals span:first-child { color: ${A_COL}; } .cmp-vals span:last-child { color: ${B_COL}; text-align: right; }
.cmp-vals .na { color: var(--ink-dim); font-style: italic; }
.cmp-bars { position: relative; margin-top: 2px; }
.cmp-bar { height: 5px; margin-bottom: 2px; border-radius: 0 2px 2px 0; position: relative; }
.cmp-bar.a { background: ${A_COL}; } .cmp-bar.b { background: ${B_COL}; }
.cmp-bar.hi { box-shadow: 0 0 0 1px rgba(255,255,255,.55); }
.cmp-bars:before { content: ""; position: absolute; left: var(--z, 0%); top: -1px; bottom: -1px; width: 1px; background: rgba(255,255,255,.22); }
.cmp-med { position: absolute; top: -3px; bottom: -3px; width: 2px; background: var(--ink); opacity: .85; }
.cmp-legend { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 11.5px; color: var(--ink-dim); margin: 6px 0; }
.cmp-legend i { display: inline-block; width: 10px; height: 6px; margin-right: 4px; }
`;

/** INE writes "Palmas de Gran Canaria, Las" and "Coruña, A": show the article first ("Las Palmas de Gran Canaria"). */
function disp(r) {
  const n = String(r.full || r.name || "");
  const m = n.match(/^(.+?), (El|La|Los|Las|L'|Les|A|O|As|Os|Els|Sa|Es|Ses)$/);
  return m ? `${m[2]}${m[2].endsWith("'") ? "" : " "}${m[1]}` : n;
}

export async function mount(ctx) {
  const { app, data, el: root, link } = ctx;
  const counties = data.levels.counties;
  if (!counties) { root.insertAdjacentHTML("beforeend", `<p class="adv-empty pad">Faltan los datos municipales (counties.json).</p>`); return {}; }
  if (!document.getElementById("cmp-css")) { const s = document.createElement("style"); s.id = "cmp-css"; s.textContent = CSS; document.head.appendChild(s); }
  const S = stats(counties);
  const byKey = new Map(counties.rows.map((r) => [r.key, r]));
  const stateName = new Map((app.data.states || []).map((s) => [s.abbr, s.name]));
  const where = (r) => `${PROV[r.v.province] || ""}${PROV[r.v.province] && stateName.get(r.v.state) && PROV[r.v.province] !== stateName.get(r.v.state) ? " · " : ""}${PROV[r.v.province] === stateName.get(r.v.state) ? "" : stateName.get(r.v.state) || r.v.state || ""}`;
  const byPop = [...counties.rows].sort((x, y) => (y.v.population || 0) - (x.v.population || 0));

  const hv = (k) => { const v = app.hash.value?.(k); return v && byKey.has(v) ? byKey.get(v) : null; };
  const st = { a: hv("a") || (ctx.params.a && byKey.get(String(ctx.params.a))) || null, b: hv("b") || null, tool: null, hl: false, slot: "a" };
  st.tool = st.b ? "pair" : "like";
  const sync = () => app.hash.update?.();

  const top = section(root, { title: "Comparar municipios", note: "Encuentra los municipios más parecidos a uno, o ponlos cara a cara. Busca por nombre o haz clic en el mapa." });
  const tabs = segmented(top, { label: "Herramienta", value: st.tool, options: [{ value: "like", label: "Municipios parecidos" }, { value: "pair", label: "Cara a cara" }], onChange: (v) => { st.tool = v; st.hl = false; if (v === "like") st.b = null; render(); sync(); } });
  const pickers = el("div", "adv-row");
  top.appendChild(pickers);
  const out = section(root, { title: "" });
  const srcNote = el("div");
  root.appendChild(srcNote);

  function slot(which, tag, color) {
    const box = el("div", "cmp-slot");
    box.style.setProperty("--c", color);
    box.innerHTML = `<span class="tag">${esc(tag)}</span><div class="cmp-search"><input type="search" placeholder="Buscar municipio" aria-label="${esc(tag)}: buscar municipio" spellcheck="false" autocomplete="off"><ul class="cmp-res" hidden></ul></div><div class="cur"></div>`;
    const input = box.querySelector("input"), res = box.querySelector(".cmp-res");
    let items = [], sel = -1;
    const close = () => { res.hidden = true; sel = -1; };
    const draw = () => {
      const q = norm(input.value.trim());
      if (!q) return close();
      const starts = [], inner = [];
      for (const r of byPop) {
        const n = norm(r.full || r.name);
        const p = n.indexOf(q);
        if (p === 0) starts.push(r); else if (p > 0) inner.push(r);
        if (starts.length >= 8) break;
      }
      items = [...starts, ...inner].slice(0, 8);
      res.innerHTML = items.length ? items.map((r, i) => `<li data-i="${i}" role="option"><span>${esc(disp(r))}</span><span class="s">${esc(where(r))} · ${esc(count3(r.v.population))}</span></li>`).join("") : `<li class="s">Sin resultados</li>`;
      res.hidden = false;
    };
    const choose = (r) => { input.value = ""; close(); set(which, r); };
    input.addEventListener("input", draw);
    input.addEventListener("focus", () => { st.slot = which; });
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); sel = (sel + (e.key === "ArrowDown" ? 1 : -1) + items.length) % Math.max(items.length, 1); [...res.children].forEach((c, i) => c.setAttribute("aria-selected", String(i === sel))); }
      else if (e.key === "Enter") { const r = items[sel < 0 ? 0 : sel]; if (r) choose(r); }
      else if (e.key === "Escape" && !res.hidden) { e.stopPropagation(); close(); }
    });
    res.addEventListener("mousedown", (e) => { const li = e.target.closest("[data-i]"); if (li) { e.preventDefault(); choose(items[+li.dataset.i]); } });
    input.addEventListener("blur", () => setTimeout(close, 120));
    return { box, cur: box.querySelector(".cur") };
  }
  const slotA = slot("a", "A", A_COL), slotB = slot("b", "B", B_COL);

  function set(which, r) {
    st[which] = r;
    if (st.tool === "like" && which === "a") st.hl = false;
    render();
    sync();
  }
  function showCur() {
    const line = (r) => (r ? `<b>${esc(disp(r))}</b> · ${esc(where(r))} · ${esc(count3(r.v.population))} hab.` : "Sin elegir");
    slotA.cur.innerHTML = line(st.a);
    slotB.cur.innerHTML = line(st.b);
  }
  function baseHighlight(rows) {
    link.base(rows.length ? rowsHighlight(counties, rows, { dim: rows.length > 2 }) : null);
  }

  function render() {
    tabs.set(st.tool);
    pickers.replaceChildren(slotA.box, ...(st.tool === "pair" ? [slotB.box] : []));
    showCur();
    out.innerHTML = "";
    if (st.tool === "like") renderLike(); else renderPair();
  }

  // --- tool 1 -----------------------------------------------------------------------------------------------------
  function renderLike() {
    baseHighlight(st.a ? [st.a] : []);
    if (!st.a) { out.innerHTML = `<p class="adv-note">Elige un municipio arriba o haz clic en uno del mapa.</p>`; return; }
    const { list, have } = similar(counties, st.a);
    if (!list.length) {
      out.innerHTML = `<p class="adv-note"><b>${esc(disp(st.a))}</b> tiene datos de ${int(have)} de los ${IND.length} indicadores, y hacen falta al menos ${MIN_SHARED}. No se puede calcular un parecido fiable.</p>`;
      return;
    }
    out.innerHTML = `<p class="adv-note">Los ${N_SIMILAR} municipios más parecidos a <b>${esc(disp(st.a))}</b> (se comparan ${int(have)} indicadores; si a otro municipio le falta alguno, se compara solo con los que tiene).</p>
      <div class="adv-row"><button type="button" class="adv-mini" data-hl aria-pressed="${st.hl}">${st.hl ? "Quitar el resaltado del mapa" : "Resaltar los 8 en el mapa"}</button><button type="button" class="adv-mini" data-pair>Ponerlo cara a cara con el primero</button></div>
      <ol class="cmp-list">${list.map((x, k) => `<li><button type="button" class="cmp-item" data-k="${k}">
        <span class="nm">${esc(disp(x.row))} <i>${esc(where(x.row))} · ${esc(count3(x.row.v.population))} hab.</i></span>
        <span class="sc">${x.score}<small>parecido</small></span>
        <span class="why">Se parecen en <b>${x.close.map((i) => esc(i.label.toLowerCase())).join("</b>, <b>")}</b>${x.far ? `; difieren sobre todo en <b>${esc(x.far.label.toLowerCase())}</b>` : ""}.</span></button></li>`).join("")}</ol>
      <p class="adv-note">Parecido estadístico con los indicadores del INE que usa este mapa; no es una valoración.</p>`;
    out.querySelector("[data-hl]").addEventListener("click", () => {
      st.hl = !st.hl;
      baseHighlight(st.hl ? [st.a, ...list.map((x) => x.row)] : [st.a]);
      renderLike();
    });
    out.querySelector("[data-pair]").addEventListener("click", () => { st.b = list[0].row; st.tool = "pair"; render(); sync(); });
    out.querySelectorAll("[data-k]").forEach((b) => {
      const r = list[+b.dataset.k].row;
      b.addEventListener("click", () => set("a", r));
      b.addEventListener("mouseenter", () => link.hover(rowsHighlight(counties, [r])));
      b.addEventListener("mouseleave", () => link.hover(null));
    });
    if (st.hl) baseHighlight([st.a, ...list.map((x) => x.row)]);
  }

  // --- tool 2 -----------------------------------------------------------------------------------------------------
  function renderPair() {
    baseHighlight([st.a, st.b].filter(Boolean));
    if (!st.a || !st.b) { out.innerHTML = `<p class="adv-note">Elige dos municipios (A y B) o haz clic en el mapa para rellenar el que tengas enfocado.</p>`; return; }
    const A = st.a, B = st.b;
    const rows = IND.map((ind) => {
      const va = raw(A, ind.key), vb = raw(B, ind.key), md = S.medians[ind.key];
      const vals = [va, vb, md].filter((v) => fin(v) && (!ind.log || v > 0));
      let a = null, b = null, m = null, zero = 0;
      if (vals.length) {
        const lg = (v) => Math.log10(v);
        let lo, hi;
        if (ind.log) { lo = lg(Math.min(...vals)) - 0.5; hi = lg(Math.max(...vals)); } else { lo = Math.min(0, ...vals); hi = Math.max(0, ...vals); }
        const span = hi - lo || 1;
        const pos = (v) => (fin(v) && (!ind.log || v > 0) ? ((ind.log ? lg(v) : v) - lo) / span : null);
        zero = ind.log ? 0 : (0 - lo) / span;
        a = pos(va); b = pos(vb); m = pos(md);
      }
      const bar = (cls, p, v, other) => (p == null ? "" : `<div class="cmp-bar ${cls}${fin(other) && v > other ? " hi" : ""}" style="margin-left:${Math.min(p, zero) * 100}%;width:${Math.max(0.8, Math.abs(p - zero) * 100)}%"></div>`);
      return `<tr><th colspan="1">${esc(ind.label)}${ind.log ? " *" : ""}</th></tr><tr><td>
        <div class="cmp-vals"><span class="${fin(va) ? "" : "na"}">${esc(fmtInd(ind, va))}</span><span class="${fin(vb) ? "" : "na"}">${esc(fmtInd(ind, vb))}</span></div>
        <div class="cmp-bars" style="--z:${zero * 100}%">${bar("a", a, va, vb)}${bar("b", b, vb, va)}${m != null ? `<i class="cmp-med" style="left:${m * 100}%" title="Mediana de España: ${esc(fmtInd(ind, md))}"></i>` : ""}</div></td></tr>`;
    });
    out.innerHTML = `<div class="adv-row"><button type="button" class="adv-mini" data-swap>Intercambiar</button><button type="button" class="adv-mini" data-copy>Copiar enlace</button><span class="adv-note" data-msg style="margin:0"></span></div>
      <div class="cmp-legend"><span><i style="background:${A_COL}"></i>${esc(disp(A))}</span><span><i style="background:${B_COL}"></i>${esc(disp(B))}</span><span><i style="background:var(--ink);width:2px;height:10px"></i>mediana de España</span><span>* barra en escala logarítmica</span></div>
      <table class="cmp-table"><tbody>${rows.join("")}</tbody></table>
      <p class="adv-note">El borde claro marca el valor más alto de cada fila. "Sin dato" significa que el INE no publica la cifra para ese municipio, no que sea cero. Habitantes, densidad y viviendas por km² se dibujan en escala logarítmica.</p>`;
    out.querySelector("[data-swap]").addEventListener("click", () => { [st.a, st.b] = [st.b, st.a]; render(); sync(); });
    out.querySelector("[data-copy]").addEventListener("click", async () => {
      app.hash.flush?.();
      const msg = out.querySelector("[data-msg]");
      try { await navigator.clipboard.writeText(location.href); msg.textContent = "Enlace copiado."; }
      catch { msg.textContent = "No se pudo copiar; copia la dirección del navegador."; }
    });
  }

  // --- hash -------------------------------------------------------------------------------------------------------
  const inView = () => app.mode === "advisor" && app.advisors?.current === "compare";
  ctx.cleanup(app.hash.register("a", { get: () => (inView() && st.a ? st.a.key : null), set(v) { if (inView() && v && byKey.has(v) && st.a?.key !== v) { st.a = byKey.get(v); render(); } } }));
  ctx.cleanup(app.hash.register("b", { get: () => (inView() && st.tool === "pair" && st.b ? st.b.key : null), set(v) { if (inView() && v && byKey.has(v) && st.b?.key !== v) { st.b = byKey.get(v); st.tool = "pair"; render(); } } }));

  render();
  sync();
  return {
    onMapClick(ev) {
      const r = ev?.cell >= 0 ? counties.rowAtCell(ev.cell) : null;
      if (!r) return false;
      const which = st.tool === "pair" ? (!st.a ? "a" : !st.b ? "b" : st.slot) : "a";
      if (st.tool === "pair") st.slot = which === "a" ? "b" : "a";
      set(which, r);
      return true;
    },
    onEscape() { if (st.hl) { st.hl = false; render(); return true; } return false; },
  };
}
