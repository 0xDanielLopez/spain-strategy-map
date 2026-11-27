// Economy advisor: jobs by CNAE section, urban-area imputed GDP on the map, leaders, specialisation and growth vs output.
import { esc, fin, ratio, colorScale, robustDomain, RAMPS } from "../core/util.js";
import { money, dollars, pct, int, signedPct, count3, fmtShort } from "../core/fmt.js";
import { barList, rampLegend, sizeLegend } from "../core/charts.js";
import { createTable } from "../core/table.js";
import { createScatter } from "../core/scatter.js";
import { section, tiles, segmented, selectBox, sourcesHtml, frameBtn, topBy } from "../core/view.js";
import { rowsHighlight } from "../core/data.js";

export const METRO_MIN = 250000;
const short = (s) => String(s || "").replace(/\s*\(.*\)\s*$/, "");

export function mount(ctx) {
  const { app, data, el, link, params } = ctx;
  const nation = app.data.nation;
  const n = nation.nation || {};
  const metros = data.levels.metros;
  const rows = metros.rows;
  const jobInd = Object.keys(nation.industries || {});
  const ind = nation.industries || {};
  const stLevel = data.levels.states;

  // --- headline -------------------------------------------------------------------------------------------------
  const topInd = jobInd.filter((k) => fin(n.jobs?.[k])).sort((a, b) => n.jobs[b] - n.jobs[a])[0];
  el.insertAdjacentHTML("beforeend", tiles([
    { label: `PIB ${n.gdp_year || ""}`, value: money(n.gdp), sub: "euros corrientes, dato publicado por el INE" },
    { label: "Por habitante", value: money(ratio(n.gdp, n.population)), sub: "PIB ÷ residentes" },
    { label: "Sector con más ocupados", value: topInd ? short(ind[topInd]) : "Sin dato", sub: topInd ? `${pct(ratio(n.jobs[topInd], n.employed))} de los ocupados` : "" },
  ]));

  // --- jobs by CNAE section (GDP by industry is not published at this level: hidden) -----------------------------
  const stRows = stLevel.rows;
  const indBody = section(el, { title: "Ocupados por sector", kicker: "España", note: "Ocupados según su lugar de residencia (no donde trabajan), por sección de la CNAE. Pasa el cursor por un sector para iluminar las comunidades donde pesa más en el empleo; haz clic para ver qué áreas urbanas se especializan en él." });
  const indRows = jobInd.filter((k) => fin(n.jobs?.[k])).sort((a, b) => n.jobs[b] - n.jobs[a]).map((k) => ({
    key: k, label: short(ind[k]), full: nation.industries_full?.[k] || ind[k], value: n.jobs[k], text: count3(n.jobs[k]), sub: pct(ratio(n.jobs[k], n.employed)),
  }));
  const states = app.data.states || [];
  const indBars = barList(indBody, {
    rows: indRows, ariaLabel: "Ocupados por sector",
    onHover: (r) => {
      if (!r) return link.hover(null);
      const top = states.map((s, i) => ({ i, v: ratio(s.jobs?.[r.key], s.employed) })).filter((x) => fin(x.v)).sort((a, b) => b.v - a.v).slice(0, 8);
      link.hover({ states: new Set(top.map((x) => x.i)), dimOthers: true });
    },
    onClick: (r) => { setIndustry(r.key); specBody.scrollIntoView({ behavior: "smooth", block: "start" }); },
  });

  // --- GDP of the autonomous communities (published figure) -----------------------------------------------------
  const ccBody = section(el, { title: "PIB por comunidad", kicker: "Dato publicado", note: "PIB a precios corrientes por comunidad autónoma, donde se produce (INE, Contabilidad Regional). Es un dato medido, no imputado." });
  const ccList = topBy(stRows, (r) => r.v.gdp, { n: 19 });
  barList(ccBody, {
    rank: true, ariaLabel: "PIB por comunidad",
    rows: ccList.map((x) => ({ key: x.r.key, label: x.r.name, sub: fin(x.r.v.gdp_pc) ? `${money(x.r.v.gdp_pc)} por habitante` : "", value: x.v, text: money(x.v), row: x.r })),
    onHover: (r) => link.hover(r ? rowsHighlight(stLevel, [r.row]) : null),
    onClick: (r) => stLevel.focus(r.row),
  });

  // --- map: metro GDP circles -----------------------------------------------------------------------------------
  const mapBody = section(el, { title: "Economías urbanas en el mapa", note: "Cada círculo es un área urbana: su superficie es el PIB imputado del área (el PIB de la provincia repartido por ocupados residentes, no un PIB medido) y su color, la renta media por persona. Pasa el cursor para ver las cifras; haz clic para abrir el área." });
  const ppDomain = robustDomain(rows.map((r) => r.v.income_per_person), 0.03) || [10000, 25000];
  const ppColor = colorScale({ type: "seq", domain: ppDomain, ramp: RAMPS.gold });
  const gMax = Math.max(...rows.map((r) => r.v.gdp || 0));
  const bubbles = ctx.bubbles("gdp", {
    rMax: 30, minR: 1.5, alpha: 0.6,
    tip: (b) => `<b>${esc(b.row.name)}</b> <span class="sub">${esc(b.row.sub)}</span><br>PIB imputado <b>${money(b.row.v.gdp)}</b> · renta media por persona <b>${money(b.row.v.income_per_person)}</b><br>${count3(b.row.v.population)} habitantes`,
    onHover: (b) => { table.setHot(b ? b.key : null); scatter.setHot(b ? b.key : null); link.hover(b ? rowsHighlight(metros, [b.row]) : null); },
    onClick: (b) => app.selectCity(b.row.ref),
  });
  const bubbleItems = rows.filter((r) => fin(r.v.gdp)).map((r) => ({ key: r.key, x: app.w.grid.cx(r.ref.cell), y: app.w.grid.cy(r.ref.cell), value: r.v.gdp, color: fin(r.v.income_per_person) ? ppColor(r.v.income_per_person) : "#8b8070", row: r }));
  bubbles.set(bubbleItems, { vMax: gMax });
  const showBubbles = document.createElement("label");
  showBubbles.className = "adv-check";
  showBubbles.innerHTML = `<input type="checkbox" checked> Mostrar los círculos de PIB`;
  showBubbles.querySelector("input").addEventListener("change", (e) => bubbles.set(e.target.checked ? bubbleItems : [], { vMax: gMax }));
  mapBody.appendChild(showBubbles);
  mapBody.insertAdjacentHTML("beforeend", rampLegend({ ramp: RAMPS.gold, domain: ppDomain, fmt: money, label: "Renta media por persona" })
    + sizeLegend([1e10, 1e11, 1e12].filter((v) => v <= gMax), (v) => 30 * Math.sqrt(v / gMax) , money, "Superficie del círculo = PIB imputado (con el zoom inicial)"));

  // --- leaders --------------------------------------------------------------------------------------------------
  const lBody = section(el, { title: "Áreas urbanas principales", note: `El PIB es imputado (provincial, repartido por ocupados), por eso no se ofrece un PIB por habitante ni por ocupado de las áreas. La renta y el crecimiento se ordenan solo para áreas de más de ${count3(METRO_MIN)} habitantes.` });
  const big = rows.filter((r) => (r.v.population || 0) >= METRO_MIN);
  segmented(lBody, {
    label: "Ordenar por", value: "gdp",
    options: [{ value: "gdp", label: "Mayor PIB imputado" }, { value: "income_per_person", label: "Renta por persona" }, { value: "growth", label: "Más crecimiento" }],
    onChange: (v) => { table.setRows(v === "gdp" ? rows : big); table.setColumns(cols, { key: v, dir: "desc" }); },
  });
  const cols = [
    { key: "name", label: "Área urbana", align: "l", value: (r) => r.name, html: (r) => `${esc(r.name)} <span class="sub">${esc(r.sub)}</span>` },
    { key: "gdp", label: "PIB imputado", value: (r) => r.v.gdp, text: (r) => money(r.v.gdp), bar: { max: gMax, color: "rgba(224,181,76,.35)" } },
    { key: "income_per_person", label: "Renta por persona", value: (r) => r.v.income_per_person, text: (r) => money(r.v.income_per_person) },
    { key: "growth", label: "Crecimiento", value: (r) => r.v.growth, text: (r) => signedPct(r.v.growth) },
  ];
  const table = createTable(lBody, {
    caption: "Áreas urbanas por PIB imputado", columns: cols, rows, sort: { key: "gdp", dir: "desc" }, rank: true, maxHeight: 280,
    search: "Buscar áreas urbanas",
    onHover: (r) => { link.hover(r ? rowsHighlight(metros, [r]) : null); bubbles.setHot(r ? r.key : null); scatter.setHot(r ? r.key : null); },
    onClick: (r) => app.selectCity(r.ref),
  });

  // --- specialisation -------------------------------------------------------------------------------------------
  const specBody = section(el, { title: "Quién se especializa en qué", note: `Cociente de localización: la proporción de ocupados residentes del área en el sector ÷ la proporción en España. ×2 significa el doble de concentración que en el conjunto del país. Áreas de más de ${count3(METRO_MIN)} habitantes; las 15 más especializadas se marcan en el mapa.` });
  let industry = params.industry && jobInd.includes(params.industry) ? params.industry : jobInd.includes("c") ? "c" : jobInd[0];
  const indSel = selectBox(specBody, {
    label: "Sector (CNAE)", value: industry,
    options: jobInd.map((k) => ({ value: k, label: short(nation.industries[k]) })),
    onChange: (v) => setIndustry(v),
  });
  const specInfo = document.createElement("p");
  specInfo.className = "adv-note";
  specBody.appendChild(specInfo);
  const lq = (r, k = industry) => {
    const o = r.ref;
    const us = ratio(n.jobs?.[k], n.employed);
    return us ? ratio(ratio(o.jobs?.[k], o.employed), us) : null;
  };
  const specTable = createTable(specBody, {
    caption: "Áreas urbanas más especializadas", rank: true, maxHeight: 260, rows: [],
    columns: [
      { key: "name", label: "Área urbana", align: "l", value: (r) => r.name, html: (r) => `${esc(r.name)} <span class="sub">${esc(r.sub)}</span>` },
      { key: "share", label: "Peso en el empleo", value: (r) => ratio(r.ref.jobs?.[industry], r.ref.employed), text: (r) => pct(ratio(r.ref.jobs?.[industry], r.ref.employed)) },
      { key: "lq", label: "Cociente", value: (r) => lq(r), text: (r) => (fin(lq(r)) ? `×${lq(r).toFixed(2).replace(".", ",")}` : "Sin dato"), bar: { max: 1, color: "rgba(74,134,214,.4)" } },
      { key: "workers", label: "Ocupados", value: (r) => r.ref.jobs?.[industry], text: (r) => count3(r.ref.jobs?.[industry]) },
    ],
    sort: { key: "lq", dir: "desc" },
    onHover: (r) => { link.hover(r ? rowsHighlight(metros, [r]) : null); scatter.setHot(r ? r.key : null); bubbles.setHot(r ? r.key : null); },
    onClick: (r) => app.selectCity(r.ref),
  });

  // --- scatter --------------------------------------------------------------------------------------------------
  const scBody = section(el, { title: "Crecimiento y producción", note: "Cada punto es un área urbana: PIB imputado en horizontal, crecimiento de la población 2021-2026 en vertical, tamaño = habitantes. Arrastra un rectángulo para seleccionar áreas y marcarlas en el mapa." });
  const scCtl = document.createElement("div");
  scCtl.className = "adv-row";
  scBody.appendChild(scCtl);
  let colorBy = "lq", allMetros = false;
  selectBox(scCtl, {
    label: "Color", value: colorBy,
    options: [{ value: "lq", label: "Especialización (sector elegido)" }, { value: "income_per_person", label: "Renta media por persona" }, { value: "none", label: "Ninguno" }],
    onChange: (v) => { colorBy = v; drawScatter(); },
  });
  segmented(scCtl, { label: "Áreas", value: "big", options: [{ value: "big", label: `${count3(METRO_MIN)}+` }, { value: "all", label: "Todas" }], onChange: (v) => { allMetros = v === "all"; drawScatter(); } });
  const legendEl = document.createElement("div");
  const scatter = createScatter(scBody, {
    points: [], height: 300,
    x: { label: "PIB imputado", fmt: (v) => money(v), log: true },
    y: { label: "Crecimiento de la población", fmt: (v) => fmtShort("signed", v) },
    size: { label: "Habitantes", fmt: count3, max: 15, min: 2 },
    refY: [{ v: n.growth ?? 0, label: `España ${signedPct(n.growth)}` }],
    onHover: (p) => { link.hover(p ? rowsHighlight(metros, [p.row]) : null); bubbles.setHot(p ? p.key : null); table.setHot(p ? p.key : null, false); },
    onClick: (p) => app.selectCity(p.row.ref),
    onBrush: (set) => {
      const sel = set ? rows.filter((r) => set.has(r.key)) : [];
      link.base(sel.length ? rowsHighlight(metros, sel, { dim: true }) : specHighlight(), { frame: sel.length > 1 });
      bubbles.setSelected(set);
      brushInfo.innerHTML = sel.length ? brushSummary(sel) : "";
    },
  });
  scBody.appendChild(legendEl);
  const brushInfo = document.createElement("div");
  brushInfo.className = "adv-brushinfo";
  scBody.appendChild(brushInfo);
  function brushSummary(sel) {
    const pop = sel.reduce((a, r) => a + (r.v.population || 0), 0);
    const gdp = sel.reduce((a, r) => a + (r.v.gdp || 0), 0);
    return `<b>${sel.length}</b> áreas urbanas seleccionadas · ${count3(pop)} habitantes · ${money(gdp)} de PIB imputado (${pct(gdp / n.gdp)} del PIB de España; las áreas se solapan con varias comunidades) ${frameBtn()}<button type="button" class="adv-mini" data-clear>Quitar</button>`;
  }
  brushInfo.addEventListener("click", (e) => { if (e.target.closest("[data-clear]")) { scatter.setSelected(null); link.base(specHighlight()); bubbles.setSelected(null); brushInfo.innerHTML = ""; } });

  function drawScatter() {
    const list = rows.filter((r) => allMetros || (r.v.population || 0) >= METRO_MIN);
    const cv = (r) => (colorBy === "lq" ? lq(r) : colorBy === "none" ? null : r.v[colorBy]);
    let color = null, legend = "";
    if (colorBy !== "none") {
      const dom = robustDomain(list.map(cv), 0.03, colorBy === "lq") || [0, 1];
      const spec = colorBy === "lq" ? { type: "seq", domain: [Math.max(0.2, dom[0]), Math.max(1.5, dom[1])], log: true, ramp: RAMPS.seq } : { type: "seq", domain: dom, ramp: RAMPS.gold };
      const cs = colorScale(spec);
      color = (c) => cs(c);
      const f = colorBy === "lq" ? (v) => `×${v.toFixed(1).replace(".", ",")}` : money;
      legend = rampLegend({ ramp: spec.ramp, domain: spec.domain, fmt: f, log: spec.log, label: colorBy === "lq" ? `Especialización en ${short(nation.industries[industry]).toLowerCase()}` : "Renta media por persona" });
    }
    const labels = [...list].sort((a, b) => (b.v.population || 0) - (a.v.population || 0)).slice(0, 8).map((r) => r.key);
    scatter.update({
      points: list.filter((r) => fin(r.v.gdp) && fin(r.v.growth)).map((r) => ({ key: r.key, x: r.v.gdp, y: r.v.growth, s: r.v.population, c: cv(r), label: r.name, sub: r.sub, row: r })),
      color, labels, colorLabel: colorBy === "none" ? null : colorBy === "lq" ? "Cociente" : "Renta por persona",
      colorFmt: colorBy === "lq" ? (v) => `×${(+v).toFixed(2).replace(".", ",")}` : dollars,
    });
    legendEl.innerHTML = legend;
  }

  let specTop = [];
  const specHighlight = () => (specTop.length ? rowsHighlight(metros, specTop, { ringMax: 15 }) : null);
  function setIndustry(k) {
    industry = k;
    indSel.set(k);
    const list = big.filter((r) => fin(lq(r))).sort((a, b) => lq(b) - lq(a));
    specTop = list.slice(0, 15);
    const maxLq = Math.max(1, ...list.slice(0, 40).map((r) => lq(r)));
    specTable.setColumns([
      { key: "name", label: "Área urbana", align: "l", value: (r) => r.name, html: (r) => `${esc(r.name)} <span class="sub">${esc(r.sub)}</span>` },
      { key: "share", label: "Peso en el empleo", value: (r) => ratio(r.ref.jobs?.[industry], r.ref.employed), text: (r) => pct(ratio(r.ref.jobs?.[industry], r.ref.employed)) },
      { key: "lq", label: "Cociente", value: (r) => lq(r), text: (r) => (fin(lq(r)) ? `×${lq(r).toFixed(2).replace(".", ",")}` : "Sin dato"), bar: { max: maxLq, color: "rgba(74,134,214,.45)" } },
      { key: "workers", label: "Ocupados", value: (r) => r.ref.jobs?.[industry], text: (r) => count3(r.ref.jobs?.[industry]) },
    ], { key: "lq", dir: "desc" });
    specTable.setRows(list);
    const us = ratio(n.jobs?.[k], n.employed);
    specInfo.innerHTML = `España: <b>${pct(us)}</b> de los ocupados residentes (${count3(n.jobs?.[k])} personas) trabajan en «${esc(short(nation.industries[k]).toLowerCase())}».`;
    if (!scatter.selected) link.base(specHighlight());
    indBars.setSelected(k);
    drawScatter();
  }
  setIndustry(industry);

  el.insertAdjacentHTML("beforeend", sourcesHtml(data, ["ine_gdp", "ine_jobs", "ine", "auf"], [
    "El PIB de las comunidades es el dato publicado por el INE, donde se produce. El de las áreas urbanas es imputado: el PIB de la provincia de cada municipio repartido por ocupados residentes, así que no mide la producción real del área.",
    "Los ocupados y la especialización se cuentan donde vive el trabajador (Censo anual de población), no donde trabaja: el empleo de un municipio dormitorio cuenta en su propia área.",
    `El PIB es de ${esc(nation.gdp_vintage || "el INE")} y la población de ${esc(nation.vintage || "el INE")}: las cifras por habitante dividen datos de años distintos.`,
    "La renta es una media por persona, no una mediana. El PIB por sector no se publica a este nivel y por eso no se muestra.",
  ]));

  return {
    onMapHover(h) {
      const r = h.cell >= 0 ? metros.rowAtCell(h.cell) : null;
      scatter.setHot(r ? r.key : null);
      specTable.setHot(r ? r.key : null);
    },
    onEscape() {
      if (scatter.selected) { scatter.setSelected(null); link.base(specHighlight()); bubbles.setSelected(null); brushInfo.innerHTML = ""; return true; }
      return false;
    },
  };
}
