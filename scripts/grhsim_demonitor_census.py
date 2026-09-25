#!/usr/bin/env python3
"""NO00014 static census: redundant change-detection elimination candidates.

A monitored boundary value v (compute fanout row with activate targets) is
redundantly monitored when every consumer unit B in its fanout activate list
is already activated by the change events of every non-constant operand of
v's producer op X: v-change implies some operand w changed (pure compute),
and B in activate(fanout(w)) means that same change fires B in the same
round. Topological order (A < B, since B consumes v) guarantees B reads the
fresh v. v's detection/publish is then redundant for activation and the
whole fanout row can be dropped (write/store of v remains; the value is
still materialized cross-unit).

Safety conditions (all static, dependency-driven; no dynamic data influences
eligibility):
  - v: Boundary storage, 1..64b two-state logic, not pinned (input shadow /
    input fanout source), not an event-gate value.
  - X = producer(v): core.compute.* single result, no objectRefs, not
    constant, not expr, owned by a supernode A.
  - fanout(v): arm list empty (no event-domain arming), every activate
    target is a supernode B != A whose ops are all side-effect free
    (core.compute.* / core.state.read / core.state.memRead only -- state
    reads are stable within a cycle, so re-firing such a unit with identical
    inputs is idempotent; units with system/dpi/io/state-write ops would
    observe their fire count shrinking).
  - for every operand w of X: producer(w) is core.compute.constant (free,
    inlined at read sites) or B in activate(fanout(w)) for every B.
  - port-arm exclusion: v is not among the first three operands of any
    core.state.regWrite / core.state.latchWrite op (armed commit ports
    consume v's change flag; conservative proxy for portArmTargets_).

Inputs
  --model      production mapped checkpoint JSON (NO00013 flow archive)
  --run        NO00013 dyn run log ([grhsim-vchg] + [grhsim-dyn] sn rows;
               optional, only for the saving re-score)
  --output     directory for summary.md / summary.json
  --cycles     guest cycles (default 100001)

Census output
  eligible     values whose full fanout row can be dropped (all targets
               covered); saving estimate = wr_v * (K_DETECT + K_SET)
  partial      values where some but not all targets are covered (only
               fanout-set bits removable; informational)
  rejections   bucketed reasons
"""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grhsim_vchg_profile import (SN_LINE, VCHG_LINE,  # noqa: E402
                                 coldness_bucket, width_bucket)

KIND_SUPER = 3
STORAGE_BOUNDARY = 2
CONSTANT_KIND = "core.compute.constant"
EXPR_KIND = "core.compute.expr"
COMPUTE_PREFIX = "core.compute."
SAFE_NON_COMPUTE = {"core.state.read", "core.state.memRead"}
PORT_ARM_OWNERS = {"core.state.regWrite", "core.state.latchWrite"}

K_DETECT = 3
K_SET = 1


