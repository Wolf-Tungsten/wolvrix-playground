# SimpleTES extended best-path direct ablation result

## 1. 阶段结论

在 [TNO0204](./TNO0204_simpletes_extended_bestpath_ablation_materialization_and_launch_20260731.md)
物化的最终 `gen150` 与六个严格 `final-minus-one` arm 上，已完成同一 CCD 的 SimTop 50k
`ABBA+BAAB` direct ablation。每组把 `final−X` 作为 control、完整 final 作为 candidate；正的
`(control−candidate)/control` 表示机制 X 在最终上下文中有收益。headline 只使用
`Host time spent` walltime。

所有正式轮次都满足：同一个 CPU/CCD 跑完两个 order，并且 ABBA 与 BAAB 的收益率 gap 严格小于
`0.25` 个百分点。最终结果如下：

| final 中被消融的机制 | control→final / ms | walltime 变化 | ABBA | BAAB | order gap | 结论 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| cold assertion/SystemTask hints | `52,365.25→51,693.75` | `+671.50 ms/+1.282339%` | `+1.327670%` | `+1.236974%` | `0.090697 pp` | 可信正向 |
| inline helpers | `52,032.75→51,645.75` | `+387.00 ms/+0.743762%` | `+0.729058%` | `+0.758479%` | `0.029421 pp` | 稳定弱正向 |
| constant MemoryRead proof/zero elimination | `51,964.75→51,585.00` | `+379.75 ms/+0.730784%` | `+0.695707%` | `+0.765856%` | `0.070149 pp` | 稳定弱正向 |
| shift/index OOB cold hints | `51,778.50→51,652.75` | `+125.75 ms/+0.242861%` | `+0.197044%` | `+0.288655%` | `0.091610 pp` | 稳定但很弱的正向 |
| residual MemoryRead OOB cold hints | `51,715.00→51,774.50` | `−59.50 ms/−0.115054%` | `−0.034797%` | `−0.195350%` | `0.160553 pp` | 双 order 小幅回退 |
| physical zero-tail | `51,297.50→51,424.50` | `−127.00 ms/−0.247575%` | `−0.172508%` | `−0.322656%` | `0.150148 pp` | 双 order 稳定回退 |

这里的 `+ms/+%` 表示 final 更快，`−ms/−%` 表示加入该机制后的 final 更慢。按 TNO0204 在正式
walltime 前固定的分类线，只有 cold assertion/SystemTask 的 `1.282339%` 达到
`max(1%, control spread/control mean)`；inline、constant MemoryRead 与 shift/index 虽然双 order
同向且 gap 很小，但都低于 `1%`，只能记为弱信号。residual MemoryRead 和 physical zero-tail 在
两个 order 都回退，不应作为后续 landing/default 候选。

## 2. Fresh build 与功能门禁

基线保持 parent `d31118bea0feb563ad09476e1419f0f15aaf574f`、Wolvrix
`16a9f493687a21a5428f1e1327a69834ea60c9f5`；final candidate digest 为
`1afdcb97fc009d6a3e656792eeb6f66751952cc2ac6506051cf050348d95efbb`，materialized source
SHA-256 为 `e4cd8e0c23d4c15d17e999b12f2ccf4d3fe2585a0cb66615be87bb7903b97756`。
七个 arm 在隔离 repo 中并行 fresh emit/O3 link，随后每个 arm 都通过 trusted focused `29/29`、
fixed-ASLR 100-cycle 和 10k-cycle SimTop 功能门禁。

| artifact | ELF bytes | ELF SHA-256 |
| --- | ---: | --- |
| final gen150 | `90,873,536` | `7e5ffc22fd309c0fb3fe4f5789591bd6bffaed3e55f2a7fda2e39f58d090ffa9` |
| final−cold assertion | `90,803,904` | `96c75132c011a164d7c323b6d59fe5733f60710b4fa9b9a3dbc6425473520d6f` |
| final−inline helpers | `91,333,144` | `e18d2eabea9bb7e6540e2a70d191618dcc6c8d84484499d50c57fa18d68de65c` |
| final−constant MemoryRead | `90,906,304` | `c34fcedc019e889eb987fa139ded640302dcac429496e3e765d85fd3bcf73281` |
| final−shift/index | `90,865,344` | `dceaf38fcc0847832ab40f582131cf269b0edb18d92813dbed949118553236ce` |
| final−residual MemoryRead | `90,873,536` | `a9950562aff7e26e92a40182ac62349ac5680d6437e5e05e2c54174c69de0552` |
| final−physical zero-tail | `90,873,536` | `c5163239a683d9fc204a46e90779a559d4c04193f767bffb50ab5ca04b21d540` |

