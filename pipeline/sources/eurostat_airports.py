import json

from ..core.source import Source, SourceInfo

YEARS = range(2022, 2026)
URL = (
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/avia_paoa"
    "?format=JSON&lang=EN&freq=A&unit=PAS&tra_meas=PAS_CRD&schedule=TOTAL&tra_cov=TOTAL"
    + "".join(f"&time={y}" for y in YEARS)
)
USER_AGENT = "spain-strategy-map/1.0 (open-source map project)"
MIN_SHARE = 0.8  # the latest year with values for at least this share of the airports that report in any year


class EurostatAirports(Source):
    info = SourceInfo(
        id="eurostat_airports",
        title="Eurostat avia_paoa (pasajeros por aeropuerto)",
        publisher="Eurostat",
        homepage="https://ec.europa.eu/eurostat/databrowser/view/avia_paoa/default/table",
        license="Reutilización permitida citando la fuente (aviso de copyright de Eurostat)",
        description="Pasajeros transportados (llegadas más salidas, servicios regulares y no regulares, tráfico nacional "
        "e internacional) por aeropuerto español y año, a partir de datos de Aena.",
        used_for=["Pasajeros de los aeropuertos"],
    )

    def fetch(self, force=False):
        self.download(URL, "avia_paoa.json", force=force, headers={"User-Agent": USER_AGENT})

    def process(self):
        d = json.loads((self.raw_dir / "avia_paoa.json").read_text(encoding="utf-8"))
        dims, size = d["id"], d["size"]
        pos = {k: d["dimension"][k]["category"]["index"] for k in dims}
        for k, want in (("schedule", "TOTAL"), ("tra_cov", "TOTAL")):
            if set(pos[k]) != {want}:
                raise RuntimeError(f"avia_paoa: {k} must be pinned to {want}, got {sorted(pos[k])}")
        assert d["dimension"]["schedule"]["category"]["label"]["TOTAL"] == "Total"
        assert d["dimension"]["tra_cov"]["category"]["label"]["TOTAL"] == "Total transport"
        strides, s = {}, 1
        for k, n in zip(reversed(dims), reversed(size)):
            strides[k] = s
            s *= n
        by_year: dict[str, dict[str, int]] = {}
        for code, i in pos["rep_airp"].items():
            if not code.startswith("ES_"):
                continue
            for year, j in pos["time"].items():
                v = d["value"].get(str(i * strides["rep_airp"] + j * strides["time"]))
                if v is not None and v > 0:
                    by_year.setdefault(year, {})[code[3:]] = int(v)
        if not by_year:
            raise RuntimeError("avia_paoa: no Spanish values")
        for y in sorted(by_year):
            print(f"    {y}: {len(by_year[y])} Spanish airports with passengers")
        anyyear = {i for v in by_year.values() for i in v}
        year = max(y for y, v in by_year.items() if len(v) >= MIN_SHARE * len(anyyear))
        airports = [{"icao": i, "passengers": p, "year": int(year)} for i, p in sorted(by_year[year].items(), key=lambda t: -t[1])]
        print(f"    using {year}: {len(airports)} airports")
        return {"vintage": f"Eurostat avia_paoa, {year} (datos de Aena)", "year": int(year), "_files": ["avia_paoa.json"], "airports": airports}
