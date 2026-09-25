#!/usr/bin/env python3
"""NO00015 static+dynamic census: edge-completion de-monitoring candidates.

Mechanism (edge completion, "M2"). A monitored boundary value v (compute
fanout row with activate targets) has producer op X (pure core.compute.*,
single result) in unit A. NO00014 dropped v's fanout row only when every
consumer unit B was *already* activated by every non-constant operand w of
X. This census prices the complementary class: B misses some operand edges,
but each missing edge (B,w) can be *added* -- w is itself a monitored
boundary value whose fanout row already activates A (X's unit, required for
freshness), so extending activate(fanout(w)) with B is well-defined.

Safety (static, dependency-driven; identical freshness proof to NO00014):
after adding edge w->B, any change of w fires A (existing edge, X
re-evaluates) and B in the same round; topological order A < B (B consumes
v) guarantees B reads the fresh v. If X(w) evaluates to the same value, B
fires redundantly; B is required side-effect free (core.compute.* /
core.state.read / core.state.memRead only), so the extra fire is
unobservable. The new edge respects the existing unit order (producer(w) <
A < B), so the activation graph stays acyclic. v's fanout row is deleted
only when EVERY consumer B is covered after completion; write/store of v
remains.

Selection (dynamic profit, performance-only -- never safety):
  save   = wr_v * (K_DETECT + K_STORE)        (detection + boundary store)
  widen  = sum over added edges (B,w):
           ch_w * (ops_B * K_OP + K_SET)      (extra B fires, upper bound;
           co-activation of several new edges in one round collapses)
  profit = save - widen; select profit > 0.
ch_w comes from the dyn run vchg profile of the *same* workload that the
measurement uses, so the estimate does not generalize across inputs.

Hard requirements per candidate (all static):
  - v: Boundary storage, 1..64b two-state logic, not pinned, not event-gate,
    not port-arm (regWrite/latchWrite first-three-operand superset).
  - X: core.compute.* single result, no objectRefs, not constant, not expr;
    owned by supernode A; A not among v's targets.
  - fanout(v): arm list empty; every target B is a supernode whose ops are
    side-effect free.
  - every non-constant operand w of X: boundary, has a live fanout activate
    row (not de-monitored), A in activate(fanout(w)), not pinned, not an
    event-gate value. (Internal / unmonitored operands cannot propagate
    v-might-change to B once v's row is gone -- same multi-hop trap that
    NO00014 proved unsafe -- so they are rejected outright.)
  - completion sources must have a runtime-live, profiled row: an
    emit-aliased core.state.read result (planReadAliases: projected state,
    no non-compute/event consumer, type match) is rejected as a missing-edge
    source because its schedule row is dead code (the added edge would never
    fire; vchg is also blind to it), and a core.dpi.call result is rejected
    because the profile has no counters at the DPI publish site (widen would
    be unpriced).
  - cascade fixpoint (greatest): non-constant operands of selected values
    must not themselves be selected (their rows must survive).

Inputs
  --model      production mapped checkpoint JSON (NO00014 flow)
  --run        NO00014 dyn run log ([grhsim-vchg] + [grhsim-dyn] rows)
  --output     directory for summary.md / summary.json
  --cycles     guest cycles (default 100001)
"""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grhsim_demonitor_census import (  # noqa: E402
    CONSTANT_KIND, EXPR_KIND, COMPUTE_PREFIX, KIND_SUPER,
    load_model, parse_run, side_effect_free)
from grhsim_vchg_profile import coldness_bucket, width_bucket  # noqa: E402

K_DETECT = 3
K_STORE = 1
K_SET = 1
K_OP = 3.25  # current compute instr/dynOp (3.19-3.23M / ~995K, NO00013/14 era)
# Exact integer-scaled (x4) pricing: K_OP = 13/4, K_SET = 4/4, save = wr*16/4.
# The profit>0 selection is computed on integers so the C++ pass reproduces
# the identical set bit-for-bit (float summation order would differ).
K_OP_X4 = 13
K_SET_X4 = 4
SAVE_X4 = 16


