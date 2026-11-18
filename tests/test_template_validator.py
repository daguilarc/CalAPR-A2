"""Tests for data-cleanup/template_validator.py.

Spec fixtures are synthetic; the real-workbook smoke test skips when the
templates are absent. Run: python3 -m unittest -v
"""
import contextlib
import io
import json
import re
import tempfile
import unittest
import zipfile
from pathlib import Path
import importlib.util

import openpyxl
import pandas as pd
from openpyxl.worksheet.datavalidation import DataValidation
from unittest import mock

THIS_DIR = Path(__file__).resolve().parent
DATA = THIS_DIR.parent / "data-cleanup"
WORKBOOKS = sorted(p for p in DATA.glob("*.xlsm") if not p.name.startswith("~$"))  # skip Excel lock files

_spec = importlib.util.spec_from_file_location(
    "template_validator", DATA / "template_validator.py")
template_validator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(template_validator)
a2_header_to_apr_columns = template_validator.a2_header_to_apr_columns
build_canonical = template_validator.build_canonical
extract_spec = template_validator.extract_spec
validate_dataframe = template_validator.validate_dataframe
workbook_dataframe = template_validator.workbook_dataframe
known_custom_rule = template_validator.known_custom_rule

KNOWN_XLOW_FORMULA = template_validator.KNOWN_XLOW_CUSTOM_FORMULA

# Real header letters/names shared by every era's Table A2 (verified against
# the .xlsm templates); needed to exercise the a2_header -> APR mapping.
XLOW_HEADERS = {"AI": "A2_13_xLow", "H": "A2_4_vLowDeed", "I": "A2_4_vLowNone",
                "Q": "A2_7_vLowDeed", "R": "A2_7_vLowNone",
                "Z": "A2_10_vLowDeed", "AA": "A2_10_vLowNone"}


def canonical(*rules, years=(2024,), form_years=None):
    """Synthetic canonical rule set. years: reporting years whose forms carry
    every rule; form_years: reporting years that have a form at all (default
    = years)."""
    out = []
    for r in rules:
        entry = {"apr_column": r[0], "a2_headers": [r[0]], "type": r[1],
                 "formula1": str(r[2]), "formula2": r[3], "operator": r[4],
                 "interpreted_operator": r[5],
                 "templates": [f"T{y}.xlsm" for y in years],
                 "years": list(years)}
        out.append(entry)
    return {"workbooks": [{"workbook": f"T{y}.xlsm", "sha256": "x", "header_row": 6,
                           "reporting_year": y}
                          for y in (form_years or years)],
            "rules": out, "assumptions": {}}


def enforced_nonblank_cells(control, canonical):
    """Non-blank cells in the columns that carry an enforced rule: the number
    of cells a clean control run actually judged."""
    cols = {r["apr_column"] for r in canonical["rules"]} & set(control.columns)
    blank = template_validator.BLANK_SPELLINGS
    return int(sum(control[c].map(lambda v: pd.notna(v)
                                  and str(v).strip().lower() not in blank).sum()
                   for c in cols))


def frame(**cols):
    return pd.DataFrame({k: [str(v) for v in vs] for k, vs in cols.items()})


X14_NS = ('xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main" '
          'xmlns:xm="http://schemas.microsoft.com/office/excel/2006/main"')


