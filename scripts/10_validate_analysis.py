"""Validación independiente del análisis de techos de la Entrega 4 (tramo de José).

No reutiliza el motor de ``06_rooftop_stats.py``: vuelve a leer ``buildings`` y
``municipalities`` y recalcula por su cuenta, para contrastar lo publicado.

1. Entradas y estado: colecciones, ``datasets``, ``ingestion_runs``, hashes de
   los reportes de la Entrega 3 y huellas por municipio frente a la preparación.
2. Conteos y áreas: los filtros de ``config.yaml`` se reescriben con pandas y se
   comparan con ``rooftop_stats``, con los CSV y con el CSV publicado en git.
3. Asignación espacial: (a) se reproduce la regla de la preparación con shapely
   (centroide dentro o en el borde; empate -> código menor); (b) se repite con
   ``$geoWithin`` esférico de MongoDB; (c) se miden las huellas que cruzan el
   límite de su municipio y el área que queda fuera de él.
4. Índices y planes: ``explain`` con ``executionStats`` de las consultas del análisis.
5. Coherencia: filtros, unidades, municipios, marca de cobertura de Google y
   correlación entre fuentes.

Uso:
    python scripts/10_validate_analysis.py
    python scripts/10_validate_analysis.py --baseline-ref HEAD   # CSV publicado a contrastar

Salidas en ``outputs/validation/``: ``entrega4_validation_report.json``,
``validation_by_municipality.csv`` y ``border_footprints_by_municipality.csv``.
Salida: 0 todo verificado, 1 alguna verificación falla, 2 error operativo.
MONGO_URI reemplaza la URI de config.yaml.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import io
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from pyproj import Geod
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from entrega2_contracts import load_config, sha256_file  # noqa: E402

SCRIPT_VERSION = "entrega4-validation-v1"
OUT_DIR = ROOT / "outputs" / "validation"
REPORT = OUT_DIR / "entrega4_validation_report.json"
BY_MPIO_CSV = OUT_DIR / "validation_by_municipality.csv"
BORDER_CSV = OUT_DIR / "border_footprints_by_municipality.csv"
SOURCES = {"ms": "microsoft", "google": "google"}
GEOD = Geod(ellps="WGS84")
# Margen interior (grados, ~550 m en el ecuador): una huella cuyo centroide está a
# más de esta distancia del límite no puede cruzarlo salvo que mida más que eso.
BORDER_MARGIN_DEG = 0.005
# Huellas grandes: se leen todas para comprobar que ninguna supera el margen.
LARGE_FOOTPRINT_M2 = 5000
AREA_TOL_M2 = 0.011       # redondeo a 2 decimales de dos sumas distintas
# Otro entorno puede redondear distinto a cm² el área geodésica de unas pocas huellas
# (PROJ/pyproj): entre corridas de entornos distintos se acepta 1e-6 relativo.
CROSS_ENV_REL_TOL = 1e-6
# area_m2 se guarda con 2 decimales: la suma de n áreas redondeadas puede alejarse
# hasta 0,005 m² por huella de la suma sin redondear de la preparación.
ROUNDING_PER_FOOTPRINT_M2 = 0.005
# El centroide se guarda con 7 decimales (~1 cm): un punto sobre el límite puede quedar
# fuera por menos de eso.
CENTROID_ROUNDING_DEG = 1e-7
UNIT_SAMPLE = 2000        # huellas por fuente para recalcular el área geodésica


def log(message: str) -> None:
    print(message, flush=True)


def _plain(value):
    """Tipos de numpy/pandas y fechas a JSON."""
    if isinstance(value, np.generic):
        return value.item()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=_plain) + "\n",
                    encoding="utf-8", newline="\n")


# ---------------------------------------------------------------- utilidades


def winning_stages(node) -> list[dict]:
    """Etapas del plan ganador (recorre inputStage/inputStages/queryPlan)."""
    if isinstance(node, list):
        return [stage for item in node for stage in winning_stages(item)]
    if not isinstance(node, dict):
        return []
    stages = [{"stage": node["stage"], **({"indexName": node["indexName"]} if "indexName" in node else {})}] \
        if "stage" in node else []
    for key in ("queryPlan", "inputStage", "inputStages", "winningPlan"):
        if key in node:
            stages += winning_stages(node[key])
    return stages


def execution_summary(explain: dict) -> dict:
    """Plan ganador y estadísticas de ejecución de un explain (find, count o aggregate)."""
    planner = explain.get("queryPlanner")
    stats = explain.get("executionStats")
    if planner is None:  # aggregate: el plan está en la primera etapa ($cursor)
        for stage in explain.get("stages", []):
            if "$cursor" in stage:
                planner = stage["$cursor"].get("queryPlanner")
                stats = stage["$cursor"].get("executionStats")
                break
    plan = winning_stages((planner or {}).get("winningPlan", {}))
    stats = stats or {}
    return {
        "winning_plan": plan,
        "uses_index": [s["indexName"] for s in plan if s["stage"] == "IXSCAN"],
        "collection_scan": any(s["stage"] == "COLLSCAN" for s in plan),
        "n_returned": stats.get("nReturned"),
        "total_keys_examined": stats.get("totalKeysExamined"),
        "total_docs_examined": stats.get("totalDocsExamined"),
        "execution_time_ms": stats.get("executionTimeMillis"),
    }


def geodesic_area(geom) -> float:
    if geom is None or geom.is_empty:
        return 0.0
    area, _ = GEOD.geometry_area_perimeter(geom)
    return abs(area)


def max_extent_m(geom, lon: float, lat: float) -> float:
    """Distancia geodésica máxima del centroide a un vértice de la huella."""
    coords = shapely.get_coordinates(geom)
    _, _, dist = GEOD.inv(np.full(len(coords), lon), np.full(len(coords), lat), coords[:, 0], coords[:, 1])
    return float(np.max(dist))


def spearman(a: pd.Series, b: pd.Series) -> float:
    """Spearman como Pearson de los rangos (sin scipy)."""
    return float(np.corrcoef(a.rank(), b.rank())[0, 1])


def baseline_csv(ref: str, path: str) -> pd.DataFrame | None:
    """CSV publicado en ``ref`` (por ejemplo HEAD), para contrastar con la corrida actual."""
    try:
        text = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=ROOT, check=True,
                              capture_output=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return pd.read_csv(io.StringIO(text), dtype={"mpio_code": str})


# ---------------------------------------------------------------- 1. entradas


def check_inputs(db, config: dict) -> dict:
    out = {"collections": {}, "sources": {}, "files": {}}
    for name in sorted(db.list_collection_names()):
        out["collections"][name] = db[name].estimated_document_count()
    for rel in ["config.yaml", "outputs/municipalities_prepare_report.json",
                config["sources"]["microsoft"]["pdet_input"]]:
        path = ROOT / rel
        out["files"][rel] = sha256_file(path) if path.is_file() else None
    municipalities_report = (ROOT / "outputs/municipalities_prepare_report.json")
    geojsonl_sha = json.loads(municipalities_report.read_text(encoding="utf-8"))["sha256"]
    checks = {
        "municipalities_170": db["municipalities"].count_documents({}) == 170,
        "subregions_16": db["pdet_subregions"].count_documents({}) == 16,
        "pdet_layer_matches_entrega2_hash": out["files"][config["sources"]["microsoft"]["pdet_input"]] == geojsonl_sha,
    }
    for dataset_id, key in SOURCES.items():
        cfg = config["sources"][key]
        prepare = json.loads((ROOT / cfg["prepare_report"]).read_text(encoding="utf-8"))
        load = json.loads((ROOT / cfg["load_report"]).read_text(encoding="utf-8"))
        for rel in (cfg["prepare_report"], cfg["load_report"], cfg["prepare_by_municipality"]):
            out["files"][rel] = sha256_file(ROOT / rel)
        in_db = db["buildings"].count_documents({"dataset_id": dataset_id})
        dataset = db["datasets"].find_one({"_id": dataset_id}) or {}
        runs = db["ingestion_runs"].count_documents({"dataset_id": dataset_id})
        last_run = db["ingestion_runs"].find_one({"dataset_id": dataset_id}, sort=[("finished_at", -1)])
        prepared_csv = pd.read_csv(ROOT / cfg["prepare_by_municipality"], dtype={"mpio_code": str})
        by_code = {row["_id"]: row["n"] for row in db["buildings"].aggregate([
            {"$match": {"dataset_id": dataset_id}}, {"$group": {"_id": "$mpio_code", "n": {"$sum": 1}}}])}
        mismatched = [code for code, n in zip(prepared_csv.mpio_code, prepared_csv.prepared_buildings)
                      if int(by_code.get(code, 0)) != int(n)]
        extra = sorted(set(by_code) - set(prepared_csv.mpio_code[prepared_csv.prepared_buildings > 0]))
        info = {
            "buildings_in_db": in_db,
            "prepared": prepare["totals"]["prepared"],
            "loaded_report": load["collection_after"],
            "prepare_status": prepare["status"],
            "load_status": load["status"],
            "load_idempotent": load.get("idempotent"),
            "dataset": {k: (v.isoformat() if hasattr(v, "isoformat") else v)
                        for k, v in dataset.items() if k in ("_id", "name", "version", "license", "url", "accessed_at")},
            "ingestion_runs": runs,
            "last_ingestion_run_finished_at": last_run["finished_at"].isoformat() if last_run else None,
            "municipalities_with_buildings": len([c for c in by_code if c]),
            "municipality_count_mismatches_vs_prepared_csv": mismatched,
            "codes_in_db_not_in_prepared_csv": extra,
            "null_mpio_code": int(by_code.get(None, 0)),
        }
        out["sources"][dataset_id] = info
        checks[f"{dataset_id}_count_matches_preparation_and_load"] = in_db == info["prepared"] == info["loaded_report"]
        checks[f"{dataset_id}_reports_ready_and_loaded"] = (info["prepare_status"] == "ready_for_load"
                                                           and info["load_status"] == "loaded"
                                                           and info["load_idempotent"] is True)
        checks[f"{dataset_id}_dataset_registered"] = bool(dataset) and dataset.get("license") == cfg["license"]
        checks[f"{dataset_id}_per_municipality_matches_preparation"] = not mismatched and not extra
        checks[f"{dataset_id}_ingestion_runs_recorded"] = runs > 0
    out["checks"] = checks
    return out


# ---------------------------------------------------------------- 2 y 3. recálculo por municipio


def filters_for(config: dict, dataset_id: str) -> dict:
    """Lectura propia de config.yaml (no se importa la del motor)."""
    a = config["analysis"]
    return {
        "min_area_m2": float(a["min_area_m2"]),
        "max_area_m2": None if a.get("max_area_m2") is None else float(a["max_area_m2"]),
        "min_confidence": float(a["min_confidence"]) if dataset_id in (a.get("confidence_sources") or []) else None,
    }


def classify(df: pd.DataFrame, filters: dict) -> pd.Series:
    """Motivo por huella, en el orden de la metodología: área mínima, área máxima, confianza."""
    reason = pd.Series("included", index=df.index)
    low_conf = pd.Series(False, index=df.index)
    if filters["min_confidence"] is not None:
        low_conf = df["confidence"].isna() | (df["confidence"] < filters["min_confidence"])
    above = pd.Series(False, index=df.index)
    if filters["max_area_m2"] is not None:
        above = df["area_m2"] > filters["max_area_m2"]
    below = df["area_m2"] < filters["min_area_m2"]
    reason[low_conf] = "low_confidence"
    reason[above] = "above_max_area"
    reason[below] = "below_min_area"
    return reason


def load_municipalities(db) -> tuple[list[str], list, list, dict]:
    docs = list(db["municipalities"].find({}, {"geometry": 1, "name": 1, "subregion_name": 1}).sort("_id", 1))
    codes = [d["_id"] for d in docs]
    geoms = [shape(d["geometry"]) for d in docs]
    for geom in geoms:
        shapely.prepare(geom)
    raw = {d["_id"]: d["geometry"] for d in docs}
    return codes, geoms, docs, raw


def recompute(db, config: dict, codes: list[str], geoms: list) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Por fuente y municipio: estadísticas propias, regla espacial y huellas de borde."""
    tree = shapely.STRtree(geoms)
    inner = [shapely.buffer(g, -BORDER_MARGIN_DEG) for g in geoms]
    for g in inner:
        shapely.prepare(g)
    rows, border_rows = [], []
    spatial = {d: {"points": 0, "rule_matches": 0, "rule_differs": 0, "outside_all": 0,
                   "on_shared_boundary": 0, "differs_examples": [], "outside_examples": [],
                   "outside_max_distance_deg": 0.0} for d in SOURCES}
    border = {d: {"candidates": 0, "crossing": 0, "area_outside_m2": 0.0, "area_crossing_m2": 0.0,
                  "max_extent_m": 0.0, "area_recheck": []} for d in SOURCES}
    for dataset_id in SOURCES:
        filters = filters_for(config, dataset_id)
        for idx, code in enumerate(codes):
            cursor = db["buildings"].find({"dataset_id": dataset_id, "mpio_code": code},
                                          {"area_m2": 1, "confidence": 1, "centroid.coordinates": 1})
            ids, xs, ys, areas, conf = [], [], [], [], []
            for doc in cursor:
                ids.append(doc["_id"])
                x, y = doc["centroid"]["coordinates"]
                xs.append(x)
                ys.append(y)
                areas.append(doc["area_m2"])
                conf.append(doc.get("confidence"))
            df = pd.DataFrame({"area_m2": np.asarray(areas, dtype=float),
                               "confidence": pd.array(conf, dtype="Float64").astype(float)})
            reason = classify(df, filters)
            inc = df.loc[reason == "included", "area_m2"]
            rows.append({
                "dataset_id": dataset_id, "mpio_code": code,
                "before": len(df),
                "below_min_area": int((reason == "below_min_area").sum()),
                "above_max_area": int((reason == "above_max_area").sum()),
                "low_confidence": int((reason == "low_confidence").sum()),
                "building_count": len(inc),
                "total_area_m2": round(math.fsum(inc), 2),
                "mean_area_m2": round(float(inc.mean()), 2) if len(inc) else None,
                "median_area_m2": round(float(inc.median()), 2) if len(inc) else None,
                "area_before_m2": round(math.fsum(df["area_m2"]), 2),
            })
            if not len(df):
                continue
            x, y = np.asarray(xs), np.asarray(ys)

            # (a) regla de la preparación: código menor entre los municipios que intersecta el centroide.
            hits = np.full(len(x), -1)
            n_hits = np.zeros(len(x), dtype=int)
            box = shapely.box(x.min(), y.min(), x.max(), y.max())
            for j in sorted(tree.query(box)):
                inside = shapely.intersects_xy(geoms[j], x, y)
                n_hits += inside
                hits = np.where((hits == -1) & inside, j, hits)
            s = spatial[dataset_id]
            s["points"] += len(x)
            s["rule_matches"] += int((hits == idx).sum())
            s["outside_all"] += int((hits == -1).sum())
            s["on_shared_boundary"] += int((n_hits > 1).sum())
            differs = np.flatnonzero((hits != idx) & (hits != -1))
            s["rule_differs"] += len(differs)
            for k in differs[:3]:
                if len(s["differs_examples"]) < 10:
                    s["differs_examples"].append({"_id": ids[k], "assigned": code, "rule": codes[hits[k]]})
            for k in np.flatnonzero(hits == -1):
                # Fuera de todo municipio: distancia al asignado (grados) para separar redondeo de error.
                dist = float(shapely.distance(geoms[idx], shapely.Point(x[k], y[k])))
                s["outside_max_distance_deg"] = max(s["outside_max_distance_deg"], dist)
                if len(s["outside_examples"]) < 10:
                    s["outside_examples"].append({"_id": ids[k], "assigned": code, "lon": x[k], "lat": y[k],
                                                  "distance_deg": dist, "distance_m": round(dist * 111_320, 4)})

            # (c) huellas cerca del límite: se leen y se mide la parte fuera del municipio.
            near = ~shapely.contains_xy(inner[idx], x, y)
            large = df["area_m2"].to_numpy() >= LARGE_FOOTPRINT_M2
            pick = np.flatnonzero(near | large)
            b = border[dataset_id]
            b["candidates"] += int(near.sum())
            crossing_n, crossing_area, outside_area = 0, 0.0, 0.0
            for start in range(0, len(pick), 5000):
                chunk = [ids[k] for k in pick[start:start + 5000]]
                pos = {ids[k]: k for k in pick[start:start + 5000]}
                for doc in db["buildings"].find({"_id": {"$in": chunk}}, {"footprint": 1, "area_m2": 1}):
                    k = pos[doc["_id"]]
                    geom = shape(doc["footprint"])
                    b["max_extent_m"] = max(b["max_extent_m"], max_extent_m(geom, x[k], y[k]))
                    if len(b["area_recheck"]) < UNIT_SAMPLE:
                        b["area_recheck"].append((doc["area_m2"], geodesic_area(geom)))
                    if not near[k] or shapely.covers(geoms[idx], geom):
                        continue
                    outside = geodesic_area(shapely.difference(geom, geoms[idx]))
                    if outside <= 0:
                        continue
                    crossing_n += 1
                    crossing_area += doc["area_m2"]
                    outside_area += outside
            b["crossing"] += crossing_n
            b["area_crossing_m2"] += crossing_area
            b["area_outside_m2"] += outside_area
            if crossing_n:
                border_rows.append({"dataset_id": dataset_id, "mpio_code": code, "crossing_footprints": crossing_n,
                                    "crossing_area_m2": round(crossing_area, 2),
                                    "area_outside_municipality_m2": round(outside_area, 2)})
        log(f"  recálculo '{dataset_id}': {spatial[dataset_id]['points']} huellas en {len(codes)} municipios")
    for b in border.values():
        pairs = b.pop("area_recheck")
        diffs = [abs(stored - recomputed) for stored, recomputed in pairs]
        b["area_recheck"] = {"footprints": len(pairs), "max_abs_diff_m2": round(max(diffs, default=0.0), 4)}
        b["area_outside_m2"] = round(b["area_outside_m2"], 2)
        b["area_crossing_m2"] = round(b["area_crossing_m2"], 2)
        b["max_extent_m"] = round(b["max_extent_m"], 1)
    return pd.DataFrame(rows), pd.DataFrame(border_rows), {"rule": spatial, "border": border}


