"""Contrato entre 03_prepare_buildings.py y la colección buildings de MongoDB.

Prueba que un registro preparado, con el run_id que agrega la carga, pasa el
validador $jsonSchema de 00_init_db.py, que sin run_id lo rechaza, y que
$geoWithin sobre buildings.centroid (índice 2dsphere) devuelve el mismo
municipio que asignó la preparación.

Usa una base temporal y la borra al terminar. Se omite si no hay MONGO_URI.
Con REAL_PREPARED_PART=<ruta o patrón glob de part-*.jsonl.gz> también inserta esas
particiones reales completas en una colección con el mismo validador.

Ejecutar:
    MONGO_URI=mongodb://admin:admin123@localhost:27017/ \
    .venv/bin/python -m unittest discover -s tests -p "test_prepare_buildings_mongo.py" -v
"""
import gzip
import importlib.util
import json
import os
import sys
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

URI = os.environ.get("MONGO_URI")

if URI:
    from bson import ObjectId
    from pymongo import GEOSPHERE, InsertOne, MongoClient
    from pymongo.errors import BulkWriteError, WriteError

    spec = importlib.util.spec_from_file_location("init_db", ROOT / "scripts/00_init_db.py")
    init_db = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(init_db)


def winning_stages(plan: dict) -> list[str]:
    stages, node = [], plan
    while node:
        stages.append(node.get("stage"))
        node = node.get("inputStage")
    return stages


@unittest.skipUnless(URI, "MONGO_URI no definida")
class MongoContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = MongoClient(URI, serverSelectionTimeoutMS=5000)
        cls.client.admin.command("ping")
        cls.db = cls.client[f"upme_pdet_test_e3_{uuid.uuid4().hex[:8]}"]
        schema = {"$jsonSchema": {"bsonType": "object", **init_db.SCHEMAS["buildings"]}}
        # strict + error: más exigente que el moderate de 00_init_db.py, para que nada pase de largo.
        cls.db.create_collection("buildings", validator=schema, validationLevel="strict", validationAction="error")

    @classmethod
    def tearDownClass(cls):
        cls.client.drop_database(cls.db.name)
        cls.client.close()

    def test_prepared_records_pass_validator_and_match_geowithin(self):
        import test_prepare_buildings as t

        with TemporaryDirectory() as tmp:
            ws = t.Workspace(Path(tmp))
            self.assertEqual(ws.run(), 0)
            records = ws.records(ws.report())
        coll = self.db["buildings"]
        with self.assertRaises(WriteError):
            coll.insert_one(dict(records[0]))  # sin run_id: el validador lo rechaza
        run_id = ObjectId()
        result = coll.insert_many([dict(r, run_id=run_id) for r in records], ordered=False)
        self.assertEqual(len(result.inserted_ids), len(records))
        coll.create_index([("centroid", GEOSPHERE)], name="centroid_2dsphere")

        multi = 0
        for muni in (t.MUNI_A, t.MUNI_B):
            ids = {d["source_ref"] for d in coll.find({"centroid": {"$geoWithin": {"$geometry": muni["geometry"]}}},
                                                       {"source_ref": 1})}
            expected = {r["source_ref"] for r in records if r["mpio_code"] == muni["code"]}
            # Cada edificación asignada a este municipio la devuelve $geoWithin.
            self.assertTrue(expected <= ids, (muni["code"], expected - ids))
            multi += len(ids - expected)
        # Lo que $geoWithin devuelve de más solo puede ser el centroide sobre el borde compartido.
        self.assertLessEqual(multi, 1)
        plan = coll.find({"centroid": {"$geoWithin": {"$geometry": t.MUNI_A["geometry"]}}}).explain()
        self.assertIn("IXSCAN", winning_stages(plan["queryPlanner"]["winningPlan"]))

    @unittest.skipUnless(os.environ.get("REAL_PREPARED_PART"), "REAL_PREPARED_PART no definida")
    def test_real_partition_loads_without_validator_rejections(self):
        import glob

        pattern = os.environ["REAL_PREPARED_PART"]
        paths = [Path(p) for p in sorted(glob.glob(pattern))]
        self.assertTrue(paths, f"ningún archivo coincide con {pattern}")
        coll = self.db["buildings_real"]
        schema = {"$jsonSchema": {"bsonType": "object", **init_db.SCHEMAS["buildings"]}}
        self.db.create_collection("buildings_real", validator=schema, validationLevel="strict",
                                  validationAction="error")
        run_id, lines, inserted, batch = ObjectId(), 0, 0, []
        try:
            for path in paths:
                with gzip.open(path, "rt", encoding="utf-8") as handle:
                    for line in handle:
                        lines += 1
                        batch.append(InsertOne(dict(json.loads(line), run_id=run_id)))
                        if len(batch) == 10_000:
                            inserted += coll.bulk_write(batch, ordered=False).inserted_count
                            batch = []
            if batch:
                inserted += coll.bulk_write(batch, ordered=False).inserted_count
        except BulkWriteError as exc:
            self.fail(f"el validador rechazó {len(exc.details['writeErrors'])} registros: "
                      f"{exc.details['writeErrors'][0]}")
        self.assertEqual(inserted, lines)
        coll.create_index([("centroid", GEOSPHERE)], name="centroid_2dsphere")
        doc = coll.find_one()
        box = {"type": "Polygon", "coordinates": [[[doc["centroid"]["coordinates"][0] - 0.01, doc["centroid"]["coordinates"][1] - 0.01],
                                                   [doc["centroid"]["coordinates"][0] + 0.01, doc["centroid"]["coordinates"][1] - 0.01],
                                                   [doc["centroid"]["coordinates"][0] + 0.01, doc["centroid"]["coordinates"][1] + 0.01],
                                                   [doc["centroid"]["coordinates"][0] - 0.01, doc["centroid"]["coordinates"][1] + 0.01],
                                                   [doc["centroid"]["coordinates"][0] - 0.01, doc["centroid"]["coordinates"][1] - 0.01]]]}
        query = {"centroid": {"$geoWithin": {"$geometry": box}}}
        plan = coll.find(query).explain()
        stages = winning_stages(plan["queryPlanner"]["winningPlan"])
        self.assertIn("IXSCAN", stages)
        print(f"\n[real] {len(paths)} archivos: {lines} líneas, {inserted} insertadas con validador strict, "
              f"0 rechazos; $geoWithin de prueba: {coll.count_documents(query)} documentos, plan {' -> '.join(stages)}")


if __name__ == "__main__":
    unittest.main()
