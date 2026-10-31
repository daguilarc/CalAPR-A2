"""Diego's append review rules: linked recovered records must await review."""
import contextlib
import copy
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

SOURCE = Path(__file__).resolve().parents[1] / "data-cleanup/tablea2_parsefilter_repair.py"
spec = importlib.util.spec_from_file_location("append_cleaner", SOURCE)
cleaner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleaner)


def identity(**kwargs):
    row = dict(zip(cleaner.IDENTITY_KEY_COLS, ["Town", "County", "2024", "P1", "1 Main St", "T1"]))
    row.update(kwargs)
    return row


def bundle(row=None, mapped=None):
    row = identity() if row is None else row
    return {"identity": row, "mapped": dict(row) if mapped is None else mapped,
            "xlsm_candidate_count": 1,
            "ambiguity_context": dict(identity=row, source_info={"source_lines": [19, 23], "raw_row_count": 2},
                                      workbook_path=Path("/work/Town2024.xlsm"), match_stage_used="apn_only",
                                      excel_row_numbers=[8], candidate_key_digest="candidate")}


def frame(rows=()):
    return pd.DataFrame(rows, columns=cleaner.IDENTITY_KEY_COLS)


class AppendSafeguardTests(unittest.TestCase):
    def screen(self, pending, original=(), current=None):
        return cleaner._screen_pending_appends(frame(original), frame(original if current is None else current), pending)

    def test_unique_positive_and_inputs_unchanged(self):
        pending = [bundle()]
        before = copy.deepcopy(pending)
        original = frame([identity(APN="other", STREET_ADDRESS="elsewhere", JURS_TRACKING_ID="other")])
        saved = original.copy(deep=True)
        accepted, withheld = cleaner._screen_pending_appends(original, original, pending)
        self.assertEqual(accepted, [pending[0]["mapped"]])
        self.assertEqual(withheld, [])
        self.assertEqual(pending, before)
        pd.testing.assert_frame_equal(original, saved)
        self.assertEqual(self.screen([]), ([], []))

    def test_each_identifier_normalized_and_field_tags(self):
        for field, value in [("APN", "p-1"), ("STREET_ADDRESS", "1 MAIN.ST"), ("JURS_TRACKING_ID", "t-1")]:
            with self.subTest(field=field):
                existing = identity(APN="different", STREET_ADDRESS="different", JURS_TRACKING_ID="different")
                existing[field] = value
                self.assertEqual(len(self.screen([bundle()], [existing])[1]), 1)
        mapped = identity(APN="UNIQUE", STREET_ADDRESS="ELSE", JURS_TRACKING_ID="OTHER")
        existing = identity(APN="OTHER", STREET_ADDRESS="UNIQUE", JURS_TRACKING_ID="ELSE")
        self.assertEqual(len(self.screen([bundle(mapped)], [existing])[0]), 1)

    def test_source_and_both_snapshots(self):
        source = identity(APN="OLD", STREET_ADDRESS="SOURCE", JURS_TRACKING_ID="SOURCE")
        mapped = identity(APN="NEW", STREET_ADDRESS="MAPPED", JURS_TRACKING_ID="MAPPED")
        existing = identity(APN="OLD", STREET_ADDRESS="OTHER", JURS_TRACKING_ID="OTHER")
        for original, current in [([existing], []), ([], [existing])]:
            accepted, withheld = self.screen([bundle(source, mapped)], original, current)
            self.assertEqual(len(withheld), 1)
            self.assertEqual(accepted, [])
            evidence = json.loads(withheld[0]["append_existing_candidates"])
            self.assertTrue(all(edge["proposal_origin"] == "source" for edge in evidence))

    def test_scope_wildcards_county_and_distinct_context(self):
        for changes in [dict(CNTY_NAME=""), dict(CNTY_NAME="Other"), dict(JURIS_NAME=""), dict(YEAR="bad")]:
            self.assertEqual(len(self.screen([bundle()], [identity(**changes)])[1]), 1)
        for changes in [dict(JURIS_NAME="Other"), dict(YEAR="2023")]:
            self.assertEqual(len(self.screen([bundle()], [identity(**changes)])[0]), 1)

    def test_year_representations_and_insufficient_identity(self):
        for year in [2024.0, "2.024e3"]:
            self.assertEqual(len(self.screen([bundle(identity(YEAR=year))], [identity()])[1]), 1)
        for year in ["2024.1", "NaN", "Infinity", ""]:
            rejected = self.screen([bundle(identity(YEAR=year))])[1]
            self.assertIn("insufficient_append_identity", json.loads(rejected[0]["append_review_reasons"]))
        for value in ["", "N/A", "NA", "NONE", "NAN", "UNKNOWN", "NOT APPLICABLE", "0", "-", "TBD", "NOT AVAILABLE", "000", "0.0", "000-000"]:
            mapped = identity(APN=value, STREET_ADDRESS="", JURS_TRACKING_ID=value)
            self.assertEqual(len(self.screen([bundle(identity(), mapped)])[1]), 1, value)
        self.assertEqual(len(self.screen([bundle(identity(CNTY_NAME=""))])[1]), 1)

    def test_numeric_aliases_preserve_payload(self):
        for field in ["APN", "JURS_TRACKING_ID"]:
            for value in ["123", "00123", "123.0", "123.00"]:
                row = identity(APN="different", STREET_ADDRESS="different", JURS_TRACKING_ID="different")
                row[field] = value
                existing = identity(APN="else", STREET_ADDRESS="else", JURS_TRACKING_ID="else")
                existing[field] = "123"
                proposal = bundle(row)
                self.assertEqual(len(self.screen([proposal], [existing])[1]), 1)
                self.assertEqual(proposal["mapped"][field], value)

    def test_actual_apn_completes_and_preserves_literal_payload(self):
        code = """
import importlib.util
import sys
spec = importlib.util.spec_from_file_location('bounded_cleaner', sys.argv[1])
cleaner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleaner)
for value in ['123.0', '048E732004800']:
    row = {'APN': value}
    before = dict(row)
    tokens = cleaner._append_identity_tokens(row)[1]
    expected = {('APN', '1230'), ('APN', '123')} if value == '123.0' else {('APN', value)}
    assert tokens == expected, tokens
    assert row == before
    print(value, 'literal/payload control passed', flush=True)
"""
        result = subprocess.run([sys.executable, "-c", code, str(SOURCE)],
                                capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("048E732004800 literal/payload control passed", result.stdout)
        self.assertIn("123.0 literal/payload control passed", result.stdout)

    def test_literal_identifiers_and_long_coefficients_remain_distinct(self):
        for field in ["APN", "JURS_TRACKING_ID"]:
            for value, other in [("1E3", "1000"), ("048E732004800", "480E732004799"),
                                 ("123456789012345678901234567890", "123456789012345678901234567891")]:
                with self.subTest(field=field, value=value):
                    row = identity(APN="candidate", STREET_ADDRESS="candidate", JURS_TRACKING_ID="candidate")
                    row[field] = value
                    existing = identity(APN="unrelated", STREET_ADDRESS="unrelated", JURS_TRACKING_ID="unrelated")
                    existing[field] = other
                    self.assertEqual({token for token in cleaner._append_identity_tokens(row)[1] if token[0] == field},
                                     {(field, value)})
                    proposal = bundle(row)
                    self.assertEqual(self.screen([proposal], [existing]), ([proposal["mapped"]], []))
                    existing[field] = value
                    accepted, withheld = self.screen([proposal], [existing])
                    self.assertEqual(accepted, [])
                    self.assertEqual(len(withheld), 1)
                    self.assertIn("possible_existing_duplicate", json.loads(withheld[0]["append_review_reasons"]))
                    self.assertEqual(proposal["mapped"][field], value)
                    if value.isascii() and value.isdigit():
                        existing[field] = "00" + value + ".00"
                        self.assertEqual(len(self.screen([proposal], [existing])[1]), 1)

    def test_pending_pair_chain_invalid_node_and_permutations(self):
        a = bundle(identity(APN="A", STREET_ADDRESS="A", JURS_TRACKING_ID="A"))
        b = bundle(identity(APN="A", STREET_ADDRESS="B", JURS_TRACKING_ID="B", CNTY_NAME=""))
        c = bundle(identity(APN="C", STREET_ADDRESS="B", JURS_TRACKING_ID="C"))
        for proposals in [[a, b], [a, b, c], [c, a, b]]:
            accepted, withheld = self.screen(proposals)
            self.assertEqual(accepted, [])
            self.assertEqual(len(withheld), len(proposals))
            self.assertTrue(all("possible_pending_duplicate" in json.loads(r["append_review_reasons"]) for r in withheld))

    def test_metadata_all_causes_and_loaded_ordinals(self):
        proposals = [bundle(), bundle()]
        _, withheld = self.screen(proposals, [identity(), identity()])
        for record in withheld:
            self.assertEqual(record["ambiguity_stage"], "append_candidate_review")
            self.assertEqual(record["df_candidate_count"], 2)
            self.assertEqual(record["source_lines"], "19|23")
            self.assertEqual(record["excel_row_numbers"], "8")
            self.assertEqual(record["workbook_path"], "Town2024.xlsm")
            self.assertEqual(json.loads(record["append_review_reasons"]), ["possible_existing_duplicate", "possible_pending_duplicate"])
            edges = json.loads(record["append_existing_candidates"])
            self.assertEqual({e["loaded_record_ordinal"] for e in edges}, {1, 2})
            self.assertEqual({e["snapshot"] for e in edges}, {"original", "current"})

    def test_metadata_is_strict_json_with_missing_raw_cells(self):
        row = identity(APN=float("nan"), STREET_ADDRESS=pd.NA)
        _, records = self.screen([bundle(row)], [identity()])
        for key in ["append_review_reasons", "append_candidate_mapped_identity", "append_existing_candidates", "append_pending_candidates"]:
            with self.subTest(key=key):
                def reject_constant(value):
                    self.fail("Nonstandard JSON constant: " + value)
                json.loads(records[0][key], parse_constant=reject_constant)
        mapped = json.loads(records[0]["append_candidate_mapped_identity"])
        self.assertEqual(mapped["APN"], "NaN")
        self.assertEqual(mapped["STREET_ADDRESS"], "<NA>")

    def test_process_contract_and_recovery_outcomes(self):
        row = identity()
        candidate = {"A2_1_Current": "MAPPED", "__excel_row_number": 8}
        matches = {"candidates": [candidate], "match_stage_used": "apn_only", "excel_row_numbers": [8]}
        with patch.object(cleaner, "_resolve_workbook_path", return_value=Path("Town2024.xlsm")), patch.object(cleaner, "_load_a2_rows_with_indexes", return_value={}), patch.object(cleaner, "_find_a2_matches", return_value=matches):
            result = cleaner._process_truncated_identity(row, {}, {}, frame(), {})
            self.assertEqual(len(result), 3)
            self.assertEqual(result[0]["upsert_append"], 1)
            self.assertEqual(result[2]["mapped"]["APN"], "MAPPED")
            existing = frame([row])
            update = cleaner._process_truncated_identity(row, {}, {}, existing, cleaner._build_identity_index(existing))
            self.assertEqual(update[0]["upsert_update"], 1)
            self.assertIsNone(update[2])
            with patch.object(cleaner, "_find_a2_matches", return_value={**matches, "candidates": []}):
                self.assertEqual(cleaner._process_truncated_identity(row, {}, {}, frame(), {})[0]["upsert_unresolved"], 1)
            with patch.object(cleaner, "_resolve_multi_xlsm", return_value=("paired", None, [])), patch.object(cleaner, "_apply_paired_upserts", return_value=2), patch.object(cleaner, "_find_a2_matches", return_value={**matches, "candidates": [candidate, candidate]}):
                result = cleaner._process_truncated_identity(row, {}, {}, frame(), {})
                self.assertEqual(result[0]["upsert_paired"], 1)
                self.assertEqual(result[0]["upsert_rows_via_pairing"], 2)
            with patch.object(cleaner, "_resolve_multi_xlsm", return_value=("ambiguous", None, None)), patch.object(cleaner, "_find_a2_matches", return_value={**matches, "candidates": [candidate, candidate]}):
                result = cleaner._process_truncated_identity(row, {}, {}, frame(), {})
                self.assertEqual(result[0]["upsert_ambiguous"], 1)
                self.assertEqual(result[1][0]["ambiguity_stage"], "xlsm_multi_match")
                self.assertIsNone(result[2])

    def test_main_concat_exports_and_counters(self):
        existing = identity(APN="EXISTING", STREET_ADDRESS="OLD ADDRESS", JURS_TRACKING_ID="OLD TRACK")
        collision = identity(APN="EXISTING", STREET_ADDRESS="NEW ADDRESS", JURS_TRACKING_ID="NEW TRACK")
        unique = identity(APN="UNIQUE", STREET_ADDRESS="UNIQUE ADDRESS", JURS_TRACKING_ID="UNIQUE TRACK")
        proposals = [collision, unique]
        metrics = []
        appended = []
        real_append = cleaner._append_rows_with_dtype_defaults
        def observe_append(df, rows):
            appended.extend(rows)
            return real_append(df, rows)
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            root = Path(directory)
            frame([existing]).to_csv(root / "tablea2.csv", index=False)
            stack.enter_context(patch.object(cleaner, "_extract_truncated_closer_rows", return_value=frame(proposals)))
            stack.enter_context(patch.object(cleaner, "_build_identity_source_map", return_value={}))
            stack.enter_context(patch.object(cleaner, "_strip_affordability_trailing_quotes", return_value=0))
            stack.enter_context(patch.object(cleaner, "_repair_column_shift_rows", return_value=0))
            stack.enter_context(patch.object(cleaner, "_resolve_workbook_path", return_value=Path("Town2024.xlsm")))
            stack.enter_context(patch.object(cleaner, "_load_a2_rows_with_indexes", return_value={}))
            def find(indexes, row):
                return {"candidates": [{"A2_1_Current": row["APN"], "A2_1_Address": row["STREET_ADDRESS"], "A2_1_ID": row["JURS_TRACKING_ID"]}], "match_stage_used": "apn_only", "excel_row_numbers": [8]}
            stack.enter_context(patch.object(cleaner, "_find_a2_matches", side_effect=find))
            stack.enter_context(patch.object(cleaner, "_append_rows_with_dtype_defaults", side_effect=observe_append))
            stack.enter_context(patch.object(cleaner, "_lone_quote_cleanup", return_value=0))
            stack.enter_context(patch.object(cleaner, "_apply_validation_filters", side_effect=lambda df: (df, df.iloc[:0], df.iloc[:0], df.iloc[:0])))
            stack.enter_context(patch.object(cleaner, "_compare_date_excluded_phases", return_value=pd.DataFrame()))
            stack.enter_context(patch.object(cleaner, "_classify_truncated_rows", return_value=(pd.DataFrame(), pd.DataFrame())))
            stack.enter_context(patch.object(cleaner, "_print_summary_block", side_effect=lambda rows: metrics.extend(rows)))
            with contextlib.redirect_stdout(io.StringIO()):
                cleaner.run_repair(root, root)
            output = pd.read_csv(root / "tablea2_cleaned_parsefilter_repair.csv")
            self.assertEqual([r["APN"] for r in appended], ["UNIQUE"])
            review = pd.read_csv(root / "ambiguous_truncated_repair.csv")
            self.assertEqual(len(output), 2)
            self.assertEqual(len(review), 1)
            self.assertEqual(review.iloc[0]["ambiguity_stage"], "append_candidate_review")
        counters = dict(metrics)
        self.assertEqual(counters["truncated_identities_resolved_append"], 1)
        self.assertEqual(counters["truncated_identities_ambiguous"], 1)
        self.assertEqual(counters["append_candidates_withheld"], 1)


if __name__ == "__main__":
    unittest.main()
