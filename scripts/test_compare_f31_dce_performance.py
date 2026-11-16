"""Frozen small artifacts test evidence contracts, never full-graph performance."""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import statistics
import sys
import tempfile
import unittest
from unittest.mock import patch

from benchmark_f29_pass_trace import sha256, write_json_atomic
from benchmark_f30_pipeline import verified_dependencies, verified_input_request
import compare_f31_dce_performance as perf
from snapshot_f30_package import archived_source, snapshot
from test_benchmark_f30_pipeline import CACHE


def native_timer(engine, stage, instance, seconds):
    return {'schema': engine + '-stage-timing.v1', 'stage': stage, 'pass_instance': instance,
            'scope': 'pass', 'clock': 'steady_clock', 'wall_s': seconds, 'complete': True}


class DcePerformanceContractTests(unittest.TestCase):
    def setUp(self):
        root = perf.ROOT / 'ptmp/firrtl-ingest/F31/performance-contract'
        root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=root)
        self.work = Path(self.temporary.name)
        self.input = self.work / 'SimTop.fir'
        self.input.write_text('synthetic contract fixture, never a full performance run\n')
        self.expected = patch.object(perf, 'EXPECTED_INPUT_SHA256', sha256(self.input))
        self.expected.start()
        self.manifest = self.work / 'manifest.json'
        self.manifest.write_text(json.dumps({'schema': 'wolvrix.xs.firrtl-inputs.v1',
            'sources': [{'path': str(self.input), 'language': 'firrtl', 'unit': 'main'}], 'tops': ['SimTop']}))
        installed = self.work / 'installed/wolvrix'
        installed.mkdir(parents=True)
        (installed / '__init__.py').write_text('# package\n')
        (installed / '_wolvrix.so').write_bytes(b'extension fixture')
        (installed / 'libwolvrix-lib.so').write_bytes(b'core fixture')
        cache = self.work / 'CMakeCache.txt'
        cache.write_text(CACHE)
        archive, source_patch, head = (self.work / name for name in ('source.tar.gz', 'source.patch', 'head.txt'))
        archive.write_bytes(b'archived-baseline fixture')
        source_patch.write_bytes(b'archived patch fixture')
        head.write_text('1' * 40 + '\n')
        self.package = self.work / 'package'
        self.identity = snapshot(argparse.Namespace(output=self.package, existing_package=installed.parent,
            record_existing=False, build_cache=cache, source_root=self.work,
            source_archive=archive, source_patch=source_patch, head_file=head))
        self.native = {'package': str(self.package / 'wolvrix/__init__.py'), 'libraries': [
            {'path': str(self.package / name), 'sha256': sha256(self.package / name)}
            for name in ('wolvrix/_wolvrix.so', 'lib/libwolvrix-lib.so')]}
        revision, source = archived_source(archive, source_patch, head)
        binary = self.work / 'gsim'
        binary.write_bytes(b'GSIM executable fixture')
        self.gsim_native = {'schema': 'wolvrix.f30.gsim-native.v1', 'binary': str(binary),
            'sha256': sha256(binary), 'source_revision': revision, 'source': source,
            'source_patch': {'path': str(source_patch), 'sha256': sha256(source_patch)},
            'build_configuration_files': [{'path': 'Makefile', 'sha256': sha256(cache)}], 'libraries': []}
        self.gsim_identity = self.work / 'gsim-identity.json'
        write_json_atomic(self.gsim_identity, self.gsim_native)
        self.configuration = {'machine': ['Linux', 'fixture'], 'cpu_model': 'fixture CPU',
            'thread_environment': {'OMP_NUM_THREADS': None}, 'cpu_affinity': [0, 1]}
        self.groups = {key: [] for key in perf.GROUPS}
        for index in range(3):
            self.groups['gsim'].append(self.sample('gsim', 'no-trace', index, 10))
            self.groups['grh_no_trace'].append(self.sample('grh', 'no-trace', index, 10))
            self.groups['grh_trace'].append(self.sample('grh', 'trace', index, 10))

    def tearDown(self):
        self.expected.stop()
        self.temporary.cleanup()

    def sample(self, engine, mode, index, seconds):
        directory = self.work / (engine + '-' + mode + '-' + str(index))
        directory.mkdir()
        timing = directory / 'timing.jsonl'
        timers = ([native_timer('gsim', 'SplitArray', 'SplitArray#0', 25),
                   native_timer('gsim', 'RemoveDeadNodes', 'RemoveDeadNodes#0', seconds)] if engine == 'gsim' else
                  [native_timer('grh', 'dead-code-elim', 'dead-code-elim#0', seconds)])
        timing.write_text(''.join(json.dumps(row) + '\n' for row in timers))
        start = (index * 10 + 1) * 10**12 if engine == 'gsim' else (40 + index * 10 + (0 if mode == 'no-trace' else 3)) * 10**12
        value = {'schema': perf.INPUT_SCHEMA, 'engine': engine, 'mode': mode, 'verify': False,
            'status': 'passed', 'source': 'raw-firrtl', 'input': str(self.input), 'input_sha256': sha256(self.input),
            'configuration': deepcopy(self.configuration), 'started_at_ns': start, 'finished_at_ns': start + 10**12,
            'wall_s': 100, 'user_s': 90, 'system_s': 3, 'maxrss_kib': 1000,
            'timing_file': str(timing), 'timing_sha256': sha256(timing),
            'native_timers': timers if engine == 'grh' else {row['pass_instance']: row for row in timers},
            'dce': {'pass_s': seconds}}
        if engine == 'gsim':
            value.update(native=deepcopy(self.gsim_native), identity_file=str(self.gsim_identity),
                identity_sha256=sha256(self.gsim_identity), returncode=0,
                command=[self.gsim_native['binary'], '--dir', str(directory / 'model'),
                         '--stop-after-stage=RemoveDeadNodes0', '--timing-output=' + str(timing), str(self.input)])
        else:
            value.update(package_identity=deepcopy(self.identity), native=deepcopy(self.native),
                identity_file=str(self.package / 'identity.json'), identity_sha256=sha256(self.package / 'identity.json'),
                dependencies=verified_dependencies(self.package, self.package / 'dependencies.json', self.identity),
                sources=verified_input_request(self.input, self.manifest)[1], manifest=str(self.manifest),
                manifest_sha256=sha256(self.manifest), prefix={
                    'stages': [{'stage': name, 'wall_s': 10} for name in ('ingest', 'xmr-resolve', 'hier-flatten')],
                    'comb_split': {'status': 'passed', 'trace': False, 'skip_comb': False, 'passes': [
                        {'pass': name, 'status': 'passed', 'pass_returned': True}
                        for name in ('comb-loop-elim', 'split-static-array')]}})
            value['dce'].update(native_pass_s=seconds, user_s=9, system_s=1, maxrss_kib=1000,
                                boundary_s=seconds + (2 if mode == 'trace' else 0))
            if mode == 'trace':
                value['dce'].update(snapshot_setup_s=1, snapshot_export_s=1)
        return value

    def paths(self, *, rebind=True, trace_count=None):
        result = {}
        for group in perf.GROUPS:
            result[group] = [self.work / (group + '-' + str(index) + '.json')
                             for index in range(len(self.groups[group]))]
        for path, sample in zip(result['gsim'], self.groups['gsim']):
            write_json_atomic(path, sample)
        if rebind:
            median = statistics.median(sample['dce']['pass_s'] for sample in self.groups['gsim'])
            reference = {'median_s': median, 'limit_s': median + max(median * 0.03, 0.010),
                'dce_timeout_s': median * 2, 'split_timeout_s': 50,
                'samples': [{'path': str(path), 'sha256': sha256(path)} for path in result['gsim']]}
            for group in ('grh_no_trace', 'grh_trace'):
                for sample in self.groups[group]:
                    sample['reference'] = deepcopy(reference)
        for group in ('grh_no_trace', 'grh_trace'):
            for path, sample in zip(result[group], self.groups[group]):
                write_json_atomic(path, sample)
        if trace_count is not None:
            result['grh_trace'] = result['grh_trace'][:trace_count]
        return [result[group] for group in perf.GROUPS]

    def compare(self, **kwargs):
        return perf.compare(*self.paths(**kwargs))

    def change_seconds(self, group, seconds):
        for sample in self.groups[group]:
            sample['dce']['pass_s'] = seconds
            key = 'RemoveDeadNodes#0' if group == 'gsim' else 0
            sample['native_timers'][key]['wall_s'] = seconds
            if group != 'gsim':
                sample['dce']['native_pass_s'] = seconds
                sample['dce']['boundary_s'] = seconds + (2 if group == 'grh_trace' else 0)
            rows = sample['native_timers'].values() if group == 'gsim' else sample['native_timers']
            path = Path(sample['timing_file'])
            path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            sample['timing_sha256'] = sha256(path)

    def test_production_and_trace_modes_use_the_same_verified_native_denominator(self):
        report = self.compare()
        self.assertTrue(report['passed'], report['errors'])
        self.assertTrue(report['complete'])
        self.assertEqual(report['hard_limit'], 'passed')
        self.assertEqual([row['mode'] for row in report['comparisons']], ['no-trace'])
        self.assertTrue(report['trace_sanity']['passed'])
        self.assertEqual(report['trace_sanity']['limit_s'], 20)
        self.assertEqual(report['reference_evidence']['dce_timeout_s'], 20)
        self.assertEqual(report['jitter_policy'], {'relative': 0.03, 'absolute_s': 0.010})
        self.assertEqual([row['boundary_median_s'] for row in report['diagnostics']], [10, 12])
        self.assertEqual(sum(map(len, report['samples'].values())), 9)

    def test_trace_is_diagnostic_while_no_trace_keeps_fixed_jitter_gate(self):
        self.change_seconds('grh_no_trace', 10.3)
        self.change_seconds('grh_trace', 10.300001)
        report = perf.compare(*self.paths(trace_count=1))
        self.assertTrue(report['complete'], report['errors'])
        self.assertTrue(report['passed'], report['errors'])
        self.assertEqual(report['hard_limit'], 'passed')
        self.assertEqual([row['classification'] for row in report['comparisons']], ['within_jitter'])
        self.assertEqual(report['trace_sanity']['classification'], 'acceptable')

    def test_one_trace_sample_is_enough_but_must_stay_within_two_times_gsim(self):
        report = perf.compare(*self.paths(trace_count=1))
        self.assertTrue(report['passed'], report['errors'])
        self.assertEqual(len(report['samples']['grh_trace']), 1)
        self.change_seconds('grh_trace', 20.1)
        report = self.compare(trace_count=1)
        self.assertFalse(report['passed'])
        self.assertEqual(report['trace_sanity']['classification'], 'too_slow')
        self.assertEqual(report['hard_limit'], 'failed')

    def test_absolute_jitter_has_fixed_ten_millisecond_floor(self):
        self.change_seconds('gsim', 0.1)
        self.change_seconds('grh_no_trace', 0.11)
        self.change_seconds('grh_trace', 0.110001)
        report = self.compare()
        self.assertEqual(report['comparisons'][0]['limit_s'], 0.11)
        self.assertEqual([row['classification'] for row in report['comparisons']], ['within_jitter'])
        self.assertTrue(report['trace_sanity']['passed'])

    def test_one_mode_cannot_be_missing_or_short_and_paths_must_be_distinct(self):
        gsim, off, on = self.paths()
        for args in ((gsim, off[:2], on), (gsim[:2], off, on), (gsim, [off[0]] * 3, on), (gsim, off, [])):
            with self.subTest(args=args):
                report = perf.compare(*args)
                self.assertFalse(report['complete'])
                self.assertFalse(report['passed'])

    def test_failed_and_timed_out_samples_are_retained_and_never_pass(self):
        sample = self.groups['grh_trace'][0]
        sample.update(status='failed', error='DCE timeout', dce_failure={'passes': [{'status': 'timeout', 'pass_s': 20.1}]})
        report = self.compare()
        self.assertFalse(report['passed'])
        self.assertFalse(report['complete'])
        self.assertEqual(report['hard_limit'], 'failed')
        self.assertEqual(len(report['samples']['grh_trace']), 3)
        self.assertEqual(report['samples']['grh_trace'][0]['raw'], sample)
        self.assertIsNone(report['samples']['grh_trace'][0]['hard_limit']['completion_time_s'])

    def test_slow_individual_sample_cannot_hide_behind_median(self):
        sample = self.groups['grh_no_trace'][0]
        sample['dce'].update(pass_s=20.1, boundary_s=20.1)
        report = self.compare()
        self.assertTrue(report['complete'], report['errors'])
        self.assertEqual(report['comparisons'][0]['classification'], 'pass')
        self.assertFalse(report['passed'])
        self.assertEqual(report['hard_limit'], 'failed')

    def test_wrong_native_instance_and_timing_summary_tampering_fail_closed(self):
        sample = self.groups['gsim'][0]
        sample['native_timers']['RemoveDeadNodes#0']['wall_s'] = 9
        report = self.compare()
        self.assertFalse(report['complete'])
        self.assertIn('timers differ', '\n'.join(report['errors']))
        sample['native_timers']['RemoveDeadNodes#0']['wall_s'] = 10
        sample['dce']['pass_s'] = 9
        self.assertIn('denominator differs', '\n'.join(self.compare()['errors']))

    def test_native_raw_file_hash_and_schema_are_validated(self):
        sample = self.groups['grh_trace'][0]
        path = Path(sample['timing_file'])
        path.write_text(path.read_text() + '\n')
        self.assertFalse(self.compare()['complete'])
        sample['timing_sha256'] = sha256(path)
        sample['native_timers'][0]['complete'] = False
        path.write_text(json.dumps(sample['native_timers'][0]) + '\n')
        sample['timing_sha256'] = sha256(path)
        self.assertIn('incomplete or invalid', '\n'.join(self.compare()['errors']))

    def test_grh_time_cannot_exclude_native_or_snapshot_work(self):
        sample = self.groups['grh_trace'][0]
        sample['dce']['pass_s'] = 9
        self.assertIn('excludes native', '\n'.join(self.compare()['errors']))
        sample['dce']['pass_s'] = 10
        sample['dce']['boundary_s'] = 10
        self.assertIn('omits pass or snapshot', '\n'.join(self.compare()['errors']))

    def test_machine_thread_input_and_affinity_must_match_all_modes(self):
        sample = self.groups['grh_trace'][0]
        for field, changed in (('machine', ['other']), ('cpu_model', 'other CPU'),
                               ('cpu_affinity', [2]), ('thread_environment', {'OMP_NUM_THREADS': '8'})):
            before = deepcopy(sample['configuration'])
            sample['configuration'][field] = changed
            with self.subTest(field=field):
                self.assertFalse(self.compare()['complete'])
            sample['configuration'] = before
        sample['input_sha256'] = 'f' * 64
        self.assertIn('complete F30/F31 SimTop', '\n'.join(self.compare()['errors']))

    def test_trace_gsim_reference_verify_and_checkpoint_are_rejected(self):
        for group, field, invalid in (('gsim', 'mode', 'trace'), ('grh_no_trace', 'verify', True),
                                      ('grh_trace', 'source', 'checkpoint')):
            sample = self.groups[group][0]
            original = sample[field]
            sample[field] = invalid
            with self.subTest(group=group, field=field):
                self.assertFalse(self.compare()['complete'])
            sample[field] = original

    def test_gsim_command_must_be_untraced_first_dce_from_raw_input(self):
        sample = self.groups['gsim'][0]
        sample['command'].insert(-1, '--semantic-node-exchange-mode=trace')
        self.assertIn('untraced raw first-DCE', '\n'.join(self.compare()['errors']))

    def test_frozen_native_source_binary_package_and_inputs_are_rechecked(self):
        targets = [Path(self.gsim_native['binary']), Path(self.identity['source']['patch']),
                   self.package / 'lib/libwolvrix-lib.so', self.manifest, self.input]
        for target in targets:
            original = target.read_bytes()
            target.write_bytes(original + b'tampered')
            with self.subTest(target=target):
                self.assertFalse(self.compare()['complete'])
            target.write_bytes(original)

    def test_mismatching_native_library_cannot_borrow_package_provenance(self):
        self.groups['grh_trace'][0]['native']['libraries'][0]['sha256'] = 'f' * 64
        self.assertIn('loaded native library', '\n'.join(self.compare()['errors']))

    def test_recorded_package_identity_hash_cannot_disagree_with_actual_file(self):
        self.groups['grh_trace'][0]['identity_sha256'] = 'f' * 64
        self.assertIn('artifact hash mismatch', '\n'.join(self.compare()['errors']))

    def test_frozen_watchdog_reference_cannot_be_changed_or_slow_reference_substituted(self):
        paths = self.paths()
        self.groups['grh_trace'][0]['reference']['dce_timeout_s'] = 100
        self.paths(rebind=False)
        report = perf.compare(*paths)
        self.assertFalse(report['complete'])
        self.assertEqual(report['samples']['grh_trace'][0]['hard_limit']['status'], 'unverified')
        self.assertIn('same supplied GSIM denominator', '\n'.join(report['errors']))

    def test_sequences_are_nonoverlapping_without_trace_alternation(self):
        sample = self.groups['grh_trace'][0]
        original = sample['started_at_ns']
        sample['started_at_ns'] = self.groups['grh_no_trace'][0]['started_at_ns']
        self.assertIn('overlap', '\n'.join(self.compare()['errors']))
        sample['started_at_ns'] = original
        self.groups['grh_trace'][0]['started_at_ns'] = 90 * 10**12
        self.groups['grh_trace'][0]['finished_at_ns'] = 91 * 10**12
        report = perf.compare(*self.paths(trace_count=1))
        self.assertTrue(report['complete'], report['errors'])

    def test_instrumented_or_nonfinite_samples_are_never_accepted(self):
        sample = self.groups['grh_trace'][0]
        sample['configuration']['instrumentation'] = {'profile': True}
        self.assertFalse(self.compare()['complete'])
        sample['configuration'].pop('instrumentation')
        sample['configuration']['profiling_environment'] = {'WOLVRIX_CLE_DEBUG': '0'}
        self.assertFalse(self.compare()['complete'])
        sample['configuration'].pop('profiling_environment')
        sample['dce']['pass_s'] = float('nan')
        report = self.compare()
        self.assertFalse(report['complete'])
        self.assertIn('raw_json', report['samples']['grh_trace'][0])

    def test_malformed_nested_records_are_retained_instead_of_crashing(self):
        sample = self.groups['grh_trace'][0]
        for field in ('prefix', 'dce', 'started_at_ns'):
            original = deepcopy(sample[field])
            sample[field] = []
            with self.subTest(field=field):
                report = self.compare()
                self.assertFalse(report['complete'])
                self.assertEqual(report['samples']['grh_trace'][0]['raw'], sample)
            sample[field] = original
        sample['configuration']['instrumentation'] = []
        self.assertFalse(self.compare()['complete'])

    def test_sources_changing_after_inspection_prevent_publication(self):
        real = perf.inspect_sample
        calls = 0

        def mutate(*args):
            nonlocal calls
            result = real(*args)
            calls += 1
            if calls == 9:
                self.input.write_bytes(self.input.read_bytes() + b'changed during comparison')
            return result

        with patch.object(perf, 'inspect_sample', side_effect=mutate):
            report = self.compare()
        self.assertFalse(report['complete'])
        self.assertIn('artifact changed during comparison', '\n'.join(report['errors']))

    def test_cli_has_no_option_to_relax_fixed_jitter(self):
        args = ['compare', '--gsim', 'g', '--grh-no-trace', 'r', '--grh-trace', 't',
                '--output', str(self.work / 'output'), '--jitter-relative', '0.5']
        error = StringIO()
        with patch.object(sys, 'argv', args), redirect_stderr(error):
            with self.assertRaises(SystemExit) as result:
                perf.main()
        self.assertEqual(result.exception.code, 2)
        self.assertIn('unrecognized arguments: --jitter-relative 0.5', error.getvalue())


if __name__ == '__main__':
    unittest.main()
