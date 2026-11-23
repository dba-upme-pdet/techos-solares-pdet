# Google y comparación municipal definitiva — Entrega 4

Responsable: Juan Sebastián Sánchez Vásquez. Revisión: 22 nov 2026 (America/Bogota).

## Cierre y procedencia de las ejecuciones

El comparador está adaptado a `entrega4-rooftop-stats-v1` y
`entrega4-methodology-v1`. Se incorporaron con merges normales el contrato y motor
comunes (`4e94c48`) y la validación independiente publicada durante esta sesión
(`7564aa3`). Se conservaron las implementaciones, la configuración y las autorías.
No se creó otro motor de estadísticas.

**Google se reutilizó de la ejecución real de José**, archivada en
`docs/delivery4/evidencia/validacion/corrida2/reproduccion/rooftop_stats_google.csv`
y su reporte homónimo. Fue ejecutada el 22 nov en su computador (MongoDB
7.0.48; marca UTC 2026-11-23T03:22:15+00:00, que corresponde al 22 nov en Bogotá),
con `scripts/06_rooftop_stats.py --source google --passes 2`.
Se copiaron ambos archivos **sin modificar sus bytes** a las rutas comunes de
`outputs/`; no existían allí. Sus SHA256 y procedencia están en
`outputs/delivery4/google_execution_receipt.json`.
**Esa ejecución archivada y sus 170 documentos MongoDB corresponden a José.**
Posteriormente Sebastián completó una reproducción local independiente, documentada abajo,
sin reemplazar estas exportaciones originales.

Microsoft conserva el CSV/reporte de **Miguel del 19 nov**, sin sobrescribirlos ni
recalcularlos: 1.720.535 edificaciones y
220.266.587,30 m² de huella. Ambos resultados tienen metodología
y filtros compatibles. La validación de José documenta una diferencia de apenas
0,78 m² en el total Microsoft entre su entorno original y la reconstrucción de Miguel,
por redondeo de áreas individuales; se conservan los valores originales de Miguel,
sin ajustes para hacerlos coincidir. Este contraste declara ambos entornos.

**Sebastián ejecutó localmente la validación de los pares exportados y la comparación
definitiva**, sin usar su base parcial ni repetir la carga del equipo.
La validación independiente de José está publicada en `main` (47/47 controles);
no se sigue describiendo como pendiente. Su corrida maestra dejó el comparador
omitido porque este aún no estaba integrado; puede repetir ese paso tras el PR.

## Método y resultado real de Google

Se reutilizan el motor común de Miguel y la metodología de Derek, sin umbrales nuevos:

| Política | Microsoft | Google |
| --- | --- | --- |
| Área mínima de huella | ≥ 20 m² | ≥ 20 m² |
| Área máxima | Sin tope (`null`) | Sin tope (`null`) |
| Confianza | No aplica; no se imputa | ≥ 0,70; ausente excluida |
| Orden de exclusiones | Área mínima → máxima → confianza | Igual |
| Municipio vacío tras filtrar | Conteo/área cero, media/mediana `null` | Igual |
| Asignación municipal | Centroide WGS84; borde → menor DIVIPOLA | Igual |

El motor calcula suma con `math.fsum`, media y mediana exacta, preserva los 170
municipios y persiste por identificador compuesto fuente/municipio. El área es
la proyección horizontal geodésica de la huella: no equivale automáticamente a
área útil del techo ni a potencial energético. No se aplica factor de aprovechamiento.

| Métrica / control Google | Resultado del reporte de José |
| --- | ---: |
| Huellas PDET antes del filtro | 2.694.775 |
| Excluidas por área mínima | 368.619 |
| Excluidas por área máxima | 0 |
| Excluidas por confianza, después del área | 259.152 |
| Incluidas | **2.067.004** |
| Área total | **203.747.640,41 m²** (203,75 km²) |
| Municipios con resultado / con observaciones | 170 / 164 |
| Verificaciones del motor | 8/8 OK |
| Duración de dos pasadas | 11.07 s |

Municipios sin observaciones tras filtros: `05475`, `05873`, `27099`, `27450`, `27491`, `27745`.
Son ceros observados de esta ejecución, no ausencia física de edificios demostrada.
Son **seis**, frente a cinco en el EDA sin filtros; Sipí (`27745`) queda sin
observaciones tras el filtro. Media y mediana son nulas en esos seis municipios.
El balance es 2.067.004 incluidas + 627.771 excluidas
= 2.694.775 entradas PDET.

