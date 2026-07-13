# NO0438 Reg-to-mem full-group profile gate

日期：2026-07-13

## 1. Implementation

按 [NO0437](./NO0437_scalar_array_true_merge_rejection_plan_20260713.md)，nested commit `9e2fc1a` 在
`wolvrix/lib/transform/reg_to_mem.cpp` 增加：

```text
WOLVRIX_REG_TO_MEM_PROFILE_ALL_GROUPS
```

实现共 18 行新增、1 行修改：

- pass 启动时读取一次环境变量；
- 空值、`0`、`false`、`off` 为关闭，其余非空值为开启；
- 记录 `config profile_all_groups=0/1`；
- 只将该 bool OR 到既有 `verboseGroup` 条件。

没有修改 discovery、group 排序、true-match、rewrite、intent annotation、stats 或 pass options。默认关闭时仍使用
`visited<=20 || every100 || members>=500 || decoded-write` 的原日志选择。

## 2. Build gate

重新构建：

```text
cmake --build wolvrix/build --target transform-reg-to-mem -j8
```

结果 exit 0，build log 无 warning/error。目标测试命令仍为
`wolvrix/build/bin/transform-reg-to-mem`，工作目录未改变。

## 3. Three-mode behavior gate

同一测试可执行文件分别在 unset、`0`、`1` 下运行：

| Mode | Exit | Pass invocations | Config records |
| --- | ---: | ---: | --- |
| unset | 0 | 33 | 33 x `profile_all_groups=0` |
| `0` | 0 | 33 | 33 x `profile_all_groups=0` |
| `1` | 0 | 33 | 33 x `profile_all_groups=1` |

将三份日志仅归一化 config bit 和所有 timing fields 后，SHA256 均为：

```text
ed782ca0a79092a96171e1a93b4afb706e2c2ff9dca21fe373ff53ce371bb433
```

三份 normalized logs 逐字节一致，证明测试图上的 group outcome、stats 和 rewrite trace 未因开关变化。测试中的 group
数量都不超过原 verbose threshold，因此开启模式没有额外 group body；完整 SimTop 才用于验证扩展日志覆盖。

## 4. Next gate

下一步 editable reinstall 后，从 NO0357 同一 pre-reg checkpoint 运行 `STOP_AFTER_PRE_SCHED=1`，要求 4,318 groups 和
`835/174/254` true/edge/intent 计数精确复现，再解析 NO0436 的 140 flattened states。短测试通过不替代该 SimTop
结构门禁。

## 5. Artifacts

```text
build/logs/xs_perf/no0437/build.log
build/logs/xs_perf/no0437/test_{default,zero,all_groups}.log
build/logs/xs_perf/no0437/test_{default,zero,all_groups}.normalized
```
