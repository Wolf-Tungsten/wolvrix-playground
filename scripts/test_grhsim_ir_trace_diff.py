#!/usr/bin/env python3

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import grhsim_ir_trace_diff as trace_diff  # noqa: E402
import gen_grhsim_ir_trace_shim as trace_shim  # noqa: E402


class TraceDiffTests(unittest.TestCase):
    def run_diff(self, golden: str, actual: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as tmp:
            golden_path = Path(tmp) / "golden.trace"
            actual_path = Path(tmp) / "actual.trace"
            golden_path.write_text(golden, encoding="utf-8")
            actual_path.write_text(actual, encoding="utf-8")
            return subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "grhsim_ir_trace_diff.py"),
                    str(golden_path),
                    str(actual_path),
                ],
                capture_output=True,
                text=True,
            )

    def test_identical_traces_pass(self):
        result = self.run_diff("eval 0 a=01 q=0\neval 1 a=02 q=1\n", "eval 0 a=01 q=0\neval 1 a=02 q=1\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("identical: 2 evals", result.stdout)

    def test_first_divergence_reports_port(self):
        result = self.run_diff(
            "eval 0 a=01 q=0\neval 1 a=02 q=1\neval 2 a=03 q=1\n",
            "eval 0 a=01 q=0\neval 1 a=02 q=0\neval 2 a=ff q=0\n",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("first divergence at line 2", result.stdout)
        self.assertIn("q: golden=1 actual=0", result.stdout)
        self.assertNotIn("a=ff", result.stdout)

    def test_length_mismatch_reported(self):
        result = self.run_diff("eval 0 a=01\n", "eval 0 a=01\neval 1 a=02\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("length mismatch", result.stdout)

    def test_parse_line(self):
        head, ports = trace_diff.parse_line("eval 12 a=ff clk=1")
        self.assertEqual(head, "eval 12")
        self.assertEqual(ports, {"a": "ff", "clk": "1"})


HEADER_SAMPLE = """#pragma once
class GrhSIM_top_module {
public:
    bool clk{};
    std::uint8_t data{};
    std::array<std::uint64_t,2> wide{};
    GrhSIM_top_module(){cpu_bind_strings();}
    void init();
    void eval();
private:
    bool cpu_first_eval=true;
};
"""


class TraceShimParseTests(unittest.TestCase):
    def test_parse_ports(self):
        with tempfile.TemporaryDirectory() as tmp:
            header = Path(tmp) / "grhsim_top_module.hpp"
            header.write_text(HEADER_SAMPLE, encoding="utf-8")
            ports, class_name = trace_shim.parse_ports(header, "GrhSIM_top_module")
        self.assertEqual(class_name, "GrhSIM_top_module")
        self.assertEqual(
            ports,
            [("bool", "clk"), ("std::uint8_t", "data"), ("std::array<std::uint64_t,2>", "wide")],
        )

    def test_alias_header_resolves_real_class(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "grhsim_top_module__p_A__0.hpp"
            real.write_text(
                HEADER_SAMPLE.replace("GrhSIM_top_module", "GrhSIM_top_module__p_A__0"),
                encoding="utf-8",
            )
            alias = Path(tmp) / "grhsim_top_module.hpp"
            alias.write_text(
                '#pragma once\n#include "grhsim_top_module__p_A__0.hpp"\n\n'
                "using GrhSIM_top_module = GrhSIM_top_module__p_A__0;\n",
                encoding="utf-8",
            )
            ports, class_name = trace_shim.parse_ports(alias, "GrhSIM_top_module")
        self.assertEqual(class_name, "GrhSIM_top_module__p_A__0")
        self.assertEqual([name for _type, name in ports], ["clk", "data", "wide"])

    def test_unsupported_type_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            header = Path(tmp) / "model.hpp"
            header.write_text(
                "class GrhSIM_m {\npublic:\n    std::string name{};\n    GrhSIM_m(){}\n};\n",
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit):
                trace_shim.parse_ports(header, "GrhSIM_m")

    def test_render_shim_mentions_ports_and_macro(self):
        shim = trace_shim.render_shim(
            "grhsim_top_module.hpp",
            "GrhSIM_top_module",
            "GrhSIM_top_module",
            "GrhSIM_top_moduleTraced",
            [("bool", "clk")],
        )
        self.assertIn('#pragma push_macro("GrhSIM_top_module")', shim)
        self.assertIn('tracePort(stream, "clk", clk);', shim)
        self.assertIn("class GrhSIM_top_moduleTraced : public GrhSIM_top_module {", shim)


if __name__ == "__main__":
    unittest.main()
