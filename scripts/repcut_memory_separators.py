#!/usr/bin/env python3
"""Find structural memory separators in a freshly captured ASC graph."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import csv
import hashlib
import json
import itertools
from pathlib import Path
import resource
import sys
import time


sys.setrecursionlimit(200_000)


class DSU:
    def __init__(self, size: int):
        self.parent = list(range(size))
        self.rank = bytearray(size)

    def find(self, value: int) -> int:
        root = value
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[value] != value:
            parent = self.parent[value]
            self.parent[value] = root
            value = parent
        return root

    def union(self, left: int, right: int) -> None:
        left = self.find(left)
        right = self.find(right)
        if left == right:
            return
        if self.rank[left] < self.rank[right]:
            left, right = right, left
        self.parent[right] = left
        if self.rank[left] == self.rank[right]:
            self.rank[left] += 1


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def identity(path: Path) -> dict:
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    require(
        (before.st_ino, before.st_size, before.st_mtime_ns)
        == (after.st_ino, after.st_size, after.st_mtime_ns),
        f"file changed while hashing: {path}",
    )
    return {
        "path": str(path.resolve()),
        "size_bytes": after.st_size,
        "sha256": digest.hexdigest(),
    }


def read_tsv(path: Path):
    with path.open(newline="") as stream:
        yield from csv.DictReader(stream, delimiter="\t")


def connected_components(
    adjacency: dict[str, set[str]],
    removed_nodes: frozenset[str] = frozenset(),
    removed_edge: tuple[str, str] | None = None,
) -> list[set[str]]:
    unseen = set(adjacency) - set(removed_nodes)
    components = []
    while unseen:
        start = min(unseen)
        unseen.remove(start)
        component = {start}
        queue = [start]
        while queue:
            node = queue.pop()
            for neighbor in adjacency[node]:
                if neighbor in removed_nodes:
                    continue
                if removed_edge is not None and (
                    (node, neighbor) == removed_edge or (neighbor, node) == removed_edge
                ):
                    continue
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    component.add(neighbor)
                    queue.append(neighbor)
        components.append(component)
    return components


def tarjan(
    adjacency: dict[str, set[str]], removed: frozenset[str] = frozenset()
) -> tuple[set[str], set[tuple[str, str]], list[set[str]]]:
    """Return articulation vertices, bridges and vertex sets of edge blocks."""
    discovery: dict[str, int] = {}
    low: dict[str, int] = {}
    parent: dict[str, str] = {}
    edge_stack: list[tuple[str, str]] = []
    articulations: set[str] = set()
    bridges: set[tuple[str, str]] = set()
    blocks: list[set[str]] = []
    clock = 0

    def visit(node: str) -> None:
        nonlocal clock
        clock += 1
        discovery[node] = low[node] = clock
        children = 0
        for neighbor in sorted(adjacency[node]):
            if neighbor in removed:
                continue
            if neighbor not in discovery:
                parent[neighbor] = node
                children += 1
                edge_stack.append((node, neighbor))
                visit(neighbor)
                low[node] = min(low[node], low[neighbor])
                if low[neighbor] > discovery[node]:
                    bridges.add(tuple(sorted((node, neighbor))))
                if low[neighbor] >= discovery[node]:
                    if node in parent or children > 1:
                        articulations.add(node)
                    block: set[str] = set()
                    while edge_stack:
                        edge = edge_stack.pop()
                        block.update(edge)
                        if edge == (node, neighbor):
                            break
                    if block:
                        blocks.append(block)
            elif parent.get(node) != neighbor and discovery[neighbor] < discovery[node]:
                low[node] = min(low[node], discovery[neighbor])
                edge_stack.append((node, neighbor))

    for root in sorted(set(adjacency) - set(removed)):
        if root in discovery:
            continue
        visit(root)
        if edge_stack:
            block: set[str] = set()
            while edge_stack:
                block.update(edge_stack.pop())
            blocks.append(block)
    return articulations, bridges, blocks


def component_metric(component: set[str], anchor_sinks: dict[str, list[int]]) -> dict:
    memories = sorted(node[2:] for node in component if node.startswith("m:"))
    anchors = sorted(node for node in component if node.startswith("a:"))
    return {
        "memory_count": len(memories),
        "anchor_count": len(anchors),
        "sink_count": sum(len(anchor_sinks[node]) for node in anchors),
        "memory_examples": memories[:8],
    }


def cut_metric(
    adjacency: dict[str, set[str]],
    anchor_sinks: dict[str, list[int]],
    removed_nodes: frozenset[str] = frozenset(),
    removed_edge: tuple[str, str] | None = None,
) -> dict:
    components = [
        component_metric(component, anchor_sinks)
        for component in connected_components(adjacency, removed_nodes, removed_edge)
    ]
    components.sort(
        key=lambda item: (item["sink_count"], item["memory_count"], item["anchor_count"]),
        reverse=True,
    )
    memory_components = sum(item["memory_count"] > 0 for item in components)
    return {
        "component_count": len(components),
        "memory_bearing_component_count": memory_components,
        "max_sink_count": components[0]["sink_count"] if components else 0,
        "max_memory_count": max((item["memory_count"] for item in components), default=0),
        "second_sink_count": components[1]["sink_count"] if len(components) > 1 else 0,
        "components": components[:12],
    }


def node_weight(node: str, anchor_sinks: dict[str, list[int]]) -> tuple[int, int, int]:
    if node.startswith("m:"):
        return (1, 0, 0)
    return (0, 1, len(anchor_sinks[node]))


def add_weight(
    left: tuple[int, int, int], right: tuple[int, int, int]
) -> tuple[int, int, int]:
    return tuple(a + b for a, b in zip(left, right, strict=True))


def subtract_weight(
    left: tuple[int, int, int], right: tuple[int, int, int]
) -> tuple[int, int, int]:
    return tuple(a - b for a, b in zip(left, right, strict=True))


def metrics_from_weights(weights: list[tuple[int, int, int]]) -> dict:
    components = [
        {"memory_count": memory, "anchor_count": anchor, "sink_count": sink}
        for memory, anchor, sink in weights
    ]
    components.sort(
        key=lambda item: (item["sink_count"], item["memory_count"], item["anchor_count"]),
        reverse=True,
    )
    return {
        "component_count": len(components),
        "memory_bearing_component_count": sum(
            item["memory_count"] > 0 for item in components
        ),
        "max_sink_count": components[0]["sink_count"] if components else 0,
        "max_memory_count": max(
            (item["memory_count"] for item in components), default=0
        ),
        "second_sink_count": components[1]["sink_count"] if len(components) > 1 else 0,
        "components": components[:12],
    }


def articulation_metrics_from_blocks(
    adjacency: dict[str, set[str]],
    anchor_sinks: dict[str, list[int]],
    articulations: set[str],
    blocks: list[set[str]],
    removed: frozenset[str] = frozenset(),
) -> dict[str, dict]:
    """Compute every articulation split from the block-cut tree in linear time."""
    tree: dict[str, set[str]] = {}
    weights: dict[str, tuple[int, int, int]] = {}
    for articulation in articulations:
        key = f"x:{articulation}"
        tree[key] = set()
        weights[key] = node_weight(articulation, anchor_sinks)
    covered_non_articulations: set[str] = set()
    for index, block in enumerate(blocks):
        key = f"b:{index}"
        tree[key] = set()
        weight = (0, 0, 0)
        for node in block:
            if node in articulations:
                articulation_key = f"x:{node}"
                tree[key].add(articulation_key)
                tree[articulation_key].add(key)
            else:
                require(node not in covered_non_articulations, "non-articulation appears in multiple blocks")
                covered_non_articulations.add(node)
                weight = add_weight(weight, node_weight(node, anchor_sinks))
        weights[key] = weight
    active_vertices = set(adjacency) - set(removed)
    require(
        covered_non_articulations | articulations == active_vertices,
        "block-cut tree lost vertices",
    )

    roots = sorted(tree)
    parent: dict[str, str | None] = {}
    order: list[str] = []
    for root in roots:
        if root in parent:
            continue
        parent[root] = None
        stack = [root]
        while stack:
            node = stack.pop()
            order.append(node)
            for neighbor in sorted(tree[node], reverse=True):
                if neighbor == parent[node]:
                    continue
                require(neighbor not in parent, "block-cut graph contains a cycle")
                parent[neighbor] = node
                stack.append(neighbor)
    subtree = dict(weights)
    for node in reversed(order):
        if parent[node] is not None:
            subtree[parent[node]] = add_weight(subtree[parent[node]], subtree[node])
    total = (0, 0, 0)
    for node, node_parent in parent.items():
        if node_parent is None:
            total = add_weight(total, subtree[node])
    expected_total = (0, 0, 0)
    for node in active_vertices:
        expected_total = add_weight(expected_total, node_weight(node, anchor_sinks))
    require(total == expected_total, f"block-cut total mismatch: {total} != {expected_total}")

    result = {}
    for articulation in sorted(articulations):
        key = f"x:{articulation}"
        branches = []
        for neighbor in tree[key]:
            if parent[key] == neighbor:
                branches.append(subtract_weight(total, subtree[key]))
            else:
                require(parent[neighbor] == key, "invalid block-cut orientation")
                branches.append(subtree[neighbor])
        result[articulation] = metrics_from_weights(branches)
    return result


def bridge_metrics_from_tree(
    adjacency: dict[str, set[str]],
    anchor_sinks: dict[str, list[int]],
    bridges: set[tuple[str, str]],
) -> dict[tuple[str, str], dict]:
    """Compute all bridge split sizes from the bridge tree in linear time."""
    bridge_lookup = {tuple(sorted(edge)) for edge in bridges}
    component_by_node: dict[str, int] = {}
    component_weights: list[tuple[int, int, int]] = []
    for start in sorted(adjacency):
        if start in component_by_node:
            continue
        component = len(component_weights)
        weight = (0, 0, 0)
        stack = [start]
        component_by_node[start] = component
        while stack:
            node = stack.pop()
            weight = add_weight(weight, node_weight(node, anchor_sinks))
            for neighbor in adjacency[node]:
                if tuple(sorted((node, neighbor))) in bridge_lookup:
                    continue
                if neighbor not in component_by_node:
                    component_by_node[neighbor] = component
                    stack.append(neighbor)
        component_weights.append(weight)

    tree: dict[int, list[tuple[int, tuple[str, str]]]] = defaultdict(list)
    for edge in sorted(bridge_lookup):
        left = component_by_node[edge[0]]
        right = component_by_node[edge[1]]
        require(left != right, "bridge endpoints remained in one component")
        tree[left].append((right, edge))
        tree[right].append((left, edge))
    parent: dict[int, int | None] = {0: None}
    parent_edge: dict[int, tuple[str, str]] = {}
    order = []
    stack = [0]
    while stack:
        component = stack.pop()
        order.append(component)
        for neighbor, edge in tree.get(component, []):
            if neighbor == parent[component]:
                continue
            require(neighbor not in parent, "bridge component graph contains a cycle")
            parent[neighbor] = component
            parent_edge[neighbor] = edge
            stack.append(neighbor)
    require(len(parent) == len(component_weights), "bridge tree is disconnected")
    subtree = list(component_weights)
    for component in reversed(order):
        if parent[component] is not None:
            subtree[parent[component]] = add_weight(
                subtree[parent[component]], subtree[component]
            )
    total = subtree[0]
    expected_total = (
        sum(node.startswith("m:") for node in adjacency),
        len(anchor_sinks),
        sum(map(len, anchor_sinks.values())),
    )
    require(total == expected_total, f"bridge-tree total mismatch: {total} != {expected_total}")
    result = {}
    for child, edge in parent_edge.items():
        result[edge] = metrics_from_weights(
            [subtree[child], subtract_weight(total, subtree[child])]
        )
    require(set(result) == bridge_lookup, "bridge-tree result coverage mismatch")
    return result


def self_test() -> None:
    chain = {
        "m:A": {"a:0"},
        "a:0": {"m:A", "m:B"},
        "m:B": {"a:0", "a:1"},
        "a:1": {"m:B", "m:C"},
        "m:C": {"a:1"},
    }
    arts, bridges, blocks = tarjan(chain)
    require(arts == {"a:0", "m:B", "a:1"}, f"chain articulation mismatch: {arts}")
    require(len(bridges) == 4 and len(blocks) == 4, "chain bridge/block mismatch")
    cycle = {
        "m:A": {"a:0", "a:1"},
        "m:B": {"a:0", "a:1"},
        "a:0": {"m:A", "m:B"},
        "a:1": {"m:A", "m:B"},
    }
    arts, bridges, blocks = tarjan(cycle)
    require(not arts and not bridges and len(blocks) == 1, "cycle should be biconnected")
    hyperedge = {
        "m:A": {"a:0"},
        "m:B": {"a:0"},
        "m:C": {"a:0"},
        "a:0": {"m:A", "m:B", "m:C"},
    }
    arts, _, _ = tarjan(hyperedge)
    require(arts == {"a:0"}, "hyperedge anchor should be the only articulation")
    anchor_sinks = {"a:0": [0], "a:1": [1]}
    metric = cut_metric(chain, anchor_sinks, frozenset({"m:B"}))
    require(metric["memory_bearing_component_count"] == 2, "memory cut did not split chain")
    fast_articulations = articulation_metrics_from_blocks(
        chain, anchor_sinks, {"a:0", "m:B", "a:1"}, tarjan(chain)[2]
    )
    def without_examples(metric):
        return {
            **metric,
            "components": [
                {key: value for key, value in component.items() if key != "memory_examples"}
                for component in metric["components"]
            ],
        }
    for node in fast_articulations:
        brute = cut_metric(chain, anchor_sinks, frozenset({node}))
        require(
            fast_articulations[node] == without_examples(brute),
            f"fast articulation metric mismatch for {node}",
        )
    fast_bridges = bridge_metrics_from_tree(chain, anchor_sinks, tarjan(chain)[1])
    for edge in fast_bridges:
        brute = cut_metric(chain, anchor_sinks, removed_edge=edge)
        require(
            fast_bridges[edge] == without_examples(brute),
            f"fast bridge metric mismatch for {edge}",
        )
    first_removed, _, first_removed_blocks = tarjan(cycle, frozenset({"m:A"}))
    require("m:B" in first_removed, "cycle pair separator not exposed")
    first_removed_metrics = articulation_metrics_from_blocks(
        cycle,
        anchor_sinks,
        first_removed,
        first_removed_blocks,
        frozenset({"m:A"}),
    )
    require(
        first_removed_metrics["m:B"]
        == without_examples(cut_metric(cycle, anchor_sinks, frozenset({"m:A", "m:B"}))),
        "pair cut metric mismatch",
    )
    print("separator analyzer self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-run", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--refinement-output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--row-limit", type=int, default=32)
    parser.add_argument("--top-cuts", type=int, default=10)
    parser.add_argument("--combine-two", action="store_true",
                        help="also evaluate unions of two independently proposed cuts")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.capture_run is None or args.output is None:
        parser.error("--capture-run and --output are required unless --self-test is used")
    require(not args.output.exists(), "refusing to overwrite output")

    started = time.monotonic()
    run_dir = args.capture_run.resolve()
    run = json.loads((run_dir / "run.json").read_text())
    require(run["status"] == "pass", "capture run did not pass")
    require(run["baseline_gate"]["passed"], "capture baseline gate did not pass")
    analysis_dir = run_dir / "analysis"
    capture_dir = run_dir / "capture"
    summary = json.loads((analysis_dir / "summary.json").read_text())
    target_asc = int(summary["max_full_closure_asc_id"])
    shapes = json.loads((analysis_dir / "memory_shapes.json").read_text())
    eligible = {name for name, row in shapes.items() if row["eligible"] and 0 < row["rows"] <= args.row_limit}
    if args.row_limit < 1 or args.top_cuts < 1:
        raise ValueError("memory limits must be positive")

    sink_rows: dict[int, dict] = {}
    asc_sinks: dict[int, list[int]] = defaultdict(list)
    state_groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for row in read_tsv(analysis_dir / "state_sink_to_asc.tsv"):
        sink = int(row["sink_index"])
        asc = int(row["asc_id"])
        require(sink not in sink_rows, f"duplicate sink index {sink}")
        sink_rows[sink] = row
        asc_sinks[asc].append(sink)
        if row["kind"] in (
            "kRegisterWritePort",
            "kLatchWritePort",
            "kMemoryWritePort",
        ):
            require(row["state_symbol"], f"state sink {sink} has no symbol")
            state_groups[(row["kind"], row["state_symbol"])].append(sink)
    require(len(sink_rows) == summary["sink_count"], "sink table count mismatch")
    require(set(sink_rows) == set(range(summary["sink_count"])), "sink indices are not contiguous")

    memory_to_asc = {
        row["memory_symbol"]: int(row["asc_id"])
        for row in read_tsv(analysis_dir / "memory_symbol_to_asc.tsv")
    }
    target_memories = {
        symbol for symbol, asc in memory_to_asc.items() if asc == target_asc
    }
    require(bool(target_memories), "largest ASC has no memory writers")

    memory_readers: dict[str, list[int]] = defaultdict(list)
    memory_incidence_rows = 0
    for row in read_tsv(capture_dir / "sink_memory_cone.tsv"):
        sink = int(row["sink_index"])
        require(sink in sink_rows, f"unknown memory-incidence sink {sink}")
        memory_readers[row["memory_symbol"]].append(sink)
        memory_incidence_rows += 1
    for readers in memory_readers.values():
        require(len(readers) == len(set(readers)), "duplicate sink-memory incidence")

    effect_consumers: dict[str, list[int]] = defaultdict(list)
    effect_metadata: dict[str, dict] = {}
    effect_incidence_rows = 0
    for row in read_tsv(capture_dir / "sink_effect_result.tsv"):
        sink = int(row["sink_index"])
        require(sink in sink_rows, f"unknown effect-incidence sink {sink}")
        key = row["effect_op_index"]
        metadata = {
            "op_symbol": row["effect_op_symbol"],
            "src_file": row["src_file"],
            "src_line": int(row["src_line"]),
        }
        if key in effect_metadata:
            require(effect_metadata[key] == metadata, "effect metadata mismatch")
        effect_metadata[key] = metadata
        effect_consumers[key].append(sink)
        effect_incidence_rows += 1
    for consumers in effect_consumers.values():
        require(len(consumers) == len(set(consumers)), "duplicate sink-effect incidence")

    # Recreate every DSU rule and require exact agreement for all ASCs.
    dsu = DSU(summary["sink_count"])
    for sinks in state_groups.values():
        for sink in sinks[1:]:
            dsu.union(sinks[0], sink)
    memory_writers = {
        symbol: sinks
        for (kind, symbol), sinks in state_groups.items()
        if kind == "kMemoryWritePort"
    }
    for symbol, readers in memory_readers.items():
        writers = memory_writers.get(symbol)
        if writers:
            for sink in readers:
                dsu.union(sink, writers[0])
    for sinks in effect_consumers.values():
        for sink in sinks[1:]:
            dsu.union(sinks[0], sink)

    root_to_asc: dict[int, int] = {}
    asc_to_root: dict[int, int] = {}
    for sink, row in sink_rows.items():
        root = dsu.find(sink)
        asc = int(row["asc_id"])
        previous_asc = root_to_asc.setdefault(root, asc)
        require(previous_asc == asc, f"reconstructed component crosses ASC {previous_asc}/{asc}")
        previous_root = asc_to_root.setdefault(asc, root)
        require(previous_root == root, f"ASC {asc} splits across reconstructed components")
    require(len(root_to_asc) == summary["asc_count"], "reconstructed ASC count mismatch")

    target_sinks = set(asc_sinks[target_asc])
    require(len(target_sinks) == summary["max_sinks"], "target sink count mismatch")

    # Contract register/latch/effect constraints into anchors. Memory constraints remain cuttable.
    local_index = {sink: index for index, sink in enumerate(sorted(target_sinks))}
    local_dsu = DSU(len(local_index))
    for (kind, _symbol), sinks in state_groups.items():
        if kind not in ("kRegisterWritePort", "kLatchWritePort"):
            continue
        selected = [local_index[sink] for sink in sinks if sink in target_sinks]
        for sink in selected[1:]:
            local_dsu.union(selected[0], sink)
    for sinks in effect_consumers.values():
        selected = [local_index[sink] for sink in sinks if sink in target_sinks]
        for sink in selected[1:]:
            local_dsu.union(selected[0], sink)

    anchor_members: dict[int, list[int]] = defaultdict(list)
    for sink, index in local_index.items():
        anchor_members[local_dsu.find(index)].append(sink)
    anchor_sinks: dict[str, list[int]] = {}
    sink_anchor: dict[int, str] = {}
    for members in anchor_members.values():
        members.sort()
        anchor = f"a:{members[0]}"
        anchor_sinks[anchor] = members
        for sink in members:
            sink_anchor[sink] = anchor

    adjacency: dict[str, set[str]] = {anchor: set() for anchor in anchor_sinks}
    edge_roles: dict[tuple[str, str], set[str]] = defaultdict(set)
    memory_endpoint_counts = {}
    for symbol in sorted(target_memories):
        memory_node = f"m:{symbol}"
        adjacency[memory_node] = set()
        readers = [sink for sink in memory_readers.get(symbol, []) if sink in target_sinks]
        writers = [sink for sink in memory_writers.get(symbol, []) if sink in target_sinks]
        require(writers, f"target memory has no writer: {symbol}")
        for role, sinks in (("cone_read", readers), ("write_owner", writers)):
            for sink in sinks:
                anchor = sink_anchor[sink]
                adjacency[memory_node].add(anchor)
                adjacency[anchor].add(memory_node)
                edge_roles[(memory_node, anchor)].add(role)
        memory_endpoint_counts[symbol] = {
            "reader_sinks": len(readers),
            "writer_sinks": len(writers),
            "anchors": len(adjacency[memory_node]),
        }

    quotient_components = connected_components(adjacency)
    require(len(quotient_components) == 1, "memory quotient does not reproduce one target component")
    only_component = quotient_components[0]
    require(
        sum(node.startswith("m:") for node in only_component) == len(target_memories),
        "memory quotient lost target memories",
    )
    require(
        sum(len(anchor_sinks[node]) for node in only_component if node.startswith("a:"))
        == len(target_sinks),
        "memory quotient lost target sinks",
    )

    articulations, bridges, blocks = tarjan(adjacency)
    articulation_metrics = articulation_metrics_from_blocks(
        adjacency, anchor_sinks, articulations, blocks
    )
    bridge_metrics = bridge_metrics_from_tree(adjacency, anchor_sinks, bridges)
    all_memory_articulations = {
        node for node in articulations if node.startswith("m:")
    }
    baseline_memory_articulations = {
        node
        for node in all_memory_articulations
        if articulation_metrics[node]["memory_bearing_component_count"] > 1
    }

    articulation_candidates = []
    for node in sorted(articulations):
        metric = articulation_metrics[node]
        if metric["component_count"] <= 1:
            continue
        candidate = {
            "node_type": "memory" if node.startswith("m:") else "anchor",
            "node": node[2:],
            **metric,
        }
        if node.startswith("m:"):
            candidate["memory"] = memory_endpoint_counts[node[2:]]
        else:
            members = anchor_sinks[node]
            candidate["anchor_sink_count"] = len(members)
            candidate["anchor_sink_examples"] = [
                {
                    "sink_index": sink,
                    "kind": sink_rows[sink]["kind"],
                    "op_symbol": sink_rows[sink]["op_symbol"],
                    "state_symbol": sink_rows[sink]["state_symbol"],
                }
                for sink in members[:12]
            ]
        articulation_candidates.append(candidate)
    articulation_candidates.sort(
        key=lambda item: (
            item["max_sink_count"],
            item["max_memory_count"],
            item["node_type"],
            item["node"],
        )
    )

    bridge_candidates = []
    for edge in sorted(bridges):
        metric = bridge_metrics[edge]
        memory_node = edge[0] if edge[0].startswith("m:") else edge[1]
        anchor_node = edge[1] if edge[0].startswith("m:") else edge[0]
        bridge_candidates.append(
            {
                "memory": memory_node[2:],
                "anchor": anchor_node[2:],
                "roles": sorted(edge_roles[(memory_node, anchor_node)]),
                "anchor_sink_count": len(anchor_sinks[anchor_node]),
                **metric,
            }
        )
    bridge_candidates.sort(
        key=lambda item: (
            item["max_sink_count"],
            item["max_memory_count"],
            item["memory"],
            item["anchor"],
        )
    )

    memory_nodes = sorted(node for node in adjacency if node.startswith("m:"))
    pair_candidates: dict[tuple[str, str], dict] = {}
    pair_tarjan_runs = 0
    for first in memory_nodes:
        if first in all_memory_articulations:
            continue
        removed_first = frozenset({first})
        after_first_articulations, _, after_first_blocks = tarjan(adjacency, removed_first)
        after_first_metrics = articulation_metrics_from_blocks(
            adjacency,
            anchor_sinks,
            after_first_articulations,
            after_first_blocks,
            removed_first,
        )
        pair_tarjan_runs += 1
        for second in sorted(after_first_articulations):
            if not second.startswith("m:") or second in all_memory_articulations:
                continue
            pair = tuple(sorted((first, second)))
            if pair in pair_candidates:
                continue
            metric = after_first_metrics[second]
            if metric["memory_bearing_component_count"] <= 1:
                continue
            pair_candidates[pair] = {
                "memories": [node[2:] for node in pair],
                "memory_metadata": [memory_endpoint_counts[node[2:]] for node in pair],
                **metric,
            }
    ordered_pairs = sorted(
        pair_candidates.values(),
        key=lambda item: (
            item["max_sink_count"],
            item["max_memory_count"],
            item["memories"],
        ),
    )

    block_metrics = []
    for block in blocks:
        metric = component_metric(block, anchor_sinks)
        metric["vertex_count"] = len(block)
        block_metrics.append(metric)
    block_metrics.sort(
        key=lambda item: (item["memory_count"], item["sink_count"], item["anchor_count"]),
        reverse=True,
    )

    anchor_size_histogram = Counter(len(members) for members in anchor_sinks.values())

    meaningful_single_memories = [
        candidate
        for candidate in articulation_candidates
        if candidate["node_type"] == "memory"
        and candidate["memory_bearing_component_count"] > 1
        and candidate["node"] in eligible
    ]
    refinement_specs = []
    for index, candidate in enumerate(meaningful_single_memories[:args.top_cuts]):
        refinement_specs.append(
            {
                "candidate_id": f"single_{index:02d}",
                "cut_kind": "single_memory",
                "cut_memories": [candidate["node"]],
            }
        )
    eligible_pairs = [c for c in ordered_pairs if all(m in eligible for m in c["memories"])]
    for index, candidate in enumerate(eligible_pairs[:args.top_cuts]):
        refinement_specs.append(
            {
                "candidate_id": f"pair_{index:02d}",
                "cut_kind": "memory_pair",
                "cut_memories": candidate["memories"],
            }
        )

    if args.combine_two:
        combined = []
        seen = {tuple(sorted(spec["cut_memories"])) for spec in refinement_specs}
        for left, right in itertools.combinations(refinement_specs, 2):
            memories = tuple(sorted(set(left["cut_memories"]) | set(right["cut_memories"])))
            if memories in seen:
                continue
            seen.add(memories)
            combined.append({"candidate_id": f"combined_{len(combined):03d}",
                             "cut_kind": "union_of_two_structural_cuts",
                             "cut_memories": list(memories)})
        refinement_specs.extend(combined)

    refinement_artifact = None
    if args.refinement_output is not None:
        require(not args.refinement_output.exists(), "refusing to overwrite refinement output")
        with args.refinement_output.open("x", newline="") as stream:
            writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
            writer.writerow(("candidate_id", "component_rank", "sink_index"))
            for spec in refinement_specs:
                removed = frozenset(f"m:{symbol}" for symbol in spec["cut_memories"])
                components = connected_components(adjacency, removed)
                components.sort(
                    key=lambda component: (
                        sum(len(anchor_sinks[node]) for node in component if node.startswith("a:")),
                        sum(node.startswith("m:") for node in component),
                    ),
                    reverse=True,
                )
                summaries = []
                for rank, component in enumerate(components):
                    sinks = sorted(
                        sink
                        for node in component
                        if node.startswith("a:")
                        for sink in anchor_sinks[node]
                    )
                    summaries.append(
                        {
                            "rank": rank,
                            "sink_count": len(sinks),
                            "memory_count": sum(node.startswith("m:") for node in component),
                        }
                    )
                    for sink in sinks:
                        writer.writerow((spec["candidate_id"], rank, sink))
                spec["components"] = summaries
        refinement_artifact = identity(args.refinement_output)

    result = {
        "schema_version": 1,
        "status": "pass",
        "scope": "read-only structural separator audit; sink/memory counts and static connectivity are not runtime",
        "input": run["input"],
        "capture_run": identity(run_dir / "run.json"),
        "validation": {
            "full_reconstructed_asc_count": len(root_to_asc),
            "expected_asc_count": summary["asc_count"],
            "all_asc_memberships_exact": True,
            "target_asc_id": target_asc,
            "target_sink_count": len(target_sinks),
            "target_memory_count": len(target_memories),
            "target_quotient_connected": True,
        },
        "incidence": {
            "memory_cone_rows": memory_incidence_rows,
            "effect_result_rows": effect_incidence_rows,
            "memory_symbols_with_readers": len(memory_readers),
            "effect_result_constraints": len(effect_consumers),
        },
        "quotient": {
            "anchor_count": len(anchor_sinks),
            "memory_count": len(memory_nodes),
            "edge_count": sum(map(len, adjacency.values())) // 2,
            "anchor_size_histogram": {
                str(key): value for key, value in sorted(anchor_size_histogram.items())
            },
        },
        "connectivity": {
            "articulation_count": len(articulations),
            "memory_articulation_count": sum(node.startswith("m:") for node in articulations),
            "memory_articulation_splitting_memories": len(baseline_memory_articulations),
            "anchor_articulation_count": sum(node.startswith("a:") for node in articulations),
            "bridge_count": len(bridges),
            "biconnected_block_count": len(blocks),
            "largest_biconnected_blocks": block_metrics[:20],
            "exhaustive_pair_memory_tarjan_runs": pair_tarjan_runs,
            "proper_pair_memory_separator_count": len(ordered_pairs),
        },
        "memory_endpoints": dict(sorted(memory_endpoint_counts.items())),
        "articulation_candidates": articulation_candidates[:100],
        "bridge_candidates": bridge_candidates[:100],
        "pair_memory_candidates": ordered_pairs[:100],
        "refinement_candidates": refinement_specs,
        "coverage_notes": {
            "single_vertex": "exhaustive over the validated memory/anchor quotient",
            "single_edge": "exhaustive over the validated memory/anchor quotient",
            "memory_pairs": "exhaustive for proper two-memory separators; pairs containing an already effective single-memory cut are omitted",
            "three_or_more": ("unions of two shortlisted single/pair cuts; not exhaustive"
                              if args.combine_two else "not searched in this pass"),
            "candidate_metric": "component sink/memory counts only; exact closure weight, copy bits, and semantic risk require top-candidate refinement",
        },
        "artifacts": {
            "sink_table": identity(analysis_dir / "state_sink_to_asc.tsv"),
            "memory_table": identity(analysis_dir / "memory_symbol_to_asc.tsv"),
            "memory_incidence": identity(capture_dir / "sink_memory_cone.tsv"),
            "effect_incidence": identity(capture_dir / "sink_effect_result.tsv"),
            "refinement_requests": refinement_artifact,
        },
        "wall_seconds": time.monotonic() - started,
        "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {
                "status": result["status"],
                "validation": result["validation"],
                "incidence": result["incidence"],
                "quotient": result["quotient"],
                "connectivity": result["connectivity"],
                "top_articulation_candidates": result["articulation_candidates"][:5],
                "top_pair_memory_candidates": result["pair_memory_candidates"][:5],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
