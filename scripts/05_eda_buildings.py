"""EDA de las huellas de edificaciones cargadas (Entrega 3).

Lee las salidas medidas de la preparación, que la carga comprobó documento por
documento (`count_matches_prepared` y `municipalities_match_preparation` en
`outputs/buildings_*_load_report.json`):

- `outputs/buildings_<fuente>_prepared_by_municipality.csv`: conteo y área por municipio;
- `outputs/buildings_<fuente>_prepare_report.json`: totales y percentiles de área;
- `outputs/pdet_mgn_crosswalk.csv`: subregión PDET de cada municipio.

No necesita MongoDB ni los archivos crudos, así que cualquier integrante lo
puede repetir. Para verificar la base cargada se usa
`scripts/04_load_buildings.py --source <fuente> --verify-only`.

Ejecutar desde la raíz:  python scripts/05_eda_buildings.py
Salidas: outputs/eda/eda_buildings_summary.json y docs/delivery3/figuras/eda_*.png
"""
import csv
import json
import statistics
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("microsoft", "google")   # claves de `sources` en config.yaml
SUMMARY = Path("outputs/eda/eda_buildings_summary.json")
FIGURES = Path("docs/delivery3/figuras")


def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _spearman(xs: list[float], ys: list[float]) -> float:
    def ranks(values):
        order = sorted(range(len(values)), key=values.__getitem__)
        result = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            for k in range(i, j + 1):
                result[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return result
    return statistics.correlation(ranks(xs), ranks(ys))


def summarize(root: Path, config: dict) -> dict:
    """Calcula el resumen del EDA. Valida las entradas y falla si no cuadran."""
    subregion = {row["mpio_code"]: row["subregion_name"]
                 for row in _read_csv(root / "outputs/pdet_mgn_crosswalk.csv")}
    sources, per_mpio = {}, {}
    for key in SOURCES:
        cfg = config["sources"][key]
        report = json.loads((root / cfg["prepare_report"]).read_text(encoding="utf-8"))
        totals = report["totals"]
        rows = _read_csv(root / cfg["prepare_by_municipality"])
        counts = {row["mpio_code"]: int(row["prepared_buildings"] or 0) for row in rows}
        areas = {row["mpio_code"]: float(row["area_m2_sum"] or 0) for row in rows}
        if set(counts) != set(subregion):
            raise ValueError(f"{key}: los municipios del CSV no son los {len(subregion)} PDET")
        if sum(counts.values()) != totals["prepared"]:
            raise ValueError(f"{key}: el CSV suma {sum(counts.values())}, el reporte {totals['prepared']}")
        with_data = [c for c in counts.values() if c > 0]
        sources[cfg["id"]] = {
            "read": totals["read"],
            "excluded_outside_pdet": totals["excluded_outside_pdet"],
            "rejected": totals["rejected"],
            "repaired": totals["repaired"],
            "prepared": totals["prepared"],
            "area_m2": totals["area_m2"],
            "municipalities_with_buildings": len(with_data),
            "municipalities_without_buildings": sorted(c for c, n in counts.items() if n == 0),
            "buildings_per_municipality": {
                "median": statistics.median(with_data), "min": min(with_data), "max": max(with_data)},
        }
        per_mpio[cfg["id"]] = (counts, areas)
    names = {row["mpio_code"]: row["name"]
             for row in _read_csv(root / config["sources"]["microsoft"]["prepare_by_municipality"])}
    (ms_n, ms_a), (go_n, go_a) = per_mpio["ms"], per_mpio["google"]
    both = sorted(c for c in subregion if ms_n[c] > 0 and go_n[c] > 0)
    by_subregion = {}
    for code, name in subregion.items():
        row = by_subregion.setdefault(name, {"municipalities": 0, "ms_buildings": 0, "ms_area_m2": 0.0,
                                             "google_buildings": 0, "google_area_m2": 0.0})
        row["municipalities"] += 1
        row["ms_buildings"] += ms_n[code]
        row["ms_area_m2"] += ms_a[code]
        row["google_buildings"] += go_n[code]
        row["google_area_m2"] += go_a[code]
    municipalities = [{"mpio_code": c, "name": names[c], "subregion": subregion[c],
                       "ms_buildings": ms_n[c], "ms_area_m2": round(ms_a[c], 2),
                       "google_buildings": go_n[c], "google_area_m2": round(go_a[c], 2)}
                      for c in sorted(subregion)]
    return {
        "inputs": "outputs/buildings_*_prepare_report.json, outputs/buildings_*_prepared_by_municipality.csv, "
                  "outputs/pdet_mgn_crosswalk.csv",
        "sources": sources,
        "comparison": {
            "pdet_municipalities": len(subregion),
            "municipalities_in_both": len(both),
            "google_over_ms_buildings": round(sources["google"]["prepared"] / sources["ms"]["prepared"], 3),
            "google_over_ms_area": round(sources["google"]["area_m2"]["sum"] / sources["ms"]["area_m2"]["sum"], 3),
            "municipalities_google_more_buildings": sum(go_n[c] > ms_n[c] for c in both),
            "spearman_buildings_per_municipality": round(_spearman([ms_n[c] for c in both], [go_n[c] for c in both]), 3),
            "spearman_area_per_municipality": round(_spearman([ms_a[c] for c in both], [go_a[c] for c in both]), 3),
        },
        "by_subregion": dict(sorted(by_subregion.items(), key=lambda kv: -kv[1]["ms_area_m2"])),
        "municipalities": municipalities,
    }


def draw_figures(summary: dict, out_dir: Path) -> list[Path]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    colors = {"ms": "#1F5FAF", "google": "#E08A1E"}
    rows = summary["municipalities"]
    paths = []

    fig, ax = plt.subplots(figsize=(6, 5))
    both = [r for r in rows if r["ms_buildings"] and r["google_buildings"]]
    ax.scatter([r["ms_buildings"] for r in both], [r["google_buildings"] for r in both], s=12, color="#444")
    top = max(max(r["ms_buildings"], r["google_buildings"]) for r in both)
    ax.plot([1, top], [1, top], color="#999", lw=1, ls="--", label="igual conteo")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("Edificaciones Microsoft (por municipio)")
    ax.set_ylabel("Edificaciones Google (por municipio)")
    ax.legend(frameon=False); ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); paths.append(out_dir / "eda_conteo_ms_vs_google.png"); fig.savefig(paths[-1], dpi=200)
    plt.close(fig)

    subs = summary["by_subregion"]
    fig, ax = plt.subplots(figsize=(8, 5.5))
    labels = [name.title() for name in subs][::-1]
    y = range(len(labels))
    ax.barh([i + 0.2 for i in y], [v["ms_area_m2"] / 1e6 for v in subs.values()][::-1], 0.4,
            color=colors["ms"], label="Microsoft")
    ax.barh([i - 0.2 for i in y], [v["google_area_m2"] / 1e6 for v in subs.values()][::-1], 0.4,
            color=colors["google"], label="Google")
    ax.set_yticks(list(y)); ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("Área de huellas (km²)"); ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); paths.append(out_dir / "eda_area_por_subregion.png"); fig.savefig(paths[-1], dpi=200)
    plt.close(fig)
    return paths


def main(root: Path = ROOT) -> int:
    config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    summary = summarize(root, config)
    out = root / SUMMARY
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    figures = draw_figures(summary, root / FIGURES)
    for dataset_id, s in summary["sources"].items():
        print(f"{dataset_id}: {s['prepared']:,} edificaciones en {s['municipalities_with_buildings']} municipios; "
              f"área total {s['area_m2']['sum'] / 1e6:.1f} km², mediana {s['area_m2']['p50']} m²")
    print(json.dumps(summary["comparison"], ensure_ascii=False))
    print(f"Resumen: {SUMMARY}; figuras: {', '.join(str(p.relative_to(root)) for p in figures)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
