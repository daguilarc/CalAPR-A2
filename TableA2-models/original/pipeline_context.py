"""Original-model pipeline context built from shared panel context."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from panel_context import prepare_panel_context


def prepare_original_context(base_path: Path | None = None) -> dict[str, Any]:
    """Build shared panel context for original-model pipeline."""
    ctx = prepare_panel_context(base_path=base_path)
    return {
        **ctx,
        "df_zip": None,
        "df_zip_yearly_long": None,
        "sf_zips_for_xsf": None,
    }
