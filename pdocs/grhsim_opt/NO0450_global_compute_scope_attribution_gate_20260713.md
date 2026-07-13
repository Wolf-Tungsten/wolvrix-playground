# NO0450 Global compute scope-aware attribution gate

日期：2026-07-13

## 1. Input and validity

按 [NO0448](./NO0448_global_compute_scope_attribution_plan_20260713.md) 及
[NO0449](./NO0449_global_scope_source_line_correction_20260713.md)，本轮只重放 existing-artifact analyzer；没有重新编译、运行
仿真或采集 perf。输入仍为 NO0403 的 latest direct 5,590 个 compute leaf samples，以及 NO0357 的 66 个
production-identical sched sources。

有效性结果为：

| Row form | Samples | Gate result |
| --- | ---: | --- |
| Generated source-backed | 4,833 | 4,833/4,833 line join，0 source mismatch |
| Runtime-frame-only | 562 | 独立保留，不猜 operation kind |
| Unresolved | 195 | 独立保留，不猜 operation kind |
| Total | 5,590 | 全部进入原 direct/compute 分母 |

所有 non-empty recorded operation labels 均能在同 batch source 中定位；精确 value/side-effect body 内的旧 kind 与 scope parser
重新识别的 kind 为 0 mismatch。analyzer exit 0，wall `10.33s`，maximum RSS `349,448 KiB`。

## 2. Corrected ownership

互斥 scope 归属如下：

| Ownership | Samples | Direct total share |
| --- | ---: | ---: |
| Exact value body | 2,473 | 37.049% |
| Comment-only or fused | 1,210 | 18.127% |
| Runtime-frame-only | 562 | 8.419% |
| Shared supernode prelude | 489 | 7.326% |
| Shared supernode dispatch | 413 | 6.187% |
| Unresolved | 195 | 2.921% |
| Exact side-effect body | 130 | 1.948% |
| Shared supernode tail | 118 | 1.768% |

该拆分与 NO0404 的 normalized mechanism 独立闭合：413 个 entry-active samples 全部归 shared dispatch；444 个 changed
compare 和 313 个 slot writeback 全部归 exact body；159 个 changed accumulate 拆为 158 exact + 1 tail；304 个 activation
拆为 191 exact + 112 tail + 1 comment-only。由此确认 parser 没有继续把 next-supernode dispatch 或 deferred tail 继承给前一
operation。

旧 operation summary 的污染规模并非只影响 `kAssign`。例如旧 `kRegisterReadPort=920` 中 919 个实际是
comment-only/fused；旧 `kMux=544` 只有 317 个 exact body；旧 `kAssign=395` 则精确复现 NO0447 的 291 exact + 104 shared
边界。后续不能再直接使用 NO0403 的 nearest-current-op 排名作为实现依据。

## 3. Corrected exact-operation ranking

达到或接近 direct 1% 的 exact-body operation 为：

| Operation | Exact samples | Direct total share |
| --- | ---: | ---: |
| `kAnd` | 629 | 9.423% |
| `kMux` | 317 | 4.749% |
| `kAssign` | 291 | 4.360% |
| `kOr` | 222 | 3.326% |
| `kLogicAnd` | 197 | 2.951% |
| `kEq` | 195 | 2.921% |
| `kSliceStatic` | 136 | 2.037% |
| `kSystemTask` | 127 | 1.903% |
| `kLogicOr` | 90 | 1.348% |
| `kLogicNot` | 80 | 1.199% |
| `kConcat` | 66 | 0.989% |

这里的 aggregate 仍不能解释为 operation 本身的可删成本。以最大的 `kAnd` 为例，629 个 samples 分为 payload 206、changed
compare 150、operand/state read 84、slot writeback 64、activation 62、changed accumulate 60、runtime helper 3。真正的新候选
只有 206 个 payload samples/direct `3.086%`，其余是跨 operation 共用的 value/change boundary。

进一步读取 206 条实际 source：204 条是 scalar `const bool next_value = lhs & rhs`，1 条是 64-bit scalar AND，1 条是
编译器归在 body 末端的 activation helper；没有 full-width `and_words`。其中 148 samples/145 unique values 有稳定 FIR 名，58
samples 是匿名 `_val_*`。因此 NO0408 的 full-width helper gate 不能替代这项检查，而 stable values 足以连接 same-FIR GSim。

## 4. Decision

全局 scope correction 通过，NO0403 的旧 operation-kind summary 自此只保留历史初筛用途。当前不改 emitter：校正后的最大
`kAnd` aggregate 主要混合真实 payload 与通用 change boundary，尚不能据 629 samples 直接提出优化。

下一步对 204 个 scalar Boolean AND payload 做 same-FIR GSim source crosscheck：对 148 个稳定命名 samples 检查 GSim 是否也有
对应 AND assignment、old/new compare 和 activation；匿名 58 个单独作为无法连接上界。只有扣除两边共同实现后仍至少 67
samples/direct 1%，才进入机器码或 emitter probe；否则转向跨 operation 的 comment/fused + shared-prelude 形态，不重复
full-width logic 或 assign forwarding。

产物：

```text
build/logs/xs_perf/no0448/analyze_global_scope.py
build/logs/xs_perf/no0448/compute_sample_rows.tsv
build/logs/xs_perf/no0448/{ownership,corrected_operation,mechanism_scope}_summary.tsv
build/logs/xs_perf/no0448/{exact_operation_mechanism,exact_operation_family}_summary.tsv
build/logs/xs_perf/no0448/old_corrected_operation_compare.tsv
build/logs/xs_perf/no0448/analysis_summary.txt
```
