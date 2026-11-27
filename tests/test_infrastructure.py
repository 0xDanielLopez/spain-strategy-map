"""Infrastructure builder on synthetic data: link rasterisation and site placement."""

import unittest

from pipeline.build import infrastructure as inf
from pipeline.core.geo import MapProjection
from pipeline.core.hexgrid import HexGrid


def grid():
    return HexGrid(radius=10.0, cols=30, rows=20)


class LinkTest(unittest.TestCase):
    def test_links_are_unique_ordered_neighbours(self):
        g = grid()
        (x0, y0), (x1, y1) = g.center(2, 5), g.center(20, 8)
        runs = inf.sample_cells(g, [(x0, y0), (x1, y1)])
        links = [l for r in runs for l in inf.links_of(g, r)]
        self.assertTrue(links)
        for a, b in links:
            self.assertLess(a, b)
            self.assertIn(b, g.neighbours(a))

    def test_build_rail_dedupes_and_keeps_best_tier(self):
        g = grid()
        owner = [0] * g.size
        line = [g.center(2, 5), g.center(12, 5)]
        proj = lambda lon, lat, region=None: (lon, lat)  # noqa: E731 - identity "projection"
        proj.region_of = lambda lon, lat: "main"
        proj.frame_at = lambda x, y: None

        class NoForeign:
            def locate(self, x, y):
                return -1

        feats = [{"scalerank": 7, "lines": [line]}, {"scalerank": 4, "lines": [line]}, {"scalerank": 9, "lines": [line]}]
        rail = inf.build_rail(g, proj, owner, feats, NoForeign())
        pairs = [tuple(r[:2]) for r in rail]
        self.assertEqual(len(pairs), len(set(pairs)))
        self.assertTrue(rail)
        self.assertEqual({r[2] for r in rail}, {0})  # the tier-0 pass wins over tier 1; scale rank 9 is not drawn

    def test_links_need_spanish_land_and_no_foreign_end(self):
        owner = [0, -1, -2, -1]
        self.assertTrue(inf.link_ok(owner, 0, 1))
        self.assertFalse(inf.link_ok(owner, 1, 3))  # sea to sea
        self.assertFalse(inf.link_ok(owner, 0, 2))  # one end on foreign land

    def test_road_classes(self):
        self.assertEqual(inf.road_class({"expressway": 1, "type": "Major Highway", "scalerank": 9}), 0)
        self.assertEqual(inf.road_class({"expressway": 0, "type": "Secondary Highway", "scalerank": 6}), 1)
        self.assertIsNone(inf.road_class({"expressway": 0, "type": "Secondary Highway", "scalerank": 9}))
        self.assertIsNone(inf.road_class({"expressway": 0, "type": "Road", "scalerank": 3}))
        self.assertEqual(inf.rail_tier({"scalerank": 5}), 0)
        self.assertEqual(inf.rail_tier({"scalerank": 7}), 1)
        self.assertIsNone(inf.rail_tier({"scalerank": 8}))
        self.assertIsNone(inf.rail_tier({"scalerank": None}))


class InsetTest(unittest.TestCase):
    def test_lines_never_join_main_map_and_inset(self):
        proj = MapProjection(min_x=-511.7, max_y=431.8, margin=80.0)
        line = [(-4.0, 40.0), (-3.0, 40.0), (-16.5, 28.3), (-16.2, 28.4)]  # mainland, then Tenerife
        pieces = list(inf.line_pieces(proj, line))
        self.assertEqual([r for r, _ in pieces], ["main", "Canarias"])
        for region, pts in pieces:
            for x, y in pts:
                self.assertEqual(proj.frame_at(x, y), None if region == "main" else region)


class PlaceTest(unittest.TestCase):
    def locator(self, owner):
        g = HexGrid(radius=10.0, cols=10, rows=10)
        proj = MapProjection(min_x=-511.7, max_y=431.8, margin=80.0)
        loc = inf.Locator.__new__(inf.Locator)
        loc.grid, loc.proj, loc.owner = g, proj, owner
        loc.county, loc.geoids = [-1] * g.size, []
        loc.muni_idx = type("Idx", (), {"locate": lambda self, x, y: -1})()
        loc.muni_codes, loc.muni_state, loc.cbsa_of = [], {}, {}
        return g, loc

    def test_land_cell_prefers_own_cell_then_nearest_spanish_within_rings(self):
        owner = [-1] * 100
        g, loc = self.locator(owner)
        own = g.cell_at(*g.center(5, 5))
        owner[own] = 3
        x, y = g.center(5, 5)
        self.assertEqual(loc.land_cell(x, y), own)
        near = g.neighbours(own)[0]
        owner[own], owner[near] = -1, 3  # sea at the point, Spanish land next door
        self.assertEqual(loc.land_cell(x, y), near)
        owner[near] = -2  # the nearest land is foreign: not a Spanish site
        self.assertEqual(loc.land_cell(x, y), -1)
        owner[near] = -1
        far = g.neighbours(g.neighbours(g.neighbours(own)[0])[0])[3]
        if far not in g.neighbours(own) and far != own:
            owner[far] = 3
            self.assertEqual(loc.land_cell(x, y, rings=1), -1)  # out of reach

    def test_known_spanish_site_skips_a_foreign_own_cell(self):
        owner = [-1] * 100
        g, loc = self.locator(owner)
        own = g.cell_at(*g.center(5, 5))
        owner[own] = -2
        near = g.neighbours(own)[1]
        owner[near] = 7
        x, y = g.center(5, 5)
        self.assertEqual(loc.land_cell(x, y), -1)
        self.assertEqual(loc.land_cell(x, y, known_spanish=True), near)

    def test_site_under_the_inset_frame_is_dropped(self):
        owner = [0] * 100
        _, loc = self.locator(owner)
        self.assertIsNone(loc.place(-0.63, 35.7))  # Oran lands under the Canary frame


class AirportPassengersTest(unittest.TestCase):
    def test_eurostat_matches_by_icao_and_sorts_nulls_last(self):
        owner = [3] * 100
        g, loc = PlaceTest.locator(self, owner)
        x, y = g.center(5, 5)
        lon, lat = -3.0, 40.0
        loc.proj = type("P", (), {"hidden": lambda self, a, b: False, "__call__": lambda self, a, b: (x, y)})()
        mk = lambda i, icao, t="medium_airport": {"id": i, "icao": icao, "ident": icao, "name": f"{i} Airport", "city": None, "type": t, "lon": lon, "lat": lat}
        sites = [mk("AAA", "LEAA"), mk("BBB", "LEBB", "large_airport"), mk("CCC", "LECC")]
        traffic = [{"icao": "LECC", "passengers": 5_000_000, "year": 2025}, {"icao": "LEZZ", "passengers": 9, "year": 2025}]
        out = inf.build_airports(loc, sites, {}, traffic)
        self.assertEqual([a["id"] for a in out], ["CCC", "BBB", "AAA"])
        self.assertEqual((out[0]["passengers"], out[0]["passengers_year"], out[0]["icao"]), (5_000_000, 2025, "LECC"))
        self.assertIsNone(out[1]["passengers"])
        self.assertIsNone(out[1]["passengers_year"])
        extra = inf.build_airports(loc, sites, {}, traffic + [{"icao": "LEXX", "passengers": 7, "year": 2025}], [mk("XXX", "LEXX", "small_airport")])
        self.assertEqual(extra[1]["id"], "XXX")  # a Eurostat airport OurAirports lists without scheduled service


if __name__ == "__main__":
    unittest.main()
