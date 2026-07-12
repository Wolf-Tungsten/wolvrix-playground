# NO0457 SimTop one-bit AND/OR static gate plan

日期：2026-07-13

## 1. Objective

[NO0456](./NO0456_one_bit_and_or_byte_emit_local_gate_20260713.md) 已通过 exhaustive fixture 与 local O3 gate，
但动态候选上界只有 direct `1.034%`。本阶段不直接 full build 或运行 SimTop，而是先从 NO0357 的同一
pre-reg-to-mem checkpoint fresh emit current SimTop，并对代表 compute batches 做 source/machine gate。

候选只新增：

```text
WOLVRIX_GRHSIM_ONE_BIT_BITWISE_BYTES=1
```

继续保留 NO0357 的 direct state-read、ordered/decoded reg-to-mem、`level-id`、108-op compute、4096-op commit、
64-batch target、4 路 emit 和 storage-ref aliases off。不开 full-word consume、runtime profile、waveform、perf 或
input/posedge fullpass specialization。

## 2. Inputs and output

```text
checkpoint:
  build/xs_grhsim_event_order_src_20260710/grhsim/wolvrix_xs_pre_reg_to_mem.json
read args:
  build/xs_grhsim_no0300_ordered_affine_fresh_20260712/grhsim/grhsim_emit/wolvrix_read_args.txt
reference source/objects:
  build/xs_grhsim_no0357_direct_state_read_20260712/grhsim/grhsim_emit
fresh output:
  build/xs_grhsim_no0457_one_bit_and_or_20260713/grhsim/grhsim_emit
```

执行前必须 `source env.sh` 并执行 editable reinstall。site-package `libwolvrix-lib.so` 必须包含
`one_bit_bitwise_bytes` 和 `grhsim_assume_bit_u8`，且实际加载路径必须指向当前 `.venv`；不能只依赖
`wolvrix/build/libwolvrix-lib.so`。

## 3. Fresh source gates

1. fresh flow exit 0，generated runtime 出现 `grhsim_assume_bit_u8`；
2. schedule stats SHA256 仍为
   `e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77`；
3. direct state-read 仍为 reads/canonical/aliases `75,830/40,108/35,722`；
4. generated file set、compute/commit batch 数和 graph/schedule 计数与 NO0357 一致；
5. default helper 以外，只允许 width-1 `kAnd/kOr` block 改写；XOR/XNOR/NOT、logical、compare、mux、reduce 和
   width > 1 bitwise source 不得变化；
6. candidate 中每个 assumed-byte block 必须能按 op comment/value marker 连接到 baseline 的同一 operation，不能用
   最近文本或跨 supernode 猜测归属。

## 4. Representative machine gates

先只编译 compute batch `0/1/29/32/43`。NO0454 的既有 machine audit 中，这五个 batch 覆盖 30 个
normalization samples：batch 0/1 覆盖 packed state operand，batch 29/32 覆盖 result normalization，batch 43
提供另一独立 source shape。

两侧均使用 generated `grhsim_SimTop.hpp` PCH 和：

```text
clang++ -std=c++20 -O3 -I. -include-pch grhsim_SimTop.hpp.pch -c grhsim_SimTop_sched_N.cpp
```

逐 object 比较：

- `.text` bytes、instruction、branch、memory-form instruction；
- assumed-byte source block 数及其 baseline/candidate disassembly；
- baseline 的 operand `cmpb/setne` 或 result `setne` 是否真实消失；
- changed compare、slot writeback 和 activation 是否仍存在。

至少三个不同 source shapes 必须真删 normalization，五个代表 objects aggregate `.text`、instructions、branches 和
memory-form 均不得增加。若 aggregate 通过但单 batch 增长，必须定位到具体 block，不能用其他 batch 收益掩盖局部回退。

## 5. Stop conditions

- schedule/direct-read identity 失败；
- fresh source 出现目标范围以外变化；
- helper 未内联，或 candidate 重新产生等价 bool normalization；
- 任一 changed/writeback/activation 语义结构消失；
- 代表 object aggregate 静态指标恶化；
- 不足三个独立 source shapes 真正删指令。

命中任一条件即保持开关默认关闭并停止，不进入 full build 或 SimTop runtime。全部通过后另起 full O3 build 和
100-cycle/10k/50k 功能计划；未完成这些功能 gate 前不作性能结论。
