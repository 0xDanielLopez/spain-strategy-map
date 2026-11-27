"""The map itself: hex grid, land/water, relief, land cover, CCAA, municipalities, rivers.

Also saves interim "_world" (grid + projection + per-cell owner/county/water/cover)
so the other builders can drop their data onto the same hexes.

Naming: "states" in the output are the 19 autonomous communities (CCAA) and
"counties" are the municipalities (the code kept the names of the original US map).
"""

from __future__ import annotations

import math
from collections import Counter

from ..core.geo import MapProjection, Shape, ShapeIndex, fit_bounds
from ..core.hexgrid import SQRT3, HexGrid
from ..core.store import load_interim, save_interim, write_web

REQUIRES = ["gisco_lau", "natural_earth", "etopo", "worldcover"]
PRODUCES = ["_world", "world.json"]

# Licence and attribution of the data in this file (web/data/world.json). The GISCO-derived parts (owner, county,
# states, counties, land/water) are for non-commercial use only and are not covered by the code's MIT licence.
ATTRIBUTION = [
    {"data": "owner, county, states, counties, land and water",
     "source": "Eurostat GISCO, Local Administrative Units (LAU) 2024",
     "license": "© EuroGeographics for the administrative boundaries. Non-commercial use only, with this notice visible; not under the MIT licence."},
    {"data": "cover, pct",
     "source": "ESA WorldCover 10 m 2021 v200",
     "license": "CC BY 4.0. © ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium."},
    {"data": "elev, elev_max, relief, sea depth", "source": "NOAA ETOPO1 via ERDDAP", "license": "Public domain"},
    {"data": "foreign land, lakes, rivers", "source": "Natural Earth 1:50m v5.1.2", "license": "Public domain"},
]

HEX_RADIUS_KM = 10.0
MARGIN_KM = 80.0

# Cell owner codes (besides the CCAA index >= 0)
WATER, FOREIGN = -1, -2

# Cartographic exceptions: places too small (or islands) to win a hex by the sampling rules.
# (name, lon, lat); each point must lie inside a Spanish municipality polygon.
FORCED_POINTS = [
    ("Ceuta", -5.33, 35.89), ("Melilla", -2.95, 35.29), ("El Hierro", -18.02, 27.75), ("La Gomera", -17.24, 28.12),
    ("La Palma", -17.86, 28.68), ("Tenerife", -16.62, 28.27), ("Gran Canaria", -15.60, 27.96),
    ("Fuerteventura", -14.02, 28.40), ("Lanzarote", -13.63, 29.04), ("Mallorca", 2.98, 39.62),
    ("Menorca", 4.05, 39.95), ("Eivissa", 1.40, 38.98), ("Formentera", 1.45, 38.70),
]

# --- tables (written to world.json so the frontend and Almanac read one definition) ---------

LAND, OCEAN, COAST, LAKE = range(4)
TIDAL_SEA_SHARE = 0.5  # share of ETOPO samples below 0 m that keeps a sea-centred hex as water
COAST_DEPTH_M = -200
WATER_TABLE = [
    {"id": LAND, "name": "Land", "rule": "At least 4 of the hex's 7 sample points (centre + 6) fall on a Spanish municipality or a Natural Earth country outline, unless the centre is sea and the ETOPO1 mean is at or below sea level, or at least half its ETOPO1 samples are (tidal bays stay water). A few places too small or too isolated to win a hex (Ceuta, Melilla, each island) are forced to land."},
    {"id": OCEAN, "name": "Ocean", "color": "#1b4266", "rule": "Sea deeper than 200 m and not next to land."},
    {"id": COAST, "name": "Coast", "color": "#2d6d97", "rule": "Sea next to a land hex, or shallower than 200 m (ETOPO1 mean)."},
    {"id": LAKE, "name": "Lake", "color": "#3a80b0", "rule": "Water hex (most of its 7 sample points off land) with Natural Earth 1:50m lake points that outnumber sea points, or above sea level."},
]

