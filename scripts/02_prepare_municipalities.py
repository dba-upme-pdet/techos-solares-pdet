"""Prepara municipios PDET para MongoDB (Entrega 2, José).

Lee el manifiesto de ``01_download_mgn.py`` y ``MunicipiosPDET.xlsx``.
Escribe documentos GeoJSON compatibles con el validador de ``00_init_db.py``.
No inserta en MongoDB y no escribe ``loaded_at``: esa fecha BSON la pone
``02_load_municipalities.py`` en el momento de la carga.

La unidad de ``MPIO_NAREA`` se toma solo de metadatos que nombran ese campo.
Si no aparece, el script se detiene y no declara los 170 municipios listos.

Uso:
    python scripts/02_prepare_municipalities.py
    python scripts/02_prepare_municipalities.py --self-check
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, mapping
from shapely.ops import orient, unary_union
from shapely.validation import make_valid

from entrega2_contracts import (
    CONTRACT_VERSION,
    PDET_COLUMNS,
    SIZE_GUARD_BYTES,
    ContractError,
    area_to_km2,
    as_int,
    crs_matches,
    document_errors,
    epsg_label,
    load_config,
    normalize_label,
    parse_area_unit,
    sha256_file,
    source_version,
    write_json,
    zfill_digits,
)

ROOT = Path(__file__).resolve().parents[1]


def metadata_texts(folder: Path) -> list[tuple[str, str]]:
    found = []
    if not folder.exists():
        return found
    for path in sorted(folder.rglob("*")):
        if path.suffix.lower() not in {".xml", ".txt", ".html", ".htm", ".qmd"}:
            continue
        if not path.is_file() or path.stat().st_size > 5_000_000:
            continue
        found.append((path.name, path.read_text(encoding="utf-8", errors="replace")))
    return found


def unit_from_files(folder: Path) -> tuple[str | None, str | None]:
    found = []
    for name, text in metadata_texts(folder):
        unit = parse_area_unit(text)
        if unit:
            found.append((unit, name))
    units = {unit for unit, _ in found}
    if len(units) > 1:
        raise ContractError("metadatos contradictorios para la unidad de MPIO_NAREA")
    if not found:
        return None, None
    return found[0]


def polygonal(geometry):
    if geometry is None or geometry.is_empty:
        return None
    current = geometry
    if not current.is_valid:
        current = make_valid(current)
    if isinstance(current, GeometryCollection):
        parts = [geom for geom in current.geoms if isinstance(geom, (Polygon, MultiPolygon))]
        current = unary_union(parts) if parts else None
    if isinstance(current, Polygon):
        return orient(current, sign=1.0)
    if isinstance(current, MultiPolygon):
        return orient(MultiPolygon([orient(part, sign=1.0) for part in current.geoms]), sign=1.0)
    return None


def discover_department_column(frame: gpd.GeoDataFrame, excel_name_by_code: dict[str, str]) -> str | None:
    skip = {"MPIO_CDPMP", "MPIO_CNMBR", "MPIO_NAREA", "DPTO_CCDGO", "mpio_code", "geometry"}
    candidates = []
    for column in frame.columns:
        if column in skip:
            continue
        matched = 0
        agrees = True
        for code, expected in excel_name_by_code.items():
            if code not in frame.index:
                continue
            value = frame.at[code, column]
            try:
                if pd.isna(value):
                    agrees = False
                    break
            except Exception:
                pass
            if normalize_label(value) != expected:
                agrees = False
                break
            matched += 1
        if agrees and matched:
            candidates.append(str(column))
    if len(candidates) > 1:
        raise ContractError("varias columnas del MGN coinciden con el departamento del Excel: " + ", ".join(candidates))
    return candidates[0] if candidates else None


def prepare_documents(
    frame: gpd.GeoDataFrame,
    excel: pd.DataFrame,
    *,
    expected_crs: str,
    target_crs: str,
    area_unit: str | None,
    source_file: str,
    version: str,
    code_column: str,
    expected_count: int | None,
) -> tuple[list[dict], dict]:
    report = {
        "contract": CONTRACT_VERSION,
        "role": "prepare-report",
        "fixture": False,
        "loaded_at_included": False,
        "loaded_at_owner": "scripts/02_load_municipalities.py",
        "area_unit": area_unit,
        "dpto_name_source": None,
        "mgn_department_column": None,
        "crs_source": epsg_label(frame.crs),
        "crs_target": target_crs,
        "repaired_geometries": 0,
        "rejected": [],
        "missing_codes": [],
        "duplicate_codes": [],
        "name_mismatches": 0,
        "oversize_ids": [],
        "municipalities_written": 0,
        "expected_municipalities": expected_count,
        "claims_full_pdet_set": False,
        "status": "blocked",
    }
    for column in (code_column, PDET_COLUMNS["dpto_code"], PDET_COLUMNS["dpto_name"], PDET_COLUMNS["subregion_id"], PDET_COLUMNS["subregion_name"], PDET_COLUMNS["mpio_name"]):
        if column not in excel.columns:
            raise ContractError(f"el Excel no tiene la columna {column}")
    if not crs_matches(frame.crs, expected_crs):
        report["status"] = "invalid_crs"
        report["error"] = f"la capa está en {epsg_label(frame.crs) or 'CRS ausente'}, se esperaba {expected_crs}"
        return [], report
    if area_unit is None:
        report["status"] = "unresolved_area_unit"
        report["error"] = "MPIO_NAREA no tiene una unidad declarada en los metadatos de la capa"
        return [], report

    working = frame.copy()
    working["mpio_code"] = working["MPIO_CDPMP"].map(lambda value: zfill_digits(value, 5))
    duplicated = sorted(working.loc[working["mpio_code"].duplicated(keep=False), "mpio_code"].unique())
    if duplicated:
        report["status"] = "duplicate_codes"
        report["duplicate_codes"] = duplicated
        report["error"] = "hay códigos DIVIPOLA repetidos en la capa municipal"
        return [], report
    working = working.set_index("mpio_code", drop=False)
    excel_name_by_code = {
        zfill_digits(row[code_column], 5): normalize_label(row[PDET_COLUMNS["dpto_name"]])
        for _, row in excel.iterrows()
    }
    department_column = discover_department_column(working, excel_name_by_code)
    report["mgn_department_column"] = department_column
    report["dpto_name_source"] = (
        f"MGN:{department_column}" if department_column else "MunicipiosPDET.xlsx:Departamento"
    )

    transformed = working.to_crs(target_crs)
    documents = []
    for _, row in excel.iterrows():
        code = zfill_digits(row[code_column], 5)
        if code not in transformed.index:
            report["missing_codes"].append(code)
            continue
        feature = transformed.loc[code]
        dpto_code = zfill_digits(row[PDET_COLUMNS["dpto_code"]], 2)
        mgn_dpto = zfill_digits(feature["DPTO_CCDGO"], 2)
        if mgn_dpto != dpto_code:
            report["rejected"].append({"_id": code, "reason": f"DPTO_CCDGO {mgn_dpto} no coincide con el Excel {dpto_code}"})
            continue
        geometry = feature.geometry
        repaired = bool(geometry is not None and not geometry.is_valid)
        polygon = polygonal(geometry)
        if polygon is None:
            report["rejected"].append({"_id": code, "reason": "geometría vacía o no poligonal después de make_valid"})
            continue
        if repaired:
            report["repaired_geometries"] += 1
        if department_column:
            dpto_name = str(feature[department_column]).strip()
        else:
            dpto_name = str(row[PDET_COLUMNS["dpto_name"]]).strip()
        mgn_name = str(feature["MPIO_CNMBR"]).strip()
        excel_name = str(row[PDET_COLUMNS["mpio_name"]]).strip()
        if normalize_label(mgn_name) != normalize_label(excel_name):
            report["name_mismatches"] += 1
        document = {
            "_id": code,
            "name": mgn_name,
            "dpto_code": dpto_code,
            "dpto_name": dpto_name,
            "subregion_id": as_int(row[PDET_COLUMNS["subregion_id"]]),
            "subregion_name": str(row[PDET_COLUMNS["subregion_name"]]).strip(),
            "area_km2": area_to_km2(feature["MPIO_NAREA"], area_unit),
            "geometry": mapping(polygon),
            "source": {"dataset": "MGN", "version": version, "file": source_file},
        }
        errors = document_errors(document)
        if any(error.startswith("documento supera") for error in errors):
            report["oversize_ids"].append(code)
        if errors:
            report["rejected"].append({"_id": code, "reason": "; ".join(errors)})
            continue
        documents.append(document)

    documents.sort(key=lambda item: item["_id"])
    report["municipalities_written"] = len(documents)
    report["missing_codes"] = sorted(set(report["missing_codes"]))
    if report["rejected"] or report["missing_codes"] or report["oversize_ids"]:
        report["status"] = "invalid_features"
        return [], report
    if expected_count is not None and len(documents) != expected_count:
        report["status"] = "incomplete_join"
        report["error"] = f"se prepararon {len(documents)} documentos y el contrato espera {expected_count}"
        return [], report
    report["status"] = "ready_for_load"
    report["claims_full_pdet_set"] = expected_count == 170 and len(documents) == 170
    return documents, report


def assert_production_manifest(manifest: dict) -> None:
    if manifest.get("contract") != CONTRACT_VERSION or manifest.get("role") != "download-manifest":
        raise ContractError("el manifiesto no es el contrato entrega2-mgn-v1")
    if manifest.get("fixture") is True:
        raise ContractError("el manifiesto es un fixture y no prueba la descarga del MGN")
    if manifest.get("status") != "complete" or manifest.get("claims_national_download") is not True:
        raise ContractError("la descarga nacional no está verificada")
    if manifest.get("crs_equals_expected") is not True:
        raise ContractError("el manifiesto no confirma el CRS de origen")
    if not manifest.get("extracted_layer"):
        raise ContractError("el manifiesto no trae extracted_layer")


def write_geojsonl(path: Path, documents: list[dict]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for document in documents
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return sha256_file(path)


def run_real(root: Path) -> int:
    config = load_config(root)
    outputs = root / config["paths"]["outputs"]
    report_path = outputs / "municipalities_prepare_report.json"
    manifest_path = outputs / "mgn_download_manifest.json"
    base = {
        "contract": CONTRACT_VERSION,
        "role": "prepare-report",
        "fixture": False,
        "loaded_at_included": False,
        "loaded_at_owner": "scripts/02_load_municipalities.py",
        "municipalities_written": 0,
        "expected_municipalities": config["sources"]["pdet_list"]["expected_municipalities"],
        "claims_full_pdet_set": False,
        "output_geojsonl": None,
    }
    if not manifest_path.exists():
        base.update(
            {
                "status": "blocked_no_layer",
                "error": "no existe outputs/mgn_download_manifest.json con una descarga verificada",
            }
        )
        write_json(report_path, base)
        print(f"[FALLA] {base['error']}", file=sys.stderr)
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    try:
        assert_production_manifest(manifest)
    except ContractError as exc:
        base.update({"status": "blocked_no_layer", "error": str(exc)})
        write_json(report_path, base)
        print(f"[FALLA] {exc}", file=sys.stderr)
        return 2

    layer_path = root / manifest["extracted_layer"]
    frame = gpd.read_file(layer_path)
    pdet = config["sources"]["pdet_list"]
    excel = pd.read_excel(root / pdet["file"], sheet_name=pdet["sheet"])
    unit = manifest.get("area_unit")
    unit_source = manifest.get("area_unit_source")
    scanned_unit, scanned_source = unit_from_files(layer_path.parent)
    if unit and scanned_unit and unit != scanned_unit:
        base.update({"status": "unresolved_area_unit", "error": "el manifiesto y los metadatos declaran unidades distintas"})
        write_json(report_path, base)
        print(f"[FALLA] {base['error']}", file=sys.stderr)
        return 3
    if not unit and scanned_unit:
        unit, unit_source = scanned_unit, scanned_source
    documents, report = prepare_documents(
        frame,
        excel,
        expected_crs=manifest["crs_expected"],
        target_crs=config["processing"]["target_crs"],
        area_unit=unit,
        source_file=manifest.get("filename") or layer_path.name,
        version=source_version(config["sources"]["mgn"]["version"]),
        code_column=pdet["code_column"],
        expected_count=pdet["expected_municipalities"],
    )
    report["fixture"] = False
    report["area_unit_source"] = unit_source
    report["source_manifest"] = manifest_path.name
    if report["status"] != "ready_for_load":
        report["output_geojsonl"] = None
        report["sha256"] = None
        write_json(report_path, report)
        print(f"[FALLA] {report['status']}: {report.get('error', '')}", file=sys.stderr)
        return 3 if report["status"] == "unresolved_area_unit" else 1
    output = root / config["paths"]["processed_data"] / "municipalities.geojsonl"
    report["sha256"] = write_geojsonl(output, documents)
    report["output_geojsonl"] = output.relative_to(root).as_posix()
    write_json(report_path, report)
    print(
        f"[OK] {report['municipalities_written']} documentos en {report['output_geojsonl']}; "
        "loaded_at no va incluido"
    )
    return 0


def _excel(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _layer(rows: list[dict], geometries, crs: str) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(rows, geometry=geometries, crs=crs)


def run_self_check() -> int:
    from shapely.geometry import Polygon

    checks: dict[str, bool] = {}

    def check(name: str, condition: bool) -> None:
        checks[name] = bool(condition)
        print(f"[{'OK' if condition else 'FALLA'}] {name}")

    square = Polygon([(-76.5, 2.2), (-76.4, 2.2), (-76.4, 2.3), (-76.45, 2.28), (-76.5, 2.3), (-76.5, 2.2)])
    bowtie = Polygon([(-76.5, 2.2), (-76.4, 2.3), (-76.4, 2.2), (-76.5, 2.3), (-76.5, 2.2)])
    excel = _excel(
        [
            {
                "id": 1,
                "Subregión PDET": "ALTO PATÍA Y NORTE DEL CAUCA",
                "Código DANE Departamento": 19,
                "Departamento": "CAUCA",
                "Código DANE Municipio": 5031,
                "Municipio": "NOMBRE DISTINTO",
            },
            {
                "id": 1,
                "Subregión PDET": "ALTO PATÍA Y NORTE DEL CAUCA",
                "Código DANE Departamento": 19,
                "Departamento": "CAUCA",
                "Código DANE Municipio": 19050,
                "Municipio": "ARGELIA",
            },
        ]
    )
    layer = _layer(
        [
            {"MPIO_CDPMP": 5031, "MPIO_CNMBR": "AMALFI", "MPIO_NAREA": 1_000_000, "DPTO_CCDGO": 5, "NOM_DEPTO": "ANTIOQUIA"},
            {"MPIO_CDPMP": "19050", "MPIO_CNMBR": "ARGELIA", "MPIO_NAREA": 12.5, "DPTO_CCDGO": "19", "NOM_DEPTO": "CAUCA"},
        ],
        [square, square],
        "EPSG:4686",
    )
    # The first fixture row above mixes departments on purpose in a later check.
    # This successful pair uses one department and a 4-digit code.
    excel_ok = excel.copy()
    excel_ok.loc[0, "Código DANE Departamento"] = 5
    excel_ok.loc[0, "Departamento"] = "ANTIOQUIA"
    layer_ok = layer.copy()
    documents, report = prepare_documents(
        layer_ok,
        excel_ok,
        expected_crs="EPSG:4686",
        target_crs="EPSG:4326",
        area_unit="m2",
        source_file="fixture-mgn.shp",
        version="2025",
        code_column="Código DANE Municipio",
        expected_count=2,
    )
    # 1_000_000 m2 -> 1 km2, and 12.5 m2 stays a small number. Rebuild with one unit.
    by_id = {item["_id"]: item for item in documents}
    check("el código 5031 se normaliza a 05031 y cruza por DIVIPOLA", "05031" in by_id and by_id["05031"]["name"] == "AMALFI")
    check("el nombre sale del MGN aunque el Excel diga otra cosa", by_id.get("05031", {}).get("name") != "NOMBRE DISTINTO")
    check("los documentos no traen loaded_at", all("loaded_at" not in item for item in documents))
    check("1 000 000 m2 declarados pasan a 1 km2", by_id.get("05031", {}).get("area_km2") == 1.0)
    check("la columna de departamento se descubre por coincidencia, no por un nombre fijo", report["mgn_department_column"] == "NOM_DEPTO")
    ring = by_id["19050"]["geometry"]["coordinates"][0]
    check("no se simplifica: el anillo conserva sus vértices", len(ring) >= 6)
    check("el anillo exterior queda en sentido antihorario", _signed_area(ring) > 0)
    check("el resultado fixture no afirma los 170 municipios", report["claims_full_pdet_set"] is False and report["status"] == "ready_for_load")

    km_docs, km_report = prepare_documents(
        layer_ok,
        excel_ok,
        expected_crs="EPSG:4686",
        target_crs="EPSG:4326",
        area_unit="km2",
        source_file="fixture-mgn.shp",
        version="2025",
        code_column="Código DANE Municipio",
        expected_count=2,
    )
    check("si la unidad declarada es km2, 12.5 no se divide", {item["_id"]: item["area_km2"] for item in km_docs}.get("19050") == 12.5 and km_report["status"] == "ready_for_load")

    missing_unit_docs, missing_report = prepare_documents(
        layer_ok,
        excel_ok,
        expected_crs="EPSG:4686",
        target_crs="EPSG:4326",
        area_unit=None,
        source_file="fixture-mgn.shp",
        version="2025",
        code_column="Código DANE Municipio",
        expected_count=2,
    )
    check("sin unidad declarada no se escribe ningún municipio", missing_unit_docs == [] and missing_report["status"] == "unresolved_area_unit")

    no_name = layer_ok.drop(columns=["NOM_DEPTO"])
    fallback_docs, fallback = prepare_documents(
        no_name,
        excel_ok,
        expected_crs="EPSG:4686",
        target_crs="EPSG:4326",
        area_unit="km2",
        source_file="fixture-mgn.shp",
        version="2025",
        code_column="Código DANE Municipio",
        expected_count=2,
    )
    check("si ninguna columna del MGN coincide, el departamento sale del Excel", fallback["dpto_name_source"].endswith("Departamento") and {item["_id"]: item["dpto_name"] for item in fallback_docs}["05031"] == "ANTIOQUIA")

    ambiguous = layer_ok.copy()
    ambiguous["OTRA"] = ambiguous["NOM_DEPTO"]
    try:
        prepare_documents(
            ambiguous,
            excel_ok,
            expected_crs="EPSG:4686",
            target_crs="EPSG:4326",
            area_unit="km2",
            source_file="fixture-mgn.shp",
            version="2025",
            code_column="Código DANE Municipio",
            expected_count=2,
        )
        check("dos columnas de departamento idénticas se rechazan", False)
    except ContractError:
        check("dos columnas de departamento idénticas se rechazan", True)

    broken = _layer(
        [{"MPIO_CDPMP": 19050, "MPIO_CNMBR": "ARGELIA", "MPIO_NAREA": 1, "DPTO_CCDGO": 19, "NOM_DEPTO": "CAUCA"}],
        [bowtie],
        "EPSG:4686",
    )
    repaired_docs, repaired = prepare_documents(
        broken,
        excel_ok.iloc[1:],
        expected_crs="EPSG:4686",
        target_crs="EPSG:4326",
        area_unit="km2",
        source_file="fixture-mgn.shp",
        version="2025",
        code_column="Código DANE Municipio",
        expected_count=1,
    )
    check("una geometría inválida se repara con make_valid y no se simplifica a la fuerza", repaired["status"] == "ready_for_load" and repaired["repaired_geometries"] == 1 and repaired_docs[0]["geometry"]["type"] in ("Polygon", "MultiPolygon"))

    huge_errors = document_errors(
        {
            "_id": "19050",
            "name": "ARGELIA",
            "dpto_code": "19",
            "dpto_name": "CAUCA",
            "subregion_id": 1,
            "subregion_name": "X",
            "area_km2": 1,
            "geometry": {"type": "Polygon", "coordinates": [[[-76.5, 2.2], [-76.4, 2.2], [-76.4, 2.3], [-76.5, 2.2]]]},
            "source": {"dataset": "MGN", "version": "2025", "file": "f"},
        },
        size_limit=40,
    )
    check("un documento sobre el límite de tamaño falla y no se recorta", any("no se simplifica" in error for error in huge_errors))

    try:
        assert_production_manifest({"contract": CONTRACT_VERSION, "role": "download-manifest", "fixture": True, "status": "complete", "claims_national_download": False, "crs_equals_expected": True, "extracted_layer": "x"})
        check("un manifiesto fixture no habilita la preparación nacional", False)
    except ContractError:
        check("un manifiesto fixture no habilita la preparación nacional", True)

    check("kilómetros cuadrados no se leen como metros", parse_area_unit("MPIO_NAREA en kilómetros cuadrados") == "km2")
    check("sin la cadena MPIO_NAREA no hay unidad", parse_area_unit("el área es de 10 metros cuadrados") is None)

    passed = all(checks.values())
    print(f"{'FIXTURE' if passed else 'FALLA'} self-check preparación: {sum(checks.values())}/{len(checks)}")
    return 0 if passed else 1


def _signed_area(ring: list) -> float:
    area = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        area += x1 * y2 - x2 * y1
    return area / 2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--self-check", action="store_true", help="pruebas con fixtures etiquetados; no usa el MGN real")
    args = parser.parse_args()
    if args.self_check:
        try:
            sys.exit(run_self_check())
        except Exception:
            traceback.print_exc()
            sys.exit(1)
    sys.exit(run_real(ROOT))


if __name__ == "__main__":
    main()
