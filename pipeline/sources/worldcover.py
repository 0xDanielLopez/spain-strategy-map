"""ESA WorldCover v200 (2021), read from the smallest overview of each 3x3 degree Cloud Optimized GeoTIFF."""

import math
import urllib.error
import struct
import zlib

from ..core.source import Source, SourceInfo

URL = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
HEAD_BYTES = 131072
# (lon_min, lon_max, lat_min, lat_max): mainland + Balearics, Ceuta + Melilla, Canary Islands.
BOXES = [(-9.4, 4.4, 35.9, 43.8), (-5.4, -2.9, 35.2, 35.95), (-18.2, -13.4, 27.6, 29.5)]

LEGEND = {0: ".", 10: "t", 20: "s", 30: "g", 40: "c", 50: "b", 60: "r", 70: "i", 80: "w", 90: "h", 95: "m", 100: "l"}
CLASSES = {
    "10": "Tree cover", "20": "Shrubland", "30": "Grassland", "40": "Cropland", "50": "Built-up",
    "60": "Bare / sparse vegetation", "70": "Snow and ice", "80": "Permanent water bodies",
    "90": "Herbaceous wetland", "95": "Mangroves", "100": "Moss and lichen",
}


def tile_name(lat0: int, lon0: int) -> str:
    return f"{'N' if lat0 >= 0 else 'S'}{abs(lat0):02d}{'E' if lon0 >= 0 else 'W'}{abs(lon0):03d}"


def needed_tiles() -> list[tuple[str, int, int]]:
    found = {}
    for lon_a, lon_b, lat_a, lat_b in BOXES:
        for lat0 in range(math.floor(lat_a / 3) * 3, math.floor(lat_b / 3) * 3 + 1, 3):
            for lon0 in range(math.floor(lon_a / 3) * 3, math.floor(lon_b / 3) * 3 + 1, 3):
                found[tile_name(lat0, lon0)] = (tile_name(lat0, lon0), lat0, lon0)
    return [found[k] for k in sorted(found) if k not in NO_TILE]


# 3-degree cells that ESA did not publish (HTTP 404, open ocean). Checked 2026-11-27.
NO_TILE = {"N33W012"}


_TYPE_FMT = {3: ("H", 2), 4: ("I", 4), 16: ("Q", 8)}
_WANTED = (256, 257, 259, 317, 322, 323, 324, 325)


def parse_ifds(b: bytes) -> list[dict]:
    """Walk the IFD chain of a little-endian classic TIFF held in `b`. Returns one {tag: values} dict per IFD.
    Raises IndexError / struct.error if an IFD or one of its arrays lies beyond the end of `b`."""
    if b[:4] != b"II*\x00":
        raise ValueError("not a little-endian classic TIFF")
    off = struct.unpack_from("<I", b, 4)[0]
    out = []
    while off:
        (cnt,) = struct.unpack_from("<H", b, off)
        d = {}
        for i in range(cnt):
            e = off + 2 + 12 * i
            tag, typ, c = struct.unpack_from("<HHI", b, e)
            if tag not in _WANTED or typ not in _TYPE_FMT:
                continue
            f, sz = _TYPE_FMT[typ]
            if c * sz <= 4:
                d[tag] = struct.unpack_from("<" + f * c, b, e + 8)
            else:
                vo = struct.unpack_from("<I", b, e + 8)[0]
                if vo + c * sz > len(b):
                    raise IndexError("IFD array beyond the fetched bytes")
                d[tag] = struct.unpack_from("<" + f * c, b, vo)
        out.append(d)
        (off,) = struct.unpack_from("<I", b, off + 2 + 12 * cnt)
    return out


