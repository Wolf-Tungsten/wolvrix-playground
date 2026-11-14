"""Node-count closure and conservative native-blocker explanation contracts."""
import unittest

from f30_split_gap_accounting import classify_family, family_gap, resolve_blocker


def retain(reason, *blockers):
    return {'outcome': 'retain', 'reason': reason, 'blockers': list(blockers)}


class FamilyAccountingTests(unittest.TestCase):
    def test_asymmetric_split_counts_include_parent_retirement(self):
        self.assertEqual(classify_family(0, 64, True, False), 'gsim_only_split')
        self.assertEqual(family_gap(0, 64, True, False), 63)
        self.assertEqual(classify_family(8, 0, False, True), 'grh_only_split')
        self.assertEqual(family_gap(8, 0, False, True), -7)

    def test_live_residual_parent_changes_net_gap(self):
        self.assertEqual(classify_family(8, 8, True, False),
                         'both_split_equal_children_different_retention')
        self.assertEqual(family_gap(8, 8, True, False), -1)
        self.assertEqual(family_gap(8, 8, False, True), 1)

    def test_equal_counts_are_not_called_equal_geometry(self):
        self.assertEqual(classify_family(8, 8, False, False),
                         'both_split_equal_children_equal_retention')
        self.assertEqual(classify_family(8, 12, False, False),
                         'both_split_different_children')
        self.assertEqual(family_gap(8, 12, False, False), 4)

    def test_unsplit_and_unexplained_retirement_remain_distinct(self):
        self.assertEqual(classify_family(0, 0, True, True), 'neither_split')
        self.assertEqual(classify_family(0, 0, False, True), 'neither_split_with_retirement')
        self.assertEqual(family_gap(0, 0, False, True), 1)

    def test_weighted_family_gap_equals_inventory_growth(self):
        # Repeated physical families, including two separate current/next
        # register parents and a retained aggregate with split children.
        groups = [(3, (0, 64, True, False)), (2, (8, 0, False, True)),
                  (2, (4, 4, False, False)), (1, (8, 8, True, False))]
        weighted = sum(count * family_gap(*family) for count, family in groups)
        grh_growth = sum(count * (family[0] + int(family[2]) - 1)
                         for count, family in groups)
        gsim_growth = sum(count * (family[1] + int(family[3]) - 1)
                          for count, family in groups)
        self.assertEqual(weighted, 174)
        self.assertEqual(weighted, gsim_growth - grh_growth)

    def test_current_inventory_total_account_closes(self):
        grh_before, grh_after, grh_survivors = 7671189, 9328200, 7451358
        gsim_before, gsim_after, gsim_survivors = 7829556, 9635014, 7583519
        added_difference = (gsim_after - gsim_survivors) - (grh_after - grh_survivors)
        retired_difference = (gsim_before - gsim_survivors) - (grh_before - grh_survivors)
        self.assertEqual(added_difference, 174653)
        self.assertEqual(retired_difference, 26206)
        self.assertEqual(added_difference - retired_difference, 148447)

    def test_invalid_counts_and_survival_are_rejected(self):
        for values in ((-1, 0, True, True), (True, 0, True, True),
                       (0, 0, 1, True), (0, 0, True, None)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                family_gap(*values)


class BlockerResolutionTests(unittest.TestCase):
    def test_multiple_decisions_and_blockers_preserve_all_causes(self):
        result = resolve_blocker(1, {
            1: [retain('unsplit_upstream_array', 2, 3), retain('unsupported_array_producer')],
            2: [retain('unsplit_array_input', 4)],
            3: [retain('unsplit_state_payload', 5)],
            4: [retain('dynamic_consumer_index')],
            5: [retain('unsupported_state_family')],
        })
        self.assertTrue(result['complete'])
        self.assertEqual(result['terminal_reasons'], [
            'dynamic_consumer_index', 'unsupported_array_producer', 'unsupported_state_family'])
        self.assertEqual(result['terminal_node_ids'], [1, 4, 5])
        self.assertEqual([row['path'] for row in result['terminals']], [[1], [1, 2, 4], [1, 3, 5]])

    def test_dynamic_state_is_preserved_without_guessing_its_mechanism(self):
        result = resolve_blocker(1, {1: [retain('dynamic_state_index', 9)],
                                     9: [retain('dynamic_consumer_index')]})
        self.assertEqual(result['terminal_reasons'], ['dynamic_state_index'])
        self.assertEqual(result['terminals'][0]['blockers'], [9])
        self.assertEqual(result['terminal_node_ids'], [1])
        self.assertTrue(result['complete'])

    def test_cycle_does_not_hide_another_terminal_branch(self):
        result = resolve_blocker(1, {1: [retain('unsplit_array_input', 2, 3)],
            2: [retain('unsplit_upstream_array', 1)], 3: [retain('dynamic_update_index')]})
        self.assertFalse(result['complete'])
        self.assertEqual(result['terminal_reasons'], ['dynamic_update_index'])
        self.assertEqual(result['issues'], [{'kind': 'cycle', 'node_id': 1, 'path': [1, 2, 1]}])

    def test_absent_decision_and_absent_blocker_are_explicit(self):
        result = resolve_blocker(1, {1: [retain('unsplit_state_payload', 2, 3)],
                                     2: [retain('unsplit_upstream_array')]})
        self.assertFalse(result['complete'])
        self.assertEqual(result['terminal_reasons'], [])
        self.assertEqual([(row['kind'], row['path']) for row in result['issues']],
                         [('missing_blocker', [1, 2]), ('missing_decisions', [1, 3])])
        self.assertEqual(resolve_blocker(9, {})['issues'][0]['kind'], 'missing_decisions')

    def test_diamond_keeps_both_native_paths_without_duplicate_same_fact(self):
        result = resolve_blocker(1, {1: [retain('unsplit_array_input', 3, 2, 2)],
            2: [retain('unsplit_upstream_array', 4)],
            3: [retain('unsplit_state_payload', 4)],
            4: [retain('dynamic_consumer_index'), retain('dynamic_consumer_index')]})
        self.assertEqual(result['terminal_reasons'], ['dynamic_consumer_index'])
        self.assertEqual([row['path'] for row in result['terminals']], [[1, 2, 4], [1, 3, 4]])

    def test_non_retaining_decision_cannot_become_retention_cause(self):
        result = resolve_blocker(1, {1: [retain('unsplit_array_input', 2)],
            2: [{'outcome': 'replace', 'reason': 'static_array_split', 'blockers': []}]})
        self.assertFalse(result['complete'])
        self.assertEqual(result['terminal_reasons'], [])
        self.assertEqual(result['issues'][0]['kind'], 'non_retaining_decision')
        self.assertEqual(result['issues'][0]['reason'], 'static_array_split')

    def test_deep_chain_does_not_depend_on_python_recursion_limit(self):
        decisions = {node: [retain('unsplit_array_input', node + 1)] for node in range(1, 1101)}
        decisions[1101] = [retain('unsupported_state_family')]
        result = resolve_blocker(1, decisions)
        self.assertTrue(result['complete'])
        self.assertEqual(result['terminal_node_ids'], [1101])
        self.assertEqual(len(result['terminals'][0]['path']), 1101)

    def test_malformed_evidence_is_rejected(self):
        for decisions in ({1: 'retain'}, {1: [{}]}, {1: [retain('unsplit_array_input', True)]}):
            with self.subTest(decisions=decisions), self.assertRaises(ValueError):
                resolve_blocker(1, decisions)


if __name__ == '__main__':
    unittest.main()
