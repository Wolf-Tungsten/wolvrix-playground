# NO0526 Event-pure legal level packing audit

日期：2026-07-13

## 1. Scope and final DAG closure

承接 [NO0524](./NO0524_event_pure_active_id_packing_audit_plan_20260713.md)，本轮完成 final supernode DAG 导出与
同 Kahn level 内的合法 packing 模拟；没有修改 production emitter。

fresh stop-after-activity-schedule 产物保持既有结构：

```text
supernodes / compute / commit  63,726 / 63,241 / 485
DAG edges                       528,622
Kahn levels                          97
max level width                    7,806
activity stats SHA256          e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77
final DAG SHA256               03f784a9c2642ea07e5850bcc52d303a1d64f8b76cb7196b0ea161079c4e373a
```

DAG ID `0..63240` 恰好是 compute supernodes，`63241..63725` 是 commit supernodes。按当前 `level-id` 算法重建
topo order 后，逐项核对 63,241 个 source marker：

```text
current edge-order errors       0
active-id mapping errors        0
batch mapping errors            0
reconstructed pure words/nodes/samples  107 / 856 / 125
```

最后一项与 NO0479/NO0483 的 production source 统计精确一致，证明 DAG node、emitter supernode、active ID、batch 和
profile row 已闭环，而不是近似名字匹配。

## 2. Bounds and blockers

现有 1,611 个 event-pure nodes、308 个 profile samples 分属 50 个 `(event_slot,event_edge)` keys：

| Packing scope | Full words | Covered nodes | Covered samples |
| --- | ---: | ---: | ---: |
| current production order | 107 | 856 | 125 |
| current contiguous-run upper | 133 | 1,064 | at most 195 |
| unrestricted per `(batch,event)` upper | 181 | 1,448 | at most 286 |

13 个不足 8 nodes 的 keys 合计 53 nodes/22 samples，无法独立组成 full word。unrestricted upper 仍剩 163 nodes；本轮
最终 legal candidate 剩 243 nodes/64 samples，即 level、batch、commit/word boundary 和 deterministic placement 相对无约束
上界再阻挡 80 nodes/42 samples。

## 3. Candidate progression

先模拟同 `(level,batch)` 内按 event key stable partition：得到 `167 words / 1,336 nodes / 238 samples`，但移动
29,966 个 compute nodes，最大 active-ID 位移 950。只使用完整同组 active words 的整体 packing 可到
`171/1,368/248`，仍移动 29,572 个节点。这两个结果只证明 legal headroom，因代码顺序扰动过大，不作为实现候选。

最终采用 targeted whole-word packing：

1. commit 位置、跨 level/batch 的 active word 和已有 pure words 全部锁定；
2. 只允许整个 8-bit word 都属于同一 `(Kahn level,current batch)` 的位置参与；
3. 对每个 event key 按 `floor(nodes/8)` 选择目标 word，优先选择当前已含最多同 key nodes 的 word；
4. 只交换补齐目标 word 所需的 event nodes 与被占节点，其余节点尽量原位保留；
5. 不读取 profile sample 数做排序或决策，profile 只用于事后验收。

结果：

| Metric | Current | Targeted | Delta |
| --- | ---: | ---: | ---: |
| pure words | 107 | 171 | +64 (`+59.81%`) |
| covered event nodes | 856 | 1,368 | +512 |
| covered samples | 125 | 244 | +119 |
| event-node coverage | `53.13%` | `84.92%` | `+31.79pp` |
| event-sample coverage | `40.58%` | `79.22%` | `+38.64pp` |

新增 119 samples 占全部 6,675 direct samples 的 `1.782772%`，通过 NO0524 的 `>=67/6675` 静态门槛。已有
856 nodes/125 samples 全部保留，新增覆盖为 512 nodes/119 samples，丢失为 0。

主要 batch 增量是 batch21 `+10 words/+16 samples`、batch24 `+8/+18`、batch41 `+3/+10` 和
batch20 `+3/+7`；没有 batch 的 pure-word 数减少。

## 4. Legality and blast radius

targeted candidate 的独立验收为：

```text
edge-order / permutation / level errors  0 / 0 / 0
commit moves / batch-membership errors   0 / 0
compute active words current/candidate   7,932 / 7,932
active-word set delta                    0
moved compute/event nodes                256 / 128
moved compute ratio                      0.404801%
changed active words                     127 (1.601109%)
max active-ID displacement               648
```

每个节点只在同一 current batch 内移动，因此 66 个 batch 的 supernode/ops/estimated-lines multiset 不变，batch count、每批
总 ops 与总 estimated lines 均不增加。这个结论是离线排列不变量；production 实现仍必须用两阶段构建重新证明 batch boundary
不漂移，不能直接把离线映射硬编码进 emitter。

threshold-2 code shape 会发生变化：

| Predicate form | Current batches/words/samples | Targeted batches/words/samples |
| --- | --- | --- |
| sparse volatile | `14 / 20 / 23` | `13 / 17 / 34` |
| dense direct | `8 / 87 / 102` | `19 / 154 / 210` |

因此总 bypass coverage 明显增加，但 volatile wrappers 减少 3、dense direct wrappers 增加 67。后续不能仅凭本篇静态 gate
宣称性能收益，必须重点检查 dense batch 的 O3 CFG、instructions、memory accesses 与 jumps。

## 5. Reproducibility and artifacts

审计脚本连续运行两次，以下输出 SHA256 保持一致：

```text
legal_level_summary.tsv          629d579ec4763df1e77353cbc087c7182f404496587960ece169b36bf41618b3
legal_targeted_words.tsv         0e2748bfec50cd77cf3da285c09457c5eac27a6ffcc646b0dffeca2413f4c01d
legal_targeted_moved_nodes.tsv   e0b94906e2fbb2106b15601059b7df136cab51e405da97a3ab9f432e406cb922
```

脚本与完整 TSV/JSON 位于 `build/logs/xs_perf/no0524/`；这些是 ignored analysis artifacts，不进入提交。

## 6. Decision and stop point

本轮 static audit 判定为 **go to a separate implementation plan**，但不是 production go：

- 只考虑 targeted whole-word 方案，放弃移动约 30k 节点的 broad stable partition；
- 后续实现必须默认关闭，先生成原始 batch/level 约束，再做 targeted reorder，最后统一重建 active IDs、fanout masks 和 batches；
- source gate 需证明 schedule stats、7,932 active-word set、66 batches、batch ops/lines 与功能入口不漂移；
- O3 object gate 必须覆盖新增 dense wrappers，随后才允许 100/10k/50k 功能回归与 quiet-load runtime A/B/A。

按当前指令，到此结束本次尝试；production 实现、测试与新一轮性能运行均未启动。

