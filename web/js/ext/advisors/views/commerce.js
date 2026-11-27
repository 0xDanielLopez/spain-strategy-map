// Infraestructuras: puertos, aeropuertos y red de carreteras y ferrocarril (infrastructure.json).
// Sin cifras de tráfico: los pasajeros y las toneladas de puertos no tienen licencia abierta, así que no se muestran.
import { esc, fin } from "../core/util.js";
import { int } from "../core/fmt.js";
import { swatchLegend } from "../core/charts.js";
import { createTable } from "../core/table.js";
import { section, tiles, segmented } from "../core/view.js";
import { focusPoint } from "../core/frame.js";
import { attributionHtml } from "../core/data.js";

const PORT_COLOR = "#4f9ad6", AIR_COLOR = "#e6cf86";
const AIR_TYPE = { large_airport: "Grande", medium_airport: "Mediano" };

// Port class from Natural Earth's scalerank (same cut-offs as the map layer): 1 = most important.
const portClass = (p) => (p.scalerank <= 2 ? 1 : p.scalerank <= 5 ? 2 : 3);
const PORT_CLASS_NAME = { 1: "Mayor", 2: "Intermedio", 3: "Menor" };
const PORT_SIZE = { 1: 3, 2: 1.8, 3: 1 };
const AIR_SIZE = { large_airport: 3, medium_airport: 1.5 };