WATER_NOTE = (
    "The GISCO LAU 1:1M municipality outlines and the Natural Earth 1:50m country and lake outlines don't meet exactly. "
    "A sea hex whose ETOPO1 mean is above sea level (and under half of its samples below it) becomes land when at least "
    "4 of its 6 neighbours are land, or when it touches both Spanish and foreign land; it takes the neighbours' majority "
    "owner. Narrow reservoirs that cover less than half a hex are land, and their river is drawn through them. Tidal "
    "bays stay water when the hex centre is sea and its ETOPO1 mean is at or below sea level or at least half of its "
    "ETOPO1 samples are. A sea hex's elevation is the mean of its ETOPO1 samples below sea level (its water depth). "
    "ETOPO1 samples come every ~3.7 km."
)

FLAT, HILLS, MOUNTAINS, PEAKS = range(4)
LAND_MIN_ALT_M = -100  # ETOPO samples below this inside a land hex are treated as sea floor
HILLS_STD_M, MOUNTAINS_STD_M = 60, 180  # usaciv used 85/260 on 25 km hexes; 10 km hexes have less spread
RELIEF_TABLE = [
    {"id": FLAT, "name": "Flat", "rule": f"Elevation standard deviation inside the hex under {HILLS_STD_M} m."},
    {"id": HILLS, "name": "Hills", "rule": f"Elevation standard deviation ≥ {HILLS_STD_M} m."},
    {"id": MOUNTAINS, "name": "Mountains", "rule": f"Elevation standard deviation ≥ {MOUNTAINS_STD_M} m, or mean elevation ≥ 2,300 m."},
    {"id": PEAKS, "name": "Peaks", "rule": "Mean elevation ≥ 2,700 m (alpine)."},
]
RELIEF_NOTE = (
    "From ETOPO1 samples (one every ~3.7 km, about 25 per hex) with altitude ≥ -100 m, so bays and sea floor don't "
    "count; all samples are used if none qualify. A hex that is mostly flat lowland with a range at one edge is eased "
    "one class. Water hexes are always flat."
)

URBAN_MIN_PCT = 20
# id, key, name, colour, WorldCover codes, rule. Ids are fixed by docs/DATA_CONTRACTS.md (ids 1, 2 and 6 are unused).
COVER = [
    (3, "forest_mixed", "Tree cover", "#43703f", [10], "Tree cover (10) is the largest group."),
    (4, "scrub", "Shrubland", "#c9b07a", [20], "Shrubland (20) is the largest group."),
    (5, "grassland", "Grassland", "#a9b35a", [30, 100], "Grassland (30) plus moss and lichen (100) is the largest group."),
    (7, "cropland", "Cropland", "#c2b84e", [40], "Cropland (40) is the largest group."),
    (8, "wetland", "Wetland", "#4f8a6e", [90, 95], "Herbaceous wetland (90) plus mangroves (95) is the largest group."),
    (9, "urban", "Built-up", "#8a8378", [50], f"Built-up (50) is ≥ {URBAN_MIN_PCT}% of the hex's land points, whatever else is there."),
    (10, "barren", "Bare / sparse", "#bfae95", [60], "Bare or sparse vegetation (60) is the largest group."),
    (11, "ice", "Snow & ice", "#e8eef2", [70], "Snow and ice (70) is the largest group."),
]
COVER_NOTE = (
    "From ESA WorldCover 2021, last overview (~600 m pixels) sampled every 1 km inside each Spanish hex (about 260 "
    "points). Permanent water (80) and no-data pixels are ignored; shares are of the remaining land points, rounded to "
    "whole percent, and the built-up threshold is applied to the rounded built-up share. Olive groves and other woody "
    "crops can appear as tree cover or shrubland, greenhouses as built-up, and pastures are inside grassland (no "
    "separate pasture share). Foreign hexes have cover 0 (none)."
)
# Groups competing for the dominant cover (built-up is decided by its threshold first): name -> (codes, cover id).
GROUPS = {
    "forest": ((10,), 3), "shrub": ((20,), 4), "grass": ((30, 100), 5), "crop": ((40,), 7),
    "wetland": ((90, 95), 8), "bare": ((60,), 10), "snow": ((70,), 11),
}
URBAN_ID = 9
BUILT_UP = (50,)
IGNORED_CLASSES = (0, 80)  # no data, permanent water
PCT = {
    "forest": (10,), "crop": (40,), "grass": (30, 100), "shrub": (20,), "wetland": (90, 95), "developed": (50,),
}
COVER_STEP_KM = 1.0


