#!/usr/bin/env python3
"""VRT transport: launch agents, persist receipts, delay/retry failures.

The project manager agent owns workflow and repository decisions. This module
does not invoke Git, enumerate repositories, choose branches, or judge research.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
import uuid
from itertools import count
from datetime import datetime
from pathlib import Path

from runner_ui import UI

HERE = Path(__file__).resolve().parent
ROLES = HERE / "prompts"


def now() -> str:
    return datetime.now().astimezone().isoformat()


def write_json(path: Path, value: dict) -> None:
    """Atomic transport checkpoints; agents never edit these files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def cli_command(cli: str, prompt: str) -> list[str]:
    if cli == "kimi":
        return shlex.split(os.environ.get("VRT_KIMI_CMD", "kimi")) + ["-p", "/goal " + prompt]
    return shlex.split(os.environ.get("VRT_CODEX_CMD", "codex")) + [
        "exec", "--dangerously-bypass-approvals-and-sandbox", prompt]


def stop_process(proc: subprocess.Popen) -> None:
    # Terminate the entire invocation, including children holding logs open.
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=3)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait()


def launch(cli: str, prompt: str, cwd: Path, log: Path, env_extra: dict,
           timeout: int, ui: UI) -> int:
    env = dict(os.environ)
    env.update(env_extra)
    with log.open("w", encoding="utf-8") as stream:
        proc = subprocess.Popen(cli_command(cli, prompt), cwd=cwd, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace", start_new_session=True)

        def drain() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                stream.write(line)
                stream.flush()
                ui.log(line.rstrip("\n"))

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        try:
            rc = proc.wait(timeout=timeout or None)
        except subprocess.TimeoutExpired:
            stop_process(proc)
            rc = 124
        except BaseException:
            stop_process(proc)
            raise
        finally:
            # A CLI that left subprocesses behind must not overlap the next one.
            stop_process(proc)
            reader.join()
            if proc.stdout:
                proc.stdout.close()
    return rc


def decision_at(path: Path, request_id: str) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("request_id") != request_id:
        raise ValueError("项目经理 response 的 request_id 不匹配")
    if data.get("kind") not in ("dispatch", "complete", "blocked"):
        raise ValueError("kind 必须是 dispatch/complete/blocked")
    if not isinstance(data.get("reason"), str) or not data["reason"].strip():
        raise ValueError("缺少 reason")
    if data["kind"] == "dispatch":
        for key in ("task_id", "role", "cwd", "prompt"):
            if not isinstance(data.get(key), str) or not data[key].strip():
                raise ValueError(f"派发缺少 {key}")
        if not Path(data["cwd"]).is_absolute() or not Path(data["cwd"]).is_dir():
            raise ValueError("cwd 必须是项目经理选择的已存在目录的绝对路径")
    return data


def save(state_path: Path, state: dict) -> None:
    state["updated_at"] = now()
    write_json(state_path, state)


def invoke(state_path: Path, state: dict, args: argparse.Namespace, ui: UI,
           role: str, prompt: str, cwd: Path, task_id: str,
           request: Path | None = None, response: Path | None = None) -> dict:
    call_id = uuid.uuid4().hex
    log = state_path.parent / f"call-{call_id}.log"
    receipt = {"call_id": call_id, "task_id": task_id, "role": role,
               "cwd": str(cwd), "log": str(log), "started_at": now(),
               "status": "running"}
    state["calls"].append(receipt)
    save(state_path, state)  # before spawning: recovery knows an action may have run
    ui.set_status(action=f"{role} {task_id}", branch=str(cwd))
    ui.info(f"派发 {role}，工作目录由项目经理指定：{cwd}")
    env = {"VRT_ACTION": role, "VRT_TASK_ID": task_id,
           "VRT_JOB": state["config"]["job"], "VRT_WORKSPACE": state["config"]["workspace"],
           "VRT_RECEIPTS": str(state_path)}
    if request and response:
        env.update(VRT_PM_REQUEST=str(request), VRT_PM_RESPONSE=str(response))
    try:
        rc = launch(state["config"]["cli"], prompt, cwd, log, env,
                    args.action_timeout, ui)
        receipt.update(status="returned" if rc == 0 else "failed", exit_code=rc)
    except KeyboardInterrupt:
        receipt.update(status="interrupted", exit_code=130)
        raise
    except OSError as exc:
        receipt.update(status="failed", exit_code=127, error=str(exc))
    finally:
        receipt["ended_at"] = now()
        save(state_path, state)
    return receipt


def delay(args: argparse.Namespace, ui: UI) -> None:
    ui.info(f"调用失败，{args.retry_delay} 秒后重试；现场保留")
    time.sleep(args.retry_delay)


def manage(state_path: Path, state: dict, args: argparse.Namespace, ui: UI) -> dict | None:
    """Ask a separate PM invocation; no default/fallback workflow in Python."""
    previous_error = None
    for attempt in count():
        request_id = uuid.uuid4().hex
        request = state_path.parent / f"pm-{request_id}-request.json"
        response = state_path.parent / f"pm-{request_id}-response.json"
        write_json(request, {"request_id": request_id, "config": state["config"],
                             "workflow": str(HERE / "vrt-workflow.md"),
                             "role_guides": str(ROLES), "receipts": str(state_path),
                             "recovery_required": state.get("recovery_required", False),
                             "previous_error": previous_error, "response": str(response)})
        prompt = (ROLES / "project_manager.md").read_text(encoding="utf-8")
        prompt += f"\n本次请求文件：{request}\n本次响应文件：{response}\nrequest_id: {request_id}\n"
        if previous_error:
            prompt += (f"\n上次调用或响应校验失败：{previous_error}\n"
                       "请特别检查响应格式：只向本次 response 文件写入一个 JSON 对象，"
                       "不要用 Markdown 代码块或终端输出代替文件；使用本次 request_id。"
                       "kind 只能是 dispatch/complete/blocked，reason 必须非空；dispatch "
                       "还须提供非空 task_id、role、prompt 和已存在目录的绝对 cwd。\n")
        receipt = invoke(state_path, state, args, ui, "PROJECT_MANAGER", prompt,
                         Path(state["config"]["workspace"]), request_id, request, response)
        try:
            if receipt["exit_code"] != 0:
                raise ValueError(f"项目经理 CLI 退出码 {receipt['exit_code']}，日志 {receipt['log']}")
            decision = decision_at(response, request_id)
            state["decisions"].append({"request": str(request), "response": str(response),
                                       "decision": decision})
            state["recovery_required"] = False
            save(state_path, state)
            return decision
        except (OSError, ValueError) as exc:
            previous_error = str(exc)
            receipt["protocol_error"] = previous_error
            save(state_path, state)
            ui.info(previous_error)
            if args.max_retries and attempt >= args.max_retries:
                break
            delay(args, ui)
    state["status"] = "paused"
    save(state_path, state)
    return None


def run(state_path: Path, state: dict, args: argparse.Namespace, ui: UI) -> int:
    dispatched = 0
    while True:
        if args.max_actions and dispatched >= args.max_actions:
            state["status"] = "paused"
            save(state_path, state)
            ui.info("到达 max-actions 检查点；下次先由项目经理核对现场")
            return 0
        decision = manage(state_path, state, args, ui)
        if decision is None:
            return 1
        if decision["kind"] != "dispatch":
            state["status"] = decision["kind"]
            state["pending"] = None
            save(state_path, state)
            ui.info(decision["reason"])
            return 0 if decision["kind"] == "complete" else 2
        state["pending"] = decision
        save(state_path, state)
        for attempt in count():
            prompt = decision["prompt"]
            prompt += (f"\n执行编号：{decision['task_id']}。项目经理派发说明：{decision['reason']}\n"
                       "调用回执：" + str(state_path) + "\n")
            if attempt:
                prompt += (f"上次调用失败：{receipt}。先核对已完成改动和提交再继续，"
                           "不要盲目重复已完成动作；不丢弃现场或无关用户改动。\n")
            receipt = invoke(state_path, state, args, ui, decision["role"],
                             prompt, Path(decision["cwd"]), decision["task_id"])
            if receipt["exit_code"] == 0:
                break
            if args.max_retries and attempt >= args.max_retries:
                break
            delay(args, ui)
        dispatched += 1
        state["pending"] = None
        save(state_path, state)
        # Even an exhausted retry goes back to PM for reconciliation/recovery.


def setup_readline() -> None:
    # GNU readline edits wrapped UTF-8 lines in userspace, without the terminal's
    # canonical input buffer limit. No history file (requirements may be private).
    import readline
    readline.parse_and_bind('"\\C-h": backward-delete-char')
    readline.parse_and_bind('"\\C-?": backward-delete-char')


def multiline_input(label: str) -> str:
    import readline
    print(label + "（单独输入 . 结束；:back 重新编辑上一行；Ctrl-C 取消）")
    lines: list[str] = []
    prefill = ""
    while True:
        readline.set_startup_hook(lambda: readline.insert_text(prefill))
        try:
            line = input("> ")
        except EOFError:
            break
        finally:
            readline.set_startup_hook(None)
        prefill = ""
        if line == ".":
            break
        if line == ":back":
            prefill = lines.pop() if lines else ""
        else:
            lines.append(line)
    return "\n".join(lines).strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="VRT 项目经理 Agent 的派发执行器（不操作 Git）")
    parser.add_argument("--repo", default=".", help="工作区入口，允许包含多个递归嵌套仓库")
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--new", dest="new_job")
    group.add_argument("--job")
    parser.add_argument("--requirements")
    parser.add_argument("--requirements-file")
    parser.add_argument("--cli", choices=("kimi", "codex"))
    parser.add_argument("--r", type=int)
    parser.add_argument("--w", type=int, help="每 RA 工程调用配额，与物理时间无关")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--no-tui", action="store_true")
    parser.add_argument("--action-timeout", type=int, default=0)
    parser.add_argument("--retry-delay", type=int, default=120, help="失败后等待秒数，默认 120")
    parser.add_argument("--max-retries", type=int, default=0,
                        help="额外重试上限，默认 0 持续重试直到成功或用户中断")
    parser.add_argument("--max-actions", type=int, default=0, help="本次最多派发的工作任务数，不含项目经理")
    args = parser.parse_args()
    if not args.yes:
        setup_readline()
    if not args.new_job and not args.job and not args.yes:
        root = Path(args.repo).resolve() / "vrt"
        projects = sorted(p.name for p in root.iterdir()
                          if p.is_dir() and p.name != "workflow" and not p.name.startswith(".")) if root.is_dir() else []
        print("VRT 项目管理\n  [n] 创建新项目")
        for index, name in enumerate(projects, 1):
            print(f"  [{index}] {name}")
        while True:
            choice = input("创建或选择已有项目 [n/编号]: ").strip().lower()
            if choice == "n":
                args.new_job = input("新项目名: ").strip()
                break
            if choice.isdigit() and 1 <= int(choice) <= len(projects):
                args.job = projects[int(choice) - 1]
                break
            print("请输入 n 或列表中的项目编号。")
    name = args.new_job or args.job or ""
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name) or name == "workflow":
        parser.error("必须指定合法项目名，workflow 为保留目录")
    project = Path(args.repo).resolve() / "vrt" / name
    if args.new_job and project.exists():
        parser.error("项目已存在，请选择已有项目或使用 --job")
    if args.job and not project.is_dir():
        parser.error("项目不存在，请先创建项目或使用 --new")
    if not args.yes:
        if not args.requirements and not args.requirements_file:
            args.requirements = multiline_input("研究需求" if args.new_job else "补充需求（可留空）")
        if args.cli is None:
            args.cli = input("CLI [kimi/codex]（留空沿用或默认 kimi）: ").strip() or None
            if args.cli not in (None, "kimi", "codex"):
                parser.error("CLI 必须是 kimi 或 codex")
        for key, label in (("r", "RA 数量 R"), ("w", "每 RA 工程调用次数 W，非小时")):
            if getattr(args, key) is None:
                value = input(label + "（留空交项目经理沿用/确定）: ").strip()
                if value:
                    try:
                        setattr(args, key, int(value))
                    except ValueError:
                        parser.error(f"{key} 必须是整数")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", args.new_job or args.job or ""):
        parser.error("必须指定合法的 --new 或 --job 任务名")
    for key in ("action_timeout", "retry_delay", "max_retries", "max_actions"):
        if getattr(args, key) < 0:
            parser.error(f"{key} 不得为负")
    for key in ("r", "w"):
        if getattr(args, key) is not None and getattr(args, key) < 1:
            parser.error(f"{key} 必须为正整数")
    return args


