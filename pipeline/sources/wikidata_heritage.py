"""Wikidata (CC0): Patrimonio Mundial de la UNESCO en España y parques nacionales de España."""

import json
import re
import time
import urllib.error
import urllib.parse

from ..core.source import Source, SourceInfo

ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "spain-strategy-map/1.0 (open-source map project)"
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"}
NATIONAL_PARK_CLASS = "Q1316973"  # clase "parque nacional" que usa Wikidata para los parques españoles (P31); P17 = España filtra el resto
PAUSE_S = 65  # el servicio SPARQL limita las consultas a una por minuto

WH_QUERY = """SELECT ?item ?itemLabel ?unesco ?coord ?crit ?partOf ?hasParts WHERE {
  ?item wdt:P1435 wd:Q9259 ; wdt:P17 wd:Q29 ; wdt:P757 ?unesco .
  OPTIONAL { ?item wdt:P625 ?coord }
  OPTIONAL { ?item wdt:P2614 ?c . ?c rdfs:label ?crit FILTER(LANG(?crit)="en") }
  OPTIONAL { ?item wdt:P361 ?partOf }
  BIND(EXISTS { ?item wdt:P527 [] } AS ?hasParts)
  SERVICE wikibase:label { bd:serviceParam wikibase:language "es,en,mul,ca,gl,eu,fr". }
}"""

NP_QUERY = """SELECT ?item ?itemLabel ?coord WHERE {
  ?item wdt:P31 ?cls ; wdt:P17 wd:Q29 . VALUES ?cls { wd:%s wd:Q46169 }
  OPTIONAL { ?item wdt:P625 ?coord }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "es,en,mul,ca,gl,eu,fr". }
}"""


def _qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def parse_point(wkt: str | None):
    """'Point(lon lat)' -> (lon, lat) or None."""
    m = re.match(r"\s*Point\(\s*(-?[\d.eE+-]+)\s+(-?[\d.eE+-]+)\s*\)", wkt or "")
    return (float(m.group(1)), float(m.group(2))) if m else None


def _val(b, k):
    return b[k]["value"] if k in b else None


def parse_heritage(bindings: list[dict]) -> list[dict]:
    """Raw rows (one per item x criterion x part-of) -> one record per item, with criteria and parent ids."""
    items: dict[str, dict] = {}
    for b in bindings:
        q = _qid(b["item"]["value"])
        it = items.setdefault(q, {"qid": q, "label": _val(b, "itemLabel"), "unesco": _val(b, "unesco"), "points": [],
                                  "criteria": set(), "part_of": set(), "has_parts": False})
        p = parse_point(_val(b, "coord"))
        if p and p not in it["points"]:
            it["points"].append(p)
        m = re.search(r"\(([ivx]+)\)", _val(b, "crit") or "")
        if m:
            it["criteria"].add(m.group(1))
        if _val(b, "partOf"):
            it["part_of"].add(_qid(b["partOf"]["value"]))
        it["has_parts"] = it["has_parts"] or _val(b, "hasParts") == "true"
    out = []
    for it in items.values():
        out.append({**it, "criteria": sorted(it["criteria"]), "part_of": sorted(it["part_of"])})
    return sorted(out, key=lambda i: int(i["qid"][1:]))


def parse_parks(bindings: list[dict]) -> list[dict]:
    items: dict[str, dict] = {}
    for b in bindings:
        q = _qid(b["item"]["value"])
        it = items.setdefault(q, {"qid": q, "label": _val(b, "itemLabel"), "points": []})
        p = parse_point(_val(b, "coord"))
        if p and p not in it["points"]:
            it["points"].append(p)
    return sorted(items.values(), key=lambda i: int(i["qid"][1:]))


class WikidataHeritage(Source):
    info = SourceInfo(
        id="wikidata_heritage",
        title="Wikidata: Patrimonio Mundial y parques nacionales de España",
        publisher="Wikidata",
        homepage="https://www.wikidata.org/",
        license="CC0 (dominio público)",
        description="Bienes españoles de la lista del Patrimonio Mundial (UNESCO) y parques nacionales de España, "
        "con sus coordenadas, consultados al servicio SPARQL de Wikidata.",
        used_for=["Capa Patrimonio y parques"],
    )

    FILES = {"wh": ("heritage.json", WH_QUERY), "np": ("parks.json", NP_QUERY % NATIONAL_PARK_CLASS)}

    def _url(self, query: str) -> str:
        return ENDPOINT + "?format=json&query=" + urllib.parse.quote(query)

    def fetch(self, force=False):
        for k, (rel, query) in enumerate(self.FILES.values()):
            cached = (self.raw_dir / rel).exists() and not force
            if k and not cached:
                time.sleep(PAUSE_S)
            for attempt in range(3):
                try:
                    self.download(self._url(query), rel, force=force, headers=HEADERS)
                    break
                except urllib.error.HTTPError as e:
                    if e.code != 429 or attempt == 2:
                        raise
                    time.sleep(PAUSE_S)

    def _bindings(self, rel):
        return json.loads((self.raw_dir / rel).read_text(encoding="utf-8"))["results"]["bindings"]

    def process(self):
        return {
            "vintage": "Wikidata (consulta SPARQL)",
            "_files": [r for r, _ in self.FILES.values()],
            "heritage": parse_heritage(self._bindings("heritage.json")),
            "parks": parse_parks(self._bindings("parks.json")),
        }
