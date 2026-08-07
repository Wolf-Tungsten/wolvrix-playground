#!/usr/bin/env python3

"""Quantitative comparison: split GRHSIM AM compute graph vs flattened gsim graph.

Metrics sections:

- A. Graph-level scale, both graphs side by side. The gsim side additionally
  reports state_write node count and a "compute-equivalent" subgraph
  (state_write nodes and their incident edges removed).
- B. Producer out-degree distribution over def_use edges deduped by
  (src, dst); buckets 0/1/2/3/4-7/8-15/16-63/>=64 (gsim side: state_write
  nodes removed).
- C. Production-assignment scoreboard, NO0012 口径
  (pdocs/grh-notepad/supernode-align/NO0012): cross_values over def_use
  values crossing blocks with at least one non-state-write consumer,
  (value, consumer block) pairs, incoming_copy_cost
  (sum of max(1, ceil(W/64))), block-level deduped dag_edges. AM side runs
  on the split compute graph + production AM assignment (kind=compute
  blocks; the input-sink block carries no instructions). gsim side runs on
  the flattened graph + block_assignment_dp.jsonl and reconciles against
  the NO0012 baseline cross_values_compute_network = 178,151.
- D. Equal-block-count comparison: both graphs re-partitioned with the
  offline amcoarsen replica (topo-partition-proj/exp/harness/amcoarsen.py,
  Out1/In1/Sibling + greedy capacity packing) at capacities chosen to land
  near the other side's production block count.
- E. Commit-graph context report: state-write instruction count, distinct
  event_rank count, compute->commit value flow (unique values among
  external_read edges with src_side="compute"), and width-derived copy
  cost. Compares against the NO0012 commit-consumer context (185,548).

The split graphs use format ``wolvrix.am-split-graph.v1`` with *global*
instruction ids (not dense), so they get a dedicated loader here; parsed
arrays are cached as ``<name>.cache.npz`` next to the JSONL (build/ tree).
The gsim graph uses the harness loader (format
``wolvrix.am-instruction-graph.v1``) and its prebuilt dataset cache — this
script never writes into topo-partition-proj/exp/dataset/.

Run with the repo venv: .venv/bin/python.

Usage:
    compute_partition_metrics.py [--d-am CAP [CAP ...]] [--d-gsim CAP ...] \
        [--d-gsim-fine CAP ...] [--coarsen-mode rotate] \
        [--json build/xs/am-split-export/metrics.json]

``--d-gsim-fine`` targets the gsim production block count (88,375) and adds
oversized-singleton fan-in stats; ``--d-only`` skips A/B/C/E and reuses the
stored report (fast single-tier reruns).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from array import array
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "topo-partition-proj" / "exp"))

from harness import amcoarsen  # noqa: E402
from harness.graph import InstructionGraph, load_graph  # noqa: E402
from harness.scorer import load_assignment, score_assignment  # noqa: E402

SPLIT_FORMAT = "wolvrix.am-split-graph.v1"
NO0012_GSIM_BASELINE = 178_151
NO0012_AM_COMMIT_CONTEXT = 185_548

REPO = Path(__file__).resolve().parents[1]
DEFAULT_AM_COMPUTE = REPO / "build" / "xs" / "am-split-export" / "split.compute.jsonl"
DEFAULT_AM_COMMIT = REPO / "build" / "xs" / "am-split-export" / "split.commit.jsonl"
DEFAULT_AM_ASSIGN = REPO / "build" / "xs" / "am-graph-export" / "block_assignment.jsonl"
GSIM_DATASET = REPO / "topo-partition-proj" / "exp" / "dataset" / "xs_gsim_flat_prod_20260804"
DEFAULT_GSIM_GRAPH = GSIM_DATASET / "instruction_graph.jsonl"
DEFAULT_GSIM_ASSIGN = GSIM_DATASET / "block_assignment_dp.jsonl"
DEFAULT_JSON = REPO / "build" / "xs" / "am-split-export" / "metrics.json"
DEFAULT_ATTRIBUTE_JSON = REPO / "build" / "xs" / "am-split-export" / "metrics_cap46.json"

# NO0012 §4 reference bucket decomposition (scripts/supernode_align_gap_attr.py
# 口径: per-value def_use edge count, buckets 1 / 2 / >=3).
NO0012_GSIM_DP_BUCKETS = {"1": 25_322, "2": 57_712, ">=3": 95_117}  # total 178,151
NO0012_AM_OPT1_CAP128_BUCKETS = {"1": 110_454, "2": 227_584, ">=3": 180_770}  # total 518,808


# ---------------------------------------------------------------------------
# split-graph loader (wolvrix.am-split-graph.v1, global instruction ids)
# ---------------------------------------------------------------------------


def load_split_graph(path: Path, use_cache: bool = True, verbose: bool = True) -> dict:
    """Parse a split-graph JSONL into dense-local numpy arrays (with npz cache).

    Node ids in the file are global instruction ids shared with the AM block
    assignment; they are remapped to dense local ids 0..N-1 here. The
    ``global_id`` array keeps local -> global for assignment lookups.
    """
    path = Path(path)
    cache_path = path.with_name(path.stem + ".cache.npz")
    if use_cache and cache_path.exists() and cache_path.stat().st_mtime >= path.stat().st_mtime:
        if verbose:
            print(f"[split] loading cache {cache_path}")
        with np.load(cache_path, allow_pickle=False) as data:
            return {
                "meta": json.loads(str(data["meta"][0])),
                "global_id": data["global_id"],
                "op": data["op"],
                "opcode_names": json.loads(str(data["opcode_names"][0])),
                "width": data["width"],
                "state_write": data["state_write"],
                "comb_loop_atom": data["comb_loop_atom"],
                "event_rank": data["event_rank"],
                "names": json.loads(str(data["names"][0])) if "names" in data else None,
                "du_src": data["du_src"],
                "du_dst": data["du_dst"],
                "du_var": data["du_var"],
                "du_width": data["du_width"],
                "er_dst": data["er_dst"],
                "er_var": data["er_var"],
                "er_width": data["er_width"],
                "er_src_compute": data["er_src_compute"],
                "ord_src": data["ord_src"],
                "ord_dst": data["ord_dst"],
            }

    started = time.time()
    header = None
    gid = array("I")
    op = array("B")
    width = array("i")
    state_write = array("b")
    comb_loop = array("b")
    event_rank = array("i")
    opcode_of: dict[str, int] = {}
    opcode_names: list[str] = []
    du_src, du_dst, du_var, du_width = array("I"), array("I"), array("I"), array("i")
    er_dst, er_var, er_width = array("I"), array("I"), array("i")
    er_src_compute = array("b")
    ord_src, ord_dst = array("I"), array("I")
    names: list[str] = []
    have_names = False
    unescape = None
    with open(path) as stream:
        for line in stream:
            if unescape is None:
                # the split exporter emits lines with literally escaped quotes
                # (\"); verified to be the only escape sequence in the export
                unescape = line.startswith('{\\"')
            if unescape:
                line = line.replace('\\"', '"')
            record = json.loads(line)
            kind = record["record"]
            if kind == "header":
                if record["format"] != SPLIT_FORMAT:
                    raise ValueError(f"unsupported graph format: {record['format']}")
                header = record
            elif kind == "node":
                name = record["opcode"]
                op_value = record["op"]
                if name not in opcode_of:
                    while len(opcode_names) <= op_value:
                        opcode_names.append("")
                    opcode_names[op_value] = name
                    opcode_of[name] = op_value
                gid.append(record["id"])
                op.append(op_value)
                width.append(record["width"])
                state_write.append(1 if record["state_write"] else 0)
                comb_loop.append(1 if record["comb_loop_atom"] else 0)
                event_rank.append(record.get("event_rank", -1))
                node_name = record.get("name", "")
                if node_name:
                    have_names = True
                names.append(node_name)
            elif kind == "edge":
                edge_kind = record["kind"]
                if edge_kind == "def_use":
                    du_src.append(record["src"])
                    du_dst.append(record["dst"])
                    du_var.append(record["var"])
                    du_width.append(record["width"])
                elif edge_kind == "external_read":
                    er_dst.append(record["dst"])
                    er_var.append(record["var"])
                    er_width.append(record["width"])
                    er_src_compute.append(1 if record.get("src_side") == "compute" else 0)
                else:
                    ord_src.append(record["src"])
                    ord_dst.append(record["dst"])
    if header is None:
        raise ValueError(f"{path} has no header record")

    global_id = np.frombuffer(gid, dtype=np.uint32).copy()
    n_nodes = global_id.size
    gmap = np.full(int(global_id.max()) + 1, -1, dtype=np.int64)
    gmap[global_id.astype(np.int64)] = np.arange(n_nodes, dtype=np.int64)

    def remap(values: np.ndarray, what: str) -> np.ndarray:
        local = gmap[values.astype(np.int64)]
        if (local < 0).any():
            raise ValueError(f"{path}: {what} references ids outside this side's node set")
        return local.astype(np.uint32)

    graph = {
        "meta": header,
        "global_id": global_id,
        "op": np.frombuffer(op, dtype=np.uint8).copy(),
        "opcode_names": opcode_names,
        "width": np.frombuffer(width, dtype=np.int32).copy(),
        "state_write": np.frombuffer(state_write, dtype=np.int8).astype(bool),
        "comb_loop_atom": np.frombuffer(comb_loop, dtype=np.int8).astype(bool),
        "event_rank": np.frombuffer(event_rank, dtype=np.int32).copy(),
        "names": names if have_names else None,
        "du_src": remap(np.frombuffer(du_src, dtype=np.uint32).copy(), "def_use src"),
        "du_dst": remap(np.frombuffer(du_dst, dtype=np.uint32).copy(), "def_use dst"),
        "du_var": np.frombuffer(du_var, dtype=np.uint32).copy(),
        "du_width": np.frombuffer(du_width, dtype=np.int32).copy(),
        "er_dst": remap(np.frombuffer(er_dst, dtype=np.uint32).copy(), "external_read dst"),
        "er_var": np.frombuffer(er_var, dtype=np.uint32).copy(),
        "er_width": np.frombuffer(er_width, dtype=np.int32).copy(),
        "er_src_compute": np.frombuffer(er_src_compute, dtype=np.int8).astype(bool),
        "ord_src": remap(np.frombuffer(ord_src, dtype=np.uint32).copy(), "order src"),
        "ord_dst": remap(np.frombuffer(ord_dst, dtype=np.uint32).copy(), "order dst"),
    }
    counts = {
        "instructions": n_nodes,
        "def_use_edges": graph["du_src"].size,
        "external_reads": graph["er_dst"].size,
        "order_edges": graph["ord_src"].size,
    }
    for key, actual in counts.items():
        if header[key] != actual:
            raise ValueError(f"{path}: header {key}={header[key]} != parsed {actual}")
    if verbose:
        print(f"[split] parsed {path.name} in {time.time() - started:.1f}s")
    if use_cache:
        np.savez(
            cache_path,
            meta=np.array([json.dumps(header)]),
            global_id=graph["global_id"],
            op=graph["op"],
            opcode_names=np.array([json.dumps(opcode_names)]),
            width=graph["width"],
            state_write=graph["state_write"],
            comb_loop_atom=graph["comb_loop_atom"],
            event_rank=graph["event_rank"],
            **({"names": np.array([json.dumps(graph["names"], ensure_ascii=False)])}
               if graph["names"] is not None else {}),
            du_src=graph["du_src"],
            du_dst=graph["du_dst"],
            du_var=graph["du_var"],
            du_width=graph["du_width"],
            er_dst=graph["er_dst"],
            er_var=graph["er_var"],
            er_width=graph["er_width"],
            er_src_compute=graph["er_src_compute"],
            ord_src=graph["ord_src"],
            ord_dst=graph["ord_dst"],
        )
        if verbose:
            print(f"[split] cache written to {cache_path}")
    return graph


def split_to_instruction_graph(split: dict) -> InstructionGraph:
    """Adapt a parsed split graph to the harness InstructionGraph shape."""
    n_nodes = int(split["global_id"].size)
    return InstructionGraph(
        instructions=n_nodes,
        variables=int(split["meta"]["variables"]),
        op=split["op"],
        opcode_names=split["opcode_names"],
        width=split["width"],
        state_write=split["state_write"],
        atom=np.arange(n_nodes, dtype=np.uint32),  # comb_loop_atoms=0: ids unused
        comb_loop_atom=split["comb_loop_atom"],
        du_src=split["du_src"],
        du_dst=split["du_dst"],
        du_var=split["du_var"],
        du_width=split["du_width"],
        er_dst=split["er_dst"],
        er_var=split["er_var"],
        er_width=split["er_width"],
        ord_src=split["ord_src"],
        ord_dst=split["ord_dst"],
        topo_order=np.empty(0, dtype=np.uint32),
        topo_pos=np.empty(0, dtype=np.uint32),
    )


# ---------------------------------------------------------------------------
# metric kernels
# ---------------------------------------------------------------------------


def scale_section(
    n_nodes: int,
    du_src: np.ndarray,
    er_dst: np.ndarray,
    ord_src: np.ndarray,
    width: np.ndarray,
    du_width: np.ndarray,
    comb_loop_atom: np.ndarray,
) -> dict:
    return {
        "nodes": int(n_nodes),
        "def_use_edges": int(du_src.size),
        "external_reads": int(er_dst.size),
        "order_edges": int(ord_src.size),
        "sum_node_width": int(width.astype(np.int64).sum()),
        "sum_def_use_edge_width": int(du_width.astype(np.int64).sum()),
        "comb_loop_atoms": int(comb_loop_atom.sum()),
    }


def outdegree_buckets(
    du_src: np.ndarray,
    du_dst: np.ndarray,
    n_nodes: int,
    keep_node: np.ndarray,
) -> dict:
    """def_use producer out-degree after (src, dst) dedup, over kept nodes."""
    key = (du_src.astype(np.int64) << 32) | du_dst.astype(np.int64)
    uniq = np.unique(key)
    usrc = (uniq >> 32).astype(np.int64)
    outdeg = np.bincount(usrc, minlength=n_nodes)
    sel = outdeg[keep_node]
    buckets = {
        "0": int((sel == 0).sum()),
        "1": int((sel == 1).sum()),
        "2": int((sel == 2).sum()),
        "3": int((sel == 3).sum()),
        "4-7": int(((sel >= 4) & (sel <= 7)).sum()),
        "8-15": int(((sel >= 8) & (sel <= 15)).sum()),
        "16-63": int(((sel >= 16) & (sel <= 63)).sum()),
        ">=64": int((sel >= 64).sum()),
    }
    return {
        "nodes": int(sel.size),
        "buckets": buckets,
        "outdeg_ge2_nodes": int((sel >= 2).sum()),
        "max_outdeg": int(sel.max()) if sel.size else 0,
    }


def network_scores(
    du_src: np.ndarray,
    du_dst: np.ndarray,
    du_var: np.ndarray,
    du_width: np.ndarray,
    er_dst: np.ndarray,
    er_var: np.ndarray,
    er_width: np.ndarray,
    instr_block: np.ndarray,
    consumer_ok: np.ndarray,
) -> dict:
    """NO0012 compute-network scoreboard for an arbitrary block assignment.

    ``consumer_ok`` is a per-instruction mask; consumers failing it
    (state-write instructions on the gsim side) are dropped from
    cross_values / pairs / cost / dag_edges alike.
    """
    instr_block = instr_block.astype(np.int64)
    pb = instr_block[du_src.astype(np.int64)]
    cb = instr_block[du_dst.astype(np.int64)]
    cross = pb != cb
    du_keep = cross & consumer_ok[du_dst.astype(np.int64)]
    cross_values = int(np.unique(du_var[du_keep]).size)
    dag_edges = int(np.unique((pb[du_keep] << 32) | cb[du_keep]).size)
    du_keys = (du_var[du_keep].astype(np.int64) << 32) | cb[du_keep]
    pairs_du_only = int(np.unique(du_keys).size)
    er_keep = consumer_ok[er_dst.astype(np.int64)]
    er_block = instr_block[er_dst[er_keep].astype(np.int64)]
    er_keys = (er_var[er_keep].astype(np.int64) << 32) | er_block
    keys = np.concatenate([du_keys, er_keys])
    widths = np.concatenate([du_width[du_keep], er_width[er_keep]])
    uniq, first = np.unique(keys, return_index=True)
    copies = np.maximum(1, (widths[first] + 63) // 64)
    return {
        "cross_values": cross_values,
        "value_block_pairs": int(uniq.size),
        "value_block_pairs_du_only": pairs_du_only,
        "incoming_copy_cost": int(copies.sum()),
        "dag_edges": dag_edges,
    }


def repartition(
    du_src: np.ndarray,
    du_dst: np.ndarray,
    ord_src: np.ndarray,
    ord_dst: np.ndarray,
    n_nodes: int,
    capacity: int,
    mode: str,
) -> tuple[np.ndarray, dict]:
    """Run the amcoarsen replica (merge passes + greedy capacity packing)."""
    esrc = np.concatenate([du_src, ord_src]).astype(np.int64)
    edst = np.concatenate([du_dst, ord_dst]).astype(np.int64)
    active = np.ones(n_nodes, dtype=bool)
    weights = np.ones(n_nodes, dtype=np.int64)
    started = time.time()
    result = amcoarsen.coarsen(esrc, edst, n_nodes, active, budget=capacity, mode=mode)
    block_of = amcoarsen.cluster_blocks(
        result.parent, esrc, edst, active, weights, capacity
    )
    info = {
        "capacity": int(capacity),
        "mode": mode,
        "blocks": int(block_of.max()) + 1,
        "coarsen_rounds": int(result.rounds),
        "merges": {k: int(v) for k, v in result.merges.items() if v},
        "seconds": round(time.time() - started, 1),
    }
    return block_of, info


def oversized_stats(
    block_of: np.ndarray,
    capacity: int,
    du_src: np.ndarray,
    du_dst: np.ndarray,
    du_var: np.ndarray,
    du_width: np.ndarray,
    er_dst: np.ndarray,
    er_var: np.ndarray,
    er_width: np.ndarray,
    consumer_ok: np.ndarray,
) -> dict:
    """Oversized-singleton blocks (cluster weight > capacity, forced into their
    own block by the greedy packer) and their fan-in: unique incoming
    (value, block) pairs / copy cost under the NO0012 consumer filter.

    With coarsen budget == packing capacity no cluster can exceed the cap
    (try_merge rejects it), so the oversized count is expected to be 0; it is
    measured here rather than assumed.
    """
    blocks = int(block_of.max()) + 1
    sizes = np.bincount(block_of, minlength=blocks)
    oversized = sizes > capacity
    n_oversized = int(oversized.sum())
    stats = {
        "oversized_singleton_blocks": n_oversized,
        "oversized_block_instructions": int(sizes[oversized].sum()),
        "full_blocks_at_capacity": int((sizes == capacity).sum()),
        "mean_block_size": round(float(sizes.mean()), 2),
    }
    if n_oversized == 0:
        stats["oversized_incoming_value_block_pairs"] = 0
        stats["oversized_incoming_unique_values"] = 0
        stats["oversized_incoming_copy_cost"] = 0
        return stats
    pb = block_of[du_src.astype(np.int64)]
    cb = block_of[du_dst.astype(np.int64)]
    du_keep = (pb != cb) & consumer_ok[du_dst.astype(np.int64)] & oversized[cb]
    erb = block_of[er_dst.astype(np.int64)]
    er_keep = consumer_ok[er_dst.astype(np.int64)] & oversized[erb]
    keys = np.concatenate(
        [
            (du_var[du_keep].astype(np.int64) << 32) | cb[du_keep],
            (er_var[er_keep].astype(np.int64) << 32) | erb[er_keep],
        ]
    )
    widths = np.concatenate([du_width[du_keep], er_width[er_keep]])
    uniq, first = np.unique(keys, return_index=True)
    copies = np.maximum(1, (widths[first] + 63) // 64)
    stats["oversized_incoming_value_block_pairs"] = int(uniq.size)
    stats["oversized_incoming_unique_values"] = int(
        np.unique(np.concatenate([du_var[du_keep], er_var[er_keep]])).size
    )
    stats["oversized_incoming_copy_cost"] = int(copies.sum())
    return stats


def d_run_am(am: dict, n_am: int, cap: int, mode: str, target_blocks: int) -> dict:
    """One D-tier run: AM compute graph repartitioned at ``cap``."""
    block_of, info = repartition(
        am["du_src"], am["du_dst"], am["ord_src"], am["ord_dst"], n_am, cap, mode
    )
    scores = network_scores(
        am["du_src"], am["du_dst"], am["du_var"], am["du_width"],
        am["er_dst"], am["er_var"], am["er_width"],
        block_of, np.ones(n_am, dtype=bool),
    )
    info["target_blocks"] = int(target_blocks)
    info.update(scores)
    return info


def d_run_gsim(
    gsim: InstructionGraph,
    gsim_compute: np.ndarray,
    cap: int,
    mode: str,
    target_blocks: int,
    with_oversized: bool = False,
) -> dict:
    """One D-tier run: gsim flat graph repartitioned at ``cap`` (NO0012 口径)."""
    block_of, info = repartition(
        gsim.du_src, gsim.du_dst, gsim.ord_src, gsim.ord_dst,
        gsim.instructions, cap, mode,
    )
    scores = network_scores(
        gsim.du_src, gsim.du_dst, gsim.du_var, gsim.du_width,
        gsim.er_dst, gsim.er_var, gsim.er_width,
        block_of, gsim_compute,
    )
    info["target_blocks"] = int(target_blocks)
    info["cross_values_compute_network"] = scores["cross_values"]
    info.update({k: v for k, v in scores.items() if k != "cross_values"})
    if with_oversized:
        info.update(
            oversized_stats(
                block_of, cap,
                gsim.du_src, gsim.du_dst, gsim.du_var, gsim.du_width,
                gsim.er_dst, gsim.er_var, gsim.er_width,
                gsim_compute,
            )
        )
    return info


def run_d_only(args: argparse.Namespace) -> int:
    """D-tier-only entry point: reuse the stored report, skip A/B/C/E."""
    if not args.json.exists():
        raise SystemExit(f"--d-only needs an existing report at {args.json}")
    report = json.loads(args.json.read_text(encoding="utf-8"))
    csec = report.get("C_production_assignment")
    if csec is None:
        raise SystemExit("--d-only needs C_production_assignment in the existing report")
    am_compute_blocks = int(csec["am"]["compute_blocks"])
    gsim_prod_blocks = int(csec["gsim"]["blocks"])
    section_d = report.get("D_equal_block_count", {})

    gsim = gsim_compute = None
    if args.d_gsim or args.d_gsim_fine:
        gsim = load_graph(args.gsim_graph, use_cache=True, verbose=True)
        gsim_compute = ~gsim.state_write
    if args.d_am:
        am = load_split_graph(args.am_compute_graph)
        n_am = int(am["global_id"].size)
        runs = section_d.get("am_to_gsim_blocks", [])
        for cap in args.d_am:
            info = d_run_am(am, n_am, cap, args.coarsen_mode, gsim_prod_blocks)
            runs.append(info)
            print(f"[D-am] cap={cap} blocks={info['blocks']} "
                  f"cross_values={info['cross_values']} ({info['seconds']}s)")
        section_d["am_to_gsim_blocks"] = runs
    if args.d_gsim:
        runs = section_d.get("gsim_to_am_blocks", [])
        for cap in args.d_gsim:
            info = d_run_gsim(gsim, gsim_compute, cap, args.coarsen_mode, am_compute_blocks)
            runs.append(info)
            print(f"[D-gsim] cap={cap} blocks={info['blocks']} "
                  f"cross_values_compute_network={info['cross_values_compute_network']} "
                  f"({info['seconds']}s)")
        section_d["gsim_to_am_blocks"] = runs
    if args.d_gsim_fine:
        runs = section_d.get("gsim_at_gsim_blocks", [])
        for cap in args.d_gsim_fine:
            info = d_run_gsim(
                gsim, gsim_compute, cap, args.coarsen_mode, gsim_prod_blocks,
                with_oversized=True,
            )
            runs.append(info)
            print(f"[D-gsim-fine] cap={cap} blocks={info['blocks']} "
                  f"cross_values_compute_network={info['cross_values_compute_network']} "
                  f"oversized={info['oversized_singleton_blocks']} ({info['seconds']}s)")
        section_d["gsim_at_gsim_blocks"] = runs
        # fold the best-landing run into the at-gsim-block-count comparison
        best = min(runs, key=lambda r: abs(r["blocks"] - gsim_prod_blocks))
        compare = section_d.get("compare", {})
        at = compare.get("at_gsim_block_count", {})
        at["gsim_same_partitioner_capacity"] = best["capacity"]
        at["gsim_same_partitioner_blocks"] = best["blocks"]
        at["gsim_same_partitioner_cross_values_compute_network"] = best[
            "cross_values_compute_network"
        ]
        if at.get("am_cross_values"):
            at["ratio_gsim_over_am_same_partitioner"] = round(
                best["cross_values_compute_network"] / at["am_cross_values"], 4
            )
        compare["at_gsim_block_count"] = at
        section_d["compare"] = compare
    if not (args.d_am or args.d_gsim or args.d_gsim_fine):
        raise SystemExit("--d-only: nothing to do (give --d-am/--d-gsim/--d-gsim-fine)")
    report["D_equal_block_count"] = section_d
    args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[report] wrote {args.json}")
    return 0


# ---------------------------------------------------------------------------
# cross_values 爆发点分解 (NO0012 §4 attribution, AM compute graph)
# ---------------------------------------------------------------------------


def attribute_assignment(am: dict, assign_path: Path) -> dict:
    """Decompose cross_values of the AM compute graph under ``assign_path``.

    Bucket 口径 mirrors scripts/supernode_align_gap_attr.py (NO0012 §4):
    per-value def_use edge count (raw, not (src,dst)-deduped), buckets
    1 / 2 / >=3. Verified to reproduce the gsim dp reference buckets
    {1: 25,322, 2: 57,712, >=3: 95,117} exactly.
    """
    assign = load_assignment(assign_path)
    header = assign.header
    n = int(am["global_id"].size)
    n_vars = int(am["meta"]["variables"])
    du_src = am["du_src"].astype(np.int64)
    du_dst = am["du_dst"].astype(np.int64)
    du_var = am["du_var"].astype(np.int64)
    du_width = am["du_width"]
    instr_block = assign.instr_block[am["global_id"].astype(np.int64)].astype(np.int64)
    pb = instr_block[du_src]
    cb = instr_block[du_dst]
    cross = pb != cb
    cvar = du_var[cross]
    ccb = cb[cross]
    # value-level dedup; width from the first crossing edge of each value
    cross_values, first = np.unique(cvar, return_index=True)
    value_width = du_width[cross][first].astype(np.int64)
    total = int(cross_values.size)

    # ---- 1. producer out-degree buckets ----------------------------------
    outdeg = np.bincount(du_var, minlength=n_vars)  # per value (SSA: == per producer)
    od = outdeg[cross_values]
    buckets = {
        "1": int((od == 1).sum()),
        "2": int((od == 2).sum()),
        ">=3": int((od >= 3).sum()),
    }
    bucket_ratios = {k: ratio(buckets[k], NO0012_GSIM_DP_BUCKETS[k]) for k in buckets}

    # ---- 2. hub concentration ---------------------------------------------
    var_def = np.full(n_vars, -1, dtype=np.int64)
    var_def[du_var] = du_src
    producer = var_def[cross_values]
    # Literal ask: crossing values per producer. Near-degenerate on this IR —
    # SSA gives essentially one value per instruction (max contribution 2), so
    # the informative hub ranking is by (value, consumer block) pairs instead.
    contrib_vals = np.bincount(producer, minlength=n)
    ranked_vals = np.argsort(-contrib_vals, kind="stable")
    ranked_vals = ranked_vals[contrib_vals[ranked_vals] > 0]
    hubs_values = {}
    for k in (10, 100, 1000):
        s = int(contrib_vals[ranked_vals[:k]].sum())
        hubs_values[f"top{k}"] = {
            "crossing_values": s,
            "share_of_cross_values": round(s / total, 6),
        }
    pair_key = np.unique((cvar << 32) | ccb)  # du-only (value, consumer block) pairs
    pair_var = pair_key >> 32
    pair_block = pair_key & 0xFFFFFFFF
    pair_producer = var_def[pair_var]
    contrib_pairs = np.bincount(pair_producer, minlength=n)
    ranked_pairs = np.argsort(-contrib_pairs, kind="stable")
    ranked_pairs = ranked_pairs[contrib_pairs[ranked_pairs] > 0]
    du_pairs_total = int(pair_key.size)
    hubs_pairs = {}
    for k in (10, 100, 1000):
        s = int(contrib_pairs[ranked_pairs[:k]].sum())
        hubs_pairs[f"top{k}"] = {
            "value_block_pairs": s,
            "share_of_du_only_pairs": round(s / du_pairs_total, 4),
        }
    instr_outdeg = np.bincount(du_src, minlength=n)
    top10 = []
    for p in ranked_pairs[:10]:
        p = int(p)
        consumer_blocks = int(np.unique(pair_block[pair_producer == p]).size)
        top10.append(
            {
                "instr": int(am["global_id"][p]),
                "opcode": am["opcode_names"][am["op"][p]],
                "width": int(am["width"][p]),
                "def_use_outdeg": int(instr_outdeg[p]),
                "crossing_values": int(contrib_vals[p]),
                "consumer_blocks": consumer_blocks,
                "value_block_pairs": int(contrib_pairs[p]),
                "block": int(instr_block[p]),
            }
        )

    # ---- 3. wide values (>=65 bits) ----------------------------------------
    wide = value_width >= 65
    wide_values = cross_values[wide]
    wide_value_copies = int(((value_width[wide] + 63) // 64).sum())
    width_of = np.zeros(n_vars, dtype=np.int64)
    width_of[cross_values] = value_width
    pair_copies = np.maximum(1, (width_of[pair_var] + 63) // 64)
    is_wide = np.zeros(n_vars, dtype=bool)
    is_wide[wide_values] = True
    wide_pair_sel = is_wide[pair_var]
    du_pair_copies_total = int(pair_copies.sum())

    # ---- 4. crossing multiplicity (distinct consumer blocks per value) -----
    mult = np.bincount(pair_var, minlength=n_vars)[cross_values]
    mult_buckets = {
        "1": int((mult == 1).sum()),
        "2": int((mult == 2).sum()),
        "3": int((mult == 3).sum()),
        "4-7": int(((mult >= 4) & (mult <= 7)).sum()),
        "8-15": int(((mult >= 8) & (mult <= 15)).sum()),
        ">=16": int((mult >= 16).sum()),
    }

    # ---- production scoreboard reconcile -----------------------------------
    network = network_scores(
        am["du_src"], am["du_dst"], am["du_var"], am["du_width"],
        am["er_dst"], am["er_var"], am["er_width"],
        instr_block, np.ones(n, dtype=bool),
    )
    return {
        "graph": "build/xs/am-split-export/split.compute.jsonl",
        "assignment": str(assign_path),
        "compute_blocks": int(assign.compute_blocks),
        "commit_blocks": int(assign.commit_blocks),
        "cross_values": total,
        "outdegree_buckets": buckets,
        "outdegree_bucket_shares": {k: round(v / total, 4) for k, v in buckets.items()},
        "outdegree_bucket_ratio_vs_gsim_dp": bucket_ratios,
        "reference_no0012": {
            "gsim_dp_88k": NO0012_GSIM_DP_BUCKETS,
            "am_opt1_cap128_26907_blocks": NO0012_AM_OPT1_CAP128_BUCKETS,
        },
        "hub_concentration_by_crossing_values": hubs_values,
        "hub_concentration_by_value_block_pairs": hubs_pairs,
        "hub_note": (
            "per-producer crossing-value contribution is near-degenerate on this IR "
            "(SSA: essentially one defined value per instruction, max 2), so the "
            "informative hub ranking is by du-only (value, consumer block) pairs; "
            "hub_top10 is ranked by pairs."
        ),
        "hub_top10": top10,
        "producers_with_crossing_values": int(ranked_vals.size),
        "wide_values_ge65": {
            "values": int(wide.sum()),
            "share_of_cross_values": round(float(wide.mean()), 4),
            "per_value_copy_units": wide_value_copies,
            "du_pair_copy_cost": int(pair_copies[wide_pair_sel].sum()),
            "share_of_du_pair_copy_cost": round(
                int(pair_copies[wide_pair_sel].sum()) / du_pair_copies_total, 4
            ),
        },
        "du_pair_copy_cost_total": du_pair_copies_total,
        "crossing_multiplicity": {
            "du_only_value_block_pairs": int(pair_key.size),
            "avg_consumer_blocks_per_value": round(float(pair_key.size) / total, 2),
            "buckets": mult_buckets,
            "max_consumer_blocks": int(mult.max()),
        },
        "production_scoreboard_check": {
            "value_block_pairs_du_plus_er": network["value_block_pairs"],
            "incoming_copy_cost": network["incoming_copy_cost"],
            "dag_edges": network["dag_edges"],
            "header_pairs": int(header["compute_compute_value_pairs"]),
            "header_incoming_copy_cost": int(header["incoming_copy_cost"]),
            "header_dag_edges": int(header["dag_edges"]),
        },
    }


def run_attribute(args: argparse.Namespace) -> int:
    am = load_split_graph(args.am_compute_graph)
    section = attribute_assignment(am, args.attribute)
    report: dict = {}
    if args.attribute_json.exists():
        report = json.loads(args.attribute_json.read_text(encoding="utf-8"))
    report["cap46_cross_values_attribution"] = section
    args.attribute_json.parent.mkdir(parents=True, exist_ok=True)
    args.attribute_json.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    s = section
    print(f"[attribute] assignment={s['assignment']}")
    print(f"[attribute] compute_blocks={s['compute_blocks']} cross_values={s['cross_values']}")
    print(f"[attribute] 出度桶: {s['outdegree_buckets']} "
          f"shares={s['outdegree_bucket_shares']}")
    print(f"[attribute] 桶倍数 vs gsim dp: {s['outdegree_bucket_ratio_vs_gsim_dp']}")
    print(f"[attribute] hub 集中度(按跨块 value 数, 退化口径): "
          f"{json.dumps(s['hub_concentration_by_crossing_values'])}")
    print(f"[attribute] hub 集中度(按 (value,块) 对): "
          f"{json.dumps(s['hub_concentration_by_value_block_pairs'])}")
    for h in s["hub_top10"]:
        print(f"[attribute] top10 instr={h['instr']} op={h['opcode']} w={h['width']} "
              f"outdeg={h['def_use_outdeg']} crossing_values={h['crossing_values']} "
              f"consumer_blocks={h['consumer_blocks']} pairs={h['value_block_pairs']} "
              f"block={h['block']}")
    print(f"[attribute] 宽值(>=65b): {json.dumps(s['wide_values_ge65'])}")
    print(f"[attribute] 跨块次数分布: {json.dumps(s['crossing_multiplicity'])}")
    print(f"[attribute] 生产对账: {json.dumps(s['production_scoreboard_check'])}")
    print(f"[report] wrote {args.attribute_json}")
    return 0


# ---------------------------------------------------------------------------
# gsim production-partitioner replica (harness/gsimpart.py) runs
# ---------------------------------------------------------------------------


def replica_run(gsimpart, du, er, n_nodes, cap, consumer_ok, label: str) -> dict:
    """One replica run: gsim-partitioner coarsen + DP at SuperNodeMaxSize=cap."""
    result = gsimpart.partition(
        du["src"], du["dst"], du["ord_src"], du["ord_dst"], n_nodes, cap, verbose=True
    )
    scores = network_scores(
        du["src"], du["dst"], du["var"], du["width"],
        er["dst"], er["var"], er["width"],
        result.block_of_node, consumer_ok,
    )
    info = {
        "supernode_max_size": int(cap),
        "blocks": int(result.blocks),
        "clusters_after_out1": int(result.clusters_after_out1),
        "clusters_after_in1": int(result.clusters_after_in1),
        "clusters_after_sublings": int(result.clusters_after_sublings),
        "merges": result.merges,
        "oversized_blocks": int(result.oversized_blocks),
        "oversized_block_instructions": int(result.oversized_block_instructions),
        "seconds": float(result.seconds),
        f"cross_values{label}": scores["cross_values"],
        "value_block_pairs": scores["value_block_pairs"],
        "incoming_copy_cost": scores["incoming_copy_cost"],
        "dag_edges": scores["dag_edges"],
    }
    return info


def run_replica(args: argparse.Namespace) -> int:
    """Replica-only entry point: gsimpart on the gsim flat graph and/or the AM
    compute graph; appends to section ``gsim_replica`` of --json."""
    from harness import gsimpart

    report: dict = {}
    if args.json.exists():
        report = json.loads(args.json.read_text(encoding="utf-8"))
    section = report.get("gsim_replica", {})

    if args.replica_gsim:
        gsim = load_graph(args.gsim_graph, use_cache=True, verbose=True)
        gsim_compute = ~gsim.state_write
        du = {"src": gsim.du_src, "dst": gsim.du_dst, "var": gsim.du_var,
              "width": gsim.du_width, "ord_src": gsim.ord_src, "ord_dst": gsim.ord_dst}
        er = {"dst": gsim.er_dst, "var": gsim.er_var, "width": gsim.er_width}
        runs = section.get("gsim_side", [])
        for cap in args.replica_gsim:
            info = replica_run(gsimpart, du, er, gsim.instructions, cap,
                               gsim_compute, "_compute_network")
            info["sanity_reference"] = {
                "production_blocks": 88375,
                "production_cross_values_compute_network": NO0012_GSIM_BASELINE,
                "production_coarsen_stage_blocks": 286748,
            }
            runs.append(info)
            print(f"[replica-gsim] cap={cap} blocks={info['blocks']} "
                  f"cross_values_compute_network={info['cross_values_compute_network']} "
                  f"({info['seconds']}s)")
        section["gsim_side"] = runs
    if args.replica_am:
        am = load_split_graph(args.am_compute_graph)
        n_am = int(am["global_id"].size)
        du = {"src": am["du_src"], "dst": am["du_dst"], "var": am["du_var"],
              "width": am["du_width"], "ord_src": am["ord_src"], "ord_dst": am["ord_dst"]}
        er = {"dst": am["er_dst"], "var": am["er_var"], "width": am["er_width"]}
        runs = section.get("am_side", [])
        for cap in args.replica_am:
            info = replica_run(gsimpart, du, er, n_am, cap,
                               np.ones(n_am, dtype=bool), "")
            runs.append(info)
            print(f"[replica-am] cap={cap} blocks={info['blocks']} "
                  f"cross_values={info['cross_values']} ({info['seconds']}s)")
        section["am_side"] = runs
    if not (args.replica_gsim or args.replica_am):
        raise SystemExit("--replica-only: give --replica-gsim and/or --replica-am caps")
    report["gsim_replica"] = section
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[report] wrote {args.json}")
    return 0


GSIM_NODE_TYPE_CACHE = REPO / "build" / "xs" / "am-split-export" / "gsim_node_type.npz"


def run_replication(args: argparse.Namespace) -> int:
    """replicationOpt replica on the gsim dp assignment (section gsim_replication)."""
    from harness import replication

    gsim = load_graph(args.gsim_graph, use_cache=True, verbose=True)
    with np.load(GSIM_NODE_TYPE_CACHE) as data:
        gsim_type = data["gsim_type"]
    if gsim_type.size != gsim.instructions:
        raise SystemExit(f"{GSIM_NODE_TYPE_CACHE}: size mismatch, rebuild the cache")
    assign = load_assignment(args.gsim_assign)
    instr_block = assign.instr_block.astype(np.int64)
    n_blocks = int(assign.blocks)
    gsim_compute = ~gsim.state_write

    pre = network_scores(
        gsim.du_src, gsim.du_dst, gsim.du_var, gsim.du_width,
        gsim.er_dst, gsim.er_var, gsim.er_width,
        instr_block, gsim_compute,
    )
    result = replication.replicate(
        gsim.du_src, gsim.du_dst, gsim.du_var, gsim.du_width,
        gsim.er_dst, gsim.er_var, gsim.er_width,
        gsim.op, gsim.width, gsim.state_write, gsim_type,
        instr_block, n_blocks, gsim.variables, verbose=True,
    )
    post = network_scores(
        result["du_src"], result["du_dst"], result["du_var"], result["du_width"],
        result["er_dst"], result["er_var"], result["er_width"],
        result["instr_block"], ~result["state_write"],
    )
    section = {
        "note": (
            "harness/replication.py replica of reference/gsim/src/replication.cpp "
            "replicationOpt on block_assignment_dp.jsonl. Caliber declarations: "
            "mustNodes approximated as empty (isArray/ExpTree semantics absent from "
            "the flat export); op count = 1 per single-enode node (+ transitive "
            "opNum), CONST/NONE/REF = 0; BASIC_WIDTH=256 per common.h:68; multiple "
            "references to the same predecessor dedup to one."
        ),
        "coverage": result["coverage"],
        "replicated_nodes": result["replicated_nodes"],
        "dup_nodes": result["dup_nodes"],
        "dups_per_replicated": result["dups_per_replicated"],
        "nodes_before": result["nodes_before"],
        "nodes_after": result["nodes_after"],
        "node_expansion": round(result["nodes_after"] / result["nodes_before"], 6),
        "blocks_before": result["blocks_before"],
        "blocks_after": result["blocks_after"],
        "pre": {
            "cross_values_compute_network": pre["cross_values"],
            "value_block_pairs": pre["value_block_pairs"],
            "incoming_copy_cost": pre["incoming_copy_cost"],
            "dag_edges": pre["dag_edges"],
        },
        "post": {
            "cross_values_compute_network": post["cross_values"],
            "value_block_pairs": post["value_block_pairs"],
            "incoming_copy_cost": post["incoming_copy_cost"],
            "dag_edges": post["dag_edges"],
        },
        "delta": {
            "cross_values_compute_network": post["cross_values"] - pre["cross_values"],
            "value_block_pairs": post["value_block_pairs"] - pre["value_block_pairs"],
            "incoming_copy_cost": post["incoming_copy_cost"] - pre["incoming_copy_cost"],
            "dag_edges": post["dag_edges"] - pre["dag_edges"],
        },
    }
    report: dict = {}
    if args.json.exists():
        report = json.loads(args.json.read_text(encoding="utf-8"))
    report["gsim_replication"] = section
    args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[replication] coverage={json.dumps(section['coverage'])}")
    print(f"[replication] replicated={section['replicated_nodes']} dups={section['dup_nodes']} "
          f"nodes {section['nodes_before']} -> {section['nodes_after']} "
          f"blocks {section['blocks_before']} -> {section['blocks_after']}")
    print(f"[replication] pre : {json.dumps(section['pre'])}")
    print(f"[replication] post: {json.dumps(section['post'])}")
    print(f"[replication] delta: {json.dumps(section['delta'])}")
    print(f"[report] wrote {args.json}")
    return 0


# ---------------------------------------------------------------------------
# report assembly
# ---------------------------------------------------------------------------


def ratio(a: int, b: int) -> float:
    return round(a / b, 4) if b else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--am-compute-graph", type=Path, default=DEFAULT_AM_COMPUTE)
    parser.add_argument("--am-commit-graph", type=Path, default=DEFAULT_AM_COMMIT)
    parser.add_argument("--am-assign", type=Path, default=DEFAULT_AM_ASSIGN)
    parser.add_argument("--gsim-graph", type=Path, default=DEFAULT_GSIM_GRAPH)
    parser.add_argument("--gsim-assign", type=Path, default=DEFAULT_GSIM_ASSIGN)
    parser.add_argument("--d-am", type=int, nargs="*", default=None, metavar="CAP",
                        help="repartition the AM compute graph at these capacities "
                             "(target: gsim block count 88,375)")
    parser.add_argument("--d-gsim", type=int, nargs="*", default=None, metavar="CAP",
                        help="repartition the gsim graph at these capacities "
                             "(target: AM compute block count 28,344)")
    parser.add_argument("--d-gsim-fine", type=int, nargs="*", default=None, metavar="CAP",
                        help="repartition the gsim graph at these capacities "
                             "(target: gsim production block count 88,375), with "
                             "oversized-singleton block stats")
    parser.add_argument("--d-only", action="store_true",
                        help="skip A/B/C/E and assignment loads; only run D-tier "
                             "repartition on top of the existing --json report")
    parser.add_argument("--attribute", type=Path, default=None, metavar="ASSIGNMENT",
                        help="cross_values 爆发点分解 (NO0012 §4) for the AM compute "
                             "graph under this block assignment, then exit")
    parser.add_argument("--attribute-json", type=Path, default=DEFAULT_ATTRIBUTE_JSON,
                        help="report path for --attribute (default: metrics_cap46.json)")
    parser.add_argument("--replica-only", action="store_true",
                        help="only run the gsim-partitioner replica tiers "
                             "(--replica-gsim/--replica-am), updating section "
                             "gsim_replica of --json")
    parser.add_argument("--replica-gsim", type=int, nargs="*", default=None, metavar="CAP",
                        help="run harness/gsimpart.py on the gsim flat graph at these "
                             "SuperNodeMaxSize values (NO0012 compute-network scoring)")
    parser.add_argument("--replica-am", type=int, nargs="*", default=None, metavar="CAP",
                        help="run harness/gsimpart.py on the AM split compute graph at "
                             "these SuperNodeMaxSize values")
    parser.add_argument("--replicate-gsim", action="store_true",
                        help="run the replicationOpt replica (harness/replication.py) on "
                             "the gsim dp assignment, updating section gsim_replication")
    parser.add_argument("--coarsen-mode", default="rotate",
                        help="amcoarsen scheduler mode (default: rotate, production behaviour)")
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    args = parser.parse_args()

    if args.replicate_gsim:
        return run_replication(args)
    if args.replica_only:
        return run_replica(args)
    if args.attribute is not None:
        return run_attribute(args)
    if args.d_only:
        return run_d_only(args)

    report: dict = {}
    if args.json.exists():
        report = json.loads(args.json.read_text(encoding="utf-8"))

    # ---- load inputs ------------------------------------------------------
    am = load_split_graph(args.am_compute_graph)
    am_graph = split_to_instruction_graph(am)
    am_assign = load_assignment(args.am_assign)
    n_am = int(am["global_id"].size)
    # assignment is indexed by global instruction id; translate to local ids
    am_instr_block = am_assign.instr_block[am["global_id"].astype(np.int64)]

    gsim = load_graph(args.gsim_graph, use_cache=True, verbose=True)
    gsim_assign = load_assignment(args.gsim_assign)
    gsim_compute = ~gsim.state_write

    # ---- A. graph-level scale --------------------------------------------
    section_a = {
        "am_compute": scale_section(
            n_am, am["du_src"], am["er_dst"], am["ord_src"],
            am["width"], am["du_width"], am["comb_loop_atom"],
        ),
        "gsim_flat": scale_section(
            gsim.instructions, gsim.du_src, gsim.er_dst, gsim.ord_src,
            gsim.width, gsim.du_width, gsim.comb_loop_atom,
        ),
    }
    keep_du = gsim_compute[gsim.du_src.astype(np.int64)] & gsim_compute[gsim.du_dst.astype(np.int64)]
    keep_er = gsim_compute[gsim.er_dst.astype(np.int64)]
    keep_ord = gsim_compute[gsim.ord_src.astype(np.int64)] & gsim_compute[gsim.ord_dst.astype(np.int64)]
    section_a["gsim_flat"]["state_write_nodes"] = int(gsim.state_write.sum())
    section_a["gsim_compute_equivalent"] = {
        "nodes": int(gsim_compute.sum()),
        "def_use_edges": int(keep_du.sum()),
        "external_reads": int(keep_er.sum()),
        "order_edges": int(keep_ord.sum()),
        "sum_node_width": int(gsim.width[gsim_compute].astype(np.int64).sum()),
        "sum_def_use_edge_width": int(gsim.du_width[keep_du].astype(np.int64).sum()),
    }
    report["A_graph_scale"] = section_a

    # ---- B. producer out-degree distribution ------------------------------
    report["B_producer_outdegree"] = {
        "am_compute": outdegree_buckets(
            am["du_src"], am["du_dst"], n_am, np.ones(n_am, dtype=bool)
        ),
        "gsim_flat_compute_nodes": outdegree_buckets(
            gsim.du_src[keep_du], gsim.du_dst[keep_du], gsim.instructions, gsim_compute
        ),
    }

    # ---- C. production-assignment scoreboard (NO0012) ---------------------
    am_board = score_assignment(am_graph, am_instr_block, am_assign.commit_mask)
    am_network = network_scores(
        am["du_src"], am["du_dst"], am["du_var"], am["du_width"],
        am["er_dst"], am["er_var"], am["er_width"],
        am_instr_block, np.ones(n_am, dtype=bool),
    )
    am_header = am_assign.header
    section_c_am = {
        "compute_blocks": int(am_assign.compute_blocks),
        "commit_blocks": int(am_assign.commit_blocks),
        "input_sink_block": am_header.get("input_sink_block"),
        **am_network,
        "scoreboard_check": {
            "cost": int(am_board.cost),
            "pairs": int(am_board.compute_compute_value_pairs),
            "dag_edges": int(am_board.dag_edges),
        },
        "assignment_header_full_design": {
            "dag_edges": int(am_header["dag_edges"]),
            "compute_compute_value_pairs": int(am_header["compute_compute_value_pairs"]),
            "incoming_copy_cost": int(am_header["incoming_copy_cost"]),
        },
        "reconciliation": {
            "cost_delta_header_minus_compute_only": int(
                am_header["incoming_copy_cost"] - am_network["incoming_copy_cost"]
            ),
            "pairs_delta_header_minus_compute_only": int(
                am_header["compute_compute_value_pairs"] - am_network["value_block_pairs"]
            ),
            "dag_edges_delta_header_minus_compute_only": int(
                am_header["dag_edges"] - am_network["dag_edges"]
            ),
            "note": (
                "header numbers score the full design (compute+commit); commit-block "
                "consumers are excluded from pairs/cost on both sides, so pairs/cost "
                "should match exactly. dag_edges differs because the header counts "
                "compute->commit block pairs while the split compute graph carries no "
                "commit nodes (those flows are commit-side external_read edges with "
                "src_side=compute)."
            ),
        },
    }

    gsim_board = score_assignment(gsim, gsim_assign.instr_block, gsim_assign.commit_mask)
    gsim_network = network_scores(
        gsim.du_src, gsim.du_dst, gsim.du_var, gsim.du_width,
        gsim.er_dst, gsim.er_var, gsim.er_width,
        gsim_assign.instr_block, gsim_compute,
    )
    gsim_all_consumers = network_scores(
        gsim.du_src, gsim.du_dst, gsim.du_var, gsim.du_width,
        gsim.er_dst, gsim.er_var, gsim.er_width,
        gsim_assign.instr_block, np.ones(gsim.instructions, dtype=bool),
    )
    gsim_header = gsim_assign.header
    section_c_gsim = {
        "blocks": int(gsim_assign.blocks),
        "cross_values_compute_network": gsim_network["cross_values"],
        "value_block_pairs_compute_network": gsim_network["value_block_pairs"],
        "value_block_pairs_du_only_compute_network": gsim_network["value_block_pairs_du_only"],
        "incoming_copy_cost_compute_network": gsim_network["incoming_copy_cost"],
        "dag_edges_compute_network": gsim_network["dag_edges"],
        "cross_values_all_consumers": gsim_all_consumers["cross_values"],
        "scoreboard_raw": {
            "cost": int(gsim_board.cost),
            "pairs": int(gsim_board.compute_compute_value_pairs),
            "dag_edges": int(gsim_board.dag_edges),
        },
        "assignment_header": {
            "dag_edges": int(gsim_header["dag_edges"]),
            "compute_compute_value_pairs": int(gsim_header["compute_compute_value_pairs"]),
            "incoming_copy_cost": int(gsim_header["incoming_copy_cost"]),
        },
        "no0012_baseline_cross_values_compute_network": NO0012_GSIM_BASELINE,
        "matches_no0012_baseline": gsim_network["cross_values"] == NO0012_GSIM_BASELINE,
    }
    report["C_production_assignment"] = {
        "am": section_c_am,
        "gsim": section_c_gsim,
        "ratios_am_over_gsim": {
            "cross_values": ratio(am_network["cross_values"], gsim_network["cross_values"]),
            "value_block_pairs": ratio(
                am_network["value_block_pairs"], gsim_network["value_block_pairs"]
            ),
            "incoming_copy_cost": ratio(
                am_network["incoming_copy_cost"], gsim_network["incoming_copy_cost"]
            ),
            "dag_edges": ratio(am_network["dag_edges"], gsim_network["dag_edges"]),
        },
    }

    # ---- D. equal-block-count repartition ---------------------------------
    section_d = report.get("D_equal_block_count", {})
    if args.d_am:
        runs = section_d.get("am_to_gsim_blocks", [])
        for cap in args.d_am:
            info = d_run_am(am, n_am, cap, args.coarsen_mode, gsim_assign.blocks)
            runs.append(info)
            print(f"[D-am] cap={cap} blocks={info['blocks']} "
                  f"cross_values={info['cross_values']} ({info['seconds']}s)")
        section_d["am_to_gsim_blocks"] = runs
    if args.d_gsim:
        runs = section_d.get("gsim_to_am_blocks", [])
        for cap in args.d_gsim:
            info = d_run_gsim(gsim, gsim_compute, cap, args.coarsen_mode,
                              am_assign.compute_blocks)
            runs.append(info)
            print(f"[D-gsim] cap={cap} blocks={info['blocks']} "
                  f"cross_values_compute_network={info['cross_values_compute_network']} "
                  f"({info['seconds']}s)")
        section_d["gsim_to_am_blocks"] = runs
    if args.d_gsim_fine:
        runs = section_d.get("gsim_at_gsim_blocks", [])
        for cap in args.d_gsim_fine:
            info = d_run_gsim(gsim, gsim_compute, cap, args.coarsen_mode,
                              gsim_assign.blocks, with_oversized=True)
            runs.append(info)
            print(f"[D-gsim-fine] cap={cap} blocks={info['blocks']} "
                  f"cross_values_compute_network={info['cross_values_compute_network']} "
                  f"oversized={info['oversized_singleton_blocks']} ({info['seconds']}s)")
        section_d["gsim_at_gsim_blocks"] = runs
    if section_d:
        report["D_equal_block_count"] = section_d

    # ---- E. commit-graph context ------------------------------------------
    commit = load_split_graph(args.am_commit_graph)
    er_compute_side = commit["er_src_compute"]
    er_var_unique_compute = int(np.unique(commit["er_var"][er_compute_side]).size)
    copies_all = np.maximum(1, (commit["er_width"].astype(np.int64) + 63) // 64)
    copies_compute = np.maximum(1, (commit["er_width"][er_compute_side].astype(np.int64) + 63) // 64)
    report["E_commit_context"] = {
        "write_instructions": int(commit["global_id"].size),
        "distinct_event_ranks": int(np.unique(commit["event_rank"]).size),
        "external_reads": int(commit["er_dst"].size),
        "external_reads_src_compute": int(er_compute_side.sum()),
        "compute_to_commit_unique_values": er_var_unique_compute,
        "no0012_commit_context_baseline": NO0012_AM_COMMIT_CONTEXT,
        "external_read_copy_cost_all": int(copies_all.sum()),
        "external_read_copy_cost_src_compute": int(copies_compute.sum()),
        "order_edges": int(commit["ord_src"].size),
    }

    # ---- emit --------------------------------------------------------------
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    a = report["A_graph_scale"]
    b = report["B_producer_outdegree"]
    c = report["C_production_assignment"]
    e = report["E_commit_context"]
    print("\n===== A. 图级规模 =====")
    print(f"AM compute : {json.dumps(a['am_compute'], ensure_ascii=False)}")
    print(f"gsim flat  : {json.dumps(a['gsim_flat'], ensure_ascii=False)}")
    print(f"gsim compute 等效: {json.dumps(a['gsim_compute_equivalent'], ensure_ascii=False)}")
    print("===== B. 生产者出度分布 (def_use 按 (src,dst) 去重) =====")
    for side, m in b.items():
        print(f"{side}: nodes={m['nodes']} buckets={m['buckets']} "
              f"outdeg>=2 合计={m['outdeg_ge2_nodes']} max={m['max_outdeg']}")
    print("===== C. 生产划分主指标 (NO0012) =====")
    print(f"AM  : cross_values={c['am']['cross_values']} pairs={c['am']['value_block_pairs']} "
          f"cost={c['am']['incoming_copy_cost']} dag_edges={c['am']['dag_edges']}")
    print(f"     header 对账 deltas: {json.dumps({k: v for k, v in c['am']['reconciliation'].items() if k != 'note'})}")
    print(f"gsim: cross_values_compute_network={c['gsim']['cross_values_compute_network']} "
          f"(NO0012 基线 {NO0012_GSIM_BASELINE}, 一致={c['gsim']['matches_no0012_baseline']}) "
          f"pairs={c['gsim']['value_block_pairs_compute_network']} "
          f"cost={c['gsim']['incoming_copy_cost_compute_network']} "
          f"dag_edges={c['gsim']['dag_edges_compute_network']}")
    print(f"AM/gsim 比值: {json.dumps(c['ratios_am_over_gsim'])}")
    if "D_equal_block_count" in report:
        print("===== D. 同等超节点数对比 =====")
        for run in report["D_equal_block_count"].get("am_to_gsim_blocks", []):
            print(f"AM→~88k : cap={run['capacity']} blocks={run['blocks']} "
                  f"cross_values={run['cross_values']} pairs={run['value_block_pairs']} "
                  f"cost={run['incoming_copy_cost']} dag={run['dag_edges']} ({run['seconds']}s)")
        for run in report["D_equal_block_count"].get("gsim_to_am_blocks", []):
            print(f"gsim→~28k: cap={run['capacity']} blocks={run['blocks']} "
                  f"cross_values_compute_network={run['cross_values_compute_network']} "
                  f"pairs={run['value_block_pairs']} cost={run['incoming_copy_cost']} "
                  f"dag={run['dag_edges']} ({run['seconds']}s)")
        for run in report["D_equal_block_count"].get("gsim_at_gsim_blocks", []):
            print(f"gsim→~88k: cap={run['capacity']} blocks={run['blocks']} "
                  f"cross_values_compute_network={run['cross_values_compute_network']} "
                  f"pairs={run['value_block_pairs']} cost={run['incoming_copy_cost']} "
                  f"dag={run['dag_edges']} oversized={run['oversized_singleton_blocks']} "
                  f"({run['seconds']}s)")
    print("===== E. commit 图快报 =====")
    print(json.dumps(e, ensure_ascii=False))
    print(f"\n[report] wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