def spherical_assignment(db, codes: list[str], raw: dict) -> dict:
    """(b) $geoWithin esférico de MongoDB por municipio, contra el mpio_code guardado."""
    out = {d: {"confirmed": 0, "assigned_elsewhere_inside": 0, "elsewhere_examples": [], "errors": []}
           for d in SOURCES}
    per_mpio = []
    for code in codes:
        try:
            groups = list(db["buildings"].aggregate([
                {"$match": {"centroid": {"$geoWithin": {"$geometry": raw[code]}}}},
                {"$group": {"_id": {"d": "$dataset_id", "m": "$mpio_code"}, "n": {"$sum": 1}}}]))
        except PyMongoError as exc:
            for d in SOURCES:
                out[d]["errors"].append({"mpio_code": code, "error": type(exc).__name__})
            continue
        for g in groups:
            d, m = g["_id"]["d"], g["_id"]["m"]
            if m == code:
                out[d]["confirmed"] += g["n"]
            else:
                out[d]["assigned_elsewhere_inside"] += g["n"]
                out[d]["elsewhere_examples"].append({"inside_spherical": code, "assigned": m, "n": g["n"]})
        per_mpio.append({"mpio_code": code, **{f"{d}_within": sum(g["n"] for g in groups
                                                                   if g["_id"]["d"] == d and g["_id"]["m"] == code)
                                               for d in SOURCES}})
    return {"summary": out, "per_municipality": per_mpio}


