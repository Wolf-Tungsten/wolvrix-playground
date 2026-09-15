"""Inspect localization, boundary slots and generated code without executing a model."""

from __future__ import annotations

import argparse
from array import array
from collections import Counter, deque
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flow", type=Path, required=True)
    parser.add_argument("--state-suffix", default="")
    parser.add_argument("--dead-cones-only", action="store_true")
    args = parser.parse_args()
    data = json.loads((args.flow / "xiangshan_grhsim_ir.json").read_bytes())
    strings = data["strings"]
    def text(value):
        return strings[value - 1] if value else ""
    ops = data["operations"]
    if args.dead_cones_only:
        producers = array("I", [0]) * (len(data["values"]) + 1)
        uses = array("I", [0]) * len(producers)
        removable = bytearray(len(ops) + 1)
        removed = bytearray(len(removable))
        for op in ops:
            name = text(op[1])
            removable[op[0]] = name.startswith("core.compute.") or name in ("core.input.read", "core.state.read")
            for value in op[5]:
                producers[value] = op[0]
            for value in op[4]:
                uses[value] += 1
        queue = deque(op[0] for op in ops if removable[op[0]] and op[5] and not any(uses[v] for v in op[5]))
        counts = Counter()
        widths = Counter()
        distinct_users = array("I", [0]) * len(producers)
        compute_users = array("I", [0]) * len(producers)
        for op in ops:
            for value in set(op[4]):
                distinct_users[value] += 1
                compute_users[value] += text(op[1]).startswith("core.compute.")
        candidates = Counter()
        clones = Counter()
        for op in ops:
            if len(op[5]) != 1 or op[6] or op[7]:
                continue
            result = op[5][0]
            if not 2 <= distinct_users[result] <= 8 or not compute_users[result]:
                continue
            type_id = data["values"][result - 1][1]
            result_type = data["types"][type_id - 1]
            if result_type[2] != "logic" or result_type[5] != "2-state" or not 1 <= result_type[3] <= 64:
                continue
            name = text(op[1])
            operand = None
            if name == "core.compute.not" and len(op[4]) == 1:
                if data["values"][op[4][0] - 1][1] == type_id:
                    operand = op[4][0]
            elif name == "core.compute.logicNot" and len(op[4]) == 1 and result_type[3] == 1:
                source_type = data["types"][data["values"][op[4][0] - 1][1] - 1]
                if source_type[2] == "logic" and source_type[3] == 1 and source_type[5] == "2-state":
                    operand = op[4][0]
            elif name in ("core.compute.xor", "core.compute.add", "core.compute.sub") and len(op[4]) == 2:
                if all(data["values"][v - 1][1] == type_id for v in op[4]):
                    constants = [text(ops[producers[v] - 1][1]) == "core.compute.constant" for v in op[4]]
                    if sum(constants) == 1:
                        operand = op[4][int(constants[0])]
            if operand and distinct_users[operand] > 1:
                candidates[name] += 1
                clones[name] += compute_users[result]
        while queue:
            index = queue.popleft()
            if removed[index]:
                continue
            op = ops[index - 1]
            if any(uses[v] for v in op[5]):
                continue
            removed[index] = 1
            counts[text(op[1])] += 1
            for value in op[5]:
                widths[str(data["types"][data["values"][value - 1][1] - 1])] += 1
            for value in op[4]:
                uses[value] -= 1
                producer = producers[value]
                if uses[value] == 0 and producer and removable[producer]:
                    queue.append(producer)
        print(json.dumps({"operations": len(ops), "dead": sum(counts.values()), "dead_by_op": dict(counts),
                          "dead_by_type": dict(widths), "bijective_roots": dict(candidates),
                          "bijective_clones": dict(clones)}, indent=2))
        return
    cpu = data["mappings"][0][4]
    parts, layout, schedule = cpu[2:5]
    kinds = ("root", "phase", "event_domain", "supernode", "node", "active_word", "emit_function")
    slots = layout[3]
    owners = array("I", [0]) * (len(ops) + 1)
    parents = array("I", [0]) * (len(parts) + 1)
    task_by_part = {}
    for numa in schedule[0]:
        for core in numa[1]:
            for task in core[1]:
                task_by_part[task[1]] = task[0]
    for part in parts:
        parents[part[0]] = part[1]
        for op in part[5]:
            owners[op] = part[0]
    def task_of(op):
        part = owners[op]
        while part:
            if part in task_by_part:
                return task_by_part[part]
            part = parents[part]
        return None
    op_counts = Counter()
    boundary_counts = Counter()
    clone_slots = Counter()
    clone_roots = set()
    selected_states = {i for i, state in enumerate(data["states"], 1)
                       if args.state_suffix and text(state[1]).endswith(args.state_suffix)}
    reads = []
    read_values = set()
    for op in ops:
        name = text(op[1])
        op_counts[name] += 1
        for value in op[5]:
            if slots[value - 1][1] == 2:
                boundary_counts[name] += 1
            if ".local" in text(op[2]):
                clone_slots[str(slots[value - 1][1])] += 1
                clone_roots.add(text(op[2]).rsplit(".", 1)[-1])
        if name == "core.state.read" and any(ref[0] == "state" and ref[1] in selected_states for ref in op[6]):
            reads.append({"op": op[0], "task": task_of(op[0]), "results": op[5]})
            read_values.update(op[5])
    selected_nots = []
    not_by_value = {}
    for op in ops:
        if text(op[1]) not in ("core.compute.not", "core.compute.logicNot") or not read_values.intersection(op[4]):
            continue
        entry = {"op": op[0], "name": text(op[2]), "task": task_of(op[0]),
                 "operands": op[4], "result": op[5][0], "slot": slots[op[5][0] - 1], "users": []}
        selected_nots.append(entry)
        not_by_value[op[5][0]] = entry
    for op in ops:
        for operand in set(op[4]):
            if operand in not_by_value:
                not_by_value[operand]["users"].append({"op": op[0], "type": text(op[1]), "task": task_of(op[0])})
    cpp_counts = Counter()
    for path in (args.flow / "model").glob("*.cpp"):
        source = path.read_bytes()
        cpp_counts["all_cpp_bytes"] += len(source)
        if "_task_" not in path.name:
            continue
        cpp_counts["tasks"] += 1
        cpp_counts["task_cpp_bytes"] += len(source)
        for marker in ("cpu_boundary.get()", "cpu_objects.get()", "cpu_local", "cpu_changed_", "cpu_flags[", "cpu_pflags["):
            cpp_counts[marker] += source.count(marker.encode())
    result = {"operations": len(ops), "values": len(data["values"]), "states": len(data["states"]),
              "op_counts": dict(op_counts), "partition_counts": dict(Counter(kinds[p[2]] for p in parts)),
              "boundary_values": sum(boundary_counts.values()), "boundary_by_op": dict(boundary_counts),
              "object_bytes": layout[6], "boundary_bytes": layout[7], "runtime_bytes": layout[8],
              "clone_slots": dict(clone_slots), "cloned_roots": len(clone_roots), "code": dict(cpp_counts),
              "selected_state_count": len(selected_states), "selected_reads": reads, "selected_nots": selected_nots}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
