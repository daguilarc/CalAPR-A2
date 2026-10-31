# CalAPR-A2

California HCD [Annual Progress Report (APR)](https://data.ca.gov/dataset/housing-element-annual-progress-report-apr-data-by-jurisdiction-and-year) Table A2 parsing, repair, and charts.

Project pages: [Housing map](https://daguilarc.github.io/CalAPR-A2/) · [Data-cleaning methods](https://daguilarc.github.io/CalAPR-A2/cleaning.html).

The data-cleaning guide walks through the Python script with flowcharts, explains repairs using original APR submissions provided by HCD, date and reporting-year rules, and deduplication, and compares excluded rows with the cleaned data. It includes a before/after chart and recommendations for improving APR data quality.

## Housing maps

The static GitHub Pages site in `docs/` provides independent Geography,
Housing type, Development stage, Tenure, Inclusionary Program, and Affordability selectors.
It reads committed geometry, a compact sparse numerator cube, and generated
selector metadata. The browser combines atomic counts and divides by the fixed
population to show units per 1,000 residents, with units/population in hover.
Cities use blue, whole counties orange, and cities plus unincorporated areas purple.
County outlines, including the state perimeter, stay visible in all views.

Rebuild from an existing local **cleaned Table A2 CSV**, from the repository root:

```bash
python3 -m maps.build_maps --input /path/to/tablea2_cleaned_parsefilter_repair.csv
```

The explicit CSV is the authority for housing counts; the map builder reuses the
chart loader, tenure/program flags, income column names, and shared labels.
It does not run another repair pass for a nondefault input. Importing the chart
module does not read or repair data. The source CSV is not committed or fetched
by the page. Generated artifacts are `maps.geojson`, `map_data.json`, and
`provenance.json` under `docs/data/releases/2018-2024/`.

Geometry, feature IDs, and population remain the historical reference in
`maps/reference/jurisdictions.geojson` (source revision `62fea25`, population:
2020–2024 ACS 5-Year Estimates). Rebuilding counts does not refresh those
boundaries or denominators. Provenance separates the input basename, SHA-256,
actual build timestamp, row/year coverage, and policies from reference provenance.

Selection definitions:

- Housing types use the chart dictionary: Single Family Detached, Single Family
  Attached, Mobile Home, Accessory dwelling units, Two to four units, and Five or
  more units. All housing also includes unknown/malformed source types.
- All-unit Entitlements, Building permits, and Certificates of occupancy are
  **net of demolitions**, using the chart's existing stage assignment and signed
  `ent_net`, `bp_net`, `co_net` values. Negative corrections are retained. Stage
  choices/title use Entitlements, Building Permits, and Certificates of Occupancy,
  appending exactly “, Net of Demolitions” only for All units. Selecting an
  affordability tier uses the base stage names with nothing appended. Stage and
  tenure selections are preserved. Tenure/program/geography changes do not
  control the suffix.
- Owner (for sale) and Renter use the chart flags; Both is their union, excluding
  unclassified tenure. Provenance reports the excluded rows and units.
- All projects includes ordinary/missing program values. Density bonus includes
  rows reporting DB; Non-bonus inclusionary includes INC without DB.
- Affordability choices include separate Low and Very Low selections and the
  combined **Low + Very Low** option. Income tiers use reported deed-restricted
  columns; ELI and non-deed-restricted units are excluded. Deed-restricted units
  sums Low, Very Low and Moderate. Demolition allocation is unavailable for
  income tiers. Housing defaults to Five or more units. All choices apply
  independently of housing type/program.
- Whole county includes all reporting jurisdictions in that county. Each
  unincorporated residual is whole county minus mapped cities for every atomic
  count. Rates with absent/nonpositive population are null.

The exporter uses the existing Python dependencies.

To preview locally, run `python3 -m http.server 8765 --directory docs` and open
`http://localhost:8765/`. The existing `.github/workflows/maps-pages.yml` deploys
static `docs/` on qualifying pushes to `main` after GitHub Pages is configured
with **GitHub Actions** as its source. A local rebuild does not publish the site.

## Pipeline

Two steps: clean the raw HCD export, then chart the cleaned data.

| Step | Command |
|------|---------|
| **Data cleaning** | `python data-cleanup/tablea2_parsefilter_repair.py` |
| **Charts from cleaned data** | `python charts/basic_apr_charts.py` |

Place the raw HCD export, `tablea2.csv`, at the repository root before running the cleaning pipeline; a fresh checkout does not include this input. The chart script runs cleaning automatically when its default cleaned CSV is missing. An explicit existing cleaned CSV input is read without another repair pass.

## Data cleaning

`data-cleanup/tablea2_parsefilter_repair.py` parses and repairs the raw APR CSV export (`tablea2.csv`, at the repo root) and reconciles truncated/malformed rows against the source `*.xlsm` workbooks that live beside it in `data-cleanup/` (`Bell2019.xlsm`, `Bell2023.xlsm`, `Campbell2024.xlsm`, `Ceres2020.xlsm`, `Colfax2021.xlsm`, `Hesperia2022.xlsm`, `Hesperia2023.xlsm`, `Hesperia2024.xlsm`, `Irvine2022.xlsm`). It performs structural quote repair, date/year validation, deduplication, and XLSM-backed recovery of truncated rows. Before appending a workbook record with no exact CSV match, it screens for possible duplicates against original and updated CSV rows and other proposed additions. Possible duplicates and records with insufficient identifiers are held for review in `ambiguous_truncated_repair.csv`; the screen does not automatically update another record or merge records.

Outputs, all written to the repo root:

- `tablea2_cleaned_parsefilter_repair.csv` — the cleaned dataset the charts read.
- `matched_truncated_repair.csv`, `unmatched_truncated_repair.csv`, `ambiguous_truncated_repair.csv` — truncated-row recovery diagnostics.
- `date_year_mismatch_rows_parsefilter_repair.csv` — rows dropped for date/year validation.
- `date_excluded_phase_comparison_parsefilter_repair.csv` — phase comparisons with retained rows; this diagnostic does not restore excluded rows.

The module docstring documents the full pipeline order, the stable identity key, XLSM lookup order, and the upsert/ambiguity rules. [The cleaning explanation and flowcharts](docs/cleaning.html) describe the same flow.

## Tests

Run the focused workbook-append safeguard tests from the repository root:

```bash
python3 -m unittest discover -s tests -p test_append_safeguard.py
```

## Charts

`charts/basic_apr_charts.py` generates the matplotlib PNGs from the cleaned APR data, written into `charts/`. Color scheme is colorblind-friendly (blue, orange, purple, gray).

## Layout

- **`data-cleanup/`** — `tablea2_parsefilter_repair.py`, the data-cleaning entry point, plus the nine `*.xlsm` source workbooks it reads.
- **`charts/`** — `basic_apr_charts.py` and its PNG output (PNGs are git-ignored).
- **`maps/`** — `build_maps.py`, the map exporter, and `reference/jurisdictions.geojson`, the historical geometry and population reference.
- **`docs/`** — `index.html` (housing map), `cleaning.html` (methods guide), guide images in `assets/`, and generated map data in `data/releases/2018-2024/`.
- **`tests/`** — `test_append_safeguard.py`, the focused workbook-append safeguard tests.
- **`tablea2.csv`** — raw HCD APR export (git-ignored input); place it at the repo root.

## Dependencies

`requirements.txt` lists the four external packages the pipeline needs: **pandas**, **numpy**, **openpyxl** (workbook parsing), and **matplotlib** (charts). Everything else it uses is in the Python standard library.

```bash
pip install -r requirements.txt
```
