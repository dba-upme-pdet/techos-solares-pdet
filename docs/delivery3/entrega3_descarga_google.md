# Entrega 3 — adquisición de Google Open Buildings (Sebastián Sánchez)

## Fuente e interfaz comprobadas

Fuente primaria: [Google Research Open Buildings](https://sites.research.google/gr/open-buildings/), apartados Data format, Download y licencia; [catálogo oficial de Earth Engine](https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_Research_open-buildings_v3_polygons). Se utiliza el producto **vectorial v3**, inferencia de mayo de 2023, no el producto temporal ráster. Google ofrece CC BY 4.0 u ODbL 1.0 a elección; aquí se registra **CC-BY-4.0**.

El enlace de metadatos de la página oficial conduce al [índice GeoJSON](https://openbuildings-public-dot-gweb-research.uw.r.appspot.com/public/tiles.geojson), con 333 celdas S2 nivel 4 y propiedades `tile_id`, `tile_url`, `size_mb`. Se constató que la antigua ruta `sites.research.google/open-buildings/tiles.geojson` devuelve 404; no se usa. Las URLs de datos se obtienen del índice y se verifican contra el prefijo oficial del producto v3.

El original es **CSV con gzip**, no GeoJSONL aunque Microsoft utilice un nombre parecido. Sus seis columnas son `latitude`, `longitude`, `area_in_meters`, `confidence`, `geometry` (WKT Polygon/MultiPolygon) y `full_plus_code`. Las posiciones son longitud/latitud geográficas interpretadas como WGS84/EPSG:4326. No hay altura. La publicación de Google ya tiene un umbral de detección; la adquisición del proyecto no añade filtros de confianza ni elimina registros originales.

## Procedimiento y seguridad de la ejecución

`scripts/03_download_google_buildings.py`:

1. Descarga el índice oficial y registra ruta, URL, bytes, SHA256, ETag, Last-Modified y MD5 publicado cuando existe.
2. Lee el GeoJSONL municipal, exige hash consistente y exactamente los 170 códigos oficiales del Excel. Selecciona las celdas que intersectan los polígonos; comprueba que su unión cubra todos los límites (tolerancia numérica 1e-8 grados).
3. Registra el plan, el volumen comprimido aproximado y espacio libre antes de descargar. `--plan-only` no descarga archivos de polígonos ni declara éxito completo; escribe `google_buildings_download_plan.json`, separado del manifiesto definitivo.
4. Descarga en bloques de 1 MiB a `.part`. Comprueba Content-Length y MD5 del servidor cuando se publica y calcula SHA256. Solo publica el archivo original tras terminar; un fallo elimina únicamente su temporal, conservando el archivo anterior. Los archivos registrados de una corrida previa se reutilizan solo si tamaño y SHA256 coinciden. `downloaded` es un checkpoint de bytes, no de inspección completa.
5. Lee **todo** el gzip, incluida su integridad/CRC al llegar al fin, en bloques de 10.000 registros. Comprueba columnas, parseo WKT, topología, tipo poligonal, coordenadas geográficas finitas, área positiva y confianza en [0,1]. Registra cantidades, tipos y rangos sin modificar los originales. Una partición con errores no se declara `ok`.
6. Escribe `complete` y `claims_pdet_coverage: true` únicamente si todas las particiones requeridas aprobaron y no quedaron límites municipales sin cubrir. Verifica el manifiesto con `download_manifest_problems(manifest, "google")`.

La cobertura afirmada es **cobertura por particiones descargadas y legibles**, no una garantía de que Google detectó edificios en cada municipio ni de exhaustividad del modelo. No se cuentan aquí edificios PDET por centroide: eso corresponde a la preparación, que debe excluir lo externo a los municipios. Los tiles incluyen territorio fuera de Colombia; se verifican rangos WGS84 globales durante adquisición. Las limitaciones y omisiones de detección de Google permanecen aplicables.

## Datos municipales y procedencia del contrato

Al iniciar faltaban los datos municipales locales. Se ejecutó el descargador oficial MGN en un directorio temporal con copias de configuración/reportes: descargó las seis páginas, todas coincidentes por contenido con el recibo, y produjo la capa nacional de 1122 municipios. Después se ejecutó el preparador oficial en otro entorno aislado, compartiendo únicamente el destino `data/`. Produjo los 170 municipios y recuperó el SHA256 esperado:

`612e2544be7ca2c22285aaac647819b910aa779ce61e1e5b872766051101f8ed`.

La evidencia resumida está en `outputs/google_municipalities_regeneration_evidence.json`; los originales y el manifiesto de regeneración quedan en `data/`, ignorados por Git. **No se sobrescribieron los reportes definitivos de la Entrega 2 ni se cargó MongoDB.**

Se incorporó únicamente `scripts/entrega3_contracts.py` desde `origin/entrega3/preparacion-huellas-ms`, commit **`1e3fdee`**, sin modificaciones: SHA256 `1537b3a7d5a10a315c41337139ea8eaa349501275f7a5e782c2021c147e8da2f`. No se fusionó esa rama ni su preparador. Así se usan directamente el validador y el contrato de Derek, sin duplicarlos. La futura integración de la rama deberá conservar el mismo archivo compartido.

## Comandos

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

## Entrega a Derek: manifiesto y lector son interfaces distintas

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

## Samuel / EDA

Se inspeccionaron `03_load_buildings.py`, `04_prepare_ms_buildings.py` y `eda_spatial_analysis.py` en `origin/feature/entrega3-eda` (`01a566b`). Utilizan otra entrada Microsoft y, en algunos puntos, claves `CONFIG["mongodb"]` y campos `geometry`/`geometry_centroid`; el esquema compartido del proyecto usa `mongo` y `footprint`/`centroid`. No se adaptó Google a esos nombres incompatibles ni se modificó su rama. Samuel y la carga deben coordinar esa interfaz con `entrega3_contracts.py` y los reportes preparados de Derek antes de comparar fuentes. No se ejecutó EDA ni se atribuyen cargas o métricas MongoDB a esta adquisición.

## Pruebas sintéticas y evidencia real

`google_download_tests.txt` registra **8/8 pruebas aprobadas**, incluida la integración sintética con el preparador upstream. Cubren selección y cobertura incompleta, índice inválido/duplicado, tamaños y MD5 incorrectos, conservación del archivo anterior y limpieza temporal, repetición segura y corrupción de caché, columnas/gzip inválidos, WKT/atributos y ausencia de un filtro adicional de confianza. Sin `DEREK_PREPARER_PATH`, ese caso de integración se marca omitido explícitamente; las otras siete pruebas son independientes.

La regeneración municipal, el índice y la inspección de CSV reales se distinguen de esas pruebas. El resultado de adquisición actual y sus magnitudes se resumen a continuación desde el manifiesto, sin inferir resultados de preparación o EDA.


## Resultado real del 16 de noviembre de 2026

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
