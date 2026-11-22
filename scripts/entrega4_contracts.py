"""Contrato compartido y metodología verificable de la Entrega 4.

Define en un solo lugar las columnas, tipos, unidades, reglas de filtrado,
política de nulos y validadores que comparten:

- motor común de estadísticas (``scripts/06_rooftop_stats.py``),
- comparación entre Microsoft y Google (``scripts/06_compare_rooftop_stats.py``),
- validación independiente, y
- análisis, mapas y tablas (``scripts/07_entrega4_analysis.py``,
  ``08_entrega4_visualizations.py``, ``09_entrega4_tables.py``).

Uso como validador de línea de comandos:
    python scripts/entrega4_contracts.py --check
    python scripts/entrega4_contracts.py --check --require-google

Salida: 0 todo válido, 1 alguna verificación falló.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from entrega2_contracts import ContractError, load_config, sha256_file  # noqa: E402

CONTRACT_VERSION = "entrega4-rooftop-stats-v1"
METHODOLOGY_ID = "upme-pdet-rooftop-stats"
METHODOLOGY_VERSION = "entrega4-methodology-v1"

VALID_SOURCES = ("ms", "google")
FILTER_ORDER = ("below_min_area", "above_max_area", "low_confidence")
INCLUDED = "included"
GOOGLE_LOW_COVERAGE_RATIO = 0.20

# Columnas oficiales de outputs/rooftop_stats_{source}.csv, en orden exacto.
ROOFTOP_STATS_CSV_COLUMNS = [
    "rank_total_area",
    "mpio_code",
    "name",
    "dpto_code",
    "dpto_name",
    "subregion_id",
    "subregion_name",
    "dataset_id",
    "building_count",
    "total_area_m2",
    "mean_area_m2",
    "median_area_m2",
    "buildings_before_filters",
    "excluded_below_min_area",
    "excluded_above_max_area",
    "excluded_low_confidence",
    "google_low_coverage",
    "computed_at",
]

# Especificación de columnas: tipo, unidad, nulabilidad y formato.
CSV_COLUMN_SPECS = {
    "rank_total_area": {
        "type": "int",
        "unit": "posición (1 = mayor área)",
        "nullable": False,
        "format": "entero 1..170; desempate por mpio_code ascendente",
    },
    "mpio_code": {
        "type": "string",
        "unit": "código DIVIPOLA",
        "nullable": False,
        "format": "5 dígitos con ceros a la izquierda (^[0-9]{5}$)",
    },
    "name": {
        "type": "string",
        "unit": "texto",
        "nullable": False,
        "format": "nombre oficial MGN2025 del municipio",
    },
    "dpto_code": {
        "type": "string",
        "unit": "código DIVIPOLA departamento",
        "nullable": False,
        "format": "2 dígitos (^[0-9]{2}$)",
    },
    "dpto_name": {
        "type": "string",
        "unit": "texto",
        "nullable": False,
        "format": "nombre del departamento MGN2025",
    },
    "subregion_id": {
        "type": "int",
        "unit": "identificador",
        "nullable": False,
        "format": "entero 1..16",
    },
    "subregion_name": {
        "type": "string",
        "unit": "texto",
        "nullable": False,
        "format": "nombre de la subregión PDET",
    },
    "dataset_id": {
        "type": "string",
        "unit": "identificador de fuente",
        "nullable": False,
        "format": "'ms' o 'google'",
    },
    "building_count": {
        "type": "int",
        "unit": "edificaciones",
        "nullable": False,
        "format": "entero >= 0 tras filtros",
    },
    "total_area_m2": {
        "type": "float",
        "unit": "m² (huella geodésica WGS84)",
        "nullable": False,
        "format": "número >= 0, redondeado a 2 decimales (0.0 si building_count = 0)",
    },
    "mean_area_m2": {
        "type": "float",
        "unit": "m² (huella geodésica WGS84)",
        "nullable": True,
        "format": "número > 0 a 2 decimales; vacío/null solo si building_count = 0",
    },
    "median_area_m2": {
        "type": "float",
        "unit": "m² (huella geodésica WGS84)",
        "nullable": True,
        "format": "mediana exacta a 2 decimales; vacío/null solo si building_count = 0",
    },
    "buildings_before_filters": {
        "type": "int",
        "unit": "edificaciones",
        "nullable": False,
        "format": "entero >= 0 en el municipio antes de filtros",
    },
    "excluded_below_min_area": {
        "type": "int",
        "unit": "edificaciones",
        "nullable": False,
        "format": "entero >= 0 excluidas por area_m2 < min_area_m2",
    },
    "excluded_above_max_area": {
        "type": "int",
        "unit": "edificaciones",
        "nullable": False,
        "format": "entero >= 0 excluidas por area_m2 > max_area_m2 (0 si max_area_m2 es null)",
    },
    "excluded_low_confidence": {
        "type": "int",
        "unit": "edificaciones",
        "nullable": False,
        "format": "entero >= 0 excluidas por confianza ausente o < min_confidence (0 en ms)",
    },
    "google_low_coverage": {
        "type": "bool",
        "unit": "bandera",
        "nullable": True,
        "format": "'true'/'false' en google; vacío en ms",
    },
    "computed_at": {
        "type": "string",
        "unit": "fecha UTC",
        "nullable": False,
        "format": "ISO-8601 con zona horaria (+00:00 o Z)",
    },
}

ROOFTOP_STATS_DOC_REQUIRED_FIELDS = (
    "_id",
    "mpio_code",
    "dataset_id",
    "name",
    "dpto_code",
    "dpto_name",
    "subregion_id",
    "subregion_name",
    "building_count",
    "total_area_m2",
    "mean_area_m2",
    "median_area_m2",
    "buildings_before_filters",
    "excluded",
    "rank_total_area",
    "filters",
    "computed_at",
    "script_version",
)

DIVIPOLA_RE = re.compile(r"^[0-9]{5}$")
DPTO_RE = re.compile(r"^[0-9]{2}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------- helpers


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def parse_iso_timestamp(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ContractError("computed_at debe tener zona horaria UTC")
        return value
    if not isinstance(value, str) or not value.strip():
        raise ContractError("computed_at vacío o no es texto")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ContractError(f"fecha ISO-8601 inválida: {value!r}") from exc
    if dt.tzinfo is None:
        raise ContractError(f"fecha sin zona horaria: {value!r}")
    return dt


def parse_optional_bool(value) -> bool | None:
    """Interpreta booleanos opcionales de CSV/JSON de forma tolerante a mayúsculas."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text == "":
            return None
        if text == "true":
            return True
        if text == "false":
            return False
    raise ContractError(f"valor booleano inválido: {value!r}")


