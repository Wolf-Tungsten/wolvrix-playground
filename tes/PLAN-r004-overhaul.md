# r004 搜索流程修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 tes 搜索流程的三处失效（测量噪声地板、假设供给中断、表型漏传），并把 r004 重构为 C=6 L=4 K=2 的加宽减深搜索。

**Architecture:** 测量层在 evaluator.py 落地 rep 级聚簇裁决（快簇中位取代跨簇 median）+ 协变量记录 + retime 补测；调度层在 tesctl.py 落地表型审计门、recon 正式 action（新鲜度门）、winner outcome 分类与迁移席位；Φ 层做 neutral 降权与 recon 引用段；最后文档/config 同步并开 r004。

**Tech Stack:** Python 3（stdlib only：unittest/mock、statistics、threading、fcntl）、bash、git。

**Spec:** `tes/DESIGN-r004-overhaul.md`（计划从 spec 论证，执行时两者一起读）

## Global Constraints

- 测量纪律硬约束：任何 emu 计时/profiling 必须持 `flock(build/tes/LOCK)` 且开跑前无其他 `emu` 进程；goal 会话在计时阶段不得发起其他负载。
- `tes/<task>/state/ledger.jsonl` **只追加**；`run.json` 只能由 tesctl.py/phi.py 写；manifest/proposal 快照不修改。
- evaluator.py 的 `EVAL_CFG` 在有活跃 run 时来自 run.json 的**冻结配置**：所有新增 config 键必须 `EVAL_CFG.get(key, default)` 读取，保证旧 run 的冻结配置不因缺键崩溃。
- recon / retime / 冒烟实验**不消耗 eval 预算**（`counters.evals` 不变、不进 ledger 候选流）。
- playground 不开分支；提交在当前分支（`grh/tes-grhsim-am`），前缀 `tes(r004-overhaul): <msg>`；**不 bump 任何 submodule 指针**（`git add` 时显式列路径，不用 `git add -A`）。
- 每个任务完成 = 测试通过 + 提交。提交前 `git status` 确认 submodule 指针未混入。
- 测试运行方式：`python3 -m unittest discover -s <tests-dir> -v`；tes 工具链无 ctest。
- 现有测试 `tes/grhsim-am-coremark/tests/test_evaluator.py` 编码的是旧固定 3 rep 协议，Task 2 重写它属于本计划范围。

---

### Task 1: 冒烟实验——双态根因与 numactl 验证（spec §1.1）

零代码改动、零预算开销，用现成 gsim emu（`build/xs/gsim/gsim-compile/emu`）做纯计时对照，决定 Task 4 是否启用 numactl 包装。

**Files:**
- Create: `scripts/tes_smoke_numa_cluster.py`（一次性实验脚本，头部标注 spike）
- Modify: `tes/grhsim-am-coremark/state/insights.md`（追加结论条目）

**Interfaces:**
- Consumes: `build/xs/gsim/gsim-compile/emu`、`testcase/xiangshan/ready-to-run/coremark-2-iteration.bin`、`riscv64-nemu-interpreter-so`（路径与 `tes/grhsim-am-coremark/config.json` paths 一致）。
- Produces: `tmp/tes_smoke_numa_<ts>.json` + stdout 汇总表；insights 条目给出裁决：Task 4 启用 or 跳过。

- [ ] **Step 1: 确认 core→NUMA 归属**

```bash
numactl --hardware | grep -E "node [01] cpus"
```

从输出确定 cores 12/13/14 所在节点（记为 LOCAL_NODE，另一节点为 REMOTE_NODE）。写进脚本头部注释。

- [ ] **Step 2: 写冒烟脚本**

```python
#!/usr/bin/env python3
"""spike: r004 协议修复冒烟——双态复现与 numactl membind 对照（spec §1.1）。

三组各 6 rep（每批 3 个并行，taskset 绑 12/13/14）：
  A 现状 / B numactl --membind=LOCAL_NODE / C --membind=REMOTE_NODE
每 rep 在 +5s/+25s 采样 /proc/<pid>/smaps_rollup(AnonHugePages) 与 numa_maps 节点分布。
持 build/tes/LOCK + 起跑前无其他 emu（与 evaluator 同纪律）。不进 ledger。
"""
```

核心结构（可直接照抄实现）：

```python
EMU = REPO / "build/xs/gsim/gsim-compile/emu"
EMU_ARGS = ["-i", "testcase/xiangshan/ready-to-run/coremark-2-iteration.bin",
            "--diff", "testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so",
            "-b", "0", "-e", "0", "-C", "50000"]
GROUPS = {"A_base": [], "B_membind_local": ["numactl", f"--membind={LOCAL}"],
          "C_membind_remote": ["numactl", f"--membind={REMOTE}"]}
CORES = ["12", "13", "14"]
REPS_PER_GROUP = 6

def run_batch(group, prefix, start, count, outdir):
    # 与 evaluator._run_rep_batch 同构：taskset -c <core> <prefix...> emu <EMU_ARGS>
    # 每 rep 起采样线程（见下），等全部结束，parse "Host time spent: N ms"
    ...

def sample_proc(pid, stop, out):
    # 1Hz；+5s/+25s 各抓一次即可：
    # AnonHugePages: re.search(r"AnonHugePages:\s+(\d+) kB", smaps_rollup)
    # numa_maps: 汇总所有行的 N<n>=<pages> → {"N0": int, "N1": int}
    ...
```

主流程：flock → pgrep emu 守卫 → 逐组跑 → 写 JSON + 打印每组 per-rep host_ms 表。

- [ ] **Step 3: 跑实验**

```bash
python3 scripts/tes_smoke_numa_cluster.py
```

预期墙钟 ~10-15 min（gsim 单 rep ~46s，18 rep 分 6 批）。若中途 LOCK 被占或检出其他 emu，等待后重跑。

- [ ] **Step 4: 分析并裁决**

判据（写进脚本 docstring 尾部作为执行记录）：
- B 组单簇且水位 ≈ A 组快簇 → NUMA 放置是根因，**Task 4 启用** `numactl_membind=<LOCAL>`；
- 三组都仍双态 → numactl 无效，**Task 4 跳过**，聚簇裁决（Task 2）为主修复；
- C 组一致慢、B 组一致快 → 根因坐实（错位对照），结论同上第一支。

- [ ] **Step 5: 记 insights + 提交**

insights.md 追加条目：三组 per-rep 数据表、协变量观察（AnonHugePages/NUMA 分布是否与快慢簇相关）、Task 4 裁决。

```bash
git add scripts/tes_smoke_numa_cluster.py tes/grhsim-am-coremark/state/insights.md
git commit -m "tes(r004-overhaul): numa 双态冒烟实验与 numactl 裁决"
```

---

### Task 2: evaluator.py 聚簇裁决 + 自适应 rep + 协变量记录（spec §1.2）

测量修复的核心。`run_reps` 从固定 3 rep 改为簇结构自适应；score 一律取快簇中位。

**Files:**
- Modify: `tes/grhsim-am-coremark/evaluator.py`（`_run_rep_batch` L117-168、`run_reps` L171-218）
- Test: `tes/grhsim-am-coremark/tests/test_evaluator.py`（重写）

**Interfaces:**
- Produces（后续任务依赖）：
  - `cluster_reps(times_ms: list[float], ratio: float) -> list[list[int]]`：按倍率缝隙聚簇，返回按簇中位升序的簇列表（元素 = rep 下标列表）。
  - `adjudicate_reps(times_ms: list[float], ratio: float) -> dict`：返回
    `{"state": "unimodal"|"bimodal"|"degraded", "clusters": list[list[int]], "fast_cluster": list[int], "median": float, "median_all": float}`。
  - `run_reps(...)` 的 result["host_ms"] 新增键：`median_all`、`clusters`、`state`、`fast_cluster`；`median` = 快簇中位（下游 tesctl/phi/dashboard 读 `median` 不变）。
  - rep 记录新增 `proc_state: {"anon_hugepages_kb_max": int, "numa_pages": {"N0": int, "N1": int}, "samples": int}`。

- [ ] **Step 1: 写失败测试（先重写整个测试文件）**

