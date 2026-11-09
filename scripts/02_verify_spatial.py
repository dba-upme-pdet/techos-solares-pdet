"""Verifica municipios PDET en MongoDB sin modificar la base.

Uso: python scripts/02_verify_spatial.py [--report ruta.json]
Salida: 0 verificación completa, 1 fallo o comprobación pendiente, 2 error operativo.
MONGO_URI reemplaza la URI de config.yaml. Las rutas son relativas al repositorio.
"""
from __future__ import annotations

import argparse
import importlib.util
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from shapely.errors import GEOSException
from shapely.geometry import shape

# Compartir constantes y normalización sin alterar los contratos del equipo.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from entrega2_contracts import (  # noqa: E402
    COLOMBIA_LAT, COLOMBIA_LON, ContractError, sha256_file, write_json, zfill_digits,
)

CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
EXPECTED = 170
_spec = importlib.util.spec_from_file_location("spatial_db_schema", ROOT / "scripts/00_init_db.py")
_schema = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_schema)
MUNICIPALITY_SCHEMA = {"bsonType": "object", **_schema.SCHEMAS["municipalities"]}


def valid_geometry(geometry):
    """GeoJSON 2D estricto: no permite que Shapely cierre anillos implícitamente."""
    if not isinstance(geometry, dict) or geometry.get("type") not in ("Polygon", "MultiPolygon"):
        return False
    # RFC 7946 usa longitud/latitud WGS84; no aceptar un CRS alternativo.
    if "crs" in geometry:
        return False
    coords = geometry.get("coordinates")
    if not isinstance(coords, (list, tuple)) or not coords:
        return False
    polygons = [coords] if geometry["type"] == "Polygon" else coords
    for polygon in polygons:
        if not isinstance(polygon, (list, tuple)) or not polygon:
            return False
        for ring in polygon:
            if not isinstance(ring, (list, tuple)) or len(ring) < 4:
                return False
            for position in ring:
                if not isinstance(position, (list, tuple)) or len(position) != 2:
                    return False
                if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                       for v in position):
                    return False
                lon, lat = position
                if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    return False
                if not (COLOMBIA_LON[0] <= lon <= COLOMBIA_LON[1]
                        and COLOMBIA_LAT[0] <= lat <= COLOMBIA_LAT[1]):
                    return False
            if list(ring[0]) != list(ring[-1]):
                return False
            if len({tuple(p) for p in ring[:-1]}) < 3:
                return False
    try:
        polygon = shape(geometry)
        return not polygon.is_empty and polygon.is_valid and polygon.area > 0
    except (ValueError, TypeError, AttributeError, IndexError, GEOSException):
        return False


def uses_spatial_index(node, index_names):
    """Llamar solo con winningPlan, nunca con rejectedPlans ni el explain entero."""
    if isinstance(node, dict):
        if node.get("indexName") in index_names and node.get("stage") in ("IXSCAN", "EXPRESS_IXSCAN"):
            return True
        return any(uses_spatial_index(value, index_names) for value in node.values())
    if isinstance(node, list):
        return any(uses_spatial_index(value, index_names) for value in node)
    return False


def load_reference(config=CONFIG, root=ROOT):
    """Referencia configurada, códigos normalizados y validados; nunca inventa códigos."""
    ref = config["sources"]["pdet_list"]
    path = root / ref["file"]
    frame = pd.read_excel(path, sheet_name=ref["sheet"])
    codes = [zfill_digits(value, 5) for value in frame[ref["code_column"]]]
    if (ref["expected_municipalities"] != EXPECTED or len(codes) != EXPECTED
            or len(set(codes)) != EXPECTED
            or any(re.fullmatch(r"[0-9]{5}", code) is None for code in codes)):
        raise ContractError("la referencia debe contener exactamente 170 códigos únicos de cinco dígitos")
    return set(codes), {"path": str(path.relative_to(root)), "sha256": sha256_file(path)}


