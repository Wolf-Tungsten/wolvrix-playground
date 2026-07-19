# TNO0158 SimpleTES formal runtime contract hardening

日期：2026-07-20

状态：正式 instance `91f6580e` 已越过 isolated clone，current-default control 正在 fresh
SimTop emit/build。正式 50k 尚未开始，因此 accepted sample、绝对 `Host time spent` 与
相对性能变化仍均为 `0`；本文只归档正式测量契约的最后收紧，不作性能或默认采用结论。

## 1. 固定身份与运行位置

```text
target working-tree HEAD  5ca6cf18b0f65102c713ee598f44e9893b88fcad
bench pinned parent       b90d204
bench pinned wolvrix      f17e90e14c3ad70a3ee93f7c6540e13dae54940a
SimpleTES runtime fix     066f252b957e344be62b11066d78b9d626186d69
instance                  91f6580e
checkpoint                SimpleTES/checkpoints/grhsim_simtop_50k/formal_20260720_01
slot                      /tmp/simpletes-grhsim-simtop-50k/240719f63589edae/slot-0
```

`b90d204..5ca6cf1` 之间只有本轮 SimpleTES 记录文档；生成路径仍固定到同一 wolvrix
`f17e90e`。最近历史 current-default 有效 control 原值为 `74,382 / 74,320 ms`，算术均值
`74,351.0 ms`，见 [TNO0155](./TNO0155_stage7_plus_current_baseline_rebuild_and_formal_gate_interruption_20260719.md)。
它采用旧 fixed-CPU/whole-node 协议，只作数量级 sanity check；本轮 dynamic-CCD 协议必须
由同组 fresh control 重新定标，不能拿历史绝对值直接评分。

## 2. 审计发现与修正

正式 evaluator 只会发出 `ABBA`，候选首轮 wall 正向后才发出 `BAAB`。只读 API 审计发现
runtime 公共入口原来只检查“两个 A、两个 B”，因此 `AABB/BABA/ABAB` 也会通过；成功
diagnostics 也没有回写实际顺序。虽然当前 launcher 不会触发错误排列，但审计接口弱于
bench 文档契约。

SimpleTES commit `066f252` 将 paired measurement 收紧为：

- `samples_per_variant` 必须绝对为 `2`；
- `group_order` 只能是 `ABBA` 或 `BAAB`，其余排列均作为 retryable trusted-runtime
  configuration error 拒绝，绝不形成 valid candidate；
- 成功结果的 diagnostics 显式写入绝对 `group_order`；
- source `env.sh` 后固定 `EMU_PROGRESS_EVERY_CYCLES=0`，移除继承的
  `EMU_RUNTIME_PROFILE`、全部 `GRHSIM_TRACE_*` 和全部
  `WOLVRIX_GRHSIM_*_TSV`，防止 trace/profile counter 污染未插桩 walltime。

这不改变候选算法、默认生成参数或 walltime 聚合，只封闭非正式顺序与继承环境旁路。

## 3. 验证绝对结果

```text
focused runtime+bench tests  56 passed in 0.17 s
full SimpleTES tests          104 passed in 4.54 s
warnings                      17 existing datetime.utcnow deprecations
git diff --check              PASS
```

新增测试绝对覆盖 `AABB/BABA/ABAB` 三个拒绝样例、`ABBA/BAAB` diagnostics，以及
`EMU_RUNTIME_PROFILE`、两个 `GRHSIM_TRACE_*`、四种 runtime TSV 污染清理。

## 4. 正式 control 当前进度

control build 已生成 Wolvrix 工具产物并进入真实 SimTop pipeline。已观察到的绝对阶段耗时：

| stage | absolute time |
| --- | ---: |
| `read_sv` | `111,750 ms` |
| `xmr-resolve` | `76,497 ms` |
| `memory-read-retime` | `2,052 ms` |
| `multidriven-guard` | `1,074 ms` |
| `blackbox-guard` | `2,036 ms` |
| `latch-transparent-read` | `1,017 ms` |
| `hier-flatten` | `43,602 ms` |
| `comb-lane-pack` | `191,706 ms` |
| `comb-loop-elim` | `68,897 ms` |

其后正在执行 `simplify`。这些是 emit/build 耗时，不是端到端仿真性能；不能与
`Host time spent` 混用。control build、100/10k、quiet-CCD 50k 的绝对结果另立新 TNO。

## 5. 保留边界

- current C++ default 和 wolvrix 源码没有改变；没有候选可以保留或默认开启。
- 最终 headline 仍唯一为有效 SimTop 50k 的正 `Host time spent` walltime。
- 任一 CCD admission、持续 monitor、ASLR personality、NUMA page placement、PMU
  scheduling、migration 或功能门禁失败，整组只作 infrastructure retry，不进入 valid budget。
- 正式会话继续使用 `gpt-5.6-sol`、`ultra` 和 MJY config/auth；本文不记录任何密钥内容。
