"""INE census sections: 2026 boundaries and the per-section tables (income, demographics, census).

A library for the city-scale maps (not part of the national build):

    load_sections(cumuns, year=2026)  -> polygons of the sections of those municipalities (lon/lat degrees)
    load_section_stats(cumuns)        -> per-section / per-district values and the match rate of every table

Boundaries: INE "Seccionado" shapefile (ETRS89 / UTM 30N), read straight from the zip.
Tables (national CSVs of up to 1.6 GB) are streamed ONCE per table for all the municipalities not yet cached;
the result is cached per municipality under data/interim/ine_sections/ (git-ignored).

Section codes change between years (the ADRH tables are one year older than the boundaries). There is no
crosswalk: a 2026 section without a row in a table gets None, and the match rate says how much population that is.
Only aggregates per section / district are kept; nothing about persons.

CLI:  uv run python -m pipeline.sources.ine_sections fetch | stats <cumun> [<cumun> ...]
"""

from __future__ import annotations

import csv
import json
import re
import sys
import zipfile

from ..core import fetch
from ..core.paths import INTERIM, RAW
from ..core.shapefile import iter_polygons, read_dbf_all
from ..core.source import Source, SourceInfo
from ..core.store import atomic_write_text
from ..core.utm import utm_to_lonlat
from .ine import parse_number

CACHE = INTERIM / "ine_sections"
CACHE_VERSION = 1
ZIP_URL = "https://www.ine.es/prodyser/cartografia/seccionado_{year}.zip"
ZIP_PATH = "seccionado_{year}.zip"

INCOME, DISTRIBUTION, DEMOGRAPHICS = "30824", "30829", "30832"
NATIONALITY, BIRTH = "65032", "65031"
TABLE_FILES = {
    INCOME: RAW / "ine" / "30824.csv",
    DISTRIBUTION: RAW / "ine" / "30829.csv",
    DEMOGRAPHICS: RAW / "ine" / "30832.csv",
    NATIONALITY: RAW / "ine_migration" / "65032.csv",
    BIRTH: RAW / "ine_migration" / "65031.csv",
}
# table -> (column of the municipality cell, column of the district cell, section cell; the rest is per table)
INCOME_FIELDS = {"Renta neta media por persona": "income"}
DEMOGRAPHIC_FIELDS = {
    "Población": "adrh_pop",
    "Edad media de la población": "age",
    "Porcentaje de población menor de 18 años": "under18_pct",
    "Porcentaje de población de 65 y más años": "over65_pct",
    "Tamaño medio del hogar": "household_size",
    "Porcentaje de hogares unipersonales": "single_households_pct",
}
POVERTY_MARK = "por debajo 60% de la mediana"
NATIONALITY_FIELDS = {"Total": "pop", "Extranjera": "foreign"}  # "Extranjera" = every foreign nationality
BIRTH_FIELDS = {"Extranjero": "born_abroad"}
# the field that says "this section has a value in this table", for the match rate
PRIMARY = {INCOME: "income", DISTRIBUTION: "poverty60_pct", DEMOGRAPHICS: "age", NATIONALITY: "pop", BIRTH: "born_abroad"}
ADRH_FIELDS = ["income", "adrh_pop", "age", "under18_pct", "over65_pct", "household_size", "single_households_pct", "poverty60_pct"]
SECTION_FIELDS = ["pop", "foreign", "born_abroad"] + ADRH_FIELDS

CODE_RE = re.compile(r"^(\d{10}|\d{7}|\d{5})\b")

INFO = SourceInfo(
    id="ine_sections",
    title="Seccionado censal y tablas por sección censal (INE)",
    publisher="Instituto Nacional de Estadística (INE)",
    homepage="https://www.ine.es/ss/Satellite?L=es_ES&c=Page&cid=1259952026632&p=1254735110672&pagename=ProductosYServicios%2FPYSLayout",
    license="INE: reutilización con cita de la fuente",
    description=(
        "Límites de las secciones censales (ETRS89) y, por sección, la renta media (ADRH), indicadores demográficos, "
        "población por nacionalidad y lugar de nacimiento (Censo anual). Solo agregados por sección, distrito y municipio."
    ),
    used_for=["Mapas de ciudad: valores estimados por hexágono a partir de la sección censal"],
)


