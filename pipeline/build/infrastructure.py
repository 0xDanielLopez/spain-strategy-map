"""Tile improvements: roads and railroads rasterised onto hex links, plus ports and airports.

Lines are never shipped as polylines. Each Natural Earth 1:10m line is sampled every SAMPLE_KM along its length,
each sample is mapped to its hex, repeats in a row are dropped, a cell whose neighbours on the line already touch is
dropped (the line only clipped its corner), and every step between two cells becomes a link between neighbouring
cells (a step that skips cells is filled with a hex line walk). The browser draws a link as a road or rail segment
from hex centre to hex centre.

Every point is projected with MapProjection (Canary Islands in their inset). A line is split wherever its region
changes and a sample that lands under (or outside) an inset frame is dropped, so no link crosses a frame.

Roads: class 0 "Autopista o autovía" = Natural Earth expressway flag; class 1 "Carretera principal" = any other
Major or Secondary Highway at scale rank <= MAJOR_MAX_SCALERANK. Rail: tier 0 at scale rank <= RAIL_MAIN_SCALERANK,
tier 1 up to RAIL_MAX_SCALERANK. A link needs one end on Spanish land (owner >= 0) and none on foreign land.

Ports: Natural Earth 1:10m ports inside Spain. Airports: OurAirports, large and medium with scheduled service.
No traffic figures are shipped (tons and passengers are null): those come from sources this project does not use.
A site's `cell` is the Spanish land cell at its point, or the nearest one up to SITE_RINGS hexes away.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from ..core.geo import MapProjection, Shape, ShapeIndex
from ..core.hexgrid import HexGrid
from ..core.paths import WEB_DATA
from ..core.store import load_interim, load_interim_payload, write_web

REQUIRES = ["_world", "natural_earth_infra", "ourairports", "natural_earth", "gisco_lau", "cities.json"]
PRODUCES = ["infrastructure.json"]

SAMPLE_KM = 4.0
MAJOR_MAX_SCALERANK = 7
MAJOR_TYPES = {"Major Highway", "Secondary Highway"}
RAIL_MAX_SCALERANK = 7
RAIL_MAIN_SCALERANK = 5
SITE_RINGS = 2
NOT_SPAIN_PORTS = {"Gibraltar"}  # a British territory whose hex the map gives to La Línea
ROAD_CLASSES = [{"id": "motorway", "name": "Autopista o autovía"}, {"id": "main", "name": "Carretera principal"}]
RAIL_TIERS = [{"id": "main", "name": "Línea principal"}, {"id": "secondary", "name": "Línea secundaria"}]

VINTAGE_NOTE = "Natural Earth v5.1.2 (1:10m)"
NOTE = ("Sin cifras de tráfico: los datos de pasajeros y mercancías vienen de Aena y Puertos del Estado, "
        "que este proyecto no usa.")
RULES = {
    "roads": "Red principal esquemática de Natural Earth 1:10m, muestreada cada 4 km y ajustada a enlaces entre centros "
             "de hexágono. Es arte de mapa, no estadística. Clase 0, autopista o autovía: las vías que Natural Earth "
             "marca como autopista o autovía. Clase 1, carretera principal: el resto de carreteras principales y "
             f"secundarias con rango de escala {MAJOR_MAX_SCALERANK} o menor, donde ninguna autopista ya une los "
             "mismos dos hexágonos.",
    "rail": f"Red ferroviaria esquemática de Natural Earth 1:10m con rango de escala {RAIL_MAX_SCALERANK} o menor, "
            f"muestreada cada 4 km y ajustada a enlaces entre centros de hexágono. Línea principal: rango "
            f"{RAIL_MAIN_SCALERANK} o menor. Es arte de mapa, no estadística: no incluye tráfico ni titularidad, y "
            "se recortan las líneas fuera de España.",
    "ports": "Puertos de Natural Earth 1:10m dentro de España (incluidas Canarias, Baleares, Ceuta y Melilla). "
             "Se ordenan por rango de escala de Natural Earth (menor es más importante); no hay cifras de mercancías.",
    "airports": "Aeropuertos grandes y medianos de OurAirports con servicio regular. No hay cifras de pasajeros.",
}
ATTRIBUTION = [
    {"data": "carreteras, ferrocarriles y puertos", "source": "Natural Earth 1:10m v5.1.2", "license": "Dominio público"},
    {"data": "aeropuertos", "source": "OurAirports", "license": "Dominio público"},
]


# ------------------------------------------------------------------ hex helpers


def _axial(grid: HexGrid, cell: int) -> tuple[int, int]:
    col, row = grid.col_row(cell)
    return col - (row - (row & 1)) // 2, row


def _from_axial(grid: HexGrid, q: int, r: int) -> int:
    col = q + (r - (r & 1)) // 2
    if 0 <= col < grid.cols and 0 <= r < grid.rows:
        return grid.index(col, r)
    return -1


def hex_distance(grid: HexGrid, a: int, b: int) -> int:
    (q1, r1), (q2, r2) = _axial(grid, a), _axial(grid, b)
    return (abs(q1 - q2) + abs(r1 - r2) + abs((q1 + r1) - (q2 + r2))) // 2


def hex_walk(grid: HexGrid, a: int, b: int) -> list[int]:
    """Cells on the hex line from a to b, both included (cube lerp with a tiny nudge to break ties)."""
    n = hex_distance(grid, a, b)
    if n <= 1:
        return [a, b] if a != b else [a]
    (q1, r1), (q2, r2) = _axial(grid, a), _axial(grid, b)
    out = []
    for i in range(n + 1):
        t = i / n
        x = q1 + (q2 - q1) * t + 1e-6
        z = r1 + (r2 - r1) * t + 1e-6
        y = -x - z
        rx, ry, rz = round(x), round(y), round(z)
        dx, dy, dz = abs(rx - x), abs(ry - y), abs(rz - z)
        if dx > dy and dx > dz:
            rx = -ry - rz
        elif dy <= dz:
            rz = -rx - ry
        c = _from_axial(grid, rx, rz)
        if c >= 0 and (not out or out[-1] != c):
            out.append(c)
    return out


def sample_cells(grid: HexGrid, pts: list[tuple[float, float]], keep=None) -> list[list[int]]:
    """Runs of distinct consecutive cells along a projected line, sampled every SAMPLE_KM. `keep(x, y)` False
    breaks the run (the sample is dropped)."""
    runs, run = [], []

    def add(x, y):
        nonlocal run
        if keep is not None and not keep(x, y):
            if len(run) > 1:
                runs.append(run)
            run = []
            return
        c = grid.cell_at(x, y)
        if c < 0:
            return
        if not run or run[-1] != c:
            run.append(c)

    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        steps = max(1, math.ceil(math.hypot(x1 - x0, y1 - y0) / SAMPLE_KM))
        for i in range(steps):
            t = i / steps
            add(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
    if pts:
        add(*pts[-1])
    if len(run) > 1:
        runs.append(run)
    return runs


def straighten(grid: HexGrid, run: list[int]) -> list[int]:
    """Drop detour cells: where the cells before and after a cell are neighbours themselves, the line only clipped
    that cell's corner. Without this, a road running along a row boundary zigzags between two rows."""
    out = []
    for c in run:
        while len(out) >= 2 and c in grid.neighbours(out[-2]):
            out.pop()
        if not out or out[-1] != c:
            out.append(c)
    return out


