# TNO0122 Stage 21 terminal pushforward probe implementation and production result

记录日期：2026-07-18

状态：Stage 21 no-mutation probe、参数透传、focused 正例和 production emit 已完成。当前默认 NO0300、ASLR 关闭口径下共找到 `1,054` 个 exact eligible terminal compute node；native 限额选择 `128` 个，投影净减 `128` 条 BAE、`128` 个 boundary value 和 `183` logical bytes。绝对收益较小，但 selected 候选均不增加 source-to-target input BAE，故继续实现 strict candidate 并以 SimTop 50k `Host time spent` walltime 裁决。C++ native default 仍为 `off`，本阶段没有端到端性能结论。

## 1. 实现与默认边界

新增的 `final-terminal-pushforward-*` 选项为：

| option | C++ default |
| --- | ---: |
| `policy` | `off` |
| `max-node-ops` | `8` |
| `max-inputs` | `16` |
| `max-outputs` | `16` |
| `max-value-width` | `64` |
| `min-bae-gain` | `1` |
| `min-boundary-value-gain` | `1` |
| `max-moves` | `128` |
| `max-moved-op-ppm` | `200` |

Python binding、native CLI 和 XS 只做 sparse 参数透传。未设置环境变量时，XS 日志对九项参数均显示 `cpp-default`；脚本中没有 XS 专用默认。当前 `policy` 仅接受 `off/probe`，因此 probe 不会改 graph、schedule、active ID、batch 或 generated C++。

候选 `C: S -> T` 必须满足：

- `C` 是完整、纯、无 side effect/intent/clone-forbidden 属性的小 compute node；op kind 限于比较、位逻辑、逻辑运算、归约、assign 和 static slice。
- 所有 external input 均由 source supernode `S` 中不属于 `C` 的 op 定义；所有 external output 只被同一个 compute target `T` 使用。
- output 不能是 declared/port value，不能有隐式 reg-to-mem index consumer；source 移除 `C` 后非空，target 加入 `C` 后不超过 compute cap。
- 由最终 `valueFanout` 精确重算 removed/added BAE、boundary values 和 logical bytes；三项均要求净正收益。
- 稳定按 BAE、boundary-value、byte gain 排序；selection 不允许两个 move 接触同一个 supernode，并受 move 数与 moved-op PPM 限制。

`added_bae=0` 的含义很重要：`C` 的 input 已经从 `S` 跨界到 `T`，所以把 `C` 推入 `T` 不新增 source-to-target 激活边；原本 `C` 的 output 边则消失。这也是本轮在静态收益较小的情况下仍进入 strict walltime 的依据。

## 2. focused gate

最小正例包含 `5` 个 8-bit compute op，final partition 稳定为 `4/1` 两个 supernode。candidate 是 source 中的单 op `kNot`，其 input 已被 target 直接使用，output 也只被 target 使用。probe 精确得到：

```text
scanned=5
exact_eligible=1
selected=1
eligible_bae_gain=1
selected_bae_gain=1
eligible_boundary_value_gain=1
selected_boundary_value_gain=1
eligible_byte_gain=1
selected_byte_gain=1
moved_ops=1
moved_op_limit=5
pair_multiplicity=3
removed_bae=1
added_bae=0
removed_boundary_values=1
added_boundary_values=0
removed_bytes=1
added_bytes=0
```

测试同时验证 default/off/probe 的完整 schedule 和 session identity、九项 CLI 的分离/等号形式、负整数拒绝、非法 policy 和大于 `1,000,000` PPM 拒绝。小图显式使用 `1,000,000` PPM，避免 production 默认 `200` PPM 向下取整为零预算。

通过的 focused gate：

```text
cmake --build wolvrix/build --target transform-activity-schedule -j2
wolvrix/build/bin/transform-activity-schedule
python3 wolvrix/tests/pybind/test_activity_schedule_options.py   # 5/5
python3 scripts/test_wolvrix_xs_grhsim_options.py                # 17/17
git diff --check
git -C wolvrix diff --check
```

C++ focused 原始输出保存在：

```text
build/logs/xs/stage21_terminal_pushforward_focused_20260718.log
```

## 3. production probe 与绝对 schedule

production 从当前默认 post-stats 恢复：

```text
build/xs_activity_stage8_dp_p050_20260715/grhsim/wolvrix_xs_post_stats.json
```

输出与原始日志为：

```text
build/xs_activity_stage21_terminal_pushforward_probe_20260718/grhsim/grhsim_emit/
build/logs/xs/xs_wolf_grhsim_build_activity_stage21_terminal_pushforward_probe_20260718.log
```

本轮 fresh work base 还生成了独立 RTL；该前置步骤约 `465s`。Python flow 的绝对时间为 activity-schedule `168,905ms`、probe `3,816ms`、write C++ `59,299ms`、总计 `256,868ms`。

最终 schedule 与当前默认完全一致：

