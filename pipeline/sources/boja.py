"""BOJA (Boletín Oficial de la Junta de Andalucía): counts of dispositions per year, section and organisation.

Open-data API of the Junta de Andalucía (licence CC BY 4.0). Only the LIMITED metadata fields
``id``, ``titleSec`` and ``organisation`` are requested: never the body, the summary or the title of a
disposition (sections 2 and 5 name natural persons). Nothing but counts is stored.

The search endpoint caps ``total_hits`` at 10,000 per query and ``size`` at 100, so the API is queried
month by month and paged. A month is accepted only if the number of distinct ids read equals ``total_hits``.
"""

from __future__ import annotations

import calendar
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

from ..core.source import Source, SourceInfo

API = "https://datos.juntadeandalucia.es/api/v0/boja/get/search_pagination"
HOMEPAGE = "https://www.juntadeandalucia.es/datosabiertos/portal/dataset/boja-disposiciones-del-ano-2025"
LICENSE = "Reconocimiento 4.0 Internacional (CC BY 4.0)"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/deed.es"
USER_AGENT = "spain-strategy-map/1.0 (open-source map project)"
YEARS = (2024, 2025, 2026)
FIELDS = ("id", "titleSec", "organisation")
PAGE_SIZE = 100
HIT_CAP = 10_000
SECTION_NAMES = {
    "0": "Disposiciones estatales",
    "1": "Disposiciones generales",
    "2": "Autoridades y personal",
    "3": "Otras disposiciones",
    "4": "Justicia",
    "5": "Anuncios",
}
MIXED = "mixto"
UNKNOWN = "sin_seccion"
SECTION_RE = re.compile(r"(?<!\d)([0-5])\.\s")


def section_code(title_sec: str) -> str:
    """Section digit from a "5. Anuncios" label. Labels with several sections glued together (the API has
    some) or without a leading number are not guessed: they go to "mixto" / "sin_seccion"."""
    digits = {m.group(1) for m in SECTION_RE.finditer(title_sec or "")}
    if len(digits) == 1:
        return digits.pop()
    return MIXED if digits else UNKNOWN


def month_ranges(today: date | None = None):
    """(year, month, date_from, date_to) for every month of YEARS up to the current one."""
    today = today or date.today()
    for y in YEARS:
        for m in range(1, 13):
            if (y, m) > (today.year, today.month):
                return
            last = calendar.monthrange(y, m)[1]
            yield y, m, f"{y}-{m:02d}-01", f"{y}-{m:02d}-{last:02d}"


def aggregate(results, counts: dict | None = None) -> dict:
    """Fold result dicts into {"total": n, "by_section": {code: n}, "by_org": {org: {code: n}}}."""
    c = counts if counts is not None else {"total": 0, "by_section": {}, "by_org": {}}
    for r in results:
        sec = section_code(r.get("titleSec", ""))
        org = (r.get("organisation") or "").strip() or "(sin organismo)"
        c["total"] += 1
        c["by_section"][sec] = c["by_section"].get(sec, 0) + 1
        o = c["by_org"].setdefault(org, {})
        o[sec] = o.get(sec, 0) + 1
    return c


def merge(into: dict, other: dict) -> None:
    into["total"] += other["total"]
    for s, n in other["by_section"].items():
        into["by_section"][s] = into["by_section"].get(s, 0) + n
    for org, secs in other["by_org"].items():
        o = into["by_org"].setdefault(org, {})
        for s, n in secs.items():
            o[s] = o.get(s, 0) + n


def _get(url: str, tries: int = 4) -> dict:
    for n in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError):
            if n == tries:
                raise
            time.sleep(2.0 * 2 ** (n - 1))
    raise AssertionError("unreachable")


def page_url(date_from: str, date_to: str, page: int) -> str:
    q = [("order_by", "id"), ("mode", "ASC"), ("size", PAGE_SIZE), ("page", page),
         ("date_from", date_from), ("date_to", date_to)] + [("campos", f) for f in FIELDS]
    return API + "?" + urllib.parse.urlencode(q)


def fetch_month(date_from: str, date_to: str, get=_get) -> dict:
    """Counts for one date range (see aggregate). Raises if the ids read do not match total_hits.
    The API numbers its pages from 0 (page 1 is the SECOND page; 400 past the last one)."""
    seen: set[str] = set()
    counts = {"total": 0, "by_section": {}, "by_org": {}}
    total_hits = None
    page = 0
    while True:
        d = get(page_url(date_from, date_to, page))
        total_hits = d["total_hits"]
        if total_hits >= HIT_CAP:
            raise ValueError(f"BOJA {date_from}..{date_to}: total_hits {total_hits} reaches the {HIT_CAP} cap")
        rows = [r for r in d["results"] if r.get("id") not in seen]
        for r in rows:
            seen.add(r["id"])
        aggregate(rows, counts)
        if not d["results"] or len(seen) >= total_hits or page * PAGE_SIZE >= total_hits + PAGE_SIZE:
            break
        page += 1
    if len(seen) != total_hits:
        raise ValueError(f"BOJA {date_from}..{date_to}: read {len(seen)} distinct ids, API says {total_hits}")
    return counts


class BojaSource(Source):
    info = SourceInfo(
        id="boja",
        title="BOJA: disposiciones publicadas, recuentos por año, sección y organismo",
        publisher="Junta de Andalucía",
        homepage=HOMEPAGE,
        license=f"{LICENSE} ({LICENSE_URL}); dataset CKAN license_id CC-BY-4.0",
        description="Solo recuentos de disposiciones (sin título, sumario ni cuerpo) por año, sección y organismo emisor.",
        used_for=["boja"],
    )

    def month_file(self, y: int, m: int):
        return self.raw_dir / f"counts_{y}-{m:02d}.json"

    def fetch(self, force: bool = False) -> None:
        """Per-month COUNT files in data/raw/boja/. A finished month is cached; the current one is refetched."""
        today = date.today()
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        for y, m, d0, d1 in month_ranges(today):
            p = self.month_file(y, m)
            if p.exists() and not force and (y, m) != (today.year, today.month):
                continue
            if self.offline:
                if p.exists():
                    continue
                raise RuntimeError(f"--offline: {p} is not cached")
            counts = fetch_month(d0, d1)
            counts["retrieved"] = today.isoformat()
            p.write_text(json.dumps(counts, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            print(f"    boja {y}-{m:02d}: {counts['total']} disposiciones")

    def process(self) -> dict:
        years: dict[str, dict] = {}
        files = []
        last_day = None
        for y, m, _d0, _d1 in month_ranges():
            p = self.month_file(y, m)
            if not p.exists():
                continue
            c = json.loads(p.read_text(encoding="utf-8"))
            last_day = max(last_day or "", c.get("retrieved", ""))
            files.append(p.name)
            ys = years.setdefault(str(y), {"total": 0, "by_section": {}, "by_org": {}, "months": {}})
            ys["months"][f"{m:02d}"] = c["total"]
            merge(ys, c)
        if not years:
            raise ValueError("boja: no monthly count files; run fetch first")
        return {
            "vintage": f"BOJA {', '.join(sorted(years))} (hasta {last_day})",
            "unit": "disposiciones publicadas en el BOJA (recuento de registros de la API, no personas ni textos)",
            "section_names": SECTION_NAMES,
            "license": LICENSE,
            "license_url": LICENSE_URL,
            "source_url": HOMEPAGE,
            "api": API,
            "retrieved": last_day,
            "years": years,
            "_files": files,
        }
