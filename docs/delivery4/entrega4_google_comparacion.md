# Google y comparación municipal — Entrega 4

Responsable: Juan Sebastián Sánchez Vásquez. Revisión: 22 nov 2026 (America/Bogota).

## Estado comprobado

La implementación se adaptó al contrato definitivo `entrega4-rooftop-stats-v1`
y a la metodología `entrega4-methodology-v1`. `origin/main` (`4e94c48`) se
incorporó mediante merge normal; los conflictos se resolvieron conservando su
configuración y documentación de coordinación. **El contrato de Derek y el motor
de Miguel están disponibles; ya no son dependencias pendientes.** No se modificaron
sus implementaciones ni se creó otro motor de estadísticas.

La ejecución definitiva de Google **no está terminada**. MongoDB local estaba
detenido y vacío; se inició su contenedor y se verificaron los originales disponibles.
La preparación oficial se completó, pero MongoDB se reinició durante la carga y
los intentos de reanudación terminaron en `ServerSelectionTimeoutError` o
`AutoReconnect`. No se ejecutó el cálculo sobre esa carga parcial y no se generaron
CSV/reporte de estadísticas Google ni una comparación presentados como definitivos.

No se necesitan nuevas descargas. Los originales, los municipios y las ocho
particiones preparadas están disponibles localmente y verificados. El bloqueo
actual es **una instancia MongoDB estable para completar la carga/cálculo**, o
recibir el CSV y reporte Google completos de una instancia ya cargada del equipo.

## Ejecución real y conservación de evidencias

1. Se inició Docker Desktop y se comprobó el volumen existente del proyecto, sin
   borrar ni reinicializar datos. Antes de cargar había 0 municipios, 0 edificios
   y 0 estadísticas. Esa constatación se limita a este computador.
2. Se verificaron los SHA256 de los ocho CSV.gz originales y de
   `data/processed/municipalities.geojsonl` contra sus manifiestos/reportes.
3. Se ejecutó el preparador de Derek mediante el auxiliar
   `scripts/06_reproduce_google_local.py`, con cuatro procesos y selección PDET.
   Los reportes se aislaron en `data/delivery4_google_reproduction/outputs/`.
4. Resultado real: **31.499.115 filas leídas, 139 rechazadas, 28.804.201 excluidas
   fuera de PDET y 2.694.775 huellas preparadas**, sin duplicados, balance correcto.
   Los totales y los **ocho SHA256 de archivos preparados coinciden exactamente**
   con la evidencia de la Entrega 3. No se sustituyeron sus reportes históricos.
5. Se cargaron los **170 municipios**, con nueve controles del cargador aprobados,
   incluidos índice, consulta espacial y plan ganador. Se usó `prune=False` y no
   se permitió ninguna excepción de hash.
6. La carga oficial de José se interrumpió. Se reanudó idempotentemente desde los
   archivos ya preparados, sin repetir la preparación ni borrar lo insertado.
   El log acredita una pasada de `8e1` con 80.564 inserciones y otra con las mismas
   80.564 sin cambios, sin rechazos. **Esto no acredita la carga completa.**
7. Se observó recuperación de MongoDB tras reinicios no limpios. Se redujo solo
   la caché de esta instancia con una sobreescritura Compose local de 0,256 GiB,
   conservando su volumen, y se amplió a 30 s la tolerancia de conexión del auxiliar.
   Las interrupciones persistieron. No se certifica una causa de memoria únicamente
   a partir de esos reinicios. No se detuvieron contenedores de otros proyectos.

El estado de la carga parcial al último sondeo está en
`outputs/delivery4/google_local_reproduction.json`; no se debe usar como resultado
municipal definitivo. Los reportes locales copiados conservan su estado real:
`outputs/delivery4/reproduction/`. Sus rutas internas se interpretan respecto de
`data/delivery4_google_reproduction/`, la raíz aislada de ejecución.
El log completo está en `docs/delivery4/evidencia/google_local_reproduction_20261122.txt`.
Los archivos pesados permanecen en `data/`, ignorados por Git.

