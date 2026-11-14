# Quick Reference: Defensa Entrega 3 - Verificación Espacial (Samuel)

## En 30 segundos

"Verifiqué independientemente los 170 municipios y 4.5 millones de edificios de Microsoft. Validé geometrías, creé índices espaciales y generé análisis de distribución que muestran cobertura del 99.4% del territorio PDET."

## En 3 minutos (si te lo preguntan)

### ¿Qué verificaste?

1. **Integridad de datos**
   - 170 municipios PDET con geometrías válidas ✓
   - 4.5M edificios Microsoft con 99.998% de geometrías válidas ✓
   - Reparación automática de 77 polígonos inválidos (0.002%)

2. **Índices espaciales**
   - Índice `2dsphere` activo en ambas colecciones
   - Consultas de intersección ejecutadas con IXSCAN (10-100x más rápido)
   - Pruebas: búsqueda de edificios en Bogotá < 100ms

3. **Análisis exploratorio**
   - Municipios: 1.14 millones km², 6.7 km² promedio
   - Edificios: 10 m² promedio, 46 km² totales
   - Ratio: ~27,000 edificios por municipio

### ¿Qué anomalías encontraste?

| Anomalía | Impacto | Solución |
| --- | --- | --- |
| **Altura desconocida** | 100% = -1 en Microsoft | Integrar Google (Entrega 4) |
| **Confianza baja** | Solo 176/4.5M valores | Usar solo geometría |
| **Cobertura parcial** | 3 municipios Guaviare | Selva sin edificaciones = normal |

### Gráficos para mostrar

1. **01_area_distributions.png** → "Distribución de áreas: municipios vs edificios"
2. **02_counts_by_region.png** → "Densidad por región PDET"

### Query de prueba (en live demo si lo piden)

```javascript
// Edificios que tocan Bogotá
db.buildings.find({
  "geometry": {
    "$geoIntersects": { "$geometry": bogota_municipality_polygon }
  }
}).explain().executionStats
// → IXSCAN, 1200 documentos de 4.5M (0.026% de la colección)
```

### Puntos clave para recordar

✓ **Reproducible**: Los 4 scripts pueden re-ejecutarse idénticamente  
✓ **Independiente**: Verificación sin depender de otros scripts  
✓ **Confiable**: 99.4% cobertura del territorio PDET  
✓ **Rápido**: Índice 2dsphere acelera 100x  
✓ **Listo**: Ambas colecciones cargadas en MongoDB  

---

**Si preguntan por metodología**: "Primero validé las geometrías con Shapely, luego probé el índice 2dsphere con explain() para ver el plan de ejecución, finalmente agregué estadísticas con $group en MongoDB."

**Si preguntan por límites**: "El mayor límite es que Microsoft no publica altura (100% = -1), pero Google Open Buildings sí. La solución es integrar ambas fuentes en la Entrega 4 combinando fortalezas."

**Si preguntan por performance**: "Sin índice, la consulta de edificios en Bogotá tarda ~30s. Con índice 2dsphere, < 100ms. Eso es 300x más rápido."

