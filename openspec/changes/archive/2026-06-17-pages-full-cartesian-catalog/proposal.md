## Why

The GitHub Pages explorer and planned Jupyter notebook must let users browse **every definable outcome × predictor combination** (city and ZIP, all phases, robustness variants)—not the small hardcoded subset wired into `acs_apr_models.py` today. The static site currently inherits whatever `main()` happens to fit and export via `ACS_APR_EXPORT_PAGES`; that couples Pages to the original analysis script and omits most column pairs.

## What Changes

- **New Pages-only export pipeline** (`pages_catalog_builder.py` + `export_pages_catalog.py`): builds `catalog.json` from a generated pair registry. Does **not** change `acs_apr_models.main()` loops, PNG output, or `r2_diagnostics.csv` from the original script.
- **Full Cartesian product** from declarative registries: outcomes (all APR rate/unit columns × phases) × predictors (`PREDICTOR_META` + geo applicability) × geographies (city, ZIP) × robustness variants × fit modes (OLS, hierarchical).
- **No R² chart floors for Pages/Jupyter**: McFadden ≥ 0.03 and OLS R² ≥ 0.20 remain **publication PNG policy** in the original script only. The website builder **does not** apply those thresholds—every pair in the registry that MLE-fits successfully exports **both** OLS and hierarchical Bayes catalog entries. McFadden and OLS R² are stored in `stats` for display, not as export gates.
- **Full two-part diagnostics in catalog**: each exported pair includes MLE coefficients and inferential stats for **both** parts—zero/hurdle (α, β, t, p) and positive-part (γ intercept, δ slope, t, p)—matching `r2_diagnostics.csv` fields, plus `ppm_beta` on hierarchical entries.
- **Decouple axis labels**: `catalog.json` stores series + keys (`y_col`, `x_col`, `geography`, …); display strings live in `docs/index.html` `CHART_LABELS` (editable without re-running CI).
- **Catalog key generalization**: **BREAKING** for existing keys — `geography:y_col:x_col:robustness:fit_mode` so arbitrary outcome columns map without hand-maintained lists.
- **Jupyter notebook** (`notebooks/apr_explorer.ipynb`): same builder as CI; local dry-run and interactive charts from pre-built or freshly built `catalog.json`.
- **Remove `ACS_APR_EXPORT_PAGES` hooks** from `acs_apr_models.py` after the dedicated builder lands (original script returns to single purpose).
- **CI workflow** calls the new builder only; no subprocess of full `acs_apr_models.main()` for catalog.

### Incorporating prior audit findings

| Finding | How this change addresses it |
|--------|------------------------------|
| Hardcoded `dr_specs`, `zip_outcomes`, `city_file_tag` | Replaced by `pair_registry.py` derived from column metadata |
| CO-only `cat_specs`; missing BP/ENT | Registry includes all `UNIT_CATEGORIES` phases where data columns exist |
| ZIP missing `income_delta`, `population_delta` | Predictors filtered by `geo_applicability`, not duplicate hardcoded lists |
| `fit_two_part_with_ci` R² gate → no catalog row | Pages builder calls a **no-threshold** fit path; original script unchanged |
| Labels baked in Plotly layout | Layout omits axis titles; `CHART_LABELS` in `index.html` |
| ZIP catalog only wired in one function | Unified `record_regression` in Pages builder for city + ZIP |
| Catalog shows only McFadden, OLS R², δ slope | `stats.two_part` exports full α/β/γ/δ + t/p for both parts |

## Capabilities

### New Capabilities

- `pair-registry`: Declarative enumeration of all outcome × predictor × geography × robustness combinations from data columns and `PREDICTOR_META`.
- `pages-catalog-builder`: Standalone pipeline that loads prepared panels, runs fits **without R² export gates**, writes `catalog.json` + `manifest.json`; shared by CI and notebook.
- `pages-explorer-ui`: Static `docs/index.html` dropdowns driven by catalog keys; axis labels from `CHART_LABELS`; R² + full two-part coefficient table shown, not used to hide hierarchical results.
- `apr-explorer-notebook`: Jupyter notebook invoking the same builder and rendering Plotly from `catalog.json`.

### Modified Capabilities

- (none — no existing `openspec/specs/` baseline in repo)

## Impact

- **New**: `TableA2-models/pair_registry.py`, `TableA2-models/pages_catalog_builder.py`, `notebooks/apr_explorer.ipynb`
- **Modified**: `scripts/export_pages_catalog.py`, `docs/index.html`, `TableA2-models/pages_export.py`, `.github/workflows/build-pages.yml`, `docs/PAGES_SETUP.md`
- **Removed** (after migration): `ACS_APR_EXPORT_PAGES`, `ACS_APR_SKIP_PNG`, `catalog_export_meta` hooks in `acs_apr_models.py`
- **Unchanged**: `acs_apr_models.main()` regression loops, R² floors for PNG charts, `r2_diagnostics.csv`
