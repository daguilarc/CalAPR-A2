#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RELEASE_DIR="$REPO_ROOT/docs/data/releases/2018-2024"
PLOTLY_URL="https://cdn.plot.ly/plotly-2.27.0.min.js"
REAL_MAPS="${1:-}"

# Fixture output is for fast UI smoke checks only.
# Playwright e2e requires a non-fixture release manifest.

rm -rf "$RELEASE_DIR"
python3 "$REPO_ROOT/scripts/export_pages_catalog.py" --fixture --staging-dir "$RELEASE_DIR"

if [ "$REAL_MAPS" = "--real-maps" ]; then
  echo "Exporting real California maps from local APR panel (several minutes)..."
  python3 "$REPO_ROOT/scripts/export_pages_catalog.py" --overlay-real-maps --staging-dir "$RELEASE_DIR"
fi

curl --fail --location --proto '=https' --tlsv1.2 --output "$RELEASE_DIR/plotly.min.js" "$PLOTLY_URL"
python3 - <<PY
import hashlib
import json
from pathlib import Path

release_dir = Path("${RELEASE_DIR}")
manifest_path = release_dir / "manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
manifest["artifact_sha256"]["plotly.min.js"] = hashlib.sha256(
    (release_dir / "plotly.min.js").read_bytes()
).hexdigest()
manifest_path.write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8")
PY
python3 "$REPO_ROOT/scripts/verify_pages_catalog.py" "$RELEASE_DIR"

echo
echo "Local site test data ready."
if [ "$REAL_MAPS" = "--real-maps" ]; then
  echo "Maps: real California jurisdictions and full labeled metric list."
  echo "Models: fixture catalog (4 pairs) for quick UI smoke test."
else
  echo "Maps: tiny polygon fixture. Re-run with --real-maps for California boundaries."
fi
echo "Start the server:"
echo "  cd $REPO_ROOT && python3 -m http.server 8765 --directory docs"
echo "Open:"
echo "  http://localhost:8765/"
