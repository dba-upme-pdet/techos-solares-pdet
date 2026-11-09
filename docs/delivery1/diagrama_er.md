# Diagrama E-R (fuente editable)

Versión Mermaid de `diagrama_er.png`. GitHub la dibuja automáticamente.
En MongoDB, `id` corresponde al campo `_id` de cada colección.

6 entidades y 7 relaciones uno a muchos. La relación MUNICIPALITY-BUILDING es
espacial: `mpio_code` se llena con `$geoWithin` sobre el centroide en la fase 3,
no durante la carga. Si el centroide no cae en ningún municipio PDET, `mpio_code`
queda en `null`.

```mermaid
erDiagram
    PDET_SUBREGION ||--|{ MUNICIPALITY : agrupa
    MUNICIPALITY |o--o{ BUILDING : "contiene (centroide)"
    DATASET ||--o{ BUILDING : provee
    DATASET ||--o{ INGESTION_RUN : registra
    INGESTION_RUN ||--o{ BUILDING : inserta
    MUNICIPALITY ||--o{ ROOFTOP_STAT : resume
    DATASET ||--o{ ROOFTOP_STAT : mide

    PDET_SUBREGION {
        int id PK "1 a 16"
        string name
        int municipality_count
    }
    MUNICIPALITY {
        string id PK "DIVIPOLA 5 digitos"
        string name
        string dpto_code "2 digitos"
        string dpto_name
        int subregion_id FK
        string subregion_name
        double area_km2
        geojson geometry "2dsphere"
        object source
        date loaded_at
    }
    DATASET {
        string id PK "ms, google o mgn"
        string name
        string version
        string license
        string url
        date accessed_at
    }
    BUILDING {
        objectid id PK
        string dataset_id FK
        string source_ref
        geojson footprint
        geojson centroid "2dsphere"
        double area_m2
        double area_src_m2
        double confidence
        double height_m
        string mpio_code FK
        objectid run_id FK
    }
    ROOFTOP_STAT {
        object id PK "mpio_code + dataset_id"
        int building_count
        double total_area_m2
        double mean_area_m2
        double median_area_m2
        object filters
        date computed_at
    }
    INGESTION_RUN {
        objectid id PK
        string dataset_id FK
        string source_file
        int rows_read
        int rows_loaded
        int rows_rejected
        date started_at
        date finished_at
        string notes
    }
```
