"""INE municipal statistics: census population, household income atlas (ADRH) and education.

Every table is read from the bulk CSV the INE publishes per table, streamed row by row
(the national ADRH tables are hundreds of MB). Numbers use the Spanish format: "." for
thousands, "," for decimals, "." alone or "" for statistical secrecy.
"""

from __future__ import annotations

import csv
import re

from ..core.source import Source, SourceInfo

CSV_URL = "https://www.ine.es/jaxiT3/files/t/es/csv_bdsc/{id}.csv"
TABLE_URL = "https://www.ine.es/jaxiT3/Tabla.htm?t={id}"
MIN_PERIOD_SHARE = 0.95  # a period is pinned only if at least this share of municipalities has a value

POP_TABLE = "73027"
INCOME_TABLE = "30824"
RELATIVE_TABLE = "30829"
DEMOGRAPHIC_TABLE = "30832"
EDUCATION_TABLE = "66620"

TITLES = {
    POP_TABLE: "Censo anual de población: población por municipios y sexo",
    INCOME_TABLE: "Atlas de distribución de renta de los hogares: indicadores de renta media (municipios, distritos y secciones)",
    RELATIVE_TABLE: "Atlas de distribución de renta de los hogares: distribución de la renta por unidad de consumo, umbrales relativos, por sexo",
    DEMOGRAPHIC_TABLE: "Atlas de distribución de renta de los hogares: indicadores demográficos",
    EDUCATION_TABLE: "Censo: población de 15 y más años por nivel de estudios (municipios de 500 habitantes o más)",
}

ADRH_HEADER = ["Municipios", "Distritos", "Secciones"]
HEADERS = {
    POP_TABLE: ["Total Nacional", "Municipios", "Sexo", "Periodo", "Total"],
    INCOME_TABLE: ADRH_HEADER + ["Indicadores de renta media", "Periodo", "Total"],
    RELATIVE_TABLE: ADRH_HEADER + ["Sexo", "Distribución de la renta por unidad de consumo", "Periodo", "Total"],
    DEMOGRAPHIC_TABLE: ADRH_HEADER + ["Indicadores demográficos", "Periodo", "Total"],
    EDUCATION_TABLE: ["Municipios de 500 habitantes o más", "Sexo", "Edad", "Nivel de estudios", "Periodo", "Total"],
}

# field -> (table, indicator label, divisor)
INCOME_LABEL = "Renta neta media por persona"
BELOW60_LABEL = "Población con ingresos por unidad de consumo por debajo 60% de la mediana"
ADRH_FIELDS = {
    "income_pp": (INCOME_TABLE, INCOME_LABEL, 1),
    "below60": (RELATIVE_TABLE, BELOW60_LABEL, 100),
    "age_mean": (DEMOGRAPHIC_TABLE, "Edad media de la población", 1),
    "pct65": (DEMOGRAPHIC_TABLE, "Porcentaje de población de 65 y más años", 100),
    "pct_spanish": (DEMOGRAPHIC_TABLE, "Porcentaje de población española", 100),
    "hh_size": (DEMOGRAPHIC_TABLE, "Tamaño medio del hogar", 1),
}
INT_FIELDS = {"pop", "pop_2021", "pop15", "higher_ed"}
FIELDS = ["pop", "pop_2021", "income_pp", "below60", "age_mean", "pct65", "pct_spanish", "hh_size", "pop15", "higher_ed", "gini"]

CODE_RE = re.compile(r"^(\d{5})\s")


def parse_number(text: str):
    """Spanish-formatted number to int (no decimals) or float; secrecy marks and blanks to None."""
    t = (text or "").strip().strip('"').strip()
    if t in ("", ".", "..", "-", "x", "X"):
        return None
    if "," in t:
        return float(t.replace(".", "").replace(",", "."))
    return int(t.replace(".", ""))


def municipal_code(cell: str):
    """INE 5-digit code from a "28079 Madrid" cell, None for anything else (national, province, blank)."""
    m = CODE_RE.match((cell or "").strip())
    return m.group(1) if m else None


def check_header(table: str, header: list[str]) -> None:
    got = [h.lstrip("﻿").strip() for h in header]
    if got != HEADERS[table]:
        raise ValueError(f"INE table {table}: unexpected header {got!r}, expected {HEADERS[table]!r}")


