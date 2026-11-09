"""Obtiene la capa municipal MGN 2025 (Entrega 2, script de Derek).

La vía usada es el WFS 2.0 público de DANE
``sources.mgn.wfs``. Cada respuesta GML se conserva byte a byte. Si esas
páginas ya están en ``data/raw`` y coinciden con
``outputs/mgn_wfs_source_receipt.json``, no se vuelve a contactar el host.
Esa coincidencia prueba la caché, no la cobertura nacional: el recibo tiene
que ser el plan de ``config.yaml`` y la capa tiene que traer
``expected_feature_count`` municipios. Un intento que no lo logra no deja
el manifiesto anterior como si fuera el resultado actual. La página
renderizada del geoportal no se solicita. La verificación TLS queda activa.

Uso:
    python scripts/01_download_mgn.py
    python scripts/01_download_mgn.py --self-check
"""
from __future__ import annotations

import argparse
import re
import sys
import traceback
from pathlib import Path

import geopandas as gpd
import requests

from entrega2_contracts import (
    CONTRACT_VERSION,
    REQUIRED_MGN_FIELDS,
    ContractError,
    archive_success_claim,
    crs_matches,
    epsg_label,
    load_config,
    official_wfs_receipt_problems,
    parse_area_unit,
    select_mgn2025_zip,
    sha256_file,
    wfs_getfeature_url,
    write_json,
)

ROOT = Path(__file__).resolve().parents[1]
VECTOR_SUFFIXES = {".shp", ".gpkg"}
METADATA_SUFFIXES = {".xml", ".txt", ".html", ".htm", ".qmd"}


def fetch_text(url: str) -> str:
    response = requests.get(
        url,
        timeout=90,
        verify=True,
        headers={"User-Agent": "techos-solares-pdet-entrega2"},
    )
    response.raise_for_status()
    response.encoding = response.encoding or "utf-8"
    return response.text


def download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_suffix(dest.suffix + ".partial")
    with requests.get(
        url,
        timeout=120,
        verify=True,
        stream=True,
        headers={"User-Agent": "techos-solares-pdet-entrega2"},
    ) as response:
        response.raise_for_status()
        with temporary.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    temporary.replace(dest)


def metadata_unit(folder: Path) -> tuple[str | None, str | None]:
    found: list[tuple[str, str]] = []
    if not folder.exists():
        return None, None
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in METADATA_SUFFIXES:
            continue
        if path.stat().st_size > 5_000_000:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        unit = parse_area_unit(text)
        if unit:
            found.append((unit, path.name))
    units = {unit for unit, _ in found}
    if len(units) > 1:
        raise ContractError("los metadatos de la capa declaran más de una unidad para MPIO_NAREA")
    if not found:
        return None, None
    return found[0]


def inspect_vectors(folder: Path) -> tuple[Path | None, object | None, list[dict]]:
    notes = []
    matches: list[tuple[Path, object]] = []
    for path in sorted(folder.rglob("*")):
        if path.suffix.lower() not in VECTOR_SUFFIXES:
            continue
        try:
            frame = gpd.read_file(path)
        except Exception as exc:
            notes.append({"path": path.name, "readable": False, "error": str(exc)})
            continue
        columns = [str(column) for column in frame.columns]
        notes.append(
            {
                "path": path.name,
                "readable": True,
                "crs": epsg_label(frame.crs),
                "columns": columns,
                "features": int(len(frame)),
            }
        )
        if set(REQUIRED_MGN_FIELDS).issubset(columns):
            matches.append((path, frame))
    if not matches:
        return None, None, notes
    preferred = [item for item in matches if re.search(r"mpio|municip", item[0].name, re.IGNORECASE)]
    chosen = preferred if len(preferred) == 1 else matches
    if len(chosen) != 1:
        names = ", ".join(path.name for path, _ in chosen)
        raise ContractError(f"hay varias capas con los campos municipales: {names}")
    return chosen[0][0], chosen[0][1], notes


def manifest_from_layer(
    *,
    frame,
    layer_path: Path,
    root: Path,
    expected_crs: str,
    source_page: str,
    file_url: str,
    archive_path: Path | None,
    fixture: bool,
    area_unit: str | None,
    area_unit_source: str | None,
) -> dict:
    missing = [field for field in REQUIRED_MGN_FIELDS if field not in frame.columns]
    nulls = int(frame.geometry.isna().sum()) if frame.geometry is not None else len(frame)
    geometry_types = sorted({geom.geom_type for geom in frame.geometry if geom is not None})
    errors = []
    if missing:
        errors.append("faltan campos: " + ", ".join(missing))
    if len(frame) == 0:
        errors.append("la capa no tiene registros")
    if not crs_matches(frame.crs, expected_crs):
        errors.append(f"CRS {epsg_label(frame.crs) or 'ausente'} no equivale a {expected_crs}")
    archive_hash = sha256_file(archive_path) if archive_path and archive_path.exists() else None
    return {
        "contract": CONTRACT_VERSION,
        "role": "download-manifest",
        "status": "complete" if not errors else "invalid",
        "fixture": fixture,
        "errors": errors,
        "source_page": source_page,
        "resolved_file_url": file_url,
        "filename": archive_path.name if archive_path else None,
        "bytes": archive_path.stat().st_size if archive_path and archive_path.exists() else None,
        "sha256": archive_hash,
        "layer_name": layer_path.name,
        "extracted_layer": layer_path.resolve().relative_to(root.resolve()).as_posix(),
        "crs_expected": expected_crs,
        "crs_epsg": epsg_label(frame.crs),
        "crs_equals_expected": crs_matches(frame.crs, expected_crs),
        "feature_count": int(len(frame)),
        "geometry_types": geometry_types,
        "columns": [str(column) for column in frame.columns if column != "geometry"],
        "required_fields_present": {field: field in frame.columns for field in REQUIRED_MGN_FIELDS},
        "null_geometry_count": nulls,
        "readable": True,
        "area_unit": area_unit,
        "area_unit_source": area_unit_source,
        "claims_national_download": not fixture and not errors,
    }


