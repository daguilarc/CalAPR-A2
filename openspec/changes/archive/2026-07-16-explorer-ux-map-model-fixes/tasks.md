## 1. Map geometry

- [x] 1.1 Decouple water clip from tiger skip in `TableA2-models/pages/db_maps.py` (`load_water_mask` / `_boundary_mode`) so `PAGES_BUILD=1` still clips when ocean shp exists
- [x] 1.2 Build `county_residual` geometries as county.difference(union of cities in county) before concat in `assemble_plot_frame` / export path
- [x] 1.3 Add unit tests for residual area < whole county and water clip under `PAGES_BUILD=1` with fixture ocean when feasible

## 1b. MF-only release export

- [x] 1b.1 In `TableA2-models/pages/map_metric_registry.py`, exclude non-MF streams (`TOTAL_*`, `total_owner_*`) from `build_map_metric_registry` candidates
- [x] 1b.2 In `scripts/export_pages_catalog.py` (or catalog finalize), drop catalog keys where `x_col` or `y_col` matches `TOTAL_*`, `total_owner_*`, or ZIP `net_CO` / `net_BP` / `net_ENT`; refresh `manifest.json` `catalog_keys`
- [x] 1b.3 Regenerate `docs/data/releases/2018-2024/` (`catalog.json`, `map_metrics.json`, `maps.geojson`, `manifest.json`) after geometry + prune changes

## 2. Maps UI chrome

- [x] 2.1 Set choropleth `marker.opacity` to 0.92 in `docs/index.html` `renderMap`
- [x] 2.2 Move Models `#geo` from shared `.tab-row` into `#panel-models` so City/ZIP geography is not visible on Maps tab
- [x] 2.3 Apply shared Models grid CSS to Maps controls so Geography view and Map metric align

## 3. Models pairing and display

- [x] 3.1 Implement catalog-neighbor X/Y option builders; wire `settleModelControls` to use them
- [x] 3.2 Default model-display to `both` when hierarchical available; preserve prior selection when still valid
- [x] 3.3 For continuous pairs, plot MLE + bootstrap from `positive_only` views
- [x] 3.4 On missing pair: purge Plotly and collapse empty 580px bordered frame (should be rare after 3.1)
- [x] 3.5 Fixed height 560, margins, axis ranges from data/curves; `Plotly.Plots.resize` on Models tab show
- [x] 3.6 Skip initial `renderModel` while Models panel is hidden, or resize immediately when opening Models

## 4. Copy and legends

- [x] 4.1 Header: `HCD APR data: 2018–2024, projects with 5+ dwelling units`
- [x] 4.2 Legend: Cities/ZIP codes; PPM hierarchical wording; observation hover names when present
- [x] 4.3 Label **Robustness Checks**; display `none` as **None**

## 5. Verification

- [x] 5.1 Update `tests/test_interactive_map_explorer.py` (and e2e if present) for `#geo` placement, neighbors, continuous band, header, MF-only release artifacts, opacity/grid contracts
- [x] 5.2 Local smoke: `python3 -m http.server` in `docs` — Monterey shoreline, continuous band tracks MLE, Models dropdowns only valid pairs, Maps tab shows Geography view + Map metric only (no City/ZIP selector)
