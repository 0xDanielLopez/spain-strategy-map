"""INE functional urban areas (Áreas urbanas funcionales, AUF) 2026: which municipalities belong to each city."""

from __future__ import annotations

import posixpath
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET

from ..core.source import Source, SourceInfo

URL = "https://www.ine.es/metodologia/iu/AmbitosterritorialesIU2026.xlsx"
FILE = "AmbitosterritorialesIU2026.xlsx"
SHEET = "Areas_Urbanas_Funcionales"
EXPECTED_AUF = 68
MIN_ROWS = 1900
NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}
COLUMNS = ["CODIGO AUF", "LITERAL AUF", "CODIGO MUNICIPIO", "LITERAL MUNICIPIO"]


def col_index(ref: str) -> int:
    """0-based column of a cell reference such as "C12"."""
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")) for si in root.findall("m:si", NS)]


def sheet_path(zf: zipfile.ZipFile, name: str) -> str:
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rid = None
    for s in wb.find("m:sheets", NS):
        if s.get("name") == name:
            rid = s.get(f"{{{NS['r']}}}id")
    if rid is None:
        raise ValueError(f"sheet {name!r} not found in the workbook")
    for rel in ET.fromstring(zf.read("xl/_rels/workbook.xml.rels")).findall("pr:Relationship", NS):
        if rel.get("Id") == rid:
            target = rel.get("Target")
            return target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
    raise ValueError(f"no relationship {rid} for sheet {name!r}")


def read_sheet(path, name: str = SHEET) -> list[list[str]]:
    """All rows of one sheet as lists of strings ("" for empty cells)."""
    with zipfile.ZipFile(path) as zf:
        strings = read_shared_strings(zf)
        root = ET.fromstring(zf.read(sheet_path(zf, name)))
    rows = []
    for row in root.iter(f"{{{NS['m']}}}row"):
        cells: dict[int, str] = {}
        for c in row.findall("m:c", NS):
            t = c.get("t")
            if t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(f"{{{NS['m']}}}t"))
            else:
                v = c.find("m:v", NS)
                val = "" if v is None or v.text is None else v.text
                if t == "s" and val != "":
                    val = strings[int(val)]
            cells[col_index(c.get("r"))] = val.strip()
        if cells:
            rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
    return rows


def plain(text: str) -> str:
    """Header text without accents, upper case ("CÓDIGO AUF" -> "CODIGO AUF")."""
    return "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c)).strip().upper()


def parse_auf(rows: list[list[str]]) -> tuple[list[dict], list[dict]]:
    """Return (cities, duplicates). A municipality listed in two AUF is kept in the first and reported."""
    hi = next((i for i, r in enumerate(rows) if "CODIGO AUF" in [plain(x) for x in r]), None)
    if hi is None:
        raise ValueError("header row with CODIGO AUF not found")
    header = [plain(x) for x in rows[hi]]
    idx = {name: header.index(name) for name in COLUMNS}
    cities: dict[str, dict] = {}
    seen: dict[str, str] = {}
    dups = []
    for r in rows[hi + 1:]:
        get = lambda k: r[idx[k]] if idx[k] < len(r) else ""  # noqa: E731
        auf, muni = get("CODIGO AUF"), get("CODIGO MUNICIPIO")
        if not auf or not muni:
            continue
        muni = muni.split(".")[0].zfill(5)
        if muni in seen:
            dups.append({"code": muni, "first": seen[muni], "other": auf})
            continue
        seen[muni] = auf
        city = cities.setdefault(auf, {"id": auf, "literal": get("LITERAL AUF"), "members": []})
        city["members"].append(muni)
    out = sorted(cities.values(), key=lambda c: c["id"])
    for c in out:
        c["members"].sort()
    return out, dups


class Auf(Source):
    info = SourceInfo(
        id="auf",
        title="Áreas urbanas funcionales (AUF) 2026",
        publisher="Instituto Nacional de Estadística (INE)",
        homepage="https://www.ine.es/metodologia/iu/",
        license="Reutilización permitida, también comercial, citando la fuente. Elaboración propia con datos extraídos del "
        "sitio web del INE: www.ine.es. El INE no participa, patrocina ni apoya esta reutilización.",
        description="Las 68 áreas urbanas funcionales que define el INE y los municipios que forman cada una. "
        "Son las ciudades del juego: cada área agrupa la ciudad central y los municipios de su alrededor.",
        used_for=["Mapa: ciudades y su área de influencia", "Ficha de cada ciudad"],
    )

    def fetch(self, force=False):
        self.download(URL, FILE, force=force, expect_binary=True)

    def process(self):
        cities, dups = parse_auf(read_sheet(self.raw_dir / FILE))
        members = [m for c in cities for m in c["members"]]
        if len(cities) != EXPECTED_AUF:
            raise ValueError(f"{len(cities)} AUF, expected {EXPECTED_AUF}")
        if len(members) + len(dups) < MIN_ROWS:
            raise ValueError(f"only {len(members) + len(dups)} AUF member rows (expected about 1,996)")
        return {
            "vintage": "INE, Áreas urbanas funcionales 2026",
            "_files": [FILE],
            "cities": cities,
            "duplicates": dups,
        }
