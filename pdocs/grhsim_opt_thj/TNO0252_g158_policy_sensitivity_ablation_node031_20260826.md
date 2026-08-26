# TNO0252: g158 排序策略敏感性消融（node031）

日期：2026-08-26

状态：`AUTO-RESEARCH STOPPED; STATIC REVIEW COMPLETE; THREE ARMS FRESH-BUILT/FUNCTION PASS; RUNTIME INVALIDATED BY HOST LOAD; NOT LANDED`。

本记录承接 [TNO0248](./TNO0248_simpletes_g158_node030_fresh_sameccd_retest_20260825.md) 的 g158 正式复测，并记录按用户要求停止 SimpleTES、在 node031 物化/并行构建候选以及尝试 runtime 消融的完整边界。它不修改 Wolvrix 生产代码、默认配置或 SimpleTES 研究基线。

## 1. 结论

静态审查确认 g158 的顶层行为只有一个：在 final schedule 已固定后，重新排列同一 `state_logic_storage_t` 的物理成员声明顺序。phase signature、引用需求分层和物理类型分组是该排序器的内部比较键，不是三个可独立启停的顶层优化。因此，本轮三臂实验应称为 **ranking-policy sensitivity**，不能把三臂的结果误报为三个独立优化的消融。

三路候选均从同一个冻结 control fresh build，且按用户提醒使用 `ProcessPoolExecutor(max_workers=3)` 并行编译；三路 focused/function gate 全部通过。但 node031 实际有大量外部 `gem5`、IDE/RemoteDev、Scala/Bloop 等任务，24 个 CCD 均未通过严格整 CCD quiet gate。只对第一臂完成了 3 轮、每轮 9 次的 runtime 尝试，共 27 次；没有任何 ABBA/BAAB walltime 样本，故本轮没有消融性能结论，也没有把无效运行当成零收益或负收益。

此前 g158 的唯一正式端到端结果仍以 TNO0248 为准：同 CCD SimTop 50k pooled walltime `43,223.00 ms -> 42,491.25 ms`，减少 `731.75 ms`、提升 `1.692964%`，order gap `0.084992 pp`。本记录不改变该结论。

## 2. 停止 SimpleTES

node030 上原有的 `typed_state_gpt56sol_max_fresh2_20260816_182232` 已按 `SIGINT` 优雅停止，没有发送 `TERM/KILL`，也未触碰其他任务。launcher、主引擎及其子进程全部退出；run log 记录 `Received SIGINT` 和 `Stopping 5 workers`，无 traceback。

最终 checkpoint 和计数：

~~~text
SimpleTES/checkpoints/grhsim_simtop_50k/typed_state_gpt56sol_max_fresh2_20260816_182232/2026-08-16/instance-5f0c84e9/db_state_174747

completed_evaluations = 151
valid                 = 108/128
generation_attempts   = 242
gen_failures          = 81
gen_cancellations     = 3
eval_failures         = 0
best_score            = 1.0478472639807577
best_node             = 621109d489774ae2b6361cc30c8dffdc
~~~

g158 的 `best_program.txt` SHA-256 仍为 `4419814848287a43d93fccb26ccd05cc0042b0985b2c0447a2098de413337416`。停止后没有启动新的 SimpleTES 实例。

## 3. g158 身份与静态归因

冻结候选位于：

~~~text
SimpleTES/checkpoints/grhsim_simtop_50k/typed_state_gpt56sol_max_fresh2_20260816_182232/2026-08-16/instance-5f0c84e9/db_state_030132/best_program.txt
~~~

~~~text
node:               621109d489774ae2b6361cc30c8dffdc
generation:         158
chain:              1
parent commit:      0dc48d4aa6dd508812d3226221e7c7a594ff3e7b
wolvrix commit:     79ec2037b00f2d4894d72785277ebe3f5d37782d
candidate mode:     default-path
enable options:     {}
candidate digest:   7715a2ea459f1d6da8c7e535525aa905e8714164e32e869498e3174cc968c01e
patch SHA-256:      cf29862adc2441aed4f72d446295fa5e60557872e7b2c59fa7641608371f72a5
program SHA-256:    4419814848287a43d93fccb26ccd05cc0042b0985b2c0447a2098de413337416
~~~

