# TNO0042 Stage 4 SimTop common-owner probe

记录日期：2026-07-14

状态：Stage 4 no-mutation probe 在 SimTop 上 PASS；stats 与 current-default raw identity，得到 strict 冲突选择前 `691` 个 exact eligible、`1,382` 条 projected removed pairs 上界。

## 1. 配置与 identity

```text
enable_local_shared_compute=true
local_shared_compute_max_clones=0
local_shared_compute_common_owner_policy=probe
local_shared_compute_max_fanout=2
local_shared_compute_max_width=64
post_dp_refine_policy=off
kahn_level_pack_policy=off
stop_after_activity_schedule=true
```

candidate 与 current-default stats SHA256 均为：

```text
e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77
```

raw JSON `cmp=0`；graph ops/values 仍为 `7,204,108 / 6,833,009`，local shared clones 为 `0`。因此 probe 确认没有 graph mutation、二次 rewrite 或 schedule/schema 漂移。

## 2. 顶层漏斗

| Metric | Count |
| --- | ---: |
| scanned compute ops | `4,386,595` |
| pre-user-guard eligible | `3,642,914` |
| reject kind / shape / width | `24,816 / 0 / 66,883` |
| reject intent attr / side effect / declared-port | `312 / 0 / 651,670` |
| invalid or non-compute user | `828,395` |
| distinct user ops not exactly two | `2,551,118` |
| consumer node count `0 / 1 / 2 / >2` | `95,143 / 2,409,732 / 241,182 / 68,462` |
| source owner invalid / is consumer | `0 / 69,450` |
| source owner third common / third non-common | `167,780 / 16` |

`rejected_consumer_nodes=194,009` 不能直接代表 common opportunity；重新从完整 user/owner 漏斗统计后，third common 为 `167,780`，clean builder 路径下 third non-common 仅 `16`。

## 3. Third-common strict 投影

| Gate | Buckets |
| --- | --- |
| common owner singleton / multi-op | `63,265 / 104,515` |
| source/left/right/any intent-or-indivisible | `0 / 0 / 0 / 0` |
| result exact boundary both/left/right/neither | `167,780 / 0 / 0 / 0` |
| operand locality both/left/right/neither | `846 / 3,196 / 1,126 / 162,612` |
| capacity both-pass/left-fail/right-fail/both-fail | `151,277 / 5,873 / 7,553 / 3,077` |
| exact eligible upper bound | `691` |
| projected removed result pairs | `1,382` |

真正的瓶颈是双边 operand locality：`167,780` 个 third-common 中只有 `846` 个 source 的全部 operands 对两个 consumer 都已 local/existing-boundary。再叠加 singleton、双边 cap 与基础 guard，剩 `691` 个单项候选。

`1,382 / 1,983,923 = 0.06966%`，只是 result boundary pair 的理论上界；strict selection 还会因共享 target累计 cap、source/target 角色与候选依赖冲突继续减少。

## 4. Eligible 形态

eligible kind：

```text
kSliceStatic 585
kAnd          52
kNot          47
kReduceAnd     3
kConcat        2
kAssign        1
kLogicNot      1
```

eligible result width：

```text
1       344
2-8     212
9-32     83
33-64    52
```

eligible operand total bits：

```text
1           48
2-4         15
5-16       272
17-64      252
65-256      64
257-1024    30
>1024       10
```

`kSliceStatic` 占 `84.7%`；另有 40 个候选 operand bits 超过 256，说明 Stage 5 必须观察 generated expression/code size，不能只按窄 result width 判断复制成本。

## 5. Cost 与结论

common-owner probe 用时 `4,487 ms`；现有 conservative clone scan 在 `maxClones=0` 下用时 `4,386 ms`，发现原 108 个机会但 `planned/applied=0/0`。activity schedule `176,339 ms`，全脚本 `355,791 ms`；wall `5:57.60`，peak RSS `28,327,008 KiB`，exit `0`。

691 的机会量仍远低于总 compute ops，但高于 Stage 3 的 108，且 projected pair 上界约为其 25.6 倍。按用户要求，下一阶段实现 conflict-aware common-owner `strict` true clone，并继续跑 SimTop structure/generated-code/50k；默认始终保持 off。

原始产物：

```text
build/logs/xs/xs_wolf_grhsim_build_activity_stage4_common_owner_probe_20260714.log
build/xs_activity_stage4_common_owner_probe_20260714/grhsim/grhsim_emit/activity_schedule_supernode_stats.json
```
