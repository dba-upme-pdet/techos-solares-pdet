# Entrega 4: validación independiente y reproducción del análisis

Tramo de José. Scripts: [`scripts/10_validate_analysis.py`](../../scripts/10_validate_analysis.py)
(validación) y [`scripts/11_run_analysis.py`](../../scripts/11_run_analysis.py) (corrida completa).
Resultado: [`outputs/validation/entrega4_validation_report.json`](../../outputs/validation/entrega4_validation_report.json),
**47/47 verificaciones en `OK`**.

```bash
python scripts/11_run_analysis.py              # análisis completo en orden; se detiene en el primer error
python scripts/10_validate_analysis.py         # solo la validación (necesita rooftop_stats de las dos fuentes)
python -m unittest discover -s tests -p "test_validate_analysis.py" -v
```

Entorno de las corridas (20 nov 2026, máquina de José): macOS 26.6.2 arm64, Python 3.14.7,
MongoDB 7.0.48, pymongo 4.20.0, shapely 2.2.0, pyproj 3.8.0, pandas 3.1.1, numpy 2.5.5, sobre el
commit `dd46825` y `config.yaml` con SHA256 `d55e9591…b280`. La base es la carga original de la
Entrega 3 (16 nov), no una reconstrucción.

## Qué es independiente

`10_validate_analysis.py` no importa el motor de `06_rooftop_stats.py` para calcular. Vuelve a leer
`buildings` municipio por municipio, reescribe los filtros de `config.yaml` con pandas y calcula
conteo, suma (`math.fsum`), promedio y mediana. Solo importa el motor para pedir el `explain` de sus
propias consultas. Una prueba sintética comprueba que la regla en pandas da el mismo motivo de
exclusión que la del motor, huella por huella.

## 1. Entradas y estado de MongoDB

| Comprobación | Microsoft | Google |
| --- | ---: | ---: |
| Huellas en `buildings` | 1.761.030 | 2.694.775 |
| Preparadas (reporte de preparación) / cargadas (reporte de carga) | 1.761.030 / 1.761.030 | 2.694.775 / 2.694.775 |
| Estado de los reportes | `ready_for_load`, `loaded`, idempotente | `ready_for_load`, `loaded`, idempotente |
| Municipios con huellas | 170 | 165 |
| Municipios cuyo conteo difiere del CSV de preparación | 0 | 0 |
| Huellas sin `mpio_code` | 0 | 0 |
| Documento de `datasets` | ODbL-1.0, versión `2026-02-03` | CC-BY-4.0, `v3` |
| `ingestion_runs` | 250 | 16 |

Además: `municipalities` tiene 170 documentos y `pdet_subregions` 16, y el SHA256 de
`data/processed/municipalities.geojsonl` es el que declara el reporte de la Entrega 2
(`612e2544…f8ed`). El reporte guarda el SHA256 de cada archivo de entrada.

## 2. Conteos y áreas por municipio

El recálculo se comparó con cuatro referencias (detalle por municipio en
[`validation_by_municipality.csv`](../../outputs/validation/validation_by_municipality.csv)):

| Contra | Filas | Resultado |
| --- | ---: | --- |
| Colección `rooftop_stats` (las dos fuentes) | 340 | Idéntico: conteos, excluidas por motivo, suma, promedio y mediana |
| `outputs/rooftop_stats_ms.csv` y `rooftop_stats_google.csv` de esta corrida | 170 + 170 | Idéntico |
| CSV de preparación de la Entrega 3 (antes de filtros) | 170 + 170 | Conteos idénticos. El área difiere a lo sumo 1,07 m² (Microsoft) y 1,69 m² (Google) por municipio |
| `outputs/rooftop_stats_ms.csv` publicado por Miguel (`HEAD`, 19 nov, su entorno) | 170 | Conteos, promedios y medianas idénticos. El área total difiere en 148 municipios, a lo sumo 0,15 m² |

**Diferencias explicadas.**

- *Contra la preparación:* `area_m2` se guarda redondeada a 2 decimales y la preparación sumó las
  áreas sin redondear. La cota es 0,005 m² por huella; la diferencia mayor llega al 31 % de esa
  cota (Google) y al 4 % (Microsoft).
