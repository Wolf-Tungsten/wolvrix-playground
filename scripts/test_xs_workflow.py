"""Check that the XS Make entry points cannot select scalarized RTL."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class XsWorkflowTests(unittest.TestCase):
    def make(self, *args):
        env = {**os.environ, "WOLF_ENV_SOURCED": "1"}
        env.pop("MAKEFLAGS", None)
        return subprocess.run(
            ["make", "--no-print-directory", *args], cwd=ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False,
        )

    def test_scalar_override_is_rejected(self):
        result = self.make("-n", "xs_rtl", "XS_PRESERVE_AGGREGATE=none")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("requires preserve-aggregate=all", result.stdout)

    def test_existing_rtl_must_have_successful_aggregate_record(self):
        (ROOT / "ptmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="xs-workflow-", dir=ROOT / "ptmp") as work:
            build = Path(work)
            (build / "rtl").mkdir()
            (build / "rtl/SimTop.sv").write_text("module SimTop; endmodule\n")
            for mode, status, accepted in (
                ("none", 0, False), ("all-extra", 0, False),
                ("all", 1, False), ("all", 0, True),
            ):
                with self.subTest(mode=mode, status=status):
                    (build / "time.log").write_text(
                        f'Command being timed: "firtool --preserve-aggregate={mode}"\n'
                        f"Exit status: {status}\n"
                    )
                    result = self.make("check_xs_aggregate_rtl", f"XS_RTL_BUILD={build}")
                    self.assertEqual(result.returncode == 0, accepted, result.stdout)

    def test_retired_targets_are_absent(self):
        for target in (
            "xs_wolf_emit", "xs_wolf_emu", "run_xs_wolf_emu", "run_xs_json_test",
            "run_xs_diff", "xs_diff_clean", "run_xs_repcut",
            "run_xs_repcut_partitioned_smoke", "build_xs_repcut_verilator",
            "run_xs_repcut_verilator", "xs_rtl_aggregate", "xs_wolf_grhsim_ir_aggregate",
            "xs_wolf_grhsim_ir_aggregate_emu", "xs_wolf_grhsim_ir_aggregate_reemit",
            "xs_wolf_grhsim_ir_aggregate_build_emu", "run_xs_wolf_grhsim_ir_aggregate_emu",
        ):
            with self.subTest(target=target):
                result = self.make("-n", target)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("No rule to make target", result.stdout)
