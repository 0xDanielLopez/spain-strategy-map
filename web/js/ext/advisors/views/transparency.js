// Lo público: delitos conocidos, boletín oficial (BOJA) y contratos menores de la Junta, siempre agregados.
// Lee tres ficheros perezosos (safety.json, boja.json, contracts_junta.json); cada sección tolera que falten
// o que les falten campos. Nunca se muestra un dato ausente como 0, ni títulos de disposiciones, ni personas.
import { esc, fin, el as mk } from "../core/util.js";
import { int, pct } from "../core/fmt.js";
import { section, tiles, segmented, selectBox } from "../core/view.js";
import { createTable } from "../core/table.js";
import { barList } from "../core/charts.js";
import { rowsHighlight, attributionHtml } from "../core/data.js";

const NA = "Sin dato";
const dec = (v, d = 1) => (fin(v) ? v.toLocaleString("es-ES", { minimumFractionDigits: d, maximumFractionDigits: d }) : NA);
const eur = (v) => (fin(v) ? `${Math.round(v).toLocaleString("es-ES")} €` : NA);
const share = (a, b) => (fin(a) && fin(b) && b > 0 ? a / b : null);
const signed = (v, d = 1) => (fin(v) ? `${v >= 0 ? "+" : "−"}${dec(Math.abs(v) * 100, d)} %` : NA);
const num = (v) => (fin(v) ? v : null);
const MIN_POP = [{ value: 1000, label: "1.000" }, { value: 5000, label: "5.000" }, { value: 20000, label: "20.000" }];

const PROVINCES = {
  "01": "Álava", "02": "Albacete", "03": "Alicante", "04": "Almería", "05": "Ávila", "06": "Badajoz", "07": "Illes Balears",
  "08": "Barcelona", "09": "Burgos", "10": "Cáceres", "11": "Cádiz", "12": "Castellón", "13": "Ciudad Real", "14": "Córdoba",
  "15": "A Coruña", "16": "Cuenca", "17": "Girona", "18": "Granada", "19": "Guadalajara", "20": "Gipuzkoa", "21": "Huelva",
  "22": "Huesca", "23": "Jaén", "24": "León", "25": "Lleida", "26": "La Rioja", "27": "Lugo", "28": "Madrid", "29": "Málaga",
  "30": "Murcia", "31": "Navarra", "32": "Ourense", "33": "Asturias", "34": "Palencia", "35": "Las Palmas", "36": "Pontevedra",
  "37": "Salamanca", "38": "Santa Cruz de Tenerife", "39": "Cantabria", "40": "Segovia", "41": "Sevilla", "42": "Soria",
  "43": "Tarragona", "44": "Teruel", "45": "Toledo", "46": "Valencia", "47": "Valladolid", "48": "Bizkaia", "49": "Zamora",
  "50": "Zaragoza", "51": "Ceuta", "52": "Melilla",
};

const empty = (host, what) => host.insertAdjacentHTML("beforeend", `<p class="adv-empty pad">Todavía no hay ${what}, así que no hay nada que mostrar aquí.</p>`);
const stamp = (f) => (f?.updated || f?.vintage ? `<p class="adv-note">Datos a fecha de ${esc(f.updated || f.vintage)}.</p>` : "");

