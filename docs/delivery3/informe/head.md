---
title: "Entrega 3: Carga e integración de huellas de edificaciones"
subtitle: "Proyecto final - Techos solares en municipios PDET para la UPME"
author: "Miguel Duarte · Samuel Emperador · José Medina · Sebastián Sánchez · Derek Sarmiento Loeber"
date: "Administración y Aplicaciones de Bases de Datos (4055), PUJ 2026-30 · 16 de noviembre de 2026"
lang: es
---

# 1. Resumen

Esta entrega carga en MongoDB 7 (colección `upme_pdet.buildings`) las huellas de edificaciones de dos fuentes abiertas: **Microsoft Global ML Building Footprints** y **Google Open Buildings v3**. Las huellas se recortan a los 170 municipios PDET que integró la Entrega 2 desde el MGN2025 del DANE. El flujo tiene cuatro tramos: descarga, preparación con un contrato común, carga idempotente con índices espaciales y verificación. El código vive en `scripts/` del repositorio `dba-upme-pdet/techos-solares-pdet`.

**Tabla 1. Resultado de las dos cargas**

| Indicador | Microsoft | Google |
| --- | ---: | ---: |
| Registros leídos de la fuente | 4 595 615 | 31 499 115 |
| Excluidos por caer fuera de los PDET | 2 834 537 | 28 804 201 |
| Reparados en la preparación | 29 | 0 |
| Rechazados en la preparación | 48 (división en MultiPolygon tras reparar) | 139 (MultiPolygon) |
| Cargados en `buildings` | 1 761 030 | 2 694 775 |
| Rechazados en la carga | 0 | 0 |
| Municipios PDET con edificaciones | 170 de 170 | 165 de 170 |
| Área geodésica cargada | 220 976 634 m² | 222 051 169 m² |
| Segunda pasada (idempotencia) | 0 insertadas, 0 actualizadas | 0 insertadas, 0 actualizadas |
| Tiempo de carga (dos pasadas) | 101,95 s | 153,29 s |
| Memoria máxima del proceso | ~320 MiB | ~256 MiB |
| Índices | `centroid_2dsphere`, `dataset_id_1_mpio_code_1` | los mismos |
| Consulta `$geoWithin` de prueba | `IXSCAN` sobre `centroid_2dsphere` | 2 983 de 2 983 dentro, `IXSCAN` |

Tras las dos cargas, `upme_pdet.buildings` tiene **4 455 805 documentos**.

# 2. Requisitos de la entrega y dónde se cumplen

El enunciado pide para la Entrega 3 los mismos requisitos de la Entrega 2, aplicados a las dos fuentes, más la eficiencia de carga y un EDA breve. La rúbrica de la semana 4 asigna esos pesos.

**Tabla 2. Cobertura de la rúbrica**

| Criterio (peso) | Dónde se demuestra |
| --- | --- |
| Data Acquisition & Verification (10) | Secciones 5 y 6: fuente, versión, particiones, manifiestos con SHA256, cobertura |
| Data Integrity & Format (10) | Sección 7: contrato `entrega3-buildings-v1`, reparaciones, rechazos, validador estricto de MongoDB |
| NoSQL Spatial Integration | Secciones 1 y 8: índice `2dsphere` y consulta `$geoWithin` con `IXSCAN` |
| Data Loading Efficiency (25) | Sección 3 y sección 8 |
| Brief EDA (10) | Sección 4 |

# 3. Eficiencia en la carga de grandes volúmenes

Google entrega 31,5 millones de filas en 3,1 GB comprimidos, así que ninguna etapa puede cargar una fuente completa en memoria. El equipo usó estas técnicas:

1. **Selección previa de particiones.** Solo se descargan las particiones que tocan Colombia: 125 de Microsoft y 8 celdas S2 de Google. Así no se descarga el resto del mundo.
2. **Lectura en flujo.** La preparación y la carga leen cada GeoJSON Lines con gzip línea por línea. La memoria no crece con el tamaño del archivo: la carga usó como máximo ~320 MiB (Microsoft) y ~256 MiB (Google).
3. **Filtro espacial antes de la carga.** El centroide de cada huella se asigna a su municipio PDET durante la preparación. Se descartan 2,8 millones de huellas de Microsoft y 28,8 millones de Google antes de escribir en la base.
4. **Escritura por lotes.** La carga usa `bulk_write` en lotes de 10 000 documentos, no una inserción por documento.
5. **`_id` determinista e idempotencia.** Cada documento tiene `_id = <dataset_id>:<blake2b-96(dataset_id + source_ref)>`. Si la carga se repite, escribe sobre los mismos documentos y no crea duplicados. La segunda pasada de cada fuente dejó 0 inserciones y 0 modificaciones.
6. **Índices pensados para la Entrega 4.** `centroid_2dsphere` responde consultas espaciales y `dataset_id_1_mpio_code_1` agrupa por fuente y municipio para el conteo y el área de techos.
7. **Compuerta de contrato.** La carga se niega a empezar si el reporte de preparación no está balanceado o si un SHA256 no coincide. Así nunca se carga un archivo incompleto.

# 4. Análisis exploratorio breve (EDA)

Los datos de esta sección salen de `outputs/buildings_ms_prepared_by_municipality.csv` y `outputs/buildings_google_prepared_by_municipality.csv`, que la preparación genera por municipio.

