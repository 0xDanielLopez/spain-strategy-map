"""Validate web/data/*.json against docs/DATA_CONTRACTS.md (v2) and report data quality.

    uv run python -m pipeline check

Part 1 checks each file's shape: required keys, types, per-cell array lengths and value
ranges. Part 2 is a short data-quality report for the base map (Spanish land hexes, hexes
per CCAA, forced cells, rivers inside the map). Cities, states and nation (F2) are checked against the economy builder.
Without statistics (F0) cities.json is [] and nation.json minimal; the other files are optional.

Every line is PASS, WARN or FAIL (NOTE for information). The exit code is 1 if
anything FAILed.

Part 3 runs builder-level checks: any module in pipeline/build/ may define

    def check(web_dir: Path) -> list[tuple[str, str]]   # [(level, message)], level in PASS/NOTE/WARN/FAIL

to validate the files it PRODUCES, so a new builder never has to edit this file. It is discovered
automatically (see run_builder_checks); a missing output should be reported as a NOTE (or WARN), not a FAIL,
unless the file is required. A check that raises is reported as a FAIL with the error.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

from .core.geo import Albers, MapProjection
from .core.paths import INTERIM, WEB_DATA

REQUIRED = ["world.json", "cities.json", "nation.json", "sources.json"]
OPTIONAL = ["states.json", "lenses.json", "resources.json", "infrastructure.json", "wonders.json", "counties.json", "districts.json", "citizens.json",
            "safety.json", "boja.json", "contracts_junta.json"]
N_CCAA = 19
LENS_FORMATS = {"int", "eur", "pct", "float", "minutes", "years", "category"}
LENS_SCALES = {"linear", "log"}
HIGHER_IS = {"good", "bad", "neutral"}
NATION_TOLERANCE = 0.005  # people on the hexes vs the municipal total
# Per-CCAA is only a sanity bound: a hex belongs to its majority CCAA but a border municipality's people are split by
# area across hexes of several CCAA, so small CCAA drift by design (measured worst 16 % for Navarra).
CCAA_TOLERANCE = 0.25

WATER_IDS = range(0, 4)
RELIEF_IDS = range(0, 4)
# Cover id -> key (fixed by the contract). F0 uses ids 0, 3, 4, 5, 7, 8, 9, 10, 11 only.
COVER_KEYS = [
    "none", "forest_deciduous", "forest_evergreen", "forest_mixed", "scrub", "grassland",
    "pasture", "cropland", "wetland", "urban", "barren", "ice",
]
CHANGE_LENSES = {"growth", "foreign_change"}  # fractions that can be below 0 and above 1
NEW_LENS_IDS = {"non_primary_homes", "tourist_homes", "housing_density", "tourist_beds", "immigration", "foreign_change",
                "born_abroad", "crime", "burglary"}
PCT_KEYS = ["forest", "crop", "grass", "shrub", "wetland", "developed"]
COLOR = re.compile(r"^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?([0-9a-fA-F]{2})?$")


# ---------------------------------------------------------------- city scopes (web/data/city/<id>/)

CITY_FILES = ("world.json", "cities.json", "nation.json", "lenses.json", "states.json", "sources.json", "projection.json")
CITY_WORLD_KEYS = ("version", "country", "attribution", "grid", "width", "height", "margin", "insets", "owner", "county", "elev",
                   "elev_max", "water", "relief", "cover", "pct", "pop", "tables", "states", "counties", "muni_cell", "forced",
                   "rivers", "scope")
CITY_SCOPE_KEYS = ("id", "kind", "name", "title", "hex_km", "levels", "note")
CITY_MAX_BYTES = 3_000_000
CITY_COVERAGE_WARN, CITY_COVERAGE_FAIL = 0.60, 0.30
NAME_OK = re.compile(r"^[\w .,'()/·-]{1,80}$")


def check_city_scope(r: Report, scope_dir: Path) -> None:
    """One scope folder: files, keys, array lengths, population conservation, lens coverage, sizes, names only."""
    sid = scope_dir.name
    docs, fails = {}, r.count("FAIL")
    for name in CITY_FILES:
        path = scope_dir / name
        if not path.exists():
            r.fail(f"city/{sid}/{name} is missing")
            continue
        if path.stat().st_size > CITY_MAX_BYTES:
            r.fail(f"city/{sid}/{name} is {path.stat().st_size / 1e6:.1f} MB (limit 3 MB)")
        try:
            docs[name] = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            r.fail(f"city/{sid}/{name} is not valid JSON ({exc})")
    w = docs.get("world.json")
    if not isinstance(w, dict):
        return
    missing = [k for k in CITY_WORLD_KEYS if k not in w]
    if missing:
        r.fail(f"city/{sid}/world.json lacks keys {missing}")
        return
    sc = w["scope"]
    if not isinstance(sc, dict) or any(k not in sc for k in CITY_SCOPE_KEYS):
        r.fail(f"city/{sid}/world.json scope lacks keys {CITY_SCOPE_KEYS}")
        return
    if sc["id"] != sid:
        r.fail(f"city/{sid}: scope.id is {sc['id']!r}")
    if w["insets"] != []:
        r.fail(f"city/{sid}: insets must be empty")
    n = w["grid"]["cols"] * w["grid"]["rows"]
    for k in ("owner", "county", "elev", "elev_max", "water", "relief", "cover", "pop"):
        if len(w[k]) != n:
            r.fail(f"city/{sid}/world.json {k} has {len(w[k])} cells, the grid has {n}")
    for k, arr in w["pct"].items():
        if len(arr) != n:
            r.fail(f"city/{sid}/world.json pct.{k} has {len(arr)} cells, the grid has {n}")
    ns, nc = len(w["states"]), len(w["counties"])
    if any(not (-2 <= o < ns) for o in w["owner"]) or any(not (-1 <= c < nc) for c in w["county"]):
        r.fail(f"city/{sid}/world.json owner/county index out of range")
    if len(w["muni_cell"]) != nc:
        r.fail(f"city/{sid}/world.json muni_cell has {len(w['muni_cell'])} entries for {nc} counties")
    land = [i for i, o in enumerate(w["owner"]) if o >= 0]
    # population conservation
    total = sum(p for p in w["pop"] if p is not None)
    ine = (docs.get("nation.json") or {}).get("nation", {}).get("population")
    if not ine:
        r.fail(f"city/{sid}/nation.json has no population")
    elif abs(total - ine) > 0.001 * ine:
        r.fail(f"city/{sid}: population on the hexes {total:,.0f} differs from the sections' {ine:,.0f} by more than 0.1 %")
    else:
        r.ok(f"city/{sid}: population on the hexes {total:,.0f} = sections {ine:,.0f} ({total / ine - 1:+.4%})")
    # lens coverage
    for lens in (docs.get("lenses.json") or {}).get("lenses", []):
        vals = lens.get("values", [])
        if len(vals) != n:
            r.fail(f"city/{sid} lens {lens.get('id')}: {len(vals)} values for {n} cells")
            continue
        # INE lenses describe people: they are measured against the land hexes that hold population (parks and farmland
        # have none and stay without data); land-cover lenses against all land hexes.
        base = [i for i in land if w["pop"][i]] if str(lens.get("source", "")).startswith("ine") else land
        share = sum(1 for i in base if vals[i] is not None) / len(base) if base else 0
        msg = f"city/{sid} lens {lens.get('id')}: {share:.0%} of {len(base)} {'populated ' if base is not land else ''}land hexes have a value"
        if share < CITY_COVERAGE_FAIL:
            r.fail(msg)
        elif share < CITY_COVERAGE_WARN:
            r.warn(msg)
    check_city_match_and_centre(r, sid, w, scope_dir)
    # privacy: only names of sections, districts and municipalities
    names = [s.get("name") for s in w["states"]] + [c.get("name") for c in w["counties"]] + [b.get("name") for b in docs.get("cities.json") or []]
    bad = [x for x in names if not isinstance(x, str) or not NAME_OK.match(x) or any(p.search(x) for p in PRIVATE_VALUE)]
    if bad:
        r.fail(f"city/{sid}: {len(bad)} name(s) are not plain place names, e.g. {_sample(bad)}")
    if r.count("FAIL") == fails:
        r.ok(f"city/{sid}: {n} cells, {len(land)} land, {nc} sections, {ns} {sc['levels']['state']['many'].lower()}")


CITY_ADRH_WARN, CITY_ADRH_FAIL = 0.97, 0.90  # share of the scope's population living in sections that have an ADRH income
CITY_BOXES = {  # lon_min, lon_max, lat_min, lat_max
    "peninsula and Balearics": (-9.5, 4.5, 35.8, 43.9), "Canaries": (-18.3, -13.3, 27.5, 29.5), "Ceuta and Melilla": (-5.6, -2.8, 35.3, 35.95),
}
CITY_CENTRE_MAX_KM = 30.0


def _haversine_km(lon1, lat1, lon2, lat2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


def scope_centre(w: dict, proj: dict) -> tuple[float, float]:
    """lon/lat of the middle of a scope's grid (world.json width/height + the scope's projection.json)."""
    alb = Albers(*proj["main_albers"])
    return alb.inverse(w["width"] / 2 + proj["min_x"] - proj["margin"], proj["max_y"] + proj["margin"] - w["height"] / 2)


def check_city_match_and_centre(r: Report, sid: str, w: dict, scope_dir: Path) -> None:
    """ADRH match rate (older builds without the field are skipped) and the scope's place on the map of Spain."""
    rate = w["scope"].get("adrh_match")
    if rate is not None:
        msg = f"city/{sid}: ADRH income matched for {rate:.1%} of the population"
        if rate < CITY_ADRH_FAIL:
            r.fail(msg + f" (below {CITY_ADRH_FAIL:.0%})")
        elif rate < CITY_ADRH_WARN:
            r.warn(msg + f" (below {CITY_ADRH_WARN:.0%})")
    try:
        proj = json.loads((scope_dir / "projection.json").read_text(encoding="utf-8"))
        lon, lat = scope_centre(w, proj)
    except (OSError, ValueError, KeyError, TypeError):
        r.fail(f"city/{sid}: the scope centre cannot be computed from projection.json")
        return
    if not any(b[0] <= lon <= b[1] and b[2] <= lat <= b[3] for b in CITY_BOXES.values()):
        r.fail(f"city/{sid}: scope centre lon {lon:.3f}, lat {lat:.3f} is outside Spain's boxes")
        return
    try:  # distance to the city's place on the national map (skipped when the national files are not there)
        nat = scope_dir.parent.parent
        cities = json.loads((nat / "cities.json").read_text(encoding="utf-8"))
        npj = json.loads((nat / "projection.json").read_text(encoding="utf-8"))
        city = next(c for c in cities if c["id"] == w["scope"]["city"])
        nlon, nlat = MapProjection(npj["min_x"], npj["max_y"], npj["margin"]).inverse(city["x"], city["y"])
    except (OSError, ValueError, KeyError, StopIteration, TypeError):
        return
    km = _haversine_km(lon, lat, nlon, nlat)
    if km > CITY_CENTRE_MAX_KM:
        r.fail(f"city/{sid}: scope centre is {km:.0f} km from the city's position on the national map (limit {CITY_CENTRE_MAX_KM:.0f} km)")


