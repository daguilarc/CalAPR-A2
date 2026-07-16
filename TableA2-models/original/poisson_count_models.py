"""Poisson ZIP/ZINB model block extracted from acs_apr_models."""

from __future__ import annotations

from acs_apr_models import (
    LABEL_POLICY_DB_FOR_SALE_UNITS,
    LABEL_POLICY_DB_UNITS,
    LABEL_POLICY_INC_FOR_SALE_UNITS,
    LABEL_POLICY_INC_UNITS,
    PHASE_DISPLAY_BY_TAG,
    _affordable_dr_only_colnames,
    _fig_ax_square_plot,
    np,
    pd,
    plt,
    setup_chart_style,
    sm,
)
from statsmodels.discrete.count_model import ZeroInflatedNegativeBinomialP, ZeroInflatedPoisson


def _poisson_result_pseudo_r2(fit_result):
    """McFadden-style pseudo R2 from deviance ratio, else from llf/llnull."""
    deviance = float(getattr(fit_result, "deviance", np.nan))
    null_deviance = float(getattr(fit_result, "null_deviance", np.nan))
    if np.isfinite(deviance) and np.isfinite(null_deviance) and null_deviance > 0:
        return float(1.0 - (deviance / null_deviance))
    llf = float(getattr(fit_result, "llf", np.nan))
    llnull = float(getattr(fit_result, "llnull", np.nan))
    if np.isfinite(llf) and np.isfinite(llnull) and llnull != 0:
        return float(1.0 - (llf / llnull))
    return np.nan


def _fit_zip_or_zinb(endog, exog):
    """Constant inflation; try ZIP first, then ZINB once."""
    exog_infl = np.ones((len(endog), 1), dtype=np.float64)
    for model_cls, tag in (
        (ZeroInflatedPoisson, "ZIP"),
        (ZeroInflatedNegativeBinomialP, "ZINB"),
    ):
        try:
            model = model_cls(endog, exog, exog_infl=exog_infl)
            fit_result = model.fit(disp=0, maxiter=300)
        except (ValueError, FloatingPointError, np.linalg.LinAlgError) as exc:
            print(f"  ERROR: {tag} fit failed: {exc}")
            continue
        if hasattr(fit_result, "converged") and not bool(fit_result.converged):
            print(f"  ERROR: {tag} fit did not converge.")
            continue
        return fit_result, tag
    return None, None


def _zip_zinb_inflation_params(fit_result):
    """Inflation / zero-process block (logit); constant inflation when exog_infl is ones."""
    mdl = fit_result.model
    k0 = int(mdl.k_inflate)
    p = np.asarray(fit_result.params, dtype=np.float64)
    bse = np.asarray(getattr(fit_result, "bse", np.full(p.shape, np.nan)), dtype=np.float64)
    pvalues = np.asarray(getattr(fit_result, "pvalues", np.full(p.shape, np.nan)), dtype=np.float64)
    if p.size < k0:
        return None
    sl = slice(0, k0)
    return p[sl], bse[sl], pvalues[sl]


def _zip_zinb_count_part_linear_params(fit_result):
    """Count block: inflation excluded; for ZINB, index 2 in the slice is NB alpha."""
    mdl = fit_result.model
    k0 = int(mdl.k_inflate)
    k1 = int(mdl.k_exog)
    p = np.asarray(fit_result.params, dtype=np.float64)
    bse = np.asarray(getattr(fit_result, "bse", np.full(p.shape, np.nan)), dtype=np.float64)
    pvalues = np.asarray(getattr(fit_result, "pvalues", np.full(p.shape, np.nan)), dtype=np.float64)
    if p.size < k0 + k1:
        return None
    sl = slice(k0, k0 + k1)
    return p[sl], bse[sl], pvalues[sl]


