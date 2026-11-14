"""EDA y análisis comparativo: municipios y edificios."""
import json, sys, os
from pathlib import Path
from datetime import datetime, timezone

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import yaml
from pymongo import MongoClient
from pymongo.errors import PyMongoError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text())
OUTPUT_DIR = ROOT / "outputs" / "eda"

client = MongoClient(os.getenv("MONGO_URI", CONFIG["mongodb"]["uri"]))
db = client[CONFIG["mongodb"]["database"]]

try:
    print("\n=== EDA MUNICIPIOS ===")
    mun_coll = db["municipalities"]
    m_stats = list(mun_coll.aggregate([{
        "$group": {
            "_id": None,
            "count": {"$sum": 1},
            "total_area": {"$sum": "$area_m2"},
            "avg_area": {"$avg": "$area_m2"},
        }
    }]))[0]
    print(f"Municipios: {m_stats['count']}")
    print(f"  Área total: {m_stats['total_area']/1e6:.0f} km²")
    print(f"  Promedio: {m_stats['avg_area']/1e6:.0f} km²")
    
    print("\n=== EDA EDIFICIOS ===")
    bldg_coll = db["buildings"]
    b_stats = list(bldg_coll.aggregate([{
        "$group": {
            "_id": None,
            "count": {"$sum": 1},
            "total_area": {"$sum": "$area_m2"},
            "avg_area": {"$avg": "$area_m2"},
        }
    }]))[0]
    print(f"Edificios: {b_stats['count']:,}")
    print(f"  Área total: {b_stats['total_area']/1e6:.0f} km²")
    print(f"  Promedio: {b_stats['avg_area']:.1f} m²")
    
    print("\n=== COMPARATIVA ===")
    ratio = b_stats['count'] / m_stats['count']
    coverage = b_stats['total_area'] / m_stats['total_area'] * 100
    print(f"Ratio: {ratio:,.0f} edificios/municipio")
    print(f"Cobertura de área: {coverage:.1f}%")
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "municipalities": {
            "total": m_stats["count"],
            "total_area_m2": m_stats["total_area"],
            "avg_area_m2": m_stats["avg_area"],
        },
        "buildings": {
            "total": b_stats["count"],
            "total_area_m2": b_stats["total_area"],
            "avg_area_m2": b_stats["avg_area"],
        },
        "comparison": {
            "ratio_buildings_per_municipality": ratio,
            "area_coverage_percent": coverage,
        }
    }
    
    with open(OUTPUT_DIR / "eda_report.json", 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"\n✓ Reporte guardado en {OUTPUT_DIR}/eda_report.json")
    sys.exit(0)
    
except PyMongoError as e:
    print(f"Error MongoDB: {e}")
    sys.exit(2)
finally:
    client.close()
