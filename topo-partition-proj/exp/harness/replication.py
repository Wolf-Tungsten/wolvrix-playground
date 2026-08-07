"""Offline replica of gsim's replicationOpt (reference/gsim/src/replication.cpp:59-122).

Semantics replicated (supernode-align sandbox, NO0013):

- repOpCount (Node::repOpCount, lines 28-57) on the flattened export, where
  every node is a single enode whose children are leaf node references:
    * type != NODE_OTHERS (gsim_type != 10)            -> -1 (never replicated)
    * root OP_WHEN (op 38)                             -> -1
    * root width > BASIC_WIDTH (256, common.h:68)      -> -1
    * CONSTANT (op 61) / no-tree (op 64 NONE)          -> 0
    * REF (op 60, root is a node reference)            -> 0 + opNum[referred]
    * otherwise                                        -> 1 + sum of opNum over
      def_use predecessors already marked replicable (transitive inlining,
      evaluated in topological = node id order)
- Replication decision (line 83): a node is replicated iff it is not a
  mustNode, op >= 0, op * outdeg < threadHold, and anyExtEdge() (some def_use
  successor in a different block). threadHold = 3 for members of singleton
  blocks, 0 otherwise — so ONLY singleton-block members can ever replicate
  (op*outdeg < 0 is impossible). outdeg is the def_use (src,dst)-deduped
  out-degree, matching Node::next.
- mustNodes (lines 64-77, array-index dependencies) cannot be recovered from
  the flat export (isArray / ExpTree semantics are gone); approximated as the
  EMPTY set and declared as a caliber difference.
- Application (lines 93-117): repNodes are processed in reverse collection
  order; each node's successors are grouped by successor block, a duplicate
  node is inserted into each successor block (prev->addNext(dup) chases values
  down replicated chains), consumers rewire to the local copy; the original
  node is deleted when no same-block successor remains (always, for singleton
  blocks) and its then-empty block is removed (removeNodesNoConnect ->
  removeEmptySuper). Duplicates re-read the original's external_read variables
  in their host block.

The replica operates on the flat arrays and returns the post-replication edge
set for rescoring. Node-level work is O(N); the dup bookkeeping only touches
replicated nodes (hundreds in practice).
"""

from __future__ import annotations

import numpy as np

NODE_OTHERS = 11  # NodeType enum, reference/gsim/include/Node.h:14-31
OP_WHEN = 38
OP_CONST = 61  # synthetic TOPO_PROJ_OP_CONST (topoProjExport.cpp:40)
OP_NONE = 64  # synthetic TOPO_PROJ_OP_NONE
OP_REF = 60  # synthetic TOPO_PROJ_OP_REF
BASIC_WIDTH = 256  # common.h:68 (NOT 64)
SINGLETON_THRESHOLD = 3  # replication.cpp:82


def compute_opnum(
    du_src: np.ndarray,
    du_dst: np.ndarray,
    op: np.ndarray,
    width: np.ndarray,
    gsim_type: np.ndarray,
) -> np.ndarray:
    """Per-node repOpCount; -1 = never replicable. Topo (id) order evaluation."""
    n = int(op.size)
    order = np.argsort(du_dst, kind="stable")
    prev_sorted = du_src[order].astype(np.int64)
    indeg = np.bincount(du_dst, minlength=n)
    off = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(indeg, out=off[1:])
    opnum = np.zeros(n, dtype=np.int64)
    for node in range(n):
        if gsim_type[node] != NODE_OTHERS or op[node] == OP_WHEN:
            opnum[node] = -1
            continue
        if op[node] == OP_CONST or op[node] == OP_NONE:
            continue  # op 0
        beg, end = off[node], off[node + 1]
        if op[node] == OP_REF:
            acc = 0
        else:
            if width[node] > BASIC_WIDTH:
                opnum[node] = -1
                continue
            acc = 1
        for p in prev_sorted[beg:end]:
            if opnum[p] >= 0:
                acc += opnum[p]
        opnum[node] = acc
    return opnum


