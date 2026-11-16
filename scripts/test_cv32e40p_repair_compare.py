import unittest
from cv32e40p_repair_compare import normalize_bool_table
from cv32e40p_repair_analysis import counter_rates


class RepresentationComparisonTests(unittest.TestCase):
    def test_only_table_representation_and_parentheses_are_normalized(self):
        before = ('std::array<std::uint8_t, 16> local_equality_table_0_{};\n'
                  'local_equality_table_0_.fill(UINT8_C(0));\n'
                  'local_equality_table_0_[address] = UINT8_C(1);\n'
                  'bool x = local_equality_table_0_[3u] != UINT8_C(0);\n'
                  'auto y = static_cast<unsigned>(local_equality_table_0_[3u] != UINT8_C(0));')
        after = ('std::array<bool, 16> local_equality_table_0_{};\n'
                 'local_equality_table_0_.fill(false);\n'
                 'local_equality_table_0_[address] = true;\n'
                 'bool x = local_equality_table_0_[3u];\n'
                 'auto y = static_cast<unsigned>(local_equality_table_0_[3u]);')
        self.assertEqual(normalize_bool_table(before), normalize_bool_table(after))
        self.assertNotEqual(normalize_bool_table(before), normalize_bool_table(after.replace('[3u]', '[4u]')))
        self.assertNotEqual(normalize_bool_table(before), normalize_bool_table(after.replace('= true', '= false')))
        unrelated = 'const bool x = state_[3u] != UINT8_C(0);'
        self.assertEqual(normalize_bool_table(unrelated), unrelated)

    def test_diagnostic_counter_accounting_and_units(self):
        counts = {'cmp:1': [2, 4, 0, 0], 'cmp:2': [0, 2, 2, 0],
                  'chg:1': [0, 2, 0, 0], 'chg:2': [0, 0, 0, 0],
                  'scalar_comparisons': [2, 6, 2, 0], 'scalar_changes': [0, 2, 0, 0]}
        self.assertEqual(counter_rates(dict(cycles=2, counts=counts))['scalar_comparisons'], [1, 3, 1, 0])
        with self.assertRaises(ValueError):
            counter_rates(dict(cycles=0, counts=counts))
        counts['scalar_comparisons'] = [2, 5, 2, 0]
        with self.assertRaises(ValueError):
            counter_rates(dict(cycles=2, counts=counts))


if __name__ == '__main__': unittest.main()
