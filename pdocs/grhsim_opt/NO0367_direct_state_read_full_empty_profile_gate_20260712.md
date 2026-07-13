# NO0367 Direct state-read full-empty profile gate

日期：2026-07-12

## 1. 有效性门禁

按 [NO0366](./NO0366_direct_state_read_full_empty_profile_plan_20260712.md) 的预声明口径，在 CPU138、NUMA1、
`setarch -R` 下串行完成 NO0300 / direct / NO0300 三轮 CoreMark 50k cmask6 fixed-period profile。

三轮都达到 guest cycles `50001`、`cycleCnt=49996`、`instrCnt=73580`、terminal PC `0x80001312`，没有
mismatch、assertion、abort、fatal/error 或 `input_fullpass_blocked`，`Total Lost Samples` 均为 0。quiet gate
首次通过值分别为：

| Run | CPU138 idle | CPU330 idle | Host time（仅 profile 参考） |
| --- | ---: | ---: | ---: |
| baseline1 | 99.67% | 99.67% | 78,033 ms |
| direct | 99.67% | 99.00% | 83,075 ms |
| baseline2 | 99.33% | 100.00% | 77,759 ms |

direct 和 baseline2 各有一次 quiet gate 未达到 99%，均保留失败样本并等待后重试。`perf record` 的 unwind/写盘会
扰动 host time，因此该列不作为 runtime 结论。

## 2. 总样本门禁

| Run | Samples | Approximate event count |
| --- | ---: | ---: |
| baseline1 | 16,940 | 169.40B |
| direct | 19,089 | 190.89B |
| baseline2 | 16,861 | 168.61B |

两次 baseline 均值为 `16,900.5`，spread 仅 `0.467%`，通过 `<=3%` 门限。direct 增加 `2,188.5`
samples，即 `+12.949%`；与 [NO0365](./NO0365_simtop_direct_state_read_fixed_aslr_runtime_gate_20260712.md)
无 record stat 的 cmask6 `+12.468%` 同向且只差 `0.481` 个百分点，采样方向可信。

`perf report` 中 baseline1/direct/baseline2 分别出现 117/116/116 个 batch symbols；缺失项是零样本的
`commit71` 或 `commit84`。两版 binary 的 `nm -S -C` 都能精确解析全部 117 个 symbols，连接工具将缺失样本按 0
处理，没有 unknown symbol。

## 3. phase 归因

NO0300 与 direct 的 activity schedule SHA256、117 个 batch ID 和 supernode membership 完全相同，因此同名 batch
可作严格逻辑对照。这里只复用 NO0300 static/fire TSV 连接 symbol 和 phase，不把它当作 direct 动态 work 计数。

| Phase | Baseline mean | Direct | Excess | Direct delta | Global excess share |
| --- | ---: | ---: | ---: | ---: | ---: |
| compute | 11,299.5 | 13,198 | +1,898.5 | +16.802% | 86.749% |
| commit | 5,278.5 | 5,545 | +266.5 | +5.049% | 12.177% |
| other | 322.5 | 346 | +23.5 | +7.287% | 1.074% |
| total | 16,900.5 | 19,089 | +2,188.5 | +12.949% | 100.000% |

新增 full-empty 前端延迟主要是 compute-wide 问题，不是 eval 主循环或单个 commit path。

## 4. batch 分散度

117 个 batches 中 88 个上升、26 个下降、3 个不变；正向增量合计 `+2,532.5`，负向合计 `-367.5`。
top-10/top-20/top-40 对总增量的覆盖分别只有 `33.745%/57.642%/88.508%`，不是少数函数垄断。

| Rank | Batch | Baseline mean | Direct | Excess | Delta | Direct markers | Size delta |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | compute33 | 138.5 | 230 | +91.5 | +66.065% | 0 | +0.001% |
| 2 | commit115 | 382.5 | 465 | +82.5 | +21.569% | 0 | +0.336% |
| 3 | compute1 | 191.5 | 270 | +78.5 | +40.992% | 5,612 | -4.386% |
| 4 | compute20 | 90.5 | 169 | +78.5 | +86.740% | 0 | +5.997% |
| 5 | compute3 | 123.5 | 196 | +72.5 | +58.704% | 1,708 | -1.613% |
| 6 | compute27 | 164.5 | 235 | +70.5 | +42.857% | 0 | +0.745% |
| 7 | compute32 | 182.5 | 253 | +70.5 | +38.630% | 0 | -1.549% |
| 8 | compute64 | 83.5 | 150 | +66.5 | +79.641% | 0 | +19.662% |
| 9 | compute13 | 82.5 | 147 | +64.5 | +78.182% | 0 | -4.618% |
| 10 | compute24 | 190.0 | 253 | +63.0 | +33.158% | 0 | +5.800% |

