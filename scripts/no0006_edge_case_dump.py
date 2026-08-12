#!/usr/bin/env python3
"""NO0006 edge-residual case dump: full local neighborhood for given node pairs.

For each requested gsim node id, prints:
  * gsim node record (opcode/width/name/type) + all in/out def_use edges
    (resolved to gsim_id + opcode + name);
  * the AM atom carrying that node_id: member instrs (id/opcode/width) and
    every def_use edge incident to those instrs, resolved to the other
    instr's opcode and its atom's node_id.
"""

import argparse
import json
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gsim-jsonl", required=True)
    parser.add_argument("--am-graph", required=True)
    parser.add_argument("--am-audit", required=True)
    parser.add_argument("--nodes", required=True, help="comma-separated gsim node ids")
    args = parser.parse_args()
    targets = {int(x) for x in args.nodes.split(",")}

    # ---- gsim side ----------------------------------------------------------
    dense_info = {}
    gid_to_dense = {}
    in_edges = {t: [] for t in targets}
    out_edges = {t: [] for t in targets}
    with open(args.gsim_jsonl) as handle:
        pending_edges = []
        for line in handle:
            if '"record":"node"' in line:
                rec = json.loads(line)
                gid = rec.get("gsim_id", rec["id"])
                dense_info[rec["id"]] = (gid, rec.get("opcode", "?"), rec.get("width", -1), rec.get("name", ""))
                if gid in targets:
                    gid_to_dense[gid] = rec["id"]
            elif '"kind":"def_use"' in line:
                pending_edges.append(line)
    target_dense = set(gid_to_dense.values())
    for line in pending_edges:
        rec = json.loads(line)
        src, dst = rec["src"], rec["dst"]
        if dst in target_dense or src in target_dense:
            sg = dense_info.get(src, (src, "?", 0, ""))
            dg = dense_info.get(dst, (dst, "?", 0, ""))
            if dst in target_dense:
                in_edges[dg[0]].append(sg)
            if src in target_dense:
                out_edges[sg[0]].append(dg)

    print("=== gsim side ===")
    for t in sorted(targets):
        info = next((v for v in dense_info.values() if v[0] == t), None)
        if info is None:
            print(f"node {t}: NOT FOUND")
            continue
        print(f"node {t} [{info[1]}/w{info[2]}] {info[3]}")
        for sg in sorted(in_edges[t]):
            print(f"    in : {sg[0]} [{sg[1]}/w{sg[2]}] {sg[3][:80]}")
        for dg in sorted(out_edges[t]):
            print(f"    out: {dg[0]} [{dg[1]}/w{dg[2]}] {dg[3][:80]}")

    # ---- AM side -------------------------------------------------------------
    node_to_atom = {}
    with open(args.am_audit) as handle:
        for line in handle:
            rec = json.loads(line)
            if rec["node_id"] in targets:
                node_to_atom[rec["node_id"]] = (rec["atom"], rec["kind"])
    target_atoms = {a for a, _ in node_to_atom.values()}
    atom_node = {}
    with open(args.am_audit) as handle:
        for line in handle:
            rec = json.loads(line)
            atom_node[rec["atom"]] = rec["node_id"]

    instr_info = {}
    atom_members = {a: [] for a in target_atoms}
    raw_edges = []
    with open(args.am_graph) as handle:
        for line in handle:
            if '"record":"node"' in line:
                rec = json.loads(line)
                if rec["atom"] in target_atoms:
                    instr_info[rec["id"]] = (rec.get("opcode", "?"), rec.get("width", -1), rec["atom"])
                    atom_members[rec["atom"]].append(rec["id"])
            elif '"kind":"def_use"' in line:
                raw_edges.append(line)
    member_set = set(instr_info)
    other_instr = {}
    incident = []
    for line in raw_edges:
        rec = json.loads(line)
        src, dst = rec["src"], rec["dst"]
        if src in member_set or dst in member_set:
            incident.append((src, dst))
    need = set()
    for src, dst in incident:
        if src not in member_set:
            need.add(src)
        if dst not in member_set:
            need.add(dst)
    with open(args.am_graph) as handle:
        for line in handle:
            if '"record":"node"' in line:
                rec = json.loads(line)
                if rec["id"] in need:
                    other_instr[rec["id"]] = (rec.get("opcode", "?"), rec.get("width", -1), rec["atom"])

    def fmt_instr(i):
        if i in instr_info:
            op, w, a = instr_info[i]
        else:
            op, w, a = other_instr.get(i, ("?", -1, -1))
        return f"instr{i}<{op}/w{w}>@atom{a}(node {atom_node.get(a, '?')})"

    print("\n=== AM side ===")
    for t in sorted(targets):
        if t not in node_to_atom:
            print(f"node {t}: no AM atom")
            continue
        atom, kind = node_to_atom[t]
        print(f"node {t} -> atom {atom} kind={kind} members={len(atom_members[atom])}")
        for i in sorted(atom_members[atom]):
            print(f"    member {fmt_instr(i)}")
        for src, dst in incident:
            sa = instr_info.get(src, other_instr.get(src, (0, 0, -1)))[2]
            da = instr_info.get(dst, other_instr.get(dst, (0, 0, -1)))[2]
            if sa == atom or da == atom:
                print(f"    edge {fmt_instr(src)} -> {fmt_instr(dst)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
