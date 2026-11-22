#!/usr/bin/env python3
"""Fase 3: Generación automática de tablas Markdown de la Entrega 4.

Lee ``outputs/entrega4_analysis_summary.json`` y ``config.yaml`` y genera
``docs/delivery4/entrega4_analysis_tables.md`` sin cifras transcritas a mano
ni factores de aprovechamiento sin respaldo.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from entrega2_contracts import load_config  # noqa: E402
from entrega4_contracts import google_low_coverage_codes  # noqa: E402

ANALYSIS_JSON = ROOT / "outputs" / "entrega4_analysis_summary.json"
OUTPUT_MD = ROOT / "docs" / "delivery4" / "entrega4_analysis_tables.md"


def read_analysis() -> dict:
    return json.loads(ANALYSIS_JSON.read_text(encoding="utf-8"))


def format_number(num, decimals: int = 2) -> str:
    if num is None:
        return "-"
    if isinstance(num, float):
        return f"{num:,.{decimals}f}"
    return f"{num:,}"


def generate_top_municipalities(analysis: dict) -> str:
    mun = analysis["municipalities"]
    top15 = sorted(mun.values(), key=lambda x: x["rank_total_area"])[:15]

    lines = [
        "## Municipios con mayor área de huella de techos",
        "",
        "Los 15 municipios PDET con mayor área total de huella geodésica (Microsoft, `area_m2 >= 20`):",
        "",
        "| Rango | Código | Municipio | Subregión | Edificaciones | Área total (km²) | Área media (m²) | Área mediana (m²) |",
        "|------:|--------|-----------|-----------|--------------:|-----------------:|----------------:|------------------:|",
    ]
    for item in top15:
        mark = " (*)" if item["google_low_coverage"] else ""
        lines.append(
            f"| {item['rank_total_area']} | {item['mpio_code']} | {item['name']}{mark} | "
            f"{item['subregion_name']} | {format_number(item['building_count'], 0)} | "
            f"{format_number(item['total_area_m2'] / 1e6, 2)} | "
            f"{format_number(item['mean_area_m2'], 1)} | {format_number(item['median_area_m2'], 1)} |"
        )
    lines.extend([
        "",
        "*`(*)` indica municipio marcado con baja cobertura de Google en el EDA de la Entrega 3 (< 20 % respecto a Microsoft).*",
        "",
    ])
    return "\n".join(lines)


def generate_bottom_municipalities(analysis: dict) -> str:
    mun = analysis["municipalities"]
    bottom15 = sorted(mun.values(), key=lambda x: x["rank_total_area"], reverse=True)[:15]

    lines = [
        "## Municipios con menor área de huella de techos",
        "",
        "Los 15 municipios PDET con menor área total de huella geodésica (Microsoft, `area_m2 >= 20`):",
        "",
        "| Rango | Código | Municipio | Subregión | Edificaciones | Área total (km²) | Área media (m²) | Área mediana (m²) |",
        "|------:|--------|-----------|-----------|--------------:|-----------------:|----------------:|------------------:|",
    ]
    for item in bottom15:
        mark = " (*)" if item["google_low_coverage"] else ""
        lines.append(
            f"| {item['rank_total_area']} | {item['mpio_code']} | {item['name']}{mark} | "
            f"{item['subregion_name']} | {format_number(item['building_count'], 0)} | "
            f"{format_number(item['total_area_m2'] / 1e6, 2)} | "
            f"{format_number(item['mean_area_m2'], 1)} | {format_number(item['median_area_m2'], 1)} |"
        )
    lines.extend([
        "",
        "*`(*)` indica municipio marcado con baja cobertura de Google en el EDA de la Entrega 3 (< 20 % respecto a Microsoft).*",
        "",
    ])
    return "\n".join(lines)


def generate_subregion_totals(analysis: dict) -> str:
    subs = sorted(
        analysis["subregions"].items(),
        key=lambda item: item[1]["total_area_m2"],
        reverse=True,
    )
    lines = [
        "## Totales por subregión PDET",
        "",
        "Agregaciones de edificaciones y área total de huella por cada una de las 16 subregiones PDET (Microsoft):",
        "",
        "| Subregión | Edificaciones | Área total (km²) | Municipios |",
        "|-----------|--------------:|-----------------:|-----------:|",
    ]
    for sub_name, sub_data in subs:
        lines.append(
            f"| {sub_name} | {format_number(sub_data['building_count'], 0)} | "
            f"{format_number(sub_data['total_area_m2'] / 1e6, 2)} | {sub_data['municipality_count']} |"
        )
    lines.append("")
    return "\n".join(lines)


def generate_comparison_section(analysis: dict, low_coverage: set[str]) -> str:
    totals = analysis["global_totals"]
    eda_ref = analysis.get("eda_reference", {})
    eda_sources = eda_ref.get("sources", {})
    eda_comp = eda_ref.get("comparison", analysis.get("comparison_metadata", {}))
    g_filtered = analysis.get("google_filtered", {"available": False})

    lines = [
        "## Contraste Microsoft vs Google",
        "",
        "### Resultados definitivos de la Entrega 4 (con filtros metodológicos)",
        "",
        f"- **Municipios PDET cubiertos (Microsoft):** {analysis['metadata']['total_municipalities']} / 170",
        f"- **Edificaciones incluidas (Microsoft, `area_m2 >= 20`):** {format_number(totals['total_buildings'], 0)}",
        f"- **Área total de huella (Microsoft):** {format_number(totals['total_area_km2'], 2)} km²",
    ]
    if g_filtered.get("available"):
        lines.extend([
            f"- **Edificaciones incluidas (Google, `area_m2 >= 20`, `confidence >= 0.70`):** {format_number(g_filtered['total_buildings'], 0)}",
            f"- **Área total de huella (Google):** {format_number(g_filtered['total_area_km2'], 2)} km²",
            f"- **Municipios con edificaciones (Google):** {g_filtered['municipalities_with_buildings']} / 170",
        ])
    else:
        lines.append(
            "- **Google filtrado (Entrega 4):** pendiente de ejecución con `scripts/06_rooftop_stats.py --source google`; "
            "no se estiman cifras filtradas multiplicando razones del EDA."
        )

    ms_eda = eda_sources.get("ms", {})
    g_eda = eda_sources.get("google", {})
    lines.extend([
        "",
        "### Referencia histórica del EDA de la Entrega 3 (sin filtros de Entrega 4)",
        "",
        f"- **Microsoft sin filtros:** {format_number(ms_eda.get('prepared'), 0)} edificaciones, "
        f"{format_number((ms_eda.get('area_m2') or {}).get('sum', 0) / 1e6, 2)} km² (170 municipios)",
        f"- **Google sin filtros:** {format_number(g_eda.get('prepared'), 0)} edificaciones, "
        f"{format_number((g_eda.get('area_m2') or {}).get('sum', 0) / 1e6, 2)} km² (165 municipios)",
        f"- **Razón Google / Microsoft (EDA):** {format_number(eda_comp.get('google_over_ms_buildings'), 2)}x en conteo, "
        f"{format_number(eda_comp.get('google_over_ms_area'), 3)}x en área",
        f"- **Correlación Spearman (EDA, sobre los 165 municipios con Google > 0):** "
        f"{format_number(eda_comp.get('spearman_buildings_per_municipality'), 3)} en conteo y "
        f"{format_number(eda_comp.get('spearman_area_per_municipality'), 3)} en área",
        f"- **Municipios con baja cobertura de Google (`5 * google < ms` en EDA):** {len(low_coverage)}",
        "",
        "### Municipios marcados por baja cobertura de Google (EDA Entrega 3)",
        "",
        "Se conservan los registros observados y no se comparan directamente sus diferencias entre fuentes; la causa de la discrepancia no está demostrada:",
        "",
        "| Código | Municipio | Subregión | MS filtrado (E4) | MS sin filtros (EDA) | Google sin filtros (EDA) |",
        "|--------|-----------|-----------|-----------------:|---------------------:|-------------------------:|",
    ])

    for code in sorted(low_coverage):
        mun = analysis["municipalities"].get(code)
        if not mun:
            continue
        lines.append(
            f"| {code} | {mun['name']} | {mun['subregion_name']} | "
            f"{format_number(mun['building_count'], 0)} | "
            f"{format_number(mun.get('eda_ms_buildings'), 0)} | "
            f"{format_number(mun.get('eda_google_buildings'), 0)} |"
        )
    lines.append("")
    return "\n".join(lines)


def generate_methodology_section() -> str:
    return "\n".join([
        "## Resumen de metodología y contrato",
        "",
        "El detalle completo y la justificación están en [`entrega4_metodologia_y_contrato.md`](entrega4_metodologia_y_contrato.md) y en `config.yaml` (`analysis.*`).",
        "",
        "- **Fuente base y contraste:** Microsoft (`ms`, 170/170 municipios) como fuente base; Google (`google`, 165/170) como contraste separado, sin sumar ambas fuentes.",
        "- **Filtros definitivos:** `area_m2 >= 20` para ambas fuentes; `max_area_m2 = null` (sin tope superior); `confidence >= 0.70` únicamente para Google (`confidence_sources: [\"google\"]`).",
        "- **Confianza ausente en Microsoft:** el 99,9994 % de las huellas PDET de Microsoft tienen `confidence = null`, por lo que no se filtra por confianza ni se imputan valores artificiales.",
        "- **Huellas grandes y atípicos:** se conservan todas las huellas válidas `>= 20 m²` (bodegas e instalaciones reales) y se reportan media y mediana exacta por municipio.",
        "- **Asignación espacial:** centroide WGS84 intersectando los 170 polígonos MGN2025, con desempate determinista por código DIVIPOLA menor (0 empates observados en ambas fuentes).",
        "- **Área de huella vs área aprovechable:** los resultados expresan área geodésica de huella en `m²` (`km² = m² / 10^6`), límite superior del techo físico; no se aplica ningún factor de aprovechamiento solar sin respaldo.",
        "",
    ])


def main() -> int:
    if not ANALYSIS_JSON.exists():
        print(f"ERROR: falta {ANALYSIS_JSON}. Corra antes scripts/07_entrega4_analysis.py.", file=sys.stderr)
        return 1

    config = load_config(ROOT)
    low_coverage = google_low_coverage_codes(config)
    analysis = read_analysis()

    content = "\n".join([
        "# Entrega 4: Tablas de análisis de techos por municipio PDET",
        "",
        "**Generado automáticamente desde:** `outputs/entrega4_analysis_summary.json`",
        "",
        "---",
        "",
        generate_top_municipalities(analysis),
        generate_bottom_municipalities(analysis),
        generate_subregion_totals(analysis),
        generate_comparison_section(analysis, low_coverage),
        generate_methodology_section(),
    ])

    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD.write_text(content, encoding="utf-8")
    print(f"Fase 3 completa: {OUTPUT_MD.relative_to(ROOT).as_posix()} ({len(content)} caracteres)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
