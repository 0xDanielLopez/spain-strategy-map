// City scope support: ?scope=<id> opens the same map for one city (data/city/<id>/*.json) instead of Spain.
// Everything here is a no-op in national mode (no ?scope), so the national page behaves exactly as before.
const ID = /^[a-z0-9-]+$/;

const requested = (() => {
  try {
    const v = new URLSearchParams(location.search).get("scope");
    return v && ID.test(v) ? v : null;
  } catch {
    return null;
  }
})();
let current = null;

/** The scope id from the URL, or null for the national map. */
export const scopeId = () => requested;
/** Folder (with trailing slash) the data files are read from. */
export const dataBase = () => (requested ? `data/city/${requested}/` : "data/");
/** world.scope of the loaded scope, or null (national map, or world.json without a scope object). */
export const scope = () => current;
export const setScope = (world) => { current = requested && world?.scope ? world.scope : null; };

const DEFAULT_LEVELS = {
  state: { one: "Comunidad", many: "Comunidades" },
  county: { one: "Municipio", many: "Municipios" },
};

/**
 * Word for a level: lvl("state") = "comunidad", lvl("state", {many: true, cap: true}) = "Comunidades".
 * level: "state" (comunidades autónomas / districts) or "county" (municipios / census sections).
 */
export function lvl(level, { many = false, cap = false } = {}) {
  const w = current?.levels?.[level]?.[many ? "many" : "one"] ?? DEFAULT_LEVELS[level][many ? "many" : "one"];
  return (cap ? w[0].toUpperCase() : w[0].toLowerCase()) + w.slice(1);
}

/** Name of the area the figures are compared with: "España" nationally, the scope name in a scope. */
export const nationName = () => current?.name || current?.title || "España";

/** The grid's hex radius in km: world.scope.hex_km in a scope, else the world's own grid radius. */
export const hexKm = (world) => current?.hex_km ?? world?.grid?.radius ?? null;

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/** Page chrome for a scope: document title, brand, "España" link, search placeholder, permanent estimate note. */
const SCOPE_ATTRIBUTION =
  "Secciones censales, población y renta: elaboración propia con datos del INE (www.ine.es) · Cobertura del suelo © ESA WorldCover 2021 (CC BY 4.0)";

/** Short data credit for the share image: the scope's sources, or null on the national map. */
export function scopeCredit() {
  return current ? "Datos: INE, ESA WorldCover" : null;
}

export function applyScopeChrome() {
  if (!current) return;
  const title = current.title || current.name || "Ciudad";
  document.title = `${title} · Spain Strategy Map`;
  document.body.classList.add("scope-map");
  const brand = document.querySelector(".brand");
  const text = brand?.querySelector(".brand-text");
  if (text) text.textContent = title;
  brand?.setAttribute("title", title);
  if (brand && !document.getElementById("scope-back")) {
    const a = document.createElement("a");
    a.id = "scope-back";
    a.href = location.pathname; // same page, no query: the national map
    a.textContent = "España";
    a.title = "Volver al mapa de España";
    a.style.cssText = "margin-left:10px;padding:2px 8px;border:1px solid var(--gold,#c9a45c);border-radius:4px;color:var(--gold-bright,#e8c777);font-size:12px;letter-spacing:.06em;text-decoration:none;white-space:nowrap;flex:none";
    brand.insertAdjacentElement("afterend", a);
  }
  // A city map uses other sources than the national one: the footer must credit those (INE asks for this wording).
  const credit = document.getElementById("attribution");
  if (credit) credit.textContent = SCOPE_ATTRIBUTION;
  const input = document.getElementById("search-input");
  if (input) {
    const label = `Buscar ${lvl("state", { many: true })} y ${lvl("county", { many: true })}`;
    input.setAttribute("aria-label", `${label} (/ o Ctrl K)`);
  }
  document.getElementById("map")?.setAttribute("aria-label", `Mapa de ${title} en hexágonos`);
  const yields = document.getElementById("yields");
  if (yields) yields.setAttribute("aria-label", `Rendimientos de ${current.name || title}`);
  if (current.note && !document.getElementById("scope-note")) {
    const n = document.createElement("div");
    n.id = "scope-note";
    n.textContent = current.note;
    n.style.cssText = "position:fixed;left:12px;top:calc(var(--topbar-h,40px) + 8px);z-index:9;max-width:min(92vw,340px);padding:4px 8px;border-radius:6px;font-size:11px;line-height:1.35;pointer-events:none;background:rgba(255,255,255,0.85);color:#3a3f47";
    document.body.appendChild(n);
  }
}

/** Short Spanish message with a link to the national map (unknown scope or broken data). */
export function showScopeError(el) {
  if (!el) return;
  el.classList.add("error");
  el.innerHTML = `No hay un mapa de ciudad llamado «${esc(requested)}». <a href="${esc(location.pathname)}">Volver al mapa de España</a>`;
}

/**
 * National map only: links to the city maps of an open city, read from data/city/index.json
 * ({"scopes":[{id,name,kind,city,...}]}). A missing or malformed file means no links, never an error.
 */
let indexLoad = null;
let indexNow = [];
export const scopesNow = () => indexNow;
export function loadScopeIndex() {
  if (requested) return Promise.resolve([]);
  indexLoad ??= fetch("data/city/index.json")
    .then((r) => (r.ok ? r.json() : null))
    .then((j) => (Array.isArray(j?.scopes) ? j.scopes.filter((s) => s && ID.test(String(s.id))) : []))
    .catch(() => [])
    .then((l) => (indexNow = l));
  return indexLoad;
}

export function scopeLinksHtml(scopes, cityId) {
  if (requested || !cityId) return "";
  const mine = scopes.filter((s) => s.city === cityId);
  if (!mine.length) return "";
  const label = (s) => (s.kind === "urban_area" ? "Área urbana" : "Municipio");
  return `<div class="chips scope-links">${mine
    .map((s) => `<a class="chip" href="?scope=${esc(s.id)}" title="${esc(s.title || s.name || "")}">Mapa de la ciudad · ${label(s)}</a>`)
    .join("")}</div>`;
}