```python
#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest import mock

EVALUATOR = Path(__file__).resolve().parents[1] / "evaluator.py"
SPEC = importlib.util.spec_from_file_location("grhsim_am_coremark_evaluator", EVALUATOR)
assert SPEC is not None and SPEC.loader is not None
evaluator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluator)


def fake_reps(start, count, times):
    # times 是本批次自己的列表（批内下标从零起）；start 是全局 rep 序号
    return [{"rep": i, "core": 12, "rc": 0, "host_ms": times[i - start],
             "instrCnt": 73584, "cycleCnt": 49998}
            for i in range(start, start + count)]


class ClusterRepsTest(unittest.TestCase):
    def test_bimodal_split(self):
        cl = evaluator.cluster_reps([295000, 389000, 296000], 1.15)
        self.assertEqual([[0, 2], [1]], cl)  # 按簇中位升序，快簇在前

    def test_unimodal_stays_one(self):
        self.assertEqual([[0, 1, 2]], evaluator.cluster_reps([295000, 297000, 296000], 1.15))

    def test_singleton_outlier_separate(self):
        self.assertEqual([[1, 2], [0]], evaluator.cluster_reps([250000, 295000, 296000], 1.15))


class AdjudicateRepsTest(unittest.TestCase):
    def test_fast_cluster_median(self):
        adj = evaluator.adjudicate_reps([295000, 389200, 295000], 1.15)
        self.assertEqual("bimodal", adj["state"])
        self.assertEqual(295000, adj["median"])
        self.assertAlmostEqual(326400, adj["median_all"], delta=1)

    def test_unimodal_plain_median(self):
        adj = evaluator.adjudicate_reps([295000, 296000, 297000], 1.15)
        self.assertEqual("unimodal", adj["state"])
        self.assertEqual(296000, adj["median"])

    def test_all_singletons_degraded(self):
        adj = evaluator.adjudicate_reps([250000, 300000, 390000], 1.15)
        self.assertEqual("degraded", adj["state"])
        self.assertEqual(250000, adj["median"])  # 取最快簇，保守


class AdaptiveRepProtocolTest(unittest.TestCase):
    def run_with(self, batches_times):
        calls = []

        def fake_batch(_emu, _cwd, _run_dir, start_idx, count, _cores):
            calls.append(count)
            return fake_reps(start_idx, count, batches_times[len(calls) - 1])

        with mock.patch.object(evaluator, "_run_rep_batch", side_effect=fake_batch):
            with mock.patch.dict(evaluator.EVAL_CFG, {}, clear=False):
                return evaluator.run_reps(Path("/fake/emu"), Path("/fake/run")), calls

    def test_unimodal_stops_at_three(self):
        result, calls = self.run_with([[250000, 251000, 252000]])
        self.assertEqual([3], calls)
        self.assertEqual("unimodal", result["host_ms"]["state"])
        self.assertEqual(251000, result["host_ms"]["median"])
        self.assertFalse(result["noisy"])

    def test_bimodal_extends_to_six(self):
        result, calls = self.run_with([[295000, 389000, 295000]] * 2)
        self.assertEqual([3, 3], calls)
        self.assertEqual("bimodal", result["host_ms"]["state"])
        self.assertEqual(295000, result["host_ms"]["median"])

    def test_extension_capped_at_reps_max(self):
        # EVAL_CFG reps_max 缺省 9：双峰持续则 3+3+3 后停止
        result, calls = self.run_with([[295000, 389000, 295000]] * 4)
        self.assertEqual([3, 3, 3], calls)
        self.assertEqual(len(result["reps"]), 9)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python3 -m unittest discover -s tes/grhsim-am-coremark/tests -v
```

预期：`AttributeError: ... cluster_reps` 等失败。

- [ ] **Step 3: 实现聚簇与裁决（evaluator.py 新增纯函数）**

放在 `_cv` 定义之后：

```python
def cluster_reps(times_ms: list[float], ratio: float) -> list[list[int]]:
    """一维倍率缝隙聚簇：排序后相邻比值 > ratio 处切分；返回按簇中位升序的簇。"""
    order = sorted(range(len(times_ms)), key=lambda i: times_ms[i])
    clusters: list[list[int]] = [[order[0]]]
    for prev, cur in zip(order, order[1:]):
        if times_ms[cur] > times_ms[prev] * ratio:
            clusters.append([])
        clusters[-1].append(cur)
    clusters.sort(key=lambda c: statistics.median(times_ms[i] for i in c))
    return clusters


def adjudicate_reps(times_ms: list[float], ratio: float) -> dict:
    """快簇（首个 ≥2 成员的簇）中位为裁决 median；全 singleton 退化取最快簇。

    state: unimodal（单簇）/ bimodal（多簇且有 ≥2 成员簇）/ degraded（全 singleton）。
    """
    clusters = cluster_reps(times_ms, ratio)
    fast = next((c for c in clusters if len(c) >= 2), None)
    if fast is None:
        state = "degraded"
        fast = clusters[0]
    elif len(clusters) == 1:
        state = "unimodal"
    else:
        state = "bimodal"
    return {"state": state, "clusters": clusters, "fast_cluster": fast,
            "median": statistics.median(times_ms[i] for i in fast),
            "median_all": statistics.median(times_ms)}
```

- [ ] **Step 4: 改 `run_reps` 为簇结构自适应**

将 L171-218 的 while 循环收口逻辑替换为（difftest/timeout/parse_fail 各门保持原样；变化点是循环出口与结果组装）：

```python
    ratio = float(ev.get("cluster_ratio", 1.15))
    reps_max = int(ev.get("reps_max", 9))
    while len(reps) < target_reps:
        batch = _run_rep_batch(...)  # 原有调用不变
        reps.extend(batch)
        # …原有 interference/timeout/difftest/parse 判定全部保留（break 分支不变）…
        if status != "ok":
            break
        times = [r["host_ms"] for r in reps if r["host_ms"] is not None]
        adj = adjudicate_reps(times, ratio)
        # 簇结构自适应：检出分裂且未达上限才加跑；不因 CV 扩增
        if len(adj["clusters"]) > 1 and len(reps) < reps_max:
            target_reps = min(len(reps) + len(cores), reps_max)
            continue
        break
```

结果组装段（替换原 `out.update({...})` 块）：

```python
    times = [r["host_ms"] for r in reps if r["host_ms"] is not None]
    out = {"status": status, "reps": reps}
    if times and all(r.get("difftest_ok") for r in reps):
        adj = adjudicate_reps(times, float(ev.get("cluster_ratio", 1.15)))
        cv = _cv(times)
        out.update({"host_ms": {"reps": times, "median": _median([times[i] for i in adj["fast_cluster"]]),
                                "median_all": _median(times), "cv": round(cv, 4),
                                "clusters": adj["clusters"], "fast_cluster": adj["fast_cluster"],
                                "state": adj["state"]},
                    "noisy": cv > ev["cv_max"] or adj["state"] == "degraded",
                    "score": -_median([times[i] for i in adj["fast_cluster"]])})
```

- [ ] **Step 5: 协变量采样线程（_run_rep_batch 内）**

文件头 import 增加 `threading`。新增：

```python
def _sample_proc_state(pid: int, stop: threading.Event, out: dict) -> None:
    """1Hz 只读采样 rep 进程的 THP/NUMA 状态（与计时纪律兼容的先例：r002 监视模式）。"""
    huge_max = 0
    pages: dict[str, int] = {}
    samples = 0
    while not stop.is_set():
        try:
            rollup = Path(f"/proc/{pid}/smaps_rollup").read_text(encoding="utf-8")
            m = re.search(r"AnonHugePages:\s+(\d+)\s+kB", rollup)
            if m:
                huge_max = max(huge_max, int(m.group(1)))
            numa = Path(f"/proc/{pid}/numa_maps").read_text(encoding="utf-8")
            cur: dict[str, int] = {}
            for n, p in re.findall(r"\bN(\d+)=(\d+)", numa):
                cur[f"N{n}"] = cur.get(f"N{n}", 0) + int(p)
            pages = cur
            samples += 1
        except (OSError, ValueError):
            break  # 进程已退出
        stop.wait(1.0)
    out.update({"anon_hugepages_kb_max": huge_max, "numa_pages": pages, "samples": samples})
```