# ---------------------------------------------------------------- comparaciones


def compare_stats(ours: pd.DataFrame, stored: pd.DataFrame, label: str, rel_tol: float = 0.0) -> dict:
    """Diferencias campo a campo entre el recálculo y otra tabla (rooftop_stats o CSV).

    ``rel_tol`` amplía la tolerancia de las áreas en proporción al valor (otro entorno).
    """
    merged = ours.merge(stored, on=["dataset_id", "mpio_code"], how="outer", suffixes=("", "_other"),
                        indicator=True)
    missing = merged[merged["_merge"] != "both"][["dataset_id", "mpio_code", "_merge"]].astype(str)
    both = merged[merged["_merge"] == "both"]
    result = {"compared": label, "rows": len(both), "missing_rows": missing.to_dict("records")}
    for field, tol in [("building_count", 0), ("before", 0), ("below_min_area", 0), ("low_confidence", 0),
                       ("total_area_m2", AREA_TOL_M2), ("mean_area_m2", AREA_TOL_M2),
                       ("median_area_m2", AREA_TOL_M2)]:
        other = f"{field}_other"
        if other not in both:
            continue
        a = pd.to_numeric(both[field], errors="coerce")
        b = pd.to_numeric(both[other], errors="coerce")
        nan_mismatch = int((a.isna() != b.isna()).sum())
        diff = (a - b).abs().fillna(0)
        limit = np.maximum(tol, rel_tol * b.abs().fillna(0)) if tol else tol
        rel = (diff / b.abs().where(b.abs() > 0)).fillna(0)
        result[field] = {"max_abs_diff": round(float(diff.max()), 4), "max_rel_diff": float(rel.max()),
                         "rows_with_difference": int((diff > 0).sum()),
                         "rows_over_tolerance": int((diff > limit).sum()),
                         "null_mismatch": nan_mismatch, "tolerance": tol, "relative_tolerance": rel_tol if tol else 0}
    result["ok"] = (not result["missing_rows"]
                    and all(v["rows_over_tolerance"] == 0 and v["null_mismatch"] == 0
                            for k, v in result.items() if isinstance(v, dict)))
    return result


