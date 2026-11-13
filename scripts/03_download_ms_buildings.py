"""Descarga Microsoft Building Footprints para los municipios PDET (Entrega 3, tramo de Miguel).

Fuente: índice público ``dataset-links.csv`` de Microsoft Global ML Building
Footprints (``sources.microsoft.index_url``). Cada fila del índice es una
partición quadkey (nivel 9) de un país: un archivo GeoJSON Lines comprimido
con gzip (el nombre termina en ``.csv.gz``, pero el contenido es una
``Feature`` GeoJSON por línea).

Pasos:
1. Descarga el índice y registra URL, fecha de acceso, ``Last-Modified``,
   ``ETag``, tamaño, MD5 (contra ``Content-MD5``) y SHA256.
2. Filtra las filas de ``Location = Colombia`` y valida quadkey, URL y versión
   (la fecha de publicación que aparece en la ruta, p. ej. ``2026-02-03``).
3. Elige solo las particiones cuyo cuadro quadkey toca algún municipio PDET
   (``data/processed/municipalities.geojsonl``, con un margen configurable).
4. Descarga cada partición elegida, comprueba bytes y ``Content-MD5``, y
   calcula su SHA256. Un archivo local que ya coincide no se vuelve a bajar.
5. Lee cada archivo completo: cuenta features, tipos de geometría, campos,
   validez, valores de ``height`` y ``confidence``, extensión y CRS.
6. Escribe el manifiesto (``sources.microsoft.manifest``) y la cobertura por
   municipio (``sources.microsoft.coverage_csv``).

El manifiesto queda en ``complete`` solo si todas las particiones elegidas se
descargaron, coinciden con el servidor y se leyeron sin errores.

Uso:
    python scripts/03_download_ms_buildings.py               # flujo completo
    python scripts/03_download_ms_buildings.py --plan-only   # índice y selección, sin bajar particiones
    python scripts/03_download_ms_buildings.py --offline     # reverifica lo ya descargado sin red
"""
from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
import json
import math
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
import shapely
from pyproj import Geod
from shapely.geometry import box, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

from entrega2_contracts import COLOMBIA_LAT, COLOMBIA_LON, ContractError, load_config, sha256_file, write_json

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_VERSION = "entrega3-ms-download-v1"
USER_AGENT = "techos-solares-pdet-entrega3"
RELEASE_RE = re.compile(r"/global-buildings/(\d{4}-\d{2}-\d{2})/")
QUADKEY_RE = re.compile(r"^[0-3]+$")
BATCH_LINES = 50_000
GEOD = Geod(ellps="WGS84")


# --------------------------------------------------------------------------- quadkeys

def quadkey_to_tile(quadkey: str) -> tuple[int, int, int]:
    """Quadkey de Bing Maps -> (x, y, zoom)."""
    if not QUADKEY_RE.match(quadkey or ""):
        raise ContractError(f"quadkey inválido: {quadkey!r}")
    x = y = 0
    zoom = len(quadkey)
    for i, digit in enumerate(quadkey):
        mask = 1 << (zoom - i - 1)
        value = int(digit)
        if value & 1:
            x |= mask
        if value & 2:
            y |= mask
    return x, y, zoom


def tile_to_quadkey(x: int, y: int, zoom: int) -> str:
    digits = []
    for i in range(zoom, 0, -1):
        mask = 1 << (i - 1)
        digit = (1 if x & mask else 0) + (2 if y & mask else 0)
        digits.append(str(digit))
    return "".join(digits)


def _tile_lat(y: int, zoom: int) -> float:
    n = math.pi - 2.0 * math.pi * y / (1 << zoom)
    return math.degrees(math.atan(math.sinh(n)))


def quadkey_bounds(quadkey: str) -> tuple[float, float, float, float]:
    """(min_lon, min_lat, max_lon, max_lat) del cuadro Web Mercator del quadkey."""
    x, y, zoom = quadkey_to_tile(quadkey)
    n = 1 << zoom
    return (x / n * 360.0 - 180.0, _tile_lat(y + 1, zoom), (x + 1) / n * 360.0 - 180.0, _tile_lat(y, zoom))