def make_template(path, headers, main_rules=(), x14_rules=(), year=2020, cells=None):
    """Write a synthetic one-sheet template: header row 6, data rows 13..1000.
    main_rules: (type, formula1, formula2, sqref); x14_rules: same shape,
    injected into the sheet XML as x14 extension validations."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Table A2"
    for col, name in headers.items():
        ws[f"{col}6"] = name
    ws["A12"] = "Summary Row: Start Data Entry Below"
    ws["A1000"] = "x"
    for addr, value in (cells or {}).items():
        ws[addr] = value
    if year is not None:
        start = wb.create_sheet("Start Here")
        start["A5"] = "Reporting Calendar Year"
        start["B5"] = year
    for rtype, f1, f2, sqref in main_rules:
        ws.add_data_validation(DataValidation(
            type=rtype, formula1=f1, formula2=f2,
            operator="between" if f2 is not None else None, sqref=sqref))
    wb.save(path)
    if not x14_rules:
        return
    body = "".join(
        f'<x14:dataValidation type="{t}"'
        f'{" operator=\"between\"" if f2 is not None else ""} allowBlank="1">'
        f'<x14:formula1><xm:f>{f1}</xm:f></x14:formula1>'
        + (f'<x14:formula2><xm:f>{f2}</xm:f></x14:formula2>' if f2 is not None else "")
        + f'<xm:sqref>{sq}</xm:sqref></x14:dataValidation>'
        for t, f1, f2, sq in x14_rules)
    ext = (f'<extLst><ext uri="{{CCE6A557-97BC-4b89-ADB6-D9C93CAAB3DF}}" {X14_NS}>'
           f'<x14:dataValidations count="{len(x14_rules)}">{body}'
           f'</x14:dataValidations></ext></extLst>')
    tmp = Path(str(path) + ".tmp")
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":  # Table A2 is sheet 1
                data = data.decode().replace("</worksheet>", ext + "</worksheet>").encode()
            zout.writestr(item, data)
    tmp.replace(path)


BASE_HEADERS = {"A": "A2_1_ID", "B": "A2_18_Affordable", "C": "A2_2_Unit",
                "D": "A2_3_Tenure"}


class HeaderlessColumnTests(unittest.TestCase):
    """F1: a data-area rule on a column with no header must be listed."""
    REASON = "column has no header in this template"

    def test_main_rule_on_headerless_column_is_unenforced(self):
        path = Path(tempfile.mkdtemp()) / "T2020.xlsx"
        make_template(path, BASE_HEADERS, main_rules=[("whole", "0", "100", "E13:E1000")])
        spec = extract_spec(path)
        hits = [u for u in spec["unenforced"] if u["reason"] == self.REASON]
        self.assertEqual([(u["column"], u["source"], u["type"]) for u in hits],
                         [("E", "main", "whole")])
        self.assertEqual(spec["rules"], [])

    def test_x14_rule_on_headerless_column_is_unenforced(self):
        path = Path(tempfile.mkdtemp()) / "T2020.xlsx"
        make_template(path, BASE_HEADERS, x14_rules=[("whole", "0", "100", "E13:E1000")])
        spec = extract_spec(path)
        hits = [u for u in spec["unenforced"] if u["reason"] == self.REASON]
        self.assertEqual([(u["column"], u["source"], u["type"]) for u in hits],
                         [("E", "x14", "whole")])
        self.assertEqual(spec["rules"], [])


class ShadowingTests(unittest.TestCase):
    """F8: a later rule is shadowed only when earlier rules cover all of its
    data-area rows; a partial overlap keeps it enforced and flags it."""

    def _spec(self, rules):
        path = Path(tempfile.mkdtemp()) / "T2020.xlsx"
        make_template(path, BASE_HEADERS, main_rules=rules)
        return extract_spec(path)

    def test_partial_overlap_keeps_later_rule_and_flags_it(self):
        spec = self._spec([("whole", "0", "20", "C13:C100"),
                           ("whole", "0", "100", "C50:C200")])
        got = [(r["formula2"], r.get("partial_overlap", False)) for r in spec["rules"]]
        self.assertEqual(got, [("20", False), ("100", True)])
        self.assertEqual([u for u in spec["unenforced"] if "shadowed" in u["reason"]], [])

    def test_fully_covered_later_rule_is_shadowed(self):
        spec = self._spec([("whole", "0", "20", "C13:C100"),
                           ("whole", "0", "5", "C20:C30")])
        self.assertEqual([r["formula2"] for r in spec["rules"]], ["20"])
        self.assertEqual([u["formula2"] for u in spec["unenforced"]
                          if "shadowed" in u["reason"]], ["5"])

    def test_coverage_by_union_of_earlier_rules_is_shadowed(self):
        spec = self._spec([("whole", "0", "1", "D13:D50"),
                           ("whole", "0", "2", "D51:D100"),
                           ("whole", "0", "3", "D13:D100")])
        self.assertEqual([r["formula2"] for r in spec["rules"]], ["1", "2"])
        self.assertEqual([u["formula2"] for u in spec["unenforced"]
                          if "shadowed" in u["reason"]], ["3"])


class ListRuleTests(unittest.TestCase):
    RULE = canonical(("UNIT_CAT", "list", '"SFA,SFD,2 to 4,5+,ADU,MH"', None, None, "in"))

    def test_allowed_value_passes(self):
        df = frame(UNIT_CAT=["SFD", "5+", "ADU"])
        self.assertEqual(validate_dataframe(df, self.RULE), [])

    def test_unknown_value_is_a_violation(self):
        df = frame(UNIT_CAT=["SFH"])  # plausible-looking, not on the list
        v = validate_dataframe(df, self.RULE)
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0]["column"], "UNIT_CAT")

    def test_blank_is_never_a_violation(self):
        df = frame(UNIT_CAT=["", "nan"])
        self.assertEqual(validate_dataframe(df, self.RULE), [])

    def test_joined_value_fails_a_single_select_list(self):
        df = frame(UNIT_CAT=["SFD, ADU"])
        self.assertEqual(len(validate_dataframe(df, self.RULE)), 1)


class MultiSelectListTests(unittest.TestCase):
    RULE = canonical(("DR_TYPE", "list", '"DB,INC,Other"', None, None, "in"))
    RULE["rules"][0]["multi_select"] = True

    def test_each_allowed_item_passes(self):
        df = frame(DR_TYPE=["DB", "DB, INC", "INC, Other, DB"])
        self.assertEqual(validate_dataframe(df, self.RULE), [])

    def test_one_unknown_item_fails(self):
        df = frame(DR_TYPE=["DB, Bonus"])
        self.assertEqual([x["value"] for x in validate_dataframe(df, self.RULE)],
                         ["DB, Bonus"])

    def test_semicolon_joined_picks_pass(self):
        # The published CSV joins picks with ";" (the template macro uses ", ").
        df = frame(DR_TYPE=["DB;INC", "DB; INC", "INC;Other;DB"])
        self.assertEqual(validate_dataframe(df, self.RULE), [])

    def test_semicolon_joined_unknown_item_fails(self):
        df = frame(DR_TYPE=["DB;Bonus", "DB;INC, Bonus"])
        self.assertEqual([x["value"] for x in validate_dataframe(df, self.RULE)],
                         ["DB;Bonus", "DB;INC, Bonus"])


class WholeRuleTests(unittest.TestCase):
    def test_below_bound_fails_equal_passes(self):
        rule = canonical(("VLOW_INCOME_DR", "whole", "0", None, None, ">="))
        df = frame(VLOW_INCOME_DR=["-1", "0", "12"])
        self.assertEqual([x["value"] for x in validate_dataframe(df, rule)], ["-1"])

    def test_negative_bound_allows_corrections(self):
        rule = canonical(("ENT_NET", "whole", "-1000", None, None, ">="))
        df = frame(ENT_NET=["-999", "-1001"])
        self.assertEqual([x["value"] for x in validate_dataframe(df, rule)], ["-1001"])

    def test_non_integer_fails_whole(self):
        rule = canonical(("VLOW_INCOME_DR", "whole", "0", None, None, ">="))
        df = frame(VLOW_INCOME_DR=["2.5"])
        self.assertEqual(len(validate_dataframe(df, rule)), 1)

    def test_between_operator(self):
        rule = canonical(("TERM_AFF_DR", "whole", "1", "99", None, "between"))
        df = frame(TERM_AFF_DR=["1", "50", "99", "100", "0"])
        self.assertEqual([x["value"] for x in validate_dataframe(df, rule)], ["100", "0"])


class DateRuleTests(unittest.TestCase):
    RULE = canonical(("ENT_DATE", "date", "18264", None, None, ">="))  # >= 1950-01-01

    def test_before_bound_fails(self):
        df = frame(ENT_DATE=["1949-12-31"])
        self.assertEqual(len(validate_dataframe(df, self.RULE)), 1)

    def test_bound_day_passes(self):
        df = frame(ENT_DATE=["1950-01-01", "2023-06-15"])
        self.assertEqual(validate_dataframe(df, self.RULE), [])

    def test_unparseable_date_fails(self):
        df = frame(ENT_DATE=["soon"])
        self.assertEqual(len(validate_dataframe(df, self.RULE)), 1)

    def test_only_whitelisted_formats_parse(self):
        # Audit finding 1: format="mixed" accepted words and foreign layouts.
        ok = ["2023-06-15", "06/15/2023", "2023/06/15", "06/15/23"]
        bad = ["today", "now", "June 15 2023", "15.06.2023", "2023-06-15T10:00",
               "2023-06-15 00:00:00"]
        v = validate_dataframe(frame(ENT_DATE=ok + bad), self.RULE)
        self.assertEqual(sorted(x["value"] for x in v), sorted(bad))

class GoverningFormTests(unittest.TestCase):
    """Revision 5: a CSV row is judged only by rules of the form(s) whose
    reporting year equals the row's YEAR."""
    LIST = ("UNIT_CAT", "list", '"SFA,SFD"', None, None, "in")

    def test_only_the_rows_own_year_is_judged(self):
        # forms exist for 2021, 2023, 2024; only the 2023 form carries the rule.
        rule = canonical(self.LIST, years=(2023,), form_years=(2021, 2023, 2024))
        df = frame(YEAR=["2021", "2023", "2024"], UNIT_CAT=["MH", "MH", "MH"])
        self.assertEqual([x["row"] for x in validate_dataframe(df, rule)], [3])

    def test_year_without_a_form_is_not_checked(self):
        rule = canonical(self.LIST, years=(2023,), form_years=(2019, 2023))
        df = frame(YEAR=["2018", "", "soon"], UNIT_CAT=["MH", "MH", "MH"])
        self.assertEqual(validate_dataframe(df, rule), [])

    def test_unchecked_year_counts(self):
        rule = canonical(self.LIST, years=(2023,), form_years=(2019, 2023))
        df = frame(YEAR=["2018", "2018", "2023", "", "soon"], UNIT_CAT=["MH"] * 5)
        self.assertEqual(template_validator.unchecked_year_counts(df, rule),
                         {"2018": 2, "blank or unparseable": 2})

    def test_each_year_uses_its_own_form_rule(self):
        a = canonical(("UNIT_CAT", "list", '"SFA"', None, None, "in"), years=(2022,))
        b = canonical(("UNIT_CAT", "list", '"SFD"', None, None, "in"), years=(2024,))
        both = {**a, "workbooks": a["workbooks"] + b["workbooks"],
                "rules": a["rules"] + b["rules"]}
        df = frame(YEAR=["2022", "2022", "2024", "2024"],
                   UNIT_CAT=["SFA", "SFD", "SFA", "SFD"])
        self.assertEqual([x["row"] for x in validate_dataframe(df, both)], [3, 4])

    def test_no_year_column_with_several_forms_is_refused(self):
        rule = canonical(self.LIST, years=(2023,), form_years=(2023, 2024))
        with self.assertRaises(ValueError):
            validate_dataframe(frame(UNIT_CAT=["MH"]), rule)

    def test_no_year_column_with_one_form_applies_every_rule(self):
        rule = canonical(self.LIST, years=(2023,))
        self.assertEqual(len(validate_dataframe(frame(UNIT_CAT=["MH"]), rule)), 1)

    def test_same_year_forms_that_disagree_are_reported_not_picked(self):
        a = canonical(("UNIT_CAT", "list", '"SFA"', None, None, "in"), years=(2024,))
        b = canonical(("UNIT_CAT", "list", '"SFD"', None, None, "in"), years=(2024,))
        both = {**a, "rules": a["rules"] + b["rules"]}
        self.assertEqual(template_validator.form_disagreements(both),
                         [{"apr_column": "UNIT_CAT", "year": 2024, "rules": 2,
                           "forms_with_rule": 1, "forms": 1}])
        df = frame(YEAR=["2024"], UNIT_CAT=["SFA"])
        self.assertEqual(validate_dataframe(df, both), [])  # neither form picked

    def test_agreeing_forms_are_not_a_disagreement(self):
        a = canonical(self.LIST, years=(2023, 2024))
        self.assertEqual(template_validator.form_disagreements(a), [])

