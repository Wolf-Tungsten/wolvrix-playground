# TNO0160 SimpleTES first formal search results and default decision

记录日期：2026-07-20

状态：正式 SimpleTES instance `91f6580e` 因达到 `16` 次 generation 上限而正常结束，
不是因达到 `8` 个 valid-candidate 上限或基础设施失败而停止。`11` 个生成成功的 proposal
中有 `2` 个完成全部 evaluator gate；最佳候选在 SimTop 50k ABBA+BAAB 合并口径上为
`74,237.50 -> 73,998.25 ms`，绝对改善 `239.25 ms`、相对改善 `0.322276478%`。
该信号低于 [TNO0110](./TNO0110_walltime_headline_criterion_and_re_evaluation_20260717.md)
规定的 `max(1%, control wall spread)` 可信线，且相同补丁的独立复测被 fresh-emit
fingerprint 假拒绝阻断。因此本轮只保留研究线索，不保留候选代码、不改变 C++ default，
也没有 wolvrix 子模块提交或父仓库 gitlink 更新。

前序 bench、正式 baseline 和 worker 启动分别见
[TNO0156](./TNO0156_simpletes_auto_research_bench_and_launch_gate_20260720.md) 与
[TNO0159](./TNO0159_simpletes_current_default_baseline_and_worker_launch_20260720.md)。本文中的
walltime 差值统一定义为 `control - candidate`，所以正值表示 candidate 更快；PMU/ELF
相对差值统一定义为 `(candidate / control - 1) * 100%`。

## 1. Instance identity, budget, and stop reason

```text
instance                    91f6580e
checkpoint                  SimpleTES/checkpoints/grhsim_simtop_50k/formal_20260720_01
latest checkpoint           db_state_161238
model / reasoning           gpt-5.6-sol / ultra
selector / chains           rpucg / 4
gen / eval workers          1 / 1
pinned parent               b90d20461d276def682f19a28be1fe65a4387eef
pinned wolvrix              f17e90e14c3ad70a3ee93f7c6540e13dae54940a
maximum generations         16
maximum valid candidates    8
formal stop                 2026-07-20 16:12:38 +08:00
stop reason                 Max generations reached
```

最终预算账本为：

| item | absolute count | 说明 |
| --- | ---: | --- |
| generation slots consumed | `16/16` | 达到硬上限后正常停止。 |
| parseable proposals entering evaluator | `11` | 加上 initial control，最终 checkpoint 有 `12` 个 finished nodes。 |
| generation failures | `5` | `4` 次 `3000 s` Codex CLI timeout；`1` 次 Codex exec/context-window failure。 |
| valid candidates | `2/8` | 两个均完成 ABBA screen 和 BAAB promotion。 |
| default-off fingerprint errors | `9` | 均在 disabled/default-off generated-fingerprint gate 返回 `CandidateError`；其中至少一例已确认是基础设施假拒绝。 |
| generation cancellations | `0` | final banner 原值。 |
| evaluator worker rejects | `0` | final banner 原值；上述 `9` 个 CandidateError 作为已完成的 `-inf` node 记录，不是 eval worker crash。 |

proposal 主要覆盖三类方向：`targeted-table-contiguous` active-mask packed table 的 outlining
与小 bucket 重内联、`final_fanin_pullback_policy=strict` 的稳定排序/规模阈值，以及
`active_mask_gap_pack_policy=targeted-direct` 的 cache-line 对齐。`11` 个 proposal 中
`8` 个属于 active-mask family，`3` 个属于 final-fanin family。最终 best score
`1.003233184568554` 只是框架的 `control_mean/candidate_mean` 排序值，不等价于通过本文的
walltime 可信采用线。

## 2. Accepted current-default baseline

initial control 的 A/B 两个角色实际指向同一 current-default ELF 和同一 generated
fingerprint `57819a3d9f1165af...`，其四个有效 ABBA 原值为：

| index | role | absolute `Host time spent` |
| --- | --- | ---: |
| 1 | control A1 | `74,900 ms` |
| 2 | control-alias B1 | `74,933 ms` |
| 3 | control-alias B2 | `74,956 ms` |
| 4 | control A2 | `74,441 ms` |

```text
all-four mean             74,807.5 ms
all-four spread           515 ms = 0.688433646%
A mean                    74,670.5 ms
B mean                    74,944.5 ms
same-ELF B-A              +274.0 ms = +0.366945447%
control emu ELF bytes     93,671,768
control emu SHA256        b8f680b2377979083fe4992e86ca7fe9731a35d6369c59236c15abe4423303e6
```

