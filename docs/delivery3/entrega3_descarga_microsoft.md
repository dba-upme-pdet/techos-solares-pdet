# Entrega 3: descarga de Microsoft Building Footprints

Alcance: `scripts/03_download_ms_buildings.py`, tramo asignado a Miguel. Cubre la descarga, el registro y la verificación de lectura de los archivos de Microsoft. La preparación (validar polígonos, área geodésica, centroide) y la carga en `buildings` son tramos posteriores; este documento les entrega los archivos y su manifiesto.

## Comandos

```bash
python scripts/03_download_ms_buildings.py --plan-only   # índice y selección, sin bajar particiones
python scripts/03_download_ms_buildings.py               # flujo completo (unos 6 min, ~356 MiB)
python scripts/03_download_ms_buildings.py --offline     # reverifica lo ya descargado, sin red
python -m unittest discover -s tests -p "test_download_ms_buildings.py" -v
```

El script lee `sources.microsoft` de `config.yaml` y sale con código distinto de cero si una partición falla o si un municipio PDET queda sin partición. Si se repite, no vuelve a bajar los archivos locales que coinciden con el servidor (`Content-Length` y `Content-MD5` vía `HEAD`). `--offline` exige que cada archivo coincida con el SHA256 del manifiesto anterior y reescribe el manifiesto con `cached = true`.

## Fuente y versión

