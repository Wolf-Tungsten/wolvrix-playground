"""Stream F21 ordinary-Node DAG comparison; expression contents are out of scope."""
from __future__ import annotations

import argparse
import heapq
import json
import re
import sys
import time
from array import array
from collections import Counter, deque
from pathlib import Path

TREE_NODE = re.compile(
    r'\{"parent": (\d+), "kind": "(module|declaration|expression|field|element)", '
    r'"name": ("(?:\\.|[^"\\])*")(?:, "index": (-?\d+))?\},?'
)
RECORD_ID = re.compile(r'\{"id": (\d+)')
SEMANTIC_IDS = re.compile(r'"semanticIds": \[([0-9, ]*)\]')
OPERANDS = re.compile(r'"in": \[([0-9, ]*)\]')
RESULTS = re.compile(r'"out": \[([0-9, ]*)\]')
WHEN_COND = re.compile(r'(?:^|\$)WHEN_COND_\d+$')
GENERATED_GUARD = re.compile(r'guard_\d+$')
KIND = {name: index for index, name in enumerate(
    ("invalid", "module", "declaration", "expression", "field", "element"))}
UNSET = 0xFFFFFFFF
MASK32 = 0xFFFFFFFF


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


def normalize(name: str) -> str:
    return name.replace("$$", "__DOT__")


def pack(source: int, target: int) -> int:
    return (source << 32) | target


def unpack(edge: int) -> tuple[int, int]:
    return edge >> 32, edge & MASK32


def int_array(pattern: re.Pattern[str], line: str) -> list[int] | None:
    match = pattern.search(line)
    if not match:
        return None
    text = match.group(1)
    return [] if not text else [int(item) for item in text.split(",")]


class GeneratedGraph:
    def __init__(self, count: int):
        self.count = count
        self.pre = [set() for _ in range(count)]
        self.succ = [set() for _ in range(count)]
        self.next = [set() for _ in range(count)]


def add_projected(raw: set[int], generated: GeneratedGraph, node_count: int,
                  source_gid: int, target_gid: int) -> None:
    source_ordinary = source_gid <= node_count
    target_ordinary = target_gid <= node_count
    if source_ordinary and target_ordinary:
        raw.add(pack(source_gid - 1, target_gid - 1))
    elif source_ordinary:
        generated.pre[target_gid - node_count - 1].add(source_gid - 1)
    elif target_ordinary:
        generated.succ[source_gid - node_count - 1].add(target_gid - 1)
    else:
        generated.next[source_gid - node_count - 1].add(target_gid - node_count - 1)


