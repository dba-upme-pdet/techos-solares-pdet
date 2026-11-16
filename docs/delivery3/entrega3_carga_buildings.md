# Carga de huellas de edificaciones en MongoDB (Entrega 3, tramo de José)

Este documento cubre la carga en `upme_pdet.buildings` de las huellas que la
preparación de Derek declaró listas, para las dos fuentes del contrato de la
Entrega 3: Microsoft Global ML Building Footprints y Google Open Buildings v3.
No repite la descarga, la preparación ni el filtro PDET: su entrada es el
reporte de preparación y los GeoJSON Lines con gzip que ese reporte declara.

Script: [`scripts/04_load_buildings.py`](../../scripts/04_load_buildings.py).

## Compuerta de entrada

La carga no toca la base si el reporte de preparación no cumple el contrato
`entrega3-buildings-v1`:

- `status = ready_for_load`, `claims_pdet_selection = true`,
  `claims_full_source = true` y `totals.balanced = true`;
- `dataset_id` igual a la fuente que se va a cargar;
- por partición, el archivo existe, su SHA256 y sus bytes coinciden con
  `partitions[].output`, y su `source_file` es el `input.local_path` del
  manifiesto de descarga.

Un reporte en `sample_only` o `source_pass_only` nunca habilita la carga.

## Diseño de la carga

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

## Microsoft

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

Reportes: [`outputs/buildings_ms_prepare_report.json`](../../outputs/buildings_ms_prepare_report.json),
[`outputs/buildings_ms_load_report.json`](../../outputs/buildings_ms_load_report.json) y
[`outputs/buildings_ms_prepared_by_municipality.csv`](../../outputs/buildings_ms_prepared_by_municipality.csv).

## Google

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

Reportes: [`outputs/buildings_google_prepare_report.json`](../../outputs/buildings_google_prepare_report.json),
[`outputs/buildings_google_load_report.json`](../../outputs/buildings_google_load_report.json) y
[`outputs/buildings_google_prepared_by_municipality.csv`](../../outputs/buildings_google_prepared_by_municipality.csv).
La memoria se midió con `/usr/bin/time -l` en
[`docs/delivery3/evidencia/load_google_memory.txt`](evidencia/load_google_memory.txt).

## Estado de la base

Tras las dos cargas, `upme_pdet.buildings` tiene 4 455 805 documentos: 1 761 030
de `ms` y 2 694 775 de `google`. Las 125 particiones de Microsoft y las 8 de
Google dejaron una corrida por pasada en `ingestion_runs` (250 y 16 documentos,
respectivamente) y las dos fuentes están en `datasets`. El área geodésica
cargada suma 220 976 634 m² para Microsoft y 222 051 169 m² para Google.
Microsoft cubre los 170 municipios PDET; Google, 165.

## Repetición e idempotencia

Cada corrida completa se ejecuta con `--passes 2`. La primera pasada inserta;
la segunda vuelve a leer los mismos archivos, no inserta nada y el conteo de la
colección no cambia. La comprobación queda en
`verification.checks.rerun_does_not_duplicate` y en `idempotent = true` del
reporte de la fuente. Además, `--verify-only` recalcula las verificaciones
sobre la base ya cargada sin insertar, para no confundir una reverificación con
una carga nueva.

## Reproducción

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

## Cargador de Samuel: incompatibilidades

El cargador de la rama `feature/entrega3-eda`
([`03_load_buildings.py`](https://github.com/dba-upme-pdet/techos-solares-pdet/blob/feature/entrega3-eda/scripts/03_load_buildings.py))
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

## Evidencia

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
