"""simple.json: the data of the simple interface (web/simple/): a map of municipal boundaries, one card per municipality.

Everything comes from files that already exist: counties.json (the municipal rows of the explorer), the interims
ine_series (income by year) and gisco_lau (boundaries), states.json and projection.json. Nothing is downloaded.

Format: see docs/DATA_CONTRACTS.md "simple.json". Percentages are 0-100, income is an integer in euros, a missing
value is null (never 0). Province and national values are population-weighted means (density = people / km2; growth = sum of 2026
population over sum of 2021 population; crime_rate and tourist are population-weighted means of municipal rates).
"""

from __future__ import annotations

import json
import math
import re
import statistics

from ..core.geo import MapProjection
from ..core.store import WEB_DATA, load_interim, load_interim_payload, write_web

REQUIRES = ["gisco_lau", "ine_series", "counties.json", "projection.json", "states.json", "infrastructure.json",
            "wonders.json"]
PRODUCES = ["simple.json"]

MAX_BYTES = 3_000_000
MADRID = "28079"
YEARS = [str(y) for y in range(2015, 2025)]
MAP_W = 1000
SIMPLIFY_EPS = 0.6  # Douglas-Peucker tolerance in map units (the map is 1000 wide)
MIN_PART_AREA = 1.5  # secondary rings smaller than this (map units squared) are dropped
# Provinces of the south by definition, whatever their latitude (islands and the African cities).
SOUTH_PROVINCES = {"35", "38", "51", "52"}

SOURCES = ("INE (Atlas de distribución de renta de los hogares 2015-2024, Censo anual de población 2021 y 2026, "
           "Censo de Población y Viviendas 2021, estadística experimental de viviendas turísticas 2026, Estadística de "
           "Migraciones y Cambios de Residencia 2022-2024); Ministerio del Interior (Balance de Criminalidad 2025). "
           "Límites municipales: Eurostat GISCO, © EuroGeographics (uso no comercial).")

PROVINCES = """01 Araba/Álava|02 Albacete|03 Alicante/Alacant|04 Almería|05 Ávila|06 Badajoz|07 Illes Balears|08 Barcelona|09 Burgos|10 Cáceres|11 Cádiz|12 Castellón/Castelló|13 Ciudad Real|14 Córdoba|15 A Coruña|16 Cuenca|17 Girona|18 Granada|19 Guadalajara|20 Gipuzkoa|21 Huelva|22 Huesca|23 Jaén|24 León|25 Lleida|26 La Rioja|27 Lugo|28 Madrid|29 Málaga|30 Murcia|31 Navarra|32 Ourense|33 Asturias|34 Palencia|35 Las Palmas|36 Pontevedra|37 Salamanca|38 Santa Cruz de Tenerife|39 Cantabria|40 Segovia|41 Sevilla|42 Soria|43 Tarragona|44 Teruel|45 Toledo|46 Valencia/València|47 Valladolid|48 Bizkaia|49 Zamora|50 Zaragoza|51 Ceuta|52 Melilla""".split("|")
PROVINCE_NAME = {p[:2]: p[3:] for p in PROVINCES}

