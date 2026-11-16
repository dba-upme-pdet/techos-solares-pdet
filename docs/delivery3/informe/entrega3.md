---
title: "Entrega 3: Carga e integración de huellas de edificaciones"
subtitle: "Proyecto final - Techos solares en municipios PDET para la UPME"
author: "Miguel Duarte · Samuel Emperador · José Medina · Sebastián Sánchez · Derek Sarmiento Loeber"
date: "Administración y Aplicaciones de Bases de Datos (4055), PUJ 2026-30 · 16 de noviembre de 2026"
lang: es
---

# 1. Resumen

Esta entrega carga en MongoDB 7 (colección `upme_pdet.buildings`) las huellas de edificaciones de dos fuentes abiertas: **Microsoft Global ML Building Footprints** y **Google Open Buildings v3**. Las huellas se recortan a los 170 municipios PDET que integró la Entrega 2 desde el MGN2025 del DANE. El flujo tiene cuatro tramos: descarga, preparación con un contrato común, carga idempotente con índices espaciales y verificación. El código vive en `scripts/` del repositorio `dba-upme-pdet/techos-solares-pdet`.

**Tabla 1. Resultado de las dos cargas**

| Indicador | Microsoft | Google |
| --- | ---: | ---: |
| Registros leídos de la fuente | 4 595 615 | 31 499 115 |
| Excluidos por caer fuera de los PDET | 2 834 537 | 28 804 201 |
| Rechazados en la preparación | 48 (29 reparados) en la pasada sin filtro | 139 (MultiPolygon) |
| Cargados en `buildings` | 1 761 030 | 2 694 775 |
| Rechazados en la carga | 0 | 0 |
| Municipios PDET con edificaciones | 170 de 170 | 165 de 170 |
| Área geodésica cargada | 220 976 634 m² | 222 051 169 m² |
| Segunda pasada (idempotencia) | 0 insertadas, 0 actualizadas | 0 insertadas, 0 actualizadas |
| Tiempo de carga (dos pasadas) | 101,95 s | 153,29 s |
| Memoria máxima del proceso | ~320 MiB | ~256 MiB |
| Índices | `centroid_2dsphere`, `dataset_id_1_mpio_code_1` | los mismos |
| Consulta `$geoWithin` de prueba | `IXSCAN` sobre `centroid_2dsphere` | 2 983 de 2 983 dentro, `IXSCAN` |

Tras las dos cargas, `upme_pdet.buildings` tiene **4 455 805 documentos**.

# 2. Requisitos de la entrega y dónde se cumplen

El enunciado pide para la Entrega 3 los mismos requisitos de la Entrega 2, aplicados a las dos fuentes, más la eficiencia de carga y un EDA breve. La rúbrica de la semana 4 asigna esos pesos.

**Tabla 2. Cobertura de la rúbrica**

| Criterio (peso) | Dónde se demuestra |
| --- | --- |
| Data Acquisition & Verification (10) | Secciones 5 y 6: fuente, versión, particiones, manifiestos con SHA256, cobertura |
| Data Integrity & Format (10) | Sección 7: contrato `entrega3-buildings-v1`, reparaciones, rechazos, validador estricto de MongoDB |
| NoSQL Spatial Integration | Secciones 1 y 8: índice `2dsphere` y consulta `$geoWithin` con `IXSCAN` |
| Data Loading Efficiency (25) | Sección 3 y sección 8 |
| Brief EDA (10) | Sección 4 |

# 3. Eficiencia en la carga de grandes volúmenes

Google entrega 31,5 millones de filas en 3,1 GB comprimidos, así que ninguna etapa puede cargar una fuente completa en memoria. El equipo usó estas técnicas:

1. **Selección previa de particiones.** Solo se descargan las particiones que tocan Colombia: 125 de Microsoft y 8 celdas S2 de Google. Así no se descarga el resto del mundo.
2. **Lectura en flujo.** La preparación y la carga leen cada GeoJSON Lines con gzip línea por línea. La memoria no crece con el tamaño del archivo: la carga usó como máximo ~320 MiB (Microsoft) y ~256 MiB (Google).
3. **Filtro espacial antes de la carga.** El centroide de cada huella se asigna a su municipio PDET durante la preparación. Se descartan 2,8 millones de huellas de Microsoft y 28,8 millones de Google antes de escribir en la base.
4. **Escritura por lotes.** La carga usa `bulk_write` en lotes de 10 000 documentos, no una inserción por documento.
5. **`_id` determinista e idempotencia.** Cada documento tiene `_id = <dataset_id>:<blake2b-96(dataset_id + source_ref)>`. Si la carga se repite, escribe sobre los mismos documentos y no crea duplicados. La segunda pasada de cada fuente dejó 0 inserciones y 0 modificaciones.
6. **Índices pensados para la Entrega 4.** `centroid_2dsphere` responde consultas espaciales y `dataset_id_1_mpio_code_1` agrupa por fuente y municipio para el conteo y el área de techos.
7. **Compuerta de contrato.** La carga se niega a empezar si el reporte de preparación no está balanceado o si un SHA256 no coincide. Así nunca se carga un archivo incompleto.

# 4. Análisis exploratorio breve (EDA)

Los datos de esta sección salen de `outputs/buildings_ms_prepared_by_municipality.csv` y `outputs/buildings_google_prepared_by_municipality.csv`, que la preparación genera por municipio.


- **Microsoft:** 1 761 030 edificaciones en 170 municipios PDET. Por municipio: mediana 8 161, mínimo 653, máximo 67 663 edificaciones. Mediana del área de huella por municipio: 75.3 m².
- **Google:** 2 694 775 edificaciones en 165 municipios PDET. Por municipio: mediana 11 018, mínimo 1, máximo 183 651 edificaciones. Mediana del área de huella por municipio: 57.3 m².
- Las dos fuentes tienen huellas en 165 municipios comunes. Google no tiene huellas en 5 municipios: Bojayá, Medio San Juan, Murindó, Nóvita, Vigía Del Fuerte.
- Google detecta 53 % más edificaciones que Microsoft, pero más pequeñas: el área total es casi igual (222,1 frente a 221,0 km²). La Entrega 4 compara las dos fuentes por municipio.

![Figura 1. Diez municipios PDET con más edificaciones en Microsoft, comparados con Google. Fuente: `outputs/buildings_*_prepared_by_municipality.csv`.](top10.png){width=95%}

**Tabla 3. Diez municipios PDET con más edificaciones (orden por Microsoft)**

| Código | Municipio | Edif. MS | Área MS (m²) | Edif. Google | Área Google (m²) |
| --- | --- | ---: | ---: | ---: | ---: |
| 47001 | Santa Marta | 67 663 | 14 224 995 | 183 651 | 15 985 602 |
| 20001 | Valledupar | 63 722 | 13 532 275 | 171 424 | 15 330 297 |
| 05837 | Turbo | 43 360 | 4 650 298 | 78 926 | 6 021 598 |
| 52835 | San Andrés De Tumaco | 41 421 | 4 487 085 | 50 493 | 3 761 508 |
| 54810 | Tibú | 35 478 | 3 575 163 | 32 843 | 2 640 872 |
| 19256 | El Tambo | 34 366 | 3 042 677 | 38 900 | 2 441 932 |
| 76109 | Buenaventura | 33 105 | 7 122 333 | 103 889 | 7 632 670 |
| 19698 | Santander De Quilichao | 30 842 | 4 225 852 | 35 691 | 3 834 722 |
| 23807 | Tierralta | 30 255 | 2 971 069 | 43 123 | 3 074 969 |
| 81065 | Arauquita | 27 815 | 3 319 887 | 35 077 | 2 921 882 |

**Lectura.** Microsoft tiene huellas en todos los municipios PDET, y Google deja 5 sin datos. Por eso, en la Entrega 4 Microsoft es la fuente base del conteo, y Google sirve para contrastar. La diferencia en el tamaño típico de huella muestra que las fuentes detectan las edificaciones de forma distinta. Por lo tanto, la Entrega 4 debe reportar el resultado de cada fuente por separado y no sumarlas.

