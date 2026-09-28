"""Semantic counterexamples for the paired-cone diagnostic (NO00027)."""

from pathlib import Path
import tempfile
import unittest

from grhsim_paired_cone_diff import (
    GsimGraph, GsimSignatures, GrhSignatures, Signatures, analyze_pairs, classify_grh,
    classify_gsim, cone_reference, dynamic_identity, independent_classification,
    independent_grh, independent_gsim, member_pairs, parse_const_literal,
    parse_gsim_int, pool_flags,
)


class GrhFixture:
    def __init__(self):
        self.model = {"kinds": {}, "operations": {}, "producer": {},
                      "strings": [], "value_width": [0], "value_sign": [False],
                      "value_name": [""], "state_name": [""],
                      "state_is_array": [False], "op_module": {}, "inputs": []}

    def string(self, value):
        self.model["strings"].append(value)
        return len(self.model["strings"])

    def op(self, kind, args=(), width=8, sign=False, params=None, refs=(), owner="m"):
        m = self.model
        oid = len(m["operations"]) + 1
        m["value_width"].append(width)
        m["value_sign"].append(sign)
        m["value_name"].append("")
        m["operations"][oid] = [oid, self.string(kind), 0, 0, list(args), [oid], list(refs),
                                     [[self.string(k), "string", v] for k, v in (params or {}).items()]]
        m["kinds"][oid] = kind
        m["producer"][oid] = oid
        m["op_module"][oid] = owner
        return oid

    def reg(self, name, width=8, array=False):
        m = self.model
        m["state_name"].append(name)
        m["state_is_array"].append(array)
        return self.op("core.state.memRead" if array else "core.state.read", width=width,
                       refs=[["state", len(m["state_name"])-1]])

    def const(self, value, width=8):
        return self.op("core.compute.constant", width=width, params={"constValue": f"{width}'d{value}"})


class GsimFixture:
    def __init__(self):
        self.graph = GsimGraph()
        self.graph.op_names = {}
        self.ops = {}

    def row(self, op, width=8, children=(), ref=None, value=None, params=(), sign=0):
        if op not in self.ops:
            oid = len(self.ops) + 1
            self.ops[op] = oid
            self.graph.op_names[oid] = op
        return (self.ops[op], width, sign, tuple(children), ref, value, tuple(params))

    def node(self, name, rows=None, root=0, width=8, kind="NODE_OTHERS"):
        self.graph.nodes[name] = [kind, width, ((root, tuple(rows)),) if rows else None]
        return (name, 0, root)


class TestConstantsAndPool(unittest.TestCase):
    def test_decimal_hex_negative_and_unknown(self):
        self.assertEqual(parse_const_literal("8'hff", 8), (255, 8))
        self.assertEqual(parse_const_literal("8'sd-1", 8), (255, 8))
        self.assertEqual(parse_const_literal("4'b10_01", 4), (9, 4))
        self.assertIsNone(parse_const_literal("1'bx", 1))
        self.assertEqual(parse_gsim_int("-1", 8), (255, 8))

    def test_width_distinguishes_same_value(self):
        p = Signatures()
        self.assertNotEqual(p.add("const", 8, (1,)), p.add("const", 16, (1,)))

    def test_commutative_and_ordered_ops(self):
        p = Signatures()
        a, b = p.add("reg", 8, (1,)), p.add("reg", 8, (2,))
        self.assertEqual(p.node("and", 8, [a, b]), p.node("and", 8, [b, a]))
        self.assertNotEqual(p.node("sub", 8, [a, b]), p.node("sub", 8, [b, a]))

    def test_select_priority_and_width(self):
        p = Signatures()
        c, d, a, b, e = [p.add("reg", w, (i,)) for i, w in enumerate((1, 1, 8, 8, 8))]
        chain = p.select(8, [c], [a], p.select(8, [d], [b], e))
        self.assertEqual(chain, p.select(8, [c, d], [a, b], e))
        self.assertNotEqual(chain, p.select(8, [d, c], [b, a], e))
        wide = p.select(16, [c], [a], p.select(8, [d], [b], e))
        self.assertNotEqual(wide, p.select(16, [c, d], [a, b], e))

    def test_commutative_operand_signs_remain_attached(self):
        p = Signatures()
        a, b = p.add("reg", 8, (1,)), p.add("reg", 8, (2,))
        left = p.node("add", 16, [a, b], [0, 1])
        self.assertEqual(left, p.node("add", 16, [b, a], [1, 0]))
        self.assertNotEqual(left, p.node("add", 16, [a, b], [1, 0]))

    def test_opaque_dependencies_are_flagged_transitively(self):
        p = Signatures()
        bad = p.add("grh_reg", 8, ("unpaired",))
        op = p.node("and", 8, [bad, bad])
        unsupported = p.node("grh:unknown", 8, [op])
        self.assertEqual(pool_flags(p)[op], 1)
        self.assertEqual(pool_flags(p)[unsupported], 3)


