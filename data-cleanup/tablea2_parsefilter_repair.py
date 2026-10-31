#!/usr/bin/env python3
"""Repair variant of TableA2 PARSEFILTER with XLSM-backed truncated-row recovery.

Purpose
- Structural CSV repair, pandas load, in-memory fixes, date/year validation, APR dedup.
- For deduped truncated-closer identities, look up the authoritative row in source
  `Table A2` workbooks (openpyxl) and upsert mapped APR fields into the working
  DataFrame. See "Upsert behavior" below for the complete set of outcomes — update and
  append are the common two, but not the only ones that write.

Two grains (do not conflate)
- Truncated physical lines: rows from `_extract_truncated_closer_rows` (one per broken
  CSV line that still parses short after closer repair). Count ~ `truncated_closer_rows`.
- Truncated identities: dedupe of those lines on the stable key below. Count ~
  `truncated_identities_detected`. Upsert ambiguity and resolution apply only here.

Inputs
- APR export: `tablea2.csv` at the repo root (one level above this script). Cleaned output
  and all diagnostic CSVs are written there too, where downstream consumers read them.
- Workbooks: `{Juris}{YEAR}.xlsm` beside this script in `data-cleanup/`, e.g. Campbell + 2024 ->
  `Campbell2024.xlsm`. Non-alphanumeric characters are stripped from `JURIS_NAME` for the
  stem. Lock files `~$*.xlsm` are ignored by convention (they are not used). Whichever
  workbooks are present in that directory are the ones available for lookup; a run uses only
  those an identity actually resolves to, and a missing workbook is an unresolved upsert.
- Sheet: only `Table A2`. Header row is the first row (within ~80 rows) whose cell set
  contains both `A2_1_ID` and `A2_18_Affordable`.

Stable identity key (dedupe and APR update match)
- Defined once as `IDENTITY_KEY_COLS`; compared after `_norm_str` (strip + upper, with
  missing/`nan`/`none` normalizing to empty).
- `JURS_TRACKING_ID` empty is allowed; `APN == "N/A"` is weak—lookup prefers tracking id
  when present and not `N/A`.
- Note an intentional asymmetry: `_classify_truncated_rows` (step 7) does NOT use `_norm_str`.
  It normalizes with `astype(str).strip().upper()`, so a missing value keys as "NAN" rather
  than "". That stage only matches diagnostics to clean rows; changing it would silently
  change which truncated lines are reported as matched.

XLSM row lookup order (first hit wins; for multiple hits in a bucket see "Upsert behavior")
1) `A2_1_ID` matches normalized `JURS_TRACKING_ID` when tracking id is non-empty and not `N/A`.
2) Else (`A2_1_Current`, `A2_1_Address`) matches normalized (`APN`, `STREET_ADDRESS`).
3) Else `A2_1_Current` matches normalized `APN`.

Row-number semantics for diagnostics
- XLSM candidate provenance uses worksheet 1-based row numbers (UI-visible Excel row numbers).
- Ambiguous and integrity diagnostics export stage + candidate row numbers to avoid DataFrame-index confusion.

Upsert behavior (every write path is listed; each identity takes exactly one outcome)
- Workbook missing, or zero XLSM matches: unresolved, no write
  -> `truncated_identities_unresolved`.
- Tracking-id stage returned a candidate whose `A2_1_ID` is not the expected tracking id
  (guardrail; unexpected): integrity diagnostic, no write
  -> `truncated_xlsm_match_integrity_errors`, row in `ambiguous_truncated_repair.csv` with
  `ambiguity_stage=xlsm_match_integrity_error`.
- Multiple XLSM rows match: normalized mapped payloads are compared first.
  * All payloads equal -> collapse to the candidate with the smallest Excel row number (tie:
    workbook order) and continue as the single-candidate case below. The collapse is recorded
    by the orthogonal flag `truncated_xlsm_equivalent_duplicates_collapsed`, which is NOT an
    outcome bucket: it co-occurs with whatever outcome the identity then reaches.
  * Payloads differ -> phase-count pairing is attempted (see next bullet). Only if pairing
    fails is the identity ambiguous, no write, `ambiguity_stage=xlsm_multi_match`.
- Phase-count pairing (`_pair_xlsm_to_df_by_phase`) resolves the many-to-many cases that would
  otherwise be ambiguous. It requires an equal number of XLSM candidates and matching APR rows,
  then: pass 1 matches candidates to APR rows whose phase counts (`PHASE_APR_COLS`) agree
  exactly; pass 2 assigns the remaining candidates to "skeleton" APR rows whose phase counts are
  all zero (typically rows whose counts were lost to truncation). If every candidate pairs
  uniquely, each is written to its paired row -> the identity counts ONCE in
  `truncated_identities_resolved_paired`, and the number of rows it wrote is reported separately
  as `truncated_rows_updated_via_pairing`. If pairing fails, the identity is ambiguous with
  `ambiguity_stage=xlsm_multi_match` (multi-candidate route) or `df_multi_match` (single
  candidate, several APR rows).
- Single resolved candidate, exactly one matching APR row: in-place update of mapped columns
  only (see `map_a2_row_to_apr_record`) -> `truncated_identities_resolved_update`.
- Single resolved candidate, zero matching APR rows: propose one synthetic APR row.
  Before concat, screen source and mapped identifiers against original/current APR rows and
  the complete pending batch. Compatible jurisdiction/year links withhold both pending
  endpoints for review; county differences never exclude a link. Incomplete mapped scope
  or missing usable mapped identifiers also withhold the proposal. Withheld proposals use
  `append_candidate_review` and count as ambiguous, not append. Accepted rows use
  dtype-consistent defaults (`NaN` for numeric, `""` for object) for unmapped columns
  -> `truncated_identities_resolved_append`. This is an identifier guard, not global dedup.
- Accounting invariant, enforced in `main` (raises on violation): detected ==
  update + append + paired + ambiguous + unresolved + integrity_errors.

Performance notes (these shape the code; do not "simplify" them back)
- Appends are accumulated and applied in ONE concat after the identity loop. Per-row concat
  copied the whole ~785k-row frame once per appended row.
- The identity -> APR row lookup is a dict built once before the loop (`_build_identity_index`),
  not a full-frame scan per identity. It is deliberately NOT updated as rows are appended,
  which is consistent with appends being deferred to after the loop.

Post-upsert text cleanup
- Lone U+0022 in `NO_FA_DR`, `NOTES`, `FIN_ASSIST_NAME` is cleared to empty (counted in
  stdout as `affordability_lone_quote_cells_fixed`). Boilerplate trailing-quote strip and
  column-shift repair are unchanged from baseline helpers.

Truncated diagnostics (separate from upsert ambiguity)
- After filters and dedup, `_classify_truncated_rows` matches each truncated physical line
  to a kept-clean APR project identity (strict / relaxed keys). Unmatched lines go to
  `unmatched_truncated_repair.csv`. This is not the same set as upsert-ambiguous identities.

Pipeline order
1) structural quote repair + line-range parse diagnostics (raw vs fixed text). The set of
   closer-repaired line numbers is returned by `_repair_quote_corruption` itself and must not
   be reconstructed by re-scanning the raw text: a rescan splits without line terminators and
   so silently misses lines whose triple-quote is closed by the newline rather than a comma.
2) `pd.read_csv(fixed_csv, on_bad_lines="skip")` -> working `df`
3) `_strip_affordability_trailing_quotes`, `_repair_column_shift_rows`
4) `_extract_truncated_closer_rows` -> truncated physical lines
5) dedupe identities -> XLSM lookup -> upsert (appends batched) -> lone-quote cleanup
6) `_row_date_phase_status` + valid YEAR filter + `_deduplicate_apr`
7) phase comparison of date-excluded rows against final retained rows;
   `_classify_truncated_rows` -> matched/unmatched truncated CSVs
8) write cleaned APR + malformed drops; print structured stdout summary

Output files (all written to the repo root unless paths are overridden via `run_repair`;
the authoritative list is the path assignment in `_set_paths`)
- Primary: `tablea2_cleaned_parsefilter_repair.csv` — the only artifact downstream consumers
  (e.g. `charts/basic_apr_charts.py`) read.
- Truncated classification: `matched_truncated_repair.csv`, `unmatched_truncated_repair.csv`
- Upsert ambiguity audit: `ambiguous_truncated_repair.csv`
- Dropped rows (date mismatches + invalid years): `date_year_mismatch_rows_parsefilter_repair.csv`
- Phase comparison: `date_excluded_phase_comparison_parsefilter_repair.csv` — potential
  repeated phase activity using parsed pipeline values and exported record ordinals.
- Metrics: stdout summary block only. Metric names are defined by the `metrics` list in `main`;
  per-run values are deliberately not recorded here, since a pasted snapshot goes stale silently.
"""

