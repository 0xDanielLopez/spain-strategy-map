"""F2 economy: cities (INE functional urban areas, AUF), autonomous communities and the nation.

Everything is counted where people LIVE (Censo anual de población, INE; occupied residents by CNAE
section) except gold. Gold (GDP) is published by INE only for the nation, the CCAA and the provinces,
so a city's gold is an imputation: each province's GDP is split among ALL its municipalities by
occupied residents, and a city adds up its members. It is not a measured municipal GDP.

Pure helpers (no I/O) come first so the tests can feed them synthetic data; build() loads the
interims and writes cities.json, states.json, nation.json and the "_economy_stats" interim that
pipeline/check.py reads for the conservation checks. Formats: docs/DATA_CONTRACTS.md.
"""

from __future__ import annotations

import math
import unicodedata
from collections import defaultdict

from ..core.geo import MapProjection
from ..core.hexgrid import HexGrid
from ..core.store import load_interim, load_interim_payload, save_interim, write_web
from .world import ring_area_centroid

REQUIRES = ["_world", "gisco_lau", "ine", "auf", "ine_jobs", "ine_gdp"]
PRODUCES = ["cities.json", "states.json", "nation.json", "_economy_stats"]

SECTIONS = "ABCDEFGHIJKLMNOPQRSTU"
KEYS = [s.lower() for s in SECTIONS]
CAPITAL_MUNI = "28079"  # Madrid
PEERS = 5
FOOTPRINT_SHARE = 0.5
GROWTH_YEARS = [2021, 2026]
GDP_TOLERANCE = 1e-6

# Yield definitions: the web gets them as nation.json "yields". "industries" = section keys counted.
# The unit "usd" is the key the web switches on to format money (it prints euros).
YIELDS = [
    {
        "key": "food", "icon": "y-food", "emoji": "🌾", "label": "Comida", "color": "#7fbf3f", "unit": "workers",
        "industries": ["a"],
        "description": "Ocupados en agricultura, ganadería, silvicultura y pesca, contados donde viven "
        "(Censo anual de población 2024, INE).",
    },
    {
        "key": "production", "icon": "y-production", "emoji": "⚙️", "label": "Producción", "color": "#d9823b",
        "unit": "workers", "industries": ["b", "c", "d", "e", "f"],
        "description": "Ocupados en industrias extractivas, industria manufacturera, energía, agua y residuos, y "
        "construcción, contados donde viven (Censo anual de población 2024, INE). A diferencia del original, "
        "incluye energía, agua y residuos.",
    },
    {
        "key": "gold", "icon": "y-gold", "emoji": "💰", "label": "Oro", "color": "#f2c94c", "unit": "usd",
        "industries": [],
        "description": "Producto interior bruto anual en euros corrientes (INE, Contabilidad Regional de España). "
        "Para las comunidades y el país es el dato publicado. Para las ciudades es un PIB provincial imputado: "
        "el PIB de la provincia de cada municipio, repartido por ocupados residentes. No es un PIB municipal medido.",
    },
    {
        "key": "science", "icon": "y-science", "emoji": "🔬", "label": "Ciencia", "color": "#4fa3e0",
        "unit": "workers", "industries": ["j", "m"],
        "description": "Ocupados en información y comunicaciones y en actividades profesionales, científicas y "
        "técnicas, contados donde viven (Censo anual de población 2024, INE).",
    },
    {
        "key": "culture", "icon": "y-culture", "emoji": "🎭", "label": "Cultura", "color": "#b07ce0",
        "unit": "workers", "industries": ["r"],
        "description": "Ocupados en actividades artísticas, recreativas y de entretenimiento, contados donde viven "
        "(Censo anual de población 2024, INE).",
    },
]
RANK_KEYS = ["population", "gdp", "gdp_per_capita", "growth"] + [y["key"] for y in YIELDS]

ATTRIBUTION = [
    {"data": "población, ocupados, renta, PIB y áreas urbanas funcionales",
     "source": "INE: Censo anual de población, Atlas de distribución de renta de los hogares, Contabilidad Regional de España y Áreas urbanas funcionales",
     "license": "Reutilización con cita de la fuente (INE)."},
    {"data": "límites municipales",
     "source": "Eurostat GISCO, Unidades Administrativas Locales (LAU) 2024",
     "license": "© EuroGeographics para los límites administrativos. Solo uso no comercial, con este aviso visible; fuera de la licencia MIT."},
]


