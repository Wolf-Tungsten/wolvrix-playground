# NO0332 Batch function page-alignment functional gate

日期：2026-07-12

## 1. 口径

承接 [NO0331](./NO0331_batch_function_page_alignment_build_gate_20260712.md)，对 NO0286-aligned 与
NO0300-aligned emu 运行 CoreMark 两迭代和 NEMU difftest。10k 两边并行执行，只用于快速功能检查；
50k 两边串行执行。两组均未固定 CPU，也未采集 PMU，因此本篇不作性能比较。

## 2. 结果

| Limit | Model | Guest cycles | `cycleCnt` | `instrCnt` | Terminal PC | Result |
| ---: | --- | ---: | ---: | ---: | --- | --- |
| 10k | NO0286 aligned | 10,001 | 9,996 | 458 | `0x800027c6` | PASS |
| 10k | NO0300 aligned | 10,001 | 9,996 | 458 | `0x800027c6` | PASS |
| 50k | NO0286 aligned | 50,001 | 49,996 | 73,580 | `0x80001312` | PASS |
| 50k | NO0300 aligned | 50,001 | 49,996 | 73,580 | `0x80001312` | PASS |

四轮日志均无 difftest mismatch、assertion、abort、segmentation fault 或 error。50k 每个 10k progress
checkpoint 的 model cycles、instruction count、commit PC 和 trap PC 也逐项一致。

未固定 Host time 为：

```text
10k old/new: 10,668 / 10,279 ms
50k old/new: 90,031 / 77,288 ms
```

50k 运行紧接 32-way 大规模编译，且 old/new 顺序固定、没有 A/B/A 或目标 CPU 空闲门禁。这组 raw time
不具备性能解释力，尤其不能据此宣称页对齐加速；正式结论只取后续 fixed CPU PMU A/B/A。

## 3. 产物与下一步

```text
build/logs/xs_perf/no0329/no0286_align4k_functional_10k.log
build/logs/xs_perf/no0329/no0300_align4k_functional_10k.log
build/logs/xs_perf/no0329/no0286_align4k_functional_50k.log
build/logs/xs_perf/no0329/no0300_align4k_functional_50k.log
```

页对齐模型通过 10k/50k 功能门禁。下一步等待编译负载消退，检查 CPU138/330 空闲度，再执行 aligned
old/new/old 50k PMU 门禁；若目标 CPU 不稳定，则同时插入原始未对齐 baseline。