首次 post-build gate 中，`minus_cold_assert` 的人类可读 artifact 路径本身含有字符串 `assert`，被
evaluator 对完整 emu log 的负面正则误判为功能失败；同一个 worker 异常跨 `ProcessPool` 后在顶层
表现为 `BrokenProcessPool`。手工核对确认 ELF 与功能输出正确，随后仅把完全相同的 ELF/image/NEMU
字节复制到 digest-only 中性临时路径执行 gate；最终 focused、100/10k 全过，正式 summary 为
`7` results、`0` failures。初始失败 summary 和原始响应均保留，不改变任何 SimpleTES production
evaluator 源码。

## 3. 同 CCD 协议修正

最初的 `run_pair.py` 分别创建 ABBA 和 BAAB runtime，只保证每个四样本组内部固定 CCD；cold
assertion 的两种 order 因而落在不同 NUMA node/CCD。旧 `direct_loo_v4` 的 cold 与 inline 数据
全部降级为诊断值，constant 尚未完成即停止；细节已在 TNO0204 追加勘误。

正式 runner `run_pair_sameccd.py` 对一个完整 paired attempt 只创建一个 `GrhSimRuntime`：

1. ABBA 动态选择通过 whole-CCD quiet window 的 placement；
2. BAAB 复用完全相同的 CPU、SMT sibling、CCD、NUMA node 和 helper CPU；
3. 每个样本仍执行 fresh pre-gate、运行中连续监控、NUMA first-touch、PMU、fixed-ASLR 和功能审计；
4. 任一 order 被污染时，整个八样本 paired attempt 作废；不把不同 attempt 的半轮拼接。

修正版第一遍 `direct_sameccd_v1` 已对六项各形成一个完整同 CCD 结果。随后用户在看到部分 order gap
后追加了更严格的一致性要求：gap 大于等于 `0.25 pp` 的机制继续运行完整同 CCD pair，直到首次获得
gap 严格小于 `0.25 pp` 的轮次。这个阈值不是性能运行前预注册的分类线，因此所有历史轮次必须公开，
并把它明确视为后验 replication consistency filter，而不是隐藏的收益挑选。

自动 driver 的选择规则固定为“按时间顺序取首个完整且 gap `<0.25 pp` 的 pair”，不在多个合格轮次
中挑收益最大的结果。完整 gap 历史为：

| 机制 | first same-CCD | repeat 1 | repeat 2 | repeat 3 | 最终选择 |
| --- | ---: | ---: | ---: | ---: | --- |
| cold assertion | `0.090697 pp` | — | — | — | first |
| inline helpers | `0.029421 pp` | — | — | — | first |
| constant MemoryRead | `0.326391 pp` | `0.070149 pp` | — | — | repeat 1 |
| shift/index | `0.424026 pp` | `0.341871 pp` | `0.262010 pp` | `0.091610 pp` | repeat 3 |
| residual MemoryRead | `0.473481 pp` | `0.160553 pp` | — | — | repeat 1 |
| physical zero-tail | `0.150148 pp` | — | — | — | first |

其中 shift/index 的两个未达标 repeat pooled walltime 分别为
`51,830.25→51,624.50 ms`（`+205.75 ms/+0.396969%`，gap `0.341871 pp`）和
`51,779.50→51,577.00 ms`（`+202.50 ms/+0.391081%`，gap `0.262010 pp`）；它们保留用于
审计，但不替代首个达标的 repeat 3。constant 与 residual 的 first same-CCD 结果分别为
`51,849.00→51,472.50 ms`（`+376.50 ms/+0.726147%`，gap `0.326391 pp`）和
`51,427.50→51,424.25 ms`（`+3.25 ms/+0.006320%`，gap `0.473481 pp`），同样不入选。

## 4. 正式样本与 placement

