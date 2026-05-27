#!/usr/bin/env python3

from __future__ import annotations

import argparse
import shlex
import sys
import time
from pathlib import Path

import wolvrix


def parse_tokens(value: str) -> list[str]:
    if not value:
        return []
    return shlex.split(value)


def log(message: str) -> None:
    sys.stderr.write(f"[grh-ir-visualize] {message}\n")
    sys.stderr.flush()


def require_ok(diagnostics: list[dict], stage: str) -> None:
    errors = [item for item in diagnostics if str(item.get("kind", "")).lower() == "error"]
    if errors:
      raise RuntimeError(f"{stage} failed with {len(errors)} diagnostics")


def load_extra_read_args(path: Path | None) -> list[str]:
    if path is None:
        return []
    if not path.exists():
        raise FileNotFoundError(f"read args file not found: {path}")
    tokens: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text:
            tokens.extend(parse_tokens(text))
    return tokens


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export a hierarchical Xiangshan GRH JSON for grh-ir-visualize.",
    )
    parser.add_argument("filelist", help="slang filelist path")
    parser.add_argument("top", help="top graph / module name")
    parser.add_argument("json_out", help="output json path")
    parser.add_argument("read_args_file", nargs="?", help="extra read args file")
    parser.add_argument("--roundtrip", action="store_true", help="read the emitted json back once")
    parser.add_argument("--log-level", default="info", help="wolvrix session log level")
    parser.add_argument(
        "--skip-safe-passes",
        action="store_true",
        help="store immediately after read_sv without extra hierarchy-safe passes",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    json_out = Path(args.json_out).resolve()
    read_args = ["-f", args.filelist, "--top", args.top]
    read_args.extend(load_extra_read_args(Path(args.read_args_file)) if args.read_args_file else [])

    safe_passes: list[tuple[str, dict]] = []
    if not args.skip_safe_passes:
        safe_passes = [
            ("xmr-resolve", {}),
            ("memory-read-retime", {}),
            ("multidriven-guard", {}),
            ("blackbox-guard", {}),
            ("latch-transparent-read", {}),
            ("simplify", {"semantics": "2state"}),
            ("memory-init-check", {}),
        ]

    total_start = time.perf_counter()
    with wolvrix.Session() as sess:
        sess.log_level = args.log_level

        start = time.perf_counter()
        log("read_sv start")
        diagnostics = sess.read_sv(None, out_design="design.main", slang_args=read_args)
        require_ok(diagnostics, "read_sv")
        log(f"read_sv done {int((time.perf_counter() - start) * 1000)}ms")

        for pass_name, kwargs in safe_passes:
            start = time.perf_counter()
            log(f"pass {pass_name} start")
            diagnostics = sess.run_pass(pass_name, design="design.main", **kwargs)
            require_ok(diagnostics, f"pass {pass_name}")
            log(f"pass {pass_name} done {int((time.perf_counter() - start) * 1000)}ms")

        json_out.parent.mkdir(parents=True, exist_ok=True)
        start = time.perf_counter()
        log(f"store_json start {json_out}")
        diagnostics = sess.store_json(design="design.main", output=str(json_out), top=[args.top])
        require_ok(diagnostics, "store_json")
        log(f"store_json done {int((time.perf_counter() - start) * 1000)}ms")

        if args.roundtrip:
            start = time.perf_counter()
            log("read_json_file start (roundtrip)")
            diagnostics = sess.read_json_file(str(json_out), out_design="design.main", replace=True)
            require_ok(diagnostics, "read_json_file")
            log(f"read_json_file done {int((time.perf_counter() - start) * 1000)}ms")

        log(f"total done {int((time.perf_counter() - total_start) * 1000)}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())