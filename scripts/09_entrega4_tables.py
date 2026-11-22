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
from entrega4_contracts import filters_for, google_low_coverage_codes  # noqa: E402

ANALYSIS_JSON = ROOT / "outputs" / "entrega4_analysis_summary.json"
OUTPUT_MD = ROOT / "docs" / "delivery4" / "entrega4_analysis_tables.md"


def _fmt_param(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def read_analysis() -> dict:
    return json.loads(ANALYSIS_JSON.read_text(encoding="utf-8"))


def format_number(num, decimals: int = 2) -> str:
    if num is None:
        return "-"
    if isinstance(num, float):
        return f"{num:,.{decimals}f}"
    return f"{num:,}"


def generate_top_municipalities(analysis: dict, min_area_label: str, ratio_pct_label: str) -> str:
    mun = analysis["municipalities"]
    top15 = sorted(mun.values(), key=lambda x: x["rank_total_area"])[:15]

    lines = [
        "## Municipios con mayor área de huella de techos",
        "",
        f"Los 15 municipios PDET con mayor área total de huella geodésica (Microsoft, `area_m2 >= {min_area_label}`):",
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
        f"*`(*)` indica municipio marcado con baja cobertura de Google en el EDA de la Entrega 3 (< {ratio_pct_label} % respecto a Microsoft).*",
        "",
    ])
    return "\n".join(lines)


