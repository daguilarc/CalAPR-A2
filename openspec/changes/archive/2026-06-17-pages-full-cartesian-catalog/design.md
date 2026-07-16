## Context

GitHub Pages serves `docs/index.html` + pre-baked `docs/data/catalog.json`. CI runs `scripts/export_pages_catalog.py`, which today subprocesses `acs_apr_models.main()` with `ACS_APR_EXPORT_PAGES=1`. That piggybacks on hardcoded regression loops and reuses `fit_two_part_with_ci`, which applies McFadden ≥ 0.03 and OLS R² ≥ 0.20 as **chart export gates**.

The original `acs_apr_models.py` script remains the authoritative batch job for PNG charts and R² diagnostics for publication. Those R² floors stay there. Pages and Jupyter are **consumers** with different policy: exhaustive pairs, hierarchical for every successful fit.

## Goals / Non-Goals

**Goals:**

- Generate the **full Cartesian product** of registered outcomes × predictors × geographies × robustness variants defined in `pair_registry.py`.
- Single Pages catalog builder used by **GitHub Actions** and **Jupyter notebook**.
- **No R² export gates** in the Pages builder: MLE success → export OLS + hierarchical (when SMC/bootstrap can run); record McFadden, OLS R², and full two-part MLE coefficients/t/p in `stats` for the UI only.
- Catalog entries keyed by `y_col`, `x_col`, `geography`, `robustness`, `fit_mode`.
- Axis labels applied at render time from `CHART_LABELS` in `index.html`.

**Non-Goals:**

- Changing `acs_apr_models.main()` regression selection, PNG paths, R² floors, or R² CSV content.
- Live on-demand PyMC refit in the browser.
- Committing raw `tablea2.csv`, NHGIS extracts, or boundary shapefiles.
- Rate-on-rate pairs in v1 (can add to registry in follow-up).

## Decisions

### 1. Dedicated `pages_catalog_builder.py` instead of `ACS_APR_EXPORT_PAGES`

**Choice:** New module loads prepared DataFrames, iterates `pair_registry.iter_pairs()`, fits via a Pages-specific path.

**Alternatives:** Keep hooks in `acs_apr_models.py` — rejected; user scope excludes modifying the original script's behavior.

### 2. Pair registry from column metadata, not hand lists

**Choice:** `pair_registry.py` builds outcomes from column patterns × `PREDICTOR_META` predictors × robustness variants.

### 3. Separate fit function for Pages — no R² chart floors

**Choice:** Add `fit_two_part_for_pages(...)` (or `fit_two_part_with_ci(..., skip_r2_chart_gate=True)`) used **only** by `pages_catalog_builder`. It:

- Runs MLE two-part on the pair
- On MLE success, runs bootstrap + hierarchical SMC (same as post-gate path in the original function)
- **Never** returns early because McFadden < 0.03 or OLS R² < 0.20
- Writes McFadden and OLS R² into catalog `stats`
- Writes two-part MLE diagnostics from `mle_two_part` into catalog `stats.two_part`

**Original script:** `fit_two_part_with_ci` unchanged; still gates PNG/CI at R² floors for publication.

**Rationale:** Website is an exploration surface; users choose pairs and interpret stats themselves. Floors are for which charts go in the paper, not which models exist on the site.

### 4. Two-part stats block in catalog

**Choice:** Each catalog entry carries a `stats.two_part` object (same MLE fit for OLS and hierarchical keys; hierarchical entries also carry `stats.ppm_beta`):

| Field | Source (`mle_two_part`) | Part |
|-------|-------------------------|------|
| `alpha`, `beta` | `alpha_mle`, `beta_mle` | Zero / hurdle (logit) |
| `beta_t`, `beta_p` | `zero_mle_t`, `zero_mle_p` | Zero part inferential |
| `intercept`, `slope` | `intercept_mle`, `slope_mle` | Positive part (γ, δ) |
| `slope_t`, `slope_p` | `positive_part_t`, `positive_part_p` | Positive part inferential |

Top-level `stats.mcfadden_r2`, `stats.ols_r2` unchanged. UI renders a compact table below the chart.

**Alternatives:** Rely on `r2_diagnostics.csv` — rejected; explorer must be self-contained from `catalog.json`.

### 5. Catalog key schema

**Choice:** `geography:y_col:x_col:robustness:fit_mode`.

### 6. Labels in `index.html`, not generated JSON

**Choice:** `CHART_LABELS` keyed by `y_col` / `x_col`; no `axis_labels.json`.

### 7. Data preparation reuse

**Choice:** `prepare_pages_context()` returns panels without running Step 12/13 regression loops from `main()`.

### 8. CI scale

**Choice:** Single workflow job with caching; optional `PAGES_CATALOG_MAX_PAIRS` and `PAGES_CATALOG_PAIR_OFFSET` for dev. **HB runs for every MLE-successful pair** (no R² skip). Dev dry-runs set `PAGES_SKIP_HIERARCHICAL=1` to skip bootstrap/SMC while still exporting OLS + hierarchical catalog entries (hierarchical CIs empty until full CI build).

**Risk:** Full Cartesian × HB may exceed 6h — shard in follow-up if needed.

### 9. Pair registry version

**Choice:** `PAIR_REGISTRY_VERSION` constant in `pair_registry.py`; written to `manifest.json` as `pair_registry_version`.

### 10. Jurisdiction filtering

**Choice:** `iter_pairs()` emits all column-valid combinations; minimum-jurisdiction filtering happens at fit time in `pages_catalog_builder` (`n_mle_failed` counts insufficient-data skips as well as MLE failures).

## Risks / Trade-offs

- **[Risk] CI runtime explosion** → Mitigation: cache panels; manifest logs `n_pairs_attempted` / `n_pairs_exported`; optional sharding; dev truncate env.
- **[Risk] Large `catalog.json`** → Mitigation: no baked axis titles; consider geography shards in v2.
- **[Risk] Weak models on site** → Mitigation: UI shows McFadden/OLS stats; user interprets; publication PNGs still gated in original script.
- **[Risk] Breaking catalog keys** → Mitigation: one-time redeploy with new schema.

## Migration Plan

1. Implement `pair_registry` + `pages_catalog_builder` with no-threshold fit path.
2. Point `export_pages_catalog.py` at builder.
3. Update `index.html` keys + `CHART_LABELS`.
4. Add `notebooks/apr_explorer.ipynb`.
5. Remove `ACS_APR_EXPORT_PAGES` hooks from `acs_apr_models.py`.
6. Re-run GitHub Actions Pages build.

## Open Questions

- Include rate-on-rate pairs in v1 registry or defer? **Deferred** (non-goal for v1).
- Shard CI by geography if pair count × HB exceeds timeout? **Open** — monitor first full build.
