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
4. En el EDA histórico, la correlación de Spearman por municipio es 0,904 en conteo
   y 0,938 en área sobre los **165 municipios con registros en ambas fuentes** (se excluyen
   los cinco con Google igual a cero; no se excluyen los otros diez señalados). Es una
   asociación de posiciones, no una certificación de exactitud ni una correlación calculada
   sobre resultados filtrados de la Entrega 4. Microsoft es la base del proyecto, no una
   verdad de referencia certificada; la discrepancia no demuestra su causa ni la cobertura real.

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

La tabla anterior describe la referencia histórica; la marca se **recalcula**, no se copia
como lista permanente de códigos. Para generar una tabla auditable de la señal:

```bash
.venv/bin/python scripts/06_compare_rooftop_stats.py --reference-only
```

Si los datos cambian, la regla de origen es la misma: `google_buildings < 0.2 * ms_buildings`
sobre `municipalities` en `outputs/eda/eda_buildings_summary.json`.
Se usa esa línea base sin filtros analíticos de la Entrega 4, no el escenario final.
Los valores observados se conservan aun cuando la marca excluya sus diferencias analíticas.

### Preguntas abiertas para la metodología

- **Huellas muy grandes.** En Microsoft, el percentil 99 del área es 912 m² y el máximo 44.720 m².
  Son bodegas e instalaciones. Hay que decidir y justificar si cuentan como techo aprovechable,
  o si se usa un umbral mínimo o máximo de área.
- **Área aprovechable frente a área de huella.** La huella es la proyección del edificio. El
  informe debe decir si se aplica un factor de aprovechamiento y de dónde sale.

## Datos y herramientas disponibles

- MongoDB `upme_pdet`: `buildings` (1.761.030 `ms` + 2.694.775 `google`, cada una con
  `dataset_id`, `mpio_code`, `area_m2`, `centroid`) y `municipalities` (170 PDET).
- Índices: `dataset_id_1_mpio_code_1` para agrupar por fuente y municipio, y
  `centroid_2dsphere` para consultas espaciales.
- Antes de calcular, comprobar la base con
  `python scripts/04_load_buildings.py --source ms --verify-only` (y `--source google`).
  Las cantidades anteriores son evidencia de la Entrega 3 en el entorno de la carga;
  no garantizan que otra instalación local tenga esos documentos.

## Avance de Sebastián: comparación y dependencia del cálculo común

El [módulo de comparación y su interfaz provisional](entrega4_google_comparacion.md)
están probados. Exporta tablas por DIVIPOLA, diferencias, porcentajes con denominador
Microsoft, rankings y señales recalculadas; conserva las observaciones originales.
La [tabla de señales históricas](../../outputs/delivery4/google_comparability_reference.csv)
está disponible para Samuel. No es una tabla final de estadísticas filtradas.

Al revisar `origin/main` en `a86e3d2` y las ramas remotas el 19 nov, no estaban
publicados el contrato final de Derek ni el motor común de Miguel. Tampoco había
exportaciones de la Entrega 4; la ejecución de Google y la comparación definitiva
siguen pendientes. No se fijaron umbrales nuevos ni se reconstruyeron estadísticas
filtradas con agregados de la Entrega 3. Las pruebas y la referencia histórica se
documentan separadas de las futuras evidencias definitivas.
