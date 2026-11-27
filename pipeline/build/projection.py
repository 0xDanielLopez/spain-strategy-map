"""Projection constants for the browser: everything web/js/geo/projection.js needs to turn lon/lat into map km.

Writes web/data/projection.json from the _world interim (min_x, max_y, margin) and pipeline/core/geo.py (main Albers
parameters and the Canarias inset: box, own Albers, frame and the fixed translation). Used by the live layers.
Format: docs/DATA_CONTRACTS.md "Live layers".
"""

from __future__ import annotations

from ..core.geo import INSETS, MAIN_ALBERS, R_EARTH_KM, MapProjection
from ..core.store import load_interim, write_web

REQUIRES = ["_world"]
PRODUCES = ["projection.json"]


def make_doc(proj: dict) -> dict:
    p = MapProjection(proj["min_x"], proj["max_y"], proj["margin"])
    return {
        "r_earth_km": R_EARTH_KM,
        "min_x": p.min_x,
        "max_y": p.max_y,
        "margin": p.margin,
        "main_albers": list(MAIN_ALBERS),  # lat1, lat2, lat0, lon0
        "insets": [
            {
                "name": i.name,
                "box": list(i.box),  # lon0, lat0, lon1, lat1
                "albers": list(i.albers),  # lat1, lat2, lat0, lon0
                "frame": list(i.frame),  # x0, y0, x1, y1 in main-Albers km, y up
                "tx": i.tx,
                "ty": i.ty,
            }
            for i in p.insets
        ],
    }


def build() -> None:
    world = load_interim("_world")
    write_web("projection.json", make_doc(world["projection"]))
