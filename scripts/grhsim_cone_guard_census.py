"""Cone-coverage census for compute supernodes (input-precision cone guards).

For every compute supernode (KIND_SUPER partition), model its boundary inputs as
activation tokens:
  - external operand values (produced outside the unit or producerless),
  - source ops that read external objects (state.read / input.read / memRead-like).
Ops with no operands (const-like) form the unconditional base that always executes.

Two coverage models per activation with changed-token set C:
  - support model (lower bound): base + union of forward cones of C
    (ops whose value could change; needs intermediate persistence to be correct).
  - ancestor model (frame-safe): base + union of ancestor cones of triggered
    outputs (outputs whose support intersects C); downward-closed, so plain
    per-op guards with output-reachability masks are correct in a fresh frame.

Endpoint units (hosting core.system.*/core.dpi.* ops) are force-activated every
round and must always run full bodies; they are reported separately and excluded
from the guard-eligible pool.
"""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import random
import re


KIND_SUPER = 3
STORAGE_BOUNDARY = 2
SN_LINE = re.compile(r"^\[grhsim-dyn] sn (\d+) act=(\d+) body=(\d+) grp=(\d+) chg=(\d+)$")


def is_source_op(name):
    low = name.lower()
    if low.startswith(("state.", "input.")):
        return "read" in low
    return "memread" in low or low.endswith(".read")


def is_endpoint_op(name):
    low = name.lower()
    return low.startswith(("core.system.", "core.dpi.", "system.", "dpi."))


