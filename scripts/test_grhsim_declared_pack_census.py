"""Synthetic-fixture tests for the declared pack census (NO00026)."""

import contextlib
from collections import Counter, defaultdict
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from grhsim_bit_update_census import Model
from grhsim_declared_pack_census import (
    build_universe, classify_forms, cones_match, control_signature, family_key,
    leaf_label, m_align, m_ctrl, m_iso, pack_cross_check, read_pack_members,
    read_reg_to_mem, run, stem_of, update_signature, verify_family_isomorphism,
)

ENDPOINT = ("Difftest enabled\ninstrCnt = 240349, cycleCnt = 99996\n"
            "Guest cycle spent: 100001\nEXCEEDING CYCLE/INSTR LIMIT at pc = 0x80000c0c\n"
            "Host time spent: 123ms\ncycles=100000 max_cycles=100000\n")


class Builder:
    def __init__(self):
        self.m = {"strings": [], "types": [[1, 0, "logic", 1, False, "2-state", 0, 0],
                                           [2, 0, "logic", 2, False, "2-state", 0, 0]],
                  "values": [], "operations": [], "states": [], "init": [],
                  "declaredSymbols": []}
        self.en = self.input("en_sig")
        self.mask = self.input("mask_sig")
        self.clk = self.input("clk")

    def intern(self, text):
        if text not in self.m["strings"]:
            self.m["strings"].append(text)
        return self.m["strings"].index(text) + 1

    def declare(self, name):
        self.m["declaredSymbols"].append(self.intern(name))

    def state(self, name, init=0, tid=1, declare=False):
        sid = len(self.m["states"]) + 1
        self.m["states"].append([sid, self.intern(name), tid, 0])
        text = f"1'b{init}" if tid != 2 else f"2'b{init:02b}"
        self.m["init"].append([sid, [[self.intern("core.init.const"),
                                      [[self.intern("value"), "string", text]]]]])
        if declare:
            self.declare(name)
        return sid

    def value(self, name="", width=1):
        vid = len(self.m["values"]) + 1
        self.m["values"].append([vid, 1 if width == 1 else 2,
                                 self.intern(name) if name else 0, 0])
        return vid

    def op(self, kind, args, name="", width=1, refs=None, params=None):
        oid = len(self.m["operations"]) + 1
        result = self.value(name, width)
        self.m["operations"].append([oid, self.intern(kind), 0, 0, list(args), [result],
                                     refs or [], [[self.intern(k), "string", v]
                                                  for k, v in (params or {}).items()]])
        return result

    def input(self, name):
        return self.op("core.input.read", [], name=name)

    def constant(self, text):
        return self.op("core.compute.constant", [], params={"constValue": text})

    def read(self, sid):
        return self.op("core.state.read", [], refs=[["state", sid]])

    def regwrite(self, sid, hist, en, data, mask, clk, edge="posedge"):
        oid = len(self.m["operations"]) + 1
        self.m["operations"].append([oid, self.intern("core.state.regWrite"), 0, 0,
                                     [en, data, mask, clk], [],
                                     [["state", sid], ["state", hist]],
                                     [[self.intern("event_edges"), "strings", [edge]]]])
        return oid

    def reg_family(self, names, kind="core.compute.xor", edge="posedge", data_width=1,
                   second_leaf=None):
        sids = []
        for name in names:
            sid = self.state(name, declare=True)
            hist = self.state(f"{name}$past")
            data = self.op(kind, [self.read(sid), second_leaf or self.en], width=data_width)
            self.regwrite(sid, hist, self.en, data, self.mask, self.clk, edge=edge)
            sids.append(sid)
        return sids


def add_mapping(model):
    compute = [op[0] for op in model["operations"]
               if model["strings"][op[1] - 1] != "core.state.regWrite"]
    model["mappings"] = [[[0, 0, [[100, 0, 3, 0, [], compute],
                                 [10, 0, 6, 0, [11], []], [11, 10, 5, 0, [100], []]], [],
                          [[[None, [[None, [[1, 10, None, 0]]]]]]]]]]


def families_of(model):
    universe = build_universe(model)
    grouped = defaultdict(list)
    for rec in universe["members"].values():
        grouped[(rec["module"], rec["stem"])].append(rec)
    fams = {key: sorted(members, key=lambda r: r["name"])
            for key, members in sorted(grouped.items()) if len(members) >= 2}
    return fams, universe


def write_json(path, model):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model))