def check_city_scopes(r: Report, web_dir: Path) -> None:
    """Runs only when web/data/city/ exists."""
    city = web_dir / "city"
    if not city.is_dir():
        return
    r.section("city scopes")
    try:
        index = json.loads((city / "index.json").read_text(encoding="utf-8"))["scopes"]
    except (OSError, ValueError, KeyError):
        r.fail("city/index.json is missing or has no scopes")
        return
    for e in index:
        if any(k not in e for k in ("id", "name", "kind", "city", "hex_km", "population", "title")):
            r.fail(f"city/index.json entry {e.get('id')!r} lacks fields")
        if not (city / str(e.get("id"))).is_dir():
            r.fail(f"city/index.json lists {e.get('id')!r} but its folder is missing")
        else:
            check_city_scope(r, city / e["id"])
    total = sum(p.stat().st_size for p in city.rglob("*") if p.is_file())
    r.ok(f"city/: {len(index)} scopes, {total / 1e6:.1f} MB in total")
    extra = sorted(p.name for p in city.iterdir() if p.is_dir() and p.name not in {e.get("id") for e in index})
    if extra:
        r.warn(f"city/ folders not in index.json: {extra}")


# ---------------------------------------------------------------- reporting


class Report:
    """Collects PASS/WARN/FAIL/NOTE lines and prints them as they come."""

    def __init__(self, quiet: bool = False):
        self.lines: list[tuple[str, str]] = []
        self.quiet = quiet

    def _add(self, level: str, msg: str) -> None:
        self.lines.append((level, msg))
        if not self.quiet:
            print(f"  {level:4}  {msg}")

    def ok(self, msg):
        self._add("PASS", msg)

    def warn(self, msg):
        self._add("WARN", msg)

    def fail(self, msg):
        self._add("FAIL", msg)

    def note(self, msg):
        self._add("NOTE", msg)

    def section(self, title):
        if not self.quiet:
            print(f"\n[{title}]")

    def count(self, level: str) -> int:
        return sum(1 for lv, _ in self.lines if lv == level)

    @property
    def failed(self) -> bool:
        return self.count("FAIL") > 0


def is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _sample(items, n=5) -> str:
    items = list(items)
    more = f" … (+{len(items) - n})" if len(items) > n else ""
    return ", ".join(str(x) for x in items[:n]) + more


def need_keys(r: Report, what: str, obj, keys) -> bool:
    """FAIL (once per object kind) if `obj` is not a dict or lacks keys. Returns True if all present."""
    if not isinstance(obj, dict):
        r.fail(f"{what}: expected an object, got {type(obj).__name__}")
        return False
    missing = [k for k in keys if k not in obj]
    if missing:
        r.fail(f"{what}: missing {', '.join(missing)}")
        return False
    return True


def check_cells(r: Report, name: str, arr, n: int, lo=None, hi=None, *, kind="int") -> bool:
    """A per-cell array: length n, every value an int (or number) within [lo, hi]."""
    if not isinstance(arr, list) or len(arr) != n:
        got = len(arr) if isinstance(arr, list) else type(arr).__name__
        r.fail(f"{name}: expected {n} values, got {got}")
        return False
    test = is_int if kind == "int" else is_num
    bad = [i for i, v in enumerate(arr) if not test(v) or (lo is not None and v < lo) or (hi is not None and v > hi)]
    if bad:
        r.fail(f"{name}: {len(bad)} values not {kind} in [{lo}, {hi}] (cells {_sample(bad)}; e.g. {arr[bad[0]]!r})")
        return False
    return True


# ---------------------------------------------------------------- validators


