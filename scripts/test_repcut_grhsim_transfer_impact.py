#!/usr/bin/env python3
import csv
from pathlib import Path
import tempfile
import unittest

from repcut_grhsim_piece_splits import load_transfer_layout, transfer_impact


class TransferImpactTest(unittest.TestCase):
    def test_same_calls_and_bytes_can_change_receiver_layout(self):
        # Two packets still carry four bits to the same two receivers.
        before = {(0, (2, 4)): (1, ((10, 1, 0),)),
                  (1, (2, 4)): (3, ((11, 1, 2), (12, 1, 1), (13, 1, 0)))}
        after = {(0, (2, 4)): (3, ((10, 1, 2), (11, 1, 1), (12, 1, 0))),
                 (1, (2, 4)): (1, ((13, 1, 0),))}
        impact = transfer_impact(before, after, [0, 1])
        self.assertEqual(impact['direct_impact_parts'], [0, 1, 2, 4])
        self.assertEqual(impact['non_endpoint_impact_parts'], [2, 4])
        self.assertEqual(len(impact['changed_transfer_bundles']), 2)
        self.assertEqual(transfer_impact(before, before, [0, 1])['changed_transfer_bundles'], [])

    def test_same_width_and_members_with_new_offsets_still_affect_receiver(self):
        before = {(0, (3,)): (2, ((10, 1, 0), (11, 1, 1)))}
        after = {(0, (3,)): (2, ((10, 1, 1), (11, 1, 0)))}
        impact = transfer_impact(before, after, [0, 1])
        self.assertEqual(impact['non_endpoint_impact_parts'], [3])
        self.assertEqual(len(impact['changed_transfer_bundles']), 1)

    def test_loader_canonicalizes_order_but_preserves_bit_offsets(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'transfers.csv'
            header = ['owner', 'readers', 'width', 'members']
            with path.open('w', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow(header)
                writer.writerow([0, '4;2;', 2, '11:1:1;10:1:0;'])
            self.assertEqual(load_transfer_layout(path),
                             {(0, (2, 4)): (2, ((10, 1, 0), (11, 1, 1)))})
            with path.open('a', newline='') as stream:
                csv.writer(stream).writerow([0, '2;4;', 2, '10:1:0;11:1:1;'])
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                load_transfer_layout(path)


if __name__ == '__main__':
    unittest.main()
