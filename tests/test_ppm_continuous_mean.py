import numpy as np
import sys, pathlib
import unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "TableA2-models"))
from pages.chart_prep import build_mle_ci


class TestPPMContinuousMean(unittest.TestCase):
    def test_continuous_bayes_mean_is_posterior_mean_not_mle_line(self):
        result = {
            "intercept_mle": 1.0, "slope_mle": 2.0,
            "alpha_mle": 0.0, "beta_mle": 0.0,
            "x_transform": None,
            "mle_result": {"model_family": "continuous"},
            "intercept_samples": np.array([1.0, 1.0, 1.0]),
            "slope_samples": np.array([2.5, 3.0, 3.5]),   # posterior-mean slope 3.0 != MLE slope 2.0
            # no alpha/beta samples -> continuous branch
        }
        x_range_raw = np.array([0.0, 1.0, 2.0])
        mle_y, _blo, _bhi, _clo, _chi, bayes_mean = build_mle_ci(result, x_range_raw)
        # MLE line = 1 + 2x = [1,3,5]; posterior mean = 1 + 3x = [1,4,7]
        np.testing.assert_allclose(mle_y, [1.0, 3.0, 5.0])
        np.testing.assert_allclose(bayes_mean, [1.0, 4.0, 7.0], rtol=1e-9)
        assert not np.allclose(bayes_mean, mle_y)   # distinct from the OLS line

    def test_two_part_partial_sample_keeps_mle_line(self):
        result = {
            "intercept_mle": 1.0, "slope_mle": 2.0,
            "alpha_mle": 0.5, "beta_mle": 0.3,          # real hurdle -> psi != 1
            "x_transform": None,
            "mle_result": {"model_family": "two_part"},  # NOT continuous
            "intercept_samples": np.array([1.0, 1.0, 1.0]),
            "slope_samples": np.array([2.5, 3.0, 3.5]),
            # no alpha/beta samples -> hits the same elif branch
        }
        x_range_raw = np.array([0.0, 1.0, 2.0])
        mle_y, _blo, _bhi, _clo, _chi, bayes_mean = build_mle_ci(result, x_range_raw)
        np.testing.assert_allclose(bayes_mean, mle_y)   # housing behavior preserved


if __name__ == "__main__":
    unittest.main()
