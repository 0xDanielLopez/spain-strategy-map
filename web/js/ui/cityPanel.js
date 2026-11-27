import { css } from "../color.js";
import { esc } from "../format.js";
import { isCapital } from "../world.js";
import { scope, scopesNow, scopeLinksHtml } from "../app/scope.js";
import { yieldGrid, amenities, industries, gdpRow, popLine, growthSpan, showPanel, hidePanel } from "./infoPanel.js";

/**
 * ctx: {w, nation, onClose, onPedia, onState(stateIndex)}
 */
export function openCityPanel(city, ctx) {
  const { w, nation } = ctx;
  const n = nation.nation;
  const owner = city.cell != null ? w.raw.owner[city.cell] : -1;
  const col = css(w.stateColor[owner] || [190, 190, 190]);

  // The city's states as links to their state panels.
  const states = (city.states || [])
    .map((abbr) => ({ abbr, i: w.raw.states.findIndex((s) => s.abbr === abbr) }))
    .map(({ abbr, i }) => (i >= 0 && ctx.onState
      ? `<button class="chip" data-state="${i}" title="Abrir ${esc(w.raw.states[i].name)}">${esc(abbr)}</button>`
      : `<span class="chip">${esc(abbr)}</span>`))
    .join("");

  const growth = growthSpan(city, n);
  // A city map has only the figures it measured: a row whose city value is missing is left out, never "–" or 0.
  const measured = !scope() || Number.isFinite(city.unemployment) || Number.isFinite(city.income_per_person);
  const economy = ((measured ? amenities(city, n) : "") + gdpRow(city)).trim();

  showPanel({
    kind: "city",
    stripe: col,
    title: city.name,
    titleHtml: `${isCapital(city) ? `<span class="cap" title="Capital del Estado">★</span> ` : ""}${esc(city.name)}`,
    sub: `${esc(city.full || "")}${states ? `<div class="chips">${states}</div>` : ""}${scopeLinksHtml(scopesNow(), city.id)}`,
    headExtra: popLine(city, growth),
    sections: [
      // Sections without data are left out (a city map may carry only population and income).
      city.yields && { title: "Rendimientos", html: `<div class="yield-grid">${yieldGrid(nation, city.yields)}</div>` },
      economy && { title: "Economía", html: economy },
      city.jobs && { title: "Sectores · dónde trabaja la gente", html: industries(city, nation) },
    ],
    foot: scope()
      ? `Fuente: ${esc(nation.vintage || "")}. Renta: media por persona, no mediana. ${esc(scope().note || "")}`
      : `Fuente: ${esc(nation.vintage)} ${nation.gdp_vintage ? `; PIB: ${esc(nation.gdp_vintage)}` : ""}.
      Verde ×N = el peso de este sector en el empleo es N veces el de España. Renta: media por persona, no mediana. El PIB de cada área es una imputación a partir del PIB provincial.`,
    onClose: ctx.onClose,
    onPedia: ctx.onPedia,
    wire(panel) {
      panel.querySelectorAll("[data-state]").forEach((b) => (b.onclick = () => ctx.onState(+b.dataset.state)));
    },
  });
}

export const closeCityPanel = hidePanel;
