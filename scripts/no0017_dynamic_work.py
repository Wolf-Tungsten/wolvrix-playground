#!/usr/bin/env python3
"""NO0017 B-layer: dynamic work decomposition for grhsim-AM vs gsim.

Inputs:
  --am-block-execs FILE   EMU_AM_BLOCK_EXECS dump: "<block> <w|c> <execs>" per line
                          (block 0 is the entry block; its execs == eval() calls)
  --am-blocks FILE        block_assignment.jsonl with {"record":"block","size":N,"atoms":M}
  --gsim-log FILE         gsim emu log containing [GSIM_RUNTIME_PROFILE] and the
                          difftest "cycleCnt" line
  --cycles N              DUT cycles for the AM run (default: parse from --am-log)
  --am-log FILE           AM emu log to parse cycleCnt from (difftest output)
  --json PATH             write results as JSON
"""
from __future__ import annotations

import argparse
import json
import re
import sys


def parse_am_block_execs(path: str):
    compute_execs = 0
    commit_execs = 0
    entry_execs = None
    per_block = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) != 3:
                continue
            block, kind, execs = int(parts[0]), parts[1], int(parts[2])
            per_block.append((block, kind, execs))
            if block == 0:
                entry_execs = execs
                continue
            if kind == "c":
                commit_execs += execs
            else:
                compute_execs += execs
    if entry_execs is None:
        raise SystemExit("am block-execs dump is missing block 0 (entry)")
    return per_block, entry_execs, compute_execs, commit_execs


def parse_am_blocks(path: str):
    sizes = {}
    atoms = {}
    kinds = {}
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line.startswith('{"record":"block"'):
                continue
            rec = json.loads(line)
            sizes[rec["id"]] = rec["size"]
            atoms[rec["id"]] = rec.get("atoms", rec["size"])
            kinds[rec["id"]] = rec.get("kind", "compute")
    return sizes, atoms, kinds


def parse_cycle_cnt(text: str):
    match = re.search(r"cycleCnt = ([0-9,]+)", text)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def parse_am_profile(text: str):
    """Parse [am-profile] summary lines emitted by dump_runtime_profile()."""
    result = {}
    match = re.search(
        r"\[am-profile\] eval calls: (\d+), rounds: (\d+) \(([0-9.]+) per eval\)", text
    )
    if match:
        result["eval_calls"] = int(match.group(1))
        result["rounds"] = int(match.group(2))
        result["rounds_per_eval"] = float(match.group(3))
    match = re.search(
        r"\[am-profile\] block execs: (\d+) \(compute (\d+), commit (\d+)\)", text
    )
    if match:
        result["block_execs"] = int(match.group(1))
        result["compute_block_execs"] = int(match.group(2))
        result["commit_block_execs"] = int(match.group(3))
    match = re.search(
        r"\[am-profile\] activations: forward (\d+), backward (\d+)", text
    )
    if match:
        result["activations_forward"] = int(match.group(1))
        result["activations_backward"] = int(match.group(2))
    match = re.search(
        r"\[am-profile\] time ms: eval ([0-9.]+), compute ([0-9.]+) \(([0-9.]+)%\), "
        r"commit ([0-9.]+) \(([0-9.]+)%\), other ([0-9.]+)",
        text,
    )
    if match:
        result["eval_ms"] = float(match.group(1))
        result["compute_ms"] = float(match.group(2))
        result["compute_pct"] = float(match.group(3))
        result["commit_ms"] = float(match.group(4))
        result["commit_pct"] = float(match.group(5))
        result["other_ms"] = float(match.group(6))
    return result


def parse_phase_timing(text: str):
    """Parse [EMU_PHASE_TIMING] breakdown emitted by the difftest emu."""
    match = re.search(
        r"\[EMU_PHASE_TIMING\] tick_total_us=(\d+) single_cycle_us=(\d+) "
        r"model_step_us=(\d+) single_cycle_other_us=(\d+) difftest_us=(\d+) "
        r"tick_misc_us=(\d+)",
        text,
    )
    if not match:
        return {}
    values = [int(group) for group in match.groups()]
    return {
        "tick_total_ms": round(values[0] / 1000.0, 1),
        "single_cycle_ms": round(values[1] / 1000.0, 1),
        "model_step_ms": round(values[2] / 1000.0, 1),
        "difftest_ms": round(values[4] / 1000.0, 1),
        "tick_misc_ms": round(values[5] / 1000.0, 1),
    }


