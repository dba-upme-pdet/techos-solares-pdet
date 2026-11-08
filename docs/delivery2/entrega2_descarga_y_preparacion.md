# Entrega 2: descarga del MGN y preparación de municipios

Alcance de este cambio: Derek (`scripts/01_download_mgn.py`) y José (`scripts/02_prepare_municipalities.py`). No incluye `01_validate_mgn.py`, `02_load_municipalities.py` ni `02_verify_spatial.py`.

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
| `outputs/mgn_download_manifest.json` | Derek | Samuel y José | `contract = entrega2-mgn-v1`, `role = download-manifest`, `status = complete`, `fixture = false`, `claims_national_download = true` |
| Capa en `extracted_layer` | Derek | Samuel y José | Shapefile o GeoPackage con `MPIO_CDPMP`, `MPIO_CNMBR`, `MPIO_NAREA`, `DPTO_CCDGO` y CRS igual a `sources.mgn.source_crs` (`EPSG:4686`) |
| `outputs/mgn_download_attempt.json` | Derek | todos | Intento fallido. No reemplaza al manifiesto |
| `data/processed/municipalities.geojsonl` | José | Miguel | Una línea JSON por municipio, solo si el reporte está en `ready_for_load` |
| `outputs/municipalities_prepare_report.json` | José | Miguel | `claims_full_pdet_set` solo es verdadero con 170 documentos reales |

Samuel cruza la capa extraída con `resources/MunicipiosPDET.xlsx`, hoja `Hoja1`, con la misma regla de este repositorio: `zfill` a 5 dígitos sobre `Código DANE Municipio`. El cruce es por código, no por nombre.

Miguel lee el JSONL, convierte cada objeto y agrega `loaded_at` como fecha BSON. El validador de `scripts/00_init_db.py` exige ese campo; por eso la preparación no lo escribe. La carga debe ser repetible por `_id` (upsert) para no duplicar. El índice `geometry_2dsphere` ya lo crea la Entrega 1.

Sebastián consulta la colección ya cargada y muestra `explain()` sobre `geometry_2dsphere`.

Los ZIP, shapefiles y el JSONL quedan fuera de git (`.gitignore`).

## Qué hace la descarga

1. Parte de `sources.mgn.url`, la página oficial indicada también en `Project.tex` del profesor: `https://geoportal.dane.gov.co/servicios/descarga-y-metadatos/datos-geoestadisticos/?cod=111`.
2. Busca en ese HTML un enlace `.zip` identificado como MGN2025. Si hay varios, se queda con el que dice "todos los niveles geográficos", que es el producto citado en el enunciado (ZIP de 1,5 GB). Si no hay un candidato único, se detiene.
3. No hay una URL de archivo escrita en `config.yaml`. El script no completa una de memoria. `sources.mgn.file_url` solo se usaría si más adelante se guarda ahí una URL vista en la página.
4. La descarga usa TLS con verificación activa.
5. Extrae la capa cuyos atributos incluyen los cuatro campos del diccionario de la Entrega 1. Comprueba que se lee y que su CRS equivale a EPSG:4686.
6. Si un XML, TXT o HTML junto a la capa dice la unidad de `MPIO_NAREA`, la copia al manifiesto. Si no la dice, `area_unit` queda nulo. No se adivina por el nombre del campo ni por el tamaño del número.
7. Si el archivo y el hash no cambiaron, la siguiente corrida no vuelve a descargar: revalida.

## Qué hace la preparación

1. Rechaza un manifiesto ausente, incompleto o marcado como fixture.
2. Normaliza DIVIPOLA con ceros a la izquierda. En `Hoja1` hay códigos de 4 dígitos, por ejemplo `5031`, que pasan a `05031`. `19050` ya tiene 5. Esta copia del Excel tiene 170 filas y el entero `5031` está en `Código DANE Municipio`. El departamento pasa a 2 dígitos y debe coincidir con el prefijo del municipio y con `DPTO_CCDGO`.
3. El nombre del municipio sale de `MPIO_CNMBR`. Un nombre distinto en el Excel no impide el cruce y queda contado en `name_mismatches`.
4. El diccionario de la Entrega 1 no nombra la columna del nombre del departamento, solo `DPTO_CCDGO`. El script usa una columna del MGN únicamente cuando sus valores coinciden con `Departamento` del Excel. Si ninguna coincide, `dpto_name` sale de esa columna del Excel y el reporte lo dice. Si coinciden dos columnas, se detiene.
5. Transforma de EPSG:4686 a `processing.target_crs` (`EPSG:4326`) y orienta los anillos exteriores en sentido antihorario. Una geometría inválida pasa por `make_valid`. No se simplifica. Si el documento pasa de 15 MB, se rechaza entero.
6. Cada vértice debe caer en la ventana de comprobación de Colombia (longitud -82 a -66, latitud -5 a 16). Un eje invertido no pasa.
7. `source` queda `{dataset: "MGN", version: "2025", file: <nombre observado>}`. `version` sale de `sources.mgn.version` (`MGN2025`).
8. Sin unidad declarada para `MPIO_NAREA`, el estado es `unresolved_area_unit`, no se escribe el JSONL y el código de salida es 3.

## Evidencia de los fixtures

Corrida el 2026-11-08 con Python 3.12.3, GeoPandas 1.2.0, pyproj 3.8.0, pandas 3.1.1, shapely 2.2.0 y requests 2.34.2. Esas versiones salen de los mínimos de `requirements.txt` para estos dos scripts. El entorno virtual no se versiona.

