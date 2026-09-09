"""Pure terminal-width-aware layout. No I/O or state mutation."""
from __future__ import annotations

import re
import time
import unicodedata
from functools import lru_cache


ANSI = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]|\x1b[@-_]")


def plain(text: str) -> str:
    text = ANSI.sub("", text).replace("\t", "    ")
    return "".join(c for c in text if c == "\n" or not unicodedata.category(c).startswith("C"))


def cell_width(char: str) -> int:
    if unicodedata.combining(char):
        return 0
    return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1


@lru_cache(maxsize=4096)
def _wrapped(text: str, width: int) -> tuple[str, ...]:
    width = max(1, width)
    lines = []
    for logical in plain(text).split("\n"):
        line, used = "", 0
        for char in logical:
            size = cell_width(char)
            if used + size > width and line:
                lines.append(line)
                line, used = "", 0
            if size > width:
                char, size = "?", 1
            line += char
            used += size
        lines.append(line)
    return tuple(lines)


def wrap(text: str, width: int) -> list[str]:
    return list(_wrapped(text, width))


def page(lines: list[str], height: int, requested: int) -> tuple[list[str], str]:
    count = max(1, (len(lines) + height - 1) // height)
    index = min(max(0, requested), count - 1)
    start = index * height
    return (lines[start:start + height] + [""] * height)[:height], f"{index + 1}/{count}"


class TerminalView:
    def sections(self, state: dict) -> tuple[str, str]:
        st = state["status"]
        dashboard = "\n".join([
            f"VRT 看板  任务={st.get('job', '-')}  周次={st.get('week', '-')}"
            f"  CLI={st.get('cli', '-')}  已运行={time.strftime('%H:%M:%S', time.gmtime(state['elapsed']))}",
            f"当前动作: {st.get('action', '-')}   工作目录: {st.get('cwd', '-')}",
            f"工程调用（已用/配额）: {st.get('hours', '-')}",
            "最近回执: " + (", ".join(state["artifacts"][-4:]) or "-"),
        ])
        pending = state["pending"].rstrip("\n")
        inbox = "待处理:\n" + (pending or "（空）")
        if state["history"]:
            event = state["history"][-1]
            inbox += f"\n已领取（非完成） {event['time']} {event['actor']}:\n{event['text']}"
        else:
            inbox += "\n尚无消费记录"
        return dashboard, inbox

    def heights(self, rows: int) -> tuple[int, int, int, int]:
        draft = min(3, max(1, rows // 8))
        body = rows - draft - 5
        dashboard = max(1, body * 4 // 10)
        inbox = max(1, body * 3 // 10)
        return draft, dashboard, inbox, max(1, body - dashboard - inbox)

    def page_counts(self, state: dict, cols: int, rows: int) -> tuple[int, int]:
        dashboard, inbox = self.sections(state)
        width = max(1, cols - 1)
        _, dash_height, inbox_height, _ = self.heights(rows)
        if rows < 12:
            dashboard += "\n" + inbox
            dash_height = max(1, rows - 3)
        return tuple(max(1, (len(wrap(text, width)) + height - 1) // height)
                     for text, height in ((dashboard, dash_height), (inbox, inbox_height)))

    def layout(self, state: dict, cols: int, rows: int) -> list[str]:
        width = max(1, cols - 1)  # Avoid the terminal's pending autowrap.
        dashboard, inbox = self.sections(state)
        draft = state["draft"]
        cursor = state["cursor"]
        before = wrap("> " + draft[:cursor] + "▏", width)
        editing = wrap("> " + draft[:cursor] + "▏" + draft[cursor:], width)
        draft_height, dash_height, inbox_height, log_height = self.heights(rows)
        edit_start = max(0, len(before) - draft_height)
        edit_lines = editing[edit_start:edit_start + draft_height]
        edit_lines += [""] * (draft_height - len(edit_lines))
        if rows < 12:
            content, number = page(wrap(dashboard + "\n" + inbox, width),
                                   max(1, rows - 3), state["dashboard_page"])
            return (content + [wrap(f"PgUp/Dn {number}", width)[0], edit_lines[0],
                               wrap("Enter 提交", width)[0]])[:rows]
        dash_lines, dash_page = page(wrap(dashboard, width), dash_height,
                                     state["dashboard_page"])
        inbox_lines, inbox_page = page(wrap(inbox, width), inbox_height, state["inbox_page"])
        logs = [line for message in state["logs"] for line in wrap(message, width)]
        end = max(log_height, len(logs) - state["log_offset"])
        log_lines = logs[max(0, end - log_height):end]
        log_lines += [""] * (log_height - len(log_lines))
        label = lambda text: wrap(text, width)[0]
        return [label(f"── 看板 {dash_page} PgUp/Dn")] + dash_lines + [
            label(f"── inbox {inbox_page} Ctrl-B/F")] + inbox_lines + [
            label("── 日志 ↑/↓")] + log_lines + [
            label("── " + state["notice"])] + edit_lines + [
            label("Enter 发送 | Ctrl-U 清草稿 | Ctrl-C 退出")]

    def render(self, state: dict, cols: int, rows: int) -> str:
        return "".join(f"\x1b[{i};1H{line}\x1b[K" for i, line in enumerate(
            self.layout(state, cols, rows), 1))
