import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from benchmark_grhsim_ir import digest, endpoint, main, migration_runtime_summary, native_work_summary, summary


class BenchmarkTests(unittest.TestCase):
    def test_endpoint_requires_difftest_and_complete_matching_run(self):
        log = """Difftest enabled
[CYCLE_LIMIT] cycles=100000 max_cycles=100000
EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80000c0c
Core-0 instrCnt = 240349, cycleCnt = 99996, IPC = 2.403586
Seed=0 Guest cycle spent: 100001
Host time spent: 122471ms
"""
        self.assertEqual(endpoint(log), (240349, 99996, 100001, "0x80000c0c", 122.471))
        for invalid in (log + "difftest mismatch", log.replace("Difftest enabled", ""),
                        log.replace("cycles=100000", "cycles=50000")):
            with self.assertRaises(ValueError):
                endpoint(invalid)

    def test_rank_gate_including_ties(self):
        def results(old, new):
            return [{"mode": mode, "host_s": value} for mode, values in (("old", old), ("new", new))
                    for value in values]
        stats = summary(results([6, 7, 8], [3, 4, 5]))
        self.assertTrue(stats["rank_gate_pass"])
        self.assertEqual(stats["one_sided_exact_p"], 0.05)
        self.assertEqual(stats["cliff_delta"], -1)
        self.assertFalse(summary(results([5, 6, 7], [3, 4, 5]))["rank_gate_pass"])
        self.assertFalse(summary(results([6], [3]))["rank_gate_pass"])

    def test_native_work_uses_guest_cycles_and_keeps_host_separate(self):
        runs = [
            {"mode": mode, "endpoint": [42, 99, 100, "0x123"], "host_s": 999,
             "counts": {"instructions:u": count, "cycles:u": count * 2}}
            for mode, counts in (("old", [1000, 1020, 980]), ("new", [800, 800, 800]))
            for count in counts
        ]
        stats = native_work_summary(runs)
        self.assertAlmostEqual(stats["instruction_reduction_percent"], 20)
        self.assertEqual(stats["old"]["mean_instructions_per_guest_cycle"], 10)
        self.assertAlmostEqual(stats["old"]["sample_sd_instructions_per_guest_cycle"], 0.2)
        self.assertEqual(stats["new"]["instruction_spread_ratio"], 0)
        self.assertEqual(stats["new"]["cpi"], 2)
        self.assertNotIn("host_s", stats["new"])

    @staticmethod
    def migration_rows(new_host=102, new_rss=1040):
        return [{"mode": mode, "host_s": host, "max_rss_kib": rss}
                for mode, host, rss in (("old", 100, 1000), ("new", new_host, new_rss)) for _ in range(3)]

    def test_migration_budget_is_not_the_optimization_rank_gate(self):
        rows = self.migration_rows()
        self.assertFalse(summary(rows)["rank_gate_pass"])
        self.assertTrue(migration_runtime_summary(rows)["accepted"])
        self.assertFalse(migration_runtime_summary(self.migration_rows(new_host=104))["runtime_ok"])
        self.assertFalse(migration_runtime_summary(self.migration_rows(new_rss=1060))["rss_ok"])

    def test_migration_rejects_noise_and_incomplete_or_invalid_samples(self):
        rows = self.migration_rows(new_host=100)
        rows[3]["host_s"], rows[5]["host_s"] = 90, 110
        result = migration_runtime_summary(rows)
        self.assertEqual(result["classification"], "NOISY")
        self.assertFalse(result["accepted"])
        for bad in (self.migration_rows()[:-1],
                    [{**row, "max_rss_kib": 0} for row in self.migration_rows()],
                    [{**row, "host_s": float("nan")} for row in self.migration_rows()]):
            with self.assertRaises(ValueError):
                migration_runtime_summary(bad)
        warmups = [{"mode": mode, "warmup": True, "host_s": 9999, "max_rss_kib": 999999}
                   for mode in ("old", "new")]
        self.assertTrue(migration_runtime_summary(warmups + self.migration_rows())["accepted"])

    def test_migration_runner_warms_both_then_alternates_and_binds_inputs(self):
        work = Path(__file__).resolve().parents[1] / "ptmp/remove-grhsim-ir/benchmark-tests"
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as directory:
            root = Path(directory)
            baseline, old, new, output = (root / "ptmp" / name for name in ("frozen", "old", "new", "results"))
            baseline.mkdir(parents=True)
            for flow in (old, new):
                (flow / "emu").mkdir(parents=True)
                (flow / "emu/emu").write_text(flow.name)
            (new / "model").mkdir()
            (new / "model/generation-identity.json").write_text('{}\n')
            input_dir = root / "testcase/xiangshan/ready-to-run"
            input_dir.mkdir(parents=True)
            inputs = {}
            for name in ("coremark-2-iteration.bin", "riscv64-nemu-interpreter-so"):
                path = input_dir / name
                path.write_text(name)
                inputs[str(path.relative_to(root))] = {"sha256": digest(path)}
            (baseline / "manifest.json").write_text(json.dumps({
                "policy": {"runtime_regression_percent": 3, "generation_compile_rss_percent": 5},
                "artifacts": {"frozen/ptmp/xs/grhsim-ir/emu/grhsim-compile/emu": {"sha256": digest(old / "emu/emu")}}}))
            (baseline / "inputs-supplement.json").write_text(json.dumps({"inputs": inputs}))
            calls = []

            def run(command, **kwargs):
                calls.append(command)
                prefix = next(part.split("=", 1)[1] for part in command if part.startswith("XS_EMU_PREFIX="))
                arguments = shlex.split(prefix)
                timing = Path(arguments[arguments.index("-o") + 1])
                timing.write_text("wall=100.00,exit=0,rss_kib=1000\n")
                kwargs["stdout"].write("Difftest enabled\n[CYCLE_LIMIT] cycles=100000 max_cycles=100000\n"
                                       "EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80000cde\n"
                                       "Core-0 instrCnt = 238535, cycleCnt = 99996\n"
                                       "Seed=0 Guest cycle spent: 100001\nHost time spent: 100000ms\n")
                kwargs["stdout"].flush()
                return SimpleNamespace(poll=lambda: 0, wait=lambda: 0)

            arguments = ["--old", str(old), "--new", str(new), "--output", str(output),
                         "--baseline-seconds", "200", "--cpu", str(min(os.sched_getaffinity(0))),
                         "--migration-baseline", str(baseline), "--no-evict-page-cache"]
            with mock.patch("benchmark_grhsim_ir.subprocess.Popen", side_effect=run), contextlib.redirect_stdout(io.StringIO()):
                main(arguments, root=root)
            self.assertEqual(len(calls), 8)
            modes = [next(part for part in command if part.startswith("XS_GRHSIM_BUILD=")) for command in calls]
            self.assertEqual(modes, [f"XS_GRHSIM_BUILD={flow}" for _ in range(4) for flow in (old, new)])
            results = json.loads((output / "results.json").read_text())
            self.assertEqual([row["warmup"] for row in results], [True, True] + [False] * 6)
            self.assertTrue(json.loads((output / "summary.json").read_text())["migration_runtime"]["accepted"])
            registration = json.loads((output / "preregister.json").read_text())
            self.assertEqual(registration["noise_limit_percent"], 5)
            self.assertEqual(registration["warmup_runs"], 2)
            # A replaced old artifact must fail before the first Make run.
            (old / "emu/emu").write_text("replaced")
            arguments[arguments.index(str(output))] = str(root / "ptmp/rejected")
            with mock.patch("benchmark_grhsim_ir.subprocess.Popen") as process, self.assertRaisesRegex(ValueError, "frozen XS"):
                main(arguments, root=root)
            process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
