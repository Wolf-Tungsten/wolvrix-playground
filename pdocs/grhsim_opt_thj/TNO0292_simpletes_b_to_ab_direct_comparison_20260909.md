# SimpleTES B to AB direct comparison

## 实验定义与执行前记录

用户要求直接复测 B/AB，以判断 A 在 B 已启用时是否仍有端到端收益。
机制定义沿用 [TNO0290](./TNO0290_simpletes_gen38_bestpath_factorial_ablation_20260909.md)：
B 是 selected hot input dispatch branch weighting，A 是 structurally hot
input-seed active-mask chunk packing。本轮 control 为 B，candidate 为 AB，
两者的差异只有 A；不再以不同批次 B0→B 与 B0→AB 的百分比相减推算边际收益。

复用 `build/grhsim_bestpath_ablation_20260909/arms_build_v1/B/` 和 `AB/`
下的不可变构建快照，运行前核验各自 `SHA256SUMS`、同源生成输入、工具链和构建配置。
所有命令先 source 仓库 `env.sh`。在 node029..node032 中选择有空闲 CCD 的节点，
使用既有 same-CCD driver 和当前 runtime：B/AB 分别作为 control/candidate，
按 ABBA+BAAB 完成八个 SimTop 50k / NEMU Difftest 样本。
顺序中的 A/B 是测量角色，不是优化机制标签。

两种顺序固定同一 CPU/CCD/NUMA placement，关闭 ASLR；每个样本使用绑定该
CPU/NUMA 的独立 inode staging，执行 quiet pre-gate、continuous monitor、
affinity、NUMA、PMU 和功能门禁。另离线重放当前 evaluator 的全部八项稳定性门禁，
核对原始 emu log 的 `Host time spent`。order gap 必须 `<0.25 pp`；不合格组保留原始
证据并复测，其他稳定性门禁也不放宽。选择第一组全部合格的结果，不按收益大小择优。

本记录建立时尚未产生本轮测量数据。后续结果、绝对 walltime、相对变化、
复测原因及最终建议在本文追加。本任务不修改生产源码、默认选项或搜索状态。

## 增量更新：构建身份与启动

本轮选择 node032；启动前短扫 19/24 CCD 通过现有空闲门槛。
两份快照逐文件 SHA256 校验通过，生成输入、工具链、构建配置均相同：

| 身份 | 值 |
| --- | --- |
| parent pin | `6e2436e37286264e9f03f114d14d81bae4ed313b` |
| Wolvrix pin | `054c6a7c09b007a12eb36fdb49fcb659a1bfc590` |
| generation input | `0c63c3180527dd97382c69781d0042637758dfed5ed4c601cd6195fa07379545` |
| toolchain | `3139fef644317380a048f6d32551a70f2e960fe73558188951636856f4617038` |
| build config | `920b5c7f1e32e61e7ad363145521736e9a10a68d0e0d112ce7b4406f00e820b3` |
| B emu SHA-256 | `35c0136aa46d876149fcb7c850af75d3220193e0f1c5d240201553c17b11eec3` |
| AB emu SHA-256 | `e85fa0051cd0d79107499513ed02ebc838297274d247c1d6ead98a32709622b8` |
| runtime.py 执行前 SHA-256 | `78b3940db9b5ae3f3eff9b711f2a525564baf6b77317b214a82253c97f7a98cd` |
| evaluator.py 执行前 SHA-256 | `2259d4d3e1f5e4c88527d01d521afbd7ae89101eceeb62b99578b510a505dcec` |
| same-CCD driver 执行前 SHA-256 | `6539112dac5b8b9276471afd7e0a474b71327559ac06929586858abe851f71f0` |

首轮输出目录为实验根下的 `results_node032_v3/AB_vs_B_repeat1/`。
pair-attempt-1 在首个 sample 启动前被拒绝：选中 CCD `32-39,224-231`，
CPU32 的 sibling CPU224 idle 降到 `0%`，CCD mean idle `93.666875%`。
没有完成样本；driver 自动开始下一次完整 pair 尝试。

## 增量更新：首轮未通过完整稳定性门禁

