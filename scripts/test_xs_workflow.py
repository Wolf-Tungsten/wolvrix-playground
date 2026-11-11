"""Check default reference SV and aggregate simulation backend entry points."""

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

    def test_reference_rtl_uses_default_generation(self):
        (ROOT / "ptmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="xs-reference-", dir=ROOT / "ptmp") as work:
            build = Path(work)
            xs = build / "xiangshan"
            xs.mkdir()
            (xs / "Makefile").write_text(""".PHONY: sim-verilog
sim-verilog:
	@test -z '$(PRESERVE_AGGREGATE)'
	@mkdir -p '$(BUILD_DIR)/rtl'
	@printf 'module SimTop; endmodule\\n' > '$(BUILD_DIR)/rtl/SimTop.sv'
	@printf 'firtool -O=release\\nExit status: 0\\n' > '$(BUILD_DIR)/time.log'
""")
            result = self.make("xs_ref_rtl", f"XS_ROOT={xs}",
                f"XS_WORK_BASE={build / 'outputs'}", f"XS_LOG_DIR={build / 'logs'}",
                "PRESERVE_AGGREGATE=all")
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertTrue((build / "outputs/ref-rtl/rtl/SimTop.sv").is_file())
            self.assertFalse((build / "outputs/rtl/rtl/SimTop.sv").exists())

    def test_reference_rtl_rejects_aggregate_generation(self):
        (ROOT / "ptmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="xs-reference-", dir=ROOT / "ptmp") as work:
            build = Path(work)
            (build / "rtl").mkdir()
            (build / "rtl/SimTop.sv").write_text("module SimTop; endmodule\n")
            for flags, status, accepted in (
                ("", 0, True), ("--preserve-aggregate=all", 0, False),
                ("--preserve-aggregate=none", 0, False), ("", 1, False),
            ):
                with self.subTest(flags=flags, status=status):
                    (build / "time.log").write_text(
                        f'Command being timed: "firtool {flags}"\nExit status: {status}\n')
                    result = self.make("check_xs_ref_rtl", f"XS_REF_RTL_BUILD={build}")
                    self.assertEqual(result.returncode == 0, accepted, result.stdout)

    def test_reference_builder_keeps_upstream_verilator_defaults(self):
        (ROOT / "ptmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="xs-reference-", dir=ROOT / "ptmp") as work:
            build = Path(work)
            xs = build / "xiangshan"
            harness = xs / "difftest"
            harness.mkdir(parents=True)
            generated = xs / "build/generated-src"
            generated.mkdir(parents=True)
            (generated / "DifftestMacros.svh").write_text("// mock macros\n")
            rtl = build / "reference-rtl"
            (rtl / "rtl").mkdir(parents=True)
            (rtl / "rtl/SimTop.sv").write_text("module SimTop; endmodule\n")
            (rtl / "time.log").write_text("firtool -O=release\nExit status: 0\n")
            (harness / "Makefile").write_text("""SIM_VFLAGS += +define+DIFFTEST
EMU_THREADS ?= 0
EMU_OPTIMIZE ?= -O3
EMU_RANDOMIZE ?= 0
.PHONY: emu
emu:
	@test '$(origin SIM_VFLAGS)' = file
	@test '$(SIM_VFLAGS)' = '+define+DIFFTEST'
	@test '$(origin EMU_THREADS)' = file
	@test '$(EMU_THREADS)' = 0
	@test '$(origin EMU_OPTIMIZE)' = file
	@test '$(EMU_OPTIMIZE)' = '-O3'
	@test '$(origin EMU_RANDOMIZE)' = file
	@test '$(EMU_RANDOMIZE)' = 0
""" + f"\t@test '$(SIM_TOP_V)' = '{rtl / 'rtl/SimTop.sv'}'\n"
                + f"\t@test '$(RTL_DIR)' = '{rtl / 'rtl'}'\n")
            result = self.make("xs_ref_emu", f"XS_ROOT={xs}",
                f"XS_REF_RTL_BUILD={rtl}", f"XS_REF_BUILD={build / 'reference-emu'}",
                f"XS_LOG_DIR={build / 'logs'}", "XS_EMU_THREADS=2",
                "XS_SIM_VFLAGS=--language 1800-2005 -Wno-fatal -fno-expand")
            self.assertEqual(result.returncode, 0, result.stdout)

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

    def test_grhsim_ir_aliases_are_absent(self):
        makefile = (ROOT / "Makefile").read_text()
        self.assertNotIn("xs_wolf_grhsim_ir", makefile)
        self.assertNotIn("XS_WOLF_GRHSIM_IR", makefile)
        for target in ("test_grhsim_ir", "run_hdlbits_grhsim_ir", "run_all_hdlbits_grhsim_ir_tests"):
            with self.subTest(target=target):
                result = self.make("-n", target)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("No rule to make target", result.stdout)

    def test_grhsim_emu_uses_current_grhsim_route(self):
        makefile = (ROOT / "Makefile").read_text()
        self.assertIn("XS_GRHSIM_SCRIPT := $(CURDIR)/scripts/wolvrix_xs_grhsim.py", makefile)
        self.assertRegex(makefile, r"(?m)^xs_grhsim_emu: xs_grhsim$")
        self.assertRegex(makefile, r'(?m)^run_xs_grhsim_emu: check_xs_aggregate_rtl$')
        self.assertIn('$(XS_GRHSIM_BUILD_ABS)/emu/emu', makefile)