import csv
import io
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from itertools import chain
from time import perf_counter
import re
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

_THIS_DIR = Path(__file__).resolve().parent
# This script and the .xlsm workbooks live in data-cleanup/; the CSV data it reads and
# writes lives at the repo root, where every downstream consumer expects it.
_REPO_ROOT = _THIS_DIR.parent


def _set_paths(base_dir: Path, output_dir: Path | None = None) -> None:
    global _input_dir
    global _output_dir
    global apr_path
    global cleaned_path
    global date_year_mismatch_path
    global date_excluded_phase_comparison_path
    global matched_truncated_path
    global unmatched_truncated_path
    global ambiguous_truncated_path

    _input_dir = Path(base_dir).resolve()
    _output_dir = Path(output_dir).resolve() if output_dir is not None else _input_dir

    apr_path = _input_dir / "tablea2.csv"
    cleaned_path = _output_dir / "tablea2_cleaned_parsefilter_repair.csv"
    date_year_mismatch_path = _output_dir / "date_year_mismatch_rows_parsefilter_repair.csv"
    date_excluded_phase_comparison_path = _output_dir / "date_excluded_phase_comparison_parsefilter_repair.csv"
    matched_truncated_path = _output_dir / "matched_truncated_repair.csv"
    unmatched_truncated_path = _output_dir / "unmatched_truncated_repair.csv"
    ambiguous_truncated_path = _output_dir / "ambiguous_truncated_repair.csv"


_set_paths(_REPO_ROOT)

_A2_REQUIRED_HEADERS = {"A2_1_ID", "A2_18_Affordable"}
_A2_TEXT_COLUMNS = ("NO_FA_DR", "NOTES", "FIN_ASSIST_NAME")
_XLSM_TO_APR_PHASE = (
    ("A2_6_Units", "NO_ENTITLEMENTS"),
    ("A2_9_Units", "NO_BUILDING_PERMITS"),
    ("A2_10_Units", "NO_OTHER_FORMS_OF_READINESS"),
)

IDENTITY_KEY_COLS = ["JURIS_NAME", "CNTY_NAME", "YEAR", "APN", "STREET_ADDRESS", "JURS_TRACKING_ID"]
PHASE_APR_COLS = [apr for _, apr in _XLSM_TO_APR_PHASE]

APR_DEDUP_COLS = [
    "JURIS_NAME", "CNTY_NAME", "YEAR", "APN", "STREET_ADDRESS", "PROJECT_NAME",
    *PHASE_APR_COLS, "DEM_DES_UNITS",
]

_DATE_CHECK_CONFIG = [
    ('BP_ISSUE_DT1', 'NO_BUILDING_PERMITS', "ISS_DATE mismatch"),
    ('ENT_APPROVE_DT1', 'NO_ENTITLEMENTS', "ENT_DATE mismatch"),
    ('CO_ISSUE_DT1', 'NO_OTHER_FORMS_OF_READINESS', "CO_DATE mismatch"),
]

_AFFORDABILITY_BOILERPLATE_PREFIX = re.compile(
    r"^\s*(Used HCD Affordability Calculator|ABAG ADU Affordability Study)",
    re.IGNORECASE,
)


def _deduplicate_apr(df):
    """Deduplicate APR rows on project identity + pipeline counts. Returns (df_deduped, n_removed)."""
    cols = [c for c in APR_DEDUP_COLS if c in df.columns]
    if len(cols) != len(APR_DEDUP_COLS):
        return df, 0
    n_before = len(df)
    numeric_cols = PHASE_APR_COLS + ["DEM_DES_UNITS"]
    df = df.assign(**{c: pd.to_numeric(df[c], errors='coerce').fillna(0) for c in numeric_cols if c in df.columns}
    ).drop_duplicates(subset=cols, keep="first")
    return df, n_before - len(df)


def extract_year_from_date(val):
    """Extract year from date string. Returns year as int or None if invalid/empty."""
    if pd.isna(val):
        return None
    v = str(val).strip()
    if not v or v in ("nan", "None"):
        return None
    if '-' in v and len(v) >= 10 and v[:4].isdigit():
        return int(v[:4])
    if '/' in v and len(parts := v.split('/')) == 3 and len(parts[2]) == 4 and parts[2].isdigit():
        return int(parts[2])
    return None


def safe_int(val):
    """Convert value to int, returning None if not numeric."""
    if pd.isna(val):
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _row_date_phase_status(row):
    """Classify date-year alignment across all active phases.

    Returns (has_any_mismatch, has_any_match, first_mismatch_label).
    A row should only be dropped when has_any_mismatch=True AND has_any_match=False,
    i.e. no active phase has a date matching the reporting year.
    """
    row_year = safe_int(row.get('YEAR'))
    if row_year is None:
        return (False, False, None)
    has_mismatch, has_match, first_label = False, False, None
    for date_col, count_col, label in _DATE_CHECK_CONFIG:
        count_int = safe_int(row.get(count_col))
        if count_int is None or count_int <= 0:
            continue
        date_year = extract_year_from_date(row.get(date_col))
        if date_year is None:
            continue
        if date_year == row_year:
            has_match = True
        else:
            has_mismatch = True
            if first_label is None:
                first_label = label
    return (has_mismatch, has_match, first_label)


def _normalize_phase_date(value):
    """Return a full calendar date; accept ISO dates/times and explicit US dates only."""
    if pd.isna(value):
        return None
    text = str(value).strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)?", text):
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
        if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", text):
            return datetime.strptime(text, "%m/%d/%Y").date().isoformat()
    except ValueError:
        pass
    return None


