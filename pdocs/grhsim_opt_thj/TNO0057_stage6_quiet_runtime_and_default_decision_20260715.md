# TNO0057 Stage 6 quiet runtime and default decision

日期：2026-07-15

## 1. 实验口径

Stage 6 runtime 使用同一个 atomic helper。每条命令均先执行 `source env.sh`；每轮固定 CPU、SMT sibling 和 NUMA，使用 `setarch x86_64 -R` 关闭 ASLR，并在运行前要求两个 sibling 的 3 秒平均 idle 均 `>=99%`。quiet gate 到 `perf` 启动的间隔为 `6..9 ms`，五项事件全部 `100.00%` scheduled。

所有完整样本都达到相同的 50k 功能终点：

```text
guest cycle / cycleCnt / instrCnt / PC
50001 / 49996 / 73580 / 0x80001312
```

负向扫描均未发现 mismatch、assert、abort、fatal、segfault 或 `input_fullpass_blocked`。可信性能组要求两次 control host cycles spread `<=1%`；candidate 相对两个 control 均值计算，跨 CPU pair 不取算术平均。

三种 binary 的含义必须区分：

- current-default：当前仓库默认 NO0300，direct state-read、pure-event bypass 和 packing 均关闭；
- probe：开启已有 direct state-read 与 threshold-2 pure-event bypass，packing 只规划不采用；
- targeted：与 probe 相同，并采用本阶段新增 active-word packing。

因此 probe/targeted/probe 是 packing-only 因果口径；default/candidate/default 评价的是相对 current-default 的完整组合，不能把组合收益归因给 packing。

## 2. Packing-only quiet A/B/A

packing-only 在两个独立 sibling pair 上都形成有效结果，方向一致：

| Metric | CPU11/203 targeted vs probe mean | CPU84/276 targeted vs probe mean |
| --- | ---: | ---: |
| control cycles spread | `0.600901%` | `0.405452%` |
| host ms | `+1.136966%` | `+5.206848%` |
| cycles | `+1.232498%` | `+5.159403%` |
| instructions | `-1.075517%` | `-1.075642%` |
| frontend empty slots | `+1.840469%` | `+7.258086%` |
| frontend cmask6 cycles | `+2.661447%` | `+9.673721%` |
| backend stalls | `+3.721214%` | `-0.847633%` |

CPU11/203 原始主计数：

| Sample | Cycles | Instructions | FE empty | FE cmask6 | Backend |
| --- | ---: | ---: | ---: | ---: | ---: |
| probe A1 | `267286635613` | `164521486686` | `1217419633558` | `157003419687` | `86717462616` |
| targeted | `271396349769` | `162752034275` | `1244301250376` | `161895542722` | `90739990659` |
| probe A2 | `268897604053` | `164521495433` | `1226208653139` | `158393542862` | `88251546841` |

CPU84/276 原始主计数：

| Sample | Cycles | Instructions | FE empty | FE cmask6 | Backend |
| --- | ---: | ---: | ---: | ---: | ---: |
| probe A1 | `272959001281` | `164521659718` | `1249425000749` | `162235395189` | `90582022545` |
| targeted | `286461325288` | `162751995518` | `1337102108220` | `177407184437` | `89342480272` |
| probe A2 | `271854522507` | `164521659410` | `1243817533927` | `161282731337` | `89630479219` |

packing 在两组中都稳定少执行约 `1.0756%` instructions，但 cycles 与 host time 均超过 1% 可信线回退，frontend 两项也同向恶化。backend 方向不一致，不作为根因；结果与新增 pure words 的删指令收益被 frontend/code-layout 代价反超一致，但本阶段没有用 exact-entry 单独证明 layout 因果。

## 3. Current-default 组合口径

CPU84/276 上形成了一组有效 current-default/targeted/current-default：

| Metric | Default A1 | Targeted | Default A2 | Targeted vs default mean |
| --- | ---: | ---: | ---: | ---: |
| host ms | `84621` | `79195` | `84461` | `-6.323559%` |
| cycles | `306776192673` | `287035861551` | `306284997990` | `-6.359800%` |
| instructions | `172881455672` | `162751994977` | `172881455523` | `-5.859194%` |
| frontend empty slots | `1434645029970` | `1340796234914` | `1432537684728` | `-6.472913%` |
| frontend cmask6 cycles | `191268335601` | `178041756819` | `190799328651` | `-6.800929%` |
| backend stalls | `95310785850` | `88833861781` | `95431051800` | `-6.854350%` |

control cycles spread 为 `0.160243%`。这证明 `direct state-read + threshold-2 bypass + packing` 的当前 native binary 整体相对 NO0300 正向，但不能推翻 packing-only 的负向结论。

同一 CPU 上随后形成有效 current-default/probe/current-default：

