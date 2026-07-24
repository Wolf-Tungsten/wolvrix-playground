# TNO0173 gen20/gen24 fresh cold-guard hint ablation result

## 1. 范围与结论

本文闭合 [TNO0171](./TNO0171_simpletes_18pct_ablation_design_and_static_attribution_20260724.md) 的单变量消融，以及 [TNO0172](./TNO0172_gen20_quiet_gate_retries_and_proof_backed_runtime_reuse_20260724.md) 的 proof-backed runtime retry。裁决只看 current-default SimTop 50k `Host time spent` walltime，改善公式为 `(control-candidate)/control`；可信线为 `max(1%, pooled control spread)`。静态 diff、PMU 和 ELF 只用于解释。

Fresh 正式结果为：

| arm | control pooled (ms) | candidate pooled (ms) | 改善 (ms) | 改善 (%) | control spread | 可信线 | 裁决 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| gen20/no-cold-hint | `73,928.00` | `73,237.50` | `690.50` | `0.934017%` | `3,566 ms / 4.823612%` | `4.823612%` | 方向一致，但低于可信线 |
| gen24/cold-hint-1024 | `74,055.00` | `60,648.25` | `13,406.75` | `18.103774%` | `1,061 ms / 1.432719%` | `1.432719%` | 明确通过 |

两 arm 的唯一运行时 source delta 是：对 `>=1,024` 个 exact-event singleton register-write guards 的 run 发射 `if (unlikely(cond))`。Fresh 改善差为 `+17.169757` 个百分点；历史相邻 checkpoint 差为 `+17.386665` 个百分点，两者只差 `0.216908` 个百分点。因此，约 `18%` 提升的主要来源已经由 fresh SimTop 50k 单变量实验确认：cold-guard `unlikely` 引发的编译器 branch weighting/hot-cold layout 与前端供给改善，而不是约 `18%` 的动态指令消除。

## 2. Arm 与 provenance

两份候选均只修改 `lib/emit/grhsim_cpp.cpp`，canonical option 完全相同：

```text
{"active_mask_gap_pack_policy":"targeted-direct"}
```

| arm | checkpoint node / historical digest | fresh full digest | candidate file bytes / SHA-256 | patch bytes / SHA-256 | enabled generated fingerprint |
| --- | --- | --- | --- | --- | --- |
| gen20/no-cold-hint | `65e3d3b5...` / `7a2c4eecca2ca55d` | `6397b7de38d265552feaaaa34ab5f79bfb53f2bd53bf191a46f0f3ad0fd4fb45` | `34,765` / `b67a8e84981da76f57855e0d88289f097eff1a742cb75e778027375a70bdb8a9` | `27,092` / `cd3e6b825b8a20428499f1a073586afefa4c2ac47c7f8697a634cf73abd4a6e8` | `f618a36bf55a531d...` |
| gen24/cold-hint-1024 | `ce990cc9...` / `911de849ff1297ee` | `e561cdb7c7986cc1b42d6c06af2a66d3d7a5cca648ae158a51bfeba2c04601b9` | `37,922` / `8f84146b6457552161b46870503cc290e2e74557f1ecf53c2b0ab27598e3e5a2` | `29,687` / `8e88033519a4d2b065a97f15fc0ed7d843ecefbad4098fe6203a61ec8163f78c` | `10b5fa3ee0ce7c58...` |

正式 evaluator identity：

```text
evaluation parent: b90d20461d276def682f19a28be1fe65a4387eef
wolvrix:          f17e90e14c3ad70a3ee93f7c6540e13dae54940a
SimpleTES tool:   fc17b90e46940ef8f013fe7ead1d435ceccaadc3
control fp:       57819a3d9f1165af...
build config fp:  c967333e4e754d81...
toolchain fp:     3139fef644317380...
env.sh SHA-256:   3922f9802d73b8422895b0628c0c948c1172e9a1cdfa1b94ece3fa3eadaa9e7a
```

两 arm 的 unpatched-options attribution、explicit-disabled/default-off identity、focused tests、100-cycle、10k-cycle、enabled fingerprint 与 artifact proof 全部 PASS。地址随机化、whole-CCD、NUMA、PMU 和运行功能 gate 未因重试而放宽。

## 3. 单变量机械证据

在同一 `f17e90e` 基线上应用两份 patch 后，gen20 目标文件为 `1,525,711 B`、SHA-256 `31f4214d7c23dd3ae5841dab40422b0e921fe71797706535d4805c49abfb5bb9`；gen24 为 `1,527,538 B`、SHA-256 `23619556e2b80e04bf6a9751456528a79a09b8db26bd28fd59d526dfb493118b`。目标源码机械 diff 只有两个相邻 hunk，净变化 `+30/-1` 行、`+1,827 B`：

