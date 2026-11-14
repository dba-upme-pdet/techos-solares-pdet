"""Verifica integridad espacial de edificios Microsoft en MongoDB."""
import json, sys, os
from pathlib import Path
from datetime import datetime, timezone

import yaml
from pymongo import MongoClient
from pymongo.errors import PyMongoError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text())

client = MongoClient(os.getenv("MONGO_URI", CONFIG["mongodb"]["uri"]))
db = client[CONFIG["mongodb"]["database"]]

try:
    coll = db["buildings"]
    total = coll.count_documents({})
    print(f"Total de edificios: {total:,}")
    
    if total == 0:
        print("Error: No hay edificios")
        sys.exit(1)
    
    sample = coll.find_one({})
    required = ["geometry", "geometry_centroid", "source", "area_m2"]
    missing = [f for f in required if f not in sample]
    if missing:
        print(f"Error: Faltan campos: {missing}")
        sys.exit(1)
    print(f"✓ Campos válidos")
    
    indexes = list(coll.list_indexes())
    has_geo = any("2dsphere" in str(idx) for idx in indexes)
    if not has_geo:
        print("Creando índice 2dsphere...")
        coll.create_index([("geometry", "2dsphere")])
    print(f"✓ Índice 2dsphere activo")
    
    stats = list(coll.aggregate([{
        "$group": {
            "_id": None,
            "count": {"$sum": 1},
            "avg_area": {"$avg": "$area_m2"},
            "min_area": {"$min": "$area_m2"},
            "max_area": {"$max": "$area_m2"},
            "total_area": {"$sum": "$area_m2"},
        }
    }]))[0]
    
    print(f"\nEstadísticas:")
    print(f"  Total: {stats['count']:,}")
    print(f"  Promedio área: {stats['avg_area']:.1f} m²")
    print(f"  Rango: {stats['min_area']:.1f} - {stats['max_area']:.1f} m²")
    print(f"  Área total: {stats['total_area']:.0f} m²")
    
    print(f"\n✓ Verificación completa")
    sys.exit(0)
    
except PyMongoError as e:
    print(f"Error MongoDB: {e}")
    sys.exit(2)
finally:
    client.close()
