# TNO0036 单字节补丁 after seed1 与原 after seed7 的性能对照

## 口径与功能门

用户在 [TNO0035](./TNO0035_after_seed1_clang23_mask_codegen_20261111.md) 根因定位后明确要求测量补丁 binary。本轮使用其中仅将 `kshiftrw` 改为 `kshiftrb` 的版本，SHA256 为 `3fd5e4c954af43d73e4ea98ed8015c3ebe26cb86dc424243e2c875c1333a94ef`。没有使用整体 no-SLP、Clang 19 或 O0 的诊断构建。

补丁 binary 复制到新的独立目录并核对哈希，不重新生成模型或选择 assignment。A 为原 after seed7 的 Clang 23 binary，B 为重新分区后的 after seed1 加单字节修正。两者均为 XiangShan `defb18e13`、完整 DiffTest/NEMU、DefaultConfig；生成 options、编译器及运行参数对齐。新 seed1 的静态 `km1` 比原 seed7 低 3.66045%，具体求解记录见 [TNO0033](./TNO0033_after_partition_retry_protocol_20261111.md)。

运行固定 node030、CPU96–127、32 个 worker、NUMA1 strict membind、ASLR disabled。复用 performance runner 的 thread pinning、code-page/preload 和标准 phase timing，关闭 trace/runtime profile，不做外部 CPU 空闲准入检查。

两侧分别通过 10k smoke、100k verification 和一次 100k 预热，随后交替执行 8 对 AB/BA。该对照共 **22 次运行全部通过**，没有拒绝样本。正式样本均通过实际 singleton affinity、NUMA locality、ASLR、code-page 和依赖哈希门。

同一 after revision 的全部 100k 运行具有相同完整签名：PC=`0x80000c1a`、instrCnt=250,838、cycleCnt=99,995、Guest cycles=100,001，完整 DiffTest=on，cycle-limit 终止，UART 为 `Running CoreMark for 2 iterations`。

## 8 对结果

正数表示补丁 after seed1 更慢。置信区间使用固定 seed 20261102、10,000 次 paired bootstrap。

| 指标 | 原 seed7 均值 / 中位数 | 补丁 seed1 均值 / 中位数 | 配对均值 / 中位数 delta | 95% CI | seed1 更慢 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Host time | 17.527250 / 17.534500 s | 23.551750 / 23.398500 s | **+34.3663% / +34.5651%** | **[+33.0658%, +35.7173%]** | 8/8 |
| 外部 walltime | 17.639278 / 17.642908 s | 23.704252 / 23.516968 s | **+34.3740% / +34.3795%** | **[+32.9880%, +35.7307%]** | 8/8 |

新分区在修复编译错误后仍明显慢于原 after seed7，降低静态切边目标没有转化为实际加速。本轮比较的是两份正确运行的完整模型；不能用先前不足 100k 周期就失败的 binary 来估计补丁本身的耗时开销。

## 已有阶段计时

以下是同一组正式样本内标准 phase timing 的中位数，无额外插桩或追加运行：

| 阶段 | 原 seed7 | 补丁 seed1 |
| --- | ---: | ---: |
| input_load | 0.472856 s | 0.466539 s |
| part_eval | 15.324811 s | 21.146851 s |
| global_update | 1.442011 s | 1.506863 s |

主要差距落在分区计算阶段。该数据不能单独区分分区负载分布、调度等待、生成代码形状及缓存行为，但支持保留原 seed7，不采用这轮新 seed1 作为性能基线。不同阶段的中位数不应相加当作 Host time。

## 归档

- [执行入口](../../build/artifacts/repcut-after-seed1-patched-perf-20261111/run.py)、[运行日志](../../build/artifacts/repcut-after-seed1-patched-perf-20261111/driver.log)。
- [冻结身份与补丁来源](../../build/xs/repcut-after-seed1-patched-perf-20261111/provenance.json)、[运行 manifest](../../build/xs/repcut-after-seed1-patched-perf-20261111/measurements/manifest.json)、[功能门](../../build/xs/repcut-after-seed1-patched-perf-20261111/measurements/functional.json)。
- [配对摘要](../../build/xs/repcut-after-seed1-patched-perf-20261111/measurements/after-old-vs-patched/summary.json)、[逐对 CSV](../../build/xs/repcut-after-seed1-patched-perf-20261111/measurements/after-old-vs-patched/pairs.csv)、[逐对 JSON](../../build/xs/repcut-after-seed1-patched-perf-20261111/measurements/after-old-vs-patched/pairs.json)。
- [原 after 的日志和放置证据](../../build/xs/repcut-after-seed1-patched-perf-20261111/measurements/old_after/)、[补丁 after 的日志和放置证据](../../build/xs/repcut-after-seed1-patched-perf-20261111/measurements/patched_after/)。

原失败 binary、诊断记录和原 seed7 retained 均保留；本轮没有修改默认编译选项。
