#!/usr/bin/env python3

"""Score a block assignment with the harness scorer and (optionally) compare
against the production scoreboard stored in the assignment header.

Usage:

    score_baseline.py <instruction_graph.jsonl> <block_assignment.jsonl>

Exit status 0 means every production header metric matches the harness
recomputation (docs/06 reconciliation, M0 gate).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.graph import load_graph  # noqa: E402
from harness.scorer import load_assignment, score_assignment  # noqa: E402


def main() -> int:
    if len(sys.argv) != 3:
        sys.stderr.write(__doc__ or "")
        return 2
    graph_path, assignment_path = sys.argv[1], sys.argv[2]
    started = time.time()
    graph = load_graph(graph_path)
    assignment = load_assignment(assignment_path)
    board = score_assignment(graph, assignment.instr_block, assignment.commit_mask)
    header = assignment.header
    print(f"[score] computed in {time.time() - started:.1f}s")
    rows = [
        ("incoming_copy_cost", board.cost, header.get("incoming_copy_cost")),
        ("dag_edges", board.dag_edges, header.get("dag_edges")),
        (
            "compute_compute_value_pairs",
            board.compute_compute_value_pairs,
            header.get("compute_compute_value_pairs"),
        ),
        ("footprint(blocks)", assignment.blocks, header.get("blocks")),
        ("compute_blocks", assignment.compute_blocks, header.get("compute_blocks")),
        ("commit_blocks", assignment.commit_blocks, header.get("commit_blocks")),
    ]
    mismatches = []
    for name, actual, expected in rows:
        marker = ""
        if expected is not None and expected != actual:
            mismatches.append(name)
            marker = "  <-- MISMATCH"
        print(f"[score] {name:30s} harness={actual:<12d} production={expected}{marker}")
    if mismatches:
        sys.stderr.write("[score] FAIL: mismatch on " + ", ".join(mismatches) + "\n")
        return 1
    print("[score] OK: harness scorer matches the production scoreboard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
