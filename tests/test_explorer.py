"""pipeline.build.explorer, economy.land_of and the new pipeline.check functions on synthetic data."""

import re
import unittest
from pathlib import Path

from pipeline import check
from pipeline.build import economy, explorer

NAMES = {k: f"Sector {k}" for k in economy.KEYS}


def jobs(**kw):
    out = {k: 0 for k in economy.KEYS}
    out.update(kw)
    return out


class Specialisations(unittest.TestCase):
    nat = jobs(a=10, c=40, g=30, i=10, t=5, u=5)  # total 100

    def test_lq_rule_and_order(self):
        # city total 10,000: i 2,000 (LQ 2.0), a 1,500 (LQ 1.5), c 3,000 (0.75, out), t 3,000 (excluded)
        total, spec = explorer.specialisations(jobs(a=1500, c=3000, i=2000, t=3000, g=500), self.nat)
        self.assertEqual(total, 10000)
        self.assertEqual([d["id"] for d in spec], ["i", "a"])
        self.assertEqual(spec[0]["lq"], 2.0)
        self.assertEqual(spec[0]["strength"], 1000)
        self.assertTrue(all(d["lq"] >= 1.25 for d in spec))

    def test_min_jobs_or_share(self):
        small = jobs(a=60, c=40)  # a: LQ 6 but 60 jobs = 60 % of a 100-job city, passes through the share
        self.assertEqual([d["id"] for d in explorer.specialisations(small, self.nat)[1]], ["a"])
        rare = jobs(a=1, c=999)  # nationally a is 0.1 % of jobs, so a small count already has LQ > 1.25
        self.assertEqual(explorer.specialisations(jobs(a=900, c=199_100), rare)[1], [])  # 900 jobs, 0.45 %
        self.assertEqual([d["id"] for d in explorer.specialisations(jobs(a=1000, c=199_000), rare)[1]], ["a"])

    def test_at_most_five_and_zero_allowed(self):
        nat = {k: 1 for k in explorer.SECTION_KEYS}
        j = {k: 100 for k in explorer.SECTION_KEYS[:8]}
        j.update({k: 1 for k in explorer.SECTION_KEYS[8:]})
        self.assertEqual(len(explorer.specialisations(j, nat)[1]), explorer.MAX_PER_CITY)
        self.assertEqual(explorer.specialisations(jobs(), self.nat), (0, []))

    def test_badge_is_top(self):
        _, spec = explorer.specialisations(jobs(a=1500, i=2000, g=6500), self.nat)
        b = explorer.badge_of(spec[0], NAMES)
        self.assertEqual(b["district"], spec[0]["id"])
        self.assertIn("veces", b["text"])
        self.assertIsNone(explorer.badge_of(None, NAMES))

    def test_icon_table_matches_web(self):
        js = (Path(__file__).resolve().parent.parent / "web/js/industry.js").read_text()
        body = re.search(r"CNAE_ICON_KEY = \{(.*?)\};", js, re.S).group(1)
        web = dict(re.findall(r"(\w): \"(\w+)\"", body))
        for k, v in explorer.ICON_KEY.items():
            self.assertEqual(web[k], v)


class Counties(unittest.TestCase):
    def test_row_nulls_and_values(self):
        muni = {"code": "01001", "name": "X", "province": "01", "ccaa": "16", "area_km2": 20.0}
        rec = {"pop": 1000, "pop_2021": 800, "age_mean": 44.1, "pct65": 0.2, "pct_spanish": 0.9, "hh_size": 2.5,
               "income_pp": 15000.0, "below60": None, "pop15": 800, "higher_ed": 200}
        row = explorer.county_row(muni, rec, "PV", None, 5)
        d = dict(zip(explorer.COLUMNS, row))
        self.assertEqual((d["density"], d["growth"], d["foreign"], d["higher_education"]), (50, 0.25, 0.1, 0.25))
        self.assertIsNone(d["poverty"])
        self.assertIsNone(d["auf"])
        empty = dict(zip(explorer.COLUMNS, explorer.county_row(muni, None, "PV", None, -1)))
        self.assertTrue(all(empty[k] is None for k in ("population", "density", "growth", "foreign", "income", "cell")))