class TestPairing(unittest.TestCase):
    def test_member_suffixes_are_not_aliased(self):
        groups = [{"key": "m_q", "gsim": [("m__DOT__q_0", 8), ("m__DOT__q_1", 8)],
                   "grhsim": [("m$q_0", 8), ("m$q_1", 8)]}]
        pairs, g, r, remainder = member_pairs(groups)
        self.assertEqual(len(pairs), 2)
        self.assertNotEqual(g["m__DOT__q_0"], g["m__DOT__q_1"])
        self.assertEqual(g["m__DOT__q_1"], r["m$q_1"])
        self.assertEqual(remainder["gsim_bits"], 0)

    def test_chunk_and_width_mismatch_remain_unpaired(self):
        groups = [{"key": "w", "gsim": [("w_0", 8), ("w_1", 8)], "grhsim": [("w", 16)]},
                  {"key": "q", "gsim": [("q", 8)], "grhsim": [("q", 4)]}]
        self.assertFalse(member_pairs(groups)[0])

    def test_name_collision_does_not_zip_arbitrarily(self):
        groups = [{"key": "a_b", "gsim": [("a$b", 8), ("a__b", 8)],
                   "grhsim": [("a_b", 8)]}]
        self.assertFalse(member_pairs(groups)[0])


class TestCrosswalk(unittest.TestCase):
    def setUp(self):
        self.p = Signatures()
        self.r = GrhFixture()
        self.g = GsimFixture()

    def compare(self, rop, groot, expected=True, rk=None, gk=None):
        ge = GrhSignatures(self.r.model, rk or {}, self.p)
        se = GsimSignatures(self.g.graph, gk or {}, self.p)
        a, b = ge.sig(rop), se.sig(groot)
        self.assertEqual(a == b, expected)
        self.assertEqual(a, independent_grh(rop, self.r.model, rk or {}, self.p, {}))
        cone = se.cone(groot)
        refs, signatures = independent_gsim(groot, se)
        self.assertEqual(cone, refs)
        self.assertEqual({l: se.memo[l] for l in cone}, signatures)
        return ge, se

    def test_constant_encodings(self):
        rop = self.r.const(255)
        root = self.g.node("n", [self.g.row("OP_INT", value="-1")])
        self.compare(rop, root)

    def test_full_register_leaf_keys(self):
        rop = self.r.reg("m$q")
        self.g.node("m__DOT__q", kind="NODE_REG_SRC")
        root = self.g.node("d", [self.g.row("OP_EMPTY", ref="m__DOT__q")])
        self.compare(rop, root, rk={"m$q": 9}, gk={"m__DOT__q": 9})

    def test_unpaired_registers_are_side_specific(self):
        rop = self.r.reg("q")
        self.g.node("q", kind="NODE_REG_SRC")
        root = self.g.node("d", [self.g.row("OP_EMPTY", ref="q")])
        self.compare(rop, root, expected=False)

    def test_result_width_is_part_of_operation(self):
        a, b = self.r.const(2), self.r.const(3)
        rop = self.r.op("core.compute.add", [a, b], width=9)
        root = self.g.node("n", [self.g.row("OP_ADD", children=[1, 2]),
                                 self.g.row("OP_INT", value="2"), self.g.row("OP_INT", value="3")])
        self.compare(rop, root, expected=False)

    def test_static_slice_bounds_are_preserved(self):
        a = self.r.const(63)
        rop = self.r.op("core.compute.sliceStatic", [a], width=3, params={"sliceStart": 1, "sliceEnd": 3})
        root = self.g.node("n", [self.g.row("OP_BITS", width=3, children=[1], params=[3, 1]), self.g.row("OP_INT", value="63")])
        self.compare(rop, root)

    def test_pad_is_shape_transparent(self):
        rop = self.r.const(2)
        root = self.g.node("n", [self.g.row("OP_PAD", width=16, children=[1]), self.g.row("OP_INT", value="2")])
        self.compare(rop, root)

    def test_named_reference_inlines_and_deduplicates(self):
        a = self.r.const(2)
        rop = self.r.op("core.compute.or", [a, a])
        self.g.node("v", [self.g.row("OP_INT", value="2")])
        root = self.g.node("n", [self.g.row("OP_OR", children=[1, 2]),
                                 self.g.row("OP_EMPTY", ref="v"), self.g.row("OP_EMPTY", ref="v")])
        _, se = self.compare(rop, root)
        self.assertEqual(len(se.cone(root)), 2)

    def test_lvalue_and_unreachable_node_excluded(self):
        rop = self.r.const(2)
        root = self.g.node("n", [self.g.row("OP_INT", value="2"), self.g.row("OP_INT", value="99")])
        _, se = self.compare(rop, root)
        self.assertEqual(len(se.cone(root)), 1)

    def test_when_and_mux_match(self):
        c, a, b = self.r.const(1, 1), self.r.const(2), self.r.const(3)
        rop = self.r.op("core.compute.mux", [c, a, b])
        root = self.g.node("n", [self.g.row("OP_WHEN", children=[1, 2, 3]),
                                 self.g.row("OP_INT", width=1, value="1"),
                                 self.g.row("OP_INT", value="2"), self.g.row("OP_INT", value="3")])
        self.compare(rop, root)

    def test_partial_when_does_not_invent_an_else_value(self):
        c, a, z = self.r.const(1, 1), self.r.const(2), self.r.const(0)
        rop = self.r.op("core.compute.mux", [c, a, z])
        root = self.g.node("n", [self.g.row("OP_WHEN", children=[1, 2]),
                                 self.g.row("OP_INT", width=1, value="1"),
                                 self.g.row("OP_INT", value="2")])
        self.compare(rop, root, expected=False)

    def test_memory_address_boundary_is_conservative(self):
        rop = self.r.reg("ram_ext$Memory", array=True)
        self.g.node("ram_MPORT_read", kind="NODE_READER")
        root = self.g.node("n", [self.g.row("OP_EMPTY", ref="ram_MPORT_read", children=[1]),
                                 self.g.row("OP_INT", value="12")])
        _, se = self.compare(rop, root, expected=False)
        self.assertEqual(len(se.cone(root)), 1)

    def test_shift_amount_is_width_independent_parameter(self):
        a, n = self.r.const(5), self.r.const(2, 32)
        rop = self.r.op("core.compute.shl", [a, n])
        root = self.g.node("n", [self.g.row("OP_SHL", children=[1], params=[2]), self.g.row("OP_INT", value="5")])
        self.compare(rop, root)

    def test_signed_compare_is_not_unsigned_compare(self):
        a, b = self.r.const(255), self.r.const(2)
        rop = self.r.op("core.compute.lt", [a, b], width=1)
        root = self.g.node("n", [self.g.row("OP_LT", width=1, children=[1, 2]),
                                 self.g.row("OP_INT", value="255", sign=1), self.g.row("OP_INT", value="2", sign=1)])
        self.compare(rop, root, expected=False)

    def test_cyclic_reference_terminates(self):
        root = self.g.node("n", [self.g.row("OP_EMPTY", ref="n")])
        se = GsimSignatures(self.g.graph, {}, self.p)
        self.assertIsInstance(se.sig(root), int)
        self.assertEqual(len(se.cycle_edges), 1)

    def test_all_assign_trees_are_visited_in_order(self):
        first = (0, (self.g.row("OP_INT", value="1"),))
        second = (0, (self.g.row("OP_INT", value="2"),))
        self.g.graph.nodes["dst"] = ["NODE_REG_DST", 8, (first, second)]
        se = GsimSignatures(self.g.graph, {}, self.p)
        root = se.root("dst")
        sig = se.sig(root)
        locations = se.cone(root)
        self.assertEqual(locations, {("dst", 0, 0), ("dst", 1, 0)})
        self.assertEqual(self.p.keys[sig][0], "gsim:assign_sequence")
        iv_locs, iv_sigs = independent_gsim(root, se)
        self.assertEqual(locations, iv_locs)
        self.assertEqual(iv_sigs, {loc: se.memo[loc] for loc in locations})
        self.g.graph.nodes["other"] = ["NODE_REG_DST", 8, (second, first)]
        self.assertNotEqual(sig, se.sig(se.root("other")))

    def test_multi_tree_named_reference_is_inlined(self):
        self.g.graph.nodes["v"] = ["NODE_OTHERS", 8,
                                    ((0, (self.g.row("OP_INT", value="3"),)),
                                     (0, (self.g.row("OP_INT", value="4"),)))]
        root = self.g.node("dst", [self.g.row("OP_EMPTY", ref="v")])
        se = GsimSignatures(self.g.graph, {}, self.p)
        se.sig(root)
        expected = {("v", 0, 0), ("v", 1, 0)}
        self.assertEqual(se.cone(root), expected)
        self.assertEqual(independent_gsim(root, se)[0], expected)


