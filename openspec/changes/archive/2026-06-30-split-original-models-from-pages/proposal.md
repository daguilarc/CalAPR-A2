## Why

`acs_apr_models.py` (~7,800 lines) mixes shared panel preparation, **original publication models** (two-part PNG loops, Poisson/ZIP-ZINB, PCA, `r2_diagnostics.csv`), and hooks consumed by the Pages explorer. Poisson runs inside `_prepare_apr_db_inc()` during Pages catalog builds even though it never enters `catalog.json` — an OMNI data-flow violation. Pages already has a symmetric pipeline shape (`pages_pipeline_context` → `pages_catalog_builder` → `pages_export` → `scripts/export_pages_catalog.py`); original analysis is still a monolithic `main()` with duplicated Steps 1–11. Browser testing is manual (`setup_local_site_test.sh` + open localhost); there is no Playwright coverage.

## What Changes

### Behavior (must have)

- **Extract Poisson/ZIP-ZINB** from `acs_apr_models.py` into `TableA2-models/original/poisson_count_models.py`.
- **Decouple Pages prep from Poisson**: shared `prepare_panel_context(run_poisson=...)`; Pages passes `run_poisson=False`.
- **ENT-only explorer registry**: `pair_registry` emits Entitlements outcomes only for `catalog.json`.
- **Poisson remains CO + ENT only** (no BP) — already true in code; document and assert.

### Pipeline symmetry (B — module roles)

Mirror the Pages three-layer pattern for original analysis:

| Layer | Original | Pages |
|-------|----------|-------|
| CLI | `scripts/run_original_models.py` | `scripts/export_pages_catalog.py` |
| Context | `original/pipeline_context.py` | `pages/pipeline_context.py` |
| Builder | `original/models_builder.py` | `pages/catalog_builder.py` |
| Export | inline in builder / `r2_diagnostics.csv` | `pages/export.py` |
| Shared | `acs_apr_models.py` + `panel_context.py` | same |

- **`panel_context.py`**: single Steps 1–11 implementation; both pipeline contexts delegate here.
- **`main()`** in `acs_apr_models.py` delegates to `original/models_builder` (backward compatible).
- **No duplicate runner** inside `TableA2-models/` — CLIs live in `scripts/` only.

### Folder symmetry (C — layout)

Move Pages modules into `TableA2-models/pages/` alongside `TableA2-models/original/`:

```
TableA2-models/
  acs_apr_models.py          # shared library
  panel_context.py           # shared Steps 1–11
  original/
    pipeline_context.py
    models_builder.py
    poisson_count_models.py
  pages/
    pipeline_context.py
    catalog_builder.py
    export.py
    pair_registry.py
    chart_prep.py
    db_maps.py
    map_metric_registry.py
```

Top-level **shim modules** (`pages_pipeline_context.py`, etc.) re-export from `pages.*` for one release cycle; update `CODE_FILES` digests and imports in-repo.

### Playwright e2e (after full Cartesian build)

Playwright runs against the **full ENT-only Cartesian release**, not the 4-pair fixture. Full data is required eventually; e2e validates the real explorer surface (dropdown cardinality, map metrics, catalog keys).

**Pipeline order (local and release CI):**

```
preflight → full export_pages_catalog → verify → promote to docs/data/releases/2018-2024 → playwright test → (publish)
```

- Add `e2e/` Playwright suite served from `docs/` after verified full release is in place.
- `playwright.config.ts` preflight: fail if `manifest.json` has `input_profile: fixture-v1`.
- Integrate Playwright into `.github/workflows/build-pages.yml` **after** full build + verify, **before** `upload-pages-artifact` / deploy.
- Keep `--fixture` for fast unit/contract tests only (`test_interactive_map_explorer.py`); fixture is **not** the Playwright prerequisite.
- Add `scripts/run_explorer_e2e.sh` (or extend runbook): verify full release present → `npx playwright test`.

## Capabilities

### New Capabilities

- `pipeline-symmetry`: Symmetric `original/` and `pages/` packages, shared `panel_context`, symmetric `scripts/` CLIs, import shims.
- `poisson-count-models`: Standalone Poisson/ZIP-ZINB module under `original/`, original pipeline only.
- `full-catalog-local-runbook`: Preflight, build, verify, serve, Playwright e2e, notebook load-only contract.
- `explorer-playwright-e2e`: Browser tests for `docs/index.html` against **verified full Cartesian** release (`input_profile: release-2018-2024-v1`).

### Modified Capabilities

- `pages-catalog-builder`: No Poisson during catalog builds; modules under `pages/`; imports via shims during migration.
- `pair-registry`: ENT-only Cartesian product; lives under `pages/pair_registry.py`.

## Impact

- **New**: `TableA2-models/panel_context.py`, `original/*`, `scripts/run_original_models.py`, `scripts/run_explorer_e2e.sh`, `e2e/*`, Playwright steps in `build-pages.yml`
- **Moved**: `pages_*.py`, `pair_registry.py`, `chart_prep.py`, `db_maps.py`, `map_metric_registry.py` → `pages/` with top-level shims
- **Modified**: `acs_apr_models.py`, `scripts/export_pages_catalog.py` (`CODE_FILES` paths), `tests/test_interactive_map_explorer.py`, `docs/PAGES_SETUP.md`, `.github/workflows/build-pages.yml`
- **Removed from scope**: separate PR workflow that builds fixture then runs Playwright
- **Outputs unchanged**: original → `TableA2-models/Cities/`, `poisson_*.png`, `r2_diagnostics.csv`; Pages → `docs/data/releases/`
- **Backward compat**: `python TableA2-models/acs_apr_models.py` still runs full original pipeline via delegation

## Entry points (after change)

```bash
# Original publication
python scripts/run_original_models.py
python TableA2-models/acs_apr_models.py   # delegates to same builder

# Pages catalog (full ENT-only Cartesian — hours)
python scripts/export_pages_catalog.py --release-id 2018-2024 --staging-dir /tmp/apr-full/2018-2024
python scripts/verify_pages_catalog.py /tmp/apr-full/2018-2024
cp -R /tmp/apr-full/2018-2024 docs/data/releases/2018-2024

# Explorer e2e (requires full release above)
cd e2e && npm ci && npx playwright install chromium && npx playwright test
# or: scripts/run_explorer_e2e.sh

# Quick fixture (unit tests / layout only — NOT for Playwright)
scripts/setup_local_site_test.sh
```
