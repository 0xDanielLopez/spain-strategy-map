"""Lenses = per-hex map overlays built from INE municipal data (and land cover).

Every municipality is spread over the hexes by AREA (world.py `muni_weights`: the share of its 1 km lattice points that
fall in each Spanish land hex), so each municipality's people are counted exactly once. For a hex h:

    hex_pop(h) = sum over municipalities m of f[m][h] * P[m]

Density = hex_pop / land km2 of the hex. Every other INE lens is a weighted mean (or a ratio of weighted sums) of the
municipal values in the hex, weighted by the people (or households, or population 15+) the municipality puts there.
A hex shows a value only when the municipalities that have it hold at least COVERAGE_MIN of the hex population.
Gini is not mapped: a mean of Ginis is not a Gini.
"""

from __future__ import annotations

import math

from ..core.store import load_interim, load_interim_payload, save_interim, write_web

REQUIRES = ["_world", "ine", "gisco_lau"]
PRODUCES = ["lenses.json", "_lens_stats"]  # counties.json is not built, see docs/DATA_CONTRACTS.md

COVERAGE_MIN = 0.9

GROUPS = [
    {"id": "people", "name": "Población"},
    {"id": "prosperity", "name": "Prosperidad"},
    {"id": "knowledge", "name": "Conocimiento"},
    {"id": "land", "name": "Territorio"},
]

ATTRIBUTION = [
    {"data": "población, renta, edad, hogares y estudios",
     "source": "INE: Censo anual de población, Atlas de distribución de renta de los hogares y Censo 2021-2024 (estudios)",
     "license": "Elaboración propia con datos extraídos del sitio web del INE: www.ine.es. El INE no participa, patrocina ni apoya esta reutilización."},
    {"data": "reparto por municipio",
     "source": "Eurostat GISCO, Unidades Administrativas Locales (LAU) 2024",
     "license": "© EuroGeographics para los límites administrativos. Solo uso no comercial."},
    {"data": "arbolado, cultivos y construido",
     "source": "ESA WorldCover 10 m 2021 v200",
     "license": "CC BY 4.0. © ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium."},
]

DOMAIN_NOTE = " Los colores cubren del percentil 2 al 98 de los hexágonos; los valores fuera de ese rango se dibujan con los colores de los extremos."
ALLOC_NOTE = " Cada municipio se reparte entre sus hexágonos por superficie."

# INE lens id -> (terms(rec) -> (numerator, denominator) or None, metadata). The hex value is sum(f*num) / sum(f*den)
# over the municipalities of the hex where terms() is not None (growth: minus 1). Population P is always rec["pop"].


def _pw(field):
    return lambda r: None if r.get("pop") is None or r.get(field) is None else (r["pop"] * r[field], r["pop"])


def _terms_growth(r):
    return None if r.get("pop") is None or not r.get("pop_2021") else (r["pop"], r["pop_2021"])


def _terms_foreign(r):
    return None if r.get("pop") is None or r.get("pct_spanish") is None else (r["pop"] * (1 - r["pct_spanish"]), r["pop"])


def _terms_household(r):
    hh = r.get("hh_size")
    return None if r.get("pop") is None or not hh or hh <= 0 else (r["pop"], r["pop"] / hh)  # households, not people


def _terms_higher_ed(r):
    return None if r.get("higher_ed") is None or not r.get("pop15") or r.get("pop") is None else (r["higher_ed"], r["pop15"])


