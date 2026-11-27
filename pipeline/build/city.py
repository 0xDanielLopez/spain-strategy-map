"""City scopes: the national map at city scale (web/data/city/<scope id>/*.json, web/data/city/index.json).

NOT a national builder: no REQUIRES / PRODUCES / build(), so `pipeline build` never runs it and the national files
stay as they are. Run it with `python -m pipeline city <scope id>|all`. Format: docs/DATA_CONTRACTS.md "City scopes".

Method: every census section (INE, 2026) is cut into a fine lattice of points (step = hex radius / 7). Each point
knows its hex, its section and its ESA WorldCover class (an overview of 37-80 m read with HTTP Range). The population of a
section goes to its hexes in proportion to its built-up points (class 50; all its points when it has fewer than 3).
Everything shown per hexagon is therefore an ESTIMATE, not an INE figure. Only aggregates per section, district and
municipality are used; nothing about persons.
"""

from __future__ import annotations

import re
import json
import math
import time
from collections import Counter, defaultdict

from ..core.geo import Albers, R_EARTH_KM, Shape, ShapeIndex
from ..core.hexgrid import SQRT3, HexGrid
from ..core.paths import WEB_DATA
from ..core.store import atomic_write_text
from ..scopes import LEVELS, SCOPES, district_abbr, district_name, short_label, expected_hexes, fix_name, municipalities, resolve_radius, sections_area_km2, target_hexes
from ..sources import ine_sections, worldcover
from .lenses import DOMAIN_NOTE, GROUPS, INE_LENSES, LAND_LENSES, NEW_LENSES, percentile_domain
from .world import COVER, COVER_NOTE, WATER_TABLE, GROUPS as COVER_GROUPS, IGNORED_CLASSES, PCT, URBAN_ID, URBAN_MIN_PCT

CITY_DIR = WEB_DATA / "city"
LATTICE_DIV = 7  # lattice step = hex radius / 7
MARGIN_HEXES, MIN_MARGIN_HEXES = 12, 6  # grid margin around the scope, in hex radii (reduced for big scopes)
MAX_CELLS = 20000
SEA_SHARE = 0.2  # share of no-data points (WorldCover has none over open sea) that makes a water hex sea, not lake
OUTSIDE_RINGS = [(0.0, 0.0)] + [(0.55 * math.cos(math.radians(60 * k)), 0.55 * math.sin(math.radians(60 * k))) for k in range(6)] \
    + [(0.95 * math.cos(math.radians(60 * k + 30)), 0.95 * math.sin(math.radians(60 * k + 30))) for k in range(6)]  # 13 samples per hex
COVERAGE_MIN = 0.90  # share of a hex's population that must sit in sections with the value
MIN_BUILT_POINTS = 3
WC_CODES = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100]
WC_INDEX = {c: i for i, c in enumerate(WC_CODES)}
NC = len(WC_CODES)
BUILT, WATER_CLASS = WC_INDEX[50], WC_INDEX[80]
WATER_NONE, WATER_OCEAN, WATER_COAST, WATER_LAKE = 0, 1, 2, 3  # as in the national water table
OWNER_WATER, OWNER_FOREIGN = -1, -2  # as in the national world.json
ESTIMATE = "Estimación: cada sección censal se reparte entre sus hexágonos según el suelo construido."
NOTE = "Los valores son estimaciones: cada sección censal se reparte entre sus hexágonos según el suelo construido."

ATTRIBUTION = [
    {"data": "secciones censales, distritos y municipios", "source": "INE, Cartografía digitalizada de secciones censales 2026 (seccionado)",
     "license": "Elaboración propia con datos extraídos del sitio web del INE: www.ine.es. El INE no participa, patrocina ni apoya esta reutilización."},
    {"data": "población, renta, edad, hogares, nacionalidad y lugar de nacimiento por sección",
     "source": "INE: Atlas de distribución de renta de los hogares y Censo anual de población",
     "license": "Elaboración propia con datos extraídos del sitio web del INE: www.ine.es. El INE no participa, patrocina ni apoya esta reutilización."},
    {"data": "viviendas turísticas y plazas por sección (estadística experimental)",
     "source": "INE: Viviendas turísticas, estadística experimental",
     "license": "CC BY 4.0. Fuente: INE, www.ine.es"},
    {"data": "cobertura del suelo, construido, arbolado",
     "source": "ESA WorldCover 10 m 2021 v200",
     "license": "CC BY 4.0. © ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium."},
]

# ---------------------------------------------------------------- geometry


def project_sections(sections: list[dict]):
    """Albers centred on the scope (parallels lat0 -/+ 0.5). Returns (albers, params, rings in Albers km (x right, y up))."""
    lons = [p[0] for s in sections for r in s["rings"] for p in r]
    lats = [p[1] for s in sections for r in s["rings"] for p in r]
    lon0, lat0 = round((min(lons) + max(lons)) / 2, 4), round((min(lats) + max(lats)) / 2, 4)
    params = [round(lat0 - 0.5, 4), round(lat0 + 0.5, 4), lat0, lon0]
    alb = Albers(*params)
    return alb, params, [[[alb(lon, lat) for lon, lat in ring] for ring in s["rings"]] for s in sections]


class Lattice:
    """Result of classifying every lattice point: per-hex class counts and votes, per (section, hex) point counts."""

    def __init__(self, grid: HexGrid, n_sections: int):
        self.grid = grid
        self.cls = [0] * (grid.size * NC)  # WorldCover class counts per hex (all points)
        self.points = [0] * grid.size  # all lattice points per hex
        self.inside = [0] * grid.size  # points inside a section and not water (land of the scope)
        self.state_votes: dict[int, Counter] = defaultdict(Counter)
        self.pairs: dict[tuple[int, int], list[int]] = {}  # (section, hex) -> [built-up points, points]
        self.section_points = [0] * n_sections


