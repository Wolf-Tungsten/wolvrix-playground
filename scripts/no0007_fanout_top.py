#!/usr/bin/env python3
"""Top-fanout units on both sides (same projection as no0007_fanout_compare)."""

import argparse
import collections
import json


def load_gsim(path):
    dense_to_gsim = {}
    names = {}
    edges = set()
    with open(path) as handle:
        for line in handle:
            if '"record":"node"' in line:
                record = json.loads(line)
                gsim_id = record.get("gsim_id", record["id"])
                dense_to_gsim[record["id"]] = gsim_id
                names[gsim_id] = record.get("name", "")
            elif '"kind":"def_use"' in line:
                record = json.loads(line)
                edges.add((record["src"], record["dst"]))
    outdeg = collections.Counter()
    for src, dst in edges:
        if src == dst:
            continue
        outdeg[(dense_to_gsim[src], dense_to_gsim[dst])] += 0  # dedup via set below
    pairs = {(dense_to_gsim[src], dense_to_gsim[dst]) for src, dst in edges if src != dst}
    outdeg = collections.Counter(src for src, _ in pairs)
    return outdeg, names


def load_am(graph_path, audit_path):
    atom_node = {}
    atom_commit = {}
    with open(audit_path) as handle:
        for line in handle:
            record = json.loads(line)
            atom_node[record["atom"]] = record["node_id"]
            atom_commit[record["atom"]] = record["kind"] == "CommitEvent"
    instr_atom = {}
    raw = []
    with open(graph_path) as handle:
        for line in handle:
            if '"record":"node"' in line:
                record = json.loads(line)
                instr_atom[record["id"]] = record["atom"]
            elif '"kind":"def_use"' in line:
                record = json.loads(line)
                raw.append((record["src"], record["dst"]))
    pairs = set()
    for src, dst in raw:
        sa, da = instr_atom[src], instr_atom[dst]
        if sa == da:
            continue
        sn, dn = atom_node[sa], atom_node[da]
        if sn < 0 or dn < 0 or atom_commit[sa] or atom_commit[da]:
            continue
        pairs.add((sn, dn))
    return collections.Counter(src for src, _ in pairs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gsim-graph", required=True)
    parser.add_argument("--am-graph", required=True)
    parser.add_argument("--am-audit", required=True)
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    gsim_deg, names = load_gsim(args.gsim_graph)
    am_deg = load_am(args.am_graph, args.am_audit)

    print("== gsim top fanout ==")
    for node, deg in gsim_deg.most_common(args.top):
        print(f"  {deg:>7}  node {node}  {names.get(node, '?')[:100]}")
    print("== AM top fanout ==")
    for node, deg in am_deg.most_common(args.top):
        print(f"  {deg:>7}  node {node}  {names.get(node, '?')[:100]}")


if __name__ == "__main__":
    main()
