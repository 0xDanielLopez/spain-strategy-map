"""Tests for the Spain map projection with the Canary Islands inset."""

import unittest

from pipeline.core.geo import INSETS, Albers, MapProjection, fit_bounds

MADRID = (-3.70, 40.42)
FINISTERRE = (-9.30, 42.88)
MENORCA = (4.33, 39.88)
CEUTA = (-5.32, 35.89)
MELILLA = (-2.94, 35.29)
LARACHE = (-6.15, 35.19)
CANARY = {"Las Palmas": (-15.42, 28.12), "Santa Cruz": (-16.25, 28.47), "El Hierro": (-17.98, 27.75)}


class GeoSpainTest(unittest.TestCase):
    def setUp(self):
        self.p = MapProjection(min_x=-980, max_y=520, margin=80)

    def test_round_trip(self):
        for name, (lon, lat) in {"Madrid": MADRID, "Finisterre": FINISTERRE, "Menorca": MENORCA,
                                 "Ceuta": CEUTA, "Melilla": MELILLA, **CANARY}.items():
            lon2, lat2 = self.p.inverse(*self.p(lon, lat))
            self.assertAlmostEqual(lon, lon2, delta=1e-6, msg=name)
            self.assertAlmostEqual(lat, lat2, delta=1e-6, msg=name)

    def test_main_matches_albers(self):
        x, y = Albers(36, 44, 40, -3)(*FINISTERRE)
        X, Y = self.p(*FINISTERRE)
        self.assertAlmostEqual(X, x + 980 + 80, places=6)
        self.assertAlmostEqual(Y, 520 - y + 80, places=6)

    def test_canary_in_frame(self):
        for name, (lon, lat) in CANARY.items():
            self.assertEqual(self.p.region_of(lon, lat), "Canarias", name)
            self.assertEqual(self.p.frame_at(*self.p(lon, lat)), "Canarias", name)
        others = {"Madrid": MADRID, "Ceuta": CEUTA, "Melilla": MELILLA, "Larache": LARACHE, "Cartagena": (-0.98, 37.60),
                  "Formentera": (1.45, 38.70), "Cabo de Gata": (-2.19, 36.72), "Cabrera": (2.93, 39.15)}
        for name, (lon, lat) in others.items():
            self.assertEqual(self.p.region_of(lon, lat), "main", name)
            self.assertIsNone(self.p.frame_at(*self.p(lon, lat)), name)

    def test_hidden(self):
        f = self.p.frames()[0]
        lon, lat = self.p._albers.inverse(*self.p._unshift((f["x0"] + f["x1"]) / 2, (f["y0"] + f["y1"]) / 2))
        self.assertTrue(self.p.hidden(lon, lat))
        self.assertFalse(self.p.hidden(*MADRID))
        self.assertFalse(self.p.hidden(*LARACHE))
        self.assertFalse(self.p.hidden(*CANARY["Las Palmas"]))

    def test_ring_region_single(self):
        ring = [(-13.2, 28.0), (-12.5, 28.0), (-12.5, 28.6), (-13.2, 28.6)]  # straddles lon -13.0
        region = self.p.ring_region(ring)
        pts = self.p.project_ring(ring)
        self.assertEqual(pts, [self.p(lo, la, region) for lo, la in ring])
        self.assertEqual(region, "main")  # bbox centre lon -12.85 is outside the box

    def test_frames(self):
        f = self.p.frames()
        self.assertEqual(len(f), 1)
        self.assertLess(f[0]["y0"], f[0]["y1"])
        self.assertLess(f[0]["x0"], f[0]["x1"])

    def test_fit_bounds(self):
        pts = [Albers(36, 44, 40, -3)(*FINISTERRE), Albers(36, 44, 40, -3)(*MENORCA)]
        min_x, max_y, w, h = fit_bounds(pts, INSETS, margin=80)
        self.assertAlmostEqual(min_x, min(pts[0][0], INSETS[0].frame[0]))
        self.assertGreaterEqual(max_y, pts[0][1])
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)


if __name__ == "__main__":
    unittest.main()
