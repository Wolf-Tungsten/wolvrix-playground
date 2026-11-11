"""Unit tests for the F21 deletion-matrix collector."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from analyze_f21_array_values import compare_array_values
from analyze_f21_anchor_alignment import (
    build_aggregate_pairs,
    build_effect_identity,
    build_grh_extra_justification,
    generated_reg_reason,
    load_split_state_map,
    load_state_family_names,
    mechanism_representatives,
    name_pattern,
    shape_width_match,
    _single_side_row,
    suffix_kind,
    survival_label,
)
from analyze_f21_gsim_reachability import GraphIndex, forward_reachable, mechanism
from analyze_f21_rob_dag_paths import (
    build_adjacency,
    bypassed_source_paths,
    longer_paths,
    two_hop_paths,
)
from analyze_f21_state_elements import (
    compare_post_split_state_elements,
    compare_state_elements,
    parse_const_literal,
)
from compare_f21_dce_nodes import collect_grh_survivors, collect_gsim_survivors, load_split_ids
from compare_f21_srcline import compare_stage
from grhsim_f21_dce_compare import collect_gsim, load_nodes, pack
from trace_f21_retained import trace_grh


ROOT = Path(__file__).resolve().parents[1]


def tree_node(parent: int, kind: str, name: str, index: int | None = None) -> str:
    suffix = "" if index is None else f', "index": {index}'
    return f'      {{"parent": {parent}, "kind": "{kind}", "name": "{name}"{suffix}}},'


def grh_fixture() -> str:
    nodes = [
        tree_node(0, "module", "top"),
        tree_node(1, "module", "first"),
        tree_node(2, "declaration", "n"),
        tree_node(3, "field", "bits"),
        tree_node(4, "element", "", 3),
        tree_node(5, "expression", "add"),
        tree_node(1, "module", "second"),
        tree_node(7, "declaration", "n"),
        tree_node(8, "field", "bits"),
        tree_node(9, "element", "", 3),
        tree_node(10, "expression", "add"),
        tree_node(1, "declaration", "first"),
        tree_node(1, "declaration", "second"),
    ]
    return "\n".join([
        '{"formatVersion": 4,',
        '  "graphs": [{',
        '    "symbol": "top",',
        '    "semanticTree": {"sourceUnit": "unit", "circuit": "circuit", "nodes": [',
        *nodes[:-1],
        nodes[-1][:-1],
        '    ]},',
        '      "vals": [',
        '        {"id": 1, "sym": "y", "semanticIds": [10]}',
        '    ],',
        '      "ops": [',
        '        {"id": 1, "kind": "kNot", "out": [1], "semanticIds": [8]}',
        '    ]',
        '  }]',
        '}',
        '',
    ])


def gsim_fixture(records: list[tuple[int, str]]) -> str:
    rows = [f'{{"id": {node_id}, "name": "{name}", "type": "NODE_OTHERS", "status": "VALID_NODE"}},'
            for node_id, name in records]
    rows[-1] = rows[-1][:-1]
    return '{"nodes": [\n' + "\n".join(rows) + '\n],"edges": []}\n'


class F21DceToolsTest(unittest.TestCase):
    def setUp(self):
        (ROOT / "ptmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="f21-dce-tools-", dir=ROOT / "ptmp")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.first = "first$n__DOT__bits[3]"
        self.second = "second$n__DOT__bits[3]"
        self.candidates = self.work / "candidates.txt"
        self.candidates.write_text(f"{self.first}\n{self.second}\n", encoding="utf-8")
        self.unmatched = self.work / "unmatched.txt"
        self.unmatched.write_text("", encoding="utf-8")
        self.grh = self.work / "grh.json"
        self.grh.write_text(grh_fixture(), encoding="utf-8")
        self.gsim_init = self.work / "gsim-init.json"
        self.gsim_init.write_text(gsim_fixture([(1, self.first), (2, self.second)]), encoding="utf-8")
        self.gsim_before = self.work / "gsim-before.json"
        self.gsim_before.write_text(gsim_fixture([(1, self.first), (2, self.second)]), encoding="utf-8")
        self.gsim_after = self.work / "gsim-after.json"
        self.gsim_after.write_text(gsim_fixture([(2, self.second)]), encoding="utf-8")
        self.split = self.work / "split.json"
        self.split.write_text('{"members": []}\n', encoding="utf-8")

    def collect(self):
        names, name_to_id = load_nodes(self.candidates, self.unmatched)
        candidates = set(names)
        originals, members, ambiguous = load_split_ids(self.gsim_init, self.split)
        before, _before_stats = collect_gsim_survivors(
            self.gsim_before, candidates, originals, members, ambiguous)
        after, _after_stats = collect_gsim_survivors(
            self.gsim_after, candidates, originals, members, ambiguous)
        grh_after, _grh_stats = collect_grh_survivors(self.grh, names, name_to_id)
        return candidates, before, after, grh_after

    def test_deletion_matrix_closes(self):
        candidates, gsim_before, gsim_after, grh_after = self.collect()
        self.assertEqual(gsim_before, candidates)
        both_survive = gsim_after & grh_after
        both_removed = candidates - (gsim_after | grh_after)
        self.assertEqual(both_survive, {self.second})
        self.assertEqual(both_removed, {self.first})
        self.assertEqual(gsim_after - grh_after, set())
        self.assertEqual(grh_after - gsim_after, set())

    def test_shape_width_match_normalizes_singleton_axes(self):
        grh = {"attrs": {"shape": {"t": "int[]", "vs": [1, 2]},
                          "width": {"t": "int", "v": 8}}}
        gsim = {"width": 4, "dimension": [2]}
        self.assertEqual(shape_width_match(grh, gsim), (True, True))

    def test_aggregate_member_rule_pairs_opposite_side_widths(self):
        grh = {
            "bundle": {"sym": "bundle", "attrs": {
                "shape": {"t": "int[]", "vs": [2]},
                "width": {"t": "int", "v": 8},
            }},
        }
        gsim = {
            "bundle_0": {"name": "bundle_0", "width": 4, "dimension": []},
            "bundle_1": {"name": "bundle_1", "width": 4, "dimension": []},
        }
        pairs, used_grh, used_gsim = build_aggregate_pairs(grh, gsim)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["direction"], "grh_aggregate_to_gsim_members")
        self.assertEqual(used_grh, {"bundle"})
        self.assertEqual(used_gsim, {"bundle_0", "bundle_1"})

    def test_single_side_survival_is_not_pairable(self):
        row = _single_side_row(
            "latch", "grh", "l", {"sym": "l", "attrs": {}},
            True, True, "no GSIM latch type", "one-sided-known",
        )
        self.assertEqual(row["survival"], "not_pairable")
        self.assertTrue(row["side_post"])

    def test_ambiguous_split_member_kept_by_id(self):
        self.split.write_text(
            '{"members": ['
            '{"parentId": 90, "parentName": "first$n__DOT__bits[3]", "memberId": 3, "memberName": "duplicate"},'
            '{"parentId": 91, "parentName": "second$n__DOT__bits[3]", "memberId": 4, "memberName": "duplicate"}'
            ']}\n', encoding="utf-8")
        self.gsim_before.write_text(gsim_fixture([(1, self.first), (2, self.second), (3, "duplicate")]),
                                    encoding="utf-8")
        candidates, gsim_before, _gsim_after, _grh_after = self.collect()
        self.assertEqual(gsim_before, candidates)

    def test_root_trace_includes_state_family(self):
        nodes = [
            tree_node(0, "module", "top"),
            tree_node(1, "expression", self.first),
            tree_node(1, "expression", self.second),
        ]
        self.grh.write_text("\n".join([
            '{"formatVersion": 4,',
            '  "graphs": [{',
            '    "symbol": "top",',
            '    "semanticTree": {"sourceUnit": "unit", "circuit": "circuit", "nodes": [',
            *nodes[:-1],
            nodes[-1][:-1],
            '    ]},',
            '      "vals": [',
            '        {"id": 1, "in": true},',
            '        {"id": 2, "semanticIds": [3]},',
            '        {"id": 3},',
            '        {"id": 4, "semanticIds": [2]},',
            '        {"id": 5, "out": true, "semanticIds": [3]}',
            '      ],',
            '      "ops": [',
            '        {"id": 1, "sym": "r", "kind": "kRegister", "in": [], "out": []},',
            '        {"id": 2, "kind": "kRegisterReadPort", "in": [], "out": [2], "semanticIds": [3], '
            '"attrs": {"regSymbol": {"t": "string", "v": "r"}}},',
            '        {"id": 3, "kind": "kRegisterWritePort", "in": [4, 1], "out": [], '
            '"attrs": {"regSymbol": {"t": "string", "v": "r"}}},',
            '        {"id": 4, "kind": "kConstant", "in": [], "out": [4], "semanticIds": [2]},',
            '        {"id": 5, "kind": "kAssign", "in": [2], "out": [5], "semanticIds": [3]}',
            '      ]',
            '  }]',
            '}',
            '',
        ]), encoding="utf-8")
        names = self.work / "trace-names.txt"
        names.write_text(f"{self.first}\n{self.second}\n", encoding="utf-8")
        report = trace_grh(self.grh, self.candidates, self.unmatched, names,
                           self.work / "root-trace.json", 80)
        first = report["targets"][self.first]
        self.assertEqual(first["root"], "port")
        self.assertIn(self.first, first["path"][0]["semanticPaths"])
        kinds = {row.get("kind") for row in first["path"]}
        self.assertIn("kRegisterReadPort", kinds)
        self.assertIn("kRegisterWritePort", kinds)
        storage_symbols = {row.get("storageSymbol") for row in first["path"]}
        self.assertIn("r", storage_symbols)
        self.assertEqual(report["targets"][self.second]["root"], "port")

        summary = trace_grh(self.grh, self.candidates, self.unmatched, names,
                            self.work / "root-summary.json", 80, summary_only=True)
        self.assertNotIn("targets", summary)
        self.assertEqual(summary["summary"]["total"], 2)
        self.assertEqual(summary["summary"]["groups"]["other"]["roots"], {"port": 2})

    def test_state_element_distribution(self):
        self.assertEqual(parse_const_literal("4'd12"), 12)
        self.assertEqual(parse_const_literal("4'hF"), 15)
        self.assertIsNone(parse_const_literal("4'bx"))
        self.grh.write_text("\n".join([
            '{"formatVersion": 4,',
            '  "graphs": [{',
            '    "symbol": "top",',
            '    "semanticTree": {"sourceUnit": "unit", "circuit": "circuit", "nodes": [',
            '      {"parent": 0, "kind": "module", "name": "top"}',
            '    ]},',
            '      "vals": [',
            '        {"id": 1},',
            '        {"id": 2},',
            '        {"id": 3},',
            '        {"id": 4},',
            '        {"id": 5}',
            '      ],',
            '      "ops": [',
            '        {"id": 1, "sym": "r", "kind": "kRegister", "in": [], "out": [], '
            '"attrs": {"shape": {"t": "int[]", "vs": [3]}, "width": {"t": "int", "v": 3}}},',
            '        {"id": 2, "kind": "kConstant", "in": [], "out": [1], '
            '"attrs": {"constValue": {"t": "string", "v": "4\'d0"}}},',
            '        {"id": 3, "kind": "kConstant", "in": [], "out": [2], '
            '"attrs": {"constValue": {"t": "string", "v": "4\'d1"}}},',
            '        {"id": 4, "kind": "kAssign", "in": [2], "out": [3]},',
            '        {"id": 5, "kind": "kRegisterReadArrayPort", "in": [1], "out": [4], '
            '"attrs": {"regSymbol": {"t": "string", "v": "r"}}},',
            '        {"id": 6, "kind": "kRegisterReadArrayPort", "in": [3], "out": [5], '
            '"attrs": {"regSymbol": {"t": "string", "v": "r"}}},',
            '        {"id": 7, "kind": "kRegisterWritePort", "in": [], "out": [], '
            '"attrs": {"regSymbol": {"t": "string", "v": "r"}}}',
            '      ]',
            '  }]',
            '}',
            '',
        ]), encoding="utf-8")
        self.gsim_init.write_text("\n".join([
            '{"nodes": [',
            '  {"id": 1, "name": "r", "type": "NODE_REG_SRC", "status": "VALID_NODE", '
            '"width": 1, "dimension": [3]}',
            '],',
            '"edges": [',
            ']}',
            '',
        ]), encoding="utf-8")
        self.split.write_text("\n".join([
            '{"entries": [',
            '  {"parentId": 1, "parentName": "r", "parentWidth": 1, "parentDimension": [3], '
            '"memberIndex": 0, "memberId": 11, "memberName": "r_0"},',
            '  {"parentId": 1, "parentName": "r", "parentWidth": 1, "parentDimension": [3], '
            '"memberIndex": 1, "memberId": 12, "memberName": "r_1"},',
            '  {"parentId": 1, "parentName": "r", "parentWidth": 1, "parentDimension": [3], '
            '"memberIndex": 2, "memberId": 13, "memberName": "r_2"}',
            ']}',
            '',
        ]), encoding="utf-8")
        self.gsim_after.write_text("\n".join([
            '{"nodes": [',
            '  {"id": 11, "name": "r_0", "type": "NODE_REG_SRC", "status": "VALID_NODE"}',
            '],',
            '"edges": [',
            ']}',
            '',
        ]), encoding="utf-8")
        report = compare_state_elements(self.grh, self.gsim_init, self.split,
                                        self.gsim_after, self.work / "state-elements.json")
        self.assertEqual(report["totals"]["elements"], 3)
        self.assertEqual(report["totals"]["gsim_retained_elements"], 1)
        self.assertEqual(report["totals"]["coarse_surplus_elements"], 2)
        self.assertEqual(report["totals"]["static_read_elements"], 2)
        self.assertEqual(report["static_leaf_read_agreement"], {"gsim_fewer": 1})
        self.assertEqual(report["read_write_patterns"][0]["name"], "static_leaf__whole")
        self.assertEqual(report["mapping"]["issues"], {})
        family = report["top_families"][0]
        self.assertEqual(family["gsimSurvivingIndices"], [0])
        self.assertEqual(family["grhStaticReadIndices"], [0, 1])

        after = self.work / "post-split.json"
        after.write_text("\n".join([
            '{"formatVersion": 4,',
            '  "graphs": [{',
            '    "symbol": "top",',
            '      "vals": [],',
            '      "ops": [',
            '        {"id": 1, "sym": "r_0", "kind": "kRegister", "in": [], "out": [], '
            '"attrs": {"width": {"t": "int", "v": 1}}},',
            '        {"id": 2, "sym": "r_1", "kind": "kRegister", "in": [], "out": [], '
            '"attrs": {"width": {"t": "int", "v": 1}}}',
            '      ]',
            '  }]',
            '}',
            '',
        ]), encoding="utf-8")
        post = compare_post_split_state_elements(
            self.grh, after, self.gsim_init, self.split, self.gsim_after,
            self.work / "post-split-report.json")
        self.assertEqual(post["totals"]["elements"], 3)
        self.assertEqual(post["totals"]["grh_retained_elements"], 2)
        self.assertEqual(post["totals"]["gsim_retained_elements"], 1)
        self.assertEqual(post["totals"]["grh_removed_elements"], 1)
        self.assertEqual(post["totals"]["remaining_surplus_elements"], 1)
        self.assertEqual(post["totals"]["different_families"], 1)
        self.assertEqual(post["mapping"]["issues"], {})

    def test_rob_edge_path_classification(self):
        from array import array

        edges = array("Q", [
            pack(0, 1), pack(1, 4),
            pack(0, 2), pack(2, 3), pack(3, 4), pack(3, 6),
            pack(0, 5),
        ])
        pairs = {(0, 4), (0, 6), (0, 7)}
        two_hop = two_hop_paths(edges, pairs)
        self.assertEqual(two_hop, {(0, 4): [1]})
        unresolved = pairs - two_hop.keys()
        longer, statuses, truncated, _visits = longer_paths(
            build_adjacency(edges), unresolved, 0, 0)
        self.assertEqual(longer, {(0, 6): [2, 3]})
        self.assertEqual(statuses, {(0, 7): "no_path"})
        self.assertEqual(truncated, [])
        bypass = bypassed_source_paths(
            array("Q", [pack(0, 4)]), array("Q", [pack(0, 1), pack(1, 4)]), {(1, 4)})
        self.assertEqual(bypass, {(1, 4): [0]})

    def test_array_value_comparison(self):
        counter = iter(range(1, 100))

        def value(name, shape, element_width, sign=0, node_type="NODE_OTHERS", named=True):
            width = element_width
            for dimension in shape:
                width *= dimension
            return {
                "id": next(counter), "name": name, "aliases": [name] if named else [],
                "shape": shape, "width": width, "elementWidth": element_width,
                "sign": sign, "nodeType": node_type, "producerKind": "kAssign",
            }

        gsim = [
            value("a", [2], 3), value("b", [2], 3), value("c", [2], 3),
            value("g", [1], 1, node_type="NODE_REG_SRC"), value("s", [1], 1, sign=0),
            value("u", [2], -1),
        ]
        grh = [
            value("a", [2], 3), value("b", [2], 4), value("c", [3], 2),
            value("h", [1], 1), value("s", [1], 1, sign=1), value("", [2], 1, named=False),
            value("u", [2], 3),
        ]
        report = compare_array_values(grh, gsim)
        self.assertEqual(report["names"], {
            "exact": 2, "element_width_mismatch": 1, "shape_mismatch": 1,
            "grh_only": 1, "gsim_only": 1, "unknown_gsim_width": 1,
        })
        self.assertEqual(report["records"]["grh_unmapped"], 1)
        self.assertEqual(report["records"]["grh_exact"], 2)
        self.assertEqual(report["records"]["gsim_gsim_only"], 1)
        self.assertEqual(report["shape_or_width_mismatch_names"], 2)
        self.assertEqual(report["sign_mismatch_names"], 1)
        self.assertEqual(report["gsim_types"]["gsim_only"], {"NODE_REG_SRC": 1})

    def test_gsim_unmatched_intermediate_is_opt_in(self):
        self.gsim_after.write_text("\n".join([
            '{"nodes": [',
            '  {"id": 1, "name": "first", "type": "NODE_OTHERS", "status": "VALID_NODE"},',
            '  {"id": 2, "name": "middle", "type": "NODE_OTHERS", "status": "VALID_NODE"},',
            '  {"id": 3, "name": "second", "type": "NODE_OTHERS", "status": "VALID_NODE"}',
            '],',
            '"edges": [',
            '  ["first", "middle"],',
            '  ["middle", "second"]',
            ']}',
            '',
        ]), encoding="utf-8")
        name_to_id = {"first": 0, "second": 1}
        raw, _contracted, _stats = collect_gsim(self.gsim_after, name_to_id)
        self.assertEqual(raw, set())
        name_to_id = {"first": 0, "second": 1}
        raw, contracted, stats = collect_gsim(self.gsim_after, name_to_id, include_unmatched=True)
        expected = {pack(0, 2), pack(2, 1)}
        self.assertEqual(raw, expected)
        self.assertEqual(contracted, expected)
        self.assertEqual(stats["coarsen"]["extra_ordinary_nodes"], 1)

    def test_gsim_forward_reachability_stops_at_effect_root(self):
        index = GraphIndex()
        start = index.add_name("r")
        middle = index.add_name("middle")
        root = index.add_name("printf", 42, "NODE_SPECIAL")
        index.starts[start] = 0
        index.ends[start] = 1
        index.starts[middle] = 1
        index.ends[middle] = 2
        index.targets.extend([middle, root])
        index.edge_count = 2
        result = forward_reachable(index, start, 10)
        self.assertEqual(result["root"], root)
        self.assertEqual(result["seen"], {start, middle, root})
        self.assertEqual(result["reason"], "root_reached")

    def test_gsim_reachability_budget_is_explicit(self):
        index = GraphIndex()
        first = index.add_name("a")
        second = index.add_name("b")
        index.starts[first] = 0
        index.ends[first] = 1
        index.targets.append(second)
        index.edge_count = 1
        result = forward_reachable(index, first, 2)
        self.assertTrue(result["truncated"])
        self.assertIn("budget 2", result["reason"])

    def test_reachability_mechanism_uses_firrtl_shape(self):
        self.assertEqual(mechanism("kConcat", "node x = cat(a, b)"),
                         "concat_to_static_slice_liveness")
        self.assertEqual(mechanism("kMux", "when cond"),
                         "mux_with_constant_or_known_select")

    def test_direct_state_symbol_trace(self):
        self.candidates.write_text("", encoding="utf-8")
        names = self.work / "state-names.txt"
        names.write_text("r_0\n", encoding="utf-8")
        self.grh.write_text("\n".join([
            '{"formatVersion": 4,',
            '  "graphs": [{',
            '    "symbol": "top",',
            '    "semanticTree": {"sourceUnit": "unit", "circuit": "circuit", "nodes": [',
            '      {"parent": 0, "kind": "module", "name": "top"}',
            '    ]},',
            '      "vals": [',
            '        {"id": 1}',
            '      ],',
            '      "ops": [',
            '        {"id": 1, "kind": "kRegisterReadPort", "in": [], "out": [1], '
            '"attrs": {"regSymbol": {"t": "string", "v": "r_0"}}},',
            '        {"id": 2, "kind": "kSystemTask", "in": [1], "out": []}',
            '    ]',
            '  }]',
            '}',
            '',
        ]), encoding="utf-8")
        report = trace_grh(self.grh, self.candidates, self.unmatched, names,
                           self.work / "state-trace.json", 10, direct_state_symbols=True)
        self.assertEqual(report["targets"]["r_0"]["root"], "kSystemTask")
        self.assertEqual(report["targets"]["r_0"]["entities"], 3)
        self.assertFalse(report["targets"]["r_0"]["truncated"])

    def test_effect_root_reachability_is_not_legitimate_by_itself(self):
        self.candidates.write_text("", encoding="utf-8")
        self.grh.write_text("\n".join([
            '{"formatVersion": 4,',
            '  "graphs": [{',
            '    "symbol": "top",',
            '    "semanticTree": {"sourceUnit": "unit", "circuit": "circuit", "nodes": [',
            '      {"parent": 0, "kind": "module", "name": "top"}',
            '    ]},',
            '      "vals": [',
            '        {"id": 1}',
            '      ],',
            '      "ops": [',
            '        {"id": 1, "kind": "kRegisterReadPort", "in": [], "out": [1], '
            '"attrs": {"regSymbol": {"t": "string", "v": "r_0"}}},',
            '        {"id": 2, "sym": "top$_op_0", "kind": "kSystemTask", '
            '"in": [1], "out": []}',
            '    }]',
            '}',
            '',
        ]), encoding="utf-8")
        row = {
            "category": "plain_register", "key": "plain:r_0", "side": "grh",
            "grh_name": "r_0", "grh_pre": True, "grh_post": True,
            "gsim_pre": True, "gsim_post": False, "survival": "grh_only",
        }
        gsim_roots = {
            "special": [{"name": "top$PRINTF_1"}],
            "ext": {}, "top_io": {},
        }
        rows, summary = build_grh_extra_justification(
            self.grh, [row], self.work, gsim_before=gsim_roots,
            gsim_after=gsim_roots,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["gsim_root_alive"], True)
        self.assertEqual(rows[0]["verdict"], "unresolved")
        self.assertIn("dependency divergence is not established", rows[0]["verdict_reason"])
        self.assertEqual(summary["verdict_counts"]["unresolved"], 1)

    def test_effect_identity_pairs_by_module_line_and_kind(self):
        grh_before = {
            "system_tasks": [{
                "id": 1, "sym": "top$child$_op_0", "attrs": {
                    "firrtl.line": {"t": "int", "v": 42},
                    "firrtl.effectKind": {"t": "string", "v": "printf"},
                },
            }],
            "dpi_calls": [{"id": 2, "kind": "kDpicCall", "attrs": {}}],
            "dpi_imports": [], "instances": [], "blackboxes": [],
        }
        grh_after = {"system_tasks": grh_before["system_tasks"],
                     "dpi_calls": [], "dpi_imports": [], "instances": [], "blackboxes": []}
        special = {"name": "top$child$PRINTF_42", "lineno": 42,
                   "type": "NODE_SPECIAL", "status": "VALID_NODE"}
        gsim_before = {"special": [special], "ext": {}}
        gsim_after = {"special": [], "ext": {}}
        rows, summary = build_effect_identity(grh_before, grh_after,
                                              gsim_before, gsim_after)
        pair = next(row for row in rows if row["side"] == "paired")
        self.assertEqual(pair["survival"], "grh_only")
        self.assertEqual(pair["module_path"], "top$child")
        self.assertEqual(pair["grh_line"], 42)
        self.assertEqual(summary["pairs"], 1)
        self.assertEqual(summary["unmatched_grh"], 1)
        self.assertEqual(summary["unmatched_gsim"], 0)

    def test_effect_identity_without_line_is_not_pairable(self):
        grh = {"system_tasks": [{"id": 1, "sym": "top$_op_0", "attrs": {}}],
               "dpi_calls": [], "dpi_imports": [], "instances": [], "blackboxes": []}
        gsim = {"special": [{"name": "top$PRINTF_7", "lineno": 7}], "ext": {}}
        rows, summary = build_effect_identity(grh, grh, gsim, {"special": [], "ext": {}})
        self.assertTrue(all(not row["pairable"] for row in rows))
        self.assertEqual(summary["pairs"], 0)
        self.assertEqual(summary["not_pairable"], len(rows))

    def test_effect_identity_accepts_named_gsim_stop(self):
        grh = {"system_tasks": [{
                    "id": 1, "sym": "top$_op_0", "attrs": {
                        "firrtl.line": {"t": "int", "v": 7},
                        "firrtl.effectKind": {"t": "string", "v": "stop"},
                    }}],
               "dpi_calls": [], "dpi_imports": [], "instances": [], "blackboxes": []}
        gsim = {"special": [{"name": "top$stop", "lineno": 7}], "ext": {}}
        rows, summary = build_effect_identity(grh, grh, gsim, gsim)
        self.assertEqual(summary["pairs"], 1)
        self.assertEqual(rows[0]["survival"], "both_alive")

    def test_srcline_compare_ignores_only_operation_attrs(self):
        v13 = self.work / "v13.json"
        v14 = self.work / "v14.json"
        v13.write_text(
            '{"graphs": [{\n'
            '"vals": [\n'
            '{"id": 1, "w": 1}\n'
            '],\n'
            '"ops": [\n'
            '{"id": 2, "kind": "kSystemTask", "attrs": {"name": {"t": "string", "v": "write"}}}\n'
            ']\n]}]}\n',
            encoding="utf-8")
        v14.write_text(
            '{"graphs": [{\n'
            '"vals": [\n'
            '{"id": 1, "w": 1}\n'
            '],\n'
            '"ops": [\n'
            '{"id": 2, "kind": "kSystemTask", "attrs": {"name": {"t": "string", "v": "write"}, '
            '"firrtl.line": {"t": "int", "v": 7}}}\n'
            ']\n]}]}\n',
            encoding="utf-8")
        result = compare_stage(v13, v14)
        self.assertTrue(result["structurally_equal"])
        self.assertEqual(result["attribute_only_differences"], 1)
        self.assertEqual(result["v13"]["records"], {"ops": 1, "vals": 1})

    def test_srcline_compare_reports_structural_difference(self):
        v13 = self.work / "v13-diff.json"
        v14 = self.work / "v14-diff.json"
        v13.write_text('{"graphs": [{\n"vals": [],\n"ops": [\n{"id": 1, "kind": "kAssign"}\n]\n]}]}\n', encoding="utf-8")
        v14.write_text('{"graphs": [{\n"vals": [],\n"ops": [\n{"id": 1, "kind": "kMux"}\n]\n]}]}\n', encoding="utf-8")
        result = compare_stage(v13, v14)
        self.assertFalse(result["structurally_equal"])
        self.assertEqual(result["structural_mismatches"], 1)

    def test_anchor_alignment_helpers(self):
        self.assertEqual(survival_label(True, True), "both_alive")
        self.assertEqual(survival_label(True, False), "grh_only")
        self.assertEqual(survival_label(False, True), "gsim_only")
        self.assertEqual(survival_label(False, False), "both_dead")
        self.assertEqual(suffix_kind("cpu$mem__DOT__read__DOT__ADDR"), "gsim_addr_pipeline")
        self.assertEqual(suffix_kind("cpu$mem__DOT__read__DOT__ADDRESS"), "gsim_address_generated")
        self.assertEqual(suffix_kind("cpu$pipe__DOT__copy__DOT__copySrc"), "gsim_copy_derived")
        self.assertEqual(generated_reg_reason({"name": "cpu$queue$ram__DOT__data", "width": 64}),
                         "gsim_depth1_memory_conversion")
        self.assertEqual(generated_reg_reason({"name": "cpu$zero", "width": 0}),
                         "gsim_zero_width_register")
        self.assertEqual(
            generated_reg_reason({
                "name": "cpu$bitmapcache$ramDatas__DOT__tag_3", "width": 25,
            }),
            "gsim_ramdatas_residual",
        )
        self.assertEqual(name_pattern("cpu$queue_17$entry_003"), "cpu$queue_#$entry_#")

    def test_mechanism_representatives_cover_low_frequency_buckets(self):
        rows = [
            {"mechanism": "gsim_dependency_unresolved:kAssign",
             "grh_name": "assign_name", "divergence_kind": "kAssign",
             "divergence_op_id": 7, "divergence_semantic_id": 9,
             "divergence_lineno": 11},
            {"mechanism": "root_mapping_unresolved",
             "grh_name": "root_name", "divergence_kind": "kMux"},
            {"mechanism": "gsim_dependency_unresolved:kAssign",
             "grh_name": "later_assign"},
        ]
        representatives = mechanism_representatives(rows)
        self.assertEqual(
            representatives["gsim_dependency_unresolved:kAssign"]["name"],
            "assign_name",
        )
        self.assertEqual(
            representatives["root_mapping_unresolved"]["name"],
            "root_name",
        )
        self.assertEqual(set(representatives), {
            "gsim_dependency_unresolved:kAssign", "root_mapping_unresolved",
        })

    def test_state_family_report_filters_split_map_by_exact_parent(self):
        report = self.work / "state-families.json"
        report.write_text(
            '{"families": [{"symbol": "keep__DOT__state"}]}\n',
            encoding="utf-8",
        )
        split_map = self.work / "split-map.json"
        split_map.write_text("\n".join([
            '{"parentId": 1, "parentName": "keep$$state", "memberId": 11, '
            '"memberName": "keep$$state[0]", "memberIndex": 0, "memberWidth": 1}',
            '{"parentId": 2, "parentName": "drop$$state", "memberId": 21, '
            '"memberName": "drop$$state[0]", "memberIndex": 0, "memberWidth": 1}',
            "",
        ]), encoding="utf-8")
        init = {
            "array_nodes": {
                1: {"id": 1, "width": 1, "dimension": [1]},
                2: {"id": 2, "width": 1, "dimension": [1]},
            },
            "memories": {},
        }
        names = load_state_family_names(report)
        split = load_split_state_map(split_map, init, state_family_names=names)
        self.assertEqual(names, {"keep__DOT__state"})
        self.assertEqual(split["stats"]["families"], 1)
        self.assertEqual(split["stats"]["members"], 1)
        self.assertEqual(list(split["families"].values())[0]["parent_name"],
                         "keep__DOT__state")


if __name__ == "__main__":
    unittest.main()
