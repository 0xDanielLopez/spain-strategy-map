"""web/js/geo/projection.js must match pipeline/core/geo.py MapProjection (<= 0.01 km, same hidden())."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from pipeline.build.projection import make_doc
from pipeline.core.geo import MapProjection

ROOT = Path(__file__).resolve().parents[1]
PROJ = {"min_x": -980.0, "max_y": 520.0, "margin": 80.0}
POINTS = {
    "Madrid": (-3.70, 40.42), "Barcelona": (2.17, 41.39), "A Coruña": (-8.41, 43.37), "Cádiz": (-6.29, 36.53),
    "Mahón": (4.27, 39.89), "Ceuta": (-5.32, 35.89), "Melilla": (-2.94, 35.29),
    "Las Palmas": (-15.42, 28.12), "Santa Cruz de Tenerife": (-16.25, 28.47), "Valverde": (-17.91, 27.81),
    "Arrecife": (-13.55, 28.96), "Puerto del Rosario": (-13.86, 28.50), "Santa Cruz de La Palma": (-17.76, 28.68),
    "San Sebastián de La Gomera": (-17.11, 28.09), "Sevilla": (-5.98, 37.39), "Valencia": (-0.38, 39.47),
    "Palma": (2.65, 39.57), "Ibiza": (1.43, 38.91), "Cap de Creus": (3.32, 42.32), "Estaca de Bares": (-7.69, 43.79),
    "Tarifa": (-5.60, 36.00), "Vigo": (-8.72, 42.24), "Bilbao": (-2.93, 43.26),
    # borders and edges: box rim of the Canarias inset, just outside it, Portugal, France, Morocco, under the frame
    "box SW": (-18.6, 27.3), "box NE": (-13.0, 29.7), "box NW": (-18.6, 29.7), "box SE": (-13.0, 27.3),
    "outside W": (-18.7, 28.5), "outside N": (-15.0, 29.8), "Lisboa": (-9.14, 38.72), "Perpiñán": (2.90, 42.70),
    "Argel": (3.06, 36.75), "Orán": (-0.63, 35.70), "Casablanca": (-7.59, 33.57), "Atlántico frame": (-1.0, 33.0),
    "Cartagena": (-0.98, 37.60), "Cabo de Gata": (-2.19, 36.72), "Formentera": (1.45, 38.70),
    "Tánger": (-5.80, 35.77), "Madeira": (-16.9, 32.7), "Marrakech": (-8.0, 31.63),
}

JS = """
import { createProjection } from %(mod)s;
import fs from "node:fs";
const [doc, pts] = JSON.parse(fs.readFileSync(%(data)s, "utf8"));
const p = createProjection(doc);
console.log(JSON.stringify(pts.map(([lon, lat]) => [...p.project(lon, lat), p.hidden(lon, lat)])));
"""


class ProjectionJsTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_matches_python(self):
        doc = make_doc(PROJ)
        py = MapProjection(**PROJ)
        pts = list(POINTS.values())
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "in.json"
            data.write_text(json.dumps([doc, pts]))
            script = Path(tmp) / "run.mjs"
            script.write_text(JS % {"mod": json.dumps((ROOT / "web/js/geo/projection.js").as_uri()), "data": json.dumps(str(data))})
            out = subprocess.run(["node", str(script)], capture_output=True, text=True, check=True).stdout
        got = json.loads(out)
        self.assertEqual(len(got), len(pts))
        n_hidden = 0
        for (name, (lon, lat)), (x, y, hid) in zip(POINTS.items(), got):
            ex, ey = py(lon, lat)
            self.assertLessEqual(abs(x - ex), 0.01, name)
            self.assertLessEqual(abs(y - ey), 0.01, name)
            self.assertEqual(hid, py.hidden(lon, lat), name)
            n_hidden += hid
        self.assertGreater(n_hidden, 0, "the sample should include hidden points")

    def test_doc_is_complete(self):
        doc = make_doc(PROJ)
        self.assertEqual(doc["insets"][0]["name"], "Canarias")
        self.assertEqual(len(doc["main_albers"]), 4)


if __name__ == "__main__":
    unittest.main()
