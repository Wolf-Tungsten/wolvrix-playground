# TNO0110 Walltime headline criterion and historical re-evaluation

记录日期：2026-07-17

状态：正式性能终点从 host cycles 改为 SimTop `Host time spent` walltime。现存 runtime TNO 已按原始 emu/runner wall 值重审；除 Stage 12 cap8192/N0 的解释发生实质变化外，默认选项决定均不变。cycles、instructions、frontend/backend 继续保留为诊断指标，不再单独裁决采用。

## 1. 新的最终性能口径

后续 SimTop 50k 的最终 headline 为 host walltime milliseconds。一个样本只有同时满足以下条件才可进入性能统计：

- 每条命令先执行 `source /nfs/home/tanghaojin/wolvrix-playground-gsim-calibrate-2/env.sh`；
- fixed-ASLR、guest 终点、difftest、CPU affinity、NUMA memory policy、node-local file placement、whole-node pre-gate/runtime monitor、scheduler/migration 与 PMU scheduling 等既有硬门禁全部通过；
- emu log 中存在唯一、正整数的 `Host time spent: Nms`；runner result 写出 `walltime_ms=N` 和 `walltime_ok=1`；
- control/candidate 的 binary header、顺序和原始 `*_emu.log`/result path 明确；不能按 `a/b` 文件名猜测角色；
- A/B/A 使用两侧 control 均值；ABBA/BAAB 分别对两份 control 与两份 candidate 取均值后计算，并同时报告合并值与两种顺序；多候选长序列若使用时间插值，必须按实际 sample center 计算并保存时间戳。

当前 strict runner `build/logs/xs_perf/page_local_retest_stage7plus_20260716/run_formal.sh` 已从 emu log 提取 `walltime_ms`，要求匹配恰好一条且为正整数（写入 `walltime_count=1`、`walltime_ok=1`）；缺失、重复或非正值均在最终 hard gate 中拒绝。共享 metrics 工具也只在唯一匹配时生成 `emu_host_time_ms`。`cycles:u`、`instructions:u`、frontend empty、frontend `cmask>=6`、backend stalls 及其它 branch/cache/TLB 事件只用于解释 wall 变化或发现异常。

性能可信线改为 walltime 口径：至少报告 control wall spread；candidate 的信号应与 `max(1%, control wall spread)` 比较。轻微结构退化仍可进入 SimTop，不以 BAE/DAG/size 预判；最终采用看 walltime。

## 2. TNO0001..TNO0051 walltime 审计

早期 runtime 的绝对 wall 已在原 TNO、对应旧 NO 或 [TNO0108](./TNO0108_absolute_raw_value_audit_and_missing_ledger_20260717.md) 追加章节中闭合：

| TNO | walltime headline / status | 重评估 |
| --- | --- | --- |
| TNO0001 | small-load GSim/GrhSIM 原始 wall 完整 | 方法/基线记录，不改结论 |
| TNO0002 | Vtype 2M：GrhSIM `4695.578 -> 4135.227 -> 4008.740 ms` | full-width/inline 正向，结论不变 |
| TNO0003 | component full-pass absolute off/on；SimTop settle 是功能/诊断 | component 正向；不把诊断 wall 当正式跨版本 gate |
| TNO0004/0005/0006 | full-mask、PHR、broadcast、active scan、array merge、slot alias/commit 的绝对 wall 已列 | wall 与 cycles 同向，历史保留/停止决定不变 |
| TNO0007/0009 | 随机 PIE overall `81230/81313 -> 84405 ms` | 只作 provisional；TNO0010 fixed-ASLR 正式替换 |
| TNO0010 | fixed-ASLR `81085/81301 -> 77319 ms`，约 `-4.77%` | ordered-affine 正向，结论不变 |
| TNO0011 | native direct `77813/77410 -> 82461 ms`，`+6.248%` | native layout 下回退，保持当时默认关闭 |
| TNO0012 | exact-entry `83678/84180 -> 82455 ms`，`-1.733%` | direct 机制正向，结论不变 |
| TNO0015 | native `83706 -> 85634 ms`，exact-entry `77429.5 -> 79011 ms` | full active-word consume 两边回退，保持关闭 |
| TNO0019/0020 | formal quiet 样本为 0；TNO0020 高负载 A/A spread `27.62%` | 不产生性能结论 |
| TNO0022 | current-default baseline-only `77594 ms` | 作为基线，不含 candidate |
| TNO0025/0030/0038/0049 | 仅 functional 50k wall、无有效 control | 不用于性能排序 |
| TNO0027 | 无 accepted candidate runtime | unrecoverable-by-design，不造值 |
| TNO0028 | 历史 affinity `386385 -> 457820 ms`，`+18.49%` | 历史反例，非 current baseline |
| TNO0031 | `82521/82277/82629 ms`，`-0.360884%` | neutral，Kahn pack 保持 off |
| TNO0033 | `77087/83894/77172 ms`，`+8.770315%` | 组合回退，Stage1/2 保持 off |
| TNO0039 | `77881/78101/78038 ms`，`+0.181504%` | neutral，clone 保持 off |
| TNO0050 | `78006/78547/77659 ms`，`+0.917997%` | neutral-to-mild regression，保持 off |
| TNO0051 | control/strict/balanced/bae/control `77694/84773/84565/84283/77423 ms` | 三策略均约 `+8.67%..+9.30%`，保持 off |

