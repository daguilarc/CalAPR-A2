"""Repair of swallowed records, split/shifted/over-wide rows and the dedup key.

Needs `tablea2.csv` (gitignored raw input) at the repo root; the module skips when it is absent.
"""
import contextlib
import csv
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "data-cleanup/tablea2_parsefilter_repair.py"
import importlib.util

spec = importlib.util.spec_from_file_location("swallow_cleaner", SOURCE)
cleaner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleaner)

RAW_PATH = REPO / "tablea2.csv"
if not RAW_PATH.exists():
    raise unittest.SkipTest(f"{RAW_PATH.name} is absent (gitignored raw input); nothing here can run")
with open(RAW_PATH, encoding="utf-8", newline="") as _fh:
    HEADER = next(csv.reader(_fh))
W = len(HEADER)


def row(**over):
    """A 52-field row from the real header; unspecified fields are ''."""
    unknown = set(over) - set(HEADER)
    assert not unknown, unknown
    return [over.get(c, "") for c in HEADER]


def to_text(rows):
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(HEADER)
    for r in rows:
        writer.writerow(r)
    return buf.getvalue()


def frame_of(rows):
    return pd.DataFrame(rows, columns=HEADER)


class DedupCoercionTests(unittest.TestCase):
    def test_output_values_preserved(self):
        a = row(JURIS_NAME="T", CNTY_NAME="Alameda", YEAR="2023", APN="A", DEM_DES_UNITS="N", NO_ENTITLEMENTS="")
        b = row(JURIS_NAME="T", CNTY_NAME="Alameda", YEAR="2023", APN="B", DEM_DES_UNITS="2")
        out, removed = cleaner._deduplicate_apr(frame_of([a, b]))
        self.assertEqual(removed, 0)
        self.assertEqual(list(out["DEM_DES_UNITS"]), ["N", "2"])
        self.assertEqual(out["NO_ENTITLEMENTS"].iloc[0], "")

    def test_blank_and_zero_still_collapse(self):
        a = row(JURIS_NAME="T", CNTY_NAME="Alameda", YEAR="2023", APN="A", NO_ENTITLEMENTS="")
        b = row(JURIS_NAME="T", CNTY_NAME="Alameda", YEAR="2023", APN="A", NO_ENTITLEMENTS="0")
        out, removed = cleaner._deduplicate_apr(frame_of([a, b]))
        self.assertEqual(removed, 1)
        self.assertEqual(out["NO_ENTITLEMENTS"].iloc[0], "")


class DedupKeyTests(unittest.TestCase):
    BASE = dict(JURIS_NAME="T", CNTY_NAME="Alameda", YEAR="2023", APN="A", STREET_ADDRESS="1 X", PROJECT_NAME="P",
                JURS_TRACKING_ID="T1", UNIT_CAT="SFD", TENURE="Owner")

    def pair(self, a, b):
        return frame_of([row(**{**self.BASE, **a}), row(**{**self.BASE, **b})])

    def test_distinct_permits_kept(self):
        for a, b in [(dict(JURS_TRACKING_ID="PMT-3201619"), dict(JURS_TRACKING_ID="PMT-3201620")),
                     (dict(UNIT_CAT="SFD"), dict(UNIT_CAT="ADU")),
                     (dict(TENURE="Owner"), dict(TENURE="Renter"))]:
            with self.subTest(a=a, b=b):
                out, removed = cleaner._deduplicate_apr(self.pair(a, b))
                self.assertEqual(removed, 0)
                self.assertEqual(len(out), 2)

    def test_blank_id_exact_copy_removed(self):
        out, removed = cleaner._deduplicate_apr(self.pair(dict(JURS_TRACKING_ID=""), dict(JURS_TRACKING_ID="T1")))
        self.assertEqual(removed, 1)
        self.assertEqual(len(out), 1)
        self.assertEqual(out["JURS_TRACKING_ID"].iloc[0], "T1")

    def test_blank_id_differing_row_kept(self):
        out, removed = cleaner._deduplicate_apr(
            self.pair(dict(JURS_TRACKING_ID="", BP_ISSUE_DT1="2023-01-01"), dict(JURS_TRACKING_ID="T1")))
        self.assertEqual(removed, 0)
        self.assertEqual(len(out), 2)

    def test_pairs_reported(self):
        pairs = []
        out, removed = cleaner._deduplicate_apr(
            self.pair(dict(CO_ISSUE_DT1="2023-01-01"), dict(CO_ISSUE_DT1="2023-02-02")), pairs_out=pairs)
        self.assertEqual(removed, 1)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["differing_columns"], "CO_ISSUE_DT1")
        self.assertIs(pairs[0]["income_tier_differs"], False)

    def test_pairs_name_their_kind(self):
        pairs = []
        cleaner._deduplicate_apr(
            self.pair(dict(CO_ISSUE_DT1="2023-01-01"), dict(CO_ISSUE_DT1="2023-02-02")), pairs_out=pairs)
        self.assertEqual([p["kind"] for p in pairs], ["key_duplicate"])

    def test_blank_id_removal_listed(self):
        pairs = []
        out, removed = cleaner._deduplicate_apr(
            self.pair(dict(JURS_TRACKING_ID=""), dict(JURS_TRACKING_ID="T1")), pairs_out=pairs)
        self.assertEqual(removed, 1)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["kind"], "blank_id_copy")
        self.assertEqual(pairs[0]["differing_columns"], "JURS_TRACKING_ID")
        self.assertEqual(json.loads(pairs[0]["removed_values"]), {"JURS_TRACKING_ID": ""})
        self.assertEqual(json.loads(pairs[0]["kept_values"]), {"JURS_TRACKING_ID": "T1"})
        self.assertIs(pairs[0]["income_tier_differs"], False)

    def test_na_like_id_collapses_like_blank(self):
        for token in ("N/A", "n/a", "NA", "None", "null"):
            with self.subTest(token=token):
                pairs = []
                out, removed = cleaner._deduplicate_apr(
                    self.pair(dict(JURS_TRACKING_ID=token), dict(JURS_TRACKING_ID="T1")), pairs_out=pairs)
                self.assertEqual(removed, 1)
                self.assertEqual(list(out["JURS_TRACKING_ID"]), ["T1"])
                self.assertEqual([p["kind"] for p in pairs], ["blank_id_copy"])
                self.assertEqual(json.loads(pairs[0]["removed_values"]), {"JURS_TRACKING_ID": token})

    def test_na_like_id_row_differing_elsewhere_kept(self):
        out, removed = cleaner._deduplicate_apr(
            self.pair(dict(JURS_TRACKING_ID="N/A", BP_ISSUE_DT1="2023-01-01"), dict(JURS_TRACKING_ID="T1")))
        self.assertEqual((removed, len(out)), (0, 2))

    def test_missing_values_shown_blank_not_nul(self):
        removed_missing = self.pair(dict(NOTES="kept note"), dict(NOTES=None))
        removed_missing["DENSITY_BONUS_TOTAL"] = pd.array([3, pd.NA], dtype="Int64")
        kept_missing = self.pair(dict(NOTES=None), dict(NOTES="removed note"))
        for frame, want_removed, want_kept in [
                (removed_missing, {"NOTES": "", "DENSITY_BONUS_TOTAL": ""}, {"NOTES": "kept note", "DENSITY_BONUS_TOTAL": "3"}),
                (kept_missing, {"NOTES": "removed note"}, {"NOTES": ""})]:
            pairs = []
            cleaner._deduplicate_apr(frame, pairs_out=pairs)
            self.assertEqual(len(pairs), 1)
            self.assertEqual(json.loads(pairs[0]["removed_values"]), want_removed)
            self.assertEqual(json.loads(pairs[0]["kept_values"]), want_kept)
            for text in (pairs[0]["removed_values"], pairs[0]["kept_values"]):
                self.assertNotIn("\\u0000", text)
                self.assertNotIn("\x00", text)

    def test_identical_pair_not_reported(self):
        pairs = []
        out, removed = cleaner._deduplicate_apr(self.pair({}, {}), pairs_out=pairs)
        self.assertEqual(removed, 1)
        self.assertEqual(pairs, [])


def raw_line(**over):
    """A 52-field raw line, joined with bare commas (values are written as given)."""
    return ",".join(row(**over))


