# Data contracts (v2)

> **Phase F0 note.** The Spain Strategy Map currently produces only `world.json` (the base map), `cities.json` (`[]`),
> `nation.json` (minimal: a "Spain" nation with null statistics) and `sources.json`. The other files described below
> (states, lenses, resources, counties, city views and so on) are inherited from the original US map and are not built
> yet. In the contracts below, "state" means an autonomous community (CCAA) and "county" a municipality.

The pipeline (Python) and the browser (web/js) agree on these files in `web/data/`. Change a contract here first, then on
both sides. All coordinates are **map km**: Albers equal-area, origin top-left, y **down** (see `pipeline/core/geo.py`).
Per-cell arrays have length `grid.cols * grid.rows`, with index `row * cols + col` (pointy-top, odd-r layout, see
`pipeline/core/hexgrid.py` ⇄ `web/js/hex.js`). `null` always means "no data". Never write `0` as a stand-in for "unknown".

## Pipeline conventions

* **Sources** (`pipeline/sources/*.py`) are discovered automatically: any `Source` subclass with `info = SourceInfo(...)`.
  `process()` returns a dict. It may include `"vintage"` (str) and `"_files"` (list of raw-file paths relative to
  `data/raw/<id>/` that this processing actually used; the Almanac cites only those).
* **Builders** (`pipeline/build/*.py`) are discovered automatically: a module with `REQUIRES`, `PRODUCES` and `build()`.
  They run in dependency order. Interims made by builders start with `_`. Helpers without `build()` (e.g. `yields.py`) are fine.
* The **`_world` interim** (made by `world`) holds: `grid`, `projection` (`MapProjection` kwargs), `owner`, `county`,
  `county_samples` (7 county indices per US cell, `[]` for other cells; sample 0 = centre), `states` (fips list, same order as
  world.json states), `counties` (geoid list), `water`, `cover`, `pct` (same as world.json). Builders that need to know whether a
  cell is land must use `owner[cell] >= 0`.
* Python is **standard library only**. Downloads go through `Source.download()` (or `Source.download_prefix()` for the
  leading block of a big sorted file), which cache them and record provenance in `data/raw/<id>/manifest.json`;
  `Source.discard(rel_path)` forgets a cached file that turned out to be bad. All three wrap `core.fetch`.
* Under `--offline` (`core.fetch.OFFLINE`, `Source.offline`) sources skip discovery requests and use the newest complete
  cached data; a download of a file that is not cached raises `OfflineError`.
