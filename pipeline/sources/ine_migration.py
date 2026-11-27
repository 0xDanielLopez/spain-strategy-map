"""INE municipal migration: foreign nationals and foreign-born population (annual Census, 2021-2026)
and immigrations from abroad (migration statistics, 2021-2024).

The two census tables are national files of about 250 MB with every census section: they are
streamed row by row and only municipal totals (Sexo Total, no section) are kept.
"""

from __future__ import annotations

import csv

from ..core.source import Source, SourceInfo
from .ine import municipal_code, parse_number

NATIONALITY_TABLE = "65032"
BIRTH_TABLE = "65031"
IMMIGRATION_TABLE = "69696"
CSV_URL = "https://www.ine.es/jaxiT3/files/t/es/csv_bdsc/{id}.csv"
TABLE_URL = "https://www.ine.es/jaxiT3/Tabla.htm?t={id}"

HEADERS = {
    NATIONALITY_TABLE: ["Total Nacional", "Provincias", "Municipios", "Secciones", "Sexo", "Nacionalidad", "Periodo", "Total"],
    BIRTH_TABLE: ["Total Nacional", "Provincias", "Municipios", "Secciones", "Sexo", "Lugar de nacimiento", "Periodo", "Total"],
    IMMIGRATION_TABLE: ["Total Nacional", "Provincias", "Municipios", "Sexo", "Periodo", "Total"],
}
TITLES = {
    NATIONALITY_TABLE: "Censo anual de población: población por nacionalidad (española, extranjera), municipios y secciones",
    BIRTH_TABLE: "Censo anual de población: población por lugar de nacimiento (España, extranjero), municipios y secciones",
    IMMIGRATION_TABLE: "Estadística de migraciones: inmigraciones procedentes del extranjero por municipios",
}
FIELDS = ["total", "foreign", "born_abroad", "immigrations_abroad"]
NATIONALITY_KEYS = {"Total": "total", "Extranjera": "foreign"}
BIRTH_KEYS = {"Extranjero": "born_abroad"}


