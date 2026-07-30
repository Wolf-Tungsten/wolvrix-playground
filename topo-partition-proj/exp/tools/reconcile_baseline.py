#!/usr/bin/env python3

"""Reconcile the exported plain-baseline block assignment against the exported
instruction graph (topo-partition-proj Phase 0 / M0).

Reads the two wolvrix exports and independently recomputes the scoreboard
numbers from the graph side, then compares them with the numbers the
production scheduler wrote into the assignment header:

- dag_edges: dedup (producer block, consumer block) over def_use edges that
  cross blocks (order edges excluded by definition);
- compute_compute_value_pairs: dedup (value, consuming compute block) where
  the value is not defined in that block; state targets / interface inputs
  (external_read) are permanent boundaries and count for every consuming
  compute block; reads inside commit blocks never count;
- incoming_copy_cost: the same pairs weighted by max(1, ceil(width / 64)).

Exit status 0 means both sides agree. Usage:

    reconcile_baseline.py <instruction_graph.jsonl> <block_assignment.jsonl>
"""

from __future__ import annotations

import json
import sys
from array import array


def fail(message: str) -> int:
    sys.stderr.write(f"[reconcile-baseline] FAIL: {message}\n")
    return 1


def main() -> int:
    if len(sys.argv) != 3:
        sys.stderr.write(__doc__ or "")
        return 2
    graph_path, assignment_path = sys.argv[1], sys.argv[2]

    commit_blocks: set[int] = set()
    header: dict | None = None
    instr_block = array("I")
    block_records = 0
    with open(assignment_path) as stream:
        for line in stream:
            record = json.loads(line)
            kind = record["record"]
            if kind == "header":
                header = record
            elif kind == "block":
                block_records += 1
                if record["kind"] == "commit":
                    commit_blocks.add(record["id"])
            elif kind == "assign":
                instr_block.append(record["block"])
    if header is None:
        return fail("assignment file has no header record")
    if len(instr_block) != header["instructions"]:
        return fail(
            f"assign records {len(instr_block)} != header instructions "
            f"{header['instructions']}"
        )
    if block_records != header["blocks"]:
        return fail(
            f"block records {block_records} != header blocks {header['blocks']}"
        )

    dag_pairs: set[int] = set()
    value_pairs: set[int] = set()
    incoming_copy_cost = 0
    edge_records = 0
    node_records = 0
    with open(graph_path) as stream:
        graph_header = json.loads(stream.readline())
        if graph_header["instructions"] != header["instructions"]:
            return fail("graph and assignment disagree on the instruction count")
        for line in stream:
            record = json.loads(line)
            if record["record"] == "node":
                node_records += 1
                continue
            edge_records += 1
            kind = record["kind"]
            if kind == "order":
                continue
            target_block = instr_block[record["dst"]]
            if kind == "def_use":
                source_block = instr_block[record["src"]]
                if source_block == target_block:
                    continue
                dag_pairs.add((source_block << 32) | target_block)
            # external_read has no producer block: it is always a boundary.
            if target_block in commit_blocks:
                continue
            pair = (record["var"] << 32) | target_block
            if pair in value_pairs:
                continue
            value_pairs.add(pair)
            incoming_copy_cost += max(1, (record["width"] + 63) // 64)
    if node_records != header["instructions"]:
        return fail(
            f"node records {node_records} != header instructions "
            f"{header['instructions']}"
        )

    expected = {
        "dag_edges": header["dag_edges"],
        "compute_compute_value_pairs": header["compute_compute_value_pairs"],
        "incoming_copy_cost": header["incoming_copy_cost"],
    }
    actual = {
        "dag_edges": len(dag_pairs),
        "compute_compute_value_pairs": len(value_pairs),
        "incoming_copy_cost": incoming_copy_cost,
    }
    mismatches = [name for name in expected if expected[name] != actual[name]]
    for name in expected:
        sys.stderr.write(
            f"[reconcile-baseline] {name}: production={expected[name]} "
            f"recomputed={actual[name]}\n"
        )
    if mismatches:
        return fail("scoreboard mismatch on: " + ", ".join(mismatches))
    sys.stderr.write(
        f"[reconcile-baseline] OK: {edge_records} edges reconciled over "
        f"{node_records} instructions / {block_records} blocks\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
