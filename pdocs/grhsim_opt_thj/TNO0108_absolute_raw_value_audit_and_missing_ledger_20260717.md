# TNO0108 TNO0001..TNO0107 absolute-value audit and missing ledger

记录日期：2026-07-17

状态：完成 `TNO0001..TNO0107` 全目录审计。本文是统一台账，不覆盖或改写旧结论；能从原始 artifact 恢复的值已追加回原 TNO，不能恢复的证据按 unrecoverable/排除样本登记。性能 headline 的 walltime protocol 另由 [TNO0110](./TNO0110_walltime_headline_criterion_and_re_evaluation_20260717.md) 规定。

## 1. 审计范围与方法

- 先完整读取本目录 `RULES.md` 与 `README.md`，再逐篇读取 `TNO0001..TNO0107`；同时检查每篇列出的 `build/logs`、`build/worktrees`、`build/xs`、`perf.csv`、`*_emu.log`、runner result 和对应旧 `NO` 来源。
- 将“正式 accepted control/candidate 样本”“结构/size 静态对照”“功能 gate”“计划/实现/回归”“被拒绝或不完整样本”分开。只有相对百分比但没有同篇或可追溯绝对原值的记录才进入补录或 missing ledger。
- 绝对值只抄自原始计数、文件大小、行数或 `Host time spent`；没有用百分比反推。每个补录章节注明 sample 顺序/数量、事件或单位和原始路径/旧 NO 来源。
- 对 derivative/citation-only 文档不重复复制同一 raw 表，而是在台账中指向已补齐的 authoritative TNO。

## 2. 已追加绝对值的文档

| TNO | 补录内容 | 样本/口径 | 原始来源 |
| --- | --- | --- | --- |
| TNO0002 | VtypeBuffer 长窗口 baseline/full-width/inline 的 GSim/GrhSIM host ms | 3 个实现 × 2 simulator；ms | `NO0226` raw gate/artifact |
| TNO0004 | state-read slot-alias host wall | baseline A1 / candidate / baseline A2，另列独立复测 | `build/logs/xs_perf/no0283/` |
| TNO0009 | 无插桩随机 PIE wall + cycles | old1 / ordered new / old2 | `build/logs/xs_perf/no0302/` |
| TNO0026 | sched17/18 bytes、object `.text` bytes、definition lines | baseline resume-control / strict / balanced；static bytes/lines | `build/worktrees/activity_baseline_20260714/`、`build/xs_activity_stage1_*` |
| TNO0028 | 历史 NO0085 structure、wall、perf counters | original topo / activation-affinity；历史 2 样本 | `pdocs/grhsim_opt/NO0085_xs_no0076_fresh_rerun_20260510.md` |
| TNO0033 | 被排除 cross-state sequence cycles raw | combo candidate + late controls；不进入正式 A/B/A | `build/logs/xs_perf/activity_stage2_kahn_bae_budget_20260714/` |
| TNO0057 | formal packing-only host wall | CPU11/203 与 CPU84/276 各 A/B/A，共 6 | 同目录 `probe2_*`、`probe6_*_emu.log` |
| TNO0060 | 四组 hybrid 五事件 PMU + host wall | 4 个 A/B/A，共 12 | `activity_stage7_hybrid_default_20260715/` |
| TNO0064 | 四组 p050/p200 五事件 PMU + host wall | 12 个 group positions、11 份不同 CSV/log | `activity_stage8_dp_penalty_20260715/` |
| TNO0072 | strict fanin wall | N0/N1 各 A/B/A，共 6 | `activity_stage10_fanin_strict_20260716/` |
| TNO0074 | corrected same-post wall | N0/N1 各 A/B/A，共 6 | 同上 `sp_n0_*`、`sp2_n1_*` |
| TNO0081 | 五档 cap raw PMU + wall | 每 node control/8192/16384/32768/control，共 10 | `activity_stage12_commit_guard_merge_cap_20260716/` |
| TNO0087 | corrected page-local PMU + wall | 每 node 7 个 accepted，共 14 | `page_local_retest_stage7plus_20260716/results/{n0,n1}_rollback/` |
| TNO0089 | interim cap32768/cap8192 wall | 4 个旧 A/B/A，共 12；只作诊断 | page-local driver/emu logs |
| TNO0090/TNO0092 | adoption headline 勘误 | 引用 TNO0087，不新增样本 | TNO0087 wall raw |
| TNO0099 | native hybrid strict wall | ABBA/BAAB 各 4，共 8 | `groups/n0/stage14_default_strict_p0_{abba,baab}_try1/` |
| TNO0102 | 后续 walltime protocol 勘误 | plan；无 runtime sample | TNO0089/runner contract |
| TNO0104 | targeted-direct wall | ABBA/BAAB 各 4，共 8 | `groups/n0/stage17_targeted_direct_strict_p0_{abba,baab}_try1/` |