- `python scripts/01_download_mgn.py --self-check` terminó `FIXTURE self-check descarga: 10/10`, salida 0. Cubre página sin ZIP, dos ZIP ambiguos, CRS ausente, CRS EPSG:4326, campo faltante y archivo ilegible.
- `python scripts/02_prepare_municipalities.py --self-check` terminó `FIXTURE self-check preparación: 17/17`, salida 0. Cubre `5031` a `05031`, ausencia de `loaded_at`, metros cuadrados contra kilómetros cuadrados, departamento descubierto o tomado del Excel, reparación sin simplificar y rechazo de un fixture como si fuera el MGN nacional.

Esas pruebas no verifican la capa nacional ni los 170 municipios.

## Evidencia del intento real

La verificación TLS quedó activa. No se escribió `sources.mgn.file_url` y no se sustituyó el ZIP por otro sitio.

`www.dane.gov.co` respondió HTTPS 200. El buscador Joomla `index.php/component/search/?searchword=MGN2025` respondió HTTP 500, así que no aportó un enlace. La portada sí enlaza `https://geoportal.dane.gov.co/` y `https://www.datos.gov.co/`.

`geoportal.dane.gov.co` resuelve a `170.238.65.72`. El puerto 443 acepta la conexión y corta el saludo TLS: OpenSSL reporta `SSL handshake has read 0 bytes and written 330 bytes` y `unexpected eof while reading`. No hay certificado del servidor. HTTP en el puerto 80 responde 502. `curl` sale con el código 35.

Dos corridas seguidas de `python scripts/01_download_mgn.py` salieron con código 2 y el mismo error:

`SSLError: HTTPSConnectionPool(host='geoportal.dane.gov.co', port=443): Max retries exceeded with url: /servicios/descarga-y-metadatos/datos-geoestadisticos/?cod=111 (Caused by SSLError(SSLEOFError(8, '[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1000)')))`

El registro quedó en `outputs/mgn_download_attempt.json` con `status: blocked`, `claims_national_download: false` y `resolved_file_url: null`. No existe `outputs/mgn_download_manifest.json`.

Dos corridas de `python scripts/02_prepare_municipalities.py` salieron con código 2. `outputs/municipalities_prepare_report.json` dice `status: blocked_no_layer`, `municipalities_written: 0` y `claims_full_pdet_set: false`. No hay `data/processed/municipalities.geojsonl`.

## Catálogo oficial que sí respondió

`datos.gov.co` está enlazado desde la portada del DANE. Estos comandos se pueden repetir:

```bash
curl -fsS "https://www.datos.gov.co/api/views/8xdp-fsgm.json"
curl -fsS "https://cdge.dane.gov.co/api/v3/datasets/798ecd3194794ed69653ea3f948a9f4b_317"
curl -fsS "https://cdge.dane.gov.co/api/download/v1/items/798ecd3194794ed69653ea3f948a9f4b/geojson?layers=317"
openssl s_client -connect portalgis.dane.gov.co:443 -servername portalgis.dane.gov.co </dev/null
```

Lo observado el 2026-11-08 quedó en `outputs/mgn_catalog_probe.json`.

| Hecho | Valor observado |
| --- | --- |
| Ficha `8xdp-fsgm` | `Municipio`, MGN 2025, acceso público. La ficha apunta a `https://cdge.dane.gov.co/datasets/798ecd3194794ed69653ea3f948a9f4b_317` |
| Capa del hub | `Municipio`, 1122 polígonos, URL `https://portalgis.dane.gov.co/mparcgis/rest/services/MGN2025/Serv_CapasMGN_2025/MapServer/317` |
| Campos publicados | `MPIO_CDPMP`, `MPIO_CNMBRE` (alias "Nombre municipio"), `DPTO_CCDGO`, `DPTO_CNMBRE` (alias "Nombre departamento"), `MPIO_NAREA` |
| Alias de `MPIO_NAREA` | "Área departamento en kilómetros cuadrados" |
| CRS del MapServer | `wkid` 102100, `latestWkid` 3857 |
| Descarga del hub | HTTP 400, `Downloads are not supported for this item.` |
| Host de la geometría | `portalgis.dane.gov.co` (`170.238.64.31`) corta el TLS igual que el geoportal: EOF y sin certificado |

La ficha `7n6i-n9av` es la otra capa municipal MGN 2025 del mismo catálogo. También declara 1122 registros y el mismo alias de área, y su geometría está en `portalgis.dane.gov.co` (`Serv_DIVIPOLA_MGN_2025`). No se descargó.

Ese alias no se usó para convertir áreas. Dice "departamento" en una capa de municipios, y no hay un XML o TXT junto a un archivo leído. `area_unit` sigue sin fijarse. El diccionario de la Entrega 1 nombra `MPIO_CNMBR`; el servicio nombra `MPIO_CNMBRE`. Sin el shapefile no se puede saber cuál de los dos trae el ZIP. El `wkid` 3857 es el del MapServer, no una lectura del archivo, así que `config.yaml` sigue exigiendo EPSG:4686 para el ZIP.

## Lo que sigue sin resolverse

- La URL concreta del ZIP citado en `Project.tex`, su hash, el nombre real de la capa, el CRS leído del archivo y una unidad de `MPIO_NAREA` que no sea un alias ambiguo.
- Los 170 documentos. El 1122 del servicio es un conteo de metadatos nacionales, no el cruce PDET, y no incluye geometrías.
- La inserción, la idempotencia en MongoDB y el `explain()` del índice. Esos puntos de la rúbrica no se dan por hechos aquí.

La Entrega 2 de estos dos tramos no está completa: el código y los contratos sí están en el repositorio, y la capa real no.
