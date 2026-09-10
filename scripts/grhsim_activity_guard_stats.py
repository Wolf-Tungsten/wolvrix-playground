#!/usr/bin/env python3
"""Audit scalar direct-task guards in a GrhSIM-IR generated model."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re


def require(condition, message):
    if not condition:
        raise ValueError(message)


def analyze(model):
    source = model.read_text()
    header = model.with_suffix(".hpp").read_text()
    sizes = re.findall(r"std::array<std::uint8_t,(\d+)> cpu_flags", header)
    require(len(sizes) == 1, "Expected one runtime flag buffer declaration")
    runtime_bytes = int(sizes[0])
    initial = dict(re.findall(r"^cpu_flags\[(\d+)\]=(255|1);$", source, re.M))
    calls = {}
    for line in source.splitlines():
        if not re.search(r"cpu_task_\d+\(\);", line):
            continue
        match = re.fullmatch(r"(?:if\(([^)]+)\))?cpu_task_(\d+)\(\);", line)
        require(match is not None, f"Unsupported task dispatch: {line[:160]}")
        predicate, task_id = match.groups()
        offsets = []
        if predicate is not None:
            for term in predicate.split("||"):
                flag = re.fullmatch(r"cpu_flags\[(\d+)\]", term)
                require(flag is not None, f"Unsupported guard: {term}")
                offsets.append(int(flag[1]))
        require(task_id not in calls, f"Repeated task dispatch: {task_id}")
        require(len(set(offsets)) == len(offsets), f"Repeated guard byte: {task_id}")
        require(all(0 <= x < runtime_bytes for x in offsets), "Guard outside runtime buffer")
        calls[task_id] = offsets
    require(bool(calls), "No direct task calls found")
    files = {p.stem.rsplit("_", 1)[1]: p for p in model.parent.glob(f"{model.stem}_task_*.cpp")}
    require(set(calls) == set(files), "Task file IDs differ from dispatch IDs; use unpacked model")
    kinds = Counter()
    lengths = Counter()
    runs = Counter()
    chunks = Counter()
    qualifying = []
    consumed_all = set()
    for task_id, offsets in calls.items():
        body = files[task_id].read_text()
        definitions = re.findall(r"::cpu_task_(\d+)\(\)\{", body)
        require(definitions == [task_id], f"Wrong task definition: {task_id}")
        consumed = [int(x) for x in re.findall(r"std::uint8_t cpu_active_word=cpu_flags\[(\d+)\]", body)]
        if not consumed:
            if offsets:
                require(len(offsets) == 1 and initial.get(str(offsets[0])) == "1",
                        f"Unrecognized domain guard: {task_id}")
                kinds["domain"] += 1
            else:
                kinds["unconditional"] += 1
            continue
        require(consumed == offsets, f"Task body bytes differ from guard: {task_id}")
        require(all(initial.get(str(x)) == "255" for x in offsets), "Non-activity byte in compute guard")
        require(consumed_all.isdisjoint(offsets), "Activity byte owned by multiple tasks")
        consumed_all.update(offsets)
        kinds["activity"] += 1
        lengths[len(offsets)] += 1
        ordered = sorted(offsets)
        task_runs = []
        for offset in ordered:
            if task_runs and offset == task_runs[-1][-1] + 1:
                task_runs[-1].append(offset)
            else:
                task_runs.append([offset])
        task_chunks = Counter()
        for run in task_runs:
            runs[len(run)] += 1
            remaining = len(run)
            for width in (8, 4, 2, 1):
                count, remaining = divmod(remaining, width)
                task_chunks[width] += count
        chunks.update(task_chunks)
        if sum(task_chunks.values()) < len(offsets):
            qualifying.append({"task": int(task_id), "offsets": offsets,
                               "packed_loads": sum(task_chunks.values())})
    require(consumed_all == {int(x) for x, value in initial.items() if value == "255"},
            "Activity ownership differs from initialized activity flags")
    byte_terms = sum(n * count for n, count in lengths.items())
    packed_terms = sum(chunks.values())
    return {
        "runtime_bytes": runtime_bytes,
        "tasks": len(calls), "task_kinds": dict(kinds),
        "activity_guard_length_histogram": dict(sorted(lengths.items())),
        "consecutive_run_histogram": dict(sorted(runs.items())),
        "packed_load_width_histogram": dict(sorted(chunks.items())),
        "activity_scalar_terms": byte_terms, "activity_packed_terms": packed_terms,
        "saved_terms": byte_terms - packed_terms,
        "saved_activity_term_percent": 100 * (byte_terms - packed_terms) / byte_terms if byte_terms else 0,
        "qualifying_tasks": qualifying,
        "checks": "PASS: dispatch/files/body/initialization/bounds/unique ownership",
        "scope": "Static source predicates only; no runtime timing or instruction-count claim",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True, help="Generated model .cpp (unpacked tasks)")
    args = parser.parse_args()
    print(json.dumps(analyze(args.model), indent=2))
