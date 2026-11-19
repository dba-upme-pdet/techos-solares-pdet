"""Estadísticas de techos contra MongoDB real (prueba de integración).

Ejecuta el self-check de ``scripts/06_rooftop_stats.py``: filtros en la
agregación, mediana exacta, municipios sin edificaciones, validador de
``rooftop_stats`` e idempotencia. Crea y borra una base temporal.

Se omite si no hay ``MONGO_URI``.

Ejecutar:
    MONGO_URI=mongodb://admin:admin123@localhost:27017/ \
    .venv/bin/python -m unittest discover -s tests -p "test_rooftop_stats_mongo.py" -v
"""
import importlib.util
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URI = os.environ.get("MONGO_URI")

spec = importlib.util.spec_from_file_location("rooftop_stats", ROOT / "scripts/06_rooftop_stats.py")
stats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stats)


@unittest.skipUnless(URI, "MONGO_URI no definida")
class RooftopStatsSelfCheckTests(unittest.TestCase):
    def test_self_check_passes(self):
        self.assertEqual(stats.run_self_check(), 0)


if __name__ == "__main__":
    unittest.main()
