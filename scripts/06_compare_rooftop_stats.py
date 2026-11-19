"""Compara exportaciones municipales del motor común; no calcula estadísticas de buildings.

Interfaz provisional hasta la publicación del contrato de Derek y el motor de Miguel.
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
from datetime import datetime
from pathlib import Path

from entrega2_contracts import ContractError, load_config, sha256_file, write_json, zfill_digits

ROOT = Path(__file__).resolve().parents[1]
INPUT_CONTRACT = "entrega4-comparison-input-provisional-v1"
OUTPUT_CONTRACT = "entrega4-comparison-provisional-v1"
METRICS = ("building_count", "total_area_m2", "mean_area_m2", "median_area_m2")


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


def timestamp(value, label):
    require(isinstance(value, str), f"{label}: falta fecha ISO 8601")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(parsed.utcoffset() is not None, f"{label}: falta zona horaria")
    except ValueError as exc:
        raise ContractError(f"{label}: fecha inválida") from exc


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
            "google_insufficient_detections": 5 * google < ms,
        })
    return result


def validate_export(payload, source, municipalities):
    """Verifica el sobre provisional sin imponer umbrales metodológicos propios."""
    require(isinstance(payload, dict), f"{source}: exportación debe ser un objeto")
    require(payload.get("contract") == INPUT_CONTRACT, f"{source}: contrato no reconocido")
    require(payload.get("status") == "complete", f"{source}: ejecución incompleta")
    require(payload.get("dataset_id") == source, f"{source}: fuente incorrecta")
    require(payload.get("evidence_kind") in ("definitive", "synthetic"),
            f"{source}: indicar evidence_kind definitive o synthetic; EDA no es resultado final")
    method = payload.get("methodology")
    require(isinstance(method, dict), f"{source}: falta metodología")
    for key in ("id", "version"):
        require(isinstance(method.get(key), str) and bool(method[key].strip()),
                f"{source}: falta methodology.{key}")
    require(isinstance(method.get("definition"), dict) and bool(method["definition"]),
            f"{source}: falta definición de metodología")
    require(method.get("empty_statistics") in ("zero", "null"),
            f"{source}: declarar política de media/mediana sin observaciones")
    filters = method.get("filters_by_source")
    require(isinstance(filters, dict) and set(filters) == {"ms", "google"}
            and all(isinstance(v, dict) for v in filters.values()),
            f"{source}: declarar filtros efectivos acordados de ambas fuentes")
    require(isinstance(payload.get("filters"), dict) and payload["filters"] == filters[source],
            f"{source}: filtros efectivos no coinciden con la metodología")
    provenance = payload.get("provenance")
    require(isinstance(provenance, dict), f"{source}: falta procedencia")
    timestamp(provenance.get("computed_at"), f"{source}: computed_at")
    for key in ("engine", "engine_version", "environment"):
        require(isinstance(provenance.get(key), str) and bool(provenance[key].strip()),
                f"{source}: falta provenance.{key}")
    references = provenance.get("input_references")
    require(isinstance(references, list) and bool(references), f"{source}: faltan referencias de entrada")
    for ref in references:
        require(isinstance(ref, dict) and isinstance(ref.get("path"), str) and bool(ref["path"])
                and isinstance(ref.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", ref["sha256"]),
                f"{source}: referencia de entrada sin ruta y SHA256 válido")
    rows = indexed(payload.get("municipalities"), source, municipalities)
    for code, row in rows.items():
        require(row.get("dataset_id") == source, f"{code}: fuente incorrecta en fila {source}")
        for metric in METRICS:
            require(metric in row, f"{source} {code}: falta {metric}; ausencia no es cero")
        nonnegative(row["building_count"], f"{source} {code} conteo", integer=True)
        nonnegative(row["total_area_m2"], f"{source} {code} área")
        count, total = row["building_count"], row["total_area_m2"]
        if count == 0:
            empty = 0 if method["empty_statistics"] == "zero" else None
            require(total == 0 and all(row[m] == empty and not isinstance(row[m], bool)
                                      for m in ("mean_area_m2", "median_area_m2")),
                    f"{source} {code}: estadísticas vacías no respetan la política declarada")
        else:
            for metric in ("mean_area_m2", "median_area_m2"):
                nonnegative(row[metric], f"{source} {code} {metric}")
            require(math.isclose(row["mean_area_m2"], total / count, rel_tol=1e-6, abs_tol=0.02),
                    f"{source} {code}: promedio inconsistente con conteo y área")
            require(row["median_area_m2"] <= total + 0.02, f"{source} {code}: mediana imposible")
    return rows


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


def compare(ms, google, municipalities, flags):
    sources = {"ms": validate_export(ms, "ms", municipalities),
               "google": validate_export(google, "google", municipalities)}
    require(ms["methodology"] == google["methodology"], "escenarios metodológicos incompatibles")
    require(ms["evidence_kind"] == google["evidence_kind"], "no mezclar evidencias sintéticas y definitivas")
    require(all(ms["provenance"][k] == google["provenance"][k] for k in ("engine", "engine_version")),
            "las fuentes no usan la misma versión del motor común")
    reference = indexed(flags, "señales de referencia", municipalities)
    ranks = {(source, metric): competition_ranks(rows, metric)
             for source, rows in sources.items() for metric in ("building_count", "total_area_m2")}
    result = []
    for code in sorted(municipalities):
        row = dict(reference[code])
        eligible = not row["google_insufficient_detections"]
        row.update({"evidence_kind": ms["evidence_kind"],
                    "methodology_id": ms["methodology"]["id"],
                    "methodology_version": ms["methodology"]["version"],
                    "comparison_eligible": eligible,
                    "comparison_status": "comparable" if eligible else "google_insufficient_detections_reference"})
        for source, rows in sources.items():
            original = rows[code]
            row.update({f"{source}_{m}": original[m] for m in METRICS})
            export = ms if source == "ms" else google
            row[f"{source}_computed_at"] = export["provenance"]["computed_at"]
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
    return {"contract": OUTPUT_CONTRACT, "status": "complete", "evidence_kind": ms["evidence_kind"],
            "methodology": ms["methodology"],
            "conventions": {
                "base_source": "ms", "contrast_source": "google",
                "difference": "google - ms", "absolute_difference": "abs(google - ms)",
                "percentage": "100 * (google - ms) / ms; null si ms = 0 o señal de exclusión",
                "rank": "descending competition (1,1,3); exact ties; all municipalities including zeros and flags",
                "signal_basis": "Entrega 3 EDA sin filtros de Entrega 4; 5 * google_buildings < ms_buildings",
                "flagged_values": "observaciones y rankings conservados; diferencias analíticas null",
                "interpretation": "discrepancia de detecciones; causa y exactitud no certificadas"},
            "summary": {"municipalities": len(result), "comparison_eligible": sum(r["comparison_eligible"] for r in result),
                        "reference_flagged": sum(r["google_insufficient_detections"] for r in result)},
            # Copias íntegras: no se pierden campos ni procedencia del motor al aplanar el CSV.
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
    parser.add_argument("--microsoft", type=Path, help="JSON exportado por el motor común y adaptado al sobre provisional")
    parser.add_argument("--google", type=Path, help="JSON de Google, mismo escenario")
    parser.add_argument("--reference-only", action="store_true", help="solo señal EDA; no es estadística final")
    parser.add_argument("--output-dir", type=Path, help="sustituye la carpeta configurada para salidas de comparación")
    args = parser.parse_args(argv)
    if args.reference_only and (args.microsoft or args.google):
        parser.error("--reference-only no acepta exportaciones finales")
    if not args.reference_only and not (args.microsoft and args.google):
        parser.error("se requieren --microsoft y --google; el EDA no los sustituye")
    try:
        config = load_config(root)
        spec = config["analysis"]["comparison"]
        municipalities = load_municipalities(root, config)
        reference_path = root / spec["reference_eda"]
        flags = reference_flags(read_json(reference_path), municipalities)
        paths = [reference_path, root / spec["municipalities"], root / config["sources"]["pdet_list"]["file"]]
        if args.reference_only:
            stem = "google_comparability_reference"
            report = {"contract": OUTPUT_CONTRACT, "status": "reference_only", "evidence_kind": "historical_eda",
                      "rule": "5 * google_buildings < ms_buildings (Google < 20 % MS); EDA sin filtros de Entrega 4",
                      "municipalities": flags,
                      "summary": {"municipalities": len(flags),
                                  "flagged": sum(r["google_insufficient_detections"] for r in flags),
                                  "google_zero": sum(r["reference_google_zero"] for r in flags)}}
        else:
            paths.extend([root / args.microsoft, root / args.google])
            report = compare(read_json(paths[-2]), read_json(paths[-1]), municipalities, flags)
            stem = ("synthetic_" if report["evidence_kind"] == "synthetic" else "") + "rooftop_stats_comparison"
        report["inputs"] = [{"path": str(p.relative_to(root)) if p.is_relative_to(root) else str(p),
                             "sha256": sha256_file(p)} for p in paths]
        out = root / (args.output_dir or Path(spec["output_dir"]))
        targets = [out / f"{stem}.{ext}" for ext in ("json", "csv")]
        require(len({p.resolve() for p in targets}) == 2 and
                not ({p.resolve() for p in paths} & {p.resolve() for p in targets}),
                "una salida no puede sobrescribir una entrada")
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
