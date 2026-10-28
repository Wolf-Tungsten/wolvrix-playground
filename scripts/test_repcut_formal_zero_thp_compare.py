import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import repcut_formal_zero_thp_compare as thp


class ThpCompareTest(unittest.TestCase):
    def test_actual_compute_addresses_must_satisfy_requested_alignment(self):
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / "emu"
            binary.write_bytes(b"fixture")
            with patch.object(thp.subprocess, "check_output", return_value=(
                    "00000100 T _ZN3foo_eval_compute_batch_0Ev\n"
                    "00000140 T _ZN3foo_eval_compute_batch_1Ev\n")):
                self.assertEqual(thp.audit_compute_alignment(binary, 64)["compute_entries"], 2)
            with patch.object(thp.subprocess, "check_output", return_value=(
                    "00000110 T _ZN3foo_eval_compute_batch_0Ev\n")):
                with self.assertRaisesRegex(ValueError, "not aligned"):
                    thp.audit_compute_alignment(binary, 64)
            with patch.object(thp.subprocess, "check_output", return_value=""):
                with self.assertRaisesRegex(ValueError, "no GrhSIM compute entries"):
                    thp.audit_compute_alignment(binary, 64)

    def test_preferred_and_retry_preserve_affinity_and_binary_arguments(self):
        command = ["taskset", "--cpu-list", "96-127", "numactl",
                   "--membind=1", "setarch", "x86_64", "-R", "/tmp/emu", "-C", "100000"]
        result = thp.with_codepage(command, "/tmp/emu", "preferred", Path("/tmp/retry.so"))
        self.assertIn("--preferred=1", result)
        self.assertNotIn("--membind=1", result)
        self.assertEqual(result[:4], command[:4])
        self.assertEqual(result[-3:], command[-3:])
        self.assertIn(f"LD_PRELOAD=/tmp/retry.so:{thp.PRELOAD}", result)
        self.assertIn("WOLVI_GRHSIM_CODE_HUGEPAGE=0", result)
        self.assertIn("REPCUT_CODEPAGE_MODE=thp", result)
        self.assertIn("--membind=1", command)

    def test_default_keeps_bind_and_rejects_unknown_policy(self):
        command = ["numactl", "--membind=1", "/tmp/emu"]
        self.assertIn("--membind=1", thp.with_codepage(command, "/tmp/emu"))
        with self.assertRaises(ValueError):
            thp.with_codepage(command, "/tmp/emu", "invalid")

    def test_incomplete_thp_does_not_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            log = output / "pair01-a-baseline.log"
            log.write_text("[codepage] PASS mode=thp bytes=4194304 anon_huge=2097152 "
                           "regions=1 setup_s=0.001 pid=123\n")
            with self.assertRaisesRegex(RuntimeError, "incomplete THP coverage"):
                thp.audit_thp(output)
            log.write_text("[codepage] PASS mode=thp bytes=4194304 anon_huge=4194304 "
                           "regions=1 setup_s=0.001 pid=123\n")
            thp.audit_thp(output)
            report = json.loads((output / "thp_verification.json").read_text())
            self.assertEqual(report["runs"][0]["huge_bytes"], 4194304)


if __name__ == "__main__":
    unittest.main()