class IneSections(Source):
    """Not auto-registered (the national catalog would list it): the registry only discovers classes that carry
    `info` at class level. To register it, set `info = INFO` on the class."""

    def __init__(self):
        self.info = INFO

    def fetch(self, force: bool = False) -> None:
        self.download(ZIP_URL.format(year=2026), ZIP_PATH.format(year=2026), force=force, expect_binary=True)

    def process(self) -> dict:
        recs = _dbf_rows(2026)
        return {"sections_2026": len(recs), "municipalities": len({r["CUMUN"] for r in recs}), "vintage": "Seccionado 2026"}


# ---------------------------------------------------------------- boundaries


def _zip_path(year: int):
    p = RAW / "ine_sections" / ZIP_PATH.format(year=year)
    if not p.exists():
        if fetch.OFFLINE:
            raise fetch.OfflineError(f"missing {p}")
        fetch.download("ine_sections", ZIP_URL.format(year=year), ZIP_PATH.format(year=year), expect_binary=True)
    return p


def _members(zf: zipfile.ZipFile) -> dict[str, str]:
    out = {}
    for n in zf.namelist():
        low = n.lower()
        for ext in ("shp", "dbf", "cpg"):
            if low.endswith("." + ext) and "secc" in low:
                out[ext] = n
    if "shp" not in out or "dbf" not in out:
        raise ValueError("seccionado zip: .shp/.dbf not found")
    return out


def _dbf_rows(year: int) -> list[dict | None]:
    with zipfile.ZipFile(_zip_path(year)) as zf:
        m = _members(zf)
        enc = zf.read(m["cpg"]).decode("ascii", "ignore").strip() if "cpg" in m else "utf-8"
        enc = {"UTF-8": "utf-8"}.get(enc.upper(), enc or "utf-8")
        with zf.open(m["dbf"]) as f:
            return read_dbf_all(f, enc)


def _round_rings(rings):
    return [[[round(x, 6), round(y, 6)] for x, y in ring] for ring in rings]


def load_sections(cumuns: set[str], year: int = 2026) -> list[dict]:
    """Sections of the given municipalities: {"cusec", "cudis", "cumun", "nmun", "rings": [[(lon, lat), ...], ...]}."""
    cumuns = set(cumuns)
    CACHE.mkdir(parents=True, exist_ok=True)
    cached: dict[str, list] = {}
    todo = set()
    for c in sorted(cumuns):
        p = CACHE / f"sections_{year}_{c}.json"
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            if doc.get("version") != CACHE_VERSION:
                raise ValueError
            cached[c] = doc["sections"]
        except (OSError, ValueError, KeyError):
            todo.add(c)
    if todo:
        rows = _dbf_rows(year)
        wanted = {i: r for i, r in enumerate(rows) if r and r.get("CUMUN") in todo}
        fresh: dict[str, list] = {c: [] for c in todo}
        with zipfile.ZipFile(_zip_path(year)) as zf, zf.open(_members(zf)["shp"]) as f:
            for i, rings in iter_polygons(f, wanted):
                r = wanted[i]
                ll = [[utm_to_lonlat(x, y) for x, y in ring] for ring in rings]
                fresh[r["CUMUN"]].append(
                    {"cusec": r["CUSEC"], "cudis": r["CUDIS"], "cumun": r["CUMUN"], "nmun": r.get("NMUN", ""), "rings": _round_rings(ll)}
                )
        for c, secs in fresh.items():
            secs.sort(key=lambda s: s["cusec"])
            atomic_write_text(CACHE / f"sections_{year}_{c}.json", json.dumps({"version": CACHE_VERSION, "sections": secs}, separators=(",", ":")))
            cached[c] = secs
    out = []
    for c in sorted(cumuns):
        for s in cached.get(c, []):
            out.append({**s, "rings": [[(x, y) for x, y in ring] for ring in s["rings"]]})
    return out