## 5. direct marker 与 native layout

只有 11 个 compute batches 包含 75,830 个 direct-read markers；它们只贡献 `+205.5` samples，即总增量
`9.390%`。另外 106 个无 marker batches 贡献 `+1,959.5`，占 `89.536%`。尤其 compute8 包含 46,779 个
markers，却从 baseline `323.5` 降到 direct `163` samples（`-49.614%`），其 symbol 同时缩小 `56.34%`。
因此不能把前端回退归因于 direct-read 访问本身。

但“无 marker”不等于代码未变：frontier/read-head 改写使 110 个 generated batch sources 和 objects 变化，它们合计
贡献 `+2,169.5` batch samples；仅有 7 个 source/object 完全相同的低采样 commit functions，合计变化 `-4.5`。
direct text 缩小也使 116/117 个 batch 入口地址及低 12-bit offset 改变，只有 compute0 保持入口不变。50 个 symbol
尺寸变化至少 1%，贡献总增量的 `63.742%`；size-byte delta 与 excess 的 Pearson 相关系数为 `+0.539`，但代码语义
和地址同时变化，相关性不能单独证明 layout 因果。

## 6. annotate 排除局部热点

对 top excess 中四类代表函数分别做 baseline/direct `perf annotate`：

| Batch | Baseline max IP | Direct max IP | Baseline top-10 IP | Direct top-10 IP |
| --- | ---: | ---: | ---: | ---: |
| compute33（size 几乎不变、无 marker） | 1.43% | 0.87% | 9.98% | 7.38% |
| commit115（小幅膨胀、无 marker） | 0.77% | 0.43% | 5.45% | 3.88% |
| compute1（缩小、有 marker） | 0.99% | 0.74% | 5.98% | 5.55% |
| compute20（膨胀、无 marker） | 2.06% | 2.37% | 14.42% | 14.19% |

cmask6 不是 precise event，这里只用 annotate 排除单 IP 集中。direct 最大值 `2.37%` 约等于 compute20 的 169
samples 中 4 个落在同一 `je`；没有复现 ordered-write probe 中 `92%~94%` 样本集中于 guard 的局部问题。

## 7. 结论与下一步

direct 的 `+12.949%` full-empty 回退是广泛、以 compute 为主的前端供给退化；它不集中在 direct-read markers、
单个 batch 或单条指令。当前 fresh emission 同时改变了 110 个函数体和 116 个入口地址，且尚未实测 direct 的动态
batch fire/eval rounds，所以仅靠本轮无法区分 native layout 与 activation locality。

下一步先做更便宜且因果边界更清楚的 4 KiB batch-function alignment probe：复用 NO0329 已构建并通过功能门禁的
NO0300 aligned binary，只把 NO0357 direct generated model 以同样参数重编。若固定 ASLR 下回退明显收敛，优先修复
layout；若保持约 6% cycles/13% cmask6 回退，再 fresh 构建 runtime-profile direct 统计 fire/rounds。

## 8. 产物

```text
build/logs/xs_perf/no0366/fixed_{baseline1,direct,baseline2}_cmask6_50k.data
build/logs/xs_perf/no0366/fixed_{baseline1,direct,baseline2}_cmask6_50k_emu.log
build/logs/xs_perf/no0366/fixed_{baseline1,direct,baseline2}_cmask6_50k_symbols.report
build/logs/xs_perf/no0366/batch_profile_join.{report,json}
build/logs/xs_perf/no0366/full_empty_batch_delta.{tsv,report}
build/logs/xs_perf/no0366/{baseline1,direct}_{compute1,compute20,compute33,commit115}_cmask6_annotate.report
```
