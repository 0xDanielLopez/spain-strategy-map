// Keyboard & mouse cheat-sheet.
import { icon } from "../ui/icon.js";
import { lvl } from "./scope.js";

const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "");
const MOD = isMac ? "⌘" : "Ctrl";

const rowsNow = () => [
  ["Moverse", [
    [["Arrastrar", "←↑→↓", "WASD"], "Desplazar el mapa"],
    [["Rueda", "+", "–"], "Acercar y alejar"],
    [["Doble clic"], "Acercar a un punto"],
    [["Dos dedos"], "Pellizca para hacer zoom, arrastra para desplazar (táctil)"],
    [["Minimapa"], "Haz clic o arrastra para saltar"],
  ]],
  ["Explorar", [
    [["Clic en ciudad"], "Abrir la pantalla de la ciudad"],
    [["Clic en tierra"], `Abrir ${lvl("state") === "comunidad" ? "esa comunidad" : "ese " + lvl("state")}`],
    [["/", `${MOD} K`], `Buscar ${lvl("state", { many: true })} y ${lvl("county", { many: true })}`],
    [["L", "Shift L"], "Lente siguiente / anterior"],
    [["Leyenda"], "Pasa el ratón o arrastra por la escala para mostrar solo ese rango"],
    [["R"], "Mostrar u ocultar recursos"],
  ]],
  ["Paneles", [
    [["?"], "Esta ayuda"],
    [["Esc"], "Cerrar ayuda, búsqueda, Almanaque y después el panel"],
  ]],
];

export function initHelp() {
  const modal = document.getElementById("help");
  if (!modal) return { open() {}, close() {}, get isOpen() { return false; } };
  const card = modal.querySelector(".help-card");
  let restore = null;
  card.innerHTML = `
    <button class="icon-btn help-close" data-close aria-label="Cerrar la ayuda">${icon("close", "✕", { size: 13 })}</button>
    <h2 id="help-title">${icon("help", "?", { size: 22 })}<span>Controles</span></h2>
    <div class="help-cols">${rowsNow().map(([title, rows]) => `
      <section><h3>${title}</h3>${rows.map(([keys, what]) => `
        <div class="help-row"><span class="keys">${keys.map((k) => `<kbd>${k}</kbd>`).join("")}</span><span>${what}</span></div>`).join("")}
      </section>`).join("")}</div>
    <p class="help-foot">Cada número sale de datos públicos: abre el <b>Almanaque</b> para ver las fuentes.
      El enlace de la barra de direcciones reabre siempre esta misma vista.
      Código fuente: <a href="https://github.com/0xDanielLopez/spain-strategy-map" target="_blank" rel="noopener">github.com/0xDanielLopez/spain-strategy-map</a> (código MIT, datos según los términos de cada fuente; consulta el README).<br>Basado en usaciv de Andrej Karpathy (MIT).</p>`;

  const close = () => {
    if (modal.hidden) return;
    modal.hidden = true;
    if (restore && document.contains(restore)) restore.focus();
    restore = null;
  };
  modal.addEventListener("click", (e) => {
    if (e.target === modal || e.target.closest("[data-close]")) close();
  });
  modal.addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;
    e.preventDefault(); // the only focusable control is the close button
    card.querySelector("[data-close]").focus();
  });

  return {
    open() {
      if (!modal.hidden) return;
      restore = document.activeElement;
      modal.hidden = false;
      card.querySelector("[data-close]").focus();
    },
    close,
    toggle() { modal.hidden ? this.open() : close(); },
    get isOpen() { return !modal.hidden; },
  };
}
