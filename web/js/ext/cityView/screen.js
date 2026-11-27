// The city screen: a docked dashboard (a bottom sheet on phones) with the header (and its city-type badge),
// Habitantes (figure rows from citizens.json), Especializaciones (districts.json), Economía, Empleo and Comparar.
// Plain HTML strings + inline SVG charts; render(el, model, handlers) fills `el`. The citizens and districts files
// load on demand (h.loadData) and fill their sections when they arrive. Nothing here invents a figure: a field the
// Spanish data does not have (null) is left out or shown as "Sin dato", never as 0.
import { esc, int, pct } from "../../format.js";
import { compact, money, popShort, yieldValue } from "./fmt.js";
import { icon, glyph } from "../../ui/icon.js";
import { css } from "../../color.js";
import { isCapital } from "../../world.js";
import { meter, bar } from "./charts.js";
import { rankCount } from "./model.js";
import { citizensHtml, mountCitizens } from "./citizens.js";
import { badgeHtml, cityDistricts, districtsHtml } from "./districts.js";

const TABS = [
  ["citizens", "Habitantes", "pop"],
  ["districts", "Especializaciones", "l-developed"],
  ["economy", "Economía", "y-gold"],
  ["workforce", "Empleo", "y-production"],
  ["compare", "Comparar", "layers"],
];

const dec = (v, d = 1) => v.toFixed(d).replace(".", ",");
const signed = (g, d = 1) => (g == null ? "Sin dato" : `${g >= 0 ? "+" : "−"}${dec(Math.abs(g * 100), d)} %`);
const eur = (v) => (v == null ? "Sin dato" : `${Math.round(v).toLocaleString("es-ES")} €`);
const gdpEur = (v) => (v == null ? "Sin dato" : money(v));
const rankCache = new WeakMap();
function countOf(cities, key) {
  let m = rankCache.get(cities);
  if (!m) rankCache.set(cities, (m = new Map()));
  if (!m.has(key)) m.set(key, rankCount(cities, key));
  return m.get(key);
}

function rankBadge(rank, of, label, tip) {
  if (rank == null) return "";
  const tier = rank <= 10 ? "gold" : rank <= 50 ? "silver" : "bronze";
  return `<div class="cv-rank ${tier}" title="${esc(tip || `${label}: puesto ${rank} de ${of} áreas urbanas (1 = el más alto)`)}">
    <span class="cv-medal">#${rank}</span><span class="cv-rank-l">${esc(label)}</span></div>`;
}

function lqBadge(lq) {
  if (lq == null) return "";
  const tip = `Cociente de localización: este sector pesa ${dec(lq, 2)} veces lo que pesa en España`;
  const cls = lq >= 1.25 ? "hi" : lq <= 0.75 ? "lo" : "mid";
  return `<span class="cv-lq ${cls}" title="${esc(tip)}">×${dec(lq)}</span>`;
}

function medallion(id, fallback, bg, size = 18) {
  return `<span class="cv-med" style="--bg:${esc(bg)}">${icon(id, fallback, { size })}</span>`;
}

