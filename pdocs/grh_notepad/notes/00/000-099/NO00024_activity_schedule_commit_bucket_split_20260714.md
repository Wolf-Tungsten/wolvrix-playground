---
id: NO00024
date: 2026-07-14
title: Activity-schedule oversized commit guard bucket splitting
kind: fix-validation
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, activity-schedule, commit-supernode, xiangshan]
parents: [NO00023]
related: [NO00002, NO00009]
supersedes: []
---

# NO00024 Activity-schedule oversized commit guard bucket splitting (2026-07-14)

> 归档编号：`NO00024`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## 异常

run14 的 GSim executable GRH 导入成功，但 schedule shape 明显异常：

```text
commit sink ops=152,912
commit event keys=6
commit supernodes=7
commit ops max=111,852
```

最大 commit translation unit 为：

```text
grhsim_SimTop_sched_69.cpp=99,233,042 bytes
```

完整 GrhSIM 编译因此出现单文件长尾。编译已按要求停止，未生成 `emu`。

`activity-schedule` 的公开参数与普通 SV 路径一致，包括：

```text
max_op_in_compute_supernode=108
max_op_in_compute_node=108
max_op_in_commit_supernode=4096
commit_guard_event_buckets=True
declared_value_compute_node_boundary=False
final_topo_policy=level-id
```

差异来自输入流水线。普通路径会执行完整 pre-schedule normalization 和 `reg-to-mem`；GSim
executable 路径为 `read_json_file -> activity-schedule`，明确跳过这些 pass。

## 根因

开启 `commitGuardEventBuckets` 时，旧实现会把超过 `maxOpInCommitSupernode` 的单个 guard bucket
整体放入一个 commit node。因此 `4096` 只限制 bucket 之间的合并，没有切开单个 oversized bucket。

run14 的两个主要 oversized bucket 分别包含 111,852 和 37,554 个普通
`kRegisterWritePort`，共享同一 event/guard；它们不是 ordered memory-write 原子组。

## 修复

`activity_schedule.cpp` 现在按以下规则处理 oversized guard bucket：

1. 使用 `buildAtomicSinkUnits` 将普通 sink 视为单 op unit。
2. 按 `maxOpInCommitSupernode` 将 unit 打包为多个 commit node。
3. 带 priority 的 ordered memory-write group 保持不可拆分，避免改变写优先级。
4. 在最终 DAG 中按 partition 创建顺序串联 commit nodes，保证分片后仍保持 sink 执行顺序。

回归测试 `commit_guard_event_oversize_bucket` 已改为验证普通同-guard sink 受 cap 限制；
`ordered_memory_write_atomic_chunk` 同时覆盖 ordered memory-write 原子例外。

```text
ctest --test-dir wolvrix/build -R '^transform-activity-schedule$' --output-on-failure
1/1 passed

ctest --test-dir wolvrix/build \
  -R '^(emit-grhsim-cpp|emit-grhsim-cpp-memory-fill|transform-activity-schedule)$' \
  --output-on-failure
3/3 passed
```

## run15 schedule-only 验证

输入仍为 run14 的同一份 3.3 GB executable GRH，只执行 LoadJson 和 activity-schedule：

```text
commit supernodes: 7 -> 43
commit ops max: 111,852 -> 4,096
compute supernodes: 112,840 -> 112,840
compute ops max: 108 -> 108
final supernodes: 112,847 -> 112,883
activity-schedule=118.327 s
wall=2:25.36
maxRSS=34,283,976 KiB
exit=0
```

统计文件：

```text
ptmp/gsim_full_exec_20260714/run15_schedule_commit_cap/activity_schedule_supernode_stats.json
```

## 干净 emit 验证

新目录从 executable GRH 重新调度并 emit，没有复用 run14 文件：

```text
ptmp/gsim_full_exec_20260714/run15_grhsim_emit_commit_cap
write_grhsim_cpp=74.363 s
wall=3:38.57
maxRSS=34,284,456 KiB
exit=0
```

生成结果：

```text
schedule translation units: 71 -> 106
all C++ files: 106 -> 141
largest commit TU: 99,233,042 -> 4,920,546 bytes
commit TU count: 6 -> 41
directory size: about 1.3 GiB
```

commit 代码总量基本不变，但已分散到可并行构建的小文件。新目录中最大的 C++ 文件约 34 MB，
属于 compute schedule，不再是超大 commit node。

## Difftest wrapper

此前编译还暴露了 GSim aggregate port ABI 与传统 flat ABI 命名不同，例如：

```text
flat: difftest_uart_out_valid
GSim: difftest__uart__out__valid
```

`testcase/xiangshan/difftest/src/test/csrc/grhsim/grhsim_port_abi.h` 提供编译期双 ABI adapter，
`grhsim.h` 通过该 adapter 访问全部必需端口，不使用运行时 stub。

## 30 分钟完整 emu 构建尝试

使用独立 build 目录、`VM_BUILD_JOBS=32` 和 `-O3`，在外层设置 30 分钟硬超时：

```text
BUILD_DIR=ptmp/gsim_full_exec_20260714/run15_difftest_commit_cap
GRHSIM_MODEL_DIR=ptmp/gsim_full_exec_20260714/run15_grhsim_emit_commit_cap
log=ptmp/gsim_full_exec_20260714/run15_grhsim_emu_build_commit_cap.log
start=2026-07-14 23:27:04 +0800
stop=2026-07-14 23:57:04 +0800
exit=124 (timeout)
```

结果：

```text
difftest wrapper objects=40
model objects=128/141
remaining model objects=13
model archive=absent
grhsim-compile/emu=absent
```

日志中没有 compiler `error`、fatal error 或 OOM，只有既有的 tautological-comparison warnings。
全部拆分后的 commit translation units 已完成；剩余 13 个均为 16.0--23.6 MB 的 compute schedule
translation units。超时终止后没有残留 clang/make 进程，已有对象可供后续增量续编。

## 后续

完整 emu 尚未生成。恢复时复用上述 run15 model/build 目录增量完成剩余 compute objects、archive 和链接，
随后先运行 2k sanity，再运行最终 CoreMark `-C 50000` NEMU difftest。
