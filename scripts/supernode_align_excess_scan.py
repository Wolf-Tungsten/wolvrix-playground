#!/usr/bin/env python3

"""Quantify graph-shape excess in an AM instruction graph (supernode-align).

Scans for pass-exploitable redundancy, split by whether the produced value
currently crosses blocks (using a reference assignment):

- exact duplicates: instructions sharing (op, result width, sorted operand
  multiset) with another instruction — CSE potential. Operands include both
  def_use and external_read vars (same variable space; external reads carry
  constants and state). Upper bound: operand order is not preserved by the
  JSONL export, so non-commutative ops are over-counted; and the export does
  NOT carry the slice_static lsb attribute, so same-source slices at
  different offsets look identical — treat slice_static dup counts as
  inflated (production CSE keys on the exact attributes and is the ground
  truth).
- alias assigns: width-matched single-operand assigns (alias elimination);
- slice chains: slice_static whose operand is itself produced by slice_static
  (slice-of-slice fusion potential);
- duplicate mem.reads: mem.read instructions sharing all operands.

Usage:
    supernode_align_excess_scan.py <instruction_graph.jsonl> [block_assignment.jsonl]

Run with the repo venv (needs numpy): .venv/bin/python.
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "topo-partition-proj" / "exp"))

import numpy as np  # noqa: E402

from harness.graph import load_graph  # noqa: E402
from harness.scorer import load_assignment  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        sys.stderr.write(__doc__ or "")
        return 2
    started = time.time()
    graph = load_graph(sys.argv[1], use_cache=True, verbose=False)
    names = graph.opcode_names
    op_name = {i: n for i, n in enumerate(names)}

    cross_var_set: set[int] | None = None
    if len(sys.argv) > 2:
        assignment = load_assignment(sys.argv[2])
        instr_block = assignment.instr_block.astype(np.int64)
        pb = instr_block[graph.du_src.astype(np.int64)]
        cb = instr_block[graph.du_dst.astype(np.int64)]
        cross_var_set = set(np.unique(graph.du_var[pb != cb]).tolist())

    # operand CSR for both edge kinds (same variable space)
    du_order = np.argsort(graph.du_dst, kind="stable")
    du_dst_s = graph.du_dst[du_order]
    du_var_s = graph.du_var[du_order]
    du_bounds = np.searchsorted(du_dst_s, np.arange(graph.instructions + 1))
    er_order = np.argsort(graph.er_dst, kind="stable")
    er_dst_s = graph.er_dst[er_order]
    er_var_s = graph.er_var[er_order]
    er_bounds = np.searchsorted(er_dst_s, np.arange(graph.instructions + 1))
    var_def = graph.var_def()
    defined = var_def >= 0
    res_of = np.full(graph.instructions, -1, dtype=np.int64)
    res_of[var_def[defined]] = np.nonzero(defined)[0]

    # per-variable width
    var_width = np.full(graph.variables, -1, dtype=np.int64)
    seen = np.zeros(graph.variables, dtype=bool)
    for arr_v, arr_w in ((graph.du_var, graph.du_width), (graph.er_var, graph.er_width)):
        first = ~seen[arr_v]
        var_width[arr_v[first]] = arr_w[first]
        seen[arr_v] = True

    def operands_of(i: int) -> tuple[int, ...]:
        ops = [int(v) for v in du_var_s[du_bounds[i]:du_bounds[i + 1]]]
        ops.extend(int(v) for v in er_var_s[er_bounds[i]:er_bounds[i + 1]])
        return tuple(sorted(ops))

    # ---- exact duplicates (op, result width, sorted operand multiset) -----
    print(f"[scan] instructions={graph.instructions} ({time.time() - started:.0f}s)")
    has_ops = (du_bounds[1:] > du_bounds[:-1]) | (er_bounds[1:] > er_bounds[:-1])
    cand = np.nonzero(has_ops & (res_of >= 0))[0]
    per_instr_key: dict[int, tuple[int, int, tuple[int, ...]]] = {}
    for i in cand.tolist():
        per_instr_key[i] = (int(graph.op[i]), int(var_width[res_of[i]]), operands_of(i))
    key_counter: Counter = Counter(per_instr_key.values())
    dup_extra = 0
    dup_extra_cross = 0
    dup_by_op: Counter = Counter()
    for key, count in key_counter.items():
        if count < 2:
            continue
        dup_extra += count - 1
        dup_by_op[op_name.get(key[0], key[0])] += count - 1
    if cross_var_set is not None:
        for i, key in per_instr_key.items():
            if key_counter[key] >= 2 and int(res_of[i]) in cross_var_set:
                dup_extra_cross += 1  # members of dup groups whose value crosses
    print(f"[dup] duplicate-extra instructions={dup_extra} "
          f"(crossing members={dup_extra_cross}) top: "
          + " ".join(f"{n}={c}" for n, c in dup_by_op.most_common(12)))

    # ---- alias assigns -----------------------------------------------------
    assign_ids = [i for i, n in enumerate(names) if n == "assign"]
    is_assign = np.isin(graph.op, assign_ids)
    alias_ok = 0
    alias_cross = 0
    for a in np.nonzero(is_assign)[0].tolist():
        if er_bounds[a + 1] != er_bounds[a]:
            continue  # reads external state: not a pure alias
        lo, hi = du_bounds[a], du_bounds[a + 1]
        if hi - lo != 1:
            continue
        u, v = int(du_var_s[lo]), int(res_of[a])
        if v < 0 or var_width[v] != var_width[u]:
            continue
        alias_ok += 1
        if cross_var_set is not None and v in cross_var_set:
            alias_cross += 1
    print(f"[alias] eliminable assigns={alias_ok} / {int(is_assign.sum())} (crossing={alias_cross})")

    # ---- slice-of-slice chains ---------------------------------------------
    slice_ids = {i for i, n in enumerate(names) if n == "slice_static"}
    if slice_ids:
        is_slice = np.isin(graph.op, list(slice_ids))
        slice_instr = np.nonzero(is_slice)[0]
        slice_op_is_slice = 0
        slice_cross = 0
        for s in slice_instr.tolist():
            lo, hi = du_bounds[s], du_bounds[s + 1]
            if hi - lo < 1:
                continue
            src_def = var_def[du_var_s[lo:hi]]
            src_def = src_def[src_def >= 0]
            if src_def.size and bool(is_slice[src_def].any()):
                slice_op_is_slice += 1
            if cross_var_set is not None and int(res_of[s]) in cross_var_set:
                slice_cross += 1
        print(f"[slice] slice_static total={slice_instr.size} crossing={slice_cross} "
              f"operand-also-slice={slice_op_is_slice}")

    # ---- duplicate mem.reads -------------------------------------------------
    memread_ids = [i for i, n in enumerate(names) if n == "mem.read"]
    if memread_ids:
        is_mr = np.isin(graph.op, memread_ids)
        mr_keys: Counter = Counter()
        mr_instr = np.nonzero(is_mr)[0]
        for i in mr_instr.tolist():
            mr_keys[(int(var_width[res_of[i]]), operands_of(i))] += 1
        mr_extra = sum(c - 1 for c in mr_keys.values() if c >= 2)
        mr_groups = sum(1 for c in mr_keys.values() if c >= 2)
        print(f"[mem.read] total={mr_instr.size} unique={len(mr_keys)} "
              f"duplicate-extra={mr_extra} (groups>=2: {mr_groups})")

    print(f"[done] {time.time() - started:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
