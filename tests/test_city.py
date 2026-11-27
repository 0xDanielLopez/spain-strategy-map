"""City scopes: synthetic sections, cover and tables only (no network, no INE files)."""

import json
import tempfile
import unittest
from pathlib import Path

from pipeline import check
from pipeline.build import city
from pipeline import scopes
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
             single_households_pct=25.0, poverty60_pct=10.0, foreign=foreign if foreign is not None else pop // 10, born_abroad=pop // 5,
             tourist_dwellings=5, tourist_places=pop // 20, tourist_pct=2.0)
    return s


class TouristLenses(unittest.TestCase):
    def sec(self, pop, **kw):
        s = {f: None for f in ine_sections.SECTION_FIELDS}
        s.update(pop=pop, **kw)
        return s

    def test_terms_zero_versus_missing(self):
        share, places = city._terms_tourist_share, city._terms_tourist_places
        zero = self.sec(1000, tourist_dwellings=0, tourist_places=0, tourist_pct=0)
        self.assertEqual(share(zero), (0, 1000))  # a real 0 stays a value
        self.assertEqual(places(zero), (0, 1000))
        none = self.sec(1000)
        self.assertIsNone(share(none))
        self.assertIsNone(places(none))
        self.assertIsNone(share(self.sec(0, tourist_pct=5.0)))  # no residents: no weight
        protected = self.sec(1000, tourist_dwellings=3, tourist_places=9, tourist_pct=None)
        self.assertIsNone(share(protected))
        self.assertEqual(places(protected), (900, 1000))

    def test_hex_values(self):
        sstats = [self.sec(1000, tourist_pct=10.0, tourist_places=50), self.sec(3000, tourist_pct=0, tourist_places=0)]
        parts = [(0, 1.0), (1, 1.0)]
        pop_of = [1000, 3000]
        share = city.hex_value(parts, city._terms_tourist_share, sstats, pop_of, 4)
        self.assertAlmostEqual(share, 0.025)  # (1000*0.10 + 3000*0) / 4000
        places = city.hex_value(parts, city._terms_tourist_places, sstats, pop_of, 2)
        self.assertAlmostEqual(places, 1.25)  # 50 places per 4000 people = 1.25 per 100
        sstats[1] = self.sec(3000)  # no data for 75 % of the people: below COVERAGE_MIN
        self.assertIsNone(city.hex_value(parts, city._terms_tourist_share, sstats, pop_of, 4))

    def test_specs_and_text(self):
        specs = {lid: meta for lid, _, meta in city.lens_specs({"tourist": "2026M05"})}
        for lid in ("tourist_share", "tourist_places"):
            d = specs[lid]["description"]
            self.assertIn("mayo de 2026", d)
            self.assertIn("Estadística experimental del INE", d)
            self.assertIn("No es un registro oficial de licencias", d)
            self.assertEqual(specs[lid]["source"], "ine_tourist")
        self.assertEqual(city.period_es("2026M11"), "noviembre de 2026")
        self.assertEqual(city.period_es(None), "?")


class Names(unittest.TestCase):
    def test_article_moves_first(self):
        self.assertEqual(fix_name("Rozas de Madrid, Las"), "Las Rozas de Madrid")
        self.assertEqual(fix_name("Escorial, El"), "El Escorial")
        self.assertEqual(fix_name("Alcobendas"), "Alcobendas")

    def test_district_names(self):
        self.assertEqual(district_name(SCOPES["madrid"], "2807901"), "Centro")
        self.assertEqual(district_name(SCOPES["madrid"], "2807921"), "Barajas")
        self.assertEqual(district_name({"districts": {}}, "0801003"), "Distrito 3")
        self.assertEqual(district_name({"districts": {}}, "0801012"), "Distrito 12")
        self.assertEqual(scopes.district_abbr({"districts": {}}, "0801003"), "D 3")
        self.assertEqual(scopes.district_abbr(SCOPES["madrid"], "2807921"), "Barajas")

    def test_scope_table(self):
        self.assertEqual(SCOPES["madrid"]["hex_km"], 0.3)
        self.assertEqual(SCOPES["madrid-auf"]["hex_km"], 1.2)
        self.assertEqual(municipalities(SCOPES["madrid"]), ["28079"])


