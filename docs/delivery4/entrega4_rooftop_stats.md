# Entrega 4: motor de estadísticas de techos y resultados de Microsoft

Tramo de Miguel. Script: [`scripts/06_rooftop_stats.py`](../../scripts/06_rooftop_stats.py).
Resultados: [`outputs/rooftop_stats_ms.csv`](../../outputs/rooftop_stats_ms.csv) y
[`outputs/rooftop_stats_ms_report.json`](../../outputs/rooftop_stats_ms_report.json).

## Qué hace

Un solo script calcula, para una fuente, el número de edificaciones y el área de techos de
cada uno de los 170 municipios PDET. La fuente se elige con `--source ms` o `--source google`;
el código, los filtros y las salidas son los mismos para las dos.

```bash
python scripts/06_rooftop_stats.py --source ms --passes 2   # análisis definitivo de Microsoft
python scripts/06_rooftop_stats.py --source google          # contraste (lo corre quien tenga Google cargado)
python scripts/06_rooftop_stats.py --self-check             # pruebas en una base temporal
```

Requisitos: `buildings` cargada con `04_load_buildings.py` (comprobable con
`python scripts/04_load_buildings.py --source ms --verify-only`) y `municipalities` con los 170
municipios. Salida: 0 resultado verificado, 1 falla de datos o verificación, 2 error operativo.

## Método

1. **Asignación al municipio.** Se usa `buildings.mpio_code`, que la preparación de la
   Entrega 3 llenó con el municipio que contiene el centroide de cada huella (`$geoWithin` sobre
   el índice `2dsphere`, verificado en la carga). El cálculo no vuelve a hacer la consulta
   espacial; agrupa por `{dataset_id, mpio_code}` con el índice `dataset_id_1_mpio_code_1`.
2. **Filtros de la metodología** (`config.yaml`, sección `analysis`). Se leen de ahí y se
   guardan en cada documento de resultado:

   | Filtro | Valor | Se aplica a | Motivo |
   | --- | --- | --- | --- |
   | Área mínima | `area_m2 >= 20` | Microsoft y Google | Umbral de la Entrega 1, confirmado con el EDA: por debajo hay casetas y ruido del modelo, sin espacio útil para paneles |
   | Área máxima | ninguna (`max_area_m2: null`) | — | Las huellas grandes (bodegas, instalaciones) son techo real; el script admite un tope si el equipo lo fija |
   | Confianza mínima | `confidence >= 0.70` | Solo Google (`confidence_sources`) | Microsoft no publica confianza (null salvo 176 huellas). Una huella de Google sin confianza no pasa |

   Una huella excluida se cuenta en el primer filtro que no cumple, en el orden de la tabla.
   Así los motivos suman el total excluido.
3. **Estadísticas por municipio.** Una agregación de MongoDB devuelve, por municipio, las huellas
   antes de filtrar, las excluidas por motivo y las áreas incluidas. La suma, el promedio y la
   **mediana exacta** se calculan en Python con esas áreas (`$median` de MongoDB 7 es aproximado).
   El área es la geodésica de la huella (`area_m2`, Entrega 3), no el área aprovechable: no se
   descuenta orientación, sombra ni pendiente.
4. **Los 170 municipios.** El resultado parte de `municipalities`, no de las huellas: un municipio
   sin huellas tras filtrar queda con `building_count = 0`, `total_area_m2 = 0` y promedio y
   mediana `null` (el validador de `rooftop_stats` en `00_init_db.py` acepta `null` en esos dos
   campos para este caso).
5. **Escritura idempotente.** Un documento por municipio y fuente con
   `_id = {mpio_code, dataset_id}` y `ReplaceOne(upsert=True)`. Repetir el cálculo reemplaza los
   mismos documentos. Si un municipio deja de existir en `municipalities`, se borra su resultado.
