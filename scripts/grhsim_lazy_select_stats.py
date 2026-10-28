#!/usr/bin/env python3
"""Count strictly private scalar producer cones behind GrhSIM selections.

This is a static coverage census, not a speedup estimate. Whole-function sample
envelopes include work that cannot be removed and do not price branch outcomes.
"""

import argparse
from array import array
from collections import Counter
import json
import mmap
from pathlib import Path
import re
import time


PURE = set("""
kConstant kAssign kAdd kSub kMul kDiv kMod kAnd kOr kXor kXnor
kLogicAnd kLogicOr kNot kLogicNot kMux kBitSelect kPrioritySelect
kEq kNe kCaseEq kCaseNe kWildcardEq kWildcardNe kLt kLe kGt kGe
kShl kLShr kAShr kReduceAnd kReduceNand kReduceOr kReduceNor
kReduceXor kReduceXnor kConcat kReplicate kSliceStatic kSliceDynamic
kZExt kSExt kTrunc
""".split())
LEAF_ROOTS = {"kAssign", "kConcat", "kReplicate", "kMux"}
SCALAR = re.compile(r"(?:bool|std::(?:u?int)(?:8|16|32|64)_t)\Z")
KIND_ALIASES = {"grhsim.bitSelect": "kBitSelect", "grhsim.prioritySelect": "kPrioritySelect"}


def records(data, section, following, key):
    marker = ('"' + section + '":[').encode()
    start = data.find(marker)
    if start < 0:
        raise ValueError(f"missing {section}")
    start += len(marker)
    end = data.find(('],"' + following + '":[').encode(), start) if following else len(data) - 2
    if end < 0:
        raise ValueError(f"missing end of {section}")
    pattern = re.compile(rb'\{"name":"(?:\\.|[^"\\])*","source":' if section == "functions" else
                         ('\\{"' + key + '":').encode())
    previous = None
    for match in pattern.finditer(data, start, end):
        if previous is not None:
            yield data[previous:match.start()].rstrip(b',')
        previous = match.start()
    if previous is not None:
        yield data[previous:end].rstrip(b',')


