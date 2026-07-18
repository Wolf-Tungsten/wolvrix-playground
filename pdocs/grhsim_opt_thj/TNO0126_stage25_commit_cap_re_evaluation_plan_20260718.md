# TNO0126 Stage 25 commit-cap re-evaluation plan on the cap8192 baseline

记录日期：2026-07-18

状态：计划在当前仓库默认生成配置（C++ native `maxOpInCommitSupernode=8192`、native hybrid 保持默认、ASLR 关闭）上重新检查 commit guard event merge cap。历史 Stage 12 的 `16384/32768` 结果使用旧默认和不完整的 NUMA/page-local 协议，不能直接作为当前结论；本阶段先做同一 post-stats 输入的结构/静态筛选，再对没有明显静态风险的候选执行 fresh page-local 双 NUMA 50k，最终只看 `Host time spent` walltime。

## 1. 候选和基线

基线为已经在 TNO0124 采用的 C++ native cap8192 生成结果：

```text
build/xs_activity_stage23_cap8192_cpp_default_20260718/grhsim/grhsim_emit/
```

结构候选先检查显式 commit cap `12288`、`16384`、`32768`。这些候选只改变 order-preserving guard-event commit coarsening，不打开 terminal pushforward strict、probe、post-DP refine、Kahn pack 或其它实验开关。所有候选从同一个 post-stats JSON 恢复，以隔离 activity-schedule 变量。

## 2. 结构和静态 gate

每个候选记录绝对值：commit/total supernodes、commit event runs、compute-compute 与 compute-commit value pairs、DAG、boundary values、commit roots、sink ops、generated source bytes/lines、最大 translation unit、`.text`/archive 大小和 activity/emitter stats SHA。要求 baseline/candidate 的 compute partition、graph、state-read 集合、sink 覆盖和功能签名闭合；允许小的结构指标退化，但若 CPP/TU 明显膨胀或功能/validator 失败则停止该档。

## 3. runtime protocol

候选和 baseline 分别复制到 fresh `/dev/shm` inode；复制过程使用空闲核上的 `taskset` + `numactl --physcpubind/--membind`。正式 run 使用 `setarch x86_64 -R`、同一 target/sibling/helper、whole-node pre/runtime idle gate、运行期 `numa_maps` placement、perf migration=0、ABBA/BAAB 四样本和两 NUMA 平衡聚合。所有顶层命令先 `source /nfs/home/tanghaojin/wolvrix-playground-gsim-calibrate-2/env.sh`。cycles/instructions/task-clock 只作诊断，walltime 是唯一端到端判据。

## 4. 默认策略

候选只有在两 NUMA 的 balanced walltime 取得稳定、可重复的正收益时才考虑改变 C++ 默认；否则保留 native cap8192，并在结果文档中记录绝对 raw log、缺失项和停止原因。
