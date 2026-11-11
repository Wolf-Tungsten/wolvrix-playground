"""Compare all array-typed GRH values with GSIM dimensioned Nodes."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from grhsim_f21_dce_compare import (
    RECORD_ID,
    RESULTS,
    SEMANTIC_IDS,
    int_array,
    module_name,
    normalize,
    parse_semantic_tree,
)
from trace_f21_retained import OP_KIND, OP_SYMBOL

SHAPE = re.compile(r'"shape": \[([0-9, ]*)\]')
WIDTH = re.compile(r'"w": (-?\d+)')


class AllSemanticNames(dict):
    def get(self, key, default=None):
        if key not in self:
            self[key] = len(self)
        return self[key]


def product(values: list[int]) -> int:
    result = 1
    for value in values:
        result *= value
    return result


def scan_gsim(source: Path) -> list[dict]:
    records = []
    with source.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip() == '"edges": [':
                break
            if not line.lstrip().startswith('{"id":'):
                continue
            record = json.loads(line.strip().rstrip(","))
            shape = record.get("dimension") or []
            if record.get("status") != "VALID_NODE" or not shape:
                continue
            width = int(record["width"])
            records.append({
                "id": int(record["id"]),
                "name": normalize(record["name"]),
                "aliases": [normalize(record["name"])],
                "shape": shape,
                "width": width * product(shape) if width >= 0 else 0,
                "elementWidth": width,
                "sign": int(record.get("sign", 0)),
                "nodeType": record.get("type", "unknown"),
            })
    return records


def scan_grh(source: Path) -> tuple[list[dict], dict]:
    semantic_names = AllSemanticNames()
    sid_to_gid, _guards, tree_stats = parse_semantic_tree(source, semantic_names)
    names = [name for name, _index in sorted(semantic_names.items(), key=lambda item: item[1])]
    records = {}
    section = ""
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
            if section == "vals":
                shape_match = SHAPE.search(line)
                if shape_match is None:
                    continue
                shape = [int(item) for item in shape_match.group(1).split(",")]
                width_match = WIDTH.search(line)
                if width_match is None:
                    raise ValueError(f"array value {record_id} lacks width")
                symbol_match = OP_SYMBOL.search(line)
                semantic_ids = int_array(SEMANTIC_IDS, line) or []
                width = int(width_match.group(1))
                records[record_id] = {
                    "id": record_id,
                    "symbol": json.loads(symbol_match.group(1)) if symbol_match else None,
                    "semanticIds": semantic_ids,
                    "opSemanticIds": [],
                    "shape": shape,
                    "width": width,
                    "elementWidth": width // product(shape) if product(shape) else 0,
                    "sign": 1 if '"sgn": true' in line else 0,
                    "nodeType": "grh_value",
                    "producerKind": "declaration_or_port",
                }
                continue
            results = int_array(RESULTS, line)
            if results is None:
                continue
            semantic_ids = int_array(SEMANTIC_IDS, line) or []
            kind_match = OP_KIND.search(line)
            for value in results:
                if value in records:
                    records[value]["opSemanticIds"] = semantic_ids
                    if kind_match:
                        records[value]["producerKind"] = kind_match.group(1)
    for record in records.values():
        aliases = []
        if record["symbol"]:
            aliases.append(record["symbol"])
        for semantic_id in [*record["semanticIds"], *record["opSemanticIds"]]:
            if semantic_id >= len(sid_to_gid):
                raise ValueError(f"SemanticId {semantic_id} exceeds tree size")
            gid = sid_to_gid[semantic_id]
            if gid:
                aliases.append(names[gid - 1])
        record["aliases"] = list(dict.fromkeys(aliases))
        record["name"] = record["symbol"] or (aliases[0] if aliases else "")
        del record["semanticIds"], record["opSemanticIds"]
    stats = {
        "tree": tree_stats,
        "array_value_records": len(records),
        "without_symbol": sum(1 for record in records.values() if not record["symbol"]),
        "without_any_name": sum(1 for record in records.values() if not record["aliases"]),
    }
    return list(records.values()), stats


def attach_primary_names(records: list[dict], reference_names: set[str]) -> None:
    for record in records:
        if record["name"] in reference_names:
            continue
        record["name"] = next((name for name in record["aliases"] if name in reference_names), record["name"])


def load_split_parents(source: Path | None) -> dict:
    if source is None:
        return {}
    parents = {}
    with source.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.lstrip().startswith('{"parentId":'):
                continue
            record = json.loads(line.strip().rstrip(","))
            parents[normalize(record["parentName"])] = {
                "shape": record["parentDimension"],
                "elementWidth": int(record["parentWidth"]),
            }
    return parents


def compare_array_values(grh_records: list[dict], gsim_records: list[dict], split_parents=None) -> dict:
    split_parents = split_parents or {}
    unnamed = [record for record in grh_records if not record["aliases"]]
    grh_records = [record for record in grh_records if record["aliases"]]
    grh_by_name = defaultdict(list)
    gsim_by_name = defaultdict(list)
    for record in grh_records:
        grh_by_name[record["name"]].append(record)
    for record in gsim_records:
        gsim_by_name[record["name"]].append(record)
    names = sorted(set(grh_by_name) | set(gsim_by_name))
    name_counts = Counter()
    record_counts = Counter()
    record_counts["grh_unmapped"] = len(unnamed)
    type_counts = defaultdict(Counter)
    grh_details = defaultdict(Counter)
    gsim_details = defaultdict(Counter)
    split_details = defaultdict(Counter)
    examples = defaultdict(list)
    mismatches = []
    shape_mismatch_relations = Counter()

    def geometry(record: dict) -> tuple:
        return (tuple(record["shape"]), record["elementWidth"])

    def compact(shape):
        return tuple(dimension for dimension in shape if dimension != 1)

    def is_suffix(left, right):
        return len(left) <= len(right) and tuple(left) == tuple(right[-len(left):]) if left else False

    def mismatch_relation(left, right):
        if any(compact(a["shape"]) == compact(b["shape"]) for a in left for b in right):
            return "degenerate_dimension_one"
        if any(is_suffix(a["shape"], b["shape"]) or is_suffix(b["shape"], a["shape"])
               for a in left for b in right):
            return "outer_dimension_reduced"
        return "other_shape_mismatch"

    def accumulate(details, record, name, producer_key):
        details["records"] += 1
        details["packed_bits"] += record["width"]
        details[f"{producer_key}:{record[producer_key]}"] += 1
        details[f"shape:{json.dumps(record['shape'], separators=(',', ':'))}"] += 1
        details[f"module:{module_name(name)}"] += 1

    for name in names:
        left = grh_by_name.get(name, [])
        right = gsim_by_name.get(name, [])
        if not left:
            category = "gsim_only"
        elif not right:
            category = "grh_only"
        else:
            left_geometries = {geometry(record) for record in left}
            right_geometries = {geometry(record) for record in right}
            if left_geometries & right_geometries:
                category = "exact"
            elif all(record["elementWidth"] < 0 for record in right):
                category = "unknown_gsim_width"
            elif {tuple(record["shape"]) for record in left} & {tuple(record["shape"]) for record in right}:
                category = "element_width_mismatch"
            else:
                category = "shape_mismatch"
        name_counts[category] += 1
        record_counts[f"grh_{category}"] += len(left)
        record_counts[f"gsim_{category}"] += len(right)
        for record in left:
            accumulate(grh_details[category], record, name, "producerKind")
        for record in right:
            accumulate(gsim_details[category], record, name, "nodeType")
            type_counts[category][record["nodeType"]] += 1
        if category != "exact" and len(examples[category]) < 40:
            examples[category].append({
                "name": name,
                "splitParent": split_parents.get(name),
                "grh": [{"id": record["id"], "shape": record["shape"],
                         "elementWidth": record["elementWidth"], "width": record["width"],
                         "producer": record["producerKind"]} for record in left[:4]],
                "gsim": [{"id": record["id"], "shape": record["shape"],
                          "elementWidth": record["elementWidth"], "width": record["width"],
                          "type": record["nodeType"]} for record in right[:4]],
            })
        if category in {"shape_mismatch", "element_width_mismatch"}:
            mismatches.append(name)
        if category == "shape_mismatch":
            shape_mismatch_relations[mismatch_relation(left, right)] += 1
    for side, records in (("grh", grh_records), ("gsim", gsim_records)):
        for record in records:
            parent = split_parents.get(record["name"])
            if parent is None:
                continue
            relation = ("same_parent_geometry" if geometry(record) ==
                        (tuple(parent["shape"]), parent["elementWidth"]) else "different_from_parent")
            detail = split_details[f"{side}_{relation}"]
            detail["records"] += 1
            detail["packed_bits"] += record["width"]
            detail[f"shape:{json.dumps(record['shape'], separators=(',', ':'))}"] += 1
            key = "producerKind" if side == "grh" else "nodeType"
            detail[f"{key}:{record[key]}"] += 1
    sign_mismatches = []
    for name in names:
        if name not in grh_by_name or name not in gsim_by_name:
            continue
        left_signs = {record["sign"] for record in grh_by_name[name]}
        right_signs = {record["sign"] for record in gsim_by_name[name]}
        if left_signs != right_signs:
            sign_mismatches.append(name)
    return {
        "names": dict(sorted(name_counts.items())),
        "records": dict(sorted(record_counts.items())),
        "gsim_types": {category: dict(sorted(counts.items())) for category, counts in sorted(type_counts.items())},
        "grh_details": {category: dict(sorted(counts.items())) for category, counts in sorted(grh_details.items())},
        "gsim_details": {category: dict(sorted(counts.items())) for category, counts in sorted(gsim_details.items())},
        "split_parent_details": {category: dict(sorted(counts.items())) for category, counts in sorted(split_details.items())},
        "sign_mismatch_names": len(sign_mismatches),
        "shape_or_width_mismatch_names": len(mismatches),
        "shape_mismatch_relations": dict(sorted(shape_mismatch_relations.items())),
        "examples": dict(sorted(examples.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grh", required=True, type=Path)
    parser.add_argument("--gsim", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--label", required=True)
    parser.add_argument("--gsim-split-map", type=Path)
    args = parser.parse_args()
    gsim_records = scan_gsim(args.gsim)
    split_parents = load_split_parents(args.gsim_split_map)
    grh_records, grh_stats = scan_grh(args.grh)
    attach_primary_names(grh_records, {record["name"] for record in gsim_records})
    comparison = compare_array_values(grh_records, gsim_records, split_parents)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": "wolvrix.f21.array-value-comparison.v1",
        "label": args.label,
        "inputs": {"grh": str(args.grh), "gsim": str(args.gsim), "gsim_split_map": str(args.gsim_split_map)},
        "semantics": {
            "shape": "GRH shape versus GSIM dimension; [1] is included.",
            "width": "GRH w is packed width. GSIM width is per-element width; packed width is width * product(dimension).",
            "names": "Full symbol is preferred, then SemanticId aliases matching a GSIM name. Records and unique names are reported separately.",
        },
        "grh": grh_stats,
        "comparison": comparison,
    }
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"label": args.label, "names": comparison["names"], "records": comparison["records"],
                      "grh": grh_stats}, sort_keys=True))


if __name__ == "__main__":
    main()
