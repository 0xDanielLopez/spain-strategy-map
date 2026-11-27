import csv

from ..core.source import Source, SourceInfo

# ETOPO1 (1 arc-minute) via NOAA ERDDAP, sampled every 2nd point (~3.7 km). The window covers the
# whole map rectangle (mainland Spain, the Balearic and Canary Islands, Ceuta, Melilla and the neighbours).
STRIDE = 2
LAT, LON = (26.5, 45.5), (-19.5, 6.5)  # the map's north-east corner reaches 5.9 E
URL = (
    "https://coastwatch.pfeg.noaa.gov/erddap/griddap/etopo180.csv"
    f"?altitude%5B({LAT[0]}):{STRIDE}:({LAT[1]})%5D%5B({LON[0]}):{STRIDE}:({LON[1]})%5D"
)
FILE = f"etopo_lat{LAT[0]}_{LAT[1]}_lon{LON[0]}_{LON[1]}_stride{STRIDE}.csv"


class Etopo(Source):
    info = SourceInfo(
        id="etopo",
        title="Modelo global de relieve ETOPO1",
        publisher="NOAA National Centers for Environmental Information (vía ERDDAP)",
        homepage="https://www.ncei.noaa.gov/products/etopo-global-relief-model",
        license="Dominio público (obra del Gobierno de EE. UU.)",
        description="Altitud del terreno y profundidad del océano, muestreadas cada ~3,7 km. Cubre la España peninsular, las islas Baleares y Canarias, Ceuta, Melilla y los países y mares vecinos. El relieve de cada hexágono (llano, colinas, montañas, "
        "picos) sale de la media y la rugosidad (desviación típica) de las muestras de tierra que contiene.",
        used_for=["Relieve (colinas, montañas)", "Sombreado del relieve", "Profundidad del océano"],
    )

    def fetch(self, force=False):
        self.download(URL, FILE, force=force)

    def process(self):
        lat, lon, alt = [], [], []
        with open(self.raw_dir / FILE, newline="") as f:
            rows = csv.reader(f)
            next(rows), next(rows)  # header + units
            for la, lo, al in rows:
                if al == "NaN":
                    continue
                lat.append(round(float(la), 4))
                lon.append(round(float(lo), 4))
                alt.append(int(float(al)))
        return {
            "vintage": "ETOPO1, 1 minuto de arco, muestreado cada ~3,7 km",
            "_files": [FILE],
            "lat": lat,
            "lon": lon,
            "alt": alt,
        }
