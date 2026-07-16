#!/usr/bin/env bash
set -euo pipefail

REPO="/Users/diegoaguilar-canabal/Desktop/work/CAY/CSVparse_hcd_apr"
STAGING="/tmp/apr-full/2018-2024"
LOG="/tmp/apr-full-finish.log"
BUILD_LOG="/tmp/apr-full-build.log"
BUILD_PID="${1:-12844}"

exec > >(tee -a "$LOG") 2>&1

echo "=== finish_co_rebuild started $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

wait_for_build() {
  if kill -0 "$BUILD_PID" 2>/dev/null; then
    echo "Waiting for build PID $BUILD_PID..."
    while kill -0 "$BUILD_PID" 2>/dev/null; do
      sleep 60
    done
    echo "Build PID exited."
  else
    echo "Build PID $BUILD_PID not running; checking staging."
  fi
  if [[ ! -f "$STAGING/manifest.json" ]]; then
    echo "ERROR: staging manifest missing after build"
    tail -50 "$BUILD_LOG" || true
    exit 1
  fi
}

verify_staging() {
  cd "$REPO"
  python3 scripts/verify_pages_catalog.py "$STAGING"
  python3 - <<'PY'
import json
from pathlib import Path
manifest = json.loads(Path("/tmp/apr-full/2018-2024/manifest.json").read_text())
assert manifest.get("input_profile") == "release-2018-2024-v1", manifest.get("input_profile")
catalog = json.loads(Path("/tmp/apr-full/2018-2024/catalog.json").read_text())
y_cols = {entry["y_col"] for entry in catalog.values() if isinstance(entry, dict) and "y_col" in entry}
bad = [y for y in y_cols if "_ENT" in y or "_BP" in y or y.endswith("_ENT_total") or y.endswith("_BP_total")]
assert not bad, f"non-CO y_col values: {bad[:10]}"
co = [y for y in y_cols if "_CO" in y or y.endswith("_CO_total")]
print(f"manifest input_profile OK; {len(catalog)} pairs; {len(co)} CO y_cols; 0 ENT/BP")
PY
}

promote() {
  cd "$REPO"
  rm -rf docs/data/releases/2018-2024
  cp -R "$STAGING" docs/data/releases/2018-2024
  echo "Promoted to docs/data/releases/2018-2024"
}

run_e2e() {
  cd "$REPO"
  bash scripts/run_explorer_e2e.sh
}

run_notebook() {
  cd "$REPO"
  "$REPO/.venv-pages/bin/python" - <<'PY'
import json
import sys
from pathlib import Path

repo = Path("/Users/diegoaguilar-canabal/Desktop/work/CAY/CSVparse_hcd_apr")
release = repo / "docs/data/releases/2018-2024"
required = ["manifest.json", "chart_labels.json", "catalog.json", "map_metrics.json", "maps.geojson"]
for name in required:
    path = release / name
    if not path.is_file():
        raise SystemExit(f"missing artifact: {path}")

manifest = json.loads((release / "manifest.json").read_text())
catalog = json.loads((release / "catalog.json").read_text())
labels = json.loads((release / "chart_labels.json").read_text())
map_metrics = json.loads((release / "map_metrics.json").read_text())
geo = json.loads((release / "maps.geojson").read_text())

assert manifest.get("input_profile") == "release-2018-2024-v1"
y_cols = {entry.get("y_col") for entry in catalog.values() if isinstance(entry, dict)}
bad = [y for y in y_cols if y and ("_ENT" in y or "_BP" in y)]
if bad:
    raise SystemExit(f"non-CO catalog y_col: {bad[:5]}")
if not y_cols:
    raise SystemExit("empty catalog y_col set")

# Simulate notebook load-release + one chart key resolution per artifact type
sample_keys = list(catalog.keys())[:5]
for key in sample_keys:
    entry = catalog[key]
    for field in ("y_col", "x_col", "geography"):
        if field not in entry:
            raise SystemExit(f"catalog entry missing {field}: {key}")
    if entry["y_col"] not in labels.get("outcomes", {}):
        raise SystemExit(f"label missing for y_col {entry['y_col']}")
    if entry["x_col"] not in labels.get("predictors", {}):
        raise SystemExit(f"label missing for x_col {entry['x_col']}")

if not map_metrics:
    raise SystemExit("map_metrics empty")
if not geo.get("features"):
    raise SystemExit("maps.geojson has no features")

print(f"notebook smoke OK: 5 artifacts loaded; {len(catalog)} pairs; sample keys {sample_keys[:3]}")
PY
}

wait_for_build
verify_staging
promote
run_e2e
run_notebook
echo "=== finish_co_rebuild complete $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
