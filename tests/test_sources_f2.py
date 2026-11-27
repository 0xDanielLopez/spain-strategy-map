import io
import unittest
import zipfile

from pipeline.sources import auf, ine_gdp, ine_jobs

BOM = "﻿"


def tiny_xlsx(path):
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rns = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    strings = ["CODIGO AUF", "LITERAL AUF", "CODIGO MUNICIPIO", "LITERAL MUNICIPIO", "ES001F", "AUF de Madrid",
               "Madrid", "Getafe", "Otra hoja", "ES002F", "AUF de Barcelona", "Barcelona"]
    sst = "".join(f"<si><t>{s}</t></si>" for s in strings)

    def c(ref, v, s=False):
        return f'<c r="{ref}" t="s"><v>{v}</v></c>' if s else f'<c r="{ref}"><v>{v}</v></c>'

    rows = [
        [c("A1", 0, 1), c("B1", 1, 1), c("C1", 2, 1), c("D1", 3, 1)],
        [c("A2", 4, 1), c("B2", 5, 1), c("C2", 28079), c("D2", 6, 1)],
        [c("A3", 4, 1), c("B3", 5, 1), c("C3", 28065), c("D3", 7, 1)],
        [c("A4", 9, 1), c("B4", 10, 1), c("C4", "1")  , c("D4", 11, 1)],
        [c("A5", 9, 1), c("B5", 10, 1), c("C5", 28079), c("D5", 6, 1)],  # duplicate municipality
    ]
    sheet = f"<worksheet {ns}><sheetData>" + "".join(f'<row r="{i}">{"".join(r)}</row>' for i, r in enumerate(rows, 1)) + "</sheetData></worksheet>"
    wb = f'<workbook {ns} {rns}><sheets><sheet name="Portada" sheetId="1" r:id="rId1"/><sheet name="Areas_Urbanas_Funcionales" sheetId="2" r:id="rId2"/></sheets></workbook>'
    rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Target="worksheets/sheet2.xml"/></Relationships>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/sharedStrings.xml", f"<sst {ns}>{sst}</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f"<worksheet {ns}><sheetData/></worksheet>")
        z.writestr("xl/worksheets/sheet2.xml", sheet)