def write_pack(path, rows):
    path.write_text("packed_state\tbit_index\tmember_name\tinit_bit\n" + "".join(
        f"{word}\t{bit}\t{member}\t{init}\n" for word, bit, member, init in rows))


def write_reg2mem(path, first_states):
    header = ("source\trows\tbase\twrites\tstatus\tfirst_state\tdetail\twrite_savings\t"
              "read_savings\tcombined_savings\n")
    path.write_text(header + "".join(f"write\t1024\t0\t3\tmerged\t{name}\tplan=writes\t"
                                     f"-19\t2044\t3049\n" for name in first_states))


def write_run(path, body=10):
    path.write_text(ENDPOINT + f"[grhsim-dyn] sn 100 act={body} body={body} grp={2 * body} "
                    f"chg=3\n[grhsim-dyn] totals grp_pub={body} grp_fire=3\n")


def write_counter_site(directory):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "model.cpp").write_text("++cpu_dyn_sn_grp[100];\n++cpu_dyn_sn_grp[100];\n"
                                         "cpu_dyn_sn_chg[100]+=cpu_dyn_any;\n"
                                         "                    ++cpu_dyn_grp_pub;\n")


def invoke(tmp, post, final=None, pack=None, reg2mem=None, run1=None, run2=None,
           sample_verify=0, sample_seed=20260928, out="out"):
    args = SimpleNamespace(post_lower_json=post, final_json=final, pack_members=pack,
                           reg_to_mem=reg2mem, run1=run1, run2=run2, top_n=25,
                           sample_verify=sample_verify, sample_seed=sample_seed,
                           out_dir=Path(tmp) / out)
    with contextlib.redirect_stdout(io.StringIO()):
        return run(args)


def dynamic_fixture(tmp):
    post = Builder()
    post.reg_family(["top$m$foo_0", "top$m$foo_1"])
    post.reg_family(["top$m$bar_0", "top$m$bar_1"])
    final = Builder()
    final.reg_family(["top$m$foo_0", "top$m$foo_1"])
    packed = final.state("packed_bits_0", tid=2)
    phist = final.state("packed_bits_0$past")
    data = final.op("core.compute.or", [final.constant("1'b0"), final.constant("1'b1")])
    final.regwrite(packed, phist, final.en, data, final.mask, final.clk)
    add_mapping(final.m)
    paths = SimpleNamespace(
        post=Path(tmp) / "post_lower.json", final=Path(tmp) / "final" / "checkpoint.json",
        pack=Path(tmp) / "pack_members.tsv", reg2mem=Path(tmp) / "reg_to_mem.tsv",
        run1=Path(tmp) / "run1.log", run2=Path(tmp) / "run2.log")
    write_json(paths.post, post.m)
    write_json(paths.final, final.m)
    write_counter_site(paths.final.parent / "model")
    write_pack(paths.pack, [("packed_bits_0", 0, "top$m$bar_0", "0"),
                            ("packed_bits_0", 1, "top$m$bar_1", "0")])
    write_reg2mem(paths.reg2mem, ["top$m$ghost_0"])
    write_run(paths.run1)
    write_run(paths.run2)
    return paths


class StemTest(unittest.TestCase):
    def test_stem_boundaries(self):
        cases = {"x_0": "x", "loadDependency_0_1": "loadDependency",
                 "io_validCntDeqVec_0_REG": "io_validCntDeqVec_0_REG",
                 "x_1_": "x_1_", "_0": "_0", "_0_1": "_0", "a_1b": "a_1b", "foo": "foo"}
        for bare, expected in cases.items():
            self.assertEqual(stem_of(bare), expected, bare)

    def test_family_key_keeps_modules_apart(self):
        self.assertNotEqual(family_key("top$a$foo_0"), family_key("top$b$foo_0"))
        self.assertEqual(family_key("top$a$foo_0"), family_key("top$a$foo_1"))
        self.assertEqual(family_key("foo_2"), ("", "foo"))


