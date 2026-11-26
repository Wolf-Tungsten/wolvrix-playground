from __future__ import annotations

import json
import unittest

from f36_grh_access import grh_accesses
from f36_gsim_access import gsim_accesses
from f36_state_port_compare import access_geometry, compare_accesses, grh_type


class F36StatePortCompareTests(unittest.TestCase):
    def test_array_shape_uses_leaf_width(self):
        state = {'kind': 'kRegister', 'width': 1, 'signed': False, 'shape': [64]}
        self.assertEqual(grh_type(state), ('register', 1, False, (64,)))

    def test_whole_and_indexed_reads_both_count(self):
        state = {'kind': 'kRegister', 'width': 8, 'signed': False, 'shape': [4, 3]}
        indexed = {'kind': 'kRegisterReadArrayPort', 'target_resolution': 'resolved',
                   'operands': [{'width': 2}], 'results': [{'width': 8, 'shape': [3]}]}
        actions = [{'kind': 'kRegisterReadPort', 'target_resolution': 'resolved'},
                   indexed, indexed]
        actions[0]['results'] = [{'width': 8, 'shape': [4, 3]}]
        accesses, issues = grh_accesses(state, actions)
        self.assertEqual(issues, [])
        self.assertEqual(access_geometry(accesses)['read'], {(0, (4, 3), 8), (1, (3,), 8)})

    def test_same_projection_matches_across_index_values_and_duplicates(self):
        left = access_geometry([('write', (0,), (3,), 8), ('write', (1,), (3,), 8)])
        right = access_geometry([('write', (None,), (3,), 8)])
        self.assertEqual(compare_accesses(left, right, [], [])[0], 'match')

    def test_extra_index_axis_changes_shape(self):
        left = access_geometry([('read', (None,), (3,), 8)])
        right = access_geometry([('read', (None, None), (), 8)])
        status, details = compare_accesses(left, right, [], [])
        self.assertEqual(status, 'mismatch')
        self.assertEqual(details['read']['grh_only'][0]['indexed_axes'], 1)
        self.assertEqual(details['read']['gsim_only'][0]['indexed_axes'], 2)
        self.assertEqual(details['write']['status'], 'match')

    def test_gsim_array_read_recovers_remaining_shape(self):
        state = {'native_kind': 'NODE_REG_SRC', 'state_id': '1', 'shape_json': '[4,3]', 'width': '8'}
        index = {'op': 'OP_INDEX_INT', 'values': [2], 'children': []}
        root = {'op': 'OP_EMPTY', 'node_id': 1, 'children': [index]}
        actions = [{'action_kind': 'read-reference', 'root_json': json.dumps(root)}]
        accesses, issues = gsim_accesses(state, actions)
        self.assertEqual(issues, [])
        self.assertEqual(access_geometry(accesses)['read'], {(1, (3,), 8)})

    def test_gsim_reset_write_has_whole_array_shape(self):
        state = {'native_kind': 'NODE_REG_SRC', 'state_id': '1', 'shape_json': '[4,3]', 'width': '8'}
        target = {'op': 'OP_EMPTY', 'node_id': 1, 'children': []}
        condition = {'op': 'OP_EMPTY', 'node_id': 3, 'children': []}
        value = {'op': 'OP_INT', 'text': '0', 'children': []}
        root = {'op': 'OP_RESET', 'children': [condition, value]}
        action = {'action_kind': 'reset', 'root_json': json.dumps(root), 'lvalue_json': json.dumps(target)}
        accesses, issues = gsim_accesses(state, [action])
        self.assertEqual(issues, [])
        self.assertEqual(access_geometry(accesses)['write'], {(0, (4, 3), 8)})

        root['children'][1] = target
        action['root_json'] = json.dumps(root)
        self.assertEqual(gsim_accesses(state, [action]), ([], []))

    def test_gsim_memory_write_combines_address_and_row_index(self):
        state = {'native_kind': 'NODE_MEMORY', 'state_id': '1', 'shape_json': '[4,3]', 'width': '8'}
        address = {'op': 'OP_EMPTY', 'node_id': 3, 'children': []}
        data = {'op': 'OP_EMPTY', 'node_id': 4, 'children': []}
        index = {'op': 'OP_INDEX_INT', 'values': [2], 'children': []}
        target = {'op': 'OP_EMPTY', 'node_id': 2, 'children': [index]}
        root = {'op': 'OP_WRITE_MEM', 'memory_id': 1, 'children': [address, data]}
        action = {'action_kind': 'write-access', 'port_id': '2',
                  'root_json': json.dumps(root), 'lvalue_json': json.dumps(target)}
        accesses, issues = gsim_accesses(state, [action])
        self.assertEqual(issues, [])
        self.assertEqual(access_geometry(accesses)['write'], {(2, (3,), 8)})


if __name__ == '__main__':
    unittest.main()
