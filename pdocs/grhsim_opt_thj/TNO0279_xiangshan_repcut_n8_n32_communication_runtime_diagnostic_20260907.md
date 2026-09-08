# TNO0279: XiangShan RepCut N=8/N=32 communication runtime diagnostic

日期：2026-09-07

状态：`N8 DIAGNOSTIC AB/BA COMPLETE; N32 BALANCED DIAGNOSTIC CAPTURE COMPLETE; DEFAULT UNCHANGED`。

## 1. 结论与适用范围

旧 baseline 与新 closure-aware 都是 `K=32` 的 Partitioned 模型，不是 Native 对比。
本轮在 node030 NUMA1 测量 `N=8/32, C=10000`，每档均完成 AB/BA，每臂两次性能
样本。Host 中心值分别减少 `7.520%` 和 `24.632%`。

通信相关的 `global_update` phase，N=8 从 `170.976` 到 `169.665 us/step`，
两序一降一升，应判为基本持平；N=32 从 `205.919` 到 `178.501 us/step`，
减少 `13.315%`，两序方向一致。N=32 的主要收益仍来自计算削峰，不是消除了通信。

这不是正式 clean performance：N=8 只通过 diagnostic 而非 strict；N=32 因
`/proc/stat` 与 task-clock 计量不闭合，按事前冻结的固定 capture 规则保留全部
四个预定样本及其失败判定，未按异常残差筛选。审计问题及采集规则见
[TNO0278](./TNO0278_xiangshan_repcut_parallel_cpu_audit_capture_protocol_20260907.md)。
不得用这组数据修改默认划分模式。

## 2. 配置、身份与执行

前置协议为 [TNO0277](./TNO0277_xiangshan_repcut_n8_n32_page_local_protocol_20260907.md)，
串行参照为 [TNO0275](./TNO0275_xiangshan_repcut_n1_page_local_ab_ba_node033_20260904.md)。
两侧继续使用 clean-v4 的统一 Clang21 frozen build，无重建、无新划分、无调度代码改动。

| 项目 | N=8 | N=32 |
| --- | --- | --- |
| 节点 / NUMA | node030 / 1 | node030 / 1 |
| 物理 CPU | `112-119` | `104-111,144-151,160-167,176-183` |
| L3 / CCD 数 | 1 | 4 |
| runner monitor CPU | 0 | 8 |
| 额外 raw CPU 采样 | 无 | CPU0，每 150 ms，只读 |
| runner | parallel-page-local-v4 | v5 + diagnostic-once-v1 capture |
| 性能采集规则 | 既定 diagnostic 门；未启动的 admission 可重试 | 每臂首次 admission 通过后只启动一次；保留全部 runtime 判定 |
| 顺序 | AB、BA | AB、BA |
| K / N 分配 | 每 worker 连续 4 个 partition | 每 worker 1 个 partition |

两档都先执行每序两臂的 `C=100` 功能门，然后执行 `C=10000`，性能记录均为
`20102` 次内部 step。下文 `us/step` 是内部 `step()` 的平均微秒数，不是单个
guest cycle 的微秒数。Host 是 emulator 日志时间；workload wall 是 Popen 到 wait
返回，已经排除 audit finalization。

N=32 最终换用了新空闲 CCD 组合，N=8 CPU 集合不是其子集。两档同节点、同 NUMA，
但拓扑集合、时间和 capture 协议不同，因此跨 N 数值仅作机制参照，不是单变量扩展实验。
相关资源扫描及失败 pilot 均保留，没有停止节点上的其它用户或 SimpleTES 工作。

| frozen ELF | SHA-256 |
| --- | --- |
| baseline | `355a2c7df9faec3e8f56591b53e5e214f7b0a3bf8453549bd3dc4cf55afadd77` |
| closure-aware | `b5803a654b2f63057f71337ae02137089e8d28177c2b0e41918fefdc6c778b55` |

每个 order/arm 独占目标 NUMA 的 tmpfs ELF/image/NEMU inode；结束后再次校验内容
及 stat 身份。每档两序合计 12 个不同输入 inode。所有性能样本的 ELF 与 NEMU
可执行驻留页均 `remote_bytes=0`，页面覆盖率和至少 3 个有效采样通过。