class UniverseFormsTest(unittest.TestCase):
    def fixture(self):
        b = Builder()
        b.reg_family(["top$m$foo_0", "top$m$foo_1"])
        b.reg_family(["top$m$pk_0", "top$m$pk_1"])
        b.reg_family(["top$m$gone_0", "top$m$gone_1"])
        b.reg_family(["top$m$myst_0", "top$m$myst_1"])
        b.state("top$m$solo", declare=True)
        b.state("top$m$dup_0", declare=True)
        b.state("top$m$dup_0")
        b.declare("top$m$ghost")
        b.m["types"].append([3, 8, "array", 0, False, "", 0, 0])
        b.state("top$m$arr", tid=3, declare=True)
        return b

    def test_universe_closure_and_forms(self):
        b = self.fixture()
        fams, universe = families_of(b.m)
        self.assertEqual(len(universe["members"]), 10)
        self.assertEqual(universe["bits"], 11)
        self.assertEqual(universe["rejected"],
                         {"duplicate_state_name": {"count": 1, "bits": 1,
                                                   "samples": ["top$m$dup_0"]}})
        self.assertEqual(universe["declared_without_logic_state"], 2)
        self.assertEqual(universe["declared_non_logic_states"], 1)
        self.assertEqual(sorted(fams), [("top$m", stem) for stem in
                                        ("foo", "gone", "myst", "pk")])
        final = Builder()
        for name in ("top$m$foo_0", "top$m$foo_1", "top$m$solo"):
            final.state(name)
        final_names = {final.m["strings"][s[1] - 1] for s in final.m["states"]}
        forms = classify_forms(universe["members"], final_names,
                               {"top$m$pk_0", "top$m$pk_1"}, {"top$m$gone_0"})
        self.assertEqual(dict(sorted(Counter(forms.values()).items())),
                         {"memified": 1, "other": 4, "packed": 2, "standalone": 3})
        with tempfile.TemporaryDirectory() as tmp:
            post = Path(tmp) / "post.json"
            write_json(post, b.m)
            final_path = Path(tmp) / "final.json"
            write_json(final_path, final.m)
            pack = Path(tmp) / "pack.tsv"
            write_pack(pack, [("packed_bits_7", 0, "top$m$pk_0", "0"),
                              ("packed_bits_7", 1, "top$m$pk_1", "1")])
            reg2mem = Path(tmp) / "r2m.tsv"
            write_reg2mem(reg2mem, ["top$m$gone_0"])
            report = invoke(tmp, post, final=final_path, pack=pack, reg2mem=reg2mem)
        self.assertTrue(report["closures"]["bit_closure"])
        self.assertTrue(report["closures"]["form_closure"])
        self.assertEqual(report["closures"]["universe_bits"], 11)
        fam = report["m_fam"]
        self.assertEqual(fam["family_count"], 4)
        self.assertEqual(fam["singleton_count"], 2)
        self.assertEqual(fam["family_bits"], 8)
        self.assertEqual(fam["singleton_bits"], 2)
        self.assertEqual(fam["forms"]["counts"],
                         {"memified": 1, "other": 4, "packed": 2, "standalone": 3})
        rows = {(r["module"], r["stem"]): r for r in fam["families"]}
        self.assertEqual(rows[("top$m", "gone")]["forms"], {"memified": 1, "other": 1})
        self.assertEqual(rows[("top$m", "pk")]["forms"], {"packed": 2})

    def test_missing_optional_inputs_mark_unavailable(self):
        b = self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            post = Path(tmp) / "post.json"
            write_json(post, b.m)
            report = invoke(tmp, post)
        self.assertTrue(report["closures"]["bit_closure"])
        self.assertFalse(report["m_align"]["available"])
        self.assertFalse(report["m_align_iso_info"]["available"])
        self.assertFalse(report["m_dyn"]["available"])
        forms = report["m_fam"]["forms"]
        self.assertEqual(forms["counts"], {"unavailable_form": 10})
        self.assertEqual(sorted(forms["missing_inputs"]),
                         ["final checkpoint", "pack-members TSV", "reg-to-mem TSV"])


