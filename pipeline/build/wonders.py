"""Patrimonio y parques: bienes españoles del Patrimonio Mundial de la UNESCO y parques nacionales (Wikidata, CC0).

* patrimonio_mundial: un marcador por identificador UNESCO. Wikidata guarda como elementos sueltos las extensiones
  (378-004, 669bis-007) y los componentes de los bienes en serie; aquí se agrupan por el número UNESCO base y se queda
  el elemento principal. Los bienes en serie o en red llevan "serial": true: su marcador es un punto representativo.
* parque_nacional: elementos de Wikidata que son parque nacional de España, con su primera coordenada.

Sin cifras de visitantes: `metrics` va vacío. Escribe web/data/wonders.json. Usa el Locator de resources.py.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

from ..core.store import load_interim_payload, write_web
from .resources import load_locator

REQUIRES = ["_world", "gisco_lau", "wikidata_heritage", "cities.json"]
PRODUCES = ["wonders.json"]

SPAIN_BBOX = (-19.0, 27.0, 5.0, 44.5)  # lon0, lat0, lon1, lat1: Península, Baleares, Canarias, Ceuta y Melilla
SERIAL_KM = 3.0
SERIAL_IDS = {"310", "320", "378", "522", "669", "773", "866", "874", "988", "1133", "1313", "1501", "1528"}
NATURAL, CULTURAL = {"vii", "viii", "ix", "x"}, {"i", "ii", "iii", "iv", "v", "vi"}
# Elementos que Wikidata clasifica como parque nacional pero que son parte de otro parque ya contado.
PART_OF_ANOTHER_PARK = {"Q1658753"}  # Illas Cíes, dentro del P. N. de las Islas Atlánticas de Galicia
OFFICIAL_COUNT = 50  # bienes de España en la Lista del Patrimonio Mundial (cifra aproximada de la UNESCO)
ATTRIBUTION = [{"data": "bienes del Patrimonio Mundial en España y parques nacionales, con sus coordenadas",
                "source": "Wikidata", "license": "CC0 (dominio público)"}]
RULES = [
    {"id": "patrimonio_mundial", "kind": "landmark", "kinds": ["monument", "natural", "landmark"], "curated": False,
     "text": "Bienes españoles de la Lista del Patrimonio Mundial de la UNESCO según Wikidata, un marcador por "
             "identificador UNESCO. El tipo sale de los criterios UNESCO: solo culturales = monumento, solo naturales = "
             "natural, mixtos o sin criterio = hito. En los bienes en serie o en red (marcados con serial) el marcador "
             "es un punto representativo, no todo el conjunto. Orden alfabético; no hay cifras de visitantes."},
    {"id": "parque_nacional", "kind": "natural", "kinds": ["natural"], "curated": False,
     "text": "Parques nacionales de España según Wikidata, con la primera coordenada que da cada uno. Los parques "
             "marinos o con islotes pueden no tener tierra española a 2 hexágonos y no se dibujan. Un parque que también "
             "es Patrimonio Mundial aparece en las dos reglas. Orden alfabético; no hay cifras de visitantes."},
]


def haversine_km(a, b) -> float:
    (lo1, la1), (lo2, la2) = a, b
    p1, p2 = math.radians(la1), math.radians(la2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def in_spain(p) -> bool:
    return SPAIN_BBOX[0] <= p[0] <= SPAIN_BBOX[2] and SPAIN_BBOX[1] <= p[1] <= SPAIN_BBOX[3]


def base_id(unesco: str) -> str:
    m = re.match(r"\d+", unesco or "")
    return m.group(0) if m else unesco


def pick_main(group: list[dict], base: str) -> dict:
    """El elemento principal de un identificador UNESCO: el que lo lleva tal cual, que no es parte de otro, que tiene
    partes, que tiene criterios, que tiene coordenadas; a igualdad, el de número Q más bajo."""
    return min(group, key=lambda i: (i["unesco"] != base, bool(i["part_of"]), not i["has_parts"], not i["criteria"],
                                     not i["points"], int(i["qid"][1:])))


def kind_of(criteria) -> str:
    c = set(criteria)
    if c and c <= CULTURAL:
        return "monument"
    if c and c <= NATURAL:
        return "natural"
    return "landmark"


def dedupe_heritage(rows: list[dict]) -> list[dict]:
    """Un registro por identificador UNESCO base: qid, nombre, tipo, punto (lon, lat) o None, serial."""
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(base_id(r["unesco"]), []).append(r)
    out = []
    for base, group in groups.items():
        main = pick_main(group, base)
        pts = [p for p in main["points"] if in_spain(p)] or [p for g in group for p in g["points"] if in_spain(p)]
        allp = [g["points"][0] for g in group if g["points"]]
        spread = max((haversine_km(a, b) for a in allp for b in allp), default=0.0)
        crit = main["criteria"] or sorted({c for g in group for c in g["criteria"]})
        out.append({"unesco": base, "qid": main["qid"], "name": main["label"], "kind": kind_of(crit),
                    "point": pts[0] if pts else None,
                    "serial": base in SERIAL_IDS or (len({g["qid"] for g in group}) > 1 and spread > SERIAL_KM)})
    return sorted(out, key=lambda r: (r["name"].lower(), r["unesco"]))


def short_park(name: str) -> str:
    s = re.sub(r"^parque nacional( y natural| marítimo[- ]terrestre)?( de(l| la| las| los)?)? ?", "", name, flags=re.I)
    return (s or name)[:1].upper() + (s or name)[1:]


def dedupe_parks(rows: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in rows:
        if r["qid"] in seen or r["qid"] in PART_OF_ANOTHER_PARK:
            continue
        seen.add(r["qid"])
        pts = [p for p in r["points"] if in_spain(p)]
        out.append({"qid": r["qid"], "name": r["label"][:1].upper() + r["label"][1:], "point": pts[0] if pts else None})
    return sorted(out, key=lambda r: r["name"].lower())


def make_wonders(heritage: list[dict], parks: list[dict], place) -> tuple[list[dict], list[str]]:
    wonders, missing = [], []
    for rule, recs in (("patrimonio_mundial", heritage), ("parque_nacional", parks)):
        rank = 0
        for r in recs:
            pos = place(*r["point"]) if r["point"] else None
            if pos is None:
                missing.append(f"{rule}: {r['name']}")
                continue
            rank += 1
            w = {"id": f"whc-{r['unesco']}" if rule == "patrimonio_mundial" else f"pn-{r['qid']}",
                 "name": r["name"], "short": r["name"] if rule == "patrimonio_mundial" else short_park(r["name"]),
                 "kind": r["kind"] if rule == "patrimonio_mundial" else "natural", "rule": rule, "rank": rank,
                 "metrics": {}, "qid": r["qid"], **pos, "cells": None, "curated": False}
            if rule == "patrimonio_mundial":
                w["unesco"] = r["unesco"]
                if r["serial"]:
                    w["serial"] = True
            wonders.append(w)
    return wonders, missing


def build() -> None:
    loc = load_locator()
    payload = load_interim_payload("wikidata_heritage")
    heritage = dedupe_heritage(payload["data"]["heritage"])
    parks = dedupe_parks(payload["data"]["parks"])
    wonders, missing = make_wonders(heritage, parks, loc.place)
    by = Counter(w["rule"] for w in wonders)
    doc = {"version": 1, "vintage": payload.get("vintage"), "sources": ["wikidata_heritage"], "attribution": ATTRIBUTION,
           "rules": RULES, "national": {"patrimonio_mundial": by["patrimonio_mundial"],
                                        "parques_nacionales": by["parque_nacional"]},
           "wonders": wonders}
    write_web("wonders.json", doc)
    print(f"    Patrimonio Mundial: {len(heritage)} identificadores UNESCO tras deduplicar "
          f"({len(heritage) - OFFICIAL_COUNT:+d} frente a las ~{OFFICIAL_COUNT} oficiales), {by['patrimonio_mundial']} con casilla; "
          f"{sum(1 for w in wonders if w.get('serial'))} en serie")
    print(f"    Parques nacionales: {len(parks)} en Wikidata, {by['parque_nacional']} con casilla")
    print(f"    sin casilla a 2 hexágonos o sin punto en España: {missing}")


def check(web_dir) -> list[tuple[str, str]]:
    path = Path(web_dir) / "wonders.json"
    if not path.exists():
        return [("NOTE", "wonders.json no construido (opcional)")]
    d = json.loads(path.read_text(encoding="utf-8"))
    rules = {r["id"] for r in d.get("rules") or []}
    ids, bad = set(), []
    for w in d.get("wonders") or []:
        if w.get("id") in ids or w.get("rule") not in rules or not isinstance(w.get("cell"), int) or w.get("metrics") != {}:
            bad.append(f"wonder {w.get('id')!r} no válido")
        ids.add(w.get("id"))
    if not d.get("attribution"):
        bad.append("falta attribution")
    out = [("FAIL", f"wonders.json: {m}") for m in bad[:12]]
    if not bad:
        out.append(("PASS", f"wonders.json: {len(d['wonders'])} sitios"))
    return out