class HostCloserTests(unittest.TestCase):
    HEADER_LINE = ",".join(HEADER)

    def host_text(self):
        host = ("HOSTJ,Cnty,2023" + "," * 39
                + r',"Used HCD Affordability Calculator to determine affordability level\\"",""'
                + ',0,0,0,0,0,"","",""')
        nextj = 'NEXTJ""",Cnty,2023,,P2,A2,,T2,SFD,Owner'
        thirdj = "THIRDJ,Cnty,2023" + "," * 49
        return "\n".join([self.HEADER_LINE, host, nextj, thirdj]) + "\n"

    def test_host_and_truncated_separate(self):
        result = cleaner._repair_quote_corruption(self.host_text())
        records = list(csv.reader(io.StringIO(result[0])))[1:]
        self.assertEqual([len(r) for r in records], [52, 10, 52])
        host = records[0]
        self.assertEqual(host[HEADER.index("NO_FA_DR")],
                         'Used HCD Affordability Calculator to determine affordability level"')
        self.assertEqual(host[HEADER.index("TERM_AFF_DR"):HEADER.index("NOTES") + 1],
                         ['', '0', '0', '0', '0', '0', '', '', ''])
        self.assertEqual(records[1][0], "NEXTJ")
        self.assertEqual(result[4], 1)

    def test_no_closer_no_change(self):
        text = "\n".join([self.HEADER_LINE,
                          "HOSTJ,Cnty,2023" + "," * 39 + r',"text\\"",""' + ",0" * 8,
                          raw_line(JURIS_NAME="OTHER", CNTY_NAME="Alameda", YEAR="2023")]) + "\n"
        result = cleaner._repair_quote_corruption(text)
        self.assertEqual(result[0], text)
        self.assertEqual(result[4], 0)

    def test_opener_followed_by_space_unchanged(self):
        text = self.HEADER_LINE + "\n" + 'A,B,' + r'"\\"" x' + ",C\n"
        result = cleaner._repair_quote_corruption(text)
        self.assertEqual(result[0], text)
        self.assertEqual(result[1], 0)

    def test_opener_quote_by_column(self):
        opener = r'"\\""'
        text = "\n".join([
            self.HEADER_LINE,
            raw_line(JURIS_NAME="TOWN", CNTY_NAME="Alameda", YEAR="2023", NO_FA_DR=opener),
            raw_line(JURIS_NAME="TOWN", CNTY_NAME="Alameda", YEAR="2023", PRIOR_APN=opener)]) + "\n"
        result = cleaner._repair_quote_corruption(text)
        df, rejects, reconstructed, counts = cleaner._load_repaired_records(result[0], result[5])
        self.assertEqual(df["NO_FA_DR"].iloc[0], '"')
        self.assertTrue(pd.isna(df["PRIOR_APN"].iloc[1]))
        self.assertEqual(counts["opener_quote_cells_kept"], 1)
        self.assertEqual(counts["opener_quote_cells_emptied"], 1)


def cell(df, i, col):
    """A cell as text, '' for a missing value."""
    v = df[col].iloc[i]
    return "" if pd.isna(v) else str(v)


as_text = lambda f: f.astype(object).where(f.notna(), "").astype(str)

_RAW_LINES = []


def raw_file_line(n):
    """Raw line n (1-based) of tablea2.csv."""
    if not _RAW_LINES:
        _RAW_LINES.extend(RAW_PATH.read_text(encoding="utf-8", errors="replace").splitlines())
    return _RAW_LINES[n - 1]


def load(text, openers=frozenset()):
    return cleaner._load_repaired_records(text, set(openers))


HEADER_LINE = ",".join(HEADER)


class OverwideTests(unittest.TestCase):
    def test_null_excess_trimmed_other_reported(self):
        base = dict(JURIS_NAME="TOWN", CNTY_NAME="Alameda", YEAR="2023", UNIT_CAT="SFD", TENURE="Owner")
        x = row(APN='016709102"""', **base) + ["NULL"]
        y = row(APN="P2", **base) + ["X"]
        metrics = []
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            root = Path(directory)
            (root / "tablea2.csv").write_text(to_text([x, y]), encoding="utf-8")
            stack.enter_context(patch.object(cleaner, "_print_summary_block", side_effect=lambda rows: metrics.extend(rows)))
            with contextlib.redirect_stdout(io.StringIO()):
                cleaner.run_repair(root, root)
            cleaned = pd.read_csv(root / "tablea2_cleaned_parsefilter_repair.csv", dtype=str)
            overwide = pd.read_csv(root / "overwide_rows_parsefilter_repair.csv", dtype=str)
            reconstructed = pd.read_csv(root / "reconstructed_rows_parsefilter_repair.csv", dtype=str)
        self.assertEqual(list(cleaned["APN"]), ["016709102"])
        self.assertEqual(len(overwide), 1)
        self.assertEqual(overwide["source_line"].iloc[0], "3")
        counters = dict(metrics)
        self.assertEqual(counters["overwide_rows_trimmed"], 1)
        self.assertEqual(counters["overwide_rows_unrepaired"], 1)
        trims = reconstructed[reconstructed["repair"] == "overwide_trim"]
        self.assertEqual(len(trims), 1)
        self.assertEqual(trims["columns_rebuilt"].iloc[0], "APN")


class ContinuationTests(unittest.TestCase):
    PARENT = dict(JURIS_NAME="TOWN", CNTY_NAME="Alameda", YEAR="2023", NOTES="first part")

    def test_notes_fold(self):
        df, _, _, counts = load(to_text([row(**self.PARENT), ["second", 'part"'] + ["NULL"] * 50]))
        self.assertEqual(len(df), 1)
        self.assertEqual(cell(df, 0, "NOTES"), "first part\nsecond,part")
        self.assertEqual(counts["fold_terminator_quotes_stripped"], 1)

    def test_split_rejoin(self):
        parent = ["TOWN", "San Diego", "2018", "", "P", "A", "GENESIS"] + ["NULL"] * 45
        tail = (['MILLENIA"', "T9", "2 to 4", "Owner"] + ["0"] * 7 + ["", "0"] + ["0"] * 7 + ["2018-03-27", "3"]
                + ["0"] * 7 + ["2019-01-25", "3"] + ["0"] * 15 + ["NULL"] * 6)
        df, _, _, counts = load(to_text([parent, tail]))
        self.assertEqual(len(df), 1)
        self.assertEqual(cell(df, 0, "PROJECT_NAME"), 'GENESIS\nMILLENIA"')
        self.assertEqual(cell(df, 0, "JURS_TRACKING_ID"), "T9")
        self.assertEqual(cell(df, 0, "UNIT_CAT"), "2 to 4")
        self.assertEqual(cell(df, 0, "TENURE"), "Owner")
        self.assertEqual(cell(df, 0, "BP_ISSUE_DT1"), "2018-03-27")

    def test_guard_blocks_across_other_record(self):
        df, _, _, counts = load(to_text([row(**self.PARENT), ["OTHERJ"], ["second", 'part"'] + ["NULL"] * 50]))
        self.assertEqual(counts["continuation_rows_unresolved"], 1)
        self.assertEqual(counts["notes_continuation_rows"], 0)
        self.assertEqual(cell(df, 0, "NOTES"), "first part")

    def test_no_parent(self):
        df, _, _, counts = load(to_text([["second", 'part"'] + ["NULL"] * 50, row(**self.PARENT)]))
        self.assertEqual(counts["continuation_rows_unresolved"], 1)
        self.assertEqual(len(df), 2)


