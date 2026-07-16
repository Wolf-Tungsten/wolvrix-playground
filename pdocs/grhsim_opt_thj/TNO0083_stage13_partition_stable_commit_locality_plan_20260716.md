# TNO0083 Stage 13 partition-stable commit locality plan

记录日期：2026-07-16

状态：定位 Stage 12 high-cap 导致全部 compute CPP 改写的确定性根因；规划由 activity schedule 导出 pre-merge 4096 canonical commit locality group，使 commit execution partition 可以 coarsen，而 materialized value slot locality 不随之全局重排。

## 1. Stage 12 暴露的问题

Stage 12 保持 graph、compute SN/op 顺序、materialized value 集合与各 typed slot count 不变，但 baseline 到 cap8192 的 `1,000,032` 个唯一 ValueId-to-slot 映射中有 `635,632` 个改号，占 `63.56%`。66 个 compute CPP 因而全部变化，最终 cycles/frontend 再次出现 socket 方向反转。

根因位于 emitter 的 `buildStateAnchoredValueOrder()`：

1. 每个 supernode 收集其中所有 register/latch read/write state；
2. 取这些 state 的最大 `state.slotIndex` 作为整个 supernode 的 `stateAnchor`；
3. 把该 anchor 赋给节点内每个 op 的每个 materialized operand；
4. 最终排序首先按 `stateAnchor` 降序，再按 first-read、read-count、graph-order 排序并分配 typed slot。

Stage 12 把多个完整 4096 baseline commit cluster 合并后，后一簇较大的 state offset 会重新锚定前一簇 operand。flattened commit op/operand 顺序不变，所以后三个排序键逐 Value 不变；唯一变化就是 supernode-level anchor。这不是统计相关性，而是全局 slot 改号的确定性来源。

## 2. 为什么不直接改成 per-op anchor

只让 commit 使用 per-operation state anchor 可以快速做到 partition-independent，但也会改变 default 4096 内部原有的 locality：当前同一个 4096 commit SN 的全部 operand 共享该节点最大 anchor。这样重测会同时混入“新 locality policy”和“commit merge”，不能隔离 Stage 12 的真实收益。

本阶段要求 default 4096 generated layout 保持不变，高 cap 只消除由跨 baseline cluster 合并造成的额外 anchor 污染。

## 3. 数据契约

新增 activity-schedule session 数据：

```text
ActivityScheduleCommitLocalityGroupByOp = vector<uint32_t>
session key = commit_locality_group_by_op
```

- vector 按 `op.index - 1` 索引，非 commit op 使用 invalid group；
- group ID 在整张 graph 上单调分配，不在每个 event 内重置；
- guard-event 模式在 4096 baseline cluster flush 时给其中每个 sink op 标 canonical group；
- requested cap `>4096` 只合并实际 execution cluster，locality group 不合并；
- cap `<=4096` 时 canonical group 与实际 commit SN 一一对应；
- 关闭 guard-event 模式时 canonical group 继续等于其直接 chunk；
- fixed commit partition / clone rebuild 从当前 graph 的 sink partition 重新生成映射，不携带旧 OperationId。

该映射只需保存在私有 rewrite build 并在 pass 结束时导出，不进入 compute 后处理。

## 4. Emitter 使用

Emitter 可选读取 locality group map：

1. compute supernode 继续使用当前 supernode-level anchor，完全不变；
2. 对每个 canonical commit locality group，按组内 state write target 计算最大 anchor；
3. 扫描实际 commit batch/op operand 时，使用该 op 所属 canonical group 的 anchor；
4. first-read、read-count、graph-order 与最终 sort/rebuild 均不改；
5. session 缺失或映射无效时回退现有 supernode anchor，保持兼容。

对 default 4096，canonical group 就是实际 supernode，计算应逐项等价。对 high cap，多个 execution supernode 子组仍保持各自 baseline anchor，因此 slot mapping 应与 default 相同。

## 5. Correctness gate

Transform focused：

- 扩展现有四-guard/9000-sink fixture；
- default 与显式 4096 group map byte-exact；
- cap6144/high-cap 每个 sink op 的 canonical group 与 4096 相同；
- 每个 merged commit SN 只能覆盖一个或多个完整、连续 locality group；
- commit op 覆盖、ordered priority 与 oversize 原子性继续闭合。

Emitter focused：

- 构造 split/merged commit schedule 和相同 canonical group map；
- 断言 materialized value 集合、typed slot count 和 ValueId-to-slot 映射完全相同；
- 缺失 metadata 的旧 session 继续走原行为；
- malformed/duplicate/uncovered commit mapping 给出明确诊断或安全 fallback，不允许越界。

Production identity：

- current-default NO0300、cap4096 stats 继续为 canonical SHA；
- 从同一 post-stats full emit 的 default generated source 与 Stage 12 control byte-exact；
- high-cap slot mapping changed count 必须为 0；
- compute op 顺序和 ValueId-to-slot 表达式保持一致；compute-to-commit BAE 降低必然会删除或重定向 activation target/mask，因此不要求整个 compute CPP byte-exact；
- commit active flags/functions 及 compute 侧对应的 activation update 变化属于预期，除此之外的 compute code 漂移需单独解释。

## 6. Runtime 计划

结构 stats 理论上与 Stage 12 完全相同，不重复用 BAE 门槛裁剪。`8192/16384/32768` 均做 full emit、O3/link、100/10k；只要 default identity 和 slot-stability gate 通过、CPP/TU 无明显膨胀，三档都进入 current-default NO0300、`setarch x86_64 -R` 的双 socket 50k。

正式序列仍用每个 socket 的前后 control 包夹并按实际 perf 中点插值。若 stable high-cap 仍无跨 socket 收益，则停止 global cap；下一阶段使用已枚举的 event/merge gain 做小预算定向选择：

- clock-only cap8192：保留 `505/597` pair gain；
- top-4 clock merge：`314` pair gain，只改变 4 个 commit function；
- pair gain `>=25` 的 9 条 merge：`461` pair gain；
- 单独 core-reset 16384 merge：`1093` pair gain，用于判断 ordered-write shared-input 大收益是否值得更大函数。

默认保持 `4096`，只有 partition-stable candidate 的跨 NUMA 50k 证据支持时才修改。
