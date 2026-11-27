"""Transparency files for the "Transparencia" advisor: safety.json, boja.json and contracts_junta.json.

Only codes, public-body names and numbers: no winners, no tax ids, no person names, no notice texts (the sources
never read them, and `check.privacy_violations` is asserted on every file before it is written).

* safety.json: Interior's Balance de Criminalidad, closings 2024 and 2025. `typologies` lists the 19 rows; the ones with
  `total` already includes every other row (`conventional` + `cybercrime`, and the rest are parts of those): never sum the typologies.
  National, CCAA (by abbreviation), province (2-digit INE code) and the 427 towns above 20,000 inhabitants (5-digit INE code).
  `population` is the Censo anual 2026 (1 January), not the year of the facts: said in `note`.
* boja.json: dispositions per year, section and issuing body (BOJA open-data API; counts only).
* contracts_junta.json: minor contracts of the Junta de Andalucía per year, province and body (aggregates).
"""

from __future__ import annotations

import re

from ..check import privacy_violations
from ..core.store import load_interim, load_interim_payload, write_web
from ..sources._spain import CCAA

REQUIRES = ["_world", "gisco_lau", "ine", "interior_crime", "boja", "junta_menores"]
PRODUCES = ["safety.json", "boja.json", "contracts_junta.json"]

POP_YEAR = 2026
TOP_ORGS = 80  # bodies kept in boja.json (by total dispositions)
TOP_ORGANS = 60  # bodies kept in contracts_junta.json (by amount of the latest year)
# Informational flag only: `total` already holds everything, so the web reads `total` and never sums typologies.
NON_ADDITIVE = {"total", "sexual_aggression_penetration", "sexual_other", "burglary_dwellings", "cybercrime"}
# BOJA announcement issuers can be private parties: only names that look like a public body keep their name.
PUBLIC_BODY = re.compile(
    r"^(consejer|ayuntamient|diputaci|universidad|agencia|servicio andaluz|delegaci|instituto|junta|parlamento|defensor|"
    r"c[aá]mara de cuentas|consorcio|mancomunidad|tribunal|presidencia|ministerio|administraci|gerencia|"
    r"audiencia|fiscal|consejo|comisi|centro|escuela|empresa p[uú]blica|entidad|ente |organismo|oficina|"
    r"secretar|viceconsejer|direcci[oó]n general|subdelegaci|confederaci[oó]n hidrogr|patronato|comunidad aut|"
    r"juzgado|registro|junta electoral|real academia|ayuntamientos)",
    re.I,
)
OTHER_ORG = "Otros emisores (no se publican nombres de particulares ni empresas)"
SECTION_LABELS = {"mixto": "Varias secciones", "sin_seccion": "Sin sección"}
SPECIAL_PROVINCES = ("sin_provincia", "otros")


def _attr(sid: str, data: str, source: str | None = None) -> dict:
    from ..sources import BY_ID
    info = BY_ID[sid].info
    return {"data": data, "source": source or f"{info.publisher}: {info.title}", "license": info.license}


def build_safety(crime: dict, ine_m: dict, lau: dict, abbr_by_code: dict, retrieved: str) -> dict:
    years = crime["years"]
    prov_of = {m["code"]: m["province"] for m in lau["municipalities"]}
    ccaa_of = {m["code"]: m["ccaa"] for m in lau["municipalities"]}
    pop_prov: dict[str, int] = {}
    pop_ccaa: dict[str, int] = {}
    for code, r in ine_m.items():
        if r.get("pop") is None or code not in prov_of:
            continue
        pop_prov[prov_of[code]] = pop_prov.get(prov_of[code], 0) + r["pop"]
        pop_ccaa[ccaa_of[code]] = pop_ccaa.get(ccaa_of[code], 0) + r["pop"]
    national_pop = sum(pop_prov.values())

    def block(src: dict, pop: int | None, with_name=True) -> dict:
        out = {"name": src["name"]} if with_name else {}
        if pop is not None:
            out["population"] = pop
        for y in years:
            if y in src:
                out[y] = src[y]
        return out

    national = block(crime["provinces"]["ES"], national_pop, with_name=False)
    national["population_year"] = POP_YEAR
    ccaa = {abbr_by_code[k]: block(v, pop_ccaa.get(k)) for k, v in crime["ccaa"].items() if k in abbr_by_code}
    provinces = {k: block(v, pop_prov.get(k)) for k, v in crime["provinces"].items() if k != "ES"}
    munis = {k: block(v, (ine_m.get(k) or {}).get("pop")) for k, v in sorted(crime["municipalities"].items())}
    return {
        "vintage": crime.get("vintage") or "Balance de Criminalidad 2024-2025",
        "updated": retrieved,
        "years": years,
        "typologies": [{**t, "additive": t["key"] not in NON_ADDITIVE} for t in crime["typologies"]],
        "note": ("Hechos conocidos por las fuerzas de seguridad en cada año, no condenas ni personas. Solo hay municipios de más "
                 "de 20.000 habitantes. La población es la del Censo anual a 1 de enero de 2026 (INE), no la de cada año de los "
                 "hechos, y no incluye a quien visita o trabaja en el municipio. Las cifras de 2024 son las que el cierre de "
                 "2025 publica de nuevo, y pueden diferir del cierre de 2024."),
        "attribution": [_attr("interior_crime", "infracciones penales por tipo, municipio, provincia y comunidad",
                              "Ministerio del Interior, Portal Estadístico de Criminalidad, Balance de Criminalidad"),
                        {"data": "población", "source": "INE: Censo anual de población 2026",
                         "license": "Elaboración propia con datos extraídos del sitio web del INE: www.ine.es. El INE no participa, patrocina ni apoya esta reutilización."}],
        "national": national, "ccaa": ccaa, "provinces": provinces, "municipalities": munis,
    }