class SonomaMemoTests(unittest.TestCase):
    MEMO = ('Applied ABAG methodology from Technical Memo \\Using ADUs to Satisfy RHNA\\\\" of 30% VL')

    def memo_row(self, **over):
        return row(JURIS_NAME="SONOMA COUNTY", CNTY_NAME="Sonoma", YEAR="2023", UNIT_CAT="ADU", TENURE="Renter",
                   NO_FA_DR=self.MEMO, TERM_AFF_DR="30% Low", DEM_DES_UNITS="30% Mod", DEM_OR_DES_UNITS='10% AM."',
                   DEM_DES_UNITS_OWN_RENT="", DENSITY_BONUS_TOTAL="1", DENSITY_BONUS_NUMBER_OTHER_INCENTIVES="0",
                   DENSITY_BONUS_INCENTIVES="0", DENSITY_BONUS_RECEIVE_REDUCTION="0", NOTES="0", **over)

    def test_realign(self):
        df, _, _, counts = load(to_text([self.memo_row()]))
        self.assertEqual(cell(df, 0, "NO_FA_DR"),
                         'Applied ABAG methodology from Technical Memo \\Using ADUs to Satisfy RHNA\\\\" of 30% VL,30% Low,30% Mod,10% AM.')
        self.assertEqual([cell(df, 0, c) for c in ("TERM_AFF_DR", "DEM_DES_UNITS", "DEM_OR_DES_UNITS",
                                                    "DEM_DES_UNITS_OWN_RENT", "DENSITY_BONUS_TOTAL",
                                                    "DENSITY_BONUS_NUMBER_OTHER_INCENTIVES")],
                         ["", "1", "0", "0", "0", "0"])
        self.assertEqual([cell(df, 0, c) for c in ("DENSITY_BONUS_INCENTIVES", "DENSITY_BONUS_RECEIVE_REDUCTION", "NOTES")],
                         ["", "", ""])
        self.assertEqual(counts["sonoma_memo_rows_realigned"], 1)


def valid_layout_row(**over):
    base = dict(JURIS_NAME="TOWN", CNTY_NAME="Alameda", YEAR="2023", UNIT_CAT="SFD", TENURE="Owner")
    base.update(over)
    return row(**base)


class ShiftedRowTests(unittest.TestCase):
    def real(self, n):
        df, _, _, counts = load(HEADER_LINE + "\n" + raw_file_line(n) + "\n")
        self.assertEqual(len(df), 1)
        self.assertEqual(df.shape[1], W)
        return df, counts

    def test_merge(self):
        df, counts = self.real(357383)
        self.assertEqual(cell(df, 0, "PROJECT_NAME"), 'NEW SFR AT \\TRELLIS\\\\" [LOT 3,BLDG 7,PLAN 2-A] UNIT 7')
        self.assertEqual(cell(df, 0, "JURS_TRACKING_ID"), "B161664")
        self.assertEqual(cell(df, 0, "UNIT_CAT"), "SFD")
        self.assertEqual(cell(df, 0, "TENURE"), "Owner")
        self.assertEqual([cell(df, 0, c) for c in HEADER[-2:]], ["", ""])
        self.assertEqual(counts["shifted_rows_realigned_merge"], 1)

    def test_merge_next(self):
        df, counts = self.real(136226)
        self.assertEqual(cell(df, 0, "PROJECT_NAME"), 'BLDG 1:  PLAN TYPE \\ B \\\\" 2,256 SF.  4  BEDROOMS')
        self.assertEqual(cell(df, 0, "JURS_TRACKING_ID"), "BLDG22-2630")
        self.assertEqual(cell(df, 0, "UNIT_CAT"), "SFD")
        self.assertEqual(cell(df, 0, "TENURE"), "Owner")
        self.assertEqual(cell(df, 0, "ENT_APPROVE_DT1"), "2022-12-21")
        self.assertEqual(cell(df, 0, "NO_ENTITLEMENTS"), "1")
        self.assertEqual(counts["shifted_rows_realigned_merge_next"], 1)

    def test_unmerge_project(self):
        df, counts = self.real(623464)
        self.assertEqual(cell(df, 0, "PROJECT_NAME"), "NATOMAS MEADOWS-ALLEY LOAD")
        self.assertEqual(cell(df, 0, "JURS_TRACKING_ID"), "RES-1824393")
        self.assertEqual(df.shape[1], 52)
        self.assertEqual(counts["shifted_rows_realigned_unmerge"], 1)

    def test_unmerge_tracking(self):
        df, counts = self.real(788105)
        self.assertEqual(cell(df, 0, "JURS_TRACKING_ID"), "ADU-01832-2020")
        self.assertEqual(cell(df, 0, "UNIT_CAT"), "ADU")
        self.assertEqual(counts["shifted_rows_realigned_unmerge"], 1)

    def test_ambiguous_left(self):
        intended = valid_layout_row(
            STREET_ADDRESS='1 \\A\\\\" ST', PROJECT_NAME='X \\B\\\\" Y"', JURS_TRACKING_ID="T1",
            **{c: "0" for c in cleaner._layout_count_cols(HEADER)})
        first, last = HEADER.index("JURS_TRACKING_ID"), HEADER.index("DENSITY_BONUS_RECEIVE_REDUCTION")
        shifted = list(intended)
        shifted[first + 1:last + 2] = intended[first:last + 1]
        shifted[first] = 'Z"'
        stage = cleaner._RecordStage(HEADER)
        valid = {tuple(new) for _, new, _ in cleaner._shift_candidates(shifted, stage) if stage.layout_valid(new)}
        self.assertEqual(len(valid), 2)
        df, _, _, counts = load(to_text([shifted]))
        self.assertEqual(counts["shifted_rows_unresolved"], 1)
        self.assertEqual(cell(df, 0, "PROJECT_NAME"), shifted[HEADER.index("PROJECT_NAME")])
        self.assertEqual(cell(df, 0, "JURS_TRACKING_ID"), 'Z"')
        self.assertEqual(cell(df, 0, "UNIT_CAT"), "T1")

    def test_valid_and_sonoma_non_memo_unchanged(self):
        sonoma = row(JURIS_NAME="SONOMA COUNTY", CNTY_NAME="Sonoma", YEAR="2023", UNIT_CAT="ADU", TENURE="Renter",
                     NO_FA_DR="Some other text", TERM_AFF_DR="30% Low", DEM_DES_UNITS="30% Mod", DEM_OR_DES_UNITS="x")
        rows = [valid_layout_row(APN="A", NOTES="n"), sonoma]
        df, _, _, counts = load(to_text(rows))
        self.assertEqual(counts["shifted_rows_unresolved"], 0)
        self.assertEqual(counts["sonoma_memo_rows_realigned"], 0)
        self.assertEqual(cell(df, 1, "NO_FA_DR"), "Some other text")
        self.assertEqual(cell(df, 1, "DEM_OR_DES_UNITS"), "x")


class WorkbookDateTests(unittest.TestCase):
    """Workbook phase dates are copied into recovered rows, so the date rule judges them too."""
    DATES = {"A2_5_Date": "2023-04-05 00:00:00", "A2_8_Date": "2023-06-07 00:00:00",
             "A2_10_Date": "2023-08-09 00:00:00"}

    def test_mapping_copies_dates_as_iso_text(self):
        mapped = cleaner.map_a2_row_to_apr_record(a2_candidate("ADU", "R", 5, **self.DATES), line_identity())
        self.assertEqual([mapped[c] for c in ("ENT_APPROVE_DT1", "BP_ISSUE_DT1", "CO_ISSUE_DT1")],
                         ["2023-04-05", "2023-06-07", "2023-08-09"])

    def test_blank_or_unparseable_workbook_date_is_not_mapped(self):
        row = a2_candidate("ADU", "R", 5, A2_5_Date="", A2_8_Date="5", A2_10_Date="Date Issued")
        mapped = cleaner.map_a2_row_to_apr_record(row, line_identity())
        self.assertFalse({"ENT_APPROVE_DT1", "BP_ISSUE_DT1", "CO_ISSUE_DT1"} & set(mapped))

    def update(self, existing, **a2_dates):
        cols = [*cleaner.IDENTITY_KEY_COLS, "UNIT_CAT", "TENURE", "ENT_APPROVE_DT1", "BP_ISSUE_DT1", "CO_ISSUE_DT1"]
        base = line_identity()
        df = pd.DataFrame([[base[c] for c in cleaner.IDENTITY_KEY_COLS] + ["ADU", "Renter"] + existing], columns=cols)
        found = {"candidates": [a2_candidate("ADU", "R", 5, **a2_dates)], "match_stage_used": "apn_only",
                 "excel_row_numbers": [5]}
        with patch.object(cleaner, "_resolve_workbook_path", return_value=Path("Town2024.xlsm")), \
                patch.object(cleaner, "_load_a2_rows_with_indexes", return_value={}), \
                patch.object(cleaner, "_find_a2_matches", return_value=found):
            result = cleaner._process_truncated_identity(
                line_identity(), {}, {}, df, cleaner._build_identity_index(df))
        return df, result[0]

    def test_update_fills_blank_keeps_equal_and_reports_different(self):
        df, counters = self.update(["", "2023-06-07", "2022-01-01"], **self.DATES)
        self.assertEqual(list(df.loc[0, ["ENT_APPROVE_DT1", "BP_ISSUE_DT1", "CO_ISSUE_DT1"]]),
                         ["2023-04-05", "2023-06-07", "2023-08-09"])
        self.assertEqual(counters["upsert_dates_filled"], 1)
        self.assertEqual(counters["upsert_dates_differing"], 1)

    def test_blank_workbook_date_keeps_csv_date(self):
        df, counters = self.update(["2020-02-02", "", ""], A2_5_Date="")
        self.assertEqual(df.at[0, "ENT_APPROVE_DT1"], "2020-02-02")
        self.assertEqual((counters["upsert_dates_filled"], counters["upsert_dates_differing"]), (0, 0))