SRC_ATLAS = "INE, Atlas de distribución de renta de los hogares, 2024"
SRC_CENSUS = "INE, Censo anual de población, 2026"
# key, label, unit, format, year, source, higher_is, icon (the order is part of the contract)
INDICATORS = [
    ("income", "Renta neta media por persona", "€", "eur", 2024, SRC_ATLAS, "better", "💶"),
    ("age_mean", "Edad media", "años", "years", 2024, SRC_ATLAS, "neutral", "🎂"),
    ("growth", "Crecimiento de la población 2021-2026", "%", "pct", 2026, "INE, Censo anual de población, 2021 y 2026", "better", "📈"),
    ("density", "Densidad de población", "hab./km²", "int", 2026, "INE, Censo anual de población 2026, y Eurostat GISCO (superficie)", "neutral", "🏙️"),
    ("elderly", "Personas de 65 años o más", "% de la población", "pct", 2024, SRC_ATLAS, "neutral", "🧓"),
    ("foreign", "Población con nacionalidad extranjera", "% de la población", "pct", 2026, SRC_CENSUS, "neutral", "🌍"),
    ("household", "Tamaño medio del hogar", "personas", "dec1", 2024, SRC_ATLAS, "neutral", "🏠"),
    ("poverty", "Población bajo el umbral de pobreza", "% de la población", "pct", 2024, SRC_ATLAS, "neutral", "⚠️"),
    ("higher_education", "Con estudios superiores", "% de la población de 15 años o más", "pct", 2024, SRC_ATLAS, "better", "🎓"),
    ("non_primary", "Viviendas no principales", "% de las viviendas", "pct", 2021, "INE, Censo de Población y Viviendas 2021", "neutral", "🏚️"),
    ("tourist", "Viviendas turísticas", "% de las viviendas", "pct", 2026, "INE, estadística experimental de viviendas turísticas (mayo de 2026), y Censo de Población y Viviendas 2021", "neutral", "🧳"),
    ("born_abroad", "Nacidos en el extranjero", "% de la población", "pct", 2026, "INE, Censo anual de población 2026 (tabla 65031)", "neutral", "🌍"),
    ("immigration", "Llegadas desde el extranjero", "por 1.000 hab. al año", "dec1", 2024, "INE, Estadística de Migraciones y Cambios de Residencia (media anual 2022-2024)", "neutral", "✈️"),
    ("crime_rate", "Infracciones penales", "por 1.000 hab.", "dec1", 2025, "Ministerio del Interior, Balance de Criminalidad 2025", "neutral", "🚨"),
]
KEYS = [i[0] for i in INDICATORS]
FRACTIONS = {"growth", "elderly", "foreign", "poverty", "higher_education", "non_primary", "tourist", "born_abroad"}  # 0..1 in counties.json, 0-100 here
COLS = ["code", "name", "province", "ccaa", "population"] + KEYS
K = {k: 5 + i for i, k in enumerate(KEYS)}
POP = 4

_ARTICLE = re.compile(r"^(.*), (El|La|Los|Las|L'|Els|Les|O|A|Os|As|el|la|los|las|l'|els|les)$")


def fix_name(name: str) -> str:
    """INE puts the article last: "Palmas de Gran Canaria, Las" -> "Las Palmas de Gran Canaria", "Hospitalet de
    Llobregat, L'" -> "L'Hospitalet de Llobregat". Each side of a bilingual "A/B" or "A / B" name is fixed alone."""
    def one(part: str) -> str:
        part = part.strip()
        m = _ARTICLE.match(part)
        if not m:
            return part
        art = m.group(2)
        art = art[0].upper() + art[1:]
        return f"{art}{m.group(1)}" if art.endswith("'") else f"{art} {m.group(1)}"
    sides = re.split(r"(\s*/\s*)", name.strip())
    return "".join(one(s) if i % 2 == 0 else s for i, s in enumerate(sides))


def weighted_mean(rows: list[list], key: str) -> float | None:
    """Population-weighted mean of `key` over the rows that have a value and a population; None if none."""
    num = den = 0.0
    for r in rows:
        x = r[K[key]]
        if x is not None and r[POP]:
            num += x * r[POP]
            den += r[POP]
    return num / den if den else None


def growth_pct(pairs: list[tuple]) -> float | None:
    """Growth 2021-2026 in %: sum of 2026 population over sum of 2021 population, minus 1, over the (pop2026, pop2021)
    pairs that have both (a missing or zero value on either side leaves the municipality out)."""
    a = b = 0.0
    for p26, p21 in pairs:
        if p26 and p21:
            a += p26
            b += p21
    return (a / b - 1) * 100 if b else None


def aggregate(rows: list[list], key: str, area: dict[str, float]) -> float | None:
    if key == "density":
        a = sum(area[r[0]] for r in rows)
        return sum(r[POP] or 0 for r in rows) / a if a else None
    return weighted_mean(rows, key)


def round_value(key: str, x: float | None):
    if x is None:
        return None
    return round(x) if key in ("income", "density") else round(x, 2)


def quantile(values: list[float], q: float) -> float:
    """Linear-interpolated quantile (q in 0..1) of a non-empty list."""
    a = sorted(values)
    i = (len(a) - 1) * q
    lo = int(i)
    hi = min(lo + 1, len(a) - 1)
    return a[lo] + (a[hi] - a[lo]) * (i - lo)


def to_value(key: str, x):
    """Counties.json value -> display value: fractions become 0-100, income an integer, null stays null."""
    if x is None:
        return None
    if key == "income":
        return int(x)
    return round(x * 100, 2) if key in FRACTIONS else x


