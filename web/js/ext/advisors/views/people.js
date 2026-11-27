// People advisor: population, growth, density, mean age and foreign nationality.
import { esc, fin, colorScale, robustDomain, RAMPS } from "../core/util.js";
import { pct, int, signedPct, count3, fmtShort, fmtValue } from "../core/fmt.js";
import { barList, histogram, rampLegend } from "../core/charts.js";
import { createScatter } from "../core/scatter.js";
import { section, tiles, segmented, mapPicker, frameBtn, sourcesHtml, topBy } from "../core/view.js";
import { rowsHighlight } from "../core/data.js";
import { growthLens } from "../core/lenses.js";

const METRO_MIN = 250000;

export function mount(ctx) {
  const { app, data, el, link } = ctx;
  const n = data.nat;
  const { states, metros, counties } = data.levels;
  const yrs = n.growth_years || [];

  el.insertAdjacentHTML("beforeend", tiles([
    { label: "Residentes", value: count3(n.population), sub: data.vintage },
    { label: `Crecimiento ${yrs.join("-")}`, value: signedPct(n.growth, 2), sub: "variación de la población, INE" },
    { label: "Áreas urbanas", value: int(metros.rows.length), sub: counties ? `${int(counties.rows.length)} municipios` : "áreas urbanas funcionales" },
  ]));

  // --- the map: growth by default, so the map tells the same story as the first chart ---------------------------
  let gLevel = "metros";
  const mapRow = document.createElement("div");
  mapRow.className = "adv-sec adv-mapsec";
  el.appendChild(mapRow);
  const lensOpt = (value, label, id) => ({ value, label, lens: () => id });
  const picker = mapPicker(ctx, mapRow, {
    value: "growth",
    options: [
      { value: "growth", label: "Crecimiento", lens: () => growthLens(data, gLevel) },
      ...(counties ? [lensOpt("density", "Densidad", "density"), lensOpt("age", "Edad media", "age"), lensOpt("foreign", "Nacionalidad extranjera", "foreign")] : []),
      { value: "terrain", label: "Relieve", lens: () => null },
    ],
  });

  // --- growth ---------------------------------------------------------------------------------------------------
  const gBody = section(el, { title: "Quién crece y quién pierde población", note: `Variación de la población ${yrs.join("-")} según las estimaciones del INE, con los límites actuales. Áreas urbanas de más de ${count3(METRO_MIN)} habitantes.` });
  const gHost = document.createElement("div");
  segmented(gBody, { label: "Territorio", value: gLevel, options: [{ value: "metros", label: "Áreas urbanas" }, { value: "states", label: "Comunidades" }], onChange: (v) => { gLevel = v; drawGrowth(); if (picker.value === "growth") picker.refresh(); } });
  gBody.appendChild(gHost);
  function drawGrowth() {
    gHost.innerHTML = "";
    const lv = gLevel === "metros" ? metros : states;
    const min = gLevel === "metros" ? METRO_MIN : 0;
    const fast = topBy(lv.rows, (r) => r.v.growth, { n: 8, min });
    const slow = topBy(lv.rows, (r) => r.v.growth, { n: 8, min, asc: true });
    const max = Math.max(...[...fast, ...slow].map((x) => Math.abs(x.v)));
    const mk = (list) => list.map((x) => ({ key: x.r.key, label: x.r.name, sub: gLevel === "metros" ? x.r.sub : "", value: x.v, text: signedPct(x.v), tone: x.v >= 0 ? "good" : "bad", row: x.r }));
    const opts = {
      diverging: true, max,
      onHover: (r) => link.hover(r ? rowsHighlight(lv, [r.row]) : null),
      onClick: (r) => lv.focus(r.row),
    };
    gHost.insertAdjacentHTML("beforeend", `<h4 class="adv-h4">Más crecimiento</h4>`);
    barList(gHost, { ...opts, rows: mk(fast), ariaLabel: "Más crecimiento" });
    gHost.insertAdjacentHTML("beforeend", `<h4 class="adv-h4">${slow.every((x) => x.v < 0) ? "Pierden población" : "Menos crecimiento"}</h4>`);
    barList(gHost, { ...opts, rows: mk(slow), ariaLabel: "Menos crecimiento" });
  }
  drawGrowth();

  if (!counties) {
    el.insertAdjacentHTML("beforeend", `<p class="adv-empty pad">Faltan los datos municipales, así que no se muestran los gráficos de municipios.</p>`);
    el.insertAdjacentHTML("beforeend", sourcesHtml(data, ["ine", "auf"], []));
    return {};
  }

  // --- density --------------------------------------------------------------------------------------------------
  const dBody = section(el, { title: "Cuánta gente por kilómetro cuadrado", note: "Municipios por residentes por km² (escala logarítmica). Cambia a <i>habitantes</i> para pesar cada municipio por su población: la mayoría de los españoles vive en la cola densa. Pasa el cursor por una barra para ver esos municipios; haz clic para mantenerlos marcados." });
  const dCtl = document.createElement("div");
  dCtl.className = "adv-row";
  dBody.appendChild(dCtl);
  let weighted = false, pinnedBin = null;
  segmented(dCtl, { label: "Contar", value: "counties", options: [{ value: "counties", label: "Municipios" }, { value: "people", label: "Habitantes" }], onChange: (v) => { weighted = v === "people"; drawHist(); } });
  const dLens = document.createElement("button");
  dLens.type = "button";
  dLens.className = "adv-mini";
  dLens.textContent = "Colorear el mapa por densidad";
  dLens.addEventListener("click", () => picker.set("density"));
  dCtl.appendChild(dLens);
  const histHost = document.createElement("div");
  dBody.appendChild(histHost);
  const binInfo = document.createElement("div");
  binInfo.className = "adv-brushinfo";
  dBody.appendChild(binInfo);
  let hist = null;
  const esDensity = counties.rows.reduce((a, r) => a + (r.v.population || 0), 0) / counties.rows.reduce((a, r) => a + (r.v.land_km2 || 0), 0);
  const cByKey = counties.byKey;
  const densRamp = RAMPS.heat;
  function drawHist() {
    histHost.innerHTML = "";
    const vals = counties.rows.map((r) => ({ key: r.key, v: r.v.density, w: r.v.population }));
    const dom = [0.3, 30000];
    hist = histogram(histHost, {
      values: vals, log: true, bins: 30, domain: dom, weighted, height: 130,
      fmt: (v) => fmtShort("float", v), unitLabel: "municipios", weightFmt: (w) => `${count3(w)} habitantes`,
      label: "Histograma de la densidad de población de los municipios",
      colorOf: (_, t) => colorScale({ type: "seq", domain: [0, 1], ramp: densRamp })(t),
      markers: [{ v: esDensity, label: "Media de España" }],
      onHover: (bin) => link.hover(bin ? rowsHighlight(counties, bin.keys.map((k) => cByKey.get(k)), { dim: true }) : null),
      onClick: (bin) => {
        pinnedBin = pinnedBin === bin.i ? null : bin.i;
        const rows = pinnedBin != null ? bin.keys.map((k) => cByKey.get(k)) : [];
        link.base(rows.length ? rowsHighlight(counties, rows, { dim: true }) : null, { frame: rows.length > 1 });
        binInfo.innerHTML = rows.length ? `<b>${int(rows.length)}</b> municipios de ${fmtShort("float", bin.x0)}-${fmtShort("float", bin.x1)} hab./km² · ${count3(rows.reduce((a, r) => a + (r.v.population || 0), 0))} habitantes ${frameBtn()}<button type="button" class="adv-mini" data-clear>Quitar</button>` : "";
      },
    });
  }
  binInfo.addEventListener("click", (e) => { if (e.target.closest("[data-clear]")) { pinnedBin = null; link.base(null); binInfo.innerHTML = ""; } });
  drawHist();

  // --- age and foreign-born -------------------------------------------------------------------------------------
  const aBody = section(el, { title: "Edad y población extranjera", note: "Cada punto es un municipio: edad media en horizontal, proporción con nacionalidad extranjera en vertical, tamaño = habitantes, color = densidad. La nacionalidad extranjera no es lo mismo que haber nacido fuera. Arrastra un rectángulo para seleccionar municipios; se iluminan en el mapa. Pasa el cursor por el mapa para encontrar un municipio aquí." });
  const aCtl = document.createElement("div");
  aCtl.className = "adv-row";
  aBody.appendChild(aCtl);
  aCtl.innerHTML = `<span class="adv-note">Colorear el mapa por</span><button type="button" class="adv-mini" data-map="age">edad media</button><button type="button" class="adv-mini" data-map="foreign">nacionalidad extranjera</button>`;
  aCtl.addEventListener("click", (e) => { const v = e.target.closest("[data-map]")?.dataset.map; if (v) picker.set(v); });
  const dDom = robustDomain(counties.rows.map((r) => r.v.density), 0.02, true) || [1, 2000];
  const dColor = colorScale({ type: "seq", domain: dDom, log: true, ramp: RAMPS.heat });
  const big = topBy(counties.rows, (r) => r.v.population, { n: 6 }).map((x) => x.r.key);
  const scatter = createScatter(aBody, {
    height: 310,
    points: counties.rows.map((r) => ({ key: r.key, x: r.v.age_mean, y: r.v.foreign, s: r.v.population, c: r.v.density, label: r.name, sub: r.sub, row: r })),
    x: { label: "Edad media", fmt: (v) => String(+v.toFixed(0)) },
    y: { label: "Nacionalidad extranjera", fmt: (v) => fmtShort("pct", v) },
    size: { label: "Habitantes", fmt: count3, max: 14, min: 1.4 },
    color: (c) => dColor(c), colorLabel: "Densidad", colorFmt: (v) => `${fmtValue("float", v)} hab./km²`,
    labels: big,
    refX: fin(medianOf(counties.rows, "age_mean")) ? [{ v: medianOf(counties.rows, "age_mean"), label: "municipio mediano" }] : [],
    onHover: (p) => link.hover(p ? rowsHighlight(counties, [p.row]) : null),
    onClick: (p) => counties.focus(p.row),
    onBrush: (set) => {
      const sel = set ? counties.rows.filter((r) => set.has(r.key)) : [];
      link.base(sel.length ? rowsHighlight(counties, sel, { dim: true }) : null, { frame: sel.length > 1 });
      selInfo.innerHTML = sel.length ? selSummary(sel) : "";
    },
  });
  aBody.insertAdjacentHTML("beforeend", rampLegend({ ramp: RAMPS.heat, domain: dDom, log: true, fmt: (v) => fmtShort("float", v), label: "Habitantes por km²" }));
  const selInfo = document.createElement("div");
  selInfo.className = "adv-brushinfo";
  aBody.appendChild(selInfo);
  function selSummary(sel) {
    const pop = sel.reduce((a, r) => a + (r.v.population || 0), 0);
    const top = [...sel].sort((a, b) => (b.v.population || 0) - (a.v.population || 0)).slice(0, 5);
    return `<b>${int(sel.length)}</b> municipios · ${count3(pop)} habitantes (${pct(pop / n.population)} de España)<br><span class="sub">Mayores: ${top.map((r) => `${esc(r.name)}, ${esc(r.sub)}`).join(" · ")}</span> ${frameBtn()}<button type="button" class="adv-mini" data-clear>Quitar</button>`;
  }
  selInfo.addEventListener("click", (e) => { if (e.target.closest("[data-clear]")) { scatter.setSelected(null); link.base(null); selInfo.innerHTML = ""; } });

  el.insertAdjacentHTML("beforeend", sourcesHtml(data, ["ine", "auf", "gisco_lau"], [
    "El mapa de crecimiento colorea las áreas urbanas por su propia variación; los hexágonos grises quedan fuera de ellas. Cambia el gráfico a Comunidades para colorear todos los hexágonos por su comunidad.",
    `El crecimiento usa las estimaciones de población del INE; los totales de población son ${esc(data.vintage)}. Son estimaciones distintas y no cuadran exactamente.`,
    `Las cifras municipales son de ${esc(data.countyVintage)}, así que pueden ir desfasadas respecto a las de áreas urbanas y comunidades.`,
    "La edad es la edad media del municipio (una media, no una mediana); la media de un grupo de municipios no es la media de sus medias. La nacionalidad extranjera mide el pasaporte, no el país de nacimiento.",
    ...(data.countiesOffMap ? [`${int(data.countiesOffMap)} de los municipios más pequeños son menores que un hexágono, así que al seleccionarlos no se marca nada en el mapa.`] : []),
  ]));

  return {
    onMapHover(h) {
      const r = h.cell >= 0 ? counties.rowAtCell(h.cell) : null;
      scatter.setHot(r ? r.key : null);
      hist?.setHot(r ? hist.binOf(r.v.density)?.i ?? null : null);
    },
    onEscape() {
      if (scatter.selected || pinnedBin != null) {
        scatter.setSelected(null); pinnedBin = null; link.base(null); selInfo.innerHTML = ""; binInfo.innerHTML = "";
        return true;
      }
      return false;
    },
  };
}

function medianOf(rows, k) {
  const s = rows.map((r) => r.v[k]).filter(fin).sort((a, b) => a - b);
  return s.length ? s[Math.floor(s.length / 2)] : null;
}
