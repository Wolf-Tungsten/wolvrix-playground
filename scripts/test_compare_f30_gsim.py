"""Small frozen fixtures cover GSIM reference collection and common boundaries."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import benchmark_f30_gsim as benchmark
import compare_f30_gsim as comparison
import test_compare_f30_performance as grh_fixture
from benchmark_f29_pass_trace import sha256, write_json_atomic


def timer_log(read=1, parse=2, init=57, split=25):
    return ''.join(f'{label} = {int(value * 1000)} ms\n' for label, value in zip(
        benchmark.TIMER_LABELS, (read, parse, init, split)))


class GsimReferenceTests(unittest.TestCase):
    def setUp(self):
        root = benchmark.ROOT / 'ptmp/firrtl-ingest/F30/gsim-contract'
        root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=root)
        self.work = Path(self.temporary.name)
        self.firrtl = self.work / 'SimTop.fir'
        self.firrtl.write_text('fixture FIRRTL\n')
        self.source = self.work / 'source'
        self.source.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.source)], check=True)
        (self.source / 'main.cpp').write_text('// source fixture\n')
        (self.source / 'Makefile').write_text('# frozen configuration\n')
        subprocess.run(['git', '-C', str(self.source), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.source), '-c', 'user.name=F30 test',
            '-c', 'user.email=f30@example.invalid', 'commit', '-qm', 'fixture'], check=True)
        self.binary = self.work / 'gsim'
        self.binary.write_bytes(b'not a real executable; subprocess is mocked')
        self.grh = [grh_fixture.PerformanceComparisonTests().sample('candidate') for _ in range(3)]
        for index, value in enumerate(self.grh):
            value['input'] = str(self.firrtl)
            value['input_sha256'] = sha256(self.firrtl)
            value['sources'][0].update(path=str(self.firrtl), sha256=sha256(self.firrtl))
            value.update(started_at_ns=(index * 10 + 40) * 10**12,
                         finished_at_ns=(index * 10 + 41) * 10**12)
        self.gsim = []
        original_run = subprocess.run
        def linked(command, *args, **kwargs):
            if command[0] == 'ldd':
                return subprocess.CompletedProcess(command, 0, 'static fixture\n')
            return original_run(command, *args, **kwargs)
        for index in range(3):
            output = self.work / ('gsim-' + str(index))
            output.mkdir()
            with patch('benchmark_f30_gsim.subprocess.run', side_effect=linked):
                native, identity = benchmark.freeze_native(self.binary, self.source, output)
            log = output / 'gsim.log'
            log.write_text(timer_log())
            self.gsim.append({'schema': benchmark.SCHEMA, 'status': 'passed', 'mode': 'no-trace', 'trace': False,
                'stop_after_stage': 'SplitArray', 'returncode': 0, 'native_identity_verified': True,
                'input_unchanged': True, 'binary_unchanged': True, 'input': str(self.firrtl),
                'input_sha256': sha256(self.firrtl), 'cpu_affinity': [0, 1],
                'configuration': {'machine': 'fixture', 'cpu_model': 'CPU', 'thread_environment': {'threads': 8},
                    'instrumentation': {'trace': False, 'dump': False, 'source': 'raw-firrtl'}},
                'native': native, 'identity_file': str(identity), 'identity_sha256': sha256(identity),
                'command': [native['binary'], '--dir', str(output / 'model'), '--stop-after-stage=SplitArray', str(self.firrtl)],
                'log': str(log), 'log_sha256': sha256(log), 'timers': benchmark.parse_timers(log.read_text()),
                'metrics': {'prefix': 60.0, 'comb-split.total': 25.0, 'prefix+transform': 85.0},
                'wall_s': 90.0, 'started_at_ns': (index * 10 + 3) * 10**12,
                'finished_at_ns': (index * 10 + 4) * 10**12})
        _, references = self.samples()
        self.timeout_reference = comparison.derive_split_timeout(
            references, self.grh[0], self.grh[0]['started_at_ns'])
        for sample in self.grh:
            sample['split_timeout_s'] = self.timeout_reference['split_timeout_s']
            sample['split_timeout_reference'] = deepcopy(self.timeout_reference)

    def tearDown(self):
        self.temporary.cleanup()

    def samples(self):
        groups = []
        for engine, values in (('grh', self.grh), ('gsim', self.gsim)):
            paths = []
            for index, value in enumerate(values):
                path = self.work / f'{engine}-{index}.json'
                write_json_atomic(path, value)
                paths.append(path)
            groups.append(paths)
        return groups

    def test_timers_require_one_of_each_and_preserve_millisecond_precision(self):
        self.assertEqual(benchmark.parse_timers('\x1b[1;35m' + timer_log()),
                         {'readFile': 1.0, 'parseFIR': 2.0, 'Init': 57.0, 'splitArray': 25.0})
        for content in (timer_log() + 'Init = 1 ms\n', timer_log().replace('Init = 57000 ms\n', '')):
            with self.assertRaises(ValueError):
                benchmark.parse_timers(content)

    def test_timeout_uses_frozen_gsim_split_median_and_pipeline_resolves_same_evidence(self):
        from benchmark_f30_pipeline import resolve_split_timeout
        for sample, seconds in zip(self.gsim, (45.903, 45.904, 45.905)):
            log = Path(sample['log'])
            log.write_text(timer_log(split=seconds))
            sample.update(log_sha256=sha256(log), timers=benchmark.parse_timers(log.read_text()), wall_s=110.0)
            sample['metrics'].update({'comb-split.total': seconds, 'prefix+transform': 60.0 + seconds})
        _, references = self.samples()
        evidence = resolve_split_timeout(references, self.grh[0], self.grh[0]['started_at_ns'])
        self.assertEqual(evidence['median_s'], 45.904)
        self.assertEqual(evidence['split_timeout_s'], 91.808)
        self.assertEqual(evidence['multiplier'], 2)
        self.assertEqual([item['sha256'] for item in evidence['samples']], list(map(sha256, references)))
        for sample in self.grh:
            sample.update(split_timeout_s=evidence['split_timeout_s'], split_timeout_reference=deepcopy(evidence))
        report = comparison.compare(*self.samples())
        self.assertTrue(report['passed'], report['errors'])
        self.assertEqual(report['split_timeout_reference'], evidence)
        self.assertEqual(report['samples']['grh'][0]['hard_limit']['limit_s'], 91.808)

    def test_timeout_requires_completed_distinct_no_trace_reference_and_matching_machine(self):
        _, references = self.samples()
        for paths in (references[:2], [references[0]] * 3, list(reversed(references))):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                comparison.derive_split_timeout(paths, self.grh[0], self.grh[0]['started_at_ns'])
        with self.assertRaisesRegex(ValueError, 'finish before'):
            comparison.derive_split_timeout(references, self.grh[0], self.gsim[-1]['started_at_ns'])
        for field, changed in (('input_sha256', 'f' * 64), ('cpu_affinity', [2, 3])):
            context = deepcopy(self.grh[0])
            context[field] = changed
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'incompatible'):
                comparison.derive_split_timeout(references, context, self.grh[0]['started_at_ns'])
        context = deepcopy(self.grh[0])
        context['configuration']['thread_environment']['threads'] = 1
        with self.assertRaisesRegex(ValueError, 'incompatible'):
            comparison.derive_split_timeout(references, context, self.grh[0]['started_at_ns'])
        self.gsim[0]['trace'] = True
        _, invalid = self.samples()
        with self.assertRaisesRegex(ValueError, 'without trace'):
            comparison.derive_split_timeout(invalid, self.grh[0], self.grh[0]['started_at_ns'])

    def test_untrusted_raw_cap_or_reference_never_marks_hard_limit_passed(self):
        self.grh[0]['split_timeout_s'] = 10**6
        report = comparison.compare(*self.samples())
        self.assertFalse(report['complete'])
        self.assertEqual(report['samples']['grh'][0]['hard_limit']['status'], 'unverified')
        self.assertEqual(report['samples']['grh'][0]['hard_limit']['limit_s'], 50.0)
        self.grh[0]['split_timeout_s'] = 50.0
        self.grh[0]['split_timeout_reference']['samples'][0]['sha256'] = '0' * 64
        report = comparison.compare(*self.samples())
        self.assertFalse(report['complete'])
        self.assertEqual(report['samples']['grh'][0]['hard_limit']['status'], 'unverified')
        self.assertIsNone(report['samples']['grh'][0]['hard_limit']['limit_s'])

    def test_reference_summary_must_remain_frozen_after_inspection(self):
        _, references = self.samples()
        inspected = list(map(comparison.inspect_gsim, references))
        references[0].write_bytes(references[0].read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'summary changed'):
            comparison.timeout_reference_from_samples(inspected, self.grh[0], self.grh[0]['started_at_ns'])

    def test_successful_sample_with_inconsistent_watchdog_row_fails_closed(self):
        self.grh[0]['no_trace']['passes'][-1]['timeout_s'] = 49.046
        report = comparison.compare(*self.samples())
        self.assertFalse(report['complete'])
        self.assertFalse(report['passed'])
        self.assertEqual(report['hard_limit'], 'incomplete')
        self.assertEqual(report['samples']['grh'][0]['hard_limit']['status'], 'unverified')
        self.assertIn('lacks verified hard-limit completion', '\n'.join(report['errors']))

    def test_derived_hard_cap_does_not_relax_native_regression_gate_or_legacy_reader(self):
        from compare_f30_performance import inspect_sample
        for sample in self.grh:
            sample['no_trace']['passes'][-1].update(pass_s=49.5, total_s=51.5)
            sample['no_trace']['wall_s'] = 65.0
            sample['wall_s'] = 130.0
        paths = self.samples()
        report = comparison.compare(*paths)
        self.assertEqual(report['hard_limit'], 'passed')
        self.assertEqual(report['status'], 'regressed')
        with self.assertRaisesRegex(ValueError, '49.046'):
            inspect_sample(paths[0][0])
        self.grh[0]['status'] = 'failed'
        self.grh[0]['no_trace']['passes'][-1].update(status='timeout', pass_s=50.1, pass_returned=False)
        report = comparison.compare(*self.samples())
        self.assertEqual(report['hard_limit'], 'failed')
        evidence = report['samples']['grh'][0]['hard_limit']
        self.assertEqual(evidence['limit_s'], 50.0)
        self.assertIsNone(evidence['completion_time_s'])

    def test_common_boundaries_and_native_source_identity_are_verified(self):
        report = comparison.compare(*self.samples())
        self.assertTrue(report['passed'], report['errors'])
        self.assertEqual(len(report['comparisons']), 3)
        self.assertEqual(len(report['diagnostic_comparisons']), 2)
        self.assertEqual(report['formal_metrics'], ['prefix', 'comb-split.pass', 'prefix+transform.pass'])
        self.assertEqual(report['reference'], 'GSIM no-trace')
        self.assertEqual(report['hard_limit'], 'passed')
        self.assertTrue(all(row['classification'] == 'strict_pass' for row in report['comparisons']))
        Path(self.gsim[0]['native']['binary']).write_bytes(b'tampered')
        rejected = comparison.compare(*self.samples())
        self.assertFalse(rejected['complete'])
        self.assertEqual(rejected['samples']['gsim'][0]['raw'], self.gsim[0])

    def test_trace_export_cost_is_visible_without_becoming_a_native_pass_gate(self):
        for sample in self.grh:
            sample.update(mode='trace')
            sample['configuration']['instrumentation']['trace'] = True
            sample['trace'] = sample.pop('no_trace')
            sample['trace']['trace'] = True
            for row in sample['trace']['passes']:
                row.update(trace_setup_s=0.5, trace_finish_s=0.5, trace_validate_at_finish=False)
            sample['trace']['wall_s'] = 26.0
            sample['wall_s'] = 91.0
        report = comparison.compare(*self.samples())
        rows = {row['metric']: row for row in report['diagnostic_comparisons']}
        self.assertTrue(report['passed'])
        self.assertEqual(report['comparisons'][1]['grh_median_s'], 20.0)
        self.assertEqual(rows['comb-split.total']['classification'], 'regression')
        self.assertEqual(rows['ingest-through-split.total']['classification'], 'within_jitter')
        self.assertEqual(report['mode'], 'trace')
        self.assertIn('trace_finish_s', report['samples']['grh'][0]['raw']['trace']['passes'][0])

    def test_verify_correctness_samples_failures_and_timeout_never_satisfy_gate(self):
        self.grh[0]['status'] = 'failed'
        row = self.grh[0]['no_trace']['passes'][-1]
        row.update(status='timeout', pass_s=50.1)
        row.pop('pass_returned')
        report = comparison.compare(*self.samples())
        self.assertEqual(report['hard_limit'], 'failed')
        self.assertEqual(report['relative'], 'incomplete')
        self.assertEqual(len(report['samples']['grh']), 3)
        self.grh[0]['status'] = 'passed'
        row.update(status='passed', pass_s=10.0, pass_returned=True)
        # A fully valid verify=1 sample is still a correctness run, not a formal timing sample.
        for sample in self.grh:
            sample['verify'] = True
            sample['configuration']['instrumentation']['verify'] = True
            for stage in sample['no_trace']['passes']:
                stage.update(semantic_validation_s=0.1, semantic_validation={'valid': True})
            sample['no_trace']['passes'][-1].update(grh_verification='passed', grh_verification_s=0.1)
        self.assertIn('verify=1', '\n'.join(comparison.compare(*self.samples())['errors']))

    def test_sample_count_input_overlap_and_no_trace_reference_are_enforced(self):
        grh, gsim = self.samples()
        self.assertFalse(comparison.compare(grh[:2], gsim)['complete'])
        self.gsim[0]['started_at_ns'] = self.grh[0]['started_at_ns']
        self.assertFalse(comparison.compare(*self.samples())['complete'])
        self.gsim[0]['started_at_ns'] = 3 * 10**12
        self.gsim[0]['trace'] = True
        report = comparison.compare(*self.samples())
        self.assertFalse(report['complete'])
        self.assertEqual(report['samples']['gsim'][0]['raw'], self.gsim[0])

    def test_flatten_profile_samples_remain_diagnostic(self):
        for sample in self.grh:
            sample['configuration']['instrumentation']['profile_flatten'] = True
        report = comparison.compare(*self.samples())
        self.assertFalse(report['complete'])
        self.assertFalse(report['passed'])
        self.assertIn('profile-flatten diagnostic', '\n'.join(report['errors']))
        self.assertEqual(len(report['samples']['grh']), 3)

    def test_split_profile_samples_remain_diagnostic(self):
        for sample in self.grh:
            sample['configuration']['instrumentation']['profile_split'] = True
        report = comparison.compare(*self.samples())
        self.assertFalse(report['complete'])
        self.assertFalse(report['passed'])
        self.assertIn('profile-split diagnostic', '\n'.join(report['errors']))
        self.assertEqual(len(report['samples']['grh']), 3)

    def test_resource_guard_diagnostic_samples_never_enter_formal_comparison(self):
        from compare_f30_performance import inspect_sample
        for sample in self.grh:
            sample['configuration']['instrumentation']['resource_guard'] = True
        paths = self.samples()
        report = comparison.compare(*paths)
        self.assertFalse(report['complete'])
        self.assertFalse(report['passed'])
        self.assertIn('resource-guard diagnostic', '\n'.join(report['errors']))
        self.assertEqual(len(report['samples']['grh']), 3)
        # Both GSIM comparison and the older paired comparison share this reader.
        with self.assertRaisesRegex(ValueError, 'resource-guard diagnostic'):
            inspect_sample(paths[0][0], expected_cap_s=self.timeout_reference['split_timeout_s'])
        for sample in self.grh:
            sample['configuration']['instrumentation']['resource_guard'] = False
            sample['resource_guard'] = {'diagnostic_only': True, 'status': 'completed'}
        self.assertIn('resource-guard diagnostic', '\n'.join(comparison.compare(*self.samples())['errors']))

    def test_jitter_and_cli_reports_keep_raw_deltas_and_boundaries(self):
        for sample in self.grh:
            sample['prefix']['stages'][0]['wall_s'] = 20.5
        paths = self.samples()
        self.assertTrue(comparison.compare(*paths)['passed'])
        self.assertFalse(comparison.compare(*paths, jitter_relative=0, jitter_absolute_s=0)['passed'])
        with self.assertRaises(ValueError):
            comparison.compare(*paths, jitter_relative=float('nan'))
        output = self.work / 'report'
        self.assertEqual(comparison.main(['--grh', *map(str, paths[0]), '--gsim', *map(str, paths[1]),
                                          '--output', str(output)]), 0)
        self.assertEqual(len((output / 'comparison.tsv').read_text().splitlines()), 4)
        self.assertEqual(len((output / 'diagnostic-comparison.tsv').read_text().splitlines()), 3)

    def test_benchmark_subprocess_failure_retains_frozen_input_and_native_evidence(self):
        identity = deepcopy(self.gsim[0]['native'])
        identity_path = Path(self.gsim[0]['identity_file'])
        output = self.work / 'failed-benchmark'
        original_run = subprocess.run
        def fail(command, **kwargs):
            if command[0] != identity['binary']:
                return original_run(command, **kwargs)
            kwargs['stdout'].write('failed before timers\n')
            return subprocess.CompletedProcess(command, 7)
        with patch.object(benchmark, 'freeze_native', return_value=(identity, identity_path)), \
                patch.object(benchmark.subprocess, 'run', side_effect=fail), \
                self.assertRaisesRegex(ValueError, 'subprocess failed'):
            benchmark.benchmark(self.binary, self.source, self.firrtl, output)
        report = json.loads((output / 'summary.json').read_text())
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['returncode'], 7)
        self.assertEqual(report['native'], identity)
        self.assertGreater(report['finished_at_ns'], report['started_at_ns'])

    def test_benchmark_success_finishes_actual_hashes_and_revalidates_common_metrics(self):
        identity = deepcopy(self.gsim[0]['native'])
        identity_path = Path(self.gsim[0]['identity_file'])
        output = self.work / 'successful-benchmark'
        def succeed(command, **kwargs):
            self.assertEqual(command[0], identity['binary'])
            kwargs['stdout'].write(timer_log())
            return subprocess.CompletedProcess(command, 0)
        with patch.object(benchmark, 'freeze_native', return_value=(identity, identity_path)), \
                patch.object(benchmark.subprocess, 'run', side_effect=succeed), \
                patch.object(benchmark.platform, 'uname', return_value=('Linux', 'fixture', '1', 'v', 'x86_64', 'CPU')), \
                patch.object(benchmark.platform, 'machine', return_value='x86_64'), \
                patch.object(benchmark.time, 'monotonic', side_effect=(100.0, 200.0)), \
                patch.object(benchmark.time, 'time_ns', side_effect=(10**12, 11 * 10**11)):
            report = benchmark.benchmark(self.binary, self.source, self.firrtl, output)
        self.assertEqual(report['status'], 'passed')
        self.assertTrue(report['input_unchanged'])
        self.assertTrue(report['binary_unchanged'])
        self.assertEqual(report['metrics'], {'prefix': 60.0, 'comb-split.total': 25.0, 'prefix+transform': 85.0})
        verified = comparison.inspect_gsim(output / 'summary.json')
        self.assertTrue(verified['accepted'])
        self.assertEqual(verified['metrics'], {**report['metrics'], 'ingest-through-split.total': 100.0,
            'comb-split.pass': 25.0, 'prefix+transform.pass': 85.0})


if __name__ == '__main__':
    unittest.main()
