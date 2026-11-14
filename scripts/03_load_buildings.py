"""Carga edificios Microsoft en MongoDB."""
import json, sys, os, hashlib, uuid
from pathlib import Path
from datetime import datetime, timezone

from pymongo import InsertOne, MongoClient, ReplaceOne
from pymongo.errors import BulkWriteError, PyMongoError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import yaml
CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text())

input_path = ROOT / "data" / "processed" / "ms_buildings.geojsonl"

def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""): digest.update(chunk)
    return digest.hexdigest()

print(f"Leyendo: {input_path}")
if not input_path.exists():
    print(f"Error: {input_path} no existe")
    sys.exit(2)

client = MongoClient(os.getenv("MONGO_URI", CONFIG["mongodb"]["uri"]))
db = client[CONFIG["mongodb"]["database"]]

try:
    if "buildings" not in db.list_collection_names():
        print("Creando colección buildings...")
        db.create_collection("buildings")
    
    coll = db["buildings"]
    documents = []
    doc_count = 0
    
    with open(input_path, 'r') as f:
        for line in f:
            if not line.strip(): continue
            doc_count += 1
            doc = json.loads(line)
            doc["_id"] = f"ms_{doc.get('source_ref')}_{hashlib.sha256(json.dumps(doc.get('geometry')).encode()).hexdigest()[:12]}"
            doc["loaded_at"] = datetime.now(timezone.utc)
            documents.append(ReplaceOne({"_id": doc["_id"]}, doc, upsert=True))
    
    print(f"Cargando {doc_count} documentos...")
    if documents:
        result = coll.bulk_write(documents)
        print(f"✓ Insertados: {result.inserted_count}")
        print(f"✓ Modificados: {result.modified_count}")
    
    report = {
        "status": "complete",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "documents_total": doc_count,
        "documents_inserted": result.inserted_count if documents else 0,
        "source_sha256": sha256_file(input_path),
    }
    
    with open(ROOT / "outputs" / "buildings_load_report.json", 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"✓ Carga completada")
    sys.exit(0)
    
except PyMongoError as e:
    print(f"Error MongoDB: {e}")
    sys.exit(2)
finally:
    client.close()
