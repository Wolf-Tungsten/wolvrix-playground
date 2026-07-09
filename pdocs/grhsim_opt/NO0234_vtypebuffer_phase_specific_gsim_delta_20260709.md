# NO0234 VtypeBuffer phase-specific perf 与 GSIM 差异对照（2026-07-09）

## 1. 背景

`NO0232` / `NO0233` 已经确认：`VtypeBuffer` 的 GrhSIM low eval 重成本并不是下降沿顺序逻辑，而是 bench 在 low eval 前驱动新输入，导致输入变化后的组合 settle 被计入 low phase。

本轮按用户建议，进一步“对照 GSIM，看看 GrhSIM 具体多了些什么”。重点不再只看完整 step，而是把 GrhSIM input-low 与 GSIM 的 next-state/input compute 子阶段放到相近窗口里做 perf 和静态代码形态对比。

## 2. 临时 phase runner

临时程序：

```text
tmp/no0234_phase_compare_20260709/vtypebuffer_phase_runner.cpp
```

使用模型：

```text
testcase/xs-components/build/no0228_model_select_perf_20260709/raw_bench/XsReal075RobVtypebufferLarge/grhsim/model/
testcase/xs-components/build/no0228_model_select_perf_20260709/raw_bench/XsReal075RobVtypebufferLarge/gsim/model/
```

runner mode：

| mode | 含义 | 备注 |
|---|---|---|
| `grhsim-input-low` | `drive(input); clock=false; eval(); sample()` | 隔离 GrhSIM input settle；状态不经 high commit 推进 |
| `grhsim-high-interleaved` | 正常 input-low 后，只对 `clock=true; eval()` 计时 | 用于隔离 high/posedge 段 |
| `gsim-sub1-input-only` | `drive(input); set_clock(1); subStep1(); sample()` | 只用于热点和代码形态对照；不是完整 step 语义 |
| `gsim-full-step` | `drive(input); set_clock(1); step(); sample()` | 完整 GSIM step 参考 |

200k smoke 输出：

```text
[PHASE_RUN] mode=grhsim-input-low vectors=200002 ms=202.548 ns_per_vector=1012.7 checksum=0x8eaf220b7bd8c5de
[PHASE_RUN] mode=grhsim-high-interleaved vectors=200002 ms=202.201 ns_per_vector=1011.0 checksum=0xb48627881e67a6e4
[PHASE_RUN] mode=gsim-sub1-input-only vectors=200002 ms=53.073 ns_per_vector=265.4 checksum=0x9d76b825bbb6e35a
[PHASE_RUN] mode=gsim-full-step vectors=200002 ms=203.763 ns_per_vector=1018.8 checksum=0xb48627881e67a6e4
```

注意：`gsim-sub1-input-only` 的 checksum 与 full-step 不相同是预期结果，因为该 mode 故意不执行 state commit；它只用于把 GSIM `subStep1()` 的 next-state/input compute 作为热点对照。

## 3. phase-specific perf stat

对 `grhsim-input-low` 与 `gsim-sub1-input-only` 各跑 2M vectors：

| metric | GrhSIM input-low | GSIM subStep1 input-only | ratio |
|---|---:|---:|---:|
| runner time | `1968.019 ms` | `529.496 ms` | `3.72x` |
| cycles | `7,553,560,167` | `2,240,344,854` | `3.37x` |
| instructions | `22,926,353,068` | `5,017,494,843` | `4.57x` |
| IPC | `3.04` | `2.24` | - |
| branches | `272,019,792` | `323,845,441` | `0.84x` |
| branch misses | `18,258,000` | `35,540,267` | `0.51x` |
| instructions/vector | `11463.2` | `2508.7` | `4.57x` |
| cycles/vector | `3776.8` | `1120.2` | `3.37x` |

结论很直接：GrhSIM input-low 慢不是因为 IPC 更差或 branch miss 更多；相反 GrhSIM IPC 更高、branch 更少。主要差异是 GrhSIM 退休了约 `4.57x` 的 host instructions，并转化为约 `3.37x` host cycles。

## 4. perf report 热点

GrhSIM input-low：