这些 accepted A/B/A 中没有 wall 与 cycles 方向相反的案例。TNO0009 的 profile-instrumented wall 与无插桩 cycles 属于不同 binary/测量口径，不构成冲突。

## 3. TNO0052..TNO0107 walltime 重评估

| TNO / candidate | raw wall order或 wall delta | cycles 对照 | walltime 结论 |
| --- | --- | --- | --- |
| TNO0057 packing-only CPU11/203 | `73509/74454/73725 ms`，`+1.136966%` | `+1.232498%` | 回退，pack off |
| TNO0057 packing-only CPU84/276 | `75148/78963/74962 ms`，`+5.206848%` | `+5.159403%` | 回退，pack off |
| TNO0060 old Stage7 hybrid | N0 `+4.2565%/+4.9772%`，N1 `-12.4887%/-12.2335%` | 同向强反转 | 旧 page-cache 协议，仅历史风险证据 |
| TNO0064 old Stage8 p050/p200 | N0 `+7.2377%/+11.7012%`，N1 `-9.6177%/-10.0091%` | 同向强反转 | 旧协议；由 TNO0087 替换 |
| TNO0072 strict | N0 `-0.087743%`，N1 `+0.727603%` | `-0.0903%/+0.7464%` | neutral/mild，off |
| TNO0074 corrected same-post | N0 `-8.771102%`，N1 `+9.366545%` | 同向强反转 | default off；旧 page placement 局限保留 |
| TNO0081 cap8192 | N0 `+3.207308%`，N1 `+7.651030%` | N0 `-0.2601%`，N1 `+7.7085%` | 唯一实质分歧；wall 明确双 node 回退，cap4096 更应保留 |
| TNO0081 cap16384 | N0/N1 `+7.411815%/+7.620319%` | 双 node 回退 | off |
| TNO0081 cap32768 | N0/N1 `+11.091921%/-0.474710%` | socket 方向分裂 | off |
| TNO0085 locality 10k | N0 remote `+2.79%`，N1 remote `+3.48%` | wall-only diagnosis | 证明 file-page locality 必须 gate |
| TNO0087 hybrid | N0/N1 `-4.124340%/-4.399014%` | `-4.237%/-4.353%` | 双 node 正向，支持 Stage14 native default |
| TNO0087 p050 | N0/N1 `+0.235477%/+0.073598%` | 约中性 | neutral，penalty 不改 |
| TNO0087 p200 | N0/N1 `+0.207507%/+0.425537%` | 两边轻微回退 | 不采用 |
| TNO0089 interim cap32768 | N0/N1 `-0.080402%/+1.230935%` | 同一旧协议 control drift | 不晋升 |
| TNO0089 interim cap8192 | N0/N1 `-0.132481%/-2.183389%` | N1 apparent 收益 | 旧 protocol/control drift，仍不晋升 |
| TNO0099 native hybrid N0 strict | ABBA `-4.079692%`，BAAB `-3.956222%`，combined `-4.017956%` | combined `-3.976741%` | 采用结论确认 |
| TNO0104 targeted-direct N0 | ABBA `+0.205534%`，BAAB `-0.318608%`，combined `-0.056566%` | combined `-0.031601%` | 顺序反向且低于 spread，neutral/off |

TNO0089/TNO0102 中旧“cycles 主口径”已追加勘误；TNO0090/TNO0092 的 adoption 依据已改为 TNO0087 wall headline。TNO0091/0094/0098 没有通过 strict admission 的正式 perf，TNO0106 只有 monitor-failed single A1，均不产生 wall 结论。

## 4. 默认选项重评估

walltime headline 下，当前默认决定为：

- C++ native hybrid `direct_single_writer_state_reads=true` 与 `pure_event_compute_word_bypass=true` 继续采用；TNO0087 双 node wall 和 TNO0099 N0 strict wall 都给出约 `4%` 收益。
- commit cap 继续 `4096`；TNO0081 cap8192/N0 的 wall/cycles 分歧消除了唯一看似正向的 N0 cycles 信号。
- Stage8 fixed penalty 继续 `1000000 PPM`；p050 neutral、p200 mild regression。
- Stage10 fanin、Stage17 targeted-direct、Stage1..6 schedule/packing/cloning 等可选策略继续默认关闭。
- N1 strict balanced 缺口、P1 cap8192 attempt2 及后续新候选仍须按 walltime protocol 补测；不因机器忙而降低 gate。

README 中旧行的 cycles 数字保留为历史摘要，不回写覆盖；从本记录之后新增的 runtime TNO 必须先报告 raw walltime、wall delta、control spread 和判定，再列 PMU 诊断。

## 5. 唯一性校验实现

共享指标工具 `scripts/grhsim_opt_metrics.py` 同步输出 `emu_host_time_count`；只有恰好一条 `Host time spent` 匹配且值为正整数时才生成 `emu_host_time_ms`。missing/duplicate log 都不再被静默当作有效 walltime；对应测试已通过。
