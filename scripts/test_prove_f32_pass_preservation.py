"""Independent formal-rooted positive/mutation contracts for pass replay."""
from __future__ import annotations

import copy
import json
import os
import unittest
from unittest.mock import patch

import prove_f32_pass_preservation as proof
import test_prove_f32_reconstruction as reconstruction_tests

artifact, write_json = reconstruction_tests.artifact, reconstruction_tests.write_json


def fixture(*, changed=False):
    values = [{'id': identifier, 'w': width, 'sgn': False, 'type': 'logic', 'domain': '4state',
               'in': identifier in (1, 2), 'out': identifier == 5, 'inout': False}
              for identifier, width in ((1, 8), (2, 1), (3, 8), (4, 8), (5, 8), (6, 8))]
    nodes = [{'id': identifier, 'parent': 1, 'name': name, 'ops': [], 'anchors': [anchor]}
             for identifier, name, anchor in ((1, 'payload', 1), (2, 'guard', 2), (3, 'output', 5))]
    ops = [{'id': 1, 'kind': 'kNot', 'in': [1], 'out': [3]},
           {'id': 2, 'kind': 'kNot', 'in': [1], 'out': [4]},
           {'id': 3, 'kind': 'kAssign' if changed else 'kMux',
            'in': [3] if changed else [2, 3, 4], 'out': [5]}]
    return {'formatVersion': 5, 'graphs': [{'symbol': 'top', 'dialects': {'grh': 4},
        'semanticTree': {'namesFlattened': True, 'nodes': nodes, 'rootPath': 1, 'sourceUnit': 'original',
                         'circuit': 'top', 'paths': [{'id': 1, 'parent': 0, 'name': 'top'}]},
        'vals': values, 'ops': ops,
        'metadata': {'firrtl.semanticPortNames': {'t': 'string[]', 'vs': ['payload', 'guard', 'output']},
                     'firrtl.semanticPortNodes': {'t': 'int[]', 'vs': [1, 2, 3]}},
        'ports': {'in': [{'name': 'payload', 'val': 1}, {'name': 'guard', 'val': 2}],
                  'out': [{'name': 'output', 'val': 5}], 'inout': []}}]}


def projection_fixture(leaf_width):
    native = fixture(changed=True)
    graph = native['graphs'][0]
    graph['vals'] = graph['vals'][:2]
    graph['vals'][0]['w'] = 32
    graph['vals'].append({'id': 5, 'w': leaf_width * 4, 'sgn': False, 'type': 'logic',
                          'domain': '4state', 'shape': [4], 'out': True})
    graph['ops'] = []
    values = [3, 4, 6, 7]
    for cell, identifier in enumerate(values):
        graph['vals'].append({'id': identifier, 'w': leaf_width, 'sgn': False,
                              'type': 'logic', 'domain': '4state'})
        graph['ops'].append({'id': cell + 1, 'kind': 'kSliceStatic', 'in': [1], 'out': [identifier],
            'attrs': {'sliceStart': {'t': 'int', 'v': cell * 8},
                      'sliceEnd': {'t': 'int', 'v': cell * 8 + leaf_width - 1}}})
    graph['ops'].append({'id': 5, 'kind': 'kConcat', 'in': list(reversed(values)), 'out': [5]})
    row = {'node_id': '3', 'role': 'value', 'value_id': '1005', 'value_generation': '7',
           'operation_id': '2005', 'operation_generation': '9', 'native_kind': 'kConcat',
           'width': str(leaf_width), 'signed': '0',
           'shape_json': '[4]', 'logic_domain': '4state', 'source_width': '8', 'source_signed': '0',
           'source_shape_json': '[4]', 'source_shape_field_depths_json': '[0]', 'projection_json': '[-1]',
           'source_bit_offset': '0', 'source_bit_width': str(leaf_width), 'evidence': 'native-binding'}
    return native, [row]


def identity_rows(native):
    graph = native['graphs'][0]
    return [{'kind': kind, 'serialized_id': str(item['id']), 'native_index': str(item['id'] + offset),
             'native_generation': str(generation)}
            for kind, field, offset, generation in (('value', 'vals', 1000, 7), ('operation', 'ops', 2000, 9))
            for item in graph[field]]


