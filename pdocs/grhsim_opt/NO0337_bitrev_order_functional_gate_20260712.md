# NO0337 Bit-reversal order functional gate

日期：2026-07-12

## 1. 口径

承接 [NO0336](./NO0336_bitrev_order_build_gate_and_text_padding_correction_20260712.md)，对只重排 NO0300
sched object 地址的 bit-reversal emu 运行 CoreMark 两迭代和 NEMU difftest。分别执行 10k 与 50k，均未
固定 CPU；本篇只验收功能，不作性能结论。

## 2. 结果

| Limit | Guest cycles | `cycleCnt` | `instrCnt` | Terminal PC | Result |
| ---: | ---: | ---: | ---: | --- | --- |
| 10k | 10,001 | 9,996 | 458 | `0x800027c6` | PASS |
| 50k | 50,001 | 49,996 | 73,580 | `0x80001312` | PASS |

50k 的每个 10k progress checkpoint 均与 numeric NO0300 一致；两轮都没有 difftest mismatch、assertion、
abort、segmentation fault 或 error。

未固定 Host time 为 `10,194 ms` 与 `83,704 ms`，只作为执行记录。由于没有 fixed CPU、PMU 或 A/B/A，
不能用于判断 bit-reversal 顺序优劣。

## 3. 产物与下一步

```text
build/logs/xs_perf/no0334/bitrev_functional_10k.log
build/logs/xs_perf/no0334/bitrev_functional_50k.log
```

功能门禁通过。下一步检查 load 与 CPU138/330，执行 numeric / bit-reversal / numeric 的 50k PMU 门禁。
