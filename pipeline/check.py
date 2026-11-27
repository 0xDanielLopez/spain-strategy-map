"""Validate web/data/*.json against docs/DATA_CONTRACTS.md (v2) and report data quality.

    uv run python -m pipeline check

Part 1 checks each file's shape: required keys, types, per-cell array lengths and value
ranges. Part 2 is a short data-quality report for the base map (Spanish land hexes, hexes
per CCAA, forced cells, rivers inside the map). Phase F0 only produces world.json,
cities.json ([]), nation.json (minimal) and sources.json; everything else is optional.

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
OPTIONAL = ["states.json", "lenses.json", "resources.json", "counties.json"]
N_CCAA = 19

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


def check_cities(r: Report, cities) -> None:
    if not isinstance(cities, list):
        r.fail("cities.json: expected a list")
    else:
        r.ok(f"cities.json: {len(cities)} cities" + (" (F0: none yet)" if not cities else ""))


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
    if r.count("FAIL") == fails_before:
        r.ok(f"nation.json: {nat['nation']['name']} ({nat['vintage']})")


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
    if docs["sources.json"] is not None:
        check_sources(r, docs["sources.json"])
    if docs["nation.json"] is not None:
        check_nation(r, docs["nation.json"])
    if docs["cities.json"] is not None:
        check_cities(r, docs["cities.json"])

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
