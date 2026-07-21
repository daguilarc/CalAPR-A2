from pathlib import Path
import sys
import unittest

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "TableA2-models"
sys.path.insert(0, str(MODELS))

from acs_apr_models import HOLDOUT_MODULUS, holdout_dropped, apply_randhash_holdout


class RandhashHoldoutTests(unittest.TestCase):
    def test_randhash_holdout_drops_modulus_zero_ids(self):
        df = pd.DataFrame({"JURISDICTION": [f"J{i}" for i in range(200)], "v": range(200)})
        kept = apply_randhash_holdout(df, "JURISDICTION", HOLDOUT_MODULUS)
        ratio = len(kept) / len(df)
        assert abs(ratio - 0.8) < 0.12, ratio
        assert all(not holdout_dropped(j, HOLDOUT_MODULUS) for j in kept["JURISDICTION"])
        assert holdout_dropped("J0", HOLDOUT_MODULUS) == holdout_dropped("J0", HOLDOUT_MODULUS)
        # must not mutate input
        assert len(df) == 200


if __name__ == "__main__":
    unittest.main()
