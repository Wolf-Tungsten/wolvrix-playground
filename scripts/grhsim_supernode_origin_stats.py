#!/usr/bin/env python3
"""Attribute grhsim General-phase supernodes to their origin RTL modules.

Reads ordinary GRH JSON and the emitter's manifest to join actual sn_<ordinal>
functions with virtual partition members and originModules. Frozen legacy
checkpoints remain readable for historical comparisons. Produces:

- a compact attribution manifest (--manifest, schema
  "grhsim-supernode-origin-manifest/v1"; per-op rows only with --op-level),
- a supernode module-purity report (--report, markdown),
- a machine-readable stdout summary (--json).

Checkpoints written before the `origin_modules` parameter exists are fully
supported: every op counts as uncovered and coverage reports as 0%.
"""

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

MANIFEST_SCHEMA = "grhsim-supernode-origin-manifest/v1"
ORIGIN_MODULES_PARAM = "origin_modules"

# wolvrix/include/grhsim/ir/model.hpp: enum class CpuPartitionKind.
CPU_PARTITION_KIND = {
    0: "Root",
    1: "Phase",
    2: "EventDomain",
    3: "Supernode",
    4: "Node",
    5: "ActiveWord",
    6: "EmitFunction",
}
# wolvrix/include/grhsim/ir/model.hpp: enum class CpuPhase.
CPU_PHASE = {
    0: "None",
    1: "Compute",
    2: "Commit",
    3: "Event",
    4: "General",
    5: "LargeSink",
    6: "Output",
}
# wolvrix/include/grhsim/ir/model.hpp: enum class CpuSupernodeCategory.
CPU_SUPERNODE_CATEGORY = {
    0: "NonSink",
    1: "SmallSinkEscape",
    2: "SmallSinkEvent",
}

PHASE_BRANCH_NAME = "General"


def fail(message):
    raise ValueError(message)


def require(condition, message):
    if not condition:
        fail(message)


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def load_model(path):
    try:
        model = json.loads(path.read_bytes())
    except FileNotFoundError:
        fail(f"{path}: file not found")
    except json.JSONDecodeError as ex:
        fail(f"{path}: invalid JSON: {ex}")
    require(isinstance(model, dict), f"{path}: top level must be a JSON object")
    if "graphs" in model:
        return model
    for key in ("format", "strings", "types", "values", "operations", "mappings"):
        require(key in model, f"{path}: missing required key {key!r}")
    return model


def load_strings(model, path):
    strings = model["strings"]
    require(isinstance(strings, list) and all(isinstance(s, str) for s in strings),
            f"{path}: 'strings' must be an array of strings")
    return strings


def string_at(strings, index, context):
    require(is_int(index) and 1 <= index <= len(strings),
            f"{context}: string id {index!r} out of range 1..{len(strings)}")
    return strings[index - 1]


def validate_op_rows(ops, counts, path):
    require(isinstance(ops, list), f"{path}: 'operations' must be an array")
    expected = counts.get("operations") if isinstance(counts, dict) else None
    if is_int(expected):
        require(expected == len(ops),
                f"{path}: counts.operations={expected} but 'operations' has {len(ops)} rows")
    seen = set()
    for row_index, op in enumerate(ops):
        context = f"{path}: operations[{row_index}]"
        require(isinstance(op, list) and len(op) == 9,
                f"{context}: op row must have 9 positional elements "
                "[id, opType, name, origin, operands, results, objectRefs, parameters, phase]")
        op_id, op_type, _name, _origin, operands, results, object_refs, parameters, phase = op
        require(is_int(op_id) and op_id >= 1, f"{context}: invalid op id {op_id!r}")
        require(op_id not in seen, f"{context}: duplicate op id {op_id}")
        seen.add(op_id)
        require(is_int(op_type) and op_type >= 1, f"{context}: invalid opType string id {op_type!r}")
        require(isinstance(operands, list) and all(is_int(v) for v in operands),
                f"{context}: operands must be an array of value ids")
        require(isinstance(results, list) and all(is_int(v) for v in results),
                f"{context}: results must be an array of value ids")
        require(isinstance(object_refs, list), f"{context}: objectRefs must be an array")
        require(isinstance(parameters, list), f"{context}: parameters must be an array")
        require(isinstance(phase, str), f"{context}: phase must be a string")