def compact_name(name):
    return name.split("(", 1)[0].rsplit("::", 1)[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-id", type=int, default=18_000_000)
    parser.add_argument("--all-owners", action="store_true", help="include nonsink general owners; Event/Output remain excluded")
    parser.add_argument("--include-bool-bitselect", action="store_true")
    args = parser.parse_args()
    started = time.monotonic()
    size = args.max_id + 1
    producer = array("I", [0]) * size
    scalar = bytearray(size)
    pinned = bytearray(size)
    uses = bytearray(size)
    owner = array("I", [0]) * size
    result = array("I", [0]) * size
    begin = array("I", [0]) * size
    count = array("H", [0]) * size
    kind = bytearray(size)
    eligible = bytearray(size)
    emitted = bytearray(size)
    inputs = array("I")
    roots = array("I")
    op_ids = array("I")
    kinds = {"": 0}
    owners = {(): 0}
    value_count = 0
    select_kinds = {"kMux", "kPrioritySelect"}
    if args.include_bool_bitselect:
        select_kinds.add("kBitSelect")

    with (args.model / "code-map.json").open("rb") as stream, mmap.mmap(
            stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        for raw in records(data, "values", "operations", "value_id"):
            item = json.loads(raw)
            value = int(item["value_id"][1:])
            if value >= size:
                raise ValueError("increase --max-id")
            source = item.get("producer")
            producer[value] = int(source[1:]) if source else 0
            scalar[value] = 2 if item["cpp_type"] == "bool" else bool(SCALAR.fullmatch(item["cpp_type"]))
            pinned[value] |= bool(item.get("storage") or item.get("snapshot_source"))
            if item.get("snapshot_source"):
                pinned[int(item["snapshot_source"][1:])] = 1
            value_count += 1
            if value_count % 1_000_000 == 0:
                print(f"values {value_count:,}", flush=True)

        print(f"values complete: {value_count:,}; scanning operations", flush=True)
        total_by_kind = Counter()
        for raw in records(data, "operations", "stores", "operation_id"):
            item = json.loads(raw)
            op = int(item["operation_id"][1:])
            if op >= size:
                raise ValueError("increase --max-id")
            op_ids.append(op)
            name = KIND_ALIASES.get(item["kind"], item["kind"])
            kind[op] = kinds.setdefault(name, len(kinds))
            key = tuple(item["execution_owner"])
            owner[op] = owners.setdefault(key, len(owners))
            args_in = [int(value[1:]) for value in item["operands"]]
            begin[op] = len(inputs)
            count[op] = len(args_in)
            inputs.extend(args_in)
            for value in args_in:
                uses[value] = min(2, uses[value] + 1)
            out = item["results"]
            if len(out) == 1:
                result[op] = int(out[0][1:])
            is_emitted = not item["elided"]
            emitted[op] = is_emitted
            total_by_kind[name] += 1
            eligible[op] = bool(is_emitted and name in PURE and result[op] and scalar[result[op]] and
                                all(scalar[value] for value in args_in))
            # Conservative leaf-plan pin: no value read through an already
            # elided op or a possible shaped leaf-plan root may be relocated.
            if item["elided"] or (name in LEAF_ROOTS and result[op] and not scalar[result[op]]):
                for value in args_in:
                    pinned[value] = 1
            is_general_owner = len(key) == 3 and key[0] == "general"
            owner_allowed = is_general_owner and (args.all_owners or key[1] != "nonsink")
            if eligible[op] and name in select_kinds and owner_allowed:
                if name != "kBitSelect" or (scalar[result[op]] == 2 and all(scalar[v] == 2 for v in args_in)):
                    roots.append(op)
            if len(op_ids) % 1_000_000 == 0:
                print(f"operations {len(op_ids):,}", flush=True)

        print(f"operations complete: {len(op_ids):,}; traversing {len(roots):,} selects", flush=True)
        names = {value: key for key, value in kinds.items()}
        owner_names = {value: key for key, value in owners.items()}
        moved = bytearray(size)
        moved_by_kind = Counter()
        moved_by_owner = Counter()
        rejects = Counter()
        root_kind_stats = {}
        top_roots = []
        max_depth = 0
        for root in roots:
            name = names[kind[root]]
            args_in = inputs[begin[root]:begin[root] + count[root]]
            conditional = args_in[1:]  # mux/bitSelect arms, later priority conditions and all arms/default
            local = set()
            stack = [(value, 1) for value in conditional]
            while stack:
                value, depth = stack.pop()
                source = producer[value]
                if not source:
                    rejects["no_producer"] += 1
                elif pinned[value]:
                    rejects["materialized_or_leaf_terminal"] += 1
                elif uses[value] != 1:
                    rejects["not_single_operand_use"] += 1
                elif owner[source] != owner[root]:
                    rejects["different_owner"] += 1
                elif not eligible[source]:
                    rejects["not_emitted_pure_scalar_operands_and_result"] += 1
                elif depth > 64 or len(local) >= 4096:
                    rejects["depth_or_node_budget"] += 1
                elif source not in local:
                    local.add(source)
                    max_depth = max(max_depth, depth)
                    stack.extend((item, depth + 1) for item in inputs[begin[source]:begin[source] + count[source]])
            stats = root_kind_stats.setdefault(name, Counter())
            stats["roots"] += 1
            stats["roots_with_movable_producers"] += bool(local)
            stats["producer_visits"] += len(local)
            if local:
                top_roots.append((len(local), root, owner[root], name))
            for source in local:
                if not moved[source]:
                    moved[source] = 1
                    moved_by_kind[names[kind[source]]] += 1
                    moved_by_owner[owner[source]] += 1

        print(f"movable producer union {sum(moved_by_kind.values()):,}; mapping profile envelopes", flush=True)
        profile = json.loads(args.profile.read_text())
        samples = Counter()
        for name, n in profile["functions"].items():
            samples[compact_name(name)] += n
        any_samples = all_samples = half_samples = 0
        any_functions = all_functions = 0
        helper_top = []
        owner_function_stats = {}
        for raw in records(data, "functions", "nonsink_functions", "name"):
            item = json.loads(raw)
            ops = [int(op[1:]) for op in item["operations"]]
            ops = [op for op in ops if emitted[op]]
            if not ops:
                continue
            n_moved = sum(bool(moved[op]) for op in ops)
            if not n_moved:
                continue
            n = samples[compact_name(item["name"])]
            any_functions += 1
            any_samples += n
            if n_moved == len(ops):
                all_functions += 1
                all_samples += n
            if n_moved * 2 >= len(ops):
                half_samples += n
            helper_top.append({"name": item["name"], "samples": n, "operations": len(ops), "movable": n_moved})
            root_name = item.get("root_function", item["name"])
            stats = owner_function_stats.setdefault(root_name, Counter())
            stats["operations_in_touched_functions"] += len(ops)
            stats["movable_in_touched_functions"] += n_moved
            stats["samples_in_touched_functions"] += n

    result_data = {
        "model": str(args.model), "profile": str(args.profile),
        "elapsed_seconds": time.monotonic() - started,
        "coverage_definition": "Union of emitted pure scalar<=64 producers (scalar operands too), exactly one graph operand use, same execution owner, no named storage/snapshot, conservative leaf terminal pins; depth<=64/nodes<=4096 per select. Conditional operands exclude first condition. This is static movable coverage, not dynamically skipped work.",
        "all_owners": args.all_owners, "include_bool_bitselect": args.include_bool_bitselect,
        "owner_scope": "all three-component general owners" if args.all_owners else "three-component general sink owners",
        "sample_envelope_caveat": "Any-touched/half-covered samples price whole helpers, including unavoidable work. Even all-covered helper samples do not imply all their runtime disappears: one branch still executes and control overhead is added.",
        "values": value_count, "operations": len(op_ids), "roots": len(roots),
        "movable_producer_union": sum(moved_by_kind.values()), "max_depth": max_depth,
        "root_kinds": root_kind_stats, "moved_kinds": moved_by_kind,
        "rejected_traversal_edges": rejects,
        "owners": [{"owner": owner_names[key], "movable": n} for key, n in moved_by_owner.most_common()],
        "profile_envelopes": {"total_samples": profile["samples"], "any_touched_samples": any_samples,
                              "any_touched_functions": any_functions, "all_covered_samples": all_samples,
                              "all_covered_functions": all_functions, "at_least_half_operations_samples": half_samples},
        "owner_functions": owner_function_stats,
        "top_helpers": sorted(helper_top, key=lambda item: item["samples"], reverse=True)[:100],
        "top_roots": [{"operation": f"o{op}", "owner": owner_names[own], "kind": name, "movable": n}
                      for n, op, own, name in sorted(top_roots, reverse=True)[:100]],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result_data, indent=2) + "\n")
    print(json.dumps({key: result_data[key] for key in ("movable_producer_union", "root_kinds", "profile_envelopes", "elapsed_seconds")}, indent=2))


if __name__ == "__main__":
    main()
