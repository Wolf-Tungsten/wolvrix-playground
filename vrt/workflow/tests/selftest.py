#!/usr/bin/env python3
"""VRT 调度脚本自测试。

在 ptmp/vrt-selftest/ 下搭建带 git 的模拟仓库（把真实 vrt/ 目录复制进去），
用 mock CLI 驱动 start-week-job.py，验证状态机、分支、提交、检测与恢复逻辑。
不触碰真实仓库，也不调用真实 LLM 后端。

用法：python3 vrt/workflow/tests/selftest.py（或 make run_vrt_selftest）
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "vrt" / "workflow" / "start-week-job.py"
MOCK = ROOT / "vrt" / "workflow" / "tests" / "mock_cli.sh"
SANDBOX = ROOT / "ptmp" / "vrt-selftest"

PROGRESS_RE = re.compile(r"^vrt\(demo\): week \d+ progress [A-Z_]+ seq \d+$")

failures: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("  PASS " if cond else "  FAIL ") + label)
    if not cond:
        failures.append(label)


def sh(args: list[str], cwd: Path | None = None, env: dict | None = None,
       check_rc: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True)
    if check_rc and proc.returncode != 0:
        raise RuntimeError(f"命令失败 {args}:\n{proc.stdout}\n{proc.stderr}")
    return proc


def git(repo: Path, *args: str) -> str:
    return sh(["git", "-C", str(repo), *args]).stdout.strip()


def setup_sandbox(name: str) -> Path:
    repo = SANDBOX / name / "repo"
    if repo.parent.exists():
        shutil.rmtree(repo.parent)
    repo.mkdir(parents=True)
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "selftest@localhost")
    git(repo, "config", "user.name", "Selftest")
    shutil.copytree(ROOT / "vrt", repo / "vrt")
    (repo / "README.md").write_text("# 模拟仓库\n\n用于 VRT 自测试。\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "demo.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "initial commit")
    return repo


def run_script(repo: Path, extra_args: list[str], env_extra: dict | None = None,
               expect_rc: int = 0) -> str:
    env = dict(os.environ)
    env["VRT_KIMI_CMD"] = f"bash {MOCK}"
    env["VRT_CODEX_CMD"] = f"bash {MOCK}"
    env["MOCK_DIR"] = str(repo.parent / "mock")
    env.update(env_extra or {})
    proc = sh([sys.executable, str(SCRIPT), "--repo", str(repo),
               "--yes", "--no-tui", "--retry-delay", "0", *extra_args],
              env=env, check_rc=False)
    out = proc.stdout + proc.stderr
    if proc.returncode != expect_rc:
        print(out[-4000:])
    check(proc.returncode == expect_rc,
          f"脚本退出码 {proc.returncode} == 预期 {expect_rc}（{extra_args[:2]}）")
    return out


def base_env() -> dict:
    return {}


# ---------------------------------------------------------------------------
# 场景
# ---------------------------------------------------------------------------

def s1_full_week() -> Path:
    print("[S1] 完整一周（R=2 W=2，mock 每方向 2 步后 done）")
    repo = setup_sandbox("s1")
    out = run_script(repo, ["--new", "demo", "--requirements", "测试需求",
                            "--cli", "kimi", "--r", "2", "--w", "2"])
    check("WEEK_DONE" in out, "S1 输出包含 WEEK_DONE")

    progress = json.loads((repo / "vrt/demo/week_1/progress.json").read_text())
    check(progress["state"] == "WEEK_DONE", "S1 progress.json 状态为 WEEK_DONE")
    check(progress["hours_used"] == {"1": 2, "2": 2}, "S1 工时统计正确")
    check(progress["seq"] == 16, f"S1 seq=16（实际 {progress['seq']}）")

    check((repo / "vrt/demo/week_1/pi_final_report.md").is_file(),
          "S1 最终报告在 base 上")
    check((repo / "vrt/demo/week_1/ra_1/report.md").is_file(),
          "S1 优胜方向报告已合并进 base")
    for i in (1, 2):
        branch = f"vrt/demo/week_1/r_{i}"
        git(repo, "rev-parse", "--verify", branch)
        report = git(repo, "show", f"{branch}:vrt/demo/week_1/ra_{i}/report.md")
        check("周报" in report, f"S1 r_{i} 分支上有周报")
        for k in (1, 2):
            for kind in ("task", "result", "review"):
                git(repo, "cat-file", "-e",
                    f"{branch}:vrt/demo/week_1/ra_{i}/steps/step_{k}_{kind}.md")
        check(True, "S1 r_%d 两步的 task/result/review 齐全" % i)

    subjects = git(repo, "log", "--all", "--format=%s").splitlines()
    progress_subjects = [s for s in subjects if PROGRESS_RE.match(s)]
    check(len(progress_subjects) == 17,
          f"S1 共有 17 个 progress 提交（实际 {len(progress_subjects)}）")
    work_exec = [s for s in subjects if "work ENG_EXEC" in s]
    check(len(work_exec) == 4, f"S1 工程师工作提交 4 次（实际 {len(work_exec)}）")

    # 每个分支 tip 都应是 progress 提交
    tips_ok = True
    for ref in ["main", "vrt/demo/week_1/r_1", "vrt/demo/week_1/r_2"]:
        tip_subject = git(repo, "log", "-1", "--format=%s", ref)
        if not PROGRESS_RE.match(tip_subject):
            tips_ok = False
    check(tips_ok, "S1 所有分支 tip 均为 progress 提交")
    return repo


def s2_next_week(repo: Path) -> None:
    print("[S2] 一周结束后再启动新周（R=2 W=1）")
    out = run_script(repo, ["--job", "demo", "--cli", "kimi", "--r", "2", "--w", "1"],
                     env_extra={"MOCK_MAX_STEP": "2"})
    check("开始第 2 周" in out, "S2 输出显示开始第 2 周")
    check("WEEK_DONE" in out, "S2 输出包含 WEEK_DONE")
    check((repo / "vrt/demo/week_2/pi_final_report.md").is_file(),
          "S2 week_2 最终报告存在")
    progress = json.loads((repo / "vrt/demo/week_2/progress.json").read_text())
    check(progress["hours_used"] == {"1": 1, "2": 1},
          "S2 W=1 时每方向恰好用 1 工时")


def s3_retry() -> None:
    print("[S3] 动作失败重试（ENG_EXEC 首次退出码 1，R=1 W=1）")
    repo = setup_sandbox("s3")
    out = run_script(repo, ["--new", "demo", "--requirements", "测试需求",
                            "--cli", "kimi", "--r", "1", "--w", "1"],
                     env_extra={"MOCK_FAIL_ONCE_ACTION": "ENG_EXEC"})
    check("重试" in out, "S3 输出包含重试提示")
    check("WEEK_DONE" in out, "S3 重试后完成本周")
    progress = json.loads((repo / "vrt/demo/week_1/progress.json").read_text())
    check(progress["hours_used"] == {"1": 1}, "S3 重试不重复扣工时")


def s4_squash() -> None:
    print("[S4] 多次提交兜底合并（ENG_EXEC 在 ra=1 step=1 提交两次）")
    repo = setup_sandbox("s4")
    out = run_script(repo, ["--new", "demo", "--requirements", "测试需求",
                            "--cli", "kimi", "--r", "1", "--w", "2"],
                     env_extra={"MOCK_DOUBLE_COMMIT": "1"})
    check("兜底合并" in out, "S4 输出包含兜底合并提示")
    subjects = git(repo, "log", "vrt/demo/week_1/r_1", "--format=%s").splitlines()
    squashed = [s for s in subjects if "兜底合并" in s]
    check(len(squashed) == 1, "S4 恰好一次兜底合并提交")
    plain = [s for s in subjects if "work ENG_EXEC ra 1 step 1" in s]
    check(len(plain) == 0, "S4 原始的两次 ENG_EXEC 提交已被合并")
    result = git(repo, "show",
                 "vrt/demo/week_1/r_1:vrt/demo/week_1/ra_1/steps/step_1_result.md")
    check("补充一行" in result, "S4 合并提交保留了全部改动内容")
    check("WEEK_DONE" in out, "S4 本周完成")


def s5_resume(repo_name: str = "s5") -> Path:
    print("[S5] max-actions 中断后续跑（R=1 W=1）")
    repo = setup_sandbox(repo_name)
    out1 = run_script(repo, ["--new", "demo", "--requirements", "测试需求",
                             "--cli", "kimi", "--r", "1", "--w", "1",
                             "--max-actions", "3"])
    check("检查点" in out1, "S5 首次运行在检查点暂停")
    check("WEEK_DONE" not in out1, "S5 首次运行未完成")
    out2 = run_script(repo, ["--job", "demo"])
    check("恢复第 1 周" in out2, "S5 第二次运行识别为恢复")
    check("WEEK_DONE" in out2, "S5 续跑后完成本周")
    progress = json.loads((repo / "vrt/demo/week_1/progress.json").read_text())
    check(progress["hours_used"] == {"1": 1}, "S5 续跑工时正确")
    return repo


def s6_dirty_detection(repo: Path) -> None:
    print("[S6] 工作区残留的中断检测")
    (repo / "README.md").write_text("dirty\n", encoding="utf-8")
    out = run_script(repo, ["--job", "demo"], expect_rc=2)
    check("reset --hard HEAD" in out, "S6 提示 git reset --hard HEAD")
    sh(["git", "-C", str(repo), "checkout", "--", "README.md"])
    out = run_script(repo, ["--job", "demo", "--r", "1", "--w", "1"])
    check("WEEK_DONE" in out, "S6 清理后正常开新周")


def s7_dangling_commit() -> None:
    print("[S7] 悬挂提交检测与 --trust-head-commits")
    repo = setup_sandbox("s7")
    run_script(repo, ["--new", "demo", "--requirements", "测试需求",
                      "--cli", "kimi", "--r", "1", "--w", "1"])
    (repo / "manual.txt").write_text("人工提交\n", encoding="utf-8")
    git(repo, "add", "manual.txt")
    git(repo, "commit", "-m", "manual commit between weeks")
    out = run_script(repo, ["--job", "demo"], expect_rc=2)
    check("manual commit between weeks" in out, "S7 列出悬挂提交供用户判断")
    out = run_script(repo, ["--job", "demo", "--r", "1", "--w", "1",
                            "--trust-head-commits"])
    check("开始第 2 周" in out and "WEEK_DONE" in out,
          "S7 --trust-head-commits 后正常开新周")


def s8_codex_path() -> None:
    print("[S8] codex 命令路径（mock 注入，R=1 W=1）")
    repo = setup_sandbox("s8")
    out = run_script(repo, ["--new", "demo", "--requirements", "测试需求",
                            "--cli", "codex", "--r", "1", "--w", "1"])
    check("WEEK_DONE" in out, "S8 codex 路径完成本周")


def s9_submodule() -> None:
    print("[S9] 子模块分支隔离（R=2 W=1，mock 在子模块内提交）")
    repo = setup_sandbox("s9")
    sub_src = repo.parent / "sub-src"
    sub_src.mkdir()
    git(sub_src, "init", "-b", "main")
    git(sub_src, "config", "user.email", "selftest@localhost")
    git(sub_src, "config", "user.name", "Selftest")
    (sub_src / "sub_notes.txt").write_text("init\n", encoding="utf-8")
    git(sub_src, "add", "-A")
    git(sub_src, "commit", "-m", "sub init")
    sh(["git", "-C", str(repo), "-c", "protocol.file.allow=always",
        "submodule", "add", str(sub_src), "sub"])
    git(repo, "commit", "-m", "add submodule")
    git(repo / "sub", "config", "user.email", "selftest@localhost")
    git(repo / "sub", "config", "user.name", "Selftest")

    out = run_script(repo, ["--new", "demo", "--requirements", "测试需求",
                            "--cli", "kimi", "--r", "2", "--w", "1"])
    check("WEEK_DONE" in out, "S9 含子模块的一周完成")

    sub = repo / "sub"
    for i in (1, 2):
        b = f"vrt/demo/week_1/r_{i}"
        git(sub, "rev-parse", "--verify", b)
        check(True, f"S9 子模块存在同名分支 {b}")
        link = git(repo, "ls-tree", b, "--", "sub").split()[2]
        tip = git(sub, "rev-parse", b)
        check(link == tip, f"S9 根分支 {b} 的 gitlink == 子模块同名分支 tip")

    # 隔离性：r_2 的子模块分支不应包含 r_1 的工作提交
    r2_log = git(sub, "log", "--format=%s", "vrt/demo/week_1/r_2")
    check("ra 1" not in r2_log and "ra 2" in r2_log,
          "S9 子模块分支相互隔离（r_2 不含 r_1 的提交）")

    # 合并后：main 的 gitlink == 优胜方向子模块 tip，且子模块工作区已对齐
    link_main = git(repo, "ls-tree", "main", "--", "sub").split()[2]
    tip_r1 = git(sub, "rev-parse", "vrt/demo/week_1/r_1")
    check(link_main == tip_r1, "S9 合并后 main 的 gitlink 指向优胜子模块提交")
    check(git(sub, "rev-parse", "HEAD") == link_main,
          "S9 PI_FINAL 后子模块工作区与 gitlink 一致")


def s10_delete_and_restart() -> None:
    """复现真实事故：用户删除任务目录并提交（分支未删），期望重新开始。"""
    print("[S10] 删除任务目录后同名重启")
    repo = setup_sandbox("s10")
    run_script(repo, ["--new", "demo", "--requirements", "测试需求",
                      "--cli", "kimi", "--r", "2", "--w", "1",
                      "--max-actions", "4"])  # 进行到 RA_REVIEW(1,1)，分支已建

    # 用户删除任务目录并提交（分支还在）
    git(repo, "checkout", "main")
    git(repo, "rm", "-rq", "vrt/demo")
    git(repo, "commit", "-q", "-m", "remove vrt work")

    # 分支未删：必须报错并提示删除，而不是从历史恢复
    out = run_script(repo, ["--new", "demo", "--requirements", "测试需求",
                            "--cli", "kimi", "--r", "2", "--w", "1"],
                     expect_rc=1)
    check("git branch -D" in out, "S10 存在历史分支时报错并提示删除")

    # 删除分支后：全新开始，必须从 PI_PLAN 起跑
    for i in (1, 2):
        git(repo, "branch", "-D", f"vrt/demo/week_1/r_{i}")
    out = run_script(repo, ["--new", "demo", "--requirements", "测试需求",
                            "--cli", "kimi", "--r", "2", "--w", "1"])
    check("惰性历史" in out, "S10 提示忽略 base 历史中的旧 progress 提交")
    check("动作 PI_PLAN" in out, "S10 从 PI_PLAN 起跑而非跳过")
    check("WEEK_DONE" in out, "S10 全新一周完成")
    check((repo / "vrt/demo/week_1/pi_final_report.md").is_file(),
          "S10 新纪元的最终报告存在")


def main() -> int:
    SANDBOX.mkdir(parents=True, exist_ok=True)
    repo1 = s1_full_week()
    s2_next_week(repo1)
    s3_retry()
    s4_squash()
    repo5 = s5_resume()
    s6_dirty_detection(repo5)
    s7_dangling_commit()
    s8_codex_path()
    s9_submodule()
    s10_delete_and_restart()

    print()
    if failures:
        print(f"自测试失败 {len(failures)} 项：")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("全部自测试通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
