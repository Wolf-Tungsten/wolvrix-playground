"""VRT CLI transport display; no workflow or repository decisions."""
import os
import sys
import threading
import time
import unicodedata
from collections import deque

def terminal_size() -> tuple[int, int]:
    """返回 (cols, rows)。直接 ioctl 查询 stdout 的 pty，窗口缩放即时生效；
    不读 COLUMNS/LINES 环境变量——进程启动后它们不会随缩放更新。
    注意 shutil/os.get_terminal_size 返回的是 (columns, lines)，别解包反了。
    """
    try:
        size = os.get_terminal_size(sys.stdout.fileno())
        return size.columns, size.lines
    except OSError:
        return 100, 30


class UI:
    """TUI 看板：顶部固定状态头 + 下方滚动日志区。

    用终端滚动区域（DECSTBM）实现：头部固定在前 HEADER_LINES 行，由定时线程
    每 0.5 秒按当前终端大小重绘（窗口缩放即时生效）；CLI 输出在下方滚动区域内
    原样透传（保留其 ANSI 颜色序列），被滚动区域隔离，不会冲乱头部布局。
    """

    HEADER_LINES = 5

    def __init__(self, use_tui: bool):
        self.use_tui = use_tui
        self.write_lock = threading.Lock()
        self.status: dict[str, str] = {}
        self.artifacts: deque[str] = deque(maxlen=6)
        self.start_time = time.monotonic()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- 生命周期 -----------------------------------------------------------

    def start(self) -> None:
        if not self.use_tui:
            return
        with self.write_lock:
            # 先向下腾出头部空间，再把滚动区域设定为头部以下
            sys.stdout.write("\n" * self.HEADER_LINES)
            sys.stdout.write("\x1b[?25l")
            sys.stdout.flush()
        self._draw_header()
        self._thread = threading.Thread(target=self._render_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self.use_tui:
            return
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        with self.write_lock:
            _, rows = terminal_size()
            sys.stdout.write("\x1b[r")             # 恢复整屏滚动
            sys.stdout.write(f"\x1b[{rows};1H")   # 光标移到最底部
            sys.stdout.write("\x1b[?25h")          # 恢复光标
            sys.stdout.flush()

    # -- 输出 ---------------------------------------------------------------

    def log(self, line: str) -> None:
        line = line.rstrip("\n")
        if not self.use_tui:
            print(line, flush=True)
            return
        with self.write_lock:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()

    def info(self, msg: str) -> None:
        self.log(f"[vrt] {msg}")

    def set_status(self, **kv: str) -> None:
        with self.write_lock:
            self.status.update({k: str(v) for k, v in kv.items()})

    def add_artifact(self, path: str) -> None:
        with self.write_lock:
            self.artifacts.append(path)

    # -- 头部定时重绘 --------------------------------------------------------

    @staticmethod
    def _fit(line: str, cols: int) -> str:
        """按显示宽度截断（CJK 计 2 列），防止换行冲乱头部；截断时以 … 收尾示意。"""
        width = 0
        end = 0
        for ch in line:
            width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
            if width > cols:
                break
            end += 1
        if end == len(line) or cols < 2:
            return line[:end]
        width = 0
        end = 0
        for ch in line:
            w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
            if width + w > cols - 1:  # 预留 1 列给省略号
                break
            width += w
            end += 1
        return line[:end] + "…"

    def _render_loop(self) -> None:
        while not self._stop.is_set():
            self._draw_header()
            self._stop.wait(0.5)

    def _draw_header(self) -> None:
        cols, rows = terminal_size()
        if rows < self.HEADER_LINES + 2:
            return
        with self.write_lock:
            st = dict(self.status)
            arts = list(self.artifacts)
        elapsed = time.strftime("%H:%M:%S",
                                time.gmtime(time.monotonic() - self.start_time))
        header = [
            "VRT 看板  任务={job}  周次={week}  CLI={cli}  已运行={elapsed}".format(
                job=st.get("job", "-"), week=st.get("week", "-"),
                cli=st.get("cli", "-"), elapsed=elapsed),
            "当前动作: {action}   分支: {branch}".format(
                action=st.get("action", "-"), branch=st.get("branch", "-")),
            "工时: {hours}".format(hours=st.get("hours", "-")),
            "最近产出: {arts}".format(arts=", ".join(arts[-4:]) if arts else "-"),
            "─" * min(cols, 100),
        ]
        out = ["\x1b7"]                              # 保存日志区光标
        out.append(f"\x1b[{self.HEADER_LINES + 1};{rows}r")  # 滚动区域
        for i, line in enumerate(header, 1):
            out.append(f"\x1b[{i};1H" + self._fit(line, cols - 1) + "\x1b[K")
        out.append("\x1b8")                          # 恢复日志区光标
        with self.write_lock:
            sys.stdout.write("".join(out))
            sys.stdout.flush()


