#!/usr/bin/env python3
"""Loop driver: repeatedly run Kimi Code CLI non-interactive goal mode.

Each iteration invokes `kimi -p PROMPT` (exec/print mode) from the repository
root with the fixed instruction:

    /goal 按照 pdocs/grhsim-ir-xiangshan-coremark.goal.md，若工作区有尚未完成终态的节点则继续完成该节点，否则完成下一个新节点

Prompt-mode goal exit codes (per official docs):
    0 = goal completed, 3 = goal blocked, 6 = goal paused.
Every outcome simply advances to the next iteration: the instruction itself
tells the next run to resume an unfinished node or start a new one.

Per-run logs and an index (runs.jsonl) are written under ptmp/kimi-goal-loop/.
Ctrl-C stops the loop (the child receives the same SIGINT and shuts down).

Docs: https://www.kimi.com/code/docs/en/kimi-code-cli/guides/goals.html
      https://www.kimi.com/code/docs/en/kimi-code-cli/reference/kimi-command.html

Usage:
    python3 pdocs/kimi_goal_loop.py                 # loop forever
    python3 pdocs/kimi_goal_loop.py --max-runs 3    # stop after 3 runs
    python3 pdocs/kimi_goal_loop.py --sleep 60      # 60 s between runs
    python3 pdocs/kimi_goal_loop.py --timeout 7200  # kill a run after 2 h
    python3 pdocs/kimi_goal_loop.py --dry-run       # print command, do not run
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROMPT = (
    "/goal 按照 pdocs/grhsim-ir-xiangshan-coremark.goal.md，"
    "若工作区有尚未完成终态的节点则继续完成该节点，否则完成下一个新节点"
)

ROOT = Path(__file__).resolve().parent.parent
GOAL_DOC = ROOT / "pdocs" / "grhsim-ir-xiangshan-coremark.goal.md"
LOG_DIR = ROOT / "ptmp" / "kimi-goal-loop"

EXIT_LABELS = {0: "complete", 3: "blocked", 6: "paused"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max-runs", type=int, default=0,
                        help="stop after N runs (default: 0 = unlimited)")
    parser.add_argument("--sleep", type=float, default=5.0,
                        help="seconds to wait between runs (default: 5)")
    parser.add_argument("--timeout", type=float, default=0.0,
                        help="kill a single run after N seconds (default: 0 = no limit)")
    parser.add_argument("--kimi", default="kimi",
                        help="path to the kimi CLI binary (default: 'kimi' from PATH)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the command and exit without running")
    return parser.parse_args()


def run_once(args: argparse.Namespace, run_id: str, log_path: Path) -> dict:
    command = [args.kimi, "-p", PROMPT]
    record = {"run_id": run_id, "command": command, "cwd": str(ROOT),
              "log": str(log_path), "started_at": datetime.now().isoformat(timespec="seconds")}
    start = time.monotonic()
    timed_out = False
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"# command: {' '.join(command)}\n# cwd: {ROOT}\n")
        try:
            process = subprocess.Popen(
                command, cwd=ROOT, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1,
            )
        except FileNotFoundError:
            log.write(f"kimi binary not found: {args.kimi}\n")
            record.update(exit_code=None, label="kimi-not-found", duration_s=0.0)
            return record
        try:
            deadline = start + args.timeout if args.timeout > 0 else None
            assert process.stdout is not None
            while True:
                line = process.stdout.readline()
                if line:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                    log.write(line)
                elif process.poll() is not None:
                    break
                if deadline is not None and time.monotonic() > deadline:
                    timed_out = True
                    process.kill()
        except KeyboardInterrupt:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
            record.update(exit_code=None, label="interrupted",
                          duration_s=round(time.monotonic() - start, 1))
            raise
        exit_code = process.wait()
    label = "timeout" if timed_out else EXIT_LABELS.get(exit_code, f"exit-{exit_code}")
    record.update(exit_code=exit_code, label=label,
                  duration_s=round(time.monotonic() - start, 1))
    return record


def main() -> int:
    args = parse_args()
    if args.dry_run:
        print(f"cd {ROOT} && {args.kimi} -p {PROMPT!r}")
        return 0
    if not GOAL_DOC.is_file():
        print(f"warning: goal doc not found: {GOAL_DOC}", file=sys.stderr)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    index_path = LOG_DIR / "runs.jsonl"

    run_number = 0
    while True:
        run_number += 1
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + f"-r{run_number:04d}"
        log_path = LOG_DIR / f"run-{run_id}.log"
        print(f"=== run {run_number} ({run_id}) -> {log_path} ===", flush=True)
        try:
            record = run_once(args, run_id, log_path)
        except KeyboardInterrupt:
            print("\nloop interrupted by user", flush=True)
            return 130
        with index_path.open("a", encoding="utf-8") as index:
            index.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"=== run {run_number} finished: {record['label']} "
              f"(exit={record['exit_code']}, {record['duration_s']}s) ===", flush=True)
        if record["label"] == "kimi-not-found":
            return 2
        if args.max_runs and run_number >= args.max_runs:
            return 0
        time.sleep(args.sleep)


if __name__ == "__main__":
    sys.exit(main())