def _compare_date_excluded_phases(excluded, retained):
    """Compare pipeline phase values, preserving all potential counterpart edges.

    IDs are 1-based CSV data-record ordinals in the existing dropped/clean exports.
    Candidate matches indicate potentially repeated activity, never proven duplicates.
    """
    started = perf_counter()
    identity_cols = ["JURIS_NAME", "CNTY_NAME", "APN", "STREET_ADDRESS", "JURS_TRACKING_ID"]
    columns = ["excluded_row_id", *identity_cols, "YEAR", "phase",
               "source_date_pipeline_value", "normalized_date", "source_homes_pipeline_value",
               "source_homes_parsed", "excluded_date_matches_reporting_year", "status", "reason",
               "identity_basis", "candidate_count", "candidate_retained_row_ids",
               "candidate_retained_years", "retained_reporting_year_matches_phase_date",
               "shared_candidate", "identity_conflict_retained_row_ids"]
    # Config labels already distinguish the three phases; no second phase/count map.
    phase_names = {"ENT_DATE mismatch": "entitlement", "ISS_DATE mismatch": "permit",
                   "CO_DATE mismatch": "completion"}
    retained_index = defaultdict(list)
    for ordinal, (_, row) in enumerate(retained.iterrows(), 1):
        norm = tuple(_norm_str(row.get(c)) for c in identity_cols)
        if all(norm[:3]):
            retained_index[norm[:3]].append((ordinal, row, norm))
    records, edges = [], defaultdict(int)
    for ordinal, (_, row) in enumerate(excluded.iterrows(), 1):
        norm = tuple(_norm_str(row.get(c)) for c in identity_cols)
        try:
            year = Decimal(str(row.get("YEAR")))
            year = int(year) if year.is_finite() and year == year.to_integral_value() else None
        except (InvalidOperation, ValueError, TypeError):
            year = None
        for date_col, count_col, label in _DATE_CHECK_CONFIG:
            raw_count = row.get(count_col)
            if not _norm_str(raw_count):
                continue
            try:
                count = Decimal(str(raw_count))
                valid_count = count.is_finite() and count > 0 and count == count.to_integral_value()
                if count.is_finite() and count == 0:
                    continue
            except InvalidOperation:
                valid_count = False
            count = int(count) if valid_count else None
            date = _normalize_phase_date(row.get(date_col))
            reasons = []
            if not all(norm[:3]) or not (norm[4] or norm[3]):
                reasons.append("missing_identity")
            if year is None:
                reasons.append("invalid_reporting_year")
            if count is None:
                reasons.append("invalid_phase_homes")
            if date is None:
                reasons.append("invalid_or_missing_phase_date")
            rec = dict(excluded_row_id=ordinal, **{c: row.get(c, "") for c in identity_cols},
                       YEAR=row.get("YEAR"), phase=phase_names[label],
                       source_date_pipeline_value=row.get(date_col), normalized_date=date,
                       source_homes_pipeline_value=raw_count, source_homes_parsed=count,
                       excluded_date_matches_reporting_year=(int(date[:4]) == year if date and year is not None else None),
                       status="insufficient_evidence" if reasons else "no_candidate_match",
                       reason=";".join(reasons), identity_basis="", candidate_count=0,
                       candidate_retained_row_ids=[], candidate_retained_years=[],
                       retained_reporting_year_matches_phase_date=False, shared_candidate=False,
                       identity_conflict_retained_row_ids=[])
            bases = set()
            if not reasons:
                for retained_id, other, other_norm in retained_index.get(norm[:3], []):
                    try:
                        other_year = Decimal(str(other.get("YEAR")))
                        other_count = Decimal(str(other.get(count_col)))
                    except InvalidOperation:
                        continue
                    if not (other_year.is_finite() and other_year == other_year.to_integral_value()
                            and other_year != year and other_year == int(date[:4])
                            and other_count.is_finite() and other_count == count
                            and _normalize_phase_date(other.get(date_col)) == date):
                        continue
                    if norm[4] and other_norm[4]:
                        if norm[4] != other_norm[4]:
                            continue
                        if norm[3] and other_norm[3] and norm[3] != other_norm[3]:
                            rec["identity_conflict_retained_row_ids"].append(retained_id)
                            continue
                        basis = "tracking_id"
                    elif norm[3] and norm[3] == other_norm[3]:
                        basis = "address_missing_tracking_id"
                    else:
                        continue
                    rec["candidate_retained_row_ids"].append(retained_id)
                    rec["candidate_retained_years"].append(int(other_year))
                    bases.add(basis)
                    edges[(retained_id, rec["phase"])] += 1
                rec["identity_basis"] = ";".join(sorted(bases))
            records.append(rec)
    for rec in records:
        ids = rec["candidate_retained_row_ids"]
        rec["candidate_count"] = len(ids)
        rec["retained_reporting_year_matches_phase_date"] = bool(ids)
        rec["shared_candidate"] = any(edges[(i, rec["phase"])] > 1 for i in ids)
        if rec["status"] != "insufficient_evidence":
            if rec["identity_conflict_retained_row_ids"]:
                rec["status"], rec["reason"] = "identity_conflict", "matching_tracking_id_conflicting_address"
            elif len(ids) > 1:
                rec["status"], rec["reason"] = "ambiguous_candidates", "multiple_eligible_retained_records"
            elif rec["shared_candidate"]:
                rec["status"], rec["reason"] = "shared_retained_candidate", "retained_phase_claimed_by_multiple_excluded_events"
            elif ids:
                rec["status"], rec["reason"] = "candidate_match", "potentially_repeated_activity_not_proven_duplicate"
            else:
                rec["reason"] = "no_counterpart_under_rule_in_final_retained_data"
        for key in ("candidate_retained_row_ids", "candidate_retained_years", "identity_conflict_retained_row_ids"):
            rec[key] = json.dumps(rec[key])
    result = pd.DataFrame(records, columns=columns)
    result["source_homes_parsed"] = pd.Series(
        [rec["source_homes_parsed"] for rec in records], dtype=object
    )
    print("Phase comparison: candidate statuses mean potentially repeated activity, not proven duplicates.")
    print(f"phase_comparison_inputs excluded={len(excluded)} retained={len(retained)} events={len(result)} candidate_edges={sum(edges.values())}")
    for (phase, status), group in result.groupby(["phase", "status"], sort=True):
        known = group["source_homes_parsed"].dropna()
        print(f"phase_comparison phase={phase} status={status} events={len(group)} homes={sum(int(v) for v in known)} unknown_counts={len(group)-len(known)}")
    print(f"phase_comparison_elapsed_seconds {perf_counter() - started:.6f}")
    return result


def _repair_quote_corruption(raw_text):
    """Repair known structural quote corruption using text patterns only."""
    quote = chr(34)
    backslash = chr(92)
    opener = "," + quote + backslash + backslash + quote + quote
    closer_pattern = re.compile(r"^([A-Z][A-Z ]*?)" + quote * 3 + r"([,\n\r])")
    lines = raw_text.splitlines(keepends=True)
    repaired_lines = []
    closer_lines = set()
    replaced_openers = 0
    replaced_closers = 0

    for line_no, line in enumerate(lines, start=1):
        cursor = 0
        out = []
        while True:
            pos = line.find(opener, cursor)
            if pos == -1:
                out.append(line[cursor:])
                break
            after = pos + len(opener)
            if after < len(line) and line[after] == " ":
                out.append(line[cursor:after])
                cursor = after
                continue
            out.append(line[cursor:pos])
            out.append("," + backslash + backslash)
            cursor = after
            replaced_openers += 1
        repaired = "".join(out)
        repaired, n_close = closer_pattern.subn(r"\1\2", repaired)
        if n_close:
            replaced_closers += n_close
            closer_lines.add(line_no)
        repaired_lines.append(repaired)
    return "".join(repaired_lines), replaced_openers, replaced_closers, closer_lines


def _count_csv_rows(csv_text):
    """Count valid data rows in CSV text (rows matching header column count)."""
    reader = csv.reader(io.StringIO(csv_text))
    expected_len = len(next(reader))
    return sum(1 for row in reader if len(row) == expected_len)


def _strip_affordability_trailing_quotes(df):
    """Strip one trailing ASCII quote from known HCD/ABAG boilerplate in text columns."""
    cols = [c for c in _A2_TEXT_COLUMNS if c in df.columns]
    if not cols:
        return 0
    n_cells = 0
    for col in cols:
        ser = df[col]
        s = ser.astype(str)
        match_prefix = s.str.match(_AFFORDABILITY_BOILERPLATE_PREFIX, na=False)
        stripped = s.str.rstrip()
        ends_quote = stripped.str.endswith('"')
        to_fix = match_prefix & ends_quote
        if not to_fix.any():
            continue
        newvals = stripped[to_fix].str.slice(0, -1).str.rstrip()
        df.loc[to_fix, col] = newvals.values
        n_cells += int(to_fix.sum())
    return n_cells


