"""Prepara huellas de edificaciones para la colección ``buildings`` (Entrega 3, tramo de Derek).

Entrada: el manifiesto de un módulo de descarga (hoy Microsoft, de Miguel) y
los 170 municipios PDET de la Entrega 2. Salida: un GeoJSON Lines con gzip
por partición, con documentos de ``buildings`` sin ``run_id``, más un reporte
por fuente que la carga (``04_load_buildings.py``) usa como compuerta.

Por cada edificación, en bloques de ``processing.batch_size`` líneas:

1. Lee la Feature y construye el polígono (orden lon/lat, WGS84).
2. Valida: tipo Polygon, no vacío, dentro de la ventana de Colombia.
3. Repara con ``make_valid`` si GEOS la marca inválida; rechaza si no queda
   un solo polígono con área.
4. Calcula centroide y área geodésica (``pyproj.Geod``, elipsoide WGS84).
5. Aplica el criterio espacial: centroide dentro o en el borde de un
   municipio PDET; borde compartido -> código DIVIPOLA menor. Lo que cae
   fuera no se escribe (se cuenta como excluido, no como rechazado).
6. Limpia atributos: ``height`` y ``confidence`` -1 pasan a null.

Al final quita huellas idénticas que vengan en dos particiones y escribe el
reporte. Se cumple ``read = rejected + excluded_outside_pdet + prepared``.

Uso:
    python scripts/03_prepare_buildings.py --source ms
    python scripts/03_prepare_buildings.py --source ms --without-pdet-selection
        # evidencia de calidad de la fuente sin la capa PDET; nunca queda lista para cargar
    python scripts/03_prepare_buildings.py --source ms --partitions 032212332
        # muestra; el reporte dice claims_full_source = false
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import shape

sys.path.insert(0, str(Path(__file__).resolve().parent))
from entrega2_contracts import ContractError, archive_success_claim, load_config, sha256_file, write_json  # noqa: E402
from entrega3_contracts import (  # noqa: E402
    CONTRACT_VERSION,
    PdetSelector,
    clean_height,
    clean_unit_interval,
    coords_in_colombia,
    download_manifest_problems,
    geodesic_area_m2,
    load_pdet_layer,
    partition_id,
    polygon_geojson,
    prepared_record_errors,
    repair_polygon,
    verify_partition_file,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_VERSION = "entrega3-prepare-v1"


# ---------------------------------------------------------------- adaptadores por fuente


def ms_attributes(props: dict) -> tuple[dict, list[str]]:
    """Microsoft: ``height`` y ``confidence`` (-1 = desconocido). No trae área original."""
    notes = []
    confidence, note = clean_unit_interval(props.get("confidence"), "confidence_unknown", "confidence_out_of_range")
    if note:
        notes.append(note)
    height, note = clean_height(props.get("height"))
    if note:
        notes.append(note)
    return {"area_src_m2": None, "confidence": confidence, "height_m": height}, notes


def ms_features(path: Path):
    """Itera ``(número_de_línea, Feature | None)`` de un GeoJSONL con gzip, sin cargarlo entero."""
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield number, json.loads(line)
            except json.JSONDecodeError:
                yield number, None


# Una entrada por fuente. Google (Slice 2) agrega aquí su lector y sus atributos
# cuando exista su manifiesto de descarga.
SOURCES = {
    "ms": {"config_key": "microsoft", "features": ms_features, "attributes": ms_attributes},
}


# ---------------------------------------------------------------- trabajo por partición

_SELECTOR: PdetSelector | None = None


def gzip_text_writer(path: Path, compresslevel: int = 5):
    """gzip de texto con cabecera fija (mtime 0, sin nombre): mismos datos, mismo SHA256."""
    raw = open(path, "wb")
    gz = gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=compresslevel, mtime=0)
    text = io.TextIOWrapper(gz, encoding="utf-8", newline="\n")
    close = text.close

    def close_all():
        close()
        raw.close()

    text.close = close_all
    return text


def _init_worker(municipalities: list[dict] | None) -> None:
    global _SELECTOR
    _SELECTOR = PdetSelector(municipalities) if municipalities else None


def _geometry_hash(geom) -> int:
    wkb = shapely.to_wkb(shapely.normalize(geom), output_dimension=2)
    return int.from_bytes(hashlib.blake2b(wkb, digest_size=8).digest(), "little")


def _process_chunk(chunk, ctx, out, rej, rep, acc):
    """Procesa un bloque de ``(línea, Feature)`` y escribe lo que pasa."""
    source, pid, file_name = ctx["source"], ctx["partition_id"], ctx["file_name"]
    precision, sliver = ctx["precision"], ctx["sliver_ratio"]
    counts = acc["counts"]
    candidates = []  # (línea, geom, props, coords_originales | None)
    for number, feat in chunk:
        ref = f"{pid}/{file_name}:{number}"
        counts["read"] += 1
        if feat is None:
            _reject(rej, counts, ref, "json_invalid")
            continue
        geometry = feat.get("geometry") if isinstance(feat, dict) else None
        if not isinstance(geometry, dict):
            _reject(rej, counts, ref, "feature_invalid")
            continue
        if geometry.get("type") != "Polygon":
            _reject(rej, counts, ref, "geometry_type_unsupported", geometry.get("type"))
            continue
        try:
            geom = shape(geometry)
        except Exception as exc:  # anillos con menos de 4 puntos, coordenadas no numéricas
            _reject(rej, counts, ref, "geometry_unparseable", str(exc)[:120])
            continue
        if geom.is_empty:
            _reject(rej, counts, ref, "geometry_empty")
            continue
        if not coords_in_colombia(geom):
            _reject(rej, counts, ref, "outside_colombia_window", list(geom.bounds))
            continue
        candidates.append((ref, geom, feat.get("properties") or {}, geometry["coordinates"]))
    if not candidates:
        return

    geoms = np.array([c[1] for c in candidates], dtype=object)
    valid = shapely.is_valid(geoms)
    kept = []
    for (ref, geom, props, coords), ok in zip(candidates, valid.tolist()):
        if ok:
            kept.append((ref, geom, props, coords))
            continue
        reason = shapely.is_valid_reason(geom)
        fixed, action = repair_polygon(geom, sliver)
        if fixed is None:
            _reject(rej, counts, ref, action, reason)
            continue
        counts["repaired"] += 1
        acc["repairs"][action] += 1
        rep.write(json.dumps({"source_ref": ref, "action": action, "reason": reason,
                              "planar_area_ratio": round(fixed.area / geom.area, 6) if geom.area else None},
                             ensure_ascii=False) + "\n")
        kept.append((ref, fixed, props, None))
    if not kept:
        return

    centroids = shapely.centroid(np.array([k[1] for k in kept], dtype=object))
    lons, lats = shapely.get_x(centroids), shapely.get_y(centroids)
    if _SELECTOR is not None:
        codes, multi = _SELECTOR.assign(lons, lats)
        counts["centroids_on_shared_boundary"] += multi
    else:
        codes = [None] * len(kept)

    for (ref, geom, props, coords), lon, lat, code in zip(kept, lons.tolist(), lats.tolist(), codes):
        if _SELECTOR is not None and code is None:
            counts["excluded_outside_pdet"] += 1
            continue
        area = geodesic_area_m2(geom)
        if not area > 0:
            _reject(rej, counts, ref, "area_nonpositive", area)
            continue
        attrs, notes = source["attributes"](props)
        for note in notes:
            acc["notes"][note] += 1
        footprint = {"type": "Polygon", "coordinates": coords} if coords is not None else polygon_geojson(geom, precision)
        record = {
            "dataset_id": ctx["dataset_id"],
            "source_ref": ref,
            "footprint": footprint,
            "centroid": {"type": "Point", "coordinates": [round(lon, precision), round(lat, precision)]},
            "area_m2": round(area, 2),
            **attrs,
            "mpio_code": code,
        }
        if ctx["check_records"]:
            errors = prepared_record_errors(record)
            if errors:
                raise ContractError(f"{ref}: registro fuera de contrato: {errors}")
        out.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        counts["prepared"] += 1
        acc["hashes"].append(_geometry_hash(geom))
        acc["codes"].append(int(code) if code else -1)
        acc["areas"].append(area)


def _reject(rej, counts, ref, reason, detail=None):
    counts["rejected"] += 1
    counts[f"rejected:{reason}"] += 1
    rej.write(json.dumps({"source_ref": ref, "reason": reason, "detail": detail}, ensure_ascii=False) + "\n")


def prepare_partition(task: dict) -> dict:
    """Lee una partición en bloques y escribe sus tres archivos. Corre en un proceso aparte."""
    started = time.time()
    source = SOURCES[task["source_key"]]
    src = Path(task["input_path"])
    out_dir = Path(task["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    pid = task["partition_id"]
    paths = {k: out_dir / f"{k}-{pid}.jsonl.gz" for k in ("part", "rejected", "repairs")}
    ctx = {**task, "source": source, "file_name": src.name}
    acc = {"counts": Counter(), "repairs": Counter(), "notes": Counter(), "hashes": [], "codes": [], "areas": []}
    tmp = {k: p.with_name(p.name + ".partial") for k, p in paths.items()}
    with gzip_text_writer(tmp["part"]) as out, gzip_text_writer(tmp["rejected"]) as rej, \
         gzip_text_writer(tmp["repairs"]) as rep:
        chunk = []
        for item in source["features"](src):
            chunk.append(item)
            if len(chunk) >= task["batch_size"]:
                _process_chunk(chunk, ctx, out, rej, rep, acc)
                chunk = []
        if chunk:
            _process_chunk(chunk, ctx, out, rej, rep, acc)
    for k in paths:
        tmp[k].replace(paths[k])
    return {
        "partition_id": pid,
        "counts": dict(acc["counts"]),
        "repairs": dict(acc["repairs"]),
        "notes": dict(acc["notes"]),
        "hashes": np.array(acc["hashes"], dtype=np.uint64),
        "codes": np.array(acc["codes"], dtype=np.int32),
        "areas": np.array(acc["areas"], dtype=np.float64),
        "paths": {k: str(p) for k, p in paths.items()},
        "seconds": round(time.time() - started, 1),
    }


# ---------------------------------------------------------------- duplicados entre particiones


def drop_cross_partition_duplicates(results: list[dict]) -> int:
    """Quita de las particiones posteriores las huellas idénticas ya vistas.

    Se compara un hash de 64 bits del WKB normalizado. Las particiones se
    recorren en orden de identificador, así que la primera aparición se queda.
    """
    seen: set[int] = set()
    removed_total = 0
    for res in results:
        hashes = res["hashes"]
        dup_mask = np.fromiter((int(h) in seen for h in hashes.tolist()), dtype=bool, count=len(hashes))
        seen.update(hashes.tolist())
        if not dup_mask.any():
            continue
        part = Path(res["paths"]["part"])
        rejected = Path(res["paths"]["rejected"])
        tmp = part.with_name(part.name + ".partial")
        rej_tmp = rejected.with_name(rejected.name + ".partial")
        with gzip.open(part, "rt", encoding="utf-8") as src, gzip_text_writer(tmp) as dst, \
             gzip.open(rejected, "rt", encoding="utf-8") as old_rej, gzip_text_writer(rej_tmp) as rej:
            for line in old_rej:
                rej.write(line)
            for line, dup in zip(src, dup_mask.tolist()):
                if dup:
                    ref = json.loads(line)["source_ref"]
                    rej.write(json.dumps({"source_ref": ref, "reason": "duplicate_geometry", "detail": None}) + "\n")
                else:
                    dst.write(line)
        tmp.replace(part)
        rej_tmp.replace(rejected)
        n = int(dup_mask.sum())
        removed_total += n
        c = res["counts"]
        c["prepared"] -= n
        c["rejected"] = c.get("rejected", 0) + n
        c["rejected:duplicate_geometry"] = c.get("rejected:duplicate_geometry", 0) + n
        keep = ~dup_mask
        res["hashes"], res["codes"], res["areas"] = hashes[keep], res["codes"][keep], res["areas"][keep]
    return removed_total


# ---------------------------------------------------------------- reporte


def _quantiles(values: np.ndarray) -> dict:
    if len(values) == 0:
        return {"count": 0}
    q = np.quantile(values, [0, 0.01, 0.1, 0.5, 0.9, 0.99, 1])
    keys = ("min", "p01", "p10", "p50", "p90", "p99", "max")
    return {"count": int(len(values)), "sum": round(float(values.sum()), 2),
            **{k: round(float(v), 2) for k, v in zip(keys, q)}}


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def write_by_municipality(path: Path, results: list[dict], municipalities: list[dict]) -> list[dict]:
    codes = np.concatenate([r["codes"] for r in results]) if results else np.array([], dtype=np.int32)
    areas = np.concatenate([r["areas"] for r in results]) if results else np.array([], dtype=np.float64)
    rows = []
    for m in sorted(municipalities, key=lambda m: m["code"]):
        mask = codes == int(m["code"])
        sel = areas[mask]
        rows.append({
            "mpio_code": m["code"],
            "name": m.get("name") or "",
            "prepared_buildings": int(mask.sum()),
            "area_m2_sum": round(float(sel.sum()), 2),
            "area_m2_median": round(float(np.median(sel)), 2) if len(sel) else "",
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else ["mpio_code"])
        writer.writeheader()
        writer.writerows(rows)
    return rows


def run(root: Path, args) -> int:
    started = datetime.now(timezone.utc)
    cfg = load_config(root)
    source_key = args.source
    source_cfg = cfg["sources"][SOURCES[source_key]["config_key"]]
    prep = cfg["processing"]["buildings"]
    dataset_id = source_cfg["id"]
    selection_on = not args.without_pdet_selection

    manifest_path = root / source_cfg["manifest"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    problems = download_manifest_problems(manifest, dataset_id)
    if problems:
        print("El manifiesto de descarga no cumple el contrato:\n  - " + "\n  - ".join(problems), file=sys.stderr)
        return 2

    partitions = sorted(manifest["partitions"], key=partition_id)
    if args.partitions:
        wanted = set(args.partitions.split(","))
        partitions = [p for p in partitions if partition_id(p) in wanted]
        missing = wanted - {partition_id(p) for p in partitions}
        if missing:
            print(f"Particiones que no están en el manifiesto: {sorted(missing)}", file=sys.stderr)
            return 2
    full_source = not args.partitions

    municipalities, pdet_sha = None, None
    if selection_on:
        try:
            municipalities, pdet_sha = load_pdet_layer(
                root, prep["pdet_input"], prep["pdet_input_report"], cfg["sources"]["pdet_list"]["expected_municipalities"]
            )
        except ContractError as exc:
            print(f"Sin capa PDET verificada: {exc}\n"
                  "Use --without-pdet-selection solo para medir la calidad de la fuente.", file=sys.stderr)
            return 3

    mode_dir = dataset_id if selection_on else f"{dataset_id}_source_pass"
    out_dir = root / prep["output_dir"] / mode_dir
    report_path = root / (source_cfg["prepare_report"] if selection_on else source_cfg["source_pass_report"])
    if selection_on and full_source:
        archive_success_claim(report_path, root / cfg["paths"]["outputs"] / "history" / report_path.name,
                              status="ready_for_load", claim="claims_pdet_selection")

    tasks = []
    inputs = {}
    for part in partitions:
        path, digest = verify_partition_file(root, part)
        pid = partition_id(part)
        inputs[pid] = {"local_path": part["local_path"], "sha256": digest, "url": part.get("url")}
        tasks.append({
            "source_key": source_key, "dataset_id": dataset_id, "partition_id": pid,
            "input_path": str(path), "out_dir": str(out_dir),
            "batch_size": int(cfg["processing"]["batch_size"]), "precision": int(prep["coordinate_precision"]),
            "sliver_ratio": float(prep["sliver_ratio"]), "check_records": bool(args.check_records),
        })
    print(f"{len(tasks)} particiones de '{dataset_id}', selección PDET {'activa' if selection_on else 'desactivada'}, "
          f"{args.workers} procesos")

    def report_progress(i, res):
        c = res["counts"]
        print(f"[{i:3d}/{len(tasks)}] {res['partition_id']}: leídas {c.get('read', 0):>7} "
              f"preparadas {c.get('prepared', 0):>7} rechazadas {c.get('rejected', 0):>3} "
              f"({res['seconds']} s)", flush=True)

    results = []
    if args.workers <= 1:  # mismo proceso: más fácil de depurar; lo usan las pruebas
        _init_worker(municipalities)
        for i, task in enumerate(tasks, start=1):
            results.append(prepare_partition(task))
            report_progress(i, results[-1])
    else:
        with ProcessPoolExecutor(max_workers=args.workers, initializer=_init_worker,
                                 initargs=(municipalities,)) as pool:
            for i, res in enumerate(pool.map(prepare_partition, tasks, chunksize=1), start=1):
                results.append(res)
                report_progress(i, res)

    duplicates = drop_cross_partition_duplicates(results)

    totals = Counter()
    repairs, notes = Counter(), Counter()
    partition_entries = []
    for res in results:
        c = Counter(res["counts"])
        totals.update(c)
        repairs.update(res["repairs"])
        notes.update(res["notes"])
        part_path = Path(res["paths"]["part"])
        partition_entries.append({
            "partition_id": res["partition_id"],
            "input": inputs[res["partition_id"]],
            "output": {"path": _relpath(part_path, root), "sha256": sha256_file(part_path),
                       "bytes": part_path.stat().st_size, "records": c.get("prepared", 0)},
            "rejected_log": _relpath(Path(res["paths"]["rejected"]), root),
            "repairs_log": _relpath(Path(res["paths"]["repairs"]), root),
            "read": c.get("read", 0),
            "rejected": c.get("rejected", 0),
            "repaired": c.get("repaired", 0),
            "excluded_outside_pdet": c.get("excluded_outside_pdet", 0),
            "prepared": c.get("prepared", 0),
            "seconds": res["seconds"],
        })

    by_reason = {k.split(":", 1)[1]: v for k, v in sorted(totals.items()) if k.startswith("rejected:")}
    read, rejected = totals.get("read", 0), totals.get("rejected", 0)
    excluded, prepared = totals.get("excluded_outside_pdet", 0), totals.get("prepared", 0)
    balanced = read == rejected + excluded + prepared and all(
        p["read"] == p["rejected"] + p["excluded_outside_pdet"] + p["prepared"] for p in partition_entries)
    areas = np.concatenate([r["areas"] for r in results]) if results else np.array([])

    if not selection_on:
        status = "source_pass_only"
    elif not full_source:
        status = "sample_only"
    elif balanced:
        status = "ready_for_load"
    else:
        status = "failed"

    by_mpio_path = None
    municipalities_with_buildings = None
    if selection_on:
        by_mpio_path = root / source_cfg["prepare_by_municipality"]
        if not full_source:
            by_mpio_path = by_mpio_path.with_name(by_mpio_path.stem + "_sample.csv")
        rows = write_by_municipality(by_mpio_path, results, municipalities)
        municipalities_with_buildings = sum(1 for r in rows if r["prepared_buildings"] > 0)

    report = {
        "contract": CONTRACT_VERSION,
        "script": "scripts/03_prepare_buildings.py",
        "script_version": SCRIPT_VERSION,
        "dataset_id": dataset_id,
        "status": status,
        "claims_pdet_selection": selection_on and full_source and status == "ready_for_load",
        "claims_full_source": full_source,
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input": {
            "download_manifest": source_cfg["manifest"],
            "download_manifest_sha256": sha256_file(manifest_path),
            "download_generated_at": manifest.get("generated_at"),
            "partitions_in_manifest": len(manifest["partitions"]),
            "partitions_processed": len(partition_entries),
            "pdet_input": prep["pdet_input"] if selection_on else None,
            "pdet_input_sha256": pdet_sha,
        },
        "datasets_document": manifest["datasets_document"],
        "selection": {
            "criterion": "centroide de la huella dentro o sobre el borde de un municipio PDET (shapely intersects)",
            "tie_rule": "borde compartido: se asigna el código DIVIPOLA menor",
            "applied": selection_on,
            "municipalities": len(municipalities) if municipalities else None,
            "municipalities_with_prepared_buildings": municipalities_with_buildings,
            "by_municipality_csv": _relpath(by_mpio_path, root) if by_mpio_path else None,
        },
        "parameters": {
            "batch_size": int(cfg["processing"]["batch_size"]), "workers": args.workers,
            "coordinate_precision": int(prep["coordinate_precision"]), "sliver_ratio": float(prep["sliver_ratio"]),
            "area": "pyproj.Geod(ellps='WGS84').geometry_area_perimeter, valor absoluto, m2",
            "centroid": "shapely centroid en lon/lat",
        },
        "totals": {
            "read": read,
            "rejected": rejected,
            "rejected_by_reason": by_reason,
            "repaired": totals.get("repaired", 0),
            "repaired_by_action": dict(sorted(repairs.items())),
            "excluded_outside_pdet": excluded,
            "prepared": prepared,
            "duplicates_removed": duplicates,
            "centroids_on_shared_boundary": totals.get("centroids_on_shared_boundary", 0),
            "attribute_notes": dict(sorted(notes.items())),
            "area_m2": _quantiles(areas),
            "balanced": balanced,
        },
        "loader_contract": {
            "files": "partitions[].output.path: GeoJSON Lines con gzip, un documento de buildings por línea",
            "add_fields": {"run_id": "ObjectId del documento de ingestion_runs de la partición"},
            "ingestion_runs": "una por partición: source_file = input.local_path, rows_read = read, "
                              "rows_rejected = rejected, rows_loaded = insertados; notes cita excluded_outside_pdet",
            "gate": "cargar solo si status = ready_for_load, claims_pdet_selection = true y el SHA256 de cada archivo coincide",
        },
        "partitions": partition_entries,
    }
    write_json(report_path, report)
    print(f"\nLeídas {read}, rechazadas {rejected}, excluidas fuera de PDET {excluded}, preparadas {prepared} "
          f"(duplicados quitados {duplicates}). Balance {'OK' if balanced else 'FALLA'}. Estado: {status}")
    print(f"Reporte: {_relpath(report_path, root)}")
    return 0 if balanced else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", choices=sorted(SOURCES), required=True)
    parser.add_argument("--workers", type=int, default=max(1, min(4, (os.cpu_count() or 2) - 1)))
    parser.add_argument("--partitions", help="lista de partition_id separada por comas (muestra)")
    parser.add_argument("--without-pdet-selection", action="store_true",
                        help="mide la calidad de la fuente sin la capa PDET; el reporte nunca queda listo para cargar")
    parser.add_argument("--check-records", action="store_true",
                        help="valida cada registro contra el contrato antes de escribirlo (más lento)")
    args = parser.parse_args()
    sys.exit(run(ROOT, args))


if __name__ == "__main__":
    main()
