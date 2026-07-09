# NO0240：GrhSIM input-change full-pass specialization 实现计划

日期：2026-07-09

## 1. 背景

[NO0238](./NO0238_dynamic_fire_compare_20260709.md) 和 [NO0239](./NO0239_no_propagate_fullpass_probe_20260709.md) 已经把 `VtypeBuffer` input-low 的主要差异拆清楚：

1. input-low 下 GrhSIM compute supernode 基本全量 active；
2. always-active 时，compute->compute changed/active propagation 不能提供剪枝收益，却贡献大量真实机器指令；
3. 临时 no-propagate full-pass probe 可让 low-only runtime `203.141ms -> 131.593ms`，但不是完整语义实现。

本文规划一个可工程化的下一步：把 unsafe probe 收敛成默认关闭、可验证的 codegen A/B。

## 2. 目标

新增一个 GrhSIM emit 实验路径：**input-change full-pass specialization**。

目标行为：

- 当 eval 由普通 data input change 触发，且本轮不是 clock/event commit 触发时，走 full-pass compute specialization；
- specialization 内所有 compute supernode 按拓扑顺序执行一次；
- downstream compute 已经保证执行，因此跳过 compute->compute changed/active propagation；
- 保留正常 event-driven eval path 作为默认路径和 fallback。

## 3. 非目标

本阶段不直接解决：

- clock-high / commit 后第二轮 compute 的优化；
- slot/ref load-store 根因；
- supernode partition 重构；
- 完整 XiangShan 默认开启。

这些必须等 input-change specialization correctness/runtime gate 通过后再推进。

## 4. 建议实现方式

### 4.1 新增 emit option

先做默认关闭选项，例如：

```text
GRHSIM_INPUT_FULLPASS_SPECIALIZATION=1
```

或 Python emit 参数：

```text
--input-fullpass-specialization
```

默认关闭，避免影响现有 gate。

### 4.2 生成 compute full-pass batch variant

不要用 runtime flag 包住现有 `eval_compute_batch_N()`，否则 Clang 难以 DCE changed/active propagation。

建议额外生成：

```cpp
void eval_compute_batch_0_fullpass();
void eval_compute_batch_1_fullpass();
...
```

该 variant：

- 不从 `supernode_active_curr_` 读取 active flags；
- 不生成 `if (activeWordFlags & mask)` 分支；
- 对 batch 内 supernode 直接顺序 emit；
- 对 compute target 不生成 `grhsim_any_changed_*` / active OR；
- 暂不改变 value assignment 本身，保持 slot 写回语义。

### 4.3 propagation policy

在 op/value emit 路径中引入明确策略，而不是字符串 patch：

```cpp
enum class ActivationPropagationPolicy {
    Normal,
    SuppressComputeTargets,
};
```

full-pass compute variant 使用 `SuppressComputeTargets`：

- compute->compute target：跳过 changed aggregation 和 active OR；
- compute->commit / event / state-visible target：先保守保留或明确证明可跳过后再删；
- commit phase：继续使用 `Normal`。

### 4.4 eval dispatch guard

在 `eval()` 中计算：

```cpp
const bool input_fullpass_candidate = !initial_eval && !clock_event && data_input_changed;
```

满足条件时：

1. 执行 full-pass compute batches；
2. refresh outputs；
3. 更新 prev input baseline；
4. 不进入 fixed-point compute->compute propagation loop。

不满足条件时走原始 path。

初版可以只在 `clock == prev_clock` 且 data input changed 时启用；clock edge/high phase 一律 fallback。

## 5. Correctness gate

最小 gate：

1. `XsReal075RobVtypebufferLarge`：`--verify 4096`；
2. NO0228 小负载集合：BigComb、FTQ、Tage、VtypeBuffer 至少 20k vectors；
3. 对 `clock-high` 行为保持 fallback，重点检查 reset/first_eval/posedge commit；
4. 如果任一 mismatch，立即记录负向文档并回退实现。

## 6. Runtime / static gate

以 `VtypeBuffer` 为主：

- 200k `--model grhsim --repeat 3`；
- phase runner 对比 input-low；
- static gate：`eval_compute_batch_0..3_fullpass` 指令应接近 NO0239 patched 量级（约 `7.8k` 指令），而不是 baseline `11.2k`；
- runtime gate：input-low 至少应有双位数下降；若完整 GrhSIM runtime 下降小于 `5%`，需要解释 high/dispatch 抵消原因。

## 7. 风险

1. full-pass 跳过 propagation 可能漏掉同轮内依赖，必须确保 batch/supernode 顺序覆盖 topological 依赖；
2. commit supernode 的 event dispatch 与 compute input 值关系需要保守处理；
3. 大负载若并非 always-active，full-pass 可能做多余工作，因此必须有 guard 和 fallback；
4. 即使成功，NO0239 显示仍有约 `2.5x` 于 GSIM 的剩余 gap，后续仍需 slot/ref 优化。

## 8. 下一步执行顺序

1. 在 `grhsim_cpp.cpp` 中梳理 activation emit call path，先只加 enum/policy，不改变默认输出；
2. 生成 full-pass compute variant，默认关闭；
3. 对 `VtypeBuffer` 开 option 做 correctness + static diff；
4. 若 correctness 过，再跑 200k/phase perf；
5. 结果新建后续 `NO0241` 文档记录。