1. 新增 generator-time selector：`cond != true`、run 只有一个 index、op kind 为 `kRegisterWritePort`，且 event-qualified run 内命中数 `>=1,024`。
2. 仅在 selector 命中时把 emitted `if (cond)` 改为 `if (unlikely(cond))`；否则仍发射普通 `if`。`unlikely(x)` 既有定义为 `__builtin_expect(!!(x), 0)`，条件仍只求值一次。

SimTop 结构 census 命中 `16` 个 exact-event runs、`44,976` 个 guards；每个 run fire `50,050` 次，加权 guard evaluations 为 `2,251,048,800`。最小命中 run 为 `1,027`，最大未命中 run 为 `703`。alignment、event-qualified continuation、selective `trackCommitActivation`、lockstep grouping 在 gen20 已存在；packed 8-byte precheck、相邻 pairing 与 `256` 门槛均不在任一 arm。

## 4. Retry 与 gate 账本

| arm / attempt | mode | eval time (s) | 结果 | accepted formal samples |
| --- | --- | ---: | --- | ---: |
| gen20 full-1 | legacy full | `5,403.366719` | atomic pre-gate：mean `97.416875%`、min `87.04%`，retryable | `0` |
| gen20 full-2 | legacy full | `5,210.357311` | `24` 个 CCD 均未通过 3s survey，retryable | `0` |
| gen20 `...9e5f560f` | proof full | `5,464.509357` | workload monitor：mean `98.958%`、min `88.89%`，retryable | `0` |
| gen20 `...974a7939` | runtime-only | `1,165.024589` | ABBA/BAAB PASS | `8` |
| gen24 `...d93d8017` | proof full | `5,450.175050` | workload monitor：mean `97.674%`、min `94.41%`，retryable | `0` |
| gen24 `...73cd3e1c` | runtime-only, 5 groups | `848.871373` | workload monitor：mean `97.527333%`、sibling `97.67%`，retryable | `0` |
| gen24 `...29ac604f` | runtime-only, up to 10 groups | `1,454.778650` | ABBA/BAAB PASS | `8` |

gen20 authoritative success attempt：

```text
01784896578555175327-896118-974a79398b0c46b1a530b4ced5f46389
proof id: 5627170196554f12820def9e2568acef
proof SHA-256: 65c9fe0aed91c32b45f3de18c9ab1f6513a5b72a44adc81a00e07c36c26ed1b0
```

gen24 authoritative success attempt：

```text
01784904581644043657-1273403-29ac604f32674dbe99a0a06ffe6fef26
proof id: 7eb014a89117423d8822f98af54871f8
proof SHA-256: b415090e11d1aba8b2647e5ea62d6a138a13f8db29a0f0e2f0ccd1e8b7fa0aae
```

Runtime-only retry 没有 clone、emit 或 build，只在同一 slot lock 下复验完整 candidate digest、patch/options、commits、generated/build/toolchain fingerprint、ELF/image/NEMU/env SHA 和上一 immutable attempt。所有污染组均 fail-closed 丢弃；表中的 `8` 条样本才进入正式结果。

## 5. Fresh 50k walltime

| arm / order | 原始顺序 (ms) | control mean (ms) | candidate mean (ms) | 改善 (ms) | 改善 (%) |
| --- | --- | ---: | ---: | ---: | ---: |
| gen20 ABBA | `C 72,588 / K 71,885 / K 71,474 / C 72,007` | `72,297.50` | `71,679.50` | `618.00` | `0.854801%` |
| gen20 BAAB | `K 74,779 / C 75,544 / C 75,573 / K 74,812` | `75,558.50` | `74,795.50` | `763.00` | `1.009814%` |
| gen20 pooled | `8 samples` | `73,928.00` | `73,237.50` | `690.50` | `0.934017%` |
| gen24 ABBA | `C 73,766 / K 60,444 / K 60,279 / C 73,540` | `73,653.00` | `60,361.50` | `13,291.50` | `18.046108%` |
| gen24 BAAB | `K 60,751 / C 74,313 / C 74,601 / K 61,119` | `74,457.00` | `60,935.00` | `13,522.00` | `18.160818%` |
| gen24 pooled | `8 samples` | `74,055.00` | `60,648.25` | `13,406.75` | `18.103774%` |

gen20 ABBA 与 BAAB 都正向，但 pooled candidate range/spread 为 `71,474..74,812 / 3,338 ms`，control 为 `72,007..75,573 / 3,566 ms`，所以 `0.934017%` 低于 `4.823612%` 可信线。gen24 candidate range/spread 为 `60,279..61,119 / 840 ms`，control 为 `73,540..74,601 / 1,061 ms`；两个 order 均约 `18%`，pooled `18.103774%` 明确高于 `1.432719%` 可信线。

