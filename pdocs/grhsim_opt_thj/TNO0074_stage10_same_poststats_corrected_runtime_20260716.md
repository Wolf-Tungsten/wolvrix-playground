# TNO0074 Stage 10 same-poststats corrected runtime

记录日期：2026-07-16

状态：完成 Stage 10 same-poststats/current-code explicit-off 控制与 strict 的 corrected 跨 NUMA 50k A/B/A。NUMA0 cycles `-8.7636%`，NUMA1 `+9.4387%`，确认强烈 socket 方向反转；TNO0072 的小幅差异来自控制 provenance 混杂，strict 默认继续关闭。

## 1. Corrected control 闭合

explicit-off 与 strict 均从同一 post-stats JSON 恢复、使用当前相同代码和全部相同参数，唯一变量是 `final_fanin_pullback_policy=off/strict`。

off stats 恢复 canonical：

```text
SHA256        e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77
supernodes    63726
DAG           528622
total BAE     1983923
compute pairs 1721698
commit pairs  262225
```

strict 继续精确应用 `84` 个 move、BAE `-254`。两边 active-ID/topo 序列完全相同；只有 `83` 个 supernode 的 emitted-op signature 改变。由于 greedy estimated-line batch 重切，仍有 `448` 个 supernode 换 batch、`79/117` 个 schedule CPP 改变。

相比之下，旧 Stage 7 rollback 与 same-post off 虽 stats、active-ID、batch mapping、ELF 大小和 GNU `size` text 总量相同，但约 `45,778` 个 supernode emitted-op signature、`66/117` 个 CPP 不同，证明 TNO0072 的旧控制存在大范围 source-clone/op-order provenance 混杂。

## 2. Corrected 静态差异

same-post off 到 strict：

```text
generated source bytes  -10840
changed sched objects     65
object bytes aggregate   +6344
ELF file bytes           +4096
GNU size text            +5248
ELF .text section        +4656
```

84 个候选实际由两个家族组成：

- 82 个 3-op/gain-3 的 1-bit OR cone，从 topo/batch `27330/29` 前移到 `674..1118 / 0..1`，BAE `-246`；
- 2 个 8-op/gain-4 的 CSR AND cone，从 topo/batch `42946/45` 前移到 `38110/40`，BAE `-8`。

这导致 boundary values `+74`，生成代码中的 `grhsim_changed` predicate 也精确 `+74`；activation update sites 仅减少 `190`。因此 raw BAE 下降不等于 boundary materialization 成本下降。

## 3. Build 与功能

same-post off full emit、O3/archive/link 全部 PASS，emu SHA256 为：

```text
453b5dad1b332facbfe1bc229256b08a88a3b304f4a4f60b7a124a843f639976
```

fixed-ASLR 100/10k 功能门禁分别到达 `101/96/0/0x0` 与 `10001/9996/458/0x800027c6`，没有 diff mismatch。strict 的相同功能门禁已在 TNO0071 通过。

## 4. Corrected NUMA0

CPU/sibling `75/267`、membind 0。A1/B/A2 的 pass gate gap 为 `8/7/7 ms`；A1 在第 10 个窗口通过，其余首个窗口通过。

| PMU | off A1 | strict B | off A2 | B vs A mean |
| --- | ---: | ---: | ---: | ---: |
| cycles | `309,402,802,827` | `283,071,006,237` | `311,119,606,798` | `-8.763648%` |
| instructions | `172,881,268,562` | `172,835,001,860` | `172,881,269,084` | `-0.026762%` |
| frontend empty | `1,449,949,699,410` | `1,293,135,378,823` | `1,460,941,809,908` | `-11.151936%` |
| frontend empty `cmask>=6` | `193,770,487,651` | `167,103,765,729` | `195,485,786,165` | `-14.142031%` |
| backend stalls | `95,023,238,018` | `94,570,364,771` | `95,185,865,403` | `-0.561684%` |

控制 cycles spread 为 `+0.554877%`，有效。

## 5. Corrected NUMA1

最初 `154/346` 的 A1 有效，但后续候选连续 20 个窗口未过 quiet gate，未运行且不拼入正式结果。重新选择 CPU/sibling `120/312`、membind 1，从 A1 开始完整重跑。pass gate gap 为 `9/8/8 ms`，B 在第 3 个窗口通过。

| PMU | off A1 | strict B | off A2 | B vs A mean |
| --- | ---: | ---: | ---: | ---: |
| cycles | `281,201,976,103` | `307,925,307,966` | `281,533,555,471` | `+9.438729%` |
| instructions | `172,881,260,792` | `172,835,009,521` | `172,881,260,732` | `-0.026753%` |
| frontend empty | `1,282,257,862,125` | `1,443,012,794,696` | `1,285,381,224,031` | `+12.399971%` |
| frontend empty `cmask>=6` | `165,839,574,646` | `192,103,806,679` | `166,321,759,328` | `+15.668976%` |
| backend stalls | `94,441,547,123` | `94,123,918,248` | `93,321,410,527` | `+0.258240%` |

控制 cycles spread 为 `+0.117915%`，有效。backend-stall 控制自身 spread 为 `-1.186%`，因此不单独解释该小项；cycles/frontend 的反转远大于噪声。

## 6. 勘误与决定

六个正式样本的五项 PMU 均 100% scheduled，guest 终点均为 `50001/49996/73580/0x80001312`，没有 mismatch/assert/fatal。

same-post corrected 结果取代 TNO0072 作为 Stage 10 的 schedule 因果裁决：

- instructions 在两个 socket 都稳定减少约 `0.02675%`，与 254 BAE 的小幅 work 收益一致；
- cycles/frontend 却出现约 `-9%/+9%` 的 socket 反转，说明 code/batch layout 完全主导；
- `finalFaninPullbackPolicy` 默认保持 `off`，不采用 strict；
- 后续 schedule 候选必须同时报告 boundary-value/materialization 变化，并限制 active-ID/batch/layout blast radius，不能只按 raw BAE 排序。

原始数据：

```text
build/xs_activity_stage10_fanin_off_samepost_20260716/
build/logs/xs_perf/activity_stage10_fanin_strict_20260716/sp_n0_*
build/logs/xs_perf/activity_stage10_fanin_strict_20260716/sp2_n1_*
```
