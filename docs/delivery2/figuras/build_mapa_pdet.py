"""Mapa de los 170 municipios PDET validados sobre la capa nacional del MGN.

Lee la capa del manifiesto y ``outputs/pdet_mgn_crosswalk.csv`` de
``01_validate_mgn.py``. Escribe ``docs/delivery2/figuras/mapa_pdet_validacion.png``.

Uso, desde la raíz del repositorio:
    python docs/delivery2/figuras/build_mapa_pdet.py
"""
import json
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).with_name("mapa_pdet_validacion.png")

manifest = json.loads((ROOT / "outputs/mgn_download_manifest.json").read_text(encoding="utf-8"))
layer = gpd.read_file(ROOT / manifest["extracted_layer"])
crosswalk = pd.read_csv(ROOT / "outputs/pdet_mgn_crosswalk.csv", dtype={"mpio_code": str})

pdet = layer.merge(crosswalk, left_on="MPIO_CDPMP", right_on="mpio_code")
subregions = sorted(pdet["subregion_id"].unique())

fig, ax = plt.subplots(figsize=(7, 8.4))
layer.plot(ax=ax, color="#ececec", edgecolor="#bdbdbd", linewidth=0.15)
pdet.plot(ax=ax, column="subregion_id", categorical=True, cmap="tab20", edgecolor="#333333", linewidth=0.2)
ax.set_xlim(-79.2, -66.7)
ax.set_ylim(-4.4, 12.6)
ax.set_axis_off()
ax.set_title(
    f"{len(pdet)} municipios PDET cruzados con el MGN 2025 ({len(subregions)} subregiones)",
    fontsize=10,
)
fig.tight_layout()
fig.savefig(OUT, dpi=200)
print(f"[OK] {OUT.relative_to(ROOT)}: {len(pdet)} municipios")
