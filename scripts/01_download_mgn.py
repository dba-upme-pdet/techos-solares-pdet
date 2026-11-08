"""Descarga el MGN 2025 y extrae la capa municipal (Entrega 2, Derek).

Lee ``sources.mgn`` y ``paths`` de ``config.yaml``. La URL de partida es la
página oficial ya configurada. Un ZIP solo se usa si esa página lo enlaza,
o si ``sources.mgn.file_url`` ya trae una URL observada. No se inventa un
enlace y no se desactiva la verificación TLS.

Uso:
    python scripts/01_download_mgn.py
    python scripts/01_download_mgn.py --self-check
"""
from __future__ import annotations

import argparse
import re
import sys
import traceback
from pathlib import Path

import geopandas as gpd
import requests

from entrega2_contracts import (
    CONTRACT_VERSION,
    REQUIRED_MGN_FIELDS,
    ContractError,
    crs_matches,
    epsg_label,
    load_config,
    parse_area_unit,
    select_mgn2025_zip,
    sha256_file,
    write_json,
)

ROOT = Path(__file__).resolve().parents[1]
VECTOR_SUFFIXES = {".shp", ".gpkg"}
METADATA_SUFFIXES = {".xml", ".txt", ".html", ".htm", ".qmd"}


def fetch_text(url: str) -> str:
    response = requests.get(
        url,
        timeout=90,
        verify=True,
        headers={"User-Agent": "techos-solares-pdet-entrega2"},
    )
    response.raise_for_status()
    response.encoding = response.encoding or "utf-8"
    return response.text


def download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_suffix(dest.suffix + ".partial")
    with requests.get(
        url,
        timeout=120,
        verify=True,
        stream=True,
        headers={"User-Agent": "techos-solares-pdet-entrega2"},
    ) as response:
        response.raise_for_status()
        with temporary.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    temporary.replace(dest)


def metadata_unit(folder: Path) -> tuple[str | None, str | None]:
    found: list[tuple[str, str]] = []
    if not folder.exists():
        return None, None
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in METADATA_SUFFIXES:
            continue
        if path.stat().st_size > 5_000_000:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        unit = parse_area_unit(text)
        if unit:
            found.append((unit, path.name))
    units = {unit for unit, _ in found}
    if len(units) > 1:
        raise ContractError("los metadatos de la capa declaran más de una unidad para MPIO_NAREA")
    if not found:
        return None, None
    return found[0]


def inspect_vectors(folder: Path) -> tuple[Path | None, object | None, list[dict]]:
    notes = []
    matches: list[tuple[Path, object]] = []
    for path in sorted(folder.rglob("*")):
        if path.suffix.lower() not in VECTOR_SUFFIXES:
            continue
        try:
            frame = gpd.read_file(path)
        except Exception as exc:
            notes.append({"path": path.name, "readable": False, "error": str(exc)})
            continue
        columns = [str(column) for column in frame.columns]
        notes.append(
            {
                "path": path.name,
                "readable": True,
                "crs": epsg_label(frame.crs),
                "columns": columns,
                "features": int(len(frame)),
            }
        )
        if set(REQUIRED_MGN_FIELDS).issubset(columns):
            matches.append((path, frame))
    if not matches:
        return None, None, notes
    preferred = [item for item in matches if re.search(r"mpio|municip", item[0].name, re.IGNORECASE)]
    chosen = preferred if len(preferred) == 1 else matches
    if len(chosen) != 1:
        names = ", ".join(path.name for path, _ in chosen)
        raise ContractError(f"hay varias capas con los campos municipales: {names}")
    return chosen[0][0], chosen[0][1], notes


def manifest_from_layer(
    *,
    frame,
    layer_path: Path,
    root: Path,
    expected_crs: str,
    source_page: str,
    file_url: str,
    archive_path: Path | None,
    fixture: bool,
    area_unit: str | None,
    area_unit_source: str | None,
) -> dict:
    missing = [field for field in REQUIRED_MGN_FIELDS if field not in frame.columns]
    nulls = int(frame.geometry.isna().sum()) if frame.geometry is not None else len(frame)
    geometry_types = sorted({geom.geom_type for geom in frame.geometry if geom is not None})
    errors = []
    if missing:
        errors.append("faltan campos: " + ", ".join(missing))
    if len(frame) == 0:
        errors.append("la capa no tiene registros")
    if not crs_matches(frame.crs, expected_crs):
        errors.append(f"CRS {epsg_label(frame.crs) or 'ausente'} no equivale a {expected_crs}")
    archive_hash = sha256_file(archive_path) if archive_path and archive_path.exists() else None
    return {
        "contract": CONTRACT_VERSION,
        "role": "download-manifest",
        "status": "complete" if not errors else "invalid",
        "fixture": fixture,
        "errors": errors,
        "source_page": source_page,
        "resolved_file_url": file_url,
        "filename": archive_path.name if archive_path else None,
        "bytes": archive_path.stat().st_size if archive_path and archive_path.exists() else None,
        "sha256": archive_hash,
        "layer_name": layer_path.name,
        "extracted_layer": layer_path.resolve().relative_to(root.resolve()).as_posix(),
        "crs_expected": expected_crs,
        "crs_epsg": epsg_label(frame.crs),
        "crs_equals_expected": crs_matches(frame.crs, expected_crs),
        "feature_count": int(len(frame)),
        "geometry_types": geometry_types,
        "columns": [str(column) for column in frame.columns if column != "geometry"],
        "required_fields_present": {field: field in frame.columns for field in REQUIRED_MGN_FIELDS},
        "null_geometry_count": nulls,
        "readable": True,
        "area_unit": area_unit,
        "area_unit_source": area_unit_source,
        "claims_national_download": not fixture and not errors,
    }