class Citizens(unittest.TestCase):
    ine = {
        "a": {"pop": 1000, "pct65": 0.2, "pct_spanish": 0.9, "pop15": 800, "higher_ed": 200, "age_mean": 40.0},
        "b": {"pop": 3000, "pct65": 0.1, "pct_spanish": 0.8, "age_mean": 50.0},  # no education data
        "c": None,
    }

    def test_distributions_and_coverage(self):
        z = explorer.citizens_of(["a", "b", "c"], self.ine)
        self.assertEqual(z["age"]["total"], 4000)
        self.assertEqual(z["age"]["counts"], {"under65": 3500, "elder": 500})
        self.assertEqual(z["age"]["coverage"], [2, 3])
        self.assertEqual(z["education"]["total"], 800)
        self.assertEqual(z["education"]["base"], "Habitantes de 15 años o más")
        self.assertEqual(z["education"]["coverage"], [1, 3])
        self.assertEqual(z["nationality"]["counts"]["foreign"], 700)
        self.assertEqual(z["age"]["mean"], 47.5)
        for d in z.values():
            self.assertAlmostEqual(sum(d["shares"].values()), 1, places=9)
            self.assertEqual(sum(d["figures"].values()), explorer.CITIZEN_FIGURES)

    def test_no_data_is_null(self):
        self.assertTrue(all(v is None for v in explorer.citizens_of(["c"], self.ine).values()))

    def test_largest_remainder(self):
        self.assertEqual(sum(explorer.largest_remainder([1, 1, 1], 10)), 10)
        self.assertEqual(explorer.largest_remainder([0, 0], 10), [0, 0])


class Land(unittest.TestCase):
    def test_sums_over_members_and_null(self):
        cover = [[10, 20, 0, 40], [0, 0, 30, 60], [0, 0, 0, 0]]
        index = {"m0": 0, "m1": 1, "m2": 2}
        self.assertEqual(economy.land_of(["m0", "m1"], index, cover), {"forest": 0.1, "crop": 0.2, "developed": 0.3})
        self.assertIsNone(economy.land_of(["m2"], index, cover))
        self.assertIsNone(economy.land_of(["m0"], index, None))


class Checks(unittest.TestCase):
    def report(self):
        return check.Report(quiet=True)

    def test_districts_lq_below_threshold_fails(self):
        _, spec = explorer.specialisations(jobs(a=1500, i=2000, g=6500), Specialisations.nat)
        cities = [{"id": "X1"}]
        doc = explorer.build_districts(cities and [{"id": "X1", "jobs": jobs(a=1500, i=2000, g=6500)}],
                                       {"nation": {"jobs": Specialisations.nat}}, NAMES, 2024)
        r = self.report()
        check.check_districts_file(r, doc, cities)
        self.assertFalse(r.failed)
        doc["cities"]["X1"]["districts"][0]["lq"] = 1.1
        r = self.report()
        check.check_districts_file(r, doc, cities)
        self.assertTrue(r.failed)

    def test_citizens_sum_check(self):
        ine = Citizens.ine
        doc = explorer.build_citizens([{"id": "X1", "counties": ["a", "b"]}], ine, ["a", "b"])
        r = self.report()
        check.check_citizens_file(r, doc, [{"id": "X1"}])
        self.assertFalse(r.failed)
        doc["cities"]["X1"]["age"]["shares"]["elder"] = 0.9
        r = self.report()
        check.check_citizens_file(r, doc, [{"id": "X1"}])
        self.assertTrue(r.failed)

    def test_counties_rows_must_match_world(self):
        muni = {"code": "01001", "name": "X", "province": "01", "ccaa": "16", "area_km2": 20.0}
        doc = explorer.build_counties(["01001"], {"01001": muni}, {}, {"16": "PV"}, {}, [0], "v")
        world = {"counties": [{"geoid": "01001"}], "owner": [0]}
        r = self.report()
        check.check_counties_file(r, doc, world, [])
        self.assertFalse(r.failed)
        world["counties"].append({"geoid": "01002"})
        r = self.report()
        check.check_counties_file(r, doc, world, [])
        self.assertTrue(r.failed)

    def test_land_check(self):
        r = self.report()
        check.check_land(r, "t", [{"land": {"forest": 0.5, "crop": 0.6, "developed": 0.1}}])
        self.assertTrue(r.failed)


if __name__ == "__main__":
    unittest.main()