def format_optional_bool(value: bool | None) -> str:
    """Serialización canónica en CSV: vacío para None, 'true'/'false' para bool."""
    if value is None:
        return ""
    return "true" if value else "false"


# ---------------------------------------------------------------- metodología y filtros


def is_google_low_coverage(ms_buildings: int, google_buildings: int) -> bool:
    """Regla exacta de cobertura insuficiente de Google: google < 0.20 * ms.

    Usa aritmética entera (5 * google < ms) para evitar errores de punto flotante
    en el borde exacto del 20 %.
    """
    if not _is_int(ms_buildings) or ms_buildings < 0:
        raise ContractError(f"ms_buildings inválido: {ms_buildings!r}")
    if not _is_int(google_buildings) or google_buildings < 0:
        raise ContractError(f"google_buildings inválido: {google_buildings!r}")
    return 5 * google_buildings < ms_buildings


def compute_google_low_coverage_codes(eda_summary: dict) -> set[str]:
    """Recalcula los códigos DIVIPOLA con baja cobertura de Google desde el EDA."""
    municipalities = eda_summary.get("municipalities")
    if not isinstance(municipalities, list) or not municipalities:
        raise ContractError("el resumen del EDA no contiene la lista 'municipalities'")
    flagged = set()
    for row in municipalities:
        code = row.get("mpio_code")
        if not isinstance(code, str) or not DIVIPOLA_RE.fullmatch(code):
            raise ContractError(f"mpio_code inválido en EDA: {code!r}")
        if is_google_low_coverage(row["ms_buildings"], row["google_buildings"]):
            flagged.add(code)
    return flagged


def google_low_coverage_codes(config: dict) -> set[str]:
    """Devuelve el conjunto de códigos configurados en analysis.google_low_coverage."""
    codes = config.get("analysis", {}).get("google_low_coverage") or []
    result = set()
    for code in codes:
        if not isinstance(code, str) or not DIVIPOLA_RE.fullmatch(code):
            raise ContractError(f"código inválido en analysis.google_low_coverage: {code!r}")
        result.add(code)
    return result


