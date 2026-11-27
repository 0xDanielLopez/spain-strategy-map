"""Area allocation and hex formulas of the INE lenses on a synthetic 2-hex / 3-municipality case."""

import unittest
from collections import Counter

from pipeline.build import lenses
from pipeline.build.world import muni_fractions


# Hex 0: 30 lattice points of municipality 0 and 20 of municipality 1; hex 1: 10 of municipality 0 and 10 of 2
# (points that fell in water hexes are never counted).
COUNTS = {0: Counter({0: 30, 1: 20}), 1: Counter({0: 10, 2: 10})}
FRAC = muni_fractions(COUNTS)
RECS = [
    {"pop": 1000, "pop_2021": 800, "age_mean": 40.0, "hh_size": 2.0, "income_pp": 10000.0, "pop15": 800, "higher_ed": 80},
    {"pop": 200, "pop_2021": 200, "age_mean": 50.0, "hh_size": 4.0, "income_pp": 20000.0, "pop15": 100, "higher_ed": 10},
    {"pop": 100, "pop_2021": None, "age_mean": None, "hh_size": 1.0, "income_pp": None, "pop15": None, "higher_ed": None},
]


class Allocation(unittest.TestCase):
    def test_fractions_sum_to_one(self):
        sums = Counter()
        for parts in FRAC.values():
            for k, f in parts:
                sums[k] += f
        for k in range(3):
            self.assertAlmostEqual(sums[k], 1.0, places=12)
        self.assertEqual(dict(FRAC[0])[0], 0.75)
        self.assertEqual(dict(FRAC[1])[0], 0.25)

    def test_hex_pop_conserves_people(self):
        self.assertAlmostEqual(lenses.hex_pop(FRAC[0], RECS), 950.0)
        self.assertAlmostEqual(lenses.hex_pop(FRAC[1], RECS), 350.0)
        self.assertAlmostEqual(sum(lenses.hex_pop(FRAC[h], RECS) for h in FRAC), 1300.0)


class Formulas(unittest.TestCase):
    def test_density(self):
        self.assertAlmostEqual(lenses.hex_density(FRAC[0], RECS, 50.0), 950 / 50)
        self.assertAlmostEqual(lenses.hex_density(FRAC[1], RECS, 20.0), 350 / 20)
        self.assertIsNone(lenses.hex_density(FRAC[0], RECS, 0.0))

    def test_growth_only_with_both_values(self):
        self.assertAlmostEqual(lenses.hex_ratio(FRAC[0], RECS, lenses._terms_growth) - 1, 950 / 800 - 1)
        # hex 1: municipality 2 has no 2021 value and holds 100 of 350 people -> 71 % covered -> null
        self.assertIsNone(lenses.hex_ratio(FRAC[1], RECS, lenses._terms_growth))

    def test_household_weighted_by_households(self):
        # hex 0: 950 people in 375 + 50 households; a mean of the sizes (2, 4) would say 3
        self.assertAlmostEqual(lenses.hex_ratio(FRAC[0], RECS, lenses._terms_household), 950 / 425)
        self.assertAlmostEqual(lenses.hex_ratio(FRAC[1], RECS, lenses._terms_household), 350 / 225)

    def test_coverage_mask(self):
        age = lenses.INE_LENSES["age"][0]
        self.assertAlmostEqual(lenses.hex_ratio(FRAC[0], RECS, age), (750 * 40 + 200 * 50) / 950)
        self.assertIsNone(lenses.hex_ratio(FRAC[1], RECS, age))  # 250 of 350 people have a value: 71 % < 90 %
        recs = [dict(r) for r in RECS]
        recs[2]["age_mean"] = 30.0
        self.assertAlmostEqual(lenses.hex_ratio(FRAC[1], recs, age), (250 * 40 + 100 * 30) / 350)

    def test_higher_education_uses_population_15_plus(self):
        self.assertAlmostEqual(lenses.hex_ratio(FRAC[0], RECS, lenses._terms_higher_ed), (60 + 10) / (600 + 100))
        self.assertIsNone(lenses.hex_ratio(FRAC[1], RECS, lenses._terms_higher_ed))

    def test_domain_log_ignores_zero(self):
        d = lenses.percentile_domain([0, 0, 5, 50, 500, None], True)
        self.assertTrue(d[0] > 0 and d[1] > d[0])


if __name__ == "__main__":
    unittest.main()
