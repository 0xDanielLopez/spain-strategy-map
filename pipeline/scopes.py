"""City scopes: the same map at city scale (docs/DATA_CONTRACTS.md "City scopes").

Adding a city is one entry in SCOPES. Two scopes of the same city can coexist (the municipality and its functional
urban area). A scope is plain data:

  id          URL id (?scope=<id>) and folder web/data/city/<id>/
  name, title short name and the title shown on the page
  kind        "municipality" | "urban_area"
  city        INE functional urban area id (data/interim/auf.json) the scope belongs to
  hex_km      hex radius in km
  municipalities  list of INE codes, or {"auf": <city id>} to take the members of that urban area
  state_level "district" (states = census districts, CUDIS) | "municipality" (states = municipalities, CUMUN)
  districts   {CUDIS suffix "NN": official name} for state_level "district"; others fall back to "Distrito NN"
  min_banner  banners (cities.json): urban areas only list municipalities with at least this many inhabitants
"""

from __future__ import annotations

import json
import re

from .core.paths import INTERIM

MADRID_DISTRICTS = {
    "01": "Centro", "02": "Arganzuela", "03": "Retiro", "04": "Salamanca", "05": "Chamartín", "06": "Tetuán",
    "07": "Chamberí", "08": "Fuencarral-El Pardo", "09": "Moncloa-Aravaca", "10": "Latina", "11": "Carabanchel",
    "12": "Usera", "13": "Puente de Vallecas", "14": "Moratalaz", "15": "Ciudad Lineal", "16": "Hortaleza",
    "17": "Villaverde", "18": "Villa de Vallecas", "19": "Vicálvaro", "20": "San Blas-Canillejas", "21": "Barajas",
}

SCOPES: dict[str, dict] = {
    "madrid": {
        "id": "madrid", "name": "Madrid", "title": "Madrid", "kind": "municipality", "city": "ES001F", "hex_km": 0.3,
        "municipalities": ["28079"], "state_level": "district", "districts": {"28079": MADRID_DISTRICTS},
    },
    "madrid-auf": {
        "id": "madrid-auf", "name": "Madrid", "title": "Área urbana de Madrid", "kind": "urban_area", "city": "ES001F",
        "hex_km": 1.2, "municipalities": {"auf": "ES001F"}, "state_level": "municipality", "min_banner": 50_000,
    },
}

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
    """Official district name from the scope's table, else a generic "Distrito NN" (cudis = 7 digits)."""
    return scope.get("districts", {}).get(cudis[:5], {}).get(cudis[5:], f"Distrito {cudis[5:]}")
