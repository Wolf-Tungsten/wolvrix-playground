# TNO0421 恒零译码表回退：冻结对照与调查启动

承接 [TNO0420](./TNO0420_decode_table_csr_only_results_20261104.md)，本轮调查恒零 `indexedLSUopTable` 提前消除如何影响后端及实际执行，暂不推进生产修复。E 保持当前默认行为；两版 CSR lowering 均开启。

## 冻结输入

- C：`build/xs/decode_table_tuned_20261103_v1/C`，动态恒定表提前折叠开启。
- E：`build/xs/decode_table_csr_only_20261104_v1/E`，该折叠关闭。
- 原表 ID：`ab90a3b3674e7d79ed393586fbc00d89c452ceb74be6b891cb86dbcf5f4c9531`。
- 层次结果：`cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$decode$decoderComp$indexedLSRegOffset_0$out_primitive$out`。
- 两组各 100,000 周期的有效 DiffTest 比较已经通过；本轮复用冻结二进制和验证记录，核验身份后开展诊断。

## 本轮进度

新增 [测量入口](../../scripts/decode_constant_measure.py)，继续调用现有单线程 NUMA/亲和性/SMT 检查；独立 observer 记录 CPU96 的 APERF、MPERF、系统负载和 CPU pressure。普通 walltime 不附加进程 PMU 或地址采样。后续 PMU、地址采样独立运行，不能混入 walltime 样本。

八对 C/E、EC 交替测量已启动，产物目录 `build/xs/decode_constant_investigation_20261104_v1/walltime1`。所有样本保留；上一轮末尾约 2 秒的速度档位变化是待解释的环境现象，不能静默删样本。

PMU 可用性预检查通过：`cycles:u`、`instructions:u`、`branches:u`、`branch-misses:u`、`ic_tag_hit_miss.instruction_cache_miss:u`、`L1-dcache-load-misses:u`、`dTLB-load-misses:u`、`iTLB-load-misses:u`。MSR 使用 CPU96 全局计数，进程事件使用 attach，记录附加延迟。PMU running percent 低于 99% 时不作为精确整段计数。

静态已知差异仍只是线索：少 49 个操作却多 1,487 个 compute node、618 个边界值、461 条活动边。下一阶段增加默认关闭的调度阶段导出，用来源和结构确认跨版本对齐，并检查只导出不改变生成代码。

## 复现

```bash
ssh node030
cd /nfs/home/tanghaojin/wolvrix-SimpleTES-workspace-5/wolvrix-playground-gsim-calibrate-5
python3 scripts/decode_constant_measure.py \
  --output build/xs/decode_constant_investigation_20261104_v1/walltime1
```

测量期间本任务不并行构建。私有库文件页和匿名页仍必须位于 NUMA node1；不修改共享机器的全局频率设置。
