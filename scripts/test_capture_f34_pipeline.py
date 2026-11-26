"""F34 window order, immutable reference evidence, and supervisor contracts."""
from argparse import Namespace
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import capture_f34_pipeline as capture
from benchmark_f29_pass_trace import sha256
from capture_f34_pipeline import gsim_times, production_calls
from f30_resource_guard import GuardLimits
from f33_guard import F34, SupervisorLimits, build_reference, run_guarded
from f33_guard import validate_reference
from test_f33_guard import fixed_sample


def timers():
    calls = [('RemoveDeadNodes#1', 'RemoveDeadNodes2'), *((timer, stage) for _, timer, stage in F34.calls)]
    return [{'schema': 'gsim-stage-timing.v1', 'scope': 'pass', 'stage': stage,
             'pass_instance': timer, 'wall_s': 0.05, 'clock': 'steady_clock', 'complete': True}
            for timer, stage in calls]


def events(run_id, engine, started):
    return [dict(run_id=run_id, engine=engine, logical_instance=logical,
                 input_boundary=f'R{i}', event=kind, monotonic_s=started,
                 **({'wall_s': 0.05} if kind == 'end' else {}))
            for i, logical in enumerate(F34.passes) for kind in ('start', 'end')]


class F34Contract(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.identity = {'semantics': '2state', 'batch_count': 1, 'input': {'sha256': 'a' * 64},
                         'configuration': {'window': [list(call) for call in F34.calls]},
                         'grh': {'source_sha256': 'b' * 64, 'binary_sha256': 'c' * 64, 'build': {'mode': 'Release'}},
                         'gsim': {'source_sha256': 'd' * 64, 'binary_sha256': 'e' * 64, 'build': {'mode': 'Release'}}}

    def samples(self, *, wrong_timer_order=False):
        result = []
        for i in range(3):
            run_id = f'gsim-{i}'
            rows = timers()
            times = gsim_times(rows)
            if wrong_timer_order and not i:
                rows[1], rows[2] = rows[2], rows[1]
            guard = {'schema': F34.guard_schema, 'status': 'completed', 'run_id': run_id, 'engine': 'gsim',
                     'resource_interference': False, 'reference_identity': self.identity, 'pass_times_s': times}
            artifacts = []
            for kind, content in (('native-timing', rows), ('stage-events', events(run_id, 'gsim', time.monotonic())),
                                  ('guard', [guard])):
                path = self.directory / f'{run_id}-{kind}.jsonl'
                path.write_text(''.join(json.dumps(record) + '\n' for record in content))
                artifacts.append({'kind': kind, 'path': str(path), 'sha256': sha256(path)})
            result.append({**guard, 'fresh_graphs': 1, 'reference_evidence': artifacts})
        return result

    def supervise(self, rows, body, reference):
        output = self.directory / 'guarded'
        command = [sys.executable, '-c', """
import json, os, subprocess, sys, time
from pathlib import Path
output = Path(sys.argv[1])
rows = json.loads(sys.argv[2])
def emit(row):
    with (output / 'stage-events.jsonl').open('a') as stream:
        stream.write(json.dumps(dict(row, monotonic_s=time.monotonic())) + '\\n')
""" + body, str(output), json.dumps(rows)]
        code = run_guarded(command, output, run_id='grh', engine='grh', identity=self.identity,
                           reference=reference, window=F34, sampler=fixed_sample,
                           limits=SupervisorLimits(resources=GuardLimits(terminate_grace_s=0.05),
                                                   prefix_s=2, between_passes_s=2, suffix_s=2, overall_s=4))
        return code, json.loads((output / 'guard.json').read_text())

    def test_reference_binds_native_order_and_exact_four_calls(self):
        samples = self.samples()
        reference = build_reference(samples, self.identity, F34)
        self.assertEqual(reference['passes']['dead-code-elim#3']['native_timer'], 'RemoveDeadNodes#2')
        self.assertEqual(reference['passes']['dead-code-elim#3']['budget_s'], 0.1)
        with self.assertRaises(ValueError):
            build_reference(samples[:2], self.identity, F34)
        with self.assertRaisesRegex(ValueError, 'expected pass order'):
            build_reference(self.samples(wrong_timer_order=True), self.identity, F34)

    def test_wrong_dce_or_successor_invalidates_stop(self):
        rows = timers()
        for extra in (rows[-1], dict(rows[-1], stage='graphPartition', pass_instance='graphPartition#0')):
            with self.assertRaises(ValueError):
                gsim_times([*rows, extra])
        with self.assertRaises(ValueError):
            gsim_times([*rows[:-1], dict(rows[-1], pass_instance='RemoveDeadNodes#1')])
        with self.assertRaises(ValueError):
            production_calls([('alias-analysis', {}), ('dead-code-elim', {})])

    def test_alias_capture_requires_native_third_dce_then_alias_analysis(self):
        rows = timers()[:2]
        self.assertEqual(gsim_times(rows, alias_only=True), {'alias-analysis#0': 0.05})
        for invalid in (rows[1:], rows + timers()[2:3]):
            with self.assertRaises(ValueError):
                gsim_times(invalid, alias_only=True)

    def test_missing_reference_fails_before_spawn(self):
        with self.assertRaisesRegex(ValueError, 'F34 GSIM reference'):
            self.supervise([], "raise Exception('must not spawn')", None)
        self.assertFalse((self.directory / 'guarded').exists())

    def test_gsim_samples_can_be_bound_to_new_grh_candidate(self):
        samples = self.samples()
        candidate = {**self.identity, 'grh': {**self.identity['grh'], 'binary_sha256': 'f' * 64}}
        reference = build_reference(samples, candidate, F34)
        self.assertEqual(reference['identity'], candidate)
        self.assertEqual(validate_reference(reference, candidate, F34)['dead-code-elim#3'], 0.1)
        with self.assertRaisesRegex(ValueError, 'mismatched F34'):
            validate_reference(reference, self.identity, F34)
        changed_gsim = {**candidate, 'gsim': {**candidate['gsim'], 'binary_sha256': 'f' * 64}}
        with self.assertRaisesRegex(ValueError, 'mismatched GSIM reference sample'):
            build_reference(samples, changed_gsim, F34)

    def test_slow_export_and_r4_stop(self):
        rows = events('grh', 'grh', 0)
        code, report = self.supervise(rows, """
for row in rows:
    emit(row)
    if row['event'] == 'end': time.sleep(0.15)
""", build_reference(self.samples(), self.identity, F34))
        self.assertEqual(code, 0)
        self.assertEqual(report['completed_passes'], list(F34.passes))
        self.assertGreater(report['wall_s'], 0.6)

    def check_alias_snapshots(self, *, mode, r0_rhs=False):
        calls = []
        session = Mock()
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=False)
        validation = {'valid': True, 'error_count': 0}
        session.read_sources.return_value = {'success': True}
        session.semantic_validate.side_effect = lambda **_: calls.append('validate') or validation
        session.semantic_snapshot.side_effect = lambda output, rhs_only=False, **_: (
            calls.append(Path(output).name + (' RHS' if rhs_only else '')) or {'success': True})

        def run_pass(_, name, *, logical_instance, timing_output, **kwargs):
            calls.append(logical_instance)
            Path(timing_output).write_text(name)
            if trace := kwargs.get('trace_alias_migrations'):
                Path(trace).write_text('trace')
            return {'success': True}

        modules = {'wolvrix': SimpleNamespace(Session=lambda: session, _run_pass_batch=run_pass),
                   'wolvrix_xs_grhsim': SimpleNamespace(firrtl_canonical_pipeline=lambda **_: [])}
        window = [(name, logical, False, {}) for name, logical in zip(capture.GRH_NAMES, F34.passes)]
        args = Namespace(mode=mode, engine='grh', output=self.directory, package=self.directory,
                         run_id='grh', batch_count=1, top=None, snapshots=False, alias_snapshots=True,
                         detail_node_ids_file=self.directory / 'detail-ids.json', r0_rhs=r0_rhs)
        args.detail_node_ids_file.write_text('[3, 8]')
        report = {'snapshots': {}, 'reference_identity': self.identity}

        def artifact(path):
            point = path.parent.name
            index = int(point[1:])
            metadata = {'engine': 'grh', 'stage': capture.GRH_STAGES[index],
                        'run_id': 'grh', 'graph_id': 'fixture', 'snapshot_id': point}
            if path.name == 'rhs-root-signatures.tsv':
                metadata.update(schema='rhs-root-signature.v2', stage=point, scope='all',
                                snapshot_id='rhs-' + point)
            return {'metadata': metadata, 'footer': {'rowCount': 1}}

        with (patch.dict(sys.modules, modules), patch.object(sys, 'path', sys.path.copy()),
              patch.object(sys, 'meta_path', sys.meta_path.copy()), patch.object(capture, 'native_identity'),
              patch.object(capture, 'verify_loaded_native'),
              patch.object(capture, 'production_calls', return_value=([], window)),
              patch.object(capture, 'grh_timer', return_value={'wall_s': 0.05}),
              patch.object(capture, 'table_artifact', side_effect=artifact) as table):
            capture.grh_run(args, {}, {}, report, self.directory / 'summary.json')
            capture.snapshot_artifacts(args, report)

        expected = ['validate', 'R0', F34.passes[0], 'validate', 'R1']
        if r0_rhs:
            expected.insert(2, 'R0 RHS')
            self.assertIn('rhs-root-signatures.tsv', report['snapshots']['R0']['artifacts'])
        if mode == 'capture':
            expected.extend([*F34.passes[1:], 'validate'])
            self.assertEqual(report['stop_boundary'], 'R4')
            self.assertEqual(report['r4_semantic_validation'], [validation])
        else:
            self.assertEqual(report['stop_boundary'], 'R1')
            self.assertEqual(report['pass_times_s'], {'alias-analysis#0': 0.05})
        self.assertEqual(calls, expected)
        self.assertEqual(tuple(report['snapshots']), ('R0', 'R1'))
        self.assertEqual([call.kwargs['detail_node_ids'] for call in session.semantic_snapshot.call_args_list
                          if not call.kwargs.get('rhs_only')],
                         [[3, 8], [3, 8]])
        self.assertEqual({call.args[0].parent.name for call in table.call_args_list}, {'R0', 'R1'})

    def test_alias_snapshots_export_two_boundaries_and_validate_r4(self):
        self.check_alias_snapshots(mode='capture')

    def test_alias_capture_stops_at_r1(self):
        self.check_alias_snapshots(mode='alias-capture')

    def test_alias_capture_records_full_r0_signatures_before_rewrite(self):
        self.check_alias_snapshots(mode='alias-capture', r0_rhs=True)

    def test_timeout_names_last_complete_boundary_and_cleans_group(self):
        rows = events('grh', 'grh', 0)
        code, report = self.supervise(rows, """
helper = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'])
(output / 'helper.pid').write_text(str(helper.pid))
for row in rows[:5]: emit(row)
time.sleep(20)
""", build_reference(self.samples(), self.identity, F34))
        self.assertEqual(code, 2)
        self.assertEqual(report['trigger']['kind'], 'running-pass-at-budget')
        self.assertEqual(report['trigger']['logical_instance'], 'common-expr#0')
        self.assertEqual(report['trigger']['last_complete_boundary'], 'R2')
        output = self.directory / 'guarded'
        self.assertTrue((output / 'guard-trigger.json').is_file())
        status = Path('/proc') / (output / 'helper.pid').read_text() / 'status'
        if status.exists():
            self.assertIn('State:\tZ', status.read_text())


if __name__ == '__main__':
    unittest.main()