def check_world(r: Report, w) -> dict | None:
    """Validate world.json. Returns a small context (n, owner, states, ...) for the quality report, or None."""
    if not isinstance(w, dict):
        r.fail("world.json: not an object")
        return None
    fails_before = r.count("FAIL")
    if w.get("version") != 2:
        r.fail(f"world.json: version is {w.get('version')!r}, expected 2")
    attr = w.get("attribution")
    if not (isinstance(attr, list) and attr and all(isinstance(a, dict) and a.get("source") and a.get("license") for a in attr)):
        r.fail("world.json: attribution must list every data source with its licence")
    elif not any("EuroGeographics" in a["license"] for a in attr):
        r.fail("world.json: attribution lacks the EuroGeographics notice required by the GISCO terms")
    if not need_keys(r, "world.json grid", w.get("grid"), ["radius", "cols", "rows"]):
        return None
    g = w["grid"]
    if not (is_num(g["radius"]) and g["radius"] > 0 and is_int(g["cols"]) and is_int(g["rows"]) and g["cols"] > 0 and g["rows"] > 0):
        r.fail(f"world.json grid: bad values {g}")
        return None
    n = g["cols"] * g["rows"]
    need_keys(r, "world.json", w, ["country", "width", "height", "margin", "insets", "owner", "county", "elev", "water", "relief",
                                   "cover", "pct", "tables", "states", "counties", "forced", "rivers"])
    for k in ("width", "height", "margin"):
        if k in w and not is_num(w[k]):
            r.fail(f"world.json {k}: not a number ({w[k]!r})")

    states, counties = w.get("states") or [], w.get("counties") or []
    if len(states) != N_CCAA:
        r.fail(f"world.json states: expected {N_CCAA} autonomous communities, got {len(states)}")
    if not all(isinstance(s, dict) and {"fips", "abbr", "name"} <= s.keys() for s in states):
        r.fail("world.json states: every entry needs fips, abbr, name")
    if not all(isinstance(c, dict) and {"geoid", "name"} <= c.keys() for c in counties):
        r.fail("world.json counties: every entry needs geoid, name")

    ok = True
    owner = w.get("owner")
    ok &= check_cells(r, "world.json owner", owner, n, -2, len(states) - 1)
    ok &= check_cells(r, "world.json county", w.get("county"), n, -1, len(counties) - 1)
    ok &= check_cells(r, "world.json elev", w.get("elev"), n)
    if "elev_max" in w:
        ok &= check_cells(r, "world.json elev_max", w["elev_max"], n, 0, 9000)
    water = w.get("water")
    if "water" in w:
        ok &= check_cells(r, "world.json water", water, n, 0, 3)
    if "relief" in w:
        ok &= check_cells(r, "world.json relief", w["relief"], n, 0, 3)
    tables = w.get("tables")
    cover_ids = None
    if "tables" in w and need_keys(r, "world.json tables", tables, ["water", "relief", "cover"]):
        for t, ids in (("water", WATER_IDS), ("relief", RELIEF_IDS)):
            got = sorted(e.get("id") for e in tables[t] if isinstance(e, dict))
            if got != list(ids) or not all("name" in e for e in tables[t]):
                r.fail(f"world.json tables.{t}: expected ids {list(ids)} with names, got {got}")
        bad = [e for e in tables["cover"] if not isinstance(e, dict) or not is_int(e.get("id")) or not 0 <= e["id"] < len(COVER_KEYS)
               or e.get("key") != COVER_KEYS[e["id"]] or "name" not in e or (e["id"] and not COLOR.match(str(e.get("color", ""))))]
        if bad:
            r.fail(f"world.json tables.cover: {len(bad)} entries don't match the fixed cover ids/keys or lack name/color: {_sample(bad, 2)}")
        else:
            cover_ids = sorted(e["id"] for e in tables["cover"])
    if "cover" in w:
        # Every cover id used by a cell must be a row of tables.cover.
        ok &= check_cells(r, "world.json cover", w["cover"], n, 0, len(COVER_KEYS) - 1)
        if cover_ids is not None and isinstance(w["cover"], list):
            unknown = sorted({v for v in w["cover"] if v not in cover_ids})
            if unknown:
                r.fail(f"world.json cover: ids {unknown} are not in tables.cover {cover_ids}")
    owner_ok = isinstance(owner, list) and len(owner) == n and all(is_int(v) for v in owner)

    if owner_ok and isinstance(water, list) and len(water) == n:
        wet_land = sum(1 for o, wt in zip(owner, water) if o != -1 and wt != 0)
        dry_water = sum(1 for o, wt in zip(owner, water) if o == -1 and wt == 0)
        if wet_land or dry_water:
            r.warn(f"world.json: owner/water disagree on {wet_land} land cells with water>0 and {dry_water} water cells with water=0")
        if isinstance(w.get("relief"), list) and len(w["relief"]) == n:
            bad = sum(1 for wt, rl in zip(water, w["relief"]) if is_int(wt) and wt != 0 and rl != 0)
            if bad:
                r.fail(f"world.json relief: {bad} water cells have relief != 0")
        elev = w.get("elev")
        if isinstance(elev, list) and len(elev) == n:
            high = [i for i, (wt, e) in enumerate(zip(water, elev)) if is_int(wt) and wt != 0 and is_num(e) and e > 0]
            if high:
                r.fail(f"world.json elev: {len(high)} water cells have elev > 0 (water elev is mean depth, <= 0; cells {_sample(high)})")

    pct = w.get("pct")
    if "pct" in w and need_keys(r, "world.json pct", pct, PCT_KEYS):
        if "pasture" in pct:
            r.fail("world.json pct: has a pasture key (pastures are inside grass in the Spain map)")
        for k in PCT_KEYS:
            ok &= check_cells(r, f"world.json pct.{k}", pct[k], n, 0, 100)
        if owner_ok and all(isinstance(pct[k], list) and len(pct[k]) == n for k in PCT_KEYS):
            over = [i for i in range(n) if sum(pct[k][i] or 0 for k in PCT_KEYS if is_num(pct[k][i])) > 100 + len(PCT_KEYS)]
            outside = [i for i in range(n) if owner[i] < 0 and any(pct[k][i] for k in PCT_KEYS)]
            if over:
                r.fail(f"world.json pct: {len(over)} cells sum above 100% (cells {_sample(over)})")
            if outside:
                r.fail(f"world.json pct: {len(outside)} non-Spanish cells have non-zero land-cover shares (must be 0)")

    W, H = w.get("width"), w.get("height")
    insets = w.get("insets")
    if isinstance(insets, list) and is_num(W) and is_num(H):
        bad = [i for i in insets if not isinstance(i, dict) or not {"name", "x0", "y0", "x1", "y1"} <= i.keys()
               or not all(is_num(i[k]) for k in ("x0", "y0", "x1", "y1")) or not (0 <= i["x0"] < i["x1"] <= W and 0 <= i["y0"] < i["y1"] <= H)]
        if bad:
            r.fail(f"world.json insets: {len(bad)} malformed or outside the map ({W} x {H}): {_sample(bad, 2)}")
    elif "insets" in w:
        r.fail("world.json insets: expected a list")

    forced = w.get("forced")
    if isinstance(forced, list):
        bad = [f for f in forced if not isinstance(f, dict) or not {"cell", "name", "reason"} <= f.keys() or not is_int(f["cell"])
               or not 0 <= f["cell"] < n or (owner_ok and (owner[f["cell"]] < 0 or (isinstance(water, list) and water[f["cell"]] != 0)))]
        if bad:
            r.fail(f"world.json forced: {len(bad)} entries malformed or not Spanish land: {_sample(bad, 2)}")
    elif "forced" in w:
        r.fail("world.json forced: expected a list")

    rivers = w.get("rivers") or []
    bad = [i for i, rv in enumerate(rivers) if not isinstance(rv, dict) or not {"name", "rank", "pts"} <= rv.keys()
           or not is_int(rv["rank"]) or not isinstance(rv["pts"], list) or len(rv["pts"]) < 4 or len(rv["pts"]) % 2 or not all(is_num(v) for v in rv["pts"])]
    if bad:
        r.fail(f"world.json rivers: {len(bad)} malformed (need name, int rank, pts=[x0,y0,x1,y1,...])")

    if ok and r.count("FAIL") == fails_before:
        r.ok(f"world.json: {g['cols']}x{g['rows']} grid, {len(states)} CCAA, {len(counties)} municipalities, {len(rivers)} rivers")
    return {
        "n": n, "grid": g, "owner": owner if owner_ok else None, "water": water if isinstance(water, list) and len(water) == n else None,
        "states": states, "counties": counties, "forced": forced if isinstance(forced, list) else [],
        "width": w.get("width"), "height": w.get("height"), "rivers": rivers,
    }


def check_sources(r: Report, doc) -> set | None:
    if not isinstance(doc, list):
        r.fail("sources.json: expected a list")
        return None
    fails_before = r.count("FAIL")
    keys = ["id", "title", "publisher", "homepage", "license", "description", "used_for", "vintage", "files"]
    ids = set()
    for s in doc:
        what = f"sources.json {s.get('id') if isinstance(s, dict) else s!r}"
        if not need_keys(r, what, s, keys):
            continue
        if s["id"] in ids:
            r.fail(f"{what}: duplicate id")
        ids.add(s["id"])
        bad = [f for f in s["files"] if not isinstance(f, dict) or not {"file", "url", "retrieved", "sha256", "bytes"} <= f.keys()]
        if bad:
            r.fail(f"{what}: {len(bad)} file entries lack file/url/retrieved/sha256/bytes")
        if not s["files"]:
            r.warn(f"{what}: no files cited (not fetched yet?)")
    if r.count("FAIL") == fails_before:
        r.ok(f"sources.json: {len(doc)} sources, {sum(len(s['files']) for s in doc if isinstance(s, dict))} files")
    return ids


CITY_KEYS = ["id", "name", "full", "states", "metro", "capital", "x", "y", "cell", "population", "employed", "yields",
             "jobs", "gdp", "gdp_year", "growth", "growth_years", "counties", "footprint", "ranks", "peers"]
YIELD_KEYS = ["food", "production", "gold", "science", "culture"]
RANK_KEYS = ["population", "gdp", "gdp_per_capita", "growth", *YIELD_KEYS]
PCT_FIELDS = ["jobs_coverage", "unemployment", "rent_burden"]


def _is_f0(nat) -> bool:
    return isinstance(nat, dict) and nat.get("year") is None


def check_ranks(r: Report, what: str, rows: list, keys=RANK_KEYS) -> None:
    """Every row's ranks: null or a permutation of 1..N over the non-null rows, per key."""
    for key in keys:
        got = [row["ranks"].get(key) if isinstance(row.get("ranks"), dict) else None for row in rows]
        have = sorted(v for v in got if v is not None)
        if have != list(range(1, len(have) + 1)):
            r.fail(f"{what} ranks.{key}: not a permutation of 1..{len(have)}")


def check_pct_fields(r: Report, what: str, rows: list) -> None:
    for row in rows:
        for k in PCT_FIELDS:
            v = row.get(k)
            if v is not None and (not is_num(v) or not 0 <= v <= 1):
                r.fail(f"{what} {row.get('id', row.get('fips'))}: {k} {v!r} outside 0..1")


