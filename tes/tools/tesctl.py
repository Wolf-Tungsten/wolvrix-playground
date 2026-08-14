#!/usr/bin/env python3
"""tesctl — TES 实验系统的无状态调度器/状态机（多任务版）。

tes/ 下每个一级子目录是一个优化任务（含 config.json 即视为任务目录），各自持有
state/run.json + state/ledger.jsonl + runs/。本工具只读取/推进状态，不保存跨调用内存。
每个 goal 会话通过 `tesctl.py next` 获得下一个（且唯一一个）要执行的 action。

任务解析（--task 省略时）：只有一个任务目录 → 用之；多个则取有活跃 run 的唯一任务；
仍歧义 → 报错并列出可选任务。

子命令：
  tasks             列出所有任务及其状态
  status            人类可读的当前状态
  next              计算并展示下一个 action（--json 输出机器可读）
  dashboard         由 run.json + ledger.jsonl 重新生成 tes/dashboard.md（状态变更命令会自动刷新）
  init-run          开新 run：冻结配置、建目标仓库 tes 分支、写 manifest 与 run.json
  record-baseline   登记基线测量结果（side 由任务 config 的 baseline_sides 定义）
  begin-step        开始一个 step：生成 Φ proposal、建候选分支与 worktree
  record-eval       登记一次评估结果（append ledger）
  finish-step       收口一个 step：裁决 winner、推进轨迹主线
  round-summary-done 标记某轮 round-summary 已完成
  close-run         收口当前 run（status=completed）
  action-done       登记一个已完成的 action（更新计数与历史）
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TES = REPO / "tes"
BUILD_TES = REPO / "build" / "tes"

TASK_DIR: Path | None = None  # main() 解析 --task 后设置


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def discover_tasks() -> list[str]:
    return sorted(p.name for p in TES.iterdir()
                  if p.is_dir() and (p / "config.json").exists())


def task_has_active_run(name: str) -> bool:
    rj = TES / name / "state" / "run.json"
    if not rj.exists():
        return False
    try:
        return load_json(rj).get("status") == "active"
    except (json.JSONDecodeError, OSError):
        return False


def resolve_task(arg: str | None) -> Path:
    tasks = discover_tasks()
    if arg:
        if arg not in tasks:
            print(f"[FAIL] 任务 {arg} 不存在（tes/{arg}/config.json）。可选: {tasks}", file=sys.stderr)
            sys.exit(1)
        return TES / arg
    if not tasks:
        print("[FAIL] tes/ 下没有任何任务目录（含 config.json 的子目录）", file=sys.stderr)
        sys.exit(1)
    if len(tasks) == 1:
        return TES / tasks[0]
    active = [t for t in tasks if task_has_active_run(t)]
    if len(active) == 1:
        return TES / active[0]
    print(f"[FAIL] 多任务歧义，请用 --task 指定。任务: {tasks}，活跃: {active}", file=sys.stderr)
    sys.exit(1)


def state_dir() -> Path:
    return TASK_DIR / "state"


def run_json_path() -> Path:
    return state_dir() / "run.json"


def ledger_path() -> Path:
    return state_dir() / "ledger.jsonl"


def task_name() -> str:
    return TASK_DIR.name


def load_config() -> dict:
    return load_json(TASK_DIR / "config.json")


def load_run() -> dict | None:
    p = run_json_path()
    return load_json(p) if p.exists() else None


def save_run(run: dict) -> None:
    save_json(run_json_path(), run)


def target_repo() -> Path:
    """候选解所在仓库（config repos.target）。"""
    return REPO / load_config()["repos"]["target"]


def git_target(*args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(target_repo()), *args],
        check=True, capture_output=True, text=True,
    )
    return r.stdout.strip()


def git_target_ok(*args: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(target_repo()), *args],
        capture_output=True,
    ).returncode == 0


def ensure_worktree(branch: str, start: str, wt_path: Path) -> None:
    """幂等建立候选 worktree：分支不存在则从 start 建分支+worktree；
    分支在但 worktree 不在则补 worktree；最后确保子模块已初始化（本地 reference，免网络）。
    这样 begin-step 在崩溃/中断后重入能补齐任何半成品现场。"""
    if not git_target_ok("rev-parse", "--verify", branch):
        git_target("worktree", "add", str(wt_path), "-b", branch, start)
    elif not wt_path.exists():
        git_target("worktree", "add", str(wt_path), branch)
    status = subprocess.run(["git", "-C", str(wt_path), "submodule", "status"],
                            check=True, capture_output=True, text=True).stdout
    needs_init = [line[1:].split()[1] for line in status.splitlines() if line.startswith("-")]
    for sp in needs_init:
        ref = target_repo() / sp
        cmd = ["git", "-C", str(wt_path), "submodule", "update", "--init"]
        if (ref / ".git").exists():  # gitfile 或目录皆可，exists() 都覆盖
            cmd += ["--reference", str(ref)]
        cmd += ["--", sp]
        subprocess.run(cmd, check=True, capture_output=True)


def append_ledger(entry: dict) -> None:
    with open(ledger_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def iter_ledger():
    p = ledger_path()
    if not p.exists():
        return
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


# ---------------------------------------------------------------------------
# next / status / tasks
# ---------------------------------------------------------------------------

def compute_next_action(run: dict | None) -> dict:
    """纯函数：由 run 状态确定下一个 action。调度 = 逐轮 round-robin。

    语义：C 条轨迹相互独立，串行交错执行与论文并行执行等价（轨迹间无信息流）。
    """
    if run is None:
        return {"type": "run-init", "reason": f"任务 {task_name()} 无活跃 run，初始化 r001"}
    if run["status"] != "active":
        return {"type": "run-closed", "reason": f"{run['run_id']} 已收口；可开新 run（restart）"}

    cfg = run["config"]["search"]
    C, L, K = cfg["C"], cfg["L"], cfg["K"]

    for side in run.get("baseline_sides", []):
        if run["baselines"].get(side) is None:
            return {"type": "baseline", "side": side,
                    "reason": f"run-init 待完成：测量 {side} 基线"}

    cs = run.get("current_step")
    if cs is not None:
        done = [c for c in cs["candidates"] if c["status"] == "done"]
        if len(done) == K:
            return {"type": "finish-step", "trajectory": cs["trajectory"], "step": cs["step"],
                    "reason": f"{cs['trajectory']} s{cs['step']:02d} 的 {K} 个候选已评估完，裁决并收口"}
        return {"type": "step-resume", "trajectory": cs["trajectory"], "step": cs["step"],
                "pending": [c["k"] for c in cs["candidates"] if c["status"] != "done"],
                "reason": f"继续未完成的 step（已完成 {len(done)}/{K} 个候选）"}

    trajs = run["trajectories"]
    done_steps = [t["steps_completed"] for t in trajs]

    if all(s >= L for s in done_steps):
        return {"type": "run-summary", "reason": f"全部 {C} 条轨迹已达 L={L} 步，写 run 总结并裁决是否 restart"}

    m = done_steps[0]
    if all(s == m for s in done_steps) and m >= 1 and m not in run["round_summaries_done"]:
        return {"type": "round-summary", "round": m,
                "reason": f"第 {m} 轮（全部 {C} 条轨迹各完成 1 步）已齐平，做跨轨迹小结"}

    t = min(trajs, key=lambda t: (t["steps_completed"], t["id"]))
    return {"type": "step", "trajectory": t["id"], "step": t["steps_completed"] + 1,
            "K": K,
            "reason": f"推进轨迹 {t['id']} 到第 {t['steps_completed'] + 1} 步（round-robin 最少步数优先）"}


def cmd_tasks(_args) -> int:
    for name in discover_tasks():
        active = task_has_active_run(name)
        line = f"{name}: {'活跃' if active else '无活跃 run'}"
        if active:
            run = load_json(TES / name / "state" / "run.json")
            cfg = run["config"]["search"]
            done = sum(t["steps_completed"] for t in run["trajectories"])
            line += (f"  run {run['run_id']} (C={cfg['C']},L={cfg['L']},K={cfg['K']}) "
                     f"steps {done}/{cfg['C']*cfg['L']} evals {run['counters']['evals']}")
        print(line)
    return 0


def cmd_status(_args) -> int:
    run = load_run()
    if run is None:
        print(f"TES[{task_name()}]: 无活跃 run。下一个 action: run-init")
        return 0
    cfg = run["config"]["search"]
    print(f"task: {task_name()}  run: {run['run_id']}  status: {run['status']}  "
          f"(C={cfg['C']}, L={cfg['L']}, K={cfg['K']}, N={cfg['C']*cfg['L']*cfg['K']})")
    print(f"evals 已用: {run['counters']['evals']}  actions 已完成: {run['counters']['actions']}")
    for t in run["trajectories"]:
        best = t.get("best") or {}
        best_s = best.get("score")
        print(f"  {t['id']}: steps {t['steps_completed']}/{cfg['L']}  "
              f"branch {t['branch']}  best {best_s if best_s is not None else '-'}")
    for name, b in run["baselines"].items():
        if b:
            print(f"baseline {name}: {b.get('host_ms_median')} ms (median, eval {b.get('eval_id')})")
        else:
            print(f"baseline {name}: 未测量")
    bo = run.get("best_overall") or {}
    if bo.get("score") is not None:
        print(f"best_overall: {bo['score']} ({bo.get('eval_id')}, {bo.get('commit','')[:12]})")
    na = compute_next_action(run)
    print(f"next action: {na['type']} — {na['reason']}")
    return 0


def cmd_next(args) -> int:
    run = load_run()
    na = compute_next_action(run)
    na["task"] = task_name()
    if run is not None:
        na["run_id"] = run["run_id"]
        na["evals_used"] = run["counters"]["evals"]
        na["budget"] = run["config"]["search"]["C"] * run["config"]["search"]["L"] * run["config"]["search"]["K"]
    if args.json:
        print(json.dumps(na, ensure_ascii=False, indent=2))
    else:
        print(f"NEXT ACTION: {na['type']}  (task {task_name()})")
        print(f"reason: {na['reason']}")
        for k, v in na.items():
            if k not in ("type", "reason", "task"):
                print(f"{k}: {v}")
    return 0


# ---------------------------------------------------------------------------
# init-run
# ---------------------------------------------------------------------------

def cmd_init_run(args) -> int:
    if run_json_path().exists():
        old = load_run()
        if old["status"] == "active" and not args.force:
            print(f"[FAIL] 已有活跃 run {old['run_id']}；先 close-run 或用 --force", file=sys.stderr)
            return 1

    cfg = load_config()
    run_id = args.run_id
    runs_root = TASK_DIR / "runs"
    if run_id is None:
        existing = sorted(p.name for p in runs_root.glob("r*") if p.is_dir())
        n = max([int(x[1:]) for x in existing], default=0) + 1
        run_id = f"r{n:03d}"
    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    search = dict(cfg["search"]); search.pop("note", None)
    for k in ("C", "L", "K"):
        if getattr(args, k) is not None:
            search[k] = getattr(args, k)
    frozen = {"search": search, "phi": cfg["phi"], "eval": cfg["eval"], "restart": cfg["restart"]}

    # pin 现场：目标仓库基线 commit + config 声明的只读引用仓库
    target_base = args.base_commit or git_target("rev-parse", "HEAD")
    pin_commits = {}
    for repo in cfg["repos"].get("pin", []):
        pin_commits[repo] = subprocess.run(
            ["git", "-C", str(REPO / repo), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True).stdout.strip()

    # 建目标仓库分支：base + C 条轨迹主线
    base_branch = f"tes/{run_id}/base"
    if git_target_ok("rev-parse", "--verify", base_branch):
        print(f"[INFO] 分支 {base_branch} 已存在，复用")
    else:
        git_target("branch", base_branch, target_base)
    trajectories = []
    for i in range(search["C"]):
        tid = f"t{i}"
        # 主线用 .../main 叶分支：git ref 不能同时是文件与目录（t0 与 t0/s01-c1 冲突）
        br = f"tes/{run_id}/{tid}/main"
        if not git_target_ok("rev-parse", "--verify", br):
            git_target("branch", br, base_branch)
        trajectories.append({"id": tid, "branch": br, "tip": target_base,
                             "steps_completed": 0, "best": None})

    manifest = {
        "run_id": run_id,
        "task": task_name(),
        "created_at": now_iso(),
        "config": frozen,
        "budget_N": search["C"] * search["L"] * search["K"],
        "pins": {
            "target_repo": cfg["repos"]["target"],
            "target_base_commit": target_base,
            "target_base_branch": base_branch,
            "repos": pin_commits,
            # run-init action 里对每个 input 补测 sha256 后回填
            "inputs": [dict(i) for i in cfg.get("inputs", [])],
        },
        "baselines": {},
        "notes": [],
    }
    save_json(run_dir / "manifest.json", manifest)

    run = {
        "schema": 1,
        "run_id": run_id,
        "task": task_name(),
        "status": "active",
        "created_at": now_iso(),
        "config": frozen,
        "pins": manifest["pins"],
        "baseline_sides": list(cfg.get("baseline_sides", ["base"])),
        "baselines": {s: None for s in cfg.get("baseline_sides", ["base"])},
        "trajectories": trajectories,
        "current_step": None,
        "round_summaries_done": [],
        "counters": {"actions": 0, "evals": 0},
        "best_overall": None,
        "phi_selection_counts": {},
        "history": [],
    }
    save_run(run)
    print(f"[OK] [{task_name()}] run {run_id} 已初始化：base={target_base[:12]} 分支 {base_branch} + "
          f"{search['C']} 条轨迹；N={manifest['budget_N']}")
    print("下一步：按 playbook 完成 run-init action（输入指纹 + 基线测量 + record-baseline）")
    _refresh_dashboard()
    return 0


def cmd_record_baseline(args) -> int:
    run = load_run()
    if run is None:
        print("[FAIL] 无活跃 run", file=sys.stderr)
        return 1
    result = load_json(REPO / args.result)
    side = args.side
    primary = load_config().get("primary_baseline")
    entry = {
        "eval_id": result["eval_id"], "run": run["run_id"], "trajectory": None,
        "step": 0, "candidate": 0, "branch": None,
        "commit": run["pins"]["target_base_commit"] if side == primary else None,
        "proposal_nodes": [], "status": result["status"],
        "score": result.get("score"), "host_ms": result.get("host_ms"),
        "hypothesis": f"{side} baseline", "insight": args.insight or "",
        "committed": True, "ts": now_iso(), "kind": f"baseline-{side}",
        "result_json": args.result,
    }
    append_ledger(entry)
    run["baselines"][side] = {"eval_id": result["eval_id"], "status": result["status"],
                              "host_ms_median": (result.get("host_ms") or {}).get("median"),
                              "score": result.get("score")}
    run["counters"]["evals"] += 1
    if side == primary and result["status"] == "ok":
        run["best_overall"] = {"eval_id": result["eval_id"], "score": result["score"],
                               "commit": run["pins"]["target_base_commit"]}
    save_run(run)
    print(f"[OK] {side} 基线已登记: {result.get('score')} (eval {result['eval_id']})")
    _refresh_dashboard()
    return 0


# ---------------------------------------------------------------------------
# step 生命周期
# ---------------------------------------------------------------------------

def next_eval_ids(run: dict, k: int) -> list[str]:
    base = run["counters"]["evals"]
    return [f"e{base + i + 1:05d}" for i in range(k)]


def cmd_begin_step(args) -> int:
    run = load_run()
    if run is None or run["status"] != "active":
        print("[FAIL] 无活跃 run", file=sys.stderr)
        return 1
    if run.get("current_step") is not None:
        print("[FAIL] 有未完成 step，先 finish-step 或继续评估", file=sys.stderr)
        return 1
    na = compute_next_action(run)
    if na["type"] != "step":
        print(f"[FAIL] 下一个 action 不是 step 而是 {na['type']}：{na['reason']}", file=sys.stderr)
        return 1
    tid, step = na["trajectory"], na["step"]
    K = run["config"]["search"]["K"]
    t = next(t for t in run["trajectories"] if t["id"] == tid)
    eval_ids = next_eval_ids(run, K)
    proposal_rel = f"tes/{task_name()}/proposals/{run['run_id']}-{tid}-s{step:02d}.md"

    candidates = []
    for k in range(1, K + 1):
        br = f"tes/{run['run_id']}/{tid}/s{step:02d}-c{k}"
        wt = BUILD_TES / task_name() / "src" / f"{eval_ids[k-1]}-{tid}-s{step:02d}c{k}"
        ensure_worktree(br, t["branch"], wt)
        candidates.append({"k": k, "branch": br, "worktree": str(wt.relative_to(REPO)),
                           "eval_id": eval_ids[k - 1], "status": "pending", "score": None})

    run["current_step"] = {"trajectory": tid, "step": step, "proposal": proposal_rel,
                           "candidates": candidates, "started_at": now_iso()}
    save_run(run)

    # 生成 Φ proposal（选历史节点 + 组装上下文）
    phi = TES / "tools" / "phi.py"
    r = subprocess.run([sys.executable, str(phi), "--task", task_name(),
                        "--trajectory", tid, "--step", str(step),
                        "--out", str(REPO / proposal_rel)],
                       capture_output=True, text=True)
    print(r.stdout, end="")
    selected = []
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        print("[WARN] phi.py 失败；current_step 已建立，可手工补 proposal", file=sys.stderr)
    else:
        try:
            selected = json.loads(r.stdout.strip().splitlines()[-1]).get("selected", [])
        except (json.JSONDecodeError, IndexError):
            pass
    run = load_run()  # phi.py 更新过 selection counts，重读避免覆盖
    run["current_step"]["proposal_nodes"] = selected
    save_run(run)
    print(f"[OK] step 开始: {tid} s{step:02d}，K={K}")
    for c in candidates:
        print(f"  c{c['k']}: {c['branch']}  worktree {c['worktree']}  eval {c['eval_id']}")
    print(f"  proposal: {proposal_rel}")
    return 0


def cmd_record_eval(args) -> int:
    run = load_run()
    if run is None or run.get("current_step") is None:
        print("[FAIL] 无进行中的 step", file=sys.stderr)
        return 1
    cs = run["current_step"]
    result = load_json(REPO / args.result)
    cand = next((c for c in cs["candidates"] if c["eval_id"] == result["eval_id"]), None)
    if cand is None:
        print(f"[FAIL] eval {result['eval_id']} 不属于当前 step", file=sys.stderr)
        return 1
    if cand["status"] == "done":
        print(f"[FAIL] eval {result['eval_id']} 已登记过", file=sys.stderr)
        return 1
    commit = git_target("rev-parse", cand["branch"]) if git_target_ok("rev-parse", "--verify", cand["branch"]) else None
    entry = {
        "eval_id": result["eval_id"], "run": run["run_id"], "trajectory": cs["trajectory"],
        "step": cs["step"], "candidate": cand["k"], "branch": cand["branch"], "commit": commit,
        "proposal_nodes": cs.get("proposal_nodes", []),
        "status": result["status"], "score": result.get("score"), "host_ms": result.get("host_ms"),
        "hypothesis": args.hypothesis, "insight": args.insight or "",
        "committed": False, "ts": now_iso(), "kind": "candidate",
        "result_json": args.result,
    }
    append_ledger(entry)
    cand["status"] = "done"
    cand["score"] = result.get("score")
    run["counters"]["evals"] += 1
    if result["status"] == "ok" and result.get("score") is not None:
        bo = run.get("best_overall")
        if bo is None or result["score"] > bo["score"]:
            run["best_overall"] = {"eval_id": result["eval_id"], "score": result["score"], "commit": commit}
    save_run(run)
    print(f"[OK] 评估已登记: {result['eval_id']} status={result['status']} score={result.get('score')}")
    remaining = [c["k"] for c in cs["candidates"] if c["status"] != "done"]
    print(f"当前 step 剩余候选: {remaining if remaining else '无（可 finish-step）'}")
    _refresh_dashboard()
    return 0


def cmd_finish_step(args) -> int:
    run = load_run()
    if run is None or run.get("current_step") is None:
        print("[FAIL] 无进行中的 step", file=sys.stderr)
        return 1
    cs = run["current_step"]
    K = run["config"]["search"]["K"]
    if any(c["status"] != "done" for c in cs["candidates"]):
        print("[FAIL] 尚有候选未评估完", file=sys.stderr)
        return 1

    # 重新读 ledger 取本 step 各候选分数
    evals = {e["eval_id"]: e for e in iter_ledger()
             if e.get("run") == run["run_id"] and e.get("trajectory") == cs["trajectory"]
             and e.get("step") == cs["step"] and e.get("kind") == "candidate"}
    ok = [e for e in evals.values() if e["status"] == "ok" and e.get("score") is not None]
    tid = cs["trajectory"]
    t = next(t for t in run["trajectories"] if t["id"] == tid)

    winner = None
    if ok:
        winner = max(ok, key=lambda e: e["score"])
        # winner 合入轨迹主线（移动分支指针 = fast-forward；主线分支从不被 checkout）
        git_target("branch", "-f", t["branch"], winner["branch"])
        t["tip"] = winner["commit"]
        if t.get("best") is None or winner["score"] > t["best"]["score"]:
            t["best"] = {"eval_id": winner["eval_id"], "score": winner["score"]}
        # 标记 ledger 中 winner 为 committed
        _mark_committed(run["run_id"], tid, cs["step"], winner["eval_id"])

    t["steps_completed"] += 1
    run["current_step"] = None
    save_run(run)

    if winner:
        print(f"[OK] {tid} s{cs['step']:02d} 收口：winner={winner['eval_id']} "
              f"score={winner['score']} 已合入 {t['branch']}")
    else:
        print(f"[OK] {tid} s{cs['step']:02d} 收口：{K} 个候选全部失败，轨迹不前进（预算已耗）")
    print("下一步：写 action 笔记（actions/Axxxx_...md）并提交 playground")
    _refresh_dashboard()
    return 0


def _mark_committed(run_id: str, tid: str, step: int, eval_id: str) -> None:
    """ledger 是 append-only；commit 标记通过追加一条补丁记录实现。"""
    append_ledger({"kind": "commit-marker", "run": run_id, "trajectory": tid,
                   "step": step, "eval_id": eval_id, "committed": True, "ts": now_iso()})


def cmd_round_summary_done(args) -> int:
    run = load_run()
    if run is None:
        return 1
    if args.round not in run["round_summaries_done"]:
        run["round_summaries_done"].append(args.round)
    save_run(run)
    print(f"[OK] 第 {args.round} 轮 round-summary 已标记完成")
    return 0


def cmd_close_run(args) -> int:
    run = load_run()
    if run is None or run["status"] != "active":
        print("[FAIL] 无活跃 run", file=sys.stderr)
        return 1
    run["status"] = "completed"
    run["closed_at"] = now_iso()
    save_run(run)
    print(f"[OK] run {run['run_id']} 已收口。best_overall={json.dumps(run.get('best_overall'), ensure_ascii=False)}")
    _refresh_dashboard()
    return 0


def cmd_action_done(args) -> int:
    run = load_run()
    if run is None:
        return 1
    run["counters"]["actions"] += 1
    run["history"].append({"n": run["counters"]["actions"], "type": args.type,
                           "note": args.note, "ts": now_iso()})
    save_run(run)
    print(f"[OK] action A{run['counters']['actions']:04d} ({args.type}) 已记录: {args.note}")
    _refresh_dashboard()
    return 0


# ---------------------------------------------------------------------------
# dashboard — 由 run.json + ledger.jsonl 重新生成 tes/dashboard.md（纯导出，不手改）
# ---------------------------------------------------------------------------

def _fmt_s(ms) -> str:
    return f"{ms / 1000:.1f}s" if isinstance(ms, (int, float)) else "-"


def _fmt_ratio(ms, target_ms) -> str:
    if isinstance(ms, (int, float)) and target_ms:
        return f"{ms / target_ms:.2f}x"
    return "-"


def _progress_bar(frac: float, width: int = 20) -> str:
    frac = max(0.0, min(1.0, frac))
    n = round(frac * width)
    return "█" * n + "░" * (width - n)


def _render_task_section(name: str) -> list[str]:
    global TASK_DIR
    TASK_DIR = TES / name
    lines = [f"## 任务 `{name}`", ""]
    run = load_run()
    if run is None:
        lines += ["尚无 run。", ""]
        return lines

    cfg = load_config()
    search = run["config"]["search"]
    budget = search["C"] * search["L"] * search["K"]
    sides = run.get("baseline_sides", [])
    primary = cfg.get("primary_baseline")
    target_side = next((s for s in sides if s != primary), None)
    base = run["baselines"].get(primary) if primary else None
    target = run["baselines"].get(target_side) if target_side else None
    base_ms = (base or {}).get("host_ms_median")
    target_ms = (target or {}).get("host_ms_median")
    bo = run.get("best_overall") or {}
    best_ms = -bo["score"] if bo.get("score") is not None else None
    na = compute_next_action(run)

    lines.append(f"run **{run['run_id']}**（{run['status']}）· C={search['C']} L={search['L']} "
                 f"K={search['K']} · evals {run['counters']['evals']}/{budget} · "
                 f"actions {run['counters']['actions']} · 下一步 `{na['type']}`：{na['reason']}")
    lines.append("")
    lines.append("| 基准 | eval | Host 中位 | vs target |")
    lines.append("|---|---|---|---|")
    if target:
        lines.append(f"| {target_side}（target） | {target['eval_id']} | {_fmt_s(target_ms)} | 1.00x |")
    if base:
        lines.append(f"| {primary}（y0 基线） | {base['eval_id']} | {_fmt_s(base_ms)} | "
                     f"{_fmt_ratio(base_ms, target_ms)} |")
    if best_ms is not None:
        lines.append(f"| **当前 best** | {bo.get('eval_id', '-')} | **{_fmt_s(best_ms)}** | "
                     f"**{_fmt_ratio(best_ms, target_ms)}** |")
    lines.append("")
    if base_ms and target_ms and best_ms is not None and base_ms != target_ms:
        frac = (base_ms - best_ms) / (base_ms - target_ms)
        lines.append(f"基线→target 进度：`{_progress_bar(frac)}` {frac * 100:.1f}%"
                     f"（{_fmt_s(base_ms)} → 目标 {_fmt_s(target_ms)}，当前差距 "
                     f"{_fmt_ratio(best_ms, target_ms)}）")
        lines.append("")

    lines.append("| 轨迹 | 分支 | 步数 | best eval | best Host |")
    lines.append("|---|---|---|---|---|")
    for t in run["trajectories"]:
        b = t.get("best") or {}
        bms = -b["score"] if b.get("score") is not None else None
        lines.append(f"| {t['id']} | `{t['branch']}` | {t['steps_completed']}/{search['L']} | "
                     f"{b.get('eval_id') or '-'} | {_fmt_s(bms)} |")
    lines.append("")

    entries = [e for e in iter_ledger() if e.get("kind") != "commit-marker"]
    if entries:
        lines.append("| eval | 类别 | 位置 | Host 中位 | vs target | 状态 | 假设 |")
        lines.append("|---|---|---|---|---|---|---|")
        for e in entries:
            ms = (e.get("host_ms") or {}).get("median")
            pos = "-" if e.get("trajectory") is None else (
                f"{e['trajectory']}/s{e['step']:02d}c{e['candidate']}")
            hyp = (e.get("hypothesis") or "").replace("|", "\\|")
            if len(hyp) > 50:
                hyp = hyp[:50] + "…"
            lines.append(f"| {e['eval_id']} | {e.get('kind', '-')} | {pos} | {_fmt_s(ms)} | "
                         f"{_fmt_ratio(ms, target_ms)} | {e.get('status', '-')} | {hyp} |")
        lines.append("")

    hist = run.get("history", [])[-5:]
    if hist:
        lines.append("最近 actions："
                     + "；".join(f"A{h['n']:04d} {h['type']}" for h in hist))
        lines.append("")
    return lines


def render_dashboard() -> str:
    global TASK_DIR
    saved = TASK_DIR
    try:
        lines = [
            "# TES 性能看板",
            "",
            "> 本文件由 `python3 tes/tools/tesctl.py dashboard` 生成；record-baseline / record-eval /",
            "> finish-step / close-run / action-done 等状态变更后也会自动刷新。**请勿手改。**",
            f"> 生成于 {now_iso()}",
            "",
        ]
        tasks = discover_tasks()
        if not tasks:
            lines.append("暂无任务（tes/ 下没有含 config.json 的目录）。")
        for name in tasks:
            lines.extend(_render_task_section(name))
        return "\n".join(lines) + "\n"
    finally:
        TASK_DIR = saved


def cmd_dashboard(_args) -> int:
    out = TES / "dashboard.md"
    out.write_text(render_dashboard(), encoding="utf-8")
    print(f"[OK] 看板已生成: {out.relative_to(REPO)}")
    return 0


def _refresh_dashboard() -> None:
    """状态变更后尽力自动刷新看板；失败不影响主命令。"""
    try:
        (TES / "dashboard.md").write_text(render_dashboard(), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] 看板自动刷新失败: {e}", file=sys.stderr)


def main() -> int:
    global TASK_DIR
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", help="任务名（tes/ 下一级目录）；省略时自动解析")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("tasks")
    sub.add_parser("status")
    sub.add_parser("dashboard")
    p = sub.add_parser("next"); p.add_argument("--json", action="store_true")

    p = sub.add_parser("init-run")
    p.add_argument("--run-id"); p.add_argument("--base-commit")
    p.add_argument("--C", type=int); p.add_argument("--L", type=int); p.add_argument("--K", type=int)
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("record-baseline")
    p.add_argument("--side", required=True)
    p.add_argument("--result", required=True, help="repo 相对路径 result.json")
    p.add_argument("--insight")

    sub.add_parser("begin-step")

    p = sub.add_parser("record-eval")
    p.add_argument("--result", required=True)
    p.add_argument("--hypothesis", required=True)
    p.add_argument("--insight")

    sub.add_parser("finish-step")

    p = sub.add_parser("round-summary-done")
    p.add_argument("--round", type=int, required=True)

    sub.add_parser("close-run")

    p = sub.add_parser("action-done")
    p.add_argument("--type", required=True)
    p.add_argument("--note", required=True, help="actions/Axxxx_...md 的 repo 相对路径")

    args = ap.parse_args()
    TASK_DIR = resolve_task(args.task)
    return {
        "tasks": cmd_tasks, "status": cmd_status, "next": cmd_next,
        "dashboard": cmd_dashboard,
        "init-run": cmd_init_run, "record-baseline": cmd_record_baseline,
        "begin-step": cmd_begin_step, "record-eval": cmd_record_eval,
        "finish-step": cmd_finish_step, "round-summary-done": cmd_round_summary_done,
        "close-run": cmd_close_run, "action-done": cmd_action_done,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
