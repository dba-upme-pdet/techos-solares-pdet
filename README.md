# Potencial solar en techos de municipios PDET (UPME)

Administración de Bases de Datos — Proyecto final  
Prof. Andrés Oswaldo Calderón Romero, Ph.D.

Flujo de trabajo geoespacial reproducible que cuenta los techos de edificaciones y estima su área total en cada uno de los 170 municipios PDET de Colombia. Usa MongoDB como motor NoSQL y dos datasets abiertos de huellas de edificaciones: Microsoft Building Footprints y Google Open Buildings v3.

## Equipo

| Integrante | Usuario de GitHub |
| --- | --- |
| Derek Sarmiento | [@Derekk8] |
| José Medina | [@joseda1327] |
| Miguel Duarte | [@MiguelDu020] |
| Sebastián Sánchez Vásquez | [@tiansv] |
| Samuel Emperador | [@emperador24] |

Organización: [`dba-upme-pdet`](https://github.com/dba-upme-pdet) · Repositorio: <https://github.com/dba-upme-pdet/techos-solares-pdet>

## Entregas

| # | Entrega | Fecha | Carpeta | Estado |
| --- | --- | --- | --- | --- |
| 1 | Diseño del esquema NoSQL y plan de implementación | Lun 2 nov 2026 | `docs/delivery1/` | Entregada |
| 2 | Integración de los límites de municipios PDET | Lun 9 nov 2026 | `docs/delivery2/` | Pendiente |
| 3 | Carga e integración de huellas de edificaciones | Lun 16 nov 2026 | `docs/delivery3/` | Pendiente |
| 4 | Flujo reproducible de análisis geoespacial | Lun 23 nov 2026 | `docs/delivery4/` | Pendiente |
| 5 | Informe técnico final | Jue 26 nov 2026 | `docs/delivery5/` | Pendiente |

## Fuentes de datos

- **DANE — Marco Geoestadístico Nacional (MGN 2025)**, nivel municipal: <https://geoportal.dane.gov.co/servicios/descarga-y-metadatos/datos-geoestadisticos/?cod=111>
- **Lista de municipios PDET** — `resources/MunicipiosPDET.xlsx`, entregado por el curso (170 municipios, 16 subregiones). Fuente: Agencia de Renovación del Territorio, <https://www.renovacionterritorio.gov.co/central-pdet/que-son-los-pdet>
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
python scripts/01_download_mgn.py
python scripts/02_load_municipalities.py
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
resources/           lista oficial de municipios PDET (Excel del curso)
scripts/             scripts y notebooks numerados del flujo
data/                descargas crudas (ignoradas por git)
outputs/             tablas y mapas de resultados
```

## Base de datos

MongoDB 7, base de datos `upme_pdet`. Colecciones: `pdet_subregions`, `municipalities`, `datasets`, `buildings`, `rooftop_stats`, `ingestion_runs`. El diagrama E-R y el diccionario de datos están en `docs/delivery1/`.

`scripts/00_init_db.py` implementa ese diseño: crea las seis colecciones con validadores `$jsonSchema` (campos obligatorios y tipos del diccionario de datos) y los índices planeados (`2dsphere` sobre `municipalities.geometry` y `buildings.centroid`, más los B-tree de apoyo). Los índices de `buildings` se crean después de la carga masiva para no frenar las inserciones.
