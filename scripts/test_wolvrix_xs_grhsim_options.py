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


if __name__ == "__main__":
    unittest.main()