`AB_vs_B_repeat1` 的 pair-attempt-2 在 node032 / NUMA0 / CPU24 /
CCD `24-31,216-223` 完成八个样本，底层 runtime 门禁通过。
但以下完整稳定性审计失败，本轮只保留为无效测量记录，不参与正式收益结论。

| 顺序 | B samples / ms | AB samples / ms | B 均值 / ms | AB 均值 / ms | AB 提升 |
| --- | --- | --- | ---: | ---: | ---: |
| ABBA | `39453,40185` | `39464,39663` | 39,819.00 | 39,563.50 | 0.641653% |
| BAAB | `40672,41296` | `40174,41699` | 40,984.00 | 40,936.50 | 0.115899% |
| pooled | — | — | 40,401.50 | 40,250.00 | 0.374986% |

pooled 少 `151.50 ms`，但 wall order gap `0.525755 pp` 超过 `0.25 pp`；
B/AB block shift 分别 `2.883556%/3.411180%`，均超过 `1%`；
B/AB sample spread 分别 `4.561712%/5.552795%`，均超过 `2%`。
其余三项稳定性门禁通过。八份原始 emu walltime、二进制角色 SHA、底层门禁均核对通过。
审计文件为本轮目录下 `stability_audit.json`，使用实验根目录的
`audit_b_ab_pair.py` 离线重放 evaluator；不修改原始 result/log。

- result SHA-256：`0a9377f1d5baa3e45e91704dc33016fb73f1c031f79ec96c901347813a14ca50`
- audit SHA-256：`a61100e440e5bf0bda6bdcd33eb067407ab0cab6107c796045d63b81e337aa0d`

按既定门槛启动 node032 第二轮 `AB_vs_B_repeat2`，重新选空闲 CCD，完整重跑两个顺序。

## 增量更新：第二轮仅 order gap 超限

`AB_vs_B_repeat2` 的 pair-attempt-1 再次选中 node032 / NUMA0 / CPU24 /
CCD `24-31,216-223`，完成全部八样本，底层门禁和八条原始 walltime 核对通过。

| 顺序 | B samples / ms | AB samples / ms | B 均值 / ms | AB 均值 / ms | AB 提升 |
| --- | --- | --- | ---: | ---: | ---: |
| ABBA | `40544,40373` | `40424,40486` | 40,458.50 | 40,455.00 | 0.008651% |
| BAAB | `40482,40356` | `40617,40425` | 40,419.00 | 40,521.00 | −0.252357% |
| pooled | — | — | 40,438.75 | 40,488.00 | −0.121789% |

AB pooled 慢 `49.25 ms`。完整稳定性门禁通过 7/8，只有 wall order gap
`0.261007 pp` 超过 `0.25 pp`，仍按预定规则拒绝，不四舍五入放宽门槛。
本轮 `stability_audit.json` 保留完整审计，随后启动第三轮 `AB_vs_B_repeat3`。

- result SHA-256：`a31ba081b40fac65ea0f4c467f7d948fd413ccc9ce88bc65e3ed0905c1ef538b`
- audit SHA-256：`51c4c224ce91a198358350f367c358699abb109b91bacbb4f5709dda63f89099`

## 增量更新：第三轮首次尝试遭遇外部污染

`AB_vs_B_repeat3` 的 pair-attempt-1 选择 node032 / CPU56 /
CCD `56-63,248-255`。前两个样本为 B `40,538 ms`、AB `40,482 ms`，
第三个 AB 样本为 `50,050 ms`，但运行中的 CCD 空闲门禁失败：非目标核
mean idle `65.780667%`、minimum `30.82%`、sibling idle `88.21%`。
本次尝试整体作废，不拼接其前两个样本到后续配对；driver 自动进入 pair-attempt-2。

## 增量更新：第三轮完整组仍未达 gap 要求，转 node031

pair-attempt-2 在 CPU40 / CCD `40-47,232-239` 再次被外部污染拒绝，
失败于第二个 AB 样本（`45,127 ms`）；非目标核 mean idle `69.394%`、
minimum `66.91%`、sibling `69.02%`，本次全部作废。
pair-attempt-3 改选 node032 / NUMA1 / CPU160 / CCD `160-167,352-359`，
完成八个合格底层样本：