def find_cpu_mapping(model, strings, path):
    mappings = model["mappings"]
    require(isinstance(mappings, list) and mappings,
            f"{path}: 'mappings' must be a non-empty array")
    cpu_mappings = []
    for index, mapping in enumerate(mappings):
        context = f"{path}: mappings[{index}]"
        require(isinstance(mapping, list) and len(mapping) >= 3,
                f"{context}: mapping row must have at least [backend, schema, complete]")
        backend = string_at(strings, mapping[0], context + " backend")
        if backend == "cpu":
            cpu_mappings.append((index, mapping))
    require(cpu_mappings, f"{path}: no 'cpu' backend mapping found")
    require(len(cpu_mappings) == 1,
            f"{path}: expected exactly one 'cpu' backend mapping, found {len(cpu_mappings)}")
    index, mapping = cpu_mappings[0]
    require(len(mapping) >= 5,
            f"{path}: mappings[{index}]: cpu mapping is missing its CpuBackendMapping payload")
    cpu = mapping[4]
    require(isinstance(cpu, list) and len(cpu) >= 3,
            f"{path}: mappings[{index}][4]: CpuBackendMapping must have at least "
            "[stage, partitionRoot, partitions]")
    partitions = cpu[2]
    require(isinstance(partitions, list), f"{path}: mappings[{index}][4][2] must be an array")
    return cpu[1], partitions


def parse_partition_tail(row, context):
    """Decode the positional attr tail: [helperChunks, eventActs, category|range, enableGuard?]."""
    tail = row[6:]
    attrs = {"helper_chunks": [], "event_acts": None, "supernode_range": None,
             "category": None, "enable_guard": None}
    if not tail:
        return attrs
    chunks = tail[0]
    require(isinstance(chunks, list), f"{context}: attr tail helperChunks must be an array")
    for chunk in chunks:
        require(isinstance(chunk, list) and len(chunk) == 2 and all(is_int(v) for v in chunk),
                f"{context}: helper chunk must be [offset, count]")
        attrs["helper_chunks"].append({"offset": chunk[0], "count": chunk[1]})
    if len(tail) >= 2:
        acts = tail[1]
        require(isinstance(acts, list) and all(is_int(v) for v in acts),
                f"{context}: attr tail eventActs must be an array of integers")
        attrs["event_acts"] = acts
    if len(tail) >= 3:
        third = tail[2]
        if isinstance(third, list):
            require(len(third) == 2 and all(is_int(v) for v in third),
                    f"{context}: supernode range must be [offset, count]")
            attrs["supernode_range"] = {"offset": third[0], "count": third[1]}
            # An empty eventActs array before a range is a positional
            # placeholder, not an engaged annotation (see readCpuMapping).
            if attrs["event_acts"] == []:
                attrs["event_acts"] = None
        else:
            require(is_int(third) and third in CPU_SUPERNODE_CATEGORY,
                    f"{context}: unknown supernode category value {third!r}")
            attrs["category"] = CPU_SUPERNODE_CATEGORY[third]
    if len(tail) >= 4:
        require(attrs["category"] is not None,
                f"{context}: enableGuard requires a supernode category")
        require(is_int(tail[3]), f"{context}: enableGuard must be an integer")
        attrs["enable_guard"] = tail[3]
    require(len(tail) <= 4, f"{context}: unexpected extra attr tail elements: {tail[4:]!r}")
    return attrs


