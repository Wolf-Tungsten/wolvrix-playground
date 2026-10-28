from fractions import Fraction
from pathlib import Path
import tempfile
import unittest

from repcut_grhsim_solver_portfolio import check_capacity, cpu_groups, cpu_list, parse_audit, select_best


class PortfolioTests(unittest.TestCase):
    def test_cpu_ranges(self):
        self.assertEqual(cpu_list('0-2,5,8-9'), [0, 1, 2, 5, 8, 9])

    def test_eight_disjoint_balanced_groups_preserve_siblings(self):
        siblings = [[cpu, cpu + 192] for cpu in range(192)]
        groups = cpu_groups(list(range(384)), 8, siblings + siblings)
        self.assertEqual([len(group) for group in groups], [48] * 8)
        self.assertEqual(sorted(cpu for group in groups for cpu in group), list(range(384)))
        for pair in siblings:
            self.assertTrue(any(set(pair) <= set(group) for group in groups))

    def test_overlapping_topology_is_rejected(self):
        with self.assertRaises(ValueError):
            cpu_groups([0, 1, 2], 2, [[0, 1], [1, 2]])

    def test_capacity_boundary_and_overflow(self):
        audit = dict(k=2, axes=[dict(axis='x', total=200, max=105),
                                dict(axis='y', total=200, max=106)])
        checks = check_capacity(audit, Fraction(5, 100))
        self.assertEqual([row['feasible'] for row in checks], [True, False])

    def test_lower_infeasible_km1_cannot_win(self):
        results = [dict(status='pass', capacity_feasible=True, full_km1=120, seed=0),
                   dict(status='pass', capacity_feasible=True, full_km1=100, seed=3),
                   dict(status='failed', capacity_feasible=False, full_km1=1, seed=2),
                   dict(status='pass', capacity_feasible=True, full_km1=100, seed=1)]
        self.assertEqual(select_best(results)['seed'], 1)
        with self.assertRaises(ValueError):
            select_best([results[2]])

    def test_parse_independent_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'audit.txt'
            path.write_text('k=2\nnodes=4\nkm1_cut=17\naxis,total,capacity,max,min,overloaded_parts\n'
                            'rising,100,52,51,49,0\npart,atoms,rising\n0,2,49\n1,2,51\n')
            audit = parse_audit(path)
            self.assertEqual(audit['km1_cut'], 17)
            self.assertEqual(audit['parts'][1], dict(part=1, atoms=2, rising=51))
            self.assertTrue(check_capacity(audit, Fraction(5, 100))[0]['feasible'])


if __name__ == '__main__':
    unittest.main()