def write_attempt(path: Path, *, page: str, status: str, error: str) -> None:
    write_json(
        path,
        {
            "contract": CONTRACT_VERSION,
            "role": "download-attempt",
            "status": status,
            "fixture": False,
            "source_page": page,
            "resolved_file_url": None,
            "layer_verified": False,
            "claims_national_download": False,
            "municipalities_prepared": 0,
            "error": error,
        },
    )


def run_real(root: Path) -> int:
    config = load_config(root)
    mgn = config["sources"]["mgn"]
    page = mgn["url"]
    expected_crs = mgn["source_crs"]
    raw_dir = root / config["paths"]["raw_data"] / "mgn2025"
    outputs = root / config["paths"]["outputs"]
    attempt = outputs / "mgn_download_attempt.json"
    manifest_path = outputs / "mgn_download_manifest.json"
    configured = (mgn.get("file_url") or "").strip()
    try:
        if configured:
            file_url = configured
        else:
            html = fetch_text(page)
            file_url = select_mgn2025_zip(page, html)
        archive = raw_dir / Path(file_url.split("?", 1)[0]).name
        existing = None
        if manifest_path.exists():
            import json

            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            archive.exists()
            and existing
            and existing.get("status") == "complete"
            and existing.get("fixture") is False
            and existing.get("sha256") == sha256_file(archive)
        ):
            print(f"[OK] archivo ya presente, se revalida {archive.name}")
        else:
            print(f"[descarga] {file_url}")
            download_file(file_url, archive)
        extract_dir = raw_dir / "extract"
        extract_dir.mkdir(parents=True, exist_ok=True)
        import zipfile

        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(extract_dir)
        layer_path, frame, _notes = inspect_vectors(extract_dir)
        if layer_path is None or frame is None:
            raise ContractError("el ZIP no tiene una capa con MPIO_CDPMP, MPIO_CNMBR, MPIO_NAREA y DPTO_CCDGO")
        unit, unit_source = metadata_unit(layer_path.parent)
        manifest = manifest_from_layer(
            frame=frame,
            layer_path=layer_path,
            root=root,
            expected_crs=expected_crs,
            source_page=page,
            file_url=file_url,
            archive_path=archive,
            fixture=False,
            area_unit=unit,
            area_unit_source=unit_source,
        )
        if manifest["errors"]:
            manifest["claims_national_download"] = False
            write_json(manifest_path, manifest)
            write_attempt(attempt, page=page, status="invalid", error="; ".join(manifest["errors"]))
            print("[FALLA] " + "; ".join(manifest["errors"]))
            return 1
        write_json(manifest_path, manifest)
        if attempt.exists():
            attempt.unlink()
        print(
            f"[OK] capa {manifest['layer_name']}: {manifest['feature_count']} registros, "
            f"CRS {manifest['crs_epsg']}, unidad de área {manifest['area_unit'] or 'no declarada'}"
        )
        return 0
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        write_attempt(attempt, page=page, status="blocked", error=message)
        print(f"[FALLA] {message}", file=sys.stderr)
        return 2


def _square(minx: float, miny: float, maxx: float, maxy: float):
    from shapely.geometry import Polygon

    return Polygon([(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy), (minx, miny)])


