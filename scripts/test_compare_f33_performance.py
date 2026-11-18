"""Contract tests for the F33 formal performance comparison gates."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import compare_f33_performance as performance


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    return path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class F33PerformanceTests(unittest.TestCase):
    def setUp(self):
        root = performance.ROOT / 'ptmp/firrtl-ingest/F33/performance-contract'
        root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=root)
        self.work = Path(self.temporary.name)
        self.input = self.work / 'SimTop.fir'
        self.input.write_bytes(b'formal-performance fixture\n')
        self.source_manifest = write_json(self.work / 'sources.json', {'fixture': True})
        self.identity = {'grh': {'package': 'package-hash'}, 'gsim': {'binary': 'binary-hash'}}
        self.configuration = {'cpu_affinity': [2, 3], 'threads': 1, 'build': 'Release'}
        self.manifest = {
            'schema': performance.GROUP_SCHEMA,
            'group_id': 'f33-fixture-group',
            'repeats_per_engine': 3,
            'schedule': ['grh', 'gsim', 'grh', 'gsim', 'grh', 'gsim'],
            'measurement': {'mode': 'no-trace', 'window_semantics': '2state',
                            'source': 'raw-firrtl', 'exports': False,
                            'verification': False, 'profile': False, 'build_type': 'Release'},
            'identity': self.identity,
            'configuration': self.configuration,
            'input': str(self.input),
            'input_sha256': digest(self.input),
            'source_manifest': str(self.source_manifest),
            'source_manifest_sha256': digest(self.source_manifest),
            'package_identity_sha256': 'a' * 64,
            'gsim_binary_sha256': 'b' * 64,
        }
        body = json.dumps(self.manifest, sort_keys=True, separators=(',', ':')).encode()
        self.manifest['manifest_sha256'] = hashlib.sha256(body).hexdigest()
        self.manifest_path = write_json(self.work / 'group.json', self.manifest)
        self.samples = []
        self.rows = []
        self.create_samples()
        self.results_path = write_json(self.work / 'results.json', {
            'schema': performance.RESULT_SCHEMA,
            'status': 'completed',
            'group_id': self.manifest['group_id'],
            'group_manifest': str(self.manifest_path),
            'group_manifest_sha256': digest(self.manifest_path),
            'started_at_ns': 100,
            'finished_at_ns': 200,
            'samples': self.rows,
        })

    def tearDown(self):
        self.temporary.cleanup()

    def create_samples(self):
        grh = {'constant-analysis#0': 10.2, 'dead-code-elim#2': 5.1, 'window': 16.0}
        gsim = {'constant-analysis#0': 10.0, 'dead-code-elim#2': 5.0, 'window': 15.7}
        previous_finish = 100
        for sequence, engine in enumerate(self.manifest['schedule'], 1):
            started = previous_finish + 1
            finished = started + 10
            previous_finish = finished
            run_id = 'run-' + str(sequence)
            sample_dir = self.work / ('sample-' + str(sequence))
            sample_dir.mkdir()
            metrics = dict(grh if engine == 'grh' else gsim)
            pass_times = {logical: metrics[logical] for logical in performance.PASSES}
            sample = {
                'schema': performance.SAMPLE_SCHEMA,
                'status': 'passed',
                'engine': engine,
                'group_id': self.manifest['group_id'],
                'run_id': run_id,
                'started_at_ns': started,
                'finished_at_ns': finished,
                'identity': self.identity,
                'configuration': self.configuration,
                'input_sha256': self.manifest['input_sha256'],
                'resource_interference': False,
                'pass_times_s': pass_times,
                'window_s': metrics['window'],
                'metrics': metrics,
            }
            guard_path = self.write_evidence(sample, sample_dir)
            sample_path = write_json(sample_dir / 'summary.json', sample)
            self.samples.append(sample)
            self.rows.append({'sequence': sequence, 'engine': engine, 'status': 'passed',
                              'run_id': run_id, 'started_at_ns': started, 'finished_at_ns': finished,
                              'summary_file': str(sample_path), 'summary_sha256': digest(sample_path),
                              'guard_file': str(guard_path), 'guard_sha256': digest(guard_path)})

    def write_evidence(self, sample, directory):
        engine = sample['engine']
        metrics = sample['metrics']
        timing_rows = [timer(engine, stage, instance, metrics[logical])
                       for logical, (stage, instance) in performance.EXPECTED[engine].items()]
        window_s = metrics['window']
        window = {'wall_s': window_s, 'clock': 'steady_clock'}
        guarded_times = {key: metrics[key] for key in performance.PASSES}
        if engine == 'gsim':
            window_timer = timer(engine, 'F33Window', 'F33Window#0', window_s, 'window')
            timing_rows.insert(0, timer(engine, 'RemoveDeadNodes1', 'RemoveDeadNodes1#0', 0, 'boundary'))
            timing_rows.append(window_timer)
            window.update(source='native', native_timer=window_timer)
        else:
            native_sum = sum(guarded_times.values())
            window.update(source='runner-monotonic', native_pass_sum_s=native_sum,
                          framework_overhead_s=window_s - native_sum)
            guarded_times = {key: value + 0.01 for key, value in guarded_times.items()}
            sample['guard_pass_times_s'] = guarded_times
        timing_path = write_jsonl(directory / 'timing.jsonl', timing_rows)
        sample['timing_files'] = [{'path': str(timing_path), 'sha256': digest(timing_path),
                                   'rows': timing_rows}]
        sample['window'] = window

        events = []
        for key, boundary, start in zip(performance.PASSES, ('Q0', 'Q1'),
                                        (100, 100 + window_s + 0.01 - guarded_times[performance.PASSES[1]])):
            common = {'engine': engine, 'run_id': sample['run_id'], 'batch_count': 1,
                      'input_boundary': boundary, 'logical_instance': key}
            events.append({**common, 'event': 'start', 'monotonic_s': start})
            events.append({**common, 'event': 'end', 'monotonic_s': start + guarded_times[key],
                           'wall_s': guarded_times[key]})
        event_path = write_jsonl(directory / 'stage-events.jsonl', events)
        sample.update(event_file=str(event_path), event_sha256=digest(event_path))
        return write_json(directory / 'guard.json', {
            'schema': 'wolvrix.f33.guard.v1', 'status': 'completed', 'returncode': 0,
            'resource_interference': False, 'run_id': sample['run_id'], 'engine': engine,
            'reference_identity': self.identity, 'pass_times_s': guarded_times,
            'events': events, 'event_errors': [],
        })

    def compare(self):
        return performance.compare(self.results_path)

    def reseal(self):
        body = dict(self.manifest)
        body.pop('manifest_sha256', None)
        self.manifest['manifest_sha256'] = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        write_json(self.manifest_path, self.manifest)
        self.results_path = write_json(self.work / 'results.json', {
            'schema': performance.RESULT_SCHEMA, 'status': 'completed',
            'group_id': self.manifest['group_id'], 'group_manifest': str(self.manifest_path),
            'group_manifest_sha256': digest(self.manifest_path), 'started_at_ns': 100,
            'finished_at_ns': 200, 'samples': self.rows,
        })

    def update_sample(self, sequence, updates):
        sample = self.samples[sequence - 1]
        sample.update(updates)
        row = self.rows[sequence - 1]
        path = Path(row['summary_file'])
        if 'metrics' in updates:
            row['guard_sha256'] = digest(self.write_evidence(sample, path.parent))
        write_json(path, sample)
        row['summary_sha256'] = digest(path)
        self.results_path = write_json(self.work / 'results.json', {
            'schema': performance.RESULT_SCHEMA, 'status': 'completed',
            'group_id': self.manifest['group_id'], 'group_manifest': str(self.manifest_path),
            'group_manifest_sha256': digest(self.manifest_path), 'started_at_ns': 100,
            'finished_at_ns': 200, 'samples': self.rows,
        })

    def test_interleaved_samples_pass_all_three_independent_median_gates(self):
        report = self.compare()
        self.assertTrue(report['complete'])
        self.assertTrue(report['passed'], report)
        self.assertEqual([row['metric'] for row in report['metrics']], list(performance.METRICS))
        self.assertTrue(all(row['stable'] for row in report['metrics']))

    def test_each_metric_has_an_independent_performance_gate(self):
        for row in self.rows:
            if row['engine'] == 'grh':
                sample = self.samples[row['sequence'] - 1]
                metrics = dict(sample['metrics'])
                metrics['window'] = 16.5
                self.update_sample(row['sequence'], {'window_s': 16.5, 'metrics': metrics})
        report = self.compare()
        self.assertFalse(report['passed'])
        window = next(row for row in report['metrics'] if row['metric'] == 'window')
        self.assertFalse(window['within_gate'])

    def test_unstable_samples_fail_even_if_the_median_is_within_gate(self):
        for row in self.rows:
            if row['engine'] == 'grh' and row['sequence'] == 1:
                sample = self.samples[row['sequence'] - 1]
                pass_times = dict(sample['pass_times_s'])
                pass_times[performance.PASSES[0]] = 10.6
                metrics = dict(sample['metrics'])
                metrics[performance.PASSES[0]] = 10.6
                self.update_sample(row['sequence'], {'pass_times_s': pass_times, 'metrics': metrics})
        report = self.compare()
        constant = next(row for row in report['metrics'] if row['metric'] == performance.PASSES[0])
        self.assertFalse(constant['stable'])
        self.assertFalse(constant['passed'])

    def test_noninterleaved_frozen_schedule_is_rejected(self):
        self.manifest['schedule'] = ['grh', 'grh', 'grh', 'gsim', 'gsim', 'gsim']
        self.reseal()
        with self.assertRaisesRegex(ValueError, 'interleave'):
            self.compare()

    def test_sample_package_identity_drift_is_rejected(self):
        self.update_sample(2, {'identity': {'grh': {'package': 'other'}, 'gsim': {'binary': 'binary-hash'}}})
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.compare()

    def test_summary_metrics_must_match_the_raw_timing_file(self):
        self.update_sample(1, {'window_s': 99.0})
        with self.assertRaisesRegex(ValueError, 'summary window time differs'):
            self.compare()

    def test_guard_interference_invalidates_a_sample(self):
        row = self.rows[0]
        guard_path = Path(row['guard_file'])
        guard = json.loads(guard_path.read_text())
        guard['resource_interference'] = True
        write_json(guard_path, guard)
        row['guard_sha256'] = digest(guard_path)
        self.results_path = write_json(self.work / 'results.json', {
            'schema': performance.RESULT_SCHEMA, 'status': 'completed',
            'group_id': self.manifest['group_id'], 'group_manifest': str(self.manifest_path),
            'group_manifest_sha256': digest(self.manifest_path), 'started_at_ns': 100,
            'finished_at_ns': 200, 'samples': self.rows,
        })
        with self.assertRaisesRegex(ValueError, 'guard did not complete cleanly'):
            self.compare()

    def test_manifest_and_sample_artifact_hashes_are_enforced(self):
        row = self.rows[0]
        row['summary_sha256'] = '0' * 64
        self.results_path = write_json(self.work / 'results.json', {
            'schema': performance.RESULT_SCHEMA, 'status': 'completed',
            'group_id': self.manifest['group_id'], 'group_manifest': str(self.manifest_path),
            'group_manifest_sha256': digest(self.manifest_path), 'started_at_ns': 100,
            'finished_at_ns': 200, 'samples': self.rows,
        })
        with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
            self.compare()


def write_jsonl(path, rows):
    Path(path).write_text(''.join(json.dumps(row, sort_keys=True) + '\n' for row in rows), encoding='utf-8')
    return Path(path)


def timer(engine, stage, instance, seconds, scope='pass'):
    return {'schema': engine + '-stage-timing.v1', 'stage': stage, 'pass_instance': instance,
            'scope': scope, 'clock': 'steady_clock', 'wall_s': seconds, 'complete': True}


if __name__ == '__main__':
    unittest.main()
