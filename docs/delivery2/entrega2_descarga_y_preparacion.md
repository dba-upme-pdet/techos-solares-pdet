# Entrega 2: descarga del MGN y preparación de municipios

Alcance de este cambio: `scripts/01_download_mgn.py`, tramo asignado a Derek, y `scripts/02_prepare_municipalities.py`, tramo asignado a José. Preparar ese segundo script no afirma que José lo haya escrito. No incluye `01_validate_mgn.py`, `02_load_municipalities.py` ni `02_verify_spatial.py`.

La rúbrica de la semana 2 (`aocalderon/PUJ`, `2026-30/DBA/Project/resources/rubrics/DBA_FinalProject_Rubrics_Week2.pdf`) pide adquisición y verificación (25), integridad y formato (20), integración espacial NoSQL (25), documentación (15), claridad del informe (5) y defensa (10). Aquí quedan cubiertos el mecanismo de descarga, el formato de los documentos y la documentación de estos dos tramos. La carga, el índice `2dsphere` y el `explain()` siguen siendo de Miguel y Sebastián.

## Comandos

```bash
python scripts/01_download_mgn.py --self-check
python scripts/02_prepare_municipalities.py --self-check
python scripts/01_download_mgn.py
python scripts/02_prepare_municipalities.py
```

`--self-check` usa figuras sintéticas marcadas como fixture. No cuenta como descarga del DANE ni como los 170 municipios.

Los scripts leen `config.yaml`. El directorio de trabajo es la raíz del repositorio. Salen con código distinto de cero cuando la verificación falla.

## Contrato para el resto del equipo

| Pieza | Quién la escribe | Quién la lee | Condición |
| --- | --- | --- | --- |
| `outputs/mgn_download_manifest.json` | Derek | Samuel y José | Resultado de la última corrida. `claims_national_download = true` solo con `status = complete`, `fixture = false`, el plan WFS de `config.yaml` y 1122 registros |
| `outputs/mgn_download_manifest.history.json` | el script, solo si una corrida posterior falla | todos | Copia intacta del último manifiesto exitoso. No es el resultado actual |
| Capa en `extracted_layer` | Derek | Samuel y José | GeoPackage con `MPIO_CDPMP`, `MPIO_CNMBR`, `MPIO_NAREA`, `DPTO_CCDGO`. El CRS de trabajo es el `srsName` del WFS interpretado como longitud/latitud. Tiene que existir y, si el manifiesto trae `sha256`, coincidir con él |
| `outputs/mgn_wfs_source_receipt.json` | recibo de las respuestas | el script de descarga | SHA256 y bytes de cada GML. Coincidir con esos hash prueba la caché, no el origen ni la cobertura |
| `outputs/mgn_download_attempt.json` | el script, solo si falla | todos | Detalle del intento fallido. El manifiesto actual queda en `blocked` o `invalid`, con `claims_national_download = false` |
| `data/processed/municipalities.geojsonl` | José | Miguel | Una línea JSON por municipio, solo si el reporte actual está en `ready_for_load` |
| `outputs/municipalities_prepare_report.json` | José | Miguel | `claims_full_pdet_set` solo es verdadero con 170 documentos reales de la capa nacional |
| `outputs/municipalities_prepare_report.history.json` | el script, solo si una corrida posterior falla | todos | Copia intacta del último reporte `ready_for_load`. No autoriza la carga |

Samuel cruza la capa extraída con `resources/MunicipiosPDET.xlsx`, hoja `Hoja1`, con la misma regla de este repositorio: `zfill` a 5 dígitos sobre `Código DANE Municipio`. El cruce es por código, no por nombre.

Miguel lee el JSONL, convierte cada objeto y agrega `loaded_at` como fecha BSON. El validador de `scripts/00_init_db.py` exige ese campo; por eso la preparación no lo escribe. La carga debe ser repetible por `_id` (upsert) para no duplicar. El índice `geometry_2dsphere` ya lo crea la Entrega 1.

Sebastián consulta la colección ya cargada y muestra `explain()` sobre `geometry_2dsphere`.

Los ZIP, shapefiles y el JSONL quedan fuera de git (`.gitignore`).

## Qué hace la descarga