def _write_layer(folder: Path, frame, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    frame.to_file(path)
    return path


def run_self_check() -> int:
    import tempfile

    checks: dict[str, bool] = {}

    def check(name: str, condition: bool) -> None:
        checks[name] = bool(condition)
        print(f"[{'OK' if condition else 'FALLA'}] {name}")

    html = """
    <html><body>
      <a href="https://fixture.invalid/otro.zip">Otra cosa</a>
      <a href="https://fixture.invalid/MGN2025_municipal.zip">MGN2025 municipal</a>
      <a href="/descargas/MGN2025_Colombia.zip">Versión MGN2025. Todos los niveles geográficos</a>
    </body></html>
    """
    try:
        chosen = select_mgn2025_zip("https://fixture.invalid/catalogo/", html)
        check("elige el ZIP MGN2025 de todos los niveles presente en el HTML", chosen.endswith("MGN2025_Colombia.zip"))
    except Exception as exc:
        check(f"elige el ZIP MGN2025 de todos los niveles presente en el HTML ({exc})", False)

    try:
        select_mgn2025_zip("https://fixture.invalid/catalogo/", "<a href='https://fixture.invalid/otro.zip'>nada</a>")
        check("rechaza una página sin ZIP MGN2025", False)
    except ContractError:
        check("rechaza una página sin ZIP MGN2025", True)

    ambiguous = """
      <a href="https://fixture.invalid/a-MGN2025.zip">MGN2025 uno</a>
      <a href="https://fixture.invalid/b-MGN2025.zip">MGN2025 dos</a>
    """
    try:
        select_mgn2025_zip("https://fixture.invalid/", ambiguous)
        check("rechaza dos ZIP MGN2025 sin un producto único", False)
    except ContractError:
        check("rechaza dos ZIP MGN2025 sin un producto único", True)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        valid = gpd.GeoDataFrame(
            {
                "MPIO_CDPMP": ["19050"],
                "MPIO_CNMBR": ["ARGELIA"],
                "MPIO_NAREA": [10.0],
                "DPTO_CCDGO": ["19"],
            },
            geometry=[_square(-76.5, 2.2, -76.4, 2.3)],
            crs="EPSG:4686",
        )
        layer = _write_layer(root, valid, "muni.shp")
        (layer.parent / "muni.xml").write_text(
            "<field><name>MPIO_NAREA</name><uom>metros cuadrados</uom></field>",
            encoding="utf-8",
        )
        unit, source = metadata_unit(layer.parent)
        reloaded = gpd.read_file(layer)
        manifest = manifest_from_layer(
            frame=reloaded,
            layer_path=layer,
            root=root,
            expected_crs="EPSG:4686",
            source_page="fixture",
            file_url="fixture://local",
            archive_path=None,
            fixture=True,
            area_unit=unit,
            area_unit_source=source,
        )
        check("capa fixture legible en EPSG:4686", manifest["status"] == "complete" and manifest["crs_equals_expected"])
        check("unidad leída del XML fixture, no inventada", manifest["area_unit"] == "m2")
        check("el manifiesto fixture no afirma una descarga nacional", manifest["claims_national_download"] is False)

        missing_crs = valid.copy()
        missing_crs = missing_crs.set_crs(None, allow_override=True)
        no_crs_path = _write_layer(root / "nocrs", missing_crs, "nocrs.shp")
        prj = no_crs_path.with_suffix(".prj")
        if prj.exists():
            prj.unlink()
        no_crs = gpd.read_file(no_crs_path)
        bad_crs = manifest_from_layer(
            frame=no_crs,
            layer_path=no_crs_path,
            root=root,
            expected_crs="EPSG:4686",
            source_page="fixture",
            file_url="fixture://local",
            archive_path=None,
            fixture=True,
            area_unit=None,
            area_unit_source=None,
        )
        check("falla si el CRS no está presente", bad_crs["status"] == "invalid" and bad_crs["crs_equals_expected"] is False)

        wrong = valid.to_crs("EPSG:4326")
        wrong_path = _write_layer(root / "wrong", wrong, "wrong.shp")
        wrong_frame = gpd.read_file(wrong_path)
        wrong_manifest = manifest_from_layer(
            frame=wrong_frame,
            layer_path=wrong_path,
            root=root,
            expected_crs="EPSG:4686",
            source_page="fixture",
            file_url="fixture://local",
            archive_path=None,
            fixture=True,
            area_unit=None,
            area_unit_source=None,
        )
        check("falla si el CRS es EPSG:4326 y se esperaba EPSG:4686", wrong_manifest["status"] == "invalid")

        incomplete = valid.drop(columns=["MPIO_NAREA"])
        incomplete_path = _write_layer(root / "miss", incomplete, "miss.shp")
        _layer, _frame, notes = inspect_vectors(incomplete_path.parent)
        check("no elige una capa sin MPIO_NAREA", _layer is None and notes and notes[0]["readable"])

        broken_dir = root / "roto"
        broken_dir.mkdir()
        (broken_dir / "roto.shp").write_bytes(b"esto no es un shapefile")
        _layer, _frame, notes = inspect_vectors(broken_dir)
        unreadable = [note for note in notes if note["path"] == "roto.shp"]
        check("un archivo ilegible no se da por válido", _layer is None and bool(unreadable) and unreadable[0]["readable"] is False)

    passed = all(checks.values())
    print(f"{'FIXTURE' if passed else 'FALLA'} self-check descarga: {sum(checks.values())}/{len(checks)}")
    return 0 if passed else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--self-check", action="store_true", help="pruebas con fixtures etiquetados; no descarga el MGN")
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
