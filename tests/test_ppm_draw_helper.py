import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import sys, pathlib
import unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "TableA2-models"))
from acs_apr_models import _draw_ppm_line


class PpmDrawHelperTests(unittest.TestCase):
    def test_draw_ppm_line_present_and_absent(self):
        fig, ax = plt.subplots()
        x = np.array([0.0, 1.0, 2.0]); ym = np.array([1.0, 4.0, 7.0])
        h = _draw_ppm_line(ax, x, ym, 3.0)
        assert h is not None
        assert "Posterior Predictive Mean" in h.get_label()
        assert _draw_ppm_line(ax, x, None, None) is None   # absent when no bayes_mean
        plt.close(fig)


if __name__ == "__main__":
    unittest.main()
