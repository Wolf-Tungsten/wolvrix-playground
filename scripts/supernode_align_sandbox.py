#!/usr/bin/env python3

"""Coarsen-rule sandbox for the supernode-align topic.

Runs the offline replica (topo-partition-proj/exp/harness/amcoarsen.py) of the
AM coarsen on an exported instruction graph, packs blocks greedily, and scores
the result with the same metrics as scripts/supernode_align_metrics.py
(cross_values primary). Used to A/B merge-rule changes without recompiling
the C++ scheduler; see pdocs/grh-notepad/supernode-align/NO0003.

Usage:
    supernode_align_sandbox.py <instruction_graph.jsonl> \
        [--mode rotate|sequential[:N]] [--budget N] [--max-instructions N] \
        [--dump-assignment OUT.jsonl]

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
    parser.add_argument("--mode", default="rotate")
    parser.add_argument("--passes", default="Out1+In1+Sibling",
                        help="pass order, +-separated (Out1/In1/Sibling/PrevSibling)")
    parser.add_argument("--budget", type=int, default=192)
    parser.add_argument("--max-instructions", type=int, default=128)
    parser.add_argument("--max-iters", type=int, default=256)
    parser.add_argument("--replicate", action="store_true",
                        help="post-coarsen replication pass (duplicate replicable producers into consuming blocks)")
    parser.add_argument("--replicate-tier", type=int, default=1, choices=[1, 2],
                        help="tier 1: operands must be block-local/const; tier 2: operands may already cross into the block")
    parser.add_argument("--include-state", action="store_true",
                        help="let state_write atoms participate in coarsen (gsim parity; default excludes them as AM commit atoms)")
    parser.add_argument("--dump-assignment", type=Path)
    args = parser.parse_args()

    started = time.time()
    graph = load_graph(args.graph, use_cache=True, verbose=False)
    atom_of = graph.atom.astype(np.int64)
    n = int(atom_of.max() + 1)
    active = np.ones(n, dtype=bool)
    if not args.include_state:
        active[atom_of[graph.state_write]] = False  # commit atoms stay out of coarsen

    src = atom_of[np.concatenate([graph.du_src, graph.ord_src]).astype(np.int64)]
    dst = atom_of[np.concatenate([graph.du_dst, graph.ord_dst]).astype(np.int64)]
    keep = (src != dst)
    pairs = np.unique((src[keep] << 32) | dst[keep])
    esrc = (pairs >> 32).astype(np.int64)
    edst = (pairs & 0xFFFFFFFF).astype(np.int64)

    # atom weights = instructions per atom (singletons for acyclic atoms)
    weights = np.bincount(atom_of, minlength=n).astype(np.int64)
    oversized = weights > args.max_instructions
    print(f"[load] atoms={n} edges={esrc.size} oversized_atoms={int(oversized.sum())} "
          f"({time.time() - started:.0f}s)")

    # MuxCond input: mux atom -> select-condition producer atom. The JSONL
    # export does not preserve operand order, so the select operand is
    # identified by the kMux 1-bit-condition rule (width==1 operand).
    mux_op_ids = [i for i, name in enumerate(graph.opcode_names) if name == "mux"]
    mux_select = np.full(n, -1, dtype=np.int64)
    if mux_op_ids:
        is_mux = np.isin(graph.op, mux_op_ids)
        dst_idx = np.argsort(graph.du_dst, kind="stable")
        d_sorted = graph.du_dst[dst_idx]
        v_sorted = graph.du_var[dst_idx]
        w_sorted = graph.du_width[dst_idx]
        bounds = np.searchsorted(d_sorted, np.arange(graph.instructions + 1))
        var_def = graph.var_def()
        mux_instr = np.nonzero(is_mux)[0]
        picked = 0
        for m in mux_instr.tolist():
            lo, hi = bounds[m], bounds[m + 1]
            ops = v_sorted[lo:hi]
            one_bit = ops[w_sorted[lo:hi] == 1]
            if one_bit.size != 1:
                continue  # ambiguous or missing select; skip
            producer = var_def[one_bit[0]]
            if producer < 0:
                continue
            mux_select[atom_of[m]] = atom_of[producer]
            picked += 1
        print(f"[load] mux atoms with identified select: {picked} / {mux_instr.size}")

    result = coarsen(
        esrc,
        edst,
        n,
        active,
        budget=args.budget,
        oversized_weight=oversized,
        mode=args.mode,
        max_iters=args.max_iters,
        weights=weights,
        pass_order=tuple(args.passes.split("+")),
        mux_select=mux_select,
    )
    print(f"[coarsen] mode={args.mode} budget={args.budget} rounds={result.rounds} "
          f"merges={result.merges} ({time.time() - started:.0f}s)")

    block_of_atom = cluster_blocks(
        result.parent, esrc, edst, active, weights, args.max_instructions
    )
    instr_block = block_of_atom[atom_of].astype(np.int64)
    # commit instructions: keep them out (their own commit blocks in production);
    # for cross_values parity with the metrics script, give them unique blocks
    # after the compute range so producer->commit always crosses.
    commit_instr = block_of_atom[atom_of] < 0
    next_block = instr_block.max() + 1
    instr_block[commit_instr] = next_block
    print(f"[pack] compute_blocks={int(next_block)} ({time.time() - started:.0f}s)")

    pb = instr_block[graph.du_src.astype(np.int64)]
    cb = instr_block[graph.du_dst.astype(np.int64)]
    cross = pb != cb
    cross_values = int(np.unique(graph.du_var[cross]).size)
    dag_keys = np.unique((pb[cross] << 32) | cb[cross])
    print(f"[score] cross_values={cross_values} dag_edges={dag_keys.size} "
          f"cross_edges={int(cross.sum())} ({time.time() - started:.0f}s)")

    if args.replicate:
        # Post-coarsen replication: duplicate a producer instruction into every
        # consuming compute block when all of its operands are available there
        # (defined in that block or constant/no-def). Replicated results become
        # block-local; commit-block consumers still cross. Iterates to a
        # fixpoint (replicas can make further producers replicable).
        var_def = graph.var_def()
        dst_idx = np.argsort(graph.du_dst, kind="stable")
        d_sorted = graph.du_dst[dst_idx]
        v_sorted = graph.du_var[dst_idx]
        bounds = np.searchsorted(d_sorted, np.arange(graph.instructions + 1))
        replicated = np.zeros(graph.instructions, dtype=bool)
        total_replicas = 0
        commit_block = next_block
        for rnd in range(20):
            pb = instr_block[graph.du_src.astype(np.int64)]
            cb = instr_block[graph.du_dst.astype(np.int64)]
            # edges already neutralized by a replica: var's producer replicated
            # and consumer in a compute block
            src_repl = replicated[graph.du_src.astype(np.int64)]
            cross = (pb != cb) & ~(src_repl & (cb != commit_block))
            cmask = cross & (cb != commit_block)
            pairs = np.unique((graph.du_var[cmask].astype(np.int64) << 32) | cb[cmask])
            if pairs.size == 0:
                print(f"[replicate] round {rnd}: fixpoint")
                break
            pv = (pairs >> 32).astype(np.int64)
            pblk = (pairs & 0xFFFFFFFF).astype(np.int64)
            prod = var_def[pv]
            ok = prod >= 0
            pv, pblk, prod = pv[ok], pblk[ok], prod[ok]
            order = np.argsort(prod, kind="stable")
            sp, sv, sb = prod[order], pv[order], pblk[order]
            uprod, starts_arr = np.unique(sp, return_index=True)
            ends_arr = np.append(starts_arr[1:], sp.size)
            # tier 2: (var, block) pairs that already cross this round
            already_cross = set()
            if args.replicate_tier == 2:
                already_cross = set(pairs.tolist())
            round_replicated = 0
            round_replicas = 0
            for i in range(uprod.size):
                P = int(uprod[i])
                if replicated[P]:
                    continue
                ops = v_sorted[bounds[P]:bounds[P + 1]]
                op_def = var_def[ops]
                op_blk = np.where(op_def >= 0, instr_block[np.maximum(op_def, 0)], -1)
                op_const = op_def < 0
                blocks = np.unique(sb[starts_arr[i]:ends_arr[i]])
                good = True
                for B in blocks.tolist():
                    ok = (op_blk == B) | op_const
                    if args.replicate_tier == 2 and not ok.all():
                        ok |= np.array(
                            [((int(u) << 32) | B) in already_cross for u in ops.tolist()]
                        )
                    if not ok.all():
                        good = False
                        break
                if not good:
                    continue
                replicated[P] = True
                round_replicated += 1
                own = instr_block[P]
                round_replicas += int((blocks != own).sum())
            total_replicas += round_replicas
            print(f"[replicate] round {rnd}: producers={round_replicated} "
                  f"replica_instructions={round_replicas} ({time.time() - started:.0f}s)")
            if round_replicated == 0:
                break
        src_repl = replicated[graph.du_src.astype(np.int64)]
        cross = (pb != cb) & ~(src_repl & (cb != commit_block))
        rep_cross_values = int(np.unique(graph.du_var[cross]).size)
        dag_keys = np.unique((pb[cross] << 32) | cb[cross])
        print(f"[replicate] total_producers={int(replicated.sum())} "
              f"total_replica_instructions={total_replicas}")
        print(f"[score-after-replicate] cross_values={rep_cross_values} "
              f"dag_edges={dag_keys.size} (before={cross_values})")

    if args.dump_assignment is not None:
        args.dump_assignment.parent.mkdir(parents=True, exist_ok=True)
        with args.dump_assignment.open("w", encoding="utf-8") as out:
            out.write('{"record":"header","format":"wolvrix.am-block-assignment.v1",'
                      f'"sandbox":true,"mode":"{args.mode}","budget":{args.budget},'
                      f'"max_instructions":{args.max_instructions},'
                      f'"instructions":{graph.instructions},"blocks":{int(next_block) + 1}}}\n')
            for block in range(int(next_block) + 1):
                out.write(f'{{"record":"block","id":{block},"kind":"compute","size":0}}\n')
            for instr, block in enumerate(instr_block.tolist()):
                out.write(f'{{"record":"assign","instr":{instr},"block":{block}}}\n')
        print(f"[dump] wrote {args.dump_assignment}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
