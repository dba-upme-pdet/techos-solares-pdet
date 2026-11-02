
"""Verifica Python 3.11+ y que estén instaladas las dependencias de requirements.txt."""

import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

reqs = [
    line.split(">=")[0].strip()
    for line in (ROOT / "requirements.txt").read_text().splitlines()
    if line.strip() and not line.startswith("#")
]

ok = sys.version_info >= (3, 11)

print(f"[{'OK' if ok else 'FALLA'}] Python {sys.version.split()[0]} (se requiere 3.11+)")

for pkg in reqs:
    try:
        print(f"[OK]    {pkg} {version(pkg)}")
    except PackageNotFoundError:
        print(f"[FALTA] {pkg}  ->  pip install -r requirements.txt")
        ok = False

sys.exit(0 if ok else 1)
