import copy
import json
import sys
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from verify_pages_catalog import verify_catalog, VerificationError


class VerifyPipelineShapeTests(unittest.TestCase):
    def setUp(self):
        self.cat = json.loads((ROOT / "docs/data/releases/2018-2024/catalog.json").read_text())

    def _entry(self, predicate):
        return next(copy.deepcopy(v) for v in self.cat.values() if predicate(v))

    def test_below_gate_pair_without_bootstrap_is_accepted(self):
        # a pair whose stationary_bootstrap availability is False must now pass
        e = self._entry(lambda v: v["availability"]["stationary_bootstrap"] is False and v.get("model_family") != "continuous")
        for view in e["views"].values():
            view.pop("stationary_bootstrap", None)   # advertised-iff-present
        verify_catalog({f"{e['geography']}:{e['y_col']}:{e['x_col']}:{e['robustness']}": e})  # no raise

    def test_continuous_new_shape_is_accepted(self):
        # simulate the Task-2 export shape: two_part=None + continuous block
        e = self._entry(lambda v: v.get("model_family") == "continuous")
        old = e["stats"].get("two_part") or {}
        e["stats"]["two_part"] = None
        e["stats"]["continuous"] = {"intercept": old.get("intercept", 0.0), "slope": old.get("slope", 0.0),
                                     "slope_t": old.get("slope_t"), "slope_p": old.get("slope_p")}
        for view in e["views"].values():
            if not e["availability"]["stationary_bootstrap"]:
                view.pop("stationary_bootstrap", None)
        verify_catalog({f"{e['geography']}:{e['y_col']}:{e['x_col']}:{e['robustness']}": e})  # no raise

    def test_still_rejects_nonfinite_continuous_slope(self):
        e = self._entry(lambda v: v.get("model_family") == "continuous")
        e["stats"]["two_part"] = None
        e["stats"]["continuous"] = {"intercept": 1.0, "slope": float("nan"), "slope_t": None, "slope_p": None}
        with self.assertRaises(VerificationError):
            verify_catalog({f"{e['geography']}:{e['y_col']}:{e['x_col']}:{e['robustness']}": e})

    def test_verify_manifest_accepts_below_gate_bootstrap_accounting(self):
        import copy, json
        from verify_pages_catalog import verify_manifest
        manifest = json.loads((ROOT / "docs/data/releases/2018-2024/manifest.json").read_text())
        # one real below-gate pair (bootstrap unavailable) -> passes patched verify_catalog
        e = next(copy.deepcopy(v) for v in self.cat.values()
                 if v["availability"]["stationary_bootstrap"] is False and v.get("model_family") != "continuous")
        for view in e["views"].values():
            view.pop("stationary_bootstrap", None)
        key = f"{e['geography']}:{e['y_col']}:{e['x_col']}:{e['robustness']}"
        catalog = {key: e}
        n_hier = 1 if e["availability"]["hierarchical"] else 0
        manifest["catalog_keys"] = [key]
        manifest["n_regressions"] = 1
        manifest["n_pairs_exported"] = 1
        manifest["n_stationary_bootstrap_succeeded"] = 0     # this pair has no bootstrap
        manifest["n_stationary_bootstrap_failed"] = 1        # informational; must NOT break reconciliation
        manifest["n_pairs_mle_failed"] = 0
        manifest["n_pairs_attempted"] = 1                    # len(catalog)+mle_failed
        manifest["n_hierarchical_succeeded"] = n_hier
        manifest["n_hierarchical_failed"] = 0
        manifest["n_hierarchical_attempted"] = n_hier
        verify_manifest(manifest, catalog)                   # must NOT raise

    def test_verify_manifest_still_rejects_bad_attempt_count(self):
        import copy, json
        from verify_pages_catalog import verify_manifest, VerificationError
        manifest = json.loads((ROOT / "docs/data/releases/2018-2024/manifest.json").read_text())
        e = next(copy.deepcopy(v) for v in self.cat.values()
                 if v["availability"]["stationary_bootstrap"] is False and v.get("model_family") != "continuous")
        for view in e["views"].values():
            view.pop("stationary_bootstrap", None)
        key = f"{e['geography']}:{e['y_col']}:{e['x_col']}:{e['robustness']}"
        catalog = {key: e}
        n_hier = 1 if e["availability"]["hierarchical"] else 0
        manifest.update({"catalog_keys": [key], "n_regressions": 1, "n_pairs_exported": 1,
                         "n_stationary_bootstrap_succeeded": 0, "n_stationary_bootstrap_failed": 1,
                         "n_pairs_mle_failed": 0, "n_pairs_attempted": 999,   # WRONG on purpose
                         "n_hierarchical_succeeded": n_hier, "n_hierarchical_failed": 0,
                         "n_hierarchical_attempted": n_hier})
        with self.assertRaises(VerificationError):
            verify_manifest(manifest, catalog)


if __name__ == "__main__":
    unittest.main()