def links_of(grid: HexGrid, run: list[int]) -> list[tuple[int, int]]:
    out = []
    run = straighten(grid, [c for path in ([run[0]], *(hex_walk(grid, a, b)[1:] for a, b in zip(run, run[1:])))
                            for c in path])
    for a, b in zip(run, run[1:]):
        path = hex_walk(grid, a, b)
        for u, v in zip(path, path[1:]):
            if u != v:
                out.append((u, v) if u < v else (v, u))
    return out


def link_ok(owner, a: int, b: int) -> bool:
    """One end on Spanish land and no end on foreign land."""
    return not (owner[a] == -2 or owner[b] == -2 or (owner[a] < 0 and owner[b] < 0))


# ------------------------------------------------------------------ roads and rail


def line_pieces(proj: MapProjection, line):
    """Split a lon/lat line wherever its region changes; project each piece in its own region. Yields
    (region, [(x, y), ...]). Pieces never join across regions, so nothing connects the main map to an inset."""
    piece, region = [], None
    for lon, lat in line:
        r = proj.region_of(lon, lat)
        if r != region and piece:
            yield region, piece
            piece = []
        region = r
        piece.append(proj(lon, lat, r))
    if len(piece) > 1:
        yield region, piece


def line_runs(grid, proj, line, extra_keep=None):
    """Cell runs of one lon/lat line: samples under another region's frame are dropped."""
    out = []
    for region, pts in line_pieces(proj, line):
        want = None if region == "main" else region

        def keep(x, y, want=want):
            return proj.frame_at(x, y) == want and (extra_keep is None or extra_keep(x, y))

        out += sample_cells(grid, pts, keep)
    return out