## 3. AB/BA 原始结果

旧到新按 `(candidate / baseline - 1) * 100%` 计算变化；负值表示时间缩短。

| N | 顺序 | baseline Host s | closure-aware Host s | 变化 |
| --- | --- | ---: | ---: | ---: |
| 8 | AB | 16.507 | 15.913 | -3.598% |
| 8 | BA | 17.218 | 15.276 | -11.279% |
| 8 | 两序中心 | 16.8625 | 15.5945 | -7.520% |
| 32 | AB | 14.108 | 10.507 | -25.525% |
| 32 | BA | 13.977 | 10.660 | -23.732% |
| 32 | 两序中心 | 14.0425 | 10.5835 | -24.632% |

N=8 的顺序效果差为 `7.680 pp`，幅度不稳定；N=32 为 `1.793 pp`。
N=32 同臂两序 Host spread 为 baseline `0.933%`、candidate `1.446%`。
每臂仅两次，均值不代表置信区间。

N=8 两序的性能样本都是首次实际 launch；BA baseline 的前四次尝试仅因 admission
未安静而未启动，第五次才启动。N=32 capture 两序均按固定规则保留每臂唯一 launch。
未将更早的 N=32 v4 一次 baseline 与十二次 rejected candidate 混入结果。

## 4. 更新阶段与计算阶段

所有派生值先合并原始总毫秒，再计算平均值、最大值或比例，不直接平均舍入后的打印值。

| 指标 | N=8 baseline | N=8 closure-aware | 变化 | N=32 baseline | N=32 closure-aware | 变化 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| input_load wall us/step | 见 summary | 见 summary | 见 summary | 13.829 | 13.552 | -2.002% |
| part_eval wall us/step | 658.995 | 596.623 | -9.465% | 473.818 | 329.588 | -30.440% |
| global_update wall us/step | 170.976 | 169.665 | -0.767% | 205.919 | 178.501 | -13.315% |
| global_update 占 step wall | 20.472% | 21.988% | +1.517 pp | 29.690% | 34.219% | +4.529 pp |
| push 函数时间跨 worker 总和 us/step | 780.317 | 636.304 | -18.456% | 1825.332 | 1767.114 | -3.189% |
| 最大 worker 的 push 平均时间之和 us/step | 135.280 | 117.898 | -12.849% | 141.607 | 117.060 | -17.334% |
| update wall 减上述最大值 us/step | 35.696 | 51.767 | +45.021% | 64.312 | 61.440 | -4.465% |

`global_update` 包含跨 partition 与顶层输出的内存拷贝，以及线程派发、唤醒和等待。
它不是纯粹的网络传输时间或物理互连流量。

每个 push 函数的计时也是 steady-clock 区间，包含缓存等待与可能的抢占，不是 CPU
执行时间。跨 worker 求和会重叠，不能把这行总和从 phase wall 中直接减去。
最大 worker 的平均计时工作量是平均关键路径的下界，不是逐 step 实测 makespan；
最后一行混合了调度、同步、函数包装和逐步负载变化，不能称精确 barrier。

### 4.1 N=8：拷贝工作量下降，但更新阶段没有稳定缩短

AB 的 global_update 为 `-2.788%`，BA 为 `+1.188%`，中心值仅 `-0.767%`。
关键 worker 的计时 push 负载减少 `17.382 us/step`，混合剩余时间却增加
`16.071 us/step`，基本抵消。因此不能宣称 N=8 的通信阶段已被优化。

N=8 的 Host 改善主要出现在 eval phase。这里还存在明显执行状态差异：按
cycles/task-clock 派生的平均频率从 `2.441` 到 `2.901 GHz`，增加 `18.845%`；
候选线程迁移更多。不能把 `7.520%` 解释为固定频率下纯负载平衡带来的收益。

### 4.2 N=32：削减最慢 worker 在实际并行执行中生效

最大 eval 从 `430.304` 到 `283.574 us/step`，减少 `34.099%`，两序分别为
`-34.097%/-34.101%`。eval phase 从 `473.818` 到 `329.588 us/step`。

global_update 两序分别减少 `15.209%/11.380%`，最大 push worker 减少
`17.231%/17.437%`。混合剩余时间则分别减少 `10.945%` 和增加 `2.574%`，
没有证据说同步成本本身已稳定下降。更新 phase 的改善主要对应关键拷贝负载下降。

