"""Interior Ministry Balance de Criminalidad: known criminal offences per year (closing tables, Q4).

Three closing tables per year: municipalities over 20,000 inhabitants (plus islands), provinces and
autonomous communities. Each table carries two years (n-1 and n) and a percent-change column, which is
dropped (computed from counts when needed). Numbers use the Spanish format ("." thousands). The
municipality table has the INE 5-digit code in the name ("41091 Sevilla"); provinces and CCAA are
mapped here to their INE codes. Only counts and public-body names are kept; municipalities below the
population threshold are absent ("sin dato"), never zero. Offences "known" are police reports and
actions, not convictions.
"""

from __future__ import annotations

import csv
import re

from ..core.source import Source, SourceInfo

BASE = "https://estadisticasdecriminalidad.ses.mir.es/sec/jaxiPx/files/_px/es/csv_bdsc/DatosBalanceAnt/l0/{id}.csv_bdsc?nocab=1"
LEGAL_URL = "https://estadisticasdecriminalidad.ses.mir.es/publico/portalestadistico/avisoLegal.html"
# year -> (municipalities, provinces, CCAA) closing table ids
TABLES = {
    "2025": ("1509012", "1509011", "1509010"),
    "2024": ("1409012", "1409011", "1409010"),
}
LEVELS = ("muni", "prov", "ccaa")
HEADER_FIRST = {"muni": "Geografía", "prov": "Provincias", "ccaa": "Comunidades autónomas"}
PERIOD_RE = re.compile(r"^enero-diciembre (\d{4})$")
CODE_RE = re.compile(r"^(\d{5})\s+(.+)$")

# (key, Spanish label, label prefix in the CSV). Order = the order of the Balance. 5.1, 5.2 and 7.1 are
# subsets of 5 and 7; I and II add up to III.
TYPOLOGIES = [
    ("conventional", "Criminalidad convencional", "I. "),
    ("homicides", "Homicidios dolosos y asesinatos consumados", "1. "),
    ("homicides_attempted", "Homicidios dolosos y asesinatos en grado tentativa", "2. "),
    ("assaults", "Delitos graves y menos graves de lesiones y riña tumultuaria", "3. "),
    ("kidnapping", "Secuestro", "4. "),
    ("sexual_offences", "Delitos contra la libertad sexual", "5. "),
    ("sexual_aggression_penetration", "Agresión sexual con penetración", "5.1"),
    ("sexual_other", "Resto de delitos contra la libertad sexual", "5.2"),
    ("robbery_violent", "Robos con violencia e intimidación", "6. "),
    ("burglary", "Robos con fuerza en domicilios, establecimientos y otras instalaciones", "7. "),
    ("burglary_dwellings", "Robos con fuerza en domicilios", "7.1"),
    ("theft", "Hurtos", "8. "),
    ("vehicle_theft", "Sustracciones de vehículos", "9. "),
    ("drug_trafficking", "Tráfico de drogas", "10."),
    ("other_conventional", "Resto de criminalidad convencional", "11."),
    ("cyber_fraud", "Estafas informáticas", "12."),
    ("cyber_other", "Otros ciberdelitos", "13."),
    ("cybercrime", "Cibercriminalidad", "II."),
    ("total", "Total de infracciones penales", "III"),
]
TYPOLOGY_KEYS = [t[0] for t in TYPOLOGIES]
_PREFIXES = [(t[2], t[0]) for t in TYPOLOGIES]

