"""Census-section library on synthetic data: UTM round trip, shapefile/dbf reading, table parsing, caching."""

import io
import json
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from pipeline.core import shapefile
from pipeline.core.utm import lonlat_to_utm, utm_to_lonlat
from pipeline.sources import ine_sections as S


def make_dbf(rows, fields):
    head_len = 32 + 32 * len(fields) + 1
    rec_len = 1 + sum(n for _, n in fields)
    out = bytearray(struct.pack("<BBBBIHH20x", 3, 26, 1, 1, len(rows), head_len, rec_len))
    for name, n in fields:
        out += name.encode().ljust(11, b"\0") + b"C" + b"\0" * 4 + bytes([n]) + b"\0" * 15
    out += b"\r"
    for r in rows:
        out += b" " + b"".join(str(v).encode("utf-8").ljust(n) for v, (_, n) in zip(r, fields))
    return bytes(out)


def make_shp(polys):
    body = b""
    for i, rings in enumerate(polys, 1):
        pts = [p for ring in rings for p in ring]
        starts, k = [], 0
        for ring in rings:
            starts.append(k)
            k += len(ring)
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        c = struct.pack("<i4di", 5, min(xs), min(ys), max(xs), max(ys), len(rings)) + struct.pack("<i", len(pts))
        c += struct.pack(f"<{len(starts)}i", *starts) + b"".join(struct.pack("<2d", *p) for p in pts)
        body += struct.pack(">ii", i, len(c) // 2) + c
    return struct.pack(">i20xi", 9994, (100 + len(body)) // 2) + b"\0" * 72 + body


SQUARE = [(440000.0, 4474000.0), (440100.0, 4474000.0), (440100.0, 4474100.0), (440000.0, 4474100.0), (440000.0, 4474000.0)]
HOLE = [(440040.0, 4474040.0), (440040.0, 4474060.0), (440060.0, 4474060.0), (440060.0, 4474040.0), (440040.0, 4474040.0)]


class UtmTests(unittest.TestCase):
    def test_known_point(self):
        lon, lat = utm_to_lonlat(440290.0, 4474257.0)
        self.assertAlmostEqual(lon, -3.7038, places=3)
        self.assertAlmostEqual(lat, 40.4168, places=3)

    def test_round_trip_under_a_millimetre(self):
        for lon, lat in [(-3.7, 40.4), (-6.1, 37.2), (0.5, 41.6), (-8.5, 43.3)]:
            e, n = lonlat_to_utm(lon, lat)
            lon2, lat2 = utm_to_lonlat(e, n)
            self.assertLess(abs(lon2 - lon) + abs(lat2 - lat), 1e-9)

    def test_central_meridian(self):
        e, _ = lonlat_to_utm(-3.0, 40.0)
        self.assertAlmostEqual(e, 500000.0, places=4)


class ShapefileTests(unittest.TestCase):
    def test_polygon_with_hole_and_skip(self):
        data = make_shp([[SQUARE, HOLE], [SQUARE]])
        got = list(shapefile.iter_polygons(io.BytesIO(data)))
        self.assertEqual([i for i, _ in got], [0, 1])
        self.assertEqual(len(got[0][1]), 2)
        self.assertEqual(got[0][1][1][2], (440060.0, 4474060.0))
        self.assertEqual([i for i, _ in shapefile.iter_polygons(io.BytesIO(data), wanted={1})], [1])

    def test_dbf(self):
        raw = make_dbf([("0000000001", "28079"), ("0000000002", "28080")], [("CUSEC", 10), ("CUMUN", 5)])
        self.assertEqual(shapefile.read_dbf(io.BytesIO(raw))[1], {"CUSEC": "0000000002", "CUMUN": "28080"})


HDR_ADRH = "﻿Municipios;Distritos;Secciones;Indicadores de renta media;Periodo;Total\n"
HDR_DEMO = "﻿Municipios;Distritos;Secciones;Indicadores demográficos;Periodo;Total\n"
HDR_DIST = "﻿Municipios;Distritos;Secciones;Sexo;Distribución de la renta por unidad de consumo;Periodo;Total\n"
HDR_NAT = "﻿Total Nacional;Provincias;Municipios;Secciones;Sexo;Nacionalidad;Periodo;Total\n"
HDR_BIRTH = "﻿Total Nacional;Provincias;Municipios;Secciones;Sexo;Lugar de nacimiento;Periodo;Total\n"


def sec(code, muni="99001 Testville"):
    return f"{muni};{code[:7]} Testville distrito;{code} Testville sección"


class StatsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        t = self.tmp
        # section 0000000001 has data, 9900199002 only existed in the older year (no polygon in the map)
        (t / "inc.csv").write_text(
            HDR_ADRH
            + f"99001 Testville;;;Renta neta media por persona;2024;20.000\n"
            + f"{sec('9900101001')};Renta neta media por persona;2024;31.340\n"
            + f"{sec('9900101001')};Renta neta media por persona;2023;27.000\n"
            + f"{sec('9900101002')};Renta neta media por persona;2024;.\n"
            + f"{sec('9900101009')};Renta neta media por persona;2024;11.000\n"
            + "99001 Testville;9900101 Testville distrito;;Renta neta media por persona;2024;25.500\n"
            + "99002 Other;;;Renta neta media por persona;2024;1\n",
            encoding="utf-8",
        )
        (t / "dist.csv").write_text(
            HDR_DIST
            + f"{sec('9900101001')};Total;Población con ingresos por unidad de consumo por debajo 60% de la mediana;2024;18,7\n"
            + f"{sec('9900101001')};Hombres;Población con ingresos por unidad de consumo por debajo 60% de la mediana;2024;99,9\n"
            + f"{sec('9900101001')};Total;Población con ingresos por unidad de consumo por debajo 40% de la mediana;2024;5,0\n",
            encoding="utf-8",
        )
        (t / "demo.csv").write_text(
            HDR_DEMO + f"{sec('9900101001')};Edad media de la población;2024;47,9\n" + f"{sec('9900101001')};Población;2024;1.149\n",
            encoding="utf-8",
        )
        (t / "nat.csv").write_text(
            HDR_NAT
            + "Total Nacional;;;;Total;Total;2026;5\n"
            + "Total Nacional;99 Test;99001 Testville;9900101001 Testville sección;Total;Total;2026;1.000\n"
            + "Total Nacional;99 Test;99001 Testville;9900101001 Testville sección;Total;Extranjera;2026;300\n"
            + "Total Nacional;99 Test;99001 Testville;9900101001 Testville sección;Total;Española;2026;700\n"
            + "Total Nacional;99 Test;99001 Testville;9900101001 Testville sección;Hombres;Total;2026;1\n"
            + "Total Nacional;99 Test;99001 Testville;9900101002 Testville sección;Total;Total;2026;500\n",
            encoding="utf-8",
        )
        (t / "birth.csv").write_text(
            HDR_BIRTH + "Total Nacional;99 Test;99001 Testville;9900101001 Testville sección;Total;Extranjero;2026;410\n", encoding="utf-8"
        )
        files = {S.INCOME: t / "inc.csv", S.DISTRIBUTION: t / "dist.csv", S.DEMOGRAPHICS: t / "demo.csv", S.NATIONALITY: t / "nat.csv", S.BIRTH: t / "birth.csv"}
        dbf = make_dbf(
            [("9900101001", "9900101", "99001", "Testville"), ("9900101002", "9900101", "99001", "Testville"), ("9800101001", "9800101", "98001", "Elsewhere")],
            [("CUSEC", 10), ("CUDIS", 7), ("CUMUN", 5), ("NMUN", 20)],
        )
        shp = make_shp([[SQUARE, HOLE], [SQUARE], [SQUARE]])
        zp = t / "seccionado_2026.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("x/SECC_CE_20260101.dbf", dbf)
            zf.writestr("x/SECC_CE_20260101.shp", shp)
            zf.writestr("x/SECC_CE_20260101.CPG", "UTF-8")
        self.patches = [
            mock.patch.object(S, "TABLE_FILES", files),
            mock.patch.object(S, "CACHE", t / "cache"),
            mock.patch.object(S, "_zip_path", lambda year: zp),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_sections(self):
        secs = S.load_sections({"99001"})
        self.assertEqual([s["cusec"] for s in secs], ["9900101001", "9900101002"])
        self.assertEqual(len(secs[0]["rings"]), 2)
        lon, lat = secs[0]["rings"][0][0]
        self.assertTrue(-3.8 < lon < -3.6 and 40.3 < lat < 40.5)
        self.assertEqual(secs[0]["nmun"], "Testville")
        self.assertEqual(S.load_sections({"99001"})[0]["rings"], secs[0]["rings"])  # from cache

    def test_stats_and_match(self):
        st = S.load_section_stats({"99001"})
        a, b = st["sections"]["9900101001"], st["sections"]["9900101002"]
        self.assertEqual(a["income"], 31340)  # latest period, "31.340" is 31340
        self.assertEqual(a["poverty60_pct"], 18.7)  # Sexo Total, 60% row only
        self.assertEqual((a["age"], a["adrh_pop"]), (47.9, 1149))
        self.assertEqual((a["pop"], a["foreign"], a["born_abroad"]), (1000, 300, 410))
        self.assertIsNone(b["income"])  # secrecy mark: stays None, never 0
        self.assertEqual(b["pop"], 500)
        self.assertEqual(st["districts"]["9900101"]["income"], 25500)
        self.assertEqual(st["vintage"][S.INCOME], "2024")
        m = st["match"][S.INCOME]
        self.assertEqual((m["sections_in_map"], m["with_value"], m["rows_without_polygon"]), (2, 1, 1))
        self.assertAlmostEqual(m["pop_share_matched"], 1000 / 1500, places=3)
        self.assertEqual(st["match"][S.NATIONALITY]["pop_share_matched"], 1.0)
        json.dumps(st)

    def test_cache_skips_the_tables(self):
        S.load_section_stats({"99001"})
        with mock.patch.object(S, "_parse_table", side_effect=AssertionError("cache not used")):
            self.assertEqual(S.load_section_stats({"99001"})["sections"]["9900101001"]["pop"], 1000)

    def test_bad_header_fails_loudly(self):
        (self.tmp / "inc.csv").write_text("a;b;c\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            S.load_section_stats({"99001"})


if __name__ == "__main__":
    unittest.main()
