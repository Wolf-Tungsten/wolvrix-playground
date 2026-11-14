"""F30 performance gates preserve evidence and bound paired median jitter."""
from copy import deepcopy
from contextlib import redirect_stderr
from io import StringIO
import json
import math
from pathlib import Path
import tempfile
import unittest

import compare_f30_performance as perf


class PerformanceComparisonTests(unittest.TestCase):
    def setUp(self):
        root = perf.ROOT / 'ptmp' / 'firrtl-ingest' / 'F30' / 'performance-contract'
        root.mkdir(parents=True, exist_ok=True)
        self.work = tempfile.TemporaryDirectory(dir=root)
        self.directory = Path(self.work.name)
        self.before = [self.sample(native='before') for _ in range(3)]
        self.after = [self.sample(native='after') for _ in range(3)]

    def tearDown(self):
        self.work.cleanup()

    def sample(self, native, mode='no-trace', verify=False):
        stages = [{'pass': name, 'status': 'passed', 'pass_returned': True,
                   'pass_s': 10.0, 'total_s': 12.0} for name in perf.PASSES]
        if mode == 'trace':
            for stage in stages:
                stage.update(trace_setup_s=0.5, trace_finish_s=0.5, trace_validate_at_finish=verify)
        if verify:
            for stage in stages:
                stage.update(semantic_validation_s=0.2, semantic_validation={'valid': True})
            stages[-1].update(grh_verification_s=0.2, grh_verification='passed')
        source = {'path': '/fixtures/SimTop.fir', 'language': 'firrtl', 'unit': 'main',
                  'bytes': 1000, 'sha256': '1' * 64}
        dependencies = {'content_sha256': 'd' * 64, 'repositories': []}
        return {'schema': perf.INPUT_SCHEMA, 'status': 'passed', 'input': '/fixtures/SimTop.fir',
            'input_sha256': '1' * 64, 'manifest': '/fixtures/manifest.json', 'manifest_sha256': '2' * 64,
            'package_identity_verified': True, 'source_identity_verified': True, 'dependencies_verified': True,
            'identity_sha256': ('b' if native == 'before' else 'c') * 64, 'sources': [source],
            'dependencies': dependencies,
            'native': {'package': '/' + native + '/wolvrix/__init__.py', 'libraries': [
                {'path': '/' + native + '/_wolvrix.so', 'sha256': ('3' if native == 'before' else '4') * 64},
                {'path': '/' + native + '/libwolvrix-lib.so', 'sha256': ('5' if native == 'before' else '6') * 64}]},
            'source_revision': native, 'configuration': {'machine': 'fixture', 'cpu_model': 'CPU',
                'thread_environment': {'threads': 8}, 'build': 'Release',
                'pass_parameters': {name: {} for name in (*perf.PREFIX_STAGES, *perf.PASSES)},
                'sources': [source], 'dependencies': dependencies,
                'instrumentation': {'source': 'raw-firrtl', 'clone': False, 'trace': mode == 'trace',
                                    'verify': verify, 'statistics': False}, 'python_version': '3.12'},
            'cpu_affinity': [0, 1], 'mode': mode, 'verify': verify, 'split_timeout_s': perf.SPLIT_TIMEOUT_S,
            'prefix': {'stages': [{'stage': name, 'wall_s': 20.0, 'user_s': 25.0, 'system_s': 1.0,
                                   'maxrss_kib': 1000} for name in perf.PREFIX_STAGES]},
            'trace' if mode == 'trace' else 'no_trace': {'trace': mode == 'trace', 'status': 'passed',
                'skip_comb': False, 'passes': stages, 'wall_s': 25.0},
            'wall_s': 90.0, 'user_s': 100.0, 'system_s': 2.0, 'maxrss_kib': 1000}

    def write_samples(self):
        result = []
        for side, samples in (('before', self.before), ('after', self.after)):
            paths = []
            for index, sample in enumerate(samples):
                if 'started_at_ns' not in sample:
                    sample['started_at_ns'] = (10 * index + (1 if side == 'before' else 5)) * 10**12
                if 'finished_at_ns' not in sample:
                    sample['finished_at_ns'] = sample['started_at_ns'] + 10**11
                path = self.directory / f'{side}-{index}.json'
                path.write_text(json.dumps(sample) + '\n')
                paths.append(path)
            result.append(paths)
        return result

    def compare(self, **policy):
        return perf.compare(*self.write_samples(), **policy)

    def test_equal_times_pass_in_strict_mode_without_same_native_requirement(self):
        report = self.compare(jitter_relative=0, jitter_absolute_s=0)
        self.assertEqual(report['status'], 'passed')
        self.assertTrue(report['complete'])
        self.assertEqual(len(report['comparisons']), 9)
        self.assertTrue(all(row['ratio'] == 1 and row['passed'] for row in report['comparisons']))
        self.assertEqual(report['samples']['after'][0]['raw'], self.after[0])

    def test_one_slow_stage_fails_despite_faster_total(self):
        for sample in self.after:
            sample['prefix']['stages'][0]['wall_s'] = 20.000001
            sample['prefix']['stages'][1]['wall_s'] = 1.0
            sample['wall_s'] = 80.0
        report = self.compare(jitter_relative=0, jitter_absolute_s=0)
        self.assertEqual(report['status'], 'regressed')
        rows = {row['metric']: row for row in report['comparisons']}
        self.assertFalse(rows['ingest']['passed'])
        self.assertTrue(rows['ingest-through-split.total']['passed'])

    def test_total_boundaries_cannot_hide_setup_or_between_pass_overhead(self):
        for metric in ('comb-loop-elim.total', 'split-static-array.total', 'comb-split.total',
                       'ingest-through-split.total'):
            with self.subTest(metric=metric):
                self.after = [self.sample('after') for _ in range(3)]
                for sample in self.after:
                    if metric.endswith('.total') and metric.split('.')[0] in perf.PASSES:
                        sample['no_trace']['passes'][perf.PASSES.index(metric.split('.')[0])]['total_s'] += 0.1
                    elif metric == 'comb-split.total':
                        sample['no_trace']['wall_s'] += 0.1
                    else:
                        sample['wall_s'] += 0.1
                report = self.compare(jitter_relative=0, jitter_absolute_s=0)
                self.assertEqual(report['status'], 'regressed')
                self.assertFalse(next(row for row in report['comparisons'] if row['metric'] == metric)['passed'])

    def test_medians_use_all_supplied_samples_in_pair_order(self):
        self.before = [self.sample('before') for _ in range(5)]
        self.after = [self.sample('after') for _ in range(5)]
        for sample, time in zip(self.after, (1, 1, 21, 22, 23)):
            sample['prefix']['stages'][0]['wall_s'] = time
            sample['wall_s'] = 100
        report = self.compare(jitter_relative=0, jitter_absolute_s=0)
        row = report['comparisons'][0]
        self.assertEqual(row['after_s'], [1, 1, 21, 22, 23])
        self.assertEqual(row['after_median_s'], 21)
        self.assertFalse(row['passed'])

    def test_default_jitter_policy_is_recorded_for_all_nine_metrics(self):
        report = self.compare()
        self.assertEqual(report['jitter_policy']['relative'], 0.03)
        self.assertEqual(report['jitter_policy']['absolute_s'], 0.010)
        self.assertFalse(report['jitter_policy']['strict'])
        for row in report['comparisons']:
            self.assertEqual(row['classification'], 'strict_pass')
            self.assertEqual(row['allowed_jitter_s'], max(row['before_median_s'] * 0.03, 0.010))
            self.assertEqual(row['threshold_s'], row['before_median_s'] + row['allowed_jitter_s'])
        perf.write_report(report, self.directory / 'jitter-report')
        header = (self.directory / 'jitter-report/comparison.tsv').read_text().splitlines()[0]
        for field in ('allowed_jitter_s', 'threshold_s', 'classification'):
            self.assertIn(field, header)

    def test_relative_jitter_boundary_passes_and_next_value_regresses(self):
        threshold = 20.0 + 20.0 * 0.03
        for elapsed, expected in ((19.0, 'strict_pass'), (20.0, 'strict_pass'),
                                   (20.1, 'within_jitter'), (threshold, 'within_jitter'),
                                   (math.nextafter(threshold, math.inf), 'regression')):
            with self.subTest(elapsed=elapsed):
                for sample in self.after:
                    sample['prefix']['stages'][0]['wall_s'] = elapsed
                report = self.compare()
                row = report['comparisons'][0]
                self.assertEqual(row['classification'], expected)
                self.assertEqual(row['delta_s'], elapsed - 20.0)
                self.assertEqual(row['ratio'], elapsed / 20.0)
                self.assertEqual(report['passed'], expected != 'regression')

    def test_absolute_jitter_floor_and_zero_baseline_have_explicit_boundaries(self):
        for baseline in (0.0, 0.1):
            threshold = baseline + 0.010
            for elapsed, expected in ((threshold, 'within_jitter'),
                                       (math.nextafter(threshold, math.inf), 'regression')):
                with self.subTest(baseline=baseline, elapsed=elapsed):
                    for sample in self.before:
                        sample['prefix']['stages'][1]['wall_s'] = baseline
                    for sample in self.after:
                        sample['prefix']['stages'][1]['wall_s'] = elapsed
                    report = self.compare()
                    row = report['comparisons'][1]
                    self.assertEqual(row['allowed_jitter_s'], 0.010)
                    self.assertEqual(row['classification'], expected)
                    self.assertEqual(report['passed'], expected != 'regression')

    def test_zero_policy_retains_strict_gate_and_custom_policy_can_only_tighten(self):
        for sample in self.after:
            sample['prefix']['stages'][0]['wall_s'] = 20.000001
        self.assertTrue(self.compare()['passed'])
        strict = self.compare(jitter_relative=0, jitter_absolute_s=0)
        self.assertFalse(strict['passed'])
        self.assertTrue(strict['jitter_policy']['strict'])
        self.assertTrue(all(row['allowed_jitter_s'] == 0 for row in strict['comparisons']))
        for sample in self.after:
            sample['prefix']['stages'][0]['wall_s'] = 20.3
        self.assertTrue(self.compare()['passed'])
        self.assertFalse(self.compare(jitter_relative=0.01, jitter_absolute_s=0.005)['passed'])

    def test_jitter_policy_rejects_out_of_range_nonfinite_and_non_numeric_values(self):
        paths = self.write_samples()
        for field, values in (('jitter_relative', (-0.001, 0.030001, float('nan'), float('inf'), True, '0.01')),
                              ('jitter_absolute_s', (-0.001, 0.010001, float('nan'), float('inf'), False, None))):
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    perf.compare(*paths, **{field: value})

    def test_cli_uses_default_jitter_accepts_strict_override_and_rejects_relaxation(self):
        for sample in self.after:
            sample['prefix']['stages'][0]['wall_s'] = 20.2
        before, after = self.write_samples()
        output = self.directory / 'cli-jitter'
        args = ['--before', *map(str, before), '--after', *map(str, after), '--output', str(output)]
        self.assertEqual(perf.main(args), 0)
        value = json.loads((output / 'comparison.json').read_text())
        self.assertEqual(value['comparisons'][0]['classification'], 'within_jitter')
        self.assertEqual(perf.main(args + ['--jitter-relative', '0', '--jitter-absolute-s', '0']), 1)
        for flag, values in (('--jitter-relative', ('-0.001', '0.031', 'nan', 'inf')),
                              ('--jitter-absolute-s', ('-0.001', '0.011', 'nan', 'inf'))):
            for invalid in values:
                with self.subTest(flag=flag, invalid=invalid), redirect_stderr(StringIO()), \
                        self.assertRaises(SystemExit) as rejected:
                    perf.main(args + [flag + '=' + invalid])
                self.assertEqual(rejected.exception.code, 2)

    def test_failed_incomplete_or_timeout_sample_is_not_silently_dropped(self):
        for status in ('failed', 'running', 'timeout'):
            with self.subTest(status=status):
                self.after = [self.sample('after') for _ in range(4)]
                self.after[0]['status'] = status
                self.before = [self.sample('before') for _ in range(4)]
                report = self.compare()
                self.assertFalse(report['complete'])
                self.assertIn('cannot be dropped', '\n'.join(report['errors']))
        self.after = [self.sample('after') for _ in range(4)]
        self.after[0]['no_trace']['passes'][-1]['status'] = 'timeout'
        self.assertFalse(self.compare()['complete'])

    def test_timeout_preserves_raw_and_separates_hard_failure_from_relative_unknown(self):
        for side in ('before', 'after'):
            sample = getattr(self, side)[0]
            sample['status'] = 'failed'
            sample['no_trace']['status'] = 'failed'
            row = sample['no_trace']['passes'][-1]
            row.update(status='timeout', pass_s=perf.SPLIT_TIMEOUT_S + 0.05)
            row.pop('pass_returned')
            sample.pop('finished_at_ns', None)
        report = self.compare()
        self.assertFalse(report['complete'])
        self.assertFalse(report['passed'])
        self.assertEqual(report['hard_limit'], 'failed')
        self.assertEqual(report['relative'], 'incomplete')
        self.assertEqual(report['comparisons'], [])
        for side in ('before', 'after'):
            self.assertEqual(len(report['samples'][side]), 3)
            rejected = report['samples'][side][0]
            self.assertFalse(rejected['accepted'])
            self.assertEqual(rejected['raw'], getattr(self, side)[0])
            self.assertEqual(rejected['hard_limit']['measurement'], 'deadline-observation-not-completion')
            self.assertIsNone(rejected['hard_limit']['completion_time_s'])
        perf.write_report(report, self.directory / 'timeout-report')
        self.assertEqual(json.loads((self.directory / 'timeout-report/comparison.json').read_text())['hard_limit'], 'failed')

    def test_dependency_provenance_is_reported_without_changing_pair_configuration(self):
        dependency_hash = 'd' * 64
        for sample in self.after:
            sample['source_revision'] += '+dependencies-sha256:' + dependency_hash
        report = self.compare()
        self.assertTrue(report['passed'])
        self.assertEqual(report['dependencies_provenance']['before'][0]['kind'], 'post-build-sidecar')
        self.assertEqual(report['dependencies_provenance']['after'][0]['kind'], 'frozen-source-bound')
        self.assertTrue(any('retroactively' in item for item in report['limitations']))
        for sample in self.before:
            sample['dependencies_provenance'] = 'post-build-sidecar'
        for sample in self.after:
            sample['dependencies_provenance'] = 'frozen-source-bound'
        self.assertTrue(self.compare()['passed'])

    def test_unserializable_rejected_numbers_preserve_original_json_text(self):
        self.after[0]['prefix']['stages'][0]['wall_s'] = float('nan')
        report = self.compare()
        self.assertFalse(report['complete'])
        self.assertIsNone(report['samples']['after'][0]['raw'])
        self.assertIn('NaN', report['samples']['after'][0]['raw_json'])
        perf.write_report(report, self.directory / 'invalid-number-report')

    def test_incompatible_configurations_reject_all_samples(self):
        changes = {'input': '/other.fir', 'input_sha256': '9' * 64, 'manifest': '/other.json',
                   'manifest_sha256': 'a' * 64, 'cpu_affinity': [2, 3], 'verify': True,
                   'configuration': {'machine': 'other'}}
        for field, value in changes.items():
            with self.subTest(field=field):
                self.after = [self.sample('after') for _ in range(3)]
                if field == 'verify':
                    self.after[0] = self.sample('after', verify=True)
                else:
                    self.after[0][field] = value
                self.assertFalse(self.compare()['complete'])

    def test_native_identity_or_revision_cannot_change_within_side(self):
        for side in ('before', 'after'):
            for field in ('native', 'source_revision'):
                with self.subTest(side=side, field=field):
                    self.before = [self.sample('before') for _ in range(3)]
                    self.after = [self.sample('after') for _ in range(3)]
                    sample = getattr(self, side)[1]
                    if field == 'native':
                        sample['native']['libraries'][0]['sha256'] = 'f' * 64
                    else:
                        sample['source_revision'] = 'changed'
                    report = self.compare()
                    self.assertFalse(report['complete'])
                    self.assertIn('within one version', '\n'.join(report['errors']))

    def test_trace_and_no_trace_are_separate_comparisons(self):
        self.after = [self.sample('after', mode='trace') for _ in range(3)]
        self.assertFalse(self.compare()['complete'])
        self.before = [self.sample('before', mode='trace') for _ in range(3)]
        report = self.compare()
        self.assertTrue(report['passed'])
        self.assertEqual(report['mode'], 'trace')
        self.assertIn('comb-loop-elim.trace_setup_s', report['components'])

    def test_trace_requires_recorded_setup_finish_and_verification(self):
        self.before = [self.sample('before', mode='trace', verify=True) for _ in range(3)]
        for field in ('trace_setup_s', 'trace_finish_s', 'semantic_validation_s'):
            with self.subTest(field=field):
                self.after = [self.sample('after', mode='trace', verify=True) for _ in range(3)]
                del self.after[0]['trace']['passes'][0][field]
                self.assertFalse(self.compare()['complete'])
        self.after = [self.sample('after', mode='trace', verify=True) for _ in range(3)]
        self.assertTrue(self.compare()['passed'])

    def test_split_independent_hard_cap_cannot_be_raised_or_averaged_away(self):
        for cap in (0, 60):
            with self.subTest(cap=cap):
                self.after = [self.sample('after') for _ in range(3)]
                self.after[0]['split_timeout_s'] = cap
                self.assertFalse(self.compare()['complete'])
        self.after = [self.sample('after') for _ in range(3)]
        stage = self.after[0]['no_trace']['passes'][-1]
        stage['pass_s'] = perf.SPLIT_TIMEOUT_S + 0.000001
        stage['total_s'] = 60
        self.after[0]['no_trace']['wall_s'] = 80
        self.after[0]['wall_s'] = 150
        self.assertFalse(self.compare()['complete'])

    def test_at_least_three_distinct_ordered_pairs_are_required(self):
        before, after = self.write_samples()
        for left, right in ((before[:2], after[:2]), (before, after[:2]),
                            ([before[0]] * 3, after), (before, before)):
            with self.subTest(left=left, right=right):
                self.assertFalse(perf.compare(left, right)['complete'])

    def test_missing_stages_invalid_numbers_and_bad_boundaries_are_incomplete(self):
        changes = (
            lambda sample: sample['prefix']['stages'].pop(),
            lambda sample: sample['no_trace']['passes'].reverse(),
            lambda sample: sample['prefix']['stages'][0].update(wall_s=True),
            lambda sample: sample['prefix']['stages'][0].update(wall_s=float('nan')),
            lambda sample: sample['no_trace']['passes'][0].update(total_s=1),
            lambda sample: sample['no_trace'].update(wall_s=1),
            lambda sample: sample.update(wall_s=1),
            lambda sample: sample['native']['libraries'][0].update(sha256='missing'),
            lambda sample: sample.update(cpu_affinity=[{}]),
        )
        for change in changes:
            with self.subTest(change=change):
                self.after = [self.sample('after') for _ in range(3)]
                change(self.after[0])
                self.assertFalse(self.compare()['complete'])

    def test_missing_configuration_revision_or_order_evidence_is_incomplete(self):
        for field in ('configuration', 'source_revision', 'started_at_ns', 'finished_at_ns'):
            with self.subTest(field=field):
                self.before = [self.sample('before') for _ in range(3)]
                self.after = [self.sample('after') for _ in range(3)]
                before, after = self.write_samples()
                del self.after[0][field]
                after[0].write_text(json.dumps(self.after[0]))
                report = perf.compare(before, after)
                self.assertFalse(report['complete'])
                self.assertFalse(report['passed'])
        for field in perf.CONFIGURATION_FIELDS:
            with self.subTest(configuration_field=field):
                self.after = [self.sample('after') for _ in range(3)]
                del self.after[0]['configuration'][field]
                self.assertFalse(self.compare()['complete'])

    def test_recorded_instrumentation_must_describe_normal_production_path(self):
        for field, invalid in (('source', 'checkpoint'), ('clone', True), ('trace', True),
                               ('verify', True), ('statistics', None)):
            with self.subTest(field=field, invalid=invalid):
                self.after = [self.sample('after') for _ in range(3)]
                self.after[0]['configuration']['instrumentation'][field] = invalid
                self.assertFalse(self.compare()['complete'])
        self.after = [self.sample('after') for _ in range(3)]
        del self.after[0]['configuration']['pass_parameters']['ingest']
        self.assertFalse(self.compare()['complete'])
        self.after = [self.sample('after') for _ in range(3)]
        for sample in self.before + self.after:
            sample['configuration']['machine'] = ['Linux', 'fixture', 'version', 'cpu']
        self.assertTrue(self.compare()['passed'])

    def test_verified_source_and_binary_provenance_cannot_be_omitted_or_changed(self):
        for field in ('package_identity_verified', 'source_identity_verified', 'dependencies_verified', 'identity_sha256'):
            with self.subTest(field=field):
                self.after = [self.sample('after') for _ in range(3)]
                del self.after[0][field]
                self.assertFalse(self.compare()['complete'])
        for field in ('sources', 'dependencies'):
            with self.subTest(field=field):
                self.after = [self.sample('after') for _ in range(3)]
                del self.after[0]['configuration'][field]
                self.assertFalse(self.compare()['complete'])
        self.after = [self.sample('after') for _ in range(3)]
        self.after[0]['identity_sha256'] = 'f' * 64
        self.assertFalse(self.compare()['complete'])
        self.after = [self.sample('after') for _ in range(3)]
        self.after[0]['configuration']['sources'][0]['sha256'] = 'f' * 64
        self.assertFalse(self.compare()['complete'])

    def test_actual_timestamp_order_must_alternate_without_overlap(self):
        before, after = self.write_samples()
        self.assertEqual(perf.compare(before, after)['execution_order'],
                         ['before[0]', 'after[0]', 'before[1]', 'after[1]', 'before[2]', 'after[2]'])
        for side in ('before', 'after'):
            for sample in getattr(self, side):
                sample['started_at_ns'] += (4 if side == 'before' else -4) * 10**12
                sample['finished_at_ns'] = sample['started_at_ns'] + 10**11
        report = self.compare()
        self.assertTrue(report['passed'])
        self.assertEqual(report['execution_order'][0], 'after[0]')
        before, after = self.write_samples()
        self.assertFalse(perf.compare(before[::-1], after)['complete'])
        self.before[0]['started_at_ns'] = self.after[0]['started_at_ns'] + 1
        self.before[0]['finished_at_ns'] = self.after[0]['finished_at_ns'] + 1
        self.assertFalse(self.compare()['complete'])

    def test_invalid_timestamps_cannot_supply_execution_order(self):
        for field in ('started_at_ns', 'finished_at_ns'):
            for invalid in (True, None, 0, -1, 2**63, '123', [], {}):
                with self.subTest(field=field, invalid=invalid):
                    self.after = [self.sample('after') for _ in range(3)]
                    before, after = self.write_samples()
                    self.after[0][field] = invalid
                    after[0].write_text(json.dumps(self.after[0]))
                    self.assertFalse(perf.compare(before, after)['complete'])

    def test_cli_outputs_json_tsv_and_correct_status(self):
        before, after = self.write_samples()
        output = self.directory / 'report'
        args = ['--before', *map(str, before), '--after', *map(str, after), '--output', str(output),
                '--jitter-relative', '0', '--jitter-absolute-s', '0']
        self.assertEqual(perf.main(args), 0)
        self.assertTrue(json.loads((output / 'comparison.json').read_text())['passed'])
        self.assertEqual(len((output / 'comparison.tsv').read_text().splitlines()), 10)
        self.after[0]['status'] = 'failed'
        self.write_samples()
        self.assertEqual(perf.main(args), 2)
        self.after = deepcopy(self.before)
        for sample in self.after:
            sample['wall_s'] += 1
            sample['started_at_ns'] += 4 * 10**12
            sample['finished_at_ns'] += 4 * 10**12
        self.write_samples()
        self.assertEqual(perf.main(args), 1)
        with self.assertRaisesRegex(ValueError, 'under repository ptmp'):
            perf.write_report({'comparisons': []}, perf.ROOT / 'comparison-outside-ptmp')


if __name__ == '__main__':
    unittest.main()
