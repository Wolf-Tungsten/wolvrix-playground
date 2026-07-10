# NO0233 VtypeBuffer phase counters 与 GSIM subStep 对齐（2026-07-09）

## 1. 背景

`NO0232` 修正了 `NO0229` 的解释：`clock=false eval` 的重成本不是下降沿顺序逻辑，而是 bench 在 low eval 前驱动新输入，导致输入变化后的组合 settle 被计入 low phase。

本轮继续按计划推进：

1. 用 `GRHSIM_PERF=eval` 模型的 `PerfCounters` 按 phase 聚合 GrhSIM round / batch / write 计数；
2. 用 GSIM 生成模型直接拆 `resetAll()` / `subStep0()` / `subStep1()` 计时，确认 GrhSIM 的 input-low / high-posedge 与 GSIM 阶段的粗略对应关系。

## 2. GrhSIM phase counter probe

临时程序：

```text
tmp/no0232_edge_semantics_20260709/vtypebuffer_phase_counter_probe.cpp
```

使用 trace 版模型：

```text
testcase/xs-components/build/no0230_eval_trace_20260709/perf_eval_final/XsReal075RobVtypebufferLarge/grhsim/model/
```

每个 vector 拆三段：

```text
fall_only: clock=false; eval()          // 输入不变，仅 falling/clock-change
input_low: drive(new_input); eval()     // clock 已低，只有输入变化 settle
high_posedge: clock=true; eval()        // posedge commit + post-commit settle
```

输出：

```text
[PHASE_COUNTER_SUMMARY] vectors=200002 checksum=0xb48627881e67a6e4
[PHASE_COUNTER] phase=fall_only evals=200002 ms=7.796 ns_per_vector=39.0 evalCount=200002 totalRound=200001 round1=200001 round2=0 computeBatch=800004 commitBatch=200001 touchedWrite=0 rounds_per_vector=1.000 compute_batches_per_vector=4.000 commit_batches_per_vector=1.000 writes_per_vector=0.000
[PHASE_COUNTER] phase=input_low evals=200002 ms=205.852 ns_per_vector=1029.3 evalCount=200002 totalRound=200001 round1=200001 round2=0 computeBatch=800004 commitBatch=200001 touchedWrite=0 rounds_per_vector=1.000 compute_batches_per_vector=4.000 commit_batches_per_vector=1.000 writes_per_vector=0.000
[PHASE_COUNTER] phase=high_posedge evals=200002 ms=211.150 ns_per_vector=1055.7 evalCount=200002 totalRound=400003 round1=200002 round2=200001 computeBatch=1600012 commitBatch=400003 touchedWrite=16832433 rounds_per_vector=2.000 compute_batches_per_vector=8.000 commit_batches_per_vector=2.000 writes_per_vector=84.161
```

注意：该模型编译了 `perf=eval` counters，绝对时间会有诊断开销；但 counters 对 round/batch/write 结构有用。

关键计数：

| phase | rounds/vector | compute batches/vector | commit batches/vector | writes/vector | 解释 |
|---|---:|---:|---:|---:|---|
| fall-only | 1.000 | 4.000 | 1.000 | 0.000 | clock 变化会进入一轮调度，但 active 为空、无状态写，墙钟很小 |
| input-low | 1.000 | 4.000 | 1.000 | 0.000 | 输入变化触发组合 settle，是 low 重成本来源 |
| high-posedge | 2.000 | 8.000 | 2.000 | 84.161 | posedge commit 后几乎每 vector 都激活第二轮 compute |

因此 high phase 的结构已基本坐实：

- round 1：posedge commit，平均 touch `84.16` 个写；
- round 2：commit 激活 reader 后消费 active compute；
- 每个 high eval 几乎稳定两轮。

## 3. Commit activation 静态 fanout

对 `grhsim_XsReal075RobVtypebufferLarge_sched_4.cpp` 解码：

| metric | value |
|---|---:|
| commit sched lines | 1612 |
| commit sink ops / touchedWrite sites | 113 |
| activity stats `compute_commit_value_pairs` | 164 |
| activity stats `commit_input_root_values` | 165 |
| activation statements in commit code | 207 |
| activation target refs, popcount-sum | 263 |
| unique active supernode ids possibly activated by commit | 26 |
| targets per write, mean | 2.33 |
| targets per write, histogram | `2:80, 3:32, 7:1` |

