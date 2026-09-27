#!/usr/bin/env python3
"""Loop driver: repeatedly run Codex CLI non-interactively.

Each iteration starts a fresh `codex exec` session from the repository root
with the fixed instruction (without Kimi's /goal command prefix):

    按照 pdocs/grhsim-ir-xiangshan-coremark.goal.md，若工作区有尚未完成终态的节点则继续完成该节点，否则完成下一个新节点

The default --approval bypass uses --dangerously-bypass-approvals-and-sandbox:
commands run without Codex sandboxing or approval prompts, including Git writes.
Use --approval auto-review for workspace-write with automatic approval review,
or --approval never for workspace-write without escalation (Git may be blocked).
--sandbox is available with --approval never; automatic review requires
workspace-write. Bypass cannot be combined with --sandbox.
Model and profile settings are inherited unless explicitly overridden.
Exit 0 means the CLI succeeded, not that a goal node reached a terminal state.
Other exit codes are logged literally; every outcome advances to the next run.
The instruction tells the next run to resume an unfinished node or start one.

A run that exceeds --timeout seconds (default: 2 hours) is killed outright —
SIGKILL to its whole process group — and the loop continues with the next task.

TUI: when stdout is a terminal (and --no-tui is not given), a fixed status bar
occupies the top of the screen with a countdown progress bar showing how long
the current run has left before it is killed; the Codex CLI output scrolls in
the region below. With --timeout 0 the bar shows elapsed time only. The bar
adapts to the terminal width: on narrow terminals less important fields
(verbose labels, the wall-clock kill time) are moved onto the progress line or
dropped entirely instead of being cut off mid-text. When stdout is not a TTY
the script falls back to plain streaming output.

Per-run logs and an index (runs.jsonl) are written under ptmp/codex-goal-loop/.
Ctrl-C stops the loop (the child's process group is terminated as well).

Docs: https://developers.openai.com/codex/noninteractive/
      https://developers.openai.com/codex/cli/reference/
      https://learn.chatgpt.com/docs/sandboxing/auto-review

Usage:
    make run_codex_goal_loop
    make run_codex_goal_loop CODEX_GOAL_LOOP_ARGS='--max-runs 3'
    make run_codex_goal_loop CODEX_GOAL_LOOP_ARGS='--sleep 60 --timeout 7200'
    make run_codex_goal_loop CODEX_GOAL_LOOP_ARGS='--model MODEL --profile PROFILE'
    make run_codex_goal_loop CODEX_GOAL_LOOP_ARGS='--no-tui'
    make run_codex_goal_loop CODEX_GOAL_LOOP_ARGS='--approval auto-review'
    make run_codex_goal_loop CODEX_GOAL_LOOP_ARGS='--approval never'
    make run_codex_goal_loop CODEX_GOAL_LOOP_ARGS='--dry-run'
"""

from __future__ import annotations

import argparse
import codecs
import json
import math
import os
import re
import selectors
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

PROMPT = (
    "按照 pdocs/grhsim-ir-xiangshan-coremark.goal.md，"
    "若工作区有尚未完成终态的节点则继续完成该节点，否则完成下一个新节点。"
    "本轮节点完成并通过文档要求的检查后，按文档暂存并提交本节点相关的代码、测试、报告与索引；"
    "涉及子模块时先提交子模块，再提交根仓库及子模块指针。"
    "保留无关改动，未完成节点不提前提交，不自动 push。"
    "本轮已授权上述节点的正常暂存和最终提交。"
    "若实际权限仍阻止 Git 写入，按当前运行模式支持的正式审批流程处理；"
    "没有可用审批流程或审批明确拒绝时记录原因并停止本轮，不绕过限制。"
)

ROOT = Path(__file__).resolve().parent.parent
GOAL_DOC = ROOT / "pdocs" / "grhsim-ir-xiangshan-coremark.goal.md"
LOG_DIR = ROOT / "ptmp" / "codex-goal-loop"

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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max-runs", type=int, default=0,
                        help="stop after N runs (default: 0 = unlimited)")
    parser.add_argument("--sleep", type=float, default=5.0,
                        help="seconds to wait between runs (default: 5)")
    parser.add_argument("--timeout", type=float, default=2 * 3600.0,
                        help="kill a single run after N seconds (default: 7200 = 2 h; 0 = no limit)")
    parser.add_argument("--codex", default="codex",
                        help="path to the Codex CLI binary (default: 'codex' from PATH)")
    parser.add_argument("--model", help="override the configured Codex model")
    parser.add_argument("--profile", help="use a named Codex configuration profile")
    parser.add_argument("--sandbox",
                        choices=("read-only", "workspace-write", "danger-full-access"),
                        help="sandbox for non-bypass modes (default: workspace-write)")
    parser.add_argument("--approval", default="bypass",
                        choices=("bypass", "auto-review", "never"),
                        help="bypass: disable Codex sandbox and approvals (default); "
                             "auto-review: review escalation automatically; "
                             "never: sandbox without escalation (may block Git writes)")
    parser.add_argument("--no-tui", action="store_true",
                        help="disable the TUI and stream plain output")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the command and exit without running")
    args = parser.parse_args(argv)
    if args.approval == "bypass" and args.sandbox is not None:
        parser.error("--sandbox cannot be combined with --approval bypass; "
                     "use --approval never or --approval auto-review")
    if args.approval == "auto-review" and args.sandbox not in (None, "workspace-write"):
        parser.error("--approval auto-review requires the workspace-write sandbox")
    if args.max_runs < 0:
        parser.error("--max-runs must be nonnegative")
    for name in ("sleep", "timeout"):
        value = getattr(args, name)
        if not math.isfinite(value) or value < 0:
            parser.error(f"--{name} must be finite and nonnegative")
    return args


