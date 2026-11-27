"""City scopes: the same map at city scale (docs/DATA_CONTRACTS.md "City scopes").

SCOPES is generated: "madrid" and "madrid-auf" are written out below; every other city of web/data/cities.json gets
one municipality scope (id = slug of its name, municipality = its core INE code). Adding a different scope = one entry. Two scopes of the same city can coexist (the municipality and its functional
urban area). A scope is plain data:

  id          URL id (?scope=<id>) and folder web/data/city/<id>/
  name, title short name and the title shown on the page
  kind        "municipality" | "urban_area"
  city        INE functional urban area id (data/interim/auf.json) the scope belongs to
  hex_km      hex radius in km; None = chosen at build time from the municipality's area and number of sections
              (radius_for below), then stored in world.scope.hex_km and index.json
  municipalities  list of INE codes, or {"auf": <city id>} to take the members of that urban area
  state_level "district" (states = census districts, CUDIS) | "municipality" (states = municipalities, CUMUN)
  districts   {CUDIS suffix "NN": official name} for state_level "district"; others fall back to "Distrito NN"
  min_banner  banners (cities.json): urban areas only list municipalities with at least this many inhabitants
"""

from __future__ import annotations

import json
import math
import re
import unicodedata

from .core.paths import INTERIM, WEB_DATA

MADRID_DISTRICTS = {
    "01": "Centro", "02": "Arganzuela", "03": "Retiro", "04": "Salamanca", "05": "Chamartín", "06": "Tetuán",
    "07": "Chamberí", "08": "Fuencarral-El Pardo", "09": "Moncloa-Aravaca", "10": "Latina", "11": "Carabanchel",
    "12": "Usera", "13": "Puente de Vallecas", "14": "Moratalaz", "15": "Ciudad Lineal", "16": "Hortaleza",
    "17": "Villaverde", "18": "Villa de Vallecas", "19": "Vicálvaro", "20": "San Blas-Canillejas", "21": "Barajas",
}

HEX_AREA = 1.5 * math.sqrt(3)  # km2 of a hexagon of radius 1 km (2.598)
MIN_HEX_KM, MAX_HEX_KM = 0.08, 0.5
MIN_TARGET_HEXES, MAX_TARGET_HEXES, HEXES_PER_SECTION = 600, 3000, 1.2


def slug(name: str) -> str:
    """URL id of a city: first variant of a bilingual name, no accents, lower case, hyphens ("Alicante / Alacant" -> "alicante")."""
    first = name.split("/")[0].strip()
    ascii_ = "".join(ch for ch in unicodedata.normalize("NFKD", first) if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")


def target_hexes(n_sections: int) -> int:
    """Wanted number of land hexes: 1.2 per census section, between 600 and 3000."""
    return int(min(MAX_TARGET_HEXES, max(MIN_TARGET_HEXES, round(HEXES_PER_SECTION * n_sections))))


def radius_for(area_km2: float, n_sections: int) -> float:
    """Hex radius (km, 0.01 steps, 0.08..0.5) that gives about target_hexes(n_sections) land hexes over area_km2."""
    r = math.sqrt(area_km2 / (HEX_AREA * target_hexes(n_sections)))
    return min(MAX_HEX_KM, max(MIN_HEX_KM, round(r, 2)))


def expected_hexes(area_km2: float, radius_km: float) -> int:
    return round(area_km2 / (HEX_AREA * radius_km * radius_km))


def sections_area_km2(sections: list[dict]) -> float:
    """Area of the sections (lon/lat rings, signed shoelace per section so holes subtract), flat approximation."""
    total = 0.0
    for s in sections:
        lat0 = sum(p[1] for rg in s["rings"] for p in rg[:1]) / max(1, len(s["rings"]))
        kx, ky = 111.195 * math.cos(math.radians(lat0)), 111.195
        a = 0.0
        for rg in s["rings"]:
            a += sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(rg, rg[1:] + rg[:1])) / 2
        total += abs(a) * kx * ky
    return total


def resolve_radius(scope: dict, sections: list[dict]) -> float:
    return scope["hex_km"] if scope.get("hex_km") else radius_for(sections_area_km2(sections), len(sections))


# Official district names for cities where the INE section codes carry only numbers (key = core municipality code).
CITY_DISTRICTS = {
    "08019": {"01": "Ciutat Vella", "02": "Eixample", "03": "Sants-Montjuïc", "04": "Les Corts", "05": "Sarrià-Sant Gervasi",
              "06": "Gràcia", "07": "Horta-Guinardó", "08": "Nou Barris", "09": "Sant Andreu", "10": "Sant Martí"},
    "35016": {"01": "Vegueta-Cono Sur-Tafira", "02": "Centro", "03": "Isleta-Puerto-Guanarteme", "04": "Ciudad Alta",
              "05": "Tamaraceite-San Lorenzo-Tenoya"},
    # Sevilla: codes and names of the city council's districts layer (ide.SEVILLA open data, CC BY 4.0), whose section
    # codes are 41091 + district + section like the INE's; cross-checked with where each district's sections fall.
    "41091": {"01": "Casco Antiguo", "02": "Macarena", "03": "Nervión", "04": "Cerro-Amate", "05": "Sur", "06": "Triana",
              "07": "Norte", "08": "San Pablo-Santa Justa", "09": "Este-Alcosa-Torreblanca", "10": "Bellavista-La Palmera",
              "11": "Los Remedios"},
}

# Cities drawn finer than the general rule (the city-specific layers are built first for these).
HEX_KM_OVERRIDES = {"41091": 0.15}