def check_cities(r: Report, cities, nat=None, world=None, interim_dir: Path | None = None) -> None:
    if not isinstance(cities, list):
        r.fail("cities.json: expected a list")
        return
    if not cities:
        if _is_f0(nat):
            r.ok("cities.json: 0 cities (F0: none yet)")
        else:
            r.fail("cities.json: empty although nation.json has statistics")
        return
    fails_before = r.count("FAIL")
    if not all(isinstance(c, dict) and need_keys(r, f"cities.json {c.get('id') if isinstance(c, dict) else '?'}", c, CITY_KEYS) for c in cities):
        return
    ids = [c["id"] for c in cities]
    if len(set(ids)) != len(ids):
        r.fail("cities.json: duplicate ids")
    pops = [c["population"] for c in cities]
    if pops != sorted(pops, reverse=True):
        r.fail("cities.json: not sorted by population, descending")
    cells = [c["cell"] for c in cities]
    dup = [k for k, n in Counter(cells).items() if n > 1]
    if dup:
        r.fail(f"cities.json: {len(dup)} cells shared by several cities, e.g. {_sample(dup)}")
    owner = (world or {}).get("owner")
    if owner:
        bad = [c["id"] for c in cities if not (isinstance(c["cell"], int) and 0 <= c["cell"] < len(owner) and owner[c["cell"]] >= 0)]
        if bad:
            r.fail(f"cities.json: city cell is not a Spanish land cell: {_sample(bad)}")
        off = [c["id"] for c in cities if any(not (isinstance(k, int) and 0 <= k < len(owner) and owner[k] >= 0) for k in c["footprint"])]
        if off:
            r.fail(f"cities.json: footprint outside Spanish land cells: {_sample(off)}")
    empty = [c["id"] for c in cities if not c["footprint"] or c["cell"] not in c["footprint"]]
    if empty:
        r.fail(f"cities.json: empty footprint or footprint without the city's own cell: {_sample(empty)}")
    if any(not c["counties"] for c in cities):
        r.fail("cities.json: a city without member municipalities")
    check_ranks(r, "cities.json", cities)
    check_pct_fields(r, "cities.json", cities)
    idset = set(ids)
    if any(len(c["peers"]) != min(5, len(cities) - 1) or c["id"] in c["peers"] or not set(c["peers"]) <= idset for c in cities):
        r.fail("cities.json: peers must be 5 other city ids")
    capitals = [c for c in cities if c["capital"]]
    if len(capitals) != 1:
        r.fail(f"cities.json: expected exactly one capital, got {len(capitals)}")
    elif capitals[0]["ranks"].get("population") != 1:
        r.fail(f"cities.json: the capital ({capitals[0]['name']}) is not first by population")
    if isinstance(nat, dict) and isinstance(nat.get("nation"), dict):
        n = nat["nation"]
        if len({tuple(c["growth_years"]) for c in cities}) != 1 or cities[0]["growth_years"][-1] != nat.get("year"):
            r.fail(f"cities.json: growth_years must be identical and end at nation.json year {nat.get('year')}")
        total = sum(c["gdp"] or 0 for c in cities)
        if n.get("gdp") and total >= n["gdp"]:
            r.fail(f"cities.json: city GDP total {total:,.0f} is not below the national GDP {n['gdp']:,.0f}")
        if n.get("population") and sum(pops) > n["population"]:
            r.fail("cities.json: city populations add up to more than the nation")
    ine_p = Path(interim_dir) / "ine.json" if interim_dir else None
    if ine_p and ine_p.exists():
        ine_m = json.loads(ine_p.read_text())["data"]["municipalities"]
        low = [c["id"] for c in cities if c.get("core") and c["population"] < (ine_m.get(c["core"]) or {}).get("pop", 0)]
        if low:
            r.fail(f"cities.json: population below the core municipality's: {_sample(low)}")
    else:
        r.note("cities.json: ine interim missing, core-municipality population not checked")
    if r.count("FAIL") == fails_before:
        r.ok(f"cities.json: {len(cities)} cities, unique land cells, ranks consistent")


def check_states(r: Report, states, nat=None) -> None:
    if not isinstance(states, list):
        r.fail("states.json: expected a list")
        return
    fails_before = r.count("FAIL")
    if len(states) != N_CCAA:
        r.fail(f"states.json: expected {N_CCAA} autonomous communities, got {len(states)}")
    if not all(isinstance(s, dict) and need_keys(r, f"states.json {s.get('abbr') if isinstance(s, dict) else '?'}", s,
                                                 ["fips", "abbr", "name", "population", "employed", "jobs", "yields", "gdp", "growth", "ranks"]) for s in states):
        return
    if len({s["fips"] for s in states}) != len(states):
        r.fail("states.json: duplicate fips")
    check_ranks(r, "states.json", states, ["population", "gdp", "gdp_per_capita", "growth", *YIELD_KEYS])
    check_pct_fields(r, "states.json", states)
    if isinstance(nat, dict) and isinstance(nat.get("nation"), dict):
        n = nat["nation"]
        if n.get("population") is not None and sum(s["population"] or 0 for s in states) != n["population"]:
            r.fail("states.json: CCAA populations do not add up to nation.json population")
        if n.get("gdp") and sum(s["gdp"] or 0 for s in states) > n["gdp"] * 1.0001:
            r.fail("states.json: CCAA GDP adds up to more than the national GDP")
        if any(s["growth_years"] != n.get("growth_years") for s in states):
            r.fail("states.json: growth_years differ from nation.json")
    if r.count("FAIL") == fails_before:
        r.ok(f"states.json: {len(states)} CCAA, ranks consistent")


def check_nation(r: Report, nat) -> None:
    if not need_keys(r, "nation.json", nat, ["vintage", "year", "gdp_vintage", "nation", "yields", "industries"]):
        return
    fails_before = r.count("FAIL")
    if not need_keys(r, "nation.json nation", nat["nation"], ["name", "population", "employed", "gdp", "yields", "jobs", "growth", "growth_years"]):
        return
    if not isinstance(nat["yields"], list) or not isinstance(nat["industries"], dict):
        r.fail("nation.json: yields must be a list and industries an object")
    for k in ("population", "employed", "gdp", "growth"):
        v = nat["nation"][k]
        if v is not None and not is_num(v):
            r.fail(f"nation.json nation.{k}: expected a number or null, got {v!r}")
    if not _is_f0(nat):
        gy = nat["nation"]["growth_years"]
        if not (isinstance(gy, list) and len(gy) == 2 and gy[-1] == nat["year"]):
            r.fail(f"nation.json: growth_years {gy!r} must end at year {nat['year']}")
        if nat["nation"]["gdp"] is None or nat["nation"]["population"] is None or nat["nation"]["growth"] is None:
            r.fail("nation.json: population, gdp and growth are required once statistics exist")
        if isinstance(nat["industries"], dict) and isinstance(nat["nation"]["jobs"], dict) and set(nat["industries"]) != set(nat["nation"]["jobs"]):
            r.fail("nation.json: industries and nation.jobs have different keys")
        if not nat.get("attribution"):
            r.fail("nation.json: attribution missing")
    if r.count("FAIL") == fails_before:
        r.ok(f"nation.json: {nat['nation']['name']} ({nat['vintage']})")


def _pct01(v) -> bool:
    return v is None or (is_num(v) and 0 <= v <= 1)


def check_land(r: Report, what: str, rows: list) -> None:
    bad = [x for x in rows if x.get("land") is not None and not (
        isinstance(x["land"], dict) and set(x["land"]) == {"forest", "crop", "developed"}
        and all(_pct01(v) and v is not None for v in x["land"].values()) and sum(x["land"].values()) <= 1 + 1e-3)]
    if bad:
        r.fail(f"{what}: land shares must be {{forest, crop, developed}} in 0..1 summing to at most 1")
    elif rows and all("land" in x for x in rows):
        r.ok(f"{what}: land shares in range")


COUNTIES_COLUMNS = ["geoid", "name", "state", "province", "population", "land_km2", "density", "growth", "age_mean",
                    "elderly", "foreign", "household", "income", "poverty", "higher_education", "auf", "cell",
                    "dwellings_total", "non_primary", "tourist", "born_abroad", "immigration", "crime_rate"]
COUNTIES_PCT = ["growth", "elderly", "foreign", "poverty", "higher_education", "non_primary", "tourist", "born_abroad"]


def check_counties_file(r: Report, doc, world=None, cities=None) -> None:
    if not isinstance(doc, dict) or not need_keys(r, "counties.json", doc, ["vintage", "fields", "columns", "rows", "attribution"]):
        return
    cols, rows = doc["columns"], doc["rows"]
    if cols != COUNTIES_COLUMNS or [f.get("key") for f in doc["fields"]] != cols:
        r.fail("counties.json: columns/fields do not match the contract")
        return
    if any(not isinstance(x, list) or len(x) != len(cols) for x in rows):
        r.fail("counties.json: a row does not have one value per column")
        return
    if world is not None:
        if [x[0] for x in rows] != [c["geoid"] for c in world["counties"]]:
            r.fail("counties.json: rows are not the world.json counties in order")
            return
        n_cells = len(world["owner"])
        if any(x[16] is not None and not (is_int(x[16]) and 0 <= x[16] < n_cells) for x in rows):
            r.fail("counties.json: cell outside the grid")
    if any(not (isinstance(x[0], str) and len(x[0]) == 5 and x[0].isdigit()) for x in rows):
        r.fail("counties.json: geoid must be a 5-digit string")
    for k in COUNTIES_PCT:
        j = cols.index(k)
        lo = -1 if k == "growth" else 0
        if any(x[j] is not None and not (is_num(x[j]) and lo <= x[j] <= (1 if k != "growth" else 100)) for x in rows):
            r.fail(f"counties.json: {k} out of range")
    if cities is not None:
        ids = {c["id"] for c in cities}
        if any(x[15] is not None and x[15] not in ids for x in rows):
            r.fail("counties.json: auf is not a cities.json id")
    pj = cols.index("population")
    if any(x[pj] is not None and (not is_int(x[pj]) or x[pj] < 0) for x in rows):
        r.fail("counties.json: population must be a non-negative integer or null")
    r.ok(f"counties.json: {len(rows)} rows x {len(cols)} columns, pct in range")


