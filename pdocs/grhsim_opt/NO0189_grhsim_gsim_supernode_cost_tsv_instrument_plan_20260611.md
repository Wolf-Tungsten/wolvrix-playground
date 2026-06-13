# NO0189 GrhSIM / GSIM 超节点成本模型 TSV 插桩计划

记录日期：2026-06-11
状态：GrhSIM 已实施；GSIM 已实施
关联：[`NO0003`](./NO0003_gsim_default_xiangshan_activation_instrument_20260418.md)、[`NO0004`](./NO0004_grhsim_default_xiangshan_activation_instrument_20260418.md)、[`NO0076`](./NO0076_xs_gsim_grhsim_supernode_activation_stats_20260508.md)、[`NO0077`](./NO0077_xs_gsim_grhsim_runtime_profile_coremark_50k_20260509.md)、[`NO0087`](./NO0087_current_gsim_grhsim_quant_profile_perf_20260511.md)、[`NO0092`](./NO0092_activity_schedule_op_granularity_commit_bucket_snapshot_20260514.md)

---

## 1. 背景与目标

为统一分析 GrhSIM 与 GSIM 的单次推进耗时，建立成本模型：

```
T = Σ_{i=1..N} f(i) · ( E(i) + A_succ(i) )  +  N · A_exam
```

- `N`：超节点个数
- `f(i)`：超节点 i 的激活频率
- `E(i)`：超节点 i 中 **op**（注意不是 Node）的数量
- `A_succ(i)`：超节点 i 中为「判断后继激活」而执行的**变动检测**数量
- `A_exam`：超节点激活检测的常数（每个超节点每次推进都要检查一次 active 位）

本计划的交付物：对 GrhSIM（`grhsim_cpp` 生成的仿真器）与 GSIM（`reference/gsim` 生成的仿真器）的 cppEmitter 插桩，使仿真结束后以 **TSV** 格式输出每个超节点的 `f(i)`、`E(i)`、`A_succ(i)`，供后续把 `A_exam` 作为整机拟合常数回归。

2026-06-11 实施记录：已按需求落地 **GrhSIM** 与 **GSIM** 侧改动。

`T` 中的 `f(i)`、`E(i)`、`A_succ(i)` 在本阶段输出；`A_exam` 与 `N` 不在 per-supernode 表中（`A_exam` 是单一全局常数，留作拟合；`N` 由表行数得到）。

> 本计划只覆盖**插桩与 TSV 导出**。公式回归、A_exam 拟合、两边数据对齐分析属于后续独立议题，应另起 `NOxxxx`。

---

## 2. 口径决定（已与需求方确认）

| 维度 | 决定 | 含义 |
| --- | --- | --- |
| GrhSIM 超节点粒度 | **compute / commit 分两行** | 一个 `supernodeId` 的 compute 部分与 commit 部分各算一个 i（各自的 `f`、`E`、`A_succ`）。`N` 因此大于 `supernodeToOps.size()`，更贴合 grhsim 实际独立调度与 per-firing 成本，也更接近 gsim 的 subStep 粒度。 |
| `f(i)` 语义 | **期望触发次数 / eval** | `f(i) = 该超节点(该 phase) 总触发次数 / 总 eval(step) 数`。grhsim 一次 eval 内有定点多轮，`f(i)` 可 > 1；gsim 每步每 subStep 跑一次，`f(i) ≤ 1`。直接代入 `Σ f·(E+A_succ)`。 |
| `A_succ(i)` 口径 | **只出变动检测比较点数** | `A_succ(i)` = 该超节点中「有后继扇出的输出值」个数；每个 `old != new` 比较计一次。不取激活边数（扇出之和）。 |
| `E(i)` 口径 | **全部分项都出列** | 插桩阶段不写死 grhsim↔gsim 的对齐口径，输出全部 op 分项，分析时再选列对齐。 |

---

## 3. 列语义与 code 映射

### 3.1 f(i) —— 唯一需要运行期计数的量

