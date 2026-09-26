#!/usr/bin/env python3
"""Unit tests for grhsim_residue_fold_gates (NO00016)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grhsim_residue_fold_gates as gates  # noqa: E402
import grhsim_residue_fold_census as rc  # noqa: E402
import grhsim_demonitor_census as dc  # noqa: E402
from test_grhsim_residue_fold_census import build_model  # noqa: E402


def folded_pair():
    """(old_model, new_model, selected, rewire): new = old with the census
    rewiring applied and the schedule fold field appended."""
    old, _expected = build_model()
    view = dc.view_from_model(old)
    view["operations"] = old["operations"]
    selected, _reject, rewire = rc.select(view, rc.tables_from_model(old))
    new = json.loads(json.dumps(old))
    for row in new["operations"]:
        if row[0] in selected:
            continue
        row[4] = [gates.resolve(rewire, v) if v in rewire else v for v in row[4]]
    new["mappings"][0][-1][4] = new["mappings"][0][-1][4] + [sorted(selected)]
    return old, new, selected, rewire


ENDPOINT_LINES = [
    "[DIFFTEST_INIT] core=0 state=0x0 store_q_addr=0x0 store_qsize=0",
    "EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80000c0c",
    "instrCnt = 240,349, cycleCnt = 99,996",
    "Guest cycle spent: 100,001",
]
SN_LINE_TEXT = "[grhsim-dyn] sn 2 act=3 body=10 grp=2 chg=1"
KIND_LINE_TEXT = "[grhsim-dyn] kind core.compute.add wr=5 ch=4 silent=1"
VCHG_LINE_TEXT = "[grhsim-vchg] v 7 wr=9 ch=8"
TOTALS_LINE_TEXT = "[grhsim-dyn] totals grp_pub=10 grp_fire=9 port_eval=8"


def write_run(path, extra=(), drop=()):
    lines = [SN_LINE_TEXT, KIND_LINE_TEXT, VCHG_LINE_TEXT, TOTALS_LINE_TEXT,
             *ENDPOINT_LINES, *extra]
    lines = [line for line in lines if line not in drop]
    path.write_text("\n".join(lines) + "\n")


class CheckpointClosureTest(unittest.TestCase):
    def test_consistent_pair_passes(self):
        old, new, selected, rewire = folded_pair()
        g = gates.gate_checkpoint_closure(old, new, selected, rewire)
        self.assertTrue(g.ok, g.detail)

    def test_extra_mutation_fails(self):
        old, new, selected, rewire = folded_pair()
        new["operations"][3][4] = [1]  # touch an input.read row's operands
        g = gates.gate_checkpoint_closure(old, new, selected, rewire)
        self.assertFalse(g.ok)

    def test_schedule_prefix_growth_fails(self):
        old, new, selected, rewire = folded_pair()
        new["mappings"][0][-1][4][6] = 1  # inputShadowBytes changed
        g = gates.gate_checkpoint_closure(old, new, selected, rewire)
        self.assertFalse(g.ok)

    def test_fold_set(self):
        old, new, selected, rewire = folded_pair()
        g = gates.gate_fold_set(new, selected, None)
        self.assertTrue(g.ok, g.detail)
        with tempfile.TemporaryDirectory() as tmp:
            recorded = Path(tmp) / "selected.json"
            recorded.write_text(json.dumps({str(k): v for k, v in selected.items()}))
            g = gates.gate_fold_set(new, selected, recorded)
            self.assertTrue(g.ok, g.detail)
            recorded.write_text(json.dumps({"1": "assign_strict"}))
            g = gates.gate_fold_set(new, selected, recorded)
            self.assertFalse(g.ok)

    def _rewired_consumer(self, old, new):
        """First op whose operands changed, with a result and >=1 operand."""
        old_ops = {row[0]: row for row in old["operations"]}
        for row in new["operations"]:
            old_row = old_ops[row[0]]
            if row[4] != old_row[4] and row[5] and row[4]:
                return old_row, row
        raise AssertionError("synthetic model has no rewired consumer")

    def test_fanout_no00014_replay_allowed(self):
        old, new, selected, rewire = folded_pair()
        old_x, new_x = self._rewired_consumer(old, new)
        v = new_x[5][0]
        operand_rows = [[w, [999], []] for w in new_x[4]]
        old["mappings"][0][-1][4][2] = [[v, [999], []]] + operand_rows
        new["mappings"][0][-1][4][2] = operand_rows
        g = gates.gate_checkpoint_closure(old, new, selected, rewire)
        self.assertTrue(g.ok, g.detail)

    def test_fanout_unexplained_drop_fails(self):
        old, new, selected, rewire = folded_pair()
        old_x, new_x = self._rewired_consumer(old, new)
        v = new_x[5][0]
        old["mappings"][0][-1][4][2] = [[v, [999], []]]
        new["mappings"][0][-1][4][2] = []  # operands do not cover target 999
        g = gates.gate_checkpoint_closure(old, new, selected, rewire)
        self.assertFalse(g.ok)

    def test_fanout_growth_rules(self):
        old, new, selected, rewire = folded_pair()
        s = sorted(set(rewire.values()))[0]
        old["mappings"][0][-1][4][2] = [[s, [1], []]]
        new["mappings"][0][-1][4][2] = [[s, [1, 2], []]]
        g = gates.gate_checkpoint_closure(old, new, selected, rewire)
        self.assertTrue(g.ok, g.detail)
        # shrinking activate targets is never allowed
        old, new, selected, rewire = folded_pair()
        old["mappings"][0][-1][4][2] = [[s, [1, 2], []]]
        new["mappings"][0][-1][4][2] = [[s, [1], []]]
        g = gates.gate_checkpoint_closure(old, new, selected, rewire)
        self.assertFalse(g.ok)
        # growth on a source that is not a rewire destination is rejected
        old, new, selected, rewire = folded_pair()
        stranger = max(set(rewire) | set(rewire.values())) + 1000
        old["mappings"][0][-1][4][2] = [[stranger, [1], []]]
        new["mappings"][0][-1][4][2] = [[stranger, [1, 2], []]]
        g = gates.gate_checkpoint_closure(old, new, selected, rewire)
        self.assertFalse(g.ok)


class RunGateTest(unittest.TestCase):
    def test_endpoint_and_counters(self):
        old, new, _selected, _rewire = folded_pair()
        view = dc.view_from_model(old)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "base.log"
            run1 = Path(tmp) / "run1.log"
            run2 = Path(tmp) / "run2.log"
            write_run(base)
            write_run(run1)
            write_run(run2)
            self.assertTrue(gates.gate_endpoint_determinism(base, run2).ok)
            g = gates.gate_counters_projection(base, run1, old, new, view)
            self.assertTrue(g.ok, g.detail)

    def test_endpoint_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            run1 = Path(tmp) / "run1.log"
            write_run(run1, drop={"instrCnt = 240,349, cycleCnt = 99,996"})
            self.assertFalse(gates.gate_endpoint_determinism(run1, None).ok)

    def test_difftest_marker_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            run1 = Path(tmp) / "run1.log"
            write_run(run1, extra={"[DIFFTEST] mismatch at pc = 0x80000c0c"})
            self.assertFalse(gates.gate_endpoint_determinism(run1, None).ok)

    def test_counter_drift_fails(self):
        old, new, _selected, _rewire = folded_pair()
        view = dc.view_from_model(old)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "base.log"
            run1 = Path(tmp) / "run1.log"
            write_run(base)
            write_run(run1, drop={SN_LINE_TEXT})
            self.assertFalse(gates.gate_counters_projection(base, run1, old, new, view).ok)

    def test_dynamic_closed_form(self):
        old, new, selected, _rewire = folded_pair()
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "base.log"
            write_run(run)
            g = gates.gate_dynamic_closed_form(old, new, run, selected,
                                               10 * len(selected), 100001)
            self.assertTrue(g.ok, g.detail)
            g = gates.gate_dynamic_closed_form(old, new, run, selected,
                                               10 * len(selected) + 1, 100001)
            self.assertFalse(g.ok)


class CounterProjectionTest(unittest.TestCase):
    """Gate-2 amendment-3 projection rule: dynamic counter deltas are allowed
    only when they equal, closed-form, the projection of statically dropped
    fanout rows; everything else must be exactly equal."""

    def projection_pair(self):
        """(old, new, view, v, kind, unit): new == old except one fanout row
        for compute-produced value v dropped (NO00014 replay shape)."""
        old, new, _selected, _rewire = folded_pair()
        view = dc.view_from_model(old)
        strings = old["strings"]
        for row in old["operations"]:
            if row[5] and row[0] in view["unit_of_op"]:
                v, kind, unit = row[5][0], strings[row[1] - 1], view["unit_of_op"][row[0]]
                break
        else:
            raise AssertionError("no compute producer in synthetic model")
        old["mappings"][0][-1][4][2] = old["mappings"][0][-1][4][2] + [[v, [999], []]]
        return old, new, view, v, kind, unit

    @staticmethod
    def base_lines(v, kind, unit):
        return [f"[grhsim-dyn] sn {unit} act=3 body=10 grp=2 chg=5",
                f"[grhsim-dyn] kind {kind} wr=100 ch=40 silent=7",
                f"[grhsim-vchg] v {v} wr=9 ch=8",
                "[grhsim-vchg] v 424242 wr=3 ch=2",
                "[grhsim-dyn] totals grp_pub=10 grp_fire=9 port_eval=8"]

    @staticmethod
    def proj_lines(v, kind, unit):
        return [f"[grhsim-dyn] sn {unit} act=3 body=10 grp=2 chg=4",
                f"[grhsim-dyn] kind {kind} wr=91 ch=32 silent=16",
                "[grhsim-vchg] v 424242 wr=3 ch=2",
                "[grhsim-dyn] totals grp_pub=10 grp_fire=8 port_eval=8"]

    def run_gate(self, tmp, old, new, view, base_lines, run1_lines):
        base = Path(tmp) / "base.log"
        run1 = Path(tmp) / "run1.log"
        base.write_text("\n".join(base_lines) + "\n")
        run1.write_text("\n".join(run1_lines) + "\n")
        return gates.gate_counters_projection(base, run1, old, new, view)

    def test_projection_consistent_passes(self):
        old, new, view, v, kind, unit = self.projection_pair()
        with tempfile.TemporaryDirectory() as tmp:
            g = self.run_gate(tmp, old, new, view,
                              self.base_lines(v, kind, unit),
                              self.proj_lines(v, kind, unit))
            self.assertTrue(g.ok, g.detail)

    def test_unexplained_vanish_fails(self):
        # no dropped row in the schedules, but a vchg key vanishes
        old, new, view, v, kind, unit = self.projection_pair()
        new["mappings"][0][-1][4][2] = old["mappings"][0][-1][4][2]
        with tempfile.TemporaryDirectory() as tmp:
            g = self.run_gate(tmp, old, new, view,
                              self.base_lines(v, kind, unit),
                              self.proj_lines(v, kind, unit))
            self.assertFalse(g.ok)

    def test_mirror_mismatch_fails(self):
        old, new, view, v, kind, unit = self.projection_pair()
        lines = self.proj_lines(v, kind, unit)
        lines[1] = f"[grhsim-dyn] kind {kind} wr=90 ch=32 silent=16"  # wr delta 10 != 9
        with tempfile.TemporaryDirectory() as tmp:
            g = self.run_gate(tmp, old, new, view,
                              self.base_lines(v, kind, unit), lines)
            self.assertFalse(g.ok)

    def test_kind_delta_missing_fails(self):
        old, new, view, v, kind, unit = self.projection_pair()
        lines = self.proj_lines(v, kind, unit)
        lines[1] = f"[grhsim-dyn] kind {kind} wr=100 ch=40 silent=7"  # unchanged
        with tempfile.TemporaryDirectory() as tmp:
            g = self.run_gate(tmp, old, new, view,
                              self.base_lines(v, kind, unit), lines)
            self.assertFalse(g.ok)

    def test_sn_chg_increase_fails(self):
        old, new, view, v, kind, unit = self.projection_pair()
        lines = self.proj_lines(v, kind, unit)
        lines[0] = f"[grhsim-dyn] sn {unit} act=3 body=10 grp=2 chg=6"
        with tempfile.TemporaryDirectory() as tmp:
            g = self.run_gate(tmp, old, new, view,
                              self.base_lines(v, kind, unit), lines)
            self.assertFalse(g.ok)

    def test_sn_act_drift_fails(self):
        old, new, view, v, kind, unit = self.projection_pair()
        lines = self.proj_lines(v, kind, unit)
        lines[0] = f"[grhsim-dyn] sn {unit} act=4 body=10 grp=2 chg=4"
        with tempfile.TemporaryDirectory() as tmp:
            g = self.run_gate(tmp, old, new, view,
                              self.base_lines(v, kind, unit), lines)
            self.assertFalse(g.ok)

    def test_sn_outside_producer_unit_fails(self):
        old, new, view, v, kind, unit = self.projection_pair()
        lines = self.proj_lines(v, kind, unit)
        lines.append("[grhsim-dyn] sn 999999 act=1 body=1 grp=1 chg=1")
        base = self.base_lines(v, kind, unit) + [
            "[grhsim-dyn] sn 999999 act=1 body=1 grp=1 chg=2"]
        with tempfile.TemporaryDirectory() as tmp:
            g = self.run_gate(tmp, old, new, view, base, lines)
            self.assertFalse(g.ok)

    def test_grp_fire_mismatch_fails(self):
        old, new, view, v, kind, unit = self.projection_pair()
        lines = self.proj_lines(v, kind, unit)
        lines[3] = "[grhsim-dyn] totals grp_pub=10 grp_fire=7 port_eval=8"
        with tempfile.TemporaryDirectory() as tmp:
            g = self.run_gate(tmp, old, new, view,
                              self.base_lines(v, kind, unit), lines)
            self.assertFalse(g.ok)

    def test_new_vchg_key_fails(self):
        old, new, view, v, kind, unit = self.projection_pair()
        lines = self.proj_lines(v, kind, unit) + ["[grhsim-vchg] v 777 wr=1 ch=1"]
        with tempfile.TemporaryDirectory() as tmp:
            g = self.run_gate(tmp, old, new, view,
                              self.base_lines(v, kind, unit), lines)
            self.assertFalse(g.ok)

    def test_identical_no_dropped_passes(self):
        old, new, view, v, kind, unit = self.projection_pair()
        new["mappings"][0][-1][4][2] = old["mappings"][0][-1][4][2]
        with tempfile.TemporaryDirectory() as tmp:
            g = self.run_gate(tmp, old, new, view,
                              self.base_lines(v, kind, unit),
                              self.base_lines(v, kind, unit))
            self.assertTrue(g.ok, g.detail)


class NeutralAndHdlbitsTest(unittest.TestCase):
    def test_neutral_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a"
            b = Path(tmp) / "b"
            (a / "sub").mkdir(parents=True)
            (b / "sub").mkdir(parents=True)
            (a / "sub" / "x.cpp").write_text("same")
            (b / "sub" / "x.cpp").write_text("same")
            (a / "x.o").write_text("object-a")   # excluded
            (b / "x.o").write_text("object-b")
            self.assertTrue(gates.gate_neutral_identical(a, b).ok)
            (b / "sub" / "x.cpp").write_text("different")
            self.assertFalse(gates.gate_neutral_identical(a, b).ok)

    def test_hdlbits(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "hdlbits.log"
            lines = []
            for dut in range(1, gates.HDLBITS_DUTS + 1):
                tag = f"{dut:03d}"
                lines.append(f"==== Running GrhSIM DUT={tag} ====")
                if tag == gates.HDLBITS_KNOWN_FAILURE:
                    lines.append("grhsim.used-bits: " + gates.DUT105_ERROR)
                else:
                    lines.append(f"[GrhTB] dut_{tag} passed: ok")
            log.write_text("\n".join(lines) + "\n")
            g = gates.gate_hdlbits([log])
            self.assertTrue(g.ok, g.detail)
            # a second unexpected failure breaks the gate
            bad = [line for line in lines if "dut_042 passed" not in line]
            log.write_text("\n".join(bad) + "\n")
            self.assertFalse(gates.gate_hdlbits([log]).ok)

    def test_hdlbits_run_marker(self):
        # the individual run_hdlbits_grhsim target logs "[RUN] DUT=x GRHSIM"
        # instead of the run_all banner; both must count as DUT sightings
        with tempfile.TemporaryDirectory() as tmp:
            log1 = Path(tmp) / "all.log"
            log2 = Path(tmp) / "rest.log"
            lines1, lines2 = [], []
            for dut in range(1, gates.HDLBITS_DUTS + 1):
                tag = f"{dut:03d}"
                target = lines1 if dut <= 105 else lines2
                marker = (f"==== Running GrhSIM DUT={tag} ====" if dut <= 105
                          else f"[RUN] DUT={tag} GRHSIM")
                target.append(marker)
                if tag == gates.HDLBITS_KNOWN_FAILURE:
                    target.append("grhsim.used-bits: " + gates.DUT105_ERROR)
                elif tag == "162":
                    # dut_162's testbench prints "passed all ..." without a colon
                    target.append(f"[GrhTB] dut_{tag} passed all prediction and training scenarios")
                else:
                    target.append(f"[GrhTB] dut_{tag} passed: ok")
            log1.write_text("\n".join(lines1) + "\n")
            log2.write_text("\n".join(lines2) + "\n")
            g = gates.gate_hdlbits([log1, log2])
            self.assertTrue(g.ok, g.detail)


if __name__ == "__main__":
    unittest.main()
