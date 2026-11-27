"""Tests for the BOJA and Junta minor-contracts sources. SYNTHETIC fixtures only (invented bodies, ids and amounts)."""

import unittest
from datetime import date

from pipeline.sources import boja, junta_menores as jm

HEADER = ("ID_EXPEDIENTE|ORGANO_CONTRATACION|NUM_EXPEDIENTE|TITULO|DESCRIPCION|TIPO_CONTRATO|PROCEDIMIENTO_ADJUDICACION|"
          "DURACION_CONTRATO|DURACION_MEDIDA|LUGAR_EJECUCION_CODIGO|LUGAR_EJECUCION_DENOMINACION|VALOR_ESTIMADO|"
          "IMPORTE_ADJUDICACION_SIN_IVA|IMPORTE_ADJUDICACION_CON_IVA|FINANCIACION_EUROPEA|FINANCIADO_POR|TASA_COFINANCIACION|"
          "NUM_LICITADORES_PRESENTADOS|NIF_ADJUDICATARIO|ADJUDICATARIO_DENOMINACION|FECHA_ADJUDICACION|FECHA_FORMALIZACION|ESTADO")
SECRET = "Empresa Ejemplo SL"


def row(organ="Organo Ficticio A", place="ES618", amount="1000,50", bidders="1"):
    f = ["1".ljust(8), organ.ljust(40), "EXP-0", "Objeto inventado", "Descripcion inventada", "Servicios", "MENOR", "1", "Meses",
         place, "Lugar", "1000", amount, "1210", "No", "", "", bidders, "X0000000X", SECRET, "01/01/2025", "", "Resuelto"]
    return "|".join(f)


class SectionTest(unittest.TestCase):
    def test_section_code(self):
        self.assertEqual(boja.section_code("5. Anuncios"), "5")
        self.assertEqual(boja.section_code("2. AUTORIDADES Y PERSONAL"), "2")
        self.assertEqual(boja.section_code("1. Disposiciones Generales5. ANUNCIOS"), boja.MIXED)
        self.assertEqual(boja.section_code("Suplemento"), boja.UNKNOWN)
        self.assertEqual(boja.section_code(None), boja.UNKNOWN)

    def test_month_ranges(self):
        r = list(boja.month_ranges(date(2026, 2, 10)))
        self.assertEqual(len(r), 12 + 12 + 2)
        self.assertEqual(r[-1], (2026, 2, "2026-02-01", "2026-02-28"))
        self.assertEqual(r[13][3], "2025-02-28")


class BojaFetchTest(unittest.TestCase):
    def results(self, ids, sec="5. Anuncios", org="Consejeria Ficticia"):
        return [{"id": i, "titleSec": sec, "organisation": org} for i in ids]

    def test_aggregate_counts_only(self):
        c = boja.aggregate(self.results(["a", "b"]) + self.results(["c"], "3. Otras disposiciones", "Ayuntamientos"))
        self.assertEqual(c["total"], 3)
        self.assertEqual(c["by_section"], {"5": 2, "3": 1})
        self.assertEqual(c["by_org"]["Ayuntamientos"], {"3": 1})
        self.assertNotIn("'a'", str(c))  # ids are not stored

    def test_fetch_month_pages_and_dedupes(self):
        pages = {0: self.results(["a", "b"]), 1: self.results(["b", "c"]), 2: self.results(["d"])}
        calls = []

        def get(url):
            p = int(url.split("page=")[1].split("&")[0])
            calls.append(p)
            return {"hits": len(pages[p]), "total_hits": 4, "results": pages[p]}

        old = boja.PAGE_SIZE
        boja.PAGE_SIZE = 2
        try:
            c = boja.fetch_month("2025-01-01", "2025-01-31", get)
        finally:
            boja.PAGE_SIZE = old
        self.assertEqual(c["total"], 4)
        self.assertEqual(calls, [0, 1, 2])

    def test_fetch_month_mismatch_and_cap_fail(self):
        with self.assertRaises(ValueError):
            boja.fetch_month("a", "b", lambda u: {"total_hits": 5, "results": self.results(["a"])} if "page=0" in u else {"total_hits": 5, "results": []})
        with self.assertRaises(ValueError):
            boja.fetch_month("a", "b", lambda u: {"total_hits": 10000, "results": []})

    def test_url_requests_limited_fields(self):
        u = boja.page_url("2025-01-01", "2025-01-31", 1)
        for banned in ("body", "summary", "bodyNoHtml", "subtitle"):
            self.assertNotIn(banned, u)
        self.assertIn("campos=organisation", u)

    def test_merge(self):
        a = boja.aggregate(self.results(["a"]))
        b = boja.aggregate(self.results(["b"], "2. Autoridades"))
        boja.merge(a, b)
        self.assertEqual(a["total"], 2)
        self.assertEqual(a["by_org"]["Consejeria Ficticia"], {"5": 1, "2": 1})


