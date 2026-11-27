"""Small, dependency-free geometry helpers.

Everything on the map lives in "map km": an Albers equal-area projection of Spain
(standard parallels 36/44, origin 40N 3W) with the Canary Islands drawn in an
inset frame in the Atlantic, shifted so the top-left of the map is (0, 0) and
y points *down* (like screen coordinates). Both the hex grid and the browser
use this space.
"""

from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from typing import IO, Iterable, Iterator

R_EARTH_KM = 6371.0088


class Albers:
    """Albers equal-area conic, standard USGS parameters for the lower 48."""

    def __init__(self, lat1=29.5, lat2=45.5, lat0=37.5, lon0=-96.0):
        p1, p2, p0 = map(math.radians, (lat1, lat2, lat0))
        self.lon0 = math.radians(lon0)
        self.n = (math.sin(p1) + math.sin(p2)) / 2
        self.c = math.cos(p1) ** 2 + 2 * self.n * math.sin(p1)
        self.rho0 = R_EARTH_KM * math.sqrt(self.c - 2 * self.n * math.sin(p0)) / self.n

    def __call__(self, lon: float, lat: float) -> tuple[float, float]:
        rho = R_EARTH_KM * math.sqrt(self.c - 2 * self.n * math.sin(math.radians(lat))) / self.n
        theta = self.n * (math.radians(lon) - self.lon0)
        return rho * math.sin(theta), self.rho0 - rho * math.cos(theta)

    def inverse(self, x: float, y: float) -> tuple[float, float]:
        """Albers km → (lon, lat)."""
        dy = self.rho0 - y
        rho = math.hypot(x, dy)
        theta = math.atan2(x, dy)
        s = (self.c - (rho * self.n / R_EARTH_KM) ** 2) / (2 * self.n)
        return math.degrees(self.lon0 + theta / self.n), math.degrees(math.asin(max(-1.0, min(1.0, s))))


class AlbersEllipsoid:
    """Ellipsoidal Albers equal-area (Snyder 1987, eqs. 14-3..14-6), output in metres.

    Defaults are EPSG:5070 (NAD83 / Conus Albers): GRS80, lat0 23, lon0 -96,
    standard parallels 29.5 and 45.5. Used to look up rasters such as NLCD.
    """

    def __init__(self, lat1=29.5, lat2=45.5, lat0=23.0, lon0=-96.0, a=6378137.0, inv_f=298.257222101):
        f = 1 / inv_f
        self.a = a
        self.e2 = f * (2 - f)
        self.e = math.sqrt(self.e2)
        self.lon0 = math.radians(lon0)
        p1, p2, p0 = map(math.radians, (lat1, lat2, lat0))
        m1, m2 = self._m(p1), self._m(p2)
        q1, q2, q0 = self._q(p1), self._q(p2), self._q(p0)
        self.n = (m1 * m1 - m2 * m2) / (q2 - q1)
        self.c = m1 * m1 + self.n * q1
        self.rho0 = a * math.sqrt(self.c - self.n * q0) / self.n

    def _m(self, phi: float) -> float:
        s = math.sin(phi)
        return math.cos(phi) / math.sqrt(1 - self.e2 * s * s)

    def _q(self, phi: float) -> float:
        s, e = math.sin(phi), self.e
        return (1 - self.e2) * (s / (1 - self.e2 * s * s) - math.log((1 - e * s) / (1 + e * s)) / (2 * e))

    def __call__(self, lon: float, lat: float) -> tuple[float, float]:
        rho = self.a * math.sqrt(self.c - self.n * self._q(math.radians(lat))) / self.n
        theta = self.n * (math.radians(lon) - self.lon0)
        return rho * math.sin(theta), self.rho0 - rho * math.cos(theta)


