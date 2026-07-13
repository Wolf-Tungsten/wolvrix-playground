# NO0518 SimTop sparse pure-event build and codegen gate

日期：2026-07-13

## 1. Build integrity

承接 [NO0517](./NO0517_simtop_sparse_pure_event_fresh_source_gate_20260713.md)，使用标准 Clang C++20 `-O3` 构建 fresh
hybrid model。Makefile 本轮内部选择 64 jobs；这只影响 build wall time，不作为性能结论。

```text
model: build/xs_grhsim_no0516_sparse_pure_event_20260713/grhsim/grhsim_emit
emu:   build/xs_grhsim_no0516_sparse_pure_event_20260713/grhsim/grhsim-compile/emu
log:   build/logs/xs/xs_wolf_grhsim_compile_no0518_sparse_pure_event_20260713.log
```

40 个 support CXX、1 个 PCH、152 个 generated CXX、117 个 sched objects、152-member archive 与最终 link 全部完成。
error/failed/undefined/killed scan 为 0，exit 0；wall `2:30.18`、peak RSS `1,270,232 KiB`。新 emu SHA256：

```text
eed8e6157dd113e11a5bee81b3101d9d4d01101937cef2b2fe582bb828e2b132
```

## 2. Real object comparison

沿用 NO0503 的 `size -A` 与 `objdump -drwC --no-show-raw-insn` 口径，对相同 22 个 eligible sched objects 做三方
比较。hybrid 相对 NO0357 baseline：

| Metric | Baseline | Hybrid | Delta |
| --- | ---: | ---: | ---: |
| `.text` bytes | 22,264,580 | 22,262,630 | -1,950 |
| instructions | 4,660,161 | 4,659,836 | -325 |
| memory forms | 1,928,608 | 1,928,381 | -227 |
| jumps | 135,170 | 135,079 | -91 |
| calls | 13,577 | 13,577 | 0 |

hybrid 相对 NO0501 plain bypass：

| Metric | Plain | Hybrid | Delta |
| --- | ---: | ---: | ---: |
| `.text` bytes | 22,274,725 | 22,262,630 | -12,095 |
| instructions | 4,661,697 | 4,659,836 | -1,861 |
| memory forms | 1,929,739 | 1,928,381 | -1,358 |
| jumps | 135,323 | 135,079 | -244 |
| calls | 13,577 | 13,577 | 0 |

batch 27 从 plain cliff 恢复 `.text/instructions/memory/jumps=-11,476/-1,781/-1,170/-240`；相对 baseline 只剩
`+1/+2/-6/-4`。全部 117 个 sched object 的 SHA 对照为 `103` identical、`14` changed，changed 集合精确等于
NO0517 的 sparse batch 集合，因此没有 source-identical object 构建噪声。

## 3. Full binary comparison

完整 emu 流式反汇编结果：

| Compared with | `.text` bytes | Instructions | Memory forms | Jumps | Calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| NO0357 baseline | -1,952 | -321 | -227 | -91 | 0 |
| NO0501 plain bypass | -12,080 | -1,859 | -1,357 | -244 | 0 |

full binary 与真实 object aggregate 同方向；小幅 text/instruction 数值差来自最终 link layout，不影响 gate 结论。

## 4. Decision

fresh build/link 与静态 codegen gate 通过，且消除了 NO0503 的 batch-27 cliff。下一步依次执行 100/10k/50k
CoreMark/NEMU 功能门禁；静态下降不等同 runtime 提速，fixed-ASLR 性能仍须等待满足 sibling-idle 的相邻 A/B/A。