def _repair_column_shift_rows(df):
    """Fix rows where NOTES text is shifted into NO_FA_DR; returns repaired row count."""
    shifted_cols = [
        "NO_FA_DR",
        "TERM_AFF_DR",
        "DEM_DES_UNITS",
        "DEM_OR_DES_UNITS",
        "DEM_DES_UNITS_OWN_RENT",
        "DENSITY_BONUS_TOTAL",
        "DENSITY_BONUS_NUMBER_OTHER_INCENTIVES",
        "DENSITY_BONUS_INCENTIVES",
        "DENSITY_BONUS_RECEIVE_REDUCTION",
        "NOTES",
    ]
    if any(c not in df.columns for c in shifted_cols):
        return 0
    text = df["NO_FA_DR"].astype(str)
    non_numeric = pd.to_numeric(df["NO_FA_DR"], errors="coerce").isna()
    has_keywords = text.str.contains(r"HCD|ABAG|affordability|Entitlement", case=False, na=False)
    has_spill_marker = text.str.contains("\",\",", regex=False, na=False)
    notes_empty = df["NOTES"].fillna("").astype(str).str.strip().eq("")
    suspect = non_numeric & has_keywords & has_spill_marker & notes_empty
    n_repaired = int(suspect.sum())
    if n_repaired == 0:
        return 0
    shifted = df.loc[suspect, shifted_cols].copy()
    df.loc[suspect, shifted_cols[:-1]] = shifted[shifted_cols[1:]].to_numpy()
    df.loc[suspect, shifted_cols[-1]] = shifted[shifted_cols[0]].values
    return n_repaired


def _extract_truncated_closer_rows(csv_text, closer_lines):
    """Extract closer-touched lines that still parse to fewer than expected columns."""
    csv_lines = csv_text.splitlines()
    if not csv_lines or not closer_lines:
        return pd.DataFrame()
    header = next(csv.reader(io.StringIO(csv_lines[0])))
    expected_len = len(header)
    rows = []
    for line_no in sorted(closer_lines):
        if line_no <= 1 or line_no > len(csv_lines):
            continue
        row = next(csv.reader(io.StringIO(csv_lines[line_no - 1])))
        parsed_len = len(row)
        if parsed_len == 0 or parsed_len >= expected_len:
            continue
        padded = row + [""] * (expected_len - parsed_len)
        rec = dict(zip(header, padded))
        rec["_source_line"] = line_no
        rec["_parsed_len"] = parsed_len
        rows.append(rec)
    return pd.DataFrame(rows)


def _classify_truncated_rows(df_clean, truncated_df):
    """Match truncated rows to clean identities and return (matched_df, unmatched_df)."""
    if truncated_df.empty:
        return pd.DataFrame(), pd.DataFrame()
    key_cols = ["JURIS_NAME", "CNTY_NAME", "APN", "STREET_ADDRESS"]
    if any(c not in df_clean.columns for c in key_cols):
        return pd.DataFrame(), truncated_df.copy()
    _clean = df_clean.copy()
    norm = {c: _clean[c].astype(str).str.strip().str.upper() for c in key_cols}
    year_num = pd.to_numeric(_clean["YEAR"], errors="coerce")
    activity = sum(
        pd.to_numeric(_clean.get(col), errors="coerce").fillna(0) for col in PHASE_APR_COLS
    )
    strict_map = defaultdict(list)
    relaxed_map = defaultdict(list)
    fallback_map = defaultdict(list)
    for idx in _clean.index:
        strict_map[(norm["JURIS_NAME"].loc[idx], norm["CNTY_NAME"].loc[idx], norm["APN"].loc[idx], norm["STREET_ADDRESS"].loc[idx])].append(idx)
        relaxed_map[(norm["JURIS_NAME"].loc[idx], norm["CNTY_NAME"].loc[idx], norm["APN"].loc[idx])].append(idx)
        fallback_map[(norm["JURIS_NAME"].loc[idx], norm["APN"].loc[idx])].append(idx)

    matched_records = []
    unmatched_records = []
    for _, row in truncated_df.iterrows():
        row_k = {c: str(row.get(c, "")).strip().upper() for c in key_cols}
        idxs = strict_map.get((row_k["JURIS_NAME"], row_k["CNTY_NAME"], row_k["APN"], row_k["STREET_ADDRESS"]), [])
        stage = "strict_juris_cnty_apn_addr"
        if not idxs:
            idxs = relaxed_map.get((row_k["JURIS_NAME"], row_k["CNTY_NAME"], row_k["APN"]), [])
            stage = "relaxed_juris_cnty_apn"
        if not idxs:
            idxs = fallback_map.get((row_k["JURIS_NAME"], row_k["APN"]), [])
            stage = "relaxed_juris_apn"
        rec = row.to_dict()
        if not idxs:
            rec["verdict"] = "unmatched"
            rec["match_stage"] = ""
            rec["matched_years"] = ""
            rec["max_pipeline_activity"] = 0
            unmatched_records.append(rec)
            continue
        max_activity = float(activity.loc[idxs].max())
        years = sorted(int(y) for y in year_num.loc[idxs].dropna().unique())
        rec["verdict"] = "matched_active" if max_activity > 0 else "matched_zero"
        rec["match_stage"] = stage
        rec["matched_years"] = "|".join(str(y) for y in years)
        rec["max_pipeline_activity"] = max_activity
        matched_records.append(rec)
    return pd.DataFrame(matched_records), pd.DataFrame(unmatched_records)



def _norm_str(val):
    if pd.isna(val):
        return ""
    s = str(val).strip()
    if not s or s.lower() in {"nan", "none"}:
        return ""
    return s.upper()


def _to_workbook_stem(juris_name):
    s = re.sub(r"[^A-Za-z0-9]+", "", str(juris_name or ""))
    return s.strip()


def _resolve_workbook_path(row):
    year = str(row.get("YEAR", "")).strip()
    juris = _to_workbook_stem(row.get("JURIS_NAME", ""))
    if not year or not juris:
        return None
    candidate = _THIS_DIR / f"{juris}{year}.xlsm"
    return candidate if candidate.exists() else None


def _load_a2_rows_with_indexes(workbook_path, cache):
    cached = cache.get(str(workbook_path))
    if cached is not None:
        return cached
    rows_raw = pd.read_excel(workbook_path, sheet_name="Table A2", header=None, dtype=str)
    header_idx = None
    header_names = None
    for idx in range(min(80, len(rows_raw))):
        row_vals = [str(v).strip() if not pd.isna(v) else "" for v in rows_raw.iloc[idx].tolist()]
        if _A2_REQUIRED_HEADERS.issubset(set(row_vals)):
            header_idx = idx
            header_names = row_vals
            break
    if header_idx is None:
        result = {"rows": [], "id_map": {}, "pair_map": {}, "apn_map": {}}
        cache[str(workbook_path)] = result
        return result
    data = rows_raw.iloc[header_idx + 1 :].copy()
    data.columns = header_names
    rows = []
    id_map = {}
    pair_map = {}
    apn_map = {}
    for raw_excel_idx, rec in data.iterrows():
        row = {k: ("" if pd.isna(v) else str(v).strip()) for k, v in rec.to_dict().items() if str(k).strip()}
        if not any(row.values()):
            continue
        row["__excel_row_number"] = int(raw_excel_idx) + 1
        rows.append(row)
        key_id = _norm_str(row.get("A2_1_ID", ""))
        key_apn = _norm_str(row.get("A2_1_Current", ""))
        key_addr = _norm_str(row.get("A2_1_Address", ""))
        if key_id:
            id_map.setdefault(key_id, []).append(row)
        if key_apn:
            apn_map.setdefault(key_apn, []).append(row)
        if key_apn or key_addr:
            pair_map.setdefault((key_apn, key_addr), []).append(row)
    result = {"rows": rows, "id_map": id_map, "pair_map": pair_map, "apn_map": apn_map}
    cache[str(workbook_path)] = result
    return result


