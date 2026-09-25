#!/usr/bin/env python3
"""Unit tests for scripts/grhsim_vchg_profile.py pure functions."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import grhsim_vchg_profile as vp


class ParseTest(unittest.TestCase):
    def test_parse_vchg(self):
        text = ("[grhsim-vchg] v 17 wr=200002 ch=31\n"
                "\x1b[35m[grhsim-vchg] v 3 wr=1 ch=0\x1b[0m\n"
                "[grhsim-dyn] kind core.compute.and wr=5 ch=1 silent=0\n")
        self.assertEqual(vp.parse_vchg(text), {17: (200002, 31), 3: (1, 0)})

    def test_parse_vchg_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            vp.parse_vchg("[grhsim-vchg] v 1 wr=1 ch=0\n[grhsim-vchg] v 1 wr=2 ch=1\n")

    def test_parse_sn(self):
        text = "[grhsim-dyn] sn 42 act=10 body=9 grp=3 chg=1\n"
        self.assertEqual(vp.parse_sn(text), {42: (10, 9, 3, 1)})

    def test_parse_kinds(self):
        text = "[grhsim-dyn] kind core.compute.and wr=100 ch=2 silent=3\n"
        self.assertEqual(vp.parse_kinds(text), {"core.compute.and": (100, 2, 3)})

    def test_parse_endpoint_commas(self):
        text = ("Core 0: EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80000C0C\n"
                "Core-0 instrCnt = 240,349, cycleCnt = 99,996, IPC = 2.403586\n"
                "Seed=0 Guest cycle spent: 100,001 (this will be different)\n"
                "Host time spent: 163,369ms\n")
        ep = vp.parse_endpoint(text)
        self.assertEqual(ep["instrCnt"], 240349)
        self.assertEqual(ep["cycleCnt"], 99996)
        self.assertEqual(ep["guest"], 100001)
        self.assertEqual(ep["pc"], "0x80000c0c")
        self.assertEqual(ep["host_ms"], 163369)

    def test_check_endpoint(self):
        ep = {"instrCnt": 240349, "cycleCnt": 99996, "guest": 100001, "pc": "0x80000c0c"}
        self.assertEqual(vp.check_endpoint(ep, (240349, 99996, 100001, "0x80000c0c")), [])
        self.assertEqual(len(vp.check_endpoint(ep, (1, 99996, 100001, "0x80000c0c"))), 1)
        self.assertEqual(len(vp.check_endpoint({"pc": None}, (1, 2, 3, "0x1"))), 4)


class ClosureTest(unittest.TestCase):
    def test_closure_exact(self):
        vchg = {1: (10, 2), 2: (20, 3)}
        kinds = {"a": (25, 4, 0), "b": (5, 1, 0)}
        clo = vp.closure_check(vchg, kinds)
        self.assertTrue(clo["wr_ok"])
        self.assertTrue(clo["ch_ok"])
        self.assertEqual(clo["sum_wr"], 30)
        self.assertEqual(clo["sum_ch"], 5)

    def test_closure_mismatch(self):
        clo = vp.closure_check({1: (10, 2)}, {"a": (11, 2, 0)})
        self.assertFalse(clo["wr_ok"])
        self.assertTrue(clo["ch_ok"])


class DistStatsTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(vp.dist_stats([])["n"], 0)

    def test_basic(self):
        d = vp.dist_stats([0, 0, 1, 2, 3, 4, 5, 6, 7, 100])
        self.assertEqual(d["n"], 10)
        self.assertEqual(d["total"], 128)
        self.assertAlmostEqual(d["zero_share"], 0.2)
        self.assertEqual(d["p50"], 3)
        self.assertEqual(d["max"], 100)
        self.assertAlmostEqual(d["top10p_share"], 100 / 128)
        self.assertAlmostEqual(d["top1p_share"], 100 / 128)

    def test_all_zero(self):
        d = vp.dist_stats([0, 0, 0])
        self.assertAlmostEqual(d["zero_share"], 1.0)
        self.assertAlmostEqual(d["top1p_share"], 0.0)


class ScanOrderTest(unittest.TestCase):
    def test_eval_task_order(self):
        text = "if(cpu_flags[958])cpu_task_1();\nif(cpu_flags[959])cpu_task_7();\n"
        self.assertEqual(vp.eval_task_order(text), {1: 0, 7: 1})

    def test_unit_scan_order(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "grhsim_SimTop_task_3.cpp").write_text(
                "++cpu_dyn_sn_act[10];\nx;\n++cpu_dyn_sn_act[11];\n")
            (p / "grhsim_SimTop_task_5.cpp").write_text("++cpu_dyn_sn_act[7];\n")
            self.assertEqual(vp.unit_scan_order(p), {10: (3, 0), 11: (3, 1), 7: (5, 0)})

    def test_unit_scan_order_collision(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "grhsim_SimTop_task_3.cpp").write_text("++cpu_dyn_sn_act[10];\n")
            (p / "grhsim_SimTop_task_5.cpp").write_text("++cpu_dyn_sn_act[10];\n")
            with self.assertRaises(ValueError):
                vp.unit_scan_order(p)


class HelperCensusTest(unittest.TestCase):
    def test_counts(self):
        text = ("grhsim_insert_scalar_words(cpu_concat,0,x,3);\n"
                "grhsim_insert_words (cpu_concat,0,y,70);\n"
                "bool c=cpu_bitwise_words_changed<'&'>(a,1,b,1,64,r,1);\n"
                "grhsim_insert_scalar_words2(not_a_helper);\n")
        counts = vp.helper_census_text(text)
        self.assertEqual(counts["grhsim_insert_scalar_words"], 1)
        self.assertEqual(counts["grhsim_insert_words"], 1)
        self.assertEqual(counts["cpu_bitwise_words_changed"], 1)
        self.assertEqual(counts["memcmp"], 0)


class ClassifyTest(unittest.TestCase):
    def test_cons_class(self):
        self.assertEqual(vp.cons_class("core.compute.and"), "compute")
        self.assertEqual(vp.cons_class("core.state.regWrite"), "port")
        self.assertEqual(vp.cons_class("core.state.read"), "read")
        self.assertEqual(vp.cons_class("core.system.task"), "sink")
        self.assertEqual(vp.cons_class("core.input.read"), "other")

    def test_width_bucket(self):
        self.assertEqual(vp.width_bucket(1), "1")
        self.assertEqual(vp.width_bucket(8), "2-8")
        self.assertEqual(vp.width_bucket(32), "9-32")
        self.assertEqual(vp.width_bucket(64), "33-64")
        self.assertEqual(vp.width_bucket(128), ">64")

    def test_coldness_bucket(self):
        self.assertEqual(vp.coldness_bucket(0.0), "0")
        self.assertEqual(vp.coldness_bucket(0.0005), "(0,0.1%)")
        self.assertEqual(vp.coldness_bucket(0.005), "[0.1%,1%)")
        self.assertEqual(vp.coldness_bucket(0.05), "[1%,10%)")
        self.assertEqual(vp.coldness_bucket(0.5), ">=10%")


class EconModelTest(unittest.TestCase):
    def _view(self):
        from types import SimpleNamespace
        view = SimpleNamespace()
        view.boundary = [10, 11, 20, 30, 40]
        view.is_boundary = set(view.boundary)
        view.producer_kind = {10: "core.compute.mux", 11: "core.compute.constant",
                              20: "core.compute.and", 30: "core.compute.and", 40: "core.compute.or"}
        view.producer_unit = {10: 100, 11: 100, 20: 100, 30: 200, 40: 900}
        view.consumer_units = {10: {100}, 11: set(), 20: {300}, 30: set(), 40: set()}
        view.consumer_classes = {10: "c", 11: "-", 20: "c", 30: "-", 40: "-"}
        view.width = {10: 32, 11: 1, 20: 1, 30: 8, 40: 64}
        view.unit_op_count = {100: 50, 300: 80}
        # candidates: value 20 (single compute consumer unit 300, <=64b)
        view.candidate_operands = {20: [10, 11]}  # and(mux_out, const)
        return view

    def test_migration_profit(self):
        view = self._view()
        vchg = {10: (1000, 500), 20: (2000, 0)}  # candidate wr=2000 ch=0; edge w=10 changes 500
        sn = {100: (5, 2000, 0, 0), 300: (5, 100, 0, 0)}
        rows, agg = vp.migration_profit(view, vchg, sn)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        # save = 2000*(3+1)=8000; reeval = body_C(100)*K_EVAL(and)=200
        # widen = ch_10(500)*ops_C(80)*3.86 = 154400; const operand free
        self.assertEqual(r["save"], 8000)
        self.assertEqual(r["reeval"], 200)
        self.assertAlmostEqual(r["widen"], 500 * 80 * 3.86)
        self.assertEqual(r["new_detect"], 0)
        self.assertEqual(r["edges"], 1)
        self.assertLess(r["profit"], 0)
        key = ("core.compute.and", "0")
        self.assertEqual(agg[key]["ops"], 1)
        self.assertEqual(agg[key]["profitable"], 0)

    def test_migration_profit_unmonitored_edge(self):
        view = self._view()
        view.candidate_operands = {20: [30, 11]}  # and(unmonitored_and_out, const)
        vchg = {20: (100, 0)}
        sn = {100: (5, 2000, 0, 0), 200: (5, 700, 0, 0), 300: (5, 100, 0, 0)}
        rows, _ = vp.migration_profit(view, vchg, sn)
        r = rows[0]
        # unmonitored edge w=30 -> new_detect = body_200(700)*3 = 2100
        self.assertEqual(r["new_detect"], 2100)
        self.assertEqual(r["widen"], 0)

    def test_undumped_decomposition(self):
        view = self._view()
        vchg = {10: (5, 1), 20: (7, 0)}  # dumped: 10, 20; undumped: 11, 30, 40
        sn = {100: (5, 2000, 0, 0), 200: (5, 700, 0, 0), 900: (0, 0, 0, 0)}
        d = vp.undumped_decomposition(view, vchg, sn)
        self.assertEqual(d["undumped"], 3)
        self.assertEqual(d["dead"], 1)       # value 40: producer unit 900 body=0
        self.assertEqual(d["nodetect"], 2)   # values 11, 30 evaluated without detection
        self.assertEqual(d["nodetect_body_fires"], 2000 + 700)


if __name__ == "__main__":
    unittest.main()