- 分子：per-supernode（grhsim 再按 compute/commit 拆）**触发计数器**，在超节点 body 进入时自增。
- 分母：
  - GrhSIM：`eval_invocation_count_`（`grhsim_cpp.cpp` 中每次 eval 自增）。
  - GSIM：`cycles`（`reference/gsim/src/cppEmitter.cpp`，`step()` 每步自增）。

### 3.2 E(i) —— 静态，emit 期已知

- **GrhSIM**：已有 `EmitModel::runtimeProfile{Source,Compute,Sink}OpsBySupernode`（`grhsim_cpp.cpp:2564` 附近，按 `OperationKind` 分类于 `grhsim_cpp.cpp:~2725-2760`）。compute 行用 compute 部分的 op 计数，commit 行用 commit 部分（sink）的 op 计数。
  - 输出列：`e_source` / `e_compute` / `e_sink` / `e_total`。
- **GSIM**：op 取 **ENode 粒度**（不是 Node）。`reference/gsim/src/perfAnalysis.cpp` 的 `countOpsInTree()` / `countOps()` 已按「跳过常量与 node-ref 的 ENode」计 op；`runtimeProfile{Node,RefENode,NonRefENode}Weight[cppId]` 也已在 emit 期写入（`cppEmitter.cpp:~1180-1190`）。
  - 输出列：`e_node` / `e_ref_enode` / `e_nonref_enode` / `e_total`（`e_total` 取 ENode-op 口径，即 `countOps`）。

> 两边 `E(i)` 字段名不同（grhsim source/compute/sink，gsim node/ref/nonref-enode），属预期，对齐口径在分析阶段决定。

### 3.3 A_succ(i) —— 静态，emit 期可数

- **GrhSIM**：变动检测在 `emitChangedValuePropagation()`（`grhsim_cpp.cpp:~4545`）发出 —— 当某输出值在 `model.boundaryFanoutByValue`（`grhsim_cpp.cpp:2540`、构建于 `:~6574-6596`）中有条目时，emit 一处 `old != new` 比较。`A_succ(i)` = 该超节点（该 phase）内命中 `boundaryFanoutByValue` 的输出值个数（已有判定 helper 在 `:~4795`）。
- **GSIM**：变动检测在 `activateNext()`（`cppEmitter.cpp:690`）发出 `cond = value != old`。`A_succ(i)` = 该超节点内调用 `activateNext` 并发出比较的节点个数（即有 `nextActiveId` 扇出的成员数）。

> 注意：本口径数的是**比较点数**，不是扇出之和（一次比较可能置多个后继 active 位）。这与「变动检测的数量」字面一致。

---

## 4. GrhSIM 插桩方案

### 4.1 数据模型（新增）

为支持 compute/commit 分两行，按 phase × supernode 维护静态与动态量。建议在生成类里新增：

```cpp
// 仅在 runtime_profile_enabled_ 时分配/累加，避免污染默认快档 runtime
std::vector<std::uint64_t> sn_fire_compute_;   // size = supernode 数
std::vector<std::uint64_t> sn_fire_commit_;
```

静态量（`e_*`、`a_succ`）不必进运行期数组——它们在 emit 期已知，可在 dump 时由 emitter 直接把常量写进 TSV 生成代码（或写一个 `static constexpr` 表）。

### 4.2 f(i) 运行期计数

- 在 compute-batch 的逐超节点门控 emit 点（`grhsim_cpp.cpp:~11760`，现有 `if (runtime_profile_enabled_) { ++runtime_profile_active_supernodes_; ... }` 块内，此处 `supernodeId` 与 `activeIdBySupernode` 均已知）追加：
  ```cpp
  ++sn_fire_compute_[<supernodeId>];
  ```
- 在 commit-batch 的对应门控 emit 点追加 `++sn_fire_commit_[<supernodeId>];`（需定位 commit phase 的逐超节点 emit 路径，与 compute 对称）。
- 保持在 `if (runtime_profile_enabled_)` 守护内，零开销默认关闭。

### 4.3 E(i) / A_succ(i) 静态列