`_run_rep_batch` 中每 rep popen 后挂守护线程，rep 结束时收尾：

```python
# procs.append(...) 处追加：
pr["proc_state"] = {}
pr["sampler_stop"] = threading.Event()
th = threading.Thread(target=_sample_proc_state,
                      args=(pr["popen"].pid, pr["sampler_stop"], pr["proc_state"]), daemon=True)
th.start()
# 结束分支（pr["rc"] is not None 时）追加：
pr["sampler_stop"].set()
```

返回 out 组装处加 `"proc_state": pr["proc_state"]`。

- [ ] **Step 6: 跑测试确认全部通过**

```bash
python3 -m unittest discover -s tes/grhsim-am-coremark/tests -v
```

预期：7 项全 PASS。

- [ ] **Step 7: 提交**

```bash
git add tes/grhsim-am-coremark/evaluator.py tes/grhsim-am-coremark/tests/test_evaluator.py
git commit -m "tes(r004-overhaul): evaluator 聚簇裁决 + 自适应 rep + rep 协变量"
```

---

### Task 3: evaluator.py `retime` 子命令（spec §1.3）

复用已建 emu 只补计时，覆盖该 eval 的计时段（result.json 保留历史）。

**Files:**
- Modify: `tes/grhsim-am-coremark/evaluator.py`（`main()` L386-429 附近 + 新增 `retime_eval`）
- Test: `tes/grhsim-am-coremark/tests/test_evaluator.py`（追加 TestCase）

**Interfaces:**
- Consumes: `run_reps`（Task 2 新版）、既有 `build/tes/<task>/evals/<eval-id>/result.json`。
- Produces: `evaluator.py retime --eval-id <eNNNNN>`；result.json 追加 `retimes: [{started_at, host_ms, score}]` 列表，并把最新裁决同步到顶层 `host_ms`/`score`（旧值进 `host_ms_superseded`）。

- [ ] **Step 1: 写失败测试**

```python
class RetimeTest(unittest.TestCase):
    def test_retime_appends_and_supersedes(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as td:
            evdir = Path(td) / "e99999"
            (evdir / "emu_build" / "grhsim-compile").mkdir(parents=True)
            (evdir / "emu_build" / "grhsim-compile" / "emu").write_text("#!/bin/sh\n")
            (evdir / "result.json").write_text(json.dumps({
                "eval_id": "e99999", "status": "ok",
                "host_ms": {"median": 389000}, "score": -389000}))
            fake = {"status": "ok", "reps": [],
                    "host_ms": {"median": 295000, "median_all": 295000,
                                "clusters": [[0]], "fast_cluster": [0],
                                "state": "unimodal", "reps": [295000], "cv": 0.0},
                    "score": -295000}
            with mock.patch.object(evaluator, "run_reps", return_value=fake), \
                 mock.patch.object(evaluator, "BUILD_TASK", Path(td)):
                rc = evaluator.retime_eval("e99999")
            self.assertEqual(0, rc)
            saved = json.loads((evdir / "result.json").read_text())
            self.assertEqual(-295000, saved["score"])
            self.assertEqual({"median": 389000}, saved["host_ms_superseded"])
            self.assertEqual(1, len(saved["retimes"]))
```

- [ ] **Step 2: 跑测试确认失败**（`retime_eval` 不存在，AttributeError）

- [ ] **Step 3: 实现**

```python
def retime_eval(eval_id: str) -> int:
    """复用既有 emu 只补计时：result.json 追加 retimes 段并刷新顶层裁决。"""
    evdir = BUILD_TASK / "evals" / eval_id
    rj = evdir / "result.json"
    if not rj.exists():
        print(f"[FAIL] {rj} 不存在", file=sys.stderr)
        return 1
    result = json.loads(rj.read_text(encoding="utf-8"))
    emu_build = evdir / "emu_build"
    if result.get("mode") == "gsim-baseline":
        emu = REPO / result["emu"]
        reps = run_reps(emu.resolve(), evdir / "run", run_cwd=emu.resolve().parent)
    elif (emu_build / "emu").exists():
        reps = run_reps(Path("emu"), evdir / "run", run_cwd=emu_build)
    elif (emu_build / "grhsim-compile" / "emu").exists():
        reps = run_reps(emu_build / "grhsim-compile" / "emu", evdir / "run")
    else:
        print(f"[FAIL] {eval_id} 无可复用 emu（未构建或已清理）", file=sys.stderr)
        return 1
    if reps.get("status") != "ok" or "host_ms" not in reps:
        print(f"[FAIL] retime 未得到有效计时: {reps.get('status')}", file=sys.stderr)
        return 1
    result.setdefault("retimes", []).append({"started_at": now_iso(), "host_ms": reps["host_ms"],
                                             "score": reps.get("score")})
    if "host_ms" in result:
        result["host_ms_superseded"] = result["host_ms"]
    result["host_ms"] = reps["host_ms"]
    result["score"] = reps.get("score")
    rj.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] {eval_id} retime: median {reps['host_ms']['median']} ms"
          f"（state={reps['host_ms']['state']}）")
    return 0
```

`main()` 注册：

```python
    p = sub.add_parser("retime", help="复用既有 emu 重跑计时协议（不重建、不占预算）")
    p.add_argument("--eval-id", required=True)
```

dispatch 处（`if args.cmd == "run"` 分支内）改为：

```python
        if args.cmd == "run":
            ...
        elif args.cmd == "retime":
            return retime_eval(args.eval_id)   # 在 LOCK 内；注意此分支直接返回
        else:
            result = evaluate_gsim(args.eval_id)
```

注意：`retime` 分支在 `with open(lock...)` 块内直接 `return`，不再走末尾写 result.json 的公共路径（retime_eval 自己写）。

- [ ] **Step 4: 跑测试确认通过**

```bash
python3 -m unittest discover -s tes/grhsim-am-coremark/tests -v
```

- [ ] **Step 5: 提交**

```bash
git add tes/grhsim-am-coremark/evaluator.py tes/grhsim-am-coremark/tests/test_evaluator.py
git commit -m "tes(r004-overhaul): evaluator retime 子命令（只补计时、保留历史）"
```

---

### Task 4: numactl 包装（**条件任务**，由 Task 1 冒烟裁决）

冒烟判定 NUMA 绑定有效才做；跳过时在计划勾选框旁注"冒烟证伪，跳过"。

**Files:**
- Modify: `tes/grhsim-am-coremark/evaluator.py`（`_run_rep_batch` 命令构造，L136 附近）
- Modify: `tes/grhsim-am-coremark/config.json`（`eval.numactl_membind`）
- Test: `tes/grhsim-am-coremark/tests/test_evaluator.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 LOCAL_NODE 裁决。
- Produces: config 键 `eval.numactl_membind: null | int`（默认 null = 不包装，旧冻结配置无此键时语义不变）。

- [ ] **Step 1: 写失败测试**

```python
class NumactlWrapTest(unittest.TestCase):
    def test_wrap_prefix_when_configured(self):
        import tempfile
        captured = {}

        class FakePopen:
            def __init__(self, cmd, **kw):
                captured["cmd"] = cmd
                self.pid = 99999
            def poll(self):
                return 0
            def wait(self, timeout=None):
                return 0

        # run_dir 必须真实存在（_run_rep_batch 会打开 rep 日志文件）
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            with mock.patch.object(evaluator.subprocess, "Popen", FakePopen), \
                 mock.patch.object(evaluator, "no_other_emu", return_value=True), \
                 mock.patch.object(evaluator, "parse_run_log",
                                   return_value={"host_ms": 1000, "instrCnt": 73584, "cycleCnt": 49998}), \
                 mock.patch.object(evaluator.threading, "Thread"), \
                 mock.patch.dict(evaluator.EVAL_CFG, {"numactl_membind": 0, "rep_timeout_sec": 60}):
                evaluator._run_rep_batch(Path("/fake/emu"), run_dir, run_dir, 1, 1, ["12"])
        self.assertEqual(["numactl", "--membind=0", "taskset", "-c", "12"],
                         captured["cmd"][:5])
