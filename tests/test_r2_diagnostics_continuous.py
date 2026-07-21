import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "TableA2-models"
sys.path.insert(0, str(MODELS))

from acs_apr_models import PairFitResult, _append_continuous_r2_diagnostics_row


def _stub():
    return PairFitResult(
        geography="city", y_col="pct_afford_sfrcondo", x_col="TOTAL_MF_CO_total",
        robustness="none", var_suffix="", fit_kind="continuous",
        coeffs={"intercept_mle": 1.0, "slope_mle": 0.5, "alpha_mle": 0.0, "beta_mle": 0.0},
        r2_gate_passed=False,
        r2={"mcfadden_r2": None, "ols_rsquared": 0.016},
        chart_arrays={},
        y_render_meta={"display_label": "Zillow Home Value Index (All Homes)"},
        x_render_meta={"display_label": "Net multifamily CO"},
        mle_diag={"positive_part_t": 1.2, "positive_part_p": 0.23},
    )


class R2DiagnosticsContinuousTests(unittest.TestCase):
    def test_append_continuous_r2_row_nulls_hurdle_fields(self):
        rows = []
        _append_continuous_r2_diagnostics_row(rows, _stub(), "City")
        assert len(rows) == 1
        r = rows[0]
        assert len(r) == 11
        assert r[0] == "Zillow Home Value Index (All Homes) vs Net multifamily CO"
        assert r[1] == "City"
        assert isinstance(r[2], float) and math.isnan(r[2])   # McFadden N/A
        assert abs(r[3] - 0.016) < 1e-9                        # full-sample OLS
        assert abs(r[4] - 0.5) < 1e-9                          # slope
        assert abs(r[5] - 1.2) < 1e-9                          # positive_part_t
        assert all(isinstance(r[i], float) and math.isnan(r[i]) for i in (7, 8, 9, 10))


if __name__ == "__main__":
    unittest.main()
