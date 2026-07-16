# pages-catalog-builder Specification

## Purpose
TBD - created by archiving change pages-full-cartesian-catalog. Update Purpose after archive.
## Requirements
### Requirement: Standalone from acs_apr_models.main

The pages catalog builder SHALL produce `catalog.json` and `manifest.json` without invoking `acs_apr_models.main()` or mutating original-script regression loops, PNG output, or `r2_diagnostics.csv`.

#### Scenario: CI export path

- **WHEN** `scripts/export_pages_catalog.py` runs in GitHub Actions
- **THEN** it calls `pages_catalog_builder` only and does not set `ACS_APR_EXPORT_PAGES`

### Requirement: No R² chart floors for Pages export

The pages catalog builder SHALL NOT apply McFadden R² ≥ 0.03 or OLS R² (y>0) ≥ 0.20 as conditions for exporting hierarchical Bayes results. Those thresholds apply only to the original script's PNG/chart policy.

#### Scenario: Sub-threshold hierarchical still exported

- **WHEN** McFadden R² is 0.01 and OLS R² is 0.15 but MLE two-part fit succeeds
- **THEN** the builder writes both `fit_mode: ols` and `fit_mode: hierarchical` catalog entries with stats reflecting the low R² values

#### Scenario: Original script unchanged

- **WHEN** `acs_apr_models.main()` runs a regression for PNG output
- **THEN** it continues to skip chart/CI emission when R² floors are not met (unchanged behavior)

### Requirement: Export on MLE success only

The builder SHALL omit a catalog row only when MLE two-part fit fails or insufficient data (jurisdiction count below minimum). R² magnitude SHALL NOT cause omission.

#### Scenario: MLE failure

- **WHEN** MLE two-part returns no fit for a registry pair
- **THEN** the builder writes no catalog entry for that pair

### Requirement: Stats recorded regardless of R²

Each exported catalog entry SHALL include McFadden R² and OLS R² (y>0) in `stats` when computable, for UI display only.

#### Scenario: Stats on weak fit

- **WHEN** a pair exports with McFadden R² below 0.03
- **THEN** `stats.mcfadden_r2` reflects the actual value and hierarchical chart data is still present

### Requirement: Full two-part MLE diagnostics exported

Each exported catalog entry SHALL include a `stats.two_part` object with MLE coefficients and inferential statistics for both parts of the model, sourced from `mle_two_part` / fit result:

- **Zero / hurdle part (logit):** `alpha`, `beta`, `beta_t`, `beta_p` (from `alpha_mle`, `beta_mle`, `zero_mle_t`, `zero_mle_p`)
- **Positive part:** `intercept`, `slope`, `slope_t`, `slope_p` (from `intercept_mle`, `slope_mle`, `positive_part_t`, `positive_part_p`)

The same `stats.two_part` values SHALL appear on both `fit_mode: ols` and `fit_mode: hierarchical` entries for a given pair (shared MLE fit).

#### Scenario: Zero and positive part coefficients present

- **WHEN** MLE two-part fit succeeds for a registry pair
- **THEN** each catalog entry for that pair includes `stats.two_part.alpha`, `stats.two_part.beta`, `stats.two_part.intercept`, and `stats.two_part.slope` as finite floats or null when not computable

#### Scenario: t-stats and p-values present

- **WHEN** MLE two-part fit succeeds and inferential stats are computed
- **THEN** `stats.two_part.beta_t`, `stats.two_part.beta_p`, `stats.two_part.slope_t`, and `stats.two_part.slope_p` are populated

### Requirement: Hierarchical posterior mean slope

Catalog entries with `fit_mode: hierarchical` SHALL include `stats.ppm_beta` (posterior predictive mean slope) when hierarchical samples exist.

#### Scenario: PPM beta on hierarchical entry

- **WHEN** hierarchical SMC returns `slope_samples` for a pair
- **THEN** the hierarchical catalog entry includes `stats.ppm_beta` as the mean of those samples

### Requirement: Catalog key schema

Catalog keys SHALL use the format `geography:y_col:x_col:robustness:fit_mode`.

#### Scenario: Key lookup

- **WHEN** geography is `zip`, `y_col` is `net_MF_CO`, `x_col` is `zhvi_condo_pct_change`, robustness is `none`, fit_mode is `hierarchical`
- **THEN** the catalog key is `zip:net_MF_CO:zhvi_condo_pct_change:none:hierarchical`

### Requirement: Series without axis titles

Catalog plotly payloads SHALL omit `xaxis.title` and `yaxis.title` from stored layout; axis labels are applied at render time.

#### Scenario: Layout shape

- **WHEN** a catalog entry is written
- **THEN** `plotly.layout` does not contain baked axis title strings

### Requirement: Manifest statistics

`manifest.json` SHALL record `built_at`, `n_pairs_attempted`, `n_pairs_exported`, `n_pairs_mle_failed`, and `pair_registry_version`.

#### Scenario: Build summary

- **WHEN** the builder completes
- **THEN** manifest includes pair counts and does not reference R²-gated tiers