INE_LENSES = {
    "growth": (_terms_growth, {
        "group": "people", "name": "Crecimiento de la población 2021-2026", "icon": "l-people", "emoji": "📈",
        "unit": "variación de la población", "format": "pct", "scale": "linear", "higher_is": "neutral", "source": "ine",
        "ramp": ["#0b2a2e", "#165a5c", "#2f8f83", "#7cc29a", "#d4ecb0", "#ffffe0"], "digits": 4,
        "description": "Variación de la población entre el 1 de enero de 2021 y el 1 de enero de 2026 (Censo anual de población, INE), con los municipios que tienen ambos datos.",
    }),
    "age": (_pw("age_mean"), {
        "group": "people", "name": "Edad media", "icon": "l-age", "emoji": "🎂",
        "unit": "años", "format": "float", "scale": "linear", "higher_is": "neutral", "source": "ine",
        "ramp": ["#00224e", "#35456c", "#666970", "#948e77", "#c8b866", "#fee838"], "digits": 1,
        "description": "Edad media de la población (Atlas de distribución de renta de los hogares, INE), ponderada por habitantes.",
    }),
    "elderly": (_pw("pct65"), {
        "group": "people", "name": "Mayores de 65 años", "icon": "l-age", "emoji": "👴",
        "unit": "% de la población", "format": "pct", "scale": "linear", "higher_is": "neutral", "source": "ine",
        "ramp": ["#1a0a2e", "#3f1d6b", "#6a3fa0", "#9a72c9", "#c9a9e6", "#f3e8ff"], "digits": 4,
        "description": "Porcentaje de población de 65 y más años (Atlas de distribución de renta de los hogares, INE).",
    }),
    "foreign": (_terms_foreign, {
        "group": "people", "name": "Nacionalidad extranjera", "icon": "l-foreign-born", "emoji": "🌍",
        "unit": "% de la población", "format": "pct", "scale": "linear", "higher_is": "neutral", "source": "ine",
        "ramp": ["#0b0405", "#382a54", "#395d9c", "#3497a9", "#60ceac", "#def5e5"], "digits": 4,
        "description": "Porcentaje de población sin nacionalidad española (Atlas de distribución de renta de los hogares, INE).",
    }),
    "household": (_terms_household, {
        "group": "people", "name": "Tamaño medio del hogar", "icon": "l-home", "emoji": "🏠",
        "unit": "personas", "format": "float", "scale": "linear", "higher_is": "neutral", "source": "ine",
        "ramp": ["#1c1a05", "#45410f", "#76701d", "#a8a033", "#d4ce62", "#f8f6c4"], "digits": 2,
        "description": "Personas por hogar (Atlas de distribución de renta de los hogares, INE). El promedio se pondera por hogares, no por personas.",
    }),
    "income": (_pw("income_pp"), {
        "group": "prosperity", "name": "Renta neta media por persona", "icon": "l-income-eur", "emoji": "💶",
        "unit": "€", "format": "eur", "scale": "linear", "higher_is": "good", "source": "ine",
        "ramp": ["#3a1c0b", "#7a4413", "#b8781f", "#e3b23c", "#f6e27f", "#fffbe0"], "digits": 0,
        "note": "Atlas de renta del INE: renta de los hogares por persona, sin establecimientos colectivos.",
        "description": "Renta neta media por persona (Atlas de distribución de renta de los hogares, INE), ponderada por habitantes.",
    }),
    "poverty": (_pw("below60"), {
        "group": "prosperity", "name": "Población bajo el 60 % de la mediana", "icon": "l-poverty", "emoji": "🥣",
        "unit": "% de la población", "format": "pct", "scale": "linear", "higher_is": "bad", "source": "ine",
        "ramp": ["#03051a", "#4c1d4b", "#a11a5b", "#e83f3f", "#f69c73", "#faebdd"], "digits": 4,
        "description": "Porcentaje de población con ingresos por unidad de consumo por debajo del 60 % de la mediana nacional (Atlas de distribución de renta de los hogares, INE).",
        "note": "Sin dato en muchos municipios pequeños: el INE lo oculta por secreto estadístico.",
    }),
    "higher_education": (_terms_higher_ed, {
        "group": "knowledge", "name": "Estudios superiores (15 años o más)", "icon": "l-degrees", "emoji": "🎓",
        "unit": "% de la población de 15 años o más", "format": "pct", "scale": "linear", "higher_is": "good", "source": "ine",
        "ramp": ["#08203e", "#0f4c81", "#2a7fc1", "#5fa8e0", "#a6d1f2", "#eaf5ff"], "digits": 4,
        "note": "El INE solo publica el nivel de estudios de municipios de 500 habitantes o más.",
        "description": "Población de 15 años o más con educación superior sobre el total de esa edad (Censo 2021-2024, INE).",
    }),
}

