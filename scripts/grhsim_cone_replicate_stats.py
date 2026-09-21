"""Census small-cone replication opportunities (gsim replicationOpt form).

gsim replicates small expression cones that cross supernode boundaries into each
consumer supernode, eliminating cross-supernode dependency/activation coupling at
the source (replication.cpp). In the grhsim CPU form the analogous materialization
is the Boundary value slot: produced in one supernode, stored with change
detection, and read from others. This census finds boundary values whose producer
cone is a small tree of single-use pure compute ops rooted at globally-visible
leaves (state.read/input.read/constant/other boundary), so each consumer
supernode could recompute the cone locally and the boundary slot plus its
write-back/compare/fanout publication could be retired.

Pool reported by cone-size and consumer-count buckets, split by consumer phase
(all-compute vs mixed/commit) since commit consumers still need the value.
"""

import argparse
from array import array
from collections import Counter
import json
from pathlib import Path

COMPUTE_PREFIX = "core.compute."
LEAF_NAMES = {"core.state.read", "core.input.read", "core.compute.constant",
              "core.state.memRead"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    args = parser.parse_args()
    model = json.loads(args.model.read_bytes())
    ops, values, strings = model["operations"], model["values"], model["strings"]
    types = {t[0]: t for t in model["types"]}
    names = [strings[op[1] - 1] for op in ops]
    payload = model["mappings"][0][-1]
    partitions = {part[0]: part for part in payload[2]}
    value_slots = payload[3][3]

    def is_scalar_2s(value):
        t = types[values[value - 1][1]]
        return t[2] == "logic" and 0 < t[3] <= 64 and t[5] == "2-state"

    producer = array("I", [0]) * (len(values) + 1)
    uses = array("I", [0]) * (len(values) + 1)
    for op in ops:
        if op[5]:
            producer[op[5][0]] = op[0]
        for operand in op[4]:
            uses[operand] += 1

    # partition tree: collect op membership per supernode subtree, and phase by
    # top-level branch (first Phase-kind child of root with phase attr).
    kind_hist = Counter(part[2] for part in partitions.values())
    print(f"partition kind histogram: {dict(sorted(kind_hist.items()))}")
    root = None
    for part in partitions.values():
        if part[2] == 0:
            root = part
            break
    phase_of_branch = {}
    if root is not None:
        for child_id in root[4]:
            child = partitions[child_id]
            phase_of_branch[child_id] = child[3] if len(child) > 3 else None
    print(f"root children phases: {phase_of_branch}")

    op_supernode = array("I", [0]) * (len(ops) + 1)
    supernode_phase = {}
    def collect(pid, phase, sn):
        part = partitions[pid]
        here = sn
        if part[2] == 3:
            here = pid
            supernode_phase[pid] = phase
        for op_id in part[5]:
            op_supernode[op_id] = here
        for child in part[4]:
            collect(child, phase, here)
    if root is not None:
        for child_id in root[4]:
            collect(child_id, phase_of_branch.get(child_id), 0)
    phase_hist = Counter(supernode_phase.values())
    print(f"supernode phase histogram: {dict(phase_hist)}")

    boundary_values = [i + 1 for i, slot in enumerate(value_slots) if slot[1] == 2]
    print(f"boundary_values={len(boundary_values)}")

    boundary_set = set(boundary_values)
    value_consumers = {}
    for op in ops:
        for operand in op[4]:
            if operand in boundary_set:
                value_consumers.setdefault(operand, []).append(op[0])

    # Exact activation trigger sets from the schedule fanout tables:
    # source value -> set of supernode partition ids it activates.
    schedule = payload[4]
    print(f"schedule sections: {[type(s).__name__ for s in schedule]}")
    print(f"schedule[2] entries={len(schedule[2])} sample={schedule[2][0] if schedule[2] else None}")
    leaf_triggers = {}
    for entry in schedule[2]:
        source, activates = entry[0], entry[1]
        bucket = leaf_triggers.setdefault(source, set())
        for target in activates:
            bucket.add(target[0] if isinstance(target, list) else target)

    # value -> set of consumer supernode ids (for activation-neutrality check).
    # Leaves can be any value (state.read results, constants, other boundary),
    # so build this for values consumed by ops inside supernodes.
    leaf_supernodes = {}
    for op in ops:
        sn = op_supernode[op[0]]
        if not sn:
            continue
        for operand in op[4]:
            bucket = leaf_supernodes.get(operand)
            if bucket is None:
                leaf_supernodes[operand] = {sn}
            else:
                bucket.add(sn)

    stats = Counter()
    examples = []

    for value in boundary_values:
        stats["boundary_total"] += 1
        op_id = producer[value]
        if not op_id or not names[op_id - 1].startswith(COMPUTE_PREFIX):
            stats["non_compute_producer"] += 1
            continue
        if not is_scalar_2s(value):
            stats["wide_value"] += 1
            continue
        # cone walk through single-use pure compute ops
        cone_ops = []
        leaves = []
        stack = [value]
        ok = True
        seen = set()
        while stack and ok:
            v = stack.pop()
            pid = producer[v]
            if pid == 0 or not names[pid - 1].startswith(COMPUTE_PREFIX):
                if names[pid - 1] in LEAF_NAMES if pid else False:
                    leaves.append(v)
                    continue
                if pid == 0:
                    leaves.append(v)  # state read result / input (producer 0 -> external?)
                    continue
                ok = False
                break
            pop = ops[pid - 1]
            if len(pop[5]) != 1 or pop[6] or not is_scalar_2s(v):
                ok = False
                break
            if pid in seen:
                continue
            seen.add(pid)
            cone_ops.append(pid)
            for operand in pop[4]:
                src = producer[operand]
                if src == 0:
                    leaves.append(operand)  # state.read results have no producing op
                    continue
                src_name = names[src - 1]
                if src_name in LEAF_NAMES:
                    leaves.append(operand)
                    continue
                if src_name.startswith(COMPUTE_PREFIX):
                    if uses[operand] != 1:
                        ok = False
                        break
                    if not is_scalar_2s(operand):
                        ok = False
                        break
                    if value_slots[operand - 1][1] == 2:
                        leaves.append(operand)  # already boundary: visible everywhere
                        continue
                    stack.append(operand)
                    continue
                ok = False
                break
        if not ok or not cone_ops:
            stats["cone_not_eligible"] += 1
            continue
        # consumer classification
        consumer_phases = set()
        consumer_supernodes = set()
        consumer_list = value_consumers.get(value, [])
        n_consumers = len(consumer_list)
        for consumer_id in consumer_list:
            sn = op_supernode[consumer_id]
            consumer_supernodes.add(sn)
            consumer_phases.add(supernode_phase.get(sn, "?"))
        if n_consumers < 2:
            stats["single_consumer"] += 1
            continue
        key_size = min(len(cone_ops), 16)
        stats[f"eligible_cone_size={key_size}"] += 1
        stats[f"eligible_consumers={min(n_consumers, 8)}"] += 1
        phase_key = "+".join(sorted(str(p) for p in consumer_phases))
        stats[f"phase:{phase_key}"] += 1
        stats["eligible_total"] += 1
        stats["eligible_cone_ops_total"] += len(cone_ops)
        # activation-neutrality: every cone leaf must already fan out to every
        # consumer supernode of the value, so cloning adds no new activation
        # edges (consumer already evaluates on each leaf change).
        if 2 <= n_consumers <= 8 and consumer_phases == {1}:
            stats["compute_only_2to8"] += 1
            leaves_cover = True
            for leaf in set(leaves):
                leaf_op = producer[leaf]
                if leaf_op == 0 or names[leaf_op - 1] in ("core.compute.constant", "core.input.read"):
                    continue  # immutable or top-level: no activation edge
                reachable = leaf_supernodes.get(leaf, set()) | leaf_triggers.get(leaf, set())
                if not (consumer_supernodes <= reachable):
                    leaves_cover = False
                    break
            if leaves_cover:
                stats[f"prime_cone_size={key_size}"] += 1
                stats[f"prime_consumers={min(n_consumers, 8)}"] += 1
                stats["prime_total"] += 1
                stats["prime_cone_ops_total"] += len(cone_ops)
            else:
                stats["nonprime_uncovered"] += 1
        if len(examples) < 8:
            examples.append({"value": value, "cone_ops": len(cone_ops),
                             "consumers": n_consumers, "phases": sorted(str(p) for p in consumer_phases)})

    print("== cone replication census ==")
    for key in sorted(stats):
        print(f"{stats[key]:10d}  {key}")
    print("== examples ==")
    for item in examples:
        print(item)


if __name__ == "__main__":
    main()
