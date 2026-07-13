# TNO0002 VtypeBuffer codegen and active-framework diagnosis

记录日期：2026-07-13

来源范围：`NO0224..NO0239`，原始记录见 [NO0224](../grhsim_opt/NO0224_vtypebuffer_codegen_hotpath_compare_20260709.md) 至 [NO0239](../grhsim_opt/NO0239_no_propagate_fullpass_probe_20260709.md)。

状态：宽字 helper 的局部收益已落地；剩余主要成本定位到 input settle 中 always-active 仍执行的 changed/active 框架。

## 1. 直接代码差异

VtypeBuffer 的 GSim hot path 主要是 64-bit lane 标量直线代码；GrhSIM 则生成：

- 1024-bit `std::array<uint64_t,16>` 临时值；
- runtime width/truncation；
- generic `grhsim_*_words<16>` 调用；
- changed compare、slot writeback 与 active propagation；
- fixed-point batch dispatch。

因此热点不是单一 helper，而是宽字 materialization 与调度框架叠加。

## 2. 宽字 helper 实验

| Experiment | Result | Decision |
| --- | --- | --- |
| full-width helper | VtypeBuffer 长窗口 `-11.93%`，helper self `13.95% -> 9.11%` | 正向保留 |
| full-width `always_inline` | VtypeBuffer 再降约 `3%`，FTQ/Tage raw 再降 `12.36%/10.56%` | 正向保留 |
| assign fusion | Vtype `-0.14%`、FTQ/Tage 回退 | 撤回 |
| aligned slice direct lane | object/binary SHA 不变 | 编译器已完成，不实现 |
| manual producer/slice fusion | object 变大，runtime `+3.61%` | 撤回 |
| compute-supernode size 64/32/256 | 全部回退 | 停止调参 |

这些结果说明朴素字符串改写和 producer-consumer 搬运会扩大 live range；真正有效的是消除 generic helper 的宽度与调用边界。

## 3. low/high phase 的真实语义

GrhSIM low/high eval 时间最初约为 `50.22%/49.78%`，但 edge probe 进一步拆出：

```text
fall-only    33.8 ns/vector
input-low  1001.6 ns/vector
```

所以 low phase 的一半工作不是下降沿顺序逻辑，而是输入变化后的组合 settle；high phase 通常是 commit 加 commit-activated compute 两轮。

与 GSim `subStep1()` 相比，GrhSIM input-low 的 runtime/instructions/cycles 分别约为 `3.72x/4.57x/3.37x`。剩余约 2 倍差距主要是执行工作量，不是 IPC。

## 4. dynamic fire 与框架成本

动态插桩显示 GrhSIM 的 38 个 compute supernodes 在 input-low 几乎全部 fire；总 fire 还低于 GSim，但源码工作量 proxy 为 `2.76x`，changed/active propagation proxy 为 GSim active set 的 `21.55x`。

临时 no-propagate full-pass probe 删除 137 条 compute propagation 后：

```text
low-only runtime        -35.22%
compute0-3 instructions -30.69%
```

该 probe 不是正确实现，但证明 always-active settle 中 active/change propagation 是可观的真实 hot cost。即使完全删除这部分，GrhSIM 仍约慢 `2.5x`，剩余来自 slot/ref 与大 supernode payload。

## 5. 阶段结论

- full-width + inline helper 是已验证的局部优化；
- empty-round skip、slice/fusion 与 partition size 调整均无效；
- low/high 各半不是“下降沿也做同样工作”；
- 下一步应把 unsafe no-propagate 上界收敛为有语义门禁的 input/posedge full-pass specialization。

## 6. 规则审计与关键数据

记录类型：连续 root-cause 诊断总结。单一议题边界是“VtypeBuffer 及相邻 clocked 小负载的额外成本究竟来自宽字 helper，还是 active/change 框架”。宽字代码调整、phase 拆分和 no-propagate probe 是回答该问题的连续证据，不作为后续独立实验容器。

### 6.1 Helper 收益复测

以下 raw run 均执行 `200002` 个 component cycles：

| Workload | 原始 ratio | Full-width ratio | Inline ratio | Inline GrhSIM vs full-width | Inline GrhSIM vs baseline |
| --- | ---: | ---: | ---: | ---: | ---: |
| FTQ | `1.624x` | `1.517x` | `1.342x` | `-12.36%` | `-17.02%` |
| Tage | `1.666x` | `1.626x` | `1.453x` | `-10.56%` | `-14.37%` |
| VtypeBuffer | `2.204x` | `2.018x` | `1.912x` | `-3.55%` | `-13.59%` |

其中 full-width 相对原始 GrhSIM 的收益分别为 `-5.31%/-4.26%/-10.41%`；inline 相对 full-width 再改善 `-12.36%/-10.56%/-3.55%`。数值来自 [NO0225](../grhsim_opt/NO0225_full_width_words_helper_ab_20260709.md) 与 [NO0226](../grhsim_opt/NO0226_full_width_words_always_inline_ab_20260709.md)。

### 6.2 Phase 与框架成本

VtypeBuffer `2,000,002`-cycle phase run 的主要原始计数为：

| Path | Wall (ms) | Host cycles | Host instructions |
| --- | ---: | ---: | ---: |
| GrhSIM input-low | 1,968.019 | 7,553,560,167 | 22,926,353,068 |
| GSim `subStep1` | 529.496 | 2,240,344,854 | 5,017,494,843 |
| Ratio | `3.72x` | `3.37x` | `4.57x` |

在 `200002`-cycle low-only repeat-5 probe 中，正常传播 median 为 `203.267ms`，禁用传播为 `131.734ms`，上界收益 `-35.22%` 且 checksum 一致。该 probe 故意破坏通用传播语义，只用于证明框架成本，不是可保留优化。详见 [NO0234](../grhsim_opt/NO0234_vtypebuffer_phase_specific_gsim_delta_20260709.md) 与 [NO0239](../grhsim_opt/NO0239_no_propagate_fullpass_probe_20260709.md)。
