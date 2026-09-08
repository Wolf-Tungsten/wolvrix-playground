# TNO0277: XiangShan RepCut N=8/N=32 page-local comparison protocol

日期：2026-09-07

状态：`PROTOCOL FROZEN; RUNNER IMPLEMENTATION AND NODE ADMISSION IN PROGRESS`。

## 1. 目的与输入

承接 [TNO0275](./TNO0275_xiangshan_repcut_n1_page_local_ab_ba_node033_20260904.md)，
测量旧 baseline 与新 closure-aware 在 `K=32, N=8/32` 的运行时间，解释数据更新、
计算负载与线程同步对收益的影响。两侧继续复用 clean-v4 ELF 与 build manifest，
保持 CoreMark image、NEMU、ASLR、工具链和分区结果身份。

每个 N 使用 `C=100` 功能门及 `C=10000` 性能样本；两臂顺序为 AB 和 BA，
各两次性能样本。N=1 的 TNO0275 作为历史串行参照，跨日期/节点比例不作为严格 scaling
headline；本轮最主要比较是同机、同 N、同 CPU mask 的 baseline/closure-aware。

## 2. CPU 与页面

- 在用户允许的 node029-node034、node036-node042 查找，优先 node030 的 CPU0-95。
- N=8 使用一个完整 CCD 的 8 个物理核；N=32 使用同一 NUMA 节点的 32 个物理核，
  优先四个完整 CCD。两档尽量同机且 N=8 是 N=32 的子集。
- 仅取每个 core 的一个 SMT thread，完整相关 CCD 与 SMT siblings 都纳入 admission/audit。
- audit/perf 控制线程在相关 CCD 外；model 主线程保留整个目标 mask，worker 按现有实现
  固定到目标 mask 升序 CPU。本轮不改变调度方式。
- 每个 order/arm 的 ELF、image、NEMU 使用独立 tmpfs inode，在目标 NUMA 绑定下复制及校验。
- 运行中继续按 RX VMA dev+inode 关联 numa_maps，保留 TNO0274 的覆盖率、本地率和至少
  3 个有效采样硬门；样本身份、输入 SHA、功能签名与线程配置都必须通过。

## 3. 计时修正

新 runner 使用独立 `parallel-page-local-v3` revision，保留已冻结 N=1 runner。
在 workload `wait()` 返回时立即记录 `workload_elapsed_seconds`，单列
`audit_finalize_seconds`，避免将审计收尾加入模型 walltime。运行期 CPU busy 的结束快照
也在 workload 结束处截取，避免审计扫描延长占用统计窗口。

默认尝试 strict 样本。若共享主机的轻量 foreign task 门无法通过，可沿用明确记录的
diagnostic 策略，仅豁免 `runtime_foreign_task_load`；功能、目标核干扰、guard idle、
affinity、页面归属仍为硬门。不得将 diagnostic 标为 strict。

## 4. 通信开销的测量定义

冻结 package 的三个 phase 是：

| 指标 | 执行方式与含义 |
| --- | --- |
| input_load | host 串行装载各 partition 输入 |
| part_eval | worker 并行计算，phase wall 包含 dispatch、计算与等待完成 |
| global_update | worker 并行发布输出，phase wall 包含数据拷贝、dispatch 和等待完成 |
| per-part input_apply | 某个 partition 输入函数内部耗时 |
| per-part eval | 某个 partition eval 函数内部耗时 |
| per-part update_push | 某个 partition 输出拷贝函数内部耗时 |

N>1 创建 N 个 worker，另有 host 主线程；它们共享 N 个物理 CPU 的预算。当前调度把
连续 partition 区间分配给 worker，N=8 每个 worker 4 个 partition，N=32 每个 worker
1 个 partition。每个 phase 独立 dispatch 并等待 worker 全部结束。

