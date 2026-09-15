"""Compare native instruction counts of generated GrhSIM CPU models."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import subprocess

from grhsim_cpu_profile import task_phases


def measure(flow):
    phases = task_phases(flow / "model/grhsim_SimTop.cpp")
    counts = defaultdict(Counter)
    tasks = defaultdict(Counter)
    group, task = "other", None
    command = ["objdump", "-d", "-C", "--no-show-raw-insn", str(flow / "emu/emu")]
    with subprocess.Popen(command, stdout=subprocess.PIPE, text=True) as process:
        for line in process.stdout:
            symbol = re.match(r"^[0-9a-f]+ <(.+)>:$", line)
            if symbol:
                match = re.fullmatch(r"\w+::cpu_task_(\d+)\(\)", symbol[1])
                task = int(match[1]) if match else None
                group = phases[task] if task is not None else (
                    "evaluator" if re.fullmatch(r"\w+::eval\(\)", symbol[1]) else "other")
                continue
            instruction = re.match(r"^\s+[0-9a-f]+:\s+(\S+)", line)
            if not instruction:
                continue
            mnemonic = instruction[1]
            row = Counter(instructions=1)
            if mnemonic.startswith("j"):
                row["jumps"] = 1
                if mnemonic not in ("jmp", "jmpq"):
                    row["conditional_jumps"] = 1
            elif mnemonic.startswith("call"):
                row["calls"] = 1
            counts[group].update(row)
            if task is not None:
                tasks[task].update(row)
        if process.wait():
            raise RuntimeError("objdump failed")
    if set(tasks) != set(phases):
        raise ValueError("native task coverage differs from generated schedule")
    size = subprocess.check_output(["size", str(flow / "emu/emu")], text=True).splitlines()[1].split()
    return {"elf_text_bytes": int(size[0]), "phase_counts": dict(counts), "tasks": dict(tasks)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    args = parser.parse_args()
    old, new = measure(args.old), measure(args.new)
    if old["tasks"].keys() != new["tasks"].keys():
        raise ValueError("task IDs differ; taskwise comparison is invalid")
    deltas = {task: new["tasks"][task]["conditional_jumps"] - row["conditional_jumps"]
              for task, row in old["tasks"].items()}
    selected = sorted(deltas, key=lambda task: (deltas[task], task))[:5]
    examples = {task: {"old": old["tasks"][task], "new": new["tasks"][task]} for task in selected}
    for item in (old, new):
        item["task_count"] = len(item.pop("tasks"))
    print(json.dumps({"old": old, "new": new, "largest_conditional_jump_reductions": examples,
                      "note": "Static instructions, not executed instructions or branch misses."}, indent=2))


if __name__ == "__main__":
    main()