patch 只触及 `lib/emit/grhsim_cpp.cpp`。它对普通 persistent state 统计 direct/raw read（权重 1）和 write destination（权重 2），保留 compute supernode/commit batch 的 phase-tagged signature，再按非空 signature、2 的幂需求等级、精确需求、原图顺序以及 `wide/u64 -> u32 -> u16 -> bool/u8` 类型组发射字段。字段名、字段类型、`logicSlotIndex`、legacy `slotIndex`、materialized-value 顺序、schedule、guard、event 和 operation 均不变。

代码中没有 SimTop/CoreMark 名称匹配、信号名匹配、ValueId 特判或其他 workload-specific gate。

## 4. 物化的三组敏感性候选

三组候选均由冻结 g158 机械生成，基线 Wolvrix source SHA-256 为 `88f031189b1b240c2d1f567a60d2c001d9835318094a40abf080ff25002ee164`。它们分别移除某一类比较键，但保留同一物理成员重排机制：

| arm | 保留的排序信息 | 移除的排序信息 | patch SHA-256 |
| --- | --- | --- | --- |
| `g158_demand_only` | read/write demand、2 的幂分层、精确 demand、图顺序、物理类型组 | active phase/unit signature 排序 | `02efdb304647238190b377de45c64fa1e91bfc14455a61742ab6f510b340d293` |
| `g158_signature_only` | active phase/unit signature、物理类型组；仍区分 referenced/unreferenced | demand magnitude/class 排序 | `8dad7f3814b6a20a5a8221f61a01d5a55a3836be76aab72908ff4b77a9d14cfa` |
| `g158_full` | 冻结 g158 的全部比较键 | 无 | `cf29862adc2441aed4f72d446295fa5e60557872e7b2c59fa7641608371f72a5` |

物化输出和每个候选的完整 digest/file SHA 记录在：

~~~text
wolvrix-playground-gsim-calibrate-5/build/grhsim_g158_ablation_20260826/candidates_v2/materialization.json
~~~

`g158_full` 的物化 candidate digest 与搜索原始 digest 不同，是因为候选文档重新生成了 metadata；其语义 patch SHA 与冻结 patch 相同，不能据此认为代码变了。

## 5. node031 并行 fresh build

构建主机为 `node031.bosccluster.com`（384 logical CPUs、2 NUMA）。所有命令先 source `wolvrix-playground-gsim-calibrate-5/env.sh`；由于系统缺少匹配的 `clang-scan-deps-19`，仅在 `/tmp/tanghaojin-clang-tools-19` 解压 Ubuntu LLVM 19.1.1 工具并通过 PATH 使用，没有改系统安装。每个候选使用 `GRHSIM_BUILD_JOBS=4`，三路候选由三个独立 worker 并行 fresh build，共享 control 只构建一次。

共享构建身份：

~~~text
control generated fingerprint: ad0f384cb9090cd87be264e22779a932d134eff2c9fc7ce92e28900a235ead53
build config fingerprint:       920b5c7f1e32e61e7ad363145521736e9a10a68d0e0d112ce7b4406f00e820b3
toolchain fingerprint:          7669097de01707e2fab9a40ae7b308617c33dece545dcc5a6e0d38be217b98bc
coremark.bin SHA-256:           c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e
nemu.so SHA-256:                094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e
control emu SHA-256:            efe03172ae2468dce092c788683309bd4ec54d44656f3afcc0d530b542ed0ebf
control emu size:               83,705,920 B
~~~

三路产物均完成 `29/29` focused tests、100-cycle 及 10k-cycle 功能门禁；10k 结果为 `instrCnt=458`、`cycleCnt=9996`、`Guest cycle spent=10001`。绝对构建结果如下：

