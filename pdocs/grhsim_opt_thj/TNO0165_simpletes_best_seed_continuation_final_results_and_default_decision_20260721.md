# TNO0165 SimpleTES best-seed continuation final results and default decision

记录日期：2026-07-21

状态：SimpleTES instance `4269c986` 已在 `8/8` 个 generated valid candidates 后正常结束。
初始 seed 的反向复测和本轮 8 个新候选合计完成 `72` 个 accepted SimTop 50k 样本；8 个
新候选的 ABBA、BAAB 均为正向。最佳 targeted-direct bitmap-only commit continuation 为
`73,828.00 -> 73,458.50 ms`，改善 `369.50 ms / 0.500487620%`，但仍低于
`max(1%, control spread)` 的 `1%` 可信线，因此不应用 patch、不改变 C++ 默认、不产生
wolvrix 或 gitlink commit。完整 best program 只作为下一轮 fresh continuation seed。

初始 seed 独立复评见
[TNO0164](./TNO0164_simpletes_best_seed_initial_runtime_result_20260720.md)。

## 1. Run identity and stop ledger

```text
instance                    4269c986
start                       2026-07-20 18:23:31 +08:00
stop                        2026-07-21 13:30:44 +08:00
elapsed                     68,833 s / 19:07:13
final checkpoint            .../instance-4269c986/db_state_133044
pinned parent               b90d20461d276def682f19a28be1fe65a4387eef
pinned wolvrix              f17e90e14c3ad70a3ee93f7c6540e13dae54940a
model / reasoning           gpt-5.6-sol / ultra
stop reason                 valid-candidate limit reached: 8/8
```

预算账本为：

| item | absolute count |
| --- | ---: |
| generation attempts | `14 / 16` |
| successful generation outputs | `10` |
| generation failures | `4` |
| generation cancellations | `0` |
| completed evaluations | `9` = `1 initial + 8 generated` |
| generated valid evaluations | `8 / 8` |
| evaluation failures / rejects | `0 / 0` |
| successful proposals left unevaluated at stop | `2` |

四次 generation failure 都是 Codex CLI 到达 `3,000 s` hard timeout，发生在
`22:08:21`、`23:33:03`、`00:23:03` 和 `04:58:07`；约 `12,000 s / 3:20:00`
generator slot 用于这些超时。停止时另外两个已经生成的 proposal 仍在 eval queue，因达到
valid target 被 drain，没有进入 `nodes.json`，也没有可恢复的 patch/digest。

engine 层发生两次 retryable infrastructure outcome：初始 seed 的 24-CCD quiet-window
admission 失败，以及候选 `6e89b85b...` BAAB 期间的外载污染。两者均对同一候选重试并最终
成功，不计 evaluation failure。候选 `077eff47...` 的两次外载污染由 runtime 内部重试吸收。
没有降低 whole-CCD、ASLR、NUMA、PMU、迁移或 function gate。

## 2. All evaluated candidates

表中 headline 都是合并 ABBA+BAAB 后的 arithmetic mean `Host time spent`。每行是在自己的
quiet measurement window 中做 paired comparison，不能跨行比较 control 的绝对高低。

| gen | digest | mechanism | control ms | candidate ms | improvement ms | improvement | control/candidate spread ms |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| initial | `842fb6de071cbe88` | prior targeted-table seed | `72,793.25` | `73,378.75` | `-585.50` | `-0.804332819%` | `2,813 / 1,536` |
| 1 | `b839eadf707aac9c` | targeted-direct 64B bitmap alignment | `74,064.00` | `73,904.50` | `+159.50` | `+0.215354288%` | `248 / 309` |
| 4 | `6e89b85b6635fe6a` | alignment + AVX2 32B vptest scan | `73,949.75` | `73,839.50` | `+110.25` | `+0.149087725%` | `244 / 308` |
| 5 | `add332bdece10fa0` | gen1 alignment exact repeat | `73,905.25` | `73,751.25` | `+154.00` | `+0.208374912%` | `147 / 145` |
| 6 | `709076f797d4a764` | alignment + terminal bitmap scan elision | `73,941.25` | `73,714.50` | `+226.75` | `+0.306662384%` | `128 / 85` |
| 7 | `0582682c251fff92` | alignment + AVX2 128B scan | `73,995.25` | `73,855.75` | `+139.50` | `+0.188525615%` | `341 / 282` |
| 9 | `4e1b41714c9faa6a` | alignment + scalar scan unroll 4 | `75,607.00` | `75,316.75` | `+290.25` | `+0.383893026%` | `259 / 823` |
| 10 | `077eff47a089239d` | alignment + SSE2 64B scan | `74,115.25` | `73,889.75` | `+225.50` | `+0.304255872%` | `1,879 / 1,695` |
| 11 | `4ce54fe69ba60931` | alignment + bitmap-only commit continuation | `73,828.00` | `73,458.50` | `+369.50` | `+0.500487620%` | `184 / 53` |

