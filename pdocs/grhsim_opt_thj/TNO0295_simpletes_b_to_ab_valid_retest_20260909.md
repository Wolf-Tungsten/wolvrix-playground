# SimpleTES B to AB valid retest

## 结果与采用建议

本次按用户要求继续直接比较 B 与 AB；用户指定本次若无可用结果则不记录文档，
因此在得到完整有效结果、通过全部稳定性门禁后才建立本记录。
本轮 `AB_vs_B_repeat10` 在 node032 的第一次完整尝试即通过所有门禁。

| 顺序 | B walltime / ms | AB walltime / ms | B−AB / ms | AB 相对 B 的提升 |
| --- | ---: | ---: | ---: | ---: |
| ABBA | 40,660.50 | 40,874.50 | −214.00 | −0.526309% |
| BAAB | 40,605.50 | 40,779.00 | −173.50 | −0.427282% |
| pooled | 40,633.00 | 40,826.75 | −193.75 | −0.476829% |

order gap `0.099027 pp < 0.25 pp`，两个顺序都显示 AB 更慢。
这是通过约定门槛的有效负收益结果：本组 A 在 B 上增加了 `193.75 ms` 的
SimTop 50k 端到端 walltime。建议落地时优先只保留 B，A 不默认启用。
本次只测量和归档，没有将 B 落地，也没有修改生产默认或 SimpleTES 搜索状态。

B 是 selected hot input dispatch branch weighting，A 是 structurally hot
input-seed active-mask chunk packing；本轮 control=B、candidate=AB，两者只差 A。
机制定义见 [TNO0290](./TNO0290_simpletes_gen38_bestpath_factorial_ablation_20260909.md)，
前期直接比较与门禁说明见 [TNO0292](./TNO0292_simpletes_b_to_ab_direct_comparison_20260909.md)。
这组结果闭合该直接比较的测量门槛；不把其他 CCD/批次的绝对耗时横向相减，
也不把本组回退幅度视为所有负载/机器上的固定值。一次通过稳定性门禁的八样本组
不等于已经排除所有系统性噪声，但当前没有保留 A 默认开启所需的正向证据。

## 原始样本与运行条件

| 顺序 | B samples / ms | AB samples / ms |
| --- | --- | --- |
| ABBA | `40519,40802` | `40767,40982` |
| BAAB | `40494,40717` | `40420,41138` |

两种顺序均为 node032 / NUMA1 / CCD `128-135,320-327` / CPU130，
SMT sibling322、helper CPU0。顺序名称中的 A/B 表示 control/candidate 角色，
实际二进制执行顺序为 `B,AB,AB,B,AB,B,B,AB`。
每个样本均运行 SimTop `-C 50000` 和 NEMU Difftest，指标取 emu 的
`Host time spent`。本次共一组完整尝试，没有基础设施重试，没有跨尝试拼接样本。

复用不可变 `arms_build_v1/B` 与 `arms_build_v1/AB` 快照；启动前 driver
逐文件检查 `SHA256SUMS`，生成输入/工具链/构建配置相同。30 秒空闲调查后，
使用 `taskset -c 0,128-143,320-335` 限定两个完整 NUMA1 CCD 和外部 helper；
runtime 自动选定 CPU130，并在 ABBA 与 BAAB 间复用同一 placement。
这只缩小选核扫描范围，没有改变门禁或测量程序。

所有 shell 命令先 source 仓库 `env.sh`。关闭 ASLR 使用 `setarch x86_64 -R`，
全部 sample personality 为 `00040000`。每个 sample 使用独立 inode staging，
复制时绑定 CPU130/NUMA1；八个 emu inode 各不相同，emu 与 NEMU 本地页比例
均为 `1.0`。八个 quiet pre-gate、continuous monitor、affinity、binary identity、
NUMA、PMU、功能门禁均通过，CPU migrations 均为 0，task-clock 与全部 PMU
events scheduled percent 均为 `100%`。

## 完整稳定性审计

既有 same-CCD driver 的 `valid=true` 仅代表底层 runtime 门禁。
本次另用 `audit_b_ab_pair.py` 核对八条原始 emu walltime 和 staged binary SHA，
并实际调用当前 evaluator 的 `_mirrored_measurement_summary`：先证明两组
placement 相同，再深拷贝原始样本并将 BAAB index 从 `1..4` 适配为 `5..8`，
未改变任何测量值或原始 result/log。完整八项门禁如下。

| 门禁 | 实测 | 阈值 | 结果 |
| --- | ---: | ---: | --- |
| wall order gap | 0.099027 pp | 0.25 pp | 通过 |
| B block shift | 0.135358% | 1% | 通过 |
| AB block shift | 0.233915% | 1% | 通过 |
| B sample spread | 0.758005% | 2% | 通过 |
| AB sample spread | 1.758651% | 2% | 通过 |
| cycles order gap | 0.144523 pp | 0.5 pp | 通过 |
| wall/cycles gain gap | 0.046164 pp | 0.5 pp | 通过 |
| user-cycles/task-clock delta | 0.003884% | 0.25% | 通过 |

