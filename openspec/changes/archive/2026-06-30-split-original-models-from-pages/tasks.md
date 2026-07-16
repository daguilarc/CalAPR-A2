## 1. Shared panel context + Poisson decoupling (fix data-flow first)

- [x] 1.1 Add `prepare_panel_context(base_path, run_poisson: bool)` in `TableA2-models/panel_context.py` — single Steps 1–11 implementation extracted from duplicated `main()` / `prepare_pages_context` blocks
- [x] 1.2 Add `run_poisson: bool = True` to `_prepare_apr_db_inc`; guard Poisson call
- [x] 1.3 Wire `run_poisson=False` through `pages/pipeline_context.py` (or shim `pages_pipeline_context.py` until move complete)

## 2. Poisson extraction

- [x] 2.1 Create `TableA2-models/original/` package (`__init__.py` if needed)
- [x] 2.2 Move Poisson/ZIP-ZINB functions into `original/poisson_count_models.py`; export `run_poisson_count_models`
- [x] 2.3 Remove Poisson block from `acs_apr_models.py`; global imports only

## 3. Original pipeline (B — module symmetry)

- [x] 3.1 Add `original/pipeline_context.py` → `prepare_original_context()` delegates to `prepare_panel_context(..., run_poisson=True)`
- [x] 3.2 Add `original/models_builder.py` → Steps 12–13, PCA, `r2_diagnostics.csv` (logic from `main()`)
- [x] 3.3 Add `scripts/run_original_models.py` CLI: `prepare_original_context()` → `build_original_models()`
- [x] 3.4 Slim `acs_apr_models.main()` to delegate to same builder (backward compat)
- [ ] 3.5 Smoke-test: `poisson_*_{CO,ENT}.png` count matches pre-refactor when all variants converge

## 4. Pages package move (C — folder symmetry)

- [x] 4.1 Create `TableA2-models/pages/` and move: `catalog_builder.py`, `pipeline_context.py`, `export.py`, `pair_registry.py`, `chart_prep.py`, `db_maps.py`, `map_metric_registry.py`
- [x] 4.2 Add top-level shims (`pages_pipeline_context.py`, `pages_catalog_builder.py`, `pages_export.py`, `pair_registry.py`) re-exporting from `pages.*`
- [x] 4.3 Update in-repo imports (`export_pages_catalog.py`, tests, `pages/catalog_builder.py` internal imports)
- [x] 4.4 Update `CODE_FILES` paths in `export_pages_catalog.py` and `verify_pages_catalog.py`
- [x] 4.5 Run `tests/test_interactive_map_explorer.py` and `TableA2-models/test_pair_registry.py`

## 5. ENT-only registry + Poisson BP documentation

- [x] 5.1 Filter `pages/pair_registry.py` `city_y_cols` / `zip_y_cols` to ENT only
- [x] 5.2 Update `test_pair_registry.py` for ENT-only pair counts; assert no CO/BP emitted
- [x] 5.3 Assert Poisson `phase_specs` is CO+ENT only in `poisson_count_models.py`
- [ ] 5.4 Trim stale CO/BP keys from `docs/chart_labels.json` or document as reserved

## 6. Full Cartesian build (prerequisite for Playwright)

- [x] 6.1 Document preflight in `docs/PAGES_SETUP.md`: Zillow 6-pack, NHGIS county cache (58 counties), repaired APR CSV, TIGER boundaries
- [ ] 6.2 Run full ENT-only build: `python scripts/export_pages_catalog.py --release-id 2018-2024 --staging-dir /tmp/apr-full/2018-2024` (no `--fixture`)
- [ ] 6.3 Verify: `python scripts/verify_pages_catalog.py /tmp/apr-full/2018-2024`; confirm `input_profile === release-2018-2024-v1` and pair count ≫ 4
- [ ] 6.4 Promote verified staging to `docs/data/releases/2018-2024/`
- [ ] 6.5 Notebook smoke: `notebooks/apr_explorer.ipynb` load-only against promoted release

## 7. Playwright e2e (after §6 — full release required)

- [x] 7.1 Add `e2e/playwright.config.ts` with `webServer` and global setup that rejects `manifest.input_profile === fixture-v1`
- [x] 7.2 Add `e2e/explorer.spec.ts`: full catalog load, Maps choropleth on real geojson, Models Plotly chart, ENT-only dropdowns, catalog scale assertion, console error guard
- [x] 7.3 Add `e2e/package.json`; document `npx playwright install chromium`
- [x] 7.4 Add `scripts/run_explorer_e2e.sh`: verify full manifest → `npx playwright test`
- [x] 7.5 Integrate Playwright into `.github/workflows/build-pages.yml` after verify, before `upload-pages-artifact`
- [x] 7.6 Keep `setup_local_site_test.sh` as fixture-only; document it does **not** satisfy Playwright prerequisites

## 8. Runbook + docs

- [x] 8.1 Update `docs/PAGES_SETUP.md` with ordered pipeline: full build → verify → promote → Playwright
- [x] 8.2 Update root `README.md` with entry points (original / full pages build / playwright / fixture smoke)

## 9. OMNI compliance verification

- [x] 9.1 `prepare_pages_context` path: `_prepare_apr_db_inc(run_poisson=False)`; no `poisson_*.png` during full or fixture catalog build
- [x] 9.2 `panel_context.py` is sole Steps 1–11 implementation
- [x] 9.3 `original/poisson_count_models.py` and `pages/*`: global imports only; no cross-pipeline imports
- [ ] 9.4 `npx playwright test` passes after §6 full build and promote

## Follow-up (after shim period)

- [ ] F.1 Remove top-level `pages_*.py` shims
- [ ] F.2 Refactor `_prepare_apr_db_inc` column writes to accumulate-then-apply
- [ ] F.3 Flatten 4-level nesting in Poisson owner branch
- [ ] F.4 Hoist local imports in `export_pages_catalog.py`