def read_rows(path, table: str):
    """Yield the data rows of a bulk CSV (lists of cells) after validating the header."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f, delimiter=";")
        check_header(table, next(rd))
        yield from rd


def collect(rows, table: str, wanted: dict[str, str] | None = None):
    """Stream rows into {key: {code: {period: value}}} plus the set of municipal codes seen.

    Per table, `wanted` maps an indicator label to a key (ADRH tables: the label column, sex Total
    where there is a sex column). The pop and education tables are handled by their own functions.
    """
    out: dict[str, dict[str, dict[str, float | int | None]]] = {k: {} for k in (wanted or {}).values()}
    codes: set[str] = set()
    for r in rows:
        if len(r) != len(HEADERS[table]):
            continue
        code = municipal_code(r[0])
        if code is None:
            continue
        if r[1].strip() or r[2].strip():  # district or section row
            continue
        if table in (INCOME_TABLE, DEMOGRAPHIC_TABLE):
            label, period, value = r[3], r[4], r[5]
        elif table == RELATIVE_TABLE:
            if r[3].strip() != "Total":
                continue
            label, period, value = r[4], r[5], r[6]
        else:
            raise ValueError(table)
        codes.add(code)
        key = wanted.get(label.strip()) if wanted else None
        if key is None:
            continue
        out[key].setdefault(code, {})[period.strip()] = parse_number(value)
    return out, codes


def pin_period(by_code: dict[str, dict[str, object]], n_codes: int, min_share: float = MIN_PERIOD_SHARE):
    """Latest period with at least `min_share` of the `n_codes` municipalities non-null (else the best-covered one). Returns (period, {code: value})."""
    counts: dict[str, int] = {}
    for per in by_code.values():
        for p, v in per.items():
            if v is not None:
                counts[p] = counts.get(p, 0) + 1
    if not counts:
        raise ValueError("no non-null values in any period")
    ok = [p for p, n in counts.items() if n >= min_share * n_codes]
    # Some indicators are secret for small municipalities in every period: then the best-covered period (latest on ties).
    period = max(ok) if ok else max(counts, key=lambda p: (counts[p], p))
    return period, {c: per[period] for c, per in by_code.items() if per.get(period) is not None}


def parse_population(rows) -> dict[str, dict[str, int]]:
    """Census population: {code: {period: total both sexes}} for municipal rows."""
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        if len(r) != 5 or r[2].strip() != "Total":
            continue
        code = municipal_code(r[1])
        if code is None:
            continue
        out.setdefault(code, {})[r[3].strip()] = parse_number(r[4])
    return out


def parse_education(rows) -> dict[str, dict[str, dict[str, int | None]]]:
    """Education: {code: {period: {"pop15": total, "higher_ed": superior}}}; sex Total, age "15 y más años"."""
    out: dict[str, dict[str, dict[str, int | None]]] = {}
    for r in rows:
        if len(r) != 6 or r[1].strip() != "Total" or r[2].strip() != "15 y más años":
            continue
        level = r[3].strip()
        key = {"Total": "pop15", "Educación superior": "higher_ed"}.get(level)
        code = municipal_code(r[0])
        if key is None or code is None:
            continue
        out.setdefault(code, {}).setdefault(r[4].strip(), {})[key] = parse_number(r[5])
    return out


def pin_latest(by_code: dict[str, dict[str, dict]], key: str):
    """Latest period in which any municipality has `key`. Returns (period, {code: value})."""
    periods = {p for per in by_code.values() for p, d in per.items() if d.get(key) is not None}
    if not periods:
        raise ValueError(f"no values for {key}")
    period = max(periods)
    return period, {c: per[period][key] for c, per in by_code.items() if per.get(period, {}).get(key) is not None}


def coverage(munis: dict[str, dict], fields=FIELDS) -> dict:
    total = sum(m["pop"] for m in munis.values() if m.get("pop"))
    out = {}
    for f in fields:
        have = [m for m in munis.values() if m.get(f) is not None]
        pop = sum(m["pop"] for m in have if m.get("pop"))
        out[f] = {"municipalities": len(have), "population_share": round(pop / total, 4) if total else 0.0}
    return out


class Ine(Source):
    info = SourceInfo(
        id="ine",
        title="INE: padrón, censo anual y Atlas de renta de los hogares",
        publisher="Instituto Nacional de Estadística (INE)",
        homepage="https://www.ine.es",
        license="Reutilización permitida, también comercial, citando la fuente. Elaboración propia con datos extraídos del "
        "sitio web del INE: www.ine.es. El INE no participa, patrocina ni apoya esta reutilización.",
        description="Datos municipales del INE: población del Censo anual (2021 y la última cifra), Atlas de distribución "
        "de renta de los hogares (renta neta por persona, población bajo el 60 % de la mediana, edad media, mayores de 65, "
        "población española, tamaño del hogar) y nivel de estudios del Censo (municipios de 500 habitantes o más).",
        used_for=["Mapa: capas de población, renta, edad y estudios", "Búsqueda de municipios", "Ficha de cada municipio"],
    )
    tables = [POP_TABLE, INCOME_TABLE, RELATIVE_TABLE, DEMOGRAPHIC_TABLE, EDUCATION_TABLE]

    def fetch(self, force=False):
        for t in self.tables:
            self.download(CSV_URL.format(id=t), f"{t}.csv", force=force, expect_binary=False)

    def process(self):
        path = lambda t: self.raw_dir / f"{t}.csv"  # noqa: E731
        munis: dict[str, dict] = {}
        periods: dict[str, str] = {}

        def put(field, code, value):
            munis.setdefault(code, {f: None for f in FIELDS})[field] = value

        pop = parse_population(read_rows(path(POP_TABLE), POP_TABLE))
        pop_codes = len(pop)
        by_code = {c: {p: v for p, v in per.items()} for c, per in pop.items()}
        periods["pop"], latest = pin_period(by_code, pop_codes)
        for c, v in latest.items():
            put("pop", c, int(v))
        periods["pop_2021"] = "2021"
        for c, per in pop.items():
            if per.get("2021") is not None:
                put("pop_2021", c, int(per["2021"]))

        for table in (INCOME_TABLE, RELATIVE_TABLE, DEMOGRAPHIC_TABLE):
            wanted = {lab: f for f, (t, lab, _) in ADRH_FIELDS.items() if t == table}
            data, codes = collect(read_rows(path(table), table), table, wanted)
            for field, by in data.items():
                div = ADRH_FIELDS[field][2]
                period, vals = pin_period(by, len(codes))
                periods[field] = period
                for c, v in vals.items():
                    put(field, c, round(float(v) / div, 6))

        edu = parse_education(read_rows(path(EDUCATION_TABLE), EDUCATION_TABLE))
        for field in ("pop15", "higher_ed"):
            periods[field], vals = pin_latest(edu, field)
            for c, v in vals.items():
                put(field, c, int(v))

        for f in INT_FIELDS:  # sanity: ints stay ints
            for m in munis.values():
                if m[f] is not None:
                    m[f] = int(m[f])
        if len(munis) < 8000:
            raise ValueError(f"only {len(munis)} municipalities with INE data (expected about 8,100)")

        def per_of(*fields):
            ps = sorted({periods[f] for f in fields})
            return ", ".join(ps)

        tables = {
            POP_TABLE: per_of("pop", "pop_2021"),
            INCOME_TABLE: per_of("income_pp"),
            RELATIVE_TABLE: per_of("below60"),
            DEMOGRAPHIC_TABLE: per_of("age_mean", "pct65", "pct_spanish", "hh_size"),
            EDUCATION_TABLE: per_of("pop15", "higher_ed"),
        }
        return {
            "vintage": f"INE: Censo anual de población {periods['pop']}, Atlas de distribución de renta de los hogares "
            f"{periods['income_pp']}, Censo {periods['pop15']} (estudios)",
            "_files": [f"{t}.csv" for t in self.tables],
            "tables": {t: {"title": TITLES[t], "period": p, "url": TABLE_URL.format(id=t)} for t, p in tables.items()},
            "periods": periods,
            "municipalities": dict(sorted(munis.items())),
            "coverage": coverage(munis),
        }
