"""Thread-safe display state, independent of terminals and workflow decisions."""
from __future__ import annotations

import threading
import time
from collections import deque


class UIModel:
    def __init__(self):
        self.lock = threading.RLock()
        self.status: dict[str, str] = {}
        self.artifacts: deque[str] = deque(maxlen=6)
        self.logs: deque[str] = deque(maxlen=2000)
        self.started = time.monotonic()
        self.pending = ""
        self.history: list[dict] = []
        self.draft = ""
        self.cursor = 0
        self.dashboard_page = 0
        self.inbox_page = 0
        self.log_offset = 0
        self.notice = "Enter 提交；未提交草稿不会被领取"

    def snapshot(self) -> dict:
        with self.lock:
            return {"status": dict(self.status), "artifacts": list(self.artifacts),
                    "logs": list(self.logs), "elapsed": int(time.monotonic() - self.started),
                    "pending": self.pending, "history": list(self.history),
                    "draft": self.draft, "cursor": self.cursor,
                    "dashboard_page": self.dashboard_page, "inbox_page": self.inbox_page,
                    "log_offset": self.log_offset, "notice": self.notice}

    def edit(self, text: str) -> None:
        with self.lock:
            self.draft = self.draft[:self.cursor] + text + self.draft[self.cursor:]
            self.cursor += len(text)

    def backspace(self) -> None:
        with self.lock:
            if self.cursor:
                self.draft = self.draft[:self.cursor - 1] + self.draft[self.cursor:]
                self.cursor -= 1
