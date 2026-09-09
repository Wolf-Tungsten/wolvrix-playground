# SimpleTES B native walltime regression

## 口径与产物

使用 [TNO0298](./TNO0298_simpletes_b_native_fresh_build_regression_20260909.md)
两份 fresh 普通 O3 产物，对比当前 pre-B `6a895c9` 默认 base 与原生 B。
两边使用相同 RTL、默认生成选项、工具链、构建配置、coremark 与 NEMU；
没有 PGO/BOLT。source、generated C++、ELF SHA 见该构建记录及冻结 manifest。

最终指标为 SimTop 50k `Host time spent` walltime，正收益定义为
`(base - base+B) / base`。每组执行完整 ABBA+BAAB 八次，两个顺序复用
同一 CPU/CCD/NUMA；顺序中的 A/B 表示 control/candidate。
每个样本都重新创建 inode 并在目标 CPU/NUMA 上 staging，关闭 ASLR，
检查即时及持续 CCD 空闲、进程 affinity/personality、NUMA 页面放置、
功能结果和 PMU。最后由冻结 evaluator 重算完整八项稳定性门禁，
order gap 必须小于 0.25 pp；旧 driver 的 `valid` 字段不能代替完整审计。

构建、性能和审计的共同根目录为：

```text
build/grhsim_b_landing_20260909/run_node032_v1/
```

使用 `build/grhsim_bestpath_ablation_20260731/run_pair_sameccd.py` 配对，
`build/grhsim_b_landing_20260909/audit_pair.py` 离线审计，runtime/evaluator
均取自本轮 `frozen/trusted_evaluator`。审计不改变任何测量数值或原始结果。

## 首组完整结果：稳定性不合格

15 秒真实拓扑调查中，node029/030/031/032 可选空闲 CCD 数分别为
0/6/0/12（排除 helper CPU0 所在 CCD），选择 node032。
首次即时 CCD 启动检查失败，没有 launch；随后 `pair1` 的 attempt 2
在 CPU145、SMT sibling337、NUMA1、CCD `144-151,336-343`、helper0
完成八次，两个顺序 placement 完全相同。

| 顺序 | base walltime | base+B walltime | 减少量 | walltime 降幅 |
| --- | ---: | ---: | ---: | ---: |
| ABBA | 43,332.50 ms | 41,226.00 ms | 2,106.50 ms | 4.861247% |
| BAAB | 43,487.50 ms | 41,720.50 ms | 1,767.00 ms | 4.063237% |
| pooled（不采用） | 43,410.00 ms | 41,473.25 ms | 1,936.75 ms | 4.461530% |

八次原始 walltime 按执行顺序为：
ABBA `43386 / 41283 / 41169 / 43279 ms`；
BAAB `41621 / 43581 / 43394 / 41820 ms`。
虽然底层运行门禁通过且两个顺序都为正收益，完整审计仍拒绝该组：

- wall order gap 为 0.798011 pp，超过 0.25 pp；
- B block shift 为 1.192335%，超过 1%，对应 B 均值 `41226.00→41720.50 ms`；
- cycles order gap 为 0.601431 pp，超过 0.5 pp。

原始结果保存在 `pair1/result.json`，完整审计为
`pair1/stability_audit.json`，SHA-256 为
`bcda65920aed4a589fa2f9a709040901279e33a2f2534b598dc61caa1663d273`。
该组不用于正式默认性能结论，没有删掉不利样本，也没有与后续组混合平均。

第二次调查 node030/032 可选空闲 CCD 数为 0/14；在 node032 新选择
`120-127,312-319`、`136-143,328-335`、`160-167,352-359` 三组完整候选 CCD
及 helper0，已开始 `pair2`，继续复用完全相同的两份二进制和原门禁。
后续完整结果在产生并审计后追加。

## 第二组完整结果：仅 order gap 未达标

`pair2` attempt 1 在 node032 CPU141、sibling333、NUMA1、CCD
`136-143,328-335`、helper0 完成八次。底层门禁全部通过，完整稳定性门禁
为 7/8；唯一失败项是 wall order gap=0.307381 pp，仍超过 0.25 pp。