def methodology_metadata(config: dict) -> dict:
    """Lee y valida el bloque analysis.methodology de config.yaml."""
    analysis = config.get("analysis")
    if not isinstance(analysis, dict):
        raise ContractError("config.yaml no contiene la sección 'analysis'")
    method = analysis.get("methodology")
    if not isinstance(method, dict):
        raise ContractError("config.yaml no contiene 'analysis.methodology'")
    required = (
        "id",
        "version",
        "base_source",
        "contrast_source",
        "area_metric",
        "usable_area_factor",
        "spatial_assignment",
        "empty_municipality_stats",
        "missing_confidence_policy",
        "outlier_policy",
    )
    missing = [key for key in required if key not in method]
    if missing:
        raise ContractError(f"faltan claves en analysis.methodology: {', '.join(missing)}")
    if method["base_source"] != "ms" or method["contrast_source"] != "google":
        raise ContractError("la metodología fija base_source='ms' y contrast_source='google'")
    if method["usable_area_factor"] is not None:
        raise ContractError("usable_area_factor debe ser null (no se aplican factores sin respaldo)")
    if method["empty_municipality_stats"] != "null":
        raise ContractError("empty_municipality_stats debe ser 'null'")
    return dict(method)


def filters_for(config: dict, dataset_id: str) -> dict:
    """Filtros efectivos de una fuente según config.yaml.

    Reglas:
    - area_m2 >= min_area_m2 (aplicado a ambas fuentes)
    - area_m2 <= max_area_m2 (si max_area_m2 no es null)
    - confidence >= min_confidence (solo si dataset_id está en confidence_sources;
      en Microsoft queda en null porque la fuente no publica confianza).
    """
    if dataset_id not in VALID_SOURCES:
        raise ContractError(f"dataset_id no soportado: {dataset_id!r}")
    analysis = config.get("analysis")
    if not isinstance(analysis, dict):
        raise ContractError("falta la sección 'analysis' en config.yaml")
    min_area = analysis.get("min_area_m2")
    if not _is_number(min_area):
        raise ContractError(f"min_area_m2 inválido: {min_area!r}")
    min_area = float(min_area)
    max_area_raw = analysis.get("max_area_m2")
    if max_area_raw is None:
        max_area = None
    elif _is_number(max_area_raw):
        max_area = float(max_area_raw)
    else:
        raise ContractError(f"max_area_m2 inválido: {max_area_raw!r}")
    if min_area < 0 or (max_area is not None and max_area <= min_area):
        raise ContractError(f"umbrales de área inválidos: min={min_area}, max={max_area}")

    confidence_sources = analysis.get("confidence_sources") or []
    applies = dataset_id in confidence_sources
    if applies:
        min_conf_raw = analysis.get("min_confidence")
        if not _is_number(min_conf_raw):
            raise ContractError(f"min_confidence inválido: {min_conf_raw!r}")
        min_conf = float(min_conf_raw)
        if not 0.0 <= min_conf <= 1.0:
            raise ContractError(f"min_confidence fuera de [0, 1]: {min_conf}")
    else:
        min_conf = None

    return {"min_area_m2": min_area, "max_area_m2": max_area, "min_confidence": min_conf}


def exclusion_reason(area_m2: float, confidence: float | None, filters: dict) -> str:
    """Primer motivo de exclusión según FILTER_ORDER, o 'included'."""
    if area_m2 < filters["min_area_m2"]:
        return "below_min_area"
    if filters["max_area_m2"] is not None and area_m2 > filters["max_area_m2"]:
        return "above_max_area"
    if filters["min_confidence"] is not None and (confidence is None or confidence < filters["min_confidence"]):
        return "low_confidence"
    return INCLUDED


# ---------------------------------------------------------------- validadores


def verify_analysis_config(config: dict, root: Path | None = None) -> list[str]:
    """Verifica coherencia interna de config.yaml (sección analysis) y regla de baja cobertura."""
    errors: list[str] = []
    try:
        methodology_metadata(config)
    except ContractError as exc:
        errors.append(str(exc))

    for source in VALID_SOURCES:
        try:
            filters_for(config, source)
        except ContractError as exc:
            errors.append(f"filtros {source}: {exc}")

    analysis = config.get("analysis") or {}
    if tuple(analysis.get("filter_order") or ()) != FILTER_ORDER:
        errors.append(f"analysis.filter_order debe ser {list(FILTER_ORDER)}")

    if "ms" in (analysis.get("confidence_sources") or []):
        errors.append("ms no puede estar en confidence_sources (confianza ausente en Microsoft)")
    if "google" not in (analysis.get("confidence_sources") or []):
        errors.append("google debe estar en confidence_sources")

    try:
        configured_codes = google_low_coverage_codes(config)
    except ContractError as exc:
        errors.append(str(exc))
        configured_codes = set()

    rule = analysis.get("google_low_coverage_rule") or {}
    if rule.get("ratio_threshold") != GOOGLE_LOW_COVERAGE_RATIO:
        errors.append(f"google_low_coverage_rule.ratio_threshold debe ser {GOOGLE_LOW_COVERAGE_RATIO}")

    if root is not None:
        ref_rel = rule.get("reference_eda", "outputs/eda/eda_buildings_summary.json")
        ref_path = root / ref_rel
        if not ref_path.is_file():
            errors.append(f"falta referencia del EDA para validar google_low_coverage: {ref_rel}")
        else:
            eda = json.loads(ref_path.read_text(encoding="utf-8"))
            recomputed = compute_google_low_coverage_codes(eda)
            if configured_codes != recomputed:
                errors.append(
                    f"google_low_coverage en config.yaml ({len(configured_codes)}) no coincide "
                    f"con el EDA ({len(recomputed)}): faltan {sorted(recomputed - configured_codes)}, "
                    f"sobran {sorted(configured_codes - recomputed)}"
                )
    return errors


