#!/usr/bin/env python3
"""Phase 2: Generate maps and comparison charts for Entrega 4.

Reads municipality geometries from GeoJSON and joins with rooftop stats.
Outputs choropleth maps and comparison charts as PNG.

Output: docs/delivery4/figuras/*.png
"""
import json
import sys
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import geopandas as gpd
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_JSON = ROOT / "outputs" / "entrega4_analysis_summary.json"
GEOJSONL = ROOT / "data" / "processed" / "municipalities.geojsonl"
FIGURAS_DIR = ROOT / "docs" / "delivery4" / "figuras"

# Color scheme
MS_BLUE = '#1F5FAF'
GOOGLE_ORANGE = '#E08A1E'

# Low-coverage municipalities
GOOGLE_COBERTURA_INSUFICIENTE = {
    "05475", "05873", "19418", "27099", "27150", "27205", "27250",
    "27425", "27450", "27491", "27615", "27745", "52612", "52621", "73616"
}

def read_analysis():
    """Read analysis summary JSON."""
    with open(ANALYSIS_JSON, 'r', encoding='utf-8') as f:
        return json.load(f)

def read_municipalities_gdf():
    """Read municipalities GeoJSON ND (newline-delimited) and return GeoDataFrame."""
    import json as json_module
    from shapely.geometry import shape

    rows = []
    with open(GEOJSONL, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                doc = json_module.loads(line)
                # MongoDB-style GeoJSON: properties at root, geometry is nested
                geom = shape(doc['geometry'])
                row = {'geometry': geom}
                # Add all other fields; rename '_id' to 'mpio_code' for merge compatibility
                for key, val in doc.items():
                    if key == '_id':
                        row['mpio_code'] = val
                    elif key != 'geometry':
                        row[key] = val
                rows.append(row)

    gdf = gpd.GeoDataFrame(rows, crs='EPSG:4326')
    # Ensure geometry is valid
    gdf = gdf[gdf.geometry.is_valid]
    return gdf

def join_data(gdf, analysis):
    """Join geospatial data with rooftop statistics."""
    # Create DataFrame from municipalities data
    mun_data = analysis['municipalities']
    mun_df = pd.DataFrame(list(mun_data.values()))

    # Merge with GeoDataFrame on mpio_code, handling duplicate columns
    merged = gdf.merge(mun_df, left_on='mpio_code', right_on='mpio_code',
                       how='inner', suffixes=('_geom', '_stats'))
    # Consolidate name column if it was duplicated
    if 'name_stats' in merged.columns:
        merged['name'] = merged['name_stats']
    return merged

def plot_choropleth_building_count(gdf, output_path):
    """Choropleth map: building count per municipality."""
    fig, ax = plt.subplots(figsize=(14, 10), dpi=200)

    gdf.plot(
        column='building_count',
        ax=ax,
        legend=True,
        legend_kwds={'label': "Cantidad de Edificaciones", 'shrink': 0.8},
        cmap='YlOrRd',
        edgecolor='black',
        linewidth=0.3,
    )

    ax.set_title('Cantidad de Edificaciones por Municipio PDET\n(Microsoft Global ML Building Footprints)',
                 fontsize=14, fontweight='bold', pad=20)
    ax.set_xlabel('Longitud', fontsize=10)
    ax.set_ylabel('Latitud', fontsize=10)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=200, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {output_path.relative_to(ROOT)}")

def plot_choropleth_total_area(gdf, output_path):
    """Choropleth map: total rooftop area per municipality."""
    fig, ax = plt.subplots(figsize=(14, 10), dpi=200)

    # Convert m² to km²
    gdf['total_area_km2'] = gdf['total_area_m2'] / 1e6

    gdf.plot(
        column='total_area_km2',
        ax=ax,
        legend=True,
        legend_kwds={'label': "Área Total (km²)", 'shrink': 0.8},
        cmap='RdYlGn',
        edgecolor='black',
        linewidth=0.3,
    )

    ax.set_title('Área Total de Techos por Municipio PDET\n(Microsoft Global ML Building Footprints)',
                 fontsize=14, fontweight='bold', pad=20)
    ax.set_xlabel('Longitud', fontsize=10)
    ax.set_ylabel('Latitud', fontsize=10)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=200, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {output_path.relative_to(ROOT)}")

def plot_choropleth_mean_area(gdf, output_path):
    """Choropleth map: mean rooftop area per building."""
    fig, ax = plt.subplots(figsize=(14, 10), dpi=200)

    # Filter out NaN values
    gdf_valid = gdf[gdf['mean_area_m2'].notna()]

    gdf_valid.plot(
        column='mean_area_m2',
        ax=ax,
        legend=True,
        legend_kwds={'label': "Área Promedio (m²)", 'shrink': 0.8},
        cmap='viridis',
        edgecolor='black',
        linewidth=0.3,
    )

    ax.set_title('Área Promedio de Techos por Municipio PDET\n(Microsoft Global ML Building Footprints)',
                 fontsize=14, fontweight='bold', pad=20)
    ax.set_xlabel('Longitud', fontsize=10)
    ax.set_ylabel('Latitud', fontsize=10)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=200, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {output_path.relative_to(ROOT)}")

def plot_top_municipalities(gdf, output_path):
    """Bar chart: Top 15 municipalities by area."""
    # Sort by rank and take top 15
    top15 = gdf.nlargest(15, 'total_area_m2').copy()
    top15['total_area_km2'] = top15['total_area_m2'] / 1e6
    top15 = top15.sort_values('total_area_km2', ascending=True)

    fig, ax = plt.subplots(figsize=(12, 8), dpi=200)

    # Color bar by low-coverage flag
    colors = [GOOGLE_ORANGE if code in GOOGLE_COBERTURA_INSUFICIENTE else MS_BLUE
              for code in top15['mpio_code']]

    ax.barh(range(len(top15)), top15['total_area_km2'], color=colors)
    ax.set_yticks(range(len(top15)))
    ax.set_yticklabels([f"{row['name']}\n({row['mpio_code']})"
                        for _, row in top15.iterrows()], fontsize=9)
    ax.set_xlabel('Área Total (km²)', fontsize=11, fontweight='bold')
    ax.set_title('Top 15 Municipios PDET por Área de Techos\n(Orange = Cobertura Insuficiente de Google)',
                 fontsize=12, fontweight='bold', pad=15)
    ax.grid(True, alpha=0.3, axis='x')

    plt.tight_layout()
    plt.savefig(output_path, dpi=200, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {output_path.relative_to(ROOT)}")

def plot_scatter_count_vs_area(gdf, output_path):
    """Scatter: Building count vs total area."""
    fig, ax = plt.subplots(figsize=(11, 8), dpi=200)

    gdf_valid = gdf[gdf['building_count'] > 0].copy()
    gdf_valid['total_area_km2'] = gdf_valid['total_area_m2'] / 1e6

    colors = [GOOGLE_ORANGE if code in GOOGLE_COBERTURA_INSUFICIENTE else MS_BLUE
              for code in gdf_valid['mpio_code']]

    ax.scatter(gdf_valid['building_count'], gdf_valid['total_area_km2'],
               c=colors, s=80, alpha=0.6, edgecolors='black', linewidth=0.5)

    # Add labels for top 5
    top5 = gdf_valid.nlargest(5, 'total_area_km2')
    for _, row in top5.iterrows():
        ax.annotate(row['name'],
                   xy=(row['building_count'], row['total_area_km2']),
                   xytext=(5, 5), textcoords='offset points', fontsize=8)

    ax.set_xlabel('Cantidad de Edificaciones', fontsize=11, fontweight='bold')
    ax.set_ylabel('Área Total (km²)', fontsize=11, fontweight='bold')
    ax.set_title('Correlación: Cantidad vs Área de Techos por Municipio\n(Spearman ρ=0.904)',
                 fontsize=12, fontweight='bold', pad=15)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=200, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {output_path.relative_to(ROOT)}")

def plot_subregion_totals(gdf, analysis, output_path):
    """Bar chart: Subregion totals (buildings + area)."""
    subregions = analysis['subregions']

    # Convert to sorted list
    sub_list = [(name, data['building_count'], data['total_area_m2'] / 1e6)
                for name, data in subregions.items()]
    sub_list.sort(key=lambda x: x[2], reverse=True)

    names, counts, areas = zip(*sub_list)

    fig, ax1 = plt.subplots(figsize=(14, 8), dpi=200)

    x = np.arange(len(names))
    width = 0.35

    bars1 = ax1.bar(x - width/2, counts, width, label='Edificaciones', color=MS_BLUE, alpha=0.7)
    ax1.set_ylabel('Cantidad de Edificaciones', fontsize=11, fontweight='bold', color=MS_BLUE)
    ax1.tick_params(axis='y', labelcolor=MS_BLUE)

    ax2 = ax1.twinx()
    bars2 = ax2.bar(x + width/2, areas, width, label='Área (km²)', color=GOOGLE_ORANGE, alpha=0.7)
    ax2.set_ylabel('Área Total (km²)', fontsize=11, fontweight='bold', color=GOOGLE_ORANGE)
    ax2.tick_params(axis='y', labelcolor=GOOGLE_ORANGE)

    ax1.set_xlabel('Subregión PDET', fontsize=11, fontweight='bold')
    ax1.set_title('Edificaciones y Área de Techos por Subregión PDET',
                  fontsize=12, fontweight='bold', pad=15)
    ax1.set_xticks(x)
    ax1.set_xticklabels(names, rotation=45, ha='right', fontsize=9)
    ax1.grid(True, alpha=0.3, axis='y')

    # Combine legends
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=10)

    plt.tight_layout()
    plt.savefig(output_path, dpi=200, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {output_path.relative_to(ROOT)}")

def main():
    if not ANALYSIS_JSON.exists():
        print(f"ERROR: {ANALYSIS_JSON} not found. Run Phase 1 first.", file=sys.stderr)
        return 1
    if not GEOJSONL.exists():
        print(f"ERROR: {GEOJSONL} not found.", file=sys.stderr)
        return 1

    print("Phase 2: Generating maps and charts...")

    # Read data
    analysis = read_analysis()
    gdf = read_municipalities_gdf()

    print(f"  Loaded {len(gdf)} municipalities geometries")

    # Join with stats
    gdf = join_data(gdf, analysis)
    print(f"  Joined {len(gdf)} municipalities with rooftop statistics")

    # Create output directory
    FIGURAS_DIR.mkdir(parents=True, exist_ok=True)

    # Generate visualizations
    print(f"\n  Generating choropleth maps...")
    plot_choropleth_building_count(gdf, FIGURAS_DIR / "map_buildings_count.png")
    plot_choropleth_total_area(gdf, FIGURAS_DIR / "map_total_area.png")
    plot_choropleth_mean_area(gdf, FIGURAS_DIR / "map_mean_area.png")

    print(f"\n  Generating comparison charts...")
    plot_top_municipalities(gdf, FIGURAS_DIR / "bar_top_municipalities.png")
    plot_scatter_count_vs_area(gdf, FIGURAS_DIR / "scatter_count_vs_area.png")
    plot_subregion_totals(gdf, analysis, FIGURAS_DIR / "subregion_totals.png")

    print(f"\nPhase 2 complete. Figures saved to: {FIGURAS_DIR.relative_to(ROOT)}")

    return 0

if __name__ == '__main__':
    sys.exit(main())
