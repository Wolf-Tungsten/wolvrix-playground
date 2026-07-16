# TNO0084 Stage 13 anchor-only production gate and order correction

记录日期：2026-07-16

状态：Stage 13 第一层 canonical commit locality-group anchor 完成 focused correctness 和 SimTop full emit。default 4096 全源码 identity 闭合，high-cap slot 漂移从约 63.6% 降至 `1.26%..1.54%`，但严格 changed=0 门槛未通过；未进入 O3/50k，根因定位为 commit `firstReadSequence` 仍依赖 actual merged topo，转入 canonical group topo-order 修正。

## 1. 第一层实现

Activity schedule 新增按 `op.index - 1` 索引的 `commit_locality_group_by_op`：

- guard-event 路径在 pre-merge、最多 4096-op 的 baseline cluster 上分配 graph-global dense group；
- requested high cap 只合并 execution cluster，不合并 locality group；
- fixed partition / clone rebuild 从当前 graph 重新生成映射；
- emitter 对完整有效的映射按 group 聚合 write-target state anchor；
- 任一 commit op 未覆盖、越界或 group invalid 时，整张 graph 回退旧 supernode anchor。

Focused transform/emitter fixture 覆盖 default/4096 map identity、high-cap 完整连续 group、split/merged typed-slot mapping、metadata 缺失/畸形 fallback 和 legacy anchor 可区分性：

```text
transform-activity-schedule  PASS   0.14 sec
emit-grhsim-cpp             PASS 292.78 sec
```

## 2. Production default identity

从 canonical same-poststats 重新 full emit cap4096：

```text
input post-stats SHA  165f5c58e06d0d8a483c49d80733f5a7a211bc27772dac5b1608b0c177a0b573
schedule stats SHA    e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77
emit stats SHA        9dd1bdddd01606507b2e3425917f260ca3ac8c5b88c55fa21408bffb17080a8b
```

新 cap4096 与 Stage 10 same-post current-default control 的 154 个 `.cpp/.hpp` 文件集合、每个文件内容和总 bytes `1,377,532,061` 全部 byte-identical。新增 metadata 在 default 下确实等价于旧 supernode anchor，没有改变 NO0300。

## 3. High-cap 严格 slot gate

三档结构 stats 与 Stage 12 对应档逐字节一致，但 typed ValueId-to-slot 并未完全稳定：

| cap | raw mapping | unique/common ValueId | changed | missing/conflict | total CPP bytes |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 4096 | `1,000,264` | `1,000,032` | `0` | `0` | `1,376,984,664` |
| 8192 | `1,000,264` | `1,000,032` | `12,623` | `0` | `1,376,752,848` |
| 16384 | `1,000,264` | `1,000,032` | `13,066` | `0` | `1,376,598,787` |
| 32768 | `1,000,264` | `1,000,032` | `15,363` | `0` | `1,376,520,397` |

cap8192 相比 Stage 12 的 `635,632` 个改号已减少 98%，且所有 residual 都保持同一 typed kind；这证明 canonical anchor 生效，但不能把“改善很多”写成 partition-stable 完成。三档 compute CPP 集合都仍为 66 个，byte identity 均为 `0/66`。

原始产物：

```text
build/xs_activity_stage13_partition_stable_commit_guard_merge_cap{4096,8192,16384,32768}_full_20260716/
build/logs/xs/xs_wolf_grhsim_build_activity_stage13_partition_stable_commit_guard_merge_cap{4096,8192,16384,32768}_full_20260716_emit.log
```

## 4. Residual root cause

最终 slot 排序键为：

```text
(stateAnchor desc, firstReadSequence asc, totalReads desc, graphOrder asc)
```

第一层只固定了第一项。`buildStateAnchoredValueOrder()` 仍按 actual `scheduleBatches -> commit supernode -> op` 扫描 read：

- compute op comment 序列 `1,910,892` 项逐位置相同；
- cap16384 的 visible commit op 两边均为 `217,452`，multiset 相同；
- 但只有 `3,690` 个 commit op 保持相同序列位置，首差在 1,134；
- high-cap 合并改变 commit DAG readiness/topo，进而改变只在 commit 首次读取的 Value 顺序；
- 这些 Value 的 `firstReadSequence` 变化继续重排 `12k..15k` 个 typed slot，并使约 451 个 compute SN 跨 batch/TU 边界。

因此本轮没有进入 O3/link、功能或 50k；否则仍会把 commit topo 引发的 layout 重抽样混入性能归因。

## 5. Order correction

第二层增加 canonical commit locality group order：

1. final materialization 保持 actual high-cap schedule 不变；
2. 以相同 compute SN 加 4096 locality groups 构造 pseudo-baseline commit DAG；
3. group incoming edge 从组内 sink operand 的 defining compute SN 精确重建；
4. 使用现有 `level-id` topo 得到 canonical group order；
5. emitter 按 actual schedule 扫描 compute reads，再按 canonical group order、组内 baseline op order扫描 commit reads一次；
6. `stateAnchor/firstReadSequence/totalReads/graphOrder` 四项全部对齐 default；任一 map/order metadata 不完整则整表 legacy fallback。

新增 focused gate 必须证明 split native 与 metadata erase 全源码 identity、merged+canonical map/order 与 split slot mapping 一致、坏 order 回退。Production 重新生成四档，目标仍是 default 全源码 identity 和 high-cap `changed=0`，不降低门槛。
