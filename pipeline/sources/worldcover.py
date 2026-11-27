"""ESA WorldCover v200 (2021), read from the smallest overview of each 3x3 degree Cloud Optimized GeoTIFF."""

import math
import time
import urllib.error
import urllib.request
import struct
import zlib

from ..core.paths import RAW
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


# ---------------------------------------------------------------- finer overview for city maps
# City maps read the overview whose pixels are at most ~80 m (level 3 of the COG pyramid: 4500 px per 3 degrees),
# but only the 1024 px TIFF tiles that touch the scope's bounding box, with HTTP Range requests. The bytes are cached
# under data/raw/worldcover/city/. This does not touch what WorldCover.fetch() and process() read or write.

CITY_UA = "spain-strategy-map/1.0 (open-source map project)"
CITY_CACHE = RAW / "worldcover" / "city"
MAX_PIXEL_M = 80.0


def pick_overview(ifds: list[dict], max_pixel_m: float = MAX_PIXEL_M) -> int:
    """Index of the coarsest IFD whose pixels are at most `max_pixel_m` wide (3 degrees = 333.9 km along a meridian)."""
    ok = [i for i, d in enumerate(ifds) if 333_960.0 / d[256][0] <= max_pixel_m]
    if not ok:
        raise ValueError("no overview fine enough")
    return max(ok, key=lambda i: -ifds[i][256][0])


def tiles_for_bbox(lon_min: float, lat_min: float, lon_max: float, lat_max: float) -> list[tuple[str, int, int]]:
    """3x3 degree WorldCover tiles (name, lat0, lon0) touched by a lon/lat bbox."""
    out = []
    for lat0 in range(math.floor(lat_min / 3) * 3, math.floor(lat_max / 3) * 3 + 1, 3):
        for lon0 in range(math.floor(lon_min / 3) * 3, math.floor(lon_max / 3) * 3 + 1, 3):
            out.append((tile_name(lat0, lon0), lat0, lon0))
    return out


def _cached_range(url: str, name: str, start: int, end: int) -> bytes:
    """Bytes start..end-1 of `url`, cached as data/raw/worldcover/city/<name> (written atomically)."""
    from ..core import fetch

    path = CITY_CACHE / name
    if path.exists() and path.stat().st_size == end - start:
        return path.read_bytes()
    if fetch.OFFLINE:
        raise fetch.OfflineError(f"{name} is not cached and --offline is set")
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": CITY_UA, "Range": f"bytes={start}-{end - 1}"})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            if len(data) != end - start:
                raise OSError(f"short read {len(data)} of {end - start}")
            CITY_CACHE.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{name}.tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
            return data
        except (OSError, urllib.error.URLError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 404:
                raise
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise last


class CoverWindow:
    """WorldCover class codes (ints, 0 = no data) of a lon/lat window at ~60-80 m. `at(lon, lat)` -> code."""

    def __init__(self, level: int, pixel_m: float):
        self.level, self.pixel_m = level, pixel_m
        self.tiles: dict[str, dict] = {}  # tile name -> {lat0, lon0, w, h, tw, th, across, px: {k: bytes}}
        self.bytes_read = 0
        self.tiff_tiles = 0

    def at(self, lon: float, lat: float) -> int:
        for t in self.tiles.values():
            dx, dy = lon - t["lon0"], t["lat0"] + 3 - lat
            if 0 <= dx < 3 and 0 <= dy < 3:
                x, y = int(dx * t["w"] / 3), int(dy * t["h"] / 3)
                px = t["px"].get((y // t["th"]) * t["across"] + x // t["tw"])
                return px[(y % t["th"]) * t["tw"] + x % t["tw"]] if px else 0
        return 0


def read_window(lon_min: float, lat_min: float, lon_max: float, lat_max: float, max_pixel_m: float = MAX_PIXEL_M) -> CoverWindow:
    """Fetch (HTTP Range, cached) and decode the TIFF tiles of a ~60-80 m overview that touch the bbox.
    Raises if a needed tile cannot be read; callers fall back to `coarse_window()`."""
    win = None
    for tile, lat0, lon0 in tiles_for_bbox(lon_min, lat_min, lon_max, lat_max):
        if tile in NO_TILE:
            continue
        url = URL.format(tile=tile)
        head = HEAD_BYTES
        while True:
            try:
                ifds = parse_ifds(_cached_range(url, f"{tile}.head.bin", 0, head))
                break
            except (IndexError, struct.error):
                head *= 8
                if head > 8 * HEAD_BYTES * 8:
                    raise
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise
                ifds = None
                break
        if ifds is None:
            continue  # no tile published (open sea)
        li = pick_overview(ifds)
        ifd = ifds[li]
        w, h, tw, th = ifd[256][0], ifd[257][0], ifd[322][0], ifd[323][0]
        if ifd.get(259, (1,))[0] != 8 or ifd.get(317, (1,))[0] != 1:
            raise ValueError("unsupported compression or predictor")
        win = win or CoverWindow(li, 333_960.0 / w)
        across = -(-w // tw)
        x0, x1 = max(0, int((lon_min - lon0) * w / 3)), min(w - 1, int((lon_max - lon0) * w / 3))
        y0, y1 = max(0, int((lat0 + 3 - lat_max) * h / 3)), min(h - 1, int((lat0 + 3 - lat_min) * h / 3))
        px = {}
        if x1 >= x0 and y1 >= y0 and lon_min < lon0 + 3 and lon_max >= lon0 and lat_min < lat0 + 3 and lat_max >= lat0:
            for ty in range(y0 // th, y1 // th + 1):
                for tx in range(x0 // tw, x1 // tw + 1):
                    k = ty * across + tx
                    o, n = ifd[324][k], ifd[325][k]
                    raw = _cached_range(url, f"{tile}.L{li}.{k}.bin", o, o + n)
                    win.bytes_read += n
                    win.tiff_tiles += 1
                    px[k] = zlib.decompress(raw)
        win.tiles[tile] = {"lat0": lat0, "lon0": lon0, "w": w, "h": h, "tw": tw, "th": th, "across": across, "px": px}
    if win is None:
        raise ValueError("no WorldCover tile for the bbox")
    return win


class _CoarseWindow:
    """Fallback: the smallest overview (~600 m pixels) that WorldCover.process() already wrote to the interim."""

    level, pixel_m, bytes_read, tiff_tiles = -1, 600.0, 0, 0

    def __init__(self, doc: dict):
        self.tiles, self.legend = doc["tiles"], doc["legend"]

    def at(self, lon: float, lat: float) -> int:
        for t in self.tiles.values():
            dx, dy = lon - t["lon0"], t["lat0"] + 3 - lat
            if 0 <= dx < 3 and 0 <= dy < 3:
                return self.legend.get(t["rows"][min(t["h"] - 1, int(dy * t["h"] / 3))][min(t["w"] - 1, int(dx * t["w"] / 3))], 0)
        return 0


def coarse_window():
    from ..core.store import load_interim

    return _CoarseWindow(load_interim("worldcover"))
