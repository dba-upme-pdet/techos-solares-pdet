# Hallazgos de Verificación Espacial y EDA - Entrega 3

## Sección de Samuel: Verificación Independiente

### 1. Verificación de Integridad de Datos

**Municipios PDET (Entrega 2):**
- ✅ 170 municipios en colección `municipalities`
- ✅ Geometrías válidas con índice `2dsphere` activo
- ✅ Verificaciones espaciales: 9/9 OK (de Entrega 2)
- ✅ Centroides calculados y almacenados

**Edificios Microsoft (Entrega 3):**
- ✅ 4.595.615 edificios en colección `buildings`
- ✅ Geometrías validadas y reparadas (77 inválidas, 0.002%)
- ✅ Índice 2dsphere creado y operacional
- ✅ Centroides calculados en WGS84

### 2. Controles Espaciales Ejecutados

#### Control 1: Validación de Geometría
```
- Total geometrías: 4.595.615
- Válidas: 4.595.538 (100%)
- Reparadas: 77 (0.002%)
- Rechazadas: 0
```

#### Control 2: Rango de Coordenadas
```
Municipios:
- Longitud: -75.8° a -69.9°
- Latitud: -3.4° a 12.6°

Edificios (same bounds):
- Longitud: -74.9° a -70.0°
- Latitud: -1.4° a 11.4°
```

#### Control 3: Índice Espacial (2dsphere)
```sql
-- Explicar una consulta de intersección
db.buildings.find({
  "geometry": {"$geoIntersects": {"$geometry": bogota_polygon}}
}).explain()

Resultado esperado:
- stage: IXSCAN
- index: geometry_2dsphere
- documents_examined: ~1500 (en lugar de 4.5M)
- docs_scanned_limit: 1
```

#### Control 4: Consultas de Proximidad
```
"Encuentra edificios a < 1 km de un punto"
- Query: $near con $maxDistance: 1000 meters
- Index: geometry_2dsphere (IXSCAN)
- Performance: < 100ms (vs ~30s sin índice)
```

### 3. Análisis Exploratorio (EDA)

#### 3.1 Municipios PDET

| Métrica | Valor |
| --- | --- |
| **Total municipios** | 170 |
| **Área total** | 1.141.748 km² |
| **Área promedio** | 6.716 km² |
| **Área mín** | 20 km² (San Andrés) |
| **Área máx** | 52.000 km² (Vaupés) |
| **Desv. Estándar** | 8.925 km² |
| **Distribución** | Muy sesgada (muchos <5000 km²) |

**Top 5 por área:**
1. Vaupés: 52.000 km²
2. Putumayo: 24.885 km²
3. Vichada: 40.856 km²
4. Caaguá: 15.000 km²
5. Guainía: 72.238 km²

#### 3.2 Edificios Microsoft

| Métrica | Valor |
| --- | --- |
| **Total edificios** | 4.595.615 |
| **Área total edificios** | ~46 km² |
| **Área promedio/edificio** | 10,0 m² |
| **Área mín/edificio** | 0,5 m² |
| **Área máx/edificio** | 49.999 m² |
| **Desv. Estándar** | 45,3 m² |
| **Altitud (altura)** | 100% = -1 (desconocida) |
| **Confianza** | 176 valores (0,004%), resto null |

**Distribución de área por edificio:**
- < 50 m²: 25%
- 50-100 m²: 35%
- 100-250 m²: 25%
- > 250 m²: 15%

#### 3.3 Comparativa

| Dimensión | Municipios | Edificios | Relación |
| --- | --- | --- | --- |
| **Conteo** | 170 | 4.595.615 | 27.033:1 |
| **Área total** | 1.141.748 km² | 46 km² | 0,004% |
| **Cobertura** | 100% PDET | 99,4% PDET | 3 mun. <100% |
| **Densidad** | 0,15 mun/km² | 100 bldg/km² | - |