def simplify(pts: list[tuple], eps: float) -> list[tuple]:
    """Douglas-Peucker on an open polyline (iterative). Fewer than 4 points come back unchanged."""
    if len(pts) < 4:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    todo = [(0, len(pts) - 1)]
    while todo:
        a, b = todo.pop()
        ax, ay = pts[a]
        bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        far, far_i = -1.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            d = abs(dy * (px - ax) - dx * (py - ay)) / length if length else math.hypot(px - ax, py - ay)
            if d > far:
                far, far_i = d, i
        if far > eps:
            keep[far_i] = True
            todo += [(a, far_i), (far_i, b)]
    return [p for p, k in zip(pts, keep) if k]


def ring_area(pts: list[tuple]) -> float:
    n = len(pts)
    return abs(sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))) / 2


def ring_centroid(pts: list[tuple]) -> tuple[float, float]:
    """Area-weighted centroid of a ring; the first point when the ring has no area."""
    a = cx = cy = 0.0
    n = len(pts)
    for i in range(n):
        xa, ya = pts[i]
        xb, yb = pts[(i + 1) % n]
        cr = xa * yb - xb * ya
        a += cr
        cx += (xa + xb) * cr
        cy += (ya + yb) * cr
    if abs(a) < 1e-9:
        return pts[0]
    return cx / (3 * a), cy / (3 * a)


def path_data(rings: list[list[tuple]]) -> str:
    """SVG path of a municipality from rings already in map units: biggest ring first, small extra parts dropped,
    integer coordinates, repeated points removed. A ring that collapses to under 3 points is dropped (the main ring
    becomes a 1-unit triangle so the municipality stays visible)."""
    cand = []
    for pts in rings:
        pts = list(pts)
        if pts and pts[0] == pts[-1]:
            pts = pts[:-1]
        cand.append((ring_area(pts) if len(pts) > 2 else 0.0, pts))
    cand.sort(key=lambda t: -t[0])
    paths = []
    for i, (area, pts) in enumerate(cand):
        if not pts or (i > 0 and area < MIN_PART_AREA):
            continue
        s = simplify(pts + [pts[0]], SIMPLIFY_EPS)[:-1]
        s = [(round(x), round(y)) for x, y in s]
        d = [s[0]]
        for q in s[1:]:
            if q != d[-1]:
                d.append(q)
        if len(d) < 3:
            if i > 0:
                continue
            x, y = d[0]
            d = [(x, y), (x + 1, y), (x + 1, y + 1)]
        paths.append("M" + " L".join(f"{x} {y}" for x, y in d) + " Z")
    return "".join(paths)


