"""Spanish municipalities from the Eurostat GISCO LAU 2024 boundaries (1:1 million)."""

import json

from ..core.geo import geojson_rings
from ..core.source import Source, SourceInfo
from ._spain import CCAA, PROVINCE_TO_CCAA

URL = "https://gisco-services.ec.europa.eu/distribution/v2/lau/geojson/LAU_RG_01M_2024_4326.geojson"
FILE = "LAU_RG_01M_2024_4326.geojson"
MIN_MUNICIPALITIES = 8100


def iter_features(text: str):
    """Yield the features of a GeoJSON FeatureCollection one by one, without parsing the whole text at once."""
    dec = json.JSONDecoder()
    key = text.index('"features"')
    pos = text.index("[", key) + 1
    n = len(text)
    while True:
        while pos < n and text[pos] in " \t\r\n,":
            pos += 1
        if pos >= n or text[pos] == "]":
            return
        feat, pos = dec.raw_decode(text, pos)
        yield feat


def parse_spanish_municipalities(text: str) -> list[dict]:
    """Keep only the features whose CNTR_CODE is ES, as municipality dicts sorted by INE code."""
    out = []
    for f in iter_features(text):
        p = f.get("properties") or {}
        if p.get("CNTR_CODE") != "ES":
            continue
        gid = str(p["GISCO_ID"])
        code = gid.split("_", 1)[1]
        province = code[:2]
        if province not in PROVINCE_TO_CCAA:
            raise ValueError(f"unknown province code {province!r} for municipality {gid}")
        out.append({
            "code": code,
            "name": p.get("LAU_NAME"),
            "province": province,
            "ccaa": PROVINCE_TO_CCAA[province],
            "area_km2": round(float(p.get("AREA_KM2") or 0), 2),
            "rings": geojson_rings(f["geometry"]),
        })
    out.sort(key=lambda m: m["code"])
    return out


class GiscoLau(Source):
    info = SourceInfo(
        id="gisco_lau",
        title="Local Administrative Units (LAU) 2024, 1:1 million",
        publisher="Eurostat GISCO",
        homepage="https://ec.europa.eu/eurostat/web/gisco/geodata/statistical-units/local-administrative-units",
        license="© EuroGeographics for the administrative boundaries. GISCO terms: non-commercial use, with this "
        "notice visible on the map; not covered by this project's MIT licence.",
        description="Boundaries of the ~8,100 Spanish municipalities (the EU-wide file is filtered to Spain). "
        "Their union is the Spanish land mass; grouping them by province gives the 19 autonomous communities "
        "(top level of the map) and the municipalities are the second level.",
        used_for=["Map: land vs. water", "Autonomous community borders", "Municipality lookup"],
    )

    def fetch(self, force=False):
        self.download(URL, FILE, force=force)

    def process(self):
        text = (self.raw_dir / FILE).read_text(encoding="utf-8")
        munis = parse_spanish_municipalities(text)
        del text
        if len(munis) < MIN_MUNICIPALITIES:
            raise ValueError(f"only {len(munis)} Spanish municipalities in LAU (expected at least {MIN_MUNICIPALITIES})")
        missing = sorted(set(PROVINCE_TO_CCAA) - {m["province"] for m in munis})
        if missing:
            raise ValueError(f"no municipalities for provinces {missing}")
        return {
            "vintage": "GISCO LAU 2024 (1:1 million)",
            "_files": [FILE],
            "municipalities": munis,
            "ccaa": CCAA,
        }
