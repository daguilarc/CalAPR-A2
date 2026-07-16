## ADDED Requirements

### Requirement: Catalog-neighbor variable menus

The Models panel SHALL populate Variable (X) and Variable (Y) from exported `catalog.json` edges for the selected geography and robustness. Given a fixed Y, X options SHALL be the set of `x_col` values such that `geography:y_col:x_col:robustness` exists in the catalog (and X ≠ Y). Given a fixed X, Y options SHALL be the set of `y_col` values with a matching catalog key. The UI SHALL NOT offer variables that have no exported pair for the other axis selection.

#### Scenario: Y change filters X

- **WHEN** geography is City, robustness is `none`, and Variable (Y) is `DB_CO_total`
- **THEN** Variable (X) lists only predictors/outcomes that appear as `x_col` in catalog keys `city:DB_CO_total:*:none`
- **AND** no option produces the missing-pair empty state when selected with that Y

#### Scenario: Previously valid X dropped

- **WHEN** user changes Y so the current X is not a neighbor of the new Y
- **THEN** the UI selects a remaining valid X (deterministic first neighbor) and renders that pair’s chart

### Requirement: Model display default Both

When the selected pair has hierarchical availability, the Model display control SHALL default to **Both** on first selection of that pair. When the user changes Y or X and the previous Model display value remains available for the new pair, the UI SHALL keep that value. When hierarchical is unavailable, the only option SHALL be Two-Part MLE + Stationary Bootstrap (or equivalent stationary-only label).

#### Scenario: Hierarchical pair opens on Both

- **WHEN** user selects a two-part pair with hierarchical samples
- **THEN** Model display is **Both** unless the user already chose another still-valid mode for the session transition

#### Scenario: Continuous pair cannot keep Hierarchical

- **WHEN** user had Hierarchical or Both selected and switches to a continuous pair without hierarchical
- **THEN** Model display becomes the stationary-only option and does not show Hierarchical or Both

### Requirement: Continuous linear band view

For pairs with `model_family` continuous (or equivalent continuous export), the Models chart SHALL plot the MLE mean and stationary bootstrap interval from the **positive_only** (linear) views, not the two_part_hurdle hurdle transform. Two-part pairs SHALL continue to use the Zero Values control (`two_part_hurdle` vs `positive_only`) as today.

#### Scenario: Continuous bootstrap tracks MLE

- **WHEN** user views a continuous city pair with Model display including stationary bootstrap
- **THEN** the bootstrap band surrounds the MLE line (not systematically ~½ the MLE slope)

### Requirement: Chart sizing and axis ranges

The Models chart SHALL use a fixed Plotly height of 560px (or equal to the prior interactive_viz contract). Switching to the Models tab SHALL resize the chart if it was plotted while hidden. Axis ranges SHALL be derived from `x_grid` and from observation and curve y-values with modest padding; for two-part displays that include zeros, y-axis lower bound SHALL be ≤ 0 only as required by data, preferring non-negative y when all plotted y ≥ 0 like the PNG explorer charts.

#### Scenario: First open Models after Maps

- **WHEN** the page loads on Maps then the user opens Models
- **THEN** the chart is full-width height ~560px, not a tiny stub from `display:none` measurement

### Requirement: Observation and hierarchical legend copy

Scatter points SHALL be legend-labeled **Cities** or **ZIP codes** according to the selected Models geography (or catalog `data_label` when present). Hierarchical mean legend text SHALL be **Posterior Predictive Mean (with county-level random effects)**. Hierarchical interval legend text SHALL describe a posterior/credible interval (not the bare string "Hierarchical Bayes" alone).

#### Scenario: City geography legend

- **WHEN** Models geography is City and hierarchical display is on
- **THEN** the legend includes **Cities** and **Posterior Predictive Mean (with county-level random effects)**

### Requirement: Observation hover names

When jurisdiction names are available on catalog point arrays, hovering a scatter observation SHALL show that jurisdiction’s name.

#### Scenario: Hover city point

- **WHEN** user hovers an observation on a city model chart with names present
- **THEN** the hover label includes the city name

### Requirement: Robustness Checks label