# ---------------------------------------------------------------- tables


def _token(cell: str) -> str | None:
    m = CODE_RE.match((cell or "").strip())
    return m.group(1) if m else None


def _stream(path, key_col: int, codes: set[str]):
    """Rows (list of cells) whose municipality cell starts with one of `codes`; a cheap byte test first."""
    keys = {c.encode() for c in codes}
    with open(path, "rb") as f:
        next(f, None)  # header
        for line in f:
            parts = line.split(b";", key_col + 1)
            if len(parts) <= key_col or parts[key_col][:5] not in keys:
                continue
            yield next(csv.reader([line.decode("utf-8").rstrip("\r\n")], delimiter=";"))


def _check_header(path, expected: list[str]):
    with open(path, encoding="utf-8-sig", newline="") as f:
        got = [h.strip() for h in next(csv.reader(f, delimiter=";"))]
    if got != expected:
        raise ValueError(f"{path.name}: unexpected header {got!r}, expected {expected!r}")


def _parse_table(table: str, codes: set[str]) -> dict[str, dict]:
    """One streaming pass: {cumun: {"period": latest, "sections": {cusec: {field: v}}, "districts": {cudis: {...}}}}."""
    path = TABLE_FILES[table]
    if table in (INCOME, DEMOGRAPHICS):
        _check_header(path, ["Municipios", "Distritos", "Secciones", "Indicadores de renta media" if table == INCOME else "Indicadores demográficos", "Periodo", "Total"])
    elif table == DISTRIBUTION:
        _check_header(path, ["Municipios", "Distritos", "Secciones", "Sexo", "Distribución de la renta por unidad de consumo", "Periodo", "Total"])
    else:
        _check_header(path, ["Total Nacional", "Provincias", "Municipios", "Secciones", "Sexo", "Nacionalidad" if table == NATIONALITY else "Lugar de nacimiento", "Periodo", "Total"])
    census = table in (NATIONALITY, BIRTH)
    key_col = 2 if census else 0
    acc: dict[str, dict] = {}  # cumun -> {"sec"/"dis": {code: {field: {period: v}}}, "period": max}
    for r in _stream(path, key_col, codes):
        if census:
            if len(r) != 8 or r[4].strip() != "Total":
                continue
            sec_cell, dist_cell, name, period, val = r[3], "", r[5].strip(), r[6].strip(), r[7]
            field = (NATIONALITY_FIELDS if table == NATIONALITY else BIRTH_FIELDS).get(name)
            muni = _token(r[2])
        else:
            if table == DISTRIBUTION:
                if len(r) != 7 or r[3].strip() != "Total" or POVERTY_MARK not in r[4]:
                    continue
                name, period, val, field = r[4], r[5].strip(), r[6], "poverty60_pct"
            else:
                if len(r) != 6:
                    continue
                name, period, val = r[3].strip(), r[4].strip(), r[5]
                field = (INCOME_FIELDS if table == INCOME else DEMOGRAPHIC_FIELDS).get(name)
            sec_cell, dist_cell, muni = r[2], r[1], _token(r[0])
        if field is None or muni not in codes:
            continue
        sec, dist = _token(sec_cell), _token(dist_cell)
        if sec and len(sec) == 10:
            kind, code = "sections", sec
        elif not (sec_cell.strip()) and dist and len(dist) == 7:
            kind, code = "districts", dist
        else:
            continue
        try:
            v = parse_number(val)
        except ValueError:
            v = None
        a = acc.setdefault(muni, {"sections": {}, "districts": {}, "period": ""})
        a[kind].setdefault(code, {}).setdefault(field, {})[period] = v
        if period > a["period"]:
            a["period"] = period
    out = {}
    for muni, a in acc.items():
        per = a["period"]
        out[muni] = {
            "period": per,
            **{k: {code: {f: pv.get(per) for f, pv in fv.items()} for code, fv in a[k].items()} for k in ("sections", "districts")},
        }
    return out


