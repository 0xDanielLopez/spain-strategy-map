"""resources.py y wonders.py con datos sintéticos: filtro de combustible, deduplicado por id UNESCO y casillas."""

import unittest

from pipeline.build import resources, wonders
from pipeline.core.hexgrid import HexGrid
from pipeline.sources import gppd, wikidata_heritage as wd


def plant(name, fuel, mw, year=None, lon=-3.0, lat=40.0):
    return {"id": name, "name": name, "fuel": fuel, "capacity_mw": mw, "lat": lat, "lon": lon, "year": year, "owner": None}


def fake_place(lon, lat):
    if lon > 100:  # sin casilla
        return None
    return {"x": 1.0, "y": 2.0, "cell": 7, "state": "AN" if lat < 40 else "MD", "county": "28079", "cbsa": None}


class Resources(unittest.TestCase):
    def test_fuel_filter_and_drop(self):
        plants = [plant("A", "Nuclear", 1000.0, 1983), plant("B", "Coal", 500.0), plant("C", "Wind", 30.0),
                  plant("D", "Hydro", 50.0), plant("E", "Gas", 400.0, lon=200.0), plant("F", "Solar", 5.0)]
        items, dropped = resources.build_items(plants, fake_place)
        self.assertEqual(sorted(i["type"] for i in items), ["hydro", "nuclear"])
        self.assertEqual(dropped, ["E"])
        nuc = next(i for i in items if i["type"] == "nuclear")
        self.assertIn("1983", nuc["detail"])
        hyd = next(i for i in items if i["type"] == "hydro")
        self.assertNotIn("None", hyd["detail"])

    def test_summary_never_invents_zero(self):
        items, _ = resources.build_items([plant("D", "Hydro", 50.0), plant("H", "Hydro", 25.5, lat=39.0)], fake_place)
        s = resources.summarise(items)
        self.assertEqual(s["national"]["hydro"], {"count": 2, "value": 75.5, "unit": "MW"})
        self.assertEqual(s["national"]["nuclear"]["count"], 0)
        self.assertIsNone(s["national"]["nuclear"]["value"])
        self.assertEqual(set(s["states"]), {"AN", "MD"})
        self.assertNotIn("nuclear", s["states"]["AN"])

    def test_tidy_name(self):
        self.assertEqual(resources.tidy_name("SALTO DE LA MUELA"), "Salto de la Muela")
        self.assertEqual(resources.tidy_name("Almaraz"), "Almaraz")

    def test_gppd_rows_only_spain_and_no_zero_for_missing(self):
        rows = [{"country": "ESP", "name": "X", "primary_fuel": "Hydro", "capacity_mw": "10", "latitude": "40",
                 "longitude": "-3", "commissioning_year": "", "gppd_idnr": "1"},
                {"country": "PRT", "name": "Y", "primary_fuel": "Hydro", "capacity_mw": "10", "latitude": "40",
                 "longitude": "-8"},
                {"country": "ESP", "name": "Z", "primary_fuel": "Gas", "capacity_mw": "", "latitude": "40", "longitude": "-3"}]
        out = gppd.parse_rows(rows)
        self.assertEqual([p["name"] for p in out], ["X", "Z"])
        self.assertIsNone(out[0]["year"])
        self.assertIsNone(out[1]["capacity_mw"])


def hrow(qid, label, unesco, points, part_of=(), has_parts=False, criteria=()):
    return {"qid": qid, "label": label, "unesco": unesco, "points": points, "part_of": list(part_of),
            "has_parts": has_parts, "criteria": list(criteria)}


