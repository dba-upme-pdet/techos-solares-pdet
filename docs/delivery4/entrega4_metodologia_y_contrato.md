# Entrega 4: metodología y contrato compartido

Responsable: Derek Sarmiento. Código del contrato: [`scripts/entrega4_contracts.py`](../../scripts/entrega4_contracts.py). Configuración compartida: [`config.yaml`](../../config.yaml) (sección `analysis`). Pruebas: [`tests/test_entrega4_contracts.py`](../../tests/test_entrega4_contracts.py). Evidencia de validación: [`evidencia/contract_validation.txt`](evidencia/contract_validation.txt).

Este documento fija el contrato común de salidas, los filtros definitivos, las decisiones metodológicas y la configuración compartida sobre los cuales operan el motor de cálculo (`scripts/06_rooftop_stats.py`), la comparación entre fuentes (`scripts/06_compare_rooftop_stats.py`), la validación independiente y los scripts de visualización e informe.

## 1. Contrato compartido de resultados (columnas, tipos, unidades y formato)

Todas las fuentes (`ms` y `google`) se procesan con el mismo motor (`scripts/06_rooftop_stats.py --source <fuente>`) y producen exactamente tres salidas verificables: documentos en la colección `rooftop_stats` de MongoDB, una tabla CSV municipal y un reporte JSON de ejecución.

### 1.1 Colección `rooftop_stats` en MongoDB

Un documento por municipio PDET y por fuente, con clave compuesta `_id = {mpio_code, dataset_id}` para garantizar idempotencia (`ReplaceOne(upsert=True)`) y evitar que las fuentes se sobrescriban entre sí. Siempre se escriben los **170 municipios PDET** de `municipalities`, incluso si alguno queda con cero edificaciones después de aplicar los filtros.

| Campo | Tipo BSON | Unidad / formato | Nulabilidad y regla |
| --- | --- | --- | --- |
| `_id` | `object` | `{mpio_code, dataset_id}` | Obligatorio; clave única por municipio y fuente |
| `mpio_code` | `string` | DIVIPOLA 5 dígitos (`^[0-9]{5}$`) | Obligatorio; conserva ceros a la izquierda |
| `dataset_id` | `string` | `"ms"` o `"google"` | Obligatorio; coincide con `datasets._id` |
| `name`, `dpto_code`, `dpto_name` | `string` | Nombre MGN2025 y código DANE de 2 dígitos | Obligatorios |
| `subregion_id`, `subregion_name` | `int`, `string` | Entero `1..16` y nombre de subregión PDET | Obligatorios |
| `building_count` | `int` / `long` | Edificaciones (`>= 0`) | Obligatorio; conteo posterior a filtros |
| `total_area_m2` | `double` | `m²` (huella geodésica WGS84, 2 decimales) | Obligatorio; `0.0` si `building_count = 0` |
| `mean_area_m2` | `double` o `null` | `m²` (2 decimales) | **`null` si y solo si `building_count = 0`** |
| `median_area_m2` | `double` o `null` | `m²` (mediana exacta en Python, 2 decimales) | **`null` si y solo si `building_count = 0`** |
| `buildings_before_filters` | `int` / `long` | Edificaciones (`>= 0`) | Obligatorio; huellas asignadas al municipio antes de filtrar |
| `excluded` | `object` | `{below_min_area, above_max_area, low_confidence}` | Obligatorio; enteros `>= 0` cuya suma más `building_count` iguala `buildings_before_filters` |
| `rank_total_area` | `int` | Posición `1..170` (`1` = mayor área total) | Obligatorio; desempate determinista por `mpio_code` ascendente |
| `filters` | `object` | `{min_area_m2, max_area_m2, min_confidence}` | Obligatorio; filtros efectivos aplicados en la corrida |
| `computed_at` | `date` | Marca temporal UTC | Obligatorio |
| `script_version` | `string` | Identificador de versión del motor | Obligatorio (`entrega4-rooftop-stats-v1`) |
| `google_low_coverage` | `bool` | Bandera de baja cobertura de Google | Solo en `dataset_id = "google"`; ausente en `ms` |

