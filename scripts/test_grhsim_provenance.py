"""Generation provenance must distinguish dirty sources and checkpoint reemits."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from grhsim_provenance import ROOT, capture_generation, file_identity, source_identity, write_identity


class ProvenanceTest(unittest.TestCase):
    def test_dirty_untracked_deleted_sources(self):
        work = ROOT / "ptmp/remove-grhsim-ir"
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="provenance-", dir=work) as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "scripts/a.py").write_text("original\n")
            (root / "Makefile").write_text("all:\n")
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "add", "Makefile", "scripts/a.py"], check=True)
            original = subprocess.check_output
            def command(args, **kwargs):
                if args[-2:] == ["rev-parse", "HEAD"]:
                    return "fixture-head\n"
                return original(args, **kwargs)
            with mock.patch("grhsim_provenance.subprocess.check_output", side_effect=command):
                initial = source_identity(root)
                self.assertEqual(initial, source_identity(root))
                (root / "scripts/a.py").write_text("dirty\n")
                changed = source_identity(root)
                self.assertNotEqual(initial["sha256"], changed["sha256"])
                (root / "scripts/new.py").write_text("new\n")
                self.assertIn("scripts/new.py", source_identity(root)["files_sha256"])
                (root / "scripts/a.py").unlink()
                self.assertIsNone(source_identity(root)["files_sha256"]["scripts/a.py"])

    def test_generation_and_publication(self):
        work = ROOT / "ptmp/remove-grhsim-ir"
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="provenance-", dir=work) as directory:
            path = Path(directory) / "graph.json"
            path.write_text("{}")
            with mock.patch("grhsim_provenance.source_identity", return_value={"sha256": "source"}), \
                 mock.patch("grhsim_provenance.loaded_libraries", return_value=[{"sha256": "binary"}]):
                identity = capture_generation("checkpoint-reemit", inputs={"checkpoint": path},
                                              configuration={"function_budget": 16})
            self.assertEqual(identity["inputs"]["checkpoint"], file_identity(path))
            self.assertEqual(identity["kind"], "checkpoint-reemit")
            target = Path(directory) / "nested/identity.json"
            write_identity(target, identity)
            self.assertEqual(json.loads(target.read_text()), identity)
            self.assertFalse(target.with_name("identity.json.pending").exists())

if __name__ == "__main__":
    unittest.main()
