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

### Decisión: Microsoft es la fuente base

Derek fijó esta regla el 16 nov 2026 a partir del EDA:

1. **El conteo y el área oficiales por municipio salen de Microsoft** (`dataset_id = "ms"`).
   Microsoft tiene huellas en los 170 municipios PDET. Google solo tiene huellas en 165.
2. **Google se reporta aparte, como contraste.** Nunca se suman las dos fuentes, porque detectan
   las mismas edificaciones con formas y tamaños distintos. Google tiene 53 % más edificaciones,
   pero el área total es casi igual (222,1 frente a 221,0 km²).
3. **En los 15 municipios de la tabla, Google tiene cobertura insuficiente.** En ellos Google tiene
   menos del 20 % de las edificaciones de Microsoft, y en 5 no tiene ninguna. En las tablas y los
   mapas de la Entrega 4, esos municipios llevan la marca de cobertura insuficiente de Google, y su
   valor de Google no se compara. La causa no está verificada.
4. En el resto, las fuentes coinciden: la correlación de Spearman por municipio es 0,904 en conteo
   y 0,938 en área. Por eso Google sirve para validar el orden de los municipios.

| Código | Municipio | Subregión PDET | Edif. Microsoft | Edif. Google |
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

Los mismos códigos, para usar en el código:

```python
GOOGLE_COBERTURA_INSUFICIENTE = {"05475", "05873", "19418", "27099", "27150", "27205", "27250", "27425", "27450", "27491", "27615", "27745", "52612", "52621", "73616"}
```

Si los datos cambian, la regla de origen es la misma: `google_buildings < 0.2 * ms_buildings`
sobre `municipalities` en `outputs/eda/eda_buildings_summary.json`.

### Preguntas abiertas para la metodología

- **Huellas muy grandes.** En Microsoft, el percentil 99 del área es 912 m² y el máximo 44.720 m².
  Son bodegas e instalaciones. Hay que decidir y justificar si cuentan como techo aprovechable,
  o si se usa un umbral mínimo o máximo de área.
- **Área aprovechable frente a área de huella.** La huella es la proyección del edificio. El
  informe debe decir si se aplica un factor de aprovechamiento y de dónde sale.

## Trabajo de la Entrega 4

| Tramo | Documento | Estado |
| --- | --- | --- |
| Motor común de estadísticas (`scripts/06_rooftop_stats.py --source ms\|google`) y resultados de Microsoft (Miguel) | [`entrega4_rooftop_stats.md`](entrega4_rooftop_stats.md) | Microsoft calculado y verificado: 170 municipios, 1.720.535 edificaciones, 220,27 km²; resultados en `outputs/rooftop_stats_ms.csv` |
| Validación independiente, resultados de Google y corrida completa (`scripts/10_validate_analysis.py`, `scripts/11_run_analysis.py`) (José) | [`entrega4_validacion.md`](entrega4_validacion.md) | 47/47 verificaciones en `OK`. Dos corridas completas con resultados idénticos y una corrida que se detiene ante el error. Google: 2.067.004 edificaciones, 203,75 km², en `outputs/rooftop_stats_google.csv` |

## Datos y herramientas disponibles

- MongoDB `upme_pdet`: `buildings` (1.761.030 `ms` + 2.694.775 `google`, cada una con
  `dataset_id`, `mpio_code`, `area_m2`, `centroid`) y `municipalities` (170 PDET).
- Índices: `dataset_id_1_mpio_code_1` para agrupar por fuente y municipio, y
  `centroid_2dsphere` para consultas espaciales.
- Antes de calcular, comprobar la base con
  `python scripts/04_load_buildings.py --source ms --verify-only` (y `--source google`).
