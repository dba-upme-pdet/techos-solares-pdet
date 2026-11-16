"""Carga las huellas preparadas de la Entrega 3 en ``buildings`` (tramo de José).

Entrada: el reporte de preparación de ``03_prepare_buildings.py``
(``outputs/buildings_<fuente>_prepare_report.json``) y los GeoJSON Lines con
gzip por partición que ese reporte declara. No vuelve a preparar ni a filtrar:
solo carga lo que el contrato ``entrega3-buildings-v1`` ya declaró listo.

Por cada partición, en lotes de ``processing.batch_size`` documentos:

1. Verifica el SHA256 y los bytes del archivo contra el reporte; sin eso no
   se toca la base.
2. Lee cada línea, valida el registro sin ``run_id`` con
   ``entrega3_contracts.prepared_record_errors`` y agrega ``run_id``: el
   ``ObjectId`` del documento de ``ingestion_runs`` de esa partición.
3. Escribe con ``UpdateOne(..., $setOnInsert: {run_id})`` y un ``_id``
   determinista ``<dataset_id>:<blake2b-96(source_ref)>``. Reintentar la carga
   actualiza atributos si cambiaron, no duplica y conserva el ``run_id``
   original de lo que ya estaba.
4. Registra la fuente en ``datasets`` y la corrida de la partición en
   ``ingestion_runs`` (``source_file`` = ``input.local_path``, leídas,
   cargadas y rechazadas).
5. Al terminar crea los índices de ``00_init_db.py`` para ``buildings``:
   ``centroid_2dsphere`` y ``dataset_id_1_mpio_code_1``.

Uso:
    python scripts/04_load_buildings.py --source ms
    python scripts/04_load_buildings.py --source google --passes 2
        # dos pasadas: la segunda debe insertar 0 y dejar el mismo conteo
    python scripts/04_load_buildings.py --source ms --partitions 032212332
        # muestra; el reporte queda en sample_only y no acredita la carga completa
    python scripts/04_load_buildings.py --self-check
        # pruebas en una base temporal de MongoDB

Salida: 0 carga verificada, 1 falla de datos o verificación, 2 error operativo.
MONGO_URI reemplaza la URI de config.yaml.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from bson import ObjectId
from pymongo import ASCENDING, GEOSPHERE, MongoClient, UpdateOne
from pymongo.errors import BulkWriteError, PyMongoError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from entrega2_contracts import (  # noqa: E402
    CONTRACT_VERSION as ENTREGA2_CONTRACT,
    ContractError,
    load_config,
    sha256_file,
    write_json,
)
from entrega3_contracts import (  # noqa: E402
    CONTRACT_VERSION,
    prepared_record_errors,
)

_spec = importlib.util.spec_from_file_location("init_db", ROOT / "scripts" / "00_init_db.py")
init_db = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(init_db)

COLLECTION = "buildings"
DATASETS = "datasets"
RUNS = "ingestion_runs"
SCRIPT_VERSION = "entrega3-load-v1"
BUILDING_INDEXES = init_db.BUILDING_INDEXES["buildings"]
# --source usa el dataset_id del contrato; config.yaml nombra la sección de Microsoft.
SOURCE_CONFIG = {"ms": "microsoft", "google": "google"}


class LoadError(Exception):
    """La entrada o la base no permiten declarar la carga."""


# ---------------------------------------------------------------- entrada


def building_id(dataset_id: str, source_ref: str) -> str:
    """``_id`` determinista: la misma huella siempre cae en el mismo documento.

    El 96 bits de blake2b hacen que una colisión entre ~5 millones de
    ``source_ref`` sea despreciable, y el ``_id`` sirve de clave idempotente
    sin un índice único secundario.
    """
    digest = hashlib.blake2b(f"{dataset_id}\x00{source_ref}".encode("utf-8"), digest_size=12).hexdigest()
    return f"{dataset_id}:{digest}"


def check_prepare_report(report: dict, dataset_id: str) -> dict:
    """Compuerta del contrato: sin ``ready_for_load`` y selección PDET no se carga."""
    problems = []
    if report.get("contract") != CONTRACT_VERSION:
        problems.append(f"contrato {report.get('contract')!r}, se esperaba {CONTRACT_VERSION!r}")
    if report.get("dataset_id") != dataset_id:
        problems.append(f"dataset_id {report.get('dataset_id')!r}, se esperaba {dataset_id!r}")
    if report.get("status") != "ready_for_load":
        problems.append(f"el reporte de preparación está en estado {report.get('status')!r}")
    if report.get("claims_pdet_selection") is not True:
        problems.append("el reporte no declara la selección PDET completa")
    if report.get("claims_full_source") is not True:
        problems.append("el reporte no declara la fuente completa")
    totals = report.get("totals") or {}
    if totals.get("balanced") is not True:
        problems.append("el reporte de preparación no cierra el balance de filas")
    if not report.get("partitions"):
        problems.append("el reporte no trae particiones")
    if problems:
        raise LoadError("; ".join(problems))
    return {
        "contract": report["contract"],
        "report_dataset_id": report["dataset_id"],
        "prepared_total": int(totals.get("prepared", 0)),
        "partitions": len(report["partitions"]),
    }


def partition_entries(report: dict, root: Path, wanted: set[str] | None) -> list[dict]:
    """Particiones del reporte, con su archivo verificado por SHA256 y bytes."""
    entries = []
    for part in sorted(report["partitions"], key=lambda p: str(p.get("partition_id"))):
        pid = str(part.get("partition_id"))
        if wanted is not None and pid not in wanted:
            continue
        output = part.get("output") or {}
        rel = output.get("path")
        if not rel:
            raise LoadError(f"partición {pid} sin output.path")
        path = root / rel
        if not path.is_file():
            raise LoadError(f"falta {rel}; vuelva a correr 03_prepare_buildings.py")
        digest = sha256_file(path)
        if digest != output.get("sha256"):
            raise LoadError(f"el SHA256 de {rel} no coincide con el reporte de preparación")
        if output.get("bytes") is not None and path.stat().st_size != output["bytes"]:
            raise LoadError(f"los bytes de {rel} no coinciden con el reporte de preparación")
        entries.append({
            "partition_id": pid,
            "path": path,
            "local_path": rel,
            "sha256": digest,
            "bytes": path.stat().st_size,
            "declared_records": int(output.get("records", 0)),
            "source_file": (part.get("input") or {}).get("local_path"),
            "excluded_outside_pdet": int(part.get("excluded_outside_pdet", 0)),
            "prepare_rejected": int(part.get("rejected", 0)),
        })
    if wanted is not None:
        found = {entry["partition_id"] for entry in entries}
        missing = wanted - found
        if missing:
            raise LoadError(f"particiones que no están en el reporte: {sorted(missing)}")
    if not entries:
        raise LoadError("el reporte no deja particiones para cargar")
    return entries


def iter_prepared(path: Path):
    """``(número_de_línea, texto)`` del GeoJSONL con gzip, sin cargarlo entero."""
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if line.strip():
                yield number, line


def prepared_document(line: str, dataset_id: str) -> tuple[dict | None, str, str]:
    """Registro listo para insertar, o ``(None, motivo, detalle)``.

    No modifica el archivo preparado: el ``_id`` y el ``run_id`` los agrega la
    carga, que es exactamente el límite del contrato.
    """
    try:
        record = json.loads(line)
    except json.JSONDecodeError as exc:
        return None, "json_invalid", str(exc)[:200]
    if not isinstance(record, dict):
        return None, "not_an_object", type(record).__name__
    if record.get("dataset_id") != dataset_id:
        return None, "dataset_mismatch", repr(record.get("dataset_id"))
    if "_id" in record:
        return None, "id_from_prepare", "el registro preparado ya trae _id"
    errors = prepared_record_errors(record)
    if errors:
        return None, "contract_violation", "; ".join(errors)[:400]
    source_ref = record.get("source_ref")
    if not isinstance(source_ref, str) or not source_ref:
        return None, "missing_source_ref", repr(source_ref)
    return record, "", ""


def batches(iterable, size: int):
    batch: list = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


# ---------------------------------------------------------------- base


def connect(config: dict) -> MongoClient:
    client = MongoClient(os.environ.get("MONGO_URI", config["mongo"]["uri"]),
                         serverSelectionTimeoutMS=5000, tz_aware=True)
    client.admin.command("ping")
    return client


def ensure_collections(db) -> None:
    """Validador de ``buildings`` y colecciones de registro, sin copiar el esquema."""
    existing = set(db.list_collection_names())
    for name in (COLLECTION, DATASETS, RUNS):
        validator = {"$jsonSchema": {"bsonType": "object", **init_db.SCHEMAS[name]}}
        if name in existing:
            db.command("collMod", name, validator=validator, validationLevel="moderate",
                       validationAction="error")
        else:
            db.create_collection(name, validator=validator, validationLevel="moderate",
                                 validationAction="error")
    for keys, name in init_db.SMALL_INDEXES[RUNS]:
        db[RUNS].create_index(keys, name=name)


def ensure_building_indexes(db) -> dict:
    """Índices de ``00_init_db.py`` para buildings; crear el 2dsphere después de cargar."""
    info = {}
    for keys, name in BUILDING_INDEXES:
        db[COLLECTION].create_index(keys, name=name)
        info[name] = [list(key) for key in keys]
    return info


def dataset_document(report: dict) -> dict:
    doc = dict(report.get("datasets_document") or {})
    missing = [key for key in ("_id", "name", "version", "license", "url", "accessed_at") if not doc.get(key)]
    if missing:
        raise LoadError(f"datasets_document sin {missing}")
    accessed = doc["accessed_at"]
    if isinstance(accessed, str):
        try:
            doc["accessed_at"] = datetime.fromisoformat(accessed.replace("Z", "+00:00"))
        except ValueError as exc:
            raise LoadError(f"accessed_at no es ISO 8601: {accessed!r}") from exc
    return doc


def upsert_dataset(db, report: dict) -> dict:
    doc = dataset_document(report)
    update = {key: value for key, value in doc.items() if key != "_id"}
    db[DATASETS].update_one({"_id": doc["_id"]}, {"$set": update}, upsert=True)
    return {"_id": doc["_id"], "name": doc["name"], "version": doc["version"],
            "license": doc["license"], "url": doc["url"],
            "accessed_at": doc["accessed_at"].isoformat()}


def write_batch(collection, documents: list[dict], run_id: ObjectId) -> dict:
    """Upsert idempotente de un lote; aísla los documentos que el validador rechace."""
    stats = {"inserted": 0, "updated": 0, "unchanged": 0, "rejected": []}
    pending = documents
    while pending:
        operations = [
            UpdateOne(
                {"_id": doc["_id"]},
                {"$set": {key: value for key, value in doc.items() if key != "run_id"},
                 "$setOnInsert": {"run_id": run_id}},
                upsert=True,
            )
            for doc in pending
        ]
        try:
            result = collection.bulk_write(operations, ordered=False)
            stats["inserted"] += result.upserted_count
            stats["updated"] += result.modified_count
            stats["unchanged"] += result.matched_count - result.modified_count
            return stats
        except BulkWriteError as exc:
            errors = exc.details.get("writeErrors") or []
            bad = {int(error["index"]) for error in errors if "index" in error}
            if not bad:
                raise
            for index in sorted(bad):
                error = next(e for e in errors if int(e.get("index", -1)) == index)
                doc = pending[index]
                stats["rejected"].append({
                    "_id": doc.get("_id"),
                    "source_ref": doc.get("source_ref"),
                    "code": error.get("code"),
                    "reason": "mongo_write_error",
                    "detail": str(error.get("errmsg"))[:400],
                })
            pending = [doc for index, doc in enumerate(pending) if index not in bad]
    return stats


def load_partition(db, entry: dict, dataset_id: str, *, batch_size: int, reject_log) -> dict:
    """Carga una partición y deja su corrida en ``ingestion_runs``."""
    run_id = ObjectId()
    started = datetime.now(timezone.utc)
    run = {
        "_id": run_id,
        "dataset_id": dataset_id,
        "source_file": entry["source_file"] or entry["local_path"],
        "rows_read": 0,
        "rows_loaded": 0,
        "rows_rejected": 0,
        "started_at": started,
        "finished_at": started,
        "notes": "carga en curso",
        "partition_id": entry["partition_id"],
        "prepared_file": entry["local_path"],
        "prepared_sha256": entry["sha256"],
    }
    db[RUNS].insert_one(run)
    stats = {"read": 0, "inserted": 0, "updated": 0, "unchanged": 0,
             "rejected": 0, "rejected_by_reason": {}, "write_rejected": 0}
    collection = db[COLLECTION]
    interrupted = None
    try:
        for lines in batches(iter_prepared(entry["path"]), batch_size):
            documents = []
            for number, line in lines:
                stats["read"] += 1
                record, reason, detail = prepared_document(line, dataset_id)
                if record is None:
                    stats["rejected"] += 1
                    stats["rejected_by_reason"][reason] = stats["rejected_by_reason"].get(reason, 0) + 1
                    reject_log.write(json.dumps({
                        "partition_id": entry["partition_id"], "line": number,
                        "reason": reason, "detail": detail,
                    }, ensure_ascii=False) + "\n")
                    continue
                source_ref = record["source_ref"]
                record["_id"] = building_id(dataset_id, source_ref)
                record["run_id"] = run_id
                documents.append(record)
            if not documents:
                continue
            result = write_batch(collection, documents, run_id)
            stats["inserted"] += result["inserted"]
            stats["updated"] += result["updated"]
            stats["unchanged"] += result["unchanged"]
            for item in result["rejected"]:
                stats["rejected"] += 1
                stats["write_rejected"] += 1
                stats["rejected_by_reason"]["mongo_write_error"] = (
                    stats["rejected_by_reason"].get("mongo_write_error", 0) + 1)
                reject_log.write(json.dumps({**item, "partition_id": entry["partition_id"]},
                                            ensure_ascii=False) + "\n")
    except BaseException as exc:  # deja la corrida marcada aunque se interrumpa
        interrupted = type(exc).__name__
        raise
    finally:
        finished = datetime.now(timezone.utc)
        loaded = stats["inserted"] + stats["updated"] + stats["unchanged"]
        notes = (
            f"insertados {stats['inserted']}, actualizados {stats['updated']}, "
            f"sin cambios {stats['unchanged']}, rechazados {stats['rejected']}; "
            f"excluidos fuera de PDET en la preparación {entry['excluded_outside_pdet']}"
        )
        if interrupted:
            notes = f"interrumpida ({interrupted}); " + notes
        db[RUNS].update_one({"_id": run_id}, {"$set": {
            "rows_read": stats["read"],
            "rows_loaded": loaded,
            "rows_rejected": stats["rejected"],
            "finished_at": finished,
            "notes": notes,
        }})
    return {
        "partition_id": entry["partition_id"],
        "prepared_file": entry["local_path"],
        "prepare_sha256": entry["sha256"],
        "bytes": entry["bytes"],
        "declared_records": entry["declared_records"],
        "run_id": str(run_id),
        "read": stats["read"],
        "loaded": stats["inserted"] + stats["updated"] + stats["unchanged"],
        "inserted": stats["inserted"],
        "updated": stats["updated"],
        "unchanged": stats["unchanged"],
        "rejected": stats["rejected"],
        "rejected_by_reason": dict(sorted(stats["rejected_by_reason"].items())),
        "seconds": round((finished - started).total_seconds(), 2),
    }


# ---------------------------------------------------------------- verificación


def _winning_stages(plan: dict) -> list[dict]:
    stages, node = [], plan
    while isinstance(node, dict) and node:
        stages.append(node)
        node = node.get("inputStage")
    return stages


def expected_municipality_codes(root: Path, source_cfg: dict) -> set[str] | None:
    """Códigos con al menos una edificación preparada, según el CSV de la preparación."""
    path = root / source_cfg.get("prepare_by_municipality", "")
    if not path.is_file():
        return None
    import csv

    with path.open(encoding="utf-8", newline="") as handle:
        return {row["mpio_code"] for row in csv.DictReader(handle)
                if int(row.get("prepared_buildings") or 0) > 0}


def verify_collection(db, dataset_id: str, expected_total: int | None,
                      expected_codes: set[str] | None) -> dict:
    collection = db[COLLECTION]
    total = collection.count_documents({"dataset_id": dataset_id})
    codes = sorted(collection.distinct("mpio_code", {"dataset_id": dataset_id}))
    codes = [code for code in codes if code]
    indexes = collection.index_information()
    spatial = [name for name, info in indexes.items() if ("centroid", "2dsphere") in info.get("key", [])]
    dataset = db[DATASETS].find_one({"_id": dataset_id})
    duplicates = list(collection.aggregate([
        {"$match": {"dataset_id": dataset_id}},
        {"$group": {"_id": "$source_ref", "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 1}}},
        {"$limit": 5},
    ], allowDiskUse=True))
    # El borde compartido puede devolver de más (se asigna al código menor),
    # pero nunca de menos: lo asignado tiene que estar dentro del municipio.
    sample_code = collection.find_one({"dataset_id": dataset_id, "mpio_code": {"$ne": None}},
                                      {"mpio_code": 1}, sort=[("mpio_code", ASCENDING)])
    sample = db["municipalities"].find_one({"_id": sample_code["mpio_code"]}) if sample_code else None
    spatial_check = {"municipality": None, "assigned": 0, "geo_within": 0,
                     "index_used": False, "ok": False}
    if sample:
        assigned = collection.count_documents({"dataset_id": dataset_id, "mpio_code": sample["_id"]})
        query = {"centroid": {"$geoWithin": {"$geometry": sample["geometry"]}}}
        geo_within = collection.count_documents({**query, "dataset_id": dataset_id})
        plan = collection.find(query).explain().get("queryPlanner", {}).get("winningPlan", {})
        stages = _winning_stages(plan)
        index_used = any(stage.get("stage") == "IXSCAN" and stage.get("indexName") in spatial
                         for stage in stages)
        spatial_check = {
            "municipality": sample["_id"],
            "assigned": assigned,
            "geo_within": geo_within,
            "index_used": index_used,
            "ok": bool(spatial and index_used and assigned > 0 and geo_within >= assigned),
        }

    checks = {
        "no_duplicate_source_refs": not duplicates,
        "count_matches_prepared": expected_total is None or total == expected_total,
        "municipalities_match_preparation": expected_codes is None or set(codes) == expected_codes,
        "dataset_registered": dataset is not None,
        "spatial_index": bool(spatial),
        "spatial_query": spatial_check["ok"] if sample else False,
    }
    return {
        "checks": checks,
        "ok": all(checks.values()),
        "total": total,
        "expected_total": expected_total,
        "duplicate_source_refs": duplicates,
        "municipalities_with_buildings": len(codes),
        "spatial_indexes": spatial,
        "spatial_query": spatial_check,
        "dataset": {k: dataset.get(k) for k in ("_id", "name", "version", "license")} if dataset else None,
    }


# ---------------------------------------------------------------- carga


def load(db, report: dict, entries: list[dict], *, dataset_id: str, batch_size: int,
         passes: int, reject_path: Path, full_source: bool,
         expected_codes: set[str] | None = None) -> dict:
    """Carga las particiones ``passes`` veces y devuelve el resultado verificable."""
    started = datetime.now(timezone.utc)
    ensure_collections(db)
    dataset = upsert_dataset(db, report)
    collection = db[COLLECTION]
    before = collection.count_documents({"dataset_id": dataset_id})
    # Una carga completa deja exactamente los registros preparados: el _id
    # determinista hace que repetirla reescriba los mismos documentos.
    expected_total = sum(entry["declared_records"] for entry in entries) if full_source else None
    expected_codes = None if not full_source else expected_codes

    reject_path.parent.mkdir(parents=True, exist_ok=True)
    run_passes = []
    rejected_samples = []
    with reject_path.open("w", encoding="utf-8", newline="\n") as reject_log:
        for pass_no in range(1, passes + 1):
            pass_started = datetime.now(timezone.utc)
            parts = []
            for entry in entries:
                result = load_partition(db, entry, dataset_id, batch_size=batch_size,
                                        reject_log=reject_log)
                parts.append(result)
                print(f"[pasada {pass_no}] {result['partition_id']}: leídas {result['read']} "
                      f"insertadas {result['inserted']} actualizadas {result['updated']} "
                      f"sin cambios {result['unchanged']} rechazadas {result['rejected']} "
                      f"({result['seconds']} s)", flush=True)
                if len(rejected_samples) < 20 and result["rejected"]:
                    rejected_samples.append({k: result[k] for k in
                                             ("partition_id", "rejected", "rejected_by_reason")})
            pass_finished = datetime.now(timezone.utc)
            run_passes.append({
                "pass": pass_no,
                "started_at": pass_started.isoformat(timespec="seconds"),
                "finished_at": pass_finished.isoformat(timespec="seconds"),
                "seconds": round((pass_finished - pass_started).total_seconds(), 2),
                "read": sum(p["read"] for p in parts),
                "loaded": sum(p["loaded"] for p in parts),
                "inserted": sum(p["inserted"] for p in parts),
                "updated": sum(p["updated"] for p in parts),
                "unchanged": sum(p["unchanged"] for p in parts),
                "rejected": sum(p["rejected"] for p in parts),
                "collection_total": collection.count_documents({"dataset_id": dataset_id}),
                "partitions": parts,
            })

    indexes = ensure_building_indexes(db)
    verification = verify_collection(db, dataset_id, expected_total, expected_codes)
    finished = datetime.now(timezone.utc)
    first, last = run_passes[0], run_passes[-1]
    idempotent = None
    if passes >= 2:
        idempotent = (
            last["inserted"] == 0
            and last["collection_total"] == first["collection_total"]
            and last["read"] == first["read"]
        )
        verification["checks"]["rerun_does_not_duplicate"] = idempotent
        verification["ok"] = all(verification["checks"].values())

    total_rejected = sum(p["rejected"] for p in run_passes[-1]["partitions"])
    if not verification["ok"]:
        status = "verification_failed"
    elif total_rejected:
        status = "loaded_with_rejects"
    else:
        status = "loaded"
    return {
        "contract": CONTRACT_VERSION,
        "script": "scripts/04_load_buildings.py",
        "script_version": SCRIPT_VERSION,
        "role": "load-report",
        "dataset_id": dataset_id,
        "status": status,
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": finished.isoformat(timespec="seconds"),
        "duration_s": round((finished - started).total_seconds(), 2),
        "passes_requested": passes,
        "parameters": {"batch_size": batch_size, "passes": passes},
        "dataset": dataset,
        "input": {
            "prepare_report": None,  # lo completa run_real
            "prepare_report_sha256": None,
            "partitions": len(entries),
            "declared_records": sum(entry["declared_records"] for entry in entries),
            "bytes": sum(entry["bytes"] for entry in entries),
        },
        "collection_before": before,
        "collection_after": verification["total"],
        "reject_log": reject_path.relative_to(ROOT).as_posix() if reject_path.is_relative_to(ROOT) else str(reject_path),
        "passes": run_passes,
        "totals": {
            "read": last["read"],
            "loaded": last["loaded"],
            "inserted": sum(p["inserted"] for p in run_passes),
            "updated": last["updated"],
            "unchanged": last["unchanged"],
            "rejected": total_rejected,
            "rejected_samples": rejected_samples,
            "first_pass_inserted": first["inserted"],
            "last_pass_inserted": last["inserted"],
        },
        "indexes": indexes,
        "verification": verification,
        "idempotent": idempotent,
    }


# ---------------------------------------------------------------- CLI


def run_verify(args) -> int:
    """Recalcula la verificación sobre la base ya cargada, sin volver a insertar."""
    config = load_config(ROOT)
    source_cfg = config["sources"][SOURCE_CONFIG[args.source]]
    dataset_id = source_cfg["id"]
    report_path = ROOT / source_cfg["load_report"]
    prepare_path = ROOT / source_cfg["prepare_report"]
    try:
        prepare = json.loads(prepare_path.read_text(encoding="utf-8"))
        check_prepare_report(prepare, dataset_id)
        wanted = {item.strip() for item in args.partitions.split(",") if item.strip()} if args.partitions else None
        entries = partition_entries(prepare, ROOT, wanted)
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {
            "dataset_id": dataset_id, "role": "load-report"}
        expected = sum(entry["declared_records"] for entry in entries) if wanted is None else None
        with connect(config) as client:
            db = client[config["mongo"]["database"]]
            indexes = ensure_building_indexes(db)
            verification = verify_collection(
                db, dataset_id, expected,
                expected_municipality_codes(ROOT, source_cfg) if wanted is None else None)
            report["mongo_version"] = client.server_info().get("version")
    except (LoadError, ContractError, OSError, json.JSONDecodeError) as exc:
        print(f"[FALLA] {exc}", file=sys.stderr)
        return 1
    except PyMongoError as exc:
        print(f"[FALLA] error de MongoDB: {type(exc).__name__}", file=sys.stderr)
        return 2

    # La reverificación no vuelve a correr las dos pasadas, pero conserva el
    # resultado de idempotencia que la carga real ya midió.
    if (int(report.get("passes_requested") or 1) >= 2
            and report.get("idempotent") is True
            and wanted is None):
        verification["checks"]["rerun_does_not_duplicate"] = True
        verification["ok"] = all(verification["checks"].values())

    rejected = int((report.get("totals") or {}).get("rejected", 0))
    report.update({
        "verification": verification,
        "indexes": indexes,
        "collection_after": verification["total"],
        "verified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": ("verification_failed" if not verification["ok"]
                   else "loaded_with_rejects" if rejected else "loaded"),
    })
    write_json(report_path, report)
    for name, ok in verification["checks"].items():
        print(f"[{'OK' if ok else 'FALLA'}] {name}")
    print(f"[{report['status']}] {verification['total']} documentos de '{dataset_id}'; "
          f"reporte en {report_path.relative_to(ROOT).as_posix()}")
    return 0 if report["status"] in ("loaded", "loaded_with_rejects") else 1


def run_real(args) -> int:
    config = load_config(ROOT)
    source = args.source
    source_cfg = config["sources"][SOURCE_CONFIG[source]]
    dataset_id = source_cfg["id"]
    report_path = ROOT / source_cfg["load_report"]
    prepare_path = ROOT / source_cfg["prepare_report"]
    report: dict = {
        "contract": CONTRACT_VERSION,
        "role": "load-report",
        "dataset_id": dataset_id,
        "database": config["mongo"]["database"],
        "collection": COLLECTION,
        "status": "blocked",
        "dry_run": False,
    }
    try:
        if not prepare_path.is_file():
            raise LoadError(f"no existe {prepare_path.relative_to(ROOT).as_posix()}; "
                            "corra antes 03_prepare_buildings.py")
        prepare = json.loads(prepare_path.read_text(encoding="utf-8"))
        report["gate"] = check_prepare_report(prepare, dataset_id)
        wanted = {item.strip() for item in args.partitions.split(",") if item.strip()} if args.partitions else None
        entries = partition_entries(prepare, ROOT, wanted)
        report["sample_only"] = wanted is not None
        with connect(config) as client:
            db = client[config["mongo"]["database"]]
            result = load(db, prepare, entries, dataset_id=dataset_id,
                          batch_size=args.batch_size or int(config["processing"]["batch_size"]),
                          passes=args.passes,
                          reject_path=ROOT / "data" / "processed" / "buildings" / dataset_id
                          / "load_rejects.jsonl",
                          full_source=wanted is None,
                          expected_codes=expected_municipality_codes(ROOT, source_cfg))
            result["mongo_version"] = client.server_info().get("version")
        result["input"]["prepare_report"] = prepare_path.relative_to(ROOT).as_posix()
        result["input"]["prepare_report_sha256"] = sha256_file(prepare_path)
        report.update(result)
        if wanted is not None:
            report["status"] = "sample_only"
    except (LoadError, ContractError) as exc:
        report["error"] = str(exc)
        write_json(report_path, report)
        print(f"[FALLA] {exc}", file=sys.stderr)
        return 1
    except PyMongoError as exc:
        report.update(status="operational_error", error=type(exc).__name__)
        write_json(report_path, report)
        print(f"[FALLA] error de MongoDB: {type(exc).__name__}", file=sys.stderr)
        return 2

    write_json(report_path, report)
    for name, ok in report["verification"]["checks"].items():
        print(f"[{'OK' if ok else 'FALLA'}] {name}")
    print(f"[{report['status']}] {report['collection_after']} documentos de '{dataset_id}' en "
          f"{report['duration_s']} s; reporte en {report_path.relative_to(ROOT).as_posix()}")
    return 0 if report["status"] in ("loaded", "loaded_with_rejects") else 1


# ---------------------------------------------------------------- self-check


def _square(x: float, y: float, size: float = 0.001) -> dict:
    ring = [[x, y], [x + size, y], [x + size, y + size], [x, y + size], [x, y]]
    return {"type": "Polygon", "coordinates": [ring]}


def _record(dataset_id: str, ref: str, code: str | None, x: float, y: float) -> dict:
    return {
        "dataset_id": dataset_id,
        "source_ref": ref,
        "footprint": _square(x, y),
        "centroid": {"type": "Point", "coordinates": [x + 0.0005, y + 0.0005]},
        "area_m2": 12100.0,
        "area_src_m2": None,
        "confidence": None,
        "height_m": None,
        "mpio_code": code,
    }


def _write_prepared(path: Path, records: list[dict], extra: list[str] | None = None) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        for line in extra or []:
            handle.write(line + "\n")
    return sha256_file(path)


def run_self_check() -> int:
    """Pruebas contra MongoDB real en una base temporal que se borra al final."""
    config = load_config(ROOT)
    results: list[tuple[str, bool]] = []

    def check(name: str, condition: bool) -> None:
        results.append((name, bool(condition)))
        print(f"[{'OK' if condition else 'FALLA'}] {name}")

    name = f"upme_pdet_load_selfcheck_{uuid.uuid4().hex[:8]}"
    try:
        client = connect(config)
    except PyMongoError as exc:
        print(f"[FALLA] no hay MongoDB para el self-check: {type(exc).__name__}", file=sys.stderr)
        return 2
    with client, __import__("tempfile").TemporaryDirectory() as tmp:
        db = client[name]
        dataset_id = "ms"
        municipality = {"_id": "05001", "name": "SINTETICO", "dpto_code": "05", "dpto_name": "ANTIOQUIA",
                        "subregion_id": 1, "subregion_name": "SINTETICA", "area_km2": 100.0,
                        "geometry": _square(-75.6, 6.2, 0.2), "source": {"dataset": "MGN"},
                        "loaded_at": datetime.now(timezone.utc)}
        db["municipalities"].insert_one({**municipality})
        report = {
            "contract": CONTRACT_VERSION,
            "dataset_id": dataset_id,
            "status": "ready_for_load",
            "claims_pdet_selection": True,
            "claims_full_source": True,
            "totals": {"balanced": True, "prepared": 3},
            "datasets_document": {"_id": dataset_id, "name": "MS", "version": "2026-02-03",
                                  "license": "ODbL-1.0", "url": "https://example.invalid/index.csv",
                                  "accessed_at": "2026-11-16T00:00:00+00:00"},
        }
        good = [_record(dataset_id, "032212332/part-a.csv.gz:1", "05001", -75.59, 6.21),
                _record(dataset_id, "032212332/part-a.csv.gz:2", "05001", -75.55, 6.21),
                _record(dataset_id, "032212333/part-b.csv.gz:1", "05001", -75.51, 6.21)]
        extra = ["{no es json", json.dumps({**_record(dataset_id, "x:9", "05001", -75.5, 6.2),
                                            "area_m2": -1})]
        root = Path(tmp)
        first, second = root / "a.jsonl.gz", root / "b.jsonl.gz"
        sha1, sha2 = _write_prepared(first, good[:2], extra), _write_prepared(second, good[2:])
        entries = []
        for pid, path, sha, records in (("032212332", first, sha1, 2), ("032212333", second, sha2, 1)):
            rel = path.relative_to(root).as_posix()
            entries.append({"partition_id": pid, "path": path, "local_path": rel, "sha256": sha,
                            "bytes": path.stat().st_size, "declared_records": records,
                            "source_file": f"data/raw/{pid}.csv.gz", "excluded_outside_pdet": 7,
                            "prepare_rejected": 2})
        report["partitions"] = [{"partition_id": e["partition_id"],
                                 "output": {"path": e["local_path"], "sha256": e["sha256"],
                                            "bytes": e["bytes"], "records": e["declared_records"]},
                                 "input": {"local_path": e["source_file"]},
                                 "excluded_outside_pdet": e["excluded_outside_pdet"],
                                 "rejected": e["prepare_rejected"]} for e in entries]
        try:
            result = load(db, report, entries, dataset_id=dataset_id, batch_size=2, passes=2,
                          reject_path=root / "rejects.jsonl", full_source=True,
                          expected_codes={"05001"})
            coll = db[COLLECTION]
            check("primera pasada inserta 3 y rechaza 2",
                  result["passes"][0]["inserted"] == 3 and result["passes"][0]["rejected"] == 2)
            check("segunda pasada inserta 0 y no cambia el conteo",
                  result["passes"][1]["inserted"] == 0
                  and result["passes"][1]["collection_total"] == 3)
            check("la carga completa queda verificada e idempotente",
                  result["status"] == "loaded_with_rejects" and result["idempotent"] is True
                  and result["verification"]["ok"] is True)
            check("los índices previstos existen",
                  {"centroid_2dsphere", "dataset_id_1_mpio_code_1"} <= set(coll.index_information()))
            check("cada partición deja su corrida en ingestion_runs",
                  db[RUNS].count_documents({"dataset_id": dataset_id}) == 4)
            runs = {run["partition_id"]: run for run in db[RUNS].find({"dataset_id": dataset_id})}
            check("ingestion_runs registra leídas, cargadas y rechazadas",
                  runs["032212332"]["rows_read"] == 4 and runs["032212332"]["rows_rejected"] == 2
                  and runs["032212332"]["rows_loaded"] == 2)
            check("la fuente queda registrada en datasets",
                  db[DATASETS].find_one({"_id": dataset_id})["version"] == "2026-02-03")
            ids = {doc["source_ref"]: doc for doc in coll.find({}, {"source_ref": 1, "run_id": 1})}
            check("el _id determinista evita duplicados de source_ref",
                  len(ids) == 3 and coll.count_documents({}) == 3)
            check("repetir no cambia el run_id de lo ya cargado",
                  result["passes"][0]["partitions"][0]["run_id"]
                  == str(ids[good[0]["source_ref"]]["run_id"]))
            check("un registro sin run_id no pasa el validador",
                  _rejects(lambda: coll.insert_one({k: v for k, v in good[0].items() if k != "run_id"})))
            check("un centroide inválido no pasa el validador",
                  _rejects(lambda: coll.insert_one({**good[0], "run_id": ObjectId(),
                                                    "centroid": {"type": "Point", "coordinates": ["x", 1]}})))
            plan = coll.find({"centroid": {"$geoWithin": {"$geometry": municipality["geometry"]}}}).explain()
            stages = _winning_stages(plan["queryPlanner"]["winningPlan"])
            check("$geoWithin usa centroid_2dsphere (IXSCAN)",
                  any(stage.get("stage") == "IXSCAN" and stage.get("indexName") == "centroid_2dsphere"
                      for stage in stages))
            bad = dict(report, claims_pdet_selection=False)
            check("sin selección PDET la compuerta detiene la carga",
                  _raises(LoadError, lambda: check_prepare_report(bad, dataset_id)))
            sample = dict(report, status="sample_only")
            check("un reporte de muestra no habilita la carga",
                  _raises(LoadError, lambda: check_prepare_report(sample, dataset_id)))
        finally:
            client.drop_database(name)
        check("la base temporal se borró", name not in client.list_database_names())

    passed = sum(ok for _, ok in results)
    print(f"Self-check: {passed}/{len(results)} OK")
    return 0 if passed == len(results) else 1


def _rejects(call) -> bool:
    from pymongo.errors import WriteError

    try:
        call()
    except (WriteError, BulkWriteError):
        return True
    return False


def _raises(exc_type, call) -> bool:
    try:
        call()
    except exc_type:
        return True
    return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", choices=("ms", "google"), help="fuente del contrato a cargar")
    parser.add_argument("--passes", type=int, default=1,
                        help="pasadas completas; con 2 se comprueba que repetir no duplica")
    parser.add_argument("--batch-size", type=int, default=0, help="documentos por bulk_write")
    parser.add_argument("--partitions", help="lista de partition_id separada por comas (muestra)")
    parser.add_argument("--verify-only", action="store_true",
                        help="recalcular la verificación sin volver a cargar")
    parser.add_argument("--self-check", action="store_true",
                        help="probar la carga en una base temporal de MongoDB")
    args = parser.parse_args(argv)
    if args.self_check:
        return run_self_check()
    if not args.source:
        parser.error("--source es obligatorio salvo con --self-check")
    if args.passes < 1:
        parser.error("--passes debe ser >= 1")
    if args.verify_only:
        return run_verify(args)
    return run_real(args)


if __name__ == "__main__":
    sys.exit(main())
