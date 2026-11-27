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


class NewLenses(unittest.TestCase):
    """Housing, migration and crime terms on invented municipalities (no real rows)."""

    HOUSING = {"municipalities": {"99001": {"dwellings_total": 100, "dwellings_primary": 60, "dwellings_non_primary": 40,
                                             "tourist_homes": 10, "tourist_beds": 50},
                                   "99002": {"dwellings_total": 200, "dwellings_primary": 190, "dwellings_non_primary": 10,
                                             "tourist_homes": None, "tourist_beds": None}}}
    MIGRATION = {"municipalities": {"99001": {
        "total": {"2021": 280, "2022": 290, "2023": 300, "2024": 310, "2026": 330},
        "foreign": {"2021": 20, "2026": 60}, "born_abroad": {"2026": 90},
        "immigrations_abroad": {"2022": 3, "2023": 6, "2024": 9}}}}
    CRIME = {"municipalities": {"99001": {"2025": {"total": 33, "burglary_dwellings": 3}, "2024": {"total": 30}}}}
    INE = {"99001": {"pop": 330}, "99002": {"pop": 500}}

    def recs(self):
        return lenses.merge_records(["99001", "99002", "99003"], self.INE, self.HOUSING, self.MIGRATION, self.CRIME)

    def test_merge_keeps_missing_as_none(self):
        a, b, c = self.recs()
        self.assertEqual((a["dw_total"], a["foreign_2026"], a["imm_sum"], a["imm_pop_sum"]), (100, 60, 18, 900))
        self.assertIsNone(b["tourist_homes"])
        self.assertIsNone(b["foreign_2026"])
        self.assertIsNone(b["crime_total"])
        self.assertIsNone(c["dw_total"])  # not in any table

    def test_terms(self):
        a, b, _ = self.recs()
        self.assertEqual(lenses._terms_non_primary(a), (40, 100))
        self.assertEqual(lenses._terms_tourist_homes(a), (10, 100))
        self.assertIsNone(lenses._terms_tourist_homes(b))
        self.assertEqual(lenses._terms_tourist_beds(a), (5000.0, 330))  # beds per 100 inhabitants
        self.assertEqual(lenses._terms_immigration(a), (18000.0, 900))  # mean over mean = 20 per 1,000 a year
        self.assertEqual(lenses._terms_foreign_change(a), (60, 20))
        self.assertEqual(lenses._terms_born_abroad(a), (90, 330))
        self.assertEqual(lenses._terms_crime(a), (33000.0, 330))
        self.assertEqual(lenses._terms_burglary(a), (3000.0, 330))
        self.assertIsNone(lenses._terms_crime(b))

    def test_immigration_needs_all_three_years(self):
        mig = {"municipalities": {"99001": {"total": {"2022": 1, "2023": 1, "2024": 1}, "immigrations_abroad": {"2022": 3, "2023": None, "2024": 9}}}}
        r = lenses.merge_records(["99001"], self.INE, self.HOUSING, mig, self.CRIME)[0]
        self.assertIsNone(r["imm_sum"])

    def test_crime_hex_needs_90_percent_of_people_with_data(self):
        recs = self.recs()
        # hex 0: municipality 0 (330 people, crime) + municipality 1 (500, no crime): 40 % covered -> null
        self.assertIsNone(lenses.hex_ratio([(0, 1.0), (1, 1.0)], recs, lenses._terms_crime))
        self.assertAlmostEqual(lenses.hex_ratio([(0, 1.0)], recs, lenses._terms_crime), 100.0)

    def test_housing_density_by_dwellings(self):
        recs = self.recs()
        self.assertAlmostEqual(lenses.hex_density([(0, 1.0), (1, 1.0)], recs, 100.0, "dw_total"), 3.0)
        self.assertIsNone(lenses.hex_density([(0, 1.0), (2, 1.0)], recs, 100.0, "dw_total"))  # municipality 2 has none


if __name__ == "__main__":
    unittest.main()