- `E`：直接读 `runtimeProfile{Source,Compute,Sink}OpsBySupernode[supernodeId]`，compute 行写 compute 类，commit 行写 sink 类（具体归属以 `supernodeHasComputePart` / `supernodeHasCommitPart`、`classifyRuntimeProfileOp` 为准，实施时核对边界 op 的 phase 归属）。
- `A_succ`：新增 emit 期统计，遍历 `schedule.supernodeToOps[supernodeId]` 的结果值，统计命中 `boundaryFanoutByValue` 的个数；按该值属于 compute 还是 commit phase 归入对应行。

### 4.4 触发与 TSV 导出

- 复用现有 `set_runtime_profile_enabled()` / `dump_runtime_profile()` 接线（emu harness 中 `EMU_RUNTIME_PROFILE=1` 路径，参考 [`NO0077`](./NO0077_xs_gsim_grhsim_runtime_profile_coremark_50k_20260509.md)）。
- 在 `dump_runtime_profile()` 末尾追加 per-supernode TSV 写出；输出路径取环境变量，缺省落到 emit 目录：
  - 建议新增 `WOLVRIX_GRHSIM_SUPERNODE_TSV`（缺省 `build/xs/grhsim/grhsim_supernode_cost.tsv`）。
- TSV 首行写表头与一行 `# total_evals=<eval_invocation_count_>` 注释，便于核算 `f`。

---

## 5. GSIM 插桩方案

GSIM 已有大量可复用件，改动最小。

> 2026-06-11：未实施。本次变更范围限定在 GrhSIM emitter。

### 5.1 已有

- per-supernode 触发计数 `activeTimes[cppId]`、`nodeNum[cppId]`、`validActive[cppId]`（`cppEmitter.cpp:~1153`，`PERF` 宏）。
- 总步数 `cycles`（`step()` 自增，`cppEmitter.cpp:1033`）。
- `emu.cpp:~326-333` 已把 `activeTimes/cycles`（即 `f(i)`）连同 `nodeNum`、名字写入 `data/active/activeTimes*.txt` —— 已是半个 TSV。
- emit 期 op 权重 `runtimeProfile{Node,RefENode,NonRefENode}Weight[cppId]`（env `GSIM_EMIT_RUNTIME_PROFILE`）。

### 5.2 需新增

1. **`E(i)` ENode-op 列**：把 `countOps`（`perfAnalysis.cpp`）的 per-supernode 结果落成可在 dump 时读取的表（或复用 `runtimeProfileNonRefENodeWeight` 作为 `e_total`）。补 `e_node` / `e_ref_enode` / `e_nonref_enode`。
2. **`A_succ(i)` 列**：emit 期在 `activateNext()` 发出比较处对当前超节点累加一个 per-supernode 计数（统计「发出变动检测的成员数」），存入 `aSucc[cppId]` 静态表。
3. **统一 TSV 导出**：新增一个 per-supernode TSV（列与 grhsim 对齐，见 §6），由 env 控制路径（建议 `GSIM_SUPERNODE_TSV`，缺省写到 gsim 输出目录）。在仿真结束（而非每 1% 周期）一次性导出，避免与现有 `activeFp` 周期 dump 混淆；可与现有 `PERF` 宏共存或新开独立开关。

> 口径统一注意：gsim `f(i)` 分母是 `cycles`；grhsim 是 `eval_invocation_count_`。两者都按「每次推进」定义，语义一致；分析时注意 grhsim 因定点多轮可 > 1。

---

## 6. TSV Schema

两边各导出一个文件，**公共字段对齐**，sim 专属分项各自成列。每文件首部含注释行记录分母。

公共列（两边同名同义）：

| 列 | 含义 |
| --- | --- |
| `sim` | `grhsim` / `gsim` |
| `supernode_id` | 稳定 id（grhsim：`supernodeId`；gsim：`cppId`） |
| `phase` | grhsim：`compute` / `commit`；gsim：`-` |
| `fire_count` | 运行期触发计数（分子） |
| `f` | `fire_count / total_evals` |
| `e_total` | op 总数（grhsim：source+compute+sink；gsim：`countOps`/non-ref ENode 口径） |
| `a_succ` | 变动检测比较点数 |

sim 专属分项列：

- GrhSIM：`e_source`、`e_compute`、`e_sink`
- GSIM：`e_node`、`e_ref_enode`、`e_nonref_enode`

