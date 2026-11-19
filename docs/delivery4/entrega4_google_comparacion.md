# Estadísticas de Google y comparación municipal con Microsoft

Responsable: Sebastián Sánchez. Estado comprobado el 19 de noviembre de 2026.

## Alcance y estado de la ejecución

Se implementó `scripts/06_compare_rooftop_stats.py`: compara las salidas municipales
del motor común, valida su compatibilidad y exporta JSON y CSV para mapas e informe.
No lee `buildings`, no calcula otra vez conteos, áreas, medias o medianas, ni escribe
en MongoDB. La persistencia en `rooftop_stats` y la exportación por fuente pertenecen
al motor de Miguel; la metodología y el contrato final corresponden a Derek.

Después de `git fetch origin`, `origin/main` apuntaba a
`a86e3d2cff4ffc22de1813961dc9391946778063`. La única rama remota de la Entrega 4
era `origin/entrega4/hallazgo-fuente-base` (`692b234`), ya integrada en `main`.
Contiene la regla de comparabilidad, pero no el contrato final ni el motor de
estadísticas. `scripts/06_rooftop_stats.py`, mencionado en el README general,
todavía no existe. Tampoco hay exportaciones finales municipales de la Entrega 4.
Se actualizó la rama personal por avance rápido desde `origin/main`, sin incorporar
ramas ajenas pendientes ni modificar sus implementaciones.

La comprobación local de conexión con `MongoClient(...).admin.command("ping")`
terminó en `ServerSelectionTimeoutError`; Docker no tenía un daemon disponible.
Esto no demuestra que la base de otro integrante esté vacía. En este computador
existe `data/processed/municipalities.geojsonl`, pero no las particiones preparadas
de `buildings`. No se descargó, preparó ni cargó de nuevo ningún conjunto masivo.

**No se ejecutó el motor de Google y no hay comparación definitiva de la Entrega 4.**
La implementación de comparación queda comprobada con una interfaz provisional,
pendiente de acoplarla al formato final que publiquen Derek y Miguel. No se eligieron
filtros analíticos nuevos. `analysis.min_area_m2 = 20` y `min_confidence = 0.70`
siguen marcados como provisionales y el comparador no los aplica ni los presupone.

## Evidencias disponibles y su procedencia

| Evidencia | Qué permite afirmar |
| --- | --- |
| `outputs/eda/eda_buildings_summary.json` y reportes de preparación/carga de la Entrega 3 | Línea base histórica preparada/cargada: MS 1.761.030 y Google 2.694.775 registros; no son estadísticas con filtros de la Entrega 4 |
| `outputs/delivery4/google_comparability_reference.json` y `.csv` | Regeneración local de la señal histórica para los 170 municipios: 15 señalados, cinco con cero Google en esa referencia |
| `docs/delivery4/comparison_test_results.txt` | Ejecución actual de las pruebas del comparador y regresión del EDA, con datos sintéticos salvo la lectura de la referencia histórica |
| `outputs/delivery4/sebastian_execution_status.json` | Inventario de dependencias, revisión remota y ausencia de ejecución definitiva |

El JSON de referencia registra las rutas y SHA256 de las tres entradas utilizadas:
EDA, cruce PDET y Excel del curso. No se reemplazaron los reportes históricos.
Los CSV agregados de la Entrega 3 no permiten obtener medianas ni estadísticas
con nuevos filtros a partir de los edificios individuales. No se usan como
sustituto del motor común.

## Interfaz provisional con el motor común

El contrato de lectura se llama `entrega4-comparison-input-provisional-v1`.
**No es una metodología aprobada por Derek ni un formato ya publicado por Miguel.**
Permite probar la comparación mientras llegan esas dependencias. Cuando se publique
el contrato común, se adaptará esta lectura o un sobre de metadatos, conservando
las cifras exportadas por el motor; no se implementará un segundo cálculo.

Cada fuente entrega un JSON con:

| Campo | Requisito |
| --- | --- |
| `contract` | `entrega4-comparison-input-provisional-v1` |
| `status` | `complete` |
| `dataset_id` | `ms` o `google`, según el argumento utilizado |
| `evidence_kind` | `definitive` para una ejecución real completa o `synthetic` para pruebas; nunca EDA histórico |
| `methodology.id`, `.version` | Identificadores explícitos e iguales en ambas fuentes |
| `methodology.definition` | Objeto no vacío que documente área, asignación municipal, estadísticos y demás decisiones del escenario común |
| `methodology.filters_by_source` | Objeto con claves `ms` y `google`; filtros efectivos, incluida la política para confianza ausente y cualquier umbral acordado |
| `methodology.empty_statistics` | `zero` o `null`, explícito y común; el comparador no decide esta política por Derek |
| `filters` | Exactamente los filtros del escenario para la fuente de ese archivo |
| `provenance` | `computed_at` ISO 8601 con zona, `engine`, `engine_version`, `environment` e `input_references` con ruta y SHA256 |
| `municipalities` | Lista con exactamente los 170 códigos oficiales, únicos y sin municipios inesperados |