**Limitaciones.** El EDA es descriptivo: el número y el área aprovechable de techos por municipio son el objetivo de la Entrega 4. El contrato actual rechaza 139 geometrías MultiPolygon de Google. El WFS del DANE puede cortar la conexión TLS desde algunas redes, y esto afecta la regeneración de la capa municipal.



# 5. Descarga de Microsoft Building Footprints

Alcance: `scripts/03_download_ms_buildings.py`, tramo asignado a Miguel. Cubre la descarga, el registro y la verificación de lectura de los archivos de Microsoft. La preparación (validar polígonos, área geodésica, centroide) y la carga en `buildings` son tramos posteriores; este documento les entrega los archivos y su manifiesto.

### Comandos

```bash
python scripts/03_download_ms_buildings.py --plan-only   # índice y selección, sin bajar particiones
python scripts/03_download_ms_buildings.py               # flujo completo (unos 6 min, ~356 MiB)
python scripts/03_download_ms_buildings.py --offline     # reverifica lo ya descargado, sin red
python -m unittest discover -s tests -p "test_download_ms_buildings.py" -v
```

El script lee `sources.microsoft` de `config.yaml` y sale con código distinto de cero si una partición falla o si un municipio PDET queda sin partición. Si se repite, no vuelve a bajar los archivos locales que coinciden con el servidor (`Content-Length` y `Content-MD5` vía `HEAD`). `--offline` exige que cada archivo coincida con el SHA256 del manifiesto anterior y reescribe el manifiesto con `cached = true`.

### Fuente y versión