* **Builder checks.** Any module in `pipeline/build/` may define `check(web_dir: Path) -> list[(level, message)]`, level one
  of `PASS`, `NOTE`, `WARN`, `FAIL`. `pipeline check` discovers and runs them after its own checks (section "builder
  checks", each line prefixed with the module name), so a new builder never edits `pipeline/check.py`. Rules: read only
  `web_dir` (tests point it at a tiny synthetic dataset); report a **missing output as a NOTE** (never WARN/FAIL: the unit
  tests run every discovered check against a dataset without your files); a check that raises is reported as a FAIL.
  Validate your file's shape against this document (keys, types, null rules, cell ranges against world.json) and add a
  short data-quality summary (counts, coverage) as PASS/NOTE lines.
* **ACS interims.** `acs_1yr` keeps every estimate line (`<TABLE>_<line>`, e.g. `C24010_007`) of its tables for the nation
  (`geos["0100000US"]`), the states (`geos["0400000USss"]`) and every CBSA (`cbsa["<5-digit code>"]`): `b01003 c24030 b19025
  b19013 b25064 b25077 b23025` plus, for citizens, `c24010` (occupation; male lines 002-037, female = male + 36), `b01001`
  (age; male 003-025, female = male + 24), `b01002` (median age), `c08301` (commute), `c15003` (education 25+) and `b05002`
  (place of birth). Sexes are **not** summed in the interim: builders add male + female lines. Census leaves some small
  CBSAs out of a table entirely (C24010 has 520 of 536 CBSAs, C08301 525, B05002 535): the CBSA's record then simply lacks
  those keys (treat as null). `acs_5yr` (`geos["0500000USsscc"]`, counties) adds `b21001` (veterans: `B21001_001` civilian
  population 18+, `_002` veterans) and `b23025` (`B23025_001` population 16+, `_006` in the armed forces, by residence).

## world.json

```jsonc
{
  "version": 2,
  "country": "Spain",
  "grid": {"radius": 10, "cols": 99, "rows": 79},
  "width": 1600.0, "height": 1200.0, "margin": 80,
  "insets": [{"name": "Canarias", "x0": 160.0, "y0": 940.0, "x1": 670.0, "y1": 1170.0}],   // map km, y down
  "owner":  [int],   // -1 water, -2 foreign land (Portugal, France, Andorra, Morocco, ...), >=0 index into states (CCAA)
  "county": [int],   // index into counties (municipality), -1 if none
  "elev":   [int],   // metres. Land: mean of land samples only. Water: mean of the hex's ETOPO samples below sea
                     // level (its depth, <= 0); lakes: min(mean, 0); -4000 where ETOPO has no samples
  "elev_max": [int], // optional: metres, the highest land sample in the hex (0 for water); the art uses it for snow
  "water":  [int],   // 0 land, 1 ocean, 2 coast (next to land or shallower than 200 m), 3 lake
  "relief": [int],   // 0 flat, 1 hills, 2 mountains, 3 peaks (alpine). 0 for water. A hex whose lower 60% of land
                     // samples is flat lowland (spread < 60 m, under 400 m) is eased one class (valley floors)
  "cover":  [int],   // land-cover id (see tables.cover). 0 = none (water, foreign land, no WorldCover land points)
  "pct": {           // share of the cell's valid WorldCover points, 0..100 ints (Spanish cells; 0 elsewhere)
    "forest": [int], "crop": [int], "grass": [int], "shrub": [int], "wetland": [int], "developed": [int]
  },                 // no "pasture": pastures are inside grass
  "tables": {
    "water":  [{"id": 0, "name": "Land"}, {"id": 1, "name": "Ocean", "color": "#1b4266", "rule": "..."}, ...],
    "relief": [{"id": 0, "name": "Flat", "rule": "..."}, ...],
    "cover":  [{"id": 3, "key": "forest_mixed", "name": "Tree cover", "color": "#43703f", "worldcover": [10], "rule": "..."}, ...]
  },
  "states":   [{"fips": "01", "abbr": "AN", "name": "Andalucía"}],   // the 19 CCAA in INE code order; owner = index
  "counties": [{"geoid": "01001", "name": "Alegría-Dulantzi", "province": "01"}],   // all LAU municipalities, code order
  "forced":   [{"cell": 1234, "name": "Ceuta", "reason": "Ceuta (19 km2) is smaller than one hex"}],
  "rivers":   [{"name": "Tajo", "rank": 1, "pts": [x0, y0, x1, y1, ...]}]   // clipped to the map; no lake centerlines
}
```

* **`states`**: 17 autonomous communities plus Ceuta and Melilla, 19 entries. `fips` is the INE community code, `abbr` the
  ISO 3166-2 suffix. **`counties`** are the GISCO LAU 2024 municipalities (`geoid` = INE municipality code, `province` =
  INE province code).
* **Ownership**: each hex samples 7 points (centre plus 6 at 60% of the way to the corners). A hex is land when more than
  half are land and it is not a tidal bay. `owner` is the CCAA with the most Spanish samples (one vote per sample; ties go
  to the centre's CCAA, else the lowest index). `county` is the centre's municipality if it lies in the owner CCAA, else
  the most common municipality among the samples in that CCAA (ties: lowest index).
* **`insets`**: the Canary Islands are drawn in a frame in the Atlantic (map km rectangles). Hexes inside a frame own only
  Spanish municipalities or sea. The projection is Albers equal-area (standard parallels 36 and 44, origin 40N 3W) for the
  mainland and a second Albers per inset.
* **`forced`**: cartographic exceptions. Ceuta, Melilla and each island get a land hex even if sampling would not give one.
  Lists only the hexes that were actually changed.

Cover ids used (fixed ids): 0 none · 3 forest_mixed (tree cover) · 4 scrub (shrubland) · 5 grassland · 7 cropland ·
8 wetland · 9 urban (built-up) · 10 barren (bare / sparse) · 11 ice (snow & ice). Ids 1, 2 and 6 are not used.
Dominant cover per cell = the largest group among its valid WorldCover points (water and no-data are ignored). A cell is
**urban** if WorldCover class 50 (built-up) is ≥ 20% of valid points. Cover comes from the last overview of ESA WorldCover 2021
(~600 m pixels) sampled every 1 km.

## cities.json

Written by `pipeline/build/economy.py` (phase F2). Empty list (`[]`) only in F0. The 68 cities are the INE functional
urban areas (AUF), sorted by population, descending:

```jsonc
{
  "id": "ES001F",                 // INE AUF code
  "name": "Madrid", "full": "Área urbana funcional de Madrid",   // name = most populous member municipality
  "states": ["MD", "CM"],         // CCAA abbreviations of the members, ordered by member population
  "metro": true, "capital": true, // capital: the AUF that contains Madrid (municipality 28079)
  "core": "28079",                // INE code of the most populous member
  "x": 532.9, "y": 459.8,         // centroid of the core's largest ring (map km, inset-aware)
  "cell": 2310,                   // land cell (owner >= 0), unique per city; banners anchor here
  "population": 6700000,          // sum of the members' Censo 2026 population
  "employed": 3100000,            // sum of the members' occupied residents (ine_jobs); absent members count 0
  "employed_members": [40, 41],   // [members present in ine_jobs, members of the AUF]
  "jobs_coverage": 0.998,         // share of employed that comes from members with CNAE sections (0..1)
  "yields": {"food": 1, "production": 2, "gold": 3.1e11, "science": 4, "culture": 5},
  "jobs": {"a": 123, "...": 0, "u": 0},   // CNAE section a..u; only members with sections (not the 4-sector ones)
  "income_per_person": 17500, "median_income": null,   // ADRH 2024, population-weighted over members with a value
  "home_value": null, "median_rent": null, "rent_burden": null, "unemployment": null,
  "gdp": 3.1e11, "gdp_year": 2023, "gdp_estimated": true, "gdp_by_industry": null,
  "growth": 0.0412, "growth_years": [2021, 2026],
  "pop_series": null,
  "counties": ["28079", "28005", "..."],   // member municipality codes (INE, 5 digits), sorted
  "footprint": [2310, 2311, "..."],        // land cells of the city, sorted (see below)
  "ranks": {"population": 1, "gdp": 1, "gdp_per_capita": null, "growth": 7,
            "food": 1, "production": 1, "gold": 1, "science": 1, "culture": 1},
  "peers": ["ES002F", "..."]               // ids of the 5 cities closest in population
}
```

* **Yields**: workers where they live (Censo anual de población 2024, INE), by CNAE section: `food` = A,
  `production` = B+C+D+E+F (includes energy, water and waste), `science` = J+M, `culture` = R, `gold` = imputed GDP.
  Members of 50-500 inhabitants only have a 4-sector split: they add `agricultura` to food and
  `industria` + `construccion` to production, and nothing to science or culture (so those two are a floor).
* **`gdp` is imputed** (`gdp_estimated: true`): INE publishes GDP for provinces, not municipalities. The GDP of each
  province is split among ALL its municipalities by occupied residents (`E_m`; for a municipality absent from
  ine_jobs, `pop_m` times the province's known employed/population ratio), and a city adds up its members. Per
  province the parts add up to the published figure (1e-6); `check` verifies it from the `_economy_stats` interim.
  Because the split follows employment, imputed GDP per head is almost a provincial constant, so
  `ranks.gdp_per_capita` is `null` for every city.
* **`footprint`**: land cell `h` belongs to a city when `sum(pop_m * f_mh over its members) / sum(pop_m * f_mh over
  all municipalities) >= 0.5`, with `f_mh` from the `_world` interim `muni_weights` (each municipality's fractions
  sum to 1). The city's own `cell` is always included, so it is never empty.
* **`growth`**: sum of Censo 2026 population / sum of 2021 population - 1 over the members that have both, over
  `growth_years = [2021, 2026]` (the end equals nation.json `year`).
* **`ranks`**: 1 = highest among all cities, `null` where the value is null; non-null ranks are a permutation of
  1..N, ties broken by population. **`peers`**: the 5 other cities closest in population by ratio
  (|log(p / q)|), nearest first.
* Null by design: `median_income`, `home_value`, `median_rent`, `rent_burden`, `unemployment`, `gdp_by_industry`,
  `pop_series`.

* **`land`** (cities.json, states.json and nation.json): `{"forest", "crop", "developed"}` shares 0..1 of the land
  (ESA WorldCover 2021, same groupings as world.json `pct`), summed over the member municipalities' own lattice points
  (not over whole hexes). The points come from world.json's allocation loop (`_world` `muni_cover` = per municipality
  `[forest, crop, developed, sampled land]` point counts). `null` when no member has a sampled point.

## states.json

A list in the order of world.json `states` (the 19 autonomous communities, CCAA):

```jsonc
{
  "fips": "13", "abbr": "MD", "name": "Comunidad de Madrid",   // INE CCAA code, ISO 3166-2 suffix
  "population": 7000000,                // sum of its municipalities (each counted in its own CCAA, not by hexes)
  "employed": 3300000, "jobs": {"a": 1, "...": 2},   // official INE totals by section (ine_jobs.regions.ccaa)
  "jobs_source": "official",            // "municipal_sum" when the CCAA is missing there (member sums, undercount)
  "yields": {"food": 1, "production": 2, "gold": 3.1e11, "science": 4, "culture": 5},
  "income_per_person": 18000, "median_income": null,
  "home_value": null, "median_rent": null, "rent_burden": null, "unemployment": null,
  "gdp": 3.1e11, "gdp_year": 2023, "gdp_estimated": false, "gdp_by_industry": null,   // published (ine_gdp.ccaa), not summed
  "growth": 0.03, "growth_years": [2021, 2026],
  "ranks": {"population": 1, "gdp": 1, "gdp_per_capita": 3, "growth": 5, "food": 1, "production": 1, "gold": 1, "science": 1, "culture": 1},  // 1..19
  "label": null                         // optional anchor {x, y, angle, size}; null here, the frontend computes its own
}
```

## nation.json

```jsonc
{
  "vintage": "INE: Censo anual de población 2026 y 2024 (ocupados), Contabilidad Regional 2023", "year": 2026,
  "gdp_vintage": "INE, Contabilidad Regional de España",
  "nation": {"name": "España", "population": 49000000, "employed": 21000000, "jobs": {"a": 1, "...": 2},
             "yields": {"food": 1, "production": 2, "gold": 1.5e12, "science": 4, "culture": 5},
             "income_per_person": 15000, "median_income": null,
             "gdp": 1.5e12, "gdp_year": 2023, "growth": 0.04, "growth_years": [2021, 2026]},
  "yields": [{"key": "food", "icon": "y-food", "emoji": "🌾", "label": "Comida", "color": "#7fbf3f",
              "unit": "workers|usd", "industries": ["a"], "description": "..."}],   // unit "usd" = money (shown in euros)
  "industries": {"a": "Agricultura, ganadería, silvicultura y pesca", "...": "...", "u": "..."},   // CNAE A..U, keys "a".."u"
  "attribution": [{"data": "...", "source": "...", "license": "..."}]
}
```

`jobs`, `employed` and `gdp` of the nation are the published INE totals. In F0 (no statistics) `year` is `null`,
`yields` and `industries` are empty and `cities.json` is `[]`. `check` requires, once `year` is set: `growth_years`
ending at `year`, population, gdp and growth present, and `industries` keys equal to `nation.jobs` keys.

## lenses.json

**Spain (F1, current).** Produced by `pipeline/build/lenses.py` (REQUIRES `_world`, `ine`, `gisco_lau`; also writes the
interim `_lens_stats` with the population totals that `check` uses for the conservation test). Top level:
`{"vintage", "attribution": [{data, source, license}], "groups", "lenses"}`; all texts are Spanish. Groups: `people`
(Población), `prosperity` (Prosperidad), `knowledge` (Conocimiento), `land` (Territorio). Lens `format` is one of
`int|eur|pct|float|minutes|years|category`; `eur` = euros (es-ES). `pct` values are 0..1 fractions (`growth` may be
negative). Lens ids: `density` (hab./km², log), `growth` (2021-2026), `age`, `elderly`, `foreign`, `household`,
`income` (eur), `poverty` (higher_is bad), `higher_education`, and the land lenses `forest`, `farmland`, `developed`
(world.json `pct`). There is no Gini lens: a mean of Ginis is not a Gini. `values[i]` is null on non-Spanish cells.

*Allocation by area.* world.py samples every Spanish land hex on the 1 km lattice used for land cover and locates each
point in a municipality (points under an inset frame only see the municipalities drawn in an inset). Interim `_world`
gets `muni_weights` (per cell: `[[municipality index, fraction]]`, fraction = its points in the cell / its points in all
Spanish land hexes, so each municipality sums to 1), `muni_fallback` (municipalities with no lattice point in a land hex:
all of it goes to the nearest land hex to an interior point) and `land_km2` (per cell, lattice points on Spanish
municipalities x 1 km2; fallback municipalities add no area). world.json gets `muni_cell` (aligned with `counties`: the
hex whose `county` is the municipality, else the hex holding most of it, never -1) for the search box.

*Hex values.* `hex_pop = sum f*P` (P = Censo anual 2026). `density = hex_pop / land_km2`. The other INE lenses are a
ratio of weighted sums over the municipalities with a value: `age`, `elderly`, `foreign` (1 - Spanish share), `income`,
`poverty` weighted by people; `household` by households (people / size); `higher_education` = higher_ed / pop15; `growth`
= sum f*P2026 / sum f*P2021 - 1 over municipalities with both. A hex is null unless those municipalities hold at least
`COVERAGE_MIN` = 90 % of its `hex_pop`. `domain` = [p2, p98] of the non-null hex values.

*Inherited from the US map* (kept below for reference; the sections that name US data do not apply to Spain).


```jsonc
{
  "vintage": "ACS 2024 5-year",
  "groups": [{"id": "people", "name": "People"}, {"id": "prosperity", "name": "Prosperity"}, {"id": "knowledge", "name": "Knowledge"},
             {"id": "life", "name": "Daily life"}, {"id": "land", "name": "Land"}],
  "lenses": [{
    "id": "density", "group": "people", "name": "Population", "icon": "l-people", "emoji": "👥",
    "unit": "people / km²", "format": "int|usd|pct|float|minutes|years",   // pct values are 0..1 fractions
    "scale": "log|linear", "domain": [1, 2000],   // 2nd-98th percentile of the hex values, computed at build time "ramp": ["#..", "..."], "higher_is": "good|bad|neutral",
    "source": "acs_5yr", "description": "...",
    "values": [number|null],       // per cell; null on non-US cells
    "note": "..."                  // optional: a short caveat the legend always shows (e.g. what a count does not measure)
  }]
}
```

**Categorical lenses** (`"format": "category"`): each value is an integer index into `categories` (or null);
`"categories": [{"id": "catholic", "name": "Catholic", "color": "#…", "description"?: "…"}]` (≥ 2), `ramp` = the
categories' colours in the same order, `"scale": "linear"`, `"domain": [0, n - 1]` (so the ramp stops land exactly on the
colours). The legend shows swatches (click one to show only it) and tooltips show the category name. `check` enforces all
of this.

**County lenses from the Religion Census, CDC PLACES, FEMA and ACS veterans** (ids are a contract with the frontend, which may link to them):

| id | group | format | values | note (legend caveat) |
|---|---|---|---|---|
| `faith` | `faith` (group "Faith") | `float`, unit `adherents per 100 residents`, domain clamped to `[0, 100]` | 2020 U.S. Religion Census adherents ÷ 2020 population × 100 (compute it; do not trust the RATE columns), per county spread to hexes like the other county lenses. Can exceed 100 (adherents are counted where the congregation is) | required: counts congregations' adherents where they worship, not residents' beliefs; about half of Americans are counted; some traditions (notably historically Black churches) are under-reported; 2020 data |
| `faith_tradition` | `faith` | `category`: `evangelical`, `mainline`, `black_protestant`, `catholic`, `orthodox`, `lds`, `other` (Latter-day Saints split out of ARDA's "Other") | the county's largest tradition by adherents; null where no adherents were reported | same caveat |
| `amenities` | `life` | `float`, unit `index`, `higher_is: good` | 100 − 10 × mean z-score of the CDC PLACES age-adjusted shares of frequent mental distress, depression, fair/poor health and no leisure-time activity (state the exact recipe in `description`); null where PLACES has no BRFSS core data (all of KY and PA in the 2025 release): never imputed | required: model-based estimates, not a happiness survey |
| `disasters` | `hazards` (group "Hazards") | `int`, unit `declarations` | distinct FEMA major-disaster (DR) declarations naming the county since 2000 (Biological/COVID excluded; deduplicated by disaster number) | required: a declaration is an administrative act, not a measure of damage |
| `veterans` | `people` | `pct` (0..1) | ACS 5-year `B21001_002 / B21001_001` (veterans among civilian adults 18+) | |

Connecticut: the map's counties are the 2022 planning regions (`09110`…`09190`). Sources on the 8 legacy counties (USRC,
FEMA) need an overlap crosswalk, or CT stays null and the lens `note`/`description` says so.

**As built** (`pipeline/build/lenses.py` `community_lenses`, appended after the land lenses so the
existing lenses keep their array positions; every county value is spread to hexes with the same population weights as
the other county lenses, and the county formulas are shared with counties.json):

* `faith` (source `usrc_2020`): county `adherents / POP2020 × 100` (1 decimal); hex = population-weighted mean;
  `domain` fixed `[0, 100]` (no percentile note); counties can exceed 100 (max ≈ 450). **CT is null** (USRC's 8 old
  counties are not apportioned: no town-level adherent counts exist), as are the two counties with a blank total.
* `faith_tradition` (`usrc_2020`): categories in this order `evangelical, mainline, black_protestant, catholic, orthodox,
  lds, other` (each `{id, name, color, description}`; `other` = ARDA "Other" minus Latter-day Saints). Hex value = the
  tradition with the most adherents after summing each county's adherents × the share of the county in the hex; null
  where none were reported. Icon `l-faith-tradition`, name "Largest tradition".
* `amenities` (`cdc_places`), **named "Wellbeing"** (the id stays `amenities` for URLs and icons; the description says
  it stands in for the strategy-game Amenities): `100 − 10 × mean(z)` over `mhlth, depression, ghlth, lpa` (`_adjprev`), z against the
  unweighted mean ± SD of all mapped counties that have all four (the values are printed in `description`); unit
  `index (100 = average county)`, 1 decimal. Null for KY, PA (and Loving County, TX). PLACES already uses CT planning
  regions.
* `disasters` (`fema_declarations`): hex = population-weighted mean of the county counts **rounded to a whole number**
  (`format: int`); no nulls (0 = no declaration, a real zero). CT regions count a disaster declared for any old county
  they overlap (Census town crosswalk `ct_cou_to_cousub_crosswalk.xlsx`).
* `veterans` (`acs_5yr`): pct, 4 decimals; no `note`.
* Icons (fall back to the emoji until `web/js/icons.js` has them): `l-faith` 🕍, `l-faith-tradition` ⛪, `l-amenities` 🎭,
  `l-disasters` 🌪️, `l-veterans` 🎖️. Groups `faith` and `hazards` sit between `life` and `land`.
* `lenses.py` defines `check(web_dir)` (presence, required notes, faith domain, a short coverage summary).

## resources.json

```jsonc
{
  "types": [{"id": "nuclear", "name": "Nuclear plant", "category": "energy|mineral|agri",
             "emoji": "☢️", "icon": "r-nuclear", "color": "#e8d44d",
             "unit": "MW", "description": "...", "source": "eia_860m"}],
  "items": [{"type": "nuclear", "name": "Palo Verde", "x": 1234.5, "y": 2345.6, "cell": 4321,
             "value": 3937, "detail": "3 units, Arizona Public Service"}]
}
```

Each item also has `"state": "AZ"` (the state the source files the site under, e.g. EIA's plant state; for oil/gas
play hexes, or when that state is not on the map, the state owning its `cell`; a border site such as Vogtle, GA, can sit
in a hex another state owns) and `"cbsa": "38060"` (the id of the
cities.json city whose member counties contain the county at the cell's centre, `world.county[cell]`, or `null`).

Items are the meaningful sites only (thresholds are documented in each type's `description`). The frontend draws at most
one icon per cell at low zoom (the highest-ranked type wins) and may show more when zoomed in.

```jsonc
"summary": {
  "note": "Totals of the mapped sites only (each type's threshold applies) ...",
  "national": {"nuclear": {"count": 54, "value": 96952, "unit": "MW"}, "oil": {"count": 120, "value": null, "unit": "km² play area"}},
  "states":   {"AZ": {"nuclear": {"count": 1, "value": 3937, "unit": "MW"}, "...": {}}}   // only types present
}
```

`summary.national` has every type in `types`; `summary.states` has, per state abbr with at least one item, the types
present there. `value` is the sum of the items' `value` (nulls skipped), or `null` for a type whose values are not
additive: oil and gas items each carry their whole play's area, so summing them is meaningless.

## counties.json

The municipality explorer: one row per municipality (8,132; world.json `counties` order), **column-oriented**, built by
`pipeline/build/explorer.py`. Municipal values come from the INE interim, never from hex lenses; `null` = no data, never 0.

```jsonc
{
  "vintage": "INE: Censo anual de población 2026, renta y demografía 2024",
  "attribution": [{"data": "...", "source": "INE ...", "license": "..."}, {"data": "...", "source": "Eurostat GISCO ...", "license": "..."}],
  "fields": [{"key": "population", "label": "Población", "format": "int", "unit": "personas", "higher_is": "neutral",
              "source": "ine", "description": "..."}],           // one per column, same order; texts in Spanish
  "columns": ["geoid", "name", "state", "province", "population", "land_km2", "density", "growth", "age_mean",
              "elderly", "foreign", "household", "income", "poverty", "higher_education", "auf", "cell"],
  "rows": [["01001", "Alegría-Dulantzi", "PV", "01", 2981, 19.9, 149, 0.0195, 41.0, 0.135, 0.098, 2.5, 17698, 0.117, 0.4295, "ES012F", 1024]]
}
```

`format` is `text`, `int`, `float`, `pct` (**0..1 fractions**) or `eur`. `geoid` is the 5-digit INE code (string), `state`
the CCAA abbreviation, `province` 2 digits. `population` = Censo anual de población 2026; `land_km2` = GISCO area;
`density` = population / land_km2; `growth` = 2026 / 2021 - 1; `age_mean` is the **mean** age (not the median);
`elderly` = share aged 65 or more; `foreign` = share with **foreign nationality** (not foreign birth); `income` = mean
income per person (ADRH, not the median); `poverty` = share under 60 % of the median income (null where INE publishes
none); `higher_education` = residents 15+ with higher education over residents 15+ (INE publishes it for about half
of the municipalities, the larger ones; the rest are `null`); `auf` = cities.json id of the functional urban area, or
`null`; `cell` = world.json `muni_cell` (representative hex).

## Optional map-layer files

Every file below is **optional**: the app and `check` work without it, and each owning builder validates its own file with
a `check(web_dir)` (see Pipeline conventions). Shared rules:

* Top level always has `"version": 1`, `"vintage"` (a human string, or `{part: string}`), and `"sources": [source ids]`
  (sources.json ids, so the Almanac can cite them).
* `cell` = a world.json cell index (pointy-top odd-r, `row * cols + col`); a site's `cell` is a US land cell (`owner >= 0`)
  unless stated. `x`, `y` = map km. `county` = 5-digit GEOID from world.json `counties` (or null), `cbsa` = a cities.json
  `id` (or null), `state` = postal abbr.
* Money is **US dollars** (not thousands or millions) unless the key says otherwise (`_musd`); shares are 0..1 fractions;
  `null` = unknown, never `0`. A value that is a **lower bound** (suppressed parts left out) says so (`lower_bound: true`
  or a `suppressed` count).
* Rules that pick things (districts, wonders, routes) are published inside the file as text (`rule` / `rules`) so the UI
  and the Almanac can quote them.
* **Loading** (browser): `infrastructure`, `military`, `wonders`, `trade` load eagerly right after the first frame (keep
  each **under ~300 kB**); `citizens`, `districts`, `disasters` load on demand with `app.loadData(name)`.

### citizens.json (lazy)

Per city (and nation), three **separate** distributions of residents, built by `pipeline/build/explorer.py` from the INE
municipal data summed over the member municipalities. Each has its own base: `age` and `nationality` over all residents,
`education` over residents aged 15 or more. Members without data are left out of that distribution and the number of
municipalities used is in `coverage` (education exists for about half of the municipalities: the larger ones). No
occupations.

```jsonc
{
  "version": 1, "vintage": "INE, Censo anual de población 2024", "year": 2024, "sources": ["ine"],
  "figures": {"age": 10, "education": 10, "nationality": 10},        // icons per distribution (largest remainder)
  "rows": {"age": "Habitantes por edad", "education": "...", "nationality": "..."},
  "bases": {"age": "Habitantes", "education": "Habitantes de 15 años o más", "nationality": "Habitantes"},
  "groups": {"age": [{"key": "under65", "label": "Menores de 65 años", "icon": "c-midlife"}, {"key": "elder", ...}],
             "education": [{"key": "other"}, {"key": "higher"}], "nationality": [{"key": "spanish"}, {"key": "foreign"}]},
  "rule": {"text": "..."}, "attribution": [...],
  "national": { /* a row */ },
  "cities": {"ES001F": { /* a row */ }}
}
// a row: each distribution is null when no member has data
{"age": {"base": "Habitantes", "total": 3500000, "counts": {"under65": 2800000, "elder": 700000},
         "shares": {"under65": 0.8, "elder": 0.2}, "figures": {"under65": 8, "elder": 2},
         "coverage": [240, 240], "mean": 43.9},      // coverage = [municipalities with data, members]; mean = mean age weighted by population
 "education": {...}, "nationality": {...}, "specialists": [], "reliable": true}
```

`counts` add up to `total` and `shares` to 1 exactly (the second share is 1 minus the first). `age.under65` / `elder` come
from the 65+ share times population; `nationality` from the Spanish-nationality share times population (foreign
nationality, not foreign birth); `education.higher` from residents 15+ with higher education. `specialists` is always empty.

### districts.json (lazy)

Sector specialisations of each city, as strategy-game districts named by CNAE section (no game's district names), built
by `pipeline/build/explorer.py`. The jobs are **residents' jobs by place of residence** (Censo anual de población 2024),
not where the firms are. Location quotient LQ = (city jobs in the section / city jobs in all sections) / (the same
for Spain).

```jsonc
{
  "version": 1, "vintage": "INE, Censo anual de población 2024", "year": 2024, "sources": ["ine_jobs", "auf"],
  "note": "Especialización de la población ocupada según dónde vive (...): cociente de localización frente a España. No mide dónde están las empresas.",
  "rule": {"min_lq": 1.25, "min_jobs": 1000, "min_share": 0.01, "max_per_city": 5, "excluded": ["T", "U"], "text": "..."},
  "catalog": [{"id": "a", "name": "Agricultura, ganadería y pesca", "icon": "i-agriculture", "color": "#7fbf3f",
               "sections": ["A"], "sub": {}, "badge": {"id": "a", "label": "Ciudad agraria", "labels": {}},
               "description": "...", "caveat": null}],        // one entry per section id "a".."s" (not t, u); icon = "i-" + web/js/industry.js iconKey
  "industries": {"a": {"title": "Agricultura, ganadería y pesca", "us_emp": null, "emp": 829713}},
  "national": {"emp": 21000000, "avg_pay": null},
  "cities": {"ES001F": {"emp": 3387488,                       // city jobs over all sections
                        "districts": [{"id": "j", "lq": 2.08, "emp": 242273, "share": 0.0715, "strength": 125000,
                                       "via": "broad", "sub": null, "lower_bound": false, "suppressed": 0}],
                        "badge": {"id": "j", "label": "Ciudad digital", "district": "j", "basis": "census", "text": "..."} | null}},
  "attribution": [...]
}
```

* **Rule**: a section (not T or U) appears when LQ >= 1.25 and it has at least 1,000 jobs or 1 % of the city's jobs;
  `strength` = jobs - jobs / LQ; sorted by strength, up to 5; an empty `districts` list is allowed.
* **Badge** = the top specialisation (its id is also `district`), or `null` when the city has none. `basis` is always
  `census`. `sub`, `lower_bound` and `suppressed` are kept for the web code but are always `null` / `false` / `0`.

### infrastructure.json (eager)

Tile improvements: roads and rail rasterised onto hex links (no polylines), plus ports and airports as sites. Built by
`pipeline/build/infrastructure.py` from `natural_earth_roads` (NE 1:10m roads + railroads, pinned v5.1.2), `usace_ports`
and `faa_airports` (both in `pipeline/sources/transport_hubs.py`). About 200 kB.

```jsonc
{
  "version": 1,
  "vintage": {"roads": "Natural Earth v5.1.2 (1:10m)", "rail": "…", "ports": "USACE principal ports, CY2023 tonnage",
              "airports": "FAA CY2025 enplanements, CY2025 all-cargo"},
  "sources": ["natural_earth_roads", "usace_ports", "faa_airports"],
  "rules": {"roads": "…", "rail": "…", "ports": "…", "airports": "…"},   // selection rules, quotable in the UI
  "road_classes": [{"id": "interstate", "name": "Interstate"}, {"id": "major", "name": "Major highway"}],
  "rail_tiers": [{"id": "main", "name": "Main line"}, {"id": "secondary", "name": "Secondary line"}],
  "hubs": {"L": "Large hub", "M": "Medium hub", "S": "Small hub", "N": "Nonhub primary"},
  "roads": [[3721, 3722, 0, "I-95"]],   // [cell a, cell b, class index, route name or null]; a < b, neighbours, unique pair
  "rail": [[3721, 3845, 0]],            // [a, b, tier index]; a < b, neighbours, unique pair
  "ports": [{"id": "2031", "name": "Houston Port Authority", "type": "coastal|great_lakes|inland", "rank": 1,
             "tons": 309531236, "domestic": …, "foreign": …, "imports": …, "exports": …, "year": 2023,   // short tons
             "x": …, "y": …, "cell": 9123, "county": "48201", "cbsa": "26420", "state": "TX"}],     // sorted by rank
  "airports": [{"id": "ATL", "name": "Hartsfield/Jackson Atlanta International", "city": "Atlanta", "hub": "L|M|S|N|null",
                "enplanements": 51459786, "enplanements_prev": 52511402, "cargo_lbs": 2864017498 | null, "year": 2025,
                "x": …, "y": …, "cell": …, "county": …, "cbsa": …, "state": "GA"}]   // sorted by enplanements, desc
}
```

* **Links** join **neighbouring** cells, at least one end on US land (`owner >= 0`) and neither end foreign land
  (`owner == -2`). Each line is sampled every 4 km, gaps are filled by a hex line walk, and a cell the line only clips
  at a corner is dropped (so a road along a row boundary does not zigzag). A pair appears once, with its best class
  (an Interstate link is never also a major link). Rail samples inside Canada or Mexico are dropped.
* **Road classes**: 0 = every NE road with `level == "Interstate"`; 1 = other roads at NE scale rank ≤ 6 plus
  expressways typed "Major Highway"/"Beltway". Route names: `I-95`, `US 101`, or the NE name for state roads; where
  several routes share a link the lowest number wins. **Rail tiers**: 0 = NE scale rank ≤ 5, 1 = 6–7.
  Natural Earth road and rail work is map art, not statistics (older alignment, about half the real rail network).
* **Ports**: USACE principal ports in the lower 48 (port-area centroid; long river ports are approximate). **Airports**:
  every primary airport (`hub` L/M/S/N) plus every airport in FAA's all-cargo table (`hub` null if not primary),
  placed by FAA id with the NASR airport master. `enplanements` null when the airport is only in the cargo table;
  `cargo_lbs` (all-cargo landed weight) null when it is not in the cargo table (not zero cargo).
* A site's `cell` is the US land cell at its point, else the nearest within 2 hexes; `x`/`y` stay the true position (a
  port's may be on water). `county`/`cbsa` come from that cell's centre county (OMB delineation, cities.json ids only).
  Tons and pounds are as published (short tons, landed lbs).

### trade.json (eager)

Freight "trade routes" between FAF5 zones (`faf5`), domestic flows only (`trade_type` 1), newest FAF year. Built by
`pipeline/build/trade.py` (after infrastructure, whose road links the drawn paths follow). About 70 kB.

```jsonc
{
  "version": 1, "vintage": "FAF5.7.1, 2024", "year": 2024, "sources": ["faf5"],
  "rule": "The 40 largest domestic freight flows by value between FAF zones in different states …",   // quote in the UI
  "path_note": "FAF gives a shipment's start and end zones, not its route: …",                          // quote in the UI
  "units": {"value_musd": "million current US dollars", "tons_k": "thousand short tons", "tmiles_m": "million ton-miles"},
  "modes": [{"id": "truck", "name": "Truck"}, {"id": "rail", …}, {"id": "water"}, {"id": "air"}, {"id": "multiple"},
            {"id": "pipeline"}, {"id": "other"}],                  // FAF dms_mode 1..7, in this order
  "commodities": {"43": "Mixed freight"},                          // SCTG2 code → FAF's short name (codes used below)
  "national_musd": {"domestic": 19788731.6, "import": 3134841.1, "export": 2045950.5},   // all zones incl. AK and HI
  "zones": [{"id": "092", "faf": ["092", "341", "363", "423"], "name": "New York-Newark, NY-NJ-CT-PA", "short": "New York",
             "kind": "metro|rest_of_state", "states": ["CT", "NJ", "NY", "PA"], "cities": ["35620", "…"],   // population order
             "counties": 30,                                          // member counties on the map
             "anchor": {"cell": 3845, "x": …, "y": …, "city": "35620" | null} | null,
             "partners": [["251", 61923.5, "truck"]],                // top 5 partner zones, any state: [zone, value_musd, top mode]
             "totals_musd": {"within": …, "other_zones": …, "import": …, "export": …}}],   // sorted by id
  "routes": [{"a": "092", "b": "251", "rank": 1, "value_musd": 61923.5, "tons_k": 15089.1, "tmiles_m": 3471.2,
              "modes": {"truck": 0.7268, "rail": 0.01, "...": 0}, "top_mode": "truck", "top_commodity": "43",
              "dist_km": 306, "path": [3845, 3846, "…"]}]           // rank order (value, desc)
}
```

* **Zones**: Alaska and Hawaii are dropped (115 zones remain). The parts of one CFS area split by a state line
  (same CSA/CBSA code) are **merged** into one zone: `id` = its lowest FAF code, `faf` lists the parts. Member counties
  come from the 2023 OMB delineation (CSA or CBSA code within the part's state; Knoxville's 2017 CSA 314 is today's 315);
  a rest-of-state zone holds the state's other counties. Each cities.json city joins the zone holding most of its
  member counties. `anchor` = the biggest city's banner cell, or (no city) the land cell nearest the middle of the
  zone's cells; `null` only if neither exists.
* **Routes**: only flows between FAF parts in **different states** count, the two zones may share no state, and their
  anchors must be ≥ 250 km apart; both directions are summed; the 40 largest by value are kept. `modes` are value
  shares (sum to 1). `top_commodity` is the largest SCTG2 by value among each part pair's top 5. `path` is a chain of
  neighbouring cells from `a`'s anchor to `b`'s along the cheapest road links (Interstate < major < rail < cross-country
  < water steps): a drawing aid, not data (FAF assigns no route).
* Values are FAF model estimates in **million current dollars** (`value_musd`) and **thousand short tons** (`tons_k`), as
  FAF publishes them; say so in the UI. Pipeline-dominated routes (crude, gas) are real and should get their own style.

### military.json (eager)

Built by `pipeline/build/military.py` from `mirta` (`sources/mirta.py`), `dmdc_personnel` (`sources/dmdc.py`),
`oldcc_spending` (`sources/oldcc.py`) and `acs_5yr`. About 280 kB (mostly installations).

```jsonc
{
  "version": 1,
  "vintage": {"installations": "DoD MIRTA FY2025 (layer edited …)", "personnel": "DMDC, as of September 30, 2026",
              "spending": "OLDCC FY2024", "acs": "ACS 2024 5-year"},
  "sources": ["mirta", "dmdc_personnel", "oldcc_spending", "acs_5yr"],
  "rule": "A metro gets an Encampment when …",           // the Encampment rule, quotable as is
  "rules": {"tier": "…", "ranges": "…", "encampment": "…", "installations": "…",   // every selection rule as text
            "names": "…"},                       // the 2025 Army renames applied to MIRTA names, with the source URL
  "flagships": ["Naval Station Norfolk", …],             // the curated flagship list (names as in MIRTA)
  "caveats": "…",                                         // show where installation/personnel numbers appear
  "components": [{"id": "army", "name": "Army", "codes": ["usa"]}, {"id": "navy"}, {"id": "air_force"}, {"id": "marines"},
                 {"id": "army_reserve"}, {"id": "navy_reserve"}, {"id": "air_force_reserve"}, {"id": "marine_reserve"},
                 {"id": "army_guard"}, {"id": "air_guard"}, {"id": "other"}],   // Space Force sites are filed as air_force
  "installations": [{"id": "fort-bragg-usa", "name": "Fort Bragg", "component": "army", "joint": false,
                     "name_mirta": "Fort Cavazos",          // optional: only when `name` differs (see rules.names);
                                                           // ids keep the MIRTA spelling (fort-cavazos-usa = Fort Hood)
                     "status": "act|semi|care",           // closed (clsd) and excess (excs) sites are left out
                     "tier": "major|base|site",            // rules.tier: by boundary area / component, never headcount
                     "curated": false,                     // true: a flagship base made 'major' by the published list
                     "area_km2": 628.4 | null,             // null: MIRTA has no boundary for the site (incl. folded parts)
                     "parts": ["NNSY St Helena", …],       // optional: small parcels folded into this installation
                     "components": ["air_force", "marines"],   // optional: when the folded parts span components
                     "cells": [..] | null,                 // hexes whose centre the boundary covers (boundaries >= 200 km²)
                     "x": …, "y": …, "cell": …, "county": "37051" | null, "cbsa": "22180" | null,
                     "state": "NC",                        // where the point lies (county, else hex owner)
                     "state_filed": "NC"}],                // the state MIRTA files it under (UTTR: NV)
                                                           // sorted major → base → site, then by area
  "ranges": [{"id": "nevada-test-and-training-range-usaf", "name": "Nevada Test and Training Range",
              "component": "air_force", "area_km2": 11702.8, "cells": [..],   // never empty (see rules.ranges)
              "state": "NV",                  // its installation's point state when mapped (Fort Bliss: TX), else hex_state
              "hex_state": "NV",              // the state holding most of its hexes (Fort Bliss: NM)
              "installation": "…" | null, "name_mirta": "…",   // name_mirta optional, as for installations
              "components": ["air_force", "marines"]}],   // optional; the 30 largest boundaries: restricted ground
  "states": {"NC": {                                       // postal abbr; 50 states, DC and PR (no data → null)
    "personnel": {"active": {"army": …, "navy": …, "marines": …, "air_force": …, "space_force": …, "coast_guard": …, "total": …},
                  "guard_reserve": {"army_guard": …, "army_reserve": …, "navy_reserve": …, "marine_reserve": …,
                                    "air_guard": …, "air_force_reserve": …, "coast_guard_reserve": …, "total": …},
                  "civilian": {"army": …, "navy": …, "marines": …, "air_force": …, "defense_wide": …, "total": …},
                  "total": …} | null,                     // DMDC, by duty state
    "spending": {"total": 1.2e10, "contracts": …, "grants": …, "payroll": …,          // OLDCC, US dollars
                 "payroll_parts": {"civilian": …, "active_duty": …, "guard_reserve": …},
                 "pct_gdp": 0.021, "per_resident": 1150, "personnel": …,              // OLDCC's own personnel count
                 "top_counties": [{"name": "Onslow", "county": "37133" | null, "contracts": …}],   // top 10, OLDCC names
                 "top_vendors": [{"name": "Austal", "contracts": …}]} | null}},       // top 5 contractors
  "national": {"personnel": {…same shape…}, "personnel_scope": "50 states, DC and US territories …",
               "spending": {"total": …, "contracts": …, "grants": …, "payroll": …, "pct_gdp": …, "per_resident": …,
                            "scope": "50 states and DC"},
               "veterans": 16900000, "armed_forces_resident": 1100000, "acs_scope": "…"},   // ACS 5-year, 50 states + DC
  "cities": {"22180": {"tier": "garrison|fortress", "armed_forces": 36721, "share": 0.1212, "naval": false,
                       "installations": ["fort-bragg-usa"],   // up to 8 ids, largest first
                       "installation_count": 1}}             // only cities that pass the Encampment rule
}
```

* Tiers: `major` = active-duty (or other DoD) boundary ≥ 100 km², or one of the curated `flagships` (large bases on
  small land: Naval Station Norfolk, Naval Base San Diego, Wright-Patterson …; `curated: true`). Guard and Reserve
  sites are never `major` (`base` from 10 km², else `site`). Other active-duty sites are `base` from 1 km², else `site`.
  Parcels under 1 km² sharing a hex and component with a larger installation are folded into the nearest one
  (`parts`); the two Barry M. Goldwater Range halves (Air Force, Marine Corps) are one installation and one range.
* Encampment (cities): (a) an active non-Guard installation of tier `major` or `base` in one of the metro's member
  counties, or a range covering one of its hexes, **and** (b) ACS armed forces (`B23025_006`, by residence, summed over
  member counties) ≥ 1% of the 16+ population, or ≥ 2,000 **and** ≥ 0.3%: `fortress` at ≥ 3%, else `garrison`.
  `naval` when the qualifying Navy and Marine installations outweigh the Army and Air Force ones, a `major` counting 4
  and a `base` 1 (so a cluster of small Navy parcels does not make Washington naval). New York and Detroit do not
  qualify; the smallest qualifying shares are about 0.3% (Tampa, Kansas City, Providence).
* Installation-level headcounts are not published; never invent them. Veterans and armed forces by county live in
  counties.json (`veterans`, `armed_forces`), not here.
* `top_counties[].county` is null where OLDCC's county name does not match one on the map (Connecticut: OLDCC uses the
  old counties, the map the 2022 planning regions; Alaska and Hawaii are not on the map). Contract dollars are by place
  of performance, not where bases are.
* Not on the map: sites outside the lower 48 and a few island sites with no US land hex within two rings (Key West,
  San Clemente and San Nicolas Islands).

### wonders.json (eager)

Built by `pipeline/build/wonders.py` from `nps_boundaries` (`sources/nps.py`), `nps_visits`, `ipeds`, `herd`
(`sources/nsf_herd.py`) and `nhl_landmarks` (`sources/nrhp_nhl.py`). About 20 kB, 52 wonders.

```jsonc
{
  "version": 1,
  "vintage": {"parks": "NPS recreation visits 2025", "boundaries": "…", "universities": "NSF HERD FY2025; IPEDS …",
              "landmarks": "NPS National Register GIS (NHL subset)"},
  "sources": ["nps_boundaries", "nps_visits", "ipeds", "herd", "nhl_landmarks"],
  "rules": [{"id": "national_park", "kind": "natural", "kinds": ["natural", "recreation", "coastal", "monument"],
             "year": 2025, "text": "The 15 lower-48 National Parks …"},
            {"id": "park_unit", "kind": "natural", "kinds": […same…], "year": 2025, "text": "The 5 most-visited other …"},
            {"id": "research_university", "kind": "university", "year": 2025, "text": "The 20 universities …"},
            {"id": "landmark", "kind": "landmark", "curated": true, "text": "Hand-picked by this project …"}],
  "national": {"park_visits": 323014305, "park_visits_year": 2025, "r1_universities": 187},
  "wonders": [{"id": "nps-GRSM", "name": "Great Smoky Mountains National Park", "short": "Great Smoky Mountains",
               "kind": "natural|recreation|coastal|monument|university|landmark",   // must be in its rule's `kinds`
               "rule": "national_park", "rank": 1,   // rank within its rule
               "metrics": {…},                    // see below; unknown values are null
               "x": …, "y": …, "cell": …, "cells": [..] | null,   // cells: hexes a big park covers (protected land)
               "county": "37173" | null, "cbsa": "…" | null, "state": "NC", "curated": false,
               "listed_as": "…",                  // landmarks only: the name in the NPS layer
               "state_note": "…"}]                // optional: why state/county differ from the publisher's (Statue of Liberty → NY)
}
```

* `metrics` by rule. Parks: `{visits, year, area_km2, unit_type}`; the merged National Mall (`nps-MALL`) adds
  `visits_of` (the memorial its `visits` come from), `memorials` ({code: visits}) and a `note`: never add the memorial
  counts together. Universities: `{rd_usd, federal_usd, year, enrollment, enrollment_year, r1, med_school,
  reported_as?}` (dollars; `enrollment` is IPEDS 12-month unduplicated headcount, which includes online students;
  `reported_as` names a combined HERD report matched to its lead campus, e.g. Texas A&M with its Health Science Center).
  Landmarks: NPS sites `{visits, year, unit_type}`, NHLs `{designated, nhl_ref, note?}` (`note` when a value the
  NHL layer leaves blank was filled in by hand: Wrigley Field's 2020 designation).
* Park `kind` follows the NPS unit type: National Recreation Areas → `recreation` (Golden Gate, Gateway, Lake Mead),
  seashores and lakeshores → `coastal` (Gulf Islands), memorials, historic sites and battlefields → `monument`, plus
  overrides for the National Mall and the Gateway Arch (a National Park, but a monument); everything else `natural`.
  `rule.kind` stays "natural" for old readers; `rule.kinds` lists what the rule allows. Parks of any of these kinds
  have `metrics.visits` and may have `cells` (protected land): readers should key on `rule` (national_park,
  park_unit), not `kind`, for visits and protected land.
* `rank` is 1-based within the wonder's rule; curated landmarks are ranked alphabetically (not by importance).
  Recreation visits are counted differently by unit type, so parks are ranked only within their rule (the rule text
  says so). Wonders are in rule order: national_park, park_unit, research_university, landmark.
* `state`/`county`: the publisher's filed state wins when the point lands across a border river on the 1:20M county
  outlines (Gateway Arch → St. Louis city). The curated landmarks never repeat a site a park rule already holds
  (Hoover Dam was dropped for Golden Spike because Lake Mead NRA is a park-unit wonder). Statue of Liberty: NPS files it under NJ,
  but Liberty Island is part of New York County, so `state` "NY", `county` "36061" with a `state_note`.

### disasters.json (lazy)

Built by `pipeline/build/disasters.py` from the sources `fema_declarations` (`pipeline/sources/openfema.py`) and
`noaa_billions` (`pipeline/sources/noaa_billion.py`). About 160 kB.

```jsonc
{
  "version": 1, "sources": ["fema_declarations", "noaa_billions"],
  "vintage": {"fema": "OpenFEMA declarations as of 2026-11-25", "noaa": "NOAA NCEI billion-dollar disasters 1980–2024 (final release)"},
  "fema": {
    "window": ["2000-01-01", "2026-11-25"], "as_of": "2026-11-25",     // as_of = the day the declarations were fetched
    "rule": "Distinct major-disaster (DR) declarations naming the county …",   // full text, quote it in the UI
    "types": [{"id": "hurricane", "name": "Hurricanes & tropical storms", "incident_types": ["Hurricane", "Tropical Storm", "Tropical Depression", "Typhoon"]},
              {"id": "flood", …}, {"id": "fire", …}, {"id": "severe_storm", …}, {"id": "winter", …},
              {"id": "other", "incident_types": []}],          // other = every FEMA incidentType not listed above
    "counties": {"columns": ["geoid", "total", "hurricane", "flood", "fire", "severe_storm", "winter", "other", "last_date"],
                 "rows": [["01001", 14, 3, 2, 0, 8, 1, 0, "2025-04-02"]]},   // world.json counties order; 0 = none declared; last_date null if none
    "states": {"TX": {"total": 120, "statewide": 3, "by_type": {"hurricane": 30, "...": 0}}},   // every DR disaster in the state (incl. AK, HI, territories)
    "recent_days": 365,
    "recent": [{"disaster": 4870, "type": "hurricane", "incident_type": "Hurricane", "title": "Severe Storms And Flooding",
                "date": "2026-10-02", "state": "FL", "counties": ["12086"], "statewide": false, "areas": 1}]
                // declared within recent_days of as_of, newest first; counties = map GEOIDs only (CT mapped to regions),
                // areas = FEMA's designated-county count (also counts areas off the map, e.g. Alaska or Puerto Rico)
  },
  "noaa": {
    "years": [1980, 2024], "final": true, "unit": "USD, CPI-adjusted", "rule": "…",
    "types": [{"id": "drought", "name": "Drought"}, {"id": "flooding"}, {"id": "freeze"}, {"id": "severe_storm"},
              {"id": "tropical_cyclone"}, {"id": "wildfire"}, {"id": "winter_storm"}],
    "states": {"TX": {"count": {"drought": 20, "...": 0}, "cost_usd": {"drought": 4.4e10, "...": 0}}},   // incl. AK, HI, PR, VI, GU
    "national": {"events": 403, "cost_usd": 2.92e12, "deaths": 16000,
                 "by_year": [{"year": 1980, "events": 3, "cost_usd": …}],      // from the national event list
                 "costliest": [{"name": "Hurricane Katrina (August 2005)", "type": "Tropical Cyclone", "begin": "2005-08-25",
                                "cost_usd": 2.0e11, "deaths": 1833}]}          // top 10 by CPI-adjusted cost
  }
}
```

NOAA events span many states: never add state costs together into a national figure (use `national`). The shared
helper `disasters.county_declarations(fema_interim, geoids)` gives the per-county counts used by the `disasters` lens,
the counties.json column and this file, so the three always agree.

## sources.json

A list of `{id, title, publisher, homepage, license, description, used_for, vintage, files: [{file, url, retrieved, sha256, bytes}]}`.
`files` lists only files the latest `process()` used (`_files`), or every manifest entry if the source didn't say. A file
saved by `download_prefix()` has a `partial` note in the manifest, and its `sha256`/`bytes` describe the saved part.

## Browser module boundaries (web/js)

* `world.js`: `prepareWorld(world, cities, extras) → w` with `w.grid`, `w.raw`, `w.stateColor[]`, `w.cityByCell: Map<cell, city>`;
  `applyLens(w, lens, band = null)` sets `w.colors`/`w.rgb`; exports `WATER = -1`, `FOREIGN = -2`.
* `camera.js`: `Camera` with `fit()`, `toScreen()`, `toWorld()`, `zoomAt()`, `panBy()`, `centerOn()`, `flyTo(x, y, scale, ms)`,
  `step(dt) → bool stillMoving`, `view()`.
* `render/*`: map drawing and banners. `main.js` owns input, state and wiring. `ui/*` owns DOM panels.
* The `state` object (owned by `main.js`, read by `render/*`): `cities`, `lens` (a lenses.json lens or null = terrain),
  `band` (`[t0, t1]` in normalised lens units 0..1, or null: cells outside are dimmed, see `applyLens`), `hoverCell`,
  `selectedCity` (a city object or null), `selectedState` (a state index, abbr, fips or `{index|abbr|fips}`, or null;
  resolved with `world.js` `stateIndex(w, ref)`), `showResources`.
* `render/snapshot.js`: `renderToCanvas(target, cam, w, state, nation, opts) → {cam, hits}` draws a full frame off-screen
  (share images, OG cards) without touching the on-screen cache. `target` is a canvas, OffscreenCanvas or 2D context;
  `opts`: `banners = true`, `overlay = true`, `dpr = 1`, `fit = "contain"|"cover"|"same"`, or an explicit `scale`, `x`, `y`.

## Browser extension API (window.__app; main.js "extension API", app/api.js)

Extensions live in `web/js/ext/<name>/index.js` and export `install(app)`; `ext/index.js` loads `cityView`, `advisors` and
`layers` (roads, rail, forts, ports, airports, wonders and trade routes). The API:

**Data.**
* `app.data.<name>`: the core files (`world`, `cities`, `states`, `nation`, `lenses`, `resources`, `sources`) are loaded
  before anything runs. Optional files: `undefined` until loaded, `null` when missing (404) or invalid.
* `app.loadData(name) → Promise<data | null>`: loads `data/<name>.json` once (cached promise; later calls return the same
  promise) and sets `app.data[name]`. Emits `"data"` `{name, data}` when it arrives. `infrastructure`, `military`,
  `wonders`, `trade` are requested automatically right after the first frame; `citizens`, `districts`, `disasters` (and
  `counties`) only when something calls `loadData`. `app.loadCounties()` = `app.loadData("counties")`.

**Static map layers** (art that belongs in the cached map, drawn once per cache render):

```js
const off = app.registerStaticLayer({
  id: "roads",                 // unique; registering the same id again replaces the layer
  z: 55,                       // where it draws among the built-in steps (app.layerZ / render/map.js Z)
  draw(ctx, vp, w, o) {},      // required. ctx starts in world km (saved/restored around the call)
  visible() { return on; },    // optional; false = not drawn, not hit-tested (part of the cache key)
  sig() { return "v1"; },      // optional; any string that changes when the art must re-render (cache key)
  minRpx: 6, maxRpx: Infinity, // optional zoom range in hex radius css px (drawn when minRpx <= Rpx < maxRpx)
  hit(xKm, yKm, Rpx) { return item | null; },   // optional hover / click test, pointer in world km
  tooltip(item) { return "<b>html</b>" | {text: "plain"} | null; },  // optional; a string is HTML: escape data yourself
  click(item, ev) { return true; },             // optional; true consumes the click (see below)
  warm(ctx, vp, w, o) {},      // optional; paint sprites for vp's zoom in idle time (stamps may land anywhere)
  snapshot: true,              // default true: drawn into share images too
});
off();   // or app.unregisterStaticLayer("roads" | layer)
```

* `o` = `{Rpx, s, dpr, lod, lens, selectedCity, showResources, snapshot, app, cells, range: {r0, r1, c0, c1},
  world(), screen(), toScreen(x, y) → [css px]}`. `cells` are the visible cell indices; `o.screen()` switches ctx to
  screen css px of the cache canvas (use `o.toScreen`), `o.world()` back. Use sprites (`render/art/sprites.js`
  getSprite/drawSprite) for anything richer than a few paths.
* Built-in z steps: `WATER 10`, `LAND 20` (land tiles), `GRID 30`, `GLYPHS 40` (terrain), `RIVERS_BORDERS 50`, `CITIES 60`
  (city tiles), `FOG 70` (edge mist), `RESOURCES 80` (screen-space icons), `LABELS 90` (state names). A layer with z
  between two steps draws after the lower one; equal to a step = right after it. Suggested slots: 45 terrain
  improvements, **55 roads and rail**, 58 restricted ground / protected land hatching, **65 sites** (ports, airports,
  forts, wonders, plaques), **85 trade routes** (above resources, under state names).
* The cache key includes every layer's id, `visible()` and `sig()`, so toggling or restyling re-renders the cache and
  nothing else does. Errors in `draw`/`hit`/`sig`/... are logged once per layer and the layer is skipped.
* **Performance**: nothing may animate continuously (an idle map draws no frames); keep each layer under ~3 ms per cache
  render at typical zooms (time it with `drawStatic(..., {layers: app.staticLayers(), timings: T})`: it reports
  `layer:<id>`); precompute geometry once (not per draw); cull to `vp`.
* `app.staticLayers()` lists the registered layers; `app.hitLayer(mx, my)` (screen css px) → `{layer: id, item} | null`.

**Hover and click.** The hover tooltip asks the layers (highest z first, only those drawn at the current zoom) after the
city banners: the first non-null `hit()` wins and its `tooltip(item)` is shown (the cell tooltip otherwise). The
`"hover"` event payload is `{cell, city, resource, x, y, layer, item}` (`layer` = id or null). A click builds
`ev = {cell, city, resource, state, x, y, pointerType, layer, item}`; outside a mode the layer's `click(item, ev)` goes
first (true consumes it), then the `"mapclick"` handlers, then the default (select city/state). While a mode is active
(City View, advisors) the `"mapclick"` handlers go first and the layer's `click` only after them.

**Map toggles.** `app.ui.addMapToggle({id, label, icon, get() → bool, set(on), title?, default?}) → remove()`: a switch
in the "Map" menu next to the Resources toggle in the lens dock (one button + a small menu, so it fits phones). `set` is
yours (flip the state your layer's `visible()` reads); main redraws. The hash key `layers` lists the switches that are on
(`#layers=roads,rail,military`, `layers=none`) and is written only while some switch differs from its default; switches
added after load are set from it, and ids whose extension has not loaded yet stay in the URL. `app.ui.mapToggles()` →
`[{id, label, on}]`. `app.ui.setMapToggle(id, on) → bool` switches one from code exactly as the menu would (redraw,
hash), e.g. an advisor's "show roads, rail and forts" button; false if no toggle has that id (yet).

**URL.** Core keys: `lens`, `city` (CBSA id), `state`, `at`, plus extension keys (`advisor`, `layers`, ...).
* `#state=` accepts a FIPS code (`48`, `6`), a postal code (`TX`, `tx`) or a state name; a link keeps the form it
  was opened with.
* `at=x,y,z`: `x`, `y` = the map-km point at the centre of the screen (rounded), and `z` = **log2(camera scale ÷
  home-fit scale)**, the zoom relative to the "whole country fits" view: `0` = home framing, `1` = twice as close,
  negative = zoomed out past it. It is relative so a link frames the same area on any screen size; it is *not* the
  absolute scale (css px per km) that `app.flyTo(x, y, scale)` and `camera.scale` use. Convert with
  `scale = fitScale × 2^z`. `at` is written only once the user (or an extension) has moved the camera.
* When the hash is written: during a fly-to the link names the **destination** right away (within one 350 ms debounce
  of the flight starting); after a pan or wheel zoom it catches up 350 ms after the camera settles; `app.setMode`
  writes it on the next task. Lens, selection and mode changes push a history entry (Back undoes them); camera moves
  replace the current one. `app.hash.flush()` writes immediately (Share calls it before copying).

**Optional state and debug handles** (not data contracts; don't rely on them from other extensions without asking):
* `state.cityBadges`: an optional `Map<city id, {label, color: "#rrggbb"}>` that `render/banners.js` reads to draw a
  city-type tab on banners that show their yield row. Filled by `ext/cityView` from districts.json; absent = no tabs.
* `app.cityView.model`: read-only getter on the City View's current model (debugging).
* `app.mapArt = {model, on, layers}`: added by `ext/layers` for debugging. `model` holds `installations`, `ports`,
  `airports`, `wonders`, each item `{data (the json row), cell, x, y}`. The layers' hit items have the shape
  `{kind: "fort"|"range"|"port"|"airport"|"wonder"|"route", data}` (route items: `data.route` with `a`/`b`); the
  advisors rely on that shape for map-to-dashboard links, so keep it.

**Who reads which fields.** The advisors read every counties.json column after `cell`, military.json `states`, districts.json
`cities` and `counties`, and citizens.json `cities`; the City View reads citizens.json, districts.json, military.json
`cities`, trade.json zones and infrastructure.json `cbsa`. Update `web/js/ext/advisors` and `web/js/ext/cityView`
when renaming a field in those files.

**Lenses.** Legend ticks print numbers only (plus short units: %, $, min, /km²); a longer `unit` is printed once under
the ticks, so keep `unit` a plain phrase ("adherents per 100 residents"), not part of the number. `lens.note` is shown in the legend; `format: "category"` lenses get a swatch legend (see lenses.json).


## Spain: infrastructure.json, resources.json, wonders.json (F3)

Same shapes as the US sections above, with these changes (built by `pipeline/build/infrastructure.py`,
`resources.py`, `wonders.py`; checked by `check.py` `check_map_layers`):

* **infrastructure.json**: roads and rail from Natural Earth 1:10m v5.1.2 rasterised to hex links (class 0 = NE
  `expressway == 1`, 1 = other major or secondary highways at scalerank <= 7; rail tier 0 = scalerank <= 5, 1 = 6-7);
  links have no route name. Ports = Natural Earth ports in Spain (`scalerank`, `rank` by scalerank, `tons: null`).
  Airports = OurAirports large and medium airports with scheduled service, plus any Eurostat airport with passengers
  (`id` IATA, `icao`, `type`, `hub: null`, `passengers` = int > 0 or null, `passengers_year` set whenever `passengers`
  is; names in Spanish, `city` = the municipality that contains the point). Sorted by passengers descending, nulls
  last. Passengers = Eurostat `avia_paoa` (`PAS_CRD`, schedule and coverage TOTAL, from Aena data), arrivals plus
  departures, latest year with values for most airports (source `eurostat_airports`, `vintage.passengers`). Ports
  have no tonnage: it comes from Puertos del Estado, which this project does not use (`note`).
* **resources.json**: WRI Global Power Plant Database v1.3 (2021 edition), Spain, only `nuclear`, `hydro`, `gas`
  (every plant, no capacity cutoff; `value` = MW). Coal and oil are left out (most have closed since), wind and solar
  too (the 2021 inventory is very incomplete). Summaries are of the plants shown, not Spain's capacity.
* **wonders.json** (shown as "Patrimonio y parques"): Wikidata (CC0). Rule `patrimonio_mundial`: one entry per UNESCO
  id (`unesco`, `qid`, `serial` for serial sites drawn at one representative point); rule `parque_nacional`: the 16
  national parks. `metrics` is empty (no open visitor figures). Sites with no Spanish land cell within 2 hexes are left
  out and counted in the build log.
* Every file has `attribution` [{data, source, license}].

## Live layers (trains and flights)

Two optional map layers ("Trenes en directo", "Vuelos en directo", off by default; `web/js/ext/live/`). The feeds have
no CORS headers, so a Cloudflare Worker relays them. The relay URL is `LIVE_URL` in `web/js/ext/live/config.js`;
`localStorage["live_url"]` overrides it (tests). The page polls `/trains` every 20 s and `/flights` every 30 s only
while the layer is on and the tab is visible, one request at a time, and keeps the last data on error.

* `GET /trains` -> `{"updated": ISO string, "source": "Renfe (CC BY 4.0)", "stale": bool, "trains": [{"id": string,
  "net": "cercanias"|"ld", "lat": number, "lon": number, "trip": string|null, "label": string|null,
  "delay": seconds int|null, "status": string|null}]}`. Delay colour: <= 60 s green, 1-5 min amber, > 5 min red,
  `null` grey (never shown as 0).
* `GET /flights` -> `{"updated": ISO string, "source": "adsb.lol (ODbL 1.0)", "stale": bool, "flights": [{"id": callsign,
  "type": ICAO type|null, "lat": number, "lon": number, "alt_ft": int|null (null on the ground), "gs_kt": number|null,
  "track": degrees|null}]}`. Only airline callsigns (3 letters + digits); the page drops anything else and does not
  draw aircraft on the ground.
* Visible attribution: "Trenes: Renfe (CC BY 4.0) · Vuelos: adsb.lol (ODbL)".

### Weather (AEMET)

Optional layer "Tiempo hoy (AEMET)" (`web/js/ext/weather/`, off by default, `layers=weather` in the hash). The page
reads the same relay as the live layers (`liveUrl()`), polls `/weather` every 30 min and on enable (only while the layer is
on and the tab is visible, one request at a time) and keeps the last data on error ("sin datos de AEMET ahora").

* `GET /weather` -> `{"updated": ISO, "source": "AEMET", "stale": bool, "cities": {"<city id>": {"ine": "28079",
  "name": string, "elaborado": ISO|null, "days": [{"date": "YYYY-MM-DD", "sky": "11"|null, "sky_text": string|null,
  "tmax": int|null, "tmin": int|null, "rain_prob": int|null, "wind_dir": "NE"|null, "wind_kmh": int|null}]}},
  "warnings": [{"title": string, "level": "amarillo"|"naranja"|"rojo"|null, "area": string|null, "link": string|null}],
  "warnings_total": int}`. `days` holds today and tomorrow and may be empty; every field may be `null` and is never shown
  as 0. Warnings: at most 60.
* Sky codes -> icon: 11 sol, 12 poco nuboso, 13 intervalos nubosos, 14-17 nuboso/cubierto, 23-26 and 43-46 lluvia, 51-64
  tormenta, 33-36 and 71-74 nieve, 81-83 niebla/bruma/calima; a trailing `n` (night) is stripped; unknown -> text only.
* Chip under each city: icon + "tmax° / tmin°", de-cluttered by population, drawn under the banners. Hover shows the
  forecast for today and tomorrow plus "Predicción de AEMET elaborada el ..." (the `elaborado` time).
* Visible credit: "Tiempo: © AEMET" (links to the AEMET legal note) and "N avisos activos" (click opens the list; warning
  links open in a new tab with `rel=noopener`). The forecast text is shown as AEMET issued it.

### projection.json

Built by `pipeline/build/projection.py` (REQUIRES `_world`). Every constant `web/js/geo/projection.js` needs to
reproduce `MapProjection` (lon/lat -> map km, Canarias inset): `r_earth_km`, `min_x`, `max_y`, `margin` (the `_world`
projection), `main_albers` `[lat1, lat2, lat0, lon0]`, and `insets` `[{name, box [lon0, lat0, lon1, lat1],
albers [lat1, lat2, lat0, lon0], frame [x0, y0, x1, y1] (main-Albers km, y up), tx, ty}]`. JS: `createProjection(doc)`
returns `{project(lon, lat) -> [x, y], hidden(lon, lat) -> bool}`; `hidden` is true for a mainland point that falls under
an inset frame and for an inset-region point outside its frame. `tests/test_projection_js.py` compares both sides
(max error 0.01 km).

## Spain: housing, migration and safety lenses; transparency files

**New lens ids** (`lenses.json`, groups `housing` (Vivienda), `people`, `safety` (Seguridad); built by `lenses.py`; each
lens is a ratio of weighted municipal sums per hex, null below COVERAGE_MIN = 0.9 of the hex population, never 0):
`non_primary_homes` (% of dwellings, Censo 2021), `tourist_homes` (% of dwellings, INE experimental, latest period
`tourist_period`), `tourist_beds` (per 100 inhabitants), `housing_density` (dwellings/km2), `immigration` (arrivals from
abroad per 1,000 inhabitants a year), `foreign_change` (foreign nationality 2021-2026), `born_abroad` (% of population),
`crime` (infracciones penales per 1,000, latest Balance closing) and `burglary` (burglaries in dwellings per 1,000). The
`foreign` lens now reads INE 65032. Crime and burglary only exist for the 427 municipalities Interior publishes, so only
hexes where those towns hold at least 90 % of the population have a value (137 of 1,949).
`counties.json` adds the columns `dwellings_total`, `non_primary`, `tourist`, `born_abroad`, `immigration`, `crime_rate`
(null = no data).

Every transparency file is built by `pipeline/build/transparency.py` and has `vintage`, `updated`, `note` and
`attribution` [{data, source, license}]. Only codes, public-body names and numbers (`check.privacy_violations` runs on
each file before it is written).

### safety.json

```jsonc
{ "years": ["2024", "2025"],
  "typologies": [{"key": "total", "label": "...", "additive": false}],   // 19 rows
  "national": {"population": 49618585, "population_year": 2026, "2025": {"total": 0, "theft": 0}},
  "ccaa": {"AN": {"name": "...", "population": 0, "2024": {}, "2025": {}}},
  "provinces": {"41": {"name": "...", "population": 0, "2024": {}, "2025": {}}},
  "municipalities": {"41091": {"name": "...", "population": 0, "2024": {}, "2025": {}}} }  // 427 towns
```

`total` already includes every other typology (`conventional` + `cybercrime`; the rest are parts of those), so consumers
read `total` and never sum the typologies. `population` is the Censo anual 2026, not the year of the facts. A missing
count is `null`, never 0. 2024 values come from the 2025 closing (which restates 2024).

### boja.json

`{"years", "sections": [{id, name}], "by_year_section": {year: {section_id: n}}, "by_organisation": [{name, counts:
{year: n}}]}`. Counts of dispositions only; no titles. Non-public issuers are grouped as "Otros emisores".

### contracts_junta.json

`{"years", "amount_basis", "year_meaning", "thresholds_eur": [15000, 40000], "provinces": {"41": {name, year: {n, amount,
single_bidder, bidders_known, under_15k, under_40k, band_15k, band_40k}}}, "unassigned": {sin_provincia|otros: {...}},
"organs": [{name, by_year}]}`. Amounts are award amounts without VAT. The single-bidder share uses `bidders_known` as denominator.
No winners and no titles are read.


## Census sections (city-scale maps)

Library `pipeline/sources/ine_sections.py` (not part of the national build; helpers `pipeline/core/shapefile.py`, `pipeline/core/utm.py`). Source: INE, "Seccionado" boundaries 2026 (ETRS89 / UTM 30N shapefile, read from the zip) and the per-section tables ADRH 30824 / 30829 / 30832 and annual Census 65032 / 65031. Reuse requires citing INE.

- `load_sections(cumuns, year=2026)` returns one dict per section: `{cusec, cudis, cumun, nmun, rings}`, `rings` = every part of the polygon as `[(lon, lat), ...]` (outer rings and holes as stored; even-odd point-in-polygon works).
- `load_section_stats(cumuns)` returns `{vintage, sections, districts, match}`. `sections[cusec]` has `pop`, `foreign`, `born_abroad` (Census 2026), and `income`, `adrh_pop`, `age`, `under18_pct`, `over65_pct`, `household_size`, `single_households_pct`, `poverty60_pct` (ADRH, latest year, Sexo Total). `districts[cudis]` has the ADRH fields. A missing value or statistical secrecy is `None`, never 0.
- Section codes change between years and there is no crosswalk: a 2026 section without a row in a table is `None`. `match[table]` = `{sections_in_map, with_value, rows_without_polygon, pop_share_matched}` (share of the 2026 census population living in sections that got a value).
- Results are cached per municipality in `data/interim/ine_sections/` (git-ignored); each table is streamed once for all pending municipalities. CLI: `python -m pipeline.sources.ine_sections stats <cumun> ...`.
- Only aggregates per section / district / municipality; nothing about persons.
- The `IneSections` source class is not auto-registered (the national `sources.json` would gain an entry); register by setting `info = INFO` on the class.

### PLACSP (interim only)

`data/interim/placsp.json` (source `placsp`, no builder yet): public procurement of town halls awarded in 2025, from the
PLACSP yearly ZIPs (perfiles del contratante and aggregated regional platforms, both without minor contracts), streamed
without extracting. `{"vintage": "2025", "downloaded", "municipalities": {ine: {tenders, lots, amount_eur,
lots_with_offers, lots_single_bid, lots_open, by_type: {works|services|supplies|concessions|other: {lots, amount_eur}},
top: [<=10 {title, cpv, amount_eur, date, procedure, offers, winner, winner_nif, link, body}]}}, "stats": {...}, "note"}`.
Town hall = DIR3 `L01` + INE code (5 digits) + 1 character. Awarded = TenderResultCode 2, 8 or 9 with AwardDate in 2025;
open = ProcedureCode 1 or 9. Amounts are without VAT. Only a winner with a valid legal-entity NIF (format and control
character) and no personal title in its name is published in `top`; every other winner is quarantined: it counts in the
totals and its name and id are never stored. Any builder must show only municipality totals plus `top`, and must pass
`check.privacy_violations`. `PLACSP_SAMPLE=N` processes every k-th member of each ZIP (a test run, not for publishing).

## City scopes (the same map at city scale)

`python -m pipeline city <scope id>|all` (`pipeline/build/city.py`, scopes defined as data in `pipeline/scopes.py`) writes
`web/data/city/<scope id>/{world,cities,nation,lenses,states,sources,projection}.json` and `web/data/city/index.json`. It is NOT
part of `pipeline build` / `all` (the module has no `REQUIRES` / `PRODUCES` / `build()`), so the national files never change.
The page opens a scope with `?scope=<id>`. Every file has the same contract as its national namesake; differences:

* **`index.json`**: `{"scopes": [{"id", "name", "kind": "municipality"|"urban_area", "city": "ES001F", "hex_km", "population", "title"}]}`.
* **Scopes**: `madrid` (municipality 28079, hex radius 0.3 km, states = 21 districts, CUDIS) and `madrid-auf` (urban area ES001F,
  about 240 municipalities, hex radius 1.2 km, states = municipalities). `counties` are census sections (CUSEC, 10 digits) in both.
* **`world.json`**: the national keys, plus `scope` = `{id, kind, name, title, hex_km, levels: {state: {one, many}, county: {one, many}},
  note, city, population (INE, sum of the sections), hex_population (sum of the hexes), sections, census_year, adrh_year}` and `pop`
  (people allocated to each hex, 2 decimals; `null` outside the scope). `insets` is `[]`, there is no Canarias frame. `owner`: index
  of the state (district or municipality) with most lattice points; `-1` water (only a lake hex outside the scope), `-2` land outside the
  scope (drawn as foreign land). `county` = the section with most lattice points in the hex. `muni_cell[k]` = the hex that holds most of
  section `k`'s allocated people (`-1` if none). `states` = `{fips: CUDIS|CUMUN, abbr, name}` sorted by code; `counties` =
  `{geoid: CUSEC, name: "<state name>, sección NNNNN", province: <state fips>}`. `elev` and `elev_max` are 0 and `relief` is 0 (flat)
  everywhere: there is no elevation source at this scale yet (said in `tables.notes`). `cover` and `pct` come from the hex's lattice
  points, including those just outside the scope.
* **Estimates**: a section's people are spread over its hexes in proportion to its built-up lattice points (ESA WorldCover class 50;
  all its points when it has fewer than 3). Nothing here is an INE count per hexagon. Conservation: the sum of `pop` equals the sum of
  the sections' census population (check fails above 0.1 %).
* **`lenses.json`**: ids `density`, `income`, `poverty`, `age`, `elderly`, `under18`, `household`, `single_households`, `foreign`,
  `born_abroad`, `forest`, `developed`; sources `ine_adrh`, `ine_census`, `worldcover`. An INE lens is `null` on a hex when the
  sections holding under 90 % of its allocated people lack the value, and on hexes without built-up land (no people). Hexes with no
  people therefore have no data for INE lenses (parks, farmland); `check` measures INE lenses against the populated land hexes.
* **`cities.json`** = banners: districts (scope `madrid`) or municipalities of 50,000 inhabitants or more (`madrid-auf`).
  `id` = CUDIS / CUMUN, `states` = `[index into world.states]`, `counties` = its CUSEC codes, `footprint` = its hexes, `cell` = the
  owned hex nearest to the population-weighted centre (unique). `ranks` = `{"population": rank}`; `peers` = `[]`. Fields of the
  national contract without a source here (`employed`, `jobs`, `yields`, `gdp`, `growth`, `pop_series`, ...) are `null`.
* **`nation.json`**: `nation.name` = the scope title, `population` (INE), `income_per_person`, `land`; `yields` is `[]` and `industries`
  `{}` (as in F0); the rest `null`. **`states.json`**: one entry per state in `world.states` order with `population` and
  `income_per_person`; the rest `null`. **`sources.json`**: only `ine_sections`, `ine_adrh`, `ine_census` and `worldcover`.
* **`projection.json`**: the national format with `main_albers = [lat0 - 0.5, lat0 + 0.5, lat0, lon0]` centred on the scope and
  `insets: []`; `web/js/geo/projection.js` works unchanged.
* **Land cover**: `pipeline/sources/worldcover.py` `read_window(bbox)` reads the ~74 m overview (level 3 of the COG pyramid) limited to
  the TIFF tiles that touch the bbox (HTTP Range, cached in `data/raw/worldcover/city/`). If that fails the build falls back to the
  smallest overview (~600 m) and `sources.json` says so.
* **Checks** (`pipeline/check.py`, only when `web/data/city/` exists): files and keys, array lengths = grid size, index ranges,
  population conservation, lens coverage (WARN below 60 %, FAIL below 30 %), files under 3 MB, and names that are plain place names.
