"""Public procurement of Spanish town halls in 2025, from the Plataforma de Contratacion del Sector Publico.

Source: PLACSP open data (Atom feeds with CODICE/UBL entries), the yearly ZIPs of the "perfiles del contratante"
(without minor contracts) and of the aggregated regional platforms (without minor contracts). Reuse with attribution.
The ZIPs hold ~24 GB of XML: they are NEVER extracted; every member is streamed with zipfile + iterparse.

Scope: town halls = DIR3 code "L01" + 5-digit INE municipality + 1 check character. Bodies without DIR3 whose NIF
starts with "P" are only counted ("unmatched_p"); their municipality is not guessed.
Only the LATEST version of each entry (key = entry <id>, by <updated>) counts. A tender seen in both ZIPs under the
same (DIR3, ContractFolderID) is kept once (the newest version).

Code lists (read from the official CODICE lists, checked against the data):
  TenderResultCode 2.09  AWARDED_RESULT_CODES = 2 (finally awarded), 8 (awarded), 9 (formalised) count as awarded.
                         1 provisional, 3 void, 4 abandoned, 5 revoked, 6/7 void, 10 best rated and 11 "encargo"
                         (in-house assignment, no competition) do NOT count; they are only tallied in stats.
  ProcedureCode 2.07     OPEN_PROCEDURE_CODES = 1 (open) and 9 (simplified open).
  ContractCode 2.08      TypeCode 3 works, 2 services, 1 supplies, 21/22/31/32 concessions, rest other.

PRIVACY (one function, publishable_winner): a winner is published only with a valid legal-entity NIF. Everything
else is quarantined: it still counts in totals, but its name and id are discarded at read time and never stored,
logged or written. No contact data, no descriptions, no attachments; only the tender title (and only when it is
safe) of the top rows.
"""

from __future__ import annotations

import os
import re
import unicodedata
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from ..core.paths import INTERIM, RAW
from ..core.source import Source, SourceInfo

BULK_DIR = "placsp_bulk"
ZIPS = {
    "perfiles": "licitacionesPerfilesContratanteCompleto3_2025.zip",
    "agregadas": "PlataformasAgregadasSinMenores_2025.zip",
}
URLS = {
    "perfiles": "https://contrataciondelestado.es/sindicacion/sindicacion_643/licitacionesPerfilesContratanteCompleto3_2025.zip",
    "agregadas": "https://contrataciondelestado.es/sindicacion/sindicacion_1044/PlataformasAgregadasSinMenores_2025.zip",
}
YEAR = 2025
AWARDED_RESULT_CODES = {"2", "8", "9"}
OPEN_PROCEDURE_CODES = {"1", "9"}
TYPE_LABELS = {"3": "works", "2": "services", "1": "supplies", "21": "concessions", "22": "concessions",
               "31": "concessions", "32": "concessions"}
TOP_N = 10
TITLE_MAX = 160
NAME_MAX = 120