| Dato | Valor |
| --- | --- |
| Producto | Microsoft Global ML Building Footprints, licencia ODbL-1.0 (<https://github.com/microsoft/GlobalMLBuildingFootprints>) |
| Índice | <https://minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv> (7 171 802 bytes, `Last-Modified` 25 feb 2026, SHA256 `9371e9fd…69f9be6`) |
| Fecha de acceso | 13 nov 2026, 15:21 UTC |
| Versión | `2026-02-03`, la fecha de publicación que aparece en la ruta de todas las URL de Colombia. Las filas del índice traen `UploadDate = 2026-02-23` |
| Partición | Quadkey de Bing Maps, nivel 9 (cuadros de ~0,7° de lado) |
| Formato | GeoJSON Lines con gzip: una `Feature` por línea. El nombre del archivo termina en `.csv.gz`, pero el contenido no es CSV |

El índice trae 232 particiones con `Location = Colombia`. Las 232 pasaron la validación: quadkey de nivel 9, URL https con `RegionName=Colombia` y el mismo quadkey, y una sola versión.

### Selección de particiones

Siguiendo el plan de la Entrega 1, solo se descargan las particiones que tocan territorio PDET. Para cada quadkey se calcula su cuadro Web Mercator en longitud/latitud y se interseca con los 170 municipios de `data/processed/municipalities.geojsonl`, ampliados 0,01° (~1 km) para no perder edificaciones partidas por el borde de un cuadro. El GeoJSONL se usa solo si `outputs/municipalities_prepare_report.json` está en `ready_for_load` y su SHA256 coincide (`612e2544…01f8ed`).

Resultado: **125 de 232 particiones** (≈356 MiB según el índice) tocan algún municipio PDET. Cada partición del manifiesto lista en `pdet_municipalities` los municipios que toca, para que la carga pueda filtrar.

### Cobertura

`outputs/ms_buildings_coverage.csv` trae una fila por municipio con las particiones que lo tocan y la fracción de su área (geodésica, WGS84) que cae dentro de cuadros con partición publicada.

- Los 170 municipios tienen al menos una partición; ninguno queda sin datos.
- 167 municipios quedan cubiertos al 100 %.
- Tres municipios de Macarena–Guaviare quedan cubiertos solo en parte, porque los quadkeys `032233210`, `032233212` y `032233302` tocan territorio PDET pero Microsoft no publica partición para ellos. Son cuadros de selva en Guaviare sin edificaciones detectadas, así que lo esperable es que falten datos y no que la descarga esté incompleta:

| Código | Municipio | Área en particiones publicadas |
| --- | --- | --- |
| 95025 | El Retorno | 66,4 % |
| 95001 | San José del Guaviare | 69,7 % |
| 95200 | Miraflores | 89,0 % |

### Integridad de los archivos

| Control | Resultado |
| --- | --- |
| Particiones descargadas y leídas | 125/125, ninguna fallida |
| Bytes descargados | 373 371 269 (≈356 MiB) |
| `Content-Length` = bytes recibidos | 125/125 |
| `Content-MD5` del servidor = MD5 local | 95/95. Las otras 30 particiones, las más grandes, no traen `Content-MD5` (Azure no lo publica para blobs subidos por bloques); para ellas queda solo la verificación de tamaño |
| SHA256 | Calculado y registrado para el índice y las 125 particiones |
| Descarga atómica | Cada archivo se escribe en `.partial` y se renombra solo si pasa las verificaciones; 3 reintentos |

### Campos, geometrías y sistema de coordenadas

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

### Contrato para la preparación y la carga

| Pieza | Contenido | Condición |
| --- | --- | --- |
| `outputs/ms_buildings_download_manifest.json` | `source`, `index`, `selection`, `totals` y una entrada por partición con `quadkey`, `url`, `release`, `upload_date`, `local_path`, `bounds`, `pdet_municipalities`, `download` (bytes, MD5, SHA256, `ETag`, `Last-Modified`) e `inspection` | Usar solo si `status = complete` y `claims_pdet_coverage = true` |
| `datasets_document` dentro del manifiesto | `_id = ms`, nombre, versión `2026-02-03`, licencia, URL y `accessed_at`: el documento de `datasets` que exige el validador de `00_init_db.py` | La carga lo inserta con `accessed_at` como fecha BSON |
| `data/raw/ms_buildings/2026-02-03/quadkey=<qk>/part-*.csv.gz` | Archivos originales, sin modificar | Fuera de git; comprobar el SHA256 del manifiesto antes de cargar |
| `data/raw/ms_buildings/dataset-links.csv` | Índice tal como se descargó | Fuera de git |
| `outputs/ms_buildings_coverage.csv` | Cobertura por municipio | Versionado |

Para reproducir los archivos en otra máquina basta con correr el script: la URL de cada partición incluye la versión, y el manifiesto permite comprobar que los bytes son los mismos.

### Pruebas

`tests/test_download_ms_buildings.py` tiene 15 pruebas con datos sintéticos, sin red ni MongoDB: conversión quadkey ↔ cuadro (incluye una partición real de San Andrés), lectura del índice (filtro por país, cero inicial perdido, URL que no corresponde, columnas faltantes), selección y cobertura, lectura de campos y CRS, ejes invertidos, archivo truncado, MD5 y SHA256, y el modo offline. Resultado local: 15/15 OK.



# 6. Descarga de Google Open Buildings v3

### Fuente e interfaz comprobadas

Fuente primaria: Google Research Open Buildings, apartados Data format, Download y licencia; catálogo oficial de Earth Engine. Se utiliza el producto **vectorial v3**, inferencia de mayo de 2023, no el producto temporal ráster. Google ofrece CC BY 4.0 u ODbL 1.0 a elección; aquí se registra **CC-BY-4.0**.

El enlace de metadatos de la página oficial conduce al índice GeoJSON, con 333 celdas S2 nivel 4 y propiedades `tile_id`, `tile_url`, `size_mb`. Se constató que la antigua ruta `sites.research.google/open-buildings/tiles.geojson` devuelve 404; no se usa. Las URLs de datos se obtienen del índice y se verifican contra el prefijo oficial del producto v3.

El original es **CSV con gzip**, no GeoJSONL aunque Microsoft utilice un nombre parecido. Sus seis columnas son `latitude`, `longitude`, `area_in_meters`, `confidence`, `geometry` (WKT Polygon/MultiPolygon) y `full_plus_code`. Las posiciones son longitud/latitud geográficas interpretadas como WGS84/EPSG:4326. No hay altura. La publicación de Google ya tiene un umbral de detección; la adquisición del proyecto no añade filtros de confianza ni elimina registros originales.

### Procedimiento y seguridad de la ejecución

`scripts/03_download_google_buildings.py`:

1. Descarga el índice oficial y registra ruta, URL, bytes, SHA256, ETag, Last-Modified y MD5 publicado cuando existe.
2. Lee el GeoJSONL municipal, exige hash consistente y exactamente los 170 códigos oficiales del Excel. Selecciona las celdas que intersectan los polígonos; comprueba que su unión cubra todos los límites (tolerancia numérica 1e-8 grados).
3. Registra el plan, el volumen comprimido aproximado y espacio libre antes de descargar. `--plan-only` no descarga archivos de polígonos ni declara éxito completo; escribe `google_buildings_download_plan.json`, separado del manifiesto definitivo.
4. Descarga en bloques de 1 MiB a `.part`. Comprueba Content-Length y MD5 del servidor cuando se publica y calcula SHA256. Solo publica el archivo original tras terminar; un fallo elimina únicamente su temporal, conservando el archivo anterior. Los archivos registrados de una corrida previa se reutilizan solo si tamaño y SHA256 coinciden. `downloaded` es un checkpoint de bytes, no de inspección completa.
5. Lee **todo** el gzip, incluida su integridad/CRC al llegar al fin, en bloques de 10.000 registros. Comprueba columnas, parseo WKT, topología, tipo poligonal, coordenadas geográficas finitas, área positiva y confianza en [0,1]. Registra cantidades, tipos y rangos sin modificar los originales. Una partición con errores no se declara `ok`.
6. Escribe `complete` y `claims_pdet_coverage: true` únicamente si todas las particiones requeridas aprobaron y no quedaron límites municipales sin cubrir. Verifica el manifiesto con `download_manifest_problems(manifest, "google")`.

La cobertura afirmada es **cobertura por particiones descargadas y legibles**, no una garantía de que Google detectó edificios en cada municipio ni de exhaustividad del modelo. No se cuentan aquí edificios PDET por centroide: eso corresponde a la preparación, que debe excluir lo externo a los municipios. Los tiles incluyen territorio fuera de Colombia; se verifican rangos WGS84 globales durante adquisición. Las limitaciones y omisiones de detección de Google permanecen aplicables.

### Datos municipales y procedencia del contrato

Al iniciar faltaban los datos municipales locales. Se ejecutó el descargador oficial MGN en un directorio temporal con copias de configuración/reportes: descargó las seis páginas, todas coincidentes por contenido con el recibo, y produjo la capa nacional de 1122 municipios. Después se ejecutó el preparador oficial en otro entorno aislado, compartiendo únicamente el destino `data/`. Produjo los 170 municipios y recuperó el SHA256 esperado:

`612e2544be7ca2c22285aaac647819b910aa779ce61e1e5b872766051101f8ed`.

La evidencia resumida está en `outputs/google_municipalities_regeneration_evidence.json`; los originales y el manifiesto de regeneración quedan en `data/`, ignorados por Git. **No se sobrescribieron los reportes definitivos de la Entrega 2 ni se cargó MongoDB.**

Se incorporó únicamente `scripts/entrega3_contracts.py` desde `origin/entrega3/preparacion-huellas-ms`, commit **`1e3fdee`**, sin modificaciones: SHA256 `1537b3a7d5a10a315c41337139ea8eaa349501275f7a5e782c2021c147e8da2f`. No se fusionó esa rama ni su preparador. Así se usan directamente el validador y el contrato de Derek, sin duplicarlos. La futura integración de la rama deberá conservar el mismo archivo compartido.

### Comandos

Desde la raíz, con las dependencias actuales de `requirements.txt`:

```bash
.venv/bin/python scripts/03_download_google_buildings.py --plan-only
.venv/bin/python scripts/03_download_google_buildings.py
# Muestra explícita, no equivale a descarga PDET completa:
.venv/bin/python scripts/03_download_google_buildings.py --probe-tile 8df
.venv/bin/python -m unittest discover -s tests -p test_download_google_buildings.py -v
```

La CLI devuelve 0 solo para una descarga completa que cumple el contrato. Los planes, muestras y fallos devuelven 1. `--probe-tile` usa una sola celda y deja `claims_pdet_coverage: false`; su salida `google_buildings_probe_manifest.json` está separada de la evidencia completa. Una repetición sin opciones revalida archivos originales; la integridad de caché se contrasta con los hashes guardados de la corrida anterior, no constituye una consulta de novedades remotas.

La comprobación de integración sintética con el preparador de Derek se ejecutó así (sin editar el archivo recuperado):

```bash
git show origin/entrega3/preparacion-huellas-ms:scripts/03_prepare_buildings.py \
  > /tmp/derek_03_prepare_buildings.py
DEREK_PREPARER_PATH=/tmp/derek_03_prepare_buildings.py \
  .venv/bin/python -m unittest discover -s tests -p test_download_google_buildings.py -v
```

### Entrega a Derek: manifiesto y lector son interfaces distintas

Archivos de entrada:

- `outputs/google_buildings_download_manifest.json`: `datasets_document` y particiones `partition_id`, `url`, `local_path`, `download.bytes`, `download.sha256`, inspección y estado.
- `data/raw/google_buildings/<tile_id>_buildings.csv.gz`: CSV.gz originales, fuera de Git. Transferirlos con su manifiesto o descargarlos con el script; no basta recibir el JSON del manifiesto sin sus archivos.
- `scripts/google_buildings_adapter.py`: lector en flujo `google_features(path)` y función `google_attributes(props)`.

El adaptador entrega `(número de registro CSV, Feature|None)`. Convierte WKT en GeoJSON sin reparar ni simplificar. Los atributos devueltos al preparador son `area_src_m2 = area_in_meters`, `confidence` conservada y `height_m = None`. El Plus Code permanece en `properties`; `source_ref` lo construye Derek con partición, archivo y número de registro, como ya hace con Microsoft. Un registro ilegible produce `None` para rechazo explícito, no una omisión silenciosa. MultiPolygon permanece MultiPolygon: el preparador actual solo admite Polygon y debe registrar su rechazo o decidir una regla explícita, sin alterarla en esta adquisición.

**El lector separado está implementado y probado; su registro en el preparador publicado sigue pendiente de Derek.** Su `SOURCES` solo contiene `ms`. Debe incorporar:

```python
from google_buildings_adapter import google_features, google_attributes
SOURCES["google"] = {
    "config_key": "google",
    "features": google_features,
    "attributes": google_attributes,
}
```

Las rutas `sources.google.prepare_report`, `prepare_by_municipality` y `source_pass_report` están configuradas. La configuración `processing.buildings` procede de la rama de preparación de Derek. Después de registrar el lector e integrar su preparador, el comando será:

```bash
.venv/bin/python scripts/03_prepare_buildings.py --source google
```

Ese comando **no está disponible todavía en este checkout**: no se importó ni reemplazó el preparador de Derek. La prueba ejecutada solo registra el adaptador temporalmente en memoria y llama `prepare_partition` sobre un CSV sintético: comprueba área geodésica calculada, área original, confianza, estructura y `dataset_id=google`, sin afirmar preparación real de millones de edificios.

### Samuel / EDA

Se inspeccionaron `03_load_buildings.py`, `04_prepare_ms_buildings.py` y `eda_spatial_analysis.py` en `origin/feature/entrega3-eda` (`01a566b`). Utilizan otra entrada Microsoft y, en algunos puntos, claves `CONFIG["mongodb"]` y campos `geometry`/`geometry_centroid`; el esquema compartido del proyecto usa `mongo` y `footprint`/`centroid`. No se adaptó Google a esos nombres incompatibles ni se modificó su rama. Samuel y la carga deben coordinar esa interfaz con `entrega3_contracts.py` y los reportes preparados de Derek antes de comparar fuentes. No se ejecutó EDA ni se atribuyen cargas o métricas MongoDB a esta adquisición.

### Pruebas sintéticas y evidencia real

`google_download_tests.txt` registra **8/8 pruebas aprobadas**, incluida la integración sintética con el preparador upstream. Cubren selección y cobertura incompleta, índice inválido/duplicado, tamaños y MD5 incorrectos, conservación del archivo anterior y limpieza temporal, repetición segura y corrupción de caché, columnas/gzip inválidos, WKT/atributos y ausencia de un filtro adicional de confianza. Sin `DEREK_PREPARER_PATH`, ese caso de integración se marca omitido explícitamente; las otras siete pruebas son independientes.

La regeneración municipal, el índice y la inspección de CSV reales se distinguen de esas pruebas. El resultado de adquisición actual y sus magnitudes se resumen a continuación desde el manifiesto, sin inferir resultados de preparación o EDA.


### Resultado real del 16 de noviembre de 2026

**Adquisición completa:** 8 particiones, **3,110,075,800 bytes comprimidos** (3.110 GB decimales), **31,499,115 registros CSV leídos íntegramente** y cero filas inválidas detectadas en estos archivos. Son filas de tiles completos, no un conteo de edificios asignados a PDET.

| Partición S2 | Bytes comprimidos | Registros leídos | Estado |
| --- | ---: | ---: | --- |
| `8e1` | 27247257 | 277823 | ok |
| `8e3` | 683305918 | 6821072 | ok |
| `8e5` | 572958296 | 5800973 | ok |
| `8e7` | 596659569 | 6021057 | ok |
| `8e9` | 595261949 | 6132325 | ok |
| `8ef` | 139802560 | 1461800 | ok |
| `91d` | 459727938 | 4620572 | ok |
| `91f` | 35112313 | 363493 | ok |

El manifiesto registra `complete`, `claims_pdet_coverage: true`, 170 municipios y ningún límite fuera de la unión de particiones. **El validador común devuelve cero problemas**. Se recalcularon los ocho SHA256 mediante `verify_partition_file`, y el contrato incorporado se comparó byte por byte con el upstream. Las estadísticas completas de geometría, coordenadas, áreas y confianza quedan en cada `inspection` del manifiesto. No se aplicó el umbral provisional de confianza del análisis.

El plan inicial estimó 3.110.100.000 bytes comprimidos; había unos 16,5 GB libres. Las particiones se descargaron secuencialmente y se inspeccionaron por bloques. Se interrumpió la primera inspección lenta para pasar a bloques vectorizados; se preservó el CSV 8e3, se contrastaron nuevamente su tamaño y MD5 con el servidor y se reanudó sin alterar el archivo. El manifiesto definitivo registra reutilización verificada de 8e1 y 8e3. Una ejecución posterior de `--plan-only` dejó intacto el manifiesto definitivo y los datos; su plan separado está en `outputs/google_buildings_download_plan.json`.

Además se conserva una muestra de formato explícita `8df` (2.179.392 bytes y 22.806 registros) en `data/raw/google_buildings/`, **fuera de las ocho particiones PDET seleccionadas**. Su evidencia está en `outputs/google_buildings_probe_evidence.json`; no se suma al conteo del plan completo ni prueba cobertura PDET. El índice ocupa 250.366 bytes. Los archivos originales permanecen fuera de Git.

Se ejecutaron también juntas las pruebas de descarga Microsoft y Google: **23/23 aprobadas** (15 de Microsoft y 8 de Google, incluida la prueba con el preparador upstream). Son pruebas sintéticas; el conteo de registros reales anterior proviene de la lectura completa, no de fixtures.

**Alcance cerrado:** adquisición Google, integridad de archivos, selección/cobertura de particiones, manifiesto compatible y adaptador independiente probado. **Pendiente de integración del equipo:** Derek debe registrar el lector en su preparador y ejecutar la preparación espacial real; después corresponde la carga y el EDA. No se declaran esos pasos realizados.

La inspección real encontró **139 MultiPolygon** entre las 31.499.115 filas; las restantes 31.498.976 son Polygon. No se convirtieron ni descartaron. El preparador de Derek los rechaza antes de la selección municipal por su regla de Polygon; deberá decidir y documentar ese tratamiento. No se ha determinado cuántos de esos MultiPolygon pertenecen a PDET. La prueba del adaptador confirma que conserva también ese tipo.

### Cierre y traspaso a Derek

Se consultaron nuevamente las referencias remotas antes de integrar este aporte. La rama de preparación sigue en `1e3fdee`: su contrato es idéntico al incorporado y su registro de fuentes sigue conteniendo solo Microsoft. Se repitió la prueba sintética contra ese preparador vigente sin modificarlo. La adquisición no necesita una corrección de interfaz para poder integrarse; registrar el lector es un paso de preparación separado.

La verificación de traspaso está en `outputs/google_buildings_handoff_verification.json`: se recalcularon los SHA256 de los ocho archivos locales y se comprobaron tamaños, índice y límites municipales contra sus reportes. No se repitieron descargas ni se sobrescribió el manifiesto definitivo. Las 23 pruebas combinadas de descarga volvieron a aprobar (15 Microsoft y 8 Google, incluida la prueba con el preparador de Derek). La lectura integral de los 31.499.115 registros es la ejecución de adquisición documentada anteriormente, no una nueva inspección en este cierre.

#### Paquete exacto que debe disponer en su computador

| Pieza | Ruta o archivos | Estado del traspaso |
| --- | --- | --- |
| Código, contrato y adaptador | `scripts/03_download_google_buildings.py`, `scripts/entrega3_contracts.py`, `scripts/google_buildings_adapter.py`, configuración Google y pruebas | Se publican en Git; debe incorporar el `main` que contiene este aporte a su trabajo |
| Manifiesto de adquisición | `outputs/google_buildings_download_manifest.json` | Versionado; es la referencia de URLs, tamaños y hashes |
| Originales Google | En `data/raw/google_buildings/`: `8e1_buildings.csv.gz`, `8e3_buildings.csv.gz`, `8e5_buildings.csv.gz`, `8e7_buildings.csv.gz`, `8e9_buildings.csv.gz`, `8ef_buildings.csv.gz`, `91d_buildings.csv.gz`, `91f_buildings.csv.gz` | Disponibles y verificados en este Mac; **no se ha confirmado que Derek los haya recibido**. Total: 3.110.075.800 bytes |
| Índice de referencia | `data/raw/google_buildings/tiles.geojson` | Conservado localmente; URL y hash en el manifiesto. El preparador consume las particiones, pero el índice permite auditar la selección |
| Límites municipales | `data/processed/municipalities.geojsonl` | Disponible localmente; debe transferirse o regenerarse con el flujo oficial |
| Reporte de los límites | `outputs/municipalities_prepare_report.json` | Versionado; debe corresponder al archivo recibido. SHA256 esperado: `612e2544be7ca2c22285aaac647819b910aa779ce61e1e5b872766051101f8ed` |

La muestra `8df` no forma parte de este paquete PDET; no es necesaria para preparar la fuente. Los archivos pesados no se incorporan a GitHub. Su transferencia debe conservar los bytes y las rutas indicadas; otra alternativa es descargarlos desde las URLs oficiales del manifiesto. Este cierre no envía archivos ni mensajes a Derek ni certifica su recepción.

#### Verificar lo recibido sin red ni descargas

Desde la raíz del checkout con estos scripts y dependencias, ejecutar:

```bash
.venv/bin/python - <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, 'scripts')
from entrega3_contracts import (
    download_manifest_problems, verify_partition_file, load_pdet_layer,
)
root = Path.cwd()
manifest = json.loads((root / 'outputs/google_buildings_download_manifest.json').read_text())
problems = download_manifest_problems(manifest, 'google')
if problems:
    raise SystemExit('\n'.join(problems))
for part in manifest['partitions']:
    path, digest = verify_partition_file(root, part)
    assert path.stat().st_size == part['download']['bytes'], str(path)
    print(part['partition_id'], path.stat().st_size, digest, 'OK')
municipalities, digest = load_pdet_layer(
    root, 'data/processed/municipalities.geojsonl',
    'outputs/municipalities_prepare_report.json', 170,
)
assert digest == manifest['selection']['municipal_sha256']
print('Contrato, ocho archivos y 170 límites municipales: OK')
PY
```

Este comando falla si falta un archivo o no coincide con su referencia; no corrige ni omite las diferencias. No necesita MongoDB. El manifiesto compartido es compatible con preparación, pero ese resultado por sí solo no registra el lector en su programa.

#### Si necesita obtener los archivos otra vez

1. Conservar una copia del manifiesto de referencia recibido para comparar la nueva ejecución. Si ya recibió los ocho archivos correctos, usar la verificación anterior y evitar una descarga repetida.
2. Obtener primero el GeoJSONL municipal con su reporte. Alternativamente, con acceso al WFS del DANE, regenerarlo mediante `01_download_mgn.py`, `01_validate_mgn.py` y `02_prepare_municipalities.py`. Esos comandos producen sus propios reportes de corrida y deben ejecutarse en un checkout/entorno de reproducción, sin sustituir las evidencias originales compartidas.
3. Con los límites consistentes, ejecutar:

```bash
.venv/bin/python scripts/03_download_google_buildings.py --plan-only
.venv/bin/python scripts/03_download_google_buildings.py
```

El plan permite revisar selección, volumen y espacio antes de descargar. El descargador valida y reutiliza los archivos registrados que ya coinciden. Una nueva corrida tendrá metadatos de su propio entorno; debe comparar los hashes con la referencia y no confundirla con una entrega de archivos que todavía no ocurrió.

#### Pendientes separados por responsabilidad

- **Adquisición de Sebastián cerrada:** fuente oficial, ocho originales, integridad, cobertura por particiones, manifiesto validado, adaptador y pruebas, documentación y comandos de traspaso. La evidencia de cierre no altera las evidencias de adquisición.
- **Coordinación / transferencia:** acordar con Derek la copia o descarga de los ocho CSV.gz y el archivo municipal; ejecutar la verificación en su computador y confirmar recepción. Solo hay evidencia de disponibilidad local, no de recepción remota.
- **Preparación de Derek:** incorporar su preparador y configuración `processing.buildings`, registrar `google_features` / `google_attributes` en `SOURCES["google"]`, y decidir/documentar cómo tratar los **139 MultiPolygon** frente al esquema Polygon. No se conoce todavía cuántos pertenecen a PDET. El lector conserva esos registros; no se cambió la lógica de Derek ni se ejecutó la preparación real de la fuente.
- **Carga y EDA:** corresponden a sus responsables una vez exista la salida preparada; no se atribuyen resultados MongoDB o EDA a este cierre.



# 7. Preparación de huellas de edificaciones

Alcance: `scripts/03_prepare_buildings.py` y `scripts/entrega3_contracts.py`, tramo asignado a Derek. Toma las particiones que entrega un módulo de descarga, las convierte en documentos de la colección `buildings` del esquema de la Entrega 1 y deja un reporte por fuente que la carga usa como compuerta. No descarga y no inserta en `upme_pdet`.

### División del trabajo de Derek en dos tramos

Se partió por el estado real del repositorio el 14 nov 2026, no por mitades de la lista de tareas:

| Pieza | Estado en `main` |
| --- | --- |
| Descarga de Microsoft (Miguel) | Lista: manifiesto `complete`, 125 particiones, 4 595 615 features |
| Descarga de Google (Sebastián) | Sin código ni manifiesto |
| Carga en `buildings` (José, `04_load_buildings.py`) | Sin código |
| Capa PDET (Entrega 2) | Lista y verificada; el GeoJSONL está fuera de git |

| Tramo | Contenido | Estado |
| --- | --- | --- |
| **1** (este documento) | Contrato común de la Entrega 3 (manifiesto de descarga, registro preparado, reporte, motivos de rechazo), criterio espacial PDET, motor de preparación por bloques y la fuente Microsoft completa | Código, pruebas y corrida real de calidad listos. Falta la corrida con la capa PDET (ver Pendiente) |
| **2** | Adaptador de Google Open Buildings v3 sobre el mismo contrato (WKT, `area_in_meters` como `area_src_m2`, `confidence`, `full_plus_code` como `source_ref`), su reporte y la comparación de las dos fuentes que necesitan el EDA y la Entrega 4 | Empieza cuando exista el manifiesto de Sebastián |

Límite entre tramos: el tramo 2 solo agrega una entrada en `SOURCES` de `03_prepare_buildings.py` (lector + atributos) y su bloque en `config.yaml`. El contrato, el criterio espacial, los rechazos, el reporte y la compuerta de carga son los del tramo 1.

### Flujo

```mermaid
flowchart LR
    D["Descarga<br/>03_download_ms_buildings.py<br/>(Miguel)"] -->|"manifiesto + SHA256"| P
    M["Capa PDET<br/>municipalities.geojsonl<br/>(Entrega 2)"] -->|"ready_for_load + SHA256"| P
    P["Preparación<br/>03_prepare_buildings.py<br/>(Derek)"] -->|"part-*.jsonl.gz<br/>+ reporte"| L["Carga<br/>04_load_buildings.py<br/>(José)"]
    P --> R["rechazos y reparaciones<br/>por partición"]
    L --> B[("buildings<br/>ingestion_runs")]
```

### Comandos

```bash
python scripts/03_prepare_buildings.py --source ms                           # corrida que habilita la carga
python scripts/03_prepare_buildings.py --source ms --without-pdet-selection  # calidad de la fuente sin capa PDET
python scripts/03_prepare_buildings.py --source ms --partitions 032212332    # muestra; nunca queda lista para cargar
python -m unittest discover -s tests -p "test_prepare_buildings.py" -v
MONGO_URI=mongodb://admin:admin123@localhost:27017/ \
  python -m unittest discover -s tests -p "test_prepare_buildings_mongo.py" -v
```

Opciones: `--workers N` (procesos, por defecto hasta 4) y `--check-records` (valida cada registro contra el contrato antes de escribirlo). Rutas y parámetros en `config.yaml`, bloque `processing.buildings` y `sources.microsoft.prepare_*`.

### Contratos

#### 1. Manifiesto de descarga (descarga → preparación)

`download_manifest_problems(manifest, dataset_id)` define lo que cualquier módulo de descarga debe entregar. El manifiesto actual de Microsoft lo cumple sin cambios (prueba `test_real_microsoft_manifest_passes`). El de Google debe cumplir lo mismo:

| Campo | Regla |
| --- | --- |
| `status` | `complete` |
| `claims_pdet_coverage` | `true` |
| `datasets_document` | `_id` (= `ms` o `google`), `name`, `version`, `license`, `url`, `accessed_at`: lo que exige el validador de `datasets` |
| `source.dataset_id` | Igual a la fuente, si viene |
| `partitions[]` | Cada una con `status = ok`, identificador único (`partition_id`; Microsoft usa `quadkey`), `local_path` y `download.sha256` |

Antes de leer una partición se recalcula su SHA256; si no coincide con el manifiesto, la corrida se detiene.

#### 2. Registro preparado (preparación → carga)

Un documento de `buildings` por línea, en GeoJSON Lines con gzip. Son los campos de la Entrega 1 menos `run_id`, que pone la carga (igual que `loaded_at` en la Entrega 2). `prepared_record_errors` revisa cada regla.

| Campo | Microsoft | Regla |
| --- | --- | --- |
| `dataset_id` | `ms` | Referencia a `datasets` |
| `source_ref` | `<quadkey>/<archivo>:<línea>` | Microsoft no trae identificador; archivo + fila, como prevé el diccionario |
| `footprint` | GeoJSON `Polygon` | WGS84, orden lon/lat. Coordenadas originales si GEOS lo da por válido; si se repara, el polígono reparado con 7 decimales |
| `centroid` | GeoJSON `Point` | Centroide de shapely, 7 decimales (~1 cm) |
| `area_m2` | Área geodésica | `pyproj.Geod(ellps="WGS84")`, valor absoluto, 2 decimales |
| `area_src_m2` | `null` | Área original de la fuente; Microsoft no la publica. Google la llenará con `area_in_meters` |
| `confidence` | `null` salvo 176 | `-1` → `null`; fuera de [0, 1] → `null` con aviso |
| `height_m` | `null` | `-1` → `null` (regla de la Entrega 1) |
| `mpio_code` | DIVIPOLA o `null` | Municipio PDET que contiene el centroide |

#### 3. Reporte de preparación (compuerta de la carga)

`outputs/buildings_<fuente>_prepare_report.json`. La carga solo debe leer archivos si `status = ready_for_load`, `claims_pdet_selection = true` y el SHA256 de cada `partitions[].output.path` coincide. El reporte trae:

- `input`: manifiesto de descarga y su SHA256, capa PDET y su SHA256.
- `datasets_document`: copiado del manifiesto, para insertarlo en `datasets`.
- `totals`: leídas, rechazadas por motivo, reparadas por acción, excluidas fuera de PDET, preparadas, duplicados, avisos de atributos, distribución de `area_m2` y `balanced`.
- `partitions[]`: por partición, entrada (ruta, SHA256), salida (ruta, SHA256, bytes, registros), rutas de los registros de rechazos y reparaciones, y los mismos contadores. Con eso la carga arma un `ingestion_runs` por partición: `source_file = input.local_path`, `rows_read = read`, `rows_rejected = rejected`, `rows_loaded` = insertados reales.
- `loader_contract`: estas mismas reglas en texto.

Estados posibles: `ready_for_load`, `source_pass_only` (sin capa PDET), `sample_only` (con `--partitions`) y `failed` (el balance no cierra). Solo el primero habilita la carga. Si una corrida nueva no termina lista, el reporte exitoso anterior queda copiado en `outputs/history/` (misma regla de la Entrega 2).

### Método

Cada partición se procesa en un proceso aparte y se lee línea por línea en bloques de `processing.batch_size` (10 000) features. Por cada edificación:

1. **Lectura.** `json.loads` de la línea; si falla → `json_invalid`.
2. **Forma.** Debe ser `Feature` con `geometry` (`feature_invalid`), de tipo `Polygon` (`geometry_type_unsupported`), construible (`geometry_unparseable`, por ejemplo un anillo de 2 puntos) y no vacía (`geometry_empty`).
3. **Ejes y CRS.** Todos los vértices dentro de la ventana de Colombia de la Entrega 2 (lon −82 a −66, lat −5 a 16). Un archivo con lat/lon invertidos cae aquí (`outside_colombia_window`). Microsoft ya viene en EPSG:4326 lon/lat (RFC 7946), así que no se reproyecta.
4. **Validez y reparación.** `shapely.is_valid` sobre el bloque. Si GEOS la marca inválida se aplica `make_valid` y se conservan las partes con área:
   - una parte → `make_valid` (reparada);
   - varias, y las menores suman menos del 1 % (`sliver_ratio`) → se conserva la mayor (`make_valid_dropped_slivers`);
   - varias de tamaño comparable (típico de un "moño" que se cruza) → rechazo `repair_split_multipolygon`, porque el esquema pide un solo `Polygon` y quedarse con una mitad cambiaría la edificación;
   - nada con área → `repair_degenerate`.
5. **Centroide y criterio espacial** (abajo).
6. **Área geodésica** en m² sobre el elipsoide WGS84; si no es positiva → `area_nonpositive`.
7. **Atributos.** `height` y `confidence` según la tabla del registro.
8. **Duplicados.** Al final se compara un hash de 64 bits del WKB normalizado de cada huella preparada. Si una huella idéntica sale en dos particiones, se queda la de la partición de identificador menor y la otra se rechaza como `duplicate_geometry`.

Se cumple, por partición y en total: `read = rejected + excluded_outside_pdet + prepared`. Las reparadas están dentro de `prepared`.

#### Criterio espacial del territorio de interés

> Una edificación pertenece al territorio PDET si su **centroide** cae dentro o sobre el borde de uno de los 170 municipios PDET de la Entrega 2. Si cae sobre un borde compartido por dos municipios, se asigna al de **código DIVIPOLA menor**. Lo que cae fuera no se escribe; se cuenta como `excluded_outside_pdet`, no como rechazo.

Por qué así:

- Es la misma regla que fija la Entrega 1 para el conteo (asignación por centroide con `$geoWithin` sobre `buildings.centroid`). Cada edificación cuenta una sola vez, aunque su polígono cruce un límite.
- La Entrega 1 dejaba el desempate en "el primer municipio procesado". Aquí se fija el código menor para que el resultado no dependa del orden de ejecución.
- Filtrar antes de la carga cumple el plan de la Entrega 1 ("leer por bloques y descartar lo que cae fuera"): no se insertan millones de documentos que la Entrega 4 no usa.
- Implementación: `shapely.STRtree` sobre los 170 polígonos y `query(..., predicate="intersects")` sobre todos los centroides del bloque a la vez.

Diferencia con la Entrega 1, a la vista: el plan decía que `mpio_code` se llenaba en la fase 3. Ahora la preparación ya lo llena, porque la prueba de punto en polígono es necesaria para filtrar. La fase 3 puede usar `$geoWithin` como verificación independiente. Shapely trata los lados de un polígono como rectas en lon/lat y MongoDB como geodésicas, así que un centroide a centímetros de un límite puede caer distinto. La prueba de MongoDB confirma que cada edificación asignada a un municipio la devuelve `$geoWithin` sobre ese municipio. La única extra posible es el centroide exacto sobre el borde compartido.

#### Archivos grandes y memoria

| Técnica | Efecto |
| --- | --- |
| Solo las particiones del manifiesto (las que tocan PDET) | 125 de 232 particiones de Colombia |
| Lectura en flujo desde gzip, bloques de 10 000 líneas | Ninguna partición se carga entera en memoria |
| Operaciones vectorizadas de shapely por bloque (`is_valid`, `centroid`, `STRtree.query`) | Unos 10 000 features/s por proceso |
| Un proceso por partición (`--workers`) | 4,6 millones de features en ~100 s con 4 procesos |
| Escritura incremental a `.partial` y renombre al terminar | Una corrida interrumpida no deja archivos a medias como buenos |
| Por edificación preparada, el proceso principal guarda solo hash, código y área (20 bytes) | ~92 MB para 4,6 millones; con eso se quitan duplicados y se arma el CSV por municipio sin releer la salida |

### Resultados con datos reales de Microsoft

Corrida del 14 nov 2026 con `--without-pdet-selection` sobre las 125 particiones del manifiesto de Miguel (versión `2026-02-03`), descargadas de nuevo en este entorno. Las 125 coincidieron byte a byte con el SHA256 del manifiesto. Reporte completo: `outputs/buildings_ms_source_pass_report.json`.

| Conteo | Valor |
| --- | --- |
| Leídas | **4 595 615** (igual al total de features del manifiesto de descarga) |
| Rechazadas | **48**, todas `repair_split_multipolygon` |
| Reparadas (incluidas en preparadas) | **29**: 18 `make_valid`, 11 `make_valid_dropped_slivers` |
| Preparadas sin filtro PDET | **4 595 567** |
| Duplicados entre particiones | 0 |
| Balance `read = rejected + excluded + prepared` | Cumple en las 125 particiones |
| `confidence` con valor | 176 (el resto `null`) |
| `height_m` con valor | 0 (todas `null`) |
| Tiempo | 95 a 101 s con 4 procesos; 486 MiB como máximo por proceso |

Las 77 geometrías inválidas que reportó la descarga son exactamente las 29 reparadas más las 48 rechazadas. Cada una está, con su `source_ref` y el motivo de GEOS, en `evidencia/ms_reparaciones_y_rechazos.csv`.

Área geodésica de las preparadas (m²):

| mín | p01 | p10 | mediana | p90 | p99 | máx | suma |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 9,66 | 17,75 | 29,84 | 82,69 | 261,09 | 1 413,64 | 76 453,09 | 699 938 128,81 |

Estas cifras incluyen edificaciones **fuera** de los municipios PDET (las particiones son cuadros de ~0,7° que se salen del territorio). No son el conteo PDET ni el área de techos de ningún municipio. El umbral `min_area_m2` (20 m²) no se aplica aquí: es un filtro de análisis de la Entrega 4, no un criterio de calidad.

#### Qué está descargado, procesado, rechazado y cargado

| Etapa | Registros de Microsoft | Fuente |
| --- | --- | --- |
| Descargados | 4 595 615 en 125 particiones | `outputs/ms_buildings_download_manifest.json` (Miguel) |
| Procesados (calidad) | 4 595 615 | `outputs/buildings_ms_source_pass_report.json` |
| Rechazados por calidad | 48 | Mismo reporte |
| Preparados sin filtro PDET | 4 595 567 | Mismo reporte; **no se cargan** |
| Excluidos fuera de PDET | Pendiente | Requiere la corrida con la capa PDET |
| Preparados para cargar (PDET) | Pendiente | `outputs/buildings_ms_prepare_report.json`, aún no generado |
| Cargados en `upme_pdet.buildings` | **0** | La carga es de José y aún no existe |

Las inserciones de la prueba de MongoDB (abajo) se hicieron en una base temporal que la prueba borra al terminar. No son una carga.

#### Cobertura geográfica real

- Fuente: solo Microsoft. Google todavía no está descargado.
- Particiones: 125 de las 232 de Colombia, las que tocan algún municipio PDET con un margen de 0,01°. No es todo el país.
- Según la cobertura de Miguel (`entrega3_descarga_microsoft.md`), 167 municipios PDET quedan cubiertos al 100 % por particiones publicadas. El Retorno (66,4 %), San José del Guaviare (69,7 %) y Miraflores (89,0 %) quedan en parte fuera, porque Microsoft no publica tres cuadros de Guaviare. Esa parte de su territorio no tiene datos de Microsoft.
- Extensión de los datos leídos: lon −79,00 a −69,92, lat −1,39 a 11,41.

### Pruebas y verificación

| Prueba | Resultado | Evidencia |
| --- | --- | --- |
| `tests/test_prepare_buildings.py`: 15 pruebas sintéticas: manifiesto real y manifiestos rotos, criterio espacial (dentro, fuera, borde, borde compartido), área geodésica contra proyección de área igual EPSG:6933 (diferencia < 0,1 %), reglas de reparación, atributos, contrato del registro, corrida completa con 13 features que cubren cada motivo, sin capa PDET, muestra, archivo alterado y repetición determinista | 15/15 OK | `evidencia/prepare_tests.txt` (suite completa del repositorio: 55 pruebas OK) |
| `tests/test_prepare_buildings_mongo.py` en MongoDB 7.0.48: validador `buildings` de `00_init_db.py` en `strict`; sin `run_id` → rechazo; con `run_id` → insertado; `$geoWithin` sobre `centroid` devuelve cada edificación asignada; plan `FETCH → IXSCAN` | OK | `evidencia/prepare_mongo_contract.txt` |
| Las 125 salidas reales (4 595 567 registros) por el mismo validador `strict`, `bulk_write` no ordenado en lotes de 10 000 | 4 595 567 insertados, 0 rechazos, 142 s | Mismo archivo |
| Repetición de la corrida real | Mismo SHA256 en las 125 salidas | `evidencia/prepare_repeticion_memoria.txt` |

#### Repetición y memoria

Dos corridas reales seguidas dieron el **mismo SHA256 en las 125 salidas** y los mismos totales. Los gzip se escriben con cabecera fija (`mtime = 0`, sin nombre de archivo) porque la cabecera normal guarda la hora y cambiaba el hash sin cambiar los datos. La prueba sintética revisa esa cabecera. El proceso más grande llegó a **486 MiB** de memoria residente y la corrida tardó 95 s con 4 procesos (`evidencia/prepare_repeticion_memoria.txt`).

### Pendiente del tramo 1

La corrida que habilita la carga necesita `data/processed/municipalities.geojsonl`, que está fuera de git. En este entorno no se pudo regenerar: `portalgis.dane.gov.co` corta la conexión TLS (el mismo síntoma que registra `outputs/mgn_catalog_probe.json`). No se usó ninguna capa sustituta.

Quien tenga la capa de la Entrega 2 (Miguel la usó el 13 nov, SHA256 `612e2544…01f8ed`) corre:

```bash
python scripts/03_download_ms_buildings.py --offline   # confirma las 125 particiones
python scripts/03_prepare_buildings.py --source ms     # ~2 min con 4 procesos
```

Debe terminar con `Balance OK. Estado: ready_for_load` y dejar `outputs/buildings_ms_prepare_report.json` y `outputs/buildings_ms_prepared_by_municipality.csv` (edificaciones y área preparadas por municipio). Esos dos archivos se versionan. Los conteos de rechazo y reparación deben ser los de la tabla de arriba, porque se calculan antes del filtro espacial.

### Interfaces para el resto del equipo

| Quién | Usa | Qué debe hacer |
| --- | --- | --- |
| José (carga) | `outputs/buildings_ms_prepare_report.json` | Verificar la compuerta; insertar `datasets_document` en `datasets`; por partición crear un `ingestion_runs`, leer `output.path`, agregar `run_id` e `insert_many(ordered=False)` en lotes de 10 000; crear después los índices con `00_init_db.py --building-indexes` |
| Sebastián (descarga de Google) | `download_manifest_problems(manifest, "google")` | Escribir un manifiesto que la cumpla, con `partition_id` por celda S2 y `sources.google.manifest` en `config.yaml` |
| Verificación espacial | Reporte + CSV por municipio | Comparar los conteos por municipio con `$geoWithin` en MongoDB después de la carga |
| EDA | Reporte (`area_m2`, avisos de atributos) + `prepared_by_municipality.csv` | Partir de estas distribuciones para fijar `min_area_m2` |

### Limitaciones

- El centroide de un polígono cóncavo puede caer fuera de la huella. Para asignar municipio el efecto es mínimo con edificaciones de decenas de m², pero existe.
- El hash de duplicados es de 64 bits: la probabilidad de colisión con 4,6 millones de huellas es del orden de 10⁻⁶.
- `repair_split_multipolygon` rechaza 48 edificaciones reales en vez de partirlas, porque el esquema pide un solo `Polygon` por documento. Son el 0,001 % de lo leído.



# 8. Carga de huellas en MongoDB e índices espaciales

Este documento cubre la carga en `upme_pdet.buildings` de las huellas que la
preparación de Derek declaró listas, para las dos fuentes del contrato de la
Entrega 3: Microsoft Global ML Building Footprints y Google Open Buildings v3.
No repite la descarga, la preparación ni el filtro PDET: su entrada es el
reporte de preparación y los GeoJSON Lines con gzip que ese reporte declara.

Script: `scripts/04_load_buildings.py`.

### Compuerta de entrada

La carga no toca la base si el reporte de preparación no cumple el contrato
`entrega3-buildings-v1`:

- `status = ready_for_load`, `claims_pdet_selection = true`,
  `claims_full_source = true` y `totals.balanced = true`;
- `dataset_id` igual a la fuente que se va a cargar;
- por partición, el archivo existe, su SHA256 y sus bytes coinciden con
  `partitions[].output`, y su `source_file` es el `input.local_path` del
  manifiesto de descarga.

Un reporte en `sample_only` o `source_pass_only` nunca habilita la carga.

### Diseño de la carga

1. **`_id` determinista.** Cada edificación recibe
   `<dataset_id>:<blake2b-96(dataset_id + "\x00" + source_ref)>`. El
   `source_ref` ya es único y estable en la preparación
   (`partición/archivo:línea`), así que repetir la carga apunta a los mismos
   documentos y no puede crear duplicados. No se necesita un índice único
   secundario.
2. **`run_id` de la primera inserción.** El documento de `buildings` recibe el
   `ObjectId` de la corrida de su partición en `ingestion_runs`. En una
   repetición se actualizan los atributos con `$set` y el `run_id` se conserva
   con `$setOnInsert`, de modo que la segunda pasada deja 0 inserciones y 0
   modificaciones.
3. **Lotes y memoria.** Se lee un GeoJSONL con gzip en flujo y se escribe con
   `bulk_write` de `processing.batch_size` (10 000 por defecto). Nunca se
   cargan en memoria una partición completa ni la fuente completa.
4. **Rechazos controlados.** Antes de insertar se repite la validación de
   `entrega3_contracts.prepared_record_errors` (la misma del validador
   `$jsonSchema`). Un registro inválido, un JSON roto o un error de escritura
   de MongoDB se cuentan por motivo, se guardan en
   `data/processed/buildings/<fuente>/load_rejects.jsonl` (ignorado por git) y
   quedan en el reporte. El archivo preparado no se modifica.
5. **Registro.** La fuente se escribe en `datasets` con los seis campos del
   validador (`_id`, `name`, `version`, `license`, `url`, `accessed_at`) y cada
   partición deja su documento en `ingestion_runs` con `source_file`,
   `rows_read`, `rows_loaded`, `rows_rejected`, `started_at` y `finished_at`,
   más `partition_id`, SHA256 del preparado y notas.
6. **Índices.** Al terminar se crean los de `00_init_db.py` para `buildings`:
   `centroid_2dsphere` sobre `centroid` y
   `dataset_id_1_mpio_code_1`. El 2dsphere se construye después de la primera
   pasada para no frenar las inserciones iniciales.
7. **Verificación.** El reporte incluye conteo total, municipios con
   edificaciones, duplicados de `source_ref` (agregación con `allowDiskUse`),
   registro en `datasets`, existencia del índice y una consulta `$geoWithin`
   real sobre un municipio cargado con su plan ganador (`IXSCAN` sobre
   `centroid_2dsphere`). Con `--passes 2` además comprueba que la segunda
   pasada inserta 0 y deja el mismo conteo.

### Microsoft

Corrida completa sobre las 125 particiones de la descarga de Miguel y la capa
de 170 municipios de la Entrega 2 (SHA256
`612e2544be7ca2c22285aaac647819b910aa779ce61e1e5b872766051101f8ed`).

| | |
| --- | --- |
| Leídas en la preparación | 4 595 615 |
| Excluidas por caer fuera de los PDET | 2 834 537 |
| Preparadas | 1 761 030 |
| Cargadas en `buildings` | 1 761 030 |
| Rechazadas en la carga | 0 |
| Municipios PDET con edificaciones | 170 |
| Duplicados de `source_ref` | 0 |
| Primera pasada | 1 761 030 insertadas |
| Segunda pasada | 0 insertadas, 0 actualizadas, 1 761 030 sin cambios |
| Duración de la carga (dos pasadas) | 101,95 s |
| Memoria máxima del proceso | 335 167 488 bytes (~320 MiB) |
| Índices | `centroid_2dsphere`, `dataset_id_1_mpio_code_1` |
| `$geoWithin` de prueba | `IXSCAN` sobre `centroid_2dsphere` |

Reportes: `outputs/buildings_ms_prepare_report.json`,
`outputs/buildings_ms_load_report.json` y
`outputs/buildings_ms_prepared_by_municipality.csv`.

### Google

Corrida completa sobre las 8 particiones S2 de la descarga de Sebastián
(3.110.075.800 bytes comprimidos, 31.499.115 filas originales) y la misma capa
de 170 municipios PDET.

| | |
| --- | --- |
| Leídas en la preparación | 31 499 115 |
| Excluidas por caer fuera de los PDET | 28 804 201 |
| Rechazadas en la preparación | 139 (`geometry_type_unsupported`, todas MultiPolygon) |
| Preparadas | 2 694 775 |
| Cargadas en `buildings` | 2 694 775 |
| Rechazadas en la carga | 0 |
| Municipios PDET con edificaciones | 165 (de 170; 5 sin huellas en la fuente) |
| Duplicados de `source_ref` | 0 |
| Primera pasada | 2 694 775 insertadas |
| Segunda pasada | 0 insertadas, 0 actualizadas, 2 694 775 sin cambios |
| Duración de la carga (dos pasadas) | 153,29 s |
| Memoria máxima del proceso | 268 681 216 bytes (~256 MiB) |
| Índices | `centroid_2dsphere`, `dataset_id_1_mpio_code_1` |
| `$geoWithin` de prueba | 2 983 asignadas / 2 983 dentro, `IXSCAN` sobre `centroid_2dsphere` |

Reportes: `outputs/buildings_google_prepare_report.json`,
`outputs/buildings_google_load_report.json` y
`outputs/buildings_google_prepared_by_municipality.csv`.
La memoria se midió con `/usr/bin/time -l` en
`docs/delivery3/evidencia/load_google_memory.txt`.

### Estado de la base

Tras las dos cargas, `upme_pdet.buildings` tiene 4 455 805 documentos: 1 761 030
de `ms` y 2 694 775 de `google`. Las 125 particiones de Microsoft y las 8 de
Google dejaron una corrida por pasada en `ingestion_runs` (250 y 16 documentos,
respectivamente) y las dos fuentes están en `datasets`. El área geodésica
cargada suma 220 976 634 m² para Microsoft y 222 051 169 m² para Google.
Microsoft cubre los 170 municipios PDET; Google, 165.

### Repetición e idempotencia

Cada corrida completa se ejecuta con `--passes 2`. La primera pasada inserta;
la segunda vuelve a leer los mismos archivos, no inserta nada y el conteo de la
colección no cambia. La comprobación queda en
`verification.checks.rerun_does_not_duplicate` y en `idempotent = true` del
reporte de la fuente. Además, `--verify-only` recalcula las verificaciones
sobre la base ya cargada sin insertar, para no confundir una reverificación con
una carga nueva.

### Reproducción

```bash
# 1. Esquema y colecciones
docker compose up -d
python scripts/00_init_db.py

# 2. Capa PDET de la Entrega 2 (si no está en data/processed/)
python scripts/01_download_mgn.py
python scripts/01_validate_mgn.py
python scripts/02_prepare_municipalities.py
python scripts/02_load_municipalities.py

# 3. Descargas y preparación
python scripts/03_download_ms_buildings.py
python scripts/03_prepare_buildings.py --source ms --workers 4
python scripts/03_download_google_buildings.py
python scripts/03_prepare_buildings.py --source google --workers 4

# 4. Carga de las dos fuentes, dos pasadas cada una
python scripts/04_load_buildings.py --source ms --passes 2
python scripts/04_load_buildings.py --source google --passes 2

# 5. Pruebas
python -m unittest discover -s tests -p "test_load_buildings*.py" -v
MONGO_URI=mongodb://admin:admin123@localhost:27017/ \
  python -m unittest discover -s tests -p "test_load_buildings_mongo.py" -v
```

Los archivos crudos y preparados viven en `data/` y no se versionan; el
manifiesto, los reportes y los CSV por municipio sí. `MONGO_URI` reemplaza la
URI de `config.yaml`.

### Cargador de Samuel: incompatibilidades

El cargador de la rama `feature/entrega3-eda`
(`03_load_buildings.py`)
no se reutilizó porque su entrada y sus campos no son los del contrato de la
preparación. Estas son las diferencias que se corrigieron en
`04_load_buildings.py`:

| Cargador de Samuel | Contrato de Derek / esquema de la Entrega 1 |
| --- | --- |
| Lee `data/processed/ms_buildings.geojsonl` | Lee las particiones con gzip que declara el reporte de preparación |
| Usa `geometry` y `geometry_centroid` | Usa `footprint` y `centroid` |
| `area_m2` con `shapely.area` en grados² | `area_m2` geodésica en m² calculada en la preparación |
| No escribe `dataset_id` ni `run_id` | El validador exige `dataset_id`, `footprint`, `centroid`, `area_m2` y `run_id` |
| `_id` con el hash de la geometría | `_id` determinista por `dataset_id` + `source_ref` |
| `bulk_write` de un solo lote con 4.5 M de `ReplaceOne` | Lotes acotados y `UpdateOne` con `$setOnInsert` |
| No registra `datasets` ni `ingestion_runs` | Registra la fuente y una corrida por partición |
| No crea índices | Crea `centroid_2dsphere` y `dataset_id_1_mpio_code_1` |
| `config["mongodb"]` (clave inexistente) | `config["mongo"]` / `MONGO_URI` |

### Evidencia

| Archivo | Contenido |
| --- | --- |
| `docs/delivery3/evidencia/prepare_ms_run.log` | Salida de la preparación de Microsoft |
| `docs/delivery3/evidencia/prepare_google_run.log` | Salida de la preparación de Google |
| `docs/delivery3/evidencia/download_google_run.log` | Salida de la descarga de Google |
| `docs/delivery3/evidencia/load_ms_run1.log` | Carga de Microsoft con dos pasadas |
| `docs/delivery3/evidencia/load_google_run1.log` | Carga de Google con dos pasadas |
| `docs/delivery3/evidencia/load_ms_memory.txt` | Tiempo y memoria máxima de la carga de Microsoft |
| `docs/delivery3/evidencia/load_google_memory.txt` | Tiempo y memoria máxima de la carga de Google |
| `docs/delivery3/evidencia/load_tests.txt` | Pruebas sintéticas y de MongoDB |


