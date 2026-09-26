#!/usr/bin/env python3
"""NO00019 pre-registered semantic gates for edge-completion boundary-op
migration (profile-priced migration allowing new activation edges).

Compares an old (baseline, NO00015) mapped checkpoint against a new
(migrated) one and, when diagnostic run logs are provided, checks the dynamic
counter bound rules. Gates (all must PASS):

1. model-section-neutral   every top-level checkpoint key except "mappings" is
                           JSON-equal between old and new (semantics untouched)
2. boundary-shrink-closed  no new Boundary values; every flipped value lands in
                           PartitionLocal; non-flipped values keep their slot kind
3. op-membership-closed    supernodes match old<->new by op-set signature
                           (ops minus migrated ops, disjoint hence unambiguous);
                           every unmigrated op stays in its matched unit; every
                           migrated op lands in the matched common consumer unit
4. census-restore-reconciliation  migrated value set == the census selection
                           recomputed in-process (old model + baseline-run vchg
                           profile) projected through the restore rule (donor
                           keeps >= 1 op; the last flat-order candidate per
                           emptied donor is spared); zero error
5. fanout-edges-closure    computeSupernodeFanout == the exact buildSchedule
                           mirror recomputed on each tree: full tree-derived
                           rows (layout-owner edge semantics, event-gate
                           arms) minus the NO00014 greatest-fixpoint replay,
                           with the NO00015 stored removal list replayed
                           (eligibility revalidated, completion edges
                           re-derived and appended to the operand rows). The
                           mirror must reproduce the stored rows byte-exactly
                           on the OLD tree (validates the mirror itself) and
                           on the NEW tree (closes the migration); migrated
                           values keep no row. inputFanout /
                           commitStateFanout / roundSeeds equal modulo the
                           old->new unit id map; inputShadows /
                           inputShadowBytes / quiescence projection / flags /
                           stored removal list byte-unchanged
6. sn-rows-bounded         per-unit [grhsim-dyn] sn act/body/grp <= baseline +
                           W_B (W_B = sum of ch_w over the unit's added edges;
                           0 for units without new edges, so donors may only
                           shrink); chg <= baseline + the closed-form
                           re-monitor allowance (sum of run1 ch over the
                           unit's re-monitored values; 0 elsewhere)
7. kind-vchg-bounded       per-value [grhsim-vchg]: migrated values drop to
                           wr=0 ch=0; re-monitored values (NO00014 replay
                           drift: no stored fanout row in the old tree, row
                           present in the new tree) are exempt from the growth
                           bounds but their baseline counters must be exactly
                           (0,0); other values ch <= baseline, wr <=
                           baseline + W_B of the producer's unit; per-kind
                           [grhsim-dyn] ch <= baseline, wr <= baseline + the
                           summed per-value allowances of the kind
8. mshrink-closure         removed Σwr over the migrated set (baseline
                           counters) == the census closed form (error 0);
                           added writes = removed - (baseline Σwr - new Σwr)
                           <= Σ_B W_B x |B's monitored outputs| (a negative
                           added term is the NO00014 replay bonus: reported,
                           not gated)
9. determinism+endpoint    run1/run2 [grhsim-vchg]/[grhsim-dyn] streams
                           identical; endpoint fields equal and match the
                           pre-registered baseline endpoint
                           (instrCnt=240349 cycleCnt=99996 guest=100001
                           pc=0x80000c0c)

Gates 1-5 always run; 6-8 need --baseline-run and --run1; 9 needs
--run1/--run2.
"""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grhsim_demonitor_census as dc  # noqa: E402
import grhsim_migrate_ec_census as mc  # noqa: E402
from grhsim_edgecomplete_gates import schedule_of, active_id_of  # noqa: E402
from grhsim_migration_gates import (  # noqa: E402
    Gate, MappingInfo, analyze_migration, gate_model_neutral,
    gate_boundary_closed, gate_membership, gate_determinism,
    parse_sn, parse_kinds)


def flat_ops_of(partitions, pid):
    """Supernode op list in flattened tree order (children in listed order)."""
    out = []

    def walk(p):
        row = partitions[p]
        for child in row[4]:
            walk(child)
        out.extend(row[5])

    walk(pid)
    return out


