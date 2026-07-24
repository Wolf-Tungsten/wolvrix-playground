# TNO0171 SimpleTES 18% ablation design and static attribution

## 1. 目的与裁决口径

本文启动对 [TNO0167](./TNO0167_simpletes_long_continuation_final_results_semantic_audit_and_default_hold_20260723.md) 中约 `18%` 跃升的正式消融。最终裁决仍只看当前仓库默认生成配置上的 SimTop 50k `Host time spent` walltime；每个正式 arm 必须通过 default-off、unpatched-options、focused test、100/10k 功能、whole-CCD quiet admission、fixed-ASLR、NUMA first-touch、PMU 和 ABBA/必要时 BAAB 门禁。静态代码、ELF 和 PMU 仅用于解释，不能替代 walltime。

本轮先做最小单变量实验：从 long continuation 的相邻有效 checkpoint 精确恢复 gen20 与 gen24。两者共享相同 enable option 和此前的复合机制，gen24 只比 gen20 多 cold singleton guard 的 branch hint，因此可以直接检验该 hint 是否是主要来源。

## 2. 历史跃升位置

long continuation 的正式 pooled 结果为：

| arm | node/digest | control (ms) | candidate (ms) | 改善 (ms) | 改善 (%) |
| --- | --- | ---: | ---: | ---: | ---: |
| gen20 | `65e3d3b5...` / `7a2c4eecca2ca55d` | `74,052.00` | `73,469.50` | `582.50` | `0.786609%` |
| gen24 | `ce990cc9...` / `911de849ff1297ee` | `73,952.00` | `60,512.50` | `13,439.50` | `18.173275%` |

收益在相邻有效 checkpoint 之间增加 `17.386666` 个百分点。gen24 candidate 的绝对 walltime 比 gen20 candidate 低 `12,957.00 ms`，即相对 gen20 candidate 低 `17.635890%`；两者来自不同 formal pair，这一数值只用于定位跃升，不能替代 fresh 单变量复测。

## 3. 机械 source-diff 结论

对最终 `nodes.json` 中 gen20 与 gen24 的 aggregate patch 做机械展开，并对应用后的 `lib/emit/grhsim_cpp.cpp` 做 source diff。两者均显式启用：

```text
active_mask_gap_pack_policy=targeted-direct
```

两者已经共同包含以下机制：

- `supernode_active_curr_` 64-byte alignment；
- event-qualified terminal bitmap continuation；
- selective `trackCommitActivation`；
- lockstep scalar commit state-write grouping。

gen24 唯一新增的运行时机制是：exact-event commit run 中，当连续 run 至少含 `1,024` 个 non-true singleton `kRegisterWritePort` guard 时，把普通 `if (cond)` 改为 `if (unlikely(cond))`。SimTop 生成结构中命中 `16` 个 run、共 `44,976` 个 guard。没有新增 guard、state write 或动态过滤；变化只影响编译器 branch weighting 和代码布局。

## 4. 历史 PMU 与 ELF 旁证

下面比较两份历史 candidate 的八样本 pooled mean，绝对值直接取各自正式 manifest：

| 指标 | gen20 candidate | gen24 candidate | 绝对变化 | 减少比例 |
| --- | ---: | ---: | ---: | ---: |
| walltime (ms) | `73,469.50` | `60,512.50` | `-12,957.00` | `17.635890%` |
| cycles | `268,864,980,371.25` | `221,425,190,666.50` | `-47,439,789,704.75` | `17.644466%` |
| instructions | `162,280,467,719.50` | `162,274,079,962.25` | `-6,387,757.25` | `0.003936%` |
| frontend no-op slots | `1,228,301,088,076.25` | `1,003,884,798,370.00` | `-224,416,289,706.25` | `18.270463%` |
| severe frontend empty | `158,706,616,540.50` | `130,789,052,489.25` | `-27,917,564,051.25` | `17.590674%` |
| backend stalls | `89,626,086,258.75` | `76,960,536,627.25` | `-12,665,549,631.50` | `14.131544%` |
| ELF bytes | `91,701,784` | `91,587,096` | `-114,688` | `0.125066%` |

instructions 几乎不变，而 cycles、walltime 和 frontend starvation 同步下降约 `17.6%..18.3%`。结合唯一 source delta，当前最强解释是 `unlikely` 改变 Clang hot/cold block placement 和前端取指供给，而不是消除了约 `18%` 的动态工作。正式复测仍是该解释成立的必要条件。

## 5. Fresh 消融 arm

新增 `SimpleTES/datasets/grhsim/simtop_50k/materialize_ablation.py`，按 `gen_id` 从 checkpoint 精确恢复 patch/options，仅改变 hypothesis/evidence 标签以得到独立 evaluator digest。SimpleTES commit 为 `eae056e`，`tests/test_grhsim_bench.py` 共 `40 passed`。

| arm | fresh digest | 变量 |
| --- | --- | --- |
| gen20/no-cold-hint | `6397b7de38d265552feaaaa34ab5f79bfb53f2bd53bf191a46f0f3ad0fd4fb45` | 共享复合机制，不发射 cold guard hint |
| gen24/cold-hint-1024 | `e561cdb7c7986cc1b42d6c06af2a66d3d7a5cca648ae158a51bfeba2c04601b9` | 唯一增加 `>=1024` cold guard `unlikely` |

两份候选均通过 `--validate-only`，只允许修改 `lib/emit/grhsim_cpp.cpp`，enable option 均为 `targeted-direct`。正式 evaluator 串行运行，不能让两个 50k arm 并发污染 CCD。

## 6. 启动状态与后续门槛

`2026-07-24 15:23 +08:00` 左右已启动 gen20 fresh evaluator。`15:35 +08:00` 时已进入 `unpatched-options` attribution emit，尚无 fresh walltime；gen24 必须等待 gen20 完整结束后再启动。

本阶段不修改 wolvrix 默认配置。后续判断规则：

1. 若 fresh gen20 仍约为 `0%..1%`，而 gen24 稳定约为 `18%`，则主收益可以归因给 cold-guard `unlikely`。
2. 若两者 fresh 差距显著缩小，则历史跃升含布局随机性或构建环境交互，继续做重复/反序复测。
3. 只有端到端 walltime 正向、功能与 formal gate 全过的机制才考虑保留或默认开启；当前只做消融，不晋升代码。

## 7. 权威产物

```text
SimpleTES/checkpoints/grhsim_simtop_50k/formal_20260721_03/2026-07-21/instance-25411edd/db_state_110407/nodes.json
/tmp/grhsim-ablation-20260724/candidates/gen20_no_cold_hint.txt
/tmp/grhsim-ablation-20260724/candidates/gen24_cold_hint_1024.txt
/tmp/simpletes-grhsim-simtop-50k/240719f63589edae/slot-0/results/evaluation_7a2c4eecca2ca55d.json
/tmp/simpletes-grhsim-simtop-50k/240719f63589edae/slot-0/results/evaluation_911de849ff1297ee.json
```
