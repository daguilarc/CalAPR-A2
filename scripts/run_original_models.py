"""CLI entrypoint for original APR model pipeline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = REPO_ROOT / "TableA2-models"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run original APR model pipeline.")
    parser.add_argument(
        "--base-path",
        type=Path,
        default=None,
        help="Optional output base path (defaults to TableA2-models).",
    )
    args = parser.parse_args()

    sys.path.insert(0, str(MODELS_DIR))
    from original.models_builder import build_original_models
    from original.pipeline_context import prepare_original_context

    ctx = prepare_original_context(base_path=args.base_path)
    build_original_models(ctx)


if __name__ == "__main__":
    main()
