"""Valida la capa municipal del MGN contra la lista PDET (Entrega 2, Samuel).

Lee la capa que declara ``outputs/mgn_download_manifest.json`` (la escribe
``01_download_mgn.py``) y ``resources/MunicipiosPDET.xlsx``. El cruce es por
código DIVIPOLA de 5 dígitos, nunca por nombre.

Revisa:
- códigos DIVIPOLA: formato, nulos y coherencia con el código de departamento;
- duplicados en la capa y en la lista PDET;
- municipios PDET que faltan en el MGN y departamentos que no coinciden;
- geometrías nulas, vacías, no poligonales, inválidas o fuera de Colombia.

No modifica la capa ni repara geometrías: eso lo hace ``02_prepare_municipalities.py``.

Escribe:
- ``outputs/mgn_validation_report.json``: resultado de cada verificación;
- ``outputs/mgn_validation_summary.md``: resumen legible para el informe;
- ``outputs/pdet_mgn_crosswalk.csv``: una fila por municipio PDET.

Salida: 0 si todo pasa, 1 si alguna verificación falla, 2 si no hay capa verificada.

Uso:
    python scripts/01_validate_mgn.py
    python scripts/01_validate_mgn.py --self-check
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box
from shapely.validation import explain_validity

from entrega2_contracts import (
    COLOMBIA_LAT,
    COLOMBIA_LON,
    CONTRACT_VERSION,
    PDET_COLUMNS,
    REQUIRED_MGN_FIELDS,
    ContractError,
    crs_matches,
    epsg_label,
    load_config,
    normalize_label,
    sha256_file,
    write_json,
    zfill_digits,
)

ROOT = Path(__file__).resolve().parents[1]
REPORT_NAME = "mgn_validation_report.json"
SUMMARY_NAME = "mgn_validation_summary.md"
CROSSWALK_NAME = "pdet_mgn_crosswalk.csv"


def strip_accents(value) -> str:
    text = unicodedata.normalize("NFKD", normalize_label(value))
    return "".join(char for char in text if not unicodedata.combining(char))


def safe_code(value, width: int) -> str | None:
    try:
        return zfill_digits(value, width)
    except ContractError:
        return None


def geometry_problem(geometry) -> str | None:
    """Motivo por el que la geometría no sirve tal como viene, o ``None``."""
    if geometry is None:
        return "geometría nula"
    if geometry.is_empty:
        return "geometría vacía"
    if geometry.geom_type not in ("Polygon", "MultiPolygon"):
        return f"tipo {geometry.geom_type}, se esperaba Polygon o MultiPolygon"
    if not geometry.is_valid:
        return "inválida: " + explain_validity(geometry)
    return None


def validate(frame: gpd.GeoDataFrame, excel: pd.DataFrame, *, config: dict) -> tuple[dict, pd.DataFrame]:
    mgn_cfg = config["sources"]["mgn"]
    pdet_cfg = config["sources"]["pdet_list"]
    code_column = pdet_cfg["code_column"]
    expected_features = mgn_cfg.get("wfs", {}).get("expected_feature_count")
    expected_pdet = pdet_cfg["expected_municipalities"]
    expected_subregions = pdet_cfg["expected_subregions"]
    checks: list[dict] = []

    def check(name: str, passed: bool, detail: str = "", *, blocking: bool = True) -> None:
        checks.append({"name": name, "passed": bool(passed), "blocking": blocking, "detail": detail})

    # --- Estructura de la capa -------------------------------------------------
    missing_fields = [field for field in REQUIRED_MGN_FIELDS if field not in frame.columns]
    check("campos obligatorios del MGN", not missing_fields, ", ".join(missing_fields) or "presentes")
    if missing_fields:
        return finish(checks, {}), pd.DataFrame()
    check(
        f"capa nacional con {expected_features} municipios",
        expected_features is None or len(frame) == expected_features,
        f"{len(frame)} registros",
    )
    check(
        f"CRS {mgn_cfg['source_crs']}",
        crs_matches(frame.crs, mgn_cfg["source_crs"]),
        epsg_label(frame.crs) or "CRS ausente",
    )

    # --- Códigos DIVIPOLA de la capa ---------------------------------------
    layer = frame.copy()
    layer["mpio_code"] = layer["MPIO_CDPMP"].map(lambda value: safe_code(value, 5))
    layer["dpto_code"] = layer["DPTO_CCDGO"].map(lambda value: safe_code(value, 2))
    bad_format = layer.loc[
        layer["mpio_code"].isna() | ~layer["mpio_code"].fillna("").str.fullmatch(r"\d{5}"), "MPIO_CDPMP"
    ]
    check("MPIO_CDPMP es DIVIPOLA de 5 dígitos", bad_format.empty, listing(bad_format.astype(str)))
    bad_dpto = layer.loc[
        layer["mpio_code"].notna() & (layer["mpio_code"].str[:2] != layer["dpto_code"]), "mpio_code"
    ]
    check("prefijo de MPIO_CDPMP = DPTO_CCDGO", bad_dpto.empty, listing(bad_dpto))
    if "MPIO_CCDGO" in layer.columns:
        suffix = layer["MPIO_CCDGO"].map(lambda value: safe_code(value, 3))
        bad_suffix = layer.loc[layer["mpio_code"].notna() & (layer["mpio_code"].str[2:] != suffix), "mpio_code"]
        check("sufijo de MPIO_CDPMP = MPIO_CCDGO", bad_suffix.empty, listing(bad_suffix))
    layer_dupes = sorted(layer.loc[layer["mpio_code"].duplicated(keep=False), "mpio_code"].dropna().unique())
    check("sin códigos repetidos en el MGN", not layer_dupes, listing(layer_dupes))
    layer["area_km2"] = pd.to_numeric(layer["MPIO_NAREA"], errors="coerce")
    bad_area = layer.loc[~(layer["area_km2"] > 0), "mpio_code"]
    check("MPIO_NAREA positiva", bad_area.empty, listing(bad_area.astype(str)))

    # --- Geometrías de la capa ---------------------------------------------
    layer["geometry_problem"] = layer.geometry.map(geometry_problem)
    bad_geometry = layer.loc[layer["geometry_problem"].notna()]
    check(
        "geometrías válidas en el MGN",
        bad_geometry.empty,
        listing(f"{row.mpio_code}: {row.geometry_problem}" for row in bad_geometry.itertuples()),
        blocking=False,  # fuera de los PDET solo se reporta; los PDET se revisan abajo
    )
    window = box(COLOMBIA_LON[0], COLOMBIA_LAT[0], COLOMBIA_LON[1], COLOMBIA_LAT[1])
    outside = layer.loc[layer.geometry.notna() & ~layer.geometry.within(window), "mpio_code"]
    check("geometrías dentro de la ventana de Colombia (lon/lat)", outside.empty, listing(outside.astype(str)))

    # --- Lista PDET ----------------------------------------------------------
    pdet = excel.copy()
    pdet["mpio_code"] = pdet[code_column].map(lambda value: safe_code(value, 5))
    pdet["dpto_code"] = pdet[PDET_COLUMNS["dpto_code"]].map(lambda value: safe_code(value, 2))
    check(f"lista PDET con {expected_pdet} filas", len(pdet) == expected_pdet, f"{len(pdet)} filas")
    bad_pdet_codes = pdet.loc[pdet["mpio_code"].isna(), code_column]
    check("códigos PDET numéricos", bad_pdet_codes.empty, listing(bad_pdet_codes.astype(str)))
    pdet_dupes = sorted(pdet.loc[pdet["mpio_code"].duplicated(keep=False), "mpio_code"].dropna().unique())
    check("sin códigos repetidos en la lista PDET", not pdet_dupes, listing(pdet_dupes))
    subregions = pdet[PDET_COLUMNS["subregion_id"]].nunique()
    check(f"{expected_subregions} subregiones PDET", subregions == expected_subregions, f"{subregions} subregiones")
    bad_pdet_prefix = pdet.loc[pdet["mpio_code"].notna() & (pdet["mpio_code"].str[:2] != pdet["dpto_code"]), "mpio_code"]
    check("prefijo de código PDET = departamento del Excel", bad_pdet_prefix.empty, listing(bad_pdet_prefix))

    # --- Cruce PDET x MGN ----------------------------------------------------
    unique_layer = layer.dropna(subset=["mpio_code"]).drop_duplicates("mpio_code").set_index("mpio_code")
    rows = []
    for _, item in pdet.dropna(subset=["mpio_code"]).iterrows():
        code = item["mpio_code"]
        found = code in unique_layer.index
        feature = unique_layer.loc[code] if found else None
        excel_name = str(item[PDET_COLUMNS["mpio_name"]]).strip()
        mgn_name = str(feature["MPIO_CNMBR"]).strip() if found else ""
        if not found:
            name_match = ""
        elif normalize_label(excel_name) == normalize_label(mgn_name):
            name_match = "igual"
        elif strip_accents(excel_name) == strip_accents(mgn_name):
            name_match = "solo_tildes"
        else:
            name_match = "distinto"
        rows.append(
            {
                "mpio_code": code,
                "subregion_id": item[PDET_COLUMNS["subregion_id"]],
                "subregion_name": str(item[PDET_COLUMNS["subregion_name"]]).strip(),
                "dpto_code_excel": item["dpto_code"],
                "dpto_code_mgn": feature["dpto_code"] if found else "",
                "name_excel": excel_name,
                "name_mgn": mgn_name,
                "name_match": name_match,
                "in_mgn": found,
                "geometry_type": feature.geometry.geom_type if found and feature.geometry is not None else "",
                "geometry_problem": "" if not found or pd.isna(feature["geometry_problem"]) else feature["geometry_problem"],
                "area_km2_mgn": float(feature["area_km2"]) if found else None,
            }
        )
    crosswalk = pd.DataFrame(rows)
    if crosswalk.empty:
        crosswalk = pd.DataFrame(columns=["mpio_code", "in_mgn", "dpto_code_excel", "dpto_code_mgn", "name_match", "geometry_problem"])

    missing = crosswalk.loc[~crosswalk["in_mgn"].astype(bool), "mpio_code"].tolist()
    found_rows = crosswalk.loc[crosswalk["in_mgn"].astype(bool)]
    check("todos los municipios PDET están en el MGN", not missing, listing(missing))
    dpto_mismatch = found_rows.loc[found_rows["dpto_code_excel"] != found_rows["dpto_code_mgn"], "mpio_code"].tolist()
    check("departamento del Excel = DPTO_CCDGO del MGN", not dpto_mismatch, listing(dpto_mismatch))
    pdet_bad_geometry = found_rows.loc[found_rows["geometry_problem"] != ""]
    check(
        "geometrías PDET válidas",
        pdet_bad_geometry.empty,
        listing(f"{row.mpio_code}: {row.geometry_problem}" for row in pdet_bad_geometry.itertuples()),
    )
    renamed = found_rows.loc[found_rows["name_match"] != "igual"]
    check(
        "nombres Excel = MGN (informativo; el cruce es por código)",
        renamed.empty,
        f"{len(renamed)} distintos ({(renamed['name_match'] == 'solo_tildes').sum()} solo por tildes)",
        blocking=False,
    )
    matched = len(found_rows) - len(dpto_mismatch)
    check(
        f"cruce completo de {expected_pdet} municipios PDET",
        matched == expected_pdet and not pdet_dupes,
        f"{matched} cruzados",
    )

    stats = {
        "mgn_features": int(len(frame)),
        "mgn_invalid_geometries": int(len(bad_geometry)),
        "mgn_geometry_types": {str(k): int(v) for k, v in frame.geom_type.value_counts().items()},
        "mgn_duplicate_codes": layer_dupes,
        "pdet_rows": int(len(pdet)),
        "pdet_subregions": int(subregions),
        "pdet_duplicate_codes": pdet_dupes,
        "pdet_matched": int(matched),
        "pdet_missing_codes": missing,
        "pdet_dpto_mismatches": dpto_mismatch,
        "pdet_invalid_geometries": pdet_bad_geometry["mpio_code"].tolist(),
        "pdet_name_differences": [
            {"_id": row.mpio_code, "excel": row.name_excel, "mgn": row.name_mgn, "tipo": row.name_match}
            for row in renamed.itertuples()
        ],
        "pdet_area_km2_total": round(float(found_rows["area_km2_mgn"].sum()), 3) if len(found_rows) else 0.0,
    }
    return finish(checks, stats), crosswalk


def listing(values, limit: int = 20) -> str:
    items = [str(value) for value in values]
    if not items:
        return "ninguno"
    shown = ", ".join(items[:limit])
    return shown + (f" y {len(items) - limit} más" if len(items) > limit else "")


def finish(checks: list[dict], stats: dict) -> dict:
    failed = [item["name"] for item in checks if item["blocking"] and not item["passed"]]
    warnings = [item["name"] for item in checks if not item["blocking"] and not item["passed"]]
    return {
        "contract": CONTRACT_VERSION,
        "role": "validation-report",
        "fixture": False,
        "status": "valid" if not failed else "invalid",
        "checks_passed": sum(item["passed"] for item in checks),
        "checks_total": len(checks),
        "failed_checks": failed,
        "warnings": warnings,
        "checks": checks,
        **stats,
    }


def summary_markdown(report: dict) -> str:
    lines = [
        "# Validación del MGN contra la lista PDET",
        "",
        f"Generado por `scripts/01_validate_mgn.py` el {report.get('generated_at', '')}.",
        "",
        f"- Estado: **{report['status']}** ({report['checks_passed']}/{report['checks_total']} verificaciones).",
        f"- Capa: `{report.get('layer', '')}` (SHA256 `{str(report.get('layer_sha256', ''))[:16]}…`).",
        f"- Municipios en el MGN: {report.get('mgn_features', 0)}. Municipios PDET cruzados: "
        f"{report.get('pdet_matched', 0)} de {report.get('pdet_rows', 0)}.",
        f"- Área MGN total de los PDET: {report.get('pdet_area_km2_total', 0):,.1f} km².",
        "",
        "| Verificación | Resultado | Detalle |",
        "| --- | --- | --- |",
    ]
    for item in report["checks"]:
        if item["passed"]:
            mark = "OK"
        else:
            mark = "FALLA" if item["blocking"] else "AVISO"
        detail = item["detail"].replace("|", "\\|")
        lines.append(f"| {item['name']} | {mark} | {detail} |")
    differences = report.get("pdet_name_differences") or []
    if differences:
        lines += ["", "## Nombres distintos entre el Excel y el MGN", "", "| Código | Excel | MGN | Tipo |", "| --- | --- | --- | --- |"]
        lines += [f"| {d['_id']} | {d['excel']} | {d['mgn']} | {d['tipo']} |" for d in differences]
    return "\n".join(lines) + "\n"


def write_outputs(outputs: Path, report: dict, crosswalk: pd.DataFrame) -> None:
    write_json(outputs / REPORT_NAME, report)
    (outputs / SUMMARY_NAME).write_text(summary_markdown(report), encoding="utf-8")
    crosswalk.to_csv(outputs / CROSSWALK_NAME, index=False, encoding="utf-8")


def blocked(outputs: Path, error: str) -> int:
    report = finish([{"name": "capa MGN verificada", "passed": False, "blocking": True, "detail": error}], {})
    report["status"] = "blocked_no_layer"
    report["error"] = error
    write_json(outputs / REPORT_NAME, report)
    print(f"[FALLA] {error}", file=sys.stderr)
    return 2


def run_real(root: Path) -> int:
    config = load_config(root)
    outputs = root / config["paths"]["outputs"]
    manifest_path = outputs / "mgn_download_manifest.json"
    if not manifest_path.exists():
        return blocked(outputs, "no existe outputs/mgn_download_manifest.json; corra 01_download_mgn.py")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("fixture") is True or manifest.get("status") != "complete" or manifest.get("claims_national_download") is not True:
        return blocked(outputs, f"el manifiesto no acredita la descarga nacional (status {manifest.get('status')})")
    layer_path = root / manifest.get("extracted_layer", "")
    if not layer_path.is_file():
        return blocked(outputs, f"no está la capa {manifest.get('extracted_layer')}")
    layer_sha = sha256_file(layer_path)
    if manifest.get("sha256") and manifest["sha256"] != layer_sha:
        return blocked(outputs, "la capa no coincide con el SHA256 del manifiesto; vuelva a correr 01_download_mgn.py")

    pdet_cfg = config["sources"]["pdet_list"]
    frame = gpd.read_file(layer_path)
    excel = pd.read_excel(root / pdet_cfg["file"], sheet_name=pdet_cfg["sheet"])
    report, crosswalk = validate(frame, excel, config=config)
    report.update(
        {
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "layer": manifest["extracted_layer"],
            "layer_sha256": layer_sha,
            "pdet_list": pdet_cfg["file"],
            "source_manifest": manifest_path.name,
        }
    )
    write_outputs(outputs, report, crosswalk)
    for item in report["checks"]:
        mark = "OK" if item["passed"] else ("FALLA" if item["blocking"] else "AVISO")
        print(f"[{mark}] {item['name']}: {item['detail']}")
    print(f"[{report['status']}] {report['checks_passed']}/{report['checks_total']}; resumen en {outputs / SUMMARY_NAME}")
    return 0 if report["status"] == "valid" else 1


# --- Self-check con figuras sintéticas -----------------------------------------

def _fixture_config(expected_features: int, expected_pdet: int, subregions: int) -> dict:
    return {
        "sources": {
            "mgn": {"source_crs": "EPSG:4686", "wfs": {"expected_feature_count": expected_features}},
            "pdet_list": {
                "code_column": "Código DANE Municipio",
                "expected_municipalities": expected_pdet,
                "expected_subregions": subregions,
            },
        }
    }


def _fixture_layer(rows: list[tuple], crs: str = "EPSG:4686") -> gpd.GeoDataFrame:
    columns = ["MPIO_CDPMP", "MPIO_CNMBR", "MPIO_NAREA", "DPTO_CCDGO", "MPIO_CCDGO", "geometry"]
    return gpd.GeoDataFrame(pd.DataFrame(rows, columns=columns), geometry="geometry", crs=crs)


def _fixture_excel(rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=["id", "Subregión PDET", "Código DANE Departamento", "Departamento", "Código DANE Municipio", "Municipio"],
    )


def run_self_check() -> int:
    from shapely.geometry import Point, Polygon

    results: list[tuple[str, bool]] = []

    def check(name: str, condition: bool) -> None:
        results.append((name, bool(condition)))
        print(f"[{'OK' if condition else 'FALLA'}] {name}")

    def failed(report: dict, fragment: str) -> bool:
        return any(fragment in name for name in report["failed_checks"])

    square = lambda x, y: box(x, y, x + 0.1, y + 0.1)  # noqa: E731
    bowtie = Polygon([(-74, 5), (-73.9, 5.1), (-73.9, 5), (-74, 5.1), (-74, 5)])
    good_layer = [
        ("05031", "AMALFI", 1210.0, "05", "031", square(-75, 6.9)),
        ("19050", "ARGELIA", 670.0, "19", "050", square(-77, 2.3)),
        ("99999", "OTRO", 10.0, "99", "999", square(-70, 4)),
    ]
    good_excel = [
        (1, "SUBREGIÓN A", 5, "ANTIOQUIA", 5031, "AMALFI"),
        (2, "SUBREGIÓN B", 19, "CAUCA", 19050, "ARGELIA"),
    ]
    config = _fixture_config(3, 2, 2)

    report, crosswalk = validate(_fixture_layer(good_layer), _fixture_excel(good_excel), config=config)
    check("FIXTURE capa y lista limpias: valid", report["status"] == "valid" and report["pdet_matched"] == 2)
    check("FIXTURE 5031 se rellena a 05031 y cruza", "05031" in set(crosswalk["mpio_code"]))

    excel = [(1, "SUBREGIÓN A", 5, "ANTIOQUIA", 5031, "AMALFÍ"), good_excel[1]]
    report, crosswalk = validate(_fixture_layer(good_layer), _fixture_excel(excel), config=config)
    check("FIXTURE nombre con tilde: aviso, no falla", report["status"] == "valid" and report["warnings"])
    check("FIXTURE nombre con tilde: tipo solo_tildes", crosswalk.set_index("mpio_code").loc["05031", "name_match"] == "solo_tildes")

    excel = good_excel + [(2, "SUBREGIÓN B", 19, "CAUCA", 19999, "FANTASMA")]
    report, _ = validate(_fixture_layer(good_layer), _fixture_excel(excel), config=_fixture_config(3, 3, 2))
    check("FIXTURE municipio PDET ausente del MGN", failed(report, "están en el MGN") and report["pdet_missing_codes"] == ["19999"])

    report, _ = validate(_fixture_layer(good_layer), _fixture_excel(good_excel + [good_excel[0]]), config=_fixture_config(3, 3, 2))
    check("FIXTURE código repetido en la lista PDET", failed(report, "lista PDET") and report["pdet_duplicate_codes"] == ["05031"])

    layer = good_layer + [("05031", "AMALFI BIS", 5.0, "05", "031", square(-75, 7.2))]
    report, _ = validate(_fixture_layer(layer), _fixture_excel(good_excel), config=_fixture_config(4, 2, 2))
    check("FIXTURE código repetido en el MGN", failed(report, "repetidos en el MGN") and report["mgn_duplicate_codes"] == ["05031"])

    layer = [good_layer[0], ("19050", "ARGELIA", 670.0, "05", "050", square(-77, 2.3)), good_layer[2]]
    report, _ = validate(_fixture_layer(layer), _fixture_excel(good_excel), config=config)
    check("FIXTURE prefijo distinto de DPTO_CCDGO", failed(report, "prefijo de MPIO_CDPMP") and failed(report, "departamento del Excel"))

    layer = [good_layer[0], good_layer[1], ("ABC", "SIN CÓDIGO", 1.0, "99", "999", square(-70, 4))]
    report, _ = validate(_fixture_layer(layer), _fixture_excel(good_excel), config=config)
    check("FIXTURE código no numérico", failed(report, "5 dígitos"))

    layer = [good_layer[0], ("19050", "ARGELIA", 670.0, "19", "050", bowtie), good_layer[2]]
    report, crosswalk = validate(_fixture_layer(layer), _fixture_excel(good_excel), config=config)
    check("FIXTURE polígono autointersecado en un PDET", failed(report, "geometrías PDET") and report["pdet_invalid_geometries"] == ["19050"])
    check("FIXTURE motivo de invalidez en el crosswalk", "Self-intersection" in crosswalk.set_index("mpio_code").loc["19050", "geometry_problem"])

    layer = good_layer[:2] + [("99999", "OTRO", 10.0, "99", "999", bowtie)]
    report, _ = validate(_fixture_layer(layer), _fixture_excel(good_excel), config=config)
    check("FIXTURE inválida fuera de los PDET: solo aviso", report["status"] == "valid" and report["mgn_invalid_geometries"] == 1)

    layer = [good_layer[0], ("19050", "ARGELIA", 670.0, "19", "050", Point(-77, 2.3)), good_layer[2]]
    report, _ = validate(_fixture_layer(layer), _fixture_excel(good_excel), config=config)
    check("FIXTURE geometría no poligonal", failed(report, "geometrías PDET"))

    layer = [good_layer[0], ("19050", "ARGELIA", 670.0, "19", "050", square(2.3, -77)), good_layer[2]]
    report, _ = validate(_fixture_layer(layer), _fixture_excel(good_excel), config=config)
    check("FIXTURE ejes lat/lon invertidos", failed(report, "ventana de Colombia"))

    report, _ = validate(_fixture_layer(good_layer, crs="EPSG:3857"), _fixture_excel(good_excel), config=config)
    check("FIXTURE CRS distinto", failed(report, "CRS"))

    report, _ = validate(_fixture_layer(good_layer[:2]), _fixture_excel(good_excel), config=config)
    check("FIXTURE capa incompleta", failed(report, "capa nacional"))

    report, _ = validate(_fixture_layer(good_layer).drop(columns="MPIO_NAREA"), _fixture_excel(good_excel), config=config)
    check("FIXTURE falta un campo obligatorio", report["status"] == "invalid" and failed(report, "campos obligatorios"))

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "outputs").mkdir()
        (root / "config.yaml").write_text("paths:\n  outputs: outputs\n", encoding="utf-8")
        code = run_real(root)
        stored = json.loads((root / "outputs" / REPORT_NAME).read_text(encoding="utf-8"))
        check("FIXTURE sin manifiesto: salida 2 y blocked_no_layer", code == 2 and stored["status"] == "blocked_no_layer")
        (root / "outputs/mgn_download_manifest.json").write_text(json.dumps({"status": "blocked"}), encoding="utf-8")
        check("FIXTURE manifiesto bloqueado: salida 2", run_real(root) == 2)

    passed = sum(ok for _, ok in results)
    print(f"FIXTURE self-check validación: {passed}/{len(results)}")
    return 0 if passed == len(results) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--self-check", action="store_true", help="prueba con figuras sintéticas; no lee el MGN")
    args = parser.parse_args()
    sys.exit(run_self_check() if args.self_check else run_real(ROOT))


if __name__ == "__main__":
    main()