文件头注释：`# total_evals=<N_eval_or_cycles>`、`# N_rows=<行数>`。

---

## 7. 运行口径（emit / build / run）

沿用现有 XiangShan CoreMark 流程，保证与历史快照可比：

- GrhSIM：`scripts/wolvrix_xs_grhsim.py` + `make xs_wolf_grhsim_emu`；运行带 `EMU_RUNTIME_PROFILE=1`、`EMU_PROGRESS_EVERY_CYCLES=0`，cycle 数对齐 50k（参考 [`NO0184`](./NO0184_coremark50k_runtime_gate_20260521.md)）或先用 20k 冒烟。
- GSIM：`make xs_gsim_emu`，按 `PERF` / `GSIM_EMIT_RUNTIME_PROFILE` 口径 build，同一 CoreMark workload 与 cycle 数。
- 两边在仿真结束后各产出一份 `*_supernode_cost.tsv`。

> 实施前需在 emu harness 里确认 `EMU_RUNTIME_PROFILE` → `set_runtime_profile_enabled(true)` 与结束时 `dump_runtime_profile()` 的具体接线点（grhsim），以及 gsim 结束导出的挂载点。

---

## 8. 验收（sanity check）

- 行数 `N_rows` == grhsim（compute+commit 两类超节点数之和）/ gsim（非空 subStep 数）。
- `Σ fire_count`（grhsim compute 行）≈ 现有聚合 `runtime_profile_active_supernodes_`（compute 部分），用于交叉校验 per-supernode 计数无遗漏/重复。
- 抽样几个已知热超节点（参考 [`NO0097`](./NO0097_no0162_hot_batch_anatomy_20260521.md) 的热 batch），核对 `e_total`、`a_succ` 与源码一致。
- gsim `f` 全部 `≤ 1`；grhsim 允许 `> 1`，但极端值需复核是否定点多轮预期。
- 关闭 profile 时，TSV 不生成且 runtime 无回退（守护在 `if (enabled)` / 独立宏内）。

### 8.1 2026-06-11 GrhSIM 实施结果

- 代码：`wolvrix/lib/emit/grhsim_cpp.cpp`
  - `EmitModel` 新增 `runtimeProfileASuccBySupernode`，`buildRuntimeProfileWeights()` 在 emit 期统计每个 supernode 的 `a_succ`（结果值命中 `boundaryFanoutByValue` 且 fanout 非空即计 1）。
  - runtime profile 生成代码新增 `runtime_profile_fire_compute_` / `runtime_profile_fire_commit_`，在每个 supernode body 进入、且 `runtime_profile_enabled_` 为 true 时分别自增。
  - `eval_invocation_count_` 现在也在 `emit_runtime_profile` 模式下生成并每次 `eval()` 自增，用作 TSV 的 `f = fire_count / total_evals` 分母。
  - `dump_runtime_profile()` 在原聚合 printf 后追加 per-supernode TSV 导出。路径由 `WOLVRIX_GRHSIM_SUPERNODE_TSV` 覆盖；缺省写入 emit 输出目录下 `grhsim_supernode_cost.tsv`。若父目录不存在，会尝试创建。
  - `init()` 会清零新增 per-supernode fire 数组、聚合 profile 计数和 `eval_invocation_count_`，避免重复 init 后混入旧运行数据。
- TSV schema（GrhSIM）：注释头 `# total_evals=<N>`、`# N_rows=<rows>`，数据列为：

```text
sim	supernode_id	phase	fire_count	f	e_total	a_succ	e_source	e_compute	e_sink
```

- GrhSIM 行粒度：compute supernode 输出 `phase=compute`，commit supernode 输出 `phase=commit`；当前 activity schedule 已拒绝 mixed compute/commit supernode，因此每个 supernode 只进入对应 phase 行。
- 测试：`wolvrix/tests/emit/test_emit_grhsim_cpp.cpp`
  - 默认 emit 断言仍不生成 runtime profile hot-path 字段。
  - `emit_runtime_profile=1` 断言生成 per-supernode fire 数组、hot-path 自增、TSV env/path/schema 片段，并实际 `make` 编译 runtime-profile 生成目录。
  - runtime-profile 测试新增最小 harness：设置 `WOLVRIX_GRHSIM_SUPERNODE_TSV`、开启 profile、执行一次 `eval()`、调用 `dump_runtime_profile()`，并检查 TSV 中 `# total_evals=1`、schema、compute/commit 行。
