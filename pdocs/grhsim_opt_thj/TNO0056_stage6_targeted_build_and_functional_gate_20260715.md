# TNO0056 Stage 6 targeted build and functional gate

日期：2026-07-15

## 1. Production targeted success

应用 [TNO0055](./TNO0055_stage6_frozen_batch_cost_proxy_fix_20260715.md) 后，正确执行 `source env.sh` 的 production targeted 完整生成通过，exit `0`。planner 与 rebuilt exact coverage 一致：

```text
baseline / candidate pure words       107 / 171
added / lost                           64 / 0
moved supernodes                       256 / 63241 = 4048 ppm
moved event supernodes                 128
changed compute active words           127 / 7932 = 16011 ppm
max active-ID displacement             648
Kahn levels / frozen batches           97 / 117
validation_passed / applied            true / true
```

117 个 batch 全量重算后，11 个 batch 的 line proxy 变化，总计 `33,287,908 -> 33,288,049`，即 `+141`（约 `0.00042%`）；最大单 batch absolute delta 为 `84`。其余 frozen-batch 与 rebuilt active-ID 门禁全部通过。

activity-schedule stats 与 probe/current-default byte-exact，SHA256 均为：

```text
e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77
```

SN `63726`、compute/commit `63241/485`、DAG `528622`、BAE `1983923`、boundary values `1000463` 全部不变。

## 2. Generated source gate

probe 是 packing 未采用的 current threshold-2 hybrid control。marker 与 source shape：

| 指标 | probe | targeted | 变化 |
| --- | ---: | ---: | ---: |
| pure words | 107 | 171 | +64 |
| eligible batches | 22 | 32 | +10 |
| sparse volatile words | 20 | 17 | -3 |
| sparse batches | 14 | 13 | -1 |
| dense direct words | 87 | 154 | +67 |
| schedule C++ bytes | 1,331,063,668 | 1,331,081,705 | +18,037 |
| schedule C++ lines | 13,383,537 | 13,383,853 | +316 |

117 个 schedule TU 中 103 个 source/object 变化，原因是 active ID 与局部 mask codegen 随 permutation 改变，不是 batch relocation。

## 3. O3 machine gate

两套 emu 均直接调用 difftest `emu` target 独立构建，没有重新触发 emit：

| 指标 | probe | targeted | 变化 |
| --- | ---: | ---: | ---: |
| emu bytes | 93,694,944 | 93,711,328 | +16,384 |
| emu `.text` | 87,113,502 | 87,129,118 | +15,616 |
| emu instructions | 16,990,987 | 16,992,660 | +1,673 |
| emu memory forms | 7,577,970 | 7,578,757 | +787 |
| emu jumps | 1,078,706 | 1,078,846 | +140 |
| emu calls | 32,318 | 32,318 | 0 |

schedule objects 的 `.text` 为 `85,433,537 -> 85,449,212`，instructions `16,884,924 -> 16,886,606`，memory forms `7,392,402 -> 7,393,195`，jumps `1,093,199 -> 1,093,339`，calls 不变。增幅均远低于 1%，没有 codegen cliff，因此继续 50k。

O3 emu SHA256：

```text
probe     618a828ae3756d8936b77ed61efd6d94ca355eda3c189236d128b7f0abd0f30a
targeted  407c706416475cfa204c749dc215c0b17211c45e47a6f0e8255fe3de551f1898
```

## 4. Fixed-ASLR functional gate

probe 与 targeted 均在 `setarch x86_64 -R` 下通过：

| Limit | Guest / cycle / instr | PC |
| ---: | --- | --- |
| 100 | `101 / 96 / 0` | `0x0` |
| 10k | `10001 / 9996 / 458` | `0x800027c6` |
| 50k | `50001 / 49996 / 73580` | `0x80001312` |

全部 exit `0`，mismatch/assert/abort/fatal/segfault/refill/input-fullpass 等负向扫描为 0。50k 的五个 10k checkpoints 去掉 `host_ms` 后 probe/targeted `diff=0`。

## 5. 当前决策

结构、O3 与功能门禁完成，值得进入 atomic quiet 50k。性能实验必须另建 runtime 文档；在 valid current-default NO0300 A/B/A 完成前，policy 保持默认 `off`。