动态平均 `84.16` writes/vector × 静态均值 `~2.33` targets/write，说明 high phase 的 commit fanout 会产生大量 activation OR，但目标 active supernode 集合上限只有 26 个，实际会强烈重叠。这解释了为什么简单跳过空 compute round（`NO0231`）没有收益：真正的 high 重活在 commit 后第二轮 active compute，而不是第一轮 active 为空时的空 dispatch。

## 4. GSIM subStep 对齐 probe

临时程序：

```text
tmp/no0232_edge_semantics_20260709/vtypebuffer_gsim_step_probe.cpp
```

手动复刻 GSIM `step()`：

```cpp
resetAll();
subStep0();
subStep1();
cycles++;
```

并与原 `step()` checksum 对比。

输出：

```text
[GSIM_SPLIT] vectors=200002 reset_all_ms=4.893 subStep0_ms=147.538 subStep1_ms=55.482 reset_all_ns_per_vector=24.5 subStep0_ns_per_vector=737.7 subStep1_ns_per_vector=277.4 step_checksum=0xb48627881e67a6e4 split_checksum=0xb48627881e67a6e4
```

GSIM 生成代码形态：

- `step()` 直接调用 `resetAll(); subStep0(); subStep1(); cycles++;`
- `subStep0()` 开头就是大量 `meta_* = meta$NEXT_*` / `data_* = data$NEXT_*` 这类状态提交，并根据变化激活后继；
- `subStep1()` 计算下一周期的 `data$NEXT_*` / `meta$NEXT_*` 等 next-state。

因此粗略对应关系是：

| GrhSIM split phase | GSIM phase | 说明 |
|---|---|---|
| fall-only | `resetAll()` / clock bookkeeping 的极轻部分 | 都很轻，不是主因 |
| input-low settle | `subStep1()` 的 next-state/input compute | GrhSIM input settle 明显更慢 |
| high-posedge commit + post-commit settle | `subStep0()` 的 state commit + activation | GrhSIM high 也更慢，但相对差距小于 input-low |

用 raw GrhSIM split（`NO0232`）与 GSIM split 对比：

| conceptual phase | GrhSIM raw ms | GSIM ms | delta |
|---|---:|---:|---:|
| fall-only / reset bookkeeping | 6.767 | 4.893 | +1.874 |
| input / next compute settle | 200.324 | 55.482 | +144.842 |
| posedge commit / post-commit settle | 198.203 | 147.538 | +50.665 |

这个对比说明：

- high/commit fanout 是真实问题；
- 但在 `VtypeBuffer` 上，**更大的相对差距来自 input-low / next-compute 类阶段**，不是单纯 commit 后 activation fanout。

## 5. 结论

本轮把 `VtypeBuffer` 的 `~2x` gap 进一步拆细：

1. 下降沿本身不是重活；
2. GrhSIM 每 vector 的真实工作主要是：
   - input-low 组合 settle，一轮 compute；
   - high-posedge commit + post-commit settle，两轮 fixed-point；
3. high phase 平均 touch `84.16` 个写，并几乎必然触发第二轮 compute；
4. GSIM 也有类似的 state commit / next-state compute 两大阶段，但静态编排在一个 `step()` 中；
5. 相比 GSIM，`VtypeBuffer` 最大的增量成本目前更偏向 GrhSIM input/next compute 代码形态，而 high commit fanout 是第二个重要问题。

## 6. 下一步

下一步不应只盯 commit fanout。更合适的优先级是：

1. **先剖 GrhSIM input-low / next-compute 热路径**：结合 `NO0224-NO0227`，重点看 `eval_compute_batch_3()` 中宽字 `std::array<uint64_t,16>` materialize、lane-level producer fusion、以及 batch 内 active checks；
2. **同时保留 high/commit fanout 线索**：后续若做 commit activation 优化，应目标于减少 commit 后第二轮 active compute 的实际工作量，而不是仅跳过第一轮空 compute dispatch；
3. **做 phase-specific perf**：构造 input-low-only 与 high-posedge-only 的独立运行窗口，让 perf report 能分别归因到 GrhSIM compute batch 与 commit batch，而不是把两个 phase 混在一起。