def classify(grid, mapped, section_state, cover, to_ll, step, bbox) -> Lattice:
    """Walk the lattice over `bbox` (map km). `mapped` = section rings in map km; cover.at(lon, lat) -> class code."""
    shapes = [Shape(r) for r in mapped]
    idx = ShapeIndex(shapes, cell_km=max(0.5, grid.radius * 3))
    lat = Lattice(grid, len(shapes))
    x0, y0, x1, y1 = bbox
    nx, ny = int((x1 - x0) / step) + 1, int((y1 - y0) / step) + 1
    cell_at, locate, at = grid.cell_at, idx.locate, cover.at
    cls, points, inside, pairs, votes = lat.cls, lat.points, lat.inside, lat.pairs, lat.state_votes
    for iy in range(ny):
        y = y0 + (iy + 0.5) * step
        for ix in range(nx):
            x = x0 + (ix + 0.5) * step
            h = cell_at(x, y)
            if h < 0:
                continue
            lon, la = to_ll(x, y)
            ci = WC_INDEX.get(at(lon, la), 0)
            cls[h * NC + ci] += 1
            points[h] += 1
            s = locate(x, y)
            if s >= 0:
                if ci != WATER_CLASS:
                    inside[h] += 1
                votes[h][section_state[s]] += 1
                p = pairs.get((s, h))
                if p is None:
                    p = pairs[(s, h)] = [0, 0]
                p[1] += 1
                p[0] += ci == BUILT
                lat.section_points[s] += 1
    for s, sh in enumerate(shapes):  # a section smaller than the lattice step still gets its centroid
        if lat.section_points[s]:
            continue
        pts = [p for r in sh.rings for p in r]
        x, y = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
        h = cell_at(x, y)
        if h < 0:
            continue
        lon, la = to_ll(x, y)
        ci = WC_INDEX.get(at(lon, la), 0)
        pairs[(s, h)] = [int(ci == BUILT), 1]
        votes[h][section_state[s]] += 1
        lat.section_points[s] = 1
    return lat


def pick_margin(width0: float, height0: float, r: float) -> int:
    """Margin in hex radii: MARGIN_HEXES, fewer for big scopes so the grid stays under MAX_CELLS (never below MIN_MARGIN_HEXES)."""
    cell = 1.5 * SQRT3 * r * r
    for m in range(MARGIN_HEXES, MIN_MARGIN_HEXES, -1):
        if (width0 + 2 * m * r) * (height0 + 2 * m * r) / cell <= MAX_CELLS:
            return m
    return MIN_MARGIN_HEXES


def sample_outside(lat: Lattice, cover, to_ll) -> None:
    """Classify the hexes the lattice walk did not reach (the outer margin): 13 WorldCover samples each."""
    g, r = lat.grid, lat.grid.radius
    at = cover.at
    for h in range(g.size):
        if lat.points[h]:
            continue
        cx, cy = g.center(*g.col_row(h))
        for dx, dy in OUTSIDE_RINGS:
            lon, la = to_ll(cx + dx * r, cy + dy * r)
            lat.cls[h * NC + WC_INDEX.get(at(lon, la), 0)] += 1
            lat.points[h] += 1


def allocation(pairs: dict, n_sections: int) -> list[list[tuple[int, float]]]:
    """Per section: [(hex, share)] summing to 1. Built-up points when the section has >= 3, else all its points."""
    by_sec: dict[int, list] = defaultdict(list)
    for (s, h), (b, n) in pairs.items():
        by_sec[s].append((h, b, n))
    out: list[list[tuple[int, float]]] = [[] for _ in range(n_sections)]
    for s, rows in by_sec.items():
        built = sum(b for _, b, _ in rows)
        use = (lambda r: r[1]) if built >= MIN_BUILT_POINTS else (lambda r: r[2])
        tot = sum(use(r) for r in rows)
        out[s] = [(h, use(r) / tot) for r in rows for h in [r[0]] if use(r) > 0]
    return out


WATER_SHARE = 0.4  # a dock 150 m wide crossing hexes of 150 m rarely fills half of any of them


def mostly_water(lat, h: int) -> bool:
    """A good part (WATER_SHARE) of the hex's WorldCover points are permanent water or have no data (open sea)."""
    return lat.points[h] > 0 and lat.cls[h * NC] + lat.cls[h * NC + WATER_CLASS] >= WATER_SHARE * lat.points[h]


def keep_water_dry(alloc: list[list[tuple[int, float]]], lat) -> list[list[tuple[int, float]]]:
    """Nobody lives in a hex that is mostly water when the section has drier hexes: its share goes to them.

    Without this a few built-up pixels on a quay give the hex people, it stays land and a river or dock that crosses
    the city disappears. A section with only wet hexes keeps them (its people must be somewhere).
    """
    out = []
    for rows in alloc:
        dry = [(h, w) for h, w in rows if not mostly_water(lat, h)]
        total = sum(w for _, w in dry)
        out.append([(h, w / total) for h, w in dry] if dry and len(dry) < len(rows) and total > 0 else rows)
    return out


# ---------------------------------------------------------------- lenses


def _frac(v):
    return None if v is None else v / 100.0


def _terms_income(s):
    return None if s["income"] is None or not s["adrh_pop"] else (s["adrh_pop"] * s["income"], s["adrh_pop"])


def _adrh(field, scale=1.0):
    def terms(s):
        if s[field] is None or not s["adrh_pop"]:
            return None
        return (s["adrh_pop"] * s[field] * scale, s["adrh_pop"])
    return terms


def _terms_household(s):  # average household size is weighted by households (people / size)
    if s["household_size"] in (None, 0) or not s["adrh_pop"]:
        return None
    hh = s["adrh_pop"] / s["household_size"]
    return (hh * s["household_size"], hh)


def _terms_single(s):  # share of households: weighted by households
    if s["single_households_pct"] is None or s["household_size"] in (None, 0) or not s["adrh_pop"]:
        return None
    hh = s["adrh_pop"] / s["household_size"]
    return (hh * s["single_households_pct"] / 100, hh)


