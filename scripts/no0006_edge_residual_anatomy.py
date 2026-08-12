#!/usr/bin/env python3
"""NO0006 edge-residual anatomy: what ARE the AM-only / gsim-only edges?

Reconciles gsim node-DAG edges against AM atom-DAG edges in the gsim
node-id space (same method as no0006_edge_reconcile.py), then dissects
the residuals:

  * opcode-pair histograms (gsim node opcode space) for AM-only and
    gsim-only edges;
  * 2-hop analysis: for an AM-only edge (u,v) does gsim have a path
    u->w->v? If so, what opcode is w (glue bypass detection)?
    Symmetric check for gsim-only edges against the AM graph.
  * witness AM instruction opcodes for AM-only edges (which instr kind
    consumes the cross-atom value that gsim does not wire directly).

Inputs are the NO0006 dumps under build/logs/no0006/.
"""

import argparse
import array
import collections
import json
import sys


def encode(u, v):
    return (u << 32) | v


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gsim-jsonl", required=True)
    parser.add_argument("--am-graph", required=True)
    parser.add_argument("--am-audit", required=True)
    parser.add_argument("--samples", type=int, default=12)
    args = parser.parse_args()

    # ---- Pass 1: gsim graph ------------------------------------------------
    dense_to_gsim = {}
    node_op = {}
    node_width = {}
    node_name = {}
    node_type = {}
    gsim_edges = set()
    with open(args.gsim_jsonl) as handle:
        for line in handle:
            if '"record":"node"' in line:
                rec = json.loads(line)
                gid = rec.get("gsim_id", rec["id"])
                dense_to_gsim[rec["id"]] = gid
                node_op[gid] = rec.get("opcode", "?")
                node_width[gid] = rec.get("width", -1)
                node_name[gid] = rec.get("name", "")
                node_type[gid] = rec.get("gsim_type", -1)
            elif '"kind":"def_use"' in line:
                rec = json.loads(line)
                if rec["src"] != rec["dst"]:
                    gsim_edges.add((rec["src"], rec["dst"]))
    # resolve dense -> gsim id space, keep dense adjacency for 2-hop later
    fwd = collections.defaultdict(list)
    gsim_edge_ids = set()
    for src, dst in gsim_edges:
        gs, gd = dense_to_gsim[src], dense_to_gsim[dst]
        if gs == gd:
            continue
        gsim_edge_ids.add(encode(gs, gd))
        fwd[gs].append(gd)
    del gsim_edges
    print(f"gsim nodes={len(node_op)} edges={len(gsim_edge_ids)}", flush=True)

    # ---- Pass 2: AM audit (atom -> node_id) --------------------------------
    atom_node = {}
    atom_commit = {}
    with open(args.am_audit) as handle:
        for line in handle:
            rec = json.loads(line)
            atom_node[rec["atom"]] = rec["node_id"]
            atom_commit[rec["atom"]] = rec["kind"] == "CommitEvent"
    print(f"am atoms={len(atom_node)}", flush=True)

    # ---- Pass 3: AM graph (nodes then buffered edges) ----------------------
    instr_atom = {}
    instr_op = {}
    raw_edges = array.array("Q")
    with open(args.am_graph) as handle:
        for line in handle:
            if '"record":"node"' in line:
                rec = json.loads(line)
                instr_atom[rec["id"]] = rec["atom"]
                instr_op[rec["id"]] = rec.get("opcode", "?")
            elif '"kind":"def_use"' in line:
                rec = json.loads(line)
                raw_edges.append(rec["src"])
                raw_edges.append(rec["dst"])
    print(f"am instrs={len(instr_atom)} raw_edges={len(raw_edges)//2}", flush=True)

    am_edge_ids = set()
    am_only_witness = {}
    aux = 0
    for i in range(0, len(raw_edges), 2):
        src, dst = raw_edges[i], raw_edges[i + 1]
        sa, da = instr_atom[src], instr_atom[dst]
        if sa == da:
            continue
        sn, dn = atom_node[sa], atom_node[da]
        if sn < 0 or dn < 0 or atom_commit[sa] or atom_commit[da]:
            aux += 1
            continue
        key = encode(sn, dn)
        am_edge_ids.add(key)
        if key not in gsim_edge_ids and key not in am_only_witness:
            am_only_witness[key] = (src, dst)
    del raw_edges, instr_atom
    print(f"am aligned edges={len(am_edge_ids)} aux_excluded={aux}", flush=True)

    am_only = am_edge_ids - gsim_edge_ids
    gsim_only = gsim_edge_ids - am_edge_ids
    both = am_edge_ids & gsim_edge_ids
    print(f"intersection={len(both)} am_only={len(am_only)} gsim_only={len(gsim_only)}", flush=True)

    def decode(key):
        return key >> 32, key & 0xFFFFFFFF

    # ---- opcode-pair histograms --------------------------------------------
    for label, keys in (("AM-only", am_only), ("gsim-only", gsim_only)):
        hist = collections.Counter()
        for key in keys:
            u, v = decode(key)
            hist[(node_op.get(u, "?"), node_op.get(v, "?"))] += 1
        print(f"\n{label} opcode-pair histogram (top 20):")
        for (uo, vo), cnt in hist.most_common(20):
            print(f"  {uo:<14} -> {vo:<14} : {cnt}")

    # ---- 2-hop analysis ------------------------------------------------------
    # AM-only (u,v): gsim path u->w->v ?
    twohop_w = collections.Counter()
    twohop_pairs = collections.Counter()
    nohop = 0
    for key in am_only:
        u, v = decode(key)
        hit = None
        for w in fwd.get(u, ()):  # u 的 gsim 直接后继
            if encode(w, v) in gsim_edge_ids:
                hit = w
                break
        if hit is None:
            nohop += 1
        else:
            twohop_w[node_op.get(hit, "?")] += 1
            twohop_pairs[(node_op.get(u, "?"), node_op.get(hit, "?"), node_op.get(v, "?"))] += 1
    print(f"\nAM-only with gsim 2-hop u->w->v: {sum(twohop_w.values())} / {len(am_only)} (no-hop {nohop})")
    print("intermediate w opcode histogram (top 15):")
    for op, cnt in twohop_w.most_common(15):
        print(f"  {op:<14} : {cnt}")
    print("(u_op, w_op, v_op) triples (top 15):")
    for triple, cnt in twohop_pairs.most_common(15):
        print(f"  {' -> '.join(triple):<44} : {cnt}")

    # gsim-only (u,v): AM path u->w->v ? (build AM forward adjacency)
    am_fwd = collections.defaultdict(list)
    for key in am_edge_ids:
        u, v = decode(key)
        am_fwd[u].append(v)
    g_twohop_w = collections.Counter()
    g_twohop_pairs = collections.Counter()
    g_nohop = 0
    for key in gsim_only:
        u, v = decode(key)
        hit = None
        for w in am_fwd.get(u, ()):
            if encode(w, v) in am_edge_ids:
                hit = w
                break
        if hit is None:
            g_nohop += 1
        else:
            g_twohop_w[node_op.get(hit, "?")] += 1
            g_twohop_pairs[(node_op.get(u, "?"), node_op.get(hit, "?"), node_op.get(v, "?"))] += 1
    print(f"\ngsim-only with AM 2-hop u->w->v: {sum(g_twohop_w.values())} / {len(gsim_only)} (no-hop {g_nohop})")
    print("intermediate w opcode histogram (top 15):")
    for op, cnt in g_twohop_w.most_common(15):
        print(f"  {op:<14} : {cnt}")
    print("(u_op, w_op, v_op) triples (top 15):")
    for triple, cnt in g_twohop_pairs.most_common(15):
        print(f"  {' -> '.join(triple):<44} : {cnt}")

    # ---- AM-only witness instr opcodes --------------------------------------
    wit_hist = collections.Counter()
    for key, (si, di) in am_only_witness.items():
        wit_hist[(instr_op.get(si, "?"), instr_op.get(di, "?"))] += 1
    print("\nAM-only witness instr opcode pairs (top 20):")
    for (so, do), cnt in wit_hist.most_common(20):
        print(f"  {so:<16} -> {do:<16} : {cnt}")

    # ---- samples -------------------------------------------------------------
    def fmt(n):
        return f"{n}[{node_op.get(n,'?')}/w{node_width.get(n,'?')}] {node_name.get(n,'')[:70]}"

    print("\nAM-only samples:")
    for key in list(am_only)[: args.samples]:
        u, v = decode(key)
        wit = am_only_witness.get(key)
        wops = f" am_instr={instr_op.get(wit[0],'?')}->{instr_op.get(wit[1],'?')}" if wit else ""
        print(f"  {fmt(u)}  ==>  {fmt(v)}{wops}")
    print("\ngsim-only samples:")
    for key in list(gsim_only)[: args.samples]:
        u, v = decode(key)
        print(f"  {fmt(u)}  ==>  {fmt(v)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
