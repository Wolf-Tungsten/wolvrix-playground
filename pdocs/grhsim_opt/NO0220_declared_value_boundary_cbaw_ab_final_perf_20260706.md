# NO0220 Declared Value Boundary CBAW A/B Final Performance

记录日期：2026-07-06

关联：[`NO0219`](./NO0219_declared_value_compute_node_boundary_plan_20260706.md)、[`NO0215`](./NO0215_cbaw_multiplicity_reduction_action_plan_20260703.md)

状态：已完成 full build + CoreMark 50k final runtime A/B。

## 1. 目的

本轮只回答一个问题：

```text
在 CBAW 路线下，把 declared value 作为 compute node seed 截断边界，
是否能改善最终 emu 的 CoreMark 50k no-profile 性能？
```

因此本轮不使用 stop-after 结构数据下结论；两组都完成 fresh emit、fresh emu build，并跑最终 `run_xs_wolf_grhsim_emu`。

## 2. 固定配置

两组共同配置：

- `partition_policy=cbaw`
- `WOLVRIX_XS_GRHSIM_FM_REFINE_MAX_ROUNDS=8`
- `WOLVRIX_XS_GRHSIM_CBAW_COARSEN_MAX_ITERATIONS=32`
- plain external baseline：`boundary=2446334 dag=703270 compute_compute=2095811`
- `XS_WOLF_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE=108`
- `XS_WOLF_GRHSIM_MAX_OP_IN_COMPUTE_NODE=108`
- `XS_WOLF_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE=4096`
- resume from `build/xs/grhsim/wolvrix_xs_pre_reg_to_mem.json`
- runtime：CoreMark 50k, no waveform, no commit trace

A/B 唯一变量：

| 组 | 环境变量 |
| --- | --- |
| baseline | `WOLVRIX_XS_GRHSIM_DECLARED_VALUE_COMPUTE_NODE_BOUNDARY` 未设置 |
| declared-boundary | `WOLVRIX_XS_GRHSIM_DECLARED_VALUE_COMPUTE_NODE_BOUNDARY=1` |

## 3. 产物

| 组 | build dir | build log | runtime logs |
| --- | --- | --- | --- |
| baseline | `tmp/no0219_cbaw_ab_base_20260706/grhsim` | `build/logs/xs/xs_wolf_grhsim_build_no0219_cbaw_ab_base_20260706.log` | `build/logs/xs/xs_wolf_grhsim_no0219_cbaw_ab_base50k_20260706.log`, `build/logs/xs/xs_wolf_grhsim_no0219_cbaw_ab_base50k_r2_20260706.log` |
| declared | `tmp/no0219_cbaw_ab_decl_20260706/grhsim` | `build/logs/xs/xs_wolf_grhsim_build_no0219_cbaw_ab_decl_20260706.log` | `build/logs/xs/xs_wolf_grhsim_no0219_cbaw_ab_decl50k_20260706.log`, `build/logs/xs/xs_wolf_grhsim_no0219_cbaw_ab_decl50k_r2_20260706.log` |

metrics JSON：

- `build/metrics/xs/no0219_cbaw_ab_base_20260706_metrics.json`
- `build/metrics/xs/no0219_cbaw_ab_decl_20260706_metrics.json`
- `build/metrics/xs/no0219_cbaw_ab_base_r2_20260706_metrics.json`
- `build/metrics/xs/no0219_cbaw_ab_decl_r2_20260706_metrics.json`

## 4. 最终性能

两组 runtime 都正常触发 50k cycle limit，且工作负载一致：

- `instrCnt = 73580`
- `cycleCnt = 49996`
- `IPC = 1.471718`
- `Guest cycle spent = 50001`
- exceed limit PC：`0x80001312`

| run | baseline host time | declared host time | declared vs baseline |
| --- | ---: | ---: | ---: |
| r1 | `300360ms` | `312784ms` | `+12424ms` / `+4.14%` |
| r2 | `304073ms` | `319724ms` | `+15651ms` / `+5.15%` |
| average | `302216.5ms` | `316254.0ms` | `+14037.5ms` / `+4.65%` |