def contract_generated(raw: set[int], generated: GeneratedGraph,
                       names: list[str] | None = None):
    result = set(raw)
    indegree = [0] * generated.count
    for targets in generated.next:
        for target in targets:
            indegree[target] += 1
    pending = deque(index for index, degree in enumerate(indegree) if degree == 0)
    processed = 0
    while pending:
        source = pending.popleft()
        processed += 1
        origins = generated.pre[source]
        for target in generated.succ[source]:
            for origin in origins:
                result.add(pack(origin, target))
        for target in generated.next[source]:
            generated.pre[target].update(origins)
            indegree[target] -= 1
            if indegree[target] == 0:
                pending.append(target)
    diagnostics = {
        "blocked_generated_nodes": 0,
        "cyclic_generated_nodes": 0,
        "cyclic_components": 0,
        "cyclic_component_examples": [],
    }
    if processed == generated.count:
        return result, diagnostics

    remaining = {index for index, degree in enumerate(indegree) if degree > 0}
    reachability = {}
    for start in remaining:
        reached = {start}
        pending_nodes = [start]
        while pending_nodes:
            source = pending_nodes.pop()
            for target in generated.next[source]:
                if target in remaining and target not in reached:
                    reached.add(target)
                    pending_nodes.append(target)
        reachability[start] = reached
    components = []
    unassigned = set(remaining)
    while unassigned:
        start = min(unassigned)
        component = {node for node in unassigned
                     if node in reachability[start] and start in reachability[node]}
        components.append(sorted(component))
        unassigned.difference_update(component)
    component_of = {}
    for component_id, component in enumerate(components):
        for node in component:
            component_of[node] = component_id
    component_pre = [set() for _ in components]
    component_succ = [set() for _ in components]
    component_next = [set() for _ in components]
    for component_id, component in enumerate(components):
        for node in component:
            component_pre[component_id].update(generated.pre[node])
            component_succ[component_id].update(generated.succ[node])
            for target in generated.next[node]:
                target_component = component_of[target]
                if target_component != component_id:
                    component_next[component_id].add(target_component)
    component_indegree = [0] * len(components)
    for targets in component_next:
        for target in targets:
            component_indegree[target] += 1
    pending_components = deque(index for index, degree in enumerate(component_indegree) if degree == 0)
    processed_components = 0
    while pending_components:
        source = pending_components.popleft()
        processed_components += 1
        origins = component_pre[source]
        for target in component_succ[source]:
            for origin in origins:
                result.add(pack(origin, target))
        for target in component_next[source]:
            component_pre[target].update(origins)
            component_indegree[target] -= 1
            if component_indegree[target] == 0:
                pending_components.append(target)
    if processed_components != len(components):
        raise AssertionError("SCC condensation unexpectedly contains a cycle")
    cyclic = [component for component in components
              if len(component) > 1 or any(node in generated.next[node] for node in component)]
    diagnostics = {
        "blocked_generated_nodes": len(remaining),
        "cyclic_generated_nodes": sum(len(component) for component in cyclic),
        "cyclic_components": len(cyclic),
        "cyclic_component_examples": [
            [names[node] if names is not None else node for node in component]
            for component in cyclic[:20]
        ],
    }
    return result, diagnostics


def load_nodes(candidates_path: Path, unmatched_path: Path) -> tuple[list[str], dict[str, int]]:
    with unmatched_path.open("r", encoding="utf-8") as stream:
        unmatched = {line.rstrip("\n") for line in stream}
    with candidates_path.open("r", encoding="utf-8") as stream:
        names = [line.rstrip("\n") for line in stream if line.rstrip("\n") not in unmatched]
    return names, {name: index for index, name in enumerate(names)}


def parse_semantic_tree(source: Path, name_to_id: dict[str, int]):
    node_count = len(name_to_id)
    paths = ["", ""]
    components = ["", ""]
    parents = array("I", [0, 0])
    node_kinds = array("B", [0, KIND["module"]])
    sid_to_gid = array("I", [0, 0])
    declaration_nodes: dict[tuple[int, str], int] = {}
    module_children: list[tuple[int, str]] = []
    guard_names: list[str] = []
    kind_counts: Counter[str] = Counter()
    roots = 0
    with source.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.startswith('      "declaredSymbols":'):
                break
            match = TREE_NODE.fullmatch(line.strip())
            if not match:
                continue
            parent = int(match.group(1))
            kind_text = match.group(2)
            kind = KIND[kind_text]
            name = json.loads(match.group(3))
            index = match.group(4)
            kind_counts[kind_text] += 1
            if parent == 0:
                roots += 1
                continue
            if parent >= len(paths):
                raise ValueError(f"invalid semantic parent {parent} at node {len(paths)}")
            semantic_id = len(paths)
            paths.append("")
            components.append("[" + str(index) + "]" if kind == KIND["element"] else name)
            parents.append(parent)
            node_kinds.append(kind)
            sid_to_gid.append(0)
            if kind == KIND["declaration"] and node_kinds[parent] == KIND["module"]:
                declaration_nodes[(parent, name)] = semantic_id
            elif kind == KIND["module"]:
                module_children.append((parent, name))
    if roots != 1:
        raise ValueError(f"expected one flattened semantic root, got {roots}")
    instance_declarations: set[int] = set()
    for parent, name in module_children:
        declaration = declaration_nodes.get((parent, name))
        if declaration is None:
            raise ValueError(f"module child lacks instance declaration: {parent}:{name}")
        instance_declarations.add(declaration)
    for semantic_id in range(2, len(paths)):
        parent = parents[semantic_id]
        kind = node_kinds[semantic_id]
        if kind == KIND["element"]:
            separator = ""
        elif (kind == KIND["module"] or node_kinds[parent] == KIND["module"]
              or parent in instance_declarations):
            separator = "$" if paths[parent] else ""
        else:
            separator = "__DOT__"
        path = paths[parent] + separator + components[semantic_id]
        paths[semantic_id] = path
        ordinary = name_to_id.get(path, -1)
        is_guard = (kind == KIND["expression"] and node_kinds[parent] == KIND["module"]
                    and GENERATED_GUARD.fullmatch(components[semantic_id]))
        if is_guard:
            guard_names.append(path)
            sid_to_gid[semantic_id] = node_count + len(guard_names)
        elif ordinary >= 0:
            sid_to_gid[semantic_id] = ordinary + 1
    guard_path_collisions = [path for path in guard_names if path in name_to_id]
    stats = {
        "semantic_nodes": sum(kind_counts.values()),
        "semantic_node_kinds": dict(sorted(kind_counts.items())),
        "ordinary_nodes": node_count,
        "guard_slots": len(guard_names),
        "guard_path_collisions": len(guard_path_collisions),
        "guard_path_collision_examples": guard_path_collisions[:20],
        "instance_declarations": len(instance_declarations),
    }
    log(f"GRH semantic tree: {stats}")
    return sid_to_gid, guard_names, stats


