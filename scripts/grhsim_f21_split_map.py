"""Map GSIM split-array member nodes back to their original aggregate keys."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

WHEN_COND = re.compile(r'(?:^|\$)WHEN_COND_\d+$')


def normalize(name: str) -> str:
    return name.replace("$$", "__DOT__")


def member_names(name: str, dimensions: list[int]):
    if not dimensions or any(dimension < 0 for dimension in dimensions):
        return
    indices = [0] * len(dimensions)
    while True:
        yield name + "_" + "_".join(str(index) for index in indices)
        for position in range(len(dimensions) - 1, -1, -1):
            indices[position] += 1
            if indices[position] < dimensions[position]:
                break
            indices[position] = 0
        else:
            return


def node_records(stream):
    for line in stream:
        if line.strip() == '"edges": [':
            break
        if line.lstrip().startswith('{"id":'):
            yield json.loads(line.strip().rstrip(","))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--init", type=Path, required=True)
    parser.add_argument("--topo", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--unmatched", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with args.unmatched.open() as stream:
        unmatched = {line.rstrip("\n") for line in stream}
    with args.candidates.open() as stream:
        candidates = {line.rstrip("\n") for line in stream} - unmatched
    original_ids = {}
    mapping = {}
    ambiguous = set()
    collisions = []
    array_nodes = 0
    zero_extent_arrays = 0
    with args.init.open() as stream:
        for record in node_records(stream):
            original_ids[record["id"]] = normalize(record["name"])
            dimensions = record["dimension"]
            if not dimensions:
                continue
            array_nodes += 1
            if 0 in dimensions:
                zero_extent_arrays += 1
                continue
            base = normalize(record["name"])
            for member in member_names(record["name"], dimensions):
                if member in mapping and mapping[member] != base:
                    ambiguous.add(member)
                    if len(collisions) < 20:
                        collisions.append({"member": member, "first": mapping[member], "second": base})
                mapping[member] = base
    with (args.out_dir / "split-member-map.tsv").open("w") as stream:
        for member, base in sorted(mapping.items()):
            stream.write(member + "\t" + base + "\n")
    def resolve_member(name):
        candidates = set()
        probe = name
        while True:
            if probe in mapping:
                candidates.add(mapping[probe])
            if not probe.endswith("_0"):
                break
            probe = probe[:-2]
        return candidates
    node_types = Counter()
    resolved_types = Counter()
    statuses = Counter()
    resolved_candidates = set()
    resolved_when = set()
    member_type = Counter()
    ambiguous_type = Counter()
    unresolved_type = Counter()
    examples = []
    ambiguous_examples = []
    unresolved_examples = []
    with args.topo.open() as stream:
        for record in node_records(stream):
            name = record["name"]
            statuses[record["status"]] += 1
            if record["status"] != "VALID_NODE":
                continue
            node_types[record["type"]] += 1
            original = original_ids.get(record["id"])
            candidates_for_name = set() if original is not None or name in ambiguous else resolve_member(name)
            mapped = next(iter(candidates_for_name)) if len(candidates_for_name) == 1 else None
            if mapped is not None:
                member_type[record["type"]] += 1
            if original is None and len(candidates_for_name) != 1:
                if len(candidates_for_name) > 1:
                    ambiguous.add(name)
                    ambiguous_type[record["type"]] += 1
                    if len(ambiguous_examples) < 20:
                        ambiguous_examples.append(name)
                else:
                    unresolved_type[record["type"]] += 1
                    if len(unresolved_examples) < 20:
                        unresolved_examples.append(name)
            base = original if original is not None else (mapped if mapped is not None else normalize(name))
            resolved_types[record["type"]] += 1
            if record["type"] == "NODE_OTHERS":
                if WHEN_COND.search(name):
                    resolved_when.add(base)
                else:
                    resolved_candidates.add(base)
            if mapped is not None and len(examples) < 20:
                examples.append({"member": name, "base": base})
    (args.out_dir / "split-ambiguous-names.txt").write_text("".join(name + "\n" for name in sorted(ambiguous)))
    matched = resolved_candidates & candidates
    (args.out_dir / "post-elim-candidates.txt").write_text("".join(name + "\n" for name in sorted(matched)))
    (args.out_dir / "post-elim-unmatched.txt").write_text("")
    report = {
        "init_array_nodes": array_nodes,
        "init_zero_extent_array_nodes": zero_extent_arrays,
        "generated_member_names": len(mapping),
        "resolved_split_member_nodes": sum(member_type.values()),
        "split_member_type_counts": dict(sorted(member_type.items())),
        "ambiguous_member_nodes": sum(ambiguous_type.values()),
        "ambiguous_member_type_counts": dict(sorted(ambiguous_type.items())),
        "ambiguous_name_count": len(ambiguous),
        "ambiguous_examples": ambiguous_examples,
        "unresolved_new_nodes": sum(unresolved_type.values()),
        "unresolved_new_type_counts": dict(sorted(unresolved_type.items())),
        "unresolved_examples": unresolved_examples,
        "split_name_collision_examples": collisions,
        "topo_status_counts": dict(sorted(statuses.items())),
        "topo_node_types": dict(sorted(node_types.items())),
        "resolved_node_types": dict(sorted(resolved_types.items())),
        "resolved_ordinary_candidates": len(resolved_candidates),
        "resolved_when_cond_nodes": len(resolved_when),
        "original_matched_candidates": len(candidates),
        "matched_original_candidates": len(matched),
        "new_candidates_not_in_original": sorted(resolved_candidates - candidates)[:30],
        "new_candidates_not_in_original_count": len(resolved_candidates - candidates),
        "original_candidates_missing_after_split": sorted(candidates - resolved_candidates)[:30],
        "original_candidates_missing_after_split_count": len(candidates - resolved_candidates),
        "examples": examples,
    }
    (args.out_dir / "split-map-stats.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
