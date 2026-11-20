"""Corre el análisis completo de la Entrega 4 en orden y se detiene ante el primer error.

Parte de la base ya cargada (Entregas 2 y 3) y ejecuta:

 1. ``00_check_environment.py``             Python y dependencias
 2. ``00_init_db.py --building-indexes``    esquema e índices (idempotente)
 3. ``02_verify_spatial.py``                170 municipios y su índice 2dsphere
 4. ``04_load_buildings.py --verify-only``  Microsoft y Google cargados sin duplicados
 5. ``06_rooftop_stats.py --passes 2``      estadísticas de Microsoft y de Google
 6. ``10_validate_analysis.py``             validación independiente
 7. ``07``, ``08`` y ``09``                  resumen, figuras y tablas (se omiten con --no-report)
 8. ``latexmk``                             informe PDF (solo con --pdf)

Cada paso deja su salida en ``<run_dir>/run.log``. El manifiesto
``<run_dir>/run_manifest.json`` registra comando, inicio, fin, duración y
código de salida de cada paso; parámetros de ``config.yaml``; versiones de
Python, paquetes, MongoDB y del repositorio; y la procedencia de cada archivo
de salida (SHA256 y paso que lo cambió).

Uso:
    python scripts/11_run_analysis.py                 # run_dir = outputs/validation/runs/<fecha>
    python scripts/11_run_analysis.py --no-report --run-dir outputs/validation/runs/prueba

Salida: 0 todos los pasos en OK; si no, el código del paso que falló.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from entrega2_contracts import load_config, sha256_file  # noqa: E402

SCRIPT_VERSION = "entrega4-run-v1"
# Archivos cuya procedencia se registra (salidas de los pasos).
TRACKED = ["outputs", "docs/delivery4/figuras", "docs/delivery4/entrega4_analysis_tables.md",
           "docs/delivery4/Entrega4_Analisis_Techos.pdf"]


def steps(run_dir: str, report: bool, pdf: bool) -> list[tuple[str, list[str], Path]]:
    py = sys.executable
    plan = [
        ("entorno", [py, "scripts/00_check_environment.py"], ROOT),
        ("esquema_e_indices", [py, "scripts/00_init_db.py", "--building-indexes"], ROOT),
        ("verificacion_municipios", [py, "scripts/02_verify_spatial.py",
                                     "--report", f"{run_dir}/municipalities_spatial_verification.json"], ROOT),
        ("verificacion_buildings_ms", [py, "scripts/04_load_buildings.py", "--source", "ms", "--verify-only"], ROOT),
        ("verificacion_buildings_google", [py, "scripts/04_load_buildings.py", "--source", "google",
                                           "--verify-only"], ROOT),
        ("rooftop_stats_ms", [py, "scripts/06_rooftop_stats.py", "--source", "ms", "--passes", "2"], ROOT),
        ("rooftop_stats_google", [py, "scripts/06_rooftop_stats.py", "--source", "google", "--passes", "2"], ROOT),
        ("validacion_independiente", [py, "scripts/10_validate_analysis.py"], ROOT),
    ]
    if report:
        plan += [
            ("resumen_analisis", [py, "scripts/07_entrega4_analysis.py"], ROOT),
            ("figuras", [py, "scripts/08_entrega4_visualizations.py"], ROOT),
            ("tablas", [py, "scripts/09_entrega4_tables.py"], ROOT),
        ]
    if pdf:
        plan.append(("informe_pdf", ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error",
                                     "entrega4_informe.tex"], ROOT / "docs" / "delivery4"))
    return plan


def snapshot() -> dict[str, str]:
    """SHA256 de los archivos de salida, para saber qué cambió cada paso."""
    hashes = {}
    for item in TRACKED:
        path = ROOT / item
        files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else []
        for f in files:
            rel = f.relative_to(ROOT).as_posix()
            if "/validation/runs/" not in f"/{rel}" and f.name != ".gitkeep":
                hashes[rel] = sha256_file(f)
    return hashes


def git(*args: str) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def content_fingerprint(path: Path, ignore: tuple[str, ...] = ("computed_at",)) -> str | None:
    """SHA256 del CSV sin las columnas de fecha: igual entre dos corridas si los valores son iguales."""
    if not path.is_file():
        return None
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = [f for f in reader.fieldnames if f not in ignore]
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(fields)
        for row in reader:
            writer.writerow([row[f] for f in fields])
    return hashlib.sha256(out.getvalue().encode("utf-8")).hexdigest()


def environment(config: dict) -> dict:
    uri = os.environ.get("MONGO_URI", config["mongo"]["uri"])
    packages = {}
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        name = line.split(">=")[0].strip()
        if name and not name.startswith("#"):
            try:
                packages[name] = version(name)
            except PackageNotFoundError:
                packages[name] = None
    for extra in ("numpy",):
        try:
            packages[extra] = version(extra)
        except PackageNotFoundError:
            pass
    info = {
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "packages": packages,
        # Sin credenciales: solo host y puerto.
        "mongo_host": urlsplit(uri).hostname, "mongo_port": urlsplit(uri).port,
        "mongo_database": config["mongo"]["database"],
        "git_commit": git("rev-parse", "HEAD"),
        "git_branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_dirty_files": (git("status", "--porcelain") or "").splitlines(),
    }
    try:
        from pymongo import MongoClient

        with MongoClient(uri, serverSelectionTimeoutMS=5000) as client:
            db = client[config["mongo"]["database"]]
            info["mongo_version"] = client.server_info().get("version")
            info["collections"] = {n: db[n].estimated_document_count() for n in sorted(db.list_collection_names())}
    except Exception as exc:  # noqa: BLE001 - se registra y el paso de esquema fallará con su propio error
        info["mongo_error"] = type(exc).__name__
    return info


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-dir", help="carpeta de la corrida, relativa al repositorio")
    parser.add_argument("--no-report", action="store_true", help="omitir 07, 08 y 09 (resumen, figuras y tablas)")
    parser.add_argument("--pdf", action="store_true", help="compilar también el informe con latexmk")
    args = parser.parse_args(argv)

    started = datetime.now(timezone.utc)
    run_id = started.strftime("%Y%m%dT%H%M%SZ")
    run_dir = args.run_dir or f"outputs/validation/runs/{run_id}"
    out = ROOT / run_dir
    out.mkdir(parents=True, exist_ok=True)
    config = load_config(ROOT)
    manifest = {
        "role": "entrega4-run-manifest",
        "script_version": SCRIPT_VERSION,
        "run_id": run_id,
        "started_at": started.isoformat(timespec="seconds"),
        "command": " ".join([Path(sys.executable).name, "scripts/11_run_analysis.py", *(argv or sys.argv[1:])]),
        "parameters": {"analysis": config["analysis"], "config_sha256": sha256_file(ROOT / "config.yaml"),
                       "report_steps": not args.no_report, "pdf": args.pdf},
        "environment": environment(config),
        "steps": [],
    }
    before = snapshot()
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    exit_code = 0
    with (out / "run.log").open("w", encoding="utf-8") as log:
        for number, (name, cmd, cwd) in enumerate(steps(run_dir, not args.no_report, args.pdf), start=1):
            header = f"\n=== [{number}] {name}: {' '.join(Path(c).name if c == sys.executable else c for c in cmd)}"
            print(header, flush=True)
            log.write(header + "\n")
            step_start = datetime.now(timezone.utc)
            proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace")
            for line in proc.stdout:
                sys.stdout.write(line)
                log.write(line)
            proc.wait()
            # Reloj de pared: perf_counter de macOS no cuenta el tiempo en reposo del equipo.
            step_end = datetime.now(timezone.utc)
            seconds = round((step_end - step_start).total_seconds(), 2)
            after = snapshot()
            changed = sorted(k for k in after if before.get(k) != after[k])
            manifest["steps"].append({
                "step": number, "name": name,
                "command": [Path(c).name if c == sys.executable else c for c in cmd],
                "cwd": cwd.relative_to(ROOT).as_posix() or ".",
                "started_at": step_start.isoformat(timespec="seconds"),
                "finished_at": step_end.isoformat(timespec="seconds"),
                "duration_s": seconds, "exit_code": proc.returncode,
                "outputs_changed": changed,
            })
            before = after
            status = "OK" if proc.returncode == 0 else f"FALLA (código {proc.returncode})"
            print(f"--- [{number}] {name}: {status} en {seconds} s", flush=True)
            log.write(f"--- [{number}] {name}: {status} en {seconds} s\n")
            log.flush()
            if proc.returncode != 0:
                exit_code = proc.returncode
                break

    finished = datetime.now(timezone.utc)
    stats_csv = config["analysis"]["rooftop_stats"]["csv"]
    manifest.update({
        "finished_at": finished.isoformat(timespec="seconds"),
        "duration_s": round((finished - started).total_seconds(), 2),
        "status": "completed" if exit_code == 0 else "stopped_on_error",
        "failed_step": None if exit_code == 0 else manifest["steps"][-1]["name"],
        "provenance": {
            path: {"sha256": sha,
                   "produced_by": next((s["name"] for s in reversed(manifest["steps"]) if path in s["outputs_changed"]),
                                       None)}
            for path, sha in sorted(snapshot().items())},
        # Solo si la corrida terminó: si no, los CSV en disco no son de esta corrida.
        "result_fingerprints": {
            d: content_fingerprint(ROOT / stats_csv.format(source=d)) for d in ("ms", "google")}
        if exit_code == 0 else None,
    })
    (out / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                           encoding="utf-8", newline="\n")
    print(f"\n[{manifest['status']}] {len(manifest['steps'])} pasos en {manifest['duration_s']} s · "
          f"manifiesto: {run_dir}/run_manifest.json")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
