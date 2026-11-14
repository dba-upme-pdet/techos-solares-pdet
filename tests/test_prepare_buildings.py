"""Pruebas de scripts/03_prepare_buildings.py y entrega3_contracts.py.

Datos SINTÉTICOS; no usan red ni MongoDB.
Ejecutar: .venv/bin/python -m unittest discover -s tests -p "test_prepare_buildings.py" -v
"""
import argparse
import csv
import gzip
import hashlib
import importlib.util
import json
import shutil
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from pyproj import Transformer
from shapely.geometry import Polygon, box, mapping
import numpy as np
import shapely

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import entrega3_contracts as c3  # noqa: E402
from entrega2_contracts import ContractError  # noqa: E402

spec = importlib.util.spec_from_file_location("prepare_buildings", ROOT / "scripts/03_prepare_buildings.py")
prep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prep)

# Dos municipios sintéticos que comparten el borde lon = -74.0.
MUNI_A = {"code": "05031", "name": "A", "geometry": mapping(box(-74.10, 4.00, -74.00, 4.10))}
MUNI_B = {"code": "05040", "name": "B", "geometry": mapping(box(-74.00, 4.00, -73.90, 4.10))}


def square(x, y, size=0.0002):
    return [[x, y], [x + size, y], [x + size, y + size], [x, y + size], [x, y]]


def feature(coords, height=-1.0, confidence=-1.0, gtype="Polygon"):
    return {"type": "Feature", "properties": {"height": height, "confidence": confidence},
            "geometry": {"type": gtype, "coordinates": coords}}