两 arm 来自不同测量窗口，不能把 candidate 绝对值当成同一 paired order；但其 control pooled 只差 `127.00 ms / 0.171789%`。作为诊断，gen24 candidate 比 gen20 candidate 低 `12,589.25 ms / 17.189623%`；正式因果量仍采用各自 paired 改善的差，即 `17.169757` 个百分点。

## 6. Runtime audit

| arm / order | CCD | CPU / sibling / helper | NUMA | initial gate count / mean / min / target / sibling |
| --- | --- | --- | ---: | --- |
| gen20 ABBA | `node1:152-159,344-351` | `152 / 344 / 0` | `1` | `16 / 99.814375 / 99.34 / 100 / 100%` |
| gen20 BAAB | `node0:80-87,272-279` | `80 / 272 / 96` | `0` | `16 / 99.979375 / 99.67 / 100 / 100%` |
| gen24 ABBA | `node0:88-95,280-287` | `89 / 281 / 96` | `0` | `16 / 99.958750 / 99.67 / 100 / 100%` |
| gen24 BAAB | `node1:144-151,336-343` | `147 / 339 / 0` | `1` | `16 / 99.751875 / 99.34 / 100 / 100%` |

正式样本的绝对 audit extrema：

| arm | pre-gate mean / min / target / sibling idle | monitor mean / min / sibling idle | gate-to-run gap |
| --- | --- | --- | --- |
| gen20 | `98.375..99.979375 / 97.66..99.67 / 98.66..100 / 98.66..100%` | `98.988667..99.687333 / 98.11..99.46 / 98.99..99.76%` | `7.435564..18.630511 ms` |
| gen24 | `98.46..99.854375 / 97.33..99.33 / 99.34..100 / 98.33..100%` | `98.774667..99.818667 / 97.81..99.65 / 98.67..99.88%` | `7.545596..8.671444 ms` |

其余 invariant：

- `16/16` 正式样本的 personality 均为 `00040000`，即 `ADDR_NO_RANDOMIZE`；`personality_ok=true`。
- gen20 ABBA/BAAB affinity 分别固定为 `[152]`/`[80]`；gen24 为 `[89]`/`[147]`。`16/16` affinity、resolved ELF 与 exe audit 均 PASS。
- `16/16` `cpu-migrations=0`，PMU 与 task-clock scheduled 均 `100%`，`cpus_utilized=1.0`。
- binary 与 NEMU NUMA local ratio 均为 `1.0`。gen20 candidate/control binary pages 为 `20,827/21,260`；gen24 candidate 为 `20,863..20,959`、control 为 `21,260`；NEMU 均为 `115` pages。
- 每条日志都只有一行 walltime，guest cycle、signature、terminal PC、negative-match 与 50k endpoint 功能审计全部 PASS。

## 7. PMU 与 ELF

下表为各 arm 八样本 pooled mean；变化比例均相对该 arm 自己的 fresh control。

| arm / event | control absolute mean | candidate absolute mean | 绝对变化 | 相对变化 |
| --- | ---: | ---: | ---: | ---: |
| gen20 cycles | `268,223,663,848.50` | `265,777,517,872.75` | `-2,446,145,975.75` | `-0.911980%` |
| gen20 instructions | `164,220,521,329.00` | `162,280,390,129.50` | `-1,940,131,199.50` | `-1.181418%` |
| gen20 frontend no-op slots | `1,223,289,093,679.25` | `1,210,267,816,824.25` | `-13,021,276,855.00` | `-1.064448%` |
| gen20 severe frontend empty | `157,853,985,766.25` | `155,759,559,389.25` | `-2,094,426,377.00` | `-1.326812%` |
| gen20 backend stalls | `89,284,206,479.50` | `88,934,720,439.25` | `-349,486,040.25` | `-0.391431%` |
| gen24 cycles | `269,722,660,304.50` | `220,524,122,637.25` | `-49,198,537,667.25` | `-18.240417%` |
| gen24 instructions | `164,220,521,946.75` | `162,274,003,045.00` | `-1,946,518,901.75` | `-1.185308%` |
| gen24 frontend no-op slots | `1,231,139,135,476.50` | `999,596,685,355.00` | `-231,542,450,121.50` | `-18.807172%` |
| gen24 severe frontend empty | `159,204,328,250.50` | `130,069,018,455.25` | `-29,135,309,795.25` | `-18.300576%` |
| gen24 backend stalls | `89,890,614,333.75` | `75,717,320,280.50` | `-14,173,294,053.25` | `-15.767268%` |

