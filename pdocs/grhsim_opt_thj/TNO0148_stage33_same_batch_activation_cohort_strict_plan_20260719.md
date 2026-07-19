# TNO0148 Stage 33 same-batch activation cohort strict plan

日期：2026-07-19

状态：Stage32 已用 current-default 50k profile 证明 `252/252` 个 exact-source cohort 在
ordinary batch 入口全等、逐 member body fire 全等、出口全清。Stage33 计划实现独立的
`same_batch_activation_cohort_policy=strict`，C++ 默认暂时保持 `off`；只有未插桩
SimTop 50k 功能与严格 page-local 双 NUMA walltime 均闭合后，才重新判断是否作为 C++
native default 打开。

## 1. 唯一基线与输入

control 固定为实际待测 commit 上 fresh 生成的仓库 C++ 默认配置：NO0300、ASLR 关闭、
commit cap=`8192`、native hybrid 默认开启，其余 activity/emitter 实验 policy 不在 XS 脚本
中私设。Stage33 只显式增加 strict policy 和下面的 current profile：

```text
build/logs/xs_perf/stage32_same_batch_cohort_probe_20260719/fire_50000.tsv
sha256=308ae8ef5192feca7036eb9ccbc86a02bc2139c081e1759a46173dec88cc053a
bytes=1155117
compute rows=63241
ignored commit rows=468
```

Stage32 current-profile replay 的 production 绝对目标是：

```text
cohorts=252 members=902 ops=88334
control_bae=3619 projected_bae=1450 saved=2169
control/projected entries=342/252
control/projected chunks=257/252
50k member body fire=9270152
50k projected guard tests saved=6854019
```

这些结构值只用于闭合实现契约；端到端采用结论只看 SimTop 50k
`Host time spent` walltime，不用 cycles、instructions、BAE 或 guard-test 投影代替。

## 2. Production manifest gate

Stage32 原先只硬校验 cohort11，不足以授权 strict 改写全部 252 组。Stage33 对 graph symbol
`SimTop` 固定完整 manifest fingerprint。fingerprint 必须采用显式、跨平台稳定的字节序列和
算法，例如 little-endian field encoding + FNV-1a，并按最终 cohort/member 顺序覆盖：

- cohort ordinal、batch、完整 source `ValueId`、source SN/batch 与 profile fire；
- 每个 member 的 SN、原 active ID、op count 与 profile fire；
- cohort/member/op/BAE/entry/chunk 的上述全局绝对计数。

任一字段、顺序或 fingerprint 不符时 production strict 必须 fail-closed；不能重新扫描出一批
“相似 cohort”后继续改写。generic focused fixture 可以不使用 SimTop fingerprint，但仍执行
全部结构不变量检查。

## 3. Strict lowering 契约

先在原始 final EmitModel 上完成全部 cohort 选择和互斥校验，再一次性构造 strict overlay：

1. 保留原 schedule、batch、active ID 和 follower holes；cohort member 必须互不重叠，follower
   不得成为另一 cohort leader，cohort 间不得有隐含同 batch 依赖。
2. 从 ordinary boundary fanout 与 ordinary initial compute seed 中删除 follower bits；同时
   断言 input/state/direct-state/memory/event 等其他 activation writer 不含 follower。
3. strict fanout 必须统一用于 direct changed propagation、deferred group 构造和
   `DeferredActivationEmitContext`，不能让 deferred flush 再写回 follower。
4. ordinary leader guard 命中后，按原 batch/topo 顺序恰好执行全部 member payload；原 follower
   guard/body 跳过。fullpass 仍逐 SN 无条件执行原 body，commit 完全不改。
5. 每个 member payload 保留自己的原 `currentActiveId/currentWordIndex`。leader word 使用真实
   `activeWordFlags`；后续原 word 使用各自独立 local accumulator，并在该 word cohort payload
   完成后 OR 回对应 global word，禁止把跨 word propagation 写回 leader byte。
6. 初版保持 ordinary/split dispatch 与 clear mask 不变，`full_active_word_consume` 不参与；若
   helper/split 无法证明 payload exactly once，则 production strict fail-closed，而不是静默
   产生部分 strict。
7. strict 生成物不包含 Stage32 runtime counter、TSV 或 probe marker；C++ 默认仍为 `off`，
   Python/native/XS 只稀疏转发显式 `strict`。

## 4. Correctness gate

最终 focused fixture 已覆盖 24 个 compute supernode：同一 active word 内两个独立 cohort
`8..12` 与 `14..18`，第二个 cohort 跨 word1/word2，前后有 non-cohort node，且 SN18 的
changed propagation 继续激活下游 SN19。default/off artifact 完全相同；default 与 strict
functional harness 均实际检查两组 cohort 输出、下游输出、initial seed、输入变化和无变化
eval。strict generated-source 断言覆盖两个 leader、8 个 follower payload、跨 word accumulator
及 follower guard 消除；`full_active_word_consume=true` 的 strict 入口也有显式 fail-closed
负向测试。

同 cohort 与 deferred-forward 的独立 focused CTest 均通过，但当前 fixture 没有把 strict
overlay 与 posedge/fullpass 正向路径或 forced helper/split 变体组合在同一 harness 中；这些
路径由 production validator 的 fail-closed 检查和既有 fullpass/helper 测试覆盖，不能把它们
描述成 strict 正向等价性证明。默认/off 必须保持完整 artifact identity，strict 必须保持
activity schedule、SN/active ID/slot/layout identity。

production 阶梯为：

1. final core rebuild + editable binding reinstall；
2. current-profile strict fresh emit，核对 252/902/88334 与完整 fingerprint；
3. O3/archive 和独立 difftest link；
4. target-node first-touch 独立 `/dev/shm` inode，`taskset + numactl --physcpubind/--membind +
   setarch x86_64 -R` 的 100/10k/50k 功能；
5. fresh same-commit default control 与 strict 分别使用独立 per-node inode，通过 whole-node
   30 秒 pre/runtime gate 后做 balanced ABBA/BAAB；任何 rejected sample 不进入结论。

## 5. 默认与后续队列

strict 的默认决定只按每 node 和合并后的 absolute walltime、相对差与组内 spread 作出；小幅
方向反转或收益落在噪声内时保持 `off`。若稳定正向，再把默认直接改在 C++ emitter 中，XS
保持 sparse，不通过脚本为 XiangShan 单独指定。

Stage33 完成后仍需按同一 current-default/fresh ELF 协议重测 Stage7+ 待决项：Stage8
DP p050、DP p200 与 Stage10 fanin strict；三者共用本轮 fresh control，旧 cap4096、旧
direct/bypass ELF 只作历史证据，不能进入新的 formal A/B。