class AufTest(unittest.TestCase):
    def test_xlsx_parse(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "a.xlsx"
            tiny_xlsx(p)
            rows = auf.read_sheet(p)
        self.assertEqual(rows[0], auf.COLUMNS)
        rows[0] = ["CÓDIGO AUF", "LITERAL AUF", "CÓDIGO MUNICIPIO", "LITERAL MUNICIPIO"]  # real header has accents
        cities, dups = auf.parse_auf(rows)
        self.assertEqual([c["id"] for c in cities], ["ES001F", "ES002F"])
        self.assertEqual(cities[0]["members"], ["28065", "28079"])
        self.assertEqual(cities[1]["members"], ["00001"])  # zero-filled to 5 digits
        self.assertEqual(dups, [{"code": "28079", "first": "ES001F", "other": "ES002F"}])

    def test_col_index(self):
        self.assertEqual([auf.col_index(x) for x in ("A1", "Z9", "AA3")], [0, 25, 26])


class JobsTest(unittest.TestCase):
    def test_section_key(self):
        self.assertEqual(section_key("A Agricultura, ganadería"), "A")
        self.assertEqual(section_key("U Actividades de organizaciones"), "U")
        for bad in ("Total CNAE", "No consta", "Industria", ""):
            self.assertIsNone(section_key(bad))

    def test_municipal_sums(self):
        big = [
            ["01001 Alegría", "Total", "Total CNAE", "2024", "30"],
            ["01001 Alegría", "Total", "Total CNAE", "2023", "99"],
            ["01001 Alegría", "Total", "A Agricultura, ganadería", "2024", "18"],
            ["01001 Alegría", "Total", "B Industrias extractivas", "2024", "10"],
            ["01001 Alegría", "Total", "No consta", "2024", "2"],
            ["01002 Otro", "Total", "Total CNAE", "2024", "10"],
            ["01002 Otro", "Total", "A Agricultura, ganadería", "2024", "."],
            ["Total Nacional", "Total", "Total CNAE", "2024", "5"],
        ]
        out, names = ine_jobs.parse_municipal(big, ine_jobs.BIG_TABLE)
        self.assertEqual(out["01001"]["total"], 30)
        self.assertEqual(out["01001"]["sections"], {"A": 18, "B": 10})
        self.assertIsNone(out["01001"]["sectors4"])
        self.assertEqual(names["B"], "Industrias extractivas")
        self.assertEqual(ine_jobs.mismatches(out), ["01002"])

    def test_small_sectors(self):
        small = [["01006 Armiñón", "Total", "Total CNAE", "2024", "123"],
                 ["01006 Armiñón", "Total", "Agricultura, ganadería y pesca", "2024", "3"],
                 ["01006 Armiñón", "Total", "Servicios", "2024", "120"]]
        out, _ = ine_jobs.parse_municipal(small, ine_jobs.SMALL_TABLE)
        self.assertEqual(out["01006"]["sectors4"], {"agricultura": 3, "servicios": 120})
        self.assertIsNone(out["01006"]["sections"])
        self.assertEqual(ine_jobs.mismatches(out), [])

    def test_regions(self):
        rows = [
            ["Total Nacional", "", "", "Total CNAE", "Total", "Total", "2024", "20.373.148"],
            ["Total Nacional", "", "", "C Industria manufacturera", "Total", "Total", "2024", "2.124.439"],
            ["Total Nacional", "", "", "C Industria manufacturera", "Total", "Hombres", "2024", "1"],
            ["Total Nacional", "13 Madrid, Comunidad de", "", "Total CNAE", "Total", "Total", "2024", "3.000.000"],
            ["Total Nacional", "13 Madrid, Comunidad de", "28 Madrid", "Total CNAE", "Total", "Total", "2024", "3.000.000"],
            ["Total Nacional", "01 Andalucía", "01 Araba/Álava", "Total CNAE", "Total", "Total", "2024", "7"],
        ]
        out, names = ine_jobs.parse_regions(rows)
        self.assertEqual(out["national"], {"total": 20373148, "sections": {"C": 2124439}})
        self.assertEqual(out["ccaa"]["13"]["total"], 3000000)
        self.assertEqual(out["provinces"]["28"]["total"], 3000000)
        self.assertIn("01", out["provinces"])  # province 01 and CCAA 01 are different keys
        self.assertEqual(names, {"C": "Industria manufacturera"})

    def test_header(self):
        with self.assertRaises(ValueError):
            ine_jobs.check_header(ine_jobs.BIG_TABLE, ["a", "b"])
        ine_jobs.check_header(ine_jobs.BIG_TABLE, [BOM + ine_jobs.HEADERS[ine_jobs.BIG_TABLE][0]] + ine_jobs.HEADERS[ine_jobs.BIG_TABLE][1:])


section_key = ine_jobs.section_key


def gdp_rows(year_values):
    rows = [["Total Nacional", "Valor", y, v] for y, v in year_values["nat"].items()]
    return rows


class GdpTest(unittest.TestCase):
    ROWS = [
        ["Total Nacional", "Valor", "2024", "1.000"],
        ["Total Nacional", "Estructura Porcentual", "2024", "100,0"],
        ["01 ANDALUCÍA", "Valor", "2024", "300"],
        ["01 Araba/Álava", "Valor", "2024", "30"],
        ["13 MADRID, COMUNIDAD DE", "Valor", "2024", "295.939"],
        ["05 CANARIAS", "Valor", "2024", "50"],
        ["05 Ávila", "Valor", "2024", "5"],
        ["EXTRA-REGIO", "Valor", "2024", "1"],
        ["13 MADRID, COMUNIDAD DE", "Valor", "2025", '""'],
    ]

    def test_codes_collide_but_are_kept_apart(self):
        d = ine_gdp.parse_gdp(self.ROWS)["2024"]
        self.assertEqual(d["national"], 1000)
        self.assertEqual(d["ccaa"]["01"], 300)
        self.assertEqual(d["provinces"]["01"], 30)
        self.assertEqual(d["ccaa"]["05"], 50)
        self.assertEqual(d["provinces"]["05"], 5)
        self.assertEqual(d["provinces"]["28"], 295939)  # single-province CCAA: Madrid
        self.assertNotIn("EXTRA-REGIO", d["ccaa"])

    def test_units_and_pinning(self):
        self.assertEqual(ine_gdp.to_euros(295939), 295_939_000)
        self.assertIsNone(ine_gdp.to_euros(None))
        by = ine_gdp.parse_gdp(self.ROWS)
        self.assertFalse(ine_gdp.complete(by["2024"]))  # tiny input has far from 52 provinces
        with self.assertRaises(ValueError):
            ine_gdp.pin_year(by)

    def test_split_code(self):
        self.assertEqual(ine_gdp.split_code("35 Palmas, Las"), ("35", "Palmas, Las"))
        self.assertEqual(ine_gdp.split_code("Total Nacional"), (None, "Total Nacional"))


if __name__ == "__main__":
    unittest.main()