class MissingColumnTests(unittest.TestCase):
    def test_missing_column_is_skipped(self):
        rule = canonical(("UNIT_CAT", "list", '"SFA"', None, None, "in"))
        self.assertEqual(validate_dataframe(frame(OTHER=["x"]), rule), [])


class CanonicalTests(unittest.TestCase):
    def _specs(self):
        s2024 = {"workbook": "T2024.xlsm", "sha256": "x", "header_row": 6,
                 "reporting_year": 2024,
                 "extracted_at": "2026-11-16T00:00:00",
                 "unspecified_type_slots": 0,
                 "headers": {"F": "A2_2_Unit"},
                 "rules": [{"a2_header": "A2_2_Unit", "column": "F", "type": "list",
                            "formula1": '"SFA,SFD"', "formula2": None,
                            "operator": None, "source": "main"}]}
        s2019 = {**s2024, "workbook": "T2019.xlsm", "reporting_year": 2019,
                 "rules": [{**s2024["rules"][0],
                            "formula1": '"SFA,SFD,2 to 4,5+,ADU,MH"'}]}
        return s2024, s2019

    def test_merge_keeps_provenance_and_years(self):
        s2024, s2019 = self._specs()
        c = build_canonical([s2024, s2019])
        # Different formulas are different rules: both survive, each carrying
        # its own provenance and reporting years.
        self.assertEqual(len(c["rules"]), 2)
        by_formula = {r["formula1"]: r for r in c["rules"]}
        self.assertEqual(by_formula['"SFA,SFD"']["templates"], ["T2024.xlsm"])
        self.assertEqual(by_formula['"SFA,SFD"']["years"], [2024])
        self.assertEqual(by_formula['"SFA,SFD,2 to 4,5+,ADU,MH"']["years"], [2019])
        self.assertNotIn("min_year", c["rules"][0])
        self.assertEqual([w["reporting_year"] for w in c["workbooks"]], [2019, 2024])

    def test_years_come_from_the_spec_not_the_filename(self):
        s2024, _ = self._specs()
        s2024["reporting_year"] = 2019  # file says 2024, Start Here B5 says 2019
        self.assertEqual(build_canonical([s2024])["rules"][0]["years"], [2019])

    def test_equivalent_lists_in_different_spellings_merge_with_year_union(self):
        # Older forms store "Y,N", newer ones a JSON array: one rule, both years.
        s2024, s2019 = self._specs()
        s2024["rules"][0]["formula1"] = '["N","Y"]'
        s2019["rules"][0]["formula1"] = '"Y,N"'
        c = build_canonical([s2024, s2019])
        self.assertEqual(len(c["rules"]), 1)
        self.assertEqual(c["rules"][0]["years"], [2019, 2024])
        self.assertEqual(sorted(c["rules"][0]["templates"]), ["T2019.xlsm", "T2024.xlsm"])
        self.assertIn("assumptions", c)

    def test_mapping_derived_from_repair_script(self):
        m = a2_header_to_apr_columns({"A2_2_Unit", "A2_3_Tenure", "A2_1_Current"})
        self.assertEqual(m["A2_2_Unit"], "UNIT_CAT")
        self.assertEqual(m["A2_3_Tenure"], "TENURE")
        self.assertEqual(m["A2_1_Current"], "APN")

    def test_unsupported_operator_is_recorded_unenforced(self):
        # Audit finding 2: such rules vanished from both lists.
        s2024, _ = self._specs()
        s2024["rules"] = [{"a2_header": "A2_2_Unit", "column": "F",
                           "type": "whole", "formula1": "5", "formula2": None,
                           "operator": "notEqual", "source": "main"}]
        c = build_canonical([s2024])
        self.assertEqual(c["rules"], [])
        self.assertEqual([u["reason"] for u in c["unenforced"]],
                         ["operator 'notEqual' not supported"])

    def test_unmapped_column_is_recorded_unenforced(self):
        # A rule on a template column the APR CSV does not carry must be
        # visible as unenforced, not dropped silently.
        s2024, _ = self._specs()
        s2024["headers"]["O"] = "A2_99_NotInCsv"
        s2024["rules"] = [{"a2_header": "A2_99_NotInCsv", "column": "O",
                           "type": "date", "formula1": "18264", "formula2": None,
                           "operator": None, "source": "main"}]
        c = build_canonical([s2024])
        self.assertEqual(c["rules"], [])
        self.assertEqual([u["reason"] for u in c["unenforced"]],
                         ["template column not in the APR CSV mapping"])

    def test_spec_json_round_trip(self):
        s2024, _ = self._specs()
        text = json.dumps(build_canonical([s2024]))
        self.assertEqual(json.loads(text)["rules"], build_canonical([s2024])["rules"])