| Metric | Default A1 | Probe | Default A2 | Probe vs default mean |
| --- | ---: | ---: | ---: | ---: |
| host ms | `84461` | `74781` | `84249` | `-11.349653%` |
| cycles | `306284997990` | `271125175139` | `305803306249` | `-11.409784%` |
| instructions | `172881455523` | `164521659114` | `172881455203` | `-4.835566%` |
| frontend empty slots | `1432537684728` | `1240112240334` | `1429463215542` | `-13.339493%` |
| frontend cmask6 cycles | `190799328651` | `160756502266` | `190292890817` | `-15.633805%` |
| backend stalls | `95431051800` | `88279520634` | `95743634327` | `-7.645178%` |

control cycles spread 为 `0.157393%`。probe 相对 current-default 是强正向，且比 targeted 更快；这与两组 packing-only 回退方向一致。该收益属于已有 direct state-read 与 threshold-2 bypass 的组合，不是 activity-ID packing 的收益。

## 4. 无效和中断样本

正式有效组出现前没有降低门槛，也没有从不同组挑选 control。以下结果只保留作负载审计，不参与结论：

| Group | Control cycles spread / status | Apparent candidate cycles |
| --- | --- | ---: |
| probe1/targeted/probe1 | `1.090870%`，无效 | `-7.426632%` |
| default1/targeted/default1 | `3.877746%`，无效 | `-7.170996%` |
| default3 | targeted 连续 40 次 gate reject，组不完整 | N/A |
| default4 rolling 1 | `1.006399%`，无效 | `-6.512485%` |
| default4 rolling 2 | `1.235922%`，无效 | `-5.768452%` |
| default4 rolling 3 | `2.225730%`，无效 | `-5.757052%` |
| default5 rolling 1 | `3.550875%`，无效；期间 live `ps` 观察到外部 BOLT 高负载 | `-9.351909%` |
| default5 rolling 2 | `1.383357%`，无效 | `-7.203376%` |

所有表观值均未用于选择候选。最终有效组分别使用严格相邻的 `default5_a3/targeted5_b3/default5_a4`、`default5_a4/probe5_b/default5_a5` 和 `probe6_a1/targeted6_b/probe6_a2`。

上表 BOLT 说明来自运行当时的只读 `ps` 终端观察，现存 runtime artifact 没有归档该进程快照，不能作为事后可复查的日志证据；该组仅凭 `3.550875%` control spread 已足够判无效。

## 5. Artifact 审计边界

首次 targeted batch 74 失败日志后来被成功 targeted 同名日志覆盖，因此 [TNO0054](./TNO0054_stage6_production_probe_and_first_targeted_gate_20260715.md) 与 [TNO0055](./TNO0055_stage6_frozen_batch_cost_proxy_fix_20260715.md) 中 `71228 -> 71234` 的原始 stderr 当前不能从现存 artifact 回查。该数字来自失败当时增强诊断的终端记录。

现存 production probe stats 还是 frozen-line validator 修正前的 schema，不含四个 frozen-line 字段。[TNO0055](./TNO0055_stage6_frozen_batch_cost_proxy_fix_20260715.md) 所述 probe 四字段为 0，限定为修正后 schema 的 `N/A` 语义，不声称当前旧 probe JSON 已含这些 key。

## 6. 默认决策

Stage 6 targeted packing 判定为负收益并停止：

- `pure_event_word_pack_policy` 保持默认 `off`；
- 不通过调预算或选择单一 CPU pair 掩盖两组同向 cycles 回退；
- planner、validators、probe stats 和 focused regression 作为默认关闭的诊断能力保留；
- current-default NO0300 在本阶段提交中不改变。

已有 direct state-read + threshold-2 pure-event bypass 组合在有效 default/probe/default 中取得 `-11.409784%` cycles，是独立的强正向候选。它不属于本次 packing 实现；是否采用应另立阶段，显式复核默认配置、回滚开关与 fresh-default identity 后再提交，不能在本文中静默改写 Stage 6 的因果结论。

原始日志位于：

```text
build/logs/xs_perf/activity_stage6_pure_event_pack_20260715
```

## 增量更新 2026-07-17：绝对数值补录/勘误

原文两组 packing-only 正式 A/B/A 已列出五项 PMU raw counters，但 host ms 只列相对值。以下从对应 `*_emu.log` 的 `Host time spent` 行补录绝对 wall time；没有从百分比反推。样本顺序与单位为 host milliseconds：

| CPU / sibling | 顺序 | sample | host ms |
| --- | ---: | --- | ---: |
| CPU11/203 | 1 | probe A1 | `73,509` |
| CPU11/203 | 2 | targeted B | `74,454` |
| CPU11/203 | 3 | probe A2 | `73,725` |
| CPU84/276 | 1 | probe A1 | `75,148` |
| CPU84/276 | 2 | targeted B | `78,963` |
| CPU84/276 | 3 | probe A2 | `74,962` |

原始路径前缀为 `build/logs/xs_perf/activity_stage6_pure_event_pack_20260715/`，文件依次为：

```text
probe2_a1_emu.log / targeted2_b_emu.log / probe2_a2_emu.log
probe6_a1_emu.log / targeted6_b_emu.log / probe6_a2_emu.log
```

这六个 wall-time 原始值对应原文的 `+1.136966%/+5.206848%`，并不改变 packing-only 负收益结论或 current-default/probe 的独立组合结论。