# ---------------------------------------------------------------- yields




# Short CNAE section names for panels (the official names are kept in nation.json "industries_full").
SHORT_SECTION = {
    "a": "Agricultura, ganadería y pesca", "b": "Industrias extractivas", "c": "Industria manufacturera",
    "d": "Energía eléctrica y gas", "e": "Agua, saneamiento y residuos", "f": "Construcción",
    "g": "Comercio y reparación de vehículos", "h": "Transporte y almacenamiento", "i": "Hostelería",
    "j": "Información y comunicaciones", "k": "Finanzas y seguros", "l": "Actividades inmobiliarias",
    "m": "Actividades profesionales y científicas", "n": "Actividades administrativas", "o": "Administración pública y defensa",
    "p": "Educación", "q": "Sanidad y servicios sociales", "r": "Artes y entretenimiento", "s": "Otros servicios",
    "t": "Hogares como empleadores", "u": "Organismos extraterritoriales",
}

def _fold(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch)).lower()


def display_name(literal: str) -> str:
    """INE AUF literal -> map name: "AUF de Coruña, A" -> "A Coruña", "AUF de Pamplona/Iruña" -> "Pamplona / Iruña"."""
    name = literal.removeprefix("AUF de ").strip()
    parts = []
    for part in name.split("/"):
        part = part.strip()
        if ", " in part:
            base, article = part.rsplit(", ", 1)
            if len(article) <= 3:
                part = f"{article} {base}"
        parts.append(part)
    return " / ".join(parts)


def named_core(literal: str, by_pop: list, muni: dict) -> str:
    """The member the INE names the area after (e.g. Oviedo, not the more populous Gijón); else the most populous."""
    want = {_fold(p) for p in display_name(literal).split(" / ")}
    for m in by_pop:
        names = {_fold(p) for p in display_name(muni[m]["name"]).split(" / ")}
        if want & names:
            return m
    return by_pop[0]

def _sum(sections: dict | None, keys) -> int:
    return sum((sections or {}).get(k.upper()) or 0 for k in keys)


def yields_of(sections: dict | None, sectors4: dict | None = None) -> dict:
    """food/production/science/culture for one record: CNAE sections when known, else the 4-sector split.

    A record with only `sectors4` (50-500 inhabitants) adds agricultura to food and industria + construccion
    to production; it has no science or culture figure, so it adds nothing there. gold is left to the caller."""
    s4 = sectors4 or {}
    out = {}
    for y in YIELDS:
        if y["key"] != "gold":
            out[y["key"]] = _sum(sections, y["industries"])
    if not sections and s4:
        out["food"] += s4.get("agricultura") or 0
        out["production"] += (s4.get("industria") or 0) + (s4.get("construccion") or 0)
    return out


def aggregate(codes, jobs_muni: dict) -> dict:
    """Employed, jobs by section, yields and coverage for a set of municipality codes.

    jobs[k] only sums members with CNAE sections; yields also use the sectors4 members. Members absent from
    ine_jobs count as 0 (reported in employed_members)."""
    codes = list(codes)
    total = len(codes)
    employed = with_sections = present = 0
    jobs = dict.fromkeys(KEYS, 0)
    yields = dict.fromkeys(("food", "production", "science", "culture"), 0)
    for c in codes:
        rec = jobs_muni.get(c)
        if rec is None:
            continue
        present += 1
        employed += rec["total"]
        if rec.get("sections"):
            with_sections += rec["total"]
            for k in KEYS:
                jobs[k] += rec["sections"].get(k.upper()) or 0
        for k, v in yields_of(rec.get("sections"), rec.get("sectors4")).items():
            yields[k] += v
    return {
        "employed": employed, "jobs": jobs, "yields": yields,
        "jobs_coverage": round(with_sections / employed, 4) if employed else None,
        "employed_members": [present, total],
    }


