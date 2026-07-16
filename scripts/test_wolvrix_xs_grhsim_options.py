#!/usr/bin/env python3

import os
import runpy
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("wolvrix_xs_grhsim.py")
MODULE = runpy.run_path(str(SCRIPT), run_name="wolvrix_xs_grhsim_option_test")
ENV_OPTIONAL_FLAG = MODULE["env_optional_flag"]
FORMAT_OPTIONAL_FLAG = MODULE["format_optional_flag"]
READ_FINAL_SIBLING_FUSION_OPTIONS = MODULE["read_final_sibling_fusion_options"]
FORMAT_NATIVE_DEFAULT_OPTION = MODULE["format_native_default_option"]


class XsGrhsimOptionTest(unittest.TestCase):
    def check_option(self, stem: str) -> None:
        high = f"WOLVRIX_XS_GRHSIM_{stem}"
        low = f"WOLVRIX_GRHSIM_{stem}"
        base = {key: value for key, value in os.environ.items() if key not in {high, low}}

        with patch.dict(os.environ, base, clear=True):
            before = dict(os.environ)
            self.assertIsNone(ENV_OPTIONAL_FLAG(high, low))
            self.assertEqual(os.environ, before)

        with patch.dict(os.environ, {**base, low: "0"}, clear=True):
            self.assertIs(ENV_OPTIONAL_FLAG(high, low), False)

        with patch.dict(os.environ, {**base, low: ""}, clear=True):
            self.assertIs(ENV_OPTIONAL_FLAG(high, low), True)

        with patch.dict(os.environ, {**base, low: "0", high: "1"}, clear=True):
            self.assertIs(ENV_OPTIONAL_FLAG(high, low), True)

        with patch.dict(os.environ, {**base, low: "0", high: ""}, clear=True):
            self.assertIs(ENV_OPTIONAL_FLAG(high, low), True)

        with patch.dict(os.environ, {**base, low: "1", high: "0"}, clear=True):
            before = dict(os.environ)
            self.assertIs(ENV_OPTIONAL_FLAG(high, low), False)
            self.assertEqual(os.environ, before)

    def test_direct_override_precedence(self) -> None:
        self.check_option("DIRECT_SINGLE_WRITER_STATE_READS")

    def test_pure_event_override_precedence(self) -> None:
        self.check_option("PURE_EVENT_COMPUTE_WORD_BYPASS")

    def test_log_value_distinguishes_cpp_default(self) -> None:
        self.assertEqual(FORMAT_OPTIONAL_FLAG(None), "cpp-default")
        self.assertEqual(FORMAT_OPTIONAL_FLAG(False), "False")
        self.assertEqual(FORMAT_OPTIONAL_FLAG(True), "True")

    def test_final_sibling_fusion_defaults(self) -> None:
        names = {
            "WOLVRIX_XS_GRHSIM_FINAL_SIBLING_FUSION_POLICY",
            "WOLVRIX_XS_GRHSIM_FINAL_SIBLING_FUSION_MIN_GAIN",
            "WOLVRIX_XS_GRHSIM_FINAL_SIBLING_FUSION_MAX_PAIRS",
            "WOLVRIX_XS_GRHSIM_FINAL_SIBLING_FUSION_MAX_FUSED_OP_PPM",
        }
        base = {key: value for key, value in os.environ.items() if key not in names}
        with patch.dict(os.environ, base, clear=True):
            options = READ_FINAL_SIBLING_FUSION_OPTIONS()
            self.assertEqual(options, {})
            for name in (
                "final_sibling_fusion_policy",
                "final_sibling_fusion_min_gain",
                "final_sibling_fusion_max_pairs",
                "final_sibling_fusion_max_fused_op_ppm",
            ):
                with self.subTest(name=name):
                    self.assertEqual(FORMAT_NATIVE_DEFAULT_OPTION(options, name), "cpp-default")

    def test_final_sibling_fusion_explicit_values(self) -> None:
        values = {
            "WOLVRIX_XS_GRHSIM_FINAL_SIBLING_FUSION_POLICY": "probe",
            "WOLVRIX_XS_GRHSIM_FINAL_SIBLING_FUSION_MIN_GAIN": "7",
            "WOLVRIX_XS_GRHSIM_FINAL_SIBLING_FUSION_MAX_PAIRS": "19",
            "WOLVRIX_XS_GRHSIM_FINAL_SIBLING_FUSION_MAX_FUSED_OP_PPM": "2300",
        }
        with patch.dict(os.environ, values, clear=True):
            self.assertEqual(
                READ_FINAL_SIBLING_FUSION_OPTIONS(),
                {
                    "final_sibling_fusion_policy": "probe",
                    "final_sibling_fusion_min_gain": 7,
                    "final_sibling_fusion_max_pairs": 19,
                    "final_sibling_fusion_max_fused_op_ppm": 2300,
                },
            )

    def test_final_sibling_fusion_values_are_independent(self) -> None:
        cases = (
            (
                "WOLVRIX_XS_GRHSIM_FINAL_SIBLING_FUSION_POLICY",
                "probe",
                "final_sibling_fusion_policy",
                "probe",
            ),
            (
                "WOLVRIX_XS_GRHSIM_FINAL_SIBLING_FUSION_MIN_GAIN",
                "7",
                "final_sibling_fusion_min_gain",
                7,
            ),
            (
                "WOLVRIX_XS_GRHSIM_FINAL_SIBLING_FUSION_MAX_PAIRS",
                "19",
                "final_sibling_fusion_max_pairs",
                19,
            ),
            (
                "WOLVRIX_XS_GRHSIM_FINAL_SIBLING_FUSION_MAX_FUSED_OP_PPM",
                "2300",
                "final_sibling_fusion_max_fused_op_ppm",
                2300,
            ),
        )
        for env_name, env_value, option_name, option_value in cases:
            with self.subTest(env_name=env_name):
                with patch.dict(os.environ, {env_name: env_value}, clear=True):
                    options = READ_FINAL_SIBLING_FUSION_OPTIONS()
                    self.assertEqual(options, {option_name: option_value})
                    self.assertEqual(
                        FORMAT_NATIVE_DEFAULT_OPTION(options, option_name),
                        str(option_value),
                    )


if __name__ == "__main__":
    unittest.main()
