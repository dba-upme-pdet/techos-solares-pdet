"""Verifica la lista oficial de municipios PDET antes de cargarla (Fase 0)."""
import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
pdet = cfg["sources"]["pdet_list"]

df = pd.read_excel(ROOT / pdet["file"], sheet_name=pdet["sheet"])
df["mpio_code"] = df[pdet["code_column"]].astype(int).astype(str).str.zfill(5)
df["dpto_code"] = df["Código DANE Departamento"].astype(int).astype(str).str.zfill(2)

checks = {
    "170 municipios": len(df) == pdet["expected_municipalities"],
    "códigos únicos": df["mpio_code"].is_unique,
    "16 subregiones": df["id"].nunique() == pdet["expected_subregions"],
    "códigos de 5 dígitos": df["mpio_code"].str.fullmatch(r"\d{5}").all(),
    "sin nulos": not df.isna().any().any(),
    "prefijo de departamento": (df["mpio_code"].str[:2] == df["dpto_code"]).all(),
}
summary = df.groupby(["id", "Subregión PDET"]).size().reset_index(name="municipios")
out = ROOT / cfg["paths"]["outputs"] / "pdet_subregions_summary.csv"
summary.to_csv(out, index=False, encoding="utf-8")

for name, ok in checks.items():
    print(f"[{'OK' if ok else 'FALLA'}] {name}")
print(summary.to_string(index=False))
sys.exit(0 if all(checks.values()) else 1)