def _append_zip_zinb_r2_diagnostics_row(
    r2_list, regression_label, geography, pseudo_r2,
    count_slope, count_t, count_p, zero_mle, zero_mle_t, zero_mle_p,
):
    """Append one ZIP/ZINB row (R2_DIAG_COLUMNS order); OLS R2 and PPM unused -> NaN."""
    r2_list.append((
        regression_label,
        geography,
        float(pseudo_r2),
        np.nan,
        float(count_slope),
        float(count_t),
        float(count_p),
        float(zero_mle),
        float(zero_mle_t),
        float(zero_mle_p),
        np.nan,
    ))


def _plot_poisson_db_vs_total_phase(
    x_vals, y_vals, fit_result, phase_tag, output_path, pseudo_r2, model_tag,
    scatter_label="MF 5+ projects",
    xlabel=None,
    ylabel=None,
    title=None,
):
    """Scatter + marginal mean line (ZIP or ZINB) for one phase (no CI bands)."""
    x_arr = np.asarray(x_vals, dtype=np.float64)
    y_arr = np.asarray(y_vals, dtype=np.float64)
    x_min = float(np.nanmin(x_arr))
    x_max = float(np.nanmax(x_arr))
    if not np.isfinite(x_min) or not np.isfinite(x_max):
        print(f"  ERROR: Skipping {phase_tag} chart due to non-finite x range.")
        return
    if x_max <= x_min:
        x_line = np.array([x_min, x_min + 1.0], dtype=np.float64)
    else:
        x_line = np.linspace(x_min, x_max, 100)
    exog_line = sm.add_constant(np.log1p(x_line), has_constant="add")
    exog_infl_line = np.ones((len(x_line), 1), dtype=np.float64)
    y_line = np.asarray(fit_result.predict(exog_line, exog_infl=exog_infl_line), dtype=np.float64)

    setup_chart_style()
    fig, ax = _fig_ax_square_plot()
    scatter_suffix = f"n={len(x_arr)}"
    xi = np.rint(x_arr).astype(np.int64)
    yi = np.rint(y_arr).astype(np.int64)
    if len(xi) == 0:
        sizes = np.array([], dtype=np.float64)
    else:
        order = np.lexsort((xi, yi))
        xi_s, yi_s = xi[order], yi[order]
        first = np.ones(len(xi_s), dtype=bool)
        first[1:] = (xi_s[1:] != xi_s[:-1]) | (yi_s[1:] != yi_s[:-1])
        run_starts = np.flatnonzero(first)
        run_ends = np.append(run_starts[1:], len(xi_s))
        run_counts = run_ends - run_starts
        dup_s = np.repeat(run_counts, run_counts)
        inv_order = np.empty_like(order)
        inv_order[order] = np.arange(len(order))
        dup = dup_s[inv_order]
        sizes = np.clip(18.0 + 22.0 * np.sqrt(dup.astype(np.float64)), 18.0, 220.0)
    scatter_handle = ax.scatter(
        x_arr, y_arr, color="#ED7D31", alpha=0.6, s=sizes, edgecolors="none",
        label=f"{scatter_label}\n({scatter_suffix})",
    )
    line_handle, = ax.plot(x_line, y_line, color="#1d4ed8", linewidth=2, label=f"{model_tag} marginal mean")
    r2_text = f"Pseudo R2 = {pseudo_r2:.3f}" if np.isfinite(pseudo_r2) else "Pseudo R2 = n/a"
    r2_handle, = ax.plot([], [], " ", label=r2_text)

    ph_disp = PHASE_DISPLAY_BY_TAG.get(phase_tag, phase_tag)
    if xlabel is None:
        xlabel = f"Multifamily (5+) net units at stage ({ph_disp})"
    if ylabel is None:
        ylabel = f"Affordable deed-restricted tier units ({ph_disp})"
    if title is None:
        title = f"{model_tag}: affordable deed-restricted vs multifamily totals ({ph_disp})"
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.set_xlim(0.0, float(np.nanmax(x_line)))
    y_max = float(max(np.nanmax(y_arr), 1.0))
    ax.set_ylim(0, y_max * 1.05)
    ax.legend(handles=[scatter_handle, line_handle, r2_handle], loc="center left", bbox_to_anchor=(1.02, 0.5))
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _poisson_owner_x_keys(df_lhs, df_rhs):
    """Return required base keys for Rule A owner Poisson merge compatibility check."""
    need = ("JURIS_CLEAN", "CNTY_CLEAN", "YEAR", "zipcode", "UNIT_CAT", "TENURE")
    miss_l = [c for c in need if c not in df_lhs.columns]
    miss_r = [c for c in need if c not in df_rhs.columns]
    if miss_l or miss_r:
        raise ValueError(
            "Rule A Poisson join: missing columns. "
            f"lhs={miss_l} rhs={miss_r}"
        )
    return list(need)


