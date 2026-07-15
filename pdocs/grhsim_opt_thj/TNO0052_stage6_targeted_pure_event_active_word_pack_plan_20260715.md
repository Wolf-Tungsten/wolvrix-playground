# TNO0052 Stage 6 targeted pure-event active-word pack plan

日期：2026-07-15

## 1. 目标与基线

Stage 1 至 Stage 5 已覆盖 supernode partition、同 Kahn level packing 与局部 clone，但近期候选在 quiet 50k 上均未形成正收益。Stage 6 暂时不再修改 supernode partition，而是在 emitter 最终分配 active ID 时，尝试把同一 event expression 的 pure compute supernode 聚成完整 8-bit active word，以扩大现有 threshold-2 pure-event bypass 的覆盖。

唯一性能基线仍是当前仓库默认生成配置，即 NO0300、ASLR 关闭。BAE、DAG、boundary 与生成代码指标只作为分析口径；轻微退化不阻止运行 SimTop，最终取舍由 fixed-ASLR SimTop 50k 决定。

本阶段承接 [TNO0020](./TNO0020_sparse_pure_event_codegen_and_legal_packing_20260713.md) 与 [NO0526](../grhsim_opt/NO0526_event_pure_legal_level_packing_audit_20260713.md)。离线 targeted 候选的预期是 pure words `107 -> 171`、新增 direct profile samples `119/6675`，移动 `256/63241` 个 compute supernode、改变 `127/7932` 个 compute active words；production 实现必须重新独立证明这些数字，不能硬编码离线映射。

## 2. 方案边界

新增默认关闭的 emitter policy：

```text
pure_event_word_pack_policy = off | probe | targeted
```

- `off`：完全沿用当前 emitter 路径，不运行 planner；默认值。
- `probe`：构造并验证候选，只写 host-side stats，不采用新 active order；生成的 C++/header 必须与 `off` 字节一致。
- `targeted`：只在全部硬门禁通过后采用候选；要求 pure-event word bypass 同时开启，否则没有运行收益而只有布局风险。

首版预算为 moved supernodes `<=5000 ppm`、changed words `<=20000 ppm`。profile sample 数只用于事后验收，不参与选择和排序。

## 3. Two-pass emitter 流水线

第一遍使用 session 原始 topo order 完整构建 baseline model 与 compute/commit batches，并冻结 batch/word 槽位。planner 只允许在以下范围交换：

1. active word 是完整 8 个 compute slots；
2. word 内节点处于同一 final DAG Kahn level 和同一 baseline batch；
3. commit、partial、跨 level、跨 batch、已有 pure word 全部锁定；
4. 对每个 exact event expression，稳定选择当前同-key 节点最多的目标 word，仅交换补齐该 word 所需的 event 节点与 victim；
5. event key、word index、supernode ID 构成确定性 tie-break。

`targeted` 采用后，将候选 permutation 写入 emitter-local topo copy，再从空 model 完整调用 `buildModel`。不能只 patch `activeIdBySupernode`，因为 boundary fanout、input/state heads、direct-state frontier 与 memory-row activation 都包含 active ID。

第二遍不重新用贪心规则决定 batch 边界，而是根据第一遍冻结的 batch/word slots 重建成员与成本。这样切断“packing 依赖 baseline batch、batch 又依赖 packed word cost”的循环；任何 batch 成员或成本不变量失败都直接拒绝，不迭代、不静默 fallback。

## 4. 硬门禁

实现和 SimTop scan 至少验证：

1. active IDs 是全 supernode 严格 permutation，正反映射互逆；
2. final DAG 每条边仍满足 producer active ID 小于 consumer active ID；
3. commit supernode 的 active ID、顺序、word/bit 和 batch 全部不变；
4. 每个 moved node 的起止位置均属于同一 `(Kahn level, baseline batch)`；
5. batch 数、phase、逐 batch member set、op count、estimated lines 与 active-word set 不变；
6. baseline 已有 pure words 不丢失，新增目标 word 最终恰好 8 个同一 exact event expression 节点；
7. rebuilt boundary/input/state/memory active-ID vectors 均在范围内且保持 sorted-unique；
8. moved-supernode 与 changed-word PPM 不越预算；
9. `off` 与当前默认 source/artifacts 字节一致，`probe` 除 stats/log 外与 `off` 字节一致；
10. activity-schedule 的 SN、compute/commit partition、DAG、BAE、boundary 统计保持 identity。

## 5. 执行顺序

1. 实现 policy、planner、frozen-batch rebuild、validators 与 `grhsim_emit_stats.json` 统计；
2. 补齐 C++ focused tests、Python/native option 校验和 XS 环境变量透传；
3. 在 current-default checkpoint 上跑 `probe`，核对 production 机会量与 NO0526 离线结果；
4. 跑 `targeted` source/build gate，重点观察 sparse volatile 与 dense direct wrapper 分布、O3 `.text`、instructions 和 jumps；
5. 依次完成 fixed-ASLR 100/10k/50k 功能门禁；
6. 机器满足 sibling idle `>=99%` 时，用原子 gate-to-run 执行 quiet 50k A/B/A。先比较 threshold-2 hybrid 与 hybrid+packing；若正向，再与当前默认 NO0300 比较。

## 6. 当前状态

本篇只冻结实现方案与门禁。production 代码、SimTop scan 和 50k 性能尚未完成；policy 保持默认 `off`。