class TestClassificationAndCounters(unittest.TestCase):
    def test_opaque_constants_remain_in_leaf_coverage_denominator(self):
        f, g, pool = GrhFixture(), GsimFixture(), Signatures()
        constant = f.op("core.compute.constant", params={"constValue": "8'bxxxxxxxx"})
        f.model.update(state_name=["", "q"], origins={}, writes={1: [constant]})
        g.node("dst", [g.row("OP_INT", value="unknown")])
        g.graph.reg_src = [("q", 8, "dst")]
        pairs = [{"key": "q", "gsim": "q", "grhsim": "q", "width": 8}]
        ge, se = GrhSignatures(f.model, {}, pool), GsimSignatures(g.graph, {}, pool)
        with tempfile.TemporaryDirectory() as directory:
            metrics, _g4, _g5, _links = analyze_pairs(pairs, f.model, g.graph, ge, se,
                                                      {constant: 10}, 1, Path(directory), 0, 0)
        self.assertEqual(metrics["M-leaf"]["grhsim_union"], 1)
        self.assertEqual(metrics["M-leaf"]["gsim_union"], 1)
        self.assertEqual(metrics["M-match"]["pair_totals"]["r_leaves"], 1)
        self.assertEqual(metrics["M-match"]["pair_totals"]["g_leaves"], 1)
        self.assertEqual(metrics["M-leaf"]["union_intersection"], 0)

    def test_unrelated_cone_cannot_match_and_dynamic_union_counts_once(self):
        f, g, pool = GrhFixture(), GsimFixture(), Signatures()
        a, b = f.const(1), f.const(2)
        add = f.op("core.compute.add", [a, b])
        f.model.update(state_name=["", "q1", "q2"], origins={}, writes={1: [add], 2: [add]})
        for n, op in (("n1", "OP_SUB"), ("n2", "OP_ADD")):
            g.node(n, [g.row(op, children=[1, 2]), g.row("OP_INT", value="1"), g.row("OP_INT", value="2")])
        g.graph.reg_src = [("q1", 8, "n1"), ("q2", 8, "n2")]
        pairs = [{"key": q, "gsim": q, "grhsim": q, "width": 8} for q in ("q1", "q2")]
        ge, se = GrhSignatures(f.model, {}, pool), GsimSignatures(g.graph, {}, pool)
        with tempfile.TemporaryDirectory() as directory:
            metrics, _g4, _g5, _links = analyze_pairs(pairs, f.model, g.graph, ge, se,
                                                      {a: 10, b: 10, add: 10}, 1, Path(directory), 0, 0)
        self.assertEqual(metrics["M-xo"]["ops"], 1)
        self.assertEqual(metrics["M-xo"]["execs"], 10)
        self.assertEqual(metrics["M-xo-dyn"]["never_matched_in_any_pair_execs"], 0)
        self.assertEqual(metrics["M-cone-cover"]["execs"], 30)

    def test_classification_priority_and_mask_select(self):
        f = GrhFixture()
        packed_slice = f.op("core.compute.sliceStatic", owner="(packed)")
        blend = f.op("core.compute.bitSelect")
        assign = f.op("core.compute.assign")
        event = f.reg("__event_1")
        for oid, expected in ((packed_slice, "owner_(packed)"), (blend, "other_semantic"),
                              (assign, "width_norm"), (event, "event_bookkeeping")):
            self.assertEqual(classify_grh(oid, f.model), expected)
            self.assertEqual(independent_classification(oid, f.model), expected)

    def test_independent_cone_stops_at_read(self):
        f = GrhFixture()
        read = f.reg("q")
        op = f.op("core.compute.add", [read, read])
        self.assertEqual(cone_reference([op], f.model), {read, op})

    def test_all_counter_fields_not_just_body(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory)/"a", Path(directory)/"b"
            text = "[grhsim-dyn] sn 1 act=3 body=2 grp=4 chg=1\n[grhsim-dyn] totals x=3\n"
            a.write_text(text)
            b.write_text(text)
            self.assertEqual(dynamic_identity(a, b)["rows"], 1)
            b.write_text(text.replace("act=3", "act=4"))
            with self.assertRaisesRegex(ValueError, "differ"):
                dynamic_identity(a, b)

    def test_missing_counters_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"a"
            path.write_text("")
            with self.assertRaisesRegex(ValueError, "missing"):
                dynamic_identity(path, path)


if __name__ == "__main__":
    unittest.main()