def check_districts_file(r: Report, doc, cities=None, nation=None) -> None:
    if not isinstance(doc, dict) or not need_keys(r, "districts.json", doc, ["version", "note", "rule", "catalog", "cities", "attribution"]):
        return
    ids = [c.get("id") for c in doc["catalog"]]
    if ids != list("abcdefghijklmnopqrs"):
        r.fail("districts.json: catalog must have one entry per CNAE section a..s")
        return
    min_lq = doc["rule"].get("min_lq", 1.25)
    bad = []
    for cid, row in doc["cities"].items():
        ds = (row or {}).get("districts", [])
        if len(ds) > doc["rule"].get("max_per_city", 5) or any(d["id"] not in ids or d["lq"] < min_lq for d in ds):
            bad.append(cid)
        elif [d["strength"] for d in ds] != sorted((d["strength"] for d in ds), reverse=True):
            bad.append(cid)
        elif row.get("badge") and (not ds or row["badge"]["district"] != ds[0]["id"]):
            bad.append(cid)
        elif not row.get("badge") and ds:
            bad.append(cid)
    if bad:
        r.fail(f"districts.json: {len(bad)} cities break the rule (LQ >= {min_lq}, <= max, sorted, badge = top): {_sample(bad)}")
    if cities is not None and set(doc["cities"]) != {c["id"] for c in cities}:
        r.fail("districts.json: cities do not match cities.json")
    elif not bad:
        r.ok(f"districts.json: {len(doc['cities'])} cities, every LQ >= {min_lq}")


def check_citizens_file(r: Report, doc, cities=None) -> None:
    if not isinstance(doc, dict) or not need_keys(r, "citizens.json", doc, ["version", "rows", "bases", "groups", "national", "cities", "attribution"]):
        return
    bad = []
    rows = [("national", doc["national"])] + list(doc["cities"].items())
    for cid, row in rows:
        for dist, spec in (row or {}).items():
            if dist not in doc["groups"] or spec is None:
                continue
            keys = [g["key"] for g in doc["groups"][dist]]
            if set(spec["shares"]) != set(keys) or abs(sum(spec["shares"].values()) - 1) > 1e-3 or not all(_pct01(v) for v in spec["shares"].values()) \
                    or sum(spec["counts"].values()) != spec["total"] or sum(spec["figures"].values()) != doc["figures"][dist] \
                    or spec["base"] != doc["bases"][dist]:
                bad.append(f"{cid}/{dist}")
    if bad:
        r.fail(f"citizens.json: {len(bad)} distributions with shares not summing to 1, counts not adding up or a wrong base: {_sample(bad)}")
    if cities is not None and set(doc["cities"]) != {c["id"] for c in cities}:
        r.fail("citizens.json: cities do not match cities.json")
    elif not bad:
        r.ok(f"citizens.json: {len(doc['cities'])} cities, 3 distributions each, shares sum to 1")


def check_economy_conservation(r: Report, interim_dir: Path) -> None:
    """Imputed GDP adds up, per province, to the published provincial GDP (from the _economy_stats interim)."""
    p = Path(interim_dir) / "_economy_stats.json"
    if not p.exists():
        r.note("_economy_stats: missing (economy not built), GDP conservation not checked")
        return
    st = json.loads(p.read_text())["data"]
    bad = [f"{k} {v['imputed']:.0f} vs {v['gdp']:.0f}" for k, v in sorted(st["provinces"].items())
           if abs(v["imputed"] - v["gdp"]) > 1e-6 * v["gdp"]]
    (r.fail if bad else r.ok)(f"imputed GDP conserved in {len(st['provinces'])} provinces (1e-6)" + (f": {', '.join(bad[:5])}" if bad else ""))
    if st["cities_gdp"] >= st["national_gdp"]:
        r.fail(f"city GDP total {st['cities_gdp']:,.0f} is not below the national GDP {st['national_gdp']:,.0f}")


# ---------------------------------------------------------------- lenses


def check_lenses(r: Report, doc, ctx: dict | None, source_ids: set | None = None) -> None:
    if not need_keys(r, "lenses.json", doc, ["vintage", "groups", "lenses"]):
        return
    fails_before = r.count("FAIL")
    groups = {g.get("id") for g in doc["groups"] if isinstance(g, dict) and "name" in g}
    if len(groups) != len(doc["groups"]):
        r.fail("lenses.json groups: every group needs id and name")
    ids = Counter(l.get("id") for l in doc["lenses"] if isinstance(l, dict))
    if any(k > 1 for k in ids.values()):
        r.fail(f"lenses.json: duplicate lens ids {[i for i, k in ids.items() if k > 1]}")
    keys = ["id", "group", "name", "icon", "emoji", "unit", "format", "scale", "domain", "ramp", "higher_is", "source", "description", "values"]
    spanish = sum(1 for o in ctx["owner"] if o >= 0) if ctx and ctx["owner"] else 0
    for lens in doc["lenses"]:
        what = f"lenses.json {lens.get('id') if isinstance(lens, dict) else lens!r}"
        if not need_keys(r, what, lens, keys):
            continue
        if lens["group"] not in groups:
            r.fail(f"{what}: unknown group {lens['group']!r}")
        if lens["format"] not in LENS_FORMATS or lens["scale"] not in LENS_SCALES or lens["higher_is"] not in HIGHER_IS:
            r.fail(f"{what}: format/scale/higher_is must be one of {sorted(LENS_FORMATS)}/{sorted(LENS_SCALES)}/{sorted(HIGHER_IS)}")
        d = lens["domain"]
        if not (isinstance(d, list) and len(d) == 2 and all(is_num(v) for v in d) and d[0] < d[1]) or (lens["scale"] == "log" and d[0] <= 0):
            r.fail(f"{what}: domain must be [lo, hi] with lo < hi (lo > 0 for log): {d!r}")
        if not (isinstance(lens["ramp"], list) and len(lens["ramp"]) >= 2 and all(COLOR.match(str(c)) for c in lens["ramp"])):
            r.fail(f"{what}: ramp must be at least 2 #hex colours")
        if source_ids is not None and lens["source"] not in source_ids:
            r.warn(f"{what}: source {lens['source']!r} is not in sources.json")
        if "note" in lens and not (lens["note"] is None or isinstance(lens["note"], str)):
            r.fail(f"{what}: note must be a string or null")
        vals = lens["values"]
        if ctx is None:
            continue
        if not isinstance(vals, list) or len(vals) != ctx["n"]:
            r.fail(f"{what}: values must have {ctx['n']} entries, got {len(vals) if isinstance(vals, list) else type(vals).__name__}")
            continue
        bad = [i for i, v in enumerate(vals) if v is not None and not is_num(v)]
        if bad:
            r.fail(f"{what}: {len(bad)} values are neither number nor null (cells {_sample(bad)})")
        if ctx["owner"]:
            off = [i for i, v in enumerate(vals) if v is not None and ctx["owner"][i] < 0]
            if off:
                r.fail(f"{what}: {len(off)} values on non-Spanish cells (must be null)")
        if lens["format"] == "pct" and lens["id"] not in CHANGE_LENSES and any(is_num(v) and not -1e-9 <= v <= 1 + 1e-9 for v in vals):
            r.fail(f"{what}: format pct but some values are outside 0..1 (pct lenses are fractions)")
        if lens["id"] in CHANGE_LENSES and any(is_num(v) and v < -1 for v in vals):
            r.fail(f"{what}: change below -100 %")
        if lens["id"] in NEW_LENS_IDS:
            if any(is_num(v) and not math.isfinite(v) for v in vals):
                r.fail(f"{what}: non-finite value")
            if any(is_num(v) and v < 0 for v in vals) and lens["id"] not in CHANGE_LENSES:
                r.fail(f"{what}: negative value")
            k = sum(1 for v in vals if v is not None)
            r.note(f"new lens {lens['id']}: coverage {k} hexes" + (f" ({k / spanish:.1%} of {spanish})" if spanish else ""))
        filled = sum(1 for v in vals if v is not None)
        r.note(f"lens {lens['id']}: {filled} non-null hexes ({filled / spanish:.1%} of {spanish} Spanish land hexes)" if spanish else f"lens {lens['id']}: {filled} non-null hexes")
    if r.count("FAIL") == fails_before:
        r.ok(f"lenses.json: {len(doc['lenses'])} lenses in {len(groups)} groups ({doc['vintage']})")


def check_conservation(r: Report, interim_dir: Path, nation=None) -> None:
    """People on the hexes (written by the lenses builder as _lens_stats) against the municipal totals."""
    p = Path(interim_dir) / "_lens_stats.json"
    if not p.exists():
        r.note("_lens_stats: missing (lenses not built), population conservation not checked")
        return
    st = json.loads(p.read_text())["data"]
    total, hexes = st["muni_pop"], st["hex_pop"]
    dev = abs(hexes - total) / total if total else 1.0
    (r.ok if dev <= NATION_TOLERANCE else r.fail)(f"population conservation: hexes {hexes:,.0f} vs municipalities {total:,.0f} ({dev:.3%}, limit {NATION_TOLERANCE:.1%})")
    bad, worst = [], ("", 0.0)
    for code, c in sorted(st["per_ccaa"].items()):
        d = abs(c["hex_pop"] - c["muni_pop"]) / c["muni_pop"] if c["muni_pop"] else (0.0 if not c["hex_pop"] else 1.0)
        if d > worst[1]:
            worst = (code, d)
        if d > CCAA_TOLERANCE:
            bad.append(f"{code} {d:.2%}")
    (r.fail if bad else r.ok)(f"population per CCAA within {CCAA_TOLERANCE:.0%}" + (f": {', '.join(bad)}" if bad else f" ({len(st['per_ccaa'])} CCAA)"))
    r.note(f"worst CCAA population drift: {worst[0]} {worst[1]:.2%} (border municipalities split by area)")
    npop = (nation or {}).get("nation", {}).get("population") if isinstance(nation, dict) else None
    if npop is not None and abs(npop - total) > 0.5:
        r.fail(f"nation.json population {npop:,} differs from the municipal total {total:,.0f}")


