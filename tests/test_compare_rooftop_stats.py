"""Comparación con datos SINTÉTICOS; referencia EDA real solo en prueba de regresión.

No calcula edificios, no necesita MongoDB y no escribe en outputs del repositorio.
"""
import copy
import csv
import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("compare_rooftop_stats", ROOT / "scripts/06_compare_rooftop_stats.py")
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

CODES = [f"{10000+i:05d}" for i in range(170)]  # arbitrarios; no representan municipios del DANE
MUNICIPALITIES = {code: {"mpio_code": code, "name_mgn": f"SINTETICO {i}",
                         "subregion_id": str(i % 16 + 1), "subregion_name": f"SINTETICA {i % 16 + 1}"}
                  for i, code in enumerate(CODES)}


def exports():
    method = {"id": "SYNTHETIC_TEST", "version": "1", "definition": {"area": "synthetic m2"},
              "empty_statistics": "zero",
              "filters_by_source": {"ms": {"synthetic_min_area": 20},
                                    "google": {"synthetic_min_area": 20, "synthetic_confidence": 0.7}}}
    result = []
    for source in ("ms", "google"):
        result.append({"contract": c.INPUT_CONTRACT, "status": "complete", "evidence_kind": "synthetic",
                       "dataset_id": source, "methodology": copy.deepcopy(method),
                       "filters": copy.deepcopy(method["filters_by_source"][source]),
                       "provenance": {"engine": "SYNTHETIC_FIXTURE_NO_ENGINE_EXECUTED", "engine_version": "1",
                                      "computed_at": "2026-11-19T10:00:00-05:00", "environment": "unittest",
                                      "input_references": [{"path": "SYNTHETIC", "sha256": "a" * 64}]},
                       "municipalities": [{"mpio_code": code, "dataset_id": source, "building_count": 10,
                                           "total_area_m2": 1000.0, "mean_area_m2": 100.0, "median_area_m2": 90.0}
                                          for code in CODES]})
    return result


def eda_reference():
    return {"municipalities": [{"mpio_code": code, "ms_buildings": 10, "google_buildings": 10} for code in CODES]}


def set_metrics(payload, index, count, total):
    payload["municipalities"][index].update(building_count=count, total_area_m2=total,
                                           mean_area_m2=total / count if count else 0,
                                           median_area_m2=total / count if count else 0)


