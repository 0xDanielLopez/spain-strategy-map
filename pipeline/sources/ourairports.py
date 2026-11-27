import csv

from ..core.source import Source, SourceInfo

URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
USER_AGENT = "spain-strategy-map/1.0 (open-source map project)"
TYPES = {"large_airport", "medium_airport"}


class OurAirports(Source):
    info = SourceInfo(
        id="ourairports",
        title="OurAirports (aeropuertos)",
        publisher="OurAirports",
        homepage="https://ourairports.com/data/",
        license="Dominio público",
        description="Lista abierta de aeropuertos del mundo. Se usan los aeropuertos españoles grandes y medianos con "
        "servicio regular: nombre, municipio y posición. No incluye cifras de pasajeros.",
        used_for=["Aeropuertos del mapa"],
    )

    def fetch(self, force=False):
        self.download(URL, "airports.csv", force=force, headers={"User-Agent": USER_AGENT})

    def process(self):
        airports = []
        with open(self.raw_dir / "airports.csv", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if row.get("iso_country") != "ES" or row.get("type") not in TYPES or row.get("scheduled_service") != "yes":
                    continue
                try:
                    lat, lon = float(row["latitude_deg"]), float(row["longitude_deg"])
                except (TypeError, ValueError):
                    continue
                airports.append({
                    "id": row.get("iata_code") or row.get("ident"),
                    "ident": row.get("ident"),
                    "name": row.get("name"),
                    "city": row.get("municipality") or None,
                    "type": row.get("type"),
                    "lon": round(lon, 5),
                    "lat": round(lat, 5),
                })
        print(f"    {len(airports)} Spanish airports with scheduled service (large/medium)")
        return {"vintage": "OurAirports (descarga actual)", "_files": ["airports.csv"], "airports": airports}