1. La fuente usada es el WFS 2.0 de `sources.mgn.wfs`: `Serv_CapasMGN_2025:Municipio`, `srsName=urn:ogc:def:crs:EPSG::4686`, `count=200` y `startIndex` 0, 200, 400, 600, 800 y 1000. No se envía `sortBy`. La ficha `datos.gov.co` `8xdp-fsgm` es la que publica ese acceso OGC.
2. La página renderizada del geoportal y `FeatureServer/317/query` no se solicitan. El cortafuegos del DANE las bloquea.
3. El recibo solo cuenta como plan oficial si su servicio, `typeName`, `srsName`, `startIndex` y `number_matched` son los de `config.yaml` (`expected_feature_count: 1122` y los seis `startIndex`). Un recibo de un municipio, aunque sus bytes coincidan, deja `cache_matches_receipt = true`, `official_page_plan = false` y `claims_national_download = false`.
4. Si `data/raw/mgn2025/wfs/page_XXXX.gml` ya coincide en bytes y SHA256 con ese recibo oficial, el script no contacta `portalgis`. Si faltan, hace un intento por página con TLS verificado y se detiene al primer fallo de red. Una respuesta que no coincida con el recibo se rechaza.
5. Si la corrida no verifica la capa nacional, el manifiesto actual pasa a `blocked` o `invalid` con `claims_national_download = false`. Si el archivo anterior era un éxito, se copia sin cambios a `outputs/mgn_download_manifest.history.json` y esa copia no se pisa en un fallo siguiente. El código de salida distinto de cero y el manifiesto actual dicen lo mismo.
6. Los elementos GML traen los alias en español. El mapa explícito es `Código_DANE_concatenado_departamento_y_municipio` a `MPIO_CDPMP`, `Nombre_municipio` a `MPIO_CNMBR` (el REST lo llama `MPIO_CNMBRE`), `Código_DANE_departamento` a `DPTO_CCDGO`, `Nombre_departamento` a `DPTO_CNMBRE` y `Área_departamento_en_kilómetros_cuadrados` a `MPIO_NAREA`. `Año_versión_DANE` se conserva y no se filtra.
7. Cada `posList` viene en latitud/longitud. La capa de trabajo guarda longitud/latitud y la etiqueta EPSG:4686 porque ese es el `srsName` declarado. El almacenamiento REST del mismo servicio informa EPSG:3857. `original_archive_crs_proven` queda en falso: no se leyó el ZIP ni un `.prj`.
8. La unidad de `MPIO_NAREA` sale del nombre oficial del elemento, kilómetros cuadrados, y del diccionario de la Entrega 1, que guarda ese valor en `area_km2`. Además se compara el atributo con el área geodésica WGS84 de cada contorno. Si el cociente mediano no cae entre 0,5 y 2, no se declara la unidad.
9. Si la capa y los hash no cambiaron, la siguiente corrida revalida y no reescribe.

## Qué hace la preparación

1. Rechaza un manifiesto ausente, incompleto, marcado como fixture, con `national_complete = false` o con un número de registros distinto de `expected_feature_count`. Si la capa no existe, no se puede leer o su SHA256 no es el del manifiesto, el reporte actual queda en `blocked_no_layer`, `unreadable_layer` o `layer_hash_mismatch`, con `claims_full_pdet_set = false` y sin GeoJSONL. Un reporte anterior `ready_for_load` se copia a `outputs/municipalities_prepare_report.history.json`.
2. Normaliza DIVIPOLA con ceros a la izquierda. En `Hoja1` hay códigos de 4 dígitos, por ejemplo `5031`, que pasan a `05031`. `19050` ya tiene 5. Esta copia del Excel tiene 170 filas y el entero `5031` está en `Código DANE Municipio`. El departamento pasa a 2 dígitos y debe coincidir con el prefijo del municipio y con `DPTO_CCDGO`.
3. El nombre del municipio sale de `MPIO_CNMBR`, ya mapeado desde `Nombre_municipio`. Un nombre distinto en el Excel no impide el cruce y queda contado en `name_mismatches`.
4. El diccionario de la Entrega 1 no nombra la columna del nombre del departamento, solo `DPTO_CCDGO`. El script usa una columna del MGN únicamente cuando sus valores coinciden con `Departamento` del Excel. Si ninguna coincide, `dpto_name` sale de esa columna del Excel y el reporte lo dice. Si coinciden dos columnas, se detiene.
5. Transforma de EPSG:4686 a `processing.target_crs` (`EPSG:4326`) y orienta los anillos exteriores en sentido antihorario. Una geometría inválida pasa por `make_valid`. No se simplifica. Si el documento pasa de 15 MB, se rechaza entero.
6. Cada vértice debe caer en la ventana de comprobación de Colombia (longitud -82 a -66, latitud -5 a 16). Un eje invertido no pasa.
7. `source` queda `{dataset: "MGN", version: "2025", file: <nombre observado>}`. `version` sale de `sources.mgn.version` (`MGN2025`).
8. Sin unidad declarada para `MPIO_NAREA`, el estado es `unresolved_area_unit`, no se escribe el JSONL y el código de salida es 3.

## Evidencia de los fixtures

Corrida el 2026-11-08 con Python 3.12.3, GeoPandas 1.2.0, pyproj 3.8.0, pandas 3.1.1, shapely 2.2.0 y requests 2.34.2.

- `python scripts/01_download_mgn.py --self-check` terminó `FIXTURE self-check descarga: 14/14`, salida 0. Incluye un GML sintético de un vértice, el rechazo de un recibo de un solo municipio y un fallo TLS simulado que archiva el manifiesto exitoso. No es la capa del DANE.
- `python scripts/02_prepare_municipalities.py --self-check` terminó `FIXTURE self-check preparación: 20/20`, salida 0. Incluye la capa ausente, la capa ilegible y un manifiesto de un solo municipio.

