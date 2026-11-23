"""Pruebas unitarias del contrato compartido y metodología de la Entrega 4.

No requieren red ni MongoDB; verifican config.yaml, las reglas de filtrado,
el esquema de documentos y CSV de rooftop_stats, y las salidas versionadas.

Ejecutar:
    .venv/bin/python -m unittest discover -s tests -p "test_entrega4_contracts.py" -v
"""
from __future__ import annotations

import csv
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from entrega2_contracts import ContractError, load_config  # noqa: E402
import entrega4_contracts as c4  # noqa: E402

NOW = datetime(2026, 11, 22, 15, 0, 0, tzinfo=timezone.utc)


def _valid_doc(dataset_id: str = "ms", count: int = 2, code: str = "05001") -> dict:
    if count == 0:
        total, mean, median = 0.0, None, None
        before, below = 1, 1
    else:
        total, mean, median = 120.0, 60.0, 50.0
        before, below = count + 1, 1
    doc = {
        "_id": {"mpio_code": code, "dataset_id": dataset_id},
        "mpio_code": code,
        "dataset_id": dataset_id,
        "name": "MUNICIPIO PRUEBA",
        "dpto_code": code[:2],
        "dpto_name": "DEPARTAMENTO",
        "subregion_id": 1,
        "subregion_name": "SUBREGIÓN",
        "building_count": count,
        "total_area_m2": total,
        "mean_area_m2": mean,
        "median_area_m2": median,
        "buildings_before_filters": before,
        "excluded": {"below_min_area": below, "above_max_area": 0, "low_confidence": 0},
        "rank_total_area": 1,
        "filters": {"min_area_m2": 20.0, "max_area_m2": None, "min_confidence": 0.7 if dataset_id == "google" else None},
        "computed_at": NOW,
        "script_version": "entrega4-rooftop-stats-v1",
    }
    if dataset_id == "google":
        doc["google_low_coverage"] = False
    return doc


class ConfigAndRulesTests(unittest.TestCase):
    def test_real_config_matches_contract_and_eda(self):
        config = load_config(ROOT)
        self.assertEqual(c4.verify_analysis_config(config, root=ROOT), [])
        method = c4.methodology_metadata(config)
        self.assertEqual(method["base_source"], "ms")
        self.assertEqual(method["contrast_source"], "google")
        self.assertIsNone(method["usable_area_factor"])
        self.assertEqual(method["empty_municipality_stats"], "null")

    def test_filters_for_microsoft_and_google(self):
        config = load_config(ROOT)
        ms_f = c4.filters_for(config, "ms")
        g_f = c4.filters_for(config, "google")
        self.assertEqual(ms_f, {"min_area_m2": 20.0, "max_area_m2": None, "min_confidence": None})
        self.assertEqual(g_f, {"min_area_m2": 20.0, "max_area_m2": None, "min_confidence": 0.7})
        with self.assertRaises(ContractError):
            c4.filters_for(config, "osm")

    def test_google_low_coverage_exact_integer_boundary(self):
        self.assertTrue(c4.is_google_low_coverage(100, 19))
        self.assertFalse(c4.is_google_low_coverage(100, 20))
        self.assertTrue(c4.is_google_low_coverage(1, 0))
        self.assertFalse(c4.is_google_low_coverage(0, 0))

    def test_exclusion_reason_precedence_and_missing_confidence(self):
        ms_f = {"min_area_m2": 20.0, "max_area_m2": None, "min_confidence": None}
        g_f = {"min_area_m2": 20.0, "max_area_m2": 5000.0, "min_confidence": 0.70}
        # Microsoft acepta confidence=None y huellas grandes sin tope.
        self.assertEqual(c4.exclusion_reason(20.0, None, ms_f), "included")
        self.assertEqual(c4.exclusion_reason(44720.44, None, ms_f), "included")
        self.assertEqual(c4.exclusion_reason(19.99, None, ms_f), "below_min_area")
        # Google excluye confianza ausente o < 0.70; prioridad: área antes que confianza.
        self.assertEqual(c4.exclusion_reason(10.0, None, g_f), "below_min_area")
        self.assertEqual(c4.exclusion_reason(6000.0, 0.2, g_f), "above_max_area")
        self.assertEqual(c4.exclusion_reason(80.0, None, g_f), "low_confidence")
        self.assertEqual(c4.exclusion_reason(80.0, 0.699, g_f), "low_confidence")
        self.assertEqual(c4.exclusion_reason(80.0, 0.70, g_f), "included")

    def test_optional_bool_parsing_is_case_insensitive(self):
        self.assertIsNone(c4.parse_optional_bool(""))
        self.assertIsNone(c4.parse_optional_bool(None))
        self.assertIs(c4.parse_optional_bool("true"), True)
        self.assertIs(c4.parse_optional_bool("True"), True)
        self.assertIs(c4.parse_optional_bool("TRUE"), True)
        self.assertIs(c4.parse_optional_bool("False"), False)
        self.assertEqual(c4.format_optional_bool(None), "")
        self.assertEqual(c4.format_optional_bool(True), "true")
        self.assertEqual(c4.format_optional_bool(False), "false")
        with self.assertRaises(ContractError):
            c4.parse_optional_bool("maybe")


