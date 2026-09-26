#!/usr/bin/env python3
"""Unit tests for grhsim_dyn_iclass_profile (NO00018)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grhsim_dyn_iclass_profile import (  # noqa: E402
    CLASSES,
    G4_ANCHOR_ARMS,
    G4_CEILING,
    G4_F_MEM,
    G4_GUARD_ALLOWANCE,
    bootstrap_ci,
    build_lookup,
    build_static_per_task,
    classify_insn,
    coldbias_table,
    dso_bucket,
    demangle_batch,
    estimate_offset,
    gate_g2,
    gate_g2_sd,
    interval_coverage,
    load_phase_ref,
    map_address,
    mem_base,
    merge_runs,
    parse_disasm,
    parse_perf_script_lines,
    run_analysis,
    split_operands,
    symbol_bucket,
    aggregate_samples,
)

TAB = "\t"

DISASM_TEXT = f"""\
emu:     file format elf64-x86-64

Disassembly of section .text:

0000000000001000 <_ZN13GrhSIM_SimTop12cpu_task_480Ev>:
 1000:{TAB}movzbl 0x70f(%rdi),%r9d
 1008:{TAB}test   %r9b,%r9b
 100b:{TAB}je     2000 <_ZN13GrhSIM_SimTop12cpu_task_480Ev+0x4c0e>
 1011:{TAB}mov    %rdi,-0x38(%rsp)
 1018:{TAB}and    $0x3f,%eax

0000000000002000 <_ZN13GrhSIM_SimTop14cpu_helper_321_0EPSt4byteRh>:
 2000:{TAB}orb    $0x4,0x170(%r14,%rdx,1)
 200a:{TAB}movzbl 0xc013a(%rax),%edx
 2011:{TAB}ret

0000000000003000 <_ZN13GrhSIM_SimTop8evaluateEv>:
 3000:{TAB}call   1000 <_ZN13GrhSIM_SimTop12cpu_task_480Ev>
 3005:{TAB}push   %rbp
 3006:{TAB}ret

0000000000004000 <malloc@plt>:
 4000:{TAB}jmp    *0x2fa2(%rip)        # 6fa8 <malloc@GLIBC_2.2.5>

0000000000008000 <_ZN13GrhSIM_SimTop12cpu_task_480Ev.cold>:
 8000:{TAB}mov    %eax,(%rdx)
 8004:{TAB}ret
