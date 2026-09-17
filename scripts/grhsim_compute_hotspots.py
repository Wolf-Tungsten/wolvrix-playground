#!/usr/bin/env python3
"""Decompose the compute-phase gprof bucket into task/helper hotspots with op-mix traits."""

import argparse
from bisect import bisect_right
from collections import Counter
from pathlib import Path
import re

from grhsim_cpu_profile import read_profile, symbols, task_phases


TASK_RE = re.compile(r"\w+::cpu_task_(\d+)\(\)")

SOURCE_COUNTERS = (
    ("wb_write_cell", re.compile(r"cpu_write_cell<")),
    ("wb_write_scalar", re.compile(r"cpu_write_scalar<")),
    ("wb_stage", re.compile(r"cpu_stage<")),
    ("wb_stage_cell", re.compile(r"cpu_stage_cell")),
    ("wb_stage_bytes", re.compile(r"cpu_stage_bytes")),
    ("apply_masked", re.compile(r"grhsim_apply_masked_words_inplace")),
    ("direct_changed", re.compile(r"cpu_direct_state_changed")),
    ("dsample", re.compile(r"cpu_dsample")),
    ("cached_defs", re.compile(r"const auto cpu_cached_value_")),
    ("cevent_defs", re.compile(r"const bool cpu_cevent_")),
    ("edge_snap_defs", re.compile(r"const bool cpu_edge_snapshot_")),
    ("event_snap_defs", re.compile(r"const bool cpu_event_snapshot_")),
    ("ifs", re.compile(r"if\(")),
    ("fors", re.compile(r"for\(")),
    ("pflag_writes", re.compile(r"cpu_pflags\[")),
)
HELPER_RE = re.compile(r"\b(grhsim_\w+)\s*\(")
WRITEBACK_LINE_RE = re.compile(
    r"cpu_write_cell<|cpu_write_scalar<|cpu_stage<|cpu_stage_cell|cpu_stage_bytes|"
    r"grhsim_apply_masked_words_inplace|cpu_direct_state_changed|cpu_dsample")


def attribute(profile_path, binary_path, model_path, expected_samples):
    period, records, maps = read_profile(profile_path.read_bytes())
    total = sum(count for count, _ in records)
    if total != expected_samples:
        raise ValueError(f"sample total {total} != expected {expected_samples}")
    native = symbols(binary_path)
    starts = sorted(native)
    phases = task_phases(model_path)
    main_maps = [m for m in maps if m[4] and Path(m[4]).resolve() == binary_path.resolve()]
    if not main_maps or len({m[0] - m[3] for m in main_maps}) != 1:
        raise ValueError("missing or inconsistent executable mapping")
    base = main_maps[0][0] - main_maps[0][3]
    functions, categories = Counter(), Counter()
    for count, pc in records:
        mapping = next((m for m in maps if m[0] <= pc < m[1]), None)
        name, category = "[unmapped]", "unmapped"
        if mapping in main_maps:
            address = pc - base
            index = bisect_right(starts, address) - 1
            name, category = "[main unresolved]", "main_unresolved"
            if index >= 0:
                start = starts[index]
                size, symbol = native[start]
                if address < start + size:
                    name, category = symbol, "main_other"
                    task = TASK_RE.fullmatch(name)
                    if task:
                        category = phases[int(task[1])]
                    elif name.endswith("::eval()"):
                        category = "evaluator"
        elif mapping:
            name = "[external] " + (mapping[4] or "anonymous")
            category = "external"
        functions[name] += count
        categories[category] += count
    return total, phases, functions, categories


def task_source_stats(path):
    stats = Counter()
    helpers = Counter()
    code_lines = 0
    writeback_lines = 0
    ternaries = 0
    for line in path.read_text().splitlines():
        if not line or line.startswith("#include") or line.startswith('extern "C"'):
            continue
        code_lines += 1
        body = line.split("//", 1)[0]
        ternaries += body.count("?")
        if WRITEBACK_LINE_RE.search(line):
            writeback_lines += 1
        for name, pattern in SOURCE_COUNTERS:
            stats[name] += len(pattern.findall(body))
        for helper in HELPER_RE.findall(body):
            helpers[helper] += 1
    stats["code_lines"] = code_lines
    stats["writeback_lines"] = writeback_lines
    stats["ternaries"] = ternaries
    return stats, helpers


