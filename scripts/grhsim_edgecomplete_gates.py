#!/usr/bin/env python3
"""NO00015 pre-registered semantic gates for edge-completion de-monitoring.

Compares an old (baseline, NO00014) mapped checkpoint against a new
(edge-completed) one and, when diagnostic run logs are provided, checks the
dynamic counter bound rules. Gates (all must PASS):

1. model-section-neutral   every top-level checkpoint key except "mappings" is
                           JSON-equal between old and new (semantics untouched)
2. partition-layout-neutral partition tree and data layout are JSON-equal
                           (edge completion touches no op membership, no slot)
3. fanout-edges-closure    new computeSupernodeFanout == old minus exactly the
                           census selected set (recomputed in-process from the
                           old model + baseline-run vchg profile); rows of
                           operand values w gain exactly the completion edges
                           (new activate set == old set + added, in activeId
                           order); all other rows byte-unchanged; inputFanout /
                           commitStateFanout / roundSeeds / inputShadows /
                           quiescenceProjection unchanged; the schedule's
                           trailing removal list equals the selected set
4. sn-rows-bounded         per-unit [grhsim-dyn] sn act/body/grp/chg <= baseline
                           for units without completion edges, <= baseline +
                           W_B for widened units (W_B = sum of ch_w over the
                           unit's added edges: the extra-fire upper bound;
                           same-round co-activation collapses)
5. vchg-rows-bounded       per-value: removed values must drop to wr=0 ch=0;
                           other values: ch <= baseline; wr <= baseline + W_B of
                           the producer's unit (extra fires rewrite outputs)
6. mshrink-closure         removed Σwr (census, exact) - (baseline Σwr - new
                           Σwr) must lie in [0, Σ_v allowance(v)] (added writes
                           from widened-unit rewrites, bounded)
7. determinism+endpoint    run1/run2 [grhsim-vchg]/[grhsim-dyn] streams identical;
                           endpoint fields equal and match the pre-registered
                           baseline endpoint (instrCnt=240349 cycleCnt=99996
                           guest=100001 pc=0x80000c0c)

Gates 1-3 always run; 4-6 need --baseline-run and --run1; 7 needs --run1/--run2.
"""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grhsim_demonitor_census as dc  # noqa: E402
import grhsim_edgecomplete_census as ec  # noqa: E402
from grhsim_demonitor_gates import (  # noqa: E402
    Gate, gate_model_neutral, gate_partition_layout_neutral, gate_determinism,
    parse_sn)


def schedule_of(model):
    return model["mappings"][0][-1][4]


def active_id_of(partitions, pid):
    row = partitions[pid]
    if len(row) > 7 and row[7] and row[7][0]:
        return row[7][0][0]
    return -1