def candidates(view):
    """Static eligibility + missing-edge pricing inputs. Returns
    (cands, rejections) where each cand row carries the missing-edge map
    {unit_B: [w, ...]} (only units with at least one missing edge)."""
    cands, rejections = [], Counter()
    activate = view["fanout_activate"]
    for vid in sorted(view["is_boundary"]):
        width = view["width"].get(vid, 0)
        if width < 1 or width > 64:
            rejections["width"] += 1
            continue
        if vid in view["pinned"]:
            rejections["pinned"] += 1
            continue
        if vid in view["event_gate_values"]:
            rejections["event_gate"] += 1
            continue
        if vid in view["port_arm_values"]:
            rejections["port_arm"] += 1
            continue
        xop = view["producer_of"].get(vid, 0)
        if not xop:
            rejections["no_producer"] += 1
            continue
        kind = view["op_name"].get(xop, "")
        if not kind.startswith(COMPUTE_PREFIX) or kind in (CONSTANT_KIND, EXPR_KIND):
            rejections["producer_kind"] += 1
            continue
        unit_a = view["unit_of_op"].get(xop, 0)
        if not unit_a:
            rejections["producer_not_in_unit"] += 1
            continue
        if view["op_has_refs"].get(xop, True) or len(view["op_results"].get(xop, ())) != 1:
            rejections["refs_or_results"] += 1
            continue
        targets = view["fanout_activate"].get(vid)
        if not targets:
            rejections["no_fanout_row"] += 1
            continue
        if view["fanout_arm"].get(vid):
            rejections["arm_non_empty"] += 1
            continue
        parts = view["partitions"]
        if any(parts[t][2] != KIND_SUPER for t in targets):
            rejections["non_super_target"] += 1
            continue
        if unit_a in targets:
            rejections["self_target"] += 1
            continue
        if any(not side_effect_free(view, t) for t in targets):
            rejections["side_effect_unit"] += 1
            continue
        operands = []
        bad = None
        for w in view["op_operands"].get(xop, ()):
            prod = view["producer_of"].get(w, 0)
            if prod and view["op_name"].get(prod, "") == CONSTANT_KIND:
                continue
            if w not in view["is_boundary"]:
                bad = "operand_not_boundary"
                break
            if w in view["pinned"]:
                bad = "edge_pinned"
                break
            if w in view["event_gate_values"]:
                bad = "edge_event_gate"
                break
            row = activate.get(w)
            if not row:
                bad = "edge_row_missing"
                break
            if unit_a not in row:
                bad = "producer_not_activated"
                break
            operands.append(w)
        if bad:
            rejections[bad] += 1
            continue
        missing = {}
        blocked = None
        for unit in targets:
            lack = [w for w in operands if unit not in activate.get(w, ())]
            # A completion edge is only as good as the runtime row that
            # carries it: emit-aliased state reads have dead rows (the added
            # edge would never fire) and DPI results are change-blind in the
            # vchg profile (unpriceable widen). Reject the candidate.
            for w in lack:
                if w in view["aliased_read_values"]:
                    blocked = "operand_aliased"
                    break
                if w in view["dpi_produced"]:
                    blocked = "operand_dpi_blind"
                    break
            if blocked:
                break
            if lack:
                missing[unit] = lack
        if blocked:
            rejections[blocked] += 1
            continue
        if not missing:
            # Full cover without any added edge: NO00014 should have taken
            # these; keep as a sanity bucket (expected ~0).
            rejections["already_covered"] += 1
            continue
        cands.append({"v": vid, "op": xop, "kind": kind, "unit_a": unit_a,
                      "width": width, "targets": sorted(targets),
                      "missing": {str(u): ws for u, ws in missing.items()},
                      "operands": operands})
    return cands, rejections


def fixpoint(view, cands):
    by_v = {c["v"]: c for c in cands}
    surviving = set(by_v)
    while True:
        drop = set()
        for vid in surviving:
            for w in by_v[vid]["operands"]:
                if w in surviving:
                    drop.add(vid)
                    break
        if not drop:
            return [by_v[v] for v in sorted(surviving)]
        surviving -= drop


