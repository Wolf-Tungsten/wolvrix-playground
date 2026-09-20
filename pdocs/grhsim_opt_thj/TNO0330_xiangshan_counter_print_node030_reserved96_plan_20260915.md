# TNO0330: XiangShan counter-print node030 reserved96 plan

日期：2026-09-15

状态：已完成探索性 Host 复测及调度对照；2026-09-17 追加方案一前后时空图（第 8.4 节）。下文保留原计划和分阶段结果。

## 1. 本轮授权与固定配置

用户明确通知已在node030预留CPU96–127，继续
[TNO0325](./TNO0325_xiangshan_counter_print_host_ab_ba_plan_20260915.md)的Host比较。
[TNO0329](./TNO0329_xiangshan_counter_print_host_admission_blocked_20260915.md)两次
无launch尝试保持归档，不与本轮拼接。

N=K=32，CPU96–127、NUMA1、monitor0；目标为四个完整CCD，SMT siblings288–319
同时纳入原负载审计。用户提供的是96–127预约，siblings是否安静以实际gate为准，
不声称额外预约。继承原legacy/push、identity worker-to-part、C100 canary→C10000，
固定完整AB然后BA，保留原admission/page/worker/PMU检查。

## 2. 冻结产物和协议

使用[TNO0328](./TNO0328_xiangshan_counter_print_partition_build_gate_20260915.md)
A_v1/B_v1完整重建ELF，无重新编译或变更分区。A打印next_counter，B打印counter，
沿用已披露的实验语义差异与RTL生成差异；不新增优化。

根目录`build/asc_counter_host_20260915/`；原`spec.json`与冻结measurement/run_pair.py、
analyze_pair.py不变。117份native/helper和64份Verilator include启动前SHA复核通过，
分别保存`native-source-reserved96-pre.json`、`verilator-source-reserved96-pre.json`。

新的pair-id为`counter-print-20260915-node030-reserved96-pair1`，output tags为
`counter-print-20260915-node030-reserved96-ab1` / `counter-print-20260915-node030-reserved96-ba1`。
`--policy diagnostic --max-attempts 4 --retry-delay-seconds 5 --timeout-seconds 600`。
只重试未launch的admission，不重抽已启动慢样本，不根据runtime gate筛选性能样本。

两序须相同host/boot/CPU/NUMA/monitor/spec/source/tool；独立page-local staging。
结果先保留全部原始gate，再汇总Host及step wall，辅助观察eval max与update耗时。
两序primitive totals先求平均再算比值；不把静态ASC或复制字节降幅当作实测加速。
本轮完成后另建独立结果文档，继续保留`formal_acceptance=false`诊断测量口径。

## 3. 增量结果（2026-09-16）

按本计划使用node030 CPU96–127、NUMA1、monitor0完成了AB和BA两次完整调度尝试。
两次的C=100 canary均通过；C=10000四个样本均实际启动并保留，没有删样或重抽。
原始capture和汇总位于：

- `build/repcut_nk32_opt_20260907/runs/counter-print-20260915-node030-reserved96-ab1/captured.json`
- `build/repcut_nk32_opt_20260907/runs/counter-print-20260916-node030-reserved96-ba2/captured.json`
- `build/asc_counter_host_20260915/analysis_reserved96_v1/summary.json`

### Host 诊断值

| C=10000 Host (s) | A | B | B/A−1 |
| --- | ---: | ---: | ---: |
| AB | 10.427 | 10.050 | −3.6156% |
| BA | 10.383 | 10.204 | −1.7240% |
| pooled | 10.405 | 10.127 | −2.6718% |

对应step wall为10.30559→10.03568 s（−2.6190%）；两序方向一致。辅助诊断值中，
`eval_part_max`为281.477→244.645 us/step（−13.0852%），global-update wall为
172.215→165.382 us/step（−3.9673%），instructions为303.663e9→286.589e9
（−5.6226%）。这些数值只说明当前样本观察到的方向，不替代质量gate。

### 证据质量与限制

AB中B/C=10000触发`runtime_guard_min_idle`和`runtime_unexplained_target_busy`；
BA中B、A两个C=10000均触发`page_placement_emu_insufficient_samples`、
`page_placement_nemu_insufficient_samples`、`runtime_unexplained_target_busy`和
`runtime_worker_binding_insufficient_samples`。因此分析器结果为
`evidence_quality=invalid_evidence_retained_without_selection`、
`formal_acceptance=false`。页面局部性在BA各只有2个合格观测（要求3个），不是模型功能失败。

结论：本次保留的AB/BA诊断数据表面上显示B的Host约减少2.67%，但由于四个性能样本
没有全部通过运行时门禁，**不能宣称counter打印修改已带来可靠Host加速**。需要真正独占
96–127及其SMT siblings、完成page/worker连续观测后，使用新的pair-id重做AB/BA；
两臂ELF无需重新编译。此前每次小步骤不再拆分新文档，后续结果继续追加本主题。

## 4. 计量口径与同步机制补充（2026-09-16）

按用户后续要求，本主题继续集中追加；新的未通过性能结果不保留、不记录，
已有历史记录不追溯删除。以下仅记录代码机制与计量方法，不新增性能结论。

### CPU 利用率的解释

legacy 调度器的 `phase_worker_loop_` 在无任务时通过 `condition_variable::wait`
睡眠；`run_phase_workers_` 发出各分区任务后，主线程等待所有 worker 的
`completed`。小分区先完成后会等待下一阶段，因此 N=K=32 不代表 32 个核始终忙碌。
主线程 CPU%、单个 worker CPU%、整个进程线程合计 CPU% 不能混用。

此前 AB/A 原始 perf 明确报告 `12.159 CPUs utilized`，约为 32 核容量的 38.0%。
这个值只用于说明该样本的整体利用率，不作为优化效果证据；也不应用进程全程
`task-clock` 除以范围略有不同的日志 Host 时间来替代同窗口的 perf 利用率。

### 对原外部负载推断的勘误

`runtime_unexplained_target_busy` 是 `/proc/stat` 忙碌时间与 perf `task-clock`
之差超过门槛，**不能据此直接断言有其他用户占用了目标核**。
`ps` 的 PSR 是最近运行 CPU，累计 CPU% 也不是当前时间窗占用；应结合当前逐线程
affinity 与时间差分，不能用陈旧 PSR 归因。本节收窄第 3 节“需要真正独占”的表述：
此前门禁失败尚不足以证明预约核心不独占。

### 当前计量实现状态

新采样器把模型页面/绑核快采样与全机任务慢扫描分离；最低 idle 门槛按用户授权从
95% 调为 93%，平均 idle 门槛仍为 98%。原有冻结采样器和两臂 ELF 不改动。
`build/asc_counter_host_20260915/measurement_v4/` 是进一步核实 CPU 计账的实验候选，
其目录内 82 项单元测试通过，但**尚未完成真实仿真的计量资格验证**，不能据此接受性能样本。

