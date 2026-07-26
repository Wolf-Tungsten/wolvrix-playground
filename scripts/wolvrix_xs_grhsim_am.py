#!/usr/bin/env python3

"""Build a XiangShan GRHSIM-AM model without replacing the legacy route."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path


def log(message: str) -> None:
    sys.stderr.write(f"[wolvrix-xs-grhsim-am] {message}\n")
    sys.stderr.flush()


def require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise RuntimeError(f"{label} not found: {path}")


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    log(f"exec {shlex.join(command)}")
    completed = subprocess.run(command, env=env, check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed with exit status {completed.returncode}: "
            f"{shlex.join(command)}"
        )


def parse_positive(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"expected an integer, got {value!r}") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {value!r}")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Normalize XiangShan RTL to GRH JSON, then lower, schedule, and emit it "
            "through the GRHSIM-AM pipeline."
        )
    )
    parser.add_argument("filelist")
    parser.add_argument("top")
    parser.add_argument("--emit-dir", type=Path, required=True)
    parser.add_argument("--normalize-dir", type=Path, required=True)
    parser.add_argument("--post-stats-json", type=Path, required=True)
    parser.add_argument("--pre-reg-to-mem-json", type=Path, required=True)
    parser.add_argument("--read-args-file", type=Path, required=True)
    parser.add_argument("--legacy-script", type=Path, required=True)
    parser.add_argument("--lower-json-bin", type=Path, required=True)
    parser.add_argument("--log-level", default="info")
    parser.add_argument("--reuse-post-stats", action="store_true")
    parser.add_argument("--blocks-per-source", type=parse_positive)
    parser.add_argument("--max-source-bytes", type=parse_positive)
    parser.add_argument("--max-instructions-per-block", type=parse_positive)
    parser.add_argument(
        "--block-formation", choices=("greedy", "coarsen-dp"), default=None
    )
    parser.add_argument("--dp-segment-penalty", type=float, default=None)
    parser.add_argument("--dp-coarsen-budget", type=int, default=None)
    args = parser.parse_args()

    emit_dir = args.emit_dir.resolve()
    normalize_dir = args.normalize_dir.resolve()
    post_stats_json = args.post_stats_json.resolve()
    pre_reg_to_mem_json = args.pre_reg_to_mem_json.resolve()
    read_args_file = args.read_args_file.resolve()
    legacy_script = args.legacy_script.resolve()
    lower_json_bin = args.lower_json_bin.resolve()

    require_file(lower_json_bin, "GRHSIM-AM lower-json binary")
    emit_dir.mkdir(parents=True, exist_ok=True)
    normalize_dir.mkdir(parents=True, exist_ok=True)
    post_stats_json.parent.mkdir(parents=True, exist_ok=True)
    pre_reg_to_mem_json.parent.mkdir(parents=True, exist_ok=True)

    if args.reuse_post_stats:
        require_file(post_stats_json, "reused post-stats JSON")
        log(f"reuse post-stats JSON {post_stats_json}")
    else:
        require_file(legacy_script, "legacy GrhSIM normalization script")
        require_file(Path(args.filelist).resolve(), "XiangShan filelist")
        require_file(read_args_file, "Wolvrix read-args file")

        normalize_env = os.environ.copy()
        normalize_env.update(
            {
                "WOLVRIX_XS_GRHSIM_ENABLE_STATS": "1",
                "WOLVRIX_XS_GRHSIM_POST_STATS_JSON": str(post_stats_json),
                "WOLVRIX_XS_GRHSIM_PRE_REG_TO_MEM_JSON": str(pre_reg_to_mem_json),
                "WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON": "0",
                "WOLVRIX_XS_GRHSIM_STOP_AFTER_PRE_SCHED": "1",
                "WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE": "0",
                "WOLVRIX_XS_GRHSIM_IMPORT_GSIM_PRECOARSEN": "",
                "WOLVRIX_XS_GRHSIM_IMPORT_GSIM_EXECUTABLE_GRH": "",
            }
        )
        run(
            [
                sys.executable,
                str(legacy_script),
                str(Path(args.filelist).resolve()),
                args.top,
                str(normalize_dir),
                "",
                str(read_args_file),
                args.log_level,
                "--waveform",
                "off",
                "--perf",
                "off",
            ],
            env=normalize_env,
        )
        require_file(post_stats_json, "generated post-stats JSON")

    lower_command = [
        str(lower_json_bin),
        str(post_stats_json),
        args.top,
        "--emit",
        str(emit_dir),
    ]
    if args.blocks_per_source is not None:
        lower_command.extend(["--blocks-per-source", str(args.blocks_per_source)])
    if args.max_source_bytes is not None:
        lower_command.extend(["--max-source-bytes", str(args.max_source_bytes)])
    if args.max_instructions_per_block is not None:
        lower_command.extend(
            ["--max-instructions-per-block", str(args.max_instructions_per_block)]
        )
    if args.block_formation is not None:
        lower_command.extend(["--block-formation", args.block_formation])
    if args.dp_segment_penalty is not None:
        lower_command.extend(["--dp-segment-penalty", str(args.dp_segment_penalty)])
    if args.dp_coarsen_budget is not None:
        if args.dp_coarsen_budget < 0:
            parser.error("--dp-coarsen-budget must be non-negative")
        lower_command.extend(["--dp-coarsen-budget", str(args.dp_coarsen_budget)])
    run(lower_command)

    require_file(emit_dir / "Makefile", "GRHSIM-AM emitted Makefile")
    require_file(emit_dir / f"grhsim_{args.top}.hpp", "GRHSIM-AM emitted model header")
    log(f"AM model ready {emit_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        log(f"FAIL: {error}")
        raise SystemExit(1)
