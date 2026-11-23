"""Comparación definitiva: contrato y motor reales, observaciones SINTÉTICAS.

Cada exportación de prueba se crea en un directorio temporal; ninguna acredita
una ejecución real de Google. La prueba MS versionada solo lee evidencia ajena.
"""
import copy
import csv
import importlib.util
import io
import json
import shutil
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


c = module("compare_stats", "06_compare_rooftop_stats.py")
engine = module("stats_engine", "06_rooftop_stats.py")
NOW = datetime(2026, 11, 22, 15, 0, tzinfo=timezone.utc)


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = c.load_config(ROOT)
        for rel in ("config.yaml", "outputs/pdet_mgn_crosswalk.csv", "outputs/eda/eda_buildings_summary.json", "resources/MunicipiosPDET.xlsx"):
            dest = self.root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / rel, dest)
        self.municipalities = c.load_municipalities(self.root, self.config)
        self.codes = sorted(self.municipalities)
        self.eda = c.read_json(self.root / self.config["analysis"]["google_low_coverage_rule"]["reference_eda"])
        self.flags = c.reference_flags(self.eda, self.municipalities)
        self.create_export("ms")
        self.create_export("google")

    def paths(self, source):
        return (self.root / f"outputs/rooftop_stats_{source}.csv", self.root / f"outputs/rooftop_stats_{source}_report.json")

    def create_export(self, source, overrides=None):
        munis = [{"_id": code, "name": row["name_mgn"], "dpto_code": code[:2], "dpto_name": "SINTETICO",
                  "subregion_id": int(row["subregion_id"]), "subregion_name": row["subregion_name"]}
                 for code, row in self.municipalities.items()]
        groups = []
        for code in self.codes:
            areas = (overrides or {}).get(code, [30.0, 60.0, 90.0] if source == "ms" else [40.0, 60.0, 100.0])
            groups.append({"_id": code, "areas": areas, "before": len(areas),
                           "below_min_area": 0, "above_max_area": 0, "low_confidence": 0})
        docs, totals = engine.build_documents(munis, groups, dataset_id=source,
            filters=c.filters_for(self.config, source), computed_at=NOW,
            low_coverage={r["mpio_code"] for r in self.flags if r["google_low_coverage"]})
        csv_path, report_path = self.paths(source)
        engine.write_csv(csv_path, docs)
        report = {
            "role": "rooftop-stats-report", "contract": c.CONTRACT_VERSION,
            "script_version": engine.SCRIPT_VERSION, "dataset_id": source,
            "dataset": {"_id": source, "version": "SYNTHETIC_TEST"},
            "evidence_kind": "synthetic", "status": "computed",
            "methodology": c.methodology_metadata(self.config), "computed_at": NOW.isoformat(),
            "filters": c.filters_for(self.config, source), "filter_order": list(c.FILTER_ORDER),
            "totals": totals, "verification": {"ok": True, "checks": {"rerun_does_not_duplicate": True}},
            "passes_requested": 2, "passes": [{"documents_after": 170, "upserted": 170},
                {"documents_after": 170, "upserted": 0, "same_values_as_previous": True}],
            "outputs": {"csv": str(csv_path.relative_to(self.root)), "csv_sha256": c.sha256_file(csv_path)},
        }
        c.write_json(report_path, report)

    def load(self, source):
        return c.load_source(*self.paths(source), source, self.config, self.root)

    def compare(self):
        return c.compare(self.load("ms"), self.load("google"), self.municipalities, self.flags)

    def change_report(self, source, change):
        path = self.paths(source)[1]
        report = c.read_json(path)
        change(report)
        c.write_json(path, report)

    def change_csv(self, source, change, rehash=True):
        path = self.paths(source)[0]
        with path.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        change(rows)
        c.write_csv(path, rows)
        if rehash:
            self.change_report(source, lambda report: report["outputs"].update(csv_sha256=c.sha256_file(path)))

    def test_full_contract_and_all_original_metrics_and_engine_rank_preserved(self):
        google = self.load("google")
        result = self.compare()
        self.assertEqual(result["summary"], {"municipalities": 170, "comparison_eligible": 155, "reference_flagged": 15})
        self.assertIn("05031", {r["mpio_code"] for r in result["municipalities"]})
        original = {r["mpio_code"]: r for r in google["municipalities"]}
        for row in result["municipalities"]:
            for key, value in original[row["mpio_code"]].items():
                self.assertEqual(row[f"google_{key}"], value)
        self.assertEqual(result["source_exports"]["google"], google)
        self.assertNotEqual(result["filters_by_source"]["ms"], result["filters_by_source"]["google"])

    def test_rejects_duplicate_missing_unexpected_or_numeric_divipola(self):
        for mutate in (lambda r: r.append(r[0]), lambda r: r.pop(),
                       lambda r: r[0].update(mpio_code="99999"), lambda r: r[0].update(mpio_code="5031")):
            with self.subTest(mutate=mutate):
                self.create_export("google")
                self.change_csv("google", mutate)
                with self.assertRaises(c.ContractError): self.load("google")

    def test_rejects_source_swaps_in_report_and_rows(self):
        self.change_report("google", lambda r: r.update(dataset_id="ms"))
        with self.assertRaisesRegex(c.ContractError, "fuente incorrecta"): self.load("google")
        self.create_export("google")
        self.change_csv("google", lambda rows: rows[0].update(dataset_id="ms"))
        with self.assertRaises(c.ContractError): self.load("google")

    def test_rejects_wrong_hash_and_unbound_csv(self):
        self.change_csv("google", lambda rows: rows[0].update(name="ALTERADO"), rehash=False)
        with self.assertRaisesRegex(c.ContractError, "SHA256"): self.load("google")
        self.create_export("google")
        alternative = self.root / "alternative.csv"
        shutil.copyfile(self.paths("google")[0], alternative)
        with self.assertRaisesRegex(c.ContractError, "no es el declarado"):
            c.load_source(alternative, self.paths("google")[1], "google", self.config, self.root)

    def test_rejects_filters_and_methodology_inconsistent_with_current_config(self):
        for mutate in (lambda r: r["filters"].update(min_confidence=None),
                       lambda r: r["methodology"].update(version="other"),
                       lambda r: r["dataset"].update(_id="other"),
                       lambda r: r["dataset"].update(version=None),
                       lambda r: r.update(contract="other"), lambda r: r.update(script_version="other")):
            self.create_export("google")
            self.change_report("google", mutate)
            with self.assertRaises(c.ContractError): self.load("google")

    def test_rejects_unbalanced_reports_and_missing_rerun_evidence(self):
        for mutate in (lambda r: r["totals"].update(included=1), lambda r: r.update(passes_requested=1),
                       lambda r: r["passes"][1].update(same_values_as_previous=False),
                       lambda r: r["passes"][1].update(upserted=1)):
            self.create_export("google")
            self.change_report("google", mutate)
            with self.assertRaises(c.ContractError): self.load("google")

    def test_rejects_row_from_another_execution_and_missing_metric(self):
        self.change_csv("google", lambda rows: rows[0].update(computed_at="2026-11-21T15:00:00+00:00"))
        with self.assertRaisesRegex(c.ContractError, "fechas"): self.load("google")
        self.create_export("google")
        self.change_csv("google", lambda rows: rows[0].update(mean_area_m2=""))
        with self.assertRaises(c.ContractError): self.load("google")

    def test_signed_absolute_and_percentage_differences(self):
        code = self.codes[0]
        self.create_export("google", {code: [40.0, 60.0]})
        row = self.compare()["municipalities"][0]
        self.assertEqual(row["building_count_difference_google_minus_ms"], -1)
        self.assertEqual(row["building_count_absolute_difference"], 1)
        self.assertAlmostEqual(row["building_count_pct_difference_over_ms"], -100 / 3)
        self.assertEqual(row["total_area_m2_difference_google_minus_ms"], -80)
        self.assertAlmostEqual(row["total_area_m2_pct_difference_over_ms"], -100 * 80 / 180)

    def test_zeros_null_statistics_and_zero_denominators(self):
        first, second, third = self.codes[:3]
        self.create_export("ms", {first: [], second: []})
        self.create_export("google", {second: [], third: []})
        rows = self.compare()["municipalities"]
        self.assertIsNone(rows[0]["building_count_pct_difference_over_ms"])
        self.assertEqual(rows[0]["building_count_pct_status"], "zero_ms_denominator")
        self.assertEqual(rows[1]["google_building_count"], 0)
        self.assertIsNone(rows[1]["google_mean_area_m2"])
        self.assertIsNone(rows[1]["google_median_area_m2"])
        self.assertEqual(rows[1]["building_count_difference_google_minus_ms"], 0)
        self.assertEqual(rows[2]["building_count_pct_difference_over_ms"], -100)
        self.assertEqual(rows[2]["google_observation_status"], "no_observations")

    def test_flags_recomputed_and_observations_preserved_without_differences(self):
        rows = self.compare()["municipalities"]
        flagged = [r for r in rows if r["google_low_coverage"]]
        self.assertEqual(len(flagged), 15)
        self.assertTrue(all(r["google_building_count"] == 3 for r in flagged))
        self.assertTrue(all(r["total_area_m2_absolute_difference"] is None for r in flagged))
        eda = copy.deepcopy(self.eda)
        eda["municipalities"][0].update(ms_buildings=100, google_buildings=20)
        flags = {r["mpio_code"]: r for r in c.reference_flags(eda, self.municipalities)}
        self.assertFalse(flags[eda["municipalities"][0]["mpio_code"]]["google_low_coverage"])
        eda["municipalities"][0]["google_buildings"] = 19
        flags = {r["mpio_code"]: r for r in c.reference_flags(eda, self.municipalities)}
        self.assertTrue(flags[eda["municipalities"][0]["mpio_code"]]["google_low_coverage"])

    def test_rejects_stale_google_flag(self):
        self.change_csv("google", lambda rows: rows[0].update(google_low_coverage="true"))
        with self.assertRaises(c.ContractError): self.load("google")

    def test_competition_ties_and_original_sequential_rank(self):
        rows = self.compare()["municipalities"]
        self.assertEqual([r["google_rank_total_area_m2"] for r in rows[:3]], [1, 1, 1])
        self.assertEqual([r["google_rank_total_area"] for r in rows[:3]], [1, 2, 3])
        values = {"a": {"n": 5}, "b": {"n": 5}, "c": {"n": 2}, "d": {"n": 0}}
        self.assertEqual(c.competition_ranks(values, "n"), {"a": 1, "b": 1, "c": 3, "d": 4})

    def test_spearman_average_ties_known_answer_and_negative_relation(self):
        self.assertEqual(c.average_ranks([10, 20, 20, 30]), [1, 2.5, 2.5, 4])
        sources = {"ms": {}, "google": {}}
        reference = {}
        for code, x, y in zip(["10000", "10001", "10002", "10003"], [1, 2, 2, 3], [4, 3, 3, 1]):
            reference[code] = {"google_low_coverage": False}
            for src, val in (("ms", x), ("google", y)):
                sources[src][code] = {"building_count": val, "total_area_m2": val * 20}
        r = c.correlations(sources, reference)
        self.assertAlmostEqual(r["all_municipalities"]["building_count"]["rho"], -1)

    def test_spearman_dynamic_populations_codes_and_constant_null(self):
        code = self.codes[0]
        self.create_export("google", {code: []})
        report = self.compare()
        corrs = report["correlations"]
        self.assertEqual(corrs["all_municipalities"]["building_count"]["n"], 170)
        self.assertEqual(corrs["positive_in_both"]["building_count"]["n"], 169)
        primary = corrs["comparable_positive_in_both"]["building_count"]
        self.assertEqual(primary["n"], 154)
        self.assertEqual(len(primary["excluded_codes"]), 16)
        self.assertEqual(primary["exclusion_reasons"][code], ["nonpositive_google"])
        self.assertIsNone(primary["rho"])
        self.assertEqual(primary["status"], "constant_input")
        self.assertEqual(set(primary["included_codes"]) | set(primary["excluded_codes"]), set(self.codes))

    def test_spearman_insufficient_observations(self):
        sources = {src: {"10000": {"building_count": 1, "total_area_m2": 20}} for src in ("ms", "google")}
        result = c.correlations(sources, {"10000": {"google_low_coverage": False}})
        self.assertEqual(result["all_municipalities"]["building_count"]["status"], "insufficient_observations")

    def test_cli_end_to_end_uses_shared_csv_report_contract_and_is_reproducible(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(c.main([], self.root), 0)
            output = self.root / "outputs/delivery4/synthetic_rooftop_stats_comparison.json"
            first = output.read_bytes()
            self.assertEqual(c.main([], self.root), 0)
        self.assertEqual(first, output.read_bytes())
        result = c.read_json(output)
        self.assertEqual(result["evidence_kind"], "synthetic")
        self.assertEqual(len(result["inputs"]), 8)
        self.assertEqual(result["contract"], c.OUTPUT_CONTRACT)
        self.assertFalse((output.parent / "rooftop_stats_comparison.json").exists())
        with output.with_suffix(".csv").open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 170)
        self.assertEqual(rows[0]["mpio_code"], "05031")

    def test_cli_failure_preserves_evidence_and_synthetic_definitive_do_not_mix(self):
        previous = self.root / "outputs/delivery4/rooftop_stats_comparison.json"
        previous.parent.mkdir(parents=True)
        previous.write_text("PREVIOUS_EVIDENCE")
        self.change_report("google", lambda r: r.pop("evidence_kind"))
        with redirect_stderr(io.StringIO()): self.assertEqual(c.main([], self.root), 1)
        self.assertEqual(previous.read_text(), "PREVIOUS_EVIDENCE")

    def test_real_microsoft_export_is_readable_without_recomputing(self):
        cfg = c.load_config(ROOT)
        export = c.load_source(ROOT / "outputs/rooftop_stats_ms.csv", ROOT / "outputs/rooftop_stats_ms_report.json", "ms", cfg, ROOT)
        self.assertEqual(len(export["municipalities"]), 170)
        self.assertEqual(export["totals"]["included"], 1720535)
        self.assertEqual(export["evidence_kind"], "definitive")

    def test_rejects_definitive_export_from_a_partial_source_load(self):
        path = self.root / self.config["sources"]["google"]["prepare_report"]
        shutil.copyfile(ROOT / self.config["sources"]["google"]["prepare_report"], path)
        self.change_report("google", lambda r: r.pop("evidence_kind"))
        with self.assertRaisesRegex(c.ContractError, "carga parcial"):
            self.load("google")

    def test_config_rule_drift_is_rejected_by_shared_contract(self):
        self.config["analysis"]["google_low_coverage"] = []
        c.write_json(self.root / "config.yaml", self.config)  # JSON también es YAML válido.
        with redirect_stderr(io.StringIO()): self.assertEqual(c.main([], self.root), 1)


if __name__ == "__main__":
    unittest.main()