| 机制 | control samples / ms | final samples / ms | 正式 placement |
| --- | --- | --- | --- |
| cold assertion | `52335,52435,52431,52260` | `51672,51707,51799,51597` | node0 CCD `72-79,264-271`，CPU `72/264` |
| inline helpers | `52041,52066,51974,52050` | `51650,51698,51612,51623` | node0 CCD `8-15,200-207`，CPU `8/200` |
| constant MemoryRead | `51857,52066,51937,51999` | `51571,51629,51621,51519` | node0 CCD `64-71,256-263`，CPU `64/256` |
| shift/index | `51745,51785,51818,51766` | `51588,51738,51621,51664` | node0 CCD `32-39,224-231`，CPU `32/224` |
| residual MemoryRead | `51715,51741,51659,51745` | `51727,51765,51808,51798` | node0 CCD `24-31,216-223`，CPU `24/216` |
| physical zero-tail | `51311,51293,51339,51247` | `51388,51393,51495,51422` | node1 CCD `144-151,336-343`，CPU `144/336` |

control/final spread 依次为：cold `175/202 ms`、inline `92/86 ms`、constant `209/110 ms`、
shift/index `73/150 ms`、residual `86/81 ms`、physical zero-tail `92/107 ms`。绝对 walltime
不能跨 CCD 直接比较，因此只在每一行内部用同一 CCD 的 direct pair 求边际收益。

## 5. 48 个正式样本的质量审计

六组共 `48` 个 accepted sample，逐个审计结果为：

- 每组 `4` 个 control 与 `4` 个 final，artifact/log 路径各不相同；
- ABBA 与 BAAB 的 `same_ccd_cpu_across_orders=true`，每组只有一个 expected CPU；
- `setarch x86_64 -R` 生效，全部 process personality 为 `00040000`；
- process affinity、resolved executable、whole-CCD pre-gate 和 continuous monitor gate 全部通过；
- CPU migrations 总数为 `0`；task-clock 与全部 PMU event 的最小 scheduled ratio 均为 `100.0%`；
- binary 与 NEMU NUMA local-page gate 全部通过；
- guest cycle、terminal PC、功能 signature 全部通过，每个 emu log 恰好一个 `Host time spent`，且与
  result JSON 的 walltime 一致。

共享机器上同时存在其他用户的 gem5/QEMU 工作负载，造成多次 quiet-window 或运行中污染重试；这些
attempt 没有混入 accepted sample。尤其是 BAAB 污染时，已经完成的 ABBA 也被整轮丢弃。

## 6. PMU 解释

下表是正式四个 final sample 相对四个对应 control sample 的均值变化；负值表示 final 更少：

| 机制 | cycles | instructions | frontend no-ops | frontend-starved | backend stalls |
| --- | ---: | ---: | ---: | ---: | ---: |
| cold assertion | `−1.285279%` | `−0.001323%` | `−1.702190%` | `−2.272568%` | `−0.367805%` |
| inline helpers | `−0.736962%` | `−1.785971%` | `−0.750074%` | `−0.593301%` | `+0.768205%` |
| constant MemoryRead | `−0.732447%` | `−0.543772%` | `−0.687054%` | `−0.640723%` | `−0.944993%` |
| shift/index | `−0.235918%` | `+0.001375%` | `−0.472384%` | `−0.562498%` | `+1.651277%` |
| residual MemoryRead | `+0.116342%` | `−0.000124%` | `+0.039121%` | `+0.086927%` | `+1.378905%` |
| physical zero-tail | `+0.190619%` | `−0.000879%` | `+0.223689%` | `+0.278330%` | `+0.228467%` |

cold assertion 几乎不改变动态 instructions，却显著降低 cycles 与前端空泡，符合冷分支布局/预测提示
改善前端行为的预期；它也是唯一越过 `1%` 可信线的机制。inline helpers 主要减少动态 instructions，
constant MemoryRead 同时减少 instructions、cycles 和两类 stall，二者与约 `0.74%/0.73%` 的稳定弱
walltime 收益一致。shift/index 的前端改善被 backend stalls 增长部分抵消，只留下约 `0.24%`。
residual MemoryRead 与 physical zero-tail 的 cycles/stalls 上升则与 walltime 回退方向一致。

PMU 只用于解释，默认/保留判断仍以端到端 50k walltime 为准。

