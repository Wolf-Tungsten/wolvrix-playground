# TNO0278: XiangShan RepCut parallel CPU audit and balanced capture protocol

日期：2026-09-07

状态：`DIAGNOSTIC CAPTURE PROTOCOL; NO STRICT N32 PERFORMANCE CLAIM`。

## 1. 背景与测量边界

承接 [TNO0277](./TNO0277_xiangshan_repcut_n8_n32_page_local_protocol_20260907.md)。
N=8 已完成 page-local v4 diagnostic AB/BA；N=32 首轮 v4 只有 baseline 一次
性能样本通过 diagnostic 门，candidate 连续 12 次未过。不能将这些不对称次数的均值
组成正式 A/B，也不能继续重试，直到计量偏差恰好有利时才选择样本。

本记录仅修正采集与证据分类，不修改 clean-v4 ELF、分区结果、执行代码或默认模式。
N=8/N=32 的性能与通信阶段分析另建结果记录。

## 2. N32 首轮 CPU accounting 异常

原始产物位于：

```text
build/repcut_closure_runtime_20260902/runs/
  node030_n32_ccd112_120_144_152_pagelocalv4_diagnostic_ab_20260907_1538/
build/repcut_closure_runtime_20260902/results/
  node030_n32_ccd112_120_144_152_pagelocalv4_unaccepted_pilot_20260907_1538/
```

全部运行在 node030 NUMA1，32 个物理核为 `112-127,144-159`，monitor 为 CPU0。
旧门使用 `max(0, proc_stat_target_busy - perf_task_clock)` 估计外来 CPU 时间；
阈值是 `max(0.05 s, workload_wall * 0.005)`。

然而 candidate attempt10 的 workload wall 为 `10.646844 s`，某目标 CPU 的
`/proc/stat total` 却增长 `12.55 s`；32 CPU 的 total 合计比 `32 * wall`
多 `28.031 CPU s`。同次 busy 减 task-clock 为 `44.929 CPU s`。
令：

```text
X = sum(target proc_stat total delta) / CLK_TCK - 32 * workload_wall
Y = proc_stat_target_busy_seconds - perf_task_clock_seconds
```

12 个 candidate 样本的 `corr(X,Y)=0.999928`，`Y-X=16.895..18.046 CPU s`。
baseline 则发生相反的 total 少记 `21.854 CPU s`，`Y=-3.437 CPU s`，被
`max(0,Y)` 截断为 0 后通过。这说明该门在这组并行样本上存在方向性筛选风险。

候选前五次记录到目标 CPU 的 foreign task 增量仅为 `7/6/1/0/1 ticks`，
而 busy 减 task-clock 为 `7.923/1.818/26.769/19.291/32.417 CPU s`。
这些全 `/proc` 任务快照可能漏掉短命任务，不能据此保证零干扰；但也不能把全部
不闭合量直接解释成外来进程运行时间。

现有 v4 只保存 total/idle，缺少原始 user/system/irq 等字段和读取时刻。
因此尚未确认偏差属于何种内核计量行为、窗口误差或其它原因。编译配置中存在
`CONFIG_VIRT_CPU_ACCOUNTING_GEN` 和 `CONFIG_NO_HZ_FULL`，但目标机器没有
启用 full-nohz CPU mask，不能仅凭内核配置归因。

## 3. v5 的附加证据与采样顺序

新建 `run_parallel_pair_v5.py`，保留冻结 v3/v4，不修改原有判定阈值：

- 同一次 `/proc/stat` 读取保留全部 10 个原始 CPU 字段，以及 monotonic 和
  MONOTONIC_RAW 读取起止、读取耗时。运行结果保留 workload 与快照边界的时间差。
- 每轮仍只做一次 worker affinity 快照，但移到全 `/proc` 任务扫描和页面扫描之后。
  v4 中首轮 affinity 可能发生在 model 启动之前，而页面在启动之后，导致较短的
  N=32 样本只有 2 个完整 worker 快照。v5 保留至少 3 次的要求，不双计快照。
- 继续区分 N 个固定单核的 RepCut worker 与 N-1 个未派发任务的 Verilator
  备用线程，记录备用线程 CPU ticks，而不是把它们误判为多余计算 worker。
- 独立 `raw_procstat_sampler.py` 可在其它 CCD 上每 150 ms 只读采集原始 CPU
  字段，为区分读取延迟、字段跳变和真实负载提供证据。

冻结身份：

