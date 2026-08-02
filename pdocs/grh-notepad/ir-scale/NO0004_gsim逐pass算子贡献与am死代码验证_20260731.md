# 19 GSim 逐 Pass 算子贡献量化与 AM 死代码交叉验证（2026-07-31）

[`18-am多出op的归因与验证计划`](18-am多出op的归因与验证计划.md) §4 任务 T1
的执行记录。三条结论先行：

1. **gsim 削 logic 的主力是死代码消除 + 常量分析，不是 commonExpr**——
   doc 18 的判据（"commonExpr 单 pass ≈1M"）被数据修正：commonExpr 只
   删 13.7 万 logic（占 11%），首轮 DCE 删 70.0 万（58%）、常量分析删
   38.6 万（32%）。
2. **AM 图里实测躺着 72.9 万条死指令（15.6%），其中 48.7 万是 logic
   op**；gsim 打平图死节点=2。AM 缺 DCE 从推测变成实锤。
3. **AM 的 logic 总量 ≈ gsim 未优化（Init）水平**（2.28M vs 2.13M，
   1.07x）；gsim 靠优化流水把它砍到 0.92M。H1（优化流水差异）成立，
   但分解要改写。

## 1. 方法

- 运行：`gsim --supernode-max-size=15 --dump-stats-json
  --stop-after-stage=graphPartition --dir <dump> build/xs/rtl/rtl/SimTop.fir`
  （生产参数，不加打平；总耗时约 21 min）。
- 落盘：18 个阶段边界各一份 `SimTop_<idx><Stage>_Stats.json`（归档于
  `exp/dataset/gsim_pass_stats_20260731/`，含 PreCoarsen 等 3 份额外
  dump）。
- 口径：`expnodes.op_types` = 全图**唯一非 ref enode** 按 op 计数
  （hash-cons 后共享 enode 只数一次；ref 单列 `node_ref_count`；
  `OP_INT` 计入 const）。逐阶段差即该 pass 的净效果。
- 分析脚本：`exp/tools/gsim_stage_op_delta.py`；结果存档
  `exp/dataset/gsim_stage_op_delta_20260731.json`。

## 2. 全流程收缩总表

节点数（生产 stderr 日志）与 op enode 数（stage dump）：

| 阶段 | 节点数 | op enode 总数 | 其中 logic | 其中 mux | 其中 const |
|---|---:|---:|---:|---:|---:|
| Init（AST2Graph） | 7,826,232 | 16,338,297 | 2,133,535 | 2,385,372 | 2,590,017 |
| SplitArray 后 | 7,826,232 | 10,459,218 | 2,133,535 | 2,385,437 | 2,592,840 |
| TopoSort 后 | 9,631,690 | 10,503,246 | 2,134,360 | 2,515,970 | 2,579,885 |
| **5 RemoveDeadNodes** | 6,012,371 | 7,359,500 | **1,434,757** | 1,402,952 | 1,680,318 |
| 6 ExprOpt | 6,012,371 | 7,323,705 | 1,434,757 | 1,398,123 | 1,676,016 |
| 8 SplitNodes | 6,035,209 | 6,978,808 | 1,472,576 | 1,399,346 | 1,676,519 |
| 10 RemoveDeadNodes1 | 5,913,722 | 6,872,727 | 1,457,165 | 1,391,383 | 1,655,805 |
| **11 ConstantAnalysis** | 5,016,699 | 5,826,535 | **1,070,737** | 1,268,277 | 1,307,467 |
| 12 RemoveDeadNodes | 4,869,990 | 5,683,217 | 1,061,089 | 1,256,716 | 1,271,135 |
| **13 AliasAnalysis** | **3,135,233** | 5,683,217 | 1,061,089 | 1,256,716 | 1,271,135 |
| 14 PatternDetect | 3,131,587 | 5,725,214 | 1,061,089 | 1,256,716 | 1,296,702 |
| **15 CommonExpr** | 2,731,641 | 5,064,634 | **924,446** | 1,234,682 | 1,148,180 |
| 16 RemoveDeadNodes | 2,708,079 | 5,018,957 | **917,837** | 1,230,877 | 1,137,896 |
| 17 graphPartition | 2,708,079 | 5,018,957 | 917,837 | 1,230,877 | 1,137,896 |

节点 9.63M → 2.71M（−72%）；op enode（SplitArray 后口径）10.46M →
5.02M（−52%）。对照：AM 从 post-stats 的 graph_operations 5,158,238 到
am_instructions 4,669,495 只 −9.5%（lower-json 日志），且 AM 流水线
里没有 DCE / 常量分析 / CSE pass（doc 18 §3 H1 的流水线清单）。

graphPartition 入口的 logic enode 917,837 与 topo-proj 打平导出的
logic 节点 910,486 互洽（差 0.8%，打平时 OP_WHEN 骨架等归桶差异）。

## 3. logic 族逐 pass 分解（2,133,535 → 917,837，共 −1,215,698）

| pass | Δlogic | 占比 | 机制 |
|---|---:|---:|---|
| 5 RemoveDeadNodes | −699,603 | 57.5% | 死代码消除（无消费者的节点整锥移除） |
| 11 ConstantAnalysis | −386,428 | 31.8% | 常量传播：897,023 个节点被判为常量后替换 |
| 15 CommonExpr | −136,643 | 11.2% | CSE：hash-cons 共享相同表达式 |
| 10 RemoveDeadNodes1 | −15,411 | 1.3% | DCE（ExprOpt/SplitNodes 尾量） |
| 12 RemoveDeadNodes | −9,648 | 0.8% | DCE（常量分析尾量） |
| 16 RemoveDeadNodes | −6,609 | 0.5% | DCE（CSE 尾量） |
| 8 SplitNodes | +37,819 | −3.1% | 宽 op 按 lane 拆开（usedBits 驱动） |
| 其余阶段 | ≈0 | — | |