FAKE_CITIES = [
    {"id": "ES001F", "name": "Madrid", "core": "28079"}, {"id": "ES021F", "name": "Alicante / Alacant", "core": "03014"},
    {"id": "ES008F", "name": "Las Palmas de Gran Canaria", "core": "35016"}, {"id": "ES063F", "name": "Donostia / San Sebastián", "core": "20069"},
    {"id": "ES025F", "name": "A Coruña", "core": "15030"},
]


class GeneratedScopes(unittest.TestCase):
    def test_slug(self):
        self.assertEqual(scopes.slug("Las Palmas de Gran Canaria"), "las-palmas-de-gran-canaria")
        self.assertEqual(scopes.slug("Alicante / Alacant"), "alicante")
        self.assertEqual(scopes.slug("Donostia / San Sebastián"), "donostia")
        self.assertEqual(scopes.slug("A Coruña"), "a-coruna")
        self.assertEqual(scopes.slug("Vitoria-Gasteiz"), "vitoria-gasteiz")

    def test_generate_keeps_madrid_and_adds_one_municipality_per_city(self):
        out = scopes.generate_scopes(FAKE_CITIES)
        self.assertEqual(list(out), ["madrid", "alicante", "las-palmas-de-gran-canaria", "donostia", "a-coruna", "madrid-auf"])
        self.assertEqual(out["madrid"]["hex_km"], 0.3)
        self.assertEqual(out["madrid"]["districts"], {"28079": scopes.MADRID_DISTRICTS})
        lp = out["las-palmas-de-gran-canaria"]
        self.assertEqual((lp["kind"], lp["municipalities"], lp["city"], lp["hex_km"], lp["title"]), ("municipality", ["35016"], "ES008F", None, "Las Palmas de Gran Canaria"))
        self.assertEqual(out["madrid-auf"]["hex_km"], 1.2)

    def test_duplicate_ids_are_refused(self):
        with self.assertRaises(ValueError):
            scopes.generate_scopes(FAKE_CITIES + [{"id": "ES999F", "name": "Alicante", "core": "03999"}])

    def test_real_scopes_are_unique_and_cover_cities_json(self):
        cities = scopes._load_cities()
        if cities:
            self.assertEqual(len(SCOPES), len(cities) + 1)
            self.assertEqual({SCOPES[i]["city"] for i in SCOPES}, {c["id"] for c in cities})

    def test_radius_targets_1_2_hexes_per_section_between_600_and_3000(self):
        self.assertEqual(scopes.target_hexes(100), 600)
        self.assertEqual(scopes.target_hexes(1000), 1200)
        self.assertEqual(scopes.target_hexes(5000), 3000)
        r = scopes.radius_for(100.0, 1000)  # sqrt(100 / (2.598 * 1200)) = 0.179
        self.assertEqual(r, 0.18)
        self.assertAlmostEqual(scopes.expected_hexes(100.0, r), 1188, delta=5)

    def test_radius_is_clamped(self):
        self.assertEqual(scopes.radius_for(5000.0, 100), 0.5)
        self.assertEqual(scopes.radius_for(0.5, 100), 0.08)

    def test_fixed_radius_wins_and_area_of_a_square(self):
        secs = [{"cusec": "x", "rings": square(-3.7, 40.4, 0.1)}]  # 0.1 degree: 11.12 km x 8.46 km
        self.assertAlmostEqual(scopes.sections_area_km2(secs), 94.1, delta=0.5)
        self.assertEqual(scopes.resolve_radius({"hex_km": 0.3}, secs), 0.3)
        self.assertEqual(scopes.resolve_radius({"hex_km": None}, secs), scopes.radius_for(scopes.sections_area_km2(secs), 1))

    def test_overview_follows_the_radius(self):
        self.assertAlmostEqual(city.overview_pixel_m(0.12), 40.0)
        self.assertEqual(city.overview_pixel_m(1.2), worldcover.MAX_PIXEL_M)


class Labels(unittest.TestCase):
    def test_short_label_rules(self):
        f = scopes.short_label
        for name, want in [("Centro", "Centro"), ("Fuencarral-El Pardo", "Fuencarral"), ("Moncloa-Aravaca", "Moncloa"),
                           ("Puente de Vallecas", "Pte. Vallecas"), ("San Blas-Canillejas", "San Blas"), ("Ciudad Lineal", "C. Lineal"),
                           ("Las Rozas de Madrid", "Las Rozas"), ("San Sebastián de los Reyes", "S. Sebastián")]:
            self.assertEqual(f(name), want)
            self.assertLessEqual(len(f(name)), 13)  # an override may be 13

    def test_every_madrid_district_label_fits(self):
        for code, name in scopes.MADRID_DISTRICTS.items():
            self.assertLessEqual(len(scopes.district_abbr(SCOPES["madrid"], "28079" + code)), 13)


