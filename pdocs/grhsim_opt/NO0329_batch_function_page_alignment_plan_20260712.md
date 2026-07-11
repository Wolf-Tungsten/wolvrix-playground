# NO0329 Batch function page-alignment probe plan

日期：2026-07-12

## 1. 依据

[NO0323](./NO0323_no0286_no0300_frontend_full_empty_profile_20260712.md) 将 NO0300 的回退定位为
compute full-empty frontend latency，[NO0328](./NO0328_no0286_no0300_l2_instruction_pmu_gate_20260712.md)
又确认 L1I、ITLB、op-cache 和 L2 instruction miss-count 均未恶化。当前剩余假设之一是 native code layout：
NO0300 虽减少动态工作和机器指令，却改变了大批 compute/commit 函数的尺寸与后续函数地址。

同一 FIR 的已编译模型显示：

| Model | Generated translation units | Externally visible model functions | Mean function text |
| --- | ---: | ---: | ---: |
| GSim NO0255 | 331 | 329 `subStep` | 147,029 bytes |
| GrhSIM NO0286 | 117 | 117 batch | 815,119 bytes |
| GrhSIM NO0300 | 117 | 117 batch | 739,365 bytes |

两边对象文件的 `.text` 默认都只有 16-byte alignment；差异不在默认对齐值，而在 GrhSIM batch 平均约为
GSim `subStep` 的 5 倍。较粗函数粒度使前面任一大函数的尺寸变化持续移动后续热函数的 cache-line、page
和 predictor address bits。

## 2. 实验变量

不重跑 graph transform、partition、schedule 或 C++ emission。分别 hardlink-copy NO0286 与 NO0300 的
`grhsim_emit` 目录，在副本中删除既有 `.o`、`.a` 和 PCH 后，以原参数加一个变量重新编译：

```text
-std=c++20 -O3 -falign-functions=4096
```

两个 emu 使用各自独立的 difftest `BUILD_DIR`。原 generated source、header、Makefile 和原 emu 均不得修改。
重编前后检查 source manifest 完全一致；重编后检查 117 个 batch 的入口地址均为 4 KiB 整数倍，并记录
`.text` 增量。页对齐会引入 padding，因此本轮只作为诊断，不因单边绝对加速而直接保留。

old 与 new 都使用同一对齐策略，目的是消除前序函数尺寸变化造成的低 12-bit 累计漂移。只对齐 NO0300
而沿用未对齐 NO0286 不能回答该问题，不采用该口径。

## 3. 门禁

1. 先运行 NO0286-aligned 与 NO0300-aligned 的 10k 功能测试；均须得到与原产物相同的 guest cycle、
   `cycleCnt`、`instrCnt` 和 terminal PC，且无 difftest mismatch。
2. 再运行两边 50k 功能门禁，确认页对齐不改变行为。
3. 性能测试前检查全机 load、CPU138 与 sibling CPU330；若负载较高或目标 CPU 不空闲，则等待，并插入
   原始未对齐 baseline 配对，不能把跨时段噪声当成布局效果。
4. 固定 CPU138、NUMA node 1，执行 aligned old / aligned new / aligned old CoreMark 50k，采集 host
   cycles、instructions、frontend empty slots 和 cmask6 full-empty cycles；所有事件须为 `100%` 调度。
5. 以两次 aligned old 均值计算 new delta，并与 NO0317/NO0328 未对齐回退比较。若 cycles 与 cmask6
   回退显著收窄，继续细化 batch section/order；若基本不变，则排除跨函数低 12-bit 漂移，转向函数内部
   basic-block layout 或编译器 code generation。

## 4. 预定产物

```text
build/xs_grhsim_no0329_no0286_align4k_20260712/grhsim
build/xs_grhsim_no0329_no0300_align4k_20260712/grhsim
build/logs/xs_perf/no0329/
```