class TextSplitTests(unittest.TestCase):
    """A text column split at a comma pushes its tail one cell right; siblings fix the layout."""
    FRAG1 = 'ABAG Paper \\Affordability\\\\" (September 8'

    def split_row(self, **over):
        return valid_layout_row(NO_FA_DR=self.FRAG1, TERM_AFF_DR='2021)"', DEM_DES_UNITS="", DEM_OR_DES_UNITS="0",
                                DEM_DES_UNITS_OWN_RENT="0", DENSITY_BONUS_TOTAL="0",
                                DENSITY_BONUS_NUMBER_OTHER_INCENTIVES="0", DENSITY_BONUS_INCENTIVES="0",
                                DENSITY_BONUS_RECEIVE_REDUCTION="", NOTES="", **over)

    def test_split_note_realigned_and_listed(self):
        df, _, recon, counts = load(to_text([self.split_row()]))
        self.assertEqual(cell(df, 0, "NO_FA_DR"), self.FRAG1 + ",2021)")
        self.assertEqual([cell(df, 0, c) for c in ("TERM_AFF_DR", "DEM_DES_UNITS", "DEM_OR_DES_UNITS",
                                                    "DEM_DES_UNITS_OWN_RENT", "DENSITY_BONUS_TOTAL",
                                                    "DENSITY_BONUS_NUMBER_OTHER_INCENTIVES",
                                                    "DENSITY_BONUS_INCENTIVES", "DENSITY_BONUS_RECEIVE_REDUCTION",
                                                    "NOTES")],
                         ["", "0", "0", "0", "0", "0", "", "", ""])
        self.assertEqual(counts["shifted_rows_realigned_merge_text"], 1)
        (rec,) = recon
        self.assertEqual(rec["repair"], "shifted_merge_text")
        self.assertEqual(rec["columns_lost"], "NOTES")
        # Hand-derived: the tail moves left one cell, so only cells whose left neighbour differs change.
        self.assertEqual(rec["columns_rebuilt"], "NO_FA_DR|TERM_AFF_DR|DEM_DES_UNITS|DENSITY_BONUS_INCENTIVES")

    def test_unsettled_row_left_and_counted(self):
        row = self.split_row()
        row[HEADER.index("DEM_DES_UNITS")] = "free text"
        df, _, recon, counts = load(to_text([row]))
        self.assertEqual(cell(df, 0, "TERM_AFF_DR"), '2021)"')
        self.assertEqual(counts["text_split_rows_unresolved"], 1)
        self.assertEqual(recon, [])

    def assert_left_and_counted(self, row, expected_term):
        df, _, recon, counts = load(to_text([row]))
        self.assertEqual(cell(df, 0, "TERM_AFF_DR"), expected_term)
        self.assertEqual((counts["text_split_rows_unresolved"], counts["shifted_rows_realigned_merge_text"]), (1, 0))
        self.assertEqual(recon, [])

    def test_fragment_without_closing_quote_left(self):
        """Without the closing quote there is nothing to drop; joining would cut a real character."""
        row = self.split_row()
        row[HEADER.index("TERM_AFF_DR")] = "2021)"
        self.assert_left_and_counted(row, "2021)")

    def test_blank_first_piece_left(self):
        """A split note has a first piece; a blank NO_FA_DR would join to ',2021)'."""
        row = self.split_row()
        row[HEADER.index("NO_FA_DR")] = ""
        self.assert_left_and_counted(row, '2021)"')

    def test_non_numeric_demolition_count_left(self):
        """The cell that would become DEM_DES_UNITS is text: the siblings' layout is not matched."""
        row = self.split_row()
        row[HEADER.index("DEM_OR_DES_UNITS")] = "Demolished"
        self.assert_left_and_counted(row, '2021)"')

    def test_legitimate_term_values_untouched(self):
        rows = [valid_layout_row(APN=str(i), NO_FA_DR="text", TERM_AFF_DR=v, DEM_DES_UNITS="0")
                for i, v in enumerate(["N/A", "1,000", "55", "", "n/a"])]
        df, _, recon, counts = load(to_text(rows))
        self.assertEqual([cell(df, i, "TERM_AFF_DR") for i in range(5)], ["N/A", "1,000", "55", "", "n/a"])
        self.assertEqual((counts["shifted_rows_realigned_merge_text"], counts["text_split_rows_unresolved"]), (0, 0))

    def test_real_napa_and_danville_lines(self):
        df, _, _, counts = load(HEADER_LINE + "\n" + raw_file_line(4658) + "\n")
        self.assertTrue(cell(df, 0, "NO_FA_DR").endswith("(September 8,2021)"))
        self.assertEqual((cell(df, 0, "TERM_AFF_DR"), cell(df, 0, "DEM_DES_UNITS"), cell(df, 0, "DEM_OR_DES_UNITS")),
                         ("", "0", "0"))
        df, _, _, counts = load(HEADER_LINE + "\n" + raw_file_line(121889) + "\n")
        self.assertTrue(cell(df, 0, "NO_FA_DR").endswith("in the range of 851 sf to 1,200 sf."))
        self.assertEqual(cell(df, 0, "TERM_AFF_DR"), "")


class LoadEquivalenceTests(unittest.TestCase):
    def test_same_text_without_triggers(self):
        rows = [
            valid_layout_row(APN="A1", PROJECT_NAME="multi\nline, quoted", NO_ENTITLEMENTS="3",
                             ENT_APPROVE_DT1="2023-04-05", NOTES="NULL", VLOW_INCOME_DR="NULL"),
            valid_layout_row(APN="A2", BP_ISSUE_DT1="2023-01-02", NO_BUILDING_PERMITS="1", DEM_DES_UNITS="0"),
            ["TOWN", "Alameda", "2023", "", "SHORT"],
        ]
        text = to_text(rows)
        got = as_text(load(text)[0])
        want = as_text(pd.read_csv(io.StringIO(text), dtype=str, on_bad_lines="skip"))
        pd.testing.assert_frame_equal(got, want)


MERGE_357383_CHANGED = [
    "PROJECT_NAME", "JURS_TRACKING_ID", "UNIT_CAT", "TENURE", "VLOW_INCOME_DR", "VLOW_INCOME_NDR",
    "ENT_APPROVE_DT1", "BP_VLOW_INCOME_DR", "BP_ISSUE_DT1", "CO_VLOW_INCOME_DR", "CO_ABOVE_MOD_INCOME",
    "CO_ISSUE_DT1", "EXTR_LOW_INCOME_UNITS", "APPROVE_SB35", "INFILL_UNITS", "FIN_ASSIST_NAME", "DR_TYPE",
    "NO_FA_DR", "DEM_OR_DES_UNITS", "DENSITY_BONUS_INCENTIVES", "DENSITY_BONUS_RECEIVE_REDUCTION"]
# Raw line 464036 (SANTA CLARA 2022) swallows five cells into the quoted project text; the repair
# moves every later cell left by six. Columns APN..NOTES whose cell differs before/after (derived
# by comparing the csv-parsed line with the loaded row, NULL = blank).
_CHANGED_464036_APN_TO_NOTES = {
    "APN", "STREET_ADDRESS", "PROJECT_NAME", "JURS_TRACKING_ID", "UNIT_CAT", "TENURE", "VLOW_INCOME_DR",
    "VLOW_INCOME_NDR", "LOW_INCOME_DR", "LOW_INCOME_NDR", "MOD_INCOME_DR", "MOD_INCOME_NDR",
    "ENT_APPROVE_DT1", "BP_MOD_INCOME_DR", "BP_ISSUE_DT1", "CO_MOD_INCOME_DR", "CO_ABOVE_MOD_INCOME",
    "CO_ISSUE_DT1", "NO_OTHER_FORMS_OF_READINESS", "APPROVE_SB35", "FIN_ASSIST_NAME", "DR_TYPE", "NO_FA_DR",
    "TERM_AFF_DR", "DEM_DES_UNITS", "DENSITY_BONUS_TOTAL", "DENSITY_BONUS_NUMBER_OTHER_INCENTIVES",
    "DENSITY_BONUS_INCENTIVES", "DENSITY_BONUS_RECEIVE_REDUCTION", "NOTES"}