class Margin(unittest.TestCase):
    def test_margin_is_12_radii_unless_the_grid_would_be_too_big(self):
        self.assertEqual(city.pick_margin(10, 10, 0.3), 12)
        m = city.pick_margin(250, 250, 1.2)
        self.assertLess(m, 12)
        self.assertGreaterEqual(m, city.MIN_MARGIN_HEXES)
        self.assertLessEqual((250 + 2 * m * 1.2) ** 2 / (1.5 * 3 ** 0.5 * 1.2 ** 2), city.MAX_CELLS)


class IndexFile(unittest.TestCase):
    def test_index_is_sorted_by_population(self):
        with tempfile.TemporaryDirectory() as tmp:
            for sid, pop in (("b", 10), ("a", 500), ("c", 10)):
                city.update_index({"id": sid, "name": sid, "kind": "municipality", "city": "ES001F", "hex_km": 0.2, "title": sid}, pop, Path(tmp))
            ids = [e["id"] for e in json.loads((Path(tmp) / "index.json").read_text(encoding="utf-8"))["scopes"]]
            self.assertEqual(ids, ["a", "b", "c"])


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
        ts = next(l for l in lenses if l["id"] == "tourist_share")
        self.assertEqual({v for v in ts["values"] if v is not None}, {0.02})
        tp = next(l for l in lenses if l["id"] == "tourist_places")
        self.assertEqual({v for v in tp["values"] if v is not None}, {5.0})  # 50 places per 1000 people = 5 per 100
        src = json.loads((out / "t" / "sources.json").read_text(encoding="utf-8"))
        self.assertIn("ine_tourist", [x["id"] for x in src])

    def test_surroundings_are_sea_or_foreign_land_and_county_stays_in_owner(self):
        class SeaEast(FakeCover):
            def at(self, lon, lat):
                return 0 if lon > -3.64 else (50 if lon < -3.69 else 30)

        worldcover.read_window = lambda *a, **k: SeaEast()
        real = city.sea_possible
        self.addCleanup(setattr, city, "sea_possible", real)
        out = Path(self.tmp.name)
        city.sea_possible = lambda *a, **k: False  # inland city: the same water is a river or a lake, never sea
        city.build_scope(self.scope, out)
        w = json.loads((out / "t" / "world.json").read_text(encoding="utf-8"))
        self.assertEqual({wt for o, wt in zip(w["owner"], w["water"]) if o == -1}, {3})
        city.sea_possible = lambda *a, **k: True  # coastal city
        res = city.build_scope(self.scope, out)
        self.assertEqual(res["hex_population"], 3000)
        w = json.loads((out / "t" / "world.json").read_text(encoding="utf-8"))
        owners = set(w["owner"])
        self.assertTrue({-2, -1} <= owners)
        self.assertTrue(all(wt in (1, 2) for o, wt in zip(w["owner"], w["water"]) if o == -1))
        self.assertTrue(all(wt == 0 for o, wt in zip(w["owner"], w["water"]) if o != -1))
        self.assertTrue(any(w["cover"][i] for i, o in enumerate(w["owner"]) if o == -2))  # foreign land keeps its real cover
        self.assertEqual(w["margin"], round(city.MARGIN_HEXES * w["scope"]["hex_km"], 1))
        fips = [st["fips"] for st in w["states"]]
        for o, c in zip(w["owner"], w["county"]):
            if o >= 0:
                self.assertEqual(w["counties"][c]["province"], fips[o])
            else:
                self.assertEqual(c, -1)

    def test_check_flags_a_broken_scope(self):
        out = Path(self.tmp.name)
        city.build_scope(self.scope, out)
        p = out / "t" / "nation.json"
        doc = json.loads(p.read_text(encoding="utf-8"))
        doc["nation"]["population"] = 2500
        p.write_text(json.dumps(doc), encoding="utf-8")
        r = check.Report(quiet=True)
        check.check_city_scope(r, out / "t")
        self.assertTrue(any(lv == "FAIL" and "population" in m for lv, m in r.lines))

    def test_adrh_match_rate_thresholds(self):
        out = Path(self.tmp.name)
        city.build_scope(self.scope, out)
        p = out / "t" / "world.json"
        doc = json.loads(p.read_text(encoding="utf-8"))
        for rate, level in ((0.99, None), (0.95, "WARN"), (0.80, "FAIL")):
            doc["scope"]["adrh_match"] = rate
            p.write_text(json.dumps(doc), encoding="utf-8")
            r = check.Report(quiet=True)
            check.check_city_scope(r, out / "t")
            hits = [lv for lv, m in r.lines if "ADRH" in m and lv in ("WARN", "FAIL")]
            self.assertEqual(hits, [level] if level else [])

    def test_centre_must_be_inside_spain(self):
        out = Path(self.tmp.name)
        city.build_scope(self.scope, out)
        proj = json.loads((out / "t" / "projection.json").read_text(encoding="utf-8"))
        w = json.loads((out / "t" / "world.json").read_text(encoding="utf-8"))
        lon, lat = check.scope_centre(w, proj)
        self.assertAlmostEqual(lon, -3.69, delta=0.05)
        self.assertAlmostEqual(lat, 40.41, delta=0.05)
        proj["main_albers"] = [36.0, 37.0, 36.5, -40.0]  # somewhere in the Atlantic
        (out / "t" / "projection.json").write_text(json.dumps(proj), encoding="utf-8")
        r = check.Report(quiet=True)
        check.check_city_scope(r, out / "t")
        self.assertTrue(any(lv == "FAIL" and "outside Spain" in m for lv, m in r.lines))

    def test_haversine(self):
        self.assertAlmostEqual(check._haversine_km(-3.7, 40.4, -3.7, 41.4), 111.2, delta=0.5)

    def test_check_ignores_missing_city_folder(self):
        r = check.Report(quiet=True)
        check.check_city_scopes(r, Path(self.tmp.name))
        self.assertEqual(r.lines, [])


