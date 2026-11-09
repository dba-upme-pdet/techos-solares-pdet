# Entrega 2: verificación de integración espacial — Sebastián Sánchez

**Estado vigente:** verificador implementado y evidencia definitiva publicada de **170/170 municipios y nueve controles aprobados** en `upme_pdet.municipalities`. La ejecución definitiva fue realizada **por Miguel, en su entorno**, el 9 de noviembre de 2026 a las 07:30 de Bogotá, e integrada mediante el PR #8 (`7d27eae`, incorporado a `main` en `cd1c057`). Esta revisión contrasta los reportes y el código; no repite la carga ni la consulta en el computador de Sebastián.

## Objetivo y alcance

`scripts/02_verify_spatial.py` verifica mediante lecturas la colección que produce el cargador de Miguel. Reutiliza el esquema de `00_init_db.py`, las constantes de `entrega2_contracts.py`, la configuración del proyecto y el Excel del curso. No escribe documentos, crea índices ni repara geometrías. La documentación anterior que describía la integración como bloqueada queda sustituida por los resultados definitivos siguientes; el resultado local anterior se conserva como antecedente separado.

## Qué comprueba y cómo

| Control | Implementación | Evidencia definitiva |
| --- | --- | --- |
| Conexión | `ping` de MongoDB; URI configurable con `MONGO_URI` | OK |
| Cantidad | Exactamente 170 documentos | 170/170 |
| DIVIPOLA | `_id` string de cinco dígitos ASCII, único; no corrige los identificadores almacenados | OK |
| Lista PDET | Normaliza con ceros a la izquierda únicamente los códigos del Excel configurado y compara los conjuntos completos | 0 faltantes, 0 sobrantes |
| Esquema y contrato | MongoDB evalúa el `$jsonSchema` compartido, incluido `loaded_at` fecha BSON; además revisa prefijo de departamento, subregión 1–16, nombres, área positiva finita y metadatos de origen | 0 errores |
| Geometría | Polygon/MultiPolygon no vacíos, profundidad correcta, posiciones 2D numéricas finitas, anillos cerrados con al menos cuatro posiciones y tres vértices distintos, topología válida y área positiva según Shapely | 170/170 válidas |
| Coordenadas e índice | La validación geométrica exige longitud/latitud WGS84 dentro de la ventana Colombia compartida y rechaza un CRS explícito alternativo; control independiente de índice `2dsphere` visible sobre `geometry` | `geometry_2dsphere` presente |
| Consulta | Punto interior del primer documento ordenado por `_id`; comparación exacta de resultados con las intersecciones de Shapely y control negativo `[0, 0]` | Positivo: `05031`; negativo: 0 |
| Ejecución del índice | `explain` con `executionStats`, sin `hint`; busca un `IXSCAN` espacial solo en `winningPlan`, exige ejecución exitosa, claves examinadas y `nReturned` coherente | `FETCH → IXSCAN`, 9 claves, 1 documento |

El reporte tiene nueve claves de control: `connection`, `count`, `divipola`, `official_codes`, `schema`, `geometry`, `index`, `query` y `explain`. Las coordenadas forman parte de `geometry`. El script diferencia `OK`, `FALLA` y `PENDIENTE`: una referencia ausente o una consulta no ejecutable impiden el éxito. Un índice en un plan rechazado no aprueba `explain`; tampoco basta con que exista en la colección.

## Pruebas automatizadas existentes

La suite de `tests/test_verify_spatial.py` contiene **23 pruebas: 11 unitarias y 12 de integración**, con subcasos adicionales. El [registro conservado](spatial_test_results.txt) muestra 23/23 aprobadas en una ejecución anterior con MongoDB 7.0.45. **No se volvieron a ejecutar en esta revisión documental.** El [self-check local del cargador](loader_selfcheck_local_results.txt) conserva otro resultado histórico de 16/16; no es la carga definitiva.

La suite cubre 170 documentos sintéticos válidos, cantidades 0/169/171, códigos inválidos y conjuntos incorrectos con cantidad correcta, duplicados, esquema BSON, geometrías inválidas, Polygon con huecos y MultiPolygon, índice ausente con `COLLSCAN`, consultas positivas/negativas y con coincidencias múltiples, planes rechazados y códigos de salida. Dos casos de integración inyectan respuestas o planes incorrectos para comprobar su rechazo; los otros diez ejercitan directamente MongoDB. Cada prueba crea una base `spatial_verify_test_<UUID>` y limpia exclusivamente sus recursos. MongoDB es obligatorio: una conexión fallida no se omite como si la integración hubiera aprobado.

[spatial_synthetic_evidence.json](spatial_synthetic_evidence.json) conserva el ejemplo sintético con `FETCH → IXSCAN`, 7 claves examinadas y 1 documento devuelto. Sigue marcado como sintético; sus códigos y cuadrados no son datos del DANE y sus cifras no deben confundirse con las 9 claves de la consulta definitiva.

## Cadena definitiva de evidencias