## 7. 归因与后续保留边界

这六个数是完整 final 上各机制的 leave-one-out 边际，不是相互独立的加数。它们不能直接相加来重构
搜索内 final 相对 RWA 的历史 `4.195920%`，也不能把不同 CCD 的绝对均值横向相减。机制之间，尤其
constant 与 residual MemoryRead emitter 改写之间，可能存在交互。

基于本轮 direct walltime：

1. cold assertion/SystemTask 是明确的 landing/default 候选；
2. inline helpers、constant MemoryRead 与 shift/index 均有双 order、低 gap 的弱正向证据，但在落地前
   仍应以组合 endpoint 做 fresh 功能与 walltime 回归；
3. residual MemoryRead OOB hints 与 physical zero-tail 在 final 上都造成稳定回退，不应保留或默认开启；
4. 若后续构造实用子集，优先直接测试相当于保留到 gen29、排除 gen68/gen150 两段的组合，而不是把
   两个负 marginal 百分比机械相加。

本阶段没有修改 Wolvrix 默认源码，也没有启动新的 auto research。

## 8. 结果身份与 SHA-256

核心 artifact 路径和 SHA-256：

| artifact | SHA-256 |
| --- | --- |
| `candidates_loo_v3/materialization_report.json` | `8341429dbe85eea17a4b0887574104428945bf384733b75ecf73bdebd6dd76bb` |
| `arms_loo_v4/parallel_build_summary.json` | `0f08ace67b5322b180801ad4caeb22fe4049645993a181bf9735e743ffbf08f3` |
| `run_pair_sameccd.py` | `6539112dac5b8b9276471afd7e0a474b71327559ac06929586858abe851f71f0` |
| `repeat_until_order_gap.py` | `d78fbbbb148ebe3e71d5f46c4da19b640f3b2085c6e75dd6f0698db4a3664e74` |
| `direct_sameccd_v1/summary.json` | `1ea9f7be68bd37ef872774f7f728b31c4583cb5907ba268c00fb1a6cea57b5a6` |
| `direct_sameccd_gap_lt_0p25_v1/summary.json` | `751645393ffc8f5229d261d6f8f80894b4079623ccfbc90392ebad00701e26db` |

正式 result JSON 的 SHA-256：

| 机制 | result SHA-256 |
| --- | --- |
| cold assertion | `f26f22ded9f01ce2f3b4c6e55640647cada576d0446dcfca8b9b6db12707f710` |
| inline helpers | `c8ab5ad9d9ced4351973cf0c3ef5405b33460e649b1f84472f3b07d715df7144` |
| constant MemoryRead | `6c07a4ab6b71a618c8e46d3cb5963b1a20fa36c758d470d8a7b53eb89253fac3` |
| shift/index | `97894c71d249c534714f599a9e525277bafc33ed99a926f28932111421d17fc1` |
| residual MemoryRead | `6d47ac5c55b2d6507ddf2415fb517159f1d40769ab91495bffbcf7e3734c008a` |
| physical zero-tail | `1805ceed9173e546541b03acdddeb91087d2b2bcb873a44a91cc57c13559a69d` |

上述路径均相对于
`build/grhsim_bestpath_ablation_20260731/`。所有未达标轮次、基础设施重试、原始 emu/perf/monitor/audit
日志也保留在同一结果树中。

## 9. SimpleTES continuation 状态

收尾审计时没有活动的 SimpleTES scheduler/generator/evaluator、ablation runner、emu、perf 或 build
进程；`/tmp/simpletes-grhsim-simtop-50k/02d8ec0c5cbeb4ef/slot-0/lock` 可非阻塞获取，说明 evaluator
slot 已释放。SimpleTES HEAD 为 `162d95543b32c68ee762f3fd9d6794f1b2cce8ac`，worktree 干净。

checkpoint 根目录仍保留历史 `launcher.pid=3369780`，但该 PID 已不存在，且仓库中没有 launcher 对该
文件的活跃锁检查；它不是 evaluator lock。消融工具、candidate、binary 和结果均位于 playground 的
ignored `build/` 树，没有改动 checkpoint 或 SimpleTES 源码。因此后续可以从既有 exact checkpoint
继续探索；本轮没有擅自启动新实例。

## 10. 增量复测勘误 2026-07-31：residual/physical 应改判中性

