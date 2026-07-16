## MODIFIED Requirements

### Requirement: Standalone from acs_apr_models.main

The pages catalog builder SHALL produce `catalog.json` and `manifest.json` without invoking `acs_apr_models.main()` or mutating original-script regression loops, PNG output, or `r2_diagnostics.csv`.

The pages panel preparation path (`pages.pipeline_context.prepare_pages_context`) SHALL NOT invoke Poisson/ZIP-ZINB count models or write Poisson PNG files during catalog builds.

Panel preparation SHALL be side-effect free with respect to original-model outputs: no Poisson PNG writes, no publication regression PNG loops, and no mutation of `r2_diagnostics.csv`.

#### Scenario: CI export path

- **WHEN** `scripts/export_pages_catalog.py` runs in GitHub Actions
- **THEN** it calls `pages.catalog_builder` only
- **THEN** it does not call `run_poisson_count_models` or write `poisson_*_*.png` files

#### Scenario: Pages context skips Poisson

- **WHEN** `prepare_pages_context()` runs as part of a catalog build
- **THEN** `prepare_panel_context` is called with `run_poisson=False`
- **THEN** no Poisson/ZINB PNGs are created in `TableA2-models/` during the build

#### Scenario: No original-model side effects during panel prep

- **WHEN** `prepare_pages_context()` completes
- **THEN** no new `poisson_*.png` files appear and `all_r2_results` passed into prep remains empty with no Poisson rows appended

#### Scenario: Original pipeline unchanged when Poisson enabled

- **WHEN** `scripts/run_original_models.py` or `acs_apr_models.main()` runs
- **THEN** Poisson/ZINB PNGs and diagnostics rows are produced as in the pre-split behavior

### Requirement: Pages modules under pages package

Pages catalog builder, pipeline context, export, and pair registry SHALL live under `TableA2-models/pages/` after migration. Top-level shim modules MAY re-export during transition.

#### Scenario: Canonical import path

- **WHEN** `pages.catalog_builder` is imported from `TableA2-models/` on `sys.path`
- **THEN** `build_pages_catalog` is available without importing `acs_apr_models.main`