这里的 `274 ms / 0.366945447%` 是相同 ELF 仅因角色/时间顺序产生的表观差异，不能解释为
性能变化。后续两个候选均只与各自同组的 fresh current-default 比较；不同组之间约
`73.8..74.2 s` 的 control 漂移不参与 candidate 评分。

## 3. Two candidates that completed all gates

两个有效候选都只修改 `wolvrix/lib/emit/grhsim_cpp.cpp`，并只在显式
`active_mask_gap_pack_policy=targeted-table-contiguous` 下启用。两者的 disabled build
保持 current-default fingerprint，unpatched same-options attribution 与 enabled fingerprint
不同；disabled/enabled focused tests 均分别为 `24/24 PASS`，100/10k 功能门禁均通过。

### 3.1 Candidate `9c49c9716a897d8c`: full typed outlining above 32 chunks

该候选保留既有合法 8/4/2/1-byte packed chunk 表示，但对 chunk 数严格大于 `32` 的 plan
按宽度生成 constexpr table，并由共享 noinline typed loop 执行。绝对覆盖为 `291/586`
groups、`65,205` entries、`14,744/19,942` chunks 和 `935` 个非空 width buckets；其余
`295` groups、`5,198` chunks 仍保持直线 lowering。enabled generated fingerprint 为
`1ca569df0e2f6909...`。

### 3.2 Candidate `842fb6de071cbe88`: inline one-to-three-chunk buckets

该候选在前者基础上，将每个 width bucket 中只有 `1..3` 个 chunk 的情况重新内联。
这样的 bucket 共 `541` 个、`815` chunks；最终保留 `394` 个 helper calls 和 `13,929`
outlined chunks，即仍 outline 原集合的 `94.47%`，同时去掉短 loop/call 开销。enabled
generated fingerprint 为 `74d82ab895b3d9f5...`。

所有 candidate runtime 样本都到达唯一正确终点：

```text
guest/cycleCnt/instrCnt/PC = 50001/49996/73580/0x80001312
```

两个候选合计 `16` 个正式 50k 样本均通过 fixed-ASLR personality `00040000`、空闲 CCD
pre-gate/runtime monitor、固定 CPU、NUMA-local first-touch、五事件 PMU 100% scheduling、
zero migration、唯一正 walltime 和功能 signature。加上 initial control，本 instance 共留下
`20` 个 accepted 50k 样本。

## 4. Absolute SimTop 50k walltime

下表中的 raw order 直接按运行顺序记录，`C` 为 current-default control，`K` 为 candidate。
spread 是同一 role 在该行内的 `max-min`。

### 4.1 Candidate `9c49c9716a897d8c`

| group | raw order and absolute walltime | control mean | candidate mean | delta | improvement | control spread | candidate spread |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ABBA, CPU48 | `C 73,985 / K 73,870 / K 73,834 / C 73,861 ms` | `73,923.0 ms` | `73,852.0 ms` | `+71.0 ms` | `+0.096045886%` | `124 ms / 0.167742110%` | `36 ms / 0.048746141%` |
| BAAB, CPU24 | `K 73,892 / C 73,830 / C 73,840 / K 73,760 ms` | `73,835.0 ms` | `73,826.0 ms` | `+9.0 ms` | `+0.012189341%` | `10 ms / 0.013543712%` | `132 ms / 0.178798797%` |
| combined | four control and four candidate samples | `73,879.0 ms` | `73,839.0 ms` | `+40.0 ms` | `+0.054142584%` | `155 ms / 0.209802515%` | `132 ms / 0.178767318%` |

ABBA 和 BAAB 均为正向，但 BAAB 仅改善 `9 ms`；combined 信号远低于 `1%`。

### 4.2 Candidate `842fb6de071cbe88`

| group | raw order and absolute walltime | control mean | candidate mean | delta | improvement | control spread | candidate spread |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ABBA, CPU73 | `C 74,341 / K 74,024 / K 74,010 / C 74,270 ms` | `74,305.5 ms` | `74,017.0 ms` | `+288.5 ms` | `+0.388261973%` | `71 ms / 0.095551473%` | `14 ms / 0.018914574%` |
| BAAB, CPU40 | `K 73,798 / C 73,895 / C 74,444 / K 74,161 ms` | `74,169.5 ms` | `73,979.5 ms` | `+190.0 ms` | `+0.256169989%` | `549 ms / 0.740196442%` | `363 ms / 0.490676471%` |
| combined | four control and four candidate samples | `74,237.50 ms` | `73,998.25 ms` | `+239.25 ms` | `+0.322276478%` | `549 ms / 0.739518437%` | `363 ms / 0.490552141%` |

