#!/usr/bin/env python3
"""Self-test the project-manager dispatch protocol."""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "vrt/workflow/start-week-job.py"
SANDBOX = ROOT / "ptmp/vrt-selftest"

def check(ok: bool, msg: str) -> None:
    if not ok:
        raise AssertionError(msg)
    print(f"PASS {msg}")

def main() -> int:
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
count=$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["calls"]))' "$state")
if [ "$VRT_ACTION" = PROJECT_MANAGER ]; then
  rid=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["request_id"])' "${VRT_PM_REQUEST}")
  if [ "$count" -le 1 ]; then
    cat > "$response" <<JSON
{"request_id":"$rid","kind":"dispatch","task_id":"technical-1","role":"ENGINEER","cwd":"${VRT_WORKSPACE}/nested/technical-repo","prompt":"写入 result.txt 并提交回执","reason":"验证嵌套仓库工作位置"}
JSON
  else
    cat > "$response" <<JSON
{"request_id":"$rid","kind":"complete","reason":"工程师回执已存在，流程完成"}
JSON
  fi
else
  echo engineer > result.txt
  echo "VRT_PRIMARY_PROGRESS: advanced" > agent-result.md
fi
''', encoding="utf-8")
    pm.chmod(0o755)
    env = {**os.environ, "VRT_KIMI_CMD": f"bash {pm}", "VRT_CODEX_CMD": f"bash {pm}"}
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
    check(not (base / ".git").exists(), "执行器没有创建或切换 Git")
    check(any(c["role"] == "PROJECT_MANAGER" for c in state["calls"]), "保存项目经理回执")
    second = subprocess.run([sys.executable, str(RUNNER), "--repo", str(base), "--job", "demo",
                             "--cli", "kimi", "--yes", "--no-tui", "--retry-delay", "0"],
                            capture_output=True, text=True, env=env)
    check(second.returncode == 0, "恢复后项目经理继续并完成")
    state = json.loads(states[0].read_text(encoding="utf-8"))
    check(state["status"] == "complete", "完成状态持久化")
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