def region_record(rec: dict) -> dict:
    """employed, jobs (lowercase keys) and yields from an official ine_jobs.regions entry (sections by letter)."""
    jobs = {k: (rec["sections"] or {}).get(k.upper()) or 0 for k in KEYS}
    yields = yields_of({k.upper(): v for k, v in jobs.items()})
    return {"employed": rec["total"], "jobs": jobs, "yields": yields}


# ---------------------------------------------------------------- GDP


def impute_gdp(codes: list[str], pop: dict, jobs_muni: dict, gdp_prov: dict) -> tuple[dict, dict]:
    """Imputed GDP per municipality, in euros, plus per-province stats.

    E_m = occupied residents (ine_jobs total); for municipalities absent from ine_jobs,
    E_m = pop_m * (province occupied known / province population known) (national ratio if the province
    has none known). GDP_m = GDP_prov * E_m / sum of E over ALL the province's municipalities.
    Provinces without a published GDP get no entry. Asserts conservation per province."""
    by_prov = defaultdict(list)
    for c in codes:
        by_prov[c[:2]].append(c)
    known_pop = defaultdict(float)
    known_emp = defaultdict(float)
    for c in codes:
        rec = jobs_muni.get(c)
        if rec is not None:
            known_pop[c[:2]] += pop.get(c) or 0
            known_emp[c[:2]] += rec["total"]
    nat_ratio = sum(known_emp.values()) / sum(known_pop.values()) if sum(known_pop.values()) else 0.0
    gdp: dict[str, float] = {}
    stats = {}
    for p, members in by_prov.items():
        if p not in gdp_prov:
            continue
        ratio = known_emp[p] / known_pop[p] if known_pop[p] else nat_ratio
        e = {c: (jobs_muni[c]["total"] if c in jobs_muni else (pop.get(c) or 0) * ratio) for c in members}
        total_e = sum(e.values())
        if total_e <= 0:
            raise RuntimeError(f"province {p}: no occupied residents to split the GDP over")
        for c in members:
            gdp[c] = gdp_prov[p] * e[c] / total_e
        got = sum(gdp[c] for c in members)
        if abs(got - gdp_prov[p]) > GDP_TOLERANCE * gdp_prov[p]:
            raise RuntimeError(f"province {p}: imputed GDP {got} differs from published {gdp_prov[p]}")
        stats[p] = {"gdp": gdp_prov[p], "imputed": got, "municipalities": len(members)}
    return gdp, stats


# ---------------------------------------------------------------- footprints and cells


def footprints(muni_weights: list, owner: list[int], codes: list[str], pop: dict, city_of: dict) -> dict[str, set[int]]:
    """City id -> land cells where share = sum_members(pop_m * f_mh) / sum_all(pop_m * f_mh) >= 0.5."""
    out: dict[str, set[int]] = {}
    for cell, parts in enumerate(muni_weights):
        if not parts or owner[cell] < 0:
            continue
        total = 0.0
        per: dict[str, float] = defaultdict(float)
        for k, f in parts:
            w = (pop.get(codes[k]) or 0) * f
            total += w
            cid = city_of.get(codes[k])
            if cid is not None:
                per[cid] += w
        if total <= 0:
            continue
        for cid, w in per.items():
            if w / total >= FOOTPRINT_SHARE:
                out.setdefault(cid, set()).add(cell)
    return out


def ring_search(grid: HexGrid, start: int, max_rings: int):
    """Yield (ring, cell) for every cell within `max_rings` steps of `start`, nearest rings first."""
    seen = {start}
    frontier = [start]
    yield 0, start
    for ring in range(1, max_rings + 1):
        nxt = []
        for c in frontier:
            for n in grid.neighbours(c):
                if n not in seen:
                    seen.add(n)
                    nxt.append(n)
                    yield ring, n
        frontier = nxt


def nearest_land(grid: HexGrid, owner: list[int], cell: int, x: float, y: float, state: int, max_rings=8):
    """Nearest land cell to (x, y), preferring `state`: the first ring with land, plus one more."""
    found_ring = None
    best = None
    for ring, c in ring_search(grid, cell, max_rings):
        if found_ring is not None and ring > found_ring + 1:
            break
        if owner[c] < 0:
            continue
        found_ring = ring if found_ring is None else found_ring
        cx, cy = grid.center(*grid.col_row(c))
        score = (owner[c] != state, math.hypot(cx - x, cy - y))
        if best is None or score < best[0]:
            best = (score, c)
    return best[1] if best else -1