Las dos pasadas mantuvieron 170 documentos. En la segunda: `upserted = 0`,
`replaced = 170`, `same_values_as_previous = true`. El reporte acredita persistencia,
conteo independiente, filtros, nulos, balance y ausencia de duplicados en el entorno
**de José**, no en la base local de Sebastián.

## Comparación, porcentajes y rankings

El script lee cada CSV/reporte con
`load_rooftop_stats_export(csv_path, report_path, config, root)`. Añade comprobaciones
de vínculo entre CSV y reporte, SHA256, fuente y versión del dataset, versión del
motor, metodología explícita y fechas de las filas. Exige dos pasadas sin nuevas
inserciones y con los mismos valores. El reporte Microsoft histórico sin
`contract`/`methodology` se admite conforme al contrato compartido; sus filtros,
versión y esquema se validan. Un metadato explícito incompatible nunca se sustituye.

Para entradas definitivas se comprueba además que `buildings_in_source` y
`assigned_pdet` coincidan con el total de la preparación versionada y su versión.
**Una carga parcial no puede pasar como estadística definitiva** aunque sus
balances internos aparenten ser correctos.

Se unen los 170 DIVIPOLA como texto de cinco caracteres; duplicados, faltantes,
códigos inesperados, fuentes equivocadas y escenarios incompatibles son errores.
Se conservan todas las columnas originales como `ms_*` y `google_*` y las
exportaciones normalizadas completas en el JSON. No se suman ni promedian las
fuentes como edificios únicos.

Para conteo y área: resta con signo `Google − Microsoft`, diferencia absoluta
`abs(Google − Microsoft)` y porcentaje `100 × (Google − Microsoft) / Microsoft`.
Denominador cero produce porcentaje nulo, incluso en 0/0, y estado
`zero_ms_denominator`. Un dato ausente provoca error; no se rellena con cero.
Media/mediana nulas expresan falta de observaciones después del filtro.

Se conservan `ms_rank_total_area` y `google_rank_total_area` del motor (secuenciales,
desempate por DIVIPOLA) y se agregan rankings descendentes de competición `1,1,3`
por conteo y área: `*_rank_building_count`, `*_rank_total_area_m2`. Los empates son
exactos sobre las cifras exportadas y se incluyen ceros y señalados.

## Señal de comparabilidad y correlaciones definitivas

La marca canónica `google_low_coverage` se recalcula con la función compartida:
`5 * google_buildings < ms_buildings` sobre el EDA, y se contrasta con configuración
y CSV. Su base es `entrega3_eda_unfiltered`, sin filtros analíticos de la Entrega 4;
no se copia una lista fija ni se cambia silenciosamente la regla al escenario filtrado.

Se señalan 15 municipios: se conservan sus valores y rankings,
pero `comparison_eligible = false` y sus diferencias son nulas con estado
`excluded_reference_signal`. Hay 155 elegibles para diferencias.
La discrepancia no demuestra su causa ni cobertura real. Microsoft es la fuente
base del proyecto, no una verdad certificada.

Spearman se calculó **localmente sobre los CSV filtrados**, como correlación de
Pearson entre rangos con promedio de empates:

| Población | n conteo | ρ conteo | n área | ρ área |
| --- | ---: | ---: | ---: | ---: |
| `all_municipalities` | 170 | 0.911018 | 170 | 0.942908 |
| `comparable_positive_in_both` | 155 | 0.912019 | 155 | 0.941336 |
| `positive_in_both` | 164 | 0.901637 | 164 | 0.936947 |

`all_municipalities` incluye ceros y señalados; `positive_in_both` exige valores
positivos en ambas fuentes para la métrica e incluye señalados. Son sensibilidades
descriptivas. `comparable_positive_in_both` excluye además la señal histórica y es
el contraste principal. Los tamaños se calculan; no se presuponen 165 ni 155.
Cada población/métrica registra `included_codes`, `excluded_codes` y
`exclusion_reasons`. Con menos de dos observaciones o una entrada constante,
ρ es nulo y se explica el estado. Estas correlaciones no son las del EDA y no
prueban exactitud de ninguna fuente.

## Comandos ejecutados y reproducción

En esta sesión, después de incorporar `7564aa3`, se copiaron íntegros los dos
archivos Google desde la ruta archivada indicada arriba a `outputs/` y se ejecutó:

```bash
.venv/bin/python scripts/entrega4_contracts.py --check --require-google
.venv/bin/python scripts/06_compare_rooftop_stats.py
```

