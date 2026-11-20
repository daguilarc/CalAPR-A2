"""Workbook rows missing from the public CSV: the rule of data-cleanup/workbook_rows_missing.py."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data-cleanup"
spec = importlib.util.spec_from_file_location("workbook_rows_missing", DATA / "workbook_rows_missing.py")
wrm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wrm)

HEADER = ["JURIS_NAME", "CNTY_NAME", "YEAR", "PRIOR_APN", "APN", "STREET_ADDRESS", "PROJECT_NAME",
          "JURS_TRACKING_ID", "UNIT_CAT", "TENURE"]


def wb_row(excel_row, tracking_id="T1", address="1 A St", apn="", unit="ADU", tenure="R", **over):
    row = {"A2_1_ID": tracking_id, "A2_1_Current": apn, "A2_1_Address": address, "A2_2_Unit": unit,
           "A2_3_Tenure": tenure, "A2_6_Units": "0", "A2_9_Units": "1", "A2_10_Units": "0",
           "A2_5_Date": "", "A2_8_Date": "2023-05-06 00:00:00", "A2_10_Date": "", "_excel_row": excel_row}
    row.update(over)
    return row


def record(tracking_id="T1", address="1 A St", apn="", unit="ADU", tenure="Renter", juris="TOWN", year="2023"):
    return [juris, "County", year, "", apn, address, "", tracking_id, unit, tenure]


def missing(rows, records):
    return [r["_excel_row"] for r in wrm.missing_rows(rows, records, HEADER, "TOWN", "2023")]


class MissingRowTests(unittest.TestCase):
    def test_shared_id_one_present_one_missing_at_another_address(self):
        rows = [wb_row(10, address="1 A St"), wb_row(11, address="2 B St")]
        self.assertEqual(missing(rows, [record(address="1 a  ST")]), [11])
        # the record belongs to the later row: only the address tells them apart
        self.assertEqual(missing(rows, [record(address="2 b st")]), [10])

    def test_multiset_one_record_accounts_for_one_row(self):
        rows = [wb_row(10), wb_row(11)]
        self.assertEqual(missing(rows, [record()]), [11])
        self.assertEqual(missing(rows, [record(), record()]), [])

    def test_housing_type_and_tenure_must_agree(self):
        self.assertEqual(missing([wb_row(10)], [record(unit="SFD")]), [10])
        self.assertEqual(missing([wb_row(10)], [record(tenure="Owner")]), [10])
        self.assertEqual(missing([wb_row(10, tenure="O", unit="SFD")], [record(tenure="Owner", unit="SFD")]), [])

    def test_other_jurisdiction_or_year_does_not_count(self):
        self.assertEqual(missing([wb_row(10)], [record(juris="OTHER")]), [10])
        self.assertEqual(missing([wb_row(10)], [record(year="2022")]), [10])

    def test_no_id_matches_on_apn_and_address(self):
        rows = [wb_row(10, tracking_id="N/A", apn="111", address="1 A St"),
                wb_row(11, tracking_id="", apn="222", address="2 B St")]
        records = [record(tracking_id="", apn="111", address="1 a st", unit="SFD")]
        self.assertEqual(missing(rows, records), [11])

    def test_rows_out_of_scope_are_not_judged(self):
        rows = [wb_row(10, tracking_id="N/A", apn="", address=""),                      # no identity part
                wb_row(11, A2_9_Units="0"),                                              # no positive units
                wb_row(12, A2_8_Date="2022-05-06 00:00:00"),                             # date rule: wrong year
                wb_row(13)]
        self.assertEqual(missing(rows, []), [13])

    def test_quoted_line_break_stays_one_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tablea2.csv"
            path.write_text(",".join(HEADER) + '\nTOWN,County,2023,,,1 A St,,"T1\n5/16/2023",ADU,Renter\n',
                            encoding="utf-8")
            header, records = wrm.public_records(path)
        self.assertEqual(len(records), 1)
        row = wb_row(10, tracking_id="T1\n5/16/2023")
        self.assertEqual([r["_excel_row"] for r in wrm.missing_rows([row], records, header, "TOWN", "2023")], [])

    def test_workbook_literal_na_survives_reading(self):
        import pandas as pd
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Town2023.xlsx"
            pd.DataFrame([["A2_1_ID", "A2_18_Affordable"], ["N/A", "x"]]).to_excel(
                path, sheet_name="Table A2", header=False, index=False)
            self.assertEqual(wrm.workbook_rows(path)[0]["A2_1_ID"], "N/A")


if __name__ == "__main__":
    unittest.main()
