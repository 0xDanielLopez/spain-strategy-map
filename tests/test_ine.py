import unittest

from pipeline.sources import ine

BOM = "﻿"


def rows(text, table):
    lines = text.strip().splitlines()
    import csv
    rd = csv.reader(lines, delimiter=";")
    ine.check_header(table, next(rd))
    return list(rd)


class NumberTest(unittest.TestCase):
    def test_spanish_numbers(self):
        self.assertEqual(ine.parse_number("17.698"), 17698)
        self.assertEqual(ine.parse_number("14.781,0"), 14781.0)
        self.assertEqual(ine.parse_number("6,6"), 6.6)
        self.assertEqual(ine.parse_number("41"), 41)
        self.assertEqual(ine.parse_number("49.618.622"), 49618622)
        for blank in (".", "", '""', " "):
            self.assertIsNone(ine.parse_number(blank))

    def test_municipal_code(self):
        self.assertEqual(ine.municipal_code("01001 Alegría-Dulantzi"), "01001")
        self.assertEqual(ine.municipal_code("03001 Atzúbia, l'"), "03001")
        for bad in ("Total Nacional", "", "28 Madrid", "28079", "02 Albacete"):
            self.assertIsNone(ine.municipal_code(bad))


INCOME = BOM + """Municipios;Distritos;Secciones;Indicadores de renta media;Periodo;Total
01001 Alegría-Dulantzi;;;Renta neta media por persona;2024;17.698
01001 Alegría-Dulantzi;;;Renta neta media por persona;2023;16.429
01001 Alegría-Dulantzi;01;;Renta neta media por persona;2024;99.999
01001 Alegría-Dulantzi;01;001;Renta neta media por persona;2024;88.888
01001 Alegría-Dulantzi;;;Renta neta media por hogar;2024;45.419
01002 Araba;;;Renta neta media por persona;2024;.
01002 Araba;;;Renta neta media por persona;2023;15.000
01003 Otra;;;Renta neta media por persona;2024;12.000
01003 Otra;;;Renta neta media por persona;2023;"""


class AdrhTest(unittest.TestCase):
    def test_header_validation(self):
        with self.assertRaises(ValueError):
            ine.check_header(ine.INCOME_TABLE, ["Municipios", "Secciones", "Distritos", "X", "Periodo", "Total"])
        ine.check_header(ine.INCOME_TABLE, ["﻿Municipios", "Distritos", "Secciones",
                         "Indicadores de renta media", "Periodo", "Total"])

    def test_municipal_filter_and_periods(self):
        rs = [r for r in rows(INCOME.replace(BOM, ""), ine.INCOME_TABLE)]
        data, codes = ine.collect(rs, ine.INCOME_TABLE, {ine.INCOME_LABEL: "income_pp"})
        self.assertEqual(codes, {"01001", "01002", "01003"})
        by = data["income_pp"]
        self.assertEqual(by["01001"], {"2024": 17698, "2023": 16429})  # district and section rows ignored
        self.assertIsNone(by["01002"]["2024"])
        # 2024 has 2 of 3 values (67 %), below 95 %: the pin falls back to 2023 only if it is complete enough
        # no period reaches 95 %: the best-covered one (2024: 2 values) wins over 2023 (2 values) by being later
        self.assertEqual(ine.pin_period(by, 3)[0], "2024")
        full = {"a": {"2024": None, "2023": 1}, "b": {"2024": 2, "2023": 3}}
        self.assertEqual(ine.pin_period(full, 2), ("2023", {"a": 1, "b": 3}))
        period, vals = ine.pin_period(by, 3, min_share=0.6)
        self.assertEqual(period, "2024")
        self.assertEqual(vals, {"01001": 17698, "01003": 12000})

    def test_relative_table_total_sex_only(self):
        text = ("Municipios;Distritos;Secciones;Sexo;Distribución de la renta por unidad de consumo;Periodo;Total\n"
                f"01001 A;;;Total;{ine.BELOW60_LABEL};2024;11,7\n"
                f"01001 A;;;Hombres;{ine.BELOW60_LABEL};2024;9,0\n"
                f"01001 A;01;;Total;{ine.BELOW60_LABEL};2024;5,0\n")
        data, _ = ine.collect(rows(text, ine.RELATIVE_TABLE), ine.RELATIVE_TABLE, {ine.BELOW60_LABEL: "below60"})
        self.assertEqual(data["below60"], {"01001": {"2024": 11.7}})

    def test_percent_to_fraction(self):
        label, div = ine.ADRH_FIELDS["pct65"][1], ine.ADRH_FIELDS["pct65"][2]
        self.assertEqual(div, 100)
        self.assertAlmostEqual(13.5 / div, 0.135)


class CensusTest(unittest.TestCase):
    def test_population(self):
        text = ("Total Nacional;Municipios;Sexo;Periodo;Total\n"
                "Total Nacional;;Total;2026;49.618.622\n"
                "Total Nacional;01001 Alegría-Dulantzi;Total;2026;2.981\n"
                "Total Nacional;01001 Alegría-Dulantzi;Hombres;2026;1.500\n"
                "Total Nacional;01001 Alegría-Dulantzi;Total;2021;2.800\n")
        pop = ine.parse_population(rows(text, ine.POP_TABLE))
        self.assertEqual(pop, {"01001": {"2026": 2981, "2021": 2800}})

    def test_education(self):
        text = ("Municipios de 500 habitantes o más;Sexo;Edad;Nivel de estudios;Periodo;Total\n"
                "01001 A;Total;15 y más años;Total;2024;2.503\n"
                "01001 A;Total;15 y más años;Educación superior;2024;1.075\n"
                "01001 A;Total;15 y más años;Educación primaria e inferior;2024;269\n"
                "01001 A;Total;De 15 a 19 años;Total;2024;232\n"
                "01001 A;Hombres;15 y más años;Total;2024;1.200\n")
        edu = ine.parse_education(rows(text, ine.EDUCATION_TABLE))
        self.assertEqual(edu, {"01001": {"2024": {"pop15": 2503, "higher_ed": 1075}}})
        self.assertEqual(ine.pin_latest(edu, "higher_ed"), ("2024", {"01001": 1075}))

    def test_coverage(self):
        munis = {"a": {"pop": 100, "x": 1}, "b": {"pop": 300, "x": None}}
        cov = ine.coverage(munis, ["x"])
        self.assertEqual(cov["x"], {"municipalities": 1, "population_share": 0.25})


if __name__ == "__main__":
    unittest.main()
