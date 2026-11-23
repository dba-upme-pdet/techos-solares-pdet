# Entrega 4: flujo reproducible de análisis geoespacial

Entrega: lunes 23 nov 2026, antes de las 14:00 (`America/Bogota`). Debe incluir:

- **Reproducibilidad y metodología:** cómo se calculan el número y el área total de techos por municipio PDET.
- **Estructura de salida (tablas y mapas):** resultados con visualizaciones adecuadas.

Rúbrica del profesor: [`DBA_2630_FinalProject_RubricWeek4.pdf`](https://github.com/aocalderon/PUJ/blob/main/2026-30/DBA/Project/resources/rubrics/DBA_2630_FinalProject_RubricWeek4.pdf)
(Reproducibility & Methodology 25, Output Data Structure 20).

## Punto de partida: hallazgos de la Entrega 3

Fuente: [`docs/delivery3/entrega3_eda.md`](../delivery3/entrega3_eda.md) y
[`outputs/eda/eda_buildings_summary.json`](../../outputs/eda/eda_buildings_summary.json),
generados por `python scripts/05_eda_buildings.py`.

### Decisiones metodológicas y contrato compartido

La especificación completa y verificable está en [`entrega4_metodologia_y_contrato.md`](entrega4_metodologia_y_contrato.md),
implementada en [`scripts/entrega4_contracts.py`](../../scripts/entrega4_contracts.py) y parametrizada en
[`config.yaml`](../../config.yaml) (sección `analysis`):

1. **Microsoft es la fuente base** (`dataset_id = "ms"`, cobertura en 170/170 municipios PDET; 3 municipios de Guaviare tienen cobertura parcial de particiones quadkey publicadas, limitación documentada). **Google se reporta aparte como contraste** (165/170 municipios) y **nunca se suman las dos fuentes**.
2. **Filtros definitivos:** `area_m2 >= 20` para ambas fuentes, `max_area_m2 = null` (se conservan huellas grandes y se reportan media y mediana exacta), y `confidence >= 0.70` únicamente para Google (`confidence_sources: ["google"]`). En Microsoft `confidence` es `null` en 1.761.020 de 1.761.030 huellas PDET (99,9994 %), por lo que no se aplica filtro de confianza ni se imputan valores.
3. **Asignación espacial:** centroide WGS84 intersectando los 170 polígonos MGN2025, con desempate determinista por código DIVIPOLA menor (`0` empates observados en ambas fuentes).
4. **Área de huella frente a área aprovechable:** las métricas reportan área geodésica de huella en `m²` (`km² = m² / 10^6`). No se aplica ningún factor de aprovechamiento solar sin respaldo (`usable_area_factor: null`).
5. **15 municipios con cobertura insuficiente de Google:** definidos por la regla exacta `5 * google_buildings < ms_buildings` (`< 20 %`) sobre el EDA de la Entrega 3 (`outputs/eda/eda_buildings_summary.json`). Se conservan sus valores observados, se marcan con `google_low_coverage = true`, no entran en diferencias analíticas directas y se aclara que la causa no está demostrada.
6. **Correlación del EDA histórico:** `0,904` en conteo y `0,938` en área corresponden a Spearman sobre los **165 municipios con `google > 0`** en el EDA sin filtros (excluye los 5 municipios con cero en Google, no los otros 10 señalados). No sustituyen la correlación filtrada de la Entrega 4.

| Código | Municipio | Subregión PDET | Edif. Microsoft (EDA) | Edif. Google (EDA) |
| --- | --- | --- | ---: | ---: |
| 05475 | Murindó | Chocó | 1.331 | 0 |
| 05873 | Vigía Del Fuerte | Chocó | 1.714 | 0 |
| 19418 | López De Micay | Pacífico Medio | 5.968 | 24 |
| 27099 | Bojayá | Chocó | 2.004 | 0 |
| 27150 | Carmen Del Darién | Chocó | 3.832 | 281 |
| 27205 | Condoto | Chocó | 2.110 | 239 |
| 27250 | El Litoral Del San Juan | Chocó | 2.010 | 309 |
| 27425 | Medio Atrato | Chocó | 1.615 | 313 |
| 27450 | Medio San Juan | Chocó | 1.627 | 0 |
| 27491 | Nóvita | Chocó | 1.403 | 0 |
| 27615 | Riosucio | Chocó | 6.107 | 1.000 |
| 27745 | Sipí | Chocó | 653 | 1 |
| 52612 | Ricaurte | Pacífico Y Frontera Nariñense | 4.878 | 196 |
| 52621 | Roberto Payán | Pacífico Y Frontera Nariñense | 2.501 | 364 |
| 73616 | Rioblanco | Sur Del Tolima | 9.018 | 1.329 |

## Estado de la Entrega 4 por integrante

| Integrante | Tramo | Artefactos principales | Estado |
| --- | --- | --- | --- |
| Derek | Metodología y contrato compartido | `config.yaml`, `scripts/entrega4_contracts.py`, [`entrega4_metodologia_y_contrato.md`](entrega4_metodologia_y_contrato.md), `tests/test_entrega4_contracts.py`, [`evidencia/contract_validation.txt`](evidencia/contract_validation.txt) | Completo y validado sobre `main` (contrato `entrega4-rooftop-stats-v1`, metodología `entrega4-methodology-v1`) |
| Miguel | Motor común (`06_rooftop_stats.py`) y resultados de Microsoft | `scripts/06_rooftop_stats.py`, [`entrega4_rooftop_stats.md`](entrega4_rooftop_stats.md), `outputs/rooftop_stats_ms.csv`, `outputs/rooftop_stats_ms_report.json` | Completo y alineado al contrato compartido (170 municipios, 1.720.535 edificaciones, 220,27 km², 8/8 verificaciones OK) |
| Sebastián | Resultados de Google y comparación entre fuentes | Rama `feature/sebastian-environment`: `scripts/06_compare_rooftop_stats.py`, `docs/delivery4/entrega4_google_comparacion.md`, `tests/test_compare_rooftop_stats.py` | Implementación adaptada y comparación definitiva ejecutada localmente con Google de José (`corrida2`, 2.067.004 incluidas, 203,75 km²) y Microsoft de Miguel. 170 filas, 15 señales y Spearman con poblaciones explícitas; [resultados y procedencia](entrega4_google_comparacion.md). PR por revisar e integrar |
| José | Validación independiente y reproducción del análisis | `scripts/10_validate_analysis.py`, `scripts/11_run_analysis.py`, `scripts/run_full_analysis.sh`, `tests/test_validate_analysis.py`, [`entrega4_validacion.md`](entrega4_validacion.md), `outputs/validation/`, [`evidencia/validacion/`](evidencia/validacion/) | Completo sobre `main` con el PR #16: 47/47 verificaciones de las dos fuentes (conteos, áreas, filtros, asignación espacial, bordes, índices y planes); dos corridas completas con resultados idénticos y una que se detiene ante el error. El paso del comparador de Sebastián queda `skipped` hasta que su script llegue a `main` |
| Samuel | Mapas, visualizaciones e informe consolidado | `scripts/07_entrega4_analysis.py`, `08_entrega4_visualizations.py`, `09_entrega4_tables.py`, `run_entrega4_pipeline.sh`, [`entrega4_informe.tex`](entrega4_informe.tex), [`Entrega4_Analisis_Techos.pdf`](Entrega4_Analisis_Techos.pdf) | Borrador base de Microsoft en `main` con correcciones aplicadas; falta regenerar mapas con `municipalities.geojsonl`, agregar mapas/gráficos de Google y consolidar secciones de Sebastián y José antes del PDF final |

## Guía de continuación e integración por integrante

Esta sección resume los puntos exactos de acople desde `main` para evitar formatos incompatibles o trabajo duplicado.

### Para Miguel (revisión breve de alineación)

- `scripts/06_rooftop_stats.py` ahora importa `ROOFTOP_STATS_CSV_COLUMNS` (como `CSV_FIELDS`), `FILTER_ORDER` (como `REASONS`), `INCLUDED`, `filters_for`, `exclusion_reason` y `format_optional_bool` desde `scripts/entrega4_contracts.py` y agrega `contract` y `methodology` en cada nueva corrida del reporte JSON.
- Tus archivos versionados `outputs/rooftop_stats_ms.csv` y `outputs/rooftop_stats_ms_report.json` ya pasan todas las comprobaciones de `python scripts/entrega4_contracts.py --check` sin necesidad de recalcular Microsoft (los filtros no cambiaron).
- Si vuelves a ejecutar `06_rooftop_stats.py` o apoyas la corrida de Google donde esté MongoDB cargado, el formato de `google_low_coverage` en CSV ahora escribe `true`/`false` en minúsculas (en `ms` sigue vacío `""`).

### Para Sebastián (ejecución de Google y acople del comparador)

**Actualización 22 nov:** el acople y la comparación definitiva están terminados en su rama. Se reutilizó sin alterar bytes el CSV/reporte Google real de José recién publicado en `7564aa3`; no se atribuye esa ejecución a Sebastián. La comparación local conserva 170 municipios y explicita poblaciones de Spearman de 170, 164 y 155. La reproducción local parcial se conservó como antecedente separado. Véanse [su documentación](entrega4_google_comparacion.md) y `secciones/google_comparacion.tex`. Los pasos siguientes describen cómo reproducir el flujo en una base completa.

1. Actualizar tu rama `feature/sebastian-environment` desde `main` (`git fetch origin && git rebase origin/main` o merge): aparecerán conflictos de texto en tres archivos (`README.md`, `config.yaml` y `docs/delivery4/README.md`). Conserva la sección `analysis` de `main` en `config.yaml` (ya incluye `analysis.comparison`, `analysis.methodology` y la regla del 20 %) y la estructura de `docs/delivery4/README.md` (actualizando solo el estado del tramo de Google/comparación); `scripts/06_rooftop_stats.py` y `scripts/entrega4_contracts.py` ya están en `main`.
2. Ejecutar el motor común sobre Google donde esté cargada `upme_pdet.buildings` (nunca crear un segundo motor de cálculo):
   ```bash
   python scripts/06_rooftop_stats.py --source google --passes 2
   python scripts/entrega4_contracts.py --check --require-google
   ```
   Esto escribe los 170 documentos de Google en `rooftop_stats` y genera `outputs/rooftop_stats_google.csv` y `outputs/rooftop_stats_google_report.json`.
3. Acoplar `scripts/06_compare_rooftop_stats.py` para leer directamente las salidas definitivas mediante `entrega4_contracts.load_rooftop_stats_export(csv_path, report_path, config, root)` (reemplazando el sobre provisional `entrega4-comparison-input-provisional-v1`).
4. Generar las tablas comparativas definitivas en `outputs/delivery4/` (diferencias absolutas, porcentajes, rankings por conteo y por área, correlaciones indicando exactamente qué municipios entran: 170, 165 o 155 no marcados, conservando los valores de los 15 municipios marcados y aclarando que la causa no está demostrada).
5. Correr pruebas (`python -m unittest discover -s tests -v`), actualizar `docs/delivery4/entrega4_google_comparacion.md` con los hallazgos reales y abrir PR a `main`.

### Para José (validación independiente y script maestro reproducible)

**Estado:** completo. Detalle y evidencia en [`entrega4_validacion.md`](entrega4_validacion.md). Los
pasos que siguen son los que se pidieron, y los cubre `bash scripts/run_full_analysis.sh`.

1. Partir de `main` y comprobar el estado de entrada en MongoDB:
   ```bash
   python scripts/04_load_buildings.py --source ms --verify-only
   python scripts/04_load_buildings.py --source google --verify-only
   ```
2. Contrastar los resultados de `rooftop_stats` (Microsoft y Google) con un cálculo independiente sobre `buildings`, verificando conteos, áreas, mediana exacta, municipios vacíos (`building_count = 0` -> `mean_area_m2 = null`, `median_area_m2 = null`) y coherencia de `filters` con `config.yaml`.
3. Verificar asignaciones espaciales por centroide (`$geoWithin` sobre `centroid_2dsphere`) y documentar si aparece alguna diferencia de borde entre el polígono planar de Shapely y la geometría esférica de MongoDB.
4. Revisar índices y planes de ejecución (`explain("executionStats")`) de `dataset_id_1_mpio_code_1` y `centroid_2dsphere`.
5. Preparar un comando o script maestro (con `set -euo pipefail`, deteniéndose ante cualquier error) que ejecute en orden: verificación de entradas -> `06_rooftop_stats.py --source ms --passes 2` -> `06_rooftop_stats.py --source google --passes 2` -> `entrega4_contracts.py --check --require-google` -> `06_compare_rooftop_stats.py` -> validación independiente -> `07`/`08`/`09`. Registrar tiempos, parámetros, versiones (Python, MongoDB, scripts) y procedencia (SHA256) en evidencias reales bajo `docs/delivery4/evidencia/`.

### Para Samuel (mapas completos, integración final y compilación del PDF)

Se aplicaron correcciones directas sobre los scripts `07`/`08`/`09` y el borrador `entrega4_informe.tex` en `main`:
- `07_entrega4_analysis.py`, `08_entrega4_visualizations.py` y `09_entrega4_tables.py` ahora leen `google_low_coverage` y metadatos desde `config.yaml` (sin listas fijas), corrigen los cuartiles exactos (`p50 = 865.919,23 m²`, `7.953,5` edificaciones), corrigen el error del gráfico de dispersión (Spearman real entre conteo y área de Microsoft es `0,959`, no el `0,904` del EDA entre fuentes), y eliminan las cifras estimadas de Google y menciones a "área aprovechable" o rangos porcentuales sin respaldo.
- `entrega4_informe.tex` y `Entrega4_Analisis_Techos.pdf` quedaron corregidos en tablas globales, Bottom 15 real, conteos por subregión (que suman 170), autoría del equipo y sección de metodología.

Pasos pendientes cuando Sebastián y José integren sus PRs en `main`:
1. Con `data/processed/municipalities.geojsonl` disponible, volver a correr `python scripts/07_entrega4_analysis.py`, `python scripts/08_entrega4_visualizations.py` y `python scripts/09_entrega4_tables.py` para regenerar los 3 mapas coropletos de Microsoft con los títulos actualizados y agregar mapas/gráficos de Google diferenciando visualmente **valores cero (`0`)**, **datos ausentes** y **los 15 municipios señalados como poco comparables**.
2. Incorporar en `docs/delivery4/entrega4_informe.tex` (leyendo cifras desde las salidas generadas, sin transcribir a mano):
   - Resumen de adquisición, integridad, eficiencia de carga y EDA de la Entrega 3 (45 puntos combinados de la rúbrica de la Semana 4).
   - Sección de metodología y contrato (`entrega4_metodologia_y_contrato.md`, ya integrada en base).
   - Resultados definitivos de Google y tablas/gráficos comparativos de Sebastián (`outputs/delivery4/`).
   - Evidencias reales de validación independiente, índices/planes y repetición de José.
3. Compilar y revisar el PDF final (`docs/delivery4/Entrega4_Analisis_Techos.pdf`) y verificar antes de entregar que no existan archivos o menciones ajenas al proyecto.

## Datos y herramientas disponibles

- MongoDB `upme_pdet`: `buildings` (1.761.030 `ms` + 2.694.775 `google`, cada una con
  `dataset_id`, `mpio_code`, `area_m2`, `centroid`) y `municipalities` (170 PDET).
- Índices: `dataset_id_1_mpio_code_1` para agrupar por fuente y municipio, y
  `centroid_2dsphere` para consultas espaciales.
- Validación rápida del contrato compartido y salidas versionadas:
  ```bash
  python scripts/entrega4_contracts.py --check
  python -m unittest discover -s tests -p "test_entrega4_contracts.py" -v
  ```
- Antes de calcular sobre MongoDB, comprobar la base con
  `python scripts/04_load_buildings.py --source ms --verify-only` (y `--source google`).
