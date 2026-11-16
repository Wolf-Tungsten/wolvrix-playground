import tempfile
from pathlib import Path
import unittest

from cv32e40p_structure import generated_comparisons, terminal_reachability, user_boundaries


class StructureTests(unittest.TestCase):
    def test_terminals_follow_combinational_values_and_stop_at_commit(self):
        values = {'a': dict(users=[dict(op='logic')]), 'b': dict(users=[dict(op='write')])}
        ops = {'logic': dict(sym='logic', out=['b']), 'write': dict(sym='write', out=[])}
        schedule = {'logic': dict(phase='compute', group=1), 'write': dict(phase='commit', group=9)}
        resolve = terminal_reachability(values, ops, schedule, {'b': 'bus'})
        self.assertEqual(resolve('a'), frozenset({'commit:9', 'output:bus'}))
        values['b']['users'] = [dict(op='logic')]
        with self.assertRaises(ValueError):
            terminal_reachability(values, ops, schedule, {})('a')

    def test_boundaries_deduplicate_users_and_protect_events_and_commit(self):
        schedule = {'self': dict(phase='compute', group='1'),
                    'a': dict(phase='compute', group='2'),
                    'b': dict(phase='compute', group='2'),
                    'write': dict(phase='commit', group='3')}
        value = dict(sym='x', out=False, users=[dict(op=x) for x in ('self', 'a', 'b', 'unused')])
        result = user_boundaries(value, 1, schedule, set())
        self.assertEqual(result['compute_targets'], [2])
        self.assertEqual(result['unscheduled_uses'], 1)
        self.assertTrue(result['compute_boundary_only'])
        self.assertFalse(user_boundaries(value, 1, schedule, {'x'})['compute_boundary_only'])
        value['users'].append(dict(op='write'))
        self.assertFalse(user_boundaries(value, 1, schedule, set())['compute_boundary_only'])
        value['users'].pop()
        value['out'] = True
        self.assertFalse(user_boundaries(value, 1, schedule, set())['compute_boundary_only'])

    def test_check_sites_combine_decode_branches_but_reject_cross_group(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'model.cpp'
            text = ('// Supernode 4: run\nconst bool grhsim_changed_7 = (old != next);\n'
                    'if (register_value != next) {}\n')
            path.write_text(text)
            self.assertEqual(generated_comparisons([path])['7']['group'], 4)
            path.write_text(text + text)
            self.assertEqual(generated_comparisons([path])['7']['check_lines'], [2, 5])
            path.write_text(text + text.replace('Supernode 4', 'Supernode 5'))
            with self.assertRaises(ValueError):
                generated_comparisons([path])


if __name__ == '__main__':
    unittest.main()