def _census(field):
    def terms(s):
        return None if s["pop"] is None or s[field] is None or s["pop"] <= 0 else (s[field], s["pop"])
    return terms


def _terms_tourist_share(s):  # INE share of dwellings, weighted by residents (the section's dwelling count is not in the file)
    if s["tourist_pct"] is None or not s["pop"] or s["pop"] <= 0:
        return None
    return (s["pop"] * s["tourist_pct"] / 100, s["pop"])


def _terms_tourist_places(s):  # places per 100 residents
    if s["tourist_places"] is None or not s["pop"] or s["pop"] <= 0:
        return None
    return (s["tourist_places"] * 100, s["pop"])


MONTHS_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def period_es(period) -> str:
    """'2026M05' -> 'mayo de 2026'."""
    m = re.fullmatch(r"(\d{4})M(0[1-9]|1[0-2])", period or "")
    return f"{MONTHS_ES[int(m.group(2)) - 1]} de {m.group(1)}" if m else "?"


def lens_specs(vint: dict) -> list[tuple]:
    """(id, terms(section) -> (num, den) | None, meta) for the section lenses. Years come from the data."""
    adrh, cen = vint.get("30824") or "?", vint.get("65032") or "?"
    pick = lambda d, k: {kk: vv for kk, vv in d[k][1].items() if kk != "digits"}

    def meta(base, source, digits, description, **over):
        m = {**base, "source": source, "digits": digits, "description": f"{description} {ESTIMATE}"}
        m.update(over)
        return m

    inc = pick(INE_LENSES, "income")
    tour = period_es(vint.get("tourist"))
    tour_base = {**pick(NEW_LENSES, "tourist_homes"), "source": "ine_tourist"}
    tour_text = (f"Estadística experimental del INE, obtenida de anuncios de plataformas de alquiler turístico (periodo: {tour}). "
                 "No es un registro oficial de licencias.")
    return [
        ("income", _terms_income, meta(inc, "ine_adrh", 0, f"Renta neta media por persona de la sección censal (Atlas de distribución de renta de los hogares {adrh}, tabla 30824, INE), ponderada por habitantes.")),
        ("poverty", _adrh("poverty60_pct", 0.01), meta(pick(INE_LENSES, "poverty"), "ine_adrh", 4, f"Porcentaje de población con ingresos por unidad de consumo por debajo del 60 % de la mediana (Atlas de distribución de renta {vint.get('30829') or adrh}, tabla 30829, INE).", note="Las secciones con secreto estadístico quedan sin dato.")),
        ("age", _adrh("age"), meta(pick(INE_LENSES, "age"), "ine_adrh", 1, f"Edad media de la población (Atlas de distribución de renta de los hogares {vint.get('30832') or adrh}, tabla 30832, INE).")),
        ("elderly", _adrh("over65_pct", 0.01), meta(pick(INE_LENSES, "elderly"), "ine_adrh", 4, f"Porcentaje de población de 65 y más años (Atlas de distribución de renta {vint.get('30832') or adrh}, tabla 30832, INE).")),
        ("under18", _adrh("under18_pct", 0.01), meta(
            {**pick(INE_LENSES, "elderly"), "name": "Menores de 18 años", "emoji": "🧒"}, "ine_adrh", 4,
            f"Porcentaje de población menor de 18 años (Atlas de distribución de renta {vint.get('30832') or adrh}, tabla 30832, INE).")),
        ("household", _terms_household, meta(pick(INE_LENSES, "household"), "ine_adrh", 2, f"Personas por hogar (Atlas de distribución de renta {vint.get('30832') or adrh}, tabla 30832, INE). El promedio se pondera por hogares.")),
        ("single_households", _terms_single, meta(
            {**pick(INE_LENSES, "household"), "name": "Hogares unipersonales", "emoji": "🧍", "unit": "% de los hogares", "format": "pct"}, "ine_adrh", 4,
            f"Porcentaje de hogares con una sola persona (Atlas de distribución de renta {vint.get('30832') or adrh}, tabla 30832, INE).")),
        ("foreign", _census("foreign"), meta(pick(INE_LENSES, "foreign"), "ine_census", 4, f"Porcentaje de población sin nacionalidad española a 1 de enero de {cen} (Censo anual de población, tabla 65032, INE).")),
        ("tourist_share", _terms_tourist_share, meta(
            {**tour_base, "name": "Viviendas turísticas por sección"}, "ine_tourist", 4,
            f"Porcentaje de viviendas de la sección que son viviendas turísticas. {tour_text}",
            note="Las secciones sin viviendas turísticas valen 0; las que el INE protege por secreto estadístico o no incluye quedan sin dato. "
                 "El INE usa las secciones del censo de 2021, y el valor de cada hexágono pondera las secciones por sus habitantes.")),
        ("tourist_places", _terms_tourist_places, meta(
            {**tour_base, "name": "Plazas turísticas por habitante", "unit": "plazas por 100 hab.", "format": "float", "emoji": "🛏️"}, "ine_tourist", 2,
            f"Plazas en viviendas turísticas por cada 100 habitantes de la sección (plazas del INE entre población del Censo anual). {tour_text}",
            note="Las secciones sin viviendas turísticas valen 0; las que el INE protege por secreto estadístico o no incluye quedan sin dato. "
                 "Mezcla dos fechas: plazas del periodo indicado y población del Censo anual.")),
        ("born_abroad", _census("born_abroad"), meta(pick(NEW_LENSES, "born_abroad"), "ine_census", 4, f"Población nacida en el extranjero a 1 de enero de {vint.get('65031') or cen} (Censo anual de población, tabla 65031, INE).")),
    ]


