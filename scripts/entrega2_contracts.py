"""Contrato de la Entrega 2 entre descarga, validación, preparación y carga.

Lo usan ``01_download_mgn.py`` y ``02_prepare_municipalities.py``.
Samuel, Miguel y Sebastián pueden importarlo. Este módulo no descarga,
no inserta y no asigna ``loaded_at``.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urljoin

import yaml
from pyproj import CRS

CONTRACT_VERSION = "entrega2-mgn-v1"
REQUIRED_MGN_FIELDS = ("MPIO_CDPMP", "MPIO_CNMBR", "MPIO_NAREA", "DPTO_CCDGO")
# Ventana geográfica de Colombia en grados. Un vértice fuera de ella indica
# eje intercambiado o CRS distinto de WGS84. No es un límite administrativo.
COLOMBIA_LON = (-82.0, -66.0)
COLOMBIA_LAT = (-5.0, 16.0)
MONGO_DOC_LIMIT = 16 * 1024 * 1024
SIZE_GUARD_BYTES = 15 * 1024 * 1024
PDET_COLUMNS = {
    "subregion_id": "id",
    "subregion_name": "Subregión PDET",
    "dpto_code": "Código DANE Departamento",
    "dpto_name": "Departamento",
    "mpio_name": "Municipio",
}

_UNIT_PATTERNS = (
    (
        "km2",
        re.compile(
            r"kil[oó]metros?\s+cuadrados|square\s+kilomet(?:er|re)s|\bkm(?:\^)?2\b",
            re.IGNORECASE,
        ),
    ),
    (
        "m2",
        re.compile(
            r"metros?\s+cuadrados|square\s+met(?:er|re)s|\bm(?:\^)?2\b|\bsqm\b",
            re.IGNORECASE,
        ),
    ),
)


class ContractError(Exception):
    """El archivo o la capa no cumplen el contrato de la Entrega 2."""


def load_config(root: Path) -> dict:
    return yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def archive_success_claim(current: Path, history: Path, *, status: str, claim: str) -> bool:
    """Copia un resultado exitoso sin modificarlo. No pisa una copia ya guardada.

    Un archivo que no está en ese estado exitoso no entra al historial.
    """
    if history.exists() or not current.is_file():
        return False
    try:
        payload = json.loads(current.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if payload.get("status") != status or payload.get(claim) is not True:
        return False
    history.parent.mkdir(parents=True, exist_ok=True)
    history.write_bytes(current.read_bytes())
    return True


def wfs_getfeature_url(wfs: dict, start_index: int) -> str:
    """URL KVP del GetFeature configurado. El recibo tiene que repetirla."""
    params = (
        ("service", "WFS"),
        ("version", "2.0.0"),
        ("request", "GetFeature"),
        ("typeNames", wfs["type_name"]),
        ("srsName", wfs["srs_name"]),
        ("count", wfs["page_size"]),
        ("startIndex", start_index),
    )
    query = "&".join(f"{key}={value}" for key, value in params)
    return wfs["url"] + "?" + query


def official_wfs_receipt_problems(wfs: dict, receipt: dict) -> list[str]:
    """El recibo describe el plan oficial solo si coincide con ``config.yaml``.

    Que los archivos locales tengan el SHA256 del recibo es otra pregunta:
    eso es integridad de la caché, no cobertura nacional.
    """
    problems: list[str] = []
    if receipt.get("service") != wfs.get("url"):
        problems.append("el servicio del recibo no es el WFS configurado")
    if receipt.get("type_name") != wfs.get("type_name") or receipt.get("srs_name") != wfs.get("srs_name"):
        problems.append("el recibo no describe el typeName y el srsName configurados")
    expected_count = wfs.get("expected_feature_count")
    if not isinstance(expected_count, int) or isinstance(expected_count, bool) or expected_count <= 0:
        problems.append("config.yaml no declara expected_feature_count de la capa nacional")
    elif receipt.get("number_matched") != expected_count:
        problems.append(
            f"number_matched {receipt.get('number_matched')} no es la capa nacional de {expected_count}"
        )
    indexes = list(wfs.get("start_indexes") or [])
    pages = list(receipt.get("pages") or [])
    observed = [page.get("start_index") for page in pages]
    if observed != indexes:
        problems.append("las páginas del recibo no son el plan startIndex configurado")
        return problems
    for page, start in zip(pages, indexes):
        if page.get("name") != f"page_{int(start):04d}.gml":
            problems.append(f"la página {start} no usa el nombre page_{int(start):04d}.gml")
            break
        if page.get("url") != wfs_getfeature_url(wfs, start):
            problems.append(f"la URL de startIndex {start} no es el GetFeature oficial")
            break
        if not isinstance(page.get("sha256"), str) or not page.get("sha256"):
            problems.append(f"la página {start} no trae sha256")
            break
        if not isinstance(page.get("bytes"), int) or isinstance(page.get("bytes"), bool) or page.get("bytes") < 0:
            problems.append(f"la página {start} no trae el tamaño en bytes")
            break
    return problems


def zfill_digits(value, width: int) -> str:
    if value is None:
        raise ContractError("código vacío")
    try:
        import pandas as pd

        if pd.isna(value):
            raise ContractError("código vacío")
    except ContractError:
        raise
    except Exception:
        pass
    if isinstance(value, bool):
        raise ContractError(f"código no numérico: {value!r}")
    if isinstance(value, float):
        if not value.is_integer():
            raise ContractError(f"código no entero: {value!r}")
        value = int(value)
    text = str(value).strip()
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".", 1)[0]
    if not re.fullmatch(r"\d+", text):
        raise ContractError(f"código no numérico: {text!r}")
    return text.zfill(width)


def as_int(value) -> int:
    if isinstance(value, bool):
        raise ContractError(f"entero inválido: {value!r}")
    try:
        import pandas as pd

        if pd.isna(value):
            raise ContractError("entero vacío")
    except ContractError:
        raise
    except Exception:
        pass
    if isinstance(value, float) and not value.is_integer():
        raise ContractError(f"entero inválido: {value!r}")
    return int(value)


def normalize_label(value) -> str:
    text = unicodedata.normalize("NFKC", "" if value is None else str(value))
    text = text.replace("²", "2")
    text = re.sub(r"\s+", " ", text).strip()
    return text.casefold()


def crs_matches(crs, expected: str) -> bool:
    if crs is None:
        return False
    try:
        return CRS.from_user_input(crs).equals(CRS.from_user_input(expected))
    except Exception:
        return False


def epsg_label(crs) -> str | None:
    if crs is None:
        return None
    try:
        code = CRS.from_user_input(crs).to_epsg()
    except Exception:
        return None
    return f"EPSG:{code}" if code else None


def parse_area_unit(metadata_text: str | None) -> str | None:
    """Devuelve ``m2`` o ``km2`` solo si el texto ata esa unidad a MPIO_NAREA.

    ``None`` significa que la unidad no está declarada. No se infiere por el
    nombre del campo ni por la magnitud del número.
    """
    if not metadata_text or not re.search(r"MPIO_NAREA", metadata_text, re.IGNORECASE):
        return None
    found: set[str] = set()
    km_pattern = _UNIT_PATTERNS[0][1]
    m_pattern = _UNIT_PATTERNS[1][1]
    for match in re.finditer(r"MPIO_NAREA", metadata_text, re.IGNORECASE):
        window = metadata_text[max(0, match.start() - 800) : match.end() + 800]
        window = unicodedata.normalize("NFKC", window).replace("²", "2").replace("㎡", "m2")
        window_units: set[str] = set()
        if km_pattern.search(window):
            window_units.add("km2")
            window = km_pattern.sub(" ", window)
        if m_pattern.search(window):
            window_units.add("m2")
        found.update(window_units)
    if not found:
        return None
    if len(found) > 1:
        raise ContractError(
            "metadatos de MPIO_NAREA declaran unidades distintas: " + ", ".join(sorted(found))
        )
    return next(iter(found))


def area_to_km2(raw_value, unit: str) -> float:
    if unit == "m2":
        factor = 1e-6
    elif unit == "km2":
        factor = 1.0
    else:
        raise ContractError(f"unidad de área no reconocida: {unit}")
    try:
        import pandas as pd

        if pd.isna(raw_value):
            raise ContractError("MPIO_NAREA vacío")
    except ContractError:
        raise
    except Exception:
        pass
    return float(raw_value) * factor


def select_mgn2025_zip(page_url: str, html: str) -> str:
    """Elige el ZIP MGN2025 que aparece en el HTML. No inventa enlaces."""
    pages: list[tuple[str, str]] = []
    for href, text in re.findall(
        r"<a\b[^>]*href\s*=\s*['\"]([^'\"]+)['\"][^>]*>(.*?)</a>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        visible = re.sub(r"<[^>]+>", " ", text)
        pages.append((urljoin(page_url, href.strip()), visible))
    for raw in re.findall(r"https?://[^\s'\"<>]+", html, flags=re.IGNORECASE):
        pages.append((raw.rstrip(").,;"), raw))

    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for url, context in pages:
        blob = f"{url} {context}"
        if ".zip" not in url.lower():
            continue
        if not re.search(r"mgn[\s_-]*2025", blob, re.IGNORECASE):
            continue
        if url in seen:
            continue
        seen.add(url)
        candidates.append((url, blob))
    if not candidates:
        raise ContractError(
            "la página oficial no contiene un enlace ZIP identificado como MGN2025"
        )
    preferred = [
        url
        for url, blob in candidates
        if re.search(r"todos\s+los\s+niveles", blob, re.IGNORECASE)
    ]
    if len(preferred) == 1:
        return preferred[0]
    if len(candidates) == 1:
        return candidates[0][0]
    listed = ", ".join(url for url, _ in candidates)
    raise ContractError("hay varios ZIP MGN2025 en la página y ninguno es único: " + listed)


def geometry_in_colombia(geojson: dict) -> bool:
    depth = 2 if geojson.get("type") == "Polygon" else 3 if geojson.get("type") == "MultiPolygon" else 0
    if depth == 0:
        return False

    def walk(coords, level: int) -> bool:
        if level == 0:
            if not isinstance(coords, (list, tuple)) or len(coords) < 2:
                return False
            lon, lat = float(coords[0]), float(coords[1])
            return COLOMBIA_LON[0] <= lon <= COLOMBIA_LON[1] and COLOMBIA_LAT[0] <= lat <= COLOMBIA_LAT[1]
        return all(walk(part, level - 1) for part in coords)

    return walk(geojson.get("coordinates"), depth)


def document_errors(document: dict, *, size_limit: int = SIZE_GUARD_BYTES) -> list[str]:
    errors = []
    if "loaded_at" in document:
        errors.append("loaded_at debe agregarlo la carga, no la preparación")
    required = (
        "_id",
        "name",
        "dpto_code",
        "dpto_name",
        "subregion_id",
        "subregion_name",
        "area_km2",
        "geometry",
        "source",
    )
    for key in required:
        if key not in document:
            errors.append(f"falta {key}")
    identifier = document.get("_id", "")
    dpto = document.get("dpto_code", "")
    if not isinstance(identifier, str) or not re.fullmatch(r"[0-9]{5}", identifier):
        errors.append("_id no es DIVIPOLA de 5 dígitos")
    if not isinstance(dpto, str) or not re.fullmatch(r"[0-9]{2}", dpto):
        errors.append("dpto_code no tiene 2 dígitos")
    elif isinstance(identifier, str) and len(identifier) >= 2 and identifier[:2] != dpto:
        errors.append("dpto_code no coincide con el prefijo de _id")
    if isinstance(document.get("subregion_id"), bool) or not isinstance(document.get("subregion_id"), int):
        errors.append("subregion_id no es int")
    if not isinstance(document.get("name"), str) or not document.get("name", "").strip():
        errors.append("name vacío")
    if not isinstance(document.get("dpto_name"), str) or not document.get("dpto_name", "").strip():
        errors.append("dpto_name vacío")
    area = document.get("area_km2")
    if isinstance(area, bool) or not isinstance(area, (int, float)):
        errors.append("area_km2 no es numérica")
    source = document.get("source")
    if not isinstance(source, dict) or any(not source.get(key) for key in ("dataset", "version", "file")):
        errors.append("source debe incluir dataset, version y file")
    geometry = document.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") not in ("Polygon", "MultiPolygon"):
        errors.append("geometry no es Polygon o MultiPolygon")
    elif not geometry_in_colombia(geometry):
        errors.append("geometry fuera de la ventana Colombia o con ejes invertidos")
    encoded = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > size_limit:
        errors.append(f"documento supera {size_limit} bytes; no se simplifica")
    return errors


def source_version(config_version: str) -> str:
    compact = re.sub(r"[\s_-]", "", config_version or "").upper()
    if compact == "MGN2025":
        return "2025"
    return config_version
