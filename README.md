# Spain Strategy Map

Spain drawn as a 4X strategy-game map: hex terrain, relief and land cover, all from public data.

**Live map: https://0xdaniellopez.github.io/spain-strategy-map/**

This project is a fork of [usaciv](https://karpathy.ai/usaciv/) by Andrej Karpathy (MIT licence), which draws the
United States in the same way. I keep his pipeline, hex grid and map art, and I replace the US data with Spanish and
European open data.

## Status

Phase F0: the base map only.

- Hexes of 10 km radius (about 260 km2 each, about 1,950 land hexes for Spain).
- Land and water, relief (flat, hills, mountains, peaks) and land cover for every hex.
- The 19 autonomous communities (17 communities plus Ceuta and Melilla) as the top level, and the 8,132 municipalities
  as the second level.
- The Canary Islands in an inset frame, like on printed maps of Spain.
- Ceuta, Melilla and the small islands get at least one hex each. These hexes are a cartographic exception: one hex
  is much larger than Ceuta or Melilla.

There are no statistics, cities, lenses or resources yet. The UI text still comes from the US version in places.

## Run it

You need Python 3.11 or newer and [uv](https://docs.astral.sh/uv/). The pipeline uses the standard library only.

```bash
uv run python -m pipeline all       # download, process, build and check (the first run downloads about 200 MB)
uv run python -m pipeline serve     # open http://127.0.0.1:8765
```

`uv run python -m pipeline all --offline` rebuilds from the cached downloads without the network.
`uv run python -m unittest discover -s tests` runs the tests.

## Data sources and licences

| Data | Publisher | Licence | Used for |
|---|---|---|---|
| [LAU 2024, 1:1 million](https://ec.europa.eu/eurostat/web/gisco/geodata/statistical-units/local-administrative-units) | Eurostat GISCO | © EuroGeographics for the administrative boundaries. Non-commercial use, with this notice visible on the map | Land and water, municipalities, autonomous communities |
| [ESA WorldCover 10 m 2021 v200](https://esa-worldcover.org/) | European Space Agency | CC BY 4.0. © ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium. Zanaga et al. 2022, doi:10.5281/zenodo.7254221 | Land cover of each hex |
| [ETOPO1](https://www.ncei.noaa.gov/products/etopo-global-relief-model) via NOAA ERDDAP | NOAA NCEI | Public domain | Relief, sea depth |
| [Natural Earth 1:50m](https://www.naturalearthdata.com/) | Natural Earth | Public domain | Neighbouring countries, lakes, rivers |

The map page shows the attribution line in a corner, as the GISCO terms require. The pipeline writes the URL,
sha256, size and date of every downloaded file to `web/data/sources.json`.

The province to autonomous community table is written by hand from the INE codes.

### What the land cover means

WorldCover has 11 classes. I read the smallest overview of each 3 x 3 degree tile (pixels of about 600 m) and sample
it every 1 km inside each hex. Some classes do not mean the same as on the US map:

- Olive groves, vineyards and other woody crops can show as tree cover or shrubland.
- Greenhouses (for example in Almería) show as built-up.
- Pastures are inside grassland: there is no separate pasture share.

## Licence

- **Code**: MIT, see [LICENSE](LICENSE). The original code is © 2026 Andrej Karpathy; my changes are © 2026 Daniel
  López.
- **Data files in `web/data/`**: they are derived from the sources above and keep their terms. The hex to
  municipality and hex to autonomous community data come from GISCO boundaries: non-commercial use only, with the
  EuroGeographics notice. They are not under the MIT licence. Raw downloads are not in this repository.

## How it works

```
pipeline/
  core/       cached downloads with a provenance manifest (fetch.py), the Source base class,
              projection with the Canary Islands inset (geo.py), hex grid (hexgrid.py), atomic JSON IO (store.py)
  sources/    one module per data source: fetch() raw files, process() -> data/interim/<id>.json
  build/      builders that put the sources onto the hex map -> web/data/*.json
  check.py    validates web/data against docs/DATA_CONTRACTS.md and prints a data-quality report
tests/        unittest suite (standard library only)
web/          the map app (ES modules, no build step); web/data holds the generated JSON
docs/         DATA_CONTRACTS.md: the shape of every web/data file
```

The flow is always source -> interim -> builder -> web/data. The map uses an Albers equal-area projection of Spain
(standard parallels 36 and 44 degrees, centre 40 N 3 W). The Canary Islands use their own Albers projection and move
into the inset frame.

### Commands

```bash
uv run python -m pipeline list                        # sources and builders (in build order)
uv run python -m pipeline fetch [source ...]          # download raw files (cached; --force re-downloads)
uv run python -m pipeline process [source ...]        # raw -> data/interim/<source>.json
uv run python -m pipeline build [builder ...]         # interim -> web/data; up-to-date builders are skipped
uv run python -m pipeline check                       # validate web/data (exit 1 on FAIL)
uv run python -m pipeline all [--offline]             # fetch + process + build + check
uv run python -m pipeline serve [--port 8765]         # serve web/
```
