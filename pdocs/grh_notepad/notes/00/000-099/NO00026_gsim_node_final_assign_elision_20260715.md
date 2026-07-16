---
id: NO00026
date: 2026-07-15
title: GSim node-final assign elision and full XiangShan retest
kind: implementation
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, grh-json, assign-elision, activity-schedule, codegen, compile-time, xiangshan]
parents: [NO00025]
related: [NO00023, NO00024]
supersedes: []
---

# NO00026 GSim node-final assign elision and full XiangShan retest (2026-07-15)

> 归档编号：`NO00026`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## 结论先行

GSim exporter 中的 node-final `kAssign` 确实是主要的结构冗余。本次在 exporter 内把单节点
expression root 的 producer result 直接 retarget 到稳定的 `gsim.v.<node-id>`，全量 XiangShan
消除了 2,488,603 个 `gsim.assign.*`，同时完整保留 392,724 个承担 width/sign coercion 的
`gsim.expr.* kAssign`。

优化使 JSON 缩小 17.4%，scheduler 输入 ops 减少 32.1%，原 108-op 口径下 compute supernodes
减少 25.2%，C++ 缩小 7.5%，schedule `static_cast` 减少 16.8%。但是 30 分钟
`clang++ -O3 -j32` gate 仍超时，只完成 124/141 objects，低于旧 run15 的 128/141。因此 exporter 修复是
正确且有效的输入图优化，但不能单独解决编译长尾；剩余问题仍在复杂 expression 和 TU 分区。

## Exporter 实现

实现位于 `reference/gsim/src/ExecutableGrhExporter.cpp`：

1. `lowerAssignedNode()` 进入时开启 per-node emission capture，`emitValue()` 和
   `emitOperation()` 暂存结构化记录，不直接写 spool。
2. node lowering 完成后，只在最终 symbol 是本 capture 新建的 `gsim.tmp.*`、有唯一 producer、
   没有被 capture 内其他 op 消费、producer 不是共享 `kConstant` 且只有一个 output 时 retarget。
3. producer output 从 temporary 改为预先声明的稳定 target，删除 temporary value record，不再
   生成 `gsim.assign.<node-id>`；node provenance、`gsim.constant_output` 和
   `gsim.empty_assignment_zero` attrs 转移到 producer。
4. 不满足条件时 flush 原记录并保留 final assign。常量和直接 `gsim.v -> gsim.v` copy 因而保持
   保守行为；coercion producer 仍是 `kAssign`，只把 output 改成稳定 target。
5. envelope 新增 `nodeFinalAssignElidedCount` 和 `nodeFinalAssignKeptCount`，便于全量审计。

该方案不做 2.8--3.4 GB JSON 的事后重写，也不 alias 全局共享 constant，retarget 的判断边界只
覆盖当前 semantic node 新产生且未共享的 root temporary。

## 小规模回归

新增 `executable-grh-node-final-assign-elision.fir`，覆盖：

- `kAdd` producer 直接产出 `add_result` 的稳定 value；
- 8 -> 9 bit coercion 的 `gsim.expr.* kAssign` 仍存在并直接产出 output value；
- shared constant 仍通过保守的 node-final assign 绑定。

以下 6 个 exporter tests 全部通过：

```text
test-executable-grh-node-final-assign-elision
test-executable-grh-split-register-clock
test-executable-grh-register-clock-liveness
test-executable-grh-async-reset-constant-next
test-executable-grh-effects
test-executable-grh-empty-memory-writer
```

专用 JSON 随后通过 Wolvrix `read_json_file -> activity-schedule -> emit_grhsim_cpp` 冒烟，原参数
为 108-op split、commit 4096、batch target 64。

## 全量导出 A/B

输入与 run14 相同：`build/xs/rtl/rtl/SimTop.fir`，输入文件为 1,671,325,062 bytes，最终
GSim semantic `nodeCount=2,710,434`。新产物：

```text
ptmp/gsim_assign_elide_20260715/full/gsim/SimTop.exec.json
sha256=c93ea0856d988e6dc48b3ede57dad870f13727079f3c09ecf3b1477034c189b0
```

| 指标 | run14 baseline | assign elision | 差异 |
| --- | ---: | ---: | ---: |
| JSON bytes | 3,369,244,412 | 2,784,160,317 | -17.4% |
| values | 7,597,096 | 5,108,493 | -32.8% |
| operations | 7,908,902 | 5,420,299 | -31.5% |
| all `kAssign` | 2,939,224 | 450,621 | -84.7% |
| `gsim.assign.*` | 2,546,486 | 57,883 | -97.7% |
| `gsim.expr.* kAssign` | 392,724 | 392,724 | unchanged |
| node final assigns elided | 0 | 2,488,603 | +2,488,603 |
| node final assigns kept | 2,546,486 | 57,883 | -97.7% |
| export wall | 10:08.42 | 10:06.30 | essentially same |
| export max RSS | 99,913,696 KiB | 99,342,336 KiB | essentially same |

`operationCount` 和 `valueCount` 都恰好减少 2,488,603；新的总 `kAssign` 也恰好等于
392,724 个 coercion 加 57,883 个保守 final binding。说明优化没有把 assign 换成另一种 op，
也没有误删 coercion。

