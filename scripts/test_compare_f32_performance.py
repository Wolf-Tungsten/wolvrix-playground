"""Small immutable evidence fixtures exercise the F32 performance gate."""
from __future__ import annotations

from copy import deepcopy
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import compare_f32_performance as perf


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2) + '\n')


def timer(engine, stage, instance, seconds, scope='pass'):
    return {'schema': engine + '-stage-timing.v1', 'stage': stage, 'pass_instance': instance,
            'scope': scope, 'clock': 'steady_clock', 'wall_s': seconds, 'complete': True}


class F32PerformanceTests(unittest.TestCase):
    def setUp(self):
        root = Path(os.environ.get('F32_PERFORMANCE_TEST_ROOT', perf.ROOT / 'ptmp/firrtl-ingest/F32/performance-contract'))
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.work = Path(self.temp.name)
        self.input = self.work / 'SimTop.fir'
        self.input.write_text('fixture, not a performance input\n')
        self.source_manifest = self.work / 'sources.json'
        write_json(self.source_manifest, {'schema': 'wolvrix.xs.firrtl-inputs.v1',
                                         'sources': [{'path': str(self.input), 'language': 'firrtl'}]})
        self.input_patch = patch.object(perf, 'INPUT_SHA256', perf.file_sha256(self.input))
        self.input_patch.start()
        self.package = self.work / 'package'
        self.package.mkdir()
        self.dependencies = self.package / 'dependencies.json'
        write_json(self.dependencies, {'content_sha256': 'd' * 64})
        self.package_identity = {'schema': 'fixture-package', 'package': str(self.package),
                                 'build': {'CMAKE_BUILD_TYPE': 'Release'}}
        write_json(self.package / 'identity.json', self.package_identity)
        self.package_patch = patch.object(perf, 'verify_package_identity', return_value=deepcopy(self.package_identity))
        self.package_patch.start()
        self.loaded_patch = patch.object(perf, 'verify_loaded_native')
        self.loaded_patch.start()
        self.dependency_patch = patch.object(perf, 'verified_dependencies', return_value={'content_sha256': 'd' * 64})
        self.dependency_patch.start()
        self.provenance_patch = patch.object(perf, 'verify_source_provenance')
        self.provenance_patch.start()
        native_dir = self.work / 'gsim-freeze'
        native_dir.mkdir()
        binary = native_dir / 'gsim'
        binary.write_bytes(b'fake gsim binary')
        archive = native_dir / 'source.tar.gz'
        archive.write_bytes(b'fake source archive')
        source_patch = native_dir / 'source.patch'
        source_patch.write_bytes(b'fake source patch')
        self.gsim_identity = {'schema': 'wolvrix.f30.gsim-native.v1', 'binary': str(binary),
            'sha256': perf.file_sha256(binary), 'source_revision': 'fixture',
            'source': {'archive': str(archive), 'archive_sha256': perf.file_sha256(archive)},
            'source_patch': {'path': str(source_patch), 'sha256': perf.file_sha256(source_patch)}, 'libraries': []}
        self.gsim_identity_path = native_dir / 'identity.json'
        write_json(self.gsim_identity_path, self.gsim_identity)
        self.group_path = self.work / 'group.json'
        self.result_path = self.work / 'results.json'
        self.group = {'schema': perf.GROUP_SCHEMA, 'status': 'frozen', 'group_id': 'fixture-group',
            'created_at_ns': 100, 'input': str(self.input), 'input_sha256': perf.INPUT_SHA256,
            'source_manifest': str(self.source_manifest), 'source_manifest_sha256': perf.file_sha256(self.source_manifest),
            'sources': [{'path': str(self.input), 'language': 'firrtl', 'unit': None,
                         'bytes': self.input.stat().st_size, 'sha256': perf.INPUT_SHA256}],
            'package': str(self.package), 'package_identity_sha256': perf.file_sha256(self.package / 'identity.json'),
            'dependencies_content_sha256': 'd' * 64, 'gsim_identity': str(self.gsim_identity_path),
            'gsim_identity_sha256': perf.file_sha256(self.gsim_identity_path),
            'gsim_binary_sha256': self.gsim_identity['sha256'],
            'configuration': {'machine': ['fixture'], 'cpu_model': 'fixture',
                              'thread_environment': {'OMP_NUM_THREADS': '1', 'TBB_NUM_THREADS': '1', 'WOLVRIX_THREADS': '1'},
                              'loader_environment': {'LD_PRELOAD': None, 'LD_LIBRARY_PATH': None},
                              'cpu_affinity': [2], 'profiling_environment': {'PROFILE': None},
                              'instrumentation': {'trace': False, 'snapshot': False, 'export': False,
                                                  'verify': False, 'profile': False, 'statistics': False}},
            'measurement': {'repeats_per_engine': 3, 'mode': 'no-trace', 'window_semantics': '2state',
                            'exports': False, 'verification': False, 'profile': False, 'build_type': 'Release',
                            'source': 'raw-firrtl'},
            'limits': {'rss_bytes': 96 * 1024**3, 'psi_percent': 25, 'psi_seconds': 8,
                       'sample_interval_s': .25, 'split_nodes_timeout_s': 180},
            'schedule': ['grh', 'gsim'] * 3}
        self.samples = []
        self.rows = []
        self.freeze_group()
        for sequence, engine in enumerate(self.group['schedule'], 1):
            sample, row = self.new_sample(sequence, engine)
            self.samples.append(sample)
            self.rows.append(row)

    def tearDown(self):
        for p in (self.input_patch, self.package_patch, self.loaded_patch, self.dependency_patch, self.provenance_patch):
            p.stop()
        self.temp.cleanup()

    def freeze_group(self):
        self.group.pop('manifest_sha256', None)
        self.group['manifest_sha256'] = hashlib.sha256(json.dumps(
            self.group, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        write_json(self.group_path, self.group)

    def native_file(self, directory, filename, rows):
        path = directory / filename
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        return path

    def new_sample(self, sequence, engine):
        directory = self.work / 'samples' / f'{sequence:02d}-{engine}'
        directory.mkdir(parents=True)
        start = sequence * 10**12
        sample = {'schema': perf.SAMPLE_SCHEMA, 'status': 'passed', 'engine': engine,
            'source': 'raw-firrtl', 'group_id': self.group['group_id'], 'group_manifest': str(self.group_path),
            'group_manifest_sha256': perf.file_sha256(self.group_path), 'input': str(self.input),
            'input_sha256': perf.INPUT_SHA256, 'window_semantics': '2state',
            'stop_after_stage': 'post-second-dead-code-elim', 'configuration': deepcopy(self.group['configuration']),
            'cpu_affinity': deepcopy(self.group['configuration']['cpu_affinity']),
            'instrumentation': {'trace': False, 'dump': False, 'verify': False, 'profile': False, 'export': False},
            'started_at_ns': start + 1, 'finished_at_ns': start + 10**11,
            'wall_s': 100.0, 'user_s': 90.0, 'system_s': 2.0, 'maxrss_kib': 1000,
            'active_stage': {'name': 'complete', 'finished': True}, 'window_passes': [], 'logical_window': [],
            'prefix': [], 'metrics': {}, 'native_returncode': 0, 'returncode': 0}
        native_rows = []
        if engine == 'grh':
            sample['native'] = {'package': str(self.package / 'wolvrix/__init__.py'), 'libraries': []}
            sample['package_identity'] = deepcopy(self.package_identity)
            sample['sources'] = deepcopy(self.group['sources'])
            sample['prefix'] = [{'stage': 'ingest', 'wall_s': 1}]
            for name in ('xmr-resolve', 'hier-flatten', 'comb-loop-elim', 'split-static-array', 'dead-code-elim'):
                native = timer('grh', name, name + '#0', 1.0)
                timing = self.native_file(directory, name + '-0.jsonl', [native])
                sample['prefix'].append({'pass': name, 'logical_instance': name + '#0', 'native_timer': native,
                    'timing_file': str(timing), 'timing_sha256': perf.file_sha256(timing)})
        else:
            sample['native'] = deepcopy(self.gsim_identity)
            sample['prefix'] = [timer('gsim', stage, stage + '#0', 1.0) for stage in perf.GSIM_PREFIX]
            native_rows.extend(sample['prefix'])
        for index, name in enumerate(perf.PASSES):
            logical, stage, instance = perf.EXPECTED[engine][name]
            native = timer(engine, stage, instance, 10.0)
            pass_record = {'pass': name, 'logical_instance': logical, 'native_timer': native}
            if engine == 'grh':
                path = self.native_file(directory, name + '-window.jsonl', [native])
                pass_record.update(timing_file=str(path), timing_sha256=perf.file_sha256(path))
            else:
                native_rows.append(native)
            sample['window_passes'].append(pass_record)
            sample['logical_window'].append({'logical_pass': name, 'logical_occurrence': index, 'native_timer': native})
            sample['metrics'][name] = 10.0
        sample['window'] = {'wall_s': 40.1, 'native_pass_sum_s': 40.0, 'framework_overhead_s': 0.1,
                            'clock': 'steady_clock'}
        if engine == 'gsim':
            window = timer('gsim', 'F32Window', 'F32Window#0', 40.1, 'window')
            native_rows.append(window)
            timing = self.native_file(directory, 'native-timing.jsonl', native_rows)
            sample.update(timing_file=str(timing), timing_sha256=perf.file_sha256(timing), native_timers=native_rows)
            sample['command'] = [self.gsim_identity['binary'], '--dir', str(directory / 'model'),
                                 '--stop-after-stage=RemoveDeadNodes1', '--timing-output=' + str(timing), str(self.input)]
            sample['window']['native_timer'] = window
        else:
            sample.update(window_started_at_ns=start + 10**9,
                          window_finished_at_ns=start + 10**9 + int(40.1 * 1e9))
        sample['metrics']['window'] = sample['window']['wall_s']
        guard = {'schema': 'wolvrix.f30.resource-guard.v1', 'status': 'completed', 'reason': 'child_completed',
                 'returncode': 0, 'limits': {'rss_bytes': 96 * 1024**3, 'psi_percent': 25,
                                           'psi_seconds': 8, 'interval_s': .25},
                 'phase_timeouts_s': {'split-nodes#0': 180}}
        guard_path = directory / 'guard.json'
        write_json(guard_path, guard)
        snapshot = {'captured_at_ns': start, 'loadavg_1_5_15': [0.1, 0.1, 0.1],
                    'memory_bytes': {'MemAvailable': 100 * 1024**3}, 'cpu_affinity': [2]}
        row = {'sequence': sequence, 'engine': engine, 'directory': str(directory),
               'summary_file': str(directory / 'summary.json'), 'status': 'passed',
               'started_at_ns': start, 'finished_at_ns': start + 10**11 + 1,
               'guard_file': str(guard_path), 'guard_sha256': perf.file_sha256(guard_path), 'returncode': 0,
               'system_before': snapshot,
               'system_after': {**snapshot, 'captured_at_ns': start + 10**11 + 1}}
        return sample, row

    def write(self):
        group_hash = perf.file_sha256(self.group_path)
        for sample, row in zip(self.samples, self.rows):
            sample['group_manifest_sha256'] = group_hash
            write_json(row['summary_file'], sample)
            row['summary_sha256'] = perf.file_sha256(row['summary_file'])
        results = {'schema': perf.RESULT_SCHEMA, 'status': 'completed', 'group_id': self.group['group_id'],
                   'group_manifest': str(self.group_path), 'group_manifest_sha256': group_hash,
                   'started_at_ns': 1000, 'finished_at_ns': 10**13, 'samples': self.rows}
        write_json(self.result_path, results)
        return self.result_path

    def compare(self):
        return perf.compare(self.write())

    def add_future_group_observations(self):
        directory = self.work / 'frozen-tools'
        directory.mkdir()
        files = []
        for name in ('benchmark_f32_passes.py', 'f30_resource_guard.py'):
            path = directory / name
            path.write_text('fixture ' + name + '\n')
            files.append({'path': str(path), 'sha256': perf.file_sha256(path)})
        self.group['tool_identity'] = {'schema': 'wolvrix.f32.benchmark-tools.v1', 'files': files}
        self.freeze_group()
        observed = {key: deepcopy(self.group['configuration'][key]) for key in perf.OBSERVED_CONFIGURATION_KEYS}
        for sample in self.samples:
            sample['tool_identity'] = deepcopy(self.group['tool_identity'])
            sample['observed_configuration'] = deepcopy(observed)
            sample['observed_configuration_after'] = deepcopy(observed)

    def change_metric(self, engine, name, values):
        targets = [sample for sample in self.samples if sample['engine'] == engine]
        for sample, value in zip(targets, values):
            record = next(record for record in sample['window_passes'] if record['pass'] == name)
            record['native_timer']['wall_s'] = value
            next(item for item in sample['logical_window'] if item['logical_pass'] == name)['native_timer']['wall_s'] = value
            sample['metrics'][name] = value
            native_sum = sum(sample['metrics'][p] for p in perf.PASSES)
            sample['window'].update(native_pass_sum_s=native_sum, wall_s=native_sum + 0.1)
            sample['metrics']['window'] = native_sum + 0.1
            if engine == 'grh':
                sample['window_finished_at_ns'] = sample['window_started_at_ns'] + int((native_sum + .1) * 1e9)
                path = Path(record['timing_file'])
                self.native_file(path.parent, path.name, [record['native_timer']])
                record['timing_sha256'] = perf.file_sha256(path)
            else:
                sample['window']['native_timer']['wall_s'] = native_sum + 0.1
                self.native_file(Path(sample['timing_file']).parent, 'native-timing.jsonl', sample['native_timers'])
                sample['timing_sha256'] = perf.file_sha256(sample['timing_file'])

    def test_complete_new_interleaved_samples_pass_five_independent_gates(self):
        report = self.compare()
        self.assertTrue(report['passed'], report['errors'])
        self.assertTrue(report['complete'])
        self.assertEqual([row['metric'] for row in report['comparisons']], [*perf.PASSES, 'window'])
        self.assertEqual(report['sample_counts'], {'grh': 3, 'gsim': 3})

    def test_slow_individual_pass_cannot_hide_behind_faster_other_passes(self):
        self.change_metric('grh', 'expr-opt', [1, 1, 1])
        self.change_metric('grh', 'used-bits', [11, 11, 11])
        report = self.compare()
        self.assertTrue(report['complete'], report['errors'])
        self.assertFalse(report['passed'])
        rows = {row['metric']: row for row in report['comparisons']}
        self.assertFalse(rows['used-bits']['within_gate'])
        self.assertTrue(rows['window']['within_gate'])

    def test_relative_threshold_and_absolute_floor_are_applied_exactly(self):
        self.change_metric('grh', 'used-bits', [10.3] * 3)
        report = self.compare()
        self.assertTrue(report['passed'], report['errors'])
        self.change_metric('grh', 'used-bits', [10.300001] * 3)
        self.assertFalse(self.compare()['passed'])
        self.change_metric('gsim', 'expr-opt', [0.1] * 3)
        self.change_metric('grh', 'expr-opt', [0.11] * 3)
        row = next(row for row in self.compare()['comparisons'] if row['metric'] == 'expr-opt')
        self.assertEqual(row['allowed_delta_s'], 0.010)
        self.assertTrue(row['within_gate'])

    def test_high_jitter_requires_a_new_whole_paired_group(self):
        self.change_metric('grh', 'used-bits', [9.0, 10.0, 11.0])
        report = self.compare()
        self.assertTrue(report['complete'], report['errors'])
        self.assertFalse(report['passed'])
        self.assertFalse(next(row for row in report['comparisons'] if row['metric'] == 'used-bits')['stable'])

    def test_failed_sample_is_retained_and_group_cannot_pass(self):
        self.samples[0]['status'] = 'failed'
        self.rows[0]['status'] = 'failed'
        report = self.compare()
        self.assertFalse(report['complete'])
        self.assertFalse(report['passed'])
        self.assertEqual(len(report['samples']), 6)
        self.assertIn('failed', '\n'.join(report['errors']))

    def test_schedule_overlap_and_prior_reused_samples_fail_closed(self):
        self.samples[2]['started_at_ns'] = self.samples[1]['started_at_ns']
        self.rows[2]['started_at_ns'] = self.rows[1]['started_at_ns']
        report = self.compare()
        self.assertFalse(report['passed'])
        self.assertIn('overlap', '\n'.join(report['errors']))
        self.rows[2]['started_at_ns'] = 3 * 10**12
        self.samples[2]['started_at_ns'] = 99
        self.assertIn('predates', '\n'.join(self.compare()['errors']))

    def test_wrong_native_dce_instance_and_raw_hash_tampering_fail(self):
        self.samples[1]['logical_window'][-1]['native_timer']['pass_instance'] = 'RemoveDeadNodes#0'
        report = self.compare()
        self.assertFalse(report['passed'])
        self.assertIn('wrong native', '\n'.join(report['errors']))
        path = Path(self.samples[0]['window_passes'][0]['timing_file'])
        path.write_text(path.read_text() + '\n')
        self.assertIn('SHA256 mismatch', '\n'.join(self.compare()['errors']))

    def test_configuration_instrumentation_and_group_internal_hash_cannot_change(self):
        self.samples[0]['configuration']['cpu_affinity'] = [3]
        self.assertIn('configuration', '\n'.join(self.compare()['errors']))
        self.samples[0]['configuration'] = deepcopy(self.group['configuration'])
        self.samples[0]['instrumentation']['profile'] = True
        self.assertIn('profiling', '\n'.join(self.compare()['errors']))
        self.group['measurement']['profile'] = True
        write_json(self.group_path, self.group)
        self.assertIn('canonical', '\n'.join(self.compare()['errors']))

    def test_missing_native_window_or_wrong_guard_result_cannot_pass(self):
        sample = self.samples[1]
        sample['native_timers'] = [row for row in sample['native_timers'] if row.get('scope') != 'window']
        self.native_file(Path(sample['timing_file']).parent, 'native-timing.jsonl', sample['native_timers'])
        sample['timing_sha256'] = perf.file_sha256(sample['timing_file'])
        self.assertIn('whole window', '\n'.join(self.compare()['errors']))
        guard_path = Path(self.rows[0]['guard_file'])
        guard = json.loads(guard_path.read_text())
        guard.update(status='failed', reason='phase_timeout', returncode=-9)
        write_json(guard_path, guard)
        self.rows[0]['guard_sha256'] = perf.file_sha256(guard_path)
        self.assertIn('resource guard', '\n'.join(self.compare()['errors']))

    def test_whole_window_gate_cannot_be_replaced_by_four_pass_sum(self):
        for sample in self.samples[::2]:
            sample['window'].update(wall_s=41.5, framework_overhead_s=1.5)
            sample['metrics']['window'] = 41.5
            sample['window_finished_at_ns'] = sample['window_started_at_ns'] + int(41.5 * 1e9)
        report = self.compare()
        self.assertTrue(report['complete'], report['errors'])
        self.assertFalse(report['passed'])
        self.assertTrue(all(row['passed'] for row in report['comparisons'][:-1]))
        self.assertFalse(report['comparisons'][-1]['passed'])

    def test_frozen_schedule_requires_interleaving_and_all_samples(self):
        self.group['schedule'] = ['grh'] * 3 + ['gsim'] * 3
        self.freeze_group()
        self.assertIn('interleave', '\n'.join(self.compare()['errors']))
        self.group['schedule'] = ['grh', 'gsim'] * 3
        self.freeze_group()
        self.rows.pop()
        self.assertIn('omits', '\n'.join(self.compare()['errors']))

    def test_pinned_guard_tampering_and_duplicate_sample_path_are_rejected(self):
        guard_path = Path(self.rows[0]['guard_file'])
        guard_path.write_text(guard_path.read_text() + '\n')
        self.assertIn('SHA256 mismatch', '\n'.join(self.compare()['errors']))
        self.rows[2]['summary_file'] = self.rows[0]['summary_file']
        self.assertIn('reuse', '\n'.join(self.compare()['errors']))

    def test_artifact_recheck_failure_cannot_leave_passed_result(self):
        with patch.object(perf.ArtifactSet, 'recheck', side_effect=ValueError('artifact changed during comparison')):
            report = self.compare()
        self.assertFalse(report['passed'])
        self.assertFalse(report['complete'])
        self.assertEqual(report['status'], 'incomplete')

    def test_cli_writes_incomplete_report_for_invalid_group(self):
        bad = self.work / 'invalid.json'
        write_json(bad, {'schema': 'invalid'})
        output = self.work / 'invalid-report'
        with redirect_stdout(io.StringIO()):
            code = perf.main(['--benchmark', str(bad), '--output', str(output)])
        self.assertEqual(code, 2)
        report = json.loads((output / 'summary.json').read_text())
        self.assertEqual(report['sample_counts'], {'grh': 0, 'gsim': 0})
        self.assertTrue(report['performance_only'])
        self.assertFalse(report['semantic_acceptance'])

    def test_thread_policy_raw_prefix_and_disabled_exports_are_checked(self):
        self.group['configuration']['thread_environment']['OMP_NUM_THREADS'] = '8'
        self.freeze_group()
        self.assertIn('thread policy', '\n'.join(self.compare()['errors']))
        self.group['configuration']['thread_environment']['OMP_NUM_THREADS'] = '1'
        self.freeze_group()
        self.samples[1]['command'].insert(1, '--dump-all')
        self.assertIn('GSIM command', '\n'.join(self.compare()['errors']))
        self.samples[1]['command'].remove('--dump-all')
        self.samples[1]['prefix'].pop(0)
        self.assertIn('exact normal raw prefix', '\n'.join(self.compare()['errors']))

    def test_new_group_pins_tools_and_records_verified_child_observations(self):
        self.add_future_group_observations()
        report = self.compare()
        self.assertTrue(report['passed'], report['errors'])
        self.assertTrue(report['execution_evidence']['tool_identity_required'])
        self.assertEqual(report['execution_evidence']['limitations'], [])
        for item in self.group['tool_identity']['files']:
            self.assertEqual(report['verified_artifacts'][item['path']], item['sha256'])
        for sample in report['samples']:
            self.assertTrue(sample['execution_evidence']['tool_sources_verified'])
            self.assertTrue(sample['execution_evidence']['child_observations_verified'])
            self.assertEqual(sample['tool_identity'], self.group['tool_identity'])
            self.assertEqual(sample['observed_configuration']['cpu_affinity'], [2])

    def test_new_group_rejects_tampered_actual_observation_before_or_after(self):
        self.add_future_group_observations()
        for field in ('observed_configuration', 'observed_configuration_after'):
            original = deepcopy(self.samples[1][field])
            for key, value in (('cpu_affinity', [3]),
                               ('thread_environment', {'OMP_NUM_THREADS': '8'}),
                               ('loader_environment', {'LD_PRELOAD': 'other.so'}),
                               ('profiling_environment', {'PROFILE': '1'})):
                with self.subTest(field=field, key=key):
                    self.samples[1][field] = {**deepcopy(original), key: value}
                    report = self.compare()
                    self.assertFalse(report['passed'])
                    self.assertIn(field + ': actual child environment', '\n'.join(report['errors']))
            self.samples[1][field] = original
        del self.samples[0]['observed_configuration_after']
        self.assertIn('observed_configuration_after', '\n'.join(self.compare()['errors']))

    def test_new_group_rejects_tool_file_hash_or_sample_identity_drift(self):
        self.add_future_group_observations()
        self.samples[1]['tool_identity']['files'][0]['sha256'] = 'c' * 64
        report = self.compare()
        self.assertFalse(report['passed'])
        self.assertIn('tool identity differs', '\n'.join(report['errors']))
        self.samples[1]['tool_identity'] = deepcopy(self.group['tool_identity'])
        Path(self.group['tool_identity']['files'][1]['path']).write_text('changed guard\n')
        self.assertIn('SHA256 mismatch', '\n'.join(self.compare()['errors']))

    def test_new_group_cannot_substitute_missing_or_duplicate_tool_records(self):
        self.add_future_group_observations()
        original = deepcopy(self.group['tool_identity'])
        for invalid in (None, {'schema': original['schema'], 'files': []},
                        {'schema': original['schema'], 'files': [original['files'][0]] * 2}):
            with self.subTest(identity=invalid):
                self.group['tool_identity'] = invalid
                self.freeze_group()
                report = self.compare()
                self.assertFalse(report['passed'])
                self.assertFalse(report['complete'])
                self.assertTrue(report['errors'])

    def test_old_group_remains_inspectable_without_fabricated_child_observations(self):
        report = self.compare()
        self.assertTrue(report['passed'], report['errors'])
        self.assertFalse(report['execution_evidence']['tool_identity_required'])
        self.assertIsNone(report['execution_evidence']['tool_identity'])
        self.assertTrue(report['execution_evidence']['limitations'])
        for sample in report['samples']:
            self.assertFalse(sample['execution_evidence']['tool_sources_verified'])
            self.assertFalse(sample['execution_evidence']['child_observations_verified'])
            self.assertNotIn('observed_configuration', sample)
            self.assertNotIn('tool_identity', sample)


@unittest.skipUnless(os.environ.get('F32_PERFORMANCE_RUNNER_GROUP'),
                     'optional read-only check of an actual runner group')
class ActualRunnerEvidenceTests(unittest.TestCase):
    def test_completed_actual_runner_samples_match_comparator_schema(self):
        directory = Path(os.environ['F32_PERFORMANCE_RUNNER_GROUP']).resolve()
        group_path = directory / 'group.json'
        manifest = perf.load_json(group_path)
        results = perf.load_json(directory / 'results.json')
        artifacts = perf.ArtifactSet()
        group_hash = results['group_manifest_sha256']
        artifacts.check(group_path, group_hash)
        completed = [row for row in results['samples'] if row.get('status') == 'passed']
        self.assertTrue(completed, 'no completed actual sample available for schema review')
        accepted = []
        for row in completed:
            sample = perf.inspect_sample(row, row['engine'], manifest['group_id'], group_hash,
                                         manifest, manifest['configuration'], artifacts)
            accepted.append({key: value for key, value in sample.items() if key != 'sample'})
        artifacts.recheck()
        root = Path(os.environ['F32_PERFORMANCE_TEST_ROOT'])
        root.mkdir(parents=True, exist_ok=True)
        write_json(root / 'actual-runner-schema-check.json', {
            'scope': 'read-only contract check of completed rows from the actual runner',
            'performance_acceptance': False, 'semantic_acceptance': False,
            'group_id': manifest['group_id'], 'group_status_observed': results['status'],
            'accepted_samples': accepted, 'verified_artifacts': artifacts.records})


if __name__ == '__main__':
    unittest.main()