def classify_relief(mean: float, std: float, hills: float = HILLS_STD_M, mountains: float = MOUNTAINS_STD_M) -> int:
    if mean >= 2700:
        return PEAKS
    if std >= mountains or mean >= 2300:
        return MOUNTAINS
    if std >= hills:
        return HILLS
    return FLAT


def is_valley_floor(samples: list) -> bool:
    """True when the lower 60% of a hex's land samples is flat lowland (within 60 m, under 400 m): the hex is mostly
    valley floor even if a range at its edge makes the whole hex's spread look hilly or mountainous."""
    if len(samples) < 6:
        return False
    v = sorted(samples)
    lo = v[: max(3, int(len(v) * 0.6))]
    return lo[-1] < 400 and lo[-1] - lo[0] < 60


def dominant_cover(counts: Counter, valid: int) -> int:
    """Cover id for a hex from its WorldCover class counts (valid = points that are not water or no-data)."""
    if not valid:
        return 0
    if round(100 * sum(counts[c] for c in BUILT_UP) / valid) >= URBAN_MIN_PCT:  # same rounding as pct.developed
        return URBAN_ID
    best, best_n = 0, 0
    for codes, cid in GROUPS.values():  # dict order breaks ties
        n = sum(counts[c] for c in codes)
        if n > best_n:
            best, best_n = cid, n
    return best  # 0 when only built-up land below the threshold


def ccaa_vote(sample_ccaa: list[int], centre_ccaa: int | None) -> int:
    """Owner of a Spanish hex: the CCAA with the most samples (one vote per sample, not per municipality).

    Ties go to the centre's CCAA if it is among the tied, else to the lowest CCAA index.
    """
    counts = Counter(sample_ccaa)
    top = max(counts.values())
    tied = sorted(c for c in counts if counts[c] == top)
    return centre_ccaa if centre_ccaa in tied else tied[0]


def pick_county(samples: list[int], muni_ccaa: list[int], owner: int) -> int:
    """County (municipality index) of a hex owned by CCAA `owner`, from its municipality per sample (-1 = none).

    Among the samples that fall in the owner CCAA: the centre's municipality (samples[0]) if it is one of them,
    else the most common (ties -> lowest index). -1 when no sample is in the owner CCAA.
    """
    pool = [k for k in samples if k >= 0 and muni_ccaa[k] == owner]
    if not pool:
        return -1
    if samples[0] in pool:
        return samples[0]
    counts = Counter(pool)
    top = max(counts.values())
    return min(k for k in counts if counts[k] == top)


def percentile(sorted_values: list[float], p: float) -> float:
    return sorted_values[min(len(sorted_values) - 1, int(p / 100 * len(sorted_values)))]


def simplify(points: list[tuple[float, float]], min_km: float) -> list[tuple[float, float]]:
    out = [points[0]]
    for p in points[1:-1]:
        if math.dist(p, out[-1]) >= min_km:
            out.append(p)
    out.append(points[-1])
    return out


def clip_segment(p, q, w, h):
    """Liang–Barsky: the part of segment p→q inside [0,w]×[0,h], or None."""
    (x0, y0), (x1, y1) = p, q
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for pk, qk in ((-dx, x0), (dx, w - x0), (-dy, y0), (dy, h - y0)):
        if pk == 0:
            if qk < 0:
                return None
            continue
        t = qk / pk
        if pk < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return None
    return (x0 + t0 * dx, y0 + t0 * dy), (x0 + t1 * dx, y0 + t1 * dy)