"""

# cpu_task_480.cold uses a distinct mangled-style name for segment merging
# tests; the primary merge test below reuses an identical symbol header.


class TestOperandHelpers(unittest.TestCase):
    def test_split_operands_paren_aware(self):
        self.assertEqual(split_operands("$0x4,0x170(%r14,%rdx,1)"),
                         ["$0x4", "0x170(%r14,%rdx,1)"])
        self.assertEqual(split_operands("%rdi,-0x38(%rsp)"),
                         ["%rdi", "-0x38(%rsp)"])
        self.assertEqual(split_operands("%eax,%ebx,%ecx"),
                         ["%eax", "%ebx", "%ecx"])

    def test_mem_base(self):
        self.assertEqual(mem_base("0x170(%r14,%rdx,1)"), "%r14")
        self.assertEqual(mem_base("-0x38(%rsp)"), "%rsp")
        self.assertEqual(mem_base("(%rbp)"), "%rbp")
        self.assertEqual(mem_base("0x7c24fa9(%rip)"), "%rip")
        self.assertIsNone(mem_base("%rax"))


class TestClassify(unittest.TestCase):
    def test_mask_and(self):
        self.assertEqual(classify_insn("and", "$0x3f,%eax"), "mask_and")
        self.assertEqual(classify_insn("andl", "$0x1ff,%eax"), "mask_and")
        self.assertEqual(classify_insn("andq", "$0x7fff,%rax"), "mask_and")
        # native widths are excluded
        self.assertEqual(classify_insn("and", "$0xff,%eax"), "logic")
        self.assertEqual(classify_insn("and", "$0xffff,%eax"), "logic")
        self.assertEqual(classify_insn("and", "$0xffffffff,%eax"), "logic")
        self.assertEqual(classify_insn("and", "$0xffffffffffffffff,%rax"), "logic")
        # not 2^n-1
        self.assertEqual(classify_insn("and", "$0x1f1,%eax"), "logic")
        # register source
        self.assertEqual(classify_insn("and", "%rbx,%rcx"), "logic")

    def test_flag_rmw(self):
        self.assertEqual(classify_insn("orb", "$0x4,0x170(%r14,%rdx,1)"), "flag_rmw")
        self.assertEqual(classify_insn("or", "$0x1,(%r15)"), "flag_rmw")
        self.assertEqual(classify_insn("andb", "$0xfe,(%rax)"), "flag_rmw")
        self.assertEqual(classify_insn("add", "$0x1,0x10(%rbx)"), "flag_rmw")
        # stack destination is excluded from flag_rmw (falls to logic for or)
        self.assertEqual(classify_insn("or", "$0x1,(%rsp)"), "logic")
        self.assertEqual(classify_insn("addq", "$0x1,(%rsp)"), "arith")

    def test_stack_mov(self):
        self.assertEqual(classify_insn("mov", "%rdi,-0x38(%rsp)"), "stk_st")
        self.assertEqual(classify_insn("movq", "$0x0,0x8(%rbp)"), "stk_st")
        self.assertEqual(classify_insn("mov", "-0x38(%rsp),%rdi"), "stk_ld")
        self.assertEqual(classify_insn("movzbl", "0x1(%rbp),%eax"), "stk_ld")

    def test_heap_mov(self):
        self.assertEqual(classify_insn("mov", "%r9b,0xd76b0(%rcx)"), "heap_st")
        self.assertEqual(classify_insn("movl", "%eax,(%rdx)"), "heap_st")
        self.assertEqual(classify_insn("movzbl", "0xc013a(%rax),%edx"), "heap_ld")
        self.assertEqual(classify_insn("mov", "0x7c24fa9(%rip),%rax"), "heap_ld")
        self.assertEqual(classify_insn("movswl", "(%r14),%eax"), "heap_ld")

    def test_sse(self):
        self.assertEqual(classify_insn("movups", "%xmm0,(%rax)"), "sse")
        self.assertEqual(classify_insn("movdqa", "(%rbx),%xmm1"), "sse")
        self.assertEqual(classify_insn("pxor", "%xmm0,%xmm0"), "sse")
        self.assertEqual(classify_insn("pcmpeqb", "%xmm1,%xmm0"), "sse")
        self.assertEqual(classify_insn("pand", "%xmm2,%xmm3"), "sse")
        self.assertEqual(classify_insn("pshufb", "%xmm0,%xmm1"), "sse")
        self.assertEqual(classify_insn("movd", "%xmm0,%eax"), "sse")
        self.assertEqual(classify_insn("movq", "%xmm0,%rax"), "sse")
        self.assertEqual(classify_insn("vaesenc", "%ymm0,%ymm1,%ymm2"), "sse")
        self.assertEqual(classify_insn("addsd", "%xmm0,%xmm1"), "sse")
        # push/pop/pause must not be caught by the p-prefix rule
        self.assertEqual(classify_insn("push", "%rbp"), "misc")
        self.assertEqual(classify_insn("pop", "%rbp"), "misc")
        self.assertEqual(classify_insn("pause", ""), "misc")
        # plain movq reg-reg is not sse
        self.assertEqual(classify_insn("movq", "%rax,%rdx"), "mov_rr")

    def test_branch_cmov_setcc_cmp(self):
        self.assertEqual(classify_insn("je", "2000"), "branch")
        self.assertEqual(classify_insn("jmp", "*%rax"), "branch")
        self.assertEqual(classify_insn("jrcxz", "100f"), "branch")
        self.assertEqual(classify_insn("cmove", "%esi,%r9d"), "cmov")
        self.assertEqual(classify_insn("cmovne", "%r8d,%r9d"), "cmov")
        self.assertEqual(classify_insn("sete", "%al"), "setcc")
        self.assertEqual(classify_insn("setne", "%cl"), "setcc")
        self.assertEqual(classify_insn("cmpb", "$0x0,0xd76ae(%rcx)"), "cmp")
        self.assertEqual(classify_insn("cmp", "%rax,%rbx"), "cmp")
        self.assertEqual(classify_insn("test", "%r9b,%r9b"), "cmp")

    def test_shift_logic_call_lea(self):
        self.assertEqual(classify_insn("shlq", "$0x3,%rax"), "shift")
        self.assertEqual(classify_insn("shrb", "%cl,%al"), "shift")
        self.assertEqual(classify_insn("shrd", "%rax,%rbx"), "shift")
        self.assertEqual(classify_insn("ror", "$0x1,%eax"), "shift")
        self.assertEqual(classify_insn("xor", "%eax,%eax"), "logic")
        self.assertEqual(classify_insn("or", "%rbx,%rcx"), "logic")
        self.assertEqual(classify_insn("not", "%rax"), "logic")
        self.assertEqual(classify_insn("call", "1000"), "call")
        self.assertEqual(classify_insn("callq", "*%rax"), "call")
        self.assertEqual(classify_insn("lea", "0x1(%rax),%rdx"), "lea")
        self.assertEqual(classify_insn("leaq", "(%rax,%rax,2),%rdx"), "lea")

    def test_mov_rr_and_arith(self):
        self.assertEqual(classify_insn("mov", "%edx,%r9d"), "mov_rr")
        self.assertEqual(classify_insn("movl", "%eax,%ecx"), "mov_rr")
        self.assertEqual(classify_insn("movq", "%r14,%r15"), "mov_rr")
        # immediate->register mov is not mov_rr per the pre-registered rule
        self.assertEqual(classify_insn("mov", "$0x1,%eax"), "misc")
        self.assertEqual(classify_insn("add", "$0x8,%rsp"), "arith")
        self.assertEqual(classify_insn("sub", "%rax,%rbx"), "arith")
        self.assertEqual(classify_insn("imul", "%rax,%rbx"), "arith")
        self.assertEqual(classify_insn("inc", "%eax"), "arith")
        self.assertEqual(classify_insn("neg", "%rax"), "arith")

    def test_misc(self):
        self.assertEqual(classify_insn("nop", ""), "misc")
        self.assertEqual(classify_insn("nopl", "0x0(%rax)"), "misc")
        self.assertEqual(classify_insn("ret", ""), "misc")
        self.assertEqual(classify_insn("leave", ""), "misc")
        self.assertEqual(classify_insn("endbr64", ""), "misc")
        self.assertEqual(classify_insn("movzbl", "%al,%edx"), "misc")
        self.assertEqual(classify_insn("xchg", "%rax,%rbx"), "misc")

    def test_class_list_is_preregistered(self):
        self.assertEqual(CLASSES,
                         ["mask_and", "flag_rmw", "stk_st", "stk_ld", "heap_st",
                          "heap_ld", "sse", "branch", "cmov", "setcc", "cmp",
                          "shift", "logic", "call", "lea", "mov_rr", "arith",
                          "misc"])


class TestParseDisasm(unittest.TestCase):
    def test_segments_counts_and_lookup(self):
        funcs = parse_disasm(DISASM_TEXT.splitlines())
        self.assertIn("_ZN13GrhSIM_SimTop12cpu_task_480Ev", funcs)
        task = funcs["_ZN13GrhSIM_SimTop12cpu_task_480Ev"]
        self.assertEqual(task["n"], 5)
        self.assertEqual(task["segments"], [[0x1000, 0x1018]])
        helper = funcs["_ZN13GrhSIM_SimTop14cpu_helper_321_0EPSt4byteRh"]
        from grhsim_dyn_iclass_profile import CLS_IDX
        self.assertEqual(helper["counts"][CLS_IDX["flag_rmw"]], 1)
        self.assertEqual(helper["counts"][CLS_IDX["heap_ld"]], 1)
        self.assertEqual(task["counts"][CLS_IDX["mask_and"]], 1)
        self.assertEqual(task["counts"][CLS_IDX["stk_st"]], 1)
        intervals, starts = build_lookup(funcs)
        self.assertEqual(map_address(0x1000, intervals, starts)[0],
                         "_ZN13GrhSIM_SimTop12cpu_task_480Ev")
        self.assertEqual(map_address(0x1018, intervals, starts)[0],
                         "_ZN13GrhSIM_SimTop12cpu_task_480Ev")
        # gap between functions is unmapped
        self.assertIsNone(map_address(0x1019, intervals, starts))
        self.assertEqual(map_address(0x4000, intervals, starts)[0], "malloc@plt")

    def test_same_symbol_segments_merge(self):
        text = (f"0000000000001000 <foo>:\n 1000:{TAB}nop\n\n"
                f"0000000000002000 <foo>:\n 2000:{TAB}ret\n\n")
        funcs = parse_disasm(text.splitlines())
        self.assertEqual(len(funcs), 1)
        self.assertEqual(funcs["foo"]["segments"], [[0x1000, 0x1000], [0x2000, 0x2000]])
        self.assertEqual(funcs["foo"]["n"], 2)
        intervals, starts = build_lookup(funcs)
        self.assertEqual(map_address(0x2000, intervals, starts),
                         ("foo", 1))


class TestPerfParsing(unittest.TestCase):
    def test_parse_perf_script_lines(self):
        text = ("     5fcf8af7fcd8 (/path/to/emu)\n"
                " ffffffffb8a00b90 ([unknown])\n"
                "     702ee080a26a (/usr/lib/x86_64-linux-gnu/libc.so.6)\n"
                "\n")
        samples = parse_perf_script_lines(text.splitlines())
        self.assertEqual(len(samples), 3)
        self.assertEqual(samples[0], (0x5FCF8AF7FCD8, "/path/to/emu"))
        self.assertEqual(samples[1], (0xFFFFFFFFB8A00B90, "[unknown]"))


class TestBucketing(unittest.TestCase):
    def test_symbol_bucket(self):
        self.assertEqual(symbol_bucket("_ZN13GrhSIM_SimTop12cpu_task_480Ev", "x"),
                         ("task", "cpu_task_480"))
        self.assertEqual(
            symbol_bucket("_ZN13GrhSIM_SimTop14cpu_helper_321_0EPSt4byteRh", "x"),
            ("helper", "cpu_helper_321_0"))
        bucket, label = symbol_bucket("_ZN13GrhSIM_SimTop8evaluateEv",
                                      "GrhSIM_SimTop::evaluate()")
        self.assertEqual(bucket, "simtop_other")
        self.assertEqual(label, "simtop::evaluate")
        bucket, _label = symbol_bucket("_ZSt4cout", "std::cout")
        self.assertEqual(bucket, "emu_other")
        bucket, label = symbol_bucket("malloc@plt", "malloc@plt")
        self.assertEqual((bucket, label), ("emu_other", "malloc@plt"))

    def test_dso_bucket(self):
        self.assertEqual(dso_bucket("/usr/lib/x86_64-linux-gnu/libc.so.6"), "dso:libc")
        self.assertEqual(
            dso_bucket("/repo/testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so"),
            "dso:nemu")
        self.assertEqual(dso_bucket("[unknown]"), "unknown")
        self.assertEqual(dso_bucket("[vdso]"), "dso:vdso")
        self.assertEqual(dso_bucket("/usr/lib/x86_64-linux-gnu/libstdc++.so.6.0.33"),
                         "dso:libstdc++")

    def test_demangle_batch(self):
        names = ["_ZN13GrhSIM_SimTop8evaluateEv", "malloc@plt"]
        dem = demangle_batch(names)
        self.assertEqual(dem[names[0]], "GrhSIM_SimTop::evaluate()")
        self.assertEqual(dem[names[1]], "malloc@plt")


class TestOffset(unittest.TestCase):
    def build_shifted(self, shift_pages):
        funcs = parse_disasm(DISASM_TEXT.splitlines())
        intervals, starts = build_lookup(funcs)
        shift = shift_pages << 12
        samples = []
        for func in funcs.values():
            for addrs in func["addrs"]:
                for addr in addrs:
                    samples.extend([addr + shift] * 3)
        return funcs, intervals, starts, samples, shift

    def test_estimate_zero_offset(self):
        funcs, _iv, _st, samples, _shift = self.build_shifted(0)
        offset, _diag = estimate_offset(samples, funcs)
        self.assertEqual(offset, 0)
        self.assertGreaterEqual(interval_coverage(samples, *build_lookup(funcs), 0), 0.99)

    def test_estimate_shifted_offset(self):
        funcs, _iv, _st, samples, shift = self.build_shifted(0x40000)
        offset, diag = estimate_offset(samples, funcs)
        self.assertEqual(offset, shift)
        self.assertEqual(diag["exact_hits_at_chosen"], len(set(samples)))

    def test_empty_samples(self):
        offset, _diag = estimate_offset([], parse_disasm(DISASM_TEXT.splitlines()))
        self.assertEqual(offset, 0)


class TestAggregate(unittest.TestCase):
    def build(self):
        funcs = parse_disasm(DISASM_TEXT.splitlines())
        intervals, starts = build_lookup(funcs)
        labels = {name: symbol_bucket(name, name) for name in funcs}
        return funcs, intervals, starts, labels

    def test_aggregate_buckets_and_classes(self):
        funcs, intervals, starts, labels = self.build()
        emu = "/fake/emu"
        samples = [(0x1000, emu), (0x1008, emu), (0x2000, emu), (0x3005, emu),
                   (0x4000, emu), (0x9999, emu),           # gap -> unmapped/misc
                   (0x1234, "/usr/lib/libc.so.6"),
                   (0xFFFF0000, "[unknown]")]
        agg = aggregate_samples(samples, lambda d: d == emu, funcs, intervals,
                                starts, 0, labels)
        self.assertEqual(agg["n_samples"], 8)
        self.assertEqual(agg["n_emu"], 6)
        self.assertEqual(agg["n_emu_mapped"], 5)
        self.assertEqual(agg["unmapped"], 1)
        self.assertEqual(agg["buckets"]["task"], 2)
        self.assertEqual(agg["buckets"]["helper"], 1)
        self.assertEqual(agg["buckets"]["simtop_other"], 1)
        self.assertEqual(agg["buckets"]["emu_other"], 1)
        self.assertEqual(agg["buckets"]["dso:libc"], 1)
        self.assertEqual(agg["buckets"]["unknown"], 2)     # [unknown] + gap
        self.assertEqual(agg["classes"]["heap_ld"], 1)     # movzbl 0x70f(%rdi)
        self.assertEqual(agg["classes"]["cmp"], 1)         # test
        self.assertEqual(agg["classes"]["flag_rmw"], 1)    # orb
        self.assertEqual(agg["classes"]["misc"], 2)        # push + gap sample
        self.assertEqual(agg["classes"]["branch"], 1)      # jmp *.. (malloc@plt)
        self.assertEqual(agg["classes_model"]["flag_rmw"], 1)
        self.assertEqual(agg["classes_model"]["misc"], 1)  # push in evaluate (model)

    def test_aggregate_with_offset_and_skid(self):
        funcs, intervals, starts, labels = self.build()
        emu = "/fake/emu"
        shift = 0x100000
        samples = [(0x1000 + shift, emu), (0x1008 + shift, emu)]
        agg = aggregate_samples(samples, lambda d: d == emu, funcs, intervals,
                                starts, shift, labels)
        self.assertEqual(agg["n_emu_mapped"], 2)
        self.assertEqual(agg["classes"]["heap_ld"], 1)
        self.assertEqual(agg["classes"]["cmp"], 1)
        # sample at 0x1008 has predecessor 0x1000 (heap_ld) with a different class
        self.assertEqual(agg["skid_checked"], 1)
        self.assertEqual(agg["skid_diff"], 1)

    def test_merge_runs(self):
        funcs, intervals, starts, labels = self.build()
        emu = "/fake/emu"
        a = aggregate_samples([(0x1000, emu)], lambda d: d == emu, funcs,
                              intervals, starts, 0, labels)
        b = aggregate_samples([(0x1000, emu), (0x1234, "/lib/libc.so.6")],
                              lambda d: d == emu, funcs, intervals, starts, 0, labels)
        merged = merge_runs([a, b])
        self.assertEqual(merged["n_samples"], 3)
        self.assertEqual(merged["classes"]["heap_ld"], 2)
        self.assertEqual(merged["buckets"]["dso:libc"], 1)


class TestGatesAndMetrics(unittest.TestCase):
    def test_g2_pass_and_fail(self):
        totals = [10000, 10000, 10000]
        ok_counts = [dict.fromkeys(CLASSES, 0) for _ in range(3)]
        for i, counts in enumerate(ok_counts):
            counts["branch"] = 2000 + i          # ~20%, tiny differences
            counts["cmp"] = 500
        ok, rows = gate_g2([dict(c) for c in ok_counts], totals)
        self.assertTrue(ok)
        classes = [row[0] for row in rows]
        self.assertEqual(classes, ["branch", "cmp"])  # both >= 1% merged share
        bad = [dict.fromkeys(CLASSES, 0) for _ in range(3)]
        bad[0]["branch"], bad[1]["branch"], bad[2]["branch"] = 2000, 3000, 2000
        ok, rows = gate_g2(bad, totals)
        self.assertFalse(ok)

    def test_g2_sd_pass_and_fail(self):
        totals = [10000] * 5
        ok_counts = [dict.fromkeys(CLASSES, 0) for _ in range(5)]
        for i, counts in enumerate(ok_counts):
            counts["branch"] = 2000 + i          # ~20%, SD far below 0.5pp
            counts["cmp"] = 500
        ok, rows = gate_g2_sd(ok_counts, totals)
        self.assertTrue(ok)
        by_cls = {row[0]: row for row in rows}
        self.assertEqual(set(by_cls), {"branch", "cmp"})
        bad = [dict.fromkeys(CLASSES, 0) for _ in range(5)]
        for i, counts in enumerate(bad):
            counts["branch"] = 2000 + 200 * i    # 20%..28%, SD ~3.2pp
        ok, rows = gate_g2_sd(bad, totals)
        self.assertFalse(ok)
        self.assertFalse({row[0]: row for row in rows}["branch"][4])

    def test_load_phase_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv = Path(tmp) / "phase.csv"
            csv.write_text("run,eval_ns,compute_ns,commit_ns,publish_ns,host_ms\n"
                           "perfA,100000000,80000000,10000000,5000000,100\n")
            rows = load_phase_ref(csv)
            self.assertEqual(len(rows), 1)
            # (80+10+5)e6 ns / (100 ms x 1e6 ns/ms) = 0.95
            self.assertAlmostEqual(rows[0]["model_wall_share"], 0.95)

    def test_bootstrap_ci_deterministic(self):
        counts = {cls: 0 for cls in CLASSES}
        counts.update({"branch": 5000, "cmp": 3000, "misc": 2000})
        first = bootstrap_ci(counts, iters=200, seed=20260926)
        second = bootstrap_ci(counts, iters=200, seed=20260926)
        self.assertEqual(first, second)
        lo, hi = first["branch"]
        self.assertLess(lo, 0.5)
        self.assertGreater(hi, 0.5)

    def test_coldbias_table(self):
        static = {7: [0] * len(CLASSES)}
        static[7][CLASSES.index("flag_rmw")] = 4
        static[7][CLASSES.index("cmp")] = 2
        fires = {7: 1000}
        share_all = {"flag_rmw": 0.001, "cmp": 0.0}
        table = coldbias_table(static, fires, share_all, cycles=100,
                               instr_per_cycle=1_000_000.0)
        row = table["flag_rmw"]
        self.assertAlmostEqual(row["closed_form_per_cycle"], 40.0)   # 1000*4/100
        self.assertAlmostEqual(row["sampled_per_cycle"], 1000.0)     # 0.001*1e6
        self.assertAlmostEqual(row["ratio"], 0.04)
        self.assertIsNone(table["cmp"]["ratio"])                     # zero denominator

    def test_build_static_per_task_helper_merge(self):
        funcs = parse_disasm(DISASM_TEXT.splitlines())
        static, orphans = build_static_per_task(funcs, {321: 480})
        self.assertEqual(orphans, [])
        from grhsim_dyn_iclass_profile import CLS_IDX
        self.assertEqual(static[480][CLS_IDX["flag_rmw"]], 1)        # helper merged
        self.assertEqual(static[480][CLS_IDX["mask_and"]], 1)
        static2, orphans2 = build_static_per_task(funcs, {})
        self.assertEqual(orphans2, ["_ZN13GrhSIM_SimTop14cpu_helper_321_0EPSt4byteRh"])
        self.assertEqual(static2[480][CLS_IDX["flag_rmw"]], 0)


class TestEndToEnd(unittest.TestCase):
    def build_inputs(self, tmp):
        disasm = Path(tmp) / "disasm.txt"
        disasm.write_text(DISASM_TEXT)
        emu = "/fake/emu"
        perf_text = "".join(
            f"     {addr:x} ({emu})\n"
            for addr in (0x1000, 0x1008, 0x100b, 0x1011, 0x1018, 0x2000, 0x200a,
                         0x3000, 0x3005, 0x4000) * 30)
        perf_text += f"     9abc (/usr/lib/libc.so.6)\n"
        return str(disasm), [("run1", perf_text), ("run2", perf_text),
                             ("run3", perf_text)], emu

    def test_run_analysis_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            disasm, perf_texts, emu = self.build_inputs(tmp)
            out1 = Path(tmp) / "out1"
            out2 = Path(tmp) / "out2"
            s1 = run_analysis(disasm, perf_texts, emu, out1, bootstrap_iters=200)
            s2 = run_analysis(disasm, perf_texts, emu, out2, bootstrap_iters=200)
            self.assertEqual((out1 / "summary.json").read_bytes(),
                             (out2 / "summary.json").read_bytes())
            self.assertEqual((out1 / "summary.md").read_bytes(),
                             (out2 / "summary.md").read_bytes())
            self.assertEqual((out1 / "iclass_per_run.tsv").read_bytes(),
                             (out2 / "iclass_per_run.tsv").read_bytes())
            self.assertEqual(s1["merged"]["n_samples"], 903)
            self.assertEqual(s1["merged"]["coverage"], 1.0)
            self.assertEqual(s1["config"]["offsets"],
                             {"run1": 0, "run2": 0, "run3": 0})
            classes = s1["runs"][0]["classes"]
            self.assertEqual(classes["heap_ld"], 60)
            self.assertEqual(classes["branch"], 60)      # je + jmp@plt
            gates = s1["gates"]
            self.assertIn("g1_model_samples", gates)
            self.assertIn("g4_flag_rmw_anchor", gates)
            # tsv has 18 classes + total per run
            tsv_lines = (out1 / "iclass_per_run.tsv").read_text().splitlines()
            self.assertEqual(len(tsv_lines), 1 + 3 * (len(CLASSES) + 1))
            parsed = json.loads((out1 / "summary.json").read_text())
            self.assertEqual(parsed["merged"]["n_samples"], 903)
    def test_run_analysis_per_run_aslr_offsets(self):
        # each perf run is a separate process with its own load bias
        with tempfile.TemporaryDirectory() as tmp:
            disasm, perf_texts, emu = self.build_inputs(tmp)
            shift = 0x40000 << 12
            shifted = []
            for line in perf_texts[1][1].splitlines():
                if f"({emu})" in line:
                    ip = int(line.split()[0], 16) + shift
                    shifted.append(f"     {ip:x} ({emu})")
                else:
                    shifted.append(line)
            perf_texts[1] = ("run2", "\n".join(shifted) + "\n")
            summary = run_analysis(disasm, perf_texts, emu, Path(tmp) / "out",
                                   bootstrap_iters=50)
            self.assertEqual(summary["config"]["offsets"],
                             {"run1": 0, "run2": shift, "run3": 0})
            self.assertEqual(summary["merged"]["coverage"], 1.0)
            self.assertEqual(summary["runs"][1]["classes"]["heap_ld"], 60)

    def test_run_analysis_phase_gate(self):
        # Amended G3: sample model share (task+helper+simtop_other) vs the
        # same-build phase-timing model wall share from --phase-csv.
        with tempfile.TemporaryDirectory() as tmp:
            disasm, perf_texts, emu = self.build_inputs(tmp)
            model_share = 270 / 301      # task 150 + helper 60 + simtop 60 of 301
            csv = Path(tmp) / "phase.csv"
            csv.write_text(
                "run,eval_ns,compute_ns,commit_ns,publish_ns,host_ms\n"
                "perfA,100000000,80000000,9000000,701000,100\n")
            self.assertAlmostEqual(89701000 / 1e8, model_share, places=5)
            s = run_analysis(disasm, perf_texts, emu, Path(tmp) / "out",
                             bootstrap_iters=50, phase_path=csv)
            self.assertTrue(s["gates"]["g3_closure"])
            self.assertIn("g3_closure_orig", s["informational"])
            self.assertIn("g2_consistency_orig", s["informational"])
            self.assertIn("g4_flag_rmw_anchor_orig", s["informational"])
            floor = G4_ANCHOR_ARMS * G4_F_MEM * G4_GUARD_ALLOWANCE
            self.assertLess(floor, 100_000.0)
            self.assertEqual(s["gate_details"]["g4_flag_rmw_anchor"][1],
                             [floor, G4_CEILING])
            # a phase reference far off the sample share fails the gate
            csv.write_text(
                "run,eval_ns,compute_ns,commit_ns,publish_ns,host_ms\n"
                "perfA,100000000,80000000,9000000,701000,80\n")
            s_bad = run_analysis(disasm, perf_texts, emu, Path(tmp) / "outb",
                                 bootstrap_iters=50, phase_path=csv)
            self.assertFalse(s_bad["gates"]["g3_closure"])
            # without a phase reference the amended gate fails closed
            s_none = run_analysis(disasm, perf_texts, emu, Path(tmp) / "out2",
                                  bootstrap_iters=50)
            self.assertFalse(s_none["gates"]["g3_closure"])


if __name__ == "__main__":
    unittest.main()
