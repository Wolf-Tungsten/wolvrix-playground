"""Validate the memory cap contract without launching allocations or services."""

import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import run_resource_capped as cap


WORK = Path(__file__).resolve().parents[1] / "ptmp/firrtl-ingest/F24/memory-audit/tests"
WORK.mkdir(parents=True, exist_ok=True)


class ResourceCapTests(unittest.TestCase):
    def test_enforcement_needs_separate_group_and_exact_limits(self):
        data = {"path": "/user/app/x.service", "memory.max": 4096,
                "memory.swap.max": 0, "memory.oom.group": 1}
        self.assertTrue(cap.valid_enforcement(data, 4096, "/user/tmux.scope"))
        for key, value in (("path", "/user/tmux.scope"),
                           ("path", "/user/tmux.scope/nested"),
                           ("memory.max", "max"), ("memory.max", 8192),
                           ("memory.swap.max", "max"), ("memory.oom.group", 0)):
            with self.subTest(key=key, value=value):
                self.assertFalse(cap.valid_enforcement({**data, key: value}, 4096, "/user/tmux.scope"))

    def test_environment_keeps_overrides_but_removes_closed_jobserver(self):
        original = {"MAKEFLAGS": " -j24 --jobserver-auth=3,4 -- VAR=a\\ b", "MFLAGS": "-j --jobserver-fds=5,6", "PATH": "test", "SECRET": "opaque"}
        result = cap.service_environment(original)
        self.assertEqual(result["MAKEFLAGS"], "-j24 -- VAR=a\\ b")
        self.assertEqual(result["MFLAGS"], "-j")
        self.assertEqual(result["SECRET"], original["SECRET"])
        self.assertIn("--jobserver-auth", original["MAKEFLAGS"])

    def test_service_properties_cover_entire_tree_and_verify_before_start(self):
        arguments = cap.make_command(["make", "-j1", "run"], "x.service", 123,
                                     Path("/output/report.json"), "/parent", {"PATH": "secret-path", "TOKEN": "secret-token"})
        for argument in ("--user", "--wait", "--pipe", "--expand-environment=no",
                         "--property=MemoryMax=123", "--property=MemorySwapMax=0",
                         "--property=OOMPolicy=kill", "--property=KillMode=control-group",
                         "--setenv=PATH", "--setenv=TOKEN"):
            self.assertIn(argument, arguments)
        self.assertTrue(any(a.startswith("--property=ExecStartPre=:") for a in arguments))
        self.assertTrue(any(a.startswith("--property=ExecStopPost=:") for a in arguments))
        self.assertNotIn("secret-token", " ".join(arguments))
        self.assertEqual(arguments[-4:], ["--", "make", "-j1", "run"])
        self.assertFalse(any(a.startswith("--property=RuntimeMaxSec=") for a in arguments))
        self.assertNotIn("--property=KillSignal=SIGKILL", arguments)

    def test_optional_deadline_kills_all_service_process_groups(self):
        arguments = cap.make_command(["make", "-j1", "run"], "x.service", 123,
                                     Path("/output/report.json"), "/parent", {}, 330)
        for argument in ("--property=RuntimeMaxSec=330s", "--property=RuntimeRandomizedExtraSec=0",
                         "--property=KillSignal=SIGKILL", "--property=SendSIGKILL=yes",
                         "--property=KillMode=control-group"):
            self.assertIn(argument, arguments)
        self.assertEqual(arguments[-4:], ["--", "make", "-j1", "run"])

    def test_nonpositive_deadline_never_launches_workload(self):
        for value in ("0", "-1"):
            with self.subTest(value=value), \
                 mock.patch("sys.argv", ["run_resource_capped.py", "--memory-max-bytes", "123",
                            "--runtime-max-seconds", value, "--output", "unused", "--", "must-not-run"]), \
                 mock.patch("sys.stderr", new_callable=io.StringIO), \
                 mock.patch.object(cap, "run") as launch:
                with self.assertRaises(SystemExit) as error:
                    cap.main()
                self.assertEqual(error.exception.code, 2)
                launch.assert_not_called()

    def test_systemd_arguments_do_not_expand_specifiers_or_shell(self):
        value = cap.exec_property(["/test tool", "a%b", 'a"b', r"a\b", "$HOME", "$(false)"])
        self.assertEqual(value, ':"/test tool" "a%%b" "a\\"b" "a\\\\b" "$HOME" "$(false)"')
        with self.assertRaises(ValueError):
            cap.exec_property(["invalid\nargument"])

    def test_manager_failure_never_launches_workload(self):
        with tempfile.TemporaryDirectory(dir=WORK) as directory:
            output = Path(directory) / "report.json"
            with mock.patch.object(cap, "unified_cgroup", return_value="/parent"), \
                 mock.patch.object(cap, "control", return_value=subprocess.CompletedProcess([], 1, "", "denied")), \
                 mock.patch.object(cap.subprocess, "run") as launch:
                self.assertEqual(cap.run(["must-not-run"], 123, output), 125)
            launch.assert_not_called()
            report = json.loads(output.read_text())
            self.assertFalse(report["enforcement_verified"])
            self.assertEqual(report["status"], "failed")
            self.assertIn("unavailable", report["error"])

    def test_missing_final_evidence_refuses_success(self):
        with tempfile.TemporaryDirectory(dir=WORK) as directory:
            output = Path(directory) / "report.json"
            stale = {"enforcement_verified": True, "unit": "old.service", "cgroup": {"path": "/old.service"}}
            cap.write_json(Path(str(output) + ".start.json"), stale)
            cap.write_json(Path(str(output) + ".stop.json"), stale)
            with mock.patch.object(cap, "unified_cgroup", return_value="/parent"), \
                 mock.patch.object(cap, "control", return_value=subprocess.CompletedProcess([], 0, "", "")), \
                 mock.patch.object(cap.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
                self.assertEqual(cap.run(["true"], 123, output), 125)
            self.assertFalse(json.loads(output.read_text())["enforcement_verified"])
            self.assertFalse(Path(str(output) + ".start.json").exists())
            self.assertFalse(Path(str(output) + ".stop.json").exists())

    def test_final_cgroup_result_survives_unloaded_service(self):
        with tempfile.TemporaryDirectory(dir=WORK) as directory:
            output = Path(directory) / "report.json"
            def launch(arguments, **kwargs):
                unit = next(arg.split("=", 1)[1] for arg in arguments if arg.startswith("--unit="))
                data = {"enforcement_verified": True, "unit": unit,
                        "cgroup": {"path": "/" + unit, "memory.peak": 100}}
                cap.write_json(Path(str(output) + ".start.json"), data)
                cap.write_json(Path(str(output) + ".stop.json"), {**data, "service_result": "oom-kill", "exit_code": "killed", "exit_status": "KILL"})
                return subprocess.CompletedProcess([], 137)
            with mock.patch.object(cap, "unified_cgroup", return_value="/parent"), \
                 mock.patch.object(cap, "control", return_value=subprocess.CompletedProcess([], 0, "", "")), \
                 mock.patch.object(cap.subprocess, "run", side_effect=launch):
                self.assertEqual(cap.run(["capped-child"], 123, output), 137)
            report = json.loads(output.read_text())
            self.assertTrue(report["enforcement_verified"])
            self.assertEqual(report["result"], "oom-kill")
            self.assertEqual(report["memory_peak_bytes"], 100)
            self.assertEqual(report["returncode"], 137)

    def test_start_verifier_does_not_allow_work_on_bad_cap(self):
        with tempfile.TemporaryDirectory(dir=WORK) as directory:
            output = Path(directory) / "start.json"
            with mock.patch.object(cap, "read_cgroup", return_value={"path": "/parent", "memory.max": "max"}):
                self.assertEqual(cap.collect(output, 123, "/parent", True), 125)
            self.assertFalse(json.loads(output.read_text())["enforcement_verified"])

    def test_deadline_failure_keeps_recorder_and_final_evidence(self):
        with tempfile.TemporaryDirectory(dir=WORK) as directory:
            output = Path(directory) / "report.json"
            def launch(arguments, **kwargs):
                self.assertIn("--property=RuntimeMaxSec=330s", arguments)
                self.assertIn("--property=KillSignal=SIGKILL", arguments)
                unit = next(arg.split("=", 1)[1] for arg in arguments if arg.startswith("--unit="))
                data = {"enforcement_verified": True, "unit": unit,
                        "cgroup": {"path": "/" + unit, "memory.peak": 100}}
                cap.write_json(Path(str(output) + ".start.json"), data)
                cap.write_json(Path(str(output) + ".stop.json"), {**data, "service_result": "timeout",
                               "exit_code": "killed", "exit_status": "KILL"})
                return subprocess.CompletedProcess([], 137)
            with mock.patch.object(cap, "unified_cgroup", return_value="/parent"), \
                 mock.patch.object(cap, "control", return_value=subprocess.CompletedProcess([], 0, "", "")), \
                 mock.patch.object(cap.subprocess, "run", side_effect=launch):
                self.assertEqual(cap.run(["capped-child"], 123, output, 330), 137)
            report = json.loads(output.read_text())
            self.assertEqual(report["runtime_max_seconds"], 330)
            self.assertTrue(report["enforcement_verified"])
            self.assertEqual(report["result"], "timeout")
            self.assertEqual(report["exec_main_status"], "KILL")
            self.assertEqual(report["status"], "failed")


if __name__ == "__main__":
    unittest.main()