对 eval/update 分别计算每 worker 的 per-part 平均时间之和，再取最大值。此值是从
聚合计时估算的关键 worker 负载；`phase wall - max(worker mean sum)` 包含同步、
唤醒、计时外函数开销以及逐步负载波动造成的差异。由于现有 ELF 没有逐步 barrier
时间序列，此差值最多作为混合 residual，不能称精确 barrier 或纯通信耗时。

per-part 时间求和是并行线程上的累计函数时间，不能从 phase wall 直接减去。
静态 cross-endpoint words 与 communication KM1 仍只用于解释连接规模，不能替代
物理缓存流量/互连字节的测量。

## 5. 输出与判定

分别报告 N=8/N=32 的 AB、BA 与 pooled Host/workload wall、三个 phase wall/share、
per-part 及 worker 的 apply/eval/push 负载、PMU task-clock/cycles/instructions、
上下文切换与迁移，以及 admission/page-local/audit 证据。记录两序效果差异。

首先回答新划分在同 N 下是否更快，再解释 global_update 耗时及占比如何变化。
N=32 跨 CCD，而 N=8 在一个 CCD，故两档之差同时包含线程数与共享缓存拓扑变化。
实验完成后按目录规范另建结果文档并更新索引。

## 6. 增量更新 2026-09-07：首轮审计修正

`parallel-page-local-v3` 首轮 N=8/C100 功能门通过，C10000 因 worker 总数检查及
外来负载门被拒，没有 accepted performance pair。原始数据保留于：

```text
build/repcut_closure_runtime_20260902/runs/
  node030_n8_ccd184_pagelocalv3_strict_ab_20260907_1527/
```

运行中实际存在 8 个正确固定到单核的 RepCut worker，以及 7 个保留整个 CPU mask
的 Verilator 辅助线程。VerilatedContext 默认以允许 CPU 数 N 创建 N-1 个备用
thread-pool worker；冻结的全部 32 个 partition model 都是 `threads()=1`，没有
向该池派发 eval 任务。备用线程在首次任务前直接等待 condition variable。

因此 N>1 的进程线程组成是 host 1 + RepCut N + Verilator 备用 N-1，即共 2N 个
OS threads，但计算仍由 N 个 RepCut worker 完成，CPU 预算仍为 N 个物理核。
派生 v4 runner 将分别校验 N 个单核 worker 与 N-1 个 full-mask 辅助线程，并记录
辅助线程 CPU ticks；保留原始 v3 和失败样本，避免覆盖身份。

资源扫描发现 node030 的 CPU0-95 受迁移后台负载影响，未找到稳定四 CCD 组合。
同机 NUMA1 的 `96-103,112-119,168-175,184-191` 连续六个 3 秒窗口全部通过；
N=8 使用嵌套 `184-191`，monitor CPU0。首轮 strict 的轻量 foreign ticks 超限，
后续按第 3 节既定 diagnostic 策略测量，继续硬拒绝目标核干扰与其它门禁失败。

## 7. 增量更新 2026-09-07：执行完成与结论分级

N=8 最终在 node030 CPU112-119、NUMA1 完成 v4 diagnostic AB/BA。N=32 首轮
暴露 CPU accounting 的方向性筛选问题，未将失败 pilot 混入正式 pair；按独立
[TNO0278](./TNO0278_xiangshan_repcut_parallel_cpu_audit_capture_protocol_20260907.md)
事前冻结的 capture 规则，在同机 NUMA1 的 `104-111,144-151,160-167,176-183`
完成固定 AB/BA，保留全部原始通过/拒绝判定，不再按 runtime 残差重试性能样本。

两档的功能、输入身份、页面与 worker 绑定证据通过，但本轮没有 strict clean
performance 结论。最终 Host、计算/更新 phase、关键 worker 与审计限制统一记录于
[TNO0279](./TNO0279_xiangshan_repcut_n8_n32_communication_runtime_diagnostic_20260907.md)。
本记录前述进行中状态保留为历史计划，不代表最终仍有仿真在运行。