def lonlat_to_tile(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    n = 1 << zoom
    lat = max(min(lat, 85.05112878), -85.05112878)
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def tiles_covering(bounds: tuple[float, float, float, float], zoom: int) -> list[str]:
    min_lon, min_lat, max_lon, max_lat = bounds
    x0, y0 = lonlat_to_tile(min_lon, max_lat, zoom)
    x1, y1 = lonlat_to_tile(max_lon, min_lat, zoom)
    return [tile_to_quadkey(x, y, zoom) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]


# --------------------------------------------------------------------------- índice

def parse_size(text: str) -> int | None:
    """'615.5KB' -> bytes aproximados (el índice redondea)."""
    match = re.match(r"^\s*([0-9.]+)\s*([KMGT]?B)\s*$", text or "", re.IGNORECASE)
    if not match:
        return None
    factor = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}[match.group(2).upper()]
    return int(float(match.group(1)) * factor)


def parse_index(path: Path, country: str, zoom: int) -> tuple[list[dict], list[str]]:
    """Filas del país con sus validaciones. Devuelve (filas, problemas)."""
    rows: list[dict] = []
    problems: list[str] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        expected = {"Location", "QuadKey", "Url", "Size", "UploadDate"}
        missing = expected - set(reader.fieldnames or [])
        if missing:
            raise ContractError(f"el índice no trae las columnas {sorted(missing)}")
        for line_no, row in enumerate(reader, start=2):
            if row["Location"] != country:
                continue
            quadkey = row["QuadKey"].strip()
            # El CSV puede perder ceros a la izquierda si alguien lo abre en Excel.
            if quadkey.isdigit() and len(quadkey) < zoom:
                quadkey = quadkey.zfill(zoom)
            url = row["Url"].strip()
            release = RELEASE_RE.search(url)
            issues = []
            if not QUADKEY_RE.match(quadkey) or len(quadkey) != zoom:
                issues.append(f"quadkey {quadkey!r} no es de nivel {zoom}")
            if f"quadkey={quadkey}/" not in url:
                issues.append("la URL no corresponde al quadkey")
            if f"RegionName={country}/" not in url:
                issues.append("la URL no corresponde al país")
            if urlparse(url).scheme != "https":
                issues.append("la URL no es https")
            if not release:
                issues.append("la URL no trae fecha de publicación")
            if issues:
                problems.append(f"línea {line_no}: " + "; ".join(issues))
                continue
            rows.append(
                {
                    "quadkey": quadkey,
                    "url": url,
                    "size_declared": row["Size"].strip(),
                    "size_declared_bytes": parse_size(row["Size"]),
                    "upload_date": row["UploadDate"].strip(),
                    "release": release.group(1),
                    "index_line": line_no,
                }
            )
    return rows, problems


# --------------------------------------------------------------------------- municipios PDET