// --- header --------------------------------------------------------------------------------------------------------
function header(m) {
  const c = m.city, n = m.nation.nation;
  const cities = m.cityList;
  const col = css(m.stateRGB);
  const chips = m.states.map((s) => (s.index >= 0
    ? `<button class="chip" data-state="${s.index}" title="Abrir ${esc(s.name)}">${esc(s.abbr)}</button>`
    : `<span class="chip">${esc(s.abbr)}</span>`)).join("");
  const g = Number.isFinite(c.growth) ? c.growth : null;
  const yrs = Array.isArray(c.growth_years) ? c.growth_years : null;
  const growth = g == null ? "" : `<span class="cv-growth ${g >= 0 ? "good" : "bad"}" title="Variación de la población ${yrs ? `${yrs[0]}–${yrs[1]}` : ""} (Censo anual de población, INE). España: ${signed(n.growth)}">${g >= 0 ? "▲" : "▼"} ${dec(Math.abs(g * 100))} %${yrs ? ` <small>desde ${yrs[0]}</small>` : ""}</span>`;
  const r = c.ranks || {};
  const N = (k) => countOf(cities, k);
  return `
  <div class="sheet-grip cv-grip" aria-hidden="true"></div>
  <header class="cv-head" style="--sc:${col}">
    <div class="cv-ribbon" aria-hidden="true"></div>
    <button class="icon-btn cv-close" data-close aria-label="Cerrar la vista de ciudad (Esc)" title="Volver al mapa (Esc)">${icon("close", "✕", { size: 13 })}</button>
    <div class="cv-kind">Vista de ciudad · Área urbana funcional</div>
    <div class="cv-title">
      <div class="cv-crest" aria-hidden="true"><span>${esc(popShort(c.population))}</span></div>
      <div class="cv-tt">
        <h2 class="cv-name" tabindex="-1">${isCapital(c) ? `<span class="cv-cap" title="Capital del país">★</span> ` : ""}${esc(c.name)}</h2>
        <div class="cv-full">${esc(c.full || "")}</div>
        <div class="cv-typeslot" data-ctype></div>
        ${chips ? `<div class="chips">${chips}</div>` : ""}
      </div>
    </div>
    <div class="cv-headline">
      <div class="cv-big"><span class="lbl">${icon("pop", "👥", { size: 13 })} Población</span><b>${int(c.population)}</b>${growth}</div>
      <div class="cv-big"><span class="lbl" title="PIB imputado: estimación, no una cifra oficial del área urbana">${icon("y-gold", "💰", { size: 13 })} PIB imputado${c.gdp_year ? ` ${c.gdp_year}` : ""}</span><b>${gdpEur(c.gdp)}</b></div>
    </div>
    <div class="cv-ranks" aria-label="Puestos entre ${cities.length} áreas urbanas">
      ${rankBadge(r.population, N("population"), "Población")}
      ${rankBadge(r.gdp, N("gdp"), "PIB imputado")}
      ${rankBadge(r.growth, N("growth"), "Crecimiento", r.growth != null ? `Crecimiento: puesto ${r.growth} de ${N("growth")} (1 = el que más crece)` : "")}
    </div>
  </header>
  <nav class="cv-tabs" aria-label="Secciones de la vista de ciudad">
    ${TABS.map(([id, label, ic]) => `<button type="button" data-tab="${id}">${icon(ic, "•", { size: 14 })}<span>${label}</span></button>`).join("")}
  </nav>`;
}

// --- citizens ------------------------------------------------------------------------------------------------------
function citizens(m) {
  const c = m.city, n = m.nation.nation;
  // A meter row: the value, with the Spain value as a tick and a small line beside it.
  const row = (ic, fb, label, v, us, fmt, better, max, sub = us != null ? `España ${fmt(us)}` : "", tick = us) => `
    <div class="cv-stat">
      <div class="cv-stat-top"><span class="sl">${icon(ic, fb, { size: 14 })}${esc(label)}</span>
        <span class="sv"><b>${v == null ? "Sin dato" : fmt(v)}</b>${sub ? `<small>${sub}</small>` : ""}</span></div>
      ${v == null ? "" : meter(v, tick, max ?? Math.max(v || 0, us || 0) * 1.35, better)}
    </div>`;
  // Employed residents (by place of residence): a count has no Spain figure beside it, so the share of residents.
  const empShare = c.employed != null && c.population > 0 ? c.employed / c.population : null;
  const natEmpShare = n.employed != null && n.population > 0 ? n.employed / n.population : null;
  const empSub = empShare == null ? ""
    : `${pct(empShare)} de los habitantes${natEmpShare != null ? ` · España ${pct(natEmpShare)}` : ""}`;
  const multi = m.tiles.length > 1;
  const tilesNote = multi
    ? `En el mapa cada hexágono del área muestra <b>≈ habitantes</b> (densidad municipal por superficie del hexágono, una estimación) y su
       <b>uso principal del suelo</b> (peso en la superficie del hexágono)${m.residentsSum > 0
        ? `. Entre los ${m.tiles.length} hexágonos suman unos ${compact(m.residentsSum)} habitantes según esa estimación` : ""}.`
    : `Esta área cabe en un hexágono del mapa (unos ${compact(m.hexArea)} km²), mostrado con su ciudad.`;
  const land = (m.land || []).filter((g) => g.share != null);
  const landHtml = land.length
    ? `<h4 class="cv-h4">Uso del suelo <span class="muted">cobertura de los municipios del área</span></h4>
       <div class="cv-tl">${land.map((g) => `<span class="cv-tl-i"><i style="background:${esc(m.landColor(g.key))}"></i>${esc(g.label)} <small>${pct(g.share, 0)}</small></span>`).join("")}</div>`
    : "";
  return `
  <section class="cv-sec" id="cv-citizens" data-sec="citizens" aria-labelledby="cv-h-citizens">
    <h3 id="cv-h-citizens">${icon("pop", "👥", { size: 15 })}Habitantes</h3>
    <div class="cv-citizens" data-citizens>${citizensHtml(m, undefined)}</div>
    <div class="cv-stats">
      ${row("pop", "👥", "Ocupados residentes", c.employed, null, int, null, c.population, empSub, natEmpShare != null ? natEmpShare * c.population : null)}
      ${row("l-income", "💵", "Renta media por persona", c.income_per_person, n.income_per_person, eur, "high")}
    </div>
    <p class="cv-note">Los ocupados se cuentan según el lugar donde viven (Censo anual de población, INE). La renta es una media por persona, no una mediana (Atlas de distribución de renta de los hogares, INE).</p>
    ${landHtml}
    <div class="cv-legend-tiles"><p>${tilesNote}</p></div>
  </section>`;
}

