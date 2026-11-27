"""Small current-run native fixtures exercise F31 identity, replay and attribution."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import analyze_f31_dce_alignment as analysis
from semantic_node_exchange import HEADERS, KINDS, SCHEMA, compact, decode_cell, encode_cell


def node(identifier, name):
    return {'node_id': identifier, 'name_path_json': [name], 'native_name': name}


def edge(identifier, source, target, kind='dependency', candidates=None, reason=None):
    return {'connection_id': identifier, 'source_node_id': source, 'target_node_id': target,
        'kind': kind, 'resolution': 'resolved' if source is not None else 'unresolved',
        'candidate_sources_json': [] if candidates is None else candidates, 'reason': reason}


def coverage(edges):
    return {kind: {'status': 'partial' if any(row['resolution'] == 'unresolved' and row['kind'] == kind for row in edges) else 'complete',
        'resolved': sum(row['kind'] == kind and row['resolution'] == 'resolved' for row in edges),
        'unresolved': sum(row['kind'] == kind and row['resolution'] == 'unresolved' for row in edges)} for kind in KINDS}


def identity(engine, session, digest='a' * 64):
    return {'schema': SCHEMA, 'engine': engine, 'run_id': engine + '-current-run',
        'graph_id': 'top', 'exchange_session_id': session, 'root_name': 'top', 'input_sha256': digest}


def snapshot(directory, phase, nodes, edges, metadata, snapshot_id):
    directory.mkdir(parents=True, exist_ok=True)
    for table, definitions in (('nodes', nodes), ('connections', edges)):
        with (directory / (phase + '.' + table + '.tsv')).open('w', encoding='utf-8') as stream:
            stream.write('#meta\t' + compact({**metadata, 'snapshot_id': snapshot_id,
                                             'stage': phase, 'table': table}) + '\n')
            stream.write('\t'.join(HEADERS[table]) + '\n')
            for row in sorted(definitions, key=lambda value: value['node_id' if table == 'nodes' else 'connection_id']):
                stream.write('\t'.join(encode_cell(compact(row[key]) if key.endswith('_json') else row[key])
                                       for key in HEADERS[table]) + '\n')
            stream.write('#footer\t' + compact({'complete': True, 'rowCount': len(definitions),
                **({'nodeInventoryComplete': True} if table == 'nodes' else {'connectionCoverage': coverage(edges)})}) + '\n')


def write_bundle(directory, engine, inventory, *, instance=None, digest='a' * 64,
                 generic=False, decisions=True, split=False, extra_decisions=(), transition_evidence=(),
                 boundary_retirements=(), connection_evidence=(), operand_mutations=(), removal_evidence=(),
                 anchor_removals=(), liveness_provenance=True):
    meta = identity(engine, engine + ('-split' if split else '-dce'), digest)
    header = {**meta, 'mode': 'trace', 'pass': 'splitArray' if split else
              'dead-code-elim' if engine == 'grh' else 'removeDeadNodes',
              'pass_instance': instance or ('SplitArray#0' if split else 'dead-code-elim#0' if engine == 'grh' else 'RemoveDeadNodes#0'),
              'before_snapshot_id': meta['exchange_session_id'] + '-before',
              'after_snapshot_id': meta['exchange_session_id'] + '-after'}
    if transition_evidence:
        header['connection_transition_trace'] = 'candidate-prune.v1'
    if boundary_retirements:
        header['boundary_retirement_trace'] = 'boundary-retirement.v1'
    if connection_evidence:
        header['connection_evidence'] = 'postpass-native-walk'
    if operand_mutations:
        header['mutation_trace'] = 'operand-rewrite.v1'
    anchor_evidence = [item for item in removal_evidence if item['cause'] == 'dead_anchor_cone']
    operand_evidence = [item for item in removal_evidence if item['cause'] != 'dead_anchor_cone']
    if anchor_removals or anchor_evidence:
        header['connection_anchor_removal_trace'] = 'dead-anchor-cone.v1'
    if operand_evidence:
        header['connection_removal_trace'] = ('pruned-operand-support.v2'
            if any('path' in item for item in operand_evidence) else 'pruned-operand-support.v1'
            if any('support_kind' in item for item in operand_evidence) else 'pruned-operand-boundary.v1')
    if engine == 'grh' and liveness_provenance:
        header['liveness_provenance'] = 'dce-causality.v1'
    for phase in ('before', 'after'):
        snapshot(directory, phase, inventory[phase + '_nodes'], inventory[phase + '_edges'], meta, header[phase + '_snapshot_id'])
    rows = []

    def append(record, seq, **fields):
        ordinal = 0 if not rows or rows[-1]['seq'] != seq else rows[-1]['ordinal'] + 1
        rows.append({'record': record, 'seq': seq, 'ordinal': ordinal, **fields})

    append('header', 0, detail_json=header)
    for mutation in operand_mutations:
        append('mutation', 0, action=mutation['action'], reason=mutation['reason'], subject='operand',
               side='transition', object_id=mutation['operation_id'], detail_json=mutation['detail'])
    for removal in anchor_removals:
        append('mutation', 0, action='delete', reason='dead_anchor_definition', subject='anchor',
               side='before', object_id=removal['target_node_id'], detail_json=removal['detail'])
    for boundary in boundary_retirements:
        append('mutation', 0, action='delete', reason='retired_node_boundary', subject='boundary',
               side='before', object_id=boundary['boundary_id'], detail_json=boundary)
    for witness in connection_evidence:
        append('evidence', 0, action=None, reason='postpass-native-witness', subject='connection',
               side='after', object_id=witness['connection_id'], detail_json=witness)
    before_nodes = {row['node_id']: row for row in inventory['before_nodes']}
    after_nodes = {row['node_id']: row for row in inventory['after_nodes']}
    deleted = sorted(before_nodes.keys() - after_nodes.keys())
    if decisions:
        for identifier in deleted:
            reason = 'dead_owner_anchor' if engine == 'grh' else 'no_observable_demand'
            detail = {'pass': header['pass'], 'outcome': 'delete', 'blocker_node_ids': []}
            if engine == 'grh':
                detail['dce_deletion'] = {'rule': reason, 'anchor_count': 1, 'demanded_anchor_count': 0,
                    'owned_operation_count': 2, 'live_owned_operation_count': 1,
                    'port_root': False, 'protected_boundary_root': False, 'state_family': False,
                    'memory_node': False, 'zero_width_boundary': False}
            append('decision', 0, subject='node', side='before', object_id=identifier,
                reason=reason, detail_json=detail)
    for identifier, outcome, reason in extra_decisions:
        append('decision', 0, subject='node', side='before', object_id=identifier, reason=reason,
               detail_json={'pass': header['pass'], 'outcome': outcome, 'blocker_node_ids': []})
    edits = []
    for subject, key, before, after in (
        ('node', 'node_id', inventory['before_nodes'], inventory['after_nodes']),
        ('connection', 'connection_id', inventory['before_edges'], inventory['after_edges'])):
        old, new = {row[key]: row for row in before}, {row[key]: row for row in after}
        for side, own, peer in (('before', old, new), ('after', new, old)):
            for identifier, body in own.items():
                if peer.get(identifier) != body:
                    edits.append({'subject': subject, 'side': side, 'object_id': identifier, 'detail_json': body})
    if edits:
        sides = {row['side'] for row in edits}
        append('event', 1, action='replace' if len(sides) == 2 else 'delete' if 'before' in sides else 'add',
               reason='complete-pass:' + header['pass'] if generic else 'dead_owner_anchor')
        for edit in edits:
            append('edit', 1, **edit)
        for evidence in transition_evidence:
            append('evidence', 1, action=None, reason=evidence['detail']['cause'],
                   subject='connection', side='after', object_id=evidence['connection_id'],
                   detail_json=evidence['detail'])
        for evidence in removal_evidence:
            append('evidence', 1, action=None, reason=evidence['cause'], subject='connection',
                   side='before', object_id=evidence['connection_id'], detail_json=evidence)
    append('footer', int(bool(edits)), detail_json={'complete': True, 'replayComplete': True,
        'eventCount': int(bool(edits)), 'decisionCount': (len(deleted) if decisions else 0) + len(extra_decisions),
        'beforeNodeCount': len(before_nodes), 'afterNodeCount': len(after_nodes),
        'beforeConnectionCount': len(inventory['before_edges']), 'afterConnectionCount': len(inventory['after_edges']),
        'nodeInventoryComplete': True, 'connectionCoverage': coverage(inventory['after_edges']),
        **({'boundaryRetirementRecordCount': len(boundary_retirements)} if boundary_retirements else {}),
        **({'connectionEvidenceRequestCount': len({row['connection_id'] for row in connection_evidence}),
            'connectionEvidenceConnectionCount': len({row['connection_id'] for row in connection_evidence}),
            'connectionEvidenceRecordCount': len(connection_evidence),
            'connectionEvidenceMissingSupportCount': 0} if connection_evidence else {}),
        **({'connectionTransitionEvidenceCount': len(transition_evidence)} if transition_evidence else {}),
        **({'mutationRecordCount': len(operand_mutations)} if operand_mutations else {}),
        **({'anchorRemovalRecordCount': len(anchor_removals),
            'connectionAnchorRemovalEvidenceRecordCount': len(anchor_evidence),
            'connectionAnchorRemovalEvidenceConnectionCount': len({row['connection_id'] for row in anchor_evidence})}
           if anchor_removals or anchor_evidence else {}),
        **({'connectionRemovalEvidenceRecordCount': len(removal_evidence),
            'connectionRemovalEvidenceConnectionCount': len({row['connection_id'] for row in removal_evidence})}
           if removal_evidence else {}),
        **({'livenessProvenanceCount': 0} if engine == 'grh' and liveness_provenance else {})})
    with (directory / 'evolution.tsv').open('w', encoding='utf-8') as stream:
        stream.write('\t'.join(HEADERS['evolution']) + '\n')
        for row in rows:
            stream.write('\t'.join(encode_cell(compact(row[key]) if key == 'detail_json' and row.get(key) is not None
                else row.get(key)) for key in HEADERS['evolution']) + '\n')


class DceAlignmentTests(unittest.TestCase):
    def setUp(self):
        base = analysis.ROOT / 'ptmp/firrtl-ingest/F31/analysis-dev'
        base.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.grh, self.gsim, self.prep = (self.work / name for name in ('grh', 'gsim', 'preparation'))
        self.output = self.work / 'analysis'
        names = ['top.in', 'top.out', 'top.dead', 'top.grh_keep', 'top.gsim_keep', 'top.r_3', 'top.r_3_0']
        self.inventory = {}
        for engine, offset, deaths in (('grh', 0, (3, 5)), ('gsim', 100, (3, 5))):
            nodes = [node(offset + index, name) for index, name in enumerate(names, 1)]
            nodes.append(node(offset + 8, 'top.' + engine + '_extra'))
            edges = [edge(offset + 1, offset + 1, offset + 2),
                edge(offset + 2, offset + 6, offset + 2, 'state_update'),
                edge(offset + 3, offset + 1, offset + 6),
                edge(offset + 5, None, offset + 2, candidates=[offset + 1, offset + 6], reason='ambiguous_native_boundary'),
                edge(offset + 6, offset + 3, offset + 2), edge(offset + 7, offset + 6, offset + 2)]
            if engine == 'grh':
                edges.append(edge(4, 7, 2, 'storage_read'))
            before_edges = [row for row in edges if engine == 'grh' or row['connection_id'] != 103]
            self.inventory[engine] = {'before_nodes': nodes, 'after_nodes': [row for row in nodes if row['node_id'] - offset not in deaths],
                'before_edges': before_edges, 'after_edges': [row for row in before_edges if row['connection_id'] - offset != 6]}
            if engine == 'gsim':
                self.s0_nodes, self.s0_edges = deepcopy(nodes), deepcopy(edges)
        self.write()

    def write(self, *, grh_transition_evidence=(), grh_boundary_retirements=(), grh_connection_evidence=(),
              grh_operand_mutations=(), grh_removal_evidence=(), gsim_operand_mutations=(),
              gsim_removal_evidence=(), grh_anchor_removals=(), gsim_anchor_removals=(), **kwargs):
        write_bundle(self.grh, 'grh', self.inventory['grh'], transition_evidence=grh_transition_evidence,
                     boundary_retirements=grh_boundary_retirements, connection_evidence=grh_connection_evidence,
                     operand_mutations=grh_operand_mutations, removal_evidence=grh_removal_evidence,
                     anchor_removals=grh_anchor_removals,
                     **kwargs)
        write_bundle(self.gsim, 'gsim', self.inventory['gsim'], operand_mutations=gsim_operand_mutations,
                     removal_evidence=gsim_removal_evidence, anchor_removals=gsim_anchor_removals, **kwargs)
        self.write_preparation()

    def write_preparation(self):
        meta = identity('gsim', 'preparation')
        for phase, nodes, edges in (('before', self.s0_nodes, self.s0_edges),
            ('after', self.inventory['gsim']['before_nodes'], self.inventory['gsim']['before_edges'])):
            snapshot(self.prep, phase, nodes, edges, meta, 'prep-' + phase)
        (self.prep / 'summary.json').write_text(compact({'schema': 'gsim-preparation.v1', 'complete': True,
            'before_snapshot_id': 'prep-before', 'after_snapshot_id': 'prep-after'}) + '\n', encoding='utf-8')

    def add_grh_provenance(self, records):
        path = self.grh / 'evolution.tsv'
        lines = path.read_text(encoding='utf-8').splitlines()
        columns = HEADERS['evolution']
        rows = [dict(zip(columns, map(decode_cell, line.split('\t')))) for line in lines[1:]]
        rows = [row for row in rows if row['record'] != 'provenance']
        for row in rows:
            if row.get('detail_json') is not None:
                row['detail_json'] = json.loads(row['detail_json'])
        header = rows[0]
        header_detail = header['detail_json']
        header_detail['liveness_provenance'] = 'dce-causality.v1'
        next_ordinal = len(records) + 1
        for row in rows[1:]:
            if row['seq'] == '0':
                row['ordinal'] = str(next_ordinal)
                next_ordinal += 1
        for index, detail in enumerate(records, 1):
            rows.insert(index, {'record': 'provenance', 'seq': '0', 'ordinal': str(index),
                'action': None, 'reason': detail['relation'], 'subject': 'liveness', 'side': 'before',
                'object_id': str(index), 'detail_json': detail})
        footer = rows[-1]
        footer_detail = footer['detail_json']
        footer_detail['livenessProvenanceCount'] = len(records)
        with path.open('w', encoding='utf-8') as stream:
            stream.write('\t'.join(columns) + '\n')
            for row in rows:
                stream.write('\t'.join(encode_cell(compact(row[key]) if key == 'detail_json' and row.get(key) is not None
                    else row.get(key)) for key in columns) + '\n')

    def analyze(self, **kwargs):
        output = kwargs.pop('output', self.output)
        return analysis.analyze(self.grh, self.gsim, self.prep, output, **kwargs)

    def rows(self, name):
        lines = [line for line in (self.output / name).read_text(encoding='utf-8').splitlines() if not line.startswith('#')]
        return [dict(zip(lines[0].split('\t'), map(decode_cell, row.split('\t')))) for row in lines[1:]]

    def assert_rejected(self):
        with self.assertRaises(ValueError):
            self.analyze()
        self.assertFalse(any(self.output.glob('*.tsv')))
        self.assertFalse(json.loads((self.output / 'summary.json').read_text())['complete'])

    def test_replay_frozen_mapping_deletion_matrix_and_two_difference_origins(self):
        original = {str(path): path.read_bytes() for directory in (self.grh, self.gsim, self.prep) for path in directory.iterdir()}
        report = self.analyze()
        self.assertTrue(report['complete'])
        self.assertTrue(report['passed'], report['issues'])
        self.assertEqual(report['nodes']['before_candidates'], 7)
        self.assertEqual(report['nodes']['deletion_matrix'], {'both_retained': 5, 'both_deleted': 2})
        self.assertEqual(report['nodes']['common_survivors'], 5)
        self.assertEqual(report['nodes']['deletion_contract'], {
            'required': 'every_gsim_deleted_grh_retained_node_has_a_rooted_semantic_explanation',
            'violations': 0, 'explained_retention': 0, 'unexplained_retention': 0,
            'allowed_grh_extra_deletions': 0})
        self.assertEqual(report['connections']['after_difference_origins'], {'introduced_by_gsim_preparation': 1,
            'inherited_from_split': 1})
        self.assertEqual(report['connections']['preparation_all_nodes']['removed'], 1)
        self.assertEqual(report['connection_scope']['g1']['comparable_unresolved'], 1)
        self.assertEqual(report['connection_scope']['s2']['comparable_unresolved'], 1)
        self.assertEqual(report['inventories']['grh']['runtime_deletions_covered'], 2)
        self.assertEqual(report['inventories']['grh']['structured_deletion_decisions'], 2)
        self.assertEqual(report['inventories']['grh']['structured_deletion_nodes_covered'], 2)
        self.assertEqual(report['inventories']['grh']['structured_deletion_rule_node_counts'], {'dead_owner_anchor': 2})
        self.assertEqual(len(self.rows('node-deletion-matrix.tsv')), 7)
        self.assertEqual(len(self.rows('node-differences.tsv')), 2)
        self.assertEqual(self.rows('node-name-changes.tsv'), [])
        self.assertEqual(original, {path: Path(path).read_bytes() for path in original})

    def test_grh_may_delete_more_nodes_than_gsim(self):
        self.inventory['grh']['after_nodes'] = [row for row in self.inventory['grh']['after_nodes']
                                                  if row['node_id'] != 4]
        self.write()
        report = self.analyze()
        self.assertTrue(report['complete'])
        self.assertTrue(report['passed'], report['issues'])
        self.assertEqual(report['nodes']['deletion_contract']['violations'], 0)
        self.assertEqual(report['nodes']['deletion_contract']['allowed_grh_extra_deletions'], 1)
        self.assertEqual(report['nodes']['deletion_matrix']['grh_deleted_gsim_retained'], 1)

    def test_unexplained_grh_retention_fails(self):
        self.inventory['gsim']['after_nodes'] = [row for row in self.inventory['gsim']['after_nodes']
                                                   if row['node_id'] != 104]
        self.write()
        report = self.analyze()
        self.assertTrue(report['complete'])
        self.assertFalse(report['passed'])
        self.assertEqual(report['nodes']['deletion_contract']['violations'], 1)
        self.assertEqual(report['nodes']['retention_explanations']['unexplained'], 1)
        self.assertTrue(any(issue == {'kind': 'unexplained_grh_retention', 'nodes': 1}
                            for issue in report['issues']))

    def test_missing_owner_provenance_is_not_reported_as_zero_violations(self):
        self.write(liveness_provenance=False)
        report = self.analyze(summary_only=True)
        self.assertEqual(report['live_operation_owners']['status'], 'unavailable')
        self.assertIsNone(report['live_operation_owners']['violating_operations'])
        self.assertIn({'kind': 'live_operation_owner_audit_unavailable',
                       'reason': 'missing_liveness_provenance'}, report['issues'])
        self.assertFalse(report['diagnostic_passed'])

    def test_summary_only_matches_full_functional_gates_without_bulk_tsvs(self):
        self.maxDiff = None
        self.inventory['gsim']['after_nodes'] = [row for row in self.inventory['gsim']['after_nodes']
                                                   if row['node_id'] != 104]
        self.inventory['grh']['after_edges'] = [row for row in self.inventory['grh']['after_edges']
                                                 if row['connection_id'] != 2]
        self.inventory['grh']['after_edges'].append(edge(20, 2, 1))
        self.write()
        self.add_grh_provenance([{'relation': 'start', 'node_id': 3, 'start_kind': 'owned_operation',
            'entity_kind': 'operation', 'entity_id': 77, 'generation': 4, 'owner_count': 1}])
        full = self.analyze(output=self.work / 'full')
        fast = self.analyze(output=self.work / 'fast', summary_only=True)

        self.assertEqual(fast['nodes'], full['nodes'])
        self.assertEqual(fast['connection_scope'], full['connection_scope'])
        self.assertEqual(fast['connections'], full['connections'])
        self.assertEqual(fast['live_operation_owners'], full['live_operation_owners'])
        self.assertEqual(fast['inventories'], full['inventories'])
        self.assertEqual(fast['issues'], full['issues'])
        self.assertFalse(full['passed'])
        self.assertIsNone(fast['passed'])
        self.assertFalse(fast['acceptance_eligible'])
        self.assertFalse(fast['diagnostic_passed'])
        self.assertTrue(fast['required_checks_run'])
        self.assertFalse(fast['full_report_complete'])
        self.assertFalse(list((self.work / 'fast').glob('*.tsv')))
        self.assertEqual(fast['nodes']['retention_explanations']['unexplained'], 1)
        self.assertEqual(fast['nodes']['unexplained_samples'][0]['grh_node_id'], 4)
        self.assertEqual(fast['nodes']['unexplained_samples'][0]['gsim_node_id'], 104)
        self.assertEqual(fast['connections']['dce_changes']['grh']['requires_semantic_review'], 1)
        self.assertEqual(fast['connections']['dce_changes']['grh']['removed_requires_semantic_review'], 1)
        self.assertEqual(fast['live_operation_owners']['violating_operations'], 1)

    def test_summary_only_matches_full_unresolved_candidate_set_change(self):
        self.maxDiff = None
        self.inventory['grh']['before_edges'].append(
            edge(50, None, 2, candidates=[1, 6], reason='changed-candidate-set'))
        self.inventory['grh']['after_edges'].append(
            edge(51, None, 2, candidates=[1, 7], reason='changed-candidate-set'))
        self.write()

        full = self.analyze(output=self.work / 'full-unresolved')
        fast = self.analyze(output=self.work / 'fast-unresolved', summary_only=True)

        self.assertEqual(fast['connection_scope'], full['connection_scope'])
        self.assertEqual(fast['connections'], full['connections'])
        changes = fast['connections']['dce_changes']['grh']
        self.assertEqual(changes['requires_semantic_review'], 1)
        self.assertEqual(changes['removed_requires_semantic_review'], 1)
        self.assertIsNone(fast['passed'])
        self.assertFalse(fast['acceptance_eligible'])

    def test_verified_database_cache_uses_content_and_verifier_fingerprints(self):
        source = self.work / 'fixture.txt'
        source.write_bytes(b'one')
        cache = self.work / 'cache'
        verifier_digests = {'validator.py': 'a' * 64}
        calls = []

        def verify(directory, database):
            calls.append(str(database))
            with sqlite3.connect(database) as db:
                for name in ('before_nodes', 'after_nodes', 'current_nodes',
                             'before_connections', 'after_connections', 'current_connections', 'evolution'):
                    db.execute(f'CREATE TABLE {name}(id INTEGER)')
            return {'complete': True, 'replay_exact': True,
                    'before': {'nodes': {'rowCount': 0}, 'connections': {'rowCount': 0}},
                    'after': {'nodes': {'rowCount': 0}, 'connections': {'rowCount': 0}}}

        with patch.object(analysis.shutil, 'disk_usage', return_value=type('Usage', (), {'free': 2**40})()):
            first = analysis.Sources()
            first.watch(source)
            result1, db1, status1 = analysis.cached_verification('grh', self.work, ('fixture.txt',), first,
                verifier_digests, cache, verify, 'dce')
            second = analysis.Sources()
            second.watch(source)
            result2, db2, status2 = analysis.cached_verification('grh', self.work, ('fixture.txt',), second,
                verifier_digests, cache, verify, 'dce')
            self.assertEqual((status1, status2), ('miss', 'hit'))
            self.assertEqual(db1, db2)
            self.assertEqual(result1, result2)

            source.write_bytes(b'two')
            third = analysis.Sources()
            third.watch(source)
            _, _, status3 = analysis.cached_verification('grh', self.work, ('fixture.txt',), third,
                verifier_digests, cache, verify, 'dce')
            self.assertEqual(status3, 'miss')
            fourth = analysis.Sources()
            fourth.watch(source)
            _, _, status4 = analysis.cached_verification('grh', self.work, ('fixture.txt',), fourth,
                {'validator.py': 'b' * 64}, cache, verify, 'dce')
            self.assertEqual(status4, 'miss')
        self.assertEqual(len(calls), 3)

    def test_verified_database_cache_rebuilds_when_database_changes(self):
        source = self.work / 'fixture.txt'
        source.write_bytes(b'cache')
        cache = self.work / 'cache-corrupt'
        calls = []

        def verify(directory, database):
            calls.append(database)
            with sqlite3.connect(database) as db:
                for name in ('before_nodes', 'after_nodes', 'current_nodes',
                             'before_connections', 'after_connections', 'current_connections', 'evolution'):
                    db.execute(f'CREATE TABLE {name}(id INTEGER)')
            return {'complete': True, 'replay_exact': True,
                    'before': {'nodes': {'rowCount': 0}, 'connections': {'rowCount': 0}},
                    'after': {'nodes': {'rowCount': 0}, 'connections': {'rowCount': 0}}}

        with patch.object(analysis.shutil, 'disk_usage', return_value=type('Usage', (), {'free': 2**40})()):
            watcher = analysis.Sources()
            watcher.watch(source)
            _, database, _ = analysis.cached_verification('gsim', self.work, ('fixture.txt',), watcher,
                {'validator.py': 'c' * 64}, cache, verify, 'dce')
            database.write_bytes(b'corrupt sqlite cache')
            watcher2 = analysis.Sources()
            watcher2.watch(source)
            _, rebuilt, status = analysis.cached_verification('gsim', self.work, ('fixture.txt',), watcher2,
                {'validator.py': 'c' * 64}, cache, verify, 'dce')
        self.assertEqual(status, 'miss')
        self.assertEqual(database, rebuilt)
        self.assertEqual(len(calls), 2)

    def test_generic_retention_requires_a_rooted_liveness_path(self):
        self.inventory['gsim']['after_nodes'] = [row for row in self.inventory['gsim']['after_nodes']
                                                   if row['node_id'] != 104]
        self.write()
        self.add_grh_provenance([
            {'relation': 'root', 'entity_kind': 'value', 'entity_id': 99, 'generation': 0,
             'root_kind': 'output_port'},
            {'relation': 'edge', 'edge_kind': 'value_definition', 'from_kind': 'value',
             'from_id': 99, 'from_generation': 0, 'to_kind': 'operation', 'to_id': 77,
             'to_generation': 0, 'slot': 0},
            {'relation': 'edge', 'edge_kind': 'operation_operand', 'from_kind': 'operation',
             'from_id': 77, 'from_generation': 0, 'to_kind': 'value', 'to_id': 13,
             'to_generation': 0, 'slot': 0},
            {'relation': 'start', 'node_id': 4, 'start_kind': 'anchor', 'entity_kind': 'value',
             'entity_id': 13, 'generation': 0}])
        report = self.analyze()
        self.assertTrue(report['passed'], report['issues'])
        explanation = self.rows('node-retention-explanations.tsv')[0]
        self.assertEqual(explanation['classification'], 'explained')
        self.assertEqual(explanation['proof_kind'], 'rooted_liveness_dependency')
        proof = json.loads(explanation['evidence_json'])
        self.assertEqual(proof['root']['root_kind'], 'output_port')
        self.assertEqual([step['edge_toward_root']['edge_kind'] for step in proof['path'][:-1]],
                         ['operation_operand', 'value_definition'])

    def test_provenance_without_a_rooted_path_does_not_explain_retention(self):
        self.inventory['gsim']['after_nodes'] = [row for row in self.inventory['gsim']['after_nodes']
                                                   if row['node_id'] != 104]
        self.write()
        self.add_grh_provenance([
            {'relation': 'edge', 'edge_kind': 'value_definition', 'from_kind': 'value',
             'from_id': 99, 'from_generation': 0, 'to_kind': 'operation', 'to_id': 77,
             'to_generation': 0, 'slot': 0},
            {'relation': 'edge', 'edge_kind': 'operation_operand', 'from_kind': 'operation',
             'from_id': 77, 'from_generation': 0, 'to_kind': 'value', 'to_id': 13,
             'to_generation': 0, 'slot': 0},
            {'relation': 'start', 'node_id': 4, 'start_kind': 'anchor', 'entity_kind': 'value',
             'entity_id': 13, 'generation': 0}])
        report = self.analyze()
        self.assertFalse(report['passed'])
        self.assertEqual(report['nodes']['retention_explanations']['unexplained'], 1)
        self.assertEqual(self.rows('node-retention-explanations.tsv')[0]['proof_kind'],
                         'no_rooted_liveness_path')

    def test_owned_operation_requires_unique_owner_to_explain_retention(self):
        self.inventory['gsim']['after_nodes'] = [row for row in self.inventory['gsim']['after_nodes']
                                                   if row['node_id'] != 104]
        for count, explained in ((1, True), (2, False), (None, False)):
            with self.subTest(owner_count=count):
                self.write()
                self.output = self.work / f'owned-operation-{count}'
                start = {'relation': 'start', 'node_id': 4, 'start_kind': 'owned_operation',
                         'entity_kind': 'operation', 'entity_id': 77, 'generation': 0}
                if count is not None:
                    start['owner_count'] = count
                self.add_grh_provenance([
                    {'relation': 'root', 'entity_kind': 'value', 'entity_id': 99, 'generation': 0,
                     'root_kind': 'output_port'},
                    {'relation': 'edge', 'edge_kind': 'value_definition', 'from_kind': 'value',
                     'from_id': 99, 'from_generation': 0, 'to_kind': 'operation', 'to_id': 77,
                     'to_generation': 0, 'slot': 0}, start])
                report = self.analyze()
                self.assertEqual(report['passed'], explained)
                self.assertEqual(self.rows('node-retention-explanations.tsv')[0]['classification'],
                                 'explained' if explained else 'unexplained')

    def test_shared_consumer_ownership_still_proves_exact_boundary_membership(self):
        self.inventory['gsim']['after_nodes'] = [row for row in self.inventory['gsim']['after_nodes']
                                                   if row['node_id'] != 104]
        self.write()
        self.add_grh_provenance([
            {'relation': 'root', 'entity_kind': 'value', 'entity_id': 99, 'generation': 0,
             'root_kind': 'output_port'},
            {'relation': 'edge', 'edge_kind': 'value_definition', 'from_kind': 'value',
             'from_id': 99, 'from_generation': 0, 'to_kind': 'operation', 'to_id': 77,
             'to_generation': 0, 'slot': 0},
            {'relation': 'edge', 'edge_kind': 'operation_operand', 'from_kind': 'operation',
             'from_id': 77, 'from_generation': 0, 'to_kind': 'value', 'to_id': 13,
             'to_generation': 0, 'slot': 2},
            {'relation': 'start', 'node_id': 2, 'start_kind': 'owned_operation',
             'entity_kind': 'operation', 'entity_id': 77, 'generation': 0, 'owner_count': 2},
            {'relation': 'start', 'node_id': 1, 'start_kind': 'owned_operation',
             'entity_kind': 'operation', 'entity_id': 77, 'generation': 0, 'owner_count': 2},
            {'relation': 'start', 'node_id': 4, 'start_kind': 'boundary_use', 'entity_kind': 'operation',
             'entity_id': 77, 'generation': 0,
             'boundary': {'source': 4, 'target': 2, 'value': 13, 'value_generation': 0,
                          'user': 77, 'user_generation': 0, 'operand_index': 2, 'kind': 'data'}}])
        report = self.analyze()
        self.assertTrue(report['passed'], report['issues'])
        self.assertEqual(self.rows('node-retention-explanations.tsv')[0]['proof_kind'],
                         'rooted_boundary_dependency')

    def test_boundary_retention_requires_exact_operand_slot_and_value(self):
        self.inventory['gsim']['after_nodes'] = [row for row in self.inventory['gsim']['after_nodes']
                                                   if row['node_id'] != 104]
        for slot, value, explained in ((2, 13, True), (1, 13, False), (2, 14, False)):
            with self.subTest(slot=slot, value=value):
                self.write()
                self.output = self.work / f'boundary-{slot}-{value}'
                self.add_grh_provenance([
                    {'relation': 'root', 'entity_kind': 'value', 'entity_id': 99, 'generation': 0,
                     'root_kind': 'output_port'},
                    {'relation': 'edge', 'edge_kind': 'value_definition', 'from_kind': 'value',
                     'from_id': 99, 'from_generation': 0, 'to_kind': 'operation', 'to_id': 77,
                     'to_generation': 0, 'slot': 0},
                    {'relation': 'edge', 'edge_kind': 'operation_operand', 'from_kind': 'operation',
                     'from_id': 77, 'from_generation': 0, 'to_kind': 'value', 'to_id': 13,
                     'to_generation': 0, 'slot': 2, 'operand_role': 'clock'},
                    {'relation': 'start', 'node_id': 2, 'start_kind': 'owned_operation',
                     'entity_kind': 'operation', 'entity_id': 77, 'generation': 0, 'owner_count': 1},
                    {'relation': 'start', 'node_id': 4, 'start_kind': 'boundary_use', 'entity_kind': 'operation',
                     'entity_id': 77, 'generation': 0,
                     'boundary': {'source': 4, 'target': 2, 'value': value, 'value_generation': 0,
                                  'user': 77, 'user_generation': 0, 'operand_index': slot, 'kind': 'clock'}}])
                report = self.analyze()
                self.assertEqual(report['passed'], explained)
                expected = 'rooted_boundary_dependency' if explained else 'no_rooted_liveness_path'
                self.assertEqual(self.rows('node-retention-explanations.tsv')[0]['proof_kind'], expected)

    def test_zero_width_binding_is_an_explicit_structural_explanation(self):
        self.inventory['gsim']['after_nodes'] = [row for row in self.inventory['gsim']['after_nodes']
                                                   if row['node_id'] != 104]
        self.write()
        self.add_grh_provenance([{'relation': 'start', 'node_id': 4, 'start_kind': 'zero_width_binding',
            'binding': {'role': 'value', 'source_width': 8, 'shape': [0],
                        'shape_field_depths': [0], 'projection': [-1]}}])
        report = self.analyze()
        self.assertTrue(report['passed'], report['issues'])
        self.assertEqual(self.rows('node-retention-explanations.tsv')[0]['proof_kind'], 'zero_width_binding')

    def test_nonzero_binding_does_not_explain_structural_retention(self):
        self.inventory['gsim']['after_nodes'] = [row for row in self.inventory['gsim']['after_nodes']
                                                   if row['node_id'] != 104]
        self.write()
        self.add_grh_provenance([{'relation': 'start', 'node_id': 4, 'start_kind': 'zero_width_binding',
            'binding': {'role': 'value', 'source_width': 8, 'shape': [2],
                        'shape_field_depths': [0], 'projection': [-1]}}])
        report = self.analyze()
        self.assertFalse(report['passed'])
        self.assertEqual(self.rows('node-retention-explanations.tsv')[0]['proof_kind'],
                         'no_rooted_liveness_path')

    def test_legacy_system_task_clock_reason_does_not_explain_retention(self):
        self.inventory['gsim']['after_nodes'] = [row for row in self.inventory['gsim']['after_nodes']
                                                   if row['node_id'] != 104]
        self.write(liveness_provenance=False)
        write_bundle(self.grh, 'grh', self.inventory['grh'], extra_decisions=(
            (2, 'retain', 'effect:system_task;effect_root_operation=77;effect_root_kind=system_task;'
                'effect_root_operand_count=3;effect_root_clock_operand=2;effect_root_clock_value=13'),
            (4, 'retain', 'demand:system_task;boundary_source=4;boundary_target=2;boundary_value=13;'
                'boundary_user=77;boundary_operand_index=2;boundary_kind=clock')),
            liveness_provenance=False)
        report = self.analyze()
        self.assertTrue(report['complete'])
        self.assertFalse(report['passed'])
        self.assertEqual(report['nodes']['deletion_contract']['unexplained_retention'], 1)
        self.assertEqual(self.rows('node-retention-explanations.tsv')[0]['proof_kind'],
                         'missing_liveness_provenance')

    def test_system_task_clock_requires_exact_rooted_operand_edge(self):
        self.inventory['gsim']['after_nodes'] = [row for row in self.inventory['gsim']['after_nodes']
                                                   if row['node_id'] != 104]
        self.write()
        self.add_grh_provenance([
            {'relation': 'root', 'entity_kind': 'operation', 'entity_id': 77, 'generation': 0,
             'root_kind': 'observable_operation', 'operation_kind': 'grh.systemTask',
             'root_identity': 77, 'root_identity_generation': 0, 'clock_operand': 2},
            {'relation': 'edge', 'edge_kind': 'operation_operand', 'from_kind': 'operation',
             'from_id': 77, 'from_generation': 0, 'to_kind': 'value', 'to_id': 13,
             'to_generation': 0, 'slot': 2, 'operand_role': 'clock'},
            {'relation': 'start', 'node_id': 2, 'start_kind': 'owned_operation',
             'entity_kind': 'operation', 'entity_id': 77, 'generation': 0, 'owner_count': 1},
            {'relation': 'start', 'node_id': 4, 'start_kind': 'boundary_use', 'entity_kind': 'operation',
             'entity_id': 77, 'generation': 0,
             'boundary': {'source': 4, 'target': 2, 'value': 13, 'value_generation': 0,
                          'user': 77, 'user_generation': 0, 'operand_index': 2, 'kind': 'clock'}}])
        report = self.analyze()
        self.assertTrue(report['complete'])
        self.assertTrue(report['passed'], report['issues'])
        proof = json.loads(self.rows('node-retention-explanations.tsv')[0]['evidence_json'])
        self.assertEqual(proof['root']['operation_kind'], 'grh.systemTask')
        self.assertEqual(proof['boundary_operand_edge']['slot'], 2)

        self.output = self.work / 'wrong-system-task-target-owner'
        self.add_grh_provenance([
            {'relation': 'root', 'entity_kind': 'operation', 'entity_id': 77, 'generation': 0,
             'root_kind': 'observable_operation', 'operation_kind': 'grh.systemTask',
             'root_identity': 77, 'root_identity_generation': 0, 'clock_operand': 2},
            {'relation': 'edge', 'edge_kind': 'operation_operand', 'from_kind': 'operation',
             'from_id': 77, 'from_generation': 0, 'to_kind': 'value', 'to_id': 13,
             'to_generation': 0, 'slot': 2, 'operand_role': 'clock'},
            {'relation': 'start', 'node_id': 2, 'start_kind': 'owned_operation',
             'entity_kind': 'operation', 'entity_id': 77, 'generation': 0, 'owner_count': 1},
            {'relation': 'start', 'node_id': 4, 'start_kind': 'boundary_use', 'entity_kind': 'operation',
             'entity_id': 77, 'generation': 0,
             'boundary': {'source': 4, 'target': 6, 'value': 13, 'value_generation': 0,
                          'user': 77, 'user_generation': 0, 'operand_index': 2, 'kind': 'clock'}}])
        report = self.analyze()
        self.assertFalse(report['passed'])
        self.assertEqual(self.rows('node-retention-explanations.tsv')[0]['proof_kind'],
                         'no_rooted_liveness_path')

        self.output = self.work / 'wrong-system-task-operand-slot'
        self.add_grh_provenance([
            {'relation': 'root', 'entity_kind': 'operation', 'entity_id': 77, 'generation': 0,
             'root_kind': 'observable_operation', 'operation_kind': 'grh.systemTask',
             'root_identity': 77, 'root_identity_generation': 0, 'clock_operand': 2},
            {'relation': 'edge', 'edge_kind': 'operation_operand', 'from_kind': 'operation',
             'from_id': 77, 'from_generation': 0, 'to_kind': 'value', 'to_id': 13,
             'to_generation': 0, 'slot': 2, 'operand_role': 'clock'},
            {'relation': 'start', 'node_id': 2, 'start_kind': 'owned_operation',
             'entity_kind': 'operation', 'entity_id': 77, 'generation': 0, 'owner_count': 1},
            {'relation': 'start', 'node_id': 4, 'start_kind': 'boundary_use', 'entity_kind': 'operation',
             'entity_id': 77, 'generation': 0,
             'boundary': {'source': 4, 'target': 2, 'value': 13, 'value_generation': 0,
                          'user': 77, 'user_generation': 0, 'operand_index': 1, 'kind': 'clock'}}])
        report = self.analyze()
        self.assertFalse(report['passed'])
        self.assertEqual(self.rows('node-retention-explanations.tsv')[0]['proof_kind'],
                         'no_rooted_liveness_path')

        self.output = self.work / 'wrong-system-task-clock-value'
        self.add_grh_provenance([
            {'relation': 'root', 'entity_kind': 'operation', 'entity_id': 77, 'generation': 0,
             'root_kind': 'observable_operation', 'operation_kind': 'grh.systemTask',
             'root_identity': 77, 'root_identity_generation': 0, 'clock_operand': 2},
            {'relation': 'edge', 'edge_kind': 'operation_operand', 'from_kind': 'operation',
             'from_id': 77, 'from_generation': 0, 'to_kind': 'value', 'to_id': 14,
             'to_generation': 0, 'slot': 2, 'operand_role': 'clock'},
            {'relation': 'start', 'node_id': 4, 'start_kind': 'boundary_use', 'entity_kind': 'operation',
             'entity_id': 77, 'generation': 0,
             'boundary': {'source': 4, 'target': 2, 'value': 13, 'value_generation': 0,
                          'user': 77, 'user_generation': 0, 'operand_index': 2, 'kind': 'clock'}}])
        report = self.analyze()
        self.assertFalse(report['passed'])
        self.assertEqual(self.rows('node-retention-explanations.tsv')[0]['proof_kind'],
                         'no_rooted_liveness_path')

    def test_legacy_state_clock_reason_does_not_explain_retention(self):
        self.inventory['gsim']['after_nodes'] = [row for row in self.inventory['gsim']['after_nodes']
                                                   if row['node_id'] != 104]
        self.write(liveness_provenance=False)
        write_bundle(self.grh, 'grh', self.inventory['grh'], extra_decisions=(
            (2, 'retain', 'demand:state;active_state_operation=77;'
                'active_state_clock_operand=2;active_state_clock_value=13'),
            (4, 'retain', 'demand:state;boundary_source=4;boundary_target=2;boundary_value=13;'
                'boundary_user=77;boundary_operand_index=2;boundary_kind=clock')),
            liveness_provenance=False)
        report = self.analyze()
        self.assertTrue(report['complete'])
        self.assertFalse(report['passed'])
        self.assertEqual(self.rows('node-retention-explanations.tsv')[0]['proof_kind'],
                         'missing_liveness_provenance')

        self.output = self.work / 'wrong-state-slot-analysis'
        write_bundle(self.grh, 'grh', self.inventory['grh'], extra_decisions=(
            (2, 'retain', 'demand:state;active_state_operation=77;'
                'active_state_clock_operand=1;active_state_clock_value=13'),
            (4, 'retain', 'demand:state;boundary_source=4;boundary_target=2;boundary_value=13;'
                'boundary_user=77;boundary_operand_index=2;boundary_kind=clock')),
            liveness_provenance=False)
        report = self.analyze()
        self.assertTrue(report['complete'])
        self.assertFalse(report['passed'])
        self.assertEqual(self.rows('node-retention-explanations.tsv')[0]['proof_kind'],
                         'missing_liveness_provenance')

    def test_live_state_clock_needs_rooted_state_family_path(self):
        self.inventory['gsim']['after_nodes'] = [row for row in self.inventory['gsim']['after_nodes']
                                                   if row['node_id'] != 104]
        self.write()
        self.add_grh_provenance([
            {'relation': 'root', 'entity_kind': 'value', 'entity_id': 99, 'generation': 0,
             'root_kind': 'output_port'},
            {'relation': 'edge', 'edge_kind': 'value_definition', 'from_kind': 'value',
             'from_id': 99, 'from_generation': 0, 'to_kind': 'operation', 'to_id': 77,
             'to_generation': 0, 'slot': 0},
            {'relation': 'edge', 'edge_kind': 'state_family', 'from_kind': 'operation',
             'from_id': 77, 'from_generation': 0, 'to_kind': 'operation', 'to_id': 88,
             'to_generation': 0, 'slot': None, 'storage_symbol': 'state'},
            {'relation': 'edge', 'edge_kind': 'operation_operand', 'from_kind': 'operation',
             'from_id': 88, 'from_generation': 0, 'to_kind': 'value', 'to_id': 13,
             'to_generation': 0, 'slot': 2, 'operand_role': 'clock'},
            {'relation': 'start', 'node_id': 2, 'start_kind': 'owned_operation',
             'entity_kind': 'operation', 'entity_id': 88, 'generation': 0, 'owner_count': 1},
            {'relation': 'start', 'node_id': 4, 'start_kind': 'boundary_use', 'entity_kind': 'operation',
             'entity_id': 88, 'generation': 0,
             'boundary': {'source': 4, 'target': 2, 'value': 13, 'value_generation': 0,
                          'user': 88, 'user_generation': 0, 'operand_index': 2, 'kind': 'clock'}}])
        report = self.analyze()
        self.assertTrue(report['passed'], report['issues'])
        proof = json.loads(self.rows('node-retention-explanations.tsv')[0]['evidence_json'])
        self.assertEqual(proof['root']['root_kind'], 'output_port')
        self.assertIn('state_family', [item['edge_toward_root']['edge_kind'] for item in proof['path']
                                       if item['edge_toward_root']])

    def test_live_state_clock_can_be_rooted_by_a_different_system_task(self):
        self.inventory['gsim']['after_nodes'] = [row for row in self.inventory['gsim']['after_nodes']
                                                   if row['node_id'] != 104]
        self.write()
        self.add_grh_provenance([
            {'relation': 'root', 'entity_kind': 'operation', 'entity_id': 66, 'generation': 0,
             'root_kind': 'observable_operation', 'operation_kind': 'grh.systemTask',
             'root_identity': 66, 'root_identity_generation': 0, 'clock_operand': 1},
            {'relation': 'edge', 'edge_kind': 'operation_operand', 'from_kind': 'operation',
             'from_id': 66, 'from_generation': 0, 'to_kind': 'value', 'to_id': 99,
             'to_generation': 0, 'slot': 0},
            {'relation': 'edge', 'edge_kind': 'value_definition', 'from_kind': 'value',
             'from_id': 99, 'from_generation': 0, 'to_kind': 'operation', 'to_id': 77,
             'to_generation': 0, 'slot': 0},
            {'relation': 'edge', 'edge_kind': 'state_family', 'from_kind': 'operation',
             'from_id': 77, 'from_generation': 0, 'to_kind': 'operation', 'to_id': 88,
             'to_generation': 0, 'slot': None, 'storage_symbol': 'state'},
            {'relation': 'edge', 'edge_kind': 'operation_operand', 'from_kind': 'operation',
             'from_id': 88, 'from_generation': 0, 'to_kind': 'value', 'to_id': 13,
             'to_generation': 0, 'slot': 2, 'operand_role': 'clock'},
            {'relation': 'start', 'node_id': 2, 'start_kind': 'owned_operation',
             'entity_kind': 'operation', 'entity_id': 88, 'generation': 0, 'owner_count': 1},
            {'relation': 'start', 'node_id': 4, 'start_kind': 'boundary_use', 'entity_kind': 'operation',
             'entity_id': 88, 'generation': 0,
             'boundary': {'source': 4, 'target': 2, 'value': 13, 'value_generation': 0,
                          'user': 88, 'user_generation': 0, 'operand_index': 2, 'kind': 'clock'}}])
        report = self.analyze()
        self.assertTrue(report['passed'], report['issues'])
        proof = json.loads(self.rows('node-retention-explanations.tsv')[0]['evidence_json'])
        self.assertEqual(proof['root']['root_identity'], 66)
        self.assertEqual(proof['start']['boundary']['user'], 88)

    def test_direct_system_task_clock_requires_its_root_clock_slot(self):
        self.inventory['gsim']['after_nodes'] = [row for row in self.inventory['gsim']['after_nodes']
                                                   if row['node_id'] != 104]
        self.write()
        self.add_grh_provenance([
            {'relation': 'root', 'entity_kind': 'operation', 'entity_id': 77, 'generation': 0,
             'root_kind': 'observable_operation', 'operation_kind': 'grh.systemTask',
             'root_identity': 77, 'root_identity_generation': 0, 'clock_operand': 1},
            {'relation': 'edge', 'edge_kind': 'operation_operand', 'from_kind': 'operation',
             'from_id': 77, 'from_generation': 0, 'to_kind': 'value', 'to_id': 13,
             'to_generation': 0, 'slot': 2, 'operand_role': 'clock'},
            {'relation': 'start', 'node_id': 2, 'start_kind': 'owned_operation',
             'entity_kind': 'operation', 'entity_id': 77, 'generation': 0, 'owner_count': 1},
            {'relation': 'start', 'node_id': 4, 'start_kind': 'boundary_use', 'entity_kind': 'operation',
             'entity_id': 77, 'generation': 0,
             'boundary': {'source': 4, 'target': 2, 'value': 13, 'value_generation': 0,
                          'user': 77, 'user_generation': 0, 'operand_index': 2, 'kind': 'clock'}}])
        report = self.analyze()
        self.assertFalse(report['passed'])
        self.assertEqual(self.rows('node-retention-explanations.tsv')[0]['proof_kind'],
                         'no_rooted_liveness_path')

    def test_exact_native_input_port_explains_identity_without_making_a_logic_root(self):
        self.inventory['gsim']['after_nodes'] = [row for row in self.inventory['gsim']['after_nodes']
                                                if row['node_id'] != 104]
        self.write()
        self.add_grh_provenance([{'relation': 'start', 'node_id': 4, 'start_kind': 'input_port',
            'entity_kind': 'value', 'entity_id': 13, 'generation': 4,
            'port_name': 'io__DOT__input', 'port_kind': 'input'}])
        report = self.analyze()
        self.assertTrue(report['passed'], report['issues'])
        row = self.rows('node-retention-explanations.tsv')[0]
        self.assertEqual(row['proof_kind'], 'exact_input_port_identity')
        self.assertEqual(json.loads(row['evidence_json'])['start']['port_name'], 'io__DOT__input')

    def test_shared_residual_requires_complete_group_and_an_actual_rooted_operation(self):
        self.inventory['gsim']['after_nodes'] = [row for row in self.inventory['gsim']['after_nodes']
                                                if row['node_id'] != 104]
        self.write()
        decisions = tuple((owner, 'retain', 'residual:uncovered_live_operation') for owner in (2, 4))
        write_bundle(self.grh, 'grh', self.inventory['grh'], extra_decisions=decisions)
        root = {'relation': 'root', 'entity_kind': 'value', 'entity_id': 90,
                'generation': 0, 'root_kind': 'output_port'}
        edge = {'relation': 'edge', 'edge_kind': 'value_definition', 'from_kind': 'value',
                'from_id': 90, 'from_generation': 0, 'to_kind': 'operation', 'to_id': 77,
                'to_generation': 4, 'slot': 0}
        starts = [{'relation': 'start', 'node_id': owner, 'start_kind': 'owned_operation',
                   'entity_kind': 'operation', 'entity_id': 77, 'generation': 4, 'owner_count': 2}
                  for owner in (2, 4)]
        group = {'relation': 'residual', 'entity_kind': 'operation', 'entity_id': 77, 'generation': 4,
                 'owner_ids': [2, 4], 'ordinary_retained_owner_count': 0,
                 'retention_rule': 'preserve_original_owner_set'}
        self.add_grh_provenance([root, edge, *starts, group])
        report = self.analyze()
        self.assertTrue(report['passed'], report['issues'])
        row = self.rows('node-retention-explanations.tsv')[0]
        self.assertEqual(row['proof_kind'], 'rooted_residual_owner_group')
        self.assertEqual(json.loads(row['evidence_json'])['residual_group']['owner_ids'], [2, 4])
        for name, records in (('no-root', [edge, *starts, group]),
                              ('no-group', [root, edge, *starts]),
                              ('wrong-generation-path', [root, {**edge, 'to_generation': 3}, *starts, group])):
            with self.subTest(name=name):
                self.output = self.work / name
                self.add_grh_provenance(records)
                report = self.analyze()
                self.assertFalse(report['passed'])
                self.assertEqual(self.rows('node-retention-explanations.tsv')[0]['classification'], 'unexplained')

    def test_rooted_liveness_memo_reuses_shared_deep_chain(self):
        with sqlite3.connect(':memory:') as db:
            db.execute("ATTACH DATABASE ':memory:' AS grh")
            db.execute('''CREATE TABLE grh.liveness_provenance(
                id INTEGER PRIMARY KEY,relation TEXT,detail_json TEXT,to_kind TEXT,to_id INTEGER,to_generation INTEGER)''')
            chain = [('value' if index % 2 == 0 else 'operation', 100 + index, 0)
                     for index in range(128)]
            leaves = [('value', 1000, 0), ('value', 1001, 0)]
            for parent, child in list(zip(chain, chain[1:])) + [(chain[-1], leaf) for leaf in leaves]:
                detail = {'relation': 'edge', 'edge_kind': 'operation_operand' if parent[0] == 'operation'
                          else 'value_definition', 'from_kind': parent[0], 'from_id': parent[1],
                          'from_generation': 0, 'to_kind': child[0], 'to_id': child[1],
                          'to_generation': 0, 'slot': 0}
                db.execute('INSERT INTO grh.liveness_provenance VALUES(NULL,?,?,?,?,?)',
                           ('edge', compact(detail), *child))
            context = {'roots': {chain[0]: {'root_kind': 'output_port'}}}
            queries = []
            db.set_trace_callback(lambda statement: queries.append(statement)
                                  if 'SELECT detail_json' in statement else None)
            first = analysis.rooted_liveness_path(db, leaves[0], context)
            self.assertEqual(first[0], [leaves[0], *reversed(chain)])
            first_queries = len(queries)
            second = analysis.rooted_liveness_path(db, leaves[1], context)
            self.assertEqual(second[0], [leaves[1], *reversed(chain)])
            self.assertEqual(len(queries) - first_queries, 1)
            analysis.rooted_liveness_path(db, leaves[0], context)
            self.assertEqual(len(queries) - first_queries, 1)
            self.assertFalse(context['unrooted_entities'])

    def test_rooted_liveness_memo_handles_multiple_roots_cycles_and_disconnected_cones(self):
        with sqlite3.connect(':memory:') as db:
            db.execute("ATTACH DATABASE ':memory:' AS grh")
            db.execute('''CREATE TABLE grh.liveness_provenance(
                id INTEGER PRIMARY KEY,relation TEXT,detail_json TEXT,to_kind TEXT,to_id INTEGER,to_generation INTEGER)''')
            first_root, second_root = ('value', 1, 0), ('value', 2, 0)
            target, cycle, branch = ('value', 3, 0), ('operation', 4, 0), ('operation', 5, 0)
            disconnected = (('value', 6, 0), ('operation', 7, 0))
            other = ('operation', 8, 0)
            links = [(branch, target), (cycle, target), (target, cycle), (first_root, cycle),
                     (disconnected[0], disconnected[1]), (disconnected[1], disconnected[0]),
                     (second_root, other)]
            for parent, child in links:
                detail = {'relation': 'edge', 'edge_kind': 'operation_operand' if parent[0] == 'operation'
                          else 'value_definition', 'from_kind': parent[0], 'from_id': parent[1],
                          'from_generation': 0, 'to_kind': child[0], 'to_id': child[1],
                          'to_generation': 0, 'slot': 0}
                db.execute('INSERT INTO grh.liveness_provenance VALUES(NULL,?,?,?,?,?)',
                           ('edge', compact(detail), *child))
            context = {'roots': {first_root: {}, second_root: {}}}
            self.assertEqual(analysis.rooted_liveness_path(db, target, context)[0],
                             [target, cycle, first_root])
            self.assertFalse(context['unrooted_entities'])
            self.assertNotIn(branch, context['rooted_predecessors'])
            self.assertIsNone(analysis.rooted_liveness_path(db, disconnected[0], context))
            self.assertEqual(context['unrooted_entities'], set(disconnected))
            queries = []
            db.set_trace_callback(queries.append)
            self.assertIsNone(analysis.rooted_liveness_path(db, disconnected[1], context))
            self.assertFalse(queries)
            self.assertEqual(analysis.rooted_liveness_path(db, other, context)[0], [other, second_root])
            context['rooted_predecessors'][target] = (cycle, {})
            context['rooted_predecessors'][cycle] = (target, {})
            with self.assertRaisesRegex(ValueError, 'cycle in cached DCE rooted liveness path'):
                analysis.rooted_liveness_path(db, target, context)

    def test_grh_snapshot_can_use_verified_evolution_header_identity(self):
        for phase in ('before', 'after'):
            for table in ('nodes', 'connections'):
                path = self.grh / f'{phase}.{table}.tsv'
                lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
                metadata = json.loads(lines[0][len('#meta\t'):])
                metadata.pop('root_name')
                metadata.pop('input_sha256')
                lines[0] = '#meta\t' + compact(metadata) + '\n'
                path.write_text(''.join(lines), encoding='utf-8')
        report = self.analyze()
        self.assertTrue(report['complete'])
        self.assertTrue(report['passed'], report['issues'])

    def test_grh_snapshot_optional_root_must_match_verified_evolution_header(self):
        path = self.grh / 'before.nodes.tsv'
        lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
        metadata = json.loads(lines[0][len('#meta\t'):])
        metadata['root_name'] = 'other-top'
        lines[0] = '#meta\t' + compact(metadata) + '\n'
        path.write_text(''.join(lines), encoding='utf-8')
        self.assert_rejected()

    def test_pass_scope_delete_decisions_supply_specific_reasons(self):
        self.write(generic=True)
        report = self.analyze()
        self.assertTrue(report['passed'], report['issues'])
        rows = self.rows('node-deletion-matrix.tsv')
        facts = json.loads(next(row for row in rows if row['grh_node_id'] == '3')['grh_evidence_json'])
        self.assertTrue(any(row.get('detail', {}).get('outcome') == 'delete' for row in facts))

    def test_reason_counts_use_fixed_mapping_sorted_lifecycle_sets_and_preserve_full_evidence(self):
        write_bundle(self.grh, 'grh', self.inventory['grh'], extra_decisions=(
            (1, 'retain', 'root:port;anchor_value=42;operation=7'),
            (1, 'retain', 'demand:output;demanded_by_operation=9'),
            (1, 'retain', 'root:port;operation=8'),
            (3, 'delete', 'no_observable_demand;anchor_value=35'),
            (2, 'replace', 'array_update_internal_rewrite'),
            (8, 'retain', 'unmatched_grh_rule')))
        write_bundle(self.gsim, 'gsim', self.inventory['gsim'], extra_decisions=(
            (101, 'retain', 'observable_output_root'), (108, 'retain', 'unmatched_gsim_rule')))
        report = self.analyze()
        counts = report['nodes']['native_reason_label_counts']
        self.assertEqual(sum(row['nodes'] for row in counts), report['nodes']['before_candidates'])
        expected = {'category': 'both_retained', 'grh_reason_labels': ['demand:output', 'root:port'],
                    'gsim_reason_labels': ['observable_output_root'], 'nodes': 1}
        self.assertIn(expected, counts)
        self.assertIn({'category': 'both_retained', 'grh_reason_labels': [],
                       'gsim_reason_labels': [], 'nodes': 4}, counts)
        self.assertIn({'category': 'both_deleted', 'grh_reason_labels': ['dead_owner_anchor', 'no_observable_demand'],
                       'gsim_reason_labels': ['no_observable_demand'], 'nodes': 1}, counts)
        self.assertNotIn('unmatched_', compact(counts))
        self.assertNotIn('array_update_internal_rewrite', compact(counts))
        self.assertIn('no native lifecycle decision supplied', report['nodes']['native_reason_label_scope']['empty_labels'])
        rows = self.rows('node-deletion-reason-counts.tsv')
        self.assertEqual(sum(int(row['node_count']) for row in rows), 7)
        self.assertTrue(all(row['evidence_scope'] == 'native_rule_labels_only_no_equivalence_claim' for row in rows))
        matrix = self.rows('node-deletion-matrix.tsv')
        native = json.loads(next(row['grh_evidence_json'] for row in matrix if row['grh_node_id'] == '1'))
        self.assertTrue(any(row['reason'] == 'root:port;anchor_value=42;operation=7' for row in native))

    def test_streamed_connection_evidence_preserves_record_order_and_json_types(self):
        with sqlite3.connect(':memory:') as db:
            db.execute('''CREATE TABLE edits(engine TEXT,subject TEXT,id INTEGER,seq INTEGER,
                ordinal INTEGER,side TEXT,action TEXT,reason TEXT)''')
            db.executemany('INSERT INTO edits VALUES(?,?,?,?,?,?,?,?)', (
                ('grh', 'connection', 4, 3, 9, 'after', 'add', 'later'),
                ('grh', 'connection', 4, 1, 4, 'before', 'replace', 'first\t\\n行'),
                ('grh', 'connection', 4, 1, 5, 'after', 'replace', 'second'),
                ('grh', 'node', 4, 0, 0, 'before', 'delete', 'not_a_connection'),
                ('gsim', 'connection', 4, 0, 0, 'before', 'delete', 'other_engine')))
            payload = db.execute('SELECT ' + analysis.connection_evidence_sql('grh', '4')).fetchone()[0]
            expected = [{'record': 'edit', 'seq': seq, 'ordinal': ordinal, 'side': side,
                         'action': action, 'reason': reason}
                        for seq, ordinal, side, action, reason in ((1, 4, 'before', 'replace', 'first\t\\n行'),
                            (1, 5, 'after', 'replace', 'second'), (3, 9, 'after', 'add', 'later'))]
            self.assertEqual(payload, compact(expected))
            self.assertEqual(db.execute('SELECT ' + analysis.connection_evidence_sql('grh', '999')).fetchone()[0], '[]')

    def test_generic_reason_without_delete_facts_is_explicit_failed_gate(self):
        self.write(generic=True, decisions=False)
        report = self.analyze()
        self.assertTrue(report['complete'])
        self.assertFalse(report['passed'])
        self.assertEqual(sum(issue['nodes'] for issue in report['issues'] if issue['kind'] == 'generic_deletion_reason'), 4)

    def test_dce_retain_decision_cannot_describe_a_deleted_node(self):
        for engine in ('grh', 'gsim'):
            with self.subTest(engine=engine):
                self.write()
                path = (self.grh if engine == 'grh' else self.gsim) / 'evolution.tsv'
                lines = path.read_text().splitlines(keepends=True)
                columns = HEADERS['evolution']
                record_column, detail_column = columns.index('record'), columns.index('detail_json')
                for index, line in enumerate(lines):
                    fields = line.rstrip('\n').split('\t')
                    if fields[record_column] != 'decision':
                        continue
                    detail = json.loads(decode_cell(fields[detail_column]))
                    if detail.get('outcome') != 'delete':
                        continue
                    detail['outcome'] = 'retain'
                    if engine == 'grh':
                        detail.pop('dce_deletion', None)
                    fields[detail_column] = encode_cell(compact(detail))
                    lines[index] = '\t'.join(fields) + '\n'
                    break
                path.write_text(''.join(lines))
                with self.assertRaisesRegex(ValueError, 'retain decision refers to a deleted Node'):
                    self.analyze()
                self.assertFalse(any(self.output.glob('*.tsv')))
                shutil.rmtree(self.output)

    def test_surviving_native_name_change_is_rejected(self):
        self.inventory['grh']['after_nodes'] = deepcopy(self.inventory['grh']['after_nodes'])
        self.inventory['grh']['after_nodes'][0]['native_name'] = 'renamed'
        self.write()
        self.assert_rejected()

    def test_surviving_path_tokens_cannot_be_reguessed_by_normalized_name(self):
        self.inventory['grh']['after_nodes'] = deepcopy(self.inventory['grh']['after_nodes'])
        self.inventory['grh']['after_nodes'][0]['name_path_json'] = ['top', 'in']
        self.write()
        self.assert_rejected()

    def test_new_same_name_node_cannot_replace_deleted_original_identity(self):
        self.inventory['grh']['after_nodes'].append(node(50, 'top.dead'))
        self.write()
        self.assert_rejected()

    def test_real_after_body_must_match_complete_native_replay(self):
        path = self.grh / 'after.connections.tsv'
        path.write_text(path.read_text().replace('\tstate_update\t', '\tstorage_write\t'), encoding='utf-8')
        self.assert_rejected()

    def test_preparation_must_keep_original_ids_names_and_path_tokens(self):
        self.s0_nodes = deepcopy(self.s0_nodes)
        self.s0_nodes[5]['native_name'] = 'different_original'
        self.write_preparation()
        self.assert_rejected()

    def test_preparation_after_must_equal_actual_dce_before(self):
        different = deepcopy(self.inventory['gsim']['before_edges'])
        different[0]['kind'] = 'external_binding'
        snapshot(self.prep, 'after', self.s0_nodes, different, identity('gsim', 'preparation'), 'prep-after')
        self.assert_rejected()

    def test_independent_sessions_bridge_semantic_edges_with_local_connection_ids(self):
        for phase, edges in (('before', self.s0_edges), ('after', self.inventory['gsim']['before_edges'])):
            renumbered = [{**row, 'connection_id': row['connection_id'] + 1000} for row in edges]
            snapshot(self.prep, phase, self.s0_nodes, renumbered,
                     identity('gsim', 'preparation'), 'prep-' + phase)
        split = self.work / 'independent-split'
        renumbered = [{**row, 'connection_id': row['connection_id'] + 2000} for row in self.s0_edges]
        write_bundle(split, 'gsim', {'before_nodes': self.s0_nodes, 'after_nodes': self.s0_nodes,
            'before_edges': renumbered, 'after_edges': renumbered}, split=True)
        report = self.analyze(gsim_split_bundle=split)
        self.assertTrue(report['passed'], report['issues'])
        self.assertEqual(report['connections']['preparation_all_nodes']['removed'], 1)
        self.assertIn('session-local', report['scope']['cross_session_bridge'])

    def test_different_input_or_wrong_dce_instance_is_rejected(self):
        for variant in ('digest', 'instance'):
            with self.subTest(variant=variant):
                write_bundle(self.gsim, 'gsim', self.inventory['gsim'],
                    **({'digest': 'b' * 64} if variant == 'digest' else {'instance': 'RemoveDeadNodes#1'}))
                self.output = self.work / (variant + '-analysis')
                self.assert_rejected()

    def test_unresolved_candidates_outside_mapping_remain_in_report(self):
        for phase in ('before_edges', 'after_edges'):
            self.inventory['grh'][phase].append(edge(50, None, 2, candidates=[8], reason='unmatched_native_source'))
        self.write()
        report = self.analyze()
        self.assertTrue(report['passed'])
        self.assertEqual(report['connection_scope']['g1']['source_or_candidates_outside_common_survivors_unresolved'], 1)
        rows = self.rows('connection-differences.tsv')
        excluded = [row for row in rows if row['phase'] == 'G1' and row['connection_id'] == '50']
        self.assertEqual(len(excluded), 1)
        self.assertEqual(json.loads(excluded[0]['body_json'])['candidate_sources_json'], [8])

    def test_deleted_unresolved_candidate_is_an_incident_endpoint(self):
        self.inventory['grh']['before_edges'].append(edge(50, None, 2, candidates=[3], reason='native_candidates'))
        self.write()
        report = self.analyze()
        self.assertTrue(report['passed'])
        row = next(row for row in self.rows('connection-differences.tsv')
                   if row['comparison'] == 'within_engine_dce' and row['connection_id'] == '50')
        self.assertEqual(row['category'], 'removed_incident_to_deleted_node')

    def test_new_dce_connection_is_linked_to_native_event_but_requires_review(self):
        self.inventory['grh']['after_edges'].append(edge(50, 7, 2, 'external_binding'))
        self.write()
        report = self.analyze()
        self.assertTrue(report['complete'])
        self.assertFalse(report['passed'])
        self.assertTrue(any(issue['kind'] == 'new_dce_connections_require_semantic_review' for issue in report['issues']))
        rows = self.rows('attribution.tsv')
        addition = next(row for row in rows if row['comparison'] == 'within_engine_dce'
                        and row['engine'] == 'grh' and row['object_id'] == '50')
        self.assertEqual(addition['evidence_status'], 'requires_semantic_review')
        self.assertTrue(json.loads(addition['evidence_json']))
        cross_addition = next(row for row in rows if row['comparison'] == 'cross_engine'
                              and row['engine'] == 'grh' and row['object_id'] == '50')
        self.assertEqual(cross_addition['evidence_status'], 'requires_semantic_review')

    def test_candidate_prune_transition_evidence_classifies_within_and_cross_engine_additions(self):
        old = edge(50, None, 2, candidates=[3, 6], reason='ambiguous_candidate')
        new = edge(51, None, 2, candidates=[6], reason='ambiguous_candidate')
        self.inventory['grh']['before_edges'].append(old)
        self.inventory['grh']['after_edges'].append(new)
        transition = {'connection_id': 51, 'detail': {
            'phase': 'pass-transition', 'cause': 'candidate_pruned_by_node_deletion',
            'event_sequence': 1, 'source_connection_id': 50, 'deleted_node_ids': [3]}}
        self.write(grh_transition_evidence=[transition])
        report = self.analyze()
        self.assertTrue(report['complete'])
        self.assertTrue(report['passed'], report['issues'])
        self.assertEqual(report['connections']['dce_changes']['grh']['introduced_by_dce_candidate_prune'], 1)
        self.assertEqual(report['connections']['after_difference_origins']['introduced_by_dce_candidate_prune'], 1)

        evidence_rows = self.rows('attribution.tsv')
        for comparison in ('within_engine_dce', 'cross_engine'):
            row = next(item for item in evidence_rows if item['comparison'] == comparison and
                       item['engine'] == 'grh' and item['object_id'] == '51')
            self.assertEqual(row['category'], 'introduced_by_dce_candidate_prune')
            self.assertEqual(row['evidence_status'], 'native_transition_evidence')
            evidence = json.loads(row['evidence_json'])['native_transition_evidence']
            self.assertEqual(evidence['source_connection_id'], 50)
            self.assertEqual(evidence['deleted_node_ids'], [3])

    def set_boundary_retirement_fixture(self, *, zero_step=False, candidates=None):
        self.inventory['grh']['after_edges'] = [item for item in self.inventory['grh']['after_edges']
                                                 if item['connection_id'] != 51]
        self.inventory['grh']['after_edges'].append(edge(51, 7 if candidates is None else None, 2,
            candidates=candidates, reason=None if candidates is None else 'ambiguous-native-boundary'))
        boundary = {'boundary_id': 1, 'source_node_id': 3, 'target_node_id': 2,
                    'value_id': 10, 'value_generation': 0, 'operation_id': 31,
                    'operation_generation': 0, 'operand_index': 2, 'boundary_kind': 'data'}
        witness = {'phase': 'postpass-native-walk', 'connection_id': 51, 'witness_kind': 'fallback_value_owner',
                   'supporting_node_id': 7, 'value_id': 11, 'value_generation': 0,
                   'operation_id': 21, 'operation_generation': 0, 'operand_index': 0}
        transition = {'connection_id': 51, 'detail': {
            'phase': 'pass-transition', 'cause': 'dependency_exposed_by_boundary_retirement',
            'event_sequence': 1, 'source_connection_id': 6, 'boundary_id': 1, 'supporting_node_id': 7,
            'start_context': {'operation_id': 31, 'operation_generation': 0, 'operand_index': 2},
            'path': [{'value_id': 10, 'value_generation': 0, 'definition_operation_id': 21,
                      'definition_operation_generation': 0, 'operand_index': 0,
                      'operand_value_id': 11, 'operand_value_generation': 0}]}}
        witnesses = [witness]
        if zero_step:
            boundary.update(value_generation=7, operation_generation=4)
            transition['detail']['start_context']['operation_generation'] = 4
            transition['detail']['path'] = []
            witnesses = [{**witness, 'supporting_node_id': source, 'value_id': 10,
                          'value_generation': 7, 'operation_id': 31,
                          'operation_generation': 4, 'operand_index': 2}
                         for source in ([7] if candidates is None else candidates)]
        self.write(grh_transition_evidence=[transition], grh_boundary_retirements=[boundary],
                   grh_connection_evidence=witnesses)
        return boundary, transition, witnesses

    def test_boundary_retirement_classifies_only_with_exact_native_causal_path(self):
        self.set_boundary_retirement_fixture()
        report = self.analyze()
        self.assertTrue(report['passed'], report['issues'])
        category = 'introduced_by_dce_boundary_retirement'
        self.assertEqual(report['connections']['dce_changes']['grh'][category], 1)
        self.assertEqual(report['connections']['after_difference_origins'][category], 1)
        for comparison in ('within_engine_dce', 'cross_engine'):
            row = next(item for item in self.rows('attribution.tsv') if item['comparison'] == comparison and
                       item['engine'] == 'grh' and item['object_id'] == '51')
            self.assertEqual(row['category'], category)
            self.assertEqual(row['evidence_status'], 'native_transition_evidence')
            evidence = json.loads(row['evidence_json'])['native_transition_evidence']
            self.assertEqual(evidence['boundary_id'], 1)
            self.assertEqual(evidence['path'][0]['operand_value_id'], 11)

    def test_zero_step_boundary_retirement_classifies_resolved_and_complete_candidate_edges(self):
        for candidates in (None, [6, 7]):
            with self.subTest(candidates=candidates):
                self.output = self.work / ('zero-step-resolved' if candidates is None else 'zero-step-candidates')
                self.set_boundary_retirement_fixture(zero_step=True, candidates=candidates)
                report = self.analyze()
                self.assertTrue(report['passed'], report['issues'])
                category = 'introduced_by_dce_boundary_retirement'
                self.assertEqual(report['connections']['dce_changes']['grh'][category], 1)
                self.assertEqual(report['connections']['after_difference_origins'][category], 1)
                for comparison in ('within_engine_dce', 'cross_engine'):
                    row = next(item for item in self.rows('attribution.tsv') if item['comparison'] == comparison and
                               item['engine'] == 'grh' and item['object_id'] == '51')
                    self.assertEqual(row['category'], category)
                    evidence = json.loads(row['evidence_json'])['native_transition_evidence']
                    self.assertEqual(evidence['path'], [])
                    self.assertEqual(evidence['start_context'],
                                     {'operation_id': 31, 'operation_generation': 4, 'operand_index': 2})

    def test_zero_step_boundary_retirement_rejects_unproven_candidate_before_attribution(self):
        boundary, transition, witnesses = self.set_boundary_retirement_fixture(zero_step=True, candidates=[6, 7])
        witnesses[-1]['value_generation'] = 8
        self.write(grh_transition_evidence=[transition], grh_boundary_retirements=[boundary],
                   grh_connection_evidence=witnesses)
        self.assert_rejected()

    def set_pruned_dependency_fixture(self, engine, *, candidates=None):
        offset = 0 if engine == 'grh' else 100
        identifier = offset + 7
        old = next(row for row in self.inventory[engine]['before_edges'] if row['connection_id'] == identifier)
        if candidates is not None:
            old.update(source_node_id=None, resolution='unresolved', candidate_sources_json=candidates,
                       reason='ambiguous_native_boundary')
        self.inventory[engine]['after_edges'] = [row for row in self.inventory[engine]['after_edges']
                                                  if row['connection_id'] != identifier]
        mutation = {'action': 'replace', 'reason': 'undemanded_operand_defined_zero', 'operation_id': 21,
            'detail': {'mutation_id': 1, 'pass': 'dead-code-elim' if engine == 'grh' else 'removeDeadNodes',
                'operation_generation': 4, 'owner_node_ids': [offset + 2],
                'before_slot': 0, 'before_value_id': 10, 'before_value_generation': 7,
                'after_slot': 0, 'after_value_id': 11, 'after_value_generation': 0}}
        evidence = [{'cause': 'pruned_operand_boundary', 'connection_id': identifier, 'mutation_id': 1,
            'source_node_id': source, 'target_node_id': offset + 2, 'value_id': 10, 'value_generation': 7,
            'operation_id': 21, 'operation_generation': 4, 'operand_index': 0, 'boundary_kind': 'data'}
            for source in ([offset + 6] if candidates is None else candidates)]
        return mutation, evidence

    def test_removed_surviving_dependency_requires_native_causality_in_each_engine(self):
        original = deepcopy(self.inventory)
        for engine in ('grh', 'gsim'):
            with self.subTest(engine=engine):
                self.inventory = deepcopy(original)
                self.output = self.work / ('unexplained-removal-' + engine)
                self.set_pruned_dependency_fixture(engine)
                self.write()
                report = self.analyze()
                self.assertTrue(report['complete'])
                self.assertFalse(report['passed'])
                self.assertEqual(report['connections']['dce_changes'][engine]['removed_requires_semantic_review'], 1)
                self.assertIn({'kind': 'removed_dce_connections_require_semantic_review', 'engine': engine,
                               'connections': 1}, report['issues'])
                row = next(item for item in self.rows('attribution.tsv') if item['comparison'] == 'within_engine_dce'
                           and item['engine'] == engine and item['object_id'] == ('7' if engine == 'grh' else '107'))
                self.assertEqual(row['category'], 'removed_between_surviving_endpoints')
                self.assertEqual(row['evidence_status'], 'requires_semantic_review')

    def test_exact_pruned_operand_boundary_explains_removed_surviving_dependency(self):
        original = deepcopy(self.inventory)
        for engine in ('grh', 'gsim'):
            with self.subTest(engine=engine):
                self.inventory = deepcopy(original)
                self.output = self.work / ('proven-removal-' + engine)
                mutation, evidence = self.set_pruned_dependency_fixture(engine)
                self.write(**{engine + '_operand_mutations': [mutation], engine + '_removal_evidence': evidence})
                report = self.analyze()
                self.assertTrue(report['passed'], report['issues'])
                self.assertEqual(report['connections']['dce_changes'][engine]['removed_by_dce_operand_pruning'], 1)
                self.assertNotIn('removed_requires_semantic_review', report['connections']['dce_changes'][engine])
                row = next(item for item in self.rows('attribution.tsv') if item['comparison'] == 'within_engine_dce'
                           and item['engine'] == engine and item['object_id'] == ('7' if engine == 'grh' else '107'))
                self.assertEqual(row['category'], 'removed_by_dce_operand_pruning')
                self.assertEqual(row['evidence_status'], 'native_removal_evidence')
                self.assertEqual(json.loads(row['evidence_json'])['native_removal_evidence'], evidence)

    def test_pruned_candidate_edge_requires_native_support_for_every_surviving_source(self):
        mutation, evidence = self.set_pruned_dependency_fixture('grh', candidates=[1, 7])
        self.write(grh_operand_mutations=[mutation], grh_removal_evidence=evidence)
        report = self.analyze()
        self.assertTrue(report['passed'], report['issues'])
        self.assertEqual(report['connections']['dce_changes']['grh']['removed_by_dce_operand_pruning'], 1)
        self.output = self.work / 'incomplete-removal-candidates'
        self.write(grh_operand_mutations=[mutation], grh_removal_evidence=evidence[:1])
        self.assert_rejected()

    def test_inexact_pruned_operand_evidence_is_rejected_before_attribution(self):
        mutation, evidence = self.set_pruned_dependency_fixture('grh')
        evidence[0]['value_generation'] += 1
        self.write(grh_operand_mutations=[mutation], grh_removal_evidence=evidence)
        self.assert_rejected()

    def test_deleted_endpoint_dependency_needs_no_surviving_edge_removal_claim(self):
        report = self.analyze()
        self.assertTrue(report['passed'], report['issues'])
        for engine in ('grh', 'gsim'):
            self.assertEqual(report['connections']['dce_changes'][engine]['removed_incident_to_deleted_node'], 1)
            self.assertNotIn('removed_requires_semantic_review', report['connections']['dce_changes'][engine])

    @staticmethod
    def set_operand_support_fields(evidence, support):
        for item in evidence:
            item.update(support_kind='boundary_use', reference_target_node_id=item['target_node_id'],
                reference_operation_id=0, reference_operation_generation=0, reference_operand_index=None,
                value_definition_operation_id=31, value_definition_operation_generation=9)
            if support == 'selected_read':
                item.update(reference_operation_id=31, reference_operation_generation=9)
            elif support.startswith('fallback'):
                item.update(support_kind='fallback_value_owner', boundary_kind=None, reference_target_node_id=0)
                if support == 'fallback_input':
                    item.update(value_definition_operation_id=0, value_definition_operation_generation=0)

    def test_named_selected_and_fallback_native_support_explains_removal_in_each_engine(self):
        original = deepcopy(self.inventory)
        for engine in ('grh', 'gsim'):
            for support in ('named', 'selected_read', 'fallback_input', 'fallback_defined'):
                with self.subTest(engine=engine, support=support):
                    self.inventory = deepcopy(original)
                    self.output = self.work / ('native-support-' + engine + '-' + support)
                    mutation, evidence = self.set_pruned_dependency_fixture(engine)
                    self.set_operand_support_fields(evidence, support)
                    self.write(**{engine + '_operand_mutations': [mutation], engine + '_removal_evidence': evidence})
                    report = self.analyze()
                    self.assertTrue(report['passed'], report['issues'])
                    self.assertEqual(report['connections']['dce_changes'][engine]['removed_by_dce_operand_pruning'], 1)
                    row = next(item for item in self.rows('attribution.tsv') if item['comparison'] == 'within_engine_dce'
                               and item['engine'] == engine and item['object_id'] == ('7' if engine == 'grh' else '107'))
                    self.assertEqual(row['evidence_status'], 'native_removal_evidence')
                    self.assertEqual(json.loads(row['evidence_json'])['native_removal_evidence'], evidence)

    def test_native_support_requires_every_original_candidate_before_attribution(self):
        mutation, evidence = self.set_pruned_dependency_fixture('grh', candidates=[1, 7])
        self.set_operand_support_fields(evidence[:1], 'named')
        self.set_operand_support_fields(evidence[1:], 'fallback_defined')
        self.write(grh_operand_mutations=[mutation], grh_removal_evidence=evidence)
        report = self.analyze()
        self.assertTrue(report['passed'], report['issues'])
        self.output = self.work / 'native-support-missing-candidate'
        self.write(grh_operand_mutations=[mutation], grh_removal_evidence=evidence[:1])
        self.assert_rejected()

    def test_native_support_cannot_bypass_unexplained_surviving_edge_removal_gate(self):
        mutation, evidence = self.set_pruned_dependency_fixture('grh')
        self.set_operand_support_fields(evidence, 'fallback_defined')
        self.inventory['grh']['before_edges'].append(edge(50, 7, 6))
        self.write(grh_operand_mutations=[mutation], grh_removal_evidence=evidence)
        report = self.analyze()
        self.assertFalse(report['passed'])
        self.assertEqual(report['connections']['dce_changes']['grh']['removed_by_dce_operand_pruning'], 1)
        self.assertEqual(report['connections']['dce_changes']['grh']['removed_requires_semantic_review'], 1)
        self.assertIn({'kind': 'removed_dce_connections_require_semantic_review', 'engine': 'grh',
                       'connections': 1}, report['issues'])

    def test_native_support_reference_and_actual_mutation_corruption_is_rejected_before_attribution(self):
        for field in ('reference_operation_generation', 'value_generation'):
            with self.subTest(field=field):
                self.output = self.work / ('native-support-corrupt-' + field)
                mutation, evidence = self.set_pruned_dependency_fixture('grh')
                self.set_operand_support_fields(evidence, 'selected_read')
                evidence[0][field] += 1
                self.write(grh_operand_mutations=[mutation], grh_removal_evidence=evidence)
                self.assert_rejected()

    @staticmethod
    def set_operand_path_fields(evidence, *, support='exact', hops=2):
        for item in evidence:
            item.update(support_kind='boundary_use', reference_target_node_id=item['target_node_id'],
                reference_operation_id=0, reference_operation_generation=0, reference_operand_index=None,
                value_definition_operation_id=51, value_definition_operation_generation=3,
                path=[{'value_id': 10, 'value_generation': 7, 'definition_operation_id': 31,
                       'definition_operation_generation': 9, 'operand_index': 1,
                       'operand_value_id': 12, 'operand_value_generation': 8},
                      {'value_id': 12, 'value_generation': 8, 'definition_operation_id': 41,
                       'definition_operation_generation': 6, 'operand_index': 2,
                       'operand_value_id': 14, 'operand_value_generation': 5}][:hops])
            terminal = item['path'][-1]
            if support == 'exact':
                item.update(reference_operation_id=terminal['definition_operation_id'],
                    reference_operation_generation=terminal['definition_operation_generation'],
                    reference_operand_index=terminal['operand_index'])
            elif support == 'selected_read':
                item.update(reference_operation_id=51, reference_operation_generation=3)
            elif support.startswith('fallback'):
                item.update(support_kind='fallback_value_owner', boundary_kind=None, reference_target_node_id=0)
                if support == 'fallback_input':
                    item.update(value_definition_operation_id=0, value_definition_operation_generation=0)

    def test_transitive_native_support_explains_removal_in_each_engine(self):
        original = deepcopy(self.inventory)
        for engine in ('grh', 'gsim'):
            with self.subTest(engine=engine):
                self.inventory = deepcopy(original)
                self.output = self.work / ('transitive-support-' + engine)
                mutation, evidence = self.set_pruned_dependency_fixture(engine)
                self.set_operand_path_fields(evidence)
                self.write(**{engine + '_operand_mutations': [mutation], engine + '_removal_evidence': evidence})
                report = self.analyze()
                self.assertTrue(report['passed'], report['issues'])
                self.assertEqual(report['verification'][engine]['header']['connection_removal_trace'],
                                 'pruned-operand-support.v2')
                self.assertEqual(report['connections']['dce_changes'][engine]['removed_by_dce_operand_pruning'], 1)
                self.assertNotIn('removed_requires_semantic_review', report['connections']['dce_changes'][engine])
                row = next(item for item in self.rows('attribution.tsv') if item['comparison'] == 'within_engine_dce'
                           and item['engine'] == engine and item['object_id'] == ('7' if engine == 'grh' else '107'))
                self.assertEqual(row['evidence_status'], 'native_removal_evidence')
                self.assertEqual(json.loads(row['evidence_json'])['native_removal_evidence'], evidence)

    def test_transitive_support_requires_each_candidate_path_before_attribution(self):
        mutation, evidence = self.set_pruned_dependency_fixture('grh', candidates=[1, 7])
        self.set_operand_path_fields(evidence[:1])
        self.set_operand_path_fields(evidence[1:], support='fallback_defined', hops=1)
        self.write(grh_operand_mutations=[mutation], grh_removal_evidence=evidence)
        report = self.analyze()
        self.assertTrue(report['passed'], report['issues'])
        self.assertEqual(report['connections']['dce_changes']['grh']['removed_by_dce_operand_pruning'], 1)
        self.output = self.work / 'transitive-support-missing-candidate'
        self.write(grh_operand_mutations=[mutation], grh_removal_evidence=evidence[:1])
        self.assert_rejected()

    def test_transitive_support_cannot_bypass_uncovered_surviving_removal_gate(self):
        mutation, evidence = self.set_pruned_dependency_fixture('grh')
        self.set_operand_path_fields(evidence, support='selected_read')
        self.inventory['grh']['before_edges'].append(edge(50, 7, 6))
        self.write(grh_operand_mutations=[mutation], grh_removal_evidence=evidence)
        report = self.analyze()
        self.assertFalse(report['passed'])
        self.assertEqual(report['connections']['dce_changes']['grh']['removed_by_dce_operand_pruning'], 1)
        self.assertEqual(report['connections']['dce_changes']['grh']['removed_requires_semantic_review'], 1)
        self.assertIn({'kind': 'removed_dce_connections_require_semantic_review', 'engine': 'grh',
                       'connections': 1}, report['issues'])

    def test_transitive_support_cannot_substitute_mutation_reference_for_terminal_use(self):
        mutation, evidence = self.set_pruned_dependency_fixture('grh')
        self.set_operand_path_fields(evidence)
        evidence[0].update(reference_operation_id=21, reference_operation_generation=4, reference_operand_index=0)
        self.write(grh_operand_mutations=[mutation], grh_removal_evidence=evidence)
        self.assert_rejected()

    def set_dead_anchor_dependency_fixture(self, engine, *, candidates=None, support='exact'):
        _, evidence = self.set_pruned_dependency_fixture(engine, candidates=candidates)
        self.set_operand_path_fields(evidence, support=support)
        for item in evidence:
            for field in ('mutation_id', 'value_id', 'value_generation', 'operation_id',
                          'operation_generation', 'operand_index'):
                del item[field]
            item.update(cause='dead_anchor_cone', anchor_removal_id=1)
        removal = {'target_node_id': 2 if engine == 'grh' else 102,
            'detail': {'anchor_removal_id': 1, 'pass': 'dead-code-elim' if engine == 'grh' else 'removeDeadNodes',
                'operation_id': 31, 'operation_generation': 9, 'value_id': 10, 'value_generation': 7}}
        return removal, evidence

    def test_dead_anchor_native_support_explains_surviving_removal_without_operand_mutation(self):
        original = deepcopy(self.inventory)
        for engine in ('grh', 'gsim'):
            with self.subTest(engine=engine):
                self.inventory = deepcopy(original)
                self.output = self.work / ('dead-anchor-support-' + engine)
                removal, evidence = self.set_dead_anchor_dependency_fixture(engine)
                self.write(**{engine + '_anchor_removals': [removal], engine + '_removal_evidence': evidence})
                report = self.analyze()
                self.assertTrue(report['passed'], report['issues'])
                header = report['verification'][engine]['header']
                self.assertEqual(header['connection_anchor_removal_trace'], 'dead-anchor-cone.v1')
                self.assertNotIn('mutation_trace', header)
                self.assertNotIn('connection_removal_trace', header)
                self.assertEqual(report['connections']['dce_changes'][engine]['removed_by_dce_operand_pruning'], 1)
                row = next(item for item in self.rows('attribution.tsv') if item['comparison'] == 'within_engine_dce'
                           and item['engine'] == engine and item['object_id'] == ('7' if engine == 'grh' else '107'))
                self.assertEqual(row['evidence_status'], 'native_removal_evidence')
                self.assertEqual(json.loads(row['evidence_json'])['native_removal_evidence'], evidence)

    def test_dead_anchor_native_support_requires_complete_mixed_candidate_paths(self):
        removal, evidence = self.set_dead_anchor_dependency_fixture('grh', candidates=[1, 7])
        self.set_operand_path_fields(evidence[1:], support='fallback_defined', hops=1)
        self.write(grh_anchor_removals=[removal], grh_removal_evidence=evidence)
        report = self.analyze()
        self.assertTrue(report['passed'], report['issues'])
        self.assertEqual(report['connections']['dce_changes']['grh']['removed_by_dce_operand_pruning'], 1)
        self.output = self.work / 'dead-anchor-missing-candidate'
        self.write(grh_anchor_removals=[removal], grh_removal_evidence=evidence[:1])
        self.assert_rejected()

    def test_dead_anchor_evidence_cannot_bypass_other_uncovered_surviving_removal(self):
        removal, evidence = self.set_dead_anchor_dependency_fixture('grh', support='selected_read')
        self.inventory['grh']['before_edges'].append(edge(50, 7, 6))
        self.write(grh_anchor_removals=[removal], grh_removal_evidence=evidence)
        report = self.analyze()
        self.assertFalse(report['passed'])
        self.assertEqual(report['connections']['dce_changes']['grh']['removed_by_dce_operand_pruning'], 1)
        self.assertEqual(report['connections']['dce_changes']['grh']['removed_requires_semantic_review'], 1)
        self.assertIn({'kind': 'removed_dce_connections_require_semantic_review', 'engine': 'grh',
                       'connections': 1}, report['issues'])

    def test_dead_anchor_root_and_terminal_corruption_rejects_before_attribution(self):
        for scenario in ('root_generation', 'terminal_reference', 'empty_path', 'missing_fact'):
            with self.subTest(scenario=scenario):
                self.output = self.work / ('dead-anchor-corrupt-' + scenario)
                removal, evidence = self.set_dead_anchor_dependency_fixture('grh')
                if scenario == 'root_generation':
                    removal['detail']['operation_generation'] += 1
                elif scenario == 'terminal_reference':
                    evidence[0].update(reference_operation_id=31, reference_operation_generation=9,
                                       reference_operand_index=1)
                elif scenario == 'empty_path':
                    evidence[0]['path'] = []
                self.write(grh_anchor_removals=[] if scenario == 'missing_fact' else [removal],
                           grh_removal_evidence=evidence)
                self.assert_rejected()

    def test_current_split_can_be_bound_without_old_after_id_reuse(self):
        split = self.work / 'current-split'
        write_bundle(split, 'gsim', {'before_nodes': self.s0_nodes, 'after_nodes': self.s0_nodes,
            'before_edges': self.s0_edges, 'after_edges': self.s0_edges}, split=True)
        report = self.analyze(gsim_split_bundle=split)
        self.assertTrue(report['passed'])
        self.assertTrue(report['verification']['split']['replay_exact'])

    def test_all_live_operation_owners_audit_detects_a_new_orphan(self):
        self.add_grh_provenance([{'relation': 'start', 'node_id': 3, 'start_kind': 'owned_operation',
            'entity_kind': 'operation', 'entity_id': 77, 'generation': 4, 'owner_count': 1}])
        report = self.analyze()
        self.assertFalse(report['passed'])
        audit = report['live_operation_owners']
        self.assertTrue(audit['complete'])
        self.assertEqual(audit['live_owned_operations'], 1)
        self.assertEqual(audit['newly_uncovered_live_operations'], 1)
        self.assertEqual(audit['incomplete_original_owner_sets'], 0)
        row, = self.rows('live-operation-owner-violations.tsv')
        self.assertEqual(row['operation_id'], '77')
        self.assertEqual(row['operation_generation'], '4')
        self.assertEqual(json.loads(row['original_owner_ids_json']), [3])
        self.assertEqual(json.loads(row['violations_json']), ['no_surviving_original_owner'])

    def test_all_live_operation_owners_audit_accepts_a_surviving_shared_owner(self):
        self.add_grh_provenance([{'relation': 'start', 'node_id': owner, 'start_kind': 'owned_operation',
            'entity_kind': 'operation', 'entity_id': 77, 'generation': 4, 'owner_count': 2}
            for owner in (2, 3)])
        report = self.analyze()
        self.assertTrue(report['passed'], report['issues'])
        audit = report['live_operation_owners']
        self.assertTrue(audit['complete'] and audit['passed'])
        self.assertEqual(audit['live_owned_operations'], 1)
        self.assertEqual(audit['owner_memberships'], 2)
        self.assertEqual(audit['newly_uncovered_live_operations'], 0)
        self.assertEqual(self.rows('live-operation-owner-violations.tsv'), [])

    def test_all_live_operation_owners_audit_rejects_incomplete_or_duplicate_memberships(self):
        start = {'relation': 'start', 'node_id': 2, 'start_kind': 'owned_operation',
                 'entity_kind': 'operation', 'entity_id': 77, 'generation': 4, 'owner_count': 2}
        for label, records in (('missing_owner', [start]),
                               ('missing_count', [{key: value for key, value in start.items() if key != 'owner_count'}]),
                               ('duplicate', [{**start, 'owner_count': 1}] * 2),
                               ('disagreeing_counts', [start, {**start, 'node_id': 3, 'owner_count': 3}])):
            with self.subTest(case=label):
                self.write()
                self.output = self.work / ('owner-audit-' + label)
                self.add_grh_provenance(records)
                report = self.analyze()
                self.assertFalse(report['passed'])
                self.assertEqual(report['live_operation_owners']['incomplete_original_owner_sets'], 1)
                self.assertEqual(report['live_operation_owners']['newly_uncovered_live_operations'], 0)
                row, = self.rows('live-operation-owner-violations.tsv')
                self.assertEqual(json.loads(row['violations_json']), ['incomplete_original_owner_set'])

    def test_live_operation_owner_audit_does_not_invent_ownerless_implementation(self):
        self.add_grh_provenance([{'relation': 'root', 'entity_kind': 'value', 'entity_id': 99,
                                 'generation': 0, 'root_kind': 'output_port'}])
        report = self.analyze()
        self.assertTrue(report['passed'], report['issues'])
        self.assertEqual(report['live_operation_owners']['live_owned_operations'], 0)
        self.assertTrue(report['live_operation_owners']['passed'])

    def test_source_mutation_during_replay_prevents_tsv_publication(self):
        original, changed = analysis.verify_bundle, False

        def changing(*args, **kwargs):
            nonlocal changed
            result = original(*args, **kwargs)
            if not changed:
                path = self.grh / 'evolution.tsv'
                path.write_bytes(path.read_bytes() + b'\n')
                changed = True
            return result

        with patch.object(analysis, 'verify_bundle', side_effect=changing):
            self.assert_rejected()
        self.assertTrue(changed)


if __name__ == '__main__':
    unittest.main()
