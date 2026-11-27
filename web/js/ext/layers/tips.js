// Hover tooltips for the map-art layers (HTML strings; every data value is escaped). Each says where the number comes
// from and the caveat that matters for it (FAF values are model estimates; bases have no published headcount; the
// trade arc is a drawing aid; curated landmarks are an editorial pick).
import { esc, compact, int, pct } from "../../format.js";
import { FORT_KINDS, fortKind, WONDER_KINDS } from "../../render/art/sites.js";
import { MODE_STYLE } from "../../render/art/improvements.js";

const muted = (s) => `<span class="muted">${s}</span>`;
const num = (n, d = 1) => (n == null || !Number.isFinite(n) ? "–" : compact(n));
const sign = (x) => (x > 0 ? "+" : x < 0 ? "−" : "±");

function usd(n) {
  if (n == null || !Number.isFinite(n)) return "–";
  const a = Math.abs(n);
  const d = (x, k) => x.toFixed(k).replace(".", ",");
  if (a >= 1e12) return `${d(n / 1e12, 2)} billones de €`;
  if (a >= 1e9) return `${d(n / 1e9, a >= 1e10 ? 1 : 2)} mil millones de €`;
  if (a >= 1e6) return `${d(n / 1e6, 1)} millones de €`;
  return `${int(n)} €`;
}

const HUB_NAME = { L: "Aeropuerto grande", M: "Aeropuerto mediano", S: "Aeropuerto pequeño", N: "Aeropuerto principal sin hub" };
const PORT_TYPE = { coastal: "Puerto costero", great_lakes: "Puerto de los Grandes Lagos", inland: "Puerto fluvial" };