class ReconstructedDiagnosticTests(unittest.TestCase):
    def test_every_rebuilt_row_listed(self):
        opener = r'"\\""'
        lines = [HEADER_LINE,
                 raw_file_line(357383), raw_file_line(136226), raw_file_line(623464),
                 ",".join(row(JURIS_NAME="TOWN", CNTY_NAME="Alameda", YEAR="2023", UNIT_CAT="SFD", TENURE="Owner",
                              PRIOR_APN=opener))]
        text = "\n".join(lines) + "\n"
        split_parent = ["TOWN", "San Diego", "2018", "", "P", "A", "GENESIS"] + ["NULL"] * 45
        split_tail = (['MILLENIA"', "T9", "2 to 4", "Owner"] + ["0"] * 7 + ["", "0"] + ["0"] * 7 + ["2018-03-27", "3"]
                      + ["0"] * 7 + ["2019-01-25", "3"] + ["0"] * 15 + ["NULL"] * 6)
        text += to_text([SonomaMemoTests().memo_row(), split_parent, split_tail,
                         row(JURIS_NAME="TOWN", CNTY_NAME="Alameda", YEAR="2023", UNIT_CAT="SFD", TENURE="Owner",
                             APN='016709102"""') + ["NULL"],
                         row(JURIS_NAME="TOWN", CNTY_NAME="Alameda", YEAR="2023", UNIT_CAT="SFD", TENURE="Owner",
                             NOTES="first part"),
                         ["second", 'part"'] + ["NULL"] * 50]).split("\n", 1)[1]
        fixed, _, _, _, _, openers = cleaner._repair_quote_corruption(text)
        df, rejects, reconstructed, counts = cleaner._load_repaired_records(fixed, openers)
        recon = pd.DataFrame(reconstructed)
        kinds = sorted(recon["repair"])
        self.assertEqual(kinds, ["notes_fold", "opener_quote_emptied", "overwide_trim", "shifted_merge",
                                 "shifted_merge_next", "shifted_unmerge", "sonoma_memo", "split_rejoin"])
        by = recon.set_index("repair")
        self.assertEqual(by.loc["overwide_trim", "columns_rebuilt"], "APN")
        self.assertEqual(by.loc["notes_fold", "columns_rebuilt"], "NOTES")
        self.assertEqual(by.loc["sonoma_memo", "columns_lost"],
                         "DENSITY_BONUS_INCENTIVES|DENSITY_BONUS_RECEIVE_REDUCTION|NOTES")
        # Each list is the cell diff of the record before/after its repair, derived by comparing the
        # csv-parsed raw line with the loaded row (NULL token = blank); sonoma by hand from memo_row().
        self.assertEqual(by.loc["shifted_merge", "columns_rebuilt"], "|".join(MERGE_357383_CHANGED))
        self.assertEqual(by.loc["shifted_merge", "columns_lost"], "DENSITY_BONUS_RECEIVE_REDUCTION|NOTES")
        self.assertEqual(by.loc["sonoma_memo", "columns_rebuilt"],
                         "NO_FA_DR|TERM_AFF_DR|DEM_DES_UNITS|DEM_OR_DES_UNITS|DEM_DES_UNITS_OWN_RENT|"
                         "DENSITY_BONUS_TOTAL|DENSITY_BONUS_INCENTIVES|DENSITY_BONUS_RECEIVE_REDUCTION|NOTES")
        self.assertEqual(by.loc["split_rejoin", "columns_rebuilt"].split("|"),
                         [c for c in HEADER[6:] if c != "ENT_APPROVE_DT1"])

    def test_rebuilt_columns_are_the_cell_diff(self):
        """Shifted rows move every later cell; the list names each column that changed, APN to NOTES."""
        self.assertEqual(self.rebuilt_of(357383), MERGE_357383_CHANGED)
        got = self.rebuilt_of(464036)
        want = [c for c in HEADER[HEADER.index("APN"):] if c in _CHANGED_464036_APN_TO_NOTES]
        self.assertEqual([c for c in got if HEADER.index(c) >= HEADER.index("APN")], want)
        self.assertGreater(len(want), 20)
        self.assertEqual(got[0], "PRIOR_APN")

    def rebuilt_of(self, n):
        text = HEADER_LINE + "\n" + raw_file_line(n) + "\n"
        _, _, reconstructed, _ = load(text)
        (rec,) = reconstructed
        return rec["columns_rebuilt"].split("|")


def line_identity(**kwargs):
    base = dict(zip(cleaner.IDENTITY_KEY_COLS, ["Town", "County", "2024", "P1", "1 Main St", "ID1"]))
    base.update(UNIT_CAT="ADU", TENURE="Renter")
    base.update(kwargs)
    return base


def a2_candidate(unit, tenure, excel_row, **extra):
    return {"A2_1_ID": "ID1", "A2_1_Current": "P1", "A2_1_Address": "1 Main St", "A2_2_Unit": unit,
            "A2_3_Tenure": tenure, "__excel_row_number": excel_row, **extra}


class LineFieldNarrowingTests(unittest.TestCase):
    COLS = [*cleaner.IDENTITY_KEY_COLS, "UNIT_CAT", "TENURE"]

    def process(self, candidates, df_rows):
        df = pd.DataFrame(df_rows, columns=self.COLS)
        found = {"candidates": candidates, "match_stage_used": "tracking_id",
                 "excel_row_numbers": [c["__excel_row_number"] for c in candidates]}
        with patch.object(cleaner, "_resolve_workbook_path", return_value=Path("Town2024.xlsm")), \
                patch.object(cleaner, "_load_a2_rows_with_indexes", return_value={}), \
                patch.object(cleaner, "_find_a2_matches", return_value=found):
            result = cleaner._process_truncated_identity(
                line_identity(), {}, {}, df, cleaner._build_identity_index(df))
        return df, result

    def test_unit_tenure_pick_one(self):
        row_in_df = line_identity()
        row_in_df.update(UNIT_CAT="adu", TENURE="renter")
        df, result = self.process([a2_candidate("SFD", "O", 390), a2_candidate("ADU", "R", 420)],
                                  [[row_in_df[c] for c in self.COLS]])
        self.assertEqual(result[0]["upsert_update"], 1)
        self.assertEqual(df.at[0, "UNIT_CAT"], "ADU")

    def test_identities_split_by_unit_tenure(self):
        rows = pd.DataFrame([line_identity(UNIT_CAT="SFD", TENURE="Owner"), line_identity()])
        self.assertEqual(len(cleaner._dedupe_truncated_identities(rows)), 2)

    def test_indistinguishable_unchanged(self):
        candidates = [a2_candidate("ADU", "R", 390, A2_21_Notes="a"), a2_candidate("ADU", "R", 420, A2_21_Notes="b")]
        df, result = self.process(candidates, [[line_identity()[c] for c in self.COLS]])
        self.assertEqual(result[0]["upsert_ambiguous"], 1)
        self.assertEqual(result[1][0]["ambiguity_stage"], "xlsm_multi_match")


class DtypeTests(unittest.TestCase):
    def test_year_int_matches_string_line(self):
        base = line_identity()
        df = pd.DataFrame([[base[c] for c in cleaner.IDENTITY_KEY_COLS]] * 2, columns=cleaner.IDENTITY_KEY_COLS)
        df["YEAR"] = pd.array([2023, pd.NA], dtype="Int64")
        matches = cleaner._identity_matches(cleaner._build_identity_index(df), line_identity(YEAR="2023", UNIT_CAT="", TENURE=""))
        self.assertEqual(list(matches), [0])

    def test_update_keeps_int64(self):
        df = pd.DataFrame({"YEAR": pd.array([2020, pd.NA], dtype="Int64"),
                           "NO_BUILDING_PERMITS": pd.array([0, 1], dtype="Int64")})
        cleaner._apply_mapped_to_df_row(df, 0, {"YEAR": "2023", "NO_BUILDING_PERMITS": "2"})
        self.assertEqual([str(df[c].dtype) for c in df.columns], ["Int64", "Int64"])
        self.assertEqual([df.at[0, "YEAR"], df.at[0, "NO_BUILDING_PERMITS"]], [2023, 2])