# ---------------------------------------------------------------- data quality


def quality_map(r: Report, ctx: dict) -> None:
    owner, water = ctx["owner"], ctx["water"]
    if owner is None:
        return
    spanish = [i for i, o in enumerate(owner) if o >= 0]
    r.ok(f"{len(spanish)} Spanish land hexes, {sum(1 for o in owner if o == -2)} foreign, {sum(1 for o in owner if o == -1)} water")
    per = Counter(owner[i] for i in spanish)
    names = [s.get("abbr", "?") if isinstance(s, dict) else "?" for s in ctx["states"]]
    r.note("hexes per CCAA: " + ", ".join(f"{names[k]} {per[k]}" for k in sorted(per) if k < len(names)))
    empty = [names[k] for k in range(len(names)) if not per[k]]
    if empty:
        r.fail(f"CCAA without any hex: {', '.join(empty)}")
    forced = ctx["forced"]
    r.ok(f"{len(forced)} forced land cells" + (": " + ", ".join(str(f.get("name")) for f in forced) if forced else ""))
    if water is not None:
        bad = [i for i in spanish if water[i] != 0]
        if bad:
            r.fail(f"{len(bad)} Spanish hexes are not land (cells {_sample(bad)})")


def quality_rivers(r: Report, ctx: dict) -> None:
    W, H = ctx["width"], ctx["height"]
    if not (is_num(W) and is_num(H)):
        return
    outside_all, stray = [], 0
    for rv in ctx["rivers"]:
        pts = rv.get("pts") if isinstance(rv, dict) else None
        if not isinstance(pts, list):
            continue
        inside = [0 <= pts[j] <= W and 0 <= pts[j + 1] <= H for j in range(0, len(pts) - 1, 2)]
        if not any(inside):
            outside_all.append(rv.get("name"))
        stray += inside.count(False)
    if outside_all:
        r.warn(f"rivers entirely outside the map: {len(outside_all)} ({_sample(outside_all)})")
    elif stray:
        r.warn(f"rivers: {stray} vertices outside the map (contract says clipped)")
    else:
        r.ok(f"rivers: all {len(ctx['rivers'])} inside the map")


TRAFFIC_KEYS = {"enplanements", "enplanements_prev", "cargo_lbs", "imports", "exports", "domestic", "foreign", "tons_total"}


def _attr_ok(a) -> bool:
    return isinstance(a, list) and bool(a) and all(
        isinstance(x, dict) and x.get("data") and x.get("source") and x.get("license") for x in a)


def check_map_layers(r: Report, docs: dict, world) -> None:
    """Shape checks for infrastructure.json, resources.json and wonders.json against world.json."""
    if not isinstance(world, dict) or not isinstance(world.get("owner"), list) or not isinstance(world.get("grid"), dict):
        r.note("map layers: world.json unusable, skipped")
        return
    owner, water, g = world["owner"], world.get("water") or [], world["grid"]
    n = len(owner)
    cols, rad = g["cols"], g["radius"]
    insets = world.get("insets") or []

    def land(c) -> bool:
        return is_int(c) and 0 <= c < n and owner[c] >= 0 and (not water or water[c] == 0)

    def frame(c):
        col, row = c % cols, c // cols
        x, y = 3 ** 0.5 * rad * (col + 0.5 * (row & 1)), 1.5 * rad * row
        return next((i["name"] for i in insets if i["x0"] <= x <= i["x1"] and i["y0"] <= y <= i["y1"]), None)

    def traffic(obj, path="") -> list[str]:
        if isinstance(obj, dict):
            return [path + k for k in obj if k in TRAFFIC_KEYS] + [t for k, v in obj.items() for t in traffic(v, path + k + ".")]
        if isinstance(obj, list):
            return [t for v in obj[:400] for t in traffic(v, path)]
        return []

    inf = docs.get("infrastructure.json")
    if inf is not None:
        before = r.count("FAIL")
        if not need_keys(r, "infrastructure.json", inf, ["roads", "rail", "ports", "airports", "attribution", "vintage"]):
            return
        if not _attr_ok(inf["attribution"]):
            r.fail("infrastructure.json: attribution must be [{data, source, license}]")
        for k in ("roads", "rail"):
            links = inf[k]
            badf = [l for l in links if not (isinstance(l, list) and len(l) >= 3 and is_int(l[0]) and is_int(l[1]) and 0 <= l[0] < n and 0 <= l[1] < n
                                             and l[0] != l[1] and l[2] in (0, 1) and (land(l[0]) or land(l[1])) and -2 not in (owner[l[0]], owner[l[1]]))]
            if badf:
                r.fail(f"infrastructure.json {k}: {len(badf)} links are not [cell, cell, 0|1] with one end on Spanish land and none on foreign land (e.g. {_sample(badf, 3)})")
            cross = sum(1 for l in links if isinstance(l, list) and len(l) >= 2 and is_int(l[0]) and is_int(l[1])
                        and 0 <= l[0] < n and 0 <= l[1] < n and frame(l[0]) != frame(l[1]))
            if cross:
                r.fail(f"infrastructure.json {k}: {cross} links cross an inset frame")
        for k in ("ports", "airports"):
            badp = [p.get("id") for p in inf[k] if not land(p.get("cell")) or not p.get("name")]
            if badp:
                r.fail(f"infrastructure.json {k}: {len(badp)} sites without a Spanish land cell ({_sample(badp)})")
        if any(p.get("tons") is not None for p in inf["ports"]):
            r.fail("infrastructure.json: port tons must be null (Puertos del Estado is not used)")
        badpax = [a.get("id") for a in inf["airports"]
                  if not (a.get("passengers") is None or (is_int(a["passengers"]) and a["passengers"] > 0 and is_int(a.get("passengers_year"))))]
        if badpax:
            r.fail(f"infrastructure.json airports: passengers must be an int > 0 (or null) with passengers_year ({_sample(badpax)})")
        if traffic(inf):
            r.fail(f"infrastructure.json: traffic fields present: {_sample(traffic(inf))}")
        if r.count("FAIL") == before:
            r.ok(f"infrastructure.json: {len(inf['roads'])} road links, {len(inf['rail'])} rail links, {len(inf['ports'])} ports, "
                 f"{len(inf['airports'])} airports; 0 cross an inset frame")

    res = docs.get("resources.json")
    if res is not None:
        before = r.count("FAIL")
        if not _attr_ok(res.get("attribution")):
            r.fail("resources.json: attribution must be [{data, source, license}]")
        bad = [i.get("name") for i in res.get("items") or [] if not land(i.get("cell"))
               or (i.get("value") is not None and not (is_num(i["value"]) and i["value"] > 0))]
        if bad:
            r.fail(f"resources.json: {len(bad)} items without a Spanish land cell or with a non-positive value ({_sample(bad)})")
        if traffic(res):
            r.fail("resources.json: traffic fields present")
        if r.count("FAIL") == before:
            r.ok(f"resources.json: {len(res.get('items') or [])} items on Spanish land cells, attribution present")

    wo = docs.get("wonders.json")
    if wo is not None:
        before = r.count("FAIL")
        if not _attr_ok(wo.get("attribution")):
            r.fail("wonders.json: attribution must be [{data, source, license}]")
        bad = [w.get("id") for w in wo.get("wonders") or [] if not land(w.get("cell"))]
        if bad:
            r.fail(f"wonders.json: {len(bad)} sites without a Spanish land cell ({_sample(bad)})")
        if r.count("FAIL") == before:
            r.ok(f"wonders.json: {len(wo.get('wonders') or [])} sites on Spanish land cells, attribution present")


# ---------------------------------------------------------------- entry point


# ---------------------------------------------------------------- transparency files (privacy + shape)

PRIVATE_KEY = re.compile(r"winner|adjudicatari|ganador|\bnif\b|\bdni\b|\bnie\b|cif|titulo|title|body|resumen|texto", re.I)
PRIVATE_VALUE = [re.compile(p) for p in (
    r"(?<![0-9A-Za-z])\d{8}[A-Z](?![0-9A-Za-z])",            # DNI
    r"(?<![0-9A-Za-z])[XYZ]\d{7}[A-Z](?![0-9A-Za-z])",        # NIE
    r"(?<![0-9A-Za-z])[A-HJNP-SUVW]\d{7}[0-9A-J](?![0-9A-Za-z])",  # NIF of an entity
)]


def privacy_violations(doc, path: str = "") -> list[str]:
    """Keys named like a winner / tax id / title / body and strings that look like a DNI, NIE or NIF, anywhere in `doc`."""
    out: list[str] = []
    if isinstance(doc, dict):
        for k, v in doc.items():
            if isinstance(k, str) and PRIVATE_KEY.search(k):
                out.append(f"{path}/{k}: key")
            out += privacy_violations(v, f"{path}/{k}")
    elif isinstance(doc, list):
        for i, v in enumerate(doc):
            out += privacy_violations(v, f"{path}[{i}]")
    elif isinstance(doc, str):
        if any(p.search(doc) for p in PRIVATE_VALUE):
            out.append(f"{path}: id-like string")
    return out


