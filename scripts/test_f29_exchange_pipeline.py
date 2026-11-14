"""Exercise both native producers through ordinary FIRRTL pass entry points."""
from collections import defaultdict
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import unittest

from semantic_node_exchange import verify_bundle, verify_snapshot
from benchmark_xs_firrtl_ingest import checked

ROOT = Path(__file__).resolve().parents[1]


def public_state(database, prefix='current'):
    with sqlite3.connect(database) as db:
        nodes = {identifier: json.loads(body) for identifier, body in db.execute(f'SELECT * FROM {prefix}_nodes')}
        edges = [json.loads(body) for body, in db.execute(f'SELECT body FROM {prefix}_connections')]
    return nodes, edges


def semantic_edges(edges):
    return {json.dumps({key: value for key, value in edge.items() if key != 'connection_id'}, sort_keys=True)
            for edge in edges}


def compare_public_states(left, right):
    """Names only locate Node candidates; compare public resolved edges separately."""
    nodes, edges = left
    other_nodes, other_edges = right
    index, own_index = defaultdict(list), defaultdict(list)
    for identifier, row in other_nodes.items():
        if row['name_path_json'] is not None:
            index[tuple(row['name_path_json'])].append(identifier)
    for identifier, row in nodes.items():
        if row['name_path_json'] is not None:
            own_index[tuple(row['name_path_json'])].append(identifier)
    pairs = {identifiers[0]: index[path][0] for path, identifiers in own_index.items()
             if len(identifiers) == 1 and len(index[path]) == 1}
    native = {(row['source_node_id'], row['target_node_id'], row['kind'])
              for row in other_edges if row['resolution'] == 'resolved'}
    expected = {(row['source_node_id'], row['target_node_id'], row['kind'])
                for row in edges if row['resolution'] == 'resolved'}
    translated = {(pairs[source], pairs[target], kind) for source, target, kind in expected
                  if source in pairs and target in pairs}
    comparable_native = {edge for edge in native if edge[0] in pairs.values() and edge[1] in pairs.values()}
    return {'grh_nodes': len(nodes), 'gsim_nodes': len(other_nodes), 'unique_candidates': len(pairs),
            'grh_resolved_connections': len(expected), 'gsim_resolved_connections': len(native),
            'grh_unresolved': sum(row['resolution'] == 'unresolved' for row in edges),
            'gsim_unresolved': sum(row['resolution'] == 'unresolved' for row in other_edges),
            'matched_connections': len(translated & comparable_native),
            'grh_only_connections': sorted(translated - comparable_native),
            'gsim_only_connections': sorted(comparable_native - translated)}


