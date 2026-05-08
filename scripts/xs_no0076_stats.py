#!/usr/bin/env python3

import argparse
import json
import re
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def summarize_compute_ops_from_post_stats(post_stats_json: Path, top_name: str) -> dict[str, int]:
    data = load_json(post_stats_json)
    for graph in data.get("graphs", []):
        if graph.get("symbol") != top_name:
            continue
        ops = graph.get("ops")
        if ops is None:
            ops = graph.get("operations", [])
        source_kinds = {"kConstant", "kRegisterReadPort", "kLatchReadPort"}
        sink_kinds = {"kRegisterWritePort", "kLatchWritePort", "kMemoryWritePort", "kMemoryFillPort"}
        decl_kinds = {"kRegister", "kMemory", "kLatch", "kDpicImport"}
        hier_kinds = {"kInstance", "kBlackbox", "kXMRRead", "kXMRWrite"}
        total_ops = len(ops)
        source_ops = sum(1 for op in ops if op.get("kind") in source_kinds)
        sink_ops = sum(1 for op in ops if op.get("kind") in sink_kinds)
        declaration_ops = sum(1 for op in ops if op.get("kind") in decl_kinds)
        hierarchy_ops = sum(1 for op in ops if op.get("kind") in hier_kinds)
        compute_ops = total_ops - source_ops - sink_ops - declaration_ops - hierarchy_ops
        return {
            "top_total_ops": total_ops,
            "top_compute_ops": compute_ops,
            "top_source_ops": source_ops,
            "top_sink_ops": sink_ops,
            "top_declaration_ops": declaration_ops,
            "top_hierarchy_ops": hierarchy_ops,
            "top_values": len(graph.get("vals", [])),
        }
    raise RuntimeError(f"top graph not found in post stats: {top_name}")


def parse_source_clones_from_log(log_path: Path) -> int:
    pattern = re.compile(r"source_clones_in_compute_nodes=(\d+)")
    last_match: int | None = None
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            match = pattern.search(line)
            if match:
                last_match = int(match.group(1))
    if last_match is None:
        raise RuntimeError(f"source_clones_in_compute_nodes not found in log: {log_path}")
    return last_match


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize NO0076 XiangShan gsim/grhsim stats")
    parser.add_argument("--gsim-stats", required=True)
    parser.add_argument("--grhsim-supernode-stats", required=True)
    parser.add_argument("--grhsim-post-summary", required=False)
    parser.add_argument("--grhsim-post-stats", required=False)
    parser.add_argument("--grhsim-log", required=False)
    parser.add_argument("--top", default="SimTop")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    gsim = load_json(Path(args.gsim_stats))
    grhsim = load_json(Path(args.grhsim_supernode_stats))
    post: dict
    if args.grhsim_post_summary and Path(args.grhsim_post_summary).exists():
        post = load_json(Path(args.grhsim_post_summary))
    elif args.grhsim_post_stats and Path(args.grhsim_post_stats).exists():
        post = summarize_compute_ops_from_post_stats(Path(args.grhsim_post_stats), args.top)
    else:
        raise RuntimeError("missing grhsim post summary and fallback post stats input")

    gsim_ref = int(gsim["enode_node_ref_count"])
    gsim_unique = int(gsim["enode_unique_count"])
    gsim_non_ref = gsim_unique - gsim_ref
    if "source_clones_in_compute_nodes" in grhsim:
        grhsim_cloned_source = int(grhsim["source_clones_in_compute_nodes"])
    elif args.grhsim_log and Path(args.grhsim_log).exists():
        grhsim_cloned_source = parse_source_clones_from_log(Path(args.grhsim_log))
    else:
        raise RuntimeError("missing source_clones_in_compute_nodes in stats and no grhsim log fallback")
    grhsim_compute = int(post["top_compute_ops"])

    summary = {
        "gsim": {
            "supernodes": int(gsim["supernodes"]),
            "boundary_activation_edges": int(gsim["boundary_activation_edges"]),
            "ref_enodes": gsim_ref,
            "non_ref_enodes": gsim_non_ref,
            "enode_unique_count": gsim_unique,
        },
        "grhsim": {
            "supernodes": int(grhsim["supernodes"]),
            "boundary_activation_edges": int(grhsim["boundary_activation_edges"]),
            "cloned_source_ops": grhsim_cloned_source,
            "compute_ops": grhsim_compute,
        },
        "alignment": {
            "supernode_delta": int(grhsim["supernodes"]) - int(gsim["supernodes"]),
            "boundary_activation_edges_delta": int(grhsim["boundary_activation_edges"]) -
                                               int(gsim["boundary_activation_edges"]),
            "ref_over_cloned_source": (gsim_ref / grhsim_cloned_source) if grhsim_cloned_source else None,
            "non_ref_over_compute": (gsim_non_ref / grhsim_compute) if grhsim_compute else None,
        },
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