def map_a2_row_to_apr_record(a2_row, identity_row):
    mapped = {
        "APN": a2_row.get("A2_1_Current", ""),
        "STREET_ADDRESS": a2_row.get("A2_1_Address", ""),
        "PROJECT_NAME": a2_row.get("A2_1_Name", ""),
        "JURS_TRACKING_ID": a2_row.get("A2_1_ID", ""),
        "UNIT_CAT": a2_row.get("A2_2_Unit", ""),
        "TENURE": a2_row.get("A2_3_Tenure", ""),
        "EXTR_LOW_INCOME_UNITS": a2_row.get("A2_13_xLow", ""),
        "APPROVE_SB35": a2_row.get("A2_14_Stream", ""),
        "INFILL_UNITS": a2_row.get("A2_15_Infill", ""),
        "FIN_ASSIST_NAME": a2_row.get("A2_16_Assist", ""),
        "DR_TYPE": a2_row.get("A2_17_Deed", ""),
        "NO_FA_DR": a2_row.get("A2_18_Affordable", ""),
        "TERM_AFF_DR": a2_row.get("A2_19_Terms", ""),
        "DEM_DES_UNITS": a2_row.get("A2_20_Units", ""),
        "DEM_OR_DES_UNITS": a2_row.get("A2_20_Dest", ""),
        "DEM_DES_UNITS_OWN_RENT": a2_row.get("A2_20_Demo", ""),
        "DENSITY_BONUS_TOTAL": a2_row.get("A2_22_DB", ""),
        "DENSITY_BONUS_NUMBER_OTHER_INCENTIVES": a2_row.get("A2_23_DB", ""),
        "DENSITY_BONUS_INCENTIVES": a2_row.get("A2_24_DB", ""),
        "DENSITY_BONUS_RECEIVE_REDUCTION": a2_row.get("A2_25_DB", ""),
        "NOTES": a2_row.get("A2_21_Notes", ""),
    }
    for xlsm_key, apr_col in _XLSM_TO_APR_PHASE:
        mapped[apr_col] = a2_row.get(xlsm_key, "")
    # Income-tier unit counts, per development stage. HCD codes the stage as the field
    # number (A2_4 entitlement, A2_7 building permit, A2_10 certificate of occupancy) and
    # the deed restriction as a Deed/None suffix. Unlike the identity fields above these
    # ARE patterned, so they are generated rather than tabulated. Omitting them left every
    # XLSM-upserted row with unit totals but no affordability breakdown.
    for a2_stage, prefix in (("A2_4", ""), ("A2_7", "BP_"), ("A2_10", "CO_")):
        for a2_tier, tier in (("vLow", "VLOW"), ("Low", "LOW"), ("Mod", "MOD")):
            mapped[f"{prefix}{tier}_INCOME_DR"] = a2_row.get(f"{a2_stage}_{a2_tier}Deed", "")
            mapped[f"{prefix}{tier}_INCOME_NDR"] = a2_row.get(f"{a2_stage}_{a2_tier}None", "")
        mapped[f"{prefix}ABOVE_MOD_INCOME"] = a2_row.get(f"{a2_stage}_Above", "")
    mapped["JURIS_NAME"] = identity_row.get("JURIS_NAME", "")
    mapped["CNTY_NAME"] = identity_row.get("CNTY_NAME", "")
    mapped["YEAR"] = identity_row.get("YEAR", "")
    return mapped


def _lone_quote_cleanup(df):
    fixed = 0
    for col in [c for c in _A2_TEXT_COLUMNS if c in df.columns]:
        ser = df[col]
        as_str = ser.astype(str).str.strip()
        mask = as_str.eq('"')
        if not mask.any():
            continue
        df.loc[mask, col] = ""
        fixed += int(mask.sum())
    return fixed


def _dedupe_truncated_identities(truncated_rows):
    if truncated_rows.empty:
        return pd.DataFrame()
    key_cols = IDENTITY_KEY_COLS
    keyed = truncated_rows.copy()
    for col in key_cols:
        if col not in keyed.columns:
            keyed[col] = ""
    for col in key_cols:
        keyed[col] = keyed[col].map(_norm_str)
    deduped = keyed.drop_duplicates(subset=key_cols, keep="first").copy()
    return deduped


def _identity_key(row):
    return tuple(_norm_str(row.get(col, "")) for col in IDENTITY_KEY_COLS)


def _build_identity_source_map(truncated_rows):
    if truncated_rows.empty:
        return {}
    source_map = {}
    for _, row in truncated_rows.iterrows():
        key = _identity_key(row)
        entry = source_map.setdefault(key, {"source_lines": [], "raw_row_count": 0})
        entry["raw_row_count"] += 1
        source_line = row.get("_source_line")
        if pd.isna(source_line):
            continue
        line_int = int(source_line)
        if line_int not in entry["source_lines"]:
            entry["source_lines"].append(line_int)
    for entry in source_map.values():
        entry["source_lines"].sort()
    return source_map


def _identity_context(identity, source_info, workbook_path):
    return {
        "workbook_path": Path(workbook_path).name,
        "source_lines": "|".join(str(v) for v in source_info["source_lines"]),
        "raw_truncated_rows_for_identity": source_info["raw_row_count"],
        "JURIS_NAME": identity.get("JURIS_NAME", ""),
        "CNTY_NAME": identity.get("CNTY_NAME", ""),
        "YEAR": identity.get("YEAR", ""),
        "APN": identity.get("APN", ""),
        "STREET_ADDRESS": identity.get("STREET_ADDRESS", ""),
        "JURS_TRACKING_ID": identity.get("JURS_TRACKING_ID", ""),
    }


def _candidate_excel_row_numbers(candidates):
    row_numbers = []
    for candidate in candidates:
        raw = candidate.get("__excel_row_number")
        try:
            row_numbers.append(int(raw))
        except (TypeError, ValueError):
            row_numbers.append("")
    return row_numbers


def _candidate_key_digest(candidates):
    fields = ["A2_1_ID", "A2_1_Current", "A2_1_Address", "A2_2_Unit", "A2_3_Tenure"]
    parts = []
    for candidate in candidates:
        values = [_norm_str(candidate.get(field, "")) for field in fields]
        parts.append(",".join(values))
    return " ; ".join(parts)


def _build_ambiguity_record(
    stage,
    xlsm_count,
    df_count,
    identity,
    source_info,
    workbook_path,
    match_stage_used="",
    excel_row_numbers=None,
    candidate_key_digest="",
    integrity_issue=None,
):
    if excel_row_numbers is None:
        excel_row_numbers = []
    record = _identity_context(identity, source_info, workbook_path)
    record.update(
        {
            "ambiguity_stage": stage,
            "xlsm_candidate_count": xlsm_count,
            "df_candidate_count": df_count,
            "match_stage_used": match_stage_used,
            "excel_row_numbers": "|".join(str(v) for v in excel_row_numbers if str(v)),
            "candidate_key_digest": candidate_key_digest,
            "integrity_violation_reason": "",
            "integrity_expected_tracking_id": "",
            "integrity_candidate_tracking_ids": "",
        }
    )
    if integrity_issue:
        record.update(integrity_issue)
    return record


def _tracking_stage_integrity_issue(match_result, identity):
    if match_result["match_stage_used"] != "tracking_id":
        return None
    expected_id = _norm_str(identity.get("JURS_TRACKING_ID", ""))
    observed = [_norm_str(candidate.get("A2_1_ID", "")) for candidate in match_result["candidates"]]
    bad_ids = [candidate_id for candidate_id in observed if candidate_id != expected_id]
    if not bad_ids:
        return None
    return {
        "integrity_violation_reason": "tracking_stage_candidate_id_mismatch",
        "integrity_expected_tracking_id": expected_id,
        "integrity_candidate_tracking_ids": "|".join(observed),
    }


def _normalize_mapped_payload(mapped):
    return {key: _norm_str(value) for key, value in mapped.items()}


