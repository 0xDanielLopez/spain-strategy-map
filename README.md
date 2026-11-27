# Spain Strategy Map

España dibujada como un mapa de estrategia 4X: terreno en hexágonos, relieve, cobertura del suelo, lentes con datos
del INE por municipio y las 68 áreas urbanas funcionales como ciudades, todo a partir de datos públicos.

**En vivo: https://0xdaniellopez.github.io/spain-strategy-map/**

El sitio tiene dos formas de ver los mismos datos:

- **Portada, vista simple** (`web/index.html` y `web/simple/`): un mapa con los límites reales de los 8.132 municipios,
  una frase que lo resume, las provincias con más y con menos, y una ficha por municipio (14 indicadores, evolución de
  la renta desde 2015, municipios parecidos). El fichero `web/data/simple.json` lo genera
  `uv run python -m pipeline build simple`.
- **Mapa de estrategia** ([estrategia.html](https://0xdaniellopez.github.io/spain-strategy-map/estrategia.html)): el
  mapa de hexágonos con ciudades, capas, años, comparador, mapas de ciudad y datos en directo. Los enlaces antiguos a la
  raíz (`?scope=sevilla`, `#lens=...`) redirigen a esta página.

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

- Capas del mapa: red principal esquemática de carreteras y ferrocarril, puertos y aeropuertos (con pasajeros
  por aeropuerto, sin toneladas en los puertos), centrales nucleares, hidroeléctricas y de gas del inventario de 2021, y patrimonio mundial y parques
  nacionales. Tres Consejeros más: energía, infraestructuras y patrimonio y parques.

- Nuevas lentes: vivienda (viviendas no principales y turísticas del Censo 2021 y de la estadística experimental del INE, plazas turísticas, viviendas por km2), población (llegadas desde el extranjero, variación de extranjeros 2021-2026, nacidos en el extranjero) y seguridad (infracciones penales y robos con fuerza en domicilios por 1.000 habitantes). La seguridad solo cubre los 427 municipios que publica Interior, así que muchos hexágonos salen sin dato, nunca con 0. Son hechos registrados por la policía, no miden la seguridad real ni cuentan a la población flotante.
- Consejero de Transparencia (Escribano Mayor): seguridad por territorio y municipio, disposiciones del BOJA y contratación menor de la Junta de Andalucía. Solo agregados: no publico nombres de personas ni de adjudicatarios, ni textos de anuncios. Ver [PRIVACY.md](PRIVACY.md).
- Deslizador de años en cinco lentes: renta, edad media, mayores de 65 y tamaño del hogar de 2015 a 2024, y densidad de 2021 a 2026. Todos los años usan la misma escala de color, para poder compararlos. La renta va en euros de cada año, sin ajustar por inflación. El año queda en el enlace (`#lens=income&y=2019`).
- Consejero Comparar: los 8 municipios más parecidos a uno (distancia entre indicadores del INE estandarizados; es un parecido estadístico, no una valoración) y dos municipios cara a cara, indicador a indicador, con la mediana de España.
- Mapas de ciudad con hexágonos de 150 a 300 m y secciones censales (ver "Mapas de ciudad").

Los Consejeros de defensa y prosperidad siguen ocultos: no tengo datos abiertos para ellos. Los pasajeros de los aeropuertos vienen de Eurostat (a partir de datos de Aena); no uso toneladas de los puertos, porque vienen de Puertos del Estado.

### Qué no cuentan las capas

- La red de carreteras y ferrocarril es arte de mapa de Natural Earth, no estadística.
- Los pasajeros de cada aeropuerto cuentan llegadas más salidas (Eurostat, a partir de datos de Aena). Los puertos siguen sin toneladas.
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

## Mapas de ciudad

Además del mapa de España hay una versión por ciudad: el mismo mapa de hexágonos, pero con hexágonos de 150 a 300 m y con los distritos de la ciudad en lugar de las comunidades. Se abre desde el panel de cada ciudad o con `?scope=sevilla`, `?scope=madrid` o `?scope=madrid-auf` (el área urbana de Madrid, con hexágonos de 1,2 km y municipios).

Sevilla es la ciudad donde pruebo primero lo que es propio de una ciudad: sus 11 distritos con nombre, el Guadalquivir y la dársena como agua, y las viviendas turísticas por sección censal (estadística experimental del INE a partir de anuncios; no es un registro de licencias). Lo que funciona allí pasa después al resto de ciudades.

Fuera del municipio el mapa dibuja el terreno real en tono apagado, o el mar en las ciudades de costa. En una ciudad de interior un río que sale del mapa nunca se dibuja como mar.

**Los valores son estimaciones.** El INE publica los datos por sección censal, no por hexágono. Reparto los habitantes de cada sección entre sus hexágonos según el suelo construido (clase 50 de ESA WorldCover, vista general de unos 74 m) y calculo cada lente a partir de ese reparto. Un hexágono queda sin dato cuando las secciones que concentran menos del 90 % de sus habitantes no tienen el valor, y donde no hay suelo construido no hay habitantes ni dato. Solo uso agregados por sección, distrito y municipio, nada sobre personas.

Fuentes: INE (seccionado censal 2026, Atlas de distribución de renta de los hogares y Censo anual de población) y ESA WorldCover 10 m 2021 (CC BY 4.0). Las ciudades se definen en `pipeline/scopes.py`: añadir una es añadir una entrada.

```bash
uv run python -m pipeline city --only sevilla   # o madrid, madrid-auf...; `city all` construye las 69 (menos de 3 GB de memoria)
uv run python -m pipeline city all --plan      # solo el plan: radio y hexágonos previstos por ciudad
uv run python -m pipeline check            # incluye las comprobaciones de web/data/city/
```

Los ficheros salen en `web/data/city/<id>/` y no tocan los del mapa de España. Necesitan en `data/raw/` el seccionado y las tablas del INE (ver `docs/DATA_CONTRACTS.md`, "City scopes").

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
| [Eurostat avia_paoa](https://ec.europa.eu/eurostat/databrowser/view/avia_paoa/default/table) | Eurostat (datos de Aena) | Reutilización citando la fuente | Pasajeros por aeropuerto |
| [Global Power Plant Database v1.3](https://datasets.wri.org/dataset/globalpowerplantdatabase) (2021) | World Resources Institute | CC BY 4.0 | Centrales nucleares, hidroeléctricas y de gas |
| [Wikidata](https://www.wikidata.org/) | Wikimedia | CC0 | Patrimonio mundial y parques nacionales |
| [Balance de Criminalidad](https://estadisticasdecriminalidad.ses.mir.es/) (cierres 2024 y 2025) | Ministerio del Interior, Portal Estadístico de Criminalidad | Reutilización comercial y no comercial, sin alterar el sentido de los datos. Origen de los datos: Portal Estadístico de Criminalidad. Interior no participa ni apoya este proyecto | Infracciones penales por tipo, en 427 municipios, provincias y comunidades |
| INE: viviendas del Censo 2021 (59525) y viviendas turísticas, estadística experimental (39363) | Instituto Nacional de Estadística | Reutilización permitida citando la fuente | Lentes de vivienda |
| INE: extranjeros y nacidos en el extranjero por municipio (65032, 65031), inmigración desde el extranjero (69696) | Instituto Nacional de Estadística | Reutilización permitida citando la fuente | Lentes de población y mapa de municipios |
| [BOJA, API de datos abiertos](https://www.juntadeandalucia.es/boja) | Junta de Andalucía | CC BY 4.0 | Recuento de disposiciones por año, sección y organismo (sin títulos ni textos) |
| Contratación menor de la Junta de Andalucía, 2024 y 2025 | Junta de Andalucía, Plataforma de Contratación | CC BY 4.0 | Contratos, euros y ofertas únicas por provincia y órgano (sin adjudicatarios) |

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

## En directo

El mapa puede dibujar encima los trenes de Renfe y los vuelos comerciales que hay ahora mismo sobre España. Los trenes salen con su retraso cuando Renfe lo publica (si no lo publica, no pongo nada, nunca un 0). Los vuelos son solo de aerolíneas, con su indicativo de vuelo, tipo de avión, altitud, velocidad y rumbo. No muestro matrículas, identificadores del transpondedor ni aviones militares.

Ahora mismo están activos los trenes y el tiempo. adsb.lol cuenta las peticiones sin clave por dirección IP (500 al día) y los Workers comparten las suyas, así que el relé recibe 429. He pedido una clave gratuita (1.000 peticiones al día); con ella el relé consulta 4 círculos cada 6 minutos (960 al día) y la guarda como secreto del Worker (`wrangler secret put ADSB_LOL_KEY`), nunca en el repositorio. Hasta entonces la capa de vuelos está apagada en `web/js/ext/live/config.js`.

| Datos | Editor | Licencia |
|---|---|---|
| Posiciones y retrasos de trenes de Cercanías y Larga Distancia (GTFS-RT en JSON) | Renfe | CC BY 4.0 |
| Posiciones ADS-B de aviones | [adsb.lol](https://adsb.lol/) | ODbL 1.0 |
| Predicción municipal de hoy y mañana y avisos meteorológicos | [AEMET](https://www.aemet.es/) | Reutilización con cita, ver [nota legal](https://www.aemet.es/es/nota_legal) |

El mapa muestra la atribución de cada capa activa: "Trenes: Renfe (CC BY 4.0)" y, cuando vuelvan los vuelos, "Vuelos: adsb.lol (ODbL)".

**Tiempo oficial (AEMET).** Para las 68 ciudades el relé lee la predicción municipal de AEMET del municipio principal de cada una (hoy y mañana: cielo, temperatura máxima y mínima, probabilidad de lluvia y viento) y la lista de avisos meteorológicos vigentes (nivel amarillo, naranja o rojo y zona). Los valores se muestran tal como los publica AEMET, sin alterar su contenido técnico, y junto a cada predicción va la hora a la que AEMET la elaboró. Si AEMET no publica un dato, el mapa no pone nada, nunca un 0. Como pide su nota legal, la información va citada así: "Fuente: AEMET" y "© AEMET". No uso el nombre de AEMET para sugerir que patrocina o apoya este proyecto. La respuesta se guarda 30 minutos y cada refresco hace 68 peticiones (una por ciudad) más una de avisos, con 6 en paralelo. Si menos de la mitad de las ciudades responde, el relé sirve la última copia buena con `"stale": true`; una ciudad que falla sola sale con `"days": []`.

**Frecuencia.** Renfe actualiza sus ficheros cada 30 s. El relé guarda cada respuesta 25 s, y el navegador la reutiliza 15 s. Si el origen falla o tarda más de 8 s, el relé sirve la última copia buena (hasta 6 h) con `"stale": true` y la cabecera `X-Live-Stale: 1`.

**Por qué hay un relé.** Ni Renfe ni adsb.lol envían cabeceras CORS, así que el navegador no puede pedirles los datos directamente. Un Cloudflare Worker sin dependencias (`live/worker/`) los descarga, los reduce al formato que usa el mapa y los devuelve con CORS solo para los orígenes de `ALLOWED_ORIGINS`:

- `GET /trains`: `{"updated", "source", "stale", "trains": [{"id", "net", "lat", "lon", "trip", "label", "delay", "status"}]}`
- `GET /flights`: `{"updated", "source", "stale", "flights": [{"id", "type", "lat", "lon", "alt_ft", "gs_kt", "track"}]}`
- `GET /weather`: `{"updated", "source", "stale", "cities": {"<id de ciudad>": {"ine", "name", "elaborado", "days": [{"date", "sky", "sky_text", "tmax", "tmin", "rain_prob", "wind_dir", "wind_kmh"}]}}, "warnings": [{"title", "level", "area", "link"}], "warnings_total"}`

La conversión está en `live/worker/src/transform.js` y `live/worker/src/weather.js` (funciones puras; la lista de ciudades `live/worker/src/cities.js` la genera `tools/gen_live_cities.py` desde `web/data/cities.json`) y se prueba con datos reales recortados:

```
cd live/worker && node --test test/*.test.mjs
```

**Montar tu propio relé.** Necesitas una cuenta gratuita de Cloudflare y `wrangler`.

1. `cd live/worker`
2. Cambia `name` en `wrangler.toml` si quieres otro nombre y añade tu sitio a `ALLOWED_ORIGINS` (separados por comas, sin barra final).
3. `npx wrangler login` y `npx wrangler deploy`. La cuenta se toma de tu entorno, no está en el repositorio.
4. Copia la URL que imprime (`https://<nombre>.<tu-subdominio>.workers.dev`) en `web/js/ext/live/config.js`.

**Presupuesto del plan gratuito de Workers.** Son 100.000 solicitudes al día, 10 ms de CPU por solicitud y 50 subpeticiones por solicitud. Una consulta a `/trains` hace 4 subpeticiones y una a `/flights` hace 4. Un refresco de `/weather` hace 69, más de las 50 que permite el plan gratuito: mi despliegue usa el plan de pago de Workers (1.000 subpeticiones); en el gratuito hay que reducir las ciudades o repartir el refresco en dos. Con los trenes activados, el mapa consulta cada 30 s: unas 2.900 solicitudes al día por visitante con la pestaña abierta todo el día (deja de consultar cuando la pestaña está oculta). Los vuelos sumarían otras tantas. En el plan gratuito eso da para unas treinta personas a la vez durante todo el día. La caché reduce las llamadas a los orígenes, no las solicitudes al Worker. Si el límite se agota, el mapa sigue funcionando sin la capa en directo.

## Licencia

- **Código**: MIT, ver [LICENSE](LICENSE). El código original es © 2026 Andrej Karpathy; mis cambios son © 2026 Daniel
  López.
- **Ficheros de datos en `web/data/`**: derivan de las fuentes de arriba y mantienen sus condiciones. Los datos de
  hexágono a municipio y de hexágono a comunidad autónoma vienen de los límites de GISCO: solo uso no comercial, con
  el aviso de EuroGeographics. No están bajo la licencia MIT. Las descargas en bruto no están en este repositorio.
  `web/data/simple.json` contiene además la geometría simplificada de los municipios, derivada de GISCO LAU: tiene
  las mismas condiciones (solo uso no comercial, © EuroGeographics) y tampoco está bajo la licencia MIT.

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