```

（FakePopen 使命令构造可断言；采样线程被 mock 掉。）

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**

`_run_rep_batch` 的 cmd 构造处（原 L136）改为：

```python
        prefix: list[str] = []
        node = ev.get("numactl_membind")
        if node is not None:
            prefix = ["numactl", f"--membind={node}"]
        cmd = [*prefix, "taskset", "-c", str(core), str(emu), ...]
```

config.json `eval` 节追加（值取 Task 1 裁决的 LOCAL_NODE）：

```json
  "numactl_membind": 0,
```

- [ ] **Step 4: 跑测试确认通过** → **Step 5: 提交**

```bash
git add tes/grhsim-am-coremark/evaluator.py tes/grhsim-am-coremark/config.json tes/grhsim-am-coremark/tests/test_evaluator.py
git commit -m "tes(r004-overhaul): rep 启动 numactl membind 包装（冒烟裁决启用）"
```

---

### Task 5: tesctl.py 候选表型审计门（spec §5）

**Files:**
- Modify: `tes/tools/tesctl.py`（`cmd_record_eval` L633-672 + 新增纯函数）
- Test: `tes/tools/tests/test_tesctl.py`（新建）

**Interfaces:**
- Produces:
  - `audit_phenotype(declared: dict, frozen: list[str], actual: list[str] | None) -> str | None`：返回 None=通过，否则为拒绝原因。
  - 候选声明文件约定：候选 worktree 根目录 `tes-candidate.json`，schema
    `{"hypothesis": str, "emit_args_add": list[str], "emit_args_remove": list[str]}`（后两者可缺省=空）。**每个候选都必须提交该文件**（无表型变更时 `{}` 或只含 hypothesis）。
  - record-eval 拒绝语义：文件缺失、声明与实际不符 → 退出码 1，不登记。

- [ ] **Step 1: 写失败测试（新建测试文件）**

```python
#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

TESCTL = Path(__file__).resolve().parents[1] / "tesctl.py"
SPEC = importlib.util.spec_from_file_location("tesctl", TESCTL)
assert SPEC is not None and SPEC.loader is not None
tesctl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tesctl)

FROZEN = ["--branchy-mux", "--scan-branch-hints"]


class AuditPhenotypeTest(unittest.TestCase):
    def test_exact_frozen_passes(self):
        self.assertIsNone(tesctl.audit_phenotype({}, FROZEN, list(FROZEN)))

    def test_declared_add_passes(self):
        self.assertIsNone(tesctl.audit_phenotype(
            {"emit_args_add": ["--my-knob"]}, FROZEN, FROZEN + ["--my-knob"]))

    def test_undeclared_knob_rejected(self):
        err = tesctl.audit_phenotype({}, FROZEN, FROZEN + ["--my-knob"])
        self.assertIsNotNone(err)

    def test_declared_but_not_passed_rejected(self):
        # r003 corr-e00073/74/75/76 的漏传场景
        err = tesctl.audit_phenotype({"emit_args_add": ["--my-knob"]}, FROZEN, list(FROZEN))
        self.assertIsNotNone(err)

    def test_remove_respected(self):
        self.assertIsNone(tesctl.audit_phenotype(
            {"emit_args_remove": ["--scan-branch-hints"]}, FROZEN, ["--branchy-mux"]))

    def test_missing_file_rejected(self):
        self.assertIsNotNone(tesctl.audit_phenotype(None, FROZEN, list(FROZEN)))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
mkdir -p tes/tools/tests
python3 -m unittest discover -s tes/tools/tests -v
```

- [ ] **Step 3: 实现纯函数 + 接线**

tesctl.py 新增（放在 `cmd_record_eval` 之前）：

```python
def audit_phenotype(declared: dict | None, frozen: list[str], actual: list[str] | None) -> str | None:
    """候选表型审计：声明（tes-candidate.json）是意图的唯一来源，实际 emit_args 必须吻合。"""
    if declared is None:
        return "候选缺少 tes-candidate.json（表型声明是硬前置，r003 表型漏传教训）"
    remove = set(declared.get("emit_args_remove") or [])
    expected = [a for a in frozen if a not in remove]
    expected += list(declared.get("emit_args_add") or [])
    if expected != list(actual or []):
        return f"表型不符：声明推导 {expected}，实际 {actual}"
    return None
```

`cmd_record_eval` 在 `result = load_json(...)` 之后、构造 entry 之前插入：

```python
    cand_decl_path = REPO / cand["worktree"] / "tes-candidate.json"
    declared = None
    if cand_decl_path.exists():
        try:
            declared = json.loads(cand_decl_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"[FAIL] {cand_decl_path} 不是合法 JSON: {exc}", file=sys.stderr)
            return 1
    err = audit_phenotype(declared, run["config"]["eval"].get("emit_args", []),
                          result.get("emit_args"))
    if err:
        print(f"[FAIL] 表型审计拒绝登记 {result['eval_id']}: {err}", file=sys.stderr)
        return 1
```

- [ ] **Step 4: 跑测试确认通过**

- [ ] **Step 5: 提交**

```bash
git add tes/tools/tesctl.py tes/tools/tests/test_tesctl.py
git commit -m "tes(r004-overhaul): record-eval 候选表型审计门"
```

---

### Task 6: recon 正式 action + 新鲜度门 + 任务 recon.py（spec §4）

**Files:**
- Modify: `tes/tools/tesctl.py`（`compute_next_action` L255-297、trajectory 初始化 L440-448、新增 `cmd_record_recon`、main 注册）
- Create: `tes/grhsim-am-coremark/recon.py`
- Test: `tes/tools/tests/test_tesctl.py`（追加）

**Interfaces:**
- Produces:
  - `RECON_STALENESS = 2`（tesctl 模块常量）。
  - `recon_due(t: dict) -> bool`：`t.get("last_recon_step") is None or t["steps_completed"] - t["last_recon_step"] >= RECON_STALENESS`。
  - 新 action 类型 `{"type": "recon", "trajectory": tid, "eval_id": <待 profile 的 eval>}`，由 `compute_next_action` 在应出 step 但 recon 到期时返回。
  - `tesctl.py record-recon --trajectory <t> --report <repo 相对路径>`：置 `t["last_recon_step"] = t["steps_completed"]`，ledger 追加 `kind=recon` 条目（**不增 evals 计数**）。
  - trajectory dict 新增字段：`last_recon_step`（init-run 初始化 null）、`tip_eval_id`（finish-step 维护，供 recon 定位既有 emu_build）。
  - `recon.py --eval-id <eNNNNN> --out <dir> [--perf]`：flock + emu 守卫；用既有 emu_build 跑 `EMU_AM_BLOCK_EXECS=<out>/block_execs.txt`，stderr 存 profile.log；解析 `[am-profile]` 段 + block_execs.txt 产出 `report.md`/`report.json`；`--perf` 加 `perf record -F 99 -o <out>/perf.data` 并 `perf report --stdio -i ... > perf.txt`。

- [ ] **Step 1: 写失败测试（追加到 test_tesctl.py）**

```python
class ReconGateTest(unittest.TestCase):
    def test_due_when_never(self):
        self.assertTrue(tesctl.recon_due({"steps_completed": 0}))

    def test_due_after_staleness(self):
        self.assertTrue(tesctl.recon_due({"steps_completed": 3, "last_recon_step": 1}))
        self.assertFalse(tesctl.recon_due({"steps_completed": 2, "last_recon_step": 1}))

    def test_next_returns_recon_before_step(self):
        run = {"status": "active", "run_id": "r004",
               "config": {"search": {"C": 1, "L": 4, "K": 2}},
               "baseline_sides": ["am"], "baselines": {"am": {"eval_id": "e00001"}},
               "trajectories": [{"id": "t0", "branch": "b", "steps_completed": 0,
                                 "tip": "x", "tip_eval_id": "e00001", "best": None}],
               "current_step": None, "round_summaries_done": []}
        na = tesctl.compute_next_action(run)
        self.assertEqual("recon", na["type"])
        self.assertEqual("t0", na["trajectory"])
        self.assertEqual("e00001", na["eval_id"])  # 无 winner 时回退 AM 基线 eval

    def test_step_after_recon(self):
        run = {"status": "active", "run_id": "r004",
               "config": {"search": {"C": 1, "L": 4, "K": 2}},
               "baseline_sides": ["am"], "baselines": {"am": {"eval_id": "e00001"}},
               "trajectories": [{"id": "t0", "branch": "b", "steps_completed": 0,
                                 "last_recon_step": 0, "tip": "x",
                                 "tip_eval_id": "e00001", "best": None}],
               "current_step": None, "round_summaries_done": []}
        self.assertEqual("step", tesctl.compute_next_action(run)["type"])
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: tesctl 实现**