def view_from_model(model):
    strings = model["strings"]
    types = {t[0]: t for t in model["types"]}
    payload = model["mappings"][0][-1]
    partitions = {p[0]: p for p in payload[2]}
    value_slots = payload[3][3]
    schedule = payload[4]

    view = {
        "op_name": {}, "op_operands": {}, "op_results": {}, "op_has_refs": {},
        "op_refs": {},
        "producer_of": {}, "consumers_of": defaultdict(list),
        "unit_of_op": {}, "unit_ops": defaultdict(list),
        "is_boundary": set(), "event_gate_values": set(), "width": {},
        "partitions": partitions,
    }
    view["is_boundary"] = {vid for vid, slot in enumerate(value_slots, start=1)
                           if slot[1] == STORAGE_BOUNDARY}
    for row in partitions.values():
        gate = row[6] if len(row) > 6 else []
        if gate:
            for event in gate[1]:
                view["event_gate_values"].add(event[0])

    for pid, part in partitions.items():
        if part[2] != KIND_SUPER:
            continue
        stack = [pid]
        while stack:
            node = partitions[stack.pop()]
            stack.extend(node[4])
            for op_id in node[5]:
                view["unit_of_op"][op_id] = pid
                view["unit_ops"][pid].append(op_id)

    for op in model["operations"]:
        oid, name_idx, _, _, operands, results, refs, _ = op[:8]
        view["op_name"][oid] = strings[name_idx - 1]
        view["op_operands"][oid] = operands
        view["op_results"][oid] = results
        view["op_has_refs"][oid] = bool(refs)
        view["op_refs"][oid] = refs
        for v in results:
            view["producer_of"][v] = oid
        for v in operands:
            view["consumers_of"][v].append(oid)

    for v in model["values"]:
        t = types[v[1]]
        view["width"][v[0]] = t[3] if t[2] == "logic" else 0

    fanout_activate = {}
    fanout_arm = {}
    for row in schedule[2]:
        fanout_activate[row[0]] = set(row[1])
        fanout_arm[row[0]] = set(row[2])
    view["fanout_activate"] = fanout_activate
    view["fanout_arm"] = fanout_arm
    input_sources = {row[0] for row in schedule[1]}
    input_shadow_values = {row[0] for row in schedule[5]}
    # layout runtime slots: [kind, owner, value, edge, offset]
    runtime_values = {row[2] for row in payload[3][4] if len(row) > 2 and row[2]}
    view["pinned"] = input_sources | input_shadow_values | runtime_values

    port_arm_values = set()
    for op in model["operations"]:
        if view["op_name"][op[0]] in PORT_ARM_OWNERS:
            port_arm_values.update(op[4][:3])
    view["port_arm_values"] = port_arm_values

    # commit state fanout: state id -> set of armed/activated partitions
    commit_fanout = defaultdict(set)
    for row in schedule[3]:
        commit_fanout[row[0]].update(row[1])
        commit_fanout[row[0]].update(row[2])
    view["commit_fanout"] = commit_fanout

    # Emit read-alias mirror (cpu_emit.cpp planReadAliases): a core.state.read
    # result inside an ActivityDrivenCompute unit whose state is quiescence
    # projected, which no op outside compute units and no event gate reads, and
    # whose type matches the state type is emitted as a direct alias of the
    # state slot -- its computeSupernodeFanout row is dead code at runtime and
    # cannot carry an added activation edge (NO00015 correctness fix).
    compute_ops = set()
    for numa in schedule[0]:
        for core in numa[1]:
            for _task_id, part, _waits, execution in core[1]:
                if execution != 0:  # CpuExecution::ActivityDrivenCompute
                    continue
                for word in partitions[part][4]:
                    for unit in partitions[word][4]:
                        for node in partitions[unit][4]:
                            compute_ops.update(partitions[node][5])
    snapshot = set()
    for op in model["operations"]:
        if op[0] not in compute_ops:
            snapshot.update(op[4])
    snapshot |= view["event_gate_values"]
    projected = set()
    for word_index, word in enumerate(schedule[8]):
        w = word
        while w:
            lsb = w & -w
            projected.add(word_index * 64 + lsb.bit_length() - 1)
            w ^= lsb
    value_type = {v[0]: v[1] for v in model["values"]}
    state_type = {s[0]: s[2] for s in model["states"]}  # [id, name, type, origin]
    aliased = set()
    dpi_produced = set()
    for op in model["operations"]:
        oid = op[0]
        name = view["op_name"][oid]
        if name == "core.dpi.call":
            dpi_produced.update(op[5])
            continue
        if name != "core.state.read" or oid not in compute_ops or not op[5] or not op[6]:
            continue
        ref = op[6][0]
        sid = ref[1] if isinstance(ref, list) else ref
        result = op[5][0]
        tid = value_type[result]
        if (sid in projected and result not in snapshot
                and types[tid][2] == "logic" and tid == state_type.get(sid)):
            aliased.add(result)
    view["aliased_read_values"] = aliased
    view["dpi_produced"] = dpi_produced
    return view


def load_model(model_path):
    return view_from_model(json.loads(Path(model_path).read_bytes()))


def side_effect_free(view, unit):
    for op in view["unit_ops"].get(unit, ()):
        name = view["op_name"].get(op, "")
        if not name.startswith(COMPUTE_PREFIX) and name not in SAFE_NON_COMPUTE:
            return False
    return True