def write_attempt(path: Path, *, page: str, status: str, error: str) -> None:
    write_json(
        path,
        {
            "contract": CONTRACT_VERSION,
            "role": "download-attempt",
            "status": status,
            "fixture": False,
            "source_page": page,
            "resolved_file_url": None,
            "layer_verified": False,
            "claims_national_download": False,
            "municipalities_prepared": 0,
            "error": error,
        },
    )


WFS_FIELD_MAP = {
    "Código_DANE_departamento": "DPTO_CCDGO",
    "Código_DANE_municipio": "MPIO_CCDGO",
    "Código_DANE_concatenado_departamento_y_municipio": "MPIO_CDPMP",
    "Nombre_departamento": "DPTO_CNMBRE",
    "Nombre_municipio": "MPIO_CNMBR",
    "Área_departamento_en_kilómetros_cuadrados": "MPIO_NAREA",
    "Año_versión_DANE": "MPIO_NANO",
}
AREA_ELEMENT = "Área_departamento_en_kilómetros_cuadrados"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _poslist_lonlat(text: str) -> list[tuple[float, float]]:
    parts = (text or "").split()
    if len(parts) < 8 or len(parts) % 2:
        raise ContractError("posList de GML inválido")
    numbers = [float(item) for item in parts]
    # urn:ogc:def:crs:EPSG::4686 declara latitud y después longitud.
    return [(numbers[index + 1], numbers[index]) for index in range(0, len(numbers), 2)]


def parse_wfs_gml(path: Path) -> tuple[list[dict], set[str]]:
    import xml.etree.ElementTree as ET
    from shapely.geometry import MultiPolygon, Polygon

    features = []
    declared: set[str] = set()
    current = None
    polygons = []
    shell = None
    holes: list = []
    pending = None
    for event, elem in ET.iterparse(path, events=("start", "end")):
        name = _local(elem.tag)
        if event == "start":
            if name == "Municipio":
                current = {}
                polygons = []
            elif name == "Polygon":
                shell = None
                holes = []
            elif name == "MultiSurface":
                srs_name = elem.attrib.get("srsName")
                if srs_name:
                    declared.add(srs_name)
            continue
        if name == "member":
            elem.clear()
            continue
        if current is None:
            continue
        if name in WFS_FIELD_MAP and elem.text and elem.text.strip():
            current[WFS_FIELD_MAP[name]] = elem.text.strip()
        elif name == "posList":
            pending = _poslist_lonlat(elem.text or "")
        elif name == "exterior":
            shell = pending
            pending = None
        elif name == "interior":
            if pending:
                holes.append(pending)
            pending = None
        elif name == "Polygon":
            if not shell or len(shell) < 4:
                raise ContractError(f"{path.name} tiene un polígono sin anillo exterior")
            polygons.append(Polygon(shell, holes))
        elif name == "Municipio":
            if not polygons:
                raise ContractError(f"{path.name} tiene un municipio sin geometría")
            current["geometry"] = polygons[0] if len(polygons) == 1 else MultiPolygon(polygons)
            features.append(current)
            current = None
    return features, declared


def load_wfs_receipt(root: Path, receipt_rel: str) -> dict:
    import json

    path = root / receipt_rel
    if not path.exists():
        raise ContractError(f"no está el recibo {receipt_rel}")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if not receipt.get("pages"):
        raise ContractError("el recibo WFS no trae páginas")
    return receipt


def page_path(raw_dir: Path, page: dict) -> Path:
    return raw_dir / page["name"]


# El WFS de DANE pone en el elemento raíz un atributo timeStamp con la hora de
# cada respuesta. Dos descargas del mismo contenido nunca tienen el mismo
# SHA256 de bytes, así que el recibo guarda además un hash de contenido: el
# SHA256 de la página con el valor de ese único atributo vaciado
# (timeStamp=""). Los bytes descargados no se modifican.
CONTENT_HASH_RULE = (
    "sha256 de la respuesta GML con el valor del atributo timeStamp del elemento raíz "
    'wfs:FeatureCollection vaciado (timeStamp=""); el resto de bytes sin cambios'
)
_ROOT_TAG_RE = re.compile(rb"<wfs:FeatureCollection\b[^>]*>")
_TIMESTAMP_RE = re.compile(rb'\btimeStamp="([^"]*)"')


def _timestamp_value_span(data: bytes) -> tuple[int, int]:
    """Posición del valor de timeStamp dentro del elemento raíz (exactamente uno)."""
    root = _ROOT_TAG_RE.search(data, 0, 65536)
    if root is None:
        raise ContractError("la respuesta no empieza con wfs:FeatureCollection")
    found = list(_TIMESTAMP_RE.finditer(data, root.start(), root.end()))
    if len(found) != 1:
        raise ContractError(f"el elemento raíz trae {len(found)} atributos timeStamp; se espera uno")
    return found[0].start(1), found[0].end(1)