def _cache_stats(cumuns: set[str]) -> dict[str, dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    have, todo = {}, set()
    for c in sorted(cumuns):
        try:
            doc = json.loads((CACHE / f"stats_{c}.json").read_text(encoding="utf-8"))
            if doc.get("version") != CACHE_VERSION:
                raise ValueError
            have[c] = doc
        except (OSError, ValueError):
            todo.add(c)
    if todo:
        per_table = {t: _parse_table(t, todo) for t in TABLE_FILES}  # one pass per table for every pending municipality
        for c in todo:
            doc = {"version": CACHE_VERSION, "tables": {t: per_table[t].get(c, {"period": None, "sections": {}, "districts": {}}) for t in TABLE_FILES}}
            atomic_write_text(CACHE / f"stats_{c}.json", json.dumps(doc, separators=(",", ":")))
            have[c] = doc
    return have


def load_section_stats(cumuns: set[str]) -> dict:
    """Per-section and per-district statistics plus the match rate of each table (see module doc)."""
    cumuns = set(cumuns)
    docs = _cache_stats(cumuns)
    in_map: dict[str, str] = {}  # cusec -> cumun, from the 2026 boundaries
    for r in _dbf_rows(2026):
        if r and r.get("CUMUN") in cumuns:
            in_map[r["CUSEC"]] = r["CUMUN"]
    sections = {c: {f: None for f in SECTION_FIELDS} for c in sorted(in_map)}
    districts: dict[str, dict] = {}
    vintage: dict[str, str | None] = {}
    outside = {t: 0 for t in TABLE_FILES}
    for c in sorted(cumuns):
        for t, tab in docs[c]["tables"].items():
            if tab["period"] and (vintage.get(t) is None or tab["period"] > vintage[t]):
                vintage[t] = tab["period"]
            for cusec, vals in tab["sections"].items():
                if cusec in sections:
                    for f, v in vals.items():
                        sections[cusec][f] = v
                elif any(v is not None for v in vals.values()):
                    outside[t] += 1  # a row at the latest period for a section that is not in the 2026 map
            if t in (INCOME, DISTRIBUTION, DEMOGRAPHICS):
                for cudis, vals in tab["districts"].items():
                    d = districts.setdefault(cudis, {f: None for f in ADRH_FIELDS})
                    d.update(vals)
    total_pop = sum(s["pop"] or 0 for s in sections.values())
    match = {}
    for t, f in PRIMARY.items():
        have = [s for s in sections.values() if s[f] is not None]
        match[t] = {
            "sections_in_map": len(sections),
            "with_value": len(have),
            "rows_without_polygon": outside[t],
            "pop_share_matched": round(sum(s["pop"] or 0 for s in have) / total_pop, 4) if total_pop else None,
        }
    return {"vintage": vintage, "sections": sections, "districts": districts, "match": match}


def main(argv: list[str]) -> int:
    import time

    if not argv or argv[0] not in ("fetch", "stats"):
        print(__doc__)
        return 2
    if argv[0] == "fetch":
        IneSections().fetch()
        return 0
    t0 = time.time()
    codes = set(argv[1:])
    secs = load_sections(codes)
    t1 = time.time()
    st = load_section_stats(codes)
    print(f"sections {len(secs)} ({t1 - t0:.1f}s); stats {time.time() - t1:.1f}s")
    print("pop", sum(s["pop"] or 0 for s in st["sections"].values()))
    print(json.dumps({"vintage": st["vintage"], "match": st["match"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