后续四项 gen29→六项 gen150 direct pair 得到六项数值快 `0.181305%`，与本文件第 1 节把 residual
MemoryRead 和 physical zero-tail 分别写成“双 order 稳定回退”不一致。为排除候选身份或构建变化，
复测直接复用本文件第 2 节的三份 immutable snapshot：`final_gen150`、
`minus_residual_memread`、`minus_physical_zero_tail`。三份 snapshot 的 11 项 `SHA256SUMS` 均重新验证
通过，parent/Wolvrix/build-config/toolchain/image/NEMU 与原实验完全相同；control 仍是 `final−X`，
candidate 仍是完整 final。

两项均重新取得同 CCD ABBA+BAAB 且 order gap `<0.25 pp` 的首轮正式结果：

| 机制 | 旧正式 control→final | 新正式 control→final | 新 ABBA | 新 BAAB | 新 gap |
| --- | ---: | ---: | ---: | ---: | ---: |
| residual MemoryRead | `51,715.00→51,774.50 ms`，`−59.50 ms/−0.115054%` | `51,656.25→51,644.25 ms`，`+12.00 ms/+0.023230%` | `−0.001936%` | `+0.048395%` | `0.050331 pp` |
| physical zero-tail | `51,297.50→51,424.50 ms`，`−127.00 ms/−0.247575%` | `51,733.75→51,759.25 ms`，`−25.50 ms/−0.049291%` | `+0.029012%` | `−0.127501%` | `0.156512 pp` |

residual 新旧正式轮次甚至使用同一个 node0 CCD `24-31,216-223` 和 CPU `24/216`；新结果相对旧结果
漂移 `+0.138284 pp`，且从双 order 负向变为跨零。physical 新结果使用 node0 CCD
`48-55,240-247`、CPU `49/241`，相对旧结果漂移 `+0.198285 pp`，同样从双 order 负向变为跨零。
因此不能把差异归因于 patch、binary 或 residual 的 CCD 类型变化；更直接的解释是这些约
`0.02%..0.25%` 的观测本来就在亚百分比 runtime 噪声区间。

新 residual 样本为 control `51687,51621,51769,51548 ms`、final
`51659,51651,51607,51660 ms`；新 physical 样本为 control `51756,51650,51751,51778 ms`、final
`51736,51640,51782,51879 ms`。两组共 16 个 sample 的 fixed-ASLR、同 CCD/CPU、affinity、0
migration、pre/monitor quiet gate、NUMA local-page、PMU scheduling 与功能审计全部通过。

新 PMU 也只显示中性量级变化：

| 机制 | cycles | instructions | frontend no-ops | frontend-starved | backend stalls |
| --- | ---: | ---: | ---: | ---: | ---: |
| residual MemoryRead | `+0.004453%` | `−0.000125%` | `−0.100054%` | `−0.065835%` | `+1.211270%` |
| physical zero-tail | `+0.040967%` | `−0.000880%` | `+0.028415%` | `+0.005281%` | `+0.183186%` |

据此勘误第 1、6、7 节的分类措辞：旧样本与数值继续保留，但“两个 order 都回退”“稳定回退”的概括
不再成立。residual MemoryRead 与 physical zero-tail 的可复现结论都应是 **中性、未证明端到端正
收益**。这仍不足以把两项保留或默认开启，因此四项 landing 子集不变；理由应从“已证明稳定回退”
修正为“复测跨零且所有观测都远低于 `1%` 可信线，没有默认开启证据”。

新增结果 SHA-256：

| artifact | SHA-256 |
| --- | --- |
| residual `round-1/result.json` | `daa053fc94af3e6aec0f8e54e5415bde4df13c672ee1d6c92a50e023da885e26` |
| residual `summary.json` | `13bbff97f472fee9e92078b0837f857a9deddb0401530f2d3af2138db5713256` |
| physical `round-1/result.json` | `ba63663c4dcffe9a9956c03833b3e367022a89f6c48b6e375f7380590281ef6b` |
| physical `summary.json` | `4657e0d0ccd6b39d837bbbc6fbd46f10f2eddfc1cea56cec148329c922eaa30c` |

artifact 位于 `build/grhsim_bestpath_ablation_20260731/rerun_residual_physical_v1/`。
