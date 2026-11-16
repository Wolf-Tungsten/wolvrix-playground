import unittest
import json
import tempfile
import contextlib
import io
from unittest.mock import patch
from pathlib import Path

from cv32e40p_regfile_compare import backend_names, measured_backends

from cv32e40p_compare import parse_result, signature, summarize, summarize_named, validate_workload
from cv32e40p_compare import identity
from cv32e40p_event_regions_compare import measure as measure_regions


class Cv32ComparisonTests(unittest.TestCase):
    def test_region_runner_uses_manifest_names_and_keeps_ratio_direction(self):
        manifest = dict(backend_pair=['old_region', 'local_cache'], feature='local_cache')
        row = dict(exit_code=0, cycles=1, uart='same')
        def sample(_out, backend, *_args):
            wall = {'old_region': 10., 'local_cache': 8., 'verilator': 5.}[backend]
            return row | dict(wall_s=wall, sim_s=wall - 1., init_s=1.)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'build.json').write_text(json.dumps(manifest))
            (root / 'structure.json').write_text('{}')
            (root / 'functional.json').write_text(json.dumps(dict(status='pass',
                build=identity(root / 'build.json'), workloads={'coremark': {b: row for b in
                    ('old_region', 'local_cache', 'verilator')}})))
            with patch('cv32e40p_event_regions_compare.check', return_value=manifest), \
                 patch('cv32e40p_event_regions_compare.sample', side_effect=sample), \
                 contextlib.redirect_stdout(io.StringIO()):
                measure_regions(root)
            result = json.loads((root / 'summary.json').read_text())
            self.assertEqual(result['old_region']['wall_s']['ratio_ci95'], [.8, .8])
            self.assertEqual(result['verilator']['wall_s']['ratio_ci95'], [1.6, 1.6])
            self.assertTrue(result['old_region']['ratio_definition'].startswith('local_cache / old_region'))

    def test_chained_comparison_keeps_backend_identity(self):
        self.assertEqual(backend_names({}), ('grhsim_baseline', 'grhsim_indexed'))
        self.assertEqual(backend_names({'backend_pair': ['grhsim_baseline', 'grhsim_packed_slices']}),
                         ('grhsim_baseline', 'grhsim_packed_slices'))

    def test_measured_backends_include_only_attached_references(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            manifest = {'backend_pair': ['grhsim_baseline', 'grhsim_packed_slices']}
            self.assertEqual(measured_backends(out, manifest), tuple(manifest['backend_pair']))
            (out / 'verilator-reference.json').write_text(json.dumps({'verilator': {}, 'verilator-original': {}}))
            self.assertEqual(measured_backends(out, manifest),
                             ('grhsim_baseline', 'grhsim_packed_slices', 'verilator', 'verilator-original'))

    def test_optimization_ratio_keeps_explicit_names(self):
        rows = [dict(grhsim_baseline=dict(wall_s=10., sim_s=8., init_s=2.),
                     grhsim_indexed=dict(wall_s=7., sim_s=6., init_s=1.)) for _ in range(8)]
        result = summarize_named(rows, 'grhsim_indexed', 'grhsim_baseline')
        self.assertEqual(result['wall_s']['ratio_ci95'], [.7, .7])
        self.assertEqual(result['sim_s']['ratio_mean'], .75)
        self.assertTrue(result['ratio_definition'].startswith('grhsim_indexed / grhsim_baseline'))

    def test_ratio_direction_is_grhsim_over_verilator(self):
        rows = [dict(verilator=dict(wall_s=2., sim_s=1., init_s=1.),
                     grhsim=dict(wall_s=20., sim_s=10., init_s=10.)) for _ in range(8)]
        result = summarize(rows)
        self.assertEqual(result['wall_s']['ratio_ci95'], [10., 10.])
        self.assertTrue(result['diagnosis_required'])
        reverse = [dict(grhsim=r['verilator'], verilator=r['grhsim']) for r in rows]
        result = summarize(reverse)
        self.assertAlmostEqual(result['wall_s']['ratio_mean'], .1)
        self.assertFalse(result['diagnosis_required'])

    def test_crc_gate_rejects_success_exit_with_wrong_crc(self):
        text = ('seedcrc : 0xe9f5\n[0]crclist : 0xe714\n[0]crcmatrix : 0x1fd7\n'
                '[0]crcstate : 0x8e3a\nIterations : 10\nCorrect operation validated.\n')
        row = dict(exit_code=0, uart=text)
        validate_workload(row, 'coremark')
        for mutated in (text.replace('e714', 'e715'), text.replace('10\n', '1\n'), text + 'ERROR!\n'):
            with self.assertRaises(ValueError): validate_workload(dict(exit_code=0, uart=mutated), 'coremark')

    def test_result_parser_preserves_guest_output(self):
        text = 'SMOKE PASS\n'
        log = ('host setup diagnostic\nCV32_RESULT {"exit_code":0,"cycles":12,"sim_s":0.1,'
               '"uart_hex":"' + text.encode().hex() + '"}\n')
        row = parse_result(log)
        self.assertEqual(row['uart'], text)
        self.assertEqual(signature(row), dict(exit_code=0, cycles=12, uart=text))
        validate_workload(row, 'smoke')
        with self.assertRaises(ValueError): parse_result(log + log)


if __name__ == '__main__':
    unittest.main()