def hex_value(parts, terms, sections_stats, pop_of, digits):
    """sum(w*num) / sum(w*den) over the sections with a value, or None if they hold < COVERAGE_MIN of the hex's people."""
    total = covered = num = den = 0.0
    for s, w in parts:
        a = w * (pop_of[s] or 0)
        total += a
        t = terms(sections_stats[s])
        if t is None:
            continue
        num += w * t[0]
        den += w * t[1]
        covered += a
    if total <= 0 or den <= 0 or covered < COVERAGE_MIN * total:
        return None
    v = num / den
    return int(round(v)) if digits == 0 else round(v, digits)


# ---------------------------------------------------------------- build


def _cover_table() -> list[dict]:
    return [{"id": 0, "key": "none", "name": "Ninguna", "rule": "Agua, tierra fuera del ámbito o sin píxeles de tierra de WorldCover."}] + [
        {"id": cid, "key": key, "name": name, "color": color, "worldcover": codes, "rule": rule} for cid, key, name, color, codes, rule in COVER
    ]


def sea_possible(scope: dict, half_diagonal_km: float, world: dict | None = None, cities: list | None = None) -> bool:
    """True when the national map has sea within reach of the scope's grid (its half diagonal plus one national hex).

    A water body that touches the edge of a city grid is taken as sea, which is right on the coast and wrong for a river
    crossing an inland city. The national map knows where the sea is; without it (or without the city) the old rule stays.
    """
    try:
        world = world or json.loads((WEB_DATA / "world.json").read_text())
        cities = cities if cities is not None else json.loads((WEB_DATA / "cities.json").read_text())
    except (OSError, ValueError):
        return True
    cities = cities.get("cities", []) if isinstance(cities, dict) else cities
    cell = next((c.get("cell") for c in cities if c.get("id") == scope.get("city")), None)
    if cell is None:
        return True
    g = HexGrid(world["grid"]["radius"], world["grid"]["cols"], world["grid"]["rows"])
    rings = math.ceil((half_diagonal_km + g.radius) / (SQRT3 * g.radius))
    seen, front = {cell}, [cell]
    for _ in range(rings + 1):
        if any(world["water"][h] in (WATER_OCEAN, WATER_COAST) for h in front):
            return True
        front = [j for h in front for j in g.neighbours(h) if j >= 0 and j not in seen and not seen.add(j)]
    return False