def road_class(f: dict) -> int | None:
    """0 motorway or dual carriageway, 1 main road, None not drawn."""
    if f["expressway"]:
        return 0
    sr = f["scalerank"] if f["scalerank"] is not None else 99
    return 1 if f["type"] in MAJOR_TYPES and sr <= MAJOR_MAX_SCALERANK else None


def build_roads(grid, proj, owner, features):
    cls_of = {}
    for f in features:
        cls = road_class(f)
        if cls is None:
            continue
        for line in f["lines"]:
            for run in line_runs(grid, proj, line):
                for a, b in links_of(grid, run):
                    if link_ok(owner, a, b):
                        cls_of[(a, b)] = min(cls, cls_of.get((a, b), 9))
    return [[a, b, c] for (a, b), c in sorted(cls_of.items())]


def rail_tier(f: dict) -> int | None:
    sr = f["scalerank"] if f["scalerank"] is not None else 99
    if sr > RAIL_MAX_SCALERANK:
        return None
    return 0 if sr <= RAIL_MAIN_SCALERANK else 1


def build_rail(grid, proj, owner, features, foreign_idx):
    tier_of = {}

    def not_foreign(x, y):
        return foreign_idx.locate(x, y) < 0

    for f in features:
        tier = rail_tier(f)
        if tier is None:
            continue
        for line in f["lines"]:
            for run in line_runs(grid, proj, line, not_foreign):
                for a, b in links_of(grid, run):
                    if link_ok(owner, a, b):
                        tier_of[(a, b)] = min(tier, tier_of.get((a, b), 9))
    return [[a, b, t] for (a, b), t in sorted(tier_of.items())]


def frame_crossings(links, grid, proj) -> int:
    """Links with exactly one end-cell centre inside an inset frame (must be 0)."""
    bad = 0
    for a, b, *_ in links:
        fa = proj.frame_at(*grid.center(*grid.col_row(a)))
        fb = proj.frame_at(*grid.center(*grid.col_row(b)))
        bad += fa != fb
    return bad


# ------------------------------------------------------------------ sites


