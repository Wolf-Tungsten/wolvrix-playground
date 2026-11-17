"""DCE integration from raw FIRRTL, with native pass journals and static graphs."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

from benchmark_f29_pass_trace import native_identity
from benchmark_f30_pipeline import verify_loaded_native, verify_package_identity
from benchmark_xs_firrtl_ingest import checked
from compare_f31_dce_equivalence import capture_actual_state, compare
from semantic_node_exchange import verify_bundle, verify_snapshot

ROOT = Path(__file__).resolve().parents[1]
STATIC_FILES = {'nodes.tsv', 'connections.tsv', 'bit-slices.tsv', 'node-endpoints.tsv'}
TRACE_FILES = {'before.nodes.tsv', 'before.connections.tsv', 'evolution.tsv',
               'after.nodes.tsv', 'after.connections.tsv'}


def public_state(database, prefix='current'):
    with sqlite3.connect(database) as db:
        nodes = {identifier: json.loads(body) for identifier, body in
                 db.execute(f'SELECT * FROM {prefix}_nodes')}
        edges = {json.dumps({key: value for key, value in json.loads(body).items()
                             if key != 'connection_id'}, sort_keys=True)
                 for body, in db.execute(f'SELECT body FROM {prefix}_connections')}
    return nodes, edges


@unittest.skipUnless(os.environ.get('F31_PACKAGE'), 'run via make test_f31_pipeline')
class RawFirrtlDcePipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.package = Path(os.environ['F31_PACKAGE']).resolve()
        identity = verify_package_identity(cls.package, cls.package / 'identity.json')
        cls.identity = identity
        # Import the recorded native package, rather than an editable install
        # that could silently pick up a different core after a later build.
        sys.meta_path[:] = [finder for finder in sys.meta_path
                            if not type(finder).__module__.startswith('_wolvrix_editable')]
        sys.path.insert(0, str(cls.package))
        import wolvrix
        verify_loaded_native(cls.package, identity, native_identity(wolvrix))
        cls.wolvrix = wolvrix
        cls.work = Path(os.environ['F31_WORK']).resolve() / 'pipeline-tests' / 'raw-firrtl'
        cls.work.mkdir(parents=True, exist_ok=True)

    def assert_export_files(self, directory, expected):
        self.assertEqual({path.name for path in directory.glob('*.tsv')}, expected)
        self.assertFalse((directory / '.evolution.pending').exists())

    def snapshot(self, session, directory, stage):
        directory.mkdir(parents=True, exist_ok=True)
        session.semantic_snapshot(design='design.main', output=str(directory), stage=stage)
        self.assert_export_files(directory, STATIC_FILES)
        database = directory / 'snapshot.sqlite'
        database.unlink(missing_ok=True)
        self.assertTrue(verify_snapshot(directory, database)['complete'])
        return public_state(database)

    def store(self, session, path):
        checked(session.store_json(design='design.main', output=str(path),
                                   mode='pretty-compact', emit_source_locations=True), 'store actual IR')
        return json.loads(path.read_text())

    def test_partial_array_and_native_reference_fixture_journals_replay(self):
        artifacts = Path(os.environ.get('F31_NATIVE_ARTIFACTS', ROOT / 'wolvrix/build/artifacts'))
        reports = []
        bundles = {name: artifacts / 'dce-array-update' / name for name in (
            'reverse-overlap', 'native-boundary-remap', 'RegisterArrayLane', 'RegisterConcatLane',
            'IndexedStateArrayLane', 'IndexedStateConcatLane', 'LatchArrayLane', 'LatchConcatLane')}
        bundles.update({name: artifacts / name for name in ('f31-retention-witness', 'f31-hierarchical-public')})
        bundles['f31-declared-storage-root'] = artifacts / 'f31-declared-storage-root'
        bundles.update({name: artifacts / name for name in (
            'f31-dce-residual-anchor', 'f31-dce-residual-shared', 'f31-dce-residual-reverse')})
        for name, bundle in bundles.items():
            with self.subTest(fixture=name):
                self.assertTrue(bundle.is_dir(), 'run make test_f31_dce to produce native correctness fixtures')
                database = self.work / (name + '.sqlite')
                database.unlink(missing_ok=True)
                report = verify_bundle(bundle, database)
                self.assertTrue(report['replay_exact'])
                self.assertGreater(report['decisions'], 0)
                for kind, coverage in report['footer']['connectionCoverage'].items():
                    self.assertEqual(coverage['status'], 'complete', f'{kind} lost native coverage')
                    self.assertEqual(coverage['unresolved'], 0)
                reports.append({'fixture': name, 'replay': report})
        (self.work / 'native-correctness-replay.json').write_text(json.dumps(reports, indent=2) + '\n')

    def test_native_transition_and_compact_provenance_replay(self):
        artifacts = Path(os.environ.get('F31_NATIVE_ARTIFACTS', ROOT / 'wolvrix/build/artifacts'))
        reports = []
        for name in ('public-exchange-boundary-retirement', 'public-exchange-owner-retirement',
                     'public-exchange-candidate-resolved', 'public-liveness-spool'):
            with self.subTest(fixture=name):
                database = self.work / (name + '.sqlite')
                database.unlink(missing_ok=True)
                report = verify_bundle(artifacts / 'semantic-nodes' / name, database)
                self.assertTrue(report['complete'] and report['replay_exact'])
                if name == 'public-liveness-spool':
                    self.assertEqual(report['liveness_provenance_count'], 16393)
                    self.assertEqual(report['events'], 0)
                else:
                    self.assertEqual(report['connection_transition_evidence'], 1)
                    if name != 'public-exchange-candidate-resolved':
                        self.assertEqual(report['boundary_retirement_count'], 1)
                reports.append({'fixture': name, 'replay': report})
        (self.work / 'native-transition-provenance-replay.json').write_text(json.dumps(reports, indent=2) + '\n')

    def test_native_removed_operand_boundary_replay(self):
        artifacts = Path(os.environ.get('F31_NATIVE_ARTIFACTS', ROOT / 'wolvrix/build/artifacts')) / 'semantic-nodes'
        positive = {'resolved-data': (1, 1), 'resolved-clock': (1, 1), 'resolved-reset': (1, 1),
                    'resolved-predicate': (1, 1), 'candidates': (2, 1), 'aborted-capture': (1, 1),
                    'forced-source-touch': (1, 1), 'overlapping-groups': (3, 2),
                    'fallback': (1, 1), 'named': (1, 1), 'wildcard': (1, 1),
                    'mixed-candidates': (2, 1), 'selected-read': (1, 1), 'delete-operand': (1, 1),
                    'path-one-step': (1, 1), 'path-two-step': (1, 1), 'path-duplicate-prefix': (1, 1)}
        bundles = sorted(artifacts.glob('public-exchange-pruned-operand-*'))
        self.assertEqual(len(bundles), 35, 'run the coordinated native regression Make target')
        reports = []
        for bundle in bundles:
            with self.subTest(fixture=bundle.name):
                database = self.work / (bundle.name + '.sqlite')
                database.unlink(missing_ok=True)
                report = verify_bundle(bundle, database)
                self.assertTrue(report['complete'] and report['replay_exact'])
                name = bundle.name.removeprefix('public-exchange-pruned-operand-')
                self.assertEqual((report['connection_removal_evidence_records'],
                                  report['connection_removal_evidence_connections']), positive.get(name, (0, 0)))
                reports.append({'fixture': name, 'replay': report})
        (self.work / 'native-removal-replay.json').write_text(json.dumps(reports, indent=2) + '\n')

    def test_native_dead_anchor_cone_replay(self):
        artifacts = Path(os.environ.get('F31_NATIVE_ARTIFACTS', ROOT / 'wolvrix/build/artifacts')) / 'semantic-nodes'
        expected = {'resolved': (1, 1, 1), 'candidates': (1, 2, 1), 'fallback': (1, 1, 1),
                    'selected-read': (1, 1, 1), 'aborted-capture': (1, 1, 1),
                    'renamed-source': (1, 0, 0), 'deleted-source': (1, 0, 0),
                    'renamed-target': (0, 0, 0), 'deleted-target': (0, 0, 0),
                    'unprepared': (0, 0, 0), 'wrong-key': (0, 0, 0), 'remapped-fact': (1, 1, 1)}
        bundles = sorted(artifacts.glob('public-exchange-dead-anchor-*'))
        self.assertEqual({bundle.name.removeprefix('public-exchange-dead-anchor-') for bundle in bundles},
                         set(expected), 'run the coordinated native regression Make target')
        reports = []
        for bundle in bundles:
            with self.subTest(fixture=bundle.name):
                database = self.work / (bundle.name + '.sqlite')
                database.unlink(missing_ok=True)
                report = verify_bundle(bundle, database)
                name = bundle.name.removeprefix('public-exchange-dead-anchor-')
                self.assertTrue(report['complete'] and report['replay_exact'])
                self.assertEqual(report['header']['connection_anchor_removal_trace'], 'dead-anchor-cone.v1')
                self.assertEqual((report['anchor_removal_count'],
                                  report['connection_anchor_removal_evidence_records'],
                                  report['connection_anchor_removal_evidence_connections']), expected[name])
                self.assertEqual((report['connection_removal_evidence_records'],
                                  report['connection_removal_evidence_connections']), expected[name][1:])
                self.assertEqual(report['footer']['mutationRecordCount'], 0)
                reports.append({'fixture': name, 'replay': report})
        (self.work / 'native-dead-anchor-replay.json').write_text(json.dumps(reports, indent=2) + '\n')

    def test_raw_ingest_prefix_trace_equivalence_and_native_timing(self):
        fixtures = [ROOT / 'wolvrix/tests/ingest/data/firrtl' / (name + '.fir') for name in (
            'f28-arrays', 'f28-bundles', 'f28-state', 'f28-hierarchy',
            'f28-comb-boundaries', 'f28-memory-effects', 'f30-split-projections')]
        fixtures.append(ROOT / 'reference/gsim/test/node-evolution.fir')
        reports = []
        total_deleted = 0
        for fixture in fixtures:
            with self.subTest(fixture=fixture.name):
                outputs = {}
                fixture_sha = hashlib.sha256(fixture.read_bytes()).hexdigest()
                for traced in (False, True):
                    mode = 'trace' if traced else 'no-trace'
                    directory = self.work / fixture.stem / mode
                    directory.mkdir(parents=True, exist_ok=True)
                    with self.wolvrix.Session() as session:
                        session.log_level = 'error'
                        session.diagnostics_raise_min_level = 'none'
                        checked(session.read_sources(
                            sources=[{'path': str(fixture), 'language': 'firrtl', 'unit': 'f31'}],
                            firrtl_options={'invalid_policy': 'zero', 'node_annotations': True},
                            out_design='design.main', pipeline='ingest'), 'raw FIRRTL ingest')
                        for name in ('xmr-resolve', 'hier-flatten', 'comb-loop-elim', 'split-static-array'):
                            checked(session.run_pass(name, design='design.main',
                                                     keep_declared_symbols=name != 'split-static-array'),
                                    name)
                        before = self.snapshot(session, directory / 'before', 'post-split-static-array')
                        before_ir = self.store(session, directory / 'before.json')
                        trace_dir = directory / 'dce'
                        if traced:
                            trace_dir.mkdir(exist_ok=True)
                            session.semantic_exchange_start(
                                design='design.main', output=str(trace_dir), stage='post-split-static-array',
                                pass_name='dead-code-elim', input_sha256=fixture_sha,
                                pass_instance='dead-code-elim#0')
                        timing = directory / 'native-timing.jsonl'
                        timing.unlink(missing_ok=True)
                        checked(session.run_pass('dead-code-elim', design='design.main',
                                                 keep_declared_symbols=False, timing_output=str(timing)), 'DCE')
                        history = session.history()[-1]
                        self.assertTrue(history['success'])
                        timer_rows = [json.loads(row) for row in timing.read_text().splitlines()]
                        self.assertEqual(len(timer_rows), 1)
                        timer = timer_rows[0]
                        self.assertEqual(timer['schema'], 'grh-stage-timing.v1')
                        self.assertEqual(timer['stage'], 'dead-code-elim')
                        self.assertEqual(timer['pass_instance'], 'dead-code-elim#0')
                        self.assertEqual(timer['scope'], 'pass')
                        self.assertEqual(timer['clock'], 'steady_clock')
                        self.assertIs(timer['complete'], True)
                        self.assertTrue(math.isfinite(timer['wall_s']) and timer['wall_s'] >= 0)
                        replay = None
                        if traced:
                            session.semantic_exchange_finish(design='design.main', stage='post-dead-code-elim')
                            self.assert_export_files(trace_dir, TRACE_FILES)
                            database = trace_dir / 'replay.sqlite'
                            database.unlink(missing_ok=True)
                            replay = verify_bundle(trace_dir, database)
                            self.assertTrue(replay['complete'] and replay['replay_exact'])
                            self.assertEqual(replay['header']['input_sha256'], fixture_sha)
                            self.assertEqual(public_state(database, 'before'), before)
                        checked(session.run_pass('grh.verify', design='design.main'), 'post-DCE grh.verify')
                        self.assertTrue(session.semantic_validate(design='design.main')['valid'])
                        after = self.snapshot(session, directory / 'after', 'post-dead-code-elim')
                        after_ir = self.store(session, directory / 'after.json')
                        before_nodes, after_nodes = before[0], after[0]
                        self.assertLessEqual(set(after_nodes), set(before_nodes))
                        for identifier, node in after_nodes.items():
                            self.assertEqual(node, before_nodes[identifier], 'DCE changed a surviving Node identity/name/path')
                        if traced:
                            self.assertEqual(public_state(database, 'after'), after)
                            total_deleted += len(before_nodes) - len(after_nodes)
                        checked(session.run_pass('dead-code-elim', design='design.main',
                                                 keep_declared_symbols=False), 'second DCE')
                        self.assertFalse(session.history()[-1]['changed'], 'second DCE was not idempotent')
                        again = self.snapshot(session, directory / 'again', 'second-dead-code-elim')
                        self.assertEqual(again, after)
                        self.assertEqual(self.store(session, directory / 'again.json'), after_ir)
                        outputs[mode] = {'before': before, 'after': after,
                                         'before_ir': before_ir, 'after_ir': after_ir}
                        reports.append({'fixture': str(fixture), 'sha256': fixture_sha, 'mode': mode,
                                        'before_nodes': len(before_nodes), 'after_nodes': len(after_nodes),
                                        'native_timing': timer, 'replay': replay})
                self.assertEqual(outputs['trace'], outputs['no-trace'],
                                 'DCE trace changed actual circuit structure or public Node graph')
        self.assertGreater(total_deleted, 0, 'fixtures did not exercise actual Node retirement')
        (self.work / 'summary.json').write_text(json.dumps(
            {'complete': True, 'fixtures': reports, 'traced_deleted_nodes': total_deleted}, indent=2) + '\n')

    def test_raw_pruned_operand_support_contexts(self):
        fixtures = {
            'f31-pruned-scalar-array-concat': None,
            'f31-pruned-scalar-array-concat-retained': None,
            'f31-pruned-named-array-update': 'named',
            'f31-pruned-selected-state-concat': 'selected_read',
        }
        reports = []
        for name, expected_context in fixtures.items():
            with self.subTest(fixture=name):
                fixture = ROOT / 'wolvrix/tests/ingest/data/firrtl' / (name + '.fir')
                fixture_sha = hashlib.sha256(fixture.read_bytes()).hexdigest()
                outputs = {}
                for traced in (False, True):
                    mode = 'trace' if traced else 'no-trace'
                    directory = self.work / name / mode
                    directory.mkdir(parents=True, exist_ok=True)
                    with self.wolvrix.Session() as session:
                        session.log_level = 'error'
                        session.diagnostics_raise_min_level = 'none'
                        checked(session.read_sources(
                            sources=[{'path': str(fixture), 'language': 'firrtl', 'unit': 'f31'}],
                            firrtl_options={'invalid_policy': 'zero', 'node_annotations': True},
                            out_design='design.main', pipeline='ingest'), 'raw FIRRTL ingest')
                        for prefix in ('xmr-resolve', 'hier-flatten', 'comb-loop-elim', 'split-static-array'):
                            checked(session.run_pass(prefix, design='design.main',
                                                     keep_declared_symbols=prefix != 'split-static-array'), prefix)
                        before = self.snapshot(session, directory / 'before', 'post-split-static-array')
                        before_ir = self.store(session, directory / 'before.json')
                        trace_dir = directory / 'dce'
                        if traced:
                            trace_dir.mkdir(exist_ok=True)
                            session.semantic_exchange_start(
                                design='design.main', output=str(trace_dir), stage='post-split-static-array',
                                pass_name='dead-code-elim', input_sha256=fixture_sha,
                                pass_instance='dead-code-elim#0', connection_evidence_at_finish=True)
                        checked(session.run_pass('dead-code-elim', design='design.main',
                                                 keep_declared_symbols=False), 'DCE')
                        if traced:
                            session.semantic_exchange_finish(design='design.main', stage='post-dead-code-elim')
                        checked(session.run_pass('grh.verify', design='design.main'), 'post-DCE grh.verify')
                        self.assertTrue(session.semantic_validate(design='design.main')['valid'])
                        after = self.snapshot(session, directory / 'after', 'post-dead-code-elim')
                        after_ir = self.store(session, directory / 'after.json')
                        checked(session.run_pass('dead-code-elim', design='design.main',
                                                 keep_declared_symbols=False), 'second DCE')
                        self.assertFalse(session.history()[-1]['changed'], 'second DCE was not idempotent')
                        self.assertEqual(self.snapshot(session, directory / 'again', 'second-dead-code-elim'), after)
                        self.assertEqual(self.store(session, directory / 'again.json'), after_ir)
                    outputs[mode] = (before, before_ir, after, after_ir)
                    if not traced:
                        continue
                    self.assert_export_files(trace_dir, TRACE_FILES)
                    database = directory / 'replay.sqlite'
                    database.unlink(missing_ok=True)
                    replay = verify_bundle(trace_dir, database)
                    self.assertTrue(replay['complete'] and replay['replay_exact'])
                    self.assertEqual(replay['header']['connection_removal_trace'], 'pruned-operand-support.v2')
                    self.assertEqual(public_state(database, 'before'), before)
                    self.assertEqual(public_state(database, 'after'), after)
                    with sqlite3.connect(database) as db:
                        evidence = [json.loads(body) for body, in db.execute(
                            'SELECT detail_json FROM connection_removal_evidence ORDER BY seq,ordinal')]
                        reasons = dict(db.execute('SELECT mutation_id,reason FROM operand_mutations'))
                        old_connections = [(identifier, json.loads(body), key) for identifier, body, key in
                                           db.execute('SELECT id,body,key FROM before_connections ORDER BY id')]
                        after_keys = {key for key, in db.execute('SELECT key FROM after_connections')}
                    removed_surviving = []
                    for identifier, edge, key in old_connections:
                        sources = ([edge['source_node_id']] if edge['source_node_id'] is not None
                                   else edge['candidate_sources_json'])
                        endpoints = [edge['target_node_id'], *sources]
                        if (edge['kind'] == 'dependency' and key not in after_keys and sources and
                                all(node in after[0] and before[0][node] == after[0][node] for node in endpoints)):
                            removed_surviving.append({'connection_id': identifier, 'edge': edge})
                    supported_connections = {support['connection_id'] for support in evidence}
                    uncovered = [edge for edge in removed_surviving
                                 if edge['connection_id'] not in supported_connections]
                    self.assertEqual(len(evidence), replay['connection_removal_evidence_records'])
                    self.assertEqual(len(before_ir['graphs']), 1)
                    graph = before_ir['graphs'][0]
                    operation_kinds = {operation['id']: operation['kind'] for operation in graph['ops']}
                    target_kinds = {node['id']: {operation_kinds[operation] for operation in node['ops']}
                                    for node in graph['semanticTree']['nodes']}
                    contexts = set()
                    context_supports = []
                    for support in evidence:
                        source, target = support['source_node_id'], support['target_node_id']
                        self.assertEqual(before[0][source], after[0][source])
                        self.assertEqual(before[0][target], after[0][target])
                        reference = (support['reference_operation_id'], support['reference_operation_generation'])
                        actual = (support['operation_id'], support['operation_generation'])
                        for step in support['path']:
                            actual = (step['definition_operation_id'], step['definition_operation_generation'])
                        definition = (support['value_definition_operation_id'],
                                      support['value_definition_operation_generation'])
                        if support['support_kind'] == 'fallback_value_owner':
                            context = 'fallback_value_owner'
                            self.assertIsNone(support['boundary_kind'])
                            self.assertEqual(support['reference_target_node_id'], 0)
                            self.assertEqual(reference, (0, 0))
                            self.assertIsNone(support['reference_operand_index'])
                        else:
                            self.assertEqual(support['support_kind'], 'boundary_use')
                            self.assertEqual(support['boundary_kind'], 'data')
                            self.assertEqual(support['reference_target_node_id'], target)
                            if reference == (0, 0):
                                context = 'named'
                                self.assertIsNone(support['reference_operand_index'])
                            elif reference != actual:
                                context = 'selected_read'
                                self.assertEqual(reference, definition)
                                self.assertIsNone(support['reference_operand_index'])
                            else:
                                context = 'exact' if support['reference_operand_index'] is not None else 'wildcard'
                        contexts.add(context)
                        if context == expected_context:
                            context_supports.append(support)
                    if expected_context is not None:
                        self.assertEqual(uncovered, [], 'removed dependency between surviving Nodes lacks native support')
                        self.assertGreater(replay['connection_removal_evidence_connections'], 0)
                        self.assertIn(expected_context, contexts)
                        expected_reason = ('array_update_group_pruning' if expected_context == 'named'
                                           else 'undemanded_operand_defined_zero')
                        expected_kind = 'kCombArrayUpdate' if expected_context == 'named' else 'kConcat'
                        self.assertTrue(any(reasons[support['mutation_id']] == expected_reason and
                                            expected_kind in target_kinds[support['target_node_id']]
                                            for support in context_supports))
                    if name == 'f31-pruned-scalar-array-concat-retained':
                        self.assertEqual(len(removed_surviving), 13)
                        self.assertEqual(uncovered, [], 'transitive Concat pruning lacks native path support')
                        self.assertEqual(len(supported_connections), 13)
                        self.assertTrue(all(len(support['path']) == 1 and
                                            reasons[support['mutation_id']] == 'undemanded_operand_defined_zero' and
                                            'kConcat' in target_kinds[support['target_node_id']]
                                            for support in evidence))
                    reports.append({'fixture': str(fixture), 'sha256': fixture_sha,
                                    'support_contexts': sorted(contexts), 'supports': evidence,
                                    'removed_surviving': removed_surviving, 'uncovered_removed_surviving': uncovered,
                                    'replay': replay})
                self.assertEqual(outputs['trace'], outputs['no-trace'],
                                 'DCE support tracing changed actual IR or the public Node graph')
        (self.work / 'raw-pruned-operand-support.json').write_text(json.dumps(reports, indent=2) + '\n')

    def test_actual_state_equivalence_workflow(self):
        fixture = ROOT / 'wolvrix/tests/ingest/data/firrtl/f28-state.fir'
        root = self.work / 'actual-equivalence'
        root.mkdir(exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix='run-', dir=root))
        samples = []
        for mode in ('no-trace', 'trace'):
            directory = work / mode
            directory.mkdir(parents=True, exist_ok=True)
            with self.wolvrix.Session() as session:
                session.log_level = 'error'
                checked(session.read_sources(
                    sources=[{'path': str(fixture), 'language': 'firrtl', 'unit': 'f31'}],
                    firrtl_options={'invalid_policy': 'zero', 'node_annotations': True},
                    out_design='design.main', pipeline='ingest'), 'raw FIRRTL ingest')
                for name in ('xmr-resolve', 'hier-flatten', 'comb-loop-elim', 'split-static-array'):
                    checked(session.run_pass(name, design='design.main',
                                             keep_declared_symbols=name != 'split-static-array'), name)
                if mode == 'trace':
                    session.semantic_exchange_start(design='design.main', output=str(directory / 'dce'),
                                                    pass_name='dead-code-elim', pass_instance='dead-code-elim#0')
                checked(session.run_pass('dead-code-elim', design='design.main', keep_declared_symbols=False), 'DCE')
                if mode == 'trace':
                    session.semantic_exchange_finish(design='design.main')
                after = capture_actual_state(session, directory / 'after', 'post-dead-code-elim')
                checked(session.run_pass('dead-code-elim', design='design.main', keep_declared_symbols=False), 'second DCE')
                history = session.history()[-1]
                again = capture_actual_state(session, directory / 'again', 'second-dead-code-elim')
            sample = {'schema': 'wolvrix.f31.dce-benchmark.v1', 'engine': 'grh', 'mode': mode,
                      'verify': True, 'status': 'passed', 'source': 'raw-firrtl',
                      'input_sha256': hashlib.sha256(fixture.read_bytes()).hexdigest(),
                      'manifest_sha256': None, 'configuration': {}, 'package_identity': self.identity,
                      'sources': [{'path': str(fixture), 'sha256': hashlib.sha256(fixture.read_bytes()).hexdigest()}],
                      'dependencies': {},
                      'dce': {'actual_after': after, 'actual_repeated': again, 'repeated_dce_history': history}}
            path = directory / 'summary.json'
            path.write_text(json.dumps(sample, indent=2) + '\n')
            samples.append(path)
        report = compare(*samples)
        self.assertTrue(report['passed'])
        (work / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    unittest.main()
