"""pipeline.build.economy on synthetic data: GDP imputation, footprints, yields, cell nudge, ranks and peers."""

import unittest

from pipeline.build import BUILDERS, economy
from pipeline.core.hexgrid import HexGrid


def jobs(total, **sections):
    return {"total": total, "sections": {k.upper(): v for k, v in sections.items()} or None, "sectors4": None}


class ImputeGdp(unittest.TestCase):
    def test_conservation_and_absent_municipalities(self):
        codes = ["28001", "28002", "28003", "08001", "08002"]
        pop = {"28001": 1000, "28002": 500, "28003": 300, "08001": 700, "08002": 100}
        jm = {"28001": jobs(400), "28002": jobs(200), "08001": jobs(350)}
        gdp, stats = economy.impute_gdp(codes, pop, jm, {"28": 9.0e9, "08": 3.0e9})
        self.assertAlmostEqual(sum(gdp[c] for c in codes[:3]), 9.0e9, delta=1e-6 * 9.0e9)
        self.assertAlmostEqual(gdp["08001"] + gdp["08002"], 3.0e9, delta=3e3)
        # 28003 is absent: E = 300 * (600/1500) = 120; total E = 720
        self.assertAlmostEqual(gdp["28003"], 9.0e9 * 120 / 720, delta=1)
        # 08002: ratio 350/700 = 0.5 -> E = 50
        self.assertAlmostEqual(gdp["08002"], 3.0e9 * 50 / 400, delta=1)
        self.assertEqual(set(stats), {"28", "08"})

    def test_province_without_gdp_is_skipped_and_empty_province_raises(self):
        gdp, stats = economy.impute_gdp(["01001"], {"01001": 5}, {"01001": jobs(2)}, {})
        self.assertEqual((gdp, stats), ({}, {}))
        with self.assertRaises(RuntimeError):
            economy.impute_gdp(["02001"], {"02001": 0}, {}, {"02": 1.0})


class Yields(unittest.TestCase):
    def test_sections_mapping(self):
        s = {k: 1 for k in economy.SECTIONS}
        s.update({"A": 10, "B": 1, "C": 100, "D": 2, "E": 3, "F": 20, "J": 7, "M": 5, "R": 4})
        y = economy.yields_of(s)
        self.assertEqual(y, {"food": 10, "production": 126, "science": 12, "culture": 4})

    def test_sectors4_members(self):
        rec = {"total": 50, "sections": None, "sectors4": {"agricultura": 5, "industria": 7, "construccion": 3, "servicios": 35}}
        self.assertEqual(economy.yields_of(None, rec["sectors4"]), {"food": 5, "production": 10, "science": 0, "culture": 0})
        jm = {"a": jobs(100, a=10, c=20, j=3), "b": rec}
        agg = economy.aggregate(["a", "b", "zz"], jm)
        self.assertEqual(agg["employed"], 150)
        self.assertEqual(agg["jobs"]["a"], 10)  # sectors4 members are not in jobs
        self.assertEqual(agg["yields"]["food"], 15)
        self.assertEqual(agg["yields"]["production"], 30)
        self.assertEqual(agg["jobs_coverage"], round(100 / 150, 4))
        self.assertEqual(agg["employed_members"], [2, 3])

    def test_yield_keys_match_contract(self):
        self.assertEqual([y["key"] for y in economy.YIELDS], ["food", "production", "gold", "science", "culture"])
        self.assertEqual(next(y for y in economy.YIELDS if y["key"] == "gold")["unit"], "usd")
        self.assertEqual(economy.KEYS[0], "a")
        self.assertEqual(len(economy.KEYS), 21)


class Footprint(unittest.TestCase):
    def test_share_formula(self):
        codes = ["m0", "m1", "m2"]
        pop = {"m0": 100, "m1": 300, "m2": 50}
        # cell 0: m0 (100*1) vs m1 (300*0.25=75) -> city X has 100/175; cell 1: m1 only; cell 2: sea; cell 3: tie 50/50
        weights = [[[0, 1.0], [1, 0.25]], [[1, 0.75]], [], [[0, 0.5], [2, 1.0]]]
        owner = [0, 0, -1, 0]
        city_of = {"m0": "X", "m1": "Y", "m2": "Z"}
        out = economy.footprints(weights, owner, codes, pop, city_of)
        self.assertEqual(out["X"], {0, 3})  # 0.571 and exactly 0.5 both count
        self.assertEqual(out["Y"], {1})
        self.assertEqual(out["Z"], {3})
        self.assertNotIn(1, out.get("X", set()))


