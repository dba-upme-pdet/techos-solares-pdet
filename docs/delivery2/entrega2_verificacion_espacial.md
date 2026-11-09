# Entrega 2: verificación de integración espacial — Sebastián Sánchez

La implementación y las pruebas están terminadas. **La integración definitiva sigue pendiente: `upme_pdet.municipalities` contiene 0 documentos.** El índice existe, pero todavía no se puede acreditar una consulta sobre los 170 municipios reales. No se cargaron datos en la base del proyecto.

## Objetivo y alcance

Verificar, mediante lecturas reproducibles, la colección que entregue el responsable de carga. Se revisaron `config.yaml`, `00_init_db.py`, `entrega2_contracts.py`, los scripts de descarga, lista PDET y preparación disponibles, el diseño de la Entrega 1, los reportes y la documentación de la Entrega 2 y las pruebas previas. No se modificaron estas piezas compartidas. El 9 de noviembre se integraron desde `origin/main` la validación de Samuel y el cargador de Miguel (`c406b34`). Siguen ausentes los archivos de `data/` que menciona el reporte de preparación. Los resultados de carga publicados por Miguel corresponden a otro entorno; no demuestran una carga en este computador. El estado vigente se detalla en la revisión del 9 de noviembre al final de este documento.

Se consultó la [rúbrica oficial de la semana 2](https://github.com/aocalderon/PUJ/blob/main/2026-30/DBA/Project/resources/rubrics/DBA_FinalProject_Rubrics_Week2.pdf), descargada y leída durante esta revisión. Asigna adquisición y verificación 25 puntos, integridad y formato 20, integración espacial NoSQL 25, documentación 15, claridad 5 y defensa 10. Este aporte ofrece validaciones y evidencia para integración espacial, integridad y documentación; no acredita la adquisición, la carga pendiente ni la defensa del equipo.

## Validaciones implementadas

| Control | Criterio |
| --- | --- |
| Conexión | `ping` real; URI de `config.yaml`, reemplazable por `MONGO_URI` |
| Cantidad | Exactamente 170 documentos; colección vacía falla |
| Identificadores | `_id` string de cinco dígitos ASCII, único, sin normalizar los documentos almacenados |
| Referencia | Lee `resources/MunicipiosPDET.xlsx`, hoja y columna configuradas; normaliza solo la referencia con `zfill_digits` del contrato y exige 170 códigos únicos. Compara conjuntos completos y registra faltantes, sobrantes y SHA256 del Excel |
| Esquema | MongoDB evalúa el mismo `$jsonSchema` importado de `00_init_db.py`, incluidos campos requeridos, tipos BSON y `loaded_at` fecha; funciona aunque el validador de la colección se haya omitido o existan documentos antiguos |
| Contrato adicional | Prefijo de departamento, subregión entera 1–16, nombres no vacíos, área positiva y finita y metadatos `source.dataset/version/file` no vacíos |
| Geometría | Polygon/MultiPolygon no vacíos, profundidad correcta, posiciones 2D numéricas finitas sin booleanos, anillos cerrados explícitamente con al menos cuatro posiciones y tres vértices distintos, área positiva y topología válida según Shapely |
| Coordenadas | Límites WGS84 y ventana Colombia compartida (-82 a -66, -5 a 16), longitud/latitud; rechaza CRS explícito alternativo, ejes invertidos y coordenadas proyectadas |
| Índice | Índice visible `2dsphere` sobre `geometry`, independientemente de su nombre; los índices ocultos no cuentan |
| Consulta | Punto interior del primer documento ordenado por `_id`, obtenido con `representative_point()`; `$geoIntersects` debe devolver exactamente los identificadores que intersectan según Shapely, incluido el municipio de muestra. Control negativo `[0, 0]` debe devolver cero |
| Uso del índice | `explain` con `executionStats`, sin `hint`; únicamente el `winningPlan` debe contener `IXSCAN` del índice espacial, ejecución exitosa, más de cero claves examinadas y `nReturned` igual a los resultados de la consulta |

Hay nueve controles reportados. `OK`, `FALLA` y `PENDIENTE` se muestran por separado. Un archivo de referencia ausente deja el cruce pendiente; un archivo presente pero inválido falla. Si faltan documentos o hay geometrías/identificadores inválidos, consulta y explain quedan pendientes. Si solo falta el índice, se ejecuta la consulta para comprobar su comportamiento; un `COLLSCAN` no aprueba el uso del índice. Cero errores de esquema sobre una colección vacía tampoco se considera éxito.

El verificador no crea índices, colecciones ni documentos ni aplica reparaciones. Únicamente escribe un archivo local si se solicita `--report`.

## Ejecución reproducible

Desde la raíz del repositorio, con las dependencias existentes de `requirements.txt` y MongoDB disponibles:

```bash
# Si MongoDB aún no está levantado:
docker compose up -d mongodb

# Pruebas unitarias e integración real, sin dependencias nuevas:
.venv/bin/python -m unittest discover -s tests -v

# Regenerar también la evidencia sintética y el registro de pruebas:
SPATIAL_TEST_REPORT=docs/delivery2/spatial_synthetic_evidence.json \
  .venv/bin/python -m unittest discover -s tests -v \
  > docs/delivery2/spatial_test_results.txt 2>&1

# Verificar la colección del proyecto y guardar evidencia local:
.venv/bin/python scripts/02_verify_spatial.py \
  --report docs/delivery2/spatial_local_evidence.json
# Consultar inmediatamente el código de salida:
echo $?
```

`MONGO_URI` se puede definir en el entorno para usar las credenciales locales. El script resuelve configuración, Excel y la ruta relativa de `--report` desde la raíz del repositorio, incluso cuando se invoca desde otro directorio. No imprime la URI.

| Código de salida del verificador | Significado |
| --- | --- |
| 0 | Todos los controles aprobaron |
| 1 | Algún control falló o quedó pendiente |
| 2 | Error operativo, por ejemplo conexión o escritura del reporte |

Las pruebas exigen MongoDB: una conexión fallida hace fallar la suite; no se omite silenciosamente la integración.

## Pruebas ejecutadas y aislamiento

Corrida del **8 de noviembre de 2026, America/Bogota**, con Python 3.14.0, PyMongo 4.19.0, Shapely 2.2.0, pandas 3.1.0 y MongoDB **7.0.45**, imagen Compose `mongo:7.0`.

**23 pruebas, todas aprobadas**, salida 0; registro completo en [spatial_test_results.txt](spatial_test_results.txt). Son 11 pruebas unitarias y 12 de integración. Dos casos de integración inyectan deliberadamente resultados o planes incorrectos para verificar su rechazo; los otros diez verifican directamente el comportamiento de MongoDB. Varios métodos incluyen subcasos adicionales.

Se probaron 170 documentos sintéticos válidos; cantidades 0, 169 y 171; códigos incorrectos con cantidad correcta; identificadores cortos, alfabéticos, Unicode y numéricos; duplicados; campos ausentes, tipos BSON incorrectos, área NaN y metadatos incompletos; estructuras y topologías geométricas inválidas; Polygon con hueco y MultiPolygon; ausencia de índice con `COLLSCAN` real; resultados espaciales positivos, negativos, en huecos y en componentes separados; coincidencias múltiples; referencia ausente o inválida; planes clásicos y envoltura SBE; exclusión de planes rechazados; claves examinadas y códigos de salida CLI.

Cada prueba de integración crea una base `spatial_verify_test_<UUID>` que debe estar ausente antes de comenzar. Solo esa base recibe documentos, cambios de índices, casos inválidos y limpieza. `addCleanup` elimina la base propia incluso si falla una aserción. No se reutiliza la base fija que borraba la prueba anterior. Después de la suite se comprobó que no quedaron bases con ese prefijo. El índice de producción y las seis colecciones del proyecto no se modificaron.

Los códigos y cuadrados sintéticos son arbitrarios, están etiquetados `SYNTHETIC_TEST` y **no representan municipios ni geometrías oficiales**. En la prueba positiva se inyecta una referencia sintética explícita. Otra prueba contrasta esos mismos datos con el Excel real y confirma que el cruce falla aunque haya 170 documentos.

## Evidencia espacial e índice

[spatial_synthetic_evidence.json](spatial_synthetic_evidence.json) conserva el reporte generado por la prueba positiva contra MongoDB real, marcado `synthetic: true`, con nombre de base temporal, versión del servidor, consulta, identificadores esperados/obtenidos, plan ganador y estadísticas.

Consulta sintética reproducida por la suite:

```javascript
const query = {
  geometry: {$geoIntersects: {$geometry: {
    type: "Point", coordinates: [-74.995, 4.005]
  }}}
};
// Ejecutar solo en la base temporal mientras exista, no sobre municipios reales:
db.municipalities.find(query, {_id: 1});
db.municipalities.explain("executionStats").find(query);
```

La base temporal ya fue eliminada; la suite la reconstruye con otro UUID. En esta corrida devolvió únicamente `_id: "10000"`; el control `[0, 0]` devolvió cero. El plan ganador fue `FETCH → IXSCAN`, con `indexName: geometry_2dsphere`, `executionSuccess: true`, `nReturned: 1`, `totalKeysExamined: 7` y `totalDocsExamined: 1`. Son resultados sintéticos, no evidencia de la carga definitiva. Se verificó también que, al retirar únicamente el índice temporal, la consulta siguiera correcta y el explain con `COLLSCAN` fallara la validación.

## Estado local y pendientes (registro del 8 de noviembre)

[spatial_local_evidence.json](spatial_local_evidence.json) registra la corrida sobre `upme_pdet.municipalities`: conexión e índice aprobados, **0/170 documentos, 170 códigos faltantes**, controles de datos fallidos y consulta/explain pendientes. Resultado **2/9 OK, `success: false`, salida 1**. La invocación desde `/tmp` con rutas absolutas produjo el mismo resultado y código. También se ejecutó la CLI contra `127.0.0.1:1`: falló la conexión con salida 2.

Pendiente del equipo: disponer de los archivos reales preparados y ejecutar la carga de Miguel agregando `loaded_at` como fecha BSON, preservando `_id` y el índice del esquema. No se implementó ni se ejecutó esa carga dentro de esta responsabilidad.

**Cuando la carga esté disponible**, ejecutar desde la raíz:

```bash
.venv/bin/python scripts/02_verify_spatial.py \
  --report outputs/municipalities_spatial_verification_real.json
echo $?
```

Ese comando es de solo lectura sobre MongoDB. Para acreditar la integración real se requiere salida 0, los nueve controles `OK`, ausencia de faltantes y sobrantes y evidencia de consulta y plan ganador en el nuevo JSON. Si falla, resolver las causas reportadas con el responsable de carga y volver a ejecutar; no sustituir la evidencia pendiente por el reporte sintético.

## Límites de la verificación

La validez topológica y los rangos de coordenadas no prueban por sí mismos el CRS de origen ni que cada límite corresponda oficialmente al DANE; la trazabilidad de descarga y transformación depende del flujo del equipo. Se verifica la presencia de metadatos de origen, no su autenticidad. Tampoco se certifica que el contorno no haya sido alterado respecto de la fuente.

El control geoespacial usa una muestra interior determinista y un punto negativo, mientras que estructura, topología y códigos se comprueban sobre todos los documentos. Shapely evalúa intersecciones en el plano y MongoDB sobre la esfera; casos cercanos a fronteras pueden requerir análisis específico. No se certifica aquí una cobertura cartográfica completa sin huecos o solapamientos entre municipios. La ejecución debe hacerse después de terminar la carga, sin escrituras concurrentes, porque las lecturas no utilizan una transacción de snapshot. El plan documentado corresponde a MongoDB 7 local, no a un despliegue fragmentado.

## Revisión de cierre del 8 de noviembre de 2026

Después de `git fetch --prune origin`, `main` sigue en `2e7de83`; la rama personal contiene ese historial y todo el componente espacial. Se volvió a ejecutar la suite: **23/23 aprobadas**, salida 0 (registro actualizado en `spatial_test_results.txt`). No se encontraron errores que requirieran modificar el verificador ni añadir pruebas. Las bases temporales quedaron eliminadas.

Se volvió a ejecutar el verificador sobre la colección del proyecto: **0/170, 2/9 OK, salida 1**. El reporte actual está en [`../../outputs/municipalities_spatial_verification_real.json`](../../outputs/municipalities_spatial_verification_real.json); `spatial_local_evidence.json` contiene una copia idéntica. Es evidencia de una comprobación real fallida, no de 170 municipios cargados. La evidencia sintética anterior conserva su etiqueta y su significado.

### Bloqueos exactos y responsables

| Responsable | Trabajo disponible | Acción necesaria para cerrar |
| --- | --- | --- |
| Sebastián | Verificador, 23 pruebas, evidencias, guía y sección propia del informe terminados | Tras la carga, ejecutar la verificación definitiva, exigir nueve OK y actualizar el JSON y la sección con resultados reales. Este último paso sigue bloqueado; su responsabilidad completa aún no puede declararse cerrada |
| Derek | Descarga integrada en `main` por el [PR #5](https://github.com/dba-upme-pdet/techos-solares-pdet/pull/5) | Facilitar las páginas/capa verificadas si se necesita regenerar el producto y completar `secciones/descarga.tex`, que sigue como marcador en el borrador de Samuel |
| José | Preparación integrada; reporte `ready_for_load` con 170 documentos | Entregar `data/processed/municipalities.geojsonl` junto al reporte correspondiente y completar `secciones/preparacion.tex`. El archivo no existe en este checkout y está excluido de Git |
| Miguel | Esquema e índice disponibles; no se encontró cargador en ninguna rama remota inspeccionada | Publicar `scripts/02_load_municipalities.py`, documentar su uso y cargar el JSONL con `loaded_at` BSON sin borrar datos reales; comprobar repetibilidad y completar `secciones/carga.tex` |
| Samuel | Validación, reportes, mapa y borrador del informe en `origin/samuel/validate-mgn` (`aa20f5f`) | Revisar e integrar con el equipo el [PR #6](https://github.com/dba-upme-pdet/techos-solares-pdet/pull/6), abierto y sin integrar al momento de la revisión. Sus resultados son evidencia publicada por Samuel, no una nueva ejecución en este equipo |
| Equipo | Descarga/preparación en `main`; contribuciones de validación y verificación publicadas aparte | Revisar e integrar esas contribuciones y la carga en `main`, completar las secciones, compilar y revisar el PDF final, entregar el informe y preparar la defensa para el lunes 9 de noviembre. No se ejecutó ninguna integración ni publicación en `main` durante esta revisión |

El cargador y el JSONL faltan tanto en el árbol local como entre los archivos versionados de las ramas remotas inspeccionadas. También falta localmente `data/raw/mgn2025/wfs/municipio.gpkg`. Los archivos pesados no deberían incorporarse a Git para solucionar esto: se deben transferir los artefactos reales o reconstruirlos con el flujo del equipo. El reporte de preparación actual registra para el JSONL el SHA256 `612e2544be7ca2c22285aaac647819b910aa779ce61e1e5b872766051101f8ed`; una regeneración requiere su reporte propio y consistente. La observación de Samuel sobre cambios de `timeStamp` del WFS y hashes entre máquinas corresponde a Derek si se requiere descargar nuevamente; no se alteraron los controles de integridad ni los bytes fuente.

### Guía corta para la ejecución definitiva

1. Integrar mediante revisión del equipo los scripts publicados. Facilitar el JSONL real, verificar sus 170 líneas y su SHA256 contra el reporte de preparación de esa misma corrida. Si falta, Derek aporta la capa y José ejecuta la preparación; Samuel valida la capa. Los manifiestos deben describir los archivos realmente disponibles.
2. Miguel publica y ejecuta su procedimiento oficial de carga. El comando previsto en el README es `.venv/bin/python scripts/02_load_municipalities.py`; confirmar su interfaz cuando lo publique. No se proporciona un cargador alternativo ni se vacía la colección.
3. Con la carga finalizada y MongoDB disponible, Sebastián ejecuta:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/02_verify_spatial.py \
  --report outputs/municipalities_spatial_verification_real.json
echo $?
```

4. Con salida 0 y nueve `OK`, guardar la nueva evidencia, actualizar el estado y los números de `secciones/verificacion.tex` y llevar esos cambios a revisión en la misma rama personal. Si falla, conservar el resultado fallido y resolver su causa con el responsable; no acreditar la integración todavía.

Se completó [`secciones/verificacion.tex`](secciones/verificacion.tex), la sección asignada a Sebastián en el borrador de Samuel, con resultados sintéticos y pendientes reales explícitos. El resto del informe no se copió ni modificó en esta rama. Al integrar ambos aportes, Git puede presentar un conflicto de adición en ese archivo: conservar la sección completa de Sebastián en lugar del marcador vacío de Samuel. El equipo debe sustituir los demás marcadores y compilar desde `docs/delivery2/` con `latexmk -pdf entrega2.tex` después de integrar el documento principal.

La rúbrica ya está cubierta por este componente en validaciones, evidencia sintética reproducible, documentación y claridad del estado. El criterio de integración espacial real del equipo sigue sin acreditarse y la defensa debe realizarse; ninguna cantidad de pruebas sintéticas sustituye esos dos puntos.

Se comprobó la compatibilidad de la sección mediante `latexmk -pdf -interaction=nonstopmode -halt-on-error entrega2.tex` sobre una copia temporal del borrador `aa20f5f` de Samuel, reemplazando únicamente `secciones/verificacion.tex` por esta contribución: salida 0 y PDF generado. La copia y el PDF temporales se eliminaron al terminar; no constituyen el informe final entregado. No se modificaron los archivos de Samuel ni se incorporaron sus cambios a esta rama.

## Revisión vigente del 9 de noviembre de 2026

### Integración y comprobaciones locales

Se integró `origin/main` en `feature/sebastian-environment`, incluyendo `64f4418` (validación de Samuel) y `c406b34` (carga de Miguel). Se resolvió únicamente el conflicto de adición de `secciones/verificacion.tex`, conservando la versión completa de Sebastián. Las cuatro secciones restantes se compararon byte por byte con `origin/main`; no se modificaron. El documento principal ya incluye `\input{secciones/verificacion}`. No se creó otra rama ni se publicó en `main`.

El primer intento falló por conexión: Docker estaba detenido. Se inició Docker Desktop y el servicio Compose, se comprobó `ping` y MongoDB 7.0.45 y se repitieron las comprobaciones:

| Comprobación | Resultado observado en este computador |
| --- | --- |
| `python -m unittest discover -s tests -v` | 23/23 aprobadas, salida 0; `spatial_test_results.txt` actualizado |
| `python scripts/02_load_municipalities.py --self-check` | 16/16 OK, salida 0; [registro local](loader_selfcheck_local_results.txt). Solo usa datos sintéticos en su base temporal y la elimina; su caso interno de eliminación afecta exclusivamente esa base |
| Verificador contra `upme_pdet.municipalities` | 0/170, conexión e índice OK, 2/9 controles aprobados, consulta/explain pendientes, salida 1 |

El JSON actual está en `outputs/municipalities_spatial_verification_real.json`, con copia idéntica en `spatial_local_evidence.json`. No se modificó el reporte de carga de Miguel ni se ejecutó su carga real: no hay entrada local que cargar. No se utilizaron `--allow-input-mismatch` ni `--prune` en la colección del proyecto. El código y las pruebas del verificador no requirieron cambios.

### Qué evidencia corresponde a cada entorno

Miguel publicó `outputs/municipalities_load_report.json` con `status: loaded`, 170 documentos sin cambios en la segunda ejecución, cero rechazados y sus nueve controles internos de carga aprobados. Su documentación también declara 9/9 del verificador de Sebastián. Son resultados de **su computador**, no de este. Sus nueve controles internos son distintos de los nueve del verificador independiente. El repositorio no incluye el reporte JSON completo de esa ejecución independiente en su entorno; nuestra ruta homónima registra el resultado local fallido y no debe reemplazarse por una afirmación de éxito de otro equipo.

### Inconsistencia de hashes: conclusión y condición de reproducción

| Producto | SHA256 publicado |
| --- | --- |
| GeoJSONL del reporte de preparación original | `612e2544be7ca2c22285aaac647819b910aa779ce61e1e5b872766051101f8ed` |
| GeoJSONL que Miguel declara haber cargado | `b229d6a397442dd2239d882281ebc005cc4a90f50c0eeeb8d18b5d7910ccbe53` |

El reporte de Miguel declara explícitamente `input_matches_prepare_report: false`. Su documentación explica que reconstruyó el JSONL mediante funciones de descarga/preparación, omitiendo la comprobación del recibo, y cargó con `--allow-input-mismatch`.

La revisión del código permite separar dos asuntos:

- Un `timeStamp` distinto altera el hash binario de un GML. Samuel documenta que al restituir el atributo original recuperó el hash de una página. Esa es evidencia reportada por Samuel; aquí no están los pares de archivos para reproducirla ni generalizarla a las seis páginas.
- `parse_wfs_gml()` recoge únicamente campos mapeados, CRS y geometrías; `prepare_documents()` no incorpora el `timeStamp` de la respuesta al JSONL. Por tanto, **el cambio exclusivo de ese atributo no basta para justificar el hash diferente del JSONL**. Tampoco un hash diferente del GeoPackage por metadatos SQLite demuestra por sí solo cambios en los documentos exportados.
- Hay otra diferencia documentada que requiere conciliación: el flujo original declara los 170 municipios preparados como MultiPolygon; Miguel declara 168 Polygon y 2 MultiPolygon al reconstruir sin el mismo control de entrada. El parser actual devuelve Polygon si encuentra una sola parte, así que la representación puede influir en los bytes. No se certifica la causa exacta, equivalencia de geometrías ni alteración de límites sin comparar los archivos. También deben compararse `source.file`, atributos y serialización.

**Conclusión:** el reporte publicado acredita una carga funcional declarada por Miguel con una excepción de integridad registrada, pero no acredita reproducción exacta de la cadena original ni una carga local. No se justifica habilitar aquí `--allow-input-mismatch` sin disponer de los artefactos y conciliar las diferencias.

Para cerrar, Derek debe facilitar las seis respuestas GML originales y el recibo correspondiente, o documentar una nueva adquisición oficial con sus hashes reales revisada por el equipo. José debe facilitar el JSONL y el reporte de preparación de esa misma corrida. Miguel debe facilitar el JSONL exacto `b229d6a3…` y el reporte/manifiesto de su reconstrucción, y adjuntar el JSON completo de su verificador si se quiere conservar como evidencia independiente de su entorno. Si se pretende probar que solo cambió el `timeStamp`, comparar las seis parejas retirando únicamente ese atributo en copias, preservar los originales y registrar hashes de ambas versiones y procedimiento; no editar la fuente para aparentar una coincidencia. Después, comparar por DIVIPOLA los atributos y geometrías de ambos JSONL y explicar cualquier diferencia. Una nueva preparación válida puede producir su propio reporte consistente; no debe presentarse como reproducción binaria del producto original.

### Archivos y secciones que todavía bloquean la entrega

Faltan localmente:

- `data/processed/municipalities.geojsonl`.
- `data/raw/mgn2025/wfs/municipio.gpkg`.
- `data/raw/mgn2025/wfs/page_0000.gml`, `page_0200.gml`, `page_0400.gml`, `page_0600.gml`, `page_0800.gml` y `page_1000.gml`.

Son archivos excluidos de Git; obtenerlos de Derek/José/Miguel con los reportes y recibos que describan esos mismos bytes. Tener solo los reportes versionados no sustituye los datos.

Derek aún debe completar `docs/delivery2/secciones/descarga.tex` y José `docs/delivery2/secciones/preparacion.tex`: ambos siguen con `\pendiente{...}` en el `main` integrado. Samuel ya aportó su sección y Miguel la suya. La sección de Sebastián está integrada y actualizada con la procedencia de cada evidencia. No se completaron ni se atribuyeron resultados en nombre de otros integrantes. **No se genera un PDF definitivo mientras existan esos marcadores y siga sin conciliarse la trazabilidad.** Una compilación de borrador para comprobar sintaxis no acredita una entrega terminada.

Tras recibir una entrada trazable y confirmar su SHA256 contra el reporte de preparación, ejecutar sin excepciones de integridad ni borrado:

```bash
.venv/bin/python scripts/02_load_municipalities.py
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/02_verify_spatial.py \
  --report outputs/municipalities_spatial_verification_real.json
echo $?
```

Solo con salida 0 y nueve `OK`, actualizar la sección espacial con el resultado local exitoso. Después de que Derek y José completen sus secciones y el equipo concilie las fuentes, ejecutar desde `docs/delivery2/`:

```bash
latexmk -pdf -interaction=nonstopmode -halt-on-error entrega2.tex
```

El equipo debe revisar el PDF, los marcadores y referencias, aprobar el PR de la rama personal e integrar en `main` mediante su revisión habitual. La integración del código puede revisarse separadamente del cierre de las evidencias reales; no se declara la entrega completa.

Se compiló una **copia temporal del borrador integrado** con `latexmk -pdf -interaction=nonstopmode -halt-on-error entrega2.tex`: salida 0, 10 páginas y dos marcadores `Pendiente:` correspondientes a Derek y José. Las referencias inicialmente indefinidas se resolvieron en la segunda pasada automática; no hubo avisos de referencias indefinidas en esa pasada final. Persisten cinco avisos de cajas demasiado anchas en el documento principal y la sección de carga, que el equipo debe revisar al maquetar la versión final. La sección espacial actualizada compiló sin errores. El PDF temporal no se publicó ni se presentó como definitivo y se eliminó al terminar la comprobación.
