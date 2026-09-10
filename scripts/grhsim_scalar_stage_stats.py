#!/usr/bin/env python3
"""Count typed shadow-stage sites in an unpacked GrhSIM-IR C++ model."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re


SCALAR_TYPES = {"bool"} | {
    f"std::{sign}int{width}_t" for sign in ("", "u") for width in (8, 16, 32, 64)
}
STAGE = re.compile(
    r"cpu_stage<([^\n;]+?)>\((\d+),(\d+),(\d+),(\d+),(true|false)\)([=;])"
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def analyze(model):
    task_files = list(model.parent.glob(f"{model.stem}_task_*.cpp"))
    require(bool(task_files), "No task files found")
    task_ids = set()
    kinds = Counter()
    scalar_kinds = Counter()
    types = Counter()
    scalar_projection = Counter()
    states = {}
    scalar_states = set()
    scalar_tasks = set()
    state_sites = Counter()
    state_tasks = defaultdict(set)
    direct_commits = 0
    excluded = Counter()
    for path in task_files:
        body = path.read_text()
        definitions = re.findall(r"::cpu_task_(\d+)\(\)\{", body)
        task_id = path.stem.rsplit("_", 1)[1]
        require(definitions == [task_id], f"Expected one matching task definition: {path.name}")
        require(task_id not in task_ids, "Repeated task ID")
        task_ids.add(task_id)
        matches = list(STAGE.finditer(body))
        require(len(matches) == body.count("cpu_stage<"), f"Unsupported stage expression: {path.name}")
        direct_commits += body.count("// cpu_direct_commit state=")
        excluded["byte_range_stage_sites"] += body.count("cpu_stage_bytes(")
        excluded["memory_cell_stage_sites"] += body.count("cpu_stage_cell(")
        for match in matches:
            cpp_type, state, offset, begin, count, projection, suffix = match.groups()
            state = int(state)
            kind = "full_assignment" if suffix == "=" else "masked_reference"
            if kind == "masked_reference":
                require(body[max(0, match.start() - 20):match.start()].endswith("auto &cpu_next="),
                        "Unexpected reference use; audit emitter before counting")
            metadata = (cpp_type, int(offset), int(begin), int(count), projection)
            require(state not in states or states[state] == metadata, "Inconsistent state metadata")
            states[state] = metadata
            kinds[kind] += 1
            types[cpp_type] += 1
            if cpp_type in SCALAR_TYPES:
                scalar_kinds[kind] += 1
                scalar_projection[projection] += 1
                scalar_states.add(state)
                scalar_tasks.add(task_id)
                state_sites[state] += 1
                state_tasks[state].add(task_id)
    calls = re.findall(r"cpu_task_(\d+)\(\);", model.read_text())
    require(len(calls) == len(set(calls)) and set(calls) == task_ids,
            "Dispatch IDs differ from task files; use scalar direct-dispatch model")
    scalar_total = sum(scalar_kinds.values())
    return {
        "task_files_and_calls": len(task_ids),
        "typed_stage_sites": sum(kinds.values()), "typed_stage_kinds": dict(kinds),
        "typed_stage_types": dict(sorted(types.items())),
        "typed_stage_distinct_states": len(states),
        "candidate_scalar_sites": scalar_total, "candidate_scalar_kinds": dict(scalar_kinds),
        "candidate_scalar_distinct_states": len(scalar_states),
        "candidate_scalar_task_count": len(scalar_tasks),
        "candidate_scalar_projection_sites": dict(scalar_projection),
        "candidate_scalar_zero_fanout_states": sum(states[s][3] == 0 for s in scalar_states),
        "candidate_scalar_states_with_repeated_sites": sum(n > 1 for n in state_sites.values()),
        "candidate_scalar_states_in_multiple_tasks": sum(len(tasks) > 1 for tasks in state_tasks.values()),
        "candidate_scalar_fraction_of_typed_sites_percent": 100 * scalar_total / sum(kinds.values()) if kinds else 0,
        "existing_direct_commit_sites": direct_commits,
        "other_staging_sites_excluded": dict(excluded),
        "checks": "PASS: task/dispatch coverage, typed-call coverage, state metadata consistency",
        "scope": "Static sites, including mutually exclusive or repeated paths; no execution frequency or timing",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(analyze(args.model), indent=2))
