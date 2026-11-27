"""Explorer files: counties.json (municipality explorer), districts.json (sector specialisations) and citizens.json.

Everything comes from the INE interim (municipal values, never from hex lenses) and from cities.json / nation.json.

* counties.json: one column-oriented row per municipality, in world.json `counties` order. null stays null.
* districts.json: per city, the CNAE sections (except T and U) where the city's residents work more than the
  national average: location quotient LQ = (city jobs in the section / city employed with sections) /
  (national jobs in the section / national employed with sections). Jobs are counted where people LIVE (Censo
  anual de población 2024), not where the firms are. Rule ported from the original: LQ >= MIN_LQ and at least
  MIN_JOBS jobs or MIN_SHARE of the city's jobs; strength = jobs - jobs / LQ; up to MAX_PER_CITY, strongest first.
* citizens.json: per city three separate distributions, each with its own base (age and nationality over all
  residents, education over residents 15 and over), summed over the member municipalities that have data.
"""

from __future__ import annotations

import unicodedata

from ..core.store import load_interim, write_web
from .economy import KEYS

REQUIRES = ["_world", "gisco_lau", "ine", "auf", "world.json", "cities.json", "nation.json"]
PRODUCES = ["counties.json", "districts.json", "citizens.json"]

MIN_LQ = 1.25
MIN_JOBS = 1000
MIN_SHARE = 0.01
MAX_PER_CITY = 5
EXCLUDED = ("t", "u")  # households as employers, extraterritorial bodies: not an economic specialisation
SECTION_KEYS = [k for k in KEYS if k not in EXCLUDED]
CITIZEN_FIGURES = 10

# CNAE section letter -> icon key. Same table as web/js/industry.js (tests/test_explorer.py keeps them equal).
ICON_KEY = {
    "a": "agriculture", "b": "mining", "c": "manufacturing", "d": "utilities", "e": "utilities", "f": "construction",
    "g": "retail", "h": "transportation", "i": "accommodation", "j": "information", "k": "finance", "l": "real_estate",
    "m": "professional", "n": "admin", "o": "public_admin", "p": "education", "q": "health", "r": "arts", "s": "other",
}
COLORS = {
    "a": "#7fbf3f", "b": "#8a7f6a", "c": "#c2643a", "d": "#e0b030", "e": "#3aa0a0", "f": "#b8864a", "g": "#d0a23a",
    "h": "#6a8fb8", "i": "#d0508a", "j": "#4a7bd0", "k": "#2f8f6a", "l": "#9a6ab0", "m": "#5a6fd0", "n": "#7a8a9a",
    "o": "#8a9a5b", "p": "#3a8fc0", "q": "#d05050", "r": "#a15bc4", "s": "#8a8a8a",
}
BADGE = {
    "a": "Ciudad agraria", "b": "Ciudad minera", "c": "Ciudad industrial", "d": "Ciudad energética",
    "e": "Ciudad de servicios ambientales", "f": "Ciudad de la construcción", "g": "Ciudad comercial",
    "h": "Nodo logístico", "i": "Ciudad de la hostelería", "j": "Ciudad digital", "k": "Ciudad financiera",
    "l": "Ciudad inmobiliaria", "m": "Ciudad de servicios profesionales", "n": "Ciudad de servicios a empresas",
    "o": "Ciudad administrativa", "p": "Ciudad educativa", "q": "Ciudad sanitaria", "r": "Ciudad del ocio y las artes",
    "s": "Ciudad de servicios personales",
}
DESCRIPTION = {
    "a": "Agricultura, ganadería, silvicultura y pesca.",
    "b": "Extracción de carbón, petróleo, gas, minerales metálicos y canteras.",
    "c": "Industria manufacturera: alimentación, metal, química, automoción, maquinaria y más.",
    "d": "Producción y distribución de electricidad, gas, vapor y aire acondicionado.",
    "e": "Captación y depuración de agua, saneamiento, gestión de residuos y descontaminación.",
    "f": "Edificación, obra civil y actividades de construcción especializada.",
    "g": "Comercio al por mayor y al por menor y reparación de vehículos de motor.",
    "h": "Transporte terrestre, marítimo y aéreo, almacenamiento y correos.",
    "i": "Hoteles, campings, restaurantes y bares.",
    "j": "Edición, audiovisual, telecomunicaciones, programación e informática.",
    "k": "Bancos, seguros, fondos de pensiones y actividades auxiliares.",
    "l": "Compraventa y alquiler de inmuebles y servicios inmobiliarios.",
    "m": "Servicios jurídicos, contables, arquitectura, ingeniería, investigación, publicidad y consultoría.",
    "n": "Alquiler, empleo, agencias de viajes, seguridad, limpieza y servicios de apoyo a empresas.",
    "o": "Administración pública, defensa y Seguridad Social obligatoria.",
    "p": "Educación en todos los niveles.",
    "q": "Hospitales, atención ambulatoria y residencial, y servicios sociales.",
    "r": "Artes, espectáculos, bibliotecas, museos, juego y actividades deportivas y recreativas.",
    "s": "Asociaciones, reparación de ordenadores y enseres y servicios personales (peluquería, lavandería).",
}
NOTE = ("Especialización de la población ocupada según dónde vive (Censo anual de población 2024, INE): "
        "cociente de localización frente a España. No mide dónde están las empresas.")