def _all_mapped_payloads_equivalent(mapped_payloads):
    if not mapped_payloads:
        return False
    baseline = _normalize_mapped_payload(mapped_payloads[0])
    for payload in mapped_payloads[1:]:
        if _normalize_mapped_payload(payload) != baseline:
            return False
    return True


def _deterministic_candidate_index(excel_row_numbers):
    best_idx = 0
    best_row = None
    for idx, row_num in enumerate(excel_row_numbers):
        if isinstance(row_num, int) and (best_row is None or row_num < best_row):
            best_row = row_num
            best_idx = idx
    return best_idx


def _find_a2_matches(indexes, identity):
    track_id = _norm_str(identity.get("JURS_TRACKING_ID", ""))
    apn = _norm_str(identity.get("APN", ""))
    addr = _norm_str(identity.get("STREET_ADDRESS", ""))
    if track_id and track_id != "N/A":
        hit = indexes["id_map"].get(track_id, [])
        if hit:
            return {
                "match_stage_used": "tracking_id",
                "candidates": hit,
                "excel_row_numbers": _candidate_excel_row_numbers(hit),
            }
    pair_hit = indexes["pair_map"].get((apn, addr), [])
    if pair_hit:
        return {
            "match_stage_used": "apn_address_pair",
            "candidates": pair_hit,
            "excel_row_numbers": _candidate_excel_row_numbers(pair_hit),
        }
    apn_hit = indexes["apn_map"].get(apn, [])
    return {
        "match_stage_used": "apn_only",
        "candidates": apn_hit,
        "excel_row_numbers": _candidate_excel_row_numbers(apn_hit),
    }


def _build_identity_index(df):
    for col in IDENTITY_KEY_COLS:
        if col not in df.columns:
            return None
    cols = [df[col].map(_norm_str).tolist() for col in IDENTITY_KEY_COLS]
    index = defaultdict(list)
    for pos, idx in enumerate(df.index):
        key = tuple(c[pos] for c in cols)
        index[key].append(idx)
    return index


def _identity_matches(identity_index, identity):
    if identity_index is None:
        return []
    return identity_index.get(_identity_key(identity), [])


def _apply_mapped_to_df_row(df, idx, mapped):
    """Write mapped payload values into a single DataFrame row.

    Mapped values are workbook strings. Assigning one into a numeric column used to let
    pandas upcast the column implicitly, which is deprecated and will raise in a future
    pandas. Cast the column to object first: same resulting values, no warning.
    """
    for col, val in mapped.items():
        if col not in df.columns:
            continue
        if isinstance(val, str) and pd.api.types.is_numeric_dtype(df[col]):
            df[col] = df[col].astype(object)
        df.at[idx, col] = val


def _apply_paired_upserts(pairs, df, identity):
    """Apply all paired XLSM-to-DF mappings, return count of rows updated."""
    for xlsm_row, idx in pairs:
        _apply_mapped_to_df_row(df, idx, map_a2_row_to_apr_record(xlsm_row, identity))
    return len(pairs)


def _resolve_multi_xlsm(matches, identity, df, identity_index):
    """Resolve multiple XLSM candidates for one truncated identity.

    Returns (resolution, mapped_candidates_or_None, pairs_or_None):
        "collapsed" – all payloads equivalent; caller picks one from mapped_candidates
        "paired"    – each candidate matched to a unique DF row via phase counts
        "ambiguous" – unresolvable
    """
    mapped_candidates = [map_a2_row_to_apr_record(c, identity) for c in matches]
    if _all_mapped_payloads_equivalent(mapped_candidates):
        return "collapsed", mapped_candidates, None
    update_idxs = _identity_matches(identity_index, identity)
    pairs = _pair_xlsm_to_df_by_phase(matches, update_idxs, df)
    if pairs is not None:
        return "paired", None, pairs
    return "ambiguous", None, None


def _pair_xlsm_to_df_by_phase(xlsm_rows, df_idxs, df):
    """Pair XLSM candidates to DataFrame rows using phase count columns.

    Pass 1: match XLSM rows to DF rows that have non-zero phase data.
    Pass 2: assign remaining XLSM rows to skeleton DF rows (all-zero phases,
    typically from truncation that lost the phase counts).

    Returns list of (xlsm_row, df_index) if all pair uniquely, else None.
    """
    if len(xlsm_rows) != len(df_idxs):
        return None
    phase_cols = [col for _, col in _XLSM_TO_APR_PHASE if col in df.columns]
    populated, skeletons = [], []
    for idx in df_idxs:
        (skeletons if all((safe_int(df.at[idx, c]) or 0) == 0 for c in phase_cols)
         else populated).append(idx)
    used_xlsm, pairs = set(), []
    for idx in populated:
        df_phases = {c: safe_int(df.at[idx, c]) or 0 for c in phase_cols}
        matched_i = None
        for i, xlsm_row in enumerate(xlsm_rows):
            if i in used_xlsm:
                continue
            xlsm_phases = {apr: safe_int(xlsm_row.get(xlsm, 0)) or 0
                           for xlsm, apr in _XLSM_TO_APR_PHASE if apr in df.columns}
            if all(xlsm_phases.get(c, 0) == v for c, v in df_phases.items()):
                matched_i = i
                break
        if matched_i is None:
            return None
        pairs.append((xlsm_rows[matched_i], idx))
        used_xlsm.add(matched_i)
    remaining = [i for i in range(len(xlsm_rows)) if i not in used_xlsm]
    if len(remaining) != len(skeletons):
        return None
    for xlsm_i, idx in zip(remaining, skeletons):
        pairs.append((xlsm_rows[xlsm_i], idx))
    return pairs


_APPEND_PLACEHOLDERS = frozenset({
    "", "NA", "NONE", "NAN", "UNKNOWN", "NOTAPPLICABLE", "0", "TBD", "NOTAVAILABLE",
})


def _append_identity_tokens(row):
    """Return canonical scope and same-field aliases without changing raw payloads."""
    scope = []
    tokens = set()
    for field in IDENTITY_KEY_COLS:
        raw = _norm_str(row.get(field, ""))
        compact = re.sub(r"[^A-Z0-9]", "", raw)
        if field == "YEAR":
            try:
                number = Decimal(raw)
                year = number if number.is_finite() and number == number.to_integral_value() else None
            except (InvalidOperation, ValueError):
                year = None
            scope.append(year)
            continue
        if field in IDENTITY_KEY_COLS[:2]:
            scope.append(compact if compact not in _APPEND_PLACEHOLDERS else None)
            continue
        if compact in _APPEND_PLACEHOLDERS:
            continue
        numeric_alias = None
        if field != "STREET_ADDRESS":
            if not compact.strip("0"):
                continue
            if re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]*)?", raw):
                whole, _, fraction = raw.partition(".")
                if not fraction.strip("0"):
                    negative = whole.startswith("-")
                    digits = whole.lstrip("+-").lstrip("0")
                    if not digits:
                        continue
                    numeric_alias = ("-" if negative else "") + digits
        tokens.add((field, compact))
        if numeric_alias is not None:
            tokens.add((field, numeric_alias))
    return tuple(scope), frozenset(tokens)