Ambos terminaron con salida 0. No necesitan MongoDB para validar/comparar las
exportaciones. Las entradas y sus SHA256, configuración y código están registrados
en el JSON de comparación y el recibo de ejecución Google.
Para generar una nueva corrida en una **base completa y validada**:

```bash
python scripts/06_rooftop_stats.py --source google --passes 2
python scripts/entrega4_contracts.py --check --require-google
python scripts/06_compare_rooftop_stats.py
```

El comparador acepta `--microsoft CSV --microsoft-report JSON --google CSV
--google-report JSON --output-dir CARPETA`; por defecto usa `config.yaml`.
Las rutas relativas parten de la raíz del proyecto. Salida 0: éxito del modo;
1: error de entrada/contrato; 2: uso inválido de CLI.
`--reference-only` solo genera `google_comparability_reference_current.*`, separado
del antecedente del 19 nov. Los sintéticos usan `synthetic_*` en temporales.

## Antecedente local: no es la ejecución definitiva

Antes de publicarse el avance de José se inició el contenedor local sin borrar
volúmenes. Se verificaron ocho originales y la capa PDET y se usaron los programas
oficiales mediante `scripts/06_reproduce_google_local.py`, con reportes aislados.
Se leyeron 31.499.115 filas: 139 rechazos, 28.804.201 fuera de PDET y 2.694.775
preparadas; los totales y los ocho SHA256 preparados coinciden con la Entrega 3.
Se cargaron 170 municipios y parte de Google. La última lectura de ese intento inicial conservada fue
**377599 edificios y 0 estadísticas**.
Los reinicios interrumpieron los intentos de carga, incluso tras reducir la caché
local a 0,256 GiB y ampliar la tolerancia de conexión a 30 s. La causa de los
reinicios no se certifica solo con esa observación. No se borró lo insertado.

Ese intento se conserva en `outputs/delivery4/google_local_reproduction.json`,
`reproduction/` y su log. **No se usó para los resultados definitivos** ni se
mezcla su entorno con el de José. No se modificaron los reportes históricos del
proyecto. Los originales y preparados pesados siguen ignorados por Git.
La comparación publicada conserva la ejecución de José como fuente. La posterior
reproducción local se completó sin sobrescribir los archivos publicados, como se describe a continuación.

## Reproducción local completada tras la autorización del usuario

El usuario autorizó detener temporalmente los servicios ajenos para liberar recursos.
Se registraron los **42 contenedores activos**, se conservaron MongoDB y su volumen
y se detuvieron los otros **41**, primero frontales, luego aplicaciones y finalmente
bases de datos/mensajería. No se eliminó ningún contenedor, imagen, volumen ni dato.
Un scheduler agotó los 120 s de cierre de `docker stop` y terminó con código 137;
el inventario registra ese caso, sin presentarlo como cierre voluntario correcto.

Los registros del kernel de Docker confirman **74 eventos `global_oom` retenidos**
y procesos terminados por falta de memoria. La VM disponía de unos 2,84 GiB.
El log de MongoDB no contenía mensajes fatales y su reinicio era no limpio.
Al restaurar los servicios se capturó el evento individual que confirma la causa:
`global_oom`, `task=mongod` y `Out of memory: Killed process 20885 (mongod)`
a las 04:03:39 UTC del 23 nov (23:03:39 del 22 nov en Bogotá).
El extracto y su ubicación están en `evidencia/local_recovery_mongod_oom_20261122.json`. Durante esta intervención, con los
otros servicios detenidos, el contador de reinicios de MongoDB permaneció **3 → 3**.

Se reanudó el cargador oficial sobre los archivos preparados existentes:

```bash
.venv/bin/python scripts/06_reproduce_google_local.py --resume-buildings
```

Reutilizó **377.599 registros sin cambios**, insertó los **2.317.176 restantes**,
no actualizó registros y terminó con **2.694.775 edificios Google** y los controles
del cargador aprobados. No se repitieron descargas ni preparación.
Después se llamó al motor común en una raíz de archivos aislada:

```python
from importlib import import_module
from pathlib import Path

stats = import_module("06_rooftop_stats")  # PYTHONPATH=scripts
stats.ROOT = Path("data/delivery4_google_reproduction").resolve()
assert stats.main(["--source", "google", "--passes", "2"]) == 0
```

