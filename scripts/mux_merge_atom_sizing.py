#!/usr/bin/env python3
"""Sizing analysis for mux-merge atoms (am-graph NO0006).

Groups compute-graph muxes by their select variable (def_use operand slot 0),
then measures how much of the input cone is absorbable into the atom under the
exclusive-use rule (a producer node is absorbable iff every use of every result
var of it stays inside the atom), plus the edge-convergence estimate.

Inputs (same-source split exports with operand slots on def_use edges):
  compute: build/xs/am-split-export-wvar/named.compute.jsonl
  commit : build/xs/am-split-export-wvar/named.commit.jsonl
    (commit external_read records pin compute vars that cross to the commit
    side -- those must count as used-outside for absorbability.)

Usage: .venv/bin/python scripts/mux_merge_atom_sizing.py [compute.jsonl] [commit.jsonl]
Writes mux_merge_atom_sizing.json next to the compute export and prints a summary.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, deque
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
COMPUTE = Path(sys.argv[1] if len(sys.argv) > 1 else
              REPO / "build/xs/am-split-export-wvar/named.compute.jsonl")
COMMIT = Path(sys.argv[2] if len(sys.argv) > 2 else
             REPO / "build/xs/am-split-export-wvar/named.commit.jsonl")
OUT = COMPUTE.parent / "mux_merge_atom_sizing.json"

CAPS = (32, 64, 128, 256)


def load_compute(path: Path):
    ops, widths = [], []
    es, ed, ev, eo = [], [], [], []
    with open(path) as f:
        for line in f:
            line = line.replace('\\"', '"')
            if '"record":"node"' in line:
                r = json.loads(line)
                ops.append(r["opcode"])
            elif '"kind":"def_use"' in line:
                r = json.loads(line)
                es.append(r["src"]); ed.append(r["dst"])
                ev.append(r["var"]); eo.append(r.get("operand", -1))
    return (np.array(ops, dtype=object), np.array(es, dtype=np.int64),
            np.array(ed, dtype=np.int64), np.array(ev, dtype=np.int64),
            np.array(eo, dtype=np.int64))


def load_commit_pinned_vars(path: Path) -> np.ndarray:
    # Every commit-side external_read var is a use outside the compute graph,
    # whether or not it also has compute-side uses (the export carries no
    # src_side, so pinning by var id is the correct conservative rule).
    pinned = []
    with open(path) as f:
        for line in f:
            line = line.replace('\\"', '"')
            if '"kind":"external_read"' not in line:
                continue
            r = json.loads(line)
            pinned.append(r["var"])
    return np.array(sorted(set(pinned)), dtype=np.int64)


def csr_by_key(key: np.ndarray, size: int):
    order = np.argsort(key, kind="stable")
    sorted_key = key[order]
    starts = np.searchsorted(sorted_key, np.arange(size + 1))
    return order, starts


def main() -> int:
    ops, es, ed, ev, eo = load_compute(COMPUTE)
    n = len(ops)
    print(f"[load] nodes={n} def_use_edges={es.size}", flush=True)
    pinned = load_commit_pinned_vars(COMMIT)
    n_vars = int(max(ev.max(), pinned.max(initial=0))) + 1
    # var -> def node
    var_def = np.full(n_vars, -1, dtype=np.int64)
    var_def[ev] = es
    var_pinned = np.zeros(n_vars, dtype=bool)
    var_pinned[pinned] = True
    print(f"[load] commit-side externally-read vars={pinned.size} "
          f"(of which compute-produced={int((var_def[pinned] >= 0).sum())})",
          flush=True)

    # CSR adjacency:
    #  by destination (consumer): node -> operand edges (var, src, slot)
    dst_order, dst_starts = csr_by_key(ed, n)
    op_var = ev[dst_order]; op_src = es[dst_order]; op_slot = eo[dst_order]
    #  by source (producer): node -> produced edges (var, dst)
    src_order, src_starts = csr_by_key(es, n)
    prod_var = ev[src_order]; prod_dst = ed[src_order]
    #  by variable: var -> use edges (dst node, slot)
    var_order, var_starts = csr_by_key(ev, n_vars)
    use_dst = ed[var_order]; use_slot = eo[var_order]
    print("[csr] adjacency ready", flush=True)

    is_mux = ops == "mux"
    mux_count = int(is_mux.sum())

    # mux select / arms from operand slots
    groups: dict[int, list[int]] = {}
    arm_of: dict[int, list[int]] = {}
    for m in np.nonzero(is_mux)[0].tolist():
        lo, hi = dst_starts[m], dst_starts[m + 1]
        sel = -1
        for k in range(lo, hi):
            slot = op_slot[k]
            if slot == 0:
                sel = int(op_var[k])
            elif slot in (1, 2):
                arm_of.setdefault(m, []).append(int(op_var[k]))
        if sel >= 0:
            groups.setdefault(sel, []).append(m)

    sizes = np.array(sorted((len(g) for g in groups.values()), reverse=True),
                    dtype=np.int64)

    def bucket(s: int) -> str:
        if s == 1: return "1"
        if s <= 3: return "2-3"
        if s <= 7: return "4-7"
        if s <= 15: return "8-15"
        if s <= 63: return "16-63"
        return ">=64"

    dist = Counter(bucket(int(s)) for s in sizes)
    mux_in = Counter()
    for s in sizes:
        mux_in[bucket(int(s))] += int(s)
    print(f"[group] select vars={sizes.size} mux with select={int(sizes.sum())} "
          f"(total mux={mux_count})")
    for b in ("1", "2-3", "4-7", "8-15", "16-63", ">=64"):
        if dist.get(b):
            print(f"   {b:>5}: groups={dist[b]:>6}  muxes={mux_in[b]:>7}", flush=True)

    # ---- absorption under exclusive use (greedy, largest groups first) ----
    claimed = np.zeros(n, dtype=bool)
    absorb_total = 0
    edge_before = 0
    edge_after = 0
    select_absorbable = 0
    overflow = 0
    mux_kept = 0
    absorbed_per_cap = Counter()
    group_absorb_sizes = []
    atom_sizes = []
    big = [(v, g) for v, g in groups.items() if len(g) >= 2]
    big.sort(key=lambda t: -len(t[1]))
    MAXCONE = 1 << 30  # cone walk unbounded; atomization skipped when the
    # TOTAL atom size exceeds MAXATOM (0 = unlimited) -- activation-granularity
    # protection, not partition-feasibility (NO0006 §10).
    MAXATOM = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    for gi, (sel, members) in enumerate(big):
        if gi % 2000 == 0:
            print(f"[absorb] {gi}/{len(big)}", flush=True)
        atom = set(members)
        work = deque()
        for m in members:
            for v in arm_of.get(m, []):
                p = var_def[v]
                if p >= 0:
                    work.append(p)
        cone: set[int] = set()
        overflowed = False
        while work and not overflowed:
            pnode = work.popleft()
            if pnode in atom or pnode in cone or claimed[pnode]:
                continue
            ok = True
            # every produced var of pnode: unpinned, all uses inside atom|cone
            lo, hi = src_starts[pnode], src_starts[pnode + 1]
            for k in range(lo, hi):
                v = int(prod_var[k])
                if var_pinned[v]:
                    ok = False; break
                ulo, uhi = var_starts[v], var_starts[v + 1]
                for u in range(ulo, uhi):
                    ud = int(use_dst[u])
                    if ud not in atom and ud not in cone:
                        ok = False; break
                if not ok:
                    break
            if not ok:
                continue
            cone.add(pnode)
            if len(cone) > MAXCONE:
                overflowed = True
                break
            lo, hi = dst_starts[pnode], dst_starts[pnode + 1]
            for k in range(lo, hi):
                q = var_def[int(op_var[k])]
                if q >= 0:
                    work.append(q)
        if overflowed:
            overflow += 1
            continue
        group_absorb_sizes.append(len(cone))
        for cap in CAPS:
            if len(cone) <= cap:
                absorbed_per_cap[cap] += len(cone)
        atom |= cone
        if MAXATOM and len(atom) > MAXATOM:
            continue  # giant atom: skip atomization entirely (activation cost)
        absorb_total += len(cone)
        atom_sizes.append(len(atom))
        mux_kept += len(members)
        for pnode in atom:
            claimed[pnode] = True
        # select absorbable?
        slo, shi = var_starts[sel], var_starts[sel + 1]
        if (var_def[sel] >= 0 and not var_pinned[sel] and
                all(int(use_dst[u]) in atom for u in range(slo, shi))):
            select_absorbable += 1
        # edge accounting via CSR (touching edges before, interface after)
        for pnode in atom:
            edge_before += (dst_starts[pnode + 1] - dst_starts[pnode]) + \
                           (src_starts[pnode + 1] - src_starts[pnode])
        iface_in = set()
        out_uses = 0
        for pnode in atom:
            lo, hi = dst_starts[pnode], dst_starts[pnode + 1]
            for k in range(lo, hi):
                if int(op_src[k]) not in atom:
                    iface_in.add((int(op_src[k]), int(op_var[k])))
            lo, hi = src_starts[pnode], src_starts[pnode + 1]
            for k in range(lo, hi):
                if int(prod_dst[k]) not in atom:
                    out_uses += 1
        edge_after += len(iface_in) + out_uses

    summary = {
        "compute_graph": str(COMPUTE),
        "mux_total": mux_count,
        "mux_with_select_identified": int(sizes.sum()),
        "select_groups": int(sizes.size),
        "group_size_distribution": {b: {"groups": dist.get(b, 0),
                                        "muxes": mux_in.get(b, 0)}
                                    for b in ("1", "2-3", "4-7", "8-15",
                                              "16-63", ">=64") if dist.get(b)},
        "groups_ge2_processed": len(big),
        "max_atom_threshold": MAXATOM,
        "atoms_kept": len(atom_sizes),
        "muxes_in_kept_atoms": mux_kept,
        "atoms_overflowing_cap256": overflow,
        "cone_nodes_absorbed_total": absorb_total,
        "cone_absorbed_per_cap": {str(c): absorbed_per_cap[c] for c in CAPS},
        "select_absorbable_groups": select_absorbable,
        "edges_touching_members_before": edge_before,
        "atom_interface_edges_after": edge_after,
        "cone_size_quantiles": np.quantile(group_absorb_sizes,
                                           [0.5, 0.9, 0.99]).tolist()
                                  if group_absorb_sizes else [],
        "atom_total_size_quantiles": np.quantile(atom_sizes,
                                                 [0.5, 0.9, 0.99, 1.0]).tolist()
                                     if atom_sizes else [],
        "atoms_over_512_nodes": int(sum(1 for s in atom_sizes if s > 512)),
        "atoms_over_2048_nodes": int(sum(1 for s in atom_sizes if s > 2048)),
    }
    print("\n== summary ==")
    text = json.dumps(summary, indent=2, ensure_ascii=False,
                      default=lambda o: int(o) if isinstance(o, np.integer)
                      else float(o))
    print(text)
    OUT.write_text(text)
    print(f"[out] {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
