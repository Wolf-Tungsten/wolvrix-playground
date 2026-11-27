"""F32 raw-prefix, exact window, artifact and resource-guard contracts."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import capture_f32_pipeline as capture
from f30_resource_guard import GuardLimits


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'ptmp/firrtl-ingest/F32/capture-contract-tests'


class FakeSession:
    def __init__(self, fail=None, pass_exception=None, failed_store=None):
        self.calls = []
        self.fail = fail
        self.pass_exception = pass_exception
        self.failed_store = failed_store
        self.mutated_failed_state = False

    def read_sources(self, **kwargs):
        self.calls.append(('ingest', kwargs))
        return []

    def run_pass(self, name, **kwargs):
        self.calls.append((name, kwargs))
        if name == self.fail:
            self.mutated_failed_state = True
            if self.pass_exception is not None:
                raise self.pass_exception
            return [{'kind': 'error', 'message': 'deliberate pass failure'}]
        Path(kwargs['timing_output']).write_text(json.dumps({
            'schema': 'grh-stage-timing.v1', 'stage': name, 'pass_instance': name + '#0',
            'scope': 'pass', 'clock': 'steady_clock', 'wall_s': 0.01, 'complete': True}) + '\n')
        return []

    def semantic_validate(self, **kwargs):
        self.calls.append(('validate', kwargs))
        return {'valid': True, 'error_count': 0}

    def semantic_snapshot(self, **kwargs):
        self.calls.append(('snapshot', kwargs))
        Path(kwargs['output']).mkdir()
        return {'success': True}

    def store_json(self, **kwargs):
        self.calls.append(('store', kwargs))
        if self.mutated_failed_state:
            if self.failed_store == 'raise':
                Path(kwargs['output']).write_text('{"partiallyWritten":')
                raise OSError('deliberate diagnostic write failure')
            if self.failed_store == 'diagnostics':
                return [{'kind': 'error', 'message': 'deliberate diagnostic store failure'}]
            Path(kwargs['output']).write_text('{"physicalGraph":"mutated failed state"}\n')
            return []
        Path(kwargs['output']).write_text('{"graphs":[]}\n')
        return []


class CaptureContractTests(unittest.TestCase):
    def setUp(self):
        WORK.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=WORK)
        self.work = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def args(self, **kwargs):
        value = dict(output=self.work, top='Top', dump_structure=True, engine='grh', release_snapshot_cache=False)
        value.update(kwargs)
        return argparse.Namespace(**value)

    def report(self):
        return {'stages': [], 'snapshots': {}}

    def test_raw_prefix_five_snapshots_and_exact_four_pass_window(self):
        session, report = FakeSession(), self.report()
        with contextlib.redirect_stdout(io.StringIO()):
            capture.grh_session(session, self.args(), report, self.work / 'summary.json', {'sources': []})
        transformations = [name for name, _ in session.calls if name not in ('validate', 'snapshot', 'store')]
        self.assertEqual(transformations, ['ingest', *capture.PREFIX, *capture.WINDOW])
        snapshots = [kwargs for name, kwargs in session.calls if name == 'snapshot']
        self.assertEqual([Path(row['output']).name for row in snapshots], ['P0', 'P1', 'P2', 'P3', 'P4'])
        self.assertEqual([row['stage'] for row in snapshots], list(capture.GRH_STAGES))
        self.assertEqual(len([name for name, _ in session.calls if name == 'validate']), 5)
        self.assertEqual(len([name for name, _ in session.calls if name == 'store']), 5)
        self.assertNotIn('failure_diagnostics', report)
        dce = [row for row in report['pass_calls'] if row['pass'] == 'dead-code-elim']
        self.assertEqual([row['logical_instance'] for row in dce], ['dead-code-elim#0', 'dead-code-elim#1'])
        self.assertNotEqual(dce[0]['timing_file'], dce[1]['timing_file'])
        self.assertEqual([row['native_timers'][0]['pass_instance'] for row in dce], ['dead-code-elim#0'] * 2)
        for name, kwargs in session.calls:
            if name in capture.WINDOW[:3]:
                self.assertEqual(kwargs['semantics'], '2state')
            if name in (*capture.WINDOW, 'split-static-array'):
                self.assertFalse(kwargs['keep_declared_symbols'])
            if name == 'store':
                self.assertEqual(kwargs['mode'], 'pretty-compact')
                self.assertFalse(kwargs['emit_def_users'])
        for row in report['pass_calls']:
            if row['pass'] in capture.WINDOW[:3]:
                self.assertEqual(row['parameters']['semantics'], '2state')

    def test_explicit_four_state_is_not_mislabeled_as_two_state(self):
        session, report = FakeSession(), self.report()
        with contextlib.redirect_stdout(io.StringIO()):
            capture.grh_session(session, self.args(semantics='4state'), report,
                                self.work / 'summary.json', {'sources': []})
        for row in report['pass_calls']:
            if row['pass'] in capture.WINDOW[:3]:
                self.assertEqual(row['parameters']['semantics'], '4state')

    def test_split_profile_setup_and_finish_are_outside_native_stage_and_finish_on_failure(self):
        for fail in (False, True):
            output = self.work / str(fail)
            output.mkdir()
            report = self.report()
            summary = output / 'summary.json'
            session = FakeSession(fail='split-nodes' if fail else None)
            native_pass = session.run_pass

            def checked_pass(name, **kwargs):
                active = json.loads(summary.read_text())['active_stage']
                if name == 'split-nodes':
                    self.assertEqual(active['name'], 'split-nodes#0')
                    self.assertEqual(report['split_nodes_profile']['status'], 'sampling')
                    self.assertEqual(profile.finish.call_count, 0)
                return native_pass(name, **kwargs)

            session.run_pass = checked_pass
            with patch.object(capture, 'SplitProfile') as factory, contextlib.redirect_stdout(io.StringIO()):
                profile = factory.return_value
                profile.symbols = {'identity': 'fixture'}
                profile.process.pid = 1234

                def setup(directory):
                    self.assertEqual(directory, output / 'split-nodes-profile')
                    self.assertEqual(json.loads(summary.read_text())['active_stage']['name'],
                                     'split-nodes#0-profile-setup')
                    self.assertNotIn('split-nodes', [name for name, _ in session.calls])
                    return profile

                def finish():
                    self.assertEqual(json.loads(summary.read_text())['active_stage']['name'],
                                     'split-nodes#0-profile-finish')
                    self.assertIn('split-nodes', [name for name, _ in session.calls])

                factory.side_effect = setup
                profile.finish.side_effect = finish
                if fail:
                    with self.assertRaisesRegex(RuntimeError, 'split-nodes'):
                        capture.grh_session(session, self.args(output=output, profile_split_nodes=True),
                                            report, summary, {'sources': []})
                else:
                    capture.grh_session(session, self.args(output=output, profile_split_nodes=True),
                                        report, summary, {'sources': []})
                factory.assert_called_once()
                profile.finish.assert_called_once()
            self.assertEqual(report['split_nodes_profile']['status'], 'completed')
            self.assertEqual(report['split_nodes_profile']['pid'], 1234)
            self.assertEqual([row['stage'] for row in report['stages'] if '-profile-' in row['stage']],
                             ['split-nodes#0-profile-setup', 'split-nodes#0-profile-finish'])

    def test_serialization_identity_map_is_an_explicit_snapshot_export(self):
        session, report = FakeSession(), self.report()
        with contextlib.redirect_stdout(io.StringIO()):
            capture.grh_session(session, self.args(serialization_id_map=True), report,
                                self.work / 'summary.json', {'sources': []})
        snapshots = [kwargs for name, kwargs in session.calls if name == 'snapshot']
        self.assertEqual(len(snapshots), 5)
        self.assertTrue(all(row['emit_serialization_id_map'] is True for row in snapshots))
        transformations = [name for name, _ in session.calls if name not in ('validate', 'snapshot', 'store')]
        self.assertEqual(transformations, ['ingest', *capture.PREFIX, *capture.WINDOW])

    def test_serialization_map_artifact_is_frozen_and_cross_session_is_rejected(self):
        report = {'input_sha256': 'a' * 64, 'snapshots': {}}
        for index, stage in enumerate(capture.GRH_STAGES):
            directory = self.work / f'P{index}'
            directory.mkdir()
            meta = {'schema': 'semantic-node-exchange.v1', 'engine': 'grh', 'stage': stage,
                    'run_id': 'run', 'snapshot_id': f'snapshot-{index}', 'graph_id': '1',
                    'exchange_session_id': f'session-{index}'}
            for name in ('nodes.tsv', 'connections.tsv', 'bit-slices.tsv', 'node-endpoints.tsv'):
                (directory / name).write_text('#meta\t' + json.dumps(meta) + '\nnode_id\n1\n' +
                    '#footer\t' + json.dumps({'complete': True, 'rowCount': 1}) + '\n')
            mapping_meta = {**meta, 'schema': 'grh.native-serialization-map.v1',
                'session_id': meta['exchange_session_id'], 'graph_symbol': 'top', 'graph_index': 1, 'graph_generation': 0}
            (directory / 'serialization-id-map.tsv').write_text('#meta\t' + json.dumps(mapping_meta) + '\n' +
                'kind\tserialized_id\tnative_index\tnative_generation\nvalue\t1\t100\t7\n' +
                '#footer\t' + json.dumps({'complete': True, 'rowCount': 1}) + '\n')
            structure = directory / 'design.json'
            structure.write_text('{"graphs":[]}\n')
            report['snapshots'][f'P{index}'] = {'directory': str(directory), 'stage': stage, 'structure': str(structure)}
        args = self.args(engine='grh', serialization_id_map=True)
        capture.finalize_snapshots(args, report)
        for record in report['snapshots'].values():
            self.assertIn('serialization-id-map.tsv', record['artifacts'])
            mapping = record['artifacts']['serialization-id-map.tsv']
            self.assertEqual(mapping['sha256'], capture.sha256(Path(mapping['path'])))
        path = self.work / 'P2/serialization-id-map.tsv'
        path.write_text(path.read_text().replace('"session_id": "session-2"', '"session_id": "other-session"'))
        with self.assertRaisesRegex(ValueError, 'mixed native graph/session identity'):
            capture.finalize_snapshots(args, report)
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            capture.finalize_snapshots(args, report)

    def test_serialization_map_cli_requires_grh_full_structure(self):
        for engine, flags in (('gsim', ['--binary', 'gsim', '--dump-structure']),
                              ('grh', ['--package', 'package', '--manifest', 'manifest'])):
            argv = ['capture_f32_pipeline.py', '--engine', engine, '--firrtl', 'input.fir',
                    '--output', str(self.work / engine), '--serialization-id-map', *flags]
            with patch.object(sys, 'argv', argv), patch.object(capture, 'run_guarded') as guarded:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    capture.main()
                guarded.assert_not_called()

    def test_failed_pass_stops_before_snapshot_and_successors(self):
        session, report = FakeSession(fail='used-bits'), self.report()
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, 'used-bits'):
            capture.grh_session(session, self.args(dump_structure=False), report,
                                self.work / 'summary.json', {'sources': []})
        self.assertEqual([Path(kwargs['output']).name for name, kwargs in session.calls if name == 'snapshot'], ['P0', 'P1'])
        self.assertEqual(session.calls[-1][0], 'used-bits')
        self.assertNotIn('failure_diagnostics', report)
        self.assertFalse((self.work / 'failed-diagnostics').exists())

    def test_failed_pass_exports_only_separate_mutated_physical_diagnostics(self):
        session, report = FakeSession(fail='split-nodes'), self.report()
        released = []

        def release(paths, **kwargs):
            self.assertEqual(session.calls[-1][0], 'store')
            self.assertTrue(all(path.is_file() for path in paths))
            released.append((list(paths), kwargs))
            return {'files': [], 'bytes': 0, 'errors': []}

        summary = self.work / 'summary.json'
        with contextlib.redirect_stdout(io.StringIO()), patch('release_f32_cache.release_files', side_effect=release):
            with self.assertRaisesRegex(RuntimeError, 'split-nodes.*deliberate pass failure') as failure:
                capture.grh_session(session, self.args(release_snapshot_cache=True), report, summary, {'sources': []})
        diagnostic = self.work / 'failed-diagnostics/split-nodes-0/design.json'
        self.assertEqual(json.loads(diagnostic.read_text()), {'physicalGraph': 'mutated failed state'})
        self.assertEqual(set(report['snapshots']), {'P0', 'P1', 'P2'})
        self.assertFalse((self.work / 'P3').exists())
        self.assertFalse((self.work / 'P4').exists())
        self.assertEqual(session.calls[-2][0], 'split-nodes')
        self.assertEqual(session.calls[-1][0], 'store')
        self.assertEqual(len([name for name, _ in session.calls if name == 'validate']), 3)
        self.assertEqual(len(report['failure_diagnostics']), 1)
        row = report['failure_diagnostics'][0]
        self.assertEqual((row['pass'], row['logical_instance'], row['status']),
                         ('split-nodes', 'split-nodes#0', 'saved'))
        self.assertTrue(row['non_authoritative'])
        self.assertTrue(row['mutated_failed_state'])
        self.assertEqual(row['structure'], str(diagnostic))
        self.assertEqual(row['pass_error'], repr(failure.exception))
        self.assertNotIn('complete', row)
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['error'], repr(failure.exception))
        self.assertEqual(json.loads(summary.read_text())['failure_diagnostics'], report['failure_diagnostics'])
        self.assertEqual(released[-1], ([diagnostic], {'sync': True, 'minimum_bytes': 8 * 1024**2}))
        self.assertEqual(report['snapshot_cache_release'][-1]['point'], 'split-nodes#0-closed-failed-diagnostics')
        self.assertFalse(any(row['pass'] == 'split-nodes' for row in report['pass_calls']))

    def test_diagnostic_store_failures_preserve_the_original_pass_exception(self):
        for failure_mode in ('raise', 'diagnostics'):
            with self.subTest(store_failure=failure_mode):
                output = self.work / failure_mode
                output.mkdir()
                original = ValueError('deliberate native pass exception')
                session = FakeSession(fail='split-nodes', pass_exception=original, failed_store=failure_mode)
                report, summary = self.report(), output / 'summary.json'
                with contextlib.redirect_stdout(io.StringIO()), patch('release_f32_cache.release_files') as release:
                    release.return_value = {'files': [], 'bytes': 0, 'errors': []}
                    with self.assertRaises(ValueError) as failure:
                        capture.grh_session(session, self.args(output=output, release_snapshot_cache=True),
                                            report, summary, {'sources': []})
                self.assertIs(failure.exception, original)
                row = report['failure_diagnostics'][0]
                self.assertEqual(row['status'], 'save_failed')
                self.assertEqual(row['pass_error'], repr(original))
                self.assertIn('deliberate diagnostic', row['error'])
                self.assertTrue(row['non_authoritative'])
                self.assertTrue(row['mutated_failed_state'])
                self.assertEqual(report['error'], repr(original))
                self.assertEqual(set(report['snapshots']), {'P0', 'P1', 'P2'})
                self.assertFalse((output / 'P3').exists())
                self.assertFalse((output / 'P4').exists())
                self.assertEqual(json.loads(summary.read_text())['error'], repr(original))
                if failure_mode == 'raise':
                    partial = output / 'failed-diagnostics/split-nodes-0/design.json'
                    self.assertEqual(partial.read_text(), '{"partiallyWritten":')
                    self.assertEqual(release.call_args.args, ([partial],))
                    self.assertEqual(release.call_args.kwargs, {'sync': True, 'minimum_bytes': 8 * 1024**2})

    def test_diagnostic_cache_advice_failure_cannot_replace_pass_failure(self):
        original = ValueError('original native failure')
        session = FakeSession(fail='used-bits', pass_exception=original)
        report = self.report()
        with contextlib.redirect_stdout(io.StringIO()), patch('release_f32_cache.release_files') as release:
            release.side_effect = [
                {'files': [], 'bytes': 0, 'errors': []},
                {'files': [], 'bytes': 0, 'errors': []},
                OSError('diagnostic cache advice failed'),
            ]
            with self.assertRaises(ValueError) as failure:
                capture.grh_session(session, self.args(release_snapshot_cache=True), report,
                                    self.work / 'summary.json', {'sources': []})
        self.assertIs(failure.exception, original)
        row = report['failure_diagnostics'][0]
        self.assertEqual(row['status'], 'saved')
        self.assertIn('diagnostic cache advice failed', row['cache_release_error'])
        self.assertEqual(report['error'], repr(original))

    def test_closed_grh_snapshot_cache_release_occurs_before_next_pass(self):
        session, report = FakeSession(), self.report()
        observed = []
        def release(paths, **kwargs):
            observed.append(([name for name, _ in session.calls], list(paths), kwargs))
            return {'files': [{'path': str(paths[0]), 'bytes': 9 * 1024**2}],
                    'bytes': 9 * 1024**2, 'errors': []}
        with contextlib.redirect_stdout(io.StringIO()), patch('release_f32_cache.release_files', side_effect=release):
            capture.grh_session(session, self.args(release_snapshot_cache=True), report,
                                self.work / 'summary.json', {'sources': []})
        self.assertEqual(len(observed), 5)
        for index, (calls, paths, kwargs) in enumerate(observed):
            self.assertEqual(calls[-1], 'store')
            self.assertEqual(paths, [self.work / f'P{index}/design.json'])
            self.assertEqual(kwargs, {'sync': True, 'minimum_bytes': 8 * 1024**2})
            self.assertEqual(len([name for name in calls if name == 'snapshot']), index + 1)
        self.assertEqual([row['point'] for row in report['snapshot_cache_release']],
                         [f'P{index}-closed-snapshot' for index in range(5)])
        self.assertTrue(all(row['bytes'] == 9 * 1024**2 and row['errors'] == []
                            for row in report['snapshot_cache_release']))

    def test_cache_release_can_be_disabled_and_errors_remain_explicit(self):
        report = self.report()
        with patch('release_f32_cache.release_files') as release:
            capture.release_snapshot_cache(self.args(), report, [], 'disabled', sync=True)
        release.assert_not_called()
        self.assertNotIn('snapshot_cache_release', report)
        failure = {'files': [], 'bytes': 0, 'errors': [{'path': 'artifact', 'error': 'advice failed'}]}
        with contextlib.redirect_stdout(io.StringIO()), patch('release_f32_cache.release_files', return_value=failure):
            capture.release_snapshot_cache(self.args(release_snapshot_cache=True), report, [], 'after-hash', sync=False)
        self.assertEqual(report['snapshot_cache_release'][0]['errors'], failure['errors'])
        self.assertFalse(report['snapshot_cache_release'][0]['sync'])

    def test_cache_helper_preserves_contents_and_ignores_small_files_and_directories(self):
        from release_f32_cache import release_files
        large, small = self.work / 'closed.tsv', self.work / 'small.tsv'
        large.write_bytes(b'complete native artifact\n')
        small.write_bytes(b'x')
        original = large.read_bytes()
        result = release_files([large, small, self.work], sync=True, minimum_bytes=8)
        self.assertEqual(result['files'], [{'path': str(large), 'bytes': len(original)}])
        self.assertEqual(result['bytes'], len(original))
        self.assertEqual(result['errors'], [])
        self.assertEqual(large.read_bytes(), original)
        self.assertEqual(small.read_bytes(), b'x')

    def test_cache_helper_rejects_symlink_and_reports_advice_errors(self):
        from release_f32_cache import release_files
        path, link = self.work / 'closed.tsv', self.work / 'link.tsv'
        path.write_bytes(b'complete native artifact\n')
        original = path.read_bytes()
        link.symlink_to(path)
        with self.assertRaisesRegex(ValueError, 'nonsymlink'):
            release_files([link], minimum_bytes=8)
        with patch('release_f32_cache.os.posix_fadvise', side_effect=OSError('deliberate advice failure')):
            result = release_files([path], minimum_bytes=8)
        self.assertEqual(result['files'], [])
        self.assertEqual(result['bytes'], 0)
        self.assertEqual(result['errors'], [{'path': str(path), 'error': 'deliberate advice failure'}])
        self.assertEqual(path.read_bytes(), original)

    def test_gsim_command_binds_input_and_stops_before_constant_analysis(self):
        fixture = self.work / 'input.fir'
        fixture.write_text('circuit fixture :\n')
        args = self.args(firrtl=fixture, engine='gsim')
        command = capture.gsim_command(args, {'binary': '/frozen/gsim'}, self.work / 'timing.jsonl')
        self.assertEqual(command[0], '/frozen/gsim')
        self.assertEqual(command[-1], str(fixture))
        self.assertIn('--semantic-node-exchange-stage=F32', command)
        self.assertIn('--semantic-node-exchange-mode=snapshot', command)
        self.assertIn('--stop-after-stage=RemoveDeadNodes1', command)
        self.assertIn('--dump-assign-tree', command)
        self.assertIn('--dump-stages=' + ','.join(capture.GSIM_STAGES), command)
        self.assertFalse(any('--trace-node-evolution' in item for item in command))

    def write_table(self, path, *, rows=1, footer_rows=None, snapshot='snapshot', complete=True):
        meta = {'schema': 'semantic-node-exchange.v1', 'engine': 'grh', 'stage': 'stage',
                'run_id': 'run', 'snapshot_id': snapshot}
        text = '#meta\t' + json.dumps(meta) + '\nnode_id\n'
        text += ''.join(str(index) + '\n' for index in range(rows))
        text += '#footer\t' + json.dumps({'complete': complete, 'rowCount': rows if footer_rows is None else footer_rows}) + '\n'
        path.write_text(text)

    def test_tsv_validation_counts_rows_and_rejects_truncated_or_mixed_data(self):
        path = self.work / 'nodes.tsv'
        self.write_table(path, rows=3)
        self.assertEqual(capture.table_artifact(path)['footer']['rowCount'], 3)
        self.write_table(path, rows=3, footer_rows=4)
        with self.assertRaisesRegex(ValueError, 'incomplete native TSV'):
            capture.table_artifact(path)
        self.write_table(path, rows=0, complete=False)
        with self.assertRaises(ValueError):
            capture.table_artifact(path)
        self.write_table(path)
        with path.open('a') as stream:
            stream.write('9\n')
        with self.assertRaisesRegex(ValueError, 'data after TSV footer'):
            capture.table_artifact(path)

    def test_native_timer_validation_rejects_incomplete_and_nan(self):
        path = self.work / 'timing.jsonl'
        row = {'schema': 'gsim-stage-timing.v1', 'scope': 'pass', 'clock': 'steady_clock',
               'complete': True, 'stage': 'ExprOpt', 'pass_instance': 'ExprOpt#0', 'wall_s': 1.0}
        path.write_text(json.dumps(row) + '\n')
        self.assertEqual(capture.native_rows(path, 'gsim'), [row])
        for update in ({'complete': False}, {'wall_s': float('nan')}, {'clock': 'realtime'}):
            path.write_text(json.dumps({**row, **update}) + '\n')
            with self.assertRaises(ValueError):
                capture.native_rows(path, 'gsim')

    def test_gsim_full_structure_requires_the_native_functional_field_contract(self):
        path = self.work / 'gsim.json'
        complete = {'semanticLineageVersion': 1, 'nodeStructureSchema': 'gsim.node-structure.v1',
                    'nodeStructureComplete': True, 'assignmentOrder': 'native-vector-order', 'nodes': []}
        path.write_text(json.dumps(complete))
        actual = capture.structure_artifact(path, 'gsim')
        self.assertEqual(actual['schema'], 'gsim.node-structure.v1')
        self.assertTrue(actual['functional_fields_complete'])
        for changes in ({'nodeStructureSchema': 'old'}, {'nodeStructureComplete': False},
                        {'assignmentOrder': 'unknown'}):
            path.write_text(json.dumps({**complete, **changes}))
            with self.assertRaisesRegex(ValueError, 'functional-field contract'):
                capture.structure_artifact(path, 'gsim')
        path.write_text('{"semanticLineageVersion": 1, "nodes": []}')
        with self.assertRaisesRegex(ValueError, 'functional-field contract'):
            capture.structure_artifact(path, 'gsim')

    def test_descendant_sampler_is_used_for_both_engines_and_limits_are_forwarded(self):
        for engine in ('grh', 'gsim'):
            output = self.work / engine
            argv = ['capture_f32_pipeline.py', '--engine', engine, '--firrtl', 'input.fir',
                    '--output', str(output), '--resource-guard-psi-percent', '40',
                    '--resource-guard-psi-seconds', '12', '--resource-guard-interval-s', '0.5']
            argv += ['--package', 'package', '--manifest', 'manifest'] if engine == 'grh' else ['--binary', 'gsim']
            with patch.object(sys, 'argv', argv), patch.object(capture, 'run_guarded', return_value=0) as guarded:
                self.assertEqual(capture.main(), 0)
            command, actual_output, limits = guarded.call_args.args
            self.assertEqual(actual_output, output)
            self.assertEqual(limits, GuardLimits(psi_percent=40, psi_seconds=12, interval_s=0.5))
            self.assertEqual(command[-1], '--guard-child')
            self.assertIs(guarded.call_args.kwargs['sampler'], capture.process_tree_sample)
            self.assertIsNone(guarded.call_args.kwargs['phase_timeouts'])

    def test_split_nodes_timeout_is_forwarded_to_external_supervisor(self):
        output = self.work / 'bounded'
        argv = ['capture_f32_pipeline.py', '--engine', 'grh', '--firrtl', 'input.fir',
                '--package', 'package', '--manifest', 'manifest', '--output', str(output),
                '--split-nodes-timeout-seconds', '180']
        with patch.object(sys, 'argv', argv), patch.object(capture, 'run_guarded', return_value=0) as guarded:
            self.assertEqual(capture.main(), 0)
        self.assertEqual(guarded.call_args.kwargs['phase_timeouts'], {'split-nodes#0': 180})

    def test_invalid_or_gsim_split_timeout_is_rejected_before_start(self):
        for value in ('180', '-1', 'nan'):
            output = self.work / ('invalid-timeout-' + value)
            argv = ['capture_f32_pipeline.py', '--engine', 'gsim', '--firrtl', 'input.fir',
                    '--binary', 'gsim', '--output', str(output), '--split-nodes-timeout-seconds', value]
            with patch.object(sys, 'argv', argv), patch.object(capture, 'run_guarded') as guarded:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    capture.main()
            guarded.assert_not_called()
            self.assertFalse(output.exists())

    def test_existing_output_is_rejected_before_starting_a_child(self):
        sentinel = self.work / 'original.txt'
        sentinel.write_text('preserve this capture')
        argv = ['capture_f32_pipeline.py', '--engine', 'gsim', '--firrtl', 'input.fir',
                '--binary', 'gsim', '--output', str(self.work)]
        with patch.object(sys, 'argv', argv), patch.object(capture, 'run_guarded') as guarded:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                capture.main()
        self.assertEqual(error.exception.code, 2)
        guarded.assert_not_called()
        self.assertEqual(sentinel.read_text(), 'preserve this capture')

    def test_non_ptmp_output_and_invalid_resource_limits_are_rejected(self):
        for output, flags in ((ROOT / 'build/f32-bad-output', []),
                              (self.work / 'bad-rss', ['--resource-guard-rss-gib', 'nan']),
                              (self.work / 'bad-psi', ['--resource-guard-psi-percent', '101'])):
            argv = ['capture_f32_pipeline.py', '--engine', 'gsim', '--firrtl', 'input.fir',
                    '--binary', 'gsim', '--output', str(output), *flags]
            with patch.object(sys, 'argv', argv), patch.object(capture, 'run_guarded') as guarded:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    capture.main()
            self.assertEqual(error.exception.code, 2)
            guarded.assert_not_called()
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