# INE province codes (names as the Balance writes them) and autonomous-community codes.
PROVINCE_CODES = {
    "Araba/Álava": "01", "Albacete": "02", "Alicante/Alacant": "03", "Almería": "04", "Ávila": "05", "Badajoz": "06",
    "Balears (Illes)": "07", "Barcelona": "08", "Burgos": "09", "Cáceres": "10", "Cádiz": "11", "Castellón/Castelló": "12",
    "Ciudad Real": "13", "Córdoba": "14", "Coruña (A)": "15", "Cuenca": "16", "Girona": "17", "Granada": "18",
    "Guadalajara": "19", "Gipuzkoa": "20", "Huelva": "21", "Huesca": "22", "Jaén": "23", "León": "24", "Lleida": "25",
    "Rioja (La)": "26", "Lugo": "27", "Madrid": "28", "Málaga": "29", "Murcia": "30", "Navarra": "31", "Ourense": "32",
    "Asturias": "33", "Palencia": "34", "Palmas (Las)": "35", "Pontevedra": "36", "Salamanca": "37",
    "Santa Cruz de Tenerife": "38", "Cantabria": "39", "Segovia": "40", "Sevilla": "41", "Soria": "42", "Tarragona": "43",
    "Teruel": "44", "Toledo": "45", "Valencia/València": "46", "Valladolid": "47", "Bizkaia": "48", "Zamora": "49",
    "Zaragoza": "50", "Ceuta": "51", "Melilla": "52",
}
CCAA_CODES = {
    "ANDALUCÍA": "01", "ARAGÓN": "02", "ASTURIAS (PRINCIPADO DE)": "03", "BALEARS (ILLES)": "04", "CANARIAS": "05",
    "CANTABRIA": "06", "CASTILLA Y LEÓN": "07", "CASTILLA - LA MANCHA": "08", "CATALUÑA": "09", "COMUNITAT VALENCIANA": "10",
    "EXTREMADURA": "11", "GALICIA": "12", "MADRID (COMUNIDAD DE)": "13", "MURCIA (REGIÓN DE)": "14",
    "NAVARRA (COMUNIDAD FORAL DE)": "15", "PAÍS VASCO": "16", "RIOJA (LA)": "17", "CIUDAD AUTÓNOMA DE CEUTA": "18",
    "CIUDAD AUTÓNOMA DE MELILLA": "19",
}
NATIONAL = {"Total Nacional", "TOTAL NACIONAL"}
ABROAD = {"En el extranjero", "EN EL EXTRANJERO"}


def parse_count(text: str):
    """Spanish integer ("1.149") to int; blanks and secrecy marks to None."""
    t = (text or "").strip().strip('"').strip()
    if t in ("", ".", "..", "-", "x", "X"):
        return None
    return int(t.replace(".", ""))


def typology_key(label: str):
    """Key of a typology label, None for anything unknown. 5.1/5.2/7.1 are checked before 5./7."""
    t = (label or "").strip()
    if t.startswith("I. "):
        return "conventional"
    if t.startswith("II."):
        return "cybercrime"
    if t.startswith("III"):
        return "total"
    m = re.match(r"^(\d+(?:\.\d)?)[.\-\s]", t)
    if not m:
        return None
    num = m.group(1)
    for prefix, key in _PREFIXES:
        if prefix[0].isdigit() and prefix.strip(". ") == num:
            return key
    return None