Cada fila municipal contiene `mpio_code` como texto DIVIPOLA de cinco caracteres,
`dataset_id`, `building_count`, `total_area_m2`, `mean_area_m2` y `median_area_m2`.
Se reutilizan los nombres de métricas de `rooftop_stats`; el identificador compuesto
de MongoDB se aplana en `mpio_code` y `dataset_id` para tablas. El comparador no cambia
el validador de `scripts/00_init_db.py`.

Un municipio sin registros después del filtro debe aparecer con conteo y área
total cero, y media/mediana según la política explícita. El esquema actual exige
media y mediana numéricas para persistir en MongoDB: una eventual política `null`
necesitará que Derek y Miguel resuelvan su representación en persistencia. Admitirla
en el comparador no modifica el esquema existente. Una fila ausente, una métrica
ausente o un conteo desconocido provocan error; nunca se completan con ceros.

Se rechazan fuentes equivocadas, códigos inválidos, duplicados, faltantes, métricas
negativas/no finitas, conteos no enteros, medias inconsistentes con total/conteo
(tolerancia absoluta de 0,02 m² o relativa de 10⁻⁶), medianas superiores al área
total y metadatos incompletos. Se exige igualdad del objeto de metodología completo
y de la versión del motor, pero **los filtros de MS y Google pueden diferir** si
así lo declara el mismo escenario por fuente. No se mezclan pruebas y ejecuciones
definitivas. Las referencias de entrada quedan registradas; verificar su integridad
en la base y ejecutar los filtros corresponde al motor y a la validación de José.

## Diferencias, ceros y posiciones

Microsoft es la fuente base del proyecto, no una verdad certificada. Google es la
fuente de contraste. No se suman ni promedian las fuentes para inferir edificios
únicos. El área de las huellas es una proyección horizontal; no equivale por sí
sola a área útil del techo ni a potencial energético.

Para conteo y área, con base `M` de Microsoft y contraste `G` de Google:

- Diferencia con signo: `G - M`. Positivo significa mayor valor en Google.
- Diferencia absoluta: `abs(G - M)`, sin dirección.
- Diferencia porcentual: `100 * (G - M) / M`, denominador Microsoft.
- Si `M = 0`, el porcentaje es `null`/celda vacía, incluso si `G = 0`;
  `*_pct_status = zero_ms_denominator`. La diferencia absoluta sigue definida
  cuando el municipio es comparable.
- Un cero explícito se conserva como `0`; `*_observation_status = no_observations`
  significa que esa ejecución no tiene observaciones tras filtrar, no que se haya
  demostrado ausencia de edificaciones físicas. Una entrada faltante es un error.

Las posiciones son descendentes por fuente y por métrica con ranking de competición:
`1, 1, 3`. Los empates son exactos sobre los valores exportados, sin redondeo adicional;
el DIVIPOLA ordena establemente las filas, sin romper los empates. Se incluyen los
170 municipios, los ceros y los señalados. Los rankings son descriptivos de cada
fuente, no una prueba de concordancia o exactitud. No se calculan correlaciones
de Spearman ni se copian las correlaciones históricas a otra población.

## Señal de discrepancia y regla de comparabilidad

Se mantiene exactamente la definición de `docs/delivery4/README.md`: sobre
`municipalities` de `outputs/eda/eda_buildings_summary.json`, marcar si
`google_buildings < 0.2 * ms_buildings`. El código usa el equivalente entero
`5 * google_buildings < ms_buildings`, sin problemas de redondeo en el umbral.
Exactamente el 20 % no se señala; una referencia MS igual a cero no activa la regla.

La referencia es la línea base de la Entrega 3, **sin filtros analíticos de la
Entrega 4**, pero con la selección PDET y limpieza de la preparación. No se aplica
silenciosamente la regla sobre los resultados finales filtrados. La marca se
recalcula en cada ejecución, nunca desde una lista fija de quince códigos.
`signal_basis = entrega3_eda_unfiltered` y los conteos `reference_*` permiten auditarla.

En la referencia vigente se reproducen 15 señales, de las cuales cinco tienen
conteo Google cero. La etiqueta es `google_insufficient_detections`: señala una
discrepancia de detecciones; no identifica su causa ni certifica cobertura real.
Para respetar la regla de no comparación del equipo, sus valores originales y
rankings se conservan, pero `comparison_eligible = false` y todas las diferencias
analíticas se exportan como `null`; el estado es `excluded_reference_signal`.
El valor observado nunca se sustituye por cero ni se elimina la fila.

