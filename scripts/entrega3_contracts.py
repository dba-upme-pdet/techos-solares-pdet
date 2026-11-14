"""Contrato de la Entrega 3 entre descarga, preparación y carga de huellas.

Lo usa ``03_prepare_buildings.py``. Los módulos de descarga (Microsoft, Google)
y la carga en MongoDB (``04_load_buildings.py``) pueden importarlo para hablar
el mismo idioma. Este módulo no descarga, no inserta y no asigna ``run_id``.

Tres piezas:

1. Manifiesto de descarga: lo que cada módulo de descarga entrega a la
   preparación (``download_manifest_problems``).
2. Registro preparado: un documento de ``buildings`` sin ``run_id``, que
   cumple el validador de ``00_init_db.py`` en cuanto la carga le agrega
   ``run_id`` (``prepared_record_errors``).
3. Criterio espacial: una edificación entra si su centroide cae dentro (o en
   el borde) de un municipio PDET; si cae en dos, gana el código DIVIPOLA
   menor (``PdetSelector``).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import shapely
from pyproj import Geod
from shapely.geometry import shape

from entrega2_contracts import COLOMBIA_LAT, COLOMBIA_LON, ContractError, sha256_file

CONTRACT_VERSION = "entrega3-buildings-v1"
GEOD = Geod(ellps="WGS84")

# Campos del registro preparado. Coinciden con SCHEMAS["buildings"] de
# 00_init_db.py; run_id lo pone la carga, igual que loaded_at en la Entrega 2.
PREPARED_FIELDS = (
    "dataset_id",
    "source_ref",
    "footprint",
    "centroid",
    "area_m2",
    "area_src_m2",
    "confidence",
    "height_m",
    "mpio_code",
)
LOADER_FIELDS = ("run_id",)

# Motivos de rechazo: la edificación no pasa a la carga.
REJECT_REASONS = {
    "json_invalid": "la línea no es JSON",
    "feature_invalid": "no es una Feature GeoJSON con geometry",
    "geometry_unparseable": "shapely no puede construir la geometría",
    "geometry_empty": "geometría vacía",
    "geometry_type_unsupported": "no es Polygon (el esquema pide Polygon)",
    "outside_colombia_window": "algún vértice fuera de la ventana de Colombia (ejes o CRS)",
    "repair_degenerate": "make_valid no deja área",
    "repair_split_multipolygon": "make_valid la parte en varios polígonos de tamaño comparable",
    "area_nonpositive": "área geodésica <= 0",
    "duplicate_geometry": "la misma huella ya salió de otra partición",
}
# Reparaciones: la edificación pasa, con la geometría corregida.
REPAIR_ACTIONS = {
    "make_valid": "make_valid devolvió un Polygon válido",
    "make_valid_dropped_slivers": "make_valid dejó astillas; se conserva el polígono mayor",
}
# Avisos de atributo: la edificación pasa con el atributo en null.
ATTRIBUTE_NOTES = {
    "confidence_unknown": "confidence -1 o ausente: null",
    "confidence_out_of_range": "confidence fuera de [0, 1]: null",
    "height_unknown": "height -1 o ausente: null",
    "height_out_of_range": "height negativa distinta de -1: null",
}

DOWNLOAD_REQUIRED_TOP = ("status", "claims_pdet_coverage", "datasets_document", "partitions", "source")
DATASET_DOC_FIELDS = ("_id", "name", "version", "license", "url", "accessed_at")


# ---------------------------------------------------------------- manifiesto de descarga


def partition_id(partition: dict) -> str | None:
    """Identificador de partición: ``partition_id`` (contrato) o ``quadkey`` (Microsoft)."""
    value = partition.get("partition_id", partition.get("quadkey"))
    return str(value) if value not in (None, "") else None


def download_manifest_problems(manifest: dict, dataset_id: str) -> list[str]:
    """Problemas que impiden preparar desde un manifiesto de descarga.

    Requisitos comunes para Microsoft (Miguel) y Google (Sebastián):
    ``status = complete``, ``claims_pdet_coverage = true``, un
    ``datasets_document`` con los seis campos del validador de ``datasets`` y
    ``_id`` igual a la fuente, y por partición ``status = ok``, un
    identificador, ``local_path`` y ``download.sha256``.
    """
    problems = [f"falta {key}" for key in DOWNLOAD_REQUIRED_TOP if key not in manifest]
    if problems:
        return problems
    if manifest.get("status") != "complete":
        problems.append(f"status es {manifest.get('status')!r}, no 'complete'")
    if manifest.get("claims_pdet_coverage") is not True:
        problems.append("claims_pdet_coverage no es true")
    doc = manifest.get("datasets_document") or {}
    for key in DATASET_DOC_FIELDS:
        if not doc.get(key):
            problems.append(f"datasets_document sin {key}")
    if doc.get("_id") != dataset_id:
        problems.append(f"datasets_document._id es {doc.get('_id')!r}, no {dataset_id!r}")
    if (manifest.get("source") or {}).get("dataset_id") not in (None, dataset_id):
        problems.append("source.dataset_id no coincide con la fuente")
    partitions = manifest.get("partitions") or []
    if not partitions:
        problems.append("el manifiesto no trae particiones")
    seen: set[str] = set()
    for index, part in enumerate(partitions):
        pid = partition_id(part)
        label = pid or f"#{index}"
        if not pid:
            problems.append(f"partición {label} sin partition_id ni quadkey")
        elif pid in seen:
            problems.append(f"partición {label} repetida")
        else:
            seen.add(pid)
        if part.get("status") != "ok":
            problems.append(f"partición {label} con status {part.get('status')!r}")
        if not part.get("local_path"):
            problems.append(f"partición {label} sin local_path")
        if not (part.get("download") or {}).get("sha256"):
            problems.append(f"partición {label} sin download.sha256")
    return problems


def verify_partition_file(root: Path, partition: dict) -> tuple[Path, str]:
    """Ruta local y SHA256; error si el archivo no es el del manifiesto."""
    path = root / partition["local_path"]
    if not path.is_file():
        raise ContractError(f"falta {partition['local_path']}; corra antes la descarga")
    digest = sha256_file(path)
    if digest != partition["download"]["sha256"]:
        raise ContractError(f"SHA256 de {partition['local_path']} no coincide con el manifiesto")
    return path, digest


# ---------------------------------------------------------------- capa PDET


def load_pdet_layer(root: Path, geojsonl: str, report: str, expected: int) -> tuple[list[dict], str]:
    """Lee los municipios PDET de la Entrega 2 con la misma compuerta que la descarga.

    Exige ``status = ready_for_load`` en el reporte y que el SHA256 del
    GeoJSONL coincida. Devuelve ``(municipios, sha256)``.
    """
    path, report_path = root / geojsonl, root / report
    if not path.exists():
        raise ContractError(f"falta {geojsonl}; corra antes scripts/02_prepare_municipalities.py")
    if not report_path.exists():
        raise ContractError(f"falta {report}")
    meta = json.loads(report_path.read_text(encoding="utf-8"))
    if meta.get("status") != "ready_for_load":
        raise ContractError(f"{report} no está en ready_for_load")
    digest = sha256_file(path)
    if meta.get("sha256") and meta["sha256"] != digest:
        raise ContractError("el SHA256 del GeoJSONL no coincide con el reporte de preparación")
    municipalities = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                doc = json.loads(line)
                municipalities.append({"code": doc["_id"], "name": doc.get("name"), "geometry": doc["geometry"]})
    if len(municipalities) != expected:
        raise ContractError(f"el GeoJSONL trae {len(municipalities)} municipios; se esperaban {expected}")
    return municipalities, digest


class PdetSelector:
    """Criterio espacial de la Entrega 3.

    Una edificación pertenece al territorio de interés si su centroide
    intersecta (dentro o sobre el borde) el polígono de un municipio PDET.
    Si intersecta dos (borde compartido), se asigna al código DIVIPOLA menor:
    la regla es determinista y cada edificación cuenta una sola vez.
    Es la misma prueba que la fase 3 hará con ``$geoWithin`` sobre
    ``buildings.centroid``; aquí se usa para no cargar lo que cae fuera.
    """

    def __init__(self, municipalities: list[dict]):
        ordered = sorted(municipalities, key=lambda m: m["code"])
        self.codes = np.array([m["code"] for m in ordered], dtype=object)
        geoms = []
        for m in ordered:
            geom = m["geometry"] if isinstance(m["geometry"], shapely.Geometry) else shape(m["geometry"])
            if not geom.is_valid:
                geom = shapely.make_valid(geom)
            geoms.append(geom)
        self.geoms = np.array(geoms, dtype=object)
        shapely.prepare(self.geoms)
        self.tree = shapely.STRtree(self.geoms)

    def assign(self, lons: np.ndarray, lats: np.ndarray) -> tuple[list[str | None], int]:
        """Código por punto (o None) y cuántos puntos tocaron más de un municipio."""
        result: list[str | None] = [None] * len(lons)
        if len(lons) == 0:
            return result, 0
        points = shapely.points(lons, lats)
        point_idx, geom_idx = self.tree.query(points, predicate="intersects")
        # ``geoms`` está ordenado por código: el índice menor es el código menor.
        hits: dict[int, int] = {}
        multi: set[int] = set()
        for p, g in zip(point_idx.tolist(), geom_idx.tolist()):
            if p in hits:
                multi.add(p)
                hits[p] = min(hits[p], g)
            else:
                hits[p] = g
        for p, g in hits.items():
            result[p] = self.codes[g]
        return result, len(multi)


# ---------------------------------------------------------------- geometría y registro


def coords_in_colombia(geom) -> bool:
    xmin, ymin, xmax, ymax = geom.bounds
    return (
        COLOMBIA_LON[0] <= xmin and xmax <= COLOMBIA_LON[1] and COLOMBIA_LAT[0] <= ymin and ymax <= COLOMBIA_LAT[1]
    )


def geodesic_area_m2(geom) -> float:
    """Área geodésica en el elipsoide WGS84 (pyproj.Geod), siempre positiva."""
    area, _ = GEOD.geometry_area_perimeter(geom)
    return abs(area)


def repair_polygon(geom, sliver_ratio: float):
    """Devuelve ``(polígono, acción)`` o ``(None, motivo_de_rechazo)``.

    ``make_valid`` puede devolver una colección. Se conservan solo partes con
    área; si queda una, es la reparación; si quedan varias y las menores suman
    menos de ``sliver_ratio`` del área, se conserva la mayor (astillas); si no,
    se rechaza porque el esquema pide un solo Polygon y escoger uno cambiaría
    la edificación.
    """
    fixed = shapely.make_valid(geom)
    parts = [p for p in shapely.get_parts(fixed) if p.geom_type in ("Polygon", "MultiPolygon")]
    polys = []
    for part in parts:
        polys.extend(shapely.get_parts(part) if part.geom_type == "MultiPolygon" else [part])
    polys = [p for p in polys if not p.is_empty and p.area > 0]
    if not polys:
        return None, "repair_degenerate"
    if len(polys) == 1:
        return polys[0], "make_valid"
    polys.sort(key=lambda p: p.area, reverse=True)
    total = sum(p.area for p in polys)
    if (total - polys[0].area) / total < sliver_ratio:
        return polys[0], "make_valid_dropped_slivers"
    return None, "repair_split_multipolygon"


def polygon_geojson(geom, precision: int) -> dict:
    """GeoJSON Polygon en orden lon/lat, coordenadas redondeadas."""
    rings = [geom.exterior] + list(geom.interiors)
    return {
        "type": "Polygon",
        "coordinates": [[[round(x, precision), round(y, precision)] for x, y in ring.coords] for ring in rings],
    }


def clean_unit_interval(value, unknown_note: str, range_note: str) -> tuple[float | None, str | None]:
    """confidence: -1/ausente -> null; fuera de [0, 1] -> null con aviso."""
    if value is None or isinstance(value, bool):
        return None, unknown_note
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None, range_note
    if number == -1:
        return None, unknown_note
    if not (0.0 <= number <= 1.0) or number != number:
        return None, range_note
    return number, None


def clean_height(value) -> tuple[float | None, str | None]:
    """height: -1/ausente -> null (regla de la Entrega 1); otra negativa -> null con aviso."""
    if value is None or isinstance(value, bool):
        return None, "height_unknown"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None, "height_out_of_range"
    if number == -1:
        return None, "height_unknown"
    if number < 0 or number != number:
        return None, "height_out_of_range"
    return number, None


def prepared_record_errors(record: dict) -> list[str]:
    """Reglas del validador ``buildings`` de ``00_init_db.py`` sobre un registro sin run_id."""
    errors = []
    for key in LOADER_FIELDS:
        if key in record:
            errors.append(f"{key} debe agregarlo la carga, no la preparación")
    for key in ("dataset_id", "footprint", "centroid", "area_m2"):
        if key not in record:
            errors.append(f"falta {key}")
    extra = set(record) - set(PREPARED_FIELDS)
    if extra:
        errors.append("campos fuera del contrato: " + ", ".join(sorted(extra)))
    if not isinstance(record.get("dataset_id"), str) or not record.get("dataset_id"):
        errors.append("dataset_id no es string")
    if record.get("source_ref") is not None and not isinstance(record["source_ref"], str):
        errors.append("source_ref no es string ni null")
    fp = record.get("footprint")
    if not isinstance(fp, dict) or fp.get("type") != "Polygon" or not fp.get("coordinates"):
        errors.append("footprint no es GeoJSON Polygon")
    ct = record.get("centroid")
    if not isinstance(ct, dict) or ct.get("type") != "Point" or len(ct.get("coordinates") or []) != 2:
        errors.append("centroid no es GeoJSON Point")
    else:
        lon, lat = ct["coordinates"]
        if not (COLOMBIA_LON[0] <= lon <= COLOMBIA_LON[1] and COLOMBIA_LAT[0] <= lat <= COLOMBIA_LAT[1]):
            errors.append("centroid fuera de Colombia o con ejes invertidos")
    area = record.get("area_m2")
    if isinstance(area, bool) or not isinstance(area, (int, float)) or area < 0:
        errors.append("area_m2 no es número >= 0")
    for key in ("area_src_m2", "height_m"):
        value = record.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            errors.append(f"{key} no es número ni null")
    conf = record.get("confidence")
    if conf is not None and (isinstance(conf, bool) or not isinstance(conf, (int, float)) or not 0 <= conf <= 1):
        errors.append("confidence fuera de [0, 1]")
    code = record.get("mpio_code")
    if code is not None and (not isinstance(code, str) or not re.fullmatch(r"[0-9]{5}", code)):
        errors.append("mpio_code no es DIVIPOLA de 5 dígitos")
    return errors
