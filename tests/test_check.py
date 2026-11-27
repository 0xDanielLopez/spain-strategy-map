"""pipeline.check on a tiny synthetic Spain-like dataset (a 3x2 grid)."""

import json
import tempfile
import unittest
from pathlib import Path

from pipeline import check


def dataset():
    """Grid 7x3 = 21 cells: cell i < 19 belongs to CCAA i, cell 19 is sea and cell 20 is Portugal."""
    owner = list(range(19)) + [-1, -2]
    n = len(owner)
    water = [0 if o != -1 else 1 for o in owner]
    world = {
        "version": 2, "country": "Spain", "grid": {"radius": 10.0, "cols": 7, "rows": 3}, "width": 130.0, "height": 40.0, "margin": 0,
        "insets": [{"name": "Canarias", "x0": 40.0, "y0": 15.0, "x1": 58.0, "y1": 29.0}],
        "owner": owner, "county": [0 if o >= 0 else -1 for o in owner], "elev": [10 if o >= 0 else -50 for o in owner],
        "water": water, "relief": [i % 3 if o >= 0 else 0 for i, o in enumerate(owner)],
        "cover": [(3, 4, 5, 7, 8, 9, 10, 11)[i % 8] if o >= 0 else 0 for i, o in enumerate(owner)],
        "pct": {k: [50 if k == "forest" and o >= 0 else 0 for o in owner] for k in check.PCT_KEYS},
        "tables": {
            "water": [{"id": i, "name": nm} for i, nm in enumerate(["Land", "Ocean", "Coast", "Lake"])],
            "relief": [{"id": i, "name": nm} for i, nm in enumerate(["Flat", "Hills", "Mountains", "Peaks"])],
            "cover": [{"id": 0, "key": "none", "name": "None"}]
            + [{"id": i, "key": check.COVER_KEYS[i], "name": "x", "color": "#123456"} for i in (3, 4, 5, 7, 8, 9, 10, 11)],
        },
        "states": [{"fips": f"{i + 1:02d}", "abbr": f"C{i}", "name": f"CCAA {i}"} for i in range(check.N_CCAA)],
        "counties": [{"geoid": "01001", "name": "A", "province": "04"}, {"geoid": "02001", "name": "C", "province": "22"}],
        "forced": [{"cell": 4, "name": "Isla", "reason": "island had no land hex"}],
        "rivers": [{"name": "Big", "rank": 1, "pts": [1.0, 1.0, 20.0, 12.0]}],
    }
    assert len(world["owner"]) == n
    nation = {"vintage": "Base map (no statistics yet)", "year": None, "gdp_vintage": None,
              "nation": {"name": "Spain", "population": None, "employed": None, "gdp": None, "yields": {}, "jobs": {},
                         "growth": None, "growth_years": None},
              "yields": [], "industries": {}}
    sources = [{"id": "etopo", "title": "t", "publisher": "p", "homepage": "h", "license": "l", "description": "d",
                "used_for": "u", "vintage": None,
                "files": [{"file": "f", "url": "u", "retrieved": "2026-01-01", "sha256": "ab", "bytes": 1}]}]
    web = {"world.json": world, "cities.json": [], "nation.json": nation, "sources.json": sources}
    return web, {}


class CheckTest(unittest.TestCase):
    def run_check(self, web, interim=None):
        with tempfile.TemporaryDirectory() as tmp:
            wd, idir = Path(tmp) / "web", Path(tmp) / "interim"
            wd.mkdir()
            idir.mkdir()
            for name, doc in web.items():
                if doc is not None:
                    (wd / name).write_text(json.dumps(doc))
            return check.run(wd, idir, quiet=True, builder_checks_=[])

    def levels(self, rep, level):
        return [m for lv, m in rep.lines if lv == level]

    def test_clean_dataset_passes(self):
        rep = self.run_check(*dataset())
        self.assertEqual(self.levels(rep, "FAIL"), [])
        self.assertEqual(self.levels(rep, "WARN"), [])
        passes = " | ".join(self.levels(rep, "PASS"))
        self.assertIn("19 Spanish land hexes", passes)
        self.assertIn("1 forced land cells", passes)

    def test_missing_optional_is_a_note(self):
        rep = self.run_check(*dataset())
        self.assertFalse(rep.failed)
        self.assertIn("lenses.json", " | ".join(self.levels(rep, "NOTE")))

    def test_missing_required_fails(self):
        web, interim = dataset()
        web["nation.json"] = None
        self.assertTrue(self.run_check(web, interim).failed)

    def test_v1_world_fails(self):
        web, _ = dataset()
        del web["world.json"]["version"]
        self.assertTrue(any("version" in m for m in self.levels(self.run_check(web), "FAIL")))

    def mutate(self, fn):
        web, _ = dataset()
        fn(web["world.json"])
        return self.run_check(web)

    def test_contract_violations(self):
        cases = {
            "owner above 18": lambda w: w["owner"].__setitem__(0, 19),
            "18 states": lambda w: w["states"].pop(),
            "pasture key": lambda w: w["pct"].__setitem__("pasture", [0] * 21),
            "cover id not in table": lambda w: w["cover"].__setitem__(0, 2),
            "inset outside map": lambda w: w["insets"][0].__setitem__("x1", 999.0),
            "forced cell is water": lambda w: w["forced"][0].__setitem__("cell", 19),
            "forced cell missing keys": lambda w: w["forced"][0].pop("reason"),
            "foreign cell with cover share": lambda w: w["pct"]["crop"].__setitem__(20, 10),
            "water cell with relief": lambda w: w["relief"].__setitem__(19, 1),
            "country missing": lambda w: w.pop("country"),
        }
        for name, fn in cases.items():
            with self.subTest(name):
                self.assertTrue(self.mutate(fn).failed)

    def test_empty_cities_and_null_nation_are_fine(self):
        web, _ = dataset()
        self.assertEqual(web["cities.json"], [])
        self.assertFalse(self.run_check(web).failed)
        web["nation.json"]["nation"]["population"] = "many"
        self.assertTrue(self.run_check(web).failed)

    def test_ccaa_without_hexes_fails(self):
        web, _ = dataset()
        web["world.json"]["owner"][4] = 0
        self.assertTrue(any("without any hex" in m for m in self.levels(self.run_check(web), "FAIL")))


if __name__ == "__main__":
    unittest.main()