模块常量与纯函数（放 `compute_next_action` 前）：

```python
RECON_STALENESS = 2  # spec §4：距上次 recon ≥2 步即到期


def recon_due(t: dict) -> bool:
    last = t.get("last_recon_step")
    return last is None or t["steps_completed"] - last >= RECON_STALENESS
```

`compute_next_action` 中 `t = min(trajs, ...)` 选定轨迹后、`return {"type": "step"...}` 之前插入：

```python
    if recon_due(t):
        eval_id = t.get("tip_eval_id") or (run["baselines"].get("am") or {}).get("eval_id")
        return {"type": "recon", "trajectory": t["id"], "eval_id": eval_id,
                "reason": f"轨迹 {t['id']} recon 证据到期（staleness≥{RECON_STALENESS}），"
                          f"先对 tip（eval {eval_id}）做非计时 profiling 再出 step"}
```

`cmd_finish_step` 的 winner 合入块追加一行 `t["tip_eval_id"] = winner["eval_id"]`。

`cmd_init_run` 的 trajectories.append 处字典加 `"last_recon_step": None, "tip_eval_id": None`。

新增命令：

```python
def cmd_record_recon(args) -> int:
    run = load_run()
    if run is None or run["status"] != "active":
        print("[FAIL] 无活跃 run", file=sys.stderr)
        return 1
    t = next((x for x in run["trajectories"] if x["id"] == args.trajectory), None)
    if t is None:
        print(f"[FAIL] 未知轨迹 {args.trajectory}", file=sys.stderr)
        return 1
    t["last_recon_step"] = t["steps_completed"]
    append_ledger({"kind": "recon", "run": run["run_id"], "trajectory": args.trajectory,
                   "step": t["steps_completed"], "eval_id": args.eval_id,
                   "report": args.report, "ts": now_iso()})
    save_run(run)
    print(f"[OK] recon 已登记: {args.trajectory} @ step {t['steps_completed']}（不占 eval 预算）")
    _refresh_dashboard()
    return 0
```

main() 注册：

```python
    p = sub.add_parser("record-recon")
    p.add_argument("--trajectory", required=True)
    p.add_argument("--eval-id", required=True, help="被 profile 的 eval（tip winner 或 AM 基线）")
    p.add_argument("--report", required=True, help="recon 报告的 repo 相对路径")
```

dispatch 字典加 `"record-recon": cmd_record_recon`。

- [ ] **Step 4: 写 recon.py**

```python
#!/usr/bin/env python3
"""recon — 对轨迹 tip 的生产 emu 做非计时 profiling（不占 eval 预算）。

用法: recon.py --eval-id e00057 --out build/tes/<task>/recon/r004-t0-s00 [--perf]
复用 <eval-id> 的既有 emu_build，跑 EMU_AM_BLOCK_EXECS 全量块执行计数 +
[am-profile] stderr 段（eval/compute/commit 时间分解、top-32 块），产出
report.md / report.json。持 build/tes/LOCK + 起跑前无其他 emu（同 evaluator 纪律）。
"""
```

实现要点（照此结构写全）：

```python
# emu 定位顺序：evdir/emu_build/emu → evdir/emu_build/grhsim-compile/emu
# 运行（taskset 绑 config eval.core，cwd=emu_build，与 evaluator 计时同环境）：
#   env EMU_AM_BLOCK_EXECS=<out>/block_execs.txt
#   [<emu>, -i <coremark_bin>, --diff <nemu_so>, -b 0 -e 0 -C <cycles>]
# stderr → <out>/profile.log；解析：
#   [am-profile] time ms: eval X, compute Y (Z%), commit W (V%) → report.json["phases"]
#   block_execs.txt 行格式 "<block> <c|w> <execs> <cycles>" → top 50 按 cycles 排序
# report.md = 阶段分解表 + top-50 块表（block/kind/execs/cycles/cycles%）
# --perf：cmd = ["perf", "record", "-F", "99", "-o", str(out/"perf.data"), *cmd]，
#   结束后 perf report --stdio -i perf.data > perf.txt
```

- [ ] **Step 5: 测试 + 冒烟 recon.py**

```bash
python3 -m unittest discover -s tes/tools/tests -v
# recon.py 对 r003 winner e00057 的既有 emu_build 实跑一次（emu 还在的话）：
python3 tes/grhsim-am-coremark/recon.py --eval-id e00057 \
  --out build/tes/grhsim-am-coremark/recon/smoke-r003-t0
cat build/tes/grhsim-am-coremark/recon/smoke-r003-t0/report.md | head -30
```

预期：report.md 含 `[am-profile]` 阶段分解与 top 块表；若 e00057 的 emu_build 已被清理，改对一个现存 eval 目录冒烟（`ls build/tes/grhsim-am-coremark/evals/` 任选），仅为验证脚本可用。

- [ ] **Step 6: 提交**

```bash
git add tes/tools/tesctl.py tes/tools/tests/test_tesctl.py tes/grhsim-am-coremark/recon.py
git commit -m "tes(r004-overhaul): recon 正式 action + 新鲜度门 + 任务 recon.py"
```

---

### Task 7: winner outcome 分类 + 迁移席位（spec §2.3、§3）

**Files:**
- Modify: `tes/tools/tesctl.py`（`cmd_finish_step` L675-716、`cmd_record_eval`、main 注册）
- Test: `tes/tools/tests/test_tesctl.py`（追加）

**Interfaces:**
- Produces:
  - `classify_outcome(winner_score: float, parent_score: float | None, noise: float) -> str`：parent 为 None → `"initial"`；`(winner - parent) / abs(parent) > noise` → `"win"`；`< -noise` → `"loss"`；否则 `"neutral"`（score 越高越好，noise 取 config `eval.adjudicate_noise`，默认 0.03）。
  - commit-marker 条目新增字段：`outcome`、`parent_eval_id`。
  - 轨迹 best 只在 `outcome == "win"` 时更新（neutral/loss 合入主线但不刷新 best）。
  - `record-eval --migration-source <eval-id>` + `validate_migration(step, already_has) -> str | None`：step < 2 → 拒绝（round 1 纯独立）；本 step 已有迁移候选 → 拒绝第二席。ledger 候选条目存 `migration_source`。

- [ ] **Step 1: 写失败测试**

```python
class OutcomeClassifyTest(unittest.TestCase):
    def test_initial_when_no_parent(self):
        self.assertEqual("initial", tesctl.classify_outcome(-100.0, None, 0.03))

    def test_win_neutral_loss(self):
        self.assertEqual("win", tesctl.classify_outcome(-100.0, -110.0, 0.03))     # +9.1%
        self.assertEqual("neutral", tesctl.classify_outcome(-100.0, -101.0, 0.03)) # +1%
        self.assertEqual("loss", tesctl.classify_outcome(-110.0, -100.0, 0.03))


class MigrationSeatTest(unittest.TestCase):
    def test_round1_rejected(self):
        self.assertIsNotNone(tesctl.validate_migration(1, False))

    def test_round2_first_seat_ok(self):
        self.assertIsNone(tesctl.validate_migration(2, False))

    def test_second_seat_rejected(self):
        self.assertIsNotNone(tesctl.validate_migration(3, True))
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**

```python
def classify_outcome(winner_score: float, parent_score: float | None, noise: float) -> str:
    """winner 相对父 tip 的裁决分类（score 越高越好；|Δ| 落入噪声带为 neutral）。"""
    if parent_score is None:
        return "initial"
    delta = (winner_score - parent_score) / abs(parent_score)
    if delta > noise:
        return "win"
    if delta < -noise:
        return "loss"
    return "neutral"