def recompute_selection(old_model, baseline_run):
    """Authoritative in-process selection: census eligibility (with the
    de-monitor closure exclusion) + integer pricing + cascade fixpoint over
    the old model and the baseline-run vchg/sn profile. Returns the census
    view, the baseline vchg counters and the selected candidates."""
    view = dc.view_from_model(old_model)
    unit_inputs = mc.compute_unit_inputs(view)
    closure, _removed14_n, _stored15_n, _check, _replay14 = mc.demonitor_closure(view)
    vchg, body = dc.parse_run(Path(baseline_run).read_text(errors="replace"))
    selected = mc.select(view, unit_inputs, vchg, body, closure)
    return view, vchg, selected


def restore_projection(selected, partitions, unit_flat_ops):
    """NO00013 restore rule mirror: a donor supernode keeps at least one op;
    when every op of a donor would migrate, its last flat-order candidate is
    spared. Returns (projected, spared). `selected` entries carry v/op/unit_a;
    unit_flat_ops maps unit -> op list in flat order."""
    by_donor = defaultdict(list)
    for c in selected:
        by_donor[c["unit_a"]].append(c)
    spared = set()
    for unit, cands in by_donor.items():
        flat = unit_flat_ops.get(unit)
        if flat is None:
            flat = flat_ops_of(partitions, unit)
            unit_flat_ops[unit] = flat
        if len(cands) < len(flat):
            continue
        order = {op: idx for idx, op in enumerate(flat)}
        spared.add(max(cands, key=lambda c: order[c["op"]])["v"])
    return [c for c in selected if c["v"] not in spared], sorted(spared)


def widen_bounds(selected, vchg):
    """Per edge-target unit: W_B = sum of ch_w over its added edges (the
    extra-fire upper bound; same-round co-activation collapses)."""
    unit_bound = defaultdict(int)
    for c in selected:
        for w in c["missing"]:
            unit_bound[c["unit_b"]] += vchg.get(w, (0, 0))[1]
    return unit_bound


def gate_reconciliation(selected, projected, spared, flipped):
    g = Gate("4.census-restore-reconciliation")
    migrated = set(flipped)
    expected = {c["v"] for c in projected}
    g.check(migrated == expected,
            f"migrated set != restore projection: only-pass "
            f"{sorted(migrated - expected)[:5]} only-census "
            f"{sorted(expected - migrated)[:5]}")
    g.note(f"census selected: {len(selected)}; spared by restore: {len(spared)} "
           f"{spared[:5]}; projected: {len(expected)}; migrated: {len(migrated)}")
    return g


KIND_EVENT_DOMAIN = 2
KIND_NODE = 4


def tree_owner_domain(partitions, op_count):
    """ScheduleGraph owner/domain mirror (cpu_schedule.cpp): an op's owner is
    the parent of the Node partition listing it (non-Node partitions own their
    listed ops directly); its domain is the nearest EventDomain ancestor above
    the listing partition (0 = compute op)."""
    owner_of = [0] * (op_count + 1)
    domain_of = [0] * (op_count + 1)
    for pid, part in partitions.items():
        ops = part[5]
        if not ops:
            continue
        unit = part[1] if part[2] == KIND_NODE else pid
        domain = 0
        parent = part[1]
        while parent:
            prow = partitions[parent]
            if prow[2] == KIND_EVENT_DOMAIN:
                domain = parent
                break
            parent = prow[1]
        for op in ops:
            if 0 < op <= op_count:
                owner_of[op] = unit
                domain_of[op] = domain
    return owner_of, domain_of


def full_fanout_rows(model, view):
    """buildSchedule computeSupernodeFanout construction mirror: every compute
    op (domain == 0) contributes an activate edge (operand -> op owner) for
    each operand whose LAYOUT owner differs from the op's owner partition; a
    null owner still opens a (targetless) row. Event-gate values gain arm
    edges to the gating partition (input values route to inputFanout
    instead). Returns {value: [activate targets in activeId order, arm
    targets in partition-id order]}; activate targets are deduped."""
    partitions = view["partitions"]
    operations = model["operations"]
    op_max = max((op[0] for op in operations), default=0)
    owner_of, domain_of = tree_owner_domain(partitions, op_max)
    value_slots = model["mappings"][0][-1][3][3]
    inputs = {v for v, op in view["producer_of"].items()
              if view["op_name"].get(op) == "core.input.read"}
    activate, arm, touched = defaultdict(set), defaultdict(set), set()
    for op in operations:
        oid = op[0]
        if oid > op_max or domain_of[oid]:
            continue
        owner = owner_of[oid]
        for w in op[4]:
            if value_slots[w - 1][2] != owner:
                touched.add(w)
                if owner:
                    activate[w].add(owner)
    for pid, part in partitions.items():
        gate = part[6] if len(part) > 6 else None
        if not gate:
            continue
        for event in gate[1]:
            v = event[0]
            if v not in inputs:
                touched.add(v)
                arm[v].add(pid)
    return {v: [sorted(activate.get(v, ()), key=lambda u: active_id_of(partitions, u)),
                sorted(arm.get(v, ()))]
            for v in touched}