class AlignTest(unittest.TestCase):
    def test_mixed_pure_and_nondeclared_words(self):
        b = Builder()
        for name in ("top$m$foo_0", "top$m$foo_1", "top$m$foo_2",
                     "top$m$bar_0", "top$m$bar_1"):
            b.state(name, declare=True)
        _, universe = families_of(b.m)
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / "pack.tsv"
            write_pack(pack, [("packed_bits_0", 1, "top$m$foo_1", "0"),
                              ("packed_bits_0", 0, "top$m$foo_0", "0"),
                              ("packed_bits_1", 0, "top$m$foo_2", "0"),
                              ("packed_bits_1", 1, "top$m$bar_0", "0"),
                              ("packed_bits_2", 0, "top$m$bar_1", "0"),
                              ("packed_bits_2", 1, "internal_tmp_9", "0"),
                              ("packed_bits_3", 0, "internal_tmp_10", "0")])
            words = read_pack_members(pack)
        report = m_align(words, universe)
        self.assertEqual(report["word_count"], 4)
        self.assertEqual(report["member_rows"], 7)
        self.assertEqual(report["single_family_words"], 1)
        self.assertEqual(report["single_family_word_ratio"], 0.25)
        self.assertEqual(report["single_family_bit_ratio"], 2 / 7)
        self.assertEqual(report["words_with_nondeclared_members"], 2)
        self.assertEqual(report["members_not_in_universe"], 2)
        self.assertEqual(report["families_with_packed_members"], 2)
        self.assertEqual(report["families_split_across_words"], 2)
        self.assertEqual(report["families_per_word"]["max"], 2)
        self.assertEqual(report["word_size"]["sum"], 7)

    def test_bad_header_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / "pack.tsv"
            pack.write_text("word\tmember\npacked_bits_0\tx\n")
            with self.assertRaisesRegex(ValueError, "header"):
                read_pack_members(pack)
            reg2mem = Path(tmp) / "r2m.tsv"
            reg2mem.write_text("a\tb\n1\t2\n")
            with self.assertRaisesRegex(ValueError, "first_state"):
                read_reg_to_mem(reg2mem)


class IsoTest(unittest.TestCase):
    def iso(self, b):
        fams, _ = families_of(b.m)
        return m_iso(Model(b.m), fams)

    def test_self_reference_permutation_is_isomorphic(self):
        b = Builder()
        b.reg_family(["top$m$foo_0", "top$m$foo_1"])
        report, digests, candidates = self.iso(b)
        self.assertEqual(report["family_count"], 1)
        row = report["families"][0]
        self.assertTrue(row["isomorphic"])
        self.assertEqual(row["signature_classes"], 1)
        self.assertEqual(digests["top$m$foo_0"], digests["top$m$foo_1"])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["members"], ["top$m$foo_0", "top$m$foo_1"])
        self.assertEqual(report["by_size"]["2"]["isomorphic"], 1)

    def test_topology_difference_breaks_isomorphism(self):
        b = Builder()
        b.reg_family(["top$m$foo_0"], kind="core.compute.xor")
        b.reg_family(["top$m$foo_1"], kind="core.compute.and")
        report, digests, _ = self.iso(b)
        row = report["families"][0]
        self.assertFalse(row["isomorphic"])
        self.assertEqual(row["signature_classes"], 2)
        self.assertNotEqual(digests["top$m$foo_0"], digests["top$m$foo_1"])

    def test_width_difference_breaks_isomorphism(self):
        b = Builder()
        b.reg_family(["top$m$foo_0"], data_width=1)
        b.reg_family(["top$m$foo_1"], data_width=2)
        report, _, _ = self.iso(b)
        self.assertEqual(report["families"][0]["signature_classes"], 2)
        self.assertFalse(report["families"][0]["isomorphic"])

    def test_leaf_reference_difference_breaks_isomorphism(self):
        b = Builder()
        other = b.input("other_sig")
        b.reg_family(["top$m$foo_0"])
        b.reg_family(["top$m$foo_1"], second_leaf=other)
        report, _, _ = self.iso(b)
        self.assertEqual(report["families"][0]["signature_classes"], 2)

    def test_leaf_labels(self):
        b = Builder()
        sids = b.reg_family(["top$m$foo_0", "top$m$foo_1"])
        const = b.constant("1'b1")
        read_self = b.read(sids[1])
        read_fam = b.read(sids[0])
        view = Model(b.m)
        ordinals = {"top$m$foo_0": 0, "top$m$foo_1": 1}
        self.assertEqual(leaf_label(view, read_self, "top$m$foo_1", ordinals), ["self"])
        self.assertEqual(leaf_label(view, read_fam, "top$m$foo_1", ordinals), ["fam", 0])
        self.assertEqual(leaf_label(view, const, "top$m$foo_1", ordinals),
                         ["const", "1'b1"])
        self.assertEqual(leaf_label(view, b.en, "top$m$foo_1", ordinals),
                         ["name", "en_sig"])

    def test_unsigned_members_are_reported(self):
        b = Builder()
        sids = b.reg_family(["top$m$foo_0", "top$m$foo_1"])
        b.regwrite(sids[0], b.state("top$m$extra_past"), b.en,
                   b.op("core.compute.xor", [b.read(sids[0]), b.en]), b.mask, b.clk)
        view = Model(b.m)
        sig, reason = update_signature(view, sids[0], "top$m$foo_0",
                                       {"top$m$foo_0": 0, "top$m$foo_1": 1})
        self.assertIsNone(sig)
        self.assertEqual(reason, "multiple_writers")
        report, _, _ = self.iso(b)
        row = report["families"][0]
        self.assertFalse(row["isomorphic"])
        self.assertEqual(row["unsigned"], {"multiple_writers": 1})