def _screen_pending_appends(original_identity_rows, current_df, pending_bundles):
    """Withhold linked or insufficient proposals, retaining all origins for review."""
    if not pending_bundles:
        return [], []
    aliases = []
    probe_index = defaultdict(list)
    reasons = [set() for _ in pending_bundles]
    existing_evidence = [[] for _ in pending_bundles]
    pending_evidence = [[] for _ in pending_bundles]
    for ordinal, bundle in enumerate(pending_bundles):
        origins = []
        for origin, key in (("source", "identity"), ("mapped", "mapped")):
            raw_identity = {field: bundle[key].get(field, "") for field in IDENTITY_KEY_COLS}
            scope, tokens = _append_identity_tokens(raw_identity)
            origins.append((origin, raw_identity, scope, tokens))
            for token in sorted(tokens):
                probe_index[token].append((ordinal, origin, scope))
        aliases.append(origins)
        if any(part is None for part in origins[1][2]) or not origins[1][3]:
            reasons[ordinal].add("insufficient_append_identity")

    # Stream each snapshot with its own scope/tokens and reuse normalized pending origins.
    existing_targets = (
        (snapshot, loaded_ordinal, raw_identity, scope, tokens)
        for snapshot, frame in (("original", original_identity_rows), ("current", current_df))
        for loaded_ordinal, values in enumerate(frame[IDENTITY_KEY_COLS].itertuples(index=False, name=None), 1)
        for raw_identity in (dict(zip(IDENTITY_KEY_COLS, values)),)
        for scope, tokens in (_append_identity_tokens(raw_identity),)
    )
    pending_targets = (
        ("pending", (other, other_origin), raw_identity, scope, tokens)
        for other, origins in enumerate(aliases)
        for other_origin, raw_identity, scope, tokens in origins
    )
    # Invalid or already linked nodes still participate; every directed edge is retained.
    for snapshot, target_ordinal, raw_identity, scope, tokens in chain(existing_targets, pending_targets):
        for field, token in sorted(tokens.intersection(probe_index)):
            for ordinal, origin, proposal_scope in probe_index[(field, token)]:
                if snapshot == "pending" and target_ordinal[0] == ordinal:
                    continue
                if any(a is not None and b is not None and a != b
                       for a, b in ((scope[0], proposal_scope[0]), (scope[2], proposal_scope[2]))):
                    continue
                if snapshot != "pending":
                    reasons[ordinal].add("possible_existing_duplicate")
                    existing_evidence[ordinal].append({
                        "loaded_record_ordinal": target_ordinal, "snapshot": snapshot,
                        "matched_field": field, "matched_token": token,
                        "proposal_origin": origin, "existing_identity": raw_identity,
                    })
                else:
                    other, other_origin = target_ordinal
                    reasons[ordinal].add("possible_pending_duplicate")
                    other_bundle = pending_bundles[other]
                    pending_evidence[ordinal].append({
                        "pending_ordinal": other + 1,
                        "source_lines": other_bundle["ambiguity_context"]["source_info"]["source_lines"],
                        "source_identity": aliases[other][0][1], "mapped_identity": aliases[other][1][1],
                        "matched_field": field, "matched_token": token,
                        "proposal_origin": origin, "other_origin": other_origin,
                    })

    accepted, withheld = [], []
    for ordinal, bundle in enumerate(pending_bundles):
        if not reasons[ordinal]:
            accepted.append(bundle["mapped"])
            continue
        record = _build_ambiguity_record(
            "append_candidate_review", bundle["xlsm_candidate_count"],
            len({edge["loaded_record_ordinal"] for edge in existing_evidence[ordinal]}),
            **bundle["ambiguity_context"],
        )
        for key, value in (
            ("append_review_reasons", sorted(reasons[ordinal])),
            ("append_candidate_mapped_identity", aliases[ordinal][1][1]),
            ("append_existing_candidates", existing_evidence[ordinal]),
            ("append_pending_candidates", pending_evidence[ordinal]),
        ):
            # Missing/nonfinite raw cells remain explicit strings in strict JSON.
            plain_value = json.loads(json.dumps(value, default=str), parse_constant=str)
            record[key] = json.dumps(plain_value, sort_keys=True, allow_nan=False)
        withheld.append(record)
    return accepted, withheld


def _append_rows_with_dtype_defaults(df, mapped_rows):
    if not mapped_rows:
        return df
    numeric_cols = {col for col in df.columns if pd.api.types.is_numeric_dtype(df[col])}
    rows = []
    for mapped_row in mapped_rows:
        row = {}
        for col in df.columns:
            if col in mapped_row:
                row[col] = mapped_row[col]
            elif col in numeric_cols:
                row[col] = np.nan
            else:
                row[col] = ""
        rows.append(row)
    return pd.concat([df, pd.DataFrame(rows, columns=df.columns)], ignore_index=True)


def _print_summary_block(metrics):
    print("\n" + "=" * 70)
    print("PARSEFILTER REPAIR SUMMARY")
    print("=" * 70)
    for key, value in metrics:
        print(f"{key:<45} {value}")
    print("=" * 70)


def _apply_validation_filters(df):
    status = df.apply(_row_date_phase_status, axis=1)
    status_df = pd.DataFrame(
        status.tolist(),
        index=df.index,
        columns=["has_mismatch", "has_match", "first_label"],
    )
    should_drop = status_df["has_mismatch"] & ~status_df["has_match"]
    df_after_mismatch = df[~should_drop].copy()
    df_dropped_mismatch = df[should_drop].copy()
    df_dropped_mismatch = df_dropped_mismatch.assign(
        mismatch_reason=status_df.loc[should_drop, "first_label"].fillna("")
    )

    valid_years = [2018, 2019, 2020, 2021, 2022, 2023, 2024]
    year_numeric = pd.to_numeric(df_after_mismatch["YEAR"], errors="coerce")
    invalid_year_mask = ~year_numeric.isin(valid_years)
    df_dropped_year = df_after_mismatch[invalid_year_mask].copy()
    df_dropped_year["mismatch_reason"] = "Invalid YEAR"
    df_clean = df_after_mismatch[~invalid_year_mask].copy()
    df_dropped = pd.concat([df_dropped_mismatch, df_dropped_year], ignore_index=True)
    return df_clean, df_dropped_mismatch, df_dropped_year, df_dropped


def _process_truncated_identity(identity, identity_source_map, workbook_cache, df, identity_index):
    counters = {
        "upsert_update": 0,
        "upsert_append": 0,
        "upsert_paired": 0,
        "upsert_rows_via_pairing": 0,
        "upsert_unresolved": 0,
        "upsert_ambiguous": 0,
        "upsert_integrity_error": 0,
        "equivalent_duplicates_collapsed": 0,
    }
    records = []
    source_info = identity_source_map.get(_identity_key(identity), {"source_lines": [], "raw_row_count": 0})
    workbook_path = _resolve_workbook_path(identity)
    if workbook_path is None:
        counters["upsert_unresolved"] += 1
        return counters, records, None
    indexes = _load_a2_rows_with_indexes(workbook_path, workbook_cache)
    match_result = _find_a2_matches(indexes, identity)
    matches = match_result["candidates"]
    match_stage_used = match_result["match_stage_used"]
    excel_row_numbers = match_result["excel_row_numbers"]
    candidate_key_digest = _candidate_key_digest(matches)
    integrity_issue = _tracking_stage_integrity_issue(match_result, identity)
    ambiguity_ctx = dict(
        identity=identity,
        source_info=source_info,
        workbook_path=workbook_path,
        match_stage_used=match_stage_used,
        excel_row_numbers=excel_row_numbers,
        candidate_key_digest=candidate_key_digest,
    )
    if integrity_issue is not None:
        counters["upsert_integrity_error"] += 1
        records.append(
            _build_ambiguity_record(
                "xlsm_match_integrity_error", len(matches), 0, **ambiguity_ctx, integrity_issue=integrity_issue
            )
        )
        return counters, records, None
    if not matches:
        counters["upsert_unresolved"] += 1
        return counters, records, None
    if len(matches) == 1:
        mapped = map_a2_row_to_apr_record(matches[0], identity)
    else:
        resolution, payload, pairs = _resolve_multi_xlsm(matches, identity, df, identity_index)
        if resolution == "paired":
            counters["upsert_rows_via_pairing"] += _apply_paired_upserts(pairs, df, identity)
            counters["upsert_paired"] += 1
            return counters, records, None
        if resolution == "ambiguous":
            counters["upsert_ambiguous"] += 1
            records.append(
                _build_ambiguity_record("xlsm_multi_match", len(matches), 0, **ambiguity_ctx)
            )
            return counters, records, None
        mapped = payload[_deterministic_candidate_index(excel_row_numbers)]
        counters["equivalent_duplicates_collapsed"] += 1
    update_idxs = _identity_matches(identity_index, identity)
    if len(update_idxs) > 1:
        pairs = _pair_xlsm_to_df_by_phase(matches, update_idxs, df)
        if pairs is None:
            counters["upsert_ambiguous"] += 1
            records.append(
                _build_ambiguity_record("df_multi_match", len(matches), len(update_idxs), **ambiguity_ctx)
            )
            return counters, records, None
        counters["upsert_rows_via_pairing"] += _apply_paired_upserts(pairs, df, identity)
        counters["upsert_paired"] += 1
        return counters, records, None
    if len(update_idxs) == 1:
        _apply_mapped_to_df_row(df, update_idxs[0], mapped)
        counters["upsert_update"] += 1
        return counters, records, None
    counters["upsert_append"] += 1
    return counters, records, {
        "identity": dict(identity), "mapped": mapped,
        "ambiguity_context": ambiguity_ctx, "xlsm_candidate_count": len(matches),
    }


