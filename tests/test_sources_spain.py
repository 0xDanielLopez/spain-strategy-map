import json
import struct
import unittest
import zlib

from pipeline.sources import gisco_lau, worldcover
from pipeline.sources._spain import CCAA, PROVINCE_TO_CCAA


def build_tiff(levels):
    """Little-endian classic TIFF; levels = [(w, h, tile, rows)], one deflate tile per level, rows = list of bytes."""
    body = bytearray(8)
    ifds = []
    for w, h, tile, rows in levels:
        pad = [bytes(r) + bytes(tile - len(r)) for r in rows] + [bytes(tile)] * (tile - len(rows))
        comp = zlib.compress(b"".join(pad))
        off = len(body)
        body += comp
        ifds.append((w, h, tile, off, len(comp)))
    pos = []
    for _ in ifds:
        pos.append(len(body))
        body += bytes(2 + 12 * 8 + 4)
    for i, (w, h, tile, off, n) in enumerate(ifds):
        ents = [(256, 4, w), (257, 4, h), (259, 3, 8), (322, 4, tile), (323, 4, tile), (324, 4, off), (325, 4, n),
                (339, 3, 1)]
        raw = struct.pack("<H", len(ents))
        for tag, typ, val in ents:
            raw += struct.pack("<HHII", tag, typ, 1, val)
        raw += struct.pack("<I", pos[i + 1] if i + 1 < len(pos) else 0)
        body[pos[i]:pos[i] + len(raw)] = raw
    body[0:8] = b"II*\x00" + struct.pack("<I", pos[0])
    return bytes(body)


class TiffTest(unittest.TestCase):
    def test_last_ifd_decoded(self):
        full = [bytes([10] * 8)] * 8
        small = [bytes([10, 20, 30]), bytes([40, 50, 60]), bytes([80, 90, 95])]
        data = build_tiff([(8, 8, 16, full), (3, 3, 16, small)])
        ifds = worldcover.parse_ifds(data)
        self.assertEqual(len(ifds), 2)
        last = ifds[-1]
        self.assertEqual((last[256][0], last[257][0]), (3, 3))
        w, h, rows = worldcover.decode_ifd(last, lambda o, n: data[o:o + n])
        self.assertEqual((w, h), (3, 3))
        self.assertEqual([[ord(c) for c in r] for r in rows], [[10, 20, 30], [40, 50, 60], [80, 90, 95]])

    def test_not_tiff(self):
        with self.assertRaises(ValueError):
            worldcover.parse_ifds(b"MM\x00*" + bytes(20))

    def test_needed_tiles(self):
        names = [t[0] for t in worldcover.needed_tiles()]
        self.assertIn("N39W003", names)
        self.assertEqual(names, sorted(set(names)))
        self.assertEqual(worldcover.tile_name(27, -18), "N27W018")


def feat(cntr, gid, name, geom_type="Polygon"):
    ring = [[0, 0], [1, 0], [1, 1], [0, 0]]
    coords = [ring] if geom_type == "Polygon" else [[ring], [ring]]
    return {"type": "Feature", "properties": {"CNTR_CODE": cntr, "GISCO_ID": gid, "LAU_NAME": name, "AREA_KM2": 12.345, "POP_2024": 0},
            "geometry": {"type": geom_type, "coordinates": coords}}


class LauTest(unittest.TestCase):
    def test_stream_keeps_only_es(self):
        feats = [feat("FR", "FR_75056", "Paris"), feat("ES", "ES_28079", "Madrid"),
                 feat("ES", "ES_08019", "Barcelona", "MultiPolygon"), feat("PT", "PT_1", "X")]
        text = json.dumps({"type": "FeatureCollection", "name": "x", "features": feats}, indent=1)
        out = gisco_lau.parse_spanish_municipalities(text)
        self.assertEqual([m["code"] for m in out], ["08019", "28079"])
        self.assertEqual((out[1]["province"], out[1]["ccaa"], out[1]["name"]), ("28", "13", "Madrid"))
        self.assertEqual(out[0]["ccaa"], "09")
        self.assertEqual(len(out[0]["rings"]), 2)
        self.assertEqual(out[1]["area_km2"], round(12.345, 2))

    def test_unknown_province(self):
        text = json.dumps({"features": [feat("ES", "ES_99001", "Ghost")]})
        with self.assertRaises(ValueError):
            gisco_lau.parse_spanish_municipalities(text)


class SpainConstantsTest(unittest.TestCase):
    def test_provinces(self):
        self.assertEqual(len(PROVINCE_TO_CCAA), 52)
        codes = {c["code"] for c in CCAA}
        self.assertEqual(len(CCAA), 19)
        self.assertEqual(set(PROVINCE_TO_CCAA.values()), codes)
        self.assertEqual(PROVINCE_TO_CCAA["51"], "18")
        self.assertEqual(PROVINCE_TO_CCAA["52"], "19")
        self.assertEqual([c["code"] for c in CCAA], sorted(codes))


if __name__ == "__main__":
    unittest.main()