def replicate(
    du_src: np.ndarray,
    du_dst: np.ndarray,
    du_var: np.ndarray,
    du_width: np.ndarray,
    er_dst: np.ndarray,
    er_var: np.ndarray,
    er_width: np.ndarray,
    op: np.ndarray,
    width: np.ndarray,
    state_write: np.ndarray,
    gsim_type: np.ndarray,
    instr_block: np.ndarray,
    n_blocks: int,
    n_variables: int,
    verbose: bool = False,
) -> dict:
    """Apply replicationOpt on the given block assignment.

    Returns the post-rep arrays (suffix ``_rep``) plus coverage/expansion
    statistics. Blocks keep their ids; empty blocks are reported via
    ``blocks_removed`` (metrics should use the dense ``instr_block_rep``
    remapping provided).
    """
    n = int(op.size)
    instr_block = instr_block.astype(np.int64)
    block_size = np.bincount(instr_block, minlength=n_blocks)

    # ---- pass 1: opNum + replication decision ------------------------------
    opnum = compute_opnum(du_src, du_dst, op, width, gsim_type)
    outdeg = np.bincount(du_src, minlength=n).astype(np.int64)
    singleton = block_size[instr_block] == 1
    can = singleton & (opnum >= 0) & (outdeg >= 1)
    coverage = {
        "singleton_blocks": int(singleton.sum()),
        "singleton_reject_type_or_when": int((singleton & (opnum < 0)).sum()),
        "singleton_reject_no_ext_edge": int((singleton & (opnum >= 0) & (outdeg == 0)).sum()),
        "singleton_reject_fanout": int(
            (can & (opnum * outdeg >= SINGLETON_THRESHOLD)).sum()
        ),
    }
    rep_mask = can & (opnum * outdeg < SINGLETON_THRESHOLD)
    rep_nodes = np.nonzero(rep_mask)[0]
    coverage["replicated_nodes"] = int(rep_nodes.size)

    # ---- pass 2: apply (reverse collection order) ---------------------------
    # successor lists per node (only materialized for nodes that need them)
    succ_offsets = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(np.bincount(du_src, minlength=n), out=succ_offsets[1:])
    succ_sorted = du_dst[np.argsort(du_src, kind="stable")].astype(np.int64)

    def successors(x: int) -> list:
        return succ_sorted[succ_offsets[x]:succ_offsets[x + 1]].tolist()

    prev_offsets = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(np.bincount(du_dst, minlength=n), out=prev_offsets[1:])
    prev_sorted = du_src[np.argsort(du_dst, kind="stable")].astype(np.int64)

    block_of = list(instr_block)
    next_add: dict[int, list] = {}  # node -> dup ids appended by addNext
    dup_block: list[int] = []
    dup_src_of: list[int] = []
    dup_consumers: list[list[int]] = []

    for node in rep_nodes[::-1].tolist():
        groups: dict[int, list[int]] = {}
        for c in successors(node):
            groups.setdefault(block_of[c], []).append(c)
        for d in next_add.get(node, ()):
            groups.setdefault(dup_block[d - n], []).append(d)
        for blk, consumers in groups.items():
            if blk == block_of[node]:
                continue  # remainNode case (never happens for singletons)
            dup_id = n + len(dup_block)
            dup_block.append(blk)
            dup_src_of.append(node)
            dup_consumers.append(consumers)
            for p in prev_sorted[prev_offsets[node]:prev_offsets[node + 1]].tolist():
                next_add.setdefault(int(p), []).append(dup_id)
    n_dups = len(dup_block)

    # ---- materialize the post-rep def_use edge set --------------------------
    alive = ~rep_mask  # every replicated singleton has no same-block successor
    edges_s: list[int] = []
    edges_d: list[int] = []
    edges_v: list[int] = []
    edges_w: list[int] = []
    # (a) untouched original edges
    keep = alive[du_src.astype(np.int64)] & alive[du_dst.astype(np.int64)]
    edges_s.append(du_src[keep].astype(np.int64))
    edges_d.append(du_dst[keep].astype(np.int64))
    edges_v.append(du_var[keep].astype(np.int64))
    edges_w.append(du_width[keep].astype(np.int64))
    # (b) dup -> consumer edges (consumers may be dups or alive originals)
    d_s: list[int] = []
    d_d: list[int] = []
    d_v: list[int] = []
    d_w: list[int] = []
    for k in range(n_dups):
        src_node = dup_src_of[k]
        dup_id = n + k
        var = n_variables + k
        w = int(width[src_node])
        for c in dup_consumers[k]:
            if c < n and not alive[c]:
                continue  # consumer was itself replicated away; its dups re-add
            d_s.append(dup_id)
            d_d.append(c)
            d_v.append(var)
            d_w.append(w)
    # (c) producer -> dup edges (gsim var == producer node id on this export)
    for p, dups in next_add.items():
        if not alive[p]:
            continue  # replicated producers re-add via their own dup grouping
        w = int(width[p])
        for dup_id in dups:
            d_s.append(int(p))
            d_d.append(dup_id)
            d_v.append(int(p))
            d_w.append(w)
    edges_s.append(np.array(d_s, dtype=np.int64))
    edges_d.append(np.array(d_d, dtype=np.int64))
    edges_v.append(np.array(d_v, dtype=np.int64))
    edges_w.append(np.array(d_w, dtype=np.int64))

    # er edges: dups re-read the source node's external variables
    er_of_node_offsets = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(np.bincount(er_dst, minlength=n), out=er_of_node_offsets[1:])
    er_sorted_idx = np.argsort(er_dst, kind="stable")
    er_var_sorted = er_var[er_sorted_idx].astype(np.int64)
    er_w_sorted = er_width[er_sorted_idx].astype(np.int64)
    e_d: list[int] = []
    e_v: list[int] = []
    e_w: list[int] = []
    for k in range(n_dups):
        src_node = dup_src_of[k]
        beg, end = er_of_node_offsets[src_node], er_of_node_offsets[src_node + 1]
        for i in range(beg, end):
            e_d.append(n + k)
            e_v.append(int(er_var_sorted[i]))
            e_w.append(int(er_w_sorted[i]))
    er_dst2 = np.concatenate([er_dst.astype(np.int64), np.array(e_d, dtype=np.int64)])
    er_var2 = np.concatenate([er_var.astype(np.int64), np.array(e_v, dtype=np.int64)])
    er_width2 = np.concatenate([er_width.astype(np.int64), np.array(e_w, dtype=np.int64)])

    # node-level arrays: dead originals keep their slot (block kept, no edges)
    n2 = n + n_dups
    instr_block2 = np.concatenate([instr_block, np.array(dup_block, dtype=np.int64)])
    state_write2 = np.concatenate([state_write, np.zeros(n_dups, dtype=bool)])

    # blocks after: singletons whose member was replicated away and that
    # received no dup become empty (removeEmptySuper)
    dup_per_block = np.bincount(np.array(dup_block, dtype=np.int64), minlength=n_blocks)
    rep_per_block = np.bincount(instr_block[rep_nodes], minlength=n_blocks)
    members_after = block_size + dup_per_block - rep_per_block
    blocks_after = int((members_after > 0).sum())

    return {
        "du_src": np.concatenate(edges_s),
        "du_dst": np.concatenate(edges_d),
        "du_var": np.concatenate(edges_v),
        "du_width": np.concatenate(edges_w).astype(np.int32),
        "er_dst": er_dst2,
        "er_var": er_var2,
        "er_width": er_width2.astype(np.int32),
        "instr_block": instr_block2,
        "state_write": state_write2,
        "n_nodes": n2,
        "coverage": coverage,
        "dup_nodes": n_dups,
        "replicated_nodes": int(rep_nodes.size),
        "nodes_before": n,
        "nodes_after": int(n - rep_nodes.size + n_dups),
        "blocks_before": int(n_blocks),
        "blocks_after": blocks_after,
        "dups_per_replicated": round(n_dups / max(rep_nodes.size, 1), 2),
    }
