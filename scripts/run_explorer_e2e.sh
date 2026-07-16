#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST_PATH="$REPO_ROOT/docs/data/releases/2018-2024/manifest.json"

python3 - <<PY
import json
from pathlib import Path

manifest_path = Path("${MANIFEST_PATH}")
if not manifest_path.exists():
    raise SystemExit(f"Missing release manifest: {manifest_path}")
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
if manifest.get("input_profile") == "fixture-v1":
    raise SystemExit("Refusing Playwright run against fixture release (input_profile=fixture-v1).")
PY

cd "$REPO_ROOT/e2e"
npx playwright test