- *Contra el CSV de Miguel:* todas las diferencias son múltiplos exactos de 0,01 m². Son unas pocas
  huellas cuya área geodésica se redondeó al centímetro cuadrado contrario en su base reconstruida.
  En total son 0,78 m² sobre 220,27 km², y la diferencia relativa máxima por municipio es
  3,2 × 10⁻⁷. La validación acepta 10⁻⁶ relativo entre entornos distintos y exige igualdad exacta
  dentro del mismo entorno. Ninguna cifra del informe cambia.

Totales recalculados: Microsoft 1.720.535 edificaciones y 220,27 km²; Google 2.067.004 edificaciones
y 203,75 km² (excluidas 368.619 por área y 259.152 por confianza).

## 3. Asignación espacial y diferencias de borde

La asignación `mpio_code` se contrastó de tres formas:

| Método | Microsoft | Google |
| --- | --- | --- |
| (a) shapely, regla de la preparación (centroide dentro o en el borde; empate → código menor) | 1.761.030 / 1.761.030 iguales | 2.694.774 iguales, 0 distintas, 1 fuera de todo municipio |
| (b) `$geoWithin` esférico de MongoDB, municipio por municipio | 100 % confirmadas | 100 % confirmadas |
| Centroides que el modelo esférico ve dentro de un segundo municipio | 1 (asignada a 47053, también en 47189) | 1 (asignada a 05837, también en 05665) |

Casos de borde:

- **Google `938c167c…`** (Tibú, 54800): el centroide guardado queda a **0,5 mm** fuera del
  polígono. La preparación usó el centroide sin redondear, y el valor guardado tiene 7 decimales
  (~1 cm). La comprobación acepta este caso solo si la distancia es de 10⁻⁷ grados o menos.
- **Plano y esfera:** shapely trata los lados del polígono como rectas en lon/lat, y MongoDB como
  geodésicas. Un punto por fuente queda dentro de dos municipios en la esfera y de uno solo en el
  plano. En Google, la regla del código menor daría 05665 en vez de 05837. Es una huella entre
  4,46 millones y no cambia ninguna cifra publicada.

**Huellas que cruzan el límite municipal.** La metodología asigna la huella completa al municipio de
su centroide. Para medir el efecto se leyeron las huellas cuyo centroide está a menos de 0,005°
(~550 m) del límite: 193.276 de Microsoft y 300.516 de Google. Se leyeron también todas las de
5.000 m² o más. Para cada una se calculó, con área geodésica, la parte que queda fuera de su
municipio:

| | Microsoft | Google |
| --- | ---: | ---: |
| Huellas que cruzan el límite | 1.405 | 2.115 |
| Área de esas huellas | 277.689 m² | 209.452 m² |
| Parte que queda fuera del municipio asignado | 35.939 m² | 37.207 m² |
| Como fracción del área total incluida | 0,016 % | 0,018 % |
| Distancia máxima del centroide a un vértice (huellas leídas) | 235 m | 215 m |

La distancia máxima (235 m) es menor que el margen de 550 m, así que el margen alcanza para todas
las huellas leídas. Los municipios más afectados son costeros o ribereños: Tumaco, Buenaventura,
Turbo y Necoclí. El caso mayor es 8.238 m² en Tumaco (Google). La tabla completa está en
[`border_footprints_by_municipality.csv`](../../outputs/validation/border_footprints_by_municipality.csv).
La base solo contiene huellas asignadas a municipios PDET. Por eso no se puede medir el área que
entra desde un municipio no PDET vecino.

## 4. Índices y planes de ejecución

Planes con `explain("executionStats")` sobre la base real:

