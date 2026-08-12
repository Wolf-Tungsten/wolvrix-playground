#!/usr/bin/env python3
"""Fanout (out-degree) distribution: gsim node-DAG vs AM atom-DAG.

Same projection as no0006_edge_reconcile.py (gsim node-id space, directed,
deduped; AM restricted to node-mapped, non-CommitEvent atoms), then computes
per-unit out-degree distributions on both sides and prints bucket histograms
plus percentiles. Universe: gsim = all nodes in the topoProj dump; AM = all
node-mapped compute atoms (by node_id).
"""

import argparse
import json


def load_gsim(path):
    dense_to_gsim = {}
    edges = set()
    with open(path) as handle:
        for line in handle:
            if '"record":"node"' in line:
                record = json.loads(line)
                dense_to_gsim[record["id"]] = record.get("gsim_id", record["id"])
            elif '"kind":"def_use"' in line:
                record = json.loads(line)
                edges.add((record["src"], record["dst"]))
    mapped = set()
    for src, dst in edges:
        if src == dst:
            continue
        mapped.add((dense_to_gsim[src], dense_to_gsim[dst]))
    return mapped, set(dense_to_gsim.values())


def load_am(graph_path, audit_path):
    atom_node = {}
    atom_commit = {}
    with open(audit_path) as handle:
        for line in handle:
            record = json.loads(line)
            atom_node[record["atom"]] = record["node_id"]
            atom_commit[record["atom"]] = record["kind"] == "CommitEvent"
    instr_atom = {}
    raw_edges = []
    with open(graph_path) as handle:
        for line in handle:
            if '"record":"node"' in line:
                record = json.loads(line)
                instr_atom[record["id"]] = record["atom"]
            elif '"kind":"def_use"' in line:
                record = json.loads(line)
                raw_edges.append((record["src"], record["dst"]))
    aligned = set()
    for src, dst in raw_edges:
        src_atom = instr_atom[src]
        dst_atom = instr_atom[dst]
        if src_atom == dst_atom:
            continue
        src_node = atom_node[src_atom]
        dst_node = atom_node[dst_atom]
        if src_node < 0 or dst_node < 0 or atom_commit[src_atom] or atom_commit[dst_atom]:
            continue
        aligned.add((src_node, dst_node))
    universe = {node for node, commit in zip(atom_node.values(), atom_commit.values())
                if node >= 0 and not commit}
    return aligned, universe


BUCKETS = [(0, 0), (1, 1), (2, 2), (3, 3), (4, 7), (8, 15), (16, 63), (64, 1 << 62)]
LABELS = ["0", "1", "2", "3", "4-7", "8-15", "16-63", ">=64"]


def report(name, edges, universe):
    outdeg = {}
    for src, _ in edges:
        outdeg[src] = outdeg.get(src, 0) + 1
    counts = [0] * len(BUCKETS)
    degrees = []
    for unit in universe:
        deg = outdeg.get(unit, 0)
        degrees.append(deg)
        for index, (lo, hi) in enumerate(BUCKETS):
            if lo <= deg <= hi:
                counts[index] += 1
                break
    degrees.sort()
    total = len(degrees)
    pct = lambda q: degrees[min(total - 1, int(total * q))] if total else 0
    mean = sum(degrees) / total if total else 0.0
    print(f"{name}: units={total} edges={len(edges)}")
    print(f"  outdeg histogram: " + " ".join(f"{label}={count}" for label, count in zip(LABELS, counts)))
    print(f"  density(fanout>=2)={100.0 * sum(counts[2:]) / total:.1f}% "
          f"mean={mean:.3f} p50={pct(0.5)} p90={pct(0.9)} p99={pct(0.99)} max={degrees[-1] if total else 0}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gsim-graph", required=True)
    parser.add_argument("--am-graph", required=True)
    parser.add_argument("--am-audit", required=True)
    args = parser.parse_args()

    gsim_edges, gsim_universe = load_gsim(args.gsim_graph)
    am_edges, am_universe = load_am(args.am_graph, args.am_audit)
    report("gsim node-DAG", gsim_edges, gsim_universe)
    report("AM atom-DAG (node-mapped compute)", am_edges, am_universe)


if __name__ == "__main__":
    main()