| 顺序 | base walltime | base+B walltime | 减少量 | walltime 降幅 |
| --- | ---: | ---: | ---: | ---: |
| ABBA | 43,327.50 ms | 41,190.00 ms | 2,137.50 ms | 4.933356% |
| BAAB | 43,072.00 ms | 41,079.50 ms | 1,992.50 ms | 4.625975% |
| pooled（不采用） | 43,199.75 ms | 41,134.75 ms | 2,065.00 ms | 4.780120% |

原始 walltime：ABBA `43556 / 41170 / 41210 / 43099 ms`；
BAAB `41091 / 43077 / 43067 / 41068 ms`。没有删除首条偏高的 control 样本，
该组整体不采用。记录保存在 `pair2/result.json` 与
`pair2/stability_audit.json`，后者 SHA-256 为
`f74a354bab76cfc8b4ba55832ace79c2fc195b03430b6aba445769cbe8daed0f`。

已使用相同三组候选 CCD 和相同二进制启动 `pair3`，由原 runtime 重新执行
即时选核/空闲检查及完整八样本，不改变任何门槛。

## 第三组完整结果：order gap 仍不合格

`pair3` attempt 1 在单次运行前遇到外部负载门禁拒绝，attempt 2 随后在
node032 CPU120、sibling312、NUMA1、CCD `120-127,312-319`、helper0
完成完整八次；底层门禁通过，完整稳定性仍为 7/8，仅 wall order gap
0.531520 pp 未达标。

| 顺序 | base walltime | base+B walltime | 减少量 | walltime 降幅 |
| --- | ---: | ---: | ---: | ---: |
| ABBA | 43,053.50 ms | 40,800.50 ms | 2,253.00 ms | 5.233024% |
| BAAB | 43,124.50 ms | 41,097.00 ms | 2,027.50 ms | 4.701504% |
| pooled（不采用） | 43,089.00 ms | 40,948.75 ms | 2,140.25 ms | 4.967045% |

原始 walltime：ABBA `42925 / 40808 / 40793 / 43182 ms`；
BAAB `41177 / 43124 / 43125 / 41017 ms`。记录为 `pair3/result.json` 与
`pair3/stability_audit.json`，审计 SHA-256 为
`483573cce534b94b1296acb8e7a4954a411eea440cc090e4204d9ffa5a60e4f8`。
该组同样不作为正式结果。

再次 15 秒调查 node029/030/031/032，可选空闲 CCD 分别为 0/0/1/16。
继续选用 node032，在当前最空闲且此前三组未测的
`184-191,376-383` CCD 加 helper0 启动 `pair4`；原 runtime 仍负责实际
选核、空闲门禁和全组运行，没有降低门槛或重编译二进制。

## 前三组的只读测量复核

没有发现错用二进制、运行顺序、ASLR、NUMA 或 perf 解析错误。前三组的
24 个完整样本均使用正确身份和独立 inode；binary/nemu 本地页面比例均为
1，PMU 调度比例均为 100%，同组两个顺序 CPU/CCD/NUMA 相同。

`pair3` 的 `user cycles / task-clock` 频率代理出现顺序相关的偏移：

| 顺序 | base 频率代理 | base+B 频率代理 |
| --- | ---: | ---: |
| ABBA | 3.64948 GHz | 3.66443 GHz |
| BAAB | 3.66275 GHz | 3.65308 GHz |

该组 walltime 收益 ABBA→BAAB 从 5.233024% 变为 4.701504%，而 cycles
收益方向相反（4.8412%→4.9969%）。合并后的频率代理差只有 0.07145%，
会掩盖两个顺序内部的偏移；现有 wall-order 门禁仍正确拒绝了这一组。
这些是计数器推导的频率代理，不是温度、电源管理或某个硬件根因的证明。

`pair2` 则不同，其 wall/cycles order gap 分别为 0.307381/0.303262 pp，
主要表现为第一条 base walltime 偏高；`pair3` 的第一条 base 反而更快，
因此不能概括为“BAAB 必然变慢”。继续使用原协议和全部门禁，未增加
特殊 warm-up、修改调频策略或丢弃单条样本。

## 正式结果：第四组完整审计通过

