// City View "Habitantes" rows: the urban area's people as rows of small figures (citizens.json, INE).
//
//   citizensHtml(m, data) → HTML      the rows (placeholders for the figure canvases)
//   mountCitizens(host, m, data)       paints the figures and wires the hover / focus read-out
//
// Three rows, each with its own base (the file's `bases`): age and nationality over all residents, education over
// residents aged 15 or more. Each row: N figures from the file (largest-remainder rounded by the pipeline), a caption
// ("cada figura ≈ 760 mil habitantes"), a read-out line that a hovered or focused figure fills ("1 de cada 5
// habitantes de Madrid tiene 65 años o más (España: 1 de cada 5)"), and a thin national bar for comparison.
// A row the INE left out is said so, never drawn as zeros.
import { esc, int, pct } from "../../format.js";
import { compact } from "./fmt.js";
import { CATEGORY_COLOR, figureCanvas, loadPainter } from "./figures.js";

const ROWS = [
  { id: "age", title: "Edad", noun: "habitantes" },
  { id: "education", title: "Estudios", noun: "habitantes de 15 años o más" },
  { id: "nationality", title: "Nacionalidad", noun: "habitantes" },
];

// The painter (figures.js / render/art/people.js) knows figure kinds, not these keys: each row and key maps to
// the figure row and kind that stands in for it.
const FIG = {
  age: { row: "age", under65: "midlife", elder: "elder" },
  education: { row: "education", other: "high_school", higher: "bachelors" },
  nationality: { row: "nativity", spanish: "born_in_state", foreign: "foreign_born" },
};
const figRow = (rid) => FIG[rid]?.row || rid;
const figKey = (rid, k) => FIG[rid]?.[k] || k;
const colorOf = (rid, k) => CATEGORY_COLOR[figRow(rid)]?.[figKey(rid, k)] || "#888";

// [singular verb phrase, plural verb phrase] per category, for "1 de cada 7 habitantes de X tiene …" / "3 de cada 10 … tienen …".
const PHRASE = {
  age: {
    under65: ["tiene menos de 65 años", "tienen menos de 65 años"],
    elder: ["tiene 65 años o más", "tienen 65 años o más"],
  },
  education: {
    other: ["no tiene estudios superiores", "no tienen estudios superiores"],
    higher: ["tiene estudios superiores", "tienen estudios superiores"],
  },
  nationality: {
    spanish: ["tiene nacionalidad española", "tienen nacionalidad española"],
    foreign: ["tiene nacionalidad extranjera", "tienen nacionalidad extranjera"],
  },
};

// Short legend labels (the file's labels are long).
const SHORT = {
  age: { under65: "Menos de 65", elder: "65 o más" },
  education: { other: "Sin superiores", higher: "Superiores" },
  nationality: { spanish: "Española", foreign: "Extranjera" },
};

/** Largest-remainder rounding of counts into n figures (the pipeline's method, for rows without figures). */
export function largestRemainder(counts, keys, n) {
  const tot = keys.reduce((a, k) => a + (counts[k] || 0), 0);
  if (!(tot > 0)) return null;
  const raw = keys.map((k) => ((counts[k] || 0) / tot) * n);
  const out = raw.map(Math.floor);
  const left = n - out.reduce((a, v) => a + v, 0);
  const order = raw.map((v, j) => [v - Math.floor(v), j]).sort((a, b) => b[0] - a[0] || a[1] - b[1]);
  for (let k = 0; k < left; k++) out[order[k][1]]++;
  return Object.fromEntries(keys.map((k, j) => [k, out[j]]));
}

/**
 * "1 de cada 7", "3 de cada 10", "menos de 1 de cada 1.000". `lead` is how a sentence starts, `plural` picks the
 * verb ("1 de cada 7 habitantes tiene", "3 de cada 10 habitantes tienen").
 */
export function oneIn(share) {
  if (share == null || !Number.isFinite(share)) return null;
  if (share <= 0) return { text: "ninguno", lead: "Ninguno de los", plural: false };
  if (share < 0.001) return { text: "menos de 1 de cada 1.000", lead: "Menos de 1 de cada 1.000", plural: false };
  if (share >= 0.3) {
    const k = Math.round(share * 10);
    return k >= 10
      ? { text: "casi todos", lead: "Casi todos los", plural: true }
      : { text: `${k} de cada 10`, lead: `${k} de cada 10`, plural: k !== 1 };
  }
  const t = `1 de cada ${int(Math.round(1 / share))}`;
  return { text: t, lead: t, plural: false };
}

function sentence(rowId, key, share, natShare, cityName, noun) {
  const a = oneIn(share);
  if (!a) return "";
  const ph = PHRASE[rowId]?.[key] || ["está en este grupo", "están en este grupo"];
  const es = oneIn(natShare);
  return `${a.lead} ${noun} de ${cityName} ${a.plural ? ph[1] : ph[0]}${es ? ` (España: ${es.text})` : ""}`;
}