def stored_frame(db, collection: str) -> pd.DataFrame:
    rows = []
    for doc in db[collection].find({}):
        rows.append({"dataset_id": doc["dataset_id"], "mpio_code": doc["mpio_code"],
                     "building_count": doc["building_count"], "total_area_m2": doc["total_area_m2"],
                     "mean_area_m2": doc["mean_area_m2"], "median_area_m2": doc["median_area_m2"],
                     "before": doc["buildings_before_filters"],
                     "below_min_area": doc["excluded"]["below_min_area"],
                     "low_confidence": doc["excluded"]["low_confidence"],
                     "filters": doc["filters"], "script_version": doc.get("script_version"),
                     "name": doc.get("name"), "subregion_name": doc.get("subregion_name"),
                     "google_low_coverage": doc.get("google_low_coverage")})
    return pd.DataFrame(rows)


def csv_frame(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(columns={"buildings_before_filters": "before", "excluded_below_min_area": "below_min_area",
                              "excluded_low_confidence": "low_confidence"})


def explain_plans(db, config: dict, raw: dict, codes: list[str]) -> dict:
    """Planes de las consultas que usa el análisis, con estadísticas reales de ejecución."""
    spec = importlib.util.spec_from_file_location("rooftop_stats", ROOT / "scripts" / "06_rooftop_stats.py")
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    sample = "47001"  # Santa Marta, el municipio con más área
    plans = {}
    for dataset_id in SOURCES:
        filters = engine.filters_for(config, dataset_id)
        plans[f"aggregate_rooftop_stats_{dataset_id}"] = execution_summary(db.command(
            "explain", {"aggregate": "buildings", "pipeline": engine.aggregation_pipeline(dataset_id, filters),
                        "cursor": {}, "allowDiskUse": True}, verbosity="executionStats"))
        plans[f"count_included_{dataset_id}"] = execution_summary(db.command(
            "explain", {"count": "buildings", "query": engine.included_query(dataset_id, codes, filters)},
            verbosity="executionStats"))
    plans["find_by_source_and_municipality"] = execution_summary(db.command(
        "explain", {"find": "buildings", "filter": {"dataset_id": "ms", "mpio_code": sample}},
        verbosity="executionStats"))
    plans["geo_within_centroid"] = execution_summary(db.command(
        "explain", {"count": "buildings", "query": {"centroid": {"$geoWithin": {"$geometry": raw[sample]}}}},
        verbosity="executionStats"))
    santa_marta = db["buildings"].find_one({"dataset_id": "ms", "mpio_code": sample}, {"centroid": 1})
    plans["municipality_of_point"] = execution_summary(db.command(
        "explain", {"find": "municipalities",
                    "filter": {"geometry": {"$geoIntersects": {"$geometry": santa_marta["centroid"]}}},
                    "projection": {"_id": 1}}, verbosity="executionStats"))
    plans["rooftop_stats_by_source"] = execution_summary(db.command(
        "explain", {"find": "rooftop_stats", "filter": {"_id.dataset_id": "ms"}}, verbosity="executionStats"))
    indexes = {name: {k: v.get("key") for k, v in db[name].index_information().items()}
               for name in ("buildings", "municipalities", "rooftop_stats")}
    expected = {
        "aggregate_rooftop_stats_ms": "dataset_id_1_mpio_code_1",
        "aggregate_rooftop_stats_google": "dataset_id_1_mpio_code_1",
        "count_included_ms": "dataset_id_1_mpio_code_1",
        "count_included_google": "dataset_id_1_mpio_code_1",
        "find_by_source_and_municipality": "dataset_id_1_mpio_code_1",
        "geo_within_centroid": "centroid_2dsphere",
        "municipality_of_point": "geometry_2dsphere",
    }
    checks = {f"plan_{name}_uses_{index}": index in plans[name]["uses_index"] for name, index in expected.items()}
    return {"indexes": indexes, "plans": plans, "checks": checks}


# ---------------------------------------------------------------- principal


def run(db, config: dict, baseline_ref: str | None) -> dict:
    timings = {}
    t = time.perf_counter()
    log("1/5 entradas y estado de MongoDB")
    inputs = check_inputs(db, config)
    timings["inputs_s"] = round(time.perf_counter() - t, 2)

    t = time.perf_counter()
    log("2/5 recálculo independiente, regla espacial y huellas de borde")
    codes, geoms, mdocs, raw = load_municipalities(db)
    ours, border_df, spatial = recompute(db, config, codes, geoms)
    timings["recompute_s"] = round(time.perf_counter() - t, 2)

    t = time.perf_counter()
    log("3/5 asignación con $geoWithin esférico de MongoDB")
    spherical = spherical_assignment(db, codes, raw)
    timings["spherical_s"] = round(time.perf_counter() - t, 2)

    log("4/5 comparación con rooftop_stats, CSV y la versión publicada")
    stats_cfg = config["analysis"]["rooftop_stats"]
    stored = stored_frame(db, stats_cfg["collection"])
    comparisons = {"rooftop_stats_collection": compare_stats(ours, stored, "colección rooftop_stats")}
    csvs = {}
    for dataset_id in SOURCES:
        path = ROOT / stats_cfg["csv"].format(source=dataset_id)
        if path.is_file():
            csvs[dataset_id] = pd.read_csv(path, dtype={"mpio_code": str})
            comparisons[f"csv_{dataset_id}"] = compare_stats(
                ours[ours.dataset_id == dataset_id], csv_frame(csvs[dataset_id]), path.relative_to(ROOT).as_posix())
        prepared = pd.read_csv(ROOT / config["sources"][SOURCES[dataset_id]]["prepare_by_municipality"],
                               dtype={"mpio_code": str})
        prep = ours[ours.dataset_id == dataset_id].merge(prepared, on="mpio_code", how="left")
        area_diff = (prep["area_before_m2"] - prep["area_m2_sum"].fillna(0)).abs()
        bound = AREA_TOL_M2 + ROUNDING_PER_FOOTPRINT_M2 * prep["before"]
        comparisons[f"prepared_csv_{dataset_id}"] = {
            "compared": "huellas y área antes de filtros vs. preparación de la Entrega 3",
            "count_mismatches": int((prep["before"] != prep["prepared_buildings"].fillna(0)).sum()),
            "area_max_abs_diff_m2": round(float(area_diff.max()), 4),
            "area_total_diff_m2": round(float((prep["area_before_m2"] - prep["area_m2_sum"].fillna(0)).sum()), 4),
            "area_max_diff_over_rounding_bound": round(float((area_diff / bound).max()), 4),
            "ok": bool((prep["before"] == prep["prepared_buildings"].fillna(0)).all() and (area_diff <= bound).all()),
        }
        if baseline_ref:
            base = baseline_csv(baseline_ref, stats_cfg["csv"].format(source=dataset_id))
            if base is not None:
                comparisons[f"published_{baseline_ref}_{dataset_id}"] = compare_stats(
                    ours[ours.dataset_id == dataset_id], csv_frame(base),
                    f"{baseline_ref}:{stats_cfg['csv'].format(source=dataset_id)}", rel_tol=CROSS_ENV_REL_TOL)

    t = time.perf_counter()
    log("5/5 índices, planes de ejecución y coherencia entre fuentes")
    plans = explain_plans(db, config, raw, codes)
    timings["plans_s"] = round(time.perf_counter() - t, 2)

    # Coherencia de filtros, unidades, municipios y resultados entre las dos fuentes.
    ms = ours[ours.dataset_id == "ms"].set_index("mpio_code")
    gg = ours[ours.dataset_id == "google"].set_index("mpio_code")
    low_cfg = set(config["analysis"]["google_low_coverage"])
    low_rule = set(gg.index[gg["before"] < 0.2 * ms.loc[gg.index, "before"]])
    comparable = sorted(set(codes) - low_cfg)
    filt = {d: [f for f in stored[stored.dataset_id == d]["filters"]] for d in SOURCES}
    same_filters_ok = all(all(f == filters_for(config, d) for f in filt[d]) and len(filt[d]) == 170 for d in SOURCES)
    names = stored.pivot_table(index="mpio_code", columns="dataset_id", values="name", aggfunc="first")
    subs = stored.pivot_table(index="mpio_code", columns="dataset_id", values="subregion_name", aggfunc="first")
    google_flags = stored[stored.dataset_id == "google"].set_index("mpio_code")["google_low_coverage"]
    unit_recheck = {d: spatial["border"][d]["area_recheck"] for d in SOURCES}
    gsrc = list(db["buildings"].aggregate([
        {"$match": {"dataset_id": "google", "area_src_m2": {"$gt": 0}}}, {"$sample": {"size": 20000}},
        {"$project": {"r": {"$divide": ["$area_m2", "$area_src_m2"]}}}]))
    ratio = pd.Series([d["r"] for d in gsrc])
    coherence = {
        "filters": {d: filters_for(config, d) for d in SOURCES},
        "low_coverage_rule_recomputed": sorted(low_rule),
        "low_coverage_config": sorted(low_cfg),
        "spearman_count_comparable": round(spearman(ms.loc[comparable, "building_count"],
                                                    gg.loc[comparable, "building_count"]), 4),
        "spearman_area_comparable": round(spearman(ms.loc[comparable, "total_area_m2"],
                                                   gg.loc[comparable, "total_area_m2"]), 4),
        "comparable_municipalities": len(comparable),
        "totals": {d: {"buildings_before": int(ours[ours.dataset_id == d]["before"].sum()),
                       "buildings_included": int(ours[ours.dataset_id == d]["building_count"].sum()),
                       "area_included_km2": round(ours[ours.dataset_id == d]["total_area_m2"].sum() / 1e6, 4)}
                   for d in SOURCES},
        "area_recheck_geodesic": unit_recheck,
        "google_area_m2_over_area_src_m2": {"sample": len(ratio), "median": round(float(ratio.median()), 5),
                                            "p01": round(float(ratio.quantile(0.01)), 5),
                                            "p99": round(float(ratio.quantile(0.99)), 5)},
    }
    coherence_checks = {
        "same_170_municipalities_both_sources": (sorted(ms.index) == sorted(gg.index) == codes
                                                 and all(sorted(stored[stored.dataset_id == d].mpio_code) == codes
                                                         for d in SOURCES)
                                                 and all(sorted(c.mpio_code) == codes for c in csvs.values())),
        "filters_recorded_match_config": same_filters_ok,
        "area_filters_identical_across_sources": (filters_for(config, "ms")["min_area_m2"]
                                                  == filters_for(config, "google")["min_area_m2"]
                                                  and filters_for(config, "ms")["max_area_m2"]
                                                  == filters_for(config, "google")["max_area_m2"]),
        "confidence_only_google": (filters_for(config, "ms")["min_confidence"] is None
                                   and filters_for(config, "google")["min_confidence"] is not None),
        "same_script_version_both_sources": stored["script_version"].nunique() == 1,
        "names_and_subregions_match_between_sources": bool((names["ms"] == names["google"]).all()
                                                           and (subs["ms"] == subs["google"]).all()),
        "low_coverage_rule_matches_config": low_rule == low_cfg,
        "google_flag_matches_config": all(bool(google_flags.get(c)) == (c in low_cfg) for c in codes),
        "area_units_geodesic_m2": all(v["max_abs_diff_m2"] <= AREA_TOL_M2 for v in unit_recheck.values()),
        "google_area_close_to_published_area": abs(coherence["google_area_m2_over_area_src_m2"]["median"] - 1) < 0.02,
        "csv_totals_match_reports": all(
            abs(c["total_area_m2"].sum() - ours[ours.dataset_id == d]["total_area_m2"].sum()) <= AREA_TOL_M2 * 170
            for d, c in csvs.items()),
    }

    rule, border, sph = spatial["rule"], spatial["border"], spherical["summary"]
    spatial_checks = {}
    for d in SOURCES:
        spatial_checks[f"{d}_shapely_rule_reproduces_assignment"] = rule[d]["rule_differs"] == 0
        spatial_checks[f"{d}_points_outside_only_by_centroid_rounding"] = (rule[d]["outside_max_distance_deg"]
                                                                          <= CENTROID_ROUNDING_DEG)
        spatial_checks[f"{d}_mongo_geowithin_without_errors"] = not sph[d]["errors"]
        spatial_checks[f"{d}_border_margin_covers_largest_footprint"] = (border[d]["max_extent_m"]
                                                                         < BORDER_MARGIN_DEG * 110_000)
        sph[d]["buildings"] = rule[d]["points"]
        sph[d]["not_confirmed"] = rule[d]["points"] - sph[d]["confirmed"]
        sph[d]["confirmed_pct"] = round(100 * sph[d]["confirmed"] / max(rule[d]["points"], 1), 4)
        border[d]["area_outside_pct_of_included"] = round(
            100 * border[d]["area_outside_m2"] / (coherence["totals"][d]["area_included_km2"] * 1e6), 4)
        # La diferencia esférico/plano solo se acepta como diferencia de borde: menos del 0,1 %.
        spatial_checks[f"{d}_spherical_differences_below_0_1pct"] = sph[d]["not_confirmed"] < 0.001 * rule[d]["points"]

    # Tabla por municipio: recálculo, publicado, regla espacial y borde.
    table = ours.merge(stored[["dataset_id", "mpio_code", "building_count", "total_area_m2"]],
                       on=["dataset_id", "mpio_code"], how="left", suffixes=("", "_rooftop_stats"))
    within = pd.DataFrame(spherical["per_municipality"]).melt(id_vars="mpio_code", var_name="dataset_id",
                                                              value_name="mongo_geowithin_confirmed")
    within["dataset_id"] = within["dataset_id"].str.replace("_within", "", regex=False)
    table = table.merge(within, on=["dataset_id", "mpio_code"], how="left")
    if not border_df.empty:
        table = table.merge(border_df, on=["dataset_id", "mpio_code"], how="left")
    table["name"] = table["mpio_code"].map({d["_id"]: d["name"] for d in mdocs})
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    table.sort_values(["dataset_id", "mpio_code"]).to_csv(BY_MPIO_CSV, index=False, lineterminator="\n")
    border_df.sort_values(["dataset_id", "area_outside_municipality_m2"], ascending=[True, False]) \
        .to_csv(BORDER_CSV, index=False, lineterminator="\n")
    top_border = (border_df.sort_values("area_outside_municipality_m2", ascending=False).head(10)
                  .assign(name=lambda f: f["mpio_code"].map({d["_id"]: d["name"] for d in mdocs}))
                  .to_dict("records")) if not border_df.empty else []

    sections = {"inputs": inputs["checks"], "comparisons": {k: v["ok"] for k, v in comparisons.items()},
                "spatial": spatial_checks, "plans": plans["checks"], "coherence": coherence_checks}
    ok = all(all(v.values()) for v in sections.values())
    return {
        "role": "entrega4-validation-report",
        "script_version": SCRIPT_VERSION,
        "parameters": {"border_margin_deg": BORDER_MARGIN_DEG, "large_footprint_m2": LARGE_FOOTPRINT_M2,
                       "area_tolerance_m2": AREA_TOL_M2, "cross_environment_rel_tol": CROSS_ENV_REL_TOL,
                       "rounding_per_footprint_m2": ROUNDING_PER_FOOTPRINT_M2,
                       "centroid_rounding_deg": CENTROID_ROUNDING_DEG, "baseline_ref": baseline_ref,
                       "analysis": config["analysis"]},
        "timings_s": timings,
        "inputs": inputs,
        "comparisons": comparisons,
        "spatial": {"shapely_rule": rule, "mongo_spherical": sph, "border_footprints": border,
                    "top10_area_outside": top_border},
        "plans": plans,
        "coherence": coherence,
        "checks": sections,
        "ok": ok,
        "status": "validated" if ok else "validation_failed",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline-ref", default="HEAD",
                        help="referencia git con los CSV publicados a contrastar ('' para omitir)")
    args = parser.parse_args(argv)
    config = load_config(ROOT)
    started = datetime.now(timezone.utc)
    try:
        with MongoClient(os.environ.get("MONGO_URI", config["mongo"]["uri"]),
                         serverSelectionTimeoutMS=5000, tz_aware=True) as client:
            client.admin.command("ping")
            db = client[config["mongo"]["database"]]
            report = run(db, config, args.baseline_ref or None)
            report["mongo_version"] = client.server_info().get("version")
            report["database"] = db.name
    except PyMongoError as exc:
        print(f"[FALLA] error de MongoDB: {type(exc).__name__}", file=sys.stderr)
        return 2
    finished = datetime.now(timezone.utc)
    report.update(started_at=started.isoformat(timespec="seconds"), finished_at=finished.isoformat(timespec="seconds"),
                  duration_s=round((finished - started).total_seconds(), 2))
    report["outputs"] = {p.relative_to(ROOT).as_posix(): sha256_file(p) for p in (BY_MPIO_CSV, BORDER_CSV)}
    write_json(REPORT, report)
    for section, checks in report["checks"].items():
        for name, ok in checks.items():
            print(f"[{'OK' if ok else 'FALLA'}] {section}.{name}")
    total = sum(len(c) for c in report["checks"].values())
    passed = sum(sum(c.values()) for c in report["checks"].values())
    print(f"[{report['status']}] {passed}/{total} verificaciones en {report['duration_s']} s · "
          f"reporte: {REPORT.relative_to(ROOT)}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