def temp_root(root):
    cfg = {"sources": {"pdet_list": {"file": "reference.xlsx", "sheet": "Hoja1", "code_column": "code",
                                    "expected_municipalities": 170, "expected_subregions": 16}},
           "analysis": {"comparison": {"reference_eda": "eda.json", "municipalities": "municipalities.csv",
                                       "output_dir": "out"}}}
    (root / "config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    pd.DataFrame({"code": CODES}).to_excel(root / "reference.xlsx", sheet_name="Hoja1", index=False)
    c.write_csv(root / "municipalities.csv", list(MUNICIPALITIES.values()))
    (root / "eda.json").write_text(json.dumps(eda_reference()), encoding="utf-8")
    for source, export in zip(("ms", "google"), exports()):
        (root / f"{source}.json").write_text(json.dumps(export), encoding="utf-8")


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.ms, self.google = exports()
        self.flags = c.reference_flags(eda_reference(), MUNICIPALITIES)

    def compare(self):
        return c.compare(self.ms, self.google, MUNICIPALITIES, self.flags)

    def test_accepts_170_and_preserves_original_exports_and_source_specific_filters(self):
        original = copy.deepcopy(self.google)
        result = self.compare()
        self.assertEqual(result["summary"]["municipalities"], 170)
        self.assertEqual(result["source_exports"]["google"], original)
        self.assertEqual(self.google, original)
        self.assertNotEqual(self.ms["filters"], self.google["filters"])
        self.assertEqual(result["municipalities"][0]["google_median_area_m2"], 90)

    def test_join_uses_code_independently_of_order(self):
        set_metrics(self.google, 0, 15, 1500)
        self.google["municipalities"].reverse()
        rows = self.compare()["municipalities"]
        self.assertEqual(rows[0]["mpio_code"], CODES[0])
        self.assertEqual(rows[0]["google_building_count"], 15)

    def test_rejects_duplicates(self):
        self.google["municipalities"].append(copy.deepcopy(self.google["municipalities"][0]))
        with self.assertRaisesRegex(c.ContractError, "duplicado"):
            self.compare()

    def test_rejects_missing_and_unexpected_municipalities(self):
        for value in (None, "99999"):
            with self.subTest(value=value):
                self.ms, self.google = exports()
                if value is None:
                    self.google["municipalities"].pop()
                else:
                    self.google["municipalities"][0]["mpio_code"] = value
                with self.assertRaisesRegex(c.ContractError, "faltantes=.*inesperados="):
                    self.compare()

    def test_rejects_nontext_short_unicode_and_whitespace_codes(self):
        for value in (10000, "1000", " 10000", "١٠٠٠٠", None):
            with self.subTest(value=value):
                self.google["municipalities"][0]["mpio_code"] = value
                with self.assertRaisesRegex(c.ContractError, "DIVIPOLA"):
                    self.compare()

    def test_rejects_source_at_envelope_and_row(self):
        for target in (self.google, self.google["municipalities"][0]):
            with self.subTest(target=target is self.google):
                target["dataset_id"] = "ms"
                with self.assertRaisesRegex(c.ContractError, "fuente incorrecta"):
                    self.compare()
                target["dataset_id"] = "google"

    def test_rejects_effective_filters_different_from_methodology(self):
        self.google["filters"] = {}
        with self.assertRaisesRegex(c.ContractError, "filtros efectivos no coinciden"):
            self.compare()

    def test_rejects_different_method_id_version_definition_and_source_filter_maps(self):
        for key, value in (("id", "OTHER"), ("version", "2"), ("definition", {"area": "OTHER"}),
                           ("filters_by_source", {"ms": {}, "google": self.google["filters"]})):
            with self.subTest(key=key):
                self.ms, self.google = exports()
                self.google["methodology"][key] = value
                with self.assertRaisesRegex(c.ContractError, "incompatibles"):
                    self.compare()

    def test_rejects_engine_version_mismatch(self):
        self.google["provenance"]["engine_version"] = "2"
        with self.assertRaisesRegex(c.ContractError, "motor común"):
            self.compare()

    def test_rejects_missing_provenance_and_hash(self):
        for key in ("computed_at", "engine", "environment", "input_references"):
            with self.subTest(key=key):
                self.ms, self.google = exports()
                del self.google["provenance"][key]
                with self.assertRaises(c.ContractError):
                    self.compare()
        self.ms, self.google = exports()
        self.google["provenance"]["input_references"][0]["sha256"] = "bad"
        with self.assertRaisesRegex(c.ContractError, "SHA256"):
            self.compare()

    def test_rejects_naive_timestamp(self):
        self.google["provenance"]["computed_at"] = "2026-11-19T10:00:00"
        with self.assertRaisesRegex(c.ContractError, "zona horaria"):
            self.compare()

    def test_rejects_historical_or_mixed_evidence_and_incomplete_exports(self):
        for key, value in (("evidence_kind", "historical_eda"), ("evidence_kind", "definitive"),
                           ("status", "pending"), ("contract", "entrega3-buildings-v1")):
            with self.subTest(key=key, value=value):
                self.ms, self.google = exports()
                self.google[key] = value
                with self.assertRaises(c.ContractError):
                    self.compare()

    def test_signed_absolute_and_percentage_differences(self):
        set_metrics(self.google, 0, 15, 500)
        row = self.compare()["municipalities"][0]
        self.assertEqual(row["building_count_difference_google_minus_ms"], 5)
        self.assertEqual(row["building_count_absolute_difference"], 5)
        self.assertEqual(row["building_count_pct_difference_over_ms"], 50)
        self.assertEqual(row["total_area_m2_difference_google_minus_ms"], -500)
        self.assertEqual(row["total_area_m2_absolute_difference"], 500)
        self.assertEqual(row["total_area_m2_pct_difference_over_ms"], -50)

    def test_ms_zero_denominators_and_both_zero_are_null_percentages(self):
        set_metrics(self.ms, 0, 0, 0)
        set_metrics(self.ms, 1, 0, 0)
        set_metrics(self.google, 1, 0, 0)
        rows = self.compare()["municipalities"]
        for row in rows[:2]:
            self.assertIsNone(row["building_count_pct_difference_over_ms"])
            self.assertIsNone(row["total_area_m2_pct_difference_over_ms"])
            self.assertEqual(row["building_count_pct_status"], "zero_ms_denominator")
        self.assertEqual(rows[0]["building_count_difference_google_minus_ms"], 10)
        self.assertEqual(rows[1]["building_count_difference_google_minus_ms"], 0)

    def test_google_observed_zero_differs_from_missing_data(self):
        set_metrics(self.google, 0, 0, 0)
        row = self.compare()["municipalities"][0]
        self.assertEqual(row["google_building_count"], 0)
        self.assertEqual(row["google_observation_status"], "no_observations")
        self.assertEqual(row["building_count_pct_difference_over_ms"], -100)
        del self.google["municipalities"][0]["total_area_m2"]
        with self.assertRaisesRegex(c.ContractError, "ausencia no es cero"):
            self.compare()

    def test_respects_explicit_empty_statistics_null_policy(self):
        for payload in (self.ms, self.google):
            payload["methodology"]["empty_statistics"] = "null"
            set_metrics(payload, 0, 0, 0)
            payload["municipalities"][0].update(mean_area_m2=None, median_area_m2=None)
        row = self.compare()["municipalities"][0]
        self.assertIsNone(row["google_median_area_m2"])
        self.google["municipalities"][0]["mean_area_m2"] = 0
        with self.assertRaisesRegex(c.ContractError, "política declarada"):
            self.compare()

    def test_rejects_invalid_numbers_and_inconsistent_statistics(self):
        for metric, value in (("building_count", True), ("building_count", 1.5), ("total_area_m2", -1),
                              ("total_area_m2", float("nan")), ("median_area_m2", float("inf")),
                              ("mean_area_m2", None), ("mean_area_m2", 99), ("median_area_m2", 2000)):
            with self.subTest(metric=metric, value=value):
                self.ms, self.google = exports()
                self.google["municipalities"][0][metric] = value
                with self.assertRaises(c.ContractError):
                    self.compare()

    def test_descending_competition_ranking_with_exact_ties_and_zeros(self):
        for payload in (self.ms, self.google):
            set_metrics(payload, 0, 30, 3000)
            set_metrics(payload, 1, 30, 3000)
            set_metrics(payload, 2, 20, 2000)
            set_metrics(payload, 3, 0, 0)
        rows = self.compare()["municipalities"]
        for source in ("ms", "google"):
            for metric in ("building_count", "total_area_m2"):
                self.assertEqual([r[f"{source}_rank_{metric}"] for r in rows[:4]], [1, 1, 3, 170])

    def test_strict_reference_threshold_recomputed_and_independent_of_final_counts(self):
        eda = eda_reference()
        eda["municipalities"][0].update(ms_buildings=10, google_buildings=2)  # exactamente 20 %: no señal
        eda["municipalities"][1].update(ms_buildings=10, google_buildings=1)
        eda["municipalities"][2].update(ms_buildings=0, google_buildings=0)
        self.flags = c.reference_flags(eda, MUNICIPALITIES)
        self.assertEqual([f["google_insufficient_detections"] for f in self.flags[:3]], [False, True, False])
        row = self.compare()["municipalities"][1]
        self.assertEqual(row["google_building_count"], 10)  # se conserva el escenario, no el conteo EDA
        self.assertIsNone(row["building_count_absolute_difference"])
        self.assertEqual(row["building_count_pct_status"], "excluded_reference_signal")
        eda["municipalities"][1]["google_buildings"] = 3
        self.assertFalse(c.reference_flags(eda, MUNICIPALITIES)[1]["google_insufficient_detections"])

    def test_rejects_invalid_reference_counts_duplicates_and_missing_codes(self):
        for mutation in (lambda d: d["municipalities"].pop(),
                         lambda d: d["municipalities"].append(d["municipalities"][0]),
                         lambda d: d["municipalities"][0].update(google_buildings=-1)):
            eda = eda_reference()
            mutation(eda)
            with self.assertRaises(c.ContractError):
                c.reference_flags(eda, MUNICIPALITIES)


class CliTests(unittest.TestCase):
    def test_comparison_cli_json_csv_and_input_hashes(self):
        with TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            root = Path(tmp)
            temp_root(root)
            self.assertEqual(c.main(["--microsoft", "ms.json", "--google", "google.json"], root), 0)
            report = c.read_json(root / "out/synthetic_rooftop_stats_comparison.json")
            self.assertEqual(report["evidence_kind"], "synthetic")
            self.assertEqual(len(report["inputs"]), 5)
            with (root / "out/synthetic_rooftop_stats_comparison.csv").open(newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 170)
            self.assertEqual(rows[0]["mpio_code"], CODES[0])
            self.assertEqual(rows[0]["evidence_kind"], "synthetic")
            self.assertFalse((root / "out/rooftop_stats_comparison.json").exists())

    def test_reference_only_is_separate_from_definitive_results(self):
        with TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            root = Path(tmp)
            temp_root(root)
            self.assertEqual(c.main(["--reference-only"], root), 0)
            report = c.read_json(root / "out/google_comparability_reference.json")
            self.assertEqual(report["evidence_kind"], "historical_eda")
            self.assertEqual(report["status"], "reference_only")
            self.assertFalse((root / "out/rooftop_stats_comparison.json").exists())

    def test_failure_preserves_existing_outputs_and_inputs(self):
        with TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            root = Path(tmp)
            temp_root(root)
            path = root / "google.json"
            path.write_text('{"contract": "bad"}', encoding="utf-8")
            output = root / "out/rooftop_stats_comparison.json"
            output.parent.mkdir()
            output.write_text("PREVIOUS_EVIDENCE", encoding="utf-8")
            self.assertEqual(c.main(["--microsoft", "ms.json", "--google", "google.json"], root), 1)
            self.assertEqual(output.read_text(), "PREVIOUS_EVIDENCE")
            self.assertEqual(path.read_text(), '{"contract": "bad"}')

    def test_json_duplicate_keys_and_nonfinite_constants_fail(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            for text in ('{"x": 1, "x": 2}', '{"x": NaN}', '{"x": Infinity}'):
                with self.subTest(text=text):
                    path.write_text(text)
                    with self.assertRaises(c.ContractError):
                        c.read_json(path)

    def test_current_real_reference_matches_official_universe(self):
        # No declara una ejecución del motor: únicamente reproduce la señal histórica.
        config = c.load_config(ROOT)
        municipalities = c.load_municipalities(ROOT, config)
        eda = c.read_json(ROOT / config["analysis"]["comparison"]["reference_eda"])
        flags = c.reference_flags(eda, municipalities)
        self.assertEqual(len(flags), 170)
        self.assertEqual(sum(f["google_insufficient_detections"] for f in flags), 15)
        self.assertEqual(sum(f["reference_google_zero"] for f in flags), 5)
        self.assertIn("05031", municipalities)
        self.assertNotIn("5031", municipalities)


if __name__ == "__main__":
    unittest.main()