def build_scope(scope: dict, out_dir=None, write_index: bool = True) -> dict:
    """Build one scope and return its measurements. Writes web/data/city/<id>/*.json and (write_index) updates index.json.
    A scope with hex_km None gets its radius from the municipality's area and sections (scopes.radius_for)."""
    t0 = time.time()
    sid = scope["id"]
    out_dir = (out_dir or CITY_DIR) / sid
    codes = municipalities(scope)
    sections = ine_sections.load_sections(set(codes))
    stats = ine_sections.load_section_stats(set(codes))
    r = resolve_radius(scope, sections)
    scope = {**scope, "hex_km": r}
    sstats = [stats["sections"].get(s["cusec"]) or {f: None for f in ine_sections.SECTION_FIELDS} for s in sections]
    n_sec = len(sections)

    # states = districts or municipalities, sorted by code
    level = scope["state_level"]
    key = (lambda s: s["cudis"]) if level == "district" else (lambda s: s["cumun"])
    state_codes = sorted({key(s) for s in sections})
    state_ix = {c: i for i, c in enumerate(state_codes)}
    muni_name = {}
    for s in sections:
        muni_name.setdefault(s["cumun"], fix_name(s["nmun"]))
    state_name = [district_name(scope, c) if level == "district" else muni_name[c] for c in state_codes]
    section_state = [state_ix[key(s)] for s in sections]

    # projection and grid
    alb, params, rings = project_sections(sections)
    xs = [p[0] for s in rings for rg in s for p in rg]
    ys = [p[1] for s in rings for rg in s for p in rg]
    min_x, max_y = min(xs), max(ys)
    mh = pick_margin(max(xs) - min_x, max_y - min(ys), r)
    margin = mh * r
    width, height = max(xs) - min_x + 2 * margin, max_y - min(ys) + 2 * margin
    grid = HexGrid.covering(width, height, r)
    mapped = [[[(x - min_x + margin, max_y - y + margin) for x, y in rg] for rg in s] for s in rings]
    to_ll = lambda x, y: alb.inverse(x + min_x - margin, max_y + margin - y)
    lon_all = [p[0] for s in sections for rg in s["rings"] for p in rg]
    lat_all = [p[1] for s in sections for rg in s["rings"] for p in rg]
    pad_lat = (margin + r) / 111.2 + 0.01  # the whole grid (scope plus margin) is classified
    pad_lon = pad_lat / math.cos(math.radians(sum(lat_all) / len(lat_all)))
    fine = True
    try:
        cover = worldcover.read_window(min(lon_all) - pad_lon, min(lat_all) - pad_lat, max(lon_all) + pad_lon, max(lat_all) + pad_lat,
                                       max_pixel_m=overview_pixel_m(r), empty_ok=True)
    except Exception as exc:  # honest fallback: the ~600 m overview the national map uses
        print(f"    ! fine WorldCover overview not available ({exc}); using the smallest overview (~600 m)")
        cover, fine = worldcover.coarse_window(), False
    step = r / LATTICE_DIV
    bbox = (margin - r, margin - r, width - margin + r, height - margin + r)
    lat = classify(grid, mapped, section_state, cover, to_ll, step, bbox)
    sample_outside(lat, cover, to_ll)
    n = grid.size
    area = 1.5 * SQRT3 * r * r  # km2 of a hexagon

    # population weights (needed first: a hex with people stays land)
    alloc = keep_water_dry(allocation(lat.pairs, n_sec), lat)
    pop_of = [s["pop"] for s in sstats]
    hex_parts: dict[int, list] = defaultdict(list)
    for s, rows in enumerate(alloc):
        for h, w in rows:
            hex_parts[h].append((s, w))
    hex_pop = [0.0] * n
    for h, parts in hex_parts.items():
        hex_pop[h] = sum(w * (pop_of[s] or 0) for s, w in parts)

    # owner / county / water. owner: state by most points (-1 water, -2 foreign land); county: the dominant section AMONG the
    # sections of the owner; a hex mostly water (class 80 or no data) is water unless it has people.
    owner, county, water = [OWNER_FOREIGN] * n, [-1] * n, [WATER_NONE] * n
    sec_hex_pts: dict[int, Counter] = defaultdict(Counter)
    for (s, h), (_, k) in lat.pairs.items():
        sec_hex_pts[h][s] += k

    wet = lambda h: mostly_water(lat, h)

    for h in range(n):
        v = lat.state_votes.get(h)
        if v:
            owner[h] = max(sorted(v), key=lambda s_: v[s_])
            c = {s_: k for s_, k in sec_hex_pts[h].items() if section_state[s_] == owner[h]}
            county[h] = max(sorted(c), key=lambda s_: c[s_]) if c else -1
            if hex_pop[h] <= 0 and wet(h):
                owner[h], county[h], water[h] = OWNER_WATER, -1, WATER_LAKE
        elif wet(h):
            owner[h], water[h] = OWNER_WATER, WATER_LAKE
    # Sea = a connected water body that touches the edge of the grid or holds hexes with no-data points (WorldCover has none over
    # open sea and marks the coastal sea as class 80, so the class alone cannot tell sea from lake); the rest stay lakes.
    edge = lambda h: not 0 < grid.col_row(h)[0] < grid.cols - 1 or not 0 < grid.col_row(h)[1] < grid.rows - 1
    seen, sea = set(), set()
    coastal = sea_possible(scope, 0.5 * math.hypot(width, height))  # inland: a river that leaves the grid is not sea
    for h0 in range(n):
        if not coastal:
            break
        if not water[h0] or h0 in seen:
            continue
        comp, queue, is_sea = [h0], [h0], False
        seen.add(h0)
        while queue:
            h = queue.pop()
            is_sea = is_sea or edge(h) or not lat.points[h] or lat.cls[h * NC] >= SEA_SHARE * lat.points[h]
            for j in grid.neighbours(h):
                if j >= 0 and water[j] and j not in seen:
                    seen.add(j)
                    comp.append(j)
                    queue.append(j)
        if is_sea:
            sea.update(comp)
    for h in sea:
        water[h] = WATER_COAST if any(j >= 0 and owner[j] != OWNER_WATER for j in grid.neighbours(h)) else WATER_OCEAN
    land = [h for h in range(n) if owner[h] >= 0]
    foreign = [h for h in range(n) if owner[h] == OWNER_FOREIGN]

    # cover and pct (points of the whole hex, including those just outside the scope)
    cover_id, pct = [0] * n, {k: [0] * n for k in PCT}
    for h in land + foreign:
        counts = Counter({code: lat.cls[h * NC + i] for code, i in WC_INDEX.items()})
        valid = sum(v for code, v in counts.items() if code not in IGNORED_CLASSES)
        if not valid:
            continue
        if round(100 * counts[50] / valid) >= URBAN_MIN_PCT:
            cover_id[h] = URBAN_ID
        else:
            best, bn = 0, 0
            for codes_, cid in COVER_GROUPS.values():
                k_ = sum(counts[c] for c in codes_)
                if k_ > bn:
                    best, bn = cid, k_
            cover_id[h] = best
        for k, cs in PCT.items():
            pct[k][h] = round(100 * sum(counts[c] for c in cs) / valid)

    ine_pop = sum(p or 0 for p in pop_of)
    on_hexes = sum(hex_pop[h] for h in land)
    if abs(on_hexes - ine_pop) > 0.001 * ine_pop:
        raise RuntimeError(f"{sid}: population on hexes {on_hexes:,.0f} differs from the sections' {ine_pop:,.0f}")
    land_km2 = {h: area * lat.inside[h] / lat.points[h] for h in land if lat.points[h]}

    # lenses
    vint = stats["vintage"]
    census = vint.get("65032") or "2026"
    values: dict[str, list] = {}
    dens = [None] * n
    for h in land:
        parts = hex_parts.get(h, [])
        tot = sum(w * (pop_of[s] or 0) for s, w in parts)
        if tot > 0 and land_km2.get(h, 0) > 0:
            dens[h] = round(tot / land_km2[h], 1)
    values["density"] = dens
    specs = lens_specs(vint)
    for lid, terms, meta in specs:
        vals = [None] * n
        for h in land:
            if hex_parts.get(h):
                vals[h] = hex_value(hex_parts[h], terms, sstats, pop_of, meta["digits"])
        values[lid] = vals
    lenses = [{
        "id": "density", "group": "people", "name": "Densidad de población", "icon": "l-people", "emoji": "👥", "unit": "hab./km²",
        "format": "int", "scale": "log", "ramp": ["#1b1035", "#4b2377", "#9a3b8a", "#e0645e", "#f9b24a", "#fff3a8"],
        "higher_is": "neutral", "source": "ine_census", "values": dens,
        "note": "Población de cada sección repartida por suelo construido: no es un recuento por hexágono. Sin dato donde no hay suelo construido.",
        "description": f"Habitantes por km² de tierra (Censo anual de población, tabla 65032, INE, 1 de enero de {census}). {ESTIMATE}",
    }]
    for lid, _, meta in specs:
        meta = {k: v for k, v in meta.items() if k != "digits"}
        lenses.append({"id": lid, **meta, "values": values[lid]})
    for lid, (k, meta) in LAND_LENSES.items():
        if lid not in ("forest", "developed"):
            continue
        lenses.append({"id": lid, "group": "land", **meta, "unit": "% de la tierra", "format": "pct", "scale": "linear", "higher_is": "neutral",
                       "source": "worldcover", "values": [round(pct[k][h] / 100, 2) if owner[h] >= 0 and cover_id[h] else None for h in range(n)]})
    coverage = {}
    for lens in lenses:
        have = sum(1 for h in land if lens["values"][h] is not None)
        coverage[lens["id"]] = round(have / len(land), 3) if land else 0
        lens["domain"] = percentile_domain(lens["values"], lens["scale"] == "log")
        lens["description"] += DOMAIN_NOTE
        if have < 0.5 * len(land):
            lens["note"] = f"{lens.get('note', '')} Con dato: {have} de {len(land)} hexágonos.".strip()
    groups = [g for g in GROUPS if any(l["group"] == g["id"] for l in lenses)]
    lens_doc = {"vintage": f"INE: Censo anual de población {census}, Atlas de distribución de renta de los hogares {vint.get('30824') or '?'}, seccionado 2026",
                "attribution": ATTRIBUTION, "groups": groups, "lenses": lenses}

    # states, counties, banners
    sec_x = {}
    for s, rows in enumerate(alloc):
        if rows:
            on_land = [t for t in rows if owner[t[0]] >= 0]
            if on_land:
                sec_x[s] = max(on_land, key=lambda t: t[1])[0]
    muni_cell = [sec_x.get(s, -1) for s in range(n_sec)]
    st_pop = [0.0] * len(state_codes)
    st_inc = [[0.0, 0.0] for _ in state_codes]
    st_secs: list[list[int]] = [[] for _ in state_codes]
    for s in range(n_sec):
        i = section_state[s]
        st_secs[i].append(s)
        st_pop[i] += pop_of[s] or 0
        if sstats[s]["income"] is not None and sstats[s]["adrh_pop"]:
            st_inc[i][0] += sstats[s]["income"] * sstats[s]["adrh_pop"]
            st_inc[i][1] += sstats[s]["adrh_pop"]
    st_income = [round(a / b) if b else None for a, b in st_inc]
    st_cells: list[list[int]] = [[] for _ in state_codes]
    for h in land:
        st_cells[owner[h]].append(h)

    def land_share(cells):
        if not cells:
            return None
        return {"forest": round(sum(pct["forest"][h] for h in cells) / len(cells) / 100, 4),
                "crop": round(sum(pct["crop"][h] for h in cells) / len(cells) / 100, 4),
                "developed": round(sum(pct["developed"][h] for h in cells) / len(cells) / 100, 4)}

    def abbr(i):
        if level == "district":
            return district_abbr(scope, state_codes[i])
        return short_label(state_name[i])

    null_fields = {"employed": None, "jobs": None, "yields": None, "median_income": None, "home_value": None, "median_rent": None,
                   "rent_burden": None, "unemployment": None, "gdp": None, "gdp_year": None, "gdp_estimated": None,
                   "gdp_by_industry": None, "growth": None, "growth_years": None}
    states_doc = [{"fips": state_codes[i], "abbr": abbr(i), "name": state_name[i], "population": round(st_pop[i]),
                   "income_per_person": st_income[i], **null_fields, "jobs_source": None, "label": None, "land": land_share(st_cells[i]),
                   "ranks": None} for i in range(len(state_codes))]
    banner_states = range(len(state_codes))
    if "min_banner" in scope:
        banner_states = [i for i in banner_states if st_pop[i] >= scope["min_banner"]]
    banners, taken = [], set()
    for i in banner_states:
        cells = st_cells[i]
        if not cells:
            continue
        tp = sum(hex_pop[h] for h in cells) or float(len(cells))
        wt = (lambda h: hex_pop[h]) if sum(hex_pop[h] for h in cells) else (lambda h: 1.0)
        cx = sum(wt(h) * grid.center(*grid.col_row(h))[0] for h in cells) / tp
        cy = sum(wt(h) * grid.center(*grid.col_row(h))[1] for h in cells) / tp
        order = sorted(cells, key=lambda h: (grid.center(*grid.col_row(h))[0] - cx) ** 2 + (grid.center(*grid.col_row(h))[1] - cy) ** 2)
        cell = next((h for h in order if h not in taken), order[0])
        taken.add(cell)
        x, y = grid.center(*grid.col_row(cell))
        banners.append({
            "id": state_codes[i], "name": state_name[i], "full": f"Distrito {state_name[i]}" if level == "district" else f"Municipio de {state_name[i]}",
            "states": [i], "metro": False, "capital": False, "core": state_codes[i], "x": round(x, 1), "y": round(y, 1), "cell": cell,
            "population": round(st_pop[i]), "employed_members": None, "jobs_coverage": None, "income_per_person": st_income[i],
            **null_fields, "pop_series": None, "counties": [sections[s]["cusec"] for s in st_secs[i]],
            "land": land_share(cells), "footprint": sorted(cells), "ranks": None, "peers": [],
        })
    for rank, b in enumerate(sorted(banners, key=lambda b: -b["population"]), 1):
        b["ranks"] = {"population": rank}
    banners.sort(key=lambda b: -b["population"])

    scope_doc = {"id": sid, "kind": scope["kind"], "name": scope["name"], "title": scope["title"], "hex_km": r, "levels": LEVELS[level],
                 "note": NOTE, "city": scope["city"], "population": round(ine_pop), "hex_population": round(on_hexes),
                 "sections": n_sec, "census_year": census, "adrh_year": vint.get("30824"),
                 "adrh_match": (stats["match"].get(ine_sections.INCOME) or {}).get("pop_share_matched")}
    tables = {
        "water": [
            {"id": 0, "name": "Tierra", "rule": "Hexágono con puntos de sección censal, o de tierra de WorldCover fuera del ámbito (tierra de fuera, en tono apagado)."},
            {**WATER_TABLE[1], "rule": "Mar abierto: hexágono de agua sin vecinos de tierra, unido por agua a puntos sin dato de WorldCover (no hay dato sobre el mar abierto)."},
            {**WATER_TABLE[2], "rule": "Mar junto a un hexágono de tierra (propia o de fuera)."},
            {**WATER_TABLE[3], "rule": "Agua que no llega al mar: la mayoría de sus puntos son agua permanente (clase 80 de WorldCover)."}],
        "relief": [{"id": 0, "name": "Llano", "rule": "A esta escala no hay fuente de altitud: toda la tierra se dibuja llana."}],
        "cover": _cover_table(),
        "notes": {"water": "Un hexágono es agua cuando la mayoría de sus puntos de WorldCover son agua permanente o no tienen dato (mar abierto). Dentro del ámbito solo si no tiene población: el puerto o la costa se dibujan como mar, y un embalse con habitantes sigue siendo tierra.",
                  "relief": "No hay fuente de altitud a esta escala en esta versión piloto: altitud 0 y relieve llano en todos los hexágonos de tierra.",
                  "cover": COVER_NOTE},
    }
    world = {
        "version": 2, "country": scope["title"], "attribution": ATTRIBUTION, "grid": grid.to_dict(), "width": round(width, 1),
        "height": round(height, 1), "margin": round(margin, 1), "insets": [], "owner": owner, "county": county,
        "elev": [0] * n, "elev_max": [0] * n, "water": water, "relief": [0] * n, "cover": cover_id, "pct": pct,
        "pop": [round(hex_pop[h], 2) if owner[h] >= 0 else None for h in range(n)], "tables": tables,
        "states": [{"fips": state_codes[i], "abbr": abbr(i), "name": state_name[i]} for i in range(len(state_codes))],
        "counties": [{"geoid": s["cusec"], "name": f"{state_name[section_state[k]] if level == 'district' else muni_name[s['cumun']]}, sección {s['cusec'][5:]}",
                      "province": key(s)} for k, s in enumerate(sections)],
        "muni_cell": muni_cell, "forced": [], "rivers": [], "scope": scope_doc,
    }
    nation = {
        "vintage": f"INE: Censo anual de población {census}, Atlas de distribución de renta de los hogares {vint.get('30824') or '?'}", "year": int(census) if census.isdigit() else None,
        "gdp_vintage": None,
        "nation": {"name": scope["title"], "population": round(ine_pop), "employed": None, "jobs": None, "yields": None,
                   "income_per_person": round(sum(a for a, _ in st_inc) / sum(b for _, b in st_inc)) if sum(b for _, b in st_inc) else None,
                   "median_income": None, "gdp": None, "gdp_year": None, "growth": None, "growth_years": None, "land": land_share(land)},
        "yields": [], "industries": {}, "industries_full": {}, "attribution": ATTRIBUTION,
    }
    src = [
        {"id": "ine_sections", "title": "Seccionado censal 2026 (INE)", "publisher": "Instituto Nacional de Estadística (INE)",
         "homepage": "https://www.ine.es/ss/Satellite?L=es_ES&c=Page&cid=1259952026632&p=1254735110672&pagename=ProductosYServicios%2FPYSLayout",
         "license": "Reutilización permitida, también comercial, citando la fuente. Elaboración propia con datos extraídos del sitio web del INE: www.ine.es. El INE no participa, patrocina ni apoya esta reutilización.",
         "description": "Límites de las secciones censales a 1 de enero de 2026 (ETRS89, UTM 30N), con su distrito y municipio.",
         "used_for": ["Mapas de ciudad: secciones, distritos y municipios"], "vintage": "Seccionado 2026",
         "files": [{"file": "seccionado_2026.zip", "url": "https://www.ine.es/prodyser/cartografia/seccionado_2026.zip"}]},
        {"id": "ine_adrh", "title": "Atlas de distribución de renta de los hogares por sección censal (INE)", "publisher": "Instituto Nacional de Estadística (INE)",
         "homepage": "https://www.ine.es/dyngs/INEbase/es/operacion.htm?c=Estadistica_C&cid=1254736176807", "license": "Reutilización con cita de la fuente (INE).",
         "description": "Renta neta media por persona, población bajo el 60 % de la mediana, edad media, tamaño del hogar y hogares unipersonales por sección censal (tablas 30824, 30829 y 30832).",
         "used_for": ["Lentes de renta, pobreza, edad y hogares de los mapas de ciudad"], "vintage": f"ADRH {vint.get('30824') or '?'}",
         "files": [{"file": f"{t}.csv", "url": f"https://www.ine.es/jaxiT3/Tabla.htm?t={t}"} for t in ("30824", "30829", "30832")]},
        {"id": "ine_census", "title": "Censo anual de población por sección censal (INE)", "publisher": "Instituto Nacional de Estadística (INE)",
         "homepage": "https://www.ine.es/dyngs/INEbase/es/operacion.htm?c=Estadistica_C&cid=1254736177095", "license": "Reutilización con cita de la fuente (INE).",
         "description": "Población, nacionalidad y lugar de nacimiento por sección censal a 1 de enero (tablas 65032 y 65031). Solo agregados.",
         "used_for": ["Población repartida, densidad, extranjeros y nacidos fuera en los mapas de ciudad"], "vintage": f"Censo anual {census}",
         "files": [{"file": f"{t}.csv", "url": f"https://www.ine.es/jaxiT3/Tabla.htm?t={t}"} for t in ("65032", "65031")]},
        {"id": "ine_tourist", "title": "Viviendas turísticas por sección censal (INE, estadística experimental)", "publisher": "Instituto Nacional de Estadística (INE)",
         "homepage": "https://www.ine.es/experimental/viv_turistica/experimental_viv_turistica.htm",
         "license": "CC BY 4.0. Fuente: INE, www.ine.es. Estadística experimental; no es un registro oficial de licencias.",
         "description": "Viviendas turísticas, plazas y porcentaje sobre el total de viviendas por sección censal, obtenidos de anuncios de plataformas. Solo agregados por sección.",
         "used_for": ["Lentes de viviendas turísticas y plazas turísticas de los mapas de ciudad"], "vintage": f"Estadística experimental, {period_es(vint.get('tourist'))}",
         "files": [{"file": ine_sections.TOURIST_FILE, "url": ine_sections.TOURIST_URL}]},
        {**worldcover.WorldCover.info.to_dict(), "vintage": "ESA WorldCover v200 (2021)", "files": [],
         "description": (f"Clases de cobertura del suelo a 10 m. Los mapas de ciudad leen una vista general de ~{cover.pixel_m:.0f} m, solo las teselas TIFF que tocan el ámbito, "
                         "con peticiones HTTP por rangos." if fine else
                         "Clases de cobertura del suelo a 10 m. En esta versión se leyó la vista general más pequeña (~600 m): no se pudo leer la fina.")},
    ]
    projection = {"r_earth_km": R_EARTH_KM, "min_x": min_x, "max_y": max_y, "margin": margin, "main_albers": params, "insets": []}

    files = {"world.json": world, "cities.json": banners, "nation.json": nation, "lenses.json": lens_doc, "states.json": states_doc,
             "sources.json": src, "projection.json": projection}
    sizes = {}
    for name, doc in files.items():
        text = json.dumps(doc, separators=(",", ":"), allow_nan=False, ensure_ascii=False)
        atomic_write_text(out_dir / name, text)
        sizes[name] = len(text.encode("utf-8"))
    if write_index:
        update_index(scope, round(ine_pop), out_dir.parent)
    res = {"id": sid, "hex_km": r, "name": scope["name"], "kind": scope["kind"], "title": scope["title"], "city": scope["city"],
           "cells": grid.size, "adrh_match": scope_doc["adrh_match"], "grid": f"{grid.cols}x{grid.rows}", "land_hexes": len(land), "sections": n_sec, "population": round(ine_pop),
           "hex_population": round(on_hexes), "margin_hexes": mh, "water_cells": sum(1 for h in range(n) if owner[h] == OWNER_WATER),
           "sea_cells": len(sea), "foreign_cells": len(foreign), "sizes": sizes, "seconds": round(time.time() - t0, 1), "coverage": coverage,
           "match": stats["match"], "overview": f"{cover.pixel_m:.0f} m" + ("" if fine else " (fallback)"),
           "wc_tiff_tiles": cover.tiff_tiles, "wc_bytes": cover.bytes_read, "banners": len(banners)}
    return res


