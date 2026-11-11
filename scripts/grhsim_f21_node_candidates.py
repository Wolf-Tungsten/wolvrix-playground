"""Read-only F21 probe for GSIM combinational Nodes and GRH semantic paths."""
from __future__ import annotations

import argparse
import json
import re
from array import array
from collections import Counter
from pathlib import Path

TREE_NODE = re.compile(
    r'\{"parent": (\d+), "kind": "(module|declaration|expression|field|element)", '
    r'"name": ("(?:\\.|[^"\\])*")(?:, "index": (-?\d+))?\},?'
)
KIND = {name: index for index, name in enumerate(
    ("invalid", "module", "declaration", "expression", "field", "element"))}
KIND_NAME = {index: name for name, index in KIND.items()}
WHEN_COND = re.compile(r'(?:^|\$)WHEN_COND_\d+$')


def normalize(name: str) -> str:
    return name.replace("$$", "__DOT__")


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def gsim_probe(source: Path, output: Path, candidates_path: Path) -> None:
    types: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    dimensions: Counter[str] = Counter()
    candidates: set[str] = set()
    normalized_collisions = []
    when_count = 0
    candidate_array_count = 0
    candidate_zero_width = 0
    with source.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip() == '"edges": [':
                break
            if not line.lstrip().startswith('{"id":'):
                continue
            record = json.loads(line.strip().rstrip(","))
            name = record["name"]
            node_type = record["type"]
            types[node_type] += 1
            statuses[record["status"]] += 1
            if node_type != "NODE_OTHERS":
                continue
            if record["dimension"]:
                dimensions["others_array"] += 1
            else:
                dimensions["others_scalar"] += 1
            if WHEN_COND.search(name):
                when_count += 1
                continue
            key = normalize(name)
            if key in candidates and len(normalized_collisions) < 20:
                normalized_collisions.append(name)
            candidates.add(key)
            if record["dimension"]:
                candidate_array_count += 1
            if record["width"] == 0:
                candidate_zero_width += 1
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    with candidates_path.open("w", encoding="utf-8") as stream:
        for name in sorted(candidates):
            stream.write(name + "\n")
    write_json(output, {
        "input": str(source),
        "node_count_in_dump": sum(types.values()),
        "node_count_excluding_memory": sum(types.values()) - types["NODE_MEMORY"],
        "node_types": dict(sorted(types.items())),
        "node_statuses": dict(sorted(statuses.items())),
        "others_dimensions": dict(sorted(dimensions.items())),
        "when_cond_nodes_excluded": when_count,
        "ordinary_others_candidates": len(candidates),
        "ordinary_others_array_nodes": candidate_array_count,
        "ordinary_others_zero_width_nodes": candidate_zero_width,
        "normalized_name_collision_examples": normalized_collisions,
        "candidates_file": str(candidates_path),
        "name_normalization": "GSIM $$ -> GRH __DOT__; no other normalization",
    })


