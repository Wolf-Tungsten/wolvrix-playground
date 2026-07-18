# TNO0128 Stage 26 fire-aware terminal pushforward plan

记录日期：2026-07-18

状态：计划在当前 cap8192/C++ native-hybrid 基线上，用 Stage19 50k runtime fire TSV 过滤 terminal pushforward strict 候选。TNO0125 已证明静态 strict 的 `128` 个 move 会让 walltime 回退；TNO0127 的 commit-cap 复测也显示局部结构收益不能替代动态 workload 证据。本阶段保持默认 off，只增加显式 profile 开关。

## 1. 动机和 profile 原值

Stage19 `fire_50000.tsv` 的格式为 `supernode_id phase f`，compute supernode 为 `0..63,240`，每个 `f` 是整个 50k 窗口的 dispatch 次数。将 TNO0125 的 128 个 strict candidate 与该 profile 对齐得到：

```text
target_fire > source_fire: 45/128
target_fire = source_fire: 50/128
target_fire < source_fire: 33/128
all-candidate moved-op fire delta: +337,980
target_fire <= source_fire retained: 83/128, fire delta -447,548
source_fire >= 1,000 and target_fire <= source_fire: 27/128
```

原始 profile：

```text
build/logs/xs_perf/activity_stage19_table_runtime_profile_20260717/fire_50000.tsv
```

这些 dispatch 次数是 work proxy，不替代 50k `Host time spent`；最终仍需 fresh page-local 双 NUMA ABBA/BAAB walltime。

## 2. 实验开关和 fail-closed 语义

新增 C++ 默认关闭的 profile path 与最小 source-fire threshold：

```text
final_terminal_pushforward_profile_path = ""
final_terminal_pushforward_profile_min_source_fire = 0
```

当 path 非空时，必须严格校验当前 compute supernode 每个 ID 恰有一条合法 `compute` profile 行；commit 行允许存在但忽略。文件不可读、格式错误、重复/缺失 compute ID 或数值溢出均 fail-closed，不能把缺失值当作 0，也不能执行 mutation。合法 profile 只保留 `source_fire >= min_source_fire` 且 `target_fire <= source_fire` 的 candidate。profile path 为空时 off/probe/strict 行为和 session identity 完全不变。

## 3. gate 和候选阶梯

先做 profile parser/focused test，再从同一 post-stats checkpoint 生成：

1. cap8192 baseline/off；
2. 普通 strict（128 move）作为对照；
3. profile strict，`min_source_fire=1000`；必要时补 `min_source_fire=10000`。旧 128-move 子集中两档分别保留 27/18 个，但 profile gate 位于全量候选入列和冲突选择之前，production selected 数不能预设，必须以新 probe 的绝对值为准。

每档记录 absolute activity stats、选中/拒绝计数、source/target fire、BAE/边界值/bytes、generated source/ELF 和功能终点。若 profile 结构或 fail-closed validator 不通过，停止 runtime；否则使用与 TNO0124/0125 完全相同的 fresh inode、`taskset`+`numactl --physcpubind/--membind`、whole-node gate、`setarch -R`、perf migration=0 和 ABBA/BAAB 协议。

## 4. 默认决策

profile strict 只有在两 NUMA balanced walltime 稳定改善时才可能成为显式推荐；即使改善，也不直接改 C++ 默认，除非后续独立 profile/无 profile workload 均证明收益。cycles、instructions、task-clock 和 fire delta 只作诊断，最终 headline 始终是 `Host time spent`。
