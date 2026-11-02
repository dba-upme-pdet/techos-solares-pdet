"""Crea el esquema de la Entrega 1 en MongoDB: colecciones, validadores e índices.

Implementa el diccionario de datos (sección 5) y los índices planeados
(sección 6.1) de docs/delivery1/. Es idempotente: se puede correr varias veces.

Uso:
    python scripts/00_init_db.py                      # colecciones + índices pequeños
    python scripts/00_init_db.py --building-indexes   # además, índices de buildings
                                                      # (correr DESPUÉS de la carga masiva)

La URI sale de config.yaml; la variable de entorno MONGO_URI la reemplaza si existe.
"""
import argparse
import os
from pathlib import Path

import yaml
from pymongo import ASCENDING, GEOSPHERE, MongoClient

ROOT = Path(__file__).resolve().parents[1]

GEOJSON_POLY = {"bsonType": "object", "required": ["type", "coordinates"],
                "properties": {"type": {"enum": ["Polygon", "MultiPolygon"]}}}
GEOJSON_POINT = {"bsonType": "object", "required": ["type", "coordinates"],
                 "properties": {"type": {"enum": ["Point"]}}}
NUM = ["double", "int", "long"]

# Validadores $jsonSchema: solo campos obligatorios y tipos del diccionario de datos.
SCHEMAS = {
    "pdet_subregions": {
        "required": ["_id", "name", "municipality_count"],
        "properties": {
            "_id": {"bsonType": "int", "minimum": 1, "maximum": 16},
            "name": {"bsonType": "string"},
            "municipality_count": {"bsonType": "int", "minimum": 1},
        },
    },
    "municipalities": {
        "required": ["_id", "name", "dpto_code", "dpto_name", "subregion_id",
                     "subregion_name", "area_km2", "geometry", "source", "loaded_at"],
        "properties": {
            "_id": {"bsonType": "string", "pattern": "^[0-9]{5}$"},
            "name": {"bsonType": "string"},
            "dpto_code": {"bsonType": "string", "pattern": "^[0-9]{2}$"},
            "dpto_name": {"bsonType": "string"},
            "subregion_id": {"bsonType": "int"},
            "subregion_name": {"bsonType": "string"},
            "area_km2": {"bsonType": NUM},
            "geometry": GEOJSON_POLY,
            "source": {"bsonType": "object"},
            "loaded_at": {"bsonType": "date"},
        },
    },
    "datasets": {
        "required": ["_id", "name", "version", "license", "url", "accessed_at"],
        "properties": {
            "_id": {"bsonType": "string"},
            "name": {"bsonType": "string"},
            "version": {"bsonType": "string"},
            "license": {"bsonType": "string"},
            "url": {"bsonType": "string"},
            "accessed_at": {"bsonType": "date"},
        },
    },
    "buildings": {
        "required": ["dataset_id", "footprint", "centroid", "area_m2", "run_id"],
        "properties": {
            "dataset_id": {"bsonType": "string"},
            "source_ref": {"bsonType": ["string", "null"]},
            "footprint": {"bsonType": "object", "required": ["type", "coordinates"],
                          "properties": {"type": {"enum": ["Polygon"]}}},
            "centroid": GEOJSON_POINT,
            "area_m2": {"bsonType": NUM, "minimum": 0},
            "area_src_m2": {"bsonType": NUM + ["null"]},
            "confidence": {"bsonType": NUM + ["null"], "minimum": 0, "maximum": 1},
            "height_m": {"bsonType": NUM + ["null"]},
            "mpio_code": {"bsonType": ["string", "null"], "pattern": "^[0-9]{5}$"},
            "run_id": {"bsonType": "objectId"},
        },
    },
    "rooftop_stats": {
        "required": ["_id", "building_count", "total_area_m2", "mean_area_m2",
                     "median_area_m2", "filters", "computed_at"],
        "properties": {
            "_id": {"bsonType": "object", "required": ["mpio_code", "dataset_id"]},
            "building_count": {"bsonType": ["int", "long"], "minimum": 0},
            "total_area_m2": {"bsonType": NUM, "minimum": 0},
            "mean_area_m2": {"bsonType": NUM},
            "median_area_m2": {"bsonType": NUM},
            "filters": {"bsonType": "object"},
            "computed_at": {"bsonType": "date"},
        },
    },
    "ingestion_runs": {
        "required": ["dataset_id", "source_file", "rows_read", "rows_loaded",
                     "rows_rejected", "started_at", "finished_at"],
        "properties": {
            "dataset_id": {"bsonType": "string"},
            "source_file": {"bsonType": "string"},
            "rows_read": {"bsonType": ["int", "long"]},
            "rows_loaded": {"bsonType": ["int", "long"]},
            "rows_rejected": {"bsonType": ["int", "long"]},
            "started_at": {"bsonType": "date"},
            "finished_at": {"bsonType": "date"},
            "notes": {"bsonType": ["string", "null"]},
        },
    },
}

# Índices de la sección 6.1. Los de buildings se crean después de la carga masiva.
SMALL_INDEXES = {
    "municipalities": [([("geometry", GEOSPHERE)], "geometry_2dsphere"),
                       ([("subregion_id", ASCENDING)], "subregion_id_1")],
    "ingestion_runs": [([("dataset_id", ASCENDING)], "dataset_id_1")],
}
BUILDING_INDEXES = {
    "buildings": [([("centroid", GEOSPHERE)], "centroid_2dsphere"),
                  ([("dataset_id", ASCENDING), ("mpio_code", ASCENDING)],
                   "dataset_id_1_mpio_code_1")],
}


def get_db():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    uri = os.environ.get("MONGO_URI", cfg["mongo"]["uri"])
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    return client[cfg["mongo"]["database"]]


def apply_schemas(db):
    existing = set(db.list_collection_names())
    for name, schema in SCHEMAS.items():
        validator = {"$jsonSchema": {"bsonType": "object", **schema}}
        if name in existing:
            db.command("collMod", name, validator=validator, validationLevel="moderate")
            print(f"[actualizada] {name}")
        else:
            db.create_collection(name, validator=validator, validationLevel="moderate")
            print(f"[creada]      {name}")


def apply_indexes(db, spec):
    for coll, indexes in spec.items():
        for keys, name in indexes:
            db[coll].create_index(keys, name=name)
            print(f"[índice]      {coll}.{name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--building-indexes", action="store_true",
                        help="crear también los índices de buildings (después de la carga)")
    args = parser.parse_args()

    db = get_db()
    apply_schemas(db)
    apply_indexes(db, SMALL_INDEXES)
    if args.building_indexes:
        apply_indexes(db, BUILDING_INDEXES)
    print(f"Esquema listo en la base '{db.name}': {sorted(db.list_collection_names())}")


if __name__ == "__main__":
    main()
