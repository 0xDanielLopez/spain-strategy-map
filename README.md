# Spain Strategy Map

España dibujada como un mapa de estrategia 4X: terreno en hexágonos, relieve, cobertura del suelo, lentes con datos
del INE por municipio y las 68 áreas urbanas funcionales como ciudades, todo a partir de datos públicos.

**Mapa en vivo: https://0xdaniellopez.github.io/spain-strategy-map/**

Este proyecto es un fork de [usaciv](https://karpathy.ai/usaciv/), de Andrej Karpathy (licencia MIT), que dibuja
Estados Unidos de la misma forma. Mantengo su pipeline, su rejilla hexagonal y el arte del mapa, y cambio los datos de
EE. UU. por datos abiertos de España y de Europa.

## Estado

Fases F0 (mapa base), F1 (lentes del INE), F2 (ciudades), F3 (capas del mapa) y F4 (Consejeros y vista de ciudad).

- Hexágonos de 10 km de radio (unos 260 km2 cada uno, unos 1.950 de tierra en España).
- Tierra y agua, relieve (llano, colinas, montañas, picos) y cobertura del suelo en cada hexágono.
- Las 19 comunidades y ciudades autónomas como primer nivel y los 8.132 municipios como segundo.
- Canarias en un recuadro, como en los mapas impresos de España.
- Ceuta, Melilla y las islas pequeñas tienen al menos un hexágono cada una. Es una excepción cartográfica: un
  hexágono es mucho más grande que Ceuta o Melilla.

- 12 lentes: densidad, crecimiento 2021-2026, edad media, mayores de 65 años, nacionalidad extranjera, tamaño del
  hogar, renta neta por persona, población bajo el 60 % de la mediana, estudios superiores, arbolado, cultivos y
  construido.
- Buscador de ciudades, comunidades y de los 8.132 municipios.
- 68 ciudades: las áreas urbanas funcionales del INE, con población, crecimiento, renta media por persona, ocupados
  por sector y cinco rendimientos (comida, producción, ciencia, cultura y oro). Las 19 comunidades tienen los mismos
  datos.

- Vista de ciudad: el área urbana en el mapa, sus habitantes (edad, estudios, nacionalidad), especializaciones
  (sectores con más peso que en España entre los ocupados que viven allí), economía, empleo y áreas comparables.
- Cinco Consejeros: economía, población, formación y perfil profesional, territorio y un explorador de ciudades,
  comunidades y municipios.

- Capas del mapa: red principal esquemática de carreteras y ferrocarril, puertos y aeropuertos (sin cifras de
  tráfico), centrales nucleares, hidroeléctricas y de gas del inventario de 2021, y patrimonio mundial y parques
  nacionales. Tres Consejeros más: energía, infraestructuras y patrimonio y parques.

Los Consejeros de defensa y prosperidad siguen ocultos: no tengo datos abiertos para ellos. Tampoco uso datos de
pasajeros ni de mercancías, porque vienen de Aena y Puertos del Estado.

### Qué no cuentan las capas

- La red de carreteras y ferrocarril es arte de mapa de Natural Earth, no estadística.
- Las centrales vienen del inventario de WRI de 2021, que ya no se actualiza. Dejo fuera el carbón y el petróleo,
  porque la mayoría de esas centrales ha cerrado desde entonces, y la eólica y la solar, porque el inventario de 2021
  está muy incompleto. Las sumas son de las centrales representadas, no la potencia instalada de España.
- Un bien del patrimonio mundial formado por muchos lugares (como el Camino de Santiago) sale con un punto
  representativo. Dos bienes compartidos con otros países no tienen punto en España.

### Rendimientos de las ciudades

- Comida, producción, ciencia y cultura cuentan ocupados por sector (CNAE) según dónde viven, del Censo anual de
  población 2024: comida = agricultura; producción = industria, energía, agua y construcción; ciencia = información y
  comunicaciones y actividades profesionales y científicas; cultura = actividades artísticas y recreativas.
- El oro es el PIB. Para las comunidades y España es el PIB publicado por el INE. Para las ciudades es un PIB
  provincial imputado: reparto el PIB de cada provincia entre sus municipios según sus ocupados y sumo los municipios
  del área. No es un PIB municipal medido, así que no comparo ciudades por PIB por habitante.

### Cómo se reparten los datos municipales

Cada municipio se reparte entre los hexágonos que toca según su superficie: cuento los puntos de una retícula de 1 km
de cada hexágono que caen en cada municipio. Así la población total de los hexágonos es igual a la de los municipios.
Esto supone que la población está repartida por igual dentro del término municipal, así que un municipio grande con
la ciudad en un extremo reparte su población también por el campo.

Las tasas y las medias de un hexágono salen de sumar numeradores y denominadores de sus municipios: la edad media se
pondera por habitantes, el tamaño del hogar por hogares y los estudios por la población de 15 años o más. Un hexágono
sale sin dato si los municipios con dato tienen menos del 90 % de su población. Por eso la pobreza y los estudios
superiores salen sin dato en muchas zonas rurales: el INE no publica esos datos en muchos municipios pequeños.

## Cómo ejecutarlo

Necesitas Python 3.11 o superior y [uv](https://docs.astral.sh/uv/). El pipeline usa solo la biblioteca estándar.

```bash
uv run python -m pipeline all       # descarga, procesa, construye y comprueba (la primera vez baja unos 3 GB)
uv run python -m pipeline serve     # abre http://127.0.0.1:8765
```

`uv run python -m pipeline all --offline` reconstruye con las descargas en caché, sin red.
`uv run python -m unittest discover -s tests` ejecuta los tests.

## Fuentes de datos y licencias

| Datos | Editor | Licencia | Uso |
|---|---|---|---|
| [LAU 2024, 1:1 millón](https://ec.europa.eu/eurostat/web/gisco/geodata/statistical-units/local-administrative-units) | Eurostat GISCO | © EuroGeographics para los límites administrativos. Uso no comercial, con este aviso visible en el mapa | Tierra y agua, municipios, comunidades autónomas |
| [ESA WorldCover 10 m 2021 v200](https://esa-worldcover.org/) | Agencia Espacial Europea | CC BY 4.0. © ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium. Zanaga et al. 2022, doi:10.5281/zenodo.7254221 | Cobertura del suelo de cada hexágono |
| [ETOPO1](https://www.ncei.noaa.gov/products/etopo-global-relief-model) vía NOAA ERDDAP | NOAA NCEI | Dominio público | Relieve, profundidad del mar |
| [Natural Earth 1:50m](https://www.naturalearthdata.com/) | Natural Earth | Dominio público | Países vecinos, lagos, ríos |
| [INE](https://www.ine.es): Censo anual de población (tabla 73027), Atlas de distribución de renta de los hogares (30824, 30829, 30832), nivel de estudios (66620) | Instituto Nacional de Estadística | Reutilización permitida citando la fuente | Lentes por municipio |
| INE: áreas urbanas funcionales 2026, ocupados por sector (69992, 70002, 69968), Contabilidad Regional (80109) | Instituto Nacional de Estadística | Reutilización permitida citando la fuente | Ciudades, rendimientos y PIB |
| [Natural Earth 1:10m](https://www.naturalearthdata.com/) carreteras, ferrocarril y puertos | Natural Earth | Dominio público | Red principal esquemática, puertos |
| [OurAirports](https://ourairports.com/data/) | OurAirports | Dominio público | Aeropuertos |
| [Global Power Plant Database v1.3](https://datasets.wri.org/dataset/globalpowerplantdatabase) (2021) | World Resources Institute | CC BY 4.0 | Centrales nucleares, hidroeléctricas y de gas |
| [Wikidata](https://www.wikidata.org/) | Wikimedia | CC0 | Patrimonio mundial y parques nacionales |

El mapa muestra la línea de atribución en una esquina, como piden las condiciones de GISCO. El pipeline guarda la URL,
el sha256, el tamaño y la fecha de cada fichero descargado en `web/data/sources.json`, y `web/data/world.json` lleva
la fuente y la licencia de cada campo.

La tabla de provincias a comunidades autónomas la escribí a mano a partir de los códigos del INE.

Datos del INE: elaboración propia con datos extraídos del sitio web del INE: www.ine.es. El INE no participa,
patrocina ni apoya este proyecto.

### Qué significa la cobertura del suelo

WorldCover tiene 11 clases. Leo la vista general más pequeña de cada tesela de 3 x 3 grados (píxeles de unos 600 m) y
la muestreo cada 1 km dentro de cada hexágono. Algunas clases no significan lo mismo que en el mapa de EE. UU.:

- Los olivares, los viñedos y otros cultivos leñosos pueden salir como arbolado o matorral.
- Los invernaderos (por ejemplo, en Almería) salen como construido.
- Los pastos están dentro del pastizal: no hay una cuota aparte de pastos.

## Licencia

- **Código**: MIT, ver [LICENSE](LICENSE). El código original es © 2026 Andrej Karpathy; mis cambios son © 2026 Daniel
  López.
- **Ficheros de datos en `web/data/`**: derivan de las fuentes de arriba y mantienen sus condiciones. Los datos de
  hexágono a municipio y de hexágono a comunidad autónoma vienen de los límites de GISCO: solo uso no comercial, con
  el aviso de EuroGeographics. No están bajo la licencia MIT. Las descargas en bruto no están en este repositorio.

## Cómo funciona

```
pipeline/
  core/       descargas en caché con un manifiesto de procedencia (fetch.py), la clase base Source,
              proyección con el recuadro de Canarias (geo.py), rejilla hexagonal (hexgrid.py), E/S JSON atómica (store.py)
  sources/    un módulo por fuente de datos: fetch() baja los ficheros, process() -> data/interim/<id>.json
  build/      constructores que llevan las fuentes al mapa de hexágonos -> web/data/*.json
  check.py    valida web/data contra docs/DATA_CONTRACTS.md y escribe un informe de calidad de datos
tests/        tests con unittest (solo biblioteca estándar)
web/          la aplicación del mapa (módulos ES, sin paso de compilación); web/data guarda el JSON generado
docs/         DATA_CONTRACTS.md: la forma de cada fichero de web/data (en inglés, como el código)
```

El flujo es siempre fuente -> intermedio -> constructor -> web/data. El mapa usa una proyección Albers de áreas
iguales para España (paralelos estándar 36 y 44 grados, centro 40 N 3 O). Canarias usa su propia proyección Albers y
se traslada al recuadro.

### Comandos

```bash
uv run python -m pipeline list                        # fuentes y constructores (en orden de construcción)
uv run python -m pipeline fetch [fuente ...]          # baja los ficheros (en caché; --force vuelve a bajarlos)
uv run python -m pipeline process [fuente ...]        # bruto -> data/interim/<fuente>.json
uv run python -m pipeline build [constructor ...]     # intermedio -> web/data; se salta lo que está al día
uv run python -m pipeline check                       # valida web/data (sale con 1 si hay FAIL)
uv run python -m pipeline all [--offline]             # fetch + process + build + check
uv run python -m pipeline serve [--port 8765]         # sirve web/
```