- 已执行：`cmake --build wolvrix/build --target emit-grhsim-cpp emit-grhsim-cpp-memory-fill -j$(nproc)`。
- 已执行：`ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'`，结果 passed。
- 已执行：`ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp-memory-fill$'`，结果 passed。

### 8.2 2026-06-11 GSIM 实施结果

- 代码：`reference/gsim/src/cppEmitter.cpp`
  - `GSIM_EMIT_RUNTIME_PROFILE=1` 时，生成模型新增 `runtimeProfileFireCount` 与 `runtimeProfileASucc`。
  - 每个 subStep supernode body 进入、且 `runtimeProfileEnabled` 为 true 时，自增 `runtimeProfileFireCount[cppId]`。
  - emit 期统计静态 `a_succ`：只统计会调用 `activateNext()` 并发出变动比较的成员节点；数组/WRITER 的无条件激活不计入。
  - 新增 `runtimeProfileOpWeight` 作为 `e_total` 的 ENode-op 口径，跳过常量、node-ref 与 index 类 ENode；保留原 `runtimeProfileNonRefENodeWeight` 作为 `e_nonref_enode` 分项。
  - `dump_runtime_profile()` 在原聚合 printf 后追加 per-supernode TSV 导出。路径由 `GSIM_SUPERNODE_TSV` 覆盖；缺省写入 gsim emit 输出目录下 `gsim_supernode_cost.tsv`。
- TSV schema（GSIM）：注释头 `# total_evals=<cycles>`、`# N_rows=<supernode_count>`，数据列为：

```text
sim	supernode_id	phase	fire_count	f	e_total	a_succ	e_node	e_ref_enode	e_nonref_enode
```

- 已执行：`make -C reference/gsim build-gsim`。
- 已执行：`GSIM_EMIT_RUNTIME_PROFILE=1 reference/gsim/build/gsim/gsim --dir /tmp/gsim-sn-prof-test reference/gsim/test/repro-usefulreset.fir`。
- 已执行：最小 harness 编译并运行 runtime profile 生成模型，检查 TSV 输出 `# total_evals=3`、`# N_rows=1` 与数据行。
- 已执行：`GSIM_EMIT_RUNTIME_PROFILE=0 reference/gsim/build/gsim/gsim --dir /tmp/gsim-sn-noprof-test reference/gsim/test/repro-usefulreset.fir`，并确认默认生成模型不包含 `runtimeProfileFireCount` / `runtimeProfileASucc` / TSV 导出片段。

---

## 9. 风险与未决

1. **A_succ 静态 vs 动态**：本计划数的是静态比较点数。grhsim/gsim 中部分比较受 supernode body 内部分支控制，单次触发实际执行的比较数可能 < 静态值。先按静态口径（与 `f·A_succ` 的 per-firing 假设一致）；若后续公式拟合残差大，再考虑加动态比较计数列。
2. **compute/commit op 的 phase 归属**：边界 op（既被 compute 读又被 commit 写的值）归属需以 `classifyRuntimeProfileOp` + `supernodeHas*Part` 为准，实施时核对，避免双算或漏算。
3. **gsim 双 dump 共存**：新 per-supernode TSV 与现有 `activeFp` 周期 dump 不要互相覆盖；建议新开独立 env 开关与独立文件。
4. **PERF 宏构建成本**：gsim per-supernode 数组在大设计上占内存/编译时间；沿用现有 `PERF` 口径，不进默认 build。
5. **A_exam 不在表内**：作为整机拟合常数，由后续回归从 `T_measured`、`Σ f·(E+A_succ)`、`N` 反解；本计划只保证 `N`（行数）与 `total_evals`（表头）可得。

---

## 10. 不在本计划范围

- 公式回归与 `A_exam` 拟合、两边数据对齐与差距归因（另起 `NOxxxx`）。
- 任何 emitter 优化/重构（本计划只读结构 + 加计数，不改调度与代码形态）。
- 默认 build 行为变更（插桩一律 env / 宏门控，缺省关闭）。