KNOWN_XLOW_FORMULA = template_validator.KNOWN_XLOW_CUSTOM_FORMULA

def custom_canonical(ref_pairs=(("CO_VLOW_INCOME_DR", "CO_VLOW_INCOME_NDR"),
                                ("BP_VLOW_INCOME_DR", "BP_VLOW_INCOME_NDR"),
                                ("VLOW_INCOME_DR", "VLOW_INCOME_NDR")),
                     years=(2024,), form_years=None):
    return {"workbooks": [{"workbook": f"T{y}.xlsm", "sha256": "x", "header_row": 6,
                           "reporting_year": y} for y in (form_years or years)],
            "rules": [{"apr_column": "EXTR_LOW_INCOME_UNITS",
                       "a2_headers": ["A2_13_xLow"], "type": "custom",
                       "formula1": KNOWN_XLOW_FORMULA, "formula2": None,
                       "operator": None, "interpreted_operator": "custom",
                       "custom": {"numeric": True,
                                  "reference_apr_columns": [list(p) for p in ref_pairs]},
                       "sources": ["main"], "templates": ["T2024.xlsm"],
                       "years": list(years)}],
            "assumptions": {}}


def xlow_frame(values=("999999999",)):
    n = len(values)
    return frame(EXTR_LOW_INCOME_UNITS=values,
                 CO_VLOW_INCOME_DR=["10"] * n, CO_VLOW_INCOME_NDR=["20"] * n,
                 BP_VLOW_INCOME_DR=["30"] * n, BP_VLOW_INCOME_NDR=["40"] * n,
                 VLOW_INCOME_DR=["50"] * n, VLOW_INCOME_NDR=["60"] * n)


class CustomRuleTests(unittest.TestCase):
    """The known 2023+ A2_13_xLow custom validation, enforced per row."""

    def test_value_exceeding_every_pair_sum_fails(self):
        v = validate_dataframe(xlow_frame(), custom_canonical())
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0]["column"], "EXTR_LOW_INCOME_UNITS")
        self.assertIn("custom", v[0]["reason"])

    def test_value_within_one_pair_sum_passes(self):
        # 90 <= CO sum (30)? no; <= BP sum (70)? no; <= VLOW sum (110)? yes
        # -> not greater than ALL three sums, so Excel's OR keeps it legal.
        v = validate_dataframe(xlow_frame(["90"]), custom_canonical())
        self.assertEqual(v, [])

    def test_blank_passes(self):
        v = validate_dataframe(xlow_frame(["", "nan"]), custom_canonical())
        self.assertEqual(v, [])

    def test_non_numeric_fails(self):
        v = validate_dataframe(xlow_frame(["N/A"]), custom_canonical())
        self.assertEqual(len(v), 1)
        self.assertIn("numeric", v[0]["reason"])

    def test_older_form_rows_not_held_to_2023_rule(self):
        rule = custom_canonical(years=(2023, 2024), form_years=(2021, 2023, 2024))
        df = xlow_frame(["999999999", "999999999"])
        df["YEAR"] = ["2021", "2024"]
        self.assertEqual([x["row"] for x in validate_dataframe(df, rule)], [3])

    def test_missing_reference_column_is_skipped(self):
        rule = custom_canonical(ref_pairs=(("NO_SUCH_COL_A", "NO_SUCH_COL_B"),))
        self.assertEqual(validate_dataframe(xlow_frame(), rule), [])


class CustomClassificationTests(unittest.TestCase):
    """Drift gate: the extracted formula must equal the known constant
    (whitespace-normalized) and its own cell addresses must resolve."""

    def test_known_formula_classifies_enforced(self):
        known = known_custom_rule(KNOWN_XLOW_FORMULA, XLOW_HEADERS, "AI")
        self.assertIsNotNone(known)
        self.assertEqual(known["target_header"], "A2_13_xLow")
        self.assertEqual(known["target_column"], "AI")
        self.assertTrue(known["numeric"])
        self.assertEqual(sorted(known["reference_pairs"]),
                         sorted([["A2_10_vLowDeed", "A2_10_vLowNone"],
                                 ["A2_7_vLowDeed", "A2_7_vLowNone"],
                                 ["A2_4_vLowDeed", "A2_4_vLowNone"]]))

    def test_perturbed_formula_is_drift_not_enforced(self):
        drifted = KNOWN_XLOW_FORMULA.replace("SUM(Z13:AA13)", "SUM(Z13:AB13)")
        self.assertIsNone(known_custom_rule(drifted, XLOW_HEADERS, "AI"))

    def test_whitespace_does_not_defeat_match(self):
        spaced = KNOWN_XLOW_FORMULA.replace("SUM(", "SUM( ").replace(",OR", ", OR")
        self.assertIsNotNone(known_custom_rule(spaced, XLOW_HEADERS, "AI"))

    def test_sqref_column_disagreeing_with_formula_is_drift(self):
        self.assertIsNone(known_custom_rule(KNOWN_XLOW_FORMULA, XLOW_HEADERS, "AJ"))


