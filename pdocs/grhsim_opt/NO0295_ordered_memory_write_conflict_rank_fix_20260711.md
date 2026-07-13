# NO0295 Ordered memory-write conflict-rank fix

日期：2026-07-11

## 1. 修复范围

[NO0294](./NO0294_ordered_memory_write_priority_rank_failure_20260711.md) 证明 matcher 容器顺序不是优先级契约。本阶段只修复 ordered priority 的派生与回退条件，不改变 write-only discovery、addr/data/mask/event/reset/domain guard 或 activity-schedule contract。

## 2. 实现

对每个 `RegularWriteFamily`：

```text
semantic priority = regular.conflicts.size()
```

`conflicts` 列出会阻断当前 writer 的所有更高优先级 writers，因此最高优先级 rank 为 0，最低优先级 rank 为 `N-1`。

ordered lowering 现在要求：

```text
distinct rank count == writer count
minimum rank == 0
maximum rank == writer count - 1
```

只有三项同时成立才省略显式 conflict guards 并写入 ordered attrs。任何重复、缺口或越界都会保守回退到原 explicit-conflict lowering，不生成部分有序语义。profile 保留 rank range、distinct 数和 `rank != regularIndex` 统计，便于后续发现 matcher 形态变化。

## 3. 测试增强

65-writer write-only synthetic 不再只检查 priority 唯一，而是建立 address 到预期 writer rank 的映射：

```text
writer 0 address  -> priority 0
writer 1 address  -> priority 1
...
writer 64 address -> priority 64
```

这能直接拦截 NO0294 中“priority 集合仍为 `[0,N)`，但被赋给错误 writer”的问题。

## 4. 定向回归

执行命令均先 `source env.sh`：

```text
cmake --build wolvrix/build -j8 --target \
  transform-reg-to-mem transform-activity-schedule \
  emit-sv-storage-ports emit-grhsim-cpp

ctest --test-dir wolvrix/build \
  -R '^(transform-reg-to-mem|transform-activity-schedule|emit-sv-storage-ports|emit-grhsim-cpp)$' \
  --output-on-failure
```

结果：

```text
emit-sv-storage-ports       PASS   0.05 s
emit-grhsim-cpp             PASS 144.97 s
transform-activity-schedule PASS   0.02 s
transform-reg-to-mem        PASS   0.14 s
```

generated-model harness 的同地址 collision 与不同地址并行写继续通过；SV 和 activity-schedule 顺序 gate 也保持通过。

## 5. 下一步

本阶段尚未证明 SimTop 功能恢复。下一 gate 必须 fresh 生成并编译，先运行 10k，确认越过 NO0294 的 guest cycle 664；通过后再运行 50k。只要任一功能 gate 失败，就不进入 runtime 测试。