def native_task_counts(binary_path, phases, cache_path):
    import json
    import subprocess
    if cache_path and Path(cache_path).exists():
        data = json.loads(Path(cache_path).read_text())
        return {int(k): v for k, v in data["tasks"].items()}, data["sizes"]
    counts = {}
    sizes = {}
    task = None
    command = ["objdump", "-d", "-C", "--no-show-raw-insn", str(binary_path)]
    with subprocess.Popen(command, stdout=subprocess.PIPE, text=True) as process:
        for line in process.stdout:
            symbol = re.match(r"^[0-9a-f]+ <(.+)>:$", line)
            if symbol:
                match = TASK_RE.fullmatch(symbol[1])
                task = int(match[1]) if match else None
                if task is not None:
                    counts.setdefault(task, Counter())
                continue
            instruction = re.match(r"^\s+([0-9a-f]+):\s+(\S+)", line)
            if not instruction or task is None:
                continue
            row = counts[task]
            row["instructions"] += 1
            mnemonic = instruction[2]
            if mnemonic.startswith("j") and mnemonic not in ("jmp", "jmpq"):
                row["conditional_jumps"] += 1
        if process.wait():
            raise RuntimeError("objdump failed")
    output = subprocess.check_output(["nm", "-n", "-S", "-C", "--defined-only", str(binary_path)], text=True)
    for line in output.splitlines():
        match = re.fullmatch(r"([0-9a-f]+)\s+([0-9a-f]+)\s+[TtWw]\s+(.+)", line)
        if match:
            task_match = TASK_RE.fullmatch(match[3])
            if task_match:
                sizes[int(task_match[1])] = int(match[2], 16)
    if set(counts) != set(phases):
        raise ValueError("native task coverage differs from generated schedule")
    if cache_path:
        Path(cache_path).write_text(json.dumps({
            "binary": str(binary_path),
            "tasks": {str(k): dict(v) for k, v in counts.items()},
            "sizes": sizes}))
    return counts, sizes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True,
                        help="grhsim_SimTop.cpp of the profiled model")
    parser.add_argument("--expected-samples", type=int, required=True)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--native-cache", type=Path, default=None)
    parser.add_argument("--reference-dir", type=Path, default=None,
                        help="optional second model dir to flag tasks whose source changed")
    args = parser.parse_args()

    total, phases, functions, categories = attribute(
        args.profile, args.binary, args.model, args.expected_samples)
    compute_total = categories["compute_task"]
    commit_total = categories["commit_task"]
    print(f"samples={total} compute_bucket={compute_total} ({compute_total / total * 100:.2f}%) "
          f"commit_bucket={commit_total} ({commit_total / total * 100:.2f}%)")

    compute_rows = [(int(m[1]), count) for name, count in functions.items()
                    if (m := TASK_RE.fullmatch(name)) and phases[int(m[1])] == "compute_task"]
    compute_rows.sort(key=lambda row: (-row[1], row[0]))
    sampled_tasks = len(compute_rows)
    cumulative = 0
    tasks_to_half = 0
    for index, (_, count) in enumerate(compute_rows, 1):
        cumulative += count
        if cumulative >= compute_total / 2 and not tasks_to_half:
            tasks_to_half = index
    top10 = sum(count for _, count in compute_rows[:10])
    top20 = sum(count for _, count in compute_rows[:20])
    top50 = sum(count for _, count in compute_rows[:50])
    print(f"sampled_compute_tasks={sampled_tasks} tasks_to_50pct_of_compute={tasks_to_half}")
    print(f"top10={top10} ({top10 / total * 100:.2f}% total, {top10 / compute_total * 100:.2f}% of compute)")
    print(f"top20={top20} ({top20 / total * 100:.2f}% total, {top20 / compute_total * 100:.2f}% of compute)")
    print(f"top50={top50} ({top50 / total * 100:.2f}% total, {top50 / compute_total * 100:.2f}% of compute)")
    print("NO00010 reference: 56397 samples, compute 47.36%, sampled_compute_tasks=3367, "
          "top10=1439 (2.55% total, 5.39% of compute), max task 173 (0.31% total)")

    model_dir = args.model.parent
    counts, sizes = native_task_counts(args.binary, phases, args.native_cache)
    changed = set()
    if args.reference_dir:
        for task, _ in compute_rows[:args.top]:
            current = (model_dir / f"grhsim_SimTop_task_{task}.cpp").read_bytes()
            reference = (args.reference_dir / f"grhsim_SimTop_task_{task}.cpp").read_bytes()
            if current != reference:
                changed.add(task)

    print(f"\n== top {args.top} compute tasks ==")
    print("rank task samples pct_total pct_compute cum_compute native_instr native_cj size_bytes "
          "code_lines wb_lines wb_share ifs fors tern write_cell write_scalar stage stage_cell "
          "apply_masked direct_changed dsample cached cevent top_helpers")
    running = 0
    aggregate = Counter()
    aggregate_helpers = Counter()
    for rank, (task, count) in enumerate(compute_rows[:args.top], 1):
        running += count
        stats, helpers = task_source_stats(model_dir / f"grhsim_SimTop_task_{task}.cpp")
        aggregate.update(stats)
        aggregate_helpers.update(helpers)
        native = counts[task]
        helper_text = ",".join(f"{name}:{n}" for name, n in helpers.most_common(3))
        flag = " [changed-in-reference]" if task in changed else ""
        wb_share = stats["writeback_lines"] / max(stats["code_lines"], 1) * 100
        print(f"{rank} {task} {count} {count / total * 100:.3f} {count / compute_total * 100:.2f} "
              f"{running / compute_total * 100:.2f} {native['instructions']} {native['conditional_jumps']} "
              f"{sizes.get(task, 0)} {stats['code_lines']} {stats['writeback_lines']} {wb_share:.1f}% "
              f"{stats['ifs']} {stats['fors']} {stats['ternaries']} "
              f"{stats['wb_write_cell']} {stats['wb_write_scalar']} {stats['wb_stage']} "
              f"{stats['wb_stage_cell']} {stats['apply_masked']} {stats['direct_changed']} "
              f"{stats['dsample']} {stats['cached_defs']} {stats['cevent_defs']} {helper_text}{flag}")

    print(f"\n== aggregate op-mix over top {args.top} compute tasks ==")
    for name, _ in SOURCE_COUNTERS:
        print(f"{name}={aggregate[name]}", end=" ")
    print(f"ternaries={aggregate['ternaries']} code_lines={aggregate['code_lines']} "
          f"writeback_lines={aggregate['writeback_lines']}")
    print("top helpers:", ", ".join(f"{n}:{c}" for n, c in aggregate_helpers.most_common(10)))

    print("\n== hottest shared helpers (main_other; compute+commit mixed) ==")
    helper_rows = [(name, count) for name, count in functions.most_common()
                   if not TASK_RE.fullmatch(name) and not name.startswith("[")
                   and not name.endswith("::eval()")][:12]
    for name, count in helper_rows:
        print(f"{count} {count / total * 100:.3f}% {name}")


if __name__ == "__main__":
    main()
