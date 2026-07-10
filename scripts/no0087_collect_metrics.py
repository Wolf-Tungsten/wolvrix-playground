#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
from statistics import mean


SOURCE_KINDS = {"kConstant", "kRegisterReadPort", "kLatchReadPort"}
SINK_KINDS = {"kRegisterWritePort", "kLatchWritePort", "kMemoryWritePort", "kMemoryFillPort"}
DECL_KINDS = {"kRegister", "kMemory", "kLatch", "kDpicImport"}
HIER_KINDS = {"kInstance", "kBlackbox", "kXMRRead", "kXMRWrite"}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def is_compute_kind(kind: str) -> bool:
    return kind not in SOURCE_KINDS and kind not in SINK_KINDS and kind not in DECL_KINDS and kind not in HIER_KINDS


def percentile(sorted_values: list[int], pct: float) -> int | None:
    if not sorted_values:
        return None
    idx = int((len(sorted_values) - 1) * pct)
    return sorted_values[idx]


def summarize_values(values: list[int]) -> dict:
    values_sorted = sorted(values)
    return {
        "count": len(values),
        "sum": sum(values),
        "zero": sum(1 for v in values if v == 0),
        "min": values_sorted[0] if values_sorted else None,
        "mean": mean(values) if values else None,
        "median": percentile(values_sorted, 0.50),
        "p90": percentile(values_sorted, 0.90),
        "p99": percentile(values_sorted, 0.99),
        "max": values_sorted[-1] if values_sorted else None,
    }


def summarize_compute_op_out_degree(post_stats: Path, top: str) -> dict:
    data = load_json(post_stats)
    graph = next((g for g in data.get("graphs", []) if g.get("symbol") == top), None)
    if graph is None:
        raise RuntimeError(f"top graph not found: {top}")

    ops = graph.get("ops") or graph.get("operations") or []
    vals = graph.get("vals") or graph.get("values") or []

    compute_ops: set[str] = set()
    op_is_compute: dict[str, bool] = {}
    for op in ops:
        sym = op.get("sym")
        if sym is None:
            continue
        is_compute = is_compute_kind(op.get("kind", ""))
        op_is_compute[sym] = is_compute
        if is_compute:
            compute_ops.add(sym)

    all_user_sets: dict[str, set[str]] = {}
    compute_user_sets: dict[str, set[str]] = {}
    multi_output_compute_ops: set[str] = set()
    seen_output_def: set[str] = set()

    for val in vals:
        def_op = val.get("def")
        if def_op not in compute_ops:
            continue
        if def_op in seen_output_def:
            multi_output_compute_ops.add(def_op)
        else:
            seen_output_def.add(def_op)
        users = val.get("users") or []
        if not users:
            continue
        all_set = all_user_sets.setdefault(def_op, set())
        compute_set = compute_user_sets.setdefault(def_op, set())
        for user in users:
            user_op = user.get("op") if isinstance(user, dict) else None
            if user_op is None:
                continue
            all_set.add(user_op)
            if op_is_compute.get(user_op, False):
                compute_set.add(user_op)

    all_degrees = [len(all_user_sets.get(op, ())) for op in compute_ops]
    compute_degrees = [len(compute_user_sets.get(op, ())) for op in compute_ops]
    return {
        "definition": {
            "compute_op_out_degree_all_users": "For each top-graph compute op, count unique user ops of all output values.",
            "compute_op_out_degree_compute_users": "Same as all_users, but only users classified as compute ops are counted.",
        },
        "compute_ops": len(compute_ops),
        "multi_output_compute_ops": len(multi_output_compute_ops),
        "compute_op_out_degree_all_users": summarize_values(all_degrees),
        "compute_op_out_degree_compute_users": summarize_values(compute_degrees),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect current NO0087 GSim/GrhSIM graph metrics")
    parser.add_argument("--gsim-stats", required=True)
    parser.add_argument("--grhsim-supernode-stats", required=True)
    parser.add_argument("--grhsim-post-summary", required=True)
    parser.add_argument("--grhsim-post-stats", required=True)
    parser.add_argument("--top", default="SimTop")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    gsim = load_json(Path(args.gsim_stats))
    grhsim = load_json(Path(args.grhsim_supernode_stats))
    post_summary = load_json(Path(args.grhsim_post_summary))
    compute_degree = summarize_compute_op_out_degree(Path(args.grhsim_post_stats), args.top)

    out = {
        "inputs": {
            "gsim_stats": args.gsim_stats,
            "grhsim_supernode_stats": args.grhsim_supernode_stats,
            "grhsim_post_summary": args.grhsim_post_summary,
            "grhsim_post_stats": args.grhsim_post_stats,
            "top": args.top,
        },
        "gsim": {
            "supernodes": gsim.get("supernodes"),
            "dag_edges": gsim.get("dag_edges"),
            "boundary_activation_edges": gsim.get("boundary_activation_edges"),
            "unique_activation_edges": gsim.get("unique_activation_edges"),
            "active_source_nodes": gsim.get("active_source_nodes"),
            "always_active_supernodes": gsim.get("always_active_supernodes"),
            "enode_unique_count": gsim.get("enode_unique_count"),
            "enode_node_ref_count": gsim.get("enode_node_ref_count"),
            "enode_non_ref_count": gsim.get("enode_unique_count") - gsim.get("enode_node_ref_count"),
            "enode_int_const_count": gsim.get("enode_int_const_count"),
            "enode_edge_count": gsim.get("enode_edge_count"),
            "enode_out_degree": gsim.get("enode_out_degree"),
            "ref_enode_out_degree": gsim.get("ref_enode_out_degree"),
            "non_ref_enode_out_degree": gsim.get("non_ref_enode_out_degree"),
        },
        "grhsim": {
            "supernodes": grhsim.get("supernodes"),
            "compute_supernodes": grhsim.get("compute_supernodes"),
            "commit_supernodes": grhsim.get("commit_supernodes"),
            "dag_edges": grhsim.get("dag_edges"),
            "topo_edges": grhsim.get("topo_edges"),
            "boundary_values": grhsim.get("boundary_values"),
            "boundary_activation_edges": grhsim.get("boundary_activation_edges"),
            "compute_compute_value_pairs": grhsim.get("compute_compute_value_pairs"),
            "compute_commit_value_pairs": grhsim.get("compute_commit_value_pairs"),
            "state_read_activation_edges": grhsim.get("state_read_activation_edges"),
            "constant_activation_edges": grhsim.get("constant_activation_edges"),
            "other_compute_activation_edges": grhsim.get("other_compute_activation_edges"),
            "out_degree_per_supernode": grhsim.get("out_degree_per_supernode"),
            "ops_per_supernode": grhsim.get("ops_per_supernode"),
            "post_stats_summary": post_summary,
            "compute_op_degree": compute_degree,
        },
        "comparison": {
            "supernode_delta_grhsim_minus_gsim": grhsim.get("supernodes") - gsim.get("supernodes"),
            "dag_edges_delta_grhsim_minus_gsim": grhsim.get("dag_edges") - gsim.get("dag_edges"),
            "boundary_activation_edges_delta_grhsim_minus_gsim": grhsim.get("boundary_activation_edges") - gsim.get("boundary_activation_edges"),
            "non_ref_enodes_over_compute_ops": (gsim.get("enode_unique_count") - gsim.get("enode_node_ref_count")) / post_summary["top_compute_ops"],
            "boundary_activation_edges_grhsim_over_gsim": grhsim.get("boundary_activation_edges") / gsim.get("boundary_activation_edges"),
        },
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
