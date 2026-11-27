"""City scopes: synthetic sections, cover and tables only (no network, no INE files)."""

import json
import tempfile
import unittest
from pathlib import Path

from pipeline import check
from pipeline.build import city
from pipeline.scopes import SCOPES, district_name, fix_name, municipalities
from pipeline.sources import ine_sections, worldcover


class FakeCover:
    level, pixel_m, bytes_read, tiff_tiles = 3, 74.0, 0, 0

    def at(self, lon, lat):
        return 50 if lon < -3.69 else 10


def square(lon, lat, d=0.02):
    return [[(lon, lat), (lon + d, lat), (lon + d, lat + d), (lon, lat + d), (lon, lat)]]


def stats(pop, income=20000, foreign=None):
    s = {f: None for f in ine_sections.SECTION_FIELDS}
    s.update(pop=pop, income=income, adrh_pop=pop, age=40.0, under18_pct=15.0, over65_pct=20.0, household_size=2.5,
             single_households_pct=25.0, poverty60_pct=10.0, foreign=foreign if foreign is not None else pop // 10, born_abroad=pop // 5)
    return s


class Names(unittest.TestCase):
    def test_article_moves_first(self):
        self.assertEqual(fix_name("Rozas de Madrid, Las"), "Las Rozas de Madrid")
        self.assertEqual(fix_name("Escorial, El"), "El Escorial")
        self.assertEqual(fix_name("Alcobendas"), "Alcobendas")

    def test_district_names(self):
        self.assertEqual(district_name(SCOPES["madrid"], "2807901"), "Centro")
        self.assertEqual(district_name(SCOPES["madrid"], "2807921"), "Barajas")
        self.assertEqual(district_name({"districts": {}}, "0801003"), "Distrito 03")

    def test_scope_table(self):
        self.assertEqual(SCOPES["madrid"]["hex_km"], 0.3)
        self.assertEqual(SCOPES["madrid-auf"]["hex_km"], 1.2)
        self.assertEqual(municipalities(SCOPES["madrid"]), ["28079"])


class Allocation(unittest.TestCase):
    def test_built_up_points_decide(self):
        out = city.allocation({(0, 1): [8, 10], (0, 2): [2, 30]}, 1)
        self.assertAlmostEqual(dict(out[0])[1], 0.8)
        self.assertAlmostEqual(sum(w for _, w in out[0]), 1.0)

    def test_few_built_points_fall_back_to_all_points(self):
        out = city.allocation({(0, 1): [1, 10], (0, 2): [1, 30]}, 1)
        self.assertAlmostEqual(dict(out[0])[2], 0.75)

    def test_hex_value_needs_90_percent_coverage(self):
        secs = [{"x": 5.0}, {"x": None}]
        terms = lambda s: None if s["x"] is None else (s["x"], 1.0)
        self.assertEqual(city.hex_value([(0, 0.95), (1, 0.05)], terms, secs, [100, 100], 1), 5.0)
        self.assertIsNone(city.hex_value([(0, 0.8), (1, 0.2)], terms, secs, [100, 100], 1))


class WorldCoverWindow(unittest.TestCase):
    def test_pick_overview_takes_the_coarsest_fine_enough(self):
        ifds = [{256: (36000,)}, {256: (18000,)}, {256: (9000,)}, {256: (4500,)}, {256: (2250,)}]
        self.assertEqual(worldcover.pick_overview(ifds), 3)  # 74 m; 2250 px is 148 m
        with self.assertRaises(ValueError):
            worldcover.pick_overview([{256: (1000,)}])

    def test_tiles_for_bbox_can_touch_two_tiles(self):
        names = [t[0] for t in worldcover.tiles_for_bbox(-3.5, 40.0, -2.8, 40.6)]
        self.assertEqual(names, ["N39W006", "N39W003"])
        self.assertEqual([t[0] for t in worldcover.tiles_for_bbox(-3.9, 40.3, -3.5, 40.6)], ["N39W006"])

    def test_window_lookup(self):
        win = worldcover.CoverWindow(3, 74.0)
        px = bytearray(4)  # a 2x2 tile
        px[0], px[3] = 50, 10
        win.tiles["T"] = {"lat0": 39, "lon0": -6, "w": 2, "h": 2, "tw": 2, "th": 2, "across": 1, "px": {0: bytes(px)}}
        self.assertEqual(win.at(-5.9, 41.9), 50)  # north-west pixel
        self.assertEqual(win.at(-3.1, 39.1), 10)  # south-east pixel
        self.assertEqual(win.at(-2.0, 40.0), 0)  # outside the tile


class BuildScope(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        secs = [
            {"cusec": "2807901001", "cudis": "2807901", "cumun": "28079", "nmun": "Madrid", "rings": square(-3.71, 40.40)},
            {"cusec": "2807902001", "cudis": "2807902", "cumun": "28079", "nmun": "Madrid", "rings": square(-3.69, 40.40)},
        ]
        st = {"2807901001": stats(1000), "2807902001": stats(2000)}
        self._orig = (ine_sections.load_sections, ine_sections.load_section_stats, worldcover.read_window)
        ine_sections.load_sections = lambda codes: secs
        ine_sections.load_section_stats = lambda codes: {"vintage": {"30824": "2024", "65032": "2026"}, "sections": st, "districts": {}, "match": {}}
        worldcover.read_window = lambda *a, **k: FakeCover()
        self.addCleanup(self.restore)
        self.scope = {**SCOPES["madrid"], "id": "t"}

    def restore(self):
        ine_sections.load_sections, ine_sections.load_section_stats, worldcover.read_window = self._orig

    def test_build_conserves_population_and_passes_check(self):
        out = Path(self.tmp.name)
        res = city.build_scope(self.scope, out)
        self.assertEqual(res["population"], 3000)
        self.assertEqual(res["hex_population"], 3000)
        w = json.loads((out / "t" / "world.json").read_text(encoding="utf-8"))
        n = w["grid"]["cols"] * w["grid"]["rows"]
        self.assertEqual(len(w["owner"]), n)
        self.assertEqual(w["insets"], [])
        self.assertEqual(w["scope"]["levels"]["state"]["one"], "Distrito")
        self.assertEqual([s["name"] for s in w["states"]], ["Centro", "Arganzuela"])
        self.assertAlmostEqual(sum(p for p in w["pop"] if p is not None), 3000, delta=3)
        self.assertTrue(all(o in (-2, -1, 0, 1) for o in w["owner"]))
        index = json.loads((out / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["scopes"][0]["id"], "t")
        r = check.Report(quiet=True)
        check.check_city_scope(r, out / "t")
        self.assertEqual([m for lv, m in r.lines if lv == "FAIL"], [])
        lenses = json.loads((out / "t" / "lenses.json").read_text(encoding="utf-8"))["lenses"]
        income = next(l for l in lenses if l["id"] == "income")
        self.assertEqual({v for v in income["values"] if v is not None}, {20000})

    def test_check_flags_a_broken_scope(self):
        out = Path(self.tmp.name)
        city.build_scope(self.scope, out)
        p = out / "t" / "nation.json"
        doc = json.loads(p.read_text(encoding="utf-8"))
        doc["nation"]["population"] = 4000
        p.write_text(json.dumps(doc), encoding="utf-8")
        r = check.Report(quiet=True)
        check.check_city_scope(r, out / "t")
        self.assertTrue(any(lv == "FAIL" and "population" in m for lv, m in r.lines))

    def test_check_ignores_missing_city_folder(self):
        r = check.Report(quiet=True)
        check.check_city_scopes(r, Path(self.tmp.name))
        self.assertEqual(r.lines, [])


if __name__ == "__main__":
    unittest.main()