def quantiles(values):
    if not values:
        return "n=0"
    data = sorted(values)
    n = len(data)
    return (f"n={n} min={data[0]:.4f} p50={data[n // 2]:.4f} p90={data[int(n * 0.9)]:.4f} "
            f"p99={data[int(n * 0.99)]:.4f} max={data[-1]:.4f} mean={sum(data) / n:.4f}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True, help="mapped xiangshan_grhsim_ir.json")
    parser.add_argument("--dynlog", type=Path, default=None,
                        help="emu log with [grhsim-dyn] per-unit counters for body weighting")
    parser.add_argument("--samples", type=int, default=200,
                        help="union-coverage samples per unit for k>=2")
    parser.add_argument("--out", type=Path, default=None, help="optional per-unit JSON dump")
    args = parser.parse_args()

    model = json.loads(args.model.read_bytes())
    ops = model["operations"]
    strings = model["strings"]
    payload = model["mappings"][0][-1]
    partitions = {part[0]: part for part in payload[2]}
    value_slots = payload[3][3]

    producer = {}
    for op in ops:
        for value in op[5]:
            producer[value] = op[0]

    body_by_unit, act_by_unit = {}, {}
    if args.dynlog:
        for line in args.dynlog.read_text(errors="replace").splitlines():
            if match := SN_LINE.match(line):
                pid = int(match[1])
                act_by_unit[pid] = int(match[2])
                body_by_unit[pid] = int(match[3])

    rng = random.Random(20260924)
    name_tally = Counter()
    rows = []
    for pid, part in partitions.items():
        if part[2] != KIND_SUPER:
            continue
        members = []
        stack = [pid]
        while stack:
            node = partitions[stack.pop()]
            members.extend(node[5])
            stack.extend(node[4])
        member_set = set(members)
        names = [strings[ops[op_id - 1][1] - 1] for op_id in members]
        name_tally.update(names)
        endpoint = any(is_endpoint_op(name) for name in names)
        # Event-semantic units (history samples / edge-guarded effects / object
        # writes) cannot be cone-guarded: such effects have no boundary-output
        # path and would be skipped permanently.
        eventful = endpoint
        if not eventful:
            for op_id, name in zip(members, names):
                op = ops[op_id - 1]
                if not is_source_op(name) and op[6]:
                    eventful = True
                    break
                for param in op[7]:
                    if strings[param[0] - 1] == "event_edges":
                        eventful = True
                        break
                if eventful:
                    break

        consumers = defaultdict(list)
        intra_producer = {}
        ext_values = set()
        src_ops = []
        base_ops = []
        output_ops = []
        for op_id, name in zip(members, names):
            operands = ops[op_id - 1][4]
            if is_source_op(name):
                src_ops.append(op_id)
            elif not operands:
                base_ops.append(op_id)
            for value in operands:
                consumers[value].append(op_id)
                if producer.get(value) not in member_set:
                    ext_values.add(value)
            for value in ops[op_id - 1][5]:
                intra_producer[value] = op_id
                if value_slots[value - 1][1] == STORAGE_BOUNDARY:
                    output_ops.append(op_id)
        output_ops = sorted(set(output_ops))

        def forward_cone(start):
            seen = set()
            stack = list(start)
            while stack:
                current = stack.pop()
                if current in seen:
                    continue
                seen.add(current)
                for value in ops[current - 1][5]:
                    stack.extend(consumers.get(value, ()))
            return seen

        def ancestor_cone(output):
            seen = set()
            stack = [output]
            while stack:
                current = stack.pop()
                if current in seen:
                    continue
                seen.add(current)
                for value in ops[current - 1][4]:
                    up = intra_producer.get(value)
                    if up is not None:
                        stack.append(up)
            return seen

        tokens = sorted(ext_values) + src_ops
        cones = []
        for value in sorted(ext_values):
            cones.append(forward_cone(consumers[value]))
        for op_id in src_ops:
            cones.append(forward_cone([op_id]))

        n_ops = len(members)
        base = set(base_ops)
        anc = {output: ancestor_cone(output) for output in output_ops}
        support = {output: set() for output in output_ops}
        for token_idx, cone in enumerate(cones):
            for output in output_ops:
                if output in cone:
                    support[output].add(token_idx)
        # Per-op output-reachability mask (guard region proxy) and dead ops.
        outs_of = defaultdict(set)
        for output, opset in anc.items():
            for op_id in opset:
                outs_of[op_id].add(output)
        dead_ops = n_ops - len(set(outs_of) | base)
        # Guard regions: adjacent ops (emission order) sharing the same outs-mask.
        adj_guards = 0
        prev_key = None
        for op_id in members:
            key = (frozenset(outs_of.get(op_id, ())), op_id in base)
            if key != prev_key:
                adj_guards += 1
                prev_key = key

        def coverage_draws(k, model_kind):
            if not tokens or len(tokens) < k:
                return []
            draws = []
            if k == 1:
                trials = (range(len(tokens)), True)
            else:
                trials = (range(min(args.samples, 20 * len(tokens))), False)
            for draw in trials[0]:
                picked = [draw] if trials[1] else rng.sample(range(len(tokens)), k)
                chosen = set(picked)
                executed = set(base)
                if model_kind == "support":
                    for token_idx in chosen:
                        executed |= cones[token_idx]
                else:
                    triggered = {output for output in output_ops if support[output] & chosen}
                    if model_kind == "ancestor":
                        for output in triggered:
                            executed |= anc[output]
                    else:  # region: whole outs-mask class runs if any output triggered
                        for op_id in members:
                            if outs_of.get(op_id, set()) & triggered:
                                executed.add(op_id)
                draws.append(len(executed) / n_ops)
            return draws

        kinds = ("support", "ancestor", "region")
        cov = {kind: {k: coverage_draws(k, kind) for k in (1, 2, 3, 4, 5, 6)} for kind in kinds}

        def mean(values):
            return sum(values) / len(values) if values else None

        rows.append({
            "pid": pid,
            "ops": n_ops,
            "tokens": len(tokens),
            "inputs": len(ext_values),
            "src_ops": len(src_ops),
            "base_ops": len(base),
            "outputs": len(output_ops),
            "endpoint": endpoint,
            "eventful": eventful,
            "act": act_by_unit.get(pid, 0),
            "body": body_by_unit.get(pid, 0),
            "dead_frac": dead_ops / n_ops,
            "adj_guards": adj_guards,
            "cov_support": {k: mean(cov["support"][k]) for k in (1, 2, 3, 4, 5, 6)},
            "cov_ancestor": {k: mean(cov["ancestor"][k]) for k in (1, 2, 3, 4, 5, 6)},
            "cov_region": {k: mean(cov["region"][k]) for k in (1, 2, 3, 4, 5, 6)},
        })

    eventful_rows = [row for row in rows if row["eventful"]]
    eligible = [row for row in rows if not row["eventful"]]
    endpoint_rows = [row for row in rows if row["endpoint"]]

    def weighted_residual(pool, field, key):
        num = den = 0
        for row in pool:
            cov = row[field][key]
            if cov is None:
                cov = 1.0
            num += row["body"] * cov * row["ops"]
            den += row["body"] * row["ops"]
        return num / den if den else None

    print(f"units={len(rows)} eligible={len(eligible)} eventful={len(eventful_rows)} "
          f"(of which endpoint={len(endpoint_rows)})")
    print(f"source op kinds seen: "
          f"{ {name: count for name, count in name_tally.items() if is_source_op(name)} }")
    print(f"endpoint op kinds seen: "
          f"{ {name: count for name, count in name_tally.items() if is_endpoint_op(name)} }")
    dyn_total = sum(row["body"] * row["ops"] for row in rows)
    dyn_endpoint = sum(row["body"] * row["ops"] for row in endpoint_rows)
    dyn_eventful = sum(row["body"] * row["ops"] for row in eventful_rows)
    print(f"dynOps total={dyn_total} endpoint share={100.0 * dyn_endpoint / max(dyn_total, 1):.2f}% "
          f"eventful share={100.0 * dyn_eventful / max(dyn_total, 1):.2f}%")
    print(f"endpoint units: act={sum(row['act'] for row in endpoint_rows)} "
          f"body={sum(row['body'] for row in endpoint_rows)}")

    for label, pool in (("eligible", eligible), ("all", rows)):
        print(f"\n== {label} pool ({len(pool)} units) ==")
        print("tokens/unit: " + quantiles([row["tokens"] for row in pool]))
        print("outputs/unit: " + quantiles([row["outputs"] for row in pool]))
        print("base ops frac: " + quantiles([row["base_ops"] / row["ops"] for row in pool]))
        print("dead ops frac: " + quantiles([row["dead_frac"] for row in pool]))
        print("adjacent guard runs/unit: " + quantiles([row["adj_guards"] for row in pool]))
        cov1 = [row["cov_support"][1] for row in pool if row["cov_support"][1] is not None]
        print("single-token support coverage (unit-mean): " + quantiles(cov1))
        cov1a = [row["cov_ancestor"][1] for row in pool if row["cov_ancestor"][1] is not None]
        print("single-token ancestor coverage (unit-mean): " + quantiles(cov1a))
        for field in ("cov_support", "cov_ancestor", "cov_region"):
            for k in (1, 2, 3, 4, 5, 6):
                residual = weighted_residual(pool, field, k)
                if residual is not None:
                    print(f"predicted dynOps residual {field} k={k}: "
                          f"{100.0 * residual:.2f}% (body-weighted)")

    # Static unit selection: guard only units whose static single-token ancestor
    # coverage is below a threshold (dependency-cone feature, no dynamic input).
    print("\n== static unit selection (selector: cov_ancestor k=1 <= T) ==")
    for threshold in (0.2, 0.3, 0.4, 0.5, 0.7, 1.01):
        selected = [row for row in eligible
                    if row["cov_ancestor"][1] is not None and row["cov_ancestor"][1] <= threshold]
        dyn_selected = sum(row["body"] * row["ops"] for row in selected)
        dyn_eligible = sum(row["body"] * row["ops"] for row in eligible)
        line = (f"T={threshold:.2f}: units={len(selected)} "
                f"({100.0 * len(selected) / max(len(eligible), 1):.1f}%) "
                f"dynOps covered={100.0 * dyn_selected / max(dyn_eligible, 1):.1f}%")
        for k in (1, 2, 3, 4):
            residual = weighted_residual(selected, "cov_region", k)
            if residual is not None:
                line += f" region-resid k={k}: {100.0 * residual:.1f}%"
        print(line)

    if args.out:
        args.out.write_text(json.dumps(rows))
        print(f"\nper-unit rows written to {args.out}")


if __name__ == "__main__":
    main()