class DocumentAndCsvContractTests(unittest.TestCase):
    def test_valid_documents_ms_google_and_empty(self):
        self.assertEqual(c4.rooftop_stats_doc_errors(_valid_doc("ms", 2)), [])
        self.assertEqual(c4.rooftop_stats_doc_errors(_valid_doc("google", 2), low_coverage_codes=set()), [])
        self.assertEqual(c4.rooftop_stats_doc_errors(_valid_doc("ms", 0)), [])

    def test_rejects_broken_document_invariants(self):
        # Municipio vacío con promedio en 0 en vez de null
        bad_empty = _valid_doc("ms", 0)
        bad_empty["mean_area_m2"] = 0.0
        self.assertTrue(c4.rooftop_stats_doc_errors(bad_empty))

        # Balance roto
        bad_bal = _valid_doc("ms", 2)
        bad_bal["buildings_before_filters"] = 99
        self.assertTrue(c4.rooftop_stats_doc_errors(bad_bal))

        # Promedio inconsistente
        bad_mean = _valid_doc("ms", 2)
        bad_mean["mean_area_m2"] = 999.0
        self.assertTrue(c4.rooftop_stats_doc_errors(bad_mean))

        # Bandera google_low_coverage indebida en ms / faltante en google
        bad_ms = _valid_doc("ms", 2)
        bad_ms["google_low_coverage"] = False
        self.assertTrue(c4.rooftop_stats_doc_errors(bad_ms))

        bad_g = _valid_doc("google", 2)
        del bad_g["google_low_coverage"]
        self.assertTrue(c4.rooftop_stats_doc_errors(bad_g))

    def test_real_microsoft_outputs_pass_full_contract(self):
        config = load_config(ROOT)
        ms_csv = ROOT / "outputs" / "rooftop_stats_ms.csv"
        ms_report = ROOT / "outputs" / "rooftop_stats_ms_report.json"
        payload = c4.load_rooftop_stats_export(ms_csv, ms_report, config, ROOT)
        self.assertEqual(payload["contract"], c4.CONTRACT_VERSION)
        self.assertEqual(payload["dataset_id"], "ms")
        self.assertEqual(len(payload["municipalities"]), 170)
        self.assertEqual(payload["totals"]["included"], 1720535)
        ok, lines = c4.check_workspace(ROOT, require_google=False)
        self.assertTrue(ok, "\n".join(lines))

    def test_csv_validator_catches_tampered_columns_and_order(self):
        with TemporaryDirectory() as tmp:
            bad_csv = Path(tmp) / "bad.csv"
            with bad_csv.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["mpio_code", "building_count"])
                writer.writerow(["05001", "10"])
            self.assertTrue(c4.rooftop_stats_csv_errors(bad_csv))

            # Reporte con SHA256 manipulado
            report = json.loads((ROOT / "outputs" / "rooftop_stats_ms_report.json").read_text(encoding="utf-8"))
            report["outputs"]["csv_sha256"] = "0" * 64
            errors = c4.rooftop_stats_report_errors(report, root=ROOT, config=load_config(ROOT))
            self.assertTrue(any("SHA256" in err for err in errors))


if __name__ == "__main__":
    unittest.main()
