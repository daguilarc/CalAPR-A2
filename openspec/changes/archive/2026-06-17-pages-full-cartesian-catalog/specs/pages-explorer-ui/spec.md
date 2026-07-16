## ADDED Requirements

### Requirement: Dropdowns from catalog keys

The Pages explorer UI SHALL populate geography, outcome (`y_col`), predictor (`x_col`), robustness, and fit mode dropdowns from keys present in `catalog.json`.

#### Scenario: New outcome appears after CI

- **WHEN** `catalog.json` contains keys with `y_col: net_BP`
- **THEN** the outcome dropdown includes `net_BP` without code changes beyond `CHART_LABELS`

### Requirement: Axis labels from CHART_LABELS

The UI SHALL resolve x-axis and y-axis titles from `CHART_LABELS` in `docs/index.html` using `entry.x_col`, `entry.y_col`, `entry.is_log_x`, and `entry.x_axis_filter_note`.

#### Scenario: Label edit without catalog rebuild

- **WHEN** a developer changes `CHART_LABELS.predictors.zori_pct_change` in `index.html` and deploys
- **THEN** charts show the updated x-axis label without re-running the catalog builder

### Requirement: R² stats displayed not gated

The UI SHALL display McFadden R² and OLS R² from catalog `stats` without hiding hierarchical charts based on R² thresholds.

#### Scenario: Low R² hierarchical view

- **WHEN** user selects hierarchical fit mode for a pair with McFadden R² below 0.03
- **THEN** the UI renders the pre-computed hierarchical chart and shows the actual R² values in the stats line

### Requirement: Two-part coefficient table

The UI SHALL display a diagnostics table below the model chart showing both parts of the two-part MLE fit from `stats.two_part`:

- Zero / hurdle: α, β, t(β), p(β)
- Positive part: γ (intercept), δ (slope), t(δ), p(δ)

When `fit_mode` is hierarchical and `stats.ppm_beta` is present, the UI SHALL also show posterior predictive mean β.

#### Scenario: Both parts visible

- **WHEN** user selects any exported pair with a populated `stats.two_part`
- **THEN** the stats area shows coefficient and t/p columns for zero and positive parts

#### Scenario: OLS vs hierarchical share MLE coefficients

- **WHEN** user toggles between OLS and hierarchical fit mode for the same pair
- **THEN** the two-part MLE coefficient table is identical; hierarchical mode additionally shows `ppm_beta` when available

### Requirement: Catalog key alignment

The UI `catalogKey()` function SHALL match the builder key format `geography:y_col:x_col:robustness:fit_mode`.

#### Scenario: Successful chart render

- **WHEN** user selects options matching an exported key
- **THEN** Plotly renders the pre-computed series with labels applied
