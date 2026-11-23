"""Pruebas de scripts/06_rooftop_stats.py con datos SINTÉTICOS; no usan red ni MongoDB.

Ejecutar: .venv/bin/python -m unittest discover -s tests -p "test_rooftop_stats.py" -v
"""
import csv
import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rooftop_stats", ROOT / "scripts/06_rooftop_stats.py")
stats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stats)

CONFIG = {"analysis": {"min_area_m2": 20, "max_area_m2": None, "min_confidence": 0.7,
                       "confidence_sources": ["google"]}}
NOW = datetime(2026, 11, 19, tzinfo=timezone.utc)
MUNICIPIOS = [{"_id": code, "name": f"M{code}", "dpto_code": "05", "dpto_name": "D",
               "subregion_id": 1, "subregion_name": "S"} for code in ("05001", "05002", "05003")]


def group(code, areas, before=None, below=0, above=0, low=0):
    return {"_id": code, "areas": areas, "before": len(areas) + below + above + low if before is None else before,
            "below_min_area": below, "above_max_area": above, "low_confidence": low}


class FiltersTests(unittest.TestCase):
    def test_confidence_only_for_configured_sources(self):
        self.assertIsNone(stats.filters_for(CONFIG, "ms")["min_confidence"])
        self.assertEqual(stats.filters_for(CONFIG, "google")["min_confidence"], 0.7)

    def test_invalid_thresholds_rejected(self):
        bad = {"analysis": {**CONFIG["analysis"], "max_area_m2": 10}}
        with self.assertRaises(stats.StatsError):
            stats.filters_for(bad, "ms")

    def test_reason_order_and_boundaries(self):
        f = {"min_area_m2": 20.0, "max_area_m2": 1000.0, "min_confidence": 0.7}
        self.assertEqual(stats.exclusion_reason(19.99, 0.9, f), "below_min_area")
        self.assertEqual(stats.exclusion_reason(20.0, 0.9, f), "included")      # el mínimo se incluye
        self.assertEqual(stats.exclusion_reason(1000.0, 0.9, f), "included")    # el máximo se incluye
        self.assertEqual(stats.exclusion_reason(1000.1, 0.1, f), "above_max_area")
        self.assertEqual(stats.exclusion_reason(10, 0.1, f), "below_min_area")   # primer filtro que falla
        self.assertEqual(stats.exclusion_reason(50, None, f), "low_confidence")
        self.assertEqual(stats.exclusion_reason(50, 0.7, f), "included")

    def test_expression_omits_disabled_filters(self):
        f = stats.filters_for(CONFIG, "ms")
        branches = stats.reason_expression(f)["$switch"]["branches"]
        self.assertEqual([b["then"] for b in branches], ["below_min_area"])
        query = stats.included_query("ms", ["05001"], f)
        self.assertNotIn("confidence", query)
        self.assertNotIn("$lte", query["area_m2"])


class DocumentsTests(unittest.TestCase):
    def build(self, groups, dataset_id="ms"):
        return stats.build_documents(MUNICIPIOS, groups, dataset_id=dataset_id,
                                     filters=stats.filters_for(CONFIG, dataset_id), computed_at=NOW,
                                     low_coverage={"05002"})

    def test_all_municipalities_even_without_buildings(self):
        docs, totals = self.build([group("05001", [30.0, 50.0, 100.0], below=1)])
        self.assertEqual([d["mpio_code"] for d in docs], ["05001", "05002", "05003"])
        empty = docs[1]
        self.assertEqual((empty["building_count"], empty["total_area_m2"]), (0, 0.0))
        self.assertIsNone(empty["mean_area_m2"])
        self.assertIsNone(empty["median_area_m2"])
        self.assertEqual(totals["included"], 3)
        self.assertEqual(totals["excluded"]["total"], 1)
        self.assertTrue(totals["balanced"])

    def test_stats_and_compound_id(self):
        docs, _ = self.build([group("05001", [30.0, 50.0, 100.0, 40.0])])
        doc = docs[0]
        self.assertEqual(doc["_id"], {"mpio_code": "05001", "dataset_id": "ms"})
        self.assertEqual(doc["total_area_m2"], 220.0)
        self.assertEqual(doc["mean_area_m2"], 55.0)
        self.assertEqual(doc["median_area_m2"], 45.0)   # mediana exacta con número par
        self.assertEqual(doc["filters"], {"min_area_m2": 20.0, "max_area_m2": None, "min_confidence": None})
        self.assertNotIn("google_low_coverage", doc)

    def test_outside_pdet_counted_apart(self):
        _, totals = self.build([group("05001", [30.0]), group(None, [25.0]), group("99999", [40.0])])
        self.assertEqual(totals["outside_pdet_or_unassigned"], 2)
        self.assertEqual(totals["assigned_pdet"], 1)
        self.assertEqual(totals["buildings_in_source"], 3)

    def test_unbalanced_group_fails(self):
        with self.assertRaises(stats.StatsError):
            self.build([group("05001", [30.0], before=5)])

    def test_rank_by_total_area(self):
        docs, _ = self.build([group("05001", [30.0]), group("05003", [500.0])])
        ranks = {d["mpio_code"]: d["rank_total_area"] for d in docs}
        self.assertEqual(ranks, {"05003": 1, "05001": 2, "05002": 3})

    def test_google_low_coverage_flag(self):
        docs, _ = self.build([group("05001", [30.0])], dataset_id="google")
        self.assertEqual({d["mpio_code"]: d["google_low_coverage"] for d in docs},
                         {"05001": False, "05002": True, "05003": False})

    def test_csv_rows_and_blank_median(self):
        docs, _ = self.build([group("05001", [30.0, 50.0])])
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.csv"
            stats.write_csv(path, docs)
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["mpio_code"], "05001")
        self.assertEqual(rows[0]["median_area_m2"], "40.0")
        self.assertEqual(rows[1]["median_area_m2"], "")
        self.assertEqual(rows[0]["computed_at"], NOW.isoformat())


if __name__ == "__main__":
    unittest.main()