def load_pdet(root: Path, ms: dict, expected: int) -> tuple[list[dict], str]:
    """Lee el GeoJSONL de la Entrega 2 solo si su reporte lo declara listo y el hash coincide."""
    path = root / ms["pdet_input"]
    report_path = root / ms["pdet_input_report"]
    if not path.exists():
        raise ContractError(f"falta {ms['pdet_input']}; corra antes scripts/02_prepare_municipalities.py")
    if not report_path.exists():
        raise ContractError(f"falta {ms['pdet_input_report']}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "ready_for_load":
        raise ContractError(f"{ms['pdet_input_report']} no está en ready_for_load")
    digest = sha256_file(path)
    if report.get("sha256") and report["sha256"] != digest:
        raise ContractError("el SHA256 del GeoJSONL no coincide con el reporte de preparación")
    municipalities = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            doc = json.loads(line)
            geometry = shape(doc["geometry"])
            if not geometry.is_valid:
                geometry = shapely.make_valid(geometry)
            municipalities.append(
                {
                    "code": doc["_id"],
                    "name": doc.get("name"),
                    "subregion": doc.get("subregion_name"),
                    "geometry": geometry,
                }
            )
    if len(municipalities) != expected:
        raise ContractError(f"el GeoJSONL trae {len(municipalities)} municipios; se esperaban {expected}")
    return municipalities, digest


def geodesic_area_km2(geometry) -> float:
    return abs(GEOD.geometry_area_perimeter(geometry)[0]) / 1e6


def select_partitions(rows: list[dict], municipalities: list[dict], *, buffer_deg: float, zoom: int) -> dict:
    """Cruza cuadros quadkey con municipios PDET.

    Devuelve las filas elegidas (con los municipios que toca cada una), los
    quadkeys que tocan territorio PDET pero no tienen partición publicada y la
    cobertura por municipio.
    """
    geometries = [m["geometry"].buffer(buffer_deg) if buffer_deg else m["geometry"] for m in municipalities]
    tree = STRtree(geometries)
    by_quadkey: dict[str, list[dict]] = {}
    for row in rows:
        by_quadkey.setdefault(row["quadkey"], []).append(row)

    selected = []
    for quadkey in sorted(by_quadkey):
        tile = box(*quadkey_bounds(quadkey))
        hits = sorted(municipalities[i]["code"] for i in tree.query(tile, predicate="intersects"))
        if hits:
            for row in by_quadkey[quadkey]:
                selected.append({**row, "bounds": list(quadkey_bounds(quadkey)), "pdet_municipalities": hits})

    pdet_union = unary_union(geometries)
    tiles_touching = [
        qk for qk in tiles_covering(pdet_union.bounds, zoom) if box(*quadkey_bounds(qk)).intersects(pdet_union)
    ]
    without_partition = sorted(set(tiles_touching) - set(by_quadkey))

    published = unary_union([box(*quadkey_bounds(qk)) for qk in {r["quadkey"] for r in selected}]) if selected else None
    coverage = []
    for municipality in municipalities:
        code = municipality["code"]
        quadkeys = sorted({r["quadkey"] for r in selected if code in r["pdet_municipalities"]})
        total = geodesic_area_km2(municipality["geometry"])
        covered = geodesic_area_km2(municipality["geometry"].intersection(published)) if published is not None else 0.0
        coverage.append(
            {
                "mpio_code": code,
                "name": municipality["name"],
                "subregion": municipality["subregion"],
                "partitions": len(quadkeys),
                "quadkeys": " ".join(quadkeys),
                "area_km2": round(total, 3),
                "area_in_published_partitions_km2": round(covered, 3),
                "share_in_published_partitions": round(covered / total, 6) if total else None,
            }
        )
    return {
        "selected": selected,
        "tiles_touching_pdet": len(tiles_touching),
        "tiles_without_partition": without_partition,
        "coverage": coverage,
    }


# --------------------------------------------------------------------------- red

def head(url: str) -> dict:
    response = requests.head(url, timeout=60, verify=True, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    return dict(response.headers)


def http_metadata(headers: dict) -> dict:
    lower = {k.lower(): v for k, v in headers.items()}
    length = lower.get("content-length")
    return {
        "content_length": int(length) if length and length.isdigit() else None,
        "content_md5": lower.get("content-md5"),
        "etag": lower.get("etag"),
        "last_modified": lower.get("last-modified"),
    }


def file_digests(path: Path) -> dict:
    md5 = hashlib.md5()
    sha = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            md5.update(chunk)
            sha.update(chunk)
            size += len(chunk)
    return {"bytes": size, "md5_b64": base64.b64encode(md5.digest()).decode(), "sha256": sha.hexdigest()}


def server_mismatch(local: dict, meta: dict) -> list[str]:
    problems = []
    if meta.get("content_length") is not None and local["bytes"] != meta["content_length"]:
        problems.append(f"bytes {local['bytes']} != Content-Length {meta['content_length']}")
    if meta.get("content_md5") and local["md5_b64"] != meta["content_md5"]:
        problems.append("MD5 local distinto de Content-MD5")
    return problems


def download(url: str, dest: Path, retries: int = 3) -> dict:
    """Baja ``url`` a ``dest`` vía ``.partial`` y verifica bytes y Content-MD5."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_name(dest.name + ".partial")
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            with requests.get(url, timeout=(30, 300), verify=True, stream=True, headers={"User-Agent": USER_AGENT}) as response:
                response.raise_for_status()
                meta = http_metadata(response.headers)
                with temporary.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            handle.write(chunk)
            local = file_digests(temporary)
            problems = server_mismatch(local, meta)
            if problems:
                raise ContractError("; ".join(problems))
            temporary.replace(dest)
            return {**meta, **local, "attempts": attempt, "cached": False}
        except (requests.RequestException, ContractError) as exc:
            last_error = exc
            temporary.unlink(missing_ok=True)
            time.sleep(2 * attempt)
    raise ContractError(f"no se pudo descargar {url}: {last_error}")


# --------------------------------------------------------------------------- lectura

def _stats(values: list[float]) -> dict:
    known = [v for v in values if v != -1.0]
    return {
        "count": len(values),
        "unknown_minus_one": len(values) - len(known),
        "min": min(known) if known else None,
        "max": max(known) if known else None,
    }


def inspect_partition(path: Path, quadkey: str | None = None, tolerance_deg: float = 0.01) -> dict:
    """Lee el archivo completo y resume campos, geometrías y coordenadas."""
    features = 0
    geometry_types: Counter = Counter()
    property_keys: Counter = Counter()
    top_level_keys: Counter = Counter()
    heights: list[float] = []
    confidences: list[float] = []
    counts = Counter()
    bounds = [math.inf, math.inf, -math.inf, -math.inf]
    tile = box(*quadkey_bounds(quadkey)).buffer(tolerance_deg) if quadkey else None
    batch: list[str] = []

    def flush() -> None:
        if not batch:
            return
        geoms = shapely.from_geojson(batch)
        counts["empty"] += int(shapely.is_empty(geoms).sum())
        counts["invalid"] += int((~shapely.is_valid(geoms)).sum())
        b = shapely.total_bounds(geoms)
        bounds[0], bounds[1] = min(bounds[0], b[0]), min(bounds[1], b[1])
        bounds[2], bounds[3] = max(bounds[2], b[2]), max(bounds[3], b[3])
        centroids = shapely.centroid(geoms)
        xs, ys = shapely.get_x(centroids), shapely.get_y(centroids)
        counts["outside_colombia"] += int(
            ((xs < COLOMBIA_LON[0]) | (xs > COLOMBIA_LON[1]) | (ys < COLOMBIA_LAT[0]) | (ys > COLOMBIA_LAT[1])).sum()
        )
        if tile is not None:
            counts["outside_tile"] += int((~shapely.intersects(tile, geoms)).sum())
        batch.clear()

    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                feature = json.loads(line)
                features += 1
                top_level_keys.update(feature.keys())
                if "crs" in feature:
                    counts["crs_members"] += 1
                properties = feature.get("properties") or {}
                property_keys.update(properties.keys())
                heights.append(float(properties.get("height", -1.0)))
                confidences.append(float(properties.get("confidence", -1.0)))
                geometry_types[(feature.get("geometry") or {}).get("type")] += 1
                batch.append(line)
                if len(batch) >= BATCH_LINES:
                    flush()
            flush()
    except (OSError, EOFError, ValueError, shapely.errors.GEOSException) as exc:
        return {"readable": False, "error": f"{type(exc).__name__}: {exc}", "features": features}

    in_colombia = features > 0 and counts["outside_colombia"] == 0
    return {
        "readable": True,
        "format": "GeoJSON Lines (una Feature por línea) comprimido con gzip",
        "features": features,
        "top_level_keys": dict(top_level_keys),
        "property_keys": dict(property_keys),
        "geometry_types": dict(geometry_types),
        "invalid_geometries": counts["invalid"],
        "empty_geometries": counts["empty"],
        "features_outside_tile": counts["outside_tile"],
        "centroids_outside_colombia": counts["outside_colombia"],
        "bounds": [round(v, 7) for v in bounds] if features else None,
        "height": _stats(heights),
        "confidence": _stats(confidences),
        "crs_members": counts["crs_members"],
        "crs": "EPSG:4326 (RFC 7946, lon/lat)" if in_colombia and counts["crs_members"] == 0 else "revisar",
    }


def partition_problems(row: dict) -> list[str]:
    info = row.get("inspection") or {}
    if not info.get("readable"):
        return [f"no legible: {info.get('error')}"]
    problems = []
    if info["features"] == 0:
        problems.append("sin features")
    if set(info["geometry_types"]) - {"Polygon"}:
        problems.append(f"tipos de geometría inesperados: {sorted(map(str, info['geometry_types']))}")
    if info["centroids_outside_colombia"]:
        problems.append(f"{info['centroids_outside_colombia']} centroides fuera de Colombia (¿ejes invertidos?)")
    if info["crs_members"]:
        problems.append("el archivo declara un miembro crs; revisar el sistema de coordenadas")
    return problems


# --------------------------------------------------------------------------- flujo

def local_path(raw_dir: Path, row: dict) -> Path:
    name = Path(urlparse(row["url"]).path).name
    return raw_dir / row["release"] / f"quadkey={row['quadkey']}" / name


def fetch_partition(row: dict, dest: Path, previous: dict | None, offline: bool) -> dict:
    if dest.exists():
        local = file_digests(dest)
        if offline:
            if not previous or previous.get("sha256") != local["sha256"]:
                raise ContractError("modo offline: el archivo local no coincide con el manifiesto anterior")
            kept = {k: previous.get(k) for k in ("content_length", "content_md5", "etag", "last_modified")}
            return {**kept, **local, "cached": True, "attempts": 0}
        meta = http_metadata(head(row["url"]))
        if not server_mismatch(local, meta):
            return {**meta, **local, "cached": True, "attempts": 0}
    if offline:
        raise ContractError("modo offline: falta el archivo local")
    return download(row["url"], dest)


def process_partition(row: dict, raw_dir: Path, root: Path, previous: dict | None, offline: bool) -> dict:
    dest = local_path(raw_dir, row)
    result = {**row, "local_path": dest.relative_to(root).as_posix()}
    try:
        result["download"] = fetch_partition(row, dest, previous, offline)
        result["inspection"] = inspect_partition(dest, row["quadkey"])
    except (ContractError, requests.RequestException, OSError) as exc:
        result["error"] = str(exc)
    problems = [result["error"]] if "error" in result else partition_problems(result)
    result["problems"] = problems
    result["status"] = "ok" if not problems else "failed"
    return result


def write_coverage_csv(path: Path, coverage: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(coverage[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(coverage)


def summarize(ok: list[dict]) -> dict:
    geometry_types: Counter = Counter()
    property_keys: Counter = Counter()
    for r in ok:
        geometry_types.update(r["inspection"]["geometry_types"])
        property_keys.update(r["inspection"]["property_keys"])

    def known(field: str) -> int:
        return sum(r["inspection"][field]["count"] - r["inspection"][field]["unknown_minus_one"] for r in ok)

    return {
        "bytes_downloaded": sum(r["download"]["bytes"] for r in ok),
        "features": sum(r["inspection"]["features"] for r in ok),
        "invalid_geometries": sum(r["inspection"]["invalid_geometries"] for r in ok),
        "empty_geometries": sum(r["inspection"]["empty_geometries"] for r in ok),
        "height_known": known("height"),
        "confidence_known": known("confidence"),
        "geometry_types": dict(geometry_types),
        "property_keys": dict(property_keys),
    }


def run(root: Path, *, plan_only: bool, offline: bool, workers: int) -> int:
    config = load_config(root)
    ms = config["sources"]["microsoft"]
    raw_dir = root / config["paths"]["raw_data"] / ms["raw_dir"]
    manifest_path = root / ms["manifest"]
    previous_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    previous_by_url = {p["url"]: p.get("download", {}) for p in previous_manifest.get("partitions", [])}
    started = datetime.now(timezone.utc)

    # 1. Índice
    index_path = raw_dir / "dataset-links.csv"
    if offline:
        if not index_path.exists() or not previous_manifest:
            raise ContractError("modo offline: faltan el índice local o el manifiesto anterior")
        index_download = {**previous_manifest["index"]["download"], **file_digests(index_path), "cached": True}
        if previous_manifest["index"]["download"].get("sha256") != index_download["sha256"]:
            raise ContractError("modo offline: el índice local no coincide con el manifiesto anterior")
        accessed_at = previous_manifest["index"]["accessed_at"]
    else:
        print(f"[1/5] índice: {ms['index_url']}")
        index_download = download(ms["index_url"], index_path)
        accessed_at = started.isoformat(timespec="seconds")

    # 2. Filas del país
    rows, index_problems = parse_index(index_path, ms["country"], ms["quadkey_zoom"])
    releases = sorted({r["release"] for r in rows})
    print(f"[2/5] {len(rows)} particiones de {ms['country']}; versión {releases}; {len(index_problems)} filas rechazadas")
    if not rows:
        raise ContractError(f"el índice no trae filas para {ms['country']}")
    if len(releases) != 1:
        raise ContractError(f"el índice mezcla versiones para {ms['country']}: {releases}")
    release = releases[0]

    # 3. Selección
    municipalities, pdet_sha = load_pdet(root, ms, config["sources"]["pdet_list"]["expected_municipalities"])
    selection = select_partitions(rows, municipalities, buffer_deg=ms["selection_buffer_deg"], zoom=ms["quadkey_zoom"])
    selected = selection["selected"]
    without = [c["mpio_code"] for c in selection["coverage"] if c["partitions"] == 0]
    declared = sum(r["size_declared_bytes"] or 0 for r in selected)
    print(
        f"[3/5] {len(selected)} de {len(rows)} particiones tocan los {len(municipalities)} municipios PDET "
        f"(~{declared / 1024**2:.1f} MB declarados); municipios sin partición: {len(without)}"
    )

    # 4. Descarga y lectura
    if plan_only:
        results = [{**r, "status": "planned"} for r in selected]
    else:
        print(f"[4/5] descarga y lectura con {workers} hilos")
        results = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(process_partition, row, raw_dir, root, previous_by_url.get(row["url"]), offline)
                for row in selected
            ]
            for done, future in enumerate(as_completed(futures), start=1):
                result = future.result()
                results.append(result)
                tag = "OK" if result["status"] == "ok" else "FALLA"
                feats = (result.get("inspection") or {}).get("features")
                cached = " (caché)" if (result.get("download") or {}).get("cached") else ""
                print(f"  [{done}/{len(selected)}] {tag} {result['quadkey']}: {feats} features{cached}")
        results.sort(key=lambda r: r["quadkey"])

    failed = [r["quadkey"] for r in results if r["status"] == "failed"]
    ok = [r for r in results if r["status"] == "ok"]
    if plan_only:
        status = "plan_only"
    elif failed or without:
        status = "incomplete"
    else:
        status = "complete"

    manifest = {
        "script": "scripts/03_download_ms_buildings.py",
        "script_version": SCRIPT_VERSION,
        "status": status,
        "claims_pdet_coverage": status == "complete",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {
            "dataset_id": ms["id"],
            "name": ms["name"],
            "license": ms["license"],
            "url": ms["url"],
            "country": ms["country"],
            "release": release,
            "upload_dates": sorted({r["upload_date"] for r in rows}),
            "format": "GeoJSON Lines comprimido con gzip, una partición por quadkey",
            "crs": "EPSG:4326 (GeoJSON RFC 7946, orden lon/lat); los archivos no declaran crs",
            "fields": {
                "height": "altura estimada en metros; -1 si no se conoce",
                "confidence": "confianza de la detección; -1 si no se publica",
            },
        },
        "datasets_document": {
            "_id": ms["id"],
            "name": ms["name"],
            "version": release,
            "license": ms["license"],
            "url": ms["index_url"],
            "accessed_at": accessed_at,
        },
        "index": {
            "url": ms["index_url"],
            "accessed_at": accessed_at,
            "local_path": index_path.relative_to(root).as_posix(),
            "download": index_download,
            "rows_country": len(rows),
            "rows_rejected": index_problems,
        },
        "selection": {
            "method": (
                f"cuadro Web Mercator de cada quadkey de nivel {ms['quadkey_zoom']} intersecado con los "
                f"municipios PDET ampliados {ms['selection_buffer_deg']} grados"
            ),
            "pdet_input": ms["pdet_input"],
            "pdet_input_sha256": pdet_sha,
            "pdet_municipalities": len(municipalities),
            "municipalities_without_partition": without,
            "tiles_touching_pdet": selection["tiles_touching_pdet"],
            "tiles_touching_pdet_without_partition": selection["tiles_without_partition"],
            "coverage_csv": ms["coverage_csv"],
        },
        "totals": {
            "partitions_country": len(rows),
            "partitions_selected": len(selected),
            "partitions_ok": len(ok),
            "partitions_failed": failed,
            "bytes_declared_selected": declared,
            **summarize(ok),
        },
        "partitions": results,
    }
    write_json(manifest_path, manifest)
    write_coverage_csv(root / ms["coverage_csv"], selection["coverage"])
    print(f"[5/5] manifiesto: {ms['manifest']} ({status}); cobertura: {ms['coverage_csv']}")
    if status == "incomplete":
        print(f"[FALLA] particiones con problemas: {failed}; municipios sin partición: {without}", file=sys.stderr)
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plan-only", action="store_true", help="descarga el índice y elige particiones, sin bajarlas")
    parser.add_argument("--offline", action="store_true", help="no usa la red; reverifica los archivos locales contra el manifiesto")
    parser.add_argument("--workers", type=int, default=4, help="descargas en paralelo (por defecto 4)")
    args = parser.parse_args()
    try:
        sys.exit(run(ROOT, plan_only=args.plan_only, offline=args.offline, workers=max(1, args.workers)))
    except (ContractError, requests.RequestException) as exc:
        print(f"[FALLA] {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
