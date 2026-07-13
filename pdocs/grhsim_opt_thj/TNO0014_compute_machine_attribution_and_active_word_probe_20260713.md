# TNO0014 Compute machine attribution and active-word probe

记录日期：2026-07-13

来源范围：`NO0403..NO0414`，原始记录见 [NO0403](../grhsim_opt/NO0403_compute1_machine_source_attribution_plan_20260712.md) 至 [NO0414](../grhsim_opt/NO0414_local_active_word_consume_machine_gate_20260712.md)。

状态：系统排除多个低覆盖候选；full active-word consume 的 generated-copy O3 probe 达到工程门槛，进入默认关闭实现。

## 1. Scope-correct machine attribution

GrhSIM 66/66、GSim 284/284 line-table objects 均保持 production `.text`。全量 5,590/3,170 compute leaf samples 显示：

```text
payload + runtime 对 compute excess 的解释 82.77%
changed/activation/writeback                 11.65%
```

activation 与 writeback 本身接近持平，没有单一 framework 类覆盖 20%。

## 2. 被停止的候选

| Candidate | Dynamic/machine upper | Decision |
| --- | ---: | --- |
| same-condition mux reuse (`len>=8`) | compute `0.1433%` | 不恢复旧 mask reuse |
| full-width OR/AND copy/spill | compute `0.3936%` | 不做 fusion |
| deferred multi-group activation net saving | compute `0.849%` | 保留 current grouping |
| unknown runtime-frame unresolved | compute `0.984%`，copy-like `0.250%` | 不改 helper |

这些结果也避免重复 NO0227/NO0236 等已证伪的 fusion 路线。

## 3. Active-word dispatch 机会

dispatch 样本中 GrhSIM 独有 local clear+restore 约 35 samples。generated-copy 对 7,921/7,932 compute words 做 immutable consume：

```text
aggregate instructions  -0.958%
bytes                   -0.946%
branches                -1.650%
66/66 batches instructions 均下降
dynamic word-block projection 1.90%..2.22% compute
```

该结果通过 direct compute 1% 门槛。工程化范围进一步收窄为完整 8-bit compute word；partial/commit words 保持旧协议。

## 4. 阶段结论

compute gap 的主体仍是 payload/runtime，不是单一 changed/activation helper。多数局部模板不足 1%；唯一达到门槛的是 full active-word clear/restore 消除，因此进入独立实现和 SimTop gate。

## 5. 规则审计与关键数据

记录类型：compute residual 候选筛选 gate。单一议题边界是“在 latest direct profile 中，哪个通用 compute framework 类真正超过 1% machine-level 门槛”。本篇只做 production-identical attribution 与 generated-copy O3 probe，没有运行候选 emu，因而没有 guest cycle、walltime 或 runtime speedup。

基础 profile 为 `5,590` 个 GrhSIM compute leaf samples；66/66 GrhSIM 与 284/284 GSim O3 objects 均通过 `.text` identity：

| Candidate | Dynamic/machine upper bound | Decision |
| --- | ---: | --- |
| same-condition mux reuse | direct compute `0.1433%` | 停止 |
| full-width OR/AND copy/spill | `0.3936%` | 停止 |
| deferred activation net saving | `0.849%` | 停止 |
| unresolved runtime frame | `0.984%` | 停止 |
| full active-word consume projection | `1.904%..2.224%` | 进入独立实现 |

Full 66-batch generated-copy O3 计数从 `14,599,944` 降到 `14,460,047` instructions，即 `-139,897/-0.9582%`；branches/memory/stack operands 同时下降 `1.6497%/0.7869%/1.4295%`。这是静态入选信号，不是仿真加速结论。详见 [NO0404](../grhsim_opt/NO0404_global_compute_machine_source_attribution_gate_20260712.md) 与 [NO0414](../grhsim_opt/NO0414_local_active_word_consume_machine_gate_20260712.md)。