El validador `$jsonSchema` en `scripts/00_init_db.py` exige los campos base y acepta `null` en `mean_area_m2` y `median_area_m2` para representar municipios sin edificaciones tras los filtros sin confundir ausencia de observaciones con un promedio de `0 m²`.

La mediana se calcula de forma **exacta** en Python (`statistics.median`) sobre las áreas incluidas de cada municipio porque el operador `$median` de MongoDB 7 es aproximado. La suma usa `math.fsum` para reducir error acumulado de punto flotante y se redondea a 2 decimales al final.

### 1.2 Archivo CSV municipal (`outputs/rooftop_stats_{source}.csv`)

Codificación UTF-8, separador coma (`,`), fin de línea `\n`, 170 filas de datos ordenadas por `rank_total_area` ascendente (`1..170`, equivalentes a `-total_area_m2`, `mpio_code`).

| # | Columna | Tipo | Unidad / formato | Regla de vacíos |
| ---: | --- | --- | --- | --- |
| 1 | `rank_total_area` | `int` | Posición `1..170` | No nulo |
| 2 | `mpio_code` | `string` | DIVIPOLA 5 dígitos | No nulo |
| 3 | `name` | `string` | Nombre MGN2025 | No nulo |
| 4 | `dpto_code` | `string` | DANE 2 dígitos | No nulo |
| 5 | `dpto_name` | `string` | Departamento MGN2025 | No nulo |
| 6 | `subregion_id` | `int` | `1..16` | No nulo |
| 7 | `subregion_name` | `string` | Subregión PDET | No nulo |
| 8 | `dataset_id` | `string` | `ms` o `google` | No nulo |
| 9 | `building_count` | `int` | Edificaciones (`>= 0`) | No nulo (`0` si vacío) |
| 10 | `total_area_m2` | `float` | `m²` (2 decimales) | No nulo (`0.0` si vacío) |
| 11 | `mean_area_m2` | `float` | `m²` (2 decimales) | Vacío (`""`) solo si `building_count = 0` |
| 12 | `median_area_m2` | `float` | `m²` (2 decimales) | Vacío (`""`) solo si `building_count = 0` |
| 13 | `buildings_before_filters` | `int` | Edificaciones (`>= 0`) | No nulo |
| 14 | `excluded_below_min_area` | `int` | Edificaciones (`>= 0`) | No nulo |
| 15 | `excluded_above_max_area` | `int` | Edificaciones (`>= 0`) | No nulo (`0` si `max_area_m2 = null`) |
| 16 | `excluded_low_confidence` | `int` | Edificaciones (`>= 0`) | No nulo (`0` en `ms`) |
| 17 | `google_low_coverage` | `bool` | `true` / `false` | Vacío (`""`) en `ms`; obligatorio en `google` |
| 18 | `computed_at` | `string` | ISO-8601 UTC (`+00:00`) | No nulo |

Conversión para presentación en mapas y tablas: `km² = total_area_m2 / 1_000_000`. Las cifras base se almacenan siempre en `m²` para evitar pérdida de precisión en municipios pequeños.

### 1.3 Reporte JSON de corrida (`outputs/rooftop_stats_{source}_report.json`)

Cada corrida nueva del motor deja un reporte JSON con `role = "rooftop-stats-report"`, `contract = "entrega4-rooftop-stats-v1"`, `dataset_id`, metadatos de `datasets`, `filters`, `filter_order`, `methodology`, marca temporal UTC, duración, totales con balance verificado (`assigned_pdet = included + excluded.total`), lista `without_buildings`, `outputs.csv_sha256`, resultados de cada pasada (`--passes 2`) y las ocho verificaciones independientes (`verification.ok = true`). Los campos `contract` y `methodology` son opcionales para mantener compatibilidad hacia atrás con `outputs/rooftop_stats_ms_report.json` (corrida definitiva de Microsoft del 19 nov 2026, previa a la formalización de `entrega4_contracts.py`).

La función `load_rooftop_stats_export(csv_path, report_path, config, root)` en `scripts/entrega4_contracts.py` valida el reporte, el SHA256 del CSV, el esquema completo y los balances fila por fila antes de entregar los datos normalizados a la comparación entre fuentes o a la generación de tablas y mapas.