LAND_LENSES = {
    "forest": ("forest", {
        "name": "Arbolado", "icon": "l-forest", "emoji": "🌲",
        "ramp": ["#0b1f0f", "#14401c", "#1f6b2b", "#3a9443", "#7fc07a", "#d5efcd"],
        "description": "Porcentaje de la tierra del hexágono cubierto de arbolado (clase 10 de ESA WorldCover).",
        "note": "Los olivares y otros cultivos leñosos pueden salir como arbolado.",
    }),
    "farmland": ("crop", {
        "name": "Cultivos", "icon": "l-farmland", "emoji": "🚜",
        "ramp": ["#141d05", "#2f4510", "#557019", "#84a02a", "#b8cf55", "#eef7b8"],
        "description": "Porcentaje de la tierra del hexágono dedicado a cultivos (clase 40 de ESA WorldCover).",
        "note": "Los olivares pueden salir como arbolado y los invernaderos como construido, no como cultivo.",
    }),
    "developed": ("developed", {
        "name": "Construido", "icon": "l-developed", "emoji": "🏙️",
        "ramp": ["#121218", "#2c2c3c", "#4b4b66", "#727294", "#a3a3c2", "#e2e2f0"],
        "description": "Porcentaje de la tierra del hexágono que es suelo construido (clase 50 de ESA WorldCover).",
        "note": "Los invernaderos pueden salir como construido.",
    }),
}


def nice(v: float, up: bool) -> float:
    """v rounded outward (up or down) to 2 significant digits."""
    if v == 0:
        return 0
    mag = 10 ** (math.floor(math.log10(abs(v))) - 1)
    return round((math.ceil if up else math.floor)(v / mag) * mag, 10)


def percentile_domain(values: list, log: bool) -> list[float] | None:
    """[2nd, 98th] percentile of the non-null hex values, rounded outward; positive values only on a log scale."""
    vals = sorted(v for v in values if v is not None and (v > 0 or not log))
    if not vals:
        return None
    lo, hi = vals[int(0.02 * (len(vals) - 1))], vals[int(0.98 * (len(vals) - 1))]
    lo, hi = nice(lo, False), nice(hi, True)
    return [lo, hi] if hi > lo else [lo, nice(vals[-1], True)]


def hex_pop(parts: list, recs: list) -> float:
    return sum(f * recs[k]["pop"] for k, f in parts if recs[k].get("pop") is not None)


def hex_density(parts: list, recs: list, land_km2: float) -> float | None:
    """People per km2 of land; null without land area or when municipalities without a population hold > 10 % of the hex."""
    if land_km2 <= 0:
        return None
    have = sum(f for k, f in parts if recs[k].get("pop") is not None)
    if not parts or have < COVERAGE_MIN * sum(f for _, f in parts):
        return None
    return hex_pop(parts, recs) / land_km2


def hex_ratio(parts: list, recs: list, terms) -> float | None:
    """sum(f*num) / sum(f*den) over the municipalities with a value, or None when they hold < COVERAGE_MIN of hex_pop."""
    total = hex_pop(parts, recs)
    if total <= 0:
        return None
    num = den = covered = 0.0
    for k, f in parts:
        t = terms(recs[k])
        if t is None:
            continue
        num += f * t[0]
        den += f * t[1]
        covered += f * recs[k]["pop"]
    if den <= 0 or covered < COVERAGE_MIN * total:
        return None
    return num / den


def round_to(v: float | None, digits: int):
    if v is None:
        return None
    return int(round(v)) if digits == 0 else round(v, digits)


