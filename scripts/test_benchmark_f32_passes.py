"""Focused contracts for the F32 raw-input benchmark runner."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from benchmark_f32_passes import (GROUP_SCHEMA, gsim_active_stage, normalized_environment,
                                  schedule, timers, verify_child_environment, verify_tool_sources)
from f30_resource_guard import PhaseDeadline

ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = Path(os.environ.get('F32_BENCHMARK_TEST_ROOT', ROOT / 'ptmp/firrtl-ingest/F32/benchmark-contract-tests')).resolve()


class BenchmarkContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if TEST_ROOT.exists():
            shutil.rmtree(TEST_ROOT)
        TEST_ROOT.mkdir(parents=True)

    def test_schedule_interleaves_and_preserves_sample_count(self):
        for count in range(3, 8):
            result = schedule(count)
            self.assertEqual(len(result), count * 2)
            self.assertEqual(result.count('grh'), count)
            self.assertEqual(result.count('gsim'), count)
            self.assertTrue(all(left != right for left, right in zip(result, result[1:])))

    def test_native_timer_requires_complete_exact_schema(self):
        path = TEST_ROOT / 'timers.jsonl'
        path.write_text(json.dumps({'schema': 'grh-stage-timing.v1', 'stage': 'used-bits',
                                    'pass_instance': 'used-bits#0', 'scope': 'pass',
                                    'clock': 'steady_clock', 'wall_s': 1.25,
                                    'complete': True}) + '\n')
        rows, indexed = timers(path, 'grh')
        self.assertEqual(len(rows), 1)
        self.assertEqual(indexed['pass']['used-bits#0']['wall_s'], 1.25)
        path.write_text(json.dumps({'schema': 'grh-stage-timing.v1', 'stage': 'used-bits',
                                    'pass_instance': 'used-bits#0', 'scope': 'pass',
                                    'clock': 'steady_clock', 'wall_s': 1.25,
                                    'complete': False}) + '\n')
        with self.assertRaises(ValueError):
            timers(path, 'grh')

    def test_manifest_hash_excludes_only_its_own_hash_field(self):
        value = {'schema': GROUP_SCHEMA, 'group_id': 'test', 'cpus': [2, 3]}
        digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        path = TEST_ROOT / 'hash.json'
        value['manifest_sha256'] = digest
        path.write_text(json.dumps(value))
        without_hash = {key: item for key, item in value.items() if key != 'manifest_sha256'}
        actual = hashlib.sha256(json.dumps(without_hash, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(actual, digest)
        value['cpus'].append(4)
        path.write_text(json.dumps(value))
        tampered = {key: item for key, item in value.items() if key != 'manifest_sha256'}
        self.assertNotEqual(hashlib.sha256(json.dumps(tampered, sort_keys=True, separators=(',', ':')).encode()).hexdigest(), digest)

    def test_formal_environment_disables_instrumentation(self):
        os.environ['WOLVRIX_SPLIT_NODES_PROFILE'] = '1'
        normalized_environment()
        self.assertNotIn('WOLVRIX_SPLIT_NODES_PROFILE', os.environ)
        self.assertEqual(os.environ['OMP_NUM_THREADS'], '1')
        self.assertEqual(os.environ['TBB_NUM_THREADS'], '1')

    def test_gsim_progress_tracks_native_order_and_stable_split_start(self):
        phase = {'name': 'gsim-raw-firrtl-prefix', 'finished': False}
        completed = set()
        self.assertEqual(gsim_active_stage(completed, phase, 10), phase)
        for key, name in (('RemoveDeadNodes#0', 'expr-opt#0'),
                          ('ExprOpt#0', 'used-bits#0'),
                          ('{g->usedBits()}#0', 'split-nodes#0')):
            completed.add(key)
            phase = gsim_active_stage(completed, phase, 20)
            self.assertEqual(phase['name'], name)
        self.assertEqual(phase['started_monotonic_s'], 20)
        self.assertEqual(gsim_active_stage(completed, phase, 60), phase)
        # A partial timer-file read cannot restart the active watchdog either.
        self.assertEqual(gsim_active_stage(set(), phase, 90), phase)
        completed.add('{g->splitNodes()}#0')
        phase = gsim_active_stage(completed, phase, 100)
        self.assertEqual(phase, {'name': 'dead-code-elim#1', 'finished': False})
        completed.add('RemoveDeadNodes1#0')
        self.assertEqual(gsim_active_stage(completed, phase, 120),
                         {'name': 'window-complete', 'finished': True})

    def test_gsim_second_dce_time_cannot_trigger_split_watchdog(self):
        guard = PhaseDeadline({'split-nodes#0': 180})
        completed = {'RemoveDeadNodes#0', 'ExprOpt#0', '{g->usedBits()}#0'}
        phase = gsim_active_stage(completed, {}, 10)
        self.assertFalse(guard.observe(phase, 10))
        self.assertFalse(guard.observe(phase, 150))
        completed.add('{g->splitNodes()}#0')
        phase = gsim_active_stage(completed, phase, 160)
        self.assertFalse(guard.observe(phase, 160))
        self.assertFalse(guard.observe(phase, 500))
        self.assertIsNone(guard.started)
        self.assertIsNone(guard.trigger)
        # A still-incomplete real split retains its original start and times out.
        phase = gsim_active_stage({'{g->usedBits()}#0'}, {}, 10)
        self.assertFalse(guard.observe(phase, 10))
        phase = gsim_active_stage({'{g->usedBits()}#0'}, phase, 189)
        self.assertTrue(guard.observe(phase, 190))
        self.assertEqual(guard.trigger['started_monotonic_s'], 10)

    def test_actual_child_configuration_rejects_affinity_thread_and_loader_drift(self):
        actual = {'machine': ['fixture'], 'cpu_model': 'fixture', 'cpu_affinity': [2],
                  'thread_environment': {'OMP_NUM_THREADS': '1'},
                  'loader_environment': {'LD_PRELOAD': None},
                  'profiling_environment': {'PROFILE': None}}
        frozen = {**deepcopy(actual), 'instrumentation': {'profile': False}}
        with patch('benchmark_f32_passes.environment', return_value=actual):
            self.assertEqual(verify_child_environment(frozen), actual)
            for field, value in (('cpu_affinity', [3]),
                                 ('thread_environment', {'OMP_NUM_THREADS': '8'}),
                                 ('loader_environment', {'LD_PRELOAD': 'other.so'})):
                changed = deepcopy(frozen)
                changed[field] = value
                with self.assertRaisesRegex(ValueError, field):
                    verify_child_environment(changed)

    def test_runner_and_guard_sources_must_match_group_identity(self):
        actual = {'schema': 'wolvrix.f32.benchmark-tools.v1', 'files': [
            {'path': '/fixture/benchmark_f32_passes.py', 'sha256': 'a' * 64},
            {'path': '/fixture/f30_resource_guard.py', 'sha256': 'b' * 64}]}
        with patch('benchmark_f32_passes.tool_source_identity', return_value=actual):
            self.assertEqual(verify_tool_sources(deepcopy(actual)), actual)
            for index in range(2):
                changed = deepcopy(actual)
                changed['files'][index]['sha256'] = 'c' * 64
                with self.assertRaisesRegex(ValueError, 'changed after group freeze'):
                    verify_tool_sources(changed)
            with self.assertRaises(ValueError):
                verify_tool_sources(None)


if __name__ == '__main__':
    unittest.main()
