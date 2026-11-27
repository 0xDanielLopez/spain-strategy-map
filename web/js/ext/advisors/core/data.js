// The advisors' data model: three "levels" (states = comunidades autónomas, metros = áreas urbanas funcionales,
// counties = municipios) of rows with typed fields, plus the links between rows and the hex map (row → highlight,
// cell → row). Built once from app.data (counties.json optional).
//
//   level = {id, label, noun, rows: [row], fields: [field], field(key), value(row, key),
//            highlight(rows, opts) → app.state.highlight, rowAtCell(cell) → row | null, focus(row), byKey: Map}
//   row   = {key, name, sub, level, ref, v: {fieldKey: value}}
//   field = {key, label, format, unit, higher_is, source, description, lens?, group, derived?}
//
// Field keys per level (null = no data; never 0):
//   states : name, abbr, population, growth, gdp, gdp_pc, income_per_person, employed, y_<yield>, land_<cover>,
//            and (with counties.json) density, poverty, age_mean, elderly, foreign, household, higher_education, land_km2
//   metros : name, states, population, growth, gdp (imputed; NO gdp_pc), income_per_person, employed, y_<yield>,
//            land_<cover> (when cities have land), plus the same county roll-ups
//   counties: geoid-keyed; name, state, metro, province, population, land_km2, density, growth, age_mean, elderly,
//            foreign, household, income, poverty, higher_education (and `auf`, `cell` kept in row.v)
import { fin, ratio } from "./util.js";
import { frameBox } from "./frame.js";

// counties.json column → lens id in lenses.json
const COUNTY_LENS = {
  density: "density", growth: "growth", age_mean: "age", elderly: "elderly", foreign: "foreign", household: "household",
  income: "income", poverty: "poverty", higher_education: "higher_education", forest: "forest", farmland: "farmland", developed: "developed",
};
// County measures we can roll up to states and metros as population-weighted means.
const ROLLUP = ["density", "poverty", "age_mean", "elderly", "foreign", "household", "higher_education"];
// Rolled-up means that only approximate the area's true value (a mean of rates or of sizes).
const APPROX = new Set(["poverty", "household"]);
const LAND_KEYS = ["forest", "crop", "grass", "shrub", "wetland", "developed"];
export const LAND_LABEL = {
  forest: "Bosque", crop: "Cultivos", pasture: "Pastos", grass: "Pastizal", shrub: "Matorral", wetland: "Humedales", developed: "Superficie construida",
};
export const LAND_COLOR = {
  forest: "#3f7a3a", crop: "#d2c457", pasture: "#93b852", grass: "#b9b06a", shrub: "#c9a874", wetland: "#4f9a86", developed: "#9a8f9e",
};
export { LAND_KEYS };