Resultado **local de Sebastián**: 170 documentos Google en `rooftop_stats`,
2.067.004 edificios incluidos, 203.747.640,41 m² y **8/8 controles OK**.
Primera pasada: 170 inserciones; segunda: 170 reemplazos, **cero inserciones**,
`same_values_as_previous = true`. El contrato común también aprobó en esa raíz.
Todas las métricas y columnas de Google coinciden exactamente con la exportación
de José, excluyendo únicamente `computed_at`. La comparación publicada y los dos
archivos Google originales conservaron sus SHA256.

Se restauraron los **41 servicios detenidos**, iniciando primero datos/mensajería,
luego aplicaciones y frontales. La comprobación posterior encontró activos los
**42 contenedores originales**, sin iniciar ninguno que estuviera detenido antes.
Tras restaurar todos los servicios, MongoDB pasó de 3 a 4 reinicios por ese OOM.
El sondeo posterior a esa recuperación volvió a confirmar 170 municipios,
2.694.775 edificios Google y 170 estadísticas persistidas.
La reproducción había terminado correctamente con los otros servicios detenidos;
restaurarlos no corrige la capacidad insuficiente de la VM. No se cambiaron los
límites globales de Docker ni se volvieron a detener servicios sin necesidad.
El inventario completo y la restauración están guardados localmente en
`data/delivery4_google_reproduction/intervention/containers_before.json` y
`containers_after.json`. Sus nombres no se publican innecesariamente en GitHub.

La evidencia exportable está en `outputs/delivery4/local_verification/`:
CSV/reporte Google locales, reporte de carga y `recovery_and_restoration.json`.
Las rutas internas de esos reportes son relativas a la raíz aislada antes indicada.
Los logs y extractos del kernel están en `docs/delivery4/evidencia/local_recovery_*`.
El antecedente parcial sigue conservado; ya no describe el estado alcanzado.
Antes de repetir cálculos, conservar siempre las exportaciones vigentes: el motor
escribe en las rutas de su raíz de ejecución.

## Archivos para Samuel y José

| Archivo | Uso |
| --- | --- |
| `outputs/rooftop_stats_google.csv` y `_report.json` | Google real de José, copiado sin modificar bytes |
| `outputs/rooftop_stats_ms.csv` y `_report.json` | Microsoft real de Miguel, conservado |
| `outputs/delivery4/rooftop_stats_comparison.csv` | Tabla definitiva de 170 municipios para mapas y diferencias |
| `outputs/delivery4/rooftop_stats_comparison.json` | Tabla, filtros, convenciones, originales, poblaciones/códigos y hashes |
| `outputs/delivery4/google_execution_receipt.json` | Archivo/commit de origen, entorno y hashes de la copia Google |
| `docs/delivery4/secciones/google_comparacion.tex` | Sección con cifras reales lista para incorporar al informe |
| `docs/delivery4/evidencia/contract_google_20261122.txt` y `comparison_20261122.txt` | Comandos y resultados de esta sesión |

Samuel debe leer `mpio_code` como texto, por ejemplo
`pd.read_csv(..., dtype={"mpio_code": "string"})`, distinguir ceros, nulos y señalados,
y usar `comparison_eligible` al mapear diferencias. El JSON de la misma corrida
aporta filtros y procedencia. José ya publicó su validación independiente; puede
integrar este comparador al paso del script maestro que antes quedaba omitido.

## Pruebas y límites del cierre

Se completó la suite anterior de 126 pruebas: 125 aprobadas y una optativa omitida,
sin errores en la repetición final. Después se ejecutaron las 20 pruebas finales
del comparador, todas aprobadas, incluida la protección frente a cargas parciales.
Las integraciones usan bases temporales; los datos sintéticos solo verifican casos
límite. Además, tras incorporar el avance de José y las exportaciones reales, aprobaron **52 regresiones finales** de comparador, contrato, motor y validador independiente, sin omisiones (`evidencia/final_delivery4_regressions_20261122.txt`). Las incidencias iniciales de conexión y sus reintentos se conservaron.
La sección LaTeX se compila aisladamente; no se declara regenerado el PDF del grupo.

El alcance de implementación y comparación de Sebastián queda ejecutado con datos
reales y listo para revisión del PR. La persistencia Google local también quedó verificada posteriormente, con evidencia
separada de la corrida original de José. Faltan integrar el PR y que
Samuel incorpore tablas/sección, complete mapas Google y compile/revise el PDF
consolidado. El envío del equipo a BrightSpace sigue pendiente.
