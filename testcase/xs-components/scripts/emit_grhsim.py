#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

import wolvrix
from wolvrix import _wolvrix as _native


def log(message: str) -> None:
    sys.stderr.write(f"[xs-components-grhsim] {message}\n")
    sys.stderr.flush()


def percentile(sorted_values: list[int], num: int, den: int) -> int:
    if not sorted_values:
        return 0
    return sorted_values[(len(sorted_values) - 1) * num // den]


def write_activity_schedule_stats(sess: wolvrix.Session, top: str, out_dir: Path) -> None:
    key_prefix = f"{top}.activity_schedule."
    summary_text = None
    try:
        summary_text = _native.session_export(sess._capsule, key=key_prefix + "summary_stats", view="text")
    except Exception:
        pass

    supernode_to_ops = [
        list(map(int, ops))
        for ops in _native.session_export(sess._capsule, key=key_prefix + "supernode_to_ops", view="python")
    ]
    dag = [
        list(map(int, succs))
        for succs in _native.session_export(sess._capsule, key=key_prefix + "dag", view="python")
    ]
    op_sizes = sorted(len(ops) for ops in supernode_to_ops)
    out_degrees = sorted(len(succs) for succs in dag)

    payload = json.loads(summary_text) if summary_text else {}
    payload.update(
        {
            "supernodes": len(supernode_to_ops),
            "dag_edges": sum(out_degrees),
            "ops_per_supernode": {
                "min": op_sizes[0] if op_sizes else 0,
                "mean": statistics.fmean(op_sizes) if op_sizes else 0.0,
                "median": statistics.median(op_sizes) if op_sizes else 0,
                "p90": percentile(op_sizes, 90, 100),
                "p99": percentile(op_sizes, 99, 100),
                "max": op_sizes[-1] if op_sizes else 0,
            },
            "dag_out_degree": {
                "min": out_degrees[0] if out_degrees else 0,
                "mean": statistics.fmean(out_degrees) if out_degrees else 0.0,
                "median": statistics.median(out_degrees) if out_degrees else 0,
                "p90": percentile(out_degrees, 90, 100),
                "p99": percentile(out_degrees, 99, 100),
                "max": out_degrees[-1] if out_degrees else 0,
            },
        }
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "activity_schedule_stats.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="ascii"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sv", required=True)
    parser.add_argument("--top", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--json", default="")
    parser.add_argument("--max-op-in-compute-supernode", type=int, default=8)
    parser.add_argument("--max-op-in-commit-supernode", type=int, default=768)
    parser.add_argument("--sched-batch-max-ops", type=int, default=2048)
    parser.add_argument("--sched-batch-max-estimated-lines", type=int, default=8192)
    parser.add_argument("--sched-batch-target-count", type=int, default=64)
    parser.add_argument("--emit-parallelism", type=int, default=4)
    parser.add_argument("--export-compute-dag", default="")
    args = parser.parse_args()

    sv_path = Path(args.sv).resolve()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    with wolvrix.Session() as sess:
        sess.log_level = "info"
        log(f"read_sv {sv_path}")
        sess.read_sv(str(sv_path), out_design="design.main", slang_args=["--top", args.top])

        passes: list[tuple[str, dict]] = [
            ("xmr-resolve", {}),
            ("multidriven-guard", {}),
            ("blackbox-guard", {}),
            ("latch-transparent-read", {}),
            ("hier-flatten", {}),
            ("comb-lane-pack", {"enable_declared_roots": False}),
            ("comb-loop-elim", {}),
            ("slice-index-const", {}),
            ("simplify", {"semantics": "2state"}),
            ("memory-init-check", {}),
            ("stats", {}),
            (
                "activity-schedule",
                {
                    "path": args.top,
                    "max_op_in_compute_supernode": args.max_op_in_compute_supernode,
                    "max_op_in_commit_supernode": args.max_op_in_commit_supernode,
                    **({"export_compute_dag": args.export_compute_dag} if args.export_compute_dag else {}),
                },
            ),
        ]
        for name, kwargs in passes:
            log(f"pass {name}")
            sess.run_pass(name, design="design.main", **kwargs)
            if name == "activity-schedule":
                write_activity_schedule_stats(sess, args.top, out_dir)

        if args.json:
            json_path = Path(args.json).resolve()
            json_path.parent.mkdir(parents=True, exist_ok=True)
            log(f"store_json {json_path}")
            sess.store_json(design="design.main", output=str(json_path), top=[args.top])

        log(f"emit_grhsim_cpp {out_dir}")
        sess.emit_grhsim_cpp(
            design="design.main",
            output=str(out_dir),
            top=[args.top],
            sched_batch_max_ops=args.sched_batch_max_ops,
            sched_batch_max_estimated_lines=args.sched_batch_max_estimated_lines,
            sched_batch_target_count=args.sched_batch_target_count,
            emit_parallelism=args.emit_parallelism,
            waveform="off",
            perf="off",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
