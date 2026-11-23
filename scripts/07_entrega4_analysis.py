#!/usr/bin/env python3
"""Fase 1: Lector automático de resultados de la Entrega 4.

Lee ``config.yaml``, ``outputs/rooftop_stats_ms.csv``, el resumen del EDA
(``outputs/eda/eda_buildings_summary.json``) y, si ya existe,
``outputs/rooftop_stats_google.csv``. Genera un JSON unificado sin transcripción
manual ni estimaciones sintéticas.

Salida: outputs/entrega4_analysis_summary.json
"""
from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from entrega2_contracts import load_config  # noqa: E402
from entrega4_contracts import (  # noqa: E402
    CONTRACT_VERSION,
    filters_for,
    google_low_coverage_codes,
    methodology_metadata,
    parse_optional_bool,
)

OUTPUT_JSON = ROOT / "outputs" / "entrega4_analysis_summary.json"


def read_stats_csv(path: Path, low_coverage: set[str]) -> dict[str, dict]:
    """Lee un CSV del motor común indexado por mpio_code."""
    municipalities = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            mpio_code = row["mpio_code"]
            flag = parse_optional_bool(row.get("google_low_coverage"))
            municipalities[mpio_code] = {
                "mpio_code": mpio_code,
                "name": row["name"],
                "dpto_code": row["dpto_code"],
                "dpto_name": row["dpto_name"],
                "subregion_id": int(row["subregion_id"]),
                "subregion_name": row["subregion_name"],
                "dataset_id": row["dataset_id"],
                "rank_total_area": int(row["rank_total_area"]),
                "building_count": int(row["building_count"]),
                "total_area_m2": float(row["total_area_m2"]),
                "mean_area_m2": float(row["mean_area_m2"]) if row["mean_area_m2"] else None,
                "median_area_m2": float(row["median_area_m2"]) if row["median_area_m2"] else None,
                "buildings_before_filters": int(row["buildings_before_filters"]),
                "excluded_below_min_area": int(row["excluded_below_min_area"]),
                "excluded_above_max_area": int(row["excluded_above_max_area"]),
                "excluded_low_confidence": int(row["excluded_low_confidence"]),
                "google_low_coverage": bool(flag) if flag is not None else (mpio_code in low_coverage),
                "computed_at": row["computed_at"],
            }
    return municipalities


def read_eda_json(path: Path) -> dict:
    """Lee outputs/eda/eda_buildings_summary.json (referencia histórica sin filtros E4)."""
    return json.loads(path.read_text(encoding="utf-8"))


def compute_subregion_totals(municipalities: dict[str, dict]) -> dict[str, dict]:
    """Agrega edificaciones y área de huella por subregión PDET."""
    subregions = defaultdict(lambda: {
        "subregion_id": None,
        "subregion_name": None,
        "building_count": 0,
        "total_area_m2": 0.0,
        "municipality_count": 0,
    })

    for mpio in municipalities.values():
        sub_name = mpio["subregion_name"]
        subregions[sub_name]["subregion_id"] = mpio["subregion_id"]
        subregions[sub_name]["subregion_name"] = sub_name
        subregions[sub_name]["building_count"] += mpio["building_count"]
        subregions[sub_name]["total_area_m2"] = round(
            subregions[sub_name]["total_area_m2"] + mpio["total_area_m2"], 2
        )
        subregions[sub_name]["municipality_count"] += 1

    return dict(subregions)


def compute_percentiles(municipalities: dict[str, dict]) -> dict[str, float]:
    """Calcula cuartiles exactos (p25, mediana p50, p75) de conteo y área municipal."""
    building_counts = [m["building_count"] for m in municipalities.values()]
    total_areas = [m["total_area_m2"] for m in municipalities.values()]

    c_q1, c_q2, c_q3 = statistics.quantiles(building_counts, n=4)
    a_q1, a_q2, a_q3 = statistics.quantiles(total_areas, n=4)
    return {
        "building_count_p25": round(c_q1, 2),
        "building_count_p50": round(statistics.median(building_counts), 2),
        "building_count_p75": round(c_q3, 2),
        "total_area_m2_p25": round(a_q1, 2),
        "total_area_m2_p50": round(statistics.median(total_areas), 2),
        "total_area_m2_p75": round(a_q3, 2),
    }


