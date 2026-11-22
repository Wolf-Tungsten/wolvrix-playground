"""Exercise collection, policy selection and model identity without a XiangShan build."""
import gzip
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from grhsim_change_sites import ChangeSites


class SiteProfileTest(unittest.TestCase):
    def test_count_and_select(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "model.cpp"
            source.write_text("""int main() {
                for (int i = 0; i < 1000; ++i) {
#ifdef GRHSIM_COUNT_SITE
                    GRHSIM_COUNT_SITE(V, 3, i == 0);
                    GRHSIM_COUNT_SITE(R, 3, i % 2);
#endif
#ifdef GRHSIM_SPARSE_3
                    return 1;
#endif
#ifdef GRHSIM_EAGER_3
                    return 2;
#endif
                }
            }
""")
            fresh = root / "fresh"
            fresh.mkdir()
            shutil.copy(source, fresh)
            sites = ChangeSites(root, root)
            sites.instrument()
            exe = root / "model"
            subprocess.run(["c++", "-std=c++20", source, "-o", exe], check=True)
            subprocess.run([exe], check=True)
            profile = root / "profile.gz"
            sites.collect(profile, 1000)
            self.assertIn("SPARSE 3 1000 1", gzip.decompress(profile.read_bytes()).decode())
            replay = ChangeSites(fresh, root)
            self.assertEqual(replay.specialize(profile, "both", 1), {"SPARSE": 1, "EAGER": 1})
            self.assertEqual(replay.specialize(profile, "sparse", 0), {"SPARSE": 0, "EAGER": 0})
            self.assertEqual(replay.specialize(profile, "commit", 0), {"SPARSE": 0, "EAGER": 1})
            self.assertEqual(replay.header(fresh / source.name).read_text(), "#define GRHSIM_EAGER_3 1\n")
            other = root / "different"
            other.mkdir()
            (other / source.name).write_text((fresh / source.name).read_text() + "// another model\n")
            with self.assertRaisesRegex(ValueError, "does not match"):
                ChangeSites(other, root).specialize(profile, "both", 5)


if __name__ == "__main__":
    unittest.main()
