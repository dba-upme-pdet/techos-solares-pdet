# Entrega 2: carga de los municipios PDET en MongoDB

Responsable: Miguel Duarte. Script: `scripts/02_load_municipalities.py`.

El script carga los 170 municipios PDET que prepara `02_prepare_municipalities.py` en la colección `municipalities`. Antes de insertar deja activos el validador `$jsonSchema` y el índice `geometry_2dsphere` de `00_init_db.py`, así que MongoDB rechaza en ese momento cualquier documento o geometría inválida. La carga es idempotente: repetirla no crea duplicados.

## Comandos

```bash
docker compose up -d
python scripts/02_prepare_municipalities.py   # José: deja el GeoJSONL y el reporte
python scripts/02_load_municipalities.py --self-check
python scripts/02_load_municipalities.py
python scripts/02_load_municipalities.py      # otra vez: 0 insertados, 170 sin cambios
```

| Opción | Efecto |
| --- | --- |
| `--self-check` | Corre la carga completa contra MongoDB real en una base temporal `load_selfcheck_<uuid>` que se borra al final |
| `--prune` | Borra de `municipalities` los `_id` que no vienen en la entrada |
| `--allow-input-mismatch` | Carga aunque el SHA256 del GeoJSONL no sea el del reporte de José; queda `input_matches_prepare_report: false` en el reporte |

Códigos de salida: 0 si la carga quedó verificada, 1 si falla la entrada o alguna verificación, 2 si hay un error de MongoDB (no se imprime la URI).

## Entradas y salidas

| Pieza | Rol | Condición |
| --- | --- | --- |
| `outputs/municipalities_prepare_report.json` | entrada (José) | contrato `entrega2-mgn-v1`, `status = ready_for_load`, `claims_full_pdet_set = true`, `loaded_at_included = false` |
| `data/processed/municipalities.geojsonl` | entrada (José) | un documento por línea; SHA256 igual al del reporte |
| `municipalities` | salida | 170 documentos, `_id` = DIVIPOLA, `loaded_at` como fecha BSON en UTC |
| `pdet_subregions` | salida | 16 documentos `{_id, name, municipality_count}` |
| `ingestion_runs` | salida | una fila por corrida: `dataset_id: "mgn"`, `source_file`, `rows_read`, `rows_loaded`, `rows_rejected`, `started_at`, `finished_at`, `notes` |
| `outputs/municipalities_load_report.json` | salida | `role = load-report`; `status` `loaded`, `verification_failed`, `blocked` u `operational_error`; conteos, verificaciones, consulta de muestra y `run_id` |

El validador, los índices y las reglas del documento no se copian: el script importa `SCHEMAS` y `SMALL_INDEXES` de `00_init_db.py` y `document_errors` de `entrega2_contracts.py`. Lo que valida José al preparar, lo que carga Miguel y lo que verifica Sebastián es la misma regla.

## Cómo evita duplicados

1. El `_id` de cada documento es el código DIVIPOLA, así que MongoDB no admite dos documentos del mismo municipio (error 11000).
2. Antes de escribir, la carga se detiene si la entrada trae un `_id` repetido.
3. Cada documento se compara con el que ya está en la base, sin `loaded_at`: si no existe se inserta, si cambió se reemplaza y si es idéntico no se toca. Por eso `loaded_at` solo cambia cuando el municipio cambia.
4. Si en la base hay un `_id` que no está en la entrada, se reporta en `extra_in_db` y la carga no se da por buena hasta correr con `--prune`.

## Verificación posterior

| Verificación | Criterio |
| --- | --- |
| `count` | 170 documentos (`expected_municipalities` de `config.yaml`) |
| `ids_match_input` | Los `_id` de la base son los de la entrada |
| `no_duplicate_ids` | Sin `_id` repetidos |
| `no_duplicate_name_dpto` | Sin pares nombre + departamento repetidos |
| `schema_valid` | `$nor: [$jsonSchema]` no devuelve documentos |
| `loaded_at_present` | Todos los documentos tienen `loaded_at` |
| `spatial_index` | Hay un índice `2dsphere` sobre `geometry` |
| `geo_query_hits_sample` | `$geoIntersects` con un punto interior del primer municipio lo devuelve |
| `geo_query_uses_index` | El plan ganador usa `geometry_2dsphere` |

La verificación completa e independiente es `02_verify_spatial.py` (Sebastián).

## Evidencia

Carga definitiva del 9 de noviembre de 2026 (07:29, hora de Bogotá). Python 3.11.9, PyMongo 4.19.0, Shapely 2.2.0 y MongoDB 7.0.45 (`mongo:7.0` en Docker).

**Entrada:** `data/processed/municipalities.geojsonl` con SHA256 `612e2544be7ca2c22285aaac647819b910aa779ce61e1e5b872766051101f8ed`, el mismo de `municipalities_prepare_report.json`. El reporte de carga queda con `input_matches_prepare_report: true`. **No se usó `--allow-input-mismatch`.**

