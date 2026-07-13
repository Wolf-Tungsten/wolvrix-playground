# NO0503 SimTop pure-event word bypass build and codegen gate

日期：2026-07-13

## 1. Production build integrity

承接 [NO0502](./NO0502_simtop_pure_event_word_bypass_fresh_emit_gate_20260713.md)，使用标准 Clang 21.1.5、C++20
`-O3` 与 32 jobs 完成独立 difftest/GrhSIM build：

```text
model: build/xs_grhsim_no0501_pure_event_bypass_20260713/grhsim/grhsim_emit
emu:   build/xs_grhsim_no0501_pure_event_bypass_20260713/grhsim/grhsim-compile/emu
log:   build/logs/xs/xs_wolf_grhsim_compile_no0503_pure_event_bypass_20260713.log
```

40 个 support CXX、1 个 PCH 加 152 个 generated CXX、117 个 sched objects、152-member archive 和最终 link
全部完成，error/failed scan 为 0、exit 0。wall `3:35.15`、peak RSS `1,264,236 KiB`；当时全机 load 很高，
build 时间不作性能结论。candidate emu SHA256 为：

```text
86d544a8edc08d420785e2c292280398696f44993659a5a5efe082165ecfa6fe
```

## 2. Production object comparison

直接比较 NO0357 baseline 与 fresh candidate 的 22 对真实 sched objects，而不是 generated-copy probe。15 个 batches
的 `.text` 下降、7 个上升，aggregate 为：

| Metric | Baseline | Candidate | Delta |
|---|---:|---:|---:|
| `.text` bytes | 22,264,580 | 22,274,725 | +10,145 |
| instructions | 4,660,161 | 4,661,697 | +1,536 |
| memory forms | 1,928,608 | 1,929,739 | +1,131 |
| jumps | 135,170 | 135,323 | +153 |
| calls | 13,577 | 13,577 | 0 |

这不是预期的 aggregate 静态下降。回退几乎全部来自 batch 27：它单独增加 `11,477` text bytes、`1,783`
instructions、`1,164` memory forms 和 `236` jumps。扣除 batch 27 后，其余 21 batches 合计反而下降
`1,332` text bytes、`247` instructions、`33` memory forms 和 `83` jumps。

抽查 5 个 source-byte-identical batches 0/26/34/64/116，以上五项指标均为逐项 0 delta，排除了两次构建噪声。

## 3. Full binary comparison

对两侧完整 `emu` 流式反汇编，结果与 object aggregate 一致：

| Metric | Baseline | Candidate | Delta |
|---|---:|---:|---:|
| `.text` bytes | 87,114,910 | 87,125,038 | +10,128 (`+0.0116%`) |
| instructions | 16,991,219 | 16,992,757 | +1,538 (`+0.0091%`) |
| memory forms | 8,880,877 | 8,882,007 | +1,130 |
| jumps | 1,078,795 | 1,078,948 | +153 |
| calls | 32,318 | 32,318 | 0 |

主要 mnemonic delta 为 `mov +1,475`、`lea +984`、`shl -671`、`jmp +347`，不是每个 wrapper 固定增加几条
branch 的线性结果。

## 4. Batch 27 codegen cliff

batch 27 只有 active words 3136/3164 两个 wrapper。分别只保留其中一个时，相对 baseline 的结果为：

| Variant | Text bytes | Instructions | Memory forms | Jumps |
|---|---:|---:|---:|---:|
| only 3136 | +11,507 | +1,789 | +1,168 | +237 |
| only 3164 | +11,505 | +1,789 | +1,168 | +237 |
| both, production | +11,477 | +1,783 | +1,164 | +236 |

任意一个 wrapper 都触发近乎相同的整函数 codegen 跳变，两者同时反而略小，说明这是 Clang 巨型函数优化/布局阈值，
不是某个 payload 的线性膨胀。`[[likely]]` 与 production 同码；`unlikely(event-hit)` 仍回退 `10,447` bytes 和
`1,696` instructions，不能作为修复。

NO0500 profile 显示 batch 27 在 50k 有 `200,106` 次 active miss，机会并不冷；其 producer/task 规模也没有形成可推广
到 emitter 的语义阈值。因此本轮不按 batch id 掩盖，也不加入无充分依据的 branch hint。

## 5. Decision

build/link 完整性 gate 通过，但静态 codegen 结论明确标记为小幅回退和 batch 27 cliff，不声称静态优化成功。按
[NO0501](./NO0501_simtop_pure_event_word_bypass_fresh_plan_20260713.md) 的 runtime-primary 判据，先继续
100/10k/50k CoreMark/NEMU 功能门禁；只有功能通过后才执行 fixed-ASLR 相邻 baseline/bypass/baseline PMU 夹测。
若 runtime 不能覆盖这项回退，再针对 giant-function codegen cliff 形成独立候选，不在当前 production source 中临时打补丁。