class Wonders(unittest.TestCase):
    ROWS = [
        hrow("Q2", "Cueva de Altamira (cueva)", "310", [(-4.12, 43.37)], part_of=["Q1"]),
        hrow("Q1", "Cueva de Altamira y arte rupestre", "310", [(-4.1, 43.4)], has_parts=True, criteria=["i", "iii"]),
        hrow("Q5", "Iglesia de San Pedro", "378-001", [(-1.0, 41.0)], part_of=["Q4"]),
        hrow("Q6", "Torre de San Martín", "378-003", [(-1.1, 41.1)], part_of=["Q4"]),
        hrow("Q4", "Arquitectura Mudéjar de Aragón", "378", [(-1.2, 41.2)], has_parts=True, criteria=["iv"]),
        hrow("Q9", "Doñana", "685", [(-6.4, 37.0)], criteria=["vii", "ix", "x"]),
        hrow("Q10", "Ibiza", "417rev", [(1.4, 38.9)], criteria=["ii", "iv", "ix"]),
        hrow("Q11", "Bosques de hayas", "1133ter", [(22.5, 48.9)], has_parts=True, criteria=["ix"]),
    ]

    def test_dedupe_by_unesco_id(self):
        out = {r["unesco"]: r for r in wonders.dedupe_heritage(self.ROWS)}
        self.assertEqual(set(out), {"310", "378", "685", "417", "1133"})
        self.assertEqual(out["310"]["qid"], "Q1")  # el principal, no el componente
        self.assertEqual(out["378"]["qid"], "Q4")
        self.assertTrue(out["378"]["serial"])
        self.assertFalse(out["685"]["serial"])
        self.assertEqual(out["685"]["kind"], "natural")
        self.assertEqual(out["417"]["kind"], "landmark")  # criterios culturales y naturales
        self.assertIn(out["378"]["kind"], ("monument",))
        self.assertIsNone(out["1133"]["point"])  # su coordenada está fuera de España

    def test_base_id_and_kind(self):
        self.assertEqual(wonders.base_id("669bis-007"), "669")
        self.assertEqual(wonders.base_id("1133ter"), "1133")
        self.assertEqual(wonders.kind_of([]), "landmark")

    def test_make_wonders_and_missing(self):
        heritage = wonders.dedupe_heritage(self.ROWS)
        parks = wonders.dedupe_parks([{"qid": "Q20", "label": "Parque nacional de Monfragüe", "points": [(-5.97, 39.82)]},
                                      {"qid": "Q20", "label": "Parque nacional de Monfragüe", "points": [(-5.97, 39.82)]},
                                      {"qid": "Q21", "label": "Parque Nacional de Cabrera", "points": [(150.0, 10.0)]}])
        self.assertEqual(len(parks), 2)
        w, missing = wonders.make_wonders(heritage, parks, fake_place)
        rules = {x["rule"] for x in w}
        self.assertEqual(rules, {"patrimonio_mundial", "parque_nacional"})
        self.assertTrue(all(x["metrics"] == {} for x in w))
        self.assertEqual(sum(1 for x in w if x["rule"] == "parque_nacional"), 1)
        self.assertEqual(len(missing), 2)  # las hayas (sin punto en España) y el parque fuera de España
        ranks = [x["rank"] for x in w if x["rule"] == "patrimonio_mundial"]
        self.assertEqual(ranks, list(range(1, len(ranks) + 1)))
        self.assertEqual(wonders.short_park("Parque nacional de Monfragüe"), "Monfragüe")

    def test_parse_wikidata(self):
        b = [{"item": {"value": "http://www.wikidata.org/entity/Q1"}, "itemLabel": {"value": "X"},
              "unesco": {"value": "5"}, "coord": {"value": "Point(-3.5 40.25)"},
              "crit": {"value": "criterion (iv)"}, "partOf": {"value": "http://www.wikidata.org/entity/Q9"},
              "hasParts": {"value": "true"}}]
        r = wd.parse_heritage(b)[0]
        self.assertEqual((r["points"], r["criteria"], r["part_of"], r["has_parts"]), ([(-3.5, 40.25)], ["iv"], ["Q9"], True))
        self.assertEqual(wd.USER_AGENT, "spain-strategy-map/1.0 (open-source map project)")


class Cells(unittest.TestCase):
    def test_land_cell_nearest_within_two_rings(self):
        grid = HexGrid(radius=10.0, cols=10, rows=10)
        owner = [-1] * grid.size
        target = grid.index(5, 5)
        owner[target] = 0
        loc = resources.Locator.__new__(resources.Locator)
        loc.grid, loc.owner = grid, owner

        class P:
            @staticmethod
            def frame_at(x, y):
                return None

        loc.proj = P
        x, y = grid.center(*grid.col_row(grid.index(6, 5)))  # una casilla de mar al lado
        self.assertEqual(loc.land_cell(x, y), target)
        x, y = grid.center(1, 1)  # lejos de la tierra
        self.assertEqual(loc.land_cell(x, y), -1)


if __name__ == "__main__":
    unittest.main()