class CanonicalCustomTests(unittest.TestCase):
    def _spec(self):
        return {"workbook": "T2024.xlsm", "sha256": "x", "header_row": 6,
                "reporting_year": 2024, "extracted_at": "2026-11-16T00:00:00",
                "unspecified_type_slots": 0, "headers": dict(XLOW_HEADERS),
                "unenforced": [],
                "rules": [{"a2_header": "A2_13_xLow", "column": "AI",
                           "type": "custom", "formula1": KNOWN_XLOW_FORMULA,
                           "formula2": None, "operator": None, "source": "main",
                           "custom": {"target_header": "A2_13_xLow",
                                      "target_column": "AI", "numeric": True,
                                      "row_anchor": 13,
                                      "reference_pairs":
                                          [["A2_10_vLowDeed", "A2_10_vLowNone"],
                                           ["A2_7_vLowDeed", "A2_7_vLowNone"],
                                           ["A2_4_vLowDeed", "A2_4_vLowNone"]]}}]}

    def test_enforced_custom_rule_passes_through_to_canonical(self):
        c = build_canonical([self._spec()])
        customs = [r for r in c["rules"] if r["type"] == "custom"]
        self.assertEqual(len(customs), 1)
        rule = customs[0]
        self.assertEqual(rule["apr_column"], "EXTR_LOW_INCOME_UNITS")
        self.assertEqual(rule["interpreted_operator"], "custom")
        self.assertEqual(rule["years"], [2024])
        self.assertEqual(rule["custom"]["reference_apr_columns"],
                         [["CO_VLOW_INCOME_DR", "CO_VLOW_INCOME_NDR"],
                          ["BP_VLOW_INCOME_DR", "BP_VLOW_INCOME_NDR"],
                          ["VLOW_INCOME_DR", "VLOW_INCOME_NDR"]])

    def test_enforced_custom_leaves_unenforced_free_of_custom_entries(self):
        c = build_canonical([self._spec()])
        self.assertEqual([u for u in c["unenforced"]
                          if u.get("type") == "custom"], [])

    def test_unenforced_entries_not_duplicated(self):
        # Regression: build_canonical appended every spec unenforced entry twice.
        spec = self._spec()
        spec["unenforced"] = [{"a2_header": "A2_2_Unit", "column": "F",
                               "type": "list", "formula1": None,
                               "source": "main", "reason": "template strip"}]
        c = build_canonical([spec])
        strips = [u for u in c["unenforced"] if u.get("reason") == "template strip"]
        self.assertEqual(len(strips), 1)


REPAIR = importlib.util.module_from_spec(
    importlib.util.spec_from_file_location("repair_under_test",
                                           DATA / "tablea2_parsefilter_repair.py"))
REPAIR.__spec__.loader.exec_module(REPAIR)


class VocabularyTests(unittest.TestCase):
    """Revision 5 item 1: form vocabulary vs published-CSV vocabulary.
    Measured 2026-11-18 from 2,551 matched workbook/CSV rows."""
    TENURE = canonical(("TENURE", "list", '"R,O"', None, None, "in"))
    INFILL = canonical(("INFILL_UNITS", "list", '"Y,N"', None, None, "in"))

    def test_default_vocabulary_is_csv(self):
        import inspect
        sig = inspect.signature(validate_dataframe)
        self.assertEqual(sig.parameters["vocabulary"].default, "csv")

    def test_unknown_vocabulary_is_refused(self):
        with self.assertRaises(ValueError):
            validate_dataframe(frame(TENURE=["O"]), self.TENURE, vocabulary="xlsm")

    def test_csv_vocabulary_translates_allowed_tenure_items(self):
        df = frame(TENURE=["Owner", "Renter", "O", "R"])
        v = validate_dataframe(df, self.TENURE, vocabulary="csv")
        self.assertEqual([x["value"] for x in v], ["O", "R"])

    def test_form_vocabulary_keeps_form_codes(self):
        df = frame(TENURE=["Owner", "O", "R"])
        v = validate_dataframe(df, self.TENURE, vocabulary="form")
        self.assertEqual([x["value"] for x in v], ["Owner"])

    def test_csv_zero_is_a_blank_infill_cell(self):
        df = frame(INFILL_UNITS=["0", "Y", "N", "Z"])
        v = validate_dataframe(df, self.INFILL, vocabulary="csv")
        self.assertEqual([x["value"] for x in v], ["Z"])

    def test_form_zero_infill_is_a_violation(self):
        v = validate_dataframe(frame(INFILL_UNITS=["0"]), self.INFILL, vocabulary="form")
        self.assertEqual([x["value"] for x in v], ["0"])

    def test_zero_is_blank_only_for_infill(self):
        # '0' in another list column is NOT blank under csv.
        df = frame(TENURE=["0"])
        self.assertEqual(len(validate_dataframe(df, self.TENURE, vocabulary="csv")), 1)

    def test_tenure_translation_has_one_source(self):
        self.assertEqual(REPAIR.FORM_TO_CSV_TENURE, {"R": "Renter", "O": "Owner"})
        # The validator uses the repair script's own object, not a copy.
        self.assertIs(template_validator.FORM_TO_CSV_TENURE,
                      template_validator._repair_module().FORM_TO_CSV_TENURE)
        self.assertIs(template_validator.CSV_VALUE_TRANSLATIONS["TENURE"],
                      template_validator.FORM_TO_CSV_TENURE)