class VocabularyTests(unittest.TestCase):
    def test_years_match_maps(self):
        sys.path.insert(0, str(REPO))
        try:
            from maps import build_maps
        finally:
            sys.path.remove(str(REPO))
        self.assertEqual(set(cleaner.VALID_YEARS), set(range(build_maps.YEARS[0], build_maps.YEARS[1] + 1)))


class IdentityPreservedTests(unittest.TestCase):
    """A workbook update/append never rewrites identity columns with normalized (upper-cased) values."""
    COLS = LineFieldNarrowingTests.COLS

    def process(self, df_rows, candidates, line):
        df = pd.DataFrame(df_rows, columns=self.COLS)
        identity = cleaner._dedupe_truncated_identities(pd.DataFrame([line])).iloc[0]
        found = {"candidates": candidates, "match_stage_used": "apn_only",
                 "excel_row_numbers": [c["__excel_row_number"] for c in candidates]}
        with patch.object(cleaner, "_resolve_workbook_path", return_value=Path("Irvine2024.xlsm")), \
                patch.object(cleaner, "_load_a2_rows_with_indexes", return_value={}), \
                patch.object(cleaner, "_find_a2_matches", return_value=found):
            result = cleaner._process_truncated_identity(
                identity, {}, {}, df, cleaner._build_identity_index(df))
        return df, result

    LINE = dict(zip(cleaner.IDENTITY_KEY_COLS, ["Irvine", "Orange", "2024", "p-1", "1 Main St", "id1"]),
                UNIT_CAT="ADU", TENURE="Renter")

    def test_identities_keep_source_case(self):
        identities = cleaner._dedupe_truncated_identities(pd.DataFrame([self.LINE]))
        self.assertEqual(identities.iloc[0]["CNTY_NAME"], "Orange")
        self.assertEqual(identities.iloc[0]["JURIS_NAME"], "Irvine")

    def test_update_keeps_existing_identity_values(self):
        existing = {**self.LINE, "APN": "p-1", "STREET_ADDRESS": "1 main St", "JURS_TRACKING_ID": "id1"}
        candidate = a2_candidate("ADU", "R", 390, A2_1_Current="P-1", A2_1_Address="1 MAIN ST", A2_1_ID="ID1")
        df, result = self.process([[existing[c] for c in self.COLS]], [candidate], self.LINE)
        self.assertEqual(result[0]["upsert_update"], 1)
        for col in cleaner.IDENTITY_KEY_COLS:
            self.assertEqual(df.at[0, col], existing[col], col)
        self.assertEqual(df.at[0, "CNTY_NAME"], "Orange")

    def test_append_uses_source_line_identity(self):
        candidate = a2_candidate("ADU", "R", 390, A2_1_Current="WB-APN", A2_1_Address="WB ADDR", A2_1_ID="WB-ID")
        df, result = self.process([], [candidate], self.LINE)
        self.assertEqual(result[0]["upsert_append"], 1)
        accepted, withheld = cleaner._screen_pending_appends(df[cleaner.IDENTITY_KEY_COLS].copy(), df, [result[2]])
        self.assertEqual(withheld, [])
        for col in cleaner.IDENTITY_KEY_COLS:
            self.assertEqual(accepted[0][col], self.LINE[col], col)


class LiteralTokenTests(unittest.TestCase):
    """Text loads without default NA parsing: only blank (and the export's NULL marker) is missing."""

    def test_na_like_tokens_survive(self):
        r = valid_layout_row(APN="N/A", PROJECT_NAME="N/A", STREET_ADDRESS="n/a", JURS_TRACKING_ID="NA",
                             NOTES="None", FIN_ASSIST_NAME="null", DR_TYPE="NULL")
        df = load(to_text([r]))[0]
        self.assertEqual([cell(df, 0, c) for c in ("APN", "PROJECT_NAME", "STREET_ADDRESS", "JURS_TRACKING_ID",
                                                    "NOTES", "FIN_ASSIST_NAME")],
                         ["N/A", "N/A", "n/a", "NA", "None", "null"])
        self.assertTrue(pd.isna(df["DR_TYPE"].iloc[0]))
        self.assertTrue(pd.isna(df["PRIOR_APN"].iloc[0]))

    def test_whole_number_column_with_token_stays_text(self):
        rows = [valid_layout_row(APN="a", NO_ENTITLEMENTS="N/A", NO_BUILDING_PERMITS="3"),
                valid_layout_row(APN="b", NO_ENTITLEMENTS="2", NO_BUILDING_PERMITS="4")]
        df = load(to_text(rows))[0]
        self.assertEqual([cell(df, i, "NO_ENTITLEMENTS") for i in (0, 1)], ["N/A", "2"])
        self.assertEqual(str(df["NO_ENTITLEMENTS"].dtype), "object")
        self.assertEqual(str(df["NO_BUILDING_PERMITS"].dtype), "Int64")


class LoneQuoteTests(unittest.TestCase):
    def test_kept_opener_cells_survive_others_cleared(self):
        df = pd.DataFrame({"NO_FA_DR": ['"', '"', "x"], "NOTES": ['"', "", ""], "FIN_ASSIST_NAME": ["", '"', ""]})
        fixed = cleaner._lone_quote_cleanup(df, keep=pd.Index([0]))
        self.assertEqual(list(df["NO_FA_DR"]), ['"', "", "x"])
        self.assertEqual(list(df["NOTES"]), ["", "", ""])
        self.assertEqual(list(df["FIN_ASSIST_NAME"]), ["", "", ""])
        self.assertEqual(fixed, 3)

    def test_default_clears_every_lone_quote(self):
        df = pd.DataFrame({"NO_FA_DR": ['"', "x"], "NOTES": ["y", "z"], "FIN_ASSIST_NAME": ["", ""]})
        self.assertEqual(cleaner._lone_quote_cleanup(df), 1)
        self.assertEqual(list(df["NO_FA_DR"]), ["", "x"])

    def test_loader_reports_kept_opener_rows(self):
        opener = r'"\\""'
        text = "\n".join([
            HEADER_LINE,
            raw_line(JURIS_NAME="TOWN", CNTY_NAME="Alameda", YEAR="2023", PRIOR_APN="p"),
            raw_line(JURIS_NAME="TOWN", CNTY_NAME="Alameda", YEAR="2023", NO_FA_DR=opener),
            raw_line(JURIS_NAME="TOWN", CNTY_NAME="Alameda", YEAR="2023", NOTES=opener)]) + "\n"
        result = cleaner._repair_quote_corruption(text)
        df = cleaner._load_repaired_records(result[0], result[5])[0]
        self.assertEqual(list(df.attrs["opener_quote_kept_rows"]), [1])


STAGE_TIER_TOTALS = (("", "NO_ENTITLEMENTS"), ("BP_", "NO_BUILDING_PERMITS"), ("CO_", "NO_OTHER_FORMS_OF_READINESS"))
INCOME_TIERS = ("VLOW_INCOME_DR", "VLOW_INCOME_NDR", "LOW_INCOME_DR", "LOW_INCOME_NDR", "MOD_INCOME_DR",
                "MOD_INCOME_NDR", "ABOVE_MOD_INCOME")
REALIGNING_REPAIRS = ("sonoma_memo", "split_rejoin", "notes_fold")


def tier_sum_violations(header, fields):
    """Stages (ENT, BP, CO) whose 7 income-tier cells do not sum to the stage total (blank/NULL = 0)."""
    ix = {c: i for i, c in enumerate(header)}
    count = lambda v: 0 if v in ("", "NULL") else int(v) if re.fullmatch(r"-?\d+", v) else None
    bad = []
    for prefix, total in STAGE_TIER_TOTALS:
        tiers = [count(fields[ix[prefix + t]]) for t in INCOME_TIERS]
        stage_total = count(fields[ix[total]])
        if None in tiers or stage_total is None or sum(tiers) != stage_total:
            bad.append(total)
    return bad