Esas pruebas no verifican los 170 municipios. Una corrida anterior de los mismos comandos, antes de estos casos, dio 11/11 y 17/17.

## Evidencia de la capa real

Desde esta red, `portalgis.dane.gov.co` corta el TLS antes del certificado (`curl` código 35, un solo intento, sin reintento). `geoportal.dane.gov.co` hace lo mismo y su puerto 80 responde 502. Ese registro sigue en `outputs/mgn_catalog_probe.json`. No es el resultado de la preparación.

Las seis respuestas WFS se obtuvieron fuera de esta red el 2026-11-08 entre 15:24:23 y 15:25:01 (`America/Bogota`), con HTTP 200. Cada GML descomprimido coincide con `outputs/mgn_wfs_source_receipt.json`. Los tamaños son 26416139, 22174892, 25069453, 29395276, 21884852 y 27119583 bytes. Los SHA256 empiezan, en orden, por `5d600d25`, `6900fa41`, `168772c3`, `d6b3ee0b`, `2b8496ab` y `2eadfeba`.

Con esas páginas ya verificadas:

| Comando | Salida |
| --- | --- |
| `python scripts/01_download_mgn.py` | 0. 1122 registros, CRS de trabajo EPSG:4686, unidad `km2`, origen `preserved-wfs-responses` |
| `python scripts/02_prepare_municipalities.py` | 0. 170 documentos |
| segunda corrida de los dos comandos | 0 y 0. El GeoPackage se revalida y el GeoJSONL conserva el hash |
| corrida posterior, con las páginas ya presentes | 0 y 0. El manifiesto sigue en `50d6749ff28b442ef8cb243542501326eb06253ca0f67c9992e828dc64ea0f30` y el GeoJSONL en `612e2544be7ca2c22285aaac647819b910aa779ce61e1e5b872766051101f8ed` |

`data/raw/mgn2025/wfs/municipio.gpkg` pesa 100577280 bytes y su SHA256 es `fe6bdebf30d586f805c844be216f9f129b8567f5f1a2b18a3212ad12cd35e17f`. `data/processed/municipalities.geojsonl` tiene 170 líneas y SHA256 `612e2544be7ca2c22285aaac647819b910aa779ce61e1e5b872766051101f8ed`. Esos dos archivos quedan fuera de git.

Los 170 `_id` son exactamente los códigos de `Hoja1` rellenados a 5 dígitos. No faltan, no sobran y no se repiten. `5031` queda en `05031` (Amalfi, Antioquia). El primer vértice leído es longitud `-74.9136401`, latitud `7.28806897`. Todas las geometrías son `MultiPolygon`. Ningún documento trae `loaded_at`. El mayor documento ocupa 1341497 bytes, por debajo del límite de 15 MB. No se simplificó ninguna geometría y `repaired_geometries` es 0. `dpto_name` salió de `DPTO_CNMBRE`.

`Año_versión_DANE` es 2025 en 168 municipios nacionales y 2024 en 954. Entre los 170 PDET son 31 y 139. No se eliminó ninguno. `source.version` queda `2025` porque el servicio publicado es MGN2025.

La unidad quedó en `km2`. El nombre del elemento oficial dice kilómetros cuadrados, y el cociente atributo / área geodésica WGS84 sobre los 1122 contornos tiene mínimo 0.9984, mediana 0.9994 y máximo 1.0209. La palabra departamento del alias se registra y no se usa para tratar el valor como área departamental.

Hay 15 nombres distintos entre `Nombre_municipio` y el Excel. El cruce no depende de ellos. Son diferencias de tilde o de forma oficial, por ejemplo `05665` SAN PEDRO DE URABÁ / SAN PEDRO DE URABA, `19548` PIENDAMÓ - TUNÍA / PIENDAMÓ y `70823` SAN JOSÉ DE TOLUVIEJO / TOLÚ VIEJO.

## Lo que sigue sin resolverse

- El ZIP de 1,5 GB citado en `Project.tex` no se descargó. El CRS del archivo original no está probado. El `srsName` del WFS declara EPSG:4686 y el REST informa EPSG:3857.
- En una copia sin las páginas GML, un GetFeature real a `portalgis.dane.gov.co` sigue cortando el TLS antes del certificado (`SSL: UNEXPECTED_EOF_WHILE_READING`, un solo `startIndex=0`, salida 2). El manifiesto de esa copia queda `blocked`, con `claims_national_download = false`, `official_page_plan = true` y `cache_matches_receipt = false`. Su historial conserva el manifiesto exitoso byte a byte. El manifiesto que está en el repositorio no se reemplazó: las páginas locales siguen revalidando. No se desactivó la verificación TLS y no se repitió el host.
- La inserción en MongoDB, la idempotencia de la carga y el `explain()` del índice `2dsphere` siguen siendo de Miguel y Sebastián.
