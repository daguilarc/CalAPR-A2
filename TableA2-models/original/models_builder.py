"""Build original city/ZIP regressions, PCA outputs, and R2 diagnostics."""

from __future__ import annotations

from acs_apr_models import (
    EV1_STANDARDIZED_INPUT_CAPTION,
    EV1_PCA_DELTA_COLS,
    R2_DIAG_COLUMNS,
    R2_DIAG_LEGACY_COLUMN_RENAMES,
    R2_THRESHOLD,
    RUN_PCA_ONLY,
    ZHVI_TIERS,
    _EV1_PCA_CITY_CO_COUNT_COLS,
    _run_city_regressions,
    _run_zip_regressions,
    _zhvi_tier_pct_afford_col,
    pd,
    run_pca_ev1_affordability,
)


def build_original_models(ctx):
    """Run Steps 12-13 + PCA/r2 diagnostics from precomputed panel context."""
    charts_skipped_low_r2 = []
    all_r2_results = ctx["all_r2_results"]
    base_output_dir = ctx["base_output_dir"]
    r2_csv_path = base_output_dir / "r2_diagnostics.csv"
    city_charts_dir = base_output_dir / "Cities"
    zip_charts_dir = base_output_dir / "ZIPCodes"

    x_var_labels = _run_city_regressions(
        ctx["df_final"],
        ctx["df_apr_db_inc"],
        ctx["permit_years"],
        ctx["legend_note_payload"],
        charts_skipped_low_r2,
        all_r2_results,
        city_charts_dir,
    )
    df_zip_for_pca = _run_zip_regressions(
        ctx["df_apr_db_inc"],
        ctx["df_apr_all"],
        ctx["mf_mask_all"],
        ctx["df_county"],
        ctx["df_county_cbsa"],
        ctx["df_msa"],
        ctx["ca_county_name_to_fips"],
        x_var_labels,
        ctx["legend_note_payload"],
        charts_skipped_low_r2,
        all_r2_results,
        zip_charts_dir,
    )

    print("\n" + "=" * 70)
    print(
        "PCA EV1 + OLS: affordability ~ EV1 composite "
        f"({EV1_STANDARDIZED_INPUT_CAPTION}; CITY only; "
        f"{', '.join(_zhvi_tier_pct_afford_col(t['key']) for t in ZHVI_TIERS)}, zori_pct_afford)"
    )
    print("=" * 70)
    df_city_for_pca = ctx["df_final"][ctx["df_final"]["geography_type"] == "City"].copy()
    city_vlow_year_cols = [f"VLOW_LOW_CO_{y}" for y in ctx["permit_years"] if f"VLOW_LOW_CO_{y}" in df_city_for_pca.columns]
    city_mod_year_cols = [f"MOD_CO_{y}" for y in ctx["permit_years"] if f"MOD_CO_{y}" in df_city_for_pca.columns]
    if "VLOW_LOW_CO_total" not in df_city_for_pca.columns and city_vlow_year_cols:
        df_city_for_pca["VLOW_LOW_CO_total"] = df_city_for_pca[city_vlow_year_cols].sum(axis=1).values
    if "MOD_CO_total" not in df_city_for_pca.columns and city_mod_year_cols:
        df_city_for_pca["MOD_CO_total"] = df_city_for_pca[city_mod_year_cols].sum(axis=1).values
    city_required = list(_EV1_PCA_CITY_CO_COUNT_COLS) + list(EV1_PCA_DELTA_COLS) + ["population"]
    city_missing = [c for c in city_required if c not in df_city_for_pca.columns]
    print(f"  EV1 preflight city missing: {city_missing if city_missing else 'none'}")
    run_pca_ev1_affordability(
        df_city_for_pca,
        df_zip_for_pca,
        city_charts_dir,
        zip_charts_dir,
        base_output_dir,
        r2_diagnostics=all_r2_results,
    )

    if all_r2_results:
        df_new = pd.DataFrame(all_r2_results, columns=R2_DIAG_COLUMNS)
        if RUN_PCA_ONLY and r2_csv_path.exists():
            df_old = pd.read_csv(r2_csv_path).rename(columns=R2_DIAG_LEGACY_COLUMN_RENAMES)
            pca_mask = df_old["Regression"].astype(str).str.endswith(" vs EV1 PC1", na=False)
            n_drop = int(pca_mask.sum())
            if n_drop:
                print(f"  PCA-only: replacing {n_drop} EV1 PC1 row(s) in {r2_csv_path.name}")
            df_r2 = pd.concat(
                [df_old.loc[~pca_mask, R2_DIAG_COLUMNS], df_new],
                ignore_index=True,
            )
        else:
            df_r2 = df_new
        df_r2["sort_key"] = df_r2[["McFadden_R2", "OLS_R2_positive_subset"]].max(axis=1, skipna=True)
        df_r2 = df_r2.sort_values("sort_key", ascending=False, na_position="last").drop(columns=["sort_key"]).reset_index(drop=True)
        sep = "=" * 70
        print("\n" + sep)
        print("R2 diagnostics (all regressions, descending)")
        print(sep)
        print(df_r2.to_string(index=False))
        print(sep)
        df_r2.to_csv(r2_csv_path, index=False)
        print(f"  Wrote: {r2_csv_path.name}")
    if charts_skipped_low_r2:
        print("\n" + "=" * 70)
        print(
            f"Charts not produced (threshold {R2_THRESHOLD}: two-part uses McFadden's R2)"
        )
        print("=" * 70)
        for chart_id, r2 in charts_skipped_low_r2:
            print(f"  {chart_id}: R2 = {r2:.4f}")
        print("=" * 70)

    print("\nAnalysis complete.")
    return {
        "x_var_labels": x_var_labels,
        "df_zip_for_pca": df_zip_for_pca,
        "all_r2_results": all_r2_results,
        "charts_skipped_low_r2": charts_skipped_low_r2,
        "r2_csv_path": r2_csv_path,
    }
