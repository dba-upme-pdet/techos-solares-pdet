# Entrega 2: verificación de integración espacial — Sebastián Sánchez

La implementación y las pruebas están terminadas. **La integración definitiva sigue pendiente: `upme_pdet.municipalities` contiene 0 documentos.** El índice existe, pero todavía no se puede acreditar una consulta sobre los 170 municipios reales. No se cargaron datos en la base del proyecto.

## Objetivo y alcance

Verificar, mediante lecturas reproducibles, la colección que entregue el responsable de carga. Se revisaron `config.yaml`, `00_init_db.py`, `entrega2_contracts.py`, los scripts de descarga, lista PDET y preparación disponibles, el diseño de la Entrega 1, los reportes y la documentación de la Entrega 2 y las pruebas previas. No se modificaron estas piezas compartidas. En este checkout no están `01_validate_mgn.py` ni `02_load_municipalities.py`, y tampoco están los archivos de `data/` que menciona el reporte de preparación. Ese reporte versionado declara 170 documentos preparados; no demuestra que estén cargados aquí.

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

## Estado local y pendientes

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
