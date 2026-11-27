from ..core.geo import bbox_intersects, geojson_lines, load_geojson
from ..core.source import Source, SourceInfo

# Pinned to a release tag so the content (and sha256) cannot change under the same URL.
TAG = "v5.1.2"
BASE = f"https://raw.githubusercontent.com/nvkelso/natural-earth-vector/{TAG}/geojson"
BBOX = (-20.0, 26.0, 6.5, 46.5)  # lon/lat window around Spain (incl. the Canary Islands) and the map margin
USER_AGENT = "spain-strategy-map/1.0 (open-source map project)"


def _round(line):
    return [(round(x, 4), round(y, 4)) for x, y in line]


class NaturalEarthInfra(Source):
    """Natural Earth 1:10m roads, railroads and ports. A separate source from the 1:50m set so the map's land and
    water (which the `world` builder reads) do not depend on these large files."""

    info = SourceInfo(
        id="natural_earth_infra",
        title="Natural Earth 1:10m (carreteras, ferrocarriles y puertos)",
        publisher="Natural Earth",
        homepage="https://www.naturalearthdata.com/",
        license="Dominio público",
        description="Carreteras principales, ferrocarriles y puertos como línea y punto a escala 1:10m. Se muestran como "
        "arte de mapa (esquema entre centros de hexágono), no como estadística: sin datos de tráfico ni de titularidad. "
        f"Los archivos están fijados a la versión {TAG} de natural-earth-vector.",
        used_for=["Carreteras y ferrocarril del mapa", "Puertos del mapa"],
    )

    FILES = ["ne_10m_roads", "ne_10m_railroads", "ne_10m_ports"]

    def _path(self, name):
        return f"{TAG}/{name}.geojson"

    def fetch(self, force=False):
        for name in self.FILES:
            self.download(f"{BASE}/{name}.geojson", self._path(name), force=force, headers={"User-Agent": USER_AGENT})

    def process(self):
        roads, rail, ports, types = [], [], [], {}
        for f in load_geojson(self.raw_dir / self._path("ne_10m_roads")):
            p = f["properties"]
            # No country field in Europe or Africa (sov_a3 is empty): the bbox keeps Portuguese, French and Moroccan
            # roads too; the builder clips to Spain.
            if p.get("featurecla") == "Ferry" or str(p.get("type") or "").startswith("Ferry"):
                continue
            lines = [ln for ln in geojson_lines(f["geometry"]) if bbox_intersects(ln, BBOX)]
            if not lines:
                continue
            types[p.get("type")] = types.get(p.get("type"), 0) + 1
            roads.append({
                "type": p.get("type") or None,  # Major Highway, Secondary Highway, Beltway, ...
                "level": p.get("level") or None,
                "ref": (str(p.get("label")).strip() or None) if p.get("label") not in (None, "") else None,
                "ref2": (str(p.get("label2")).strip() or None) if p.get("label2") not in (None, "") else None,
                "expressway": 1 if p.get("expressway") == 1 else 0,
                "scalerank": p.get("scalerank"),
                "lines": [_round(ln) for ln in lines],
            })
        for f in load_geojson(self.raw_dir / self._path("ne_10m_railroads")):
            p = f["properties"]
            # No country field: the bbox keeps Portuguese, French and Moroccan lines too; the builder clips to Spain.
            lines = [ln for ln in geojson_lines(f["geometry"]) if bbox_intersects(ln, BBOX)]
            if lines:
                rail.append({"scalerank": p.get("scalerank"), "category": p.get("category"),
                             "lines": [_round(ln) for ln in lines]})
        for f in load_geojson(self.raw_dir / self._path("ne_10m_ports")):
            lon, lat = f["geometry"]["coordinates"][:2]
            if BBOX[0] <= lon <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]:
                ports.append({"name": f["properties"].get("name"), "scalerank": f["properties"].get("scalerank"),
                              "lon": round(lon, 5), "lat": round(lat, 5)})
        print(f"    {len(roads)} road features in the window ({types}), {len(rail)} rail features and {len(ports)} ports in the window")
        return {
            "vintage": f"Natural Earth {TAG} (1:10m)",
            "_files": [self._path(n) for n in self.FILES],
            "roads": roads,
            "rail": rail,
            "ports": ports,
        }
