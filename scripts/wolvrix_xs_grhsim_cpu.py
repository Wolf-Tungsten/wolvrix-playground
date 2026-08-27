#!/usr/bin/env python3

"""Build a XiangShan model through the GRHSIM IR CPU single-thread flow."""

from __future__ import annotations

import argparse
import shlex
import sys
import time
import traceback
from pathlib import Path

import wolvrix


def log(message: str) -> None:
    sys.stderr.write(f"[wolvrix-xs-grhsim-cpu] {message}\n")
    sys.stderr.flush()


def parse_positive(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"expected an integer, got {value!r}") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {value!r}")
    return parsed


def has_error_diagnostic(diagnostics: list[dict]) -> bool:
    return any(
        str(diagnostic.get("kind", "")).lower() == "error"
        for diagnostic in diagnostics
    )


def require_ok(diagnostics: list[dict], label: str) -> None:
    if has_error_diagnostic(diagnostics):
        raise RuntimeError(f"{label} failed")


def read_args(filelist: Path, top: str, read_args_file: Path) -> list[str]:
    if not filelist.is_file():
        raise RuntimeError(f"XiangShan filelist not found: {filelist}")
    if not read_args_file.is_file():
        raise RuntimeError(f"Wolvrix read-args file not found: {read_args_file}")

    result = ["-f", str(filelist), "--top", top]
    for line in read_args_file.read_text(encoding="utf-8").splitlines():
        token = line.strip()
        if token:
            result.extend(shlex.split(token))
    return result


def normalize(session: wolvrix.Session, slang_args: list[str]) -> None:
    start = time.perf_counter()
    log("read_sv start")
    require_ok(
        session.read_sv(None, out_design="design.main", slang_args=slang_args),
        "read_sv",
    )
    log(f"read_sv done {int((time.perf_counter() - start) * 1000)}ms")

    passes: list[tuple[str, dict]] = [
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
                "output_mode": "array",
            },
        ),
        ("comb-loop-elim", {}),
        ("simplify", {"semantics": "2state"}),
        ("simplify", {"semantics": "2state"}),
        ("memory-init-check", {}),
        (
            "reg-to-mem",
            {
                "ordered_writes": True,
                "decoded_write_storage": True,
            },
        ),
        (
            "lane-aggregate",
            {
                "min_lanes": 4,
                "keep_declared_symbols": False,
                "output_mode": "array",
            },
        ),
        ("simplify", {"semantics": "2state"}),
    ]
    for pass_name, pass_options in passes:
        start = time.perf_counter()
        log(f"pass {pass_name} start")
        require_ok(
            session.run_pass(pass_name, design="design.main", **pass_options),
            f"pass {pass_name}",
        )
        log(f"pass {pass_name} done {int((time.perf_counter() - start) * 1000)}ms")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Normalize XiangShan RTL, lower it to GRHSIM IR, and emit the "
            "stage-1 CPU single-thread model."
        )
    )
    parser.add_argument("filelist", type=Path)
    parser.add_argument("top")
    parser.add_argument("output", type=Path)
    parser.add_argument("read_args_file", type=Path)
    parser.add_argument("log_level", nargs="?", default="info")
    parser.add_argument("--resume-grh-json", type=Path)
    parser.add_argument("--normalized-json", type=Path)
    parser.add_argument("--ops-per-source-file", type=parse_positive, default=50000)
    parser.add_argument("--fixed-point-iteration-limit", type=parse_positive, default=100)
    args = parser.parse_args()

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    total_start = time.perf_counter()

    with wolvrix.Session() as session:
        session.log_level = args.log_level
        session.diagnostics_raise_min_level = "none"

        if args.resume_grh_json is not None:
            resume_path = args.resume_grh_json.resolve()
            if not resume_path.is_file():
                raise RuntimeError(f"resumed GRH JSON not found: {resume_path}")
            start = time.perf_counter()
            log(f"read_json_file start {resume_path}")
            require_ok(
                session.read_json_file(str(resume_path), out_design="design.main"),
                "read_json_file",
            )
            log(
                "read_json_file done "
                f"{int((time.perf_counter() - start) * 1000)}ms"
            )
        else:
            normalize(
                session,
                read_args(
                    args.filelist.resolve(),
                    args.top,
                    args.read_args_file.resolve(),
                ),
            )

        if args.normalized_json is not None:
            normalized_json = args.normalized_json.resolve()
            normalized_json.parent.mkdir(parents=True, exist_ok=True)
            start = time.perf_counter()
            log(f"store_json start {normalized_json}")
            session.store_json(
                design="design.main",
                output=str(normalized_json),
                top=[args.top],
            )
            log(f"store_json done {int((time.perf_counter() - start) * 1000)}ms")

        start = time.perf_counter()
        log(f"cpu_single_thread start {output}")
        require_ok(
            wolvrix.pipelines.cpu_single_thread(
                session,
                design="design.main",
                module="grhsim.main",
                top=args.top,
                output=str(output),
                ops_per_source_file=args.ops_per_source_file,
                fixed_point_iteration_limit=args.fixed_point_iteration_limit,
            ),
            "cpu_single_thread",
        )
        log(
            "cpu_single_thread done "
            f"{int((time.perf_counter() - start) * 1000)}ms"
        )

    required = [
        output / "Makefile",
        output / f"grhsim_{args.top}.hpp",
    ]
    for path in required:
        if not path.is_file():
            raise RuntimeError(f"CPU single-thread emit is incomplete: {path}")

    log(f"total done {int((time.perf_counter() - total_start) * 1000)}ms")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        log(f"FAIL: {error}")
        traceback.print_exc(file=sys.stderr)
        raise SystemExit(1)