| 顺序 | B samples / ms | AB samples / ms | B 均值 / ms | AB 均值 / ms | AB 提升 |
| --- | --- | --- | ---: | ---: | ---: |
| ABBA | `40898,40778` | `40948,40926` | 40,838.00 | 40,937.00 | −0.242421% |
| BAAB | `40888,40960` | `40868,40814` | 40,924.00 | 40,841.00 | 0.202815% |
| pooled | — | — | 40,881.00 | 40,889.00 | −0.019569% |

AB pooled 慢 `8.00 ms`。完整审计仍通过 7/8，仅 wall order gap
`0.445236 pp` 超限，两种顺序方向相反，因此仍不作正式结论。

- result SHA-256：`0dcf151066cad073af9701570327b4396b58e9ecbe85a79527935b02ccca3d1f`
- audit SHA-256：`d889d11fecb27cc354d811ad4660ef287e9470bc5deafc7bcef3c6595052b89b`

此时一次短扫显示 node031 load `8.56`、整机 idle `98.973%`、16/24 CCD
通过现有门槛；node032 仍有空闲 CCD，但本轮发生两次运行期污染。
第三轮结束后转 node031 启动 `results_node031_v3/AB_vs_B_repeat4`，
不并行叠跑配对，继续复用相同 B/AB 快照和门槛。

## 增量更新：node031 未形成完整组，缩小下次选核范围

node031 第四轮未形成完整配对：

| attempt | CPU | 拒绝原因 |
| --- | ---: | --- |
| 1 | 88 | 首个 control pre-gate minimum idle `94%<95%`，未启动 |
| 2 | 42 | 首个 control 运行期 CCD mean/min idle `93.866%/80.27%` 超限；原始 `40,525 ms` 不采纳 |
| 3 | 104 | 首个 control pre-gate mean idle `97.99375%`、target `97.99%`，均低于 `98%` |
| 4 | 89 | 首个 control pre-gate CCD 几乎全忙，mean idle `0.061875%` |
| 5 | — | 仅完成 B `40,528 ms`、AB `40,984 ms`；第三个样本中断，无完整 ABBA/BAAB |

调查发现 runtime 逐个扫描 24 个 CCD，每组 3 秒，最早的空闲观测可能已过约 69 秒。
后续 pre-gate 会拒绝变忙的 CCD，因此有效性检查没有失效，但等待和重试代价增加。
再次短扫 node032 的 NUMA1 CCD `96-103,288-295` 得 mean/min idle
`99.834%/99.33%`，helper 为 CPU0。决定终止 node031 这轮未完成的尝试，
保留所有 partial logs，并转 node032 新目录 `results_node032_v3/AB_vs_B_repeat5`。

对本轮确切 driver PID `3025344` 发送 SIGINT；Python 的 `finally` 清理运行子进程。
退出后独立两次核对 node031 的相关 driver/perf/emu 进程匹配数为 0；没有
`result.json`，不把 partial samples 拼入其他轮次。

第五轮只在原命令前添加 `taskset -c 0,96-103,288-295`，没有修改 runtime 源码。
runtime 按自身 affinity 过滤 topology，因此只枚举这一完整 16 逻辑核 CCD，
保留外部 helper CPU0，扫描约 3 秒即可完成。仍由 runtime 在该 CCD 内选取空闲
物理核，并原样执行 pre/continuous/ASLR/NUMA/PMU/功能门禁及八项稳定性判定。
限定选核范围不豁免门禁，CCD 变忙仍应作废重测。

## 增量更新：第五轮在第七样本污染后耗尽空闲尝试

第五轮 pair-attempt-1 在 CPU98 / sibling290 / NUMA1 /
CCD `96-103,288-295` 完成 ABBA，B samples `41165,40675 ms`，
AB samples `40674,40620 ms`，均值 `40,920.00→40,647.00 ms`，
表面提升 `0.667155%`。BAAB 前两个样本为 AB `40,787 ms`、B `40,706 ms`。
第三个 BAAB 样本（全组第七个，B `40,722 ms`）的持续监测 minimum idle
为 `92.85%<95%`，因此整组作废，包括此前底层合格的六个样本。

