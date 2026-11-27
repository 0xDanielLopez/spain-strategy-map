"""INE Contabilidad Regional de España: gross domestic product (PIB) at current prices, by province and CCAA."""

from __future__ import annotations

import csv

from ..core.source import Source, SourceInfo
from ._spain import CCAA, PROVINCE_TO_CCAA
from .ine import parse_number

TABLE = "80109"
URL = f"https://www.ine.es/jaxiT3/files/t/es/csv_bdsc/{TABLE}.csv"
HEADER = ["Comunidades y Ciudades Autónomas y Provincias", "Magnitud", "Periodo", "Total"]
LEVEL = "Valor"  # level at current prices; the other magnitudes are % structure and variation rates
UNIT = 1000  # the table is in thousands of euros


def split_code(label: str):
    """("28", "Madrid") from "28 Madrid"; (None, label) when there is no leading 2-digit code."""
    head, _, rest = label.strip().partition(" ")
    if len(head) == 2 and head.isdigit():
        return head, rest.strip()
    return None, label.strip()


def parse_gdp(rows):
    """Return {period: {"national": thousands, "ccaa": {code: thousands}, "provinces": {code: thousands}}}.

    CCAA and province codes collide (01 Andalucía vs 01 Araba/Álava): CCAA rows are written in
    capitals, provinces in normal case. A CCAA with a single province (Madrid, Murcia, Navarra, Asturias,
    Cantabria, La Rioja, Illes Balears, Ceuta, Melilla) has no province rows: its value is that province's.
    """
    out: dict[str, dict] = {}
    for r in rows:
        if len(r) != 4 or r[1].strip() != LEVEL:
            continue
        label, period, value = r[0].strip(), r[2].strip(), parse_number(r[3])
        d = out.setdefault(period, {"national": None, "ccaa": {}, "provinces": {}})
        if label == "Total Nacional":
            d["national"] = value
            continue
        code, name = split_code(label)
        if code is None or name == "EXTRA-REGIO":
            continue
        if name == name.upper():
            d["ccaa"][code] = value
        else:
            d["provinces"][code] = value
    ccaa_codes = {c["code"] for c in CCAA}
    by_ccaa: dict[str, list[str]] = {}
    for p, c in PROVINCE_TO_CCAA.items():
        by_ccaa.setdefault(c, []).append(p)
    for period, d in out.items():
        for c, ps in by_ccaa.items():
            if len(ps) == 1 and ps[0] not in d["provinces"] and c in d["ccaa"]:
                d["provinces"][ps[0]] = d["ccaa"][c]
        if set(d["ccaa"]) - ccaa_codes:
            raise ValueError(f"unexpected CCAA codes in {period}: {sorted(set(d['ccaa']) - ccaa_codes)}")
    return out


def complete(d: dict) -> bool:
    """True when the national total, all 19 CCAA and all 52 provinces have a value."""
    return (
        d["national"] is not None
        and len(d["ccaa"]) == 19 and all(v is not None for v in d["ccaa"].values())
        and set(d["provinces"]) == set(PROVINCE_TO_CCAA) and all(v is not None for v in d["provinces"].values())
    )


def pin_year(by_period: dict) -> str:
    ok = [p for p, d in by_period.items() if complete(d)]
    if not ok:
        raise ValueError("no year with the national total, 19 CCAA and 52 provinces")
    return max(ok)


def to_euros(thousands):
    return None if thousands is None else int(thousands) * UNIT


class IneGdp(Source):
    info = SourceInfo(
        id="ine_gdp",
        title="Contabilidad Regional de España: PIB a precios corrientes por provincias y comunidades",
        publisher="Instituto Nacional de Estadística (INE)",
        homepage=f"https://www.ine.es/jaxiT3/Tabla.htm?t={TABLE}",
        license="Reutilización permitida, también comercial, citando la fuente. Elaboración propia con datos extraídos del "
        "sitio web del INE: www.ine.es. El INE no participa, patrocina ni apoya esta reutilización.",
        description="Producto interior bruto a precios corrientes de España, de las 19 comunidades y ciudades autónomas y de "
        "las 52 provincias, en el último año con datos de todas las provincias.",
        used_for=["Mapa: riqueza de cada ciudad y región", "Ficha de cada ciudad"],
    )

    def fetch(self, force=False):
        self.download(URL, f"{TABLE}.csv", force=force, expect_binary=False)

    def process(self):
        with open(self.raw_dir / f"{TABLE}.csv", encoding="utf-8-sig", newline="") as f:
            rd = csv.reader(f, delimiter=";")
            header = [h.strip() for h in next(rd)]
            if header != HEADER:
                raise ValueError(f"INE table {TABLE}: unexpected header {header!r}")
            by_period = parse_gdp(rd)
        year = pin_year(by_period)
        d = by_period[year]
        return {
            "vintage": "INE, Contabilidad Regional de España",
            "_files": [f"{TABLE}.csv"],
            "year": int(year),
            "unit": "euros",
            "national": to_euros(d["national"]),
            "ccaa": {c: to_euros(v) for c, v in sorted(d["ccaa"].items())},
            "provinces": {p: to_euros(v) for p, v in sorted(d["provinces"].items())},
        }