def gate_fanout_edges(old_model, new_model, baseline_vchg):
    g = Gate("3.fanout-edges-closure")
    old_sched = schedule_of(old_model)
    new_sched = schedule_of(new_model)
    for idx, name in ((1, "inputFanout"), (3, "commitStateFanout"), (4, "roundSeeds"),
                      (5, "inputShadows"), (6, "inputShadowBytes"),
                      (7, "quiescenceProjectionBits"), (8, "quiescenceProjectionWords")):
        g.check(old_sched[idx] == new_sched[idx], f"{name} differs")
    g.check(old_sched[9:] == new_sched[9:][:len(old_sched[9:])],
            "schedule trailing flags prefix differs")

    view = dc.view_from_model(old_model)
    selected = ec.select(view, baseline_vchg)
    expected_removed = {c["v"] for c in selected}
    # added edges per operand value w: set of target units
    added = defaultdict(set)
    for c in selected:
        for unit, ws in c["missing"].items():
            for w in ws:
                added[w].add(int(unit))

    old_rows = {row[0]: row for row in old_sched[2]}
    new_rows = {row[0]: row for row in new_sched[2]}
    grew = sorted(set(new_rows) - set(old_rows))
    g.check(not grew, f"{len(grew)} new fanout rows appeared: {grew[:5]}")
    removed = set(old_rows) - set(new_rows)
    g.check(removed == expected_removed,
            f"removed set mismatch: only-pass {sorted(removed - expected_removed)[:5]} "
            f"only-census {sorted(expected_removed - removed)[:5]}")
    partitions = view["partitions"]
    bad_edges, bad_order, changed_other = [], [], []
    for v in set(old_rows) & set(new_rows):
        old_row, new_row = old_rows[v], new_rows[v]
        if old_row[2] != new_row[2]:
            bad_edges.append((v, "arm changed"))
            continue
        old_act, new_act = old_row[1], new_row[1]
        if v in added:
            if set(new_act) != set(old_act) | added[v]:
                bad_edges.append((v, f"activate set mismatch (+{sorted(added[v])[:3]}...)"))
            elif new_act != sorted(new_act, key=lambda u: active_id_of(partitions, u)):
                bad_order.append(v)
        elif old_act != new_act:
            changed_other.append(v)
    g.check(not bad_edges, f"{len(bad_edges)} rows have wrong edge sets: {bad_edges[:3]}")
    g.check(not bad_order, f"{len(bad_order)} rows lost activeId ordering: {bad_order[:5]}")
    g.check(not changed_other, f"{len(changed_other)} untouched rows changed: {changed_other[:5]}")
    removal_field = new_sched[10] if len(new_sched) > 10 else None
    g.check(removal_field == sorted(expected_removed),
            "schedule removal list != census selected set")
    g.note(f"removed rows: {len(removed)}; operand rows widened: {len(added)}; "
           f"added edges: {sum(len(s) for s in added.values())}; "
           f"remaining rows: {len(new_rows)}")
    return g, selected, added


def widen_bounds(selected, vchg):
    """Per widened unit: W_B = sum of ch_w over its added edges (extra-fire
    upper bound). Per value allowance: W_B of its producer's unit."""
    unit_bound = defaultdict(int)
    for c in selected:
        for unit, ws in c["missing"].items():
            unit_bound[int(unit)] += sum(vchg.get(w, (0, 0))[1] for w in ws)
    return unit_bound


def gate_sn_bounded(baseline_run, run1, unit_bound):
    g = Gate("4.sn-rows-bounded")
    base = parse_sn(baseline_run)
    new = parse_sn(run1)
    g.check(bool(base), "baseline log has no sn rows")
    g.check(bool(new), "new run log has no sn rows")
    violations, shrinks, widened = [], [], 0
    for pid, nrow in new.items():
        brow = base.get(pid)
        if brow is None:
            violations.append((pid, "new unit row", nrow))
            continue
        bound = unit_bound.get(pid, 0)
        if bound:
            widened += 1
        if any(n > b + bound for n, b in zip(nrow, brow)):
            violations.append((pid, brow, nrow, f"bound +{bound}"))
        elif any(n < b for n, b in zip(nrow, brow)):
            shrinks.append((pid, brow, nrow))
    missing = sorted(set(base) - set(new))
    g.check(not missing, f"{len(missing)} baseline units lost their sn row: {missing[:5]}")
    g.check(not violations, f"{len(violations)} units exceed baseline+bound: {violations[:5]}")
    g.note(f"units compared: {len(base)}; widened (bound>0): {widened}; "
           f"shrunk: {len(shrinks)}; sample {shrinks[:5]}")
    return g


