"""Pruebas de scripts/05_eda_buildings.py con datos SINTÉTICOS; no usan red ni MongoDB.

Ejecutar: .venv/bin/python -m unittest discover -s tests -p "test_eda_buildings.py" -v
"""
import csv
import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("eda_buildings", ROOT / "scripts/05_eda_buildings.py")
eda = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eda)

MUNICIPIOS = [("05001", "A", "SUB UNO"), ("05002", "B", "SUB UNO"), ("05003", "C", "SUB DOS")]


def _csv(path: Path, header: list[str], rows: list[list]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def _area(total: float, p50: float) -> dict:
    return {"sum": total, "p01": 1, "p10": 2, "p50": p50, "p90": 9, "p99": 10, "max": 11, "min": 1, "count": 1}


def make_root(tmp: Path, ms_counts, google_counts, google_prepared=None) -> Path:
    config = {"sources": {}}
    for key, dataset_id, counts, prepared in (("microsoft", "ms", ms_counts, None),
                                              ("google", "google", google_counts, google_prepared)):
        csv_path = f"outputs/buildings_{dataset_id}_prepared_by_municipality.csv"
        report_path = f"outputs/buildings_{dataset_id}_prepare_report.json"
        config["sources"][key] = {"id": dataset_id, "prepare_report": report_path,
                                  "prepare_by_municipality": csv_path}
        _csv(tmp / csv_path, ["mpio_code", "name", "prepared_buildings", "area_m2_sum", "area_m2_median"],
             [[code, name, n, n * 10.0 if n else "", 10.0 if n else ""]
              for (code, name, _), n in zip(MUNICIPIOS, counts)])
        total = sum(counts) if prepared is None else prepared
        (tmp / report_path).write_text(json.dumps({"totals": {
            "read": total + 5, "excluded_outside_pdet": 5, "rejected": 0, "repaired": 0,
            "prepared": total, "area_m2": _area(total * 10.0, 10.0)}}), encoding="utf-8")
    _csv(tmp / "outputs/pdet_mgn_crosswalk.csv", ["mpio_code", "subregion_name"],
         [[code, sub] for code, _, sub in MUNICIPIOS])
    (tmp / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    return tmp


class EdaBuildingsTests(unittest.TestCase):
    def test_summary_compares_sources_and_lists_missing_municipalities(self):
        with TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), [10, 20, 30], [15, 0, 60])
            self.assertEqual(eda.main(root), 0)
            summary = json.loads((root / eda.SUMMARY).read_text(encoding="utf-8"))
            self.assertEqual(summary["sources"]["ms"]["prepared"], 60)
            self.assertEqual(summary["sources"]["google"]["municipalities_without_buildings"], ["05002"])
            self.assertEqual(summary["comparison"]["municipalities_in_both"], 2)
            self.assertEqual(summary["comparison"]["municipalities_google_more_buildings"], 2)
            self.assertEqual(summary["by_subregion"]["SUB UNO"]["ms_buildings"], 30)
            for name in ("eda_conteo_ms_vs_google.png", "eda_area_por_subregion.png"):
                self.assertTrue((root / eda.FIGURES / name).stat().st_size > 0)

    def test_rejects_csv_that_does_not_match_the_prepare_report(self):
        with TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), [10, 20, 30], [15, 0, 60], google_prepared=999)
            with self.assertRaisesRegex(ValueError, "google"):
                eda.main(root)


if __name__ == "__main__":
    unittest.main()