gen20 与 gen24 相对各自 control 的 instructions 减少几乎相同（`1.181418%` 对 `1.185308%`），但 gen24 的 cycles、frontend no-op 与 severe frontend empty 额外下降约 `18%`。这与 branch hint 改善代码布局和前端供给、而非减少动态工作量的解释一致。

| arm / role | ELF bytes | SHA-256 | 相对 control |
| --- | ---: | --- | ---: |
| gen20 control | `93,671,768` | `b8f680b2377979083fe4992e86ca7fe9731a35d6369c59236c15abe4423303e6` | baseline |
| gen20 candidate | `91,701,784` | `f3b145f009c55f161386dfb4f34b31219b591422e9a8ece12ba5ece0600e0774` | `-1,969,984 B / -2.103071%` |
| gen24 control | `93,671,768` | `b8f680b2377979083fe4992e86ca7fe9731a35d6369c59236c15abe4423303e6` | baseline |
| gen24 candidate | `91,587,096` | `8e14054c283d0fbaaab262a2628b96fcbbb57047d51175eb8aac47a2e693035d` | `-2,084,672 B / -2.225507%` |

Cold hint 相对 gen20 只再缩小 ELF `114,688 B / 0.125066%`，但带来 `17.169757` 个百分点的 paired walltime 增量；收益不是由大规模代码删除造成。

## 8. 归因与保留决定

本轮得到以下闭环：

1. source diff 只有 cold singleton guard 的 `unlikely`，并且 selector 命中范围已精确 census；
2. gen20 fresh 只有 `0.934017%` 弱正向，gen24 fresh 为可信的 `18.103774%`；单变量差 `17.169757 pp` 复现历史 `17.386665 pp`；
3. 两 arm instructions 变化几乎相同，而 gen24 cycles 与 frontend starvation 同 walltime 一起下降约 `18%`；
4. ABBA/BAAB、fixed-ASLR、whole-CCD、NUMA、PMU、功能与 proof identity 全部通过。

结论：`>=1,024` exact-event singleton register-write guard run 上的 `unlikely` 是约 `18%` 提升的主要来源，并满足其所在 gen24 复合 arm 的端到端 walltime 保留门槛。

本阶段只做归因，没有修改 wolvrix 源码或 current-default。该 hint 依赖 gen20 已形成的 event-qualified run 结构，不能仅凭本次结果直接把一个孤立宏默认到当前 baseline；后续若合入，应以 gen24 复合 patch 为候选，补更广语义回归和 fresh current-default integration 复测后再决定默认。

## 9. 权威产物

```text
/tmp/grhsim-ablation-20260724/candidates/gen20_no_cold_hint.txt
/tmp/grhsim-ablation-20260724/candidates/gen24_cold_hint_1024.txt

/tmp/simpletes-grhsim-simtop-50k/240719f63589edae/slot-0/results/attempts/6397b7de38d265552feaaaa34ab5f79bfb53f2bd53bf191a46f0f3ad0fd4fb45/01784896578555175327-896118-974a79398b0c46b1a530b4ced5f46389/
  complete.json       SHA-256 348f6e0325fdf17df78b5a7eef3124ef0080a979660c639fac6649783c9d65da
  runtime_result.json SHA-256 feb53f2ac204c2a99f36de7f553609ab664cc05c606229fc9da5d06a21fe6d6e
  evaluation.json     SHA-256 16d0e357130d7e38b2f521673266fe23503cfe49ef4748d8d01a734befbeff08

/tmp/simpletes-grhsim-simtop-50k/240719f63589edae/slot-0/results/attempts/e561cdb7c7986cc1b42d6c06af2a66d3d7a5cca648ae158a51bfeba2c04601b9/01784904581644043657-1273403-29ac604f32674dbe99a0a06ffe6fef26/
  complete.json       SHA-256 2a9c39a4c66ebd356848e7cfe754ec98dbcc6ddd058f8463bd79c11d6131da4d
  runtime_result.json SHA-256 1c4b7fc0c07edb3b8da1508c86dd48960e65b2fe9d4202dbbae128019750e039
  evaluation.json     SHA-256 13a7c7e2a6128c6d5d2b7e37fee71b0704e5e4606b9f18f685c04597c91a47f5

/tmp/simpletes-grhsim-simtop-50k/240719f63589edae/slot-0/results/runtime_6397b7de38d26555/
/tmp/simpletes-grhsim-simtop-50k/240719f63589edae/slot-0/results/runtime_e561cdb7c7986cc1/
SimpleTES/checkpoints/grhsim_simtop_50k/formal_20260721_03/2026-07-21/instance-25411edd/db_state_110407/nodes.json
```