class CtrlTest(unittest.TestCase):
    def test_control_signature_subfamilies(self):
        b = Builder()
        b.reg_family(["top$m$foo_0", "top$m$foo_1"])
        b.reg_family(["top$m$bar_0"], edge="posedge")
        b.reg_family(["top$m$bar_1"], edge="negedge")
        mask2 = b.input("mask2_sig")
        b.reg_family(["top$m$baz_0"])
        hist = b.state("top$m$baz_1$past")
        baz1 = b.state("top$m$baz_1", declare=True)
        data = b.op("core.compute.xor", [b.read(baz1), b.en])
        b.regwrite(baz1, hist, b.en, data, mask2, b.clk)
        qux0 = b.state("top$m$qux_0", declare=True)
        qux1 = b.state("top$m$qux_1", declare=True)
        shared_hist = b.state("top$m$qux_past")
        for sid in (qux0, qux1):
            data = b.op("core.compute.xor", [b.read(sid), b.en])
            b.regwrite(sid, shared_hist, b.en, data, b.mask, b.clk)
        fams, _ = families_of(b.m)
        report, digests, mergeable = m_ctrl(Model(b.m), fams)
        rows = {(r["module"], r["stem"]): r for r in report["families"]}
        self.assertEqual(rows[("top$m", "foo")]["subfamilies"], 1)
        self.assertEqual(rows[("top$m", "foo")]["mergeable_subfamilies"], 1)
        self.assertEqual(rows[("top$m", "foo")]["mergeable_bits"], 2)
        self.assertEqual(rows[("top$m", "bar")]["subfamilies"], 2)
        self.assertEqual(rows[("top$m", "bar")]["mergeable_subfamilies"], 0)
        self.assertEqual(rows[("top$m", "baz")]["subfamilies"], 2)
        self.assertEqual(rows[("top$m", "qux")]["rejected"],
                         {"nonprivate_or_unknown_history": 2})
        self.assertEqual(report["rejected"], {"nonprivate_or_unknown_history": 2})
        self.assertEqual(report["eligible_members"], 6)
        self.assertEqual(report["mergeable_subfamilies"], 1)
        self.assertEqual(report["mergeable_bits"], 2)
        self.assertEqual(mergeable[("top$m", "foo")], ["top$m$foo_0", "top$m$foo_1"])
        self.assertEqual(digests["top$m$foo_0"], digests["top$m$foo_1"])
        self.assertNotEqual(digests["top$m$bar_0"], digests["top$m$bar_1"])
        view = Model(b.m)
        sig, reason = control_signature(view, qux0)
        self.assertIsNone(sig)
        self.assertEqual(reason, "nonprivate_or_unknown_history")


class CrossCheckTest(unittest.TestCase):
    def test_packed_word_violations_are_counted(self):
        b = Builder()
        b.reg_family(["top$m$foo_0", "top$m$foo_1"], kind="core.compute.xor", edge="posedge")
        b.reg_family(["top$m$bar_0", "top$m$bar_1"], kind="core.compute.and", edge="negedge")
        b.reg_family(["top$m$baz_0", "top$m$baz_1"], kind="core.compute.xor", edge="posedge")
        fams, _ = families_of(b.m)
        view = Model(b.m)
        _, iso_digests, _ = m_iso(view, fams)
        _, ctrl_digests, _ = m_ctrl(view, fams)
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / "pack.tsv"
            write_pack(pack, [("packed_bits_0", 0, "top$m$foo_0", "0"),
                              ("packed_bits_0", 1, "top$m$bar_0", "0"),
                              ("packed_bits_1", 0, "top$m$foo_1", "0"),
                              ("packed_bits_1", 1, "top$m$baz_0", "0"),
                              ("packed_bits_2", 0, "top$m$bar_1", "0")])
            words = read_pack_members(pack)
        iso_gate, iso_violating = pack_cross_check(words, iso_digests)
        self.assertEqual(iso_gate["words_total"], 3)
        self.assertEqual(iso_gate["words_checked"], 2)
        self.assertEqual(iso_gate["mismatches"], 1)
        self.assertEqual(iso_violating, ["packed_bits_0"])
        self.assertEqual(len(iso_gate["mismatch_samples"]), 1)
        self.assertEqual(iso_gate["mismatch_samples"][0]["word"], "packed_bits_0")
        self.assertEqual(len(iso_gate["mismatch_samples"][0]["classes"]), 2)
        ctrl_gate, ctrl_violating = pack_cross_check(words, ctrl_digests)
        self.assertEqual(ctrl_gate["mismatches"], 1)
        self.assertEqual(ctrl_gate["words_checked"], 2)
        self.assertEqual(ctrl_violating, ["packed_bits_0"])