class Locator:
    def __init__(self, world, grid, proj, munis, cities):
        self.grid, self.proj = grid, proj
        self.owner, self.county, self.geoids = world["owner"], world["county"], world["counties"]
        self.idx_of = {g: i for i, g in enumerate(self.geoids)}
        abbr_of = {fips: abbr for fips, abbr in zip(world["states"], world["state_abbrs"])}
        muni_state = {m["code"]: abbr_of.get(m["ccaa"]) for m in munis}
        self.muni_state = muni_state
        self.muni_codes = [m["code"] for m in munis]
        self.muni_idx = ShapeIndex([Shape([proj.project_ring(r) for r in m["rings"]]) for m in munis], cell_km=30)
        self.cbsa_of = {}
        for c in cities:
            for g in c["counties"]:
                self.cbsa_of.setdefault(g, c["id"])

    def land_cell(self, x, y, rings=SITE_RINGS, known_spanish=False) -> int:
        """Spanish land cell at the point, else the nearest within `rings` hexes; -1 when the nearest land is
        foreign or there is none. `known_spanish` (the source says the site is in Spain, e.g. an airport on the
        border) skips foreign cells instead of rejecting the site."""
        grid, owner = self.grid, self.owner
        cell = grid.cell_at(x, y)
        if cell < 0:
            return -1
        if owner[cell] >= 0:
            return cell
        if owner[cell] == -2 and not known_spanish:
            return -1
        seen, frontier = {cell}, [cell]
        for _ in range(rings):
            ring = list(dict.fromkeys(n for c in frontier for n in grid.neighbours(c) if n not in seen))
            seen.update(ring)
            land = [n for n in ring if owner[n] >= 0] if known_spanish else [n for n in ring if owner[n] != -1]
            if land:
                best = min(land, key=lambda n: math.dist(grid.center(*grid.col_row(n)), (x, y)))
                return best if owner[best] >= 0 else -1
            frontier = ring
        return -1

    def place(self, lon, lat, known_spanish=False) -> dict | None:
        if lon is None or lat is None or self.proj.hidden(lon, lat):  # e.g. Algeria, under the Canary inset frame
            return None
        x, y = self.proj(lon, lat)
        mi = self.muni_idx.locate(x, y)
        cell = self.land_cell(x, y, known_spanish=known_spanish)
        if cell < 0:
            return None
        if mi >= 0:
            code = self.muni_codes[mi]
        else:
            ci = self.county[cell]
            code = self.geoids[ci] if ci >= 0 else None
        return {"x": round(x, 1), "y": round(y, 1), "cell": cell, "county": code,
                "cbsa": self.cbsa_of.get(code) if code else None, "state": self.muni_state.get(code) if code else None}


# ------------------------------------------------------------------ Spanish names

# OurAirports names are in English ("Seville Airport"); the map shows the usual Spanish name. A name that starts with a
# person's name reads "Aeropuerto <name>", a place "Aeropuerto de <place>".
AIRPORT_NAME_OVERRIDES = {
    "Region of Murcia International Airport": "Aeropuerto Internacional de la Región de Murcia",
    "Seville Airport": "Aeropuerto de Sevilla",
    "F.G.L. Airport Granada-Jaén Airport": "Aeropuerto Federico García Lorca Granada-Jaén",
    "Pirineus - la Seu d'Urgel Airport": "Aeropuerto de Andorra-La Seu d'Urgell",
    "Santiago-Rosalía de Castro Airport": "Aeropuerto de Santiago-Rosalía de Castro",
}
PERSON_PREFIXES = ("Adolfo Suárez", "César Manrique", "Josep Tarradellas", "Seve Ballesteros")


def airport_name_es(name: str) -> str:
    if name in AIRPORT_NAME_OVERRIDES:
        return AIRPORT_NAME_OVERRIDES[name]
    base = name.removesuffix(" Airport").strip().replace("–", "-")
    return f"Aeropuerto {base}" if base.startswith(PERSON_PREFIXES) else f"Aeropuerto de {base}"


def _fold(s: str) -> str:
    import unicodedata
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch)).lower().strip()


def accent_lookup(municipalities: list[dict]) -> dict:
    """Folded name -> accented name, from municipality names ("Coruña, A" -> "A Coruña"; "Donostia / San Sebastián" ->
    both parts). Natural Earth port names come without accents ("Malaga")."""
    out = {}
    for m in municipalities:
        for part in m["name"].split("/"):
            part = part.strip()
            if ", " in part:
                base, art = part.rsplit(", ", 1)
                if len(art) <= 3:
                    part = f"{art} {base}"
            out.setdefault(_fold(part), part)
    return out