def wfs_content_sha256(data: bytes) -> tuple[str, str]:
    """Hash de contenido de una página WFS y el timeStamp que traía."""
    import hashlib

    start, end = _timestamp_value_span(data)
    digest = hashlib.sha256()
    digest.update(data[:start])
    digest.update(data[end:])
    return digest.hexdigest(), data[start:end].decode("ascii")


def sha256_with_timestamp(data: bytes, timestamp: str) -> str:
    """SHA256 de bytes que tendría la misma página servida con otro timeStamp."""
    import hashlib

    start, end = _timestamp_value_span(data)
    digest = hashlib.sha256()
    digest.update(data[:start])
    digest.update(timestamp.encode("ascii"))
    digest.update(data[end:])
    return digest.hexdigest()


def page_match(path: Path, page: dict) -> dict:
    """``exact`` si coinciden los bytes; ``content`` si solo cambió el timeStamp."""
    result = {"name": page["name"], "match": None, "observed_sha256": None, "server_timestamp": None}
    if not path.is_file():
        return result
    import hashlib

    data = path.read_bytes()
    observed = hashlib.sha256(data).hexdigest()
    result["observed_sha256"] = observed
    try:
        content, timestamp = wfs_content_sha256(data)
        result["server_timestamp"] = timestamp
    except ContractError:
        content = None
    if observed == page["sha256"] and len(data) == page["bytes"]:
        result["match"] = "exact"
    elif content is not None and page.get("content_sha256") == content:
        result["match"] = "content"
    return result


def page_matches(raw_dir: Path, receipt: dict) -> list[dict]:
    return [page_match(page_path(raw_dir, page), page) for page in receipt["pages"]]


def pages_match_receipt(raw_dir: Path, receipt: dict) -> bool:
    return all(item["match"] for item in page_matches(raw_dir, receipt))


def backfill_receipt_content_hashes(root: Path, receipt_rel: str, raw_dir: Path, window_s: int = 900) -> dict:
    """Agrega ``content_sha256`` y el timeStamp original a cada página del recibo.

    Solo con prueba: o la página local es idéntica byte a byte a la del
    recibo, o existe un timeStamp a ``window_s`` segundos de ``retrieved_at``
    con el que la página local reproduce exactamente el ``sha256`` del recibo.
    En ese caso la única diferencia con los bytes originales es ese atributo.
    """
    import json
    from datetime import datetime, timedelta, timezone

    path = root / receipt_rel
    receipt = load_wfs_receipt(root, receipt_rel)
    for page in receipt["pages"]:
        local = page_path(raw_dir, page)
        if not local.is_file():
            raise ContractError(f"falta {local.name}; no se puede probar su contenido")
        data = local.read_bytes()
        content, local_timestamp = wfs_content_sha256(data)
        original = None
        if sha256_file(local) == page["sha256"]:
            original = local_timestamp
        else:
            base = datetime.fromisoformat(page["retrieved_at"]).astimezone(timezone.utc)
            for offset in sorted(range(-window_s, window_s + 1), key=abs):
                candidate = (base + timedelta(seconds=offset)).strftime("%Y-%m-%dT%H:%M:%SZ")
                if sha256_with_timestamp(data, candidate) == page["sha256"]:
                    original = candidate
                    break
        if original is None:
            raise ContractError(
                f"{local.name} difiere del recibo en algo más que el timeStamp; no se registra su contenido"
            )
        if page.get("content_sha256") not in (None, content):
            raise ContractError(f"{local.name}: el recibo ya trae otro content_sha256")
        page["content_sha256"] = content
        page["server_timestamp"] = original
        print(f"[OK] {local.name}: timeStamp original {original}, content_sha256 {content[:12]}…")
    receipt["content_hash_rule"] = CONTENT_HASH_RULE
    path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return receipt


