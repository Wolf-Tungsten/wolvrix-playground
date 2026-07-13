# NO0513 Sparse-batch volatile threshold audit gate

日期：2026-07-13

## 1. Sweep result

按 [NO0512](./NO0512_sparse_batch_volatile_threshold_audit_plan_20260713.md)，将 NO0503 plain 与 NO0511 all-volatile
真实 O3 objects 按 per-batch eligible-word threshold `0..37` 组合，并联结 NO0500 50k profile。关键变化点为：

| Threshold | Volatile words | Hit share | Miss share | Text vs baseline | Instructions | Memory | Jumps | Gate |
|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 0 | 0 | 0% | 0% | +10,145 | +1,536 | +1,131 | +153 | fail |
| 1 | 8 | 7.48% | 8.34% | +9,274 | +1,390 | +930 | +150 | fail |
| 2 | 20 | 18.69% | 22.99% | -2,049 | -352 | -225 | -89 | **pass** |
| 3 | 26 | 24.30% | 29.07% | -1,890 | -317 | -221 | -94 | fail: >20% words |
| 8 | 49 | 45.79% | 52.81% | -1,445 | -223 | -194 | -99 | fail: hot batch 21 |
| 37 | 107 | 100% | 100% | +398 | +148 | -53 | -103 | fail |

只有 threshold 2 同时满足四项不差于 plain、text/instructions 低于 baseline、volatile words `<=20%` 和 hot
35/58/21 保持 direct。threshold 1 未包含两-word batch 27，故仍保留主要 cliff；threshold 3 虽静态仍改善，但扩大到
24.30% words，超过预设暴露门限。

## 2. Threshold-2 composition

规则只读取每个 batch 的 eligible pure-event word 总数：

```text
eligible <= 2: local volatile-copy outer predicate
eligible >  2: direct outer predicate
```

它选择 14 个 batches、20/107 words：

```text
12, 16, 18, 20, 22, 24, 25, 27, 37, 50, 51, 56, 57, 61
```

列表只是规则在当前 SimTop 上的结果，不进入实现。NO0500 动态覆盖为：

```text
hit          1,001,000  (18.6916%)
miss         1,597,203  (22.9858%)
total        2,598,203  (21.1167%)
```

五个 miss-hot batches 35/58/21/41/30 全部保持 direct predicate；它们合计覆盖 `67.29%` misses，继续获得 outer
condition 对内部 event checks 的 hit-path simplification。

## 3. Static closure

threshold-2 hybrid 相对 NO0357 baseline：

```text
.text           -2,049 bytes
instructions      -352
memory forms       -225
jumps               -89
calls                 0
```

相对 plain production candidate 进一步减少 `12,194` text bytes、`1,888` instructions、`1,356` memory forms 和
`242` jumps，calls 不变。组合使用的是逐 TU 真实 plain/volatile objects，不是按 wrapper 数推算。

## 4. Decision

threshold-2 通过 audit，可进入默认仍关闭的 bypass emitter 实现 gate。实现不得包含当前 batch ids，只能在 batch word
结构确定后统计 eligible 数并选择 predicate shape；synthetic 必须覆盖 1/2/3 eligible words 的边界、default/source identity、
hit/miss 功能与原有负向 eligibility。之后 fresh SimTop 应精确得到同一 14 batches/20 volatile words，并重新 O3 build/function。

本 gate 只证明静态 hybrid 优于 plain/baseline；最终仍需在共享负载恢复后与 NO0357、plain candidate 做 fixed-ASLR runtime
对比，不能由 object aggregate 宣布提速。
