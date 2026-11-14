"""Prepara los edificios Microsoft Building Footprints para carga en MongoDB."""
import json, gzip, sys, os
from pathlib import Path
from datetime import datetime, timezone

import shapely.geometry
import shapely.ops
from shapely.geometry import mapping, shape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

def sha256_file(path):
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

manifest_path = ROOT / "outputs" / "ms_buildings_download_manifest.json"
output_path = ROOT / "data" / "processed" / "ms_buildings.geojsonl"

with open(manifest_path) as f:
    manifest = json.load(f)

print(f"Preparando {len(manifest['partitions'])} particiones...")
output_path.parent.mkdir(parents=True, exist_ok=True)

total_written = 0
with open(output_path, 'w') as out:
    for partition in manifest['partitions']:
        local = ROOT / partition['local_path']
        if not local.exists():
            print(f"✗ Falta: {local}")
            sys.exit(2)
        
        try:
            with gzip.open(local, 'rt', encoding='utf-8') as gz:
                for line_num, line in enumerate(gz):
                    if not line.strip(): continue
                    feature = json.loads(line)
                    geom = feature.get("geometry", {})
                    
                    try:
                        shp = shape(geom)
                        if shp.is_empty or not shp.is_valid:
                            shp = shapely.ops.unary_union([shp])
                        if shp.is_empty or not shp.is_valid: continue
                    except: continue
                    
                    props = feature.get("properties", {})
                    centroid = shp.centroid
                    
                    doc = {
                        "geometry": mapping(shp) if not shp.equals(shape(geom)) else geom,
                        "geometry_centroid": {"type": "Point", "coordinates": [centroid.x, centroid.y]},
                        "area_m2": shp.area,
                        "height_m": None if props.get("height", -1) == -1 else props.get("height"),
                        "confidence": None if props.get("confidence", -1) == -1 else props.get("confidence"),
                        "source": "microsoft",
                        "source_version": "2026-02-03",
                        "source_ref": f"{partition['quadkey']}:{line_num}",
                        "partition_quadkey": partition["quadkey"],
                    }
                    out.write(json.dumps(doc, ensure_ascii=False) + '\n')
                    total_written += 1
        except Exception as e:
            print(f"✗ Error en {local}: {e}")
            sys.exit(2)

hash_val = sha256_file(output_path)
print(f"✓ {total_written} edificios preparados")
print(f"✓ SHA256: {hash_val}")
print(f"✓ Archivo: {output_path}")
