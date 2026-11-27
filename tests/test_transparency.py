"""pipeline.build.transparency and the privacy assertion of pipeline.check, on invented data only."""

import unittest

from pipeline import check
from pipeline.build import transparency as T

CRIME = {
    "years": ["2024", "2025"], "vintage": "Balance ficticio",
    "typologies": [{"key": "total", "label": "Total"}, {"key": "theft", "label": "Hurtos"}],
    "municipalities": {"99001": {"name": "Villa Ejemplo", "2024": {"total": 10, "theft": 4}, "2025": {"total": 12, "theft": 5}}},
    "provinces": {"ES": {"name": "España", "2025": {"total": 12, "theft": 5}, "2024": {"total": 10, "theft": 4}},
                  "99": {"name": "Provincia Ejemplo", "2025": {"total": 12, "theft": 5}}},
    "ccaa": {"98": {"name": "Comunidad Ejemplo", "2025": {"total": 12, "theft": 5}}},
}
INE = {"99001": {"pop": 25000}, "99002": {"pop": 5000}}
LAU = {"municipalities": [{"code": "99001", "province": "99", "ccaa": "98"}, {"code": "99002", "province": "99", "ccaa": "98"}]}


class Safety(unittest.TestCase):
    def test_shape_and_population(self):
        d = T.build_safety(CRIME, INE, LAU, {"98": "ZZ"}, "2026-11-27")
        self.assertEqual(d["national"]["population"], 30000)
        self.assertEqual(d["national"]["population_year"], 2026)
        self.assertEqual(d["ccaa"]["ZZ"]["population"], 30000)
        self.assertEqual(d["provinces"]["99"]["population"], 30000)
        self.assertEqual(d["municipalities"]["99001"]["2025"]["total"], 12)
        self.assertEqual(d["municipalities"]["99001"]["population"], 25000)
        self.assertEqual({t["key"]: t["additive"] for t in d["typologies"]}, {"total": False, "theft": True})
        self.assertEqual(check.privacy_violations(d), [])


class Boja(unittest.TestCase):
    B = {"retrieved": "2026-11-27", "section_names": {"1": "Disposiciones generales"},
         "years": {"2025": {"by_section": {"1": 3, "mixto": 1}, "by_org": {
             "Consejería Ficticia": {"1": 3}, "Persona Inventada Pérez": {"mixto": 1}}}}}

    def test_private_issuers_are_grouped(self):
        d = T.build_boja(self.B)
        names = [g["name"] for g in d["by_organisation"]]
        self.assertIn("Consejería Ficticia", names)
        self.assertNotIn("Persona Inventada Pérez", names)
        self.assertEqual(names[-1], T.OTHER_ORG)
        self.assertEqual(d["by_organisation"][-1]["counts"], {"2025": 1})
        self.assertEqual(sum(d["by_year_section"]["2025"].values()), 4)


class Junta(unittest.TestCase):
    A = {"n": 10, "n_amount": 10, "amount_sin_iva": 1234.5, "n_bidders_known": 9, "n_single_bidder": 4,
         "n_lt_15000": 9, "n_lt_40000": 10, "n_band_15000": 2, "n_band_40000": 0}
    J = {"vintage": "x", "year_meaning": "y", "thresholds_eur": [15000, 40000], "province_codes": {"41": "Sevilla"},
         "years": {"2025": {"provinces": {"41": A, "sin_provincia": A}, "organs": {"Instituto Ficticio": {"n": 10, "n_amount": 10, "amount_sin_iva": 1234.5}}}}}

    def test_special_provinces_are_not_provinces(self):
        d = T.build_junta(self.J)
        self.assertEqual(list(d["provinces"]), ["41"])
        self.assertIn("sin_provincia", d["unassigned"])
        self.assertEqual(d["provinces"]["41"]["2025"]["single_bidder"], 4)
        self.assertEqual(d["provinces"]["41"]["name"], "Sevilla")
        self.assertEqual(d["organs"][0]["by_year"]["2025"], {"n": 10, "amount": 1234.5})
        self.assertEqual(check.privacy_violations(d), [])


class Privacy(unittest.TestCase):
    def test_keys_and_values_are_caught(self):
        self.assertTrue(check.privacy_violations({"adjudicatario": "x"}))
        self.assertTrue(check.privacy_violations({"a": {"winner_name": 1}}))
        self.assertTrue(check.privacy_violations({"a": ["12345678Z"]}))  # DNI shape (invented)
        self.assertTrue(check.privacy_violations({"a": "X1234567L"}))   # NIE shape (invented)
        self.assertTrue(check.privacy_violations({"a": "B1234567J"}))   # NIF shape (invented)
        self.assertEqual(check.privacy_violations({"name": "Consejería Ficticia", "n": 3, "codes": ["41", "41091"]}), [])


if __name__ == "__main__":
    unittest.main()