def grh_probe(source: Path, output: Path, candidates_path: Path,
              unmatched_path: Path) -> None:
    with candidates_path.open("r", encoding="utf-8") as stream:
        candidates = {line.rstrip("\n") for line in stream}
    kinds: Counter[str] = Counter()
    leaves: Counter[str] = Counter()
    matched_leaves: Counter[str] = Counter()
    expression_roles: Counter[str] = Counter()
    matched: set[str] = set()
    paths: list[str] = []
    names: list[str] = []
    parents = array("I")
    node_kinds = array("B")
    children = array("I")
    declaration_nodes: dict[tuple[int, str], int] = {}
    module_children: list[tuple[int, str]] = []
    roots = 0
    leaf_count = 0
    matched_leaf_count = 0
    with source.open("r", encoding="utf-8") as stream:
        for line in stream:
            match = TREE_NODE.fullmatch(line.strip())
            if not match:
                continue
            parent = int(match.group(1))
            kind_text = match.group(2)
            kind = KIND[kind_text]
            name = json.loads(match.group(3))
            index = match.group(4)
            kinds[kind_text] += 1
            if parent == 0:
                roots += 1
                paths = ["", ""]
                names = ["", ""]
                parents = array("I", [0, 0])
                node_kinds = array("B", [0, KIND["module"]])
                children = array("I", [0, 0])
                declaration_nodes.clear()
                module_children.clear()
                continue
            if parent >= len(paths):
                raise ValueError(f"invalid semantic parent {parent} at semantic node {len(paths)}")
            semantic_id = len(paths)
            children[parent] += 1
            parent_kind = node_kinds[parent]
            paths.append("")
            names.append("[" + str(index) + "]" if kind == KIND["element"] else name)
            parents.append(parent)
            node_kinds.append(kind)
            children.append(0)
            if kind == KIND["declaration"] and parent_kind == KIND["module"]:
                declaration_nodes[(parent, name)] = semantic_id
            elif kind == KIND["module"]:
                module_children.append((parent, name))
            if kind == KIND["expression"]:
                if parent_kind != KIND["module"]:
                    expression_roles["non_root_expression"] += 1
                elif name.startswith("guard_"):
                    expression_roles["generated_guard"] += 1
                elif name.startswith("effect@"):
                    expression_roles["generated_effect"] += 1
                else:
                    expression_roles["firrtl_node_or_other"] += 1
    instance_declarations: set[int] = set()
    missing_instance_declarations = []
    for parent, name in module_children:
        declaration = declaration_nodes.get((parent, name))
        if declaration is None:
            missing_instance_declarations.append(paths[parent] + "$" + name)
        else:
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
        paths[semantic_id] = paths[parent] + separator + names[semantic_id]
    for semantic_id in range(1, len(paths)):
        if children[semantic_id] or node_kinds[semantic_id] == KIND["module"]:
            continue
        kind_text = KIND_NAME[node_kinds[semantic_id]]
        key = paths[semantic_id]
        leaf_count += 1
        leaves[kind_text] += 1
        if key in candidates:
            matched.add(key)
            matched_leaf_count += 1
            matched_leaves[kind_text] += 1
    unmatched = candidates - matched
    unmatched_path.parent.mkdir(parents=True, exist_ok=True)
    with unmatched_path.open("w", encoding="utf-8") as stream:
        for name in sorted(unmatched):
            stream.write(name + "\n")
    write_json(output, {
        "input": str(source),
        "module_roots": roots,
        "instance_declarations": len(instance_declarations),
        "module_children_without_instance_declaration": missing_instance_declarations[:20],
        "semantic_nodes": dict(sorted(kinds.items())),
        "semantic_nodes_total": sum(kinds.values()),
        "expression_roles": dict(sorted(expression_roles.items())),
        "semantic_leaves": dict(sorted(leaves.items())),
        "semantic_leaves_total": leaf_count,
        "gsim_candidates": len(candidates),
        "exact_name_matches": len(matched),
        "exact_name_match_ratio": len(matched) / len(candidates) if candidates else 1.0,
        "gsim_candidates_unmatched": len(unmatched),
        "gsim_unmatched_examples": sorted(unmatched)[:30],
        "gsim_unmatched_file": str(unmatched_path),
        "grh_projected_leaves_matched": matched_leaf_count,
        "grh_projected_leaves_matched_by_kind": dict(sorted(matched_leaves.items())),
        "grh_duplicate_leaf_projections_on_matches": matched_leaf_count - len(matched),
        "caveat": "Name projection only; not a Node DAG or expression equivalence result.",
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)
    for mode in ("gsim", "grh"):
        sub = subparsers.add_parser(mode)
        sub.add_argument("--input", type=Path, required=True)
        sub.add_argument("--output", type=Path, required=True)
        sub.add_argument("--candidates", type=Path, required=True)
        if mode == "grh":
            sub.add_argument("--unmatched", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "gsim":
        gsim_probe(args.input, args.output, args.candidates)
    else:
        grh_probe(args.input, args.output, args.candidates, args.unmatched)


if __name__ == "__main__":
    main()
