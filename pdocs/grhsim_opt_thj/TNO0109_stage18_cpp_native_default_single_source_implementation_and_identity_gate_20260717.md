# TNO0109 Stage 18 C++ native-default single-source implementation and identity gate

记录日期：2026-07-17

状态：[TNO0107](./TNO0107_stage18_cpp_native_default_single_source_cleanup_plan_20260717.md) 已实现。XS clean environment 不再重复注入与 `ActivityScheduleOptions` 完全同值的 28 个参数；Makefile 不再无条件制造 commit cap `4096` 高层覆盖。两套 fresh production gate 证明：clean sparse default 与 current native-hybrid/cap4096 的 157 个 artifact 全部 byte-exact，显式 cap8192 的全部 `.cpp/.hpp/.json` 也与旧显式 cap8192 byte-exact。该阶段只改变配置所有权和日志来源，不改变 schedule、generated C++ 或端到端程序。

## 1. 实现范围

父仓新增声明式 `read_activity_schedule_sparse_options()`，按三类读取 28 个高层环境变量：

```text
bool    3
integer 20
string  5
```

clean environment 返回空字典；只有变量实际存在时才把对应 key 传给 `activity-schedule`。显式 `false` 不会因 Python truthiness 丢失，整数和字符串保持旧解析/校验语义。迁为 sparse 的 family 为：

- commit cap/guard；
- declared-value boundary；
- local-shared compute 与 common-owner policy/预算；
- DP segment penalty；
- post-DP refine/swap policy 与预算；
- Kahn-level pack policy 与预算；
- final-fanin pullback policy 与预算；
- final topo policy。

Stage15 final-sibling family 继续使用已有 sparse reader，并与上述 options 合并后一次性传入 pass。Stage14 direct-state/event-bypass 与 Stage16/17 active-mask 的既有 sparse precedence 没有改变。`export_compute_dag` 仍只在显式配置时加入。

config log 对迁移项打印 `cpp-default` 或显式值，不再为了日志在 Python 中复制 C++ 常量。通用默认因此只有一个来源：

```text
ActivityScheduleOptions / C++
```

以下 XiangShan 平台配置仍明确保留，没有错误地迁回通用默认：

```text
compute supernode/node cap   108 / 108
split oversize              true, max 108
batch ops/lines/target      2048 / 8192 / 64
emit parallelism            4
storage-ref aliases         0
```

## 2. Makefile 默认源修正

顶层 Makefile 的：

```make
XS_WOLF_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE
```

由隐式 `4096` 改为空默认，并计算一个仅在 make 变量或继承的 `WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE` 非空时才存在的 effective override。recipe 行为为：

- default dry-run：command echo 显示 `cpp-default`，实际 Python 命令前缀没有 commit-cap 高层环境赋值；
- `XS_WOLF_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE=8192`：精确注入 `8192`；
- 继承 `WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE=8192`：同样精确注入 `8192`。

这同时保留旧实验接口与高层环境接口，且不会再用脚本/Makefile 的伪默认遮蔽未来 C++ 默认。

## 3. Focused option gate

测试直接检查 sparse kwargs，而不是只检查日志文本：

| gate | 结果 |
| --- | --- |
| clean environment 的 28 项 options | 精确 `{}` |
| 28 项显式 bool/int/string | 精确字典对账 |
| 三个 bool 的显式 false | 独立保留 |
| activity-schedule kwargs compiler | 接受全部 28 项 |
| 非法整数/负数 | reader/compiler 分层拒绝 |
| Stage14/15/17 已有 sparse precedence | 保持通过 |
| XS option unittest | `16/16 PASS` |
| Python syntax compile | PASS |
| `git diff --check` | PASS |

日志：

```text
build/logs/xs/stage18_cpp_native_defaults_20260717/xs_options.log
build/logs/xs/stage18_cpp_native_defaults_20260717/make_default_dryrun.log
build/logs/xs/stage18_cpp_native_defaults_20260717/make_make8192_dryrun.log
build/logs/xs/stage18_cpp_native_defaults_20260717/make_env8192_dryrun.log
```

## 4. Clean sparse production identity

fresh output 与日志：

