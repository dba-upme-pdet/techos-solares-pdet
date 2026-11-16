"""Pruebas de scripts/04_load_buildings.py sin MongoDB ni red.

Datos SINTÉTICOS. La carga contra MongoDB se prueba en
``test_load_buildings_mongo.py`` (o con ``04_load_buildings.py --self-check``).

Ejecutar:
    .venv/bin/python -m unittest discover -s tests -p "test_load_buildings.py" -v
"""
import gzip
import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import entrega3_contracts as c3  # noqa: E402

spec = importlib.util.spec_from_file_location("load_buildings", ROOT / "scripts/04_load_buildings.py")
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)

MUNI = "05001"


def record(ref: str, *, code: str | None = MUNI, area: float = 12100.0) -> dict:
    ring = [[-75.6, 6.2], [-75.599, 6.2], [-75.599, 6.201], [-75.6, 6.201], [-75.6, 6.2]]
    return {
        "dataset_id": "ms",
        "source_ref": ref,
        "footprint": {"type": "Polygon", "coordinates": [ring]},
        "centroid": {"type": "Point", "coordinates": [-75.5995, 6.2005]},
        "area_m2": area,
        "area_src_m2": None,
        "confidence": None,
        "height_m": None,
        "mpio_code": code,
    }


PREPARE = {
    "contract": c3.CONTRACT_VERSION,
    "dataset_id": "ms",
    "status": "ready_for_load",
    "claims_pdet_selection": True,
    "claims_full_source": True,
    "totals": {"balanced": True, "prepared": 2},
    "partitions": [{"partition_id": "111"}],
}


class ReportGateTests(unittest.TestCase):
    def test_ready_report_passes_and_declares_totals(self):
        gate = loader.check_prepare_report(PREPARE, "ms")
        self.assertEqual(gate["prepared_total"], 2)
        self.assertEqual(gate["partitions"], 1)

    def test_wrong_dataset_is_rejected(self):
        with self.assertRaises(loader.LoadError):
            loader.check_prepare_report({**PREPARE, "dataset_id": "google"}, "ms")

    def test_sample_or_source_pass_never_loads(self):
        for status in ("sample_only", "source_pass_only", "failed"):
            with self.subTest(status=status), self.assertRaises(loader.LoadError):
                loader.check_prepare_report({**PREPARE, "status": status}, "ms")

    def test_report_without_pdet_selection_is_rejected(self):
        with self.assertRaises(loader.LoadError):
            loader.check_prepare_report({**PREPARE, "claims_pdet_selection": False}, "ms")

    def test_report_with_unbalanced_rows_is_rejected(self):
        with self.assertRaises(loader.LoadError):
            loader.check_prepare_report({**PREPARE, "totals": {"balanced": False, "prepared": 2}}, "ms")


class IdentityTests(unittest.TestCase):
    def test_id_is_deterministic(self):
        first = loader.building_id("ms", "032212332/part-a.csv.gz:7")
        self.assertEqual(first, loader.building_id("ms", "032212332/part-a.csv.gz:7"))
        self.assertTrue(first.startswith("ms:"))
        self.assertEqual(len(first.split(":")[1]), 24)

    def test_id_changes_with_dataset_and_reference(self):
        base = loader.building_id("ms", "ref")
        self.assertNotEqual(base, loader.building_id("google", "ref"))
        self.assertNotEqual(base, loader.building_id("ms", "ref2"))

    def test_many_references_do_not_collide(self):
        ids = {loader.building_id("ms", f"032212332/part-{i // 10000}.csv.gz:{i}") for i in range(200_000)}
        self.assertEqual(len(ids), 200_000)