Host 共减少 `3.459 s`，phase 变化基本闭合：

- eval 节省约 `2.899 s`，贡献约 84%。
- global_update 节省约 `0.551 s`，贡献约 16%。
- input_load 节省约 `0.006 s`，其它差额很小。

计算下降更快，所以更新阶段虽然绝对耗时降低，占比反而由 `29.690%` 升到
`34.219%`。占比变大不代表该阶段变慢。

## 5. 线程数增加后，通信开销没有随核数等比缩小

以本轮数据作有条件的跨 N 参照：

| 指标，N=8 到 N=32 | baseline | closure-aware |
| --- | ---: | ---: |
| global_update wall | 170.976 -> 205.919 us，+20.437% | 169.665 -> 178.501 us，+5.208% |
| push 函数时间跨 worker 总和 | 780.317 -> 1825.332 us，2.339x | 636.304 -> 1767.114 us，2.777x |
| update 混合剩余时间 | 35.696 -> 64.312 us，+80.166% | 51.767 -> 61.440 us，+18.687% |

N=32 跨四个 CCD。更多并行 worker 并没有把更新时间缩短为 N=8 的四分之一，
而是出现更多累计拷贝函数等待与更高的 phase 剩余时间。结合代码中的共享对象拷贝、
每阶段逐 worker condition-variable 通知/等待，这与跨 CCD 缓存访问及同步代价的
影响一致；本轮没有硬件缓存一致性流量计数，不能把增长精确拆成其中哪一项。

静态通信规模不随本轮 N 改变，因为仍是同一 K=32 划分。
[TNO0266](./TNO0266_xiangshan_repcut_closure_weight_k32_static_ab_20260901.md) 的
cross-endpoint words 总量为 `2,455,010 -> 2,595,894`，增加 `5.739%`；
communication proxy KM1 为 `14,224,071 -> 22,306,433`，增加 `56.822%`。
二者是静态指标，不是本轮实际总线字节。连接总量增加与最慢 worker 的拷贝时间减少
可以同时发生，不构成矛盾。

## 6. PMU 与审计边界

| 指标，两序中心 | N=8 baseline -> candidate | N=32 baseline -> candidate |
| --- | ---: | ---: |
| instructions | 275.618 -> 290.681 G，+5.465% | 289.251 -> 303.888 G，+5.061% |
| task-clock | 82.260 -> 74.884 CPU s，-8.967% | 123.378 -> 129.582 CPU s，+5.028% |
| cycles | 200.771 -> 217.212 G，+8.189% | 205.350 -> 203.396 G，-0.952% |
| cycles/task-clock 平均 GHz | 2.441 -> 2.901 | 1.664 -> 1.570 |
| context switches | 382256.5 -> 428505.5 | 1410026 -> 1400307 |
| CPU migrations | 32 -> 7543 | 24197.5 -> 18834 |

这是整个 workload 的聚合 PMU 值，不是单个 phase 的 PMU。所有事件记录的运行覆盖
均为 100%，未 multiplex。worker 快照均固定单核；host 主线程保留整个目标 mask，
可发生迁移，不能把进程级 migrations 直接解释为 worker 没有 pin。

两档的 N-1 个 Verilator 备用线程观测 CPU ticks 均为 0；不能由进程总 OS thread
数 `2N` 推导出存在 `2N` 个忙碌计算线程。最终进程退出前的未采样尾部不在该断言内。

N=32 四个性能样本的页面和 worker 门均通过，完整 worker 快照数分别为
AB baseline/candidate `5/3`，BA candidate/baseline `3/5`。但是：

- 四条 strict 判定均保留 `runtime_foreign_task_load`。
- baseline 两序原 diagnostic 判定通过；candidate 两序仍拒绝
  `runtime_unexplained_target_busy`，差额分别 `18.018/54.737 CPU s`。
- 原始 CPU total 相对 `32 * workload_wall`，baseline 为 `-20.226/-22.767 CPU s`，
  candidate 为 `+0.758/+33.846 CPU s`。用原始快照准确读取窗口代替 workload 窗口，
  偏差仍存在；不是 audit finalize 混入导致。