export function buildData(app) {
  const { cities = [], states = [], nation = {}, counties, resources, sources = [] } = app.data;
  const w = app.w;
  const grid = w.grid;
  const owner = w.raw.owner;
  const countyOf = w.raw.county || [];
  const P = w.raw.pct || null; // per-cell land cover, 0..100
  const n = grid.size;

  // --- cell indexes ---------------------------------------------------------------------------------------------
  const stateCells = new Map();
  const countyCells = new Map();
  for (let i = 0; i < n; i++) {
    const o = owner[i];
    if (!(o >= 0)) continue;
    if (!stateCells.has(o)) stateCells.set(o, []);
    stateCells.get(o).push(i);
    const c = countyOf[i];
    if (c >= 0) {
      if (!countyCells.has(c)) countyCells.set(c, []);
      countyCells.get(c).push(i);
    }
  }
  // cell → metro: footprints, smaller metros first so a bigger metro's majority wins; then every city's own cell.
  const cellMetro = new Map();
  for (let k = cities.length - 1; k >= 0; k--) for (const cell of cities[k].footprint || []) cellMetro.set(cell, cities[k]);
  for (const c of cities) if (c.cell != null) cellMetro.set(c.cell, c);

  const srcTitle = new Map(sources.map((s) => [s.id, s]));
  const nat = nation.nation || {};
  const vintage = nation.vintage || "INE";
  const countyVintage = counties?.vintage || "INE";
  const years = (nat.growth_years || []).join("–");

  // Land-cover shares (0..1) of a set of cells, from the world's per-cell cover; null where no cell has samples.
  const landFromCells = (cells) => {
    if (!P || !cells || !cells.length) return null;
    const sums = Object.fromEntries(LAND_KEYS.map((k) => [k, 0]));
    let m = 0;
    for (const i of cells) {
      let tot = 0;
      for (const k of LAND_KEYS) tot += P[k]?.[i] || 0;
      if (tot <= 0) continue;
      m++;
      for (const k of LAND_KEYS) sums[k] += P[k]?.[i] || 0;
    }
    return m ? Object.fromEntries(LAND_KEYS.map((k) => [k, sums[k] / (m * 100)])) : null;
  };
  const landOf = (o, cells) => o.land || landFromCells(cells);

  // --- fields ---------------------------------------------------------------------------------------------------
  const F = (key, label, format, o = {}) => ({ key, label, format, unit: o.unit || null, higher_is: o.higher_is || "neutral", source: o.source || "", description: o.description || "", lens: o.lens || null, group: o.group || "Economía", derived: !!o.derived });
  const econFields = (level) => [
    F("population", "Residentes", "int", { unit: "personas", source: "ine", group: "Personas", description: `Residentes empadronados (${vintage}).`, lens: "density" }),
    F("growth", "Crecimiento", "signed", { unit: "variación de la población", source: "ine", group: "Personas", description: `Variación de la población ${years} (INE).`, lens: "growth" }),
    level === "states"
      ? F("gdp", "PIB", "money", { unit: "€ al año", source: "ine_gdp", description: `PIB a precios corrientes, donde se produce (INE, Contabilidad Regional, ${nat.gdp_year || nation.gdp_vintage || ""}).` })
      : F("gdp", "PIB imputado", "money", { unit: "€ al año", source: "ine_gdp", description: "PIB imputado: el PIB de la provincia de cada municipio, repartido por ocupados residentes. No es un PIB medido en el área urbana." }),
    ...(level === "states" ? [F("gdp_pc", "PIB por habitante", "eur", { unit: "€ por residente", higher_is: "good", source: "ine_gdp", description: "PIB de la comunidad ÷ residentes." })] : []),
    F("income_per_person", "Renta por persona", "eur", { unit: "€ al año, media", higher_is: "good", source: "ine", group: "Prosperidad", description: "Renta media por persona (una media, no una mediana), INE, Atlas de distribución de renta de los hogares.", lens: "income" }),
    F("employed", "Ocupados", "int", { unit: "ocupados residentes", source: "ine_jobs", description: "Ocupados según su lugar de residencia, no según dónde trabajan (INE, Censo 2024)." }),
    ...(nation.yields || []).filter((y) => y.unit !== "usd").map((y) => F(`y_${y.key}`, `${y.label} (ocupados)`, "int", { unit: "ocupados residentes", source: "ine_jobs", group: "Ocupados por sector", description: y.description })),
  ];
  const rollupFields = () => counties ? ROLLUP.map((k) => {
    const f = counties.fields.find((x) => x.key === k);
    if (!f) return null;
    const approx = APPROX.has(k);
    return F(k, f.label + (approx ? " ≈" : ""), f.format, {
      unit: f.unit, higher_is: f.higher_is, source: f.source || "ine", group: groupOf(k), lens: COUNTY_LENS[k],
      description: k === "density" ? `Residentes ÷ superficie, sumados sobre los municipios del área (${countyVintage}).`
        : `${f.description || ""} Media ponderada por población de los municipios${approx ? " (aproximación, no el dato propio del área)" : ""} (${countyVintage}).`.trim(),
      derived: true,
    });
  }).filter(Boolean) : [];

  // --- roll-ups from counties -------------------------------------------------------------------------------------
  const roll = { states: new Map(), metros: new Map() };
  const cRows = [];
  if (counties) {
    const col = Object.fromEntries(counties.columns.map((k, j) => [k, j]));
    counties.rows.forEach((r, i) => cRows.push({ r, i }));
    const add = (map, key, r) => {
      if (key == null) return;
      let a = map.get(key);
      if (!a) map.set(key, (a = { pop: 0, land: 0, s: {}, wt: {} }));
      const pop = r[col.population];
      if (fin(pop)) a.pop += pop;
      if (fin(r[col.land_km2])) a.land += r[col.land_km2];
      for (const k of ROLLUP) {
        if (k === "density") continue;
        const v = r[col[k]];
        if (fin(v) && fin(pop) && pop > 0) {
          a.s[k] = (a.s[k] || 0) + v * pop;
          a.wt[k] = (a.wt[k] || 0) + pop;
        }
      }
    };
    for (const { r } of cRows) {
      add(roll.states, r[col.state], r);
      add(roll.metros, r[col.auf], r);
    }
  }
  const rolled = (map, key) => {
    const a = map.get(key);
    const out = {};
    if (!a) return out;
    out.density = a.land > 0 ? a.pop / a.land : null;
    out.land_km2 = a.land || null;
    for (const k of ROLLUP) if (k !== "density") out[k] = a.wt[k] ? a.s[k] / a.wt[k] : null;
    return out;
  };

  // gdp_pc only where GDP is a measured figure (states); an imputed city GDP is a provincial constant by construction.
  const econValues = (o, level) => ({
    population: o.population ?? null,
    growth: o.growth ?? null,
    gdp: o.gdp ?? o.yields?.gold ?? null,
    ...(level === "states" ? { gdp_pc: ratio(o.gdp ?? o.yields?.gold, o.population) } : {}),
    income_per_person: o.income_per_person ?? null,
    employed: o.employed ?? null,
    ...Object.fromEntries((nation.yields || []).filter((y) => y.unit !== "usd").map((y) => [`y_${y.key}`, o.yields?.[y.key] ?? null])),
  });
  const landValues = (land) => Object.fromEntries(LAND_KEYS.map((k) => [`land_${k}`, land?.[k] ?? null]));

  // --- resources by place (none for Spain yet; kept so the map link layer keeps working) --------------------------
  const items = resources?.items || [];
  const typeById = new Map((resources?.types || []).map((t) => [t.id, t]));

  // --- states ---------------------------------------------------------------------------------------------------
  const stateList = Array.isArray(states) ? states : [];
  const stateRows = stateList.map((s, idx) => ({
    key: s.abbr, name: s.name, sub: s.abbr, level: "states", ref: idx,
    v: {
      name: s.name, abbr: s.abbr, ...econValues(s, "states"), ...rolled(roll.states, s.abbr),
      ...landValues(landOf(s, stateCells.get(idx))),
    },
  }));
  const landFields = LAND_KEYS.map((k) => F(`land_${k}`, LAND_LABEL[k], "pct", { unit: "cuota de la superficie", source: "worldcover", group: "Territorio", description: `Cuota de la superficie con cobertura de ${LAND_LABEL[k].toLowerCase()} (ESA WorldCover, media sobre los hexágonos del área).`, lens: k === "forest" ? "forest" : k === "developed" ? "developed" : k === "crop" ? "farmland" : null }));
  const landKm2 = () => (counties ? [F("land_km2", "Superficie", "km2", { unit: "km²", source: "ine", group: "Territorio", derived: true, description: "Superficie sumada de los municipios del área." })] : []);
  const states_ = makeLevel({
    id: "states", label: "Comunidades", noun: "comunidad",
    rows: stateRows,
    fields: [F("name", "Comunidad", "text", { group: "Nombre" }), ...econFields("states"), ...rollupFields(), ...landKm2(), ...landFields],
    highlight: (rows) => ({ states: new Set(rows.map((r) => r.ref)) }),
    rowAtCell: (cell) => (owner[cell] >= 0 ? stateRows[owner[cell]] || null : null),
    focus: (row) => app.selectState(row.ref, { fly: true }),
    cellsOf: (row) => stateCells.get(row.ref) || [],
  });

  // --- metros (áreas urbanas funcionales) ---------------------------------------------------------------------------
  const metroHasLand = cities.some((c) => c.land);
  const metroRows = cities.map((c) => ({
    key: c.id, name: c.name, sub: (c.states || []).join("–"), level: "metros", ref: c,
    v: {
      name: c.name, states: (c.states || []).join("–"),
      ...econValues(c, "metros"), ...rolled(roll.metros, c.id),
      ...(metroHasLand ? landValues(c.land) : {}),
    },
  }));
  const metroByCity = new Map(metroRows.map((r) => [r.ref, r]));
  const metros = makeLevel({
    id: "metros", label: "Áreas urbanas", noun: "área urbana",
    rows: metroRows,
    fields: [F("name", "Área urbana", "text", { group: "Nombre" }), F("states", "Comunidades", "text", { group: "Nombre" }), ...econFields("metros"), ...rollupFields(), ...landKm2(), ...(metroHasLand ? landFields : [])],
    highlight: (rows, o = {}) => {
      const cells = new Set();
      for (const r of rows) for (const c of r.ref.footprint || [r.ref.cell]) cells.add(c);
      return { cells, cities: rows.length <= (o.ringMax ?? 30) ? new Set(rows.map((r) => r.key)) : undefined };
    },
    rowAtCell: (cell) => { const c = cellMetro.get(cell); return c ? metroByCity.get(c) : null; },
    focus: (row) => app.selectCity(row.ref, { fly: true }),
    cellsOf: (row) => row.ref.footprint || [row.ref.cell],
  });

  // --- counties (municipios) ---------------------------------------------------------------------------------------
  let counties_ = null;
  if (counties) {
    const cols = counties.columns;
    const cityName = new Map(cities.map((c) => [c.id, c.name]));
    const countyRows = cRows.map(({ r, i }) => {
      const v = {};
      cols.forEach((k, j) => (v[k] = r[j]));
      v.metro = v.auf ? cityName.get(v.auf) || null : null;
      return { key: v.geoid, name: shortCounty(v.name), full: v.name, sub: v.state, level: "counties", ref: i, v };
    });
    // counties.json rows follow world.json counties; map by geoid anyway in case they ever diverge.
    const worldIdx = new Map((w.raw.counties || []).map((c, k) => [c.geoid, k]));
    for (const row of countyRows) row.ref = worldIdx.get(row.key) ?? row.ref;
    const rowByWorld = new Map(countyRows.map((r) => [r.ref, r]));
    // Municipalities smaller than a hex own no cell: counties.json `cell` (the hex nearest the centre) stands in.
    const cellsOfRow = (r) => countyCells.get(r.ref) || (Number.isInteger(r.v.cell) ? [r.v.cell] : []);
    const fields = counties.fields.filter((f) => f.key !== "auf" && f.key !== "geoid" && f.key !== "cell").map((f) => ({
      ...F(f.key, f.key === "name" ? "Municipio" : f.label, f.format, { unit: f.unit, higher_is: f.higher_is, source: f.source, description: f.description, lens: COUNTY_LENS[f.key], group: groupOf(f.key) }),
    }));
    fields.splice(2, 0, F("metro", "Área urbana", "text", { group: "Nombre", description: "El área urbana funcional (AUF) a la que pertenece el municipio, si está en el mapa." }));
    counties_ = makeLevel({
      id: "counties", label: "Municipios", noun: "municipio",
      rows: countyRows, fields,
      highlight: (rows) => {
        const cells = new Set();
        for (const r of rows) for (const c of cellsOfRow(r)) cells.add(c);
        return { cells };
      },
      rowAtCell: (cell) => (countyOf[cell] >= 0 ? rowByWorld.get(countyOf[cell]) || null : null),
      focus: (row) => {
        let cells = cellsOfRow(row);
        // A municipality smaller than a hex owns no cell: frame its urban area instead, or open its community.
        if (!cells.length && row.v.auf) cells = cities.find((c) => c.id === row.v.auf)?.footprint || [];
        if (!cells.length) return app.selectState(row.v.state, { fly: true });
        let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
        for (const c of cells) {
          const x = grid.cx(c), y = grid.cy(c);
          x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y);
        }
        const R = grid.R * 6;
        frameBox(app, { x0: x0 - R, y0: y0 - R, x1: x1 + R, y1: y1 + R }, { pad: 24, maxScale: 2.4 });
      },
      cellsOf: (row) => cellsOfRow(row),
    });
  }

  const countiesOffMap = counties_ ? counties_.rows.filter((r) => !counties_.cellsOf(r).length).length : 0; // no hex, not even a stand-in
  return {
    app, nation, nat, vintage, countyVintage, countiesOffMap,
    levels: { states: states_, metros, counties: counties_ },
    stateCells, countyCells, cellMetro, metroByCity,
    items, typeById,
    source: (id) => srcTitle.get(id) || null,
  };
}

