// City View "Especializaciones": the city's sector specialisations from districts.json (INE jobs by CNAE section,
// residents by place of residence), shown as strategy-game districts named by sector. A specialisation is a CNAE
// section whose weight in the city's employed residents is well above its weight in Spain (location quotient).
//
//   cityDistricts(ddata, id) → [district]   the city's specialisations, strongest first, each with what the dock and
//                                           the map plaques need ({id, name, short, color, icon, lq, emp, …})
//   badgeOf(ddata, id) → {label, text, color, icon, district} | null | undefined   the city-type badge
//   districtsHtml(m, ddata) → HTML          the section body
//   badgeHtml(m, ddata) → HTML              the header badge
import { esc, int, pct } from "../../format.js";
import { compact } from "./fmt.js";
import { icon } from "../../ui/icon.js";
import { hasIcon } from "../../icons.js";

// Short plaque names by CNAE letter (the catalog names are long; the map clips plaques to about 18 characters).
const SHORT = {
  a: "Agricultura", b: "Extractivas", c: "Industria", d: "Energía", e: "Agua y residuos", f: "Construcción",
  g: "Comercio", h: "Transporte", i: "Hostelería", j: "Comunicaciones", k: "Finanzas", l: "Inmobiliarias",
  m: "Prof. y ciencia", n: "Admin. y apoyo", o: "Administración", p: "Educación", q: "Sanidad", r: "Artes y ocio",
  s: "Otros servicios",
};

const catCache = new WeakMap();
function catalog(ddata) {
  let m = catCache.get(ddata);
  if (!m) catCache.set(ddata, (m = new Map((ddata?.catalog || []).map((c) => [c.id, c]))));
  return m;
}

/** The catalog icon when the icon set draws it, else null (canvas plaques then use the emoji). */
export function iconFor(cat) {
  return cat?.icon && hasIcon(cat.icon) ? cat.icon : null;
}

/** The city's specialisations: districts.json entries (strongest first) joined with their catalog entry. */
export function cityDistricts(ddata, id) {
  const cat = catalog(ddata);
  const row = ddata?.cities?.[id] || null;
  return (row?.districts || []).map((d) => {
    const c = cat.get(d.id) || {};
    return {
      ...d, name: c.name || ddata?.industries?.[d.id]?.title || String(d.id).toUpperCase(),
      short: SHORT[d.id] || c.name || String(d.id).toUpperCase(),
      color: c.color || "#5a6a7a", icon: iconFor(c), emoji: "◆", cat: c, mapLq: d.lq,
    };
  });
}

/** The city-type badge; undefined while districts.json is loading, null when there is none. */
export function badgeOf(ddata, id) {
  if (!ddata) return ddata; // undefined (loading) or null (missing)
  const row = ddata.cities?.[id];
  if (!row) return null;
  if (!row.badge) {
    return { label: "Perfil diversificado", text: "Ningún sector destaca por encima del peso que tiene en España", color: "#6a7484", icon: null, district: null };
  }
  const c = catalog(ddata).get(row.badge.district) || {};
  return { ...row.badge, color: c.color || "#6a7484", icon: iconFor(c), emoji: "◆" };
}

export function badgeHtml(m, ddata) {
  const b = badgeOf(ddata, m.city.id);
  if (!b) return "";
  return `<span class="cv-type${b.district ? "" : " plain"}" style="--tc:${esc(b.color)}" title="Tipo de ciudad: ${esc(b.text || b.label)} (Censo anual de población ${esc(String(ddata.year || ""))}, INE)">
    <span class="cv-type-ic">${icon(b.icon, b.emoji || "◆", { size: 13 })}</span>${esc(b.label)}</span>`;
}

const dec = (v, d = 1) => v.toFixed(d).replace(".", ",");

function lqTag(lq, tip) {
  if (lq == null) return "";
  const cls = lq >= 1.25 ? "hi" : lq <= 0.75 ? "lo" : "mid";
  return `<span class="cv-lq ${cls}" title="${esc(tip || `Cociente de localización: ${dec(lq, 2)} veces el peso que tiene en España`)}">×${dec(lq)}</span>`;
}

function districtCard(d) {
  const c = d.cat || {};
  const facts = [];
  if (d.emp != null) {
    facts.push(`<div><span>Ocupados</span><b>${compact(d.emp)}</b><small>${d.share != null ? `${pct(d.share, 1)} de los ocupados` : ""}</small></div>`);
  }
  if (d.strength != null) {
    facts.push(`<div title="Ocupados por encima de la media nacional: ocupados menos ocupados entre el cociente de localización (así se ordenan las especializaciones)"><span>Sobre la media</span><b>${compact(Math.max(0, d.strength))}</b><small>ocupados</small></div>`);
  }
  const caveat = c.caveat ? `<p class="cv-dc-cav">${esc(c.caveat)}</p>` : "";
  return `<div class="cv-dc" style="--dc:${esc(d.color)}" title="${esc(c.description || "")}">
    <div class="cv-dc-h"><span class="cv-dc-hex">${icon(d.icon, d.emoji, { size: 18 })}</span>
      <div class="cv-dc-t"><b>${esc(d.name)}</b><small>${esc(c.description || "")}</small></div>
      ${d.lq != null ? lqTag(d.lq, `Cociente de localización: el peso de este sector en los ocupados de la ciudad es ${dec(d.lq, 2)} veces el de España.`) : ""}</div>
    ${facts.length ? `<div class="cv-dc-f">${facts.join("")}</div>` : ""}
    ${caveat}
  </div>`;
}

/** The Especializaciones section body. ddata: districts.json (undefined while loading, null when missing). */
export function districtsHtml(m, ddata) {
  if (ddata === undefined) return `<p class="muted cv-note">Cargando las especializaciones…</p>`;
  if (!ddata) return `<p class="muted cv-note">Las especializaciones no están disponibles.</p>`;
  const id = m.city.id;
  const row = ddata.cities?.[id] || null;
  const list = cityDistricts(ddata, id);
  const b = badgeOf(ddata, id);
  let lead;
  if (!row) {
    lead = `<p class="cv-lead">Sin dato: no hay ocupados por sector para ${esc(m.city.name)}, así que no se calculan especializaciones.</p>`;
  } else {
    lead = `<p class="cv-lead">${b?.district ? `<b class="cv-type-l" style="--tc:${esc(b.color)}">${esc(b.label)}</b> · ${esc(b.text || "")}. ` : ""}${
      row.emp != null ? `Se cuentan ${int(row.emp)} ocupados que viven en el área urbana.` : ""}</p>`;
  }
  const cards = list.length
    ? `<div class="cv-dcs">${list.map(districtCard).join("")}</div>`
    : row ? `<p class="muted cv-note">Ninguna especialización supera la regla: los sectores de los ocupados de ${esc(m.city.name)} pesan casi como en España.</p>` : "";
  return `${lead}
    ${cards}
    <div class="cv-schematic">
      <p><b>◆ En el mapa</b> cada especialización aparece como una placa sobre un hexágono del área, cerca de la ciudad. Las posiciones son esquemáticas: indican en qué se especializa el área, no dónde están las empresas.</p>
    </div>
    <details class="cv-more cv-rule"><summary>Cómo se eligen</summary>
      <p>${esc(ddata.rule?.text || "")}</p>
    </details>
    <p class="cv-note">${esc(ddata.vintage || "INE")}. ${esc(ddata.note || "")} ×N = cociente de localización frente a España.</p>`;
}