def rooftop_stats_doc_errors(
    doc: dict,
    *,
    expected_dataset_id: str | None = None,
    low_coverage_codes: set[str] | None = None,
) -> list[str]:
    """Valida un documento de la colección rooftop_stats contra el contrato de Entrega 4."""
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["el documento debe ser un objeto"]
    for key in ROOFTOP_STATS_DOC_REQUIRED_FIELDS:
        if key not in doc:
            errors.append(f"falta el campo obligatorio '{key}'")
    if errors:
        return errors

    code = doc["mpio_code"]
    dataset_id = doc["dataset_id"]
    if not isinstance(code, str) or not DIVIPOLA_RE.fullmatch(code):
        errors.append(f"mpio_code inválido: {code!r}")
    if dataset_id not in VALID_SOURCES:
        errors.append(f"dataset_id inválido: {dataset_id!r}")
    if expected_dataset_id is not None and dataset_id != expected_dataset_id:
        errors.append(f"dataset_id es {dataset_id!r}, se esperaba {expected_dataset_id!r}")

    expected_id = {"mpio_code": code, "dataset_id": dataset_id}
    if doc["_id"] != expected_id:
        errors.append(f"_id es {doc['_id']!r}, se esperaba {expected_id!r}")

    if not isinstance(doc["dpto_code"], str) or not DPTO_RE.fullmatch(doc["dpto_code"]):
        errors.append(f"dpto_code inválido: {doc['dpto_code']!r}")
    if not _is_int(doc["subregion_id"]) or not 1 <= doc["subregion_id"] <= 16:
        errors.append(f"subregion_id fuera de 1..16: {doc['subregion_id']!r}")
    if not _is_int(doc["rank_total_area"]) or doc["rank_total_area"] < 1:
        errors.append(f"rank_total_area inválido: {doc['rank_total_area']!r}")

    count = doc["building_count"]
    total = doc["total_area_m2"]
    mean = doc["mean_area_m2"]
    median = doc["median_area_m2"]
    before = doc["buildings_before_filters"]

    if not _is_int(count) or count < 0:
        errors.append(f"building_count inválido: {count!r}")
    if not _is_number(total) or total < 0:
        errors.append(f"total_area_m2 inválido: {total!r}")
    if not _is_int(before) or before < 0:
        errors.append(f"buildings_before_filters inválido: {before!r}")

    excluded = doc["excluded"]
    if not isinstance(excluded, dict) or set(excluded) != set(FILTER_ORDER):
        errors.append(f"excluded debe tener exactamente las claves {FILTER_ORDER}")
    else:
        for reason in FILTER_ORDER:
            if not _is_int(excluded[reason]) or excluded[reason] < 0:
                errors.append(f"excluded.{reason} inválido: {excluded[reason]!r}")
        if _is_int(count) and _is_int(before) and all(_is_int(excluded[r]) for r in FILTER_ORDER):
            if count + sum(excluded.values()) != before:
                errors.append(
                    f"{code}: balance roto ({count} + {sum(excluded.values())} != {before})"
                )

    if _is_int(count) and _is_number(total):
        if count == 0:
            if total != 0.0:
                errors.append(f"{code}: total_area_m2 debe ser 0.0 cuando building_count = 0")
            if mean is not None or median is not None:
                errors.append(f"{code}: mean_area_m2 y median_area_m2 deben ser null cuando building_count = 0")
        else:
            if not _is_number(mean) or mean <= 0:
                errors.append(f"{code}: mean_area_m2 inválido ({mean!r}) con building_count > 0")
            elif not math.isclose(mean, total / count, rel_tol=1e-6, abs_tol=0.02):
                errors.append(f"{code}: mean_area_m2 ({mean}) no coincide con total/count ({total / count:.4f})")
            if not _is_number(median) or median <= 0:
                errors.append(f"{code}: median_area_m2 inválido ({median!r}) con building_count > 0")
            elif median > total + 0.02:
                errors.append(f"{code}: median_area_m2 ({median}) supera total_area_m2 ({total})")

    filters = doc["filters"]
    if not isinstance(filters, dict) or set(filters) != {"min_area_m2", "max_area_m2", "min_confidence"}:
        errors.append("filters debe contener min_area_m2, max_area_m2 y min_confidence")

    try:
        parse_iso_timestamp(doc["computed_at"])
    except ContractError as exc:
        errors.append(str(exc))

    if dataset_id == "ms":
        if "google_low_coverage" in doc:
            errors.append("google_low_coverage no debe escribirse en documentos de Microsoft")
    elif dataset_id == "google":
        if "google_low_coverage" not in doc or not isinstance(doc["google_low_coverage"], bool):
            errors.append("google_low_coverage (bool) es obligatorio en documentos de Google")
        elif low_coverage_codes is not None and doc["google_low_coverage"] != (code in low_coverage_codes):
            errors.append(f"{code}: google_low_coverage no coincide con la lista configurada")

    return errors


