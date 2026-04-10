#!/usr/bin/env python3

import os
import shlex
import sys
import time
from pathlib import Path

import wolvrix
from wolvrix.adapters.stats import StatsValue


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


if len(sys.argv) < 6:
    raise RuntimeError(
        "usage: wolvrix_xs_grhsim.py <filelist> <top> <cpp_out_dir> <json_out> <read_args_file> [log_level]"
    )

filelist = sys.argv[1]
top_name = sys.argv[2]
cpp_out_dir = Path(sys.argv[3]).resolve()
json_out = sys.argv[4]
read_args_file = sys.argv[5]
log_level = sys.argv[6] if len(sys.argv) > 6 else "info"
post_stats_json = Path(
    os.environ.get(
        "WOLVRIX_XS_GRHSIM_POST_STATS_JSON",
        str(cpp_out_dir / "wolvrix_xs_post_stats.json"),
    )
).resolve()
resume_from_stats_json = env_flag("WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON")

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
    pre_sched_pipeline: list[tuple[str, dict]] = [
        ("xmr-resolve", {}),
        ("memory-read-retime", {}),
        ("mem-to-reg", {"row_limit": 512}),
        ("multidriven-guard", {}),
        ("blackbox-guard", {}),
        ("latch-transparent-read", {}),
        ("hier-flatten", {}),
        ("comb-loop-elim", {}),
        ("simplify", {"semantics": "2state"}),
        ("memory-init-check", {}),
        ("stats", {"out_stats": "stats.main"}),
    ]
    post_sched_pipeline: list[tuple[str, dict]] = [
        ("activity-schedule", {"args": ["-path", top_name, "-enable-replication", "true"]}),
    ]

    if resume_from_stats_json:
        if not post_stats_json.exists():
            raise RuntimeError(f"post-stats json not found: {post_stats_json}")
        start = time.perf_counter()
        log(f"read_json_file start {post_stats_json}")
        sess.read_json_file(str(post_stats_json), out_design="design.main")
        log(f"read_json_file done {int((time.perf_counter() - start) * 1000)}ms")
    else:
        start = time.perf_counter()
        log("read_sv start")
        sess.read_sv(
            None,
            out_design="design.main",
            slang_args=read_args,
        )
        log(f"read_sv done {int((time.perf_counter() - start) * 1000)}ms")

        for pass_name, pass_kwargs in pre_sched_pipeline:
            start = time.perf_counter()
            log(f"pass {pass_name} start")
            sess.run_pass(pass_name, design="design.main", **pass_kwargs)
            if pass_name == "stats":
                write_stats_json(sess, "stats.main", cpp_out_dir)
                write_design_json(sess, "design.main", top_name, post_stats_json, "write_post_stats_json")
            log(f"pass {pass_name} done {int((time.perf_counter() - start) * 1000)}ms")

    for pass_name, pass_kwargs in post_sched_pipeline:
        start = time.perf_counter()
        log(f"pass {pass_name} start")
        sess.run_pass(pass_name, design="design.main", **pass_kwargs)
        log(f"pass {pass_name} done {int((time.perf_counter() - start) * 1000)}ms")

    write_design_json(sess, "design.main", top_name, Path(json_out), "write_json")

    start = time.perf_counter()
    log(f"write_grhsim_cpp start {cpp_out_dir}")
    sess.emit_grhsim_cpp(design="design.main", output=str(cpp_out_dir), top=[top_name])
    log(f"write_grhsim_cpp done {int((time.perf_counter() - start) * 1000)}ms")

    log(f"total done {int((time.perf_counter() - total_start) * 1000)}ms")
