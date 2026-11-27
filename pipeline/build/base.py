"""F0 placeholders: no cities and no statistics yet, only the shapes the web app expects (plus the national population once INE data exists)."""

from ..core.store import load_interim, write_web

REQUIRES = ["_world"]
PRODUCES = ["cities.json", "nation.json"]


def national_population() -> int | None:
    """Sum of the municipal populations (INE annual census) when the "ine" interim exists, else None (F0 mode).

    "ine" is read optionally, so it is not in REQUIRES: the base builds without it."""
    try:
        ine = load_interim("ine")
    except FileNotFoundError:
        return None
    return int(sum(r["pop"] for r in ine["municipalities"].values() if r.get("pop") is not None))


def build() -> None:
    population = national_population()
    write_web("cities.json", [])
    write_web(
        "nation.json",
        {
            "vintage": "Mapa base (sin estadísticas todavía)" if population is None else "Censo anual de población del INE, 1 de enero de 2026",
            "year": None,
            "gdp_vintage": None,
            "nation": {
                "name": "España", "population": population, "employed": None, "gdp": None,
                "yields": {}, "jobs": {}, "growth": None, "growth_years": None,
            },
            "yields": [],
            "industries": {},
        },
    )