def overview_pixel_m(radius_km: float) -> float:
    """Coarsest WorldCover pixel (m) allowed for a hex radius: radius / 3, never coarser than the 80 m default."""
    return min(worldcover.MAX_PIXEL_M, radius_km * 1000 / 3)


def update_index(scope: dict, population: int, city_dir=None) -> None:
    """Add or replace one scope in index.json; the list is sorted by population (largest first), then id."""
    city_dir = city_dir or CITY_DIR
    path = city_dir / "index.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {"scopes": []}
    entry = {"id": scope["id"], "name": scope["name"], "kind": scope["kind"], "city": scope["city"], "hex_km": scope["hex_km"],
             "population": population, "title": scope["title"]}
    by_id = {e["id"]: e for e in doc.get("scopes", [])}
    by_id[scope["id"]] = entry
    entries = sorted(by_id.values(), key=lambda e: (-e["population"], e["id"]))
    atomic_write_text(path, json.dumps({"scopes": entries}, separators=(",", ":"), ensure_ascii=False))


def plan_rows(ids) -> list[dict]:
    """Radius and expected land hexes of the scopes without building them (needs the sections, cached per municipality)."""
    codes = {c for sid in ids for c in municipalities(SCOPES[sid])}
    ine_sections.load_sections(codes)
    rows = []
    for sid in ids:
        secs = ine_sections.load_sections(set(municipalities(SCOPES[sid])))
        area = sections_area_km2(secs)
        r = resolve_radius(SCOPES[sid], secs)
        rows.append({"id": sid, "sections": len(secs), "area_km2": round(area, 1), "hex_km": r,
                     "target_hexes": None if SCOPES[sid].get("hex_km") else target_hexes(len(secs)), "expected_hexes": expected_hexes(area, r)})
    return rows