最佳候选的两个 order 均正向，方向一致性比单次正向更有价值；但 combined `239.25 ms`
仍小于 initial same-ELF 的 `274.0 ms` 角色差异，且低于本候选 combined control spread
`549 ms`。因此该结果只能作为弱正信号，不能作为默认采用证据。

## 5. PMU and ELF diagnosis

以下 PMU 是每个候选 ABBA+BAAB 中四个 control 与四个 candidate 样本各自的算术均值；
负相对差表示 candidate 减少该事件。PMU 只解释 walltime，不独立裁决。

| candidate | event | control absolute mean | candidate absolute mean | absolute delta | relative delta |
| --- | --- | ---: | ---: | ---: | ---: |
| `9c49c971` | instructions | `164,220,587,119.25` | `162,234,679,157.50` | `-1,985,907,961.75` | `-1.209293%` |
| `9c49c971` | cycles | `270,412,677,111.00` | `270,254,922,762.25` | `-157,754,348.75` | `-0.058338%` |
| `9c49c971` | backend stalls | `89,532,008,220.75` | `89,056,757,014.25` | `-475,251,206.50` | `-0.530817%` |
| `9c49c971` | frontend empty | `1,236,597,236,360.00` | `1,237,826,566,204.50` | `+1,229,329,844.50` | `+0.099412%` |
| `9c49c971` | frontend `cmask>=6` | `160,036,738,932.00` | `160,239,735,434.25` | `+202,996,502.25` | `+0.126844%` |
| `842fb6de` | instructions | `164,220,588,111.00` | `162,191,396,608.75` | `-2,029,191,502.25` | `-1.235650%` |
| `842fb6de` | cycles | `271,514,631,581.75` | `270,591,305,052.50` | `-923,326,529.25` | `-0.340065%` |
| `842fb6de` | backend stalls | `90,526,915,152.50` | `88,887,467,213.50` | `-1,639,447,939.00` | `-1.811006%` |
| `842fb6de` | frontend empty | `1,242,025,061,522.25` | `1,239,866,234,236.50` | `-2,158,827,285.75` | `-0.173815%` |
| `842fb6de` | frontend `cmask>=6` | `160,941,729,137.00` | `160,671,583,595.75` | `-270,145,541.25` | `-0.167853%` |

最佳候选的五项 PMU 全部同向下降，支持“小 bucket 重内联保留 instruction 收益并减轻
frontend/backend cancellation”的机制解释；但 walltime 只有 `0.322276478%`，不能用 PMU
替代最终可信线。

staged emu ELF 的绝对大小与 SHA 为：

| build | ELF bytes | delta vs control | relative size | SHA256 |
| --- | ---: | ---: | ---: | --- |
| current-default control | `93,671,768` | `0` | `0%` | `b8f680b2377979083fe4992e86ca7fe9731a35d6369c59236c15abe4423303e6` |
| `9c49c971` | `93,769,640` | `+97,872` | `+0.104483989%` | `84186868ceee0b719485677e981071a19e4fea49c3874d410d7c5aedb0ad7518` |
| `842fb6de` | `93,706,176` | `+34,408` | `+0.036732519%` | `5f852cc0c9d7d0b8dcb16a77bc01064df2c3db9c474c5b00c878b2e3f9cb6652` |

相较 full outlining，最佳候选将 ELF 增量从 `97,872` bytes 降到 `34,408` bytes，但仍未
小于 current-default ELF。

## 6. Confirmed default-off fingerprint false rejection

generation `15` 的 node `ff88e91f29bf4b79ad1160bcbf9f4976` 再次提出了最佳候选。
它与 generation `9` 的有效 best node 在以下两项上逐字节相同：

```text
patch bytes                 7,584
patch SHA256                1961bd2872fb06afb1c5f0cf636f351cb58e56d2f41fa3d355fbb399ae233b8f
enable option               active_mask_gap_pack_policy=targeted-table-contiguous
```

两次 hypothesis/evidence 不同，所以 whole-candidate digest 不同；最后一次对应 artifact
前缀为 `0a4de21cc0d2`。它完成 unpatched-same-options emit、disabled build、disabled
`24/24` focused tests 和 100/10k 功能门禁后，却返回：

```text
CandidateError: candidate changes generated C++ while enable_options are absent;
optimization is not default-off
```