## 2. Filtros definitivos de área y confianza

Los filtros se fijan en `config.yaml` (`analysis.*`) a partir de los umbrales propuestos en la Entrega 1 y contrastados con las distribuciones medidas del EDA de la Entrega 3 (`outputs/eda/eda_buildings_summary.json`):

| Parámetro | Valor definitivo | Fuentes donde aplica | Regla de inclusión | Justificación medida |
| --- | --- | --- | --- | --- |
| `min_area_m2` | `20` (`20.0 m²`) | `ms` y `google` | `area_m2 >= 20.0` | En el EDA de la Entrega 3, Microsoft tiene `min = 9,69 m²` y `p01 = 17,62 m²`; Google tiene `min = 2,50 m²` y `p10 = 16,66 m²`. Por debajo de `20 m²` las huellas suelen corresponder a estructuras menores (como casetas o cobertizos) o artefactos de detección sin superficie práctica para arreglos fotovoltaicos (aunque ninguna fuente publica tipología constructiva). En Microsoft, este filtro excluye `40.495` huellas (`2,30 %` del conteo) y solo `0,71 km²` (`0,32 %` del área total, de `220,98` a `220,27 km²`), con un efecto municipal máximo de `5,23 %` de las huellas (`Dibulla`, `44090`; `1,18 %` de su área). |
| `max_area_m2` | `null` (sin tope) | Ninguna | Sin límite superior | Ver sección 4: las huellas grandes pueden corresponder a infraestructura de gran formato (bodegas o instalaciones) y no se descartan sin verificación catastral. |
| `min_confidence` | `0.70` | Solo `google` (`confidence_sources: ["google"]`) | `confidence >= 0.70` (y no `null`) | Google Open Buildings v3 publica probabilidad de detección en `[0, 1]`. El umbral `0,70` conserva detecciones de confianza media-alta y descarta detecciones débiles o sin puntaje (`null`). |

### Orden determinista de evaluación (`filter_order`)

Para que el conteo de excluidas por motivo sea aditivo y no cuente dos veces una misma huella, cada edificación se evalúa en el orden exacto:

1. `below_min_area`: `area_m2 < min_area_m2`
2. `above_max_area`: `max_area_m2 != null` y `area_m2 > max_area_m2`
3. `low_confidence`: solo si `dataset_id` pertenece a `confidence_sources`, y `confidence == null` o `confidence < min_confidence`
4. `included`: cumple todos los filtros aplicables

Tanto la expresión `$switch` en la agregación de MongoDB (`scripts/06_rooftop_stats.py`) como la referencia en Python (`entrega4_contracts.exclusion_reason`) aplican exactamente la misma secuencia y se contrastan en pruebas automáticas.

## 3. Tratamiento de la confianza ausente en Microsoft

En `outputs/buildings_ms_prepare_report.json` se midió que, de las `1.761.030` edificaciones PDET de Microsoft, **`1.761.020` (`99,9994 %`) tienen `confidence = null`** (originalmente `-1` o campo ausente en las particiones publicadas; solo `10` registros dentro de PDET y `176` en las 125 particiones completas traen un valor numérico).

Se evaluaron dos errores que deben evitarse:

- **No filtrar Microsoft por confianza:** exigir `confidence >= 0.70` (o rechazar `null`) eliminaría el `99,9994 %` del conjunto de datos base.
- **No imputar confianza sintética:** rellenar `null` con `1.0` u otro valor inventado alteraría los metadatos reales de la fuente.

**Regla definitiva:** en `buildings` se conserva `confidence = null` tal como fue preparado en la Entrega 3; en `config.yaml`, `confidence_sources` contiene únicamente `["google"]`. En consecuencia, para `ms` el filtro efectivo queda explícitamente registrado como `filters.min_confidence = null` y `excluded.low_confidence = 0` en todos los documentos de `rooftop_stats`, el CSV y el reporte JSON. En `google`, cualquier huella con `confidence = null` o `< 0.70` se clasifica en `excluded.low_confidence`.

