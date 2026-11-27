import csv
import unittest

from pipeline.sources import interior_crime as ic

BOM = "﻿"

# Synthetic fixtures: invented municipalities and figures, never real rows.
MUNI = BOM + """Geografía;Tipología penal;Periodos:;Total
99901 Villa Ejemplo;I. CRIMINALIDAD CONVENCIONAL;enero-diciembre 2024;1.200
99901 Villa Ejemplo;I. CRIMINALIDAD CONVENCIONAL;enero-diciembre 2025;1.150
99901 Villa Ejemplo;I. CRIMINALIDAD CONVENCIONAL;Variación % 2025/2024;-4,2
99901 Villa Ejemplo;5.1.-Agresión sexual con penetración;enero-diciembre 2025;3
99901 Villa Ejemplo;5. Delitos contra la libertad sexual;enero-diciembre 2025;7
99901 Villa Ejemplo;7.1.-Robos con fuerza en domicilios;enero-diciembre 2025;20
99901 Villa Ejemplo;7. Robos con fuerza en domicilios, establecimientos y otras instalaciones;enero-diciembre 2025;30
99901 Villa Ejemplo;12.-Estafas informáticas;enero-diciembre 2025;..
99901 Villa Ejemplo;III. TOTAL INFRACCIONES PENALES;enero-diciembre 2025;1.500
99902 Aldea, la;III. TOTAL INFRACCIONES PENALES;enero-diciembre 2025;0
Isla  de Ejemplo;III. TOTAL INFRACCIONES PENALES;enero-diciembre 2025;9.000
EJEMPLO (COMUNIDAD DE);III. TOTAL INFRACCIONES PENALES;enero-diciembre 2025;99.999
NACIONAL;III. TOTAL INFRACCIONES PENALES;enero-diciembre 2025;999.999
99903 Sin Tipo;99. Otra cosa;enero-diciembre 2025;5
"""

PROV = BOM + """Provincias;Tipología penal;Periodos:;Total
Total Nacional;III. TOTAL INFRACCIONES PENALES;enero-diciembre 2025;2.000.000
Sevilla;III. TOTAL INFRACCIONES PENALES;enero-diciembre 2025;1.000
En el extranjero;III. TOTAL INFRACCIONES PENALES;enero-diciembre 2025;50
"""

CCAA = BOM + """Comunidades autónomas;Tipología penal;Periodos:;Total
TOTAL NACIONAL;I. CRIMINALIDAD CONVENCIONAL;enero-diciembre 2025;2.000.000
ANDALUCÍA;I. CRIMINALIDAD CONVENCIONAL;enero-diciembre 2025;300.000
EN EL EXTRANJERO;I. CRIMINALIDAD CONVENCIONAL;enero-diciembre 2025;50
"""


def rows(text, level):
    rd = csv.reader(text.strip().splitlines(), delimiter=";")
    head = [h.lstrip(BOM).strip() for h in next(rd)]
    assert head[0] == ic.HEADER_FIRST[level]
    return [(r[0].strip(), r[1].strip(), r[2].strip(), r[3]) for r in rd]


class CountTest(unittest.TestCase):
    def test_parse_count(self):
        self.assertEqual(ic.parse_count("1.149"), 1149)
        self.assertEqual(ic.parse_count("0"), 0)
        for blank in ("", ".", "..", " "):
            self.assertIsNone(ic.parse_count(blank))