@dataclass
class Inset:
    """A far-away region drawn inside a fixed frame of the main map.

    `box` = (lon0, lat0, lon1, lat1): points inside it belong to the inset.
    `albers` = (lat1, lat2, lat0, lon0) of the inset's own projection.
    `frame` = (x0, y0, x1, y1) in main-Albers km (y up). The projected box is
    centred inside the frame by a fixed translation (tx, ty).
    """

    name: str
    box: tuple[float, float, float, float]
    albers: tuple[float, float, float, float]
    frame: tuple[float, float, float, float]
    proj: Albers = field(init=False, repr=False)
    tx: float = field(init=False, repr=False)
    ty: float = field(init=False, repr=False)

    def __post_init__(self):
        self.proj = Albers(*self.albers)
        lon0, lat0, lon1, lat1 = self.box
        pts = []
        for i in range(41):
            t = i / 40
            lo, la = lon0 + (lon1 - lon0) * t, lat0 + (lat1 - lat0) * t
            pts += [self.proj(lo, lat0), self.proj(lo, lat1), self.proj(lon0, la), self.proj(lon1, la)]
        cx = (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2
        cy = (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2
        x0, y0, x1, y1 = self.frame
        self.tx, self.ty = (x0 + x1) / 2 - cx, (y0 + y1) / 2 - cy

    def contains_lonlat(self, lon: float, lat: float) -> bool:
        lon0, lat0, lon1, lat1 = self.box
        return lon0 <= lon <= lon1 and lat0 <= lat <= lat1

    def contains_xy(self, x: float, y: float) -> bool:
        """Is a main-Albers km point inside the frame?"""
        x0, y0, x1, y1 = self.frame
        return x0 <= x <= x1 and y0 <= y <= y1

    def project(self, lon: float, lat: float) -> tuple[float, float]:
        """lon/lat -> main-Albers km (y up), already translated into the frame."""
        x, y = self.proj(lon, lat)
        return x + self.tx, y + self.ty

    def inverse(self, x: float, y: float) -> tuple[float, float]:
        return self.proj.inverse(x - self.tx, y - self.ty)


# Move the frame here (main-Albers km, y up). Bottom right of the map, over the Mediterranean and the Algerian
# coast: south of Cartagena and Formentera, east of Melilla and Cabo de Gata. The bottom-left corner of the screen
# belongs to the minimap, so the frame stays away from it.
INSETS = (Inset("Canarias", (-18.6, 27.3, -13.0, 29.7), (27.6, 29.4, 28.5, -15.75), (110.0, -610.0, 620.0, -380.0)),)

MAIN_ALBERS = (36.0, 44.0, 40.0, -3.0)


def fit_bounds(points_main_albers: Iterable[tuple[float, float]], insets=INSETS, margin: float = 0.0):
    """Bounds covering main-Albers points (km, y up) and every inset frame.

    Returns (min_x, max_y, width, height) in km, including `margin` on every
    side, ready for MapProjection(min_x, max_y, margin) and the map size.
    """
    xs, ys = [], []
    for x, y in points_main_albers:
        xs.append(x)
        ys.append(y)
    for ins in insets:
        x0, y0, x1, y1 = ins.frame
        xs += [x0, x1]
        ys += [y0, y1]
    return min(xs), max(ys), max(xs) - min(xs) + 2 * margin, max(ys) - min(ys) + 2 * margin


@dataclass
class MapProjection:
    """lon/lat -> map km (origin top-left, y down), Canary Islands in an inset."""

    min_x: float
    max_y: float
    margin: float
    insets: tuple = INSETS

    def __post_init__(self):
        self._albers = Albers(*MAIN_ALBERS)

    def _shift(self, x: float, y: float) -> tuple[float, float]:
        return x - self.min_x + self.margin, self.max_y - y + self.margin

    def _unshift(self, X: float, Y: float) -> tuple[float, float]:
        return X + self.min_x - self.margin, self.max_y + self.margin - Y

    def _inset(self, name: str | None):
        return next((i for i in self.insets if i.name == name), None)

    def region_of(self, lon: float, lat: float) -> str:
        for ins in self.insets:
            if ins.contains_lonlat(lon, lat):
                return ins.name
        return "main"

    def ring_region(self, ring) -> str:
        """Region of a ring, decided once from its lon/lat bbox centre."""
        lons = [p[0] for p in ring]
        lats = [p[1] for p in ring]
        return self.region_of((min(lons) + max(lons)) / 2, (min(lats) + max(lats)) / 2)

    def __call__(self, lon: float, lat: float, region: str | None = None) -> tuple[float, float]:
        if region is None:
            region = self.region_of(lon, lat)
        ins = self._inset(region) if region != "main" else None
        x, y = ins.project(lon, lat) if ins else self._albers(lon, lat)
        return self._shift(x, y)

    def project_ring(self, ring) -> list[tuple[float, float]]:
        region = self.ring_region(ring)
        return [self(p[0], p[1], region) for p in ring]

    def hidden(self, lon: float, lat: float) -> bool:
        """True if a main-region point lands under an inset frame (callers drop it)."""
        if self.region_of(lon, lat) != "main":
            return False
        x, y = self._albers(lon, lat)
        return any(i.contains_xy(x, y) for i in self.insets)

    def frame_at(self, X: float, Y: float) -> str | None:
        x, y = self._unshift(X, Y)
        return next((i.name for i in self.insets if i.contains_xy(x, y)), None)

    def inverse(self, X: float, Y: float) -> tuple[float, float]:
        """map km -> (lon, lat); inside an inset frame the inset's inverse is used."""
        x, y = self._unshift(X, Y)
        for ins in self.insets:
            if ins.contains_xy(x, y):
                return ins.inverse(x, y)
        return self._albers.inverse(x, y)

    def frames(self) -> list[dict]:
        out = []
        for ins in self.insets:
            x0, y0, x1, y1 = ins.frame
            (ax, ay), (bx, by) = self._shift(x0, y1), self._shift(x1, y0)
            out.append({"name": ins.name, "x0": round(ax, 1), "y0": round(ay, 1), "x1": round(bx, 1), "y1": round(by, 1)})
        return out

    def to_dict(self) -> dict:
        return {"min_x": self.min_x, "max_y": self.max_y, "margin": self.margin}


def ring_contains(ring: list[tuple[float, float]], x: float, y: float) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


class Shape:
    """A (multi)polygon as a bag of rings; even-odd rule handles holes."""

    def __init__(self, rings: Iterable[list[tuple[float, float]]]):
        self.rings = [r for r in rings if len(r) >= 3]
        xs = [p[0] for r in self.rings for p in r] or [0]
        ys = [p[1] for r in self.rings for p in r] or [0]
        self.bbox = (min(xs), min(ys), max(xs), max(ys))

    def contains(self, x: float, y: float) -> bool:
        x0, y0, x1, y1 = self.bbox
        if x < x0 or x > x1 or y < y0 or y > y1:
            return False
        inside = False
        for r in self.rings:
            if ring_contains(r, x, y):
                inside = not inside
        return inside


class ShapeIndex:
    """Bucket shapes by coarse grid square so point lookups only test a few shapes."""

    def __init__(self, shapes: list[Shape], cell_km: float = 100.0):
        self.shapes = shapes
        self.cell = cell_km
        self.buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
        for k, s in enumerate(shapes):
            x0, y0, x1, y1 = s.bbox
            for gx in range(int(x0 // cell_km), int(x1 // cell_km) + 1):
                for gy in range(int(y0 // cell_km), int(y1 // cell_km) + 1):
                    self.buckets[(gx, gy)].append(k)

    def locate(self, x: float, y: float) -> int:
        for k in self.buckets.get((int(x // self.cell), int(y // self.cell)), ()):
            if self.shapes[k].contains(x, y):
                return k
        return -1


# --- file formats -----------------------------------------------------------

KML_NS = "{http://www.opengis.net/kml/2.2}"


def read_kml_placemarks(fileobj: IO[bytes]) -> Iterator[tuple[dict, list[list[tuple[float, float]]]]]:
    """Yield (properties, rings) for each Placemark in a Census cartographic KML."""
    for _, el in ET.iterparse(fileobj):
        if el.tag != KML_NS + "Placemark":
            continue
        props = {sd.get("name"): (sd.text or "") for sd in el.iter(KML_NS + "SimpleData")}
        rings = []
        for coords in el.iter(KML_NS + "coordinates"):
            pts = []
            for tok in (coords.text or "").split():
                lon, lat = tok.split(",")[:2]
                pts.append((round(float(lon), 5), round(float(lat), 5)))
            rings.append(pts)
        yield props, rings
        el.clear()


def geojson_rings(geom: dict) -> list[list[tuple[float, float]]]:
    t, c = geom["type"], geom["coordinates"]
    polys = [c] if t == "Polygon" else c if t == "MultiPolygon" else []
    return [[(round(x, 5), round(y, 5)) for x, y, *_ in ring] for poly in polys for ring in poly]


def geojson_lines(geom: dict) -> list[list[tuple[float, float]]]:
    t, c = geom["type"], geom["coordinates"]
    lines = [c] if t == "LineString" else c if t == "MultiLineString" else []
    return [[(round(x, 5), round(y, 5)) for x, y, *_ in line] for line in lines]


def load_geojson(path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)["features"]


def bbox_intersects(points: Iterable[tuple[float, float]], bbox: tuple[float, float, float, float]) -> bool:
    x0, y0, x1, y1 = bbox
    return any(x0 <= x <= x1 and y0 <= y <= y1 for x, y in points)