**判据核对**：doc 18 预期"若 commonExpr 单 pass 消 ≈1M logic 则 H1
坐实"——实测 commonExpr 只消 13.7 万（其全部桶合计 −66.3 万 op），
**CSE 不是主力**；H1 成立的形式是"AM 缺整条优化流水（DCE + 常量
分析 + CSE），其中 DCE 与常量分析贡献近九成"。

## 4. AM 侧死代码交叉验证

gsim 首轮 DCE 删掉的是"无消费者"的节点锥。直接在 AM 图上复测同一
性质：以 state_write 节点 + 副作用 op（system.task / dpi.call /
changed.* / mem.write / mem.fill）+ order 边端点为根，沿 def_use
反图 BFS，不可达即死。

| 图 | 节点 | 死指令 | 占比 | 其中 logic |
|---|---:|---:|---:|---:|
| AM（xs_full_20260730） | 4,669,495 | **729,077** | **15.6%** | **486,528** |
| gsim 打平（20260731） | 3,043,902 | 2 | 0.0% | 0 |

AM 死 op top：logic_and 196,020、mux 134,323、logic_or 120,847、
and 98,051、eq 88,215、logic_not 67,753（replicate 9,552、
slice_static 6,768 等少量）。gsim 侧仅 1 个 CONST_INT + 1 个 INPUT
无引用——4 轮 DCE 后图是干净的。

**这 48.7 万死 logic 直接占 logic 总差（Δ1,366,236）的 36%**，且性质
与 gsim 首轮 DCE 的删除物完全同类。AM 缺 DCE 从流水清单推测变成
图上实锤。

## 5. logic 差归因更新

Δ1,366,236 的估计分解（AM 侧实测以"死代码"一项为准，其余为 gsim
侧删除量的类比估计，待 T2 在 AM 上实测修正）：

| 来源 | 估计量 | 占比 | 证据等级 |
|---|---:|---:|---|
| 死代码（AM 无 DCE） | 486,528 | 36% | AM 图实测 |
| 常量传播级联（AM 无常量分析） | ~386,000 | 28% | gsim ConstantAnalysis 实测，AM 待 T2 |
| CSE（AM redundant-elim 未接入） | ~137,000 | 10% | gsim CommonExpr 实测，AM 待 T2 |
| 余量（多轮 DCE 尾量 + IR 惯用法差异） | ~357,000 | 26% | 差额；惯用法部分归 T4 |

旁证"AM ≈ gsim 未优化水平"：AM logic 2,276,722 vs gsim Init
2,133,535（1.07x）；AM 的 2.28M 基本就是"没削过"的形态。

## 6. 附带观察

- **AliasAnalysis 删 173.5 万别名节点**（4.87M→3.14M，op 数不变）——
  这是 wire 差（AM `assign` 233k vs gsim `REF` 69k）的主要机制：
  gsim 把纯连线节点消掉，AM 保留。
- OP_READ_MEM 在 AliasAnalysis 从 4,532 → 3,394（重复读端口被合并）。
  AM `mem.read` 49.3k 是另一量级的口径差异，仍归 T5 清算。
- InferAllWidth 插入 271k 个 OP_PAD，随后被常量分析折掉大半——
  gsim 的 cast/shift"反向多出"（doc 18 §2）确属降阶产物，非语义内容。
- PatternDetect 反向 +22k op（把惯用形态重写为 cmp/const/slice 组合），
  量小，不影响归因。
- OP_NOT 在 FIR 里本来就少（Init 18,840 → 终态 7,039）vs AM `not` 族
  210k——这不是优化能解释的，是 IR 惯用法差异（SV 的 `!`/`~` vs FIR
  的 `eq(x,0)`/取反内联），移交 T4 采样确认。

## 7. 对 T2 的调整

T2 从"单挂 redundant-elim"扩展为**优化三件套**（按贡献排序）：

1. 接 `dead-code-elim`（wolvrix 已有 `lib/transform/dead_code_elim.cpp`，
   预期直接消 ~70 万指令 / ~49 万 logic）；
2. 常量传播级联（`const_fold` + DCE 迭代，对标 ConstantAnalysis 的
   ~39 万 logic）；
3. 接 `redundant-elim`（CSE，对标 ~14 万 logic）。

验证链：改 `scripts/wolvrix_xs_grhsim.py` 的 pre_sched_pipeline →
重导 post-stats JSON → grhsim-am-lower-json 重出 JSONL →
`op_shape_compare.py` 复测（logic 差应收窄到 <40 万）→ 死代码复测
（应 <1%）→ 功能门（difftest/既有验证流）。若验证通过，再在 CSE 后
的 AM 图上重跑 doc 16 的同一规范化 DP——这就是第二步分析的输入基线。

## 备注

- 阶段 dump：`exp/dataset/gsim_pass_stats_20260731/`（21 份 JSON）；
  分析结果：`exp/dataset/gsim_stage_op_delta_20260731.json`。
- 死代码复测脚本为本分析一次性内联实现（def_use 反图 BFS，全量
  ~25 s/图）；若 T2 需要可固化到 `exp/tools/`。
- gsim 日志关键行：`[commonExpr] remove 399946 nodes`、
  `[aliasAnalysis] remove 1734757 alias`、
  `[constantNode] find 897023 constantNodes`、
  `[removeDeadNodes] remove 3619319 deadNodes`。
