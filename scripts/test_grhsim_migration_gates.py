#!/usr/bin/env python3
"""Unit tests for scripts/grhsim_migration_gates.py (synthetic checkpoints/logs)."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from grhsim_migration_gates import (EXPECTED_ENDPOINT, MappingInfo, analyze_migration,
                                    gate_boundary_closed, gate_determinism,
                                    gate_kind_dominated, gate_membership,
                                    gate_model_neutral, gate_mshrink,
                                    gate_sn_dominated)

ROOT = 0
SUPER = 3
NODE = 4
LOCAL = 1
BOUNDARY = 2


def make_model(partitions, slots, operations):
    """Minimal mapped checkpoint dict.

    partitions: rows [id, parent, kind, phase, children, ops, gate]
    slots:      slot kind per value id, 1-based (index 0 is a placeholder)
    operations: rows (oid, operands, results)
    """
    payload = [0, 0, partitions, [0, 0, 0, [[None, kind] for kind in slots[1:]]]]
    return {
        "strings": ["core.compute.and"],
        "types": [],
        "values": [[vid, 0] for vid in range(1, len(slots))],
        "operations": [[oid, 1, 0, 0, operands, results, [], 0]
                       for oid, operands, results in operations],
        "states": [],
        "mappings": [["cpu", 0, payload]],
    }


OPERATIONS = [
    (10, [5], [1]),         # in A node 4; v1 -> consumed by 20 in B (migrates)
    (11, [6], [2]),         # in A node 4; v2 -> consumed by 20 in B (stays)
    (12, [6], [3]),         # in A node 6; v3 -> consumed by 20 in B (migrates)
    (20, [1, 2, 3], [4]),   # in B node 5
]

OLD_PARTITIONS = [
    [1, 0, ROOT, 0, [2, 3], [], []],
    [2, 1, SUPER, 0, [4, 6], [], []],   # unit A
    [3, 1, SUPER, 0, [5], [], []],      # unit B
    [4, 2, NODE, 0, [], [10, 11], []],
    [5, 3, NODE, 0, [], [20], []],
    [6, 2, NODE, 0, [], [12], []],
]
OLD_SLOTS = [None, BOUNDARY, BOUNDARY, BOUNDARY, LOCAL, BOUNDARY, BOUNDARY]

# Post-migration: ops 10/12 moved into B; node 6 dropped; B renumbered to 7/9.
NEW_PARTITIONS = [
    [1, 0, ROOT, 0, [2, 7], [], []],
    [2, 1, SUPER, 0, [4], [], []],      # unit A (donor)
    [7, 1, SUPER, 0, [9], [], []],      # unit B (target, renumbered)
    [4, 2, NODE, 0, [], [11], []],
    [9, 7, NODE, 0, [], [12, 10, 20], []],
]
NEW_SLOTS = [None, LOCAL, BOUNDARY, LOCAL, LOCAL, BOUNDARY, BOUNDARY]

BASELINE_LOG = """[grhsim-dyn] sn 2 act=5 body=4 grp=3 chg=2
[grhsim-dyn] sn 3 act=9 body=8 grp=7 chg=6
[grhsim-dyn] kind core.compute.and wr=100 ch=10 silent=0
[grhsim-dyn] kind core.compute.or wr=50 ch=5 silent=0
"""
NEW_LOG = """[grhsim-dyn] sn 2 act=4 body=4 grp=3 chg=1
[grhsim-dyn] sn 7 act=9 body=8 grp=7 chg=6
[grhsim-dyn] kind core.compute.and wr=60 ch=10 silent=0
[grhsim-dyn] kind core.compute.or wr=50 ch=5 silent=0
"""
ENDPOINT_LINES = """Core 0: EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80000c0c
Core-0 instrCnt = 240,349, cycleCnt = 99,996, IPC = 2.403586
Seed=0 Guest cycle spent: 100,001 (this will be different from cycleCnt if emu loads a snapshot)
[grhsim-vchg] v 1 wr=10 ch=2
"""


def old_model():
    return make_model(OLD_PARTITIONS, OLD_SLOTS, OPERATIONS)


def new_model():
    return make_model(NEW_PARTITIONS, NEW_SLOTS, OPERATIONS)


class MigrationGateTests(unittest.TestCase):
    def test_happy_path(self):
        old, new = MappingInfo(old_model()), MappingInfo(new_model())
        flipped, moved, new_to_old, old_to_new, ambiguous = analyze_migration(old, new)
        self.assertEqual(sorted(flipped), [1, 3])
        self.assertEqual(sorted(moved), [10, 12])
        self.assertEqual(new_to_old, {2: 2, 7: 3})
        self.assertFalse(ambiguous)
        self.assertTrue(gate_model_neutral(old_model(), new_model()).ok)
        self.assertTrue(gate_boundary_closed(old, new, flipped).ok)
        g = gate_membership(old, new, flipped, moved, new_to_old, old_to_new, ambiguous)
        self.assertTrue(g.ok, g.detail)

    def test_neutral_models_pass(self):
        old = MappingInfo(old_model())
        again = MappingInfo(old_model())
        flipped, moved, new_to_old, old_to_new, ambiguous = analyze_migration(old, again)
        self.assertFalse(flipped)
        self.assertFalse(moved)
        self.assertTrue(gate_model_neutral(old_model(), old_model()).ok)
        self.assertTrue(gate_boundary_closed(old, again, flipped).ok)
        self.assertTrue(gate_membership(old, again, flipped, moved, new_to_old,
                                        old_to_new, ambiguous).ok)

    def test_section_drift_detected(self):
        drifted = new_model()
        drifted["states"] = [[7, 0]]
        self.assertFalse(gate_model_neutral(old_model(), drifted).ok)

    def test_new_boundary_detected(self):
        bad = new_model()
        bad["mappings"][0][-1][3][3][3][1] = BOUNDARY  # v4: LOCAL -> BOUNDARY
        old = MappingInfo(old_model())
        g = gate_boundary_closed(old, MappingInfo(bad), {1: LOCAL, 3: LOCAL})
        self.assertFalse(g.ok)

    def test_wrong_target_unit_detected(self):
        # op 10 lands back in A (own new node) instead of the consumer unit B.
        bad_partitions = [row[:] for row in NEW_PARTITIONS]
        bad_partitions[1] = [2, 1, SUPER, 0, [4, 8], [], []]
        bad_partitions[4] = [9, 7, NODE, 0, [], [12, 20], []]
        bad_partitions.append([8, 2, NODE, 0, [], [10], []])
        bad = make_model(bad_partitions, NEW_SLOTS, OPERATIONS)
        old, new = MappingInfo(old_model()), MappingInfo(bad)
        flipped, moved, new_to_old, old_to_new, ambiguous = analyze_migration(old, new)
        g = gate_membership(old, new, flipped, moved, new_to_old, old_to_new, ambiguous)
        self.assertFalse(g.ok)

    def test_unmigrated_op_move_detected(self):
        # op 11 moved into B but v2 keeps its Boundary slot (membership drift).
        bad_partitions = [row[:] for row in NEW_PARTITIONS]
        bad_partitions[3] = [4, 2, NODE, 0, [], []]
        bad_partitions[4] = [9, 7, NODE, 0, [], [12, 10, 11, 20], []]
        bad = make_model(bad_partitions, NEW_SLOTS, OPERATIONS)
        old, new = MappingInfo(old_model()), MappingInfo(bad)
        flipped, moved, new_to_old, old_to_new, ambiguous = analyze_migration(old, new)
        g = gate_membership(old, new, flipped, moved, new_to_old, old_to_new, ambiguous)
        self.assertFalse(g.ok)

    def _write(self, tmp, name, text):
        path = tmp / name
        path.write_text(text)
        return path

    def test_log_gates_pass(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            base = self._write(tmp, "base.log", BASELINE_LOG + ENDPOINT_LINES)
            run1 = self._write(tmp, "run1.log", NEW_LOG + ENDPOINT_LINES)
            run2 = self._write(tmp, "run2.log", NEW_LOG + ENDPOINT_LINES)
            old, new = MappingInfo(old_model()), MappingInfo(new_model())
            _, _, _, old_to_new, _ = analyze_migration(old, new)
            g = gate_sn_dominated(base, run1, old_to_new, {3})
            self.assertTrue(g.ok, g.detail)
            gk, base_kinds, new_kinds = gate_kind_dominated(base, run1)
            self.assertTrue(gk.ok, gk.detail)
            self.assertTrue(gate_mshrink(base_kinds, new_kinds, 0.014, 100001).ok)
            self.assertTrue(gate_determinism(run1, run2).ok)

    def test_log_gates_catch_violations(self):
        bad_new = NEW_LOG.replace("grp=7", "grp=8").replace(
            "core.compute.or wr=50", "core.compute.or wr=51")
        with TemporaryDirectory() as td:
            tmp = Path(td)
            base = self._write(tmp, "base.log", BASELINE_LOG + ENDPOINT_LINES)
            run1 = self._write(tmp, "run1.log", bad_new + ENDPOINT_LINES)
            run2 = self._write(tmp, "run2.log", NEW_LOG + ENDPOINT_LINES)
            old, new = MappingInfo(old_model()), MappingInfo(new_model())
            _, _, _, old_to_new, _ = analyze_migration(old, new)
            self.assertFalse(gate_sn_dominated(base, run1, old_to_new, {3}).ok)
            self.assertFalse(gate_kind_dominated(base, run1)[0].ok)
            self.assertFalse(gate_determinism(run1, run2).ok)
            _, base_kinds, new_kinds = gate_kind_dominated(base, run1)
            self.assertFalse(gate_mshrink(base_kinds, new_kinds, 0.99, 100001).ok)

    def test_bonus_flip_producer_stay_allowed(self):
        # v2 is produced by op 70 inside B and read only by op 50 in A; when 50
        # migrates into B, v2 flips Boundary->local without its producer moving.
        ops = [(50, [2], [1]), (51, [3], [5]), (70, [3], [2]), (60, [1, 5], [4])]
        old_parts = [
            [1, 0, ROOT, 0, [2, 3], [], []],
            [2, 1, SUPER, 0, [4], [], []],
            [3, 1, SUPER, 0, [5], [], []],
            [4, 2, NODE, 0, [], [50, 51], []],
            [5, 3, NODE, 0, [], [70, 60], []],
        ]
        old_slots = [None, BOUNDARY, BOUNDARY, BOUNDARY, LOCAL, BOUNDARY]
        new_parts = [
            [1, 0, ROOT, 0, [2, 3], [], []],
            [2, 1, SUPER, 0, [4], [], []],
            [3, 1, SUPER, 0, [5], [], []],
            [4, 2, NODE, 0, [], [51], []],
            [5, 3, NODE, 0, [], [50, 70, 60], []],
        ]
        new_slots = [None, LOCAL, LOCAL, BOUNDARY, LOCAL, BOUNDARY]
        old = MappingInfo(make_model(old_parts, old_slots, ops))
        new = MappingInfo(make_model(new_parts, new_slots, ops))
        flipped, moved, new_to_old, old_to_new, ambiguous = analyze_migration(old, new)
        self.assertEqual(sorted(flipped), [1, 2])
        g = gate_membership(old, new, flipped, moved, new_to_old, old_to_new, ambiguous)
        self.assertTrue(g.ok, g.detail)

    def test_expected_endpoint_constant(self):
        self.assertEqual(EXPECTED_ENDPOINT["instr"], 240349)
        self.assertEqual(EXPECTED_ENDPOINT["pc"], "0x80000c0c")


if __name__ == "__main__":
    unittest.main()