def validate_migration(step: int, already_has_migration: bool) -> str | None:
    """迁移席位：round 1 保持纯独立探索（spec §3）；每 step 至多 1 席。"""
    if step < 2:
        return "round 1 为纯独立探索，迁移候选从 step 2 起开放"
    if already_has_migration:
        return "本 step 已有 1 席迁移候选，其余席位须为本轨迹邻域机制"
    return None
```

`cmd_finish_step` winner 块改造（替换原 winner 处理段）：

```python
    winner = None
    if ok:
        winner = max(ok, key=lambda e: e["score"])
        noise = float(run["config"]["eval"].get("adjudicate_noise", 0.03))
        parent_eval = t.get("tip_eval_id")
        parent = None
        if parent_eval:
            parent = next((e for e in iter_ledger()
                           if e.get("run") == run["run_id"] and e.get("eval_id") == parent_eval
                           and e.get("kind") != "commit-marker"), None)
        outcome = classify_outcome(winner["score"], parent.get("score") if parent else None, noise)
        git_target("branch", "-f", t["branch"], winner["branch"])
        t["tip"] = winner["commit"]
        t["tip_eval_id"] = winner["eval_id"]
        # best 只在真实进步时更新（initial=轨迹首个 winner，父为 AM 基线）；neutral/loss 不刷 best
        if outcome in ("win", "initial") and (t.get("best") is None or winner["score"] > t["best"]["score"]):
            t["best"] = {"eval_id": winner["eval_id"], "score": winner["score"]}
        _mark_committed(run["run_id"], tid, cs["step"], winner["eval_id"],
                        outcome=outcome, parent_eval_id=parent_eval)
        print(f"  outcome={outcome}（noise 带 ±{noise:.0%}，父 {parent_eval}）")
```

`_mark_committed` 签名扩展：

```python
def _mark_committed(run_id: str, tid: str, step: int, eval_id: str,
                    outcome: str, parent_eval_id: str | None) -> None:
    append_ledger({"kind": "commit-marker", "run": run_id, "trajectory": tid,
                   "step": step, "eval_id": eval_id, "committed": True,
                   "outcome": outcome, "parent_eval_id": parent_eval_id, "ts": now_iso()})
```

注意 best 的初始建立：轨迹首个 winner 的 tip_eval_id 初始为 None → parent None → outcome=initial，上面代码已把 `initial` 与 `win` 一并纳入 best 更新条件。

`cmd_record_eval` 增加参数与校验（接在 Task 5 表型审计之后）：

```python
# main() 注册：p = sub.add_parser("record-eval"); p.add_argument("--migration-source")
# cmd_record_eval 内：
    already = any(e.get("kind") == "candidate" and e.get("migration_source")
                  for e in iter_ledger()
                  if e.get("run") == run["run_id"] and e.get("trajectory") == cs["trajectory"]
                  and e.get("step") == cs["step"])
    err = validate_migration(cs["step"], already) if args.migration_source else None
    if err:
        print(f"[FAIL] 迁移席位校验: {err}", file=sys.stderr)
        return 1
# entry 构造追加字段："migration_source": args.migration_source,
```

- [ ] **Step 4: 跑测试确认通过**

- [ ] **Step 5: 提交**

```bash
git add tes/tools/tesctl.py tes/tools/tests/test_tesctl.py
git commit -m "tes(r004-overhaul): winner outcome 分类 + 迁移席位（round≥2，每步1席）"
```

---

### Task 8: phi.py neutral 降权 + proposal recon 段（spec §2.4、§4）

**Files:**
- Modify: `tes/tools/phi.py`（`trajectory_nodes` L48-77、`rpucg_select` L80-99、proposal 模板 L229-236）
- Test: `tes/tools/tests/test_phi.py`（新建）

**Interfaces:**
- Consumes: Task 7 的 commit-marker `outcome` 字段；Task 6 的 ledger `kind=recon` 条目。
- Produces:
  - `trajectory_nodes` 返回值由 `(S, rejected, failed)` 改为 `(S, rejected, failed, outcomes)`，outcomes = `{eval_id: outcome}`；`main()` 相应解包。
  - neutral 节点在 `rpucg_select` 的 min-max 归一化中以其**前驱已提交节点的原始 score** 参与（历史地位 = 父节点，不再制造人工峰值）；debug 表仍显示原始 score。
  - proposal 新增「本轨迹 recon 证据」段：列出 ledger 中本轨迹最新 `kind=recon` 条目的 report 路径 + 硬要求句。

- [ ] **Step 1: 写失败测试（新建 test_phi.py）**

```python
#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

PHI = Path(__file__).resolve().parents[1] / "phi.py"
SPEC = importlib.util.spec_from_file_location("phi", PHI)
assert SPEC is not None and SPEC.loader is not None
phi = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(phi)


def entry(eval_id, step, score, committed=True, outcome="win", parents=None):
    return {"kind": "candidate", "run": "r004", "trajectory": "t0", "step": step,
            "candidate": 1, "eval_id": eval_id, "status": "ok", "score": score,
            "committed": committed, "proposal_nodes": parents or []}