这次拒绝已确认是假拒绝，而不是补丁绕过显式 option：disabled control 与 candidate 生成物
中新增的 `grhsim_or_active_chunks_*` helper 命中数都为 `0`。根因是 candidate clone 在
unpatched-same-options 阶段独立重跑了 XiangShan `sim-verilog`，没有复用 cached control 的
generated RTL。control 与 candidate 两轮 elaboration 的 `Bpu.sv/Ftq.sv/Ifu.sv/`
`LogPerfEndpoint.sv/PreDecode.sv` 出现等价枚举/拼接顺序漂移；未被本 bench 后续读取的
`SimTop.fir` 也不同。五个实际 HDL 输入的漂移继续传播为 `17` 个 schedule CPP 变化，索引为
`15,19,22,26..31,35..39,42,64,95`；典型差异是临时 value ID
`grhsim_v721535_0 -> grhsim_v721536_0`，以及等价 boolean operand 的排列变化。也就是说，
当前 gate 错误地比较了两套不同 elaboration 输入上的 generated C++；byte-exact default-off
原则本身仍应保留。

由于这一假拒绝发生在 run 的最后一个 evaluator node，最佳补丁没有获得第二组独立
ABBA+BAAB。其它 `8` 个同类 fingerprint CandidateError 不能仅凭错误字符串判断为真实
default-on 违规或假拒绝；在修复/归一化 fresh fingerprint gate 前，不应把 `9` 个拒绝全部
解释为候选本身无效。

## 7. Trust-line and repository decision

[TNO0110](./TNO0110_walltime_headline_criterion_and_re_evaluation_20260717.md) 要求候选信号与
`max(1%, control wall spread)` 比较：

| candidate | combined wall improvement | control spread | required trust line | decision |
| --- | ---: | ---: | ---: | --- |
| `9c49c971` | `0.054142584%` | `0.209802515%` | `1%` | 低于可信线，不采用。 |
| `842fb6de` | `0.322276478%` | `0.739518437%` | `1%` | 低于可信线，且缺独立重复，不采用。 |

因此本轮的准确结论是：typed outlining 加小 bucket 重内联得到方向一致、PMU 支持的
`0.322276478%` 弱正信号，值得在修复 fingerprint gate 后原样复测，但尚未取得可信的
端到端性能提升。当前 repository 决定为：

- 用户 checkout 中 `wolvrix` 继续保持 `f17e90e`，current-default 生成配置和 C++ defaults
  均不变；
- 不把 `best_program.txt` 的 patch 应用到用户工作树，不保留或默认开启候选；
- 没有 wolvrix code commit，没有父仓库 submodule pointer/gitlink 更新；
- 后续 auto research 必须先把 cached control 的 generated RTL/difftest 输入作为私有、
  byte-exact snapshot 提供给 candidate，再执行现有 strict fingerprint gate；best patch 的
  独立复测视为新阶段，不覆盖本文结论。

## 8. Artifact ledger

checkpoint 内的 durable run ledger（相对 workspace root）为：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/formal_20260720_01/2026-07-20/instance-91f6580e/run.log
SimpleTES/checkpoints/grhsim_simtop_50k/formal_20260720_01/2026-07-20/instance-91f6580e/db_state_161238/nodes.json
SimpleTES/checkpoints/grhsim_simtop_50k/formal_20260720_01/2026-07-20/instance-91f6580e/db_state_161238/scores_000012.csv
SimpleTES/checkpoints/grhsim_simtop_50k/formal_20260720_01/2026-07-20/instance-91f6580e/db_state_161238/best_program.txt
```

evaluator manifest、逐样本 audit/emu/perf/monitor 和最后一次假拒绝日志位于临时 slot；这些
路径用于本机追溯，不作为永久仓库链接：

```text
/tmp/simpletes-grhsim-simtop-50k/240719f63589edae/slot-0/results/evaluation_9c49c9716a897d8c.json
/tmp/simpletes-grhsim-simtop-50k/240719f63589edae/slot-0/results/runtime_result_9c49c9716a897d8c.json
/tmp/simpletes-grhsim-simtop-50k/240719f63589edae/slot-0/results/runtime_9c49c9716a897d8c/
/tmp/simpletes-grhsim-simtop-50k/240719f63589edae/slot-0/results/evaluation_842fb6de071cbe88.json
/tmp/simpletes-grhsim-simtop-50k/240719f63589edae/slot-0/results/runtime_result_842fb6de071cbe88.json
/tmp/simpletes-grhsim-simtop-50k/240719f63589edae/slot-0/results/runtime_842fb6de071cbe88/
/tmp/simpletes-grhsim-simtop-50k/240719f63589edae/slot-0/results/candidate_0a4de21cc0d2_unpatched_options_emit.log
/tmp/simpletes-grhsim-simtop-50k/240719f63589edae/slot-0/results/candidate_0a4de21cc0d2_disabled_build.log
```
