#!/usr/bin/env python3
"""NO00021 bucket dynamic price: dynamic cost attribution of pass-product buckets.

NO00020 (accepted) identified three op buckets that exist only on the GrhSIM-IR
side (no gsim counterpart), attributed by name classifiers:

  * ``(reg-to-mem)`` -- ``__reg_to_mem_<digits>`` array states and their access
    machinery (grhsim.reg-to-mem pass products),
  * ``(packed)``     -- ``packed_bits_<digits>`` word states and their
    merge/extract ops (grhsim.pack-bit-registers pass products),
  * ``(events)``     -- ``__event_*`` edge-bookkeeping states and their guard
    ops (ingest-level event histories).

This script prices them dynamically with deterministic calibers only (no new
simulation runs), linking two archives of one production build:

  1. production checkpoint -> per-op bucket attribution (same code path as
     NO00020's analyze_grhsim), op residence classification (compute
     supernode / commit task / detached) and unit membership;
  2. dyn run log           -> per-unit body/chg fires ([grhsim-dyn] sn rows),
     per-value change counters ([grhsim-vchg] rows), commit rows and totals.

Metrics (pre-registered in pdocs/NO00021-*.md):
  M-bexec   per-bucket dynamic op execs/cycle (compute domain, closed form:
            sum over units body(unit) * bucket ops in unit);
  M-bmon    per-bucket monitored-value count, sum wr / sum ch per cycle;
  M-bwake   per-bucket change-driven consumer-unit wakes (upper-bound proxy:
            sum over values ch(v) * distinct consumer compute units);
  M-bcommit commit-domain per-bucket static op composition + global counters.

Gates:
  G1 every op is attributed to exactly one of the three buckets or (other);
  G2 per-bucket static op counts equal NO00020's report values exactly;
  G3 sn unit keys == checkpoint compute unit keys (no orphans), sum chg ==
     totals.grp_fire exactly, residence counts close to totalOps;
  G4 vchg value ids in range, sum wr equals the archived M-shrink integer;
  G5 two script runs over the same inputs are byte identical (checked by the
     caller comparing summary.json/summary.md).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from grhsim_demonitor_census import view_from_model  # noqa: E402
from grhsim_kind_cost_census import (  # noqa: E402
    EXEC_COMPUTE,
    compute_task_units,
    load_dyn_fires,
)
from grhsim_gsim_module_compare import (  # noqa: E402
    ANON_MODULE,
    DEAD_MODULE,
    EVENTS_MODULE,
    PACKED_MODULE,
    REG2MEM_MODULE,
    STATE_READ_KINDS,
    is_generated_value_name,
    module_of_path,
    module_of_state_name,
    propagate_value_owners,
)

BUCKET_MODULES = (REG2MEM_MODULE, PACKED_MODULE, EVENTS_MODULE)
OTHER_BUCKET = "(other)"

VCHG_LINE = re.compile(r"^\[grhsim-vchg\] v (\d+) wr=(\d+) ch=(\d+)")
COMMIT_LINE = re.compile(r"^\[grhsim-dyn\] commit (\d+) ent=(\d+)")


def log(msg):
    print(f"[grhsim-bucket-dyn-price] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Bucket attribution (mirrors grhsim_gsim_module_compare.analyze_grhsim)
# ---------------------------------------------------------------------------


def bucket_of_module(module):
    """Collapse an attributed module to a pass-product bucket or (other)."""
    return module if module in BUCKET_MODULES else OTHER_BUCKET


def attribute_op_modules(model):
    """Per-op module attribution, same code path as NO00020 analyze_grhsim.

    Returns (op_module, value_named_module, owner, aux) where op_module[oid]
    is the attributed module string, and aux carries op/state/value tables
    needed downstream (kinds, operands, results, refs, names).
    """
    strings = model["strings"]
    states = model["states"]
    values = model["values"]
    operations = model["operations"]

    state_name = [""] * (len(states) + 1)
    for row in states:
        state_name[row[0]] = strings[row[1] - 1]

    n_values = len(values)
    value_name = [""] * (n_values + 1)
    for row in values:
        value_name[row[0]] = strings[row[2] - 1] if row[2] else ""

    n_ops = len(operations)
    op_kind = [""] * (n_ops + 1)
    op_operands = [None] * (n_ops + 1)
    op_results = [None] * (n_ops + 1)
    op_refs = [None] * (n_ops + 1)
    for op in operations:
        oid = op[0]
        op_kind[oid] = strings[op[1] - 1]
        op_operands[oid] = op[4]
        op_results[oid] = op[5]
        op_refs[oid] = op[6]

    inputs = [strings[row[1] - 1] for row in model["inputs"]]
    outputs = [strings[row[1] - 1] for row in model["outputs"]]

    value_named_module = [None] * (n_values + 1)
    for vid in range(1, n_values + 1):
        name = value_name[vid]
        if not is_generated_value_name(name):
            value_named_module[vid] = module_of_state_name(name)

    io_names = {index + 1: name for index, name in enumerate(inputs)}
    for pos in range(1, n_ops + 1):
        if op_kind[pos] in STATE_READ_KINDS:
            for res in op_results[pos]:
                if value_named_module[res] is None:
                    ref = op_refs[pos][0] if op_refs[pos] else None
                    target_module = None
                    if isinstance(ref, list) and len(ref) >= 2 and isinstance(ref[1], int):
                        if ref[0] == "state" and 0 < ref[1] < len(state_name):
                            target_module = module_of_state_name(state_name[ref[1]])
                        elif ref[0] == "input" and ref[1] in io_names:
                            target_module = module_of_path(io_names[ref[1]], "$")
                    if target_module is None:
                        target_module = module_of_path(value_name[res], "$")
                    value_named_module[res] = target_module

    consumers_of = defaultdict(list)
    for pos in range(1, n_ops + 1):
        for operand in op_operands[pos]:
            consumers_of[operand].append(pos)

    io_names.update({index + 1: name for index, name in enumerate(outputs)})

    def sink_module_of(pos):
        for ref in op_refs[pos] or ():
            if not isinstance(ref, list) or len(ref) < 2 or not isinstance(ref[1], int):
                continue
            if ref[0] == "state" and 0 < ref[1] < len(state_name):
                return module_of_state_name(state_name[ref[1]])
            if ref[0] in ("input", "output") and ref[1] in io_names:
                return module_of_path(io_names[ref[1]], "$")
        return None

    owner = propagate_value_owners(
        n_values,
        lambda vid: value_named_module[vid],
        lambda vid: consumers_of.get(vid, ()),
        lambda pos: op_results[pos],
        sink_module_of=sink_module_of,
    )

    op_module = [None] * (n_ops + 1)
    for pos in range(1, n_ops + 1):
        module = None
        for res in op_results[pos]:
            named = value_named_module[res]
            if named is not None:
                module = named
                break
        if module is None:
            for ref in op_refs[pos] or ():
                if isinstance(ref, list) and len(ref) >= 2 and ref[0] == "state" \
                        and isinstance(ref[1], int) and 0 < ref[1] < len(state_name):
                    module = module_of_state_name(state_name[ref[1]])
                    break
        if module is None:
            for res in op_results[pos]:
                module = owner[res]
                if module:
                    break
        if module is None or module == DEAD_MODULE:
            for operand in op_operands[pos]:
                named = value_named_module[operand]
                if named is not None:
                    module = named
                    break
        if not module:
            module = ANON_MODULE
        op_module[pos] = module

    aux = {
        "state_name": state_name,
        "value_name": value_name,
        "op_kind": op_kind,
        "op_operands": op_operands,
        "op_results": op_results,
        "op_refs": op_refs,
        "consumers_of": consumers_of,
        "n_values": n_values,
        "n_ops": n_ops,
    }
    return op_module, value_named_module, owner, aux


# ---------------------------------------------------------------------------
# Residence classification (compute supernode / commit task / detached)
# ---------------------------------------------------------------------------


def schedule_task_rows(schedule):
    for numa in schedule[0]:
        for core in numa[1]:
            for row in core[1]:
                yield row


def classify_residence(model, view):
    """Assign every op to ('compute', unit), ('commit', task) or ('detached', None).

    Compute residence uses the schedule walk mirrored in
    grhsim_kind_cost_census.compute_task_units (task -> word -> unit
    supernode). Commit tasks hold their ops one level up: walk the task's
    partition subtree and collect op ids directly.
    """
    partitions = view["partitions"]
    payload = model["mappings"][0][-1]
    schedule = payload[4]
    compute_tasks, all_task_ids, unit_to_task = compute_task_units(partitions, schedule)
    compute_units = {unit for _task, units in compute_tasks for unit in units}

    residence = {}
    for unit in compute_units:
        for op in view["unit_ops"][unit]:
            residence[op] = ("compute", unit)

    commit_task_ops = {}
    for row in schedule_task_rows(schedule):
        task_id, part, execution = row[0], row[1], row[3]
        if execution == EXEC_COMPUTE:
            continue
        ops = []
        stack = [part]
        seen = set()
        while stack:
            node = partitions[stack.pop()]
            for child in node[4]:
                if child not in seen:
                    seen.add(child)
                    stack.append(child)
            ops.extend(node[5])
        commit_task_ops[task_id] = ops
        for op in ops:
            if op not in residence:
                residence[op] = ("commit", task_id)

    return {
        "residence": residence,
        "compute_tasks": compute_tasks,
        "compute_units": compute_units,
        "all_task_ids": all_task_ids,
        "commit_task_ops": commit_task_ops,
    }


# ---------------------------------------------------------------------------
# Dyn log parsing
# ---------------------------------------------------------------------------


def parse_vchg_and_commit(run_path):
    """Parse [grhsim-vchg] rows and [grhsim-dyn] commit rows."""
    vchg = {}
    commit = {}
    with open(run_path) as handle:
        for line in handle:
            match = VCHG_LINE.match(line)
            if match:
                vchg[int(match.group(1))] = (int(match.group(2)), int(match.group(3)))
                continue
            match = COMMIT_LINE.match(line)
            if match:
                commit[int(match.group(1))] = int(match.group(2))
    return vchg, commit


# ---------------------------------------------------------------------------
# Metric assembly (pure functions, unit-testable)
# ---------------------------------------------------------------------------


def compute_exec_metrics(view, aux, op_bucket, residence_info, body):
    """Full execs join with per-(bucket, kind) resolution."""
    unit_ops = view["unit_ops"]
    op_kind = aux["op_kind"]
    compute_units = residence_info["compute_units"]
    per_bucket = Counter()
    per_bucket_kind = Counter()
    total = 0
    orphans = []
    missing_units = []
    for unit, fires in body.items():
        if unit not in compute_units:
            orphans.append(unit)
            continue
        ops = unit_ops.get(unit)
        if ops is None:
            missing_units.append(unit)
            continue
        bucket_counts = Counter()
        kind_counts = Counter()
        for op in ops:
            bucket_counts[op_bucket[op]] += 1
            kind_counts[(op_bucket[op], op_kind[op])] += 1
        for bucket, count in bucket_counts.items():
            per_bucket[bucket] += fires * count
        for key, count in kind_counts.items():
            per_bucket_kind[key] += fires * count
        total += fires * len(ops)
    silent_units = sorted(compute_units - set(body.keys()))
    return {
        "per_bucket": per_bucket,
        "per_bucket_kind": per_bucket_kind,
        "total": total,
        "orphan_sn_units": sorted(orphans),
        "missing_units": sorted(missing_units),
        "silent_units": silent_units,
    }


def monitored_by_bucket(value_name, value_named_module, owner, vchg, n_values):
    """Per-bucket monitored-value aggregates from [grhsim-vchg] rows."""
    per_bucket = {}
    out_of_range = []
    for vid, (wr, ch) in vchg.items():
        if vid <= 0 or vid > n_values:
            out_of_range.append(vid)
            continue
        module = value_named_module[vid]
        if module is None:
            module = owner[vid]
        bucket = bucket_of_module(module)
        entry = per_bucket.setdefault(bucket, {"values": 0, "wr": 0, "ch": 0})
        entry["values"] += 1
        entry["wr"] += wr
        entry["ch"] += ch
    total_wr = sum(pair[0] for pair in vchg.values())
    total_ch = sum(pair[1] for pair in vchg.values())
    return per_bucket, total_wr, total_ch, sorted(out_of_range)


def wakes_by_bucket(residence, consumers_of, vchg, bucket_of_value):
    """Upper-bound wake proxy: sum over values ch(v) x consumer compute units."""
    per_bucket = Counter()
    per_bucket_commit = Counter()
    total = 0
    for vid, (_wr, ch) in vchg.items():
        if not ch:
            continue
        units = set()
        commit_tasks = set()
        for pos in consumers_of.get(vid, ()):
            where = residence.get(pos)
            if where is None:
                continue
            if where[0] == "compute":
                units.add(where[1])
            else:
                commit_tasks.add(where[1])
        bucket = bucket_of_value(vid)
        wakes = ch * len(units)
        per_bucket[bucket] += wakes
        per_bucket_commit[bucket] += ch * len(commit_tasks)
        total += wakes
    return per_bucket, per_bucket_commit, total


def static_bucket_counts(op_module, op_kind, n_ops):
    per_bucket = Counter()
    per_bucket_kind = Counter()
    for pos in range(1, n_ops + 1):
        bucket = bucket_of_module(op_module[pos])
        per_bucket[bucket] += 1
        per_bucket_kind[(bucket, op_kind[pos])] += 1
    return per_bucket, per_bucket_kind


def residence_counts(residence, op_bucket, n_ops):
    per_bucket_res = Counter()
    detached = []
    for op in range(1, n_ops + 1):
        where = residence.get(op)
        res = where[0] if where else "detached"
        if res == "detached":
            detached.append(op)
        per_bucket_res[(op_bucket[op], res)] += 1
    return per_bucket_res, detached


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def fmt_int(value):
    return f"{value:,}"


def render_summary_md(summary):
    lines = []
    lines.append("# NO00021 bucket dynamic price summary")
    lines.append("")
    gates = summary["gates"]
    lines.append("## Gates")
    lines.append("")
    lines.append("| gate | result | detail |")
    lines.append("|---|---|---|")
    for name in sorted(gates):
        ok, detail = gates[name]
        lines.append(f"| {name} | {'PASS' if ok else 'FAIL'} | {detail} |")
    lines.append("")
    cycles = summary["inputs"]["cycles"]
    mbexec = summary["metrics"]["M-bexec"]
    total = mbexec["total_execs"]
    lines.append("## M-bexec (compute-domain dynamic execs/cycle)")
    lines.append("")
    lines.append("| bucket | static ops | execs/run | execs/cycle | share |")
    lines.append("|---|---|---|---|---|")
    for bucket in (*BUCKET_MODULES, OTHER_BUCKET):
        row = mbexec["buckets"].get(bucket)
        if row is None:
            continue
        share = row["execs"] / total if total else 0.0
        lines.append(
            f"| {bucket} | {fmt_int(row['static_ops'])} | {fmt_int(row['execs'])} "
            f"| {row['execs'] / cycles:,.1f} | {share:.4%} |")
    lines.append(f"| **total** | {fmt_int(mbexec['total_static_ops'])} "
                 f"| {fmt_int(total)} | {total / cycles:,.1f} | 100% |")
    lines.append("")
    lines.append("### Top (bucket, kind) execs/cycle")
    lines.append("")
    lines.append("| bucket | kind | execs/cycle |")
    lines.append("|---|---|---|")
    for key, execs in mbexec["top_bucket_kind"]:
        lines.append(f"| {key[0]} | {key[1]} | {execs / cycles:,.1f} |")
    lines.append("")
    mbmon = summary["metrics"]["M-bmon"]
    lines.append("## M-bmon (monitored boundary values)")
    lines.append("")
    lines.append("| bucket | values | wr/cycle | wr share | ch/cycle | ch share |")
    lines.append("|---|---|---|---|---|---|")
    for bucket in (*BUCKET_MODULES, OTHER_BUCKET):
        row = mbmon["buckets"].get(bucket, {"values": 0, "wr": 0, "ch": 0})
        lines.append(
            f"| {bucket} | {fmt_int(row['values'])} | {row['wr'] / cycles:,.1f} "
            f"| {row['wr'] / mbmon['total_wr']:.4%} | {row['ch'] / cycles:,.1f} "
            f"| {row['ch'] / mbmon['total_ch']:.4%} |")
    lines.append("")
    mbwake = summary["metrics"]["M-bwake"]
    lines.append("## M-bwake (change-driven consumer-unit wakes, upper-bound proxy)")
    lines.append("")
    lines.append("| bucket | wakes/cycle | share | commit-side ch x tasks/cycle |")
    lines.append("|---|---|---|---|")
    for bucket in (*BUCKET_MODULES, OTHER_BUCKET):
        row = mbwake["buckets"].get(bucket, {"wakes": 0, "commit_wakes": 0})
        share = row["wakes"] / mbwake["total_wakes"] if mbwake["total_wakes"] else 0.0
        lines.append(
            f"| {bucket} | {row['wakes'] / cycles:,.1f} | {share:.4%} "
            f"| {row['commit_wakes'] / cycles:,.1f} |")
    lines.append("")
    mbcommit = summary["metrics"]["M-bcommit"]
    lines.append("## M-bcommit (commit-domain static composition + global counters)")
    lines.append("")
    lines.append("| bucket | commit-resident ops |")
    lines.append("|---|---|")
    for bucket in (*BUCKET_MODULES, OTHER_BUCKET):
        lines.append(f"| {bucket} | {fmt_int(mbcommit['static_ops'].get(bucket, 0))} |")
    lines.append("")
    lines.append("### Top (bucket, kind) commit-resident static ops")
    lines.append("")
    lines.append("| bucket | kind | ops |")
    lines.append("|---|---|---|")
    for key, count in mbcommit["top_bucket_kind"]:
        lines.append(f"| {key[0]} | {key[1]} | {fmt_int(count)} |")
    lines.append("")
    lines.append("### Global dyn counters (context)")
    lines.append("")
    lines.append("| counter | value | per cycle |")
    lines.append("|---|---|---|")
    for key, value in sorted(mbcommit["totals"].items()):
        lines.append(f"| {key} | {fmt_int(value)} | {value / cycles:,.1f} |")
    lines.append("")
    lines.append(f"commit rows: {fmt_int(mbcommit['commit_rows'])}; "
                 f"median ent {mbcommit['commit_ent_median']:,}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="production checkpoint JSON")
    parser.add_argument("--run", required=True, help="dyn run log with [grhsim-dyn]/[grhsim-vchg] rows")
    parser.add_argument("--output", required=True, help="output directory")
    parser.add_argument("--cycles", type=int, default=100001)
    parser.add_argument("--expect-ops", type=json.loads, default=None,
                        help="JSON object {bucket: static op count} for G2")
    parser.add_argument("--expect-vchg-wr", type=int, default=None,
                        help="archived sum wr integer for G4")
    args = parser.parse_args(argv)

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    log(f"loading model {args.model}")
    model = json.loads(Path(args.model).read_bytes())
    op_module, value_named_module, owner, aux = attribute_op_modules(model)
    view = view_from_model(model)
    residence_info = classify_residence(model, view)
    log(f"model: ops={aux['n_ops']:,} values={aux['n_values']:,} "
        f"compute_units={len(residence_info['compute_units']):,} "
        f"commit_tasks={len(residence_info['commit_task_ops']):,}")

    body, chg, totals = load_dyn_fires(args.run)
    vchg, commit_rows = parse_vchg_and_commit(args.run)
    log(f"dyn: sn units={len(body):,} vchg values={len(vchg):,} commit rows={len(commit_rows):,}")

    op_bucket = [OTHER_BUCKET] * (aux["n_ops"] + 1)
    for pos in range(1, aux["n_ops"] + 1):
        op_bucket[pos] = bucket_of_module(op_module[pos])

    static_counts, static_kind = static_bucket_counts(
        op_module, aux["op_kind"], aux["n_ops"])
    res_counts, detached = residence_counts(
        residence_info["residence"], op_bucket, aux["n_ops"])
    exec_metrics = compute_exec_metrics(
        view, aux, op_bucket, residence_info, body)
    mon_buckets, total_wr, total_ch, oor = monitored_by_bucket(
        aux["value_name"], value_named_module, owner, vchg, aux["n_values"])

    def bucket_of_value(vid):
        module = value_named_module[vid]
        if module is None:
            module = owner[vid]
        return bucket_of_module(module)

    wake_buckets, wake_commit, total_wakes = wakes_by_bucket(
        residence_info["residence"], aux["consumers_of"], vchg, bucket_of_value)

    gates = {}
    # G1: every op attributed to exactly one bucket or (other) — construction
    # guarantees a single label; verify no op missed attribution.
    unattributed = sum(1 for pos in range(1, aux["n_ops"] + 1)
                       if op_module[pos] is None)
    gates["G1_attribution_closed"] = (
        unattributed == 0, [unattributed])
    # G2: static bucket op counts vs NO00020 report values.
    if args.expect_ops is not None:
        diffs = {bucket: [static_counts.get(bucket, 0), expect]
                 for bucket, expect in args.expect_ops.items()
                 if static_counts.get(bucket, 0) != expect}
        gates["G2_static_counts"] = (not diffs, diffs if diffs else
                                     {b: static_counts.get(b, 0)
                                      for b in args.expect_ops})
    # G3: dynamic closure.
    chg_total = sum(chg.get(unit, 0) for unit in residence_info["compute_units"])
    gates["G3_sn_keys"] = (
        not exec_metrics["orphan_sn_units"] and not exec_metrics["missing_units"],
        {"orphans": exec_metrics["orphan_sn_units"][:5],
         "missing": exec_metrics["missing_units"][:5]})
    gates["G3_chg_closure"] = (
        chg_total == totals.get("grp_fire"),
        [chg_total, totals.get("grp_fire")])
    res_sum = sum(res_counts.values())
    gates["G3_residence_closure"] = (
        res_sum == aux["n_ops"],
        [res_sum, aux["n_ops"], len(detached)])
    # G4: monitored-domain reconciliation.
    gates["G4_vchg_range"] = (not oor, oor[:5])
    if args.expect_vchg_wr is not None:
        gates["G4_wr_closure"] = (
            total_wr == args.expect_vchg_wr, [total_wr, args.expect_vchg_wr])

    cycles = args.cycles
    commit_static = Counter()
    commit_static_kind = Counter()
    for (bucket, res), count in res_counts.items():
        if res == "commit":
            commit_static[bucket] += count
    for task, ops in residence_info["commit_task_ops"].items():
        for op in ops:
            if residence_info["residence"].get(op, (None,))[0] == "commit":
                commit_static_kind[(op_bucket[op], aux["op_kind"][op])] += 1

    commit_ents = sorted(commit_rows.values())
    summary = {
        "inputs": {
            "model": str(args.model),
            "run": str(args.run),
            "cycles": cycles,
            "expect_ops": args.expect_ops,
            "expect_vchg_wr": args.expect_vchg_wr,
        },
        "gates": gates,
        "metrics": {
            "M-bexec": {
                "buckets": {
                    bucket: {"static_ops": static_counts.get(bucket, 0),
                             "execs": exec_metrics["per_bucket"].get(bucket, 0)}
                    for bucket in (*BUCKET_MODULES, OTHER_BUCKET)
                },
                "total_static_ops": aux["n_ops"],
                "total_execs": exec_metrics["total"],
                "silent_compute_units": len(exec_metrics["silent_units"]),
                "top_bucket_kind": [
                    (list(key), value)
                    for key, value in sorted(
                        exec_metrics["per_bucket_kind"].items(),
                        key=lambda item: (-item[1], item[0]))[:25]
                ],
            },
            "M-bmon": {
                "buckets": mon_buckets,
                "total_values": len(vchg),
                "total_wr": total_wr,
                "total_ch": total_ch,
            },
            "M-bwake": {
                "buckets": {
                    bucket: {"wakes": wake_buckets.get(bucket, 0),
                             "commit_wakes": wake_commit.get(bucket, 0)}
                    for bucket in (*BUCKET_MODULES, OTHER_BUCKET)
                },
                "total_wakes": total_wakes,
            },
            "M-bcommit": {
                "static_ops": dict(commit_static),
                "top_bucket_kind": [
                    (list(key), value)
                    for key, value in sorted(
                        commit_static_kind.items(),
                        key=lambda item: (-item[1], item[0]))[:25]
                ],
                "commit_rows": len(commit_rows),
                "commit_ent_median": (commit_ents[len(commit_ents) // 2]
                                      if commit_ents else 0),
                "totals": totals,
            },
        },
    }
    # Reference convenience views (per-cycle) for the report body.
    summary["derived"] = {
        "execs_per_cycle": {
            bucket: exec_metrics["per_bucket"].get(bucket, 0) / cycles
            for bucket in (*BUCKET_MODULES, OTHER_BUCKET)
        },
        "wr_per_cycle": {
            bucket: mon_buckets.get(bucket, {}).get("wr", 0) / cycles
            for bucket in (*BUCKET_MODULES, OTHER_BUCKET)
        },
        "wakes_per_cycle": {
            bucket: wake_buckets.get(bucket, 0) / cycles
            for bucket in (*BUCKET_MODULES, OTHER_BUCKET)
        },
        "total_execs_per_cycle": exec_metrics["total"] / cycles,
    }

    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "summary.md").write_text(render_summary_md(summary), encoding="utf-8")
    failed = [name for name, (ok, _detail) in gates.items() if not ok]
    log(f"gates: {'all PASS' if not failed else 'FAILED ' + ','.join(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