def collect_gsim(source: Path, name_to_id: dict[str, int], original_init: Path | None = None,
                 split_map: Path | None = None, ambiguous_names: Path | None = None,
                 drop_self: bool = False, include_unmatched: bool = False):
    node_count = len(name_to_id)
    coarsen = split_map is not None
    if coarsen and original_init is None:
        raise ValueError("split-array coarsening requires the original Init JSON")
    original_ids = {}
    member_map = {}
    member_ids = {}
    member_name_counts = Counter()
    ambiguous = set()
    explicit_split_map = split_map is not None and split_map.suffix == ".json"
    if coarsen:
        with original_init.open("r", encoding="utf-8") as stream:
            for line in stream:
                if line.strip() == '"edges": [':
                    break
                if not line.lstrip().startswith('{"id":'):
                    continue
                record = json.loads(line.strip().rstrip(","))
                original_ids[record["id"]] = normalize(record["name"])
        with split_map.open("r", encoding="utf-8") as stream:
            if explicit_split_map:
                for line in stream:
                    if not line.lstrip().startswith('{"parentId":'):
                        continue
                    record = json.loads(line.strip().rstrip(","))
                    member_ids[record["memberId"]] = normalize(record["parentName"])
                    member_name_counts[record["memberName"]] += 1
            else:
                for line in stream:
                    member, base = line.rstrip("\n").split("\t")
                    member_map[member] = base
        if ambiguous_names is not None and not explicit_split_map:
            with ambiguous_names.open("r", encoding="utf-8") as stream:
                ambiguous = {line.rstrip("\n") for line in stream}
    ambiguous_member_names = {name for name, count in member_name_counts.items() if count > 1}

    def resolve_member(name):
        if name in member_map:
            return {member_map[name]}
        if explicit_split_map:
            return set()
        candidates = set()
        probe = name
        while True:
            if probe in member_map:
                candidates.add(member_map[probe])
            if not probe.endswith("_0"):
                break
            probe = probe[:-2]
        return candidates

    when_to_index: dict[str, int] = {}
    resolved_names = {}
    ambiguous_node_names = set()
    dumped_nodes = 0
    valid_nodes = 0
    resolved_split_nodes = 0
    unresolved_new_nodes = 0
    ambiguous_split_nodes = 0
    with source.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip() == '"edges": [':
                break
            if not line.lstrip().startswith('{"id":'):
                continue
            dumped_nodes += 1
            record = json.loads(line.strip().rstrip(","))
            base = normalize(record["name"])
            if coarsen:
                if record["status"] != "VALID_NODE":
                    continue
                valid_nodes += 1
                original = original_ids.get(record["id"])
                if original is not None:
                    base = original
                elif explicit_split_map:
                    parent = member_ids.get(record["id"])
                    if parent is None:
                        unresolved_new_nodes += 1
                        base = None
                    elif record["name"] in ambiguous_member_names:
                        ambiguous_split_nodes += 1
                        ambiguous_node_names.add(record["name"])
                        base = None
                    else:
                        base = parent
                        resolved_split_nodes += 1
                else:
                    candidates = set() if record["name"] in ambiguous else resolve_member(record["name"])
                    if len(candidates) == 1:
                        base = next(iter(candidates))
                        resolved_split_nodes += 1
                    else:
                        unresolved_new_nodes += 1
            if base is not None:
                resolved_names[record["name"]] = base
                if record["type"] == "NODE_OTHERS" and WHEN_COND.search(record["name"]):
                    when_to_index[base] = len(when_to_index)
    extra_ordinary_nodes = 0
    if include_unmatched:
        additional = sorted(set(resolved_names.values()) - set(name_to_id) - set(when_to_index))
        for base in additional:
            name_to_id[base] = len(name_to_id)
        extra_ordinary_nodes = len(additional)
        node_count = len(name_to_id)
    generated = GeneratedGraph(len(when_to_index))
    raw: set[int] = set()
    total_edges = 0
    ambiguous_edges = 0
    in_edges = False
    with source.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not in_edges:
                if line.strip() == '"edges": [':
                    in_edges = True
                continue
            if not line.lstrip().startswith('["'):
                continue
            source_name, target_name = json.loads(line.strip().rstrip(","))
            total_edges += 1
            if source_name in ambiguous_node_names or target_name in ambiguous_node_names:
                ambiguous_edges += 1
                continue
            source_name = resolved_names.get(source_name, normalize(source_name))
            target_name = resolved_names.get(target_name, normalize(target_name))
            source_ordinary = name_to_id.get(source_name, -1)
            target_ordinary = name_to_id.get(target_name, -1)
            source_gid = source_ordinary + 1 if source_ordinary >= 0 else 0
            target_gid = target_ordinary + 1 if target_ordinary >= 0 else 0
            if not source_gid and source_name in when_to_index:
                source_gid = node_count + when_to_index[source_name] + 1
            if not target_gid and target_name in when_to_index:
                target_gid = node_count + when_to_index[target_name] + 1
            if drop_self and source_gid == target_gid:
                continue
            if source_gid and target_gid:
                add_projected(raw, generated, node_count, source_gid, target_gid)
    log(f"GSIM raw projected edges: {len(raw)}; contracting {len(when_to_index)} WHEN_COND nodes")
    contracted, contraction_diagnostics = contract_generated(raw, generated)
    stats = {
        "coarsen": {
            "enabled": coarsen,
            "drop_self": drop_self,
            "explicit_member_id_mapping": explicit_split_map,
            "valid_nodes": valid_nodes,
            "resolved_split_nodes": resolved_split_nodes,
            "unresolved_new_nodes": unresolved_new_nodes,
            "ambiguous_split_nodes": ambiguous_split_nodes,
            "ambiguous_edges": ambiguous_edges,
            "include_unmatched": include_unmatched,
            "extra_ordinary_nodes": extra_ordinary_nodes,
        },
        "contraction": contraction_diagnostics,
        "dumped_nodes_including_memory": dumped_nodes,
        "total_prev_next_edges": total_edges,
        "when_cond_nodes": len(when_to_index),
        "raw_projected_edges": len(raw),
        "contracted_projected_edges": len(contracted),
    }
    log(f"GSIM DAG: {stats}")
    return raw, contracted, stats