| metric | absolute value |
| --- | ---: |
| graph ops | `7,204,108` |
| compute nodes | `1,092,530` |
| total supernodes | `63,726` |
| compute supernodes | `63,241` |
| commit supernodes | `485` |
| DAG edges | `528,622` |
| boundary values | `1,000,463` |
| boundary activation edges | `1,983,923` |
| compute-compute value pairs | `1,721,698` |
| compute-commit value pairs | `262,225` |
| state-read activation edges | `84,972` |
| memory-read activation edges | `47,830` |
| constant activation edges | `45,686` |
| other-compute activation edges | `1,805,435` |
| topo edges | `10,150,909` |

## 4. production candidate funnel

完整绝对漏斗如下：

```text
scanned=1,092,530
pure=287,944
exact_eligible=1,054
selected=128
eligible_bae_gain=1,054
selected_bae_gain=128
eligible_boundary_value_gain=1,054
selected_boundary_value_gain=128
eligible_byte_gain=1,184
selected_byte_gain=183
moved_ops=128
moved_op_limit=1,125
```

所有 `1,054` 个 eligible 的 BAE gain 和 boundary-value gain 都精确为 `1`。node op 分布为 `1-op: 1,037`、`2-op: 17`；默认 selection 的 `128` 个全部为 1-op。selected output kind 为：

| kind | selected |
| --- | ---: |
| `kNot` | `68` |
| `kSliceStatic` | `27` |
| `kLogicNot` | `22` |
| `kOr` | `9` |
| `kAnd` | `2` |

主要 reject 绝对数为：

| reason | count |
| --- | ---: |
| node size | `121,004` |
| op kind | `629,714` |
| width | `53,868` |
| declared/port output | `100,588` |
| input not defined by source remainder | `143,351` |
| invalid consumer | `15,551` |
| more than one target | `23,123` |
| target capacity | `1,906` |
| insufficient BAE gain | `2,371` |
| selection max-moves | `514` |
| selection touched-supernode conflict | `412` |

owner、restricted、side-effect、clone-forbidden、shape、no-input、too-many-input、no-output、too-many-output、hidden-consumer、source-empty、fanout-mismatch、boundary-value-gain、byte-gain和selection-budget rejects 均为 `0`。默认选择未碰到 moved-op budget，而是先达到 `128` move 上限。

相对当前绝对 schedule：

- selected 投影 BAE 为 `1,983,923 -> 1,983,795`，减少 `128`，即 `-0.006451863%`；
- 全部 eligible 的理论 BAE 上界为 `1,983,923 -> 1,982,869`，减少 `1,054`，即 `-0.053127062%`，但未做冲突消解；
- selected 投影 boundary values 为 `1,000,463 -> 1,000,335`，减少 `128`，即 `-0.012794076%`；
- 全部 eligible 的理论 boundary-value 上界减少 `1,054`，即 `-0.105351222%`。

## 5. no-mutation identity

probe 目录包含 `158` 个普通 emitter 文件：`154` 个 cpp/hpp、`117` 个 schedule cpp。schedule cpp 绝对大小为 `1,331,059,293` bytes；全部 cpp/hpp 为 `1,356,872,724` bytes，cpp/hpp 加 Makefile 为 `1,356,877,425` bytes。

与 Stage 20 current-default emit 逐文件比较，除 `wolvrix_read_args.txt` 外全部 byte-exact；排除该 path-bearing 文件的 `157` 文件 content manifest 均为：

```text
8d4ccb9627485e2525c8aac4a34b8eee38b40e29e26f9206442862f4b0a6d5ec
```

两个核心 stats 也保持绝对 identity：

```text
activity_schedule_supernode_stats.json
e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77

grhsim_emit_stats.json
9dd1bdddd01606507b2e3425917f260ca3ac8c5b88c55fa21408bffb17080a8b
```

`wolvrix_read_args.txt` 的 SHA 从 Stage 20 的 `bd420039...` 变为 `6678ed31...`，唯一文本差异是 RTL include 路径从 `build/xs/rtl/rtl` 变为本轮 fresh work base；这不是 generated-program 差异。

## 6. 下一阶段与性能判据

Stage 22 将实现独立 `strict` policy，实际移动当前默认 selection 的 `128` 个 compute node，并在重建 derived schedule 后逐项验证：supernode/kind/op partition、capacity、commit partition、DAG/topo、state-read sets、compute-commit pairs，以及 projected/actual BAE 必须一致。随后做 production emit、O3/功能 gate 和正确 page-local 双 NUMA SimTop 50k A/B。

最终采用与否只看 `Host time spent` walltime 的绝对样本和 balanced A/B 结果；cycles/instructions 仅作诊断。runtime 必须使用独立 `/dev/shm` inode、`taskset`、`numactl --physcpubind/--membind`、`setarch x86_64 -R`、整 node pre/runtime idle gate 和 page placement 检查。若 walltime 没有可重复收益，C++ default 保持 `off`。