def price(view, cands, vchg):
    """Annotate every candidate with wr/ch/save/widen/profit (+ integer-scaled
    profit_x4 used for the selection decision) from the vchg profile."""
    ops_of = {u: len(ops) for u, ops in view["unit_ops"].items()}
    for c in cands:
        wr, ch = vchg.get(c["v"], (0, 0))
        widen = 0.0
        widen_x4 = 0
        cold_edges = 0
        for u, ws in c["missing"].items():
            ops_b = ops_of.get(int(u), 0)
            for w in ws:
                w_wr, w_ch = vchg.get(w, (0, 0))
                widen += w_ch * (ops_b * K_OP + K_SET)
                widen_x4 += w_ch * (ops_b * K_OP_X4 + K_SET_X4)
                if w_ch == 0:
                    cold_edges += 1
        c["wr"], c["ch"] = wr, ch
        c["save"] = wr * (K_DETECT + K_STORE)
        c["widen"], c["widen_x4"] = widen, widen_x4
        c["profit"] = c["save"] - widen
        c["profit_x4"] = wr * SAVE_X4 - widen_x4
        c["cold_edges"] = cold_edges
    return cands


def select(view, vchg):
    """Authoritative selection: eligibility, integer pricing (profit>0), then
    the cascade fixpoint over the profitable set (a selected value's
    non-constant operands must keep their rows). Mirrors the C++ pass."""
    cands, _ = candidates(view)
    price(view, cands, vchg)
    return fixpoint(view, [c for c in cands if c["profit_x4"] > 0])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile-output", type=Path,
                        help="write the flat vchg profile consumed by the "
                             "grhsim.demonitor-edge-completion pass")
    parser.add_argument("--cycles", type=int, default=100001)
    args = parser.parse_args(argv)

    view = load_model(args.model)
    cands, rejections = candidates(view)

    monitored = sum(1 for v in view["is_boundary"] if view["fanout_activate"].get(v))
    n_edges = sum(len(ws) for c in cands for ws in c["missing"].values())
    out = {"boundary": len(view["is_boundary"]), "monitored_rows": monitored,
           "candidates": len(cands),
           "added_edges": n_edges,
           "rejections": dict(rejections),
           "by_kind": dict(Counter(c["kind"] for c in cands))}
    lines = ["# NO00015 edge-completion census", "",
             f"boundary values: {out['boundary']}",
             f"monitored (fanout row with activate targets): {monitored}",
             f"candidates (completion feasible): {out['candidates']}",
             f"added edges: {out['added_edges']}",
             "", "## rejections"]
    lines += [f"- {k}: {v}" for k, v in sorted(rejections.items())]
    lines += ["", "## candidates by kind"]
    lines += [f"- {k}: {v}" for k, v in sorted(out["by_kind"].items(), key=lambda kv: -kv[1])]

    if args.run:
        vchg, _body = parse_run(args.run.read_text(errors="replace"))
        total_wr = sum(w for w, _ in vchg.values())
        sel, tot_save, tot_widen = [], 0, 0.0
        all_save, all_widen = 0, 0.0
        rej_save, rej_widen, rej_n = 0, 0.0, 0
        price(view, cands, vchg)
        for c in cands:
            all_save += c["save"]
            all_widen += c["widen"]
            if c["profit_x4"] > 0:
                sel.append(c)
            else:
                rej_n += 1
                rej_save += c["save"]
                rej_widen += c["widen"]
        # Safety fixpoint over the SELECTED set (not the eligible set): a
        # selected value's non-constant operands must keep their rows, so any
        # selected operand drops the dependent. Eligible-but-unselected
        # operands keep their rows and stay valid completion sources.
        pre_fixpoint = len(sel)
        sel = fixpoint(view, sel)
        agg = defaultdict(lambda: {"n": 0, "save": 0, "widen": 0.0, "profit": 0.0})
        for c in sel:
            tot_save += c["save"]
            tot_widen += c["widen"]
            key = (c["kind"], width_bucket(c["width"]),
                   coldness_bucket(c["ch"] / c["wr"] if c["wr"] else 0.0))
            a = agg[key]
            a["n"] += 1
            a["save"] += c["save"]
            a["widen"] += c["widen"]
            a["profit"] += c["profit"]
        tot_profit = tot_save - tot_widen
        cyc = args.cycles
        out["total_wr_pc"] = total_wr / cyc
        out["all_save_instr_pc"] = all_save / cyc
        out["all_widen_instr_pc"] = all_widen / cyc
        out["all_profit_instr_pc"] = (all_save - all_widen) / cyc
        out["rejected_n"] = rej_n
        out["rejected_save_instr_pc"] = rej_save / cyc
        out["rejected_widen_instr_pc"] = rej_widen / cyc
        out["rejected_profit_instr_pc"] = (rej_save - rej_widen) / cyc
        out["selected_pre_fixpoint"] = pre_fixpoint
        out["cascade_trimmed"] = pre_fixpoint - len(sel)
        out["selected"] = len(sel)
        out["selected_edges"] = sum(len(ws) for c in sel for ws in c["missing"].values())
        out["selected_cold_edges"] = sum(c["cold_edges"] for c in sel)
        out["save_wr_pc"] = tot_save / (K_DETECT + K_STORE) / cyc
        out["save_instr_pc"] = tot_save / cyc
        out["widen_instr_pc"] = tot_widen / cyc
        out["profit_instr_pc"] = tot_profit / cyc
        lines += ["", "## dynamic profit (estimate, K_OP=%.2f)" % K_OP,
                  f"- all candidates (static-only selection): save "
                  f"{out['all_save_instr_pc']:,.1f} widen {out['all_widen_instr_pc']:,.1f} "
                  f"profit {out['all_profit_instr_pc']:,.1f} instr/cycle",
                  f"- rejected by profit<=0: {out['rejected_n']} values, save "
                  f"{out['rejected_save_instr_pc']:,.1f} widen {out['rejected_widen_instr_pc']:,.1f} "
                  f"profit {out['rejected_profit_instr_pc']:,.1f} instr/cycle",
                  f"- selected (profit>0): {out['selected']} values "
                  f"(pre-fixpoint {out['selected_pre_fixpoint']}, cascade "
                  f"fixpoint trimmed {out['cascade_trimmed']}), "
                  f"{out['selected_edges']} added edges "
                  f"({out['selected_cold_edges']} with ch_w=0)",
                  f"- detection writes removed: {out['save_wr_pc']:,.1f}/cycle",
                  f"- save: {out['save_instr_pc']:,.1f} instr/cycle",
                  f"- widen (upper bound): {out['widen_instr_pc']:,.1f} instr/cycle",
                  f"- **profit: {out['profit_instr_pc']:,.1f} instr/cycle**"]
        top = sorted(agg.items(), key=lambda kv: -kv[1]["profit"])[:20]
        out["by_class"] = {str(k): {"n": v["n"], "save_pc": v["save"] / cyc,
                                    "widen_pc": v["widen"] / cyc,
                                    "profit_pc": v["profit"] / cyc}
                           for k, v in top}
        lines += ["", "## top classes by profit/cycle"]
        lines += [f"- {k}: n={v['n']} save={v['save'] / cyc:,.1f} "
                  f"widen={v['widen'] / cyc:,.1f} profit={v['profit'] / cyc:,.1f}"
                  for k, v in top]
        (args.output.mkdir(parents=True, exist_ok=True))
        (args.output / "selected.json").write_text(json.dumps(
            [{"v": c["v"], "kind": c["kind"], "wr": c["wr"], "ch": c["ch"],
              "save": c["save"], "widen": c["widen"], "profit": c["profit"],
              "missing": c["missing"]} for c in sel], indent=0))
        if args.profile_output:
            # Flat profile for the C++ pass: header + "<id> <wr> <ch>" rows.
            # Only values the pass can ever price are needed: candidate values
            # (wr) and their non-constant producer operands (ch).
            needed = set()
            for c in cands:
                needed.add(c["v"])
                needed.update(c["operands"])
            with args.profile_output.open("w") as fh:
                fh.write(f"# grhsim-vchg-profile v1 cycles={args.cycles}\n")
                for vid in sorted(needed):
                    wr, ch = vchg.get(vid, (0, 0))
                    fh.write(f"{vid} {wr} {ch}\n")

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(json.dumps(out, indent=1))
    (args.output / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