ATTRIBUTION = [
    {"data": "población, ocupados por sección CNAE, renta, edad, nacionalidad y estudios",
     "source": "INE: Censo anual de población y Atlas de distribución de renta de los hogares",
     "license": "Reutilización con cita de la fuente (INE)."},
    {"data": "límites y superficie municipales",
     "source": "Eurostat GISCO, Unidades Administrativas Locales (LAU) 2024",
     "license": "© EuroGeographics para los límites administrativos. Solo uso no comercial, con este aviso visible; fuera de la licencia MIT."},
]


def es(x: float, nd: int = 1) -> str:
    """es-ES decimal comma."""
    return f"{x:.{nd}f}".replace(".", ",")


def fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


# --- counties.json -------------------------------------------------------------------------------------------

COUNTY_FIELDS = [
    ("geoid", "Código INE", "text", "", "neutral", "gisco_lau", "Código INE del municipio (5 cifras: provincia y municipio)."),
    ("name", "Municipio", "text", "", "neutral", "gisco_lau", "Nombre del municipio."),
    ("state", "Comunidad", "text", "", "neutral", "gisco_lau", "Comunidad autónoma (abreviatura)."),
    ("province", "Provincia", "text", "", "neutral", "gisco_lau", "Código de provincia (2 cifras)."),
    ("population", "Población", "int", "personas", "neutral", "ine", "Habitantes según el Censo anual de población 2026 (INE)."),
    ("land_km2", "Superficie", "float", "km²", "neutral", "gisco_lau", "Superficie del municipio según Eurostat GISCO (LAU 2024)."),
    ("density", "Densidad", "int", "hab./km²", "neutral", "ine", "Población dividida por la superficie del municipio."),
    ("growth", "Crecimiento", "pct", "variación de la población", "neutral", "ine", "Variación de la población entre 2021 y 2026 (Censo anual de población, INE)."),
    ("age_mean", "Edad media", "float", "años", "neutral", "ine", "Edad media de los residentes (media, no mediana; INE 2024)."),
    ("elderly", "Mayores de 65", "pct", "% de la población", "neutral", "ine", "Porcentaje de residentes de 65 años o más (INE 2024)."),
    ("foreign", "Nacionalidad extranjera", "pct", "% de la población", "neutral", "ine", "Porcentaje de residentes con nacionalidad extranjera, no con país de nacimiento extranjero (INE 2024)."),
    ("household", "Tamaño del hogar", "float", "personas", "neutral", "ine", "Personas por hogar (INE 2024)."),
    ("income", "Renta por persona", "eur", "€", "good", "ine", "Renta media por persona, media y no mediana (Atlas de distribución de renta de los hogares, INE 2024)."),
    ("poverty", "Bajo el umbral de pobreza", "pct", "% de la población", "bad", "ine", "Porcentaje de población con renta por debajo del 60 % de la mediana (INE 2024)."),
    ("higher_education", "Estudios superiores", "pct", "% de la población de 15 años o más", "good", "ine", "Residentes de 15 años o más con estudios superiores (INE 2024; solo municipios con dato)."),
    ("auf", "Área urbana", "text", "", "neutral", "auf", "Código del área urbana funcional (INE) a la que pertenece, si pertenece a alguna."),
    ("cell", "Hexágono", "int", "", "neutral", "gisco_lau", "Hexágono representativo del municipio en el mapa."),
]
COLUMNS = [f[0] for f in COUNTY_FIELDS]


