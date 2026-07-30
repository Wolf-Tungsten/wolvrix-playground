"""Score an arbitrary block assignment on the exported instruction graph.

Semantics are exactly the reconciled production scoreboard (docs/06,
exp/tools/reconcile_baseline.py):

- ``cost`` (a.k.a. incoming_copy_cost, the Phase-1 optimization target):
  for every (value, consuming compute block) pair where the value is not
  defined in that block, charge ``max(1, ceil(width / 64))`` copies. State
  targets / interface inputs (external_read edges) are permanent boundaries
  and count for every consuming compute block. Reads inside commit blocks
  never count. Multiple uses of the same value inside one block dedup to one.
- ``dag_edges``: def_use edges crossing blocks, deduped by
  (producer block, consumer block); order edges never count.
- ``compute_compute_value_pairs``: the unweighted version of cost (the
  pair count).
- ``footprint``: block count (each block costs fixed code size).

Everything is vectorized numpy so the full XiangShan graph scores in seconds.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .graph import InstructionGraph

ASSIGNMENT_FORMAT = "wolvrix.am-block-assignment.v1"


@dataclass
class Scoreboard:
    cost: int
    dag_edges: int
    compute_compute_value_pairs: int
    footprint: int  # total blocks (code-size proxy)
    compute_blocks: int
    commit_blocks: int

    def as_dict(self) -> dict[str, int]:
        return {
            "cost": self.cost,
            "dag_edges": self.dag_edges,
            "compute_compute_value_pairs": self.compute_compute_value_pairs,
            "footprint": self.footprint,
            "compute_blocks": self.compute_blocks,
            "commit_blocks": self.commit_blocks,
        }


def score_assignment(
    graph: InstructionGraph,
    instr_block: np.ndarray,
    commit_mask: np.ndarray,
) -> Scoreboard:
    """Score an assignment.

    ``instr_block``: (N,) uint32 block id per instruction. ``commit_mask``:
    (B,) bool, block id -> is a commit block.
    """
    if instr_block.shape[0] != graph.instructions:
        raise ValueError("instr_block length != instruction count")
    instr_block = instr_block.astype(np.int64)
    consumer_block = instr_block[graph.du_dst.astype(np.int64)]
    producer_block = instr_block[graph.du_src.astype(np.int64)]
    cross = producer_block != consumer_block

    dag_keys = np.unique((producer_block[cross] << 32) | consumer_block[cross])
    dag_edges = int(dag_keys.size)

    # (value, consuming compute block) pairs, width at first occurrence.
    parts = []
    du_keep = cross & ~commit_mask[consumer_block]
    parts.append(
        (
            (graph.du_var[du_keep].astype(np.int64) << 32) | consumer_block[du_keep],
            graph.du_width[du_keep],
        )
    )
    er_block = instr_block[graph.er_dst.astype(np.int64)]
    er_keep = ~commit_mask[er_block]
    parts.append(
        (
            (graph.er_var[er_keep].astype(np.int64) << 32) | er_block[er_keep],
            graph.er_width[er_keep],
        )
    )
    keys = np.concatenate([part[0] for part in parts])
    widths = np.concatenate([part[1] for part in parts])
    unique_keys, first = np.unique(keys, return_index=True)
    copies = np.maximum(1, (widths[first] + 63) // 64)
    return Scoreboard(
        cost=int(copies.sum()),
        dag_edges=dag_edges,
        compute_compute_value_pairs=int(unique_keys.size),
        footprint=int(commit_mask.size),
        compute_blocks=int((~commit_mask).sum()),
        commit_blocks=int(commit_mask.sum()),
    )


@dataclass
class Assignment:
    instr_block: np.ndarray  # (N,) uint32
    commit_mask: np.ndarray  # (max_block_id + 1,) bool; slot 0 pads 1-based ids
    blocks: int  # block records in the file (real blocks, excludes padding)
    compute_blocks: int
    commit_blocks: int
    header: dict


def load_assignment(path: str | Path) -> Assignment:
    """Load a ``wolvrix.am-block-assignment.v1`` JSONL export."""
    path = Path(path)
    header = None
    kinds: dict[int, bool] = {}
    instr_block = []
    with open(path) as stream:
        for line in stream:
            record = json.loads(line)
            kind = record["record"]
            if kind == "header":
                if record["format"] != ASSIGNMENT_FORMAT:
                    raise ValueError(f"unsupported assignment format: {record['format']}")
                header = record
            elif kind == "block":
                kinds[record["id"]] = record["kind"] == "commit"
            elif kind == "assign":
                instr_block.append(record["block"])
    if header is None:
        raise ValueError(f"{path} has no header record")
    if len(instr_block) != header["instructions"]:
        raise ValueError(
            f"assign records {len(instr_block)} != header instructions {header['instructions']}"
        )
    max_block = max(kinds) if kinds else 0
    commit_mask = np.zeros(max_block + 1, dtype=bool)
    for block_id, is_commit in kinds.items():
        commit_mask[block_id] = is_commit
    commit_blocks = sum(kinds.values())
    # The input sink is listed as a size-0 compute block record, while the
    # header's compute_blocks excludes it (docs/06 §1).
    input_sink = 1 if header.get("input_sink_block") else 0
    return Assignment(
        instr_block=np.array(instr_block, dtype=np.uint32),
        commit_mask=commit_mask,
        blocks=len(kinds),
        compute_blocks=len(kinds) - commit_blocks - input_sink,
        commit_blocks=commit_blocks,
        header=header,
    )
