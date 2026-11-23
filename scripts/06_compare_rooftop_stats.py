"""Compara exportaciones municipales del motor común; no calcula estadísticas de buildings.

Lee CSV + reporte mediante entrega4_contracts.load_rooftop_stats_export.
Contrato, fórmulas y comandos: docs/delivery4/entrega4_google_comparacion.md.
--reference-only recalcula SOLO la señal del EDA, nunca resultados finales.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import statistics
from pathlib import Path

from entrega2_contracts import ContractError, load_config, sha256_file, write_json, zfill_digits

from entrega4_contracts import (
    CONTRACT_VERSION, FILTER_ORDER, compute_google_low_coverage_codes, filters_for,
    load_rooftop_stats_export, methodology_metadata, verify_analysis_config,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_CONTRACT = "entrega4-source-comparison-v1"


def require(condition, message):
    if not condition:
        raise ContractError(message)


def read_json(path):
    def reject_constant(value):
        raise ContractError(f"{path}: valor JSON no finito {value}")

    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"{path}: clave JSON duplicada {key}")
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant,
                      object_pairs_hook=unique_keys)


def indexed(rows, label, expected=None):
    require(isinstance(rows, list) and bool(rows), f"{label}: faltan filas municipales")
    result = {}
    for row in rows:
        require(isinstance(row, dict), f"{label}: fila no es un objeto")
        code = row.get("mpio_code")
        require(isinstance(code, str) and re.fullmatch(r"[0-9]{5}", code),
                f"{label}: DIVIPOLA inválido {code!r}; debe ser texto de cinco dígitos")
        require(code not in result, f"{label}: código duplicado {code}")
        result[code] = row
    if expected is not None:
        missing, extra = set(expected) - result.keys(), result.keys() - set(expected)
        require(not missing and not extra,
                f"{label}: faltantes={sorted(missing)}, inesperados={sorted(extra)}")
    return result


def nonnegative(value, label, integer=False):
    require(type(value) in ((int,) if integer else (int, float))
            and math.isfinite(value) and value >= 0, f"{label}: número no negativo inválido")


def load_municipalities(root, config):
    """El cruce aporta etiquetas; el Excel del curso determina el universo esperado."""
    import pandas as pd

    spec = config["sources"]["pdet_list"]
    frame = pd.read_excel(root / spec["file"], sheet_name=spec["sheet"])
    codes = [zfill_digits(v, 5) for v in frame[spec["code_column"]]]
    require(len(codes) == len(set(codes)) == spec["expected_municipalities"] == 170,
            "la referencia oficial debe contener 170 códigos únicos")
    require(all(re.fullmatch(r"[0-9]{5}", c) for c in codes), "referencia DIVIPOLA inválida")
    with (root / config["analysis"]["comparison"]["municipalities"]).open(
            encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    result = indexed(rows, "cruce PDET", codes)
    require(len({r.get("subregion_id") for r in rows}) == spec["expected_subregions"] == 16,
            "el cruce PDET debe contener las 16 subregiones")
    for code, row in result.items():
        require(row.get("name_mgn") and row.get("subregion_name"), f"{code}: faltan etiquetas PDET")
    return result


def reference_flags(eda, municipalities):
    """Regla vigente: Google < 20 % MS en el EDA SIN filtros de la Entrega 4."""
    require(isinstance(eda, dict), "referencia EDA debe ser un objeto")
    rows = indexed(eda.get("municipalities"), "referencia EDA", municipalities)
    flagged = compute_google_low_coverage_codes(eda)
    result = []
    for code, row in sorted(rows.items()):
        for source in ("ms", "google"):
            nonnegative(row.get(f"{source}_buildings"), f"EDA {code} {source}", integer=True)
        ms, google = row["ms_buildings"], row["google_buildings"]
        result.append({
            "mpio_code": code,
            "evidence_kind": "historical_eda",
            "signal_basis": "entrega3_eda_unfiltered",
            "name": municipalities[code].get("name_mgn"),
            "subregion_name": municipalities[code].get("subregion_name"),
            "reference_ms_buildings": ms,
            "reference_google_buildings": google,
            "reference_google_over_ms": google / ms if ms else None,
            "reference_ms_zero": ms == 0,
            "reference_google_zero": google == 0,
            # Multiplicación entera: el umbral es estricto y no depende del redondeo.
            "google_low_coverage": code in flagged,
        })
    return result


def load_source(csv_path, report_path, source, config, root):
    """Reutiliza el contrato compartido y vincula el CSV solicitado con su reporte."""
    report = read_json(report_path)
    kind = report.get("evidence_kind", "definitive")
    require(kind in ("definitive", "synthetic"), "el EDA no es un resultado definitivo de rooftop_stats")
    require(report.get("dataset_id") == source, f"{source}: fuente incorrecta en reporte")
    dataset = report.get("dataset") or {}
    require(dataset.get("_id") == source and dataset.get("version"),
            f"{source}: falta identificación y versión del dataset de entrada")
    declared = (report.get("outputs") or {}).get("csv")
    require(isinstance(declared, str) and (root / declared).resolve() == csv_path.resolve(),
            f"{source}: el CSV solicitado no es el declarado por el reporte")
    require(sha256_file(csv_path) == report["outputs"].get("csv_sha256"),
            f"{source}: SHA256 del CSV no coincide con el reporte")
    payload = load_rooftop_stats_export(csv_path, report_path, config, root)
    if kind == "definitive":
        source_key = "microsoft" if source == "ms" else "google"
        prepare_path = root / config["sources"][source_key]["prepare_report"]
        prepared = read_json(prepare_path)
        require(prepared.get("status") == "ready_for_load" and prepared.get("dataset_id") == source,
                f"{source}: falta referencia de preparación completa")
        expected = prepared["totals"]["prepared"]
        require(report["totals"].get("buildings_in_source") == expected
                and report["totals"].get("assigned_pdet") == expected,
                f"{source}: estadísticas sobre una carga parcial o distinta de la preparación ({expected})")
        require((prepared.get("datasets_document") or {}).get("version") == dataset["version"],
                f"{source}: versión preparada y versión analizada diferentes")
        payload["prepared_input_reference"] = {"path": str(prepare_path.relative_to(root)),
                                               "sha256": sha256_file(prepare_path), "expected_buildings": expected}
    # El lector común admite el reporte MS histórico sin contract/methodology.
    # Cuando existen esos campos, nunca se sustituyen silenciosamente por config.
    require(report.get("contract", CONTRACT_VERSION) == CONTRACT_VERSION,
            f"{source}: contrato incompatible")
    require(report.get("methodology", methodology_metadata(config)) == methodology_metadata(config),
            f"{source}: metodología incompatible con config.yaml")
    require(report.get("script_version") == CONTRACT_VERSION, f"{source}: versión de motor incompatible")
    require(all(row["dataset_id"] == source for row in payload["municipalities"]),
            f"{source}: fuente incorrecta en filas")
    require(all(row["computed_at"] == report["computed_at"] for row in payload["municipalities"]),
            f"{source}: fechas de filas y reporte no corresponden a la misma ejecución")
    passes = report.get("passes") or []
    require(report.get("passes_requested", 0) >= 2 and len(passes) >= 2 and all(
        item.get("same_values_as_previous") is True and item.get("upserted") == 0
        and item.get("documents_after") == len(payload["municipalities"])
        for item in passes[1:]) and report["verification"]["checks"].get("rerun_does_not_duplicate") is True,
        f"{source}: falta evidencia de repetición sin duplicados y con los mismos valores")
    payload["source_report"] = report
    payload["evidence_kind"] = kind
    return payload


def competition_ranks(rows, metric):
    """Descendente, competición: 1, 1, 3. Empate exacto sobre valores exportados."""
    ordered = sorted(rows, key=lambda c: (-rows[c][metric], c))
    ranks, previous, rank = {}, None, 0
    for position, code in enumerate(ordered, 1):
        value = rows[code][metric]
        if value != previous:
            rank = position
        ranks[code], previous = rank, value
    return ranks


def average_ranks(values):
    """Rangos ascendentes con promedio de posiciones empatadas para Spearman."""
    ordered = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    i = 0
    while i < len(ordered):
        j = i + 1
        while j < len(ordered) and values[ordered[j]] == values[ordered[i]]:
            j += 1
        for index in ordered[i:j]:
            ranks[index] = (i + 1 + j) / 2
        i = j
    return ranks


def correlations(sources, reference):
    """Poblaciones dinámicas y exclusiones exactas, sin reutilizar correlaciones EDA."""
    result = {}
    for population in ("all_municipalities", "positive_in_both", "comparable_positive_in_both"):
        result[population] = {}
        for metric in ("building_count", "total_area_m2"):
            included, excluded = [], {}
            for code in sorted(reference):
                reasons = []
                if population != "all_municipalities":
                    reasons += [f"nonpositive_{src}" for src in ("ms", "google") if sources[src][code][metric] <= 0]
                if population == "comparable_positive_in_both" and reference[code]["google_low_coverage"]:
                    reasons.append("reference_google_low_coverage")
                if reasons:
                    excluded[code] = reasons
                else:
                    included.append(code)
            xs, ys = ([sources[src][code][metric] for code in included] for src in ("ms", "google"))
            rho, status = None, "insufficient_observations"
            if len(included) >= 2:
                status = "constant_input"
                if len(set(xs)) > 1 and len(set(ys)) > 1:
                    rho = statistics.correlation(average_ranks(xs), average_ranks(ys))
                    status = "defined"
            result[population][metric] = {
                "rho": rho, "status": status, "n": len(included),
                "included_codes": included, "excluded_codes": sorted(excluded),
                "exclusion_reasons": excluded,
                "use": "primary_comparable_contrast" if population == "comparable_positive_in_both" else "descriptive_sensitivity_including_reference_flags",
            }
    return result


def compare(ms, google, municipalities, flags):
    sources = {"ms": indexed(ms["municipalities"], "ms", municipalities),
               "google": indexed(google["municipalities"], "google", municipalities)}
    require(ms["methodology"] == google["methodology"], "escenarios metodológicos incompatibles")
    require(ms["evidence_kind"] == google["evidence_kind"], "no mezclar evidencias sintéticas y definitivas")
    evidence_kind = ms["evidence_kind"]
    require(ms["filters_by_source"] == google["filters_by_source"], "filtros de escenarios incompatibles")
    for source, payload in (("ms", ms), ("google", google)):
        require(payload["contract"] == CONTRACT_VERSION and payload["dataset_id"] == source,
                f"{source}: contrato o fuente incorrectos")
        require(payload["filters"] == payload["filters_by_source"][source], f"{source}: filtros incompatibles")
        require(all(row["dataset_id"] == source for row in sources[source].values()), f"{source}: fuente incorrecta en filas")
    require(ms["provenance"]["engine_version"] == google["provenance"]["engine_version"],
            "las fuentes no usan la misma versión del motor común")
    reference = indexed(flags, "señales de referencia", municipalities)
    require(all(row["google_low_coverage"] is reference[code]["google_low_coverage"]
                for code, row in sources["google"].items()), "bandera Google no coincide con la referencia recalculada")
    ranks = {(source, metric): competition_ranks(rows, metric)
             for source, rows in sources.items() for metric in ("building_count", "total_area_m2")}
    result = []
    for code in sorted(municipalities):
        row = dict(reference[code])
        eligible = not row["google_low_coverage"]
        row.update({"evidence_kind": evidence_kind,
                    "methodology_id": ms["methodology"]["id"],
                    "methodology_version": ms["methodology"]["version"],
                    "comparison_eligible": eligible,
                    "comparison_status": "comparable" if eligible else "google_low_coverage_reference"})
        for source, rows in sources.items():
            original = rows[code]
            row.update({f"{source}_{key}": value for key, value in original.items()})
            row[f"{source}_observation_status"] = "observed" if original["building_count"] else "no_observations"
            for metric in ("building_count", "total_area_m2"):
                row[f"{source}_rank_{metric}"] = ranks[source, metric][code]
        for metric in ("building_count", "total_area_m2"):
            base, contrast = sources["ms"][code][metric], sources["google"][code][metric]
            difference = contrast - base
            row[f"{metric}_difference_google_minus_ms"] = difference if eligible else None
            row[f"{metric}_absolute_difference"] = abs(difference) if eligible else None
            row[f"{metric}_pct_difference_over_ms"] = 100 * difference / base if eligible and base else None
            row[f"{metric}_pct_status"] = (
                "excluded_reference_signal" if not eligible else "zero_ms_denominator" if base == 0 else "defined")
        result.append(row)
    return {"contract": OUTPUT_CONTRACT, "status": "complete", "evidence_kind": evidence_kind,
            "methodology": ms["methodology"], "filters_by_source": ms["filters_by_source"],
            "conventions": {
                "base_source": "ms", "contrast_source": "google",
                "difference": "google - ms", "absolute_difference": "abs(google - ms)",
                "percentage": "100 * (google - ms) / ms; null si ms = 0 o señal de exclusión",
                "rank": "descending competition (1,1,3); exact ties; all municipalities including zeros and flags",
                "engine_rank": "original rank_total_area retained; sequential with mpio_code tiebreak",
                "spearman": "Pearson correlation of average ranks; exact populations and exclusions in correlations",
                "signal_basis": "Entrega 3 EDA sin filtros de Entrega 4; regla compartida, no escenario filtrado",
                "flagged_values": "observaciones y rankings conservados; diferencias analíticas null",
                "interpretation": "discrepancia de detecciones; causa y exactitud no certificadas"},
            "summary": {"municipalities": len(result), "comparison_eligible": sum(r["comparison_eligible"] for r in result),
                        "reference_flagged": sum(r["google_low_coverage"] for r in result)},
            "correlations": correlations(sources, reference),
            "source_exports": {"ms": ms, "google": google}, "municipalities": result}


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: str(v).lower() if isinstance(v, bool) else v for k, v in row.items()})


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--microsoft", type=Path, help="CSV MS; por defecto analysis.rooftop_stats.csv")
    parser.add_argument("--microsoft-report", type=Path, help="reporte JSON MS")
    parser.add_argument("--google", type=Path, help="CSV Google")
    parser.add_argument("--google-report", type=Path, help="reporte JSON Google")
    parser.add_argument("--reference-only", action="store_true", help="solo señal EDA; no estadística final")
    parser.add_argument("--output-dir", type=Path, help="carpeta de comparación")
    args = parser.parse_args(argv)
    if args.reference_only and any((args.microsoft, args.google, args.microsoft_report, args.google_report)):
        parser.error("--reference-only no acepta exportaciones finales")
    try:
        root = root.resolve()
        config = load_config(root)
        errors = verify_analysis_config(config, root=root)
        require(not errors, "; ".join(errors))
        rule = config["analysis"]["google_low_coverage_rule"]
        require(rule["basis"] == "entrega3_eda_unfiltered", "base de comparabilidad no reconocida")
        municipalities = load_municipalities(root, config)
        reference_path = root / rule["reference_eda"]
        flags = reference_flags(read_json(reference_path), municipalities)
        spec = config["analysis"]["comparison"]
        paths = [reference_path, root / spec["municipalities"], root / config["sources"]["pdet_list"]["file"], root / "config.yaml"]
        if args.reference_only:
            stem = "google_comparability_reference_current"
            report = {"contract": OUTPUT_CONTRACT, "status": "reference_only", "evidence_kind": "historical_eda",
                      "rule": rule, "municipalities": flags,
                      "summary": {"municipalities": len(flags),
                                  "flagged": sum(r["google_low_coverage"] for r in flags),
                                  "google_zero": sum(r["reference_google_zero"] for r in flags)}}
        else:
            exports = {}
            stats = config["analysis"]["rooftop_stats"]
            for source, csv_arg, report_arg in (("ms", args.microsoft, args.microsoft_report),
                                                ("google", args.google, args.google_report)):
                csv_path = root / (csv_arg or Path(stats["csv"].format(source=source)))
                report_path = root / (report_arg or Path(stats["report"].format(source=source)))
                exports[source] = load_source(csv_path, report_path, source, config, root)
                paths.extend([csv_path, report_path])
            report = compare(exports["ms"], exports["google"], municipalities, flags)
            stem = ("synthetic_" if report["evidence_kind"] == "synthetic" else "") + "rooftop_stats_comparison"
        report["inputs"] = [{"path": str(p.relative_to(root)) if p.is_relative_to(root) else str(p),
                             "sha256": sha256_file(p)} for p in paths]
        report["implementation"] = {"comparison_sha256": sha256_file(Path(__file__)),
                                    "contract_sha256": sha256_file(ROOT / "scripts/entrega4_contracts.py")}
        out = root / (args.output_dir or Path(spec["output_dir"]))
        targets = [out / f"{stem}.{ext}" for ext in ("json", "csv")]
        require(not ({p.resolve() for p in paths} & {p.resolve() for p in targets}), "una salida no puede sobrescribir una entrada")
        for target in targets:
            require(not target.is_symlink(), f"salida no puede ser un enlace simbólico: {target}")
        write_json(targets[0], report)
        write_csv(targets[1], report["municipalities"])
        label = "REFERENCIA HISTÓRICA, no resultados finales" if args.reference_only else report["evidence_kind"]
        print(f"[OK] {label}: {json.dumps(report['summary'])}")
        print(f"JSON: {targets[0]}\nCSV: {targets[1]}")
        return 0
    except (ContractError, OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
        print(f"[FALLA] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
