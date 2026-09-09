"""Inbox concurrency and terminal integration tests, run by run_vrt_selftest."""
from __future__ import annotations

import fcntl
import json
import os
import pty
import select
import signal
import struct
import subprocess
import sys
import termios
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def runtime_tests(root: Path, sandbox: Path, check) -> None:
    from runner_inbox import Inbox
    from runner_ui import UI
    from runner_ui_view import TerminalView, cell_width, wrap

    directory = sandbox / "runtime"
    directory.mkdir(parents=True, exist_ok=True)
    inbox = Inbox(directory / "inbox.txt")
    inbox.path.write_text("", encoding="utf-8")
    inbox.history_path.unlink(missing_ok=True)
    with ThreadPoolExecutor(max_workers=12) as pool:
        jobs = []
        for i in range(80):
            jobs.append(pool.submit(inbox.append, f"命令-{i}"))
            if i % 7 == 0:
                jobs.append(pool.submit(inbox.consume, f"agent-{i}"))
        for job in jobs:
            job.result()
    inbox.consume("final")
    history = inbox.snapshot()["history"]
    consumed = [line for event in history for line in event["text"].splitlines()]
    check(sorted(consumed) == sorted(f"命令-{i}" for i in range(80)),
          "并发追加和领取不丢消息、不重复领取")
    check(not inbox.snapshot()["pending"] and not inbox.consume("again"),
          "消费清空 inbox，空轮询不重复生成回执")
    ui = UI(False, inbox)
    ui.handle_input("先跑测式\x7f试")
    check(ui.model.snapshot()["draft"] == "先跑测试" and not inbox.snapshot()["pending"],
          "中文草稿与退格可见，Enter 前不发布半条消息")
    ui.handle_input("\x1b[")
    ui.handle_input("D再\x1b[F\r")
    check(inbox.snapshot()["pending"] == "先跑测再试\n" and not ui.model.snapshot()["draft"],
          "分段方向键编辑，Enter 同步 inbox 并清空草稿")
    ui.handle_input("\x1b[200~两行\n不要提前发送\x1b[201~")
    check(ui.model.snapshot()["draft"] == "两行\n不要提前发送"
          and "两行" not in inbox.snapshot()["pending"], "括号粘贴中的换行不触发发送")
    ui.handle_input("\r")
    inbox.consume("ENGINEER/demo")
    ui._refresh_inbox()
    check(not ui.model.snapshot()["pending"]
          and ui.model.snapshot()["history"][-1]["actor"] == "ENGINEER/demo",
          "Agent 领取后 UI 同步空文件及带角色的消费记录")
    inbox.path.write_text("外部编辑的追加要求", encoding="utf-8")
    ui._refresh_inbox()
    check(ui.model.snapshot()["pending"] == "外部编辑的追加要求", "外部文件修改同步到 inbox 面板")

    view = TerminalView()
    ui.set_status(job="窄屏测试", week="3", cli="codex", action="ENGINEER 执行长任务",
                  cwd="/very/long/" + "nested/" * 20 + "END_OF_PATH",
                  hours="RA1:2/6 RA2:4/6 RA3:0/6")
    ui.add_artifact("ENGINEER: returned END_OF_RECEIPT")
    ui.model.edit("输入中文 e\u0301 " * 80)
    ui.model.logs.append("\x1b[31m日志内容\x1b[0m" * 50)
    for cols, rows in [(100, 30), (40, 24), (20, 16), (10, 8), (2, 4)]:
        state = ui.model.snapshot()
        frame = view.layout(state, cols, rows)
        check(len(frame) == rows and all(sum(cell_width(c) for c in line) <= cols - 1
                                        for line in frame), f"布局适配 {cols}x{rows}，不越界")
    pages = []
    for index in range(100):
        state = ui.model.snapshot()
        state["dashboard_page"] = index
        pages.extend(view.layout(state, 24, 20))
    joined = "".join(pages)
    check("END_OF_PATH" in joined and "END_OF_RECEIPT" in joined,
          "窄屏看板自动换行，长路径及回执末尾可翻页查看")
    text = "中文窄屏 e\u0301 /long/path" * 10
    check("".join(wrap(text, 17)) == text, "中文、组合字符和长单词换行不丢内容")
    state = ui.model.snapshot()
    check(any("▏" in line for line in view.layout(state, 24, 20)), "长草稿保持插入光标可见")
    state.update(draft="x" * 21, cursor=21)
    check(any("▏" in line for line in view.layout(state, 24, 12)), "草稿恰好填满一行时光标仍可见")
    for _ in range(100):
        ui.handle_input("\x1b[6~")
    last = ui.model.snapshot()["dashboard_page"]
    ui.handle_input("\x1b[5~")
    check(ui.model.snapshot()["dashboard_page"] == max(0, last - 1),
          "翻页到末尾后可立即向前翻页")
    terminal_test(root, directory, check)