class CtrlGateExplanationTest(unittest.TestCase):
    def test_id_distinct_but_structurally_identical_enables_are_explained(self):
        b = Builder()
        # foo enables are structurally identical but carry distinct value ids
        # (two separate not ops; canonicalize-compute would merge them later).
        for i in (0, 1):
            sid = b.state(f"top$m$foo_{i}", declare=True)
            hist = b.state(f"top$m$foo_{i}$past")
            en_i = b.op("core.compute.not", [b.en])
            data = b.op("core.compute.xor", [b.read(sid), en_i])
            b.regwrite(sid, hist, en_i, data, b.mask, b.clk)
        # bar carries a genuine difference: edge polarity.
        b.reg_family(["top$m$bar_0"], edge="posedge")
        b.reg_family(["top$m$bar_1"], edge="negedge")
        with tempfile.TemporaryDirectory() as tmp:
            post = Path(tmp) / "post.json"
            write_json(post, b.m)
            pack = Path(tmp) / "pack.tsv"
            write_pack(pack, [("packed_bits_0", 0, "top$m$foo_0", "0"),
                              ("packed_bits_0", 1, "top$m$foo_1", "0"),
                              ("packed_bits_1", 0, "top$m$bar_0", "0"),
                              ("packed_bits_1", 1, "top$m$bar_1", "0")])
            report = invoke(tmp, post, pack=pack)
        gate = report["m_align_ctrl_gate"]
        self.assertEqual(gate["words_checked"], 2)
        self.assertEqual(gate["violations"], 2)
        explanation = gate["explanation"]
        self.assertEqual(explanation["explained_by_structural_unification"], 1)
        self.assertEqual(explanation["residual_violations"], 1)
        self.assertEqual(explanation["residual_component_diffs"], {"edges": 1})
        sample = explanation["residual_samples"][0]
        self.assertEqual(sample["word"], "packed_bits_1")
        self.assertEqual(sample["components_differing"], ["edges"])
        # The demoted M-iso check is informational: identical data cones here.
        info = report["m_align_iso_info"]
        self.assertEqual(info["words_checked"], 2)
        self.assertEqual(info["mixed_signature_words"], 0)
        self.assertIn("informational", info["note"])


class UpperBoundTest(unittest.TestCase):
    def test_mixed_word_over_attribution_and_incomplete_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            post = Builder()
            post.reg_family(["top$m$foo_0", "top$m$foo_1"])
            post.reg_family(["top$m$bar_0", "top$m$bar_1"])
            post.reg_family(["top$m$gone_0", "top$m$gone_1"])
            final = Builder()
            final.reg_family(["top$m$foo_0"])
            final.reg_family(["top$m$gone_0"])
            packed = final.state("packed_bits_0", tid=2)
            phist = final.state("packed_bits_0$past")
            data = final.op("core.compute.or", [final.constant("1'b0"),
                                                final.constant("1'b1")])
            final.regwrite(packed, phist, final.en, data, final.mask, final.clk)
            add_mapping(final.m)
            post_path = Path(tmp) / "post.json"
            write_json(post_path, post.m)
            final_path = Path(tmp) / "final" / "checkpoint.json"
            write_json(final_path, final.m)
            write_counter_site(final_path.parent / "model")
            pack = Path(tmp) / "pack.tsv"
            write_pack(pack, [("packed_bits_0", 0, "top$m$bar_0", "0"),
                              ("packed_bits_0", 1, "top$m$foo_1", "0")])
            run1, run2 = Path(tmp) / "run1.log", Path(tmp) / "run2.log"
            write_run(run1)
            write_run(run2)
            report = invoke(tmp, post_path, final=final_path, pack=pack,
                            run1=run1, run2=run2)
        dyn = report["m_dyn"]
        self.assertEqual(dyn["measured_families"], 0)
        self.assertEqual(dyn["mixed_families"]["count"], 2)
        self.assertEqual(dyn["incomplete_families"]["count"], 1)
        self.assertEqual(dyn["union_execs"], 0)
        upper = dyn["upper_bound"]
        # {or, xor(foo_0), xor(gone_0)} x 10 fires; bar_1/gone_1 stay out.
        self.assertEqual(upper["union_execs"], 30)
        self.assertEqual(upper["compute_share"], 0.3)
        self.assertEqual(upper["mixed_family_word_cones"], 1)
        self.assertEqual(upper["incomplete_family_member_cones"], 1)
        self.assertEqual(upper["unattributable_members"], 2)


