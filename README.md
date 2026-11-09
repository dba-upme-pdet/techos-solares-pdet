# Potencial solar en techos de municipios PDET (UPME)

Administración de Bases de Datos · Pontificia Universidad Javeriana · 2026-30  
Prof. Andrés Oswaldo Calderón Romero, Ph.D.

Flujo de trabajo geoespacial reproducible que cuenta los techos de edificaciones y estima su área total en cada uno de los 170 municipios PDET de Colombia. Usa MongoDB como motor NoSQL y dos datasets abiertos de huellas de edificaciones: Microsoft Building Footprints y Google Open Buildings v3.

## Equipo

| Integrante | Usuario de GitHub |
| --- | --- |
| Derek Sarmiento | [@DereKk8](https://github.com/DereKk8) |
| José Medina | [@joseda1327](https://github.com/joseda1327) |
| Miguel Duarte | [@MiguelDu020](https://github.com/MiguelDu020) |
| Sebastián Sánchez Vásquez | [@tiansv](https://github.com/tiansv) |
| Samuel Emperador | [@emperador24](https://github.com/emperador24) |

Organización: [`dba-upme-pdet`](https://github.com/dba-upme-pdet) · Repositorio: <https://github.com/dba-upme-pdet/techos-solares-pdet>

## Entregas

| # | Entrega | Fecha | Carpeta | Estado |
| --- | --- | --- | --- | --- |
| 1 | Diseño del esquema NoSQL y plan de implementación | Lun 2 nov 2026 | [`docs/delivery1/`](docs/delivery1/) | Entregada |
| 2 | Integración de los límites de municipios PDET | Lun 9 nov 2026 | [`docs/delivery2/`](docs/delivery2/) | 170/170 municipios y verificación espacial 9/9 documentados en el entorno de Miguel; informe y entrega final por revisar |
| 3 | Carga e integración de huellas de edificaciones | Lun 16 nov 2026 | `docs/delivery3/` | Pendiente |
| 4 | Flujo reproducible de análisis geoespacial | Lun 23 nov 2026 | `docs/delivery4/` | Pendiente |
| 5 | Informe técnico final | Jue 26 nov 2026 | `docs/delivery5/` | Pendiente |

### Entrega 1 en el repositorio

| Archivo | Contenido |
| --- | --- |
| [`Entrega1_Diseno_Esquema_y_Plan_de_Implementacion.pdf`](docs/delivery1/Entrega1_Diseno_Esquema_y_Plan_de_Implementacion.pdf) | Informe: plan de implementación, modelo E-R y diccionario de datos |
| [`entrega1.tex`](docs/delivery1/entrega1.tex) | Fuente LaTeX del informe (`latexmk -pdf entrega1.tex`) |
| [`diagrama_er.png`](docs/delivery1/diagrama_er.png) | Diagrama E-R, generado con `python docs/delivery1/er/build_er.py` |
| [`diagrama_er.md`](docs/delivery1/diagrama_er.md) | Versión Mermaid del diagrama, visible en GitHub |
| [`scripts/00_init_db.py`](scripts/00_init_db.py) | Esquema implementado en MongoDB: validadores e índices |

### Entrega 2 en el repositorio

`scripts/01_download_mgn.py` es el tramo asignado a Derek y `scripts/02_prepare_municipalities.py` es el tramo asignado a José. Samuel valida la capa contra la lista PDET (`01_validate_mgn.py`, detalle en [`docs/delivery2/entrega2_validacion_mgn.md`](docs/delivery2/entrega2_validacion_mgn.md)). Miguel carga (`02_load_municipalities.py`) y Sebastián verifica el índice (`02_verify_spatial.py`). Una corrida que no verifica la capa no deja el manifiesto ni el reporte anteriores como si el resultado actual estuviera listo. El detalle y la evidencia están en [`docs/delivery2/entrega2_descarga_y_preparacion.md`](docs/delivery2/entrega2_descarga_y_preparacion.md).

| Archivo | Contenido |
| --- | --- |
| [`scripts/01_download_mgn.py`](scripts/01_download_mgn.py) | Lee el WFS municipal MGN 2025, o las respuestas GML ya verificadas, y escribe el manifiesto |
| [`scripts/01_validate_mgn.py`](scripts/01_validate_mgn.py) | Cruza el MGN con los 170 PDET y revisa DIVIPOLA, duplicados, faltantes y geometrías |
| [`scripts/02_prepare_municipalities.py`](scripts/02_prepare_municipalities.py) | Cruza por DIVIPOLA, pasa a GeoJSON WGS84 y deja la fecha de carga para Miguel |
| [`scripts/02_load_municipalities.py`](scripts/02_load_municipalities.py) | Carga idempotente en `municipalities` con validador y `2dsphere` activos; llena `pdet_subregions` e `ingestion_runs`. Detalle en [`docs/delivery2/entrega2_carga_municipios.md`](docs/delivery2/entrega2_carga_municipios.md) |
| [`outputs/municipalities_load_report.json`](outputs/municipalities_load_report.json) | Resultado de la última carga: insertados, reemplazados, sin cambios, verificaciones y `run_id` |
| [`scripts/02_verify_spatial.py`](scripts/02_verify_spatial.py) | Nueve controles independientes, consulta con control negativo y uso efectivo del índice en el plan ganador. [Método y pruebas](docs/delivery2/entrega2_verificacion_espacial.md) |
| [`outputs/municipalities_spatial_verification_real.json`](outputs/municipalities_spatial_verification_real.json) | Ejecución definitiva de Miguel del 9 nov: 170/170, nueve `OK`, `FETCH → IXSCAN` sobre `geometry_2dsphere`; distinta del antecedente local de Sebastián |
| [`scripts/entrega2_contracts.py`](scripts/entrega2_contracts.py) | Contrato común: campos, CRS, códigos y reglas de unidad de área |
| [`outputs/mgn_wfs_source_receipt.json`](outputs/mgn_wfs_source_receipt.json) | URL, tamaño y SHA256 de las seis respuestas WFS |
| [`outputs/mgn_download_manifest.json`](outputs/mgn_download_manifest.json) | Capa de trabajo: 1122 municipios, CRS declarado y unidad observada |
| [`outputs/municipalities_prepare_report.json`](outputs/municipalities_prepare_report.json) | 170 documentos, hash del GeoJSONL y códigos |
| [`outputs/mgn_validation_summary.md`](outputs/mgn_validation_summary.md) | Resumen de la validación: 20 verificaciones y nombres distintos |
| [`outputs/pdet_mgn_crosswalk.csv`](outputs/pdet_mgn_crosswalk.csv) | Una fila por municipio PDET con su cruce en el MGN |
| [`outputs/mgn_catalog_probe.json`](outputs/mgn_catalog_probe.json) | Hosts que no completaron TLS. No es el resultado de la preparación |

## Fuentes de datos

- **DANE, Marco Geoestadístico Nacional (MGN 2025)**, nivel municipal: <https://geoportal.dane.gov.co/servicios/descarga-y-metadatos/datos-geoestadisticos/?cod=111>
- **Lista de municipios PDET**: `resources/MunicipiosPDET.xlsx`, entregado por el curso (170 municipios, 16 subregiones). Fuente: Agencia de Renovación del Territorio, <https://www.renovacionterritorio.gov.co/central-pdet/que-son-los-pdet>
- **Microsoft Building Footprints** (ODbL): <https://planetarycomputer.microsoft.com/dataset/ms-buildings>
- **Google Open Buildings v3** (CC BY-4.0 / ODbL): <https://sites.research.google/gr/open-buildings/>

## Requisitos

- Docker y Docker Compose
- Python 3.11 o superior

## Cómo correrlo

```bash
# 1. Levantar MongoDB
docker compose up -d

# 2. Crear el entorno de Python
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Verificar el entorno y crear el esquema (Entrega 1)
python scripts/00_check_environment.py     # versiones de Python y dependencias
python scripts/00_check_pdet_list.py       # calidad de la lista PDET (170 / 16)
python scripts/00_init_db.py               # colecciones, validadores e índices

# 4. Correr el flujo en orden (los scripts se agregan en cada entrega)
python scripts/01_download_mgn.py                 # manifiesto en outputs/mgn_download_manifest.json; valida cada GML por bytes o por contenido (sin timeStamp)
python scripts/01_validate_mgn.py                 # cruce con la lista PDET; resumen en outputs/
python scripts/02_prepare_municipalities.py       # GeoJSONL en data/processed/; sin loaded_at
python scripts/02_load_municipalities.py          # Miguel: inserta y pone loaded_at; repetirla no duplica
python scripts/02_verify_spatial.py               # Sebastián
python scripts/03_download_buildings.py
python scripts/04_load_buildings.py
python scripts/00_init_db.py --building-indexes   # índices de buildings, después de la carga
jupyter notebook scripts/05_eda.ipynb
python scripts/06_rooftop_stats.py
jupyter notebook scripts/07_maps.ipynb
```

Las credenciales de MongoDB tienen valores por defecto solo para desarrollo local. Para cambiarlas, copie `.env.example` a `.env` (ignorado por git): Docker Compose lee `MONGO_USER` y `MONGO_PASSWORD`, y los scripts usan `MONGO_URI` si está definida.

Todas las rutas, URLs y umbrales se definen en `config.yaml`; los scripts los leen de ahí y no tienen valores escritos a mano.

## Estructura del repositorio

```
README.md            este archivo
docker-compose.yml   MongoDB 7
config.yaml          rutas, URLs, umbrales
requirements.txt     dependencias de Python
docs/                una carpeta por entrega (PDF + diagramas)
  delivery1/er/       generador del diagrama E-R (build_er.py)
resources/           lista oficial de municipios PDET (Excel del curso)
scripts/             scripts y notebooks numerados del flujo
data/                descargas crudas (ignoradas por git)
outputs/             tablas y mapas de resultados
```

## Base de datos

MongoDB 7, base de datos `upme_pdet`. Colecciones: `pdet_subregions`, `municipalities`, `datasets`, `buildings`, `rooftop_stats`, `ingestion_runs`. El diagrama E-R y el diccionario de datos están en `docs/delivery1/`.

`scripts/00_init_db.py` implementa ese diseño: crea las seis colecciones con validadores `$jsonSchema` (campos obligatorios y tipos del diccionario de datos) y los índices planeados (`2dsphere` sobre `municipalities.geometry` y `buildings.centroid`, más los B-tree de apoyo). Los índices de `buildings` se crean después de la carga masiva para no frenar las inserciones.