结论：declared-boundary 版本两次都比 baseline 慢。即使按平均值看，也慢 `4.65%`；按第二次复测看，已经超过 `NO0219` 预设的 `+5%` runtime 上限。

## 5. 结构结果

| 指标 | baseline | declared | delta |
| --- | ---: | ---: | ---: |
| seed `compute_nodes` | `1396066` | `2204668` | `+808602` / `+57.92%` |
| initial compute supernodes | `449958` | `569392` | `+119434` / `+26.54%` |
| final supernodes | `75074` | `75498` | `+424` / `+0.56%` |
| final compute supernodes | `74577` | `75001` | `+424` / `+0.57%` |
| final `boundary_activation_edges` | `2253277` | `2273631` | `+20354` / `+0.90%` |
| final `dag_edges` | `643038` | `628567` | `-14471` / `-2.25%` |
| final `compute_compute_value_pairs` | `1902754` | `1923108` | `+20354` / `+1.07%` |
| final `state_read_activation_edges` | `130101` | `183886` | `+53785` / `+41.34%` |
| generated sched lines | `15794371` | `16054505` | `+260134` / `+1.65%` |
| generated sched bytes | `1561016726` | `1584431909` | `+23415183` / `+1.50%` |

declared-boundary 确实显著切细了 seed 层，并让 CBAW 看见更多语义边界。但最终结构只换来 DAG 下降；final BAE 和 compute-compute value pairs 都小幅上升，且 state-read activation 增幅明显。

## 6. declared boundary 生效性

declared 组关键计数：

| 计数 | 值 |
| --- | ---: |
| `boundary_declared` | `3022197` |
| `declared_boundary_values` | `1214544` |
| `declared_boundary_edges` | `2808640` |
| `declared_cut_fixed` | `351` |
| `declared_cut_fatal` | `0` |

这些计数证明 NO0219 的 hard seed boundary 已实际生效，并且 invariant fixer 没有留下 fatal violation。

## 7. 构建成本

| 阶段 | baseline | declared | delta |
| --- | ---: | ---: | ---: |
| `compute_node_build` | `20448ms` | `91279ms` | `+70831ms` / `+346.40%` |
| materialize `coarsen` | `475989ms` | `553712ms` | `+77723ms` / `+16.33%` |
| `final_materialize` | `493408ms` | `570353ms` | `+76945ms` / `+15.59%` |
| activity-schedule total | `582679ms` | `730899ms` | `+148220ms` / `+25.44%` |
| script total emit | `660669ms` | `809048ms` | `+148379ms` / `+22.46%` |

更细的 seed 让 CBAW 候选规模从 `89584218` 增到 `136338645`，但最终 runtime 没有受益。

## 8. 判断

本轮 A/B 的关键信号是：

- declared hard boundary 生效，seed `compute_nodes` 增加 `57.92%`。
- CBAW 能把大量额外 seed 重新合回，final supernodes 只增加 `0.56%`。
- final DAG 变好 `2.25%`，但 final BAE / compute-compute value pairs 变差约 `1%`。
- 生成代码体积只小幅增加，但 state-read activation 增加 `41.34%`。
- 两次 final CoreMark 50k 都变慢，平均 `+4.65%`，复测最高 `+5.15%`。

结论：**declared value hard seed boundary 不应作为当前 CBAW 默认配置启用**。它适合作为诊断开关，证明 declared 语义切点确实能被保留下来；但按当前 CBAW/DP/FM 成本模型，保留这些 hard boundary 没有转化为最终性能收益，反而带来 seed 爆炸、构建成本上升和 final runtime 回退。

后续如果继续利用 declared 语义，方向不应是 hard boundary 默认开启，而应改成 CBAW soft hint / attribution：

- 只对特定 declared kind / fanout / width 加 soft no-merge penalty。
- 把 declared boundary 纳入 CBAW accepted/rejected attribution，识别哪些 declared cut 最后导致 BAE 或 state-read activation 上升。
- 若做二阶段实验，必须继续用 full emu CoreMark 50k 验收，不能只看 DAG 或 seed p99。