| Consulta | Índice del plan ganador | Claves / documentos examinados | Tiempo |
| --- | --- | ---: | ---: |
| Agregación de `06_rooftop_stats.py`, Microsoft | `IXSCAN dataset_id_1_mpio_code_1` → `FETCH` | 1.761.030 / 1.761.030 | 1,6 s |
| Agregación de `06_rooftop_stats.py`, Google | `IXSCAN dataset_id_1_mpio_code_1` → `FETCH` | 2.694.775 / 2.694.775 | 3,2 s |
| Conteo independiente con filtros, Microsoft / Google | `IXSCAN dataset_id_1_mpio_code_1` | 1.761.030 / 2.694.775 docs | 0,7 / 1,8 s |
| Huellas de una fuente y un municipio (Santa Marta) | `IXSCAN dataset_id_1_mpio_code_1` | 67.663 / 67.663 | 27 ms |
| `$geoWithin` de centroides en Santa Marta | `IXSCAN centroid_2dsphere` | 267.072 / 267.058 | 3,4 s |
| Municipio de un punto (`$geoIntersects`) | `IXSCAN geometry_2dsphere` | 6 / 1 | 2 ms |
| `rooftop_stats` por fuente (`_id.dataset_id`) | `COLLSCAN` | 340 docs | 0 ms |

Ninguna consulta sobre `buildings` recorre la colección completa. Dos observaciones, sin cambios
aplicados:

- El conteo con filtros hace `FETCH` de cada huella porque `area_m2` y `confidence` no están en el
  índice. Un índice `{dataset_id, mpio_code, area_m2, confidence}` haría que el índice cubriera la
  consulta. Hoy tarda 2 s, así que no hace falta.
- `rooftop_stats` se consulta por `_id.dataset_id` sin índice. Con 340 documentos no importa.

## 5. Coherencia de filtros, unidades, municipios y resultados de las dos fuentes

| Comprobación | Resultado |
| --- | --- |
| Los 170 municipios en `municipalities`, en `rooftop_stats` y en los dos CSV | Mismo conjunto en las dos fuentes |
| Filtros guardados en cada documento = `config.yaml` | Sí: `min_area_m2 = 20` y sin máximo en las dos; `min_confidence = 0,70` solo en Google |
| Misma `script_version`, nombres y subregiones en las dos fuentes | Sí |
| Unidades: `area_m2` frente al área geodésica de la huella recalculada (2.000 por fuente) | Diferencia máxima de 0,005 m², es decir, el redondeo a cm² |
| Google: `area_m2` / área publicada por Google (`area_src_m2`, 20.000 huellas) | Mediana 0,9958 (p1 0,9953, p99 0,9962) |
| Regla de cobertura insuficiente recalculada (`google < 0,2 × ms`, antes de filtros) | Los mismos 15 códigos de `config.yaml`, y la marca de Google coincide |
| Spearman Microsoft–Google en los 155 municipios comparables | Conteo 0,912; área 0,941 |

El área geodésica del proyecto es un 0,4 % menor que la que publica Google para la misma huella, y
la diferencia es constante (p1–p99 dentro de ±0,05 %). Parece una diferencia de método de cálculo
de Google; no altera el orden de los municipios. Las correlaciones son algo mayores que las del EDA
de la Entrega 3 (0,904 y 0,938) porque ahora se calculan tras los filtros y sin los 15 municipios
marcados.

## 6. Corrida completa: `11_run_analysis.py`

Ejecuta en orden y se detiene en el primer paso que devuelve un código distinto de 0:

| # | Paso | Script |
| ---: | --- | --- |
| 1 | entorno | `00_check_environment.py` |
| 2 | esquema e índices | `00_init_db.py --building-indexes` |
| 3 | municipios | `02_verify_spatial.py --report <run_dir>/…` |
| 4–5 | huellas cargadas | `04_load_buildings.py --source ms\|google --verify-only` |
| 6–7 | estadísticas | `06_rooftop_stats.py --source ms\|google --passes 2` |
| 8 | validación | `10_validate_analysis.py` |
| 9–11 | resumen, figuras y tablas | `07`, `08`, `09` (se omiten con `--no-report`) |
| 12 | informe PDF | `latexmk` (solo con `--pdf`) |

El código de salida es el del paso que falló, o 0 si todos terminan bien. La salida de cada paso
queda en `<run_dir>/run.log`.

## 7. Registro de tiempos, parámetros, versiones y procedencia