def replay_demonitor_redundant(view, rows):
    """NO00014 greatest-fixpoint replay on the full mirror rows (dc.census is
    the exact mirror of applyDemonitorRedundant). Returns (kept rows, removed
    value set, state-cover leftovers); the C++ pass only removes
    compute-produced rows, so a non-empty state-cover list is a mirror bug."""
    full_view = dict(view)
    full_view["fanout_activate"] = {v: set(row[0]) for v, row in rows.items()}
    full_view["fanout_arm"] = {v: set(row[1]) for v, row in rows.items()}
    eligible, _partial, _rej, _pa, state_cover, _pre = dc.census(full_view)
    removed = {e["v"] for e in eligible}
    return ({v: row for v, row in rows.items() if v not in removed},
            removed, state_cover)


def replay_edge_completion(view, rows, stored15):
    """NO00015 stored-list replay (applyDemonitorEdgeCompletion): every stored
    value is revalidated on the post-NO00014 rows, its missing completion
    edges are re-derived and appended to the operand rows (activeId order),
    then the stored rows are dropped. activates() reads the pre-addition rows
    throughout, matching the C++ EdgeCompletionView built once up front.
    Returns (rows, invalid entries) — invalid covers values whose stored
    removal no longer revalidates and completion-edge sources without a row."""
    partitions = view["partitions"]

    def activates(w, unit):
        row = rows.get(w)
        return row is not None and unit in row[0]

    invalid = []
    additions = defaultdict(set)
    for v in stored15:
        row = rows.get(v)
        xop = view["producer_of"].get(v, 0)
        unit_a = view["unit_of_op"].get(xop, 0)
        operands = []
        ok = bool(row and row[0] and not row[1] and unit_a)
        if ok:
            for w in view["op_operands"].get(xop, ()):
                prod = view["producer_of"].get(w, 0)
                if prod and view["op_name"].get(prod, "") == "core.compute.constant":
                    continue
                if (w not in view["is_boundary"] or w in view["pinned"]
                        or not activates(w, unit_a)):
                    ok = False
                    break
                operands.append(w)
        if ok:
            for target in row[0]:
                for w in operands:
                    if activates(w, target):
                        continue
                    if w in view["aliased_read_values"] or w in view["dpi_produced"]:
                        ok = False
                        break
                    additions[w].add(target)
                if not ok:
                    break
        if not ok:
            invalid.append(v)
    for w in sorted(additions):
        row = rows.get(w)
        if row is None:
            invalid.append(w)
            continue
        row[0] = sorted(set(row[0]) | additions[w],
                        key=lambda u: active_id_of(partitions, u))
    for v in stored15:
        rows.pop(v, None)
    return rows, sorted(set(invalid))