def parse_partitions(partitions, path):
    parsed = {}
    for row_index, row in enumerate(partitions):
        context = f"{path}: cpu partitions[{row_index}]"
        require(isinstance(row, list) and len(row) >= 6,
                f"{context}: partition row must have at least "
                "[id, parent, kind, phase, children, ops]")
        partition_id, parent, kind, phase, children, ops = row[:6]
        require(is_int(partition_id) and partition_id >= 1,
                f"{context}: invalid partition id {partition_id!r}")
        require(partition_id not in parsed,
                f"{context}: duplicate partition id {partition_id}")
        require(is_int(parent) and parent >= 0, f"{context}: invalid parent id {parent!r}")
        require(is_int(kind) and kind in CPU_PARTITION_KIND,
                f"{context}: unknown partition kind value {kind!r}")
        require(is_int(phase) and phase in CPU_PHASE,
                f"{context}: unknown cpu phase value {phase!r}")
        require(isinstance(children, list) and all(is_int(c) and c >= 1 for c in children),
                f"{context}: children must be an array of partition ids")
        require(isinstance(ops, list) and all(is_int(o) and o >= 1 for o in ops),
                f"{context}: ops must be an array of op ids")
        parsed[partition_id] = {
            "id": partition_id,
            "parent": parent,
            "kind": CPU_PARTITION_KIND[kind],
            "phase": CPU_PHASE[phase],
            "children": children,
            "ops": ops,
            "attrs": parse_partition_tail(row, context),
        }
    return parsed


def general_phase_branch(parsed, root_id, path):
    require(is_int(root_id) and root_id in parsed,
            f"{path}: partition root id {root_id!r} not found in partitions")
    root = parsed[root_id]
    require(root["kind"] == "Root",
            f"{path}: partition root {root_id} has kind {root['kind']!r}, expected 'Root'")
    branches = []
    for child_id in root["children"]:
        require(child_id in parsed,
                f"{path}: root child partition id {child_id} not found in partitions")
        child = parsed[child_id]
        if child["kind"] == "Phase" and child["phase"] == PHASE_BRANCH_NAME:
            branches.append(child)
    require(branches, f"{path}: partition root has no Phase child with phase 'General'")
    require(len(branches) == 1,
            f"{path}: partition root has {len(branches)} 'General' phase branches, expected 1")
    return branches[0]


def enumerate_supernodes(branch, parsed, path):
    """General-branch children in tree order; ordinal = index (matches sn_<ordinal>)."""
    supernodes = []
    for child_id in branch["children"]:
        require(child_id in parsed,
                f"{path}: General branch child partition id {child_id} not found in partitions")
        child = parsed[child_id]
        if child["kind"] == "Supernode":
            supernodes.append(child)
            continue
        require(child["kind"] == "EmitFunction",
                f"{path}: General branch child {child_id} has unexpected kind "
                f"{child['kind']!r} (expected 'Supernode' or 'EmitFunction')")
        require(not child["children"],
                f"{path}: EmitFunction partition {child_id} must be a leaf")
        require(child["attrs"]["supernode_range"] is not None,
                f"{path}: EmitFunction partition {child_id} is missing its supernode range")
    return supernodes


def supernode_member_ops(supernode, parsed, path):
    """Member ops = concatenation of the child Node partitions' op lists, in order."""
    require(supernode["attrs"]["category"] is not None or not supernode["children"],
            f"{path}: supernode partition {supernode['id']} has no child Node partitions")
    member_ops = []
    for child_id in supernode["children"]:
        require(child_id in parsed,
                f"{path}: supernode {supernode['id']} child partition id {child_id} "
                "not found in partitions")
        child = parsed[child_id]
        require(child["kind"] == "Node",
                f"{path}: supernode {supernode['id']} child {child_id} has kind "
                f"{child['kind']!r}, expected 'Node'")
        member_ops.extend(child["ops"])
    return member_ops


def parse_origin_modules(raw_value, context):
    """Accept a list of path strings or a single comma-joined string; tolerate both."""
    if isinstance(raw_value, str):
        if not raw_value:
            return []
        return [part.strip() for part in raw_value.split(",") if part.strip()]
    if isinstance(raw_value, list):
        paths = []
        for item in raw_value:
            require(isinstance(item, str),
                    f"{context}: origin_modules entries must be strings, got {item!r}")
            if "," in item:
                paths.extend(part.strip() for part in item.split(",") if part.strip())
            elif item:
                paths.append(item)
        return paths
    fail(f"{context}: origin_modules value must be a string or an array of strings, "
         f"got {type(raw_value).__name__}")