class NeutralDownweightTest(unittest.TestCase):
    def test_neutral_uses_parent_score_in_norm(self):
        with tempfile.TemporaryDirectory() as td:
            task = Path(td)
            (task / "state").mkdir()
            lines = [
                {"kind": "baseline-am", "run": "r004", "eval_id": "e00001", "score": -364.0},
                entry("e00002", 1, -229.0),
                {"kind": "commit-marker", "run": "r004", "trajectory": "t0", "step": 1,
                 "eval_id": "e00002", "committed": True, "outcome": "win"},
                # e00003 名义分略高于父（噪声漂移），outcome=neutral
                entry("e00003", 2, -226.0, parents=["e00002"]),
                {"kind": "commit-marker", "run": "r004", "trajectory": "t0", "step": 2,
                 "eval_id": "e00003", "committed": True, "outcome": "neutral"},
                entry("e00004", 3, -220.0, parents=["e00003"]),
                {"kind": "commit-marker", "run": "r004", "trajectory": "t0", "step": 3,
                 "eval_id": "e00004", "committed": True, "outcome": "win"},
            ]
            (task / "state" / "ledger.jsonl").write_text(
                "\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
            phi.TASK_DIR = task
            S, _rej, _fail, outcomes = phi.trajectory_nodes("r004", "t0")
            self.assertEqual({"e00002": "win", "e00003": "neutral", "e00004": "win"}, outcomes)
            eff = phi.effective_scores(S, outcomes)
            # e00003 的归一化输入 = 前驱 e00002 的 -229，而非名义 -226
            self.assertEqual(-229.0, eff["e00003"])
            self.assertEqual(-220.0, eff["e00004"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python3 -m unittest discover -s tes/tools/tests -v
```

- [ ] **Step 3: 实现**

`trajectory_nodes` 修改：commit-marker 循环记录 outcomes，返回值加第四元：

```python
    outcomes: dict[str, str] = {}
    for e in iter_ledger():
        if e.get("run") != run_id:
            continue
        if e.get("kind") == "commit-marker":
            if e.get("trajectory") == tid:
                committed_ids.add(e["eval_id"])
                if e.get("outcome"):
                    outcomes[e["eval_id"]] = e["outcome"]
            continue
        entries.append(e)
    # …原 S/rejected/failed 构造不变…
    return S, rejected, failed, outcomes
```

新增纯函数（放 `rpucg_select` 前）：

```python
def effective_scores(S: list[dict], outcomes: dict[str, str]) -> dict[str, float]:
    """归一化输入分：neutral 节点取前驱已提交节点的原始分（历史地位=父，防 artifact 峰值）。"""
    chain = sorted((e for e in S if e.get("kind") == "candidate"),
                   key=lambda e: (e.get("step") or 0, e["eval_id"]))
    eff: dict[str, float] = {}
    prev: dict | None = None
    for e in chain:
        if outcomes.get(e["eval_id"]) == "neutral" and prev is not None:
            eff[e["eval_id"]] = eff.get(prev["eval_id"], prev["score"])
        else:
            eff[e["eval_id"]] = e["score"]
        prev = e
    for e in S:
        eff.setdefault(e["eval_id"], e["score"])  # root baseline 等
    return eff
```

`rpucg_select` 签名改为 `rpucg_select(S, counts, gamma, lam, max_nodes, eff_scores=None)`，归一化段：

```python
    scores_map = eff_scores or {e["eval_id"]: e["score"] for e in S}
    scores = list(scores_map.values())
    lo, hi = min(scores), max(scores)
    norm = {nid: (1.0 if hi == lo else (s - lo) / (hi - lo)) for nid, s in scores_map.items()}
```

`rho` 的名次分位同样改用 `scores_map`（替换原 `order = sorted(S, key=...)` 段）：

```python
    order = sorted(scores_map, key=lambda nid: scores_map[nid])
    rho = {}
    n = len(order)
    for i, nid in enumerate(order):
        rho[nid] = 1.0 if n == 1 else i / (n - 1)
```

`main()` 解包改四元（`S, rejected, failed, outcomes = trajectory_nodes(...)`），rpucg 调用处传 `eff_scores=effective_scores(S, outcomes)`。

proposal 模板在「## 本 step 任务」前插入 recon 段：

```python
    recon_reports = [e for e in iter_ledger()
                     if e.get("run") == run_id and e.get("kind") == "recon"
                     and e.get("trajectory") == tid]
    lines.append("\n## 本轨迹 recon 证据（动态病灶数据）\n")
    if recon_reports:
        latest = recon_reports[-1]
        lines.append(f"- 最新 recon: `{latest.get('report')}`（基于 eval {latest.get('eval_id')}）")
        lines.append("- **硬要求**：每个候选的病灶证据必须引用 recon 报告中的动态权重"
                     "（块 execs/cycles 分布）；静态计数只作辅证。无新鲜 recon 的假设不得占用席位。")
    else:
        lines.append("-（尚无 recon 报告；状态机应先出 recon action，若先见到本 proposal 说明流程有误）")
```

- [ ] **Step 4: 跑测试确认通过**

- [ ] **Step 5: 提交**

```bash
git add tes/tools/phi.py tes/tools/tests/test_phi.py
git commit -m "tes(r004-overhaul): phi neutral 降权 + proposal recon 证据段"
```

---

### Task 9: dashboard 簇列 + 工具链全量回归（spec §6 看板部分）

**Files:**
- Modify: `tes/tools/tesctl.py`（`_render_task_section` 评估表 L836-849）

**Interfaces:**
- Consumes: ledger 候选条目 `host_ms.state`（Task 2 起写入）。
- Produces: 评估表新增「簇」列，显示 `unimodal`/`bimodal`/`degraded`（旧条目无该键显示 `-`）。

- [ ] **Step 1: 修改表头与行渲染**

表头行改：

```python
        lines.append("| eval | 类别 | 位置 | Host 中位 | vs target | 簇 | 状态 | 假设 |")
        lines.append("|---|---|---|---|---|---|---|---|")
```

行渲染在 `status` 列前插入：

```python
            cluster_state = (e.get("host_ms") or {}).get("state") or "-"
            lines.append(f"| {e['eval_id']} | {e.get('kind', '-')} | {pos} | {_fmt_s(ms)} | "
                         f"{_fmt_ratio(ms, target_ms)} | {cluster_state} | {e.get('status', '-')} | {hyp} |")
```

（`median` 已是 Task 2 的裁决值，Host 中位列语义自动升级为快簇中位，无需再改。）

- [ ] **Step 2: 全量回归 + 看板实跑**

```bash
python3 -m unittest discover -s tes/grhsim-am-coremark/tests -v
python3 -m unittest discover -s tes/tools/tests -v
python3 tes/tools/tesctl.py dashboard && git diff --stat tes/dashboard.md
```

预期：两套测试全 PASS；dashboard 生成不报错（r003 旧数据簇列显示 `-`）。dashboard.md 的 diff 是生成物正常变化，提交与否由下步统一处理。

- [ ] **Step 3: 提交**

```bash
git add tes/tools/tesctl.py tes/dashboard.md
git commit -m "tes(r004-overhaul): dashboard 评估表增加簇状态列"
```

---

### Task 10: config + 文档同步（spec §2.1、§3、§6）

**Files:**
- Modify: `tes/grhsim-am-coremark/config.json`
- Modify: `tes/grhsim-am-coremark/protocol.md`、`tes/RULES.md`、`tes/DESIGN.md`、`tes/playbook.md`、`tes/grhsim-am-coremark/playbook.md`
- Modify: `tes/grhsim-am-coremark/state/insights.md`（追加协议升级落地条目）

- [ ] **Step 1: config.json 修改**

- `search`：`"C": 6, "L": 4, "K": 2`，note 改为「r004 起 C=6/L=4/K=2（N=48）：论文 Fig.2 L 饱和 → 预算从 L 挪到 C；K 两席全为机制候选，测量校准走协议动作」。
- `eval` 追加：`"reps_max": 9, "cluster_ratio": 1.15, "adjudicate_noise": 0.03`，note 补「计时协议 r004 起为簇结构自适应：双峰检出才加跑至 ≤9 rep，score=快簇中位；rep 协变量 1Hz 只读采样」。若 Task 4 启用则另有 `numactl_membind`（已在 Task 4 加）。
- `restart`：`"max": 3`；`prepared_solution` 整体替换为：

```json
  "prepared_solution": {
   "source_run": "r003",
   "source_eval": "e00057",
   "commit": "1563c3d837fcfe9db28fc36901531a70b59fd790",
   "emit_args": ["--branchy-mux", "--resize-elision", "--init-zero-elision",
    "--source-part-activity-guard", "--source-word-activity-guard",
    "--wide-storage-first-touch", "--concat-insert-inline", "--inline-scalar-helpers",
    "--concat-insert-unroll", "--wide-detect-fast-path",
    "--sys-task-body-outline", "--scan-branch-hints"],
   "note": "r004 y0 = r003/e00057（t0 best 229.429s）；emit_args 以 e00057 result.json 实测为准，本表经 resolve_base_eval 一致性断言"
  }
```

改前先核对：`python3 -c "import json; print(json.load(open('build/tes/grhsim-am-coremark/evals/e00057/result.json'))['emit_args'])"`——若与本表不符，以 result.json 为准改本表（resolve_base_eval 会对 prepared_solution 与台账/结果文件做一致性断言）。

- [ ] **Step 2: protocol.md 改写计时段**

「计时」条替换为：

```markdown
- 计时：簇结构自适应协议（r004 起）。先 3 rep（每 rep `taskset` 绑独立物理核、单批并行）；
  检出双峰（相邻倍率 > 1.15）自动加跑至 ≤9 rep；**score = 快簇中位**，弃用跨簇 median。
  每 rep 1Hz 只读采样 smaps_rollup/numa_maps 协变量。CV>5% 或 degraded（全 singleton）
  标 `noisy`。评估之间严格串行（全局 LOCK + emu 进程守卫），不开 emu 内插桩。
  整批慢态嫌疑时用 `evaluator.py retime --eval-id` 只补计时（不占预算）。
```

「可调旋钮」段前补一句表型声明要求：候选必须随 commit 提交 `tes-candidate.json`（见任务 playbook）。

- [ ] **Step 3: RULES.md 修改**

- §1 测量纪律：「固定 3 rep」改为簇自适应口径（与 protocol.md 一致）；补协变量采样与 retime 条款。
- §4 增三条：
  - 「迁移席位：step 2 起每 step 至多 1 席可引用他轨迹已确认机制（假设写明来源 eval，record-eval --migration-source 登记）；round 1 保持纯独立。」
  - 「recon 是正式协议 action，不占 eval 预算；轨迹距上次 recon ≥2 步时状态机先出 recon。」
  - 「候选必须随附 tes-candidate.json 表型声明，record-eval 硬审计；原样重测/安慰剂不占候选席位的规则不变。」

- [ ] **Step 4: DESIGN.md 修改**

- §3 串行等价论证补：「轨迹独立限于 round 1 与 Φ proposal 构造；round≥2 的迁移席位是显式、可审计的跨轨迹通道（r002 实践证明其为最高产通道之一，RULES §4 修订）。」
- §6 Φ 补：neutral 节点归一化降权（以前驱分参与）。
- §7 默认参数改 C=6 L=4 K=2 N=48，理由句替换为「r001-r003 证据：L 方向收益集中于前 2 步（论文 Fig.2 L 饱和复现），预算从 L 挪到 C；单评估 ~40min 仍约束 K=2」。

- [ ] **Step 5: playbook 修改**

tes/playbook.md：
- step 节第 3 步补：「每个候选 commit 必须随附 worktree 根 `tes-candidate.json`（`{"hypothesis","emit_args_add","emit_args_remove"}`，无表型变更也要 `{}`）；record-eval 审计不符拒登记。」
- step 节第 4d 步补 `--migration-source` 用法（step≥2 且引用他轨迹机制时）。
- round-summary 节补：「round 2 的 round-summary 先对两个基线 eval 各做一次
  `python3 tes/grhsim-am-coremark/evaluator.py retime --eval-id <基线 eval>`
  （中段重锚，spec §1.4；不占预算、不耗新 eval-id、复用既有 emu），新旧裁决对照写进
  小结；快带水位漂移 >3% 时追加 insights 并重估 vs target 口径。」
- 新增 recon 节：

```markdown
## recon

对应 `next` = `recon`（轨迹 recon 证据到期时先于 step 出）。不占评估预算。

1. `python3 tes/<task>/recon.py --eval-id <action 给出的 eval> --out build/tes/<task>/recon/<run>-<t>-sNN`
   （对 tip winner 或 AM 基线的既有 emu_build 做非计时 profiling；`--perf` 可选加 perf record）。
2. 读 report.md 提炼动态热点，写 action 笔记。
3. `python3 tes/tools/tesctl.py record-recon --trajectory <t> --eval-id <eval> --report <report.md 路径>`，按 goal.md 收口。
```

tes/grhsim-am-coremark/playbook.md：
- 「候选实施纪律」节补 tes-candidate.json schema 与示例；「结果解读速查」补 `host_ms.state`/`median_all` 字段说明与 retime 用法。

- [ ] **Step 6: insights.md 追加 + 提交**

追加条目：协议升级落地清单（聚簇裁决/自适应 rep/协变量/retime/表型审计/recon 门/迁移席位/安慰剂退役）、r002 悬置项（rep 簇分组、基线重锚）关闭声明、冒烟结论回链 Task 1。

```bash
git add tes/grhsim-am-coremark/config.json tes/grhsim-am-coremark/protocol.md \
  tes/RULES.md tes/DESIGN.md tes/playbook.md tes/grhsim-am-coremark/playbook.md \
  tes/grhsim-am-coremark/state/insights.md
git commit -m "tes(r004-overhaul): 协议与文档同步（C=6/L=4/K=2、迁移席位、recon 门、表型审计）"
```

---

### Task 11: r004 run-init（基线重锚，spec §1.4、§2.1）

操作任务：开 r004 并用新协议重测双基线。**此任务在 wolvrix 建分支（tes/r004/*），属已批准的方案内容。**

**Files:**
- 无代码改动；产物为 `tes/grhsim-am-coremark/runs/r004/manifest.json`、run.json 状态、ledger 基线条目、insights 条目。

**Interfaces:**
- Consumes: Task 2 的新计时协议、Task 10 的 config。
- Produces: 活跃 run r004（C=6 L=4 K=2）；双基线（新协议，含簇状态）；run.json 供后续 goal 驱动。

- [ ] **Step 1: 前置核验**

```bash
python3 tes/tools/tesctl.py next   # 预期 run-closed（r003 已收口）
git -C wolvrix cat-file -t 1563c3d837fcfe9db28fc36901531a70b59fd790   # y0 commit 存在
```

- [ ] **Step 2: init-run**

```bash
python3 tes/tools/tesctl.py init-run --base-eval r003/e00057 --C 6 --L 4 --K 2
```

预期输出：6 条轨迹分支（tes/r004/t0..t5/main）+ base 分支建立，基线 eval 预留号打印。

- [ ] **Step 3: 输入指纹回填**（playbook run-init 第 2 步）

```bash
sha256sum build/xs/grhsim-am/wolvrix_xs_post_stats.json
# 值回填 manifest.json 与 run.json 的 pins.inputs[].sha256（唯一允许手改 run.json 的场景）
```

- [ ] **Step 4: AM y0 基线测量（新协议，冷 ccache 放宽编译预算一次）**

```bash
git -C wolvrix worktree add "$PWD/build/tes/grhsim-am-coremark/src/base-r004" tes/r004/base
cd build/tes/grhsim-am-coremark/src/base-r004 && for m in external/slang external/mt-kahypar external/libfst; do
  git submodule update --init --reference "$OLDPWD/wolvrix/$m" -- "$m"
done && cd "$OLDPWD"
python3 tes/grhsim-am-coremark/evaluator.py run \
  --worktree build/tes/grhsim-am-coremark/src/base-r004 \
  --eval-id <run.json 为 am 预留的 eval-id> --compile-budget-sec 5400
python3 tes/tools/tesctl.py record-baseline --side am --result build/tes/grhsim-am-coremark/evals/<eval-id>/result.json \
  --insight "r004 y0=r003/e00057 重锚（新聚簇协议）"
```

- [ ] **Step 5: gsim 基线测量**

```bash
python3 tes/grhsim-am-coremark/evaluator.py gsim --eval-id <为 gsim 预留的 eval-id>
python3 tes/tools/tesctl.py record-baseline --side gsim --result .../result.json --insight "r004 gsim 重锚"
```

- [ ] **Step 6: 核验 + insights + 提交**

检查两个 result.json 的 `host_ms.state`：若为 bimodal，确认快簇中位水位与 r003 同机制读数可比；若 degraded/slow_only 嫌疑，用 `retime` 补测后再登记。insights.md 追加 r004 起点判断（双基线、簇状态、vs r003 口径对照）。

```bash
git add tes/grhsim-am-coremark/state/insights.md
git commit -m "tes(grhsim-am-coremark/r004): run-init 与双基线重锚"
```

（本条按 tes 惯例带 run 前缀；r004 manifest/run.json 由 tesctl 写，其状态推进在下一 goal 的 action 中继续。）

- [ ] **Step 7: 向用户汇报**

汇报：修复落地清单、双基线数值与簇状态、下一个 action（预期 6 条轨迹的 recon）、停止规则重申（r004 前 2 轮零确认收益即停）。

---

## Self-Review 记录

- **Spec 覆盖**：§1.1→Task 1；§1.2→Task 2；§1.3→Task 3（`slow_only` 自动标记简化为 state=bimodal/unimodal/degraded + retime 补测——候选无稳定快带参照，自动判定不可行，此为实现层简化，已在此声明）；§1.4→Task 11 Step 4-5（run-init 重锚）+ Task 10 Step 5 的 round-summary retime 条款（round 2 中段重锚，复用 Task 3 的 retime，不需新 eval-id）；§2.1→Task 10 Step 1 + Task 11；§2.2→Task 10 Step 3（安慰剂退役为纪律条款，无代码）；§2.3→Task 7；§2.4→Task 8；§3→Task 7 + Task 10 Step 3/4；§4→Task 6 + Task 8 recon 段 + Task 10 Step 5；§5→Task 5 + Task 10 Step 5；§6→Task 9/10。
- **类型一致性**：`cluster_reps`/`adjudicate_reps`/`audit_phenotype`/`classify_outcome`/`validate_migration`/`recon_due`/`effective_scores` 签名在定义处与使用处一致；`trajectory_nodes` 四元返回的解包点仅 phi.py main 一处。
- **遗留说明**：Task 4 经 Task 1 冒烟证伪（numactl 对两 emu 均无实质影响，双态当日未复现），已跳过；ledger 旧条目无 `outcome`/`state` 字段，phi/dashboard 均已按 `.get` 缺省处理。
- **实施期修正**：① recon.py 不能复用生产 emu 做块级 profiling（`--runtime-profile` 是编译期 emit 旋钮，default off）——默认模式改为用该 eval 的 wbuild 同 commit lower-json 以「生产 emit_args + --runtime-profile」重 emit 并构建 recon emu，`--perf` 模式才直用生产 emu_build；② 自适应 rep 在双峰持续时直达 reps_max（同一放置抽签不会自愈，加跑只是多取证）；③ Task 6/7 的 tesctl 侧合并为一个提交。