function rowModel(rowDef, row, nat, groups, figuresN) {
  const keys = (groups[rowDef.id] || []).map((g) => g.key);
  const n = figuresN[rowDef.id] ?? 10;
  const figs = row.figures || largestRemainder(row.counts || {}, keys, n);
  return { keys, n, figs };
}

/** The Habitantes rows. data = citizens.json (or null / undefined while loading). */
export function citizensHtml(m, data) {
  const c = m.city;
  if (data === undefined) return `<p class="muted cv-note">Cargando la composición de los habitantes…</p>`;
  if (!data || !data.cities) return `<p class="muted cv-note">La composición de los habitantes no está disponible.</p>`;
  const row0 = data.cities[c.id];
  if (!row0) {
    return `<p class="muted cv-note">Sin dato: el INE no publica estas distribuciones para el área urbana de ${esc(c.name)}.</p>`;
  }
  const nat = data.national || {};
  const groups = data.groups || {};
  const bases = data.bases || {};
  const label = Object.fromEntries(Object.entries(groups).map(([r, gs]) => [r, Object.fromEntries(gs.map((g) => [g.key, g.label]))]));

  // Headline chips: mean age (a mean, not a median), higher education, foreign nationality.
  const med = row0.age?.mean, usMed = nat.age?.mean;
  const ba = row0.education?.shares?.higher, usBa = nat.education?.shares?.higher;
  const fb = row0.nationality?.shares?.foreign, usFb = nat.nationality?.shares?.foreign;
  const chip = (v, us, fmt, lbl, tip) => (v == null ? "" : `<div class="cv-cz-chip" title="${esc(tip)}"><b>${fmt(v)}</b><span>${esc(lbl)}</span>${us != null ? `<small>España ${fmt(us)}</small>` : ""}</div>`);
  const dec = (v) => v.toFixed(1).replace(".", ",");

  const rows = ROWS.map((rd) => {
    const row = row0[rd.id];
    const base = row?.base || bases[rd.id] || "";
    const head = `<div class="cv-cz-h"><b>${esc(rd.title)}</b><span>${esc(base)}</span></div>`;
    if (!row) {
      return `<div class="cv-cz-row missing" data-row="${rd.id}">${head}
        <p class="muted cv-note">Sin dato: el INE no publica esta distribución para ${esc(c.name)}.</p></div>`;
    }
    const { keys, n, figs } = rowModel(rd, row, nat[rd.id], groups, data.figures || {});
    if (!figs) return `<div class="cv-cz-row missing" data-row="${rd.id}">${head}<p class="muted cv-note">Sin dato para esta fila.</p></div>`;
    const per = row.total / n;
    const cells = [];
    for (const k of keys) {
      for (let j = 0; j < (figs[k] || 0); j++) {
        // One tab stop per category (its first figure), not one per figure.
        cells.push(`<span class="cv-fig" tabindex="${j ? -1 : 0}" role="img" data-k="${esc(k)}" aria-label="${esc(label[rd.id]?.[k] || k)}"></span>`);
      }
    }
    // Legend: every category, with its share and the national share. Categories that round to no figure are still
    // listed (greyed), so nothing silently disappears.
    const legend = keys.map((k) => {
      const sh = row.shares?.[k], us = nat[rd.id]?.shares?.[k];
      return `<span class="cv-cz-k${figs[k] ? "" : " zero"}" data-k="${esc(k)}" title="${esc(label[rd.id]?.[k] || k)}: ${sh != null ? pct(sh, 1) : "–"}${us != null ? ` (España ${pct(us, 1)})` : ""}${figs[k] ? "" : ". Se redondea a ninguna figura."}"><i style="background:${esc(colorOf(rd.id, k))}"></i>${esc(SHORT[rd.id]?.[k] || k)} <small>${sh != null ? pct(sh, 0) : "–"}</small></span>`;
    }).join("");
    // National comparison bar (shares), in the figures' order.
    const usBar = nat[rd.id]?.shares ? `<div class="cv-cz-us" title="Reparto en España, mismo orden"><span>España</span><div>${keys.map((k) => {
      const s = nat[rd.id].shares[k] || 0;
      return s > 0 ? `<i style="flex:${s};background:${esc(colorOf(rd.id, k))}" title="${esc(SHORT[rd.id]?.[k] || k)}: ${pct(s, 1)} en España"></i>` : "";
    }).join("")}</div></div>` : "";
    const cov = Array.isArray(row.coverage) && row.coverage[0] < row.coverage[1]
      ? ` · dato de ${int(row.coverage[0])} de ${int(row.coverage[1])} municipios` : "";
    const cap = `Cada figura ≈ ${compact(per)} ${rd.noun} · ${compact(row.total)} en total${cov}`;
    const extra = rd.id === "age" && med != null ? ` · edad media ${dec(med)} años${usMed != null ? ` (España ${dec(usMed)})` : ""}` : "";
    return `<div class="cv-cz-row" data-row="${rd.id}" style="--n:${n}">${head}
      <div class="cv-figs" role="group" aria-label="${esc(rd.title)}: ${keys.filter((k) => figs[k]).map((k) => `${figs[k]} de ${n} ${SHORT[rd.id]?.[k] || k}`).join(", ")}">${cells.join("")}</div>
      ${usBar}
      <div class="cv-cz-out" aria-live="polite" data-default="${esc(cap + extra)}">${esc(cap + extra)}</div>
      <div class="cv-cz-legend">${legend}</div>
    </div>`;
  }).join("");

  const unreliable = row0.reliable === false
    ? `<p class="cv-warn">Área urbana pequeña: estas cifras son orientativas.</p>` : "";
  return `
    <div class="cv-cz-top">
      ${chip(med, usMed, dec, "edad media (años)", "Edad media de los habitantes (media, no mediana)")}
      ${chip(ba, usBa, (v) => pct(v, 0), "con estudios superiores", "Habitantes de 15 años o más con estudios superiores")}
      ${chip(fb, usFb, (v) => pct(v, 0), "nacionalidad extranjera", "Habitantes con nacionalidad extranjera (no es lo mismo que haber nacido en el extranjero)")}
    </div>
    ${unreliable}
    <div class="cv-cz${row0.reliable === false ? " unreliable" : ""}">${rows}</div>
    <p class="cv-note">${esc(data.vintage || "INE")}. Cada fila usa su propia base: edad y nacionalidad sobre todos los habitantes, estudios sobre los de 15 años o más. Las figuras se redondean para que cada fila sume 10; pasa el ratón o toca una figura para ver su porcentaje. Nacionalidad extranjera no es lo mismo que nacido en el extranjero.</p>`;
}

