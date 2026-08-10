#!/usr/bin/env python3

"""Supernode-construction alignment metrics: grhsim AM compute blocks vs gsim
supernodes (topic pdocs/grh-notepad/supernode-align).

Both sides are read from topo-proj JSONL exports, which share the
``wolvrix.am-instruction-graph.v1`` / ``wolvrix.am-block-assignment.v1``
formats (gsim side: ``--export-topo-proj``; AM side:
``WOLVRIX_GRHSIM_AM_INSTRUCTION_GRAPH_JSONL`` /
``WOLVRIX_GRHSIM_AM_BLOCK_ASSIGNMENT_JSONL``), so one loader serves both.

Primary alignment metric (NO0012 口径裁定): ``cross_values_compute_network`` —
distinct values with at least one def_use edge whose producer block !=
consumer block, counting only values that cross to at least one
non-state-write consumer. State-write consumers (AM commit blocks, gsim
state-write supernode members) are execution-model taps and excluded on both
sides alike.

Node-unit 口径 (NO0007): the alignment node unit is the scheduling atom.
When the AM assignment export carries post-merge atom ids
(``wolvrix.am-block-assignment.v1`` assign records with ``atom``, NO0007 P3),
``nodes``/``block_node_*`` count atoms — the AM counterpart of a gsim node
(1 compute enode + folded when skeleton; NO0007 §1-§2). Legacy datasets and
the gsim side have no atom column and fall back to instruction/node counts,
which for gsim is already the aligned unit. cross_values* are distinct-value
metrics and are multiplicity- and atom-invariant given the same assignment.

Legacy metrics: ``cross_values`` (all consumers) and the block-level
compute-consumer variant; context: the production scoreboard
(dag_edges / compute_compute_value_pairs / incoming_copy_cost) and
external-read (state / interface) unique value counts.

Verdict (only printed when both sides are given):
  AM supernodes (compute + commit blocks) <= gsim supernodes, and
  AM cross_values_compute_network / gsim cross_values_compute_network <= 1.10.
Methodology ruling (2026-08-08, user): cross-metric comparisons are only
  meaningful at *matched* supernode counts — a coarser partition cuts fewer
  edges by construction. The compare output therefore always prints
  ``block_count_ratio`` and ``block_count_matched`` (AM/gsim within +/-10%),
  and ``aligned`` requires the match in addition to the ratio gate.

Usage:
    supernode_align_metrics.py --gsim-graph G --gsim-assign A \
        --am-graph G --am-assign A [--json OUT]

Run with the repo venv (needs numpy): .venv/bin/python.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "topo-partition-proj" / "exp"))

import numpy as np  # noqa: E402

from harness.graph import load_graph  # noqa: E402
from harness.scorer import load_assignment, score_assignment  # noqa: E402

RATIO_TARGET = 1.10


def measure_side(graph_path: Path, assign_path: Path) -> dict:
    started = time.time()
    graph = load_graph(graph_path, use_cache=True, verbose=False)
    assignment = load_assignment(assign_path)
    instr_block = assignment.instr_block.astype(np.int64)
    commit_mask = assignment.commit_mask

    producer_block = instr_block[graph.du_src.astype(np.int64)]
    consumer_block = instr_block[graph.du_dst.astype(np.int64)]
    cross = producer_block != consumer_block
    cross_values = int(np.unique(graph.du_var[cross]).size)
    compute_consumer = ~commit_mask[consumer_block]
    cross_values_compute_consumer = int(np.unique(graph.du_var[cross & compute_consumer]).size)
    # compute-network metric (NO0012): drop values whose crossing consumers are
    # all state-write instructions, on BOTH sides — AM commit blocks and gsim
    # state-write members alike. A value crossing to both a state write and a
    # compute consumer still counts.
    state_write_consumer = graph.state_write[graph.du_dst.astype(np.int64)]
    cross_values_compute_network = int(
        np.unique(graph.du_var[cross & ~state_write_consumer]).size
    )

    # Distinct value-edge 口径 (NO0007): unique (consumer, var) pairs — the
    # gsim export dedups refs per (dst, node) at source while the AM export is
    # per-operand; this metric is the unit-fair edge count for both sides.
    def_use_value_edges = int(
        np.unique(
            (graph.du_dst.astype(np.uint64) << 32) | graph.du_var.astype(np.uint64)
        ).size
    )

    ext_consumer_block = instr_block[graph.er_dst.astype(np.int64)]
    external_read_values = int(np.unique(graph.er_var).size)
    external_read_values_compute_consumer = int(
        np.unique(graph.er_var[~commit_mask[ext_consumer_block]]).size
    )

    board = score_assignment(graph, assignment.instr_block, commit_mask)

    # Node-unit accounting (NO0007): atoms when the assignment carries them,
    # instructions otherwise (legacy AM datasets, gsim nodes).
    if assignment.instr_atom is not None:
        pair = (instr_block.astype(np.uint64) << 32) | assignment.instr_atom.astype(np.uint64)
        uniq_blocks = (np.unique(pair) >> 32).astype(np.int64)
        node_unit = "atom"
        nodes = int(np.unique(assignment.instr_atom).size)
    else:
        uniq_blocks = None
        node_unit = "instruction"
        nodes = int(graph.instructions)
    if uniq_blocks is not None:
        block_sizes = np.bincount(uniq_blocks, minlength=2)[1:]
    else:
        block_sizes = np.bincount(instr_block[instr_block > 0])
    block_node_max = int(block_sizes.max()) if block_sizes.size else 0
    block_node_mean = round(float(block_sizes.mean()), 2) if block_sizes.size else 0.0

    return {
        "graph": str(graph_path),
        "assignment": str(assign_path),
        "instructions": int(graph.instructions),
        "variables": int(graph.variables),
        "def_use_edges": int(graph.du_src.size),
        "def_use_value_edges": def_use_value_edges,
        "external_reads": int(graph.er_dst.size),
        "blocks": int(assignment.blocks),
        "compute_blocks": int(assignment.compute_blocks),
        "commit_blocks": int(assignment.commit_blocks),
        "supernodes": int(assignment.compute_blocks + assignment.commit_blocks),
        "node_unit": node_unit,
        "nodes": nodes,
        "block_node_max": block_node_max,
        "block_node_mean": block_node_mean,
        "cross_values": cross_values,
        "cross_values_compute_consumer": cross_values_compute_consumer,
        "cross_values_compute_network": cross_values_compute_network,
        "external_read_values": external_read_values,
        "external_read_values_compute_consumer": external_read_values_compute_consumer,
        "dag_edges": board.dag_edges,
        "compute_compute_value_pairs": board.compute_compute_value_pairs,
        "incoming_copy_cost": board.cost,
        "measure_seconds": round(time.time() - started, 1),
    }


def print_side(name: str, metrics: dict) -> None:
    print(f"[{name}] graph={metrics['graph']}")
    print(f"[{name}] assignment={metrics['assignment']}")
    for key in (
        "instructions",
        "variables",
        "def_use_edges",
        "def_use_value_edges",
        "external_reads",
        "blocks",
        "compute_blocks",
        "commit_blocks",
        "supernodes",
        "node_unit",
        "nodes",
        "block_node_max",
        "block_node_mean",
        "cross_values",
        "cross_values_compute_consumer",
        "cross_values_compute_network",
        "external_read_values",
        "external_read_values_compute_consumer",
        "dag_edges",
        "compute_compute_value_pairs",
        "incoming_copy_cost",
        "measure_seconds",
    ):
        print(f"[{name}] {key}={metrics[key]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_data = Path(__file__).resolve().parents[1] / "topo-partition-proj" / "exp" / "dataset"
    parser.add_argument("--gsim-graph", type=Path,
                        default=default_data / "xs_gsim_flat_prod_20260804" / "instruction_graph.jsonl",
                        help="gsim instruction_graph.jsonl (default: flattened-prod baseline, NO0010)")
    parser.add_argument("--gsim-assign", type=Path,
                        default=default_data / "xs_gsim_flat_prod_20260804" / "block_assignment_dp.jsonl",
                        help="gsim block_assignment_dp.jsonl (default: flattened-prod baseline)")
    parser.add_argument("--am-graph", type=Path,
                        default=default_data / "xs_am_no0007p3_20260808" / "instruction_graph.jsonl",
                        help="AM instruction_graph.jsonl (default: NO0007 P3 = atom-weighted partition, post-merge atom ids)")
    parser.add_argument("--am-assign", type=Path,
                        default=default_data / "xs_am_no0007p3_20260808" / "block_assignment.jsonl",
                        help="AM block_assignment.jsonl (default: NO0007 P3, assign records carry post-merge atom ids)")
    parser.add_argument("--json", type=Path, help="write the full report as JSON")
    args = parser.parse_args()

    have_gsim = args.gsim_graph is not None or args.gsim_assign is not None
    have_am = args.am_graph is not None or args.am_assign is not None
    if have_gsim and (args.gsim_graph is None or args.gsim_assign is None):
        parser.error("--gsim-graph and --gsim-assign must be given together")
    if have_am and (args.am_graph is None or args.am_assign is None):
        parser.error("--am-graph and --am-assign must be given together")
    if not have_gsim and not have_am:
        parser.error("nothing to measure: give --gsim-* and/or --am-*")

    report: dict[str, dict] = {}
    if have_gsim:
        report["gsim"] = measure_side(args.gsim_graph, args.gsim_assign)
        print_side("gsim", report["gsim"])
    if have_am:
        report["am"] = measure_side(args.am_graph, args.am_assign)
        print_side("am", report["am"])

    ok = True
    if have_gsim and have_am:
        gsim = report["gsim"]
        am = report["am"]
        ratio = am["cross_values"] / gsim["cross_values"] if gsim["cross_values"] else 0.0
        ratio_compute = (
            am["cross_values_compute_consumer"] / gsim["cross_values_compute_consumer"]
            if gsim["cross_values_compute_consumer"]
            else 0.0
        )
        ratio_network = (
            am["cross_values_compute_network"] / gsim["cross_values_compute_network"]
            if gsim["cross_values_compute_network"]
            else 0.0
        )
        blocks_ok = am["supernodes"] <= gsim["supernodes"]
        ratio_ok = ratio <= RATIO_TARGET
        network_ok = ratio_network <= RATIO_TARGET
        # Block-count match gate (2026-08-08 ruling): cross metrics are only
        # comparable at matched supernode counts (+-10%).
        block_ratio = am["supernodes"] / gsim["supernodes"] if gsim["supernodes"] else 0.0
        block_matched = 0.9 <= block_ratio <= 1.1
        ok = blocks_ok and network_ok and block_matched
        nodes_ratio = am["nodes"] / gsim["nodes"] if gsim["nodes"] else 0.0
        print(
            f"[compare] nodes am={am['nodes']} ({am['node_unit']}) "
            f"gsim={gsim['nodes']} ({gsim['node_unit']}) ratio={nodes_ratio:.4f}"
        )
        print(
            f"[compare] block_node_size am max={am['block_node_max']} mean={am['block_node_mean']} | "
            f"gsim max={gsim['block_node_max']} mean={gsim['block_node_mean']}"
        )
        print(
            f"[compare] supernodes am={am['supernodes']} gsim={gsim['supernodes']} "
            f"(am <= gsim: {blocks_ok})"
        )
        print(
            f"[compare] block_count_ratio={block_ratio:.4f} "
            f"block_count_matched(+-10%)={block_matched}"
        )
        print(
            f"[compare] cross_values am={am['cross_values']} gsim={gsim['cross_values']} "
            f"ratio={ratio:.4f} (legacy all-consumer metric, target <= {RATIO_TARGET}: {ratio_ok})"
        )
        print(f"[compare] cross_values_compute_consumer ratio={ratio_compute:.4f}")
        print(
            f"[compare] cross_values_compute_network am={am['cross_values_compute_network']} "
            f"gsim={gsim['cross_values_compute_network']} "
            f"ratio={ratio_network:.4f} (PRIMARY, target <= {RATIO_TARGET}: {network_ok})"
        )
        report["compare"] = {
            "supernode_blocks_ok": blocks_ok,
            "block_count_ratio": block_ratio,
            "block_count_matched": block_matched,
            "nodes_ratio": nodes_ratio,
            "cross_values_ratio": ratio,
            "cross_values_compute_consumer_ratio": ratio_compute,
            "cross_values_compute_network_ratio": ratio_network,
            "ratio_target": RATIO_TARGET,
            "aligned": ok,
        }
        print(f"[compare] aligned(compute-network, block-matched)={ok}")

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"[report] wrote {args.json}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
