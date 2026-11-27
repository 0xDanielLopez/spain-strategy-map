// Hover tooltips for the map-art layers (HTML strings; every data value is escaped). Each says where the number comes
// from and the caveat that matters for it. A null value is never shown as 0: the line is left out or says "sin dato".
// Spain has airport passengers (Eurostat) but no port tonnage in this build (not openly licensed), so the port line only
// appear when a file brings them.
import { esc, compact, int } from "../../format.js";
import { portClass } from "./model.js";

const muted = (s) => `<span class="muted">${s}</span>`;
const isNum = (n) => typeof n === "number" && Number.isFinite(n);
const num = (n) => (isNum(n) ? compact(n) : "sin dato");
const dec = (n, d = 1) => n.toFixed(d).replace(".", ",");

const HUB_NAME = { L: "Aeropuerto grande", M: "Aeropuerto mediano", S: "Aeropuerto pequeño", N: "Aeropuerto principal" };
const AIRPORT_TYPE = { large_airport: "Aeropuerto grande", medium_airport: "Aeropuerto mediano", small_airport: "Aeropuerto pequeño", heliport: "Helipuerto", seaplane_base: "Base de hidroaviones", closed: "Aeropuerto cerrado" };
const PORT_CLASS = ["Puerto de primer orden", "Puerto importante", "Puerto"];
const ROAD_CLASS = { 0: "Autopista o autovía", 1: "Carretera principal" };
const RAIL_TIER = { 0: "Línea ferroviaria principal", 1: "Línea ferroviaria secundaria" };
const WONDER_KIND = { natural: "Espacio natural", recreation: "Espacio natural", coastal: "Espacio natural", monument: "Monumento", landmark: "Bien cultural", university: "Universidad" };
const RESOURCE_NOTE = "inventario de 2021";

const where = (...parts) => esc(parts.filter((p) => p != null && p !== "").join(", "));

/** The visible rule label of a heritage/park item: "Patrimonio mundial" or "Parque nacional". */
function wonderRule(x, rule) {
  const id = String(x.rule || rule?.id || "");
  const label = String(rule?.name || rule?.label || "");
  const hay = `${id} ${label} ${x.rule_name || ""}`.toLowerCase();
  if (/world|heritage|unesco|mundial/.test(hay)) return "Patrimonio mundial";
  if (/park|parque/.test(hay)) return "Parque nacional";
  return label || x.rule_name || "";
}

export const tips = {
  port(p) {
    const cls = PORT_CLASS[portClass(p)] || "Puerto";
    const lines = [`<b>${esc(p.name || "Puerto")}</b> ${p.state ? muted(esc(p.state)) : ""}`.trim(), esc(cls)];
    if (isNum(p.tons)) lines.push(`<b>${num(p.tons)}</b> toneladas${p.year ? ` (${esc(p.year)})` : ""}`);
    else lines.push(muted("Sin cifras de tráfico: no hay datos con licencia abierta."));
    if (isNum(p.scalerank)) lines.push(muted(`Categoría ${esc(p.scalerank)} de Natural Earth (0 = mayor)`));
    return lines.join("<br>");
  },
  airport(a) {
    const kind = a.hub ? HUB_NAME[a.hub] || a.hub : AIRPORT_TYPE[a.type] || "Aeropuerto";
    const lines = [`<b>${esc([a.id, a.name].filter(Boolean).join(" · ") || "Aeropuerto")}</b> ${a.city ? muted(esc(a.city)) : ""}`.trim(), esc(kind)];
    if (isNum(a.passengers)) lines.push(`<b>${num(a.passengers)}</b> pasajeros${a.passengers_year ? ` en ${esc(a.passengers_year)}` : ""} (llegadas y salidas)`);
    return lines.join("<br>");
  },
  road(r) {
    const cls = typeof r?.class === "string" ? r.class : ROAD_CLASS[r?.cls ?? r?.class];
    return [`<b>${esc(r?.name || "Carretera")}</b>`, esc(cls || "Carretera")].join("<br>");
  },
  rail(r) {
    const tier = typeof r?.tier === "string" ? r.tier : RAIL_TIER[r?.tier];
    return [`<b>${esc(r?.name || "Ferrocarril")}</b>`, esc(tier || "Línea ferroviaria")].join("<br>");
  },
  /** A resource site (resources.json item): the type name, the value in MW and the detail. */
  resource(it, typeName) {
    const lines = [`<b>${esc(it.name || typeName || "Recurso")}</b> ${it.state ? muted(esc(it.state)) : ""}`.trim()];
    if (typeName && it.name) lines.push(esc(typeName));
    if (isNum(it.value)) lines.push(`<b>${it.value >= 100 ? int(it.value) : dec(it.value)}</b> MW de capacidad`);
    if (it.detail) lines.push(esc(it.detail));
    lines.push(muted(`Datos del ${RESOURCE_NOTE}.`));
    return lines.join("<br>");
  },
  wonder(x, m) {
    const rule = m.data.wonders?.rules?.find((r) => r.id === x.rule);
    const ruleName = wonderRule(x, rule);
    const mt = x.metrics || {};
    const lines = [`<b>${esc(x.name)}</b> ${x.state ? muted(where(x.state)) : ""}`.trim()];
    lines.push(esc([ruleName, WONDER_KIND[x.kind]].filter((v, i, a) => v && a.indexOf(v) === i).join(" · ") || "Patrimonio y parques"));
    if (isNum(mt.area_km2)) lines.push(`${int(mt.area_km2)} km²`);
    if (isNum(mt.visits)) lines.push(`<b>${num(mt.visits)}</b> visitas${mt.year ? ` (${esc(mt.year)})` : ""}`);
    if (mt.designated) lines.push(`Declarado en ${esc(mt.designated)}`);
    const serial = x.serial_note || x.serial || mt.serial_note;
    if (serial) lines.push(muted(esc(typeof serial === "string" ? serial : "Bien en serie: varios lugares bajo una sola declaración.")));
    if (rule?.text) lines.push(muted(esc(rule.text)));
    return lines.join("<br>");
  },
};
