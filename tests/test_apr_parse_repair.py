from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import tablea2_parsefilter_repair as parser


ROOT = Path(__file__).resolve().parents[1]


class AprRepairBoundaryTests(unittest.TestCase):
    def test_chart_repair_script_is_not_symlink_to_root(self):
        chart_script = ROOT / "TableA2-charts" / "tablea2_parsefilter_repair.py"
        self.assertFalse(chart_script.is_symlink(), "Charts repair script must be a real wrapper file, not a symlink.")

        root_script = ROOT / "tablea2_parsefilter_repair.py"
        chart_script = ROOT / "TableA2-charts" / "tablea2_parsefilter_repair.py"

        self.assertNotEqual(
            root_script.read_bytes(),
            chart_script.read_bytes(),
            "Charts repair script must wrap, not duplicate, the root implementation.",
        )

    def test_root_module_exports_run_repair(self):
        self.assertTrue(callable(parser.run_repair))

    def test_path_configuration_separates_inputs_and_outputs(self):
        with TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            input_dir = temp_root / "inputs"
            output_dir = temp_root / "outputs"
            try:
                parser._set_paths(input_dir, output_dir)
                self.assertEqual(parser.apr_path.resolve(), (input_dir / "tablea2.csv").resolve())
                self.assertEqual(
                    parser.cleaned_path.resolve(),
                    (output_dir / "tablea2_cleaned_parsefilter_repair.csv").resolve(),
                )
                self.assertEqual(parser._input_dir.resolve(), input_dir.resolve())
                self.assertEqual(parser._output_dir.resolve(), output_dir.resolve())
            finally:
                parser._set_paths(ROOT, ROOT)

    def test_quote_repair_preserves_clean_text(self):
        raw = "A,B,C\n1,2,3\n"
        repaired, openers, closers, changed_lines = parser._repair_quote_corruption(raw)

        self.assertEqual(repaired, raw)
        self.assertEqual(openers, 0)
        self.assertEqual(closers, 0)
        self.assertEqual(changed_lines, set())

    def test_chart_wrapper_imports_canonical_root(self):
        chart_script = ROOT / "TableA2-charts" / "tablea2_parsefilter_repair.py"
        source = chart_script.read_text(encoding="utf-8")

        self.assertIn("from tablea2_parsefilter_repair import run_repair", source)
        self.assertIn("run_repair(base_dir=chart_dir, output_dir=chart_dir)", source)


if __name__ == "__main__":
    unittest.main()