**Self-check: 16/16 OK.** Primera carga, segunda carga idéntica sin cambios, documento modificado reemplazado, subregiones e `ingestion_runs`, `_id` repetido y `loaded_at` en la entrada rechazados, `$jsonSchema` rechaza un `_id` de 4 dígitos y un documento sin `loaded_at` (121), `2dsphere` rechaza un polígono que se auto-intersecta (16755), `_id` rechaza un municipio repetido (11000), `_id` ajeno reportado y borrado con `--prune`, base temporal eliminada.

**Carga real, dos veces seguidas:**

| Corrida | Leídos | Insertados | Reemplazados | Sin cambios | Rechazados | En la colección |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 170 | 0 | 170 | 0 | 0 | 170 |
| 2 | 170 | 0 | 0 | 170 | 0 | 170 |

La corrida 1 reemplazó los 170 documentos de la carga de prueba anterior (archivo `b229d6a3…`, ver abajo); no insertó ninguno porque los 170 `_id` ya existían. La corrida 2 no tocó nada: 170 documentos, 170 `_id` distintos y el mismo `loaded_at` en todos. Las 9 verificaciones dieron OK en las dos corridas. Además:

- `municipalities`: índices `_id_`, `geometry_2dsphere` y `subregion_id_1`; validador con `validationAction: error` y los diez campos obligatorios.
- Geometrías: 170 `MultiPolygon` (168 de una sola parte; Tumaco con 3 y Buenaventura con 31). El documento más grande, Solano (18756), ocupa 1,75 MB en BSON (límite: 16 MB).
- `pdet_subregions`: 16 documentos cuyos `municipality_count` suman 170.
- `$geoIntersects` con un punto interior de Amalfi (05031) y de San Vicente del Caguán (18753): cada consulta devuelve solo su municipio, con `FETCH → IXSCAN` sobre `geometry_2dsphere`, 7 claves examinadas y 1 documento leído.
- `02_verify_spatial.py` (Sebastián) sobre esta misma base: **9/9 OK, salida 0**. Evidencia en `outputs/municipalities_spatial_verification_real.json`.

La base `upme_pdet` queda cargada con este archivo para la verificación espacial.

Municipios y área por subregión, leídos de la colección cargada:

| Subregión | Municipios | Área MGN (km²) |
| --- | ---: | ---: |
| Alto Patía y Norte del Cauca | 24 | 13 178 |
| Cuenca del Caguán y Piedemonte Caqueteño | 17 | 93 298 |
| Montes de María | 15 | 6 407 |
| Sierra Nevada - Perijá | 15 | 20 415 |
| Chocó | 14 | 29 548 |
| Bajo Cauca y Nordeste Antioqueño | 13 | 17 615 |
| Macarena - Guaviare | 12 | 96 169 |
| Pacífico y Frontera Nariñense | 11 | 17 119 |
| Putumayo | 9 | 25 063 |
| Urabá Antioqueño | 8 | 9 459 |
| Catatumbo | 8 | 9 238 |
| Sur de Bolívar | 7 | 10 332 |
| Sur de Córdoba | 5 | 9 581 |
| Pacífico Medio | 4 | 14 302 |
| Arauca | 4 | 10 540 |
| Sur del Tolima | 4 | 6 919 |

Para revisarlo en `mongosh`:

```javascript
use upme_pdet
db.municipalities.countDocuments()                       // 170
db.municipalities.distinct("_id").length                 // 170
db.municipalities.getIndexes()                           // _id_, geometry_2dsphere, subregion_id_1
db.ingestion_runs.find({dataset_id: "mgn"}).sort({started_at: -1})
db.municipalities.find(
  {geometry: {$geoIntersects: {$geometry: {type: "Point", coordinates: [-74.3088, 1.7374]}}}},
  {name: 1, subregion_name: 1})                          // San Vicente del Caguán
```

## Archivo definitivo frente a la carga de prueba

La primera carga (8 de noviembre) usó un GeoJSONL reconstruido a mano, SHA256 `b229d6a3…`, con `--allow-input-mismatch`, porque el `timeStamp` del WFS impedía validar la descarga. Eso quedó resuelto con el hash de contenido del recibo (`entrega2_descarga_y_preparacion.md`), y la cadena completa volvió a producir el archivo de José, `612e2544…`. Comparados por `_id`:

| Aspecto | Reconstruido (`b229d6a3…`) | Definitivo (`612e2544…`) |
| --- | --- | --- |
| Municipios | 170 | los mismos 170 |
| Nombre, departamento, subregión, `area_km2` | idénticos | idénticos |
| Coordenadas | idénticas en los 170 | idénticas en los 170 |
| `geometry.type` | 168 `Polygon`, 2 `MultiPolygon` (GML leído sin pasar por el GeoPackage) | 170 `MultiPolygon` (el GeoPackage guarda la capa como `MultiPolygon`) |
| `source.file` | `municipio.gpkg` | `Serv_CapasMGN_2025:Municipio` (campo `filename` del manifiesto) |
| Fin de línea | CRLF (escrito en Windows) | LF |

Las diferencias son de forma, no de contenido geográfico. Por eso la corrida 1 reemplazó los 170 documentos y la corrida 2 no cambió ninguno.
