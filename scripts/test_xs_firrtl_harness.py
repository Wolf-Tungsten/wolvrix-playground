"""Check that shared Chisel output cannot silently replace a frozen harness."""

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from xs_firrtl_harness import make_variable_overrides, parse_configuration, prepare_harness, tool_identities


ROOT = Path(__file__).resolve().parents[1]


class FirrtlHarnessTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "ptmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="firrtl-harness-", dir=ROOT / "ptmp")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.firrtl = self.work / "SimTop.fir"
        self.firrtl.write_text("FIRRTL version 6.0.0\ncircuit SimTop :\n")
        self.generated = self.work / "shared/generated-src"
        self.generated.mkdir(parents=True)
        (self.generated / "difftest-state.h").write_text("#define CORES 1\n")
        (self.generated / "difftest-dpic.cpp").write_text("void original() {}\n")
        (self.generated / "nested").mkdir()
        (self.generated / "nested/profile.json").write_text('{"cores": 1}\n')
        self.xs = self.work / "xs"
        (self.xs / "difftest/config").mkdir(parents=True)
        (self.xs / "difftest/src/test/csrc/grhsim").mkdir(parents=True)
        (self.xs / "Makefile").write_text("# Chisel build\n")
        (self.xs / "difftest/Makefile").write_text("include grhsim.mk\n")
        (self.xs / "difftest/grhsim.mk").write_text("# emu build\n")
        (self.xs / "difftest/config/config.h").write_text("#define CONFIG 1\n")
        (self.xs / "difftest/src/test/csrc/grhsim/grhsim.cpp").write_text("void step() {}\n")
        self.output = self.work / "flow/harness-inputs"
        self.tools = patch("xs_firrtl_harness.tool_identities", return_value={"CXX": {"sha256": "compiler"}})
        self.tools.start()
        self.addCleanup(self.tools.stop)

    def prepare(self, **kwargs):
        return prepare_harness(firrtl=self.firrtl, generated_dir=self.generated,
            xs_root=self.xs, output_dir=self.output, configuration={"NUM_CORES": "1"}, **kwargs)

    def test_shared_sources_overwritten_snapshot_still_reused(self):
        first = self.prepare()
        snapshot_identity = (self.output / "snapshot-identity.json").read_bytes()
        build_stat = (self.output / "build-identity.json").stat()
        (self.generated / "difftest-state.h").write_text("#define CORES 2\n")
        (self.generated / "difftest-dpic.cpp").unlink()
        (self.generated / "replacement.cpp").write_text("void replacement() {}\n")
        second = self.prepare()
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual((self.output / "build-identity.json").stat().st_ino, build_stat.st_ino)
        self.assertEqual((self.output / "build-identity.json").stat().st_mtime_ns, build_stat.st_mtime_ns)
        self.assertEqual((self.output / "snapshot-identity.json").read_bytes(), snapshot_identity)
        self.assertEqual((self.output / "generated-src/difftest-state.h").read_text(), "#define CORES 1\n")
        self.assertTrue((self.output / "generated-src/difftest-dpic.cpp").is_file())
        self.assertTrue((self.output / "generated-src/nested/profile.json").is_file())
        self.assertFalse((self.output / "generated-src/replacement.cpp").exists())

    def test_snapshot_damage_and_extra_file_rejected(self):
        self.prepare()
        header = self.output / "generated-src/difftest-state.h"
        header.write_text("corrupt\n")
        with self.assertRaisesRegex(ValueError, "snapshot files differ"):
            self.prepare()
        header.write_text("#define CORES 1\n")
        (self.output / "generated-src/unrecorded.cpp").write_text("extra\n")
        with self.assertRaisesRegex(ValueError, "snapshot files differ"):
            self.prepare()

    def test_firrtl_change_rejected_refresh_preserves_previous_snapshot(self):
        first = self.prepare()
        self.firrtl.write_text("FIRRTL version 6.0.0\ncircuit Changed :\n")
        with self.assertRaisesRegex(ValueError, "FIRRTL differs"):
            self.prepare()
        (self.generated / "difftest-state.h").write_text("#define CORES 2\n")
        second = self.prepare(refresh=True)
        self.assertNotEqual(first["snapshot_sha256"], second["snapshot_sha256"])
        self.assertEqual((self.output / "generated-src/difftest-state.h").read_text(), "#define CORES 2\n")
        archives = list((self.output / "snapshots").iterdir())
        self.assertEqual(len(archives), 1)
        self.assertEqual((archives[0] / "generated-src/difftest-state.h").read_text(), "#define CORES 1\n")
        self.assertTrue((archives[0] / "snapshot-identity.json").is_file())

    def test_common_source_change_records_new_build_identity(self):
        first = self.prepare()
        (self.xs / "difftest/config/config.h").write_text("#define CONFIG 2\n")
        second = self.prepare()
        self.assertEqual(first["snapshot_sha256"], second["snapshot_sha256"])
        self.assertNotEqual(first["sha256"], second["sha256"])
        self.assertTrue(first["common_harness_matches_capture"])
        self.assertFalse(second["common_harness_matches_capture"])
        self.assertEqual(second["design_compatibility"], "not inferred from build identity")
        self.assertEqual(len(list((self.output / "build-identities").glob("*.json"))), 2)
        current = json.loads((self.output / "build-identity.json").read_text())
        self.assertEqual(current["sha256"], second["sha256"])
        self.assertIn("difftest/src/test/csrc/grhsim/grhsim.cpp", current["common_harness"]["files"])

    def test_missing_generated_header_and_unrecorded_directory_rejected(self):
        (self.generated / "difftest-state.h").unlink()
        with self.assertRaisesRegex(ValueError, "missing generated difftest-state.h"):
            self.prepare()
        (self.output / "generated-src").mkdir(parents=True)
        user_file = self.output / "generated-src/mine.txt"
        user_file.write_text("preserve\n")
        with self.assertRaisesRegex(ValueError, "unrecorded harness directory"):
            self.prepare(refresh=True)
        self.assertEqual(user_file.read_text(), "preserve\n")

    def test_configuration_identity_and_validation(self):
        self.assertEqual(parse_configuration(["NUM_CORES=1", "CXXFLAGS=-O3 -g"]),
                         {"NUM_CORES": "1", "CXXFLAGS": "-O3 -g"})
        for entries in (["NUM_CORES"], ["=1"], ["NUM_CORES=1", "NUM_CORES=2"]):
            with self.assertRaisesRegex(ValueError, "unique configuration"):
                parse_configuration(entries)
        first = self.prepare()
        second = prepare_harness(firrtl=self.firrtl, generated_dir=self.generated,
            xs_root=self.xs, output_dir=self.output, configuration={"NUM_CORES": "2"})
        self.assertNotEqual(first["sha256"], second["sha256"])
        self.assertEqual(first["snapshot_sha256"], second["snapshot_sha256"])

    def test_make_overrides_ignore_scheduling_and_preserve_values(self):
        first = r'-j2 --jobserver-auth=3,4 --output-sync=target -- NO_DIFF=1 PGO_CFLAGS=-fprofile-use=profile\ data SIM_CXXFLAGS=-DNAME="a\ b"'
        second = r'rs -j12 --jobserver-auth=9,10 -- SIM_CXXFLAGS=-DNAME="a\ b" PGO_CFLAGS=-fprofile-use=profile\ data NO_DIFF=1'
        expected = {"NO_DIFF": "1", "PGO_CFLAGS": "-fprofile-use=profile data",
                    "SIM_CXXFLAGS": '-DNAME="a b"'}
        self.assertEqual(make_variable_overrides(first), expected)
        self.assertEqual(make_variable_overrides(second), expected)

    def test_harness_environment_and_make_overrides_change_only_build_identity(self):
        with patch.dict(os.environ, {"MAKEFLAGS": "-j2 -- NO_DIFF=1", "NO_DIFF": "1",
                "PGO_LDFLAGS": "-fprofile-use=first", "FIRRTL_UNRELATED_ENV": "exclude"}):
            first = self.prepare()
            self.assertNotIn("FIRRTL_UNRELATED_ENV", first["environment"])
            with patch.dict(os.environ, {"MAKEFLAGS": "-j8 --jobserver-auth=7,8 -- NO_DIFF=1"}):
                self.assertEqual(first["sha256"], self.prepare()["sha256"])
            with patch.dict(os.environ, {"PGO_LDFLAGS": "-fprofile-use=second"}):
                second = self.prepare()
            with patch.dict(os.environ, {"MAKEFLAGS": "-- NO_DIFF=0", "NO_DIFF": "0"}):
                third = self.prepare()
        self.assertNotEqual(first["sha256"], second["sha256"])
        self.assertNotEqual(first["sha256"], third["sha256"])
        self.assertEqual(first["snapshot_sha256"], second["snapshot_sha256"])
        self.assertEqual(first["snapshot_sha256"], third["snapshot_sha256"])

    def test_actual_make_cli_overrides_are_recorded(self):
        tool = self.work / "identity-tool"
        tool.write_text('#!/bin/sh\nprintf "identity tool 1\\n"\n')
        tool.chmod(0o755)
        makefile = self.work / "capture.mk"
        command = [sys.executable, str(ROOT / "scripts/xs_firrtl_harness.py"),
            "--firrtl", str(self.firrtl), "--generated-dir", str(self.generated),
            "--xs-root", str(self.xs), "--output-dir", str(self.output)]
        makefile.write_text(".PHONY: capture\ncapture:\n\t@" + shlex.join(command) + "\n")
        environment = {**os.environ, "MAKEFLAGS": "", "MFLAGS": "", "MAKEOVERRIDES": "",
                       **{key: str(tool) for key in ("CC", "CXX", "AR", "MAKE")}}

        def capture(arguments):
            result = subprocess.run(["make", "--no-print-directory", "-f", str(makefile),
                "capture", *arguments], cwd=ROOT, env=environment, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(result.returncode, 0, result.stdout)
            return json.loads((self.output / "build-identity.json").read_text())

        first = capture(["-j2", "NO_DIFF=1", "PGO_CFLAGS=-fprofile-use=profile data", 'SIM_CXXFLAGS=-DNAME="a b"'])
        second = capture(["-j3", 'SIM_CXXFLAGS=-DNAME="a b"', "PGO_CFLAGS=-fprofile-use=profile data", "NO_DIFF=0"])
        self.assertEqual(first["make_variable_overrides"]["NO_DIFF"], "1")
        self.assertEqual(second["make_variable_overrides"]["NO_DIFF"], "0")
        self.assertEqual(second["make_variable_overrides"]["PGO_CFLAGS"], "-fprofile-use=profile data")
        self.assertEqual(second["make_variable_overrides"]["SIM_CXXFLAGS"], '-DNAME="a b"')
        self.assertNotEqual(first["sha256"], second["sha256"])
        self.assertEqual(first["snapshot_sha256"], second["snapshot_sha256"])
        before = (self.output / "build-identity.json").stat().st_mtime_ns
        third = capture(["-j4", "NO_DIFF=0", "PGO_CFLAGS=-fprofile-use=profile data", 'SIM_CXXFLAGS=-DNAME="a b"'])
        self.assertEqual(second["sha256"], third["sha256"])
        self.assertEqual(before, (self.output / "build-identity.json").stat().st_mtime_ns)

    def test_tool_executable_identity_and_version(self):
        tool = self.work / "mock-tool"
        tool.write_text('#!/bin/sh\nprintf "mock version 1\\n"\n')
        tool.chmod(0o755)
        configuration = {key: str(tool) for key in ("CC", "CXX", "AR", "MAKE", "PYTHON")}
        first = tool_identities(configuration)
        self.assertEqual(first["CXX"]["version"], "mock version 1")
        self.assertEqual(first["CXX"]["executable"], str(tool.resolve()))
        tool.write_text('#!/bin/sh\nprintf "mock version 2\\n"\n')
        second = tool_identities(configuration)
        self.assertNotEqual(first["CXX"]["sha256"], second["CXX"]["sha256"])
        self.assertEqual(second["CXX"]["version"], "mock version 2")

    def test_damaged_identity_and_recursive_output_rejected(self):
        self.prepare()
        path = self.output / "snapshot-identity.json"
        identity = json.loads(path.read_text())
        identity["generated"]["files"].clear()
        path.write_text(json.dumps(identity))
        with self.assertRaisesRegex(ValueError, "identity is damaged"):
            self.prepare()
        with self.assertRaisesRegex(ValueError, "outside the generated"):
            prepare_harness(firrtl=self.firrtl, generated_dir=self.generated,
                xs_root=self.xs, output_dir=self.generated / "snapshot")


if __name__ == "__main__":
    unittest.main()
