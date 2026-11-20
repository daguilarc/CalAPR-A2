#!/usr/bin/env python3
"""List the Table A2 workbook rows that the public `tablea2.csv` does not carry.

Reader: whoever reconciles the public APR export against the nine `.xlsm` source workbooks beside
this script. Output: `workbook_rows_missing_from_public_csv.csv` at the repo root (every workbook
column, plus `_workbook` and `_excel_row`, sorted by workbook and row).

Rule
- A workbook row is judged when it has at least one identity part (tracking ID, APN or address; a
  blank or an N/A-like token counts as absent, via the repair script's `_is_missing_token`), has a
  positive A2_6 / A2_9 / A2_10 unit count, and passes the repair script's date rule against the
  reporting year in the file name (a row whose dated phases all fall outside that year is not).
- It is present when a physical record of the public file, of the same jurisdiction and year, has the
  same tracking ID, housing type, tenure (O -> Owner, R -> Renter) and address; with no tracking ID
  the match is on APN and address. Comparison ignores case and whitespace. Matching is a multiset:
  one public record accounts for one workbook row.
- The public file is first passed through the repair script's structural quote repair (closer and
  host-closer lines), which keeps a record from swallowing the next one, then read with `csv.reader`,
  so a quoted field holding a line break (Hesperia's "RES20-00428\\n5/16/2023") stays one record.
  Truncated lines count as records. Workbooks are read without default NA parsing, so a
  literal "N/A" cell stays text.
"""
import csv
import importlib.util
import io
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent
OUTPUT_NAME = "workbook_rows_missing_from_public_csv.csv"
_WORKBOOK_NAME = re.compile(r"([A-Za-z]+)(\d{4})\.xlsm")
_UNIT_COLUMNS = ("A2_6_Units", "A2_9_Units", "A2_10_Units")


def _repair_module():
    spec = importlib.util.spec_from_file_location("tablea2_parsefilter_repair",
                                                  _THIS_DIR / "tablea2_parsefilter_repair.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


repair = _repair_module()


def _norm(value):
    return " ".join(str(value).split()).upper()


def workbook_rows(path):
    """Every non-empty Table A2 data row of a workbook: header names -> text, plus `_excel_row`."""
    raw = pd.read_excel(path, sheet_name="Table A2", header=None, dtype=str, keep_default_na=False)
    header_at = next(i for i in range(min(80, len(raw)))
                     if repair._A2_REQUIRED_HEADERS.issubset({str(v).strip() for v in raw.iloc[i]}))
    names = [str(v).strip() for v in raw.iloc[header_at]]
    rows = []
    for index in range(header_at + 1, len(raw)):
        row = {name: str(value).strip() for name, value in zip(names, raw.iloc[index]) if name}
        if any(row.values()):
            row["_excel_row"] = index + 1
            rows.append(row)
    return rows


def _is_judged(row, year):
    """Has an identity part and positive units, and passes the date rule for `year`."""
    if all(not row.get(c, "") or repair._is_missing_token(row[c])
           for c in ("A2_1_ID", "A2_1_Current", "A2_1_Address")):
        return False
    if not any((repair.safe_int(row.get(c)) or 0) > 0 for c in _UNIT_COLUMNS):
        return False
    mismatch, match, _ = repair._row_date_phase_status(
        repair.map_a2_row_to_apr_record(row, {"YEAR": year}))
    return not (mismatch and not match)


def _keys(tracking_id, apn, unit, tenure, address):
    return ("id", _norm(tracking_id), _norm(unit), _norm(tenure), _norm(address)), \
           ("apn", _norm(apn), _norm(address))


def missing_rows(rows, records, header, juris, year):
    """The judged `rows` of one workbook that no record of `records` (public file, parsed) accounts for."""
    ix = {c: i for i, c in enumerate(header)}
    value = lambda rec, col: rec[ix[col]] if ix[col] < len(rec) else ""
    index = {"id": defaultdict(list), "apn": defaultdict(list)}
    for n, rec in enumerate(records):
        if _norm(value(rec, "JURIS_NAME")) != juris or value(rec, "YEAR").strip() != year:
            continue
        id_key, apn_key = _keys(value(rec, "JURS_TRACKING_ID"), value(rec, "APN"), value(rec, "UNIT_CAT"),
                                value(rec, "TENURE"), value(rec, "STREET_ADDRESS"))
        index["id"][id_key].append(n)
        index["apn"][apn_key].append(n)
    consumed, missing = set(), []
    for row in rows:
        if not _is_judged(row, year):
            continue
        tenure = repair.FORM_TO_CSV_TENURE.get(row.get("A2_3_Tenure", ""), row.get("A2_3_Tenure", ""))
        id_key, apn_key = _keys(row.get("A2_1_ID", ""), row.get("A2_1_Current", ""), row.get("A2_2_Unit", ""),
                                tenure, row.get("A2_1_Address", ""))
        has_id = row.get("A2_1_ID", "") and not repair._is_missing_token(row["A2_1_ID"])
        candidates = index["id"][id_key] if has_id else index["apn"][apn_key]
        free = next((n for n in candidates if n not in consumed), None)
        if free is None:
            missing.append(row)
        else:
            consumed.add(free)
    return missing


def public_records(public_csv_path):
    """(header, records) of the public file: structural quote repair, then `csv.reader`."""
    text = repair._repair_quote_corruption(
        Path(public_csv_path).read_text(encoding="utf-8", errors="replace"))[0]
    reader = csv.reader(io.StringIO(text, newline=""))
    header = next(reader)
    return header, [rec for rec in reader if rec]


def build(public_csv_path, workbook_dir):
    """Missing rows of all workbooks in `workbook_dir`, as a DataFrame sorted by workbook and row."""
    header, records = public_records(public_csv_path)
    found = []
    for path in sorted(Path(workbook_dir).glob("*.xlsm")):
        match = _WORKBOOK_NAME.fullmatch(path.name)
        if match is None:
            continue
        juris, year = match.group(1).upper(), match.group(2)
        for row in missing_rows(workbook_rows(path), records, header, juris, year):
            found.append({"_workbook": path.name, "_excel_row": row["_excel_row"],
                          **{k: v for k, v in row.items() if k != "_excel_row"}})
    return pd.DataFrame(found)


def main(public_csv_path=_REPO_ROOT / "tablea2.csv", workbook_dir=_THIS_DIR, output_dir=_REPO_ROOT):
    frame = build(public_csv_path, workbook_dir)
    frame.to_csv(Path(output_dir) / OUTPUT_NAME, index=False)
    print(f"{OUTPUT_NAME}: {len(frame)} rows")
    print(frame.groupby("_workbook").size().to_string())
    return frame


if __name__ == "__main__":
    main()