## 4. Tratamiento de huellas grandes y valores atípicos

En el EDA de la Entrega 3 la distribución del área de huella presenta una cola derecha marcada en ambas fuentes:

| Fuente | Mín. (m²) | p10 (m²) | Mediana p50 (m²) | p90 (m²) | p99 (m²) | Máx. (m²) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Microsoft (`1.761.030` PDET sin filtros) | 9,69 | 28,84 | 76,92 | 229,47 | 911,97 | 44.720,44 |
| Google (`2.694.775` PDET sin filtros) | 2,50 | 16,66 | 57,83 | 159,90 | 444,91 | 20.829,74 |

**Decisión definitiva (`max_area_m2: null`, `outlier_policy: "retain_all_above_min_area"`):** se conservan todas las huellas geométricamente válidas con `area_m2 >= 20 m²`, sin recorte superior ni winsorización.

Justificación:

1. **Cautela ante falta de tipología y relevancia solar:** ninguna de las dos fuentes publica un atributo de uso del suelo ni tipo de edificación; sin embargo, las huellas superiores a `1.000 m²` pueden corresponder a cubiertas de gran formato (como bodegas, centros de acopio, infraestructura portuaria o edificaciones institucionales), plausibles en municipios con media elevada como Apartadó, Buenaventura, Florencia, Santa Marta y Valledupar. Aplicar un tope arbitrario sin verificación catastral o fotogramétrica podría subestimar el techo físico disponible.
2. **Control previo de anomalías geométricas:** las geometrías corruptas (autointersecciones complejas o polígonos degenerados) ya fueron tratadas en la Entrega 3 (`48` rechazadas como `repair_split_multipolygon` y `29` reparadas en Microsoft; `139` rechazadas por tipo no soportado en Google).
3. **Robustez estadística sin pérdida de información:** el contrato exige reportar **media y mediana exacta** por municipio. La diferencia entre ambas revela de inmediato la presencia de grandes estructuras sin eliminarlas; por ejemplo, en Apartadó (`05045`) la media es `347,86 m²` frente a una mediana de `97,00 m²`, mientras la mediana de las medianas municipales en los 170 PDET es `77,06 m²` frente a una media global de `128,02 m²` por edificación.
4. **Reproducibilidad ante análisis de sensibilidad:** `max_area_m2` permanece parametrizado en `config.yaml` (`null` por defecto), de modo que cualquier prueba de sensibilidad con un tope superior se ejecuta sin cambiar código y queda registrada en `filters`.

## 5. Asignación espacial por centroide y desempate en límites compartidos

La pertenencia municipal de cada edificación sigue una regla única compartida entre la Entrega 3 (`scripts/entrega3_contracts.py`, clase `PdetSelector`) y la Entrega 4:

1. **Criterio de asignación:** se calcula el centroide de cada polígono en EPSG:4326 (`shapely.centroid`, almacenado como GeoJSON `Point` lon/lat con 7 decimales, precisión aproximada de `1 cm`). Una edificación pertenece al territorio PDET si su centroide intersecta (cae en el interior o sobre el borde de) alguno de los 170 polígonos municipales oficiales del MGN2025 (`data/processed/municipalities.geojsonl`).
2. **Por qué centroide y no intersección de polígonos:** asignar por centroide garantiza una relación 1 a 1 entre edificación y municipio, evitando doble conteo de edificios cuyos techos cruzan un límite administrativo, y permite validar directamente contra el índice `2dsphere` (`buildings.centroid`) con `$geoWithin`.
3. **Desempate determinista en límites compartidos:** la Entrega 1 dejaba el empate en "el primer municipio procesado", lo cual dependía del orden de lectura. La regla definitiva asigna cualquier centroide sobre un límite compartido al municipio con el **código DIVIPOLA menor** (`min(mpio_code)`).
4. **Evidencia medida:** en las corridas completas de preparación de la Entrega 3 (`outputs/buildings_ms_prepare_report.json` y `outputs/buildings_google_prepare_report.json`), el contador `centroids_on_shared_boundary` fue **`0` en Microsoft** (`1.761.030` edificios) y **`0` en Google** (`2.694.775` edificios). Aunque no hubo empates reales, la regla garantiza determinismo en cualquier actualización futura.
5. **Eficiencia y matiz geométrico de borde:** `mpio_code` queda materializado en `buildings` desde la Entrega 3 y verificado en carga con `$geoWithin`; en la Entrega 4, `06_rooftop_stats.py` agrupa directamente por `{dataset_id, mpio_code}` aprovechando el índice `dataset_id_1_mpio_code_1`. Como limitación documentada, Shapely evalúa aristas de polígonos en coordenadas planares lon/lat mientras MongoDB `$geoWithin` sobre `2dsphere` usa arcos geodésicos en la esfera; un centroide a centímetros de un segmento limítrofe largo podría clasificarse distinto entre ambas geometrías, aspecto que revisa la validación independiente de José. Adicionalmente, en polígonos cóncavos el centroide puede quedar fuera de la huella, con impacto marginal a escala municipal.

