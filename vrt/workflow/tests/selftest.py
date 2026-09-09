#!/usr/bin/env python3
"""Self-test the project-manager dispatch protocol."""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
import runpy
import io
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "vrt/workflow/start-week-job.py"
SANDBOX = ROOT / "ptmp/vrt-selftest"

def check(ok: bool, msg: str) -> None:
    if not ok:
        raise AssertionError(msg)
    print(f"PASS {msg}")

def main() -> int:
    sys.path.insert(0, str(RUNNER.parent))
    runner = runpy.run_path(str(RUNNER))
    from runner_ui import UI
    from runtime_selftest import runtime_tests
    runtime_tests(ROOT, SANDBOX, check)
    prompts = ROOT / "vrt/workflow/prompts"
    check(not (prompts / ("race_" + "contract.md")).exists(), "旧赛马契约已移除")
    check("不负责实现步骤" in (prompts / "pi_plan.tmpl.md").read_text(encoding="utf-8"),
          "PI 提示词只保留方向职责")
    engineer_prompt = (prompts / "eng_exec.tmpl.md").read_text(encoding="utf-8")
    check("不能直接甩回 RA" in engineer_prompt and "尝试最小修复" in engineer_prompt,
          "工程师提示词要求遇阻继续排查修复")
    check(all(len(p.read_text(encoding="utf-8").splitlines()) <= 20
              for p in prompts.glob("*.tmpl.md")), "角色模板保持精简")
    check(runner["cli_command"]("codex", "x")[-1] == "x",
          "Codex 保持提示词原样，由派发层添加角色前缀")
    check(runner["cli_command"]("kimi", "/goal x")[-1] == "/goal x",
          "Kimi 不重复添加 /goal 前缀")
    dashboard = UI(False)
    sample = {"config": {"week": 4, "r": 2, "w": 6}, "decisions": []}
    runner["refresh_dashboard"](dashboard, sample)
    check(dashboard.status["week"] == "4" and dashboard.status["hours"] == "RA1:?/6 RA2:?/6",
          "启动看板显示指定周次和配额，未知用量不冒充零")
    sample["decisions"] = [{"decision": {"week": 4, "hours_budget": 6,
                                          "hours_used": {"1": 2, "2": 0}}}]
    runner["refresh_dashboard"](dashboard, sample)
    check(dashboard.status["hours"] == "RA1:2/6 RA2:0/6", "项目经理决策刷新调用计数")
    sample["decisions"].append({"decision": {"kind": "dispatch"}})
    runner["refresh_dashboard"](dashboard, sample)
    check(dashboard.status["week"] == "4" and "RA1:2/6" in dashboard.status["hours"],
          "恢复和旧格式响应保留最近已确认数据")
    sample["decisions"].append({"decision": {"week": 5, "hours_used": {}}})
    runner["refresh_dashboard"](dashboard, sample)
    check(dashboard.status["hours"] == "RA1:?/6 RA2:?/6", "空对象及换周不显示空白或沿用旧用量")
    dashboard.set_status(cwd="/nested/repo", action="PI plan")
    dashboard.add_artifact("PI: returned")
    runner["refresh_dashboard"](dashboard, sample)
    with redirect_stdout(io.StringIO()) as captured:
        dashboard._draw_header()
    check("工作目录: /nested/repo" in captured.getvalue() and "最近回执:" in captured.getvalue()
          and "周次=5" in captured.getvalue(), "实际看板渲染显示正确标签及周次")
    base = SANDBOX / "pm-protocol"
    if base.exists():
        shutil.rmtree(base)
    nested = base / "nested" / "technical-repo"
    nested.mkdir(parents=True)
    (nested / "README.md").write_text("nested repository\n", encoding="utf-8")
    pm = base / "mock_pm.sh"
    pm.write_text(r'''#!/usr/bin/env bash
set -euo pipefail
response="${VRT_PM_RESPONSE:-}"
state="${VRT_RECEIPTS:?}"
printf '%s' "${@: -1}" > "${VRT_RECEIPTS}.${VRT_ACTION}.prompt.txt"
test -f "${VRT_INBOX:?}"
test -n "${VRT_INBOX_ACTOR:?}"
count=$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["calls"]))' "$state")
if [ "$VRT_ACTION" = PROJECT_MANAGER ]; then
  printf '%s' "${@: -1}" > "${VRT_PM_REQUEST}.prompt.txt"
  rid=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["request_id"])' "${VRT_PM_REQUEST}")
  if [ "$count" -le 1 ]; then
    printf '%s\n' '运行时追加：保留验证证据' | make --no-print-directory -s -C "$VRT_TEST_DRIVER_ROOT" vrt_inbox VRT_INBOX_ACTION=send
    cat > "$response" <<JSON
{"request_id":"$rid","kind":"dispatch","task_id":"technical-1","role":"ENGINEER","cwd":"${VRT_WORKSPACE}/nested/technical-repo","prompt":"写入 result.txt 并提交回执","reason":"验证嵌套仓库工作位置"}
JSON
  else
    make --no-print-directory -s -C "$VRT_TEST_DRIVER_ROOT" vrt_inbox VRT_INBOX_ACTION=history > "${VRT_RECEIPTS}.history.json"
    cat > "$response" <<JSON
{"request_id":"$rid","kind":"complete","reason":"工程师回执已存在，流程完成"}
JSON
  fi
else
  make --no-print-directory -s -C "$VRT_TEST_DRIVER_ROOT" vrt_inbox VRT_INBOX_ACTION=consume > inbox-received.txt
  echo engineer > result.txt
  echo "VRT_PRIMARY_PROGRESS: advanced" > agent-result.md
fi
''', encoding="utf-8")
    pm.chmod(0o755)
    env = {**os.environ, "VRT_KIMI_CMD": f"bash {pm}", "VRT_CODEX_CMD": f"bash {pm}",
           "VRT_TEST_DRIVER_ROOT": str(ROOT)}
    first = subprocess.run([sys.executable, str(RUNNER), "--repo", str(base), "--new", "demo",
                            "--requirements", "验证项目经理协议", "--cli", "kimi", "--yes",
                            "--no-tui", "--retry-delay", "0", "--max-actions", "1"],
                           capture_output=True, text=True, env=env)
    check(first.returncode == 0, "项目经理首次派发成功")
    states = list((base / "vrt/demo/.runner").glob("*/state.json"))
    check(len(states) == 1, "生成单一执行状态文件")
    state = json.loads(states[0].read_text(encoding="utf-8"))
    dispatch = next(d["decision"] for d in state["decisions"] if d["decision"]["kind"] == "dispatch")
    check(dispatch["cwd"].endswith("nested/technical-repo"), "项目经理选择嵌套仓库")
    check((nested / "result.txt").is_file(), "技术 Agent 在指定目录执行")
    check((nested / "inbox-received.txt").read_text().strip() == "运行时追加：保留验证证据",
          "嵌套目录 Agent 经 Makefile 领取共享 inbox")
    check(not (base / "vrt/demo/.runner/inbox.txt").read_text(), "真实派发领取后清空待处理文件")
    check(not (base / ".git").exists(), "执行器没有创建或切换 Git")
    check(any(c["role"] == "PROJECT_MANAGER" for c in state["calls"]), "保存项目经理回执")
    for role in ("PROJECT_MANAGER", "ENGINEER"):
        actual = Path(str(states[0]) + f".{role}.prompt.txt").read_text(encoding="utf-8")
        check("每隔最多 3 分钟" in actual and "VRT_INBOX_ACTION=consume" in actual
              and "VRT_INBOX_ACTION=history" in actual
              and str(base / "vrt/demo/.runner/inbox.txt") in actual,
              f"实际 {role} 调用收到统一轮询指令、历史与共享 inbox 绝对路径")
    def check_pm_context(snapshot: dict) -> None:
        for entry in snapshot["decisions"]:
            prompt = Path(entry["request"] + ".prompt.txt").read_text(encoding="utf-8")
            for line in (f"工作区入口：{base}", "项目名称：demo",
                         f"当前项目档案目录：{base / 'vrt/demo'}",
                         f"本次执行会话目录：{states[0].parent}",
                         f"本次请求文件：{entry['request']}",
                         f"本次响应文件：{entry['response']}",
                         f"调用回执文件：{states[0]}"):
                check(line in prompt.splitlines(), f"实际 CLI 提示词包含 {line}")
    check_pm_context(state)
    second = subprocess.run([sys.executable, str(RUNNER), "--repo", str(base), "--job", "demo",
                             "--cli", "codex", "--yes", "--no-tui", "--retry-delay", "0"],
                            capture_output=True, text=True, env=env)
    check(second.returncode == 0, "恢复后项目经理继续并完成")
    state = json.loads(states[0].read_text(encoding="utf-8"))
    check_pm_context(state)
    check(state["status"] == "complete", "完成状态持久化")
    shared_history = json.loads(Path(str(states[0]) + ".history.json").read_text())
    check(shared_history[-1]["text"].strip() == "运行时追加：保留验证证据",
          "恢复后的项目经理仍可读取工程师已领取的用户要求")
    check(len(state["decisions"]) >= 2, "派发与完成决策均有记录")
    check((base / "vrt/demo/project.json").is_file(), "项目元数据位于 vrt/项目名")
    check((base / "vrt/demo/requirements.md").read_text().strip() == "验证项目经理协议",
          "创建时保存完整需求")
    check(all(Path(c["log"]).is_relative_to(base / "vrt/demo") for c in state["calls"]),
          "调用日志归档在项目目录")
    (base / "vrt/workflow").mkdir()
    command = [sys.executable, str(RUNNER), "--repo", str(base), "--cli", "kimi",
               "--r", "1", "--w", "1", "--no-tui", "--retry-delay", "0",
               "--max-retries", "1", "--max-actions", "1"]
    created = subprocess.run(command, input="n\ndemo2\n第一行需求\n第二行需求\n.\n",
                             capture_output=True, text=True, env=env, timeout=15)
    check(created.returncode == 0, "交互菜单创建项目并派发")
    check((base / "vrt/demo2/requirements.md").read_text().strip() == "第一行需求\n第二行需求",
          "多行需求完整归档")
    selected = subprocess.run(command, input="2\n.\n", capture_output=True,
                              text=True, env=env, timeout=15)
    check(selected.returncode == 0 and "[2] demo2" in selected.stdout,
          "交互菜单按编号选择已有项目")
    check("[3] workflow" not in selected.stdout, "菜单排除 workflow")
    existing = subprocess.run(command + ["--new", "demo", "--requirements", "不能覆盖", "--yes"],
                              capture_output=True, text=True, env=env, timeout=15)
    check(existing.returncode != 0 and "项目已存在" in existing.stderr, "拒绝覆盖已有项目")
    missing = subprocess.run(command + ["--job", "missing", "--yes"],
                             capture_output=True, text=True, env=env, timeout=15)
    check(missing.returncode != 0 and "项目不存在" in missing.stderr, "拒绝选择不存在的项目")
    print("全部项目经理协议自测试通过。")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, subprocess.SubprocessError) as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        raise SystemExit(1)