/** Paint the figure canvases and wire the read-outs. */
export function mountCitizens(host, m, data) {
  if (!host || !data?.cities?.[m.city.id]) return;
  const row0 = data.cities[m.city.id];
  const nat = data.national || {};
  const dpr = Math.min(3, Math.max(1, Math.round((devicePixelRatio || 1) * 2) / 2));
  const paintAll = () => {
    host.querySelectorAll(".cv-cz-row[data-row]").forEach((rowEl) => {
      const rid = rowEl.dataset.row;
      rowEl.querySelectorAll(".cv-fig").forEach((el) => {
        const src = figureCanvas(figRow(rid), figKey(rid, el.dataset.k), 36, dpr);
        const cv = document.createElement("canvas");
        cv.width = src.width;
        cv.height = src.height;
        cv.getContext("2d").drawImage(src, 0, 0);
        el.replaceChildren(cv);
      });
    });
  };
  paintAll();
  // Once the citizen painter (render/art/people.js) loads, repaint the figures.
  loadPainter().then(() => { if (host.isConnected) paintAll(); });

  host.querySelectorAll(".cv-cz-row[data-row]").forEach((rowEl) => {
    const rid = rowEl.dataset.row;
    const rd = ROWS.find((r) => r.id === rid);
    const row = row0[rid];
    const out = rowEl.querySelector(".cv-cz-out");
    if (!row || !out || !rd) return;
    const show = (k) => {
      rowEl.querySelectorAll("[data-k]").forEach((el) => el.classList.toggle("lit", el.dataset.k === k));
      rowEl.classList.toggle("focus", !!k);
      if (!k) {
        out.textContent = out.dataset.default;
        out.classList.remove("on");
        return;
      }
      const sh = row.shares?.[k], us = nat[rid]?.shares?.[k];
      out.innerHTML = `${esc(sentence(rid, k, sh, us, m.city.name, rd.noun))}<small>${sh != null ? pct(sh, 1) : "–"} aquí${us != null ? ` · ${pct(us, 1)} en España` : ""}${row.counts?.[k] != null ? ` · ≈${compact(row.counts[k])} personas` : ""}</small>`;
      out.classList.add("on");
    };
    let pinned = null;
    rowEl.addEventListener("pointerover", (e) => {
      const el = e.target.closest("[data-k]");
      if (el && rowEl.contains(el)) show(el.dataset.k);
    });
    rowEl.addEventListener("pointerleave", () => show(pinned));
    rowEl.addEventListener("focusin", (e) => {
      const el = e.target.closest("[data-k]");
      if (el) show(el.dataset.k);
    });
    rowEl.addEventListener("focusout", () => show(pinned));
    // A tap pins the category (phones have no hover); another tap on it lets go.
    rowEl.addEventListener("click", (e) => {
      const el = e.target.closest("[data-k]");
      if (!el) return;
      pinned = pinned === el.dataset.k ? null : el.dataset.k;
      show(pinned);
    });
  });
}
