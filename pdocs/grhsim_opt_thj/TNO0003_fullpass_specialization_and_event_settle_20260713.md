# TNO0003 Full-pass specialization and event settle

记录日期：2026-07-13

来源范围：`NO0240..NO0254`，原始记录见 [NO0240](../grhsim_opt/NO0240_input_fullpass_specialization_plan_20260709.md) 至 [NO0254](../grhsim_opt/NO0254_event_settle_density_ftq_tage_gate_20260710.md)。

状态：input/posedge full-pass 与 event adaptive settle 已完成功能闭环；完整 SimTop 仍需依赖稀疏 post-commit closure，不能全图 full-pass。

## 1. 小负载 full-pass 收益

默认关闭的 input full-pass 让普通 data input change 直接执行 compute fullpass、跳过 compute-to-compute propagation：

| Workload | Input full-pass raw gain |
| --- | ---: |
| BigComb | `-25.05%` |
| FTQ | `-9.49%` |
| Tage | `-12.21%` |
| VtypeBuffer | `-7.75%` |

VtypeBuffer low phase 下降约 `27%`。随后 posedge full-pass 在 FTQ/Tage/Vtype 上进一步降低 high phase `10%..17%`，raw runtime 再降 `8%..11%`。

当前 best 与 GSim 对照仍有：

```text
VtypeBuffer runtime      1.52x
retired instructions     1.70x
```

post-commit whole-supernode subset closure 已覆盖 30/38 supernodes，且动态 bit 高频，说明继续做粗粒度 subset 的上限有限。

## 2. SimTop correctness 回归与修复

完整 SimTop 暴露了小负载没有覆盖的 event 语义：原 input/posedge fast path 跳过 clock negedge event commit，10k 出现 refill fail/ABORT。

修复链条为：

1. 按 commit event sample 精确阻断 input full-pass；
2. event fast path 使用 `compute -> commit -> clear edge -> post-commit compute`；
3. pre-commit 保留 input/event seed 的 normal active compute；
4. unknown/event 形态保守回退。

修复后 SimTop 10k/50k difftest 通过，且没有再以隐藏 `input_fullpass_blocked` 的方式规避问题。

## 3. 全图 post-commit 的失败原因

SimTop 10k 中 event 命中 10,048 次且每次 state changed；全图 post-commit fullpass 因此执行：

```text
10,048 * 71,871 = 722,159,808 compute-supernode visits
```

其代价远高于省下的 active work。active-pre 修正虽把 10k host time 从约 92s 降到 61s，仍不足以解决全图 settle。

## 4. Adaptive settle

最终按 commit reader density 分流：

- density `<=25%`：使用动态 active closure；
- density `>25%`：保留 fullpass。

SimTop 相邻 10k 从 `88,144ms` 降到 `19,222ms`，fresh 10k/50k 功能通过。FTQ/Tage reader density 为 `66.00%/61.39%`，强制 active closure 分别回退 `7.57%/5.59%`，支持保留 25% 阈值。

## 5. 阶段结论

full-pass 是 always-active 小负载的有效优化，但不能直接外推到完整 SimTop。正确策略是按 event 语义保持执行顺序，并按 post-commit reader density 在 active closure 与 fullpass 间选择。

## 6. 规则审计与关键数据

记录类型：连续 correctness/root-cause 总结。单一议题边界是“full-pass specialization 如何在保留 clock event 顺序的前提下落到 SimTop”。小负载收益、negedge 修复和 adaptive settle 共同回答这一问题；新的 full-pass 变体应另建 TNO。

### 6.1 小负载 200k gate

每项均为 `200002` 个 component cycles，并执行 `--verify 4096`：

| Workload | Full-pass off (ms) | Full-pass on (ms) | Delta |
| --- | ---: | ---: | ---: |
| NfmappedSmall | 8.142 | 7.787 | `-4.36%` |
| FTQ | 531.896 | 481.421 | `-9.49%` |
| Tage | 456.279 | 400.564 | `-12.21%` |
| VtypeBuffer | 409.407 | 377.688 | `-7.75%` |

VtypeBuffer repeat-3 的 median 从 `430.048ms` 降至 `370.881ms`，即 `-13.81%`。详见 [NO0241](../grhsim_opt/NO0241_input_fullpass_codegen_p0_20260709.md) 与 [NO0242](../grhsim_opt/NO0242_input_fullpass_small_matrix_20260709.md)。

### 6.2 SimTop 功能终点与 settle 成本

| Gate | Guest cycles | `cycleCnt` | `instrCnt` | Host time | 数据用途 |
| --- | ---: | ---: | ---: | ---: | --- |
| corrected fresh 10k | 10,001 | 9,996 | 458 | 19,421ms | 功能回归 |
| corrected fresh 50k | 50,001 | 49,996 | 73,580 | 138,169ms | 功能回归 |
| full-graph settle 10k | 10,001 | 9,996 | 458 | 88,144ms | 相邻旧路径 |
| adaptive settle 10k | 10,001 | 9,996 | 458 | 19,222ms | 相邻候选 |

四项均完成 NEMU difftest；50k terminal PC 为 `0x80001312`。fresh 10k/50k 的绝对 host time 受共享机负载影响，只证明功能和成本量级，不作为跨版本正式性能值；`88,144 -> 19,222ms` 是同一诊断窗口内的相邻比较。详见 [NO0253](../grhsim_opt/NO0253_adaptive_post_commit_settle_20260710.md)。