def _parse_csv_row_as_metrics(row: dict, line_number: int) -> tuple[dict | None, list[str]]:
    errors: list[str] = []
    code = row["mpio_code"]
    dataset_id = row["dataset_id"]
    if not DIVIPOLA_RE.fullmatch(code):
        errors.append(f"línea {line_number}: mpio_code inválido {code!r}")
    if not DPTO_RE.fullmatch(row["dpto_code"]):
        errors.append(f"línea {line_number}: dpto_code inválido {row['dpto_code']!r}")
    if dataset_id not in VALID_SOURCES:
        errors.append(f"línea {line_number}: dataset_id inválido {dataset_id!r}")
    for text_field in ("name", "dpto_name", "subregion_name"):
        if not row[text_field].strip():
            errors.append(f"línea {line_number}: {text_field} vacío")

    ints = {}
    for int_field in (
        "rank_total_area",
        "subregion_id",
        "building_count",
        "buildings_before_filters",
        "excluded_below_min_area",
        "excluded_above_max_area",
        "excluded_low_confidence",
    ):
        try:
            ints[int_field] = int(row[int_field])
        except ValueError:
            errors.append(f"línea {line_number}: {int_field} no es entero ({row[int_field]!r})")

    try:
        total_area = float(row["total_area_m2"])
        if not math.isfinite(total_area) or total_area < 0:
            errors.append(f"línea {line_number}: total_area_m2 negativo o no finito")
    except ValueError:
        errors.append(f"línea {line_number}: total_area_m2 no es número ({row['total_area_m2']!r})")
        total_area = -1.0

    opt_floats = {}
    for float_field in ("mean_area_m2", "median_area_m2"):
        raw = row[float_field].strip()
        if raw == "":
            opt_floats[float_field] = None
        else:
            try:
                val = float(raw)
                if not math.isfinite(val) or val <= 0:
                    errors.append(f"línea {line_number}: {float_field} inválido ({raw!r})")
                opt_floats[float_field] = val
            except ValueError:
                errors.append(f"línea {line_number}: {float_field} no es número ({raw!r})")
                opt_floats[float_field] = None

    try:
        low_cov = parse_optional_bool(row["google_low_coverage"])
    except ContractError as exc:
        errors.append(f"línea {line_number}: {exc}")
        low_cov = None

    try:
        parse_iso_timestamp(row["computed_at"])
    except ContractError as exc:
        errors.append(f"línea {line_number}: {exc}")

    if errors:
        return None, errors

    count = ints["building_count"]
    before = ints["buildings_before_filters"]
    excl_sum = (
        ints["excluded_below_min_area"]
        + ints["excluded_above_max_area"]
        + ints["excluded_low_confidence"]
    )
    if count < 0 or before < 0 or ints["excluded_below_min_area"] < 0 or ints["excluded_above_max_area"] < 0 or ints["excluded_low_confidence"] < 0:
        errors.append(f"línea {line_number}: conteos negativos")
    if count + excl_sum != before:
        errors.append(f"línea {line_number} ({code}): balance roto ({count} + {excl_sum} != {before})")
    if not 1 <= ints["subregion_id"] <= 16:
        errors.append(f"línea {line_number} ({code}): subregion_id fuera de 1..16")

    if count == 0:
        if total_area != 0.0:
            errors.append(f"línea {line_number} ({code}): total_area_m2 != 0 con building_count = 0")
        if opt_floats["mean_area_m2"] is not None or opt_floats["median_area_m2"] is not None:
            errors.append(f"línea {line_number} ({code}): mean/median deben estar vacíos con building_count = 0")
    else:
        mean_val = opt_floats["mean_area_m2"]
        med_val = opt_floats["median_area_m2"]
        if mean_val is None or med_val is None:
            errors.append(f"línea {line_number} ({code}): falta mean_area_m2 o median_area_m2")
        else:
            if not math.isclose(mean_val, total_area / count, rel_tol=1e-6, abs_tol=0.02):
                errors.append(f"línea {line_number} ({code}): mean_area_m2 inconsistente con total/count")
            if med_val > total_area + 0.02:
                errors.append(f"línea {line_number} ({code}): median_area_m2 supera total_area_m2")

    parsed = {
        **ints,
        "mpio_code": code,
        "name": row["name"],
        "dpto_code": row["dpto_code"],
        "dpto_name": row["dpto_name"],
        "subregion_name": row["subregion_name"],
        "dataset_id": dataset_id,
        "total_area_m2": total_area,
        "mean_area_m2": opt_floats["mean_area_m2"],
        "median_area_m2": opt_floats["median_area_m2"],
        "google_low_coverage": low_cov,
        "computed_at": row["computed_at"],
    }
    return parsed, errors


