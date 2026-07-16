# TNO0079 Stage 12 commit guard merge-cap implementation and structure scan

日期：2026-07-16

状态：完成 order-preserving two-level commit coarsening、focused correctness/独立终审和 current-default NO0300 的 `4096/8192/16384/32768` 结构扫描；default raw identity，三个高 cap 候选均减少 commit SN、compute-to-commit pairs、total BAE 与 DAG，全部进入 full CPP/O3/50k。

## 1. 实现

按 [TNO0078](./TNO0078_stage12_commit_guard_merge_cap_sweep_plan_20260716.md)，没有增加新 option；继续使用既有 `maxOpInCommitSupernode`。guard-event 路径现在分两层：

1. 始终以 `min(requested cap, 4096)` 按现有 event/guard first-seen 顺序生成 baseline clusters；
2. requested cap `<=4096` 时直接导出，默认路径不变；
3. requested cap `>4096` 时，在每个 event 内按顺序 greedily concat 完整 baseline cluster；
4. 不拆 baseline cluster、不跨 event、不改变 cluster 内 sink op vector；
5. baseline cluster 自身超过 requested cap 时仍原子单独导出。

关闭 `commitGuardEventBuckets` 的旧路径继续直接按 requested cap 切分，不受两级逻辑影响。公共 scheduling 文档同时澄清：commit cap 是 atomic bucket 之间的 packing 上限，不是单个 guard/ordered bucket 的 correctness 硬上限。

## 2. 结构单调性

高 cap candidate 是 default commit target partition 的 order-preserving quotient：若 baseline node target 为 `c`，candidate 只把若干连续 `c` 映射到一个新 target。对每个 value 去重后：

```text
candidate compute-to-commit pairs <= baseline pairs
candidate commit input roots       <= baseline roots
candidate commit DAG edges         <= baseline edges
candidate total BAE                <= baseline BAE
```

compute partition、compute-to-compute pairs、graph、boundary value 集合和 state-read sets 不变。这个证明不外推到 runtime；合并仍会改变 commit 函数边界、activation 粒度和链接布局。

## 3. Focused gate

新增同 event、四 guard、`9000` sink 的 fixture。实际测试要求：

- default 与显式 `4096` schedule/summary byte-exact；
- `4096` 三个 baseline commit node 在 `6144` 下只合并为两个；
- candidate flattened sink ordinal 和全局执行顺序与 baseline exact；
- 每个 candidate cluster 精确等于连续完整 baseline clusters 的 concat；
- 测试内模拟 direct high-cap guard recut，并要求其结果与 two-level partition 不同；
- 重复 compute-defined data 的 commit targets `2 -> 1`，总 compute-to-commit pairs `3 -> 2`；
- commit input roots `13 -> 10`，defined input union 与全部 sink operands 闭合；
- 既有 oversized guard bucket 和 ordered memory-write atomic/priority fixtures 继续通过。

最终 focused build/CTest `1/1 PASS`，`0.15s`；submodule/parent `git diff --check` 通过。独立只读终审未发现代码 blocker，并确认默认 identity、同 event/连续 concat、oversize/ordered 原子性和 vector move 生命周期正确。

## 4. Production 口径

四点从 Stage 10/11 的同一 post-stats 恢复：

```text
input SHA256=165f5c58e06d0d8a483c49d80733f5a7a211bc27772dac5b1608b0c177a0b573
dp_segment_penalty_ppm=1000000
post_dp_refine_policy=off
kahn_level_pack_policy=off
final_fanin_pullback_policy=off
all clone/direct/bypass/packing experiments=off
final_topo_policy=level-id
```

显式 `4096` stats SHA 为 canonical：

```text
e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77
cmp=0
```

因此实现/refactor 没有改变 current-default NO0300。

## 5. Structure scan

| Commit cap | Total SN | Commit SN/runs | Compute-commit pairs | Total BAE | DAG | Commit input roots | Commit p99/max |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `4096` | `63726` | `485` | `262225` | `1983923` | `528622` | `262268` | `4096 / 42937` |
| `8192` | `63709` | `468` | `261628` | `1983326` | `527990` | `261654` | `8184 / 42937` |
| `16384` | `63700` | `459` | `260164` | `1981862` | `527331` | `260181` | `16339 / 42937` |
| `32768` | `63696` | `455` | `259982` | `1981680` | `526921` | `259995` | `16380 / 42937` |

相对 `4096`：

| Commit cap | SN delta | Compute-commit pair delta | Total BAE delta | DAG delta |
| ---: | ---: | ---: | ---: | ---: |
| `8192` | `-17` | `-597` (`-0.228%`) | `-597` (`-0.030%`) | `-632` (`-0.120%`) |
| `16384` | `-26` | `-2061` (`-0.786%`) | `-2061` (`-0.104%`) | `-1291` (`-0.244%`) |
| `32768` | `-30` | `-2243` (`-0.855%`) | `-2243` (`-0.113%`) | `-1701` (`-0.322%`) |

三点均保持：

```text
compute supernodes=63241
compute-compute pairs=1721698
boundary values=1000463
event keys=450
sink ops=218994
source clones=2045861
graph ops/values=7204108/6833009
topo edges=10150909
```

实际 runs 精确复现计划预估的 `485 -> 468/459/455`。`32768` 的 commit p99 仍约 `16k`，且三点 max 都没有超过 baseline 已有的 oversized atomic node `42937`；当前没有出现历史无 cap 的超大单 node/TU 明显风险。

## 6. 决策

三个 candidate 都是严格结构正收益，且绝对机会从 `597` 到 `2243` pairs，不能只挑一个点提前裁剪。下一步对 `8192/16384/32768` 全部完成 full emit、O3/link 和 100/10k；检查 generated source、最大 CPP、object/ELF text 与 build tail 后，再进入 NUMA0/NUMA1 fixed-ASLR 50k。

默认继续保持 `4096`，最终只由跨 NUMA runtime 决定是否修改。

## 7. 产物

```text
build/xs_activity_stage12_commit_guard_merge_cap{4096,8192,16384,32768}_20260716/grhsim/grhsim_emit/activity_schedule_supernode_stats.json
build/logs/xs/xs_wolf_grhsim_build_activity_stage12_commit_guard_merge_cap{4096,8192,16384,32768}_20260716.log
```
