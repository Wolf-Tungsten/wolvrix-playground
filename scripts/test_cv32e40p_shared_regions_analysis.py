import copy
import unittest

from cv32e40p_shared_regions_analysis import decompose_reports


def report(rows):
    return dict(cycles=100, values=rows, total=dict(values=len(rows),
        check_sites=sum(len(row['check_lines']) for row in rows),
        comparisons=sum(row['comparisons'] for row in rows),
        changes=sum(row['changes'] for row in rows)))


def value(index, comparisons, sites=1):
    return dict(id=str(index), value='v' + str(index), width=1, kind='kEq', group=0,
        check_lines=list(range(sites)), comparisons=comparisons, changes=0)


class ComparisonAccountingTests(unittest.TestCase):
    def test_removed_cached_checks_do_not_imply_equal_dynamic_savings(self):
        before = report([value(1, .01, 3), value(2, .1, 3), value(3, .2)])
        after = report([value(2, 1), value(3, .6), value(4, .2)])
        result = decompose_reports(before, after)
        self.assertEqual(result['removed_values'], 1)
        self.assertEqual(result['removed_cached_values'], 1)
        self.assertAlmostEqual(result['removed_cached_previous_comparisons'], .01)
        self.assertAlmostEqual(result['retained_cache_lost_delta'], .9)
        self.assertAlmostEqual(result['retained_comparison_delta'], 1.3)
        self.assertAlmostEqual(result['reconstructed_after_comparisons'], 1.8)
        self.assertGreater(result['after']['comparisons'], result['before']['comparisons'])

    def test_rejects_changed_id_and_duplicate_id(self):
        before = report([value(1, .1)])
        after = copy.deepcopy(before)
        after['values'][0]['value'] = 'another_value'
        with self.assertRaisesRegex(ValueError, 'identity'):
            decompose_reports(before, after)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            decompose_reports(before, report([value(1, .1), value(1, .2)]))

    def test_rejects_inconsistent_workload_or_aggregate(self):
        before = report([value(1, .1)])
        after = copy.deepcopy(before)
        after['cycles'] += 1
        with self.assertRaisesRegex(ValueError, 'cycle'):
            decompose_reports(before, after)
        after = copy.deepcopy(before)
        after['total']['comparisons'] += 1
        with self.assertRaisesRegex(ValueError, 'aggregate'):
            decompose_reports(before, after)


if __name__ == '__main__':
    unittest.main()
