"""Pruebas de scripts/03_download_ms_buildings.py. Datos SINTÉTICOS; no usan red ni MongoDB.

Ejecutar: .venv/bin/python -m unittest discover -s tests -p "test_download_ms_buildings.py" -v
"""
import base64
import gzip
import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("download_ms", ROOT / "scripts/03_download_ms_buildings.py")
ms = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ms)

BASE = "https://minedbuildings.z5.web.core.windows.net/global-buildings/2026-02-03/global-buildings.geojsonl"


def feature(x, y, size=0.0002, height=-1.0, confidence=-1.0):
    ring = [[x, y], [x + size, y], [x + size, y + size], [x, y + size], [x, y]]
    return {"type": "Feature", "properties": {"height": height, "confidence": confidence},
            "geometry": {"type": "Polygon", "coordinates": [ring]}}


def write_gz(path, features):
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for f in features:
            handle.write(json.dumps(f) + "\n")


class QuadkeyTests(unittest.TestCase):
    def test_round_trip(self):
        for qk in ["0", "3", "032203231", "032233200"]:
            x, y, z = ms.quadkey_to_tile(qk)
            self.assertEqual(ms.tile_to_quadkey(x, y, z), qk)

    def test_bounds_contain_known_building(self):
        # Partición real de San Andrés: sus edificaciones están cerca de (-81.708, 12.531).
        min_lon, min_lat, max_lon, max_lat = ms.quadkey_bounds("032203231")
        self.assertTrue(min_lon <= -81.708 <= max_lon and min_lat <= 12.531 <= max_lat)

    def test_level_one_quadrants(self):
        self.assertEqual(ms.quadkey_bounds("0")[:2], (-180.0, 0.0))
        self.assertAlmostEqual(ms.quadkey_bounds("3")[0], 0.0)

    def test_tiles_covering_includes_point_tile(self):
        x, y = ms.lonlat_to_tile(-74.1, 4.6, 9)
        self.assertIn(ms.tile_to_quadkey(x, y, 9), ms.tiles_covering((-74.2, 4.5, -74.0, 4.7), 9))

    def test_invalid_quadkey(self):
        with self.assertRaises(ms.ContractError):
            ms.quadkey_to_tile("0124")