def rooftop_stats_csv_errors(
    csv_path: Path,
    *,
    expected_dataset_id: str | None = None,
    expected_codes: set[str] | None = None,
    low_coverage_codes: set[str] | None = None,
) -> list[str]:
    """Valida un CSV exportado por el motor común contra el contrato de Entrega 4."""
    if not csv_path.is_file():
        return [f"no existe el CSV: {csv_path}"]
    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ROOFTOP_STATS_CSV_COLUMNS:
            return [
                f"columnas del CSV no coinciden con el contrato: "
                f"esperadas={ROOFTOP_STATS_CSV_COLUMNS}, recibidas={reader.fieldnames}"
            ]
        rows = list(reader)

    errors: list[str] = []
    parsed_rows: list[dict] = []
    seen_codes: set[str] = set()
    for idx, row in enumerate(rows, start=2):
        parsed, row_errors = _parse_csv_row_as_metrics(row, idx)
        errors.extend(row_errors)
        if parsed is None:
            continue
        code = parsed["mpio_code"]
        if code in seen_codes:
            errors.append(f"mpio_code duplicado en CSV: {code}")
        seen_codes.add(code)
        if expected_dataset_id is not None and parsed["dataset_id"] != expected_dataset_id:
            errors.append(f"línea {idx}: dataset_id={parsed['dataset_id']!r}, esperado {expected_dataset_id!r}")
        if parsed["dataset_id"] == "ms" and parsed["google_low_coverage"] is not None:
            errors.append(f"línea {idx}: google_low_coverage debe ir vacío en Microsoft")
        if parsed["dataset_id"] == "google":
            if parsed["google_low_coverage"] is None:
                errors.append(f"línea {idx}: falta google_low_coverage en Google")
            elif low_coverage_codes is not None and parsed["google_low_coverage"] != (code in low_coverage_codes):
                errors.append(f"línea {idx} ({code}): google_low_coverage no coincide con la configuración")
        parsed_rows.append(parsed)

    if expected_codes is not None and seen_codes != expected_codes:
        missing = sorted(expected_codes - seen_codes)
        extra = sorted(seen_codes - expected_codes)
        errors.append(f"municipios del CSV no coinciden con los esperados: faltan={missing[:5]}, sobran={extra[:5]}")

    # Orden por rank_total_area 1..N y criterio (-total_area_m2, mpio_code).
    if parsed_rows and len(parsed_rows) == len(rows):
        ranks = [r["rank_total_area"] for r in parsed_rows]
        if ranks != list(range(1, len(parsed_rows) + 1)):
            errors.append("rank_total_area no es secuencial 1..N en el orden del CSV")
        expected_order = sorted(parsed_rows, key=lambda r: (-r["total_area_m2"], r["mpio_code"]))
        if [r["mpio_code"] for r in parsed_rows] != [r["mpio_code"] for r in expected_order]:
            errors.append("el orden del CSV no coincide con (-total_area_m2, mpio_code)")

    return errors


