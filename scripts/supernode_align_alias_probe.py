#!/usr/bin/env python3

"""Offline alias-elimination probe (supernode-align, NO0005 §4).

Bypasses width-matched single-operand `assign` instructions in an exported AM
instruction graph (consumers of the assign result are re-pointed to the
assign's operand), then re-runs the gsim-style coarsen (GOut1/GIn1) and
reports cross_values before/after. Estimates the value of an AM-level alias
elimination pass before touching production code.

Usage:
    supernode_align_alias_probe.py <instruction_graph.jsonl> [--budget N] [--max-instructions N]

Run with the repo venv (needs numpy): .venv/bin/python.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "topo-partition-proj" / "exp"))

import numpy as np  # noqa: E402

from harness.amcoarsen import coarsen, cluster_blocks  # noqa: E402
from harness.graph import load_graph  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph", type=Path)
    parser.add_argument("--budget", type=int, default=7000)
    parser.add_argument("--max-instructions", type=int, default=128)
    args = parser.parse_args()

    started = time.time()
    graph = load_graph(args.graph, use_cache=True, verbose=False)
    print(f"[load] instructions={graph.instructions} variables={graph.variables} "
          f"({time.time() - started:.0f}s)")

    # ---- identify eliminable assigns -------------------------------------
    assign_op_ids = [i for i, name in enumerate(graph.opcode_names) if name == "assign"]
    if not assign_op_ids:
        print("[alias] no assign opcodes found")
        return 1
    is_assign_op = np.isin(graph.op, assign_op_ids)
    var_def = graph.var_def()
    # per-variable width from first du/er edge occurrence
    var_width = np.full(graph.variables, -1, dtype=np.int64)
    seen = np.zeros(graph.variables, dtype=bool)
    for arr_v, arr_w in ((graph.du_var, graph.du_width), (graph.er_var, graph.er_width)):
        first = ~seen[arr_v]
        var_width[arr_v[first]] = arr_w[first]
        seen[arr_v] = True
    # operand structure per instruction
    du_order = np.argsort(graph.du_dst, kind="stable")
    du_dst_s = graph.du_dst[du_order]
    du_var_s = graph.du_var[du_order]
    du_bounds = np.searchsorted(du_dst_s, np.arange(graph.instructions + 1))
    er_order = np.argsort(graph.er_dst, kind="stable")
    er_dst_s = graph.er_dst[er_order]
    er_bounds = np.searchsorted(er_dst_s, np.arange(graph.instructions + 1))
    # result var per instruction (first defined var)
    res_of = np.full(graph.instructions, -1, dtype=np.int64)
    defined = var_def >= 0
    res_of[var_def[defined]] = np.nonzero(defined)[0]

    alias_of = np.full(graph.instructions, -1, dtype=np.int64)  # instr -> operand var
    n_instr = graph.instructions
    for a in np.nonzero(is_assign_op)[0].tolist():
        if er_bounds[a + 1] != er_bounds[a]:
            continue  # reads external state: not a pure alias
        lo, hi = du_bounds[a], du_bounds[a + 1]
        if hi - lo != 1:
            continue  # need exactly one operand
        u = int(du_var_s[lo])
        v = int(res_of[a])
        if v < 0:
            continue
        if var_width[v] != var_width[u]:
            continue  # width-changing assign: keep semantics
        alias_of[a] = u
    print(f"[alias] eliminable assigns: {int((alias_of >= 0).sum())} / {int(is_assign_op.sum())} "
          f"({time.time() - started:.0f}s)")

    # ---- resolve alias chains at value level ------------------------------
    # alias_var[v] = ultimate replacement var for v (itself if not assign-produced)
    alias_var = np.arange(graph.variables, dtype=np.int64)
    for a in np.nonzero(alias_of >= 0)[0].tolist():
        v = int(res_of[a])
        alias_var[v] = alias_of[a]

    def resolve(x: np.ndarray) -> np.ndarray:
        r = x.copy()
        while True:
            p = alias_var[r]
            if (p == r).all():
                return r
            r = np.where(p == r, r, alias_var[p])

    eliminated = alias_of >= 0
    # ---- rewrite edges ----------------------------------------------------
    keep_du = ~eliminated[graph.du_dst.astype(np.int64)]
    new_var = resolve(graph.du_var[keep_du])
    new_dst = graph.du_dst[keep_du]
    new_def = var_def[new_var]  # defining instruction of resolved var
    has_def = new_def >= 0
    new_src = np.where(has_def, new_def, 0).astype(np.int64)
    # constant/state vars (no definer): become external reads instead
    g_du_src = new_src[has_def]
    g_du_dst = new_dst[has_def].astype(np.int64)
    g_du_var = new_var[has_def]
    g_er_dst = np.concatenate([graph.er_dst, new_dst[~has_def]]).astype(np.int64)
    g_er_var = np.concatenate([graph.er_var, new_var[~has_def]]).astype(np.int64)
    keep_ord = ~(eliminated[graph.ord_src.astype(np.int64)] | eliminated[graph.ord_dst.astype(np.int64)])
    g_ord_src = graph.ord_src[keep_ord].astype(np.int64)
    g_ord_dst = graph.ord_dst[keep_ord].astype(np.int64)
    alive = ~eliminated
    alive_idx = np.nonzero(alive)[0]
    # atoms: keep original atom ids of alive instructions; state_write unchanged
    g_atom_of_instr = graph.atom[alive_idx].astype(np.int64)
    g_state_write = graph.state_write[alive_idx]
    print(f"[alias] alive instructions={alive_idx.size} "
          f"du {graph.du_src.size}->{g_du_src.size} er {graph.er_dst.size}->{g_er_dst.size} "
          f"({time.time() - started:.0f}s)")

    # ---- coarsen on the rewritten graph -----------------------------------
    # remap atom ids to dense 0..M-1
    uniq_atoms, atom_dense = np.unique(g_atom_of_instr, return_inverse=True)
    m = uniq_atoms.size
    active = np.ones(m, dtype=bool)
    active[atom_dense[g_state_write]] = False
    # map edge endpoints (original instruction ids -> alive positions -> dense atoms)
    pos_of = np.full(n_instr, -1, dtype=np.int64)
    pos_of[alive_idx] = np.arange(alive_idx.size)
    esrc = atom_dense[pos_of[g_du_src]]
    edst = atom_dense[pos_of[g_du_dst]]
    osrc = atom_dense[pos_of[g_ord_src]]
    odst = atom_dense[pos_of[g_ord_dst]]
    all_src = np.concatenate([esrc, osrc])
    all_dst = np.concatenate([edst, odst])
    keep = all_src != all_dst
    pairs = np.unique((all_src[keep] << 32) | all_dst[keep])
    e_src = (pairs >> 32).astype(np.int64)
    e_dst = (pairs & 0xFFFFFFFF).astype(np.int64)
    weights = np.bincount(atom_dense, minlength=m).astype(np.int64)
    oversized = weights > args.max_instructions
    result = coarsen(
        e_src, e_dst, m, active, budget=args.budget, oversized_weight=oversized,
        mode="sequential", max_iters=64, weights=weights,
        pass_order=("GOut1", "GIn1"),
    )
    print(f"[coarsen-after-alias] merges={result.merges} rounds={result.rounds} "
          f"({time.time() - started:.0f}s)")
    block_of_atom = cluster_blocks(result.parent, e_src, e_dst, active, weights, args.max_instructions)
    instr_block_alive = block_of_atom[atom_dense].astype(np.int64)
    next_block = instr_block_alive.max() + 1
    instr_block_alive[block_of_atom[atom_dense] < 0] = next_block

    pb = instr_block_alive[pos_of[g_du_src]]
    cb = instr_block_alive[pos_of[g_du_dst]]
    cross = pb != cb
    cross_values = int(np.unique(g_du_var[cross]).size)
    print(f"[score-after-alias] cross_values={cross_values} cross_edges={int(cross.sum())} "
          f"blocks={int(next_block) + 1} ({time.time() - started:.0f}s)")
    print("[reference] same coarsen config without alias elimination: 620,522 "
          "(build/logs/sandbox_gsim_style_20260804.log)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
