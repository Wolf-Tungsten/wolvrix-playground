#!/usr/bin/env python3
"""NO0006 L2 reconciliation: gsim flatten-graph nodes vs AM node-aligned atoms.

Inputs:
  --gsim-jsonl  topoProj per-node dump of the gsim flatten graph
                (record=="node" lines carry id + gsim_type).
  --am-audit    AM node-atom audit JSONL written by
                WOLVRIX_GRHSIM_AM_NODE_ATOM_AUDIT_JSONL
                (one line per atom: atom/node_id/kind/instructions/multi_sink).

Reports the per-node-type bijection table: gsim node census, AM node-mapped
compute atoms, nodes with no compute atom, nodes with >1 compute atom, and
the unowned (AM clock-domain helper) atom histogram.
"""

import argparse
import collections
import json
import sys

NODE_TYPE_NAMES = {
    0: "INVALID", 1: "REG_SRC", 2: "REG_DST", 3: "SPECIAL", 4: "INP",
    5: "OUT", 6: "MEMORY", 7: "READER", 8: "WRITER", 9: "READWRITER",
    10: "INFER", 11: "OTHERS", 12: "REG_RESET", 13: "EXT_IN",
    14: "EXT_OUT", 15: "EXT",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gsim-jsonl", required=True)
    parser.add_argument("--am-audit", required=True)
    parser.add_argument("--top-missing", type=int, default=0,
                        help="print up to N sample node ids missing an atom")
    args = parser.parse_args()

    gsim_type = {}
    with open(args.gsim_jsonl) as handle:
        for line in handle:
            if '"record":"node"' not in line:
                continue
            record = json.loads(line)
            # Newer dumps carry the exporter-space node id as gsim_id; older
            # dumps only have the dense topoProj enumeration id.
            node_id = record.get("gsim_id", record["id"])
            gsim_type[node_id] = record.get("gsim_type", -1)

    atoms_by_node = collections.defaultdict(list)
    unowned_kind = collections.Counter()
    commit_atoms = 0
    compute_atoms = 0
    multi_sink = 0
    instructions_by_kind = collections.Counter()
    with open(args.am_audit) as handle:
        for line in handle:
            record = json.loads(line)
            kind = record["kind"]
            instructions_by_kind[kind] += record["instructions"]
            if kind == "CommitEvent":
                commit_atoms += 1
                continue
            compute_atoms += 1
            multi_sink += record.get("multi_sink", 0)
            node_id = record["node_id"]
            if node_id < 0:
                unowned_kind[kind] += 1
                continue
            atoms_by_node[node_id].append(record)

    node_type_census = collections.Counter(gsim_type.values())
    atom_type_census = collections.Counter()
    missing_type_census = collections.Counter()
    missing_samples = collections.defaultdict(list)
    duplicate_nodes = 0
    duplicate_type_census = collections.Counter()
    for node_id, node_type in gsim_type.items():
        atoms = atoms_by_node.get(node_id)
        if not atoms:
            missing_type_census[node_type] += 1
            if len(missing_samples[node_type]) < args.top_missing:
                missing_samples[node_type].append(node_id)
            continue
        atom_type_census[node_type] += 1
        if len(atoms) > 1:
            duplicate_nodes += 1
            duplicate_type_census[node_type] += 1

    # AM atoms whose node id is absent from the gsim census (should not happen).
    alien_nodes = [n for n in atoms_by_node if n not in gsim_type]

    name = lambda t: NODE_TYPE_NAMES.get(t, f"TYPE_{t}")
    print("== NO0006 L2 reconciliation: gsim node vs AM compute atom ==\n")
    header = f"{'node_type':<12} {'gsim_nodes':>12} {'am_atoms':>12} {'no_atom':>10} {'dup_atom':>10}"
    print(header)
    print("-" * len(header))
    all_types = sorted(set(node_type_census) | set(atom_type_census))
    for node_type in all_types:
        print(f"{name(node_type):<12} {node_type_census.get(node_type, 0):>12} "
              f"{atom_type_census.get(node_type, 0):>12} "
              f"{missing_type_census.get(node_type, 0):>10} "
              f"{duplicate_type_census.get(node_type, 0):>10}")
    print("-" * len(header))
    print(f"{'TOTAL':<12} {len(gsim_type):>12} {sum(atom_type_census.values()):>12} "
          f"{sum(missing_type_census.values()):>10} {duplicate_nodes:>10}")

    print("\n== AM atom census ==")
    print(f"compute atoms (excl CommitEvent): {compute_atoms}")
    print(f"  node-mapped: {sum(atom_type_census.values())}")
    print(f"  unowned (AM clock-domain helpers): {sum(unowned_kind.values())} "
          f"{dict(unowned_kind)}")
    print(f"  multi-sink compute atoms: {multi_sink}")
    print(f"commit atoms (AM附加层, not in L2 scope): {commit_atoms}")
    print(f"instructions by atom kind: {dict(instructions_by_kind)}")
    print(f"atoms keyed by node ids absent from gsim census: {len(alien_nodes)}")

    if args.top_missing:
        print("\n== missing-atom samples by type ==")
        for node_type, samples in sorted(missing_samples.items()):
            print(f"  {name(node_type)}: {samples}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