def op_origin_modules(op, strings, context):
    for parameter in op[7]:
        require(isinstance(parameter, list) and len(parameter) == 3,
                f"{context}: parameter rows must be [nameId, tag, value]")
        name = string_at(strings, parameter[0], context + " parameter name")
        if name != ORIGIN_MODULES_PARAM:
            continue
        tag, value = parameter[1], parameter[2]
        require(tag in ("string", "strings"),
                f"{context}: origin_modules parameter must use tag 'string' or 'strings', "
                f"got {tag!r}")
        return parse_origin_modules(value, context)
    return None


def build_value_widths(values, types, strings, path):
    """Map value id -> result bit width (0 when the type is not a core.logic)."""
    logic_types = set()
    type_width = {}
    for row_index, row in enumerate(types):
        context = f"{path}: types[{row_index}]"
        require(isinstance(row, list) and len(row) == 7,
                f"{context}: type row must have 7 positional elements")
        type_id = row[0]
        require(is_int(type_id) and type_id >= 1, f"{context}: invalid type id {type_id!r}")
        require(type_id not in type_width, f"{context}: duplicate type id {type_id}")
        name = string_at(strings, row[1], context)
        width = row[3]
        require(is_int(width) and width >= 0, f"{context}: invalid type width {width!r}")
        type_width[type_id] = width
        if name == "core.logic":
            logic_types.add(type_id)
    widths = {}
    for row_index, row in enumerate(values):
        context = f"{path}: values[{row_index}]"
        require(isinstance(row, list) and len(row) == 4,
                f"{context}: value row must have [id, type, name, origin]")
        value_id, type_id = row[0], row[1]
        require(is_int(value_id) and value_id >= 1, f"{context}: invalid value id {value_id!r}")
        require(value_id not in widths, f"{context}: duplicate value id {value_id}")
        require(type_id in type_width, f"{context}: unknown type id {type_id!r}")
        widths[value_id] = type_width[type_id] if type_id in logic_types else 0
    return widths


def op_result_width(op, value_widths):
    if len(op[5]) == 1:
        return value_widths.get(op[5][0], 0)
    return 0


def canonical_origins(paths, module_table, module_index):
    """Deduplicate module paths and intern them sorted for a stable origin-set."""
    return tuple(sorted({intern(module_table, module_index, module) for module in paths}))


def intern(table, index_of, value):
    index = index_of.get(value)
    if index is None:
        index = len(table)
        table.append(value)
        index_of[value] = index
    return index


def build_manifest(model_path, strings, ops_by_id, supernodes, value_widths, op_level):
    module_table = []
    module_index = {}
    kind_table = []
    kind_index = {}
    entries = []
    for ordinal, supernode in enumerate(supernodes):
        context = f"{model_path}: supernode ordinal {ordinal} (partition {supernode['id']})"
        member_ops = supernode["member_ops"]
        seen_ops = set()
        op_rows = []
        buckets = Counter()
        for op_id in member_ops:
            require(op_id not in seen_ops,
                    f"{context}: duplicate op id {op_id} in member op list")
            seen_ops.add(op_id)
            op = ops_by_id.get(op_id)
            require(op is not None, f"{context}: op id {op_id} not found in 'operations'")
            kind = intern(kind_table, kind_index, string_at(strings, op[1], context))
            width = op_result_width(op, value_widths)
            origins = canonical_origins(op_origin_modules(op, strings, context) or [],
                                        module_table, module_index)
            op_rows.append((op_id, kind, width, origins))
            buckets[(kind, width, origins)] += 1
        groups = [
            {"kind_idx": kind, "width": width, "origins": list(origins), "count": count}
            for (kind, width, origins), count in sorted(buckets.items())
        ]
        entry = {
            "ordinal": ordinal,
            "category": supernode["attrs"]["category"] or "Unknown",
            "phase": "General",
            "op_count": len(op_rows),
            "groups": groups,
        }
        if op_level:
            entry["ops"] = [[op_id, kind, width, list(origins)]
                            for op_id, kind, width, origins in op_rows]
        entries.append(entry)
    return {
        "schema": MANIFEST_SCHEMA,
        "model": str(model_path),
        "supernode_count": len(entries),
        "module_table": module_table,
        "kind_table": kind_table,
        "supernodes": entries,
    }


def grh_attr(op, key, default=None):
    value = op.get("attrs", {}).get(key)
    return default if value is None else value.get("vs", value.get("v"))