## 6. Configuración compartida

Todas las decisiones metodológicas y rutas residen en [`config.yaml`](../../config.yaml) bajo `analysis`:

| Clave en `config.yaml` | Valor actual | Consumidores |
| --- | --- | --- |
| `analysis.methodology.*` | `id`, `version`, `base_source: "ms"`, `contrast_source: "google"`, `area_metric`, `usable_area_factor: null`, `spatial_assignment`, `empty_municipality_stats: "null"`, `missing_confidence_policy`, `outlier_policy` | `entrega4_contracts.py`, `06_rooftop_stats.py`, `07_entrega4_analysis.py`, comparación y reporte |
| `analysis.min_area_m2` | `20` | `06_rooftop_stats.py`, `entrega4_contracts.py` |
| `analysis.max_area_m2` | `null` | `06_rooftop_stats.py`, `entrega4_contracts.py` |
| `analysis.min_confidence` | `0.70` | `06_rooftop_stats.py`, `entrega4_contracts.py` |
| `analysis.confidence_sources` | `["google"]` | `06_rooftop_stats.py`, `entrega4_contracts.py` |
| `analysis.filter_order` | `["below_min_area", "above_max_area", "low_confidence"]` | `06_rooftop_stats.py`, `entrega4_contracts.py` |
| `analysis.google_low_coverage_rule` | `ratio_threshold: 0.20`, `basis: "entrega3_eda_unfiltered"`, `reference_eda` | `entrega4_contracts.py`, comparación |
| `analysis.google_low_coverage` | Lista de 15 códigos DIVIPOLA verificada contra el EDA | `06_rooftop_stats.py`, `07`/`08`/`09`, validación |
| `analysis.rooftop_stats.*` | `collection`, `csv`, `report` | `06_rooftop_stats.py`, `entrega4_contracts.py`, `07_entrega4_analysis.py` |
| `analysis.comparison.*` | `municipalities`, `reference_eda`, `output_dir` | `06_compare_rooftop_stats.py`, `entrega4_contracts.py` |

Ningún script debe fijar umbrales ni listas de códigos a mano: `python scripts/entrega4_contracts.py --check` falla si `config.yaml` diverge del EDA o si un archivo de salida incumple el contrato.

## 7. Justificación de Microsoft como fuente base y Google como contraste

A partir de los hallazgos medidos del EDA de la Entrega 3 (`outputs/eda/eda_buildings_summary.json`):