Los siguientes reportes publicados por Miguel se revisaron sin modificarlos:

| Reporte | Resultado comprobado al leer el archivo |
| --- | --- |
| [Descarga](../../outputs/mgn_download_manifest.json) | `complete`, `fixture: false`, capa nacional de 1122 municipios, seis páginas con coincidencia `content`, `cache_matches_receipt: true` |
| [Validación](../../outputs/mgn_validation_report.json) | `valid`, 170 PDET cruzados; SHA256 de la capa igual al del manifiesto; 19/20 controles OK y un aviso informativo sobre nombres |
| [Preparación](../../outputs/municipalities_prepare_report.json) | `ready_for_load`, 170 líneas/documentos, sin faltantes ni duplicados, `claims_full_pdet_set: true` |
| [Carga](../../outputs/municipalities_load_report.json) | `loaded`, `input_matches_prepare_report: true`, 170 almacenados y sin cambios en la segunda corrida, cero rechazados/borrados, `prune: false`, nueve controles internos aprobados |
| [Verificación espacial definitiva](../../outputs/municipalities_spatial_verification_real.json) | `success: true`, nueve estados `OK`, colección `upme_pdet.municipalities`, consulta y plan ganador completos |

Preparación y carga registran el mismo SHA256 del GeoJSONL:

```text
612e2544be7ca2c22285aaac647819b910aa779ce61e1e5b872766051101f8ed
```

También se contrastaron los 170 códigos preparados con el Excel local, el SHA256 del Excel con la referencia del verificador y el SHA256 de la capa entre descarga y validación. La carga finalizada a las 07:30:25 y la verificación registrada a las 07:30:46 del 9 de noviembre corresponden al entorno de Miguel. El `success: true` y los nueve `OK` son coherentes con la salida 0 definida por la CLI y documentada en la sección de carga. Los nueve controles internos del cargador y los nueve del verificador independiente son comprobaciones distintas.

### Consulta y uso efectivo del índice

El punto representativo del primer municipio (`05031`, Amalfi) quedó registrado como:

```javascript
{
  geometry: {$geoIntersects: {$geometry: {
    type: "Point",
    coordinates: [-74.9514735167314, 7.020482489999999]
  }}}
}
```

El reporte devuelve `actual_ids = expected_ids = ["05031"]`. El control negativo utiliza el punto `[0.0, 0.0]`, fuera de la ventana Colombia, y registra **cero coincidencias**.

La consulta definitiva se explicó sin `hint`. El **plan ganador** contiene `FETCH → IXSCAN`, `indexName: geometry_2dsphere` y `keyPattern: {geometry: "2dsphere"}`. Las estadísticas registran `executionSuccess: true`, `nReturned: 1`, `totalKeysExamined: 9` y `totalDocsExamined: 1`. Esto acredita lectura efectiva del índice en esa ejecución, además de su existencia. Las 7 claves del ejemplo sintético no sustituyen las 9 del JSON definitivo; la sección de carga usa ahora la misma evidencia definitiva.

### Diferencia de hashes resuelta

El PR #8 separa el SHA256 binario del GML del `content_sha256`: este último omite únicamente el valor de `timeStamp` del elemento raíz, sin modificar el archivo fuente ni los demás bytes. El [recibo](../../outputs/mgn_wfs_source_receipt.json) conserva los hashes originales y los de contenido; el manifiesto registra los hashes observados y la coincidencia por contenido de las seis páginas. La documentación de descarga describe cómo se comprobó que restituir el atributo original reproduce los hashes del recibo. Aquí se revisaron esos registros y la implementación, sin recalcular los hashes de los GML ausentes localmente.

El `timeStamp` explica la variación del GML, no por sí solo la del JSONL anterior `b229d6a3…`. La sección de preparación documenta las diferencias de aquel producto: Polygon frente a MultiPolygon, `source.file` y finales de línea CRLF frente a LF. El flujo definitivo vuelve a pasar por el GeoPackage, conserva 170 MultiPolygon y escribe LF; recupera el hash `612e2544…` de la preparación original. El cargador ya declara coincidencia con el reporte. **La antigua excepción de hash no es un bloqueo vigente ni se necesita para esta evidencia definitiva.** No se utilizó ninguna excepción ni se modificaron datos durante esta revisión.

## Antecedente local de Sebastián: 0/170

[spatial_local_evidence.json](spatial_local_evidence.json) conserva la comprobación anterior de la base de Sebastián: 0 municipios, 170 códigos faltantes, 2/9 controles aprobados y `success: false`. En ese momento estaban disponibles la conexión y el índice, pero no la carga. Es un antecedente de otro entorno, **no el estado de la evidencia definitiva del equipo**. No se afirma que los 170 municipios se cargaron o verificaron en este Mac.

El archivo de `outputs/` que antes contenía esa comprobación fue actualizado por Miguel con el resultado definitivo; el antecedente local permanece en `docs/delivery2/`. Se conserva también la evidencia sintética separada. Esta revisión no ejecutó el script contra la base local ni sobrescribió ningún reporte.