def _attrs_ok(doc) -> bool:
    return _attr_ok(doc.get("attribution"))


def check_transparency_files(r: Report, safety, boja, junta, counties=None, cities=None) -> None:
    for name, doc, keys in (("safety.json", safety, ["years", "typologies", "national", "ccaa", "provinces", "municipalities", "note", "attribution"]),
                            ("boja.json", boja, ["years", "sections", "by_year_section", "by_organisation", "note", "attribution"]),
                            ("contracts_junta.json", junta, ["years", "provinces", "organs", "amount_basis", "note", "attribution"])):
        if doc is None:
            continue
        if not need_keys(r, name, doc, keys):
            continue
        if not _attrs_ok(doc):
            r.fail(f"{name}: attribution must be a non-empty list of {{data, source, license}}")
        bad = privacy_violations(doc)
        (r.fail if bad else r.ok)(f"{name}: privacy structure " + (f"violations {_sample(bad)}" if bad else "clean (codes, public bodies and numbers only)"))
    if safety is not None and isinstance(safety.get("municipalities"), dict):
        keys = {t["key"] for t in safety["typologies"]}
        codes = {x[0] for x in counties["rows"]} if counties else None
        badm = [c for c, m in safety["municipalities"].items() if not (len(c) == 5 and c.isdigit()) or (codes is not None and c not in codes)]
        if badm:
            r.fail(f"safety.json: municipality codes not in counties.json: {_sample(badm)}")
        negs = [c for c, m in safety["municipalities"].items() for y in safety["years"]
                for k, v in (m.get(y) or {}).items() if k not in keys or (v is not None and (not is_int(v) or v < 0))]
        if negs:
            r.fail(f"safety.json: unknown typology or a value that is not a non-negative integer or null: {_sample(negs)}")
        if len(safety["municipalities"]) < 400:
            r.warn(f"safety.json: only {len(safety['municipalities'])} towns (the 2025 closing has 427)")
        r.note(f"safety.json: {len(safety['municipalities'])} towns, {len(safety['provinces'])} provinces, {len(safety['ccaa'])} CCAA")
    if junta is not None and isinstance(junta.get("provinces"), dict):
        badp = [c for c in junta["provinces"] if not (len(c) == 2 and c.isdigit())]
        if badp:
            r.fail(f"contracts_junta.json: province keys must be 2-digit INE codes: {_sample(badp)}")
        for c, p in junta["provinces"].items():
            for y in junta["years"]:
                d = p.get(y) or {}
                if d and (d["single_bidder"] > d["n"] or d["under_15k"] > d["n"] or d["under_40k"] > d["n"] or d["under_15k"] > d["under_40k"]):
                    r.fail(f"contracts_junta.json {c} {y}: a share is above 100 % or the tranches are inconsistent")
    if boja is not None and isinstance(boja.get("by_year_section"), dict):
        for y, o in boja["by_year_section"].items():
            if any(not is_int(v) or v < 0 for v in o.values()):
                r.fail(f"boja.json {y}: counts must be non-negative integers")
        org_tot = {y: sum(g["counts"].get(y, 0) for g in boja["by_organisation"]) for y in boja["years"]}
        for y in boja["years"]:
            if org_tot[y] > sum(boja["by_year_section"][y].values()):
                r.fail(f"boja.json {y}: bodies add up to more than the year total")


def check_foreign_consistency(r: Report, lenses, counties, citizens, interim_dir: Path) -> None:
    """The foreign lens, counties.json and citizens.json must read the same table (65032, 2026)."""
    p = Path(interim_dir) / "ine_migration.json"
    if not p.exists() or counties is None:
        r.note("foreign consistency: ine_migration interim or counties.json missing, skipped")
        return
    nat = json.loads(p.read_text())["data"]["national"]
    foreign, total = nat["foreign"]["2026"], nat["total"]["2026"]
    cols = counties["columns"]
    j, pj = cols.index("foreign"), cols.index("population")
    num = sum(x[j] * x[pj] for x in counties["rows"] if x[j] is not None and x[pj])
    den = sum(x[pj] for x in counties["rows"] if x[j] is not None and x[pj])
    share = num / den if den else 0
    dev = abs(share - foreign / total)
    (r.ok if dev < 0.002 else r.fail)(f"foreign consistency: counties.json {share:.4%} vs national table {foreign / total:.4%}")
    lens = next((l for l in (lenses or {}).get("lenses", []) if l.get("id") == "foreign"), None)
    if lens is not None and "65032" not in lens.get("description", ""):
        r.fail("foreign consistency: the foreign lens does not cite table 65032")
    if citizens is not None:
        cz = (citizens.get("national") or {}).get("nationality")
        if cz and cz["counts"]["foreign"] != foreign:
            r.fail(f"foreign consistency: citizens.json national foreign {cz['counts']['foreign']:,} != table 65032 {foreign:,}")
        elif cz:
            r.ok(f"foreign consistency: citizens.json national foreign {foreign:,} equals table 65032 (2026)")


def _load(r: Report, web_dir: Path, name: str, required: bool):
    p = web_dir / name
    if not p.exists():
        (r.fail if required else r.note)(f"{name}: missing" + ("" if required else " (optional, skipped)"))
        return None
    try:
        return json.loads(p.read_text())
    except ValueError as exc:
        r.fail(f"{name}: invalid JSON ({exc})")
        return None


LEVELS = ("PASS", "NOTE", "WARN", "FAIL")


def builder_checks() -> list[tuple[str, object]]:
    """(builder module name, check function) for every pipeline/build module that defines check(web_dir).

    Helpers without build() count too, so a module can check a file another builder writes.
    """
    import importlib
    import pkgutil

    from . import build as build_pkg

    out = []
    for m in sorted(pkgutil.iter_modules(build_pkg.__path__), key=lambda m: m.name):
        mod = importlib.import_module(f"{build_pkg.__name__}.{m.name}")
        fn = getattr(mod, "check", None)
        if callable(fn):
            out.append((m.name, fn))
    return out


def run_builder_checks(r: Report, web_dir: Path, checks=None) -> None:
    """Run each builder's check(web_dir) and add its lines to the report (prefixed with the builder name)."""
    checks = builder_checks() if checks is None else checks
    if not checks:
        return
    r.section("builder checks")
    for name, fn in checks:
        try:
            lines = fn(web_dir) or []
        except Exception as exc:  # a broken check must not hide the rest of the report
            r.fail(f"{name}: check() raised {type(exc).__name__}: {exc}")
            continue
        for item in lines:
            try:
                level, msg = item
            except (TypeError, ValueError):
                r.fail(f"{name}: check() returned {item!r}, expected (level, message)")
                continue
            level = str(level).upper()
            if level not in LEVELS:
                r.fail(f"{name}: unknown level {level!r} for: {msg}")
                continue
            r._add(level, f"{name}: {msg}")


def check_simple(r: Report, web_dir: Path) -> None:
    """simple.json (simple interface), only when the file exists: size, a row and a shape for every municipality of
    counties.json, indicator order, Sevilla's income against counties.json, 10-value series, names without a trailing
    article."""
    path = web_dir / "simple.json"
    if not path.exists():
        return
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        r.fail(f"simple.json: invalid JSON ({exc})")
        return
    size = path.stat().st_size
    (r.ok if size < 3_000_000 else r.fail)(f"simple.json: {size / 1e6:.2f} MB (limit 3.0 MB)")
    cols = (doc.get("munis") or {}).get("cols") or []
    rows = (doc.get("munis") or {}).get("rows") or []
    keys = [i.get("key") for i in doc.get("indicators", [])]
    (r.ok if cols[5:] == keys and len(keys) == 14 else r.fail)("simple.json: indicator order matches the municipal columns")
    miss = [k for k in keys if k not in ((doc.get("nation") or {}))
            or any(k not in (p.get("values") or {}) for p in doc.get("provinces", []))]
    (r.ok if not miss else r.fail)("simple.json: every indicator is in provinces and nation" + (f" (missing {miss})" if miss else ""))
    counties = _load(r, web_dir, "counties.json", False)
    if counties:
        ci = {k: i for i, k in enumerate(counties["columns"])}
        have = {row[0] for row in rows}
        shapes = (doc.get("shapes") or {}).get("munis") or {}
        missing = [c[0] for c in counties["rows"] if c[0] not in have or not shapes.get(c[0])]
        (r.ok if not missing else r.fail)(f"simple.json: every municipality of counties.json has a row and a shape"
                                          + (f" (missing {len(missing)}, e.g. {missing[:3]})" if missing else ""))
        sev = next((c for c in counties["rows"] if c[0] == "41091"), None)
        mine = next((row for row in rows if row[0] == "41091"), None)
        if sev and mine and "income" in cols:
            ok = mine[cols.index("income")] == int(sev[ci["income"]])
            (r.ok if ok else r.fail)("simple.json: Sevilla income equals counties.json")
    ser = doc.get("series") or {}
    bad = [k for k, v in (ser.get("munis") or {}).items() if len(v) != 10]
    bad += [k for k, v in (ser.get("provinces") or {}).items() if len(v) != 10]
    ok = len(ser.get("years") or []) == 10 and len(ser.get("nation") or []) == 10 and not bad
    (r.ok if ok else r.fail)("simple.json: every series has 10 values" + (f" (bad: {bad[:3]})" if bad else ""))
    tail = re.compile(r", (El|La|Los|Las|L'|Els|Les|A|O|Os|As)$")
    names = [row[1] for row in rows if tail.search(row[1])]
    (r.ok if not names else r.fail)("simple.json: no name ends with an article" + (f" (e.g. {names[:3]})" if names else ""))

    _check_simple_points(r, web_dir, doc)