1. **Cobertura completa de los 170 municipios PDET:** Microsoft registra edificaciones en **170 de 170** municipios PDET (`1.761.030` sin filtros; `1.720.535` tras `area_m2 >= 20`). Google solo registra edificaciones en **165 de 170**: tiene `0` detecciones en Murindó (`05475`), Vigía del Fuerte (`05873`), Bojayá (`27099`), Medio San Juan (`27450`) y Nóvita (`27491`).
2. **Municipios con baja cobertura de Google (regla de comparabilidad):** con la regla exacta `5 * google_buildings < ms_buildings` (estrictamente `< 20 %` de las edificaciones de Microsoft sobre la línea base sin filtros del EDA), **15 municipios** (11 en Chocó, 2 en Pacífico y Frontera Nariñense, 1 en Pacífico Medio y 1 en Sur del Tolima) quedan marcados con `google_low_coverage = true`. Sus valores observados se **conservan** en las salidas de Google, pero no se usan para diferencias porcentuales ni conclusiones comparativas directas. **La causa de esta discrepancia no está demostrada** (puede obedecer a cobertura de imágenes, nubosidad o sensibilidad del detector, pero no se afirma como causa probada).
3. **Nunca sumar ambas fuentes:** las dos fuentes detectan las mismas estructuras físicas con diferente segmentación. En el EDA sin filtros, Google tiene `53 %` más polígonos (`2.694.775` frente a `1.761.030`) con huellas más pequeñas (mediana `57,83 m²` frente a `76,92 m²`), pero el área total es casi idéntica (`222,05 km²` frente a `220,98 km²`, razón `1,005`). Sumarlas duplicaría el parque edificado.
4. **Valor de Google como contraste independiente:** en el EDA histórico sobre los **165 municipios con `google > 0`** (excluye únicamente los 5 con cero en Google; mantiene los otros 10 señalados), la correlación de Spearman es `0,904` en conteo y `0,938` en área. Esto confirma una alta concordancia ordinal en el ranking municipal; en la Entrega 4, la comparación definitiva reporta correlaciones sobre resultados filtrados indicando explícitamente qué subconjunto de municipios entra (los 170 o los 155 sin marca de baja cobertura).
5. **Limitación propia de Microsoft declarada con transparencia:** Microsoft es la fuente base por cobertura municipal completa, no una verdad de terreno certificada. Según `outputs/ms_buildings_coverage.csv`, 167 municipios están cubiertos al `100 %` por particiones quadkey publicadas por Microsoft, mientras que tres municipios de Guaviare tienen cobertura parcial de particiones publicadas: El Retorno (`95025`, `66,4 %`), San José del Guaviare (`95001`, `69,7 %`) y Miraflores (`95200`, `89,0 %`). Esa limitación permanece visible en el informe.

## 8. Área de huella frente a área aprovechable para paneles solares

Las métricas `total_area_m2`, `mean_area_m2` y `median_area_m2` miden el **área geodésica de la huella de edificación** (`pyproj.Geod(ellps="WGS84")`), es decir, la proyección horizontal en planta del contorno del edificio sobre el elipsoide WGS84.

**Diferencia conceptual y política del proyecto:**

- El área de huella constituye un **límite superior** del techo físico, **no** el área aprovechable para instalar paneles fotovoltaicos.
- Estimar área aprovechable requiere variables que no existen en Microsoft Building Footprints ni en Google Open Buildings v3: pendiente e inclinación de la cubierta, orientación (azimut), sombreado por vegetación, relieve o edificios vecinos, capacidad estructural de la cubierta, obstáculos (tanques, tragaluces, ductos) y retiros técnicos de mantenimiento.
- **No se introduce ningún factor de aprovechamiento sin respaldo** (`analysis.methodology.usable_area_factor: null`). No se multiplican las áreas por porcentajes arbitrarios ni se reportan rangos porcentuales sin fuente técnica verificable. El resultado de la Entrega 4 entrega de forma limpia el área geodésica de huella por municipio para que la UPME o un estudio técnico posterior aplique factores de utilización calibrados por tipología constructiva y región.

## 9. Verificación y evidencia

Comandos reproducibles de validación del contrato y pruebas unitarias:

```bash
python scripts/entrega4_contracts.py --check
python -m unittest discover -s tests -p "test_entrega4_contracts.py" -v
python -m unittest discover -s tests -p "test_rooftop_stats.py" -v
```

Al ejecutarse sobre las salidas versionadas de Microsoft (`outputs/rooftop_stats_ms.csv` y `outputs/rooftop_stats_ms_report.json`), todas las comprobaciones de esquema, SHA256, orden de ranking, balance de filtros y consistencia con `config.yaml` y el EDA aprueban sin observaciones (`evidencia/contract_validation.txt`). Cuando Google quede ejecutado con el motor común, se valida con `--require-google`.