| Dato | Valor |
| --- | --- |
| Producto | Microsoft Global ML Building Footprints, licencia ODbL-1.0 (<https://github.com/microsoft/GlobalMLBuildingFootprints>) |
| Índice | <https://minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv> (7 171 802 bytes, `Last-Modified` 25 feb 2026, SHA256 `9371e9fd…69f9be6`) |
| Fecha de acceso | 13 nov 2026, 15:21 UTC |
| Versión | `2026-02-03`, la fecha de publicación que aparece en la ruta de todas las URL de Colombia. Las filas del índice traen `UploadDate = 2026-02-23` |
| Partición | Quadkey de Bing Maps, nivel 9 (cuadros de ~0,7° de lado) |
| Formato | GeoJSON Lines con gzip: una `Feature` por línea. El nombre del archivo termina en `.csv.gz`, pero el contenido no es CSV |

El índice trae 232 particiones con `Location = Colombia`. Las 232 pasaron la validación: quadkey de nivel 9, URL https con `RegionName=Colombia` y el mismo quadkey, y una sola versión.

## Selección de particiones

Siguiendo el plan de la Entrega 1, solo se descargan las particiones que tocan territorio PDET. Para cada quadkey se calcula su cuadro Web Mercator en longitud/latitud y se interseca con los 170 municipios de `data/processed/municipalities.geojsonl`, ampliados 0,01° (~1 km) para no perder edificaciones partidas por el borde de un cuadro. El GeoJSONL se usa solo si `outputs/municipalities_prepare_report.json` está en `ready_for_load` y su SHA256 coincide (`612e2544…01f8ed`).

Resultado: **125 de 232 particiones** (≈356 MiB según el índice) tocan algún municipio PDET. Cada partición del manifiesto lista en `pdet_municipalities` los municipios que toca, para que la carga pueda filtrar.

## Cobertura

`outputs/ms_buildings_coverage.csv` trae una fila por municipio con las particiones que lo tocan y la fracción de su área (geodésica, WGS84) que cae dentro de cuadros con partición publicada.

- Los 170 municipios tienen al menos una partición; ninguno queda sin datos.
- 167 municipios quedan cubiertos al 100 %.
- Tres municipios de Macarena–Guaviare quedan cubiertos solo en parte, porque los quadkeys `032233210`, `032233212` y `032233302` tocan territorio PDET pero Microsoft no publica partición para ellos. Son cuadros de selva en Guaviare sin edificaciones detectadas, así que lo esperable es que falten datos y no que la descarga esté incompleta:

| Código | Municipio | Área en particiones publicadas |
| --- | --- | --- |
| 95025 | El Retorno | 66,4 % |
| 95001 | San José del Guaviare | 69,7 % |
| 95200 | Miraflores | 89,0 % |

## Integridad de los archivos

| Control | Resultado |
| --- | --- |
| Particiones descargadas y leídas | 125/125, ninguna fallida |
| Bytes descargados | 373 371 269 (≈356 MiB) |
| `Content-Length` = bytes recibidos | 125/125 |
| `Content-MD5` del servidor = MD5 local | 95/95. Las otras 30 particiones, las más grandes, no traen `Content-MD5` (Azure no lo publica para blobs subidos por bloques); para ellas queda solo la verificación de tamaño |
| SHA256 | Calculado y registrado para el índice y las 125 particiones |
| Descarga atómica | Cada archivo se escribe en `.partial` y se renombra solo si pasa las verificaciones; 3 reintentos |

## Campos, geometrías y sistema de coordenadas

Cada archivo se lee completo con `gzip` + `json` y se analiza con `shapely.from_geojson`.

| Aspecto | Resultado |
| --- | --- |
| Edificaciones | **4 595 615** features en las 125 particiones |
| Claves por feature | `type`, `properties`, `geometry`; no hay `id` |
| Propiedades | `height` y `confidence` en todas las features |
| `height` | −1 (desconocida) en el 100 % de las features de Colombia |
| `confidence` | −1 en 4 595 439 features; solo 176 traen valor (0,76–1,00) |
| Tipos de geometría | Solo `Polygon` |
| Geometrías vacías | 0 |
| Geometrías inválidas (GEOS) | 77 (0,002 %); la preparación las repara con `make_valid` o las rechaza |
| Features fuera de su cuadro quadkey (±0,01°) | 0 |
| Sistema de coordenadas | EPSG:4326 en orden longitud/latitud (GeoJSON RFC 7946). Ningún archivo declara `crs`; todos los centroides caen en el rango de Colombia en ese orden. Extensión: −79,00 a −69,92 de longitud y −1,39 a 11,41 de latitud |

Consecuencias para las siguientes etapas:

- `buildings.height_m` queda en `null` para toda la fuente Microsoft (regla de la Entrega 1 para −1).
- `buildings.confidence` queda en `null` salvo 176 casos, así que el umbral `min_confidence` no se puede aplicar a Microsoft; se aplica solo a Google.
- No hay identificador original: `source_ref` se arma con archivo + número de línea, como prevé el diccionario de datos.
- No hace falta reproyectar: las coordenadas ya están en el CRS que exige el índice `2dsphere`.

## Contrato para la preparación y la carga

| Pieza | Contenido | Condición |
| --- | --- | --- |
| `outputs/ms_buildings_download_manifest.json` | `source`, `index`, `selection`, `totals` y una entrada por partición con `quadkey`, `url`, `release`, `upload_date`, `local_path`, `bounds`, `pdet_municipalities`, `download` (bytes, MD5, SHA256, `ETag`, `Last-Modified`) e `inspection` | Usar solo si `status = complete` y `claims_pdet_coverage = true` |
| `datasets_document` dentro del manifiesto | `_id = ms`, nombre, versión `2026-02-03`, licencia, URL y `accessed_at`: el documento de `datasets` que exige el validador de `00_init_db.py` | La carga lo inserta con `accessed_at` como fecha BSON |
| `data/raw/ms_buildings/2026-02-03/quadkey=<qk>/part-*.csv.gz` | Archivos originales, sin modificar | Fuera de git; comprobar el SHA256 del manifiesto antes de cargar |
| `data/raw/ms_buildings/dataset-links.csv` | Índice tal como se descargó | Fuera de git |
| `outputs/ms_buildings_coverage.csv` | Cobertura por municipio | Versionado |

Para reproducir los archivos en otra máquina basta con correr el script: la URL de cada partición incluye la versión, y el manifiesto permite comprobar que los bytes son los mismos.

## Pruebas

`tests/test_download_ms_buildings.py` tiene 15 pruebas con datos sintéticos, sin red ni MongoDB: conversión quadkey ↔ cuadro (incluye una partición real de San Andrés), lectura del índice (filtro por país, cero inicial perdido, URL que no corresponde, columnas faltantes), selección y cobertura, lectura de campos y CRS, ejes invertidos, archivo truncado, MD5 y SHA256, y el modo offline. Resultado local: 15/15 OK.