Microsoft **sí** tiene una exportación definitiva validada y reutilizable:
`outputs/rooftop_stats_ms.csv` y `outputs/rooftop_stats_ms_report.json`.
Corresponde a **Miguel, 19 nov 2026**, con 1.720.535 edificaciones y
220.266.587,30 m² de huella. Se validaron esquema, SHA256, filtros, balances y dos
pasadas; no se repitió su cálculo ni se atribuye esa ejecución a Sebastián.

## Método efectivo y lectura del contrato

El comparador llama directamente a
`load_rooftop_stats_export(csv_path, report_path, config, root)` para cada fuente.
El sobre provisional anterior dejó de ser una entrada aceptada. Se reutilizan
nombres, nulos y métricas del contrato; la persistencia y la exportación por fuente
siguen perteneciendo al motor común de Miguel.

La configuración definitiva de `main` se conserva:

| Política | Microsoft | Google |
| --- | --- | --- |
| Área mínima | `area_m2 >= 20` | `area_m2 >= 20` |
| Área máxima | Sin tope (`null`) | Sin tope (`null`) |
| Confianza | No se filtra ni se imputa | `confidence >= 0.70`; ausente excluida |
| Orden de exclusiones | Área mínima → máxima → confianza | Igual |
| Municipio vacío tras filtrar | Conteo/área cero; media y mediana `null` | Igual |
| Pertenencia municipal | Centroide WGS84; desempate por menor DIVIPOLA | Igual |

El área es la proyección horizontal geodésica de la huella; **no equivale
automáticamente a área útil del techo ni a potencial energético**. No hay factor
arbitrario de aprovechamiento. Suma, media y mediana exacta se obtienen exclusivamente
con el motor común, no a partir de agregados históricos del EDA.

Además de la validación compartida, el comparador comprueba:

- Que el CSV solicitado sea el declarado por su reporte y tenga su SHA256.
- Fuente, versión del dataset, versión del motor, metodología explícita cuando
  existe, filtros efectivos y fechas coherentes entre filas y reporte.
- Dos pasadas con los mismos valores, sin inserciones adicionales y con 170 resultados.
- **Integridad de la carga de entrada:** para una exportación definitiva,
  `buildings_in_source` y `assigned_pdet` deben coincidir con el total completo
  de la preparación versionada, y las versiones de los datasets deben corresponder.
  Así se rechazan estadísticas calculadas sobre una carga local parcial aunque
  sus balances internos aparentemente aprueben.

El reporte Microsoft anterior a la formalización no declara `contract`/`methodology`;
el lector compartido admite ese caso histórico. El comparador valida sus filtros,
versión y esquema actuales y conserva el reporte original. Si un reporte sí declara
una metodología o contrato incompatibles, se rechaza, sin sustituirlos por `config`.

## Comparación y rankings implementados

Se unen los **170 códigos DIVIPOLA como texto de cinco caracteres**, sin rellenar
faltantes con ceros. Se rechazan duplicados, municipios faltantes/inesperados,
fuentes equivocadas, balances rotos y escenarios incompatibles.
Todas las columnas originales se conservan con prefijos `ms_*` y `google_*`;
el JSON incluye las exportaciones normalizadas y sus reportes completos.
Las fuentes no se suman ni promedian como edificios únicos.

Para conteo y área total:

- Resta con signo: `Google - Microsoft`; positivo significa más en Google.
- Diferencia absoluta: `abs(Google - Microsoft)`.
- Porcentaje: `100 * (Google - Microsoft) / Microsoft`.
- Denominador Microsoft cero: porcentaje `null` (CSV vacío), incluido 0/0;
  `*_pct_status = zero_ms_denominator`. Un cero observado permanece como 0.
- Media/mediana nulas significan ausencia de observaciones después del filtro;
  una fila o métrica ausente es un error, no un cero.

