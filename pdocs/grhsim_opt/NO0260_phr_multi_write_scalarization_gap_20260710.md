# NO0260 PHR multi-write scalarization gap

日期：2026-07-10

## 背景

[NO0259](./NO0259_state_read_reuse_post_profile_20260710.md) 显示 candidate 的
`eval_compute_batch_54()` 占 50k sampled cycles 的 `2.30%`，其中 `154/245` sample 落在
`kLogicAnd`。本轮把 sampled operation id 反查到同一份 pre-reg-to-mem JSON 的 RTL
source location，并与同 FIR 的 GSIM 代码对照。

## Sample 来源

产物：

```text
build/logs/xs_perf/no0258/grhsim_state_read_change_compute_batch_54_sample_modules.tsv
build/logs/xs_perf/no0258/grhsim_state_read_change_compute_batch_54_static_modules.tsv
```

在能映射回 pre-reg-to-mem operation 的 `199` 个 sampled ops 中：

| RTL file | samples | mapped share |
| --- | ---: | ---: |
| `Phr.sv` | `153` | `76.88%` |
| `AheadBtb.sv` | `10` | `5.03%` |
| `LogPerfEndpoint.sv` | `9` | `4.52%` |
| 其它 | `27` | `13.57%` |

以全部 `245` 个 batch54 samples 为分母，`Phr.sv` 仍占 `62.45%`。

## 静态结构

batch54 normal 函数共有 `28495` 个 operation comments。`21123` 个可回查到原始 pre-reg
JSON，其中：

| RTL file | ops | mapped share | all-op lower bound |
| --- | ---: | ---: | ---: |
| `Phr.sv` | `13828` | `65.46%` | `48.53%` |

`Phr.sv` 的 batch54 operations 为：

| kind | count |
| --- | ---: |
| `kLogicAnd` | `13489` |
| `kLogicOr` | `329` |
| `kMux` | `10` |

这些逻辑主要为 `phr_0..531` 的多路动态写生成逐行 one-hot 条件和优先级 data。以
`phr_157` 为例，SV 对同一个 scalar register 展开了多条：

```systemverilog
if (addr_0 == 10'h9d) phr_157 <= data_0;
else if (addr_1 == 10'h9d) phr_157 <= data_1;
...
else if (update_addr_12 == 10'h9d) phr_157 <= update_data_12;
```

因此 GrhSIM 必须在 compute phase 评估约 `532 * 25` 个 LogicAnd，并在 commit phase 扫描
532 个 scalar write。

## GSIM 对照

同 FIR 的 GSIM 状态声明为：

```cpp
uint8_t ...phr[1024];
uint8_t ...phr$NEXT[1024];
```

实际 active rows 为 532；commit 用一个 loop 复制：

```cpp
for (int i = 0; i < 532; ++i) phr[i] = phr$NEXT[i];
```

动态更新保留为 28 条索引写，而不是转成每行 one-hot：

```cpp
phr$NEXT[new_ptr_0] = data_0;
...
phr$NEXT[new_ptr_27] = data_27;
```

相关文件与 profile：

| GSIM function | 主要关系 | profile share | text size |
| --- | --- | ---: | ---: |
| `subStep325()` | PHR dynamic writes | `0.35%` | `0x1cc04` |
| `subStep19()` | array commit loop 等 | `0.71%` | `0x5daaa` |
| `subStep83()` | PHR packed reads 等 | `0.29%` | `0x166b4` |
| `subStep296()` | PHR value construction 等 | `0.10%` | `0xfe75` |

这些函数不一定只含 PHR，因此不能把 share 简单相加当成 PHR 精确时间；但代码形态差异是
确定的：GSIM 保留 array + indexed writes，GrhSIM 恢复失败后保留 scalar + one-hot network。

## 当前 reg-to-mem 为什么未命中

现有 `reg-to-mem` 的正确默认模式由
[NO0205](./NO0205_reg_to_mem_single_user_correct_mode_20260623.md) 固化：anchor discovery
要求 concat result 和每个 register-read result 都是 single-user。PHR 的 scalar read 同时被
packed dynamic read和其它普通逻辑使用，因此不会进入当前 candidate group。

即使放宽读侧，现有 true matcher 也只支持：

- 一个动态 point-write family；
- 可选一个 reset/fill family；
- 或 reset + 单个 point write 的 compound shape。

PHR 有 28 个按优先级排列的动态写，当前 `RegularWriteFamily` 无法表达。

## 结论

PHR multi-write scalarization 是当前 GrhSIM 相对 GSIM 的具体额外工作来源，至少占 batch54
约一半静态 ops，并覆盖约 `62%` dynamic samples。不能通过重新打开 shared-read intent
解决，因为 NO0205 已证明该路径会造成 storage ownership 误归属和 SimTop correctness
失败。

安全方向必须是独立 true-rewrite：只有完整证明读闭包、28 个 priority writes、reset 和
事件顺序后才把 scalar registers 改写为 memory；匹配失败时不打 intent attrs。实施计划见
[NO0262](./NO0262_multi_write_true_merge_plan_20260710.md)。
