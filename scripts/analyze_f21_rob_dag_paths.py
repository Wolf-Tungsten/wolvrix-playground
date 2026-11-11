"""Classify GrhSIM-only ROB edges by their corresponding GSIM DAG paths."""
from __future__ import annotations

import argparse
import json
import sys
import time
from array import array
from collections import Counter, defaultdict, deque
from pathlib import Path

from grhsim_f21_dce_compare import collect_gsim, module_name, pack, unpack


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


def read_edges(path: Path) -> array:
    edges = array("Q")
    with path.open("rb") as stream:
        edges.fromfile(stream, path.stat().st_size // 8)
    if sys.byteorder != "little":
        edges.byteswap()
    return edges


def two_hop_paths(edges: array, pairs: set[tuple[int, int]]) -> dict[tuple[int, int], list[int]]:
    sources = {source for source, _target in pairs}
    target_sources = defaultdict(list)
    for source, target in pairs:
        target_sources[target].append(source)
    first_hops = defaultdict(set)
    for edge in edges:
        source, middle = unpack(edge)
        if source in sources:
            first_hops[middle].add(source)
    paths = {}
    for edge in edges:
        middle, target = unpack(edge)
        origins = first_hops.get(middle)
        candidates = target_sources.get(target)
        if origins is None or candidates is None:
            continue
        for source in candidates:
            pair = (source, target)
            if source in origins and pair in pairs:
                paths.setdefault(pair, []).append(middle)
    return paths


def bypassed_source_paths(candidate_edges: array, reference_edges: array,
                          pairs: set[tuple[int, int]]) -> dict[tuple[int, int], list[int]]:
    targets = {target for _source, target in pairs}
    candidate_incoming = defaultdict(set)
    for edge in candidate_edges:
        source, target = unpack(edge)
        if target in targets:
            candidate_incoming[target].add(source)
    sources = {source for source, _target in pairs}
    reference_predecessors = defaultdict(set)
    for edge in reference_edges:
        predecessor, source = unpack(edge)
        if source in sources:
            reference_predecessors[source].add(predecessor)
    paths = {}
    for source, target in pairs:
        for predecessor in reference_predecessors.get(source, ()):
            if predecessor != source and predecessor in candidate_incoming.get(target, ()):
                paths.setdefault((source, target), []).append(predecessor)
    return paths


def build_adjacency(edges: array) -> dict[int, list[int]]:
    outgoing = defaultdict(list)
    for edge in edges:
        source, target = unpack(edge)
        outgoing[source].append(target)
    return outgoing


def longer_paths(outgoing: dict[int, list[int]], pairs: set[tuple[int, int]],
                 max_depth: int, visit_budget: int):
    by_source = defaultdict(set)
    for source, target in pairs:
        by_source[source].add(target)
    paths = {}
    statuses = {}
    truncated_sources = []
    visited_counts = {}
    for index, (source, targets) in enumerate(sorted(by_source.items()), start=1):
        remaining = set(targets)
        parents = {source: -1}
        depths = {source: 0}
        pending = deque([source])
        truncated = False
        while pending and remaining and not truncated:
            node = pending.popleft()
            depth = depths[node]
            if max_depth and depth >= max_depth:
                continue
            for target in outgoing.get(node, ()):
                if target in parents:
                    continue
                parents[target] = node
                depths[target] = depth + 1
                if target in remaining:
                    remaining.remove(target)
                pending.append(target)
            if visit_budget and len(parents) > visit_budget:
                truncated = True
        if truncated:
            truncated_sources.append(source)
        visited_counts[source] = len(parents)
        for target in targets - remaining:
            path = []
            node = target
            while node != source:
                parent = parents[node]
                if parent != source:
                    path.append(parent)
                node = parent
            path.reverse()
            paths[(source, target)] = path
        for target in remaining:
            status = "truncated" if truncated else ("no_path_within_depth" if max_depth else "no_path")
            statuses[(source, target)] = status
        if index % 100 == 0 or index == len(by_source):
            log(f"longer-path sources: {index}/{len(by_source)}; resolved={len(paths)}; "
                f"truncated={len(truncated_sources)}")
    return paths, statuses, truncated_sources, visited_counts


def named_path(names: list[str], source: int, target: int, middle: list[int]) -> list[str]:
    return [names[source], *(names[node] for node in middle), names[target]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--names", required=True, type=Path)
    parser.add_argument("--grh-edges", required=True, type=Path)
    parser.add_argument("--gsim-edges", required=True, type=Path)
    parser.add_argument("--target-module", default="")
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--max-depth", type=int, default=2)
    parser.add_argument("--visit-budget", type=int, default=200000)
    parser.add_argument("--gsim-json", type=Path)
    parser.add_argument("--gsim-original-init", type=Path)
    parser.add_argument("--gsim-split-map", type=Path)
    parser.add_argument("--reference-survivors", type=Path)
    parser.add_argument("--candidate-pre-edges", type=Path)
    args = parser.parse_args()
    if args.max_depth < 0 or args.visit_budget < 0:
        raise ValueError("depth and visit budget must be non-negative")
    if args.gsim_json and (args.gsim_original_init is None or args.gsim_split_map is None):
        raise ValueError("raw GSIM analysis requires original Init and split map")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    names = args.names.read_text(encoding="utf-8").splitlines()
    gsim_stats = None
    if args.gsim_json:
        name_to_id = {name: index for index, name in enumerate(names)}
        _raw, gsim_edges, gsim_stats = collect_gsim(
            args.gsim_json, name_to_id, args.gsim_original_init, args.gsim_split_map,
            include_unmatched=True)
        del _raw
        expanded_names = [None] * len(name_to_id)
        for name, index in name_to_id.items():
            expanded_names[index] = name
        names = expanded_names
    else:
        gsim_edges = read_edges(args.gsim_edges)
    grh_edges = read_edges(args.grh_edges)
    log(f"loaded {len(grh_edges)} GRH and {len(gsim_edges)} GSIM edges")
    reference_survivors = None
    if args.reference_survivors:
        reference_survivors = set(args.reference_survivors.read_text(encoding="utf-8").splitlines())
    pre_existing = set(read_edges(args.candidate_pre_edges)) if args.candidate_pre_edges else None
    gsim_edge_set = set(gsim_edges)
    pairs = set()
    for edge in grh_edges:
        if edge in gsim_edge_set:
            continue
        source, target = unpack(edge)
        if not args.target_module or module_name(names[target]) == args.target_module:
            pairs.add((source, target))
    del gsim_edge_set
    if not pairs:
        raise ValueError("no candidate-only edges in the requested scope")
    log(f"selected {len(pairs)} candidate-only edges targeting {args.target_module or '<all>'}")

    statuses = {}
    search_pairs = set()
    for source, target in pairs:
        if reference_survivors is not None:
            source_alive = names[source] in reference_survivors
            target_alive = names[target] in reference_survivors
            if not source_alive or not target_alive:
                status = ("both_absent" if not source_alive and not target_alive else
                          "source_absent" if not source_alive else "target_absent")
                statuses[(source, target)] = status
                continue
        search_pairs.add((source, target))
    two_hop = two_hop_paths(gsim_edges, search_pairs)
    unresolved = search_pairs - two_hop.keys()
    bypass = bypassed_source_paths(grh_edges, gsim_edges, unresolved)
    unresolved -= bypass.keys()
    log(f"two-hop paths: {len(two_hop)}; bypassed sources: {len(bypass)}; "
        f"remaining={len(unresolved)}; absent-endpoint edges={len(statuses)}")
    all_paths = dict(two_hop)
    statuses.update({pair: "two_hop" for pair in two_hop})
    statuses.update({pair: "bypassed_source" for pair in bypass})
    longer = {}
    truncated_sources = []
    visited_counts = {}
    if unresolved and args.max_depth != 2:
        outgoing = build_adjacency(gsim_edges)
        longer, longer_statuses, truncated_sources, visited_counts = longer_paths(
            outgoing, unresolved, args.max_depth, args.visit_budget)
        all_paths.update(longer)
        statuses.update(longer_statuses)
        for pair in longer:
            statuses[pair] = "longer_path"
    else:
        for pair in unresolved:
            statuses[pair] = "not_checked_beyond_two_hop"
    del grh_edges, gsim_edges

    chosen = {}
    for pair, middle in all_paths.items():
        chosen[pair] = ([min(two_hop[pair], key=lambda node: names[node])]
                        if pair in two_hop else middle)
    intermediate_counts = Counter()
    for pair, middle in chosen.items():
        if middle:
            intermediate_counts[middle[0]] += 1
    bypass_choices = {pair: min(alternatives, key=lambda node: names[node])
                      for pair, alternatives in bypass.items()}
    bypassed_counts = Counter(source for source, _target in bypass)
    rows = []
    pre_existing_counts = Counter()
    for source, target in sorted(pairs, key=lambda pair: (names[pair[0]], names[pair[1]])):
        pair = (source, target)
        middle = chosen.get(pair, [])
        pre_status = ("not_checked" if pre_existing is None else
                      "present_pre_split" if pack(source, target) in pre_existing else "absent_pre_split")
        pre_existing_counts[(statuses[pair], pre_status)] += 1
        bypass_source = names[bypass_choices[pair]] if pair in bypass_choices else ""
        rows.append((statuses[pair], names[source], names[target],
                     ",".join(names[node] for node in middle), bypass_source, pre_status))
    with (args.out_dir / "edge-paths.tsv").open("w", encoding="utf-8") as stream:
        stream.write("classification\tsource\ttarget\tintermediates\tbypass_source\tpre_split\n")
        for row in rows:
            stream.write("\t".join(row) + "\n")

    examples = defaultdict(list)
    for pair in sorted(pairs, key=lambda item: (names[item[0]], names[item[1]])):
        status = statuses[pair]
        if len(examples[status]) >= 30:
            continue
        source, target = pair
        path = ([names[bypass_choices[pair]], names[source], names[target]]
                if pair in bypass_choices else named_path(names, source, target, chosen.get(pair, [])))
        examples[status].append({
            "classification": status,
            "path": path,
        })
    counts = Counter(statuses.values())
    report = {
        "scope": {
            "target_module": args.target_module or "<all>",
            "candidate_only_edges": len(pairs),
            "grh_only_edges": len(pairs),
            "max_depth": args.max_depth,
            "visit_budget_per_source": args.visit_budget,
            "gsim_input": "all_valid_nodes" if args.gsim_json else "matched_nodes_only",
            "reference_survivors": str(args.reference_survivors) if args.reference_survivors else None,
            "candidate_pre_edges": str(args.candidate_pre_edges) if args.candidate_pre_edges else None,
            "note": "A reference-side path proves a corresponding projected dependency, not expression-level semantic equivalence.",
        },
        "gsim": gsim_stats,
        "counts": dict(sorted(counts.items())),
        "pre_existing_counts": {f"{status}|{pre_status}": count
                                for (status, pre_status), count in sorted(pre_existing_counts.items())},
        "two_hop_alternative_middle_counts": {
            "one": sum(1 for pair in two_hop if len(two_hop[pair]) == 1),
            "multiple": sum(1 for pair in two_hop if len(two_hop[pair]) > 1),
        },
        "bypass_alternative_predecessor_counts": {
            "one": sum(1 for pair in bypass if len(bypass[pair]) == 1),
            "multiple": sum(1 for pair in bypass if len(bypass[pair]) > 1),
        },
        "top_first_intermediates": [
            {"name": names[node], "edges": count}
            for node, count in intermediate_counts.most_common(50)
        ],
        "top_bypassed_sources": [
            {"name": names[node], "edges": count}
            for node, count in bypassed_counts.most_common(50)
        ],
        "truncated_sources": [names[node] for node in truncated_sources],
        "largest_source_visits": [
            {"name": names[node], "visited": count}
            for node, count in sorted(visited_counts.items(), key=lambda item: item[1], reverse=True)[:30]
        ],
        "examples": dict(sorted(examples.items())),
    }
    (args.out_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                                             encoding="utf-8")
    log(f"wrote {len(rows)} classified edges to {args.out_dir}; counts={dict(counts)}")


if __name__ == "__main__":
    main()