class TypologyTest(unittest.TestCase):
    def test_nineteen_unique(self):
        self.assertEqual(len(ic.TYPOLOGIES), 19)
        self.assertEqual(len(set(ic.TYPOLOGY_KEYS)), 19)

    def test_keys(self):
        cases = {
            "I. CRIMINALIDAD CONVENCIONAL": "conventional",
            "II. CIBERCRIMINALIDAD (infracciones penales cometidas en/por medio ciber)": "cybercrime",
            "III. TOTAL INFRACCIONES PENALES": "total",
            "1. Homicidios dolosos y asesinatos consumados": "homicides",
            "5. Delitos contra la libertad sexual": "sexual_offences",
            "5.1.-Agresión sexual con penetración": "sexual_aggression_penetration",
            "5.2.-Resto de delitos contra la libertad sexual": "sexual_other",
            "7. Robos con fuerza en domicilios, establecimientos y otras instalaciones": "burglary",
            "7.1.-Robos con fuerza en domicilios": "burglary_dwellings",
            "10. Tráfico de drogas": "drug_trafficking",
            "12.-Estafas informáticas": "cyber_fraud",
            "13.-Otros ciberdelitos": "cyber_other",
        }
        for label, key in cases.items():
            self.assertEqual(ic.typology_key(label), key, label)
        self.assertIsNone(ic.typology_key("99. Otra cosa"))

    def test_header_check(self):
        import pathlib, tempfile
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "x.csv"
            p.write_text(BOM + "Otra;Tipología penal;Periodos:;Total\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                list(ic.read_rows(p, "muni"))


class ParseTest(unittest.TestCase):
    def test_municipalities(self):
        out, islands, unknown = ic.parse_table(rows(MUNI, "muni"), "muni")
        self.assertEqual(sorted(out), ["99901", "99902", "99903"][:2])
        v = out["99901"]
        self.assertEqual(v["name"], "Villa Ejemplo")
        self.assertEqual(v["2024"], {"conventional": 1200})
        self.assertEqual(v["2025"]["conventional"], 1150)
        self.assertEqual(v["2025"]["sexual_offences"], 7)
        self.assertEqual(v["2025"]["sexual_aggression_penetration"], 3)
        self.assertEqual(v["2025"]["burglary"], 30)
        self.assertEqual(v["2025"]["burglary_dwellings"], 20)
        self.assertIsNone(v["2025"]["cyber_fraud"])  # secrecy mark: missing, not zero
        self.assertEqual(out["99902"]["2025"]["total"], 0)  # a real zero stays zero
        self.assertEqual(out["99902"]["name"], "Aldea, la")
        self.assertEqual(list(islands), ["Isla de Ejemplo"])
        self.assertEqual(unknown, {"99. Otra cosa"})

    def test_no_percent_change(self):
        out, _, _ = ic.parse_table(rows(MUNI, "muni"), "muni")
        self.assertEqual(set(out["99901"]) - {"name"}, {"2024", "2025"})

    def test_provinces_and_ccaa(self):
        prov, _, _ = ic.parse_table(rows(PROV, "prov"), "prov")
        self.assertEqual(sorted(prov), ["41", "ES"])
        self.assertEqual(prov["41"]["2025"]["total"], 1000)
        ccaa, _, _ = ic.parse_table(rows(CCAA, "ccaa"), "ccaa")
        self.assertEqual(sorted(ccaa), ["01", "ES"])
        self.assertEqual(ccaa["01"]["2025"]["conventional"], 300000)

    def test_unknown_province_fails(self):
        bad = [("Atlantis", "III. TOTAL INFRACCIONES PENALES", "enero-diciembre 2025", "1")]
        with self.assertRaises(ValueError):
            ic.parse_table(bad, "prov")

    def test_code_tables(self):
        self.assertEqual(len(ic.PROVINCE_CODES), 52)
        self.assertEqual(sorted(ic.PROVINCE_CODES.values()), [f"{i:02d}" for i in range(1, 53)])
        self.assertEqual(sorted(ic.CCAA_CODES.values()), [f"{i:02d}" for i in range(1, 20)])


class RevisionTest(unittest.TestCase):
    def test_revisions(self):
        old = {"99901": {"2024": {"total": 10}}, "99902": {"2024": {"total": 5}}}
        new = {"99901": {"2024": {"total": 11}}, "99902": {"2024": {"total": 5}}, "99903": {"2024": {"total": 1}}}
        self.assertEqual(ic.revisions(old, new, "2024"), {"shared": 2, "changed_total": 1, "only_old": 0, "only_new": 1})


class MetaTest(unittest.TestCase):
    def test_licence_kept(self):
        info = ic.InteriorCrime.info
        self.assertIn("Origen de los datos: Portal Estadístico de Criminalidad", info.license)
        self.assertIn("fines comerciales y no comerciales", info.license)
        self.assertIn(ic.LEGAL_URL, info.license)


if __name__ == "__main__":
    unittest.main()