```text
build/xs_activity_stage18_cpp_native_defaults_sparse_20260717/grhsim/grhsim_emit/
build/logs/xs/xs_wolf_grhsim_build_activity_stage18_cpp_native_defaults_sparse_20260717.log
```

它使用同一 post-stats checkpoint，显式保留上述 XS 平台参数，并故意 unset 全部 28 个迁移项。日志确认所有迁移项为 `cpp-default`。最终结构绝对值为：

| metric | sparse default |
| --- | ---: |
| total supernodes | `63,726` |
| compute supernodes | `63,241` |
| commit supernodes | `485` |
| DAG edges | `528,622` |
| boundary values | `1,000,463` |
| boundary activation edges | `1,983,923` |
| compute-compute value pairs | `1,721,698` |
| compute-commit value pairs | `262,225` |

单文件 SHA256：

```text
activity_schedule_supernode_stats.json
  e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77

grhsim_emit_stats.json
  9dd1bdddd01606507b2e3425917f260ca3ac8c5b88c55fa21408bffb17080a8b
```

与 Stage17/current native-hybrid default 逐目录 `diff -qr` 的差异数为 `0`：两边都是 `157` 个文件，两个 JSON、artifact set、Makefile、全部 `.cpp/.hpp` 均 byte-exact。因而 schedule、active ID、value slot、batch/file order、generated model 与后续 O3 输入都没有变化。

## 5. 显式 cap8192 identity

为确认 sparse helper 没有破坏 Stage12 实验入口，又 fresh 生成：

```text
build/xs_activity_stage18_cpp_native_defaults_cap8192_20260717/grhsim/grhsim_emit/
build/logs/xs/xs_wolf_grhsim_build_activity_stage18_cpp_native_defaults_cap8192_20260717.log
```

日志只显式显示 `max_op_in_commit_supernode=8192`，guard 和其它迁移项继续由 C++ default 提供。结构绝对值为：

| metric | explicit cap8192 |
| --- | ---: |
| total supernodes | `63,709` |
| compute supernodes | `63,241` |
| commit supernodes | `468` |
| DAG edges | `527,990` |
| boundary values | `1,000,463` |
| boundary activation edges | `1,983,326` |
| compute-compute value pairs | `1,721,698` |
| compute-commit value pairs | `261,628` |

activity stats SHA256 为：

```text
6c41b8b25d83e05d402dbeb6164553bdd10903b8c8e67efae8cfd3cf6542257c
```

与旧 `build/xs_activity_stage14_native_hybrid_default_cap8192_20260717/grhsim/grhsim_emit/` 对照时，全部 `.cpp`、`.hpp` 和 JSON manifest byte-exact；旧目录额外存在的 `.o/.pch/.a` 只是已完成 O3 build 的派生产物，不属于 generated-source 差异。显式 cap、guard 继承与 codegen 行为均保持。

## 6. Walltime 边界与结论

[TNO0110](./TNO0110_walltime_headline_criterion_and_re_evaluation_20260717.md) 已将端到端最终判据统一为 SimTop `Host time spent` walltime，cycles/PMU 只作解释。本阶段没有声称新的性能收益，也不使用 cycles 裁决：clean sparse output 与既有 default 的全部 generated artifact byte-exact，二者是同一个端到端程序；重复跑 walltime 只会重新采样同一 binary 的噪声，弱于 byte identity 证明。

共享指标工具 `scripts/grhsim_opt_metrics.py` 现在要求 `Host time spent` 在日志中恰好出现一次，输出 `emu_host_time_count`；只有唯一正值才产生 `emu_host_time_ms`。严格 page-local runner 同步把 `walltime_count/walltime_ms/walltime_ok` 写入每个样本的 result，并拒绝缺失或重复 walltime 的样本。

因此 Stage18 的结论仅是配置所有权清理成功：

```text
通用 default              C++ single source
XS clean override         none for identical activity defaults
XS platform-specific      explicit and unchanged
experimental override     sparse and unchanged
generated behavior        byte-identical
```

Stage7+ 的 cap8192 attempt2 与其它性能候选仍须独立执行 strict page-local SimTop 50k，并以 walltime 作为 headline；本阶段不借 source identity 修改任何性能默认。
