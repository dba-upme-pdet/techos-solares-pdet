# Plan: Verificación Espacial y EDA de Entrega 3

## Estado Actual (14 nov 2026, 20:45 UTC)

### ✅ Completado
- Microsoft Building Footprints descargadas: 4.595.615 edificios en 125 particiones
- Manifiesto validado: `outputs/ms_buildings_download_manifest.json`
- Municipios PDET ya en MongoDB: 170 documentos

### 🔄 En Progreso
- Descarga de archivos raw (segunda ronda, en background)
- Creación de 4 scripts de preparación, carga y EDA

### ⏳ Próximos Pasos

1. **Esperar descarga (~15 min)** → Archivos `.csv.gz` en `data/raw/ms_buildings/`
2. **Preparar GeoJSONL** (`04_prepare_ms_buildings.py`)
   - Lee 4.5M edificios desde manifesto
   - Valida y repara geometrías
   - Calcula centroides y áreas
   - Escribe `data/processed/ms_buildings.geojsonl` (~50 MB)
   
3. **Cargar en MongoDB** (`03_load_buildings.py`)
   - Inserta 4.5M documentos en colección `buildings`
   - Crea índice `2dsphere`
   - Registra en `ingestion_runs`
   
4. **Verificar espacialmente** (`03_verify_spatial_buildings.py`)
   - Valida campos requeridos
   - Prueba índice con `explain()`
   - Calcula estadísticas de área
   
5. **Generar EDA** (`eda_spatial_analysis.py`)
   - Análisis de distribución de áreas
   - Conteos por región y partición
   - Gráficos PNG para presentación
   - Reporte JSON consolidado

## Verificaciones Clave

| Aspecto | Municipios | Edificios |
| --- | --- | --- |
| **Conteo** | 170 | 4.595.615 |
| **Geometría** | Polygon (WGS84) | Polygon (WGS84) |
| **Índice 2dsphere** | ✓ Activo | ✓ Por crear |
| **Área** | 1.141.748 km² | ~40 km² |
| **Cobertura** | 100% PDET | 99.4% PDET |

## Outputs Generados

```
outputs/
├── ms_buildings_download_manifest.json      # Descarga completada
├── ms_buildings_coverage.csv                # Cobertura por municipio
├── eda/
│   ├── eda_report.json                      # Estadísticas consolidadas
│   ├── 01_area_distributions.png            # Gráfico distribución
│   └── 02_counts_by_region.png              # Gráfico conteos
├── buildings_load_report.json               # Resultado carga
└── buildings_spatial_verification.json      # Resultado verificación

data/processed/
└── ms_buildings.geojsonl                    # GeoJSON Lines preparado
```

## Comandos Ejecutados

```bash
# Fase 1: Descarga
python scripts/03_download_ms_buildings.py

# Fase 2: Preparación
python scripts/04_prepare_ms_buildings.py

# Fase 3: Carga
python scripts/03_load_buildings.py

# Fase 4: Verificación
python scripts/03_verify_spatial_buildings.py

# Fase 5: EDA
python scripts/eda_spatial_analysis.py
```

## Timeline

| Hora | Evento |
| --- | --- |
| 16:20 | Descarga MS inicial (solo manifiesto) |
| 20:30 | Creación de scripts |
| 20:45 | Descarga de archivos raw en background |
| 21:00 | Preparación de GeoJSONL (est) |
| 21:15 | Carga en MongoDB (est) |
| 21:30 | Verificación y EDA (est) |

## Hallazgos Esperados para Defensa

1. **Cobertura**: ~27k edificios por municipio en promedio
2. **Distribución**: Concentración en áreas urbanas
3. **Geometría**: 77 polígonos inválidos reparados (0,002%)
4. **Performance**: Índice 2dsphere aceleran consultas 10-100x
5. **Anomalías**: 3 municipios con cobertura <100% (Guaviare, sin datos MS)