NIF_RE = re.compile(r"^[ABCDFGNPQRSW][0-9]{7}[0-9A-J]$")
# Personal markers. All of them run on text that went through clean_text() (NFKC, no zero-width characters, single
# spaces). False positives only remove a row from "top" (its amounts stay in the totals), so the patterns are greedy.
PERSON_TITLE_RE = re.compile(
    r"(?<![A-Za-zÁÉÍÓÚÑáéíóúñ])(?:"
    # abbreviations: the name may follow with no space ("D.Juan", "Dª Ana", "D.ª Ana")
    r"(?:D\.\s*[ªº]?|D[ªº]\.?|Dña\.|Dna\.|Sr\.|Sra\.|Srta\.|Hnos\.|Vda\.)\s*"
    # whole words: a space must follow, so "Dones" or "Donosti" do not match
    r"|(?:Dña|Don|Doña|Sr|Sra|Srta|Señor|Señora|Señorita|Hnos|Hermanos|Herederos\s+de|Hijos\s+de|Viuda\s+de|Vda\s+de)\s+"
    r")(?=[A-Za-zÁÉÍÓÚÑáéíóúñ])",
    re.IGNORECASE,
)
# DNI 12345678Z, 12.345.678-Z, 12 345 678 Z; NIE X1234567L; K/L/M NIFs; any of them with separators or in lower case.
DNI_NIE_RE = re.compile(
    r"(?<![0-9])[0-9]{1,2}[. ]?[0-9]{3}[. ]?[0-9]{3}[ .\-]?[A-Za-z](?![A-Za-z0-9])"
    r"|(?<![A-Za-z0-9])[XYZKLMxyzklm][ .\-]?[0-9]{7}[ .\-]?[A-Za-z](?![A-Za-z0-9])"
    r"|\*{2,}[0-9]{2,6}\*+"
)
CONTACT_RE = re.compile(
    r"@|https?://|www\."
    r"|(?<![0-9])(?:\+34[ .\-]?)?[6789][0-9]{2}[ .\-]?[0-9]{2,3}[ .\-]?[0-9]{2,3}(?:[ .\-]?[0-9]{2})?(?![0-9])",
    re.IGNORECASE,
)
ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff\u00ad]")
# The 16 municipalities whose own name carries "Don"/"Doña": removed from TITLES (never from winner names) before the
# personal-title test. The three bare forms do not count when a capitalised word follows ("Don Benito Falso").
PLACE_WITH_TITLE_RE = re.compile(
    r"(?:Casas\s+de\s+Don\s+(?:Pedro|Antonio|G[óo]mez)|Torre\s+de\s+Don\s+Miguel|Puebla\s+de\s+Don\s+(?:Rodrigo|Fadrique)"
    r"|Valencia\s+de\s+Don\s+Juan|Villamart[íi]n\s+de\s+Don\s+Sancho|Castrillo\s+de\s+Don\s+Juan"
    r"|Calzada\s+de\s+Don\s+Diego|Cubo\s+de\s+Don\s+Sancho|Villa\s+de\s+Don\s+Fadrique|Almunia\s+de\s+Do[ñn]a\s+Godina)"
    r"|(?:Don\s+Benito|Don\s+[ÁA]lvaro|Do[ñn]a\s+Menc[íi]a)(?!\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ])",
)
# CIF control: these entity letters carry a letter, these a digit (the rest may carry either).
CONTROL_LETTER, CONTROL_DIGIT = set("NPQRSW"), set("AB")
DIR3_RE = re.compile(r"^L01([0-9]{5})[0-9A-Z]$")


# ------------------------------------------------------------------ privacy

def cif_control_ok(nif: str) -> bool:
    """Official CIF check on an already normalised NIF matching NIF_RE."""
    digits = [int(c) for c in nif[1:8]]
    total = 0
    for pos, d in enumerate(digits, start=1):
        if pos % 2 == 0:
            total += d
        else:
            total += sum(int(c) for c in str(2 * d))
    control = (10 - total % 10) % 10
    digit, letter = str(control), "JABCDEFGHI"[control]
    if nif[0] in CONTROL_LETTER:
        return nif[8] == letter
    if nif[0] in CONTROL_DIGIT:
        return nif[8] == digit
    return nif[8] in (digit, letter)


def normalize_nif(raw: str | None) -> str:
    return re.sub(r"[\s.\-]", "", raw or "").upper()


def clean_text(s: str | None) -> str:
    """NFKC, no zero-width or bidi characters, single spaces."""
    s = (s or "").replace("ª", "\ue000").replace("º", "\ue001")  # NFKC would fold them into "a"/"o" ("Dª" -> "Da")
    s = ZERO_WIDTH_RE.sub("", unicodedata.normalize("NFKC", s)).replace("\ue000", "ª").replace("\ue001", "º")
    return re.sub(r"\s+", " ", s).strip()


def has_personal_marker(s: str, titles: bool = True, places: bool = False) -> bool:
    """True if the text carries an identity document, contact data or (titles=True) a personal form of address.
    places=True first removes the municipality names that contain "Don"/"Doña"."""
    if DNI_NIE_RE.search(s) or CONTACT_RE.search(s):
        return True
    if not titles:
        return False
    return bool(PERSON_TITLE_RE.search(PLACE_WITH_TITLE_RE.sub(" ", s) if places else s))