// --- districts -----------------------------------------------------------------------------------------------------
function districts(m) {
  return `
  <section class="cv-sec" id="cv-districts" data-sec="districts" aria-labelledby="cv-h-districts">
    <h3 id="cv-h-districts">${icon("l-developed", "🏙", { size: 15 })}Especializaciones</h3>
    <div data-districts>${districtsHtml(m, undefined)}</div>
  </section>`;
}

// --- economy -------------------------------------------------------------------------------------------------------
function economy(m) {
  const c = m.city, nat = m.nation, n = nat.nation;
  const r = c.ranks || {};
  const cities = m.cityList;
  const yields = nat.yields.map((y) => {
    const v = c.yields?.[y.key];
    const rk = r[y.key];
    const isGdp = y.key === "gold";
    return `<div class="cv-yield" style="--yc:${esc(y.color)}" title="${esc(isGdp ? "PIB imputado" : y.label)}: ${esc(y.description || "")}">
      <div class="ico">${glyph(y, 20)}</div><div class="val">${v == null ? "Sin dato" : yieldValue(y, v)}</div>
      <div class="lbl">${esc(isGdp ? "PIB imputado" : y.label)}</div>
      ${rk != null ? `<div class="rk">#${rk} <small>de ${countOf(cities, y.key)}</small></div>` : ""}</div>`;
  }).join("");
  const natShareGdp = c.gdp != null && n.gdp ? c.gdp / n.gdp : null;
  return `
  <section class="cv-sec" id="cv-economy" data-sec="economy" aria-labelledby="cv-h-economy">
    <h3 id="cv-h-economy">${icon("y-gold", "💰", { size: 15 })}Economía</h3>
    <div class="cv-gdp">
      <div><span class="lbl">PIB imputado${c.gdp_year ? ` (${c.gdp_year})` : ""}</span><b>${gdpEur(c.gdp)}</b>${r.gdp != null ? `<small>puesto ${r.gdp} de ${countOf(cities, "gdp")}</small>` : ""}</div>
      <div><span class="lbl">Peso en el PIB de España</span><b>${natShareGdp != null ? pct(natShareGdp, 2) : "Sin dato"}</b><small>${pct(c.population / n.population, 2)} de los habitantes</small></div>
    </div>
    <p class="cv-note">PIB imputado: estimación a partir de ${esc(nat.gdp_vintage || "la Contabilidad Regional de España (INE)")}, repartida entre los municipios; no es una cifra oficial del área urbana.</p>
    <h4 class="cv-h4">Recursos del área <span class="muted">puesto entre las áreas urbanas</span></h4>
    <div class="cv-yields">${yields}</div>
    <p class="cv-note">Comida, producción, ciencia y cultura cuentan ocupados residentes por grupo de sectores CNAE; el PIB imputado va en euros.</p>
  </section>`;
}

