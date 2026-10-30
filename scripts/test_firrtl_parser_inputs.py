"""The F03 acceptance gate must reject changed inputs and failed body validation."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

import firrtl_parser_inputs as inputs


ROOT = Path(__file__).resolve().parents[1]
WORK = Path(os.environ.get("FIRRTL_INPUT_TEST_WORK", ROOT / "ptmp/firrtl-ingest/F03/input-gate-tests"))
INSPECTOR = Path(os.environ.get("FIRRTL_INSPECTOR", ROOT / "wolvrix/build/bin/inspect-firrtl"))


class FrozenInputsTest(unittest.TestCase):
    def setUp(self):
        WORK.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=WORK)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "wolvrix/tests/ingest/data/firrtl").mkdir(parents=True)
        self.fir = self.root / "T.fir"
        self.fir.write_text("FIRRTL version 6.0.0\ncircuit T:\n  module T:\n    skip\n")
        (self.root / "wolvrix/tests/ingest/data/firrtl/fixture.fir").write_text(self.fir.read_text())
        (self.root / "T.sv").write_text("module T; endmodule\n")
        (self.root / "filelist.f").write_text("T.sv\n")
        (self.root / "generation.log").write_text("test generation record\n")
        (self.root / "spec.md").write_text("test specification identity\n")
        self.manifest = self.root / "frozen.json"

    def run_gate(self, mode):
        arguments = [mode, "--root", str(self.root), "--firrtl", str(self.fir),
                     "--sv-filelist", str(self.root / "filelist.f"),
                     "--generation-log", str(self.root / "generation.log"),
                     "--spec", str(self.root / "spec.md"), "--inspector", str(INSPECTOR),
                     "--manifest", str(self.manifest), "--work-dir", str(self.root / "work")]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return inputs.main(arguments)

    def test_capture_verify_and_refuse_accidental_recapture(self):
        self.assertEqual(self.run_gate("capture"), 0)
        frozen = self.manifest.read_bytes()
        self.assertEqual(self.run_gate("verify"), 0)
        self.assertEqual(self.run_gate("capture"), 1)
        self.assertEqual(self.manifest.read_bytes(), frozen)

    def test_each_input_kind_is_frozen(self):
        self.assertEqual(self.run_gate("capture"), 0)
        for path in [self.fir, self.root / "T.sv", self.root / "spec.md", self.root / "generation.log",
                     self.root / "wolvrix/tests/ingest/data/firrtl/fixture.fir"]:
            with self.subTest(path=path.name):
                before = path.read_bytes()
                path.write_bytes(before + b"\n")
                self.assertEqual(self.run_gate("verify"), 1)
                path.write_bytes(before)
        (self.root / "new.svh").write_text("`define ADDED 1\n")
        self.assertEqual(self.run_gate("verify"), 1)

    def test_missing_sv_and_changed_results_are_rejected(self):
        self.assertEqual(self.run_gate("capture"), 0)
        frozen = json.loads(self.manifest.read_text())
        frozen["parser"]["validated_modules"] += 1
        self.manifest.write_text(json.dumps(frozen))
        self.assertEqual(self.run_gate("verify"), 1)
        (self.root / "T.sv").unlink()
        self.assertEqual(self.run_gate("verify"), 1)

    def test_body_errors_cannot_produce_a_frozen_success(self):
        self.fir.write_text(self.fir.read_text().replace("skip", "unknown_statement"))
        self.assertEqual(self.run_gate("capture"), 1)
        self.assertFalse(self.manifest.exists())


if __name__ == "__main__":
    unittest.main()
