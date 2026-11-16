import unittest
from cv32e40p_equality_family_analysis import parse_families


class FamilyCoverageTests(unittest.TestCase):
    def test_initial_clear_set_sites_are_one_semantic_predicate(self):
        code = '''// Shared equality family: source=71 predicates=2
auto &grhsim_eq_cache_0 = shared_equality_cache_[0u];
const bool grhsim_changed_4 = old4 != (grhsim_eq_address_0 == 1u);
const bool grhsim_changed_8 = old8 != (grhsim_eq_address_0 == 2u);
const bool grhsim_changed_4 = old4 != false;
const bool grhsim_changed_4 = old4 != true;
const bool grhsim_changed_8 = old8 != false;
const bool grhsim_changed_8 = old8 != true;
grhsim_eq_cache_0.previous = grhsim_eq_address_0;
'''
        self.assertEqual(parse_families(code), [dict(source='71', cache='0', ids=['4','8'])])
        with self.assertRaises(ValueError): parse_families(code.replace('predicates=2', 'predicates=3'))
        with self.assertRaises(ValueError): parse_families(code.replace('grhsim_eq_cache_0.previous =', 'invalid.previous ='))


if __name__ == '__main__': unittest.main()
