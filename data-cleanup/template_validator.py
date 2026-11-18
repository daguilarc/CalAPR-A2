#!/usr/bin/env python3
"""Template-conformance validator for the CalAPR-A2 Table A2 pipeline.

The HCD `.xlsm` templates embed data-validation rules on Table A2 data cells.
Those rules are the regulator's machine-readable specification of a valid APR
row; this module extracts them (openpyxl main validations + x14 extension
validations parsed from the raw sheet XML), merges them across templates by reporting year,
and checks a cleaned APR CSV against the merged spec.

Provenance and assumptions (also recorded in every generated spec JSON):
- Data area: rows data_start..data_end, where data_start follows the
  template's "Start Data Entry Below" sentinel row and data_end is derived
  from the template's own rule geometry. Main-list rules scoped to template
  strips or to overflow rows outside the data area are recorded as
  unenforced, never applied to data rows. Data-area rules on a column with
  no header in that template are unenforced too ("column has no header in
  this template"), main and x14 alike.
- First rule wins: when several rules govern the same cells Excel applies the
  first in file order (checked against Excel on Campbell2024 AT13/AT500/AT1000,
  0..20 before 0..100). A later rule is "shadowed" (unenforced) only when
  earlier rules on that column cover all of its data-area rows; a partial
  overlap keeps it in the spec marked "partial_overlap": true. The validator
  does not scope rules to rows when checking a CSV, so both rules of a
  partial-overlap pair stay in the spec; as two distinct rules carried for
  one column and year they are listed by form_disagreements and judge no CSV
  row. No shipped template has a partial overlap.
- x14 helper-sheet list references are resolved to values with openpyxl
  (ranges capped at 200 cells; failures recorded as unenforced, not guessed).
- A rule with a single numeric/date formula and no operator is interpreted as
  `>= bound` (Excel stores operator=None in these templates).
- `type=None` slots are recorded as unenforced. The ONE known `custom` formula
  (the 2023+ A2_13_xLow extra-low-income rule) is enforced with structured
  semantics whenever the extracted formula matches it exactly (whitespace-
  normalized) and its own cell addresses resolve through the header row; any
  other custom formula is recorded as unenforced with reason
  "template formula changed" (drift gate).
- Blank cells ("", "nan", "none" spellings) are never violations.
- Multi-select: on columns where the template's own Worksheet_Change macro
  joins picks as "old, new" (read from vbaProject.bin), a list rule checks
  each item. Items split on "," or ";" (the macro writes ", "; the published
  CSV joins some columns, e.g. DR_TYPE and APPROVE_SB35, with ";").
- Unenforced reasons: "template strip (above data area)", "overflow rows
  (below data area)", "shadowed by an earlier rule on the same cells",
  "column has no header in this template", "template column not in the APR
  CSV mapping", "template formula changed", "operator ... not supported",
  "list reference resolved to no values", "non-list reference rule not
  evaluated" and "outside the data area".
- Governing form (Revision 5; replaces min_year supersession): a form's
  reporting year is read from its "Start Here" sheet, cell B5 (not from the
  filename). Each canonical rule carries `years`, the sorted reporting years
  of the forms that carry it; rules that are the same set of list items (the
  older templates store "R,O", the newer a JSON array) are one rule. A CSV
  row is judged only by rules whose `years` contain the row's YEAR. A row
  whose YEAR has no form (e.g. 2018, blank, unparseable) is not checked at
  all; the CLI prints their count on its own line. A (column, year) on which
  the forms of that year disagree (different rules, or only some of that
  year's forms carry a rule) is listed by form_disagreements and judges no
  row: neither form is picked. Without a YEAR column, validate_dataframe
  applies every rule of a single-form canonical (positive controls) and
  refuses a canonical holding several reporting years.
- Vocabulary (Revision 5): validate_dataframe(vocabulary="csv") (default; CLI
  --input) compares the published CSV's words, "form" compares the form's own
  codes (positive controls on workbook rows). Under "csv": TENURE list items
  are translated through FORM_TO_CSV_TENURE (defined once in the repair
  script and imported); INFILL_UNITS "0" counts as a blank cell; the rules on
  DEM_OR_DES_UNITS and DEM_DES_UNITS_OWN_RENT are applied with the allowed
  set = the form rule's own items plus "0" (author's ruling 2026-11-18: the
  data's actual state is accepted and modelled; HCD's published CSV shows "0"
  where the form had an entry, while rows the repair script rebuilds carry the
  form's own values "Demolished"/"Destroyed" and "O"/"R"). Anything else in
  those columns is a violation. The measurements behind each are cited at the
  constants below (measured 2026-11-18 from 2,551 matched workbook/CSV rows).
- Dates: A2_5_Date, A2_8_Date, A2_10_Date map to ENT_APPROVE_DT1,
  BP_ISSUE_DT1, CO_ISSUE_DT1 in this validator only (the repair script does
  not copy dates, deliberately). workbook_dataframe renders workbook datetime
  cells as YYYY-MM-DD, the form the CSV carries (measured 100% equal on
  167/1,533/1,356 matched cells). The form's date rule is 1950-01-01..
  2050-01-01 (serials 18264..54789); it is not a check against the row's YEAR.
- Date parsing uses an explicit format whitelist (%Y-%m-%d, %m/%d/%Y,
  %Y/%m/%d, %m/%d/%y); datetime text such as "2023-06-15 00:00:00" is
  rejected; pure-integer date-cell values are treated as Excel serials;
  non-finite numerics are malformed.

CLI:
  python3 template_validator.py --workbook Hesperia2024.xlsm [--workbook ...]
      [--input tablea2_cleaned_parsefilter_repair.csv] [--write-spec]
      [--spec-out template_spec.json] [--report violations.csv]
      [--check-spec template_spec.json]

With --input the CLI validates the CSV in the "csv" vocabulary against the
rules of the forms whose reporting year equals each row's YEAR, then prints
the rows not checked, form disagreements, and a per-column summary.
Without --input the CLI runs the positive control on EVERY --workbook, in the
"form" vocabulary: each workbook's own Table A2 rows are validated against
the rules built from that workbook alone, one "positive control:" line per
workbook. Exit codes: 1 when
--input is given and violations are found, or (no --input) when any
workbook's control has a violation; 2 on spec drift with --check-spec; 0
otherwise. The spec JSON is written only with --write-spec, so
positive-control runs never clobber the baseline.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

import openpyxl
import numpy as np
import pandas as pd
from openpyxl.utils import get_column_letter, column_index_from_string

THIS_DIR = Path(__file__).resolve().parent
EXCEL_EPOCH = datetime(1899, 12, 30)
SHEET = "Table A2"
DATA_END = 1000
SHEET_LAST_ROW = 1048576  # Excel's maximum row
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%m/%d/%y")
NO_HEADER_REASON = "column has no header in this template"
MAX_RESOLVED = 200
BLANK_SPELLINGS = {"", "nan", "none"}
START_SHEET = "Start Here"
VOCABULARIES = ("csv", "form")


def _repair_module():
    """The repair script, imported (never re-declared): the single source of
    the form->CSV mapping and of FORM_TO_CSV_TENURE."""
    if str(THIS_DIR) not in sys.path:
        sys.path.insert(0, str(THIS_DIR))
    import tablea2_parsefilter_repair as repair  # noqa: PLC0415
    return repair


# Judgment inputs for the "csv" vocabulary. Each was measured 2026-11-18 from
# 2,551 matched workbook/CSV rows (matching key: jurisdiction, YEAR, APN,
# tracking ID, address; mapping report in the Revision 5 notes under
# openspec/). Ruled by the measurement, not by the form: change them only with
# a new measurement.
# TENURE: O->Owner 2,202, R->Renter 349, no exceptions. Defined in the repair
# script so recovered rows and this validator share one definition.
FORM_TO_CSV_TENURE = _repair_module().FORM_TO_CSV_TENURE
CSV_VALUE_TRANSLATIONS = {"TENURE": FORM_TO_CSV_TENURE}
# INFILL_UNITS: a blank form cell is published as the string "0" (17 of 23
# blank form cells; 0 of 2,505 non-blank Y/N cells became "0").
CSV_ZERO_IS_BLANK_COLUMNS = ("INFILL_UNITS",)
# DEM_OR_DES_UNITS / DEM_DES_UNITS_OWN_RENT: the form's "Demolished", "O", "R"
# are published as "0" (measured 2026-11-18: 43/43 and 31/31 clean matched rows
# where the form had an entry). Ruled 2026-11-18 by the author: the data's
# actual state is accepted and modelled, so under "csv" the allowed set is the
# form rule's own items (what the repair script rebuilds from the workbooks)
# plus "0" (HCD's export). Added to the allowed items of list rules only.
CSV_EXPORT_EXTRA_ITEMS = {"DEM_OR_DES_UNITS": ("0",),
                          "DEM_DES_UNITS_OWN_RENT": ("0",)}
# Form date columns -> CSV date columns: equal on 167/167, 1,533/1,533 and
# 1,356/1,356 matched cells (no other CSV column agrees above 0.033).
# Validator only: the repair script deliberately does not copy dates.
A2_DATE_TO_APR_COLUMNS = {"A2_5_Date": "ENT_APPROVE_DT1",
                          "A2_8_Date": "BP_ISSUE_DT1",
                          "A2_10_Date": "CO_ISSUE_DT1"}
ASSUMPTIONS = {
    "single_formula_numeric_date": "interpreted as >= bound",
    "blank_cells": "'', 'nan', 'none' (any case) are never violations",
    "governing_form": ("a CSV row is judged only by rules of the form(s) whose "
                       "reporting year (Start Here!B5) equals the row's YEAR; "
                       "a row whose YEAR has no form is not checked; a "
                       "(column, year) on which same-year forms disagree is "
                       "reported and judges no row"),
    "csv_vocabulary": ("vocabulary='csv' translates TENURE list items "
                       "R->Renter, O->Owner, treats INFILL_UNITS '0' as blank "
                       "(measured 2026-11-18 from 2,551 matched workbook/CSV "
                       "rows); vocabulary='form' applies the form's own codes"),
    "demolition_columns_zero": ("HCD's published CSV shows '0' in "
                                "DEM_OR_DES_UNITS and DEM_DES_UNITS_OWN_RENT "
                                "in every complete matched row where the form "
                                "had an entry (measured 2026-11-18: 43/43, "
                                "31/31), while rows the repair script rebuilds "
                                "from the workbooks carry the form's own values "
                                "('Demolished'/'Destroyed'; 'O'/'R'). Author's "
                                "ruling 2026-11-18: that state is accepted and "
                                "modelled; vocabulary='csv' allows the form "
                                "rule's items plus '0' on those two columns, "
                                "anything else is a violation"),
    "date_mapping": ("A2_5_Date/A2_8_Date/A2_10_Date -> ENT_APPROVE_DT1/"
                     "BP_ISSUE_DT1/CO_ISSUE_DT1 in the validator only; "
                     "workbook datetimes render as YYYY-MM-DD"),
    "date_formats": ("whitelist " + ", ".join(DATE_FORMATS) +
                     "; pure-integer values treated as Excel serials"),
    "data_area": "rows data_start..data_end; data_start follows the "
                 "'Start Data Entry Below' sentinel, data_end is the start "
                 "row of the template's overflow block (the most common start "
                 "row of ranges running to the sheet's last row) minus one; "
                 "rules on header-less columns are listed as unenforced",
    "first_rule_wins": ("Excel applies the first rule in file order where "
                        "rules overlap; a later rule is shadowed (unenforced) "
                        "only when earlier rules cover all its data-area "
                        "rows; a partial overlap is kept with partial_overlap=true; "
                        "CSV rows are not row-scoped, so both rules count as "
                        "two distinct rules for one column and year, are "
                        "listed by form_disagreements and judge no CSV row "
                        "(no shipped template has one)"),
    "multi_select": ("list rules on columns whose Worksheet_Change macro "
                     "joins picks check each item; items split on ',' or "
                     "';' (macro writes ', '; the published CSV uses ';' in "
                     "some columns, e.g. DR_TYPE, APPROVE_SB35)"),
    "unenforced_listing": ("template strips, overflow rows, shadowed rules, "
                           "header-less columns, unmapped columns, unsupported "
                           "operators, drifted custom formulas and unresolved "
                           "references are listed in 'unenforced', not "
                           "dropped; rule types other than list, whole, "
                           "decimal, date and custom (e.g. textLength, time) "
                           "would be counted as enforced but are not "
                           "evaluated; no shipped template has one"),
    "custom_xlow": ("the known 2023+ A2_13_xLow formula is enforced: blank "
                    "passes, non-numeric fails, otherwise a violation iff the "
                    "value exceeds ALL THREE pair sums; blank/text comparator "
                    "cells count as 0 (Excel SUM semantics); any other custom "
                    "formula is drift and stays unenforced"),
}

# The one custom validation carried by the 2023+ templates (main validations,
# sqref anchored at the first data row): extra-low-income units on a row must
# be numeric and fit within at least one of the three low-income stage pairs.
# Stored whitespace-normalized; comparison strips all whitespace.
KNOWN_XLOW_CUSTOM_FORMULA = (
    "AND(ISNUMBER(AI13),OR(AI13<=SUM(Z13:AA13),"
    "AI13<=SUM(Q13:R13),AI13<=SUM(H13:I13)))"
)
_CELL = r"[A-Z]{1,3}\d+"
_COL = r"[A-Z]{1,3}"
_KNOWN_CUSTOM_RE = re.compile(
    rf"^AND\(ISNUMBER\(({_CELL})\),OR\("
    rf"\1<=SUM\({_COL}\d+:({_COL})\d+\),"
    rf"\1<=SUM\({_COL}\d+:({_COL})\d+\),"
    rf"\1<=SUM\({_COL}\d+:({_COL})\d+\)\)\)$")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _data_start(ws, header_row: int) -> int:
    for row in range(1, header_row + 8):
        for col in range(1, min(ws.max_column, 12) + 1):
            v = ws.cell(row=row, column=col).value
            if isinstance(v, str) and "start data entry below" in v.lower():
                return row + 1
    return header_row + 1


def _data_end(ws, data_start: int) -> int:
    """Last data row. Every template ends its data area with an overflow block:
    ranges that start just past the data area and run to the sheet's last row
    (row 1001 in most templates, 2497 in Irvine2022, 662 in Hesperia2024).
    The most common start row among those ranges, minus one, is the data end.
    Only ranges starting after data_start vote, so ranges that begin at the
    data start and reach the sheet end (2019-2022 templates, e.g.
    H13:N1048576) do not vote at all. A data rule that starts lower and runs
    to the sheet end does vote (Hesperia2022 AG18:AG1048576) and is outvoted
    by the overflow block (7 to 1). A tie would be decided by first-seen order
    (Counter ordering), which no shipped template hits."""
    starts = Counter(r.min_row for dv in ws.data_validations.dataValidation
                     if dv.type for r in dv.sqref.ranges
                     if r.max_row == SHEET_LAST_ROW and r.min_row > data_start)
    return starts.most_common(1)[0][0] - 1 if starts else min(ws.max_row, DATA_END)


def _ovba_decompress(buf: bytes, i: int) -> bytes:
    """MS-OVBA 2.4.1 decompression of the container starting at buf[i]."""
    out = bytearray()
    i += 1  # signature byte 0x01
    while i + 2 <= len(buf):
        hdr = int.from_bytes(buf[i:i + 2], "little")
        size, compressed = (hdr & 0x0FFF) + 3, hdr & 0x8000
        chunk, i, start = buf[i + 2:i + size], i + size, len(out)
        if not compressed:
            out += chunk[:4096]
            continue
        j = 0
        while j < len(chunk):
            flags, j = chunk[j], j + 1
            for bit in range(8):
                if j >= len(chunk):
                    break
                if not (flags >> bit) & 1:
                    out.append(chunk[j])
                    j += 1
                    continue
                tok, j = int.from_bytes(chunk[j:j + 2], "little"), j + 2
                bc = max((len(out) - start - 1).bit_length(), 4)
                length, off = (tok & (0xFFFF >> bc)) + 3, (tok >> (16 - bc)) + 1
                for _ in range(length):
                    out.append(out[-off])
    return bytes(out)


def _ole_streams(d: bytes) -> dict:
    """Name -> bytes for every stream in an OLE compound file (vbaProject.bin)."""
    ss = 1 << int.from_bytes(d[30:32], "little")
    mss = 1 << int.from_bytes(d[32:34], "little")
    nfat, dirstart = (int.from_bytes(d[o:o + 4], "little") for o in (44, 48))
    cutoff, minifat_start, _, difat_start, ndifat = (
        int.from_bytes(d[o:o + 4], "little") for o in (56, 60, 64, 68, 72))
    sec = lambda n: d[512 + n * ss: 512 + (n + 1) * ss]
    words = lambda b: [int.from_bytes(b[k:k + 4], "little") for k in range(0, len(b), 4)]
    difat, n = words(d[76:512]), difat_start
    for _ in range(ndifat):
        s = sec(n)
        difat += words(s[:-4])
        n = int.from_bytes(s[-4:], "little")
    fat = [w for f in difat[:nfat] for w in words(sec(f))]

    def chain(start, table):
        while start < 0xFFFFFFFA:
            yield start
            start = table[start]

    read = lambda start: b"".join(sec(x) for x in chain(start, fat))
    dirs = read(dirstart)
    entries = []
    for k in range(0, len(dirs), 128):
        e = dirs[k:k + 128]
        nl = int.from_bytes(e[64:66], "little")
        entries.append((e[:max(nl - 2, 0)].decode("utf-16-le"), e[66],
                        int.from_bytes(e[116:120], "little"),
                        int.from_bytes(e[120:124], "little")))
    ministream = read(entries[0][2])
    minifat = [w for x in chain(minifat_start, fat) for w in words(sec(x))]
    streams = {}
    for name, typ, start, size in entries:
        if typ != 2:
            continue
        if size >= cutoff:
            streams[name] = read(start)[:size]
        else:
            streams[name] = b"".join(ministream[x * mss:(x + 1) * mss]
                                     for x in chain(start, minifat))[:size]
    return streams


def _multi_select_columns(workbook_path: Path, codename: str | None) -> set:
    """Column letters where the sheet's Worksheet_Change macro joins picks as
    "old, new". Read from the template's own VBA (module = the sheet's code
    name); commented-out lines do not count. Empty when there is no macro."""
    with zipfile.ZipFile(workbook_path) as zf:
        if "xl/vbaProject.bin" not in zf.namelist() or not codename:
            return set()
        vba = zf.read("xl/vbaProject.bin")
    module = _ole_streams(vba).get(codename, b"")
    at = module.find(b"\x00Attribut")
    if at < 3:
        return set()
    source = _ovba_decompress(module, at - 3).decode("latin-1")
    live = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("'"))
    if 'Oldvalue & ", " & Newvalue' not in live:
        return set()
    cols = set()
    for cond in re.findall(r"If\s+(Target\.column\s*=\s*\d+(?:\s+Or\s+Target\.column\s*=\s*\d+)*)\s+Then",
                           live, re.I):
        cols |= {get_column_letter(int(n)) for n in re.findall(r"\d+", cond)}
    return cols


def _sheet_xml_text(workbook_path: Path, sheet_index: int) -> str:
    with zipfile.ZipFile(workbook_path) as zf:
        names = zf.namelist()
        preferred = f"xl/worksheets/sheet{sheet_index + 1}.xml"
        if preferred in names:
            text = zf.read(preferred).decode("utf-8", "ignore")
            if "dataValidation" in text:
                return text
        best, best_text, best_n = "", "", -1
        for n in names:
            if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n):
                text = zf.read(n).decode("utf-8", "ignore")
                n_rules = (text.count("<dataValidation ")
                           + text.count("<x14:dataValidation "))
                if n_rules > best_n:
                    best, best_text, best_n = n, text, n_rules
        return best_text


def _x14_rules(sheet_text: str) -> list[dict]:
    """Parse x14 (extension) data validations — the real data-area rules that
    openpyxl drops. Returns type/operator/formulas plus xm:sqref ranges."""
    out = []
    for m in re.finditer(r"<x14:dataValidation\b([^>]*)>(.*?)</x14:dataValidation>",
                         sheet_text, re.S):
        attrs, body = m.group(1), m.group(2)
        t = re.search(r'\btype="([^"]+)"', attrs)
        sq = re.search(r"<xm:sqref>([^<]+)</xm:sqref>", body)
        if not t or not sq:
            continue
        op = re.search(r'\boperator="([^"]+)"', attrs)
        f1 = re.search(r"<x14:formula1>(.*?)</x14:formula1>", body, re.S)
        f2 = re.search(r"<x14:formula2>(.*?)</x14:formula2>", body, re.S)
        strip_tags = lambda g: re.sub(r"<[^>]+>", "", g).strip() if g else None
        out.append({"type": t.group(1),
                    "operator": op.group(1) if op else None,
                    "formula1": strip_tags(f1.group(1)) if f1 else None,
                    "formula2": strip_tags(f2.group(1)) if f2 else None,
                    "sqref": sq.group(1).strip()})
    return out


_REF_RE = re.compile(
    r"(?:'([^']+)'|([A-Za-z_ ]+?))!\$([A-Z]+)\$(\d+)(?::\$([A-Z]+)\$(\d+))?")


def _resolve_ref(ref: str, wb_values) -> tuple[str | None, list]:
    """Resolve 'Sheet'!$C$2:$C$5 (or a single cell) to the referenced values.
    wb_values must be loaded with data_only=True so cached cell values, not
    formulas, are returned."""
    m = _REF_RE.fullmatch(ref.strip())
    if not m:
        return None, []
    sheet = (m.group(1) or m.group(2)).strip()
    col1 = column_index_from_string(m.group(3))
    row1 = int(m.group(4))
    col2 = column_index_from_string(m.group(5) or m.group(3))
    row2 = int(m.group(6) or m.group(4))
    try:
        ws = wb_values[sheet]
    except KeyError:
        return None, []
    values = []
    for col in range(min(col1, col2), max(col1, col2) + 1):
        for row in range(min(row1, row2), max(row1, row2) + 1):
            v = ws.cell(row=row, column=col).value
            if v not in (None, ""):
                values.append(str(v))
            if len(values) >= MAX_RESOLVED:
                break
    return sheet, values


def known_custom_rule(formula, headers, sqref_col):
    """Classify an extracted `custom` validation against the one known 2023+
    formula (whitespace-normalized comparison). Returns structured semantics —
    target column/header, numeric requirement, and the three reference
    column-letter pairs, all derived from the FORMULA's own cell addresses
    mapped through the header row — when it matches and its target column
    agrees with the sqref column. Returns None for any drift, which the
    caller must record as unenforced ("template formula changed")."""
    norm = re.sub(r"\s+", "", str(formula or "")).upper()
    # Drift gate: ONLY the exact known constant is enforced. The regex below
    # is deliberately looser (any column letters); it only extracts the
    # addresses once equality has already established the formula's identity,
    # so a look-alike formula (e.g. SUM(Z13:AB13)) can never slip through.
    if norm != KNOWN_XLOW_CUSTOM_FORMULA.upper():
        return None
    m = _KNOWN_CUSTOM_RE.match(norm)
    if not m:
        return None
    target_col, row_anchor = re.match(r"([A-Z]{1,3})(\d+)", m.group(1)).groups()
    if target_col != sqref_col:
        return None
    target_header = headers.get(target_col)
    if not target_header:
        return None
    pairs = []
    for hi, lo in re.findall(rf"SUM\(({_COL})\d+:({_COL})\d+\)", norm):
        h_hi, h_lo = headers.get(hi), headers.get(lo)
        if not h_hi or not h_lo:
            return None
        pairs.append([h_hi, h_lo])
    return {"target_column": target_col, "target_header": target_header,
            "numeric": True, "row_anchor": int(row_anchor),
            "reference_pairs": pairs}


def _reporting_year(wb, workbook_path: Path) -> int:
    """The form's reporting year: "Start Here" sheet, cell B5 (A5 reads
    "Reporting Calendar Year"). Not the filename."""
    if START_SHEET not in wb.sheetnames:
        sys.exit(f"{workbook_path}: no '{START_SHEET}' sheet to read the reporting year from")
    value = wb[START_SHEET]["B5"].value
    try:
        if isinstance(value, bool):
            raise ValueError
        year = int(value.strip()) if isinstance(value, str) else int(value)
        ok = 1990 <= year <= 2100 and (isinstance(value, str) or value == year)
    except (TypeError, ValueError):
        ok = False
    if not ok:
        sys.exit(f"{workbook_path}: '{START_SHEET}'!B5 is {value!r}, not a reporting year")
    return year


def extract_spec(workbook_path: Path) -> dict:
    """Read one workbook's Table A2 into a spec dict: enforced rules (main +
    x14, data-area only), unenforced rules with reasons, provenance."""
    workbook_path = Path(workbook_path)
    wb = openpyxl.load_workbook(workbook_path, data_only=False)
    ws = wb[SHEET]

    header_row, headers = None, {}
    for row in range(1, 81):
        values = {c: ws.cell(row=row, column=c).value for c in range(1, ws.max_column + 1)}
        named = {c: v for c, v in values.items() if v}
        if "A2_1_ID" in named.values() and "A2_18_Affordable" in named.values():
            header_row = row
            headers = {get_column_letter(c): v for c, v in named.items()}
            break
    if header_row is None:
        sys.exit(f"{workbook_path}: no header row with A2_1_ID and A2_18_Affordable in {SHEET}")

    data_start = _data_start(ws, header_row)
    data_end = _data_end(ws, data_start)
    rules, unenforced, unspecified = [], [], 0
    custom_seen = set()
    claimed = {}  # column -> [(min_row, max_row)] already governed, file order

    def classify(header, col, rtype, f1, f2, op, source, rows):
        if rtype is None:
            return
        # Two rules on the same cells: Excel applies the first one in file
        # order (verified 2026-11-17 by asking Excel for the active rule on
        # Campbell2024 AT13/AT500/AT1000, which carries 0..20 then 0..100).
        # The later rule is shadowed only when earlier rules cover ALL of its
        # data-area rows; a partial overlap keeps it (flagged), since it still
        # governs the rows the earlier rules do not reach.
        lo, hi = max(rows[0], data_start), min(rows[1], data_end)
        earlier = claimed.get(col, [])
        reach = lo  # first data row not yet covered by the earlier rules
        for a, b in sorted(earlier):
            if a <= reach:
                reach = max(reach, b + 1)
        partial = reach <= hi and any(a <= hi and lo <= b for a, b in earlier)
        if earlier and reach > hi:
            unenforced.append({"a2_header": header, "column": col, "type": rtype,
                               "formula1": f1, "formula2": f2, "source": source,
                               "reason": "shadowed by an earlier rule on the "
                                         "same cells (Excel applies the first)"})
            return
        claimed.setdefault(col, []).append((lo, hi))
        flag = {"partial_overlap": True} if partial else {}
        if rtype == "custom":
            known = known_custom_rule(f1, headers, col)
            if known:
                # Enforced custom rule: structured semantics ride along and
                # build_canonical/validate_dataframe treat it like any rule.
                key = (known["target_header"], re.sub(r"\s+", "", str(f1)))
                if key not in custom_seen:
                    custom_seen.add(key)
                    rules.append({"a2_header": known["target_header"],
                                  "column": known["target_column"],
                                  "type": rtype, "formula1": f1,
                                  "formula2": None, "operator": None,
                                  "source": source, "custom": known, **flag})
                return
            # Drift gate: anything but the exact known formula stays unaudited.
            unenforced.append({"a2_header": header, "column": col, "type": rtype,
                               "formula1": f1, "source": source,
                               "reason": "template formula changed"})
            return
        rules.append({"a2_header": header, "column": col, "type": rtype,
                      "formula1": f1, "formula2": f2, "operator": op,
                      "source": source, **flag})

    for dv in ws.data_validations.dataValidation:
        for rng in dv.sqref.ranges:
            in_data = not (rng.max_row < data_start or rng.min_row > data_end)
            cols = [get_column_letter(c) for c in range(rng.min_col, rng.max_col + 1)]
            if dv.type is None:
                if in_data:
                    unspecified += len(cols)
                continue
            for col in cols:
                header = headers.get(col)
                if not header:
                    if in_data:
                        unenforced.append({
                            "a2_header": None, "column": col, "type": dv.type,
                            "formula1": None if dv.formula1 is None else str(dv.formula1),
                            "formula2": None if dv.formula2 is None else str(dv.formula2),
                            "source": "main", "reason": NO_HEADER_REASON})
                    continue
                if in_data:
                    classify(header, col, dv.type,
                             None if dv.formula1 is None else str(dv.formula1),
                             None if dv.formula2 is None else str(dv.formula2),
                             None if dv.operator is None else str(dv.operator),
                             "main", (rng.min_row, rng.max_row))
                else:
                    unenforced.append({
                        "a2_header": header, "column": col, "type": dv.type,
                        "formula1": None if dv.formula1 is None else str(dv.formula1),
                        "source": "main",
                        "reason": ("template strip (above data area)"
                                   if rng.max_row < data_start
                                   else "overflow rows (below data area)")})

    sheet_text = _sheet_xml_text(workbook_path, wb.sheetnames.index(SHEET))
    wb_values = openpyxl.load_workbook(workbook_path, data_only=True)
    for xr in _x14_rules(sheet_text):
        f1, resolved = xr["formula1"], None
        if xr["type"] == "list" and f1 and not f1.startswith('"'):
            if _REF_RE.fullmatch(f1.strip()):
                resolved = _resolve_ref(f1, wb_values)[1]
            if not resolved:
                unenforced.append({"type": "list", "formula1": f1,
                                   "source": "x14", "sqref": xr["sqref"],
                                   "reason": "list reference resolved to no values"})
                continue
        elif f1 and ("!" in f1 or f1.startswith("=")):
            unenforced.append({"type": xr["type"], "formula1": f1, "source": "x14",
                               "sqref": xr["sqref"],
                               "reason": "non-list reference rule not evaluated"})
            continue
        for rng in xr["sqref"].split():
            cells = re.findall(r"([A-Z]+)(\d+)", rng)
            rows = (int(cells[0][1]), int(cells[-1][1]))
            if rows[1] < data_start or rows[0] > data_end:
                unenforced.append({"type": xr["type"], "formula1": f1,
                                   "source": "x14", "sqref": rng,
                                   "reason": "outside the data area"})
                continue
            first, last = (column_index_from_string(c) for c in
                           (cells[0][0], cells[-1][0]))
            for col in (get_column_letter(i) for i in range(first, last + 1)):
                header = headers.get(col)
                if not header:
                    unenforced.append({"a2_header": None, "column": col,
                                       "type": xr["type"], "formula1": f1,
                                       "formula2": xr["formula2"], "source": "x14",
                                       "sqref": rng, "reason": NO_HEADER_REASON})
                    continue
                if xr["type"] == "list":
                    allowed = json.dumps(resolved) if resolved is not None else f1
                    classify(header, col, "list", allowed, None, None, "x14", rows)
                else:
                    classify(header, col, xr["type"], f1, xr["formula2"],
                             xr["operator"], "x14", rows)

    # Columns where the template's own macro appends each new pick as
    # "old, new" (HCD's multi-select). Their list rules check each item.
    multi = _multi_select_columns(workbook_path, ws.sheet_properties.codeName)
    for rule in rules:
        if rule["type"] == "list" and rule["column"] in multi:
            rule["multi_select"] = True

    seen, unique_unenforced = set(), []
    for u in unenforced:
        key = json.dumps(u, sort_keys=True)
        if key not in seen:
            seen.add(key)
            unique_unenforced.append(u)

    return {
        "workbook": workbook_path.name,
        "sha256": _sha256(workbook_path),
        "reporting_year": _reporting_year(wb, workbook_path),
        "extracted_at": datetime.now().isoformat(timespec="seconds"),
        "sheet": SHEET,
        "header_row": header_row,
        "data_start": data_start,
        "data_end": data_end,
        "headers": headers,
        "rules": rules,
        "unenforced": unique_unenforced,
        "unspecified_type_slots": unspecified,
    }


def a2_header_to_apr_columns(headers) -> dict:
    """A2 header name -> cleaned-CSV column name: the repair script's own
    mapping (imported, never re-declared) plus A2_DATE_TO_APR_COLUMNS, which
    only this validator carries."""
    a2_row = {h: h for h in headers}
    mapped = _repair_module().map_a2_row_to_apr_record(a2_row, {})
    result = {header: col for col, header in mapped.items() if header in headers}
    result.update({h: c for h, c in A2_DATE_TO_APR_COLUMNS.items() if h in headers})
    return result


def _allowed_items(formula1) -> list:
    """The items of a list rule: a JSON array (x14 references resolved to
    values) or a quoted comma string (main validations)."""
    f1 = formula1 or ""
    if f1.startswith("["):
        items = [a.strip().strip('"') for a in json.loads(f1) if str(a).strip()]
    else:
        items = [a.strip() for a in f1.strip('"').split(",")]
    return [a for a in items if a]


def build_canonical(specs: list[dict]) -> dict:
    """Merge per-workbook specs into one canonical rule set.

    Rules are keyed by (APR column, type, formula1, formula2, operator); a list
    rule is keyed by its set of items instead of its spelling. Each carries its
    template provenance and `years`, the reporting years (Start Here!B5) of the
    forms that carry it (governing form, see module docstring). Workbook
    provenance and the named assumptions travel with it.
    """
    workbooks, merged, unmapped = [], {}, []
    for spec in sorted(specs, key=lambda s: s["workbook"]):
        name = spec["workbook"]
        year = spec["reporting_year"]
        workbooks.append({k: spec[k] for k in
                          ("workbook", "sha256", "extracted_at", "header_row",
                           "reporting_year", "unspecified_type_slots")})
        mapping = a2_header_to_apr_columns(set(spec["headers"].values()))
        for rule in spec["rules"]:
            col = mapping.get(rule["a2_header"])
            if col is None:
                unmapped.append({"a2_header": rule["a2_header"],
                                 "type": rule["type"],
                                 "formula1": rule["formula1"],
                                 "reason": "template column not in the APR CSV mapping",
                                 "template": name})
                continue
            multi = bool(rule.get("multi_select"))
            if rule["type"] == "list":
                key = (col, "list", frozenset(_allowed_items(rule["formula1"])), multi)
            else:
                key = (col, rule["type"], rule["formula1"], rule["formula2"],
                       rule["operator"], multi)
            entry = merged.setdefault(key, {
                "apr_column": col,
                "a2_headers": [],
                "type": rule["type"],
                "formula1": rule["formula1"],
                "formula2": rule["formula2"],
                "operator": rule["operator"],
                "interpreted_operator": _interpreted_operator(rule),
                "multi_select": multi,
                "sources": [],
                "templates": [],
                "years": [],
            })
            if rule["a2_header"] not in entry["a2_headers"]:
                entry["a2_headers"].append(rule["a2_header"])
            if rule["source"] not in entry["sources"]:
                entry["sources"].append(rule["source"])
            if name not in entry["templates"]:
                entry["templates"].append(name)
            if rule.get("partial_overlap"):
                entry["partial_overlap"] = True
            if year not in entry["years"]:
                entry["years"] = sorted(entry["years"] + [year])
            custom = rule.get("custom")
            if custom:
                refs = [[mapping.get(h) for h in pair]
                        for pair in custom.get("reference_pairs", [])]
                if all(c for pair in refs for c in pair):
                    entry["interpreted_operator"] = "custom"
                    entry["custom"] = {"numeric": True,
                                       "reference_apr_columns": refs}
    rules = sorted(merged.values(), key=lambda r: (r["apr_column"], r["type"] or ""))
    supported = {">=", ">", "<=", "<", "between", "notBetween", "equal",
                 "in", "custom"}
    enforced, unenforced = [], []
    for rule in rules:
        if rule["interpreted_operator"] in supported:
            enforced.append(rule)
        elif rule["type"] == "custom":
            unenforced.append({"apr_column": rule["apr_column"],
                               "type": rule["type"], "formula1": rule["formula1"],
                               "operator": rule["operator"], "templates": rule["templates"],
                               "reason": "custom rule references columns "
                                         "outside the APR mapping"})
        else:
            unenforced.append({"apr_column": rule["apr_column"],
                               "type": rule["type"], "formula1": rule["formula1"],
                               "operator": rule["operator"], "templates": rule["templates"],
                               "reason": f"operator {rule['operator']!r} not supported"})
    # Per-template unenforced entries (and unmapped rules) merge with the
    # canonical-level ones above; identical entries collapse into one carrying
    # every template it came from.
    seen_unenforced = {}
    per_template = [(spec["workbook"], u) for spec in
                    sorted(specs, key=lambda s: s["workbook"])
                    for u in spec.get("unenforced", [])]
    per_template += [(u["template"], u) for u in unmapped]
    for name, u in per_template:
        key = json.dumps({k: v for k, v in u.items() if k != "template"},
                         sort_keys=True)
        if key in seen_unenforced:
            if name not in seen_unenforced[key]["templates"]:
                seen_unenforced[key]["templates"].append(name)
        else:
            entry = {k: v for k, v in u.items() if k != "template"}
            entry["templates"] = [name]
            seen_unenforced[key] = entry
            unenforced.append(entry)
    return {
        "workbooks": workbooks,
        "rules": enforced,
        "unenforced": unenforced,
        "assumptions": ASSUMPTIONS,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def _interpreted_operator(rule: dict) -> str:
    if rule["type"] == "list":
        return "in"
    op = rule["operator"]
    normalized = {"greaterThanOrEqual": ">=", "lessThanOrEqual": "<=",
                  "greaterThan": ">", "lessThan": "<"}.get(op, op)
    if normalized:
        return normalized
    if rule["formula2"]:
        return "between"
    if rule["type"] in ("whole", "decimal", "date"):
        return ">="  # named assumption; see module docstring
    return "unspecified"


def _bound(value, rule_type: str):
    if rule_type == "date":
        return pd.Timestamp(EXCEL_EPOCH + timedelta(days=float(value)))
    return float(value)


def _within(values: pd.Series, rule: dict):
    """Boolean Series: True where numeric/date values satisfy the rule."""
    op = rule["interpreted_operator"]
    b1 = _bound(rule["formula1"], rule["type"]) if rule["formula1"] is not None else None
    b2 = _bound(rule["formula2"], rule["type"]) if rule["formula2"] is not None else None
    if op == ">=":
        return values >= b1
    if op == ">":
        return values > b1
    if op == "<=":
        return values <= b1
    if op == "<":
        return values < b1
    if op == "between":
        return (values >= b1) & (values <= b2)
    if op == "notBetween":
        return (values < b1) | (values > b2)
    if op == "equal":
        return values == b1
    raise ValueError(f"unhandled operator {op!r}")


def _row_years(series: pd.Series) -> pd.Series:
    """Each row's YEAR as a float; blank, unparseable and non-integral
    values are NaN."""
    years = pd.to_numeric(series.astype(str).str.strip(), errors="coerce")
    return years.where(years % 1 == 0)


def form_disagreements(canonical: dict) -> list[dict]:
    """(column, year) pairs on which the forms of one reporting year disagree:
    more than one distinct rule carries that column and year, or only some of
    that year's forms carry a rule for it. Neither form is picked; validate_
    dataframe judges no row on a pair listed here."""
    year_of = {w["workbook"]: w["reporting_year"] for w in canonical["workbooks"]}
    forms_per_year = Counter(year_of.values())
    rules, carriers = {}, {}
    for rule in canonical["rules"]:
        for year in rule["years"]:
            rules.setdefault((rule["apr_column"], year), set()).add(id(rule))
        for tpl in rule["templates"]:
            if tpl in year_of:
                carriers.setdefault((rule["apr_column"], year_of[tpl]), set()).add(tpl)
    out = []
    for (col, year), ids in sorted(rules.items()):
        forms = len(carriers.get((col, year), ()))
        if len(ids) > 1 or 0 < forms < forms_per_year[year]:
            out.append({"apr_column": col, "year": year, "rules": len(ids),
                        "forms_with_rule": forms, "forms": forms_per_year[year]})
    return out


def unchecked_year_counts(df: pd.DataFrame, canonical: dict,
                          year_col: str = "YEAR") -> dict:
    """Rows validate_dataframe does not judge because their YEAR has no form,
    counted by YEAR ("blank or unparseable" for the rest)."""
    if year_col not in df.columns:
        return {}
    years = _row_years(df[year_col])
    form_years = {w["reporting_year"] for w in canonical["workbooks"]}
    counts = Counter("blank or unparseable" if pd.isna(y) else str(int(y))
                     for y in years[~years.isin(form_years)])
    return dict(sorted(counts.items(), key=lambda kv: (not kv[0].isdigit(), kv[0])))


def validate_dataframe(df: pd.DataFrame, canonical: dict, year_col: str = "YEAR",
                       row_offset: int = 2, vocabulary: str = "csv") -> list[dict]:
    """Classify every (row, rule) pair into pass or violation. Total function
    over its documented inputs; it raises ValueError on an unknown vocabulary
    and on a frame with no YEAR column judged against several forms.

    Governing form: a row is judged only by rules whose `years` contain the
    row's YEAR; a row whose YEAR has no form is not judged (see
    unchecked_year_counts); a (column, year) listed by form_disagreements
    judges no row. Without a YEAR column every rule applies, which is only
    meaningful for a single-form canonical (positive controls).
    vocabulary: "csv" compares the published CSV's words (TENURE items
    translated, INFILL_UNITS "0" blank, "0" also allowed on DEM_OR_DES_UNITS
    and DEM_DES_UNITS_OWN_RENT); "form" compares the form's own codes.
    row_offset converts DataFrame index to human row numbers (2 for a CSV with
    a header line; the template's data_start for a positive control).
    """
    if vocabulary not in VOCABULARIES:
        raise ValueError(f"vocabulary must be one of {VOCABULARIES}, got {vocabulary!r}")
    csv_vocab = vocabulary == "csv"
    violations = []
    if year_col in df.columns:
        years = _row_years(df[year_col])
    elif len({w["reporting_year"] for w in canonical["workbooks"]}) > 1:
        raise ValueError(f"no {year_col!r} column to choose between the reporting "
                         "years of the canonical's forms")
    else:
        years = None
    disagreeing = {}
    for d in form_disagreements(canonical):
        disagreeing.setdefault(d["apr_column"], []).append(d["year"])

    by_column = {}
    for rule in canonical["rules"]:
        by_column.setdefault(rule["apr_column"], []).append(rule)

    for col, rules in by_column.items():
        if col not in df.columns:
            continue
        s = df[col].astype(str).str.strip()
        blank = s.str.lower().isin(BLANK_SPELLINGS)
        if csv_vocab and col in CSV_ZERO_IS_BLANK_COLUMNS:
            blank = blank | s.eq("0")

        evaluated = []
        for rule in rules:
            if years is None:
                governing = pd.Series(True, index=df.index)
            else:
                governing = years.isin(rule["years"])
                if col in disagreeing:
                    governing &= ~years.isin(disagreeing[col])

            if rule["type"] == "custom":
                pairs = (rule.get("custom") or {}).get("reference_apr_columns") or []
                if not pairs or any(c not in df.columns for p in pairs for c in p):
                    continue  # unresolvable comparators cannot be evaluated
                values = pd.to_numeric(s, errors="coerce")
                # Excel SUM: blank/text comparator cells count as 0.
                sums = []
                for a, b in pairs:
                    pa = pd.to_numeric(df[a].astype(str).str.strip(), errors="coerce").fillna(0)
                    pb = pd.to_numeric(df[b].astype(str).str.strip(), errors="coerce").fillna(0)
                    sums.append(pa + pb)
                exceeds_all = pd.Series(True, index=df.index)
                for total in sums:
                    exceeds_all &= values > total
                non_numeric = ~blank & values.isna()
                too_big = ~blank & values.notna() & exceeds_all
                labels = ",".join(f"{a}+{b}" for a, b in pairs)
                evaluated.append((rule, governing, non_numeric,
                                  "custom rule: value must be numeric (ISNUMBER)"))
                evaluated.append((rule, governing, too_big,
                                  f"custom rule: value exceeds every comparator "
                                  f"sum ({labels})"))
                continue

            if rule["type"] == "list":
                allowed = _allowed_items(rule["formula1"])
                if csv_vocab:
                    translation = CSV_VALUE_TRANSLATIONS.get(col, {})
                    allowed = ([translation.get(a, a) for a in allowed]
                               + list(CSV_EXPORT_EXTRA_ITEMS.get(col, ())))
                if rule.get("multi_select"):
                    # HCD's macro stores several picks as "a, b, c"; the
                    # published CSV joins them with ";".
                    items = s.str.split(r"[,;]", regex=True).map(
                        lambda xs: [x.strip() for x in xs])
                    bad = ~blank & ~items.map(lambda xs: all(x in allowed for x in xs))
                    reason = f"an item is not in {allowed} (multi-select)"
                else:
                    bad = ~blank & ~s.isin(allowed)
                    reason = f"value not in {allowed}"
            elif rule["type"] in ("whole", "decimal", "date"):
                if rule["type"] == "date":
                    digits = s.str.fullmatch(r"\d+").fillna(False)
                    serial_mask = digits & s.str.len().between(4, 7)
                    # Digits and separators only: pandas otherwise reads
                    # "now"/"today" as dates even under an explicit format.
                    text = s.where(~digits & s.str.fullmatch(r"[0-9/: -]+"), None)
                    values = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
                    for fmt in DATE_FORMATS:  # whitelist only; no inference
                        values = values.fillna(pd.to_datetime(text, format=fmt,
                                                              errors="coerce"))
                    malformed = ~blank & ((values.isna() & ~serial_mask)
                                          | (digits & ~serial_mask))
                    if serial_mask.any():
                        from_serial = pd.Series(pd.NaT, index=values.index)
                        from_serial[serial_mask] = [
                            pd.Timestamp(EXCEL_EPOCH + timedelta(days=float(v)))
                            for v in s[serial_mask]]
                        values = values.where(~serial_mask, from_serial)
                else:
                    values = pd.to_numeric(s, errors="coerce")
                    malformed = ~blank & ~(values.notna() & np.isfinite(values))
                    if rule["type"] == "whole":
                        malformed = malformed | (~blank & values.notna() & (values % 1 != 0))
                bad = malformed | (~blank & values.notna() & ~_within(values, rule))
                reason = f"violates {rule['interpreted_operator']} {rule['formula1']}"
                if rule["formula2"]:
                    reason += f" .. {rule['formula2']}"
            else:
                continue
            evaluated.append((rule, governing, bad, reason))

        for rule, governing, bad, reason in evaluated:
            for idx in df.index[bad & governing]:
                violations.append({
                    "row": int(idx) + row_offset,
                    "column": col,
                    "value": s.at[idx],
                    "reason": reason,
                    "templates": ",".join(rule["templates"]),
                    "years": rule["years"],
                })
    return violations


def workbook_dataframe(workbook_path: Path, spec: dict) -> pd.DataFrame:
    """The template's own Table A2 data rows, as a DataFrame keyed by APR
    column names. Positive-control input: rows entered under Excel's own
    validation."""
    wb = openpyxl.load_workbook(workbook_path, data_only=True)
    ws = wb[SHEET]
    header_row = spec["header_row"]
    headers = {c: ws.cell(row=header_row, column=c).value
               for c in range(1, ws.max_column + 1)}
    rows = []
    data_start = spec.get("data_start", spec["header_row"] + 1)
    for row in range(data_start, ws.max_row + 1):
        # Workbook dates render as the CSV's own YYYY-MM-DD text (measured exact).
        vals = {h: (v.strftime("%Y-%m-%d") if isinstance(v, date) else v)
                for h, v in ((h, ws.cell(row=row, column=c).value)
                             for c, h in headers.items() if h)}
        if any(v not in (None, "") for v in vals.values()):
            rows.append(vals)
    df = pd.DataFrame(rows)
    mapping = a2_header_to_apr_columns(set(spec["headers"].values()))
    return df.rename(columns=mapping)


def _summarize(violations: list[dict]) -> str:
    if not violations:
        return "no violations"
    counts = pd.DataFrame(violations).groupby(["column", "reason"]).size()
    lines = [f"  {col}: {n} x {reason}" for (col, reason), n in
             counts.sort_values(ascending=False).items()]
    return "\n".join(lines)


def _column_summary(violations: list[dict]) -> str:
    frame_ = pd.DataFrame(violations)
    per_col = frame_.groupby("column").agg(n=("row", "size"), rows=("row", "nunique"))
    return "\n".join(f"  {col}: {r.n} violations on {r.rows} rows"
                     for col, r in per_col.sort_values("n", ascending=False).iterrows())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workbook", action="append", required=True,
                    help="template .xlsm (repeatable)")
    ap.add_argument("--input", help="cleaned APR CSV to validate")
    ap.add_argument("--spec-out", default=str(THIS_DIR / "template_spec.json"))
    ap.add_argument("--write-spec", action="store_true",
                    help="write the canonical spec JSON to --spec-out "
                         "(positive controls must not clobber it)")
    ap.add_argument("--report", help="write violations CSV here")
    ap.add_argument("--check-spec", help="regenerate and diff against this spec JSON")
    args = ap.parse_args(argv)

    specs = [extract_spec(Path(w)) for w in args.workbook]
    canonical = build_canonical(specs)
    spec_text = json.dumps(canonical, indent=2)

    if args.check_spec:
        old = json.loads(Path(args.check_spec).read_text())
        old_rules = {json.dumps(r, sort_keys=True) for r in old["rules"]}
        new_rules = {json.dumps(r, sort_keys=True) for r in canonical["rules"]}
        for gone in sorted(old_rules - new_rules):
            print(f"DRIFT: rule removed: {gone}")
        for added in sorted(new_rules - old_rules):
            print(f"DRIFT: rule added: {added}")
        old_shas = {w["workbook"]: w["sha256"] for w in old["workbooks"]}
        for w in canonical["workbooks"]:
            if old_shas.get(w["workbook"], w["sha256"]) != w["sha256"]:
                print(f"DRIFT: workbook changed: {w['workbook']}")
        drift = (old_rules != new_rules
                 or {w["workbook"]: w["sha256"] for w in canonical["workbooks"]} != old_shas)
        print("spec drift detected" if drift else "spec unchanged")
        return 2 if drift else 0

    if args.write_spec:
        Path(args.spec_out).write_text(spec_text + "\n")
        print(f"spec: {len(canonical['rules'])} rules from {len(specs)} template(s) "
              f"-> {args.spec_out}")
    else:
        print(f"spec: {len(canonical['rules'])} rules from {len(specs)} template(s) "
              f"(not written; pass --write-spec)")
    for u in canonical.get("unenforced", []):
        print(f"unenforced: {u.get('reason')} "
              f"({u.get('a2_header') or u.get('column') or u.get('apr_column', '?')})")

    if not args.input:
        # One control per workbook, each judged by its OWN template's rules
        # (a combined canonical would hold a template's rows to rules of
        # other reporting years).
        failed = False
        for spec, workbook in zip(specs, args.workbook):
            own = build_canonical([spec])
            control = workbook_dataframe(Path(workbook), spec)
            first = spec.get("data_start", spec["header_row"] + 1)
            violations = validate_dataframe(control, own, row_offset=first,
                                            vocabulary="form")
            flagged_rows = len({v["row"] for v in violations})
            print(f"positive control: {spec['workbook']} Table A2 data rows: "
                  f"{len(control)} rows, {len(violations)} violations on "
                  f"{flagged_rows} rows")
            if violations:
                print(_summarize(violations))
                failed = True
        return 1 if failed else 0

    df = pd.read_csv(args.input, dtype=str, keep_default_na=False, na_values=[])
    for d in form_disagreements(canonical):
        print(f"form disagreement: {d['apr_column']} year {d['year']}: "
              f"{d['rules']} distinct rules, {d['forms_with_rule']} of "
              f"{d['forms']} forms carry one; no row judged")
    unchecked = unchecked_year_counts(df, canonical)
    detail = ", ".join(f"{k}: {n}" for k, n in unchecked.items())
    print(f"rows not checked (YEAR has no form): {sum(unchecked.values())}"
          + (f" ({detail})" if detail else ""))
    violations = validate_dataframe(df, canonical, vocabulary="csv")
    print(f"{args.input}: {len(df)} rows, {len(violations)} violations")
    if violations:
        print("per-column summary:")
        print(_column_summary(violations))
        print("by column and reason:")
        print(_summarize(violations))
        if args.report:
            pd.DataFrame(violations).to_csv(args.report, index=False)
            print(f"report: {args.report}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())