def download_wfs_pages(raw_dir: Path, wfs: dict, receipt: dict) -> None:
    """Un intento por página. Un fallo TLS o de red detiene el host."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    for page in receipt["pages"]:
        dest = page_path(raw_dir, page)
        url = wfs_getfeature_url(wfs, page["start_index"])
        temporary = dest.with_suffix(dest.suffix + ".partial")
        try:
            with requests.get(
                url,
                timeout=600,
                verify=True,
                stream=True,
                headers={"User-Agent": "techos-solares-pdet-entrega2"},
            ) as response:
                response.raise_for_status()
                with temporary.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            handle.write(chunk)
        except requests.exceptions.RequestException as exc:
            if temporary.exists():
                temporary.unlink()
            raise ContractError(
                "el WFS de portalgis no respondió; no se reintenta ese host: "
                + f"{type(exc).__name__}: {exc}"
            ) from exc
        temporary.replace(dest)
        matched = page_match(dest, page)
        if not matched["match"]:
            raise ContractError(
                f"{dest.name} no coincide con el recibo ni por bytes ni por contenido: "
                f"sha256 {matched['observed_sha256']}, {dest.stat().st_size} bytes"
            )


def area_geometry_check(frame) -> dict:
    from pyproj import Geod

    geod = Geod(ellps="WGS84")
    projected = frame.to_crs("EPSG:4326")
    ratios = []
    for geom, raw in zip(projected.geometry, frame["MPIO_NAREA"], strict=True):
        area_m2 = abs(geod.geometry_area_perimeter(geom)[0])
        if area_m2 == 0:
            raise ContractError("geometría con área geodésica cero")
        ratios.append(float(raw) / (area_m2 / 1_000_000))
    ratios.sort()
    count = len(ratios)

    def percentile(fraction: float) -> float:
        return ratios[min(count - 1, max(0, round(fraction * (count - 1))))]

    return {
        "method": "atributo / (área geodésica WGS84 del contorno servido, en km2)",
        "compared_features": count,
        "min": ratios[0],
        "p10": percentile(0.10),
        "median": percentile(0.50),
        "p90": percentile(0.90),
        "max": ratios[-1],
    }


def decide_area_unit(check: dict) -> str | None:
    median = check["median"]
    # m2 would put this ratio near 1e-6. The schema element names square kilometres.
    if 0.5 <= median <= 2:
        return "km2"
    return None


def features_to_frame(features: list[dict]):
    rows = []
    for feature in features:
        row = {field: feature.get(field) for field in (*REQUIRED_MGN_FIELDS, "DPTO_CNMBRE", "MPIO_CCDGO", "MPIO_NANO")}
        row["geometry"] = feature["geometry"]
        rows.append(row)
    frame = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4686")
    frame["MPIO_NAREA"] = frame["MPIO_NAREA"].astype(float)
    frame["MPIO_NANO"] = frame["MPIO_NANO"].astype(int)
    return frame


def write_failed_download(manifest_path: Path, payload: dict) -> None:
    """Sustituye el manifiesto actual sin borrar un éxito anterior."""
    history = manifest_path.with_name("mgn_download_manifest.history.json")
    archive_success_claim(
        manifest_path,
        history,
        status="complete",
        claim="claims_national_download",
    )
    body = dict(payload)
    body["claims_national_download"] = False
    body["national_complete"] = False
    if body.get("status") == "complete":
        body["status"] = "blocked"
    if history.is_file():
        body["history_manifest"] = history.name
    write_json(manifest_path, body)


def run_real(root: Path) -> int:
    import json

    config = load_config(root)
    mgn = config["sources"]["mgn"]
    wfs = mgn["wfs"]
    expected_crs = mgn["source_crs"]
    raw_dir = root / config["paths"]["raw_data"] / "mgn2025" / "wfs"
    outputs = root / config["paths"]["outputs"]
    attempt = outputs / "mgn_download_attempt.json"
    manifest_path = outputs / "mgn_download_manifest.json"
    layer_path = raw_dir / "municipio.gpkg"
    live_request = False
    cache_matches = False
    official_plan = None
    try:
        receipt = load_wfs_receipt(root, wfs["receipt"])
        problems = official_wfs_receipt_problems(wfs, receipt)
        official_plan = not problems
        cache_matches = pages_match_receipt(raw_dir, receipt)
        if problems:
            message = "; ".join(problems)
            write_failed_download(
                manifest_path,
                {
                    "contract": CONTRACT_VERSION,
                    "role": "download-manifest",
                    "status": "blocked",
                    "fixture": False,
                    "official_page_plan": False,
                    "cache_matches_receipt": cache_matches,
                    "live_wfs_request_this_run": False,
                    "layer_verified": False,
                    "readable": False,
                    "extracted_layer": None,
                    "feature_count": None,
                    "source_page": wfs["url"],
                    "bytes_source": None,
                    "error": message,
                },
            )
            write_attempt(attempt, page=wfs["url"], status="blocked", error=message)
            print(f"[FALLA] {message}", file=sys.stderr)
            return 1
        if cache_matches:
            print("[OK] páginas GML ya verificadas contra el recibo; no se contacta portalgis")
        else:
            live_request = True
            print("[descarga] WFS 2.0, un intento por página")
            download_wfs_pages(raw_dir, wfs, receipt)
            cache_matches = True
        matches = page_matches(raw_dir, receipt)
        for item in matches:
            print(f"[recibo] {item['name']}: coincide por {'bytes' if item['match'] == 'exact' else 'contenido (solo cambia timeStamp)'}")
        expected_count = int(wfs["expected_feature_count"])
        existing = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
        if (
            layer_path.exists()
            and existing
            and existing.get("status") == "complete"
            and existing.get("fixture") is False
            and existing.get("claims_national_download") is True
            and existing.get("national_complete") is not False
            and existing.get("official_page_plan") is not False
            and existing.get("feature_count") == expected_count
            and existing.get("sha256") == sha256_file(layer_path)
            and existing.get("source_page_sha256") == [page["sha256"] for page in receipt["pages"]]
        ):
            frame = gpd.read_file(layer_path)
            if len(frame) != expected_count or not crs_matches(frame.crs, expected_crs):
                raise ContractError("la capa guardada no coincide con el recibo o con el CRS de trabajo")
            print(
                f"[OK] capa ya presente, se revalida {layer_path.name}: "
                f"{len(frame)} registros, CRS {epsg_label(frame.crs)}"
            )
            return 0
        features = []
        declared: set[str] = set()
        for page in receipt["pages"]:
            parsed, page_srs = parse_wfs_gml(page_path(raw_dir, page))
            features.extend(parsed)
            declared.update(page_srs)
            print(f"[leída] {page['name']}: {len(parsed)} municipios")
        if declared != {wfs["srs_name"]}:
            raise ContractError(f"srsName observado {sorted(declared)} distinto de {wfs['srs_name']}")
        codes = [feature.get("MPIO_CDPMP") for feature in features]
        if len(features) != expected_count or len(features) != receipt["number_matched"] or len(set(codes)) != len(codes):
            raise ContractError(f"se leyeron {len(features)} features y {len(set(codes))} códigos")
        if any(not re.fullmatch(r"[0-9]{5}", code or "") for code in codes):
            raise ContractError("hay un MPIO_CDPMP que no tiene 5 dígitos")
        frame = features_to_frame(features)
        check = area_geometry_check(frame)
        unit = decide_area_unit(check)
        unit_source = (
            f"elemento GML {AREA_ELEMENT}, alias publicado de MPIO_NAREA; "
            "el diccionario de la Entrega 1 guarda ese valor en area_km2"
            if unit == "km2"
            else None
        )
        layer_path.parent.mkdir(parents=True, exist_ok=True)
        if layer_path.exists():
            layer_path.unlink()
        frame.to_file(layer_path, driver="GPKG")
        stored = gpd.read_file(layer_path)
        manifest = manifest_from_layer(
            frame=stored,
            layer_path=layer_path,
            root=root,
            expected_crs=expected_crs,
            source_page=wfs["url"],
            file_url=wfs["url"] + "?service=WFS&version=2.0.0&request=GetFeature&typeNames=" + wfs["type_name"],
            archive_path=None,
            fixture=False,
            area_unit=unit,
            area_unit_source=unit_source,
        )
        years = frame["MPIO_NANO"].value_counts().to_dict()
        manifest.update(
            {
                "distribution": "ogc-wfs-2.0-gml32",
                "claims_zip_product": False,
                "original_archive_crs_proven": False,
                "served_srs_name": wfs["srs_name"],
                "gml_axis_order": wfs["axis_order"],
                "coordinates_stored": "longitude,latitude",
                "rest_storage_crs": wfs["rest_storage_crs"],
                "crs_note": (
                    "El srsName del GML declara EPSG:4686 con eje latitud/longitud. "
                    "El almacenamiento REST del mismo servicio informa EPSG:3857. "
                    "No se leyó el ZIP ni un .prj de archivo, así que el CRS del archivo original no está probado. "
                    "La capa de trabajo guarda longitud/latitud y usa EPSG:4686 como CRS declarado por el WFS."
                ),
                "field_name_map": {value: key for key, value in WFS_FIELD_MAP.items()},
                "municipality_name_source": "Nombre_municipio, que el servicio REST llama MPIO_CNMBRE; la Entrega 1 lo nombra MPIO_CNMBR",
                "live_wfs_request_this_run": live_request,
                "bytes_source": "preserved-wfs-responses" if not live_request else "live-wfs",
                "cache_matches_receipt": True,
                "official_page_plan": True,
                "expected_feature_count": expected_count,
                "source_page_sha256": [page["sha256"] for page in receipt["pages"]],
                "source_pages": receipt["pages"],
                "source_page_matches": matches,
                "page_match_rule": "exact = mismos bytes que el recibo; content = " + CONTENT_HASH_RULE,
                "sha256": sha256_file(layer_path),
                "filename": wfs["type_name"],
                "bytes": layer_path.stat().st_size,
                "feature_version_year_counts": {str(year): int(count) for year, count in sorted(years.items())},
                "area_geometry_check": check,
                "area_unit_note": (
                    "El nombre del elemento dice departamento aunque el objeto es un municipio. "
                    "La unidad se toma de kilómetros cuadrados en ese nombre y del cociente contra el área geodésica; "
                    "no se usa la magnitud de un solo municipio."
                ),
                "discovery_dataset": receipt.get("discovery_dataset"),
            }
        )
        if unit is None:
            manifest["status"] = "invalid"
            manifest["errors"] = list(manifest["errors"]) + [
                "el cociente entre MPIO_NAREA y el área geodésica no confirma kilómetros cuadrados ni metros cuadrados"
            ]
        national = (
            manifest["status"] == "complete"
            and not manifest["errors"]
            and unit == "km2"
            and manifest["feature_count"] == expected_count
        )
        manifest["national_complete"] = national
        manifest["claims_national_download"] = national
        if not national:
            write_failed_download(manifest_path, manifest)
            write_attempt(attempt, page=wfs["url"], status="invalid", error="; ".join(manifest["errors"]))
            print("[FALLA] " + "; ".join(manifest["errors"]))
            return 1
        write_json(manifest_path, manifest)
        if attempt.exists():
            attempt.unlink()
        print(
            f"[OK] capa {manifest['layer_name']}: {manifest['feature_count']} registros, "
            f"CRS de trabajo {manifest['crs_epsg']}, unidad {manifest['area_unit']}, "
            f"origen de bytes {manifest['bytes_source']}"
        )
        return 0
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        page = wfs.get("url", mgn["url"])
        write_failed_download(
            manifest_path,
            {
                "contract": CONTRACT_VERSION,
                "role": "download-manifest",
                "status": "blocked",
                "fixture": False,
                "official_page_plan": official_plan,
                "cache_matches_receipt": cache_matches,
                "live_wfs_request_this_run": live_request,
                "layer_verified": False,
                "readable": False,
                "extracted_layer": None,
                "feature_count": None,
                "source_page": page,
                "bytes_source": None,
                "error": message,
            },
        )
        write_attempt(attempt, page=page, status="blocked", error=message)
        print(f"[FALLA] {message}", file=sys.stderr)
        return 2


def _square(minx: float, miny: float, maxx: float, maxy: float):
    from shapely.geometry import Polygon

    return Polygon([(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy), (minx, miny)])


def _write_layer(folder: Path, frame, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    frame.to_file(path)
    return path


def run_self_check() -> int:
    import tempfile

    checks: dict[str, bool] = {}

    def check(name: str, condition: bool) -> None:
        checks[name] = bool(condition)
        print(f"[{'OK' if condition else 'FALLA'}] {name}")

    html = """
    <html><body>
      <a href="https://fixture.invalid/otro.zip">Otra cosa</a>
      <a href="https://fixture.invalid/MGN2025_municipal.zip">MGN2025 municipal</a>
      <a href="/descargas/MGN2025_Colombia.zip">Versión MGN2025. Todos los niveles geográficos</a>
    </body></html>
    """
    try:
        chosen = select_mgn2025_zip("https://fixture.invalid/catalogo/", html)
        check("elige el ZIP MGN2025 de todos los niveles presente en el HTML", chosen.endswith("MGN2025_Colombia.zip"))
    except Exception as exc:
        check(f"elige el ZIP MGN2025 de todos los niveles presente en el HTML ({exc})", False)

    try:
        select_mgn2025_zip("https://fixture.invalid/catalogo/", "<a href='https://fixture.invalid/otro.zip'>nada</a>")
        check("rechaza una página sin ZIP MGN2025", False)
    except ContractError:
        check("rechaza una página sin ZIP MGN2025", True)

    ambiguous = """
      <a href="https://fixture.invalid/a-MGN2025.zip">MGN2025 uno</a>
      <a href="https://fixture.invalid/b-MGN2025.zip">MGN2025 dos</a>
    """
    try:
        select_mgn2025_zip("https://fixture.invalid/", ambiguous)
        check("rechaza dos ZIP MGN2025 sin un producto único", False)
    except ContractError:
        check("rechaza dos ZIP MGN2025 sin un producto único", True)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        valid = gpd.GeoDataFrame(
            {
                "MPIO_CDPMP": ["19050"],
                "MPIO_CNMBR": ["ARGELIA"],
                "MPIO_NAREA": [10.0],
                "DPTO_CCDGO": ["19"],
            },
            geometry=[_square(-76.5, 2.2, -76.4, 2.3)],
            crs="EPSG:4686",
        )
        layer = _write_layer(root, valid, "muni.shp")
        (layer.parent / "muni.xml").write_text(
            "<field><name>MPIO_NAREA</name><uom>metros cuadrados</uom></field>",
            encoding="utf-8",
        )
        unit, source = metadata_unit(layer.parent)
        reloaded = gpd.read_file(layer)
        manifest = manifest_from_layer(
            frame=reloaded,
            layer_path=layer,
            root=root,
            expected_crs="EPSG:4686",
            source_page="fixture",
            file_url="fixture://local",
            archive_path=None,
            fixture=True,
            area_unit=unit,
            area_unit_source=source,
        )
        check("capa fixture legible en EPSG:4686", manifest["status"] == "complete" and manifest["crs_equals_expected"])
        check("unidad leída del XML fixture, no inventada", manifest["area_unit"] == "m2")
        check("el manifiesto fixture no afirma una descarga nacional", manifest["claims_national_download"] is False)

        missing_crs = valid.copy()
        missing_crs = missing_crs.set_crs(None, allow_override=True)
        no_crs_path = _write_layer(root / "nocrs", missing_crs, "nocrs.shp")
        prj = no_crs_path.with_suffix(".prj")
        if prj.exists():
            prj.unlink()
        no_crs = gpd.read_file(no_crs_path)
        bad_crs = manifest_from_layer(
            frame=no_crs,
            layer_path=no_crs_path,
            root=root,
            expected_crs="EPSG:4686",
            source_page="fixture",
            file_url="fixture://local",
            archive_path=None,
            fixture=True,
            area_unit=None,
            area_unit_source=None,
        )
        check("falla si el CRS no está presente", bad_crs["status"] == "invalid" and bad_crs["crs_equals_expected"] is False)

        wrong = valid.to_crs("EPSG:4326")
        wrong_path = _write_layer(root / "wrong", wrong, "wrong.shp")
        wrong_frame = gpd.read_file(wrong_path)
        wrong_manifest = manifest_from_layer(
            frame=wrong_frame,
            layer_path=wrong_path,
            root=root,
            expected_crs="EPSG:4686",
            source_page="fixture",
            file_url="fixture://local",
            archive_path=None,
            fixture=True,
            area_unit=None,
            area_unit_source=None,
        )
        check("falla si el CRS es EPSG:4326 y se esperaba EPSG:4686", wrong_manifest["status"] == "invalid")

        incomplete = valid.drop(columns=["MPIO_NAREA"])
        incomplete_path = _write_layer(root / "miss", incomplete, "miss.shp")
        _layer, _frame, notes = inspect_vectors(incomplete_path.parent)
        check("no elige una capa sin MPIO_NAREA", _layer is None and notes and notes[0]["readable"])

        broken_dir = root / "roto"
        broken_dir.mkdir()
        (broken_dir / "roto.shp").write_bytes(b"esto no es un shapefile")
        _layer, _frame, notes = inspect_vectors(broken_dir)
        unreadable = [note for note in notes if note["path"] == "roto.shp"]
        check("un archivo ilegible no se da por válido", _layer is None and bool(unreadable) and unreadable[0]["readable"] is False)

    gml = """<?xml version="1.0" encoding="utf-8"?>
