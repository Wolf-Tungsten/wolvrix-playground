#!/usr/bin/env python3
"""phi — SimpleTES 的提案构造器 Φ 的 TES 实例化。

从台账（ledger.jsonl）重建当前轨迹的已提交历史 S，用 RPUCG（图版 PUCT，
分数 min-max 归一化后做 U 值反向传播）选择最多 max_nodes 个历史节点，
组装下一个 step 的 proposal 文件（tes/proposals/<run>-<traj>-sNN.md）。

输出：proposal 文件 + stdout 最后一行 JSON {"selected": [eval_id, ...]}。
纯函数式：除写 proposal 文件和更新 run.json 的 phi_selection_counts 外无副作用。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TES = REPO / "tes"
TASK_DIR: Path | None = None  # main() 里按 --task 设置


def ledger_file() -> Path:
    return TASK_DIR / "state" / "ledger.jsonl"


def run_json_file() -> Path:
    return TASK_DIR / "state" / "run.json"


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def iter_ledger():
    lp = ledger_file()
    if not lp.exists():
        return
    with open(lp, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def trajectory_nodes(run_id: str, tid: str):
    """重建轨迹的已提交集合 S 与附属列表。

    S = 本 run 的 am 基线（root y0）+ 本轨迹所有被 commit-marker 标记的 winner。
    返回 (S, rejected, failed)：rejected=评估成功但未中选的候选，failed=失败候选。
    """
    committed_ids = set()
    entries = []
    for e in iter_ledger():
        if e.get("run") != run_id:
            continue
        if e.get("kind") == "commit-marker":
            if e.get("trajectory") == tid:
                committed_ids.add(e["eval_id"])
            continue
        entries.append(e)
    S, rejected, failed = [], [], []
    for e in entries:
        if e.get("kind") == "baseline-am":
            S.append(e)  # root
            continue
        if e.get("trajectory") != tid or e.get("kind") != "candidate":
            continue
        if e["eval_id"] in committed_ids:
            S.append(e)
        elif e["status"] == "ok":
            rejected.append(e)
        else:
            failed.append(e)
    return S, rejected, failed


def rpucg_select(S: list[dict], counts: dict[str, int], gamma: float, lam: float,
                 max_nodes: int) -> tuple[list[str], list[dict]]:
    """图版 PUCT：U_i = max(rn_i, gamma * max_child U)，归一化分数；探索项 λρ√(1+|S|)/(1+n)。

    返回选中的 eval_id 列表与调试表。
    """
    if not S:
        return [], []
    by_id = {e["eval_id"]: e for e in S}
    children: dict[str, list[str]] = {e["eval_id"]: [] for e in S}
    for e in S:
        for p in e.get("proposal_nodes") or []:
            if p in children:
                children[p].append(e["eval_id"])

    scores = [e["score"] for e in S]
    lo, hi = min(scores), max(scores)
    norm = {}
    for e in S:
        norm[e["eval_id"]] = 1.0 if hi == lo else (e["score"] - lo) / (hi - lo)

    # U 反向传播（图为 DAG：父节点一定先于子节点产生）
    U: dict[str, float] = {}

    def u_of(nid: str) -> float:
        if nid in U:
            return U[nid]
        u = norm[nid]
        ch = children.get(nid) or []
        if ch:
            u = max(u, gamma * max(u_of(c) for c in ch))
        U[nid] = u
        return u

    for e in S:
        u_of(e["eval_id"])

    order = sorted(S, key=lambda e: e["score"])
    rho = {}
    n = len(S)
    for i, e in enumerate(order):
        rho[e["eval_id"]] = 1.0 if n == 1 else i / (n - 1)

    table = []
    for e in S:
        nid = e["eval_id"]
        ni = counts.get(nid, 0)
        explore = lam * rho[nid] * math.sqrt(1 + n) / (1 + ni)
        table.append({"eval_id": nid, "score": e["score"], "U": U[nid], "rho": rho[nid],
                      "n": ni, "explore": explore, "rpucg": U[nid] + explore,
                      "parents": list(e.get("proposal_nodes") or []), "children": children[nid]})

    selected: list[str] = []
    banned: set[str] = set()
    for row in sorted(table, key=lambda r: -r["rpucg"]):
        if len(selected) >= max_nodes:
            break
        nid = row["eval_id"]
        if nid in banned:
            continue
        selected.append(nid)
        # 排除一跳邻居，降低冗余
        banned.update(row["parents"])
        banned.update(row["children"])
    return selected, table


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--trajectory", required=True)
    ap.add_argument("--step", type=int, required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    global TASK_DIR
    TASK_DIR = TES / args.task
    run = load_json(run_json_file())
    run_id = run["run_id"]
    cfg = run["config"]
    phi_cfg = cfg["phi"]
    K = cfg["search"]["K"]
    tid = args.trajectory

    S, rejected, failed = trajectory_nodes(run_id, tid)
    counts = run.get("phi_selection_counts", {})
    selected, table = rpucg_select(S, counts, phi_cfg["gamma"], phi_cfg["lambda"],
                                   phi_cfg["max_nodes"])

    # 轨迹主线 tip（最近提交节点）强制纳入，保证精修连续性
    tip = max(S, key=lambda e: (e.get("step") or 0, e["eval_id"])) if S else None
    if tip and tip["eval_id"] not in selected:
        if len(selected) >= phi_cfg["max_nodes"] and selected:
            selected[-1] = tip["eval_id"]
        else:
            selected.append(tip["eval_id"])

    counts = dict(counts)
    for nid in selected:
        counts[nid] = counts.get(nid, 0) + 1
    run["phi_selection_counts"] = counts
    rj = run_json_file()
    tmp = rj.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(run, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(rj)

    by_id = {e["eval_id"]: e for e in S}
    brief = (TASK_DIR / "brief.md").read_text(encoding="utf-8")
    protocol_file = TASK_DIR / "protocol.md"  # 任务自定义的评估协议文本，可选
    tstate = next(t for t in run["trajectories"] if t["id"] == tid)

    lines: list[str] = []
    lines.append(f"# Proposal {run_id}/{tid}/s{args.step:02d}（Φ 自动生成）\n")
    lines.append(f"- task: {args.task}  run: {run_id}  trajectory: {tid}  step: {args.step}/{cfg['search']['L']}")
    lines.append(f"- 轨迹主线分支: `{tstate['branch']}`  best: {json.dumps(tstate.get('best'))}")
    for side, b in (run.get("baselines") or {}).items():
        if b:
            lines.append(f"- 基线 {side}: score {b.get('score')}"
                         f"（host 中位 {b.get('host_ms_median')} ms，eval {b.get('eval_id')}）")
    lines.append("\n---\n\n## 任务指令（x0）\n")
    lines.append(brief)
    if protocol_file.exists():
        lines.append("\n## 评估协议\n")
        lines.append(protocol_file.read_text(encoding="utf-8"))
    lines.append("\n## Φ 选中的历史节点（本轮 refinement 的出发材料）\n")
    if not selected:
        lines.append("-（无历史节点；本 step 从基线直接出发）")
    for nid in selected:
        e = by_id[nid]
        hm = e.get("host_ms") or {}
        lines.append(f"### {nid}（step {e.get('step')}, score {e.get('score')}, host 中位 {hm.get('median')} ms）")
        lines.append(f"- 假设: {e.get('hypothesis')}")
        if e.get("insight"):
            lines.append(f"- 洞察: {e['insight']}")
        lines.append(f"- 分支 `{e.get('branch')}`  commit `{str(e.get('commit'))[:12]}`  结果 `{e.get('result_json')}`")
        lines.append("")
    if phi_cfg.get("include_rejected", True) and rejected:
        lines.append("\n## 本轨迹已评估但未中选的变体（避免原样重试；可在其基础上改机制）\n")
        for e in rejected[-8:]:
            hm = e.get("host_ms") or {}
            lines.append(f"- {e['eval_id']} s{e.get('step')}c{e.get('candidate')}: score {e.get('score')}"
                         f"（{hm.get('median')} ms）— {e.get('hypothesis')}")
    if phi_cfg.get("include_failures", True) and failed:
        lines.append("\n## 失败模式摘要（本轨迹）\n")
        for e in failed[-8:]:
            lines.append(f"- {e['eval_id']} s{e.get('step')}c{e.get('candidate')}: **{e['status']}** — {e.get('hypothesis')}"
                         f"（日志见 `{e.get('result_json')}`）")
    lines.append("\n## 本 step 任务\n")
    lines.append(f"设计并实现 **{K} 个互不相同的候选**（机制层面不同，不是同一想法的参数微调；"
                 "任务支持的可调旋钮见上方任务指令）。每个候选：在各自 worktree 实施 → 提交到各自"
                 "候选分支 → 任务 evaluator 串行评估 → `tesctl.py record-eval` 登记。"
                 "全部完成后 `tesctl.py finish-step` 裁决。")
    lines.append("\n## Φ 选择调试表（RPUCG）\n")
    lines.append("| node | score | U | ρ | n | RPUCG | selected |")
    lines.append("|---|---|---|---|---|---|---|")
    for row in sorted(table, key=lambda r: -r["rpucg"]):
        lines.append(f"| {row['eval_id']} | {row['score']} | {row['U']:.3f} | {row['rho']:.2f} | "
                     f"{row['n']} | {row['rpucg']:.3f} | {'*' if row['eval_id'] in selected else ''} |")
    lines.append("")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"[phi] proposal 已写入 {out}（选中 {len(selected)} 节点: {selected}）")
    print(json.dumps({"selected": selected}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