def scope_line(res: dict) -> str:
    adrh = res.get("adrh_match")
    diff = res["hex_population"] / res["population"] - 1 if res["population"] else 0
    return (f"[city] {res['id']}: r={res['hex_km']} km cells={res['cells']} land={res['land_hexes']} sections={res['sections']} "
            f"pop={res['hex_population']:,}/{res['population']:,} ({diff:+.3%}) adrh={'n/a' if adrh is None else f'{adrh:.1%}'} {res['seconds']}s")


def _build_one(sid: str) -> dict:
    return build_scope(SCOPES[sid], write_index=False)


def build_all(ids=None, jobs: int = 1) -> list[dict]:
    """Build the scopes. Section geometry and statistics are loaded ONCE for every municipality of the requested
    scopes (one streaming pass over the big INE tables, cached per municipality); then each scope reads its cache.
    jobs > 1 builds scopes in parallel processes; index.json is written once at the end, by this process."""
    ids = list(ids or SCOPES)
    codes = {c for sid in ids for c in municipalities(SCOPES[sid])}
    t0 = time.time()
    ine_sections.load_sections(codes)
    ine_sections.load_section_stats(codes)
    print(f"[city] sections and statistics ready for {len(codes)} municipalities in {time.time() - t0:.0f}s", flush=True)
    out = []
    if jobs > 1 and len(ids) > 1:
        import multiprocessing

        with multiprocessing.get_context("fork").Pool(min(jobs, len(ids))) as pool:
            for res in pool.imap_unordered(_build_one, ids):
                print(scope_line(res), flush=True)
                out.append(res)
    else:
        for sid in ids:
            out.append(_build_one(sid))
            print(scope_line(out[-1]), flush=True)
    for res in out:
        update_index({**SCOPES[res["id"]], "hex_km": res["hex_km"]}, res["population"])
    return out
