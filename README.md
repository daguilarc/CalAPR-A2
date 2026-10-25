# CSVparse_hcd_apr

California HCD [Annual Progress Report (APR)](https://data.ca.gov/dataset/housing-element-annual-progress-report-apr-data-by-jurisdiction-and-year) Table A2 parsing, repair, and charts.

## Archived maps page

The maps-only GitHub Pages site lives in `docs/`. It restores the archived
2018–2024 map release from the repository history: eight multifamily housing
metrics across incorporated cities, whole counties, and cities plus
unincorporated county areas. The page reads committed GeoJSON and metric
metadata; it does not run a notebook, generate regressions, or rebuild data.

To preview locally, run `python -m http.server 8765 --directory docs` and open
`http://localhost:8765/`. After GitHub Pages is set to **GitHub Actions** as
the source, pushes to `main` that change `docs/` deploy the site through
`.github/workflows/maps-pages.yml`.

## Pipeline

Two steps: clean the raw HCD export, then chart the cleaned data.

| Step | Command |
|------|---------|
| **Data cleaning** | `python data-cleanup/tablea2_parsefilter_repair.py` |
| **Charts from cleaned data** | `python charts/basic_apr_charts.py` |

The chart script runs the cleaning step automatically if the cleaned CSV isn't already present, so `python charts/basic_apr_charts.py` alone is enough on a fresh checkout.

## Data cleaning

`data-cleanup/tablea2_parsefilter_repair.py` parses and repairs the raw APR CSV export (`tablea2.csv`, at the repo root) and reconciles truncated/malformed rows against the source `*.xlsm` workbooks that live beside it in `data-cleanup/` (`Bell2019.xlsm`, `Bell2023.xlsm`, `Campbell2024.xlsm`, `Ceres2020.xlsm`, `Colfax2021.xlsm`, `Hesperia2022.xlsm`, `Hesperia2023.xlsm`, `Hesperia2024.xlsm`, `Irvine2022.xlsm`). It performs structural quote repair, date/year validation, deduplication, and XLSM-backed recovery of truncated rows.

Outputs, all written to the repo root:

- `tablea2_cleaned_parsefilter_repair.csv` — the cleaned dataset the charts read.
- `matched_truncated_repair.csv`, `unmatched_truncated_repair.csv`, `ambiguous_truncated_repair.csv` — truncated-row recovery diagnostics.
- `date_year_mismatch_rows_parsefilter_repair.csv` — rows dropped for date/year validation.

The module docstring documents the full pipeline order, the stable identity key, XLSM lookup order, and the upsert/ambiguity rules. `flowchart1_main_pipeline.png`, `flowchart2_workbook_upsert.png`, and `flowchart3_date_year_mismatch.png` diagram the same flow.

## Charts

`charts/basic_apr_charts.py` generates the matplotlib PNGs from the cleaned APR data, written into `charts/`. Color scheme is colorblind-friendly (blue, orange, purple, gray).

## Layout

- **`data-cleanup/`** — `tablea2_parsefilter_repair.py`, the data-cleaning entry point, plus the nine `*.xlsm` source workbooks it reads.
- **`charts/`** — `basic_apr_charts.py` and its PNG output (PNGs are git-ignored).
- **`tablea2.csv`** — raw HCD APR export (git-ignored input); place it at the repo root.

## Dependencies

`requirements.txt` lists the four external packages the pipeline needs: **pandas**, **numpy**, **openpyxl** (workbook parsing), and **matplotlib** (charts). Everything else it uses is in the Python standard library.

```bash
pip install -r requirements.txt
```
