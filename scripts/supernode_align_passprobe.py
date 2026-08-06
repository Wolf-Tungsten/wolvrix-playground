#!/usr/bin/env python3

"""Graph-pass probe on the NO0010 flat-graph baseline (supernode-align).

Applies graph-level passes to an exported AM instruction graph in memory,
re-runs the production-equivalent sandbox coarsen (sequential Out1+In1+Sibling,
budget/max-instructions as given), and scores cross_values. Used to quantify
pass candidates before touching production C++ (NO0010 §0/§5.3).

Passes:
- ``alias``: bypass width-matched single-operand assigns (consumers re-pointed
  to the assign's operand); iterated to chain fixpoint.
- ``cse``: eliminate exact duplicates — same (op, result width, sorted operand
  multiset, sorted er operand multiset) — over a whitelist of side-effect-free
  ops; representative = lowest instruction id; iterated to fixpoint (downstream
  instructions can become duplicates after re-pointing). Operand order is not
  preserved by the JSONL export, so non-commutative ops are an upper bound.

Usage:
    supernode_align_passprobe.py <instruction_graph.jsonl> \
        [--passes alias,cse] [--budget N] [--max-instructions N] [--max-iters N]

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

# side-effect-free ops eligible for CSE (state writes/reads, event detectors,
# host calls excluded)
CSE_WHITELIST = {
    "and", "or", "xor", "xnor", "not", "logic_and", "logic_or", "logic_not",
    "eq", "ne", "lt", "le", "gt", "ge",
    "add", "sub", "mul", "div", "shl", "lshr", "ashr",
    "mux", "concat", "slice_static", "slice_dynamic", "replicate",
    "reduce_or", "reduce_and", "reduce_xor",
    "array.mux", "array.broadcast", "array.reduce_or", "array.reduce_and",
    "array.reduce_lanes_or", "array.reduce_lanes_and", "array.reduce_lanes_xor",
    "array.onehot", "array.read_all",
}


class RewrittenGraph:
    """Mutable instruction-graph view for pass rewriting."""

    def __init__(self, graph):
        n = graph.instructions
        self.n = n
        self.variables = graph.variables
        self.op = graph.op
        self.atom = graph.atom.astype(np.int64)
        self.state_write = graph.state_write
        self.opcode_names = graph.opcode_names
        # per-instruction operand lists (du vars, er vars)
        du_order = np.argsort(graph.du_dst, kind="stable")
        du_dst_s = graph.du_dst[du_order]
        du_var_s = graph.du_var[du_order]
        du_bounds = np.searchsorted(du_dst_s, np.arange(n + 1))
        er_order = np.argsort(graph.er_dst, kind="stable")
        er_dst_s = graph.er_dst[er_order]
        er_var_s = graph.er_var[er_order]
        er_bounds = np.searchsorted(er_dst_s, np.arange(n + 1))
        self.du_ops = [du_var_s[du_bounds[i]:du_bounds[i + 1]].astype(np.int64) for i in range(n)]
        self.er_ops = [er_var_s[er_bounds[i]:er_bounds[i + 1]].astype(np.int64) for i in range(n)]
        # result var per instruction
        var_def = graph.var_def()
        defined = var_def >= 0
        self.res_of = np.full(n, -1, dtype=np.int64)
        self.res_of[var_def[defined]] = np.nonzero(defined)[0]
        # width per variable
        self.var_width = np.full(graph.variables, -1, dtype=np.int64)
        seen = np.zeros(graph.variables, dtype=bool)
        for arr_v, arr_w in ((graph.du_var, graph.du_width), (graph.er_var, graph.er_width)):
            first = ~seen[arr_v]
            self.var_width[arr_v[first]] = arr_w[first]
            seen[arr_v] = True
        # order edges (kept as raw arrays, re-pointed on elimination)
        self.ord_src = graph.ord_src.astype(np.int64)
        self.ord_dst = graph.ord_dst.astype(np.int64)
        self.alive = np.ones(n, dtype=bool)

    # -- passes ------------------------------------------------------------

    def alias_pass(self) -> int:
        """Bypass width-matched single-operand assigns. Returns eliminated count."""
        assign_ids = [i for i, name in enumerate(self.opcode_names) if name == "assign"]
        is_assign = np.isin(self.op, assign_ids)
        alias_var = np.arange(self.variables, dtype=np.int64)
        eliminated = 0
        for a in np.nonzero(is_assign & self.alive)[0].tolist():
            if self.er_ops[a].size:
                continue
            if self.du_ops[a].size != 1:
                continue
            u = int(self.du_ops[a][0])
            v = int(self.res_of[a])
            if v < 0 or self.var_width[v] != self.var_width[u]:
                continue
            alias_var[v] = u
            self.alive[a] = False
            eliminated += 1
        if not eliminated:
            return 0
        # resolve chains
        while True:
            p = alias_var[alias_var]
            if (p == alias_var).all():
                break
            alias_var = p
        # re-point all operand vars of alive instructions
        for i in np.nonzero(self.alive)[0].tolist():
            if self.du_ops[i].size:
                self.du_ops[i] = alias_var[self.du_ops[i]]
            if self.er_ops[i].size:
                self.er_ops[i] = alias_var[self.er_ops[i]]
        return eliminated

    def cse_pass(self) -> int:
        """Eliminate exact duplicates over the whitelist. Returns eliminated count."""
        wl_ids = {i for i, name in enumerate(self.opcode_names) if name in CSE_WHITELIST}
        groups: dict[tuple, list[int]] = {}
        for i in np.nonzero(self.alive)[0].tolist():
            if int(self.op[i]) not in wl_ids:
                continue
            if self.res_of[i] < 0:
                continue
            if not (self.du_ops[i].size or self.er_ops[i].size):
                continue
            key = (
                int(self.op[i]),
                int(self.var_width[self.res_of[i]]),
                tuple(sorted(int(v) for v in self.du_ops[i])),
                tuple(sorted(int(v) for v in self.er_ops[i])),
            )
            groups.setdefault(key, []).append(i)
        alias_var = np.arange(self.variables, dtype=np.int64)
        rep_of = np.arange(self.n, dtype=np.int64)  # instruction-level representative
        eliminated = 0
        for members in groups.values():
            if len(members) < 2:
                continue
            rep = min(members)
            rep_var = int(self.res_of[rep])
            for m in members:
                if m == rep:
                    continue
                alias_var[int(self.res_of[m])] = rep_var
                rep_of[m] = rep
                self.alive[m] = False
                eliminated += 1
        if not eliminated:
            return 0
        # no chains possible within one round (rep vars are not eliminated),
        # but be safe
        while True:
            p = alias_var[alias_var]
            if (p == alias_var).all():
                break
            alias_var = p
        for i in np.nonzero(self.alive)[0].tolist():
            if self.du_ops[i].size:
                self.du_ops[i] = alias_var[self.du_ops[i]]
            if self.er_ops[i].size:
                self.er_ops[i] = alias_var[self.er_ops[i]]
        # order edges: re-point eliminated endpoints to their representative
        mask = ~self.alive[self.ord_src]
        self.ord_src[mask] = rep_of[self.ord_src[mask]]
        mask = ~self.alive[self.ord_dst]
        self.ord_dst[mask] = rep_of[self.ord_dst[mask]]
        return eliminated

    def romfold_pass(self) -> int:
        """Mark constant-address reads of never-written memories as dead
        (their results become external constants: zero-init storage).

        INVALID on the JSONL export: the exporter drops write->memory operand
        edges (isDependencyOperand excludes state-target operands), so every
        memory looks unwritten. Kept only as documentation of the NO0011 §3.1
        pitfall; do not use its numbers."""
        memread_ids = [i for i, name in enumerate(self.opcode_names) if name == "mem.read"]
        memwrite_ids = [i for i, name in enumerate(self.opcode_names)
                        if name in ("mem.write", "mem.fill")]
        if not memread_ids:
            return 0
        written = np.zeros(self.variables, dtype=bool)
        for i in np.nonzero(self.alive)[0].tolist():
            if int(self.op[i]) in memwrite_ids and self.er_ops[i].size >= 1:
                written[int(self.er_ops[i][0])] = True
        eliminated = 0
        for i in np.nonzero(self.alive)[0].tolist():
            if int(self.op[i]) not in memread_ids:
                continue
            if self.du_ops[i].size != 0 or self.er_ops[i].size != 2:
                continue  # only the (memory, const-address) form
            if written[int(self.er_ops[i][0])]:
                continue
            self.alive[i] = False
            eliminated += 1
        return eliminated

    # -- export to sandbox --------------------------------------------------

    def edge_arrays(self):
        """Build (du_src, du_dst, du_var, er_dst, er_var, ord_src, ord_dst) over
        alive instructions, resolved through current operand lists."""
        alive_idx = np.nonzero(self.alive)[0]
        var_def = np.full(self.variables, -1, dtype=np.int64)
        for i in alive_idx.tolist():
            if self.res_of[i] >= 0:
                var_def[self.res_of[i]] = i
        du_src_l, du_dst_l, du_var_l = [], [], []
        er_dst_l, er_var_l = [], []
        for i in alive_idx.tolist():
            for v in self.du_ops[i]:
                d = var_def[v]
                if d >= 0:
                    du_src_l.append(d)
                    du_dst_l.append(i)
                    du_var_l.append(int(v))
                else:
                    er_dst_l.append(i)
                    er_var_l.append(int(v))
            for v in self.er_ops[i]:
                er_dst_l.append(i)
                er_var_l.append(int(v))
        keep_ord = self.alive[self.ord_src] & self.alive[self.ord_dst]
        return (
            np.array(du_src_l, dtype=np.int64),
            np.array(du_dst_l, dtype=np.int64),
            np.array(du_var_l, dtype=np.int64),
            np.array(er_dst_l, dtype=np.int64),
            np.array(er_var_l, dtype=np.int64),
            self.ord_src[keep_ord],
            self.ord_dst[keep_ord],
            alive_idx,
        )


def run_sandbox(rg: RewrittenGraph, budget: int, max_instructions: int, max_iters: int) -> None:
    du_src, du_dst, du_var, er_dst, er_var, ord_src, ord_dst, alive_idx = rg.edge_arrays()
    atom_of_instr = rg.atom[alive_idx]
    uniq_atoms, atom_dense = np.unique(atom_of_instr, return_inverse=True)
    m = uniq_atoms.size
    active = np.ones(m, dtype=bool)
    active[atom_dense[rg.state_write[alive_idx]]] = False
    pos_of = np.full(rg.n, -1, dtype=np.int64)
    pos_of[alive_idx] = np.arange(alive_idx.size)
    esrc = atom_dense[pos_of[du_src]]
    edst = atom_dense[pos_of[du_dst]]
    osrc = atom_dense[pos_of[ord_src]]
    odst = atom_dense[pos_of[ord_dst]]
    all_src = np.concatenate([esrc, osrc])
    all_dst = np.concatenate([edst, odst])
    keep = all_src != all_dst
    pairs = np.unique((all_src[keep] << 32) | all_dst[keep])
    e_src = (pairs >> 32).astype(np.int64)
    e_dst = (pairs & 0xFFFFFFFF).astype(np.int64)
    weights = np.bincount(atom_dense, minlength=m).astype(np.int64)
    oversized = weights > max_instructions
    result = coarsen(
        e_src, e_dst, m, active, budget=budget, oversized_weight=oversized,
        mode="sequential", max_iters=max_iters, weights=weights,
        pass_order=("Out1", "In1", "Sibling"),
    )
    print(f"[coarsen] merges={result.merges} rounds={result.rounds}")
    block_of_atom = cluster_blocks(result.parent, e_src, e_dst, active, weights, max_instructions)
    instr_block_alive = block_of_atom[atom_dense].astype(np.int64)
    next_block = instr_block_alive.max() + 1
    instr_block_alive[instr_block_alive < 0] = next_block
    pb = instr_block_alive[pos_of[du_src]]
    cb = instr_block_alive[pos_of[du_dst]]
    cross = pb != cb
    cross_values = int(np.unique(du_var[cross]).size)
    print(f"[score] cross_values={cross_values} cross_edges={int(cross.sum())} "
          f"compute_blocks={int(next_block)} instructions={alive_idx.size}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph", type=Path)
    parser.add_argument("--passes", default="alias,cse")
    parser.add_argument("--budget", type=int, default=192)
    parser.add_argument("--max-instructions", type=int, default=128)
    parser.add_argument("--max-iters", type=int, default=256)
    args = parser.parse_args()

    started = time.time()
    graph = load_graph(args.graph, use_cache=True, verbose=False)
    print(f"[load] instructions={graph.instructions} ({time.time() - started:.0f}s)")
    rg = RewrittenGraph(graph)
    print(f"[init] operand lists built ({time.time() - started:.0f}s)")

    for name in [p.strip() for p in args.passes.split(",") if p.strip()]:
        if name == "alias":
            total = 0
            for rnd in range(8):
                n = rg.alias_pass()
                total += n
                if n == 0:
                    break
            print(f"[pass:alias] eliminated={total} alive={int(rg.alive.sum())} "
                  f"({time.time() - started:.0f}s)")
        elif name == "cse":
            total = 0
            for rnd in range(8):
                n = rg.cse_pass()
                total += n
                print(f"[pass:cse] round {rnd}: eliminated={n} ({time.time() - started:.0f}s)")
                if n == 0:
                    break
            print(f"[pass:cse] eliminated_total={total} alive={int(rg.alive.sum())}")
        elif name == "romfold":
            n = rg.romfold_pass()
            print(f"[pass:romfold] eliminated={n} alive={int(rg.alive.sum())} "
                  f"({time.time() - started:.0f}s)")
        else:
            print(f"[pass:{name}] unknown pass, skipped")

    run_sandbox(rg, args.budget, args.max_instructions, args.max_iters)
    print(f"[done] {time.time() - started:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
