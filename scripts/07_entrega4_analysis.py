#!/usr/bin/env python3
"""Phase 1: Automatic data reader for Entrega 4 analysis.

Reads rooftop_stats_ms.csv and eda_buildings_summary.json into unified JSON summary.
No manual figure transcription; all data flows from automatic computation.

Output: outputs/entrega4_analysis_summary.json
"""
import csv
import json
import sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
STATS_CSV = ROOT / "outputs" / "rooftop_stats_ms.csv"
EDA_JSON = ROOT / "outputs" / "eda" / "eda_buildings_summary.json"
OUTPUT_JSON = ROOT / "outputs" / "entrega4_analysis_summary.json"

# Low-coverage municipalities (from README.md)
GOOGLE_COBERTURA_INSUFICIENTE = {
    "05475", "05873", "19418", "27099", "27150", "27205", "27250",
    "27425", "27450", "27491", "27615", "27745", "52612", "52621", "73616"
}

def read_stats_csv():
    """Read rooftop_stats_ms.csv into indexed dict."""
    municipalities = {}
    with open(STATS_CSV, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            mpio_code = row['mpio_code']
            municipalities[mpio_code] = {
                'mpio_code': mpio_code,
                'name': row['name'],
                'dpto_code': row['dpto_code'],
                'dpto_name': row['dpto_name'],
                'subregion_id': row['subregion_id'],
                'subregion_name': row['subregion_name'],
                'dataset_id': row['dataset_id'],
                'rank_total_area': int(row['rank_total_area']),
                'building_count': int(row['building_count']),
                'total_area_m2': float(row['total_area_m2']),
                'mean_area_m2': float(row['mean_area_m2']) if row['mean_area_m2'] else None,
                'median_area_m2': float(row['median_area_m2']) if row['median_area_m2'] else None,
                'buildings_before_filters': int(row['buildings_before_filters']),
                'excluded_below_min_area': int(row['excluded_below_min_area']),
                'google_low_coverage': row['google_low_coverage'] == 'TRUE' or mpio_code in GOOGLE_COBERTURA_INSUFICIENTE,
            }
    return municipalities

def read_eda_json():
    """Read eda_buildings_summary.json for comparison metadata."""
    with open(EDA_JSON, 'r', encoding='utf-8') as f:
        return json.load(f)

def compute_subregion_totals(municipalities):
    """Aggregate building counts and areas by subregion."""
    subregions = defaultdict(lambda: {
        'subregion_name': None,
        'building_count': 0,
        'total_area_m2': 0.0,
        'municipality_count': 0,
    })

    for mpio in municipalities.values():
        sub_name = mpio['subregion_name']
        subregions[sub_name]['subregion_name'] = sub_name
        subregions[sub_name]['building_count'] += mpio['building_count']
        subregions[sub_name]['total_area_m2'] += mpio['total_area_m2']
        subregions[sub_name]['municipality_count'] += 1

    return dict(subregions)

def compute_percentiles(municipalities):
    """Compute building count and area percentiles."""
    building_counts = sorted([m['building_count'] for m in municipalities.values()])
    total_areas = sorted([m['total_area_m2'] for m in municipalities.values()])

    n = len(building_counts)
    return {
        'building_count_p25': building_counts[n//4],
        'building_count_p50': building_counts[n//2],
        'building_count_p75': building_counts[3*n//4],
        'total_area_m2_p25': total_areas[n//4],
        'total_area_m2_p50': total_areas[n//2],
        'total_area_m2_p75': total_areas[3*n//4],
    }

def main():
    if not STATS_CSV.exists():
        print(f"ERROR: {STATS_CSV} not found", file=sys.stderr)
        return 1
    if not EDA_JSON.exists():
        print(f"ERROR: {EDA_JSON} not found", file=sys.stderr)
        return 1

    print("Phase 1: Reading rooftop statistics and EDA metadata...")
    municipalities = read_stats_csv()
    eda = read_eda_json()

    print(f"  Loaded {len(municipalities)} municipalities from stats CSV")
    print(f"  Loaded EDA metadata with {len(eda.get('municipalities', []))} municipalities")

    # Compute aggregations
    subregions = compute_subregion_totals(municipalities)
    percentiles = compute_percentiles(municipalities)

    # Build summary document
    summary = {
        'metadata': {
            'generated_from': [
                str(STATS_CSV.relative_to(ROOT)),
                str(EDA_JSON.relative_to(ROOT))
            ],
            'total_municipalities': len(municipalities),
            'total_subregions': len(subregions),
        },
        'global_totals': {
            'total_buildings': sum(m['building_count'] for m in municipalities.values()),
            'total_area_m2': sum(m['total_area_m2'] for m in municipalities.values()),
            'total_area_km2': sum(m['total_area_m2'] for m in municipalities.values()) / 1e6,
            'total_buildings_before_filters': sum(m['buildings_before_filters'] for m in municipalities.values()),
            'total_excluded_below_min_area': sum(m['excluded_below_min_area'] for m in municipalities.values()),
            'mean_buildings_per_municipality': sum(m['building_count'] for m in municipalities.values()) / len(municipalities),
            'mean_area_m2_per_municipality': sum(m['total_area_m2'] for m in municipalities.values()) / len(municipalities),
        },
        'percentiles': percentiles,
        'subregions': subregions,
        'municipalities': municipalities,
        'comparison_metadata': eda.get('comparison', {}),
        'low_coverage_municipalities': list(GOOGLE_COBERTURA_INSUFICIENTE),
        'low_coverage_count': len(GOOGLE_COBERTURA_INSUFICIENTE),
    }

    # Write output
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"  Computed subregion totals: {len(subregions)} subregions")
    print(f"  Global totals: {summary['global_totals']['total_buildings']:,} buildings, "
          f"{summary['global_totals']['total_area_km2']:.2f} km²")
    print(f"  Low-coverage municipalities: {len(GOOGLE_COBERTURA_INSUFICIENTE)}")
    print(f"\nPhase 1 complete. Output: {OUTPUT_JSON.relative_to(ROOT)}")

    return 0

if __name__ == '__main__':
    sys.exit(main())
