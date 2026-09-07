#!/usr/bin/env python3
"""VRT 每周工作调度脚本。

工作流定义见同目录 vrt-workflow.md。本脚本负责：
- 启动检测（git 环境、base 分支、中断检测）；
- 交互式收集任务参数；
- 以状态机串行调度六个动作（每个动作 = 一次 CLI 调用）；
- 维护 progress.json 并负责其提交，校验 AI 工作提交（含兜底 squash）；
- 管理每周 R 个研究助理分支的创建与切换。

恢复原理：所有状态都在 git 历史与 vrt/ 目录内。progress 提交信息约定为
"vrt(<job>): week <N> progress <STATE> seq <S>"，其中 seq 是周内动作序号，
跨分支搜索 (week, seq) 最大者即为全局最新状态，恢复时从该提交中读取
progress.json。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = SCRIPT_DIR / "prompts"

DEFAULT_R = 4
DEFAULT_W = 6
MAX_RETRIES = 3

STATE_TEMPLATE = {
    "PI_PLAN": "pi_plan.tmpl.md",
    "RA_PLAN_STEP": "ra_plan_step.tmpl.md",
    "ENG_EXEC": "eng_exec.tmpl.md",
    "RA_REVIEW": "ra_review.tmpl.md",
    "RA_SUMMARY": "ra_summary.tmpl.md",
    "PI_FINAL": "pi_final.tmpl.md",
}

JOB_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9\-_]*$")


class GitError(RuntimeError):
    pass


class AbortRun(RuntimeError):
    """需要人类介入的不可恢复错误。"""


# ---------------------------------------------------------------------------
# git 辅助
# ---------------------------------------------------------------------------

def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} 失败: {proc.stderr.strip()}")
    return proc


def git_out(repo: Path, *args: str) -> str:
    return git(repo, *args).stdout.strip()


def ensure_git_identity(repo: Path) -> None:
    if not git_out(repo, "config", "user.email"):
        git(repo, "config", "user.email", "vrt-bot@localhost")
        git(repo, "config", "user.name", "VRT Bot")


def current_branch(repo: Path) -> str:
    return git_out(repo, "rev-parse", "--abbrev-ref", "HEAD")


def rev_parse(repo: Path, ref: str) -> str:
    return git_out(repo, "rev-parse", ref)


def worktree_dirty(repo: Path) -> list[str]:
    out = git_out(repo, "status", "--porcelain")
    return [l for l in out.splitlines() if l.strip()]


def branch_exists(repo: Path, branch: str) -> bool:
    return git(repo, "rev-parse", "--verify", "--quiet", branch,
               check=False).returncode == 0


def ra_branch(job: str, week: int, i: int) -> str:
    return f"vrt/{job}/week_{week}/r_{i}"


def job_branches(repo: Path, job: str) -> list[str]:
    out = git_out(repo, "for-each-ref", "--format=%(refname:short)",
                  f"refs/heads/vrt/{job}/")
    return [l for l in out.splitlines() if l.strip()]


def progress_re(job: str) -> re.Pattern:
    return re.compile(
        rf"^vrt\({re.escape(job)}\): week (\d+) progress ([A-Z_]+) seq (\d+)$"
    )


def progress_msg(job: str, week: int, state: str, seq: int) -> str:
    return f"vrt({job}): week {week} progress {state} seq {seq}"


def scan_progress_commits(repo: Path, job: str, refs: list[str]) -> list[dict]:
    """在指定 refs 的历史中查找该任务的全部 progress 提交。"""
    pattern = progress_re(job)
    out = git_out(repo, "log", "--format=%H%x1f%s", *refs)
    found = []
    seen = set()
    for line in out.splitlines():
        if "\x1f" not in line:
            continue
        commit, subject = line.split("\x1f", 1)
        m = pattern.match(subject)
        if m and commit not in seen:
            seen.add(commit)
            found.append({
                "commit": commit,
                "week": int(m.group(1)),
                "state": m.group(2),
                "seq": int(m.group(3)),
            })
    return found


def latest_progress_commit(repo: Path, job: str, refs: list[str]) -> dict | None:
    """(week, seq) 最大者即全局最新状态。"""
    found = scan_progress_commits(repo, job, refs)
    if not found:
        return None
    return max(found, key=lambda c: (c["week"], c["seq"]))


def branch_last_progress(repo: Path, job: str, ref: str) -> dict | None:
    """单个分支历史中最近的 progress 提交。

    分支可能因合并包含其他分支的 progress 提交，不能依赖 git log 顺序，
    统一按 (week, seq) 取最大。
    """
    found = scan_progress_commits(repo, job, [ref])
    if not found:
        return None
    return max(found, key=lambda c: (c["week"], c["seq"]))


# ---------------------------------------------------------------------------
# 路径与 progress.json
# ---------------------------------------------------------------------------

def job_dir_rel(job: str) -> str:
    return f"vrt/{job}"


def week_dir_rel(job: str, week: int) -> str:
    return f"vrt/{job}/week_{week}"


def progress_path(job: str, week: int) -> str:
    return f"{week_dir_rel(job, week)}/progress.json"


def write_progress(repo: Path, progress: dict) -> None:
    path = repo / progress_path(progress["job"], progress["week"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def commit_progress(repo: Path, progress: dict) -> None:
    progress["seq"] = progress.get("seq", -1) + 1
    progress["status"] = "done"
    progress["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    write_progress(repo, progress)
    path = progress_path(progress["job"], progress["week"])
    git(repo, "add", "--", path)
    git(repo, "commit", "-m",
        progress_msg(progress["job"], progress["week"], progress["state"],
                     progress["seq"]),
        "--", path)


# ---------------------------------------------------------------------------
# 界面：TUI 看板 / 纯文本流
# ---------------------------------------------------------------------------

class UI:
    def __init__(self, use_tui: bool):
        self.use_tui = use_tui
        self.lock = threading.Lock()
        self.lines: deque[str] = deque(maxlen=4000)
        self.status: dict[str, str] = {}
        self.artifacts: deque[str] = deque(maxlen=6)
        self.start_time = time.monotonic()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.use_tui:
            return
        sys.stdout.write("\x1b[?1049h\x1b[?25l")
        sys.stdout.flush()
        self._thread = threading.Thread(target=self._render_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self.use_tui:
            return
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        sys.stdout.write("\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()

    def log(self, line: str) -> None:
        line = line.rstrip("\n")
        with self.lock:
            self.lines.append(line)
        if not self.use_tui:
            print(line, flush=True)

    def info(self, msg: str) -> None:
        self.log(f"[vrt] {msg}")

    def set_status(self, **kv: str) -> None:
        with self.lock:
            self.status.update({k: str(v) for k, v in kv.items()})

    def add_artifact(self, path: str) -> None:
        with self.lock:
            self.artifacts.append(path)

    def _render_loop(self) -> None:
        while not self._stop.is_set():
            self._draw()
            self._stop.wait(0.2)

    def _draw(self) -> None:
        with self.lock:
            lines = list(self.lines)
            st = dict(self.status)
            arts = list(self.artifacts)
        rows, cols = shutil.get_terminal_size((100, 30))
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
        body_budget = max(rows - len(header) - 1, 1)
        body = lines[-body_budget:]
        out = ["\x1b[H"]
        for line in header + body:
            out.append(line[: cols - 1] + "\x1b[K")
        out.append("\x1b[J")
        sys.stdout.write("\n".join(out))
        sys.stdout.flush()


# ---------------------------------------------------------------------------
# 提示词渲染与 CLI 调用
# ---------------------------------------------------------------------------

def render_prompt(state: str, ctx: dict[str, str], retry_no: int) -> str:
    template = (PROMPTS_DIR / STATE_TEMPLATE[state]).read_text(encoding="utf-8")
    ctx = dict(ctx)
    if retry_no > 0:
        ctx["RETRY_NOTICE"] = (
            f"\n# 重试提示\n\n本动作的上一次尝试未能成功完成（这是第 {retry_no} 次重试）。"
            "工作区或提交历史中可能有上次尝试的残留，请自行检查、清理或修正，"
            "然后完整完成上述动作。\n"
        )
    else:
        ctx["RETRY_NOTICE"] = ""
    prompt = template
    for key, value in ctx.items():
        prompt = prompt.replace("{{" + key + "}}", value)
    leftover = re.findall(r"\{\{[A-Z_]+\}\}", prompt)
    if leftover:
        raise AbortRun(f"提示词模板存在未渲染的占位符: {leftover}")
    return prompt


def cli_command(cli: str, prompt: str) -> list[str]:
    if cli == "kimi":
        # 注意：kimi 的 -p 非交互模式与 --auto/--yolo 互斥，-p 本身即可无人值守执行
        base = shlex.split(os.environ.get("VRT_KIMI_CMD", "kimi"))
        return base + ["-p", prompt]
    if cli == "codex":
        base = shlex.split(os.environ.get("VRT_CODEX_CMD", "codex"))
        return base + ["exec", "--dangerously-bypass-approvals-and-sandbox", prompt]
    raise AbortRun(f"未知 CLI: {cli}")


def run_cli(cli: str, prompt: str, env_extra: dict[str, str], ui: UI,
            repo: Path, timeout: int) -> int:
    cmd = cli_command(cli, prompt)
    ui.info("启动 CLI: " + " ".join(shlex.quote(c) for c in cmd[:3]) + " ...")
    env = dict(os.environ)
    env.update(env_extra)
    proc = subprocess.Popen(
        cmd,
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )

    def reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            ui.log(line.rstrip("\n"))

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    try:
        rc = proc.wait(timeout=timeout if timeout > 0 else None)
    except subprocess.TimeoutExpired:
        ui.info(f"动作超时（{timeout}s），终止 CLI 进程")
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        rc = -1
    t.join(timeout=5)
    return rc


# ---------------------------------------------------------------------------
# 动作校验与兜底
# ---------------------------------------------------------------------------

def expected_outputs(state: str, ctx: dict[str, str]) -> list[str]:
    week_dir = ctx["WEEK_DIR"]
    ra_dir = ctx.get("RA_DIR", "")
    k = ctx.get("STEP_INDEX", "1")
    outputs = {
        "PI_PLAN": [f"{week_dir}/pi_plan.md"],
        "RA_PLAN_STEP": [f"{ra_dir}/steps/step_{k}_task.md"],
        "ENG_EXEC": [f"{ra_dir}/steps/step_{k}_result.md"],
        "RA_REVIEW": [f"{ra_dir}/steps/step_{k}_review.md"],
        "RA_SUMMARY": [f"{ra_dir}/report.md"],
        "PI_FINAL": [f"{week_dir}/pi_final_report.md"],
    }
    return outputs[state]


def read_verdict(review_file: Path) -> str | None:
    if not review_file.is_file():
        return None
    for line in review_file.read_text(encoding="utf-8").splitlines()[:5]:
        m = re.match(r"\s*VRT_VERDICT:\s*(continue|done|no_value)\s*$", line)
        if m:
            return m.group(1)
    return None


def squash_commits(repo: Path, pre_head: str, job: str, week: int,
                   state: str, ui: UI) -> None:
    msgs = git_out(repo, "log", "--format=%B%x1e", f"{pre_head}..HEAD")
    combined = " | ".join(
        m.strip().splitlines()[0] for m in msgs.split("\x1e") if m.strip()
    )
    git(repo, "reset", "--soft", pre_head)
    git(repo, "commit", "-m",
        f"vrt({job}): week {week} {state}（多次提交兜底合并）\n\n原始提交: {combined}")
    ui.info("检测到动作产生多次提交，已兜底合并为一次")


def count_new_commits(repo: Path, state: str, pre_head: str,
                      job: str, week: int) -> int:
    """动作产生的新提交数。

    PI_FINAL 会把优胜分支 merge 进 base，rev-list pre..HEAD 会把被合并分支的
    全部历史提交都算进来，因此对 PI_FINAL 需要排除各 RA 分支已有的提交。
    """
    if state == "PI_FINAL":
        week_branches = [b for b in job_branches(repo, job)
                         if f"week_{week}/" in b]
        return int(git_out(repo, "rev-list", "--count", "HEAD",
                           "--not", pre_head, *week_branches))
    return int(git_out(repo, "rev-list", "--count", f"{pre_head}..HEAD"))


def verify_action(repo: Path, state: str, ctx: dict[str, str], pre_head: str,
                  job: str, week: int, ui: UI) -> str | None:
    """动作结束后校验。返回 None 表示通过，否则返回失败原因。"""
    n_commits = count_new_commits(repo, state, pre_head, job, week)
    max_commits = 2 if state == "PI_FINAL" else 1
    if n_commits == 0:
        return "动作未产生任何提交"
    if n_commits > max_commits:
        if state == "PI_FINAL":
            return f"PI_FINAL 动作产生 {n_commits} 次提交（超过允许的 2 次），请人工检查"
        squash_commits(repo, pre_head, job, week, state, ui)
    dirty = [l for l in worktree_dirty(repo) if progress_path(job, week) not in l]
    if dirty:
        return f"动作结束后工作区仍有未提交内容: {dirty[:3]}"
    for rel in expected_outputs(state, ctx):
        if not (repo / rel).is_file():
            return f"缺少契约要求的产出文件: {rel}"
    if state == "RA_REVIEW":
        review = repo / expected_outputs(state, ctx)[0]
        if read_verdict(review) is None:
            return "审查文件缺少机器可读结论行 VRT_VERDICT"
    return None


# ---------------------------------------------------------------------------
# 状态机
# ---------------------------------------------------------------------------

def next_action(progress: dict) -> dict | None:
    """根据已完成的最后一个动作，计算下一个动作（RA_REVIEW 的走向由 verdict 决定，不在此函数内）。"""
    state = progress["state"]
    i, k = progress.get("ra_index", 0), progress.get("step_index", 0)
    r = progress["r"]
    if state in ("WEEK_START",):
        return {"state": "PI_PLAN", "ra_index": 0, "step_index": 0}
    if state == "PI_PLAN":
        return {"state": "RA_PLAN_STEP", "ra_index": 1, "step_index": 1}
    if state == "RA_PLAN_STEP":
        return {"state": "ENG_EXEC", "ra_index": i, "step_index": k}
    if state == "ENG_EXEC":
        return {"state": "RA_REVIEW", "ra_index": i, "step_index": k}
    if state == "RA_SUMMARY":
        if i < r:
            return {"state": "RA_PLAN_STEP", "ra_index": i + 1, "step_index": 1}
        return {"state": "PI_FINAL", "ra_index": 0, "step_index": 0}
    return None


def action_branch(progress: dict, action: dict) -> str:
    if action["state"] in ("PI_PLAN", "PI_FINAL"):
        return progress["base_branch"]
    return ra_branch(progress["job"], progress["week"], action["ra_index"])


def build_ctx(progress: dict, action: dict, user_supplement: str) -> dict[str, str]:
    job, week = progress["job"], progress["week"]
    i, k = action.get("ra_index", 0), action.get("step_index", 0)
    return {
        "JOB": job,
        "WEEK": str(week),
        "R": str(progress["r"]),
        "W": str(progress["w"]),
        "JOB_DIR": job_dir_rel(job),
        "WEEK_DIR": week_dir_rel(job, week),
        "RA_INDEX": str(i),
        "STEP_INDEX": str(k),
        "RA_DIR": f"{week_dir_rel(job, week)}/ra_{i}",
        "BASE_BRANCH": progress["base_branch"],
        "CURRENT_BRANCH": action_branch(progress, action),
        "USER_SUPPLEMENT": user_supplement or "（无）",
        "BRANCH_LIST": "\n".join(
            f"  - {ra_branch(job, week, j)}" for j in range(1, progress["r"] + 1)
        ),
    }


def ensure_ra_branches(repo: Path, progress: dict) -> None:
    base = progress["base_branch"]
    for j in range(1, progress["r"] + 1):
        b = ra_branch(progress["job"], progress["week"], j)
        if not branch_exists(repo, b):
            git(repo, "branch", b, base)


def checkout(repo: Path, branch: str) -> None:
    dirty = worktree_dirty(repo)
    if dirty:
        raise AbortRun(
            "切换分支前检测到工作区不干净:\n" + "\n".join(dirty[:10])
            + "\n请人工检查后恢复（参见 vrt-workflow.md 第 7 节）。"
        )
    if current_branch(repo) != branch:
        git(repo, "checkout", branch)


def decide_after_review(repo: Path, progress: dict, ui: UI) -> dict:
    """RA_REVIEW 完成后读取 verdict，决定下一步走向。"""
    i, k = progress["ra_index"], progress["step_index"]
    checkout(repo, ra_branch(progress["job"], progress["week"], i))
    verdict = read_verdict(
        repo / week_dir_rel(progress["job"], progress["week"])
        / f"ra_{i}" / "steps" / f"step_{k}_review.md"
    )
    hours = progress["hours_used"].get(str(i), 0)
    if verdict == "continue" and hours < progress["w"]:
        action = {"state": "RA_PLAN_STEP", "ra_index": i, "step_index": k + 1}
    else:
        action = {"state": "RA_SUMMARY", "ra_index": i, "step_index": 0}
    ui.info(f"研究助理 {i} 第 {k} 步审查结论: {verdict}"
            f"（已用工时 {hours}/{progress['w']}）")
    return action


# ---------------------------------------------------------------------------
# 启动检测（对应 vrt-workflow.md 第 7 节）
# ---------------------------------------------------------------------------

def detect_interruption(repo: Path, job: str, args: argparse.Namespace,
                        ask) -> dict | None:
    """检测上次工作是否妥善结束。返回全局最新 progress 提交（无则 None）；

    发现异常时打印恢复建议并以退出码 2 退出。
    """
    refs = ["HEAD"] + job_branches(repo, job)
    anchor = latest_progress_commit(repo, job, refs)
    dirty = worktree_dirty(repo)

    if anchor is None:
        if dirty:
            print("检测到工作区有未提交改动，且该任务尚无 progress 提交：")
            print("\n".join(dirty[:10]))
            print("可能是首个动作中断的残留。请人工检查确认后执行：")
            print("  git reset --hard HEAD")
            print("  git clean -fd   # 如有未跟踪的残留文件")
            sys.exit(2)
        return None

    # 逐分支检查：每个分支 tip 必须等于其历史中最近的 progress 提交，
    # 否则存在悬挂提交（中断残留，或用户的人工提交）。
    dangling: dict[str, str] = {}
    for ref in {current_branch(repo), *job_branches(repo, job)}:
        b_anchor = branch_last_progress(repo, job, ref)
        if b_anchor is None:
            continue
        tip = rev_parse(repo, ref)
        if tip != b_anchor["commit"]:
            extra = git_out(repo, "log", "--format=%h %s",
                            f"{b_anchor['commit']}..{ref}")
            dangling[ref] = extra

    if not dirty and not dangling:
        return anchor

    print("检测到上次工作可能未妥善结束：")
    if dirty:
        print("\n[工作区有未提交改动]（上次中断很可能发生在 CLI 运行期间）：")
        print("\n".join(dirty[:10]))
        print("请用 git status 检查，确认是中断残留后执行：")
        print("  git reset --hard HEAD")
        print("  git clean -fd   # 如有未跟踪的残留文件")
    for ref, extra in dangling.items():
        b_anchor = branch_last_progress(repo, job, ref)
        print(f"\n[分支 {ref} 在其最近 progress 提交之后还有提交]：")
        print(extra)
    if dangling and not dirty:
        print("\n以上是中断残留还是人工有效提交？")
        print("若是中断残留，请逐分支执行恢复（脚本不自动回退）：")
        for ref in dangling:
            b_anchor = branch_last_progress(repo, job, ref)
            print(f"  git checkout {ref} && git reset --hard {b_anchor['commit']}")
        if args.trust_head_commits:
            print("（--trust-head-commits 已指定，视为人工有效提交，继续启动）")
            return anchor
        if ask("确认以上提交均为人工有效提交，继续启动？"):
            return anchor
    sys.exit(2)


# ---------------------------------------------------------------------------
# 交互
# ---------------------------------------------------------------------------

def ask_yes_no(question: str) -> bool:
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def ask_multiline(prompt: str) -> str:
    print(prompt)
    print("（多行输入，单独一行 . 结束；直接输入 . 表示无）")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == ".":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def list_jobs(repo: Path) -> list[str]:
    vrt = repo / "vrt"
    if not vrt.is_dir():
        return []
    return sorted(p.name for p in vrt.iterdir()
                  if p.is_dir() and p.name != "workflow" and (p / "job.json").is_file())


def interactive_setup(repo: Path, args: argparse.Namespace) -> argparse.Namespace:
    if not args.new_job and not args.job:
        print("VRT 每周工作启动")
        print("  [1] 创建新的研究目标")
        print("  [2] 继续已有研究目标")
        choice = input("请选择 [1/2]: ").strip()
        if choice == "1":
            args.new_job = input("任务名（小写字母/数字/-/_）: ").strip()
        else:
            jobs = list_jobs(repo)
            if not jobs:
                print("没有可继续的研究目标。")
                sys.exit(1)
            for idx, j in enumerate(jobs, 1):
                print(f"  [{idx}] {j}")
            args.job = jobs[int(input("请选择: ").strip()) - 1]
    if args.new_job and not args.requirements and not args.requirements_file:
        args.requirements = ask_multiline("请输入研究需求描述：")
    if args.job:
        supplement = ask_multiline("本周是否有新的需求补充？")
        if supplement:
            args.requirements = supplement
    if not args.cli:
        choice = input("选择 CLI [1] kimi [2] codex（默认 kimi）: ").strip()
        args.cli = {"1": "kimi", "2": "codex"}.get(choice, "kimi")
    if args.r is None:
        val = input(f"研究助理数量 R（默认 {DEFAULT_R}）: ").strip()
        args.r = int(val) if val else DEFAULT_R
    if args.w is None:
        val = input(f"每位研究助理工时 W（默认 {DEFAULT_W}）: ").strip()
        args.w = int(val) if val else DEFAULT_W
    return args


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="VRT 每周工作调度脚本")
    p.add_argument("--repo", default=".", help="目标 git 仓库路径（默认当前目录）")
    p.add_argument("--new", dest="new_job", help="创建新研究目标（任务名）")
    p.add_argument("--job", help="继续已有研究目标（任务名）")
    p.add_argument("--requirements", help="需求描述文本（新建必填，继续为补充）")
    p.add_argument("--requirements-file", help="需求描述文件路径")
    p.add_argument("--cli", choices=["kimi", "codex"], help="LLM CLI 后端")
    p.add_argument("--r", type=int, help="研究助理数量")
    p.add_argument("--w", type=int, help="每位研究助理的工时数")
    p.add_argument("--yes", action="store_true", help="非交互模式，跳过确认")
    p.add_argument("--no-tui", action="store_true", help="禁用 TUI 看板，纯文本输出")
    p.add_argument("--action-timeout", type=int, default=0,
                   help="单个动作超时秒数，0 表示不限")
    p.add_argument("--retry-delay", type=int, default=300,
                   help="动作失败后重试前的等待秒数（避开服务波动），默认 300")
    p.add_argument("--max-actions", type=int, default=0,
                   help="最多执行多少个动作后暂停（0 表示不限）")
    p.add_argument("--trust-head-commits", action="store_true",
                   help="中断检测时将悬挂提交视为人工有效提交，直接继续")
    return p.parse_args()


def load_requirements(args: argparse.Namespace) -> str:
    if args.requirements_file:
        return Path(args.requirements_file).read_text(encoding="utf-8").strip()
    return (args.requirements or "").strip()


def read_progress_at_commit(repo: Path, commit: dict, job: str) -> dict:
    path = progress_path(job, commit["week"])
    text = git_out(repo, "show", f"{commit['commit']}:{path}")
    return json.loads(text)


def ensure_job_init(repo: Path, job: str, base_branch: str, requirements: str) -> None:
    job_json = repo / job_dir_rel(job) / "job.json"
    if job_json.is_file():
        return
    job_json.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "name": job,
        "base_branch": base_branch,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "initial_requirements": requirements,
    }
    job_json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    git(repo, "add", "--", str(job_json.relative_to(repo)))
    git(repo, "commit", "-m", f"vrt({job}): init job")


def run_week(repo: Path, progress: dict, requirements: str,
             args: argparse.Namespace, ui: UI) -> int:
    """状态机主循环。返回 0 表示本周完成或到达 max-actions 检查点。"""
    actions_done = 0
    retries = 0
    while True:
        if progress["state"] == "RA_REVIEW":
            action = decide_after_review(repo, progress, ui)
        else:
            action = next_action(progress)

        if action is None:
            if progress["state"] == "PI_FINAL":
                progress["state"] = "WEEK_DONE"
                commit_progress(repo, progress)
                ui.info("本周工作完成（WEEK_DONE）")
                return 0
            raise AbortRun(f"状态机无法推进: state={progress['state']}")

        if args.max_actions and actions_done >= args.max_actions:
            ui.info(f"到达 max-actions={args.max_actions} 检查点，暂停。再次运行可继续。")
            return 0

        state = action["state"]
        if state.startswith("RA_") or state == "ENG_EXEC":
            ensure_ra_branches(repo, progress)
        branch = action_branch(progress, action)
        checkout(repo, branch)

        ctx = build_ctx(progress, action, requirements)
        prompt = render_prompt(state, ctx, retries)
        ui.set_status(
            action=f"{state} ra={action.get('ra_index', '-')} step={action.get('step_index', '-')}",
            branch=branch,
            hours=" ".join(f"RA{j}:{progress['hours_used'].get(str(j), 0)}/{progress['w']}"
                           for j in range(1, progress["r"] + 1)),
        )
        ui.info(f"=== 动作 {state}（RA {action.get('ra_index', '-')}, "
                f"步 {action.get('step_index', '-')}"
                f"{'，第 ' + str(retries) + ' 次重试' if retries else ''}）===")

        pre_head = rev_parse(repo, "HEAD")
        env_extra = {
            "VRT_ACTION": state,
            "VRT_JOB": progress["job"],
            "VRT_WEEK": str(progress["week"]),
            "VRT_RA_INDEX": str(action.get("ra_index", 0)),
            "VRT_STEP_INDEX": str(action.get("step_index", 0)),
            "VRT_R": str(progress["r"]),
            "VRT_W": str(progress["w"]),
            "VRT_REPO": str(repo),
        }
        rc = run_cli(progress["cli"], prompt, env_extra, ui, repo,
                     args.action_timeout)

        if rc != 0:
            failure = f"CLI 退出码 {rc}"
        else:
            failure = verify_action(repo, state, ctx, pre_head,
                                    progress["job"], progress["week"], ui)
        if failure:
            retries += 1
            ui.info(f"动作校验失败：{failure}")
            if retries > MAX_RETRIES:
                ui.stop()
                print(f"动作 {state} 已连续失败 {MAX_RETRIES} 次（{failure}）。",
                      file=sys.stderr)
                print("脚本退出并保留现场，请人工介入处理后重新运行"
                      "（参见 vrt-workflow.md 第 7 节）。", file=sys.stderr)
                return 1
            ui.info(f"将进行第 {retries} 次重试（不扣工时），"
                    f"先等待 {args.retry_delay} 秒以避开服务波动...")
            time.sleep(args.retry_delay)
            continue

        retries = 0
        if state == "ENG_EXEC":
            key = str(action["ra_index"])
            progress["hours_used"][key] = progress["hours_used"].get(key, 0) + 1
        progress["state"] = state
        progress["ra_index"] = action.get("ra_index", 0)
        progress["step_index"] = action.get("step_index", 0)
        progress["retries"] = retries
        commit_progress(repo, progress)
        actions_done += 1
        for rel in expected_outputs(state, ctx):
            ui.add_artifact(rel)
        ui.info(f"=== 动作 {state} 完成 ===")


def main() -> int:
    args = parse_args()
    repo = Path(args.repo).resolve()
    if git(repo, "rev-parse", "--is-inside-work-tree", check=False).returncode != 0:
        print(f"错误：{repo} 不是 git 仓库。", file=sys.stderr)
        return 1
    if git(repo, "rev-parse", "--verify", "HEAD", check=False).returncode != 0:
        print("错误：仓库尚无任何提交，请先创建初始提交。", file=sys.stderr)
        return 1

    if not args.yes:
        args = interactive_setup(repo, args)
    cli_explicit = args.cli is not None
    job = args.new_job or args.job
    if not job:
        print("错误：必须指定 --new 或 --job。", file=sys.stderr)
        return 1
    if not JOB_NAME_RE.match(job):
        print(f"错误：任务名 {job!r} 不合法（允许小写字母、数字、-、_）。", file=sys.stderr)
        return 1
    requirements = load_requirements(args)
    if args.new_job and not requirements:
        print("错误：新建任务必须提供需求描述（--requirements 或 --requirements-file）。",
              file=sys.stderr)
        return 1
    if not args.cli:
        args.cli = "kimi"

    job_json_path = repo / job_dir_rel(job) / "job.json"
    if args.new_job and job_json_path.is_file():
        print(f"错误：任务 {job} 已存在，请用 --job 继续。", file=sys.stderr)
        return 1
    if args.job and not job_json_path.is_file():
        print(f"错误：任务 {job} 不存在（无 job.json）。", file=sys.stderr)
        return 1
    is_new_job = bool(args.new_job)

    if is_new_job:
        base_branch = current_branch(repo)
    else:
        base_branch = json.loads(job_json_path.read_text(encoding="utf-8"))["base_branch"]
        cur = current_branch(repo)
        ra_branch_re = re.compile(rf"^vrt/{re.escape(job)}/week_\d+/r_\d+$")
        if cur != base_branch and not ra_branch_re.match(cur):
            print(f"错误：当前分支 {cur} 既不是 base 分支 {base_branch}，"
                  "也不是本任务的 RA 分支。", file=sys.stderr)
            return 1

    anchor = detect_interruption(repo, job, args,
                                 ask_yes_no if not args.yes else (lambda q: False))

    ensure_git_identity(repo)
    if is_new_job:
        ensure_job_init(repo, job, base_branch, requirements)

    # 由锚点决定：开新周 or 恢复当周
    if anchor is None:
        week = 1
        last_progress = None
    else:
        last_progress = read_progress_at_commit(repo, anchor, job)
        week = last_progress["week"]

    if anchor is not None and last_progress["state"] != "WEEK_DONE":
        progress = last_progress
        print(f"恢复第 {week} 周：状态 {progress['state']}，"
              f"RA {progress.get('ra_index', '-')}，步 {progress.get('step_index', '-')}，"
              f"seq {progress.get('seq', '-')}")
    else:
        if anchor is not None:
            week = last_progress["week"] + 1
        if args.r is None:
            args.r = (last_progress or {}).get("r", DEFAULT_R)
        if args.w is None:
            args.w = (last_progress or {}).get("w", DEFAULT_W)
        if not cli_explicit and last_progress:
            args.cli = last_progress.get("cli", args.cli)
        progress = {
            "version": 1,
            "job": job,
            "week": week,
            "cli": args.cli,
            "base_branch": base_branch,
            "r": args.r,
            "w": args.w,
            "state": "WEEK_START",
            "ra_index": 0,
            "step_index": 0,
            "seq": -1,
            "hours_used": {},
            "retries": 0,
            "status": "done",
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        print(f"开始第 {week} 周：job={job} cli={args.cli} R={args.r} W={args.w}")

    use_tui = (not args.no_tui) and sys.stdout.isatty()
    ui = UI(use_tui)
    ui.set_status(job=job, week=str(progress["week"]), cli=progress["cli"])
    ui.start()
    try:
        rc = run_week(repo, progress, requirements, args, ui)
    finally:
        ui.stop()
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AbortRun as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)
    except GitError as e:
        print(f"git 错误：{e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n收到中断信号，脚本退出。现场保留，重新运行可按状态机恢复。",
              file=sys.stderr)
        sys.exit(130)
