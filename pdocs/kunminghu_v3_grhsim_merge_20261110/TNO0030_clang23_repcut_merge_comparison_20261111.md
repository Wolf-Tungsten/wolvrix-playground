# TNO0030 Clang 23 下 RepCut merge 前后 8 对结果

## 固定模型与验证

沿用 [TNO0029](./TNO0029_all_clang23_rebuild_protocol_20261111.md) 的统一编译器实验：before 使用 TNO0027 的 seed2 initial，after 使用原 retained seed7 initial。两侧均以 Clang 23.1.2 重编译全部生成 C++ 及 DiffTest harness，没有重新分区或 migration。源码副本与原件在编译前后逐文件哈希相同。

node030、CPU96–127、NUMA1 strict membind、ASLR disabled，保留原 performance 的 code-page/preload、thread pinning、phase timing。固定 CoreMark/NEMU、100,000 周期、完整 DiffTest，正式运行关闭 trace，没有外部 CPU 空闲准入。

22 次运行（两侧 smoke、verify、warmup 和 16 个计时样本）全部通过功能及 placement 门，没有拒绝样本。两侧 Guest cycles=100,001、cycle-limit 终止，UART 均为 `Running CoreMark for 2 iterations`。before PC=`0x80000cde`、instrCnt=238,535、cycleCnt=99,996；after PC=`0x80000c1a`、instrCnt=250,838、cycleCnt=99,995。各版本内部签名稳定，跨版本不要求固定周期下提交进度相同。

## 配对结果

正数表示 after 更慢；固定 seed 20261102、10,000 次 paired bootstrap。

| 指标 | before 均值 / 中位数 | after 均值 / 中位数 | 配对均值 / 中位数 delta | 95% CI | after 更慢 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Host time | 11.701750 / 11.689000 s | 17.882875 / 17.875000 s | **+52.8448% / +53.3252%** | **[+51.3918%, +54.0385%]** | 8/8 |
| 外部 walltime | 11.802054 / 11.784056 s | 17.996602 / 17.987510 s | **+52.5105% / +53.0140%** | **[+51.0327%, +53.7197%]** | 8/8 |

在这两份冻结模型下，统一 Clang 23 后的 merge-after 明显更慢。本轮 before 是重试后的 seed2，而历史 Clang 19 merge 对测使用 seed3 migration candidate，因此不能把这张表与旧表的变化全部归为编译器差异。before 多做了一轮分区搜索，after 未做对称重试；本结果也不能排除 after 另有更优分区。

结论是当前两份已选模型、各自 revision/DefaultConfig/DiffTest 的整体仿真成本差异，不能解释为孤立的 backend 优化或纯微架构逻辑增量。

## 归档

- [配置/输入 manifest](../../build/xs/kunminghu-v3-clang23-retest-20261111/measurements/repcut/manifest.json)、[功能门](../../build/xs/kunminghu-v3-clang23-retest-20261111/measurements/repcut/functional.json)。
- [summary](../../build/xs/kunminghu-v3-clang23-retest-20261111/measurements/repcut/summary.json)、[逐对 CSV](../../build/xs/kunminghu-v3-clang23-retest-20261111/measurements/repcut/pairs.csv)、[逐对 JSON](../../build/xs/kunminghu-v3-clang23-retest-20261111/measurements/repcut/pairs.json)。
- [before 构建](../../build/xs/kunminghu-v3-clang23-retest-20261111/builds/repcut/before/)、[after 构建](../../build/xs/kunminghu-v3-clang23-retest-20261111/builds/repcut/after/)、[逐样本运行与放置证据](../../build/xs/kunminghu-v3-clang23-retest-20261111/measurements/repcut/)。
