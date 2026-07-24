# TNO0169 SimpleTES fresh replication interim checkpoint and new best

## 1. 范围与状态

本文记录 [TNO0168](./TNO0168_simpletes_best_candidate_fresh_replication_launch_20260723.md) 启动的 instance `50c610a6` 在 `2026-07-24 12:42 +08:00` 的中间 checkpoint。该 instance 仍在运行，本文不是最终停止账本，也不据此改动 wolvrix 或默认配置。

当前 live 状态：

- unified exec session：`32342`，仍有 session id、没有 exit code
- scheduler：generation worker `0 active / 0 queued`，evaluation worker `1 active / 3 queued`
- 最新稳定 checkpoint：`db_state_092715`，写于 `09:27:15`
- completed evaluations：`7`，包括 initial seed `1` 次和 generated valid `6` 次
- generation attempts：`15`
- checkpoint generation failures：`6`
- evaluation failures：`0`
- generated valid：`6/16`
- checkpoint best score：`1.2326159492826159`
- checkpoint best node：`07aed5e981084c0d9befc39643a50728`

checkpoint 之后，live log 在 `09:56:14` 又记录了一次 generation failure，并在 `11:05:53`、`12:39:24` 两次记录 retryable evaluation infrastructure outcome。最近一次 digest `1051b1e8a495bfb6` 的 monitor minimum idle 只有 `91.69%`，低于 `95%` runtime minimum，因此没有形成 walltime，并按原候选重试。quiet-CCD、fixed-ASLR、NUMA、PMU 和功能 gate 没有放宽；这些 live 计数要等下一 checkpoint 或最终停止账本再定稿。

## 2. 上轮最佳 seed 的 fresh 复现

initial seed 仍为 digest `b917061c3cfb4eed`。上一实例的正式 pooled 结果为 `74,327.00 -> 60,685.75 ms`，改善 `13,641.25 ms / 18.353021%`。本实例 fresh 重建和重新选 CCD 后得到：

| run | control (ms) | candidate (ms) | 改善 (ms) | 改善 (%) |
| --- | ---: | ---: | ---: | ---: |
| 上一实例 `25411edd` | `74,327.00` | `60,685.75` | `13,641.25` | `18.353021%` |
| fresh initial `50c610a6` | `73,862.75` | `60,257.00` | `13,605.75` | `18.420313%` |

fresh initial 的 control spread 为 `3.651367%`，所以该组可信线为 `3.651367%`；`18.420313%` 仍明显超过可信线。它提供了跨时间、跨 CCD 的独立复现，确认上一轮约 `18%` 的大幅收益不是单次 order 或单个 CCD 偶然值，但复合 patch 的语义审计和组件消融仍未完成。

## 3. 最新 checkpoint 的全部有效节点

下表均为正式 ABBA screen 与 BAAB promotion 的 pooled `Host time spent` arithmetic mean；`initial` 不计入 `6/16` generated valid。

| gen | digest | control (ms) | candidate (ms) | 改善 (ms) | 改善 (%) |
| ---: | --- | ---: | ---: | ---: | ---: |
| initial | `b917061c3cfb4eed` | `73,862.75` | `60,257.00` | `13,605.75` | `18.420313%` |
| `0` | `02b0074ea6d0ecb1` | `75,804.00` | `61,809.50` | `13,994.50` | `18.461427%` |
| `1` | `6986a5ff108740ae` | `74,154.75` | `60,508.25` | `13,646.50` | `18.402732%` |
| `5` | `02b0074ea6d0ecb1` | `73,812.00` | `60,286.25` | `13,525.75` | `18.324595%` |
| `6` | `d982100637455509` | `73,731.00` | `60,314.00` | `13,417.00` | `18.197230%` |
| `9` | `c0c066cd9b9e824e` | `73,883.00` | `59,940.00` | `13,943.00` | `18.871730%` |
| `10` | `48bed03cc87990ae` | `73,908.50` | `60,115.75` | `13,792.75` | `18.661927%` |

目前 initial 和六个 generated candidate 全部有效、全部在 ABBA 与 BAAB 两个方向分别正向。gen 0 与 gen 5 的 digest 相同但属于独立 formal evaluation，其 spread 和绝对 walltime 不同，因此两行都保留。

## 4. 当前新最佳 gen 9

gen 9 / node `07aed5e9...` / digest `c0c066cd9b9e824e` 的原始样本：