def read_rows(path, table: str):
    """Stream the rows of a bulk CSV after validating the header."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f, delimiter=";")
        got = [h.strip() for h in next(rd)]
        if got != HEADERS[table]:
            raise ValueError(f"INE table {table}: unexpected header {got!r}, expected {HEADERS[table]!r}")
        yield from rd


def parse_census(rows, table: str, keys: dict[str, str]):
    """Census rows (8 cells, with sections) -> ({code: {field: {year: value|None}}}, {field: {year: national}}).

    Keeps sex Total and municipal rows without section; the national row (all geography cells empty) is kept apart.
    """
    munis: dict[str, dict[str, dict[str, int | None]]] = {}
    national: dict[str, dict[str, int | None]] = {}
    for r in rows:
        if len(r) != 8 or r[4].strip() != "Total":
            continue
        field = keys.get(r[5].strip())
        if field is None:
            continue
        year, value = r[6].strip(), parse_number(r[7])
        if not (r[1].strip() or r[2].strip() or r[3].strip()):
            national.setdefault(field, {})[year] = value
            continue
        if r[3].strip():  # census section row
            continue
        code = municipal_code(r[2])
        if code is not None:
            munis.setdefault(code, {}).setdefault(field, {})[year] = value
    return munis, national


def parse_immigrations(rows):
    """Immigrations from abroad, both sexes: ({code: {year: value|None}}, {year: national})."""
    munis: dict[str, dict[str, int | None]] = {}
    national: dict[str, int | None] = {}
    for r in rows:
        if len(r) != 6 or r[3].strip() != "Ambos sexos":
            continue
        year, value = r[4].strip(), parse_number(r[5])
        if not (r[1].strip() or r[2].strip()):
            national[year] = value
            continue
        code = municipal_code(r[2])
        if code is not None:
            munis.setdefault(code, {})[year] = value
    return munis, national


def merge(nat_c, birth_c, imm) -> dict[str, dict[str, dict[str, int | None]]]:
    """{code: {field: {year: value}}} with every field present (empty dict when the code has no data)."""
    out: dict[str, dict[str, dict]] = {}
    for src in (nat_c, birth_c):
        for code, d in src.items():
            for f, per in d.items():
                out.setdefault(code, {k: {} for k in FIELDS})[f] = dict(per)
    for code, per in imm.items():
        out.setdefault(code, {k: {} for k in FIELDS})["immigrations_abroad"] = dict(per)
    for row in out.values():
        for k in FIELDS:
            row.setdefault(k, {})
    return out


def coverage(munis: dict[str, dict], fields=FIELDS) -> dict:
    """Per field and year: municipalities with a value and secrets (present but None)."""
    out: dict[str, dict] = {}
    for f in fields:
        years = sorted({y for m in munis.values() for y in m.get(f, {})})
        out[f] = {
            y: {
                "municipalities": sum(1 for m in munis.values() if m.get(f, {}).get(y) is not None),
                "secret": sum(1 for m in munis.values() if y in m.get(f, {}) and m[f][y] is None),
            }
            for y in years
        }
    return out


def national_sums(munis: dict[str, dict], fields=FIELDS) -> dict:
    return {f: {y: sum(m[f][y] for m in munis.values() if m.get(f, {}).get(y) is not None)
                for y in sorted({y for m in munis.values() for y in m.get(f, {})})} for f in fields}


class IneMigration(Source):
    info = SourceInfo(
        id="ine_migration",
        title="INE: extranjeros, nacidos en el extranjero e inmigración por municipio",
        publisher="Instituto Nacional de Estadística (INE)",
        homepage="https://www.ine.es",
        license="Reutilización permitida, también comercial, citando la fuente. Elaboración propia con datos extraídos del "
        "sitio web del INE: www.ine.es. El INE no participa, patrocina ni apoya esta reutilización.",
        description="Población por nacionalidad y por lugar de nacimiento del Censo anual (2021-2026) e inmigraciones "
        "procedentes del extranjero (2021-2024), por municipio. Solo totales municipales, sin secciones censales.",
        used_for=["Mapa: población extranjera, nacidos fuera y llegadas", "Ficha de cada municipio"],
    )
    tables = [NATIONALITY_TABLE, BIRTH_TABLE, IMMIGRATION_TABLE]

    def fetch(self, force=False):
        for t in self.tables:
            self.download(CSV_URL.format(id=t), f"{t}.csv", force=force, expect_binary=False)

    def process(self):
        p = lambda t: self.raw_dir / f"{t}.csv"  # noqa: E731
        nat, nat_nat = parse_census(read_rows(p(NATIONALITY_TABLE), NATIONALITY_TABLE), NATIONALITY_TABLE, NATIONALITY_KEYS)
        birth, birth_nat = parse_census(read_rows(p(BIRTH_TABLE), BIRTH_TABLE), BIRTH_TABLE, BIRTH_KEYS)
        imm, imm_nat = parse_immigrations(read_rows(p(IMMIGRATION_TABLE), IMMIGRATION_TABLE))
        munis = merge(nat, birth, imm)
        if len(munis) < 8000:
            raise ValueError(f"only {len(munis)} municipalities with migration data (expected about 8,132)")
        years = lambda f: sorted({y for m in munis.values() for y in m[f]})  # noqa: E731
        census_years, imm_years = years("foreign"), years("immigrations_abroad")
        return {
            "vintage": f"INE: Censo anual de población {census_years[0]}-{census_years[-1]}, "
            f"migraciones {imm_years[0]}-{imm_years[-1]}",
            "_files": [f"{t}.csv" for t in self.tables],
            "tables": {
                NATIONALITY_TABLE: {"title": TITLES[NATIONALITY_TABLE], "period": ", ".join(census_years), "url": TABLE_URL.format(id=NATIONALITY_TABLE)},
                BIRTH_TABLE: {"title": TITLES[BIRTH_TABLE], "period": ", ".join(years("born_abroad")), "url": TABLE_URL.format(id=BIRTH_TABLE)},
                IMMIGRATION_TABLE: {"title": TITLES[IMMIGRATION_TABLE], "period": ", ".join(imm_years), "url": TABLE_URL.format(id=IMMIGRATION_TABLE)},
            },
            "periods": {"census": census_years, "immigrations": imm_years},
            "national": {"foreign": nat_nat.get("foreign"), "total": nat_nat.get("total"), "born_abroad": birth_nat.get("born_abroad"), "immigrations_abroad": imm_nat},
            "municipalities": dict(sorted(munis.items())),
            "coverage": coverage(munis),
        }
