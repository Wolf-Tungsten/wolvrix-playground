#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import wolvrix


def log(message: str) -> None:
    sys.stderr.write(f"[xs-components-grhsim] {message}\n")
    sys.stderr.flush()


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
    parser.add_argument("--emit-runtime-stats", action="store_true")
    parser.add_argument("--export-compute-dag", default="")
    parser.add_argument("--stop-after-activity-schedule", action="store_true")
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
            ("reg-to-mem", {}),
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

        if args.json:
            json_path = Path(args.json).resolve()
            json_path.parent.mkdir(parents=True, exist_ok=True)
            log(f"store_json {json_path}")
            sess.store_json(design="design.main", output=str(json_path), top=[args.top])

        if args.stop_after_activity_schedule:
            log("stop after activity-schedule")
            return 0

        log(f"emit_grhsim_cpp {out_dir}")
        sess.emit_grhsim_cpp(
            design="design.main",
            output=str(out_dir),
            top=[args.top],
            sched_batch_max_ops=args.sched_batch_max_ops,
            sched_batch_max_estimated_lines=args.sched_batch_max_estimated_lines,
            sched_batch_target_count=args.sched_batch_target_count,
            emit_parallelism=args.emit_parallelism,
            emit_runtime_stats=args.emit_runtime_stats,
            waveform="off",
            perf="off",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