class TierSumGateTests(unittest.TestCase):
    def good_row(self):
        return valid_layout_row(VLOW_INCOME_DR="1", LOW_INCOME_NDR="2", NO_ENTITLEMENTS="3",
                                BP_ABOVE_MOD_INCOME="4", NO_BUILDING_PERMITS="4")

    def test_aligned_row_passes(self):
        self.assertEqual(tier_sum_violations(HEADER, self.good_row()), [])

    def test_row_misaligned_by_one_column_is_flagged(self):
        good = self.good_row()
        first = HEADER.index("VLOW_INCOME_DR")
        shifted = good[:first] + [""] + good[first:-1]
        # One cell right: ENT/BP/CO tiers each pick up a neighbouring stage's cell and the totals
        # read the cell before them (hand-derived: all three stages break).
        self.assertEqual(tier_sum_violations(HEADER, shifted),
                         ["NO_ENTITLEMENTS", "NO_BUILDING_PERMITS", "NO_OTHER_FORMS_OF_READINESS"])


class MissingIdentifierTests(unittest.TestCase):
    """N/A-like APN / tracking id is missing information: compared as blank, text kept."""

    def test_identity_key_treats_token_as_blank(self):
        for col in ("APN", "JURS_TRACKING_ID"):
            for token in ("N/A", "n/a", "NA", "None", "null", ""):
                with self.subTest(col=col, token=token):
                    self.assertEqual(cleaner._identity_key(line_identity(**{col: token})),
                                     cleaner._identity_key(line_identity(**{col: ""})))
        self.assertNotEqual(cleaner._identity_key(line_identity(APN="N/A")),
                            cleaner._identity_key(line_identity(APN="P2")))
        self.assertEqual(cleaner._identity_key(line_identity(STREET_ADDRESS="N/A"))[4], "N/A")

    def test_workbook_lookup_ignores_token_ids(self):
        row = {"A2_1_ID": "N/A", "A2_1_Current": "n/a", "A2_1_Address": "1 Main St", "__excel_row_number": 5}
        idx = {"id_map": {}, "pair_map": {("", "1 MAIN ST"): [row]}, "apn_map": {}}
        found = cleaner._find_a2_matches(idx, line_identity(JURS_TRACKING_ID="n/a", APN="N/A"))
        self.assertEqual(found["match_stage_used"], "apn_address_pair")
        self.assertEqual(found["candidates"], [row])

    def test_workbook_index_keys_token_as_blank(self):
        with patch.object(cleaner.pd, "read_excel", return_value=pd.DataFrame(
                [["A2_1_ID", "A2_18_Affordable", "A2_1_Current", "A2_1_Address"],
                 ["N/A", "x", "NA", "1 Main St"]])):
            idx = cleaner._load_a2_rows_with_indexes("w.xlsm", {})
        self.assertEqual(idx["id_map"], {})
        self.assertEqual(list(idx["pair_map"]), [("", "1 MAIN ST")])


class WholeNumberTokenTests(unittest.TestCase):
    def test_int64_value_definition(self):
        na = object()
        cases = [("", na), ("  ", na), ("3", 3), (" 3 ", 3), ("3.0", 3), ("-2", -2), (5, 5),
                 ("None", None), ("nan", None), ("N/A", None), ("NA", None), ("NULL", None), ("null", None),
                 ("1_000", None), ("\u0661\u0662\u0663", None), ("3.5", None), ("Infinity", None)]
        for value, want in cases:
            with self.subTest(value=value):
                got = cleaner._int64_value(value)
                if want is na:
                    self.assertTrue(got is pd.NA)
                else:
                    self.assertEqual(got, want)
                    self.assertIs(got is None, want is None)

    def test_int64_range(self):
        lo, hi = -2**63, 2**63 - 1
        for text, want in [(str(hi), hi), (str(lo), lo), (str(hi + 1), None), (str(lo - 1), None),
                           ("99999999999999999999", None), ("1e30", None), ("9.3e18", None), ("1e3", 1000)]:
            with self.subTest(text=text):
                self.assertEqual(cleaner._int64_value(text), want)

    def test_oversized_count_degrades_column_instead_of_raising(self):
        df = pd.DataFrame({"NO_BUILDING_PERMITS": pd.array([1, 2], dtype="Int64")})
        cleaner._apply_mapped_to_df_row(df, 0, {"NO_BUILDING_PERMITS": "99999999999999999999"})
        self.assertEqual(str(df["NO_BUILDING_PERMITS"].dtype), "object")
        self.assertEqual(df.at[0, "NO_BUILDING_PERMITS"], "99999999999999999999")

    def test_update_with_literal_token_degrades_column_and_keeps_text(self):
        for token in ("N/A", "None", "NULL"):
            with self.subTest(token=token):
                df = pd.DataFrame({"NO_BUILDING_PERMITS": pd.array([1, 2], dtype="Int64")})
                cleaner._apply_mapped_to_df_row(df, 0, {"NO_BUILDING_PERMITS": token})
                self.assertEqual(str(df["NO_BUILDING_PERMITS"].dtype), "object")
                self.assertEqual(df.at[0, "NO_BUILDING_PERMITS"], token)

    def test_one_definition_of_missing(self):
        for token in ["N/A", "N-A", "n.a.", "NA", "None", "null", "NULL", " N / A "]:
            with self.subTest(token=token):
                self.assertEqual(cleaner._norm_id(token), "")
                tokens = cleaner._append_identity_tokens(line_identity(APN=token))[1]
                self.assertEqual({t for t in tokens if t[0] == "APN"}, set())
        for real in ["NA-1", "N1", "0397-161-52", "NONE-7"]:
            with self.subTest(real=real):
                self.assertNotEqual(cleaner._norm_id(real), "")


class WorkbookLiteralTextTests(unittest.TestCase):
    """The workbook reader, like the CSV load, treats only a blank cell as missing."""

    def load_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Town2023.xlsx"
            pd.DataFrame([["A2_1_ID", "A2_18_Affordable", "A2_1_Current", "A2_1_Address", "A2_1_Name", "A2_21_Notes"],
                          ["N/A", "n/a", "NA", "1 Main St", "N/A", "None"],
                          ["T9", "", "P9", "2 Main St", "", ""]]).to_excel(
                path, sheet_name="Table A2", header=False, index=False)
            return cleaner._load_a2_rows_with_indexes(path, {})

    def test_literal_tokens_reach_the_mapped_record(self):
        idx = self.load_fixture()
        first = idx["rows"][0]
        self.assertEqual([first[c] for c in ("A2_1_ID", "A2_18_Affordable", "A2_1_Current", "A2_1_Name", "A2_21_Notes")],
                         ["N/A", "n/a", "NA", "N/A", "None"])
        mapped = cleaner.map_a2_row_to_apr_record(first, line_identity())
        self.assertEqual((mapped["PROJECT_NAME"], mapped["NO_FA_DR"], mapped["NOTES"], mapped["APN"],
                          mapped["JURS_TRACKING_ID"]), ("N/A", "n/a", "None", "NA", "N/A"))

    def test_blank_cell_still_blank(self):
        second = self.load_fixture()["rows"][1]
        self.assertEqual((second["A2_18_Affordable"], second["A2_1_Name"]), ("", ""))

    def test_index_keys_read_tokens_as_missing_identifiers(self):
        idx = self.load_fixture()
        self.assertEqual(sorted(idx["id_map"]), ["T9"])
        self.assertEqual(sorted(idx["apn_map"]), ["P9"])
        self.assertEqual(sorted(idx["pair_map"]), [("", "1 MAIN ST"), ("P9", "2 MAIN ST")])


class HelperTests(unittest.TestCase):
    def test_finite_integral_predicate(self):
        from decimal import Decimal
        cases = {"3": True, "3.0": True, "-2": True, "0": True, "3.5": False, "NaN": False,
                 "Infinity": False, "-Infinity": False}
        for text, want in cases.items():
            self.assertIs(cleaner._is_finite_integral(Decimal(text)), want, text)


