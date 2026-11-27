// Patrimonio y parques: bienes españoles del Patrimonio Mundial de la UNESCO y parques nacionales (wonders.json).
// Sin cifras de visitantes: los datos abiertos de Wikidata no las traen y no se inventan.
import { esc, fin, el as mk } from "../core/util.js";
import { int } from "../core/fmt.js";
import { section, tiles, segmented } from "../core/view.js";
import { createTable } from "../core/table.js";
import { frameBox, focusPoint } from "../core/frame.js";
import { attributionHtml } from "../core/data.js";

const KIND = {
  monument: { label: "Cultural", color: "#e0b54c" },
  natural: { label: "Natural", color: "#6aa84f" },
  landmark: { label: "Mixto o sin criterio", color: "#c9a0e0" },
};
const RULE_TITLE = { patrimonio_mundial: "Patrimonio Mundial", parque_nacional: "Parques nacionales" };

export async function mount(ctx) {
  const { app, el, link } = ctx;
  const won = await app.loadData("wonders");
  const wonders = (won?.wonders || []).map((w) => ({ ...w, key: w.id }));
  if (!won || !wonders.length) {
    el.innerHTML = `<p class="adv-empty pad">Todavía no hay datos de patrimonio y parques, así que no hay nada que mostrar aquí.</p>`;
    return {};
  }
  const states = app.data.states || [];
  const stateName = new Map(states.map((s) => [s.abbr, s.name]));
  const stateIdx = new Map(states.map((s, i) => [s.abbr, i]));
  const heritage = wonders.filter((w) => w.rule === "patrimonio_mundial");
  const parks = wonders.filter((w) => w.rule === "parque_nacional");
  const nat = won.national || {};
  const tables = [];
  const kindOf = (w) => (w.rule === "parque_nacional" ? "natural" : w.kind);
  const colorOf = (w) => (w.rule === "parque_nacional" ? "#2f9e6e" : KIND[w.kind]?.color || "#ccc");

  // --- cabecera -------------------------------------------------------------------------------------------------
  const regions = new Set(wonders.map((w) => w.state).filter(Boolean)).size;
  el.insertAdjacentHTML("beforeend", tiles([
    { label: "Patrimonio Mundial", value: int(fin(nat.patrimonio_mundial) ? nat.patrimonio_mundial : heritage.length), sub: "marcadores con casilla en el mapa" },
    { label: "Parques nacionales", value: int(fin(nat.parques_nacionales) ? nat.parques_nacionales : parks.length), sub: "con casilla en el mapa" },
    { label: "Comunidades", value: int(regions), sub: "con al menos un marcador" },
  ]) + `<p class="adv-callout">Son los bienes que tienen una coordenada en Wikidata dentro de España. No hay cifras de visitantes ni de superficie.</p>`);

  // --- mapa -----------------------------------------------------------------------------------------------------
  const bubbles = ctx.bubbles("wonders", {
    rMax: 9, minR: 9, alpha: 0.28,
    tip: (b) => `<b>${esc(b.it.name)}</b><br>${esc(RULE_TITLE[b.it.rule] || b.it.rule)} · ${esc(b.it.rule === "parque_nacional" ? "Parque nacional" : KIND[b.it.kind]?.label || "")}${b.it.state ? ` · ${esc(stateName.get(b.it.state) || b.it.state)}` : ""}${b.it.serial ? `<br><span class="sub">bien en serie: el marcador es un punto representativo</span>` : ""}`,
    onHover: (b) => { for (const t of tables) t.setHot(b ? b.key : null); },
    onClick: (b) => flyTo(b.it),
  });
  const wonderHover = (w) => {
    link.hover(w ? { cells: new Set(w.cells && w.cells.length ? w.cells : w.cell != null ? [w.cell] : []), label: w.short || w.name } : null);
    bubbles.setHot(w ? w.key : null);
  };
  const mkTable = (host, list, caption) => {
    const t = createTable(host, {
      caption, rank: true, maxHeight: 300, search: "Buscar por nombre o comunidad",
      searchText: (w) => `${w.name} ${stateName.get(w.state) || w.state || ""}`,
      columns: [
        { key: "name", label: "Nombre", align: "l", width: "minmax(0,1.8fr)", value: (w) => w.short || w.name, html: (w) => `<i class="dot" style="background:${colorOf(w)}"></i>${esc(w.short || w.name)}${w.serial ? ` <span class="sub">en serie</span>` : ""}`, tip: (w) => w.name },
        { key: "state", label: "CCAA", align: "l", width: "minmax(0,1fr)", value: (w) => stateName.get(w.state) || w.state, text: (w) => stateName.get(w.state) || w.state || "sin dato" },
        ...(list === heritage ? [{ key: "kind", label: "Tipo", align: "l", width: "88px", hideBelow: 380, value: (w) => KIND[w.kind]?.label, text: (w) => KIND[w.kind]?.label || "sin dato" }] : []),
      ],
      rows: list, sort: { key: "name", dir: "asc" },
      onHover: wonderHover,
      onClick: (w) => flyTo(w),
    });
    tables.push(t);
    return t;
  };

  // --- Patrimonio Mundial ---------------------------------------------------------------------------------------
  const rule = (id) => (won.rules || []).find((r) => r.id === id);
  const hBody = section(el, { title: "Patrimonio Mundial", kicker: "Lista de la UNESCO", note: esc(rule("patrimonio_mundial")?.text || "") });
  let kind = "all";
  const hHost = mk("div");
  const hTable = mkTable(hHost, heritage, "Bienes españoles del Patrimonio Mundial");
  segmented(hBody, {
    label: "Tipo", value: kind,
    options: [{ value: "all", label: "Todos" }, ...Object.entries(KIND).filter(([k]) => heritage.some((w) => w.kind === k)).map(([k, v]) => ({ value: k, label: v.label }))],
    onChange: (x) => { kind = x; hTable.setRows(heritage.filter((w) => kind === "all" || w.kind === kind)); drawMarkers(); },
  });
  hBody.appendChild(hHost);

  // --- Parques nacionales ---------------------------------------------------------------------------------------
  const pBody = section(el, { title: "Parques nacionales", kicker: "Parques de España", note: esc(rule("parque_nacional")?.text || "") });
  const pHost = mk("div");
  pBody.appendChild(pHost);
  mkTable(pHost, parks, "Parques nacionales");

  function drawMarkers() {
    const vis = [...heritage.filter((w) => kind === "all" || w.kind === kind), ...(kind === "all" || kind === "natural" ? parks : [])];
    bubbles.set(vis.filter((w) => fin(w.x) && fin(w.y)).map((w) => ({ key: w.key, x: w.x, y: w.y, value: 1, color: colorOf(w), it: w })), { vMax: 1 });
  }
  drawMarkers();
  pBody.insertAdjacentHTML("beforeend", `<p class="adv-note">Marcadores del mapa: <i class="dot" style="background:${KIND.monument.color}"></i>Patrimonio cultural · <i class="dot" style="background:${KIND.natural.color}"></i>Patrimonio natural · <i class="dot" style="background:${KIND.landmark.color}"></i>mixto o sin criterio · <i class="dot" style="background:#2f9e6e"></i>parque nacional.</p>`);

  // --- por comunidad --------------------------------------------------------------------------------------------
  const cBody = section(el, { title: "Por comunidad", note: "Cuántos bienes y parques con marcador hay en cada comunidad autónoma. Un bien en serie cuenta solo en la comunidad de su punto representativo." });
  const cRows = states.map((s) => ({ key: s.abbr, name: s.name, h: heritage.filter((w) => w.state === s.abbr).length, p: parks.filter((w) => w.state === s.abbr).length }))
    .filter((r) => r.h + r.p > 0);
  const cTable = createTable(cBody, {
    caption: "Patrimonio y parques por comunidad", rank: true, maxHeight: 300, search: "Buscar comunidades", rows: cRows,
    columns: [
      { key: "name", label: "Comunidad", align: "l", width: "minmax(0,1.6fr)", value: (r) => r.name, text: (r) => r.name },
      { key: "h", label: "Patrimonio", short: "Patrimonio Mundial", value: (r) => r.h, text: (r) => int(r.h), bar: { max: Math.max(...cRows.map((r) => r.h), 1), color: "rgba(224,181,76,.3)" } },
      { key: "p", label: "Parques", short: "Parques nacionales", value: (r) => r.p, text: (r) => int(r.p), bar: { max: Math.max(...cRows.map((r) => r.p), 1), color: "rgba(47,158,110,.3)" } },
    ],
    sort: { key: "h", dir: "desc" },
    onHover: (r) => link.hover(r && stateIdx.has(r.key) ? { states: new Set([stateIdx.get(r.key)]), dimOthers: true, label: r.name } : null),
  });

  function flyTo(w) {
    if (!w) return;
    if (w.cells && w.cells.length > 2) {
      const b = app.highlightBounds({ cells: new Set(w.cells) });
      if (b) return frameBox(app, b, { pad: 60, maxScale: 3 });
    }
    if (fin(w.x) && fin(w.y)) focusPoint(app, w.x, w.y, Math.min(app.cam.maxScale, Math.max(app.cam.scale, (app.cam.fitScale || 1) * 3.2)));
  }

  el.insertAdjacentHTML("beforeend", attributionHtml([won], [
    "Faltan dos bienes españoles del Patrimonio Mundial porque su coordenada en Wikidata cae fuera de España (los bosques de hayas de los Cárpatos y el patrimonio del mercurio de Almadén e Idrija).",
    "En los bienes en serie o en red el marcador es un punto representativo, no todo el conjunto.",
    "El tipo cultural, natural o mixto sale de los criterios UNESCO que da Wikidata; el parque nacional se deduce de su clase en Wikidata, no de una lista oficial.",
    "Algunos espacios, como Doñana, son a la vez Patrimonio Mundial y parque nacional y aparecen en las dos listas; los parques marinos o con islotes pueden no tener casilla.",
  ]));

  return {
    onMapHover(h) {
      if (h.item?.kind === "wonder") for (const t of tables) t.setHot(h.item.data?.id ?? null);
      const owner = h.cell >= 0 ? app.w.raw.owner[h.cell] : -1;
      const sr = owner >= 0 ? app.data.states?.[owner] : null;
      cTable.setHot(sr ? sr.abbr : null, false);
    },
    onMapClick(ev) {
      if (ev.item?.kind !== "wonder") return false;
      flyTo(wonders.find((w) => w.id === ev.item.data?.id));
      return true;
    },
  };
}
