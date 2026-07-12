# NO0409 Deferred activation cost audit plan

日期：2026-07-12

## 1. Problem

[NO0404](./NO0404_global_compute_machine_source_attribution_gate_20260712.md) 的同周期 O3 profile 显示，GrhSIM
change tracking 为 603 samples，GSim 为 313 samples，约有 `7.25B` instructions 净超额；其中 GrhSIM
`changed_accumulate` 单独占 159 samples / `3.975B` instructions。当前 compute emitter 会为至少两个 source
共享的 successor 建立 `grhsim_any_changed_<supernode>_<group>`，每个 source 先 OR 到 group，组尾再统一传播
activation。

当前算法不是最初的 exact-fanout grouping。它按“拥有完全相同 source set 的 active IDs”构造最多 16 个
partial-overlap groups，因此一个 changed source 可以同时更新多个 groups。构组阶段只检查 source count >= 2，
没有比较新增 accumulate 与省下的 activation machine cost。需要先确定 current grouping 是净收益、净开销，还是
仅有部分 group 值得保留。

## 2. Exact inputs

本轮复用以下已经闭合的相同版本数据，不先重跑仿真：

- NO0357 direct-state production 的 66 个 generated compute sources / O3 objects；
- [NO0399](./NO0399_direct_scalar_locality_runtime_profile_50k_gate_20260712.md) 的 63,726-row direct 50k
  supernode fire；
- [NO0404](./NO0404_global_compute_machine_source_attribution_gate_20260712.md) 的 5,590 个 fixed-period compute
  samples，以及 66/66 `.text` byte-identical line-table objects。

所有 generated-source parser 必须闭合 group declaration、source update、supernode marker 与 final activation use；有
无法解析项时单列，不用估算值填补。

## 3. Static and dynamic attribution

按 supernode 重建每个 group 的 source set 和 target mask，至少输出：

- group 数、source-update 数、每 source 的 group multiplicity；
- group source count / target count 分布；
- `updates * direct fire`、final activation statements / words `* direct fire`；
- 同一 source 连续更新多个 groups、多级 source-set subset 和 exact-fanout 可合并范围；
- batch / supernode top 分布，防止把全局分散成本误当成单点热点。

三种形态使用同一成本口径比较：

1. current partial-overlap grouping；
2. 旧版 exact-fanout grouping，只合并完整 successor mask 相同的 sources；
3. no-deferred 上界，每个 source 直接传播自己的 successor mask。

source 语句数只作为上界；最终决策必须使用 production O3 machine realization。

## 4. Machine gate

把 NO0404 的 159 个 `changed_accumulate` samples 和 304 个 `activation_propagation` samples 映射到 group、source、
target word及候选形态。先检查 current partial-overlap 中哪些 accumulate 是 exact grouping 也需要的，哪些仅由 partial
overlap 引入；再对代表 hot batches 生成 exact/no-deferred 临时版本并用相同 `clang++ -std=c++20 -O3` 编译。

代表 object 必须比较目标 compute symbol 的 text bytes、static instructions、stack operands，并以 disassembly 确认
减少的是实际 OR/move/spill，而不是源码行被 Clang CSE。临时版本只用于 gate，不先进入默认源码。

## 5. Decision

只有候选同时满足以下条件才实现默认关闭的 emitter switch并进入 SimTop 功能/runtime A/B：

1. 可移除 O3 samples 或代表 O3 指令外推量达到 direct compute `139.750B` instructions 的 `1%`；
2. 至少覆盖 GrhSIM-vs-GSim change-tracking 净超额 290 samples 的 `20%`；
3. activation machine work 没有以同等或更大幅度回增；
4. 候选不扩大 generated text / stack pressure，且不是单一 batch 的布局现象。

未过门槛则保留 current grouping，不做全局 branchless changed-check，不重复
[NO0083](./NO0083_branchless_changed_activation_experiment_20260509.md) 或
[NO0084](./NO0084_active_word_accumulator_negative_20260509.md) 的负向路径。

