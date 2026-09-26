#!/usr/bin/env python3
"""Loop driver: repeatedly run Kimi Code CLI non-interactive goal mode.

Each iteration invokes `kimi -p PROMPT` (exec/print mode) from the repository
root with the fixed instruction:

    /goal 按照 pdocs/grhsim-ir-xiangshan-coremark.goal.md，若工作区有尚未完成终态的节点则继续完成该节点，否则完成下一个新节点

Prompt-mode goal exit codes (per official docs):
    0 = goal completed, 3 = goal blocked, 6 = goal paused.
Every outcome simply advances to the next iteration: the instruction itself
tells the next run to resume an unfinished node or start a new one.

A run that exceeds --timeout seconds (default: 2 hours) is killed outright —
SIGKILL to its whole process group — and the loop continues with the next task.

TUI: when stdout is a terminal (and --no-tui is not given), a fixed status bar
occupies the top of the screen with a countdown progress bar showing how long
the current run has left before it is killed; the kimi CLI output scrolls in
the region below. With --timeout 0 the bar shows elapsed time only. The bar
adapts to the terminal width: on narrow terminals less important fields
(verbose labels, the wall-clock kill time) are moved onto the progress line or
dropped entirely instead of being cut off mid-text. When stdout is not a TTY
the script falls back to plain streaming output.

Per-run logs and an index (runs.jsonl) are written under ptmp/kimi-goal-loop/.
Ctrl-C stops the loop (the child's process group is terminated as well).

Docs: https://www.kimi.com/code/docs/en/kimi-code-cli/guides/goals.html
      https://www.kimi.com/code/docs/en/kimi-code-cli/reference/kimi-command.html

Usage:
    python3 pdocs/kimi_goal_loop.py                 # loop forever
    python3 pdocs/kimi_goal_loop.py --max-runs 3    # stop after 3 runs
    python3 pdocs/kimi_goal_loop.py --sleep 60      # 60 s between runs
    python3 pdocs/kimi_goal_loop.py --timeout 7200  # kill a run after 2 h (default: 2 h)
    python3 pdocs/kimi_goal_loop.py --no-tui        # plain streaming output
    python3 pdocs/kimi_goal_loop.py --dry-run       # print command, do not run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
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

# CSI sequences ending in 'm' (SGR colors) are kept; every other CSI/OSC
# sequence from the child is dropped so it cannot break the TUI layout.
_CSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


def sanitize_output(text: str) -> str:
    text = _OSC_RE.sub("", text)
    return _CSI_RE.sub(lambda m: m.group(0) if m.group(0).endswith("m") else "", text)


def fmt_hms(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max-runs", type=int, default=0,
                        help="stop after N runs (default: 0 = unlimited)")
    parser.add_argument("--sleep", type=float, default=5.0,
                        help="seconds to wait between runs (default: 5)")
    parser.add_argument("--timeout", type=float, default=2 * 3600.0,
                        help="kill a single run after N seconds (default: 7200 = 2 h; 0 = no limit)")
    parser.add_argument("--kimi", default="kimi",
                        help="path to the kimi CLI binary (default: 'kimi' from PATH)")
    parser.add_argument("--no-tui", action="store_true",
                        help="disable the TUI and stream plain output")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the command and exit without running")
    return parser.parse_args()


class TermUI:
    """Fixed countdown bar on top; child output scrolls in the region below.

    All terminal writes go through ``_lock``. The bar is redrawn by a daemon
    thread every 0.25 s using DEC save/restore cursor so the output cursor in
    the scroll region is never disturbed.
    """

    BAR_LINES = 3

    def __init__(self, stream, enabled: bool) -> None:
        self.stream = stream
        self.enabled = enabled
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._render_thread: threading.Thread | None = None
        self._cols, self._rows = shutil.get_terminal_size(fallback=(80, 24))
        self._title = "starting"
        # phase: ("idle",) | ("run", start_mono, timeout_s, kill_at_wall)
        #        | ("sleep", start_mono, seconds, wake_at_wall)
        self._phase: tuple = ("idle",)
        self._utf8 = "UTF" in (getattr(stream, "encoding", None) or "").upper()
        self._fill, self._empty = ("█", "░") if self._utf8 else ("#", "-")
        self._dash = "—" if self._utf8 else "-"

    # lifecycle -----------------------------------------------------------
    def start(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            self.stream.write("\x1b[?25l")  # hide cursor
            self.stream.write("\x1b[2J\x1b[H")  # clear screen
            self._apply_region_locked()
            self._render_locked()
            self.stream.flush()
        self._render_thread = threading.Thread(target=self._render_loop, daemon=True)
        self._render_thread.start()

    def close(self) -> None:
        if not self.enabled:
            return
        self._stop_event.set()
        if self._render_thread is not None:
            self._render_thread.join(timeout=2)
        with self._lock:
            self.stream.write("\x1b[r")  # reset scroll region
            self.stream.write(f"\x1b[{self._rows};1H\n")  # move below everything
            self.stream.write("\x1b[?25h")  # show cursor
            self.stream.flush()

    # state ---------------------------------------------------------------
    def begin_run(self, run_number: int, run_id: str, timeout_s: float) -> None:
        self._title = f"run #{run_number}  {run_id}"
        kill_at = time.time() + timeout_s if timeout_s > 0 else None
        self._phase = ("run", time.monotonic(), timeout_s, kill_at)

    def begin_sleep(self, seconds: float, next_run: int) -> None:
        self._title = f"between runs; next is run #{next_run}"
        self._phase = ("sleep", time.monotonic(), seconds, time.time() + seconds)

    def idle(self, text: str) -> None:
        self._title = text
        self._phase = ("idle",)

    # output --------------------------------------------------------------
    def write(self, text: str) -> None:
        if not self.enabled:
            self.stream.write(text)
            self.stream.flush()
            return
        with self._lock:
            self.stream.write(sanitize_output(text))
            self.stream.flush()

    # rendering -----------------------------------------------------------
    def _apply_region_locked(self) -> None:
        top = self.BAR_LINES + 1
        self.stream.write(f"\x1b[{top};{self._rows}r")
        self.stream.write(f"\x1b[{top};1H")

    def _render_loop(self) -> None:
        while not self._stop_event.wait(0.25):
            size = shutil.get_terminal_size(fallback=(80, 24))
            with self._lock:
                if (size.columns, size.lines) != (self._cols, self._rows):
                    self._cols, self._rows = size.columns, size.lines
                    self.stream.write("\x1b[r\x1b[2J")
                    self._apply_region_locked()
                self._render_locked()
                self.stream.flush()

    def _render_locked(self) -> None:
        self.stream.write("\x1b7")  # save cursor
        for index, line in enumerate(self._compose_bar()):
            self.stream.write(f"\x1b[{index + 1};1H\x1b[2K{line}")
        self.stream.write("\x1b8")  # restore cursor

    def _compose_bar(self) -> list[str]:
        cols = max(1, self._cols)
        phase = self._phase
        title = f" kimi goal loop {self._dash} {self._title}"
        lines: list[tuple[str, str]] = [(title, "1")]
        if phase[0] == "run":
            _, start, timeout_s, kill_at = phase
            elapsed = time.monotonic() - start
            if timeout_s > 0:
                remaining = max(0.0, timeout_s - elapsed)
                frac = min(1.0, elapsed / timeout_s)
                status, has_wall = self._run_status(elapsed, timeout_s,
                                                    remaining, kill_at, cols)
                suffix = "" if has_wall or not kill_at else f" at {self._wall_clock(kill_at)}"
                lines += [(status, ""), self._bar(frac, cols, suffix)]
            else:
                lines += [(f" elapsed {fmt_hms(elapsed)}   (no timeout)", ""), ("", "")]
        elif phase[0] == "sleep":
            _, start, seconds, wake_at = phase
            elapsed = time.monotonic() - start
            remaining = max(0.0, seconds - elapsed)
            frac = min(1.0, elapsed / seconds) if seconds > 0 else 1.0
            lines += [(f" next run in {remaining:0.1f}s", ""),
                      self._bar(frac, cols, f" at {self._wall_clock(wake_at)}")]
        else:
            lines += [("", ""), ("", "")]
        rendered = []
        for text, style in lines[: self.BAR_LINES]:
            fitted = self._fit(text, cols)
            rendered.append(f"\x1b[{style}m{fitted}\x1b[0m" if style and fitted else fitted)
        return rendered

    def _run_status(self, elapsed: float, timeout_s: float, remaining: float,
                    kill_at: float | None, cols: int) -> tuple[str, bool]:
        """Pick the most verbose status line that fits; bool = shows wall clock."""
        e, t, r = fmt_hms(elapsed), fmt_hms(timeout_s), fmt_hms(remaining)
        candidates = []
        if kill_at is not None:
            candidates.append(f" elapsed {e} / {t}   kill in {r} (at {self._wall_clock(kill_at)})")
        candidates += [f" elapsed {e} / {t}   kill in {r}",
                       f" {e} / {t}  kill in {r}"]
        for candidate in candidates:
            if len(candidate) <= cols:
                return candidate, "(at " in candidate
        return candidates[-1], False

    @staticmethod
    def _wall_clock(when: float) -> str:
        moment = datetime.fromtimestamp(when)
        if moment.date() != datetime.now().date():
            return moment.strftime("%m-%d %H:%M")
        return moment.strftime("%H:%M:%S")

    def _fit(self, text: str, cols: int) -> str:
        """Truncate to ``cols`` columns with an ellipsis marker if needed."""
        if len(text) <= cols:
            return text
        marker = "…" if self._utf8 else "..."
        if cols <= len(marker):
            return text[:cols]
        return text[: cols - len(marker)] + marker

    def _bar(self, frac: float, cols: int, suffix: str = "") -> tuple[str, str]:
        """Progress bar line and its SGR style; visible width is at most ``cols``."""
        width = cols - 10 - len(suffix)
        if suffix and width < 10:
            suffix = ""
            width = cols - 10
        width = max(1, width)
        filled = min(width, int(width * frac))
        body = f"{self._fill * filled}{self._empty * (width - filled)}"
        color = "32" if frac < 0.75 else ("33" if frac < 0.9 else "31")
        return f" [{body}] {frac * 100:5.1f}%{suffix}", color


def _signal_group(process: subprocess.Popen, sig: int) -> None:
    try:
        os.killpg(process.pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def kill_tree(process: subprocess.Popen) -> None:
    _signal_group(process, signal.SIGKILL)
    process.wait()


def terminate_tree(process: subprocess.Popen) -> None:
    _signal_group(process, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        kill_tree(process)


def run_once(args: argparse.Namespace, run_id: str, log_path: Path,
             ui: TermUI) -> dict:
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
                start_new_session=True,
            )
        except FileNotFoundError:
            log.write(f"kimi binary not found: {args.kimi}\n")
            record.update(exit_code=None, label="kimi-not-found", duration_s=0.0)
            return record

        def pump_output() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                ui.write(line)
                log.write(line)

        pump = threading.Thread(target=pump_output, daemon=True)
        pump.start()
        try:
            try:
                process.wait(timeout=args.timeout if args.timeout > 0 else None)
            except subprocess.TimeoutExpired:
                timed_out = True
                message = f"# timeout after {args.timeout}s; killing process group\n"
                log.write(message)
                ui.write(message)
                kill_tree(process)
        except KeyboardInterrupt:
            terminate_tree(process)
            record.update(exit_code=None, label="interrupted",
                          duration_s=round(time.monotonic() - start, 1))
            pump.join(timeout=5)
            raise
        pump.join(timeout=5)
        exit_code = process.returncode
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

    use_tui = (not args.no_tui and sys.stdout.isatty()
               and os.environ.get("TERM", "") not in ("", "dumb"))
    ui = TermUI(sys.stdout, use_tui)
    ui.start()

    run_number = 0
    try:
        while True:
            run_number += 1
            run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + f"-r{run_number:04d}"
            log_path = LOG_DIR / f"run-{run_id}.log"
            ui.write(f"=== run {run_number} ({run_id}) -> {log_path} ===\n")
            ui.begin_run(run_number, run_id, args.timeout)
            try:
                record = run_once(args, run_id, log_path, ui)
            except KeyboardInterrupt:
                ui.write("\nloop interrupted by user\n")
                return 130
            with index_path.open("a", encoding="utf-8") as index:
                index.write(json.dumps(record, ensure_ascii=False) + "\n")
            ui.write(f"=== run {run_number} finished: {record['label']} "
                     f"(exit={record['exit_code']}, {record['duration_s']}s) ===\n")
            if record["label"] == "kimi-not-found":
                return 2
            if args.max_runs and run_number >= args.max_runs:
                ui.idle("done")
                return 0
            ui.begin_sleep(args.sleep, run_number + 1)
            try:
                time.sleep(args.sleep)
            except KeyboardInterrupt:
                ui.write("\nloop interrupted by user\n")
                return 130
    finally:
        ui.close()


if __name__ == "__main__":
    sys.exit(main())
