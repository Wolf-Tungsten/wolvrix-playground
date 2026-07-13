# TNO0020 Sparse pure-event codegen and legal packing

记录日期：2026-07-13

来源范围：`NO0510..NO0526`，原始记录见 [NO0510](../grhsim_opt/NO0510_batch27_event_predicate_codegen_probe_plan_20260713.md) 至 [NO0526](../grhsim_opt/NO0526_event_pure_legal_level_packing_audit_20260713.md)。

状态：threshold-2 hybrid 已实现并通过 source/build/功能 gate；正式性能仍无有效 quiet 样本。targeted legal packing 静态 gate 通过，但 production 实现尚未开始。

## 1. Predicate codegen stabilization

batch27 的 local volatile hit copy 将 cliff 从 `+11,477 bytes/+1,783 instructions` 恢复到约 `-5/0`，证明根因是 outer predicate 向内部 event checks 的编译期传播。

但全 107 words 使用 volatile 会伤害 hot dense batches。按真实 plain/volatile objects 和动态 hit/miss 审计后，eligible-word count threshold 2 是唯一全指标过门方案：

```text
volatile words  20 / 107
sparse batches  14
dense direct    87 words
```

hybrid 相对 direct-state baseline 的 text/instructions/memory/jumps 为 `-2,049/-352/-225/-89`，相对 plain 再减少 `12,194/1,888/1,356/242`。

## 2. Implementation and fresh SimTop

子仓库实现只在 bypass 已开启且 batch eligible count 为 1..2 时生成 `const volatile bool hit`，dense 保持 direct predicate。synthetic 同批次 1/2/3-word 边界精确得到 volatile `1/2/0`。

fresh SimTop：

- 14 sparse batches/20 volatile/87 direct 精确闭合；
- 相对 plain 仅 14 sched files 改变；
- batch27 cliff 消失；
- 100-cycle、10k、50k checkpoints 与 baseline/plain byte-exact；
- terminal guest/cycleCnt/instr/PC 为 `50,001/49,996/73,580/0x80001312`；
- 无 mismatch/assert/profile leak/`input_fullpass_blocked`。

## 3. Runtime 数据边界

quiet survey 未满足 `>=99%`，正式 fixed-ASLR gate保持零有效样本。按明确允许的高负载 CPU28 初测，三次功能与 PMU schedule 均正确，但 baseline cycles 为：

```text
903.697B / 684.399B
A/A spread / mean = 27.62%
```

因此 hybrid cycle 结果作废。两次 baseline instructions 仅差 `0.000050%`，hybrid instructions 下降 `1.419647%`，只能作为 code-shape 辅助信号，不能换算成仿真提速。

## 4. Legal active-ID packing

final DAG 为 63,726 nodes/528,622 edges/97 Kahn levels；63,241 个 compute active-ID/batch 映射逐项闭合。当前 pure coverage：

```text
107 words / 856 nodes / 125 profile samples
```

targeted whole-word packing 只在同一 `(level,current batch)` 的完整 word 内移动节点，锁住 commit、跨组 words 与已有 pure words。结果：

```text
171 words / 1,368 nodes / 244 samples
new samples        119 / 6,675 direct = 1.782772%
moved compute nodes 256 / 63,241 = 0.404801%
changed active words 127 / 7,932
edge/order/level/batch errors 0
lost existing coverage 0
```

该候选通过静态 1% 门槛，但会把 dense direct words 从 87 墏到 154、sparse volatile words 从 20 变为 17，必须另做 production two-pass 实现、O3 dense-wrapper gate、功能和 quiet runtime。

## 5. 当前停止点

- threshold-2 hybrid：实现和功能正确，性能尚未在 quiet load 下确认；
- high-load A/B/A：仅证明噪声和 host instructions 方向，cycle 无效；
- legal packing：只有离线静态候选，尚未修改 production emitter；
- 后续文档应从本目录下一个 TNO 编号继续，原 `pdocs/grhsim_opt` 不再新增记录。

## 6. 规则审计与关键数据

记录类型：pure-event bypass 的 codegen stabilization 与阶段停止快照。单一议题边界是“如何消除 plain predicate cliff，并判断 production 候选是否已经具备可信 runtime 条件”。Legal packing 仅记录为该候选的下一可量化上界，尚未构成 production 实现；一旦实施必须新建 TNO。

### 6.1 Hybrid build/function

- threshold-2 仅让 14 个 sparse batches 的 20/107 wrappers 使用 volatile predicate，其余 87 保持 direct。
- 相对 direct-state baseline 的 O3 text/instructions/memory/jumps 为 `-1,950/-325/-227/-91`；相对 plain 为 `-12,095/-1,861/-1,358/-244`。
- 100/10k/50k 功能终点分别为 `101/100/96/0/0`、`10001/9996/458/0x800027c6`、`50001/49996/73580/0x80001312`；checkpoints 与 baseline/plain byte-exact。

### 6.2 CPU28 高负载 A/B/A

三轮均 fixed-ASLR、五事件 `100%` scheduled，并达到 guest/cycleCnt/instr/PC=`50001/49996/73580/0x80001312`：

| Sample | Host ms | Host cycles | Host instructions | CPU28/220 preflight idle |
| --- | ---: | ---: | ---: | ---: |
| baseline1 | 329,632 | 903,696,969,842 | 166,888,353,356 | `95.65%/92.64%` |
| hybrid | 351,791 | 965,083,345,014 | 164,519,086,973 | `95.65%/95.65%` |
| baseline2 | 244,335 | 684,398,522,260 | 166,888,269,841 | `98.00%/94.98%` |

Baseline cycles 极差达到均值 `27.617791%`，故任何 cycles/walltime delta 均无效；host instructions 的 A/A 差仅 `0.000050%`，hybrid `-1.419647%` 只作为 code-shape 辅助信号。正式 quiet gate 仍为 0 个有效性能样本。

### 6.3 未实现的静态上界

Legal level packing 只移动 256/63,241 compute nodes，使 pure words/samples 从 `107/125` 增到 `171/244`，新增 `119/6675=1.78%` direct samples。该结果没有 generated C++、功能周期或 runtime 数据，不能与 hybrid A/B/A 合并为性能结论。来源见 [NO0518](../grhsim_opt/NO0518_simtop_sparse_pure_event_build_codegen_gate_20260713.md)、[NO0521](../grhsim_opt/NO0521_simtop_sparse_pure_event_50k_functional_gate_20260713.md)、[NO0525](../grhsim_opt/NO0525_sparse_pure_event_high_load_aba_20260713.md) 与 [NO0526](../grhsim_opt/NO0526_event_pure_legal_level_packing_audit_20260713.md)。
