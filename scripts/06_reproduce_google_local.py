"""Repone entradas locales ausentes con scripts oficiales y reportes aislados.

No descarga ni calcula estadísticas. Solo se usa cuando el MongoDB local está
vacío y se conservan los ocho originales y la capa PDET verificados. Después:
python scripts/06_rooftop_stats.py --source google --passes 2
"""
import importlib
import json
import os
import shutil
import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path

import yaml
from pymongo import MongoClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from entrega2_contracts import ContractError, load_config
from entrega3_contracts import load_pdet_layer, verify_partition_file, download_manifest_problems


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--load-prepared", action="store_true", help="reutiliza la preparación aislada ya terminada")
    parser.add_argument("--resume-buildings", action="store_true", help="reanuda la carga idempotente de esta reproducción local")
    options = parser.parse_args()
    config = load_config(ROOT)
    local = ROOT / "data/delivery4_google_reproduction"
    manifest_path = ROOT / config["sources"]["google"]["manifest"]
    manifest = json.loads(manifest_path.read_text())
    problems = download_manifest_problems(manifest, "google")
    if problems:
        raise ContractError("; ".join(problems))
    for part in manifest["partitions"]:
        verify_partition_file(ROOT, part)
    load_pdet_layer(ROOT, config["processing"]["buildings"]["pdet_input"],
                    config["processing"]["buildings"]["pdet_input_report"], 170)
    print("[OK] SHA256 de los ocho originales y de la capa de 170 municipios", flush=True)
    with MongoClient(os.environ.get("MONGO_URI", config["mongo"]["uri"]), serverSelectionTimeoutMS=5000) as client:
        client.admin.command("ping")
        db = client[config["mongo"]["database"]]
        # Este auxiliar de recuperación no reemplaza entradas ni resultados existentes.
        if options.resume_buildings:
            previous = json.loads((local / "outputs/municipalities_load_report.json").read_text())
            expected = json.loads((ROOT / config["processing"]["buildings"]["pdet_input_report"]).read_text())["ids"]
            if (previous.get("status") != "loaded" or db.rooftop_stats.count_documents({})
                    or set(db.municipalities.distinct("_id")) != set(expected)
                    or db.buildings.count_documents({"dataset_id": {"$ne": "google"}}, limit=1)):
                raise ContractError("la base no corresponde a esta reproducción local; no se reanuda")
        elif any(db[name].count_documents({}, limit=1) for name in ("municipalities", "buildings", "rooftop_stats")):
            raise ContractError("recuperación solo para base local vacía; reutilice/verifique los datos existentes")
    (local / "data/processed").mkdir(parents=True, exist_ok=True)
    (local / "outputs").mkdir(exist_ok=True)
    for link, target in ((local / "data/raw", ROOT / "data/raw"),
                         (local / "data/processed/municipalities.geojsonl", ROOT / config["processing"]["buildings"]["pdet_input"]),
                         (local / "resources", ROOT / "resources")):
        if not link.exists():
            link.symlink_to(target, target_is_directory=target.is_dir())
    (local / "config.yaml").write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
    for rel in (config["sources"]["google"]["manifest"], config["processing"]["buildings"]["pdet_input_report"],
                config["analysis"]["comparison"]["municipalities"]):
        destination = local / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, destination)
    if not options.load_prepared and not options.resume_buildings:
        prepare = importlib.import_module("03_prepare_buildings")
        args = Namespace(source="google", workers=4, partitions=None, without_pdet_selection=False, check_records=False)
        result = prepare.run(local, args)
        if result:
            return result
    # Los módulos oficiales ya están importados desde el repositorio; solo cambia
    # su raíz de ejecución para aislar archivos y conservar los reportes históricos.
    if not options.resume_buildings:
        municipalities = importlib.import_module("02_load_municipalities")
        municipalities.ROOT = local
        result = municipalities.run_real(Namespace(prune=False, allow_input_mismatch=False))
        if result:
            return result
    buildings = importlib.import_module("04_load_buildings")
    buildings.ROOT = local
    # Tolerancia de conexión local ante recuperación del contenedor; no cambia
    # filtros, documentos, validadores, lotes ni lógica del cargador compartido.
    def local_connect(cfg):
        client = MongoClient(os.environ.get("MONGO_URI", cfg["mongo"]["uri"]),
                             serverSelectionTimeoutMS=30000, tz_aware=True)
        client.admin.command("ping")
        return client
    buildings.connect = local_connect
    result = buildings.run_real(Namespace(source="google", passes=1, batch_size=0, partitions=None))
    print(f"Reportes locales de reproducción: {local / 'outputs'}", flush=True)
    return result


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ContractError as exc:
        print(f"[FALLA] {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        # No se imprime texto de excepciones de conexión que pueda incluir credenciales.
        print(f"[FALLA] reproducción local: {type(exc).__name__}", file=sys.stderr)
        sys.exit(1)
