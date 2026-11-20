#!/usr/bin/env python3
"""Phase 3: Generate markdown tables and summary for Entrega 4.

Reads analysis JSON and generates markdown with tables of:
- Top 15 municipalities by area
- Bottom 15 municipalities
- 16 subregions with totals
- Comparison metadata and low-coverage flags

Output: docs/delivery4/entrega4_analysis_tables.md
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_JSON = ROOT / "outputs" / "entrega4_analysis_summary.json"
OUTPUT_MD = ROOT / "docs" / "delivery4" / "entrega4_analysis_tables.md"

# Low-coverage municipalities
GOOGLE_COBERTURA_INSUFICIENTE = {
    "05475", "05873", "19418", "27099", "27150", "27205", "27250",
    "27425", "27450", "27491", "27615", "27745", "52612", "52621", "73616"
}

def read_analysis():
    """Read analysis summary JSON."""
    with open(ANALYSIS_JSON, 'r', encoding='utf-8') as f:
        return json.load(f)

def format_number(num, decimals=2):
    """Format number with thousands separator."""
    if num is None:
        return "—"
    if isinstance(num, float):
        return f"{num:,.{decimals}f}"
    return f"{num:,}"

def generate_top_municipalities(analysis):
    """Generate markdown table: top 15 municipalities."""
    mun = analysis['municipalities']

    # Sort by rank (rank 1 = highest area)
    sorted_mun = sorted(mun.values(), key=lambda x: x['rank_total_area'])
    top15 = sorted_mun[:15]

    md = "## Municipios con Mayor Área de Techos\n\n"
    md += "Los 15 municipios PDET con mayor área total de techos aprovechables (Microsoft):\n\n"
    md += "| Rango | Código | Municipio | Subregión | Edificaciones | Área Total (km²) | Área Media (m²) | Área Mediana (m²) |\n"
    md += "|------:|--------|-----------|-----------|---------------:|------------------:|----------------:|------------------:|\n"

    for mun_data in top15:
        flag = "⚠️ " if mun_data['google_low_coverage'] else ""
        area_km2 = mun_data['total_area_m2'] / 1e6
        md += f"| {mun_data['rank_total_area']} | {mun_data['mpio_code']} | {flag}{mun_data['name']} | "
        md += f"{mun_data['subregion_name']} | {format_number(mun_data['building_count'], 0)} | "
        md += f"{format_number(area_km2, 2)} | {format_number(mun_data['mean_area_m2'], 1)} | "
        md += f"{format_number(mun_data['median_area_m2'], 1)} |\n"

    md += "\n*⚠️ = Cobertura insuficiente de Google (< 20% de edificaciones respecto a Microsoft)*\n\n"
    return md

def generate_bottom_municipalities(analysis):
    """Generate markdown table: bottom 15 municipalities."""
    mun = analysis['municipalities']

    # Sort by rank (rank 170 = lowest area)
    sorted_mun = sorted(mun.values(), key=lambda x: x['rank_total_area'], reverse=True)
    bottom15 = sorted_mun[:15]

    md = "## Municipios con Menor Área de Techos\n\n"
    md += "Los 15 municipios PDET con menor área total de techos aprovechables (Microsoft):\n\n"
    md += "| Rango | Código | Municipio | Subregión | Edificaciones | Área Total (km²) | Área Media (m²) | Área Mediana (m²) |\n"
    md += "|------:|--------|-----------|-----------|---------------:|------------------:|----------------:|------------------:|\n"

    for mun_data in bottom15:
        flag = "⚠️ " if mun_data['google_low_coverage'] else ""
        area_km2 = mun_data['total_area_m2'] / 1e6
        md += f"| {mun_data['rank_total_area']} | {mun_data['mpio_code']} | {flag}{mun_data['name']} | "
        md += f"{mun_data['subregion_name']} | {format_number(mun_data['building_count'], 0)} | "
        md += f"{format_number(area_km2, 2)} | {format_number(mun_data['mean_area_m2'], 1)} | "
        md += f"{format_number(mun_data['median_area_m2'], 1)} |\n"

    md += "\n*⚠️ = Cobertura insuficiente de Google*\n\n"
    return md

def generate_subregion_totals(analysis):
    """Generate markdown table: subregion totals."""
    subs = analysis['subregions']

    # Sort by area descending
    sorted_subs = sorted(subs.items(), key=lambda x: x[1]['total_area_m2'], reverse=True)

    md = "## Totales por Subregión PDET\n\n"
    md += "Agregaciones de edificaciones y área de techos por cada una de las 16 subregiones PDET:\n\n"
    md += "| Subregión | Edificaciones | Área Total (km²) | Municipios |\n"
    md += "|-----------|---------------:|------------------:|----------:|\n"

    for sub_name, sub_data in sorted_subs:
        area_km2 = sub_data['total_area_m2'] / 1e6
        md += f"| {sub_name} | {format_number(sub_data['building_count'], 0)} | "
        md += f"{format_number(area_km2, 2)} | {sub_data['municipality_count']} |\n"

    md += "\n"
    return md

def generate_comparison_section(analysis):
    """Generate markdown section: MS vs Google comparison."""
    comp = analysis['comparison_metadata']
    low_cov = analysis['low_coverage_count']

    md = "## Comparación Microsoft vs Google: Hallazgos Clave\n\n"

    md += f"- **Municipios con datos:** {analysis['metadata']['total_municipalities']} PDET\n"
    md += f"- **Edificaciones Microsoft:** {format_number(analysis['global_totals']['total_buildings'], 0)}\n"
    md += f"- **Área total (Microsoft):** {format_number(analysis['global_totals']['total_area_km2'], 2)} km²\n\n"

    md += "### Contraste con Google:\n\n"
    md += f"- **Edificaciones Google:** {format_number(analysis['global_totals']['total_buildings'] * comp.get('google_over_ms_buildings', 1), 0)} "
    md += f"({format_number(comp.get('google_over_ms_buildings', 1), 2)}x Microsoft)\n"
    md += f"- **Área Google:** {format_number(analysis['global_totals']['total_area_km2'] * comp.get('google_over_ms_area', 1), 2)} km² "
    md += f"({format_number(comp.get('google_over_ms_area', 1), 2)}x Microsoft)\n"
    md += f"- **Correlación Spearman (edificaciones):** {format_number(comp.get('spearman_buildings_per_municipality', 0), 3)}\n"
    md += f"- **Correlación Spearman (área):** {format_number(comp.get('spearman_area_per_municipality', 0), 3)}\n"
    md += f"- **Municipios con cobertura insuficiente de Google:** {low_cov} (< 20% de edificaciones respecto a Microsoft)\n\n"

    md += "### Municipios con Cobertura Insuficiente:\n\n"
    md += "Los siguientes municipios tienen representación deficiente en Google Building Footprints "
    md += "y no deben compararse directamente:\n\n"
    md += "| Código | Municipio | Subregión | MS Edificaciones | Google Edificaciones |\n"
    md += "|--------|-----------|-----------|------------------:|---------------------:|\n"

    for code in sorted(GOOGLE_COBERTURA_INSUFICIENTE):
        if code in analysis['municipalities']:
            mun = analysis['municipalities'][code]
            # Note: we don't have exact Google count here, so we note it's sparse
            md += f"| {code} | {mun['name']} | {mun['subregion_name']} | "
            md += f"{format_number(mun['building_count'], 0)} | Sparse |\n"

    md += "\n"
    return md

def generate_methodology_section():
    """Generate markdown section: Methodology."""
    md = "## Metodología\n\n"
    md += "### Fuente de Datos\n\n"
    md += "- **Microsoft Global ML Building Footprints** v2026-02-03 (ODbL-1.0), acceso 13 nov 2026\n"
    md += "- **Geometrías municipales:** Capas MGN2025 del DANE (170 municipios PDET)\n\n"

    md += "### Filtros Aplicados\n\n"
    md += "- **Área mínima:** 20 m² (umbral Entrega 1, confirmado en EDA)\n"
    md += "- **Área máxima:** Ninguna (bodegas e instalaciones son techo real)\n"
    md += "- **Ubicación:** Centroide dentro de geometría municipal PDET (`$geoWithin` sobre índice 2dsphere)\n\n"

    md += "### Cálculo\n\n"
    md += "1. Se lee el CSV `outputs/rooftop_stats_ms.csv` generado por `scripts/06_rooftop_stats.py`\n"
    md += "2. Se agrupa por municipio (código DANE 5 dígitos) con geometría de `data/processed/municipalities.geojsonl`\n"
    md += "3. Para cada municipio se calcula: conteo, suma de áreas, media, mediana\n"
    md += "4. Se genera un JSON de análisis (`outputs/entrega4_analysis_summary.json`)\n"
    md += "5. Se producen mapas coropletos con geopandas y gráficos con matplotlib\n"
    md += "6. Este informe integra todas las salidas en un PDF compilado con LaTeX\n\n"

    md += "### Limitaciones y Consideraciones\n\n"
    md += "- **Huellas muy grandes:** En Microsoft, el percentil 99 del área es 912 m² y el máximo 44.720 m². "
    md += "Son bodegas e instalaciones que sí representan techo real.\n"
    md += "- **Área aprovechable:** La cifra es la proyección del edificio (huella), sin descuento por orientación, "
    md += "sombra o pendiente. Para obtener área aprovechable, aplicar un factor de aprovechamiento según normativa.\n"
    md += "- **Cobertura de Google:** 15 municipios tienen < 20% de cobertura respecto a Microsoft. "
    md += "No se suman ambas fuentes; se reportan por separado.\n\n"

    return md

def main():
    if not ANALYSIS_JSON.exists():
        print(f"ERROR: {ANALYSIS_JSON} not found. Run Phase 1 first.", file=sys.stderr)
        return 1

    print("Phase 3: Generating tables and markdown summary...")

    analysis = read_analysis()

    # Generate markdown
    md = "# Entrega 4: Tablas de Análisis de Techos por Municipio PDET\n\n"
    md += f"**Generado automáticamente desde:** `outputs/entrega4_analysis_summary.json`\n\n"
    md += f"---\n\n"

    md += generate_top_municipalities(analysis)
    md += generate_bottom_municipalities(analysis)
    md += generate_subregion_totals(analysis)
    md += generate_comparison_section(analysis)
    md += generate_methodology_section()

    # Write output
    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_MD, 'w', encoding='utf-8') as f:
        f.write(md)

    print(f"  Generated {len(md)} characters of markdown")
    print(f"\nPhase 3 complete. Output: {OUTPUT_MD.relative_to(ROOT)}")

    return 0

if __name__ == '__main__':
    sys.exit(main())
