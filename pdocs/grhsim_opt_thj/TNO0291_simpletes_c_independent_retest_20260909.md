# SimpleTES C independent retest

## 本轮结果

按用户要求，对 [TNO0290](./TNO0290_simpletes_gen38_bestpath_factorial_ablation_20260909.md)
的 C 单项进行一次独立复测。C 是在 event-qualified commit 路径上省略冗余的
global active-byte clear。本轮比较仍为 B0→C，未启用 A/B，不是 ABC→AB 的
leave-one-out 比较。

node031 的第一组完整 ABBA+BAAB 即达到 order gap `<0.25 pp`：

| 顺序 | B0 walltime / ms | C walltime / ms | B0−C / ms | walltime 提升 |
| --- | ---: | ---: | ---: | ---: |
| ABBA | 42,524.00 | 42,755.00 | −231.00 | −0.543223% |
| BAAB | 42,661.50 | 42,878.50 | −217.00 | −0.508655% |
| pooled | 42,592.75 | 42,816.75 | −224.00 | −0.525911% |

gap 为 `0.034567 pp`，两个顺序都显示 C 更慢。本轮没有发现 C 单项的正向收益。
旧 `C_repeat4` 是 `42,440.75→42,470.25 ms`（慢 `29.50 ms/0.069509%`，
两个顺序方向相反，gap `0.216498 pp`）。旧轮与本轮使用不同 CCD，不能用绝对均值
跨轮相减。本轮提供方向一致的回退证据，但两轮的回退幅度不同，不能把 `0.525911%`
视为所有机器/CCD 上的固定开销，也不能据此证明 C 在含 B 的组合中没有交互收益。

## 样本与测量条件

本轮复用上一阶段已构建的不可变 binary，没有重新生成 RTL 或重编译。
八个 measured samples 的端到端指标均读取 emu 的 `Host time spent`，每次运行
`-C 50000`，并使用 NEMU Difftest。

| 顺序 | B0 samples / ms | C samples / ms |
| --- | --- | --- |
| ABBA | `42512, 42536` | `42536, 42974` |
| BAAB | `42589, 42734` | `42694, 43063` |

同组固定 node031 / NUMA1 / CCD `104-111,296-303` / CPU `104`，SMT sibling `296`，
helper CPU `0`。ABBA 与 BAAB 复用同一 runtime placement。
关闭 ASLR 的方式是 `setarch x86_64 -R`；每个 sample 继续执行 quiet CCD pre-gate、
continuous monitor、进程 affinity、NUMA 页面、PMU 和功能门禁。
driver 返回 `valid=true`，`selected_pair_attempt=1`，没有发生 infrastructure retry。
B0/C 的四样本 spread 分别为 `222/527 ms`。

旧 driver 只调用 runtime 底层门禁，未自动执行 evaluator 的完整稳定性判断。
因此本次另做离线复核：核对两组 placement 相同，拼接原始八个样本，将第二组的
sample index 从 `1..4` 适配为 `5..8`，构造 `ABBA+BAAB` diagnostics 后实际调用
当前 `evaluator._mirrored_measurement_summary`。未改变任何 walltime、PMU 或原始日志。

| 完整稳定性门禁 | 实测 | 阈值 | 结果 |
| --- | ---: | ---: | --- |
| wall order gap | 0.034567 pp | <0.25 pp | 通过 |
| control block shift | 0.322825% | <1% | 通过 |
| candidate block shift | 0.288439% | <1% | 通过 |
| control sample spread | 0.521215% | <2% | 通过 |
| candidate sample spread | 1.230827% | <2% | 通过 |
| cycles order gap | 0.153406 pp | <0.5 pp | 通过 |
| wall/cycles gain gap | 0.042062 pp | <0.5 pp | 通过 |
| user-cycles/task-clock delta | 0.000809% | <0.25% | 通过 |

八份原始 emu log 均与 JSON walltime 一致；ASLR personality 为 `00040000`，
CPU migrations 全为 0，task-clock 和全部 PMU events scheduled ratio 为 100%，
emu/NEMU 本地页比例为 1.0。每个 sample 使用不同 staging binary inode，
复制时绑定 CPU104/NUMA1。

同样复核旧 `C_repeat4` 后发现 candidate sample spread 为 `2.180350%`，
超过当前 `<2%` 阈值。因此旧组只能视为通过 gap 的历史数据，未通过完整当前门禁；
本轮则全部通过。完整适配步骤、源文件 hash 与门禁结果保存在本轮目录的
`stability_audit_v2.json`，没有回写原始 `result.json`。v2 修正了审计材料中
legacy driver 的源文件引用（实际使用 `grhsim_bestpath_ablation_20260731` 下的脚本），
计算结果不变。可复现脚本是实验根目录的 `audit_c_retest.py`，使用新 `--output`
路径即可离线重算；runtime/evaluator hash 记录的是审计时文件身份。

PMU 的 pooled candidate−control 变化为：cycles `+0.567973%`，instructions
`−0.001499%`，frontend no-ops `+0.584059%`，frontend-starved `+0.840446%`，
backend stalls `+1.398437%`。cycles 与 walltime 同向变差；这些数据用于解释，
本轮结论仍由端到端 walltime 决定。

## 身份与复现入口

所有实验路径以 `build/grhsim_bestpath_ablation_20260909/` 为根：

- control：`control_v2/`
- candidate：`arms_build_v1/C/`
- 本轮结果：`results_node031_v2/C_repeat5/result.json`
- 原始 emu/perf/monitor/audit：`results_node031_v2/C_repeat5/runtime_logs/pair-attempt-1/`
- 上轮结果：`results_node031_v2/C_repeat4/result.json`（保留原记录）

| 身份 | 值 |
| --- | --- |
| parent pin | `6e2436e37286264e9f03f114d14d81bae4ed313b` |
| Wolvrix pin | `054c6a7c09b007a12eb36fdb49fcb659a1bfc590` |
| generation input | `0c63c3180527dd97382c69781d0042637758dfed5ed4c601cd6195fa07379545` |
| toolchain | `3139fef644317380a048f6d32551a70f2e960fe73558188951636856f4617038` |
| build config | `920b5c7f1e32e61e7ad363145521736e9a10a68d0e0d112ce7b4406f00e820b3` |
| B0 emu SHA-256 | `02654be2541f58be51dd36dbd48a93975b2560853561cf4829c6acfe9630c4b5` |
| C emu SHA-256 | `00c569e247679f90397c0f9fa02a39249276099d596257f25452c490eda03e7e` |
| 本轮 result SHA-256 | `24f3a2a8c69f6dd786f789e1644893e72a09bbd7328ecd2748fe206c5a6f4b5e` |
| stability audit v2 SHA-256 | `d699bb920db65af58184e952440a91e701242836b703dd43a36f9844409ad8aa` |

在 node031、workspace 根目录，先 `source wolvrix-playground-gsim-calibrate-5/env.sh`，
随后使用 `build/grhsim_bestpath_ablation_20260731/run_pair_sameccd.py`，
参数为 `--control control_v2 --candidate arms_build_v1/C --output results_node031_v2/C_repeat5`
（均展开为上述实验根下的绝对路径）、`--runtime SimpleTES/datasets/grhsim/simtop_50k/runtime.py`、
`--env-sh wolvrix-playground-gsim-calibrate-5/env.sh`（后两者展开为 workspace 下的绝对路径）、
`--retries 8`。复现时必须指定新 output 目录，避免覆盖本轮证据。

本阶段只运行 C 复测并归档结果，没有修改生产源码、默认选项或 SimpleTES 搜索状态。
