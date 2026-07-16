## Context

Cartesian 2018–2024 release is staged in `docs/data/releases/2018-2024/` (668 catalog keys). Explorer bugs are mostly client + map-export, not missing fits. Continuous pairs ship `α=β=0` with hurdle-shaped bootstrap views; UI plots `two_part_hurdle` by default. Pages builds set `PAGES_BUILD=1` which forces tiger boundary mode and **disables** ocean clipping. Residual county polygons are full counties. Models `#geo` (City/ZIP) sits in the shared tab row and leaks onto Maps even though Maps only supports city/county layer modes.

Constraints: no statistical refit / SMC rebuild; prune shipped release artifacts to MF scope; `docs/chart_labels.json` authoring partitions unchanged.

## Goals / Non-Goals

**Goals:**
- Shoreline-correct land polygons and residual = county − cities.
- Readable choropleth; Maps/Models control separation and aligned grids.
- Only exported catalog pairs selectable; continuous bands track MLE; chart size/ranges match interactive_viz/PNG intent.
- MF 5+ framing in header and **shipped release artifacts**; clearer legends and Robustness Checks.
- Models Geography (`#geo`) inside Models panel only.

**Non-Goals:**
- Re-running hierarchical/bootstrap for all pairs.
- Deleting TOTAL/total_owner from authored `chart_labels.json` partitions.
- Changing CI Python 3.11.14 pin.
- Runtime UI hide-lists for non-MF outcomes (data layer owns scope).
- OpenSpec-only work without code (artifacts accompany implementation).

## Decisions

1. **Water clip vs tiger mode** — Tiger remains boundary download source; water mask loads whenever `*ocean*.shp` exists, including `PAGES_BUILD=1`. Rationale: prior coupling “Pages ⇒ skip water” caused ocean fill.

2. **Residual geometry** — `county_residual` geometry = county.difference(union(cities in county)), matching numeric residual rates. Rationale: painting full counties for residual lied about unincorporated extent.

3. **Continuous bands without export rewrite** — UI selects `views.positive_only` for `model_family === "continuous"` (infer if needed). Rationale: catalog already has aligned positive_only; avoids refit. Optional later: export continuous bootstrap as linear-only.

4. **Valid-pair menus** — X given Y (and reverse) from catalog edges for geo+robustness. **BREAKING** vs prior “Symmetric variable dropdowns” which forbade catalog co-occurrence. Rationale: empty/missing-pair UX was unacceptable.

5. **MF-only shipped release (not UI filter)** — Drop catalog keys where `x_col` or `y_col` is a non-MF housing outcome (`TOTAL_*`, `total_owner_*`, ZIP `net_CO` / `net_BP` / `net_ENT`). Exclude the same streams from `build_map_metric_registry`. Regenerate `catalog.json`, `manifest.json`, `map_metrics.json`, `maps.geojson`. Rationale: pruning shipped artifacts does not require model refit; runtime filters would hide keys that should never ship. Authoring labels stay in repo for the export pipeline.

6. **Choropleth opacity 0.92** — Locked value. Rationale: 0.78 + Positron washed fills; PNG path is opaque.

7. **Model display default `both`** — When hierarchical available; preserve prior selection across Y/X if still listed.

8. **Models Geography placement** — Move `#geo` from shared `.tab-row` into `#panel-models`. Rationale: Maps tab uses `#map-geography` (layer view: cities/counties/residual), not City-vs-ZIP; shared placement caused misleading ZIP option on Maps.

## Risks / Trade-offs

- [Ocean shp missing locally] → Clip no-ops; document required boundary cache file for shoreline fix.
- [Simplify 500 m after clip] → Thin water cutouts may collapse; verify coastal county visually; lower tolerance if needed.
- [Valid-pair menus hide theoretical cartesian] → Users only see exported edges (~86% city); matches data truth.
- [Pruned catalog drops cross-stream pairs] → Keys where MF outcome pairs with all-housing outcome (e.g. `TOTAL_MF_CO_total` × `TOTAL_CO_total`) are removed with the non-MF column; acceptable for MF-only explorer scope.

## Migration Plan

1. Ship `index.html` + `db_maps.py` + `map_metric_registry.py` + export finalize + tests.
2. Regenerate pruned release into `docs/data/releases/2018-2024/`.
3. Smoke http.server; no promote/CI required for local testing.
4. Rollback: restore prior `index.html` and `2018-2024.bak-*` release if needed.

## Open Questions

- None locked for implementation. Hover jurisdiction names depend on catalog point labels being present; if absent, hover shows metric only until a follow-up exports names.
