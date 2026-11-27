# Privacidad

## Qué publica este repositorio

- Solo agregados: códigos (INE, provincia, comunidad), nombres de organismos públicos y números.
- Cifras de delitos conocidos por municipio, provincia y comunidad (Ministerio del Interior).
- Recuentos de disposiciones del BOJA por año, sección y organismo emisor.
- Contratación menor de la Junta de Andalucía agregada por provincia y órgano de contratación: número de contratos, euros sin IVA, ofertas únicas y tramos de importe.

## Qué no publica nunca

- Nombres, NIF, DNI o NIE de personas físicas ni de autónomos.
- Adjudicatarios, licitadores, títulos, descripciones o textos de anuncios.
- Datos de contacto, direcciones de personas ni filas individuales de contratos.
- Los ficheros descargados en bruto: viven en `data/raw/` y `data/interim/`, que Git ignora.

Los emisores del BOJA que no parecen un organismo público se agrupan como "Otros emisores", sin nombre. El pipeline
comprueba la estructura de cada fichero de salida antes de escribirlo y rechaza claves de persona y patrones de
DNI, NIE o NIF. Los tests usan solo datos inventados.

## Cómo pedir una retirada

1. Abre una incidencia (Issue) en GitHub de este repositorio.
2. Indica la página, el fichero o la fila donde lo has visto.
3. No pegues el dato personal en la incidencia: basta con señalar dónde está.

Lo revisaré y, si procede, lo retiraré del repositorio y de su historial.