class SampleVerifyTest(unittest.TestCase):
    def test_matcher_agrees_with_digest_on_positive_and_negative(self):
        b = Builder()
        b.reg_family(["top$m$foo_0", "top$m$foo_1"])
        b.reg_family(["top$m$bar_0"], kind="core.compute.xor")
        b.reg_family(["top$m$bar_1"], kind="core.compute.and")
        fams, _ = families_of(b.m)
        view = Model(b.m)
        report, _, _ = m_iso(view, fams)
        rows = {(r["module"], r["stem"]): r for r in report["families"]}
        self.assertTrue(rows[("top$m", "foo")]["isomorphic"])
        self.assertFalse(rows[("top$m", "bar")]["isomorphic"])
        self.assertTrue(verify_family_isomorphism(view, fams[("top$m", "foo")]))
        self.assertFalse(verify_family_isomorphism(view, fams[("top$m", "bar")]))

    def test_matcher_handles_shared_subcones(self):
        b = Builder()
        sid0 = b.state("top$m$foo_0", declare=True)
        shared = b.op("core.compute.not", [b.read(sid0)])
        data0 = b.op("core.compute.and", [shared, shared])
        b.regwrite(sid0, b.state("top$m$foo_0$past"), b.en, data0, b.mask, b.clk)
        sid1 = b.state("top$m$foo_1", declare=True)
        first = b.op("core.compute.not", [b.read(sid1)])
        second = b.op("core.compute.not", [b.read(sid1)])
        data1 = b.op("core.compute.and", [first, second])
        b.regwrite(sid1, b.state("top$m$foo_1$past"), b.en, data1, b.mask, b.clk)
        fams, _ = families_of(b.m)
        view = Model(b.m)
        report, _, _ = m_iso(view, fams)
        self.assertFalse(report["families"][0]["isomorphic"])
        self.assertFalse(verify_family_isomorphism(view, fams[("top$m", "foo")]))
        b2 = Builder()
        for i in (0, 1):
            sid = b2.state(f"top$m$foo_{i}", declare=True)
            shared = b2.op("core.compute.not", [b2.read(sid)])
            data = b2.op("core.compute.and", [shared, shared])
            b2.regwrite(sid, b2.state(f"top$m$foo_{i}$past"), b2.en, data, b2.mask, b2.clk)
        fams2, _ = families_of(b2.m)
        view2 = Model(b2.m)
        self.assertTrue(m_iso(view2, fams2)[0]["families"][0]["isomorphic"])
        self.assertTrue(verify_family_isomorphism(view2, fams2[("top$m", "foo")]))

    def test_run_level_sample_verify_is_deterministic(self):
        b = Builder()
        b.reg_family(["top$m$foo_0", "top$m$foo_1"])
        b.reg_family(["top$m$baz_0", "top$m$baz_1"])
        b.reg_family(["top$m$bar_0"], kind="core.compute.xor")
        b.reg_family(["top$m$bar_1"], kind="core.compute.and")
        reports = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as tmp:
                post = Path(tmp) / "post.json"
                write_json(post, b.m)
                reports.append(invoke(tmp, post, sample_verify=4))
        sample = reports[0]["g3_sample_verify"]
        self.assertTrue(sample["enabled"])
        self.assertEqual(sample["seed"], 20260928)
        self.assertEqual(sample["sampled_isomorphic"], 2)
        self.assertEqual(sample["sampled_nonisomorphic"], 1)
        self.assertEqual(sample["disagreements"], 0)
        self.assertEqual(sample["agreement_rate"], 1.0)
        self.assertEqual(reports[1]["g3_sample_verify"], sample)


