#!/usr/bin/env python3

import argparse
import json
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
    sys.stderr.write(f"[xs-scalar-memory-pack-probe] {message}\n")
    sys.stderr.flush()


def read_extra_args(path: str) -> list[str]:
    if not path:
        return []
    file = Path(path)
    if not file.exists():
        raise RuntimeError(f"read args file not found: {path}")
    out: list[str] = []
    for line in file.read_text(encoding="utf-8").splitlines():
        token = line.strip()
        if token:
            out.extend(parse_tokens(token))
    return out


def has_error_diagnostic(diags: list[dict]) -> bool:
    return any(str(item.get("kind", "")).lower() == "error" for item in diags)


def require_ok(diags: list[dict], label: str) -> None:
    if has_error_diagnostic(diags):
        raise RuntimeError(f"{label} failed")


def write_stats_json(sess: wolvrix.Session, key: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    value = sess.get(key)
    if not isinstance(value, StatsValue):
        raise TypeError(f"session key is not stats: {key}")
    value.write_json(str(out_path))
    log(f"stats json written {out_path}")


def latest_info_message(diags: list[dict], pass_name: str) -> str | None:
    target = pass_name.lower()
    for item in reversed(diags):
        if str(item.get("kind", "")).lower() != "info":
            continue
        if str(item.get("pass", "")).lower() != target:
            continue
        return str(item.get("message", ""))
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build XiangShan checkpoint JSON once, then probe scalar-memory-pack from that JSON."
    )
    parser.add_argument("filelist")
    parser.add_argument("top")
    parser.add_argument("out_dir")
    parser.add_argument("read_args_file")
    parser.add_argument("log_level", nargs="?", default="info")
    parser.add_argument(
        "--checkpoint",
        choices=["xmr-resolve", "flatten-simplify"],
        default="flatten-simplify",
        help="Which pre-pack stage to materialize before replaying scalar-memory-pack",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    checkpoint_tag = args.checkpoint.replace("-", "_")
    checkpoint_json = out_dir / f"after_{checkpoint_tag}.json"
    scalar_json = out_dir / f"after_{checkpoint_tag}_plus_scalar_memory_pack.json"
    checkpoint_stats_json = out_dir / f"after_{checkpoint_tag}_stats.json"
    scalar_stats_json = out_dir / f"after_{checkpoint_tag}_plus_scalar_memory_pack_stats.json"
    summary_json = out_dir / "summary.json"

    read_args = ["-f", args.filelist, "--top", args.top]
    read_args.extend(read_extra_args(args.read_args_file))

    summary: dict[str, object] = {
        "filelist": str(Path(args.filelist).resolve()),
        "top": args.top,
        "read_args_file": str(Path(args.read_args_file).resolve()),
        "out_dir": str(out_dir),
        "checkpoint": args.checkpoint,
        "artifacts": {
            f"after_{checkpoint_tag}_json": str(checkpoint_json),
            f"after_{checkpoint_tag}_plus_scalar_memory_pack_json": str(scalar_json),
            f"after_{checkpoint_tag}_stats_json": str(checkpoint_stats_json),
            f"after_{checkpoint_tag}_plus_scalar_memory_pack_stats_json": str(scalar_stats_json),
        },
        "timing_ms": {},
    }

    total_start = time.perf_counter()

    with wolvrix.Session() as sess:
        sess.log_level = args.log_level
        sess.diagnostics_raise_min_level = "none"

        start = time.perf_counter()
        log("read_sv start")
        diags = sess.read_sv(None, out_design="design.main", slang_args=read_args)
        require_ok(diags, "read_sv")
        summary["timing_ms"]["read_sv"] = int((time.perf_counter() - start) * 1000)
        log(f"read_sv done {summary['timing_ms']['read_sv']}ms")

        checkpoint_pipeline: list[tuple[str, dict]] = [("xmr-resolve", {})]
        if args.checkpoint == "flatten-simplify":
            checkpoint_pipeline.extend(
                [
                    ("multidriven-guard", {}),
                    ("blackbox-guard", {}),
                    ("latch-transparent-read", {}),
                    ("hier-flatten", {}),
                    ("comb-lane-pack", {"enable_declared_roots": False}),
                    ("comb-loop-elim", {}),
                    ("simplify", {"semantics": "2state", "keep_declared_symbols": False}),
                ]
            )

        for pass_name, pass_kwargs in checkpoint_pipeline:
            start = time.perf_counter()
            log(f"pass {pass_name} start")
            diags = sess.run_pass(pass_name, design="design.main", **pass_kwargs)
            require_ok(diags, f"pass {pass_name}")
            timing_key = pass_name.replace("-", "_")
            summary["timing_ms"][timing_key] = int((time.perf_counter() - start) * 1000)
            log(f"pass {pass_name} done {summary['timing_ms'][timing_key]}ms")

        start = time.perf_counter()
        log(f"pass stats(after_{checkpoint_tag}) start")
        checkpoint_stats_key = f"stats.after_{checkpoint_tag}"
        diags = sess.run_pass("stats", design="design.main", out_stats=checkpoint_stats_key)
        require_ok(diags, f"pass stats(after_{checkpoint_tag})")
        write_stats_json(sess, checkpoint_stats_key, checkpoint_stats_json)
        summary["timing_ms"][f"stats_after_{checkpoint_tag}"] = int((time.perf_counter() - start) * 1000)
        log(f"pass stats(after_{checkpoint_tag}) done {summary['timing_ms'][f'stats_after_{checkpoint_tag}']}ms")

        start = time.perf_counter()
        log(f"store_json after_{checkpoint_tag} start {checkpoint_json}")
        diags = sess.store_json(design="design.main", output=str(checkpoint_json), top=[args.top])
        require_ok(diags, f"store_json(after_{checkpoint_tag})")
        summary["timing_ms"][f"store_json_after_{checkpoint_tag}"] = int((time.perf_counter() - start) * 1000)
        log(f"store_json after_{checkpoint_tag} done {summary['timing_ms'][f'store_json_after_{checkpoint_tag}']}ms")

    with wolvrix.Session() as sess:
        sess.log_level = args.log_level
        sess.diagnostics_raise_min_level = "none"

        start = time.perf_counter()
        log(f"read_json_file after_{checkpoint_tag} start {checkpoint_json}")
        diags = sess.read_json_file(str(checkpoint_json), out_design="design.main")
        require_ok(diags, f"read_json_file(after_{checkpoint_tag})")
        summary["timing_ms"][f"read_json_after_{checkpoint_tag}"] = int((time.perf_counter() - start) * 1000)
        log(f"read_json_file after_{checkpoint_tag} done {summary['timing_ms'][f'read_json_after_{checkpoint_tag}']}ms")

        start = time.perf_counter()
        log("pass scalar-memory-pack start")
        diags = sess.run_pass("scalar-memory-pack", design="design.main", keep_declared_symbols=False)
        require_ok(diags, "pass scalar-memory-pack")
        summary["timing_ms"]["scalar_memory_pack"] = int((time.perf_counter() - start) * 1000)
        summary["scalar_memory_pack_info"] = latest_info_message(diags, "scalar-memory-pack")
        summary["scalar_memory_pack_diagnostics"] = diags
        log(f"pass scalar-memory-pack done {summary['timing_ms']['scalar_memory_pack']}ms")

        start = time.perf_counter()
        log(f"pass stats(after_{checkpoint_tag}_plus_scalar_memory_pack) start")
        scalar_stats_key = f"stats.after_{checkpoint_tag}_plus_scalar_memory_pack"
        diags = sess.run_pass("stats", design="design.main", out_stats=scalar_stats_key)
        require_ok(diags, f"pass stats(after_{checkpoint_tag}_plus_scalar_memory_pack)")
        write_stats_json(sess, scalar_stats_key, scalar_stats_json)
        summary["timing_ms"][f"stats_after_{checkpoint_tag}_plus_scalar_memory_pack"] = int(
            (time.perf_counter() - start) * 1000
        )
        log(
            f"pass stats(after_{checkpoint_tag}_plus_scalar_memory_pack) done "
            f"{summary['timing_ms'][f'stats_after_{checkpoint_tag}_plus_scalar_memory_pack']}ms"
        )

        start = time.perf_counter()
        log(f"store_json after_{checkpoint_tag}_plus_scalar_memory_pack start {scalar_json}")
        diags = sess.store_json(design="design.main", output=str(scalar_json), top=[args.top])
        require_ok(diags, f"store_json(after_{checkpoint_tag}_plus_scalar_memory_pack)")
        summary["timing_ms"][f"store_json_after_{checkpoint_tag}_plus_scalar_memory_pack"] = int(
            (time.perf_counter() - start) * 1000
        )
        log(
            f"store_json after_{checkpoint_tag}_plus_scalar_memory_pack done "
            f"{summary['timing_ms'][f'store_json_after_{checkpoint_tag}_plus_scalar_memory_pack']}ms"
        )

    summary["timing_ms"]["total"] = int((time.perf_counter() - total_start) * 1000)
    summary_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"summary written {summary_json}")
    log(f"total done {summary['timing_ms']['total']}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
