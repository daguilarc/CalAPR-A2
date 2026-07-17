"""Prepare city/ZIP panels for Pages catalog without publication regressions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from acs_apr_models import _run_zip_regressions
from panel_context import prepare_panel_context


def prepare_pages_context(base_path: Path | None = None) -> dict[str, Any]:
    """Build shared panel (Steps 1-11), then ZIP panel only for Pages."""
    panel_ctx = prepare_panel_context(base_path=base_path)
    base_output_dir = panel_ctx["base_output_dir"]

    zip_panel = _run_zip_regressions(
        panel_ctx["df_apr_db_inc"],
        panel_ctx["df_apr_all"],
        panel_ctx["mf_mask_all"],
        panel_ctx["df_county"],
        panel_ctx["df_county_cbsa"],
        panel_ctx["df_msa"],
        panel_ctx["ca_county_name_to_fips"],
        {},
        panel_ctx["legend_note_payload"],
        [],
        [],
        base_output_dir / "ZIPCodes",
        panels_only=True,
    )
    df_zip, df_zip_yearly_long, sf_zips_for_xsf = zip_panel

    return {
        "df_final": panel_ctx["df_final"],
        "df_zip": df_zip,
        "df_zip_yearly_long": df_zip_yearly_long,
        "sf_zips_for_xsf": sf_zips_for_xsf,
        "legend_note_payload": panel_ctx["legend_note_payload"],
        "permit_years": panel_ctx["permit_years"],
        "base_output_dir": base_output_dir,
    }