def municipality_scope(city: dict) -> dict:
    sc = _municipality_scope(city)
    if city["core"] in CITY_DISTRICTS:
        sc["districts"] = {city["core"]: CITY_DISTRICTS[city["core"]]}
    if city["core"] in HEX_KM_OVERRIDES:
        sc["hex_km"] = HEX_KM_OVERRIDES[city["core"]]
    return sc


def _municipality_scope(city: dict) -> dict:
    return {"id": slug(city["name"]), "name": city["name"], "title": city["name"], "kind": "municipality", "city": city["id"],
            "hex_km": None, "municipalities": [city["core"]], "state_level": "district"}


def generate_scopes(cities: list[dict]) -> dict[str, dict]:
    """madrid and madrid-auf as written, plus one municipality scope per other city (ids must be unique)."""
    out = {
        "madrid": {
            "id": "madrid", "name": "Madrid", "title": "Madrid", "kind": "municipality", "city": "ES001F", "hex_km": 0.3,
            "municipalities": ["28079"], "state_level": "district", "districts": {"28079": MADRID_DISTRICTS},
        },
    }
    for c in cities:
        sc = municipality_scope(c)
        if c["id"] == "ES001F":
            continue
        if sc["id"] in out or sc["id"] == "madrid-auf":
            raise ValueError(f"duplicate scope id {sc['id']!r} ({c['id']})")
        out[sc["id"]] = sc
    out["madrid-auf"] = {
        "id": "madrid-auf", "name": "Madrid", "title": "Área urbana de Madrid", "kind": "urban_area", "city": "ES001F",
        "hex_km": 1.2, "municipalities": {"auf": "ES001F"}, "state_level": "municipality", "min_banner": 50_000,
    }
    return out


def _load_cities() -> list[dict]:
    try:
        return json.loads((WEB_DATA / "cities.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


SCOPES: dict[str, dict] = generate_scopes(_load_cities())

LEVELS = {
    "district": {"state": {"one": "Distrito", "many": "Distritos"}, "county": {"one": "Sección censal", "many": "Secciones censales"}},
    "municipality": {"state": {"one": "Municipio", "many": "Municipios"}, "county": {"one": "Sección censal", "many": "Secciones censales"}},
}

_ARTICLE = re.compile(r"^(.*), (El|La|Los|Las|L'|Els|Les|O|A|Os|As)$")


def fix_name(name: str) -> str:
    """INE puts the article last: "Rozas de Madrid, Las" -> "Las Rozas de Madrid"."""
    m = _ARTICLE.match(name.strip())
    if not m:
        return name.strip()
    art = m.group(2)
    return f"{art}{m.group(1)}" if art.endswith("'") else f"{art} {m.group(1)}"


def municipalities(scope: dict) -> list[str]:
    spec = scope["municipalities"]
    if isinstance(spec, list):
        return sorted(spec)
    doc = json.loads((INTERIM / "auf.json").read_text(encoding="utf-8"))["data"]
    for c in doc["cities"]:
        if c["id"] == spec["auf"]:
            return sorted(c["members"])
    raise KeyError(f"urban area {spec['auf']} not in data/interim/auf.json")


def district_name(scope: dict, cudis: str) -> str:
    """Official district name from the scope's table, else "Distrito N" (N without leading zero; cudis = 7 digits)."""
    return scope.get("districts", {}).get(cudis[:5], {}).get(cudis[5:], f"Distrito {cudis[5:].lstrip('0') or '0'}")


LABEL_MAX = 12
LABEL_OVERRIDES = {
    "Puente de Vallecas": "Pte. Vallecas", "Villa de Vallecas": "V. Vallecas", "Ciudad Lineal": "C. Lineal",  # Madrid
    "Casco Antiguo": "Casco Antiguo", "San Pablo-Santa Justa": "San Pablo", "Este-Alcosa-Torreblanca": "Este",
    "Bellavista-La Palmera": "Bellavista",  # Sevilla
}
_LABEL_SKIP = {"el", "la", "los", "las", "de", "del", "d", "l", "y", "i"}
_LABEL_PREFIX = {"san": "S.", "santa": "Sta.", "santo": "Sto.", "puerto": "Pto.", "ciudad": "C.", "puente": "Pte.", "villa": "V."}


def short_label(name: str) -> str:
    """Readable short label (<= 12 characters): the name itself when it fits, else the part before a hyphen or slash,
    else its significant words (articles dropped, a leading San/Santa/Puerto... abbreviated) that fit, else cut at 12."""
    name = name.strip()
    if name in LABEL_OVERRIDES:
        return LABEL_OVERRIDES[name]
    if len(name) <= LABEL_MAX:
        return name
    first = re.split(r"\s*[-/]\s*", name)[0].strip()
    if 0 < len(first) <= LABEL_MAX:
        return first
    parts = first.split()
    words = parts[:1] + [w for w in parts[1:] if w.lower() not in _LABEL_SKIP]
    if words and words[0].lower() in _LABEL_PREFIX and len(words) > 1:
        words[0] = _LABEL_PREFIX[words[0].lower()]
    out = ""
    for w in words:
        cand = f"{out} {w}".strip()
        if len(cand) > LABEL_MAX:
            break
        out = cand
    return out or first[:LABEL_MAX - 1] + "."


def district_abbr(scope: dict, cudis: str) -> str:
    """Short label: a named district's name (short_label), "D N" for a generic one."""
    names = scope.get("districts", {}).get(cudis[:5], {})
    if cudis[5:] in names:
        return short_label(names[cudis[5:]])
    return f"D {cudis[5:].lstrip('0') or '0'}"
