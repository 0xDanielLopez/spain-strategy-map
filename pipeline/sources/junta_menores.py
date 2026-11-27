"""Junta de Andalucía: minor contracts ("contratación menor") 2024 and 2025, aggregated while streaming.

Source: Plataforma de Contratación de la Junta de Andalucía, open-data CSV per year (licence CC BY 4.0).
The files hold ~70,000-125,000 rows each ("|" separated, Windows-1252). The CKAN links point to an internal
host that does not resolve; the same path works on www.juntadeandalucia.es.

PRIVACY: rows are never kept. Each line is read, folded into counters and dropped. The winner columns
(NIF_ADJUDICATARIO, ADJUDICATARIO_DENOMINACION) are never read, and neither are titles or descriptions.
Output holds codes, public-body names and numbers only.

Amount used: IMPORTE_ADJUDICACION_SIN_IVA (award amount WITHOUT VAT, EUR). The legal thresholds of the minor
procedure (15,000 EUR services and supplies, 40,000 EUR works) are also expressed without VAT.
Year = the year of the dataset (the Junta publishes one file per year), not the award date.
"""

from __future__ import annotations

import re

from ..core.source import Source, SourceInfo

HOST = "https://www.juntadeandalucia.es/datosabiertos/portal/dataset"
DATASET_PAGE = HOST + "/{dataset}"
FILES = {
    2024: ("cdf0e880-0a19-46cf-a09e-856328d85700", "8438488e-9d85-47f7-8820-b8f0ef45f264", "menores_2024_v1_20250420.csv"),
    2025: ("00510697-b39d-4e19-b142-14565baafabd", "5a95ae9f-8842-4944-bcf9-2db6b08f5394", "menores_2025_v1_20260618.csv"),
}
LICENSE = "Reconocimiento 4.0 Internacional (CC BY 4.0)"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/deed.es"
USER_AGENT = "spain-strategy-map/1.0 (open-source map project)"
SEP = "|"
ENCODING = "cp1252"
THRESHOLDS = (15_000, 40_000)
BAND_SHARE = 1 / 15  # "just below" a threshold: within the last 1/15 (14,000 of 15,000; 37,333 of 40,000)
AMOUNT_COL = "IMPORTE_ADJUDICACION_SIN_IVA"
USED_COLS = ["ORGANO_CONTRATACION", "LUGAR_EJECUCION_CODIGO", AMOUNT_COL, "NUM_LICITADORES_PRESENTADOS"]
EXPECTED_COLS = 23
FORBIDDEN_COLS = ("NIF_ADJUDICATARIO", "ADJUDICATARIO_DENOMINACION")  # never read

# NUTS3 (Andalucía) -> INE province code
NUTS3_TO_INE = {"ES611": "04", "ES612": "11", "ES613": "14", "ES614": "18", "ES615": "21", "ES616": "23", "ES617": "29", "ES618": "41"}
PROVINCE_NAMES = {"04": "Almería", "11": "Cádiz", "14": "Córdoba", "18": "Granada", "21": "Huelva", "23": "Jaén", "29": "Málaga", "41": "Sevilla"}
NO_PROVINCE = "sin_provincia"  # NUTS2/regional code ("ES61") or empty
OTHER = "otros"  # any other place code (outside Andalucía or invalid)


def parse_amount(text: str):
    """EUR amount from "12145,62" / "9190" / "1.234,50"; blanks and garbage to None (never 0)."""
    t = (text or "").strip()
    if not t:
        return None
    try:
        if "," in t:
            t = t.replace(".", "").replace(",", ".")
        v = float(t)
    except ValueError:
        return None
    return v if v >= 0 else None


def province_key(code: str) -> str:
    c = (code or "").strip().upper()
    if c in NUTS3_TO_INE:
        return NUTS3_TO_INE[c]
    if c in ("ES61", ""):
        return NO_PROVINCE
    return OTHER


