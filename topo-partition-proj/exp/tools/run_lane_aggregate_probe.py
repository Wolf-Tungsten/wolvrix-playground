#!/usr/bin/env python3
"""Run lane-aggregate on the pre-reg2mem XiangShan GRH JSON and reconcile op counts.

Usage:
  python3 topo-partition-proj/exp/tools/run_lane_aggregate_probe.py \
      [--min-lanes 8] [--out-dir build/xs/lane-agg-probe]

Reads build/xs/grhsim-am/wolvrix_xs_pre_reg_to_mem.json (2.9G), runs
reg-to-mem (复现 E1 基线) → lane-aggregate → simplify(2state) → stats,
writes post stats JSON and a summary JSON with totals.

Baseline for comparison: E1 stats (build/xs/grhsim-am/wolvrix_xs_post_stats.json)。
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import wolvrix  # noqa: E402

PRE_JSON = "build/xs/grhsim-am/wolvrix_xs_pre_reg_to_mem.json"
TOP = "SimTop"

# doc 23 口径（logic+mux+concat+slice+cmp+arith+shift）——与
# topo-partition-proj/exp/tools/module_attr_compare.py 的 GRH_KIND_BUCKET 一致。
# E1 全图复算 = 3,429,884；doc 23 的 3,415,591 是 E3(L1L2) 图，差 14,293 是
# L2 的增量优化。对账必须用同一条流水产出的图。
COMPUTE_KINDS = {
    "kAnd", "kOr", "kXor", "kXnor", "kNot",
    "kLogicAnd", "kLogicOr", "kLogicNot",
    "kReduceAnd", "kReduceOr", "kReduceXor", "kReduceNor", "kReduceNand", "kReduceXnor",
    "kMux",
    "kConcat", "kReplicate",
    "kSliceStatic", "kSliceDynamic", "kSliceArray",
    "kEq", "kNe", "kCaseEq", "kCaseNe", "kWildcardEq", "kWildcardNe",
    "kLt", "kLe", "kGt", "kGe",
    "kAdd", "kSub", "kMul", "kDiv", "kMod",
    "kShl", "kLShr", "kAShr",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-lanes", type=int, default=8)
    ap.add_argument("--max-index-holes", type=int, default=2)
    ap.add_argument("--skip-lane-aggregate", action="store_true",
                    help="baseline 模式：只跑 reg-to-mem+simplify+stats，用于复核 E1 口径")
    ap.add_argument("--out-dir", type=Path, default=Path("build/xs/lane-agg-probe"))
    ap.add_argument("--pre-json", type=Path, default=Path(PRE_JSON))
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stats_path = args.out_dir / "lane_agg_post_stats.json"
    summary_path = args.out_dir / "lane_agg_summary.json"

    with wolvrix.Session() as sess:
        sess.log_level = "info"
        t0 = time.perf_counter()
        sess.read_json_file(str(args.pre_json), out_design="main", replace=True)
        print(f"read_json done {time.perf_counter()-t0:.1f}s", flush=True)

        t0 = time.perf_counter()
        diags = sess.run_pass(
            "reg-to-mem",
            design="main",
            intent=True,
            ordered_writes=True,
            decoded_write_storage=True,
        )
        print(f"reg-to-mem done {time.perf_counter()-t0:.1f}s diags={diags}", flush=True)

        t0 = time.perf_counter()
        if args.skip_lane_aggregate:
            print("baseline mode: lane-aggregate skipped", flush=True)
            report = None
        else:
            diags = sess.run_pass(
                "lane-aggregate",
                design="main",
                min_lanes=args.min_lanes,
                max_index_holes=args.max_index_holes,
                keep_declared_symbols=False,
                out_lane_aggregate_report="lane_agg.report",
            )
            print(f"lane-aggregate done {time.perf_counter()-t0:.1f}s diags={diags}", flush=True)

        report = None
        if not args.skip_lane_aggregate:
            try:
                report = sess.get("lane_agg.report").to_dict()
            except Exception as exc:  # noqa: BLE001
                print(f"report fetch failed: {exc}", flush=True)

        t0 = time.perf_counter()
        sess.run_pass("simplify", design="main", semantics="2state")
        print(f"simplify done {time.perf_counter()-t0:.1f}s", flush=True)

        t0 = time.perf_counter()
        # post_stats JSON 实际是 design graph dump（与生产流水一致），不是 stats 直方图
        sess.store_json(design="main", output=str(stats_path), top=[TOP])
        print(f"store_json done {time.perf_counter()-t0:.1f}s -> {stats_path}", flush=True)

    # summarize compute ops from stats json
    t0 = time.perf_counter()
    with open(stats_path) as f:
        stats = json.load(f)
    total = 0
    compute = 0
    kinds = {}
    for graph in stats.get("graphs", []):
        if graph.get("symbol") != TOP:
            continue
        for op in graph.get("ops", []):
            k = op.get("kind", "")
            total += 1
            kinds[k] = kinds.get(k, 0) + 1
            if k in COMPUTE_KINDS:
                compute += 1
    summary = {
        "top_total_ops": total,
        "top_compute_ops": compute,
        "min_lanes": args.min_lanes,
        "kind_counts": dict(sorted(kinds.items(), key=lambda kv: -kv[1])),
        "report": report,
        "elapsed_readme": "compare vs E1: compute 3,415,591 (AM) vs 2,813,531 (gsim)",
    }
    summary_path.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"summary -> {summary_path} ({time.perf_counter()-t0:.1f}s)")
    print(f"top_total_ops={total} top_compute_ops={compute}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