def build_grh_manifest(model_path, model, emitted_path, top=None, op_level=False):
    require(emitted_path is not None, "Ordinary GRH requires --emit-manifest; function ordinals cannot be inferred from partition names")
    emitted = json.loads(emitted_path.read_text())
    require(emitted.get("emitter") == "grhsim-cpu-st-cpp", "Unexpected emitter manifest")
    top = top or emitted.get("top")
    require(top == emitted.get("top"), "GRH top differs from emitter manifest")
    graphs = [graph for graph in model.get("graphs", []) if graph.get("symbol") == top]
    require(len(graphs) == 1, "GRH must contain exactly one selected top: " + str(top))
    graph = graphs[0]
    require(graph.get("metadata", {}).get("grhsim.stage", {}).get("v") == "sink-partitioned",
            "Origin analysis requires the emitted sink-partitioned GRH checkpoint")
    ops = {op["sym"]: op for op in graph["ops"]}
    require(len(ops) == len(graph["ops"]), "Duplicate GRH operation symbol")
    values = {value["sym"]: value for value in graph["vals"]}
    expected = {symbol for symbol, op in ops.items() if grh_attr(op, "grhsim.partition", [])[:2] == ["general", "nonsink"]}
    module_table, module_index, kind_table, kind_index, entries = [], {}, [], {}, []
    seen = set()
    functions = emitted.get("nonsink_functions")
    require(isinstance(functions, list), "Emitter manifest lacks nonsink_functions source map")
    for ordinal, function in enumerate(functions):
        require(function.get("ordinal") == ordinal, "Emitter ordinals must be consecutive in generated order")
        partition = function.get("partition")
        require(isinstance(partition, list) and len(partition) == 3 and partition[:2] == ["general", "nonsink"],
                "Invalid nonsink function partition")
        symbols = function.get("operation_symbols")
        require(isinstance(symbols, list) and symbols, "Empty or missing nonsink function membership")
        rows, buckets = [], Counter()
        for symbol in symbols:
            require(symbol in expected and symbol not in seen, "Unknown/duplicate emitter operation: " + str(symbol))
            seen.add(symbol)
            op = ops[symbol]
            require(grh_attr(op, "grhsim.partition", [])[:3] == partition, "Stale emitter partition for " + symbol)
            kind = intern(kind_table, kind_index, op["kind"])
            width = max((values[name]["w"] for name in op["out"]), default=0)
            paths = grh_attr(op, "originModules", [])
            require(isinstance(paths, list) and all(isinstance(path, str) for path in paths),
                    "Invalid originModules on " + symbol)
            origins = canonical_origins(paths, module_table, module_index)
            rows.append([symbol, kind, width, list(origins)])
            buckets[(kind, width, origins)] += 1
        entry = {"ordinal": ordinal, "category": "NonSink", "phase": "General", "partition": partition,
                 "op_count": len(rows), "groups": [
                     {"kind_idx": kind, "width": width, "origins": list(origins), "count": count}
                     for (kind, width, origins), count in sorted(buckets.items())]}
        if op_level:
            entry["ops"] = rows
        entries.append(entry)
    require(seen == expected, "Emitter source map omits GRH nonsink members")
    return {"schema": MANIFEST_SCHEMA, "model": str(model_path), "emit_manifest": str(emitted_path),
            "top": top, "supernode_count": len(entries), "module_table": module_table,
            "kind_table": kind_table, "supernodes": entries}


def shannon_entropy(counts):
    total = sum(counts)
    if total <= 0:
        return 0.0
    entropy = 0.0
    for count in counts:
        if count:
            probability = count / total
            entropy -= probability * math.log(probability)
    return entropy


