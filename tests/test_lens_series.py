"""lens_series: INE series parsing and the per-year hex values, on synthetic data only."""

import unittest

from pipeline.build import lens_series
from pipeline.build.lenses import INE_LENSES, hex_density, hex_ratio
from pipeline.sources import ine_series

INCOME = [
    "Municipios;Distritos;Secciones;Indicadores de renta media;Periodo;Total",
    "01001 Alegría;;;Renta neta media por persona;2024;17.698",
    "01001 Alegría;;;Renta neta media por persona;2023;16.429",
    "01001 Alegría;01001 distrito 01;;Renta neta media por persona;2024;99.999",
    "01001 Alegría;01001 distrito 01;0100101001;Renta neta media por persona;2024;88.888",
    "01002 Otra;;;Renta neta media por persona;2024;.",
    "Total Nacional;;;Renta neta media por persona;2024;15.000",
]
DEMO = [
    "Municipios;Distritos;Secciones;Indicadores demográficos;Periodo;Total",
    "01001 Alegría;;;Edad media de la población;2024;41",
    "01001 Alegría;;;Edad media de la población;2023;40,8",
    "01001 Alegría;;;Población;2024;2.000",
    "01001 Alegría;;;Población;2023;1.900",
    "01001 Alegría;;;Tamaño medio del hogar;2024;2,5",
]
POP = [
    "Total Nacional;Municipios;Sexo;Periodo;Total",
    "Total Nacional;;Total;2026;49.618.622",
    "Total Nacional;01001 Alegría;Total;2026;3.000",
    "Total Nacional;01001 Alegría;Hombres;2026;1.500",
    "Total Nacional;01001 Alegría;Total;2025;2.900",
]


class SeriesSource(unittest.TestCase):
    def setUp(self):
        self.data = ine_series.build_series(INCOME, DEMO, POP)
        self.m = self.data["municipalities"]

    def test_only_municipal_rows_and_spanish_numbers(self):
        self.assertEqual(self.m["01001"]["income"], {"2024": 17698, "2023": 16429})
        self.assertEqual(self.m["01001"]["age"]["2023"], 40.8)
        self.assertEqual(self.m["01001"]["adrh_pop"], {"2024": 2000, "2023": 1900})
        self.assertEqual(self.m["01001"]["pop"], {"2026": 3000, "2025": 2900})
        self.assertEqual(set(self.m), {"01001"})

    def test_secrecy_mark_is_missing_not_zero(self):
        self.assertNotIn("01002", self.m)

    def test_years_ascending(self):
        self.assertEqual(self.data["years"]["income"], ["2023", "2024"])
        self.assertEqual(self.data["years"]["pop"], ["2025", "2026"])


class SeriesBuilder(unittest.TestCase):
    def test_year_records_use_that_years_population(self):
        munis = [{"income": {"2023": 10000, "2024": 12000}, "adrh_pop": {"2023": 100, "2024": 200}}, {"income": {"2024": 5000}}]
        r23 = lens_series.year_records(munis, "2023", lens_series.ATLAS_LENSES["income"])
        self.assertEqual(r23[0], {"pop": 100, "income_pp": 10000})
        self.assertEqual(r23[1], {"pop": None, "income_pp": None})

    def test_hex_value_is_weighted_by_year_population(self):
        munis = [{"income": {"2024": 10000}, "adrh_pop": {"2024": 100}}, {"income": {"2024": 20000}, "adrh_pop": {"2024": 300}}]
        recs = lens_series.year_records(munis, "2024", lens_series.ATLAS_LENSES["income"])
        v = hex_ratio([[0, 1.0], [1, 0.5]], recs, INE_LENSES["income"][0])
        self.assertAlmostEqual(v, (100 * 10000 + 150 * 20000) / 250)

    def test_hex_without_enough_covered_population_is_null(self):
        munis = [{"income": {"2024": 10000}, "adrh_pop": {"2024": 100}}, {"adrh_pop": {"2024": 900}}]
        recs = lens_series.year_records(munis, "2024", lens_series.ATLAS_LENSES["income"])
        self.assertIsNone(hex_ratio([[0, 1.0], [1, 1.0]], recs, INE_LENSES["income"][0]))
        self.assertIsNone(hex_density([[0, 1.0]], [{"pop": None}], 2.0))

    def test_compact_keeps_only_indexed_hexes(self):
        lenses = [{"id": "x", "years": [2020, 2021], "values": [[1, None, 3], [4, None, 6]], "domain": [0, 9]}]
        out = lens_series.compact(lenses, [0, 2])
        self.assertEqual(out["index"], [0, 2])
        self.assertEqual(out["lenses"][0]["values"], [[1, 3], [4, 6]])

    def test_mean_income_skips_missing(self):
        munis = [{"income": {"2024": 10000}, "adrh_pop": {"2024": 100}}, {"adrh_pop": {"2024": 900}}]
        self.assertEqual(lens_series.mean_income(munis, "2024"), 10000)
        self.assertIsNone(lens_series.mean_income(munis, "2020"))


if __name__ == "__main__":
    unittest.main()
