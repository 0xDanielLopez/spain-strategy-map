"""INE municipal housing: Census 2021 dwellings (table 59525) and experimental tourist dwellings (39363).

Spanish number format ("." thousands, "," decimals, "." alone or "" = secret -> None). The census table
comes from the older tpx exporter (TAB separated); the tourist table is a normal ";" bulk CSV with
province, municipality and national rows mixed in: only rows with a municipal code are kept per
municipality, the national rows feed a national series.
"""

from __future__ import annotations

import csv

from ..core.source import Source, SourceInfo
from .ine import municipal_code, parse_number

CENSUS_TABLE = "59525"
TOURIST_TABLE = "39363"
CENSUS_URL = "https://www.ine.es/jaxi/files/tpx/es/csv_bd/59525.csv"
TOURIST_URL = "https://www.ine.es/jaxiT3/files/t/es/csv_bdsc/39363.csv"
TABLE_URL = "https://www.ine.es/jaxiT3/Tabla.htm?t={id}"

CENSUS_HEADER = ["Total Nacional", "Municipios", "Tipo de vivienda (principal o no)", "Total"]
TOURIST_HEADER = ["Total Nacional", "Comunidades y Ciudades Autónomas", "Provincias", "Municipios", "Viviendas y plazas", "Periodo", "Total"]
CENSUS_LABELS = {"Total": "dwellings_total", "Vivienda principal": "dwellings_primary", "Vivienda no principal": "dwellings_non_primary"}
TOURIST_LABELS = {"Viviendas turísticas": "tourist_homes", "Plazas": "tourist_beds"}
FIELDS = ["dwellings_total", "dwellings_primary", "dwellings_non_primary", "tourist_homes", "tourist_beds"]


def read_rows(path, delimiter: str, header: list[str], table: str):
    """Yield data rows (lists of cells) of a bulk CSV after validating its header."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f, delimiter=delimiter)
        got = [h.strip() for h in next(rd)]
        if got != header:
            raise ValueError(f"INE table {table}: unexpected header {got!r}, expected {header!r}")
        yield from rd


def parse_census(rows):
    """Census 2021 dwellings: ({code: {field: int|None}}, {field: national int}). Only the three known labels."""
    munis: dict[str, dict[str, int | None]] = {}
    national: dict[str, int | None] = {}
    for r in rows:
        if len(r) != 4:
            continue
        field = CENSUS_LABELS.get(r[2].strip())
        if field is None:
            continue
        value = parse_number(r[3])
        if not r[1].strip():
            national[field] = value
            continue
        code = municipal_code(r[1])
        if code is not None:
            munis.setdefault(code, {})[field] = value
    return munis, national


def parse_tourist(rows):
    """Tourist dwellings: ({code: {field: {period: int|None}}}, {field: {period: int|None}} national series)."""
    munis: dict[str, dict[str, dict[str, int | None]]] = {}
    national: dict[str, dict[str, int | None]] = {}
    for r in rows:
        if len(r) != 7:
            continue
        field = TOURIST_LABELS.get(r[4].strip())
        if field is None:
            continue
        period, value = r[5].strip(), parse_number(r[6])
        if not (r[1].strip() or r[2].strip() or r[3].strip()):
            national.setdefault(field, {})[period] = value
            continue
        code = municipal_code(r[3])
        if code is not None:
            munis.setdefault(code, {}).setdefault(field, {})[period] = value
    return munis, national


def latest_period(munis: dict, field: str) -> str:
    periods = {p for m in munis.values() for p in m.get(field, {})}
    if not periods:
        raise ValueError(f"no periods for {field}")
    return max(periods)


def coverage(munis: dict[str, dict], fields=FIELDS) -> dict:
    return {f: {"municipalities": sum(1 for m in munis.values() if m.get(f) is not None)} for f in fields}


class IneHousing(Source):
    info = SourceInfo(
        id="ine_housing",
        title="INE: viviendas del Censo 2021 y viviendas turísticas (experimental)",
        publisher="Instituto Nacional de Estadística (INE)",
        homepage="https://www.ine.es",
        license="Reutilización permitida, también comercial, citando la fuente. Elaboración propia con datos extraídos del "
        "sitio web del INE: www.ine.es. El INE no participa, patrocina ni apoya esta reutilización.",
        description="Viviendas totales, principales y no principales por municipio (Censo 2021) y viviendas turísticas y "
        "plazas turísticas por municipio (estadística experimental del INE, último corte y serie nacional).",
        used_for=["Mapa: viviendas no principales y presión turística", "Ficha de cada municipio"],
    )

    def fetch(self, force=False):
        self.download(CENSUS_URL, f"{CENSUS_TABLE}.csv", force=force, expect_binary=False)
        self.download(TOURIST_URL, f"{TOURIST_TABLE}.csv", force=force, expect_binary=False)

    def process(self):
        census, census_nat = parse_census(read_rows(self.raw_dir / f"{CENSUS_TABLE}.csv", "\t", CENSUS_HEADER, CENSUS_TABLE))
        tourist, tourist_nat = parse_tourist(read_rows(self.raw_dir / f"{TOURIST_TABLE}.csv", ";", TOURIST_HEADER, TOURIST_TABLE))
        if len(census) < 8000:
            raise ValueError(f"only {len(census)} municipalities in the census dwellings table (expected about 8,131)")
        periods = sorted({p for m in tourist.values() for per in m.values() for p in per})
        latest = latest_period(tourist, "tourist_homes")
        munis: dict[str, dict] = {}
        for code in sorted(set(census) | set(tourist)):
            row = {f: None for f in FIELDS}
            row.update(census.get(code, {}))
            for f in ("tourist_homes", "tourist_beds"):
                row[f] = tourist.get(code, {}).get(f, {}).get(latest)
            row["tourist_period"] = latest
            munis[code] = row
        return {
            "vintage": f"INE: Censo 2021 (viviendas), viviendas turísticas experimentales {latest}",
            "_files": [f"{CENSUS_TABLE}.csv", f"{TOURIST_TABLE}.csv"],
            "tables": {
                CENSUS_TABLE: {"title": "Censo 2021: viviendas por municipio y tipo (principal o no)", "period": "2021", "url": TABLE_URL.format(id=CENSUS_TABLE)},
                TOURIST_TABLE: {"title": "Viviendas turísticas y plazas (estadística experimental)", "period": latest, "url": TABLE_URL.format(id=TOURIST_TABLE)},
            },
            "periods": {"census": "2021", "tourist": latest, "tourist_all": periods},
            "national": {"census_2021": census_nat, "tourist_series": tourist_nat},
            "municipalities": munis,
            "coverage": coverage(munis),
        }
