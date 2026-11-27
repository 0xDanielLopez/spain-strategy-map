// Knowledge advisor ("Formación y perfil profesional"): higher education and the science yield, a sector proxy.
import { esc, fin, ratio, colorScale, robustDomain, RAMPS } from "../core/util.js";
import { money, pct, int, count3, fmtShort } from "../core/fmt.js";
import { barList, histogram, rampLegend } from "../core/charts.js";
import { createTable } from "../core/table.js";
import { createScatter } from "../core/scatter.js";
import { section, tiles, segmented, mapPicker, frameBtn, sourcesHtml, topBy } from "../core/view.js";
import { rowsHighlight } from "../core/data.js";
import { scienceLens } from "../core/lenses.js";

const METRO_MIN = 250000;
const PROXY = "ocupados en información y comunicaciones y en actividades profesionales, científicas y técnicas";

export function mount(ctx) {
  const { app, data, el, link } = ctx;
  const n = data.nat;
  const nation = app.data.nation;
  const { metros, counties } = data.levels;
  const sci = nation.yields?.find((y) => y.key === "science");
  const usSci = n.yields?.science;
  const usShare = ratio(usSci, n.employed);
  const withDeg = counties ? counties.rows.filter((r) => fin(r.v.higher_education)) : [];
  const wavg = (k) => {
    let a = 0, w = 0;
    for (const r of withDeg) if (fin(r.v[k]) && fin(r.v.population)) { a += r.v[k] * r.v.population; w += r.v.population; }
    return w ? a / w : null;
  };

  el.insertAdjacentHTML("beforeend", tiles([
    { label: "Ocupados en el sector del conocimiento", value: count3(usSci), sub: `${pct(usShare)} de los ocupados (aproximación sectorial)`, color: sci?.color },
    { label: "Estudios superiores", value: pct(wavg("higher_education")), sub: counties ? `población de 15 años o más, municipios con dato (${int(withDeg.length)})` : "Sin dato" },
    { label: "Renta media por persona", value: money(n.income_per_person), sub: "una media, no una mediana" },
  ]));

  // --- the map: higher education by default (the scatter's x axis), or the sector proxy's share by area ---------
  const mapRow = document.createElement("div");
  mapRow.className = "adv-sec adv-mapsec";
  el.appendChild(mapRow);
  const picker = mapPicker(ctx, mapRow, {
    value: counties ? "higher_education" : "science",
    options: [
      ...(counties ? [{ value: "higher_education", label: "Estudios superiores", lens: () => "higher_education" }] : []),
      { value: "science", label: "Empleo en conocimiento", lens: () => scienceLens(data) },
      { value: "terrain", label: "Relieve", lens: () => null },
    ],
  });

  // --- science yield: a sector proxy ------------------------------------------------------------------------------
  const sBody = section(el, { title: "Empleo en conocimiento (aproximación sectorial)", note: `No mide investigadores ni formación: cuenta ${PROXY}, donde viven. Un administrativo de un despacho de abogados cuenta; un investigador de un hospital, no. El ranking por peso solo incluye áreas urbanas de más de ${count3(METRO_MIN)} habitantes.` });
  const sHost = document.createElement("div");
  let mode = "share";
  segmented(sBody, { label: "Ordenar por", value: mode, options: [{ value: "share", label: "Peso en el empleo" }, { value: "abs", label: "Más ocupados" }], onChange: (v) => { mode = v; drawSci(); } });
  const sMap = document.createElement("button");
  sMap.type = "button";
  sMap.className = "adv-mini";
  sMap.textContent = "Colorear el mapa por empleo en conocimiento";
  sMap.addEventListener("click", () => picker.set("science"));
  sBody.querySelector(".adv-seg")?.after(sMap);
  sBody.appendChild(sHost);
  const share = (r) => ratio(r.v.y_science, r.v.employed);
  function drawSci() {
    sHost.innerHTML = "";
    const list = mode === "abs" ? topBy(metros.rows, (r) => r.v.y_science, { n: 12 }) : topBy(metros.rows, share, { n: 12, min: METRO_MIN });
    barList(sHost, {
      rank: true, ariaLabel: "Áreas urbanas con más empleo en conocimiento",
      rows: list.map((x) => ({ key: x.r.key, label: x.r.name, sub: mode === "abs" ? pct(share(x.r)) : fin(usShare) ? `×${(share(x.r) / usShare).toFixed(2).replace(".", ",")} España` : "", value: x.v, text: mode === "abs" ? count3(x.v) : pct(x.v), color: sci?.color, row: x.r })),
      onHover: (r) => link.hover(r ? rowsHighlight(metros, [r.row]) : null),
      onClick: (r) => metros.focus(r.row),
    });
  }
  drawSci();

  if (!counties) {
    el.insertAdjacentHTML("beforeend", `<p class="adv-empty pad">Faltan los datos municipales, así que no se muestran los gráficos de estudios superiores.</p>`);
    el.insertAdjacentHTML("beforeend", sourcesHtml(data, ["ine_jobs"], []));
    return {};
  }

  // --- higher education vs income ---------------------------------------------------------------------------------
  const dBody = section(el, { title: "Estudios superiores y renta", note: "Proporción de residentes de 15 años o más con estudios superiores frente a la renta media por persona (una media, no una mediana); color = densidad. Los municipios sin dato de estudios no aparecen. Arrastra para seleccionar; pasa el cursor por el mapa para encontrar un lugar." });
  const dCtl = document.createElement("div");
  dCtl.className = "adv-row";
  dBody.appendChild(dCtl);
  let level = "counties";
  segmented(dCtl, { label: "Lugares", value: level, options: [{ value: "counties", label: "Municipios" }, { value: "metros", label: "Áreas urbanas" }], onChange: (v) => { level = v; drawDeg(); } });
  const lv = () => data.levels[level];
  const inc = (r) => (level === "counties" ? r.v.income : r.v.income_per_person);
  const dDom = robustDomain(counties.rows.map((r) => r.v.density), 0.02, true) || [1, 2000];
  const dColor = colorScale({ type: "seq", domain: dDom, log: true, ramp: RAMPS.heat });
  const nounOf = () => (level === "counties" ? "municipios" : "áreas urbanas");
  const scatter = createScatter(dBody, {
    height: 300, points: [],
    x: { label: "Residentes con estudios superiores", fmt: (v) => fmtShort("pct", v) },
    y: { label: "Renta media por persona", fmt: money, log: true },
    size: { label: "Habitantes", fmt: count3, max: 14, min: 1.4 },
    color: (c) => dColor(c), colorLabel: "Densidad", colorFmt: (v) => `${fmtShort("float", v)} hab./km²`,
    onHover: (p) => link.hover(p ? rowsHighlight(lv(), [p.row]) : null),
    onClick: (p) => lv().focus(p.row),
    onBrush: (set) => {
      const sel = set ? lv().rows.filter((r) => set.has(r.key)) : [];
      link.base(sel.length ? rowsHighlight(lv(), sel, { dim: true }) : null, { frame: sel.length > 1 });
      selInfo.innerHTML = sel.length ? `<b>${int(sel.length)}</b> ${nounOf()} · ${count3(sel.reduce((a, r) => a + (r.v.population || 0), 0))} habitantes ${frameBtn()}<button type="button" class="adv-mini" data-clear>Quitar</button>` : "";
    },
  });
  dBody.insertAdjacentHTML("beforeend", rampLegend({ ramp: RAMPS.heat, domain: dDom, log: true, fmt: (v) => fmtShort("float", v), label: "Habitantes por km²" }));
  const selInfo = document.createElement("div");
  selInfo.className = "adv-brushinfo";
  dBody.appendChild(selInfo);
  const clearSel = () => { scatter.setSelected(null); link.base(null); selInfo.innerHTML = ""; };
  selInfo.addEventListener("click", (e) => { if (e.target.closest("[data-clear]")) clearSel(); });
  function drawDeg() {
    clearSel();
    const rows = lv().rows;
    scatter.update({
      points: rows.filter((r) => fin(r.v.higher_education) && fin(inc(r))).map((r) => ({ key: r.key, x: r.v.higher_education, y: inc(r), s: r.v.population, c: r.v.density, label: r.name, sub: r.sub, row: r })),
      labels: topBy(rows, (r) => r.v.population, { n: 6 }).map((x) => x.r.key),
    });
  }
  drawDeg();

  // --- where higher education is rarer ----------------------------------------------------------------------------
  const bBody = section(el, { title: "Dónde hay más y menos estudios superiores", note: "Municipios por proporción de residentes de 15 años o más con estudios superiores. Pasa el cursor por una barra para marcar esos municipios en el mapa." });
  const bHost = document.createElement("div");
  bBody.appendChild(bHost);
  const bbHist = histogram(bHost, {
    values: withDeg.map((r) => ({ key: r.key, v: r.v.higher_education })), bins: 30, domain: [0, 0.7], height: 120,
    fmt: (v) => fmtShort("pct", v), unitLabel: "municipios", label: "Histograma de la proporción de residentes con estudios superiores",
    colorOf: (_, t) => colorScale({ type: "seq", domain: [0, 1], ramp: RAMPS.seq })(t),
    onHover: (bin) => link.hover(bin ? rowsHighlight(counties, bin.keys.map((k) => counties.byKey.get(k)), { dim: true }) : null),
  });
  createTable(bBody, {
    caption: "Estudios superiores por municipio", rank: true, maxHeight: 240, search: "Buscar municipios",
    rows: withDeg,
    columns: [
      { key: "name", label: "Municipio", align: "l", value: (r) => r.name, html: (r) => `${esc(r.name)} <span class="sub">${esc(r.sub)}</span>` },
      { key: "population", label: "Habitantes", value: (r) => r.v.population, text: (r) => count3(r.v.population) },
      { key: "higher_education", label: "Estudios superiores", value: (r) => r.v.higher_education, text: (r) => pct(r.v.higher_education), bar: { max: 0.7, color: "rgba(74,134,214,.4)" } },
      { key: "income", label: "Renta por persona", value: (r) => r.v.income, text: (r) => money(r.v.income) },
    ],
    sort: { key: "higher_education", dir: "desc" },
    onHover: (r) => link.hover(r ? rowsHighlight(counties, [r]) : null),
    onClick: (r) => counties.focus(r),
  });

  el.insertAdjacentHTML("beforeend", sourcesHtml(data, ["ine", "ine_jobs", "auf"], [
    `El empleo en conocimiento es una aproximación por sector (${PROXY}), contado donde vive el trabajador, no donde trabaja.`,
    `Los estudios superiores son cifras municipales de ${esc(data.countyVintage)} sobre residentes de 15 años o más; solo ${int(withDeg.length)} de ${int(counties.rows.length)} municipios tienen dato. Los valores de las áreas urbanas son medias de sus municipios ponderadas por población (con dato).`,
    "El mapa de empleo en conocimiento colorea solo las áreas urbanas (los hexágonos grises quedan fuera).",
    "La renta es una media por persona, no una mediana.",
    ...(data.countiesOffMap ? [`${int(data.countiesOffMap)} de los municipios más pequeños son menores que un hexágono, así que al seleccionarlos no se marca nada en el mapa.`] : []),
  ]));

  return {
    onMapHover(h) {
      const r = h.cell >= 0 ? lv().rowAtCell(h.cell) : null;
      scatter.setHot(r ? r.key : null);
      const c = h.cell >= 0 ? counties.rowAtCell(h.cell) : null;
      bbHist.setHot(c ? bbHist.binOf(c.v.higher_education)?.i ?? null : null);
    },
    onEscape() {
      if (scatter.selected) { clearSel(); return true; }
      return false;
    },
  };
}