`pair4` 的 attempt 1 在运行中遇到外部负载，attempt 2/3 被即时空闲门禁
拒绝；这些不完整尝试都整体舍弃。attempt 4 在 node032 CPU184、
sibling376、NUMA1、CCD `184-191,376-383`、helper0 完成 ABBA+BAAB。
两份二进制仍为 TNO0298 的同一快照；本组是第一个完整通过全部门禁的组，
作为正式结果，不与前三组或被中断的尝试混合。

| 顺序 | base walltime | base+B walltime | 减少量 | walltime 降幅 |
| --- | ---: | ---: | ---: | ---: |
| ABBA | 43,059.00 ms | 41,025.50 ms | 2,033.50 ms | 4.722590% |
| BAAB | 43,038.00 ms | 41,077.00 ms | 1,961.00 ms | 4.556438% |
| **正式 pooled** | **43,048.50 ms** | **41,051.25 ms** | **1,997.25 ms** | **4.639534%** |

八条原始 walltime 按执行顺序为：

- ABBA：`43019 / 40986 / 41065 / 43099 ms`；
- BAAB：`41136 / 43010 / 43066 / 41018 ms`。

所有 50k 功能签名均为 instr=73,580 / cycle=49,996 / guest=50,001，
terminal PC=`0x80001312`，无负向错误；ASLR personality 均为 `00040000`，
CPU migration 均为 0。八次 binary/nemu 本地页面比例均为 1，task-clock
与全部 PMU event 调度比例均为 100%，八个独立 staging inode 与对应快照
的 binary/image/nemu SHA 全部一致。原始 emu 日志 walltime 与结果逐条相符。

完整稳定性门禁 8/8 通过：

| 门禁 | 实际值 | 上限 |
| --- | ---: | ---: |
| wall order gap | 0.166151 pp | 0.25 pp |
| base block shift | 0.048782% | 1% |
| base+B block shift | 0.125453% | 1% |
| base sample spread | 0.206744% | 2% |
| base+B sample spread | 0.365397% | 2% |
| cycles order gap | 0.176129 pp | 0.5 pp |
| wall/cycles gain gap | 0.060388 pp | 0.5 pp |
| user-cycles/task-clock 代理差 | 0.064783% | 0.25% |

辅助 PMU 计数如下，百分比统一为 `(base+B - base) / base`；最终裁决仍是
上面的 walltime，不能用某一 PMU 项代替端到端结果。

| 事件（每个 role 四次均值） | base | base+B | 变化 |
| --- | ---: | ---: | ---: |
| cycles:u | 156,275,007,428.50 | 148,930,203,951.75 | -4.699922% |
| instructions:u | 148,662,103,085.00 | 148,082,145,619.50 | -0.390118% |
| de_no_dispatch_per_slot.no_ops_from_frontend:u | 693,084,978,088.50 | 649,555,553,429.00 | -6.280532% |
| cpu/de_no_dispatch_per_slot.no_ops_from_frontend,cmask=0x6/u | 86,899,755,982.50 | 80,333,298,577.75 | -7.556359% |
| de_no_dispatch_per_slot.backend_stalls:u | 53,883,923,792.75 | 55,283,914,523.50 | +2.598160% |

正式原始结果为 `pair4/result.json`，SHA-256：
`ddfca43382bdd3c5db74d44c328738175fb51de53ec8de423cbf7d99212e7260`。
完整审计为 `pair4/stability_audit.json`，SHA-256：
`35fe4edd310e176acf079eb94f01d7c7e1be2a50304032b6ba771c85306adc86`，
返回 `accepted: true`，failed stability gates 为空。审计还重验全部冻结文件、
实际生成源码及双方配置身份；没有重写原始数据。

本轮结论：B 在当前默认 baseline 上有明确的 SimTop 50k walltime 正收益，
保留通用 C++/Python 默认启用的落地实现。A/C 未纳入。本任务的 8 项 CTest、
双方各 32 项 pybind、100/10k/50k 功能检查和 SimpleTES 161 项 bench/runtime
回归均已完成；新研究 pin 与空 control 的交接见 TNO0297。本轮性能采样结束。
