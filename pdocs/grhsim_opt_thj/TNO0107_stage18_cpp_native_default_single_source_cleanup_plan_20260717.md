# TNO0107 Stage 18 C++ native default single-source cleanup plan

记录日期：2026-07-17

状态：计划。Stage 18 只清理 `activity-schedule` 中与 `ActivityScheduleOptions` 完全同值的 XS 隐式参数，并修正 Makefile 对 commit cap `4096` 的无条件高层环境注入。C++ 数值、XS 平台特有配置、emitter batching 和 generated behavior 均不修改；实现后必须以完整 JSON/source byte identity 和显式实验 override spot tests 证明零行为变化。

## 1. 动机与唯一默认源原则

[TNO0090](./TNO0090_stage14_native_hybrid_default_adoption_plan_20260717.md) 到 [TNO0105](./TNO0105_stage17_full_regression_gate_20260717.md) 已逐步把 Stage14 hybrid、Stage15 sibling fusion 和 Stage16/17 active-mask policy 改为 C++ native default 加 XS sparse override。继续在 XS 脚本里重复一组与 C++ 完全相同的 activity-schedule 数值，会形成两个默认源：后续 C++ 默认调整时，XS 仍被旧脚本参数钉住，日志又难以区分平台选择和历史重复值。

Stage 18 的原则是：

```text
通用默认          -> ActivityScheduleOptions / C++
XS 平台特有选择   -> XS 显式传参
用户实验值        -> WOLVRIX_XS_GRHSIM_* sparse override
```

本阶段是配置所有权清理，不是新的 schedule 或 emitter 优化。不会借机修改任何 C++ 默认数值，也不会根据尚未完成的 Stage7+ runtime 队列晋升其它实验选项。

## 2. 迁为 sparse 的 ActivitySchedule 参数

当前 XS clean default 与 C++ `ActivityScheduleOptions` 完全相同的参数族为：

| family | C++/当前 XS default |
| --- | --- |
| commit | `max_op_in_commit_supernode=4096`、`commit_guard_event_buckets=true` |
| declared boundary | `declared_value_compute_node_boundary=false` |
| local shared compute | `enable=false`、fanout `2`、width `64`、clones `4096`、cloned-op `5000 ppm` |
| common owner | policy `off`、clones `4096`、cloned-op `5000 ppm` |
| Stage8 DP | `dp_segment_penalty_ppm=1000000` |
| Stage11 post-DP/swap | policy `off`、rounds `1`、moves `4096`、moved-op/regression 各 `10000 ppm` |
| Kahn pack | policy `off`、moves `4096`、moved-op/regression 各 `10000 ppm` |
| Stage10 fanin | policy `off`、node ops `8`、value width `64`、min gain `3`、moves `4096`、moved-op `5000 ppm` |
| final topo | `level-id` |

脚本应只在对应 `WOLVRIX_XS_GRHSIM_*` 环境变量实际存在时，把该 key 加入 `activity-schedule` kwargs；未设置时不传，由 C++ struct 提供默认。每个 policy 的预算项必须保持独立 override：例如只设置 `POST_DP_REFINE_MAX_MOVES` 时只传该预算，不能顺带重新注入 policy 或其它默认。

config log 对省略项应标明 `cpp-default`，显式值标明 `xs-override`；不要为了打印数值再次在 Python 中复制 C++ 常量。`path=top_name` 仍是必填目标，不属于默认清理。

## 3. 必须保留的 XS 平台配置

以下值与 C++ 默认不同，或已被 full-XiangShan codegen 明确使用，本阶段继续显式保留：

| parameter | XS | C++ | 决定 |
| --- | ---: | ---: | --- |
| `max_op_in_compute_supernode` | `108` | `128` | 保留 XS `108` |
| `max_op_in_compute_node` | 跟随 XS compute cap，默认 `108` | `8192` | 保留依赖关系 |
| `split_oversize_compute_nodes` | `true` | `false` | 保留 `true` |
| `split_oversize_compute_node_max_ops` | 跟随 XS compute cap，默认 `108` | `0` sentinel | 本阶段保留显式 `108`，不利用 sentinel 重构 |
| batch max ops/lines/target | `2048/8192/64` | `512/4096/0` | 三元组整体保留 |
| emit parallelism | `4` | host hardware concurrency | 保留资源上限 `4` |
| storage-ref aliases | `0` | `1` | 保留 XS `0` |

batch 三元组不能拆开清理：`target_count=64` 会根据 total ops/lines 动态抬高另外两个上限，只省略其中一个可能改变 batch/file layout。`sched_batches_per_cpp=1`、waveform/perf、full-active/profile/word-pack 等 emitter 选项虽然也在审计中出现，但不属于本阶段范围，保持现状，避免把 activity default ownership cleanup 与 emitter 环境优先级问题混在同一提交。

