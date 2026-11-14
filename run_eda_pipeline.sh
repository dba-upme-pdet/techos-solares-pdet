#!/bin/bash
set -e

PROJECT_DIR="$(pwd)"
LOG_FILE="${PROJECT_DIR}/outputs/eda_pipeline.log"
mkdir -p "${PROJECT_DIR}/outputs"

log() {
    echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log "========================================"
log "EDA SPATIAL VERIFICATION PIPELINE - START"
log "========================================"

# Step 1: Wait for download
log "Step 1: Monitoring download ($(du -sh data/raw/ms_buildings/ 2>/dev/null || echo '0MB'))..."
while [ $(find data/raw/ms_buildings/ -name "*.csv.gz" 2>/dev/null | wc -l) -lt 120 ]; do
    sleep 30
    COUNT=$(find data/raw/ms_buildings/ -name "*.csv.gz" 2>/dev/null | wc -l)
    SIZE=$(du -sh data/raw/ms_buildings/ 2>/dev/null | cut -f1)
    log "  Download progress: $COUNT/125 partitions ($SIZE)"
done
log "✓ Download complete"

# Step 2: Prepare buildings
log "\nStep 2: Preparing buildings GeoJSONL..."
.venv/bin/python3 scripts/04_prepare_ms_buildings.py 2>&1 | tee -a "$LOG_FILE"

# Step 3: Load buildings
log "\nStep 3: Loading buildings to MongoDB..."
.venv/bin/python3 scripts/03_load_buildings.py 2>&1 | tee -a "$LOG_FILE"

# Step 4: Verify spatial
log "\nStep 4: Verifying spatial index..."
.venv/bin/python3 scripts/03_verify_spatial_buildings.py 2>&1 | tee -a "$LOG_FILE"

# Step 5: Generate EDA
log "\nStep 5: Generating EDA and visualizations..."
.venv/bin/python3 scripts/eda_spatial_analysis.py 2>&1 | tee -a "$LOG_FILE"

log "\n========================================"
log "✓ PIPELINE COMPLETE"
log "========================================"
log "Outputs available in:"
log "  - outputs/eda/eda_report.json"
log "  - outputs/eda/*.png"
log "  - outputs/buildings_load_report.json"