def clean_name(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _new_prov() -> dict:
    return {"n": 0, "n_amount": 0, "amount_sin_iva": 0.0, "n_bidders_known": 0, "n_single_bidder": 0,
            "n_lt_15000": 0, "n_lt_40000": 0, "n_band_15000": 0, "n_band_40000": 0}


def aggregate_lines(lines) -> dict:
    """Stream text lines (header first) into counters; rows are dropped as soon as they are counted.

    Lines whose field count is not 23 (a "|" or a line break inside a free-text field) are skipped and
    counted in "rows_malformed": the position of the numeric columns cannot be trusted there.
    """
    it = iter(lines)
    header = [h.strip().lstrip("﻿") for h in next(it).rstrip("\r\n").split(SEP)]
    if len(header) != EXPECTED_COLS:
        raise ValueError(f"junta_menores: expected {EXPECTED_COLS} columns, got {len(header)}")
    missing = [c for c in USED_COLS if c not in header]
    if missing:
        raise ValueError(f"junta_menores: columns missing from the header: {missing}")
    ix = {c: header.index(c) for c in USED_COLS}
    out = {"rows": 0, "rows_malformed": 0, "provinces": {}, "organs": {}}
    bands = [(t, t * (1 - BAND_SHARE)) for t in THRESHOLDS]
    for line in it:
        line = line.rstrip("\r\n")
        if not line.strip():
            continue
        f = line.split(SEP)
        if len(f) != EXPECTED_COLS:
            out["rows_malformed"] += 1
            continue
        out["rows"] += 1
        prov = out["provinces"].setdefault(province_key(f[ix["LUGAR_EJECUCION_CODIGO"]]), _new_prov())
        organ = clean_name(f[ix["ORGANO_CONTRATACION"]]) or "(sin órgano)"
        org = out["organs"].setdefault(organ, {"n": 0, "n_amount": 0, "amount_sin_iva": 0.0})
        prov["n"] += 1
        org["n"] += 1
        amt = parse_amount(f[ix[AMOUNT_COL]])
        if amt is not None:
            for d in (prov, org):
                d["n_amount"] += 1
                d["amount_sin_iva"] += amt
            for t, lo in bands:
                if amt < t:
                    prov[f"n_lt_{t}"] += 1
                    if amt >= lo:
                        prov[f"n_band_{t}"] += 1
        b = f[ix["NUM_LICITADORES_PRESENTADOS"]].strip()
        if b.isdigit() and int(b) >= 1:  # blank and 0 are "unknown", not "no bidder"
            prov["n_bidders_known"] += 1
            if int(b) == 1:
                prov["n_single_bidder"] += 1
    for d in list(out["provinces"].values()) + list(out["organs"].values()):
        d["amount_sin_iva"] = round(d["amount_sin_iva"], 2)
    return out


def aggregate_file(path) -> dict:
    with open(path, encoding=ENCODING, errors="replace", newline=None) as fh:
        return aggregate_lines(fh)


class JuntaMenores(Source):
    info = SourceInfo(
        id="junta_menores",
        title="Contratación menor de la Junta de Andalucía, 2024 y 2025 (agregada por provincia y órgano)",
        publisher="Junta de Andalucía, Plataforma de Contratación",
        homepage="https://www.juntadeandalucia.es/datosabiertos/portal/dataset/00510697-b39d-4e19-b142-14565baafabd",
        license=f"{LICENSE} ({LICENSE_URL}); dataset CKAN license_id CC-BY-4.0",
        description="Número e importe (sin IVA) de contratos menores por provincia de ejecución y por órgano de contratación. Sin adjudicatarios.",
        used_for=["contracts_junta"],
    )

    def url(self, year: int) -> str:
        ds, res, name = FILES[year]
        return f"{HOST}/{ds}/resource/{res}/download/{name}"

    def fetch(self, force: bool = False) -> None:
        for year, (_ds, _res, name) in FILES.items():
            self.download(self.url(year), name, force=force, headers={"User-Agent": USER_AGENT})

    def process(self) -> dict:
        years = {}
        files = []
        for year, (_ds, _res, name) in FILES.items():
            agg = aggregate_file(self.raw_dir / name)
            if agg["rows"] == 0:
                raise ValueError(f"junta_menores {year}: no valid rows")
            years[str(year)] = agg
            files.append(name)
        return {
            "vintage": "Contratación menor Junta de Andalucía " + ", ".join(sorted(years)),
            "unit": "contratos menores publicados (una fila de la plataforma = un contrato o un lote)",
            "amount": "Importe de adjudicación SIN IVA (EUR), campo IMPORTE_ADJUDICACION_SIN_IVA",
            "year_meaning": "año del fichero publicado por la Junta, no de la fecha de adjudicación",
            "province_codes": PROVINCE_NAMES,
            "special_keys": {NO_PROVINCE: "lugar de ejecución solo a nivel de Andalucía (ES61) o vacío", OTHER: "otro lugar de ejecución"},
            "thresholds_eur": list(THRESHOLDS),
            "band_definition": f"n_band_T = contratos con importe en [T x (1 - 1/15), T): 14.000 a 15.000 y 37.333 a 40.000",
            "license": LICENSE,
            "license_url": LICENSE_URL,
            "source_urls": {str(y): DATASET_PAGE.format(dataset=FILES[y][0]) for y in FILES},
            "years": years,
            "_files": files,
        }
