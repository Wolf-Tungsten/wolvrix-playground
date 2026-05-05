#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="ascii"))


def pick_stats(data: dict, key: str) -> dict:
    value = data.get(key)
    if not isinstance(value, dict):
        raise KeyError(f"missing stats key {key}")
    return value


def ratio(num: float, den: float) -> float | None:
    return num / den if den else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gsim-stats", required=True)
    parser.add_argument("--grhsim-activity", required=True)
    parser.add_argument("--grhsim-ir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    gsim = load(Path(args.gsim_stats))
    grh_activity = load(Path(args.grhsim_activity))
    grh_ir = load(Path(args.grhsim_ir))
    graph = grh_ir["graphs"][0]

    gsim_nodes = int(gsim["node_count"])
    gsim_enodes = int(gsim["expnodes"]["unique_count"])
    grh_ops = len(graph.get("ops", []))
    grh_vals = len(graph.get("vals", []))
    grh_boundary_values = int(grh_activity["boundary_values"])
    grh_boundary_edges = int(grh_activity["boundary_activation_edges"])

    payload = {
        "gsim": {
            "node_count": gsim_nodes,
            "unique_enodes": gsim_enodes,
            "unique_enodes_per_node": ratio(gsim_enodes, gsim_nodes),
            "nodes_enodes": pick_stats(gsim, "nodes_enodes"),
            "supernodes_members": pick_stats(gsim, "supernodes_members"),
            "supernodes_enodes": pick_stats(gsim, "supernodes_enodes"),
            "node_enode_dominant_slots": gsim.get("node_enode_dominant_slots", {}),
        },
        "grhsim": {
            "ops": grh_ops,
            "vals": grh_vals,
            "supernodes": grh_activity["supernodes"],
            "ops_per_supernode": grh_activity["ops_per_supernode"],
            "boundary_values": grh_boundary_values,
            "boundary_activation_edges": grh_boundary_edges,
            "boundary_value_fanout": grh_activity["boundary_value_fanout"],
            "boundary_values_per_op": ratio(grh_boundary_values, grh_ops),
            "boundary_values_per_val": ratio(grh_boundary_values, grh_vals),
            "boundary_activation_edges_per_op": ratio(grh_boundary_edges, grh_ops),
        },
        "cross": {
            "grhsim_ops_per_gsim_node": ratio(grh_ops, gsim_nodes),
            "gsim_unique_enodes_per_grhsim_op": ratio(gsim_enodes, grh_ops),
            "grhsim_boundary_values_per_gsim_node": ratio(grh_boundary_values, gsim_nodes),
            "grhsim_boundary_values_per_gsim_unique_enode": ratio(grh_boundary_values, gsim_enodes),
        },
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="ascii")

    print("GSIM:")
    print(f"  nodes={gsim_nodes} unique_enodes={gsim_enodes} enodes/node={payload['gsim']['unique_enodes_per_node']:.3f}")
    print(
        "  node_enodes "
        f"median={payload['gsim']['nodes_enodes']['median']} "
        f"p90={payload['gsim']['nodes_enodes']['p90']} "
        f"p99={payload['gsim']['nodes_enodes']['p99']} "
        f"max={payload['gsim']['nodes_enodes']['max']}"
    )
    print(
        "  supernode_enodes "
        f"median={payload['gsim']['supernodes_enodes']['median']} "
        f"p90={payload['gsim']['supernodes_enodes']['p90']} "
        f"max={payload['gsim']['supernodes_enodes']['max']}"
    )
    print("GrhSIM:")
    print(f"  ops={grh_ops} vals={grh_vals} supernodes={grh_activity['supernodes']}")
    print(
        "  ops/supernode "
        f"median={payload['grhsim']['ops_per_supernode']['median']} "
        f"p90={payload['grhsim']['ops_per_supernode']['p90']} "
        f"max={payload['grhsim']['ops_per_supernode']['max']}"
    )
    print(
        "  boundary "
        f"values={grh_boundary_values} "
        f"activation_edges={grh_boundary_edges} "
        f"values/op={payload['grhsim']['boundary_values_per_op']:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