export const tips = {
  port(p, m) {
    const yr = p.year ?? "";
    const lines = [
      `<b>${esc(p.name)}</b> ${muted(`${esc(PORT_TYPE[p.type] || "Puerto")}, ${esc(p.state || "")}`)}`,
      `n.º ${esc(p.rank)} por tonelaje · <b>${num(p.tons)}</b> toneladas (${esc(yr)})`,
    ];
    if (p.foreign != null || p.domestic != null) lines.push(`Exterior ${num(p.foreign)} · nacional ${num(p.domestic)}`);
    if (p.imports != null || p.exports != null) lines.push(`Importaciones ${num(p.imports)} · exportaciones ${num(p.exports)}`);
    lines.push(muted("Puertos principales; situados en el centro del área portuaria (los puertos fluviales largos son aproximados)."));
    return lines.join("<br>");
  },
  airport(a) {
    const lines = [`<b>${esc(a.id)} · ${esc(a.name)}</b> ${muted(esc([a.city, a.state].filter(Boolean).join(", ")))}`];
    lines.push(a.hub ? esc(HUB_NAME[a.hub] || a.hub) : "Aeropuerto de carga (no es un aeropuerto principal de pasajeros)");
    if (a.enplanements != null) {
      let ch = "";
      if (a.enplanements_prev > 0) {
        const r = a.enplanements / a.enplanements_prev - 1;
        ch = ` (${sign(r)}${Math.abs(r * 100).toFixed(1).replace(".", ",")} % sobre ${a.year - 1})`;
      }
      lines.push(`<b>${num(a.enplanements)}</b> embarques en ${esc(a.year)}${ch}`);
    }
    if (a.cargo_lbs != null) lines.push(`Peso de carga aterrizada ${num(a.cargo_lbs)} lb`);
    lines.push(muted("Datos anuales de embarques y carga."));
    return lines.join("<br>");
  },
  fort(f, m) {
    const comp = m.data.military?.components?.find((c) => c.id === f.component);
    const name = comp?.name || FORT_KINDS[fortKind(f.component)]?.name || "Instalación de defensa";
    const tier = { major: "Instalación principal", base: "Base", site: "Instalación" }[f.tier] || "";
    const status = { act: "", semi: " · semiactiva", care: " · en mantenimiento" }[f.status] ?? "";
    const lines = [
      `<b>${esc(f.name)}</b> ${muted(esc(f.state || ""))}`,
      `${esc(name)}${f.joint ? " · base conjunta" : ""} · ${esc(tier)}${esc(status)}`,
    ];
    if (f.area_km2 != null) lines.push(`Perímetro ${int(f.area_km2)} km²`);
    lines.push(muted("Tamaño según la superficie: no se publica el personal de cada base."));
    return lines.join("<br>");
  },
  range(r, m) {
    const comp = m.data.military?.components?.find((c) => c.id === r.component);
    return [
      `<b>${esc(r.name)}</b> ${muted(esc(r.state || ""))}`,
      `Terreno restringido · ${esc(comp?.name || "")} · ${int(r.area_km2)} km²`,
      muted("Uno de los 30 mayores recintos de defensa, dibujado sobre las casillas que cubre."),
    ].join("<br>");
  },
  wonder(x, m) {
    const k = WONDER_KINDS[x.kind]?.name || "Maravilla";
    const rule = m.data.wonders?.rules?.find((r) => r.id === x.rule);
    const mt = x.metrics || {};
    const lines = [`<b>${esc(x.name)}</b> ${muted(esc([x.state].filter(Boolean).join("")))}`];
    if (x.kind === "university") {
      lines.push(`${esc(k)} · n.º ${esc(x.rank)} por gasto en investigación`);
      if (mt.rd_usd != null) lines.push(`I+D ${usd(mt.rd_usd)} (${esc(mt.year)})${mt.federal_usd != null ? `, ${pct(mt.federal_usd / mt.rd_usd, 0)} público` : ""}`);
      if (mt.enrollment != null) lines.push(`${int(mt.enrollment)} estudiantes (${esc(mt.enrollment_year)})`);
    } else if (x.curated) {
      lines.push(`${esc(k)} · selección propia (no ordenada por datos)`);
      if (mt.visits != null) lines.push(`${num(mt.visits)} visitas (${esc(mt.year)})`);
      if (mt.designated) lines.push(`Hito histórico desde ${esc(mt.designated)}`);
    } else {
      lines.push(`${esc(k)} · n.º ${esc(x.rank)} por visitas${mt.unit_type ? ` entre ${esc(mt.unit_type === "National Park" ? "los parques nacionales" : "otros espacios protegidos")}` : ""}`);
      if (mt.visits != null) lines.push(`<b>${num(mt.visits)}</b> visitas (${esc(mt.year)})${mt.visits_of ? ` ${muted(`(${esc(mt.visits_of)})`)}` : ""}`);
      if (mt.area_km2 != null) lines.push(`${int(mt.area_km2)} km²`);
    }
    if (rule?.text) lines.push(muted(esc(rule.text)));
    return lines.join("<br>");
  },
  route(rt, m) {
    const r = rt.route;
    const t = m.data.trade || {};
    const a = rt.a?.short || rt.a?.name || r.a, b = rt.b?.short || rt.b?.name || r.b;
    const modes = Object.entries(r.modes || {}).filter(([, v]) => v >= 0.05).sort((p, q) => q[1] - p[1])
      .map(([k, v]) => `${esc(MODE_STYLE[k]?.label || k)} ${Math.round(v * 100)}%`).join(" · ");
    const com = t.commodities?.[r.top_commodity];
    const lines = [
      `<b>${esc(a)} ⇄ ${esc(b)}</b> ${muted(`ruta comercial n.º ${esc(r.rank)}`)}`,
      `<b>${usd(r.value_musd * 1e6)}</b> de mercancías al año, ${num(r.tons_k * 1e3)} toneladas (estimación ${esc(t.year ?? "")})`,
    ];
    if (modes) lines.push(modes);
    if (com) lines.push(`Mercancía principal: ${esc(com)}`);
    lines.push(muted("Suma de ambos sentidos. Se dibuja como un arco entre la mayor ciudad de cada zona: los datos recogen dónde empieza y acaba la carga, no su ruta."));
    return lines.join("<br>");
  },
};