随后 attempt2..9 均无法在限定 CCD 上通过初始空闲门禁，本轮正常返回
`valid=false`、`same-CCD paired attempts exhausted after 9 attempts`。
没有合格的八样本结果；该半组提升不用于默认决定。保留本轮 `result.json`
及全部 attempt/log，重新调查可用节点和 CCD。

## 增量更新：node030 第六轮与前五次基础设施拒绝

短扫 node030 的 NUMA1 三组 CCD mean idle 为 `99.938%/99.730%/99.584%`，
minimum idle 为 `99.67%/98.33%/99.00%`。启动第六轮
`results_node030_v3/AB_vs_B_repeat6`，原命令前缀改为
`taskset -c 0,160-167,176-191,352-359,368-383`，即三个完整 CCD 和 helper CPU0。
选择扫描约 9 秒，所有门槛保持原值。

前五次尝试均因基础设施空闲门禁失败：

| attempt | CPU | 失败位置与证据 |
| --- | ---: | --- |
| 1 | 179 | 第二个 AB sample pre-gate mean/min idle `93.377%/0%`；仅 B `41,316 ms` 完成 |
| 2 | 160 | 第二个 AB sample 运行期 mean/min idle `97.202%/65.02%`；该 AB `41,061 ms` 不采纳 |
| 3 | 184 | 完成 ABBA 和 BAAB 前三条，最后 AB pre-gate sibling idle `97.32%<98%` |
| 4 | 181 | 首个 sample pre-gate mean/min idle `97.861%/76.41%` |
| 5 | 182 | 首个 sample pre-gate minimum idle `92.98%` |

attempt3 的原始顺序为 B `40971`、AB `40996`、AB `41186`、B `41301`、
AB `41230`、B `41470`、B `40890 ms`，缺少最后一条 AB，不能作为完整配对。
其 ABBA 均值 `41,136.00→41,091.00 ms`（少 `45 ms/0.109393%`）只作半组记录。
随后进入 attempt6，后续结果另行追加。

## 增量更新：第六轮同样耗尽基础设施重试

attempt6 在 node030 / CPU177 / NUMA1 / CCD `176-183,368-375` 完成
ABBA：B `40955,40656 ms`，AB `40890,40900 ms`，均值
`40,805.50→40,895.00 ms`，AB 慢 `89.50 ms/0.219333%`。
BAAB 首个 AB 为 `40,956 ms`，第二个 B 为 `43,019 ms`，但该 B 的持续
CCD mean/min idle 为 `93.093333%/53.62%`，整组作废。
attempt7..9 的候选 CCD 均未通过初始空闲门禁，本轮返回 `valid=false`。

- 第五轮 result SHA-256：`33aae3a6a10f23887c876c555d47a5b9797032901a8e4ab081777a547e1768ca`
- 第六轮 result SHA-256：`54326ab8e50f971f950b41c6b8088f9f19d6b4ef2889b978fd120c5db8b5e945`

此时所有性能进程均已结束；前三轮有完整组但 gap 超限，第四轮中断且不完整，
第五、六轮因基础设施重试耗尽均无完整合格组。继续进行四节点 30 秒连续空闲调查，
不把已经观察到的小差异提升为达标的性能结论。

## 阶段收尾：四节点均无可用 CCD，正式复测仍未完成

2026-09-09 `10:45:30–10:46:00` 对 node029..node032 并行执行 30 秒只读
all-CPU mpstat 调查。每个 CPU 均解析到 30 个一秒观测；四台的 24 个 CCD
全部未通过既有 average-row 空闲门禁，额外逐秒 minimum idle 检查也无通过者。

| 节点 | load（1 min） | 整机 mean idle | 通过既有门禁的 CCD |
| --- | ---: | ---: | ---: |
| node029 | 72.18 | 80.730% | 0/24 |
| node030 | 128.99 | 62.909% | 0/24 |
| node031 | 32.41 | 91.091% | 0/24 |
| node032 | 31.21 | 90.870% | 0/24 |

相对较稳的 node032 CCD `56-63,248-255` mean idle 也仅 `96.978%`，
最低 CPU 平均 idle `96.49%`，最差一秒 `71.72%`。该快照只说明当时资源状态，
不保证将来的可用性；也不能将短扫通过理解为后续整个八样本窗口必然空闲。

