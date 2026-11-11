# TNO0033 merge-after 的独立 8-seed 分区重试

## 目的和固定输入

接续 [TNO0030](./TNO0030_clang23_repcut_merge_comparison_20261111.md)，为 after 也独立重跑一轮标准的 8 次分区，检查是否能改善原 retained seed7 的运行时间。复用 after 的冻结 `memory.json`、完整和 reduced HGR，不重新 elaboration、frontend 或 memory lowering；输入和工具 SHA256 在求解前固定，并在生成/编译后复核。

模型源为 XiangShan `defb18e13`、DiffTest `b17a43a`。生成与编译使用当前 Wolvrix 工具、与原 after 相同的 options / memory targets、Clang 23.1.2、`-std=c++20 -O3 -march=native -pthread`、64-byte 对象代码节对齐。harness 使用上一轮 Clang 23 after 构建所冻结的 generated headers，完整 DiffTest/NEMU 保持开启。

| 输入 | SHA256 |
| --- | --- |
| memory.json | `6a2510cac638cbefa9e432d6e7f3e4ade8158fbda05cef09e0ccdb06792c07fc` |
| 完整 HGR | `d2039565c041ba9151942d12cf1ca59d7a4b152633ad74c4cdc11342e0f3c3db` |
| reduced HGR | `e7d5080ba388f424c545cd391f3f66275664d92a2c0abf7fa6bdd08ff2163361` |
| MtKaHyPar binary | `9cb663fc1c9aac63e890a44c4ec71cf46ffefdb20430fa48193dfa0a60cb1c97` |

完整 HGR header 为 `578172 308029 11 6`，即 578,172 条边、308,029 个节点、6 维权重。原 oversized 隔离节点为 `[4, 1319]`；reduced header 为 `567451 308027 11 6`，求解 30 个普通分区，再还原为 32 分区。

## 八次求解和选择

仍使用 seeds 0–7，各 48 个 solver threads，epsilon=0.05、默认 preset、`km1` 目标。选择满足完整图六维容量约束且 `km1` 最小的候选；这是静态目标选择，不是把八个模型都编译计时后选择 walltime 最短者。

| seed | 原 after 完整图 km1 | 本次完整图 km1 |
| ---: | ---: | ---: |
| 0 | 46,214,542 | 44,349,417 |
| 1 | 44,820,873 | **40,769,428** |
| 2 | 48,093,067 | 40,908,479 |
| 3 | 46,183,451 | 41,674,766 |
| 4 | 43,997,647 | 42,120,685 |
| 5 | 43,963,224 | 44,091,310 |
| 6 | 44,657,508 | 42,569,256 |
| 7 | **42,318,476** | 43,087,112 |

八个新候选均满足容量约束；相同 seed 的新旧 assignment 哈希均不同。选中 seed1，相对原 seed7 最小 `km1` 降低 **3.66045%**。保留全部原始结果，不因性能结果重新选择其他 seed。

本轮与 before 的重试一样，先不叠加自动 atom migration，以隔离重新分区的效果。旧 after seed7 的 Clang 23 binary 和新 seed1 都独立保留。

## 功能和计时安排

运行固定 node030、CPU96–127、NUMA1 strict membind、ASLR disabled，原 performance code-page/preload、thread pinning 和 phase timing。使用相同 CoreMark、100,000 周期、完整 NEMU DiffTest，正式样本关闭 trace，不做外部 CPU 空闲准入。

旧 after、新 after、当前 before seed2 分别通过 10k smoke、100k verification、预热。两个 after 必须 PC、提交指令数、周期数、终止条件和 UART 全部一致；before/after 则分别通过 NEMU，比较共同终止条件、Guest cycles 和输出。

随后串行做两个独立 8 对 AB/BA：

1. 旧 after seed7 → 新 after seed1：直接判断此次重新分区的效果。
2. 当前 before seed2 → 新 after seed1：在两边都完成一次追加 8-seed 重试后，重新取得前后对照。

全部样本仍用已有严格 Runner 检查实际 32 个 singleton affinity、NUMA 页、ASLR personality、codepage PASS 和冻结依赖。Host time 与外部 walltime 分别统计，固定 seed 20261102，10,000 次 paired bootstrap。只有通过所有门的样本进入统计。

## 归档

- [执行脚本](../../build/artifacts/repcut-after-retry-clang23-20261111/run.py)、[驱动日志](../../build/artifacts/repcut-after-retry-clang23-20261111/driver.log)。
- [身份与工具 manifest](../../build/xs/repcut-after-retry-clang23-20261111/provenance.json)、[八次结果与选择](../../build/xs/repcut-after-retry-clang23-20261111/selection.json)、[原始 solver 日志](../../build/xs/repcut-after-retry-clang23-20261111/solves/)。

本记录形成于求解完成、生成模型期间。功能门和两个 8 对系列完成后另文归档。