def verify_report(collection, *, reference_codes=None, reference_status="OK", reference_info=None):
    """Lectura de documentos, $jsonSchema y consultas sin hint ni escrituras.

    reference_codes permite inyectar un conjunto explícitamente sintético en pruebas.
    En CLI siempre se lee el Excel configurado. Un pendiente impide el éxito global.
    """
    report = {"database": collection.database.name, "collection": collection.name,
              "checked_at": datetime.now(timezone.utc).isoformat(), "checks": {},
              "reference": reference_info or {}}

    def record(name, status, message, **evidence):
        report["checks"][name] = {"status": status, "message": message, **evidence}
        print(f"[{status}] {name}: {message}")

    def check(name, condition, message, **evidence):
        record(name, "OK" if condition else "FALLA", message, **evidence)

    collection.database.client.admin.command("ping")
    record("connection", "OK", "Conexión a MongoDB")
    documents = list(collection.find({}).sort("_id", 1))
    count = len(documents)
    check("count", count == EXPECTED, f"Municipios: {count}/{EXPECTED}")
    codes = [doc.get("_id") for doc in documents]
    format_ok = all(isinstance(code, str) and re.fullmatch(r"[0-9]{5}", code) for code in codes)
    unique = len({repr(code) for code in codes}) == count
    check("divipola", count > 0 and format_ok and unique, "Identificadores únicos de cinco dígitos ASCII")
    if reference_status != "OK" or reference_codes is None:
        record("official_codes", reference_status if reference_status != "OK" else "PENDIENTE",
               "Referencia PDET no verificable", detail=reference_info or {})
    else:
        observed = {code for code in codes if isinstance(code, str)}
        missing, extra = sorted(reference_codes - observed), sorted(observed - reference_codes)
        check("official_codes", not missing and not extra and format_ok and unique,
              f"Cruce PDET: faltan {len(missing)}, sobran {len(extra)}", missing=missing, extra=extra)

    # MongoDB interpreta el mismo $jsonSchema que usa 00_init_db.py, incluso si
    # la colección existente no tiene validador o contiene documentos antiguos.
    schema_errors = [repr(doc["_id"]) for doc in collection.find(
        {"$nor": [{"$jsonSchema": MUNICIPALITY_SCHEMA}]}, {"_id": 1})]
    contract_errors = []
    for doc in documents:
        code, department, area = doc.get("_id"), doc.get("dpto_code"), doc.get("area_km2")
        if (not isinstance(code, str) or department != code[:2]
                or type(doc.get("subregion_id")) is not int or not 1 <= doc["subregion_id"] <= 16
                or any(not isinstance(doc.get(k), str) or not doc[k].strip()
                       for k in ("name", "dpto_name", "subregion_name"))
                or isinstance(area, bool) or not isinstance(area, (int, float))
                or not math.isfinite(area) or area <= 0
                or not isinstance(doc.get("source"), dict)
                or any(not isinstance(doc["source"].get(k), str) or not doc["source"][k].strip()
                       for k in ("dataset", "version", "file"))):
            contract_errors.append(repr(code))
    check("schema", count > 0 and not schema_errors and not contract_errors,
          f"Esquema y contrato: {len(schema_errors)} errores de esquema, {len(contract_errors)} de contrato",
          schema_error_ids=schema_errors, contract_error_ids=contract_errors)

    invalid = [repr(doc.get("_id")) for doc in documents if not valid_geometry(doc.get("geometry"))]
    check("geometry", count > 0 and not invalid, f"Geometrías válidas: {count - len(invalid)}/{count}",
          invalid_ids=invalid)
    indexes = collection.index_information()
    spatial_indexes = [name for name, info in indexes.items()
                       if ("geometry", "2dsphere") in info.get("key", []) and not info.get("hidden")]
    check("index", bool(spatial_indexes), "Índice 2dsphere visible sobre geometry", indexes=spatial_indexes)
    if not count or invalid or not format_ok or not unique:
        record("query", "PENDIENTE", "Requiere documentos e identificadores con geometrías válidas")
        record("explain", "PENDIENTE", "Requiere consulta espacial verificable")
    else:
        geometries = {doc["_id"]: shape(doc["geometry"]) for doc in documents}
        sample_id = codes[0]
        point = geometries[sample_id].representative_point()
        query = {"geometry": {"$geoIntersects": {"$geometry": {
            "type": "Point", "coordinates": [point.x, point.y]}}}}
        expected = sorted(code for code, geom in geometries.items() if geom.intersects(point))
        actual = sorted(doc["_id"] for doc in collection.find(query, {"_id": 1}))
        # Control negativo fuera de la ventana Colombia del contrato.
        negative_query = {"geometry": {"$geoIntersects": {"$geometry": {
            "type": "Point", "coordinates": [0.0, 0.0]}}}}
        negative = collection.count_documents(negative_query)
        check("query", actual == expected and sample_id in actual and negative == 0,
              f"$geoIntersects: {len(actual)} coincidencias, control negativo: {negative}",
              query=query, expected_ids=expected, actual_ids=actual,
              negative_query=negative_query, negative_matches=negative)
        explanation = collection.database.command({"explain": {
            "find": collection.name, "filter": query}, "verbosity": "executionStats"})
        winning = explanation.get("queryPlanner", {}).get("winningPlan", {})
        stats = explanation.get("executionStats", {})
        check("explain", bool(spatial_indexes) and uses_spatial_index(winning, spatial_indexes)
              and stats.get("executionSuccess") is True and stats.get("nReturned") == len(actual)
              and stats.get("totalKeysExamined", 0) > 0,
              "Plan ganador sin hint y ejecución del índice espacial",
              winning_plan=winning, execution_stats=stats)
    report["success"] = all(c["status"] == "OK" for c in report["checks"].values())
    print(f"Resultado: {sum(c['status'] == 'OK' for c in report['checks'].values())}/{len(report['checks'])} OK")
    return report


def verify(collection):
    """Interfaz booleana conservada para consumidores existentes."""
    codes, info = load_reference()
    return verify_report(collection, reference_codes=codes, reference_info=info)["success"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="guardar evidencia JSON (relativa al repositorio)")
    args = parser.parse_args(argv)
    report = {"success": False}
    try:
        try:
            codes, info = load_reference()
            status = "OK"
        except FileNotFoundError:
            codes, info, status = None, {"reason": "Archivo de referencia ausente"}, "PENDIENTE"
        except (ContractError, ValueError, KeyError, OSError) as exc:
            codes, info, status = None, {"reason": str(exc)}, "FALLA"
        with MongoClient(os.environ.get("MONGO_URI", CONFIG["mongo"]["uri"]),
                         serverSelectionTimeoutMS=5000, socketTimeoutMS=30000) as client:
            report = verify_report(client[CONFIG["mongo"]["database"]]["municipalities"],
                                   reference_codes=codes, reference_status=status, reference_info=info)
        exit_code = 0 if report["success"] else 1
    except (PyMongoError, ValueError, TypeError, KeyError, OSError) as exc:
        # No registrar excepciones de conexión que podrían incluir credenciales.
        print(f"[FALLA] Error operativo: {type(exc).__name__}")
        report.update(success=False, operational_error=type(exc).__name__)
        exit_code = 2
    if args.report:
        try:
            write_json(ROOT / args.report, report)
        except (OSError, TypeError, ValueError) as exc:
            print(f"[FALLA] No se pudo guardar el reporte: {type(exc).__name__}")
            return 2
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
