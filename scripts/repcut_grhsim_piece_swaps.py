#!/usr/bin/env python3
"""Generate automatic two-way whole-piece swaps for GrhSIM refinement.

The source and destination partition sets come from the current baseline
profile: expensive lanes are paired with lanes that have the most headroom.
Only complete source-model pieces are exchanged.  No RTL names or fixed
partition numbers are used; exact assignment and backend-plan evaluation must
follow before a candidate can be compiled.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path

from repcut_grhsim_local_search_rank import load_eval_times
from repcut_grhsim_piece_candidates import propose
from repcut_grhsim_plan_gate import identity, save


def generate(model: Path, features: Path, assignment: Path, parts: Path,
             source_count: int, target_count: int, top: int,
             output: Path) -> dict:
    labels = list(map(int, assignment.read_text().split()))
    partitions = max(labels, default=-1) + 1
    timings = load_eval_times(parts)
    if set(timings) != set(range(partitions)):
        raise ValueError("profile partition set does not match assignment")
    if source_count < 1 or target_count < 1 or top < 1:
        raise ValueError("source-count, target-count, and top must be positive")
    sources = sorted(timings, key=lambda p: (-timings[p]["eval"], p))[:source_count]
    targets = [p for p in sorted(timings, key=lambda p: (timings[p]["eval"], p))
               if p not in sources][:target_count]
    if not targets:
        raise ValueError("no destination partitions remain after source selection")

    # Ask the common proposal generator for the top complete pieces in every
    # selected lane.  It returns destination-expanded records; retain one
    # representative per (source, piece) before constructing swaps.
    records = propose(model, features, labels, sorted(set(sources + targets)),
                      partitions, top, partitions - 1)
    pieces: dict[int, dict[int, dict]] = defaultdict(dict)
    for record in records:
        pieces[record["source"]].setdefault(record["piece"], record)

    output.mkdir(parents=True, exist_ok=False)
    candidates = []
    seen = set()
    for source in sources:
        for target in targets:
            source_records = sorted(pieces[source].values(),
                                    key=lambda r: (-r["shape_score"], -len(r["members"]), r["piece"]))[:top]
            target_records = sorted(pieces[target].values(),
                                    key=lambda r: (-r["shape_score"], -len(r["members"]), r["piece"]))[:top]
            for left in source_records:
                for right in target_records:
                    if left["piece"] == right["piece"]:
                        continue
                    moved = labels.copy()
                    valid = True
                    for atom in left["members"]:
                        if labels[atom] != source:
                            valid = False
                            break
                        moved[atom] = target
                    if valid:
                        for atom in right["members"]:
                            if labels[atom] != target:
                                valid = False
                                break
                            moved[atom] = source
                    if not valid:
                        continue
                    key = tuple(moved)
                    if key in seen:
                        continue
                    seen.add(key)
                    name = (f"swap_p{source}_p{target}_piece_{left['piece']}_"
                            f"{right['piece']}")
                    path = output / (name + ".assignment")
                    path.write_text("".join(f"{label}\n" for label in moved))
                    candidates.append({
                        "name": name,
                        "source": source,
                        "destination": target,
                        # Keep the same proposal schema consumed by the
                        # bounded exact evaluator.  A swap moves one complete
                        # piece in each direction, so the aggregate fields
                        # describe both sides of the exchange.
                        "moved_atoms": (len(left["members"])
                                        + len(right["members"])),
                        "shape_score": (left["shape_score"]
                                        + right["shape_score"]),
                        "source_piece": left["piece"],
                        "destination_piece": right["piece"],
                        "source_shape_score": left["shape_score"],
                        "destination_shape_score": right["shape_score"],
                        "source_moved_atoms": len(left["members"]),
                        "destination_moved_atoms": len(right["members"]),
                        "assignment": identity(path),
                    })
    if not candidates:
        raise ValueError("no legal swaps generated")
    inputs = {name: identity(path) for name, path in {
        "model": model, "features": features, "assignment": assignment,
        "parts": parts,
    }.items()}
    result = {
        "status": "proposals_only",
        "inputs": inputs,
        "partitions": partitions,
        "source_mode": "profile_top_eval",
        "source_partitions": sources,
        "target_partitions": targets,
        "baseline_eval_us": {str(p): timings[p]["eval"] for p in timings},
        "selected_features": "common backend-shape whole-piece proposals",
        "timing_used": "only to choose source and headroom destination sets",
        "candidates": candidates,
        "needs_exact_assignment_and_backend_evaluation": True,
    }
    save(output / "selection.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--assignment", type=Path, required=True)
    parser.add_argument("--parts", type=Path, required=True)
    parser.add_argument("--source-count", type=int, default=4)
    parser.add_argument("--target-count", type=int, default=8)
    parser.add_argument("--top", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = generate(args.model, args.features, args.assignment, args.parts,
                      args.source_count, args.target_count, args.top, args.output)
    print(json.dumps({
        "candidates": len(result["candidates"]),
        "sources": result["source_partitions"],
        "targets": result["target_partitions"],
        "output": str(args.output),
    }))


if __name__ == "__main__":
    main()
