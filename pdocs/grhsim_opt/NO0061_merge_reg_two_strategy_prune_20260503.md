# NO0061 `merge-reg` Two-Strategy Prune

## 1. 背景

[`NO0060`](./NO0060_merge_reg_all_strategies_probe_20260503.md) 已经用同一次 all-strategies replay probe 拆出各策略贡献：

| 策略 | 消除的原始寄存器 | 占比 |
| --- | ---: | ---: |
| `scalar-to-memory` | `64736` | `36.17%` |
| `indexed-bundle-entry-to-wide-register` | `106757` | `59.65%` |
| 其它四个策略合计 | `7467` | `4.17%` |

其中 `onehot-indexed-bank-to-wide-register` 在 all-strategies 口径下为 `0`，`bitset-to-wide-register` 仅 `36`，`bundle-shift-pipeline-to-wide-register` 与 `shift-chain-to-wide-register` 合计贡献也很小。

## 2. 本轮决策

`merge-reg` 只保留两个策略：

```text
scalar-to-memory
indexed-bundle-entry-to-wide-register
```

删除 / 下线的策略：

```text
bundle-shift-pipeline-to-wide-register
onehot-indexed-bank-to-wide-register
bitset-to-wide-register
shift-chain-to-wide-register
```

## 3. 代码调整

本轮收窄了外部 API：

- `MergeRegOptions` 只保留：
  - `enableScalarToMemory`
  - `enableIndexedBundleEntryToWideRegister`
- Python pass kwargs 只保留：
  - `enable_scalar_to_memory`
  - `enable_indexed_bundle_entry_to_wide_register`
- `scripts/wolvrix_xs_grhsim.py` 只读取上述两个环境变量。
- `merge-reg` 日志只输出 indexed-bundle-entry 的候选 / rewrite 计数，以及 scalar-to-memory 是否改变。

同时清理了旧策略对应的实现和测试 fixture，避免已下线策略继续留在执行路径或对外参数里。

## 4. 验证

构建：

```bash
cmake --build wolvrix/build --target transform-merge-reg
```

测试：

```bash
ctest --test-dir wolvrix/build --output-on-failure -R 'transform-(pass-manager|merge-reg|scalar-memory-pack)'
```

结果：

```text
100% tests passed, 0 tests failed out of 3
```

注：后续 [`NO0062`](./NO0062_merge_reg_inline_scalar_to_memory_20260503.md) 已将独立 `scalar-memory-pack` pass 下线并内联到 `merge-reg`，因此当前回归命令不再包含 `transform-scalar-memory-pack`。

## 5. 后续注意

历史文档 [`NO0053`](./NO0053_merge_reg_scalar_to_memory_only_coremark_50k_20260502.md) 到 [`NO0060`](./NO0060_merge_reg_all_strategies_probe_20260503.md) 仍按当时实现记录旧策略实验结果，不回改历史结论。

从本记录之后，“当前 `merge-reg` 默认策略”应理解为只包含 `scalar-to-memory` 与 `indexed-bundle-entry-to-wide-register`。