def projection_model(fixture, arena):
    native, endpoints = fixture
    return proof.Model(native, arena, endpoints, identity_rows(native))


class ReplayContracts(unittest.TestCase):
    def compare(self, before, after):
        arena = proof.Arena()
        rows = proof.compare_models(proof.Model(before, arena), proof.Model(after, arena), 1)
        return {row['node_id']: row for row in rows}

    def test_changed_mux_cone_from_actual_formal_inputs_is_proved(self):
        rows = self.compare(fixture(), fixture(changed=True))
        self.assertTrue(rows[3]['anchor_value_preservation_proved'])
        self.assertFalse(rows[3]['complete_node_preservation_proved'])

    def test_selecting_different_arm_and_undefined_values_cannot_pass(self):
        before, after = fixture(), fixture(changed=True)
        after['graphs'][0]['ops'][0]['kind'] = 'kAssign'
        rows = self.compare(before, after)
        self.assertFalse(rows[3]['anchor_value_preservation_proved'])
        self.assertIn('lane forms differ', rows[3]['reason'])

    def test_common_node_name_is_not_an_input_binding(self):
        after = fixture(changed=True)
        after['graphs'][0]['semanticTree']['nodes'][0]['anchors'] = [6]
        with self.assertRaisesRegex(ValueError, 'unique actual Node/anchor binding'):
            self.compare(fixture(), after)

    def test_changed_formal_semantic_identity_is_rejected(self):
        after = fixture(changed=True)
        graph = after['graphs'][0]
        graph['semanticTree']['nodes'][0]['id'] = 7
        graph['metadata']['firrtl.semanticPortNodes']['vs'][0] = 7
        with self.assertRaisesRegex(ValueError, 'semantic formal metadata'):
            self.compare(fixture(), after)

    def test_malformed_or_drifting_native_identity_metadata_is_rejected(self):
        for mutate in (
                lambda graph: graph['metadata']['firrtl.semanticPortNames'].update(t='int[]'),
                lambda graph: graph['metadata']['firrtl.semanticPortNodes']['vs'].__setitem__(1, 1),
                lambda graph: graph['metadata']['firrtl.semanticPortNames']['vs'].__setitem__(1, ''),
                lambda graph: graph['ports']['in'][1].update(name='payload'),
                lambda graph: graph['ports']['out'][0].update(val=6),
                lambda graph: graph['semanticTree']['nodes'][0].update(parent=99)):
            after = fixture(changed=True)
            mutate(after['graphs'][0])
            with self.assertRaises(ValueError):
                self.compare(fixture(), after)
        for field in ('symbol', 'sourceUnit', 'circuit', 'path-name'):
            after = fixture(changed=True)
            graph = after['graphs'][0]
            if field == 'symbol':
                graph[field] = 'another'
            elif field == 'path-name':
                graph['semanticTree']['paths'][0]['name'] = 'another'
            else:
                graph['semanticTree'][field] = 'another'
            with self.assertRaisesRegex(ValueError, 'identity context'):
                self.compare(fixture(), after)

    def test_compact_value_and_operation_ids_can_change(self):
        before, after = fixture(), fixture(changed=True)
        graph = after['graphs'][0]
        for value in graph['vals']:
            value['id'] += 100
        for op in graph['ops']:
            op['id'] += 200
            op['in'] = [value + 100 for value in op['in']]
            op['out'] = [value + 100 for value in op['out']]
        for node in graph['semanticTree']['nodes']:
            node['anchors'] = [value + 100 for value in node['anchors']]
        for direction in ('in', 'out'):
            for port in graph['ports'][direction]:
                port['val'] += 100
        self.assertTrue(self.compare(before, after)[3]['anchor_value_preservation_proved'])

    def test_signed_unknown_state_and_new_nodes_remain_unproved(self):
        for kind in ('kDFF', 'unknown'):
            after = fixture(changed=True)
            after['graphs'][0]['ops'][-1]['kind'] = kind
            self.assertFalse(self.compare(fixture(), after)[3]['anchor_value_preservation_proved'])
        after = fixture(changed=True)
        after['graphs'][0]['vals'][4]['sgn'] = True
        self.assertFalse(self.compare(fixture(), after)[3]['anchor_value_preservation_proved'])
        after = fixture(changed=True)
        after['graphs'][0]['semanticTree']['nodes'].append(
            {'id': 9, 'parent': 1, 'name': 'new', 'ops': [], 'anchors': [5]})
        self.assertFalse(self.compare(fixture(), after)[9]['anchor_value_preservation_proved'])

    def test_unknown_literal_is_never_silently_zero(self):
        before, after = fixture(), fixture(changed=True)
        after['graphs'][0]['ops'][0] = {'id': 1, 'kind': 'kConstant', 'in': [], 'out': [3],
                                      'attrs': {'constValue': {'t': 'string', 'v': "8'bx"}}}
        result = self.compare(before, after)[3]
        self.assertFalse(result['anchor_value_preservation_proved'])
        self.assertIn('unknown literal', result['reason'])

    def test_nonformal_unbound_value_cannot_be_a_free_equal_leaf(self):
        after = fixture(changed=True)
        after['graphs'][0]['ops'][0]['in'] = [6]
        result = self.compare(fixture(), after)[3]
        self.assertFalse(result['anchor_value_preservation_proved'])
        self.assertIn('unbound nonformal', result['reason'])

    def test_geometry_change_and_duplicate_producer_fail_closed(self):
        after = fixture(changed=True)
        after['graphs'][0]['vals'][4]['w'] = 4
        self.assertFalse(self.compare(fixture(), after)[3]['anchor_value_preservation_proved'])
        after = fixture(changed=True)
        after['graphs'][0]['ops'].append({'id': 9, 'kind': 'kAssign', 'in': [1], 'out': [5]})
        with self.assertRaisesRegex(ValueError, 'duplicate native value producer'):
            self.compare(fixture(), after)

    def test_array_update_leaf_width_change_preserves_static_observer(self):
        def array_fixture(leaf_width):
            native = fixture(changed=True)
            graph = native['graphs'][0]
            graph['vals'] = [graph['vals'][0], graph['vals'][1]]
            graph['vals'][1]['w'] = 3  # full dynamic index is retained
            for identifier, width, shape in ((3, leaf_width * 2, [2]), (4, leaf_width * 2, [2]),
                                              (5, 3, []), (6, 1, []), (7, 8, []),
                                              (8, leaf_width, []), (9, 32, []), (10, leaf_width, [])):
                graph['vals'].append({'id': identifier, 'w': width, 'sgn': False, 'type': 'logic',
                                     'domain': '4state', 'shape': shape, 'out': identifier == 5})
            graph['ops'] = [
                {'id': 1, 'kind': 'kConstant', 'in': [], 'out': [7], 'attrs': {'constValue': {'t': 'string', 'v': '0'}}},
                {'id': 2, 'kind': 'kConstant', 'in': [], 'out': [6], 'attrs': {'constValue': {'t': 'string', 'v': "1'b1"}}},
                {'id': 3, 'kind': 'kSliceStatic', 'in': [1], 'out': [8], 'attrs': {
                    'sliceStart': {'t': 'int', 'v': 0}, 'sliceEnd': {'t': 'int', 'v': leaf_width - 1}}},
                {'id': 4, 'kind': 'kConcat', 'in': [7, 8], 'out': [3]},
                {'id': 5, 'kind': 'kCombArrayUpdate', 'in': [3, 6, 2, 8], 'out': [4],
                 'attrs': {'indexCounts': {'t': 'int[]', 'vs': [1]}}},
                {'id': 6, 'kind': 'kConstant', 'in': [], 'out': [9], 'attrs': {'constValue': {'t': 'string', 'v': "32'b1"}}},
                {'id': 7, 'kind': 'kSliceArray', 'in': [4, 9], 'out': [10]},
                {'id': 8, 'kind': 'kSliceStatic', 'in': [10], 'out': [5], 'attrs': {
                    'sliceStart': {'t': 'int', 'v': 0}, 'sliceEnd': {'t': 'int', 'v': 2}}}]
            return native
        self.assertTrue(self.compare(array_fixture(8), array_fixture(3))[3]['anchor_value_preservation_proved'])
        changed_index = array_fixture(3)
        changed_index['graphs'][0]['ops'][4]['in'][2] = 7
        self.assertFalse(self.compare(array_fixture(8), changed_index)[3]['anchor_value_preservation_proved'])
        shortened_index = array_fixture(3)
        shortened_index['graphs'][0]['vals'][1]['w'] = 1
        with self.assertRaisesRegex(ValueError, 'formal input identities'):
            self.compare(array_fixture(8), shortened_index)
        first, second = array_fixture(8), array_fixture(8)
        for native in (first, second):
            update = native['graphs'][0]['ops'][4]
            update['attrs']['indexCounts']['vs'] = [1, 1]
            update['in'].extend([6, 2, 7])
        second['graphs'][0]['ops'][4]['in'][4] = 7
        second['graphs'][0]['ops'][4]['in'][-1] = 8
        self.assertFalse(self.compare(first, second)[3]['anchor_value_preservation_proved'])

    def test_multidimensional_suffix_coordinates_match_independent_integer_oracle(self):
        native = fixture(changed=True)
        graph = native['graphs'][0]
        graph['vals'] = graph['vals'][:2]
        for identifier, width, shape in ((3, 12, [2, 3]), (4, 12, [2, 3]), (5, 2, []),
                                          (6, 1, []), (7, 6, [3]), (8, 32, []), (9, 6, [3]),
                                          (10, 32, [])):
            graph['vals'].append({'id': identifier, 'w': width, 'sgn': False, 'type': 'logic',
                                 'domain': '4state', 'shape': shape, 'out': identifier == 5})
        graph['ops'] = [
            {'id': 1, 'kind': 'kConstant', 'in': [], 'out': [3],
             'attrs': {'constValue': {'t': 'string', 'v': '0'}}},
            {'id': 2, 'kind': 'kConstant', 'in': [], 'out': [6],
             'attrs': {'constValue': {'t': 'string', 'v': "1'b1"}}},
            {'id': 3, 'kind': 'kAssign', 'in': [1], 'out': [7]},
            {'id': 4, 'kind': 'kCombArrayUpdate', 'in': [3, 6, 2, 7], 'out': [4],
             'attrs': {'indexCounts': {'t': 'int[]', 'vs': [1]}}},
            {'id': 5, 'kind': 'kConstant', 'in': [], 'out': [8],
             'attrs': {'constValue': {'t': 'string', 'v': "32'b1"}}},
            {'id': 6, 'kind': 'kSliceArray', 'in': [4, 8], 'out': [9]},
            {'id': 7, 'kind': 'kConstant', 'in': [], 'out': [10],
             'attrs': {'constValue': {'t': 'string', 'v': "32'd2"}}},
            {'id': 8, 'kind': 'kSliceArray', 'in': [9, 10], 'out': [5]}]
        arena = proof.Arena()
        bits = proof.Model(native, arena).bits(5)

        def evaluate(identifier, a, guard):
            term = arena.terms[identifier]
            if term[0] == 'literal':
                return int(term[1])
            if term[0] == 'formal-input':
                return ((a if term[1][0] == 1 else guard) >> term[2]) & 1
            if term[0] == 'kAnd':
                return evaluate(term[1], a, guard) & evaluate(term[2], a, guard)
            if term[0] == 'defined-logical-equality':
                return int(all(evaluate(left, a, guard) == evaluate(right, a, guard)
                               for left, right in zip(term[1], term[2])))
            if term[0] == 'defined-mux':
                return evaluate(term[2] if evaluate(term[1], a, guard) else term[3], a, guard)
            self.fail('unexpected symbolic term')

        for a in range(256):
            for guard in (0, 1):
                expected = ((a >> 4) & 3) if guard else 0
                actual = sum(evaluate(bit, a, guard) << index for index, bit in enumerate(bits))
                self.assertEqual(actual, expected)
        # Rank-two scalar and rank-zero whole writes exercise the suffix-size
        # boundaries independently of the lane-normalization equality check.
        scalar = copy.deepcopy(native)
        scalar_graph = scalar['graphs'][0]
        scalar_graph['vals'].append({'id': 11, 'w': 2, 'sgn': False, 'type': 'logic', 'domain': '4state'})
        scalar_graph['ops'].append({'id': 9, 'kind': 'kConstant', 'in': [], 'out': [11],
                                   'attrs': {'constValue': {'t': 'string', 'v': "2'b11"}}})
        scalar_graph['ops'][3] = {'id': 4, 'kind': 'kCombArrayUpdate', 'in': [3, 6, 8, 10, 11], 'out': [4],
                                  'attrs': {'indexCounts': {'t': 'int[]', 'vs': [2]}}}
        arena = proof.Arena()
        scalar_bits = proof.Model(scalar, arena).bits(5)
        self.assertEqual(sum(evaluate(bit, 0, 0) << index for index, bit in enumerate(scalar_bits)), 3)
        out_of_bounds = copy.deepcopy(scalar)
        oob_graph = out_of_bounds['graphs'][0]
        oob_graph['vals'].append({'id': 12, 'w': 32, 'sgn': False, 'type': 'logic', 'domain': '4state'})
        oob_graph['ops'].append({'id': 10, 'kind': 'kConstant', 'in': [], 'out': [12],
                                'attrs': {'constValue': {'t': 'string', 'v': "32'd3"}}})
        oob_graph['ops'][3]['in'][3] = 12
        arena = proof.Arena()
        oob_bits = proof.Model(out_of_bounds, arena).bits(5)
        self.assertEqual(sum(evaluate(bit, 0, 0) << index for index, bit in enumerate(oob_bits)), 0)
        invalid_read = copy.deepcopy(scalar)
        invalid_read['graphs'][0]['ops'][4]['attrs']['constValue']['v'] = "32'd2"
        with self.assertRaisesRegex(proof.Unsupported, 'array read geometry or bounds'):
            proof.Model(invalid_read, proof.Arena()).bits(5)
        whole = copy.deepcopy(native)
        whole['graphs'][0]['ops'][3] = {'id': 4, 'kind': 'kCombArrayUpdate', 'in': [3, 6, 3], 'out': [4],
            'attrs': {'indexCounts': {'t': 'int[]', 'vs': [0]}}}
        whole_model = proof.Model(whole, proof.Arena())
        self.assertTrue(all(bit == whole_model.arena.zero for bit in whole_model.bits(5)))

    def test_controls_bounds_and_symbolic_budgets_fail_closed(self):
        after = fixture(changed=False)
        graph = after['graphs'][0]
        graph['ops'][0] = {'id': 1, 'kind': 'kConstant', 'in': [], 'out': [3],
                          'attrs': {'constValue': {'t': 'string', 'v': "8'bz"}}}
        self.assertFalse(self.compare(fixture(), after)[3]['anchor_value_preservation_proved'])
        graph['ops'][-1]['in'][0] = 1
        self.assertIn('non-bit mux control', self.compare(fixture(), after)[3]['reason'])
        with patch.object(proof, 'MAX_TERMS', 2):
            rows = self.compare(fixture(), fixture(changed=True))
        self.assertTrue(all(row['status'] == 'unproved' for row in rows.values()))
        with patch.object(proof, 'MAX_BITS', 4):
            with self.assertRaisesRegex(ValueError, 'oversized native logical type'):
                self.compare(fixture(), fixture(changed=True))

    def test_native_source_leaf_projection_is_a_distinct_conditional_certificate(self):
        arena = proof.Arena()
        old, new = projection_fixture(8), projection_fixture(3)
        rows = proof.compare_models(projection_model(old, arena), projection_model(new, arena), 2)
        certificate = next(row for row in rows if row['node_id'] == 3)
        self.assertEqual(certificate['status'], 'retained_projection_preservation_proved')
        self.assertTrue(certificate['retained_projection_preservation_proved'])
        self.assertFalse(certificate['anchor_value_preservation_proved'])
        self.assertFalse(certificate['full_width_anchor_equality_proved'])
        self.assertFalse(certificate['discarded_bits_unobservable_proved'])
        self.assertEqual((certificate['leaf_count'], certificate['before_leaf_width'], certificate['after_leaf_width']),
                         (4, 8, 3))
        self.assertEqual(certificate['retained_bits_proved'], 12)

    def test_source_candidates_and_invalid_geometry_never_create_projection_evidence(self):
        for field, value in (('evidence', 'anchor-candidate'), ('source_width', '-1'),
                             ('source_width', '16'), ('source_bit_offset', '2'), ('source_bit_width', '4'),
                             ('source_shape_json', '[2,2]'), ('source_shape_json', '[4.0]'),
                             ('projection_json', '[0]'), ('projection_json', '[-1.0]'),
                             ('source_shape_field_depths_json', '[1]'), ('width', '8'),
                             ('source_signed', '1'), ('value_id', '0')):
            old, new = projection_fixture(8), projection_fixture(3)
            new[1][0][field] = value
            arena = proof.Arena()
            with self.subTest(field=field, value=value):
                rows = proof.compare_models(projection_model(old, arena), projection_model(new, arena), 2)
                row = next(row for row in rows if row['node_id'] == 3)
                self.assertEqual(row['status'], 'unproved')
                self.assertFalse(row['retained_projection_preservation_proved'])

    def test_projection_checks_every_cell_stride_not_packed_low_prefix(self):
        for mutation in ('swap-cells', 'wrong-source-offset'):
            old, new = projection_fixture(8), projection_fixture(3)
            if mutation == 'swap-cells':
                new[0]['graphs'][0]['ops'][-1]['in'].reverse()
            else:
                # This is the common wrong packed-prefix mapping: it copies
                # input bits 0..11 rather than each original leaf's low3 bits.
                for cell, op in enumerate(new[0]['graphs'][0]['ops'][:4]):
                    op['attrs']['sliceStart']['v'] = cell * 3
                    op['attrs']['sliceEnd']['v'] = cell * 3 + 2
            arena = proof.Arena()
            rows = proof.compare_models(projection_model(old, arena), projection_model(new, arena), 2)
            row = next(row for row in rows if row['node_id'] == 3)
            self.assertEqual(row['status'], 'unproved')
            self.assertIn('symbolic lanes differ', row['reason'])

    def test_projection_requires_real_anchor_and_defining_operation_identity_mapping(self):
        for field, value in (('role', 'effect'), ('value_id', '1003'), ('value_id', '9999'),
                             ('value_generation', '8'), ('operation_id', '2001'), ('operation_id', '9999'),
                             ('operation_id', '0'), ('operation_generation', '8'), ('native_kind', 'kAssign')):
            old, new = projection_fixture(8), projection_fixture(3)
            new[1][0][field] = value
            arena = proof.Arena()
            with self.subTest(field=field, value=value):
                rows = proof.compare_models(projection_model(old, arena), projection_model(new, arena), 2)
                self.assertEqual(next(row for row in rows if row['node_id'] == 3)['status'], 'unproved')
        old, new = projection_fixture(8), projection_fixture(3)
        arena = proof.Arena()
        rows = proof.compare_models(proof.Model(old[0], arena, old[1]), proof.Model(new[0], arena, new[1]), 2)
        self.assertIn('explicit native-to-serialized identity map', next(row for row in rows if row['node_id'] == 3)['reason'])
        for mutation in ('missing-value', 'missing-op', 'duplicate-raw', 'extra-serialized'):
            rows = identity_rows(new[0])
            if mutation == 'missing-value':
                rows = [row for row in rows if row['kind'] != 'value' or row['serialized_id'] != '5']
            elif mutation == 'missing-op':
                rows = [row for row in rows if row['kind'] != 'operation' or row['serialized_id'] != '5']
            elif mutation == 'duplicate-raw':
                rows[1]['native_index'] = rows[0]['native_index']
            else:
                rows.append({'kind': 'value', 'serialized_id': '999', 'native_index': '9999', 'native_generation': '0'})
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                proof.Model(new[0], proof.Arena(), new[1], rows)