def spanish_int(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


def spanish_dec1(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def income_findings(provinces: list[dict], nation_income: float, munis: list[tuple], madrid_lat: float) -> list[str]:
    """Three true sentences about income. `munis` = (province code, latitude, income) per municipality with income;
    `madrid_lat` (the latitude of Madrid city) splits north from south; the islands and the African cities are south."""
    north = [v > nation_income for p, lat, v in munis if lat > madrid_lat and p not in SOUTH_PROVINCES]
    south = [v > nation_income for p, lat, v in munis if lat <= madrid_lat or p in SOUTH_PROVINCES]
    n = round(10 * sum(north) / len(north))
    m = round(10 * sum(south) / len(south))
    ranked = sorted((p for p in provinces if p["values"]["income"] is not None), key=lambda p: -p["values"]["income"])
    hi, lo = ranked[0], ranked[-1]
    ratio = spanish_dec1(hi["values"]["income"] / lo["values"]["income"])
    return [
        f"Al norte de Madrid, {n} de cada 10 municipios superan la renta media de España. Al sur, {m} de cada 10.",
        f"{hi['name']} tiene la renta más alta: {spanish_int(hi['values']['income'])} €.",
        f"{lo['name']}, la más baja: {spanish_int(lo['values']['income'])} €. {hi['name']} la multiplica por {ratio}.",
    ]


def world_to_box(x: float, y: float, tf: dict) -> tuple[float, float]:
    """Map world coordinates (the x, y used across web/data) into the municipal box: X = s*x + dx, Y = s*y + dy."""
    return tf["s"] * x + tf["dx"], tf["s"] * y + tf["dy"]


def short_airport_name(name: str) -> str:
    """Airport name without the leading "Aeropuerto de/del/de la" (or plain "Aeropuerto")."""
    return re.sub(r"^Aeropuerto\s+(?:del\s+|de\s+)?", "", name.strip(), flags=re.I).strip() or name.strip()


def build_points(tf: dict) -> dict:
    """Airports, ports and World Heritage items as {name, x, y} in box coordinates (one decimal)."""
    infra = json.loads((WEB_DATA / "infrastructure.json").read_text(encoding="utf-8"))
    wonders = json.loads((WEB_DATA / "wonders.json").read_text(encoding="utf-8"))

    def at(o: dict) -> dict:
        x, y = world_to_box(o["x"], o["y"], tf)
        return {"x": round(x, 1), "y": round(y, 1)}

    airports = [{"name": short_airport_name(a["name"]), "city": a.get("city")} | at(a) for a in infra["airports"]]
    ports = [{"name": q["name"]} | at(q) for q in infra["ports"]]
    heritage = [{"name": w["name"]} | at(w) for w in wonders["wonders"] if w.get("rule") == "patrimonio_mundial"]
    return {"airports": airports, "ports": ports, "heritage": heritage}


def build() -> None:
    counties = json.loads((WEB_DATA / "counties.json").read_text(encoding="utf-8"))
    ci = {k: i for i, k in enumerate(counties["columns"])}
    series = load_interim("ine_series")
    gis = load_interim("gisco_lau")["municipalities"]
    states = json.loads((WEB_DATA / "states.json").read_text(encoding="utf-8"))
    ccaa_name = {s["fips"]: s["name"] for s in states}
    gm = {g["code"]: g for g in gis}

    rows, area, renamed, pop21 = [], {}, 0, {}
    for r in counties["rows"]:
        code = r[0]
        if code not in gm:
            continue
        name = fix_name(r[1])
        renamed += name != r[1].strip()
        area[code] = r[ci["land_km2"]] or gm[code]["area_km2"]
        p21 = ((series["municipalities"].get(code) or {}).get("pop") or {}).get("2021")
        g = r[ci["growth"]]
        if not p21 and g is not None and r[ci["population"]]:
            p21 = r[ci["population"]] / (1 + g)  # counties.json growth is a fraction
        pop21[code] = p21
        rows.append([code, name, r[ci["province"]], gm[code]["ccaa"], r[ci["population"]]] + [to_value(k, r[ci[k]]) for k in KEYS])

    by_prov: dict[str, list] = {}
    for r in rows:
        by_prov.setdefault(r[2], []).append(r)
    provinces = []
    for p in sorted(by_prov):
        rs = by_prov[p]
        ccaas = [r[3] for r in rs]
        cc = max(set(ccaas), key=ccaas.count)
        provinces.append({"code": p, "name": PROVINCE_NAME[p], "ccaa": cc, "ccaa_name": ccaa_name.get(cc),
                          "population": sum(r[POP] or 0 for r in rs),
                          "values": {k: round_value(k, aggregate(rs, k, area)) for k in KEYS} | {
                              "growth": round_value("growth", growth_pct([(r[POP], pop21[r[0]]) for r in rs]))}})

    nation = {}
    for k in KEYS:
        xs = [r[K[k]] for r in rows if r[K[k]] is not None]
        value = growth_pct([(r[POP], pop21[r[0]]) for r in rows]) if k == "growth" else aggregate(rows, k, area)
        nation[k] = {"value": round_value(k, value), "median": round_value(k, statistics.median(xs)),
                     "q": [round_value(k, quantile(xs, q)) for q in (.05, .25, .5, .75, .95)]}

    by_code = series["municipalities"]

    def muni_series(code: str) -> list:
        d = (by_code.get(code) or {}).get("income") or {}
        return [None if d.get(y) is None else int(round(d[y])) for y in YEARS]

    def weighted_series(codes: list[str]) -> list:
        out = []
        for i in range(len(YEARS)):
            num = den = 0
            for c in codes:
                x = ms[c][i]
                if x is not None:
                    num += x * pop[c]
                    den += pop[c]
            out.append(round(num / den) if den else None)
        return out

    ms = {r[0]: muni_series(r[0]) for r in rows}
    pop = {r[0]: r[POP] or 0 for r in rows}
    ser = {"years": [int(y) for y in YEARS], "nation": weighted_series(list(ms)),
           "provinces": {p: weighted_series([r[0] for r in by_prov[p]]) for p in by_prov}, "munis": ms}

    # Shapes: project once, scale the whole map (insets included) to a box MAP_W wide.
    pj = json.loads((WEB_DATA / "projection.json").read_text(encoding="utf-8"))
    proj = MapProjection(pj["min_x"], pj["max_y"], pj["margin"])
    projected = {g["code"]: [proj.project_ring(ring) for ring in g["rings"]] for g in gis}
    pts_all = [p for rr in projected.values() for ring in rr for p in ring]
    x0, x1 = min(p[0] for p in pts_all), max(p[0] for p in pts_all)
    y0, y1 = min(p[1] for p in pts_all), max(p[1] for p in pts_all)
    for ins in proj.frames():
        x0, x1 = min(x0, ins["x0"]), max(x1, ins["x1"])
        y0, y1 = min(y0, ins["y0"]), max(y1, ins["y1"])
    scale = MAP_W / (x1 - x0)
    height = math.ceil((y1 - y0) * scale)
    shapes, centroid = {}, {}
    for code, rr in projected.items():
        scaled = []
        for ring in rr:
            pts = [((x - x0) * scale, (y - y0) * scale) for x, y in ring]
            if pts and pts[0] == pts[-1]:
                pts = pts[:-1]
            if pts:
                scaled.append(pts)
        if not scaled:
            continue
        shapes[code] = path_data(scaled)
        biggest = max(scaled, key=lambda p: ring_area(p) if len(p) > 2 else 0)
        cx, cy = ring_centroid(biggest) if len(biggest) > 2 else biggest[0]
        centroid[code] = [round(cx), round(cy)]
    bbox = {}
    for p, rs in by_prov.items():
        xs, ys = [], []
        for r in rs:
            nums = list(map(int, re.findall(r"-?\d+", shapes[r[0]])))
            xs += nums[0::2]
            ys += nums[1::2]
        bbox[p] = [min(xs), min(ys), max(xs), max(ys)]

    # One affine for every municipality (Canarias included: the inset is already part of the world coordinates).
    from_world = {"s": round(scale, 9), "dx": round(-x0 * scale, 6), "dy": round(-y0 * scale, 6)}
    points = build_points(from_world)

    # Findings: latitude of each municipality = centroid of its biggest ring in lon/lat.
    lat = {}
    for g in gis:
        ring = max(g["rings"], key=lambda q: ring_area(q) if len(q) > 2 else 0)
        lat[g["code"]] = ring_centroid(ring)[1] if len(ring) > 2 else ring[0][1]
    inc = [(r[2], lat[r[0]], r[K["income"]]) for r in rows if r[K["income"]] is not None and r[0] in lat]
    findings = {"income": income_findings(provinces, nation["income"]["value"], inc, lat[MADRID])}

    vintage = load_interim_payload("ine_series")["vintage"]
    doc = {
        "meta": {"sources": SOURCES,
                 "points_sources": "Aeropuertos: OurAirports (dominio público). Puertos: Natural Earth (dominio público). "
                                   "Patrimonio Mundial: Wikidata (CC0).",
                 "years": {"income": 2024, "population": 2026, "series": [2015, 2024]},
                 "shapes_note": "Mapa de España con Canarias en un recuadro.",
                 "built": "Renta de 2024, población de 2026. " + vintage + "."},
        "indicators": [dict(key=a, label=b, unit=u, format=f, year=y, source=s, higher_is=h, icon=e)
                       for a, b, u, f, y, s, h, e in INDICATORS],
        "munis": {"cols": COLS, "rows": rows}, "provinces": provinces, "nation": nation, "series": ser,
        "shapes": {"w": MAP_W, "h": height, "munis": shapes, "from_world": from_world}, "points": points, "provinces_bbox": bbox, "munis_centroid": centroid,
        "findings": findings,
    }
    size = len(json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode())
    if size > MAX_BYTES:
        raise RuntimeError(f"simple.json is {size / 1e6:.2f} MB, over the {MAX_BYTES / 1e6:.1f} MB limit")
    write_web("simple.json", doc)
    print(f"    {len(rows)} municipalities, {renamed} names fixed, map {MAP_W}x{height}")
    for s in findings["income"]:
        print("    " + s)