class DynamicTest(unittest.TestCase):
    def test_dynamic_arm_prices_standalone_and_packed_cones(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = dynamic_fixture(tmp)
            report = invoke(tmp, paths.post, final=paths.final, pack=paths.pack,
                            reg2mem=paths.reg2mem, run1=paths.run1, run2=paths.run2)
        dyn = report["m_dyn"]
        self.assertTrue(dyn["available"])
        self.assertEqual(dyn["candidate_families"], 2)
        self.assertEqual(dyn["measured_families"], 2)
        self.assertEqual(dyn["mixed_families"]["count"], 0)
        self.assertEqual(dyn["incomplete_families"]["count"], 0)
        self.assertEqual(dyn["union_ops"], 3)
        self.assertEqual(dyn["union_execs"], 30)
        self.assertEqual(dyn["compute_execs"], 100)
        self.assertEqual(dyn["compute_share"], 0.3)
        self.assertEqual(dyn["cycles"], 100001)
        top = dyn["top_families"]
        self.assertEqual([(r["stem"], r["execs"]) for r in top], [("foo", 20), ("bar", 10)])
        self.assertEqual(dyn["ctrl_mergeable_members"], 4)
        self.assertEqual(dyn["ctrl_mergeable_union_execs"], 30)
        upper = dyn["upper_bound"]
        self.assertEqual(upper["union_execs"], 30)
        self.assertEqual(upper["compute_share"], 0.3)
        self.assertEqual(upper["mixed_family_word_cones"], 0)
        self.assertEqual(upper["unattributable_members"], 0)
        self.assertEqual(report["m_ctrl"]["mergeable_by_form"],
                         {"members": {"packed": 2, "standalone": 2},
                          "bits": {"packed": 2, "standalone": 2}})
        gate = report["dynamic_gate"]
        self.assertTrue(gate["independent_runs_equal"])
        self.assertEqual(gate["compute_execs"], 100)
        self.assertTrue(report["closures"]["bit_closure"])
        forms = report["m_fam"]["forms"]["counts"]
        self.assertEqual(forms, {"packed": 2, "standalone": 2})

    def test_mixed_word_buckets_the_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = dynamic_fixture(tmp)
            write_pack(paths.pack, [("packed_bits_0", 0, "top$m$bar_0", "0"),
                                    ("packed_bits_0", 1, "top$m$foo_1", "0")])
            report = invoke(tmp, paths.post, final=paths.final, pack=paths.pack,
                            reg2mem=paths.reg2mem, run1=paths.run1, run2=paths.run2)
        dyn = report["m_dyn"]
        self.assertEqual(dyn["measured_families"], 0)
        self.assertEqual(dyn["mixed_families"]["count"], 2)
        self.assertEqual(dyn["mixed_families"]["samples"], ["top$m$bar", "top$m$foo"])
        self.assertEqual(dyn["union_execs"], 0)
        upper = dyn["upper_bound"]
        # Over-attribution: the whole mixed word cone plus the standalone
        # member cone of the mixed families; bar_1 (form other) stays out.
        self.assertEqual(upper["union_execs"], 20)
        self.assertEqual(upper["mixed_family_word_cones"], 1)
        self.assertEqual(upper["unattributable_members"], 1)
        self.assertEqual(report["m_align"]["single_family_words"], 0)

    def test_run_pair_must_be_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = dynamic_fixture(tmp)
            with self.assertRaisesRegex(ValueError, "both --run1 and --run2"):
                invoke(tmp, paths.post, final=paths.final, run1=paths.run1)


class DeterminismTest(unittest.TestCase):
    def test_two_runs_byte_equal(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = dynamic_fixture(tmp)
            invoke(tmp, paths.post, final=paths.final, pack=paths.pack,
                   reg2mem=paths.reg2mem, run1=paths.run1, run2=paths.run2, out="a")
            invoke(tmp, paths.post, final=paths.final, pack=paths.pack,
                   reg2mem=paths.reg2mem, run1=paths.run1, run2=paths.run2, out="b")
            for name in ("summary.json", "summary.md"):
                first = (Path(tmp) / "a" / name).read_bytes()
                second = (Path(tmp) / "b" / name).read_bytes()
                self.assertEqual(first, second, name)
            self.assertNotIn(str(tmp), (Path(tmp) / "a" / "summary.json").read_text())


if __name__ == "__main__":
    unittest.main()