| 文件 | SHA-256 |
| --- | --- |
| run_parallel_pair_v4.py | `8ca429c12c49cac6d21f52ce2808e47b593a8eebf43dee4e9bd85aed85c8abf2` |
| run_parallel_pair_v5.py | `695f5542ada4acfe3317ef843aefa78096b418a7015881d92799dabf21d95fab` |
| raw_procstat_sampler.py | `fa15d2b6525a6935cd477b080d484cf7d4e0d48d120ca5f64b6518b19882f06d` |

## 4. 固定 AB/BA capture 规则

新增独立 `capture_parallel_pair_v1.py` 复用 v5，输出 `captured.json`，固定状态为
`diagnostic_capture_not_formal_acceptance`，不生成冒充正式通过的 `accepted.json`。

1. 每序、每臂使用独立 NUMA-local tmpfs 输入；全部输入、工具、runner、拓扑及顺序
   记录身份，结束后重新验证 staging 与源 build manifest。
2. 两序分别为旧后新 AB 和新后旧 BA；每序先运行两臂 C=100 功能门，再运行
   C=10000 性能样本。K=32、N=32、相同 CPU mask 与 NUMA 保持不变。
3. admission 不安静时尚未启动仿真，可以有限重试；每臂 C=10000 一旦启动，
   无论 runtime audit 通过或拒绝，都保留该次并推进下一臂，不按性能或审计残差重抽。
4. 保留原 `accepted`、`rejection_reasons`、完整 runtime/page/worker 判定，
   不清洗失败结果。功能签名、输入身份或计时产物错误仍停止采集。
5. 汇总全部四次预定性能记录，分别报告 AB、BA 和两序中心值。页面、worker 或
   干扰证据不充分时必须说明；该汇总不能称为 strict 或正式 clean performance。

这一策略用于回答共享节点当前观察到的性能和更新阶段代价，不能替代后续修正
CPU accounting 审计并取得低干扰独立重复组。不得据此把 closure-aware 改为默认。

## 5. 指标解释继续沿用 TNO0277

`global_update` 是数据拷贝及线程派发/等待的墙钟区间，含跨 partition 与顶层输出
更新，不是互连字节计数。每 worker 的 push 平均时间之和的最大值是关键工作量的
聚合下界；phase wall 减该值仍是混合剩余时间，不能改称纯 barrier。

跨 N 比较还混合了单 CCD 与四 CCD 的缓存拓扑变化，以及频率、调度和共享机器
负载变化。正式结论优先比较同 N、同 mask 的新旧划分，不从旧 N=1 跨机数据生成
严格 scaling headline。

## 6. 增量更新 2026-09-07：固定 capture 的原始 CPU 计量证据

最终 N=32 固定 AB/BA 使用 node030 NUMA1、物理 CPU
`104-111,144-151,160-167,176-183`，runner monitor 为 CPU8。
独立原始采样器绑定 CPU0，以 150 ms 间隔运行 `180.002 s`，自然结束并回收进程，
共保存 `1201` 次样本。两个 monitor 均位于测量 CCD 外。

原始与汇总产物：

- [独立原始采样 JSONL](../../build/repcut_closure_runtime_20260902/results/raw_procstat_node030_n32_capture_20260907_1557.jsonl)。
- [四样本 CPU accounting 汇总](../../build/repcut_closure_runtime_20260902/results/node030_n32_capture_20260907_1557_raw_accounting_summary.json)，记录输入 SHA、原始 runtime verdict、页面与线程门、起止快照和独立采样交叉核对。
- [AB captured.json](../../build/repcut_closure_runtime_20260902/runs/node030_n32_ccd104_144_160_176_pagelocalv5_capture_ab_20260907_1557/captured.json)。
- [BA captured.json](../../build/repcut_closure_runtime_20260902/runs/node030_n32_ccd104_144_160_176_pagelocalv5_capture_ba_20260907_1557/captured.json)。

### 6.1 窗口长度与字段贡献

四个性能样本的起始原始快照结束至 workload 计时开始间隔为
`0.773..1.890 ms`；workload 计时结束至结束快照开始为 `0.139..0.268 ms`。
起止快照读取耗时分别为 `0.418..1.042 ms`、`0.515..0.620 ms`。
这些实际边界排除了“固定约 0.55 秒未扣尾巴，累乘 32 核形成约 17 CPU 秒”
这一解释；不能把先前公式中的 `Y-X` 直接解释成审计尾巴。

以下均为 32 个目标 CPU 的累计 CPU 秒；差额保留正负号，没有经过旧门的 `max(0, ...)` 截断。

