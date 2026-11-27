"""Synthetic CSV snippets only: invented municipalities and numbers, no real rows."""

import tempfile
import unittest
from pathlib import Path

from pipeline.sources import ine_housing as H
from pipeline.sources import ine_migration as M

BOM = "﻿"


def write(text: str) -> Path:
    d = tempfile.mkdtemp()
    p = Path(d) / "t.csv"
    p.write_text(text, encoding="utf-8")
    return p


CENSUS = (
    BOM + "Total Nacional\tMunicipios\tTipo de vivienda (principal o no)\tTotal\n"
    "Total Nacional\t\tTotal\t3.000\n"
    "Total Nacional\t99001 Villa Ejemplo\tTotal\t1.290\n"
    "Total Nacional\t99001 Villa Ejemplo\tVivienda principal\t1.121\n"
    "Total Nacional\t99001 Villa Ejemplo\tVivienda no principal\t169\n"
    "Total Nacional\t99002  Aldea Muestra\tTotal\t.\n"
    "Total Nacional\t99002  Aldea Muestra\tOtra cosa\t5\n"
)

TOURIST = (
    BOM + ";".join(H.TOURIST_HEADER) + "\n"
    "Total Nacional;;;;Viviendas turísticas;2026M05;341.001\n"
    "Total Nacional;;;;Viviendas turísticas;2025M11;329.764\n"
    "Total Nacional;99 Ejemplo;99 Ejemplo;;Viviendas turísticas;2026M05;7\n"
    "Total Nacional;99 Ejemplo;99 Ejemplo;99001 Villa Ejemplo;Viviendas turísticas;2026M05;12\n"
    "Total Nacional;99 Ejemplo;99 Ejemplo;99001 Villa Ejemplo;Viviendas turísticas;2025M11;10\n"
    "Total Nacional;99 Ejemplo;99 Ejemplo;99001 Villa Ejemplo;Plazas;2026M05;60\n"
    "Total Nacional;99 Ejemplo;99 Ejemplo;99001 Villa Ejemplo;Plazas por vivienda turística;2026M05;5,0\n"
    "Total Nacional;99 Ejemplo;99 Ejemplo;99002 Aldea Muestra;Viviendas turísticas;2026M05;.\n"
)


class HousingTests(unittest.TestCase):
    def test_census(self):
        munis, nat = H.parse_census(H.read_rows(write(CENSUS), "\t", H.CENSUS_HEADER, "t"))
        self.assertEqual(nat, {"dwellings_total": 3000})
        self.assertEqual(munis["99001"], {"dwellings_total": 1290, "dwellings_primary": 1121, "dwellings_non_primary": 169})
        self.assertEqual(munis["99002"], {"dwellings_total": None})  # secret stays None, never 0
        self.assertEqual(len(munis), 2)

    def test_tourist(self):
        munis, nat = H.parse_tourist(H.read_rows(write(TOURIST), ";", H.TOURIST_HEADER, "t"))
        self.assertEqual(nat["tourist_homes"], {"2026M05": 341001, "2025M11": 329764})
        self.assertEqual(munis["99001"]["tourist_homes"], {"2026M05": 12, "2025M11": 10})
        self.assertEqual(munis["99001"]["tourist_beds"], {"2026M05": 60})
        self.assertIsNone(munis["99002"]["tourist_homes"]["2026M05"])
        self.assertEqual(set(munis), {"99001", "99002"})  # province row is not a municipality
        self.assertEqual(H.latest_period(munis, "tourist_homes"), "2026M05")

    def test_bad_header(self):
        with self.assertRaises(ValueError):
            list(H.read_rows(write("a;b\n"), ";", H.TOURIST_HEADER, "t"))


def census_csv(kind: str, col: str, rows: list[str]) -> str:
    return BOM + ";".join(M.HEADERS[kind]) + "\n" + "\n".join(rows) + "\n"


class MigrationTests(unittest.TestCase):
    def test_nationality(self):
        txt = census_csv(M.NATIONALITY_TABLE, "", [
            "Total Nacional;;;;Total;Extranjera;2026;7.000",
            "Total Nacional;;;;Total;Total;2026;50.000",
            "Total Nacional;99 Ejemplo;99001 Villa Ejemplo;;Total;Extranjera;2026;300",
            "Total Nacional;99 Ejemplo;99001 Villa Ejemplo;;Total;Total;2026;1.500",
            "Total Nacional;99 Ejemplo;99001 Villa Ejemplo;9900101001;Total;Extranjera;2026;40",  # section row
            "Total Nacional;99 Ejemplo;99001 Villa Ejemplo;;Hombres;Extranjera;2026;150",  # other sex
            "Total Nacional;99 Ejemplo;99001 Villa Ejemplo;;Total;Española;2026;1.200",  # not kept
            "Total Nacional;99 Ejemplo;99002 Aldea Muestra;;Total;Extranjera;2021;.",
        ])
        munis, nat = M.parse_census(M.read_rows(write(txt), M.NATIONALITY_TABLE), M.NATIONALITY_TABLE, M.NATIONALITY_KEYS)
        self.assertEqual(nat["foreign"]["2026"], 7000)
        self.assertEqual(munis["99001"], {"foreign": {"2026": 300}, "total": {"2026": 1500}})
        self.assertIsNone(munis["99002"]["foreign"]["2021"])

    def test_birth_and_immigration_and_merge(self):
        b = census_csv(M.BIRTH_TABLE, "", [
            "Total Nacional;99 Ejemplo;99001 Villa Ejemplo;;Total;Extranjero;2026;420",
            "Total Nacional;99 Ejemplo;99001 Villa Ejemplo;;Total;España;2026;1.080",
        ])
        birth, _ = M.parse_census(M.read_rows(write(b), M.BIRTH_TABLE), M.BIRTH_TABLE, M.BIRTH_KEYS)
        self.assertEqual(birth, {"99001": {"born_abroad": {"2026": 420}}})
        i = BOM + ";".join(M.HEADERS[M.IMMIGRATION_TABLE]) + "\n" + "\n".join([
            "Total Nacional;;;Ambos sexos;2024;1.288.562",
            "Total Nacional;99 Ejemplo;99001 Villa Ejemplo;Ambos sexos;2024;11",
            "Total Nacional;99 Ejemplo;99001 Villa Ejemplo;Hombres;2024;6",
            "Total Nacional;99 Ejemplo;99003 Pueblo Nuevo;Ambos sexos;2024;0",
        ]) + "\n"
        imm, nat = M.parse_immigrations(M.read_rows(write(i), M.IMMIGRATION_TABLE))
        self.assertEqual(nat, {"2024": 1288562})
        self.assertEqual(imm, {"99001": {"2024": 11}, "99003": {"2024": 0}})
        merged = M.merge({"99001": {"foreign": {"2026": 300}}}, birth, imm)
        self.assertEqual(merged["99001"]["immigrations_abroad"], {"2024": 11})
        self.assertEqual(merged["99003"]["foreign"], {})
        cov = M.coverage(merged)
        self.assertEqual(cov["foreign"]["2026"], {"municipalities": 1, "secret": 0})
        self.assertEqual(M.national_sums(merged)["born_abroad"], {"2026": 420})

    def test_bad_header(self):
        with self.assertRaises(ValueError):
            list(M.read_rows(write("x;y\n"), M.NATIONALITY_TABLE))


if __name__ == "__main__":
    unittest.main()