class ExportZeroColumnTests(unittest.TestCase):
    """Author's ruling 2026-11-18: the data's state is accepted and modelled.
    HCD's published CSV shows "0" in DEM_OR_DES_UNITS / DEM_DES_UNITS_OWN_RENT
    wherever the form had an entry (measured); rows the repair script rebuilds
    carry the form's own values. Under "csv" the allowed set is the form rule's
    items plus "0"; anything else is a violation; "form" is unchanged."""
    RULES = canonical(("DEM_OR_DES_UNITS", "list", '"Demolished,Destroyed"', None, None, "in"),
                      ("DEM_DES_UNITS_OWN_RENT", "list", '"R,O"', None, None, "in"))
    CASES = {"DEM_OR_DES_UNITS": (["0", "Demolished", "Destroyed"], ["Other", "demolished", "O", "1"]),
             "DEM_DES_UNITS_OWN_RENT": (["0", "O", "R"], ["Owner", "o", "Demolished", "1"])}

    def test_csv_vocabulary_accepts_zero_and_form_items(self):
        for col, (good, _) in self.CASES.items():
            with self.subTest(col=col):
                self.assertEqual(validate_dataframe(frame(**{col: good}), self.RULES,
                                                    vocabulary="csv"), [])

    def test_csv_vocabulary_flags_anything_else(self):
        for col, (_, bad) in self.CASES.items():
            with self.subTest(col=col):
                v = validate_dataframe(frame(**{col: bad}), self.RULES, vocabulary="csv")
                self.assertEqual([x["value"] for x in v], bad)
                self.assertEqual({x["column"] for x in v}, {col})

    def test_form_vocabulary_unchanged(self):
        df = frame(DEM_OR_DES_UNITS=["0", "Demolished"], DEM_DES_UNITS_OWN_RENT=["0", "O"])
        v = validate_dataframe(df, self.RULES, vocabulary="form")
        self.assertEqual(sorted((x["column"], x["value"]) for x in v),
                         [("DEM_DES_UNITS_OWN_RENT", "0"), ("DEM_OR_DES_UNITS", "0")])

    def test_one_constant_names_the_extra_item(self):
        self.assertEqual(template_validator.CSV_EXPORT_EXTRA_ITEMS,
                         {"DEM_OR_DES_UNITS": ("0",), "DEM_DES_UNITS_OWN_RENT": ("0",)})

    def test_nothing_is_listed_unenforced_for_them(self):
        self.assertFalse(hasattr(template_validator, "vocabulary_unenforced"))
        self.assertFalse(hasattr(template_validator, "CSV_UNCARRIED_REASON"))
        self.assertNotIn("does not carry", json.dumps(template_validator.ASSUMPTIONS))


class DateMappingTests(unittest.TestCase):
    """Revision 5 item 3: the form's date columns map to the CSV's date
    columns in the validator only; workbook datetimes render as YYYY-MM-DD."""
    DATES = {"A2_5_Date": "ENT_APPROVE_DT1", "A2_8_Date": "BP_ISSUE_DT1",
             "A2_10_Date": "CO_ISSUE_DT1"}

    def test_validator_maps_the_three_date_headers(self):
        m = a2_header_to_apr_columns(set(self.DATES) | {"A2_3_Tenure"})
        for header, col in self.DATES.items():
            self.assertEqual(m[header], col)
        self.assertEqual(m["A2_3_Tenure"], "TENURE")

    def test_unrequested_date_header_is_not_invented(self):
        self.assertNotIn("A2_5_Date", a2_header_to_apr_columns({"A2_3_Tenure"}))

    def test_repair_script_deliberately_does_not_copy_dates(self):
        mapped = REPAIR.map_a2_row_to_apr_record(
            {h: "x" for h in self.DATES}, {})
        self.assertEqual({col for col, v in mapped.items() if v == "x"}, set())

    def test_workbook_datetimes_render_as_iso_dates(self):
        import datetime
        path = Path(tempfile.mkdtemp()) / "T2020.xlsx"
        headers = {**BASE_HEADERS, "E": "A2_5_Date"}
        make_template(path, headers, cells={"E13": datetime.datetime(2023, 6, 15)})
        spec = extract_spec(path)
        df = workbook_dataframe(path, spec)
        # row 1000 is make_template's "x" sentinel row, hence the second row
        self.assertEqual(df["ENT_APPROVE_DT1"].tolist()[0], "2023-06-15")

    def test_form_vocabulary_date_control_sees_the_csv_text(self):
        rule = canonical(("ENT_APPROVE_DT1", "date", "18264", None, None, ">="))
        ok = frame(ENT_APPROVE_DT1=["2023-06-15"])
        self.assertEqual(validate_dataframe(ok, rule, vocabulary="form"), [])
        early = frame(ENT_APPROVE_DT1=["1949-12-31"])
        self.assertEqual(len(validate_dataframe(early, rule, vocabulary="form")), 1)


class ReportingYearTests(unittest.TestCase):
    """Revision 5 item 4: the form's year is Start Here!B5, not the filename."""

    def test_extract_spec_reads_start_here_b5_not_the_filename(self):
        path = Path(tempfile.mkdtemp()) / "T2020.xlsx"
        make_template(path, BASE_HEADERS, year=2021)
        self.assertEqual(extract_spec(path)["reporting_year"], 2021)

    def test_missing_start_here_is_fatal_not_guessed(self):
        path = Path(tempfile.mkdtemp()) / "T2020.xlsx"
        make_template(path, BASE_HEADERS, year=None)
        with self.assertRaises(SystemExit):
            extract_spec(path)

    def test_non_year_b5_is_fatal(self):
        path = Path(tempfile.mkdtemp()) / "T2020.xlsx"
        make_template(path, BASE_HEADERS, year="soon")
        with self.assertRaises(SystemExit):
            extract_spec(path)


class RepairTenureTranslationTests(unittest.TestCase):
    """Revision 5 item 5: recovered rows use the published CSV's vocabulary."""

    def test_form_codes_become_csv_words(self):
        for code, word in (("O", "Owner"), ("R", "Renter")):
            got = REPAIR.map_a2_row_to_apr_record({"A2_3_Tenure": code}, {})
            self.assertEqual(got["TENURE"], word)

    def test_other_values_pass_through(self):
        for v in ("", "Owner", "X"):
            got = REPAIR.map_a2_row_to_apr_record({"A2_3_Tenure": v}, {})
            self.assertEqual(got["TENURE"], v)

    def test_demolition_columns_unchanged_open_finding(self):
        got = REPAIR.map_a2_row_to_apr_record(
            {"A2_20_Dest": "Demolished", "A2_20_Demo": "O"}, {})
        self.assertEqual((got["DEM_OR_DES_UNITS"], got["DEM_DES_UNITS_OWN_RENT"]),
                         ("Demolished", "O"))