Stage14 的 `direct_single_writer_state_reads` 和 `pure_event_compute_word_bypass`、Stage15 sibling family、Stage16/17 `active_mask_gap_pack_policy` 已在高层未设置时不传 attribute；Stage 18 不重复改动这些已闭合路径。

## 4. Makefile commit-cap 条件导出

当前 Makefile 同时存在：

```make
XS_WOLF_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE ?= 4096
```

以及 recipe 中无条件：

```text
WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE="$(XS_WOLF_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE)"
```

因此仅把 Python 改成“环境变量存在才传”并不能形成 sparse default；Makefile 会在每次 full XS emit 时制造一个看似显式的 `4096`。

Stage 18 应让 `XS_WOLF_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE` 在用户未设置时保持 empty/undefined，并只在非空或可证明显式设置时向 recipe 注入高层环境变量。必须保留现有显式接口：

```bash
make ... XS_WOLF_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE=8192
```

仍应精确传成 XS override。默认 `make` 则不导出该变量，最终由 C++ `4096` 决定。command echo 也要区分 `cpp-default` 与显式值，不能继续打印一个并未传入的伪默认。

本阶段不处理 Makefile 的 `sched_batches_per_cpp=1` 注入；它属于后续 emitter default ownership 议题，避免扩大当前变更范围。

## 5. 行为 identity gate

必须在同一 current native-hybrid/cap4096 checkpoint 上形成 legacy-explicit control 与 sparse candidate。除 config source 日志允许从数值变成 `cpp-default` 外，以下全部 byte-exact：

1. `activity_schedule_supernode_stats.json`；
2. `grhsim_emit_stats.json`；
3. activity schedule session-derived JSON/manifest；
4. generated artifact 文件集合；
5. 全部 `*.cpp/*.hpp/Makefile` source manifest；
6. schedule function/file order、active ID、value slot 和 commit locality metadata。

当前 canonical checksum 可作为额外交叉检查：

```text
activity_schedule_supernode_stats.json
  e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77

grhsim_emit_stats.json
  9dd1bdddd01606507b2e3425917f260ca3ac8c5b88c55fa21408bffb17080a8b

155 generated source manifest
  bfcf0b9d4554b5da76bcc0f08c733a8bb9f9f6b96c50150c51cdded162853cda
```

若任一 generated artifact 变化，先定位是遗漏的 XS 平台参数、Makefile 空值传播、bool 空字符串语义还是 kwargs 编译差异；不能把 source 漂移视作“仅配置清理”继续提交。source byte-exact 后 O3/SimTop 会是同一程序，本阶段无需用 runtime 噪声替代更强的 identity 证明。

## 6. 显式 override spot tests

默认 identity 之外，至少覆盖：

- Make dry-run/default：不出现 commit-cap 高层注入；显式 Make `8192` 时精确出现一次；
- Stage12：cap `8192` 且 guard 继承 C++ `true`，以及 cap `8192` + explicit guard `false`；
- Stage8：DP penalty `500000` 与 `2000000`（p050/p200）；
- Stage10：fanin `probe/strict` 及独立 max-node/min-gain/move/PPM override；
- Stage11：post-DP `strict` 与 `swap-probe`，并验证单独 budget override 不隐式注入其它 key；
- Kahn policy 与预算的独立 override；
- local-shared/common-owner 的显式 enable/policy/budget；
- final topo 非默认值；
- Stage14 explicit `0/0` rollback、Stage15 probe、Stage17 `targeted-direct` 仍保持原 sparse precedence，证明本轮 helper 没有误伤既有路径。

unit tests 应直接检查生成的 kwargs 字典，而不是只看格式化日志。full production identity 后再完成脚本 syntax、XS option tests 和相关 activity-schedule regression；完整 build/CTest 结果按目录规则另立记录。

## 7. 实现与提交边界

Stage 18 预计只修改父仓的 XS 脚本、Makefile、父仓 option tests 和对应文档；不修改 `ActivityScheduleOptions` 或 emitter C++ 默认。如果实现过程中没有子模块文件变化，不创建空的子模块提交，也不移动 submodule pointer；若后续确实需要子模块测试/接口改动，则必须先单独提交子模块，再提交父仓 pointer。

提交粒度以 Stage 18 single-source cleanup 整体为单位，不为单个 helper、测试或文档拆提交。fresh emit、identity diff、build/test 日志和 generated artifacts 留在 `build/`，不纳入提交。