因此本阶段在外部负载阻断处收尾，所有性能与调查进程均已结束。
用户要求的 `order gap<0.25 pp` 正式 B→AB 比较尚未完成，不能宣布已完成有效复测。
已有三组完整测量如下，全部拒绝，不择取较接近门槛的一组当作达标结果：

| 轮次 | B / ms | AB / ms | B−AB / ms | AB 提升 | gap / pp | 不采用原因 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| node032 repeat1 | 40,401.50 | 40,250.00 | 151.50 | 0.374986% | 0.525755 | gap、block shift、sample spread 超限 |
| node032 repeat2 | 40,438.75 | 40,488.00 | −49.25 | −0.121789% | 0.261007 | 仅 gap 超限 |
| node032 repeat3 | 40,881.00 | 40,889.00 | −8.00 | −0.019569% | 0.445236 | 仅 gap 超限 |

repeat4 没有完整组，repeat5/6 的基础设施重试耗尽也没有完整组。
这些结果未提供 A 在 B 上稳定获益的证据，但尚不足以给出符合约定门槛的
边际收益数值，也不能据此声称 A 已被证明无效。上一阶段“优先保留 B”的建议
仍是暂定建议，本轮没有新增通过正式门禁的证据，没有修改生产默认或重启研究。

## 后续复现入口

在有空闲 CCD 的 node029..node032 节点，从 workspace 根运行以下命令；
每次使用新的 output 目录（下例 `AB_vs_B_repeat7` 在本阶段未执行）。
先短扫选择实际空闲的 CCD，必要时给 python 命令加 `taskset`，允许集合应包含
完整的 16 逻辑核 CCD 以及该 CCD 外的 helper CPU，不能只允许单个物理核。
helper 和目标 NUMA 的页放置仍由 runtime 管理，不手工改记录或阈值。

```bash
source wolvrix-playground-gsim-calibrate-5/env.sh
python3 -u wolvrix-playground-gsim-calibrate-5/build/grhsim_bestpath_ablation_20260731/run_pair_sameccd.py \
  --control wolvrix-playground-gsim-calibrate-5/build/grhsim_bestpath_ablation_20260909/arms_build_v1/B \
  --candidate wolvrix-playground-gsim-calibrate-5/build/grhsim_bestpath_ablation_20260909/arms_build_v1/AB \
  --output wolvrix-playground-gsim-calibrate-5/build/grhsim_bestpath_ablation_20260909/results_resume_v3/AB_vs_B_repeat7 \
  --env-sh wolvrix-playground-gsim-calibrate-5/env.sh \
  --runtime SimpleTES/datasets/grhsim/simtop_50k/runtime.py \
  --retries 8
python3 wolvrix-playground-gsim-calibrate-5/build/grhsim_bestpath_ablation_20260909/audit_b_ab_pair.py \
  --result wolvrix-playground-gsim-calibrate-5/build/grhsim_bestpath_ablation_20260909/results_resume_v3/AB_vs_B_repeat7/result.json \
  --output wolvrix-playground-gsim-calibrate-5/build/grhsim_bestpath_ablation_20260909/results_resume_v3/AB_vs_B_repeat7/stability_audit.json
```

仅对底层完整有效结果执行离线审计；基础设施失败/incomplete 不应调用该审计函数。
离线脚本复用 `audit_c_retest.py` 的原始 walltime/placement/底层门禁核对，并实际
调用当前 evaluator 的八项 stability gates；额外核对每个 staged binary SHA 与
B/AB 快照身份。脚本 SHA-256 为
`3a73d0b16f463d4e2aadaba9cc8ed91370e843302d33993b154816ca4e0bd75d`。
阶段末 runtime/evaluator SHA 与启动前记录相同。

## 勘误：样本序号表述

上述第三轮 attempt2 的“第二个 AB 样本”和第六轮 attempt1/2 的
“第二个 AB sample”，均指全组第 2 个样本（该组第 1 个 AB），
对应原始 JSON 的 `failed_sample_index=2`、`failed_sample_role=candidate`，
不是该组第 2 个 candidate。其失败原因、原始 walltime 和无效结论不变。
