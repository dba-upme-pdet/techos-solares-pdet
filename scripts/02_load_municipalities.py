"""Carga los municipios PDET en MongoDB (Entrega 2, Miguel).

Lee ``data/processed/municipalities.geojsonl`` (salida de
``02_prepare_municipalities.py``) y lo carga en ``municipalities`` con el
validador ``$jsonSchema`` y el índice ``geometry_2dsphere`` de ``00_init_db.py``
ya activos, así MongoDB rechaza cualquier documento o geometría inválida.

La carga es idempotente: el ``_id`` es el código DIVIPOLA, cada documento se
inserta, se reemplaza si cambió o se deja igual si ya estaba idéntico.
Repetirla no crea duplicados ni cambia ``loaded_at`` de lo que no cambió.
También deja las 16 subregiones en ``pdet_subregions``, registra la corrida
en ``ingestion_runs`` y escribe ``outputs/municipalities_load_report.json``.

Uso:
    python scripts/02_load_municipalities.py
    python scripts/02_load_municipalities.py --prune          # borra _id que no están en la entrada
    python scripts/02_load_municipalities.py --allow-input-mismatch
    python scripts/02_load_municipalities.py --self-check     # pruebas en una base temporal

Salida: 0 carga verificada, 1 falla de datos o de verificación, 2 error operativo.
MONGO_URI reemplaza la URI de config.yaml.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from pymongo import DeleteOne, InsertOne, MongoClient, ReplaceOne
from pymongo.errors import BulkWriteError, PyMongoError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from entrega2_contracts import (  # noqa: E402
    CONTRACT_VERSION,
    ContractError,
    document_errors,
    load_config,
    sha256_file,
    write_json,
)

# 00_init_db.py empieza con número: se importa por ruta para reutilizar el
# mismo validador e índices, sin copiarlos.
_spec = importlib.util.spec_from_file_location("init_db", ROOT / "scripts" / "00_init_db.py")
init_db = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(init_db)

COLLECTION = "municipalities"
SUBREGIONS = "pdet_subregions"
RUNS = "ingestion_runs"
RUN_DATASET_ID = "mgn"   # diccionario de datos 5.6: dataset_id de datasets._id "o mgn"


class LoadError(Exception):
    """La entrada o la colección no cumplen lo necesario para declarar la carga."""


# ---------------------------------------------------------------- entrada


def read_geojsonl(path: Path) -> list[dict]:
    if not path.is_file():
        raise LoadError(f"no existe {path.name}; corra antes 02_prepare_municipalities.py")
    documents = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                documents.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise LoadError(f"línea {number} de {path.name} no es JSON: {exc}") from exc
    return documents


def check_prepare_report(report: dict, input_path: Path, root: Path, *, allow_mismatch: bool) -> dict:
    """La entrada tiene que ser la que José declaró lista; si no, no se carga."""
    problems = []
    if report.get("contract") != CONTRACT_VERSION:
        problems.append(f"contrato {report.get('contract')!r}, se esperaba {CONTRACT_VERSION}")
    if report.get("status") != "ready_for_load":
        problems.append(f"el reporte de preparación está en estado {report.get('status')!r}")
    if report.get("claims_full_pdet_set") is not True:
        problems.append("el reporte de preparación no declara los 170 municipios")
    if report.get("loaded_at_included") is not False:
        problems.append("la preparación no debe traer loaded_at")
    declared = report.get("output_geojsonl")
    if declared and (root / declared).resolve() != input_path.resolve():
        problems.append(f"el reporte declara {declared}, se pidió cargar {input_path.name}")
    observed = sha256_file(input_path)
    sha_ok = observed == report.get("sha256")
    if not sha_ok and not allow_mismatch:
        problems.append(
            f"sha256 de {input_path.name} ({observed[:12]}…) no es el del reporte "
            f"({str(report.get('sha256'))[:12]}…); vuelva a correr 02_prepare_municipalities.py "
            "o use --allow-input-mismatch dejándolo registrado"
        )
    if problems:
        raise LoadError("; ".join(problems))
    return {"input_sha256": observed, "input_matches_prepare_report": sha_ok}


def check_documents(documents: list[dict], *, expected_count: int, expected_ids: list[str] | None) -> None:
    """Revisa la entrada antes de tocar la base: contrato, duplicados y conjunto PDET."""
    problems = []
    ids = [doc.get("_id") for doc in documents]
    repeated = sorted(code for code, n in Counter(ids).items() if n > 1)
    if repeated:
        problems.append(f"_id repetidos en la entrada: {repeated}")
    for doc in documents:
        errors = document_errors(doc)
        if errors:
            problems.append(f"{doc.get('_id')}: {'; '.join(errors)}")
    if len(set(ids)) != expected_count:
        problems.append(f"la entrada trae {len(set(ids))} municipios distintos y se esperan {expected_count}")
    if expected_ids is not None and set(ids) != set(expected_ids):
        missing = sorted(set(expected_ids) - set(ids))
        extra = sorted(set(ids) - set(expected_ids))
        problems.append(f"no es el conjunto del reporte: faltan {missing}, sobran {extra}")
    if problems:
        raise LoadError(" | ".join(problems[:20]))


def subregions_from(documents: list[dict]) -> list[dict]:
    """pdet_subregions sale de los mismos documentos: _id, nombre y conteo."""
    names: dict[int, set[str]] = {}
    counts: Counter = Counter()
    for doc in documents:
        names.setdefault(doc["subregion_id"], set()).add(doc["subregion_name"])
        counts[doc["subregion_id"]] += 1
    conflicting = {key: sorted(value) for key, value in names.items() if len(value) > 1}
    if conflicting:
        raise LoadError(f"una subregión tiene más de un nombre: {conflicting}")
    return [
        {"_id": key, "name": next(iter(names[key])), "municipality_count": counts[key]}
        for key in sorted(names)
    ]


# ---------------------------------------------------------------- base


def ensure_schema(db) -> list[str]:
    """Validador e índices de 00_init_db.py, solo para las colecciones que toca esta carga."""
    existing = set(db.list_collection_names())
    for name in (COLLECTION, SUBREGIONS, RUNS):
        validator = {"$jsonSchema": {"bsonType": "object", **init_db.SCHEMAS[name]}}
        if name in existing:
            db.command("collMod", name, validator=validator, validationLevel="moderate",
                       validationAction="error")
        else:
            db.create_collection(name, validator=validator, validationLevel="moderate",
                                 validationAction="error")
    for coll in (COLLECTION, RUNS):
        for keys, index_name in init_db.SMALL_INDEXES[coll]:
            db[coll].create_index(keys, name=index_name)
    return sorted(db[COLLECTION].index_information())


def without_loaded_at(doc: dict) -> dict:
    return {key: value for key, value in doc.items() if key != "loaded_at"}


def plan_operations(collection, documents: list[dict], loaded_at: datetime, *, prune: bool):
    """Inserta lo nuevo, reemplaza lo que cambió y no toca lo idéntico."""
    existing = {doc["_id"]: doc for doc in collection.find({})}
    incoming = {doc["_id"] for doc in documents}
    operations, summary = [], {"insert": [], "replace": [], "unchanged": [], "delete": [], "extra_in_db": []}
    for doc in documents:
        current = existing.get(doc["_id"])
        if current is None:
            operations.append(InsertOne({**doc, "loaded_at": loaded_at}))
            summary["insert"].append(doc["_id"])
        elif without_loaded_at(current) == doc:
            summary["unchanged"].append(doc["_id"])
        else:
            operations.append(ReplaceOne({"_id": doc["_id"]}, {**doc, "loaded_at": loaded_at}))
            summary["replace"].append(doc["_id"])
    for code in sorted(set(existing) - incoming, key=str):
        summary["extra_in_db"].append(code)
        if prune:
            operations.append(DeleteOne({"_id": code}))
            summary["delete"].append(code)
    return operations, summary


def write_errors(exc: BulkWriteError) -> list[dict]:
    rejected = []
    for error in exc.details.get("writeErrors", []):
        op = error.get("op") or {}
        code = op.get("_id") if isinstance(op, dict) else None
        if code is None and isinstance(op, dict):
            code = (op.get("q") or {}).get("_id")
        rejected.append({"_id": code, "code": error.get("code"), "message": str(error.get("errmsg"))[:500]})
    return rejected


def verify_collection(collection, documents: list[dict], *, expected_count: int) -> dict:
    """Lo mínimo para afirmar la carga; la verificación completa es 02_verify_spatial.py."""
    from shapely.geometry import shape

    expected_ids = sorted(doc["_id"] for doc in documents)
    stored_ids = sorted(doc["_id"] for doc in collection.find({}, {"_id": 1}))
    duplicates = list(collection.aggregate([
        {"$group": {"_id": {"name": "$name", "dpto_code": "$dpto_code"}, "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 1}}},
    ]))
    schema = {"bsonType": "object", **init_db.SCHEMAS[COLLECTION]}
    schema_violations = [doc["_id"] for doc in collection.find({"$nor": [{"$jsonSchema": schema}]}, {"_id": 1})]
    missing_loaded_at = collection.count_documents({"loaded_at": {"$exists": False}})
    indexes = collection.index_information()
    spatial = [name for name, info in indexes.items() if ("geometry", "2dsphere") in info.get("key", [])]

    # Un punto dentro de un municipio cargado tiene que devolver ese municipio por el índice.
    sample = documents[0]
    point = shape(sample["geometry"]).representative_point()
    query = {"geometry": {"$geoIntersects": {"$geometry": {"type": "Point", "coordinates": [point.x, point.y]}}}}
    hits = sorted(doc["_id"] for doc in collection.find(query, {"_id": 1}))
    plan = collection.find(query).explain().get("queryPlanner", {}).get("winningPlan", {})

    def uses_index(node) -> bool:
        if isinstance(node, dict):
            return node.get("indexName") in spatial or any(uses_index(v) for v in node.values())
        if isinstance(node, list):
            return any(uses_index(v) for v in node)
        return False

    checks = {
        "count": len(stored_ids) == expected_count,
        "ids_match_input": stored_ids == expected_ids,
        "no_duplicate_ids": len(stored_ids) == len(set(stored_ids)),
        "no_duplicate_name_dpto": not duplicates,
        "schema_valid": not schema_violations,
        "loaded_at_present": missing_loaded_at == 0,
        "spatial_index": bool(spatial),
        "geo_query_hits_sample": sample["_id"] in hits,
        "geo_query_uses_index": uses_index(plan),
    }
    return {
        "checks": checks,
        "ok": all(checks.values()),
        "stored_count": len(stored_ids),
        "schema_violations": schema_violations,
        "duplicate_name_dpto": [d["_id"] for d in duplicates],
        "spatial_indexes": spatial,
        "sample_query": {"_id": sample["_id"], "point": [point.x, point.y], "hits": hits},
    }


def load(db, documents: list[dict], *, expected_count: int, expected_ids: list[str] | None,
         source_file: str, prune: bool = False) -> dict:
    """Carga completa sobre ``db``. La usa main() y --self-check."""
    started = datetime.now(timezone.utc)
    result: dict = {"started_at": started.isoformat(), "rows_read": len(documents)}
    check_documents(documents, expected_count=expected_count, expected_ids=expected_ids)
    subregions = subregions_from(documents)
    result["indexes"] = ensure_schema(db)
    collection = db[COLLECTION]

    operations, summary = plan_operations(collection, documents, started, prune=prune)
    rejected: list[dict] = []
    if operations:
        try:
            collection.bulk_write(operations, ordered=False)
        except BulkWriteError as exc:
            rejected = write_errors(exc)
    rejected_ids = {item["_id"] for item in rejected}
    result.update({
        "inserted": len([c for c in summary["insert"] if c not in rejected_ids]),
        "replaced": len([c for c in summary["replace"] if c not in rejected_ids]),
        "unchanged": len(summary["unchanged"]),
        "deleted": len(summary["delete"]),
        "extra_in_db": summary["extra_in_db"],
        "rejected": rejected,
    })

    sub_ops = [ReplaceOne({"_id": item["_id"]}, item, upsert=True) for item in subregions]
    sub_result = db[SUBREGIONS].bulk_write(sub_ops, ordered=False)
    result["subregions"] = {
        "count": len(subregions),
        "upserted": sub_result.upserted_count,
        "modified": sub_result.modified_count,
    }

    verification = verify_collection(collection, documents, expected_count=expected_count)
    result["verification"] = verification
    finished = datetime.now(timezone.utc)
    ok = verification["ok"] and not rejected and (prune or not summary["extra_in_db"])
    notes = (
        f"insertados {result['inserted']}, reemplazados {result['replaced']}, "
        f"sin cambios {result['unchanged']}, borrados {result['deleted']}, rechazados {len(rejected)}"
    )
    if summary["extra_in_db"] and not prune:
        notes += f"; en la base hay _id fuera de la entrada: {summary['extra_in_db']} (use --prune)"
    run = db[RUNS].insert_one({
        "dataset_id": RUN_DATASET_ID,
        "source_file": source_file,
        "rows_read": len(documents),
        "rows_loaded": result["inserted"] + result["replaced"] + result["unchanged"],
        "rows_rejected": len(rejected),
        "started_at": started,
        "finished_at": finished,
        "notes": notes,
    })
    result.update({
        "run_id": str(run.inserted_id),
        "finished_at": finished.isoformat(),
        "duration_s": round((finished - started).total_seconds(), 3),
        "notes": notes,
        "status": "loaded" if ok else "verification_failed",
    })
    return result


# ---------------------------------------------------------------- CLI


def connect(config: dict) -> MongoClient:
    client = MongoClient(os.environ.get("MONGO_URI", config["mongo"]["uri"]),
                         serverSelectionTimeoutMS=5000, tz_aware=True)
    client.admin.command("ping")
    return client


def run_real(args) -> int:
    config = load_config(ROOT)
    outputs = ROOT / config["paths"]["outputs"]
    report_path = outputs / "municipalities_load_report.json"
    input_path = ROOT / config["paths"]["processed_data"] / "municipalities.geojsonl"
    expected_count = int(config["sources"]["pdet_list"]["expected_municipalities"])
    report: dict = {
        "contract": CONTRACT_VERSION,
        "role": "load-report",
        "fixture": False,
        "database": config["mongo"]["database"],
        "collection": COLLECTION,
        "input_geojsonl": input_path.relative_to(ROOT).as_posix(),
        "prune": args.prune,
        "status": "blocked",
    }
    try:
        prepare_path = outputs / "municipalities_prepare_report.json"
        if not prepare_path.is_file():
            raise LoadError("no existe outputs/municipalities_prepare_report.json")
        prepare = json.loads(prepare_path.read_text(encoding="utf-8"))
        if not input_path.is_file():
            raise LoadError(f"no existe {report['input_geojsonl']}; corra antes 02_prepare_municipalities.py")
        report.update(check_prepare_report(prepare, input_path, ROOT, allow_mismatch=args.allow_input_mismatch))
        documents = read_geojsonl(input_path)
        with connect(config) as client:
            db = client[config["mongo"]["database"]]
            report["mongo_version"] = client.server_info().get("version")
            report.update(load(db, documents, expected_count=expected_count,
                               expected_ids=prepare.get("ids"), source_file=report["input_geojsonl"],
                               prune=args.prune))
    except (LoadError, ContractError) as exc:
        report["error"] = str(exc)
        write_json(report_path, report)
        print(f"[FALLA] {exc}", file=sys.stderr)
        return 1
    except PyMongoError as exc:
        # No se imprime la excepción completa: puede traer la URI con la clave.
        report.update(status="operational_error", error=type(exc).__name__)
        write_json(report_path, report)
        print(f"[FALLA] error de MongoDB: {type(exc).__name__}", file=sys.stderr)
        return 2

    write_json(report_path, report)
    for name, ok in report["verification"]["checks"].items():
        print(f"[{'OK' if ok else 'FALLA'}] {name}")
    print(
        f"[{report['status']}] {report['notes']}; colección con "
        f"{report['verification']['stored_count']} documentos; reporte en "
        f"{report_path.relative_to(ROOT).as_posix()}"
    )
    for item in report["rejected"][:10]:
        print(f"  rechazado {item['_id']}: código {item['code']} {item['message'][:160]}", file=sys.stderr)
    return 0 if report["status"] == "loaded" else 1


# ---------------------------------------------------------------- self-check


def _square(code: str, subregion: int, x: float, y: float) -> dict:
    ring = [[x, y], [x + 0.1, y], [x + 0.1, y + 0.1], [x, y + 0.1], [x, y]]
    return {
        "_id": code, "name": f"SINTETICO {code}", "dpto_code": code[:2], "dpto_name": "SINTETICO",
        "subregion_id": subregion, "subregion_name": f"SUBREGION {subregion}", "area_km2": 123.0,
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "source": {"dataset": "MGN", "version": "2025", "file": "fixture"},
    }


def run_self_check() -> int:
    """Pruebas contra MongoDB real en una base temporal que se borra al final."""
    config = load_config(ROOT)
    results: list[tuple[str, bool]] = []

    def check(name: str, condition: bool) -> None:
        results.append((name, bool(condition)))
        print(f"[{'OK' if condition else 'FALLA'}] {name}")

    def rejected_with(insert, code: int) -> bool:
        try:
            insert()
        except PyMongoError as exc:
            return getattr(exc, "code", None) == code
        return False

    def raises_load_error(call) -> bool:
        try:
            call()
        except LoadError:
            return True
        return False

    docs = [_square("19050", 1, -76.0, 2.0), _square("19075", 1, -75.0, 2.0), _square("05031", 3, -75.0, 7.0)]
    ids = [d["_id"] for d in docs]
    name = f"load_selfcheck_{uuid.uuid4().hex[:12]}"
    try:
        client = connect(config)
    except PyMongoError as exc:
        print(f"[FALLA] no hay MongoDB para el self-check: {type(exc).__name__}", file=sys.stderr)
        return 2
    with client:
        if name in client.list_database_names():
            print("[FALLA] la base temporal ya existía", file=sys.stderr)
            return 2
        db = client[name]
        coll = db[COLLECTION]
        now = datetime.now(timezone.utc)

        def run(documents, **kwargs):
            return load(db, documents, expected_count=3, expected_ids=ids, source_file="fixture", **kwargs)

        try:
            first = run(docs)
            check("primera carga: 3 insertados y verificación OK",
                  first["inserted"] == 3 and first["status"] == "loaded")
            stamps = {d["_id"]: d["loaded_at"] for d in coll.find({}, {"loaded_at": 1})}

            second = run(docs)
            check("segunda carga idéntica: 0 insertados, 0 reemplazados, 3 sin cambios",
                  (second["inserted"], second["replaced"], second["unchanged"]) == (0, 0, 3))
            check("repetir la carga no duplica: siguen 3 documentos", coll.count_documents({}) == 3)
            check("repetir la carga no cambia loaded_at de lo que no cambió",
                  stamps == {d["_id"]: d["loaded_at"] for d in coll.find({}, {"loaded_at": 1})})

            changed = [dict(d) for d in docs]
            changed[0] = {**changed[0], "area_km2": 999.0}
            third = run(changed)
            check("un documento que cambió se reemplaza, no se duplica",
                  third["replaced"] == 1 and coll.count_documents({}) == 3
                  and coll.find_one({"_id": "19050"})["area_km2"] == 999.0)
            check("pdet_subregions queda con conteos derivados",
                  db[SUBREGIONS].count_documents({}) == 2
                  and db[SUBREGIONS].find_one({"_id": 1})["municipality_count"] == 2)
            check("cada corrida queda en ingestion_runs",
                  db[RUNS].count_documents({"dataset_id": RUN_DATASET_ID}) == 3)

            check("un _id repetido en la entrada detiene la carga",
                  raises_load_error(lambda: run(docs + [docs[0]])))
            with_loaded = [dict(d) for d in docs]
            with_loaded[0]["loaded_at"] = "2026-01-01"
            check("una entrada que ya trae loaded_at se rechaza",
                  raises_load_error(lambda: run(with_loaded)))

            check("el validador $jsonSchema rechaza un _id de 4 dígitos (código 121)",
                  rejected_with(lambda: coll.insert_one({**docs[0], "_id": "1905", "loaded_at": now}), 121))
            check("el validador $jsonSchema rechaza un documento sin loaded_at (código 121)",
                  rejected_with(lambda: coll.insert_one({**docs[0], "_id": "99003", "dpto_code": "99"}), 121))
            bowtie = {"type": "Polygon", "coordinates": [[[-70, 3], [-69, 4], [-69, 3], [-70, 4], [-70, 3]]]}
            check("el índice 2dsphere rechaza un polígono que se auto-intersecta (código 16755)",
                  rejected_with(lambda: coll.insert_one({**docs[0], "_id": "99001", "dpto_code": "99",
                                                         "loaded_at": now, "geometry": bowtie}), 16755))
            check("el índice _id rechaza insertar un municipio ya cargado (código 11000)",
                  rejected_with(lambda: coll.insert_one({**docs[1], "loaded_at": now}), 11000))

            coll.insert_one({**docs[0], "_id": "99002", "dpto_code": "99", "loaded_at": now})
            stale = run(docs)
            check("un _id ajeno en la base se reporta y sin --prune la carga no se da por buena",
                  stale["extra_in_db"] == ["99002"] and stale["status"] != "loaded")
            pruned = run(docs, prune=True)
            check("con --prune se borra y la carga queda verificada",
                  pruned["deleted"] == 1 and pruned["status"] == "loaded" and coll.count_documents({}) == 3)
        finally:
            client.drop_database(name)
        check("la base temporal se borró", name not in client.list_database_names())

    passed = sum(ok for _, ok in results)
    print(f"Self-check: {passed}/{len(results)} OK")
    return 0 if passed == len(results) else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--prune", action="store_true",
                        help="borrar de municipalities los _id que no están en la entrada")
    parser.add_argument("--allow-input-mismatch", action="store_true",
                        help="cargar aunque el sha256 del GeoJSONL no sea el del reporte de preparación "
                             "(queda registrado en el reporte)")
    parser.add_argument("--self-check", action="store_true",
                        help="probar la carga en una base temporal de MongoDB")
    args = parser.parse_args(argv)
    if args.self_check:
        return run_self_check()
    return run_real(args)


if __name__ == "__main__":
    sys.exit(main())