def build() -> None:
    world = load_interim("_world")
    ine = load_interim("ine")
    lau = load_interim("gisco_lau")
    weights = world["muni_weights"]
    land_km2 = world["land_km2"]
    owner = world["owner"]
    n = len(owner)
    by_code = ine["municipalities"]
    recs = [by_code.get(code) or {} for code in world["counties"]]
    lau_by_code = {m["code"]: m for m in lau["municipalities"]}
    ccaa_codes = world["states"]
    ccaa_of = [ccaa_codes.index(lau_by_code[c]["ccaa"]) for c in world["counties"]]

    values: dict[str, list] = {"density": [None] * n}
    for lid in INE_LENSES:
        values[lid] = [None] * n
    pops = [0.0] * n
    for i, parts in enumerate(weights):
        if owner[i] < 0 or not parts:
            continue
        pops[i] = hex_pop(parts, recs)
        values["density"][i] = hex_density(parts, recs, land_km2[i])
        for lid, (terms, meta) in INE_LENSES.items():
            v = hex_ratio(parts, recs, terms)
            if v is not None and lid == "growth":
                v -= 1
            values[lid][i] = round_to(v, meta["digits"])
    values["density"] = [None if v is None else round(v, 1) for v in values["density"]]

    # Conservation: the people on the hexes against the municipal totals, nationally and per CCAA (read by check).
    muni_pop = sum(r["pop"] for r in recs if r.get("pop") is not None)
    hex_total = sum(pops)
    per_ccaa = {c: {"muni_pop": 0.0, "hex_pop": 0.0} for c in ccaa_codes}
    for k, r in enumerate(recs):
        if r.get("pop") is not None:
            per_ccaa[ccaa_codes[ccaa_of[k]]]["muni_pop"] += r["pop"]
    for i in range(n):
        if owner[i] >= 0:
            per_ccaa[ccaa_codes[owner[i]]]["hex_pop"] += pops[i]
    save_interim("_lens_stats", {"muni_pop": muni_pop, "hex_pop": hex_total, "per_ccaa": per_ccaa, "coverage_min": COVERAGE_MIN})
    print(f"    population on hexes {hex_total:,.0f} of {muni_pop:,.0f} ({hex_total / muni_pop:.4%})")

    lenses = [{
        "id": "density", "group": "people", "name": "Densidad de población", "icon": "l-people", "emoji": "👥",
        "unit": "hab./km²", "format": "int", "scale": "log",
        "ramp": ["#1b1035", "#4b2377", "#9a3b8a", "#e0645e", "#f9b24a", "#fff3a8"], "higher_is": "neutral", "source": "ine",
        "note": "Población repartida por superficie dentro de cada municipio: supone densidad uniforme en el término municipal.",
        "description": "Habitantes por km² de tierra (Censo anual de población, INE, 1 de enero de 2026).",
        "values": values["density"],
    }]
    for lid, (_, meta) in INE_LENSES.items():
        meta = {k: v for k, v in meta.items() if k != "digits"}
        lenses.append({"id": lid, **meta, "values": values[lid]})
    pct = world.get("pct")
    if pct:
        cover = world.get("cover") or [1] * n  # cover 0 = no land-cover samples: no data, not 0 %
        for lid, (key, meta) in LAND_LENSES.items():
            lenses.append({
                "id": lid, "group": "land", **meta, "unit": "% de la tierra", "format": "pct", "scale": "linear",
                "higher_is": "neutral", "source": "worldcover",
                "values": [round(pct[key][i] / 100, 2) if owner[i] >= 0 and cover[i] else None for i in range(n)],
            })
    for lens in lenses:
        lens["domain"] = percentile_domain(lens["values"], lens["scale"] == "log")
        lens["description"] += (ALLOC_NOTE if lens["source"] == "ine" else "") + DOMAIN_NOTE
    groups = [g for g in GROUPS if any(l["group"] == g["id"] for l in lenses)]
    write_web("lenses.json", {"vintage": load_interim_payload("ine")["vintage"], "attribution": ATTRIBUTION, "groups": groups, "lenses": lenses})
    spanish = sum(1 for o in owner if o >= 0)
    for lens in lenses:
        k = sum(1 for v in lens["values"] if v is not None)
        print(f"    {lens['id']:17} {k:5} hexes ({k / spanish:.1%} of {spanish})  domain {lens['domain']}")
