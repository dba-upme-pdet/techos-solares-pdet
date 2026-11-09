"""Unittest + MongoDB real. Todos los datos de integración son SINTÉTICOS.

Ejecutar: .venv/bin/python -m unittest discover -s tests -v
MongoDB es obligatorio: una conexión fallida falla las pruebas, no las omite.
"""
import copy
import importlib.util
import io
import os
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch
from uuid import uuid4

from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, OperationFailure, ServerSelectionTimeoutError

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("verify_spatial", ROOT / "scripts/02_verify_spatial.py")
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)


def square(x=-74.1, y=4.6, size=0.01):
    return {"type": "Polygon", "coordinates": [[[x, y], [x + size, y],
            [x + size, y + size], [x, y + size], [x, y]]]}


def synthetic_documents():
    """Códigos arbitrarios y cuadrados; no son municipios ni límites del DANE."""
    return [{"_id": f"{10000+i:05d}", "name": f"SINTETICO {i}", "dpto_code": "10",
             "dpto_name": "SINTETICO", "subregion_id": i % 16 + 1,
             "subregion_name": "SINTETICA", "area_km2": 1.0,
             "geometry": square(-75 + (i % 17) * 0.03, 4 + (i // 17) * 0.03),
             "source": {"dataset": "SYNTHETIC_TEST", "version": "1", "file": "fixture"},
             "loaded_at": datetime(2026, 1, 1, tzinfo=timezone.utc)} for i in range(170)]


class TestGeometry(unittest.TestCase):
    def test_valid_polygon_multipolygon_and_hole(self):
        polygon = square(size=0.1)
        polygon["coordinates"].append([[-74.08, 4.62], [-74.08, 4.64],
                                        [-74.06, 4.64], [-74.06, 4.62], [-74.08, 4.62]])
        self.assertTrue(v.valid_geometry(polygon))
        self.assertTrue(v.valid_geometry({"type": "MultiPolygon", "coordinates": [
            square()["coordinates"], square(-73)["coordinates"]]}))

    def test_invalid_structures_and_topology(self):
        invalid = [None, {}, {"type": "Point", "coordinates": [-74, 4]},
                   {"type": "Polygon", "coordinates": []},
                   {"type": "MultiPolygon", "coordinates": [[]]},
                   {"type": "Polygon", "coordinates": [[[-74, 4], [-73, 4], [-73, 5]]]},
                   {"type": "Polygon", "coordinates": [[[-74, 4], [-73, 5], [-74, 5], [-73, 4], [-74, 4]]]},
                   {"type": "Polygon", "coordinates": [[[-74, 4]] * 4]},
                   {"type": "Polygon", "coordinates": square()["coordinates"][0]},
                   {"type": "MultiPolygon", "coordinates": square()["coordinates"]}]
        hole = square()
        hole["coordinates"].append(square(-72)["coordinates"][0])
        invalid.append(hole)
        for geometry in invalid:
            with self.subTest(geometry=geometry):
                self.assertFalse(v.valid_geometry(geometry))

    def test_invalid_positions(self):
        for position in ([181, 4], [-74, 91], [4, -74], [-740000, 400000],
                         [-74, float("nan")], [float("inf"), 4], [True, 4],
                         ["-74", 4], [-74], [-74, 4, 0], None):
            geometry = square()
            geometry["coordinates"][0][1] = position
            with self.subTest(position=position):
                self.assertFalse(v.valid_geometry(geometry))

    def test_rejects_crs_override(self):
        geometry = square()
        geometry["crs"] = {"type": "name", "properties": {"name": "EPSG:3857"}}
        self.assertFalse(v.valid_geometry(geometry))


class TestReferenceAndPlan(unittest.TestCase):
    def test_official_reference(self):
        codes, info = v.load_reference()
        self.assertEqual(len(codes), 170)
        self.assertIn("05031", codes)
        self.assertEqual(len(info["sha256"]), 64)

    def test_reference_rejects_duplicates_bad_codes_and_count(self):
        for codes in ([5031] * 170, list(range(169)), ["invalid"] + list(range(169))):
            with self.subTest(codes=codes[:2]), patch.object(v.pd, "read_excel", return_value={
                    v.CONFIG["sources"]["pdet_list"]["code_column"]: codes}):
                with self.assertRaises(v.ContractError):
                    v.load_reference()

    def test_winning_plan_classic_and_sbe(self):
        scan = {"stage": "IXSCAN", "indexName": "geometry_2dsphere"}
        for plan in (scan, {"stage": "FETCH", "inputStage": scan},
                     {"queryPlan": {"stage": "FETCH", "inputStage": scan}},
                     {"shards": [{"winningPlan": scan}]}):
            self.assertTrue(v.uses_spatial_index(plan, ["geometry_2dsphere"]))
        self.assertFalse(v.uses_spatial_index({"stage": "COLLSCAN"}, ["geometry_2dsphere"]))
        self.assertFalse(v.uses_spatial_index({"indexName": "geometry_2dsphere"}, ["geometry_2dsphere"]))

    def test_rejected_plan_cannot_pass(self):
        explanation = {"queryPlanner": {"winningPlan": {"stage": "COLLSCAN"},
                       "rejectedPlans": [{"stage": "IXSCAN", "indexName": "geometry_2dsphere"}]}}
        self.assertFalse(v.uses_spatial_index(explanation["queryPlanner"]["winningPlan"], ["geometry_2dsphere"]))

    def test_duplicate_identifiers(self):
        coll = MagicMock()
        docs = synthetic_documents()
        docs[1]["_id"] = docs[0]["_id"]
        cursor = MagicMock()
        cursor.sort.return_value = docs
        coll.find.side_effect = [cursor, []]
        coll.index_information.return_value = {}
        with redirect_stdout(io.StringIO()):
            report = v.verify_report(coll, reference_codes={doc["_id"] for doc in docs})
        self.assertEqual(report["checks"]["divipola"]["status"], "FALLA")

    def test_cli_exit_codes(self):
        for success, code in ((True, 0), (False, 1)):
            with patch.object(v, "MongoClient"), patch.object(v, "verify_report", return_value={"success": success}):
                self.assertEqual(v.main([]), code)
        with patch.object(v, "MongoClient", side_effect=ServerSelectionTimeoutError("fixture")), redirect_stdout(io.StringIO()):
            self.assertEqual(v.main([]), 2)

    def test_cli_missing_and_invalid_reference_and_json(self):
        for error, status in ((FileNotFoundError(), "PENDIENTE"), (v.ContractError("bad reference"), "FALLA")):
            with TemporaryDirectory() as tmp, patch.object(v, "load_reference", side_effect=error), \
                    patch.object(v, "MongoClient"), patch.object(v, "verify_report", return_value={"success": False}) as verify:
                path = Path(tmp) / "report.json"
                self.assertEqual(v.main(["--report", str(path)]), 1)
                self.assertEqual(verify.call_args.kwargs["reference_status"], status)
                self.assertTrue(path.is_file())


class TestMongoIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = MongoClient(os.environ.get("MONGO_URI", v.CONFIG["mongo"]["uri"]),
                                 serverSelectionTimeoutMS=5000)
        cls.client.admin.command("ping")

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def setUp(self):
        # Nunca reutilizar, vaciar ni borrar un recurso preexistente.
        self.db_name = "spatial_verify_test_" + uuid4().hex
        self.assertNotIn(self.db_name, self.client.list_database_names())
        self.db = self.client[self.db_name]
        self.addCleanup(self.client.drop_database, self.db_name)
        self.collection = self.db.create_collection("municipalities", validator={"$jsonSchema": v.MUNICIPALITY_SCHEMA})
        self.collection.create_index([("geometry", "2dsphere")])
        self.docs = synthetic_documents()
        self.codes = {doc["_id"] for doc in self.docs}
        self.collection.insert_many(self.docs)

    def run_verifier(self, **kwargs):
        with redirect_stdout(io.StringIO()):
            return v.verify_report(self.collection, reference_codes=kwargs.pop("reference_codes", self.codes), **kwargs)

    def test_accepts_170_synthetic_documents_and_real_explain(self):
        report = self.run_verifier(reference_info={"synthetic": True})
        self.assertTrue(report["success"], report)
        query = report["checks"]["query"]
        self.assertEqual(query["actual_ids"], [self.docs[0]["_id"]])
        self.assertEqual(query["negative_matches"], 0)
        explain = report["checks"]["explain"]
        self.assertTrue(v.uses_spatial_index(explain["winning_plan"], ["geometry_2dsphere"]))
        self.assertGreater(explain["execution_stats"]["totalKeysExamined"], 0)
        if os.environ.get("SPATIAL_TEST_REPORT"):
            report["synthetic"] = True
            report["mongodb_version"] = self.client.server_info()["version"]
            v.write_json(Path(os.environ["SPATIAL_TEST_REPORT"]), report)

    def test_incorrect_counts(self):
        self.collection.delete_one({"_id": self.docs[-1]["_id"]})
        self.assertEqual(self.run_verifier()["checks"]["count"]["status"], "FALLA")
        extra = copy.deepcopy(self.docs[-1])
        self.collection.insert_one(extra)
        extra["_id"] = "10999"
        self.collection.insert_one(extra)
        self.assertEqual(self.run_verifier()["checks"]["count"]["status"], "FALLA")
        self.collection.delete_many({})
        report = self.run_verifier()
        self.assertFalse(report["success"])
        self.assertEqual(report["checks"]["query"]["status"], "PENDIENTE")

    def test_wrong_codes_with_correct_count(self):
        official, _ = v.load_reference()
        report = self.run_verifier(reference_codes=official)
        self.assertEqual(report["checks"]["count"]["status"], "OK")
        self.assertEqual(report["checks"]["official_codes"]["status"], "FALLA")

    def test_invalid_identifiers_and_mongo_uniqueness(self):
        with self.assertRaises(DuplicateKeyError):
            self.collection.insert_one(self.docs[0])
        for identifier in ("5031", "ABCDE", "１２３４５", 10000):
            with self.subTest(identifier=identifier):
                self.collection.delete_one({"_id": self.docs[0]["_id"]})
                document = copy.deepcopy(self.docs[0])
                document["_id"] = identifier
                self.collection.insert_one(document, bypass_document_validation=True)
                self.assertEqual(self.run_verifier()["checks"]["divipola"]["status"], "FALLA")
                self.collection.delete_one({"_id": identifier})
                self.collection.insert_one(self.docs[0])

    def test_schema_and_contract_errors(self):
        for field, value in (("loaded_at", "2026-01-01"), ("dpto_code", "99"),
                             ("subregion_id", True), ("area_km2", float("nan")),
                             ("source", {}), ("name", "")):
            with self.subTest(field=field):
                self.collection.update_one({"_id": self.docs[0]["_id"]}, {"$set": {field: value}},
                                           bypass_document_validation=True)
                self.assertEqual(self.run_verifier()["checks"]["schema"]["status"], "FALLA")
                self.collection.replace_one({"_id": self.docs[0]["_id"]}, self.docs[0])
        self.collection.update_one({"_id": self.docs[0]["_id"]}, {"$unset": {"loaded_at": ""}},
                                   bypass_document_validation=True)
        self.assertEqual(self.run_verifier()["checks"]["schema"]["status"], "FALLA")

    def test_invalid_geometry_without_index(self):
        self.collection.drop_index("geometry_2dsphere")
        geometry = square()
        geometry["coordinates"][0].pop()
        self.collection.update_one({"_id": self.docs[0]["_id"]}, {"$set": {"geometry": geometry}})
        report = self.run_verifier()
        self.assertEqual(report["checks"]["geometry"]["status"], "FALLA")
        self.assertEqual(report["checks"]["query"]["status"], "PENDIENTE")

    def test_missing_index_real_collection_scan(self):
        self.collection.drop_index("geometry_2dsphere")
        report = self.run_verifier()
        self.assertFalse(report["success"])
        self.assertEqual(report["checks"]["index"]["status"], "FALLA")
        self.assertEqual(report["checks"]["query"]["status"], "OK")
        self.assertEqual(report["checks"]["explain"]["status"], "FALLA")
        self.assertIn("COLLSCAN", str(report["checks"]["explain"]["winning_plan"]))

    def test_multipolygon_hole_and_overlapping_results(self):
        geometry = square(size=0.02)
        geometry["coordinates"].append(square(-74.095, 4.605, 0.003)["coordinates"][0])
        multi = {"type": "MultiPolygon", "coordinates": [geometry["coordinates"], square(-73)["coordinates"]]}
        self.collection.update_one({"_id": self.docs[0]["_id"]}, {"$set": {"geometry": multi}})
        self.collection.update_one({"_id": self.docs[1]["_id"]}, {"$set": {"geometry": multi}})
        report = self.run_verifier()
        self.assertTrue(report["success"], report)
        self.assertEqual(len(report["checks"]["query"]["actual_ids"]), 2)
        for point, expected in (([-74.094, 4.606], []), ([-72.995, 4.605], ["10000", "10001"])):
            result = list(self.collection.find({"geometry": {"$geoIntersects": {"$geometry": {
                "type": "Point", "coordinates": point}}}}, {"_id": 1}))
            self.assertEqual(sorted(doc["_id"] for doc in result), expected)

    def test_schema_enforced_by_real_mongo(self):
        bad = copy.deepcopy(self.docs[0])
        bad["_id"] = "10999"
        bad.pop("loaded_at")
        with self.assertRaises(OperationFailure) as error:
            self.collection.insert_one(bad)
        self.assertEqual(error.exception.code, 121)

    def test_pending_reference_prevents_success(self):
        report = self.run_verifier(reference_codes=None, reference_status="PENDIENTE")
        self.assertFalse(report["success"])
        self.assertEqual(report["checks"]["official_codes"]["status"], "PENDIENTE")

    def test_incorrect_query_results_are_rejected(self):
        original_find = self.collection.find

        def corrupted_find(query, *args, **kwargs):
            if "$geoIntersects" in query.get("geometry", {}):
                return []
            return original_find(query, *args, **kwargs)

        with patch.object(self.collection, "find", side_effect=corrupted_find):
            report = self.run_verifier()
        self.assertFalse(report["success"])
        self.assertEqual(report["checks"]["query"]["status"], "FALLA")

    def test_spatial_rejected_plan_and_zero_keys_cannot_pass(self):
        for plan, keys in (({"stage": "COLLSCAN"}, 1),
                           ({"stage": "IXSCAN", "indexName": "geometry_2dsphere"}, 0)):
            explanation = {"queryPlanner": {"winningPlan": plan, "rejectedPlans": [
                {"stage": "IXSCAN", "indexName": "geometry_2dsphere"}]},
                "executionStats": {"executionSuccess": True, "nReturned": 1, "totalKeysExamined": keys}}
            with self.subTest(plan=plan, keys=keys), patch.object(
                    self.collection.database, "command", return_value=explanation):
                report = self.run_verifier()
            self.assertFalse(report["success"])
            self.assertEqual(report["checks"]["query"]["status"], "OK")
            self.assertEqual(report["checks"]["explain"]["status"], "FALLA")


if __name__ == "__main__":
    unittest.main()
