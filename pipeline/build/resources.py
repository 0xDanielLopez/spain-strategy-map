"""Recursos del mapa: centrales nucleares, hidroeléctricas y de gas (WRI GPPD, edición 2021).

Solo se dibujan tres tipos. Carbón y petróleo quedan fuera porque la mayoría de esas centrales ya han cerrado; el
eólico y el solar, porque el inventario de 2021 está muy incompleto. Todas las centrales cuentan (sin umbral de
capacidad); el mapa muestra un icono por casilla. Cada punto se proyecta con MapProjection (Canarias en su recuadro).

El `Locator` (lon/lat -> x, y, casilla de tierra española, comunidad, municipio y área urbana) también lo usa wonders.py.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from ..core.geo import MapProjection, Shape, ShapeIndex
from ..core.hexgrid import HexGrid
from ..core.paths import WEB_DATA
from ..core.store import load_interim, load_interim_payload, write_web
from ..sources._spain import CCAA

REQUIRES = ["_world", "gisco_lau", "gppd", "cities.json"]
PRODUCES = ["resources.json"]

RINGS = 2  # una casilla sin tierra española se ajusta a la más cercana hasta a 2 hexágonos
ISO_OF = {c["code"]: c["iso"] for c in CCAA}
VINTAGE = "inventario histórico de 2021 (WRI GPPD, edición 2021)"
ATTRIBUTION = [{
    "data": "centrales nucleares, hidroeléctricas y de gas de España (inventario de 2021)",
    "source": "World Resources Institute, Global Power Plant Database v1.3",
    "license": "CC BY 4.0",
}]
NOTE = (f"Totales de las centrales representadas, según el {VINTAGE}: no son la capacidad de España. "
        "Las centrales de carbón y petróleo no se dibujan porque la mayoría ha cerrado desde entonces, y las de energía "
        "eólica y solar tampoco porque el inventario de 2021 está muy incompleto. El mapa muestra un icono por casilla.")


def _t(id, name, emoji, color, what):
    return {"id": id, "name": name, "category": "energy", "emoji": emoji, "icon": f"r-{id}", "color": color,
            "unit": "MW", "source": "gppd", "as_of": "inventario de 2021",
            "description": f"{what} Es el {VINTAGE}. El valor es la capacidad instalada de la central en MW. "
                           "Entran todas las centrales de España con ese combustible principal, sin umbral de capacidad."}


TYPES = [
    _t("nuclear", "Central nuclear", "☢️", "#e8d44d", "Centrales con combustible principal nuclear."),
    _t("hydro", "Central hidroeléctrica", "💧", "#3fa7d6", "Centrales con combustible principal hidráulico."),
    _t("gas", "Central de gas", "🔥", "#f08a24", "Centrales con combustible principal gas natural."),
]
FUEL_TYPE = {"Nuclear": "nuclear", "Hydro": "hydro", "Gas": "gas"}
LOWER = {"de", "del", "la", "las", "los", "el", "y", "en", "i", "a"}


def tidy_name(name: str) -> str:
    """'ASCO GR' -> 'Asco Gr'; a name already in mixed case is left as it is."""
    name = " ".join((name or "").split())
    if not name.isupper():
        return name
    words = name.lower().split(" ")
    return " ".join(w if (k and w in LOWER) else w[:1].upper() + w[1:] for k, w in enumerate(words))


class Locator:
    """lon/lat -> (x, y, casilla de tierra española) y x/y -> comunidad (abreviatura), municipio y área urbana."""

    def __init__(self, world: dict, munis: list[dict], cities: list[dict]):
        self.world = world
        self.proj = MapProjection(**world["projection"])
        self.grid = HexGrid(**world["grid"])
        self.owner = world["owner"]
        self.abbrs = [ISO_OF[c] for c in world["states"]]
        self.codes = [m["code"] for m in munis]
        self.muni_abbr = {m["code"]: ISO_OF[m["ccaa"]] for m in munis}
        self.index = ShapeIndex([Shape([self.proj.project_ring(r) for r in m["rings"]]) for m in munis], 30)
        self.city_of = {}
        for c in cities:
            for code in c["counties"]:
                self.city_of.setdefault(code, c["id"])

    def land_cell(self, x: float, y: float, rings: int = RINGS) -> int:
        """La casilla de tierra española en x/y, si no la más cercana hasta `rings` hexágonos, sin cruzar el recuadro
        de un inset; -1 si no hay ninguna."""
        cell = self.grid.cell_at(x, y)
        if cell < 0:
            return -1
        frame = self.proj.frame_at(x, y)
        if self.owner[cell] >= 0:
            return cell
        seen, frontier = {cell}, [cell]
        for _ in range(rings):
            ring = [n for c in frontier for n in self.grid.neighbours(c) if n not in seen]
            seen.update(ring)
            land = [n for n in ring
                    if self.owner[n] >= 0 and self.proj.frame_at(*self.grid.center(*self.grid.col_row(n))) == frame]
            if land:
                return min(land, key=lambda n: (self.grid.center(*self.grid.col_row(n))[0] - x) ** 2
                           + (self.grid.center(*self.grid.col_row(n))[1] - y) ** 2)
            frontier = ring
        return -1

    def place(self, lon: float, lat: float):
        """Un sitio en el mapa: dict con x, y, cell, state, county (municipio INE) y cbsa, o None si el punto queda
        oculto bajo un recuadro o sin tierra española a 2 hexágonos."""
        if self.proj.hidden(lon, lat):
            return None
        x, y = self.proj(lon, lat)
        cell = self.land_cell(x, y)
        if cell < 0:
            return None
        k = self.index.locate(x, y)
        county = self.codes[k] if k >= 0 else None
        if county is None:  # fuera de los polígonos (costa): el municipio representativo de la casilla
            m = self.world["county"][cell]
            county = self.codes[m] if m >= 0 else None
        state = self.muni_abbr[county] if county else self.abbrs[self.owner[cell]]
        x, y = round(x, 1), round(y, 1)
        if self.grid.cell_at(x, y) != cell:  # punto ajustado desde el mar: el centro de su casilla
            x, y = (round(v, 1) for v in self.grid.center(*self.grid.col_row(cell)))
        return {"x": x, "y": y, "cell": cell, "state": state, "county": county, "cbsa": self.city_of.get(county)}


def load_locator() -> Locator:
    cities = json.loads((WEB_DATA / "cities.json").read_text(encoding="utf-8"))
    return Locator(load_interim("_world"), load_interim("gisco_lau")["municipalities"], cities)


def build_items(plants: list[dict], place) -> tuple[list[dict], list[str]]:
    """Centrales de los tres combustibles -> items; `place(lon, lat)` devuelve la posición o None. Devuelve también los
    nombres de las centrales descartadas por no tener casilla."""
    items, dropped = [], []
    for p in plants:
        t = FUEL_TYPE.get(p["fuel"])
        if t is None:
            continue
        pos = place(p["lon"], p["lat"])
        if pos is None:
            dropped.append(p["name"])
            continue
        detail = (f"Puesta en servicio en {p['year']}." if p.get("year")
                  else "El inventario no indica el año de puesta en servicio.")
        items.append({"type": t, "name": tidy_name(p["name"]), "x": pos["x"], "y": pos["y"], "cell": pos["cell"],
                      "value": p["capacity_mw"], "detail": detail, "state": pos["state"], "cbsa": pos["cbsa"]})
    items.sort(key=lambda i: (i["type"], -(i["value"] or 0), i["name"]))
    return items, dropped


def summarise(items: list[dict]) -> dict:
    def cell(its, t):
        vals = [i["value"] for i in its if i["value"] is not None]
        return {"count": len(its), "value": round(sum(vals), 1) if vals else None, "unit": "MW"}

    by = defaultdict(lambda: defaultdict(list))
    for i in items:
        by[i["state"]][i["type"]].append(i)
    national = {t["id"]: cell([i for i in items if i["type"] == t["id"]], t["id"]) for t in TYPES}
    states = {s: {t["id"]: cell(by[s][t["id"]], t["id"]) for t in TYPES if by[s][t["id"]]} for s in sorted(by)}
    return {"note": NOTE, "national": national, "states": states}


def build() -> None:
    loc = load_locator()
    payload = load_interim_payload("gppd")
    items, dropped = build_items(payload["data"]["plants"], loc.place)
    doc = {"vintage": VINTAGE, "attribution": ATTRIBUTION, "note": NOTE, "types": TYPES, "items": items,
           "summary": summarise(items)}
    write_web("resources.json", doc)
    for t, v in doc["summary"]["national"].items():
        print(f"    {t}: {v['count']} centrales, {v['value']} MW")
    print(f"    {len(dropped)} centrales sin casilla a {RINGS} hexágonos: {dropped}")


def check(web_dir) -> list[tuple[str, str]]:
    path = Path(web_dir) / "resources.json"
    if not path.exists():
        return [("NOTE", "resources.json no construido (opcional)")]
    d = json.loads(path.read_text(encoding="utf-8"))
    ids = {t["id"] for t in d.get("types") or []}
    bad = [f"item {i.get('name')!r}: tipo o casilla no válidos" for i in d.get("items") or []
           if i.get("type") not in ids or not isinstance(i.get("cell"), int)
           or (i.get("value") is not None and not i["value"] > 0)]
    if not d.get("attribution"):
        bad.append("falta attribution")
    out = [("FAIL", f"resources.json: {m}") for m in bad[:12]]
    if not bad:
        out.append(("PASS", f"resources.json: {len(d['items'])} centrales"))
    return out
