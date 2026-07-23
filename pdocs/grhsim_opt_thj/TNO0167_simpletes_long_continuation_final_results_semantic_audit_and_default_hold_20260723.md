# TNO0167 SimpleTES long continuation final results, semantic audit, and default hold

## 1. 目的与口径

本文闭合 [TNO0166](./TNO0166_simpletes_long_best_seed_continuation_launch_20260721.md) 启动的 long continuation，汇总 instance `25411edd` 的最终 ledger、全部有效 SimTop 50k `Host time spent`、最佳候选的正式 gate、机制审计与默认决策。

最终裁决仍只看当前仓库默认生成配置上的端到端 SimTop 50k walltime。每组测试均要求 whole CCD 空闲、地址随机化关闭、固定 CPU/NUMA first-touch、PMU 与功能审计通过；可信线为 `max(1%, control spread)`。静态指标和 PMU 只用于解释，不替代 walltime。

## 2. 实例终止状态与账本

- instance：`25411edd`
- 启动：`2026-07-21 16:59:59 +08:00`
- 正常停止：`2026-07-23 11:04:07 +08:00`
- wall-clock 运行时长：约 `42 h 04 min 09 s`
- 停止原因：达到 `16/16` generated valid target，不是 crash 或人工中断
- 预算：`32 proposals / 16 valid`，实际 generation attempts `30/32`
- generation failures：`8`；其中 `7` 次 Codex CLI `5400 s` timeout，`1` 次 usage-limit `CodexExecError`
- completed evaluations：`21`，即 initial seed `1` 次、generated candidate `20` 次
- generated valid：`16`；generated invalid：`4`；engine-level evaluation failures：`0`
- retryable runtime infrastructure outcomes：`8`，均按同候选重试后恢复，没有放宽 quiet-CCD、ASLR、NUMA、PMU 或功能 gate
- best score：`1.224785060743255`
- best node：`e5fd2c89bc5b435f95c4f661e8dee064`
- 最终 checkpoint：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/formal_20260721_03/2026-07-21/instance-25411edd/db_state_110407
```

`30 - 8 = 22` 个 generation 输出中有 `20` 个进入正式 evaluation；达到 valid target 时另有 `2` 个已经生成的工作没有形成结果。最终 `policy.json` 仍保留 batch 29 的 pending 记录，因此该 checkpoint 的结果完整，但不是适合原地 resume 的零 pending 状态。后续必须用 `best_program.txt` 做 fresh `--init-program`，不能把残留 policy 当成可继续账本。

另一个导出字段 `metadata.chain_best_scores` 仍停留在 initial score，和 `nodes.json`、`best_node_id` 不一致；本轮最佳值以最终 `metadata.best_score`、`metadata.best_node_id`、`nodes.json` 和对应 `evaluation_*.json` 为准。

## 3. 无效候选与失败边界

四个 completed evaluation 被 fail-closed 判为 CandidateError，没有 walltime 分数：

| gen | 原因 |
| ---: | --- |
| `3` | build 未产生 `emu` |
| `4` | structured patch 缺少末尾换行 |
| `9` | `git apply` 报 corrupt patch |
| `10` | 请求 same-batch strict，但 profile path 为空；emitter 按契约 fail closed |

这些失败没有被当作零分性能样本，也没有改变正式 gate。

## 4. 全部有效 walltime

下表的 control/candidate 均为 ABBA screen 与 BAAB promotion 共四个样本的 pooled arithmetic mean；改善百分比为 `(control - candidate) / control`。`initial` 不计入 `16/16` generated valid target。

| gen | digest | control (ms) | candidate (ms) | 改善 (ms) | 改善 (%) |
| ---: | --- | ---: | ---: | ---: | ---: |
| initial | `4ce54fe69ba60931` | `74,782.25` | `74,501.00` | `281.25` | `0.376092%` |
| `0` | `5eafc3d05446c3fe` | `73,912.25` | `73,676.25` | `236.00` | `0.319298%` |
| `1` | `5302e94531d923a4` | `74,147.50` | `73,705.00` | `442.50` | `0.596783%` |
| `2` | `f56ac4c3333ffccb` | `73,548.00` | `73,279.25` | `268.75` | `0.365408%` |
| `6` | `ad97807a68ce35e1` | `73,660.25` | `73,320.25` | `340.00` | `0.461579%` |
| `7` | `7d14cba67273e966` | `73,817.00` | `73,486.25` | `330.75` | `0.448068%` |
| `8` | `ee13ef674f85e5f3` | `73,851.50` | `73,465.25` | `386.25` | `0.523009%` |
| `12` | `6c0ef5a5834e4197` | `75,426.50` | `75,037.50` | `389.00` | `0.515734%` |
| `13` | `b1e43cf2b83672ce` | `74,168.00` | `73,994.00` | `174.00` | `0.234603%` |
| `14` | `814f62ae4c0b76fa` | `73,764.00` | `73,383.75` | `380.25` | `0.515495%` |
| `19` | `042e38b3718837b2` | `73,920.00` | `73,461.25` | `458.75` | `0.620603%` |
| `20` | `7a2c4eecca2ca55d` | `74,052.00` | `73,469.50` | `582.50` | `0.786609%` |
| `22` | `80972b3f17e172d5` | `73,970.00` | `73,802.75` | `167.25` | `0.226105%` |
| `24` | `911de849ff1297ee` | `73,952.00` | `60,512.50` | `13,439.50` | `18.173275%` |
| `25` | `3686687fced3fdb2` | `74,171.75` | `73,594.00` | `577.75` | `0.778935%` |
| `26` | `df73eff7ba4ff4af` | `74,053.00` | `73,464.00` | `589.00` | `0.795376%` |
| `27` | `b917061c3cfb4eed` | `74,327.00` | `60,685.75` | `13,641.25` | `18.353021%` |

所有 `16` 个 generated valid candidate 都在 ABBA 和 BAAB 两个方向上分别正向，且都通过正式 gate。除 gen 24 和 gen 27 外，其余收益均小于 `1%` 可信线，不能单独晋升。

## 5. 最佳候选正式结果

最佳候选为 gen 27 / node `e5fd2c89...` / digest `b917061c3cfb4eed`。

| order | 原始顺序 (ms) | control mean (ms) | candidate mean (ms) | 改善 (ms) | 改善 (%) |
| --- | --- | ---: | ---: | ---: | ---: |
| ABBA | `C 74181 / K 60663 / K 60723 / C 74306` | `74,243.50` | `60,693.00` | `13,550.50` | `18.251429%` |
| BAAB | `K 60574 / C 74500 / C 74321 / K 60783` | `74,410.50` | `60,678.50` | `13,732.00` | `18.454385%` |
| pooled | 上述 8 个样本 | `74,327.00` | `60,685.75` | `13,641.25` | `18.353021%` |

control spread 为 `319 ms / 0.429185%`，candidate spread 为 `209 ms`；正式可信线因此仍是 `1%`。`18.353021%` 明显超过可信线，且两种 order 方向一致。

运行门禁：

- ABBA：CPU `24`，CCD `node0:24-31,216-223`
- BAAB：CPU `9`，CCD `node0:8-15,200-207`
- 两组入场 gate 均为 CCD mean idle `99.896875%`、minimum `99.67%`
- 8/8 样本 affinity 正确、CPU migrations `0`、personality `00040000`，即地址随机化已关闭
- binary 与 NEMU local-page ratio 均为 `1.0`
- 五个 PMU event scheduled ratio 和 task-clock scheduled ratio 均为 `100%`
- 8/8 signature、guest-cycle 与 terminal-PC audit 通过
- 四个 candidate emu log 均跑满 50k：`Guest cycle = 50001`、`cycleCnt = 49996`、`instrCnt = 73580`、terminal PC `0x80001312`，不是提前退出

ELF 绝对值：

| role | bytes | SHA256 |
| --- | ---: | --- |
| control | `93,671,768` | `b8f680b2377979083fe4992e86ca7fe9731a35d6369c59236c15abe4423303e6` |
| candidate | `91,640,344` | `3603dec49b4313fd9beb91d781e600695b317b9e1df58943909ef240c269e912` |

八样本 pooled PMU mean：

| event | control | candidate | candidate 减少 |
| --- | ---: | ---: | ---: |
| cycles | `271,410,282,655.25` | `221,634,937,934.50` | `18.339521%` |
| instructions | `164,220,579,158.25` | `160,264,855,380.50` | `2.408787%` |
| frontend no-op slots | `1,242,172,747,226.50` | `1,008,297,146,844.25` | `18.827945%` |
| severe frontend empty | `160,966,890,107.75` | `132,015,416,698.75` | `17.985980%` |
| backend stalls | `89,585,403,578.75` | `76,273,650,115.75` | `14.859288%` |

## 6. 最佳程序与机制归因

持久化 seed：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/formal_20260721_03/2026-07-21/instance-25411edd/db_state_110407/best_program.txt
bytes: 46653
sha256: 988d6b504c773b118ef57a9d380c9fcfe689aaabd251ffde7e81e7fe02810ae7
```