def _check_simple_points(r: Report, web_dir: Path, doc: dict) -> None:
    """simple.json points: from_world lands six known municipalities within 3 box units of their centroid, every point
    lies in the box, counts match the source files, Madrid and Barcelona have their airport and port close by."""
    sh = doc.get("shapes") or {}
    tf, pts, cen = sh.get("from_world"), doc.get("points") or {}, doc.get("munis_centroid") or {}
    if not (tf and pts and cen):
        r.fail("simple.json: from_world, points and munis_centroid are present")
        return
    w, h = sh.get("w", 1000), sh.get("h", 0)
    off = [(k, p["name"]) for k, v in pts.items() for p in v
           if not (isinstance(p.get("x"), (int, float)) and isinstance(p.get("y"), (int, float))
                   and 0 <= p["x"] <= w and 0 <= p["y"] <= h)]
    (r.ok if not off else r.fail)("simple.json: every point lies inside the box" + (f" (outside: {off[:3]})" if off else ""))
    infra, wonders = _load(r, web_dir, "infrastructure.json", False), _load(r, web_dir, "wonders.json", False)
    if infra and wonders:
        want = {"airports": len(infra["airports"]), "ports": len(infra["ports"]),
                "heritage": sum(1 for x in wonders["wonders"] if x.get("rule") == "patrimonio_mundial")}
        got = {k: len(pts.get(k) or []) for k in want}
        (r.ok if got == want else r.fail)(f"simple.json: point counts {got} match the source files {want}")

    def dist(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])

    interim = Path(__file__).resolve().parents[1] / "data" / "interim" / "gisco_lau.json"
    proj = _load(r, web_dir, "projection.json", False)
    if interim.exists() and proj:
        from .build.simple import ring_area, ring_centroid
        mp = MapProjection(proj["min_x"], proj["max_y"], proj["margin"])
        gis = {g["code"]: g for g in json.loads(interim.read_text())["data"]["municipalities"]}
        bad = []
        for code in ("28079", "41091", "08019", "35016", "38038", "07040"):
            ring = max(gis[code]["rings"], key=lambda q: ring_area(q) if len(q) > 2 else 0)
            wx, wy = ring_centroid(mp.project_ring(ring))
            bx, by = tf["s"] * wx + tf["dx"], tf["s"] * wy + tf["dy"]
            d = dist((bx, by), cen[code])
            if d > 3:
                bad.append((code, round(d, 1)))
        (r.ok if not bad else r.fail)("simple.json: from_world lands 6 municipalities within 3 units of their centroid"
                                      + (f" (off: {bad})" if bad else ""))
    mad = next((p for p in pts.get("airports", []) if p.get("city") == "Madrid"), None)
    bcn = next((p for p in pts.get("ports", []) if p["name"] == "Barcelona"), None)
    ok = (mad and bcn and "28079" in cen and "08019" in cen
          and dist((mad["x"], mad["y"]), cen["28079"]) <= 25 and dist((bcn["x"], bcn["y"]), cen["08019"]) <= 25)
    (r.ok if ok else r.fail)("simple.json: Madrid airport and Barcelona port lie within 25 units of their municipality")


def check_lens_series(r: Report, web_dir: Path) -> None:
    """lens_series.json (year slider data), only when the file exists: years ascending, array lengths, the latest
    year of every series against the current lens of lenses.json, file size."""
    path = web_dir / "lens_series.json"
    if not path.exists():
        return
    try:
        doc = json.loads(path.read_text())
    except ValueError as exc:
        r.fail(f"lens_series.json: invalid JSON ({exc})")
        return
    size = path.stat().st_size
    (r.ok if size < 1_500_000 else r.fail)(f"lens_series.json: {size / 1e6:.2f} MB (limit 1.5 MB)")
    lenses = _load(r, web_dir, "lenses.json", False)
    current = {l["id"]: l for l in (lenses or {}).get("lenses", [])}
    index = doc.get("index")
    n = len(index) if index is not None else doc.get("hexes")
    if index is not None and index != sorted(set(index)):
        r.fail("lens_series.json: index must be ascending and unique")
    for s in doc.get("lenses", []):
        what = f"lens_series.json {s.get('id')}"
        years, rows = s.get("years") or [], s.get("values") or []
        if not years or years != sorted(set(years)) or len(rows) != len(years):
            r.fail(f"{what}: years must be ascending and match the value rows")
            continue
        if any(len(row) != n for row in rows):
            r.fail(f"{what}: every row needs {n} values (one per hex)")
            continue
        cur = current.get(s["id"])
        if cur is None:
            r.note(f"{what}: no lens with this id in lenses.json, latest year not compared")
            continue
        full = cur["values"]
        idx = index if index is not None else range(len(full))
        pairs = list(zip(idx, rows[-1]))
        bad = 0
        tol = {"income": 1.0, "age": 0.1, "household": 0.01, "elderly": 0.0101, "density": 0.2}.get(s["id"], 1e-9)
        for i, v in pairs:
            c = full[i]
            if s["id"] == "income" and c:
                tol = 0.01 * c  # weighted by the Atlas population of the year, lenses.json by the 2026 census: euros apart
            if (v is None) != (c is None) or (v is not None and abs(v - c) > tol + 1e-9):
                bad += 1
        share = 1 - bad / max(1, len(pairs))
        (r.ok if share >= 0.99 else r.warn)(f"{what}: latest year {years[-1]} equals lenses.json for {share:.1%} of hexes")


def run(web_dir: Path = WEB_DATA, interim_dir: Path = INTERIM, quiet: bool = False, builder_checks_=None) -> Report:
    """Run every check and return the report.

    builder_checks_: None = discover the builder check() functions (part 3); a list of (name, fn) to run those
    instead; [] to skip part 3.
    """
    r = Report(quiet)
    r.section("contracts (docs/DATA_CONTRACTS.md v2)")
    docs = {name: _load(r, web_dir, name, True) for name in REQUIRED}
    docs.update({name: _load(r, web_dir, name, False) for name in OPTIONAL})
    ctx = check_world(r, docs["world.json"]) if docs["world.json"] is not None else None
    source_ids = None
    if docs["sources.json"] is not None:
        source_ids = check_sources(r, docs["sources.json"])
    if docs["nation.json"] is not None:
        check_nation(r, docs["nation.json"])
    if docs["cities.json"] is not None:
        check_cities(r, docs["cities.json"], docs["nation.json"], docs["world.json"], interim_dir)
    if docs.get("states.json") is not None:
        check_states(r, docs["states.json"], docs["nation.json"])
    if isinstance(docs["cities.json"], list) and docs["cities.json"]:
        check_land(r, "cities.json", docs["cities.json"])
    if isinstance(docs.get("states.json"), list):
        check_land(r, "states.json", docs["states.json"])
    if docs.get("counties.json") is not None:
        check_counties_file(r, docs["counties.json"], docs["world.json"], docs["cities.json"])
    if docs.get("districts.json") is not None:
        check_districts_file(r, docs["districts.json"], docs["cities.json"], docs["nation.json"])
    if docs.get("citizens.json") is not None:
        check_citizens_file(r, docs["citizens.json"], docs["cities.json"])
    if docs["nation.json"] is not None and not _is_f0(docs["nation.json"]):
        check_economy_conservation(r, interim_dir)

    if docs.get("lenses.json") is not None:
        check_lenses(r, docs["lenses.json"], ctx, source_ids)
        check_conservation(r, interim_dir, docs.get("nation.json"))

    check_transparency_files(r, docs.get("safety.json"), docs.get("boja.json"), docs.get("contracts_junta.json"), docs.get("counties.json"), docs["cities.json"])
    check_foreign_consistency(r, docs.get("lenses.json"), docs.get("counties.json"), docs.get("citizens.json"), interim_dir)

    check_map_layers(r, docs, docs["world.json"])

    r.section("data quality")
    if ctx is None:
        r.note("world.json unusable; skipping the data-quality report")
    else:
        quality_map(r, ctx)
        quality_rivers(r, ctx)
    run_builder_checks(r, web_dir, builder_checks_)
    check_city_scopes(r, web_dir)
    check_lens_series(r, web_dir)
    check_simple(r, web_dir)
    return r


def main(web_dir: Path = WEB_DATA, interim_dir: Path = INTERIM) -> int:
    r = run(web_dir, interim_dir)
    print(f"\ncheck: {r.count('PASS')} pass, {r.count('WARN')} warn, {r.count('FAIL')} fail")
    return 1 if r.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