def decode_ifd(ifd: dict, read) -> tuple[int, int, list[str]]:
    """Decode a tiled, deflate-compressed, 1 byte per pixel IFD. `read(offset, length)` returns the tile bytes.
    Returns (w, h, rows); each row is a string whose characters are the raw class codes (latin-1)."""
    w, h = ifd[256][0], ifd[257][0]
    if ifd.get(259, (1,))[0] != 8:
        raise ValueError("expected deflate compression (8)")
    if ifd.get(317, (1,))[0] != 1:
        raise ValueError("unsupported predictor")
    tw, th = ifd[322][0], ifd[323][0]
    across = -(-w // tw)
    grid = [bytearray(w) for _ in range(h)]
    for k, (o, n) in enumerate(zip(ifd[324], ifd[325])):
        px = zlib.decompress(read(o, n))
        ty, tx = divmod(k, across)
        x0, y0 = tx * tw, ty * th
        cw = min(tw, w - x0)
        for r in range(min(th, h - y0)):
            grid[y0 + r][x0:x0 + cw] = px[r * tw:r * tw + cw]
    return w, h, [bytes(g).decode("latin-1") for g in grid]


class WorldCover(Source):
    info = SourceInfo(
        id="worldcover",
        title="ESA WorldCover 10 m 2021 v200",
        publisher="Agencia Espacial Europea (ESA), consorcio WorldCover",
        homepage="https://esa-worldcover.org/",
        license="CC BY 4.0. © ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) "
        "processed by ESA WorldCover consortium. Zanaga et al. 2022, doi:10.5281/zenodo.7254221. Texto de atribución exigido, se mantiene en inglés.",
        description="Clases de cobertura del suelo globales a 10 m para 2021. Solo se lee la vista general más pequeña (píxeles de ~600 m, "
        "vecino más cercano) de cada tesela de 3x3 grados, mediante peticiones HTTP por rangos. La cobertura de cada hexágono "
        "(porcentajes de arbolado, cultivos y construido) sale de los píxeles que contiene.",
        used_for=["Cobertura del suelo por hexágono", "Porcentajes de arbolado, cultivos y construido"],
    )

    def _last_ifd(self, tile: str, url: str):
        head = self.download(url, f"{tile}.head.bin", headers={"Range": f"bytes=0-{HEAD_BYTES - 1}"}).read_bytes()
        try:
            return parse_ifds(head)[-1]
        except (IndexError, struct.error):  # IFD chain longer than the first 128 KB: fetch a bigger head
            big = self.download(url, f"{tile}.head2.bin", headers={"Range": f"bytes=0-{8 * HEAD_BYTES - 1}"})
            return parse_ifds(big.read_bytes())[-1]

    def fetch(self, force=False):
        for tile, _, _ in needed_tiles():
            url = URL.format(tile=tile)
            try:
                ifd = self._last_ifd(tile, url)
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
                print(f"    {tile}: no tile published (open ocean), skipped")
                continue
            o, n = ifd[324], ifd[325]
            lo, hi = min(o), max(a + b for a, b in zip(o, n))
            self.download(url, f"{tile}.ov.bin", headers={"Range": f"bytes={lo}-{hi - 1}"}, force=force)

    def process(self):
        tiles, files, unknown = {}, [], set()
        inv = {code: ch for code, ch in LEGEND.items()}
        for tile, lat0, lon0 in needed_tiles():
            if not (self.raw_dir / f"{tile}.ov.bin").exists():
                continue  # no tile published (open ocean)
            ifd = self._last_ifd(tile, URL.format(tile=tile))
            lo = min(ifd[324])
            blob = (self.raw_dir / f"{tile}.ov.bin").read_bytes()
            w, h, raw = decode_ifd(ifd, lambda o, n: blob[o - lo:o - lo + n])
            table = {}
            rows = []
            for r in raw:
                for ch in set(r):
                    code = ord(ch)
                    if code not in inv:
                        unknown.add(code)
                    table[ord(ch)] = inv.get(code, ".")
                rows.append(r.translate(table))
            tiles[tile] = {"lat0": lat0, "lon0": lon0, "w": w, "h": h, "rows": rows}
            files += [f"{tile}.head.bin", f"{tile}.ov.bin"]
        if unknown:
            print(f"    warning: unknown WorldCover codes treated as nodata: {sorted(unknown)}")
        return {
            "vintage": "ESA WorldCover v200 (2021), última vista general (~600 m)",
            "_files": files,
            "tiles": tiles,
            "legend": {ch: code for code, ch in LEGEND.items()},
            "classes": CLASSES,
            "tiles_note": "rows[0] is the north edge (lat0 + 3), column 0 the west edge (lon0)",
        }
