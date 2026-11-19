"""Estadísticas de techos por municipio PDET para una fuente (Entrega 4, tramo de Miguel).

Motor común de cálculo: el mismo código sirve para Microsoft y para Google; la
fuente se elige con ``--source``. Lee ``buildings`` ya cargada por
``04_load_buildings.py`` y escribe un documento por municipio y fuente en
``rooftop_stats`` (``_id = {mpio_code, dataset_id}``).

Método:

1. Filtros de ``config.yaml`` (sección ``analysis``), los mismos para las dos
   fuentes salvo la confianza, que solo se aplica a ``confidence_sources``:
   ``area_m2 >= min_area_m2``, ``area_m2 <= max_area_m2`` (si no es null) y
   ``confidence >= min_confidence``. Cada huella excluida se cuenta por el
   primer filtro que no cumple, en ese orden, para que los motivos sumen el
   total excluido.
2. Una agregación de MongoDB agrupa por ``mpio_code`` (índice
   ``dataset_id_1_mpio_code_1``): huellas antes de filtrar, excluidas por
   motivo y áreas incluidas. La suma, el promedio y la mediana exacta se
   calculan en Python con esas áreas (``$median`` de MongoDB 7 es aproximada).
3. Se escriben los 170 municipios de ``municipalities``, también los que quedan
   sin edificaciones (``building_count = 0``, promedio y mediana ``null``).
   ``ReplaceOne`` con ``upsert`` sobre el ``_id`` compuesto: repetir el cálculo
   reemplaza los mismos 170 documentos y no duplica.
4. Exporta ``outputs/rooftop_stats_<fuente>.csv`` (ordenado por área total) y
   ``outputs/rooftop_stats_<fuente>_report.json`` con fuente, filtros, fecha,
   cantidades incluidas y excluidas, y verificaciones.

Uso:
    python scripts/06_rooftop_stats.py --source ms --passes 2
        # dos pasadas: la segunda debe dejar los mismos 170 documentos y valores
    python scripts/06_rooftop_stats.py --source google
    python scripts/06_rooftop_stats.py --self-check
        # pruebas en una base temporal de MongoDB

Salida: 0 resultado verificado, 1 falla de datos o verificación, 2 error operativo.
MONGO_URI reemplaza la URI de config.yaml.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import math
import os
import statistics
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pymongo import MongoClient, ReplaceOne
from pymongo.errors import PyMongoError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from entrega2_contracts import load_config, sha256_file, write_json  # noqa: E402

_spec = importlib.util.spec_from_file_location("init_db", ROOT / "scripts" / "00_init_db.py")
init_db = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(init_db)

SCRIPT_VERSION = "entrega4-rooftop-stats-v1"
BUILDINGS = "buildings"
MUNICIPALITIES = "municipalities"
# --source usa el dataset_id del contrato; config.yaml nombra la sección de Microsoft.
SOURCE_CONFIG = {"ms": "microsoft", "google": "google"}
REASONS = ("below_min_area", "above_max_area", "low_confidence")
INCLUDED = "included"
CSV_FIELDS = [
    "rank_total_area", "mpio_code", "name", "dpto_code", "dpto_name", "subregion_id",
    "subregion_name", "dataset_id", "building_count", "total_area_m2", "mean_area_m2",
    "median_area_m2", "buildings_before_filters", "excluded_below_min_area",
    "excluded_above_max_area", "excluded_low_confidence", "google_low_coverage", "computed_at",
]


class StatsError(Exception):
    """La base o los filtros no permiten declarar el resultado."""


# ---------------------------------------------------------------- filtros


def filters_for(config: dict, dataset_id: str) -> dict:
    """Filtros que se aplican a la fuente; se guardan tal cual en cada documento."""
    analysis = config["analysis"]
    min_area = float(analysis["min_area_m2"])
    max_area = analysis.get("max_area_m2")
    max_area = None if max_area is None else float(max_area)
    if min_area < 0 or (max_area is not None and max_area <= min_area):
        raise StatsError(f"umbrales de área inválidos: min={min_area}, max={max_area}")
    applies = dataset_id in (analysis.get("confidence_sources") or [])
    min_conf = float(analysis["min_confidence"]) if applies else None
    if min_conf is not None and not 0 <= min_conf <= 1:
        raise StatsError(f"min_confidence fuera de [0, 1]: {min_conf}")
    return {"min_area_m2": min_area, "max_area_m2": max_area, "min_confidence": min_conf}


def exclusion_reason(area_m2: float, confidence: float | None, filters: dict) -> str:
    """Referencia en Python de ``reason_expression``: primer filtro que falla o ``included``."""
    if area_m2 < filters["min_area_m2"]:
        return "below_min_area"
    if filters["max_area_m2"] is not None and area_m2 > filters["max_area_m2"]:
        return "above_max_area"
    if filters["min_confidence"] is not None and (confidence is None or confidence < filters["min_confidence"]):
        return "low_confidence"
    return INCLUDED


def reason_expression(filters: dict) -> dict:
    """Misma regla que ``exclusion_reason`` como expresión de agregación."""
    branches = [{"case": {"$lt": ["$area_m2", filters["min_area_m2"]]}, "then": "below_min_area"}]
    if filters["max_area_m2"] is not None:
        branches.append({"case": {"$gt": ["$area_m2", filters["max_area_m2"]]}, "then": "above_max_area"})
    if filters["min_confidence"] is not None:
        # confidence null o ausente no alcanza el umbral: $ifNull lo vuelve -1.
        branches.append({"case": {"$lt": [{"$ifNull": ["$confidence", -1]}, filters["min_confidence"]]},
                         "then": "low_confidence"})
    return {"$switch": {"branches": branches, "default": INCLUDED}}


def included_query(dataset_id: str, codes: list[str], filters: dict) -> dict:
    """Consulta independiente de la agregación, para verificar el total incluido."""
    area = {"$gte": filters["min_area_m2"]}
    if filters["max_area_m2"] is not None:
        area["$lte"] = filters["max_area_m2"]
    query = {"dataset_id": dataset_id, "mpio_code": {"$in": codes}, "area_m2": area}
    if filters["min_confidence"] is not None:
        query["confidence"] = {"$gte": filters["min_confidence"]}
    return query


def aggregation_pipeline(dataset_id: str, filters: dict) -> list[dict]:
    return [
        {"$match": {"dataset_id": dataset_id}},
        {"$project": {"_id": 0, "mpio_code": 1, "area_m2": 1, "reason": reason_expression(filters)}},
        {"$group": {
            "_id": "$mpio_code",
            "before": {"$sum": 1},
            **{reason: {"$sum": {"$cond": [{"$eq": ["$reason", reason]}, 1, 0]}} for reason in REASONS},
            # $push omite $$REMOVE: solo quedan las áreas incluidas.
            "areas": {"$push": {"$cond": [{"$eq": ["$reason", INCLUDED]}, "$area_m2", "$$REMOVE"]}},
        }},
    ]


# ---------------------------------------------------------------- cálculo


def area_stats(areas: list[float]) -> dict:
    """Conteo, suma, promedio y mediana exacta; promedio y mediana null sin edificaciones."""
    if not areas:
        return {"building_count": 0, "total_area_m2": 0.0, "mean_area_m2": None, "median_area_m2": None}
    total = math.fsum(areas)
    return {
        "building_count": len(areas),
        "total_area_m2": round(total, 2),
        "mean_area_m2": round(total / len(areas), 2),
        "median_area_m2": round(statistics.median(areas), 2),
    }


def build_documents(municipalities: list[dict], groups: list[dict], *, dataset_id: str,
                    filters: dict, computed_at: datetime, low_coverage: set[str]) -> tuple[list[dict], dict]:
    """Un documento por municipio PDET (los 170) y los totales del cálculo."""
    by_code = {group["_id"]: group for group in groups}
    codes = {mpio["_id"] for mpio in municipalities}
    outside = sum(group["before"] for code, group in by_code.items() if code not in codes)
    documents = []
    for mpio in sorted(municipalities, key=lambda item: item["_id"]):
        group = by_code.get(mpio["_id"]) or {"before": 0, "areas": [], **{reason: 0 for reason in REASONS}}
        stats = area_stats(group["areas"])
        excluded = {reason: int(group[reason]) for reason in REASONS}
        if stats["building_count"] + sum(excluded.values()) != group["before"]:
            raise StatsError(f"{mpio['_id']}: incluidas + excluidas no suman las huellas del municipio")
        doc = {
            "_id": {"mpio_code": mpio["_id"], "dataset_id": dataset_id},
            "mpio_code": mpio["_id"],
            "dataset_id": dataset_id,
            "name": mpio.get("name"),
            "dpto_code": mpio.get("dpto_code"),
            "dpto_name": mpio.get("dpto_name"),
            "subregion_id": mpio.get("subregion_id"),
            "subregion_name": mpio.get("subregion_name"),
            **stats,
            "buildings_before_filters": int(group["before"]),
            "excluded": excluded,
            "filters": dict(filters),
            "computed_at": computed_at,
            "script_version": SCRIPT_VERSION,
        }
        if dataset_id == "google":
            doc["google_low_coverage"] = mpio["_id"] in low_coverage
        documents.append(doc)

    # Ranking por área total (1 = más área); empates por código para que sea estable.
    ordered = sorted(documents, key=lambda d: (-d["total_area_m2"], d["mpio_code"]))
    for rank, doc in enumerate(ordered, start=1):
        doc["rank_total_area"] = rank

    excluded_totals = {reason: sum(doc["excluded"][reason] for doc in documents) for reason in REASONS}
    included = sum(doc["building_count"] for doc in documents)
    assigned = sum(doc["buildings_before_filters"] for doc in documents)
    totals = {
        "buildings_in_source": assigned + outside,
        "outside_pdet_or_unassigned": outside,
        "assigned_pdet": assigned,
        "excluded": {**excluded_totals, "total": sum(excluded_totals.values())},
        "included": included,
        "total_area_m2": round(math.fsum(doc["total_area_m2"] for doc in documents), 2),
        "balanced": included + sum(excluded_totals.values()) == assigned,
    }
    return documents, totals


def comparable(doc: dict) -> tuple:
    """Valores de un resultado sin la fecha, para comparar dos pasadas."""
    return (doc["_id"]["mpio_code"], doc["building_count"], doc["total_area_m2"], doc["mean_area_m2"],
            doc["median_area_m2"], doc["buildings_before_filters"], tuple(sorted(doc["excluded"].items())),
            tuple(sorted(doc["filters"].items())))


# ---------------------------------------------------------------- base


def connect(config: dict) -> MongoClient:
    client = MongoClient(os.environ.get("MONGO_URI", config["mongo"]["uri"]),
                         serverSelectionTimeoutMS=5000, tz_aware=True)
    client.admin.command("ping")
    return client


def ensure_collection(db, name: str) -> None:
    """Validador de ``rooftop_stats`` de ``00_init_db.py``, en modo error."""
    validator = {"$jsonSchema": {"bsonType": "object", **init_db.SCHEMAS["rooftop_stats"]}}
    if name in db.list_collection_names():
        db.command("collMod", name, validator=validator, validationLevel="strict", validationAction="error")
    else:
        db.create_collection(name, validator=validator, validationLevel="strict", validationAction="error")


def compute_pass(db, *, dataset_id: str, filters: dict, collection: str, low_coverage: set[str]) -> dict:
    """Una pasada completa: agrega, construye los 170 documentos y los escribe."""
    municipalities = list(db[MUNICIPALITIES].find(
        {}, {"name": 1, "dpto_code": 1, "dpto_name": 1, "subregion_id": 1, "subregion_name": 1}))
    if not municipalities:
        raise StatsError("la colección municipalities está vacía; corra antes 02_load_municipalities.py")
    if db[BUILDINGS].count_documents({"dataset_id": dataset_id}, limit=1) == 0:
        raise StatsError(f"buildings no tiene huellas de '{dataset_id}'; corra antes 04_load_buildings.py")
    computed_at = datetime.now(timezone.utc).replace(microsecond=0)
    groups = list(db[BUILDINGS].aggregate(aggregation_pipeline(dataset_id, filters), allowDiskUse=True))
    documents, totals = build_documents(municipalities, groups, dataset_id=dataset_id, filters=filters,
                                        computed_at=computed_at, low_coverage=low_coverage)
    if not totals["balanced"]:
        raise StatsError("las huellas incluidas y excluidas no cierran el balance")
    result = db[collection].bulk_write([ReplaceOne({"_id": doc["_id"]}, doc, upsert=True) for doc in documents],
                                       ordered=True)
    # Un municipio que ya no está en municipalities no debe quedar con un resultado viejo.
    stale = db[collection].delete_many({"_id.dataset_id": dataset_id,
                                        "_id.mpio_code": {"$nin": [doc["mpio_code"] for doc in documents]}})
    return {
        "computed_at": computed_at,
        "documents": documents,
        "totals": totals,
        "write": {"upserted": result.upserted_count, "replaced": result.matched_count,
                  "deleted_stale": stale.deleted_count},
    }


def verify(db, *, dataset_id: str, filters: dict, collection: str, documents: list[dict],
           totals: dict) -> dict:
    """Comprobaciones sobre lo que quedó escrito, con consultas independientes."""
    codes = sorted(db[MUNICIPALITIES].distinct("_id"))
    stored = list(db[collection].find({"_id.dataset_id": dataset_id}))
    stored_codes = [doc["_id"]["mpio_code"] for doc in stored]
    duplicates = list(db[collection].aggregate([
        {"$match": {"dataset_id": dataset_id}},
        {"$group": {"_id": "$mpio_code", "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 1}}},
    ]))
    in_source = db[BUILDINGS].count_documents({"dataset_id": dataset_id})
    included = db[BUILDINGS].count_documents(included_query(dataset_id, codes, filters))
    expected = {comparable(doc) for doc in documents}
    empty_ok = all(doc["mean_area_m2"] is None and doc["median_area_m2"] is None
                   for doc in stored if doc["building_count"] == 0)
    checks = {
        "all_pdet_municipalities": sorted(stored_codes) == codes and len(codes) == len(stored),
        "no_duplicate_municipalities": not duplicates and len(set(stored_codes)) == len(stored_codes),
        "stored_matches_computed": {comparable(doc) for doc in stored} == expected,
        "included_matches_independent_count": sum(doc["building_count"] for doc in stored) == included,
        "balance_with_source": totals["buildings_in_source"] == in_source and totals["balanced"],
        "filters_recorded": all(doc["filters"] == filters for doc in stored),
        "empty_municipalities_without_mean": empty_ok,
    }
    return {
        "checks": checks,
        "ok": all(checks.values()),
        "documents": len(stored),
        "expected_municipalities": len(codes),
        "independent_included_count": included,
        "buildings_in_source": in_source,
        "duplicates": duplicates,
    }


# ---------------------------------------------------------------- salidas


def write_csv(path: Path, documents: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(documents, key=lambda d: d["rank_total_area"])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        for doc in rows:
            writer.writerow({
                **{key: doc.get(key) for key in CSV_FIELDS},
                "excluded_below_min_area": doc["excluded"]["below_min_area"],
                "excluded_above_max_area": doc["excluded"]["above_max_area"],
                "excluded_low_confidence": doc["excluded"]["low_confidence"],
                "mean_area_m2": "" if doc["mean_area_m2"] is None else doc["mean_area_m2"],
                "median_area_m2": "" if doc["median_area_m2"] is None else doc["median_area_m2"],
                "google_low_coverage": "" if "google_low_coverage" not in doc else doc["google_low_coverage"],
                "computed_at": doc["computed_at"].isoformat(),
            })


def dataset_info(db, dataset_id: str) -> dict | None:
    doc = db["datasets"].find_one({"_id": dataset_id})
    if not doc:
        return None
    info = {key: doc.get(key) for key in ("_id", "name", "version", "license", "url")}
    accessed = doc.get("accessed_at")
    info["accessed_at"] = accessed.isoformat() if hasattr(accessed, "isoformat") else accessed
    return info


def run(db, *, config: dict, dataset_id: str, passes: int, collection: str) -> tuple[dict, list[dict]]:
    """Corre ``passes`` pasadas y devuelve el reporte y los documentos (sin escribir archivos)."""
    filters = filters_for(config, dataset_id)
    low_coverage = set(config["analysis"].get("google_low_coverage") or [])
    started = datetime.now(timezone.utc)
    ensure_collection(db, collection)
    pass_reports, previous, last = [], None, None
    for number in range(1, passes + 1):
        last = compute_pass(db, dataset_id=dataset_id, filters=filters, collection=collection,
                            low_coverage=low_coverage)
        after = db[collection].count_documents({"_id.dataset_id": dataset_id})
        item = {"pass": number, **last["write"], "documents_after": after,
                "computed_at": last["computed_at"].isoformat()}
        if previous is not None:
            item["same_values_as_previous"] = (
                {comparable(d) for d in last["documents"]} == {comparable(d) for d in previous})
        pass_reports.append(item)
        previous = last["documents"]
    verification = verify(db, dataset_id=dataset_id, filters=filters, collection=collection,
                          documents=last["documents"], totals=last["totals"])
    if passes >= 2:
        # Repetir no inserta nada nuevo, deja los mismos 170 documentos y los mismos valores.
        verification["checks"]["rerun_does_not_duplicate"] = all(
            item["documents_after"] == verification["expected_municipalities"]
            and item["upserted"] == 0 and item["same_values_as_previous"]
            for item in pass_reports[1:])
        verification["ok"] = all(verification["checks"].values())
    documents = last["documents"]
    with_buildings = [doc for doc in documents if doc["building_count"] > 0]
    finished = datetime.now(timezone.utc)
    report = {
        "role": "rooftop-stats-report",
        "script_version": SCRIPT_VERSION,
        "dataset_id": dataset_id,
        "dataset": dataset_info(db, dataset_id),
        "collection": collection,
        "filters": filters,
        "filter_order": list(REASONS),
        "computed_at": last["computed_at"].isoformat(),
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": finished.isoformat(timespec="seconds"),
        "duration_s": round((finished - started).total_seconds(), 2),
        "totals": last["totals"],
        "municipalities": {
            "expected": verification["expected_municipalities"],
            "written": len(documents),
            "with_buildings": len(with_buildings),
            "without_buildings": sorted(doc["mpio_code"] for doc in documents if doc["building_count"] == 0),
        },
        "area_per_municipality_m2": {
            "median_of_totals": round(statistics.median(d["total_area_m2"] for d in documents), 2),
            "max": max(d["total_area_m2"] for d in documents),
            "min_with_buildings": min((d["total_area_m2"] for d in with_buildings), default=0.0),
        },
        "top10_total_area": [
            {"rank": d["rank_total_area"], "mpio_code": d["mpio_code"], "name": d["name"],
             "building_count": d["building_count"], "total_area_m2": d["total_area_m2"]}
            for d in sorted(documents, key=lambda d: d["rank_total_area"])[:10]],
        "passes_requested": passes,
        "passes": pass_reports,
        "verification": verification,
        "status": "computed" if verification["ok"] else "verification_failed",
    }
    return report, documents


# ---------------------------------------------------------------- CLI


def run_real(args) -> int:
    config = load_config(ROOT)
    source_cfg = config["sources"][SOURCE_CONFIG[args.source]]
    dataset_id = source_cfg["id"]
    stats_cfg = config["analysis"]["rooftop_stats"]
    report_path = ROOT / stats_cfg["report"].format(source=dataset_id)
    csv_path = ROOT / stats_cfg["csv"].format(source=dataset_id)
    try:
        with connect(config) as client:
            db = client[config["mongo"]["database"]]
            report, documents = run(db, config=config, dataset_id=dataset_id, passes=args.passes,
                                    collection=stats_cfg["collection"])
            report["mongo_version"] = client.server_info().get("version")
            report["database"] = db.name
    except StatsError as exc:
        write_json(report_path, {"role": "rooftop-stats-report", "dataset_id": dataset_id,
                                 "status": "blocked", "error": str(exc)})
        print(f"[FALLA] {exc}", file=sys.stderr)
        return 1
    except PyMongoError as exc:
        print(f"[FALLA] error de MongoDB: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    write_csv(csv_path, documents)
    report["outputs"] = {"csv": csv_path.relative_to(ROOT).as_posix(), "csv_sha256": sha256_file(csv_path),
                         "report": report_path.relative_to(ROOT).as_posix()}
    write_json(report_path, report)
    for name, ok in report["verification"]["checks"].items():
        print(f"[{'OK' if ok else 'FALLA'}] {name}")
    totals = report["totals"]
    print(f"[{report['status']}] '{dataset_id}': {report['municipalities']['written']} municipios "
          f"({report['municipalities']['with_buildings']} con edificaciones); incluidas {totals['included']}, "
          f"excluidas {totals['excluded']['total']} de {totals['assigned_pdet']} en PDET; "
          f"área {totals['total_area_m2'] / 1e6:.2f} km² en {report['duration_s']} s")
    print(f"CSV: {report['outputs']['csv']}  ·  reporte: {report['outputs']['report']}")
    return 0 if report["status"] == "computed" else 1


# ---------------------------------------------------------------- self-check


def _building(dataset_id: str, ref: str, code: str | None, area: float, confidence=None) -> dict:
    return {"_id": f"{dataset_id}:{ref}", "dataset_id": dataset_id, "source_ref": ref, "mpio_code": code,
            "area_m2": area, "confidence": confidence,
            "centroid": {"type": "Point", "coordinates": [-75.0, 6.0]}}


def run_self_check() -> int:
    """Base temporal: 3 municipios (uno sin huellas), filtros, mediana, nulos e idempotencia."""
    config = load_config(ROOT)
    name = f"rooftop_selfcheck_{uuid.uuid4().hex[:8]}"
    failures = []

    def check(label: str, condition: bool) -> None:
        print(f"[{'OK' if condition else 'FALLA'}] {label}")
        if not condition:
            failures.append(label)

    test_config = {**config, "analysis": {**config["analysis"], "min_area_m2": 20, "max_area_m2": 1000,
                                          "min_confidence": 0.7, "confidence_sources": ["google"]}}
    try:
        client = connect(config)
    except PyMongoError as exc:
        print(f"[FALLA] sin MongoDB: {type(exc).__name__}", file=sys.stderr)
        return 2
    try:
        db = client[name]
        db[MUNICIPALITIES].insert_many([
            {"_id": code, "name": f"M{code}", "dpto_code": code[:2], "dpto_name": "D",
             "subregion_id": 1, "subregion_name": "S"} for code in ("05001", "05002", "05003")])
        db[BUILDINGS].insert_many([
            _building("ms", "a1", "05001", 10.0),      # < 20 m²
            _building("ms", "a2", "05001", 30.0),
            _building("ms", "a3", "05001", 50.0),
            _building("ms", "a4", "05001", 100.0),
            _building("ms", "a5", "05001", 5000.0),    # > max
            _building("ms", "b1", "05002", 19.99),     # municipio que queda vacío
            _building("ms", "x1", None, 80.0),         # sin municipio
            _building("google", "g1", "05001", 40.0, 0.9),
            _building("google", "g2", "05001", 40.0, 0.5),   # baja confianza
            _building("google", "g3", "05002", 60.0, None),  # sin confianza
        ])
        report, docs = run(db, config=test_config, dataset_id="ms", passes=2, collection="rooftop_stats")
        by_code = {doc["mpio_code"]: doc for doc in docs}
        check("escribe los 3 municipios, también los vacíos", report["municipalities"]["written"] == 3)
        check("conteo y suma tras filtros", by_code["05001"]["building_count"] == 3
              and by_code["05001"]["total_area_m2"] == 180.0)
        check("mediana exacta y promedio", by_code["05001"]["median_area_m2"] == 50.0
              and by_code["05001"]["mean_area_m2"] == 60.0)
        check("excluidas por motivo", by_code["05001"]["excluded"] == {
            "below_min_area": 1, "above_max_area": 1, "low_confidence": 0})
        check("municipio vacío: 0 edificaciones y promedio/mediana null",
              by_code["05002"]["building_count"] == 0 and by_code["05002"]["mean_area_m2"] is None
              and by_code["05003"]["buildings_before_filters"] == 0)
        check("huella sin municipio queda fuera y cierra el balance",
              report["totals"]["outside_pdet_or_unassigned"] == 1 and report["totals"]["balanced"]
              and report["totals"]["buildings_in_source"] == 7)
        check("Microsoft no aplica confianza", report["filters"]["min_confidence"] is None)
        check("verificaciones en OK", report["verification"]["ok"])
        check("segunda pasada no duplica", report["verification"]["checks"].get("rerun_does_not_duplicate") is True
              and db["rooftop_stats"].count_documents({}) == 3)
        greport, gdocs = run(db, config=test_config, dataset_id="google", passes=1, collection="rooftop_stats")
        gby = {doc["mpio_code"]: doc for doc in gdocs}
        check("Google aplica confianza (incluida null)", gby["05001"]["building_count"] == 1
              and gby["05002"]["excluded"]["low_confidence"] == 1
              and gby["05001"]["google_low_coverage"] is False)
        check("las dos fuentes conviven sin pisarse", db["rooftop_stats"].count_documents({}) == 6
              and greport["verification"]["ok"])
        same_rule = True
        for dataset_id in ("ms", "google"):
            filters = filters_for(test_config, dataset_id)
            mongo = {doc["_id"]: doc["reason"] for doc in db[BUILDINGS].aggregate([
                {"$match": {"dataset_id": dataset_id}},
                {"$project": {"reason": reason_expression(filters)}}])}
            for doc in db[BUILDINGS].find({"dataset_id": dataset_id}):
                same_rule &= mongo[doc["_id"]] == exclusion_reason(doc["area_m2"], doc["confidence"], filters)
        check("Python y MongoDB aplican la misma regla de filtros", same_rule)
        try:
            db["rooftop_stats"].insert_one({"_id": {"mpio_code": "1", "dataset_id": "ms"}, "building_count": -1})
            check("el validador rechaza un resultado incompleto", False)
        except PyMongoError:
            check("el validador rechaza un resultado incompleto", True)
    finally:
        client.drop_database(name)
        client.close()
    print("self-check:", "OK" if not failures else f"{len(failures)} fallas")
    return 0 if not failures else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", choices=sorted(SOURCE_CONFIG), help="fuente a calcular (dataset_id)")
    parser.add_argument("--passes", type=int, default=1,
                        help="pasadas completas; con 2 se comprueba que repetir no duplica")
    parser.add_argument("--self-check", action="store_true", help="pruebas en una base temporal")
    args = parser.parse_args(argv)
    if args.self_check:
        return run_self_check()
    if not args.source:
        parser.error("indique --source ms o --source google")
    if args.passes < 1:
        parser.error("--passes debe ser al menos 1")
    return run_real(args)


if __name__ == "__main__":
    sys.exit(main())
