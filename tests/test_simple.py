"""simple.json builder: names, weighted means, quantiles, simplification, null rule and findings, on synthetic data."""

import unittest

from pipeline.build import simple


def row(code, pop, **v):
    vals = {k: None for k in simple.KEYS}
    vals.update(v)
    return [code, "x", code[:2], "01", pop] + [vals[k] for k in simple.KEYS]


class Names(unittest.TestCase):
    def test_article_goes_first(self):
        self.assertEqual(simple.fix_name("Palmas de Gran Canaria, Las"), "Las Palmas de Gran Canaria")
        self.assertEqual(simple.fix_name("Hospitalet de Llobregat, L'"), "L'Hospitalet de Llobregat")
        self.assertEqual(simple.fix_name("Coruña, A"), "A Coruña")
        self.assertEqual(simple.fix_name("Sevilla"), "Sevilla")

    def test_each_side_of_a_bilingual_name(self):
        self.assertEqual(simple.fix_name("Rioja, La/Rioja, Errioxa"), "La Rioja/Rioja, Errioxa")
        self.assertEqual(simple.fix_name("Pobla, La / Poble, El"), "La Pobla / El Poble")
        self.assertEqual(simple.fix_name("Alicante/Alacant"), "Alicante/Alacant")


class Numbers(unittest.TestCase):
    def test_weighted_mean_skips_missing_and_zero_population(self):
        rows = [row("01001", 100, income=10), row("01002", 300, income=20), row("01003", 50, income=None),
                row("01004", None, income=999)]
        self.assertAlmostEqual(simple.weighted_mean(rows, "income"), 17.5)
        self.assertIsNone(simple.weighted_mean([row("01003", 50)], "income"))

    def test_density_uses_area(self):
        rows = [row("01001", 100), row("01002", 300)]
        self.assertEqual(simple.aggregate(rows, "density", {"01001": 1, "01002": 3}), 100)

    def test_quantiles(self):
        xs = [1, 2, 3, 4, 5]
        self.assertEqual(simple.quantile(xs, 0.5), 3)
        self.assertEqual(simple.quantile(xs, 0.25), 2)
        self.assertAlmostEqual(simple.quantile(xs, 0.1), 1.4)

    def test_null_is_not_zero(self):
        self.assertIsNone(simple.to_value("income", None))
        self.assertIsNone(simple.round_value("growth", None))
        self.assertEqual(simple.to_value("income", 0.0), 0)
        self.assertEqual(simple.to_value("elderly", 0.209), 20.9)
        self.assertEqual(simple.to_value("age_mean", 43.9), 43.9)


class Shapes(unittest.TestCase):
    def test_simplify_keeps_triangle_and_drops_collinear(self):
        tri = [(0, 0), (50, 0), (0, 50)]
        self.assertEqual(simple.simplify(tri + [tri[0]], 0.6)[:-1], tri)
        line = [(0, 0), (10, 0.1), (20, 0), (30, 0.1), (40, 0)]
        self.assertEqual(simple.simplify(line, 0.6), [(0, 0), (40, 0)])

    def test_path_drops_degenerate_ring_and_small_parts(self):
        big = [(0, 0), (40, 0), (40, 40), (0, 40)]
        dot = [(100, 100), (100.2, 100), (100.1, 100.2)]
        d = simple.path_data([dot, big])
        self.assertEqual(d.count("M"), 1)
        self.assertTrue(d.startswith("M0 0"))
        self.assertEqual(simple.path_data([dot]).count("M"), 1)  # the main ring stays as a tiny triangle


class Findings(unittest.TestCase):
    def test_sentences(self):
        provs = [{"name": "Norte", "values": {"income": 20000}}, {"name": "Sur", "values": {"income": 10000}},
                 {"name": "Sin dato", "values": {"income": None}}]
        munis = [("20", 43.0, 18000)] * 3 + [("20", 43.2, 9000)] * 2 + [("41", 37.0, 9000)] * 3 + [("41", 37.1, 16000)] \
            + [("35", 28.0, 20000)]
        out = simple.income_findings(provs, 15000, munis, 40.4)
        self.assertEqual(out[0], "Al norte de Madrid, 6 de cada 10 municipios superan la renta media de España. "
                                 "Al sur, 4 de cada 10.")  # north 3/5; south 2/5 (Canarias count as south)
        self.assertEqual(out[1], "Norte tiene la renta más alta: 20.000 €.")
        self.assertEqual(out[2], "Sur, la más baja: 10.000 €. Norte la multiplica por 2,0.")


if __name__ == "__main__":
    unittest.main()