@unittest.skipUnless(WORKBOOKS, "template .xlsm files not present")
class WorkbookSmokeTests(unittest.TestCase):
    def test_extract_and_positive_control(self):
        # Newest template: the era whose data-area rules live in x14 extensions.
        newest = max(WORKBOOKS, key=lambda p: re.search(r"(?:19|20)\d{2}", p.stem).group())
        spec = extract_spec(newest)
        self.assertEqual(spec["header_row"], 6)
        self.assertIn("sha256", spec)
        self.assertIn("data_start", spec)
        canonical = build_canonical([spec])
        self.assertGreater(len(canonical["rules"]), 30)
        self.assertTrue(any("x14" in r["sources"] for r in canonical["rules"]),
                        "expected x14 extension rules in the newest template")
        control = workbook_dataframe(newest, spec)
        self.assertGreater(len(control), 0)
        # Regression control (re-audit F1): a 2024 row is judged by the 2024
        # form's list — a value legal only under the 2024 SB-9 list must
        # validate clean, not be flagged by other years' Y/N lists.
        sb9 = frame(YEAR=["2024"], UNIT_CAT=["SFA"],
                    APPROVE_SB35=["SB 9 (2021) - Duplex in SF Zone"])
        era_rules = [r for r in canonical["rules"]
                     if r["apr_column"] == "APPROVE_SB35"]
        self.assertEqual(validate_dataframe(sb9,
                       {**canonical, "rules": era_rules}), [])

    # Exact positive-control survivors per template (column -> count). With
    # HCD's multi-select columns read from each template's macro, every
    # template's own rows validate clean.
    CONTROL_SURVIVORS = {}

    def test_multi_select_columns_read_from_each_template_macro(self):
        # From each template's Table A2 Worksheet_Change macro (2026-11-17);
        # Bell2019's multi-select line is commented out.
        expected = {"Bell2019.xlsm": [], "Ceres2020.xlsm": ["AL", "AM"],
                    "Colfax2021.xlsm": ["AL", "AM", "AU"],
                    "Hesperia2022.xlsm": ["AL", "AM", "AU"],
                    "Irvine2022.xlsm": ["AL", "AM", "AU"],
                    "Bell2023.xlsm": ["AJ", "AL", "AM", "AU"],
                    "Campbell2024.xlsm": ["AJ", "AL", "AM", "AU"],
                    "Hesperia2023.xlsm": ["AJ", "AL", "AM", "AU"],
                    "Hesperia2024.xlsm": ["AJ", "AL", "AM", "AU"]}
        import openpyxl
        for wb in WORKBOOKS:
            with self.subTest(workbook=wb.name):
                codename = openpyxl.load_workbook(wb)[template_validator.SHEET] \
                    .sheet_properties.codeName
                self.assertEqual(sorted(template_validator._multi_select_columns(
                    wb, codename)), expected[wb.name])

    def test_positive_control_every_template(self):
        # Audit finding 3/5: the control ran on one template and exempted
        # whole columns. Run it on each template against that template's own
        # rules, and pin survivors exactly.
        for wb in WORKBOOKS:
            with self.subTest(workbook=wb.name):
                spec = extract_spec(wb)
                canonical = build_canonical([spec])
                control = workbook_dataframe(wb, spec)
                self.assertGreater(len(control), 0,
                                   f"{wb.name}: control frame has no rows")
                evaluated = enforced_nonblank_cells(control, canonical)
                self.assertGreater(
                    evaluated, 0,
                    f"{wb.name}: {evaluated} non-blank cells in enforced-rule "
                    f"columns ({len(control)} control rows)")
                violations = validate_dataframe(control, canonical,
                                                row_offset=spec["data_start"],
                                                vocabulary="form")
                counts = {}
                for v in violations:
                    counts[v["column"]] = counts.get(v["column"], 0) + 1
                self.assertEqual(counts, self.CONTROL_SURVIVORS.get(wb.name, {}),
                                 f"{wb.name}: {violations[:10]}")

    def test_data_end_stops_before_overflow_block(self):
        # Audit finding 3: 2019-2022 templates derived data_end = 1048576, so
        # the overflow rules (rows after the data area) were enforced.
        expected = {"Bell2019.xlsm": 1000, "Hesperia2022.xlsm": 1000,
                    "Irvine2022.xlsm": 2496, "Bell2023.xlsm": 1000,
                    "Hesperia2024.xlsm": 661}
        for wb in WORKBOOKS:
            if wb.name in expected:
                with self.subTest(workbook=wb.name):
                    self.assertEqual(extract_spec(wb)["data_end"], expected[wb.name])

    def test_duplicate_rule_on_same_cells_first_wins(self):
        # Audit finding 4: AT13:AT1000 carries 0..20 then 0..100. Excel
        # (queried 2026-11-17, Campbell2024 AT13/AT500/AT1000) applies 0..20.
        wb = next(w for w in WORKBOOKS if w.name == "Campbell2024.xlsm")
        spec = extract_spec(wb)
        at = [(r["formula1"], r["formula2"]) for r in spec["rules"]
              if r["column"] == "AT"]
        self.assertEqual(at, [("0", "20")])
        shadowed = [u for u in spec["unenforced"]
                    if u.get("column") == "AT" and "shadowed" in u["reason"]]
        self.assertEqual([u["formula2"] for u in shadowed], ["100"])
        canonical = build_canonical([spec])
        col = next(r["apr_column"] for r in canonical["rules"]
                   if r["a2_headers"] == ["A2_23_DB"])
        v = validate_dataframe(frame(YEAR=["2024"], **{col: ["21"]}), canonical)
        self.assertEqual(len(v), 1)

    def test_headerless_data_rules_listed_in_2021_template(self):
        # F1 on the real template: AS..AV have no header in Colfax2021 yet
        # carry data-area rules (AS decimal, AT whole x2, AU/AV x14 lists).
        wb = next(w for w in WORKBOOKS if w.name == "Colfax2021.xlsm")
        spec = extract_spec(wb)
        got = {u["column"] for u in spec["unenforced"]
               if u["reason"] == "column has no header in this template"}
        self.assertGreaterEqual(got, {"AS", "AT", "AU", "AV"})

    def test_cli_control_runs_on_every_workbook(self):
        # F3: one control per workbook, each against its own spec, exit 0 on
        # clean data. Bell2019 judged by the 2024 rules gave 13 false violations.
        names = ["Bell2019.xlsm", "Campbell2024.xlsm"]
        argv = [a for n in names for a in ("--workbook", str(DATA / n))]
        real, canon_workbooks = template_validator.validate_dataframe, []

        def spy(df, canonical, **kw):
            canon_workbooks.append([w["workbook"] for w in canonical["workbooks"]])
            return real(df, canonical, **kw)

        out = io.StringIO()
        with mock.patch.object(template_validator, "validate_dataframe", side_effect=spy), \
                contextlib.redirect_stdout(out):
            code = template_validator.main(argv)
        lines = [l for l in out.getvalue().splitlines() if l.startswith("positive control:")]
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual(len(lines), 2, out.getvalue())
        self.assertIn("Bell2019.xlsm", lines[0])
        self.assertIn("Campbell2024.xlsm", lines[1])
        self.assertEqual(canon_workbooks, [[n] for n in names])

    def test_cli_control_exit_1_if_any_workbook_violates(self):
        names = ["Bell2019.xlsm", "Campbell2024.xlsm"]
        argv = [a for n in names for a in ("--workbook", str(DATA / n))]
        fake = [{"row": 13, "column": "DR_TYPE", "value": "x", "reason": "r",
                 "templates": "T", "years": [2024]}]
        out = io.StringIO()
        with mock.patch.object(template_validator, "validate_dataframe",
                               side_effect=[[], fake]), \
                contextlib.redirect_stdout(out):
            code = template_validator.main(argv)
        self.assertEqual(code, 1, out.getvalue())
        self.assertEqual(out.getvalue().count("positive control:"), 2, out.getvalue())

    def test_cli_positive_control_fails_on_violations(self):
        # Audit finding 5: the CLI exited 0 with 10 control violations. Inject
        # one violation into the control run; a clean run must still exit 0.
        from unittest import mock
        wb = str(next(w for w in WORKBOOKS if w.name == "Campbell2024.xlsm"))
        fake = [{"row": 13, "column": "DR_TYPE", "value": "x", "reason": "r",
                 "templates": "T", "years": [2024]}]
        with mock.patch.object(template_validator, "validate_dataframe",
                               return_value=fake):
            self.assertEqual(template_validator.main(["--workbook", wb]), 1)
        self.assertEqual(template_validator.main(["--workbook", wb]), 0)

    def test_custom_xlow_rule_enforced_and_clean_on_own_data(self):
        # The newest template carries the known A2_13_xLow custom rule; it must
        # extract as enforced-with-semantics, survive build_canonical, leave no
        # custom-drift entry in unenforced, and pass on the template's own rows.
        spec = extract_spec(max(WORKBOOKS,
                                key=lambda p: re.search(r"(?:19|20)\d{2}", p.stem).group()))
        customs = [r for r in spec["rules"] if r["type"] == "custom"]
        self.assertEqual(len(customs), 1)
        self.assertEqual(customs[0]["custom"]["target_header"], "A2_13_xLow")
        self.assertEqual(customs[0]["custom"]["target_column"], "AI")
        canonical = build_canonical([spec])
        enforced = [r for r in canonical["rules"]
                    if r["type"] == "custom" and r["apr_column"] == "EXTR_LOW_INCOME_UNITS"]
        self.assertEqual(len(enforced), 1)
        self.assertEqual(enforced[0]["interpreted_operator"], "custom")
        self.assertEqual([u for u in canonical["unenforced"]
                          if u.get("reason") == "template formula changed"], [])
        control = workbook_dataframe(
            max(WORKBOOKS, key=lambda p: re.search(r"(?:19|20)\d{2}", p.stem).group()),
            spec)
        violations = validate_dataframe(control, canonical,
                                        row_offset=spec.get("data_start",
                                                            spec["header_row"] + 1),
                                        vocabulary="form")
        xlow = [v for v in violations if v["column"] == "EXTR_LOW_INCOME_UNITS"]
        self.assertEqual(xlow, [],
                         f"positive-control EXTR_LOW_INCOME_UNITS violations: {xlow[:5]}")

    def test_perturbed_formula_in_real_template_goes_unenforced(self):
        # Drift gate end-to-end: one changed comparator column (Z->AB, a real
        # header) in the shipped .xlsm must disable enforcement, not silently
        # enforce different semantics.
        src = max(WORKBOOKS, key=lambda p: re.search(r"(?:19|20)\d{2}", p.stem).group())
        dst = Path(tempfile.mkdtemp()) / "drifted.xlsm"
        with zipfile.ZipFile(src) as zin, \
                zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if b"SUM(Z13:AA13)" in data:
                    data = data.replace(b"SUM(Z13:AA13)", b"SUM(Z13:AB13)")
                zout.writestr(item, data)
        spec = extract_spec(dst)
        self.assertEqual([r for r in spec["rules"] if r["type"] == "custom"], [])
        drifted = [u for u in spec["unenforced"] if u.get("type") == "custom"]
        self.assertEqual(len(drifted), 1)
        self.assertEqual(drifted[0]["reason"], "template formula changed")

    def test_reporting_years_of_the_nine_workbooks(self):
        # Start Here!B5 measured 2026-11-18 (mapping report section 2).
        expected = {"Bell2019.xlsm": 2019, "Bell2023.xlsm": 2023,
                    "Campbell2024.xlsm": 2024, "Ceres2020.xlsm": 2020,
                    "Colfax2021.xlsm": 2021, "Hesperia2022.xlsm": 2022,
                    "Hesperia2023.xlsm": 2023, "Hesperia2024.xlsm": 2024,
                    "Irvine2022.xlsm": 2022}
        for wb in WORKBOOKS:
            with self.subTest(workbook=wb.name):
                self.assertEqual(extract_spec(wb)["reporting_year"], expected[wb.name])

    def test_date_rules_are_enforced_in_every_workbook(self):
        for wb in WORKBOOKS:
            with self.subTest(workbook=wb.name):
                c = build_canonical([extract_spec(wb)])
                cols = {r["apr_column"] for r in c["rules"] if r["type"] == "date"}
                self.assertEqual(cols, {"ENT_APPROVE_DT1", "BP_ISSUE_DT1",
                                        "CO_ISSUE_DT1"})

    def test_cli_csv_run_prints_unchecked_years_and_judges_demolition_columns(self):
        csv_path = Path(tempfile.mkdtemp()) / "mini.csv"
        csv_path.write_text("YEAR,TENURE,DEM_OR_DES_UNITS\n"
                            "2018,X,0\n2018,X,0\n2024,Owner,0\n2024,X,0\n"
                            "2024,Owner,Destroyed\n2024,Owner,Bogus\n")
        wb = str(next(w for w in WORKBOOKS if w.name == "Campbell2024.xlsm"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = template_validator.main(["--workbook", wb, "--input", str(csv_path)])
        text = out.getvalue()
        self.assertEqual(code, 1, text)
        self.assertIn("rows not checked (YEAR has no form): 2 (2018: 2)", text)
        self.assertNotIn("does not carry", text)
        self.assertIn("2 violations", text)  # 2024 TENURE X; 2024 DEM_OR_DES_UNITS Bogus
        self.assertIn("TENURE: 1 violations on 1 rows", text)
        self.assertIn("DEM_OR_DES_UNITS: 1 violations on 1 rows", text)


if __name__ == "__main__":
    unittest.main()

