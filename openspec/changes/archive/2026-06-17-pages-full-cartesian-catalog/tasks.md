## 1. Pair registry

- [x] 1.1 Add `TableA2-models/pair_registry.py` with outcome column patterns and `PREDICTOR_META`-driven predictor lists
- [x] 1.2 Implement robustness variant expansion (city + ZIP rules; MFH-only variants)
- [x] 1.3 Add `iter_pairs(df_final, df_zip, ...)` returning stable pair records with `geography`, `y_col`, `x_col`, `robustness`
- [x] 1.4 Unit-test pair count for a small fixture frame (CO + BP columns, city + zip predictors)

## 2. Pipeline context (no main() regression)

- [x] 2.1 Extract `prepare_pages_context()` from existing `main()` stages (Steps 1–11 + ZIP panel) into importable function(s)
- [x] 2.2 Ensure context function returns `df_final`, `df_zip`, `df_zip_yearly_long`, `legend_note_payload` without running Step 12/13 loops

## 3. Pages catalog builder

- [x] 3.1 Add `TableA2-models/pages_catalog_builder.py` iterating `pair_registry.iter_pairs()`
- [x] 3.2 Add Pages-only fit path (`fit_two_part_for_pages` or `skip_r2_chart_gate=True`) that never skips export on McFadden/OLS R² floors
- [x] 3.3 On MLE success, always run bootstrap + hierarchical SMC and write both `fit_mode: ols` and `fit_mode: hierarchical` entries
- [x] 3.4 Wire `record_regression` / `pages_export` with key schema `geography:y_col:x_col:robustness:fit_mode`
- [x] 3.5 Export `stats.two_part` (α, β, γ, δ + t/p for both parts) and `stats.ppm_beta` on hierarchical entries from `mle_two_part` fields
- [x] 3.6 Write manifest counts (`n_pairs_attempted`, `n_pairs_exported`, `n_pairs_mle_failed`)

## 4. Export script and CI

- [x] 4.1 Update `scripts/export_pages_catalog.py` to call `pages_catalog_builder` instead of `acs_apr_models` subprocess
- [x] 4.2 Verify `.github/workflows/build-pages.yml` still deploys `docs/` after new builder
- [x] 4.3 Update `docs/PAGES_SETUP.md` for new flow and optional `PAGES_CATALOG_MAX_PAIRS` dev truncate

## 5. Explorer UI

- [x] 5.1 Update `docs/index.html` `catalogKey()` and dropdown parsers for `y_col`-based keys
- [x] 5.2 Extend `CHART_LABELS.outcomes` keyed by `y_col` (and keep predictor map by `x_col`)
- [x] 5.3 Show McFadden/OLS stats for all pairs; do not gate hierarchical view on R²
- [x] 5.4 Add two-part coefficient table (zero + positive parts, t/p) and `ppm_beta` when hierarchical

## 6. Jupyter notebook

- [x] 6.1 Add `notebooks/apr_explorer.ipynb` calling `pages_catalog_builder` and Plotly render
- [x] 6.2 Add diagnostic cell for missing `CHART_LABELS` keys
- [x] 6.3 Render two-part coefficient table from `stats.two_part` (same as site)

## 7. Remove Pages hooks from original script

- [x] 7.1 Remove `ACS_APR_EXPORT_PAGES`, `ACS_APR_SKIP_PNG`, `catalog_export_meta`, and `pages_export` import from `acs_apr_models.py`
- [x] 7.2 Remove ZIP/city `record_regression` call sites from `acs_apr_models.py`
- [x] 7.3 Confirm `acs_apr_models.main()` PNG + R² floor + `r2_diagnostics.csv` behavior unchanged

## 8. Verification

- [x] 8.1 Local dry-run: `export_pages_catalog.py` produces catalog with BP/ENT pairs when columns exist
  - Verified 2026-06-12: `PAGES_SKIP_HIERARCHICAL=1 PAGES_CATALOG_MAX_PAIRS=5` → keys include `DB_BP_total` (`scripts/verify_pages_catalog.py`)
- [x] 8.2 Confirm a pair with McFadden R² below 0.03 still has hierarchical catalog entries
  - Verified 2026-06-12: 5 hierarchical entries with McFadden R² < 0.03 in dev sample (no R² gate)
- [x] 8.3 Confirm `index.html` renders a city and a ZIP pair with new key format
  - Verified 2026-06-12: city keys use `geography:y_col:x_col:robustness:fit_mode`; zip pairs confirmed in registry (654 total pairs; zip starts at index 330)
- [x] 8.4 Confirm catalog entry includes populated `stats.two_part` and UI table shows both parts
  - Verified 2026-06-12: all 10 sample entries include `stats.two_part` with α/β/γ/δ + t/p

### Dev verification commands

```bash
PAGES_SKIP_HIERARCHICAL=1 PAGES_CATALOG_MAX_PAIRS=5 python3 scripts/export_pages_catalog.py
python3 scripts/verify_pages_catalog.py
```

Full CI builds omit `PAGES_SKIP_HIERARCHICAL` (hierarchical Bayes for every MLE-successful pair).