/** Municipality names are already short in Spanish ("Coruña, A"); kept for callers that shorten names. */
export function shortCounty(name) {
  return String(name || "");
}

function groupOf(k) {
  if (["population", "density", "age_mean", "elderly", "foreign", "household", "growth"].includes(k)) return "Personas";
  if (["income", "poverty", "income_per_person"].includes(k)) return "Prosperidad";
  if (["higher_education"].includes(k)) return "Conocimiento";
  if (["forest", "crop", "farmland", "developed", "land_km2"].includes(k)) return "Territorio";
  if (["name", "state", "metro", "province"].includes(k)) return "Nombre";
  return "Otros";
}

function makeLevel(def) {
  const fieldByKey = new Map(def.fields.map((f) => [f.key, f]));
  const byKey = new Map(def.rows.map((r) => [r.key, r]));
  return {
    ...def,
    byKey,
    field: (k) => fieldByKey.get(k) || null,
    value: (row, k) => row.v[k] ?? null,
    numericFields: () => def.fields.filter((f) => f.format !== "text"),
    /** Add fields after the fact (optional files that load on demand); a key already present is skipped. */
    addFields(list) {
      for (const f of list) {
        if (fieldByKey.has(f.key)) continue;
        def.fields.push(f);
        fieldByKey.set(f.key, f);
      }
    },
  };
}

// Optional files that load on demand were a US-only extension (military, districts, citizens). Spain has none of
// them: the call stays so views can keep awaiting it, and it adds no columns.
export async function extendData(data, names = []) {
  return Object.fromEntries(names.map((n) => [n, null]));
}

/** The highlight for a set of rows of one level, with defaults (gold outline, other land dimmed when asked). */
export function rowsHighlight(level, rows, opts = {}) {
  if (!level || !rows || !rows.length) return null;
  const one = rows.length === 1 ? rows[0] : null;
  const label = opts.label ?? (one ? (one.level === "states" ? one.name : `${one.full || one.name}${one.sub ? `, ${one.sub}` : ""}`) : "");
  return { ...level.highlight(rows, opts), dimOthers: !!opts.dim, color: opts.color, label };
}