<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0" xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:m="https://fixture.invalid/m">
  <wfs:member><m:Municipio gml:id="f.1">
    <m:Código_DANE_concatenado_departamento_y_municipio>05031</m:Código_DANE_concatenado_departamento_y_municipio>
    <m:Nombre_municipio>AMALFI</m:Nombre_municipio>
    <m:Código_DANE_departamento>05</m:Código_DANE_departamento>
    <m:Área_departamento_en_kilómetros_cuadrados>10.5</m:Área_departamento_en_kilómetros_cuadrados>
    <m:Año_versión_DANE>2024</m:Año_versión_DANE>
    <m:SHAPE><gml:MultiSurface srsName="urn:ogc:def:crs:EPSG::4686"><gml:surfaceMember><gml:Polygon>
      <gml:exterior><gml:LinearRing><gml:posList>6.2 -75.5 6.2 -75.4 6.3 -75.4 6.3 -75.5 6.2 -75.5</gml:posList></gml:LinearRing></gml:exterior>
    </gml:Polygon></gml:surfaceMember></gml:MultiSurface></m:SHAPE>
  </m:Municipio></wfs:member>
</wfs:FeatureCollection>
"""
    with tempfile.TemporaryDirectory() as tmp:
        gml_path = Path(tmp) / "page_0000.gml"
        gml_path.write_text(gml, encoding="utf-8")
        parsed, declared = parse_wfs_gml(gml_path)
        point = list(parsed[0]["geometry"].exterior.coords)[0]
        check(
            "FIXTURE: el GML latitud/longitud se guarda como longitud/latitud y Nombre_municipio pasa a MPIO_CNMBR",
            declared == {"urn:ogc:def:crs:EPSG::4686"}
            and parsed[0]["MPIO_CDPMP"] == "05031"
            and parsed[0]["MPIO_CNMBR"] == "AMALFI"
            and parsed[0]["MPIO_NAREA"] == "10.5"
            and point[0] == -75.5
            and point[1] == 6.2,
        )

    import contextlib
    import io
    import json

    real_wfs = load_config(ROOT)["sources"]["mgn"]["wfs"]
    real_receipt = json.loads((ROOT / real_wfs["receipt"]).read_text(encoding="utf-8"))
    check(
        "el recibo del repositorio sigue el plan oficial de 1122 municipios",
        official_wfs_receipt_problems(real_wfs, real_receipt) == [],
    )

    def mini_config(folder: Path) -> None:
        (folder / "config.yaml").write_text(
            """