def build_ports(loc: Locator, ports: list[dict], accents: dict | None = None) -> list[dict]:
    accents = accents or {}
    out = []
    for p in sorted(ports, key=lambda p: (p["scalerank"] if p["scalerank"] is not None else 99, p["name"] or "")):
        at = loc.place(p["lon"], p["lat"]) if p["name"] not in NOT_SPAIN_PORTS else None
        if at is None:
            continue  # outside Spain
        name = accents.get(_fold(p["name"] or ""), p["name"])
        out.append({"id": f"ES-P{len(out) + 1:03d}", "name": name, "scalerank": p["scalerank"],
                    "rank": len(out) + 1, "tons": None, **at})
    return out


def muni_display(municipalities: list[dict]) -> dict:
    """INE code -> display name ("Coruña, A" -> "A Coruña"); replaces OurAirports' English "city" field."""
    out = {}
    for m in municipalities:
        parts = []
        for part in m["name"].split("/"):
            part = part.strip()
            if ", " in part:
                base, art = part.rsplit(", ", 1)
                if len(art) <= 3:
                    part = f"{art} {base}"
            parts.append(part)
        out[m["code"]] = " / ".join(parts)
    return out


def build_airports(loc: Locator, airports: list[dict], names: dict | None = None) -> list[dict]:
    names = names or {}
    out, seen = [], set()
    for a in sorted(airports, key=lambda a: (a["type"] != "large_airport", a["name"] or "")):
        at = loc.place(a["lon"], a["lat"], known_spanish=True)
        if at is None or a["id"] in seen:
            continue
        seen.add(a["id"])
        out.append({"id": a["id"], "name": airport_name_es(a["name"] or a["id"]), "city": names.get(at.get("county"), a["city"]), "type": a["type"], "hub": None,
                    "passengers": None, **at})
    return out


# ------------------------------------------------------------------ build


def build() -> None:
    world = load_interim("_world")
    grid, proj, owner = HexGrid(**world["grid"]), MapProjection(**world["projection"]), world["owner"]
    infra = load_interim("natural_earth_infra")
    lau = load_interim("gisco_lau")
    world = dict(world, state_abbrs=[c["iso"] for c in sorted(lau["ccaa"], key=lambda c: c["code"])])
    foreign = load_interim("natural_earth")["countries"]
    foreign_idx = ShapeIndex([Shape([proj.project_ring(r) for r in c["rings"]]) for c in foreign], cell_km=200)

    roads = build_roads(grid, proj, owner, infra["roads"])
    rail = build_rail(grid, proj, owner, infra["rail"], foreign_idx)
    cities = json.loads((WEB_DATA / "cities.json").read_text())
    loc = Locator(world, grid, proj, lau["municipalities"], cities)
    ports = build_ports(loc, infra["ports"], accent_lookup(lau["municipalities"]))
    airports = build_airports(loc, load_interim("ourairports")["airports"], muni_display(lau["municipalities"]))

    doc = {
        "version": 1,
        "vintage": {"roads": VINTAGE_NOTE, "rail": VINTAGE_NOTE, "ports": VINTAGE_NOTE,
                    "airports": load_interim_payload("ourairports")["vintage"]},
        "sources": ["natural_earth_infra", "ourairports"],
        "attribution": ATTRIBUTION,
        "note": NOTE,
        "rules": RULES,
        "road_classes": ROAD_CLASSES,
        "rail_tiers": RAIL_TIERS,
        "hubs": {},
        "roads": roads,
        "rail": rail,
        "ports": ports,
        "airports": airports,
    }
    write_web("infrastructure.json", doc)
    n0 = Counter(r[2] for r in roads)
    t0 = Counter(r[2] for r in rail)
    cross = frame_crossings(roads, grid, proj) + frame_crossings(rail, grid, proj)
    print(f"    roads: {n0[0]} autopista/autovía + {n0[1]} principal links; rail: {t0[0]} principal + {t0[1]} secundaria; "
          f"{len(ports)} ports, {len(airports)} airports; links crossing an inset frame: {cross}")