def covered_targets(view, vid, xop, targets):
    """For each target unit, decide coverage by X's operands. Returns
    (covered set, first failure reason for uncovered)."""
    operands = view["op_operands"].get(xop, ())
    fanout_activate = view["fanout_activate"]
    covered, uncovered = set(), set()
    for unit in targets:
        ok = True
        for w in operands:
            prod = view["producer_of"].get(w, 0)
            if prod and view["op_name"].get(prod, "") == CONSTANT_KIND:
                continue
            if unit not in fanout_activate.get(w, ()):
                ok = False
                break
        (covered if ok else uncovered).add(unit)
    return covered, uncovered


def census(view):
    eligible, partial, rejections = [], [], Counter()
    port_arm_but_eligible = []
    state_cover = []
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
        xop = view["producer_of"].get(vid, 0)
        if not xop:
            rejections["no_producer"] += 1
            continue
        kind = view["op_name"].get(xop, "")
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
        is_compute = kind.startswith(COMPUTE_PREFIX) and kind != EXPR_KIND
        is_state_read = kind in SAFE_NON_COMPUTE
        if not is_compute and not is_state_read:
            rejections["producer_kind"] += 1
            continue
        if is_compute:
            covered, uncovered = covered_targets(view, vid, xop, targets)
            if uncovered:
                rejections["operand_not_covering"] += 1
                if covered:
                    partial.append({"v": vid, "kind": kind, "width": width,
                                    "unit_a": unit_a,
                                    "covered": sorted(covered), "uncovered": sorted(uncovered)})
                continue
        else:
            # state.read / memRead producer: v changes only when the referenced
            # state commits; every target unit must be armed by the same state
            # via commit fanout (i.e. contain its own read of that state).
            refs = state_refs_of(view, xop)
            if len(refs) != 1:
                rejections["state_refs"] += 1
                continue
            armed = view["commit_fanout"].get(refs[0], set())
            if not targets <= armed:
                rejections["state_not_covering"] += 1
                continue
        row = {"v": vid, "op": xop, "kind": kind, "unit_a": unit_a,
               "width": width, "targets": sorted(targets)}
        if vid in view["port_arm_values"]:
            port_arm_but_eligible.append(row)
            rejections["port_arm"] += 1
            continue
        (eligible if is_compute else state_cover).append(row)
    # Cascade fixpoint: v's removal is only safe if every non-constant operand
    # of X(v) keeps its own fanout row -- otherwise v's producer unit A (and
    # the consumer coverage) could lose the activation that keeps v fresh.
    # Iterate to the greatest fixpoint so chains of candidates are resolved.
    pre_fixpoint = len(eligible)
    eligible = cascade_fixpoint(view, eligible)
    return eligible, partial, rejections, port_arm_but_eligible, state_cover, pre_fixpoint


def cascade_fixpoint(view, eligible):
    """Greatest fixpoint of the survival rule: a removed value's non-constant
    producer operands must not themselves be removed."""
    by_v = {e["v"]: e for e in eligible}
    surviving = set(by_v)
    while True:
        drop = set()
        for vid in surviving:
            xop = by_v[vid]["op"]
            for w in view["op_operands"].get(xop, ()):
                prod = view["producer_of"].get(w, 0)
                if prod and view["op_name"].get(prod, "") == CONSTANT_KIND:
                    continue
                if w in surviving:
                    drop.add(vid)
                    break
        if not drop:
            return [by_v[v] for v in sorted(surviving)]
        surviving -= drop


def state_refs_of(view, op):
    # objectRefs of the producer op; checkpoint operation row field 6.
    return list(view["op_refs"].get(op, ()))