---

## 11. 增量更新 2026-06-12：口径对齐修正与首轮实测归因

> 本节为执行本计划 TSV 产物后的首轮对齐分析与实测结论。原计划 §10 将此类分析划为另起文档；此处按需求方要求并入本文，作为追加记录，不改动 §1–§10 任何原结论。数据均为 XiangShan CoreMark 50k。

### 11.1 关键修正：E(i) 口径不可直接比，需给 GSIM 补 source/sink

首轮拿 grhsim `e_total`(=source+compute+sink) 比 gsim `e_total`(=`countOps`，仅 compute 类 real-op ENode) 得到 `Σf·E ≈ 1.52×`，**系口径不可比造成的假象**：gsim 的 op 口径把常量(`OP_INT`)、节点引用(`nodePtr`)、index、写口(lval) 全部排除，**结构性缺 source/sink**。按可比口径（grhsim `e_compute` ↔ gsim `e_total`）实为 **0.64×**。

修正：给 GSIM 侧补 source/sink 计数，`e_total` 重定义为 `compute+source+sink`，与 grhsim 真正逐列对齐。
- 代码：`reference/gsim/src/cppEmitter.cpp`，`RuntimeProfileWeights` 新增 `sourceOps`/`sinkOps`；新增 `countRuntimeProfileConstInTree`（常量 per-occurrence）、`collectRegReadRefs`（寄存器读 per-distinct，supernode 级去重）；sink 按成员节点类型计（`NODE_REG_DST` 写口 + `NODE_WRITER`/`NODE_READWRITER` 内存写口）。
- 映射：grhsim `kConstant`→gsim `OP_INT`；`kRegisterReadPort`→`nodePtr→NODE_REG_SRC`（每超节点每寄存器计 1）；`kRegisterWritePort`→`NODE_REG_DST`；`kMemoryWritePort`→`NODE_WRITER`；latch/fill gsim 无对应记 0；memory read 两边都归 compute。
- TSV 新增列：`e_compute`/`e_source`/`e_sink`（`e_total=三者之和`），保留 `e_node`/`e_ref_enode`/`e_nonref_enode`。
- **踩坑修正**：新增两个 `[superId]` 大内联数组（2×677KB）把 `SSimTop` 对象布局推移 1.35MB，使 gsim 生成代码中一处潜在越界读（首个 step 读未初始化索引）由"撞已映射页静默返回垃圾"变为 SIGSEGV（`subStep87`）。改为 `std::vector<uint64_t>` 堆分配（对象仅增 ~48B）后恢复。属 gsim 参考实现自身健壮性问题，非插桩逻辑错误。
- sanity：`e_total==compute+source+sink` 逐行无误；新 `e_compute` 与旧 `e_total` 仅 4/84714 行差异（gsim 重生成非确定性，可忽略）。

### 11.2 对齐后的成本对比

| 单次 eval `Σf·X` | GRHSIM | GSIM | grh/gsim |
| --- | --- | --- | --- |
| compute | 520,856 | 809,762 | 0.64× |
| source | 310,458 | 509,618 | 0.61× |
| sink | 396,481 | 36,793 | **10.78×** |
| e_total | 1,227,796 | 1,356,173 | 0.91× |
| a_succ | 151,435 | 75,098 | 2.02× |
| **Σf·(E+A)** | 1,379,230 | 1,431,271 | **0.96×** |
| eval 次数 | 100,102 | 50,101 | 2.00× |
| 总工作量（×eval 数） | 1.381e11 | 7.171e10 | **1.93×** |

**修正结论**：单次 eval 的算子工作量两边基本相等（0.96×，grhsim 甚至略低）；总工作量差距 ~1.93× 几乎全部来自 grhsim 每 cycle 2 次 eval。最初的 1.52×/3.1× 作废。构成差异显著：grhsim sink 10.8×、a_succ 2×，compute/source 反而更少。

### 11.3 为什么每 cycle 2 次 eval（结构性，不可免费消除）

