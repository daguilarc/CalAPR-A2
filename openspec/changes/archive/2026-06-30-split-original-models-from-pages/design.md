## Context

Two pipelines share `acs_apr_models.py` today. Pages already split in June 2026 (`pages-full-cartesian-catalog`); original did not.

```
TODAY
─────
acs_apr_models.main()  ──────────► publication PNGs, poisson_*.png, r2_diagnostics.csv
        ▲
        │ duplicated Steps 1–11
        │
prepare_pages_context() ──► build_pages_catalog() ──► docs/data/releases/

TARGET (B + C)
──────────────
                    acs_apr_models.py  (shared fit helpers, constants)
                    panel_context.py   (shared Steps 1–11, run_poisson flag)
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
     original/pipeline_context      pages/pipeline_context
     run_poisson=True                 run_poisson=False
              │                               │
              ▼                               ▼
     original/models_builder        pages/catalog_builder
              │                               │
              ▼                               ▼
     Cities/, poisson_*.png,         pages/export.py
     r2_diagnostics.csv                      │
                                            ▼
                                   docs/data/releases/

scripts/run_original_models.py      scripts/export_pages_catalog.py
```

Poisson charts write to `TableA2-models/poisson_*_{CO,ENT}.png` (`base_output_dir`), not a `Poisson/` subdirectory.

## Goals / Non-Goals

**Goals:**

- Symmetric pipeline modules (`original/` ↔ `pages/`) and symmetric CLIs (`scripts/run_original_models.py` ↔ `scripts/export_pages_catalog.py`).
- Shared `prepare_panel_context()` — eliminate Steps 1–11 duplication between `main()` and Pages prep.
- Poisson extraction; Pages path never runs count models.
- ENT-only explorer registry.
- Playwright e2e against **full Cartesian** release after verify (local + `build-pages.yml`).
- Documented full local build pipeline ending in Playwright.

**Non-Goals:**

- Poisson/ZINB in explorer UI or `catalog.json`.
- Moving `acs_apr_models.py` body into `original/` (stays shared library at package root).
- Relocating publication PNG outputs under `original/outputs/` (outputs stay at `TableA2-models/` root).
- Playwright against fixture-only release (`input_profile: fixture-v1`).
- Changing R² publication floors in original two-part CO loops.

## Decisions

### 1. B + C coexist: module symmetry inside folder symmetry

**Choice:** `TableA2-models/original/` and `TableA2-models/pages/` each implement context → builder → export. Shared code at `TableA2-models/acs_apr_models.py` + `panel_context.py`.

**Shim strategy:** Keep `pages_pipeline_context.py`, `pages_catalog_builder.py`, `pages_export.py`, `pair_registry.py` at top level as one-line re-exports until shims removed in follow-up:

```python
# TableA2-models/pages_pipeline_context.py (shim)
from pages.pipeline_context import *  # noqa: F403
```

Update `CODE_FILES` in `export_pages_catalog.py` to hash canonical `pages/*` paths after shim period ends (or hash both during transition — document in tasks).

### 2. Shared panel context

**Choice:** New `panel_context.py` with `prepare_panel_context(base_path, run_poisson: bool) -> dict`.

```python
# original/pipeline_context.py
def prepare_original_context(base_path=None):
    return prepare_panel_context(base_path, run_poisson=True)

# pages/pipeline_context.py
def prepare_pages_context(base_path=None):
    ctx = prepare_panel_context(base_path, run_poisson=False)
    # ZIP panel build (panels_only) stays Pages-specific
    ...
    return ctx
```

### 3. Original builder + CLI

**Choice:** `original/models_builder.py` owns Steps 12–13, PCA, `r2_diagnostics.csv` write — logic moved from `main()`. `scripts/run_original_models.py`:

```python
from original.pipeline_context import prepare_original_context
from original.models_builder import build_original_models

def main():
    ctx = prepare_original_context()
    build_original_models(ctx)
```

`acs_apr_models.main()` calls the same `build_original_models(prepare_original_context())`.

### 4. Poisson extraction

Move `_poisson_result_pseudo_r2` through `run_poisson_db_vs_total_units` (+ `_attach_poisson_owner_x_rule_a`) to `original/poisson_count_models.py`. Export `run_poisson_count_models(...)`. `_prepare_apr_db_inc(run_poisson=True)` calls it; `run_poisson=False` skips.

### 5. ENT-only pair registry

Filter `city_y_cols` / `zip_y_cols` to `ENT` phase only in `pages/pair_registry.py`.