def rooftop_stats_report_errors(
    report: dict,
    *,
    root: Path | None = None,
    config: dict | None = None,
) -> list[str]:
    """Valida el reporte JSON generado por scripts/06_rooftop_stats.py."""
    errors: list[str] = []
    if not isinstance(report, dict):
        return ["el reporte debe ser un objeto JSON"]
    if report.get("role") != "rooftop-stats-report":
        errors.append(f"role inesperado: {report.get('role')!r}")
    dataset_id = report.get("dataset_id")
    if dataset_id not in VALID_SOURCES:
        errors.append(f"dataset_id inválido en reporte: {dataset_id!r}")
    if report.get("status") != "computed":
        errors.append(f"status es {report.get('status')!r}, se esperaba 'computed'")
    if not (report.get("verification") or {}).get("ok"):
        errors.append("verification.ok no es true")
    if tuple(report.get("filter_order") or ()) != FILTER_ORDER:
        errors.append(f"filter_order del reporte no coincide con {list(FILTER_ORDER)}")

    totals = report.get("totals") or {}
    if totals.get("balanced") is not True:
        errors.append("totals.balanced no es true")
    excl = totals.get("excluded") or {}
    if all(_is_int(excl.get(r)) for r in FILTER_ORDER):
        excl_sum = sum(excl[r] for r in FILTER_ORDER)
        if excl.get("total") != excl_sum:
            errors.append("totals.excluded.total no suma los motivos")
        if totals.get("included", -1) + excl_sum != totals.get("assigned_pdet", -2):
            errors.append("totals.included + totals.excluded.total != totals.assigned_pdet")

    try:
        parse_iso_timestamp(report.get("computed_at"))
    except ContractError as exc:
        errors.append(f"computed_at del reporte: {exc}")

    if config is not None and dataset_id in VALID_SOURCES:
        expected_filters = filters_for(config, dataset_id)
        if report.get("filters") != expected_filters:
            errors.append(f"filtros del reporte ({report.get('filters')}) != config.yaml ({expected_filters})")

    outputs = report.get("outputs") or {}
    csv_rel = outputs.get("csv")
    csv_sha = outputs.get("csv_sha256")
    if not csv_rel or not isinstance(csv_sha, str) or not SHA256_RE.fullmatch(csv_sha):
        errors.append("outputs.csv o outputs.csv_sha256 inválido")
    elif root is not None:
        csv_path = root / csv_rel
        if not csv_path.is_file():
            errors.append(f"CSV declarado en reporte no existe: {csv_rel}")
        else:
            actual_sha = sha256_file(csv_path)
            if actual_sha != csv_sha:
                errors.append(f"SHA256 de {csv_rel} no coincide con el reporte")
            with csv_path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            csv_included = sum(int(r["building_count"]) for r in rows)
            csv_before = sum(int(r["buildings_before_filters"]) for r in rows)
            csv_area = round(math.fsum(float(r["total_area_m2"]) for r in rows), 2)
            if csv_included != totals.get("included"):
                errors.append(f"suma building_count en CSV ({csv_included}) != reporte ({totals.get('included')})")
            if csv_before != totals.get("assigned_pdet"):
                errors.append(f"suma buildings_before_filters en CSV ({csv_before}) != reporte ({totals.get('assigned_pdet')})")
            if not math.isclose(csv_area, float(totals.get("total_area_m2", -1)), rel_tol=0.0, abs_tol=0.02):
                errors.append(f"suma total_area_m2 en CSV ({csv_area}) != reporte ({totals.get('total_area_m2')})")

    return errors


def load_pdet_codes(root: Path, config: dict) -> set[str]:
    """Lee los 170 códigos DIVIPOLA oficiales desde outputs/pdet_mgn_crosswalk.csv."""
    rel = config.get("analysis", {}).get("comparison", {}).get("municipalities", "outputs/pdet_mgn_crosswalk.csv")
    path = root / rel
    if not path.is_file():
        raise ContractError(f"falta el cruce municipal PDET: {rel}")
    with path.open(encoding="utf-8", newline="") as handle:
        codes = {row["mpio_code"].strip() for row in csv.DictReader(handle) if row.get("mpio_code")}
    expected = int(config["sources"]["pdet_list"]["expected_municipalities"])
    if len(codes) != expected:
        raise ContractError(f"{rel} tiene {len(codes)} códigos; se esperaban {expected}")
    return codes


