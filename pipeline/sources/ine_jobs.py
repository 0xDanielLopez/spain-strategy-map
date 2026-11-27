"""INE census: employed residents by municipality and CNAE activity section (Censo, 2024)."""

from __future__ import annotations

import csv

from ..core.source import Source, SourceInfo
from .ine import municipal_code, parse_number

CSV_URL = "https://www.ine.es/jaxiT3/files/t/es/csv_bdsc/{id}.csv"
BIG_TABLE = "69992"  # municipalities of 500 inhabitants or more, CNAE sections
SMALL_TABLE = "70002"  # municipalities of 50 to 500 inhabitants, four sectors
REGION_TABLE = "69968"  # national, CCAA and provinces, CNAE sections
YEAR = "2024"
HEADERS = {
    BIG_TABLE: ["Municipios de 500 habitantes o más", "Sexo", "Actividad económica", "Periodo", "Total"],
    SMALL_TABLE: ["Municipios entre 50 y 500 habitantes", "Sexo", "Actividad económica", "Periodo", "Total"],
    REGION_TABLE: ["Total Nacional", "Comunidades y Ciudades Autónomas", "Provincias", "Actividad económica",
                   "Lugar trabajo", "Sexo", "Periodo", "Total"],
}
SECTORS4 = {"Agricultura, ganadería y pesca": "agricultura", "Industria": "industria",
            "Construcción": "construccion", "Servicios": "servicios"}
TOTAL_LABEL = "Total CNAE"
UNKNOWN_LABEL = "No consta"


def section_key(label: str):
    """CNAE section letter from "A Agricultura, ..." -> "A"; None for "Total CNAE", "No consta" and anything else."""
    head, _, rest = label.strip().partition(" ")
    if rest and len(head) == 1 and head.isalpha() and head.isupper():
        return head
    return None


def check_header(table: str, header: list[str]) -> None:
    got = [h.lstrip("﻿").strip() for h in header]
    if got != HEADERS[table]:
        raise ValueError(f"INE table {table}: unexpected header {got!r}, expected {HEADERS[table]!r}")


def read_rows(path, table: str):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f, delimiter=";")
        check_header(table, next(rd))
        yield from rd


def parse_municipal(rows, table: str, year: str = YEAR):
    """Stream a municipal table into {code: {"total", "unknown", "sections" | "sectors4"}} and {letter: name}."""
    out: dict[str, dict] = {}
    names: dict[str, str] = {}
    n_cols = len(HEADERS[table])
    for r in rows:
        if len(r) != n_cols or r[1].strip() != "Total" or r[3].strip() != year:
            continue
        code = municipal_code(r[0])
        if code is None:
            continue
        label, value = r[2].strip(), parse_number(r[4])
        m = out.setdefault(code, {"total": None, "unknown": None, "sections": {} if table == BIG_TABLE else None,
                                  "sectors4": {} if table == SMALL_TABLE else None})
        if label == TOTAL_LABEL:
            m["total"] = value
        elif label == UNKNOWN_LABEL:
            m["unknown"] = value
        elif table == BIG_TABLE:
            k = section_key(label)
            if k is None:
                raise ValueError(f"unexpected activity {label!r}")
            names[k] = label.partition(" ")[2].strip()
            m["sections"][k] = value
        else:
            k = SECTORS4.get(label)
            if k is None:
                raise ValueError(f"unexpected sector {label!r}")
            m["sectors4"][k] = value
    return out, names


def mismatches(munis: dict) -> list[str]:
    """Codes whose sections (or sectors) plus "No consta" do not add up to the total."""
    bad = []
    for code, m in munis.items():
        parts = m["sections"] if m["sections"] is not None else m["sectors4"]
        s = sum(v or 0 for v in parts.values()) + (m["unknown"] or 0)
        if m["total"] is None or s != m["total"]:
            bad.append(code)
    return sorted(bad)