def analyze_supernode(entry, module_table):
    module_ops = Counter()
    for group in entry["groups"]:
        origins = group["origins"]
        if not origins:
            continue
        per_module = group["count"] / len(origins)
        for index in origins:
            module_ops[module_table[index]] += per_module
    uncovered = sum(group["count"] for group in entry["groups"] if not group["origins"])
    op_count = entry["op_count"]
    covered = op_count - uncovered
    distinct = len(module_ops)
    if module_ops and covered:
        top_module, top_ops = max(module_ops.items(), key=lambda item: (item[1], item[0]))
        max_module_share = top_ops / covered
        entropy = shannon_entropy(list(module_ops.values()))
    else:
        top_module, max_module_share, entropy = None, 0.0, 0.0
    return {
        "ordinal": entry["ordinal"],
        "category": entry["category"],
        "op_count": op_count,
        "covered_ops": covered,
        "uncovered_ops": uncovered,
        "group_count": len(entry["groups"]),
        "distinct_modules": distinct,
        "single_origin": distinct == 1,
        "max_module_share": max_module_share,
        "entropy": entropy,
        "top_module": top_module,
        "top_modules": [
            {"module": module, "op_share": count / covered}
            for module, count in sorted(module_ops.items(), key=lambda item: (-item[1], item[0]))[:3]
        ] if covered else [],
    }


def summarize(stats, top):
    def weighted(rows, weight_of):
        total_weight = sum(weight_of(row) for row in rows)
        if not total_weight:
            return 0.0
        return sum(weight_of(row) for row in rows if row["single_origin"]) / total_weight

    def shares(rows):
        return {
            "by_supernode": weighted(rows, lambda row: 1),
            "by_op": weighted(rows, lambda row: row["op_count"]),
            "by_group": weighted(rows, lambda row: row["group_count"]),
        }

    by_category = {}
    for category in sorted({row["category"] for row in stats}):
        rows = [row for row in stats if row["category"] == category]
        by_category[category] = {
            "supernodes": len(rows),
            "ops": sum(row["op_count"] for row in rows),
            "covered_ops": sum(row["covered_ops"] for row in rows),
            "single_origin_supernodes": sum(row["single_origin"] for row in rows),
            "single_origin_share": shares(rows),
            "max_entropy": max((row["entropy"] for row in rows), default=0.0),
        }
    total_ops = sum(row["op_count"] for row in stats)
    covered_ops = sum(row["covered_ops"] for row in stats)
    most_mixed = sorted(stats, key=lambda row: (-row["entropy"], -row["op_count"], row["ordinal"]))[:top]
    return {
        "supernodes": len(stats),
        "ops": total_ops,
        "covered_ops": covered_ops,
        "uncovered_ops": total_ops - covered_ops,
        "coverage": covered_ops / total_ops if total_ops else 0.0,
        "single_origin_supernodes": sum(row["single_origin"] for row in stats),
        "single_origin_share": shares(stats),
        "by_category": by_category,
        "most_mixed": most_mixed,
    }


def percent(value):
    return f"{100.0 * value:.1f}%"