TNO0057/0060/0064/0072/0074/0081/0087/0089/0099/0104 的新增章节还明确写出 event 名称/单位、sample 顺序和 `Host time spent` 路径；TNO0089/TNO0102 的旧 cycles 主口径已由 walltime 勘误替代。

## 3. 已有绝对值或交叉来源的文档

以下正式或静态记录在原文已经有 control/candidate 绝对表，或其相对摘要紧邻同一文档/authoritative TNO 的绝对表，因此不重复拷贝：

- TNO0001、TNO0003、TNO0005、TNO0006、TNO0007、TNO0008、TNO0010、TNO0011、TNO0012、TNO0015、TNO0018、TNO0020；
- TNO0022、TNO0023、TNO0024、TNO0025、TNO0029、TNO0030、TNO0031、TNO0032、TNO0033（正式组）、TNO0036、TNO0037、TNO0038、TNO0039、TNO0042、TNO0048、TNO0049、TNO0050、TNO0051；
- TNO0056、TNO0059、TNO0062、TNO0063、TNO0066、TNO0069、TNO0071、TNO0072、TNO0074、TNO0079、TNO0080、TNO0083、TNO0084、TNO0085、TNO0086、TNO0089；
- TNO0091、TNO0094、TNO0095、TNO0097、TNO0099、TNO0100、TNO0103、TNO0105。

TNO0058→0057、TNO0073→0072、TNO0090/0092→0087、TNO0102→0100 是引用/计划关系；TNO0085 与 TNO0089 本身已经含 wall 原始表。计划、实现、结构 gate、回归 gate 和无 emu probe 不要求伪造 control/candidate runtime。

## 4. Unrecoverable / rejected ledger

这些条目没有可作为正式 accepted control/candidate 结果的绝对值；台账保留原因，不从百分比造值：

| TNO/字段 | 搜索位置 | 原因与处置 |
| --- | --- | --- |
| TNO0026 model-storage absolute bytes | Stage 1 analyzer outputs、`build/worktrees/activity_baseline_20260714/` | 只剩约 `2.6..2.8 KB` 摘要，canonical analyzer 字段/原始输出未保留；已列 unrecoverable，不影响其它 static raw。 |
| TNO0027 strict/balanced/bae-budget candidate runtime | `build/logs/xs_perf/activity_stage1_policies_20260714/` | 没有 accepted candidate perf/emu，只有 high-load diagnostic control；不能补造 A/B/A。 |
| TNO0045/0046 final candidate stats | 对应 Stage 5 build/diagnostic logs | mutation 后在 final stats 前硬失败；只有 rewrite/order diagnostics，candidate final structure/runtime 不存在。 |
| TNO0054/0055 首次 stderr `71228 -> 71234` | Stage 6 artifact | 后续成功同名日志覆盖首次失败 stderr；数字仅来自当时终端记录，不是 accepted runtime 字段。 |
| TNO0057 invalid/high-spread rows | `activity_stage6_pure_event_pack_20260715/` | 这些组明确被 control-spread/gate 判无效；BOLT `ps` 快照未归档。正式有效组的 raw 已补录，不把无效组混入结论。 |
| TNO0064 rejected p050、TNO0074 orphan N1、TNO0089 cap16384、TNO0106 monitor-failed A1 | 各自 page-local/strict group dirs | gate/monitor 失败或包夹不完整，没有 accepted candidate 结论；保留 rejection 证据，不降低门槛。 |
| TNO0091/TNO0094/TNO0098、TNO0104 N1 | 对应 strict-window survey/runner logs | pre-perf rejection 或外部负载阻断，未启动完整性能组；不写成性能回退/收益。 |

## 5. Walltime audit handoff

全目录 accepted runtime 的 wall 原值均已在原 TNO、旧 NO 或本次追加章节中找到；没有 accepted-unrecoverable wall field。唯一会改变旧 interpretation 的有效差异是 TNO0081 cap8192/N0：cycles 插值为 `-0.2601%`，但按相同 run-center wall 插值为 `+3.207308%`，因此默认 cap4096 的保守决定更强。其它 accepted A/B/A 中 wall 与 cycles 方向一致，旧默认选项决定不因 headline 切换而改变。

新的 runner contract、headline 规则和逐阶段 walltime re-evaluation 见 [TNO0110](./TNO0110_walltime_headline_criterion_and_re_evaluation_20260717.md)。