def parse_regions(rows, year: str = YEAR):
    """{"national": {...}, "ccaa": {code: {...}}, "provinces": {code: {...}}} with "total" and "sections" each."""
    out = {"national": {"total": None, "sections": {}}, "ccaa": {}, "provinces": {}}
    names: dict[str, str] = {}
    for r in rows:
        if len(r) != 8 or r[4].strip() != "Total" or r[5].strip() != "Total" or r[6].strip() != year:
            continue
        nat, ccaa, prov, label = r[0].strip(), r[1].strip(), r[2].strip(), r[3].strip()
        if nat == "Total Nacional" and not ccaa and not prov:
            entry = out["national"]
        elif ccaa and not prov:
            entry = out["ccaa"].setdefault(ccaa.split(" ", 1)[0], {"total": None, "sections": {}})
        elif prov:
            entry = out["provinces"].setdefault(prov.split(" ", 1)[0], {"total": None, "sections": {}})
        else:
            continue
        value = parse_number(r[7])
        if label == TOTAL_LABEL:
            entry["total"] = value
        elif (k := section_key(label)) is not None:
            names[k] = label.partition(" ")[2].strip()
            entry["sections"][k] = value
    return out, names


class IneJobs(Source):
    info = SourceInfo(
        id="ine_jobs",
        title="Censo: ocupados por municipio y sección de actividad económica (CNAE)",
        publisher="Instituto Nacional de Estadística (INE)",
        homepage="https://www.ine.es/jaxiT3/Tabla.htm?t=" + BIG_TABLE,
        license="Reutilización permitida, también comercial, citando la fuente. Elaboración propia con datos extraídos del "
        "sitio web del INE: www.ine.es. El INE no participa, patrocina ni apoya esta reutilización.",
        description="Personas ocupadas residentes en cada municipio, por sección de actividad económica (CNAE) en los "
        "municipios de 500 habitantes o más y por cuatro grandes sectores en los de 50 a 500, más los totales oficiales "
        "de España, las comunidades y las provincias.",
        used_for=["Mapa: capas de empleo por sector", "Ficha de cada ciudad: a qué se dedica su gente"],
    )
    tables = [BIG_TABLE, SMALL_TABLE, REGION_TABLE]

    def fetch(self, force=False):
        for t in self.tables:
            self.download(CSV_URL.format(id=t), f"{t}.csv", force=force, expect_binary=False)

    def process(self):
        p = lambda t: self.raw_dir / f"{t}.csv"  # noqa: E731
        big, names = parse_municipal(read_rows(p(BIG_TABLE), BIG_TABLE), BIG_TABLE)
        small, _ = parse_municipal(read_rows(p(SMALL_TABLE), SMALL_TABLE), SMALL_TABLE)
        if not big or not small:
            raise ValueError(f"year {YEAR} not found in the municipal tables")
        bad_big, bad_small = mismatches(big), mismatches(small)
        overlap = sorted(set(big) & set(small))
        munis = {}
        for code in sorted(set(big) | set(small)):
            m = big.get(code) or small[code]
            munis[code] = {"total": m["total"], "sections": m["sections"], "sectors4": m["sectors4"]}
        regions, rnames = parse_regions(read_rows(p(REGION_TABLE), REGION_TABLE))
        if set(rnames) != set(names):
            raise ValueError(f"section letters differ between tables: {sorted(set(rnames) ^ set(names))}")
        return {
            "vintage": f"INE, Censo de Población y Viviendas: ocupados por actividad económica, {YEAR}",
            "_files": [f"{t}.csv" for t in self.tables],
            "year": int(YEAR),
            "sections": dict(sorted(names.items())),
            "municipalities": munis,
            "regions": regions,
            "checks": {"sum_mismatch_500plus": len(bad_big), "sum_mismatch_50to500": len(bad_small),
                       "mismatch_examples": (bad_big + bad_small)[:10], "tables_overlap": len(overlap)},
        }
