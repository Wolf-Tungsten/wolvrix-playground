"""Public snapshot/journal contract tests, including corruption controls."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import semantic_node_exchange as exchange_reader
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

    def write(self, *, operand_mutations=(), anchor_removals=()):
        self.snapshot('before.', self.before_nodes, self.before_edges, 'before')
        self.snapshot('after.', self.after_nodes, self.after_edges, 'after')
        self.rows = []
        def append(record, seq, **fields):
            ordinal = 0 if not self.rows or self.rows[-1]['seq'] != seq else self.rows[-1]['ordinal'] + 1
            self.rows.append({'record': record, 'seq': seq, 'ordinal': ordinal, **fields})
        has_transition_evidence = any(event.get('transition_evidence') for event in self.events)
        has_removal_evidence = any(event.get('removal_evidence') for event in self.events)
        all_removal_items = [item for event in self.events for item in event.get('removal_evidence', [])]
        anchor_evidence = [item for item in all_removal_items if item['cause'] == 'dead_anchor_cone']
        operation_evidence = [item for item in all_removal_items if item['cause'] == 'removed_operation_path']
        removal_items = [item for item in all_removal_items
                         if item['cause'] not in ('dead_anchor_cone', 'removed_operation_path')]
        has_anchor_removal = bool(anchor_removals or anchor_evidence)
        has_operation_removal = bool(operation_evidence)
        removal_trace = ('pruned-operand-support.v2' if any('path' in item for item in removal_items) else
                         'pruned-operand-support.v1' if any('support_kind' in item for item in removal_items) else
                         'pruned-operand-boundary.v1')
        append('header', 0, detail_json={**self.identity, 'mode': 'trace', 'pass': 'split-static-array',
                                        'before_snapshot_id': 'before', 'after_snapshot_id': 'after',
                                        **({'connection_transition_trace': 'candidate-prune.v1'}
                                           if has_transition_evidence else {}),
                                        **({'mutation_trace': 'operand-rewrite.v1'} if operand_mutations else {}),
                                        **({'connection_removal_trace': removal_trace}
                                           if removal_items else {}),
                                        **({'connection_anchor_removal_trace': 'dead-anchor-cone.v1'}
                                           if has_anchor_removal else {}),
                                        **({'connection_operation_removal_trace': 'removed-operation-path.v1'}
                                           if has_operation_removal else {})})
        for mutation in operand_mutations:
            append('mutation', 0, action=mutation['action'], reason=mutation['reason'], subject='operand',
                   side='transition', object_id=mutation['operation_id'], detail_json=mutation['detail'])
        for removal in anchor_removals:
            append('mutation', 0, action='delete', reason='dead_anchor_definition', subject='anchor',
                   side='before', object_id=removal['target_node_id'], detail_json=removal['detail'])
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
            for evidence in event.get('transition_evidence', []):
                append('evidence', seq, action=None, reason=evidence['detail']['cause'],
                       subject='connection', side='after', object_id=evidence['connection_id'],
                       detail_json=evidence['detail'])
            for evidence in event.get('removal_evidence', []):
                append('evidence', seq, action=None, reason=evidence['cause'], subject='connection',
                       side='before', object_id=evidence['connection_id'], detail_json=evidence)
        append('footer', len(self.events), detail_json={
            'complete': True, 'replayComplete': True, 'eventCount': len(self.events),
            'beforeNodeCount': len(self.before_nodes), 'beforeConnectionCount': len(self.before_edges),
            'afterNodeCount': len(self.after_nodes), 'afterConnectionCount': len(self.after_edges),
            'nodeInventoryComplete': True, 'connectionCoverage': coverage(self.after_edges),
            **({'connectionTransitionEvidenceCount': sum(len(event.get('transition_evidence', []))
                                                          for event in self.events)}
               if has_transition_evidence else {}),
            **({'mutationRecordCount': len(operand_mutations)} if operand_mutations else {}),
            **({'anchorRemovalRecordCount': len(anchor_removals),
                'connectionAnchorRemovalEvidenceRecordCount': len(anchor_evidence),
                'connectionAnchorRemovalEvidenceConnectionCount': len({item['connection_id']
                    for item in anchor_evidence})} if has_anchor_removal else {}),
            **({'connectionOperationRemovalEvidenceRecordCount': len(operation_evidence),
                'connectionOperationRemovalEvidenceConnectionCount': len({item['connection_id']
                    for item in operation_evidence})} if has_operation_removal else {}),
            **({'connectionRemovalEvidenceRecordCount': sum(len(event.get('removal_evidence', []))
                                                            for event in self.events),
                'connectionRemovalEvidenceConnectionCount': len({item['connection_id']
                    for event in self.events for item in event.get('removal_evidence', [])})}
               if has_removal_evidence or has_anchor_removal else {})})
        self.write_rows()

    def write_rows(self):
        with (self.directory / 'evolution.tsv').open('w') as stream:
            stream.write('\t'.join(HEADERS['evolution']) + '\n')
            for row in self.rows:
                stream.write('\t'.join(encode_cell(compact(row[key]) if key == 'detail_json' and row.get(key) is not None
                                                   else row.get(key)) for key in HEADERS['evolution']) + '\n')

    def set_liveness_provenance(self, records):
        self.write()
        self.rows[0]['detail_json']['liveness_provenance'] = 'dce-causality.v1'
        for row in self.rows[1:]:
            if row['seq'] == 0:
                row['ordinal'] += len(records)
        for ordinal, detail in enumerate(records, 1):
            self.rows.insert(ordinal, {'record': 'provenance', 'seq': 0, 'ordinal': ordinal,
                'action': None, 'reason': detail['relation'], 'subject': 'liveness', 'side': 'before',
                'object_id': ordinal, 'detail_json': detail})
        footer = self.rows[-1]
        footer['detail_json']['livenessProvenanceCount'] = len(records)
        self.write_rows()

    def write_with_connection_evidence(self, witnesses, mutations=None):
        self.write()
        self.rows[0]['detail_json']['connection_evidence'] = 'postpass-native-walk'
        if mutations is not None:
            self.rows[0]['detail_json']['mutation_trace'] = 'operand-rewrite.v1'
            mutation_rows = [{'record': 'mutation', 'seq': 0, 'ordinal': 0,
                              'action': item['action'], 'reason': item['reason'],
                              'subject': 'operand', 'side': 'transition',
                              'object_id': item['operation_id'], 'detail_json': item['detail']}
                             for item in mutations]
        else:
            mutation_rows = []
        evidence_rows = []
        for witness in witnesses:
            evidence_rows.append({'record': 'evidence', 'seq': 0, 'ordinal': 0, 'action': None,
                                  'reason': 'postpass-native-witness', 'subject': 'connection', 'side': 'after',
                                  'object_id': witness['connection_id'], 'detail_json': witness})
        self.rows[1:1] = mutation_rows + evidence_rows
        for seq in {row['seq'] for row in self.rows}:
            ordinal = 0
            for row in self.rows:
                if row['seq'] == seq:
                    row['ordinal'] = ordinal
                    ordinal += 1
        expected = {connection['connection_id']
                    for event in self.events for connection in event.get('after_edges', [])
                    if connection['kind'] == 'dependency'}
        footer = self.rows[-1]['detail_json']
        footer.update(connectionEvidenceRequestCount=len(expected),
                      connectionEvidenceConnectionCount=len({item['connection_id'] for item in witnesses}),
                      connectionEvidenceRecordCount=len(witnesses),
                      **({'mutationRecordCount': len(mutations),
                          'connectionEvidenceMutationMatchCount': sum('mutation_id' in item for item in witnesses)}
                         if mutations is not None else {}),
                      connectionEvidenceMissingSupportCount=sum(
                          item['witness_kind'] == 'missing_native_boundary' for item in witnesses))
        self.write_rows()

    @staticmethod
    def boundary_witness(connection_id, source, target, *, value=11, operation=21, boundary_kind='data'):
        return {'phase': 'postpass-native-walk', 'connection_id': connection_id,
                'witness_kind': 'boundary_use', 'supporting_node_id': source,
                'reference_target_node_id': target, 'value_id': value, 'value_generation': 0,
                'operation_id': operation, 'operation_generation': 0, 'operand_index': 0,
                'reference_operation_id': operation, 'reference_operation_generation': 0,
                'reference_operand_index': 0, 'value_definition_operation_id': operation + 1,
                'value_definition_operation_generation': 0, 'boundary_kind': boundary_kind}

    @staticmethod
    def operand_mutation(*, operation=21, slot=0, before_value=10, after_value=11):
        return {'action': 'replace', 'reason': 'array_update_group_pruning', 'operation_id': operation,
                'detail': {'mutation_id': 1, 'pass': 'split-static-array', 'operation_generation': 0,
                           'owner_node_ids': [2],
                           'before_slot': slot, 'before_value_id': before_value,
                           'before_value_generation': 0, 'after_slot': slot,
                           'after_value_id': after_value, 'after_value_generation': 0}}

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

    def test_operation_removal_summary_decision_replays(self):
        detail = {'pass': 'split-static-array', 'outcome': 'replace', 'blocker_node_ids': [],
                  'operation_removal_count': 2, 'operation_ids_hash': '0123456789abcdef',
                  'first_operation': 17, 'last_operation': 29}
        self.decisions = [{'object_id': 2, 'reason':
                           'owned_operations_removed;count=2;hash=0123456789abcdef',
                           'detail_json': detail}]
        self.write()
        self.assertTrue(verify_bundle(self.directory)['replay_exact'])

    def test_operation_removal_summary_rejects_incomplete_or_inconsistent_evidence(self):
        valid = {'pass': 'split-static-array', 'outcome': 'replace', 'blocker_node_ids': [],
                 'operation_removal_count': 2, 'operation_ids_hash': '0123456789abcdef',
                 'first_operation': 17, 'last_operation': 29}
        invalid = [
            {**valid, 'operation_removal_count': 0},
            {**valid, 'operation_ids_hash': 'not-a-hash'},
            {**valid, 'last_operation': -1},
            {**valid, 'outcome': 'retain'},
            {key: value for key, value in valid.items() if key != 'last_operation'},
        ]
        for detail in invalid:
            with self.subTest(detail=detail):
                self.decisions = [{'object_id': 2,
                    'reason': 'owned_operations_removed;count=2;hash=0123456789abcdef',
                    'detail_json': detail}]
                self.write()
                with self.assertRaisesRegex(ValueError, 'operation-removal summary'):
                    verify_bundle(self.directory)

    def test_decision_cannot_refer_to_a_node_created_by_a_later_event(self):
        for identifier, blockers in ((4, []), (2, [4])):
            with self.subTest(identifier=identifier, blockers=blockers):
                self.decisions = [self.decision(identifier, blockers=blockers)]
                self.write()
                (self.directory / 'after.nodes.tsv').unlink()
                with self.assertRaisesRegex(ValueError, 'outside the before inventory'):
                    verify_bundle(self.directory)

    def test_decision_refs_checked_for_zero_event_pass_before_opening_after(self):
        self.after_nodes, self.after_edges, self.events = self.before_nodes, self.before_edges, []
        self.decisions = [self.decision(blockers=[999])]
        self.write()
        (self.directory / 'after.nodes.tsv').unlink()
        with self.assertRaisesRegex(ValueError, 'outside the before inventory'):
            verify_bundle(self.directory)

    def test_delete_decision_requires_actual_node_retirement(self):
        self.decisions = [self.decision(outcome='delete')]
        self.write()
        self.assertTrue(verify_bundle(self.directory)['replay_exact'])
        self.decisions = [self.decision(1, outcome='delete')]
        self.write()
        with self.assertRaisesRegex(ValueError, 'delete decision.*surviving'):
            verify_bundle(self.directory)

    def test_structured_dce_deletion_evidence_replays_and_is_validated(self):
        evidence = {'rule': 'dead_owner_anchor', 'anchor_count': 1, 'demanded_anchor_count': 0,
                    'owned_operation_count': 2, 'live_owned_operation_count': 1,
                    'port_root': False, 'protected_boundary_root': False, 'state_family': False,
                    'memory_node': False, 'zero_width_boundary': False}
        detail = {'pass': 'split-static-array', 'outcome': 'delete', 'blocker_node_ids': [],
                  'dce_deletion': evidence}
        self.decisions = [{'object_id': 2, 'reason': evidence['rule'], 'detail_json': detail}]
        self.write()
        self.assertTrue(verify_bundle(self.directory)['replay_exact'])

        invalid = []
        invalid.append({**detail, 'outcome': 'retain'})
        invalid.append({**detail, 'blocker_node_ids': [1]})
        invalid.append({**detail, 'dce_deletion': {**evidence, 'rule': []}})
        invalid.append({**detail, 'dce_deletion': {**evidence, 'anchor_count': True}})
        invalid.append({**detail, 'dce_deletion': {**evidence, 'demanded_anchor_count': 2}})
        invalid.append({**detail, 'dce_deletion': {**evidence, 'live_owned_operation_count': 3}})
        invalid.append({**detail, 'dce_deletion': {**evidence, 'port_root': 0}})
        invalid.append({**detail, 'dce_deletion': {**evidence, 'unexpected': False}})
        invalid.append({**detail, 'dce_deletion': {key: value for key, value in evidence.items()
                                                     if key != 'memory_node'}})
        for candidate in invalid:
            with self.subTest(candidate=candidate):
                self.decisions = [{'object_id': 2, 'reason': 'dead_owner_anchor', 'detail_json': candidate}]
                self.write()
                with self.assertRaisesRegex(ValueError, 'invalid structured DCE deletion evidence'):
                    verify_bundle(self.directory)
        self.decisions = [{'object_id': 2, 'reason': 'different_rule', 'detail_json': detail}]
        self.write()
        with self.assertRaisesRegex(ValueError, 'invalid structured DCE deletion evidence'):
            verify_bundle(self.directory)

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
                       {'outcome': 'add'}, {'outcome': []}, {'outcome': None},
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

    def test_liveness_payload_is_stored_once_without_weakening_stream_checks(self):
        records = [
            {'relation': 'root', 'entity_kind': 'value', 'entity_id': 44, 'generation': 0,
             'root_kind': 'output_port'},
            {'relation': 'start', 'node_id': 2, 'start_kind': 'anchor',
             'entity_kind': 'value', 'entity_id': 44, 'generation': 0},
        ]
        self.set_liveness_provenance(records)
        database = self.directory / 'single-provenance.sqlite'
        report = verify_bundle(self.directory, database)
        self.assertTrue(report['replay_exact'])
        self.assertEqual(report['liveness_provenance_count'], len(records))
        self.assertEqual(report['footer']['livenessProvenanceCount'], len(records))
        with sqlite3.connect(database) as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM evolution WHERE record='provenance'").fetchone()[0], 0)
            self.assertEqual([json.loads(row[0]) for row in db.execute(
                'SELECT detail_json FROM liveness_provenance ORDER BY id')], records)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM evolution WHERE record IN ('header','footer')").fetchone()[0], 2)
        self.rows[2]['ordinal'] += 1
        self.write_rows()
        with self.assertRaisesRegex(ValueError, 'noncontiguous record ordinal'):
            verify_bundle(self.directory)

    def test_liveness_batches_flush_at_limit_and_before_other_record_kinds(self):
        records = [{'relation': 'root', 'entity_kind': 'value', 'entity_id': 44, 'generation': 0,
                    'root_kind': 'output_port'}]
        records.extend({'relation': 'start', 'node_id': 2, 'start_kind': 'anchor',
                        'entity_kind': 'value', 'entity_id': 44 + index, 'generation': 0}
                       for index in range(1, 5))
        self.set_liveness_provenance(records)
        # A decision between provenance runs must flush the partial preceding
        # run even though no event/footer has consumed the table yet.
        decision = {'record': 'decision', 'seq': 0, 'action': None, 'subject': 'node', 'side': 'before',
                    **self.decision(1, outcome='retain')}
        self.rows.insert(4, decision)
        for index, row in enumerate(self.rows):
            if row['seq'] == 0:
                row['ordinal'] = index
        self.write_rows()
        batches = []
        original_connect = sqlite3.connect

        class RecordingConnection(sqlite3.Connection):
            def executemany(self, statement, parameters):
                if 'INSERT INTO liveness_provenance' in statement:
                    parameters = list(parameters)
                    batches.append(len(parameters))
                return super().executemany(statement, parameters)

        def connect(*args, **kwargs):
            return original_connect(*args, factory=RecordingConnection, **kwargs)

        database = self.directory / 'batched-provenance.sqlite'
        with patch.object(exchange_reader, 'PROVENANCE_BATCH_SIZE', 2), \
                patch.object(exchange_reader.sqlite3, 'connect', connect):
            result = verify_bundle(self.directory, database)
        self.assertTrue(result['replay_exact'])
        self.assertEqual(result['liveness_provenance_count'], len(records))
        self.assertEqual(batches, [2, 1, 2])
        with sqlite3.connect(database) as db:
            self.assertEqual([json.loads(row[0]) for row in db.execute(
                'SELECT detail_json FROM liveness_provenance ORDER BY id')], records)

    def test_liveness_tail_batch_is_visible_to_footer_validation(self):
        self.after_nodes, self.after_edges, self.events = self.before_nodes, self.before_edges, []
        records = [{'relation': 'start', 'node_id': 999, 'start_kind': 'anchor',
                    'entity_kind': 'value', 'entity_id': 44, 'generation': 0}]
        self.set_liveness_provenance(records)
        with patch.object(exchange_reader, 'PROVENANCE_BATCH_SIZE', 2):
            with self.assertRaisesRegex(ValueError, 'outside the before Node inventory'):
                verify_bundle(self.directory)
        records[0]['node_id'] = 2
        self.set_liveness_provenance(records)
        with patch.object(exchange_reader, 'PROVENANCE_BATCH_SIZE', 2):
            self.assertTrue(verify_bundle(self.directory)['replay_exact'])
        self.rows[1]['ordinal'] += 1
        self.write_rows()
        with patch.object(exchange_reader, 'PROVENANCE_BATCH_SIZE', 2):
            with self.assertRaisesRegex(ValueError, 'noncontiguous record ordinal'):
                verify_bundle(self.directory)

    def test_derived_database_page_cache_has_a_bounded_budget(self):
        with sqlite3.connect(':memory:') as db:
            exchange_reader.create_database(db)
            self.assertEqual(db.execute('PRAGMA main.cache_size').fetchone()[0], -256 * 1024)

    def test_liveness_provenance_records_are_strictly_validated(self):
        root = {'relation': 'root', 'entity_kind': 'operation', 'entity_id': 31, 'generation': 0,
                'root_kind': 'observable_operation', 'operation_kind': 'kSystemTask',
                'root_identity': 31, 'root_identity_generation': 0, 'clock_operand': 2}
        edge = {'relation': 'edge', 'edge_kind': 'operation_operand', 'from_kind': 'operation',
                'from_id': 31, 'from_generation': 0, 'to_kind': 'value', 'to_id': 44,
                'to_generation': 0, 'slot': 2, 'operand_role': 'clock'}
        start = {'relation': 'start', 'node_id': 2, 'start_kind': 'boundary_use',
                 'entity_kind': 'operation', 'entity_id': 31, 'generation': 0,
                 'boundary': {'source': 2, 'target': 3, 'value': 44, 'value_generation': 0,
                              'user': 31, 'user_generation': 0, 'operand_index': 2, 'kind': 'clock'}}
        storage_root = {'relation': 'root', 'entity_kind': 'operation', 'entity_id': 32, 'generation': 0,
                        'root_kind': 'declared_storage', 'operation_kind': 'kRegisterWritePort',
                        'root_identity': 0, 'root_identity_generation': 0, 'storage_symbol': 'state'}
        self.set_liveness_provenance([root, edge, start, storage_root])
        self.assertEqual(verify_bundle(self.directory)['liveness_provenance_count'], 4)
        with sqlite3.connect(':memory:') as db:
            result = verify_bundle(self.directory)
            self.assertTrue(result['replay_exact'])

        for malformed in (
                {**start, 'boundary': {**start['boundary'], 'operand_index': True}},
                {**start, 'boundary': {**start['boundary'], 'user': 99}},
                {**root, 'entity_kind': 'value'},
                {**root, 'root_kind': 'declared_storage'},
                {**root, 'operation_kind': 'kAdd'},
                {**root, 'operation_kind': 'unknown_effect'},
                {**storage_root, 'entity_kind': 'value'},
                {**storage_root, 'operation_kind': 'kRegisterReadPort'},
                {**storage_root, 'operation_kind': 'kAssign'},
                {key: value for key, value in storage_root.items() if key != 'storage_symbol'},
                {key: value for key, value in storage_root.items() if key != 'root_identity'},
                {**root, 'operation_kind': 'kSystemTask', 'clock_operand': 2,
                 'root_identity': 32, 'root_identity_generation': 0},
                {**edge, 'slot': -1},
                {**root, 'root_kind': 'system_task'},
                {**edge, 'operand_role': 'clock', 'edge_kind': 'value_definition'},
                {**root, 'clock_operand': True},
                {**start, 'unexpected': 'field'}):
            with self.subTest(malformed=malformed):
                self.set_liveness_provenance([root, edge, malformed])
                with self.assertRaisesRegex(ValueError, 'DCE|liveness'):
                    verify_bundle(self.directory)

    def test_owned_operation_start_separates_membership_from_unique_ownership(self):
        start = {'relation': 'start', 'node_id': 2, 'start_kind': 'owned_operation',
                 'entity_kind': 'operation', 'entity_id': 31, 'generation': 0, 'owner_count': 2}
        for count in (1, 2, 2**32 - 1):
            self.set_liveness_provenance([{**start, 'owner_count': count}])
            self.assertTrue(verify_bundle(self.directory)['replay_exact'])
        for count in (0, -1, True, 2**32, None, '2'):
            with self.subTest(count=count):
                self.set_liveness_provenance([{**start, 'owner_count': count}])
                with self.assertRaisesRegex(ValueError, 'owned-operation owner count'):
                    verify_bundle(self.directory)
        self.set_liveness_provenance([{**start, 'start_kind': 'anchor', 'entity_kind': 'value'}])
        with self.assertRaisesRegex(ValueError, 'owned-operation owner count'):
            verify_bundle(self.directory)

    def test_zero_width_binding_record_requires_exact_binding_shape(self):
        valid = {'relation': 'start', 'node_id': 2, 'start_kind': 'zero_width_binding',
                 'binding': {'role': 'value', 'source_width': 1, 'shape': [0],
                             'shape_field_depths': [0], 'projection': [-1]}}
        self.set_liveness_provenance([valid])
        self.assertEqual(verify_bundle(self.directory)['liveness_provenance_count'], 1)
        invalid = {**valid, 'binding': {**valid['binding'], 'shape': [0.0]}}
        self.set_liveness_provenance([invalid])
        with self.assertRaisesRegex(ValueError, 'structural DCE binding'):
            verify_bundle(self.directory)

    def test_exact_input_port_start_is_structural_and_must_survive(self):
        start = {'relation': 'start', 'node_id': 1, 'start_kind': 'input_port',
                 'entity_kind': 'value', 'entity_id': 31, 'generation': 4,
                 'port_name': 'io__DOT__input', 'port_kind': 'input'}
        for kind in ('input', 'inout'):
            self.set_liveness_provenance([{**start, 'port_kind': kind}])
            self.assertTrue(verify_bundle(self.directory)['replay_exact'])
        for changes in ({'port_kind': 'output'}, {'port_name': ''}, {'port_name': None},
                        {'entity_kind': 'operation'}, {'node_id': 2},
                        {'start_kind': 'anchor'}, {'owner_count': 1}):
            with self.subTest(changes=changes):
                self.set_liveness_provenance([{**start, **changes}])
                with self.assertRaisesRegex(ValueError, 'DCE|liveness'):
                    verify_bundle(self.directory)

    def test_residual_groups_require_complete_original_memberships_and_decisions(self):
        group = {'relation': 'residual', 'entity_kind': 'operation', 'entity_id': 31, 'generation': 4,
                 'owner_ids': [1, 3], 'ordinary_retained_owner_count': 0,
                 'retention_rule': 'preserve_original_owner_set'}
        starts = [{'relation': 'start', 'node_id': owner, 'start_kind': 'owned_operation',
                   'entity_kind': 'operation', 'entity_id': 31, 'generation': 4, 'owner_count': 2}
                  for owner in (1, 3)]
        self.decisions = [{**self.decision(identifier=owner), 'reason': 'residual:uncovered_live_operation'}
                          for owner in (1, 3)]
        self.set_liveness_provenance([group, *starts])
        self.assertTrue(verify_bundle(self.directory)['replay_exact'])
        for records in ([group, starts[0]], [group, *starts, group],
                        [group, *starts, {**starts[0], 'node_id': 2, 'owner_count': 3}],
                        [group, *starts, starts[0]],
                        [{**group, 'owner_ids': [1]}, *starts],
                        [{**group, 'owner_ids': [1, 2]}, *starts],
                        [group, starts[0], {**starts[1], 'owner_count': 3}],
                        [group, starts[0], {**starts[1], 'generation': 5}],
                        [{**group, 'owner_ids': [1, 1]}, *starts],
                        [{**group, 'ordinary_retained_owner_count': True}, *starts],
                        [{**group, 'ordinary_retained_owner_count': 1}, *starts],
                        [{**group, 'retention_rule': 'select_one_owner'}, *starts]):
            with self.subTest(records=records):
                self.set_liveness_provenance(records)
                with self.assertRaisesRegex(ValueError, 'residual'):
                    verify_bundle(self.directory)
        for decisions in (self.decisions[:1],
                          [self.decisions[0], {**self.decisions[1], 'reason': 'demand:output'}],
                          [self.decisions[0], {**self.decisions[1], 'detail_json': {
                              **self.decisions[1]['detail_json'], 'outcome': 'replace'}}]):
            self.decisions = decisions
            self.set_liveness_provenance([group, *starts])
            with self.assertRaisesRegex(ValueError, 'residual'):
                verify_bundle(self.directory)

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

    def test_connection_evidence_covers_each_added_dependency(self):
        witnesses = [self.boundary_witness(3, 1, 4), self.boundary_witness(4, 1, 5),
                     self.boundary_witness(5, 4, 3)]
        self.write_with_connection_evidence(witnesses)
        evidence = verify_bundle(self.directory)['connection_evidence']
        self.assertEqual(evidence, {'requests': 3, 'connections': 3, 'records': 3,
                                    'missing_support_records': 0, 'exact_operand_mutation_matches': 0,
                                    'unmatched_witness_records': 3})

    def test_connection_evidence_links_exact_operand_mutation(self):
        witnesses = [self.boundary_witness(3, 1, 4), self.boundary_witness(4, 1, 5),
                     self.boundary_witness(5, 4, 3)]
        witnesses[0].update(mutation_id=1, mutation_match='exact_consumer_operand_value')
        self.write_with_connection_evidence(witnesses, [self.operand_mutation()])
        evidence = verify_bundle(self.directory)['connection_evidence']
        self.assertEqual(evidence['exact_operand_mutation_matches'], 1)
        self.assertEqual(evidence['unmatched_witness_records'], 2)

    def test_connection_evidence_rejects_mutation_link_with_wrong_use(self):
        witnesses = [self.boundary_witness(3, 1, 4), self.boundary_witness(4, 1, 5),
                     self.boundary_witness(5, 4, 3)]
        witnesses[0].update(mutation_id=1, mutation_match='exact_consumer_operand_value')
        for mutation in (self.operand_mutation(operation=22),
                         self.operand_mutation(slot=1),
                         self.operand_mutation(after_value=12)):
            with self.subTest(mutation=mutation):
                self.write_with_connection_evidence(witnesses, [mutation])
                with self.assertRaisesRegex(ValueError, 'does not support'):
                    verify_bundle(self.directory)

    def test_connection_evidence_requires_exact_added_dependency_id_set(self):
        state_update = edge(6, 1, 3, 'state_update')
        self.after_edges.append(state_update)
        witnesses = [self.boundary_witness(3, 1, 4), self.boundary_witness(5, 4, 3),
                     {'phase': 'postpass-native-walk', 'connection_id': 6,
                      'witness_kind': 'missing_native_boundary'}]
        self.write_with_connection_evidence(witnesses)
        with self.assertRaisesRegex(ValueError, 'evidence IDs differ'):
            verify_bundle(self.directory)

    def test_connection_evidence_rejects_wrong_unresolved_candidate_target_and_kind(self):
        unresolved = edge(6, None, 3)
        unresolved.update(resolution='unresolved', candidate_sources_json=[1], reason='ambiguous')
        self.after_edges.append(unresolved)
        witnesses = [self.boundary_witness(3, 1, 4), self.boundary_witness(4, 1, 5),
                     self.boundary_witness(5, 4, 3), self.boundary_witness(6, 2, 3)]
        self.write_with_connection_evidence(witnesses)
        with self.assertRaisesRegex(ValueError, 'does not support'):
            verify_bundle(self.directory)

        witnesses[-1] = self.boundary_witness(6, 1, 999)
        self.write_with_connection_evidence(witnesses)
        with self.assertRaisesRegex(ValueError, 'does not support'):
            verify_bundle(self.directory)

        witnesses[-1] = self.boundary_witness(6, 1, 3, boundary_kind='state-update')
        self.write_with_connection_evidence(witnesses)
        with self.assertRaisesRegex(ValueError, 'does not support'):
            verify_bundle(self.directory)

    def test_connection_evidence_rejects_unknown_fields_and_incomplete_fallback(self):
        witness = self.boundary_witness(3, 1, 4)
        witness['unexpected'] = 'ignored-before'
        self.write_with_connection_evidence([witness, self.boundary_witness(4, 1, 5),
                                             self.boundary_witness(5, 4, 3)])
        with self.assertRaisesRegex(ValueError, 'witness identity'):
            verify_bundle(self.directory)

        incomplete = {'phase': 'postpass-native-walk', 'connection_id': 3,
                      'witness_kind': 'fallback_value_owner', 'supporting_node_id': 1,
                      'value_id': 11, 'value_generation': 0, 'operation_id': 21,
                      'operation_generation': 0}
        self.write_with_connection_evidence([incomplete, self.boundary_witness(4, 1, 5),
                                             self.boundary_witness(5, 4, 3)])
        with self.assertRaisesRegex(ValueError, 'fallback witness is incomplete'):
            verify_bundle(self.directory)

    def test_static_snapshot_is_independent_of_trace(self):
        self.snapshot('', self.before_nodes, self.before_edges, 'snapshot')
        self.assertTrue(verify_snapshot(self.directory)['complete'])
        self.assertFalse((self.directory / 'evolution.tsv').exists())

    def set_pruned_operand_fixture(self, *, candidates=None):
        self.after_nodes = deepcopy(self.before_nodes)
        old = edge(10, 1 if candidates is None else None, 3)
        if candidates is not None:
            old.update(resolution='unresolved', candidate_sources_json=candidates, reason='ambiguous')
        self.before_edges, self.after_edges = [old], []
        evidence = [{'cause': 'pruned_operand_boundary', 'connection_id': 10, 'mutation_id': 1,
            'source_node_id': source, 'target_node_id': 3, 'value_id': 10, 'value_generation': 7,
            'operation_id': 21, 'operation_generation': 4, 'operand_index': 0, 'boundary_kind': 'data'}
            for source in ([1] if candidates is None else candidates)]
        self.events = [{'action': 'delete', 'reason': 'array_update_group_pruning',
                        'before_edges': [old], 'removal_evidence': evidence}]
        mutation = self.operand_mutation()
        mutation['detail'].update(owner_node_ids=[3], operation_generation=4, before_value_generation=7)
        return mutation, evidence

    def test_removed_dependency_requires_exact_old_boundary_and_destructive_mutation(self):
        for action in ('replace', 'delete'):
            for reason in ('array_update_group_pruning', 'undemanded_operand_defined_zero'):
                with self.subTest(action=action, reason=reason):
                    mutation, _ = self.set_pruned_operand_fixture()
                    mutation.update(action=action, reason=reason)
                    if action == 'delete':
                        for field in ('after_slot', 'after_value_id', 'after_value_generation'):
                            del mutation['detail'][field]
                    self.write(operand_mutations=[mutation])
                    result = verify_bundle(self.directory)
                    self.assertTrue(result['replay_exact'])
                    self.assertEqual(result['connection_removal_evidence_records'], 1)
                    self.assertEqual(result['connection_removal_evidence_connections'], 1)

    def test_removed_unresolved_dependency_covers_all_original_candidates(self):
        mutation, evidence = self.set_pruned_operand_fixture(candidates=[1, 2])
        self.write(operand_mutations=[mutation])
        result = verify_bundle(self.directory)
        self.assertTrue(result['replay_exact'])
        self.assertEqual(result['connection_removal_evidence_records'], 2)
        self.assertEqual(result['connection_removal_evidence_connections'], 1)
        evidence.pop()
        self.write(operand_mutations=[mutation])
        with self.assertRaisesRegex(ValueError, 'every original candidate'):
            verify_bundle(self.directory)

    def test_removed_dependency_allows_unchanged_endpoint_implementation_touch(self):
        mutation, _ = self.set_pruned_operand_fixture()
        self.events[0].update(action='replace', before_nodes=[self.before_nodes[2]],
                              after_nodes=[self.before_nodes[2]])
        self.write(operand_mutations=[mutation])
        self.assertTrue(verify_bundle(self.directory)['replay_exact'])

    def test_removed_dependency_accepts_supported_boundary_kinds(self):
        for kind in ('data', 'clock', 'reset', 'predicate'):
            with self.subTest(kind=kind):
                mutation, evidence = self.set_pruned_operand_fixture()
                evidence[0]['boundary_kind'] = kind
                self.write(operand_mutations=[mutation])
                self.assertTrue(verify_bundle(self.directory)['replay_exact'])

    def test_removed_dependency_rejects_inexact_boundary_identity_and_unsupported_fields(self):
        changes = {'connection_id': 11, 'mutation_id': 2, 'source_node_id': 2, 'target_node_id': 2,
            'value_id': 12, 'value_generation': 8, 'operation_id': 22, 'operation_generation': 5,
            'operand_index': 1, 'boundary_kind': 'state-update', 'cause': 'target_operation_changed',
            'event_sequence': 1}
        for field, value in changes.items():
            with self.subTest(field=field):
                mutation, evidence = self.set_pruned_operand_fixture()
                evidence[0][field] = value
                self.write(operand_mutations=[mutation])
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)

    def test_removed_dependency_rejects_unrelated_or_slot_only_mutations(self):
        for scenario in ('missing', 'owner', 'reason', 'slot_only', 'addition'):
            with self.subTest(scenario=scenario):
                mutation, _ = self.set_pruned_operand_fixture()
                if scenario == 'owner':
                    mutation['detail']['owner_node_ids'] = [2]
                elif scenario == 'reason':
                    mutation['reason'] = 'operand_ordering'
                elif scenario == 'slot_only':
                    mutation['detail'].update(after_slot=1, after_value_id=10, after_value_generation=7)
                elif scenario == 'addition':
                    mutation['action'] = 'add'
                    for field in ('before_slot', 'before_value_id', 'before_value_generation'):
                        del mutation['detail'][field]
                self.write(operand_mutations=[] if scenario == 'missing' else [mutation])
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)

    def test_removed_dependency_rejects_stale_unchanged_and_non_dependency_connections(self):
        for scenario in ('stale_id', 'unchanged', 'non_dependency', 'same_dependency_new_id'):
            with self.subTest(scenario=scenario):
                mutation, _ = self.set_pruned_operand_fixture()
                if scenario == 'stale_id':
                    self.events[0]['before_edges'] = []
                    self.after_edges = deepcopy(self.before_edges)
                elif scenario == 'unchanged':
                    self.after_edges = deepcopy(self.before_edges)
                    self.events[0].update(action='replace', after_edges=self.after_edges)
                elif scenario == 'non_dependency':
                    self.before_edges[0]['kind'] = 'state_update'
                else:
                    self.after_edges = [{**self.before_edges[0], 'connection_id': 11}]
                    self.events[0].update(action='replace', after_edges=self.after_edges)
                self.write(operand_mutations=[mutation])
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)

    def test_removed_dependency_rejects_later_reintroduction_of_same_public_key(self):
        mutation, _ = self.set_pruned_operand_fixture()
        self.after_edges = [{**self.before_edges[0], 'connection_id': 11}]
        self.events.append({'action': 'add', 'reason': 'later_reintroduction', 'after_edges': self.after_edges})
        self.write(operand_mutations=[mutation])
        with self.assertRaisesRegex(ValueError, 'final|reintroduc'):
            verify_bundle(self.directory)

    def test_removed_dependency_evidence_must_match_original_snapshot_edge(self):
        mutation, evidence = self.set_pruned_operand_fixture()
        intermediate = {**self.before_edges[0], 'connection_id': 11, 'source_node_id': 2}
        evidence[0].update(connection_id=11, source_node_id=2)
        self.events = [
            {'action': 'replace', 'reason': 'earlier_rewire', 'before_edges': self.before_edges,
             'after_edges': [intermediate]},
            {'action': 'delete', 'reason': 'array_update_group_pruning', 'before_edges': [intermediate],
             'removal_evidence': evidence}]
        self.write(operand_mutations=[mutation])
        with self.assertRaisesRegex(ValueError, 'same-event old edge retirement'):
            verify_bundle(self.directory)

    def test_removed_dependency_rejects_retired_or_changed_endpoint_identities(self):
        for identifier in (1, 3):
            for scenario in ('retired', 'changed'):
                with self.subTest(identifier=identifier, scenario=scenario):
                    mutation, _ = self.set_pruned_operand_fixture()
                    original = next(item for item in self.before_nodes if item['node_id'] == identifier)
                    self.events[0]['before_nodes'] = [original]
                    self.after_nodes = [item for item in self.after_nodes if item['node_id'] != identifier]
                    if scenario == 'changed':
                        replacement = node(identifier, 'changed')
                        self.after_nodes.append(replacement)
                        self.events[0].update(action='replace', after_nodes=[replacement])
                    self.write(operand_mutations=[mutation])
                    with self.assertRaises(ValueError):
                        verify_bundle(self.directory)

    def test_removed_dependency_rejects_wrong_event_side_and_trace_declarations(self):
        for scenario in ('side', 'event', 'header_missing', 'header_version', 'records', 'connections'):
            with self.subTest(scenario=scenario):
                mutation, evidence = self.set_pruned_operand_fixture()
                if scenario == 'event':
                    self.events[0]['removal_evidence'] = []
                    self.events.append({'action': 'replace', 'reason': 'touch',
                        'before_nodes': [self.before_nodes[2]], 'after_nodes': [self.before_nodes[2]],
                        'removal_evidence': evidence})
                self.write(operand_mutations=[mutation])
                if scenario == 'side':
                    next(row for row in self.rows if row['record'] == 'evidence')['side'] = 'after'
                elif scenario == 'header_missing':
                    del self.rows[0]['detail_json']['connection_removal_trace']
                elif scenario == 'header_version':
                    self.rows[0]['detail_json']['connection_removal_trace'] = 'pruned-operand-boundary.v0'
                elif scenario in ('records', 'connections'):
                    field = 'connectionRemovalEvidence' + ('RecordCount' if scenario == 'records' else 'ConnectionCount')
                    self.rows[-1]['detail_json'][field] = 2
                self.write_rows()
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)

    def set_pruned_operand_support_fixture(self, support='exact', *, candidates=None):
        mutation, evidence = self.set_pruned_operand_fixture(candidates=candidates)
        for item in evidence:
            item.update(support_kind='boundary_use', reference_target_node_id=item['target_node_id'],
                reference_operation_id=item['operation_id'],
                reference_operation_generation=item['operation_generation'],
                reference_operand_index=item['operand_index'],
                value_definition_operation_id=31, value_definition_operation_generation=9)
            if support == 'wildcard':
                item['reference_operand_index'] = None
            elif support == 'named':
                item.update(reference_operation_id=0, reference_operation_generation=0, reference_operand_index=None)
            elif support == 'selected_read':
                item.update(reference_operation_id=31, reference_operation_generation=9, reference_operand_index=None)
            elif support.startswith('fallback'):
                item.update(support_kind='fallback_value_owner', boundary_kind=None, reference_target_node_id=0,
                    reference_operation_id=0, reference_operation_generation=0, reference_operand_index=None)
                if support == 'fallback_input':
                    item.update(value_definition_operation_id=0, value_definition_operation_generation=0)
        return mutation, evidence

    def test_pruned_operand_support_replays_exact_wildcard_named_selected_and_fallback(self):
        for support in ('exact', 'wildcard', 'named', 'selected_read', 'fallback_input', 'fallback_defined'):
            with self.subTest(support=support):
                mutation, evidence = self.set_pruned_operand_support_fixture(support)
                self.write(operand_mutations=[mutation])
                database = self.directory / (support + '.sqlite')
                result = verify_bundle(self.directory, database)
                self.assertTrue(result['replay_exact'])
                self.assertEqual(result['connection_removal_evidence_records'], 1)
                self.assertEqual(result['connection_removal_evidence_connections'], 1)
                self.assertEqual(result['header']['connection_removal_trace'], 'pruned-operand-support.v1')
                with sqlite3.connect(database) as db:
                    rows = db.execute('SELECT detail_json FROM connection_removal_evidence').fetchall()
                    self.assertEqual([json.loads(row[0]) for row in rows], evidence)

    def test_pruned_operand_support_can_mix_candidate_supports_but_must_cover_every_source(self):
        mutation, evidence = self.set_pruned_operand_support_fixture('named', candidates=[1, 2])
        evidence[1].update(support_kind='fallback_value_owner', boundary_kind=None, reference_target_node_id=0)
        self.write(operand_mutations=[mutation])
        self.assertEqual(verify_bundle(self.directory)['connection_removal_evidence_records'], 2)
        evidence.pop()
        self.write(operand_mutations=[mutation])
        with self.assertRaisesRegex(ValueError, 'every original candidate'):
            verify_bundle(self.directory)

    def test_pruned_operand_support_rejects_inconsistent_boundary_reference_contexts(self):
        changes = (
            ('exact', 'reference_target_node_id', 2),
            ('exact', 'reference_operation_id', 22),
            ('exact', 'reference_operation_generation', 5),
            ('exact', 'reference_operand_index', 1),
            ('exact', 'boundary_kind', None),
            ('wildcard', 'reference_operation_generation', 5),
            ('wildcard', 'reference_operand_index', 1),
            ('named', 'reference_operation_generation', 1),
            ('named', 'reference_operand_index', 0),
            ('named', 'reference_operation_id', 22),
            ('named', 'reference_target_node_id', 0),
            ('selected_read', 'reference_operation_id', 32),
            ('selected_read', 'reference_operation_generation', 10),
            ('selected_read', 'reference_operand_index', 0),
            ('selected_read', 'value_definition_operation_id', 32),
            ('selected_read', 'value_definition_operation_generation', 10),
        )
        for support, field, value in changes:
            with self.subTest(support=support, field=field):
                mutation, evidence = self.set_pruned_operand_support_fixture(support)
                evidence[0][field] = value
                self.write(operand_mutations=[mutation])
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)

    def test_pruned_operand_support_rejects_fabricated_fallback_reference_contexts(self):
        changes = (('reference_target_node_id', 3), ('reference_operation_id', 21),
            ('reference_operation_generation', 4), ('reference_operand_index', 0),
            ('boundary_kind', 'data'), ('boundary_kind', 'null'),
            ('value_definition_operation_generation', 9), ('support_kind', 'missing_native_boundary'))
        for field, value in changes:
            with self.subTest(field=field):
                mutation, evidence = self.set_pruned_operand_support_fixture('fallback_input')
                evidence[0][field] = value
                self.write(operand_mutations=[mutation])
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)

    def test_pruned_operand_support_rejects_invalid_labels_and_scalar_types(self):
        changes = [('support_kind', value) for value in ('', None, 'fallback', True)]
        changes.extend(('boundary_kind', value) for value in ('dependency', 'null', True))
        numeric = ('reference_target_node_id', 'reference_operation_id', 'reference_operation_generation',
            'reference_operand_index', 'value_definition_operation_id', 'value_definition_operation_generation')
        changes.extend((field, value) for field in numeric for value in (True, '0', -1, 2**32))
        changes.append(('reference_operand_index', 2**32 - 1))
        for field, value in changes:
            with self.subTest(field=field, value=value):
                mutation, evidence = self.set_pruned_operand_support_fixture()
                evidence[0][field] = value
                self.write(operand_mutations=[mutation])
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)

    def test_duplicate_pruned_operand_support_does_not_cover_a_missing_candidate(self):
        mutation, evidence = self.set_pruned_operand_support_fixture('named', candidates=[1, 2])
        evidence[1] = deepcopy(evidence[0])
        self.write(operand_mutations=[mutation])
        with self.assertRaises(ValueError):
            verify_bundle(self.directory)

    def test_pruned_operand_support_requires_complete_versioned_fields(self):
        fields = ('support_kind', 'reference_target_node_id', 'reference_operation_id',
            'reference_operation_generation', 'reference_operand_index',
            'value_definition_operation_id', 'value_definition_operation_generation')
        for field in fields:
            with self.subTest(missing=field):
                mutation, evidence = self.set_pruned_operand_support_fixture('named')
                del evidence[0][field]
                self.write(operand_mutations=[mutation])
                self.rows[0]['detail_json']['connection_removal_trace'] = 'pruned-operand-support.v1'
                self.write_rows()
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)
        for new_fields in (False, True):
            with self.subTest(new_fields=new_fields):
                mutation, _ = (self.set_pruned_operand_support_fixture() if new_fields
                               else self.set_pruned_operand_fixture())
                self.write(operand_mutations=[mutation])
                self.rows[0]['detail_json']['connection_removal_trace'] = (
                    'pruned-operand-boundary.v1' if new_fields else 'pruned-operand-support.v1')
                self.write_rows()
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)

    def test_pruned_operand_support_preserves_exact_actual_mutation_requirement(self):
        changes = {'mutation_id': 2, 'operation_id': 22, 'operation_generation': 5,
            'operand_index': 1, 'value_id': 12, 'value_generation': 8}
        for support in ('named', 'selected_read', 'fallback_input'):
            for field, value in changes.items():
                with self.subTest(support=support, field=field):
                    mutation, evidence = self.set_pruned_operand_support_fixture(support)
                    evidence[0][field] = value
                    self.write(operand_mutations=[mutation])
                    with self.assertRaises(ValueError):
                        verify_bundle(self.directory)

    def test_pruned_operand_support_cannot_replace_destructive_mutation_or_owner_evidence(self):
        for scenario in ('missing', 'owner', 'reason', 'slot_only'):
            with self.subTest(scenario=scenario):
                mutation, _ = self.set_pruned_operand_support_fixture('fallback_input')
                if scenario == 'owner':
                    mutation['detail']['owner_node_ids'] = [2]
                elif scenario == 'reason':
                    mutation['reason'] = 'operand_ordering'
                elif scenario == 'slot_only':
                    mutation['detail'].update(after_slot=1, after_value_id=10, after_value_generation=7)
                self.write(operand_mutations=[] if scenario == 'missing' else [mutation])
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)

    def set_pruned_operand_path_fixture(self, support='exact', *, hops=2, candidates=None):
        mutation, evidence = self.set_pruned_operand_support_fixture(support, candidates=candidates)
        steps = []
        value, generation = 10, 7
        operation, operation_generation, operand = 21, 4, 0
        for index in range(hops):
            operation, operation_generation, operand = 31 + 10 * index, 9 + index, 2 + index
            next_value, next_generation = 40 + 10 * index, 8 + index
            steps.append({'value_id': value, 'value_generation': generation,
                'definition_operation_id': operation, 'definition_operation_generation': operation_generation,
                'operand_index': operand, 'operand_value_id': next_value,
                'operand_value_generation': next_generation})
            value, generation = next_value, next_generation
        for item in evidence:
            item.update(path=deepcopy(steps), reference_operation_id=operation,
                reference_operation_generation=operation_generation, reference_operand_index=operand,
                value_definition_operation_id=91, value_definition_operation_generation=6)
            if support == 'wildcard':
                item['reference_operand_index'] = None
            elif support == 'named':
                item.update(reference_operation_id=0, reference_operation_generation=0, reference_operand_index=None)
            elif support == 'selected_read':
                item.update(reference_operation_id=91, reference_operation_generation=6, reference_operand_index=None)
            elif support.startswith('fallback'):
                item.update(reference_operation_id=0, reference_operation_generation=0, reference_operand_index=None)
                if support == 'fallback_input':
                    item.update(value_definition_operation_id=0, value_definition_operation_generation=0)
        return mutation, evidence

    def test_pruned_operand_paths_replay_direct_and_transitive_terminal_support(self):
        for hops in (0, 1, 2):
            for support in ('exact', 'wildcard', 'named', 'selected_read', 'fallback_input', 'fallback_defined'):
                with self.subTest(hops=hops, support=support):
                    mutation, evidence = self.set_pruned_operand_path_fixture(support, hops=hops)
                    self.write(operand_mutations=[mutation])
                    database = self.directory / f'path-{hops}-{support}.sqlite'
                    result = verify_bundle(self.directory, database)
                    self.assertTrue(result['replay_exact'])
                    self.assertEqual(result['connection_removal_evidence_records'], 1)
                    self.assertEqual(result['connection_removal_evidence_connections'], 1)
                    self.assertEqual(result['header']['connection_removal_trace'], 'pruned-operand-support.v2')
                    with sqlite3.connect(database) as db:
                        stored = db.execute('SELECT detail_json FROM connection_removal_evidence').fetchall()
                        self.assertEqual([json.loads(row[0]) for row in stored], evidence)
                    self.assertEqual((evidence[0]['operation_id'], evidence[0]['operation_generation'],
                        evidence[0]['operand_index'], evidence[0]['value_id'], evidence[0]['value_generation']),
                        (21, 4, 0, 10, 7))

    def test_pruned_operand_paths_require_complete_versioned_path_fields(self):
        for scenario in ('missing_path', 'v1_with_path', 'legacy_with_path', 'unknown_record_field',
                         'missing_step_field', 'unknown_step_field'):
            with self.subTest(scenario=scenario):
                mutation, evidence = self.set_pruned_operand_path_fixture()
                if scenario == 'missing_path':
                    del evidence[0]['path']
                elif scenario == 'unknown_record_field':
                    evidence[0]['unchecked'] = True
                elif scenario == 'missing_step_field':
                    del evidence[0]['path'][0]['definition_operation_generation']
                elif scenario == 'unknown_step_field':
                    evidence[0]['path'][0]['unchecked'] = True
                self.write(operand_mutations=[mutation])
                self.rows[0]['detail_json']['connection_removal_trace'] = (
                    'pruned-operand-support.v1' if scenario == 'v1_with_path' else
                    'pruned-operand-boundary.v1' if scenario == 'legacy_with_path' else
                    'pruned-operand-support.v2')
                self.write_rows()
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)

    def test_pruned_operand_paths_reject_invalid_container_and_scalar_types(self):
        for value in (None, {}, '', True, [None], [0]):
            with self.subTest(path=value):
                mutation, evidence = self.set_pruned_operand_path_fixture()
                evidence[0]['path'] = value
                self.write(operand_mutations=[mutation])
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)
        fields = ('value_id', 'value_generation', 'definition_operation_id',
            'definition_operation_generation', 'operand_index', 'operand_value_id', 'operand_value_generation')
        changes = [(field, value) for field in fields for value in (True, '0', -1, 2**32)]
        changes.extend((field, 0) for field in ('value_id', 'definition_operation_id', 'operand_value_id'))
        changes.append(('operand_index', 2**32 - 1))
        for field, value in changes:
            with self.subTest(field=field, value=value):
                mutation, evidence = self.set_pruned_operand_path_fixture()
                evidence[0]['path'][0][field] = value
                self.write(operand_mutations=[mutation])
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)

    def test_pruned_operand_paths_reject_disconnected_reordered_and_cyclic_chains(self):
        cases = (
            ('wrong_start_value', lambda path: path[0].update(value_id=12)),
            ('wrong_start_generation', lambda path: path[0].update(value_generation=8)),
            ('disconnected_value', lambda path: path[1].update(value_id=41)),
            ('disconnected_generation', lambda path: path[1].update(value_generation=9)),
            ('missing_first_hop', lambda path: path.pop(0)),
            ('reordered_hops', lambda path: path.reverse()),
            ('cycle_to_start', lambda path: path[-1].update(operand_value_id=10, operand_value_generation=7)),
            ('cycle_to_intermediate', lambda path: path[-1].update(operand_value_id=40, operand_value_generation=8)),
        )
        for scenario, mutate in cases:
            with self.subTest(scenario=scenario):
                mutation, evidence = self.set_pruned_operand_path_fixture()
                mutate(evidence[0]['path'])
                self.write(operand_mutations=[mutation])
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)

    def test_pruned_operand_paths_require_terminal_reference_context(self):
        cases = (
            ('exact', {'reference_operation_id': 21, 'reference_operation_generation': 4,
                       'reference_operand_index': 0}),
            ('exact', {'reference_operation_id': 31, 'reference_operation_generation': 9,
                       'reference_operand_index': 2}),
            ('exact', {'reference_operation_generation': 11}),
            ('exact', {'reference_operand_index': 2}),
            ('wildcard', {'reference_operation_id': 21, 'reference_operation_generation': 4}),
            ('selected_read', {'reference_operation_id': 31, 'reference_operation_generation': 9}),
            ('selected_read', {'value_definition_operation_id': 31, 'value_definition_operation_generation': 9}),
            ('fallback_input', {'reference_operation_id': 41, 'reference_operation_generation': 10}),
        )
        for support, changes in cases:
            with self.subTest(support=support, changes=changes):
                mutation, evidence = self.set_pruned_operand_path_fixture(support)
                evidence[0].update(changes)
                self.write(operand_mutations=[mutation])
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)

    def test_pruned_operand_paths_preserve_exact_destructive_mutation_start(self):
        changes = {'mutation_id': 2, 'operation_id': 22, 'operation_generation': 5,
                   'operand_index': 1, 'value_id': 12, 'value_generation': 8}
        for field, value in changes.items():
            with self.subTest(field=field):
                mutation, evidence = self.set_pruned_operand_path_fixture('named')
                evidence[0][field] = value
                if field in ('value_id', 'value_generation'):
                    evidence[0]['path'][0][field] = value
                self.write(operand_mutations=[mutation])
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)
        for scenario in ('missing', 'owner', 'reason', 'slot_only'):
            with self.subTest(scenario=scenario):
                mutation, _ = self.set_pruned_operand_path_fixture('fallback_input')
                if scenario == 'owner':
                    mutation['detail']['owner_node_ids'] = [2]
                elif scenario == 'reason':
                    mutation['reason'] = 'operand_ordering'
                elif scenario == 'slot_only':
                    mutation['detail'].update(after_slot=1, after_value_id=10, after_value_generation=7)
                self.write(operand_mutations=[] if scenario == 'missing' else [mutation])
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)

    def test_pruned_operand_paths_cover_each_candidate_with_its_own_complete_support(self):
        mutation, evidence = self.set_pruned_operand_path_fixture('exact', candidates=[1, 2])
        evidence[1].update(path=[{'value_id': 10, 'value_generation': 7,
            'definition_operation_id': 61, 'definition_operation_generation': 3, 'operand_index': 1,
            'operand_value_id': 70, 'operand_value_generation': 2}], support_kind='fallback_value_owner',
            boundary_kind=None, reference_target_node_id=0, reference_operation_id=0,
            reference_operation_generation=0, reference_operand_index=None,
            value_definition_operation_id=0, value_definition_operation_generation=0)
        self.write(operand_mutations=[mutation])
        result = verify_bundle(self.directory)
        self.assertTrue(result['replay_exact'])
        self.assertEqual(result['connection_removal_evidence_records'], 2)
        self.assertEqual(result['connection_removal_evidence_connections'], 1)
        for scenario in ('missing', 'duplicate', 'spliced_terminal'):
            with self.subTest(scenario=scenario):
                mutation, evidence = self.set_pruned_operand_path_fixture('exact', candidates=[1, 2])
                if scenario == 'missing':
                    evidence.pop()
                elif scenario == 'duplicate':
                    evidence[1] = deepcopy(evidence[0])
                else:
                    evidence[1]['path'] = evidence[1]['path'][:1]
                self.write(operand_mutations=[mutation])
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)

    def set_dead_anchor_fixture(self, support='exact', *, hops=2, candidates=None):
        _, evidence = self.set_pruned_operand_path_fixture(support, hops=hops, candidates=candidates)
        for item in evidence:
            for field in ('mutation_id', 'value_id', 'value_generation', 'operation_id',
                          'operation_generation', 'operand_index'):
                del item[field]
            item.update(cause='dead_anchor_cone', anchor_removal_id=1)
        removal = {'target_node_id': 3, 'detail': {'anchor_removal_id': 1, 'pass': 'split-static-array',
            'operation_id': 31, 'operation_generation': 9, 'value_id': 10, 'value_generation': 7}}
        return removal, evidence

    def set_operation_path_fixture(self, *, candidates=None, path_kind='intermediate'):
        old = edge(10, 1 if candidates is None else None, 3)
        if candidates is not None:
            old.update(resolution='unresolved', candidate_sources_json=candidates, reason='ambiguous')
        if path_kind == 'direct_root':
            root_value, root_generation = 70, 2
            root_user, root_user_generation, root_operand = 62, 4, 1
            path = []
            removed_operation, removed_generation = 62, 4
            terminal_operation, terminal_generation, terminal_operand = 62, 4, 1
        else:
            root_value, root_generation = 10, 7
            root_user, root_user_generation, root_operand = 0, 0, None
            path = [
                {'value_id': 10, 'value_generation': 7, 'definition_operation_id': 61,
                 'definition_operation_generation': 3, 'operand_index': 0,
                 'operand_value_id': 11, 'operand_value_generation': 1},
                {'value_id': 11, 'value_generation': 1, 'definition_operation_id': 62,
                 'definition_operation_generation': 4, 'operand_index': 1,
                 'operand_value_id': 70, 'operand_value_generation': 2},
            ]
            removed_operation, removed_generation = 61, 3
            terminal_operation, terminal_generation, terminal_operand = 62, 4, 1
        sources = [1] if candidates is None else candidates
        evidence = [{'cause': 'removed_operation_path', 'connection_id': 10,
            'removed_operation_id': removed_operation, 'removed_operation_generation': removed_generation,
            'source_node_id': source, 'target_node_id': 3, 'value_id': 70, 'value_generation': 2,
            'operation_id': terminal_operation, 'operation_generation': terminal_generation,
            'operand_index': terminal_operand, 'support_kind': 'fallback_value_owner',
            'boundary_kind': None, 'reference_target_node_id': 0, 'reference_operation_id': 0,
            'reference_operation_generation': 0, 'reference_operand_index': None,
            'value_definition_operation_id': 0, 'value_definition_operation_generation': 0,
            'root_value_id': root_value, 'root_value_generation': root_generation,
            'root_user_operation_id': root_user,
            'root_user_operation_generation': root_user_generation,
            'root_operand_index': root_operand, 'path': deepcopy(path)} for source in sources]
        self.before_edges, self.after_edges = [old], []
        self.events = [{'action': 'delete', 'reason': 'dead-code-elim',
                        'before_edges': [old], 'removal_evidence': evidence}]
        return evidence

    def test_removed_operation_path_covers_direct_and_intermediate_witnesses(self):
        for path_kind in ('direct_root', 'intermediate'):
            with self.subTest(path_kind=path_kind):
                self.after_nodes = deepcopy(self.before_nodes)
                evidence = self.set_operation_path_fixture(path_kind=path_kind, candidates=[1, 2])
                self.write()
                result = verify_bundle(self.directory)
                self.assertTrue(result['replay_exact'])
                self.assertEqual(result['connection_removal_evidence_records'], 2)
                self.assertEqual(result['connection_removal_evidence_connections'], 1)
                self.assertEqual(result['connection_operation_removal_evidence_records'], 2)
                self.assertEqual(result['connection_operation_removal_evidence_connections'], 1)
                self.assertEqual(result['header']['connection_operation_removal_trace'],
                                 'removed-operation-path.v1')
                for scenario in ('outside_path', 'wrong_generation', 'disconnected', 'missing_candidate'):
                    with self.subTest(scenario=scenario):
                        evidence = self.set_operation_path_fixture(path_kind=path_kind, candidates=[1, 2])
                        if scenario == 'outside_path':
                            evidence[0]['removed_operation_id'] = 99
                        elif scenario == 'wrong_generation':
                            evidence[0]['removed_operation_generation'] += 1
                        elif scenario == 'disconnected':
                            if evidence[0]['path']:
                                evidence[0]['path'][0]['operand_value_id'] = 99
                            else:
                                evidence[0]['root_value_id'] = 99
                        else:
                            evidence.pop()
                        self.write()
                        with self.assertRaises(ValueError):
                            verify_bundle(self.directory)

    def test_dead_anchor_cone_replays_nonempty_paths_and_terminal_support(self):
        for hops in (1, 2):
            for support in ('exact', 'wildcard', 'named', 'selected_read', 'fallback_input', 'fallback_defined'):
                with self.subTest(hops=hops, support=support):
                    removal, evidence = self.set_dead_anchor_fixture(support, hops=hops)
                    self.write(anchor_removals=[removal])
                    database = self.directory / f'anchor-{hops}-{support}.sqlite'
                    result = verify_bundle(self.directory, database)
                    self.assertTrue(result['replay_exact'])
                    self.assertEqual(result['connection_removal_evidence_records'], 1)
                    self.assertEqual(result['connection_removal_evidence_connections'], 1)
                    self.assertEqual(result['header']['connection_anchor_removal_trace'], 'dead-anchor-cone.v1')
                    self.assertEqual(result['anchor_removal_count'], 1)
                    self.assertEqual(result['connection_anchor_removal_evidence_records'], 1)
                    self.assertEqual(result['connection_anchor_removal_evidence_connections'], 1)
                    self.assertNotIn('connection_removal_trace', result['header'])
                    self.assertNotIn('mutation_trace', result['header'])
                    with sqlite3.connect(database) as db:
                        stored = db.execute('SELECT detail_json FROM connection_removal_evidence').fetchall()
                        self.assertEqual([json.loads(row[0]) for row in stored], evidence)

    def test_dead_anchor_cone_covers_every_candidate_with_its_own_terminal_support(self):
        removal, evidence = self.set_dead_anchor_fixture(candidates=[1, 2])
        evidence[1].update(path=evidence[1]['path'][:1], support_kind='fallback_value_owner',
            boundary_kind=None, reference_target_node_id=0, reference_operation_id=0,
            reference_operation_generation=0, reference_operand_index=None,
            value_definition_operation_id=0, value_definition_operation_generation=0)
        self.write(anchor_removals=[removal])
        self.assertEqual(verify_bundle(self.directory)['connection_removal_evidence_records'], 2)
        for scenario in ('missing', 'duplicate', 'spliced_terminal'):
            with self.subTest(scenario=scenario):
                removal, evidence = self.set_dead_anchor_fixture(candidates=[1, 2])
                if scenario == 'missing':
                    evidence.pop()
                elif scenario == 'duplicate':
                    evidence[1] = deepcopy(evidence[0])
                else:
                    evidence[1]['path'] = evidence[1]['path'][:1]
                self.write(anchor_removals=[removal])
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)

    def test_dead_anchor_and_operand_removal_use_separate_fact_namespaces_and_total_counters(self):
        operand, operand_evidence = self.set_pruned_operand_path_fixture('named')
        operand_evidence = deepcopy(operand_evidence)
        removal, anchor_evidence = self.set_dead_anchor_fixture('selected_read')
        old = deepcopy(self.before_edges[0])
        old['connection_id'] = 11
        old['source_node_id'] = 2
        self.before_edges.append(old)
        self.events[0]['before_edges'].append(old)
        for item in anchor_evidence:
            item['connection_id'] = 11
            item['source_node_id'] = 2
        self.events[0]['removal_evidence'] = operand_evidence + anchor_evidence
        self.write(operand_mutations=[operand], anchor_removals=[removal])
        result = verify_bundle(self.directory)
        self.assertTrue(result['replay_exact'])
        self.assertEqual(result['connection_removal_evidence_records'], 2)
        self.assertEqual(result['connection_removal_evidence_connections'], 2)
        self.assertEqual(result['anchor_removal_count'], 1)
        self.assertEqual(result['connection_anchor_removal_evidence_records'], 1)
        self.assertEqual(result['connection_anchor_removal_evidence_connections'], 1)
        footer = self.rows[-1]['detail_json']
        self.assertEqual(footer['anchorRemovalRecordCount'], 1)
        self.assertEqual(footer['connectionAnchorRemovalEvidenceRecordCount'], 1)
        self.assertEqual(footer['connectionAnchorRemovalEvidenceConnectionCount'], 1)

    def test_dead_anchor_fact_requires_exact_fields_types_and_pass(self):
        fields = ('anchor_removal_id', 'pass', 'operation_id', 'operation_generation', 'value_id', 'value_generation')
        cases = [('missing_' + field, field, None) for field in fields]
        cases += [('unknown', 'unchecked', True), ('wrong_pass', 'pass', 'dead-code-elim')]
        cases += [(field + str(value), field, value) for field in fields if field != 'pass'
                  for value in (True, '1', -1, 2**32)]
        cases += [(field + '_zero', field, 0) for field in ('anchor_removal_id', 'operation_id', 'value_id')]
        for scenario, field, value in cases:
            with self.subTest(scenario=scenario):
                removal, _ = self.set_dead_anchor_fixture()
                if scenario.startswith('missing_'):
                    del removal['detail'][field]
                else:
                    removal['detail'][field] = value
                self.write(anchor_removals=[removal])
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)

    def test_dead_anchor_fact_requires_seq_zero_delete_before_anchor_row(self):
        changes = {'record': 'decision', 'seq': 1, 'action': 'replace', 'reason': 'dead_anchor',
                   'subject': 'operand', 'side': 'transition', 'object_id': 1}
        for field, value in changes.items():
            with self.subTest(field=field):
                removal, _ = self.set_dead_anchor_fixture()
                self.write(anchor_removals=[removal])
                fact = next(row for row in self.rows if row['record'] == 'mutation')
                fact[field] = value
                self.write_rows()
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)

    def test_dead_anchor_cone_requires_its_fact_target_and_exact_root_definition(self):
        cases = (
            ('missing_fact', lambda fact, item: None),
            ('unknown_fact', lambda fact, item: item.update(anchor_removal_id=2)),
            ('wrong_fact_target', lambda fact, item: fact.update(target_node_id=1)),
            ('wrong_evidence_target', lambda fact, item: item.update(target_node_id=1)),
            ('wrong_root_value', lambda fact, item: item['path'][0].update(value_id=11)),
            ('wrong_root_value_generation', lambda fact, item: item['path'][0].update(value_generation=8)),
            ('wrong_root_definition', lambda fact, item: item['path'][0].update(definition_operation_id=32)),
            ('wrong_root_definition_generation', lambda fact, item: item['path'][0].update(definition_operation_generation=10)),
            ('empty_path', lambda fact, item: item.update(path=[])),
        )
        for scenario, mutate in cases:
            with self.subTest(scenario=scenario):
                removal, evidence = self.set_dead_anchor_fixture()
                mutate(removal, evidence[0])
                self.write(anchor_removals=[] if scenario == 'missing_fact' else [removal])
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)

    def test_dead_anchor_cone_rejects_disconnected_cyclic_or_inexact_terminal_paths(self):
        cases = (
            ('disconnected_value', lambda item: item['path'][1].update(value_id=99)),
            ('disconnected_generation', lambda item: item['path'][1].update(value_generation=9)),
            ('cyclic', lambda item: item['path'][1].update(operand_value_id=10, operand_value_generation=7)),
            ('terminal_operation', lambda item: item.update(reference_operation_id=31, reference_operation_generation=9,
                                                          reference_operand_index=2)),
            ('terminal_generation', lambda item: item.update(reference_operation_generation=11)),
            ('terminal_slot', lambda item: item.update(reference_operand_index=2)),
            ('unknown_field', lambda item: item.update(unchecked=True)),
            ('bad_path_type', lambda item: item.update(path={})),
            ('bad_step_type', lambda item: item['path'][0].update(operand_index=True)),
            ('unknown_step_field', lambda item: item['path'][0].update(unchecked=True)),
        )
        for scenario, mutate in cases:
            with self.subTest(scenario=scenario):
                removal, evidence = self.set_dead_anchor_fixture()
                mutate(evidence[0])
                self.write(anchor_removals=[removal])
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)

    def test_dead_anchor_cone_requires_declared_header_and_exact_fact_and_evidence_counts(self):
        counters = ('anchorRemovalRecordCount', 'connectionAnchorRemovalEvidenceRecordCount',
                    'connectionAnchorRemovalEvidenceConnectionCount', 'connectionRemovalEvidenceRecordCount',
                    'connectionRemovalEvidenceConnectionCount')
        for scenario in ('missing_header', 'bad_version', 'duplicate_fact', 'gap_in_fact_ids',
                         *counters, *('missing_' + field for field in counters)):
            with self.subTest(scenario=scenario):
                removal, _ = self.set_dead_anchor_fixture()
                if scenario == 'gap_in_fact_ids':
                    removal['detail']['anchor_removal_id'] = 2
                self.write(anchor_removals=[removal, deepcopy(removal)] if scenario == 'duplicate_fact' else [removal])
                if scenario == 'missing_header':
                    del self.rows[0]['detail_json']['connection_anchor_removal_trace']
                elif scenario == 'bad_version':
                    self.rows[0]['detail_json']['connection_anchor_removal_trace'] = 'dead-anchor-cone.v0'
                elif scenario in counters:
                    self.rows[-1]['detail_json'][scenario] += 1
                elif scenario.startswith('missing_'):
                    del self.rows[-1]['detail_json'][scenario.removeprefix('missing_')]
                self.write_rows()
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)

    def test_dead_anchor_cone_requires_same_event_old_edge_and_unchanged_surviving_endpoints(self):
        for scenario in ('missing_old_edit', 'wrong_old_edge', 'changed_source', 'deleted_source',
                         'changed_target', 'same_key_reinserted'):
            with self.subTest(scenario=scenario):
                removal, _ = self.set_dead_anchor_fixture()
                if scenario == 'missing_old_edit':
                    self.events[0]['before_edges'] = []
                elif scenario == 'wrong_old_edge':
                    self.events[0]['before_edges'] = [edge(10, 2, 3)]
                elif scenario in ('changed_source', 'changed_target'):
                    identifier = 1 if scenario == 'changed_source' else 3
                    previous = next(row for row in self.before_nodes if row['node_id'] == identifier)
                    current = node(identifier, 'changed')
                    self.after_nodes = [current if row['node_id'] == identifier else row for row in self.after_nodes]
                    self.events[0].update(before_nodes=[previous], after_nodes=[current])
                elif scenario == 'deleted_source':
                    self.after_nodes = [row for row in self.after_nodes if row['node_id'] != 1]
                    self.events[0]['before_nodes'] = [self.before_nodes[0]]
                else:
                    created = edge(11, 1, 3)
                    self.after_edges = [created]
                    self.events[0]['after_edges'] = [created]
                self.write(anchor_removals=[removal])
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)

    def test_dead_anchor_fact_without_final_edge_claim_still_requires_an_unchanged_surviving_target(self):
        removal, _ = self.set_dead_anchor_fixture()
        self.events[0]['removal_evidence'] = []
        self.write(anchor_removals=[removal])
        result = verify_bundle(self.directory)
        self.assertTrue(result['replay_exact'])
        self.assertEqual(result['anchor_removal_count'], 1)
        self.assertEqual(result['connection_removal_evidence_records'], 0)
        for scenario in ('changed', 'retired'):
            with self.subTest(scenario=scenario):
                removal, _ = self.set_dead_anchor_fixture()
                self.events[0]['removal_evidence'] = []
                target = next(row for row in self.before_nodes if row['node_id'] == 3)
                self.events[0]['before_nodes'] = [target]
                self.after_nodes = [row for row in self.after_nodes if row['node_id'] != 3]
                if scenario == 'changed':
                    current = node(3, 'changed')
                    self.after_nodes.append(current)
                    self.events[0]['after_nodes'] = [current]
                self.write(anchor_removals=[removal])
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)

    def test_removal_claims_require_unchanged_final_endpoints_after_later_events(self):
        for cause in ('operand', 'anchor'):
            for role in ('source', 'candidate_source', 'target'):
                for change in ('renamed', 'deleted'):
                    with self.subTest(cause=cause, role=role, change=change):
                        candidates = [1, 2] if role == 'candidate_source' else None
                        if cause == 'operand':
                            mutation, _ = self.set_pruned_operand_path_fixture('named', candidates=candidates)
                            arguments = {'operand_mutations': [mutation]}
                        else:
                            removal, _ = self.set_dead_anchor_fixture('named', candidates=candidates)
                            arguments = {'anchor_removals': [removal]}
                        identifier = 3 if role == 'target' else 2 if role == 'candidate_source' else 1
                        previous = next(row for row in self.before_nodes if row['node_id'] == identifier)
                        later = {'action': 'replace' if change == 'renamed' else 'delete',
                                 'reason': 'later_endpoint_change', 'before_nodes': [previous]}
                        self.after_nodes = [row for row in self.after_nodes if row['node_id'] != identifier]
                        if change == 'renamed':
                            current = node(identifier, 'later_name')
                            later['after_nodes'] = [current]
                            self.after_nodes.append(current)
                        self.events.append(later)
                        self.write(**arguments)
                        with self.assertRaises(ValueError):
                            verify_bundle(self.directory)

    def test_later_unrelated_node_change_preserves_valid_removal_claims(self):
        for cause in ('operand', 'anchor'):
            with self.subTest(cause=cause):
                if cause == 'operand':
                    mutation, _ = self.set_pruned_operand_path_fixture('named')
                    arguments = {'operand_mutations': [mutation]}
                else:
                    removal, _ = self.set_dead_anchor_fixture('named')
                    arguments = {'anchor_removals': [removal]}
                previous = next(row for row in self.before_nodes if row['node_id'] == 2)
                current = node(2, 'unrelated_later_name')
                self.after_nodes = [current if row['node_id'] == 2 else row for row in self.after_nodes]
                self.events.append({'action': 'replace', 'reason': 'later_unrelated_node_change',
                                    'before_nodes': [previous], 'after_nodes': [current]})
                self.write(**arguments)
                result = verify_bundle(self.directory)
                self.assertTrue(result['replay_exact'])
                self.assertEqual(result['events'], 2)
                self.assertEqual(result['connection_removal_evidence_records'], 1)

    def set_candidate_prune_fixture(self, *, source=None, created=None, deleted_ids=None):
        node_a, node_b, target = node(1, 'B'), node(2, 'A'), node(3, 'target')
        old = {'connection_id': 10, 'source_node_id': None, 'target_node_id': 3,
               'kind': 'dependency', 'resolution': 'unresolved',
               'candidate_sources_json': [1, 2], 'reason': 'ambiguous'}
        new = {'connection_id': 11, 'source_node_id': None, 'target_node_id': 3,
               'kind': 'dependency', 'resolution': 'unresolved',
               'candidate_sources_json': [1], 'reason': 'ambiguous'}
        source = old if source is None else source
        created = new if created is None else created
        deleted_ids = [2] if deleted_ids is None else deleted_ids
        detail = {'phase': 'pass-transition', 'cause': 'candidate_pruned_by_node_deletion',
                  'event_sequence': 1, 'source_connection_id': source['connection_id'],
                  'deleted_node_ids': deleted_ids}
        self.before_nodes = [node_a, node_b, target]
        self.after_nodes = [node_a, target]
        self.before_edges = [source]
        self.after_edges = [created]
        self.events = [{'action': 'replace', 'reason': 'candidate_prune',
                        'before_nodes': [node_b], 'before_edges': [source],
                        'after_edges': [created],
                        'transition_evidence': [{'connection_id': created['connection_id'],
                                                 'detail': detail}]}]

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

    def test_snapshot_bulk_reference_checks_all_endpoint_roles(self):
        for role in ('source', 'target', 'candidate'):
            with self.subTest(role=role):
                connection = edge(1, 1, 2)
                if role == 'candidate':
                    connection.update(source_node_id=None, resolution='unresolved',
                                      candidate_sources_json=[1, 999], reason='ambiguous')
                else:
                    connection[role + '_node_id'] = 999
                self.snapshot('', self.before_nodes, [connection], 'snapshot')
                with self.assertRaisesRegex(ValueError, 'inactive Node'):
                    verify_snapshot(self.directory)

    def test_bulk_reference_index_deduplicates_self_and_candidate_endpoints(self):
        unresolved = edge(2, None, 2)
        unresolved.update(resolution='unresolved', candidate_sources_json=[1, 2], reason='ambiguous')
        self.before_edges = [edge(1, 1, 1), unresolved]
        self.after_nodes, self.after_edges, self.events = self.before_nodes, self.before_edges, []
        self.write()
        database = self.directory / 'refs.sqlite'
        self.assertTrue(verify_bundle(self.directory, database)['replay_exact'])
        with sqlite3.connect(database) as db:
            self.assertEqual(db.execute('SELECT * FROM connection_refs ORDER BY edge,node').fetchall(),
                             [(1, 1), (2, 1), (2, 2)])

    def test_event_cannot_reference_a_node_created_by_a_later_event(self):
        extra = node(8, 'later')
        added = edge(8, 1, 8)
        self.after_nodes, self.after_edges = [*self.before_nodes, extra], [*self.before_edges, added]
        self.events = [{'action': 'add', 'reason': 'premature_edge', 'after_edges': [added]},
                       {'action': 'add', 'reason': 'create_later', 'after_nodes': [extra]}]
        self.write()
        (self.directory / 'after.nodes.tsv').unlink()
        with self.assertRaisesRegex(ValueError, 'inactive Node'):
            verify_bundle(self.directory)

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

    def test_candidate_prune_transition_evidence_replays(self):
        self.set_candidate_prune_fixture()
        self.write()
        result = verify_bundle(self.directory)
        self.assertTrue(result['replay_exact'])
        self.assertEqual(result['connection_transition_evidence'], 1)

        self.set_candidate_prune_fixture()
        self.events[0]['before_edges'] = []
        self.write()
        with self.assertRaisesRegex(ValueError, 'same-event connection edits'):
            verify_bundle(self.directory)

    def test_candidate_prune_can_resolve_one_remaining_native_source(self):
        old = {'connection_id': 10, 'source_node_id': None, 'target_node_id': 3,
               'kind': 'dependency', 'resolution': 'unresolved',
               'candidate_sources_json': [1, 2], 'reason': 'ambiguous-native-boundary'}
        self.set_candidate_prune_fixture(source=old, created=edge(11, 1, 3))
        self.write()
        self.assertEqual(verify_bundle(self.directory)['connection_transition_evidence'], 1)
        self.events[0]['after_edges'][0]['source_node_id'] = 3
        self.after_edges[0]['source_node_id'] = 3
        self.write()
        with self.assertRaisesRegex(ValueError, 'does not match the pruned candidate set'):
            verify_bundle(self.directory)

    def set_boundary_retirement_fixture(self, *, candidates=None, zero_step=False):
        source, retired, target = node(1, 'upstream'), node(2, 'retired'), node(3, 'target')
        old = edge(10, 2, 3)
        created = edge(11, 1, 3)
        live_nodes = [source, target]
        if candidates is not None:
            created.update(source_node_id=None, resolution='unresolved',
                           candidate_sources_json=candidates, reason='ambiguous-native-boundary')
            live_nodes.append(node(4, 'other_upstream'))
        transition = {'phase': 'pass-transition', 'cause': 'dependency_exposed_by_boundary_retirement',
                      'event_sequence': 1, 'source_connection_id': 10, 'boundary_id': 1,
                      'supporting_node_id': 1,
                      'start_context': {'operation_id': 31, 'operation_generation': 0, 'operand_index': 2},
                      'path': [{'value_id': 10, 'value_generation': 0, 'definition_operation_id': 21,
                                'definition_operation_generation': 0, 'operand_index': 0,
                                'operand_value_id': 11, 'operand_value_generation': 0}]}
        boundary = {'boundary_id': 1, 'source_node_id': 2, 'target_node_id': 3,
                    'value_id': 10, 'value_generation': 0, 'operation_id': 31,
                    'operation_generation': 0, 'operand_index': 2, 'boundary_kind': 'data'}
        if zero_step:
            boundary.update(value_generation=7, operation_generation=4)
            transition['start_context']['operation_generation'] = 4
            transition['path'] = []
        self.before_nodes = [*live_nodes, retired]
        self.after_nodes = live_nodes
        self.before_edges, self.after_edges = [old], [created]
        self.events = [{'action': 'replace', 'reason': 'retire_native_boundary',
                        'before_nodes': [retired], 'before_edges': [old], 'after_edges': [created],
                        'transition_evidence': [{'connection_id': 11, 'detail': transition}]}]
        witnesses = [self.boundary_witness(11, source_id, 3)
                     for source_id in ([1] if candidates is None else candidates)]
        if zero_step:
            witnesses = [{'phase': 'postpass-native-walk', 'connection_id': 11,
                          'witness_kind': 'fallback_value_owner', 'supporting_node_id': source_id,
                          'value_id': 10, 'value_generation': 7, 'operation_id': 31,
                          'operation_generation': 4, 'operand_index': 2}
                         for source_id in ([1] if candidates is None else candidates)]
        self.write_with_connection_evidence(witnesses)
        self.rows[0]['detail_json']['boundary_retirement_trace'] = 'boundary-retirement.v1'
        self.rows.insert(1, {'record': 'mutation', 'seq': 0, 'ordinal': 1,
                            'action': 'delete', 'reason': 'retired_node_boundary', 'subject': 'boundary',
                            'side': 'before', 'object_id': 1, 'detail_json': boundary})
        for seq in {row['seq'] for row in self.rows}:
            for ordinal, row in enumerate(row for row in self.rows if row['seq'] == seq):
                row['ordinal'] = ordinal
        self.rows[-1]['detail_json']['boundaryRetirementRecordCount'] = 1
        self.write_rows()
        return boundary, transition

    def test_boundary_retirement_native_path_replays_resolved_and_candidate_edges(self):
        for candidates in (None, [1, 4]):
            with self.subTest(candidates=candidates):
                self.set_boundary_retirement_fixture(candidates=candidates)
                result = verify_bundle(self.directory)
                self.assertTrue(result['replay_exact'])
                self.assertEqual(result['boundary_retirement_count'], 1)
                self.assertEqual(result['connection_transition_evidence'], 1)

        boundary, _ = self.set_boundary_retirement_fixture()
        boundary.update(operation_id=0, operand_index=None, boundary_kind='value_owner')
        self.write_rows()
        self.assertEqual(verify_bundle(self.directory)['connection_transition_evidence'], 1)

    def test_boundary_retirement_rejects_incomplete_or_disconnected_native_paths(self):
        cases = (
            ('wrong start value', lambda b, t: t['path'][0].update(value_id=999)),
            ('wrong consumer', lambda b, t: t['start_context'].update(operation_id=32)),
            ('wrong slot', lambda b, t: t['start_context'].update(operand_index=1)),
            ('wrong target', lambda b, t: b.update(target_node_id=1)),
            ('wrong source', lambda b, t: b.update(source_node_id=1)),
            ('missing mutation', lambda b, t: t.update(boundary_id=2)),
            ('missing path', lambda b, t: t.update(path=[])),
            ('wrong terminal value', lambda b, t: t['path'][-1].update(operand_value_id=99)),
            ('wrong terminal operation', lambda b, t: t['path'][-1].update(definition_operation_id=22)),
            ('wrong supporting Node', lambda b, t: t.update(supporting_node_id=3)),
            ('wrong cause', lambda b, t: t.update(cause='unproven_retirement')),
            ('cyclic path', lambda b, t: t['path'][0].update(operand_value_id=10)),
            ('unknown field', lambda b, t: t.update(unchecked=True)),
        )
        for label, mutate in cases:
            with self.subTest(label=label):
                boundary, transition = self.set_boundary_retirement_fixture()
                mutate(boundary, transition)
                self.write_rows()
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)

    def test_zero_step_boundary_retirement_requires_exact_same_native_operand_use(self):
        for candidates in (None, [1, 4]):
            with self.subTest(candidates=candidates):
                self.set_boundary_retirement_fixture(candidates=candidates, zero_step=True)
                result = verify_bundle(self.directory)
                self.assertTrue(result['replay_exact'])
                self.assertEqual(result['connection_transition_evidence'], 1)

        for field, wrong in (('value_id', 12), ('value_generation', 8), ('operation_id', 32),
                             ('operation_generation', 5), ('operand_index', 1)):
            with self.subTest(field=field):
                self.set_boundary_retirement_fixture(zero_step=True)
                witness = next(row['detail_json'] for row in self.rows if row['record'] == 'evidence'
                               and row['seq'] == 0)
                witness[field] = wrong
                self.write_rows()
                with self.assertRaisesRegex(ValueError, 'exact terminal native support'):
                    verify_bundle(self.directory)

        for named in (False, True):
            with self.subTest(named=named):
                boundary, transition = self.set_boundary_retirement_fixture(zero_step=True)
                boundary['operand_index'] = None
                transition['start_context']['operand_index'] = None
                if named:
                    boundary.update(operation_id=0, operation_generation=0, boundary_kind='value_owner')
                    transition['start_context'].update(operation_id=0, operation_generation=0)
                self.write_rows()
                with self.assertRaisesRegex(ValueError, 'requires an exact native operand use'):
                    verify_bundle(self.directory)

    def test_zero_step_boundary_retirement_rejects_incomplete_candidates_and_retained_source(self):
        self.set_boundary_retirement_fixture(candidates=[1, 4], zero_step=True)
        witness = next(row['detail_json'] for row in self.rows if row['record'] == 'evidence'
                       and row['seq'] == 0 and row['detail_json'].get('supporting_node_id') == 4)
        witness['operand_index'] = 1
        self.write_rows()
        with self.assertRaisesRegex(ValueError, 'exact terminal native support'):
            verify_bundle(self.directory)

        self.set_boundary_retirement_fixture(zero_step=True)
        witness = next(row['detail_json'] for row in self.rows if row['record'] == 'evidence'
                       and row['seq'] == 0)
        witness.clear()
        witness.update(phase='postpass-native-walk', connection_id=11, witness_kind='missing_native_boundary')
        self.rows[-1]['detail_json']['connectionEvidenceMissingSupportCount'] = 1
        self.write_rows()
        with self.assertRaisesRegex(ValueError, 'exact terminal native support'):
            verify_bundle(self.directory)

        self.set_boundary_retirement_fixture(zero_step=True)
        transition_index = next(index for index, row in enumerate(self.rows)
                                if row['record'] == 'evidence' and row['seq'] == 1)
        self.rows.insert(transition_index, {'record': 'edit', 'seq': 1, 'ordinal': 0,
            'action': None, 'reason': None, 'subject': 'node', 'side': 'after',
            'object_id': 2, 'detail_json': node(2, 'retired')})
        for ordinal, row in enumerate(row for row in self.rows if row['seq'] == 1):
            row['ordinal'] = ordinal
        self.write_rows()
        with self.assertRaisesRegex(ValueError, 'not retired in the same event'):
            verify_bundle(self.directory)

    def test_boundary_retirement_requires_native_support_for_every_candidate(self):
        self.set_boundary_retirement_fixture(candidates=[1, 4])
        row = next(row for row in self.rows if row['record'] == 'evidence' and row['seq'] == 0 and
                   row['detail_json'].get('supporting_node_id') == 4)
        row['detail_json']['value_id'] = 12
        self.write_rows()
        with self.assertRaisesRegex(ValueError, 'exact terminal native support'):
            verify_bundle(self.directory)

    def test_boundary_retirement_requires_same_event_node_retirement_and_declared_count(self):
        self.set_boundary_retirement_fixture()
        self.rows = [row for row in self.rows if not (
            row['record'] == 'edit' and row['subject'] == 'node' and row['object_id'] == 2)]
        for seq in {row['seq'] for row in self.rows}:
            for ordinal, row in enumerate(row for row in self.rows if row['seq'] == seq):
                row['ordinal'] = ordinal
        self.write_rows()
        with self.assertRaisesRegex(ValueError, 'not retired in the same event'):
            verify_bundle(self.directory)
        self.set_boundary_retirement_fixture()
        self.rows[-1]['detail_json']['boundaryRetirementRecordCount'] = 2
        self.write_rows()
        with self.assertRaisesRegex(ValueError, 'boundary retirement count mismatch'):
            verify_bundle(self.directory)

    def test_candidate_prune_transition_evidence_rejects_forged_mutations(self):
        bad_cases = (
            ('wrong target', lambda source, created: created.update(target_node_id=1), None),
            ('wrong kind', lambda source, created: created.update(kind='state_update'), None),
            ('wrong reason', lambda source, created: created.update(reason='different_reason'), None),
            ('candidate not removed', lambda source, created: created.update(candidate_sources_json=[1, 2]), None),
            ('deleted candidate omitted', lambda source, created: None, [1]),
            ('unknown detail field', lambda source, created: None, None),
            ('source not unresolved', lambda source, created: source.update(
                source_node_id=1, resolution='resolved', candidate_sources_json=[], reason=None), None),
        )
        for label, mutate_connections, deleted_ids in bad_cases:
            with self.subTest(label=label):
                source = {'connection_id': 10, 'source_node_id': None, 'target_node_id': 3,
                          'kind': 'dependency', 'resolution': 'unresolved',
                          'candidate_sources_json': [1, 2], 'reason': 'ambiguous'}
                created = {'connection_id': 11, 'source_node_id': None, 'target_node_id': 3,
                           'kind': 'dependency', 'resolution': 'unresolved',
                           'candidate_sources_json': [1], 'reason': 'ambiguous'}
                mutate_connections(source, created)
                self.set_candidate_prune_fixture(source=source, created=created, deleted_ids=deleted_ids)
                self.write()
                if label == 'unknown detail field':
                    self.rows[-2]['detail_json']['unexpected'] = True
                    self.write_rows()
                with self.assertRaises(ValueError):
                    verify_bundle(self.directory)

        self.set_candidate_prune_fixture()
        self.write()
        header = self.rows[0]['detail_json']
        del header['connection_transition_trace']
        self.write_rows()
        with self.assertRaisesRegex(ValueError, 'transition evidence position'):
            verify_bundle(self.directory)

        self.set_candidate_prune_fixture()
        self.write()
        self.rows[-1]['detail_json']['connectionTransitionEvidenceCount'] = 2
        self.write_rows()
        with self.assertRaisesRegex(ValueError, 'transition evidence count mismatch'):
            verify_bundle(self.directory)

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
