# NO0060 `merge-reg` All Strategies Probe 合并效果记录

## 1. 目的

使用 `scripts/xs_scalar_memory_pack_probe.py` 对当前 `merge-reg` 全策略组合做一次 replay probe，只记录 IR 层面的合并效果，不重新 emit / build / run `grhsim`。

本次输入沿用当前 XiangShan `grhsim` checkpoint：

```text
build/xs/grhsim/after_flatten_simplify.json
```

该 checkpoint 是 `flatten-simplify` 后、`merge-reg` 前的 GRH JSON。

## 2. 执行命令

```bash
python3 scripts/xs_scalar_memory_pack_probe.py \
  build/xs/wolf/wolf_emit/xs_wolf.f \
  SimTop \
  build/xs/scalar_memory_pack_probe_all_strategies_per_strategy_20260503 \
  build/xs/grhsim/grhsim_emit/wolvrix_read_args.txt \
  info \
  --resume-checkpoint-json build/xs/grhsim/after_flatten_simplify.json
```

`merge-reg` pass 本轮使用默认参数。当前默认参数等价于全部策略开启：

```text
scalar-to-memory
bundle-shift-pipeline-to-wide-register
indexed-bundle-entry-to-wide-register
onehot-indexed-bank-to-wide-register
bitset-to-wide-register
shift-chain-to-wide-register
```

## 3. 关键日志

`merge-reg` 输出：

```text
merge-reg: merge-reg: graphs=1 candidate_clusters=2171 candidate_members=38329 bundle_pipeline_clusters=81 bundle_pipeline_members=3986 indexed_bundle_entry_clusters=7896 indexed_bundle_entry_members=108549 rewritten_bundle_pipeline_clusters=80 rewritten_bundle_pipeline_members=3978 rewritten_indexed_bundle_entry_clusters=10085 rewritten_indexed_bundle_entry_members=106757 rewritten_onehot_indexed_bank_clusters=0 rewritten_onehot_indexed_bank_members=0 rewritten_bitset_clusters=1 rewritten_bitset_members=36 rewritten_shift_chain_clusters=36 rewritten_shift_chain_members=3453 rewritten_clusters=10202 rewritten_members=114224 scalar_to_memory_changed=true strategies=scalar-to-memory,bundle-shift-pipeline-to-wide-register,indexed-bundle-entry-to-wide-register,onehot-indexed-bank-to-wide-register,bitset-to-wide-register,shift-chain-to-wide-register
```

含义：

- `strategies` 确认 6 个策略全部开启。
- `scalar_to_memory_changed=true` 表示 scalar-to-memory 子策略有实际改写。
- `rewritten_clusters=10202` / `rewritten_members=114224` 是 wide-register 类策略的改写规模，不包含 scalar-to-memory report 中的 memory rows。
- `rewritten_*_clusters/members` 字段给出了各 wide-register 子策略在同一次 all-strategies run 中的真实归因。

## 4. 寄存器集合变化

来自 `summary.json` / `merge_reg_register_report.json`：

| 指标 | 数量 |
| --- | ---: |
| 合并前 `kRegister` | `286014` |
| 合并后 `kRegister` | `117256` |
| 原始寄存器被消除 | `178960` |
| 原始寄存器仍残留 | `107054` |
| 新建聚合寄存器 | `10202` |
| 净减少 `kRegister` | `168758` |

比例：

- 原始寄存器消除率：`178960 / 286014 = 62.57%`
- 净 `kRegister` 减少率：`168758 / 286014 = 59.00%`
- residual 占原始寄存器比例：`37.43%`

这里“原始寄存器被消除”包含被改写成 memory row 的 scalar register，也包含被改写成 wide register lane 的 scalar register。

## 5. 策略贡献拆分

`scalar-to-memory` 的详细 report：

```text
build/xs/scalar_memory_pack_probe_all_strategies_per_strategy_20260503/merge_reg_scalar_memory_pack_report.json
```

本轮 report 中：

- `records=64736`
- `clusters=570`
- 平均每个 memory cluster 收回 `113.57` 个 scalar register

按 row_count 聚合的主要分布：

| row_count | records |
| ---: | ---: |
| `512` | `34816` |
| `64` | `21376` |
| `256` | `3328` |
| `1024` | `2048` |
| `16` | `1632` |
| `128` | `768` |
| `32` | `544` |
| `8` | `224` |

按 width 聚合的主要分布：

| width | records |
| ---: | ---: |
| `2` | `38216` |
| `1` | `9760` |
| `5` | `3216` |
| `6` | `3176` |
| `3` | `2088` |
| `64` | `1976` |
| `8` | `1672` |

同一次 all-strategies run 中，各策略对“原始寄存器被消除”的贡献如下：

| 策略 | 改写 clusters | 消除的原始寄存器 | 占总消除比例 |
| --- | ---: | ---: | ---: |
| `scalar-to-memory` | `570` memory clusters | `64736` | `36.17%` |
| `bundle-shift-pipeline-to-wide-register` | `80` | `3978` | `2.22%` |
| `indexed-bundle-entry-to-wide-register` | `10085` | `106757` | `59.65%` |
| `onehot-indexed-bank-to-wide-register` | `0` | `0` | `0.00%` |
| `bitset-to-wide-register` | `1` | `36` | `0.02%` |
| `shift-chain-to-wide-register` | `36` | `3453` | `1.93%` |
| 合计 | `10772` | `178960` | `100.00%` |

说明：

- `scalar-to-memory` 的 `64736` 来自 memory pack report 的 row records；cluster 数 `570` 是按 `(graph, cluster_index, memory)` 去重后的 memory cluster 数。
- 其它 5 个策略来自 `merge-reg` 日志中的 per-strategy `rewritten_*_clusters/members` 字段。
- 5 个 wide-register 策略合计 `114224`，与 `merge-reg` 总日志中的 `rewritten_members=114224` 对齐。
- 6 个策略合计 `178960`，与寄存器集合报告中的 `merged_register_count=178960` 对齐。

## 6. 产物

本轮输出目录：

```text
build/xs/scalar_memory_pack_probe_all_strategies_per_strategy_20260503
```

关键文件：

```text
summary.json
after_flatten_simplify_plus_merge_reg.json
merge_reg_register_report.json
merge_reg_all_registers_sorted.txt
merge_reg_merged_registers.txt
merge_reg_residual_registers.txt
merge_reg_created_registers.txt
merge_reg_scalar_memory_pack_report.json
```

文件规模快照：

```text
after_flatten_simplify_plus_merge_reg.json  2.7G
merge_reg_all_registers_sorted.txt          24M
merge_reg_merged_registers.txt              15M
merge_reg_residual_registers.txt           8.9M
merge_reg_created_registers.txt            1.8M
merge_reg_scalar_memory_pack_report.json    19M
summary.json                               3.3K
```

## 7. 结论

在当前 `2026-05-03` checkpoint 上，`merge-reg` 全策略 replay probe 能消除 `178960` 个原始 `kRegister`，净减少 `168758` 个 `kRegister`。其中最大贡献来自 `indexed-bundle-entry-to-wide-register`，消除 `106757` 个原始寄存器，占总消除数 `59.65%`；其次是 `scalar-to-memory`，消除 `64736` 个，占 `36.17%`。

本次 probe 与 [`NO0059`](./NO0059_merge_reg_all_strategies_coremark_50k_20260503.md) 的 full build / 50k runtime 记录使用同一组全策略语义；`NO0059` 证明全策略组合可构建并跑满 50k，本篇只固化合并规模和产物位置。