if __name__ == "__main__":
    unittest.main()


class SeaPossibleTest(unittest.TestCase):
    """An inland city never gets sea cells, however its river leaves the grid (synthetic national map)."""

    def setUp(self):
        cols, rows = 12, 6
        water = [0] * (cols * rows)
        for r in range(rows):
            water[r * cols] = 1  # sea along the west edge
        self.world = {"grid": {"radius": 10.0, "cols": cols, "rows": rows}, "water": water}
        self.cities = [{"id": "COAST", "cell": 2 * cols + 1}, {"id": "INLAND", "cell": 2 * cols + 9}]

    def test_coastal_city_can_have_sea(self):
        self.assertTrue(city.sea_possible({"city": "COAST"}, 5.0, self.world, self.cities))

    def test_inland_city_cannot(self):
        self.assertFalse(city.sea_possible({"city": "INLAND"}, 5.0, self.world, self.cities))

    def test_a_large_grid_reaches_further(self):
        self.assertTrue(city.sea_possible({"city": "INLAND"}, 150.0, self.world, self.cities))

    def test_unknown_city_keeps_the_old_rule(self):
        self.assertTrue(city.sea_possible({"city": "NOPE"}, 5.0, self.world, self.cities))



class KeepWaterDryTest(unittest.TestCase):
    """A mostly-water hex gives its share of a section to the drier hexes (synthetic lattice)."""

    class Lat:
        def __init__(self, water_points):
            self.points = [10, 10, 10]
            self.cls = [0] * (3 * city.NC)
            for h, k in water_points.items():
                self.cls[h * city.NC + city.WATER_CLASS] = k

    def test_share_moves_to_dry_hexes_and_still_sums_to_one(self):
        out = city.keep_water_dry([[(0, 0.5), (1, 0.25), (2, 0.25)]], self.Lat({1: 6}))
        self.assertEqual([h for h, _ in out[0]], [0, 2])
        self.assertAlmostEqual(sum(w for _, w in out[0]), 1.0)
        self.assertAlmostEqual(out[0][0][1], 2 / 3)

    def test_a_section_with_only_wet_hexes_keeps_them(self):
        rows = [[(0, 0.5), (1, 0.5)]]
        self.assertEqual(city.keep_water_dry(rows, self.Lat({0: 9, 1: 5})), rows)

    def test_no_water_no_change(self):
        rows = [[(0, 1.0)], []]
        self.assertEqual(city.keep_water_dry(rows, self.Lat({})), rows)

