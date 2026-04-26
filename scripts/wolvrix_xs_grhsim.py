#!/usr/bin/env python3

import argparse
import json
import os
import shlex
import statistics
import sys
import time
import traceback
from pathlib import Path

import wolvrix
from wolvrix.adapters.stats import StatsValue
from wolvrix import _wolvrix as _native


def parse_tokens(value: str) -> list[str]:
    if not value:
        return []
    return shlex.split(value)


def log(message: str) -> None:
    sys.stderr.write(f"[wolvrix-xs-grhsim] {message}\n")
    sys.stderr.flush()


def env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    return int(value.strip())


def write_stats_json(sess: wolvrix.Session, key: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "wolvrix_xs_stats.json"
    value = sess.get(key)
    if not isinstance(value, StatsValue):
        raise TypeError(f"session key is not stats: {key}")
    value.write_json(str(out_path))
    log(f"stats json written {out_path}")


def write_design_json(sess: wolvrix.Session, design: str, top_name: str, out_path: Path, label: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    log(f"{label} start {out_path}")
    sess.store_json(design=design, output=str(out_path), top=[top_name])
    log(f"{label} done {int((time.perf_counter() - start) * 1000)}ms")

def has_error_diagnostic(diags: list[dict]) -> bool:
    return any(str(item.get("kind", "")).lower() == "error" for item in diags)


def require_ok(diags: list[dict], label: str) -> None:
    if has_error_diagnostic(diags):
        raise RuntimeError(f"{label} failed")


def percentile(sorted_values: list[int], num: int, den: int) -> int:
    if not sorted_values:
        return 0
    idx = (len(sorted_values) - 1) * num // den
    return sorted_values[idx]


def write_supernode_stats(sess: wolvrix.Session, key: str, out_dir: Path) -> None:
    raw = _native.session_export(sess._capsule, key=key, view="python")
    supernode_to_ops = [list(map(int, ops)) for ops in raw]
    dag_key = key.rsplit("supernode_to_ops", 1)[0] + "dag"
    dag_raw = _native.session_export(sess._capsule, key=dag_key, view="python")
    dag = [list(map(int, succs)) for succs in dag_raw]
    sizes = sorted(len(ops) for ops in supernode_to_ops)
    edge_count = sum(len(succs) for succs in dag)
    out_degrees = sorted(len(succs) for succs in dag)
    if sizes:
        summary = {
            "supernodes": len(sizes),
            "ops_per_supernode": {
                "min": sizes[0],
                "mean": statistics.fmean(sizes),
                "median": statistics.median(sizes),
                "p90": percentile(sizes, 90, 100),
                "p99": percentile(sizes, 99, 100),
                "max": sizes[-1],
            },
            "dag_edges": edge_count,
            "out_degree_per_supernode": {
                "min": out_degrees[0],
                "mean": statistics.fmean(out_degrees),
                "median": statistics.median(out_degrees),
                "p90": percentile(out_degrees, 90, 100),
                "p99": percentile(out_degrees, 99, 100),
                "max": out_degrees[-1],
            },
        }
    else:
        summary = {
            "supernodes": 0,
            "ops_per_supernode": {
                "min": 0,
                "mean": 0.0,
                "median": 0,
                "p90": 0,
                "p99": 0,
                "max": 0,
            },
            "dag_edges": 0,
            "out_degree_per_supernode": {
                "min": 0,
                "mean": 0.0,
                "median": 0,
                "p90": 0,
                "p99": 0,
                "max": 0,
            },
        }
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "activity_schedule_supernode_stats.json"
    out_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    log(
        "activity-schedule supernode stats "
        f"supernodes={summary['supernodes']} "
        f"dag_edges={summary['dag_edges']} "
        f"ops_mean={summary['ops_per_supernode']['mean']:.3f} "
        f"ops_median={summary['ops_per_supernode']['median']} "
        f"ops_p90={summary['ops_per_supernode']['p90']} "
        f"ops_p99={summary['ops_per_supernode']['p99']} "
        f"ops_max={summary['ops_per_supernode']['max']} "
        f"outdeg_mean={summary['out_degree_per_supernode']['mean']:.3f} "
        f"outdeg_p99={summary['out_degree_per_supernode']['p99']} "
        f"outdeg_max={summary['out_degree_per_supernode']['max']}"
    )
    log(f"activity-schedule supernode stats written {out_path}")


def write_comb_lane_pack_report(sess: wolvrix.Session, key: str, out_path: Path) -> None:
    raw = _native.session_export(sess._capsule, key=key, view="python")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(raw, indent=2, sort_keys=True), encoding="utf-8")
    log(f"comb-lane-pack report written {out_path} groups={len(raw)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("filelist")
    parser.add_argument("top")
    parser.add_argument("cpp_out_dir")
    parser.add_argument("json_out")
    parser.add_argument("read_args_file")
    parser.add_argument("log_level", nargs="?", default="info")
    parser.add_argument("--waveform", choices=["off", "declared-symbols"], default="off")
    parser.add_argument("--perf", choices=["off", "eval"], default="off")
    args = parser.parse_args()

    filelist = args.filelist
    top_name = args.top
    cpp_out_dir = Path(args.cpp_out_dir).resolve()
    json_out = args.json_out
    read_args_file = args.read_args_file
    log_level = args.log_level
    post_stats_json = Path(
        os.environ.get(
            "WOLVRIX_XS_GRHSIM_POST_STATS_JSON",
            str(cpp_out_dir / "wolvrix_xs_post_stats.json"),
        )
    ).resolve()
    resume_from_stats_json = env_flag("WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON")
    enable_mem_to_reg = env_flag("WOLVRIX_XS_GRHSIM_ENABLE_MEM_TO_REG", default=False)
    mem_to_reg_row_limit = env_int("WOLVRIX_XS_GRHSIM_MEM_TO_REG_ROW_LIMIT", 64)
    supernode_max_size = env_int("WOLVRIX_XS_GRHSIM_SUPERNODE_MAX_SIZE", 72)
    sched_batch_max_ops = env_int("WOLVRIX_XS_GRHSIM_SCHED_BATCH_MAX_OPS", 2048)
    sched_batch_max_estimated_lines = env_int("WOLVRIX_XS_GRHSIM_SCHED_BATCH_MAX_ESTIMATED_LINES", 8192)
    sched_batch_target_count = env_int("WOLVRIX_XS_GRHSIM_SCHED_BATCH_TARGET_COUNT", 800)
    emit_parallelism = env_int("WOLVRIX_XS_GRHSIM_EMIT_PARALLELISM", 8)
    stop_after_pre_sched = env_flag("WOLVRIX_XS_GRHSIM_STOP_AFTER_PRE_SCHED", default=False)
    comb_lane_pack_report = os.environ.get(
        "WOLVRIX_XS_GRHSIM_COMB_LANE_PACK_REPORT",
        str(cpp_out_dir.parent / "comb_lane_pack_report_xs.json"),
    )

    total_start = time.perf_counter()

    read_args: list[str] = ["-f", filelist, "--top", top_name]

    if read_args_file:
        path = Path(read_args_file)
        if not path.exists():
            raise RuntimeError(f"read args file not found: {read_args_file}")
        for line in path.read_text(encoding="utf-8").splitlines():
            token = line.strip()
            if token:
                read_args.extend(parse_tokens(token))

    cpp_out_dir.mkdir(parents=True, exist_ok=True)

    with wolvrix.Session() as sess:
        sess.log_level = log_level
        sess.diagnostics_raise_min_level = "none"
        pre_sched_pipeline: list[tuple[str, dict]] = [
            ("xmr-resolve", {}),
            ("memory-read-retime", {}),
            ("multidriven-guard", {}),
            ("blackbox-guard", {}),
            ("latch-transparent-read", {}),
            ("hier-flatten", {}),
            (
                "comb-lane-pack",
                {
                    "enable_declared_roots": False,
                    "out_comb_lane_pack_report": "comb-lane-pack.reports",
                },
            ),
            ("comb-loop-elim", {}),
            ("simplify", {"semantics": "2state"}),
            ("memory-init-check", {}),
            ("stats", {"out_stats": "stats.main"}),
        ]
        if enable_mem_to_reg:
            pre_sched_pipeline.insert(2, ("mem-to-reg", {"row_limit": mem_to_reg_row_limit}))
            log(f"mem-to-reg enabled row_limit={mem_to_reg_row_limit}")
        else:
            log("mem-to-reg disabled for GrhSIM flow")
        post_sched_pipeline: list[tuple[str, dict]] = [
            (
                "activity-schedule",
                {
                    "args": [
                        "-path",
                        top_name,
                        "-supernode-max-size",
                        str(supernode_max_size),
                        "-max-sink-supernode-op",
                        "768",
                        "-enable-replication",
                        "false",
                    ]
                },
            ),
        ]
        log(
            "activity-schedule supernode-max-size="
            f"{supernode_max_size} max_sink_supernode_op=768 "
            f"enable_replication=false "
            f"sched_batch_max_ops={sched_batch_max_ops} "
            f"sched_batch_max_estimated_lines={sched_batch_max_estimated_lines} "
            f"sched_batch_target_count={sched_batch_target_count} "
            f"emit_parallelism={emit_parallelism} waveform={args.waveform} perf={args.perf}"
        )

        if resume_from_stats_json:
            if not post_stats_json.exists():
                raise RuntimeError(f"post-stats json not found: {post_stats_json}")
            start = time.perf_counter()
            log(f"read_json_file start {post_stats_json}")
            diags = sess.read_json_file(str(post_stats_json), out_design="design.main")
            require_ok(diags, "read_json_file")
            log(f"read_json_file done {int((time.perf_counter() - start) * 1000)}ms")
        else:
            start = time.perf_counter()
            log("read_sv start")
            diags = sess.read_sv(
                None,
                out_design="design.main",
                slang_args=read_args,
            )
            require_ok(diags, "read_sv")
            log(f"read_sv done {int((time.perf_counter() - start) * 1000)}ms")

            for pass_name, pass_kwargs in pre_sched_pipeline:
                start = time.perf_counter()
                log(f"pass {pass_name} start")
                diags = sess.run_pass(pass_name, design="design.main", **pass_kwargs)
                require_ok(diags, f"pass {pass_name}")
                if pass_name == "comb-lane-pack":
                    write_comb_lane_pack_report(sess, "comb-lane-pack.reports", Path(comb_lane_pack_report))
                if pass_name == "stats":
                    write_stats_json(sess, "stats.main", cpp_out_dir)
                    write_design_json(sess, "design.main", top_name, post_stats_json, "write_post_stats_json")
                log(f"pass {pass_name} done {int((time.perf_counter() - start) * 1000)}ms")

        if stop_after_pre_sched:
            log("stop after pre-sched enabled")
            log(f"total done {int((time.perf_counter() - total_start) * 1000)}ms")
            return 0

        for pass_name, pass_kwargs in post_sched_pipeline:
            start = time.perf_counter()
            log(f"pass {pass_name} start")
            diags = sess.run_pass(pass_name, design="design.main", **pass_kwargs)
            require_ok(diags, f"pass {pass_name}")
            if pass_name == "activity-schedule":
                write_supernode_stats(sess, f"{top_name}.activity_schedule.supernode_to_ops", cpp_out_dir)
            log(f"pass {pass_name} done {int((time.perf_counter() - start) * 1000)}ms")

        if json_out:
            log(f"skip write_json after activity-schedule {json_out}")

        start = time.perf_counter()
        log(f"write_grhsim_cpp start {cpp_out_dir}")
        diags = sess.emit_grhsim_cpp(
            design="design.main",
            output=str(cpp_out_dir),
            top=[top_name],
            sched_batch_max_ops=sched_batch_max_ops,
            sched_batch_max_estimated_lines=sched_batch_max_estimated_lines,
            sched_batch_target_count=sched_batch_target_count,
            emit_parallelism=emit_parallelism,
            waveform=args.waveform,
            perf=args.perf,
        )
        require_ok(diags, "emit_grhsim_cpp")
        log(f"write_grhsim_cpp done {int((time.perf_counter() - start) * 1000)}ms")

        log(f"total done {int((time.perf_counter() - total_start) * 1000)}ms")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as ex:
        log(f"FAIL: {ex}")
        traceback.print_exc(file=sys.stderr)
        raise SystemExit(1)