| order | 原始顺序 (ms) | control mean (ms) | candidate mean (ms) | 改善 (ms) | 改善 (%) |
| --- | --- | ---: | ---: | ---: | ---: |
| ABBA | `C 73983 / K 60028 / K 59937 / C 73905` | `73,944.00` | `59,982.50` | `13,961.50` | `18.881180%` |
| BAAB | `K 59867 / C 73805 / C 73839 / K 59928` | `73,822.00` | `59,897.50` | `13,924.50` | `18.862263%` |
| pooled | 上述 8 个样本 | `73,883.00` | `59,940.00` | `13,943.00` | `18.871730%` |

control spread 为 `178 ms / 0.240921%`，candidate spread 为 `161 ms`，因此可信线仍为 `1%`。两种 order 的结果紧密且方向一致。

正式 gate：

- ABBA：CPU `72`，CCD `node0:72-79,264-271`；入场 mean idle `99.95875%`、minimum `99.67%`
- BAAB：CPU `176`，CCD `node1:176-183,368-375`；入场 mean/minimum idle 均为 `100%`
- 8/8 样本 personality `00040000`、affinity 正确、CPU migrations `0`
- 8/8 NUMA、PMU scheduled ratio、signature、guest-cycle 与 terminal-PC gate 通过

八样本 pooled PMU mean：

| event | control | candidate | candidate 减少 |
| --- | ---: | ---: | ---: |
| cycles | `270,342,333,640.00` | `219,250,302,366.50` | `18.899012%` |
| instructions | `164,220,403,745.75` | `159,969,292,767.50` | `2.588662%` |
| frontend no-op slots | `1,235,252,758,921.00` | `996,963,229,370.25` | `19.290751%` |
| severe frontend empty | `159,810,218,963.50` | `130,465,559,686.25` | `18.362192%` |
| backend stalls | `90,323,891,349.75` | `75,120,419,868.50` | `16.832171%` |

## 5. 当前最佳机制

checkpoint best program：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/continuation_20260723_194100/2026-07-23/instance-50c610a6/db_state_092715/best_program.txt
bytes: 47443
sha256: 99f27ad0c99058e8e53ec6a11124733c031f54c6b72c2e52a8c97e4e2f2431b7
```

它保留上轮复合 targeted-direct 机制，并沿用 gen 0 对相邻两个 8-byte packed guard block 的配对预检。gen 9 的新增点更窄：

- packed-precheck eligibility 仍要求至少 `1,024` 个 singleton register guards，不扩大 packed-load 范围；
- 只把现有 `unlikely(cond)` cold-guard layout hint 的门槛从 `1,024` 降到 `256`；
- production 结构恰好增加三个 medium exact-event run，guard 数分别为 `422/703/466`，共 `1,591` 个；下一个 run 只有 `88`，形成自然断点；
- patch 相对 `f17e90e` 只改 `lib/emit/grhsim_cpp.cpp`，约 `+575/-7`，没有改默认路径。

相对 fresh initial 的改善比例，gen 9 从 `18.420313%` 提高到 `18.871730%`，增加约 `0.451416` 个百分点；由于两次 formal evaluation 使用不同 CCD 和 control group，这只能视为当前 end-to-end 新最佳，不能当成严格的单机制 paired attribution。最终仍需专门消融。

现有重复结果也提示 attribution 方向：gen 0 的 paired-block digest `02b0074e...` 两次 formal evaluation 分别为 `18.461427%` 和 `18.324595%`，围绕 seed 摇摆，没有稳定证明 pairing 自身正向；而不依赖扩大 packing 范围、只下调 hint 门槛到 `512` 的 gen 10 已达到 `18.661927%`。因此当前证据更支持“扩大 cold-guard `unlikely` hint 覆盖”是本轮新增收益的主要来源，paired-block 至多是小项，仍需复测和消融确认。

## 6. 当前决定

- SimpleTES 继续运行，不重复启动 worker，不人工停止当前 evaluation/retry。
- 当前已有强证据表明约 `18%` 大收益可 fresh 复现，且搜索把新最佳推进到 `18.871730%`。
- run 尚未达到 `16/16`，当前 best 可能继续变化；不提前形成终止账本。
- 仍不把复合候选写入 wolvrix 或默认开启。最终需结合全 run 结果、fresh replication、组件消融与更广语义回归再决定保留方式。

## 7. 权威产物

```text
SimpleTES/checkpoints/grhsim_simtop_50k/continuation_20260723_194100/2026-07-23/instance-50c610a6/run.log
SimpleTES/checkpoints/grhsim_simtop_50k/continuation_20260723_194100/2026-07-23/instance-50c610a6/db_state_092715/metadata.json
SimpleTES/checkpoints/grhsim_simtop_50k/continuation_20260723_194100/2026-07-23/instance-50c610a6/db_state_092715/nodes.json
/tmp/simpletes-grhsim-simtop-50k/240719f63589edae/slot-0/results/evaluation_c0c066cd9b9e824e.json
```