class DriftTests(unittest.TestCase):
    def test_counties_match_reference_geojson(self):
        geo = json.loads((REPO / "maps/reference/jurisdictions.geojson").read_text(encoding="utf-8"))
        whole = {re.sub(r"\s+COUNTY$", "", f["properties"]["county_name"]).strip()
                 for f in geo["features"] if f["properties"]["geo_type"] == "county_whole"}
        self.assertEqual({c.upper() for c in cleaner.CA_COUNTIES}, whole)

    def test_chart_unit_categories_match_template_spec(self):
        spec = json.loads((REPO / "data-cleanup/template_spec.json").read_text(encoding="utf-8"))
        (rule,) = [r for r in spec["rules"] if r["apr_column"] == "UNIT_CAT" and r["type"] == "list"]
        sys.path.insert(0, str(REPO / "charts"))
        try:
            import basic_apr_charts
        finally:
            sys.path.remove(str(REPO / "charts"))
        codes = basic_apr_charts.UNIT_CAT_CODES_TOP_TO_BOTTOM
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(set(codes), set(rule["formula1"].strip('"').split(",")))


def record_starts(text):
    """Start line of every csv record: the previous record's `reader.line_num` + 1."""
    reader = csv.reader(io.StringIO(text))
    starts, previous = [], 0
    for _ in reader:
        starts.append(previous + 1)
        previous = reader.line_num
    return starts


class RealFileTests(unittest.TestCase):
    def test_record_starts(self):
        raw = RAW_PATH.read_text(encoding="utf-8", errors="replace")
        fixed, _, _, closer_lines, host_closer_repairs, _ = cleaner._repair_quote_corruption(raw)
        self.assertEqual(set(record_starts(fixed)), set(record_starts(raw)) | closer_lines)
        self.assertEqual(host_closer_repairs, 72)


    def test_pipeline_outcomes(self):
        """One scratch run of the real file; each gate names one failure a reader of the counts would hit."""
        run = real_run()
        m, cleaned = run["metrics"], run["cleaned"]
        # G2 upsert outcomes: workbook repairs lost or duplicated. Re-measured 2026-11-19 after literal
        # N/A text stopped being blanked at load: (73, 0, 6, 1, 2, 5, 6) -> (79, 0, 0, 1, 2, 5, 0). The six
        # Hesperia truncated lines whose APN or tracking id is literally "N/A" now match their existing
        # rows (was blank, so unmatched, so six withheld "possible_existing_duplicate" appends).
        self.assertEqual(
            tuple(m[k] for k in ("truncated_identities_resolved_update", "truncated_identities_resolved_append",
                                 "append_candidates_withheld", "truncated_identities_resolved_paired",
                                 "truncated_rows_updated_via_pairing", "truncated_identities_unresolved",
                                 "truncated_identities_ambiguous")),
            (79, 0, 0, 1, 2, 5, 0))
        # G3: distinct permits merged, or copies double-counted
        self.assertEqual(m["dedup_rows_removed"], 6194)
        # G4: records dropped at load
        self.assertEqual(m["overwide_rows_unrepaired"], 0)
        # G5: counts read from shifted columns. Every row a realignment step touched has its three
        # stages' income tiers summing to the stage total.
        checked = [(repair, rec["start"], tier_sum_violations(header, rec["fields"]))
                   for header, rec, repair in run["touched"]
                   if repair in REALIGNING_REPAIRS or repair.startswith("shifted_")]
        self.assertGreater(len(checked), 0)
        self.assertEqual([c for c in checked if c[2]], [])
        # G6: Sonoma text in count columns
        self.assertEqual(m["sonoma_memo_rows_realigned"], 441)
        # G8: a split note left in TERM_AFF_DR (fragment like `2021)"`); nothing left unsettled
        fragments = cleaned["TERM_AFF_DR"][~cleaned["TERM_AFF_DR"].str.fullmatch(r"[\d,]*")
                                           & ~cleaned["TERM_AFF_DR"].str.upper().isin(["N/A", "NA", "NONE", "NULL"])]
        self.assertEqual(list(fragments), [])
        self.assertEqual(m["text_split_rows_unresolved"], 0)
        self.assertEqual(m["shifted_rows_realigned_merge_text"], TEXT_SPLIT_ROWS)
        # G7: "2020.0" published
        dotted = sum(int(cleaned[c].str.endswith(".0").sum()) for c in run["int64_cols"])
        self.assertEqual(dotted, 0)

    def test_county_spelled_one_way(self):
        counties = real_run()["cleaned"]["CNTY_NAME"]
        self.assertEqual(counties.nunique(), counties.str.upper().nunique())
        irvine = real_run()["cleaned"].query("JURIS_NAME == 'IRVINE'")
        self.assertGreater(len(irvine), 0)
        self.assertEqual(set(irvine["CNTY_NAME"]), {"Orange"})

    def test_phase_basis_never_rests_on_na_like_id(self):
        phase = real_run()["phase"]
        weak = phase["JURS_TRACKING_ID"].str.strip().str.upper().isin(["N/A", "NA", "NONE", "NULL"])
        self.assertGreater(len(phase), 0)
        self.assertEqual(int((weak & phase["identity_basis"].str.split(";").map(lambda b: "tracking_id" in b)).sum()), 0)

    def test_literal_na_text_published(self):
        cleaned = real_run()["cleaned"]
        self.assertGreater(int((cleaned == "N/A").sum().sum()), 0)

    def test_pairs_file_has_no_nul_and_lists_blank_id_removals(self):
        run = real_run()
        self.assertNotIn("\\u0000", run["pairs_text"])
        self.assertNotIn("\x00", run["pairs_text"])
        blank = run["pairs"][run["pairs"]["kind"] == "blank_id_copy"]
        self.assertEqual(len(blank), 5)
        self.assertEqual(blank["JURIS_NAME"].value_counts().to_dict(), {"FONTANA": 4, "CUDAHY": 1})
        self.assertEqual(set(run["pairs"]["kind"]), {"key_duplicate", "blank_id_copy"})

    def test_opener_quotes_kept_in_no_fa_dr(self):
        run = real_run()
        self.assertEqual(run["metrics"]["opener_quote_cells_kept"], 15)
        self.assertEqual(run["metrics"]["opener_quote_cells_kept_after_cleanup"], 15)
        kept_in_output = int((run["cleaned"]["NO_FA_DR"] == '"').sum())
        self.assertGreater(kept_in_output, 0)
        self.assertLessEqual(kept_in_output, 15)
        for col in ("NOTES", "FIN_ASSIST_NAME"):
            self.assertEqual(int((run["cleaned"][col] == '"').sum()), 0)


# Rows whose TERM_AFF_DR held a fragment of a split note at load (Napa County 89, Danville 19, Marin
# County 4, Ukiah 2). 109 of them (85/18/4/2) reached the earlier cleaned file; the other 5 (4 Napa,
# 1 Danville) are dropped by the date and dedup filters, so the loader's count is 114.
TEXT_SPLIT_ROWS = 114

_REAL_RUN = {}


def real_run():
    """One scratch run of the real file, shared by every real-file gate."""
    if _REAL_RUN:
        return _REAL_RUN
    metrics, int64_cols, touched = [], [], []
    real_load = cleaner._load_repaired_records
    real_note = cleaner._RecordStage.note

    def observe_load(text, openers):
        result = real_load(text, openers)
        int64_cols.extend(c for c in result[0].columns if result[0][c].dtype == "Int64")
        return result

    def observe_note(self, rec, repair, *args, **kwargs):
        touched.append((self.header, rec, repair))
        return real_note(self, rec, repair, *args, **kwargs)

    with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
        out = Path(directory)
        stack.enter_context(patch.object(cleaner, "_print_summary_block", side_effect=lambda r: metrics.extend(r)))
        stack.enter_context(patch.object(cleaner, "_load_repaired_records", side_effect=observe_load))
        stack.enter_context(patch.object(cleaner._RecordStage, "note", observe_note))
        with contextlib.redirect_stdout(io.StringIO()):
            cleaner.run_repair(REPO, out)
        read = lambda name: pd.read_csv(out / name, dtype=str, keep_default_na=False, low_memory=False)
        _REAL_RUN.update(
            metrics=dict(metrics), int64_cols=int64_cols, touched=touched,
            cleaned=read("tablea2_cleaned_parsefilter_repair.csv"),
            pairs=read("dedup_collapsed_pairs_parsefilter_repair.csv"),
            phase=read("date_excluded_phase_comparison_parsefilter_repair.csv"),
            pairs_text=(out / "dedup_collapsed_pairs_parsefilter_repair.csv").read_text(encoding="utf-8"))
    return _REAL_RUN


if __name__ == "__main__":
    unittest.main()
