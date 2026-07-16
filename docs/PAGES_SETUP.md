# APR Explorer immutable release setup

The public explorer is a static consumer of the verified `2018-2024` archive. Pushing code and elapsed time do not rebuild models.

## Repository configuration

Enable GitHub Pages with **GitHub Actions** as its source. Under **Settings → Secrets and variables → Actions**, set:

- variable `RELEASE_OWNER` to the one GitHub login authorized to publish;
- secret `ZILLOW_INPUTS_URL` to an expiring or access-controlled HTTPS URL for the owner-maintained `zillow-inputs.tar.gz`;
- secret `ZILLOW_INPUTS_SHA256` to the lowercase SHA-256 digest of that exact archive;
- secret `HCD_INPUT_SHA256` to the lowercase SHA-256 digest of the exact downloaded `tablea2.csv` source;
- secret `IPUMS_API_KEY` when NHGIS caches must be refreshed; and
- secret `FRED_API_KEY` when CPI inputs must be refreshed.

The Zillow archive must contain these six files at its root (no containing directory):

- `City_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv`
- `City_zhvi_uc_condo_tier_0.33_0.67_sm_sa_month.csv`
- `City_zori_uc_sfrcondomfr_sm_sa_month.csv`
- `Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv`
- `Zip_zhvi_uc_condo_tier_0.33_0.67_sm_sa_month.csv`
- `Zip_zori_uc_sfrcondomfr_sm_sa_month.csv`

Create and hash it with `tar -czf zillow-inputs.tar.gz <six files>` and `sha256sum zillow-inputs.tar.gz`. The workflow refuses a missing secret, a non-HTTPS URL, a digest mismatch, a missing filename, or an input without both January 2018 and December 2024 columns. The URL itself stays encrypted as a GitHub Actions secret.

Download the configured HCD `TABLEA2_URL` once for review, calculate `sha256sum tablea2.csv`, and store that exact digest as `HCD_INPUT_SHA256`. The workflow verifies the raw download before running the repair script; the release manifest then records separate raw and repaired HCD digests.

The release uses HCD APR 2018–2024, 2020–2024 ACS 5-Year Estimates with 2014–2018 comparison values, and the January 2018–December 2024 cuts of the City/ZIP ZHVI and ZORI `*_sm_sa_month.csv` files. Monetary values use real 2024 dollars.

The workflow uses CPython 3.11.14 and installs the complete dependency closure from `requirements-pages-release.lock` with dependency resolution disabled and SHA-256 hash checking required, then runs `pip check`. Updating any direct or transitive dependency requires an intentional lockfile regeneration and a new release-pipeline review; `requirements-pages-release.txt` is only the human-maintained direct dependency input.

## Owner-only manual publication

Only the configured owner may run **Actions → Publish immutable APR Explorer release → Run workflow** with release id `2018-2024`. The job rejects other actors before data preparation. A full stationary-bootstrap and hierarchical build can take several hours.

The job builds in a new staging directory, verifies it, promotes the unpacked release under `docs/data/releases/2018-2024/`, and deploys the `docs/` tree to GitHub Pages.

The manifest records the fixed random seed, exact CPython runtime, exact transitive lockfile digest, checked-out code revision, the exact release-critical code digest, exact raw and repaired HCD plus Zillow/ACS/CPI/reference/geometry input inventory and digests, and per-artifact digests. The verifier rejects omitted or extra code, dependency, and input entries.

An existing deployed release directory is not overwritten by an ordinary run. A failed preparation, fit, map export, or verification leaves the deployed release unchanged.

## Local verification and dry runs

Exercise the complete release contract without source preparation, fitting, or publication:

```bash
python3 scripts/export_pages_catalog.py --fixture --staging-dir /tmp/apr-release/2018-2024
python3 scripts/verify_pages_catalog.py /tmp/apr-release/2018-2024
python3 -m http.server 8080 --directory docs
```

For a real, non-publishing staged build, first prepare `tablea2_cleaned_parsefilter_repair.csv` and required caches, then run:

```bash
python3 scripts/export_pages_catalog.py --release-id 2018-2024 --staging-dir /tmp/apr-full/2018-2024
python3 scripts/verify_pages_catalog.py /tmp/apr-full/2018-2024
```

If the Zillow files are outside `TableA2-models/`, set `ZILLOW_INPUT_DIR=/absolute/path/to/extracted/archive` for the local command.

The legacy standalone five-PNG map command is fully offline. It additionally requires
`TableA2-models/nhgis_cache_2018_county_b19013_b01003.json`, containing a top-level
`data` object with 58-element arrays named `COUNTYA`, `county_population_2018`, and
`county_income_2018`. `scripts/bootstrap_pages_data.py` copies this file from
`docs/data/census/` when present. It does not substitute a live Census API request.

Catalog keys use `geography:y_col:x_col:robustness`. Model display and zero-value choices select nested archived summaries and never refit.

## Build to Playwright pipeline

For the release gate and CI checks, run the pipeline in this order:

1. build and stage release artifacts with `scripts/export_pages_catalog.py`;
2. verify staged artifacts with `scripts/verify_pages_catalog.py`;
3. run browser e2e with `scripts/run_explorer_e2e.sh` (fails fast when `manifest.input_profile` is `fixture-v1`);
4. only then upload the Pages artifact.

Local fixture setup from `scripts/setup_local_site_test.sh` is intentionally excluded from Playwright e2e.

## Future 2025 data

Do not replace the 2018–2024 directory. A 2025 publication requires an explicit new release id, source-vintage configuration, verifier expectations, workflow path, and authored website provenance update.
