# Entrega 3: preparación de huellas de edificaciones

Alcance: `scripts/03_prepare_buildings.py` y `scripts/entrega3_contracts.py`, tramo asignado a Derek. Toma las particiones que entrega un módulo de descarga, las convierte en documentos de la colección `buildings` del esquema de la Entrega 1 y deja un reporte por fuente que la carga usa como compuerta. No descarga y no inserta en `upme_pdet`.

## División del trabajo de Derek en dos tramos

Se partió por el estado real del repositorio el 14 nov 2026, no por mitades de la lista de tareas:

| Pieza | Estado en `main` |
| --- | --- |
| Descarga de Microsoft (Miguel) | Lista: manifiesto `complete`, 125 particiones, 4 595 615 features |
| Descarga de Google (Sebastián) | Sin código ni manifiesto |
| Carga en `buildings` (José, `04_load_buildings.py`) | Sin código |
| Capa PDET (Entrega 2) | Lista y verificada; el GeoJSONL está fuera de git |

| Tramo | Contenido | Estado |
| --- | --- | --- |
| **1** (este documento) | Contrato común de la Entrega 3 (manifiesto de descarga, registro preparado, reporte, motivos de rechazo), criterio espacial PDET, motor de preparación por bloques y la fuente Microsoft completa | Código, pruebas y corrida real de calidad listos. Falta la corrida con la capa PDET (ver [Pendiente](#pendiente-del-tramo-1)) |
| **2** | Adaptador de Google Open Buildings v3 sobre el mismo contrato (WKT, `area_in_meters` como `area_src_m2`, `confidence`, `full_plus_code` como `source_ref`), su reporte y la comparación de las dos fuentes que necesitan el EDA y la Entrega 4 | Empieza cuando exista el manifiesto de Sebastián |

Límite entre tramos: el tramo 2 solo agrega una entrada en `SOURCES` de `03_prepare_buildings.py` (lector + atributos) y su bloque en `config.yaml`. El contrato, el criterio espacial, los rechazos, el reporte y la compuerta de carga son los del tramo 1.

## Flujo

```mermaid
flowchart LR
    D["Descarga<br/>03_download_ms_buildings.py<br/>(Miguel)"] -->|"manifiesto + SHA256"| P
    M["Capa PDET<br/>municipalities.geojsonl<br/>(Entrega 2)"] -->|"ready_for_load + SHA256"| P
    P["Preparación<br/>03_prepare_buildings.py<br/>(Derek)"] -->|"part-*.jsonl.gz<br/>+ reporte"| L["Carga<br/>04_load_buildings.py<br/>(José)"]
    P --> R["rechazos y reparaciones<br/>por partición"]
    L --> B[("buildings<br/>ingestion_runs")]
```

## Comandos

```bash
python scripts/03_prepare_buildings.py --source ms                           # corrida que habilita la carga
python scripts/03_prepare_buildings.py --source ms --without-pdet-selection  # calidad de la fuente sin capa PDET
python scripts/03_prepare_buildings.py --source ms --partitions 032212332    # muestra; nunca queda lista para cargar
python -m unittest discover -s tests -p "test_prepare_buildings.py" -v
MONGO_URI=mongodb://admin:admin123@localhost:27017/ \
  python -m unittest discover -s tests -p "test_prepare_buildings_mongo.py" -v
```

Opciones: `--workers N` (procesos, por defecto hasta 4) y `--check-records` (valida cada registro contra el contrato antes de escribirlo). Rutas y parámetros en `config.yaml`, bloque `processing.buildings` y `sources.microsoft.prepare_*`.

## Contratos

### 1. Manifiesto de descarga (descarga → preparación)

`download_manifest_problems(manifest, dataset_id)` define lo que cualquier módulo de descarga debe entregar. El manifiesto actual de Microsoft lo cumple sin cambios (prueba `test_real_microsoft_manifest_passes`). El de Google debe cumplir lo mismo:

| Campo | Regla |
| --- | --- |
| `status` | `complete` |
| `claims_pdet_coverage` | `true` |
| `datasets_document` | `_id` (= `ms` o `google`), `name`, `version`, `license`, `url`, `accessed_at`: lo que exige el validador de `datasets` |
| `source.dataset_id` | Igual a la fuente, si viene |
| `partitions[]` | Cada una con `status = ok`, identificador único (`partition_id`; Microsoft usa `quadkey`), `local_path` y `download.sha256` |

Antes de leer una partición se recalcula su SHA256; si no coincide con el manifiesto, la corrida se detiene.

### 2. Registro preparado (preparación → carga)

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

### 3. Reporte de preparación (compuerta de la carga)

`outputs/buildings_<fuente>_prepare_report.json`. La carga solo debe leer archivos si `status = ready_for_load`, `claims_pdet_selection = true` y el SHA256 de cada `partitions[].output.path` coincide. El reporte trae:

- `input`: manifiesto de descarga y su SHA256, capa PDET y su SHA256.
- `datasets_document`: copiado del manifiesto, para insertarlo en `datasets`.
- `totals`: leídas, rechazadas por motivo, reparadas por acción, excluidas fuera de PDET, preparadas, duplicados, avisos de atributos, distribución de `area_m2` y `balanced`.
- `partitions[]`: por partición, entrada (ruta, SHA256), salida (ruta, SHA256, bytes, registros), rutas de los registros de rechazos y reparaciones, y los mismos contadores. Con eso la carga arma un `ingestion_runs` por partición: `source_file = input.local_path`, `rows_read = read`, `rows_rejected = rejected`, `rows_loaded` = insertados reales.
- `loader_contract`: estas mismas reglas en texto.

Estados posibles: `ready_for_load`, `source_pass_only` (sin capa PDET), `sample_only` (con `--partitions`) y `failed` (el balance no cierra). Solo el primero habilita la carga. Si una corrida nueva no termina lista, el reporte exitoso anterior queda copiado en `outputs/history/` (misma regla de la Entrega 2).

## Método

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

### Criterio espacial del territorio de interés

> Una edificación pertenece al territorio PDET si su **centroide** cae dentro o sobre el borde de uno de los 170 municipios PDET de la Entrega 2. Si cae sobre un borde compartido por dos municipios, se asigna al de **código DIVIPOLA menor**. Lo que cae fuera no se escribe; se cuenta como `excluded_outside_pdet`, no como rechazo.

Por qué así:

- Es la misma regla que fija la Entrega 1 para el conteo (asignación por centroide con `$geoWithin` sobre `buildings.centroid`). Cada edificación cuenta una sola vez, aunque su polígono cruce un límite.
- La Entrega 1 dejaba el desempate en "el primer municipio procesado". Aquí se fija el código menor para que el resultado no dependa del orden de ejecución.
- Filtrar antes de la carga cumple el plan de la Entrega 1 ("leer por bloques y descartar lo que cae fuera"): no se insertan millones de documentos que la Entrega 4 no usa.
- Implementación: `shapely.STRtree` sobre los 170 polígonos y `query(..., predicate="intersects")` sobre todos los centroides del bloque a la vez.

Diferencia con la Entrega 1, a la vista: el plan decía que `mpio_code` se llenaba en la fase 3. Ahora la preparación ya lo llena, porque la prueba de punto en polígono es necesaria para filtrar. La fase 3 puede usar `$geoWithin` como verificación independiente. Shapely trata los lados de un polígono como rectas en lon/lat y MongoDB como geodésicas, así que un centroide a centímetros de un límite puede caer distinto. La prueba de MongoDB confirma que cada edificación asignada a un municipio la devuelve `$geoWithin` sobre ese municipio. La única extra posible es el centroide exacto sobre el borde compartido.

### Archivos grandes y memoria

| Técnica | Efecto |
| --- | --- |
| Solo las particiones del manifiesto (las que tocan PDET) | 125 de 232 particiones de Colombia |
| Lectura en flujo desde gzip, bloques de 10 000 líneas | Ninguna partición se carga entera en memoria |
| Operaciones vectorizadas de shapely por bloque (`is_valid`, `centroid`, `STRtree.query`) | Unos 10 000 features/s por proceso |
| Un proceso por partición (`--workers`) | 4,6 millones de features en ~100 s con 4 procesos |
| Escritura incremental a `.partial` y renombre al terminar | Una corrida interrumpida no deja archivos a medias como buenos |
| Por edificación preparada, el proceso principal guarda solo hash, código y área (20 bytes) | ~92 MB para 4,6 millones; con eso se quitan duplicados y se arma el CSV por municipio sin releer la salida |

## Resultados con datos reales de Microsoft

Corrida del 14 nov 2026 con `--without-pdet-selection` sobre las 125 particiones del manifiesto de Miguel (versión `2026-02-03`), descargadas de nuevo en este entorno. Las 125 coincidieron byte a byte con el SHA256 del manifiesto. Reporte completo: [`outputs/buildings_ms_source_pass_report.json`](../../outputs/buildings_ms_source_pass_report.json).

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

Las 77 geometrías inválidas que reportó la descarga son exactamente las 29 reparadas más las 48 rechazadas. Cada una está, con su `source_ref` y el motivo de GEOS, en [`evidencia/ms_reparaciones_y_rechazos.csv`](evidencia/ms_reparaciones_y_rechazos.csv).

Área geodésica de las preparadas (m²):

| mín | p01 | p10 | mediana | p90 | p99 | máx | suma |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 9,66 | 17,75 | 29,84 | 82,69 | 261,09 | 1 413,64 | 76 453,09 | 699 938 128,81 |

Estas cifras incluyen edificaciones **fuera** de los municipios PDET (las particiones son cuadros de ~0,7° que se salen del territorio). No son el conteo PDET ni el área de techos de ningún municipio. El umbral `min_area_m2` (20 m²) no se aplica aquí: es un filtro de análisis de la Entrega 4, no un criterio de calidad.

### Qué está descargado, procesado, rechazado y cargado

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

### Cobertura geográfica real

- Fuente: solo Microsoft. Google todavía no está descargado.
- Particiones: 125 de las 232 de Colombia, las que tocan algún municipio PDET con un margen de 0,01°. No es todo el país.
- Según la cobertura de Miguel ([`entrega3_descarga_microsoft.md`](entrega3_descarga_microsoft.md)), 167 municipios PDET quedan cubiertos al 100 % por particiones publicadas. El Retorno (66,4 %), San José del Guaviare (69,7 %) y Miraflores (89,0 %) quedan en parte fuera, porque Microsoft no publica tres cuadros de Guaviare. Esa parte de su territorio no tiene datos de Microsoft.
- Extensión de los datos leídos: lon −79,00 a −69,92, lat −1,39 a 11,41.

## Pruebas y verificación

| Prueba | Resultado | Evidencia |
| --- | --- | --- |
| `tests/test_prepare_buildings.py`: 15 pruebas sintéticas: manifiesto real y manifiestos rotos, criterio espacial (dentro, fuera, borde, borde compartido), área geodésica contra proyección de área igual EPSG:6933 (diferencia < 0,1 %), reglas de reparación, atributos, contrato del registro, corrida completa con 13 features que cubren cada motivo, sin capa PDET, muestra, archivo alterado y repetición determinista | 15/15 OK | [`evidencia/prepare_tests.txt`](evidencia/prepare_tests.txt) (suite completa del repositorio: 55 pruebas OK) |
| `tests/test_prepare_buildings_mongo.py` en MongoDB 7.0.48: validador `buildings` de `00_init_db.py` en `strict`; sin `run_id` → rechazo; con `run_id` → insertado; `$geoWithin` sobre `centroid` devuelve cada edificación asignada; plan `FETCH → IXSCAN` | OK | [`evidencia/prepare_mongo_contract.txt`](evidencia/prepare_mongo_contract.txt) |
| Las 125 salidas reales (4 595 567 registros) por el mismo validador `strict`, `bulk_write` no ordenado en lotes de 10 000 | 4 595 567 insertados, 0 rechazos, 142 s | Mismo archivo |
| Repetición de la corrida real | Mismo SHA256 en las 125 salidas | [`evidencia/prepare_repeticion_memoria.txt`](evidencia/prepare_repeticion_memoria.txt) |

### Repetición y memoria

Dos corridas reales seguidas dieron el **mismo SHA256 en las 125 salidas** y los mismos totales. Los gzip se escriben con cabecera fija (`mtime = 0`, sin nombre de archivo) porque la cabecera normal guarda la hora y cambiaba el hash sin cambiar los datos. La prueba sintética revisa esa cabecera. El proceso más grande llegó a **486 MiB** de memoria residente y la corrida tardó 95 s con 4 procesos ([`evidencia/prepare_repeticion_memoria.txt`](evidencia/prepare_repeticion_memoria.txt)).

## Pendiente del tramo 1

La corrida que habilita la carga necesita `data/processed/municipalities.geojsonl`, que está fuera de git. En este entorno no se pudo regenerar: `portalgis.dane.gov.co` corta la conexión TLS (el mismo síntoma que registra `outputs/mgn_catalog_probe.json`). No se usó ninguna capa sustituta.

Quien tenga la capa de la Entrega 2 (Miguel la usó el 13 nov, SHA256 `612e2544…01f8ed`) corre:

```bash
python scripts/03_download_ms_buildings.py --offline   # confirma las 125 particiones
python scripts/03_prepare_buildings.py --source ms     # ~2 min con 4 procesos
```

Debe terminar con `Balance OK. Estado: ready_for_load` y dejar `outputs/buildings_ms_prepare_report.json` y `outputs/buildings_ms_prepared_by_municipality.csv` (edificaciones y área preparadas por municipio). Esos dos archivos se versionan. Los conteos de rechazo y reparación deben ser los de la tabla de arriba, porque se calculan antes del filtro espacial.

## Interfaces para el resto del equipo

| Quién | Usa | Qué debe hacer |
| --- | --- | --- |
| José (carga) | `outputs/buildings_ms_prepare_report.json` | Verificar la compuerta; insertar `datasets_document` en `datasets`; por partición crear un `ingestion_runs`, leer `output.path`, agregar `run_id` e `insert_many(ordered=False)` en lotes de 10 000; crear después los índices con `00_init_db.py --building-indexes` |
| Sebastián (descarga de Google) | `download_manifest_problems(manifest, "google")` | Escribir un manifiesto que la cumpla, con `partition_id` por celda S2 y `sources.google.manifest` en `config.yaml` |
| Verificación espacial | Reporte + CSV por municipio | Comparar los conteos por municipio con `$geoWithin` en MongoDB después de la carga |
| EDA | Reporte (`area_m2`, avisos de atributos) + `prepared_by_municipality.csv` | Partir de estas distribuciones para fijar `min_area_m2` |

## Limitaciones

- El centroide de un polígono cóncavo puede caer fuera de la huella. Para asignar municipio el efecto es mínimo con edificaciones de decenas de m², pero existe.
- El hash de duplicados es de 64 bits: la probabilidad de colisión con 4,6 millones de huellas es del orden de 10⁻⁶.
- `repair_split_multipolygon` rechaza 48 edificaciones reales en vez de partirlas, porque el esquema pide un solo `Polygon` por documento. Son el 0,001 % de lo leído.