def clip_polyline(pts, w, h) -> list[list[tuple[float, float]]]:
    """Split a polyline into the pieces that lie inside the map rectangle."""
    pieces, cur = [], []
    for p, q in zip(pts, pts[1:]):
        seg = clip_segment(p, q, w, h)
        if seg is None:
            if len(cur) >= 2:
                pieces.append(cur)
            cur = []
            continue
        a, b = seg
        if cur and math.dist(cur[-1], a) < 1e-9:
            cur.append(b)
        else:
            if len(cur) >= 2:
                pieces.append(cur)
            cur = [a, b]
        if b != q:  # left the map inside this segment
            pieces.append(cur)
            cur = []
    if len(cur) >= 2:
        pieces.append(cur)
    return pieces


def land_runs(pts, is_land, step: float = 2.0) -> list[list[tuple[float, float]]]:
    """Split a projected polyline (densified every `step` km) into the runs whose points satisfy is_land."""
    runs, cur = [], []
    for k, (p, q) in enumerate(zip(pts, pts[1:])):
        n = max(1, math.ceil(math.dist(p, q) / step))
        for j in range(0 if k == 0 else 1, n + 1):
            t = j / n
            pt = (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]))
            if is_land(pt):
                cur.append(pt)
            else:
                if len(cur) >= 2:
                    runs.append(cur)
                cur = []
    if len(cur) >= 2:
        runs.append(cur)
    return runs


def join_lines(lines: list[list[tuple[float, float]]], tol: float = 0.5) -> list[list[tuple[float, float]]]:
    """Greedily join polylines whose ends meet (within `tol` km), reversing pieces as needed."""
    lines = [list(l) for l in lines]
    joined = True
    while joined:
        joined = False
        for a in range(len(lines)):
            for b in range(len(lines)):
                if a == b or not lines[a] or not lines[b]:
                    continue
                la, lb = lines[a], lines[b]
                for la2, lb2 in ((la, lb), (la, lb[::-1]), (la[::-1], lb), (la[::-1], lb[::-1])):
                    if math.dist(la2[-1], lb2[0]) <= tol:
                        lines[a] = la2 + lb2[1:]
                        lines[b] = []
                        joined = True
                        break
        lines = [l for l in lines if l]
    return lines