def build_command(args: argparse.Namespace) -> list[str]:
    command = [args.codex, "exec"]
    if args.approval == "bypass":
        command += ["--dangerously-bypass-approvals-and-sandbox"]
    elif args.approval == "auto-review":
        # exec needs its dedicated flag; the top-level -a is not sufficient.
        command += ["--approve-for-me"]
    else:
        command += ["-c", 'approval_policy="never"',
                    "--sandbox", args.sandbox or "workspace-write"]
    command += ["--color", "never"]
    if args.model:
        command += ["--model", args.model]
    if args.profile:
        command += ["--profile", args.profile]
    return command + [PROMPT]


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
        title = f" codex goal loop {self._dash} {self._title}"
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
        pass
    # The leader may exit before descendants that ignore SIGTERM.
    kill_tree(process)


def run_once(args: argparse.Namespace, run_id: str, log_path: Path,
             ui: TermUI) -> dict:
    command = build_command(args)
    record = {"run_id": run_id, "command": command, "cwd": str(ROOT),
              "log": str(log_path), "started_at": datetime.now().isoformat(timespec="seconds")}
    start = time.monotonic()
    timed_out = False
    interrupted = False
    with log_path.open("w", encoding="utf-8", buffering=1) as log:
        log.write(f"# command: {shlex.join(command)}\n# cwd: {ROOT}\n")
        try:
            process = subprocess.Popen(
                command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            label = "codex-not-found" if isinstance(exc, FileNotFoundError) else "launch-error"
            message = f"cannot start Codex: {exc}\n"
            log.write(message)
            ui.write(message)
            record.update(exit_code=None, label=label, duration_s=0.0)
            return record

        assert process.stdout is not None
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

        def write_output(data: bytes, final: bool = False) -> None:
            text = decoder.decode(data, final=final)
            log.write(text)
            ui.write(text)

        # Poll output and the deadline together so silent children, partial
        # lines, and inherited pipes cannot prevent timeout enforcement.
        try:
            with selectors.DefaultSelector() as selector:
                os.set_blocking(process.stdout.fileno(), False)
                selector.register(process.stdout, selectors.EVENT_READ)
                while process.poll() is None:
                    wait_s = 0.25
                    if args.timeout > 0:
                        remaining = args.timeout - (time.monotonic() - start)
                        if remaining <= 0:
                            timed_out = True
                            message = f"# timeout after {args.timeout}s; killing process group\n"
                            log.write(message)
                            ui.write(message)
                            kill_tree(process)
                            break
                        wait_s = min(wait_s, remaining)
                    for key, _ in selector.select(wait_s):
                        data = os.read(key.fd, 65536)
                        if data:
                            write_output(data)
                        else:
                            selector.unregister(key.fileobj)
        except KeyboardInterrupt:
            interrupted = True
            terminate_tree(process)
        finally:
            # No background work from one iteration should overlap the next.
            kill_tree(process)
            while True:
                try:
                    data = os.read(process.stdout.fileno(), 65536)
                except BlockingIOError:
                    break
                if not data:
                    break
                write_output(data)
            write_output(b"", final=True)
            process.stdout.close()
        exit_code = process.returncode
    label = ("interrupted" if interrupted else "timeout" if timed_out
             else "success" if exit_code == 0 else f"exit-{exit_code}")
    record.update(exit_code=exit_code, label=label,
                  duration_s=round(time.monotonic() - start, 1))
    return record


def main() -> int:
    args = parse_args()
    if args.dry_run:
        print(f"cd {shlex.quote(str(ROOT))} && {shlex.join(build_command(args))}")
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
            run_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f") + f"-r{run_number:04d}"
            log_path = LOG_DIR / f"run-{run_id}.log"
            ui.write(f"=== run {run_number} ({run_id}) -> {log_path} ===\n")
            ui.begin_run(run_number, run_id, args.timeout)
            record = run_once(args, run_id, log_path, ui)
            with index_path.open("a", encoding="utf-8") as index:
                index.write(json.dumps(record, ensure_ascii=False) + "\n")
            ui.write(f"=== run {run_number} finished: {record['label']} "
                     f"(exit={record['exit_code']}, {record['duration_s']}s) ===\n")
            if record["label"] == "interrupted":
                ui.write("\nloop interrupted by user\n")
                return 130
            if record["label"] in ("codex-not-found", "launch-error"):
                return 2
            if args.max_runs and run_number >= args.max_runs:
                ui.idle("done")
                return 0
            ui.begin_sleep(args.sleep, run_number + 1)
            time.sleep(args.sleep)
    except KeyboardInterrupt:
        ui.write("\nloop interrupted by user\n")
        return 130
    finally:
        ui.close()


if __name__ == "__main__":
    sys.exit(main())