## Comandos y archivos para Samuel

Desde la raíz del repositorio, sin MongoDB ni descargas:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_compare_rooftop_stats.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_eda_buildings.py' -v
.venv/bin/python scripts/06_compare_rooftop_stats.py --reference-only
```

Actualmente Samuel puede usar `outputs/delivery4/google_comparability_reference.csv`
para la capa de señales históricas, uniendo por `mpio_code`. **No debe representarla
como estadísticas finales de Google.** El JSON homónimo aporta regla y hashes.

Una vez disponibles las dos exportaciones reales con el contrato definitivo
adaptado a la interfaz de lectura:

```bash
.venv/bin/python scripts/06_compare_rooftop_stats.py \
  --microsoft RUTA_EXPORTACION_MS.json \
  --google RUTA_EXPORTACION_GOOGLE.json
```

Las rutas de las entradas son argumentos obligatorios. `analysis.comparison` en
`config.yaml` fija el cruce, la referencia EDA y la carpeta de salida;
`--output-dir` permite una carpeta aislada. Las rutas relativas se resuelven desde
la raíz del proyecto, también cuando el comando se invoca desde otro directorio.
Salida `0` significa validación/exportación exitosa del modo ejecutado; `1` indica
entrada inválida o inaccesible y `2` uso incorrecto. Un éxito `--reference-only`
no significa que se haya ejecutado el motor de estadísticas.

| Salida | Uso |
| --- | --- |
| `outputs/delivery4/rooftop_stats_comparison.csv` | Tabla municipal final para mapas; solo se crea con exportaciones `definitive` |
| `outputs/delivery4/rooftop_stats_comparison.json` | Tabla, metodología, convenciones, SHA256 de entradas y copias íntegras de ambas exportaciones |
| `synthetic_rooftop_stats_comparison.*` | Mismo formato para pruebas, separado de los nombres finales |

Los dos archivos finales **todavía no existen**, porque no se han recibido las
exportaciones del motor común. Los CSV se escriben en UTF-8, con booleanos
`true`/`false` y nulos vacíos; los ceros permanecen `0`. Al leerlos en pandas,
Samuel debe usar `dtype={"mpio_code": "string"}` para conservar ceros iniciales.
Debe consultar el JSON de la misma ejecución para filtros y procedencia y usar
`comparison_eligible` antes de mapear diferencias. `ms_*` y `google_*` conservan
las cuatro métricas originales; `reference_*` son exclusivamente históricas.
Los campos `*_rank_building_count` y `*_rank_total_area_m2` son posiciones por
fuente; `*_difference_google_minus_ms`, `*_absolute_difference` y
`*_pct_difference_over_ms` describen el contraste. No hay un total combinado.

Las entradas se validan antes de escribir y las pruebas verifican que un rechazo
conserva resultados previos. El programa rechaza salidas que sobrescriban entradas.
Los resultados sintéticos usan nombres separados; las pruebas escriben únicamente
en directorios temporales.

## Pruebas y cierre pendiente

Se ejecutaron **25 pruebas del comparador y 2 de regresión del EDA, todas aprobadas**.
Cubren unión por código e independencia del orden; universo de 170 municipios;
duplicados y faltantes; fuente, filtros, metodología, versión del motor y procedencia;
ceros, ausencias, nulos, porcentajes y negativos; empates; umbral estricto; cambio de
la referencia sin lista fija; formatos JSON/CSV, hashes y conservación de evidencias.
La prueba de referencia real solo lee archivos históricos; las demás observaciones
son sintéticas y no acreditan el cálculo municipal de la Entrega 4.

| Responsable | Pendiente exacto |
| --- | --- |
| Derek | Publicar metodología y contrato de salida: filtros efectivos por fuente, confianza desconocida, área de huella frente a aprovechable, media/mediana sin observaciones y compatibilidad con el esquema de persistencia |
| Miguel | Publicar motor común, CLI y exportación/persistencia; generar Microsoft con la metodología versionada y aportar acceso a una base cargada o resultados trazables |
| Sebastián | Adaptar la lectura al contrato publicado, ejecutar ese mismo motor para Google en una base disponible, comparar ambos escenarios y publicar las tablas/evidencias definitivas |
| José | Validar independientemente los resultados y filtros del motor común |
| Samuel | Mapas y consolidación del informe usando las tablas definitivas y la señal histórica documentada |

No se puede dar el comando exacto del cálculo de Google antes de que Miguel publique
su CLI: se revisarán sus argumentos y efectos con `--help` y su documentación antes
de ejecutar. No se inventa una interfaz del motor. La implementación provisional
de comparación está comprobada; la ejecución definitiva de Sebastián sigue pendiente
de esas dependencias y de una base accesible. El informe/PDF final y la entrega
del equipo no quedan acreditados por este avance.