def safe_body(name: str | None) -> str | None:
    """Name of the public body, or None if it carries an identity document or contact data. Titles are not tested:
    town names such as Don Benito are legitimate here."""
    b = clean_text(name)
    return None if not b or has_personal_marker(b, titles=False) else b[:NAME_MAX]


def publishable_winner(raw_id: str | None, name: str | None):
    """The ONLY place that decides publishable vs quarantine. Returns (name, nif) or None (quarantine)."""
    nif = normalize_nif(raw_id)
    if not NIF_RE.match(nif) or not cif_control_ok(nif):
        return None
    clean = clean_text(name)
    if not clean or has_personal_marker(clean):
        return None
    return clean[:NAME_MAX], nif


def safe_title(title: str | None) -> str | None:
    """Tender title usable in a public row, or None (personal-title or DNI/NIE pattern)."""
    t = clean_text(title)
    if not t or has_personal_marker(t, places=True):
        return None
    return t[:TITLE_MAX]


# ------------------------------------------------------------------ XML helpers

def ln(tag: str) -> str:
    return tag.rpartition("}")[2]


def kids(el, name):
    return [c for c in el if ln(c.tag) == name]


def kid(el, name):
    for c in el:
        if ln(c.tag) == name:
            return c
    return None


def path(el, *names):
    for n in names:
        if el is None:
            return None
        el = kid(el, n)
    return el


def text(el) -> str:
    return (el.text or "").strip() if el is not None else ""


def to_float(s: str):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def to_int(s: str):
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def stamp(updated: str) -> int:
    """ISO timestamp -> sortable int (local time, enough to order versions)."""
    digits = re.sub(r"\D", "", (updated or "")[:19])
    return int(digits) if digits else 0


# ------------------------------------------------------------------ entry parsing

def parse_entry(entry):
    """One <entry> -> dict (or None without ContractFolderStatus). Winner names/ids are decided here and dropped."""
    cfs = kid(entry, "ContractFolderStatus")
    if cfs is None:
        return None
    eid = text(kid(entry, "id"))
    updated = stamp(text(kid(entry, "updated")))
    link_el = kid(entry, "link")
    link = link_el.get("href", "") if link_el is not None else ""

    dir3 = nif = ""
    body = ""
    lcp = kid(cfs, "LocatedContractingParty")
    party = kid(lcp, "Party") if lcp is not None else None
    if party is not None:
        for pid in kids(party, "PartyIdentification"):
            idel = kid(pid, "ID")
            scheme = idel.get("schemeName", "") if idel is not None else ""
            if scheme == "DIR3" and not dir3:
                dir3 = text(idel).upper()
            elif scheme == "NIF" and not nif:
                nif = normalize_nif(text(idel))
        body = safe_body(text(path(party, "PartyName", "Name"))) or ""
    out = {"id": eid, "updated": updated, "dir3": dir3, "nif": nif, "body": body, "link": link,
           "folder": text(kid(cfs, "ContractFolderID")), "results": []}
    m = DIR3_RE.match(dir3)
    if not m:
        return out  # not a town hall: nothing else is needed

    proj = kid(cfs, "ProcurementProject")
    out["type"] = TYPE_LABELS.get(text(kid(proj, "TypeCode")) if proj is not None else "", "other")
    out["procedure"] = text(path(cfs, "TenderingProcess", "ProcedureCode"))
    tender_cpv = text(path(proj, "RequiredCommodityClassification", "ItemClassificationCode")) if proj is not None else ""
    title = text(kid(proj, "Name")) if proj is not None else ""
    lot_cpv = {}
    for lot in kids(cfs, "ProcurementProjectLot"):
        lid = text(kid(lot, "ID"))
        cpv = text(path(lot, "ProcurementProject", "RequiredCommodityClassification", "ItemClassificationCode"))
        if lid and cpv:
            lot_cpv[lid] = cpv
    results = {}
    for i, tr in enumerate(kids(cfs, "TenderResult")):
        code = text(kid(tr, "ResultCode"))
        date = text(kid(tr, "AwardDate"))[:10]
        year = to_int(date[:4]) if date else None
        offers = to_int(text(kid(tr, "ReceivedTenderQuantity")))
        lid = text(path(tr, "AwardedTenderedProject", "ProcurementProjectLotID"))
        amount = to_float(text(path(tr, "AwardedTenderedProject", "LegalMonetaryTotal", "TaxExclusiveAmount")))
        winner = None
        if code in AWARDED_RESULT_CODES and year == YEAR:
            wp = kid(tr, "WinningParty")
            raw_id = raw_name = ""
            if wp is not None:
                ids = kids(wp, "PartyIdentification")
                pick = next((x for x in ids if kid(x, "ID") is not None and kid(x, "ID").get("schemeName") == "NIF"), None)
                if pick is None and ids:
                    pick = ids[0]
                raw_id = text(kid(pick, "ID")) if pick is not None else ""
                raw_name = text(path(wp, "PartyName", "Name"))
            winner = publishable_winner(raw_id, raw_name)  # raw_id / raw_name go out of scope here
            raw_id = raw_name = ""
        res = {"code": code, "year": year, "date": date, "offers": offers, "amount": amount, "winner": winner,
               "cpv": lot_cpv.get(lid) or tender_cpv}
        results[lid if lid else f"#{i}"] = res  # same lot twice in one entry: keep the last
    out["results"] = list(results.values())
    out["title"] = safe_title(title) if any(r["winner"] for r in out["results"]) else None
    out["ine"] = m.group(1)
    return out


