"""Public snapshot/journal contract tests, including corruption controls."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from semantic_node_exchange import HEADERS, KINDS, SCHEMA, compact, encode_cell, verify_bundle, verify_snapshot

ROOT = Path(__file__).resolve().parents[1]


def node(identifier, name):
    return {'node_id': identifier, 'name_path_json': [name], 'native_name': name}


def edge(identifier, source, target, kind='dependency'):
    return {'connection_id': identifier, 'source_node_id': source, 'target_node_id': target,
            'kind': kind, 'resolution': 'resolved', 'candidate_sources_json': [], 'reason': None}


def coverage(edges):
    return {kind: {'status': 'partial' if any(row['resolution'] == 'unresolved' and row['kind'] == kind for row in edges) else 'complete',
                   'resolved': sum(row['kind'] == kind and row['resolution'] == 'resolved' for row in edges),
                   'unresolved': sum(row['kind'] == kind and row['resolution'] == 'unresolved' for row in edges)} for kind in KINDS}


class ExchangeContractTests(unittest.TestCase):
    def setUp(self):
        work = ROOT / 'ptmp' / 'firrtl-ingest' / 'F29' / 'exchange-contract'
        work.mkdir(parents=True, exist_ok=True)
        self.directory = Path(tempfile.mkdtemp(dir=work))
        self.identity = {'schema': SCHEMA, 'engine': 'fixture', 'run_id': 'run',
                         'graph_id': 'top', 'exchange_session_id': 'session'}
        self.before_nodes = [node(1, 'input'), node(2, 'a'), node(3, 'out')]
        self.after_nodes = [self.before_nodes[0], self.before_nodes[2], node(4, 'a_0'), node(5, 'a_1')]
        self.before_edges = [edge(1, 1, 2), edge(2, 2, 3)]
        self.after_edges = [edge(3, 1, 4), edge(4, 1, 5), edge(5, 4, 3)]
        self.decisions = []
        self.events = [{'action': 'replace', 'reason': 'array_split',
                        'before_nodes': self.before_nodes[1:], 'after_nodes': self.after_nodes[1:],
                        'before_edges': self.before_edges, 'after_edges': self.after_edges,
                        'lineage': [(2, 4), (2, 5)]}]

    def tearDown(self):
        shutil.rmtree(self.directory)

    def snapshot(self, prefix, nodes, edges, snapshot_id):
        for table, definitions in (('nodes', nodes), ('connections', edges)):
            with (self.directory / f'{prefix}{table}.tsv').open('w') as stream:
                stream.write('#meta\t' + compact({**self.identity, 'snapshot_id': snapshot_id,
                                                 'stage': prefix or 'snapshot', 'table': table}) + '\n')
                stream.write('\t'.join(HEADERS[table]) + '\n')
                for row in sorted(definitions, key=lambda item: item['node_id' if table == 'nodes' else 'connection_id']):
                    fields = [compact(row[key]) if key.endswith('_json') and row[key] is not None else row[key]
                              for key in HEADERS[table]]
                    stream.write('\t'.join(map(encode_cell, fields)) + '\n')
                stream.write('#footer\t' + compact({'complete': True, 'rowCount': len(definitions),
                    **({'nodeInventoryComplete': True} if table == 'nodes' else {'connectionCoverage': coverage(edges)})}) + '\n')

    def write(self):
        self.snapshot('before.', self.before_nodes, self.before_edges, 'before')
        self.snapshot('after.', self.after_nodes, self.after_edges, 'after')
        self.rows = []
        def append(record, seq, **fields):
            ordinal = 0 if not self.rows or self.rows[-1]['seq'] != seq else self.rows[-1]['ordinal'] + 1
            self.rows.append({'record': record, 'seq': seq, 'ordinal': ordinal, **fields})
        append('header', 0, detail_json={**self.identity, 'mode': 'trace', 'pass': 'split-static-array',
                                        'before_snapshot_id': 'before', 'after_snapshot_id': 'after'})
        for decision in self.decisions:
            append('decision', 0, subject='node', side='before', **decision)
        for seq, event in enumerate(self.events, 1):
            append('event', seq, action=event['action'], reason=event['reason'])
            for side in ('before', 'after'):
                for subject, suffix in (('node', 'nodes'), ('connection', 'edges')):
                    for payload in event.get(side + '_' + suffix, []):
                        append('edit', seq, subject=subject, side=side,
                               object_id=payload['node_id' if subject == 'node' else 'connection_id'], detail_json=payload)
            for parent, child in event.get('lineage', []):
                append('lineage', seq, subject='node', side='before', object_id=parent,
                       detail_json={'to_node_id': child, 'relation': 'split'})
        append('footer', len(self.events), detail_json={
            'complete': True, 'replayComplete': True, 'eventCount': len(self.events),
            'beforeNodeCount': len(self.before_nodes), 'beforeConnectionCount': len(self.before_edges),
            'afterNodeCount': len(self.after_nodes), 'afterConnectionCount': len(self.after_edges),
            'nodeInventoryComplete': True, 'connectionCoverage': coverage(self.after_edges)})
        self.write_rows()

    def write_rows(self):
        with (self.directory / 'evolution.tsv').open('w') as stream:
            stream.write('\t'.join(HEADERS['evolution']) + '\n')
            for row in self.rows:
                stream.write('\t'.join(encode_cell(compact(row[key]) if key == 'detail_json' and row.get(key) is not None
                                                   else row.get(key)) for key in HEADERS['evolution']) + '\n')

    def decision(self, identifier=2, outcome='retain', blockers=None, **details):
        return {'object_id': identifier, 'reason': 'dynamic_update', 'detail_json': {
            'pass': 'split-static-array', 'outcome': outcome,
            'blocker_node_ids': [] if blockers is None else blockers, **details}}

    def test_decisions_replay_without_mutating_public_inventory(self):
        self.after_nodes, self.after_edges, self.events = self.before_nodes, self.before_edges, []
        self.decisions = [self.decision(blockers=[3, 1], update_ordinal=0, axis=1),
                          self.decision(1, outcome='replace')]
        self.write()
        original = {path.name: path.read_bytes() for path in self.directory.glob('*.tsv')}
        database = self.directory / 'decisions.sqlite'
        result = verify_bundle(self.directory, database)
        self.assertTrue(result['replay_exact'])
        self.assertEqual(result['events'], 0)
        self.assertEqual(result['decisions'], 2)
        self.assertEqual(result['actions'], {})
        self.assertEqual(original, {path.name: path.read_bytes() for path in self.directory.glob('*.tsv')})
        with sqlite3.connect(database) as db:
            for table in ('nodes', 'connections'):
                self.assertEqual(db.execute(f'SELECT * FROM before_{table} ORDER BY id').fetchall(),
                                 db.execute(f'SELECT * FROM current_{table} ORDER BY id').fetchall())
            decisions = db.execute("SELECT seq,ordinal,detail_json FROM evolution WHERE record='decision' ORDER BY ordinal").fetchall()
            self.assertEqual([(seq, ordinal) for seq, ordinal, _ in decisions], [(0, 1), (0, 2)])
            self.assertEqual([json.loads(detail) for _, _, detail in decisions],
                             [decision['detail_json'] for decision in self.decisions])

    def test_decisions_may_refer_to_before_nodes_retired_by_events(self):
        self.decisions = [self.decision(outcome='replace', blockers=[2])]
        self.write()
        self.assertTrue(verify_bundle(self.directory)['replay_exact'])

    def test_decision_pass_belongs_to_combined_header_pass_chain(self):
        self.decisions = [self.decision(), self.decision(1, **{'pass': 'comb-loop-elim'})]
        self.write()
        self.rows[0]['detail_json']['pass'] = 'comb-loop-elim,split-static-array'
        self.write_rows()
        self.assertEqual(verify_bundle(self.directory)['decisions'], 2)
        self.rows[2]['detail_json']['pass'] = 'grh-to-grhsim'
        self.write_rows()
        with self.assertRaisesRegex(ValueError, 'invalid native pass decision'):
            verify_bundle(self.directory)

    def test_decision_count_footer_is_optional_and_checked_when_present(self):
        for count in (0, 2):
            with self.subTest(count=count):
                self.decisions = [self.decision()] * count
                self.write()
                self.assertEqual(verify_bundle(self.directory)['decisions'], count)
                self.rows[-1]['detail_json']['decisionCount'] = count
                self.write_rows()
                self.assertEqual(verify_bundle(self.directory)['decisions'], count)
                for invalid in (None, True, -1, count + 1, float(count), str(count), [], {}):
                    with self.subTest(invalid=invalid):
                        self.rows[-1]['detail_json']['decisionCount'] = invalid
                        self.write_rows()
                        with self.assertRaisesRegex(ValueError, 'native decision count mismatch'):
                            verify_bundle(self.directory)

    def test_decision_nodes_and_blockers_must_be_in_before_inventory(self):
        for identifier, blockers in ((4, []), (2, [4]), (99, []), (2, [99])):
            with self.subTest(identifier=identifier, blockers=blockers):
                self.decisions = [self.decision(identifier, blockers=blockers)]
                self.write()
                (self.directory / 'after.nodes.tsv').unlink()
                with self.assertRaisesRegex(ValueError, 'outside the before inventory'):
                    verify_bundle(self.directory)

    def test_decision_rejects_malformed_blockers_with_value_error(self):
        for blockers in (None, '2', 2, {}, [1, 1], [True], [-1], [2**63], [1.0], ['1'], [[]], [{}]):
            with self.subTest(blockers=blockers):
                self.decisions = [self.decision()]
                self.decisions[0]['detail_json']['blocker_node_ids'] = blockers
                self.write()
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)

    def test_decision_requires_bound_pass_and_known_detail_fields(self):
        for change in ({'pass': 'comb-loop-elim'}, {'pass': []}, {'pass': ''}, {'pass': None},
                       {'outcome': 'delete'}, {'outcome': []}, {'outcome': None},
                       {'unexpected': True}):
            with self.subTest(change=change):
                self.decisions = [self.decision(**change)]
                self.write()
                with self.assertRaisesRegex(ValueError, 'invalid native pass decision'):
                    verify_bundle(self.directory)
        for missing in ('pass', 'outcome', 'blocker_node_ids'):
            with self.subTest(missing=missing):
                self.decisions = [self.decision()]
                del self.decisions[0]['detail_json'][missing]
                self.write()
                with self.assertRaisesRegex(ValueError, 'invalid native pass decision'):
                    verify_bundle(self.directory)

    def test_decision_coordinates_are_bounded_integer_scalars(self):
        for field in ('update_ordinal', 'axis'):
            for invalid in (None, True, -1, 2**64, 0.0, '0', [], {}):
                with self.subTest(field=field, invalid=invalid):
                    self.decisions = [self.decision(**{field: invalid})]
                    self.write()
                    with self.assertRaisesRegex(ValueError, 'invalid native decision coordinate'):
                        verify_bundle(self.directory)
            self.decisions = [self.decision(**{field: 2**64 - 1})]
            self.write()
            self.assertTrue(verify_bundle(self.directory)['replay_exact'])

    def test_decision_requires_before_node_reason_and_no_edit_action(self):
        for field, invalid in (('subject', 'connection'), ('side', 'after'), ('action', 'replace'),
                               ('reason', ''), ('reason', None), ('object_id', None)):
            with self.subTest(field=field, invalid=invalid):
                self.decisions = [self.decision()]
                self.write()
                self.rows[1][field] = invalid
                self.write_rows()
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)
        for malformed in (None, [], 'retain'):
            with self.subTest(detail=malformed):
                self.decisions = [self.decision()]
                self.write()
                self.rows[1]['detail_json'] = malformed
                self.write_rows()
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)

    def test_decision_after_events_is_rejected(self):
        self.write()
        footer = self.rows.pop()
        self.rows.append({'record': 'decision', 'seq': footer['seq'], 'ordinal': footer['ordinal'],
                          'subject': 'node', 'side': 'before', **self.decision()})
        footer['ordinal'] += 1
        self.rows.append(footer)
        self.write_rows()
        with self.assertRaisesRegex(ValueError, 'invalid native pass decision'):
            verify_bundle(self.directory)

    def test_malformed_header_pass_and_edit_kind_are_value_errors(self):
        for field, invalid in (('pass', []), ('after_snapshot_id', [])):
            with self.subTest(field=field):
                self.write()
                self.rows[0]['detail_json'][field] = invalid
                self.write_rows()
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)
        self.write()
        edit = next(row for row in self.rows if row['record'] == 'edit' and row['subject'] == 'connection')
        edit['detail_json']['kind'] = []
        self.write_rows()
        with self.assertRaises(ValueError):
            verify_bundle(self.directory)

    def test_split_replays_nodes_and_connections(self):
        self.write()
        result = verify_bundle(self.directory, self.directory / 'exchange.sqlite')
        self.assertTrue(result['replay_exact'])
        self.assertEqual(result['lineage_count'], 2)
        self.assertEqual(result['footer']['afterConnectionCount'], 3)

    def test_static_snapshot_is_independent_of_trace(self):
        self.snapshot('', self.before_nodes, self.before_edges, 'snapshot')
        self.assertTrue(verify_snapshot(self.directory)['complete'])
        self.assertFalse((self.directory / 'evolution.tsv').exists())

    def test_static_footer_requires_final_lf(self):
        for table in ('nodes', 'connections'):
            with self.subTest(table=table):
                self.snapshot('', self.before_nodes, self.before_edges, 'snapshot')
                path = self.directory / (table + '.tsv')
                path.write_bytes(path.read_bytes()[:-1])
                with self.assertRaisesRegex(ValueError, 'line ending'):
                    verify_snapshot(self.directory)

    def test_static_metadata_and_footer_reject_crlf(self):
        for table in ('nodes', 'connections'):
            for index in (0, -1):
                with self.subTest(table=table, index=index):
                    self.snapshot('', self.before_nodes, self.before_edges, 'snapshot')
                    path = self.directory / (table + '.tsv')
                    lines = path.read_bytes().splitlines(keepends=True)
                    lines[index] = lines[index][:-1] + b'\r\n'
                    path.write_bytes(b''.join(lines))
                    with self.assertRaisesRegex(ValueError, 'line ending'):
                        verify_snapshot(self.directory)

    def test_zero_event_pass(self):
        self.after_nodes, self.after_edges, self.events = self.before_nodes, self.before_edges, []
        self.write()
        self.assertEqual(verify_bundle(self.directory)['events'], 0)

    def test_same_id_implementation_touch_with_identical_public_state(self):
        self.after_nodes, self.after_edges = self.before_nodes, self.before_edges
        self.events = [{'action': 'replace', 'reason': 'internal_rewrite',
                        'before_nodes': [self.before_nodes[1]], 'after_nodes': [self.before_nodes[1]]}]
        self.write()
        self.assertEqual(verify_bundle(self.directory)['actions'], {'replace': 1})

    def test_add_then_delete_is_replayed(self):
        extra = node(8, 'temporary')
        self.after_nodes, self.after_edges = self.before_nodes, self.before_edges
        self.events = [{'action': 'add', 'reason': 'temporary_create', 'after_nodes': [extra]},
                       {'action': 'delete', 'reason': 'temporary_retire', 'before_nodes': [extra]}]
        self.write()
        self.assertEqual(verify_bundle(self.directory)['actions'], {'add': 1, 'delete': 1})

    def test_merge_multiple_nodes_and_edges(self):
        merged = node(8, 'merged')
        self.after_nodes = [self.before_nodes[0], merged]
        self.after_edges = [edge(8, 1, 8)]
        self.events = [{'action': 'replace', 'reason': 'merge', 'before_nodes': self.before_nodes[1:],
                        'after_nodes': [merged], 'before_edges': self.before_edges,
                        'after_edges': self.after_edges}]
        self.write()
        self.assertTrue(verify_bundle(self.directory)['replay_exact'])

    def test_retired_node_identity_cannot_be_reused(self):
        extra = node(8, 'temporary')
        self.after_nodes, self.after_edges = [*self.before_nodes, extra], self.before_edges
        self.events = [{'action': 'add', 'reason': 'create', 'after_nodes': [extra]},
                       {'action': 'delete', 'reason': 'retire', 'before_nodes': [extra]},
                       {'action': 'add', 'reason': 'reuse', 'after_nodes': [extra]}]
        self.write()
        with self.assertRaisesRegex(ValueError, 'retired identity'):
            verify_bundle(self.directory)

    def test_connection_only_change_uses_same_algebra(self):
        self.after_nodes = self.before_nodes
        self.after_edges = [self.before_edges[0], edge(9, 1, 3)]
        self.events = [{'action': 'replace', 'reason': 'dependency_retarget',
                        'before_edges': self.before_edges[1:], 'after_edges': self.after_edges[1:]}]
        self.write()
        self.assertTrue(verify_bundle(self.directory)['replay_exact'])

    def test_rewire_with_same_node_definitions(self):
        self.after_nodes, self.after_edges = self.before_nodes, [self.before_edges[0], edge(3, 1, 3)]
        self.events = [{'action': 'replace', 'reason': 'operand_retarget',
                        'before_nodes': [self.before_nodes[2]], 'after_nodes': [self.before_nodes[2]],
                        'before_edges': [self.before_edges[1]], 'after_edges': [self.after_edges[1]]}]
        self.write()
        self.assertTrue(verify_bundle(self.directory)['replay_exact'])

    def test_tsv_escaping_and_null_are_distinct(self):
        self.before_nodes[1] = node(2, 'a\t.\\N\n行')
        self.after_nodes, self.after_edges, self.events = self.before_nodes, self.before_edges, []
        self.write()
        self.assertTrue(verify_bundle(self.directory)['replay_exact'])

    def test_missing_incident_edge_deletion_is_rejected(self):
        self.events[0]['before_edges'] = self.before_edges[:1]
        self.write()
        with self.assertRaisesRegex(ValueError, 'inactive Node'):
            verify_bundle(self.directory)

    def test_actual_after_cannot_supply_missing_event(self):
        self.events = []
        self.write()
        with self.assertRaisesRegex(ValueError, 'inventory count mismatch'):
            verify_bundle(self.directory)

    def test_bad_precondition_is_rejected_before_after_is_opened(self):
        self.events[0]['before_nodes'] = [node(2, 'wrong'), self.before_nodes[2]]
        self.write()
        (self.directory / 'after.nodes.tsv').unlink()
        with self.assertRaisesRegex(ValueError, 'precondition'):
            verify_bundle(self.directory)

    def test_tampered_after_is_rejected(self):
        self.write()
        changed = deepcopy(self.after_nodes)
        changed[1]['native_name'] = 'tampered'
        self.snapshot('after.', changed, self.after_edges, 'after')
        with self.assertRaisesRegex(ValueError, 'differs from actual after'):
            verify_bundle(self.directory)

    def test_invalid_lineage_is_rejected(self):
        self.events[0]['lineage'] = [(1, 4)]
        self.write()
        with self.assertRaisesRegex(ValueError, 'outside its event'):
            verify_bundle(self.directory)

    def test_incorrect_action_is_rejected(self):
        self.events[0]['action'] = 'add'
        self.write()
        with self.assertRaisesRegex(ValueError, 'cardinalities'):
            verify_bundle(self.directory)

    def test_duplicate_edit_is_rejected(self):
        self.events[0]['after_nodes'].append(self.after_nodes[-1])
        self.write()
        with self.assertRaises(ValueError):
            verify_bundle(self.directory)

    def test_truncated_evolution_is_rejected(self):
        self.write()
        self.rows.pop()
        self.write_rows()
        with self.assertRaisesRegex(ValueError, 'truncated'):
            verify_bundle(self.directory)

    def test_duplicate_semantic_connection_is_rejected(self):
        self.after_edges.append(edge(6, 4, 3))
        self.write()
        with self.assertRaises(ValueError):
            verify_bundle(self.directory)

    def test_different_snapshot_identity_is_rejected(self):
        self.write()
        self.identity['run_id'] = 'another-run'
        self.snapshot('after.', self.after_nodes, self.after_edges, 'after')
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            verify_bundle(self.directory)

    def test_forged_coverage_counts_are_rejected(self):
        self.write()
        self.rows[-1]['detail_json']['connectionCoverage']['dependency']['resolved'] = 99
        self.write_rows()
        with self.assertRaisesRegex(ValueError, 'coverage differs'):
            verify_bundle(self.directory)

    def test_missing_coverage_categories_are_rejected(self):
        self.write()
        self.rows[-1]['detail_json']['connectionCoverage'] = {}
        self.write_rows()
        with self.assertRaisesRegex(ValueError, 'coverage categories'):
            verify_bundle(self.directory)


if __name__ == '__main__':
    unittest.main()
