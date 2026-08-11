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
    parser.add_argument("--max-atoms-per-block", type=parse_positive)
    parser.add_argument("--tree-atom-fold-max-instr", type=int, default=None)
    parser.add_argument("--dp-segment-penalty", type=float, default=None)
    parser.add_argument("--dp-coarsen-atom-budget", type=int, default=None)
    parser.add_argument("--dp-coarsen-instr-budget", type=int, default=None)
    parser.add_argument("--merge-when-min-group", type=int, default=None)
    parser.add_argument("--dp-refinement-rounds", type=int, default=None)
    parser.add_argument("--fanout-absorb-max-instructions", type=int, default=None)
    parser.add_argument("--fanout-absorb-budget-mult", type=float, default=None)
    parser.add_argument("--fanout-absorb-max-consumers", type=int, default=None)
    parser.add_argument("--runtime-profile", action="store_true")
    parser.add_argument("--full-evaluation", action="store_true")
    parser.add_argument("--changed-trace", action="store_true")
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
    if args.max_atoms_per_block is not None:
        lower_command.extend(
            ["--max-atoms-per-block", str(args.max_atoms_per_block)]
        )
    if args.tree_atom_fold_max_instr is not None:
        if args.tree_atom_fold_max_instr < 0:
            parser.error("--tree-atom-fold-max-instr must be non-negative")
        lower_command.extend(
            ["--tree-atom-fold-max-instr", str(args.tree_atom_fold_max_instr)]
        )
    if args.dp_segment_penalty is not None:
        lower_command.extend(["--dp-segment-penalty", str(args.dp_segment_penalty)])
    if args.dp_coarsen_atom_budget is not None:
        if args.dp_coarsen_atom_budget < 0:
            parser.error("--dp-coarsen-atom-budget must be non-negative")
        lower_command.extend(["--dp-coarsen-atom-budget", str(args.dp_coarsen_atom_budget)])
    if args.dp_coarsen_instr_budget is not None:
        if args.dp_coarsen_instr_budget < 0:
            parser.error("--dp-coarsen-instr-budget must be non-negative")
        lower_command.extend(["--dp-coarsen-instr-budget", str(args.dp_coarsen_instr_budget)])
    if args.merge_when_min_group is not None:
        if args.merge_when_min_group < 0:
            parser.error("--merge-when-min-group must be non-negative")
        lower_command.extend(["--merge-when-min-group", str(args.merge_when_min_group)])
    if args.dp_refinement_rounds is not None:
        if args.dp_refinement_rounds < 0:
            parser.error("--dp-refinement-rounds must be non-negative")
        lower_command.extend(["--dp-refinement-rounds", str(args.dp_refinement_rounds)])
    if args.fanout_absorb_max_instructions is not None:
        if args.fanout_absorb_max_instructions < 0:
            parser.error("--fanout-absorb-max-instructions must be non-negative")
        lower_command.extend(["--fanout-absorb-max-instructions", str(args.fanout_absorb_max_instructions)])
    if args.fanout_absorb_budget_mult is not None:
        lower_command.extend(["--fanout-absorb-budget-mult", str(args.fanout_absorb_budget_mult)])
    if args.fanout_absorb_max_consumers is not None:
        if args.fanout_absorb_max_consumers < 0:
            parser.error("--fanout-absorb-max-consumers must be non-negative")
        lower_command.extend(["--fanout-absorb-max-consumers", str(args.fanout_absorb_max_consumers)])
    if args.runtime_profile:
        lower_command.append("--runtime-profile")
    if args.full_evaluation:
        lower_command.append("--full-evaluation")
    if args.changed_trace:
        lower_command.append("--changed-trace")
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
