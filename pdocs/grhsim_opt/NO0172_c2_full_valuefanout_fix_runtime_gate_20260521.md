# NO0172 C2 Full + ValueFanout Fix Runtime Gate

日期：2026-05-21

## 目的

验证 `NO0171` 中恢复出的 C2 full unbounded 结构收益，是否能转化为 XiangShan CoreMark runtime 收益。

本次不是 fresh 诊断起点，而是基于 scheduler 代码修复后的必要 full emit/build/runtime gate。

## 配置

产物目录：

```text
tmp/no0172_xs_c2_full_valuefanout_fix_full/
```

关键 activity-schedule 配置：

```text
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SINGLE_PARENT_MERGE=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_SIBLING_MERGE=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE=0
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE=0
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS=0
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_CANDIDATE_BUDGET=0
WOLVRIX_XS_GRHSIM_SCHED_BATCH_TARGET_COUNT=800
```

## Emit 结果

来自 `tmp/no0172_xs_c2_full_valuefanout_fix_full/emit.log`：

| 项目 | 数值 |
| --- | ---: |
| `activity-schedule` | `187186 ms` |
| `write_grhsim_cpp` | `57919 ms` |
| `total` | `266127 ms` |

结构统计：

| 指标 | 数值 |
| --- | ---: |
| `supernodes` | `74945` |
| `compute_supernodes` | `74430` |
| `commit_supernodes` | `515` |
| `dag_edges` | `485905` |
| `boundary_values` | `1151073` |
| `boundary_activation_edges` | `2216514` |
| `compute_compute_value_pairs` | `1858400` |
| `compute_commit_value_pairs` | `358114` |
| `state_read_activation_edges` | `9367` |
| `constant_activation_edges` | `4749` |
| `other_compute_activation_edges` | `2202365` |
| `essent_small_sibling_merges` | `329802` |

结论：结构已恢复到 `NO0162/NO0171` 快档画像，`source activation edge` 爆炸已经消除。

## Build 结果

`grhsim_emit/libgrhsim_SimTop.a` 已生成，大小约 `148 MB`，并确认 archive 内包含关键成员：

```text
grhsim_SimTop_state.o
grhsim_SimTop_eval.o
grhsim_SimTop_state_init_9.o
grhsim_SimTop_sched_993.o
```

注意：本次 model build 的干净 wall-clock 不能作为有效数据。续编阶段误触发 `grhsim_SimTop_state_init_9.cpp` 重新编译，archive 已生成后该编译仍长期占用 CPU，最终被手动终止。因此本记录只把 archive 作为可运行产物使用，不用本次 model build 墙钟时间做对比。

difftest emu build 通过：

| 项目 | 数值 |
| --- | ---: |
| `real` | `7.32 s` |
| `user` | `6.56 s` |
| `sys` | `0.76 s` |
| `emu` 大小 | `132 MB` |

## 20k Runtime Gate

命令口径：

```text
./grhsim-compile/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 20000
```

结果来自 `tmp/no0172_xs_c2_full_valuefanout_fix_full/build/coremark20k.log`：

| 项目 | 数值 |
| --- | ---: |
| `host_cycles` | `20000` |
| `model_cycles` | `20000` |
| `instrCnt` | `14121` |
| `cycleCnt` | `19996` |
| `IPC` | `0.706191` |
| `Host time spent` | `129095 ms` |
| `real` | `129.10 s` |
| 速度 | `154.9 cycles/s` |

difftest 已启用：

```text
The first instruction of core 0 has commited. Difftest enabled.
```

本轮到达 cycle limit，未出现 difftest mismatch。

## 对比

| 实验 | 20k 时间 | 约速度 | 备注 |
| --- | ---: | ---: | --- |
| `NO0162` | `98988 ms` | `202.0 cycles/s` | 快档参考 |
| `NO0154` | `103348 ms` | `193.5 cycles/s` | 当前改进后参考 |
| `NO0164` | `166379 ms` | `120.2 cycles/s` | 结构漂移负向 |
| `NO0172` | `129095 ms` | `154.9 cycles/s` | 结构恢复但 runtime 未恢复 |

`NO0172` 相比 `NO0164` 明显恢复，但仍比 `NO0162` 慢约 `30%`。按当前 gate 规则，20k 已明显低于快档，不继续跑 50k。

## 结论

`valueFanout skipDag` 修复 + C2 full unbounded 能恢复静态结构，但不能单独恢复 runtime 快档。

当前根因判断需要进一步收窄：`BAE/dag/source-edge` 已不是唯一解释，下一步应比较 `NO0162` 与 `NO0172` 的 generated-code 形态、热 batch 分布和 runtime profile，尤其检查：

- 是否存在 scheduler/emitter 代码生成差异导致同结构不同代码形态。
- 是否 `state_init_9.cpp`/large TU 异常说明生成文件布局或 PCH 依赖发生漂移。
- 是否 runtime 热点从 activation edge 数量转移到 value materialize、state alias、commit path 或 cache/code layout。
