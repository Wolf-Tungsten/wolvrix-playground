#!/usr/bin/env python3
"""NO0006 edge reconciliation: gsim node-DAG edges vs AM atom-DAG edges.

Projects both sides into the gsim node-id space and compares the directed
node-pair sets:

  * gsim: def_use edges (src/dst are dense topoProj ids, mapped through the
    node record's gsim_id), self-loops dropped, deduped.
  * AM: instruction-level def_use edges projected through instruction->atom
    (graph dump) and atom->node_id (node-atom audit). Edges touching unowned
    (node_id<0) or CommitEvent atoms are classified as AM clock-domain
   附加层 and excluded from the aligned set; self loops dropped; deduped.

Reports |intersection|, |AM-only|, |gsim-only| and per-endpoint-type
histograms for the residuals.
"""

import argparse
import collections
import json
import sys

NODE_TYPE_NAMES = {
    0: "INVALID", 1: "REG_SRC", 2: "REG_DST", 3: "SPECIAL", 4: "INP",
    5: "OUT", 6: "MEMORY", 7: "READER", 8: "WRITER", 9: "READWRITER",
    10: "INFER", 11: "OTHERS", 12: "REG_RESET", 13: "EXT_IN",
    14: "EXT_OUT", 15: "EXT", -1: "<none>",
}


def load_gsim(path):
    dense_to_gsim = {}
    node_type = {}
    edges = set()
    with open(path) as handle:
        for line in handle:
            if '"record":"node"' in line:
                record = json.loads(line)
                gsim_id = record.get("gsim_id", record["id"])
                dense_to_gsim[record["id"]] = gsim_id
                node_type[gsim_id] = record.get("gsim_type", -1)
            elif '"kind":"def_use"' in line:
                record = json.loads(line)
                edges.add((record["src"], record["dst"]))
    mapped = set()
    for src, dst in edges:
        if src == dst:
            continue
        mapped.add((dense_to_gsim[src], dense_to_gsim[dst]))
    return mapped, node_type


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
    aux = 0
    for src, dst in raw_edges:
        src_atom = instr_atom[src]
        dst_atom = instr_atom[dst]
        if src_atom == dst_atom:
            continue
        src_node = atom_node[src_atom]
        dst_node = atom_node[dst_atom]
        if src_node < 0 or dst_node < 0 or atom_commit[src_atom] or atom_commit[dst_atom]:
            aux += 1
            continue
        aligned.add((src_node, dst_node))
    return aligned, aux


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gsim-jsonl", required=True)
    parser.add_argument("--am-graph", required=True)
    parser.add_argument("--am-audit", required=True)
    parser.add_argument("--samples", type=int, default=8)
    args = parser.parse_args()

    gsim_edges, node_type = load_gsim(args.gsim_jsonl)
    am_edges, aux_edges = load_am(args.am_graph, args.am_audit)

    both = am_edges & gsim_edges
    am_only = am_edges - gsim_edges
    gsim_only = gsim_edges - am_edges

    print("== NO0006 edge reconciliation (node-id space, directed, deduped) ==")
    print(f"gsim node-DAG def_use edges: {len(gsim_edges)}")
    print(f"AM atom-DAG def_use edges (node-mapped, compute-only): {len(am_edges)}")
    print(f"AM edges excluded as clock-domain附加层 (commit/unowned endpoint): {aux_edges}")
    print(f"intersection: {len(both)}")
    print(f"AM-only: {len(am_only)}")
    print(f"gsim-only: {len(gsim_only)}")
    if gsim_edges:
        print(f"edge recall (intersection / gsim): {len(both)/len(gsim_edges):.4f}")
    if am_edges:
        print(f"edge precision (intersection / AM): {len(both)/len(am_edges):.4f}")

    def type_hist(pairs):
        hist = collections.Counter()
        for src, dst in pairs:
            hist[(node_type.get(src, -1), node_type.get(dst, -1))] += 1
        return hist

    for label, pairs in (("AM-only", am_only), ("gsim-only", gsim_only)):
        print(f"\n{label} endpoint-type histogram (src_type -> dst_type : count):")
        for (src_type, dst_type), count in type_hist(pairs).most_common(12):
            print(f"  {NODE_TYPE_NAMES.get(src_type):<10} -> {NODE_TYPE_NAMES.get(dst_type):<10} : {count}")
        print(f"{label} samples: {list(pairs)[:args.samples]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
