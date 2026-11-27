from ..core.geo import bbox_intersects, geojson_lines, geojson_rings, load_geojson
from ..core.source import Source, SourceInfo

# Pinned to a release tag so the content (and sha256) cannot change under the same URL.
TAG = "v5.1.2"
BASE = f"https://raw.githubusercontent.com/nvkelso/natural-earth-vector/{TAG}/geojson"
BBOX = (-20.0, 26.0, 6.5, 46.5)  # lon/lat window around Spain (incl. the Canary Islands) and the map margin


class NaturalEarth(Source):
    info = SourceInfo(
        id="natural_earth",
        title="Natural Earth 1:50m (países, lagos, ríos)",
        publisher="Natural Earth",
        homepage="https://www.naturalearthdata.com/",
        license="Dominio público",
        description="Países vecinos (Portugal, Francia, Andorra, Gibraltar, Marruecos, Argelia; se muestran difuminados), lagos grandes y ríos principales. "
        f"Los archivos están fijados a la versión {TAG} de natural-earth-vector.",
        used_for=["Tierra extranjera (Portugal, Francia, Marruecos...)", "Lagos", "Ríos"],
    )

    FILES = ["ne_50m_admin_0_countries", "ne_50m_lakes", "ne_50m_rivers_lake_centerlines"]

    def _path(self, name):
        return f"{TAG}/{name}.geojson"

    def fetch(self, force=False):
        for name in self.FILES:
            self.download(f"{BASE}/{name}.geojson", self._path(name), force=force)

    def _features(self, name):
        return load_geojson(self.raw_dir / self._path(name))

    def process(self):
        # Every non-Spanish country with land in the window (Spain itself comes from LAU),
        # keeping only its rings there, so foreign coasts inside the map are land rather than sea.
        countries = []
        for f in self._features("ne_50m_admin_0_countries"):
            if f["properties"].get("ADM0_A3") == "ESP":
                continue
            rings = [r for r in geojson_rings(f["geometry"]) if bbox_intersects(r, BBOX)]
            if rings:
                countries.append({"name": f["properties"]["ADMIN"], "rings": rings})
        lakes = []
        for f in self._features("ne_50m_lakes"):
            rings = geojson_rings(f["geometry"])
            if rings and bbox_intersects(rings[0], BBOX):
                lakes.append({"name": f["properties"].get("name"), "rings": rings})
        rivers = []
        for f in self._features("ne_50m_rivers_lake_centerlines"):
            p = f["properties"]
            for line in geojson_lines(f["geometry"]):
                if bbox_intersects(line, BBOX):
                    rivers.append(
                        {"name": p.get("name"), "rank": p.get("scalerank", 10), "featurecla": p.get("featurecla"), "line": line}
                    )
        return {
            "vintage": f"Natural Earth {TAG} (1:50m)",
            "_files": [self._path(n) for n in self.FILES],
            "countries": countries,
            "lakes": lakes,
            "rivers": rivers,
        }
