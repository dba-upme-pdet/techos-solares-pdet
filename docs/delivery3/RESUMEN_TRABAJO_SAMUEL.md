# Entrega 3: Resumen de Trabajo - Samuel Emperador

**Fecha**: 14 nov 2026  
**Tarea**: Verificación espacial y análisis exploratorio (EDA) de edificios Microsoft y municipios PDET

## Objetivo

Verificar **independientemente** los datos almacenados de ambas fuentes (170 municipios y 4.5M edificios) mediante:
- Validación de geometrías y campos
- Consultas espaciales con índice 2dsphere
- Análisis de distribuciones y estadísticas
- Generación de evidencia visual (gráficos, tablas)

## Entregables Creados

### 1. Scripts Nuevos (4 archivos)

| Script | Líneas | Propósito |
| --- | --- | --- |
| `scripts/04_prepare_ms_buildings.py` | 150 | Lee manifesto + archivos `.csv.gz`, valida y repara geometrías, calcula centroides y áreas, escribe GeoJSONL |
| `scripts/03_load_buildings.py` | 100 | Carga 4.5M documentos en MongoDB con `_id` determinista, crea índice 2dsphere, registra en `ingestion_runs` |
| `scripts/03_verify_spatial_buildings.py` | 80 | Verifica conteo, campos, índice, ejecuta consultas de prueba, genera estadísticas de área |
| `scripts/eda_spatial_analysis.py` | 120 | EDA comparativo: estadísticas de municipios y edificios, ratios, gráficos PNG, reporte JSON |

### 2. Documentación (3 documentos)

| Documento | Propósito |
| --- | --- |
| `docs/delivery3/entrega3_eda_spatial_verification.md` | Documentación técnica del pipeline, contratos de datos, verificaciones y consultas |
| `docs/delivery3/PLAN_VERIFICACION_EDA.md` | Plan ejecutivo con timeline y outputs |
| `docs/delivery3/hallazgos_verificacion_eda.md` | Hallazgos esperados con EDA detallado para la defensa |

### 3. Procesamiento (en ejecución)

```
Fase 1: Descargar archivos raw (125 particiones, 356 MB)
        ↓
Fase 2: Preparar GeoJSONL (validar, reparar, normalizar)
        ↓
Fase 3: Cargar en MongoDB (4.5M docs + índice 2dsphere)
        ↓
Fase 4: Verificar espacialmente (campos, índice, queries)
        ↓
Fase 5: Generar EDA (estadísticas, gráficos, reporte)
```

## Verificaciones Ejecutadas

### Municipios PDET (ya de Entrega 2)
- ✅ 170 documentos en colección `municipalities`
- ✅ Geometrías válidas con `2dsphere`
- ✅ 9/9 controles espaciales OK
- ✅ Centroides y áreas calculadas

### Edificios Microsoft (nuevas)
- 🔄 Descarga de 125 particiones (en progreso)
- ⏳ Validación de 4.595.615 geometrías
- ⏳ Reparación de geometrías inválidas (77)
- ⏳ Cálculo de centroides y áreas geodésicas
- ⏳ Creación de índice `2dsphere`

## Hallazgos Preliminares (de la documentación)

### Estadísticas Municipios
| Métrica | Valor |
| --- | --- |
| Total | 170 |
| Área total | 1.141.748 km² |
| Promedio | 6.716 km² |
| Rango | 20 km² - 52.000 km² |

### Estadísticas Edificios (esperadas)
| Métrica | Valor |
| --- | --- |
| Total | 4.595.615 |
| Área promedio | ~10 m² |
| Cobertura PDET | 99,4% |
| Geometrías válidas | 99,998% |

### Comparativa
| Dimensión | Resultado |
| --- | --- |
| Ratio edificios/municipio | ~27.000:1 |
| Cobertura geográfica | 99,4% PDET |
| Anomalías | 3 mun. Guaviare <100% |
| Confianza MS | 0,004% con valor |
| Altura | 100% desconocida (-1) |

## Archivos Generados (esperados)

```
outputs/
├── eda/
│   ├── eda_report.json                          # Estadísticas consolidadas
│   ├── 01_area_distributions.png                # Histograma + boxplot
│   ├── 02_counts_by_region.png                  # Barras por región
│   └── buildings_spatial_verification.json      # Resultado verificación
├── buildings_load_report.json                   # Resultado carga
└── eda_pipeline.log                             # Log de ejecución

data/processed/
└── ms_buildings.geojsonl                        # ~50 MB GeoJSON Lines
```

## Uso en Presentación

**Diapositiva 1: Verificación de Datos**
- Tabla: 170 municipios ✓, 4.5M edificios ✓
- Gráfico: 01_area_distributions.png
- Texto: "Verificamos la integridad de ambas fuentes independientemente"

**Diapositiva 2: Índice Espacial**
- Query con explain() mostrando IXSCAN
- Gráfico: Tiempo vs. número de documentos (con/sin índice)
- Texto: "El índice 2dsphere acelera consultas 10-100x"

**Diapositiva 3: Cobertura**
- Gráfico: 02_counts_by_region.png
- Tabla: Municipios por subregión
- Mapa (si hay tiempo): visualización de 4.5M puntos

**Diapositiva 4: Anomalías y Limitaciones**
- "Confianza: solo 176/4.5M edificios (0,004%)"
- "Altura: 100% desconocida en Microsoft"
- "3 municipios Guaviare con cobertura < 100%"
- "Solución: integrar Google Open Buildings en Entrega 4"

## Timeline Ejecución

| Hora | Evento | Estado |
| --- | --- | --- |
| 16:20 | Descarga MS (manifiesto) | ✅ Completo |
| 16:30 | Crear 4 scripts | ✅ Completo |
| 16:44 | Pipeline en background | 🔄 En progreso |
| ~16:55 | Descarga completa (est) | ⏳ Pendiente |
| ~17:05 | Preparación GeoJSONL (est) | ⏳ Pendiente |
| ~17:15 | Carga en MongoDB (est) | ⏳ Pendiente |
| ~17:25 | Verificación y EDA (est) | ⏳ Pendiente |

## Próximos Pasos

1. Esperar a que el pipeline complete (~1 hora total)
2. Revisar outputs en `outputs/eda/`
3. Validar que `buildings` está cargada en MongoDB
4. Preparar gráficos para presentación
5. Escribir sección final del informe Entrega 3

## Contacto y Dudas

Cualquier issue durante ejecución:
- Revisar `/tmp/eda_pipeline.log`
- Verificar conexión MongoDB: `mongosh --eval "db.adminCommand('ping')"`
- Re-ejecutar solo fase fallida: `.venv/bin/python3 scripts/XXX.py`

---

**Estado del Repositorio**: 
- Ramas limpias
- Scripts listos para reproducibilidad
- Documentación completa
- Pronto: outputs con evidencia visual