B/AB 的四样本 spread 分别为 `308/718 ms`。ABBA、BAAB 都回退，
`direction_consistent_positive=false` 在此表示“不满足双正向”，不是方向相反。

PMU 辅助数据如下；最终默认建议仍依据上述端到端 walltime。

| 指标（四样本均值） | B | AB | AB−B 相对变化 |
| --- | ---: | ---: | ---: |
| cycles:u | 148,972,101,602.75 | 149,751,215,858.00 | +0.522993% |
| instructions:u | 147,332,769,950.25 | 147,154,094,415.00 | −0.121273% |
| frontend no-ops | 653,780,673,750.00 | 658,204,995,062.50 | +0.676729% |
| frontend no-ops cmask=6 | 80,805,920,108.25 | 81,534,235,165.75 | +0.901314% |
| backend stalls | 51,779,558,868.50 | 51,941,305,533.00 | +0.312376% |

指令数略降而 cycles/walltime 增加，说明更少指令未转化为本组的端到端收益；
仅凭这些聚合事件不能断言具体的微架构因果。

## 身份与复现

所有路径以 `build/grhsim_bestpath_ablation_20260909/` 为实验根：

- control：`arms_build_v1/B/`
- candidate：`arms_build_v1/AB/`
- 结果：`results_resume_v3/AB_vs_B_repeat10/result.json`
- 完整审计：`results_resume_v3/AB_vs_B_repeat10/stability_audit.json`
- 原始日志：`results_resume_v3/AB_vs_B_repeat10/runtime_logs/pair-attempt-1/{abba,baab}/`

| 身份 | SHA-256 或 commit |
| --- | --- |
| parent pin | `6e2436e37286264e9f03f114d14d81bae4ed313b` |
| Wolvrix pin | `054c6a7c09b007a12eb36fdb49fcb659a1bfc590` |
| generation input | `0c63c3180527dd97382c69781d0042637758dfed5ed4c601cd6195fa07379545` |
| toolchain | `3139fef644317380a048f6d32551a70f2e960fe73558188951636856f4617038` |
| build config | `920b5c7f1e32e61e7ad363145521736e9a10a68d0e0d112ce7b4406f00e820b3` |
| B emu | `35c0136aa46d876149fcb7c850af75d3220193e0f1c5d240201553c17b11eec3` |
| AB emu | `e85fa0051cd0d79107499513ed02ebc838297274d247c1d6ead98a32709622b8` |
| result.json | `ae7e199541205b0e0e632be3a6469d71e5cc2c7b43a08e7f01afbba11c2309a0` |
| stability_audit.json | `7563706d066e38d8ccf83d5e2b2fc01886dc777fe621d8529e71ad3e0194e90a` |
| runtime.py | `78b3940db9b5ae3f3eff9b711f2a525564baf6b77317b214a82253c97f7a98cd` |
| evaluator.py | `2259d4d3e1f5e4c88527d01d521afbd7ae89101eceeb62b99578b510a505dcec` |
| same-CCD driver | `6539112dac5b8b9276471afd7e0a474b71327559ac06929586858abe851f71f0` |
| audit_b_ab_pair.py | `3a73d0b16f463d4e2aadaba9cc8ed91370e843302d33993b154816ca4e0bd75d` |

runtime/evaluator/driver hash 在启动前读取，审计文件也记录了审计时身份。
从 workspace 根目录执行以下命令可以复现（使用新的 output 目录，勿覆盖证据）：

```bash
source wolvrix-playground-gsim-calibrate-5/env.sh
taskset -c 0,128-143,320-335 python3 -u \
  wolvrix-playground-gsim-calibrate-5/build/grhsim_bestpath_ablation_20260731/run_pair_sameccd.py \
  --control wolvrix-playground-gsim-calibrate-5/build/grhsim_bestpath_ablation_20260909/arms_build_v1/B \
  --candidate wolvrix-playground-gsim-calibrate-5/build/grhsim_bestpath_ablation_20260909/arms_build_v1/AB \
  --output wolvrix-playground-gsim-calibrate-5/build/grhsim_bestpath_ablation_20260909/results_resume_v3/AB_vs_B_repeat11 \
  --env-sh wolvrix-playground-gsim-calibrate-5/env.sh \
  --runtime SimpleTES/datasets/grhsim/simtop_50k/runtime.py --retries 8
```

命令应在有空闲 CCD 的 node032 或兼容节点上执行；allowlist 需按当时实际空闲
拓扑选择。底层完整有效结果再交给 `audit_b_ab_pair.py --result ... --output ...`
审计；脚本拒绝覆盖，全部门禁通过才返回 0。上述 repeat11 是复现示例，本阶段未启动。