def free_cell(grid: HexGrid, owner, taken: set, cell: int, x: float, y: float, state: int, max_rings=2):
    """Nearest untaken land cell within `max_rings`, preferring `state`; None if there is none."""
    best = None
    for ring, c in ring_search(grid, cell, max_rings):
        if owner[c] < 0 or c in taken:
            continue
        cx, cy = grid.center(*grid.col_row(c))
        score = (owner[c] != state, math.hypot(cx - x, cy - y))
        if best is None or score < best[0]:
            best = (score, c)
    return best[1] if best else None


def assign_cells(grid: HexGrid, owner: list[int], cities: list[dict], states_of: dict) -> dict[str, list]:
    """Banner cell per city (cities sorted by population, bigger first): the core's hex, snapped to land,
    pulled back into the core's CCAA, and nudged to a free land cell (2 rings, then 6) when taken.
    Sets c["cell"]; states_of[id] = (core CCAA index, set of member CCAA indices). Returns report lists."""
    taken: set[int] = set()
    rep = {"snapped": [], "pulled": [], "moved": [], "shared": []}
    for c in cities:
        state, own = states_of[c["id"]]
        cell = c["cell"]
        if cell < 0 or owner[cell] < 0:
            cell = nearest_land(grid, owner, max(cell, 0), c["x"], c["y"], state)
            rep["snapped"].append(c["name"])
        elif owner[cell] not in own:
            alt = free_cell(grid, owner, taken, cell, c["x"], c["y"], state)
            if alt is not None and owner[alt] == state:
                cell = alt
                rep["pulled"].append(c["name"])
        if cell in taken:
            alt = free_cell(grid, owner, taken, cell, c["x"], c["y"], state) or free_cell(
                grid, owner, taken, cell, c["x"], c["y"], state, max_rings=6)
            if alt is None:
                rep["shared"].append(c["name"])
            else:
                cell = alt
                rep["moved"].append(c["name"])
        taken.add(cell)
        c["cell"] = cell
    return rep


# ---------------------------------------------------------------- ranks


def rank_value(row: dict, key: str):
    if key == "gdp_per_capita":
        return row["gdp"] / row["population"] if row.get("gdp") is not None and row.get("population") else None
    if key in ("population", "gdp", "growth"):
        return row.get(key)
    return row["yields"].get(key)


def add_ranks(rows: list[dict], skip: tuple = ()) -> None:
    """ranks: 1 = highest, null where the value is null; ties keep the incoming order (population order).
    `skip` keys get a null rank for every row."""
    for r in rows:
        r["ranks"] = {}
    for key in RANK_KEYS:
        have = [] if key in skip else [r for r in rows if rank_value(r, key) is not None]
        have.sort(key=lambda r: -rank_value(r, key))
        for i, r in enumerate(have, 1):
            r["ranks"][key] = i
        for r in rows:
            r["ranks"].setdefault(key, None)


def add_peers(cities: list[dict]) -> None:
    """peers: the PEERS other cities closest in population by ratio, nearest first."""
    for i, c in enumerate(cities):
        lp = math.log(c["population"])
        near = sorted((abs(math.log(o["population"]) - lp), j) for j, o in enumerate(cities) if j != i)
        c["peers"] = [cities[j]["id"] for _, j in near[:PEERS]]


# ---------------------------------------------------------------- shared numbers


def growth_of(codes, ine_m: dict) -> float | None:
    """sum pop 2026 / sum pop_2021 - 1 over the members that have both numbers."""
    a = b = 0
    for c in codes:
        r = ine_m.get(c)
        if r and r.get("pop") is not None and r.get("pop_2021"):
            a += r["pop"]
            b += r["pop_2021"]
    return round(a / b - 1, 4) if b else None


def income_of(codes, ine_m: dict) -> int | None:
    """Population-weighted ADRH income per person over the members that have a value."""
    num = den = 0.0
    for c in codes:
        r = ine_m.get(c)
        if r and r.get("income_pp") is not None and r.get("pop"):
            num += r["income_pp"] * r["pop"]
            den += r["pop"]
    return round(num / den) if den else None