def _r(x, nd=4):
    return None if x is None else round(x, nd)


def county_row(muni: dict, rec: dict | None, state: str, auf_id: str | None, cell: int) -> list:
    """One counties.json row. `rec` = the ine interim record of the municipality (None when absent)."""
    rec = rec or {}
    pop, pop21, area = rec.get("pop"), rec.get("pop_2021"), muni.get("area_km2")
    ps = rec.get("pct_spanish")
    p15, hed = rec.get("pop15"), rec.get("higher_ed")
    return [
        muni["code"], muni["name"], state, muni["province"], pop,
        _r(area, 1), round(pop / area) if pop is not None and area else None,
        _r(pop / pop21 - 1) if pop is not None and pop21 else None,
        rec.get("age_mean"), rec.get("pct65"), _r(1 - ps) if ps is not None else None, rec.get("hh_size"),
        rec.get("income_pp"), rec.get("below60"), _r(hed / p15) if hed is not None and p15 else None,
        auf_id, cell if cell >= 0 else None,
    ]


def build_counties(codes, muni_by_code, ine_m, ccaa_abbr, auf_of, cells, vintage) -> dict:
    rows = [county_row(muni_by_code[c], ine_m.get(c), ccaa_abbr[muni_by_code[c]["ccaa"]], auf_of.get(c), cells[i])
            for i, c in enumerate(codes)]
    return {
        "vintage": vintage, "attribution": ATTRIBUTION,
        "fields": [{"key": k, "label": lb, "format": fmt, "unit": u, "higher_is": h, "source": s, "description": d}
                   for k, lb, fmt, u, h, s, d in COUNTY_FIELDS],
        "columns": COLUMNS, "rows": rows,
    }


# --- districts.json ------------------------------------------------------------------------------------------

def specialisations(jobs: dict, nat_jobs: dict) -> tuple[int, list[dict]]:
    """(city employed with sections, [specialisation]) by the LQ rule. Pure: jobs/nat_jobs map section key -> int."""
    total = sum(v or 0 for v in jobs.values())
    nat_total = sum(v or 0 for v in nat_jobs.values())
    out = []
    if not total or not nat_total:
        return total, out
    for k in SECTION_KEYS:
        n, nat = jobs.get(k) or 0, nat_jobs.get(k) or 0
        if not n or not nat:
            continue
        lq = (n / total) / (nat / nat_total)
        if lq >= MIN_LQ and (n >= MIN_JOBS or n / total >= MIN_SHARE):
            out.append({"id": k, "lq": round(lq, 2), "emp": n, "share": round(n / total, 4),
                        "strength": round(n - n / lq), "via": "broad", "sub": None, "lower_bound": False,
                        "suppressed": 0})
    out.sort(key=lambda d: (-d["strength"], d["id"]))
    return total, out[:MAX_PER_CITY]


def badge_of(top: dict | None, names: dict) -> dict | None:
    if not top:
        return None
    return {"id": top["id"], "label": BADGE[top["id"]], "district": top["id"], "basis": "census",
            "text": f"{names[top['id']]}: {es(top['lq'])} veces el peso de España en ocupados residentes"}


_JOBS = f"{MIN_JOBS:,}".replace(",", ".")
RULE_TEXT = (
    f"Una especialización aparece cuando el peso de un sector en los ocupados que viven en la ciudad es al menos "
    f"{es(MIN_LQ, 2)} veces el peso que tiene en España (cociente de localización) y suma al menos {_JOBS} ocupados "
    f"o el {MIN_SHARE:.0%} de los ocupados de la ciudad. Se ordenan por los ocupados por encima de la media nacional "
    f"(ocupados menos ocupados dividido entre el cociente) y se muestran hasta {MAX_PER_CITY} por ciudad. Las secciones "
    f"T (hogares como empleadores) y U (organismos extraterritoriales) no cuentan. La etiqueta de la ciudad es la de su "
    f"primera especialización. Los ocupados se cuentan donde viven, no donde están las empresas."
)


