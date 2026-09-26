#!/usr/bin/env python3
"""Unit tests for grhsim_residue_fold_census (NO00016)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grhsim_demonitor_census import view_from_model  # noqa: E402
from grhsim_residue_fold_census import (parse_sv_literal, select,  # noqa: E402
                                        tables_from_model, dynamic_savings)

# string table indices
S_CONSTANT = 1
S_ASSIGN = 2
S_NOT = 3
S_EQ = 4
S_NE = 5
S_XOR = 6
S_AND = 7
S_OR = 8
S_ADD = 9
S_SLICE = 10
S_CONSTVALUE = 11
S_SLICESTART = 12
S_SLICEEND = 13
S_INPUT_READ = 14
S_OUTPUT_WRITE = 15

STRINGS = ["", "core.compute.constant", "core.compute.assign", "core.compute.not",
           "core.compute.eq", "core.compute.ne", "core.compute.xor", "core.compute.and",
           "core.compute.or", "core.compute.add", "core.compute.sliceStatic",
           "constValue", "sliceStart", "sliceEnd", "core.input.read", "core.output.write"]

# type ids: 1 = u8 two-state, 2 = u1 two-state, 3 = u4 two-state,
#           4 = u8 four-state, 5 = s8 two-state
TYPES = [[1, 0, "logic", 8, False, "2-state"], [2, 0, "logic", 1, False, "2-state"],
         [3, 0, "logic", 4, False, "2-state"], [4, 0, "logic", 8, False, "4-state"],
         [5, 0, "logic", 8, True, "2-state"]]


def build_model():
    """Synthetic model exercising every fold class, rejects and the DCE cascade.

    Partition tree: root p1 -> emit p4 -> word p5 -> supernode p2 -> node p3
    holding every compute op; constants sit first in p3 (so CSE hits are
    ordered before the folds); input.read/output.write ops stay outside.
    """
    values = []   # (vid, type)
    ops = []      # (oid, name_idx, operands, results, params)
    compute_ops = []
    boundary = set()
    fanout_sources = set()

    vid = 0
    oid = 0

    def value(t):
        nonlocal vid
        vid += 1
        values.append((vid, t))
        return vid

    def op(name, operands, results, params=None, compute=True):
        nonlocal oid
        oid += 1
        ops.append((oid, name, operands, results, params or []))
        if compute:
            compute_ops.append(oid)
        return oid

    def const(t, lit):
        v = value(t)
        op(S_CONSTANT, [], [v], [[S_CONSTVALUE, "string", lit]])
        return v

    def chain_out(v):
        op(S_OUTPUT_WRITE, [v], [], compute=False)

    def sink(name, operands, t):
        """compute op whose result feeds an output.write (kept alive)."""
        r = value(t)
        o = op(name, operands, [r])
        chain_out(r)
        return o

    a = value(1)
    op(S_INPUT_READ, [], [a], compute=False)
    b = value(1)
    op(S_INPUT_READ, [], [b], compute=False)
    p = value(2)
    op(S_INPUT_READ, [], [p], compute=False)
    q = value(2)
    op(S_INPUT_READ, [], [q], compute=False)
    i4 = value(3)
    op(S_INPUT_READ, [], [i4], compute=False)
    x4 = value(4)
    op(S_INPUT_READ, [], [x4], compute=False)

    k1 = const(1, "8'hab")
    k4 = const(3, "4'hb")
    kone = const(2, "1'h1")

    # assign_strict + consumer rewire
    t_assign = value(1)
    assign_op = op(S_ASSIGN, [a], [t_assign])
    sink(S_XOR, [t_assign, b], 1)
    # not_not + one-level dce_cascade (inner not)
    n1 = value(2)
    not1_op = op(S_NOT, [p], [n1])
    n2 = value(2)
    not2_op = op(S_NOT, [n1], [n2])
    sink(S_AND, [n2, q], 2)
    # multi-level dce cascade: unread chain top folds as not_not, then the
    # inner not and its and producer cascade away (h3 -> h2 -> h1)
    h1v = value(2)
    h1_op = op(S_AND, [p, q], [h1v])
    h2v = value(2)
    h2_op = op(S_NOT, [h1v], [h2v])
    h3v = value(2)
    h3_op = op(S_NOT, [h2v], [h3v])
    # self_eq -> existing 1 constant
    r_eq = value(2)
    eq_op = op(S_EQ, [a, a], [r_eq])
    sink(S_OR, [r_eq, q], 2)
    # self_ne with no 0 constant of bit type -> cse miss reject
    r_ne = value(2)
    op(S_NE, [b, b], [r_ne])
    sink(S_OR, [r_ne, q], 2)
    # const_slice CSE hit / miss
    r4 = value(3)
    slice_low_op = op(S_SLICE, [k1], [r4], [[S_SLICESTART, "int", 0], [S_SLICEEND, "int", 3]])
    sink(S_ADD, [r4, i4], 3)
    r4hi = value(3)
    op(S_SLICE, [k1], [r4hi], [[S_SLICESTART, "int", 4], [S_SLICEEND, "int", 7]])
    sink(S_ADD, [r4hi, i4], 3)
    # slice_full_strict
    rfull = value(1)
    slice_full_op = op(S_SLICE, [a], [rfull], [[S_SLICESTART, "int", 0], [S_SLICEEND, "int", 7]])
    sink(S_XOR, [rfull, b], 1)
    # assign_width: s8 result, u8 operand, agnostic consumer
    tw = value(5)
    assign_width_op = op(S_ASSIGN, [a], [tw])
    sink(S_XOR, [tw, b], 5)
    # assign_type reject: width mismatch
    tm = value(3)
    op(S_ASSIGN, [a], [tm])
    sink(S_XOR, [tm, i4], 3)
    # uses transfer keeps the folded assign's source alive
    tv = value(1)
    keep_op = op(S_AND, [a, b], [tv])
    tv2 = value(1)
    assign2_op = op(S_ASSIGN, [tv], [tv2])
    sink(S_XOR, [tv2, b], 1)
    # twostate guard: self_eq over a four-state operand
    r4s = value(2)
    op(S_EQ, [x4, x4], [r4s])
    sink(S_OR, [r4s, q], 2)
    # boundary reject
    tb = value(1)
    boundary.add(tb)
    op(S_ASSIGN, [a], [tb])
    sink(S_XOR, [tb, b], 1)
    # pinned reject (input fanout source)
    tp = value(1)
    fanout_sources.add(tp)
    op(S_ASSIGN, [a], [tp])
    sink(S_XOR, [tp, b], 1)
    # order rule: a matching 4'ha constant exists but is positioned after the
    # r4hi slice in the compute walk, so r4hi stays a CSE miss
    const(3, "4'ha")

    value_slots = [[0, 2 if v in boundary else 1] for v, _t in values]
    partitions = [
        [1, 0, 0, 0, [4], []],
        [4, 1, 6, 0, [5], []],
        [5, 4, 5, 0, [2], []],
        [2, 5, 3, 0, [3], []],
        [3, 2, 4, 0, [], compute_ops],
    ]
    schedule = [
        [[0, [[0, [[1, 4, [], 0]]]]]],            # numaNodes
        [[src, [], []] for src in sorted(fanout_sources)],  # inputFanout
        [],                                     # computeSupernodeFanout
        [],                                     # commitStateFanout
        [],                                     # roundSeeds
        [],                                     # inputShadows
        0,                                      # inputShadowBytes
        0,                                      # projectionBits
        [],                                     # projectionWords
    ]
    payload = [7, 1, partitions, [[], [], [], value_slots, []], schedule]
    model = {
        "strings": STRINGS[1:],
        "types": TYPES,
        "values": [[v, t] for v, t in values],
        "states": [],
        "operations": [[o, n, 0, 0, opr, res, [], prm] for o, n, opr, res, prm in ops],
        "mappings": [["cpu", "test", True, [], payload]],
    }
    expected = {
        assign_op: "assign_strict", assign2_op: "assign_strict",
        assign_width_op: "assign_width",
        slice_full_op: "slice_full_strict", slice_low_op: "const_slice",
        not1_op: "dce_cascade", not2_op: "not_not",
        h1_op: "dce_cascade", h2_op: "dce_cascade", h3_op: "not_not",
        eq_op: "self_eq", keep_op: None,  # keep_op must survive (uses transfer)
    }
    return model, expected


class ParseSvLiteralTest(unittest.TestCase):
    def test_bases(self):
        self.assertEqual(parse_sv_literal("8'hab"), 0xAB)
        self.assertEqual(parse_sv_literal("1'h1"), 1)
        self.assertEqual(parse_sv_literal("'b11"), 3)
        self.assertEqual(parse_sv_literal("4'd9"), 9)
        self.assertEqual(parse_sv_literal("8'o17"), 15)
        self.assertEqual(parse_sv_literal("42"), 10 * 4 + 2)
        self.assertEqual(parse_sv_literal("1_0"), 10)
        self.assertEqual(parse_sv_literal("32 'hff"), 0xFF)

    def test_unknown_digits_fold_to_zero(self):
        self.assertEqual(parse_sv_literal("8'hxx"), 0)
        self.assertEqual(parse_sv_literal("4'b1z0?"), 0b1000)

    def test_big_literals_stay_exact(self):
        self.assertEqual(parse_sv_literal("68'hfffffffffffffffff"), (1 << 68) - 1)

    def test_failures(self):
        self.assertIsNone(parse_sv_literal("10'd1x"))
        self.assertIsNone(parse_sv_literal(""))
        self.assertIsNone(parse_sv_literal("8'h"))
        self.assertIsNone(parse_sv_literal("abc"))
        self.assertIsNone(parse_sv_literal("8'hf f"))


class SelectTest(unittest.TestCase):
    def test_selection_classes(self):
        model, expected = build_model()
        view = view_from_model(model)
        view["operations"] = model["operations"]
        selected, reject, rewire = select(view, tables_from_model(model))
        want = {oid: cls for oid, cls in expected.items() if cls}
        self.assertEqual(selected, want)
        # uses transfer: the folded assign's source op survives the cascade
        keep = [oid for oid, cls in expected.items() if cls is None]
        self.assertNotIn(keep[0], selected)
        self.assertEqual(reject["assign_type"], 1)
        self.assertEqual(reject["const_slice_cse_miss"], 1)
        self.assertEqual(reject["self_cmp_cse_miss"], 1)
        self.assertEqual(reject["twostate_guard"], 1)

    def test_dynamic_savings(self):
        model, expected = build_model()
        view = view_from_model(model)
        view["operations"] = model["operations"]
        selected, _reject, _rewire = select(view, tables_from_model(model))
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run.log"
            run.write_text("[grhsim-dyn] sn 2 act=3 body=10 grp=2 chg=1\n")
            dyn = dynamic_savings(view, selected, run)
        self.assertEqual(sum(dyn.values()), 10 * len(selected))


if __name__ == "__main__":
    unittest.main()
