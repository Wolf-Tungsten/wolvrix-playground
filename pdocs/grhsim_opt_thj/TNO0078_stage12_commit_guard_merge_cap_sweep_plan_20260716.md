# TNO0078 Stage 12 commit guard merge-cap sweep plan

日期：2026-07-16

状态：规划 current-default NO0300 上的 commit guard-event merge-cap 中间点；以 default `4096` 分区为 byte-exact 基础，只合并同 event 的相邻完整 commit node，扫描 `8192/16384/32768` 的 SN、compute-to-commit BAE、CPP 与 fixed-ASLR 50k。

## 1. 为什么检查中间 cap

Stage 11 的 equal-load compute swap exact 集合为空，见 [TNO0076](./TNO0076_stage11_equal_load_swap_probe_implementation_and_production_result_20260716.md)。当前 schedule 的 commit 侧仍有一个范围很小、历史未覆盖的结构变量：

```text
commit_event_keys=450
commit_event_key_runs=485
commit_supernodes=485
compute_commit_value_pairs=262225
```

当前 guard-event 路径先按 normalized event key 和 canonical guard key 形成 atomic bucket，再按 first-seen guard 顺序装箱。代码把 merge limit 写成：

```text
min(maxOpInCommitSupernode, 4096)
```

因此外部显式设置 `8192/16384` 目前没有作用。

历史端点已经说明该变量值得补扫：

- cap `1024` 把 commit SN 从 `515` 增到 `721`，20k runtime 回退 `20.2%`；
- cap `4096` 的 guard-event packing 在当时 50k 比 emit-only 基线快 `3.48%`；
- 每 event 单一无 cap commit SN 又比 `4096` 快约 `1.04%`，但最大 CPP 达 `160MB/199万行`；
- `8192/16384` 从未在 SimTop commit cap 上测试过。

这些旧数据不是当前 NO0300/fixed-ASLR 性能结论，只说明 `4096` 与无 cap 之间存在尚未量化的 compile/runtime 折中区间。历史细节见 [`NO0134`](../grhsim_opt/NO0134_commit_supernode_cap1024_build_positive_runtime_negative_20260521.md) 与 [`NO0200`](../grhsim_opt/NO0200_commit_shared_guard_group_emit_plan_20260615.md)。

## 2. Current production 分片

现有 stats 没有逐 commit node/event 列表；从 current generated CPP 的 sink 注释和 event guard 可恢复出 35 个 extra run 全部来自 3 个 event key：

| Event key | 当前 runs | Extra | Atomic oversize node | 其余 normal ops/runs |
| --- | ---: | ---: | ---: | ---: |
| posedge clock | `28` | `27` | `42937` | `108563 / 27` |
| clock + core reset | `8` | `7` | `18439` | `28608 / 7` |
| clock + reset_sync | `2` | `1` | `5130` | `2556 / 1` |

三类 normal runs 都已经在 `4096` 下装满到不能直接两两合并。CPP 可见 sink 给出的 full-event 重复 root-input gain 下界为 `2208`；另有 `1542` 个 emitter 省略 op 注释的 memory writes，因此全量 root-input gain 只能约束在 `[2208,3741]`，不能当作 exact compute-to-commit BAE gain；实际收益只认 activity-schedule 完整 recount。

## 3. Order-preserving coarsening

直接把第一层 guard bucket 的装箱 cap 改成 `8192` 会重新选择切点。node 数通常下降，但某个 value 可能被新切点从一个旧 node 拆到两个新 node，compute-to-commit pair 不保证单调。

Stage 12 使用更强约束：

1. 无论 candidate cap 多大，先按当前规则生成 byte-exact `4096` baseline commit nodes；
2. `maxOpInCommitSupernode <= 4096` 的行为完全不变；公开 pass 继续把 `0` 视为非法值；
3. 仅当显式 cap `>4096` 时，在每个 event 内按原顺序扫描 baseline nodes；
4. 只有相邻完整 baseline node 的 op 数之和不超过 candidate cap 时才 concat；
5. 不拆 baseline node，不跨 event，不改变任何 node 内 op/vector order；
6. 原子 guard/ordered-write bucket 即使超过 `4096` 仍保持完整，只有整个 baseline node 能被安全合并时才参与更高层 coarsen。

这样 candidate commit partition 是 baseline partition 的 order-preserving coarsening。每个 candidate input-value set 是若干 baseline set 的 union，因此 commit input roots、compute-to-commit value pairs、commit DAG edges 与 total BAE 理论上只能不变或下降。

## 4. Correctness gate

Focused fixture 使用同 event 的四个 guard bucket、`9000` 个 sink op 和两个 compute-defined data value：

- default 与显式 cap `4096` 必须 schedule/summary byte-exact，并形成三个 commit node；
- cap `6144` 必须只把完整连续 baseline node 合成两个 commit node；
- candidate op ordinal vector 必须精确等于 baseline vectors 的有序 concat；
- sink multiset、event key、guard 邻接和 inputValues 必须保持；ordered group 的原子性与 priority 顺序继续由既有独立 memory-write fixtures 覆盖；
- compute-to-commit pairs 应从 `3` 降到 `2`，commit input roots 从 `13` 降到 `10`；
- default/explicit `4096` summary 和 schedule byte-exact。

Production validators 至少要求：

- sink op 全覆盖、无重复；
- candidate 每个 node 只含单一 normalized event key；
- candidate partition 可精确还原为连续 baseline node concat；
- node 内 op order byte-exact，ordered-write group 连续且 priority 顺序不变；
- inputValues 由 candidate ops 精确重建；
- compute partition、state-read sets、graph ops/values 与 source clone 数不变；
- actual compute-to-commit pairs/BAE 不高于 baseline；
- final DAG/topo 与完整 schedule validators 通过。

## 5. Structure sweep

从 Stage 10/11 使用的同一 post-stats 恢复，显式锁定 current-default NO0300：

```text
dp_segment_penalty_ppm=1000000
post_dp_refine_policy=off
kahn_level_pack_policy=off
final_fanin_pullback_policy=off
all clone/direct/bypass/packing experiments=off
final_topo_policy=level-id
```

扫描：

```text
commit merge cap = 4096 / 8192 / 16384 / 32768
```

记录 commit SN/runs、compute-to-commit pairs、total BAE、DAG、boundary values、commit op 分位数/max、generated source/最大 CPP、object/ELF `.text` 和 build tail。`4096` 必须与 canonical explicit-off SHA byte-exact。

## 6. Runtime gate

该方向允许温和结构或静态指标退化，不用单一 BAE 阈值提前停止。只要 candidate 没有明显 CPP/TU 爆炸且结构变化真实，就完成 fixed-ASLR SimTop 100/10k，再做 50k quiet A/B/A。鉴于 Stage 8/10 已多次出现 socket 方向反转，正式结论至少覆盖 NUMA0/NUMA1；最终仍以 current-default NO0300、ASLR off 的 50k cycles/instructions/frontend/backend 为准。

默认保持 `4096`，只有跨 NUMA 证据支持时才修改默认值。