class JuntaTest(unittest.TestCase):
    def test_parse_amount(self):
        self.assertEqual(jm.parse_amount("12145,62"), 12145.62)
        self.assertEqual(jm.parse_amount("1.234,50"), 1234.5)
        self.assertEqual(jm.parse_amount("9190"), 9190.0)
        self.assertIsNone(jm.parse_amount("   "))
        self.assertIsNone(jm.parse_amount("n/d"))

    def test_province_key(self):
        self.assertEqual(jm.province_key("ES618 "), "41")
        self.assertEqual(jm.province_key("ES61"), jm.NO_PROVINCE)
        self.assertEqual(jm.province_key("ES300"), jm.OTHER)

    def test_aggregate(self):
        lines = [HEADER,
                 row(amount="14500", bidders="1"),
                 row(amount="30000,00", bidders="3"),
                 row("Organo Ficticio B", "ES617", "50000", ""),
                 row(place="ES61", amount="", bidders="0"),
                 "linea|rota",
                 ""]
        out = jm.aggregate_lines(lines)
        self.assertEqual(out["rows"], 4)
        self.assertEqual(out["rows_malformed"], 1)
        s = out["provinces"]["41"]
        self.assertEqual((s["n"], s["n_amount"], s["amount_sin_iva"]), (2, 2, 44500.0))
        self.assertEqual((s["n_lt_15000"], s["n_lt_40000"], s["n_band_15000"], s["n_band_40000"]), (1, 2, 1, 0))
        self.assertEqual((s["n_bidders_known"], s["n_single_bidder"]), (2, 1))
        m = out["provinces"]["29"]
        self.assertEqual((m["n"], m["n_lt_40000"], m["n_bidders_known"]), (1, 0, 0))
        sp = out["provinces"][jm.NO_PROVINCE]
        self.assertEqual((sp["n"], sp["n_amount"], sp["amount_sin_iva"]), (1, 0, 0.0))  # n_amount 0 says "unknown"
        a = out["organs"]["Organo Ficticio A"]
        self.assertEqual((a["n"], a["n_amount"]), (3, 2))

    def test_no_winner_data_in_output(self):
        out = jm.aggregate_lines([HEADER, row(), row()])
        text = repr(out)
        self.assertNotIn(SECRET, text)
        self.assertNotIn("X0000000X", text)
        self.assertNotIn("Objeto inventado", text)

    def test_bad_header(self):
        with self.assertRaises(ValueError):
            jm.aggregate_lines(["A|B|C"])
        with self.assertRaises(ValueError):
            jm.aggregate_lines([HEADER.replace("IMPORTE_ADJUDICACION_SIN_IVA", "IMPORTE_X")])

    def test_winner_columns_never_used(self):
        self.assertFalse(set(jm.FORBIDDEN_COLS) & set(jm.USED_COLS))

    def test_urls_use_public_host(self):
        for y in jm.FILES:
            u = jm.JuntaMenores().url(y)
            self.assertTrue(u.startswith("https://www.juntadeandalucia.es/"))
            self.assertNotIn("paas", u)


if __name__ == "__main__":
    unittest.main()