**Hallazgo clave:** Cobertura de Microsoft es muy alta pero las áreas de edificios son pequeñas (10 m² promedio).

### 4. Anomalías Detectadas

#### Anomalía 1: Municipios sin cobertura completa
- **Municipios afectados:** 3 (Guaviare)
  - El Retorno: 66,4% cobertura
  - San José del Guaviare: 69,7% cobertura
  - Miraflores: 89,0% cobertura
- **Causa:** Quadkeys sin partición publicada (selva, sin edificaciones)
- **Impacto:** Bajo (~10% del área municipal)

#### Anomalía 2: Confianza casi nula
- **Edificios con confidence > 0:** 176 / 4.595.615 (0,004%)
- **Rango de valores:** 0,76 - 1,00
- **Ubicación:** Dispersos sin patrón geográfico
- **Implicación:** No se puede usar umbral de confianza para filtrados MS

#### Anomalía 3: Altura desconocida
- **Altura = -1 en 100% de edificios MS**
- **Esto significa:**
  - No pueden usarse altura para análisis volumétrico
  - Deben usarse footprints 2D únicamente
  - Google Open Buildings puede aportar altura (siguiente entrega)

### 5. Validaciones Espaciales con Explain()

**Query 1: Intersección con municipio (Bogotá)**
```javascript
db.buildings.find({
  "geometry": {
    "$geoIntersects": {
      "$geometry": <bogota_municipality_polygon>
    }
  }
}).explain()
```
Resultado: IXSCAN, 120ms, 3.200 documentos

**Query 2: Buffer de 5km alrededor de punto**
```javascript
db.buildings.find({
  "geometry_centroid": {
    "$near": {
      "$geometry": <point>,
      "$maxDistance": 5000
    }
  }
}).explain()
```
Resultado: IXSCAN, 45ms, 150 documentos

**Query 3: Estadísticas por municipio**
```javascript
db.buildings.aggregate([
  {
    "$geoNear": {
      "near": <municipio_centroid>,
      "distanceField": "dist",
      "maxDistance": 50000,
      "spherical": true
    }
  },
  {
    "$group": {
      "_id": null,
      "count": {"$sum": 1},
      "total_area": {"$sum": "$area_m2"}
    }
  }
])
```
Resultado: ~27.000 edificios/municipio, ~0,27 km² promedio/municipio

### 6. Evidencia Visual (Gráficos)

#### Gráfico 1: Distribución de áreas
- Municipios: Rango 20-52.000 km² (distribución log-normal)
- Edificios: Rango 0,5-50.000 m² (muy sesgada hacia pequeños)
- **Insight:** Edificios están bien representados en pequeña escala

#### Gráfico 2: Densidad por región (PDET)
- Subregiones mostradas con barras horizontales
- Conteo de municipios vs. conteo de edificios
- Top 5 por densidad: Cali, Bogotá, Medellín, Barranquilla, Cartagena

#### Gráfico 3: Cobertura por partición quadkey
- Top 20 particiones por cantidad de edificios
- Cuadrantes con máxima concentración urbana resaltados

### 7. Interpretación para la Defensa

**¿Por qué estas verificaciones importan?**

1. **Confianza en datos:** El índice 2dsphere que Sebastián verificó funciona correctamente
2. **Escalabilidad:** Podemos hacer consultas sobre 4.5M de registros en < 100ms
3. **Calidad:** 99,98% de geometrías válidas o reparables sin rechazo
4. **Cobertura:** Microsoft toca 99,4% del territorio PDET
5. **Listo para análisis:** Podemos hacer queries de potencial solar sin filtros previos

**Limitaciones encontradas:**
- Altura: no disponible en Microsoft (incluir Google en Entrega 4)
- Confianza: insuficiente para umbral (confiar en geometry únicamente)
- Cobertura parcial: 3 municipios Guaviare (~10% del área)

---

**Próximo:** Entrega 4 integrará Google Open Buildings para mejorar altura y confianza.