def gate_fanout_edges(old_model, new_model, old_to_new, migrated):
    g = Gate("5.fanout-edges-closure")
    old_sched = schedule_of(old_model)
    new_sched = schedule_of(new_model)
    for idx, name in ((5, "inputShadows"), (6, "inputShadowBytes"),
                      (7, "quiescenceProjectionBits"), (8, "quiescenceProjectionWords"),
                      (9, "demonitorRedundant")):
        g.check(old_sched[idx] == new_sched[idx], f"{name} differs")
    g.check(len(old_sched) == len(new_sched),
            f"schedule field count differs: {len(old_sched)} vs {len(new_sched)}")
    stored15 = new_sched[10] if len(new_sched) > 10 else []
    old_stored = old_sched[10] if len(old_sched) > 10 else []
    g.check(old_stored == stored15, "NO00015 stored removal list changed")

    # Unit-id-remapped equality for input/commit fanout and roundSeeds.
    for idx, name in ((1, "inputFanout"), (3, "commitStateFanout")):
        old_sec = {row[0]: row for row in old_sched[idx]}
        new_sec = {row[0]: row for row in new_sched[idx]}
        g.check(set(old_sec) == set(new_sec), f"{name} row key sets differ")
        bad = []
        for key in set(old_sec) & set(new_sec):
            mapped = sorted(old_to_new.get(u, -1) for u in old_sec[key][1])
            if mapped != sorted(new_sec[key][1]) or old_sec[key][2] != new_sec[key][2]:
                bad.append(key)
        g.check(not bad, f"{name} rows differ beyond unit renumbering: {bad[:5]}")
    unmapped_seeds = [pid for pid in old_sched[4] if pid not in old_to_new]
    g.check(not unmapped_seeds,
            f"{len(unmapped_seeds)} roundSeeds units lost in the id map: {unmapped_seeds[:5]}")
    g.check(sorted(old_to_new.get(pid, -1) for pid in old_sched[4]) == sorted(new_sched[4]),
            "roundSeeds differ beyond unit renumbering")

    # computeSupernodeFanout: exact buildSchedule mirror on BOTH trees. The
    # old-tree run validates the mirror against the NO00015 archive; the
    # new-tree run then closes the migration — every row delta is by
    # construction the composition of the op moves, the NO00014 replay drift
    # and the re-derived NO00015 completion edges.
    old_rows = {row[0]: row for row in old_sched[2]}
    new_rows = {row[0]: row for row in new_sched[2]}
    for label, model, sched, stored_rows in (("old", old_model, old_sched, old_rows),
                                             ("new", new_model, new_sched, new_rows)):
        view = dc.view_from_model(model)
        full = full_fanout_rows(model, view)
        kept, removed14, state_cover = replay_demonitor_redundant(view, full)
        g.check(not state_cover,
                f"{label}: {len(state_cover)} state-read rows in the NO00014 replay set")
        mirrored, invalid = replay_edge_completion(view, kept, stored15)
        g.check(not invalid,
                f"{label}: stored removal list fails revalidation: {invalid[:5]}")
        only_stored = sorted(set(stored_rows) - set(mirrored))
        only_mirror = sorted(set(mirrored) - set(stored_rows))
        g.check(not only_stored and not only_mirror,
                f"{label}: row keys deviate from the tree mirror: only-stored "
                f"{only_stored[:5]} (+{len(only_stored)}) only-mirror "
                f"{only_mirror[:5]} (+{len(only_mirror)})")
        bad_act, bad_order = [], []
        for v in set(stored_rows) & set(mirrored):
            row, want = stored_rows[v], mirrored[v]
            if set(row[1]) != set(want[0]) or set(row[2]) != set(want[1]):
                bad_act.append(v)
            elif row[1] != want[0] or row[2] != want[1]:
                bad_order.append(v)
        g.check(not bad_act,
                f"{label}: {len(bad_act)} rows deviate from the tree mirror: {bad_act[:5]}")
        g.check(not bad_order,
                f"{label}: {len(bad_order)} rows lost activeId ordering: {bad_order[:5]}")
        g.note(f"{label}: full rows {len(full)}; NO00014 replay {len(removed14)}; "
               f"stored rows {len(stored_rows)}")
    leaked = set(new_rows) & set(migrated)
    g.check(not leaked, f"{len(leaked)} migrated values keep a fanout row: {sorted(leaked)[:5]}")
    removed = set(old_rows) - set(new_rows)
    appeared = sorted(set(new_rows) - set(old_rows))
    g.note(f"rows: old {len(old_rows)} new {len(new_rows)}; removed {len(removed)} "
           f"(migrated {len(set(migrated))}, replay/completion drift "
           f"{len(removed - set(migrated))}); re-monitored rows {len(appeared)} "
           f"{appeared[:5]}")
    return g


