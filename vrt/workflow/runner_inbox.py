"""Shared, locked user inbox; no workflow decisions or command execution."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


class Inbox:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.history_path = self.path.with_name(self.path.stem + "-history.jsonl")
        self.lock_path = self.path.with_suffix(".lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._locked():
            self.path.touch(exist_ok=True)

    @contextmanager
    def _locked(self):
        # Lock a separate inode: editors may replace inbox.txt using rename.
        with self.lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def _history(self) -> list[dict]:
        if not self.history_path.exists():
            return []
        return [json.loads(line) for line in self.history_path.read_text(
            encoding="utf-8").splitlines() if line.strip()]

    def snapshot(self) -> dict:
        with self._locked():
            return {"pending": self.path.read_text(encoding="utf-8"),
                    "history": self._history()}

    def append(self, message: str) -> None:
        if not message.strip():
            return
        with self._locked():
            with self.path.open("a+", encoding="utf-8") as stream:
                stream.seek(0)
                existing = stream.read()
                if existing and not existing.endswith("\n"):
                    stream.write("\n")
                stream.write(message.rstrip("\n") + "\n")
                stream.flush()
                os.fsync(stream.fileno())

    def consume(self, actor: str) -> str:
        with self._locked():
            message = self.path.read_text(encoding="utf-8")
            if not message.strip():
                return ""
            event = {"time": datetime.now().astimezone().isoformat(),
                     "actor": actor, "text": message}
            # Preserve the instructions before clearing, including on a failed
            # CLI invocation. A crash here may redeliver, but cannot lose them.
            with self.history_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            with self.path.open("w", encoding="utf-8") as stream:
                stream.flush()
                os.fsync(stream.fileno())
            return message


def main() -> None:
    parser = argparse.ArgumentParser(description="VRT 用户 inbox（文本指令，不作为 shell 执行）")
    parser.add_argument("action", choices=("send", "consume", "show", "history"))
    parser.add_argument("--inbox", default=os.environ.get("VRT_INBOX"))
    parser.add_argument("--actor", default=os.environ.get("VRT_INBOX_ACTOR", "user"))
    args = parser.parse_args()
    if not args.inbox:
        parser.error("需要 --inbox 或 VRT_INBOX 环境变量")
    inbox = Inbox(Path(args.inbox))
    if args.action == "send":
        inbox.append(sys.stdin.read())
    elif args.action == "consume":
        print(inbox.consume(args.actor), end="")
    elif args.action == "show":
        print(inbox.snapshot()["pending"], end="")
    else:
        print(json.dumps(inbox.snapshot()["history"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