def build_boja(b: dict) -> dict:
    years = sorted(b["years"])
    sec_ids = sorted({s for y in years for s in b["years"][y]["by_section"]})
    names = {**b["section_names"], **SECTION_LABELS}
    by_org: dict[str, dict[str, int]] = {}
    for y in years:
        for org, secs in b["years"][y]["by_org"].items():
            org = " ".join(org.replace("\xa0", " ").split())  # the API mixes plain and non-breaking spaces
            name = org if PUBLIC_BODY.match(org) else OTHER_ORG
            d = by_org.setdefault(name, {})
            d[y] = d.get(y, 0) + sum(secs.values())
    ranked = sorted(by_org.items(), key=lambda kv: (kv[0] == OTHER_ORG, -sum(kv[1].values()), kv[0]))
    return {
        "vintage": b.get("retrieved") and f"BOJA {years[0]}-{years[-1]}, hasta {b['retrieved']}" or f"BOJA {years[0]}-{years[-1]}",
        "updated": b.get("retrieved"),
        "years": years,
        "sections": [{"id": s, "name": names.get(s, s)} for s in sec_ids],
        "by_year_section": {y: dict(sorted(b["years"][y]["by_section"].items())) for y in years},
        "by_organisation": [{"name": n, "counts": c} for n, c in ranked[:TOP_ORGS]],
        "note": (f"Recuento de disposiciones publicadas en el BOJA, sin títulos ni textos. El último año ({years[-1]}) llega hasta "
                 f"{b.get('retrieved')}. Un emisor que no es un organismo público se agrupa en «Otros emisores»."),
        "attribution": [_attr("boja", "disposiciones del BOJA por año, sección y organismo", "Junta de Andalucía, Boletín Oficial de la Junta de Andalucía (datos abiertos)")],
    }


def build_junta(j: dict) -> dict:
    years = sorted(j["years"])
    provinces: dict[str, dict] = {}
    unassigned: dict[str, dict] = {}
    for y in years:
        for code, a in j["years"][y]["provinces"].items():
            row = {"n": a["n"], "amount": round(a["amount_sin_iva"], 2) if a["n_amount"] else None,
                   "single_bidder": a["n_single_bidder"], "bidders_known": a["n_bidders_known"],
                   "under_15k": a["n_lt_15000"], "under_40k": a["n_lt_40000"],
                   "band_15k": a["n_band_15000"], "band_40k": a["n_band_40000"]}
            if code in SPECIAL_PROVINCES:
                unassigned.setdefault(code, {})[y] = row
            else:
                provinces.setdefault(code, {"name": j["province_codes"].get(code)})[y] = row
    organs: dict[str, dict] = {}
    for y in years:
        for name, a in j["years"][y]["organs"].items():
            organs.setdefault(name, {})[y] = {"n": a["n"], "amount": round(a["amount_sin_iva"], 2) if a["n_amount"] else None}
    last = years[-1]
    ranked = sorted(organs.items(), key=lambda kv: (-(kv[1].get(last, {}).get("amount") or 0), kv[0]))
    return {
        "vintage": j.get("vintage") or "Contratación menor Junta de Andalucía", "updated": None, "years": years,
        "amount_basis": "de adjudicación, sin IVA",
        "year_meaning": j["year_meaning"],
        "thresholds_eur": j["thresholds_eur"],
        "provinces": provinces, "unassigned": unassigned,
        "organs": [{"name": n, "by_year": by} for n, by in ranked[:TOP_ORGANS]],
        "note": ("Agregados de contratos menores de la Junta de Andalucía por provincia de ejecución y órgano de contratación; no se "
                 "publican adjudicatarios, títulos ni personas. El año es el del fichero que publica la Junta. «Un solo licitador» "
                 "cuenta los contratos con una única oferta sobre el total de contratos; los tramos son contratos por debajo de "
                 "15.000 y 40.000 euros, y los «cerca del umbral» son los que están en el 6,7 % inmediatamente inferior."),
        "attribution": [_attr("junta_menores", "contratos menores", "Junta de Andalucía, Contratación menor (datos abiertos)")],
    }


def build() -> None:
    abbr = {c["code"]: c["iso"] for c in CCAA}
    ine_m = load_interim("ine")["municipalities"]
    lau = load_interim("gisco_lau")
    crime_payload = load_interim_payload("interior_crime")
    safety = build_safety(crime_payload["data"], ine_m, lau, abbr, (crime_payload.get("processed") or "")[:10])
    boja = build_boja(load_interim("boja"))
    junta_payload = load_interim_payload("junta_menores")
    junta = build_junta({**junta_payload["data"], "vintage": junta_payload.get("vintage")})
    junta["updated"] = (junta_payload.get("processed") or "")[:10]
    for name, doc in (("safety.json", safety), ("boja.json", boja), ("contracts_junta.json", junta)):
        bad = privacy_violations(doc)
        if bad:
            raise AssertionError(f"{name}: possible personal data, not written: {bad[:5]}")
        write_web(name, doc)
    nat = safety["national"]
    print(f"    safety: {len(safety['municipalities'])} towns, {len(safety['provinces'])} provinces, {len(safety['ccaa'])} CCAA; "
          f"national total 2025 {nat['2025']['total']:,}")
    print(f"    boja: {len(boja['years'])} years, {sum(boja['by_year_section'][y].get('1', 0) for y in boja['years'])} general provisions; "
          f"{len(boja['by_organisation'])} bodies; others {boja['by_organisation'][-1]['name'][:20] if boja['by_organisation'] else '-'}")
    print(f"    contracts_junta: {len(junta['provinces'])} provinces, {len(junta['organs'])} bodies, years {junta['years']}")