def build_value_groups(source: Path, sid_to_gid: array, name_to_id: dict[str, int],
                       guard_names: list[str]):
    ordinary_count = len(name_to_id)
    offsets = array("I", [UNSET])
    sizes = array("I", [0])
    pool = array("I")

    def ensure(value: int) -> None:
        if value >= len(offsets):
            missing = value + 1 - len(offsets)
            offsets.extend([UNSET] * missing)
            sizes.extend([0] * missing)

    def groups(semantic_ids: list[int]) -> list[int]:
        if len(semantic_ids) > 8:
            if max(semantic_ids) >= len(sid_to_gid):
                raise ValueError(f"SemanticId {max(semantic_ids)} exceeds tree size {len(sid_to_gid)}")
            return sorted({sid_to_gid[semantic_id] for semantic_id in semantic_ids
                           if sid_to_gid[semantic_id]})
        result: list[int] = []
        for semantic_id in semantic_ids:
            if semantic_id >= len(sid_to_gid):
                raise ValueError(f"SemanticId {semantic_id} exceeds tree size {len(sid_to_gid)}")
            gid = sid_to_gid[semantic_id]
            if gid and gid not in result:
                result.append(gid)
        return result

    def assign(value: int, value_groups: list[int]) -> None:
        ensure(value)
        if offsets[value] != UNSET:
            return
        offsets[value] = len(pool)
        sizes[value] = len(value_groups)
        pool.extend(value_groups)

    section = ""
    value_records = 0
    operation_records = 0
    relevant_operations = 0
    missing_operation_semantics = 0
    values_without_semantics = 0
    named_source_guard_ids = 0
    with source.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.startswith('      "vals":'):
                section = "vals"
                continue
            if line.startswith('      "ops":'):
                section = "ops"
                continue
            if not section or not line.startswith('        {"id":'):
                continue
            record_id = int(RECORD_ID.match(line[8:]).group(1))
            semantic_ids = int_array(SEMANTIC_IDS, line)
            if section == "vals":
                value_records += 1
                if semantic_ids is not None and '"sym":' in line:
                    for semantic_id in semantic_ids:
                        gid = sid_to_gid[semantic_id]
                        if gid <= ordinary_count:
                            continue
                        ordinary = name_to_id.get(guard_names[gid - ordinary_count - 1], -1)
                        if ordinary >= 0:
                            sid_to_gid[semantic_id] = ordinary + 1
                            named_source_guard_ids += 1
                if semantic_ids is None:
                    values_without_semantics += 1
                    ensure(record_id)
                else:
                    assign(record_id, groups(semantic_ids))
                continue
            operation_records += 1
            if semantic_ids is None:
                missing_operation_semantics += 1
                semantic_ids = []
            operation_groups = groups(semantic_ids)
            if operation_groups:
                relevant_operations += 1
            results = int_array(RESULTS, line)
            if results is None:
                raise ValueError(f"operation {record_id} lacks an out array")
            for value in results:
                ensure(value)
                if offsets[value] == UNSET:
                    assign(value, operation_groups)
    stats = {
        "value_records": value_records,
        "max_value_id": len(offsets) - 1,
        "operation_records": operation_records,
        "relevant_operations": relevant_operations,
        "missing_operation_semantics": missing_operation_semantics,
        "values_without_semantics": values_without_semantics,
        "named_source_guard_ids_reclassified": named_source_guard_ids,
        "unset_values_after_producer_propagation": offsets.count(UNSET) - 1,
        "value_group_links": len(pool),
    }
    log(f"GRH value groups: {stats}")
    return offsets, sizes, pool, stats


