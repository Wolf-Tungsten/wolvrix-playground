# NO0334 NO0300 sched object-order probe plan

日期：2026-07-12

## 1. 依据与 GSim 对照

[NO0333](./NO0333_batch_function_page_alignment_runtime_gate_20260712.md) 已证明，只改 batch 地址即可让
NO0286/NO0300 相对 cycles 摆动约 10 percentage points，但全同 page offset 的 4 KiB alignment 不是可保留
方案。本轮去掉 alignment/padding，只改变函数物理顺序。

同一 FIR 的执行顺序与地址顺序对照为：

| Model | Functions | Runtime call order | Address-adjacent pair is next call | Address-order descents |
| --- | ---: | --- | ---: | ---: |
| GSim NO0255 | 329 `subStep` | `0 -> 328` | 5 / 328 (1.52%) | 157 |
| GrhSIM NO0300 | 117 batch | `0 -> 116` | 116 / 116 (100%) | 0 |

GSim 与 GrhSIM 都按编号调用函数，但 GSim Makefile 用 filesystem `find` 收集 model objects，当前 binary 的
物理顺序几乎完全打散；GrhSIM generated Makefile 和 archive 则严格按 sched 编号排列。结合 GSim 函数平均
text 约 147 KB、GrhSIM 约 739 KB，本轮检查“超大函数 + 执行顺序等于地址顺序”是否放大地址敏感性。

## 2. 唯一预声明排列

只测试一个 deterministic 7-bit bit-reversal order：对 batch id `0..116` 的 7-bit 表示反转 bit，再按反转值
升序排列。例如开头为：

```text
0, 64, 32, 96, 16, 80, 48, 112, 8, ...
```

该排列把连续执行 id 均匀分散，且不依赖本次性能结果。不得枚举多个随机 seed/order 后挑选最快者，否则会
把 layout 噪声过拟合成优化。

## 3. 构造与结构门禁

直接复用未对齐 NO0300 的原始 `.o`，保留 state/eval/state-init object 顺序，只重排 117 个 sched objects。
优先重建 archive；若静态链接器按 unresolved-symbol 而不是 archive member 顺序抽取，则改用显式 object input
list，并以最终 `nm -n` 为准。不得重新编译 object。

变体必须满足：

1. 117 个 batch 的最终地址顺序严格等于预声明 bit-reversal order；
2. 原始与变体的每个 batch symbol size 完全相同；
3. emu `.text` size 完全相同，不引入 alignment padding；
4. generated source/object SHA 或 inode 身份不变；
5. 变体 emu 与原 emu SHA 不同，证明链接布局确实变化。

## 4. 功能与性能门禁

先运行 10k，再运行 50k CoreMark/NEMU difftest；终点必须与 NO0300 完全一致。性能测试前检查全机 load、
CPU138 与 sibling 330，固定 CPU138/NUMA1 执行：

```text
NO0300 numeric baseline / NO0300 bit-reversal / NO0300 numeric baseline
```

采集 cycles、instructions、frontend empty slots 和 cmask6 cycles，全部须为 `100%` 调度。instructions 应在
计数噪声内不变；若 cycles/cmask6 density 稳定变化，则证明无 padding 的函数顺序本身可控。bit-reversal
只是诊断排列，即使变快也不直接作为默认顺序；后续需要用 profile/call transition 生成有依据的 deterministic
order。若变化很小，则 archive 级顺序不是 NO0300 的主要可操作层，转向单个超大函数内部 basic-block layout
或减小 batch 函数粒度。

## 5. 预定产物

```text
build/xs_grhsim_no0334_no0300_bitrev_order_20260712/grhsim
build/logs/xs_perf/no0334/
```