class IndexTests(unittest.TestCase):
    def write_index(self, folder, lines):
        path = Path(folder) / "dataset-links.csv"
        path.write_text("Location,QuadKey,Url,Size,UploadDate\n" + "\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_filters_country_and_rejects_bad_rows(self):
        with TemporaryDirectory() as tmp:
            path = self.write_index(tmp, [
                f"Colombia,032203231,{BASE}/RegionName=Colombia/quadkey=032203231/part-1.csv.gz,260.5KB,2026-02-23",
                f"Colombia,32203213,{BASE}/RegionName=Colombia/quadkey=032203213/part-2.csv.gz,1.2MB,2026-02-23",
                f"Colombia,032203300,{BASE}/RegionName=Colombia/quadkey=999999999/part-3.csv.gz,1KB,2026-02-23",
                f"Peru,032203231,{BASE}/RegionName=Peru/quadkey=032203231/part-4.csv.gz,1KB,2026-02-23",
            ])
            rows, problems = ms.parse_index(path, "Colombia", 9)
        self.assertEqual([r["quadkey"] for r in rows], ["032203231", "032203213"])  # cero recuperado
        self.assertEqual(rows[0]["release"], "2026-02-03")
        self.assertEqual(rows[1]["size_declared_bytes"], int(1.2 * 1024**2))
        self.assertEqual(len(problems), 1)
        self.assertIn("quadkey", problems[0])

    def test_missing_columns(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.csv"
            path.write_text("Location,Url\n", encoding="utf-8")
            with self.assertRaises(ms.ContractError):
                ms.parse_index(path, "Colombia", 9)


class SelectionTests(unittest.TestCase):
    def test_selects_only_tiles_touching_pdet(self):
        x, y = ms.lonlat_to_tile(-74.1, 4.6, 9)
        inside = ms.tile_to_quadkey(x, y, 9)
        far = ms.tile_to_quadkey(x + 5, y, 9)
        rows = [{"quadkey": qk, "url": f"u{qk}", "size_declared_bytes": 1} for qk in (inside, far)]
        municipalities = [{"code": "00001", "name": "SINTÉTICO", "subregion": "S",
                           "geometry": box(-74.15, 4.55, -74.05, 4.65)}]
        result = ms.select_partitions(rows, municipalities, buffer_deg=0.0, zoom=9)
        self.assertEqual([r["quadkey"] for r in result["selected"]], [inside])
        self.assertEqual(result["selected"][0]["pdet_municipalities"], ["00001"])
        self.assertEqual(result["coverage"][0]["partitions"], 1)
        self.assertGreater(result["coverage"][0]["share_in_published_partitions"], 0)

    def test_reports_tiles_without_partition(self):
        municipalities = [{"code": "00002", "name": "SIN DATOS", "subregion": "S",
                           "geometry": box(-74.15, 4.55, -74.05, 4.65)}]
        result = ms.select_partitions([], municipalities, buffer_deg=0.0, zoom=9)
        self.assertEqual(result["selected"], [])
        self.assertGreaterEqual(len(result["tiles_without_partition"]), 1)
        self.assertEqual(result["coverage"][0]["partitions"], 0)


class InspectionTests(unittest.TestCase):
    def test_reads_fields_geometry_and_crs(self):
        x, y = ms.lonlat_to_tile(-74.1, 4.6, 9)
        qk = ms.tile_to_quadkey(x, y, 9)
        min_lon, min_lat, _, _ = ms.quadkey_bounds(qk)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "part.csv.gz"
            write_gz(path, [feature(min_lon + 0.1, min_lat + 0.1),
                            feature(min_lon + 0.2, min_lat + 0.2, height=6.5, confidence=0.9)])
            info = ms.inspect_partition(path, qk)
        self.assertTrue(info["readable"])
        self.assertEqual(info["features"], 2)
        self.assertEqual(info["geometry_types"], {"Polygon": 2})
        self.assertEqual(info["property_keys"], {"height": 2, "confidence": 2})
        self.assertEqual(info["height"]["unknown_minus_one"], 1)
        self.assertEqual(info["height"]["max"], 6.5)
        self.assertEqual(info["invalid_geometries"], 0)
        self.assertEqual(info["features_outside_tile"], 0)
        self.assertTrue(info["crs"].startswith("EPSG:4326"))
        self.assertEqual(ms.partition_problems({"inspection": info}), [])

    def test_swapped_axes_are_flagged(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "part.csv.gz"
            write_gz(path, [feature(4.6, -74.1)])  # lat/lon invertidos
            info = ms.inspect_partition(path)
        self.assertEqual(info["centroids_outside_colombia"], 1)
        self.assertEqual(info["crs"], "revisar")
        self.assertTrue(ms.partition_problems({"inspection": info}))

    def test_truncated_file_is_not_readable(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "part.csv.gz"
            write_gz(path, [feature(-74.1, 4.6)] * 200)
            data = path.read_bytes()
            path.write_bytes(data[: len(data) // 2])
            info = ms.inspect_partition(path)
        self.assertFalse(info["readable"])
        self.assertTrue(ms.partition_problems({"inspection": info})[0].startswith("no legible"))


class IntegrityTests(unittest.TestCase):
    def test_digests_and_server_mismatch(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.bin"
            path.write_bytes(b"techos")
            local = ms.file_digests(path)
        md5 = base64.b64encode(hashlib.md5(b"techos").digest()).decode()
        self.assertEqual(local["md5_b64"], md5)
        self.assertEqual(local["sha256"], hashlib.sha256(b"techos").hexdigest())
        self.assertEqual(ms.server_mismatch(local, {"content_length": 6, "content_md5": md5}), [])
        self.assertEqual(len(ms.server_mismatch(local, {"content_length": 7, "content_md5": "x"})), 2)

    def test_http_metadata(self):
        meta = ms.http_metadata({"Content-Length": "10", "Content-MD5": "abc", "ETag": "e", "Last-Modified": "d"})
        self.assertEqual(meta, {"content_length": 10, "content_md5": "abc", "etag": "e", "last_modified": "d"})

    def test_offline_requires_matching_manifest(self):
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / "f.csv.gz"
            dest.write_bytes(b"abc")
            row = {"url": "https://example.invalid/f.csv.gz"}
            with self.assertRaises(ms.ContractError):
                ms.fetch_partition(row, dest, {"sha256": "otro"}, offline=True)
            good = {"sha256": hashlib.sha256(b"abc").hexdigest()}
            self.assertTrue(ms.fetch_partition(row, dest, good, offline=True)["cached"])


if __name__ == "__main__":
    unittest.main()