# ------------------------------------------------------------------ streaming

def pick_members(names: list[str], sample: int | None) -> list[str]:
    names = [n for n in names if n.endswith(".atom")]
    if not sample or sample >= len(names):
        return names
    return [names[int(i * len(names) / sample)] for i in range(sample)]


class Collector:
    """Keeps the latest version of every entry; heavy records only for town halls."""

    def __init__(self):
        self.seen = {}          # hash(entry id) -> updated stamp (all entries, deleted included)
        self.records = {}       # hash(entry id) -> parsed town-hall entry
        self.tomb = set()       # hash(entry id) whose latest event is a deletion
        self.p_ids = set()      # hash(entry id) of latest versions whose body has no DIR3 and a "P" NIF
        self.entries_read = 0
        self.deleted = 0

    def add_entry(self, parsed):
        self.entries_read += 1
        if parsed is None:
            return
        key = hash(parsed["id"])
        if self.seen.get(key, -1) > parsed["updated"]:
            return
        self.seen[key] = parsed["updated"]
        self.tomb.discard(key)
        self.records.pop(key, None)
        self.p_ids.discard(key)
        if DIR3_RE.match(parsed["dir3"]):
            self.records[key] = parsed
        elif not parsed["dir3"] and parsed["nif"].startswith("P"):
            self.p_ids.add(key)

    def add_deleted(self, ref: str, when: str):
        self.deleted += 1
        key = hash(ref)
        w = stamp(when)
        if self.seen.get(key, -1) <= w:
            self.seen[key] = w
            self.tomb.add(key)
            self.records.pop(key, None)
            self.p_ids.discard(key)


def stream_zip(zpath: Path, members: list[str], coll: Collector, label: str, t0: float):
    with zipfile.ZipFile(zpath) as z:
        for n, name in enumerate(members, start=1):
            with z.open(name) as f:
                for _, el in ET.iterparse(f, events=("end",)):
                    tag = ln(el.tag)
                    if tag == "entry":
                        coll.add_entry(parse_entry(el))
                        el.clear()
                    elif tag == "deleted-entry":
                        coll.add_deleted(el.get("ref", ""), el.get("when", ""))
                        el.clear()
            if n % 50 == 0 or n == len(members):
                print(f"    {label}: {n}/{len(members)} members, {coll.entries_read} entries, {time.time() - t0:.0f}s", flush=True)