def parse_run(text):
    vchg, body = {}, {}
    for line in text.splitlines():
        m = VCHG_LINE.match(line)
        if m:
            vchg[int(m.group(1))] = (int(m.group(2)), int(m.group(3)))
            continue
        m = SN_LINE.match(line)
        if m:
            body[int(m.group(1))] = int(m.group(3))
    return vchg, body


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cycles", type=int, default=100001)
    args = parser.parse_args(argv)

    view = load_model(args.model)
    eligible, partial, rejections, port_arm_rows, state_cover, pre_fixpoint = census(view)

    monitored = sum(1 for v in view["is_boundary"] if view["fanout_activate"].get(v))
    out = {"boundary": len(view["is_boundary"]), "monitored_rows": monitored,
           "eligible": len(eligible), "state_cover": len(state_cover),
           "cascade_trimmed": pre_fixpoint - len(eligible),
           "partial": len(partial), "port_arm_but_eligible": len(port_arm_rows),
           "rejections": dict(rejections),
           "by_kind": dict(Counter(e["kind"] for e in eligible + state_cover)),
           "by_width": dict(Counter(width_bucket(e["width"]) for e in eligible + state_cover))}
    lines = ["# NO00014 de-monitor census", "",
             f"boundary values: {out['boundary']}",
             f"monitored (fanout row with activate targets): {monitored}",
             f"eligible compute full-cover: {out['eligible']} (cascade fixpoint trimmed {out['cascade_trimmed']} candidates)",
             f"eligible state-cover: {out['state_cover']}",
             f"  (counts are post-cascade-fixpoint: operands of removed values keep their rows)",
             f"partial-cover: {out['partial']}",
             f"port_arm-but-otherwise-eligible: {out['port_arm_but_eligible']}",
             "", "## rejections"]
    lines += [f"- {k}: {v}" for k, v in sorted(rejections.items())]
    lines += ["", "## eligible by kind"]
    lines += [f"- {k}: {v}" for k, v in sorted(out["by_kind"].items(), key=lambda kv: -kv[1])]
    lines += ["", "## eligible by width"]
    lines += [f"- {k}: {v}" for k, v in sorted(out["by_width"].items())]

    if args.run:
        vchg, body = parse_run(args.run.read_text(errors="replace"))
        total_wr = sum(w for w, _ in vchg.values())

        def wr_of(rows):
            return sum(vchg.get(r["v"], (0, 0))[0] for r in rows)

        save_wr = wr_of(eligible)
        state_wr = wr_of(state_cover)
        part_wr = wr_of(partial)
        pa_wr = wr_of(port_arm_rows)
        out["total_wr_pc"] = total_wr / args.cycles
        out["eligible_wr_pc"] = save_wr / args.cycles
        out["state_cover_wr_pc"] = state_wr / args.cycles
        out["eligible_wr_frac"] = (save_wr + state_wr) / total_wr if total_wr else 0.0
        out["partial_wr_pc"] = part_wr / args.cycles
        out["port_arm_wr_pc"] = pa_wr / args.cycles
        out["save_instr_pc"] = (save_wr + state_wr) / args.cycles * (K_DETECT + K_SET)
        lines += ["", "## dynamic re-score (estimate only)",
                  f"- total monitored wr: {out['total_wr_pc']:,.1f}/cycle",
                  f"- eligible compute wr removed: {out['eligible_wr_pc']:,.1f}/cycle",
                  f"- eligible state-cover wr removed: {out['state_cover_wr_pc']:,.1f}/cycle",
                  f"- combined = {out['eligible_wr_frac'] * 100:.2f}% of monitored",
                  f"- saving estimate (x{K_DETECT + K_SET} instr/wr):"
                  f" {out['save_instr_pc']:,.1f} instr/cycle",
                  f"- partial-cover wr (set-only): {out['partial_wr_pc']:,.1f}/cycle",
                  f"- port_arm-but-eligible wr (excluded): {out['port_arm_wr_pc']:,.1f}/cycle"]
        agg = defaultdict(lambda: {"n": 0, "wr": 0})
        for e in eligible + state_cover:
            wr, ch = vchg.get(e["v"], (0, 0))
            key = (e["kind"], width_bucket(e["width"]),
                   coldness_bucket(ch / wr if wr else 0.0))
            agg[key]["n"] += 1
            agg[key]["wr"] += wr
        top = sorted(agg.items(), key=lambda kv: -kv[1]["wr"])[:20]
        out["by_class"] = {str(k): {"n": v["n"], "wr_pc": v["wr"] / args.cycles}
                           for k, v in top}
        lines += ["", "## top classes by wr/cycle"]
        lines += [f"- {k}: n={v['n']} wr={v['wr'] / args.cycles:,.1f}/cycle" for k, v in top]

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(json.dumps(out, indent=1))
    (args.output / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
