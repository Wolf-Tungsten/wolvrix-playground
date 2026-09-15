"""Audit state read materialization and compute/commit sharing in a CPU mapping."""

import argparse
from array import array
from collections import Counter
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--notify", action="store_true")
    parser.add_argument("--projected-only", action="store_true")
    parser.add_argument("--feedback", action="store_true")
    parser.add_argument("--pack-states", action="store_true")
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()
    model = json.loads(args.model.read_bytes())
    strings, types, values = model["strings"], model["types"], model["values"]
    ops = model["operations"]
    cpu = model["mappings"][0][4]
    parts, layout, schedule = cpu[2:5]
    text = lambda index: strings[index - 1] if index else ""
    if args.summary_only:
        def summarize(item):
            strings = item["strings"]
            text = lambda index: strings[index - 1] if index else ""
            _, _, parts, layout, schedule = item["mappings"][0][4]
            operations = Counter(text(op[1]) for op in item["operations"])
            widths = Counter()
            for op in item["operations"]:
                if text(op[1]) == "core.state.regWrite":
                    state = item["states"][op[6][0][1] - 1]
                    widths[str(item["types"][state[2] - 1][3])] += 1
            return {"operations": len(item["operations"]), "values": len(item["values"]),
                    "states": len(item["states"]), "op_counts": operations, "register_widths": widths,
                    "tasks": sum(len(core[1]) for numa in schedule[0] for core in numa[1]),
                    "round_seeds": len(schedule[4]), "projection_states": sum(word.bit_count() for word in schedule[8]),
                    "object_bytes": layout[6], "boundary_bytes": layout[7], "runtime_bytes": layout[8],
                    "boundary_values": sum(slot[1] == 2 for slot in layout[3])}
        report = {"new": summarize(model)}
        if args.reference:
            report["old"] = summarize(json.loads(args.reference.read_bytes()))
        print(json.dumps(report, indent=2))
        return
    commit_names = {"core.state." + name for name in
                    ("regWrite", "latchWrite", "memWrite", "memFill", "memAssign", "memWriteSeq")}
    compute_uses = array("I", [0]) * (len(values) + 1)
    pure_uses = array("I", [0]) * (len(values) + 1)
    other_uses = bytearray(len(values) + 1)
    snapshot = bytearray(len(values) + 1)
    ordinary = bytearray(len(model["states"]) + 1)
    for state in model["states"]:
        type_ = types[state[2] - 1]
        ordinary[state[0]] = type_[2] == "logic" and type_[5] == "2-state"
    for op in ops:
        name = text(op[1])
        for i, ref in enumerate(op[6]):
            if ref[0] == "state" and not (i == 0 and name in
                    ("core.state.read", "core.state.regWrite", "core.state.latchWrite")):
                ordinary[ref[1]] = 0
        for operand in set(op[4]):
            if (name.startswith("core.compute.") or name == "core.output.write" or
                    name == "core.dpi.call" or name.startswith("core.system.") or name == "core.state.memRead"):
                pure_uses[operand] += 1
            else:
                other_uses[operand] = 1
            if name in commit_names:
                snapshot[operand] = 1
            else:
                compute_uses[operand] += 1
    for part in parts:
        # event_gate is [source, [[value, edge], ...]], [] when absent.
        if part[6]:
            for event in part[6][1]:
                snapshot[event[0]] = 1
    projection = schedule[8]
    counts, split_widths, boundary_ops = Counter(), Counter(), Counter()
    examples = []
    unprojected_examples = []
    for op in ops:
        name = text(op[1])
        for value in op[5]:
            if layout[3][value - 1][1] == 2:
                boundary_ops[name] += 1
        if name != "core.state.read":
            continue
        counts["state_reads"] += 1
        result, state = op[5][0], op[6][0][1]
        rtype = types[values[result - 1][1] - 1]
        same_type = values[result - 1][1] == model["states"][state - 1][2]
        eligible = rtype[2] == "logic" and same_type
        projected = bool((projection[state // 64] >> (state % 64)) & 1)
        counts["projected"] += projected
        counts["snapshot"] += bool(snapshot[result])
        counts["existing_alias"] += projected and eligible and not snapshot[result]
        counts["ordinary_reads"] += bool(ordinary[state])
        extra_alias = bool(not args.projected_only and ordinary[state] and not projected and eligible and not snapshot[result])
        counts["additional_unprojected_aliases"] += extra_alias
        counts["additional_unprojected_boundary_aliases"] += extra_alias and layout[3][result - 1][1] == 2
        counts["effective_aliases"] += eligible and not snapshot[result] and (projected or
            (ordinary[state] and not args.projected_only))
        if extra_alias and layout[3][result - 1][1] == 2 and len(unprojected_examples) < 6:
            unprojected_examples.append({"op": op[0], "value": result, "state": state,
                "state_name": text(model["states"][state - 1][1]), "width": rtype[3],
                "slot": layout[3][result - 1], "object": layout[2][len(model["inputs"]) + len(model["outputs"]) + state - 1]})
        if ordinary[state] and eligible and pure_uses[result] and other_uses[result] and not op[7]:
            counts["pass_splits"] += 1
            counts["pass_distinct_compute_uses"] += pure_uses[result]
        if eligible and snapshot[result] and compute_uses[result]:
            counts["mixed_reads"] += 1
            counts["mixed_compute_uses"] += compute_uses[result]
            counts["mixed_projected_reads"] += projected
            counts["mixed_projected_compute_uses"] += compute_uses[result] if projected else 0
            split_widths[str(rtype[3])] += 1
            if len(examples) < 10:
                examples.append({"op": op[0], "state": state, "name": text(op[2]),
                                 "width": rtype[3], "projected": projected,
                                 "compute_uses": compute_uses[result]})
    report = {"counts": counts, "mixed_widths": split_widths,
              "boundary_by_op": boundary_ops, "examples": examples, "unprojected_examples": unprojected_examples,
              "operations": len(ops), "values": len(values), "states": len(model["states"]),
              "task_executions": Counter(str(task[3]) for numa in schedule[0]
                                         for core in numa[1] for task in core[1]),
              "boundary_values": sum(boundary_ops.values()),
              "object_bytes": layout[6], "boundary_bytes": layout[7], "runtime_bytes": layout[8]}
    if args.notify:
        owners = array("I", [0]) * (len(ops) + 1)
        for part in parts:
            if part[2] == 4:
                for index in part[5]:
                    owners[index] = part[1]
        aliases = array("I", [0]) * (len(values) + 1)
        for op in ops:
            if text(op[1]) == "core.state.read":
                value, state = op[5][0], op[6][0][1]
                projected = (projection[state // 64] >> (state % 64)) & 1
                if (owners[op[0]] and not snapshot[value] and (projected or (ordinary[state] and not args.projected_only)) and
                        values[value - 1][1] == model["states"][state - 1][2]):
                    aliases[value] = state
        work = bytearray(len(parts) + 1)
        consumers = {}
        materialized = {}
        for op in ops:
            owner = owners[op[0]]
            if not owner:
                continue
            if text(op[1]) == "core.state.read" and not aliases[op[5][0]]:
                materialized.setdefault(op[6][0][1], set()).add(owner)
            inactive = False
            if len(op[5]) == 1:
                result_type = types[values[op[5][0] - 1][1] - 1]
                inactive = bool(aliases[op[5][0]]) or (text(op[1]) == "core.compute.constant" and
                    (result_type[2] == "string" or (result_type[2] == "logic" and
                     result_type[5] == "2-state" and 1 <= result_type[3] <= 64)))
            if not inactive:
                work[owner] = 1
            for value in op[4]:
                if aliases[value]:
                    consumers.setdefault(aliases[value], set()).add(owner)
        words = {part[0]: part[1] for part in parts if part[2] == 3}
        histogram = Counter()
        exact = Counter()
        seeded = set(schedule[4])
        seeded_filter = Counter()
        for state, activate, arm in schedule[3]:
            units = set(activate) | consumers.get(state, set())
            before = len({words[unit] for unit in units}) + len(arm)
            after = len({words[unit] for unit in units if work[unit]}) + len(arm)
            histogram[f"{before}->{after}"] += 1
            required = materialized.get(state, set()) | consumers.get(state, set()) if ordinary[state] else units
            exact[f"{before}->{len({words[unit] for unit in required}) + len(arm)}"] += 1
            seeded_filter[f"{before}->{len({words[unit] for unit in required if unit not in seeded}) + len(arm)}"] += 1
        report["notify"] = {"inert_units": sum(not work[unit] for unit in set(owners) if unit),
                            "target_words_before_after": histogram,
                            "target_words_exact_reader_filter": exact,
                            "target_words_omit_seeded_readers": seeded_filter}
    if args.feedback or args.pack_states:
        producer = array("I", [0]) * (len(values) + 1)
        users = array("I", [0]) * len(producer)
        writers = Counter()
        for op in ops:
            for value in op[5]:
                producer[value] = op[0]
            for value in op[4]:
                users[value] += 1
            if text(op[1]) in ("core.state.regWrite", "core.state.latchWrite"):
                writers[op[6][0][1]] += 1
        feedback = Counter()
        feedback_examples = []
        for op in ops:
            if text(op[1]) not in ("core.state.regWrite", "core.state.latchWrite"):
                continue
            state = op[6][0][1]
            if not ordinary[state] or writers[state] != 1:
                continue
            data = ops[producer[op[4][1]] - 1]
            if text(data[1]) != "core.compute.mux" or len(data[4]) != 3 or data[6] or data[7]:
                continue
            rtype = model["states"][state - 1][2]
            if any(values[value - 1][1] != rtype for value in data[4][1:] + data[5]):
                continue
            for branch in (1, 2):
                src = ops[producer[data[4][branch]] - 1]
                if text(src[1]) == "core.state.read" and src[6] == [["state", state]]:
                    feedback["writers"] += 1
                    feedback["single_use_mux"] += users[data[5][0]] == 1
                    feedback["false_branch_hold"] += branch == 2
                    feedback["width_" + str(types[rtype - 1][3])] += 1
                    if len(feedback_examples) < 8:
                        feedback_examples.append({"write": op[0], "mux": data[0], "hold_branch": branch,
                            "enable": ops[producer[op[4][0]] - 1], "mask": ops[producer[op[4][2]] - 1]})
                    break
        report["feedback"] = {"counts": feedback, "examples": feedback_examples}
        if args.pack_states:
            references = Counter(ref[1] for op in ops for ref in op[6] if ref[0] == "state")
            initial = {record[0]: record[1] for record in model["init"]}
            groups = Counter()
            for op in ops:
                if text(op[1]) != "core.state.regWrite":
                    continue
                state = op[6][0][1]
                t = types[model["states"][state - 1][2] - 1]
                if not ordinary[state] or writers[state] != 1 or t[2:6] != ["logic", 1, False, "2-state"]:
                    continue
                if any(references[ref[1]] != 1 for ref in op[6][1:]):
                    continue
                key = (tuple(op[4][:1] + op[4][2:]), json.dumps(op[7]),
                       tuple(json.dumps(initial.get(ref[1])) for ref in op[6][1:]))
                groups[key] += 1
            report["pack_states"] = {"group_sizes": Counter(groups.values()),
                "eligible_states": sum(count for count in groups.values() if count >= 2),
                "groups": sum(count >= 2 for count in groups.values()),
                "writes_after_pack64": sum((count + 63) // 64 for count in groups.values() if count >= 2)}
    if args.reference:
        old = json.loads(args.reference.read_bytes())
        # Section names are checked against the actual serializer, not silently
        # skipped. All existing operation identities and state effects survive.
        if model.keys() != old.keys() or len(ops) < len(old["operations"]):
            raise ValueError("model sections or original operation coverage changed")
        unchanged = [key for key in model if key not in
                     ("counts", "strings", "values", "operations", "mappings")]
        for key in unchanged:
            if model[key] != old[key]:
                raise ValueError(f"unexpected change in {key}")
        string_changes = [(i + 1, a, b) for i, (a, b) in enumerate(zip(old["strings"], strings)) if a != b]
        if string_changes:
            # Mapping-only backend/schema strings are interned after semantic
            # passes. New view names precede this suffix; all semantic string
            # indices must still match exactly.
            suffix = sorted({index for mapping in old["mappings"] for index in mapping[:2]})
            if suffix != list(range(suffix[0], len(old["strings"]) + 1)):
                raise ValueError("changed string indices are not a backend suffix")
            if (strings[:suffix[0] - 1] != old["strings"][:suffix[0] - 1] or
                    strings[-len(suffix):] != old["strings"][suffix[0] - 1:]):
                raise ValueError("semantic strings or backend/schema names changed")
        if values[:len(old["values"])] != old["values"]:
            raise ValueError("existing values changed")
        if schedule[7:] != old["mappings"][0][4][4][7:]:
            raise ValueError("quiescence projection changed")
        producers = {op[5][0]: op for op in old["operations"] if text(op[1]) == "core.state.read"}
        added = ops[len(old["operations"]):]
        views = {}
        for op in added:
            if (text(op[1]) != "core.state.read" or op[4] or len(op[5]) != 1 or
                    len(op[6]) != 1 or op[7] or not ordinary[op[6][0][1]]):
                raise ValueError("unexpected appended operation")
            views[op[5][0]] = op
        rewired, changed_ops = 0, 0
        commit_unchanged = 0
        for before, after in zip(old["operations"], ops):
            if before[:4] + before[5:] != after[:4] + after[5:]:
                raise ValueError("original operation changed beyond its operands")
            if len(before[4]) != len(after[4]):
                raise ValueError("operand count changed")
            if text(before[1]) in commit_names:
                if before != after:
                    raise ValueError("commit snapshot changed")
                commit_unchanged += 1
            changed_ops += before[4] != after[4]
            for a, b in zip(before[4], after[4]):
                if a == b:
                    continue
                if a not in producers or b not in views or snapshot[b]:
                    raise ValueError("rewrite is not an isolated compute view")
                if producers[a][6] != views[b][6] or values[a - 1][1] != values[b - 1][1]:
                    raise ValueError("view reads a different state or type")
                rewired += 1
        if len(values) - len(old["values"]) != len(added) or len(views) != len(added):
            raise ValueError("added read/value coverage differs")
        report["comparison"] = {"unchanged_sections": unchanged, "new_reads": len(added),
                                "backend_string_index_changes": string_changes,
                                "rewired_operands": rewired, "changed_compute_ops": changed_ops,
                                "unchanged_commit_ops": commit_unchanged,
                                "boundary_values_delta": sum(boundary_ops.values()) -
                                    sum(slot[1] == 2 for slot in old["mappings"][0][4][3][3])}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
