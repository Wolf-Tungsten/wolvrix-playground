# NO0441 Branch-not-in-update shape diagnostic gate

日期：2026-07-13

## 1. Implementation

按 [NO0440](./NO0440_outer_reset_mux_recovery_audit_plan_20260713.md)，nested commit `479932a` 增加默认关闭的：

```text
WOLVRIX_REG_TO_MEM_PROFILE_BRANCH_NOT_IN_UPDATE
```

环境值解析复用 full-group profile 的空值/`0`/`false`/`off` 关闭规则。开关只在 consolidated matcher 即将返回
`branch_not_in_update` 时扫描 group，不改变 return value、候选顺序、stats 或 IR。

每条 `branch_not_in_update_shape` 汇总：

- 顶层 mux rows 与共同 guard；
- guard 对 write events 的相同/取反关系、event index 和 polarity；
- 共同 updateCond、mask、events 和 edges；
- 常量 reset-arm rows；
- normal arm 根 operation-kind histogram；
- normal arm 到同 row `kRegisterReadPort` 的依赖。

依赖 DFS 每行最多访问 2,048 values；超限单列为 `normal_truncated_rows`。实现没有把超限当成无 self dependency。

## 2. Targeted test

新增 4-row/1-bit 最小图：

```text
updateCond = common lock
nextValue  = !reset ? normal_data : 1'b0
events     = posedge clock, posedge reset
```

它保留 concat/slice array read anchor，但 current matcher 必须继续拒绝。开关开启时精确输出一条：

```text
rows=4 outer_mux_rows=4
common_guard=1 relation_polarity=-1 relation_event_index=1
guard_negated_event_rows=4 constant_reset_rows=4
normal_no_self_rows=4 normal_truncated_rows=0
normal_roots=source:4 reset_roots=kConstant:4
```

pass 后仍有 4 个 `kRegister` 和 4 个 `kRegisterWritePort`、0 memory，证明诊断没有掩盖或改写拒绝。

## 3. Build and behavior gate

`transform-reg-to-mem` target 重建 exit 0，wall `6.33s`、maximum RSS `337,920 KiB`，build/test logs 无
warning/error。测试 executable 在 unset、`0`、`1` 下均完成 34 次 pass invocation 并 exit 0。

去掉开启模式唯一的 shape record，并归一化 config bit 和 timing fields 后，三份日志 SHA256 均为：

```text
eb70cc0cb4b0a55bed90d8d6224794488e53e872b7a7ee3fea71c4722b5e4885
```

## 4. Editable install gate

editable reinstall exit 0，site-package paths 为：

```text
.venv/lib/python3.12/site-packages/wolvrix/_wolvrix.so
.venv/lib/python3.12/site-packages/wolvrix/libwolvrix-lib.so
```

SHA256 分别为 `b5f0f212...` 和 `0f75f43a...`；core library 同时包含 env name 与
`branch_not_in_update_shape` string，允许进入 SimTop checkpoint audit。

## 5. Artifacts

```text
build/logs/xs_perf/no0440/build_with_test.{log,resource}
build/logs/xs_perf/no0440/test_{default,zero,audit}.{log,normalized}
build/logs/xs_perf/no0440/install.{log,resource}
```