def main() -> int:
    config = load_config(ROOT)
    stats_cfg = config["analysis"]["rooftop_stats"]
    ms_csv = ROOT / stats_cfg["csv"].format(source="ms")
    google_csv = ROOT / stats_cfg["csv"].format(source="google")
    eda_json = ROOT / config["analysis"]["google_low_coverage_rule"]["reference_eda"]

    if not ms_csv.exists():
        print(f"ERROR: no existe {ms_csv}", file=sys.stderr)
        return 1
    if not eda_json.exists():
        print(f"ERROR: no existe {eda_json}", file=sys.stderr)
        return 1

    low_coverage = google_low_coverage_codes(config)
    methodology = methodology_metadata(config)

    print("Fase 1: leyendo estadísticas de Microsoft y metadatos del EDA...")
    municipalities = read_stats_csv(ms_csv, low_coverage)
    eda = read_eda_json(eda_json)
    eda_by_code = {row["mpio_code"]: row for row in eda.get("municipalities", [])}

    for code, mpio in municipalities.items():
        eda_row = eda_by_code.get(code)
        if eda_row:
            mpio["eda_ms_buildings"] = eda_row.get("ms_buildings")
            mpio["eda_google_buildings"] = eda_row.get("google_buildings")
            mpio["eda_ms_area_m2"] = eda_row.get("ms_area_m2")
            mpio["eda_google_area_m2"] = eda_row.get("google_area_m2")

    google_filtered = None
    generated_from = [
        ms_csv.relative_to(ROOT).as_posix(),
        eda_json.relative_to(ROOT).as_posix(),
    ]
    if google_csv.exists():
        google_munis = read_stats_csv(google_csv, low_coverage)
        generated_from.append(google_csv.relative_to(ROOT).as_posix())
        google_total_b = sum(m["building_count"] for m in google_munis.values())
        google_total_a = round(math.fsum(m["total_area_m2"] for m in google_munis.values()), 2)
        google_filtered = {
            "available": True,
            "total_buildings": google_total_b,
            "total_area_m2": google_total_a,
            "total_area_km2": round(google_total_a / 1e6, 4),
            "municipalities_with_buildings": sum(1 for m in google_munis.values() if m["building_count"] > 0),
        }
        for code, mpio in municipalities.items():
            g_row = google_munis.get(code)
            if g_row:
                mpio["google_building_count"] = g_row["building_count"]
                mpio["google_total_area_m2"] = g_row["total_area_m2"]
    else:
        google_filtered = {"available": False}

    subregions = compute_subregion_totals(municipalities)
    percentiles = compute_percentiles(municipalities)

    total_buildings = sum(m["building_count"] for m in municipalities.values())
    total_area_m2 = round(math.fsum(m["total_area_m2"] for m in municipalities.values()), 2)
    medians = [m["median_area_m2"] for m in municipalities.values() if m["median_area_m2"] is not None]

    summary = {
        "metadata": {
            "contract": CONTRACT_VERSION,
            "methodology": methodology,
            "filters_by_source": {
                "ms": filters_for(config, "ms"),
                "google": filters_for(config, "google"),
            },
            "generated_from": generated_from,
            "total_municipalities": len(municipalities),
            "total_subregions": len(subregions),
        },
        "global_totals": {
            "total_buildings": total_buildings,
            "total_area_m2": total_area_m2,
            "total_area_km2": round(total_area_m2 / 1e6, 4),
            "total_buildings_before_filters": sum(m["buildings_before_filters"] for m in municipalities.values()),
            "total_excluded_below_min_area": sum(m["excluded_below_min_area"] for m in municipalities.values()),
            "total_excluded_above_max_area": sum(m["excluded_above_max_area"] for m in municipalities.values()),
            "total_excluded_low_confidence": sum(m["excluded_low_confidence"] for m in municipalities.values()),
            "mean_buildings_per_municipality": round(total_buildings / len(municipalities), 2),
            "mean_area_m2_per_municipality": round(total_area_m2 / len(municipalities), 2),
            "global_mean_area_per_building_m2": round(total_area_m2 / total_buildings, 2) if total_buildings else None,
            "median_of_municipality_median_area_m2": round(statistics.median(medians), 2) if medians else None,
        },
        "percentiles": percentiles,
        "subregions": subregions,
        "municipalities": municipalities,
        "google_filtered": google_filtered,
        "eda_reference": {
            "sources": eda.get("sources", {}),
            "comparison": eda.get("comparison", {}),
            "note": "Referencia histórica sin filtros de Entrega 4; Spearman sobre 165 municipios con Google > 0.",
        },
        "comparison_metadata": eda.get("comparison", {}),
        "low_coverage_municipalities": sorted(low_coverage),
        "low_coverage_count": len(low_coverage),
    }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"  Municipios: {len(municipalities)} · Subregiones: {len(subregions)}")
    print(f"  Microsoft: {total_buildings:,} edificaciones, {total_area_m2 / 1e6:.2f} km²")
    print(f"  Google filtrado disponible: {google_filtered['available']}")
    print(f"  Salida: {OUTPUT_JSON.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
