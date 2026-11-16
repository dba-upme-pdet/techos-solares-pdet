#!/usr/bin/env bash
# Genera el informe de la Entrega 3 desde la raíz del repositorio:  docs/delivery3/informe/build.sh
# Requiere python3 con matplotlib, pandoc, mermaid-cli (mmdc) y chromium.
set -euo pipefail
raiz=$(git rev-parse --show-toplevel); aqui="$raiz/docs/delivery3/informe"; tmp=$(mktemp -d)
python3 "$raiz/scripts/05_eda_buildings.py"
python3 "$aqui/ensamblar.py" "$raiz/docs/delivery3" "$aqui/head.md" "$tmp" > "$tmp/entrega3.md"
for m in "$tmp"/diagrama*.mmd; do [ -e "$m" ] && mmdc -q -i "$m" -o "${m%.mmd}.png" -s 3 -b white; done
cp "$aqui/style.css" "$tmp/" && cp -r "$raiz/docs/delivery3/figuras" "$tmp/"
(cd "$tmp" && pandoc entrega3.md -s --toc --toc-depth=1 -M toc-title=Contenido --embed-resources --css style.css -o entrega3.html)
chromium --headless --no-sandbox --disable-gpu --no-pdf-header-footer --print-to-pdf="${1:-$tmp/entrega3.pdf}" "file://$tmp/entrega3.html" 2>/dev/null
echo "${1:-$tmp/entrega3.pdf}"
