import contextlib
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import grhsim_perf_search as search


LOG = """Difftest enabled
[CYCLE_LIMIT] cycles=100000 max_cycles=100000
EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80000cde
Core-0 instrCnt = 238535, cycleCnt = 99996, IPC = 2.385445
Seed=0 Guest cycle spent: 100001
Host time spent: HOSTms
"""


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.work = Path(__file__).resolve().parents[1] / "ptmp/grhsim-perf-search-tests"
        self.work.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=self.work)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "ptmp/rtl/rtl").mkdir(parents=True)
        (self.root / "ptmp/rtl/rtl/SimTop.sv").write_text("module SimTop; endmodule\n")
        (self.root / "Makefile").write_text("# fixture\n")
        source = self.root / "wolvrix/lib/emit/example.cpp"
        source.parent.mkdir(parents=True)
        source.write_text("// fixture source\n")
        # The fixture has no git checkout. Exercise the caller's source-identity
        # comparisons with real changing file hashes; provenance has its own tests.
        source_mock = mock.patch.object(search, "source_identity", side_effect=lambda root: search.fingerprints({
            str(path.relative_to(root)): path for path in sorted((root / "wolvrix/lib").rglob("*.cpp"))}))
        source_mock.start()
        self.addCleanup(source_mock.stop)
        compiler_mock = mock.patch.object(search, "compiler_information", return_value={"CC": {"version": "fixture"}})
        compiler_mock.start()
        self.addCleanup(compiler_mock.stop)
        inputs = self.root / "testcase/xiangshan/ready-to-run"
        inputs.mkdir(parents=True)
        for name in search.INPUT_NAMES:
            (inputs / name).write_text(name)
        for mode in ("old", "new"):
            binary = self.root / f"ptmp/{mode}/emu/emu"
            binary.parent.mkdir(parents=True)
            binary.write_text(mode)
            binary.chmod(0o755)

    def test_endpoint_requires_difftest_seed_limit_and_host_ms(self):
        text = LOG.replace("HOST", "12345")
        self.assertEqual(search.parse_endpoint(text)["host_ms"], 12345)
        for invalid in (text.replace("Seed=0", "Seed=1"),
                        text.replace("cycles=100000 max_cycles=100000", "cycles=99999 max_cycles=100000"),
                        text.replace("Difftest enabled", ""), text + "difftest mismatch",
                        text + "Host time spent: 1ms\n", text.replace("12345ms", "0ms")):
            with self.assertRaises(ValueError):
                search.parse_endpoint(invalid)

    def test_endpoint_accepts_original_harness_ten_cycle_limit_lines(self):
        progress = "".join(f"[CYCLE_LIMIT] cycles={cycles} max_cycles=100000\n"
                           for cycles in range(10000, 100001, 10000))
        text = LOG.replace("HOST", "12345").replace(
            "[CYCLE_LIMIT] cycles=100000 max_cycles=100000\n", progress)
        self.assertEqual(search.parse_endpoint(text), {
            "endpoint": [238535, 99996, 100001, "0x80000cde"],
            "host_ms": 12345, "seed": 0, "max_cycles": 100000})
        for invalid in (text.replace("cycles=10000 max_cycles=100000", "cycles=10000 max_cycles=99999"),
                        text.replace("cycles=20000 max_cycles=100000", "cycles=10000 max_cycles=100000"),
                        text.replace("cycles=20000 max_cycles=100000", "cycles=9999 max_cycles=100000"),
                        text.replace("cycles=20000 max_cycles=100000", "cycles=100001 max_cycles=100000"),
                        text.replace("cycles=10000 max_cycles=100000", "cycles=-1 max_cycles=100000"),
                        text.replace("[CYCLE_LIMIT] cycles=100000 max_cycles=100000\n", ""),
                        text + "[CYCLE_LIMIT] cycles=100000 max_cycles=100000\n"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                search.parse_endpoint(invalid)

    def test_process_metadata_rejects_threads_or_affinity_outside_protocol(self):
        binary = self.root / "ptmp/new/emu/emu"
        for threads, allowed, valid in ((1, {2}, True), (2, {2}, False), (1, {3}, False)):
            def read(path, *args, **kwargs):
                return "" if path.name == "children" else f"Threads:\t{threads}\n"
            with mock.patch.object(Path, "read_text", read), \
                    mock.patch.object(Path, "resolve", return_value=binary), \
                    mock.patch.object(search.os, "sched_getaffinity", return_value=allowed):
                if valid:
                    self.assertEqual(search.observe_emu(1, binary, 2),
                                     [{"pid": 1, "threads": 1, "cpus_allowed": [2]}])
                else:
                    with self.assertRaises(ValueError):
                        search.observe_emu(1, binary, 2)

    @staticmethod
    def rows(new, old):
        return [{"mode": mode, "host_ms": value}
                for pair in zip(new, old) for mode, value in zip(("new", "old"), pair)]

    def test_ratio_uses_sum_speedup_and_has_no_pair_rank_noise_gate(self):
        result = search.summarize(self.rows([150, 100, 50], [100, 110, 120]), Decimal("10"))
        self.assertTrue(result["threshold_passed"])
        self.assertEqual(result["speedup_percent"], "10.0")
        self.assertEqual(result["new_sum_ms"], 300)
        self.assertLess(Decimal(result["pair_speedup_percent"][0]), 0)
        self.assertFalse(search.summarize(self.rows([100] * 3, [109] * 3), Decimal("10"))["threshold_passed"])
        self.assertFalse(search.summarize(self.rows([100] * 3, [110] * 3), Decimal("10.000000000001"))["threshold_passed"])
        with self.assertRaises(ValueError):
            search.summarize(list(reversed(self.rows([100] * 3, [120] * 3))), Decimal("10"))

    def arguments(self, action):
        args = [action, "--output", str(self.root / "ptmp/result"),
                "--rtl", str(self.root / "ptmp/rtl/rtl")]
        if action == "benchmark":
            args += ["--old", str(self.root / "ptmp/old"), "--new", str(self.root / "ptmp/new"),
                     "--threshold", "10", "--cpu", str(min(os.sched_getaffinity(0)))]
        return args

    def test_full_build_is_fresh_from_sv_and_default_jobs_32(self):
        calls = []

        def run(command, root, env, directory, **kwargs):
            calls.append((command, env, kwargs))
            binary = directory / "emu/emu"
            binary.parent.mkdir()
            binary.write_text("built")
            binary.chmod(0o755)
            return {"returncode": 0, "wall_s": 2399.9, "terminated_reason": None}

        with mock.patch.object(search, "run_logged", side_effect=run), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(search.main(self.arguments("build"), root=self.root), 0)
        command, env, kwargs = calls[0]
        self.assertIn("xs_grhsim_emu", command)
        self.assertIn("-j32", command)
        self.assertIn("VM_BUILD_JOBS=32", command)
        self.assertIn("XS_GRHSIM_RESUME_FROM_FLAT_GRH_JSON=0", command)
        for key, value in search.FIXED.items():
            self.assertIn(f"{key}={value}", command)
        self.assertEqual(kwargs["timeout_s"], 2400)
        self.assertEqual(env["EMU_THREADS"], "0")
        evidence = json.loads((self.root / "ptmp/result/build.json").read_text())
        self.assertEqual(evidence["inputs_before"], evidence["inputs_after"])
        self.assertEqual(evidence["compilers"]["CC"]["version"], "fixture")
        self.assertEqual(evidence["settings"]["EMU_THREADS"], "0")
        with self.assertRaises(ValueError):
            search.new_output(self.root / "ptmp/result", self.root)

    def test_build_over_budget_fails_even_with_exit_zero(self):
        with mock.patch.object(search, "run_logged", return_value={
                "returncode": 0, "wall_s": 2401, "terminated_reason": None}), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(search.main(self.arguments("build"), root=self.root), 1)
        result = json.loads((self.root / "ptmp/result/build.json").read_text())
        self.assertEqual(result["classification"], "failed")

    def test_build_reenumerates_inputs_and_preserves_python_command_as_one_make_argument(self):
        calls = []

        def run(command, root, env, directory, **kwargs):
            calls.append(command)
            (root / "ptmp/rtl/rtl/new_include.svh").write_text("`define ADDED 1\n")
            binary = directory / "emu/emu"
            binary.parent.mkdir()
            binary.write_text("built")
            binary.chmod(0o755)
            return {"returncode": 0, "wall_s": 100, "terminated_reason": None}

        args = self.arguments("build") + ["--make-var", "PYTHON=/opt/frozen/python -S"]
        with mock.patch.object(search, "run_logged", side_effect=run), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(search.main(args, root=self.root), 1)
        self.assertIn("PYTHON=/opt/frozen/python -S", calls[0])
        result = json.loads((self.root / "ptmp/result/build.json").read_text())
        self.assertNotEqual(result["inputs_before"], result["inputs_after"])
        self.assertIn("ptmp/rtl/rtl/new_include.svh", result["inputs_after"])

    def test_symlink_binary_is_resolved_for_runtime_observer(self):
        for mode in ("new", "old"):
            binary = self.root / f"ptmp/{mode}/emu/emu"
            target = binary.with_name("actual-emu")
            binary.rename(target)
            binary.symlink_to(target.name)
        status, _, result = self.fake_benchmark()
        self.assertEqual(status, 0)
        preregister = json.loads((self.root / "ptmp/result/preregister.json").read_text())
        for mode in ("new", "old"):
            self.assertTrue(preregister["fingerprints_before"][f"binary_{mode}"]["path"].endswith("emu/emu"))

    def test_build_timeout_sends_term_then_kill_to_entire_group(self):
        process = SimpleNamespace(pid=987654, poll=lambda: None,
                                  wait=mock.Mock(side_effect=[subprocess.TimeoutExpired("make", 5), -9]))
        output = self.root / "ptmp/process"
        output.mkdir()
        with mock.patch.object(search.subprocess, "Popen", return_value=process), \
                mock.patch.object(search.time, "monotonic", side_effect=[0, 2400, 2405]), \
                mock.patch.object(search.os, "killpg") as kill:
            result = search.run_logged(["make", "xs_grhsim_emu"], self.root, {}, output, timeout_s=2400)
        self.assertEqual(kill.call_args_list, [mock.call(987654, signal.SIGTERM), mock.call(987654, signal.SIGKILL)])
        self.assertEqual(result["terminated_reason"], "full build exceeded 2400 seconds")

    def fake_benchmark(self, host_times=None, alter=None):
        calls = []
        times = iter(host_times or [100000, 110000] * 3)

        def run(command, root, env, directory, **kwargs):
            calls.append(command)
            (directory / "make.log").write_text(LOG.replace("HOST", str(next(times))))
            if alter:
                alter(len(calls))
            return {"returncode": 0, "wall_s": 999, "terminated_reason": None,
                    "process_observations": [{"threads": 1, "cpus_allowed": [2]}]}

        with mock.patch.object(search, "run_logged", side_effect=run), contextlib.redirect_stdout(io.StringIO()):
            status = search.main(self.arguments("benchmark"), root=self.root)
        return status, calls, json.loads((self.root / "ptmp/result/summary.json").read_text())

    def test_benchmark_six_fixed_runs_original_ms_and_input_hashes(self):
        status, calls, result = self.fake_benchmark()
        self.assertEqual(status, 0)
        self.assertEqual(len(calls), 6)
        for command, mode in zip(calls, search.ORDER):
            self.assertIn(f"XS_GRHSIM_BUILD={self.root / 'ptmp' / mode}", command)
            self.assertIn("XS_SIM_MAX_CYCLE=100000", command)
            self.assertIn("EMU_THREADS=0", command)
            self.assertTrue(any(arg.startswith("XS_EMU_DIFF_ARGS=--diff ") and arg.endswith("-s 0") for arg in command))
            self.assertFalse(any("perf stat" in arg or "time -" in arg for arg in command))
        self.assertEqual(result["old_host_ms"], [110000] * 3)
        self.assertEqual(result["new_host_ms"], [100000] * 3)
        self.assertTrue(result["fingerprints_unchanged"])
        self.assertTrue(result["threshold_passed"])

    def test_valid_below_threshold_is_failed_not_invalid(self):
        status, calls, result = self.fake_benchmark([100000, 109999] * 3)
        self.assertEqual(status, 1)
        self.assertEqual(len(calls), 6)
        self.assertEqual(result["classification"], "failed")

    def test_changed_input_invalidates_entire_group_without_selecting_samples(self):
        def alter(index):
            if index == 2:
                (self.root / "testcase/xiangshan/ready-to-run/coremark-2-iteration.bin").write_text("changed")
        status, calls, result = self.fake_benchmark(alter=alter)
        self.assertEqual(status, 2)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["classification"], "invalid")
        self.assertIn("repeat all six", result["action"])

    def test_added_sv_include_invalidates_group(self):
        def alter(index):
            if index == 2:
                (self.root / "ptmp/rtl/rtl/added.svh").write_text("`define CHANGED 1\n")
        status, calls, result = self.fake_benchmark(alter=alter)
        self.assertEqual(status, 2)
        self.assertEqual(len(calls), 2)
        after = json.loads((self.root / "ptmp/result/fingerprints-after.json").read_text())
        self.assertIn("ptmp/rtl/rtl/added.svh", after)
        self.assertEqual(result["classification"], "invalid")

    def test_modified_native_source_during_last_run_invalidates_all_six(self):
        def alter(index):
            if index == 6:
                (self.root / "wolvrix/lib/emit/example.cpp").write_text("// modified\n")
        status, calls, result = self.fake_benchmark(alter=alter)
        self.assertEqual(status, 2)
        self.assertEqual(len(calls), 6)
        self.assertEqual(result["completed_runs"], 6)
        self.assertIn("source code", result["reason"])
        self.assertEqual(result["classification"], "invalid")

    def test_added_harness_source_invalidates_group(self):
        def alter(index):
            if index == 1:
                source = self.root / "testcase/xiangshan/difftest/src/test/csrc/example.cpp"
                source.parent.mkdir(parents=True)
                source.write_text("// added harness source\n")
        status, calls, result = self.fake_benchmark(alter=alter)
        self.assertEqual(status, 2)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["classification"], "invalid")

    def test_overrides_cannot_enable_pgo_probes_or_resume(self):
        for assignment in ("PGO_CFLAGS=-O3", "WOLVRIX_GRHSIM_PERF=1",
                           "XS_GRHSIM_RESUME_FROM_FLAT_GRH_JSON=1", "CXXFLAGS=-fprofile-use=x",
                           "CXX=clang++ -fcs-profile-generate", "CC=clang -fauto-profile=x",
                           "CXXFLAGS=-fbranch-probabilities", "CXXFLAGS=-fcoverage-mapping"):
            with self.assertRaises(ValueError):
                search.assignments([assignment])
        self.assertEqual(search.assignments(["XS_GRHSIM_MAX_FUNCTION_LINES=2048"]),
                         {"XS_GRHSIM_MAX_FUNCTION_LINES": "2048"})
        for flag in ("-fprofile-use=bad", "-fcs-profile-generate", "-fmemory-profile", "--coverage"):
            with mock.patch.dict(os.environ, {"CXXFLAGS": "-O3 " + flag}):
                with self.assertRaises(ValueError):
                    search.clean_environment()


if __name__ == "__main__":
    unittest.main()