def gate_sn_bounded(baseline_run, run1, old_to_new, unit_bound, targets, remon_chg):
    g = Gate("6.sn-rows-bounded")
    base = parse_sn(baseline_run)
    new = parse_sn(run1)
    g.check(bool(base), "baseline log has no sn rows")
    g.check(bool(new), "new run log has no sn rows")
    violations, shrinks, widened = [], [], 0
    for old_pid, brow in base.items():
        new_pid = old_to_new.get(old_pid, -1)
        nrow = new.get(new_pid)
        if nrow is None:
            violations.append((old_pid, "unit lost its sn row", brow))
            continue
        bound = unit_bound.get(old_pid, 0)
        if bound:
            widened += 1
        chg_allow = remon_chg.get(new_pid, 0)
        if any(n > b + bound for n, b in zip(nrow[:3], brow[:3])):
            violations.append((old_pid, brow, nrow, f"act/body/grp bound +{bound}"))
        elif nrow[3] > brow[3] + chg_allow:
            violations.append((old_pid, ("chg", brow[3]), ("chg", nrow[3]),
                               f"chg bound +{chg_allow}"))
        elif any(n < b for n, b in zip(nrow, brow)):
            shrinks.append((old_pid, brow, nrow))
    g.check(not violations, f"{len(violations)} units exceed their bounds: {violations[:5]}")
    g.note(f"units compared: {len(base)}; edge targets: {len(targets)}; "
           f"widened (W_B>0): {widened}; shrunk: {len(shrinks)}; sample {shrinks[:5]}; "
           f"re-monitored chg allowances (new unit: +chg): {sorted(remon_chg.items())[:5]}")
    return g


def monitored_output_counts(view):
    """Per unit: number of monitored (live fanout row) boundary outputs."""
    counts = defaultdict(int)
    for vid in view["is_boundary"]:
        if not view["fanout_activate"].get(vid):
            continue
        unit = view["unit_of_op"].get(view["producer_of"].get(vid, 0), 0)
        counts[unit] += 1
    return counts


def gate_kind_vchg_bounded(baseline_run, run1, migrated, unit_bound, view,
                           remonitored):
    g = Gate("7.kind-vchg-bounded")
    base, _ = dc.parse_run(Path(baseline_run).read_text(errors="replace"))
    new, _ = dc.parse_run(Path(run1).read_text(errors="replace"))
    g.check(bool(base), "baseline log has no vchg rows")
    g.check(bool(new), "new run log has no vchg rows")
    violations, widened_values = [], 0
    for v in set(base) | set(new):
        bwr, bch = base.get(v, (0, 0))
        nwr, nch = new.get(v, (0, 0))
        if v in migrated:
            if nwr or nch:
                violations.append((v, "migrated but still counted", (bwr, bch), (nwr, nch)))
            continue
        if v in remonitored:
            if (bwr, bch) != (0, 0):
                violations.append((v, "re-monitored but baseline counted",
                                   (bwr, bch), (nwr, nch)))
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
    base_kinds = parse_kinds(baseline_run)
    new_kinds = parse_kinds(run1)
    kind_allowance = defaultdict(int)
    for v, prod in view["producer_of"].items():
        if v in migrated or v not in view["is_boundary"]:
            continue
        kind = view["op_name"].get(prod, "")
        unit = view["unit_of_op"].get(prod, 0)
        kind_allowance[kind] += unit_bound.get(unit, 0)
    kind_violations = []
    for kind, row in new_kinds.items():
        brow = base_kinds.get(kind)
        if brow is None or row[1] > brow[1]:
            kind_violations.append((kind, brow, row))
            continue
        if row[0] > brow[0] + kind_allowance.get(kind, 0):
            kind_violations.append((kind, brow, row, f"wr allowance +{kind_allowance.get(kind, 0)}"))
    g.check(not violations, f"{len(violations)} values violate bounds: {violations[:5]}")
    g.check(not kind_violations, f"{len(kind_violations)} kinds violate bounds: {kind_violations[:5]}")
    g.note(f"values compared: {len(set(base) | set(new))}; migrated (wr must be 0): "
           f"{len(migrated)}; re-monitored (NO00014 replay drift, baseline must "
           f"be (0,0)): {len(remonitored)}; values in widened units: "
           f"{widened_values}; kinds compared: {len(new_kinds)}")
    return g