def build_districts(cities: list[dict], nation: dict, names: dict, year) -> dict:
    nat_jobs = nation["nation"]["jobs"]
    out = {}
    for c in cities:
        total, spec = specialisations(c["jobs"], nat_jobs)
        out[c["id"]] = {"emp": total or None, "districts": spec, "badge": badge_of(spec[0] if spec else None, names)}
    catalog = [{
        "id": k, "name": names[k], "icon": "i-" + ICON_KEY[k], "color": COLORS[k], "sections": [k.upper()],
        "sub": {}, "badge": {"id": k, "label": BADGE[k], "labels": {}}, "description": DESCRIPTION[k], "caveat": None,
    } for k in SECTION_KEYS]
    return {
        "version": 1, "vintage": "INE, Censo anual de población 2024", "year": year, "sources": ["ine_jobs", "auf"],
        "note": NOTE,
        "rule": {"min_lq": MIN_LQ, "min_jobs": MIN_JOBS, "min_share": MIN_SHARE, "max_per_city": MAX_PER_CITY,
                 "excluded": [k.upper() for k in EXCLUDED], "text": RULE_TEXT},
        "catalog": catalog,
        "industries": {k: {"title": names[k], "us_emp": None, "emp": nat_jobs.get(k)} for k in SECTION_KEYS},
        "national": {"emp": sum(v or 0 for v in nat_jobs.values()), "avg_pay": None},
        "cities": out, "attribution": ATTRIBUTION,
    }


# --- citizens.json -------------------------------------------------------------------------------------------

def largest_remainder(values: list[float], n: int) -> list[int]:
    """Integers summing exactly to n, proportional to values (Hamilton's method)."""
    vals = [max(0.0, float(v or 0)) for v in values]
    tot = sum(vals)
    if tot <= 0 or n <= 0:
        return [0] * len(vals)
    q = [v * n / tot for v in vals]
    base = [int(x) for x in q]
    order = sorted(range(len(vals)), key=lambda i: (-(q[i] - base[i]), -vals[i], i))
    for i in order[: n - sum(base)]:
        base[i] += 1
    return base


GROUPS = {
    "age": [{"key": "under65", "label": "Menores de 65 años", "icon": "c-midlife"},
            {"key": "elder", "label": "65 años o más", "icon": "c-elder"}],
    "education": [{"key": "other", "label": "Sin estudios superiores", "icon": "c-edu2"},
                  {"key": "higher", "label": "Estudios superiores", "icon": "c-edu4"}],
    "nationality": [{"key": "spanish", "label": "Nacionalidad española", "icon": "c-local"},
                    {"key": "foreign", "label": "Nacionalidad extranjera", "icon": "c-immigrant"}],
}
ROWS = {"age": "Habitantes por edad", "education": "Habitantes de 15 años o más por estudios",
        "nationality": "Habitantes por nacionalidad"}
BASES = {"age": "Habitantes", "education": "Habitantes de 15 años o más", "nationality": "Habitantes"}
# distribution -> (second category key, count of the first category)
KEYS2 = {"age": ("under65", "elder"), "education": ("other", "higher"), "nationality": ("spanish", "foreign")}


def two_way(row: str, total: int, second: int) -> dict:
    """A two-category distribution; `second` = people in the second category of KEYS2[row]."""
    a, b = KEYS2[row]
    second = min(max(second, 0), total)
    s2 = round(second / total, 4)
    counts = {a: total - second, b: second}
    return {"base": BASES[row], "total": total, "counts": counts, "shares": {a: round(1 - s2, 4), b: s2},
            "figures": dict(zip((a, b), largest_remainder([counts[a], counts[b]], CITIZEN_FIGURES)))}


def citizens_of(codes: list[str], ine_m: dict) -> dict:
    """The three distributions for a set of municipalities (those with data only) and their coverage."""
    age = [0, 0]; edu = [0, 0]; nat = [0, 0]  # [total, second category]
    cov = {"age": [0, 0], "education": [0, 0], "nationality": [0, 0]}
    mean = [0.0, 0]
    for c in codes:
        r = ine_m.get(c) or {}
        pop = r.get("pop")
        for key in cov:
            cov[key][1] += 1
        if pop and r.get("pct65") is not None:
            age[0] += pop; age[1] += r["pct65"] * pop; cov["age"][0] += 1
        if pop and r.get("pct_spanish") is not None:
            nat[0] += pop; nat[1] += (1 - r["pct_spanish"]) * pop; cov["nationality"][0] += 1
        if r.get("pop15") and r.get("higher_ed") is not None:
            edu[0] += r["pop15"]; edu[1] += r["higher_ed"]; cov["education"][0] += 1
        if pop and r.get("age_mean") is not None:
            mean[0] += r["age_mean"] * pop; mean[1] += pop
    out = {}
    for key, (tot, second) in (("age", age), ("education", edu), ("nationality", nat)):
        out[key] = two_way(key, round(tot), round(second)) if tot else None
        if out[key]:
            out[key]["coverage"] = cov[key]
    if out["age"] and mean[1]:
        out["age"]["mean"] = round(mean[0] / mean[1], 1)
    return out