- capture 汇总器重算并核对这些拒绝原因，原 `accepted=false` 没有被改成 true。

因此证据支持“本轮新划分的计算削峰转化成了更短并行 wall，N=32 更新阶段也减少”，
但不支持“严格无干扰条件下保证相同比例加速”，也没有取得纯 barrier 或互连字节数。

## 7. 产物与复算

实验根目录为 `build/repcut_closure_runtime_20260902/`。原始输入：

```text
runs/node030_n8_ccd112_pagelocalv4_diagnostic_ab_20260907_1534/accepted.json
runs/node030_n8_ccd112_pagelocalv4_diagnostic_ba_20260907_1534/accepted.json
runs/node030_n32_ccd104_144_160_176_pagelocalv5_capture_ab_20260907_1557/captured.json
runs/node030_n32_ccd104_144_160_176_pagelocalv5_capture_ba_20260907_1557/captured.json
```

| 记录 | SHA-256 |
| --- | --- |
| N8 AB accepted | `31abb8fa866ec62500a9c783b27b0ff03d36d479abf61e19da85ba73007f7d23` |
| N8 BA accepted | `cabf8f92a0e9ef1fd2b3108f2cf5c7b5c27db0bcd3662f031edbf3729e265d6b` |
| N32 AB captured | `5d64e0736b473276d94967df95792099e138e1b39e78ca0f079b787cc379db0c` |
| N32 BA captured | `d71b23a12fd58a03062270a6d8e5191fcb9a080ea9fc6e283aeff8a22789005a` |

汇总目录：

```text
results/node030_n8_ccd112_pagelocalv4_diagnostic_pooled_20260907_1534/
results/node030_n32_ccd104_144_160_176_pagelocalv5_capture_pooled_20260907_1557/
```

每个目录有 `summary.json` 与 `comparisons.csv`，保留每 partition 和 worker 的
平均计时数据。N=32 summary SHA 为
`3a56867f7a72268b2f32582d3222446fd98e4abc17b6db4b8c45b6010dfa162a`。

汇总器 `analyze_parallel.py` SHA 为
`ba3aa39eed961c9081745d77b3afa323db9b79cd8d348b87054ddb1810708acd`，
独立 capture 汇总器 `analyze_parallel_capture.py` SHA 为
`5780eb299b95c65e5e237a766a5beac4420752fcffccd8b8f72ff52da9e131ff`。
后者逐条核对 attempts 中全部 launched 记录与 captured 顺序完全一致，并重新解析
日志、PMU、timing、页面与 worker gate，避免选择性遗漏失败样本。

复算时给上述汇总器分别传两次 `--accepted` 或 `--captured` 和一个不存在的新
`--output-dir`；不得覆盖已有 summary。相关 runner/analyzer 的 77 项聚焦测试通过。

## 8. 保留与下一步

保留 clean-v4 两臂 ELF、全部运行/失败记录、tmpfs staging 及 raw CPU 证据。
未拆大 ASC，未改变默认权重或运行时调度。

下一阶段的性能判定需要先解决并行 CPU accounting 审计的适用性，再取得独立、
低干扰重复组。若继续定位通信，需要逐 phase 的硬件缓存/互连事件或逐 step 的
worker dispatch/completion 时间线；现有聚合差值不足以单独归因 barrier。

## 9. 增量补充 2026-09-07：N8 input_load 明细

第 4 节引用 summary 的 N=8 input_load 中心值为 baseline `5.206 us/step`、
closure-aware `5.323 us/step`，增加 `0.117 us/step / 2.250%`。
两序分别为 `+9.813%/-4.757%`，方向不稳定，绝对值也远小于 eval/update，
不改变本记录对性能收益来源的判断。

术语勘误：第 4.1 节标题“拷贝工作量下降”应严格理解为“拷贝函数累计计时下降”，
不是静态拷贝次数或字节数下降；第 4.2 节“关键拷贝负载下降”指关键 worker 的
拷贝函数计时下降。第 5 节“更多累计拷贝函数等待”应理解为“更长的累计拷贝函数
计时”，不能将全部时间增长单独归因于等待。本轮未分离指令执行、缓存停顿与抢占。
这些澄清不改变表中时间值，也不改变静态通信规模增加的结论。
