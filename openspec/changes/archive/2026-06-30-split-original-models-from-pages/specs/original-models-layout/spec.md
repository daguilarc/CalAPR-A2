## ADDED Requirements

### Requirement: Symmetric pipeline packages

The repository SHALL organize original and Pages pipelines as symmetric packages under `TableA2-models/original/` and `TableA2-models/pages/`, each implementing context → builder → export roles. Shared panel preparation and fit helpers SHALL remain in `TableA2-models/acs_apr_models.py` and `TableA2-models/panel_context.py`.

#### Scenario: Original package layout

- **WHEN** the change is implemented
- **THEN** `TableA2-models/original/` contains `pipeline_context.py`, `models_builder.py`, and `poisson_count_models.py`
- **THEN** `TableA2-models/pages/` contains `pipeline_context.py`, `catalog_builder.py`, `export.py`, and `pair_registry.py`

#### Scenario: Pages package layout

- **WHEN** the change is implemented
- **THEN** Pages modules previously at `TableA2-models/pages_*.py` and top-level `pair_registry.py` live under `TableA2-models/pages/`
- **THEN** top-level shim modules re-export from `pages.*` until explicitly removed

### Requirement: Symmetric CLI entry points in scripts/

Original and Pages pipelines SHALL expose CLIs under `scripts/`, not inside `TableA2-models/`.

#### Scenario: Original CLI

- **WHEN** a developer runs `python scripts/run_original_models.py` from the repo root with valid inputs
- **THEN** the command produces publication PNGs under `TableA2-models/Cities/` and `TableA2-models/ZIPCodes/`, count-model PNGs `TableA2-models/poisson_*_{CO,ENT}.png`, and `TableA2-models/r2_diagnostics.csv`
- **THEN** the command does not write or mutate `docs/data/releases/*/catalog.json`

#### Scenario: Pages CLI unchanged path

- **WHEN** a developer runs `python scripts/export_pages_catalog.py`
- **THEN** it imports from `pages.catalog_builder` (directly or via shim) and does not invoke `scripts/run_original_models.py` or `acs_apr_models.main()`

### Requirement: Shared panel context

Steps 1–11 panel preparation SHALL be implemented once in `panel_context.prepare_panel_context(run_poisson: bool)`. Both `original.pipeline_context` and `pages.pipeline_context` SHALL delegate to it.

#### Scenario: No duplicated Steps 1–11

- **WHEN** `acs_apr_models.main()` and `pages.pipeline_context.prepare_pages_context()` are compared
- **THEN** neither contains a full inline copy of Steps 1–11; both call `prepare_panel_context`

#### Scenario: Poisson flag divergence

- **WHEN** `prepare_original_context()` runs
- **THEN** it calls `prepare_panel_context(..., run_poisson=True)`
- **WHEN** `prepare_pages_context()` runs
- **THEN** it calls `prepare_panel_context(..., run_poisson=False)`

### Requirement: Backward-compatible acs_apr_models.main

`python TableA2-models/acs_apr_models.py` SHALL continue to run the full original publication pipeline by delegating to `original.models_builder.build_original_models`.

#### Scenario: Legacy main invocation

- **WHEN** a developer runs `python TableA2-models/acs_apr_models.py`
- **THEN** output matches `python scripts/run_original_models.py` for the same inputs

### Requirement: Shared library import boundary

`acs_apr_models.py` SHALL remain importable without importing `original.*` or `pages.*`. `original` and `pages` packages SHALL import from `acs_apr_models` and `panel_context`, not from each other.

#### Scenario: No cross-pipeline imports

- **WHEN** `pages.catalog_builder` is imported
- **THEN** it does not import `original.models_builder` or `original.poisson_count_models`
