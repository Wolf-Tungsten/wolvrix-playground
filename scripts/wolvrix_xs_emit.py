#!/usr/bin/env python3

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
    sys.stderr.write(f"[wolvrix-xs] {message}\n")
    sys.stderr.flush()


def write_stats_json(sess: wolvrix.Session, key: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "wolvrix_xs_stats.json"
    value = sess.get(key)
    if not isinstance(value, StatsValue):
        raise TypeError(f"session key is not stats: {key}")
    value.write_json(str(out_path))
    log(f"stats json written {out_path}")


if len(sys.argv) < 6:
    raise RuntimeError(
        "usage: wolvrix_xs_emit.py <filelist> <top> <sv_out> <json_out> <read_args_file> [log_level]"
    )

filelist = sys.argv[1]
top_name = sys.argv[2]
sv_out = sys.argv[3]
json_out = sys.argv[4]
read_args_file = sys.argv[5]
log_level = sys.argv[6] if len(sys.argv) > 6 else "info"

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

start = time.perf_counter()
log("read_sv start")
with wolvrix.Session() as sess:
    sess.log_level = log_level
    sess.read_sv(
        None,
        out_design="design.main",
        slang_args=read_args,
    )
    log(f"read_sv done {int((time.perf_counter() - start) * 1000)}ms")

    pipeline: list[tuple[str, dict]] = [
        ("xmr-resolve", {}),
        ("memory-read-retime", {}),
        #("mem-to-reg", {"row_limit": 512}),
        ("multidriven-guard", {}),
        ("blackbox-guard", {}),
        ("latch-transparent-read", {}),
        ("hier-flatten", {}),
        ("comb-loop-elim", {}),
        ("simplify", {"semantics": "2state"}),
        ("memory-init-check", {}),
        ("stats", {"out_stats": "stats.main"}),
    ]
    for pass_name, pass_kwargs in pipeline:
        start = time.perf_counter()
        log(f"pass {pass_name} start")
        sess.run_pass(pass_name, design="design.main", **pass_kwargs)
        if pass_name == "stats":
            write_stats_json(sess, "stats.main", Path("tmp"))
        log(f"pass {pass_name} done {int((time.perf_counter() - start) * 1000)}ms")

    start = time.perf_counter()
    log(f"write_json start {json_out}")
    sess.store_json(design="design.main", output=json_out)
    log(f"write_json done {int((time.perf_counter() - start) * 1000)}ms")

    start = time.perf_counter()
    log("read_json start")
    sess.read_json_file(json_out, out_design="design.main", replace=True)
    log(f"read_json done {int((time.perf_counter() - start) * 1000)}ms")

    start = time.perf_counter()
    log(f"write_sv start {sv_out}")
    sess.emit_sv(design="design.main", output=sv_out)
    log(f"write_sv done {int((time.perf_counter() - start) * 1000)}ms")

    log(f"total done {int((time.perf_counter() - total_start) * 1000)}ms")