# ------------------------------------------------------------------ aggregation

def new_muni() -> dict:
    return {"tenders": 0, "lots": 0, "amount_eur": 0.0, "lots_with_offers": 0, "lots_single_bid": 0, "lots_open": 0,
            "by_type": {}, "top": []}


def aggregate(records, p_count: int, known_ine: set[str], coll_stats: dict) -> tuple[dict, dict]:
    """Latest town-hall records -> (municipalities, stats). Pure function (unit tested)."""
    # one tender seen on both platforms: keep the newest version of (DIR3, ContractFolderID)
    best = {}
    dup = 0
    for r in records:
        k = (r["dir3"], r["folder"]) if r["folder"] else (r["id"],)
        if k in best:
            dup += 1
            if best[k]["updated"] > r["updated"]:
                continue
        best[k] = r
    munis: dict[str, dict] = {}
    result_codes: dict[str, int] = {}
    procedure_codes: dict[str, int] = {}
    years: dict[str, int] = {}
    ine_unknown: dict[str, int] = {}
    dir3_bodies = set()
    ine_ok = set()
    town_tenders = 0
    lots_awarded = quarantined = no_amount = 0
    ignored_other_year = 0
    for r in best.values():
        town_tenders += 1
        dir3_bodies.add(r["dir3"])
        ine = r["ine"]
        known = ine in known_ine
        if known:
            ine_ok.add(r["dir3"])
        procedure_codes[r["procedure"]] = procedure_codes.get(r["procedure"], 0) + 1
        awarded_here = []
        for res in r["results"]:
            result_codes[res["code"]] = result_codes.get(res["code"], 0) + 1
            if res["code"] in AWARDED_RESULT_CODES:
                y = str(res["year"]) if res["year"] else "none"
                years[y] = years.get(y, 0) + 1
                if res["year"] == YEAR:
                    awarded_here.append(res)
                else:
                    ignored_other_year += 1
        if not awarded_here:
            continue
        lots_awarded += len(awarded_here)
        quarantined += sum(1 for x in awarded_here if not x["winner"])
        no_amount += sum(1 for x in awarded_here if x["amount"] is None)
        if not known:
            ine_unknown[ine] = ine_unknown.get(ine, 0) + 1
            continue
        m = munis.setdefault(ine, new_muni())
        m["tenders"] += 1
        bt = m["by_type"].setdefault(r["type"], {"lots": 0, "amount_eur": 0.0})
        for x in awarded_here:
            amt = x["amount"] or 0.0
            m["lots"] += 1
            m["amount_eur"] += amt
            bt["lots"] += 1
            bt["amount_eur"] += amt
            if x["offers"] is not None:
                m["lots_with_offers"] += 1
                if x["offers"] == 1:
                    m["lots_single_bid"] += 1
            if r["procedure"] in OPEN_PROCEDURE_CODES:
                m["lots_open"] += 1
            if x["winner"] and r.get("title") and x["amount"] is not None:
                m["top"].append({"title": r["title"], "cpv": x["cpv"], "amount_eur": round(x["amount"], 2), "date": x["date"],
                                 "procedure": r["procedure"], "offers": x["offers"], "winner": x["winner"][0],
                                 "winner_nif": x["winner"][1], "link": r["link"], "body": r["body"]})
        bt["amount_eur"] = round(bt["amount_eur"], 2)
    for m in munis.values():
        m["amount_eur"] = round(m["amount_eur"], 2)
        m["top"] = sorted(m["top"], key=lambda t: -t["amount_eur"])[:TOP_N]
        for v in m["by_type"].values():
            v["amount_eur"] = round(v["amount_eur"], 2)
    stats = {
        **coll_stats,
        "tenders_town_halls": town_tenders,
        "cross_platform_duplicates": dup,
        "dir3_l01_bodies": len(dir3_bodies),
        "ine_matched": len(ine_ok),
        "ine_unknown": sorted(ine_unknown),
        "unmatched_p": p_count,
        "lots_awarded_2025": lots_awarded,
        "lots_awarded_other_year_ignored": ignored_other_year,
        "lots_without_amount": no_amount,
        "quarantined_lots": quarantined,
        "quarantine_share": round(quarantined / lots_awarded, 4) if lots_awarded else None,
        "result_codes": dict(sorted(result_codes.items())),
        "procedure_codes": dict(sorted(procedure_codes.items())),
        "years": dict(sorted(years.items())),
    }
    return dict(sorted(munis.items())), stats


