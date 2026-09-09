"""MVC controller: terminal lifecycle, keyboard events and shared inbox I/O."""
from __future__ import annotations

import codecs
import os
import select
import signal
import sys
import termios
import threading
import tty

from runner_inbox import Inbox
from runner_ui_model import UIModel
from runner_ui_view import TerminalView, plain


def terminal_size() -> tuple[int, int]:
    try:
        size = os.get_terminal_size(sys.stdout.fileno())
        return size.columns, size.lines
    except (OSError, ValueError):
        return 100, 30


class UI:
    def __init__(self, use_tui: bool, inbox: Inbox | None = None):
        self.use_tui = use_tui
        self.inbox = inbox
        self.model = UIModel()
        self.view = TerminalView()
        self.write_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._input_fd: int | None = None
        self._terminal_fd: int | None = None
        self._term_attrs = None
        self._keys = ""
        self._paste = False
        self._last_frame = ""
        self._inbox_stamp = None

    @property
    def status(self) -> dict[str, str]:
        return self.model.snapshot()["status"]

    def start(self) -> None:
        if not self.use_tui:
            return
        try:
            if sys.stdin.isatty():
                self._input_fd = sys.stdin.fileno()
                self._terminal_fd = self._input_fd
                self._term_attrs = termios.tcgetattr(self._input_fd)
                tty.setcbreak(self._input_fd)
            with self.write_lock:
                sys.stdout.write("\x1b[?1049h\x1b[2J\x1b[?25l\x1b[?2004h")
                sys.stdout.flush()
            self._refresh_inbox()
            self._draw_header()
            self._thread = threading.Thread(target=self._event_loop, daemon=True)
            self._thread.start()
        except BaseException:
            self.stop()
            raise

    def stop(self) -> None:
        if not self.use_tui:
            return
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        try:
            if self._term_attrs is not None:
                termios.tcsetattr(self._terminal_fd, termios.TCSADRAIN, self._term_attrs)
        finally:
            with self.write_lock:
                sys.stdout.write("\x1b[r\x1b[?2004l\x1b[?25h\x1b[?1049l")
                sys.stdout.flush()
        if self.model.snapshot()["draft"]:
            print("[vrt] 未提交草稿：" + plain(self.model.snapshot()["draft"]), flush=True)

    def log(self, line: str) -> None:
        line = line.rstrip("\n")
        if not self.use_tui:
            print(line, flush=True)
            return
        with self.model.lock:
            self.model.logs.append(plain(line))

    def info(self, msg: str) -> None:
        self.log(f"[vrt] {msg}")

    def set_status(self, **kv: str) -> None:
        with self.model.lock:
            self.model.status.update({k: str(v) for k, v in kv.items()})

    def add_artifact(self, path: str) -> None:
        with self.model.lock:
            self.model.artifacts.append(path)

    def _refresh_inbox(self) -> None:
        if self.inbox is None:
            return
        def stamp(path):
            try:
                st = path.stat()
                return st.st_ino, st.st_mtime_ns, st.st_size
            except FileNotFoundError:
                return None
        changed = (stamp(self.inbox.path), stamp(self.inbox.history_path))
        if changed == self._inbox_stamp:
            return
        snapshot = self.inbox.snapshot()
        with self.model.lock:
            if len(snapshot["history"]) > len(self.model.history):
                self.model.notice = "Agent 已领取指令（非完成）；Enter 继续发送"
            self.model.pending = snapshot["pending"]
            self.model.history = snapshot["history"]
        self._inbox_stamp = changed

    def _submit(self) -> None:
        with self.model.lock:
            if not self.model.draft.strip():
                return
            if self.inbox is None:
                self.model.notice = "未配置 inbox；草稿保留"
                return
            self.inbox.append(self.model.draft)
            self.model.draft = ""
            self.model.cursor = 0
            self.model.inbox_page = 0
            self.model.notice = "已写入 inbox，等待 Agent 领取；Enter 继续发送"
        self._refresh_inbox()

    def handle_input(self, text: str) -> None:
        """Incremental UTF-8/escape input; pasted newlines never send a draft."""
        self._keys += text
        sequences = {"\x1b[A": "up", "\x1b[B": "down", "\x1b[C": "right",
                     "\x1b[D": "left", "\x1b[H": "home", "\x1b[F": "end",
                     "\x1b[1~": "home", "\x1b[4~": "end", "\x1b[3~": "delete",
                     "\x1b[5~": "pageup", "\x1b[6~": "pagedown",
                     "\x1b[200~": "paste", "\x1b[201~": "endpaste"}
        while self._keys:
            if self._keys.startswith("\x1b"):
                sequence = next((s for s in sequences if self._keys.startswith(s)), None)
                if sequence:
                    self._keys = self._keys[len(sequence):]
                    action = sequences[sequence]
                    if action in ("paste", "endpaste"):
                        self._paste = action == "paste"
                    elif not self._paste:
                        self._navigate(action)
                    continue
                if any(s.startswith(self._keys) for s in sequences):
                    return
                self._keys = self._keys[1:]
                continue
            char, self._keys = self._keys[0], self._keys[1:]
            if self._paste:
                self.model.edit(plain(char.replace("\r", "\n")))
            elif char in ("\r", "\n"):
                self._submit()
            elif char in ("\x7f", "\b"):
                self.model.backspace()
            elif char == "\x15":
                with self.model.lock:
                    self.model.draft, self.model.cursor = "", 0
            elif char in ("\x02", "\x06"):
                with self.model.lock:
                    _, count = self.view.page_counts(self.model.snapshot(), *terminal_size())
                    current = min(self.model.inbox_page, count - 1)
                    self.model.inbox_page = min(count - 1, max(0, current + (1 if char == "\x06" else -1)))
            elif char == "\x03":
                os.kill(os.getpid(), signal.SIGINT)
            elif char.isprintable():
                self.model.edit(char)

    def _navigate(self, action: str) -> None:
        with self.model.lock:
            m = self.model
            if action == "left":
                m.cursor = max(0, m.cursor - 1)
            elif action == "right":
                m.cursor = min(len(m.draft), m.cursor + 1)
            elif action == "home":
                m.cursor = 0
            elif action == "end":
                m.cursor = len(m.draft)
            elif action == "delete":
                m.draft = m.draft[:m.cursor] + m.draft[m.cursor + 1:]
            elif action in ("pageup", "pagedown"):
                count, _ = self.view.page_counts(m.snapshot(), *terminal_size())
                current = min(m.dashboard_page, count - 1)
                m.dashboard_page = min(count - 1, max(0, current + (1 if action == "pagedown" else -1)))
            elif action in ("up", "down"):
                m.log_offset = max(0, m.log_offset + (1 if action == "up" else -1))

    def _event_loop(self) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        while not self._stop.is_set():
            try:
                if self._input_fd is not None:
                    ready, _, _ = select.select([self._input_fd], [], [], 0.1)
                    if ready:
                        data = os.read(self._input_fd, 4096)
                        if data:
                            self.handle_input(decoder.decode(data))
                        else:
                            self._input_fd = None
                else:
                    self._stop.wait(0.1)
                self._refresh_inbox()
                self._draw_header()
            except (OSError, ValueError) as exc:
                with self.model.lock:
                    self.model.notice = f"输入/inbox 错误，草稿保留：{exc}"
                self._draw_header()
                self._stop.wait(0.5)

    def _draw_header(self) -> None:
        cols, rows = terminal_size()
        frame = self.view.render(self.model.snapshot(), cols, rows)
        if frame != self._last_frame:
            with self.write_lock:
                sys.stdout.write(frame)
                sys.stdout.flush()
            self._last_frame = frame