`emu/emu.cpp` 把 grhsim 当 Verilator 驱动：`set_clock(1);step()`（正沿）+ `set_clock(0);step()`（负沿）= 2 eval/cycle；GSIM 则单 `step()` 内部模型整 cycle。clock 在 grhsim 是被 toggle 的输入信号，负沿是真实事件。负沿侧有 difftest/DPI-C 副作用点（`kDpicCall`、`DifftestSDCard` 在负沿写），直接删负沿 eval 会改协同仿真语义。想 1 eval/cycle 只能换成 gsim 那种 cycle-based 单遍模型，属架构级改动。

### 11.4 负沿/正沿实测拆分（grhsim 插桩，修正先前臆测）

给 grhsim 加按时钟边沿拆分的计数（`grhsim_cpp.cpp`：`runtime_profile_{eval,rounds,active}_{pos,neg,other}_`，eval 头按 `grhsim_classify_edge(prev_clock,clock)` 分类，dump 输出 `[GRHSIM_RUNTIME_PROFILE_EDGE]`）。实测：

```
eval:    posedge=50050   negedge=50051   other=1      (≈各半，证实 2 eval/cycle)
rounds/eval:  pos=2.01    neg=2.00
活跃超节点/eval: pos=16,422   neg=2,316
全部 firing 中负沿占 12.4%
```

- **负沿激活 ≈ 正沿的 14.1%**（2,316 vs 16,422），且负沿同样跑 ~2 轮定点。**先前"负沿几乎空转、只有 3 个锥"的推断错误**：负沿实际触发 ~2316 个超节点（很可能由 difftest 在 cycle 后半拍 poke 输入/中断/内存响应 + 时钟电平相关逻辑驱动），是真实工作，不能免费砍。

### 11.5 N·A_exam 占比实测（小，非主因）

激活扫描每轮重跑全部 batch 的逐字 `if(word!=0)` 门控；总轮数 = 200,653。
- 逻辑口径 `N×rounds = 1.46e10` → 占总工作量 **9.6%**。
- 机器实际口径（8 超节点/字，`N/8×rounds = 1.82e9`）→ **1.3%**。

**先前"~50000 次空转扫描是浪费大头"夸大了**；N·A_exam 真实占比 1.3%–9.6%，非性能主因。

### 11.6 核心矛盾与归因：模型 ~2× vs 实测 8.4×

| | 值 |
| --- | --- |
| op-count 模型总工作量（USEFUL+EXAM） | grhsim 1.53e11 vs gsim ~7.6e10 ≈ **2.0×** |
| 实测墙钟（host time） | grhsim **390,640ms** vs gsim **46,307ms** = **8.4×** |

模型 2×、实测 8.4×，缺口 ~4× 既非 N·A_exam（≤10%）也非负沿（已计入 firing）。**主因是每个 op 的真实成本不均等，而代价公式假设等权**：grhsim 工作压在 sink（39.7e9 次写口/store）+ source（31e9 读/常量物化）+ 事件驱动派发（激活位读写、按边界值变动检测、batch 间接调用）+ 粗粒度超节点/巨大状态对象的 cache 不友好。

**归因**：grhsim 慢 8.4× ≈ 2×（双边沿 eval，结构性）× ~4×（每 op 更贵，主要是 store-heavy 的 sink/commit + 事件派发开销）。优化重点不在砍负沿或减扫描，而在降低 sink/commit 内存写成本与事件派发开销——与 §11.2 中 commit-phase sink 10.8× 同根因。

### 11.7 本次新增插桩（默认关闭，env/宏门控）

- GSIM source/sink：`reference/gsim/src/cppEmitter.cpp`（仅 `GSIM_EMIT_RUNTIME_PROFILE=1` 时生成）。
- GrhSIM 边沿拆分计数：`wolvrix/lib/emit/grhsim_cpp.cpp`（仅 `emit_runtime_profile` 时生成；运行期 `if(runtime_profile_enabled_)` 守护）。
- 产物：`tmp/grhsim_cost_tsv_20260611/gsim_supernode_cost_v2.tsv`（对齐后）、grhsim `[GRHSIM_RUNTIME_PROFILE_EDGE]` 行（log）。
