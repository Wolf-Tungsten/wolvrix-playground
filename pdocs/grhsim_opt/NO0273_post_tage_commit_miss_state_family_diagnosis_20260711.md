# NO0273 Post-TAGE commit-miss state-family diagnosis

日期：2026-07-11

## 目标

承接 [NO0272](./NO0272_tage_true_merge_simtop_50k_gate_20260711.md) 的 post-profile，把新的
commit batch 头部 `95/84/88` 从“整个函数占比”继续拆到具体 write guard 和状态族。这里不按
generated C++ 中的静态 write 数量直接选目标，而是把每个 `branch-misses` sample 映射回对应的
`value_bool_slots_[N]` guard，再映射到 guard 控制的 GRH operation。

## 样本映射

输入仍为 NO0272 的 50k profile：

```text
build/logs/xs_perf/no0271/tage_true_merge_simtop_50k_branch_misses.data
samples: 11763
lost samples: 0
period: 500000
```

对三个符号执行 `perf annotate -n`。generated object 中 `value_bool_slots_` 的对象内基址为
`0x22bc8`；因此外层 guard 的 `cmpb $0, offset(%rbx)` 可以还原为
`slot = offset - 0x22bc8`。再用 generated C++ 中的 slot 与 operation comment 建立映射。

| batch | local samples | mapped outer write guards | other/skid |
| --- | ---: | ---: | ---: |
| `84` | `344` | `344` | `0` |
| `88` | `339` | `338` | `1` |
| `95` | `361` | `354` | `7` |

状态族聚合结果：

| batch | state family | samples | batch 内占比 | 全 profile 占比 |
| --- | --- | ---: | ---: | ---: |
| `84` | ROB `debug_VecOtherPdest` | `282` | `81.98%` | `2.40%` |
| `84` | ICache replacer | `20` | `5.81%` | `0.17%` |
| `88` | `logEndpoint` counters | `301` | `89.05%` | `2.56%` |
| `88` | FP regfile | `19` | `5.62%` | `0.16%` |
| `95` | `logEndpoint` counters | `225` | `63.56%` | `1.91%` |
| `95` | SBuffer `dataModule` | `92` | `25.99%` | `0.78%` |

这说明三个头部 batch 不是同一种问题。`logEndpoint` 两项合计占全 profile `4.47%`，但它们在
GSim 中也仍是独立 scalar counter，例如 `mshr_latency_5_230_240_4` 以普通 scalar `$NEXT`
计算并单独提交。SBuffer 当前包络更小，且 GSim 对代表性的 `data$NEXT_10_1_0` 也使用 scalar
状态。二者都不能仅凭名字或同一模块前缀直接 memory-pack。

逐样本 TSV 与 annotate 产物：

```text
build/logs/xs_perf/no0273/commit{84,88,95}_branch_misses_annotate_samples.report
build/logs/xs_perf/no0273/commit{84,88,95}_sample_slots.tsv
build/logs/xs_perf/no0273/commit{84,88,95}_sampled_blocks.tsv
```

## ROB 的 GSim / GrhSIM 结构差异

ROB 是三个批次中最明确的 aggregate-storage 差异。GSim 在 `SimTop.h` 中保留：

```cpp
uint8_t ...debug_VecOtherPdest[512][8];
uint8_t ...debug_VecOtherPdest$NEXT[512][8];
```

commit 时用双层循环提交实际 352 行：

```cpp
for (int i0 = 0; i0 < 352; ++i0)
    for (int i1 = 0; i1 < 8; ++i1)
        debug_VecOtherPdest[i0][i1] = debug_VecOtherPdest$NEXT[i0][i1];
```

GrhSIM batch84 则包含恰好 `352 * 8 = 2816` 个 `kRegisterWritePort`，每个 scalar write 都有独立
update guard。按采样周期估算，该状态族对应约 `141M` 次 branch misses。

这不是新发现的名字差异：[NO0050](./NO0050_scalar_memory_pack_vs_gsim_graphpartition_gap_20260430.md)
已把它列为最大的未收回 scalar group；本轮新增证据是它现在确实占 post-TAGE SimTop runtime
profile 的头部，而不只是静态 register-count 差异。

## 当前 matcher 为什么漏掉

pre-reg-to-mem IR 对每个内层 lane 生成一个 512-element concat，并由 8 个动态 dequeue index
共同读取。实际 storage 只有 352 个 register；为了覆盖 9-bit index 空间，concat 形态为：

```text
[row0 repeated 160 times, row351, row350, ..., row1, row0]
```

因此现有 true-only discovery 的两个路径都失败：

1. 整个 512 序列没有较短的周期，`repeatedSequencePeriod()` 返回 512；
2. 前 512 个 operand 并不唯一，因为 row0 共出现 161 次。

该 padding 不能直接删除，否则会改变动态 index `352..511` 时 alias 到 row0 的现有图语义。

## 下一实现边界

可保持精确语义的通用方向是识别“单侧重复 edge value + 唯一 storage core”布局：

1. 只在去掉单侧 padding 后，剩余 core 全部唯一且 padding value 等于 core 边缘 value 时形成
   true-only storage candidate；
2. memory depth 使用唯一 core 的 352 行；
3. 不删除原 concat 和 dynamic slices，只把每个 scalar register read 替换为对应 constant-row
   memory read。padding operand 原本共享 row0 read result，替换后仍共享同一个 memory-read result；
4. 写侧继续经过现有 strict matcher，要求完整逐行覆盖、地址/数据/掩码/event family 一致；
5. synthetic case 必须显式检查 out-of-domain padding 仍 alias 到 edge row，不能只检查 register 数量。

目标是把 2816 个 scalar commit guards 收敛为按 lane 的少量 indexed memory writes；是否实际可改写
仍由下一阶段 stop-after matcher 诊断决定，不在本诊断中预设成功。

## 结论

post-TAGE 头部已经从函数级热点分解为三类不同状态。下一项最有证据的通用优化是 ROB
`debug_VecOtherPdest` 的 edge-padded aggregate storage；`logEndpoint` 和 SBuffer 暂时保留为后续
独立议题，避免把 scalar counter、二维 storage 和普通分散状态用同一规则误合并。
