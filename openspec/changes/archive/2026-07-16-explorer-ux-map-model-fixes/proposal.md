## Why

The live APR Explorer (Maps + Models) has broken shoreline geometry, washed-out choropleths, Models controls leaking onto Maps, invalid X/Y pairs, continuous-model bootstrap bands at ~½ the MLE line, Plotly sizing/range bugs, and a release that still ships all-housing outcome streams despite 5+ multifamily framing. These block trustworthy review of the cartesian 2018–2024 release without another full model refit.

## What Changes

- Clip ocean water from place/county boundaries under Pages builds; punch city holes into `county_residual` geometries; regenerate `maps.geojson`.
- Raise choropleth opacity; keep Positron basemap.
- Move Models **Geography** (City/ZIP `#geo`) into the Models panel so Maps shows **Geography view** + **Map metric** only; align Maps control grid with Models.
- Models: catalog-neighbor X/Y menus only; default Model display to **Both** when hierarchical exists and preserve selection across variable changes when still valid.
- Continuous pairs: plot linear MLE + `positive_only` bootstrap (not hurdle with α=β=0).
- Fixed chart height, resize on tab show, axis ranges from data/curves (PNG-aligned).
- Legends: Cities/ZIP codes + hover names; Posterior Predictive Mean (county REs); **Robustness Checks**.
- Header: `HCD APR data: 2018–2024, projects with 5+ dwelling units`.
- **MF-only shipped release:** prune non-multifamily outcomes from `catalog.json`, `manifest.json`, and `map_metrics.json` at export; regenerate release artifacts. Authoring `chart_labels.json` partitions unchanged.

No statistical refit / SMC rebuild. No CI Python pin change.

## Capabilities

### New Capabilities

- `explorer-map-geometry`: Pages ocean water clip and county_residual city punch-out for `maps.geojson`.

### Modified Capabilities

- `pages-explorer-ui`: Maps/Models chrome, catalog-neighbor pairing menus, model display defaults, continuous band view, chart layout/legends, header, MF-only release scope, robustness label.
- `explorer-map-interaction`: choropleth opacity/contrast.

## Impact

- [`docs/index.html`](docs/index.html) — primary UI behavior.
- [`TableA2-models/pages/db_maps.py`](TableA2-models/pages/db_maps.py) — boundary clip / residual geometry / geojson export.
- [`TableA2-models/pages/map_metric_registry.py`](TableA2-models/pages/map_metric_registry.py) — exclude non-MF streams from map metrics.
- [`scripts/export_pages_catalog.py`](scripts/export_pages_catalog.py) — prune non-MF catalog keys at finalize.
- Release artifacts under `docs/data/releases/2018-2024/` — regenerate pruned `catalog.json`, `map_metrics.json`, `maps.geojson`, `manifest.json`.
- Tests: `tests/test_interactive_map_explorer.py`, e2e explorer specs if present.
