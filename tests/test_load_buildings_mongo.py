"""Carga de buildings contra MongoDB real (pruebas de integración).

Ejecuta el self-check de ``scripts/04_load_buildings.py``: validador, ``_id``
determinista, idempotencia, ``ingestion_runs``, ``datasets`` e índice
``centroid_2dsphere``. Crea y borra una base temporal.

Se omite si no hay ``MONGO_URI``.

Ejecutar:
    MONGO_URI=mongodb://admin:admin123@localhost:27017/ \
    .venv/bin/python -m unittest discover -s tests -p "test_load_buildings_mongo.py" -v
"""
import importlib.util
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

URI = os.environ.get("MONGO_URI")

spec = importlib.util.spec_from_file_location("load_buildings", ROOT / "scripts/04_load_buildings.py")
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)


@unittest.skipUnless(URI, "MONGO_URI no definida")
class LoadSelfCheckTests(unittest.TestCase):
    def test_self_check_passes(self):
        self.assertEqual(loader.run_self_check(), 0)


if __name__ == "__main__":
    unittest.main()