The Models robustness control label SHALL read **Robustness Checks**. Catalog key `none` SHALL display as a human-readable option (e.g. **None**), not the raw token `none`.

#### Scenario: Robustness control chrome

- **WHEN** user views the Models panel
- **THEN** the control is labeled **Robustness Checks** and the selected option text is not the bare string `none`

### Requirement: Multifamily 5+ explorer framing

The vintage header SHALL read **HCD APR data: 2018–2024, projects with 5+ dwelling units**. Shipped release artifacts (`catalog.json`, `map_metrics.json`) SHALL contain only multifamily-scoped outcome streams. Non-MF housing outcomes SHALL NOT appear in the explorer release: `TOTAL_*`, `total_owner_*`, and ZIP all-housing `net_CO` / `net_BP` / `net_ENT`. Multifamily streams (`TOTAL_MF_*`, `mf_owner_*`, `net_MF_*`, deed-restricted MF streams) SHALL remain. Authoring `docs/chart_labels.json` partitions MAY retain non-MF labels for the export pipeline; the explorer SHALL NOT ship those outcome keys.

#### Scenario: Header text

- **WHEN** user loads the explorer
- **THEN** the subtitle under the h1 includes **projects with 5+ dwelling units**

#### Scenario: All-housing absent from shipped catalog

- **WHEN** user loads the archived release
- **THEN** `catalog.json` contains no keys where `x_col` or `y_col` is `TOTAL_CO_total` or `total_owner_CO_total`
- **AND** `map_metrics.json` contains no entries for `TOTAL_CO_total` or `total_owner_CO_total`

#### Scenario: MF outcomes available

- **WHEN** user opens Variable (Y) for City
- **THEN** `TOTAL_MF_CO_total` and `mf_owner_CO_total` remain selectable when present in the pruned catalog-neighbor set

### Requirement: Models Geography control scope

The city/ZIP **Geography** control (`#geo`) SHALL be rendered inside the Models panel only, not in the shared tab row above Maps/Models tabs. The Maps tab SHALL show **Geography view** (`#map-geography`) and **Map metric** only.

#### Scenario: Maps tab hides city ZIP geo

- **WHEN** user is on the Maps tab
- **THEN** the Models Geography (City/ZIP) control is not visible
- **AND** Geography view remains visible

#### Scenario: Models tab shows city ZIP geo

- **WHEN** user is on the Models tab
- **THEN** the Geography (City/ZIP) control is visible inside the Models panel

### Requirement: Shared Maps Models control grid

Maps panel controls (Geography view, Map metric) SHALL use the same CSS grid column template as Models panel controls so the two Maps dropdowns align horizontally the same way Models dropdowns align.

#### Scenario: Desktop Maps alignment

- **WHEN** viewport is wide enough for two columns
- **THEN** Geography view and Map metric share equal columns matching Models’ two-column grid

## MODIFIED Requirements

### Requirement: Symmetric variable dropdowns

The explorer SHALL populate Variable (X) and Variable (Y) from catalog-neighbor sets for the selected geography and robustness (see Catalog-neighbor variable menus). Identity pairs remain excluded. Dropdown options SHALL be derived from catalog key co-occurrence for the active geo and robustness. Labels for those keys SHALL still resolve from `chart_labels.variables` (with partition fallback).

#### Scenario: Same universe replaced by neighbors

- **WHEN** geography is City and Variable (Y) is `income_delta_pct_change`
- **THEN** Variable (X) lists only catalog neighbors of that Y, each with a display label from `chart_labels`
- **AND** every listed X yields a rendered chart for that Y

### Requirement: Dropdowns from catalog keys

The Pages explorer UI SHALL populate geography and robustness dropdowns from values present in `catalog.json` or release manifest. Variable (`y_col`) and Variable (`x_col`) dropdowns SHALL be populated from catalog edges for the selected geography and robustness, with labels from `chart_labels.json`.

#### Scenario: Label without catalog edge omitted

- **WHEN** `chart_labels.json` defines a variable with zero exported catalog edges for the selected geography and robustness
- **THEN** that variable does not appear in Variable (X) or Variable (Y)