def project_grh_edges(source: Path, sid_to_gid: array, ordinary_count: int,
                      guard_names: list[str], offsets: array, sizes: array, pool: array):
    guard_count = len(guard_names)
    generated = GeneratedGraph(guard_count)
    ordinary_out: dict[int, set[int]] = {}
    in_ops = False
    relevant_operations = 0
    relevant_operands = 0
    out_of_scope_operands = 0
    unresolved_operands = 0
    unresolved_examples = []
    projected_pair_attempts = 0
    max_operation_groups = 0
    largest_operations = []
    large_logs = 0

    def groups(semantic_ids: list[int]) -> list[int]:
        if len(semantic_ids) > 8:
            return sorted({sid_to_gid[semantic_id] for semantic_id in semantic_ids
                           if sid_to_gid[semantic_id]})
        result: list[int] = []
        for semantic_id in semantic_ids:
            gid = sid_to_gid[semantic_id]
            if gid and gid not in result:
                result.append(gid)
        return result

    with source.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not in_ops:
                if line.startswith('      "ops":'):
                    in_ops = True
                continue
            if not line.startswith('        {"id":'):
                continue
            semantic_ids = int_array(SEMANTIC_IDS, line) or []
            operation_groups = groups(semantic_ids)
            if not operation_groups:
                continue
            relevant_operations += 1
            max_operation_groups = max(max_operation_groups, len(operation_groups))
            if relevant_operations % 5000000 == 0:
                log(f"GRH projection progress: {relevant_operations} relevant ops, "
                    f"{len(ordinary_out)} targets, {projected_pair_attempts} group pairs")
            operands = int_array(OPERANDS, line)
            if operands is None:
                raise ValueError("operation lacks an in array")
            source_groups: set[int] = set()
            for value in operands:
                relevant_operands += 1
                if value >= len(offsets) or offsets[value] == UNSET:
                    unresolved_operands += 1
                    if len(unresolved_examples) < 20:
                        unresolved_examples.append({"operation": int(RECORD_ID.match(line[8:]).group(1)),
                                                    "value": value, "consumer_gids": operation_groups})
                    continue
                start = offsets[value]
                size = sizes[value]
                if not size:
                    out_of_scope_operands += 1
                    continue
                source_groups.update(pool[index] for index in range(start, start + size))
            pair_count = len(source_groups) * len(operation_groups)
            projected_pair_attempts += pair_count
            if pair_count > 1000000:
                operation_id = int(RECORD_ID.match(line[8:]).group(1))
                item = (pair_count, operation_id, len(source_groups), len(operation_groups), len(operands))
                if len(largest_operations) < 20:
                    heapq.heappush(largest_operations, item)
                elif item > largest_operations[0]:
                    heapq.heapreplace(largest_operations, item)
                if pair_count > 50000000 and large_logs < 10:
                    large_logs += 1
                    log(f"large GRH group product: op={operation_id}, sources={len(source_groups)}, "
                        f"targets={len(operation_groups)}, pairs={pair_count}")
            ordinary_sources = {gid - 1 for gid in source_groups if gid <= ordinary_count}
            guard_sources = {gid - ordinary_count - 1 for gid in source_groups if gid > ordinary_count}
            ordinary_targets = {gid - 1 for gid in operation_groups if gid <= ordinary_count}
            guard_targets = {gid - ordinary_count - 1 for gid in operation_groups if gid > ordinary_count}
            for target in ordinary_targets:
                ordinary_out.setdefault(target, set()).update(ordinary_sources)
            for target in guard_targets:
                generated.pre[target].update(ordinary_sources)
            for source in guard_sources:
                generated.succ[source].update(ordinary_targets)
                generated.next[source].update(guard_targets)
    for source in range(guard_count):
        generated.next[source].discard(source)
    raw: set[int] = set()
    for target, sources in ordinary_out.items():
        for source in sources:
            if source != target:
                raw.add(pack(source, target))
    del ordinary_out
    log(f"GRH raw projected edges: {len(raw)}; contracting {guard_count} guard nodes")
    contracted, contraction_diagnostics = contract_generated(raw, generated, guard_names)
    large_examples = [{
        "group_pairs": pair_count, "operation": operation_id,
        "source_groups": source_count, "target_groups": target_count, "operands": operand_count,
    } for pair_count, operation_id, source_count, target_count, operand_count
        in sorted(largest_operations, reverse=True)]
    stats = {
        "contraction": contraction_diagnostics,
        "relevant_operations": relevant_operations,
        "relevant_operands": relevant_operands,
        "projected_pair_attempts": projected_pair_attempts,
        "max_operation_groups": max_operation_groups,
        "largest_group_products": large_examples,
        "out_of_scope_operands": out_of_scope_operands,
        "unresolved_operands": unresolved_operands,
        "unresolved_examples": unresolved_examples,
        "raw_projected_edges": len(raw),
        "contracted_projected_edges": len(contracted),
    }
    log(f"GRH DAG: {stats}")
    return raw, contracted, stats


