import importlib.util, shutil, unittest
from pathlib import Path
import tempfile
ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("export_pages_catalog_t", ROOT / "scripts/export_pages_catalog.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod


class PromoteReplaceTests(unittest.TestCase):
    def _stage(self, base, text):
        s = base / "stage"; s.mkdir(); (s / "catalog.json").write_text(text); return s

    def test_refuses_when_exists_without_force(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); mod.DOCS_RELEASES = tmp / "releases"
            dest = mod.DOCS_RELEASES / mod.RELEASE_ID; dest.mkdir(parents=True); (dest / "catalog.json").write_text("OLD")
            with self.assertRaises(FileExistsError):
                mod.promote_release(self._stage(tmp, "NEW"))

    def test_replace_swaps_and_removes_backup(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); mod.DOCS_RELEASES = tmp / "releases"
            dest = mod.DOCS_RELEASES / mod.RELEASE_ID; dest.mkdir(parents=True); (dest / "catalog.json").write_text("OLD")
            mod.promote_release(self._stage(tmp, "NEW"), replace=True)
            self.assertEqual((dest / "catalog.json").read_text(), "NEW")
            self.assertFalse(dest.with_name(f"{dest.name}.prev").exists())   # backup cleaned up

    def test_replace_restores_old_on_copy_failure(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); mod.DOCS_RELEASES = tmp / "releases"
            dest = mod.DOCS_RELEASES / mod.RELEASE_ID; dest.mkdir(parents=True); (dest / "catalog.json").write_text("OLD")
            missing_stage = tmp / "does_not_exist"   # copytree will raise
            with self.assertRaises(BaseException):
                mod.promote_release(missing_stage, replace=True)
            self.assertTrue(dest.exists() and (dest / "catalog.json").read_text() == "OLD")  # live release restored


if __name__ == "__main__":
    unittest.main()