// --- workforce -----------------------------------------------------------------------------------------------------
function workforce(m) {
  const cards = m.inds.map((d) => {
    const spec = d.lq != null && d.lq >= 1.25;
    return `<div class="cv-bld${spec ? " spec" : ""}" title="${esc(d.label)}: ${int(d.jobs)} ocupados residentes (${pct(d.share)}; España ${pct(d.natShare)})">
      ${medallion(d.icon, "•", d.color, 17)}
      <div class="cv-bld-t"><span class="cv-bld-n">${esc(d.short)}</span>
        <span class="cv-bld-v">${compact(d.jobs)} <small>${pct(d.share, 1)}</small></span></div>
      ${lqBadge(d.lq)}
    </div>`;
  }).join("");
  return `
  <section class="cv-sec" id="cv-workforce" data-sec="workforce" aria-labelledby="cv-h-workforce">
    <h3 id="cv-h-workforce">${icon("y-production", "⚙️", { size: 15 })}Empleo</h3>
    <p class="cv-lead">Sectores (CNAE) de los ${int(m.city.employed)} ocupados que viven en el área urbana. <span class="cv-lq hi">×N</span> compara el peso de un sector en la ciudad con su peso en España.</p>
    <div class="cv-blds">${cards || `<p class="muted cv-note">Sin dato de ocupados por sector.</p>`}</div>
    <p class="cv-note">${esc(m.nation.vintage)}: ocupados según su lugar de residencia, no según dónde están las empresas.</p>
  </section>`;
}

// --- compare -------------------------------------------------------------------------------------------------------
const COMPARE = {
  size: [
    ["Población", (c) => c.population, (v) => popShort(v)],
    ["Crecimiento", (c) => (Number.isFinite(c.growth) ? c.growth : null), (v) => signed(v)],
  ],
  economy: [
    ["Renta/persona", (c) => c.income_per_person, eur],
    ["Ocupados", (c) => c.employed, (v) => compact(v)],
    ["PIB imputado", (c) => c.gdp, gdpEur],
  ],
};

export function compareTable(m, set = "size") {
  const rows = [m.city, ...m.peers];
  const cols = COMPARE[set] || COMPARE.size;
  const max = cols.map(([, f]) => Math.max(...rows.map((c) => Math.abs(f(c) ?? 0))) || 1);
  return `<div class="cv-cmp" role="table" aria-label="${esc(m.city.name)} y las áreas parecidas">
    <div class="cv-cmp-r cv-cmp-h" role="row"><span role="columnheader">Área</span>${cols.map(([l]) => `<span role="columnheader">${esc(l)}</span>`).join("")}</div>
    ${rows.map((c, k) => `<div class="cv-cmp-r${k === 0 ? " me" : ""}" role="row">
      <span role="cell">${k === 0 ? `<b class="cv-cmp-n">${esc(c.name)}</b>` : `<button type="button" class="cv-cmp-n" data-peer="${esc(c.id)}" title="Abrir ${esc(c.full || c.name)} en la vista de ciudad">${esc(c.name)}</button>`}<small>${esc((c.states || []).join("–"))}</small></span>
      ${cols.map(([, f, fmt], j) => {
        const v = f(c);
        const col = v != null && v < 0 ? "#f08a6a" : k === 0 ? "#ecd08e" : "#8fa6bd";
        return `<span role="cell"><em>${v == null ? "Sin dato" : esc(fmt(v))}</em>${bar(v == null ? 0 : Math.abs(v) / max[j], col)}</span>`;
      }).join("")}
    </div>`).join("")}
  </div>`;
}

function compare(m) {
  return `
  <section class="cv-sec" id="cv-compare" data-sec="compare" aria-labelledby="cv-h-compare">
    <h3 id="cv-h-compare">${icon("layers", "⚖️", { size: 15 })}Comparar</h3>
    <p class="cv-lead">Las ${m.peers.length} áreas urbanas más cercanas en población. Pulsa una para abrirla.</p>
    <div class="cv-seg" role="group" aria-label="Medidas">
      <button type="button" data-set="size" aria-pressed="true">Tamaño</button>
      <button type="button" data-set="economy" aria-pressed="false">Economía</button>
    </div>
    <div data-compare>${compareTable(m, "size")}</div>
  </section>`;
}

function footer(m) {
  const nat = m.nation;
  return `<div class="cv-foot">Fuentes: ${esc(nat.vintage)}${nat.gdp_vintage ? `; PIB: ${esc(nat.gdp_vintage)}` : ""}. Los puestos se
    calculan entre las ${m.cityList.length} áreas urbanas del mapa.
    <a href="#" data-pedia>Almanaque ›</a></div>`;
}

