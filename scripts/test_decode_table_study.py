import unittest

from decode_table_study import parse, reference


class DecodeConstraints(unittest.TestCase):
    def test_priority_preserves_first_match(self):
        t=parse('WDT1|P|3|4|4|f|f|1,1,3,f;7,7,5,f')
        self.assertEqual(reference(t,7),(3,15))
        self.assertEqual(reference(t,0),(15,15))

    def test_truth_merges_care_and_does_not_stop_at_first(self):
        t=parse('WDT1|T|3|4|4|a|f|1,1,1,3;2,2,4,c')
        self.assertEqual(reference(t,3),(5,15))
        self.assertEqual(reference(t,1),(1,3))
        self.assertEqual(reference(t,0),(10,15))

    def test_dont_care_is_not_default_or_observed_difference(self):
        t=parse('WDT1|T|2|4|4|f|8|1,1,7,2')
        self.assertEqual(reference(t,0),(8,8))
        self.assertEqual(reference(t,1),(2,2))
        for actual in (2,3,6,15):
            value,care=reference(t,1)
            self.assertEqual((actual^value)&care,0)
        self.assertNotEqual((0^reference(t,1)[0])&reference(t,1)[1],0)

    def test_conflict_rejected(self):
        t=parse('WDT1|T|2|1|1|0|1|1,1,1,1;2,2,0,1')
        with self.assertRaisesRegex(ValueError,'conflicting'):reference(t,3)

    def test_wide_key_and_output(self):
        t=parse('WDT1|P|65|129|64,65|0|1ffffffffffffffffffffffffffffffff|10000000000000000,10000000000000000,100000000000000000000000000000000,1ffffffffffffffffffffffffffffffff')
        self.assertEqual(reference(t,1<<64)[0],1<<128)
        self.assertEqual(reference(t,(1<<64)-1)[0],0)


if __name__=='__main__':unittest.main()