`<run_dir>/run_manifest.json` guarda:

- **Tiempos:** inicio, fin, duración y código de salida de cada paso. Se mide con reloj de pared,
  porque `perf_counter` de macOS no cuenta el tiempo en que el equipo está en reposo. Lo descubrimos
  en una corrida de prueba en la que faltaban 111 s.
- **Parámetros:** la sección `analysis` de `config.yaml` y su SHA256.
- **Versiones:** Python, plataforma, paquetes de `requirements.txt` y numpy, versión de MongoDB, host
  y base (sin credenciales), commit, rama y archivos sin confirmar.
- **Procedencia:** SHA256 de cada archivo de `outputs/` y `docs/delivery4/figuras`, con el paso que
  lo modificó por última vez.
- **Huella de resultados:** SHA256 de cada CSV de `rooftop_stats` sin la columna `computed_at`. Si
  dos corridas dan la misma huella, sus valores son iguales.

## 8. Evidencia de validación y repetición

Corridas reales en `outputs/validation/runs/`:

| Corrida | Estado | Duración | Huella `ms` | Huella `google` |
| --- | --- | ---: | --- | --- |
| [`corrida1`](../../outputs/validation/runs/corrida1/run_manifest.json) | `completed`, 11/11 pasos | 167,0 s | `4d00d4c0…044e` | `9fd85fc2…2e8a` |
| [`corrida2`](../../outputs/validation/runs/corrida2/run_manifest.json) | `completed`, 11/11 pasos | 164,2 s | `4d00d4c0…044e` | `9fd85fc2…2e8a` |
| [`corrida_con_error`](../../outputs/validation/runs/corrida_con_error/run_manifest.json) | `stopped_on_error` en el paso 2 (MongoDB en un puerto sin servidor), código 1 | 10,9 s | — | — |

Duración de los pasos de `corrida2`: validación 120,1 s, verificación de huellas 8,9 s + 13,5 s,
estadísticas 5,2 s + 9,2 s y el resto menos de 4 s cada uno.

**Repetición.** Las dos corridas dan resultados idénticos para las dos fuentes. Entre ellas, 33 de
los 41 archivos registrados tienen el mismo SHA256. Los otros 8 solo cambian en fechas o en el orden
de una lista:

- Los CSV y reportes de `rooftop_stats` cambian por `computed_at`, pero la huella de contenido es
  igual.
- Los reportes de carga cambian por `verified_at`.
- El reporte de validación cambia por sus fechas y tiempos.
- `entrega4_analysis_summary.json` cambia porque `07_entrega4_analysis.py` escribe
  `low_coverage_municipalities` desde un `set`, cuyo orden varía entre ejecuciones de Python. Se
  verificó corriendo el script dos veces. Para el autor del script: ordenar la lista
  (`sorted(...)`) lo vuelve determinista.

Las figuras y las tablas de `09` salieron iguales en las dos corridas. Frente a la versión publicada,
solo cambia `scatter_count_vs_area.png`. Se generó con el CSV reproducido, que difiere en céntimos
de m², y no se versiona.

**Qué se versiona.**

- Los resultados de Google ([`rooftop_stats_google.csv`](../../outputs/rooftop_stats_google.csv) y
  su reporte) son nuevos: es la primera corrida de `--source google`. 170 municipios, 164 con
  edificaciones. Los 6 sin edificaciones son 5 sin huellas de Google y Sipí, que tiene una sola
  huella y no pasa los filtros.
- `rooftop_stats_ms.csv` y su reporte quedan como los publicó Miguel. La copia reproducida de
  `corrida2` está en
  [`runs/corrida2/reproduccion/`](../../outputs/validation/runs/corrida2/reproduccion/), y la
  comparación con la publicada está en la sección 2.
- Los reportes de carga de la Entrega 3 solo ganan el campo `verified_at` de la reverificación.

Pruebas: 110 pruebas del repositorio en `OK` (2 omitidas por requerir datos externos). Incluyen las 12
nuevas de `tests/test_validate_analysis.py`. El log está en
[`evidencia/validacion_tests.txt`](evidencia/validacion_tests.txt).