候选额外采集 `/proc/schedstat` v15 的逐 CPU 纳秒运行计数，保留原 `/proc/stat`
诊断值。由于该计数在任务切出时结算，端点在 Host 计时区间外逐核短暂迁移并恢复
monitor affinity，以避免遗漏结束时仍在运行的外部任务；端点开销不从残差扣除，
也不增加原 `max(0.05 s, elapsed * 0.005)` 的残差容忍量。
参考：[Linux 调度统计文档](https://www.kernel.org/doc/html/latest/scheduler/sched-stats.html)、
[Linux 6.8 切换记账实现](https://github.com/torvalds/linux/blob/v6.8/kernel/sched/stats.h)。

受控的忙循环、睡醒循环、短暂/持续外部任务注入用于验证检测方向；另用现成的
`perf bench sched pipe` 对比同核与跨核唤醒，确认不能仅凭低利用率解释残差，
高频跨核睡醒下不同计数来源仍不可直接当作等价 CPU 时间。后续须先解释该口径差异，
不得调大容差吸收它，也不得将计量修正视为已经取得 Host 加速。

## 5. 探索性 AB/BA 结果（2026-09-16）

用户明确调整目标：当前仅为早期探索，不再要求严格保证核空闲。因此本节覆盖第 4 节
“先解决计账再继续”的执行前置要求，暂停深入计账修正，使用新的
`measurement_v5/`、`--policy exploratory` 完成固定 AB→BA。
CPU admission、SMT idle、外部任务及 `/proc/stat` 残差改为显式告警，仍保留原始值和
strict/diagnostic verdict；功能、输入/产物身份、页面局部性、worker 绑核仍为硬检查。
不启用 v4 的 scheduler 计账候选与端点迁移，不修改任何冻结版本或 A/B ELF。

### 配置与保留范围

- node030，N=K=32，CPU96–127，NUMA1，monitor0，legacy/push，identity worker-to-part。
- A 为原 `next_counter` 打印；B 为 `counter` 打印，保留此前说明的当拍打印语义差异。
- 每序 C100 两臂 canary 后执行 C10000 两臂；21:50–21:51 完成一个完整 AB/BA pair。
- 首个预定 pair 即完成，未按 Host、空闲度或计账告警挑样/重抽；原始 8 次 launch 全部保留。
- 59 项测试通过；独立分析重算功能、身份、页面、绑核和探索性 verdict，状态为
  `balanced_exploratory`，`formal_acceptance=false`。
- 117 份 native/helper 与 64 份 Verilator include 前后身份一致；12 个 staged inode 独立。
  四个性能样本有 9–10 个完整 worker 观测，EMU/NEMU 各有 9–10 个合格页面观测，
  观测到的 executable resident pages 均位于 NUMA1。

### Host 与辅助指标

| C=10000 Host (s) | A | B | B/A−1 |
| --- | ---: | ---: | ---: |
| AB | 10.444 | 10.134 | −2.9682% |
| BA | 10.345 | 10.196 | −1.4403% |
| 两序平均 | 10.3945 | 10.1650 | −2.2079% |

辅助指标：step wall 10.29097→10.06969 s（−2.1502%）；
`eval_part_max` 282.074→247.352 us/step（−12.3097%）；
实际 part-eval phase wall 326.779→319.986 us/step（−2.0788%）；
instructions 303.618e9→286.459e9（−5.6515%）。global-update wall 平均下降约 1.54%，
但 AB/BA 分别为 −4.57% / +1.56%，不据此认定通信阶段获得稳定改善。
`eval_part_max` 是各分区平均值的最大值，不是逐 step 临界路径的直接观测。

环境告警未被掩盖：三个性能样本的 admission 最低 idle 为 0%；AB 运行期有 SMT idle
及外部任务告警，四个样本都有原计账残差告警。这些不再阻塞本阶段，但意味着约 2.2%
不是精确、无干扰的加速估计。两序 Host 方向一致，**早期结论是修改有小幅收益迹象，
ASC/eval 的下降没有等比例转化为 Host 收益**；后续探索优先看阶段调度与同步尾部，
不再为本轮深入打磨 CPU 计账。

### 产物

以下路径均相对仓库根目录：

- `build/asc_counter_host_20260915/runs/counter-exploratory-ff6af223af48-1-ab/captured.json`
- `build/asc_counter_host_20260915/runs/counter-exploratory-ff6af223af48-1-ba/captured.json`
- `build/asc_counter_host_20260915/analysis-counter-exploratory-ff6af223af48-1/summary.json`
- 同一 analysis 目录的 `comparisons.csv`、`retention.json`。

## 6. 最大分区收益未转化为 Host 收益的原因（2026-09-17）

本节继续使用探索性口径。先重算第 5 节无新增 probe 的原始 AB/BA，再增加两组独立的
诊断 AB/BA；两组诊断均为 node030 CPU96–127、N=K=32、legacy/push。
**主要定位到 eval 的延迟派发：主线程与 worker 共用核心，唤醒同核 worker 时主线程
可能暂停运行，后续 partition 整批延迟开工。** update 的关键分区还从较早派发的位置
移到了编号 30，计算变短并未等比例缩短最后完成时间。

### 6.1 原性能样本：损失发生在 phase 内部

原始性能数据仍以第 5 节为准；每样本 20102 steps，两序原始总量平均。

| Host 时间组成 / s | A | B | B−A |
| --- | ---: | ---: | ---: |
| input load | 0.281183 | 0.249447 | −0.031736 |
| eval phase wall | 6.568912 | 6.432359 | −0.136554 |
| update phase wall | 3.440874 | 3.387888 | −0.052986 |
| Host−step | 0.103533 | 0.095307 | −0.008226 |
| Host | 10.394500 | 10.165000 | −0.229500 |

外层 Host−step 仅约 1%，不是收益损失的主要位置。最大 partition 平均 eval 从
282.074 降到 247.352 us/step（−34.722），实际 eval wall 却仅从 326.779 降到
319.986（−6.793）；两者差额从 44.705 增至 72.634 us/step。该差额含派发、唤醒、
等待、计时边界遗漏和逐步波动，不能直接命名为纯 barrier 时间。

还需区分三层量：重建后最大分区 ops 608762→447447（−26.50%）是静态计数；
实际最大分区平均 eval 只下降 12.31%；整个 Host 下降 2.21%。不同算子的执行代价、
动态触发和访存行为不同，静态 ops 比例本来就不是运行时间比例。

### 6.2 第一组诊断：主要是晚开始，不是“平均数掩盖了更大的逐步最大值”

对两臂只重编 common 并重新链接，复用各自原模型对象，保持 ABI、编译/链接选项、
分区和调度行为不变。沿用原同步事件 probe，但固定每 **17** steps 采样一次，从 step1
开始，避免旧 stride16 只采到同一时钟边沿。每个长样本 1183 个完整事件记录，覆盖
奇偶两类 step；调用路径为 clock1→step、clock0→step，因此奇数 step 对应上升沿。

每步按最后 eval_end 选择实际 critical lane（“最后完成者”，不是固定 partition），
分解 dispatch→其开始 + 其执行本体。下表只比较同一诊断版本，单位 us/step：

| 实际 eval 关键路径 | A | B | B−A |
| --- | ---: | ---: | ---: |
| critical lane 开始偏移 | 25.662 | 65.255 | +39.594 |
| 该 lane 执行本体 | 287.136 | 246.410 | −40.726 |
| dispatch→最后 eval 完成 | 312.798 | 311.665 | −1.133 |

AB/BA 的开始延迟分别增加 43.758 / 35.429 us，方向一致。
`mean(每步最大本体)` 为 287.336→251.786 us，`max(各 lane 平均本体)` 为
284.081→250.836 us；两者差额反而从 3.256 降至 0.950 us。因此本轮数据不支持
“新版本只是逐步最慢 partition 更频繁切换、被平均数隐藏”为主要原因。

延迟集中在上升沿：critical 开始偏移 24.761→97.356 us，而本体 409.053→365.798 us，
上升沿 eval 完成反而从 433.814 延后到 463.153 us；下降沿则 191.577→159.921 us。
B 的上升沿 95.52% 采样由 part_11 最后完成，尽管全程平均 eval 最大者是 part_7。
同一组 probe 里 update critical lane 从 A 的 part_11（97.38%）变为 B 的 part_30
（98.86%）；critical update 本体 116.518→86.318 us，但从 eval 完成到它开始的延迟
61.441→75.874 us。分区编号跨 A/B 不代表相同逻辑集合，这里讨论的是派发位置。

### 6.3 第二组诊断：延迟主要发生在主线程还没派发到关键 worker 时

在另一组独立 probe 中增加 host 的逐 lane 加锁前、解锁后/notify 前、notify 返回后三个
时间点，以及整轮 dispatch 的线程 CPU 时间和 notify 前后当前 CPU。所有额外查询只在
stride17 采样步进行，host 数据与 worker 事件槽分离；没有修改锁、条件变量或派发顺序。

| eval 派发诊断 / us | A | B | B−A |
| --- | ---: | ---: | ---: |
| 派发全部 32 个 worker 的 wall | 59.375 | 83.957 | +24.581 |
| 这段期间主线程 CPU 时间 | 56.002 | 52.093 | −3.909 |
| wall−主线程 CPU（未运行时间近似） | 3.373 | 31.864 | +28.490 |
| 所有 lane 的加锁/设标志/解锁段合计 | 3.342 | 3.056 | −0.285 |
| critical lane 收到派发前的偏移 | 14.987 | 52.515 | +37.528 |
| critical lane 从 notify 前打点到开始 | 13.964 | 17.314 | +3.350 |

critical 开始总延迟增加 40.877 us，其中约 92% 落在主线程尚未派发到该 lane 的区间。
`notify` 前打点在解锁之后，因此少数 worker 可先于该打点启动；分析保留负差值，不截断。
上述 CPU 差值用于区分派发中的运行/暂停，不用于重新进行外部负载计账验收。

同核唤醒是最明确的关联：eval 中跨核 notify 平均 A/B 为 1.497/1.365 us，基本不变；
唤醒与主线程当前 CPU 相同的 worker 时为 4.297/34.181 us。B 的 2367 次同核通知中有
896 次超过 20 us，而 73345 次跨核通知仅 4 次超过 20 us。B 有 897 次在 notify 返回前，
被唤醒 worker 已完整执行完本步 eval；A 仅 19 次。

具体可复核例子：第二组 BA/B 的 step171，host 在 CPU96 通知 part_0，notify 前/后偏移
1.990/92.941 us；part_0 在 6.840 us 开始、86.321 us 结束。约 91 us 的通知区间内，
同核 worker 已完成约 79.5 us 的计算，而后续 31 个 worker 尚未派发。

原调度代码 `run_phase_workers_` 按 workerIndex=0..31 串行设标志并 `notify_one`，
之后逐个等待 `completed`；32 个 worker 固定绑在 CPU96–127，host 也允许在这 32 核
上运行。因此 N=K=32 仍包含额外一个负责派发的主线程。时间戳、同核关系与 CPU 时间
共同强支持“唤醒同核 worker 后 host 被切出，拖延后续派发”的机制。尚未采集内核
调度栈，不能细分每次 notify 内的调度路径，也不把该现象归因于其他用户。

### 6.4 结论与下一步

当前主要问题已经从“最大逻辑锥是否变小”推进到“计算缩短能否兑现为共同的完成时间”。
对本例更有解释力的量是 `max(开始偏移_i + 本体耗时_i)`，而非仅 `max(本体耗时_i)`。
下一轮优先做小范围因果对照：

1. 在保持 partition→CPU 不变的前提下，独立调整 eval/update 的**派发顺序**，优先通知
   各阶段关键重分区；这样不会把 CPU 位置变化与通知顺序混在一起。
2. 单独验证 host 与 worker 同核竞争：可用额外 host 核做机制对照（明确增加了一个
   可用核，不能冒充同资源加速），或在既有 32 核资源内研究先批量发布再执行的调度。
3. 证据支持后再考虑替换每阶段逐个 sleep/wake 的方式，不直接把之前较慢的 pipeline
   方案当成已验证改进。分区器后续目标也应考虑两个时钟边沿与派发位置。

本轮只增加诊断产物，没有修改生产 runtime 或推广优化。两组共 16 次预定 launch 均通过
探索性功能/身份/页面/绑核检查，事件完整性与时间顺序通过，环境告警完整保留；两臂各自
复用模型对象 A=1422、B=1384，原模型与 native/helper/Verilator 来源未变。新增分析器
3+2 项针对性测试通过，host collector 自测通过。**probe 有扰动，本文两组诊断数值不与
第 5 节无 probe Host 值相减、不合并计算加速；性能结论仍是第 5 节约 2.21% 的探索值。**

诊断产物（相对仓库根）：

- `build/asc_counter_host_20260915/sync_diagnosis_20260917/analysis/summary.json`
- `build/asc_counter_host_20260915/dispatch_diagnosis_20260917/analysis/summary.json`
- 对应目录的 `spec.json`、`build_probes.py`、两臂 `build-manifest.json` 与 analyzer。
- 原始 capture：`build/asc_counter_host_20260915/runs/counter-sync17-20260917-{ab1,ba1}/`
  及 `counter-dispatch17-20260917-{ab1,ba1}/`，每目录的 `captured.json` 和原始 `.log`。

## 7. 单步仿真时空图（2026-09-17）

为把上述“关键分区计算变短、但开始派发变晚”的现象放到同一时间轴上，新增了单步交互图。
每一行是一个实际线程：Host 行显示两轮串行派发，worker 行显示 `eval`、`update` 以及其间的
墙钟空档；悬停可查看精确起止和耗时，页面还提供 32 个 worker 的逐行表、Host 每次通知明细
和 CSV 导出。A/B 使用同一相对时间原点和同一横轴，可切换四组诊断样本的所有实际采样步。

默认展示 `BA / step 171`，因为它直观呈现 B 的同核通知：Host 在 CPU96 通知 `part_0` 的跨度
为 1.990–92.941 μs，而 worker 0 在 6.840–86.321 μs 已完成 eval；这只是机制示例，不是平均
或典型性能。页面另提供 step 2925（上升沿）和 11102（下降沿）快捷入口。静态 PNG/SVG 也
一并输出，便于直接查看。

时间线的范围是 `dispatch_begin`（开始派发 normal_eval）到 `host_return`（normal_update
全部汇合结束），不含之前的 input load、空 early phases、外层 Host 工作和之后的 probe 缓冲
复制。奇数 step 是本次运行的 clock=1，偶数 step 是 clock=0；一个完整硬件周期要调用两个
step。灰色只表示 callback / 派发之外的时间（等待、调度、框架等），不能等同 CPU 空闲；彩色
`eval`/`update` 和橙色 notify 也是墙钟区间，可能包含线程被停调。当前没有 sched_switch 轨迹，
因此图不会把这些区间命名成更细的内核状态。

产物（相对实验目录 `build/asc_counter_host_20260915/timeline_20260917/`）：

- `timeline.html`：离线可打开的交互图，数据和字体已内嵌；
- `timeline_ba_step171.png` / `.svg`：默认机制示例；`timeline_ba_step2925.*`、
  `timeline_ba_step11102.*`：两个实际对照步；
- `timeline_ba_step171.csv` 等：逐区间数据；`manifest.json`：四组日志 SHA256、采样数量
  和验证状态；`plot_timeline.py`：可复生成器。

生成前重新通过已有 host-dispatch analyzer；四组各 1183 个采样步、共 151424 条 worker 时间线，
所有区间求和闭合，原始日志 SHA256 与 capture 中记录一致。该图是诊断 probe 的可视化，保留
probe 扰动限制，不替换第 5 节无 probe 的 Host 性能结论。

## 8. Host/worker 竞争的分步优化（2026-09-17）

沿用用户授权的探索性口径，在 node030 CPU96–127、NUMA1、N=K=32 上继续。固定 B 的
counter-print 模型、identity partition→CPU 映射和 push update；仅重编 common 调度封装，
复用原模型对象。Host 固定到较轻的 part_9 所在 CPU105，先分离验证通知顺序和 Host 参与：

| 对照 | A | B | 独立改变的因素 |
| --- | --- | --- | --- |
| 1 | Host 固定，原顺序通知 32 workers | 同核 lane9 最后通知 | 通知顺序；完成等待顺序保持不变 |
| 2 | 同核 lane9 最后通知 | Host 直接执行 lane9，31 后台 workers | Host 接管本地分区；仍为原独立锁/CV、两个阶段 |
| 3 | Host 参与，原独立锁/CV | Host 参与，epoch 发布与分散完成标志 | 阶段同步；短自旋后休眠，预算固定，不按成绩调参 |

每项预定执行一次 AB→BA，包含各臂 C100 功能检查和 C10000 性能样本；不因性能快慢重抽。
最后对有收益的候选与原冻结 B/legacy 做单独 AB→BA，给出端到端 Host 收益。阶段 1–3 使用
同一实验 ELF，避免模式间编译布局差异；最后对照明确包含完整调度改变。保留功能、输入身份、
页面放置和真实绑核检查，CPU 空闲及计账差额仅作环境告警。

实验目录为 `build/asc_counter_host_20260915/host_contention_20260917/`；运行时、构建器和
测量适配器均独立放置，原冻结源、ELF 和生产 runtime 不覆盖。配置日志区分计算 lane 数、
后台 worker 数、Host 所在 lane/CPU 与通知顺序，避免把固定 Host 的 32-worker 模式误判成
31-worker 模式。用户要求的有效进展在本节追加，不为每次构建另建记录。

### 8.1 实现和分步结果

三项候选和最终端到端对照已完成，共 4 组 AB→BA、32 次预定 launch。**本节每组的 A/B
表示调度 control/treatment，两臂均使用 counter-print 的 B 模型，不是前文两个 RTL 版本。**
每组下表值为两序 C10000 Host 秒数的算术平均；各样本均 20102 steps、guest 10001 cycles、
458 instructions、terminal PC `0x800027c6`，功能、配置、输入身份、页面放置与绑核均通过。

| 独立对照 | A Host / s | B Host / s | B 相对 A | AB / BA 各自变化 |
| --- | ---: | ---: | ---: | --- |
| 固定 Host：原通知顺序 → 同核 worker 最后通知 | 9.5970 | 9.2110 | −4.02% | −4.50% / −3.54% |
| 同核最后通知 → Host 接管 part_9 | 9.0515 | 10.1080 | +11.67% | +12.18% / +11.16% |
| Host 接管：独立锁/CV → epoch 广播 | 10.0165 | 9.7155 | −3.01% | −2.87% / −3.14% |
| 原冻结 B/legacy → 固定 Host＋同核最后通知 | 10.0885 | 9.0625 | **−10.17%** | **−10.82% / −9.51%** |

最终保留的优选实验配置是 `legacy-last`，Host=CPU105、lane9 最后通知，仍有 32 个后台
worker；不是 Host 参与计算。最终直接对照 AB 为 10.137→9.040 s，BA 为 10.040→9.085 s。
完整收益包含固定 Host 位置及通知顺序，不能全部归因于“最后通知”；第一组才是单独通知
顺序的 4.02% 收益。不同组的环境和执行时刻不同，不把三组百分比串乘作为最终收益。

### 8.2 收益和回退发生在哪里

第一组只换通知顺序，eval max（各分区平均值的最大值）几乎完全不变：247.821→247.825 μs；
eval phase wall 却从 305.535 降到 285.595 μs/step，减少 19.940 μs。update wall 为
157.225→157.569 μs，基本不变。这与“计算没有变，但后续关键 worker 更早收到派发”一致。

最终原冻结 B 对优选配置的对照如下，单位 μs/step：

| 指标 | 原冻结 B/legacy | 固定 Host＋同核最后通知 |
| --- | ---: | ---: |
| input load wall | 11.309 | 10.898 |
| eval phase wall | 323.316 | 284.559 |
| eval max | 246.747 | 245.104 |
| eval wall−max 混合剩余量 | 76.569 | 39.455 |
| update phase wall | 162.771 | 152.250 |
| update max | 88.727 | 88.887 |
| update wall−max 混合剩余量 | 74.044 | 63.362 |

指令总量仅 −0.106%，上下文切换 −1.48%，迁核 8470.5→43 次；Host 收益主要体现为阶段
完成时间缩短，并非模型逻辑变少。上述 wall−max 仍包含派发、唤醒、包装间隙和逐步波动，
不命名为纯 barrier 时间；迁核减少也不单独作为因果证明。

Host 参与计算的结果没有支持此前“最值得保留”的预期。第二组虽然上下文切换减少 4.60%、
指令减少 1.01%，但 part_9 的 eval 均值 19.338→41.139 μs，update 15.392→24.529 μs，
input load 10.807→16.008 μs；eval/update 阶段剩余开销也增加。代码核对确认同一 lane9
调用同一模型 eval/复制函数，计时没有把外部派发和等待直接混进 callback；本轮未采缓存等
硬件事件，不能把这些变化直接认定为缓存污染或某种 Verilator TLS 开销。**暂不推广
Host 接管分区。**

第三组实现使用共享阶段编号（epoch）发布 eval/update，每阶段一次 `futex wake-all`，各
worker 的完成编号分别占独立 cacheline，由 Host 汇总。等待先固定自旋 10 μs，再休眠；
正常同步路径不使用全体共用的互斥锁，也没有 31 次逐 worker 的 update 通知。它把
update wall 从 175.539 降到 156.005 μs，但不能完全抵消 Host 参与的回退，而且 task-clock
增加 10.10%、指令增加 5.87%。因此本轮不选该候选。阶段重构还减少了每步两次 registry
查找，跨实现主要比较 Host/total-step，不把各阶段差额视为完全相同的计时边界。

### 8.3 产物、验证和复现

以下路径相对实验目录 `build/asc_counter_host_20260915/host_contention_20260917/`：

- 优选可执行文件 `builds/v2/emu`，SHA256
  `8ebfd1e3baf4dfe8298ef82b4cf82875dea20c0fe56497104fd2a184544c6ae2`。
- `builds/v2/build-manifest.json`、`reused-input-identities.json`：仅重编 common，复用原
  1384 个模型对象、32 个模型 archive，其余链接输入和编译选项保持原样；类头文件 ABI
  SHA256 为 `1ed40c98f569faa088877ba4c52318e807c1bc7ccff494860ca10acf7f419842`，与冻结源一致。
- `runtime/generate_runtime.py`、`runtime/legacy_scheduler.h`：模式生成与独立 worker 锁/CV
  调度；`team/team_runtime.h`：独立阶段广播候选。构建器为 `build_runtime.py`。
- `specs/v2/01-last.json`、`02-host.json`、`03-team.json`、`final-legacy-last.json`：已执行配置；
  `analysis/v2-01-last/`、`v2-02-host/`、`v2-03-team/`、`v2-final-last/`：对应汇总与 CSV。
- 原始 capture 在上一层 `runs/host-contention-v2-{01-last,02-host,03-team,final-last}-{ab,ba}/`。
  每个目录保留配置、perf、timing、页面和实际线程绑定证据；性能样本有 8–9 次完整绑定采样。
- `measurement/run_pair.py`、`analyze_pair.py` 是原 v5 的独立适配；`run_experiment.py` 负责
  固定 AB→BA、来源前后核验和失败测量清理，不按性能值重试。

并发 helper 的 1400 轮正常和 ASAN/UBSAN 检查通过；team 的多轮并发、ASAN/UBSAN 和 TSAN
检查通过，覆盖阶段间普通内存可见性、完整 update 后返回、异常停止回收与 Host lane 分配。
测量适配器 31 项测试通过。额外复核并修正了初始化注册失败时错误状态的生命周期，保证
先回收后台线程再释放状态。所有真实测量均使用修正后的 v2。

仍采用探索性口径：16 个性能样本均为 `balanced_exploratory` 证据组的一部分，环境空闲、
外部任务和 `/proc/stat` 计账告警保留且不阻塞；不宣称严格隔离或统计显著性。原冻结 A/B
ELF、模型对象、native/Verilator 来源未修改。暂未改生产 runtime 默认值。

在 node030 从仓库根复现最终对照，可使用新的、未占用的 tag：

```bash
python3 build/asc_counter_host_20260915/host_contention_20260917/run_experiment.py \
  --spec build/asc_counter_host_20260915/host_contention_20260917/specs/v2/final-legacy-last.json \
  --tag final-last-repeat-01
```

单独启用优选模式需要 32 核初始亲和掩码 `96-127`、`XS_EMU_THREADS=32`、
`WOLVI_REPCUT_RUNTIME_MODE=legacy-last` 和 `WOLVI_REPCUT_HOST_LANE=9`；Host 在模型和
辅助线程初始化后固定到 CPU105，后台 partition→CPU 仍为 part_i→CPU(96+i)。

### 8.4 方案一实现前后的时空图

针对“固定 Host＋同核 worker 最后通知”补采逐线程时间戳，提供两种对照：`full` 为
`legacy → legacy-last`，包含 Host 固定与通知顺序两项改变；`order-only` 为
`legacy-pinned → legacy-last`，两边 Host 都固定 CPU105，仅改变通知顺序。
两边都是同一个带 probe 的实验 ELF、同一 counter-print 模型和分区，仍为 32 workers＋Host。
其中 `full` 的 A 用 legacy 模式复现原调度语义，Host 可在 CPU96–127 迁移，并非直接运行
旧冻结 ELF。原无 probe 的 −10.17% / −4.02% 仍是相应性能结论，不用图中数值替换。

在 node030 预定各执行一次 AB→BA，共 16 次 launch，均通过功能、输入身份、页面和真实
绑核检查；环境告警保留、不据此重抽。每 17 steps 采样一次，8 个 C10000 运行各有 1183
个完整采样步，共 9464 条 Host、302848 条 worker 时间线；C100 检查也验证了事件完整性。
所有 Host 事件按实际通知顺序 `0..8,10..31,9` 校验、绘制，不把 lane 编号当作时间顺序。

[离线交互图](../../build/asc_counter_host_20260915/host_contention_20260917/timeline_probe_20260917/visual/timeline.html)
可切换两种对照、AB/BA 和全部采样步，放大横轴、悬停查看每段起止，并导出完整区间 CSV。
静态图每组提供上升沿、下降沿各一个实际样本：固定使用 BA，在同奇偶全部候选中，最小化
`|A窗口−A中位数|/A中位数 + |B窗口−B中位数|/B中位数`，平局取较小 step。
不按收益选样、不剔除异常值，也不拼接出“平均时间线”。

| 对照 / 时钟沿 | PNG（同目录另有 SVG、CSV） | A 窗口 / μs | B 窗口 / μs |
| --- | --- | ---: | ---: |
| 完整方案 / 上升沿，默认 | [step 18395](../../build/asc_counter_host_20260915/host_contention_20260917/timeline_probe_20260917/visual/timeline_full_ba_step18395.png) | 621.076 | 565.556 |
| 完整方案 / 下降沿 | [step 12428](../../build/asc_counter_host_20260915/host_contention_20260917/timeline_probe_20260917/visual/timeline_full_ba_step12428.png) | 338.483 | 329.943 |
| 仅通知顺序 / 上升沿 | [step 2551](../../build/asc_counter_host_20260915/host_contention_20260917/timeline_probe_20260917/visual/timeline_order-only_ba_step2551.png) | 657.567 | 626.626 |
| 仅通知顺序 / 下降沿 | [step 3078](../../build/asc_counter_host_20260915/host_contention_20260917/timeline_probe_20260917/visual/timeline_order-only_ba_step3078.png) | 377.954 | 355.444 |

默认图中，A 的 Host 在 CPU99 通知同核 part_3，橙色跨度为 4.650–57.270 μs，其中
part_3 的 eval 在 9.500–51.760 μs 完整执行；这与 Host 被同核 worker 暂停的机制一致。
B 最后通知 CPU105 上的 part_9，跨度仅 2.920 μs。两侧最终控制 eval 完成的都是 part_11：
开始时刻 86.840→35.640 μs，本体 344.164→351.684 μs，完成时刻 431.004→387.324 μs。
因此这个样本的主要变化是计算条开始得更早，并不是最长计算条明显变短。

纯通知顺序的 step 2551 则更直接：A 通知 part_9 的跨度为 14.820–60.880 μs，part_9
在 20.470–55.480 μs 执行 eval，之后才继续派发 part_10 等线程；B 把 part_9 留到最后，
其通知跨度 41.260–43.860 μs。part_10 的启动由 78.550 提前至 31.340 μs，part_11
由 79.701 提前至 31.270 μs。方案一使后面的分区免受中途同核通知停顿的连带影响；
它不保证每一步都更快，也不保证同核通知永远不会暂停 Host。

全采样中，完整方案的逐步最长 eval 均值为 250.740→251.739 μs，而所有 workers 启动
完成的偏移为 105.465→59.545 μs，eval 全体完成偏移为 315.654→278.463 μs。
“最后完成者的本体均值”不能替代固定分区计算量比较：最后完成者身份也在变化。
纯通知顺序这组的 Host eval 派发跨度为 67.182→49.959 μs，所有 workers 启动完成
偏移为 85.538→65.024 μs；但其 eval 本体在 AB/BA 中波动方向不同，采样窗口的总变化
也不一致。因此这一组只用于展示派发和启动机制，不据此新增总体加速结论。

图的窗口仍为 normal_eval 派发开始到 normal_update 汇合结束，不含 input load、外层
Host 工作和 probe 缓冲复制；一个 step 是半个硬件周期。蓝/绿 callback 和橙色通知均为
墙钟跨度，可能含停调；灰色表示未细分的等待、调度或框架时间，不等同 CPU 空闲。
probe 未改变原 worker 锁范围和同步轮次，但采样与未采样步都有额外记录/分支开销。

新增产物集中于 `build/asc_counter_host_20260915/host_contention_20260917/timeline_probe_20260917/`：
`build_probe.py` 和 `builds/v1/build-manifest.json` 记录仅重编 common、复用 1384 个模型
对象的来源；`probe/` 为时间戳插桩，`specs/v1/{full,order-only}.json` 为运行配置；
`analysis/{full,order-only}/` 为独立事件分析，`analysis/selections.json` 及
`analysis_tools/select_examples.py` 记录选样规则、精确分数和来源 SHA；`visual/` 保存
可复生成器、HTML、PNG/SVG/CSV 与 manifest。原始 capture 位于
`build/asc_counter_host_20260915/runs/host-contention-timeline-v1-{full,order-only}-{ab,ba}/`。

绘图前的事件与区间闭合检查、离线浏览器检查均通过；浏览器覆盖两种对照和 AB/BA 切换，
默认 CSV 的 714 个区间覆盖两侧共 66 个线程且各自闭合，无脚本错误或外网请求。四张静态图
已目视检查；验证结果在 `visual/browser-validation.json`，产物 SHA 在 `visual/manifest.json`。

### 8.5 Host 参与回退的进一步诊断（2026-09-17）

本节比较仍是 `legacy-last → legacy-host`：Host 均固定 CPU105，前者保留同核 worker9，
后者由 Host 接管 part_9。原无 probe 的 Host 增量为 1.0565 s（9.0515→10.1080 s，
+11.67%），按 20102 steps 可闭合分为 input load +0.10456 s、eval +0.37419 s、
update +0.51676 s，以及 Host−step +0.06099 s。不能把 part_9 的增加直接加到关键路径，
因为它与其他 31 个分区并行。

代码核对：两模式先按同一顺序派发其他 31 个分区，之后分别通知 worker9 或直接调用
`run_phase_batch_(phaseFns,9,32)`；Host 接管模式在本地 callback 结束后才开始逐 lane
收集完成状态。两边使用相同的 part_9 eval/update 代码，模型内部 `threads()=1`，没有
新增 Verilator 子任务；原 part9 eval 计时仅包围模型 `eval()`，没有混入派发和等待。
input load 在派发之前独立计时，统计槽仍为同一 `[9][9]`、64 字节对齐，registry 查询
次数也相同。因此没有发现重复计算、统计假共享或计时范围变化可以解释回退。

为区分执行与停调，新增隔离的 wall/CPU probe，仅重编 common、复用全部 1384 个模型
对象和原 ABI；每 17 steps 同时记录 Host input、派发、汇合，以及 32 lanes 的 eval/update
墙钟和 `CLOCK_THREAD_CPUTIME_ID`。node030 预定 AB→BA 的 8 次 launch 均通过功能、
身份、页面和实际绑核检查，四个长测各有 1183 完整采样步。带 probe 的整跑 Host 为
9.108→10.119 s（+11.10%，两序 +11.36% / +10.84%），复现回退，但不替换原无 probe 数值。

下表为这次 probe 的实际采样均值，单位 μs；A 为同核最后通知，B 为 Host 参与：

| 区间 | A 墙钟 | B 墙钟 | A 线程 CPU | B 线程 CPU |
| --- | ---: | ---: | ---: | ---: |
| part_9 eval callback | 20.182 | 34.491 | 20.883 | 35.613 |
| part_9 update callback | 14.810 | 20.418 | 15.176 | 21.489 |
| Host input load | 11.003 | 14.130 | 11.617 | 15.231 |
| Host eval 派发 | 39.670 | 51.209 | 39.269 | 52.271 |
| Host update 派发 | 40.141 | 52.099 | 40.754 | 53.167 |

增加的是执行中的 CPU 时间，不能主要解释成被停调。CPU 时钟的采样范围略包围墙钟
范围，故小幅 CPU>wall 是端点计量差，保留原值，不算成负等待。特别是 Host 每阶段少发
一次通知，派发 CPU 时间反而增加约 12–13 μs；异常沿整个 Host 执行路径出现。

阶段时序给出了更具体的传播路径。update 墙钟增加 16.081 μs，可精确分解为最终完成
worker 启动更晚 +13.798、本体 −0.436、最后 callback 结束到 Host 返回 +2.718 μs。
eval 增加 27.859 μs，则为关键启动 +8.059、本体 +13.577、收尾 +6.223 μs。
因此收尾延迟确实存在，但 update 主要败在启动晚。2366 个 B 采样中，part_9 的 eval
从未最后完成，update 仅一次最后完成；它平均仍比该阶段最晚 callback 早完成
211.878 / 82.316 μs。**“Host 接管 part_9 后，本地计算直接堵住阶段结束”不符合这些样本。**

回退还有明显的 CCD 局部性。Host 所在 CPU104–111 的另外 7 个 worker（part8、10–15）
eval 线程 CPU 时间总和 822.414→916.322 μs（+11.42%），update 总和 +12.29%；其他
24 个 worker 对应仅 +0.90% / +0.29%。part11 eval CPU 增加 19.921 μs，而 part7 仅
+0.543 μs。应继续区分同 CCD 的频率和共享资源影响，不能只归因于 Host 的栈/TLS 切换。
旧测和本轮 CPU105 的 SMT 兄弟 CPU297 均未观察到忙碌，辅助线程也未消耗采样 CPU ticks；
当前证据不支持将主要回退归因于 CPU105/297 上的外部任务。

诊断产物集中在 `build/asc_counter_host_20260915/host_contention_20260917/host_participation_probe_20260917/`：
`build_probe.py`、`probe/`、`builds/v1/build-manifest.json`、`specs/v1/host.json`，以及
`analyze_probe.py` 和 `analysis/v1/summary.json`。采集器真实并发 mock 与分析器 15 项
针对性测试通过；独立分析复核全部事件、时序、CPU 位置和日志 SHA。原始 capture 为
`build/asc_counter_host_20260915/runs/host-contention-host-wallcpu-v1-{ab,ba}/`。

随后对**原无插桩 v2 ELF**执行一次独立 AB→BA，旁路读取 33 个逻辑 CPU 的频率报告值
（每 20 ms），同时用 CPU 级 `APERF/MPERF` 硬件计数器观察 Host 所在 CCD 和对照核
（每 100 ms）。全部 8 次 launch 通过，Host 为 8.9735→10.0305 s（+11.779%，
AB +11.847%、BA +11.712%）。只读监控绑 CPU0，未修改 governor、频率或调度参数。

去除每个长测首尾各 1 s，以累计 APERF 除以累计 MPERF，按 2.55 GHz 参考频率换算：

| CPU / 用途 | A 有效运行频率估计 / GHz | B 有效运行频率估计 / GHz | 比值变化 |
| --- | ---: | ---: | ---: |
| CPU105 / Host、part_9 | 3.606 | 1.894 | **−47.47%** |
| CPU103 / part_7，对照 | 3.606 | 3.610 | +0.11% |
| CPU104、106–111 / 同 CCD 其他 workers | 约 1.443 | 约 1.363 | 约 −5.6% |
| CPU120、127 / 其他 CCD 对照 | 约 1.460 | 约 1.452 | 约 −0.55% |

CPU105 的原始 APERF/MPERF 为 1.41416→0.74288；分序估计 AB 3.604→1.795 GHz、
BA 3.608→2.000 GHz，完整窗口与去除边界后的结论一致。sysfs 报告也支持这一差异：
A 的 717 个内部窗口样本全部超过 2.8 GHz，B 的 823 个样本没有一个超过 2.8 GHz。
sysfs 仅作辅证，不把它的报告值直接当作硬件周期测量；APERF/MPERF 也是 CPU 级而非
callback 专属计数。两事件无复用，perf 启动与 workload 的时钟对齐仍有毫秒级边界误差，
因此主结论使用去除首尾各 1 s 的稳定窗口。

这给出了此前 Host 路径普遍变慢的主要解释：**Host 接管后，CPU105 的实际执行频率
大幅下降，输入准备和通知循环一起变慢，后续 worker 更晚启动；同 CCD 其他核也出现较小
降频，进一步增加部分 callback 时间。**该频率比值对应等周期工作的耗时约变成 1.90 倍；
同一无插桩频率对照中的 part9 eval 为 19.125→34.963 μs，约 1.83 倍，量级吻合。
但不能据此给出 11.779% 回退的精确降频贡献，也不把其他未测缓存/内存因素全部排除。

33 核的 policy 元数据在开始和结束完全一致。CPU105 为 `acpi-cpufreq / schedutil`，
boost 开启；[Linux CPUFreq 文档](https://docs.kernel.org/admin-guide/pm/cpufreq.html#schedutil)
说明 schedutil 使用调度器的利用率估计。Host 与 worker9 合并会改变运行、睡眠和唤醒
节奏；它如何具体改变 governor 的估计仍属待验证机制，本轮未采 governor 决策轨迹。
应将“实际运行频率已不同”与“哪个调频分支导致差异”分开。下一步评估 Host 参与本身的
框架收益，应先控制并核验运行频率；本轮没有修改系统频率，也未据此推广或撤销生产实现。

旁路工具为同诊断目录的 `frequency_monitor.py`，产物在 `frequency/host-freq-v1/`：
`digest.json`、`msr-distributions.csv`、`frequency-bands.csv`、原始 `msr.tsv` 与
`samples.csv`、起止 policy 和 `run.json`；完整汇总为 `summary.json`。对应原始 capture
是 `build/asc_counter_host_20260915/runs/host-contention-host-freq-v1-{ab,ba}/`。

### 8.6 为什么 Host 参与后 CPU105 会降频（2026-09-18）

这一节进一步区分“观测到的频率差异”和“调频器为什么作出这个决定”。频率分析脚本及
逐采样结果在 `host_participation_probe_20260917/frequency_analysis/`，仍然是只读旁路
分析，没有修改 governor、频率上限或系统调度参数。

#### 观测事实

CPU105 使用 `acpi-cpufreq + schedutil`，可见状态为 1.5/2.0/2.55 GHz，boost 开启，
`schedutil/rate_limit_us=1000`。这里的 2.55 GHz 是 policy 的请求上限，不是 boost 后
硬件周期上限；`scaling_cur_freq` 主要是驱动报告的最近请求值，实际执行频率以 CPU 级
APERF/MPERF 为主。因此 A 中约 3.60 GHz 并不与 policy max=2.55 GHz 矛盾。

去掉每次长测首尾各 1 s 后，CPU105 的结果为：

| 对照 | A：legacy-last | B：legacy-host | 变化 |
| --- | ---: | ---: | ---: |
| AB，APERF/MPERF 换算 | 3.6037 GHz | 1.7951 GHz | −1.8086 GHz |
| BA，APERF/MPERF 换算 | 3.6084 GHz | 1.9997 GHz | −1.6087 GHz |
| B 的 sysfs 状态分布 | 内部样本全部高于 2.8 GHz | AB 约 63.6% 为 1.5 GHz，其余约 36.4% 为 2.0 GHz；BA 近似全为 2.0 GHz | 离散低 P-state |

这个差异具有局部性：CPU103 对照核仍为约 3.606→3.610 GHz；CPU104、106–111
同 CCD 仅约下降 5.6%；CPU120、127 其他 CCD 约下降 0.55%。因此不能解释成整机统一
热保护或整个节点同时被压低。CPU105 的 SMT 兄弟 CPU297 也没有忙碌迹象。CPU105
所属 `freqdomain_cpus=104 105`，但各 CPU 的 policy mask 独立；同 CCD 的小幅变化更像
共享功耗/boost 资源，不能解释 CPU105 的主效应。

#### 最可能的调频链路

Linux `schedutil` 不是按“进程累计用了多少 CPU 时间”调频，而是根据最近的调度器利用率
估计。PELT 对运行/可运行时间做指数衰减，半衰期约 32 ms；`UTIL_EST` 还会利用任务
近期唤醒前后的估计，调频请求受 1 ms rate limit 限制。其核心逻辑可概括为

```
最近的 rq/task utilization  ->  schedutil 请求 P-state  ->  ACPI/CPB 实际频率
```

A (`legacy-last`) 中 CPU105 同时有 Host 和 worker9 两个独立的 CFS 实体：Host 负责
派发/等待，worker9 被唤醒执行 part_9。即使单步总工作量不变，这两个实体的运行、睡眠、
唤醒交替会给同一个 runqueue 提供更密集的近期利用率/唤醒信号，实际结果是 CPU105 长时间
维持 boost 频率。

B (`legacy-host`) 删除了 worker9 这个实体，Host 自己执行 part_9，然后在阶段同步处
阻塞。它的单步 CPU 时间反而更高（Host step 线程 CPU 约 161.9→279.3 μs），但这不是
`schedutil` 所直接使用的量；单一实体的“短 burst→睡眠/等待→再唤醒”模式可能让 PELT/
`util_est` 在采样点低于高频阈值，调频器于是落到 1.5/2.0 GHz。低频又把同一段 Host
代码执行得更久，形成“利用率反馈偏低 → 低频 → burst 变长”的自增强回路。按文档中的
近似公式，policy 上限 2.55 GHz 时，1.9 GHz 大致对应 `u≈1.9/(1.25×2.55)=0.60`；
要直接请求上限则需要 `u≈0.80` 左右。这说明即使 Host 实际更忙，也可能没有跨过高频请求
阈值。

这是目前最符合数据的机制，但还不是内核级证明。我们没有权限读取 CPU105 runqueue 的
实时 `util_avg/util_est`，也没有拿到完整的 `sched_switch/sched_wakeup` 与
`power:cpu_frequency` 轨迹，所以不能断言究竟是 PELT 衰减、`UTIL_EST`、IO-wait 唤醒
boost，还是它们的组合。当前能确定的是：CPU105 的实际频率先发生了稳定、可重复的模式
差异，而 Host/part9 的 CPU 时间增加是该差异的结果之一，不是“CPU 更忙所以必然更高频”。

还要注意调频事件的相位：单步 Host wall 约 467/518 μs，而 governor 的 rate limit 是
1 ms，通常跨两步才有一次新的请求机会。A 中 worker9 的唤醒/通知可能恰好在窗口到点时
续上较高利用率；B 中 Host 的 dispatch、inline callback 和等待事件相位不同，可能留下
1.5/2.0 GHz 请求。这与“两个 CFS 实体提高利用率”和“rate-limit 下最后一次更新时机”
是同一条可证伪链，不能只看 CPU 总 busy 时间。

#### 下一步的最小证伪实验

不应直接把调频器现象硬编码进框架。最小代价的验证顺序是：

1. 在 B 中保留 Host 接管，但增加一个不执行 Verilator 的周期性空壳 CFS 线程，复现
   worker9 的唤醒/短 burst 节奏；若 CPU105 恢复到 A 的高频，说明“第二个调度实体”是
   主要触发因素，而不是 part9 的计算量。
2. 对 B 的 Host 临时设置 `uclamp.min=1024`，仅用于诊断；若 Host 时间和 CPU105
   频率明显回到 A 附近，说明低 PELT 利用率导致的 schedutil 请求是主因。该设置不能作为
   正式性能结果，因为它改变了运行时调度策略。
3. 采集权限允许时直接记录两种模式的 `se.avg.util_avg`、`se.avg.util_est.ewma`、
   `sched_wakeup` 和 `power:cpu_frequency`，把“请求低频”与“硬件在高请求下受限”分开。

官方背景：[schedutil 调速器文档](https://docs.kernel.org/scheduler/schedutil.html)说明
PELT、`UTIL_EST`、利用率到频率的映射及 rate limit；[CPUFreq 文档](https://cdn.kernel.org/doc/html/latest/admin-guide/cpufreq.html)
说明 schedutil 使用调度器利用率；[util clamp 文档](https://kernel.org/doc/html/latest/scheduler/sched-util-clamp.html)
说明 `uclamp.min` 可抬高调频利用率下界。上述实验尚未改变生产默认，也不据此声称已经
解决 Host 回退。

### 8.7 关于长期忙等待的判断（2026-09-18）

当前 `legacy` runtime 的空闲路径是纯 `condition_variable`：worker 在
`legacy_scheduler.h:83–99` 等待 `hasWork`，Host 在 `run_phase:140–167` 等待各 lane 的
`completed`。因此“长期保持 runnable”在机制上确实可能改变两件事：减少 park/wakeup 延迟，
并让 `schedutil` 持续看到高的近期运行利用率。

本工程已有一个相关但不等价的先验：`team-host` 使用 epoch 原子事件，先自旋 10 μs，
超时后才进入 futex；其 Host 从 10.0165 s 降到 9.7155 s，改善约 3.01%。但该实现同时
改成了 epoch 广播、futex wake-all 和汇总等待，不能把这 3% 全部归因于 10 μs 自旋。

如果接受专用核上长期占满 CPU、功耗不作为目标，建议把实验拆成三个独立变量：

1. **worker-only spin**：31 个后台 worker 永远轮询自己的 work epoch，Host 仍按原协议等待。
   这主要测试 worker 的唤醒延迟和各 worker 的频率，不能直接修复 CPU105，因为
   `legacy-host` 中 CPU105 没有 worker，只有 Host。
2. **host-wait spin**：Host 在等待其他 lane 完成时也持续轮询。它能直接保持 CPU105
   runnable，最有可能验证“低 PELT/schedutil 利用率导致降频”的假设；代价是约 46% 的
   Host 阶段等待时间会变成无效 CPU 时间。
3. **all-spin**：两者同时自旋；本节当时将其只视为极限诊断。该默认策略判断后来被
   8.11 的 walltime 优先决策取代。

实验应至少比较 `condition-variable`、10 μs、50 μs、200 μs 和无限自旋，记录 Host wall、
Host thread CPU、CPU105 APERF/MPERF、上下文切换及各阶段 wall。若 `host-wait spin` 使
CPU105 从约 1.9 GHz 恢复到 A 的约 3.6 GHz，且 Host wall 同步下降，就直接支持调频反馈
解释；若频率恢复但 wall 不降，说明等待/同步本身仍是主瓶颈；若频率也不恢复，则要继续
查 CPB/SMT 或其他硬件资源。

实现上不能只把 `cv.wait` 改成空循环：现有 `hasWork`、`completed` 受 mutex 保护，忙等
版本必须改成带 acquire/release 的 epoch/atomic 状态，并处理 stop、异常和 shutdown，最好
复用已有 `team_runtime.h` 的 cacheline 隔离、`PAUSE` 和 futex fallback。即使功耗不考虑，
也建议使用 `PAUSE` 而不是空指令循环，以减少对 SMT 兄弟和内存系统的无谓干扰。

### 8.8 Host-only 自旋实验结果（2026-09-18）

在独立目录 `host_spin_20260918/` 实现了 Host-only 等待策略：worker 仍使用原
condition-variable，Host 在每个 completion wait 中先轮询 `completed_fast`，使用
`PAUSE` 自旋到预算耗尽后再回到原 CV。`completed_fast` 由实际使用的 scheduler worker
loop 以 release store 发布，Host 以 acquire load 读取；`0` 保持基线，`infinite` 仅作
极限诊断。没有修改生产 runtime、RTL 或模型对象。

node029 的 CPU96–127、NUMA1 完成 4 个预算的 AB/BA；每个 pair 的 C100/C10000 四次
launch 均通过功能、输入、页面、线程身份和绑核检查。以下是两侧长测的 pooled Host 结果，
均为 exploratory，不能当作正式验收：

| Host spin 预算 | A：0 us / s | B：spin / s | B 相对 A | task-clock 变化 | 聚合平均 GHz 变化 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 10 us | 10.9265 | 10.7315 | −1.78% | +0.08% | +1.09% |
| 50 us | 11.2320 | 9.7250 | **−13.42%** | −0.17% | +6.28% |
| 200 us | 10.9645 | 9.4520 | **−13.79%** | +1.98% | +7.37% |
| infinite | 11.1395 | 9.6215 | **−13.63%** | +1.24% | +9.78% |

50 us 组的阶段指标也同步改善：eval wall `336.675→301.744 μs`（−10.38%），update
wall `199.681→167.328 μs`（−16.20%），eval critical max `258.885→250.556 μs`
（−3.22%）。这不是只减少某个 Host 统计项；关键路径和阶段尾部都变短，而 task-clock
基本不变。

另外用 CPU105 的 APERF/MPERF 做了独立 AB、BA 旁路采样，去除每个长测首尾各 1 s，按
2.55 GHz reference 换算：

| 顺序 | A：0 us | B：50 us |
| --- | ---: | ---: |
| AB | 约 1.59 GHz | 约 3.64 GHz |
| BA | 约 1.63 GHz | 约 3.63 GHz |

CPU105 的频率在两个顺序中都从低 P-state 恢复到 boost 区间，和 Host wall 的改善方向
完全一致。APERF/MPERF 是 CPU-wide 计数，不是 Host callback 独占测量；但 AB/BA 的
重复性足以支持“Host 自旋保持 runnable，阻止 schedutil 利用率反馈掉到低频”这一因果
解释。10 us 尚未稳定抬高频率，50 us 已经足够；继续增加到 200 us 或无限自旋没有额外
端到端收益，说明真正需要的是覆盖调频/唤醒窗口，而不是长期占满 CPU。

本轮当时因此不继续实现 worker-only 或 all-spin：它们不会直接作用于 B 的 CPU105，且会把
31 个等待 worker 的 CPU 时间全部变成无效 runnable work。当前最合理的后续方案是把
Host completion wait 做成可配置的 bounded/adaptive spin，预算先以约 50 us 为实验候选，
超时后仍回退 CV/futex；当时不把 infinite spin 作为默认实现。后续 8.9 的实测和 8.11
明确的 walltime 优先目标已取代这一阶段性默认选择。构建、spec、capture、分析和
CPU105 旁路文件均保留在 `host_spin_20260918/` 及同级 `runs/host-spin-v3-*`。

### 8.9 50 us 与 all-spin 对比实验（2026-09-18）

根据上一节当时的结论，隔离实验 runtime v5 将 `legacy-host` 在未设置
`WOLVI_REPCUT_HOST_SPIN_US` 时的默认 Host 等待预算设为 `50 us`；显式设置为 `0` 仍可
复现纯 condition-variable 对照。生产 emitter/runtime 未改默认。另实现了独立的
all-spin 诊断模式：Host 使用 `infinite`，31 个后台 worker 通过
`WOLVI_REPCUT_WORKER_SPIN_US=infinite` 永久轮询各自的 work flag；work/done/stop 均使用
acquire/release 原子标志，stop 路径仍会设置 CV 条件并 join，避免 shutdown 卡死。

v5 使用新日志字段显式记录 `wait_policy=host-spin|all-spin`、Host/worker spin 状态；只
重编译 common，复用原 1384 个模型对象。runtime 单测覆盖普通模式、Host 参与、异常 drain
及 stop/join，均通过。node030 的 CPU96–127、NUMA1 上以同一 `all-spin.json` 做 AB/BA，
每侧 C100/C10000 四个 launch 均 `captured accepted=True`；由于这是专门验证极限忙等的
探索性实验，仍不作为 formal acceptance。

对照为 A=Host-only `50 us`，候选为 B=Host+worker `infinite`。AB/BA pooled 结果如下：

| 指标 | A：Host 50 us | B：all-spin | B 相对 A |
| --- | ---: | ---: | ---: |
| Host wall | `8.9445 s` | `6.5750 s` | **−26.49%** |
| step wall | `8.8808 s` | `6.5200 s` | −26.58% |
| eval wall | `281.022 us` | `250.577 us` | −10.83% |
| eval critical max | `243.841 us` | `239.417 us` | −1.81% |
| global update wall | `149.313 us` | `63.259 us` | −57.63% |
| update critical max | `90.248 us` | `50.387 us` | −44.17% |
| perf task-clock（进程线程合计） | `121.377 s` | `210.698 s` | **+73.59%** |
| perf context-switches | `1,300,226` | `432.5` | **−99.97%** |
| perf cycles | `1.988e11` | `7.552e11` | +279.95% |
| perf instructions | `2.962e11` | `9.117e11` | +207.82% |
| 聚合平均 GHz | `1.638` | `3.584` | +118.88% |

这回答了“all-spin 是否节省线程唤醒/休眠开销”：是的，context switch 几乎消失，且
Host/worker 的阶段尾部明显变短；但它不是免费收益，task-clock 增加约 `89.3 s`，约等于
把 31 个原本可睡眠的 worker 长时间变成 runnable，并用更高频率运行 `PAUSE` 循环。关键
eval critical max 只改善 `1.81%`，而总 Host wall 改善 `26.49%`，说明主要收益仍来自
等待期间的调频与唤醒延迟，而不是 RTL callback 本身变快。all-spin 因而适合作为“可达到的
上界/因果诊断”。“不适合作为默认方案”的结论包含了 CPU 时间和功耗目标；8.11 在明确只
优化最终 walltime、CPU96–127 专用且不考虑功耗后，将该结论更新为 all-spin 默认。

本轮产物：`build/asc_counter_host_20260915/host_contention_20260917/host_spin_20260918/`
下的 v5 build/spec/analysis，以及 `runs/host-all-spin-v5-{ab,ba}/captured.json`。

### 8.10 未固定 Host 与 all-spin 的单步时空图（2026-09-18）

为直观看出 all-spin 缩短了哪一段时间，新增一套与旧时空图相同格式的稀疏 timeline
probe。A 为未固定 Host 的 `legacy`（worker 空闲时使用 condition variable），B 为
`legacy-host` 的 all-spin（Host 与 worker 都永久轮询）；两侧使用同一 counter-print RTL、
同一分区、同一 `N=K=32`，在 node030 CPU96–127 / NUMA1 上按 AB/BA 运行 C100/C10000。
四个 launch 的 `captured accepted=True`，probe integrity 通过，共得到 4,732 个 step 记录、
151,424 条 worker timeline。这个 probe 只用于观察事件结构，插桩会扰动时序，不能把图中
单步数值当作正式性能验收结果。

图中每个面板有一行 Host 和 32 行 `part_00..part_31`：蓝色是 eval 逻辑 callback，绿色是
update/跨分区复制，橙色是 Host 通知跨度，紫色是 Host 派发准备，灰色只是“没有被本 probe
标成 callback/派发”的墙钟区间，不等于 CPU 空闲。all-spin 的 Host 行 lane 9 是直接执行
Host callback 周围插入的观测区间；B 面板中原 `part_09` 行已标成 `Host lane / CPU105`，
不应误读成一个额外的 worker callback。

选取的是同一 BA 序列中、分别接近奇偶窗口中位数的真实 step，按规则选样，不是按收益挑选，
也不是总体平均时间线：

| step | A 未固定 Host 窗口 | B all-spin 窗口 | 关键可视差异 |
| ---: | ---: | ---: | --- |
| 3129 | `582.017 us` | `433.165 us` | 最晚 eval 从 `33.141 us` 提前到 `6.330 us`；eval callback 本体 `367.984→352.544 us`（−4.20%），update 最晚分区 `89.261→49.311 us`（−44.76%），最终结束 `568.237→431.795 us`。 |
| 18480 | `351.233 us` | `214.752 us` | 最晚 eval 从 `20.210 us` 提前到 `6.540 us`；eval callback 本体 `133.651→132.181 us`（−1.10%），update 最晚分区 `90.261→50.201 us`（−44.38%），最终结束 `337.823→213.312 us`。 |

因此时空图支持前面 Host/worker 自旋实验的解释：all-spin 的主要变化是 callback 更早开始、
update 汇合尾部明显收短，而 RTL eval 本体在 step 18480 几乎不变；它节省的是线程唤醒、
调度和低频等待造成的空档，不是把逻辑锥本身算得更少。图中 Host eval dispatch 的墙钟也没有
出现同量级变化（例如 step 3129 为 `42.731→42.140 us`），所以不能把收益简单归因于 Host
派发循环变快。

静态图（英文标签避免受限中文子集字体缺字）和交互版如下：

- [step 3129 PNG](../../build/asc_counter_host_20260915/host_contention_20260917/timeline_probe_20260917/visual/unpinned-vs-allspin/timeline_unpinned-vs-allspin_ba_step3129.png)
- [step 18480 PNG](../../build/asc_counter_host_20260915/host_contention_20260917/timeline_probe_20260917/visual/unpinned-vs-allspin/timeline_unpinned-vs-allspin_ba_step18480.png)
- [交互 HTML](../../build/asc_counter_host_20260915/host_contention_20260917/timeline_probe_20260917/visual/unpinned-vs-allspin/timeline.html)

原始数据、逐区间 CSV、选择记录和 manifest 均在
`build/asc_counter_host_20260915/host_contention_20260917/timeline_probe_20260917/`
对应的 `analysis/unpinned-vs-allspin/` 与 `visual/unpinned-vs-allspin/` 下。

### 8.11 all-spin 改为当前默认方案（2026-09-20）

当前目标明确为最小化最终 walltime；node030 CPU96–127 是本任务专用资源，功耗和额外
task-clock 不作为本阶段优化目标。因此采用 8.9 已验证的 all-spin 作为当前默认，而不再以
Host 50 us + worker condition variable 为默认。这个决定的适用范围是当前隔离的
`N=K=32` runtime：Host 占 lane 9 / CPU105，另有 31 个后台 worker，合计仍为 32 个
runnable 执行实体，不会在 32 个保留 CPU 上形成第 33 个执行实体。

`host_spin_20260918` 的 v6 生成器现在对 `legacy-host` 使用以下规则：

- 两个 spin 环境变量都未设置：Host 和 worker 均为 infinite spin，即 all-spin；
- `WOLVI_REPCUT_HOST_SPIN_US=50` 且 `WOLVI_REPCUT_WORKER_SPIN_US=0`：恢复上一候选的
  Host 50 us + worker CV；
- 两项都显式为 `0`：恢复 Host/worker condition-variable 等待；
- 显式值先清除各自默认值再解析，runtime 日志用 `host_spin_source` 和
  `worker_spin_source` 区分 `default` 与 `environment`。

同时修正了 Host 数值预算的上界检查：`1000000` 合法，`1000001` 及更大的十进制值会在
乘加前按无溢出的边界公式拒绝。v6 manifest 记录默认 `all-spin`、两个 override 环境变量及
CV 回退组合；旧 v5 二进制、manifest 和数据均未覆盖。

独立 C++ 测试覆盖默认解析、显式 all-spin、50 us/CV 与全 CV 回退、200 轮并发、Host 和
worker callback 异常 drain、worker 初始化失败及 idle shutdown/join。普通测试与
ASan/UBSan 通过；TSan runtime 在 node029 启动时因 `unexpected memory mapping` 退出，
未进入测试代码，因此不能把它记为 TSan 通过。

node030 CPU96–127 / NUMA1 上又以 A=显式 all-spin、B=默认 all-spin 做了一组 AB/BA
C100/C10000 等价性 smoke。八次 launch 均 `captured accepted=True`，B 的 runtime 日志
均明确记录：

```text
wait_policy=all-spin
host_spin_infinite=true, worker_spin_infinite=true
host_spin_source=default, worker_spin_source=default
```

长测 pooled 结果如下；两条路径的差异均处于运行噪声范围，说明默认配置没有额外开销：

| 指标 | A：显式 all-spin | B：默认 all-spin | B 相对 A |
| --- | ---: | ---: | ---: |
| Host wall | `6.814 s` | `6.801 s` | `−0.19%` |
| eval wall | `260.003 us` | `259.541 us` | `−0.18%` |
| update wall | `65.180 us` | `65.452 us` | `+0.42%` |
| perf task-clock | `218.347 s` | `217.889 s` | `−0.21%` |
| perf context-switches | `405.5` | `406.0` | `+0.12%` |
| 聚合平均 GHz | `3.494` | `3.495` | `+0.03%` |

v6 构建和规格位于 `host_spin_20260918/{builds,specs}/v6/`；默认等价性 capture 位于
`runs/host-default-allspin-v6-smoke-{ab,ba}/`，分析位于
`host_spin_20260918/analysis/v6-default-equivalence/`。这些仍是当前 XiangShan
`N=K=32` 专用 runtime 的 exploratory 证据；通用生产 emitter 还支持 `N<K`、可变 K 和
early phase，不能直接用硬编码 lane 9 的实验实现替换，故本轮没有把该专用实现冒充成通用
生产默认。

### 8.12 all-spin 通用实现落入 Wolvrix emitter（2026-09-20）

前面的 all-spin 已在固定 `N=K=32`、Host lane 9 的隔离 runtime 中验证。本轮将机制移入
`wolvrix/lib/emit/verilator_repcut_package.cpp` 的通用 Verilator RepCut package 生成器，边界
刻意保持保守：令 `N=XS_EMU_THREADS`、`K=RepCut partition count`，只有 `N=K>=2` 默认启用
Host 参与和 all-spin；`N<K` 继续使用原有 N 个后台 worker＋condition variable，`N<=1` 继续
串行。这样 N=K 时仍只有 N 个 runnable 实体：Host 接管一个逻辑 lane，后台只创建 N−1 个
worker，不再产生原先的 N+1 个实体。

通用实现不再硬编码 32 路、空 early phase 或 CPU105：默认 Host lane 为 `min(9,N−1)`，可用
`WOLVI_REPCUT_HOST_LANE` 覆盖；`WOLVI_REPCUT_HOST_SPIN_US` 和
`WOLVI_REPCUT_WORKER_SPIN_US` 支持 `infinite`/有限回退（worker 侧为 `0` 或 `infinite`）。
每个 worker 增加 cacheline 对齐的 acquire/release work/completion/stop 原子状态；all-spin
热路径不进入 mutex/CV，混合或 CV 回退仍保留 predicate 等待。线程启动增加绑核握手，Host
保存并在 shutdown/异常后恢复完整 affinity mask；Host 或 worker 异常会先 drain 已派发 callback，
再 stop/join 后重新抛出，避免后台线程继续访问模型。

验证方面，`emit-verilator-repcut-package` 生成契约测试已更新并通过；生成的 common wrapper
以 C++17 编译通过，覆盖 K=3 fixture 的 200-step smoke source，RepCut 相关 5 个 CTest
目标全部通过。本节提交时尚未用该通用 emitter 重新生成 XiangShan 32 分区 ELF，也没有把
代码落地宣称为新的 Host walltime 结果；后续端到端验证见 8.13。

### 8.13 通用 emitter 的 XiangShan 端到端验证（2026-09-20）

用 Wolvrix `5f6bb8b` 重新读取 B 组已分区 JSON（`3,681,281,481` bytes，SHA-256
`c33ecac1f8d82f06fb81e10b253540c681321749300b00949b74a423f8d78c0a`）并直接生成生产
package，没有重跑 Chisel、ingest 或 RepCut。新旧 package 的 65 个 SV 文件逐字节一致，
因此复用原 32 个 Verilator partition archive；所有受新 header 影响的对象均重新编译，包括
common/load/eval/update 四个 wrapper 和外层 `partitioned_verilator.cpp`，随后重新链接得到 ELF
`db03f4986dadb0cc9753c4d2d50fc3179efb6dcba242d70e5fdbbacf5109c8d7`。这只复用模型机器码，
不复用本轮要验证的 runtime 或其对象布局。

在 node030 CPU96–127、NUMA1 上，不设置三个 `WOLVI_REPCUT_*` override，以
`XS_EMU_THREADS=32` 运行。启动日志确认生产路径为 `legacy-host`、31 个后台 worker、Host lane 9
/ CPU105、`per-lane-atomic-spin`、Host/worker 均为默认 infinite spin，且
`early_phases=supported`。C=100 以 exit 0 结束，功能签名为 PC `0x0`、`instrCnt=0`、
`cycleCnt=96`、guest cycle `101`、302 steps。两次 C=10000 均以 exit 0 结束，无 difftest
mismatch/assert，且都得到 PC `0x800027c6`、`instrCnt=458`、`cycleCnt=9996`、guest cycle
`10001`、20102 steps，和既有基线完全一致。

同一时间窗按“生产、旧 v6、生产”交错运行 C=10000，得到：

| 指标 | 生产 run 1 | 旧专用 v6 对照 | 生产 run 2 |
| --- | ---: | ---: | ---: |
| Host time | `7.809 s` | `8.038 s` | `7.860 s` |
| step total | `7.746 s` | `7.972 s` | `7.795 s` |
| eval avg | `301.052 us` | `311.116 us` | `303.680 us` |
| update avg | `72.628 us` | `73.298 us` | `71.948 us` |

这组短交错只用于确认生产落地没有明显性能回退，不替代正式 AB/BA 性能验收；当前节点状态下
旧 v6 同样慢于 8.11 的历史约 `6.8 s`，因此不把跨时间窗口差异归因于代码。生成、身份审计、
成功 ELF 和运行日志集中在 `build/asc_counter_host_20260915/production_allspin_20260920/`。