def parse_gsim_profile(path: str):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    match = re.search(
        r"\[GSIM_RUNTIME_PROFILE\] active_supernodes=(\d+) nodes=(\d+) "
        r"ref_enodes=(\d+) non_ref_enodes=(\d+) total_enodes=(\d+)",
        text,
    )
    if not match:
        raise SystemExit("no [GSIM_RUNTIME_PROFILE] line found in gsim log")
    cycles = parse_cycle_cnt(text)
    return {
        "active_supernodes": int(match.group(1)),
        "nodes": int(match.group(2)),
        "ref_enodes": int(match.group(3)),
        "non_ref_enodes": int(match.group(4)),
        "total_enodes": int(match.group(5)),
        "cycles": cycles,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--am-block-execs")
    parser.add_argument("--am-blocks")
    parser.add_argument("--am-log")
    parser.add_argument("--gsim-log")
    parser.add_argument("--cycles", type=int, default=None)
    parser.add_argument("--json", dest="json_path")
    args = parser.parse_args()

    result = {}

    if args.am_block_execs and args.am_blocks:
        per_block, eval_calls, compute_execs, commit_execs = parse_am_block_execs(
            args.am_block_execs
        )
        sizes, atoms, kinds = parse_am_blocks(args.am_blocks)
        dyn_instructions = 0
        dyn_atoms = 0
        missing = 0
        for block, kind, execs in per_block:
            if block == 0 or execs == 0:
                continue
            size = sizes.get(block)
            if size is None:
                missing += 1
                continue
            dyn_instructions += execs * size
            dyn_atoms += execs * atoms.get(block, size)
        cycles = args.cycles
        log_text = None
        if args.am_log:
            with open(args.am_log, "r", encoding="utf-8", errors="replace") as fh:
                log_text = fh.read()
        if cycles is None and log_text is not None:
            cycles = parse_cycle_cnt(log_text)
        if cycles is None:
            raise SystemExit("AM cycle count unknown: pass --cycles or --am-log")
        result["am"] = {
            "cycles": cycles,
            "eval_calls": eval_calls,
            "evals_per_cycle": round(eval_calls / cycles, 4),
            "compute_block_execs": compute_execs,
            "commit_block_execs": commit_execs,
            "compute_block_execs_per_cycle": round(compute_execs / cycles, 1),
            "commit_block_execs_per_cycle": round(commit_execs / cycles, 1),
            "dynamic_instructions": dyn_instructions,
            "dynamic_atoms": dyn_atoms,
            "dynamic_instructions_per_cycle": round(dyn_instructions / cycles, 1),
            "dynamic_atoms_per_cycle": round(dyn_atoms / cycles, 1),
            "blocks_missing_size": missing,
        }
        if log_text is not None:
            profile = parse_am_profile(log_text)
            if profile:
                result["am"]["profile"] = profile
            phase = parse_phase_timing(log_text)
            if phase:
                result["am"]["phase_timing"] = phase

    if args.gsim_log:
        with open(args.gsim_log, "r", encoding="utf-8", errors="replace") as fh:
            gsim_text = fh.read()
        cycles = parse_cycle_cnt(gsim_text) or args.cycles
        entry = {"cycles": cycles}
        try:
            profile = parse_gsim_profile(args.gsim_log)
            cycles = cycles or profile["cycles"]
            if cycles is None:
                raise SystemExit("gsim cycle count unknown")
            entry.update(
                {
                    "active_supernodes_per_cycle": round(
                        profile["active_supernodes"] / cycles, 1
                    ),
                    "dynamic_nodes_per_cycle": round(profile["nodes"] / cycles, 1),
                    "total_enodes_per_cycle": round(
                        profile["total_enodes"] / cycles, 1
                    ),
                    "ref_enodes_per_cycle": round(profile["ref_enodes"] / cycles, 1),
                }
            )
        except SystemExit:
            pass
        phase = parse_phase_timing(gsim_text)
        if phase:
            entry["phase_timing"] = phase
        result["gsim"] = entry

    if (
        "am" in result
        and "gsim" in result
        and result["gsim"].get("dynamic_nodes_per_cycle")
    ):
        am = result["am"]
        gs = result["gsim"]
        result["compare"] = {
            "dynamic_units_per_cycle_am_over_gsim": round(
                am["dynamic_atoms_per_cycle"] / gs["dynamic_nodes_per_cycle"], 3
            )
            if gs["dynamic_nodes_per_cycle"] > 0
            else None,
            "active_groups_per_cycle_am_over_gsim": round(
                (am["compute_block_execs_per_cycle"])
                / gs["active_supernodes_per_cycle"],
                3,
            )
            if gs["active_supernodes_per_cycle"] > 0
            else None,
        }

    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
