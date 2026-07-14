# TNO0033 Stage 2 combination runtime and default decision

记录日期：2026-07-14

状态：Stage 2 `bae-budget` 与 Stage 1 `strict` 组合完成 fresh build、fixed-ASLR 功能门禁和有效 quiet A/B/A；尽管 BAE/DAG 与静态代码尺寸下降，50k cycles 明确回退 `8.713%`，两个策略继续默认关闭。

## 1. Full build 与功能门禁

候选配置与结构结果见 [TNO0032](./TNO0032_stage2_bae_plus_stage1_strict_structure_gate_20260714.md)。full emit 与 O3/link 复现相同 stats，最终产物为：

| Metric | current default | combination | Delta |
| --- | ---: | ---: | ---: |
| generated cpp+hpp count | `154` | `156` | `+2` |
| generated cpp+hpp bytes | `1,379,126,286` | `1,374,559,624` | `-4,566,662` |
| sched cpp count | `117` | `119` | `+2` |
| sched cpp bytes | `1,353,312,855` | `1,348,751,101` | `-4,561,754` |
| emu bytes | `94,768,184` | `94,633,944` | `-134,240` |
| ELF `.text` bytes | `88,186,297` | `88,041,610` | `-144,687` (`-0.1641%`) |

候选哈希：

```text
emu   b717def175dc0e9b681a8830672eb4fba28fa1281c22e693d9ce626b101c7629
.text 028f75b7594bd0321b54237eefc4e8147ad63345855730c6f224b3db3dc1b99e
```

fixed-ASLR 三档功能结果均为 PASS，difftest 正常且负向关键词为零：

| Gate | guest cycle | cycleCnt | instrCnt | PC | host wall |
| --- | ---: | ---: | ---: | --- | ---: |
| 100 | `101` | `96` | `0` | `0x0` | `388 ms` |
| 10k | `10,001` | `9,996` | `458` | `0x800027c6` | `10,449 ms` |
| 50k functional | `50,001` | `49,996` | `73,580` | `0x80001312` | `78,906 ms` |

主要产物：

```text
build/xs_activity_stage2_kahn_bae_postdp_strict_full_20260714/grhsim/grhsim-compile/emu
build/logs/xs/xs_wolf_grhsim_build_activity_stage2_kahn_bae_postdp_strict_candidate_20260714.log
```

## 2. 有效 quiet A/B/A

正式包夹固定在 NUMA1 的 SMT pair CPU113/305，三轮均使用 `setarch $(uname -m) -R` 和同一组五事件。pre-control gate 平均 idle 为 `100% / 99%`，candidate 与 post-control 均为 `100% / 100%`；所有事件 running ratio 均为 `100%`。

三轮 guest endpoint 完全一致：

```text
50001 / 49996 / 73580 / 0x80001312
```

| Metric | pre-control | combination | post-control | Candidate vs control mean |
| --- | ---: | ---: | ---: | ---: |
| cycles | `282,758,826,629` | `307,576,374,238` | `283,089,671,210` | `+8.713331%` |
| instructions | `172,881,288,171` | `171,914,101,837` | `172,881,287,053` | `-0.559451%` |
| frontend empty slots | `1,292,454,118,628` | `1,441,418,959,149` | `1,293,947,701,843` | `+11.461332%` |
| frontend cmask6 | `167,559,442,433` | `192,240,299,626` | `167,801,521,071` | `+14.646796%` |
| backend stalls | `92,881,424,022` | `94,050,757,875` | `93,261,472,416` | `+1.052213%` |
| host wall | `77,087 ms` | `83,894 ms` | `77,172 ms` | `+8.770315%` |

两侧 control cycles spread 仅 `0.116938%`，远低于候选回退，也低于本阶段 `1%` 可信门槛。candidate 少执行约 `0.56%` instructions，却增加 `11.46%` frontend empty slots 和 `14.65%` frontend cmask6；因此回退来自明显的前端供给/代码布局恶化，而不是动态逻辑工作增加。BAE `-1.156%`、DAG `-3.748%` 和 `.text -0.164%` 均不足以预测该布局效应。

正式原始数据：

```text
build/logs/xs_perf/activity_stage2_kahn_bae_budget_20260714/combo_control_after5_*
build/logs/xs_perf/activity_stage2_kahn_bae_budget_20260714/combo2_candidate_*
build/logs/xs_perf/activity_stage2_kahn_bae_budget_20260714/combo2_control_after1_*
```

## 3. 排除的跨状态序列

第一次组合测量将较早的约 `300 B` cycles control 与随后降到约 `283 B` cycles 的 control 混在同一包夹中，频率/系统状态已经变化，因此该组不得用于正式百分比。其 candidate cycles 为 `307,823,181,138`，与有效重测的 `307,576,374,238` 接近，但这里只保留为诊断旁证。

正式序列以紧邻 candidate 的 `combo_control_after5` 和 `combo2_control_after1` 为两侧 control；两者 spread `0.117%`，闭合了同一性能状态下的 A/B/A。

## 4. Stage 2 结论与默认配置

Stage 2 standalone `bae-budget` 在 [TNO0031](./TNO0031_stage2_bae_budget_quiet_aba_20260714.md) 中仅改善 `0.324%` cycles，低于可信门槛；与 Stage 1 `strict` 组合则明确回退 `8.713%`。因此 current-default 保持：

```text
kahn_level_pack_policy=off
post_dp_refine_policy=off
```

实现、显式 options、exact evaluator 和测试继续默认关闭保留，供后续定向实验使用。本阶段同时证明：即使 BAE、DAG、boundary values、instructions 与 `.text` 都下降，activity schedule 的函数/分片布局仍可能触发大幅 frontend cliff；后续候选必须继续跑 fixed-ASLR 50k，不能用结构指标直接晋升。

## 5. 增量生成代码与 PMU 归因

对 current-default 与组合候选的生成代码、ELF symbol 和五事件做进一步对照：

- compute batch 数均为 `66`，runtime header、生成参数与 clang `-O3` 配置一致；
- compute 函数总 `.text` 从 `72,012,132` 降至 `71,872,876` bytes（`-0.193%`），排除代码总量膨胀；
- 66 个 compute 函数的绝对 size 变化平均约 `87.5 KiB`、最大约 `378 KiB`，地址绝对漂移平均约 `121 KiB`、最大约 `445 KiB`，说明 batch 内容和链接布局被广泛重排；
- sched translation unit 从 `117` 增至 `119`，来自 commit estimated-line 重切分，不是 compute batch 数增加。

PMU 归一后，IPC 从约 `0.6111` 降至 `0.5589`（`-8.53%`）；frontend empty slots/cycle 与 frontend cmask6/cycle 分别增加约 `2.528%` 和 `5.458%`，backend stalls/cycle 反而下降约 `7.047%`。结合 standalone Kahn-level pack 的 `-0.324%` cycles，可将组合的主要负收益定位到追加 Stage 1 post-DP strict 后发生的前端代码布局/动态局部性退化。

现有五事件不能继续严谨地区分 I-cache/iTLB、分支预测/BTB alias 或活跃 supernode 代码页局部性，因此本文不把回退写成某个具体 frontend 子机制已经证实。若未来重启该方向，应先增加 frontend 子事件或 `perf record`，而不是继续仅按 BAE/DAG 搜索。
