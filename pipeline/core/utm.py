"""Transverse Mercator (UTM) on GRS80 with the Krueger series, accurate to well under 1 m.

ETRS89 / UTM zone 30N (the grid of the INE census-section boundaries) is the default:
central meridian -3 degrees, scale 0.9996, false easting 500000 m.
ETRS89 and WGS84 agree to about 1 m, so the degrees returned here can be used as WGS84.
"""

from __future__ import annotations

import math

A_GRS80 = 6378137.0
F_GRS80 = 1 / 298.257222101
K0 = 0.9996
E0 = 500000.0
LON0_ZONE30 = -3.0

_n = F_GRS80 / (2 - F_GRS80)
_e = math.sqrt(F_GRS80 * (2 - F_GRS80))
_A = A_GRS80 / (1 + _n) * (1 + _n**2 / 4 + _n**4 / 64)
_ALPHA = (
    _n / 2 - 2 * _n**2 / 3 + 5 * _n**3 / 16 + 41 * _n**4 / 180,
    13 * _n**2 / 48 - 3 * _n**3 / 5 + 557 * _n**4 / 1440,
    61 * _n**3 / 240 - 103 * _n**4 / 140,
    49561 * _n**4 / 161280,
)
_BETA = (
    _n / 2 - 2 * _n**2 / 3 + 37 * _n**3 / 96 - _n**4 / 360,
    _n**2 / 48 + _n**3 / 15 - 437 * _n**4 / 1440,
    17 * _n**3 / 480 - 37 * _n**4 / 840,
    4397 * _n**4 / 161280,
)
_DELTA = (
    2 * _n - 2 * _n**2 / 3 - 2 * _n**3 + 116 * _n**4 / 45,
    7 * _n**2 / 3 - 8 * _n**3 / 5 - 227 * _n**4 / 45,
    56 * _n**3 / 15 - 136 * _n**4 / 35,
    4279 * _n**4 / 630,
)


def utm_to_lonlat(easting: float, northing: float, lon0: float = LON0_ZONE30) -> tuple[float, float]:
    """(E, N) metres in the northern hemisphere -> (lon, lat) degrees."""
    xi = northing / (K0 * _A)
    eta = (easting - E0) / (K0 * _A)
    xi_p = xi - sum(b * math.sin(2 * j * xi) * math.cosh(2 * j * eta) for j, b in enumerate(_BETA, 1))
    eta_p = eta - sum(b * math.cos(2 * j * xi) * math.sinh(2 * j * eta) for j, b in enumerate(_BETA, 1))
    chi = math.asin(math.sin(xi_p) / math.cosh(eta_p))
    lat = chi + sum(d * math.sin(2 * j * chi) for j, d in enumerate(_DELTA, 1))
    lon = math.radians(lon0) + math.atan2(math.sinh(eta_p), math.cos(xi_p))
    return math.degrees(lon), math.degrees(lat)


def lonlat_to_utm(lon: float, lat: float, lon0: float = LON0_ZONE30) -> tuple[float, float]:
    """(lon, lat) degrees -> (E, N) metres in the northern hemisphere."""
    phi = math.radians(lat)
    dlam = math.radians(lon - lon0)
    s = math.sin(phi)
    t = math.sinh(math.atanh(s) - _e * math.atanh(_e * s))
    xi_p = math.atan2(t, math.cos(dlam))
    eta_p = math.atanh(math.sin(dlam) / math.sqrt(1 + t * t))
    easting = E0 + K0 * _A * (eta_p + sum(a * math.cos(2 * j * xi_p) * math.sinh(2 * j * eta_p) for j, a in enumerate(_ALPHA, 1)))
    northing = K0 * _A * (xi_p + sum(a * math.sin(2 * j * xi_p) * math.cosh(2 * j * eta_p) for j, a in enumerate(_ALPHA, 1)))
    return easting, northing