def edge_metrics(gsim: set[int], grh: set[int], keep_differences: bool):
    gsim_only = {edge for edge in gsim if edge not in grh} if keep_differences else None
    grh_only = {edge for edge in grh if edge not in gsim} if keep_differences else None
    gsim_only_count = len(gsim_only) if keep_differences else sum(1 for edge in gsim if edge not in grh)
    grh_only_count = len(grh_only) if keep_differences else sum(1 for edge in grh if edge not in gsim)
    matched = len(gsim) - gsim_only_count
    result = {
        "gsim_edges": len(gsim),
        "grh_edges": len(grh),
        "matched_edges": matched,
        "gsim_only_edges": gsim_only_count,
        "grh_only_edges": grh_only_count,
        "precision": matched / len(grh) if grh else 1.0,
        "recall": matched / len(gsim) if gsim else 1.0,
    }
    return result, gsim_only, grh_only


def summarize_degrees(values: array) -> dict[str, int]:
    ordered = sorted(values)
    if not ordered:
        return {"p50": 0, "p90": 0, "p99": 0, "max": 0}
    return {
        "p50": ordered[(len(ordered) - 1) * 50 // 100],
        "p90": ordered[(len(ordered) - 1) * 90 // 100],
        "p99": ordered[(len(ordered) - 1) * 99 // 100],
        "max": ordered[-1],
    }


def degree_comparison(gsim: set[int], grh: set[int], names: list[str]):
    count = len(names)
    gsim_in = array("I", [0]) * count
    gsim_out = array("I", [0]) * count
    grh_in = array("I", [0]) * count
    grh_out = array("I", [0]) * count
    for edges, incoming, outgoing in ((gsim, gsim_in, gsim_out), (grh, grh_in, grh_out)):
        for edge in edges:
            source, target = unpack(edge)
            outgoing[source] += 1
            incoming[target] += 1
    different_nodes = 0
    largest = []
    for node in range(count):
        delta = abs((gsim_in[node] + gsim_out[node]) - (grh_in[node] + grh_out[node]))
        if not delta:
            continue
        different_nodes += 1
        item = (delta, node)
        if len(largest) < 20:
            heapq.heappush(largest, item)
        elif item > largest[0]:
            heapq.heapreplace(largest, item)
    examples = [{
        "name": names[node],
        "absolute_total_degree_delta": delta,
        "gsim_in": gsim_in[node], "gsim_out": gsim_out[node],
        "grh_in": grh_in[node], "grh_out": grh_out[node],
    } for delta, node in sorted(largest, reverse=True)]
    return {
        "gsim_in": summarize_degrees(gsim_in),
        "gsim_out": summarize_degrees(gsim_out),
        "grh_in": summarize_degrees(grh_in),
        "grh_out": summarize_degrees(grh_out),
        "nodes_with_degree_difference": different_nodes,
        "largest_degree_differences": examples,
    }


def module_name(name: str) -> str:
    return name.rsplit("$", 1)[0] if "$" in name else "<top>"


def difference_details(gsim_only: set[int], grh_only: set[int], names: list[str]):
    modules: Counter[tuple[str, str]] = Counter()
    for label, edges in (("gsim_only", gsim_only), ("grh_only", grh_only)):
        for edge in edges:
            _source, target = unpack(edge)
            modules[(module_name(names[target]), label)] += 1
    module_names = {module for module, _label in modules}
    top_modules = sorted(module_names,
                         key=lambda module: modules[(module, "gsim_only")] + modules[(module, "grh_only")],
                         reverse=True)[:20]
    module_rows = [{
        "module": module,
        "gsim_only": modules[(module, "gsim_only")],
        "grh_only": modules[(module, "grh_only")],
    } for module in top_modules]
    examples = {}
    for label, edges in (("gsim_only", gsim_only), ("grh_only", grh_only)):
        rows = []
        for edge in sorted(edges)[:30]:
            source, target = unpack(edge)
            rows.append({"source": names[source], "target": names[target]})
        examples[label] = rows
    return {"top_modules_by_target": module_rows, "examples": examples}


def write_edges(path: Path, edges: set[int]) -> None:
    log(f"writing {len(edges)} edges to {path}")
    array("Q", sorted(edges)).tofile(path.open("wb"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gsim", type=Path, required=True)
    parser.add_argument("--grh", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--unmatched", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--index-cache", type=Path)
    parser.add_argument("--gsim-original-init", type=Path)
    parser.add_argument("--gsim-split-map", type=Path)
    parser.add_argument("--gsim-ambiguous", type=Path)
    parser.add_argument("--gsim-drop-self", action="store_true")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    names, name_to_id = load_nodes(args.candidates, args.unmatched)
    log(f"ordinary matched Nodes: {len(names)}")
    gsim_raw, gsim_edges, gsim_stats = collect_gsim(
        args.gsim, name_to_id, args.gsim_original_init, args.gsim_split_map,
        args.gsim_ambiguous, args.gsim_drop_self)
    if args.index_cache:
        def load_cached(filename):
            result = array("I")
            path = args.index_cache / filename
            with path.open("rb") as stream:
                result.fromfile(stream, path.stat().st_size // 4)
            return result
        sid_to_gid = load_cached("grh-sid-gids.u32")
        offsets = load_cached("grh-value-offsets.u32")
        sizes = load_cached("grh-value-sizes.u32")
        pool = load_cached("grh-value-group-pool.u32")
        guard_names = json.loads((args.index_cache / "guard-names.json").read_text())
        index_stats = json.loads((args.index_cache / "index-stats.json").read_text())
        tree_stats = index_stats["tree"]
        value_stats = index_stats["values"]
        log(f"loaded GRH projection index from {args.index_cache}")
    else:
        sid_to_gid, guard_names, tree_stats = parse_semantic_tree(args.grh, name_to_id)
        offsets, sizes, pool, value_stats = build_value_groups(
            args.grh, sid_to_gid, name_to_id, guard_names)
        for filename, values in (("grh-sid-gids.u32", sid_to_gid),
                                 ("grh-value-offsets.u32", offsets),
                                 ("grh-value-sizes.u32", sizes),
                                 ("grh-value-group-pool.u32", pool)):
            with (args.out_dir / filename).open("wb") as output:
                values.tofile(output)
        (args.out_dir / "guard-names.json").write_text(json.dumps(guard_names) + "\n")
        (args.out_dir / "index-stats.json").write_text(json.dumps({
            "tree": tree_stats, "values": value_stats}, indent=2, sort_keys=True) + "\n")
    grh_raw, grh_edges, grh_stats = project_grh_edges(
        args.grh, sid_to_gid, len(names), guard_names, offsets, sizes, pool)
    del sid_to_gid, offsets, sizes, pool
    raw_metrics, _unused, _unused2 = edge_metrics(gsim_raw, grh_raw, False)
    del gsim_raw, grh_raw
    metrics, gsim_only, grh_only = edge_metrics(gsim_edges, grh_edges, True)
    report = {
        "scope": "Matched ordinary Nodes only; prev/next edges, no dep edges; expression contents excluded.",
        "name_projection": {"ordinary_nodes": len(names), "guard_nodes": len(guard_names)},
        "gsim": gsim_stats,
        "grh_tree": tree_stats,
        "grh_values": value_stats,
        "grh_projection": grh_stats,
        "raw_without_generated_contraction": raw_metrics,
        "contracted": metrics,
        "degrees": degree_comparison(gsim_edges, grh_edges, names),
        "differences": difference_details(gsim_only, grh_only, names),
        "edge_file_format": f"native {sys.byteorder}-endian uint64; source << 32 | target; IDs follow sorted candidate names",
    }
    write_edges(args.out_dir / "gsim-contracted-edges.u64", gsim_edges)
    write_edges(args.out_dir / "grh-contracted-edges.u64", grh_edges)
    (args.out_dir / "dag-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    log(f"contracted metrics: {metrics}")


if __name__ == "__main__":
    main()
