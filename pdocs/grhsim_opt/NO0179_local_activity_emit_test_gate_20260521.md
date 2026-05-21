# NO0179 Local Activity/Emit Test Gate

日期：2026-05-21

## 目的

在不启动 XiangShan fresh emit/build/runtime 的前提下，补一个本地轻量质量门，覆盖当前目标相关的两块代码：

- `grhsim-cpp` emitter；
- `activity-schedule` transform。

## 首次 CTest 结果

直接运行：

```sh
ctest --test-dir wolvrix/build --output-on-failure -R 'activity|grhsim'
```

结果：

| 测试 | 结果 |
| --- | --- |
| `emit-grhsim-cpp` | Passed |
| `emit-grhsim-cpp-memory-fill` | Failed, `NUMERICAL` |
| `transform-activity-schedule` | Passed |

单独运行旧二进制：

```sh
wolvrix/build/bin/emit-grhsim-cpp-memory-fill
```

退出码为 `139`，即段错误。

## 处理

考虑到 nested `wolvrix` 工作区已有源码改动，首次失败可能来自 stale test binary。先重建相关目标：

```sh
cmake --build wolvrix/build --target \
  emit-grhsim-cpp \
  emit-grhsim-cpp-memory-fill \
  transform-activity-schedule \
  -j$(nproc)
```

重建成功。

## 重测结果

重新运行：

```sh
ctest --test-dir wolvrix/build --output-on-failure -R 'activity|grhsim'
```

结果：

| 测试 | 结果 | 时间 |
| --- | --- | ---: |
| `emit-grhsim-cpp` | Passed | `56.56 sec` |
| `emit-grhsim-cpp-memory-fill` | Passed | `0.01 sec` |
| `transform-activity-schedule` | Passed | `0.01 sec` |

总结果：

```text
100% tests passed, 0 tests failed out of 3
Total Test time (real) = 56.58 sec
```

## 结论

当前源码对应的本地 activity/emit 相关轻量门通过。

首次 `emit-grhsim-cpp-memory-fill` 段错误不是当前源码重建后的失败，属于 stale binary 风险；后续在引用 CTest 结果前，应先确认相关目标已重建，尤其 nested `wolvrix` 处于 dirty 状态时。

本测试不能替代 latest default 的 XiangShan full emit/build/runtime 闭环。