| 顺序与臂 | raw user | raw system | raw busy | perf task-clock | busy - task-clock |
| --- | ---: | ---: | ---: | ---: | ---: |
| AB baseline | 103.460 | 18.890 | 122.350 | 123.28510 | -0.93510 |
| AB closure-aware | 122.690 | 25.500 | 148.190 | 130.17169 | +18.01831 |
| BA closure-aware | 156.190 | 27.540 | 183.730 | 128.99275 | +54.73725 |
| BA baseline | 100.110 | 18.340 | 118.450 | 123.47132 | -5.02132 |

四个窗口的 nice、iowait、irq、softirq、steal、guest、guest_nice 增量均为 0，
本轮差额实际落在 user/system 计量中，不能归为单列的 IRQ 或 steal 时间。
`sum(raw total) - 32 * workload_wall` 依次为
`-20.22598/+0.75793/+33.84579/-22.76670 CPU s`，仍有明显非守恒现象。

独立采样器读取耗时中位数 `1.231 ms`、最大 `1.613 ms`，没有观察到原始 CPU
字段倒退。以邻近 workload 边界的独立快照计算，四次 busy 分别为
`122.350/148.180/183.420/118.120 CPU s`，与 runner 起止计数差不超过 `0.330 s`。
独立快照与 workload 边界最多相差约 74 ms，不能用来替代精确 endpoint，
但复现了大幅差额，支持这不是 runner 的 JSON 加总错误或审计收尾扫描造成的现象。

### 6.2 内核源码中相符的计量机制

对照 Linux v6.8 上游源码，可确认这几条计量路径并不相同：

- [`account_process_tick` 与 `cputime_adjust`](https://github.com/torvalds/linux/blob/v6.8/kernel/sched/cputime.c#L448-L605)：未启用该 CPU 的 vtime 时，user/system 使用 tick 归属；源码说明 tick 统计可能高估或低估，task cputime 会另外对齐 scheduler runtime。
- [`/proc/stat` 的 idle 来源](https://github.com/torvalds/linux/blob/v6.8/fs/proc/stat.c#L23-L49)及 [CPU 字段输出](https://github.com/torvalds/linux/blob/v6.8/fs/proc/stat.c#L129-L155)：user/system 来自 CPU cpustat；idle 在可用时单独取 `get_cpu_idle_time_us`，并不是强制与其它字段相加后等于墙钟容量。
- [`perf task-clock`](https://github.com/torvalds/linux/blob/v6.8/kernel/events/core.c#L10558-L10601)：累计 perf task context 的运行时间，不是重新读取 `/proc/stat` 的 user/system tick。
- [`generic vtime` 的启用条件](https://github.com/torvalds/linux/blob/v6.8/include/linux/vtime.h#L62-L82)：它依赖 context tracking，不能仅凭 `CONFIG_VIRT_CPU_ACCOUNTING_GEN=y` 推断每个 CPU 都已使用该路径。

node030 内核为 `6.8.0-111-generic`，`CONFIG_HZ=1000`，没有启用 full-nohz CPU mask，
且 `CONFIG_IRQ_TIME_ACCOUNTING` 未开启。以上源码机制与观察到的计量差异相符，
但本轮没有逐 tick 追踪，也没有严格复现并分离该内核版本的全部路径，
因此不能断言每一秒差额都已完全归因，或所有差额都不含外来工作。

### 6.3 判定、身份与验证

四条性能记录的 page gate 均通过，ELF/NEMU 的观察到的 remote bytes 均为 0。
完整 worker 绑定样本数依次为 `5/3/3/5`，没有未知线程配置；每次 31 个 Verilator
备用线程的最大已观察 lifetime CPU ticks 合计均为 0。
这些线程计数仍受观察时刻和 tick 分辨率限制，不宣称逐纳秒的零消耗。

两个 baseline 的原始 diagnostic accepted 为 true；两个 closure-aware 的原始
accepted 为 false，唯一拒绝原因为 `runtime_unexplained_target_busy`。
原始 verdict 原样保留，固定采集没有据该 verdict 选择或重试已启动的性能样本。
最终仍为 balanced diagnostic capture，不是 formal clean acceptance。

`capture_parallel_pair_v1.py` 的冻结 SHA-256 为
`38c27648aaf0f565ee85915f95fbeec16e7b3b678a320aef8b4ac4090299eb21`。
v5 的 23 项聚焦测试以及 capture wrapper 的 7 项测试通过；后者覆盖性能失败不重试、
accepted/reasons 不改写、仅 admission 未启动重试，以及功能/计时错误记录后停止。
冻结 v4/v5 和原始实验产物均未修改；没有放宽原 CPU 门，也没有继续实施内核修复。