def _attach_poisson_owner_x_rule_a(df_apr_db_inc, df_apr_all, mf_mask_all, phase_context=None):
    """Attach Rule A owner x columns on index-aligned APR subsets."""
    _poisson_owner_x_keys(df_apr_db_inc, df_apr_all)
    if len(df_apr_all) != len(mf_mask_all):
        raise ValueError(
            f"mf_mask_all length {len(mf_mask_all)} != len(df_apr_all) {len(df_apr_all)}"
        )
    if not df_apr_all.index.equals(mf_mask_all.index):
        mf_mask_all = mf_mask_all.reindex(df_apr_all.index, fill_value=False)

    idx = df_apr_db_inc.index
    in_all = idx.isin(df_apr_all.index)
    join_match_rate = float(in_all.mean()) if len(idx) else 0.0
    print(
        f"  Rule A Poisson owner x: index_match_rate={join_match_rate:.4f} "
        f"({int(in_all.sum()):,} / {len(idx):,} db_inc rows in df_apr_all index)"
    )
    if join_match_rate < 0.999:
        print(
            "  WARNING: Rule A index match rate < 0.999 - db_inc rows missing from df_apr_all (unexpected)."
        )

    rhs_ix = df_apr_all.reindex(idx)
    co_h = pd.to_numeric(rhs_ix["units_CO"], errors="coerce").to_numpy(dtype=np.float64)
    owner_h = np.asarray(rhs_ix["is_owner"].fillna(False), dtype=bool)
    mf_h = np.asarray(mf_mask_all.reindex(idx, fill_value=False).fillna(False), dtype=bool)

    if phase_context is not None:
        ent_vec = np.asarray(
            phase_context["net_units_canonical_by_phase"]["ENT"], dtype=np.float64
        )
        if len(ent_vec) != len(df_apr_all):
            raise ValueError("Rule A attach: ENT vector length mismatch vs df_apr_all")
        ent_h = pd.Series(ent_vec, index=df_apr_all.index).reindex(idx).to_numpy(dtype=np.float64)
    else:
        ent_h = pd.to_numeric(rhs_ix.get("NO_ENTITLEMENTS"), errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)

    rule_a = owner_h & mf_h
    x_co = np.where(rule_a, co_h, np.nan).astype(np.float64)
    x_ent = np.where(rule_a, ent_h, np.nan).astype(np.float64)
    out = df_apr_db_inc.copy()
    out["x_co_mf_owner_net"] = x_co
    out["x_ent_mf_owner_net"] = x_ent
    return out