def gate_vchg_bounded(baseline_run, run1, selected, unit_bound, view):
    g = Gate("5.vchg-rows-bounded")
    base, _ = dc.parse_run(Path(baseline_run).read_text(errors="replace"))
    new, _ = dc.parse_run(Path(run1).read_text(errors="replace"))
    g.check(bool(base), "baseline log has no vchg rows")
    g.check(bool(new), "new run log has no vchg rows")
    removed = {c["v"] for c in selected}
    violations, widened_values = [], 0
    for v in set(base) | set(new):
        bwr, bch = base.get(v, (0, 0))
        nwr, nch = new.get(v, (0, 0))
        if v in removed:
            if nwr or nch:
                violations.append((v, "removed but still counted", (bwr, bch), (nwr, nch)))
            continue
        if nch > bch:
            violations.append((v, "ch grew", (bwr, bch), (nwr, nch)))
            continue
        prod = view["producer_of"].get(v, 0)
        unit = view["unit_of_op"].get(prod, 0)
        allow = unit_bound.get(unit, 0)
        if allow:
            widened_values += 1
        if nwr > bwr + allow:
            violations.append((v, f"wr grew beyond +{allow}", (bwr, bch), (nwr, nch)))
    g.check(not violations, f"{len(violations)} values violate bounds: {violations[:5]}")
    g.note(f"values compared: {len(set(base) | set(new))}; removed (wr must be 0): "
           f"{len(removed)}; values in widened units: {widened_values}")
    return g


def gate_mshrink_closure(baseline_run, run1, selected, unit_bound, view, cycles):
    g = Gate("6.mshrink-closure")
    base, _ = dc.parse_run(Path(baseline_run).read_text(errors="replace"))
    new, _ = dc.parse_run(Path(run1).read_text(errors="replace"))
    removed_wr = sum(base.get(c["v"], (0, 0))[0] for c in selected)
    base_wr = sum(w for w, _ in base.values())
    new_wr = sum(w for w, _ in new.values())
    allowance = 0
    for v in set(base) | set(new):
        prod = view["producer_of"].get(v, 0)
        unit = view["unit_of_op"].get(prod, 0)
        allowance += unit_bound.get(unit, 0)
    added = removed_wr - (base_wr - new_wr)
    g.check(0 <= added <= allowance,
            f"added writes {added} outside [0, {allowance}] "
            f"(removed {removed_wr}, shrink {base_wr - new_wr})")
    g.note(f"baseline Σwr={base_wr} new Σwr={new_wr} "
           f"removed={removed_wr} ({removed_wr / cycles:.2f}/cyc) "
           f"added_writes={added} bound={allowance}")
    return g


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-model", type=Path, required=True)
    parser.add_argument("--new-model", type=Path, required=True)
    parser.add_argument("--baseline-run", type=Path, required=True,
                        help="baseline (NO00014) dyn run log: recomputes the "
                             "pricing selection and provides baseline counters")
    parser.add_argument("--run1", type=Path)
    parser.add_argument("--run2", type=Path)
    parser.add_argument("--cycles", type=int, default=100001)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    old_model = json.loads(args.old_model.read_bytes())
    new_model = json.loads(args.new_model.read_bytes())
    baseline_vchg, _ = dc.parse_run(args.baseline_run.read_text(errors="replace"))

    gates = [gate_model_neutral(old_model, new_model),
             gate_partition_layout_neutral(old_model, new_model)]
    fanout_gate, selected, added = gate_fanout_edges(old_model, new_model, baseline_vchg)
    gates.append(fanout_gate)

    if args.run1:
        view = dc.view_from_model(old_model)
        unit_bound = widen_bounds(selected, baseline_vchg)
        gates.append(gate_sn_bounded(args.baseline_run, args.run1, unit_bound))
        gates.append(gate_vchg_bounded(args.baseline_run, args.run1, selected, unit_bound, view))
        gates.append(gate_mshrink_closure(args.baseline_run, args.run1, selected, unit_bound,
                                          view, args.cycles))
    if args.run1 and args.run2:
        gates.append(gate_determinism(args.run1, args.run2))

    ok = all(g.ok for g in gates)
    lines = ["# NO00015 edge-completion gates", ""]
    for g in gates:
        lines.append(f"- [{'PASS' if g.ok else 'FAIL'}] {g.name}")
        for detail in g.detail:
            lines.append(f"    - {detail}")
    lines.append("")
    lines.append(f"VERDICT: {'ALL GATES PASS' if ok else 'GATE FAILURE'}")
    text = "\n".join(lines) + "\n"
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "gates.md").write_text(text)
    (args.output / "gates.json").write_text(json.dumps(
        {"ok": ok, "gates": [g.row() for g in gates]}, indent=1))
    print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