NOTE = (
    "Contratos adjudicados en 2025 (año de la fecha de adjudicación) por ayuntamientos que publican en la Plataforma de "
    "Contratación del Sector Público o en las plataformas autonómicas agregadas. No incluye contratos menores. "
    "Cuentan los lotes adjudicados, adjudicados definitivamente y formalizados; no cuentan las adjudicaciones provisionales, "
    "los desiertos, los desistimientos ni los encargos a medios propios. Se toma la última versión publicada de cada "
    "licitación. Los ayuntamientos que contratan fuera de estas plataformas o sin código DIR3 no aparecen. Los contratos "
    "con adjudicatarios que no son personas jurídicas con NIF válido cuentan en los totales, pero no se publica "
    "su nombre ni su identificador."
)


def known_municipalities() -> set[str]:
    import json
    d = json.loads((INTERIM / "gisco_lau.json").read_text())["data"]
    return {m["code"] for m in d["municipalities"]}


class Placsp(Source):
    info = SourceInfo(
        id="placsp",
        title="Plataforma de Contratación del Sector Público: licitaciones de ayuntamientos 2025",
        publisher="Ministerio de Hacienda, Plataforma de Contratación del Sector Público (PLACSP)",
        homepage="https://contrataciondelestado.es/wps/portal/DatosAbiertos",
        license="Datos abiertos del sector público; reutilización con cita de la fuente (Ley 37/2007).",
        description="Contratos adjudicados por ayuntamientos en 2025, sin contratos menores: recuentos, importes y "
        "licitaciones con una sola oferta por municipio.",
        used_for=["Solo interim: contratación pública municipal (aún sin constructor)"],
    )

    @property
    def raw_dir(self) -> Path:
        return RAW / BULK_DIR

    def fetch(self, force: bool = False):
        import urllib.request
        for key, name in ZIPS.items():
            dest = self.raw_dir / name
            if dest.exists() and not force:
                continue
            if self.offline:
                raise FileNotFoundError(f"{dest} missing (--offline)")
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".part")
            req = urllib.request.Request(URLS[key], headers={"User-Agent": "spain-strategy-map/1.0 (open-source map project)"})
            with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as out:
                while chunk := r.read(1 << 20):
                    out.write(chunk)
            os.replace(tmp, dest)

    def process(self) -> dict:
        sample = int(os.environ.get("PLACSP_SAMPLE", "0") or 0) or None
        t0 = time.time()
        coll = Collector()
        downloaded = ""
        for key, name in ZIPS.items():
            zpath = self.raw_dir / name
            if not zpath.exists():
                raise FileNotFoundError(f"{zpath} missing - run: uv run python -m pipeline fetch placsp")
            downloaded = max(downloaded, datetime.fromtimestamp(zpath.stat().st_mtime, timezone.utc).date().isoformat())
            with zipfile.ZipFile(zpath) as z:
                members = pick_members(z.namelist(), sample)
            print(f"    {key}: {len(members)} members{' (SAMPLE)' if sample else ''}", flush=True)
            stream_zip(zpath, members, coll, key, t0)
        munis, stats = aggregate(
            coll.records.values(), len(coll.p_ids), known_municipalities(),
            {"entries_read": coll.entries_read, "deleted_entries": coll.deleted,
             "tenders_latest": len(coll.seen) - len(coll.tomb),
             "members_sampled": sample or "all"},
        )
        print(f"    parse+aggregate {time.time() - t0:.0f}s, {len(munis)} municipalities", file=sys.stderr)
        return {"vintage": str(YEAR), "downloaded": downloaded, "municipalities": munis, "stats": stats, "note": NOTE}