def write_report(summary, model_path, out):
    print("# Supernode origin-module purity report", file=out)
    print(file=out)
    print(f"- model: `{model_path}`", file=out)
    print(f"- General-phase supernodes: {summary['supernodes']}", file=out)
    print(f"- member ops: {summary['ops']} (covered {summary['covered_ops']}, "
          f"uncovered {summary['uncovered_ops']})", file=out)
    print(f"- origin_modules coverage: {percent(summary['coverage'])}", file=out)
    shares = summary["single_origin_share"]
    print(f"- single-origin supernodes: {summary['single_origin_supernodes']} "
          f"({percent(shares['by_supernode'])} by supernode count, "
          f"{percent(shares['by_op'])} by op count, "
          f"{percent(shares['by_group'])} by group count)", file=out)
    if summary["coverage"] == 0.0:
        print(file=out)
        print("> No op carries an `origin_modules` parameter in this checkpoint; "
              "purity metrics below only reflect attribution coverage, not module mixing.",
              file=out)
    print(file=out)
    print("## By category", file=out)
    print(file=out)
    print("| category | supernodes | ops | covered ops | single-origin | "
          "single-origin (by sn / by op / by group) | max entropy |", file=out)
    print("| --- | ---: | ---: | ---: | ---: | --- | ---: |", file=out)
    for category, row in summary["by_category"].items():
        cat_shares = row["single_origin_share"]
        print(f"| {category} | {row['supernodes']} | {row['ops']} | {row['covered_ops']} | "
              f"{row['single_origin_supernodes']} | "
              f"{percent(cat_shares['by_supernode'])} / {percent(cat_shares['by_op'])} / "
              f"{percent(cat_shares['by_group'])} | {row['max_entropy']:.3f} |", file=out)
    print(file=out)
    print(f"## Top {len(summary['most_mixed'])} most-mixed supernodes (by Shannon entropy)", file=out)
    print(file=out)
    print("| rank | ordinal (sn_<ordinal>) | category | ops | covered | distinct modules | "
          "max module share | entropy | top modules |", file=out)
    print("| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |", file=out)
    for rank, row in enumerate(summary["most_mixed"], start=1):
        top_modules = ", ".join(
            f"`{item['module']}` {percent(item['op_share'])}" for item in row["top_modules"]
        ) or "-"
        print(f"| {rank} | {row['ordinal']} | {row['category']} | {row['op_count']} | "
              f"{row['covered_ops']} | {row['distinct_modules']} | "
              f"{percent(row['max_module_share'])} | {row['entropy']:.3f} | {top_modules} |",
              file=out)
    print(file=out)
    print("Entropy is the Shannon entropy (natural log) of the per-module op-count "
          "distribution within one supernode; multi-origin ops split their count evenly "
          "across their origin modules. `max module share` is the largest single module's "
          "fraction of the supernode's covered ops.", file=out)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", type=Path, required=True,
                        help="ordinary GRH checkpoint (or a frozen historical model)")
    parser.add_argument("--emit-manifest", type=Path,
                        help="generated model/manifest.json; required for ordinary GRH")
    parser.add_argument("--graph-top", help="selected GRH top (default: emitter manifest top)")
    parser.add_argument("--manifest", type=Path,
                        help="write the supernode origin manifest JSON to this path")
    parser.add_argument("--report", type=Path,
                        help="write the markdown purity report to this path")
    parser.add_argument("--top", type=int, default=20,
                        help="number of most-mixed supernodes to report (default 20)")
    parser.add_argument("--op-level", action="store_true",
                        help="include per-op rows in the manifest (default: aggregate groups only)")
    parser.add_argument("--json", action="store_true",
                        help="print the machine-readable summary JSON to stdout")
    args = parser.parse_args()
    if args.top < 0:
        parser.error("--top must be non-negative")

    try:
        model = load_model(args.model)
        if "graphs" in model:
            manifest = build_grh_manifest(args.model, model, args.emit_manifest, args.graph_top, args.op_level)
        else:
            counts = model.get("counts", {})
            strings = load_strings(model, args.model)
            ops = model["operations"]
            validate_op_rows(ops, counts, args.model)
            ops_by_id = {op[0]: op for op in ops}
            root_id, partitions = find_cpu_mapping(model, strings, args.model)
            parsed = parse_partitions(partitions, args.model)
            branch = general_phase_branch(parsed, root_id, args.model)
            supernodes = enumerate_supernodes(branch, parsed, args.model)
            for supernode in supernodes:
                supernode["member_ops"] = supernode_member_ops(supernode, parsed, args.model)
            value_widths = build_value_widths(model["values"], model["types"], strings, args.model)
            manifest = build_manifest(args.model, strings, ops_by_id, supernodes, value_widths, args.op_level)
        stats = [analyze_supernode(entry, manifest["module_table"])
                 for entry in manifest["supernodes"]]
        summary = summarize(stats, args.top)
        summary["model"] = str(args.model)
        summary["schema"] = MANIFEST_SCHEMA

        if args.manifest is not None:
            args.manifest.parent.mkdir(parents=True, exist_ok=True)
            args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        if args.report is not None:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            with args.report.open("w", encoding="utf-8") as out:
                write_report(summary, args.model, out)
        if args.json:
            print(json.dumps(summary, indent=2))
        else:
            print(f"supernodes={summary['supernodes']} ops={summary['ops']} "
                  f"coverage={percent(summary['coverage'])} "
                  f"single_origin={summary['single_origin_supernodes']} "
                  f"by_sn={percent(summary['single_origin_share']['by_supernode'])} "
                  f"by_op={percent(summary['single_origin_share']['by_op'])} "
                  f"by_group={percent(summary['single_origin_share']['by_group'])}")
    except ValueError as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
