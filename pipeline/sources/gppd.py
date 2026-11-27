"""WRI Global Power Plant Database v1.3 (edición 2021), solo centrales de España."""

import csv
import io
import zipfile

from ..core.source import Source, SourceInfo

URL = "https://wri-dataportal-prod.s3.amazonaws.com/manual/global_power_plant_database_v_1_3.zip"
ZIP = "global_power_plant_database_v_1_3.zip"
CSV_NAME = "global_power_plant_database.csv"


def _num(s):
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def parse_rows(rows) -> list[dict]:
    """Spanish plants from GPPD CSV rows (dicts). Unknown numbers stay None, never 0."""
    out = []
    for r in rows:
        if (r.get("country") or "").strip() != "ESP":
            continue
        lat, lon, mw = _num(r.get("latitude")), _num(r.get("longitude")), _num(r.get("capacity_mw"))
        if lat is None or lon is None:
            continue
        year = _num(r.get("commissioning_year"))
        out.append({
            "id": (r.get("gppd_idnr") or "").strip(),
            "name": (r.get("name") or "").strip(),
            "fuel": (r.get("primary_fuel") or "").strip(),
            "capacity_mw": mw,
            "lat": lat,
            "lon": lon,
            "year": int(year) if year is not None else None,
            "owner": (r.get("owner") or "").strip() or None,
        })
    return out


class Gppd(Source):
    info = SourceInfo(
        id="gppd",
        title="WRI Global Power Plant Database v1.3 (edición 2021)",
        publisher="World Resources Institute",
        homepage="https://datasets.wri.org/dataset/globalpowerplantdatabase",
        license="CC BY 4.0",
        description="Inventario histórico de centrales eléctricas de 2021. Se usan solo las centrales de España "
        "nucleares, hidroeléctricas y de gas.",
        used_for=["Centrales nucleares, hidroeléctricas y de gas"],
    )

    def fetch(self, force=False):
        self.download(URL, ZIP, force=force, expect_binary=True)

    def process(self):
        with zipfile.ZipFile(self.raw_dir / ZIP) as z:
            with z.open(CSV_NAME) as f:
                rows = list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8")))
        return {"vintage": "WRI GPPD v1.3 (2021)", "_files": [ZIP], "plants": parse_rows(rows)}