## Ejecución y reproducción

Desde la raíz, con las dependencias existentes instaladas:

```bash
# Pruebas unitarias e integración en bases temporales; requiere MongoDB.
.venv/bin/python -m unittest discover -s tests -v

# Verificación de solo lectura, con un reporte nuevo para otra ejecución/entorno.
.venv/bin/python scripts/02_verify_spatial.py \
  --report outputs/municipalities_spatial_verification_local.json
echo $?
```

El reporte definitivo ya publicado se preserva en `municipalities_spatial_verification_real.json`; usar otro destino al repetir una comprobación local. Salidas: **0** si todos los controles aprueban, **1** ante fallos o pendientes y **2** ante un error operativo. La configuración, el Excel y los reportes relativos se resuelven desde la raíz del repositorio; `MONGO_URI` reemplaza la URI de `config.yaml`.

Para reproducir la cadena completa en otro computador se necesitan las páginas GML o una descarga que cumpla el recibo, la capa y el GeoJSONL con sus reportes correspondientes; los datos pesados están excluidos de Git. Seguir el flujo descarga → validación → preparación → carga → verificación del README, sin excepciones de hash ni eliminación de registros. Esa reproducción adicional no es una condición pendiente de la contribución documental de Sebastián ni invalida la ejecución definitiva publicada.

## Límites y cierre del informe

La estructura, topología y códigos se revisan en todos los documentos; la consulta geoespacial usa una muestra interior determinista y un control negativo. No demuestra el uso del índice para todos los puntos o planes posibles ni certifica que no existan huecos o solapamientos entre municipios. Shapely calcula en el plano y MongoDB sobre la esfera: resultados cercanos a fronteras pueden requerir análisis específico.

Los rangos de coordenadas no prueban por sí solos el CRS original, y la presencia de `source` no autentica la descarga; esa trazabilidad depende del flujo y sus recibos. Los reportes permiten comprobar su consistencia, pero sin los archivos de datos no se recalculan aquí sus hashes. No se leyó el ZIP original ni un `.prj`; el manifiesto mantiene `original_archive_crs_proven: false`. La ejecución presupone carga terminada y sin escrituras concurrentes, porque no utiliza una transacción de snapshot. El plan publicado corresponde a MongoDB 7.0.45 del entorno de Miguel, no a un clúster fragmentado.

Las cinco etapas del informe tienen contenido y evidencia. Descarga y preparación fueron redactadas por Miguel según sus comentarios de autoría; no consta una revisión de Derek y José y no se inventa esa aprobación. Esos comentarios no ocultan secciones vacías. La revisión editorial completa fue realizada por Sebastián. No quedan bloqueos técnicos de redacción o compilación: falta el envío del PDF a **BrightSpace** con su comprobante y la defensa que corresponda al curso. El repositorio no permite certificar aprobaciones individuales ni el cumplimiento administrativo de la participación de todos los integrantes.

### Revisión final del informe completo

Se revisaron el documento principal, sus cinco secciones, el modelo E–R reutilizado, la figura PDET, las tablas y referencias, el README y los documentos de cada etapa. Se consultó el enunciado y la rúbrica vigente `DBA_2630_FinalProject_RubricWeek2.pdf` (el nombre citado antes ya no es el vigente): plan de implementación 15, modelo/diccionario 20, adquisición y verificación 30, integridad/formato 20 e integración espacial 15. El informe resume el plan y el modelo de la Entrega 1, y presenta resultados en las cinco etapas; no se asigna una nota ni se supone una aprobación docente.

Se contrastaron programáticamente los reportes, el Excel y el CSV de cruce: 170 códigos únicos, 16 subregiones, hashes declarados consistentes, repetición de carga con 170 sin cambios y nueve controles espaciales OK. Se comprobaron el plan ganador y las estadísticas 9 claves/1 documento, más el control negativo de cero resultados. No se conectó a MongoDB ni se volvieron a ejecutar las pruebas históricas. Los reportes y las evidencias sintéticas/locales se preservaron byte por byte.

Se corrigieron la fecha/procedencia del reporte vigente de validación, las cifras del índice en carga, los límites de reproducción y la distinción entre evidencia narrativa de la primera carga y el JSON versionado de la segunda. Se resolvieron los desbordamientos con columnas ajustadas, rutas divisibles y mejor paginación; se corrigieron avisos de marcadores PDF y un título aislado. Se conservaron las autorías y los resultados válidos.

`latexmk -pdf -interaction=nonstopmode -halt-on-error entrega2.tex` genera el [PDF final](entrega2.pdf), de **15 páginas**. Se revisaron visualmente todas las páginas. El log final no registra errores, avisos de LaTeX, cajas desbordadas ni referencias indefinidas; el texto extraído no contiene marcadores visibles `Pendiente:` ni referencias `??`. El PDF corresponde a las fuentes publicadas. La publicación no demuestra el envío a BrightSpace: ese trámite queda explícitamente pendiente, y no se realizó desde esta sesión.