### 6. Playwright e2e after full Cartesian build

**Choice:** Playwright is the last gate before publish. It runs only against a verified **full** release at `docs/data/releases/2018-2024/` with `manifest.input_profile === release-2018-2024-v1` and catalog pair count ≫ 4.

```
LOCAL / RELEASE CI
──────────────────
1. preflight (Zillow, NHGIS, APR, TIGER)
2. python scripts/export_pages_catalog.py --staging-dir /tmp/apr-full/2018-2024   # no --fixture
3. python scripts/verify_pages_catalog.py /tmp/apr-full/2018-2024
4. promote → docs/data/releases/2018-2024/
5. cd e2e && npx playwright test
6. (CI only) upload-pages-artifact + deploy
```

| Test | Assertion |
|------|-----------|
| Release profile | `manifest.input_profile` is `release-2018-2024-v1`, not `fixture-v1` |
| Catalog scale | `Object.keys(catalog).length` ≫ 4 (ENT-only full Cartesian) |
| Page load | `#status` leaves "Loading…"; no network failure on catalog/manifest |
| Maps tab | `#map-chart` visible; Plotly choropleth on real California geojson |
| Models tab | `#tab-models` → `#model-chart` renders; `#x-col` / `#y-col` populated with many ENT outcomes |
| ENT-only | No `#y-col option` ending `_CO_total` or `_BP_total` |
| Console | fail on `console` `error` |

**Fixture (`--fixture`)** stays for `test_interactive_map_explorer.py` and quick layout checks via `setup_local_site_test.sh`. Fixture does **not** satisfy Playwright prerequisites.

**CI integration:** Add Node + Playwright steps to `build-pages.yml` after the existing verify step (job already has `timeout-minutes: 360` and runs full `export_pages_catalog.py --publish`). No separate PR workflow with fixture + Playwright.

**Local helper:** `scripts/run_explorer_e2e.sh` reads `docs/data/releases/2018-2024/manifest.json`, rejects `fixture-v1`, then runs `npx playwright test`.

### 7. Entry points

| Command | Pipeline |
|---------|----------|
| `python scripts/run_original_models.py` | Original |
| `python TableA2-models/acs_apr_models.py` | Original (delegate) |
| `python scripts/export_pages_catalog.py ...` (no `--fixture`) | Full Pages Cartesian |
| `scripts/run_explorer_e2e.sh` | Playwright (requires step above) |
| `scripts/setup_local_site_test.sh` | Fixture only (not Playwright) |

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| Import breakage from `pages/` move | Top-level shims; update `sys.path` tests; grep imports before removing shims |
| `CODE_FILES` digest drift | Update paths in `export_pages_catalog.py` and `verify_pages_catalog.py` |
| `run_original_models` vs `main()` drift | Single `build_original_models()` implementation; `main()` delegates only |
| Playwright flake on Plotly | Wait for `#map-chart .main-svg`; full catalog has more pairs to exercise dropdown changes |
| Full build runtime (hours) | Same cost as publish workflow today; Playwright adds minutes after build completes |
| Local dev without full rebuild | Reuse promoted `docs/data/releases/2018-2024/` if `input_profile` is already full; `run_explorer_e2e.sh` checks manifest |

## Migration Plan

1. Add `panel_context.py` + `run_poisson` flag; wire Pages `run_poisson=False` (fixes data-flow violation first).
2. Extract `original/poisson_count_models.py`.
3. Add `original/pipeline_context.py`, `original/models_builder.py`, `scripts/run_original_models.py`; slim `main()` to delegate.
4. Move Pages modules to `pages/`; add shims; update imports and `CODE_FILES`.
5. ENT-only `pair_registry`; update unit tests.
6. Document full build → verify → promote → Playwright runbook.
7. Add Playwright e2e + integrate into `build-pages.yml` after verify.

## OMNI compliance

| Rule | Fix in this change |
|------|-------------------|
| Data flow | `run_poisson=False` on Pages path |
| Repetition | `panel_context.py` dedupes Steps 1–11 |
| Repetition | Poisson extraction; ENT-only registry |
| Imports global | All new modules; hoist `export_pages_catalog` locals in same PR or follow-up task |
| Nesting | Flatten 4-deep Poisson owner branch during extraction |

**Deferred:** `_prepare_apr_db_inc` one-by-one column `assign` batching; `iter_pairs` city/ZIP block dedup; remove shims after one release.
