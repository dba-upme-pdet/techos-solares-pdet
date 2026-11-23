#!/bin/bash
# Entrega 4: Complete pipeline orchestration
# Executes all phases: data reader, visualizations, tables, and PDF compilation

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "================================================"
echo "Entrega 4: Complete Analysis Pipeline"
echo "================================================"
echo ""

# Activate venv if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
    echo "✓ Virtual environment activated"
fi

echo ""
echo "Phase 0: Shared Contract Validation"
echo "-----------------------------------"
python scripts/entrega4_contracts.py --check

echo ""
echo "Phase 1: Automated Data Reader"
echo "-------------------------------"
python scripts/07_entrega4_analysis.py

echo ""
echo "Phase 2: Maps and Charts Generation"
echo "-----------------------------------"
if [ -f "data/processed/municipalities.geojsonl" ]; then
    python scripts/08_entrega4_visualizations.py
else
    echo "Notice: data/processed/municipalities.geojsonl not found; regenerating charts only (--charts-only)."
    python scripts/08_entrega4_visualizations.py --charts-only
fi

echo ""
echo "Phase 3: Tables and Markdown Summary"
echo "------------------------------------"
python scripts/09_entrega4_tables.py

echo ""
echo "Phase 4: PDF Compilation (LaTeX)"
echo "--------------------------------"
cd "$ROOT/docs/delivery4"

# Check if latexmk is available
if ! command -v latexmk &> /dev/null; then
    echo "ERROR: latexmk not found. Install texlive-latex-extra (macOS: brew install texlive)" >&2
    exit 1
fi

echo "Compiling LaTeX..."
latexmk -pdf -interaction=nonstopmode -halt-on-error entrega4_informe.tex > /dev/null 2>&1 || {
    echo "ERROR: LaTeX compilation failed. Check entrega4_informe.log for details" >&2
    latexmk -pdf -interaction=nonstopmode entrega4_informe.tex
    exit 1
}

mv -f entrega4_informe.pdf Entrega4_Analisis_Techos.pdf
# Clean auxiliary files
latexmk -C entrega4_informe.tex > /dev/null 2>&1
rm -f entrega4_informe.aux entrega4_informe.log entrega4_informe.out entrega4_informe.toc entrega4_informe.fls entrega4_informe.fdb_latexmk

echo "✓ PDF generated successfully"

cd "$ROOT"

echo ""
echo "================================================"
echo "✓ Pipeline Complete!"
echo "================================================"
echo ""
echo "Generated outputs:"
echo "  - outputs/entrega4_analysis_summary.json"
echo "  - docs/delivery4/figuras/*.png (6 visualizations at 200 dpi)"
echo "  - docs/delivery4/entrega4_analysis_tables.md"
echo "  - docs/delivery4/Entrega4_Analisis_Techos.pdf"
echo ""
echo "Next steps:"
echo "  1. Review PDF: open docs/delivery4/Entrega4_Analisis_Techos.pdf"
echo "  2. Verify all figures render correctly"
echo "  3. Check municipality numbers match README.md expectations"
echo "  4. Commit all outputs: git add docs/delivery4 outputs/entrega4_*"
echo "  5. Push and open pull request for Entrega 4"
echo ""
