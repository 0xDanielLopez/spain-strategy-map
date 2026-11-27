"""F0 placeholders: no cities and no statistics yet, only the shapes the web app expects."""

from ..core.store import write_web

REQUIRES = ["_world"]
PRODUCES = ["cities.json", "nation.json"]


def build() -> None:
    write_web("cities.json", [])
    write_web(
        "nation.json",
        {
            "vintage": "Mapa base (sin estadísticas todavía)",
            "year": None,
            "gdp_vintage": None,
            "nation": {
                "name": "España", "population": None, "employed": None, "gdp": None,
                "yields": {}, "jobs": {}, "growth": None, "growth_years": None,
            },
            "yields": [],
            "industries": {},
        },
    )