@unittest.skipUnless(os.environ.get('F29_GSIM_BINARY'), 'run via make test_f29_exchange_pipeline')
class NativeExchangePipelineTests(unittest.TestCase):
    def assert_exports(self, directory, traced):
        expected = ({'before.nodes.tsv', 'before.connections.tsv', 'evolution.tsv',
                     'after.nodes.tsv', 'after.connections.tsv'} if traced else
                    {'nodes.tsv', 'connections.tsv'})
        self.assertEqual({path.name for path in directory.glob('*.tsv')}, expected)
        self.assertFalse((directory / '.evolution.pending').exists())

    def test_static_and_pass_native_five_file_export(self):
        import wolvrix
        work = Path(os.environ['F29_WORK']).resolve() / 'exchange-pipeline'
        work.mkdir(parents=True, exist_ok=True)
        reports = []
        fixtures = [ROOT / 'wolvrix/tests/ingest/data/firrtl' / (name + '.fir') for name in (
            'f28-arrays', 'f28-bundles', 'f28-state', 'f28-hierarchy', 'f28-comb-boundaries',
            'f28-memory-effects', 'f30-split-projections')]
        fixtures.append(ROOT / 'reference/gsim/test/node-evolution.fir')
        for fixture in fixtures:
            with self.subTest(fixture=fixture.name):
                directory = work / fixture.stem
                directory.mkdir(parents=True, exist_ok=True)
                grh_replays, snapshots = {}, {}
                for mode in ('plain', 'traced'):
                    with wolvrix.Session() as session:
                        request = {'sources': [{'path': str(fixture), 'language': 'firrtl', 'unit': 'f29'}],
                                   'firrtl_options': {'invalid_policy': 'zero', 'node_annotations': True}}
                        checked(session.read_sources(**request, out_design='design.main', pipeline='ingest'), 'ingest')
                        for name in ('xmr-resolve', 'hier-flatten'):
                            checked(session.run_pass(name, design='design.main', keep_declared_symbols=True), name)
                        stages = [('flatten', None), ('comb-loop-elim', 'comb-loop-elim'),
                                  ('split-static-array', 'split-static-array')]
                        for stage, name in stages:
                            output = directory / f'grh-{mode}-{stage}'
                            if name:
                                if mode == 'traced':
                                    session.semantic_exchange_start(design='design.main', output=str(output),
                                                                    stage='before-' + stage, pass_name=name)
                                checked(session.run_pass(name, design='design.main'), name)
                                if mode == 'traced':
                                    session.semantic_exchange_finish(design='design.main', stage=stage)
                                    database = output / 'verified.sqlite'
                                    database.unlink(missing_ok=True)
                                    result = verify_bundle(output, database)
                                    self.assertTrue(result['replay_exact'])
                                    self.assert_exports(output, True)
                                    grh_replays[name] = result
                            if mode == 'plain' or not name:
                                session.semantic_snapshot(design='design.main', output=str(output), stage=stage)
                                database = output / 'snapshot.sqlite'
                                database.unlink(missing_ok=True)
                                snapshots[f'grh-{mode}-{stage}'] = verify_snapshot(output, database)
                                self.assert_exports(output, False)
                            checked(session.store_json(design='design.main', output=str(directory / f'{mode}-{stage}.json'),
                                                       mode='pretty-compact', emit_source_locations=True), stage)
                for stage in ('flatten', 'comb-loop-elim', 'split-static-array'):
                    self.assertEqual((directory / f'plain-{stage}.json').read_bytes(),
                                     (directory / f'traced-{stage}.json').read_bytes())
                    plain = public_state(directory / f'grh-plain-{stage}/snapshot.sqlite')
                    traced = public_state(directory / f'grh-traced-{stage}' /
                                          ('snapshot.sqlite' if stage == 'flatten' else 'verified.sqlite'))
                    self.assertEqual(plain[0], traced[0])
                    self.assertEqual(semantic_edges(plain[1]), semantic_edges(traced[1]))
                gsim = directory / 'gsim-trace'
                gsim.mkdir(exist_ok=True)
                command = [os.environ['F29_GSIM_BINARY'], '--dir', str(directory / 'gsim-output'),
                           '--stop-after-stage=SplitArray', '--semantic-node-exchange=' + str(gsim),
                           '--semantic-node-exchange-mode=trace', str(fixture)]
                with (directory / 'gsim-trace.log').open('w') as stream:
                    subprocess.run(command, cwd=ROOT / 'reference/gsim', stdout=stream, stderr=subprocess.STDOUT, check=True)
                database = gsim / 'verified.sqlite'
                database.unlink(missing_ok=True)
                native = verify_bundle(gsim, database)
                self.assert_exports(gsim, True)
                for stage in ('Init', 'SplitArray'):
                    snapshot = directory / ('gsim-snapshot-' + stage)
                    snapshot.mkdir(exist_ok=True)
                    command = [os.environ['F29_GSIM_BINARY'], '--dir', str(directory / 'gsim-output'),
                               '--stop-after-stage=' + stage, '--semantic-node-exchange=' + str(snapshot),
                               '--semantic-node-exchange-mode=snapshot', '--semantic-node-exchange-stage=' + stage, str(fixture)]
                    with (directory / ('gsim-snapshot-' + stage + '.log')).open('w') as stream:
                        subprocess.run(command, cwd=ROOT / 'reference/gsim', stdout=stream, stderr=subprocess.STDOUT, check=True)
                    snapshot_db = snapshot / 'verified.sqlite'
                    snapshot_db.unlink(missing_ok=True)
                    snapshots['gsim-' + stage] = verify_snapshot(snapshot, snapshot_db)
                    self.assert_exports(snapshot, False)
                    exported = public_state(snapshot_db)
                    reference = public_state(database, 'before' if stage == 'Init' else 'after')
                    self.assertEqual(exported[0], reference[0])
                    self.assertEqual(semantic_edges(exported[1]), semantic_edges(reference[1]))
                comparison = compare_public_states(
                    public_state(directory / 'grh-traced-split-static-array/verified.sqlite'), public_state(database))
                reports.append({'fixture': str(fixture), 'grh_replays': grh_replays,
                                'gsim_replay': native, 'snapshots': snapshots, 'comparison': comparison})
        (work / 'summary.json').write_text(json.dumps({'complete': True, 'fixtures': reports}, indent=2) + '\n')


if __name__ == '__main__':
    unittest.main()