def generate_bottom_municipalities(analysis: dict, min_area_label: str, ratio_pct_label: str) -> str:
    mun = analysis["municipalities"]
    bottom15 = sorted(mun.values(), key=lambda x: x["rank_total_area"], reverse=True)[:15]

    lines = [
        "## Municipios con menor área de huella de techos",
        "",
        f"Los 15 municipios PDET con menor área total de huella geodésica (Microsoft, `area_m2 >= {min_area_label}`):",
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
        f"*`(*)` indica municipio marcado con baja cobertura de Google en el EDA de la Entrega 3 (< {ratio_pct_label} % respecto a Microsoft).*",
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
        f"Agregaciones de edificaciones y área total de huella por cada una de las {len(subs)} subregiones PDET (Microsoft):",
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


def generate_comparison_section(analysis: dict, low_coverage: set[str], config: dict) -> str:
    totals = analysis["global_totals"]
    eda_ref = analysis.get("eda_reference", {})
    eda_sources = eda_ref.get("sources", {})
    eda_comp = eda_ref.get("comparison", analysis.get("comparison_metadata", {}))
    g_filtered = analysis.get("google_filtered", {"available": False})
    ms_f = filters_for(config, "ms")
    g_f = filters_for(config, "google")
    min_area_label = _fmt_param(ms_f["min_area_m2"])
    min_conf_label = f"{g_f['min_confidence']:.2f}" if g_f["min_confidence"] is not None else "null"
    total_munis = analysis["metadata"]["total_municipalities"]
    ms_with_buildings = sum(1 for m in analysis["municipalities"].values() if m["building_count"] > 0)

    lines = [
        "## Contraste Microsoft vs Google",
        "",
        "### Resultados definitivos de la Entrega 4 (con filtros metodológicos)",
        "",
        f"- **Municipios PDET cubiertos (Microsoft):** {ms_with_buildings} / {total_munis}",
        f"- **Edificaciones incluidas (Microsoft, `area_m2 >= {min_area_label}`):** {format_number(totals['total_buildings'], 0)}",
        f"- **Área total de huella (Microsoft):** {format_number(totals['total_area_km2'], 2)} km²",
    ]
    if g_filtered.get("available"):
        lines.extend([
            f"- **Edificaciones incluidas (Google, `area_m2 >= {min_area_label}`, `confidence >= {min_conf_label}`):** {format_number(g_filtered['total_buildings'], 0)}",
            f"- **Área total de huella (Google):** {format_number(g_filtered['total_area_km2'], 2)} km²",
            f"- **Municipios con edificaciones (Google):** {g_filtered['municipalities_with_buildings']} / {total_munis}",
        ])
    else:
        lines.append(
            "- **Google filtrado (Entrega 4):** pendiente de ejecución con `scripts/06_rooftop_stats.py --source google`; "
            "no se estiman cifras filtradas multiplicando razones del EDA."
        )

    ms_eda = eda_sources.get("ms", {})
    g_eda = eda_sources.get("google", {})
    ms_munis = ms_eda.get("municipalities_with_buildings", total_munis)
    g_munis = g_eda.get("municipalities_with_buildings", eda_comp.get("municipalities_in_both"))
    in_both = eda_comp.get("municipalities_in_both", g_munis)
    lines.extend([
        "",
        "### Referencia histórica del EDA de la Entrega 3 (sin filtros de Entrega 4)",
        "",
        f"- **Microsoft sin filtros:** {format_number(ms_eda.get('prepared'), 0)} edificaciones, "
        f"{format_number((ms_eda.get('area_m2') or {}).get('sum', 0) / 1e6, 2)} km² ({ms_munis} municipios)",
        f"- **Google sin filtros:** {format_number(g_eda.get('prepared'), 0)} edificaciones, "
        f"{format_number((g_eda.get('area_m2') or {}).get('sum', 0) / 1e6, 2)} km² ({g_munis} municipios)",
        f"- **Razón Google / Microsoft (EDA):** {format_number(eda_comp.get('google_over_ms_buildings'), 2)}x en conteo, "
        f"{format_number(eda_comp.get('google_over_ms_area'), 3)}x en área",
        f"- **Correlación Spearman (EDA, sobre los {in_both} municipios con Google > 0):** "
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


def generate_methodology_section(analysis: dict, config: dict) -> str:
    ms_f = filters_for(config, "ms")
    g_f = filters_for(config, "google")
    min_area_label = _fmt_param(ms_f["min_area_m2"])
    max_area_label = "null (sin tope superior)" if ms_f["max_area_m2"] is None else _fmt_param(ms_f["max_area_m2"])
    min_conf_label = f"{g_f['min_confidence']:.2f}" if g_f["min_confidence"] is not None else "null"
    conf_sources = json.dumps(config["analysis"].get("confidence_sources") or [])
    eda_sources = analysis.get("eda_reference", {}).get("sources", {})
    total_munis = analysis["metadata"]["total_municipalities"]
    ms_munis = eda_sources.get("ms", {}).get("municipalities_with_buildings", total_munis)
    g_munis = eda_sources.get("google", {}).get("municipalities_with_buildings", "-")

    return "\n".join([
        "## Resumen de metodología y contrato",
        "",
        "El detalle completo y la justificación están en [`entrega4_metodologia_y_contrato.md`](entrega4_metodologia_y_contrato.md) y en `config.yaml` (`analysis.*`).",
        "",
        f"- **Fuente base y contraste:** Microsoft (`ms`, {ms_munis}/{total_munis} municipios) como fuente base; Google (`google`, {g_munis}/{total_munis}) como contraste separado, sin sumar ambas fuentes.",
        f"- **Filtros definitivos:** `area_m2 >= {min_area_label}` para ambas fuentes; `max_area_m2 = {max_area_label}`; `confidence >= {min_conf_label}` únicamente para Google (`confidence_sources: {conf_sources}`).",
        "- **Confianza ausente en Microsoft:** en `buildings_ms_prepare_report.json` la casi totalidad de huellas PDET de Microsoft tiene `confidence = null`, por lo que no se filtra por confianza ni se imputan valores artificiales.",
        f"- **Huellas grandes y atípicos:** se conservan todas las huellas válidas `>= {min_area_label} m²` y se reportan media y mediana exacta por municipio.",
        f"- **Asignación espacial:** centroide WGS84 intersectando los {total_munis} polígonos MGN2025, con desempate determinista por código DIVIPOLA menor (0 empates observados en ambas fuentes).",
        "- **Área de huella vs área aprovechable:** los resultados expresan área geodésica de huella en `m²` (`km² = m² / 10^6`), límite superior del techo físico; no se aplica ningún factor de aprovechamiento solar sin respaldo (`usable_area_factor: null`).",
        "",
    ])


def main() -> int:
    if not ANALYSIS_JSON.exists():
        print(f"ERROR: falta {ANALYSIS_JSON}. Corra antes scripts/07_entrega4_analysis.py.", file=sys.stderr)
        return 1

    config = load_config(ROOT)
    low_coverage = google_low_coverage_codes(config)
    min_area_label = _fmt_param(filters_for(config, "ms")["min_area_m2"])
    ratio_pct_label = _fmt_param(config["analysis"]["google_low_coverage_rule"]["ratio_threshold"] * 100)
    analysis = read_analysis()

    content = "\n".join([
        "# Entrega 4: Tablas de análisis de techos por municipio PDET",
        "",
        "**Generado automáticamente desde:** `outputs/entrega4_analysis_summary.json`",
        "",
        "---",
        "",
        generate_top_municipalities(analysis, min_area_label, ratio_pct_label),
        generate_bottom_municipalities(analysis, min_area_label, ratio_pct_label),
        generate_subregion_totals(analysis),
        generate_comparison_section(analysis, low_coverage, config),
        generate_methodology_section(analysis, config),
    ])

    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD.write_text(content, encoding="utf-8")
    print(f"Fase 3 completa: {OUTPUT_MD.relative_to(ROOT).as_posix()} ({len(content)} caracteres)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