def build_citizens(cities: list[dict], ine_m: dict, all_codes: list[str]) -> dict:
    return {
        "version": 1, "vintage": "INE, Censo anual de población 2024", "year": 2024, "sources": ["ine"],
        "figures": {k: CITIZEN_FIGURES for k in GROUPS},
        "rows": ROWS, "bases": BASES, "groups": GROUPS,
        "rule": {"text": "Cada distribución usa su propia base: edad y nacionalidad sobre todos los habitantes, "
                         "estudios sobre los de 15 años o más. Se suman los municipios del área urbana con dato "
                         "(el número de municipios con dato está en `coverage`). Nacionalidad extranjera no es "
                         "lo mismo que nacido en el extranjero."},
        "national": {**citizens_of(all_codes, ine_m), "specialists": []},
        "cities": {c["id"]: {**citizens_of(c["counties"], ine_m), "specialists": [], "reliable": True} for c in cities},
        "attribution": ATTRIBUTION,
    }


# --- build ---------------------------------------------------------------------------------------------------

def build() -> None:
    import json
    from ..core.paths import WEB_DATA
    from ..sources._spain import CCAA

    world = json.loads((WEB_DATA / "world.json").read_text())
    cities = json.loads((WEB_DATA / "cities.json").read_text())
    nation_doc = json.loads((WEB_DATA / "nation.json").read_text())
    lau = load_interim("gisco_lau")
    ine = load_interim("ine")
    ine_m = ine["municipalities"]
    codes = [c["geoid"] for c in world["counties"]]
    muni_by_code = {m["code"]: m for m in lau["municipalities"]}
    abbr = {c["code"]: c["iso"] for c in CCAA}
    auf_of = {m: c["id"] for c in cities for m in c["counties"]}
    counties = build_counties(codes, muni_by_code, ine_m, abbr, auf_of, world["muni_cell"],
                              "INE: Censo anual de población 2026, renta y demografía 2024")
    write_web("counties.json", counties)
    names = nation_doc["industries"]
    districts = build_districts(cities, nation_doc, names, 2024)
    write_web("districts.json", districts)
    citizens = build_citizens(cities, ine_m, codes)
    write_web("citizens.json", citizens)

    # Report the numbers.
    counts: dict[str, int] = {}
    zero = 0
    for c in districts["cities"].values():
        if c["badge"]:
            counts[c["badge"]["id"]] = counts.get(c["badge"]["id"], 0) + 1
        else:
            zero += 1
    print("    badges per section: " + ", ".join(f"{k.upper()} {counts[k]}" for k in sorted(counts)) + f"; no badge {zero}")
    by_name = {fold(c["name"]): c for c in cities}
    for label in ("Madrid", "Barcelona", "Benidorm", "Vícar", "Huelva"):
        c = by_name.get(fold(label)) or next((x for x in cities if fold(label) in fold(x["name"])), None)
        b = districts["cities"][c["id"]] if c else None
        top = ", ".join(f"{d['id'].upper()} {d['lq']}" for d in b["districts"]) if b else "-"
        print(f"    {label}: {b['badge']['label'] if b and b['badge'] else 'sin etiqueta'} ({top})" if c else f"    {label}: not found")
    cov = citizens["national"]
    print(f"    citizens coverage (municipalities with data of {len(codes)}): age {cov['age']['coverage'][0]}, "
          f"education {cov['education']['coverage'][0]}, nationality {cov['nationality']['coverage'][0]}")
    short = [(c["name"], cz["education"]["coverage"]) for c in cities
             if (cz := citizens["cities"][c["id"]])["education"] and cz["education"]["coverage"][0] < cz["education"]["coverage"][1]]
    print(f"    {len(short)} cities with education covering fewer members than the city has"
          + (f" (e.g. {short[0][0]} {short[0][1][0]}/{short[0][1][1]})" if short else ""))
    print(f"    counties: {len(counties['rows'])} rows x {len(COLUMNS)} columns")
