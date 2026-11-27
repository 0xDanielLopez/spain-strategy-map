"""Year series of five lenses, for the year slider of the national map: web/data/lens_series.json.

Same method as lenses.py (it reuses its terms, hex_ratio, hex_density, rounding and percentile domain): every
municipality is spread over the hexes by area (`muni_weights`), a hex value is a ratio of weighted sums, and a hex is null
when the municipalities with a value hold less than COVERAGE_MIN of its population. Per year, the weight of the Atlas
lenses (income, age, elderly, household) is the Atlas population of THAT year (`adrh_pop`); density uses the census
population of that year (73027). Income is in euros of each year, not adjusted for inflation.

Format: see docs/DATA_CONTRACTS.md "lens_series.json". Dense (one value per hex of lenses.json) when it fits in
MAX_BYTES, else only the hexes that have a value in some lens (top-level "index").

Reads the interim ine_series, which is NOT a registered source: make it with `uv run python -m pipeline.sources.ine_series`.
"""

from __future__ import annotations

import json

from ..core.store import load_interim, load_interim_payload, write_web
from .lenses import INE_LENSES, hex_density, hex_ratio, percentile_domain, round_to

REQUIRES = ["_world", "ine_series"]
PRODUCES = ["lens_series.json"]

MAX_BYTES = 1_500_000

# lens id (same as in lenses.json) -> the municipal fields it needs, mapped to the record keys lenses.py reads.
# (series field, record key, divisor); "pop" is always the weight of the year.
ATLAS_LENSES = {
    "income": [("income", "income_pp", 1)],
    "age": [("age", "age_mean", 1)],
    "elderly": [("over65", "pct65", 100)],
    "household": [("household", "hh_size", 1)],
}

NOTE = ("La renta está en euros de cada año, sin ajustar por inflación. Cada municipio se reparte entre sus "
        "hexágonos por superficie, igual que en el mapa de capas.")


def year_records(munis: list[dict], year: str, fields: list[tuple]) -> list[dict]:
    """One record per municipality for `year`: pop = Atlas population of the year, plus the lens fields.
    A missing value stays absent (None), never 0."""
    out = []
    for m in munis:
        rec = {"pop": (m.get("adrh_pop") or {}).get(year)}
        for series_field, key, div in fields:
            v = (m.get(series_field) or {}).get(year)
            rec[key] = None if v is None else v / div
        out.append(rec)
    return out


def compact(lenses: list[dict], land: list[int]) -> dict:
    """Same lenses restricted to the hex indices `land` (values arrays aligned with that index)."""
    return {"index": land, "lenses": [{**l, "values": [[row[i] for i in land] for row in l["values"]]} for l in lenses]}


def mean_income(munis: list[dict], year: str) -> float | None:
    num = den = 0.0
    for m in munis:
        v, p = (m.get("income") or {}).get(year), (m.get("adrh_pop") or {}).get(year)
        if v is not None and p:
            num += v * p
            den += p
    return num / den if den else None


def build() -> None:
    world = load_interim("_world")
    series = load_interim("ine_series")
    weights, owner, land_km2, codes = world["muni_weights"], world["owner"], world["land_km2"], world["counties"]
    n = len(owner)
    by_code = series["municipalities"]
    munis = [by_code.get(c) or {} for c in codes]
    lenses = []

    for lid, fields in ATLAS_LENSES.items():
        terms, meta = INE_LENSES[lid]
        years = [y for y in series["years"][fields[0][0]] if y in series["years"]["adrh_pop"]]
        rows = []
        for y in years:
            recs = year_records(munis, y, fields)
            rows.append([None if owner[i] < 0 or not parts else round_to(hex_ratio(parts, recs, terms), meta["digits"])
                         for i, parts in enumerate(weights)])
        lenses.append({"id": lid, "years": [int(y) for y in years], "values": rows,
                       "domain": percentile_domain([v for r in rows for v in r], False)})

    years = series["years"]["pop"]
    rows = []
    for y in years:
        recs = [{"pop": (m.get("pop") or {}).get(y)} for m in munis]
        rows.append([None if owner[i] < 0 or not parts else (None if (d := hex_density(parts, recs, land_km2[i])) is None else round(d, 1))
                     for i, parts in enumerate(weights)])
    lenses.append({"id": "density", "years": [int(y) for y in years], "values": rows,
                   "domain": percentile_domain([v for r in rows for v in r], True)})

    doc = {"vintage": load_interim_payload("ine_series")["vintage"], "note": NOTE, "hexes": n, "lenses": lenses}
    size = len(json.dumps(doc, separators=(",", ":")))
    if size > MAX_BYTES:
        land = [i for i in range(n) if any(row[i] is not None for l in lenses for row in l["values"])]
        doc = {**doc, **compact(lenses, land)}
        print(f"    {size / 1e3:.0f} kB dense > {MAX_BYTES / 1e3:.0f} kB: index of {len(land)} hexes")
    write_web("lens_series.json", doc)
    for l in lenses:
        print(f"    {l['id']:10} years {l['years'][0]}-{l['years'][-1]} domain {l['domain']}")
    for y in series["years"]["income"]:
        print(f"    mean income {y}: {mean_income(munis, y):,.0f} EUR")
