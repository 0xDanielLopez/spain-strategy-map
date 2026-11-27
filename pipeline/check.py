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

from .core.paths import INTERIM, WEB_DATA

REQUIRED = ["world.json", "cities.json", "nation.json", "sources.json"]
OPTIONAL = ["states.json", "lenses.json", "resources.json", "counties.json", "districts.json", "citizens.json"]
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
PCT_KEYS = ["forest", "crop", "grass", "shrub", "wetland", "developed"]
COLOR = re.compile(r"^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?([0-9a-fA-F]{2})?$")


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
                    "elderly", "foreign", "household", "income", "poverty", "higher_education", "auf", "cell"]
COUNTIES_PCT = ["growth", "elderly", "foreign", "poverty", "higher_education"]


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
        if lens["format"] == "pct" and lens["id"] != "growth" and any(is_num(v) and not -1e-9 <= v <= 1 + 1e-9 for v in vals):
            r.fail(f"{what}: format pct but some values are outside 0..1 (pct lenses are fractions)")
        if lens["id"] == "growth" and any(is_num(v) and v < -1 for v in vals):
            r.fail(f"{what}: growth below -100 %")
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


# ---------------------------------------------------------------- entry point


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

    r.section("data quality")
    if ctx is None:
        r.note("world.json unusable; skipping the data-quality report")
    else:
        quality_map(r, ctx)
        quality_rivers(r, ctx)
    run_builder_checks(r, web_dir, builder_checks_)
    return r


def main(web_dir: Path = WEB_DATA, interim_dir: Path = INTERIM) -> int:
    r = run(web_dir, interim_dir)
    print(f"\ncheck: {r.count('PASS')} pass, {r.count('WARN')} warn, {r.count('FAIL')} fail")
    return 1 if r.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
