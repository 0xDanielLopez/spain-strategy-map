// Energía: las centrales nucleares, hidroeléctricas y de gas del inventario histórico de 2021 (resources.json).
import { esc, fin } from "../core/util.js";
import { fmtValue, mw, int, count3 } from "../core/fmt.js";
import { barList, shareBar, stackedBars, sizeLegend } from "../core/charts.js";
import { createTable } from "../core/table.js";
import { section, tiles, chips } from "../core/view.js";
import { frameBox, focusPoint } from "../core/frame.js";
import { attributionHtml } from "../core/data.js";
import { glyph } from "../../../ui/icon.js";

const GROUPS = [
  { id: "thermal", label: "Centrales térmicas", types: ["nuclear", "gas"] },
  { id: "water", label: "Hidroeléctricas", types: ["hydro"] },
];

export function mount(ctx) {
  const { app, data, el, link } = ctx;
  const res = app.data.resources;
  if (!res) {
    el.innerHTML = `<p class="adv-empty pad">Todavía no hay datos de centrales eléctricas, así que no hay nada que mostrar aquí.</p>`;
    return {};
  }
  const types = res.types;
  const typeById = new Map(types.map((t) => [t.id, t]));
  const items = res.items.map((it, i) => ({ ...it, idx: i, key: String(i) }));
  const nat = res.summary?.national || {};
  const isMW = (t) => typeById.get(t)?.unit === "MW";
  const mwTypes = types.filter((t) => t.unit === "MW");
  const states = app.data.states || [];
  const stateIdx = new Map(states.map((s, i) => [s.abbr, i]));
  // Draw groups in GROUPS order, plus any type the groups do not list.
  const listed = new Set(GROUPS.flatMap((g) => g.types));
  const groups = GROUPS.map((g) => ({ ...g, types: g.types.filter((t) => typeById.has(t)) })).filter((g) => g.types.length);
  const extra = types.filter((t) => !listed.has(t.id)).map((t) => t.id);
  if (extra.length) groups.push({ id: "other", label: "Otras", types: extra });

  const st = { on: new Set(types.map((t) => t.id)), min: 0, state: null };
  ctx.setShowResources(true);

  // --- headline -------------------------------------------------------------------------------------------------
  const totalMW = mwTypes.reduce((a, t) => a + (nat[t.id]?.value || 0), 0);
  const sites = mwTypes.reduce((a, t) => a + (nat[t.id]?.count || 0), 0);
  const top = el.appendChild(document.createElement("div"));
  top.innerHTML = tiles([
    { label: "Potencia representada", value: mw(totalMW), sub: `${int(sites)} centrales` },
    ...mwTypes.map((t) => ({ label: t.name, value: mw(nat[t.id]?.value), sub: `${int(nat[t.id]?.count || 0)} centrales` })),
  ]) + `<p class="adv-callout">${esc(res.note || res.summary?.note || "Totales de las centrales representadas, no de toda España.")}</p>`;

  // --- national mix ---------------------------------------------------------------------------------------------
  const mixBody = section(el, { title: "Mix de las centrales representadas", kicker: esc(res.vintage || "Inventario de 2021"), note: "Capacidad instalada (MW) de las centrales del mapa, por tipo. Es el inventario histórico de 2021: no incluye eólica ni solar, y las centrales de carbón y petróleo no se dibujan. <b>No</b> es la capacidad total de España." });
  const mixParts = mwTypes.map((t) => ({ key: t.id, label: t.name, value: nat[t.id]?.value || 0, color: t.color, text: mw(nat[t.id]?.value), icon: glyph(t, 14) })).sort((a, b) => b.value - a.value);
  const mixHover = (p) => {
    if (!p) { link.hover(null); bubbles.setSelected(null); return; }
    const set = new Set(visible().filter((it) => it.type === p.key).map((it) => it.idx));
    link.hover({ resources: set, dimOthers: true });
    bubbles.setSelected(new Set(visible().filter((it) => it.type === p.key).map((it) => it.key)));
  };
  const solo = (typeId) => {
    const only = st.on.size === 1 && st.on.has(typeId);
    st.on = only ? new Set(types.map((t) => t.id)) : new Set([typeId]);
    typeChips.set(st.on);
    apply();
  };
  shareBar(mixBody, { parts: mixParts, legend: false, onHover: mixHover, onClick: (p) => solo(p.key) });
  const mixBars = barList(mixBody, {
    rows: mixParts.map((p) => ({ ...p, sub: `${int(nat[p.key]?.count || 0)} centrales` })),
    onHover: mixHover, onClick: (p) => solo(p.key), ariaLabel: "Capacidad representada por tipo",
  });

  // --- filters --------------------------------------------------------------------------------------------------
  const fBody = section(el, { title: "Filtrar el mapa", note: "Activa o desactiva tipos (Alt + clic para ver solo uno). El mapa atenúa el terreno y dibuja cada central como un círculo según su capacidad." });
  const typeChips = chips(fBody, {
    label: "Tipos de central",
    items: groups.flatMap((g) => g.types.map((t) => {
      const ty = typeById.get(t);
      return { key: t, label: ty.name, color: ty.color, icon: glyph(ty, 13), count: nat[t]?.count ?? null };
    })),
    onChange: (on) => { st.on = on; apply(); },
  });
  const quick = document.createElement("div");
  quick.className = "adv-row";
  quick.innerHTML = groups.map((g) => `<button type="button" class="adv-mini" data-g="${g.id}">${esc(g.label)}</button>`).join("") +
    `<button type="button" class="adv-mini" data-g="all">Todas</button><button type="button" class="adv-mini" data-g="none">Ninguna</button>`;
  fBody.appendChild(quick);
  quick.addEventListener("click", (e) => {
    const g = e.target.closest("[data-g]")?.dataset.g;
    if (!g) return;
    st.on = g === "all" ? new Set(types.map((t) => t.id)) : g === "none" ? new Set() : new Set(groups.find((x) => x.id === g).types);
    typeChips.set(st.on);
    apply();
  });
  const slider = document.createElement("div");
  slider.className = "adv-slider";
  slider.innerHTML = `<label><span>Tamaño mínimo</span><input type="range" min="0" max="2000" step="100" value="0" aria-label="Capacidad mínima de la central en MW"><b>Cualquiera</b></label>`;
  fBody.appendChild(slider);
  const range = slider.querySelector("input");
  range.addEventListener("input", () => {
    st.min = +range.value;
    slider.querySelector("b").textContent = st.min ? `≥ ${int(st.min)} MW` : "Cualquiera";
    apply();
  });
  const stateChip = document.createElement("div");
  stateChip.className = "adv-row adv-filterbar";
  fBody.appendChild(stateChip);
  stateChip.addEventListener("click", (e) => { if (e.target.closest("[data-clear-state]")) setState(null); });
  const legendBox = document.createElement("div");
  fBody.appendChild(legendBox);

  // --- top sites ------------------------------------------------------------------------------------------------
  const tBody = section(el, { title: "Centrales", note: "Todas las centrales que pasan los filtros. Pasa el ratón para localizarla en el mapa; haz clic para ir a ella." });
  const sizeSort = (r) => (isMW(r.type) && fin(r.value) ? r.value : null);
  const table = createTable(tBody, {
    caption: "Centrales representadas",
    search: "Buscar centrales y comunidades",
    searchText: (r) => `${r.name} ${r.state || ""} ${r.detail || ""} ${typeById.get(r.type)?.name || ""}`,
    rank: true,
    columns: [
      { key: "name", label: "Central", align: "l", width: "minmax(0,1.7fr)", value: (r) => r.name, html: (r) => `<span class="ic">${glyph(typeById.get(r.type), 13)}</span>${esc(r.name)}` },
      { key: "type", label: "Tipo", align: "l", width: "minmax(0,1fr)", value: (r) => typeById.get(r.type)?.name, text: (r) => typeById.get(r.type)?.name || r.type },
      { key: "state", label: "CCAA", align: "l", width: "46px", value: (r) => r.state, text: (r) => r.state || "–" },
      { key: "value", label: "Capacidad", width: "minmax(0,.95fr)", value: sizeSort, text: (r) => sizeText(r), title: "Ordenar por capacidad instalada (MW)" },
    ],
    rows: [],
    sort: { key: "value", dir: "desc" },
    maxHeight: 300,
    onHover: (r) => {
      link.hover(r ? { resources: new Set([r.idx]), dimOthers: true, label: r.name } : null);
      bubbles.setHot(r ? r.key : null);
    },
    onClick: (r) => flyTo(r),
  });
  function sizeText(r) {
    const t = typeById.get(r.type);
    if (!fin(r.value)) return "sin dato";
    if (t?.unit === "MW") return mw(r.value);
    return `${fmtValue("float", r.value)} ${t?.unit || ""}`.trim();
  }
  function flyTo(r) {
    focusPoint(app, r.x, r.y, Math.min(app.cam.maxScale, Math.max(app.cam.scale, (app.cam.fitScale || 1) * 3.2)));
  }

  // --- por comunidad -------------------------------------------------------------------------------------------
  const sBody = section(el, { title: "Potencia por comunidad", note: "Capacidad representada por comunidad autónoma y tipo. Haz clic en una comunidad para filtrar todo por ella; otro clic la quita." });
  const stSum = res.summary?.states || {};
  const stateRows = states
    .map((s, i) => {
      const by = stSum[s.abbr] || {};
      const parts = Object.fromEntries(mwTypes.filter((t) => fin(by[t.id]?.value)).map((t) => [t.id, by[t.id].value]));
      const total = Object.values(parts).reduce((a, v) => a + v, 0);
      return { key: s.abbr, label: s.name, idx: i, parts, total, text: mw(total) };
    })
    .filter((r) => r.total > 0)
    .sort((a, b) => b.total - a.total);
  const stacks = stackedBars(sBody, {
    rows: stateRows, keys: mwTypes.map((t) => ({ key: t.id, label: t.name, color: t.color })), fmt: (v) => mw(v),
    ariaLabel: "Capacidad representada por comunidad",
    onHover: (x) => {
      if (!x) return link.hover(null);
      const sIdx = x.row.idx;
      const set = x.part ? new Set(items.filter((it) => it.state === x.row.key && it.type === x.part).map((it) => it.idx)) : undefined;
      link.hover({ states: new Set([sIdx]), resources: set, dimOthers: true, label: x.part ? `${x.row.label}: ${typeById.get(x.part)?.name || x.part}` : x.row.label });
    },
    onClick: (x) => setState(st.state === x.row.key ? null : x.row.key, true),
  });
  const withPower = new Set(stateRows.map((r) => r.key));
  const noPower = states.filter((s) => !withPower.has(s.abbr)).map((s) => s.name);
  if (noPower.length) sBody.insertAdjacentHTML("beforeend", `<p class="adv-note">Sin centrales representadas: ${esc(noPower.join(", "))}.</p>`);

  // --- explainer ------------------------------------------------------------------------------------------------
  const eBody = section(el, { title: "Qué significa cada símbolo", note: "Cada tipo de central, cuántas hay en el mapa y de dónde salen los datos." });
  eBody.innerHTML = groups.map((g) => `<h4 class="adv-h4">${esc(g.label)}</h4>${g.types.map((t) => {
    const ty = typeById.get(t);
    const s = nat[t] || {};
    const total = fin(s.value) ? mw(s.value) : "";
    return `<div class="adv-explain" style="--cc:${esc(ty.color)}"><span class="ic">${glyph(ty, 22)}</span><div>
      <b>${esc(ty.name)}</b> <span class="sub">${int(s.count || 0)} en el mapa${total ? ` · ${esc(total)}` : ""} · en ${esc(ty.unit)}</span>
      <p>${esc(ty.description)}</p></div></div>`;
  }).join("")}`).join("");

  el.insertAdjacentHTML("beforeend", attributionHtml([res], [
    `${esc(res.vintage || "Inventario de 2021")}: es una foto antigua. Una central cerrada o puesta en marcha después de 2021 no está reflejada.`,
    "Los totales son solo de las centrales representadas, no la capacidad de España. La eólica y la solar no se dibujan porque el inventario de 2021 está muy incompleto.",
    "La capacidad instalada (MW) no es lo que produce la central: una de 1.000 MW genera en un año una fracción de esa capacidad, según cuántas horas funcione.",
    "El mapa muestra un icono por casilla: una central que cae a menos de 2 casillas de otra puede no dibujarse.",
  ]));

  // --- map ------------------------------------------------------------------------------------------------------
  const bubbles = ctx.bubbles("sites", {
    rMax: 24,
    tip: (b) => {
      const it = b.it, t = typeById.get(it.type);
      return `<b>${esc(it.name)}</b><br>${esc(t.name)} · <b>${esc(mw(it.value))}</b>${it.state ? ` · ${esc(it.state)}` : ""}${it.detail ? `<br><span class="sub">${esc(it.detail)}</span>` : ""}`;
    },
    onHover: (b) => table.setHot(b ? b.key : null),
    onClick: (b) => { table.setHot(b.key); flyTo(b.it); },
  });

  function visible() {
    return items.filter((it) => st.on.has(it.type) && (!st.min || (isMW(it.type) && fin(it.value) && it.value >= st.min)) && (!st.state || it.state === st.state));
  }

  function setState(abbr, fly = false) {
    st.state = abbr;
    stacks.setSelected(abbr);
    apply();
    if (abbr && fly) {
      const b = app.highlightBounds({ states: new Set([stateIdx.get(abbr)]) });
      if (b) frameBox(app, b, { pad: 30, maxScale: 2.6 });
    }
  }

  function apply() {
    const typesOn = st.min ? new Set([...st.on].filter(isMW)) : st.on;
    const all = typesOn.size === types.length && !st.min;
    ctx.setResourceFilter(all ? null : { types: new Set(typesOn), minValue: st.min || undefined });
    const vis = visible();
    table.setRows(vis);
    const mwVis = vis.filter((it) => isMW(it.type) && fin(it.value));
    const vMax = Math.max(1, ...items.filter((it) => isMW(it.type) && fin(it.value)).map((it) => it.value));
    bubbles.set(mwVis.map((it) => ({ key: it.key, x: it.x, y: it.y, value: it.value, color: typeById.get(it.type).color, it })), { vMax });
    const sIdx = st.state ? stateIdx.get(st.state) : null;
    link.base({ dimOthers: true, states: sIdx != null ? new Set([sIdx]) : undefined });
    stateChip.innerHTML = st.state
      ? `<span class="adv-fchip">Comunidad: <b>${esc(states[sIdx]?.name || st.state)}</b> · ${int(vis.length)} centrales<button type="button" data-clear-state aria-label="Quitar el filtro de comunidad">✕</button></span>`
      : "";
    const r = (v) => 24 * Math.sqrt(v / vMax);
    legendBox.innerHTML = sizeLegend([250, 1000, 4000].filter((v) => v <= vMax * 1.2), r, (v) => `${int(v)} MW`, "Superficie del círculo = capacidad");
    mixBars.setSelected(st.on.size === 1 ? [...st.on][0] : null);
  }
  apply();

  return {
    onMapHover(h) {
      if (h.resource) {
        const it = items[res.items.indexOf(h.resource)];
        if (it) table.setHot(it.key);
      }
    },
    onEscape() {
      if (st.state) { setState(null); return true; }
      return false;
    },
    destroy() {},
  };
}