def write_partition(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for line in lines:
            handle.write((line if isinstance(line, str) else json.dumps(line)) + "\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_for(parts):
    return {
        "status": "complete",
        "claims_pdet_coverage": True,
        "source": {"dataset_id": "ms"},
        "datasets_document": {"_id": "ms", "name": "MS", "version": "2026-02-03", "license": "ODbL-1.0",
                              "url": "https://example.invalid/index.csv", "accessed_at": "2026-11-13T00:00:00+00:00"},
        "partitions": parts,
    }


class Workspace:
    """Raíz temporal con config.yaml, capa PDET y dos particiones sintéticas."""

    def __init__(self, tmp: Path, *, with_pdet=True):
        self.root = tmp
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        cfg["sources"]["pdet_list"]["expected_municipalities"] = 2
        (tmp / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
        self.cfg = cfg
        if with_pdet:
            geojsonl = tmp / cfg["processing"]["buildings"]["pdet_input"]
            geojsonl.parent.mkdir(parents=True, exist_ok=True)
            geojsonl.write_text("".join(json.dumps({"_id": m["code"], "name": m["name"], "geometry": m["geometry"]}) + "\n"
                                        for m in (MUNI_A, MUNI_B)), encoding="utf-8")
            report = tmp / cfg["processing"]["buildings"]["pdet_input_report"]
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps({"status": "ready_for_load",
                                          "sha256": hashlib.sha256(geojsonl.read_bytes()).hexdigest()}))
        bowtie = [[-74.05, 4.05], [-74.0498, 4.0502], [-74.0498, 4.05], [-74.05, 4.0502], [-74.05, 4.05]]
        # Polígono con una espina de área casi nula: make_valid deja el cuadro y una astilla.
        spike = [[-74.06, 4.06], [-74.0598, 4.06], [-74.0598, 4.0602], [-74.0599, 4.0602],
                 [-74.0599, 4.0606], [-74.05989999, 4.0602], [-74.06, 4.0602], [-74.06, 4.06]]
        self.lines_a = [
            feature([square(-74.05, 4.05)], confidence=0.9),            # 1 dentro de A
            feature([square(-73.95, 4.05)], height=7.5),                 # 2 dentro de B
            feature([square(-75.00, 4.05)]),                             # 3 fuera de PDET
            "{esto no es json",                                          # 4 json_invalid
            feature([bowtie]),                                           # 5 repair_split_multipolygon
            feature([[[4.05, -74.05], [4.0502, -74.05], [4.0502, -74.0498], [4.05, -74.05]]]),  # 6 ejes invertidos
            feature([square(-74.03, 4.03)], gtype="MultiPolygon"),       # 7 tipo no soportado
            feature([spike]),                                            # 8 reparada (astilla)
            feature([[[-74.0, 4.02], [-73.9999, 4.02], [-73.9999, 4.0201], [-74.0, 4.0201], [-74.0, 4.02]]]),
            # 9: centroide en lon -73.99995, dentro de B
            feature([square(-74.000244140625, 4.0625, 0.00048828125)]),  # 10 centroide exacto en lon -74: A (menor)
            feature([[[-74.04, 4.04], [-74.04, 4.04]]]),                 # 11 anillo de 2 puntos
        ]
        self.lines_b = [
            feature([square(-74.05, 4.05)], confidence=0.9),             # duplicado de la línea 1
            feature([square(-74.08, 4.08)], confidence=1.5),             # dentro de A, confidence fuera de rango
        ]
        parts = []
        for qk, lines in (("000000001", self.lines_a), ("000000002", self.lines_b)):
            rel = f"data/raw/ms_buildings/test/quadkey={qk}/part-{qk}.csv.gz"
            digest = write_partition(tmp / rel, lines)
            parts.append({"quadkey": qk, "status": "ok", "local_path": rel, "url": f"https://example.invalid/{qk}",
                          "download": {"sha256": digest}})
        self.manifest = manifest_for(parts)
        manifest_path = tmp / cfg["sources"]["microsoft"]["manifest"]
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def run(self, **kw):
        args = argparse.Namespace(source="ms", workers=1, partitions=None, without_pdet_selection=False,
                                  check_records=True)
        for k, v in kw.items():
            setattr(args, k, v)
        return prep.run(self.root, args)

    def report(self, key="prepare_report"):
        return json.loads((self.root / self.cfg["sources"]["microsoft"][key]).read_text(encoding="utf-8"))

    def records(self, report):
        out = []
        for part in report["partitions"]:
            with gzip.open(self.root / part["output"]["path"], "rt", encoding="utf-8") as handle:
                out.extend(json.loads(line) for line in handle)
        return out


class ManifestContractTests(unittest.TestCase):
    def test_real_microsoft_manifest_passes(self):
        manifest = json.loads((ROOT / "outputs/ms_buildings_download_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(c3.download_manifest_problems(manifest, "ms"), [])

    def test_broken_manifests(self):
        base = manifest_for([{"quadkey": "1", "status": "ok", "local_path": "x", "download": {"sha256": "a"}}])
        cases = {
            "status": dict(base, status="blocked"),
            "claims_pdet_coverage": dict(base, claims_pdet_coverage=False),
            "_id": dict(base, datasets_document=dict(base["datasets_document"], _id="google")),
            "sha256": dict(base, partitions=[{"quadkey": "1", "status": "ok", "local_path": "x", "download": {}}]),
            "repetida": dict(base, partitions=base["partitions"] * 2),
            "partition_id": dict(base, partitions=[{"status": "ok", "local_path": "x", "download": {"sha256": "a"}}]),
        }
        for needle, manifest in cases.items():
            with self.subTest(needle):
                problems = c3.download_manifest_problems(manifest, "ms")
                self.assertTrue(any(needle in p for p in problems), problems)

    def test_partition_id_prefers_contract_key(self):
        self.assertEqual(c3.partition_id({"partition_id": "89a4", "quadkey": "0"}), "89a4")
        self.assertEqual(c3.partition_id({"quadkey": "032212332"}), "032212332")


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.sel = c3.PdetSelector([MUNI_B, MUNI_A])  # orden de entrada no importa

    def test_inside_outside_and_shared_border(self):
        import numpy as np
        codes, multi = self.sel.assign(np.array([-74.05, -73.95, -75.0, -74.0]), np.array([4.05, 4.05, 4.05, 4.05]))
        self.assertEqual(codes, ["05031", "05040", None, "05031"])
        self.assertEqual(multi, 1)

    def test_boundary_point_counts_as_inside(self):
        import numpy as np
        codes, _ = self.sel.assign(np.array([-74.10]), np.array([4.05]))
        self.assertEqual(codes, ["05031"])


class GeometryTests(unittest.TestCase):
    def test_geodesic_area_matches_equal_area_projection(self):
        poly = box(-74.0, 4.0, -73.999, 4.001)
        to_ea = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True).transform
        projected = shapely.transform(poly, lambda xy: np.column_stack(to_ea(xy[:, 0], xy[:, 1]))).area
        self.assertAlmostEqual(c3.geodesic_area_m2(poly) / projected, 1.0, places=3)

    def test_area_is_positive_for_clockwise_ring(self):
        cw = Polygon([(0, 0), (0, 0.001), (0.001, 0.001), (0.001, 0), (0, 0)])
        self.assertGreater(c3.geodesic_area_m2(cw), 0)

    def test_repair_rules(self):
        bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
        self.assertEqual(c3.repair_polygon(bowtie, 0.01), (None, "repair_split_multipolygon"))
        spike = Polygon([(0, 0), (2, 0), (2, 2), (1, 2), (1, 4), (0.999999, 2), (0, 2), (0, 0)])
        fixed, action = c3.repair_polygon(spike, 0.01)
        self.assertIn(action, ("make_valid", "make_valid_dropped_slivers"))
        self.assertTrue(fixed.is_valid)
        self.assertEqual(fixed.geom_type, "Polygon")

    def test_attribute_cleaning(self):
        self.assertEqual(c3.clean_unit_interval(-1, "u", "r"), (None, "u"))
        self.assertEqual(c3.clean_unit_interval(0.8, "u", "r"), (0.8, None))
        self.assertEqual(c3.clean_unit_interval(1.5, "u", "r"), (None, "r"))
        self.assertEqual(c3.clean_height(-1), (None, "height_unknown"))
        self.assertEqual(c3.clean_height(-3), (None, "height_out_of_range"))
        self.assertEqual(c3.clean_height(4.2), (4.2, None))

    def test_record_contract(self):
        good = {"dataset_id": "ms", "source_ref": "q/f:1", "footprint": {"type": "Polygon", "coordinates": [square(-74, 4)]},
                "centroid": {"type": "Point", "coordinates": [-74.0, 4.0]}, "area_m2": 5.0, "area_src_m2": None,
                "confidence": None, "height_m": None, "mpio_code": "05031"}
        self.assertEqual(c3.prepared_record_errors(good), [])
        for bad, needle in (
            (dict(good, run_id="x"), "run_id"),
            (dict(good, centroid={"type": "Point", "coordinates": [4.0, -74.0]}), "ejes"),
            (dict(good, mpio_code="5031"), "DIVIPOLA"),
            (dict(good, confidence=2), "confidence"),
            (dict(good, extra=1), "fuera del contrato"),
        ):
            with self.subTest(needle):
                self.assertTrue(any(needle in e for e in c3.prepared_record_errors(bad)))


class EndToEndTests(unittest.TestCase):
    def test_full_run_counts_and_records(self):
        with TemporaryDirectory() as tmp:
            ws = Workspace(Path(tmp))
            self.assertEqual(ws.run(), 0)
            rep = ws.report()
            t = rep["totals"]
            self.assertEqual(rep["status"], "ready_for_load")
            self.assertTrue(rep["claims_pdet_selection"])
            self.assertEqual(t["read"], 13)
            self.assertEqual(t["excluded_outside_pdet"], 1)
            self.assertEqual(t["rejected_by_reason"], {
                "duplicate_geometry": 1, "geometry_type_unsupported": 1, "geometry_unparseable": 1,
                "json_invalid": 1, "outside_colombia_window": 1, "repair_split_multipolygon": 1})
            self.assertEqual(t["rejected"], 6)
            self.assertEqual(t["prepared"], 6)
            self.assertEqual(t["repaired"], 1)
            self.assertEqual(t["duplicates_removed"], 1)
            self.assertEqual(t["centroids_on_shared_boundary"], 1)
            self.assertTrue(t["balanced"])
            records = ws.records(rep)
            self.assertEqual(len(records), 6)
            for r in records:
                self.assertEqual(c3.prepared_record_errors(r), [])
            by_ref = {r["source_ref"].rsplit(":", 1)[1] + "@" + r["source_ref"][:9]: r for r in records}
            first = by_ref["1@000000001"]
            self.assertEqual((first["mpio_code"], first["confidence"], first["height_m"]), ("05031", 0.9, None))
            self.assertEqual(first["footprint"]["coordinates"], [square(-74.05, 4.05)])  # coordenadas originales
            self.assertEqual(by_ref["2@000000001"]["height_m"], 7.5)
            self.assertEqual(by_ref["9@000000001"]["mpio_code"], "05040")
            self.assertEqual(by_ref["10@000000001"]["mpio_code"], "05031")
            self.assertIsNone(by_ref["2@000000002"]["confidence"])
            self.assertIn("8@000000001", by_ref)  # reparada
            lon, lat = first["centroid"]["coordinates"]
            self.assertAlmostEqual(lon, -74.0499, places=6)
            self.assertAlmostEqual(lat, 4.0501, places=6)
            self.assertAlmostEqual(first["area_m2"], 0.0002 * 111320 * 0.0002 * 110570, delta=10)
            for part in rep["partitions"]:
                self.assertEqual(hashlib.sha256((ws.root / part["output"]["path"]).read_bytes()).hexdigest(),
                                 part["output"]["sha256"])
            with (ws.root / rep["selection"]["by_municipality_csv"]).open(encoding="utf-8") as handle:
                rows = {r["mpio_code"]: int(r["prepared_buildings"]) for r in csv.DictReader(handle)}
            self.assertEqual(rows, {"05031": 4, "05040": 2})

    def test_without_pdet_layer_refuses_unless_source_pass(self):
        with TemporaryDirectory() as tmp:
            ws = Workspace(Path(tmp), with_pdet=False)
            self.assertEqual(ws.run(), 3)
            self.assertFalse((ws.root / ws.cfg["sources"]["microsoft"]["prepare_report"]).exists())
            self.assertEqual(ws.run(without_pdet_selection=True), 0)
            rep = ws.report("source_pass_report")
            self.assertEqual(rep["status"], "source_pass_only")
            self.assertFalse(rep["claims_pdet_selection"])
            self.assertEqual(rep["totals"]["excluded_outside_pdet"], 0)
            self.assertEqual(rep["totals"]["prepared"], 7)  # 6 + la que estaba fuera de PDET
            self.assertTrue(all(r["mpio_code"] is None for r in ws.records(rep)))

    def test_sample_is_never_ready(self):
        with TemporaryDirectory() as tmp:
            ws = Workspace(Path(tmp))
            self.assertEqual(ws.run(partitions="000000002"), 0)
            rep = ws.report()
            self.assertEqual(rep["status"], "sample_only")
            self.assertFalse(rep["claims_full_source"])
            self.assertFalse(rep["claims_pdet_selection"])

    def test_tampered_partition_is_refused(self):
        with TemporaryDirectory() as tmp:
            ws = Workspace(Path(tmp))
            target = ws.root / ws.manifest["partitions"][0]["local_path"]
            write_partition(target, ws.lines_a[:2])
            with self.assertRaises(ContractError):
                ws.run()

    def test_rerun_is_deterministic(self):
        with TemporaryDirectory() as tmp:
            ws = Workspace(Path(tmp))
            ws.run()
            first = [p["output"]["sha256"] for p in ws.report()["partitions"]]
            for part in ws.report()["partitions"]:
                header = (ws.root / part["output"]["path"]).read_bytes()[:10]
                self.assertEqual(header[4:8], b"\x00\x00\x00\x00")  # mtime 0 en la cabecera gzip
                self.assertEqual(header[3] & 0x08, 0)                  # sin nombre de archivo
            ws.run()
            second = ws.report()
            self.assertEqual(first, [p["output"]["sha256"] for p in second["partitions"]])
            # La corrida exitosa anterior quedó en el historial sin modificarse.
            history = ws.root / "outputs/history/buildings_ms_prepare_report.json"
            self.assertTrue(history.exists())


if __name__ == "__main__":
    unittest.main()
