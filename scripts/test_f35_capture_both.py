"""Exercise paired captures for a full circuit, a module, and a frozen reference."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from capture_f35_pipeline import TRACE_FILES, WORK, footer
from f35_gsim_reference import GSIM_BUNDLES
from f35_pass_guard import PASSES


FIXTURE = """FIRRTL version 6.0.0
circuit Example :
  module Child :
    input a : UInt<1>
    output y : UInt<1>
    node n = not(a)
    connect y, n
  module Example :
    input a : UInt<1>
    output y : UInt<1>
    inst child of Child
    connect child.a, a
    connect y, child.y
"""


class F35CaptureBothTests(unittest.TestCase):
    def test_capture_module_full_circuit_and_reuse(self):
        binary = os.environ.get("F35_GSIM_BINARY")
        if not binary:
            self.skipTest("F35_GSIM_BINARY is unset")
        with TemporaryDirectory(dir=WORK, prefix="paired-test-") as temporary:
            directory = Path(temporary)
            source = directory / "Example.fir"
            source.write_text(FIXTURE)
            manifest = directory / "ingest-request.json"
            manifest.write_text(json.dumps({
                "schema": "wolvrix.xs.firrtl-inputs.v1",
                "sources": [{"path": source.name, "language": "firrtl"}],
                "tops": ["Example"],
                "firrtl_options": {"init_policy": "unknown", "invalid_policy": "zero"},
            }))
            command = [sys.executable, str(Path(__file__).with_name("f35_capture_both.py")),
                       "--firrtl", str(source), "--manifest", str(manifest)]

            full = self.capture(command, directory / "full", "--binary", binary)
            self.assertEqual(full["scope"], "full")
            self.assertEqual(full["firrtl"], str(source))
            self.assertFalse(full["reused_gsim_reference"])
            self.assertEqual(len(full["grh"]["passes"][0]["bundles"]), 2)

            module = self.capture(command, directory / "module", "--binary", binary, "--module", "Child")
            self.assertEqual(module["scope"], "module")
            self.assertFalse(module["reused_gsim_reference"])
            self.assertEqual(len(module["grh"]["passes"][0]["bundles"]), 1)
            extraction = json.loads(Path(module["module_extraction"]).read_text())
            self.assertEqual(extraction["modules"], ["Child"])
            self.assertEqual(extraction["source_circuit"], "Example")
            gsim = json.loads(Path(module["gsim"]["summary"]).read_text())
            self.assertEqual(gsim["top"], "Child")
            self.assertEqual(gsim["binary"]["command"][-1], str(directory / "module" / "isolated.fir"))

            rerun = self.capture(command, directory / "module-rerun", "--binary", binary, "--module", "Child")
            self.assertNotEqual(rerun["gsim"]["run_id"], module["gsim"]["run_id"])

            reference = Path(full["gsim"]["summary"]).parent
            conflict = directory / "module-with-reference"
            result = subprocess.run([*command, "--output", str(conflict), "--module", "Child",
                                     "--reference", str(reference)], capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--module requires a fresh GSIM capture", result.stderr)
            self.assertFalse(conflict.exists())

            reused = self.capture(command, directory / "reuse", "--reference", str(reference))
            self.assertTrue(reused["reused_gsim_reference"])
            self.assertEqual(reused["gsim"], full["gsim"])
            self.assertNotEqual(reused["grh"]["run_id"], full["grh"]["run_id"])
            self.assertFalse((directory / "reuse" / "gsim").exists())

            duplicate = subprocess.run([*command, "--output", str(directory / "reuse"),
                                        "--reference", str(reference)],
                                       capture_output=True, text=True, timeout=30)
            self.assertNotEqual(duplicate.returncode, 0)
            self.assertIn("output already exists", duplicate.stderr)
            self.assertEqual(json.loads((directory / "reuse" / "summary.json").read_text()), reused)

    def capture(self, command, output, *extra):
        result = subprocess.run([*command, "--output", str(output), *extra],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        summary = json.loads((output / "summary.json").read_text())
        self.assertTrue(summary["complete"])
        for engine, expected in (("gsim", GSIM_BUNDLES), ("grh", PASSES)):
            passes = summary[engine]["passes"]
            self.assertEqual(tuple(stage["pass"] for stage in passes), expected)
            for stage in passes:
                self.assertTrue(stage["bundles"])
                for directory in map(Path, stage["bundles"]):
                    for filename in TRACE_FILES:
                        self.assertTrue(footer(directory / filename)["complete"])
        return summary