def load_rooftop_stats_export(csv_path: Path, report_path: Path, config: dict, root: Path) -> dict:
    """Valida y carga la exportación oficial de una fuente (CSV + reporte JSON).

    Devuelve una estructura normalizada con metodología, filtros, procedencia y
    los 170 registros municipales, lista para comparación entre fuentes o tablas.
    """
    report = json.loads(report_path.read_text(encoding="utf-8"))
    dataset_id = report.get("dataset_id")
    codes = load_pdet_codes(root, config)
    low_cov = google_low_coverage_codes(config)

    errors = rooftop_stats_report_errors(report, root=root, config=config)
    errors.extend(
        rooftop_stats_csv_errors(
            csv_path,
            expected_dataset_id=dataset_id,
            expected_codes=codes,
            low_coverage_codes=low_cov,
        )
    )
    if errors:
        raise ContractError("; ".join(errors))

    municipalities = []
    with csv_path.open(encoding="utf-8", newline="") as handle:
        for idx, row in enumerate(csv.DictReader(handle), start=2):
            parsed, row_errors = _parse_csv_row_as_metrics(row, idx)
            if row_errors or parsed is None:
                raise ContractError("; ".join(row_errors))
            municipalities.append(parsed)

    return {
        "contract": CONTRACT_VERSION,
        "status": report["status"],
        "dataset_id": dataset_id,
        "methodology": methodology_metadata(config),
        "filters_by_source": {src: filters_for(config, src) for src in VALID_SOURCES},
        "filters": report["filters"],
        "provenance": {
            "computed_at": report["computed_at"],
            "engine": "scripts/06_rooftop_stats.py",
            "engine_version": report.get("script_version"),
            "database": report.get("database"),
            "mongo_version": report.get("mongo_version"),
            "input_references": [
                {"path": csv_path.relative_to(root).as_posix() if csv_path.is_relative_to(root) else str(csv_path),
                 "sha256": sha256_file(csv_path)},
                {"path": report_path.relative_to(root).as_posix() if report_path.is_relative_to(root) else str(report_path),
                 "sha256": sha256_file(report_path)},
            ],
        },
        "totals": report["totals"],
        "municipalities": municipalities,
    }


# ---------------------------------------------------------------- CLI


def check_workspace(root: Path = ROOT, *, require_google: bool = False) -> tuple[bool, list[str]]:
    """Valida config.yaml y los artefactos de rooftop_stats existentes en outputs/."""
    lines: list[str] = []
    ok = True
    config = load_config(root)

    cfg_errors = verify_analysis_config(config, root=root)
    if cfg_errors:
        ok = False
        for err in cfg_errors:
            lines.append(f"[FALLA] config.yaml: {err}")
    else:
        lines.append("[OK] config.yaml: metodología, filtros y 15 códigos de baja cobertura verificados contra el EDA")

    codes = load_pdet_codes(root, config)
    low_cov = google_low_coverage_codes(config)
    stats_cfg = config["analysis"]["rooftop_stats"]

    for source in VALID_SOURCES:
        csv_path = root / stats_cfg["csv"].format(source=source)
        report_path = root / stats_cfg["report"].format(source=source)
        if not csv_path.exists() and not report_path.exists():
            if source == "google" and not require_google:
                lines.append(
                    f"[PENDIENTE] {source}: aún no existen {csv_path.relative_to(root).as_posix()} "
                    f"ni {report_path.relative_to(root).as_posix()}"
                )
                continue
            ok = False
            lines.append(f"[FALLA] {source}: faltan {csv_path.relative_to(root).as_posix()} y {report_path.relative_to(root).as_posix()}")
            continue

        if not csv_path.exists() or not report_path.exists():
            ok = False
            lines.append(f"[FALLA] {source}: falta uno de los dos archivos (CSV o reporte JSON)")
            continue

        report = json.loads(report_path.read_text(encoding="utf-8"))
        src_errors = rooftop_stats_report_errors(report, root=root, config=config)
        src_errors.extend(
            rooftop_stats_csv_errors(
                csv_path,
                expected_dataset_id=source,
                expected_codes=codes,
                low_coverage_codes=low_cov,
            )
        )
        if src_errors:
            ok = False
            for err in src_errors:
                lines.append(f"[FALLA] {source}: {err}")
        else:
            totals = report["totals"]
            lines.append(
                f"[OK] {source}: {report['municipalities']['written']}/170 municipios, "
                f"{totals['included']} edificaciones incluidas, "
                f"{totals['total_area_m2'] / 1e6:.2f} km², SHA256 y balance verificados"
            )

    return ok, lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="valida config.yaml y salidas de Entrega 4")
    parser.add_argument(
        "--require-google",
        action="store_true",
        help="exige que ya existan outputs/rooftop_stats_google.csv y su reporte JSON",
    )
    args = parser.parse_args(argv)
    if not args.check:
        parser.print_help()
        return 0
    try:
        ok, lines = check_workspace(ROOT, require_google=args.require_google)
    except (ContractError, OSError, ValueError, KeyError) as exc:
        print(f"[FALLA] {exc}", file=sys.stderr)
        return 1
    for line in lines:
        print(line)
    print(f"contrato {CONTRACT_VERSION} ({METHODOLOGY_VERSION}): {'OK' if ok else 'FALLA'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