```text
42.80% children / 39.47% self  GrhSIM_XsReal075RobVtypebufferLarge::eval_compute_batch_3()
23.10% children / 21.54% self  GrhSIM_XsReal075RobVtypebufferLarge::eval_compute_batch_0()
22.34% children / 19.18% self  GrhSIM_XsReal075RobVtypebufferLarge::eval_compute_batch_2()
18.21% children / 14.40% self  GrhSIM_XsReal075RobVtypebufferLarge::eval_compute_batch_1()
 3.91% children /  0.79% self  GrhSIM_XsReal075RobVtypebufferLarge::eval()
```

GSIM subStep1 input-only：

```text
85.49% children / 76.59% self  SXsReal075RobVtypebufferLarge::subStep1()
22.50% children /  9.44% self  main
```

这说明 GrhSIM input-low 的重活不是 eval wrapper，而是被拆散到 4 个 compute batch 中；GSIM 对应的 input/next-state compute 则集中在一个专用 `subStep1()` 中。

## 5. 生成 C++ 静态形态对照

统计对象：

- GrhSIM input-low 主要执行：`grhsim_XsReal075RobVtypebufferLarge_eval.cpp` + `sched_0.cpp` ... `sched_3.cpp`；
- GSIM 对照执行：`XsReal075RobVtypebufferLarge1.cpp`。

主要源码计数：

| unit | lines | nonblank | `if` | `unlikely` | `activeFlags` | `oldFlag` | `supernode_active_curr_` | `value_u64_slots_` | `value_words_16_slots_` | `grhsim_value_storage_ref` | `_words_full` | `$NEXT` refs | `uint64_t` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GrhSIM eval | 87 | 83 | 9 | 0 | 0 | 0 | 12 | 0 | 0 | 0 | 0 | 0 | 1 |
| GrhSIM compute 0-3 | 9965 | 9911 | 49 | 43 | 0 | 0 | 134 | 1492 | 26 | 263 | 46 | 0 | 2720 |
| GrhSIM commit 4 | 1498 | 1494 | 165 | 2 | 0 | 0 | 211 | 116 | 0 | 113 | 0 | 0 | 226 |
| GSIM subStep1 | 4661 | 4661 | 141 | 75 | 97 | 115 | 0 | 0 | 0 | 0 | 0 | 420 | 1768 |
| GSIM subStep0 | 12459 | 12457 | 479 | 235 | 762 | 334 | 0 | 0 | 0 | 0 | 0 | 824 | 4237 |

GrhSIM compute 0-3 合计源码约为 GSIM subStep1 的 `2.14x` 行数；文件字节数为 `771066 / 254220 = 3.03x`。这与 perf 里的 `4.57x` instruction gap 方向一致，但说明差异不仅是代码体积，还包括每条生成语句的间接性和宽字临时处理。

GrhSIM compute batch 分解：

| file | lines | `if` | `unlikely` | `supernode_active_curr_` | `value_u64_slots_` | `value_words_16_slots_` | `grhsim_value_storage_ref` | `_words_full` | `uint64_t` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `sched_0.cpp` | 3211 | 9 | 9 | 43 | 274 | 0 | 70 | 0 | 481 |
| `sched_1.cpp` | 2098 | 9 | 9 | 35 | 387 | 0 | 87 | 0 | 695 |
| `sched_2.cpp` | 1405 | 9 | 9 | 35 | 118 | 0 | 8 | 0 | 179 |
| `sched_3.cpp` | 3248 | 22 | 16 | 21 | 713 | 26 | 98 | 46 | 1365 |

`eval_compute_batch_3()` 既是 perf 第一热点，也是宽字热点：

| helper | refs in compute 0-3 |
|---|---:|
| `grhsim_and_words_full` | 14 |
| `grhsim_xor_words_full` | 14 |
| `grhsim_or_words_full` | 7 |
| `grhsim_assign_words_full` | 6 |
| `grhsim_not_words_full` | 5 |
| `grhsim_slice_words` | 112 |

二进制符号尺寸也支持这个判断：

| symbol | size bytes |
|---|---:|
| `SXsReal075RobVtypebufferLarge::subStep1()` | 12198 |
| `GrhSIM_XsReal075RobVtypebufferLarge::eval_compute_batch_0()` | 11905 |
| `GrhSIM_XsReal075RobVtypebufferLarge::eval_compute_batch_1()` | 7887 |
| `GrhSIM_XsReal075RobVtypebufferLarge::eval_compute_batch_2()` | 11072 |
| `GrhSIM_XsReal075RobVtypebufferLarge::eval_compute_batch_3()` | 21723 |
| GrhSIM compute 0-3 total | 52587 |

