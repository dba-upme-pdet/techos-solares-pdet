"""Pruebas de scripts/10_validate_analysis.py y 11_run_analysis.py con datos SINTÉTICOS; sin red ni MongoDB.

Ejecutar: .venv/bin/python -m unittest discover -s tests -p "test_validate_analysis.py" -v
"""
import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validate = _load("validate_analysis", "scripts/10_validate_analysis.py")
runner = _load("run_analysis", "scripts/11_run_analysis.py")
rooftop = _load("rooftop_stats", "scripts/06_rooftop_stats.py")

CONFIG = {"analysis": {"min_area_m2": 20, "max_area_m2": 1000, "min_confidence": 0.7,
                       "confidence_sources": ["google"]}}


class ClassifyTests(unittest.TestCase):
    def test_same_rule_as_engine(self):
        """La reescritura en pandas da el mismo motivo que la regla del motor, huella por huella."""
        rows = [(10, None), (20, None), (19.99, 0.9), (1000, 0.7), (1000.01, 0.9), (50, 0.69), (50, None),
                (5000, 0.1), (30, 0.95)]
        df = pd.DataFrame(rows, columns=["area_m2", "confidence"])
        for dataset_id in ("ms", "google"):
            ours = validate.classify(df, validate.filters_for(CONFIG, dataset_id)).tolist()
            engine_filters = rooftop.filters_for(CONFIG, dataset_id)
            expected = [rooftop.exclusion_reason(a, c, engine_filters) for a, c in rows]
            self.assertEqual(ours, expected, dataset_id)

    def test_confidence_only_google(self):
        self.assertIsNone(validate.filters_for(CONFIG, "ms")["min_confidence"])
        self.assertEqual(validate.filters_for(CONFIG, "google")["min_confidence"], 0.7)


class CompareTests(unittest.TestCase):
    def frame(self, area, count=3):
        return pd.DataFrame([{"dataset_id": "ms", "mpio_code": "05001", "building_count": count, "before": count,
                              "below_min_area": 0, "low_confidence": 0, "total_area_m2": area,
                              "mean_area_m2": None, "median_area_m2": None}])

    def test_identical(self):
        self.assertTrue(validate.compare_stats(self.frame(100.0), self.frame(100.0), "x")["ok"])

    def test_count_difference_fails(self):
        self.assertFalse(validate.compare_stats(self.frame(100.0), self.frame(100.0, count=4), "x")["ok"])

    def test_area_rounding_and_cross_environment(self):
        self.assertTrue(validate.compare_stats(self.frame(100.01), self.frame(100.0), "x")["ok"])
        big = 14_204_771.93
        self.assertFalse(validate.compare_stats(self.frame(big + 0.15), self.frame(big), "x")["ok"])
        self.assertTrue(validate.compare_stats(self.frame(big + 0.15), self.frame(big), "x", rel_tol=1e-6)["ok"])

    def test_missing_row_fails(self):
        other = pd.concat([self.frame(1.0), self.frame(1.0).assign(mpio_code="05002")])
        self.assertFalse(validate.compare_stats(self.frame(1.0), other, "x")["ok"])


class HelpersTests(unittest.TestCase):
    def test_spearman_is_rank_based(self):
        a = pd.Series([1, 2, 3, 4])
        self.assertAlmostEqual(validate.spearman(a, a ** 3), 1.0)
        self.assertAlmostEqual(validate.spearman(a, -a), -1.0)

    def test_winning_stages_finds_index(self):
        plan = {"queryPlanner": {"winningPlan": {"stage": "FETCH", "inputStage": {
            "stage": "IXSCAN", "indexName": "centroid_2dsphere"}}}, "executionStats": {"nReturned": 5}}
        summary = validate.execution_summary(plan)
        self.assertEqual(summary["uses_index"], ["centroid_2dsphere"])
        self.assertFalse(summary["collection_scan"])
        self.assertEqual(summary["n_returned"], 5)

    def test_aggregate_explain_uses_cursor_stage(self):
        plan = {"stages": [{"$cursor": {"queryPlanner": {"winningPlan": {"stage": "PROJECTION_DEFAULT",
                                                                       "inputStage": {"stage": "COLLSCAN"}}}}}]}
        self.assertTrue(validate.execution_summary(plan)["collection_scan"])

    def test_geodesic_area_of_small_square(self):
        from shapely.geometry import box
        # 0,0001° x 0,0001° en el ecuador ~ 11,13 m (longitud) x 11,06 m (latitud).
        self.assertAlmostEqual(validate.geodesic_area(box(0, 0, 0.0001, 0.0001)), 123.1, delta=0.1)

    def test_fingerprint_ignores_computed_at(self):
        with TemporaryDirectory() as tmp:
            a, b, c = (Path(tmp) / n for n in ("a.csv", "b.csv", "c.csv"))
            a.write_text("mpio_code,total_area_m2,computed_at\n05001,1.5,2026-11-19\n", encoding="utf-8")
            b.write_text("mpio_code,total_area_m2,computed_at\n05001,1.5,2026-11-20\n", encoding="utf-8")
            c.write_text("mpio_code,total_area_m2,computed_at\n05001,1.6,2026-11-19\n", encoding="utf-8")
            self.assertEqual(runner.content_fingerprint(a), runner.content_fingerprint(b))
            self.assertNotEqual(runner.content_fingerprint(a), runner.content_fingerprint(c))

    def test_pipeline_order(self):
        names = [name for name, _, _ in runner.steps("outputs/x", report=True, pdf=False)]
        self.assertLess(names.index("verificacion_buildings_ms"), names.index("rooftop_stats_ms"))
        self.assertLess(names.index("rooftop_stats_google"), names.index("validacion_independiente"))
        self.assertLess(names.index("validacion_independiente"), names.index("resumen_analisis"))
        self.assertNotIn("informe_pdf", names)


if __name__ == "__main__":
    unittest.main()
