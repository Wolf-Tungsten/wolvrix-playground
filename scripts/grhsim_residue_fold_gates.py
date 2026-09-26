#!/usr/bin/env python3
"""NO00016 pre-registered semantic gates for post-schedule residue folding.

Compares a baseline (NO00015) mapped checkpoint against a residue-folded one
and, when diagnostic run logs are provided, checks the dynamic counter rules.
Gates (all must PASS):

1. endpoint-determinism-difftest
                           run1 endpoint fields equal the pre-registered
                           baseline (instrCnt=240349 cycleCnt=99996
                           guest=100001 pc=0x80000c0c); no difftest failure
                           markers; run1/run2 [grhsim-vchg]/[grhsim-dyn]
                           streams identical when --run2 is given
2. counters-projection     per-key equality of [grhsim-dyn] sn rows (unit
                           act/body/grp/chg), kind rows, [grhsim-vchg] rows and
                           the totals line between baseline run and run1,
                           except deltas that equal, closed-form, the dynamic
                           projection of the statically gate-3-verified dropped
                           fanout rows (NO00014 replay over the rewired operand
                           graph, preregistration amendment 2/3): the vanished
                           vchg set must equal the dropped-row value set; per
                           producer kind, wr decrease == silent increase == sum
                           of baseline vchg wr over the dropped values, and ch
                           decrease == sum of baseline vchg ch; sn act/body/grp
                           exactly equal everywhere and chg may only strictly
                           decrease, only in producer units of dropped values;
                           totals equal except grp_fire, whose decrease must
                           equal the sum of sn chg decreases. With no dropped
                           rows this degenerates to exact equality.
3. checkpoint-closure      top-level sections other than mappings/operations
                           are JSON-equal; operations equal the census replay
                           (every unselected consumer's operands r->resolve(src)
                           for exactly the census rewire set, recomputed
                           in-process from the old model); partition tree and
                           mapping stage/root equal; layout value-slot kinds
                           unchanged; every schedule field except
                           computeSupernodeFanout is equal and the new schedule
                           carries exactly one extra trailing field (the fold
                           list). computeSupernodeFanout rows may differ only
                           as the refresh-time NO00014/NO00015 replay over the
                           rewired operand graph: a dropped row's producer
                           operands were rewired and every non-constant
                           operand activates every old activate target in the
                           new rows (the row is redundant); a grown row's
                           source is a rewire destination, activate targets
                           only grow, arm targets unchanged.
4. fold-set-exact          the schedule fold list == the in-process census
                           selection (and == --census-selected keys when given)
5. neutral-identical       knob-off reemit directory is byte-identical to the
                           reference flow directory (excluding *.o/*.a)
6. hdlbits-161-162         GrhSIM-IR hdlbits logs: every DUT passed except the
                           pre-registered DUT=105 failure (error text must
                           match); 162 DUTs seen, 161 passed
7. dynamic-closed-form     sum over folded ops of their unit's baseline body
                           fires == census dynamic value (and ==
                           --expected-dynamic when given)

Gates 3-4 always run; 1-2 and 7 need --baseline-run/--run1; 5 needs
--neutral-dir/--neutral-ref; 6 needs --hdlbits-log.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grhsim_demonitor_census as dc  # noqa: E402
import grhsim_residue_fold_census as rc  # noqa: E402
from grhsim_demonitor_gates import (  # noqa: E402
    Gate, EXPECTED_ENDPOINT, parse_endpoint, parse_sn, parse_kinds, key_stream)
from grhsim_vchg_profile import SN_LINE  # noqa: E402

DIFFTEST_BAD = re.compile(r"(?i)difftest.*(mismatch|fail|abort|error)|HIT BAD TRAP")
TOTALS_LINE = re.compile(r"^\[grhsim-dyn] totals (.*)$")
DUT_BANNER = re.compile(r"^==== Running GrhSIM DUT=(\d+) ====")
DUT_RUN = re.compile(r"^\[RUN] DUT=(\d+) ")  # individual run_hdlbits_grhsim target marker
DUT_PASS = re.compile(r"^\[GrhTB] dut_(\d+) passed(?::| )")
DUT105_ERROR = ("used-bits dangling value 101 produced by core.compute.sliceStatic "
                "consumed by op 105 core.compute.concat")
HDLBITS_DUTS = 162
HDLBITS_KNOWN_FAILURE = "105"


def schedule_of(model):
    return model["mappings"][0][-1][4]


def census_selection(old_model):
    view = dc.view_from_model(old_model)
    view["operations"] = old_model["operations"]
    selected, reject, rewire = rc.select(view, rc.tables_from_model(old_model))
    return view, selected, reject, rewire


def resolve(rewire, value):
    seen = set()
    while value in rewire:
        if value in seen:
            raise ValueError(f"rewire cycle at value {value}")
        seen.add(value)
        value = rewire[value]
    return value


def gate_endpoint_determinism(run1, run2):
    g = Gate("1.endpoint-determinism-difftest")
    endpoint = parse_endpoint(run1)
    g.check(endpoint == EXPECTED_ENDPOINT,
            f"endpoint {endpoint} != pre-registered {EXPECTED_ENDPOINT}")
    bad = [line for line in Path(run1).read_text(errors="replace").splitlines()
           if DIFFTEST_BAD.search(line)]
    g.check(not bad, f"difftest failure markers in run1: {bad[:3]}")
    if run2:
        s1, s2 = key_stream(run1), key_stream(run2)
        g.check(s1 == s2, f"run1/run2 key streams differ ({len(s1)} vs {len(s2)} lines)")
        e2 = parse_endpoint(run2)
        g.check(e2 == endpoint, f"run2 endpoint {e2} != run1 {endpoint}")
        bad2 = [line for line in Path(run2).read_text(errors="replace").splitlines()
                if DIFFTEST_BAD.search(line)]
        g.check(not bad2, f"difftest failure markers in run2: {bad2[:3]}")
    g.note(f"endpoint {endpoint}")
    return g


def parse_totals(path):
    totals = {}
    for line in key_stream(path):
        m = TOTALS_LINE.match(line)
        if m:
            for pair in m.group(1).split():
                key, _, value = pair.partition("=")
                totals[key] = int(value)
    return totals


def parse_kinds_full(path):
    kinds = {}
    for line in key_stream(path):
        m = re.match(r"^\[grhsim-dyn] kind (\S+) wr=(\d+) ch=(\d+) silent=(\d+)$", line)
        if m:
            kinds[m.group(1)] = (int(m.group(2)), int(m.group(3)), int(m.group(4)))
    return kinds


def gate_counters_projection(baseline_run, run1, old_model, new_model, view):
    """Amendment-3 rule: exact per-key counter equality except deltas that
    equal, closed-form, the dynamic projection of the statically
    gate-3-verified dropped fanout rows (see the module docstring)."""
    g = Gate("2.counters-projection")
    dropped = ({r[0] for r in schedule_of(old_model)[2]}
               - {r[0] for r in schedule_of(new_model)[2]})
    strings = old_model["strings"]
    producer = {}
    for row in old_model["operations"]:
        for res in row[5]:
            producer[res] = row[0]
    kind_of_op = {row[0]: strings[row[1] - 1] for row in old_model["operations"]}
    unit_of_op = view["unit_of_op"]
    drop_units = {unit_of_op.get(producer.get(v)) for v in dropped}
    drop_units.discard(None)

    base_v = dc.parse_run(Path(baseline_run).read_text(errors="replace"))[0]
    new_v = dc.parse_run(Path(run1).read_text(errors="replace"))[0]
    g.check(bool(base_v), "baseline log has no vchg rows")
    g.check(bool(new_v), "run1 log has no vchg rows")
    drop_kind_wr = Counter()
    drop_kind_ch = Counter()
    for v in dropped:
        kind = kind_of_op.get(producer.get(v))
        wr, ch = base_v.get(v, (0, 0))
        drop_kind_wr[kind] += wr
        drop_kind_ch[kind] += ch

    missing = set(base_v) - set(new_v)
    extra = sorted(set(new_v) - set(base_v))
    g.check(missing == dropped,
            f"vchg vanished set != dropped fanout-row set: {len(missing)} vanished vs "
            f"{len(dropped)} dropped (only-vanished {sorted(missing - dropped)[:5]}, "
            f"only-dropped {sorted(dropped - missing)[:5]})")
    g.check(not extra, f"vchg: {len(extra)} new keys: {extra[:5]}")
    changed = [k for k in base_v.keys() & new_v.keys() if base_v[k] != new_v[k]]
    g.check(not changed, f"vchg: {len(changed)} surviving keys changed: {changed[:5]}")
    g.note(f"vchg: {len(missing)} vanished == dropped rows; "
           f"{len(base_v.keys() & new_v.keys())} survivors equal")

    base_k, new_k = parse_kinds_full(baseline_run), parse_kinds_full(run1)
    g.check(set(base_k) == set(new_k),
            f"kind key sets differ: {sorted(set(base_k) ^ set(new_k), key=str)[:5]}")
    changed_kinds = [k for k in base_k if k in new_k and base_k[k] != new_k[k]]
    bad_kind = [k for k in changed_kinds if k not in drop_kind_wr]
    g.check(not bad_kind, f"kind changes outside dropped-value producer kinds: "
                          f"{bad_kind[:5]}")
    for k in changed_kinds:
        if k in bad_kind:
            continue
        (wo, co, so), (wn, cn, sl) = base_k[k], new_k[k]
        g.check(wo > wn and wo - wn == sl - so == drop_kind_wr[k],
                f"kind {k}: wr decrease {wo - wn} / silent increase {sl - so} != "
                f"dropped-row wr sum {drop_kind_wr[k]}")
        g.check(co >= cn and co - cn == drop_kind_ch[k],
                f"kind {k}: ch decrease {co - cn} != dropped-row ch sum {drop_kind_ch[k]}")
    for k in drop_kind_wr:
        if k not in changed_kinds and (drop_kind_wr[k] or drop_kind_ch[k]):
            g.check(False, f"kind {k}: expected delta from dropped rows "
                           f"(wr {drop_kind_wr[k]}, ch {drop_kind_ch[k]}) but counters "
                           f"are unchanged")
    g.note(f"kind: {len(changed_kinds)} keys changed, all mirror the dropped-row "
           f"projection; {len(base_k) - len(changed_kinds)} keys equal")

    base_s, new_s = parse_sn(baseline_run), parse_sn(run1)
    g.check(set(base_s) == set(new_s),
            f"sn key sets differ: {sorted(set(base_s) ^ set(new_s))[:5]}")
    changed_sn = [k for k in base_s if k in new_s and base_s[k] != new_s[k]]
    bad_sn = [k for k in changed_sn if k not in drop_units]
    g.check(not bad_sn, f"sn changes outside dropped-value producer units: "
                        f"{bad_sn[:5]}")
    dchg = 0
    for k in changed_sn:
        o, n = base_s[k], new_s[k]
        g.check(o[:3] == n[:3] and o[3] > n[3],
                f"sn {k}: non-chg field changed or chg did not decrease: {o} -> {n}")
        dchg += o[3] - n[3]
    g.note(f"sn: {len(changed_sn)} keys changed (chg-only decreases inside "
           f"dropped-value producer units, total -{dchg}); "
           f"{len(base_s) - len(changed_sn)} keys equal")

    base_t, new_t = parse_totals(baseline_run), parse_totals(run1)
    g.check(set(base_t) == set(new_t),
            f"totals key sets differ: {sorted(set(base_t) ^ set(new_t))[:5]}")
    changed_t = [k for k in base_t if k in new_t and base_t[k] != new_t[k]]
    bad_t = [k for k in changed_t if k != "grp_fire"]
    g.check(not bad_t, f"totals keys other than grp_fire changed: {bad_t[:5]}")
    if "grp_fire" in changed_t:
        g.check(base_t["grp_fire"] - new_t["grp_fire"] == dchg,
                f"grp_fire decrease {base_t['grp_fire'] - new_t['grp_fire']} != "
                f"sum of sn chg decreases {dchg}")
    elif dchg:
        g.check(False, f"sn chg decreases total {dchg} but grp_fire is unchanged")
    g.note(f"totals: grp_fire -{dchg} == sn chg decrease; "
           f"{len(base_t) - len(changed_t)} keys equal")
    return g


def gate_checkpoint_closure(old_model, new_model, selected, rewire):
    g = Gate("3.checkpoint-closure")
    old_keys = {k for k in old_model if k not in ("mappings", "operations")}
    new_keys = {k for k in new_model if k not in ("mappings", "operations")}
    g.check(old_keys == new_keys, f"top-level key sets differ: {old_keys ^ new_keys}")
    for key in sorted(old_keys & new_keys):
        g.check(old_model[key] == new_model[key], f"section '{key}' differs")

    # operations: replay the census rewiring over the old rows
    expected = []
    for row in old_model["operations"]:
        oid = row[0]
        if oid in selected:
            expected.append(row)
            continue
        operands = [resolve(rewire, v) if v in rewire else v for v in row[4]]
        expected.append([oid, row[1], row[2], row[3], operands, row[5], row[6]]
                        + list(row[7:]))
    new_ops = new_model["operations"]
    g.check(len(expected) == len(new_ops),
            f"operation count differs: {len(expected)} vs {len(new_ops)}")
    if len(expected) == len(new_ops):
        diffs = [(e[0], e, n) for e, n in zip(expected, new_ops) if e != n]
        g.check(not diffs, f"{len(diffs)} operation rows differ beyond the rewire set: "
                           f"{[d[0] for d in diffs[:5]]}")

    old_payload = old_model["mappings"][0][-1]
    new_payload = new_model["mappings"][0][-1]
    g.check(old_payload[0] == new_payload[0], "mapping stage differs")
    g.check(old_payload[1] == new_payload[1], "partition root differs")
    g.check(old_payload[2] == new_payload[2], "partition tree differs")
    old_slots = old_payload[3][3]
    new_slots = new_payload[3][3]
    g.check(len(old_slots) == len(new_slots), "layout value slot count differs")
    flipped = [i + 1 for i, (o, n) in enumerate(zip(old_slots, new_slots)) if o[1] != n[1]]
    g.check(not flipped, f"{len(flipped)} value slots flipped storage kind: {flipped[:5]}")
    if old_payload[3] != new_payload[3]:
        g.note("data layout payload differs beyond slot kinds (operand-derived "
               "helper read caches / densification recomputed)")

    old_sched = schedule_of(old_model)
    new_sched = schedule_of(new_model)
    g.check(len(new_sched) == len(old_sched) + 1,
            f"schedule field count {len(old_sched)} -> {len(new_sched)} (expected +1)")
    for i in range(min(len(old_sched), len(new_sched))):
        if i == 2:  # computeSupernodeFanout: replay-checked below
            continue
        g.check(new_sched[i] == old_sched[i], f"schedule field {i} differs")
    check_fanout_replay(g, old_model, new_model, rewire)
    g.note(f"schedule fields {len(old_sched)} -> {len(new_sched)}; "
           f"fold list length {len(new_sched[-1]) if len(new_sched) > len(old_sched) else 0}")
    return g


def check_fanout_replay(g, old_model, new_model, rewire):
    """computeSupernodeFanout may change only as the refresh-time replay of
    the NO00014 de-monitoring fixpoint / NO00015 completion additions over
    the rewired operand graph (see gate 3 in the module docstring)."""
    old_rows = {r[0]: r for r in schedule_of(old_model)[2]}
    new_rows = {r[0]: r for r in schedule_of(new_model)[2]}
    only_old = sorted(set(old_rows) - set(new_rows))
    only_new = sorted(set(new_rows) - set(old_rows))
    changed = sorted(k for k in set(old_rows) & set(new_rows) if old_rows[k] != new_rows[k])
    if not (only_old or only_new or changed):
        return
    strings = old_model["strings"]
    const_results = {res for row in old_model["operations"]
                     if strings[row[1] - 1] == "core.compute.constant"
                     for res in row[5]}
    producer_of = {}
    for row in old_model["operations"]:
        for res in row[5]:
            producer_of[res] = row[0]
    old_ops = {row[0]: row for row in old_model["operations"]}
    new_ops = {row[0]: row for row in new_model["operations"]}
    rewire_targets = set(rewire.values())
    for target in list(rewire.values()):
        while target in rewire:
            target = rewire[target]
            rewire_targets.add(target)

    bad_drop = []
    for v in only_old:
        xid = producer_of.get(v)
        x_old, x_new = old_ops.get(xid), new_ops.get(xid)
        if x_old is None or x_new is None or x_old[4] == x_new[4]:
            bad_drop.append(v)  # not attributable to the rewiring
            continue
        redundant = True
        for w in x_new[4]:
            if w in const_results:
                continue
            row = new_rows.get(w)
            activates = set(row[1]) if row else set()
            if any(t not in activates for t in old_rows[v][1]):
                redundant = False
                break
        if not redundant:
            bad_drop.append(v)
    g.check(not bad_drop, f"{len(bad_drop)} dropped fanout rows not explained by the "
                          f"NO00014 replay over rewired operands: {bad_drop[:5]}")

    bad_grow = []
    for s in only_new + changed:
        old_row = old_rows.get(s, [s, [], []])
        new_row = new_rows.get(s)
        if (s not in rewire_targets or old_row[2] != new_row[2]
                or not set(old_row[1]) <= set(new_row[1])):
            bad_grow.append(s)
    g.check(not bad_grow, f"{len(bad_grow)} grown fanout rows violate the "
                          f"rewire-destination growth rule: {bad_grow[:5]}")
    g.note(f"fanout rows dropped {len(only_old)} (NO00014 replay), "
           f"grown {len(only_new) + len(changed)} (rewire destinations)")


def gate_fold_set(new_model, selected, census_selected_path):
    g = Gate("4.fold-set-exact")
    fold_field = schedule_of(new_model)[-1]
    expected = sorted(selected)
    g.check(fold_field == expected,
            f"schedule fold list != census selection ({len(fold_field)} vs {len(expected)})")
    if census_selected_path:
        recorded = {int(k) for k in json.loads(Path(census_selected_path).read_text())}
        g.check(set(fold_field) == recorded,
                f"schedule fold set != census selected.json "
                f"(only-schedule {sorted(set(fold_field) - recorded)[:5]}, "
                f"only-census {sorted(recorded - set(fold_field))[:5]})")
    g.note(f"folded ops: {len(fold_field)}")
    return g


def gate_neutral_identical(neutral_dir, reference_dir):
    g = Gate("5.neutral-identical")
    neutral = {p.relative_to(neutral_dir): p for p in Path(neutral_dir).rglob("*")
               if p.is_file() and p.suffix not in (".o", ".a")}
    reference = {p.relative_to(reference_dir): p for p in Path(reference_dir).rglob("*")
                 if p.is_file() and p.suffix not in (".o", ".a")}
    only_neutral = sorted(set(neutral) - set(reference))
    only_reference = sorted(set(reference) - set(neutral))
    g.check(not only_neutral, f"{len(only_neutral)} files only in neutral: {only_neutral[:5]}")
    g.check(not only_reference, f"{len(only_reference)} files only in reference: "
                                f"{only_reference[:5]}")
    diffs = [rel for rel in neutral.keys() & reference.keys()
             if neutral[rel].read_bytes() != reference[rel].read_bytes()]
    g.check(not diffs, f"{len(diffs)} files differ: {diffs[:5]}")
    g.note(f"files compared: {len(neutral.keys() & reference.keys())}")
    return g


def gate_hdlbits(log_paths):
    g = Gate("6.hdlbits-161-162")
    seen, passed = set(), set()
    failure_text = ""
    for path in log_paths:
        current = None
        for line in Path(path).read_text(errors="replace").splitlines():
            m = DUT_BANNER.search(line) or DUT_RUN.search(line)
            if m:
                current = m.group(1)
                seen.add(current)
            m = DUT_PASS.search(line)
            if m:
                passed.add(m.group(1))
            if current == HDLBITS_KNOWN_FAILURE and DUT105_ERROR in line:
                failure_text = line
    g.check(len(seen) == HDLBITS_DUTS,
            f"saw {len(seen)} DUT banners, expected {HDLBITS_DUTS}")
    failed = seen - passed
    g.check(failed == {HDLBITS_KNOWN_FAILURE},
            f"failed DUTs {sorted(failed)} != pre-registered ['{HDLBITS_KNOWN_FAILURE}']")
    g.check(bool(failure_text), "DUT=105 failure did not carry the pre-registered error text")
    g.note(f"passed {len(passed)}/{len(seen)}; known failure DUT=105: {failure_text[:80]}")
    return g


def gate_dynamic_closed_form(old_model, new_model, baseline_run, selected, expected_dynamic, cycles):
    g = Gate("7.dynamic-closed-form")
    view = dc.view_from_model(old_model)
    body = {}
    for line in key_stream(baseline_run):
        m = SN_LINE.match(line)
        if m:
            body[int(m.group(1))] = int(m.group(3))
    g.check(bool(body), "baseline log has no sn rows")
    per_class = Counter()
    for oid, cls in selected.items():
        per_class[cls] += body.get(view["unit_of_op"].get(oid, 0), 0)
    total = sum(per_class.values())
    # the folded model's schedule list must price to the same total
    fold_field = schedule_of(new_model)[-1]
    refold = sum(body.get(view["unit_of_op"].get(oid, 0), 0) for oid in fold_field)
    g.check(refold == total, f"schedule fold list prices to {refold} != census {total}")
    if expected_dynamic is not None:
        g.check(total == expected_dynamic,
                f"closed-form dynamic {total} != pre-registered {expected_dynamic}")
    g.note(f"dynamic execs removed: {total} ({total / cycles:.1f}/cycle); "
           f"classes: {dict(per_class.most_common())}")
    return g


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-model", type=Path, required=True)
    parser.add_argument("--new-model", type=Path, required=True)
    parser.add_argument("--baseline-run", type=Path,
                        help="baseline (NO00015) dyn run log: counter equality and "
                             "closed-form dynamic pricing baselines")
    parser.add_argument("--run1", type=Path)
    parser.add_argument("--run2", type=Path)
    parser.add_argument("--census-selected", type=Path,
                        help="census selected.json artifact for gate 4 cross-check")
    parser.add_argument("--neutral-dir", type=Path,
                        help="knob-off reemit flow directory (gate 5)")
    parser.add_argument("--neutral-ref", type=Path,
                        help="reference flow directory for the neutral byte comparison")
    parser.add_argument("--hdlbits-log", type=Path, action="append", default=[],
                        help="GrhSIM-IR hdlbits log (repeatable)")
    parser.add_argument("--expected-dynamic", type=int,
                        help="pre-registered dynamic removal total (gate 7)")
    parser.add_argument("--cycles", type=int, default=100001)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    old_model = json.loads(args.old_model.read_bytes())
    new_model = json.loads(args.new_model.read_bytes())
    _view, selected, _reject, rewire = census_selection(old_model)

    gates = [gate_checkpoint_closure(old_model, new_model, selected, rewire),
             gate_fold_set(new_model, selected, args.census_selected)]
    if args.run1:
        gates.append(gate_endpoint_determinism(args.run1, args.run2))
    if args.baseline_run and args.run1:
        gates.append(gate_counters_projection(args.baseline_run, args.run1,
                                              old_model, new_model, _view))
    if args.neutral_dir and args.neutral_ref:
        gates.append(gate_neutral_identical(args.neutral_dir, args.neutral_ref))
    if args.hdlbits_log:
        gates.append(gate_hdlbits(args.hdlbits_log))
    if args.baseline_run:
        gates.append(gate_dynamic_closed_form(old_model, new_model, args.baseline_run,
                                              selected, args.expected_dynamic, args.cycles))

    ok = all(g.ok for g in gates)
    lines = ["# NO00016 residue-fold gates", ""]
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