Se conservan `ms_rank_total_area` y `google_rank_total_area` originales del motor:
posiciones secuenciales 1..170, desempate por DIVIPOLA. Se agregan rankings
**descendentes de competición**, con empates exactos `1,1,3`, por fuente y por
conteo/área (`*_rank_building_count`, `*_rank_total_area_m2`). Incluyen los ceros y
señalados; son descriptivos y no se confunden con el ranking secuencial del motor.

## Señal de baja comparabilidad y Spearman

La marca canónica `google_low_coverage` se recalcula con la función compartida
sobre el EDA, mediante `5 * google_buildings < ms_buildings`, y se contrasta con
la configuración y el CSV Google. Su base es `entrega3_eda_unfiltered`: selección
y limpieza PDET de la Entrega 3, **sin filtros analíticos de la Entrega 4**.
No se usa una lista fija en el comparador ni se cambia la regla al escenario filtrado.
La referencia vigente contiene 15 señales y cinco ceros Google.

Se conservan las observaciones de los señalados, sus exclusiones y rankings.
`comparison_eligible = false` excluye sus diferencias directas, exportadas como
nulos con estado `excluded_reference_signal`. La discrepancia no demuestra su
causa ni cobertura real. Microsoft es la fuente base del proyecto, no una verdad
certificada.

Spearman se calcula sobre los **resultados filtrados**, como correlación de Pearson
entre rangos con promedio en empates, para conteo y área por separado:

| Población | Inclusión | Interpretación |
| --- | --- | --- |
| `all_municipalities` | Todos, incluidos ceros y señalados | Sensibilidad descriptiva |
| `positive_in_both` | Valores positivos en ambas fuentes para esa métrica | Sensibilidad descriptiva; incluye señalados |
| `comparable_positive_in_both` | Pares positivos y sin señal histórica | Contraste principal |

Cada población registra `n`, `included_codes`, `excluded_codes` y
`exclusion_reasons`. Los tamaños no se presuponen iguales a 170/165/155.
Con menos de dos observaciones o entrada constante, ρ es nulo y se explica el
estado. **Todavía no hay coeficientes definitivos Google–Microsoft calculados.**
Los valores históricos 0,904 y 0,938 del EDA no se presentan como nuevos.
La correlación expresa asociación ordinal, no exactitud de una fuente.

## Comandos para terminar y traspaso mínimo

Con una base del equipo **ya cargada y verificada**:

```bash
python scripts/04_load_buildings.py --source google --verify-only
python scripts/06_rooftop_stats.py --source google --passes 2
python scripts/entrega4_contracts.py --check --require-google
python scripts/06_compare_rooftop_stats.py
```

La primera verificación puede actualizar el reporte de carga de quien la ejecute:
se debe conservar su copia histórica o usar una raíz de reproducción separada.
**No ejecutar el cálculo en esta base parcial** hasta completar la carga y verificar
2.694.775 registros Google y 170 municipios.

El mínimo a solicitar a Miguel o al integrante que tenga esa base es ejecutar
los dos comandos centrales y proporcionar íntegros:

- `outputs/rooftop_stats_google.csv`.
- `outputs/rooftop_stats_google_report.json`, con `status = computed`, ocho
  controles aprobados, balance, SHA256 del CSV y dos pasadas sin duplicados.

No hace falta transferir los originales de varios GB. Se conservará la atribución
de la ejecución al entorno que realmente la realice. Con esos dos archivos y
Microsoft ya versionado, la comparación no necesita MongoDB.

La recuperación local ejecutada, usando los scripts oficiales, fue:

```bash
.venv/bin/python scripts/06_reproduce_google_local.py
.venv/bin/python scripts/06_reproduce_google_local.py --load-prepared
.venv/bin/python scripts/06_reproduce_google_local.py --resume-buildings
```

