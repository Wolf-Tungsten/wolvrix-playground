#!/usr/bin/env python3
"""tesctl — TES 实验系统的无状态调度器/状态机。

所有状态都在 tes/ 目录的文件里（state/run.json + state/ledger.jsonl + runs/<run>/manifest.json）。
本工具只读取/推进状态，不保存任何跨调用内存。每个 goal 会话通过 `tesctl.py next`
获得下一个（且唯一一个）要执行的 action。

子命令：
  status            人类可读的当前状态
  next              计算并展示下一个 action（--json 输出机器可读）
  init-run          开新 run：冻结配置、建 wolvrix 分支、写 manifest 与 run.json
  record-baseline   登记 AM/gsim 基线测量结果
  begin-step        开始一个 step：生成 Φ proposal、建候选分支与 worktree
  record-eval       登记一次评估结果（append ledger）
  finish-step       收口一个 step：裁决 winner、推进轨迹主线
  round-summary-done 标记某轮 round-summary 已完成
  close-run         收口当前 run（status=completed）
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
STATE = TES / "state"
RUN_JSON = STATE / "run.json"
LEDGER = STATE / "ledger.jsonl"
CONFIG = TES / "config.json"


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


def load_config() -> dict:
    return load_json(CONFIG)


def load_run() -> dict | None:
    if not RUN_JSON.exists():
        return None
    return load_json(RUN_JSON)


def save_run(run: dict) -> None:
    save_json(RUN_JSON, run)


def git_wolvrix(*args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(REPO / "wolvrix"), *args],
        check=True, capture_output=True, text=True,
    )
    return r.stdout.strip()


def git_wolvrix_ok(*args: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(REPO / "wolvrix"), *args],
        capture_output=True,
    ).returncode == 0


def ensure_worktree(branch: str, start: str, wt_path: Path) -> None:
    """幂等建立候选 worktree：分支不存在则从 start 建分支+worktree；
    分支在但 worktree 不在则补 worktree；最后确保子模块已初始化（本地 reference，免网络）。
    这样 begin-step 在崩溃/中断后重入能补齐任何半成品现场。"""
    if not git_wolvrix_ok("rev-parse", "--verify", branch):
        git_wolvrix("worktree", "add", str(wt_path), "-b", branch, start)
    elif not wt_path.exists():
        git_wolvrix("worktree", "add", str(wt_path), branch)
    status = subprocess.run(["git", "-C", str(wt_path), "submodule", "status"],
                            check=True, capture_output=True, text=True).stdout
    needs_init = [line[1:].split()[1] for line in status.splitlines() if line.startswith("-")]
    for sp in needs_init:
        ref = REPO / "wolvrix" / sp
        cmd = ["git", "-C", str(wt_path), "submodule", "update", "--init"]
        if (ref / ".git").exists():  # gitfile 或目录皆可，exists() 都覆盖
            cmd += ["--reference", str(ref)]
        cmd += ["--", sp]
        subprocess.run(cmd, check=True, capture_output=True)


def append_ledger(entry: dict) -> None:
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def iter_ledger():
    if not LEDGER.exists():
        return
    with open(LEDGER, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


# ---------------------------------------------------------------------------
# next / status
# ---------------------------------------------------------------------------

def compute_next_action(run: dict | None) -> dict:
    """纯函数：由 run 状态确定下一个 action。调度 = 逐轮 round-robin。

    语义：C 条轨迹相互独立，串行交错执行与论文并行执行等价（轨迹间无信息流）。
    """
    if run is None:
        return {"type": "run-init", "reason": "无活跃 run，初始化 r001"}
    if run["status"] != "active":
        return {"type": "run-closed", "reason": f"{run['run_id']} 已收口；可开新 run（restart）"}

    cfg = run["config"]["search"]
    C, L, K = cfg["C"], cfg["L"], cfg["K"]

    if run["baselines"]["am"] is None or run["baselines"]["gsim"] is None:
        return {"type": "baseline", "reason": "run-init 待完成：测量 AM y0 与 gsim target 基线"}

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

    # 轮次齐平检查：所有轨迹步数一致且 >=1 且该轮未总结 -> round-summary
    m = done_steps[0]
    if all(s == m for s in done_steps) and m >= 1 and m not in run["round_summaries_done"]:
        return {"type": "round-summary", "round": m,
                "reason": f"第 {m} 轮（全部 {C} 条轨迹各完成 1 步）已齐平，做跨轨迹小结"}

    # round-robin：步数最少者优先，平手取小编号
    t = min(trajs, key=lambda t: (t["steps_completed"], t["id"]))
    return {"type": "step", "trajectory": t["id"], "step": t["steps_completed"] + 1,
            "K": K,
            "reason": f"推进轨迹 {t['id']} 到第 {t['steps_completed'] + 1} 步（round-robin 最少步数优先）"}


def cmd_status(_args) -> int:
    run = load_run()
    if run is None:
        print("TES: 无活跃 run。下一个 action: run-init")
        return 0
    cfg = run["config"]["search"]
    print(f"run: {run['run_id']}  status: {run['status']}  "
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
    if run is not None:
        na["run_id"] = run["run_id"]
        na["evals_used"] = run["counters"]["evals"]
        na["budget"] = run["config"]["search"]["C"] * run["config"]["search"]["L"] * run["config"]["search"]["K"]
    if args.json:
        print(json.dumps(na, ensure_ascii=False, indent=2))
    else:
        print(f"NEXT ACTION: {na['type']}")
        print(f"reason: {na['reason']}")
        for k, v in na.items():
            if k not in ("type", "reason"):
                print(f"{k}: {v}")
    return 0


# ---------------------------------------------------------------------------
# init-run
# ---------------------------------------------------------------------------

def cmd_init_run(args) -> int:
    if RUN_JSON.exists():
        old = load_run()
        if old["status"] == "active" and not args.force:
            print(f"[FAIL] 已有活跃 run {old['run_id']}；先 close-run 或用 --force", file=sys.stderr)
            return 1

    cfg = load_config()
    run_id = args.run_id
    if run_id is None:
        existing = sorted(p.name for p in (TES / "runs").glob("r*") if p.is_dir())
        n = max([int(x[1:]) for x in existing], default=0) + 1
        run_id = f"r{n:03d}"
    run_dir = TES / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    search = dict(cfg["search"]); search.pop("note", None)
    for k in ("C", "L", "K"):
        if getattr(args, k) is not None:
            search[k] = getattr(args, k)
    frozen = {"search": search, "phi": cfg["phi"], "eval": cfg["eval"], "restart": cfg["restart"]}

    # pin 现场：三个仓库的 commit
    wolvrix_base = args.base_commit or git_wolvrix("rev-parse", "HEAD")
    gsim_commit = subprocess.run(["git", "-C", str(REPO / "reference/gsim"), "rev-parse", "HEAD"],
                                 check=True, capture_output=True, text=True).stdout.strip()
    xs_commit = subprocess.run(["git", "-C", str(REPO / "testcase/xiangshan"), "rev-parse", "HEAD"],
                               check=True, capture_output=True, text=True).stdout.strip()

    # 建 wolvrix 分支：base + C 条轨迹主线
    base_branch = f"tes/{run_id}/base"
    if git_wolvrix_ok("rev-parse", "--verify", base_branch):
        print(f"[INFO] 分支 {base_branch} 已存在，复用")
    else:
        git_wolvrix("branch", base_branch, wolvrix_base)
    trajectories = []
    for i in range(search["C"]):
        tid = f"t{i}"
        # 主线用 .../main 叶分支：git ref 不能同时是文件与目录（t0 与 t0/s01-c1 冲突）
        br = f"tes/{run_id}/{tid}/main"
        if not git_wolvrix_ok("rev-parse", "--verify", br):
            git_wolvrix("branch", br, base_branch)
        trajectories.append({"id": tid, "branch": br, "tip": wolvrix_base,
                             "steps_completed": 0, "best": None})

    manifest = {
        "run_id": run_id,
        "created_at": now_iso(),
        "config": frozen,
        "budget_N": search["C"] * search["L"] * search["K"],
        "pins": {
            "wolvrix_base_commit": wolvrix_base,
            "wolvrix_base_branch": base_branch,
            "gsim_commit": gsim_commit,
            "xiangshan_commit": xs_commit,
            "exec_json": cfg["paths"]["exec_json"],
            "exec_json_sha256": None,  # run-init action 里补测
        },
        "baselines": {},
        "notes": [],
    }
    save_json(run_dir / "manifest.json", manifest)

    run = {
        "schema": 1,
        "run_id": run_id,
        "status": "active",
        "created_at": now_iso(),
        "config": frozen,
        "pins": manifest["pins"],
        "baselines": {"am": None, "gsim": None},
        "trajectories": trajectories,
        "current_step": None,
        "round_summaries_done": [],
        "counters": {"actions": 0, "evals": 0},
        "best_overall": None,
        "phi_selection_counts": {},
        "history": [],
    }
    save_run(run)
    print(f"[OK] run {run_id} 已初始化：base={wolvrix_base[:12]} 分支 {base_branch} + "
          f"{search['C']} 条轨迹；N={manifest['budget_N']}")
    print("下一步：按 playbook 完成 run-init action（输入指纹 + 双基线测量 + record-baseline）")
    return 0


def cmd_record_baseline(args) -> int:
    run = load_run()
    if run is None:
        print("[FAIL] 无活跃 run", file=sys.stderr)
        return 1
    result = load_json(REPO / args.result)
    side = args.side
    entry = {
        "eval_id": result["eval_id"], "run": run["run_id"], "trajectory": None,
        "step": 0, "candidate": 0, "branch": None,
        "commit": run["pins"]["wolvrix_base_commit"] if side == "am" else run["pins"]["gsim_commit"],
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
    if side == "am" and result["status"] == "ok":
        run["best_overall"] = {"eval_id": result["eval_id"], "score": result["score"],
                               "commit": run["pins"]["wolvrix_base_commit"]}
    save_run(run)
    print(f"[OK] {side} 基线已登记: {result.get('score')} (eval {result['eval_id']})")
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
    proposal_rel = f"proposals/{run['run_id']}-{tid}-s{step:02d}.md"

    candidates = []
    for k in range(1, K + 1):
        br = f"tes/{run['run_id']}/{tid}/s{step:02d}-c{k}"
        wt = f"build/tes/src/{eval_ids[k-1]}-{tid}-s{step:02d}c{k}"
        ensure_worktree(br, t["branch"], REPO / wt)
        candidates.append({"k": k, "branch": br, "worktree": wt,
                           "eval_id": eval_ids[k - 1], "status": "pending", "score": None})

    run["current_step"] = {"trajectory": tid, "step": step, "proposal": proposal_rel,
                           "candidates": candidates, "started_at": now_iso()}
    save_run(run)

    # 生成 Φ proposal（选历史节点 + 组装上下文）
    phi = TES / "tools" / "phi.py"
    r = subprocess.run([sys.executable, str(phi), "--trajectory", tid, "--step", str(step),
                        "--out", str(TES / proposal_rel)],
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
    print(f"  proposal: tes/{proposal_rel}")
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
    commit = git_wolvrix("rev-parse", cand["branch"]) if git_wolvrix_ok("rev-parse", "--verify", cand["branch"]) else None
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
        git_wolvrix("branch", "-f", t["branch"], winner["branch"])
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
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status")
    p = sub.add_parser("next"); p.add_argument("--json", action="store_true")

    p = sub.add_parser("init-run")
    p.add_argument("--run-id"); p.add_argument("--base-commit")
    p.add_argument("--C", type=int); p.add_argument("--L", type=int); p.add_argument("--K", type=int)
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("record-baseline")
    p.add_argument("--side", choices=["am", "gsim"], required=True)
    p.add_argument("--result", required=True, help="repo 相对路径 result.json")
    p.add_argument("--insight")

    p = sub.add_parser("begin-step")

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
    return {
        "status": cmd_status, "next": cmd_next, "init-run": cmd_init_run,
        "record-baseline": cmd_record_baseline, "begin-step": cmd_begin_step,
        "record-eval": cmd_record_eval, "finish-step": cmd_finish_step,
        "round-summary-done": cmd_round_summary_done, "close-run": cmd_close_run,
        "action-done": cmd_action_done,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
