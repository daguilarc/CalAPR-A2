## ADDED Requirements

### Requirement: Standalone Poisson/ZIP-ZINB module

Poisson and zero-inflated count models SHALL live in `TableA2-models/original/poisson_count_models.py` and SHALL NOT remain inline only inside `acs_apr_models.py`.

#### Scenario: Module exports run function

- **WHEN** `poisson_count_models.py` is imported
- **THEN** it exposes `run_poisson_count_models(...)` accepting prepared `df_apr_db_inc`, owner Rule-A columns context, `output_dir`, and an `all_r2_results` accumulator list

#### Scenario: Four variant families

- **WHEN** `run_poisson_count_models` executes with complete inputs
- **THEN** it attempts fits for DB, INC, DB_owner, and INC_owner variants across CO and ENT phases where data permits (minimum n ≥ 20 valid rows per fit)
- **THEN** it writes PNG files named `poisson_{db,inc}_units_vs_total_{CO,ENT}.png` and owner variants under the caller-supplied `output_dir` (`TableA2-models/` via `base_output_dir`)

### Requirement: Original pipeline only

`run_poisson_count_models` SHALL be invoked from the original pipeline (`run_poisson=True` path) only. The Pages pipeline SHALL NOT import or call it during catalog builds.

#### Scenario: Pages build skips Poisson module

- **WHEN** `scripts/export_pages_catalog.py --fixture` runs
- **THEN** `original.poisson_count_models` is not imported and no `poisson_*.png` files are created

### Requirement: ZIP-first then ZINB fallback

Each count-model fit SHALL attempt Zero-Inflated Poisson first and Zero-Inflated Negative Binomial second when ZIP fails or does not converge.

#### Scenario: Model selection

- **WHEN** ZIP fit converges
- **THEN** the saved chart and diagnostics row use the ZIP tag
- **WHEN** ZIP fails and ZINB converges
- **THEN** the saved chart and diagnostics row use the ZINB tag

### Requirement: Diagnostics append to r2 list

Each successful Poisson/ZINB fit SHALL append one row to the caller-supplied `all_r2_results` list using the existing `R2_DIAG_COLUMNS` schema.

#### Scenario: Original builder collects diagnostics

- **WHEN** `original.models_builder.build_original_models` completes
- **THEN** `r2_diagnostics.csv` contains ZIP/ZINB rows matching the pre-extraction format

### Requirement: Building Permit (BP) phase excluded from Poisson

Poisson/ZIP-ZINB count models SHALL NOT fit, plot, or emit diagnostics for BP. Allowed phases are CO and ENT only.

#### Scenario: No BP phase specs

- **WHEN** `run_poisson_count_models` defines its phase loop
- **THEN** the phase list contains only `CO` and `ENT` tags
- **THEN** no output files match `poisson_*_BP.png`
