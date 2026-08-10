#!/usr/bin/env python3
"""Dump a dataset's atom-DAG and metric inputs as raw .npy arrays for the
standalone C++ partition lab (partition_lab.cpp).

Usage: partition_lab_dump.py DATASET_DIR OUT_DIR
Reads <DATASET_DIR>/graph_cache.npz (+ instruction_graph.jsonl for state_write
fallback) and writes OUT_DIR/{atom_offsets,atom_targets,atom_min_instr,
instr_atom,instr_state_write,du_src,d du_dst,du_var}.npy
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

import numpy as np


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("out")
    ap.add_argument("--full-graph", action="store_true")
    args = ap.parse_args()
    dataset = Path(args.dataset)
    out = Path(args.out)
    full_graph = args.full_graph
    out.mkdir(parents=True, exist_ok=True)
    c = np.load(dataset / "graph_cache.npz")
    instr_atom = c["atom"].astype(np.int64)
    n_instr = int(np.asarray(c["instructions"]).item())
    n_atom = int(instr_atom.max()) + 1

    # NO0015: the lab must partition the graph the production partitioner
    # actually sees. AM production partitions only the compute graph (commit
    # atoms = atoms containing state_write instructions are clustered
    # separately), so they are excluded here. gsim production partitions its
    # whole node graph (REG_UPDATE/writer nodes included), so gsim datasets
    # are left untouched. --full-graph reproduces the pre-fix (NO0014) dumps.
    is_gsim = "REG_UPDATE" in str(c["opcode_names"][0])
    drop = np.zeros(n_atom, dtype=bool)
    if not is_gsim and not full_graph:
        sw = c["state_write"].astype(bool)
        np.logical_or.at(drop, instr_atom[sw], True)
    keep_atom = ~drop
    remap = np.full(n_atom, -1, dtype=np.int64)
    remap[keep_atom] = np.arange(int(keep_atom.sum()), dtype=np.int64)
    n_kept = int(keep_atom.sum())

    # instruction-level edges: def_use + order (the AM atom DAG is the SCC
    # condensation of def_use + ordered-effect edges)
    e_src = [c["du_src"].astype(np.int64)]
    e_dst = [c["du_dst"].astype(np.int64)]
    if "ord_src" in c:
        e_src.append(c["ord_src"].astype(np.int64))
        e_dst.append(c["ord_dst"].astype(np.int64))
    src = np.concatenate(e_src)
    dst = np.concatenate(e_dst)

    a_src = remap[instr_atom[src]]
    a_dst = remap[instr_atom[dst]]
    keep = (a_src != a_dst) & (a_src >= 0) & (a_dst >= 0)
    dropped_backfeed = int(((a_src < 0) & (a_dst >= 0)).sum())
    if dropped_backfeed:
        raise SystemExit(f"commit->compute back-edge count={dropped_backfeed}; split violated")
    pair = np.unique((a_src[keep].astype(np.uint64) << 32) | a_dst[keep].astype(np.uint64))
    ea_src = (pair >> 32).astype(np.int64)
    ea_dst = (pair & np.uint64(0xFFFFFFFF)).astype(np.int64)

    order = np.argsort(ea_src, kind="stable")
    ea_src, ea_dst = ea_src[order], ea_dst[order]
    offsets = np.zeros(n_kept + 1, dtype=np.int64)
    np.add.at(offsets, ea_src + 1, 1)
    offsets = np.cumsum(offsets)

    atom_min_instr = np.full(n_kept, n_instr, dtype=np.int64)
    np.minimum.at(atom_min_instr, remap[instr_atom[keep_atom[instr_atom]]],
                  np.arange(n_instr, dtype=np.int64)[keep_atom[instr_atom]])

    # NO0015 replication support: per-atom "hard" flag (not replicable).
    # hard = read-port / detector / host-effect roots (mem.read*, changed.*,
    # dpi/system) -- replication stops at these (replicate up TO the read
    # port, never duplicating the port itself).
    names = ast.literal_eval(str(c["opcode_names"][0]))
    op = c["op"].astype(np.int64)
    tpos = c["topo_pos"].astype(np.int64)
    best = np.full(n_atom, -1, dtype=np.int64)
    np.maximum.at(best, instr_atom, tpos)
    ach = tpos == best[instr_atom]
    root_instr = np.full(n_atom, -1, dtype=np.int64)
    root_instr[instr_atom[ach]] = np.arange(n_instr)[ach]
    root_op = np.full(n_atom, -1, dtype=np.int64)
    valid = root_instr >= 0
    root_op[valid] = op[root_instr[valid]]
    hard_substr = ("mem.read", "changed.", "dpi", "system")
    hard_names = {i for i, nm in enumerate(names)
                  if any(sub in nm for sub in hard_substr)}
    atom_hard = np.isin(root_op, list(hard_names)) if hard_names else np.zeros(n_atom, bool)
    atom_hard = atom_hard[keep_atom]
    atom_icount = np.bincount(remap[instr_atom[keep_atom[instr_atom]]],
                              minlength=n_kept)

    np.save(out / "atom_offsets.npy", offsets.astype(np.uint32))
    np.save(out / "atom_hard.npy", atom_hard.astype(np.uint8))
    np.save(out / "atom_icount.npy", atom_icount.astype(np.uint32))
    np.save(out / "atom_targets.npy", ea_dst.astype(np.uint32))
    np.save(out / "atom_min_instr.npy", atom_min_instr.astype(np.uint32))
    np.save(out / "instr_atom.npy", remap[instr_atom].astype(np.uint32))
    np.save(out / "instr_state_write.npy", c["state_write"].astype(np.uint8))
    np.save(out / "du_src.npy", c["du_src"].astype(np.uint32))
    np.save(out / "du_dst.npy", c["du_dst"].astype(np.uint32))
    np.save(out / "du_var.npy", c["du_var"].astype(np.uint32))
    print(f"atoms={n_kept} (dropped {int(drop.sum())} state atoms, gsim={is_gsim}) "
          f"edges={ea_src.size} instrs={n_instr} -> {out}")


if __name__ == "__main__":
    main()