6. **Registro.** Cada documento lleva `filters`, `computed_at` y `script_version`. El reporte JSON
   registra la fuente (documento de `datasets`: nombre, versión, licencia, URL, fecha de acceso),
   los filtros, la fecha, las cantidades incluidas y excluidas por motivo, el balance y las
   verificaciones.

### Documento de `rooftop_stats`

| Campo | Contenido |
| --- | --- |
| `_id` | `{mpio_code, dataset_id}` |
| `mpio_code`, `dataset_id`, `name`, `dpto_code`, `dpto_name`, `subregion_id`, `subregion_name` | Identificación del municipio y la fuente |
| `building_count` | Edificaciones con centroide en el municipio que pasan los filtros |
| `total_area_m2`, `mean_area_m2`, `median_area_m2` | Suma, promedio y mediana del área de huella (m², 2 decimales) |
| `buildings_before_filters` | Huellas del municipio antes de filtrar |
| `excluded` | `{below_min_area, above_max_area, low_confidence}` |
| `rank_total_area` | Puesto del municipio por área total dentro de la fuente (1 = mayor) |
| `filters`, `computed_at`, `script_version` | Filtros aplicados, fecha UTC del cálculo y versión del script |
| `google_low_coverage` | Solo en Google: municipio de la lista de cobertura insuficiente ([README](README.md)) |

El CSV tiene las mismas columnas (con `excluded` separado en tres), una fila por municipio,
ordenado por `rank_total_area`.

### Verificaciones

Después de escribir, el script compara lo guardado con consultas independientes:

| Verificación | Qué comprueba |
| --- | --- |
| `all_pdet_municipalities` | Hay exactamente un resultado por cada municipio de `municipalities` (170) |
| `no_duplicate_municipalities` | Ningún municipio tiene dos documentos de la misma fuente |
| `stored_matches_computed` | Lo guardado es igual a lo calculado |
| `included_matches_independent_count` | La suma de `building_count` es igual a un `count_documents` con los filtros escritos como consulta, sin la agregación |
| `balance_with_source` | Incluidas + excluidas + fuera de PDET = huellas de la fuente en `buildings` |
| `filters_recorded` | Todos los documentos guardan los filtros de esta corrida |
| `empty_municipalities_without_mean` | Un municipio sin edificaciones no trae promedio ni mediana |
| `rerun_does_not_duplicate` | Con `--passes 2`: la segunda pasada no inserta nada, deja 170 documentos y los mismos valores |

## Análisis definitivo de Microsoft

Corrida del 19 nov 2026, 19:38 UTC, en el entorno de Miguel (MongoDB 7.0.45), con
`--passes 2`. Fuente: Microsoft Global ML Building Footprints, versión `2026-02-03`,
ODbL-1.0, accedida el 13 nov 2026. Log: [`evidencia/rooftop_stats_ms_run.txt`](evidencia/rooftop_stats_ms_run.txt).

Antes de calcular, la base local se reconstruyó con los scripts de la Entrega 3
(`03_prepare_buildings.py --source ms` y `04_load_buildings.py --source ms`): mismas 1.761.030
huellas PDET, 48 rechazadas y 2.834.537 fuera de PDET que en el reporte versionado; las seis
verificaciones de la carga en `OK`. Los reportes versionados de la Entrega 3 no se modificaron.

| Cantidad | Valor |
| --- | ---: |
| Huellas de Microsoft en `buildings` (asignadas a un municipio PDET) | 1.761.030 |
| Excluidas: área menor de 20 m² | 40.495 (2,3 %) |
| Excluidas: área máxima / confianza | 0 / 0 (no aplican a Microsoft) |
| **Edificaciones incluidas** | **1.720.535** |
| **Área total de techos** | **220,27 km²** (220.266.587 m²) |
| Municipios con resultado / con edificaciones | 170 / 170 |
| Mediana del área total por municipio | 0,87 km² |
| Duración (dos pasadas) | 33,7 s |