程序只修改 `lib/emit/grhsim_cpp.cpp`，patch 规模约 `+538/-7`，显式启用 `active_mask_gap_pack_policy=targeted-direct`。它不是单一的 8-byte guard 优化，而是以下机制的组合：

1. `eventQualifiedBitmapContinuation`：在严格 fail-closed 条件成立时，用 event-edge qualification 避免无意义的 terminal active-bitmap scan。
2. lockstep scalar commit state-write grouping：对同一 guard 下、同 next/init expression、单写者的连续 scalar state writes 共享 change predicate 和 next value。
3. 对大规模 cold singleton exact-event guards 增加 `unlikely` 布局提示。
4. gen 27 在 gen 24 组合上增加 8 个连续 `value_bool_slots_` byte 的 alias-safe `memcpy` word precheck，外层 word 非零时仍逐个执行原 exact guards 和 write bodies。

gen 24 已经达到 `18.173275%`，gen 27 的最终值为 `18.353021%`，增量只有约 `0.179747` 个百分点。因此约 `18%` 的跃升属于 gen 24 已包含的复合改动，不能归因给 gen 27 新增的 packed precheck；下一阶段必须做组件消融。

## 7. 补充语义审计

在 `/tmp/grhsim-long-audit-20260723` 做过一组非正式 60k difftest：