def read_rows(path, level: str):
    """Yield (geo, typology label, period cell, value cell) after validating the header."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f, delimiter=";")
        head = [h.strip() for h in next(rd)]
        if head != [HEADER_FIRST[level], "Tipología penal", "Periodos:", "Total"]:
            raise ValueError(f"Interior crime {level}: unexpected header {head!r}")
        for r in rd:
            if len(r) == 4:
                yield r[0].strip(), r[1].strip(), r[2].strip(), r[3]


def parse_table(rows, level: str):
    """Stream rows into {id: {"name": str, year: {key: count|None}}}, plus the unknown typology labels and the
    islands (muni level, rows without a code that are not a CCAA/national/abroad aggregate)."""
    out: dict[str, dict] = {}
    islands: dict[str, dict] = {}
    unknown: set[str] = set()
    for geo, label, period, value in rows:
        pm = PERIOD_RE.match(period)
        if not pm:
            continue  # percent-change column
        year = pm.group(1)
        key = typology_key(label)
        if key is None:
            unknown.add(label)
            continue
        if level == "muni":
            m = CODE_RE.match(geo)
            if m:
                ident, name, target = m.group(1), m.group(2).strip(), out
            elif geo.startswith("Isla"):
                ident, name, target = re.sub(r"\s+", " ", geo), re.sub(r"\s+", " ", geo), islands
            else:
                continue  # CCAA, national and abroad aggregates: the CCAA table is the source
        elif level == "prov":
            if geo in NATIONAL:
                ident, name, target = "ES", "España", out
            elif geo in ABROAD:
                continue
            else:
                code = PROVINCE_CODES.get(geo)
                if code is None:
                    raise ValueError(f"unknown province {geo!r}")
                ident, name, target = code, geo, out
        else:
            if geo in NATIONAL:
                ident, name, target = "ES", "España", out
            elif geo.upper() in ABROAD:
                continue
            else:
                code = CCAA_CODES.get(geo)
                if code is None:
                    raise ValueError(f"unknown autonomous community {geo!r}")
                ident, name, target = code, geo, out
        rec = target.setdefault(ident, {"name": name})
        rec.setdefault(year, {})[key] = parse_count(value)
    return out, islands, unknown


def revisions(old: dict, new: dict, year: str) -> dict:
    """Compare `year` between an older closing table (`old`) and a newer one: shared ids, changed total, ids only in one."""
    shared = set(old) & set(new)
    changed = [c for c in shared if old[c].get(year, {}).get("total") != new[c].get(year, {}).get("total")]
    return {"shared": len(shared), "changed_total": len(changed), "only_old": len(set(old) - set(new)), "only_new": len(set(new) - set(old))}


class InteriorCrime(Source):
    info = SourceInfo(
        id="interior_crime",
        title="Ministerio del Interior: Balance de Criminalidad (cierre anual)",
        publisher="Ministerio del Interior, Portal Estadístico de Criminalidad",
        homepage="https://estadisticasdecriminalidad.ses.mir.es",
        license="Las presentes condiciones generales permiten la reutilización de los documentos sometidos a ellas para "
        "fines comerciales y no comerciales. Condiciones: está prohibido desnaturalizar el sentido de la información; debe "
        "citarse la fuente: \"Origen de los datos: Portal Estadístico de Criminalidad\"; no se podrá indicar, insinuar o "
        "sugerir que el Portal Estadístico de Criminalidad reutilizado participa, patrocina o apoya la reutilización. "
        f"Fuente de las condiciones: {LEGAL_URL}",
        description="Hechos conocidos (denuncias y actuaciones policiales, no condenas) por tipología penal, enero a diciembre, "
        "en municipios de más de 20.000 habitantes, provincias y comunidades autónomas. Los municipios menores no tienen dato.",
        used_for=["Mapa: capa de seguridad (tasa por 1.000 habitantes)", "Ficha de municipio: 19 tipologías y variación anual"],
    )

    def _file(self, year, level):
        return f"{TABLES[year][LEVELS.index(level)]}.csv"

    def fetch(self, force=False):
        for year in TABLES:
            for level in LEVELS:
                self.download(BASE.format(id=TABLES[year][LEVELS.index(level)]), self._file(year, level), force=force, expect_binary=False)

    def process(self):
        parsed = {}
        files = []
        for year in TABLES:
            for level in LEVELS:
                rel = self._file(year, level)
                files.append(rel)
                parsed[(year, level)] = parse_table(read_rows(self.raw_dir / rel, level), level)
        latest, previous = "2025", "2024"
        out: dict = {
            "vintage": "Balance de Criminalidad, enero-diciembre 2025 y 2024 (cierres)",
            "years": [previous, latest],
            "typologies": [{"key": k, "label": lab} for k, lab, _ in TYPOLOGIES],
            "municipalities": parsed[(latest, "muni")][0],
            "islands": parsed[(latest, "muni")][1],
            "provinces": parsed[(latest, "prov")][0],
            "ccaa": parsed[(latest, "ccaa")][0],
            "revisions_vs_2024_closing": {
                lvl: revisions(parsed[(previous, lvl)][0], parsed[(latest, lvl)][0], previous) for lvl in LEVELS
            },
            "_files": files,
        }
        return out