Las ocho verificaciones quedaron en `OK`. Las dos pasadas reemplazaron los mismos 170
documentos (`upserted = 0` en ambas, `same_values_as_previous = true`), y una corrida aparte
dejó un CSV con los mismos valores salvo `computed_at`. Repetir el análisis no duplica.

El filtro de 20 m² quita a lo sumo el 5,2 % de las huellas de un municipio (Dibulla), así que el
total queda cerca del EDA de la Entrega 3 (221,0 km² sin filtrar).

### Diez municipios con más área de techos (Microsoft)

| # | Código | Municipio | Edificaciones | Área (km²) |
| ---: | --- | --- | ---: | ---: |
| 1 | 47001 | Santa Marta | 66.497 | 14,20 |
| 2 | 20001 | Valledupar | 62.178 | 13,51 |
| 3 | 76109 | Buenaventura | 32.632 | 7,11 |
| 4 | 18001 | Florencia | 26.487 | 6,68 |
| 5 | 05837 | Turbo | 42.084 | 4,63 |
| 6 | 52835 | San Andrés de Tumaco | 40.707 | 4,47 |
| 7 | 19698 | Santander de Quilichao | 30.341 | 4,22 |
| 8 | 18753 | San Vicente del Caguán | 22.997 | 3,75 |
| 9 | 54810 | Tibú | 34.622 | 3,56 |
| 10 | 47189 | Ciénaga | 21.475 | 3,47 |

Los de menor área son Sipí (642 edificaciones; 0,05 km²) y Murindó (1.311; 0,11 km²).

### Por subregión PDET (suma de sus municipios)

| Subregión | Edificaciones | Área (km²) |
| --- | ---: | ---: |
| Sierra Nevada - Perijá | 287.899 | 46,20 |
| Alto Patía y Norte del Cauca | 265.317 | 30,17 |
| Cuenca del Caguán y Piedemonte Caqueteño | 131.224 | 22,52 |
| Urabá Antioqueño | 110.379 | 15,25 |
| Putumayo | 106.390 | 13,79 |
| Montes de María | 126.814 | 11,78 |
| Macarena - Guaviare | 91.513 | 11,46 |
| Bajo Cauca y Nordeste Antioqueño | 99.599 | 10,65 |
| Arauca | 73.091 | 10,18 |
| Catatumbo | 87.522 | 9,20 |
| Pacífico Medio | 48.837 | 8,74 |
| Sur de Córdoba | 79.095 | 8,30 |
| Pacífico y Frontera Nariñense | 77.821 | 8,09 |
| Sur de Bolívar | 51.577 | 5,82 |
| Sur del Tolima | 46.767 | 4,74 |
| Chocó | 36.690 | 3,40 |

La tabla completa de los 170 municipios está en el CSV.

## Pruebas

- `tests/test_rooftop_stats.py`: 11 pruebas sintéticas sin MongoDB (filtros y sus bordes, orden de
  los motivos, municipios vacíos, `_id` compuesto, mediana exacta, ranking, marca de Google, CSV).
- `tests/test_rooftop_stats_mongo.py`: corre `--self-check` en una base temporal (13 comprobaciones:
  filtros dentro de la agregación, misma regla en Python y en MongoDB, municipio vacío con `null`,
  huella sin municipio fuera del balance, validador, dos fuentes sin pisarse e idempotencia).
  Resultado: [`evidencia/rooftop_stats_selfcheck.txt`](evidencia/rooftop_stats_selfcheck.txt).

```bash
MONGO_URI=mongodb://admin:admin123@localhost:27017/ python -m unittest discover -s tests -p "test_rooftop_stats*.py" -v
```

## Pendiente para el equipo

- Correr `--source google` donde esté cargada Google; el motor ya aplica la confianza mínima y
  marca los 15 municipios con cobertura insuficiente.
- Si el equipo decide un área máxima o un factor de aprovechamiento, se cambia en `config.yaml`
  (`max_area_m2`) y se vuelve a correr; el filtro queda registrado en cada resultado.