| role | walltime (ms) | instrCnt | cycleCnt | Guest cycle | terminal PC |
| --- | ---: | ---: | ---: | ---: | --- |
| control | `93,455` | `122,373` | `59,996` | `60,001` | `0x800010fe` |
| candidate | `77,781` | `122,373` | `59,996` | `60,001` | `0x800010fe` |

该诊断改善 `15,674 ms / 16.7717%`，两边 endpoint 一致且未见 mismatch。不过它没有正式 whole-CCD monitor、PMU 与完整 ABBA/BAAB，不能计入正式 score；尚未完成的 `control-100k.log` 也不能写成 100k PASS。

## 8. 默认与后续决定

性能结论明确：最佳候选通过 50k end-to-end walltime 门槛，可作为后续研究和 fresh replication 的持久 seed。

但本轮不直接合入 wolvrix，也不默认开启。原因不是性能不足，而是 patch 同时改变 terminal continuation、多个 state 的共享 change predicate、branch layout 和 packed guard，单一 CoreMark 50k signature/terminal-PC 不能独立证明所有 workload 的状态语义。下一步至少需要：

1. 从 `best_program.txt` fresh 初始化，重新完成 ABBA/BAAB 独立复现。
2. 分别消融 lockstep grouping、terminal-scan qualification、cold-guard hint 与 packed precheck，建立真实 walltime 归因。
3. 扩大功能回归或加入更强的 state/difftest 比对，再决定是否拆分后合入并默认开启。

因此本阶段代码/default 状态不变；只保留 checkpoint seed、正式结果和审计记录。

## 9. 权威产物

```text
SimpleTES/checkpoints/grhsim_simtop_50k/formal_20260721_03/2026-07-21/instance-25411edd/run.log
SimpleTES/checkpoints/grhsim_simtop_50k/formal_20260721_03/2026-07-21/instance-25411edd/db_state_110407/metadata.json
SimpleTES/checkpoints/grhsim_simtop_50k/formal_20260721_03/2026-07-21/instance-25411edd/db_state_110407/nodes.json
SimpleTES/checkpoints/grhsim_simtop_50k/formal_20260721_03/2026-07-21/instance-25411edd/db_state_110407/best_program.txt
/tmp/simpletes-grhsim-simtop-50k/240719f63589edae/slot-0/results/evaluation_b917061c3cfb4eed.json
```
