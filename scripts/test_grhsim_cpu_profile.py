import struct
import unittest

from grhsim_cpu_profile import read_profile


class ProfileReaderTests(unittest.TestCase):
    def profile(self):
        # Two stacks with distinct leaf PCs: parent PCs must not add flat samples.
        words = (0, 3, 0, 5025, 0, 7, 2, 0x8123, 0x8456, 11, 1, 0x8567, 0, 1, 0)
        return struct.pack("<15Q", *words) + b"8000-9000 r-xp 00000000 00:01 1 /model\n"

    def test_flat_weight_and_mapping(self):
        period, records, maps = read_profile(self.profile())
        self.assertEqual(period, 5025)
        self.assertEqual(records, [(7, 0x8123), (11, 0x8567)])
        self.assertEqual(sum(count for count, _ in records), 18)
        self.assertEqual(maps, [(0x8000, 0x9000, "r-xp", 0, "/model")])

    def test_reject_incomplete_or_unsupported(self):
        data = self.profile()
        for bad in (data[:20], data[:80], data[:120], b"bad!!!!!" + data[8:],
                    data[:120] + b"not a mapping\n"):
            with self.subTest(size=len(bad)), self.assertRaises(ValueError):
                read_profile(bad)


if __name__ == "__main__":
    unittest.main()