| arm | build elapsed | generated fingerprint | `emu` size | size vs control | `emu` SHA-256 |
| --- | ---: | --- | ---: | ---: | --- |
| `g158_demand_only` | `2126.103 s` | `27176d7ae1a2c07aeaff3722f70c4f3b90fa87feb4dac3f9fa0091ffae562` | `83,947,584 B` | `+241,664 B / +0.288706%` | `d6b5631cf295a37d77d620b45b0b43fbcba4f341dd0c596a3b5c22fc4e110220` |
| `g158_signature_only` | `2124.984 s` | `c272dbc507a05389c36fc72417faf8fa9b5b872f2de81fdc79a3fee129500d9a` | `83,484,736 B` | `-221,184 B / -0.264239%` | `d07682b6cc5acb3827c26935267713bf1b85cdfbe9d202014d0fc55de76a1056` |
| `g158_full` | `2176.656 s` | `747800786a14b5292c355f5fdfe6fb359f460676b54dd24fc618af6d062082a9` | `83,521,600 B` | `-184,320 B / -0.220199%` | `8241ef7523ebb0d1474c667b9158ee5ff48c3c843f5ab7948db129e28933b598` |

完整 summary：

~~~text
wolvrix-playground-gsim-calibrate-5/build/grhsim_g158_ablation_20260826/arms_v1/parallel_build_summary.json
~~~

所有候选与 control 使用相同 `coremark.bin`/`nemu.so`，构建失败数为 `0`，没有残留 build worker。

## 6. node031 runtime 尝试与无效原因

按 SimTop 50k walltime 的正式协议，计划对三组候选分别与同一 control 做 fixed-ASLR、同 CCD 的 ABBA+BAAB；选样需要整 CCD quiet/continuous-load gate。实际先启动 `g158_demand_only`，因为该臂已连续无法获得安静 CCD，未浪费另外两臂的仿真时间。

runner 使用 `run_single_pair_until_gap.py` 和 `run_pair_sameccd.py`，每轮最多 9 次尝试、threshold `0.25 pp`、最多 8 次 retry。前 3 轮共 27 次尝试，每次都在进入 workload 前被基础设施门禁拒绝：

~~~text
error: no dynamically discovered CCD passed the strict quiet-window gate
ccd_count: 24
gate: 3s whole-CCD count=16 mean>=98 min>=95 target+sibling>=98
samples: []
retryable_infra: true
~~~

独立 `mpstat -P ALL 1 3` 也观察到代表性 CCD 只有 `mean_idle=94.86375%`、`min_idle=86.3%`；其余多个 CCD 的 `min_idle` 为 `0`。node031 当时存在外部 `gem5.opt/gem5.fast`、JetBrains RemoteDev、Scala/Bloop 等进程，机器总负载约 `38..193`（384 logical CPUs），与“CCD 空闲”前提不符。

结果摘要：

~~~text
wolvrix-playground-gsim-calibrate-5/build/grhsim_g158_ablation_20260826/results_v1/g158_demand_only/summary.json
SHA-256: 7e40d6424e15670a2ec85782b410b0fd621f29e0713248a4b33bef163427582f
~~~

三个已完成轮次均为 `valid=false`、`retryable=true`、`returncode=1`；没有 control/candidate walltime、没有 ABBA/BAAB 结果。第 4 轮刚开始时，仅向该 runner 的精确 process group（PGID `1347803`）发送 `SIGINT`，未发送 `TERM/KILL`，未影响 node031 其他用户任务；SSH 会话因此返回预期的 `KeyboardInterrupt`，这不是候选或构建错误。最终没有 runner/子进程残留。

## 7. 决策与后续边界

- 本轮不能判定 phase signature、demand policy 或二者组合各自的 walltime 收益；三臂的 binary size 差异也不等于性能差异。
- 不放宽 quiet gate、不使用污染样本、不将 `N/A` 转换为 `0%`，也不改变 TNO0248 的正式 g158 结果。
- 不把这三个敏感性臂 landing 到 Wolvrix，也不改变默认选项或 SimpleTES baseline；本轮没有生产代码变更。
- `arms_v1` 中的 control 和三组候选是完整、可复用的 immutable artifacts。后续应在确实空闲的 node/CCD 上，对三臂各自完成同 CCD ABBA+BAAB，再按 `<0.25 pp` order-gap 规则选结果。
- 实验脚本和产物保存在 ignored 的 `build/grhsim_g158_ablation_20260826/` 下，未加入生产提交；它们不会阻塞后续 SimpleTES 探索。
