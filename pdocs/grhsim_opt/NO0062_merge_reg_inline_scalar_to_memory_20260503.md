# NO0062 `merge-reg` Inline Scalar-to-Memory

## 1. 背景

[`NO0061`](./NO0061_merge_reg_two_strategy_prune_20260503.md) 之后，`merge-reg` 只保留两个策略：

```text
scalar-to-memory
indexed-bundle-entry-to-wide-register
```

其中 `scalar-to-memory` 仍由独立的 `scalar-memory-pack` pass 实现和暴露。这样会留下两个入口：用户既可以直接运行 `scalar-memory-pack`，也可以通过 `merge-reg` 运行同一套逻辑。

## 2. 本轮决策

彻底移除独立 `scalar-memory-pack` 组件，只保留 `merge-reg` 内部的 `scalar-to-memory` 策略。

具体含义：

- `availableTransformPasses()` 不再列出 `scalar-memory-pack`。
- `makePass("scalar-memory-pack")` 不再注册独立 pass。
- CMake 不再构建 `transform-scalar-memory-pack` 测试目标。
- 旧的 `transform/scalar_memory_pack.hpp`、`lib/transform/scalar_memory_pack.cpp` 和独立测试文件删除。
- 原实现合并到 `wolvrix/lib/transform/merge_reg.cpp` 的私有 `scalar_to_memory` 命名空间中。

## 3. 兼容调整

`scripts/xs_scalar_memory_pack_probe.py` 仍用于 replay `merge-reg` 的寄存器合并效果，但 scalar-to-memory 细分报告不再使用旧环境变量：

```text
旧：WOLVRIX_SCALAR_MEMORY_PACK_REPORT_JSON
新：WOLVRIX_MERGE_REG_SCALAR_TO_MEMORY_REPORT_JSON
```

报告文件名同步改为：

```text
merge_reg_scalar_to_memory_report.json
```

内部日志和 `SrcLoc.pass` 也统一到 `merge-reg`，不再生成新的独立 `scalar-memory-pack` 标识。

## 4. 验证

构建：

```bash
cmake --build wolvrix/build --target transform-merge-reg
```

测试：

```bash
ctest --test-dir wolvrix/build --output-on-failure -R transform-merge-reg
```

结果：

```text
100% tests passed, 0 tests failed out of 1
```

额外检查：

- `cmake --build wolvrix/build --target help` 中不再有 `transform-scalar-memory-pack`。
- `rg 'scalar-memory-pack|ScalarMemoryPackPass|scalar_memory_pack' wolvrix` 无源码残留。
