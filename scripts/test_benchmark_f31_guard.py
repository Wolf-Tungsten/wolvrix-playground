"""F31 benchmark resource-guard configuration contract."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import benchmark_f31_dce
from f30_resource_guard import GuardLimits


ROOT = Path(__file__).resolve().parents[1]


class BenchmarkGuardTests(unittest.TestCase):
    def test_custom_limits_are_forwarded_to_external_guard(self):
        output = ROOT / 'ptmp/firrtl-ingest/F31/benchmark-guard-tests/custom'
        argv = ['benchmark_f31_dce.py', '--engine', 'grh', '--mode', 'trace',
                '--firrtl', str(ROOT / 'build/xs/rtl/rtl/SimTop.fir'),
                '--manifest', str(ROOT / 'ptmp/semantic-bindings/F26/grh/ingest-request.json'),
                '--package', str(ROOT / 'ptmp/firrtl-ingest/F31/package'),
                '--output', str(output), '--resource-guard-rss-gib', '96',
                '--resource-guard-psi-percent', '50', '--resource-guard-psi-seconds', '12',
                '--resource-guard-interval-s', '0.5']
        with patch.object(sys, 'argv', argv), patch('f30_resource_guard.run_guarded', return_value=0) as guarded:
            with self.assertRaises(SystemExit) as exit_info:
                benchmark_f31_dce.main()
        self.assertEqual(exit_info.exception.code, 0)
        command, work, limits = guarded.call_args.args
        self.assertEqual(work, output.resolve())
        self.assertEqual(limits, GuardLimits(rss_bytes=96 * 1024**3, psi_percent=50,
                                             psi_seconds=12, interval_s=0.5))
        self.assertEqual(command[-1], '--guard-child')
        self.assertIn('--resource-guard-psi-percent', command)

    def test_invalid_psi_limits_fail_before_starting_guard(self):
        output = ROOT / 'ptmp/firrtl-ingest/F31/benchmark-guard-tests/invalid'
        argv = ['benchmark_f31_dce.py', '--engine', 'grh', '--firrtl', 'input.fir',
                '--manifest', 'manifest.json', '--package', 'package', '--output', str(output),
                '--resource-guard-psi-percent', '101']
        with patch.object(sys, 'argv', argv), patch('f30_resource_guard.run_guarded') as guarded:
            with self.assertRaises(SystemExit) as exit_info:
                benchmark_f31_dce.main()
        self.assertEqual(exit_info.exception.code, 2)
        guarded.assert_not_called()


if __name__ == '__main__':
    unittest.main()