class Cells(unittest.TestCase):
    def test_unique_cell_nudge(self):
        grid = HexGrid(10.0, 6, 6)
        owner = [0] * grid.size
        start = grid.index(3, 3)
        x, y = grid.center(3, 3)
        cities = [{"id": f"c{i}", "name": f"c{i}", "x": x, "y": y, "cell": start} for i in range(4)]
        rep = economy.assign_cells(grid, owner, cities, {c["id"]: (0, {0}) for c in cities})
        cells = [c["cell"] for c in cities]
        self.assertEqual(len(set(cells)), 4)
        self.assertEqual(cells[0], start)
        self.assertEqual(len(rep["moved"]), 3)
        self.assertTrue(all(owner[c] >= 0 for c in cells))

    def test_snaps_water_to_land(self):
        grid = HexGrid(10.0, 6, 6)
        owner = [-1] * grid.size
        land = grid.index(3, 4)
        owner[land] = 0
        c = {"id": "c", "name": "c", "x": 0.0, "y": 0.0, "cell": grid.index(3, 3)}
        economy.assign_cells(grid, owner, [c], {"c": (0, {0})})
        self.assertEqual(c["cell"], land)


class Ranks(unittest.TestCase):
    def rows(self):
        out = []
        for i, (p, g, gr) in enumerate([(900, 50, 0.01), (500, 70, None), (100, 10, 0.05)]):
            out.append({"id": f"c{i}", "population": p, "gdp": g, "growth": gr,
                        "yields": {"food": 3 - i, "production": None, "gold": g, "science": 1, "culture": 1}})
        return out

    def test_ranks(self):
        rows = self.rows()
        economy.add_ranks(rows, skip=("gdp_per_capita",))
        self.assertEqual([r["ranks"]["population"] for r in rows], [1, 2, 3])
        self.assertEqual([r["ranks"]["gdp"] for r in rows], [2, 1, 3])
        self.assertEqual([r["ranks"]["growth"] for r in rows], [2, None, 1])
        self.assertEqual([r["ranks"]["production"] for r in rows], [None] * 3)
        self.assertEqual([r["ranks"]["science"] for r in rows], [1, 2, 3])  # ties keep population order
        self.assertEqual([r["ranks"]["gdp_per_capita"] for r in rows], [None] * 3)

    def test_state_gdp_per_capita(self):
        rows = self.rows()
        economy.add_ranks(rows)
        self.assertEqual([r["ranks"]["gdp_per_capita"] for r in rows], [3, 1, 2])

    def test_peers(self):
        cities = [{"id": str(i), "population": p} for i, p in enumerate([1000, 800, 400, 390, 100, 90, 10])]
        economy.add_peers(cities)
        self.assertEqual(cities[2]["peers"][:2], ["3", "1"])
        self.assertTrue(all(len(c["peers"]) == 5 and c["id"] not in c["peers"] for c in cities))


class Numbers(unittest.TestCase):
    def test_growth_and_income(self):
        ine = {"a": {"pop": 110, "pop_2021": 100, "income_pp": 10000.0}, "b": {"pop": 300, "pop_2021": None, "income_pp": 20000.0},
               "c": {"pop": 100, "pop_2021": 100, "income_pp": None}}
        self.assertEqual(economy.growth_of(["a", "b", "c"], ine), round(210 / 200 - 1, 4))
        self.assertEqual(economy.income_of(["a", "b", "c"], ine), round((1.1e6 + 6e6) / 410))
        self.assertEqual(economy.population_of(["a", "b", "x"], ine), 410)


class Registry(unittest.TestCase):
    def test_registered_and_ordered(self):
        self.assertIn("economy", BUILDERS)
        self.assertNotIn("base", BUILDERS)
        names = list(BUILDERS)
        self.assertLess(names.index("world"), names.index("economy"))


if __name__ == "__main__":
    unittest.main()