El primer modo exige una base vacía. Los modos de reanudación reutilizan la
preparación; `--resume-buildings` exige que los municipios correspondan a esta
reproducción, que no haya otras fuentes ni estadísticas y no usa `prune`.
No se modifican los filtros ni validadores del cargador.
Se usó esta sobreescritura **local**, ignorada por Git:

```yaml
services:
  mongodb:
    command: ["mongod", "--auth", "--bind_ip_all", "--wiredTigerCacheSizeGB", "0.256"]
```

Ruta: `data/delivery4_google_reproduction/compose.low-memory.yaml`. Comando:
`docker compose -f docker-compose.yml -f data/delivery4_google_reproduction/compose.low-memory.yaml up -d --no-deps mongodb`.
Se conservó el volumen y `docker-compose.yml` del equipo quedó intacto.
La [documentación oficial de MongoDB](https://www.mongodb.com/docs/v7.0/reference/configuration-options/#mongodb-setting-storage.wiredTiger.engineConfig.cacheSizeGB)
explica el ajuste de caché frente a otros consumidores de memoria.

## Archivos para Samuel y José

| Archivo | Estado y uso |
| --- | --- |
| `scripts/06_compare_rooftop_stats.py` | Comparador adaptado, comprobado con contrato y motor reales |
| `outputs/delivery4/google_local_reproduction.json` y `reproduction/` | Evidencia real de preparación completa y carga local interrumpida; no estadísticas definitivas |
| `outputs/delivery4/google_comparability_reference.*` | Antecedente histórico del 19 nov, conservado |
| `outputs/delivery4/rooftop_stats_comparison.csv` y `.json` | **Aún no existen**; se producirán al disponer de Google completo y validado |
| `docs/delivery4/comparison_test_results.txt` | Suite completa: 126 pruebas, 125 aprobadas y una optativa omitida |
| `evidencia/comparison_final_contract_tests_20261122.txt` | 20 pruebas de la versión final del comparador aprobadas |
| `docs/delivery4/secciones/google_comparacion.tex` | Sección preparada con estado real; resultados todavía pendientes |

Samuel deberá unir por `mpio_code` conservando ceros iniciales, por ejemplo con
`pd.read_csv(..., dtype={"mpio_code": "string"})`, y distinguir ceros, nulos y señalados.
El JSON acompañante registra filtros, poblaciones, convenciones y hashes de entradas,
configuración, comparador y contrato. Se preserva íntegra la exportación original.
José puede validar ambos pares CSV/reporte con el contrato y reproducir el contraste.
El comparador acepta rutas alternativas mediante `--microsoft CSV --microsoft-report
JSON --google CSV --google-report JSON --output-dir CARPETA`; por defecto usa `config`.
Salida 0: modo ejecutado correctamente; 1: error de entrada/contrato; 2: error de CLI.
`--reference-only` solo produce `google_comparability_reference_current.*` y no
acredita estadísticas finales. Las pruebas usan nombres `synthetic_*` en temporales.

## Pruebas y límites del cierre

Se ejecutó la suite completa: **125 aprobadas, una optativa omitida**, sin errores
en la repetición final. La omisión corresponde a `REAL_PREPARED_PART`, una inserción
opcional de partición real completa en una base temporal. Después se ejecutaron
las **20 pruebas del comparador final**, todas aprobadas, incluida la protección
contra entradas parciales. Los sintéticos no acreditan resultados reales de Google.

La primera suite tuvo incidencias de conexión durante el arranque; se conservan
en `evidencia/full_suite_initial_20261122.txt` y su reintento se documenta por separado.
Las integraciones usan bases temporales y no borran las colecciones del proyecto.
No se modificaron pruebas ajenas para esconder fallos.

La implementación de Sebastián está adaptada y probada. La ejecución definitiva
sigue abierta hasta disponer del par Google validado y producir el contraste real.
José conserva la validación independiente; Samuel, mapas, consolidación y revisión
del PDF completo. No se declara terminada la entrega del equipo ni enviada a BrightSpace.
