#!/bin/bash
# Entrega 4: análisis completo en orden, deteniéndose ante el primer error (tramo de José).
# Pasos, tiempos, versiones y procedencia: scripts/11_run_analysis.py.
#
# Uso: bash scripts/run_full_analysis.sh [--no-report] [--pdf] [--run-dir RUTA]

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ -d ".venv" ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

exec python scripts/11_run_analysis.py "$@"
