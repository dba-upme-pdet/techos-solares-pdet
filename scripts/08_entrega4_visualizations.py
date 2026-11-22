#!/usr/bin/env python3
"""Fase 2: Generación de mapas coropletos y gráficos comparativos (Entrega 4).

Lee ``outputs/entrega4_analysis_summary.json`` y ``config.yaml``.
Para los mapas coropletos requiere ``data/processed/municipalities.geojsonl``;
con ``--charts-only`` regenera los gráficos de barras, dispersión y subregiones
sin requerir las geometrías municipales.

Salida: docs/delivery4/figuras/*.png
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from entrega2_contracts import load_config  # noqa: E402
from entrega4_contracts import google_low_coverage_codes  # noqa: E402

ANALYSIS_JSON = ROOT / "outputs" / "entrega4_analysis_summary.json"
GEOJSONL = ROOT / "data" / "processed" / "municipalities.geojsonl"
FIGURAS_DIR = ROOT / "docs" / "delivery4" / "figuras"

MS_BLUE = "#1F5FAF"
GOOGLE_ORANGE = "#E08A1E"
ZERO_GRAY = "#D9D9D9"


def read_analysis() -> dict:
    return json.loads(ANALYSIS_JSON.read_text(encoding="utf-8"))


def build_stats_df(analysis: dict) -> pd.DataFrame:
    return pd.DataFrame(list(analysis["municipalities"].values()))


def read_municipalities_gdf():
    import geopandas as gpd
    from shapely.geometry import shape

    rows = []
    with GEOJSONL.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                doc = json.loads(line)
                row = {"geometry": shape(doc["geometry"])}
                for key, val in doc.items():
                    if key == "_id":
                        row["mpio_code"] = val
                    elif key != "geometry":
                        row[key] = val
                rows.append(row)

    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    return gdf[gdf.geometry.is_valid]


def join_data(gdf, stats_df: pd.DataFrame):
    merged = gdf.merge(stats_df, on="mpio_code", how="left", suffixes=("_geom", "_stats"))
    if "name_stats" in merged.columns:
        merged["name"] = merged["name_stats"].fillna(merged.get("name_geom"))
    return merged


def _plot_zero_and_missing(ax, gdf, column: str, zero_mask):
    """Dibuja por separado municipios con valor 0 y datos ausentes (NaN)."""
    missing = gdf[gdf[column].isna()]
    zeros = gdf[zero_mask & gdf[column].notna()]
    legend_handles = []
    if len(zeros) > 0:
        zeros.plot(ax=ax, color=ZERO_GRAY, edgecolor="black", linewidth=0.35, hatch="///")
        legend_handles.append(Patch(facecolor=ZERO_GRAY, edgecolor="black", hatch="///", label="Valor cero (0)"))
    if len(missing) > 0:
        missing.plot(ax=ax, color="white", edgecolor="#666666", linewidth=0.35, hatch="...")
        legend_handles.append(Patch(facecolor="white", edgecolor="#666666", hatch="...", label="Dato ausente"))
    if legend_handles:
        ax.legend(handles=legend_handles, loc="lower left", fontsize=9)


def plot_choropleth_building_count(gdf, output_path: Path):
    fig, ax = plt.subplots(figsize=(14, 10), dpi=200)
    positive = gdf[gdf["building_count"] > 0]
    positive.plot(
        column="building_count",
        ax=ax,
        legend=True,
        legend_kwds={"label": "Cantidad de edificaciones (area >= 20 m²)", "shrink": 0.8},
        cmap="YlOrRd",
        edgecolor="black",
        linewidth=0.3,
    )
    _plot_zero_and_missing(ax, gdf, "building_count", gdf["building_count"] == 0)
    ax.set_title(
        "Cantidad de edificaciones por municipio PDET\n(Microsoft Global ML Building Footprints, área >= 20 m²)",
        fontsize=14, fontweight="bold", pad=20,
    )
    ax.set_xlabel("Longitud", fontsize=10)
    ax.set_ylabel("Latitud", fontsize=10)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  Guardado: {output_path.relative_to(ROOT).as_posix()}")


def plot_choropleth_total_area(gdf, output_path: Path):
    fig, ax = plt.subplots(figsize=(14, 10), dpi=200)
    gdf = gdf.copy()
    gdf["total_area_km2"] = gdf["total_area_m2"] / 1e6
    positive = gdf[gdf["building_count"] > 0]
    positive.plot(
        column="total_area_km2",
        ax=ax,
        legend=True,
        legend_kwds={"label": "Área total de huella (km²)", "shrink": 0.8},
        cmap="RdYlGn",
        edgecolor="black",
        linewidth=0.3,
    )
    _plot_zero_and_missing(ax, gdf, "total_area_km2", gdf["building_count"] == 0)
    ax.set_title(
        "Área total de huella de techos por municipio PDET\n(Microsoft Global ML Building Footprints, área >= 20 m²)",
        fontsize=14, fontweight="bold", pad=20,
    )
    ax.set_xlabel("Longitud", fontsize=10)
    ax.set_ylabel("Latitud", fontsize=10)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  Guardado: {output_path.relative_to(ROOT).as_posix()}")


def plot_choropleth_mean_area(gdf, output_path: Path):
    fig, ax = plt.subplots(figsize=(14, 10), dpi=200)
    valid = gdf[gdf["mean_area_m2"].notna()]
    valid.plot(
        column="mean_area_m2",
        ax=ax,
        legend=True,
        legend_kwds={"label": "Área media de huella por edificación (m²)", "shrink": 0.8},
        cmap="viridis",
        edgecolor="black",
        linewidth=0.3,
    )
    _plot_zero_and_missing(ax, gdf, "mean_area_m2", gdf["building_count"] == 0)
    ax.set_title(
        "Área media de huella por edificación en municipios PDET\n(Microsoft Global ML Building Footprints, área >= 20 m²)",
        fontsize=14, fontweight="bold", pad=20,
    )
    ax.set_xlabel("Longitud", fontsize=10)
    ax.set_ylabel("Latitud", fontsize=10)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  Guardado: {output_path.relative_to(ROOT).as_posix()}")


def plot_top_municipalities(df: pd.DataFrame, low_coverage: set[str], output_path: Path):
    top15 = df.nlargest(15, "total_area_m2").copy()
    top15["total_area_km2"] = top15["total_area_m2"] / 1e6
    top15 = top15.sort_values("total_area_km2", ascending=True)

    fig, ax = plt.subplots(figsize=(12, 8), dpi=200)
    colors = [GOOGLE_ORANGE if code in low_coverage else MS_BLUE for code in top15["mpio_code"]]
    ax.barh(range(len(top15)), top15["total_area_km2"], color=colors)
    ax.set_yticks(range(len(top15)))
    ax.set_yticklabels([f"{row['name']} ({row['mpio_code']})" for _, row in top15.iterrows()], fontsize=9)
    ax.set_xlabel("Área total de huella (km²)", fontsize=11, fontweight="bold")
    ax.set_title(
        "Top 15 municipios PDET por área total de huella (Microsoft, >= 20 m²)",
        fontsize=12, fontweight="bold", pad=15,
    )
    ax.grid(True, alpha=0.3, axis="x")
    handles = [Patch(facecolor=MS_BLUE, label="Microsoft (base; cobertura Google >= 20 % en EDA)")]
    if any(code in low_coverage for code in top15["mpio_code"]):
        handles.append(Patch(facecolor=GOOGLE_ORANGE, label="Marcado con baja cobertura de Google en EDA (< 20 %)"))
    ax.legend(handles=handles, loc="lower right", fontsize=9)
    plt.tight_layout()
    plt.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  Guardado: {output_path.relative_to(ROOT).as_posix()}")


def plot_scatter_count_vs_area(df: pd.DataFrame, low_coverage: set[str], output_path: Path):
    fig, ax = plt.subplots(figsize=(11, 8), dpi=200)
    valid = df[df["building_count"] > 0].copy()
    valid["total_area_km2"] = valid["total_area_m2"] / 1e6
    spearman_ms = valid["building_count"].rank(method="average").corr(
        valid["total_area_km2"].rank(method="average")
    )

    normal = valid[~valid["mpio_code"].isin(low_coverage)]
    flagged = valid[valid["mpio_code"].isin(low_coverage)]

    ax.scatter(
        normal["building_count"], normal["total_area_km2"],
        c=MS_BLUE, s=70, alpha=0.65, edgecolors="black", linewidth=0.5,
        label=f"Cobertura Google >= 20 % en EDA (n={len(normal)})",
    )
    ax.scatter(
        flagged["building_count"], flagged["total_area_km2"],
        c=GOOGLE_ORANGE, s=75, alpha=0.8, edgecolors="black", linewidth=0.5,
        label=f"Google poco comparable en EDA (< 20 %, n={len(flagged)})",
    )

    top5 = valid.nlargest(5, "total_area_km2")
    label_offsets = {
        "47001": (-74, 4),   # SANTA MARTA: arriba-izquierda
        "20001": (6, -11),   # VALLEDUPAR: abajo-derecha
    }
    for _, row in top5.iterrows():
        offset = label_offsets.get(row["mpio_code"], (6, 5))
        ax.annotate(
            row["name"],
            xy=(row["building_count"], row["total_area_km2"]),
            xytext=offset, textcoords="offset points", fontsize=8,
        )
    ax.set_xlim(right=valid["building_count"].max() * 1.09)
    ax.set_ylim(top=valid["total_area_km2"].max() * 1.08)

    ax.set_xlabel("Cantidad de edificaciones (Microsoft, >= 20 m²)", fontsize=11, fontweight="bold")
    ax.set_ylabel("Área total de huella (km²)", fontsize=11, fontweight="bold")
    ax.set_title(
        f"Relación entre cantidad de edificaciones y área total por municipio PDET\n"
        f"(Microsoft, n={len(valid)}; Spearman conteo vs área = {spearman_ms:.3f})",
        fontsize=12, fontweight="bold", pad=15,
    )
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=9)
    plt.tight_layout()
    plt.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  Guardado: {output_path.relative_to(ROOT).as_posix()}")


def plot_subregion_totals(analysis: dict, output_path: Path):
    subregions = analysis["subregions"]
    sub_list = [
        (name, data["building_count"], data["total_area_m2"] / 1e6)
        for name, data in subregions.items()
    ]
    sub_list.sort(key=lambda x: x[2], reverse=True)
    names, counts, areas = zip(*sub_list)

    fig, ax1 = plt.subplots(figsize=(14, 8), dpi=200)
    x = np.arange(len(names))
    width = 0.35

    ax1.bar(x - width / 2, counts, width, label="Edificaciones (Microsoft)", color=MS_BLUE, alpha=0.75)
    ax1.set_ylabel("Cantidad de edificaciones", fontsize=11, fontweight="bold", color=MS_BLUE)
    ax1.tick_params(axis="y", labelcolor=MS_BLUE)

    ax2 = ax1.twinx()
    ax2.bar(x + width / 2, areas, width, label="Área de huella (km²)", color=GOOGLE_ORANGE, alpha=0.75)
    ax2.set_ylabel("Área total de huella (km²)", fontsize=11, fontweight="bold", color=GOOGLE_ORANGE)
    ax2.tick_params(axis="y", labelcolor=GOOGLE_ORANGE)

    ax1.set_xlabel("Subregión PDET", fontsize=11, fontweight="bold")
    ax1.set_title("Edificaciones y área total de huella por subregión PDET (Microsoft, >= 20 m²)",
                  fontsize=12, fontweight="bold", pad=15)
    ax1.set_xticks(x)
    ax1.set_xticklabels(names, rotation=45, ha="right", fontsize=9)
    ax1.grid(True, alpha=0.3, axis="y")

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right", fontsize=10)

    plt.tight_layout()
    plt.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  Guardado: {output_path.relative_to(ROOT).as_posix()}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--charts-only",
        action="store_true",
        help="genera solo los gráficos que no requieren municipalities.geojsonl",
    )
    args = parser.parse_args(argv)

    if not ANALYSIS_JSON.exists():
        print(f"ERROR: falta {ANALYSIS_JSON}. Corra antes scripts/07_entrega4_analysis.py.", file=sys.stderr)
        return 1

    config = load_config(ROOT)
    low_coverage = google_low_coverage_codes(config)
    analysis = read_analysis()
    stats_df = build_stats_df(analysis)
    FIGURAS_DIR.mkdir(parents=True, exist_ok=True)

    if not args.charts_only:
        if not GEOJSONL.exists():
            print(f"ERROR: falta {GEOJSONL}. Use --charts-only o prepare la capa municipal.", file=sys.stderr)
            return 1
        gdf = join_data(read_municipalities_gdf(), stats_df)
        print(f"Fase 2: generando mapas coropletos ({len(gdf)} municipios)...")
        plot_choropleth_building_count(gdf, FIGURAS_DIR / "map_buildings_count.png")
        plot_choropleth_total_area(gdf, FIGURAS_DIR / "map_total_area.png")
        plot_choropleth_mean_area(gdf, FIGURAS_DIR / "map_mean_area.png")

    print("Fase 2: generando gráficos comparativos...")
    plot_top_municipalities(stats_df, low_coverage, FIGURAS_DIR / "bar_top_municipalities.png")
    plot_scatter_count_vs_area(stats_df, low_coverage, FIGURAS_DIR / "scatter_count_vs_area.png")
    plot_subregion_totals(analysis, FIGURAS_DIR / "subregion_totals.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
