from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "TableA2-models"
sys.path.insert(0, str(MODELS))

from acs_apr_models import _housing_rate_axis_label


class HousingAxisLabelTests(unittest.TestCase):
    def test_housing_axis_label_with_and_without_range(self):
        assert _housing_rate_axis_label("Net multifamily CO", "2018-2024") == "Net multifamily CO per 1000 pop (2018-2024)"
        assert _housing_rate_axis_label("Net multifamily CO", "") == "Net multifamily CO per 1000 pop"
        assert _housing_rate_axis_label("Net multifamily CO") == "Net multifamily CO per 1000 pop"


if __name__ == "__main__":
    unittest.main()