export async function mount(ctx) {
  const { app, el, link } = ctx;
  const infra = await app.loadData("infrastructure");
  if (!infra) {
    el.innerHTML = `<p class="adv-empty pad">Todavía no hay datos de infraestructuras, así que no hay nada que mostrar aquí.</p>`;
    return {};
  }
  const stateName = new Map((app.data.states || []).map((s) => [s.abbr, s.name]));
  const ports = (infra.ports || []).map((p) => ({ ...p, key: `p${p.id}` }));
  const airports = (infra.airports || []).map((a) => ({ ...a, key: `a${a.id}` }));
  const nRoad = [], nRail = [];
  for (const r of infra.roads || []) nRoad[r[2]] = (nRoad[r[2]] || 0) + 1;
  for (const r of infra.rail || []) nRail[r[2]] = (nRail[r[2]] || 0) + 1;
  const v = infra.vintage || {};
  let portTable = null, airTable = null, portBubbles = null, airBubbles = null;

  // --- cabecera -----------------------------------------------------------------------------------------------
  const nLarge = airports.filter((a) => a.type === "large_airport").length;
  el.insertAdjacentHTML("beforeend", tiles([
    { label: "Puertos", value: int(ports.length), sub: "principales, de Natural Earth" },
    { label: "Aeropuertos", value: int(airports.length), sub: `${int(nLarge)} grandes y ${int(airports.length - nLarge)} medianos` },
    { label: "Tramos de autopista o autovía", value: int(nRoad[0] || 0), sub: "enlaces entre casillas" },
  ]) + `<p class="adv-callout">${esc(infra.note || "Sin cifras de tráfico.")}</p>`);

  // --- puertos --------------------------------------------------------------------------------------------------
  const portHover = (p) => {
    link.hover(p ? { cells: new Set(p.cell != null ? [p.cell] : []), label: p.name } : null);
    portBubbles?.setHot(p ? p.key : null);
  };
  const pBody = section(el, { title: "Puertos", kicker: esc(v.ports || ""), note: "Puertos principales, ordenados por la clase que les da Natural Earth (de mayor a menor importancia). No hay toneladas: esa cifra no tiene licencia abierta." });
  portTable = createTable(pBody, {
    caption: "Puertos principales", rank: true, maxHeight: 300, search: "Buscar puertos",
    searchText: (p) => `${p.name} ${stateName.get(p.state) || p.state || ""}`,
    columns: [
      { key: "name", label: "Puerto", align: "l", width: "minmax(0,1.5fr)", value: (p) => p.name, text: (p) => p.name },
      { key: "state", label: "CCAA", align: "l", width: "minmax(0,1.2fr)", value: (p) => stateName.get(p.state) || p.state, text: (p) => stateName.get(p.state) || p.state || "sin dato" },
      { key: "cls", label: "Clase", align: "l", width: "86px", value: (p) => (fin(p.scalerank) ? p.scalerank : null), text: (p) => (fin(p.scalerank) ? PORT_CLASS_NAME[portClass(p)] : "sin dato"), title: "Clase de Natural Earth (scalerank): menor número, más importante" },
    ],
    rows: [...ports].sort((a, b) => (fin(a.rank) ? a.rank : 1e9) - (fin(b.rank) ? b.rank : 1e9)),
    sort: { key: "cls", dir: "asc" },
    onHover: portHover,
    onClick: (p) => flyTo(p),
  });
  pBody.insertAdjacentHTML("beforeend", `<p class="adv-note">${int(ports.length)} puertos. Las posiciones son las de Natural Earth, aproximadas.</p>`);

  // --- aeropuertos ----------------------------------------------------------------------------------------------
  const airHover = (a) => {
    link.hover(a ? { cells: new Set(a.cell != null ? [a.cell] : []), label: `${a.id} · ${a.name || a.city}` } : null);
    airBubbles?.setHot(a ? a.key : null);
  };
  const aBody = section(el, { title: "Aeropuertos", kicker: esc(v.airports || ""), note: "Aeropuertos grandes y medianos según OurAirports. Sin cifra de pasajeros: la que publica Aena no tiene licencia abierta." });
  airTable = createTable(aBody, {
    caption: "Aeropuertos grandes y medianos", rank: true, maxHeight: 300, search: "Buscar aeropuertos",
    searchText: (a) => `${a.id} ${a.name} ${a.city || ""} ${stateName.get(a.state) || ""}`,
    columns: [
      { key: "city", label: "Aeropuerto", align: "l", width: "minmax(0,1.3fr)", value: (a) => a.name || a.city, html: (a) => `${esc((a.name || a.city || "").replace(/^Aeropuerto (de )?/, ""))} <span class="sub">${esc(a.id)}</span>`, tip: (a) => a.name },
      { key: "state", label: "CCAA", align: "l", width: "minmax(0,1.2fr)", value: (a) => stateName.get(a.state) || a.state, text: (a) => stateName.get(a.state) || a.state || "sin dato" },
      { key: "type", label: "Tipo", align: "l", width: "76px", value: (a) => AIR_SIZE[a.type] ?? null, text: (a) => AIR_TYPE[a.type] || "sin dato", title: "Tipo de OurAirports" },
    ],
    rows: airports,
    sort: { key: "type", dir: "desc" },
    onHover: airHover,
    onClick: (a) => flyTo(a),
  });

  // --- en el mapa -----------------------------------------------------------------------------------------------
  const mBody = section(el, { title: "En el mapa", note: "Cada círculo es un puerto o un aeropuerto. El tamaño sigue su clase, no su tráfico." });
  let show = "both";
  segmented(mBody, {
    label: "Mostrar", value: show,
    options: [{ value: "both", label: "Puertos y aeropuertos" }, { value: "ports", label: "Puertos" }, { value: "air", label: "Aeropuertos" }],
    onChange: (x) => { show = x; drawSites(); },
  });
  mBody.insertAdjacentHTML("beforeend", swatchLegend([{ label: "Puertos", color: PORT_COLOR }, { label: "Aeropuertos", color: AIR_COLOR }]));
  portBubbles = ctx.bubbles("ports", {
    rMax: 14, alpha: 0.5,
    tip: (b) => `<b>${esc(b.it.name)}</b><br>Puerto · clase ${esc(PORT_CLASS_NAME[portClass(b.it)].toLowerCase())}${b.it.state ? ` · ${esc(stateName.get(b.it.state) || b.it.state)}` : ""}`,
    onHover: (b) => portTable?.setHot(b ? b.key : null),
    onClick: (b) => { portTable?.setHot(b.key); flyTo(b.it); },
  });
  airBubbles = ctx.bubbles("airports", {
    rMax: 14, alpha: 0.5,
    tip: (b) => `<b>${esc(b.it.id)} · ${esc(b.it.name)}</b><br>Aeropuerto ${esc((AIR_TYPE[b.it.type] || "").toLowerCase())}${b.it.city ? ` · ${esc(b.it.city)}` : ""}`,
    onHover: (b) => airTable?.setHot(b ? b.key : null),
    onClick: (b) => { airTable?.setHot(b.key); flyTo(b.it); },
  });
  function drawSites() {
    portBubbles.set(show !== "air" ? ports.filter((p) => fin(p.scalerank)).map((p) => ({ key: p.key, x: p.x, y: p.y, value: PORT_SIZE[portClass(p)], color: PORT_COLOR, it: p })) : [], { vMax: 3 });
    airBubbles.set(show !== "ports" ? airports.filter((a) => AIR_SIZE[a.type]).map((a) => ({ key: a.key, x: a.x, y: a.y, value: AIR_SIZE[a.type], color: AIR_COLOR, it: a })) : [], { vMax: 3 });
  }
  drawSites();

  // --- carreteras y ferrocarril ---------------------------------------------------------------------------------
  const nBody = section(el, { title: "Carreteras y ferrocarril", note: "Red esquemática de Natural Earth: es arte de mapa, no una estadística de kilómetros." });
  const toggles = (() => { try { return app.ui.mapToggles?.() || []; } catch { return []; } })();
  nBody.innerHTML = `<p class="adv-note">${(infra.road_classes || []).map((c, i) => `<b>${esc(c.name)}</b>: ${int(nRoad[i] || 0)} tramos entre casillas`).join(" · ")}<br>${(infra.rail_tiers || []).map((c, i) => `<b>${esc(c.name)}</b>: ${int(nRail[i] || 0)} tramos entre casillas`).join(" · ")}</p>
    <p class="adv-note">${esc(infra.rules?.roads || "")}</p><p class="adv-note">${esc(infra.rules?.rail || "")}</p>
    ${toggles.length ? `<p class="adv-note">Activa o desactiva las carreteras, el ferrocarril y los puertos desde el menú <b>Mapa</b>, junto a Recursos.</p>` : ""}`;

  function flyTo(p) {
    if (!p || !fin(p.x) || !fin(p.y)) return;
    focusPoint(app, p.x, p.y, Math.min(app.cam.maxScale, Math.max(app.cam.scale, (app.cam.fitScale || 1) * 3)));
  }

  el.insertAdjacentHTML("beforeend", attributionHtml([infra], [
    "Sin cifras de tráfico: ni pasajeros ni toneladas, porque Aena y Puertos del Estado no publican con licencia abierta.",
    "Las carreteras y los ferrocarriles de Natural Earth son una versión simplificada, no la red real: el ferrocarril de nivel secundario es especialmente denso y es arte de mapa.",
    "Los puertos son los principales de Natural Earth (sin tildes en los nombres); los aeropuertos, los grandes y medianos de OurAirports.",
  ]));

  return {
    onMapHover(h) {
      if (h.item?.kind === "port") portTable?.setHot(`p${h.item.data?.id}`);
      if (h.item?.kind === "airport") airTable?.setHot(`a${h.item.data?.id}`);
    },
    onMapClick(ev) {
      if (ev.item?.kind === "port" || ev.item?.kind === "airport") { flyTo(ev.item.data); return true; }
      return false;
    },
  };
}
