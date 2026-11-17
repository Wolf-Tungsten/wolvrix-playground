"""Portable positive/mutation contracts for the independent F32 lane verifier."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import prove_f32_reconstruction as verifier


def compact(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def artifact(path):
    body = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)}


def write_json(path, value):
    path.write_text(compact(value) + '\n')


def encode(value):
    if value is None:
        return r'\N'
    if isinstance(value, (dict, list)):
        value = compact(value)
    elif type(value) is bool:
        value = 'true' if value else 'false'
    return str(value).replace('\\', '\\\\').replace('\t', '\\t').replace('\n', '\\n').replace('\r', '\\r')


def expression(identifier, op, width, children=(), node=None, shift=False):
    return {'id': identifier, 'nativeId': identifier + 1000, 'op': op,
            'opcode': {'OP_EQ': 11, 'OP_OR': 16, 'OP_SHL': 30, 'OP_EMPTY': 0}[op],
            'width': width, 'sign': 0, 'isClock': 0, 'reset': 0, 'usedBit': -1,
            'nodeId': node, 'memoryNodeId': None, 'values': [128] if shift else [],
            'strVal': '', 'children': list(children)}


def native_node(identifier, width, kind, trees=None):
    return {'id': identifier, 'name': 'irrelevant-' + str(identifier), 'type': kind,
            'status': 'VALID_NODE', 'width': width, 'sign': 0, 'dimension': [],
            'isClock': False, 'clockId': -1, 'asReset': 0, 'assignTrees': trees or [],
            'valTree': None, 'resetTree': None, 'resetCond': None, 'resetVal': None, 'memTree': None}


class ReconstructionContracts(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get('F32_RECONSTRUCTION_TEST_ROOT',
                                  verifier.ROOT / 'ptmp/firrtl-ingest/F32/reconstruction-contract-tmp'))
        base.mkdir(parents=True, exist_ok=True)
        self.work = Path(tempfile.mkdtemp(prefix='case-', dir=base))
        self.comparison = self.work / 'comparison'
        self.grh, self.gsim = self.work / 'grh', self.work / 'gsim'
        self.index = 0

    def tearDown(self):
        shutil.rmtree(self.work)

    def table(self, path, meta, rows, footer=None):
        header = verifier.HEADERS[path.name]
        body = '#meta\t' + compact(meta) + '\n' + '\t'.join(header) + '\n'
        body += ''.join('\t'.join(map(encode, row)) + '\n' for row in rows)
        body += '#footer\t' + compact({'complete': True, 'rowCount': len(rows), **(footer or {})}) + '\n'
        path.write_text(body)
        return artifact(path)

    def fixture(self, *, repeated=False, target_id=3):
        self.target_id = target_id
        self.pairs = {1: 10, 2: 20, target_id: target_id * 10, 5: 50, 6: 60}
        output_id = self.pairs[target_id]
        low_value = 101 if repeated else 102
        self.captures = {}
        self.snapshot_records = {'grh': {}, 'gsim': {}}
        for engine, directory in (('grh', self.grh), ('gsim', self.gsim)):
            directory.mkdir()
            capture = {'schema': 'wolvrix.f32.pipeline-capture.v1', 'engine': engine,
                'status': 'completed', 'source': 'raw-firrtl', 'input_sha256': 'a' * 64,
                'trace_enabled': False, 'trace_validation': False, 'full_structure': True, 'snapshots': {}}
            for stage in range(5):
                base = directory / f'P{stage}'
                base.mkdir()
                meta = {'schema': 'semantic-node-exchange.v1', 'engine': engine, 'run_id': engine + '-run',
                        'graph_id': 'top', 'exchange_session_id': engine + '-session-' + str(stage),
                        'snapshot_id': engine + '-snapshot-' + str(stage), 'stage': verifier.STAGES[engine][stage]}
                offset = stage * 10
                concat, equal, assign = offset + 1, offset + 2, offset + 3
                anchors = {1: 101, 2: 103, target_id: 104, 5: low_value, 6: 101}
                widths = {1: 128, 2: 256, target_id: 1, 5: 128, 6: 128}
                if engine == 'grh':
                    nodes = [{'id': identifier, 'parent': 1, 'name': 'unused',
                              'ops': [concat, equal, assign] if identifier == target_id else [],
                              'anchors': [anchors[identifier]]} for identifier in sorted(self.pairs)]
                    values = [{'id': identifier, 'w': width, 'sgn': False, 'type': 'logic',
                               'domain': '4state', 'shape': []}
                              for identifier, width in ((101, 128), (102, 128), (103, 256),
                                                        (104, 1), (105, 256), (106, 1))]
                    structure = {'formatVersion': 5, 'graphs': [{'semanticTree': {
                        'rootPath': 1, 'namesFlattened': True, 'paths': [{'id': 1, 'parent': 0}], 'nodes': nodes,
                        'boundaryUses': [
                            {'source': 6, 'target': target_id, 'value': 101, 'user': concat, 'operandIndex': 0, 'kind': 'data'},
                            {'source': 5, 'target': target_id, 'value': low_value, 'user': concat, 'operandIndex': 1, 'kind': 'data'},
                            {'source': 2, 'target': target_id, 'value': 103, 'user': 0, 'operandIndex': 2**32 - 1, 'kind': 'data'}]},
                        'vals': values, 'ops': [
                            {'id': concat, 'kind': 'kConcat', 'in': [101, low_value], 'out': [105]},
                            {'id': equal, 'kind': 'kEq', 'in': [105, 103], 'out': [106]},
                            {'id': assign, 'kind': 'kAssign', 'in': [106], 'out': [104]}]}]}
                    ids = sorted(self.pairs)
                    typed_rows = [(identifier, 'value', anchors[identifier] + 1000, 0,
                        assign + 1000 if identifier == target_id else 0, 0,
                        'kAssign' if identifier == target_id else 'input', widths[identifier], False, [], '4state',
                        -1, False, [], [], [], 0, -1, 'anchor-candidate') for identifier in ids]
                    typed_name = 'node-endpoints.tsv'
                else:
                    entries = [expression(0, 'OP_EQ', 1, (2, 3)),
                        expression(1, 'OP_EMPTY', 1, node=output_id), expression(2, 'OP_OR', 256, (4, 5)),
                        expression(3, 'OP_EMPTY', 256, node=20), expression(4, 'OP_SHL', 256, (6,), shift=True),
                        expression(5, 'OP_EMPTY', 128, node=50), expression(6, 'OP_EMPTY', 128, node=60)]
                    nodes = [native_node(native, widths[identifier], 'NODE_OUT' if identifier == target_id else
                        'NODE_OTHERS' if identifier in (5, 6) else 'NODE_INP',
                        [{'root': 0, 'lvalue': 1, 'nodes': entries}] if identifier == target_id else
                        [{'root': 0, 'lvalue': 1, 'nodes': [expression(0, 'OP_EMPTY', 128, node=10),
                                                         expression(1, 'OP_EMPTY', -1, node=native)]}]
                        if identifier in (5, 6) else []) for identifier, native in sorted(self.pairs.items())]
                    structure = {'nodeStructureSchema': 'gsim.node-structure.v1', 'nodeStructureComplete': True,
                        'assignmentOrder': 'native-vector-order', 'memoryInventoryComplete': True, 'memories': [], 'nodes': nodes}
                    ids = sorted(self.pairs.values())
                    typed_rows = [(node['id'], node['type'], node['width'], False, [], None, None, 0, -1,
                                   len(node['assignTrees'])) for node in sorted(nodes, key=lambda row: row['id'])]
                    typed_name = 'node-details.tsv'
                artifacts = {}
                artifacts['nodes.tsv'] = self.table(base / 'nodes.tsv', {**meta, 'table': 'nodes'},
                    [(identifier, ['name-' + str(identifier)], 'arbitrary') for identifier in ids], {'nodeInventoryComplete': True})
                edges = [(index + 1, source if engine == 'grh' else self.pairs[source],
                          target_id if engine == 'grh' else output_id, 'dependency', 'resolved', [], None)
                         for index, source in enumerate((2, 5, 6))]
                coverage = {'dependency': {'resolved': 3, 'unresolved': 0, 'status': 'complete'}}
                artifacts['connections.tsv'] = self.table(base / 'connections.tsv', {**meta, 'table': 'connections'},
                                                            edges, {'connectionCoverage': coverage})
                artifacts['bit-slices.tsv'] = self.table(base / 'bit-slices.tsv',
                    {**meta, 'schema': 'semantic-node-bit-slices.v1'}, [])
                typed_meta = {**meta, 'schema': 'grh.semantic-node-endpoints.v2'} if engine == 'grh' else {
                    **meta, 'table': 'node-details', 'detail_schema': 'gsim.node-details.v1'}
                artifacts[typed_name] = self.table(base / typed_name, typed_meta, typed_rows)
                write_json(base / 'design.json', structure)
                artifacts['structure'] = artifact(base / 'design.json')
                capture['snapshots'][f'P{stage}'] = {'directory': str(base), 'stage': meta['stage'],
                    'structure': str(base / 'design.json'), 'artifacts': artifacts}
                self.snapshot_records[engine][f'P{stage}'] = {'run_id': meta['run_id'], 'snapshot_id': meta['snapshot_id'],
                    'nodes': len(ids), 'connections': len(edges), 'coverage': coverage}
            self.captures[engine] = capture
            write_json(directory / 'summary.json', capture)
        self.comparison.mkdir()
        self.inputs = {'schema': 'wolvrix.f32.comparison-checkpoint.v1', 'inventory_complete': True,
            'proof_implementation': dict(verifier.HISTORICAL_IMPLEMENTATION), 'snapshots': self.snapshot_records,
            'capture_summaries': {engine: {'path': str(directory), 'sha256': artifact(directory / 'summary.json')['sha256']}
                for engine, directory in (('grh', self.grh), ('gsim', self.gsim))}}
        write_json(self.comparison / 'inputs.json', self.inputs)
        self.summary = {'schema': 'wolvrix.f32.semantic-comparison.v1', 'status': 'analyzed', 'complete': True,
            'full_native_structure_compared': True, 'input_sha256': 'a' * 64, 'snapshots': self.snapshot_records,
            'comparison_database': str(self.comparison / 'comparison.sqlite'), 'semantic_acceptance': False}
        write_json(self.comparison / 'summary.json', self.summary)
        (self.comparison / 'differences.jsonl').write_text('{}\n')
        db = sqlite3.connect(self.comparison / 'comparison.sqlite')
        db.executescript('CREATE TABLE pairs(stage INTEGER,grh INTEGER,gsim INTEGER,name TEXT);'
                         'CREATE TABLE structural(stage INTEGER,grh INTEGER,gsim INTEGER,status TEXT,reason TEXT);')
        for stage in range(5):
            db.executemany('INSERT INTO pairs VALUES(?,?,?,?)',
                           [(stage, left, right, 'unused') for left, right in self.pairs.items()])
            db.execute('INSERT INTO structural VALUES(?,?,?,?,?)', (stage, target_id, output_id, 'unverified',
                        'nonidentical_expression_exceeds_exhaustive_bit_budget'))
        db.commit()
        db.close()

    def mutate_structure(self, engine, change, stage=3, raw=False):
        path = (self.grh if engine == 'grh' else self.gsim) / f'P{stage}' / 'design.json'
        if raw:
            path.write_text(change(path.read_text()))
        else:
            native = json.loads(path.read_text())
            change(native)
            write_json(path, native)
        self.captures[engine]['snapshots'][f'P{stage}']['artifacts']['structure'] = artifact(path)
        directory = self.grh if engine == 'grh' else self.gsim
        write_json(directory / 'summary.json', self.captures[engine])
        self.inputs['capture_summaries'][engine]['sha256'] = artifact(directory / 'summary.json')['sha256']
        write_json(self.comparison / 'inputs.json', self.inputs)

    def run_proof(self, targets=None):
        self.index += 1
        return verifier.prove(self.comparison, self.grh, self.gsim, self.work / ('proof-' + str(self.index)),
                              targets or [(3, self.target_id, self.pairs[self.target_id])])

    def assert_unverified(self, report, message=None):
        self.assertEqual(report['status'], 'unverified')
        self.assertEqual(report['certificates'], [])
        self.assertFalse(report['semantic_acceptance'])
        if message:
            self.assertIn(message, compact(report))

    def assert_positive(self, repeated, target_id):
        self.fixture(repeated=repeated, target_id=target_id)
        before = {str(path): artifact(path)['sha256'] for directory in (self.comparison, self.grh, self.gsim)
                  for path in directory.rglob('*') if path.is_file()}
        report = self.run_proof([(stage, target_id, self.pairs[target_id]) for stage in (3, 4)])
        self.assertEqual(report['status'], 'conditional_anchor_expressions_proved', compact(report))
        self.assertEqual(len(report['certificates']), 2)
        for certificate in report['certificates']:
            self.assertEqual(certificate['lemma_replay']['lane_count'], 256)
            self.assertEqual(certificate['boundary_bindings']['H']['grh_node'], 6)
            self.assertEqual(certificate['boundary_bindings']['L']['grh_node'], 5)
            if repeated:
                self.assertEqual(certificate['boundary_bindings']['H']['compact_value'],
                                 certificate['boundary_bindings']['L']['compact_value'])
            for field in verifier.UNPROVED:
                self.assertFalse(certificate[field])
            self.assertEqual(certificate['reader_result']['status'], 'unverified')
        self.assertFalse(report['proof_implementation']['normalizer_called'])
        self.assertFalse(report['proof_implementation']['reader_called'])
        self.assertFalse(report['historical_comparison_implementation_is_current_code_claim'])
        self.assertEqual(report['comparison_implementation_group'], 'closed-v8-reader-cd4aa9ad')
        self.assertEqual(report['historical_comparison_implementation'], verifier.HISTORICAL_IMPLEMENTATION)
        self.assertEqual(report['proof_implementation']['sha256'], hashlib.sha256(Path(verifier.__file__).read_bytes()).hexdigest())
        self.assertEqual(before, {path: artifact(Path(path))['sha256'] for path in before})
        self.assertTrue(all(item['sha256'] == item['sha256_after'] and item['stat_before'] == item['stat_after']
                            for item in report['inputs']))
        self.assertFalse(any(Path(str(self.comparison / 'comparison.sqlite') + suffix).exists()
                             for suffix in ('-wal', '-shm', '-journal')))

    def test_mixed_shape_at_P3_and_P4(self):
        self.assert_positive(False, 10)

    def test_producer_shape_at_P3_and_P4(self):
        self.assert_positive(False, 11)

    def test_repeated_physical_value_distinct_children_at_P3_and_P4(self):
        self.assert_positive(True, 3)

    def mutate_entry(self, identifier, **updates):
        self.mutate_structure('gsim', lambda native: next(node for node in native['nodes']
            if node['id'] == self.pairs[self.target_id])['assignTrees'][0]['nodes'][identifier].update(updates))

    def test_wrong_shifts_fail_closed(self):
        self.fixture()
        for shift in (127, 129, 0, 256, 128.0, True):
            with self.subTest(shift=shift):
                self.mutate_entry(4, values=[shift])
                self.assert_unverified(self.run_proof())

    def test_wrong_native_widths_fail_closed(self):
        self.fixture()
        for identifier, width in ((0, 2), (2, 255), (4, 128), (5, 256), (6, 127), (3, 255), (1, -1)):
            with self.subTest(identifier=identifier):
                self.mutate_entry(identifier, width=width)
                self.assert_unverified(self.run_proof())
                self.mutate_entry(identifier, width={0: 1, 1: 1, 2: 256, 3: 256, 4: 256, 5: 128, 6: 128}[identifier])

    def test_signed_expression_fails_closed(self):
        self.fixture()
        for identifier in (0, 2, 4, 5, 6, 3):
            with self.subTest(identifier=identifier):
                self.mutate_entry(identifier, sign=1)
                self.assert_unverified(self.run_proof())
                self.mutate_entry(identifier, sign=0)

    def test_wrong_native_node_width_and_sign_fail_closed(self):
        self.fixture()
        for updates in ({'width': 127}, {'width': 128, 'sign': 1}):
            self.mutate_structure('gsim', lambda native: next(node for node in native['nodes'] if node['id'] == 60).update(updates))
            self.assert_unverified(self.run_proof())

    def test_or_operand_order_fails_closed(self):
        self.fixture()
        self.mutate_entry(2, children=[5, 4])
        self.assert_unverified(self.run_proof())

    def test_eq_operand_order_fails_closed(self):
        self.fixture()
        self.mutate_entry(0, children=[3, 2])
        self.assert_unverified(self.run_proof())

    def test_different_child_identity_fails_even_for_shared_value(self):
        self.fixture(repeated=True)
        self.mutate_entry(6, nodeId=50)
        self.assert_unverified(self.run_proof(), 'operand identity')

    def test_wrong_c_identity_fails_closed(self):
        self.fixture()
        self.mutate_entry(3, nodeId=10)
        self.assert_unverified(self.run_proof())

    def test_wrong_lvalue_identity_fails_closed(self):
        self.fixture()
        self.mutate_entry(1, nodeId=50)
        self.assert_unverified(self.run_proof())

    def test_incomplete_native_structure_fails_closed(self):
        self.fixture()
        self.mutate_structure('gsim', lambda native: native.update(nodeStructureComplete=False))
        self.assert_unverified(self.run_proof(), 'complete native GSIM')

    def test_partial_tree_fails_closed(self):
        self.fixture()
        self.mutate_structure('gsim', lambda native: next(node for node in native['nodes'] if node['id'] == 30)
                              ['assignTrees'][0]['nodes'].pop())
        self.assert_unverified(self.run_proof())

    def test_extra_assignment_fails_closed(self):
        self.fixture()
        self.mutate_structure('gsim', lambda native: next(node for node in native['nodes'] if node['id'] == 30)
                              ['assignTrees'].append({'root': 0, 'lvalue': 0, 'nodes': []}))
        self.assert_unverified(self.run_proof())

    def test_memory_or_reset_semantics_fail_closed(self):
        self.fixture()
        self.mutate_structure('gsim', lambda native: next(node for node in native['nodes'] if node['id'] == 30)
                              .update(resetTree={'root': 0}))
        self.assert_unverified(self.run_proof())

    def test_missing_or_ambiguous_boundary_slot_fails_closed(self):
        self.fixture(repeated=True)
        self.mutate_structure('grh', lambda native: native['graphs'][0]['semanticTree']['boundaryUses'].pop(0))
        self.assert_unverified(self.run_proof(), 'operand-slot boundary')
        self.mutate_structure('grh', lambda native: native['graphs'][0]['semanticTree']['boundaryUses'].append(
            copy.deepcopy(native['graphs'][0]['semanticTree']['boundaryUses'][0])))
        self.assert_unverified(self.run_proof())

    def test_swapped_boundary_slots_fail_for_shared_physical_value(self):
        self.fixture(repeated=True)
        def swap(native):
            uses = native['graphs'][0]['semanticTree']['boundaryUses']
            uses[0]['operandIndex'], uses[1]['operandIndex'] = 1, 0
        self.mutate_structure('grh', swap)
        self.assert_unverified(self.run_proof(), 'operand identity')

    def test_boundary_source_must_anchor_actual_compact_value(self):
        self.fixture()
        self.mutate_structure('grh', lambda native: next(node for node in native['graphs'][0]['semanticTree']['nodes']
            if node['id'] == 6).update(anchors=[102]))
        self.assert_unverified(self.run_proof(), 'exact native anchor')

    def test_generic_high_slot_does_not_substitute_for_actual_slot(self):
        self.fixture()
        self.mutate_structure('grh', lambda native: native['graphs'][0]['semanticTree']['boundaryUses'][0]
                              .update(user=0, operandIndex=2**32 - 1))
        self.assert_unverified(self.run_proof())

    def test_explicit_c_operand_slot_is_supported(self):
        self.fixture()
        self.mutate_structure('grh', lambda native: native['graphs'][0]['semanticTree']['boundaryUses'][2]
                              .update(user=32, operandIndex=1))
        self.assertEqual(self.run_proof()['status'], 'conditional_anchor_expressions_proved')

    def test_wrong_grh_type_fails_closed(self):
        self.fixture()
        self.mutate_structure('grh', lambda native: next(value for value in native['graphs'][0]['vals']
                              if value['id'] == 101).update(sgn=True))
        self.assert_unverified(self.run_proof())

    def test_extra_owned_operation_fails_closed(self):
        self.fixture()
        def extra(native):
            graph = native['graphs'][0]
            graph['vals'].append({'id': 999, 'w': 128, 'sgn': False, 'type': 'logic', 'domain': '4state'})
            graph['ops'].append({'id': 999, 'kind': 'kAssign', 'in': [101], 'out': [999]})
            next(node for node in graph['semanticTree']['nodes'] if node['id'] == 3)['ops'].append(999)
        self.mutate_structure('grh', extra)
        self.assert_unverified(self.run_proof(), 'owned-operation inventory')

    def test_duplicate_json_key_fails_closed(self):
        self.fixture()
        self.mutate_structure('gsim', lambda body: body.replace('"nodeStructureComplete":true',
            '"nodeStructureComplete":true,"nodeStructureComplete":true'), raw=True)
        self.assert_unverified(self.run_proof(), 'duplicate JSON key')

    def test_duplicate_native_id_fails_closed(self):
        self.fixture()
        self.mutate_structure('gsim', lambda native: native['nodes'].append(copy.deepcopy(native['nodes'][0])))
        self.assert_unverified(self.run_proof(), 'duplicate or invalid native identity')

    def test_float_or_boolean_boundary_ids_fail_closed(self):
        self.fixture()
        for field, value in (('source', 6.0), ('target', 3.0), ('value', 101.0),
                             ('source', True), ('user', 31.0), ('operandIndex', False)):
            with self.subTest(field=field, value=value):
                self.mutate_structure('grh', lambda native: native['graphs'][0]['semanticTree']['boundaryUses'][0]
                                      .update({field: value}))
                self.assert_unverified(self.run_proof(), 'native boundary use')
                self.mutate_structure('grh', lambda native: native['graphs'][0]['semanticTree']['boundaryUses'][0]
                    .update({'source': 6, 'target': 3, 'value': 101, 'user': 31, 'operandIndex': 0}))

    def test_float_node_identity_and_opcode_fail_closed(self):
        self.fixture()
        self.mutate_entry(6, nodeId=60.0)
        self.assert_unverified(self.run_proof())
        self.mutate_entry(6, nodeId=60)
        self.mutate_entry(4, opcode=30.0)
        self.assert_unverified(self.run_proof())

    def test_float_root_and_parent_ids_fail_closed(self):
        self.fixture()
        self.mutate_structure('grh', lambda native: native['graphs'][0]['semanticTree'].update(rootPath=1.0))
        self.assert_unverified(self.run_proof())
        self.mutate_structure('grh', lambda native: native['graphs'][0]['semanticTree'].update(rootPath=1))
        self.mutate_structure('grh', lambda native: native['graphs'][0]['semanticTree']['nodes'][0].update(parent=1.0))
        self.assert_unverified(self.run_proof())

    def test_boundary_user_must_reference_actual_owned_operand_slot(self):
        self.fixture()
        self.mutate_structure('grh', lambda native: native['graphs'][0]['semanticTree']['boundaryUses'][0]
                              .update(user=999))
        self.assert_unverified(self.run_proof(), 'boundary operation/slot reference')

    def test_verifier_source_identity_must_match_loaded_module(self):
        self.fixture()
        with patch.object(verifier, 'LOADED_SOURCE_SHA256', 'b' * 64):
            self.assert_unverified(self.run_proof(), 'source changed since module load')

    def test_source_hash_drift_fails_before_database_connection(self):
        self.fixture()
        path = self.grh / 'P3/design.json'
        path.write_text(path.read_text() + '\n')
        with patch.object(verifier.sqlite3, 'connect', side_effect=AssertionError('must not connect')):
            self.assert_unverified(self.run_proof(), 'path/hash/bytes mismatch')

    def test_historical_reader_or_dependency_hash_drift_fails_closed(self):
        self.fixture()
        for name in verifier.HISTORICAL_IMPLEMENTATION:
            self.inputs['proof_implementation'][name] = 'b' * 64
            write_json(self.comparison / 'inputs.json', self.inputs)
            self.assert_unverified(self.run_proof(), 'historical reader/dependency hashes')
            self.inputs['proof_implementation'][name] = verifier.HISTORICAL_IMPLEMENTATION[name]

    def test_typed_index_reader_group_is_accepted_and_bound_separately(self):
        self.fixture(repeated=True)
        identity = verifier.ACCEPTED_IMPLEMENTATIONS['typed-index-reader-564c8a57']
        self.inputs['proof_implementation'] = dict(identity)
        write_json(self.comparison / 'inputs.json', self.inputs)
        report = self.run_proof([(3, 3, 30), (4, 3, 30)])
        self.assertEqual(report['status'], 'conditional_anchor_expressions_proved')
        self.assertEqual(len(report['certificates']), 2)
        self.assertEqual(report['comparison_implementation_group'], 'typed-index-reader-564c8a57')
        self.assertEqual(report['historical_comparison_implementation'], identity)
        self.assertEqual(report['proof_implementation']['sha256'], hashlib.sha256(Path(verifier.__file__).read_bytes()).hexdigest())
        self.assertFalse(report['proof_implementation']['reader_called'])
        self.assertFalse(report['proof_implementation']['normalizer_called'])
        self.assertFalse(report['historical_comparison_implementation_is_current_code_claim'])
        self.assertFalse(report['semantic_acceptance'])

    def test_approved_hashes_in_wrong_dependency_slots_rejected_as_mixed_identity(self):
        self.fixture()
        for name, approved in verifier.ACCEPTED_IMPLEMENTATIONS.items():
            with self.subTest(group=name):
                identity = dict(approved)
                identity['compare_f28_semantic_tree.py'], identity['semantic_bitvector.py'] = (
                    identity['semantic_bitvector.py'], identity['compare_f28_semantic_tree.py'])
                self.inputs['proof_implementation'] = identity
                write_json(self.comparison / 'inputs.json', self.inputs)
                with patch.object(verifier.sqlite3, 'connect', side_effect=AssertionError('must not connect')):
                    report = self.run_proof()
                self.assert_unverified(report, 'no exact approved identity group')
                self.assertIsNone(report['comparison_implementation_group'])

    def test_each_dependency_hash_must_match_the_complete_approved_group(self):
        self.fixture()
        for group, approved in verifier.ACCEPTED_IMPLEMENTATIONS.items():
            for filename in approved:
                with self.subTest(group=group, filename=filename):
                    identity = dict(approved)
                    identity[filename] = 'f' * 64
                    self.inputs['proof_implementation'] = identity
                    write_json(self.comparison / 'inputs.json', self.inputs)
                    with patch.object(verifier.sqlite3, 'connect', side_effect=AssertionError('must not connect')):
                        report = self.run_proof()
                    self.assert_unverified(report, 'no exact approved identity group')
                    self.assertIsNone(report['comparison_implementation_group'])

    def test_extra_missing_or_renamed_identity_keys_are_rejected(self):
        self.fixture()
        for group, approved in verifier.ACCEPTED_IMPLEMENTATIONS.items():
            for mutation in ('extra', 'missing', 'renamed'):
                with self.subTest(group=group, mutation=mutation):
                    identity = dict(approved)
                    if mutation == 'extra':
                        identity['extra.py'] = identity['semantic_node_exchange.py']
                    elif mutation == 'missing':
                        identity.pop('semantic_node_exchange.py')
                    else:
                        identity['renamed.py'] = identity.pop('semantic_node_exchange.py')
                    self.inputs['proof_implementation'] = identity
                    write_json(self.comparison / 'inputs.json', self.inputs)
                    with patch.object(verifier.sqlite3, 'connect', side_effect=AssertionError('must not connect')):
                        report = self.run_proof()
                    self.assert_unverified(report, 'no exact approved identity group')
                    self.assertIsNone(report['comparison_implementation_group'])

    def test_incomplete_checkpoint_fails_closed(self):
        self.fixture()
        self.inputs['inventory_complete'] = False
        write_json(self.comparison / 'inputs.json', self.inputs)
        self.assert_unverified(self.run_proof())

    def test_database_sidecars_rejected_before_connect(self):
        self.fixture()
        for suffix in ('-wal', '-shm', '-journal'):
            path = Path(str(self.comparison / 'comparison.sqlite') + suffix)
            path.touch()
            with patch.object(verifier.sqlite3, 'connect', side_effect=AssertionError('must not connect')):
                self.assert_unverified(self.run_proof(), 'SQLite sidecars')
            path.unlink()

    def test_input_mutation_during_verification_discards_all_certificates(self):
        self.fixture()
        original = verifier.FrozenInputs.verify
        def mutate_and_verify(instance):
            path = self.grh / 'P3/design.json'
            path.write_text(path.read_text() + '\n')
            original(instance)
        with patch.object(verifier.FrozenInputs, 'verify', mutate_and_verify):
            self.assert_unverified(self.run_proof(), 'input stat changed')

    def test_one_failure_discards_other_successful_target(self):
        self.fixture()
        self.mutate_entry(4, values=[127])
        report = self.run_proof([(4, 3, 30), (3, 3, 30)])
        self.assert_unverified(report)
        self.assertEqual(len(report['failures']), 1)

    def test_reader_original_result_must_be_exact_gap(self):
        self.fixture()
        with sqlite3.connect(self.comparison / 'comparison.sqlite') as db:
            db.execute("UPDATE structural SET reason='unsupported' WHERE stage=3")
        self.assert_unverified(self.run_proof(), 'historical reader gap')

    def test_explicit_pair_and_target_limits(self):
        self.fixture()
        self.assert_unverified(self.run_proof([(3, 3, 50)]), 'actual comparison pair')
        for targets in ([(2, 3, 30)], [(3, 3, 30)] * 2, [(3, i, i) for i in range(1, 8)]):
            with self.assertRaisesRegex(ValueError, 'distinct explicit P3/P4'):
                self.run_proof(targets)

    def test_oversized_native_artifact_fails_before_connect(self):
        self.fixture()
        path = self.grh / 'P3/design.json'
        path.write_bytes(b' ' * (verifier.MAX_FILE + 1))
        with patch.object(verifier.sqlite3, 'connect', side_effect=AssertionError('must not connect')):
            self.assert_unverified(self.run_proof(), 'small-capture byte limit')

    def test_existing_output_is_never_overwritten(self):
        self.fixture()
        self.run_proof()
        with self.assertRaisesRegex(ValueError, 'new directory'):
            verifier.prove(self.comparison, self.grh, self.gsim, self.work / 'proof-1', [(3, 3, 30)])

    def test_cli_failure_has_nonzero_status_and_no_certificate(self):
        self.fixture()
        self.mutate_entry(4, values=[129])
        result = subprocess.run([sys.executable, str(Path(verifier.__file__)), '--comparison', str(self.comparison),
            '--grh', str(self.grh), '--gsim', str(self.gsim), '--output', str(self.work / 'cli-failure'),
            '--target', 'P3:3:30'], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assert_unverified(json.loads((self.work / 'cli-failure/summary.json').read_text()))


if __name__ == '__main__':
    unittest.main()
