"""F33 boundary and unique third-DCE capture contracts without production graphs."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmark_f29_pass_trace import sha256
from capture_f33_pipeline import (GRH_STAGES, PASSES, grh_session, grh_sessions,
                                  gsim, gsim_command, release_files, release_snapshot_cache,
                                  validate_membership, verify_prepared)
from f33_guard import append_event


ROOT = Path(__file__).resolve().parents[1]


class InstalledApiMappingTests(unittest.TestCase):
    def test_actual_constant_analysis_mapping_accepts_top_and_semantics(self):
        # Import the actual installed Python API, so this catches missing named
        # mappings even when the injectable capture Session contracts pass.
        import wolvrix
        for mode in ('2state', '4state'):
            with self.subTest(semantics=mode):
                named = {'top': 'SimTop', 'semantics': mode}
                positional = ['-existing-option']
                self.assertEqual(wolvrix._compile_run_pass('constant-analysis', positional, named),
                                 ('constant-analysis', ['-existing-option', '-top=SimTop', '-semantics=' + mode]))
                self.assertEqual(named, {'top': 'SimTop', 'semantics': mode})
                self.assertEqual(positional, ['-existing-option'])
        self.assertEqual(wolvrix._compile_run_pass('constant_analysis', [], {}), ('constant-analysis', []))

    def test_actual_constant_analysis_mapping_rejects_unknown_parameters(self):
        import wolvrix
        with self.assertRaisesRegex(TypeError, 'unexpected named parameters.*extra_option'):
            wolvrix._compile_run_pass('constant-analysis', [],
                                     {'top': 'SimTop', 'semantics': '2state', 'extra_option': True})


class FakeSession:
    def __init__(self):
        self.calls = []
        self.snapshots = []

    def read_sources(self, **kwargs):
        self.calls.append(('ingest', kwargs))
        return {'success': True}

    def run_pass(self, name, **kwargs):
        self.calls.append((name, kwargs))
        Path(kwargs['timing_output']).write_text(json.dumps({
            'schema': 'grh-stage-timing.v1', 'scope': 'pass', 'clock': 'steady_clock',
            'stage': name, 'wall_s': 0.00000001, 'complete': True}) + '\n')
        return {'success': True}

    def semantic_validate(self, **kwargs):
        return {'valid': True}

    def semantic_snapshot(self, **kwargs):
        self.snapshots.append(kwargs)
        Path(kwargs['output']).mkdir()
        return {'success': True}


def fake_batch(sessions, name, **kwargs):
    """Inject the native aggregate protocol without Python per-graph timers."""
    events = kwargs.pop('stage_events')
    run_id = kwargs.pop('run_id')
    logical = kwargs.pop('logical_instance')
    timing = Path(kwargs.pop('timing_output'))
    for session in sessions:
        # Preserve observable call order without exercising per-member file I/O.
        session.calls.append((name, dict(kwargs)))
        if hasattr(session, 'trace'):
            session.trace.append((id(session), name))
    duration = 0.00000002 * len(sessions)
    append_event(events, run_id=run_id, engine='grh', logical_instance=logical,
                 event='start', batch_count=len(sessions))
    append_event(events, run_id=run_id, engine='grh', logical_instance=logical,
                 event='end', wall_s=duration, batch_count=len(sessions))
    timing.write_text(json.dumps({'schema': 'grh-stage-timing.v1', 'scope': 'pass',
                                 'clock': 'steady_clock', 'stage': name, 'pass_instance': name + '#0',
                                 'wall_s': duration, 'complete': True, 'batch_count': len(sessions),
                                 'native_member_times_s': [0.00000001] * len(sessions),
                                 'native_sum_s': 0.00000001 * len(sessions)}) + '\n')
    return [{'kind': 'info', 'message': 'native batch diagnostic'},
            {'action': 'run_pass_batch', 'success': True}]


class CaptureTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'ptmp').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='f33-capture-test-', dir=ROOT / 'ptmp')
        self.output = Path(self.temp.name)
        self.firrtl = self.output / 'test.fir'
        self.firrtl.write_text('test source')
        self.args = argparse.Namespace(output=self.output, top=None, dump_structure=False,
                                       serialization_id_map=False, run_id='fixture-run',
                                       firrtl=self.firrtl, release_snapshot_cache=False, batch_count=1)

    def tearDown(self):
        self.temp.cleanup()

    def test_native_sequence_stops_at_q2_and_preserves_second_dce_input(self):
        session = FakeSession()
        report = {'stages': []}
        with patch('capture_f33_pipeline.release_snapshot_cache'):
            grh_session(session, self.args, report, self.output / 'summary.json', {}, batch_runner=fake_batch)
        names = [name for name, _ in session.calls]
        self.assertEqual(names, ['ingest', 'xmr-resolve', 'hier-flatten', 'comb-loop-elim',
                                 'split-static-array', 'dead-code-elim', 'expr-opt', 'used-bits',
                                 'split-nodes', 'dead-code-elim', 'constant-analysis', 'dead-code-elim'])
        self.assertEqual([row['stage'] for row in session.snapshots], list(GRH_STAGES))
        self.assertEqual([Path(row['output']).name for row in session.snapshots], ['Q0', 'Q1', 'Q2'])
        self.assertEqual([row['logical_instance'] for row in report['pass_calls'] if not row['prefix']], list(PASSES))
        options = next(options for name, options in session.calls if name == 'constant-analysis')
        self.assertEqual(options['semantics'], '2state')
        dce_options = [options for name, options in session.calls if name == 'dead-code-elim']
        self.assertTrue(dce_options[-1]['drop_disabled_firrtl_assertions'])
        events = [json.loads(line) for line in (self.output / 'stage-events.jsonl').read_text().splitlines()]
        self.assertEqual([(row['logical_instance'], row['event']) for row in events],
                         [(PASSES[0], 'start'), (PASSES[0], 'end'), (PASSES[1], 'start'), (PASSES[1], 'end')])
        self.assertEqual(report['stop_boundary'], 'Q2')

    def test_gsim_unique_third_dce_stop_and_events(self):
        command = gsim_command(self.args, {'binary': '/frozen/gsim'}, self.output / 'timing.jsonl')
        self.assertIn('--stop-after-stage=RemoveDeadNodes2', command)
        self.assertIn('--semantic-node-exchange-stage=F33', command)
        self.assertIn('--stage-events=' + str(self.output / 'stage-events.jsonl'), command)
        self.assertIn('--run-id=fixture-run', command)
        self.assertNotIn('--stop-after-stage=RemoveDeadNodes', command)

    def test_fresh_batch_preloads_all_q0_before_either_window_pass(self):
        trace = []
        class TracedSession(FakeSession):
            def read_sources(self, **kwargs):
                trace.append((id(self), 'ingest'))
                return super().read_sources(**kwargs)

            def run_pass(self, name, **kwargs):
                trace.append((id(self), name))
                return super().run_pass(name, **kwargs)

        sessions = [TracedSession(), TracedSession(), TracedSession()]
        for session in sessions:
            session.trace = trace
        self.args.batch_count = 3
        report = {'stages': []}
        with patch('capture_f33_pipeline.release_snapshot_cache'):
            grh_sessions(sessions, self.args, report, self.output / 'summary.json', {}, batch_runner=fake_batch)
        first_constant = next(index for index, (_, name) in enumerate(trace) if name == 'constant-analysis')
        self.assertEqual(sum(name == 'ingest' for _, name in trace[:first_constant]), 3)
        self.assertEqual(sum(name == 'dead-code-elim' for _, name in trace[:first_constant]), 6)
        self.assertEqual([name for _, name in trace[first_constant:]], ['constant-analysis'] * 3 + ['dead-code-elim'] * 3)
        for session in sessions:
            self.assertEqual(sum(name == 'constant-analysis' for name, _ in session.calls), 1)
            self.assertEqual(sum(name == 'dead-code-elim' for name, _ in session.calls), 3)
        self.assertEqual([len(session.snapshots) for session in sessions], [3, 0, 0])
        events = [json.loads(line) for line in (self.output / 'stage-events.jsonl').read_text().splitlines()]
        self.assertEqual([row['batch_count'] for row in events], [3] * 4)
        for row in report['pass_calls']:
            if not row['prefix']:
                self.assertEqual(len(row['timing_files']), 1)
                self.assertGreaterEqual(row['python_call_wall_s'], row['native_pass_sum_s'])
                self.assertEqual(row['native_timers'][0]['batch_count'], 3)
                self.assertAlmostEqual(report['pass_times_s'][row['logical_instance']], 0.00000006)
        self.assertTrue(report['snapshots']['Q2']['calibration_representative'])
        command = gsim_command(self.args, {'binary': '/frozen/gsim'}, self.output / 'timing.jsonl')
        self.assertIn('--f33-batch=3', command)

    def test_batch_cannot_reuse_one_session(self):
        self.args.batch_count = 2
        session = FakeSession()
        with self.assertRaises(ValueError):
            grh_sessions([session, session], self.args, {'stages': []}, self.output / 'summary.json', {},
                         batch_runner=fake_batch)

    def test_preflight_error_does_not_start_native_performance_timer(self):
        def invalid_batch(*args, **kwargs):
            raise TypeError('invalid native dispatch')
        with self.assertRaisesRegex(TypeError, 'invalid native dispatch'):
            grh_session(FakeSession(), self.args, {'stages': []}, self.output / 'summary.json', {},
                        batch_runner=invalid_batch)
        self.assertFalse((self.output / 'stage-events.jsonl').exists())

    def test_malformed_aggregate_constituents_reject_checkpoint(self):
        def corrupt_batch(*args, **kwargs):
            result = fake_batch(*args, **kwargs)
            path = Path(kwargs['timing_output'])
            row = json.loads(path.read_text())
            row['native_member_times_s'] = []
            path.write_text(json.dumps(row) + '\n')
            return result
        with self.assertRaisesRegex(ValueError, 'invalid aggregate GRH'):
            grh_session(FakeSession(), self.args, {'stages': []}, self.output / 'summary.json', {},
                        batch_runner=corrupt_batch)

    def test_gsim_batch_accepts_only_real_aggregate_timer_layout(self):
        self.args.batch_count = 4
        self.args.source_root = ROOT / 'reference/gsim'
        rows = [{'stage': 'F33BatchPrefix', 'scope': 'prefix', 'wall_s': 0.5, 'batch_count': 4},
                {'stage': 'ConstantAnalysis', 'scope': 'pass', 'pass_instance': 'ConstantAnalysis#0',
                 'wall_s': 0.02, 'batch_count': 4},
                {'stage': 'RemoveDeadNodes2', 'scope': 'pass', 'pass_instance': 'RemoveDeadNodes#1',
                 'wall_s': 0.01, 'batch_count': 4}]
        report = {}
        with patch('capture_f33_pipeline.subprocess.run', return_value=argparse.Namespace(returncode=0)), \
                patch('capture_f33_pipeline.native_rows', return_value=rows):
            gsim(self.args, {'native': {'binary': '/frozen/gsim'}}, report, self.output / 'summary.json')
        self.assertEqual(report['pass_times_s'], dict(zip(PASSES, (0.02, 0.01))))
        self.assertTrue(all(row['calibration_representative'] for row in report['snapshots'].values()))
        self.assertEqual(report['stop_boundary'], 'Q2')

    def test_prepared_rejects_actual_cli_option_mismatch(self):
        self.args.manifest = self.output / 'manifest.json'
        self.args.manifest.write_text('{}')
        self.args.package = self.output / 'package'
        self.args.package.mkdir()
        (self.args.package / 'identity.json').write_text('{}')
        binary, native_identity = self.output / 'native', self.output / 'native-identity.json'
        binary.write_text('binary')
        native_identity.write_text('{}')
        native = {'source_sha256': 'a' * 64, 'binary_sha256': 'b' * 64, 'build': {'type': 'test'}}
        identity = {'input': {'sha256': sha256(self.firrtl), 'manifest_sha256': sha256(self.args.manifest), 'sources': []},
                    'configuration': {'top': None, 'capture_structure': False, 'serialization_id_map': False,
                                      'release_snapshot_cache': False, 'fresh_graph_batch': 1},
                    'semantics': '2state', 'batch_count': 1, 'grh': native,
                    'gsim': {**native, 'binary_sha256': sha256(binary)}}
        prepared = {'schema': 'wolvrix.f33.prepared.v1', 'identity': identity,
                    'package_identity_sha256': sha256(self.args.package / 'identity.json'),
                    'native_identity_sha256': sha256(native_identity), 'native_identity': str(native_identity),
                    'native': {'binary': str(binary)}}
        self.args.prepared = self.output / 'prepared.json'
        self.args.prepared.write_text(json.dumps(prepared))
        with patch('capture_f33_pipeline.environment', return_value={}):
            self.assertEqual(verify_prepared(self.args), prepared)
            for field, changed in (('top', 'OtherTop'), ('dump_structure', True), ('serialization_id_map', True),
                                   ('release_snapshot_cache', True), ('batch_count', 2)):
                args = copy.copy(self.args)
                setattr(args, field, changed)
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'CLI'):
                    verify_prepared(args)

    def test_execution_membership_matches_ids_flags_and_footer(self):
        meta = {'run_id': 'run', 'snapshot_id': 'snap', 'stage': 'ConstantAnalysis', 'engine': 'gsim'}
        artifacts = {'nodes.tsv': {'metadata': meta, 'footer': {'rowCount': 2}},
                     'execution-membership.tsv': {'metadata': {**meta, 'table': 'execution-membership',
                                                               'detail_schema': 'gsim.f33.membership.v1'},
                                                  'footer': {'rowCount': 2, 'activeComputation': 1,
                                                             'inlineConstantSource': 1, 'sourceCatalog': 0}}}
        (self.output / 'nodes.tsv').write_text('node_id\tname_path_json\tnative_name\n1\t[]\ta\n3\t[]\tb\n')
        valid = ('node_id\tclassification\tnative_status\texecution_member\tstorage\texternal\tinput\toutput\n'
                 '1\tactive_computation\t0\t1\t0\t0\t0\t0\n'
                 '3\tinline_constant_source\t1\t0\t0\t0\t0\t0\n')
        path = self.output / 'execution-membership.tsv'
        path.write_text(valid)
        self.assertEqual(validate_membership(self.output, artifacts)['inlineConstantSource'], 1)
        for corrupt in (valid.replace('3\tinline', '4\tinline'),
                        valid.replace('active_computation', 'source_catalog'),
                        valid.replace('3\tinline_constant_source\t1\t0', '3\tinline_constant_source\t1\t2')):
            path.write_text(corrupt)
            with self.assertRaises(ValueError):
                validate_membership(self.output, artifacts)

    def test_cache_advice_uses_actual_f33_root_and_rejects_symlinks(self):
        work = ROOT / 'ptmp/firrtl-ingest/F33'
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='cache-regression-', dir=work) as name:
            directory = Path(name)
            path = directory / 'nodes.tsv'
            path.write_text('closed F33 artifact')
            with patch('capture_f33_pipeline.os.posix_fadvise') as advise, \
                    patch('capture_f33_pipeline.os.fdatasync') as sync:
                result = release_files([path], sync=True, minimum_bytes=1)
                self.assertEqual(result['bytes'], path.stat().st_size)
                advise.assert_called_once()
                sync.assert_called_once()
                report = {}
                args = argparse.Namespace(release_snapshot_cache=True)
                release_snapshot_cache(args, report, [path], 'Q0-verified', sync=False)
                self.assertEqual(len(report['snapshot_cache_release']), 1)
            link = directory / 'linked.tsv'
            link.symlink_to(path)
            with self.assertRaisesRegex(ValueError, 'nonsymlink F33'):
                release_files([link], minimum_bytes=1)
            with self.assertRaisesRegex(ValueError, 'nonsymlink F33'):
                release_files([self.firrtl], minimum_bytes=1)


if __name__ == '__main__':
    unittest.main()
