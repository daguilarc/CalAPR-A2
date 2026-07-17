"""Build GitHub Pages regression catalog from full Cartesian pair registry."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np

import statsmodels.api as sm

from acs_apr_models import (
    CHART_LEGEND_GEO_CITY,
    CHART_LEGEND_GEO_ZIP,
    ECON_META,
    _exclude_by_str,
    _exclude_by_upper,
    _filter_jurisdiction_panel,
    _melt_jurisdiction_years,
    _predictor_display_label,
    _predictor_fit_mask_kind,
    _predictor_is_log_x,
    _rate_per_1000,
    _resolve_legend_note,
    _to_upper_set,
    fit_two_part_for_pages,
    stationary_bootstrap_ols,
)
from .export import PAGES_CATALOG, PAGES_MANIFEST, record_regression, write_pages_data
from .pair_registry import PairRecord, iter_pairs, parse_city_outcome
from .pipeline_context import prepare_pages_context


def _city_fit_mask(df_final, x_col: str, requires_msa: bool) -> np.ndarray:
    is_city = df_final["geography_type"] == "City"
    fit_mask_kind = _x_col_fit_mask_kind(x_col)
    if fit_mask_kind == "finite":
        valid_x = (
            df_final[x_col].notna()
            & np.isfinite(np.asarray(df_final[x_col].values, dtype=np.float64))
        )
    else:
        valid_x = df_final[x_col].notna() & (df_final[x_col] > 0)
    mask = is_city & valid_x
    if requires_msa:
        mask = mask & df_final["msa_income"].notna()
    return mask.values


def _zip_fit_mask(df_zip, x_col: str, requires_msa: bool, use_log_x: bool) -> np.ndarray:
    if use_log_x:
        valid_x = df_zip[x_col].notna() & (df_zip[x_col] > 0)
    else:
        valid_x = (
            df_zip[x_col].notna()
            & np.isfinite(np.asarray(df_zip[x_col].values, dtype=np.float64))
        )
    mask = valid_x
    if requires_msa:
        mask = mask & df_zip["msa_income"].notna()
    return mask.values


def _valid_x_mask(frame, x_col, x_transform, x_fit_mask_kind):
    del x_transform
    if x_fit_mask_kind == "finite":
        return (
            frame[x_col].notna()
            & np.isfinite(np.asarray(frame[x_col].values, dtype=np.float64))
        ).values
    return (frame[x_col].notna() & (frame[x_col] > 0)).values


def _is_construction_y_col(key: str) -> bool:
    return key.endswith("_CO_total") or key.endswith("_CO")


def _x_col_transform(x_col: str) -> str:
    if x_col in ECON_META:
        return "log" if _predictor_is_log_x(x_col) else "identity"
    return "identity"


def _x_col_fit_mask_kind(x_col: str) -> str:
    if x_col in ECON_META:
        return _predictor_fit_mask_kind(x_col)
    return "finite"


def _pair_x_label(x_col: str) -> str:
    if x_col in ECON_META:
        return _predictor_display_label(x_col)
    return x_col


def _fit_continuous_pair(
    frame,
    *,
    label_col,
    county_col,
    x_col,
    y_col,
    min_jurisdictions,
    x_transform,
    x_fit_mask_kind,
    requires_msa,
) -> dict | None:
    del county_col
    mask = _valid_x_mask(frame, x_col, x_transform, x_fit_mask_kind)
    valid_y = (
        frame[y_col].notna()
        & np.isfinite(np.asarray(frame[y_col].values, dtype=np.float64))
    )
    mask = mask & valid_y.values
    if requires_msa:
        mask = mask & frame["msa_income"].notna().values

    df_v = frame[mask].copy()
    if len(df_v) < min_jurisdictions:
        return None

    x_raw = np.asarray(df_v[x_col].values, dtype=np.float64)
    y_vals = np.asarray(df_v[y_col].values, dtype=np.float64)
    x_model = np.log(np.maximum(x_raw, 1e-300)) if x_transform == "log" else x_raw

    fit = sm.OLS(y_vals, sm.add_constant(x_model)).fit()
    intercept_mle = float(fit.params[0])
    slope_mle = float(fit.params[1])
    mle_result = {
        "intercept_mle": intercept_mle,
        "slope_mle": slope_mle,
        "alpha_mle": 0.0,
        "beta_mle": 0.0,
        "model_family": "continuous",
        "positive_part_t": float(fit.tvalues[1]),
        "positive_part_p": float(fit.pvalues[1]),
    }

    boot_intercept_samples, boot_slope_samples = stationary_bootstrap_ols(x_model, y_vals)
    boot_alpha_samples = boot_beta_samples = None
    if boot_intercept_samples is not None and boot_slope_samples is not None:
        boot_alpha_samples = np.zeros(len(boot_intercept_samples), dtype=np.float64)
        boot_beta_samples = np.zeros(len(boot_slope_samples), dtype=np.float64)

    labels = df_v[label_col].values if label_col in df_v.columns else np.array([""] * len(df_v))
    return {
        "intercept_mle": intercept_mle,
        "slope_mle": slope_mle,
        "alpha_mle": 0.0,
        "beta_mle": 0.0,
        "boot_alpha_samples": boot_alpha_samples,
        "boot_beta_samples": boot_beta_samples,
        "boot_intercept_samples": boot_intercept_samples,
        "boot_slope_samples": boot_slope_samples,
        "x_data": x_raw,
        "y_data": y_vals,
        "jurisdictions": labels,
        "mcfadden_r2": None,
        "ols_rsquared": float(fit.rsquared),
        "mle_result": mle_result,
        "x_transform": "log" if x_transform == "log" else None,
    }


def _apply_exclude(df, label_col: str, exclude_set, geography: str):
    if not exclude_set:
        return df
    if geography == "city":
        return df[_exclude_by_upper(df[label_col], _to_upper_set(exclude_set))].copy()
    return df[_exclude_by_str(df[label_col].astype(str).str.zfill(5), exclude_set)].copy()


def _fit_city_pair(pair: PairRecord, df_final, permit_years) -> dict | None:
    mask = _city_fit_mask(df_final, pair.x_col, pair.requires_msa)
    df_geo = df_final[mask].copy()
    df_geo = _apply_exclude(df_geo, "JURISDICTION", pair.exclude_set, "city")
    if len(df_geo) < pair.min_jurisdictions:
        return None

    dr_type, cat_suffix = parse_city_outcome(pair.y_col)
    cat_prefix = f"{dr_type}_{cat_suffix}"
    yearly_cols = [y for y in permit_years if f"{cat_prefix}_{y}" in df_geo.columns]
    if not yearly_cols:
        return None

    keep_cols = ["JURISDICTION", "county", pair.x_col, "population"]
    df_totals = df_geo[keep_cols + [pair.y_col]].rename(columns={pair.y_col: "units"})
    df_yearly = _melt_jurisdiction_years(
        df_geo,
        keep_cols,
        yearly_cols,
        lambda d, y: {"units": d[f"{cat_prefix}_{y}"]},
    )
    if df_yearly.empty or len(df_totals) < pair.min_jurisdictions:
        return None

    return fit_two_part_for_pages(
        df_totals,
        df_yearly,
        pair.x_col,
        "units",
        permit_years,
        log_x=_x_col_transform(pair.x_col) == "log",
        county_col="county",
        label_col="JURISDICTION",
        x_varies_by_year=False,
    )


def _fit_zip_pair(pair: PairRecord, df_zip, df_zip_yearly_long) -> dict | None:
    use_log_x = _x_col_transform(pair.x_col) == "log"
    mask = _zip_fit_mask(df_zip, pair.x_col, pair.requires_msa, use_log_x)
    df_v = df_zip[mask].copy()
    df_v = _apply_exclude(df_v, "zipcode", pair.exclude_set, "zip")
    if len(df_v) < pair.min_jurisdictions:
        return None
    pop_ok = df_v["population"].notna() & (df_v["population"] > 0)
    if pop_ok.sum() < pair.min_jurisdictions:
        return None

    use_zips = set(df_v["zipcode"].astype(str).str.zfill(5))
    pred_filter = (
        (lambda zy_df: (zy_df[pair.x_col].notna() & np.isfinite(zy_df[pair.x_col].values)))
        if not use_log_x
        else (lambda zy_df: (zy_df[pair.x_col].notna() & (zy_df[pair.x_col] > 0)))
    )
    zy = _filter_jurisdiction_panel(
        df_zip_yearly_long,
        "zipcode",
        use_zips,
        pair.x_col,
        pair.y_col,
        predicate=pred_filter,
    )
    if zy.empty:
        return None
    zy = zy.copy()
    zy["y_rate"] = _rate_per_1000(zy[pair.y_col].values.astype(float), zy["population"].values.astype(float))
    df_yearly_zip = zy[["year", "county", "population", pair.x_col, "y_rate"]].copy()
    zip_years = sorted(df_yearly_zip["year"].dropna().unique().astype(int).tolist())
    if not zip_years:
        return None

    df_totals_zip = df_v[["zipcode", "county", "population"]].copy().reset_index(drop=True)
    df_totals_zip[pair.x_col] = df_v[pair.x_col].values.astype(float)
    df_totals_zip["y_rate"] = _rate_per_1000(
        df_v[pair.y_col].values.astype(float),
        df_v["population"].values.astype(float),
    )
    return fit_two_part_for_pages(
        df_totals_zip,
        df_yearly_zip,
        pair.x_col,
        "y_rate",
        zip_years,
        log_x=use_log_x,
        y_is_rate=True,
        rate_precomputed=True,
        county_col="county",
        label_col="zipcode",
        x_varies_by_year=False,
    )


def build_pages_catalog(
    docs_data_dir: Path,
    maps_geojson_path: Path | None = None,
    *,
    max_pairs: int | None = None,
    context: dict[str, Any] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """Run pipeline context + full pair iteration; write catalog.json."""
    PAGES_CATALOG.clear()
    PAGES_MANIFEST.clear()
    ctx = context if context is not None else prepare_pages_context()
    df_final = ctx["df_final"]
    df_zip = ctx["df_zip"]
    df_zip_yearly_long = ctx["df_zip_yearly_long"]
    legend_note_payload = ctx["legend_note_payload"]
    permit_years = ctx["permit_years"]

    n_attempted = 0
    n_exported = 0
    n_mle_failed = 0
    n_bootstrap_succeeded = 0
    n_bootstrap_failed = 0
    n_hierarchical_attempted = 0
    n_hierarchical_succeeded = 0
    n_hierarchical_failed = 0
    pair_offset = int(os.environ.get("PAGES_CATALOG_PAIR_OFFSET", "0") or 0)

    for pair_index, pair in enumerate(iter_pairs(df_final, df_zip)):
        if pair_index < pair_offset:
            continue
        if max_pairs is not None and n_attempted >= max_pairs:
            break
        n_attempted += 1

        if pair.y_col in ECON_META or not _is_construction_y_col(pair.y_col):
            frame = df_zip if pair.geography == "zip" else df_final
            result = _fit_continuous_pair(
                frame,
                label_col="zipcode" if pair.geography == "zip" else "JURISDICTION",
                county_col="county",
                x_col=pair.x_col,
                y_col=pair.y_col,
                min_jurisdictions=pair.min_jurisdictions,
                x_transform=_x_col_transform(pair.x_col),
                x_fit_mask_kind=_x_col_fit_mask_kind(pair.x_col),
                requires_msa=pair.requires_msa,
            )
        elif pair.geography == "city":
            result = _fit_city_pair(pair, df_final, permit_years)
        else:
            result = _fit_zip_pair(pair, df_zip, df_zip_yearly_long)

        if result is None:
            n_mle_failed += 1
            continue

        has_bootstrap = all(result.get(name) is not None for name in (
            "boot_alpha_samples", "boot_beta_samples", "boot_intercept_samples", "boot_slope_samples"
        ))
        if not has_bootstrap:
            n_bootstrap_failed += 1
            continue
        n_bootstrap_succeeded += 1
        hierarchy_attempted = not bool(os.environ.get("PAGES_SKIP_HIERARCHICAL"))
        if hierarchy_attempted:
            n_hierarchical_attempted += 1
        has_hierarchy = all(result.get(name) is not None for name in (
            "alpha_samples", "beta_samples", "intercept_samples", "slope_samples"
        ))
        if has_hierarchy:
            n_hierarchical_succeeded += 1
        elif hierarchy_attempted:
            n_hierarchical_failed += 1

        result["income_label"] = _pair_x_label(pair.x_col)
        if pair.x_axis_filter_note:
            result["x_axis_filter_note"] = pair.x_axis_filter_note

        var_label = {
            "_xsf": "excl. SF" if pair.geography == "city" else "excl. SF Co.",
            "_city_hash": "- # 20%",
            "_zip_hash": "- # 20%",
            "_xsf_city_hash": "excl. SF - # 20%",
            "_xsf_zip_hash": "excl. SF Co. - # 20%",
        }.get(pair.var_suffix, "")
        legend_geo = CHART_LEGEND_GEO_CITY if pair.geography == "city" else CHART_LEGEND_GEO_ZIP
        data_label = f"{legend_geo} {var_label}".strip() if var_label else legend_geo

        record_regression(
            result,
            geography=pair.geography,
            y_col=pair.y_col,
            x_col=pair.x_col,
            robustness=pair.robustness,
            data_label=data_label,
            dr_type=pair.dr_type,
            cat_suffix=pair.cat_suffix,
            legend_exclusion_note=_resolve_legend_note(
                legend_note_payload,
                pair.dr_type,
                pair.cat_suffix,
                pair.geography,
            ),
        )
        n_exported += 1

    PAGES_MANIFEST.update(
        {
            "pipeline": "pages_catalog_builder",
            "n_pairs_attempted": n_attempted,
            "n_pairs_exported": n_exported,
            "n_pairs_mle_failed": n_mle_failed,
            "n_stationary_bootstrap_succeeded": n_bootstrap_succeeded,
            "n_stationary_bootstrap_failed": n_bootstrap_failed,
            "n_hierarchical_attempted": n_hierarchical_attempted,
            "n_hierarchical_succeeded": n_hierarchical_succeeded,
            "n_hierarchical_failed": n_hierarchical_failed,
        }
    )
    if write:
        write_pages_data(docs_data_dir, maps_geojson_path)
    return {
        "n_pairs_attempted": n_attempted,
        "n_pairs_exported": n_exported,
        "n_pairs_mle_failed": n_mle_failed,
        "n_catalog_entries": len(PAGES_CATALOG),
    }