paths:
  raw_data: data/raw
  processed_data: data/processed
  outputs: outputs
sources:
  mgn:
    version: MGN2025
    url: "https://portalgis.dane.gov.co/mparcgis/services/MGN2025/Serv_CapasMGN_2025/MapServer/WFSServer"
    source_crs: EPSG:4686
    wfs:
      url: "https://portalgis.dane.gov.co/mparcgis/services/MGN2025/Serv_CapasMGN_2025/MapServer/WFSServer"
      type_name: "Serv_CapasMGN_2025:Municipio"
      srs_name: "urn:ogc:def:crs:EPSG::4686"
      page_size: 200
      start_indexes: [0, 200, 400, 600, 800, 1000]
      axis_order: latitude,longitude
      rest_storage_crs: EPSG:3857
      receipt: outputs/mgn_wfs_source_receipt.json
      expected_feature_count: 1122
  pdet_list:
    file: resources/MunicipiosPDET.xlsx
    sheet: Hoja1
    code_column: "Código DANE Municipio"
    expected_municipalities: 170
    expected_subregions: 16
processing:
  target_crs: EPSG:4326
""",
            encoding="utf-8",
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        mini_config(root)
        gml_path = root / "data/raw/mgn2025/wfs/page_0000.gml"
        gml_path.parent.mkdir(parents=True)
        gml_path.write_text(gml, encoding="utf-8")
        digest = sha256_file(gml_path)
        receipt = {
            "number_matched": 1,
            "pages": [
                {
                    "bytes": gml_path.stat().st_size,
                    "name": "page_0000.gml",
                    "sha256": digest,
                    "start_index": 0,
                    "url": "http://127.0.0.1:9/wfs",
                }
            ],
            "service": "http://127.0.0.1:9/wfs",
            "srs_name": "urn:ogc:def:crs:EPSG::4686",
            "type_name": "Serv_CapasMGN_2025:Municipio",
        }
        (root / "outputs").mkdir()
        (root / "outputs/mgn_wfs_source_receipt.json").write_text(
            json.dumps(receipt), encoding="utf-8"
        )

        def refuse_network(*_args, **_kwargs):
            raise AssertionError("este caso no debe abrir la red")

        original_get = requests.get
        requests.get = refuse_network
        try:
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                code = run_real(root)
        finally:
            requests.get = original_get
        manifest = json.loads((root / "outputs/mgn_download_manifest.json").read_text(encoding="utf-8"))
        check(
            "un recibo de un municipio no se anuncia como descarga nacional",
            code == 1
            and manifest.get("claims_national_download") is False
            and manifest.get("national_complete") is False
            and manifest.get("official_page_plan") is False
            and manifest.get("cache_matches_receipt") is True
            and manifest.get("status") != "complete"
            and "Traceback" not in captured.getvalue(),
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        mini_config(root)
        wfs = load_config(root)["sources"]["mgn"]["wfs"]
        pages = []
        for start in wfs["start_indexes"]:
            pages.append(
                {
                    "bytes": 1,
                    "name": f"page_{int(start):04d}.gml",
                    "sha256": "0" * 64,
                    "start_index": start,
                    "url": wfs_getfeature_url(wfs, start),
                }
            )
        receipt = {
            "number_matched": 1122,
            "pages": pages,
            "service": wfs["url"],
            "srs_name": wfs["srs_name"],
            "type_name": wfs["type_name"],
        }
        outputs = root / "outputs"
        outputs.mkdir()
        (outputs / "mgn_wfs_source_receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
        seeded = {
            "claims_national_download": True,
            "contract": CONTRACT_VERSION,
            "feature_count": 1122,
            "fixture": False,
            "role": "download-manifest",
            "status": "complete",
        }
        write_json(outputs / "mgn_download_manifest.json", seeded)
        seeded_bytes = (outputs / "mgn_download_manifest.json").read_bytes()

        def tls_closed(*_args, **_kwargs):
            raise requests.exceptions.SSLError("UNEXPECTED_EOF_WHILE_READING")

        original_get = requests.get
        requests.get = tls_closed
        try:
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                code = run_real(root)
                second = run_real(root)
        finally:
            requests.get = original_get
        current = json.loads((outputs / "mgn_download_manifest.json").read_text(encoding="utf-8"))
        history = outputs / "mgn_download_manifest.history.json"
        check(
            "un fallo TLS no deja el manifiesto exitoso como resultado actual",
            code == 2
            and second == 2
            and current.get("claims_national_download") is False
            and current.get("national_complete") is False
            and current.get("status") == "blocked"
            and current.get("feature_count") is None
            and current.get("extracted_layer") is None
            and history.is_file()
            and history.read_bytes() == seeded_bytes
            and json.loads(history.read_text(encoding="utf-8"))["claims_national_download"] is True
            and "Traceback" not in captured.getvalue(),
        )

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        header = '<?xml version="1.0"?><wfs:FeatureCollection xmlns:wfs="x" timeStamp="{ts}" numberMatched="1">'
        body = "<wfs:member>contenido</wfs:member></wfs:FeatureCollection>"
        first = (header.format(ts="2026-11-08T20:23:33Z") + body).encode()
        later = (header.format(ts="2026-11-09T02:38:15Z") + body).encode()
        altered = (header.format(ts="2026-11-09T02:38:15Z") + body.replace("contenido", "contenidO")).encode()
        import hashlib

        content, _ts = wfs_content_sha256(first)
        page = {
            "name": "page_0000.gml",
            "bytes": len(first),
            "sha256": hashlib.sha256(first).hexdigest(),
            "content_sha256": content,
            "retrieved_at": "2026-11-08T15:24:23-05:00",
        }
        target = folder / "page_0000.gml"
        target.write_bytes(first)
        check("misma respuesta: coincide por bytes", page_match(target, page)["match"] == "exact")
        target.write_bytes(later)
        later_match = page_match(target, page)
        check(
            "otra descarga que solo cambia timeStamp coincide por contenido",
            later_match["match"] == "content" and later_match["server_timestamp"] == "2026-11-09T02:38:15Z",
        )
        target.write_bytes(altered)
        check("un byte distinto fuera del timeStamp no coincide", page_match(target, page)["match"] is None)
        check(
            "sin content_sha256 en el recibo, otro timeStamp no basta",
            page_match(folder / "page_0000.gml", {**page, "content_sha256": None})["match"] is None,
        )
        doubled = (header.format(ts="a").replace('numberMatched="1">', 'numberMatched="1" timeStamp="b">') + body).encode()
        try:
            wfs_content_sha256(doubled)
            check("dos timeStamp en la raíz se rechazan", False)
        except ContractError:
            check("dos timeStamp en la raíz se rechazan", True)
        check(
            "reponer el timeStamp original reproduce el sha256 del recibo",
            sha256_with_timestamp(later, "2026-11-08T20:23:33Z") == page["sha256"],
        )
        (folder / "outputs").mkdir()
        receipt_rel = "outputs/receipt.json"
        bare = {k: v for k, v in page.items() if k != "content_sha256"}
        (folder / receipt_rel).write_text(json.dumps({"pages": [bare]}), encoding="utf-8")
        target.write_bytes(later)
        with contextlib.redirect_stdout(io.StringIO()):
            filled = backfill_receipt_content_hashes(folder, receipt_rel, folder, window_s=120)
        check(
            "el backfill encuentra el timeStamp original y registra el hash de contenido",
            filled["pages"][0]["content_sha256"] == content
            and filled["pages"][0]["server_timestamp"] == "2026-11-08T20:23:33Z",
        )
        (folder / receipt_rel).write_text(json.dumps({"pages": [bare]}), encoding="utf-8")
        target.write_bytes(altered)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                backfill_receipt_content_hashes(folder, receipt_rel, folder, window_s=120)
            check("el backfill rechaza una página con otro contenido", False)
        except ContractError:
            check("el backfill rechaza una página con otro contenido", True)

    passed = all(checks.values())
    print(f"{'FIXTURE' if passed else 'FALLA'} self-check descarga: {sum(checks.values())}/{len(checks)}")
    return 0 if passed else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--self-check", action="store_true", help="pruebas con fixtures etiquetados; no descarga el MGN")
    parser.add_argument(
        "--backfill-receipt",
        action="store_true",
        help="agrega content_sha256 al recibo solo si las páginas locales reproducen el sha256 original cambiando el timeStamp",
    )
    args = parser.parse_args()
    if args.backfill_receipt:
        try:
            config = load_config(ROOT)
            backfill_receipt_content_hashes(
                ROOT,
                config["sources"]["mgn"]["wfs"]["receipt"],
                ROOT / config["paths"]["raw_data"] / "mgn2025" / "wfs",
            )
        except ContractError as exc:
            print(f"[FALLA] {exc}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)
    if args.self_check:
        try:
            sys.exit(run_self_check())
        except Exception:
            traceback.print_exc()
            sys.exit(1)
    sys.exit(run_real(ROOT))


if __name__ == "__main__":
    main()
