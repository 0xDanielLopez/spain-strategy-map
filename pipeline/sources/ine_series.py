"""INE municipal time series for the year slider of the national map (not part of the national catalog).

Streams the raw INE CSVs already cached by the `ine` source and keeps only municipal rows, per year:

    income            30824  Renta neta media por persona (euros of each year)
    adrh_pop, age, over65, under18, household, single_households   30832 (Atlas de renta, demographic indicators)
    pop               73027  Censo anual de población, 1 January of each year (2021-2026)

Output interim data/interim/ine_series.json (git-ignored):
    {"years": {field: [years, ascending]}, "municipalities": {ine: {field: {year: value}}}}
A missing value (secrecy mark, blank) is left out, never written as 0. Only municipal aggregates are kept.

Not auto-registered: the registry only discovers classes that carry `info` at class level, so sources.json does not
change. CLI:  uv run python -m pipeline.sources.ine_series
"""

from __future__ import annotations

import sys
import time

from ..core.paths import RAW
from ..core.store import save_interim
from .ine import municipal_code, parse_number

INCOME_FILE = RAW / "ine" / "30824.csv"
DEMOGRAPHICS_FILE = RAW / "ine" / "30832.csv"
POP_FILE = RAW / "ine" / "73027.csv"

INCOME_LABELS = {"Renta neta media por persona": "income"}
DEMOGRAPHIC_LABELS = {
    "Población": "adrh_pop",
    "Edad media de la población": "age",
    "Porcentaje de población de 65 y más años": "over65",
    "Porcentaje de población menor de 18 años": "under18",
    "Tamaño medio del hogar": "household",
    "Porcentaje de hogares unipersonales": "single_households",
}
FIELDS = ["income", "adrh_pop", "age", "over65", "under18", "household", "single_households", "pop"]


def _number(text: str):
    """Spanish number to int/float, None for blanks and secrecy marks (or anything unparseable)."""
    try:
        return parse_number(text)
    except ValueError:
        return None


def read_indicator_rows(lines, labels: dict, into: dict) -> int:
    """Municipal rows of an Atlas table (Municipios;Distritos;Secciones;Indicador;Periodo;Total) into
    into[code][field][year] = value. Rows with a district or a section are skipped. Returns the rows kept."""
    kept = 0
    for line in lines:
        parts = line.rstrip("\r\n").split(";")
        if len(parts) != 6 or parts[1] or parts[2]:
            continue
        field = labels.get(parts[3].strip().strip('"'))
        if field is None:
            continue
        code = municipal_code(parts[0].strip('"﻿'))
        if code is None:
            continue
        value = _number(parts[5])
        if value is not None:
            into.setdefault(code, {}).setdefault(field, {})[parts[4].strip()] = value
            kept += 1
    return kept


def read_population_rows(lines, into: dict) -> int:
    """Census table 73027 (Total Nacional;Municipios;Sexo;Periodo;Total): municipal rows, both sexes."""
    kept = 0
    for line in lines:
        parts = line.rstrip("\r\n").split(";")
        if len(parts) != 5 or parts[2].strip() != "Total":
            continue
        code = municipal_code(parts[1].strip('"'))
        value = _number(parts[4])
        if code is None or value is None:
            continue
        into.setdefault(code, {}).setdefault("pop", {})[parts[3].strip()] = value
        kept += 1
    return kept


def build_series(income_lines, demographics_lines, pop_lines) -> dict:
    munis: dict = {}
    read_indicator_rows(income_lines, INCOME_LABELS, munis)
    read_indicator_rows(demographics_lines, DEMOGRAPHIC_LABELS, munis)
    read_population_rows(pop_lines, munis)
    years = {f: sorted({y for m in munis.values() for y in m.get(f, {})}) for f in FIELDS}
    return {"years": years, "municipalities": munis}


def process() -> dict:
    with INCOME_FILE.open(encoding="utf-8-sig") as a, DEMOGRAPHICS_FILE.open(encoding="utf-8-sig") as b, \
            POP_FILE.open(encoding="utf-8-sig") as c:
        data = build_series(a, b, c)
    data["_files"] = ["ine/30824.csv", "ine/30832.csv", "ine/73027.csv"]
    data["vintage"] = "INE: Atlas de distribución de renta de los hogares y Censo anual de población"
    return data


if __name__ == "__main__":
    t = time.time()
    out = process()
    vintage = out.pop("vintage")
    save_interim("ine_series", out, vintage=vintage)
    print(f"ine_series: {len(out['municipalities'])} municipalities, years {out['years']} in {time.time() - t:.0f}s")
    sys.exit(0)