也就是说，GrhSIM input-low 实际要经过一组总尺寸约 `52.6 KB` 的 compute batch；GSIM 对照阶段则主要是一个约 `12.2 KB` 的 `subStep1()`。

## 6. GrhSIM 具体多了什么

结合 perf 与静态统计，当前可以把 “GrhSIM 比 GSIM 多的东西” 拆成几类：

1. **更多 host instructions**
   - input-low 对照中，GrhSIM retired instructions 是 GSIM `subStep1()` 的 `4.57x`；
   - IPC 和 branch miss 都不是主矛盾。

2. **更通用的 fixed-point batch 框架**
   - GrhSIM input-low 每次 eval 都进入 `eval()` fixed-point 框架，调度 4 个 compute batch，并用 `supernode_active_curr_` 维护 active mask；
   - GSIM 也有 `activeFlags`，但在 `subStep1()` 中是专用的两阶段静态 schedule，直接围绕 `activeFlags[i]` / `oldFlag` 展开。

3. **slot/ref 间接存取**
   - GrhSIM compute 0-3 中有 `1492` 次 `value_u64_slots_` 引用、`26` 次 `value_words_16_slots_` 引用、`263` 次 `grhsim_value_storage_ref` 引用；
   - GSIM `subStep1()` 没有这类通用 value slot/ref，更多是直接字段、局部 `uint64_t`、以及 `data$NEXT_*` / `meta$NEXT_*` 等 next-state 字段。

4. **宽字临时和 helper 仍在最热 batch**
   - `eval_compute_batch_3()` 占 GrhSIM input-low 第一热点；
   - 同一个文件里集中出现 `_words_full`、`value_words_16_slots_` 和大量 `slice_words`；
   - 这与 `NO0225` / `NO0226` 中 full-width helper 与 always-inline 带来显著收益的事实一致。

5. **输入 settle 与 high commit 的问题不同**
   - high phase 的 commit fanout 已在 `NO0233` 坐实，平均 `84.16` writes/vector，并触发第二轮 compute；
   - 但 input-low phase 没有状态写，仍然比 GSIM 对应 next-compute 阶段慢 `3.72x`，因此不能只把剩余 gap 归因于 commit fanout。

## 7. emitter 切入点评估

快速查看 `wolvrix/lib/emit/grhsim_cpp.cpp` 后，当前不建议把下一步简化成“给 `grhsim_value_storage_ref` 加 inline/always_inline”：

- helper 定义本身已经是 `inline T &grhsim_value_storage_ref(std::array<std::byte, N> &storage, std::size_t offset)`；
- 生成代码中的主要差异不是函数调用边界，而是状态和 value 被表示为通用 storage/slot，再在每个 supernode 中通过 offset/ref/slot 取出；
- GSIM 的对应代码则是更专用的 typed fields、局部 `uint64_t` 和 `$NEXT` 字段。

因此更可信的优化方向是改变生成代码形态：让 batch 内可局部化的 value/state 以 typed local 或 typed lane 形式流动，减少反复从 `value_u64_slots_`、`value_words_16_slots_`、`state_logic_storage_` 做通用搬运；而不是只改 helper 属性。

## 8. 结论与下一步

本轮更直接地回答了“GrhSIM 具体多了什么”：在 `VtypeBuffer` input-low / next-compute 对照中，GrhSIM 多的不是 branch miss，而是通用 GRH eval 框架带来的大量额外指令、slot/ref 间接访问、跨 batch active 调度，以及最热 batch 中的宽字临时/helper。

下一步优化优先级建议：

1. **优先处理 GrhSIM input-low compute 代码形态**：针对 `eval_compute_batch_3()`，做结构化 wide-lane scalarization / producer-consumer 融合，而不是字符串级 assign fusion；
2. **减少 value slot/ref 间接性**：对 batch 内局部只读/单写 value 尝试生成直接局部变量或 typed lane 引用，避免频繁通过 `value_u64_slots_` / `grhsim_value_storage_ref` 搬运；
3. **保留 high/commit fanout 线索**：commit fanout 是第二大问题，但它解释不了 input-low 阶段的 `3.7x`，应与 compute-code-shape 分线推进。