class FrozenCaptureContracts(unittest.TestCase):
    def setUp(self):
        # Reuse only the native five-snapshot fixture writer, never its proof.
        self.fixture_case = reconstruction_tests.ReconstructionContracts(methodName='runTest')
        test_root = os.environ.get('F32_PRESERVATION_TEST_ROOT',
            str(proof.ROOT / 'ptmp/firrtl-ingest/F32/preservation-contract-tmp'))
        with patch.dict(os.environ, {'F32_RECONSTRUCTION_TEST_ROOT': test_root}):
            self.fixture_case.setUp()
        self.addCleanup(self.fixture_case.tearDown)
        self.fixture_case.fixture()
        self.work = self.fixture_case.work
        self.comparison, self.grh = self.fixture_case.comparison, self.fixture_case.grh
        self.captures = self.fixture_case.captures
        for stage in range(5):
            path = self.grh / f'P{stage}' / 'design.json'
            native = fixture(changed=stage > 0)
            graph = native['graphs'][0]
            # Keep this writer's five-ID inventory, with two unused identities.
            graph['semanticTree']['nodes'].extend([
                {'id': 5, 'parent': 1, 'name': 'extra5', 'ops': [], 'anchors': [3]},
                {'id': 6, 'parent': 1, 'name': 'extra6', 'ops': [], 'anchors': [4]}])
            write_json(path, native)
            self.captures['grh']['snapshots'][f'P{stage}']['artifacts']['structure'] = artifact(path)
        write_json(self.grh / 'summary.json', self.captures['grh'])
        checkpoint = self.fixture_case.inputs
        checkpoint['capture_summaries']['grh']['sha256'] = artifact(self.grh / 'summary.json')['sha256']
        write_json(self.comparison / 'inputs.json', checkpoint)

    def test_full_frozen_capture_reports_conditional_anchor_evidence_only(self):
        output = self.work / 'preservation'
        before = {path: path.read_bytes() for path in (self.grh / 'summary.json', self.comparison / 'summary.json')}
        report = proof.prove(self.comparison, self.grh, output)
        self.assertTrue(report['complete'])
        self.assertFalse(report['window_acceptance'])
        self.assertFalse(report['semantic_acceptance'])
        self.assertFalse(report['four_state_behavior_proved'])
        self.assertFalse(report['certificate_ingestion_implemented'])
        self.assertEqual(report['results_by_boundary']['P1']['anchor_value_preservation_proved'], 5)
        self.assertTrue(all(path.read_bytes() == body for path, body in before.items()))
        self.assertTrue(all(row['sha256'] == row['sha256_after'] for row in report['frozen_inputs']))

    def test_stale_artifact_and_missing_formal_binding_do_not_publish_success(self):
        path = self.grh / 'P1/design.json'
        path.write_text(path.read_text() + ' ')
        output = self.work / 'stale'
        with self.assertRaisesRegex(ValueError, 'artifact path/hash/bytes mismatch'):
            proof.prove(self.comparison, self.grh, output)
        self.assertFalse((output / 'summary.json').exists())

    def test_frozen_native_source_endpoints_bind_projection_certificate(self):
        for stage in range(5):
            base = self.grh / f'P{stage}'
            native, endpoints = projection_fixture(8 if stage < 2 else 3)
            native['graphs'][0]['semanticTree']['nodes'].extend([
                {'id': 5, 'parent': 1, 'name': 'extra5', 'ops': [], 'anchors': [3]},
                {'id': 6, 'parent': 1, 'name': 'extra6', 'ops': [], 'anchors': [4]}])
            write_json(base / 'design.json', native)
            record = self.captures['grh']['snapshots'][f'P{stage}']
            record['artifacts']['structure'] = artifact(base / 'design.json')
            for name in ('nodes.tsv', 'connections.tsv'):
                current = base / name
                lines = current.read_text().splitlines(keepends=True)
                header = json.loads(lines[0].split('\t', 1)[1])
                header['graph_id'] = '1'
                lines[0] = '#meta\t' + json.dumps(header) + '\n'
                current.write_text(''.join(lines))
                record['artifacts'][name] = artifact(current)
            path = base / 'node-endpoints.tsv'
            meta = json.loads(path.read_text().splitlines()[0].split('\t', 1)[1])
            meta['graph_id'] = '1'
            row = {'value_generation': '0', 'operation_id': '5', 'operation_generation': '0',
                   'native_kind': 'kConcat', **endpoints[0]}
            columns = reconstruction_tests.verifier.HEADERS['node-endpoints.tsv']
            record['artifacts']['node-endpoints.tsv'] = self.fixture_case.table(
                path, meta, [tuple(row[column] for column in columns)])
            mapping_path = base / 'serialization-id-map.tsv'
            mapping_meta = {**meta, 'schema': 'grh.native-serialization-map.v1', 'graph_index': 1, 'graph_generation': 0,
                            'graph_symbol': 'top', 'session_id': meta['exchange_session_id']}
            mapping_rows = identity_rows(native)
            mapping_path.write_text('#meta\t' + json.dumps(mapping_meta) + '\n' +
                'kind\tserialized_id\tnative_index\tnative_generation\n' +
                ''.join('\t'.join(row[key] for key in ('kind', 'serialized_id', 'native_index', 'native_generation')) + '\n'
                        for row in mapping_rows) +
                '#footer\t' + json.dumps({'complete': True, 'rowCount': len(mapping_rows)}) + '\n')
            record['artifacts']['serialization-id-map.tsv'] = artifact(mapping_path)
        write_json(self.grh / 'summary.json', self.captures['grh'])
        checkpoint = self.fixture_case.inputs
        checkpoint['capture_summaries']['grh']['sha256'] = artifact(self.grh / 'summary.json')['sha256']
        write_json(self.comparison / 'inputs.json', checkpoint)
        output = self.work / 'native-projection'
        report = proof.prove(self.comparison, self.grh, output)
        self.assertEqual(report['results_by_boundary']['P2']['retained_projection_preservation_proved'], 1)
        rows = [json.loads(line) for line in (output / 'anchor_certificates.jsonl').read_text().splitlines()]
        certificate = next(row for row in rows if row['boundary'] == 'P2' and row['node_id'] == 3)
        self.assertTrue(certificate['retained_projection_preservation_proved'])
        self.assertFalse(certificate['anchor_value_preservation_proved'])
        endpoint_path = str(self.grh / 'P2/node-endpoints.tsv')
        self.assertTrue(any(row['path'] == endpoint_path and row['sha256'] == row['sha256_after']
                            for row in report['frozen_inputs']))
        # Changing a source offset after publication invalidates its frozen
        # artifact hash before any new projection certificate can be emitted.
        path = self.grh / 'P2/node-endpoints.tsv'
        path.write_text(path.read_text().replace('\t0\t3\tnative-binding', '\t1\t3\tnative-binding'))
        rejected = self.work / 'mutated-projection'
        with self.assertRaisesRegex(ValueError, 'artifact path/hash/bytes mismatch'):
            proof.prove(self.comparison, self.grh, rejected)
        self.assertFalse((rejected / 'summary.json').exists())

    def test_verifier_source_drift_and_input_changes_prevent_success(self):
        output = self.work / 'changed-source'
        with patch.object(proof, 'LOADED_SOURCE_SHA256', '0' * 64):
            with self.assertRaisesRegex(ValueError, 'source changed since module load'):
                proof.prove(self.comparison, self.grh, output)
        self.assertFalse((output / 'summary.json').exists())
        original = proof.compare_models

        def mutate_after_replay(*args):
            rows = original(*args)
            path = self.grh / 'summary.json'
            path.write_text(path.read_text() + ' ')
            return rows

        output = self.work / 'changed-input'
        with patch.object(proof, 'compare_models', side_effect=mutate_after_replay):
            with self.assertRaisesRegex(ValueError, 'input stat changed'):
                proof.prove(self.comparison, self.grh, output)
        self.assertFalse((output / 'summary.json').exists())


if __name__ == '__main__':
    unittest.main()