def population_of(codes, ine_m: dict) -> int:
    return int(sum((ine_m.get(c) or {}).get("pop") or 0 for c in codes))


# ---------------------------------------------------------------- build


def core_xy(rings: list, proj: MapProjection) -> tuple[float, float]:
    """Map km of the centroid of the largest projected ring (inset-aware, as world.py projects rings)."""
    projected = [proj.project_ring(r) for r in rings]
    _, x, y = ring_area_centroid(max(projected, key=lambda r: ring_area_centroid(r)[0]))
    return x, y


def build() -> None:
    world = load_interim("_world")
    lau = load_interim("gisco_lau")
    ine_m = load_interim("ine")["municipalities"]
    auf = load_interim("auf")
    jobs_doc = load_interim("ine_jobs")
    gdp_doc = load_interim("ine_gdp")
    from ..sources._spain import CCAA

    proj = MapProjection(**world["projection"])
    grid = HexGrid(**world["grid"])
    owner = world["owner"]
    codes = world["counties"]
    index = {c: i for i, c in enumerate(codes)}
    muni = {m["code"]: m for m in lau["municipalities"]}
    ccaa_index = {c: i for i, c in enumerate(world["states"])}
    ccaa_meta = {c["code"]: c for c in CCAA}
    jobs_m = jobs_doc["municipalities"]
    year = gdp_doc["year"]
    pop = {c: (ine_m.get(c) or {}).get("pop") or 0 for c in codes}

    gdp_m, gdp_stats = impute_gdp(codes, pop, jobs_m, gdp_doc["provinces"])
    city_of = {m: a["id"] for a in auf["cities"] for m in a["members"]}
    feet = footprints(world["muni_weights"], owner, codes, pop, city_of)

    cities, states_of = [], {}
    missing_members = []
    for a in auf["cities"]:
        members = [m for m in a["members"] if m in index]
        missing_members += [m for m in a["members"] if m not in index]
        by_pop = sorted(members, key=lambda m: (-pop[m], m))
        name = display_name(a["literal"])
        core = named_core(a["literal"], by_pop, muni)
        x, y = core_xy(muni[core]["rings"], proj)
        agg = aggregate(members, jobs_m)
        gdp = round(sum(gdp_m.get(m, 0.0) for m in members))
        ccaa_order = []
        for m in by_pop:
            ab = ccaa_meta[muni[m]["ccaa"]]["iso"]
            if ab not in ccaa_order:
                ccaa_order.append(ab)
        cities.append({
            "id": a["id"], "name": name, "full": f"Área urbana funcional de {name}",
            "states": ccaa_order, "metro": True, "capital": CAPITAL_MUNI in members, "core": core,
            "x": round(x, 1), "y": round(y, 1), "cell": muni_cell(world, index[core]),
            "population": population_of(members, ine_m), "employed": agg["employed"],
            "employed_members": agg["employed_members"], "jobs_coverage": agg["jobs_coverage"],
            "yields": {"food": agg["yields"]["food"], "production": agg["yields"]["production"], "gold": gdp,
                       "science": agg["yields"]["science"], "culture": agg["yields"]["culture"]},
            "jobs": agg["jobs"],
            "income_per_person": income_of(members, ine_m), "median_income": None,
            "home_value": None, "median_rent": None, "rent_burden": None, "unemployment": None,
            "gdp": gdp, "gdp_year": year, "gdp_estimated": True, "gdp_by_industry": None,
            "growth": growth_of(members, ine_m), "growth_years": GROWTH_YEARS,
            "pop_series": None, "counties": sorted(members),
        })
        states_of[a["id"]] = (ccaa_index[muni[core]["ccaa"]], {ccaa_index[muni[m]["ccaa"]] for m in members})
    cities.sort(key=lambda c: -c["population"])
    rep = assign_cells(grid, owner, cities, states_of)
    for c in cities:
        cells = feet.get(c["id"], set()) | {c["cell"]}
        c["footprint"] = sorted(cells)
    add_ranks(cities, skip=("gdp_per_capita",))
    add_peers(cities)

    # States: each municipality counts in its own CCAA (never summed over hexes).
    regions = jobs_doc["regions"]
    members_of = defaultdict(list)
    for c in codes:
        members_of[muni[c]["ccaa"]].append(c)
    states, notes = [], []
    for s in world["states"]:
        meta = ccaa_meta[s]
        rec = regions["ccaa"].get(s)
        if rec and rec.get("sections"):
            econ, source = region_record(rec), "official"
        else:
            agg = aggregate(members_of[s], jobs_m)
            econ, source = {k: agg[k] for k in ("employed", "jobs", "yields")}, "municipal_sum"
            notes.append(f"{meta['iso']}: employed from municipal sums ({agg['employed_members'][0]}/{agg['employed_members'][1]} municipalities)")
        gdp = (gdp_doc["ccaa"] or {}).get(s)
        population = population_of(members_of[s], ine_m)
        states.append({
            "fips": s, "abbr": meta["iso"], "name": meta["name"], "population": population,
            "employed": econ["employed"], "jobs": econ["jobs"], "jobs_source": source,
            "yields": {"food": econ["yields"]["food"], "production": econ["yields"]["production"], "gold": gdp,
                       "science": econ["yields"]["science"], "culture": econ["yields"]["culture"]},
            "income_per_person": income_of(members_of[s], ine_m), "median_income": None,
            "home_value": None, "median_rent": None, "rent_burden": None, "unemployment": None,
            "gdp": gdp, "gdp_year": year, "gdp_estimated": False, "gdp_by_industry": None,
            "growth": growth_of(members_of[s], ine_m), "growth_years": GROWTH_YEARS, "label": None,
        })
    add_ranks(states)

    nat = region_record(regions["national"])
    nation = {
        "name": "España", "population": population_of(codes, ine_m), "employed": nat["employed"], "jobs": nat["jobs"],
        "yields": {"food": nat["yields"]["food"], "production": nat["yields"]["production"], "gold": gdp_doc["national"],
                   "science": nat["yields"]["science"], "culture": nat["yields"]["culture"]},
        "income_per_person": income_of(codes, ine_m), "median_income": None,
        "gdp": gdp_doc["national"], "gdp_year": year, "growth": growth_of(codes, ine_m), "growth_years": GROWTH_YEARS,
    }
    write_web("cities.json", cities)
    write_web("states.json", states)
    write_web("nation.json", {
        "vintage": "INE 2024-2026",
        "year": 2026, "gdp_vintage": gdp_doc.get("vintage") or f"INE, Contabilidad Regional de España {year}",
        "nation": nation, "yields": YIELDS,
        "industries": {k: SHORT_SECTION.get(k, jobs_doc["sections"][k.upper()]) for k in KEYS},
        "industries_full": {k: jobs_doc["sections"][k.upper()] for k in KEYS},
        "attribution": ATTRIBUTION,
    })
    save_interim("_economy_stats", {
        "provinces": gdp_stats, "national_gdp": gdp_doc["national"], "cities_gdp": sum(c["gdp"] for c in cities),
    })
    print(f"    {len(cities)} cities, {len(states)} CCAA; {len(gdp_stats)} provinces with imputed GDP (conserved to {GDP_TOLERANCE:g})")
    for label, items in (("cells snapped to land", rep["snapped"]), ("pulled into their CCAA", rep["pulled"]),
                         ("moved to a free cell", rep["moved"]), ("still sharing a cell", rep["shared"]),
                         ("AUF members not in the municipality list", missing_members), ("states", notes)):
        if items:
            print(f"    {len(items)} {label}: {', '.join(items[:8])}")
    short = [c["name"] for c in cities if c["employed_members"][0] < c["employed_members"][1]]
    if short:
        print(f"    {len(short)} cities with members absent from ine_jobs (counted 0): {', '.join(short[:8])}")


def muni_cell(world: dict, k: int) -> int:
    """Representative hex of municipality index k, as world.py picks it for world.json muni_cell: the hex whose
    county it is, else the hex holding most of it (-1 if none)."""
    for i, c in enumerate(world["county"]):
        if c == k:
            return i
    best, best_w = -1, 0.0
    for i, parts in enumerate(world["muni_weights"]):
        for m, f in parts:
            if m == k and f > best_w:
                best, best_w = i, f
    return best