class PreparedDocumentTests(unittest.TestCase):
    def test_valid_record_passes_as_is(self):
        doc, reason, detail = loader.prepared_document(json.dumps(record("a:1")), "ms")
        self.assertIsNotNone(doc)
        self.assertEqual((reason, detail), ("", ""))
        self.assertNotIn("_id", doc)
        self.assertNotIn("run_id", doc)

    def test_invalid_json_is_rejected(self):
        doc, reason, _ = loader.prepared_document("{no es json", "ms")
        self.assertIsNone(doc)
        self.assertEqual(reason, "json_invalid")

    def test_dataset_mismatch_is_rejected(self):
        doc, reason, _ = loader.prepared_document(json.dumps(record("a:1")), "google")
        self.assertIsNone(doc)
        self.assertEqual(reason, "dataset_mismatch")

    def test_contract_violation_is_rejected(self):
        bad = {**record("a:1"), "area_m2": -1}
        doc, reason, detail = loader.prepared_document(json.dumps(bad), "ms")
        self.assertIsNone(doc)
        self.assertEqual(reason, "contract_violation")
        self.assertIn("area_m2", detail)

    def test_record_already_carrying_id_is_rejected(self):
        doc, reason, _ = loader.prepared_document(json.dumps({**record("a:1"), "_id": "x"}), "ms")
        self.assertIsNone(doc)
        self.assertEqual(reason, "id_from_prepare")

    def test_missing_source_ref_is_rejected(self):
        bad = {k: v for k, v in record("a:1").items() if k != "source_ref"}
        doc, reason, _ = loader.prepared_document(json.dumps(bad), "ms")
        self.assertIsNone(doc)
        self.assertEqual(reason, "missing_source_ref")


class PartitionEntryTests(unittest.TestCase):
    def write_partition(self, root: Path, name: str, lines: list[str]) -> dict:
        path = root / "data" / "processed" / "buildings" / "ms" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        return {
            "partition_id": name.split("-")[1].split(".")[0],
            "output": {"path": path.relative_to(root).as_posix(),
                       "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                       "bytes": path.stat().st_size, "records": len(lines)},
            "input": {"local_path": f"data/raw/{name}"},
            "excluded_outside_pdet": 4,
            "rejected": 1,
        }

    def test_entries_are_verified_and_selected(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = {**PREPARE, "partitions": [self.write_partition(root, "part-111.jsonl.gz", ["{}"]),
                                                self.write_partition(root, "part-222.jsonl.gz", ["{}"])]}
            entries = loader.partition_entries(report, root, {"222"})
            self.assertEqual([entry["partition_id"] for entry in entries], ["222"])
            self.assertEqual(entries[0]["source_file"], "data/raw/part-222.jsonl.gz")
            self.assertEqual(entries[0]["excluded_outside_pdet"], 4)

    def test_changed_bytes_stop_the_load(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            part = self.write_partition(root, "part-111.jsonl.gz", ["{}"])
            part["output"]["bytes"] += 1
            with self.assertRaises(loader.LoadError):
                loader.partition_entries({**PREPARE, "partitions": [part]}, root, None)

    def test_changed_sha_stops_the_load(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            part = self.write_partition(root, "part-111.jsonl.gz", ["{}"])
            part["output"]["sha256"] = "0" * 64
            with self.assertRaises(loader.LoadError):
                loader.partition_entries({**PREPARE, "partitions": [part]}, root, None)

    def test_missing_partition_stops_the_load(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            part = self.write_partition(root, "part-111.jsonl.gz", ["{}"])
            with self.assertRaises(loader.LoadError):
                loader.partition_entries({**PREPARE, "partitions": [part]}, root, {"999"})


class BatchTests(unittest.TestCase):
    def test_batches_keep_order_and_bounded_size(self):
        self.assertEqual(list(loader.batches(range(7), 3)), [[0, 1, 2], [3, 4, 5], [6]])
        self.assertEqual(list(loader.batches([], 3)), [])

    def test_iter_prepared_skips_blank_lines(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "part.jsonl.gz"
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                handle.write('{"a": 1}\n\n{"b": 2}\n')
            self.assertEqual(list(loader.iter_prepared(path)), [(1, '{"a": 1}\n'), (3, '{"b": 2}\n')])


if __name__ == "__main__":
    unittest.main()