def gate_mshrink_closure(baseline_run, run1, selected, migrated, unit_bound, view, cycles):
    g = Gate("8.mshrink-closure")
    base, _ = dc.parse_run(Path(baseline_run).read_text(errors="replace"))
    new, _ = dc.parse_run(Path(run1).read_text(errors="replace"))
    closed_form = sum(base.get(c["v"], (0, 0))[0] for c in selected)
    removed_wr = sum(base.get(v, (0, 0))[0] for v in migrated)
    g.check(removed_wr == closed_form,
            f"removed Σwr {removed_wr} != census closed form {closed_form} "
            f"(error {removed_wr - closed_form})")
    base_wr = sum(w for w, _ in base.values())
    new_wr = sum(w for w, _ in new.values())
    outputs = monitored_output_counts(view)
    allowance = sum(unit_bound.get(unit, 0) * count for unit, count in outputs.items())
    added = removed_wr - (base_wr - new_wr)
    g.check(added <= allowance,
            f"added writes {added} exceed the allowance {allowance} "
            f"(removed {removed_wr}, shrink {base_wr - new_wr})")
    if added < 0:
        g.note(f"NO00014 replay bonus: shrink exceeds the migrated-set closed "
               f"form by {-added} writes/run")
    g.note(f"baseline Σwr={base_wr} new Σwr={new_wr} "
           f"removed={removed_wr} ({removed_wr / cycles:.2f}/cyc) "
           f"added_writes={added} allowance={allowance}")
    return g


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-model", type=Path, required=True)
    parser.add_argument("--new-model", type=Path, required=True)
    parser.add_argument("--baseline-run", type=Path, required=True,
                        help="baseline (NO00015) dyn run log: recomputes the "
                             "pricing selection and provides baseline counters")
    parser.add_argument("--run1", type=Path)
    parser.add_argument("--run2", type=Path)
    parser.add_argument("--census", type=Path,
                        help="archived census selected.json for a cross-check "
                             "of the in-process recomputation")
    parser.add_argument("--cycles", type=int, default=100001)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    old_model = json.loads(args.old_model.read_bytes())
    new_model = json.loads(args.new_model.read_bytes())
    old = MappingInfo(old_model)
    new = MappingInfo(new_model)

    view, vchg, selected = recompute_selection(old_model, args.baseline_run)
    if args.census:
        archived = {row["v"] for row in json.loads(args.census.read_text())}
        if archived != {c["v"] for c in selected}:
            raise RuntimeError(
                f"in-process selection {len(selected)} != archived census "
                f"{len(archived)} (symdiff "
                f"{len(archived ^ {c['v'] for c in selected})})")
    unit_flat_ops = {}
    projected, spared = restore_projection(
        selected, view["partitions"], unit_flat_ops)
    unit_bound = widen_bounds(projected, vchg)

    gates = [gate_model_neutral(old_model, new_model)]
    flipped, moved_ops, new_to_old, old_to_new, ambiguous = analyze_migration(old, new)
    gates.append(gate_boundary_closed(old, new, flipped))
    gates.append(gate_membership(old, new, flipped, moved_ops, new_to_old,
                                 old_to_new, ambiguous))
    gates.append(gate_reconciliation(selected, projected, spared, flipped))
    migrated = set(flipped)
    gates.append(gate_fanout_edges(old_model, new_model, old_to_new, migrated))

    if args.run1:
        # NO00014 replay drift: values the old tree de-monitored (no stored
        # row) but the new tree re-monitors (row reappears). Their baseline
        # counters are (0,0) by construction; the new counts are exempt from
        # the growth bounds, and the producer unit's chg bound is widened by
        # the closed-form sum of their run1 ch.
        remonitored = ({row[0] for row in schedule_of(new_model)[2]}
                       - {row[0] for row in schedule_of(old_model)[2]})
        run1_vchg, _ = dc.parse_run(Path(args.run1).read_text(errors="replace"))
        remon_chg = defaultdict(int)
        for v in remonitored:
            unit = new.unit_of_op.get(new.producer.get(v, 0), 0)
            if unit:
                remon_chg[unit] += run1_vchg.get(v, (0, 0))[1]
        targets = {c["unit_b"] for c in projected}
        gates.append(gate_sn_bounded(args.baseline_run, args.run1, old_to_new,
                                     unit_bound, targets, remon_chg))
        gates.append(gate_kind_vchg_bounded(args.baseline_run, args.run1, migrated,
                                            unit_bound, view, remonitored))
        gates.append(gate_mshrink_closure(args.baseline_run, args.run1, selected,
                                          migrated, unit_bound, view, args.cycles))
    if args.run1 and args.run2:
        gates.append(gate_determinism(args.run1, args.run2))

    ok = all(g.ok for g in gates)
    lines = ["# NO00019 edge-completion migration gates", ""]
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