def main() -> int:
    args = parse_args()
    workspace = Path(args.repo).resolve()
    if not workspace.is_dir():
        raise ValueError("工作区入口不存在")
    requirements = (Path(args.requirements_file).read_text(encoding="utf-8")
                    if args.requirements_file else args.requirements or "")
    if args.new_job and not requirements:
        raise ValueError("新任务必须提供需求")
    job = args.new_job or args.job
    project = workspace / "vrt" / job
    transport = project / ".runner"
    if args.new_job and project.exists():
        raise ValueError("项目已存在，请使用 --job")
    transport.mkdir(parents=True, exist_ok=True)
    latest = transport / "latest.json"
    state_path = None
    if not args.new_job and latest.is_file():
        pointer = json.loads(latest.read_text(encoding="utf-8"))
        state_path = transport / pointer["run_id"] / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state["status"] == "complete":
            state_path = None  # new session/week interpretation is PM's job
    if state_path is None:
        run_id = uuid.uuid4().hex
        state_path = transport / run_id / "state.json"
        state = {"version": 2, "status": "active", "calls": [], "decisions": [],
                 "pending": None, "config": {"job": job, "workspace": str(workspace),
                 "project_dir": str(project),
                 "intent": "new" if args.new_job else "continue", "requirements": requirements,
                 "r": args.r, "w": args.w, "cli": args.cli or "kimi"}}
        save(state_path, state)
        write_json(latest, {"run_id": run_id})
        if args.new_job:
            write_json(project / "project.json", {"name": job, "created_at": now(),
                                                   "initial_requirements": requirements})
            (project / "requirements.md").write_text(requirements + "\n", encoding="utf-8")
    else:
        # Resume only asks PM. Never replay an unknown outcome automatically.
        state["recovery_required"] = True
        for call in state["calls"]:
            if call["status"] == "running":
                call["status"] = "unknown_after_interrupt"
        state["config"]["intent"] = "continue"
        if requirements:
            state["config"]["supplement"] = requirements
        for key in ("r", "w", "cli"):
            if getattr(args, key) is not None:
                state["config"][key] = getattr(args, key)
        state["status"] = "active"
        save(state_path, state)
    ui = UI(not args.no_tui and sys.stdout.isatty())
    ui.set_status(job=job, week="项目经理判定", cli=state["config"]["cli"], hours="由项目经理核算")
    ui.start()
    try:
        return run(state_path, state, args, ui)
    finally:
        ui.stop()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("调用已中断；回执与现场保留，重启后先交项目经理核对。", file=sys.stderr)
        sys.exit(130)
    except (OSError, ValueError) as exc:
        print(f"执行器错误：{exc}", file=sys.stderr)
        sys.exit(1)
