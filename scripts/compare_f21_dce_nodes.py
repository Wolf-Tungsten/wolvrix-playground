"""Compare F21 GrhSIM/GSIM deletion on their common pre-DCE semantic Nodes."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

from grhsim_f21_dce_compare import (
    SEMANTIC_IDS,
    load_nodes,
    module_name,
    normalize,
    parse_semantic_tree,
)


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


def load_split_ids(original_init: Path, split_map: Path):
    originals = {}
    with original_init.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip() == '"edges": [':
                break
            if not line.lstrip().startswith('{"id":'):
                continue
            record = json.loads(line.strip().rstrip(","))
            originals[record["id"]] = normalize(record["name"])
    members = {}
    name_counts = Counter()
    with split_map.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.lstrip().startswith('{"parentId":'):
                continue
            record = json.loads(line.strip().rstrip(","))
            members[record["memberId"]] = normalize(record["parentName"])
            name_counts[record["memberName"]] += 1
    ambiguous = {name for name, count in name_counts.items() if count > 1}
    return originals, members, ambiguous


def collect_gsim_survivors(source: Path, candidates: set[str], originals: dict,
                           members: dict, ambiguous_names: set[str]):
    survivors = set()
    stats = Counter()
    with source.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip() == '"edges": [':
                break
            if not line.lstrip().startswith('{"id":'):
                continue
            stats["dumped_nodes"] += 1
            record = json.loads(line.strip().rstrip(","))
            if record["status"] != "VALID_NODE":
                stats["invalid_nodes"] += 1
                continue
            node_id = record["id"]
            if node_id in originals:
                base = originals[node_id]
            elif node_id in members:
                if record["name"] in ambiguous_names:
                    stats["ambiguous_split_nodes"] += 1
                base = members[node_id]
                stats["resolved_split_nodes"] += 1
            else:
                base = normalize(record["name"])
            if base in candidates:
                survivors.add(base)
    stats["survivors"] = len(survivors)
    log(f"GSIM survivors: {stats}")
    return survivors, dict(sorted(stats.items()))


def collect_grh_survivors(source: Path, names: list[str], name_to_id: dict[str, int]):
    sid_to_gid, _guard_names, tree_stats = parse_semantic_tree(source, name_to_id)
    survivors = set()
    stats = Counter()
    section = None
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
            stats[f"{section}_records"] += 1
            semantic_ids = SEMANTIC_IDS.search(line)
            if semantic_ids is None:
                stats[f"{section}_without_semantics"] += 1
                continue
            text = semantic_ids.group(1)
            if not text:
                continue
            for item in text.split(","):
                semantic_id = int(item)
                if semantic_id >= len(sid_to_gid):
                    raise ValueError(f"SemanticId {semantic_id} exceeds tree size")
                gid = sid_to_gid[semantic_id]
                if 0 < gid <= len(names):
                    survivors.add(names[gid - 1])
    stats["survivors"] = len(survivors)
    log(f"GRH survivors: {stats}")
    return survivors, {"tree": tree_stats, "entities": dict(sorted(stats.items()))}


def category_details(names: set[str]):
    modules = Counter(module_name(name) for name in names)
    return {
        "count": len(names),
        "top_modules": [{"module": name, "count": count}
                        for name, count in modules.most_common(20)],
        "examples": sorted(names)[:30],
    }


def write_names(path: Path, names) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for name in sorted(names):
            stream.write(name + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grh-before", required=True, type=Path)
    parser.add_argument("--grh-after", required=True, type=Path)
    parser.add_argument("--gsim-before", required=True, type=Path)
    parser.add_argument("--gsim-after", required=True, type=Path)
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--unmatched", required=True, type=Path)
    parser.add_argument("--gsim-original-init", required=True, type=Path)
    parser.add_argument("--gsim-split-map", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    names, name_to_id = load_nodes(args.candidates, args.unmatched)
    candidates = set(names)
    if not candidates:
        raise ValueError("empty common pre-DCE candidates")
    originals, members, ambiguous_names = load_split_ids(
        args.gsim_original_init, args.gsim_split_map)
    log(f"common pre-DCE candidates: {len(candidates)}")

    gsim_before, gsim_before_stats = collect_gsim_survivors(
        args.gsim_before, candidates, originals, members, ambiguous_names)
    gsim_after, gsim_after_stats = collect_gsim_survivors(
        args.gsim_after, candidates, originals, members, ambiguous_names)
    grh_before_direct, grh_before_stats = collect_grh_survivors(args.grh_before, names, name_to_id)
    grh_after, grh_after_stats = collect_grh_survivors(args.grh_after, names, name_to_id)
    grh_before_stats["direct_reference_candidates"] = len(grh_before_direct)
    grh_before_stats["name_only_candidates"] = len(candidates - grh_before_direct)

    stale_candidates = candidates - gsim_before
    candidates &= gsim_before
    if not candidates:
        raise ValueError("empty candidates after intersecting with the current GSIM graph")
    grh_after &= candidates
    gsim_after &= candidates
    grh_before_direct &= candidates
    grh_before_stats["direct_reference_candidates"] = len(grh_before_direct)
    grh_before_stats["name_only_candidates"] = len(candidates - grh_before_direct)
    if stale_candidates:
        write_names(args.out_dir / "stale-pre-candidates.txt", stale_candidates)

    both_survive = grh_after & gsim_after
    both_removed = candidates - (grh_after | gsim_after)
    grh_only_removed = gsim_after - grh_after
    gsim_only_removed = grh_after - gsim_after

    report = {
        "schema": "wolvrix.f21.deletion-matrix.v1",
        "common_pre_dce_candidates": len(candidates),
        "stale_pre_candidates": category_details(stale_candidates),
        "matrix": {
            "both_removed": category_details(both_removed),
            "grh_only_removed": category_details(grh_only_removed),
            "gsim_only_removed": category_details(gsim_only_removed),
            "both_survive": category_details(both_survive),
        },
        "grh_before": grh_before_stats,
        "grh_after": grh_after_stats,
        "gsim_before": gsim_before_stats,
        "gsim_after": gsim_after_stats,
    }
    total = len(candidates)
    if (len(both_removed) + len(grh_only_removed) + len(gsim_only_removed) +
            len(both_survive)) != total:
        raise AssertionError("deletion matrix does not close")
    report["ratios"] = {
        "both_removed": len(both_removed) / total,
        "grh_only_removed": len(grh_only_removed) / total,
        "gsim_only_removed": len(gsim_only_removed) / total,
        "both_survive": len(both_survive) / total,
    }
    write_names(args.out_dir / "common-survivors.txt", both_survive)
    write_names(args.out_dir / "grh-survivors.txt", grh_after)
    write_names(args.out_dir / "gsim-survivors.txt", gsim_after)
    write_names(args.out_dir / "gsim-only-retained.txt", gsim_only_removed)
    (args.out_dir / "empty-unmatched.txt").write_text("", encoding="utf-8")
    (args.out_dir / "deletion-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    log(f"deletion matrix: {report['ratios']}")


if __name__ == "__main__":
    main()