def hex_lattice(radius: float, step: float) -> list[tuple[float, float]]:
    """Offsets of a square lattice (spacing `step`) that fall inside a pointy-top hex."""
    half_w = SQRT3 / 2 * radius
    n = int(radius // step) + 1
    out = []
    for iy in range(-n, n + 1):
        for ix in range(-n, n + 1):
            x, y = (ix + 0.5) * step, (iy + 0.5) * step
            if abs(x) <= half_w and abs(y) <= radius - abs(x) / SQRT3:
                out.append((x, y))
    return out


def majority(values: list, centre) -> object:
    """Most common value; ties go to `centre` if it is among the tied, else to the first seen."""
    counts = Counter(values)
    top = max(counts.values())
    tied = [v for v in counts if counts[v] == top]
    return centre if centre in tied else tied[0]



def build() -> None:
    lau = load_interim("gisco_lau")
    ne = load_interim("natural_earth")
    etopo = load_interim("etopo")
    wc = load_interim("worldcover")

    ccaa = sorted(lau["ccaa"], key=lambda c: c["code"])
    ccaa_index = {c["code"]: i for i, c in enumerate(ccaa)}
    munis = sorted(lau["municipalities"], key=lambda m: m["code"])
    muni_ccaa = [ccaa_index[m["ccaa"]] for m in munis]

    # Projection: fit every main-region municipality ring plus the inset frames, with a margin.
    probe = MapProjection(0, 0, 0)
    main_pts = [
        probe._albers(lon, lat)
        for m in munis
        for ring in m["rings"]
        if probe.ring_region(ring) == "main"
        for lon, lat in ring
    ]
    min_x, max_y, width, height = fit_bounds(main_pts, margin=MARGIN_KM)
    del main_pts
    proj = MapProjection(min_x, max_y, MARGIN_KM)
    grid = HexGrid.covering(width, height, HEX_RADIUS_KM)
    print(f"    grid {grid.cols}×{grid.rows} = {grid.size} hexes of {HEX_RADIUS_KM:g} km")

    def shape(rings):
        return Shape([proj.project_ring(r) for r in rings])

    muni_idx = ShapeIndex([shape(m["rings"]) for m in munis], cell_km=30)
    foreign_idx = ShapeIndex([shape(c["rings"]) for c in ne["countries"]], cell_km=200)
    lake_idx = ShapeIndex([shape(l["rings"]) for l in ne["lakes"]])

    # --- elevation statistics per hex (land samples and all samples) -----------------------------
    stats_all = [[0, 0.0, 0.0] for _ in range(grid.size)]
    stats_land = [[0, 0.0, 0.0] for _ in range(grid.size)]
    samples_land = [[] for _ in range(grid.size)]  # land altitudes, for the peak height and the valley-floor test
    below_sea = [0] * grid.size  # ETOPO samples below 0 m ...
    below_sum = [0.0] * grid.size  # ... and their altitude sum
    hidden = 0
    for lat, lon, alt in zip(etopo["lat"], etopo["lon"], etopo["alt"]):
        if proj.hidden(lon, lat):  # mainland-projection samples that fall under an inset frame
            hidden += 1
            continue
        i = grid.cell_at(*proj(lon, lat))
        if i < 0:
            continue
        if alt < 0:
            below_sea[i] += 1
            below_sum[i] += alt
        for st in (stats_all[i], stats_land[i]) if alt >= LAND_MIN_ALT_M else (stats_all[i],):
            st[0] += 1
            st[1] += alt
            st[2] += alt * alt
        if alt >= LAND_MIN_ALT_M:
            samples_land[i].append(alt)
    print(f"    {hidden} ETOPO samples dropped under inset frames")

    def sea_share(i):
        return below_sea[i] / stats_all[i][0] if stats_all[i][0] else 0.0

    def mean_std(st):
        n, s1, s2 = st
        if not n:
            return None, None
        m = s1 / n
        return m, math.sqrt(max(0.0, s2 / n - m * m))

    # --- ownership: majority of 7 sample points --------------------------------------------------
    # The centre plus six points 60% of the way to each corner. Each point is lake, a municipality,
    # foreign land or sea (inside an inset frame only municipalities or sea count). Land when more
    # than half are land; the CCAA with most samples owns the hex.
    offsets = [(0.0, 0.0)] + [
        (0.6 * HEX_RADIUS_KM * math.cos(math.radians(60 * k - 30)), 0.6 * HEX_RADIUS_KM * math.sin(math.radians(60 * k - 30)))
        for k in range(6)
    ]
    owner = [WATER] * grid.size
    water = [OCEAN] * grid.size
    for i in range(grid.size):
        cx, cy = grid.center(*grid.col_row(i))
        in_inset = proj.frame_at(cx, cy) is not None
        kinds = []
        for dx, dy in offsets:
            x, y = cx + dx, cy + dy
            if not in_inset and lake_idx.locate(x, y) >= 0:
                kinds.append("lake")
            elif (s := muni_idx.locate(x, y)) >= 0:
                kinds.append(s)
            elif not in_inset and foreign_idx.locate(x, y) >= 0:
                kinds.append(FOREIGN)
            else:
                kinds.append("sea")
        land = [k for k in kinds if not isinstance(k, str)]
        m_all, _ = mean_std(stats_all[i])
        # Tidal bays are narrower than half a hex; keep them water when the centre is sea and the hex is
        # mostly at or below sea level in ETOPO1.
        tidal = kinds[0] == "sea" and m_all is not None and (m_all <= 0 or sea_share(i) >= TIDAL_SEA_SHARE)
        if len(land) * 2 > len(kinds) and not tidal:
            es = [k for k in land if k >= 0]
            n_foreign = len(land) - len(es)
            if len(es) > n_foreign or (len(es) == n_foreign and kinds[0] != FOREIGN):
                centre = muni_ccaa[kinds[0]] if isinstance(kinds[0], int) and kinds[0] >= 0 else None
                owner[i] = ccaa_vote([muni_ccaa[k] for k in es], centre)
            else:
                owner[i] = FOREIGN
            water[i] = LAND
        else:
            wet = [k for k in kinds if isinstance(k, str)]
            # Points in neither the lake nor the land outlines are usually sea, but next to a lake they are
            # mostly gaps between the two datasets' shorelines, so a lake hex needs only to be above sea level.
            above_sea = m_all is not None and m_all > 0
            lakeish = "lake" in wet and (above_sea or majority(wet, kinds[0] if kinds[0] in wet else "lake") == "lake")
            water[i] = LAKE if lakeish else OCEAN

    # Sliver fix: LAU (1:1M) and Natural Earth (1:50m) outlines don't meet exactly, leaving water hexes
    # on land along the borders. A non-lake water hex whose ETOPO mean is above sea level becomes land if at
    # least 4 of its neighbours are land, or if it touches both Spanish and foreign land. It takes its land
    # neighbours' majority owner.
    slivers = []
    for i in range(grid.size):
        if water[i] != OCEAN:
            continue
        m, _ = mean_std(stats_all[i])
        land_nb = [owner[j] for j in grid.neighbours(i) if water[j] == LAND]
        border = FOREIGN in land_nb and any(o >= 0 for o in land_nb)
        if m is not None and m > 0 and sea_share(i) < TIDAL_SEA_SHARE and (len(land_nb) >= 4 or border):
            slivers.append((i, Counter(land_nb).most_common(1)[0][0]))
    for i, o in slivers:
        owner[i], water[i] = o, LAND
    print(f"    {len(slivers)} sliver water hexes turned into land: {[i for i, _ in slivers]}")

    # --- municipalities for Spanish cells --------------------------------------------------------
    county = [-1] * grid.size
    county_samples: list[list[int]] = [[] for _ in range(grid.size)]
    for i in range(grid.size):
        if owner[i] >= 0:
            cx, cy = grid.center(*grid.col_row(i))
            county_samples[i] = [muni_idx.locate(cx + dx, cy + dy) for dx, dy in offsets]
    # Hexes whose seven points all miss the municipality polygons (e.g. reclaimed slivers) borrow the most
    # common municipality of their same-CCAA neighbours for the centre sample.
    borrowed = 0
    for i in range(grid.size):
        smp = county_samples[i]
        if smp and max(smp) < 0:
            nb = [k for j in grid.neighbours(i) if owner[j] == owner[i] for k in county_samples[j] if k >= 0]
            if nb:
                smp[0] = Counter(nb).most_common(1)[0][0]
                borrowed += 1
    # The hex's county must lie in its owner CCAA (see pick_county). county_samples keep every point.
    off_ccaa = 0
    for i, smp in enumerate(county_samples):
        if smp:
            county[i] = pick_county(smp, muni_ccaa, owner[i])
            off_ccaa += county[i] < 0
    print(f"    {borrowed} Spanish hexes borrowed a neighbour's municipality; {off_ccaa} have none in their own CCAA")

    # --- forced land: places too small or isolated to win a hex --------------------------------
    forced = []
    for name, lon, lat in FORCED_POINTS:
        x, y = proj(lon, lat)
        mi = muni_idx.locate(x, y)
        if mi < 0:
            raise RuntimeError(f"forced point {name} ({lon}, {lat}) is not inside any municipality polygon; move it inland")
        i = grid.cell_at(x, y)
        if i < 0:
            raise RuntimeError(f"forced point {name} is outside the grid")
        if owner[i] >= 0:
            continue
        reason = f"{name} ({munis[mi]['area_km2']:g} km2 municipality) is smaller than one hex" if munis[mi]["area_km2"] < 260 else f"{name}: island had no land hex"
        owner[i], water[i], county[i] = muni_ccaa[mi], LAND, mi
        county_samples[i] = [mi] * len(offsets)
        forced.append({"cell": i, "name": name, "reason": reason})
    print(f"    {len(forced)} forced land hexes: {[f['name'] for f in forced]}")

    # --- elevation, water depth classes and relief -------------------------------------------------
    elev = [0] * grid.size
    relief = [FLAT] * grid.size
    elev_max = [0] * grid.size  # highest land sample (m): snow on high ranges whose mean is held down by valleys
    valley_floor = 0
    no_elev = 0
    relief_inputs = []  # (mean, std, valley floor) of Spanish land hexes, for the threshold report
    for i in range(grid.size):
        if water[i] == LAND:
            m, sd = mean_std(stats_land[i])
            if m is None:
                m, sd = mean_std(stats_all[i])
                m = None if m is None else max(m, 0.0)
            if m is None:
                no_elev += 1
                continue  # elev 0, flat
            elev[i] = round(m)
            relief[i] = classify_relief(max(m, 0.0), sd)
            vf = is_valley_floor(samples_land[i])
            if relief[i] in (HILLS, MOUNTAINS) and vf:
                relief[i] -= 1  # mostly flat lowland with a range at one edge
                valley_floor += 1
            if owner[i] >= 0:
                relief_inputs.append((max(m, 0.0), sd, vf))
            if samples_land[i]:
                elev_max[i] = max(0, round(max(samples_land[i])))
        else:
            m, _ = mean_std(stats_all[i])
            if m is None:
                no_elev += 1
                elev[i] = -4000  # outside the elevation window: assume deep ocean
            elif water[i] != LAKE and below_sea[i]:
                elev[i] = round(below_sum[i] / below_sea[i])  # sea: mean depth of the samples under water
            else:
                elev[i] = min(round(m), 0)
            if water[i] == OCEAN:
                near_land = any(water[j] == LAND for j in grid.neighbours(i))
                water[i] = COAST if near_land or elev[i] > COAST_DEPTH_M else OCEAN
    print(f"    {no_elev} hexes without elevation samples; {valley_floor} valley-floor hexes eased one relief class")

    stds = sorted(sd for _, sd, _ in relief_inputs)
    means = sorted(m for m, _, _ in relief_inputs)
    by_class = Counter(relief[i] for i in range(grid.size) if owner[i] >= 0 and water[i] == LAND)
    print(f"    relief over {len(relief_inputs)} Spanish land hexes: " + ", ".join(f"{RELIEF_TABLE[c]['name']} {by_class[c]}" for c in range(4)))
    for label, vals in (("std", stds), ("mean", means)):
        print(f"      {label} p50/p75/p90/p97: " + " / ".join(f"{percentile(vals, p):.0f}" for p in (50, 75, 90, 97)) + " m")
    for hi, mo in ((HILLS_STD_M, MOUNTAINS_STD_M), (60, 180), (50, 150)):
        cnt = Counter()
        for m, sd, vf in relief_inputs:
            c = classify_relief(m, sd, hi, mo)
            cnt[c - 1 if c in (HILLS, MOUNTAINS) and vf else c] += 1
        print(f"      std thresholds {hi}/{mo}: " + ", ".join(f"{RELIEF_TABLE[c]['name']} {cnt[c]}" for c in range(4)))

    # --- land cover from WorldCover ----------------------------------------------------------------
    legend = wc["legend"]
    tiles = {(t["lat0"], t["lon0"]): t for t in wc["tiles"].values()}
    lattice = hex_lattice(HEX_RADIUS_KM, COVER_STEP_KM)
    cover = [0] * grid.size
    pct = {k: [0] * grid.size for k in PCT}
    no_cover = 0
    for i in range(grid.size):
        if owner[i] < 0:
            continue
        cx, cy = grid.center(*grid.col_row(i))
        counts: Counter = Counter()
        for ox, oy in lattice:
            lon, lat = proj.inverse(cx + ox, cy + oy)
            lat0, lon0 = 3 * math.floor(lat / 3), 3 * math.floor(lon / 3)
            t = tiles.get((lat0, lon0))
            if t is None:
                continue  # no tile published: sea
            w, h = t["w"], t["h"]
            c = min(w - 1, max(0, int((lon - lon0) * w / 3)))
            r = min(h - 1, max(0, int((lat0 + 3 - lat) * h / 3)))
            counts[legend[t["rows"][r][c]]] += 1
        valid = sum(n for code, n in counts.items() if code not in IGNORED_CLASSES)
        cover[i] = dominant_cover(counts, valid)
        if not valid:
            no_cover += 1
            continue
        for k, codes in PCT.items():
            pct[k][i] = round(100 * sum(counts[c] for c in codes) / valid)
    print(f"    {len(lattice)} WorldCover points per hex; {no_cover} Spanish hexes without land-cover samples")

    # --- rivers ----------------------------------------------------------------------------------
    # Lake centerlines are kept only where they cross land hexes (reservoirs narrower than half a hex),
    # so rivers don't stop in the middle of land; over water hexes they go. Points under an inset frame are dropped.
    def on_land(pt):
        c = grid.cell_at(*pt)
        return c >= 0 and water[c] == LAND

    def project_line(line):
        runs, cur = [], []
        for lon, lat in line:
            if proj.hidden(lon, lat):
                if len(cur) >= 2:
                    runs.append(cur)
                cur = []
            else:
                cur.append(proj(lon, lat))
        if len(cur) >= 2:
            runs.append(cur)
        return runs

    by_river: dict[tuple, list] = {}
    for r in ne["rivers"]:
        if r["rank"] > 8:
            continue
        for line in project_line(r["line"]):
            if (r.get("featurecla") or "").startswith("Lake Centerline"):
                parts = [run for p in clip_polyline(line, width, height) for run in land_runs(p, on_land)]
            else:
                parts = clip_polyline(line, width, height)
            by_river.setdefault((r["name"], r["rank"]), []).extend(parts)
    rivers = []
    for (name, rank), parts in by_river.items():
        for piece in join_lines(parts):
            if sum(math.dist(a, b) for a, b in zip(piece, piece[1:])) < 1.0:
                continue  # a corner clipped down to nothing
            pts = simplify(piece, 4.0)
            if len(pts) >= 2:
                rivers.append({"name": name, "rank": rank, "pts": [round(v, 1) for p in pts for v in p]})

    cover_table = [{"id": 0, "key": "none", "name": "None", "rule": "Water, foreign land, or no WorldCover land pixels."}] + [
        {"id": cid, "key": key, "name": name, "color": color, "worldcover": codes, "rule": rule}
        for cid, key, name, color, codes, rule in COVER
    ]
    tables = {
        "water": WATER_TABLE,
        "relief": RELIEF_TABLE,
        "cover": cover_table,
        "notes": {"water": WATER_NOTE, "relief": RELIEF_NOTE, "cover": COVER_NOTE},
    }
    states_out = [{"fips": c["code"], "abbr": c["iso"], "name": c["name"]} for c in ccaa]
    write_web(
        "world.json",
        {
            "version": 2,
            "country": "Spain",
            "attribution": ATTRIBUTION,
            "grid": grid.to_dict(),
            "width": round(width, 1),
            "height": round(height, 1),
            "margin": MARGIN_KM,
            "insets": proj.frames(),
            "owner": owner,
            "county": county,
            "elev": elev,
            "elev_max": elev_max,
            "water": water,
            "relief": relief,
            "cover": cover,
            "pct": pct,
            "tables": tables,
            "states": states_out,
            "counties": [{"geoid": m["code"], "name": m["name"], "province": m["province"]} for m in munis],
            "forced": forced,
            "rivers": rivers,
        },
    )
    save_interim(
        "_world",
        {
            "grid": grid.to_dict(),
            "projection": proj.to_dict(),
            "owner": owner,
            "county": county,
            "county_samples": county_samples,
            "states": [c["code"] for c in ccaa],
            "counties": [m["code"] for m in munis],
            "water": water,
            "cover": cover,
            "pct": pct,
        },
    )