export async function mount(ctx) {
  const { app, el, link, data } = ctx;
  const [safety, boja, junta] = await Promise.all(["safety", "boja", "contracts_junta"].map((n) => app.loadData(n).catch(() => null)));
  const counties = data?.levels?.counties || null;
  const states = data?.levels?.states || null;
  const rowByCode = new Map((counties?.rows || []).map((r) => [r.key, r]));
  const stateName = new Map((app.data.states || []).map((s) => [s.abbr, s.name]));
  const provName = (code, o) => o?.name || PROVINCES[code] || `Provincia ${code}`;
  const provRows = (code) => (counties?.rows || []).filter((r) => String(r.v.province) === String(code));
  const tables = [];

  // =============================================================================================================
  // 1) Seguridad
  // =============================================================================================================
  const sBody = section(el, {
    kicker: "Delitos conocidos", title: "Seguridad",
    note: "Hechos conocidos por las fuerzas de seguridad, por tipo de delito. Son hechos registrados, no condenas ni personas, y no miden toda la delincuencia real.",
  });
  const typ = safety?.typologies || [];
  const years = (safety?.years || []).map(String).sort();
  const yNow = years[years.length - 1], yPrev = years.length > 1 ? years[years.length - 2] : null;
  if (!safety || !typ.length || !yNow) {
    empty(sBody, "datos de seguridad");
  } else {
    const total = (o, y) => {
      const b = o?.[y];
      if (!b) return null;
      // "total" ya incluye todos los tipos (las demás filas son partes de él): nunca se suman entre sí
      return fin(b.total) ? b.total : null;
    };
    const rate = (o, y) => share(total(o, y), o?.population) * 1000;
    const popOf = (o) => num(o?.population);
    // selector de territorio: España, comunidades y provincias
    const opts = [{ value: "ES", label: "España", group: "" }];
    for (const k of Object.keys(safety.ccaa || {})) opts.push({ value: `c:${k}`, label: stateName.get(k) || k, group: "Comunidades" });
    for (const k of Object.keys(safety.provinces || {}).sort()) opts.push({ value: `p:${k}`, label: provName(k, safety.provinces[k]), group: "Provincias" });
    const objOf = (v) => (v === "ES" ? safety.national : v.startsWith("c:") ? safety.ccaa?.[v.slice(2)] : safety.provinces?.[v.slice(2)]);
    const nameOf = (v) => opts.find((o) => o.value === v)?.label || "España";
    let terr = "ES";
    const tHead = mk("div", "adv-row");
    sBody.appendChild(tHead);
    selectBox(tHead, { label: "Territorio", options: opts, value: terr, onChange: (v) => { terr = v; drawTerr(); } });
    const tHost = mk("div");
    sBody.appendChild(tHost);
    function drawTerr() {
      const o = objOf(terr);
      const tNow = total(o, yNow), tPrev = yPrev ? total(o, yPrev) : null;
      const rNow = rate(o, yNow);
      tHost.innerHTML = tiles([
        { label: `Hechos conocidos, ${yNow}`, value: fin(tNow) ? int(tNow) : NA, sub: nameOf(terr) },
        { label: "Por 1.000 habitantes", value: fin(rNow) ? dec(rNow) : NA, sub: popOf(o) ? `población ${safety.national?.population_year || ""}`.trim() : "sin población" },
        { label: `Cambio ${yPrev || ""}${yPrev ? "-" : ""}${yNow}`, value: fin(tNow) && fin(tPrev) && tPrev > 0 ? signed(tNow / tPrev - 1) : NA, sub: "variación del total de hechos" },
      ]);
      if (!o || !fin(tNow)) tHost.insertAdjacentHTML("beforeend", `<p class="adv-empty">No hay cifras de ${esc(nameOf(terr))}.</p>`);
      if (terr.startsWith("p:") && counties) link.base(rowsHighlight(counties, provRows(terr.slice(2)), { dim: true }), { frame: true });
      else if (terr.startsWith("c:") && states) { const r = states.rows.find((x) => x.key === terr.slice(2)); link.base(r ? rowsHighlight(states, [r], { dim: true }) : null, { frame: !!r }); }
      else link.base(null);
    }
    drawTerr();

    // ranking de municipios por tasa
    const munis = Object.entries(safety.municipalities || {}).map(([code, m]) => ({
      key: code, name: m.name || rowByCode.get(code)?.name || code, pop: popOf(m), n: total(m, yNow), nPrev: yPrev ? total(m, yPrev) : null,
      rate: rate(m, yNow), m, row: rowByCode.get(code) || null,
    }));
    const rBody = section(el, {
      title: "Hechos conocidos por 1.000 habitantes",
      note: `Municipios por la tasa de ${yNow}. Es una tasa sobre los residentes: no descuenta a quien visita, trabaja o está de paso, así que los destinos turísticos y las ciudades que reciben mucha gente salen con tasas más altas que su vecindario real. Un municipio pequeño salta mucho con pocos hechos. Esto no es un ranking de seguridad ni de peligrosidad.`,
    });
    let minPop = 5000, selected = null;
    const rHead = mk("div", "adv-row");
    rBody.appendChild(rHead);
    rHead.insertAdjacentHTML("beforeend", `<span class="adv-note">Población mínima</span>`);
    const tHostR = mk("div");
    const rows = () => munis.filter((x) => fin(x.rate) && (x.pop ?? 0) >= minPop);
    const rTable = createTable(tHostR, {
      caption: "Municipios por hechos conocidos por 1.000 habitantes", rank: true, maxHeight: 320, search: "Buscar municipio",
      rows: rows(), sort: { key: "rate", dir: "desc" },
      columns: [
        { key: "name", label: "Municipio", align: "l", width: "minmax(0,1.6fr)", value: (r) => r.name, text: (r) => r.name },
        { key: "pop", label: "Habitantes", value: (r) => r.pop, text: (r) => int(r.pop), hideBelow: 380 },
        { key: "n", label: `Hechos ${yNow}`, short: "Hechos", value: (r) => r.n, text: (r) => (fin(r.n) ? int(r.n) : NA) },
        { key: "rate", label: "Por 1.000", value: (r) => r.rate, text: (r) => dec(r.rate), bar: { max: Math.max(1, ...rows().map((r) => r.rate).sort((a, b) => b - a).slice(0, 20)), color: "rgba(196,106,79,.3)" } },
      ],
      onHover: (r) => link.hover(r?.row ? rowsHighlight(counties, [r.row]) : null),
      onClick: (r) => pickMuni(r.key, true),
    });
    tables.push(rTable);
    segmented(rHead, { label: "Población mínima", value: minPop, options: MIN_POP, onChange: (v) => { minPop = Number(v); rTable.setRows(rows()); } });
    rBody.appendChild(tHostR);
    if (!munis.length) empty(rBody, "cifras por municipio");

    // detalle de un municipio: las 19 tipologías y su cambio interanual
    const dBody = section(el, {
      title: "Qué tipos de hecho",
      note: `Elige un municipio en la tabla o en el mapa para ver cada tipología en ${yNow}${yPrev ? ` y su cambio respecto a ${yPrev}` : ""}.`,
    });
    const dHost = mk("div");
    dBody.appendChild(dHost);
    function pickMuni(code, fly) {
      selected = code;
      const mu = safety.municipalities?.[code];
      const row = rowByCode.get(code);
      rTable.setHot(code, true);
      if (!mu) { dHost.innerHTML = `<p class="adv-empty">No hay cifras de este municipio.</p>`; return; }
      dHost.innerHTML = "";
      dHost.insertAdjacentHTML("beforeend", `<h4 class="adv-h4">${esc(mu.name || row?.name || code)}${fin(mu.population) ? ` <span class="sub">${int(mu.population)} habitantes</span>` : ""}</h4>`);
      const list = typ.map((t) => {
        const a = num(mu[yNow]?.[t.key]), b = yPrev ? num(mu[yPrev]?.[t.key]) : null;
        const ch = fin(a) && fin(b) && b > 0 ? a / b - 1 : null;
        return { key: t.key, label: t.label, value: a, text: fin(a) ? `${int(a)}${fin(b) ? ` (${fin(ch) ? signed(ch, 0) : `antes ${int(b)}`})` : ""}` : NA, tone: fin(ch) ? (ch > 0.1 ? "bad" : ch < -0.1 ? "good" : undefined) : undefined };
      }).sort((x, y) => (y.value ?? -1) - (x.value ?? -1));
      barList(dHost, { rows: list.map((r) => ({ ...r, value: r.value ?? 0 })), ariaLabel: "Hechos por tipología" });
      dHost.insertAdjacentHTML("beforeend", `<p class="adv-note">Entre paréntesis, el cambio frente a ${esc(yPrev || "el año anterior")}. Un tipo sin cifra aparece como "${NA}", no como cero. Cifras pequeñas cambian mucho en porcentaje.</p>`);
      if (row) { link.base(rowsHighlight(counties, [row]), { frame: false }); if (fly) counties.focus(row); }
    }
    el.addEventListener("click", (e) => { if (e.target.closest("[data-clear-muni]")) { selected = null; link.base(null); dHost.innerHTML = ""; } });
    dHost.innerHTML = `<p class="adv-empty">Ningún municipio elegido.</p>`;
    var pickFromMap = (cell) => {
      const r = counties?.rowAtCell?.(cell);
      if (r && safety.municipalities?.[r.key]) { pickMuni(r.key, false); return true; }
      return false;
    };
    el.insertAdjacentHTML("beforeend", attributionHtml([safety], [
      "Los hechos son los conocidos y registrados por las fuerzas de seguridad en cada municipio; no hay personas, denuncias concretas ni sentencias.",
      "La tasa usa los residentes. No cuenta a la población flotante (turistas, trabajadores o estudiantes de paso), y por eso no sirve para decir qué lugar es más o menos seguro.",
      ...(safety.note ? [esc(safety.note)] : []),
    ]) + stamp(safety));
  }

  // =============================================================================================================
  // 2) Boletín oficial (BOJA)
  // =============================================================================================================
  const bBody = section(el, {
    kicker: "Junta de Andalucía", title: "Boletín oficial (BOJA)",
    note: "Cuántas disposiciones publica el Boletín Oficial de la Junta de Andalucía, por año y sección, y qué consejerías publican más. Solo recuentos: no se muestran títulos ni textos.",
  });
  const bYears = (boja?.years || Object.keys(boja?.by_year_section || {})).map(String).sort();
  if (!boja || !bYears.length) {
    empty(bBody, "datos del BOJA");
  } else {
    const secs = boja.sections || [];
    let by = bYears[bYears.length - 1];
    const yearTotal = (y) => {
      const o = boja.by_year_section?.[y];
      if (!o) return null;
      const v = Object.values(o).filter(fin);
      return v.length ? v.reduce((a, b) => a + b, 0) : null;
    };
    const bHost = mk("div");
    segmented(bBody, { label: "Año", value: by, options: bYears.map((y) => ({ value: y, label: y })), onChange: (v) => { by = String(v); drawBoja(); } });
    bBody.appendChild(bHost);
    function drawBoja() {
      bHost.innerHTML = "";
      const t = yearTotal(by);
      bHost.insertAdjacentHTML("beforeend", tiles([
        { label: `Disposiciones ${by}`, value: fin(t) ? int(t) : NA, sub: by === bYears[bYears.length - 1] ? "el último año puede estar incompleto" : "todas las secciones" },
        { label: "Secciones", value: int(secs.length), sub: "del boletín" },
      ]));
      const o = boja.by_year_section?.[by] || {};
      const sRows = secs.map((s) => ({ key: s.id, label: s.name, value: num(o[s.id]) ?? 0, text: fin(o[s.id]) ? int(o[s.id]) : NA })).sort((a, b) => b.value - a.value);
      bHost.insertAdjacentHTML("beforeend", `<h4 class="adv-h4">Por sección, ${esc(by)}</h4>`);
      if (sRows.length) barList(bHost, { rows: sRows, ariaLabel: "Disposiciones por sección" }); else bHost.insertAdjacentHTML("beforeend", `<p class="adv-empty">Sin secciones.</p>`);
      const orgs = (boja.by_organisation || []).map((g) => ({ key: g.name, label: g.name, v: num(g.counts?.[by]) })).filter((g) => fin(g.v)).sort((a, b) => b.v - a.v).slice(0, 10);
      bHost.insertAdjacentHTML("beforeend", `<h4 class="adv-h4">Quién más publica, ${esc(by)}</h4>`);
      if (orgs.length) barList(bHost, { rows: orgs.map((g) => ({ key: g.key, label: g.label, value: g.v, text: int(g.v) })), ariaLabel: "Organismos con más disposiciones", rank: true });
      else bHost.insertAdjacentHTML("beforeend", `<p class="adv-empty">No hay recuento por organismo de ${esc(by)}.</p>`);
      bHost.insertAdjacentHTML("beforeend", `<h4 class="adv-h4">Total por año</h4>`);
      barList(bHost, { rows: bYears.map((y) => ({ key: y, label: y, value: yearTotal(y) ?? 0, text: fin(yearTotal(y)) ? int(yearTotal(y)) : NA })), compact: true, ariaLabel: "Disposiciones por año" });
    }
    drawBoja();
    el.insertAdjacentHTML("beforeend", attributionHtml([boja], [
      "Cada disposición cuenta una vez, en la sección y el organismo con que se publicó. Las cifras no dicen si una norma importa más que otra.",
      ...(boja.note ? [esc(boja.note)] : []),
    ]) + stamp(boja));
  }

  // =============================================================================================================
  // 3) Contratos menores de la Junta
  // =============================================================================================================
  const cBody = section(el, {
    kicker: "Junta de Andalucía", title: "Contratos menores de la Junta",
    note: "Contratos menores adjudicados por la Junta de Andalucía, por provincia y año. Son agregados por provincia y órgano: no se muestran adjudicatarios, ni autónomos, ni personas.",
  });
  const cYears = (junta?.years || []).map(String).sort();
  if (!junta || !cYears.length || !junta.provinces) {
    empty(cBody, "datos de contratos de la Junta");
  } else {
    let cy = cYears[cYears.length - 1];
    const basis = junta.amount_basis ? `importes ${junta.amount_basis}` : "importes";
    const cHost = mk("div");
    segmented(cBody, { label: "Año", value: cy, options: cYears.map((y) => ({ value: y, label: y })), onChange: (v) => { cy = String(v); drawJunta(); } });
    cBody.appendChild(cHost);
    let cTable = null;
    function drawJunta() {
      cHost.innerHTML = "";
      const prows = Object.entries(junta.provinces).map(([code, p]) => {
        const d = p?.[cy] || {};
        return { key: code, name: provName(code, p), n: num(d.n), amount: num(d.amount), single: num(d.single_bidder), s15: num(d.under_15k), s40: num(d.under_40k) };
      }).filter((r) => fin(r.n));
      const tn = prows.reduce((a, r) => a + r.n, 0), ta = prows.reduce((a, r) => a + (r.amount ?? 0), 0);
      const hasAmt = prows.some((r) => fin(r.amount));
      cHost.insertAdjacentHTML("beforeend", tiles([
        { label: `Contratos ${cy}`, value: prows.length ? int(tn) : NA, sub: "con provincia conocida" },
        { label: "Importe", value: hasAmt ? eur(ta) : NA, sub: basis },
      ]));
      const hosts = mk("div");
      cHost.appendChild(hosts);
      cTable = createTable(hosts, {
        caption: `Contratos menores por provincia, ${cy}`, rank: true, maxHeight: 320, rows: prows, sort: { key: "amount", dir: "desc" },
        columns: [
          { key: "name", label: "Provincia", align: "l", width: "minmax(0,1.3fr)", value: (r) => r.name, text: (r) => r.name },
          { key: "n", label: "Contratos", value: (r) => r.n, text: (r) => int(r.n) },
          { key: "amount", label: "Importe", value: (r) => r.amount, text: (r) => eur(r.amount), bar: { max: Math.max(1, ...prows.map((r) => r.amount ?? 0)), color: "rgba(201,164,58,.3)" } },
          { key: "single", label: "Un solo licitador", short: "Un solo&shy;licitador", value: (r) => share(r.single, r.n), text: (r) => (fin(r.single) ? pct(share(r.single, r.n)) : NA), hideBelow: 400 },
          { key: "s15", label: "Menos de 15.000 €", short: "Menos de 15 mil €", value: (r) => share(r.s15, r.n), text: (r) => (fin(r.s15) ? pct(share(r.s15, r.n)) : NA), hideBelow: 460 },
          { key: "s40", label: "Menos de 40.000 €", short: "Menos de 40 mil €", value: (r) => share(r.s40, r.n), text: (r) => (fin(r.s40) ? pct(share(r.s40, r.n)) : NA), hideBelow: 520 },
        ],
        onHover: (r) => link.hover(r && counties ? rowsHighlight(counties, provRows(r.key), { dim: true, label: r.name }) : null),
        onClick: (r) => { if (counties) link.base(rowsHighlight(counties, provRows(r.key), { dim: true, label: r.name }), { frame: true }); },
      });
      tables.length = 0;
      const organs = (junta.organs || []).map((o) => ({ name: o.name, n: num(o.by_year?.[cy]?.n), amount: num(o.by_year?.[cy]?.amount) })).filter((o) => fin(o.n))
        .sort((a, b) => (b.amount ?? -1) - (a.amount ?? -1)).slice(0, 10);
      cHost.insertAdjacentHTML("beforeend", `<h4 class="adv-h4">Órganos con más importe, ${esc(cy)}</h4>`);
      if (organs.length) barList(cHost, { rank: true, ariaLabel: "Órganos de contratación", rows: organs.map((o) => ({ key: o.name, label: o.name, value: o.amount ?? 0, text: fin(o.amount) ? `${eur(o.amount)} (${int(o.n)})` : `${NA} (${int(o.n)})` })) });
      else cHost.insertAdjacentHTML("beforeend", `<p class="adv-empty">No hay desglose por órgano de ${esc(cy)}.</p>`);
      cHost.insertAdjacentHTML("beforeend", `<p class="adv-note">Un solo licitador y los tramos por debajo de 15.000 y 40.000 € se calculan sobre el número de contratos de cada provincia; donde falta el dato se lee "${NA}", no 0 %. Un porcentaje alto no prueba ninguna irregularidad.</p>`);
    }
    drawJunta();
    el.insertAdjacentHTML("beforeend", attributionHtml([junta], [
      `Los ${basis} y los contratos menores son solo una parte de la contratación pública; los contratos grandes se tramitan por otros procedimientos.`,
      ...(junta.note ? [esc(junta.note)] : []),
    ]) + stamp(junta));
  }

  return {
    onMapClick(ev) {
      return typeof pickFromMap === "function" && ev?.cell >= 0 ? pickFromMap(ev.cell) : false;
    },
    destroy() { for (const t of tables) t.destroy?.(); },
  };
}