def terminal_test(root: Path, directory: Path, check) -> None:
    """Use a real PTY, including split UTF-8, resize and terminal restoration."""
    driver = directory / "terminal_driver.py"
    driver.write_text('''import sys, time
from pathlib import Path
from runner_ui import UI
from runner_inbox import Inbox
root = Path(sys.argv[1])
ui = UI(True, Inbox(root / "terminal-inbox.txt"))
ui.set_status(job="PTY测试", week="1", action="运行中")
ui.start()
(root / "ready").touch()
try:
    while not (root / "stop").exists():
        ui.log("并行日志，不应抢走键盘输入")
        time.sleep(0.05)
finally:
    ui.stop()
''', encoding="utf-8")
    for name in ("ready", "stop", "terminal-inbox.txt", "terminal-inbox-history.jsonl"):
        (directory / name).unlink(missing_ok=True)
    master, slave = pty.openpty()
    before = termios.tcgetattr(slave)
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 60, 0, 0))
    env = {**os.environ, "PYTHONPATH": str(root / "vrt/workflow"), "PYTHONDONTWRITEBYTECODE": "1"}
    child = subprocess.Popen([sys.executable, str(driver), str(directory)],
                             stdin=slave, stdout=slave, stderr=slave, env=env)
    output = bytearray()

    def pump_until(predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if select.select([master], [], [], 0.05)[0]:
                output.extend(os.read(master, 65536))
            if predicate():
                return
        raise AssertionError("PTY 等待超时: " + output.decode("utf-8", errors="replace")[-1000:])

    try:
        pump_until(lambda: (directory / "ready").exists())
        message = "运行中追加命令".encode("utf-8")
        os.write(master, message[:2])
        pump_until(lambda: True)
        os.write(master, message[2:])
        pump_until(lambda: "运行中追加命令".encode() in output)
        check(not (directory / "terminal-inbox.txt").read_text(), "PTY 输入即时可见且尚未发布")
        os.write(master, b"\r")
        pump_until(lambda: "运行中追加命令" in (directory / "terminal-inbox.txt").read_text())
        check(True, "真实终端中文分段输入和 Enter 提交成功")
        from runner_inbox import Inbox
        inbox = Inbox(directory / "terminal-inbox.txt")
        output.clear()
        inbox.consume("PTY-agent")
        pump_until(lambda: "已领取".encode() in output)
        check(True, "真实终端实时显示 Agent 消费状态")
        output.clear()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 18, 24, 0, 0))
        pump_until(lambda: b"\x1b[18;1H" in output)
        check(b"\x1b[24;1H" not in output, "窗口缩窄后重新布局到实际屏幕高度")
        (directory / "stop").touch()
        pump_until(lambda: child.poll() is not None)
        check(child.returncode == 0 and termios.tcgetattr(slave) == before,
              "正常退出恢复终端 canonical/echo 设置")
        check(b"\x1b[?2004l" in output and b"\x1b[?1049l" in output,
              "退出关闭括号粘贴并恢复原屏幕")
        (directory / "stop").unlink()
        (directory / "ready").unlink()
        child = subprocess.Popen([sys.executable, str(driver), str(directory)],
                                 stdin=slave, stdout=slave, stderr=slave, env=env)
        pump_until(lambda: (directory / "ready").exists())
        child.send_signal(signal.SIGINT)
        pump_until(lambda: child.poll() is not None)
        check(child.returncode != 0 and termios.tcgetattr(slave) == before,
              "SIGINT 中断同样恢复终端 canonical/echo 设置")
    finally:
        if child.poll() is None:
            child.send_signal(signal.SIGTERM)
            child.wait(timeout=5)
        os.close(master)
        os.close(slave)
