#!/usr/bin/env python3
"""NO00019 static+dynamic census: edge-completion boundary-op migration
(profile-priced migration allowing new activation edges).

Mechanism. A monitored boundary value v (live compute fanout row) is produced
by pure-compute op X in compute supernode A, and every consumer of v sits in a
single different compute supernode B that is side-effect free. NO00013
migrated X into B only when every operand of X was already available in B
(producer in B, already a cross-unit input of B, or constant) -- zero new
edges, hence widen == 0. This census prices the complementary class: some
operands w are not yet available in B, but w is a monitored boundary value
with a runtime-live fanout row, so migrating X into B makes B a reader of w
and the rebuilt schedule extends activate(fanout(w)) with B -- the new edge
is created by the migration itself (schedule rebuild from the partition
tree), so no separate edge-adding machinery is needed.

Safety (static; NO00013 five-point equivalence proof + NO00015 edge
freshness rule):
  - init() activates every unit once in flattened topological order, so X's
    initial value reaches B's consumers before they read it.
  - Within a round B fires whenever v could have changed: every non-constant
    operand w of X is either B-local (recomputed inside the same B fire),
    already activates B (live row, B in activate), or is a new edge source --
    a monitored w whose live row gains B on rebuild, so a w-change fires B in
    the same round; producer(w) < A (A reads w) and A < B (B reads v) keep
    the activation graph acyclic, and topological dispatch rewrites w's slot
    before B runs, so X re-evaluates on fresh operands.
  - Extra B fires (w changed but v would not have) are unobservable: B is
    side-effect free (core.compute.* / core.state.read / core.state.memRead).
  - A's firing set can only shrink (X's operands leave A's input set).

Selection (dynamic profit, performance-only -- never safety; integer x4
arithmetic so the C++ pass reproduces the identical set):
  save_x4   = wr_v * 16                       (K_DETECT=3 + K_STORE=1, x4)
  widen_x4  = sum over new edges w: ch_w * ((ops_B+1) * 13 + 4)
              (extra B fires, upper bound; co-activation collapses)
  reeval_x4 = body_B * K_EVAL_X4(kind_X)      (X re-executes in B's
              pre-existing fires; no credit for A-side savings)
  select profit_x4 = save_x4 - widen_x4 - reeval_x4 > 0.
Cascade fixpoint (greatest): a selected value's non-constant operands must
not themselves be selected (a migrated operand loses its boundary row /
becomes unit-local, breaking the dependent's freshness proof).

De-monitor closure exclusion (pipeline-position safety): the pass runs after
grhsim.demonitor-edge-completion, whose stored removal list is re-validated
against the current tree on every schedule rebuild, and whose NO00014
companion rule is silently recomputed. Migrating a value whose fanout row
covers a de-monitored value (as a NO00014 cover source or a NO00015
completion-edge source) would invalidate that re-validation (hard throw) or
silently un-demonitor it; likewise, adding a consumer unit to a row that
carries NO00015 completion edges could make that row newly NO00014-removable
and break the stored list. Candidates are therefore rejected when v itself,
or any of its new-edge sources, is a non-constant producer operand of a
de-monitored value (NO00014 recomputed set + NO00015 stored set).

Inputs
  --model      production mapped checkpoint JSON (NO00015 flow archive)
  --run        NO00015 dyn run log ([grhsim-vchg] + [grhsim-dyn] sn rows)
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
    census as demonitor_census, load_model, parse_run, side_effect_free)
from grhsim_vchg_profile import coldness_bucket, width_bucket  # noqa: E402

KIND_NODE = 4
SCHEDULE_TAIL_EC_REMOVED = 10  # schedule array index of the NO00015 stored
# removal list (positional trailing field; [9] is the demonitorRedundant flag)

K_DETECT = 3
K_STORE = 1
K_SET = 1
K_OP = 3.25  # compute instr/dynOp (NO00013/14/15 constant)
# Integer x4 pricing (C++/Python identical decision): save = wr*16,
# widen edge = ch_w * ((ops_B+1)*13 + 4), reeval = body_B * K_EVAL_X4.
SAVE_X4 = 16
K_OP_X4 = 13
K_SET_X4 = 4
K_EVAL = {"core.compute.mux": 3, "core.compute.and": 2, "core.compute.or": 2,
          "core.compute.xor": 2, "core.compute.not": 2, "core.compute.eq": 2,
          "core.compute.logicNot": 1, "core.compute.sliceStatic": 2,
          "core.compute.bitSelect": 2, "core.compute.add": 3,
          "core.compute.sub": 3}
K_EVAL_X4 = defaultdict(lambda: 12, {k: v * 4 for k, v in K_EVAL.items()})


def is_compute_super(view, unit):
    """Compute supernode = kind Supernode whose first child is a Node
    (checkpoint phase attrs are all None; NO00014 lesson, mirrors
    cpu_schedule.cpp)."""
    parts = view["partitions"]
    part = parts[unit]
    children = part[4]
    return (part[2] == KIND_SUPER and bool(children)
            and parts[children[0]][2] == KIND_NODE)


def compute_unit_inputs(view):
    """In(B): cross-unit operand values read by each supernode's ops
    (pre-migration partition tree)."""
    unit_inputs = defaultdict(set)
    for unit, ops in view["unit_ops"].items():
        for op in ops:
            for w in view["op_operands"].get(op, ()):
                prod_unit = view["unit_of_op"].get(view["producer_of"].get(w, 0), 0)
                if prod_unit != unit:
                    unit_inputs[unit].add(w)
    return unit_inputs


def full_fanout(view):
    """Tree-derived (full) compute fanout activate rows: buildSchedule rebuilds
    rows from the partition tree before replaying the NO00014 rule, so the
    replayed removal set is computed on these rows, not on the stored
    (pruned) ones. A boundary value's full activate row = the compute
    supernodes (other than its producer unit) containing its consumers."""
    activate = {}
    for vid in view["is_boundary"]:
        prod_unit = view["unit_of_op"].get(view["producer_of"].get(vid, 0), 0)
        targets = set()
        for c in view["consumers_of"].get(vid, ()):
            u = view["unit_of_op"].get(c, 0)
            if u and u != prod_unit and is_compute_super(view, u):
                targets.add(u)
        if targets:
            activate[vid] = targets
    return activate


def demonitored_values(view):
    """De-monitored values, exact characterization (C++ pass mirror): boundary
    values whose STORED row is missing while the tree-derived full row
    (compute-supernode consumers outside the producer unit) is non-empty.
    buildSchedule rebuilds full rows from the tree, then the NO00014/NO00015
    rules delete rows; so stored-missing & full-non-empty is exactly the union
    of the two removal sets."""
    removed = set()
    for vid in view["is_boundary"]:
        if view["fanout_activate"].get(vid):
            continue
        prod_unit = view["unit_of_op"].get(view["producer_of"].get(vid, 0), 0)
        for c in view["consumers_of"].get(vid, ()):
            u = view["unit_of_op"].get(c, 0)
            if u and u != prod_unit and is_compute_super(view, u):
                removed.add(vid)
                break
    return removed


def demonitor_closure(view):
    """De-monitor closure: non-constant producer operands of de-monitored
    values. A candidate whose v or new-edge sources land here is rejected
    (pipeline-position safety). Returns (closure, removed_n, stored15_n,
    removed14_check, removed14) where removed14_check validates the
    characterization against the full-row replay recompute (must equal 19308,
    NO00014 archive) and removed14 is the replayed removal set itself."""
    removed = demonitored_values(view)
    stored = view.get("stored_ec_removed") or set()
    full_view = dict(view)
    full_view["fanout_activate"] = full_fanout(view)
    full_view["fanout_arm"] = {}  # deleted rows had empty arms (removal rule)
    removed14_rows, _partial, _rej, _pa, state_cover, _pre = demonitor_census(full_view)
    removed14 = {e["v"] for e in removed14_rows} | {e["v"] for e in state_cover}
    # Characterization validation: removed == NO00014 replay set + stored set.
    removed14_check = len(removed14)
    if removed != (removed14 | set(stored)):
        raise RuntimeError(
            "de-monitor characterization mismatch: "
            f"characterization {len(removed)} vs replay {len(removed14)} + "
            f"stored {len(stored)} (symdiff "
            f"{len(removed ^ (removed14 | set(stored)))})")
    closure = set()
    for vid in removed:
        xop = view["producer_of"].get(vid, 0)
        for w in view["op_operands"].get(xop, ()):
            prod = view["producer_of"].get(w, 0)
            if prod and view["op_name"].get(prod, "") == CONSTANT_KIND:
                continue
            closure.add(w)
    return closure, len(removed), len(stored), removed14_check, removed14


def candidates(view, unit_inputs, closure=()):
    """Static eligibility. Returns (cands, rejections); each cand carries
    v/op/kind/unit_a/unit_b/width/operands (non-constant) /missing (new-edge
    sources)."""
    cands, rejections = [], Counter()
    activate = view["fanout_activate"]
    closure = set(closure)
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
        if vid in closure:
            rejections["closure_source"] += 1
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
        if not is_compute_super(view, unit_a):
            rejections["producer_not_compute"] += 1
            continue
        if view["op_has_refs"].get(xop, True) or len(view["op_results"].get(xop, ())) != 1:
            rejections["refs_or_results"] += 1
            continue
        row = activate.get(vid)
        if not row:
            rejections["no_fanout_row"] += 1
            continue
        if view["fanout_arm"].get(vid):
            rejections["arm_non_empty"] += 1
            continue
        consumers = view["consumers_of"].get(vid, [])
        if not consumers:
            rejections["dead"] += 1
            continue
        units = {view["unit_of_op"].get(c, 0) for c in consumers}
        if len(units) != 1:
            rejections["multi_consumer_unit"] += 1
            continue
        unit_b = next(iter(units))
        if unit_b == 0:
            rejections["consumer_no_unit"] += 1
            continue
        if unit_b == unit_a:
            rejections["self_unit"] += 1
            continue
        if not is_compute_super(view, unit_b):
            rejections["non_compute_target"] += 1
            continue
        if not side_effect_free(view, unit_b):
            rejections["side_effect_unit"] += 1
            continue
        inputs_b = unit_inputs.get(unit_b, set())
        operands = []
        missing = []
        bad = None
        for w in view["op_operands"].get(xop, ()):
            prod = view["producer_of"].get(w, 0)
            if prod and view["op_name"].get(prod, "") == CONSTANT_KIND:
                # Constants are inlined at read sites wherever they live --
                # except a donor-local constant result whose only external
                # reader is X itself: the data layout does not inline those,
                # so X leaving would turn w into a NEW boundary value
                # (NO00013 constant rejection rule).
                if view["unit_of_op"].get(prod, 0) == unit_a and not any(
                        view["unit_of_op"].get(c, 0) != unit_a
                        for c in view["consumers_of"].get(w, ()) if c != xop):
                    bad = "constant_orphan"
                    break
                continue
            if prod and view["unit_of_op"].get(prod, 0) == unit_b:
                operands.append(w)
                continue
            if w in inputs_b:
                operands.append(w)
                continue
            if not prod:
                bad = "input_unseen"
                break
            # New edge source: w must carry a runtime-live row so the rebuilt
            # schedule can activate B on w-change (NO00015 liveness rules).
            if w == vid:
                bad = "edge_self"
                break
            if w in closure:
                bad = "closure_edge"
                break
            if w not in view["is_boundary"]:
                bad = "edge_not_boundary"
                break
            if not activate.get(w):
                bad = "edge_row_missing"
                break
            if w in view["pinned"]:
                bad = "edge_pinned"
                break
            if w in view["event_gate_values"]:
                bad = "edge_event_gate"
                break
            if w in view["aliased_read_values"]:
                bad = "edge_aliased"
                break
            if w in view["dpi_produced"]:
                bad = "edge_dpi_blind"
                break
            operands.append(w)
            missing.append(w)
        if bad:
            rejections[bad] += 1
            continue
        cands.append({"v": vid, "op": xop, "kind": kind, "unit_a": unit_a,
                      "unit_b": unit_b, "width": width,
                      "operands": operands, "missing": missing})
    return cands, rejections


def price(view, cands, vchg, body):
    """Annotate candidates with wr/ch/save/widen/reeval/profit (float) and the
    integer x4 profit used for selection."""
    for c in cands:
        wr, ch = vchg.get(c["v"], (0, 0))
        ops_b = len(view["unit_ops"].get(c["unit_b"], ()))
        widen_x4 = 0
        cold_edges = 0
        for w in c["missing"]:
            _w_wr, w_ch = vchg.get(w, (0, 0))
            widen_x4 += w_ch * ((ops_b + 1) * K_OP_X4 + K_SET_X4)
            if w_ch == 0:
                cold_edges += 1
        body_b = body.get(c["unit_b"], 0)
        reeval_x4 = body_b * K_EVAL_X4[c["kind"]]
        c["wr"], c["ch"] = wr, ch
        c["save"] = wr * (K_DETECT + K_STORE)
        c["widen"] = widen_x4 / 4.0
        c["reeval"] = reeval_x4 / 4.0
        c["profit"] = c["save"] - c["widen"] - c["reeval"]
        c["profit_x4"] = wr * SAVE_X4 - widen_x4 - reeval_x4
        c["cold_edges"] = cold_edges
        c["body_b"] = body_b
        c["ops_b"] = ops_b
    return cands


def fixpoint(view, cands):
    """Greatest fixpoint: a selected value's non-constant operands must not be
    selected (a migrated operand loses its row / becomes unit-local)."""
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


def select(view, unit_inputs, vchg, body, closure=()):
    """Authoritative selection: eligibility (with the de-monitor closure
    exclusion), integer pricing (profit>0), then the cascade fixpoint over the
    profitable set. Mirrors the C++ pass."""
    cands, _ = candidates(view, unit_inputs, closure)
    price(view, cands, vchg, body)
    return fixpoint(view, [c for c in cands if c["profit_x4"] > 0])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile-output", type=Path,
                        help="write the flat profile consumed by the "
                             "grhsim.migrate-boundary-ops-ec pass")
    parser.add_argument("--cycles", type=int, default=100001)
    args = parser.parse_args(argv)

    view = load_model(args.model)
    unit_inputs = compute_unit_inputs(view)
    closure, removed14_n, stored15_n, cascade14, _removed14 = demonitor_closure(view)
    cands, rejections = candidates(view, unit_inputs, closure)

    monitored = sum(1 for v in view["is_boundary"] if view["fanout_activate"].get(v))
    n_edges = sum(len(c["missing"]) for c in cands)
    zero_edge = sum(1 for c in cands if not c["missing"])
    out = {"boundary": len(view["is_boundary"]), "monitored_rows": monitored,
           "demonitor_removed14": removed14_n, "demonitor_removed14_cascade": cascade14,
           "demonitor_stored15": stored15_n,
           "closure": len(closure),
           "candidates": len(cands), "new_edges": n_edges,
           "zero_edge_candidates": zero_edge,
           "rejections": dict(rejections),
           "by_kind": dict(Counter(c["kind"] for c in cands))}
    lines = ["# NO00019 edge-completion migration census", "",
             f"boundary values: {out['boundary']}",
             f"monitored (live fanout row): {monitored}",
             f"de-monitor sets: NO00014 replayed {removed14_n} (cascade trimmed {cascade14}) "
             f"+ NO00015 stored {stored15_n}; closure (protected producer operands): {len(closure)}",
             f"candidates (single consumer unit, edge feasible): {out['candidates']}",
             f"  of which zero-new-edge (NO00013 remnants): {zero_edge}",
             f"new edges required: {out['new_edges']}",
             "", "## rejections"]
    lines += [f"- {k}: {v}" for k, v in sorted(rejections.items())]
    lines += ["", "## candidates by kind"]
    lines += [f"- {k}: {v}" for k, v in sorted(out["by_kind"].items(), key=lambda kv: -kv[1])]

    if args.run:
        vchg, body = parse_run(args.run.read_text(errors="replace"))
        total_wr = sum(w for w, _ in vchg.values())
        price(view, cands, vchg, body)
        sel = select(view, unit_inputs, vchg, body, closure)
        pre_fixpoint = sum(1 for c in cands if c["profit_x4"] > 0)
        tot = {"save": 0.0, "widen": 0.0, "reeval": 0.0, "profit": 0.0, "wr": 0}
        agg = defaultdict(lambda: {"n": 0, "save": 0.0, "widen": 0.0,
                                   "reeval": 0.0, "profit": 0.0})
        for c in sel:
            tot["save"] += c["save"]
            tot["widen"] += c["widen"]
            tot["reeval"] += c["reeval"]
            tot["profit"] += c["profit"]
            tot["wr"] += c["wr"]
            key = (c["kind"], width_bucket(c["width"]),
                   coldness_bucket(c["ch"] / c["wr"] if c["wr"] else 0.0))
            a = agg[key]
            a["n"] += 1
            a["save"] += c["save"]
            a["widen"] += c["widen"]
            a["reeval"] += c["reeval"]
            a["profit"] += c["profit"]
        cyc = args.cycles
        all_profit = sum(c["profit"] for c in cands) / cyc
        out["total_wr_pc"] = total_wr / cyc
        out["all_profit_instr_pc"] = all_profit
        out["selected_pre_fixpoint"] = pre_fixpoint
        out["cascade_trimmed"] = pre_fixpoint - len(sel)
        out["selected"] = len(sel)
        out["selected_edges"] = sum(len(c["missing"]) for c in sel)
        out["selected_cold_edges"] = sum(c["cold_edges"] for c in sel)
        out["selected_zero_edge"] = sum(1 for c in sel if not c["missing"])
        out["save_wr_pc"] = tot["wr"] / cyc
        out["save_instr_pc"] = tot["save"] / cyc
        out["widen_instr_pc"] = tot["widen"] / cyc
        out["reeval_instr_pc"] = tot["reeval"] / cyc
        out["profit_instr_pc"] = tot["profit"] / cyc
        lines += ["", "## dynamic profit (estimate)",
                  f"- all candidates aggregate profit: {all_profit:,.1f} instr/cycle",
                  f"- selected (profit>0): {out['selected']} values "
                  f"(pre-fixpoint {pre_fixpoint}, cascade trimmed "
                  f"{out['cascade_trimmed']}; zero-edge "
                  f"{out['selected_zero_edge']}), {out['selected_edges']} new "
                  f"edges ({out['selected_cold_edges']} with ch_w=0)",
                  f"- detection writes removed: {out['save_wr_pc']:,.1f}/cycle",
                  f"- save: {out['save_instr_pc']:,.1f} instr/cycle",
                  f"- widen (upper bound): {out['widen_instr_pc']:,.1f} instr/cycle",
                  f"- reeval (upper bound): {out['reeval_instr_pc']:,.1f} instr/cycle",
                  f"- **profit: {out['profit_instr_pc']:,.1f} instr/cycle**"]
        top = sorted(agg.items(), key=lambda kv: -kv[1]["profit"])[:20]
        out["by_class"] = {str(k): {"n": v["n"], "save_pc": v["save"] / cyc,
                                    "widen_pc": v["widen"] / cyc,
                                    "reeval_pc": v["reeval"] / cyc,
                                    "profit_pc": v["profit"] / cyc}
                           for k, v in top}
        lines += ["", "## top classes by profit/cycle"]
        lines += [f"- {k}: n={v['n']} save={v['save'] / cyc:,.1f} "
                  f"widen={v['widen'] / cyc:,.1f} reeval={v['reeval'] / cyc:,.1f} "
                  f"profit={v['profit'] / cyc:,.1f}" for k, v in top]
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "selected.json").write_text(json.dumps(
            [{"v": c["v"], "op": c["op"], "kind": c["kind"],
              "unit_a": c["unit_a"], "unit_b": c["unit_b"],
              "wr": c["wr"], "ch": c["ch"], "save": c["save"],
              "widen": c["widen"], "reeval": c["reeval"],
              "profit": c["profit"], "missing": c["missing"]}
             for c in sel], indent=0))
        if args.profile_output:
            # Flat profile for the C++ pass: value rows "v <id> <wr> <ch>"
            # (candidates + their non-constant operands) and unit rows
            # "u <unit> <body>" (candidate consumer units).
            values = set()
            units = set()
            for c in cands:
                values.add(c["v"])
                values.update(c["operands"])
                units.add(c["unit_b"])
            with args.profile_output.open("w") as fh:
                fh.write(f"# grhsim-migrate-ec-profile v1 cycles={args.cycles}\n")
                for vid in sorted(values):
                    wr, ch = vchg.get(vid, (0, 0))
                    fh.write(f"v {vid} {wr} {ch}\n")
                for unit in sorted(units):
                    fh.write(f"u {unit} {body.get(unit, 0)}\n")

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(json.dumps(out, indent=1))
    (args.output / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