gen1 与 gen5 是完全相同 patch 的独立复测。合并两次的绝对结果为 control
`73,984.625 ms`、candidate `73,827.875 ms`，改善 `156.750 ms / 0.211868%`。这支持
64B alignment 是可复现的小收益，但仍不足单独晋升默认。

8 个 generated candidates 都是 evaluator valid，且各自 ABBA、BAAB 方向一致正向；上一轮
best seed 则 ABBA `+0.2835%`、BAAB `-1.9309%`，pooled 回退，证明旧 `0.322%` 弱信号不能
直接继承为新 baseline 分数。

## 3. Best candidate identity and mechanism

```text
best node                   89a7597a1bd9481dbbb45321194a0ed2
generation / chain          11 / 1
score                       1.0050300509811663
full candidate digest       4ce54fe69ba60931c52a19225d9235548960ec88e40f36792c8c08b3780a4bf1
changed file                lib/emit/grhsim_cpp.cpp
patch line count            +35 / -8
enable option               active_mask_gap_pack_policy=targeted-direct
control generated fp        57819a3d9f1165af
candidate generated fp      18f07c64a4b26009
```

该候选保留 gen1 已复测的 `alignas(64)` active bitmap，并在 ordinary、未插桩、
targeted-direct 路径中：

- 停止发射冗余 `commit_activated_readers_ = true` stores；
- 不再在每轮 commit 前清零同一 summary bool；
- 直接用已经承载 reader activation 的 packed active bitmap 作为 continuation predicate；
- 对 perf/profile、input-fullpass、posedge-fullpass 和非 targeted-direct 路径继续保留原 flag
  protocol。

它没有改变 current-default 输出；disabled candidate 继续 byte-identical，enabled output 同时
区别于 control 和 unpatched same-options build，归因 gate 完整通过。

## 4. Best absolute walltime and runtime gates

| order | sequence, absolute walltime ms | control mean | candidate mean | improvement |
| --- | --- | ---: | ---: | ---: |
| ABBA, CPU16/N0 | `C 73,839 / K 73,458 / K 73,465 / C 73,919` | `73,879.00` | `73,461.50` | `417.50 ms / 0.5651%` |
| BAAB, CPU136/N1 | `K 73,482 / C 73,735 / C 73,819 / K 73,429` | `73,777.00` | `73,455.50` | `321.50 ms / 0.4358%` |
| pooled | all eight samples | `73,828.00` | `73,458.50` | `369.50 ms / 0.500487620%` |

八个样本均满足：personality `00040000`、单 CPU affinity、zero migration、binary/NEMU
NUMA-local ratio `1.0`、PMU scheduled `100%`、continuous monitor、guest cycle/signature/terminal
PC 和唯一 walltime 行。control spread 为 `184 ms / 0.249227935%`，candidate spread 为
`53 ms`。

## 5. Best PMU and ELF evidence

八样本 pooled arithmetic mean：

| metric | control | candidate | relative change |
| --- | ---: | ---: | ---: |
| instructions | `164,220,564,845.50` | `163,379,068,512.75` | `-0.5124%` |
| cycles | `270,426,621,157.50` | `269,076,844,158.00` | `-0.4991%` |
| backend stalls | `89,744,514,038.25` | `89,648,479,828.00` | `-0.1070%` |
| frontend no-op slots | `1,236,319,581,836.25` | `1,228,448,501,012.25` | `-0.6367%` |
| severe frontend empty | `159,991,774,111.00` | `158,566,950,001.75` | `-0.8906%` |

```text
control ELF bytes / SHA256
93,671,768 / b8f680b2377979083fe4992e86ca7fe9731a35d6369c59236c15abe4423303e6

candidate ELF bytes / SHA256
91,947,544 / 37c96fcdb7e5989d2094b7a09d5730d7a0be553572fd7cbba80e3d36f8dc447d
```

PMU、ELF size 和两个 runtime order 都支持该机制是真实正向信号；但它们仍是 walltime 的
诊断证据，不能替代预定可信线。

## 6. Default decision and durable seed

本组采用阈值为 `max(1%, 0.249227935%) = 1%`。最佳 `0.500487620%` 仅达到阈值约一半，
因此：

```text
apply patch to user wolvrix       no
change C++ default                no
wolvrix source commit             none
parent gitlink commit             none
use as next research seed         yes
```

durable seed 为：

```text
path
SimpleTES/checkpoints/grhsim_simtop_50k/formal_20260720_02/2026-07-20/
instance-4269c986/db_state_133044/best_program.txt

bytes                       14,571
file SHA256                 1711b4c8b0097164add65fca011b1b65567c02b07d78b3567fe35538ada509ab
candidate digest            4ce54fe69ba60931c52a19225d9235548960ec88e40f36792c8c08b3780a4bf1
validate-only               PASS
```

该文件包含完整 marked candidate，不等于已经应用到用户 worktree 的 source。后续只能以
fresh instance 独立复评它，旧 walltime 只作为选择 seed 的 provenance，不能直接继承为新
instance score。