## 原 108-op schedule A/B

严格对比使用生成 run15 的 2026-07-14 20:27 `.venv` native binding，因为 7 月 15 日工作区
中的未提交 scheduler 修改已把内部 coarsen cap 放大为 108 x 32。两次都显式使用：

```text
max_op_in_compute_supernode=108
max_op_in_compute_node=108
split_oversize_compute_nodes=True
split_oversize_compute_node_max_ops=108
max_op_in_commit_supernode=4096
commit_guard_event_buckets=True
declared_value_compute_node_boundary=False
final_topo_policy=level-id
sched_batch_target_count=64
```

| 指标 | run15 baseline | assign elision | 差异 |
| --- | ---: | ---: | ---: |
| input eligible ops | 7,757,160 | 5,268,557 | -32.1% |
| input topo edges | 12,832,384 | 10,343,781 | -19.4% |
| source clones | 2,662,209 | 2,662,209 | unchanged |
| post-clone eligible ops | 10,419,369 | 7,930,766 | -23.9% |
| post-clone topo edges | 12,957,530 | 10,468,927 | -19.2% |
| compute nodes | 861,970 | 833,277 | -3.3% |
| compute supernodes | 112,840 | 84,439 | -25.2% |
| commit supernodes / max ops | 43 / 4,096 | 43 / 4,096 | unchanged |
| final DAG edges | 639,803 | 486,359 | -24.0% |
| boundary values | 690,268 | 649,072 | -6.0% |
| boundary activation edges | 1,607,471 | 1,483,050 | -7.7% |

LoadJson 从 24.947 s 降到 19.149 s。activity-schedule 从 run14 记录的 120.732 s 降到
103.223 s；结构主对照使用 run15 commit-cap stats。source clones 完全不变，表明消除的是
producer 后的 node binding，而不是 scheduler 为共享 source 建立的 clone 语义。

当前 7 月 15 日 binding 也做了补充运行：内部 3,456-op coarsen 下为 25,078 compute
supernodes、184,527 DAG edges，schedule 92.095 s，emit 47.195 s。该结果受未提交 scheduler
修改影响，不进入 run15 的严格主表。

## C++ 与 30 分钟编译

两边都由 run15 binding、108-op schedule、target 64 生成，均为 106 schedule TUs、33
state-init TUs 和 141 个 model C++ files：

| 指标 | run15 baseline | assign elision | 差异 |
| --- | ---: | ---: | ---: |
| C++ bytes | 1,320,746,311 | 1,222,146,841 | -7.5% |
| C++ lines | 10,681,780 | 9,960,904 | -6.7% |
| schedule `static_cast` occurrences | 14,515,110 | 12,082,761 | -16.8% |
| largest TU | 33,983,694 B | 36,157,553 B | +6.4% |
| write_grhsim_cpp | 69.870 s (run14) | 53.130 s | -24.0% |

30 分钟 gate 命令：

```bash
timeout 1800s make -C \
  ptmp/gsim_assign_elide_20260715/full/grhsim_emit_run15_binding \
  -j32 CXX=clang++ CXXFLAGS='-std=c++20 -O3'
```

结果为 exit 124、124/141 objects、archive absent。没有 compiler error、fatal error、OOM 或
残留 clang/make 进程。旧 run15 是 128/141，故总 bytes/casts 下降没有转化为 30 分钟完成数
提升。新剩余 17 个 TU 为 10.9--20.2 MB、31k--145k lines、162k--287k casts；旧剩余 13 个
为 16.0--23.6 MB、70k--183k lines、210k--384k casts。单 TU 变轻了，但重分区后有更多 TU
落入 clang `-O3` 长尾集合。

## 判断与后续

1. exporter-side retarget 应保留：它删除的是无语义增益的 node-final identity binding，且小回归、
   全量 JSON load 和 state/commit 结构均通过。
2. 不应继续删除 392,724 个 `gsim.expr.* kAssign`，它们承担真实 width/sign coercion；后续若要
   优化，应在保持转换语义的前提下改善 emitter expression，而不是把 op 直接抹掉。
3. 编译 gate 说明总 op/cast 数不是充分指标。下一步应按 TU/supernode 记录 expression depth、
   wide op、cast nesting 和 clang wall time，并针对剩余 17 个 TU 做 emitter-side local temporary
   materialization 或更细的 complexity-aware batching。
4. 工作区 scheduler 已改变 108 参数的实际含义；后续正式 A/B 必须固定 native binding 或把
   coarsen multiplier 暴露为显式参数，避免日志显示 108 而内部实际使用 3,456。

## 证据路径

```text
ptmp/gsim_assign_elide_20260715/full/logs/xs_gsim_executable_grh_export_assign_elide_20260715.log
ptmp/gsim_assign_elide_20260715/full/logs/import_emit_run15_binding.log
ptmp/gsim_assign_elide_20260715/full/logs/model_compile_run15_binding.log
ptmp/gsim_assign_elide_20260715/full/grhsim_emit_run15_binding/activity_schedule_supernode_stats.json
ptmp/gsim_assign_elide_20260715/full/run_import_emit_run15_binding.sh
```
