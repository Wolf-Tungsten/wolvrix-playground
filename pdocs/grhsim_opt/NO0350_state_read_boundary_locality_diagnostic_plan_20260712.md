# NO0350 State-read boundary locality diagnostic plan

日期：2026-07-12

## 1. 触发

[NO0349](./NO0349_fixed_aslr_latest_instruction_profile_codegen_compare_20260712.md) 将 latest GrhSIM/GSim
profile excess 的 `71.43%` 近似归因到 compute。最大 compute8 没有单指令热点；其 `21,069` 个 scalar
state-read 物化中，`19,565` 个来自 logEndpoint。现有 NO0283 same-supernode/same-state alias 已把 timer
物化从 `29,686` 降到 `431`，但不同 logEndpoint states 不能使用同一 alias 规则。

生成代码显示 commit state change 当前经过两级传播：

1. commit 更新 state 后激活包含相应 read port 的 state-read supernode；
2. state-read supernode 比较持久 result slot 与 state、更新 slot，再激活真实 consumer supernodes。

一个 state-read supernode 可能聚合多个不同 states。任一 state 改变都会执行该 supernode 中的全部操作，因此
大量彼此无关的 slot compare/update 可能形成 NO0349 看到的分散 compute 指令。直接删除 slot 或把结果改成局部
变量没有足够语义依据：consumer 可能被其他输入独立激活，且 mixed supernode 还可能包含本地组合计算。

## 2. 诊断实现

在 `grhsim-cpp` emitter 增加默认关闭的 `state_read_locality_stats` 诊断，由
`WOLVRIX_GRHSIM_STATE_READ_LOCALITY_STATS=1` 或同名 emit attribute 开启。开启时在 output directory 生成：

```text
grhsim_state_read_locality.tsv
```

每个 register/latch read result 输出一行，至少包含：

- source operation/value/state symbol、width 与 scalar/wide；
- source supernode、schedule batch、该 supernode 的总 op/read op 数；
- result 是否 materialized、是否复用 canonical slot、是否需要 tracked change；
- boundary fanout 数；
- graph users 在 source supernode、同 batch 其他 supernode、跨 batch 中的分布；
- unique user supernode/batch 数，以及 source supernode 是否只含 state reads。

诊断只读取既有 graph/model/schedule 映射，不改变 `materializedValues`、active IDs、batch packing、storage layout 或
generated C++。synthetic emitter 回归检查 TSV schema、read rows、same-state alias 和 mixed-supernode 分类。

## 3. SimTop 分析

从与 NO0300 相同的 pre-reg-to-mem checkpoint fresh emit，保持：

```text
reg_to_mem_ordered_writes=True
reg_to_mem_decoded_write_storage=True
final_topo_policy=level-id
max_op_in_compute_supernode=108
sched_batch_target_count=64
```

将 locality TSV 与 NO0311 已有 NO0300 50k `supernode_fire.tsv` 严格按 supernode ID 连接，报告：

- 全局及 `timer/logEndpoint/cpu` 前缀的 read/materialized/alias/fanout 数；
- pure state-read 与 mixed supernode 的数量、动态 fire、`fire * read_ops` 估算扫描工作；
- compute8 及全局 top estimated-scan supernodes；
- 同 supernode、同 batch、跨 batch consumer 分布。

`fire * read_ops` 只是候选排序指标，不等同于 retired instructions；最终收益仍须由无插桩 fixed-ASLR perf stat
确认。

## 4. 候选门槛

只有当 pure state-read forwarding supernodes 占可观动态扫描工作时，才进入“commit 直接激活 consumer”候选；
该候选还必须证明初始化、register/latch commit、multiple readers、same-state aliases、consumer 独立激活和
output/waveform/event/phase-crossing值的行为不变。protected 或 mixed cases 先保守回退。

若主要工作来自 mixed supernodes，则不做 direct-activation 重写，转而评估 per-state guard 或调整 state-read
聚类。任何行为改动都另立实现、结构、功能和 runtime gate 文档。