def main():
    print(f"Loading: {apr_path}")
    raw_csv = apr_path.read_text(encoding="utf-8", errors="replace")
    fixed_csv, n_openers, n_closers, closer_lines = _repair_quote_corruption(raw_csv)

    rows_before_fix = _count_csv_rows(raw_csv)
    rows_after_fix = _count_csv_rows(fixed_csv)
    df = pd.read_csv(io.StringIO(fixed_csv), low_memory=False, on_bad_lines="skip")
    rows_loaded_main_pipeline = len(df)

    affordability_quote_cells_fixed = _strip_affordability_trailing_quotes(df)
    column_shift_repaired = _repair_column_shift_rows(df)
    truncated_rows = _extract_truncated_closer_rows(fixed_csv, closer_lines)

    identities = _dedupe_truncated_identities(truncated_rows)
    identity_source_map = _build_identity_source_map(truncated_rows)
    workbook_cache = {}
    identity_index = _build_identity_index(df)
    upsert_update = 0
    upsert_append = 0
    upsert_paired = 0
    upsert_rows_via_pairing = 0
    upsert_unresolved = 0
    upsert_ambiguous = 0
    upsert_integrity_error = 0
    equivalent_duplicates_collapsed = 0
    ambiguous_records = []
    pending_appends = []
    original_identity_rows = df[IDENTITY_KEY_COLS].copy()
    for _, identity in identities.iterrows():
        counters, identity_records, pending_append = _process_truncated_identity(
            identity, identity_source_map, workbook_cache, df, identity_index
        )
        upsert_update += counters["upsert_update"]
        upsert_append += counters["upsert_append"]
        upsert_paired += counters["upsert_paired"]
        upsert_rows_via_pairing += counters["upsert_rows_via_pairing"]
        upsert_unresolved += counters["upsert_unresolved"]
        upsert_ambiguous += counters["upsert_ambiguous"]
        upsert_integrity_error += counters["upsert_integrity_error"]
        equivalent_duplicates_collapsed += counters["equivalent_duplicates_collapsed"]
        ambiguous_records.extend(identity_records)
        if pending_append is not None:
            pending_appends.append(pending_append)

    accepted_appends, withheld_appends = _screen_pending_appends(original_identity_rows, df, pending_appends)
    append_candidates_withheld = len(withheld_appends)
    upsert_append -= append_candidates_withheld
    upsert_ambiguous += append_candidates_withheld
    ambiguous_records.extend(withheld_appends)
    df = _append_rows_with_dtype_defaults(df, accepted_appends)

    _resolved_total = (
        upsert_update + upsert_append + upsert_paired
        + upsert_ambiguous + upsert_unresolved + upsert_integrity_error
    )
    if _resolved_total != len(identities):
        raise AssertionError(
            "truncated identity accounting mismatch: "
            f"detected={len(identities)} update={upsert_update} append={upsert_append} "
            f"paired={upsert_paired} ambiguous={upsert_ambiguous} "
            f"unresolved={upsert_unresolved} integrity={upsert_integrity_error} "
            f"sum={_resolved_total}"
        )

    lone_quote_cells_fixed = _lone_quote_cleanup(df)
    truncated_rows_unresolved_after_xlsm = upsert_unresolved + upsert_ambiguous + upsert_integrity_error
    rows_after_upsert = len(df)

    df_clean, df_dropped_mismatch, df_dropped_year, df_dropped = _apply_validation_filters(df)

    df_clean, n_dedup = _deduplicate_apr(df_clean)
    phase_comparison = _compare_date_excluded_phases(df_dropped_mismatch, df_clean)
    matched_truncated, unmatched_truncated = _classify_truncated_rows(df_clean, truncated_rows)

    df_clean.to_csv(cleaned_path, index=False)
    matched_truncated.to_csv(matched_truncated_path, index=False)
    unmatched_truncated.to_csv(unmatched_truncated_path, index=False)
    pd.DataFrame(ambiguous_records).to_csv(ambiguous_truncated_path, index=False)
    df_dropped.to_csv(date_year_mismatch_path, index=False)
    phase_comparison.to_csv(date_excluded_phase_comparison_path, index=False)

    metrics = [
        ("rows_parsed_before_fix", rows_before_fix),
        ("rows_parsed_after_fix", rows_after_fix),
        ("rows_loaded_main_pipeline", rows_loaded_main_pipeline),
        ("net_row_delta_after_minus_before", rows_after_fix - rows_before_fix),
        ("opener_replacements", n_openers),
        ("closer_replacements", n_closers),
        ("affordability_trailing_quote_cells_fixed", affordability_quote_cells_fixed),
        ("affordability_lone_quote_cells_fixed", lone_quote_cells_fixed),
        ("column_shift_rows_repaired", column_shift_repaired),
        ("truncated_closer_rows", len(truncated_rows)),
        ("truncated_identities_detected", len(identities)),
        ("truncated_identities_resolved_update", upsert_update),
        ("truncated_identities_resolved_append", upsert_append),
        ("append_candidates_withheld", append_candidates_withheld),
        ("truncated_identities_resolved_paired", upsert_paired),
        ("truncated_rows_updated_via_pairing", upsert_rows_via_pairing),
        ("truncated_identities_unresolved", upsert_unresolved),
        ("truncated_identities_ambiguous", upsert_ambiguous),
        ("truncated_xlsm_match_integrity_errors", upsert_integrity_error),
        ("truncated_xlsm_equivalent_duplicates_collapsed", equivalent_duplicates_collapsed),
        ("truncated_rows_unresolved_after_xlsm", truncated_rows_unresolved_after_xlsm),
        ("rows_after_upsert", rows_after_upsert),
        ("rows_after_filters", len(df_clean)),
        ("rows_dropped_validation", len(df_dropped)),
        ("rows_dropped_date_mismatch", len(df_dropped_mismatch)),
        ("rows_dropped_invalid_year", len(df_dropped_year)),
        ("dedup_rows_removed", n_dedup),
    ]
    _print_summary_block(metrics)
    print(f"Output cleaned data: {cleaned_path}")
    print(f"Matched truncated: {matched_truncated_path} ({len(matched_truncated):,})")
    print(f"Unmatched truncated: {unmatched_truncated_path} ({len(unmatched_truncated):,})")
    print(f"Ambiguous upsert identities: {ambiguous_truncated_path} ({len(ambiguous_records):,})")
    print(f"Date-year mismatches: {date_year_mismatch_path} ({len(df_dropped):,})")


def run_repair(base_dir: Path, output_dir: Path | None = None) -> None:
    _set_paths(base_dir, output_dir)
    main()


if __name__ == "__main__":
    run_repair(_REPO_ROOT, _REPO_ROOT)