def run_poisson_db_vs_total_units(df_apr_db_inc, output_dir, all_r2_results, co_cols, bp_cols, ent_cols):
    """Run ZIP/ZINB fits for affordable DR units vs stage project totals."""
    required_base = {"DR_TYPE_CLEAN"}
    missing_base = sorted(required_base - set(df_apr_db_inc.columns))
    if missing_base:
        print(f"  ERROR: Skipping ZIP/ZINB block; missing columns: {missing_base}")
        return

    dr_co = _affordable_dr_only_colnames(co_cols)
    dr_ent = _affordable_dr_only_colnames(ent_cols)
    tier_by_phase = {"CO": dr_co, "ENT": dr_ent}
    phase_specs = [
        ("ENT", "proj_units_ENT"),
        ("CO", "proj_units_CO"),
    ]
    variant_defs = [
        (
            "DB",
            lambda d: d["DR_TYPE_CLEAN"] == "DB",
            "poisson_db_units_vs_total",
            "APR MF 5+ DB",
            {
                "scatter_label": "Projects, {phase}",
                "policy_label": LABEL_POLICY_DB_UNITS,
                "regressor_label": "net multifamily units",
                "xlabel_tpl": "Net Multifamily Units ({phase})",
                "ylabel_tpl": f"{LABEL_POLICY_DB_UNITS} ({{phase}})",
            },
        ),
        (
            "INC",
            lambda d: d["DR_TYPE_CLEAN"] == "INC",
            "poisson_inc_units_vs_total",
            "APR MF 5+ INC",
            {
                "scatter_label": "Projects, {phase}",
                "policy_label": LABEL_POLICY_INC_UNITS,
                "regressor_label": "net multifamily units",
                "xlabel_tpl": "Net Multifamily Units ({phase})",
                "ylabel_tpl": f"{LABEL_POLICY_INC_UNITS} ({{phase}})",
            },
        ),
        (
            "DB_owner",
            lambda d: (d["DR_TYPE_CLEAN"] == "DB") & d["is_owner"],
            "poisson_db_units_vs_total_owner",
            "APR MF 5+ DB for-sale",
            {
                "scatter_label": "For-Sale Projects, {phase}",
                "policy_label": LABEL_POLICY_DB_FOR_SALE_UNITS,
                "regressor_label": "net multifamily owner-occupant units",
                "xlabel_tpl": "Net Multifamily Owner-Occupant ({phase})",
                "ylabel_tpl": f"{LABEL_POLICY_DB_FOR_SALE_UNITS} ({{phase}})",
            },
        ),
        (
            "INC_owner",
            lambda d: (d["DR_TYPE_CLEAN"] == "INC") & d["is_owner"],
            "poisson_inc_units_vs_total_owner",
            "APR MF 5+ INC for-sale",
            {
                "scatter_label": "For-Sale Projects, {phase}",
                "policy_label": LABEL_POLICY_INC_FOR_SALE_UNITS,
                "regressor_label": "net multifamily owner-occupant units",
                "xlabel_tpl": "Net Multifamily Owner-Occupant ({phase})",
                "ylabel_tpl": f"{LABEL_POLICY_INC_FOR_SALE_UNITS} ({{phase}})",
            },
        ),
    ]

    if "is_owner" not in df_apr_db_inc.columns:
        print("  ERROR: Skipping owner ZIP/ZINB variants; is_owner missing.")
        variant_defs = [v for v in variant_defs if v[0] not in {"DB_owner", "INC_owner"}]

    n_appended = 0
    for variant_key, mask_fn, file_stem, geography, vkw in variant_defs:
        sub = df_apr_db_inc.loc[mask_fn(df_apr_db_inc)]
        if len(sub) == 0:
            print(f"  ERROR: Skipping ZIP/ZINB variant {variant_key}; no rows after mask.")
            continue

        for phase_tag, x_col_default in phase_specs:
            if variant_key in {"DB_owner", "INC_owner"}:
                if phase_tag == "CO":
                    x_col = "x_co_mf_owner_net"
                elif phase_tag == "ENT":
                    x_col = "x_ent_mf_owner_net"
                else:
                    x_col = x_col_default
            else:
                x_col = x_col_default
            tier_cols = [c for c in tier_by_phase[phase_tag] if c in sub.columns]
            if not tier_cols:
                print(f"  ERROR: Skipping {variant_key} {phase_tag}; no affordable _DR tier columns present.")
                continue
            if x_col not in sub.columns:
                print(f"  ERROR: Skipping {variant_key} {phase_tag}; missing {x_col}.")
                continue

            x_series = pd.to_numeric(sub[x_col], errors="coerce")
            y_series = sub[tier_cols].apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1)
            valid = (
                x_series.notna()
                & y_series.notna()
                & np.isfinite(np.asarray(x_series.values, dtype=np.float64))
                & np.isfinite(np.asarray(y_series.values, dtype=np.float64))
                & (np.asarray(y_series.values, dtype=np.float64) >= 0)
                & (np.asarray(x_series.values, dtype=np.float64) >= 0)
            )
            n_valid = int(valid.sum())
            if n_valid < 20:
                print(
                    f"  ERROR: Skipping {variant_key} {phase_tag} ZIP/ZINB fit; n={n_valid} after valid mask (<20)."
                )
                continue

            x_use = np.asarray(x_series[valid].values, dtype=np.float64)
            y_use = np.asarray(y_series[valid].values, dtype=np.float64)
            exog = sm.add_constant(np.log1p(x_use), has_constant="add")
            endog = np.asarray(y_use, dtype=np.float64)
            fit_result, model_tag = _fit_zip_or_zinb(endog, exog)
            if fit_result is None:
                print(f"  ERROR: Skipping {variant_key} {phase_tag}; ZIP and ZINB both failed.")
                continue
            infl = _zip_zinb_inflation_params(fit_result)
            lin = _zip_zinb_count_part_linear_params(fit_result)
            if infl is None or lin is None:
                print(f"  ERROR: Skipping {variant_key} {phase_tag}; unexpected parameter layout.")
                continue
            params_infl, bse_infl, pvalues_infl = infl
            params_lin, bse_lin, pvalues_lin = lin
            if params_lin.size < 2:
                print(
                    f"  ERROR: Skipping {variant_key} {phase_tag}; count-part parameter length {params_lin.size}."
                )
                continue
            slope_log1p = float(params_lin[1])
            count_se = float(bse_lin[1]) if bse_lin.size > 1 else np.nan
            count_t = slope_log1p / count_se if np.isfinite(count_se) and count_se > 0 else np.nan
            count_p = float(pvalues_lin[1]) if pvalues_lin.size > 1 else np.nan
            zero_mle = float(params_infl[0])
            zero_se = float(bse_infl[0]) if bse_infl.size > 0 else np.nan
            zero_mle_t = zero_mle / zero_se if np.isfinite(zero_se) and zero_se > 0 else np.nan
            zero_mle_p = float(pvalues_infl[0]) if pvalues_infl.size > 0 else np.nan
            pseudo_r2 = _poisson_result_pseudo_r2(fit_result)
            out_png = output_dir / f"{file_stem}_{phase_tag}.png"
            ph = PHASE_DISPLAY_BY_TAG.get(phase_tag, phase_tag)
            if "xlabel_tpl" in vkw:
                xlabel = vkw["xlabel_tpl"].format(phase=ph)
            else:
                xlabel = f"Net units ({ph})"
            ylabel = vkw["ylabel_tpl"].format(phase=ph)
            title = f"{model_tag}: {vkw['policy_label']} vs {xlabel}"
            _plot_poisson_db_vs_total_phase(
                x_use, y_use, fit_result, phase_tag, out_png, pseudo_r2, model_tag,
                scatter_label=vkw["scatter_label"].format(phase=ph),
                xlabel=xlabel,
                ylabel=ylabel,
                title=title,
            )
            reg_lbl = (
                f"ZIP/ZINB: {vkw['policy_label']} ~ log1p({vkw['regressor_label']}) ({ph}) "
                f"{model_tag} {variant_key}"
            )
            _append_zip_zinb_r2_diagnostics_row(
                all_r2_results, reg_lbl, geography, pseudo_r2,
                slope_log1p, count_t, count_p, zero_mle, zero_mle_t, zero_mle_p,
            )
            n_appended += 1
            print(f"  Saved: {out_png.name}")

    if n_appended:
        print(f"  ZIP/ZINB: appended {n_appended} row(s) to r2 diagnostics.")
    else:
        print("  ERROR: No ZIP/ZINB phase fits completed; nothing appended to r2 diagnostics.")


def run_poisson_count_models(df_apr_db_inc, output_dir, all_r2_results, co_cols, bp_cols, ent_cols):
    """Public wrapper for Poisson count-model regression block."""
    return run_poisson_db_vs_total_units(
        df_apr_db_inc,
        output_dir,
        all_r2_results,
        co_cols,
        bp_cols,
        ent_cols,
    )