/**
 * Fill the dock. handlers: {onClose, onState(idx), onPeer(id), onPedia,
 * loadData(name) → Promise<data|null>, onDistricts(list)} (the city's specialisations once districts.json is in,
 * for the map plaques).
 */
/**
 * Scrolls the dock to a section (its tab id, e.g. "districts"). Citizens and districts arrive later and change the
 * heights above, so the section is re-aligned as they do, for up to 4 s or until the user scrolls themselves.
 */
export function goToSection(el, id) {
  const sec = el?.querySelector(`[data-sec="${id}"]`);
  if (!sec) return false;
  const align = () => {
    const nav = el.querySelector(".cv-tabs");
    el.scrollTop = Math.max(0, sec.offsetTop - (nav?.offsetHeight || 0) - 4);
    el.onscroll?.(); // the tab spy (a scroll event is not always sent for a programmatic jump)
  };
  align();
  let ro = null;
  const stop = () => {
    ro?.disconnect();
    ro = null;
    for (const t of ["wheel", "touchstart", "keydown", "pointerdown"]) el.removeEventListener(t, stop);
  };
  for (const t of ["wheel", "touchstart", "keydown", "pointerdown"]) el.addEventListener(t, stop, { passive: true });
  if (typeof ResizeObserver === "function") {
    ro = new ResizeObserver(() => { if (sec.isConnected) align(); else stop(); });
    for (const c of el.children) ro.observe(c);
  }
  setTimeout(stop, 4000);
  return true;
}

export function render(el, m, h) {
  el.classList.add("cv-dock");
  el.style.setProperty("--sc", css(m.stateRGB));
  el.innerHTML = header(m) + citizens(m) + districts(m) + economy(m) + workforce(m) + compare(m) + footer(m);
  el.scrollTop = 0;

  el.querySelector("[data-close]").onclick = () => h.onClose();
  el.querySelectorAll("[data-state]").forEach((b) => (b.onclick = () => h.onState(+b.dataset.state)));
  el.querySelector("[data-pedia]").onclick = (e) => { e.preventDefault(); h.onPedia(); };

  // Compare: metric sets and peer links (delegated, the table is re-rendered).
  const cmp = el.querySelector("[data-compare]");
  el.querySelectorAll("[data-set]").forEach((b) => (b.onclick = () => {
    el.querySelectorAll("[data-set]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    cmp.innerHTML = compareTable(m, b.dataset.set);
  }));
  cmp.addEventListener("click", (e) => {
    const b = e.target.closest("[data-peer]");
    if (b) h.onPeer(b.dataset.peer);
  });

  // Tabs scroll to their section; the active tab follows the scroll position.
  const nav = el.querySelector(".cv-tabs");
  const tabs = [...el.querySelectorAll("[data-tab]")];
  const secs = tabs.map((t) => el.querySelector(`[data-sec="${t.dataset.tab}"]`));
  tabs.forEach((t, k) => (t.onclick = () => {
    const top = secs[k].offsetTop - nav.offsetHeight - 4;
    el.scrollTo({ top, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }));
  const spy = () => {
    const y = el.scrollTop + nav.offsetHeight + 24;
    let k = 0;
    secs.forEach((s, j) => { if (s.offsetTop <= y) k = j; });
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 4) k = secs.length - 1;
    tabs.forEach((t, j) => t.classList.toggle("on", j === k));
  };
  el.onscroll = spy;
  spy();

  // Citizens and districts arrive with their files (each loaded once, on demand).
  const czHost = el.querySelector("[data-citizens]");
  Promise.resolve(h.loadData?.("citizens")).then((data) => {
    if (!czHost.isConnected) return;
    czHost.innerHTML = citizensHtml(m, data ?? null);
    mountCitizens(czHost, m, data);
  }, () => { if (czHost.isConnected) czHost.innerHTML = citizensHtml(m, null); });
  const dHost = el.querySelector("[data-districts]");
  const typeSlot = el.querySelector("[data-ctype]");
  Promise.resolve(h.loadData?.("districts")).then((dd) => {
    if (!dHost.isConnected) return;
    dHost.innerHTML = districtsHtml(m, dd ?? null);
    typeSlot.innerHTML = badgeHtml(m, dd ?? null);
    h.onDistricts?.(dd ? cityDistricts(dd, m.city.id) : []);
  }, () => { if (dHost.isConnected) dHost.innerHTML = districtsHtml(m, null); });
}
