# TNO0442：分组 RAT 的完整 S3 性能测量（2026-11-05）

## 结论与配置

完整 S3 上未测出稳定加速。B 相对 A 的配对均值为 **+0.170705%**，固定种子 paired
bootstrap 95% 区间 **[-0.182087%, +0.461222%]**，B 在 2/8 对中更快。区间跨零，
不能把这次小差异认定为确定回退，也不能据此证明两者性能等价。

承接 [实现记录 TNO0440](./TNO0440_grouped_rat_s3_integration_20261105.md) 与
[功能验收 TNO0441](./TNO0441_grouped_rat_s3_functional_gate_20261105.md)：

| 项目 | A | B |
|---|---|---|
| 模型 | 原硬件 DiffTest | commit-rat adapter |
| 状态表示 | ordinary | RAT grouped，其他状态 ordinary |
| DiffTest RTL / 采集 / harness / NEMU | 全开 | 全开 |
| intrinsic | none | none |

B 保留原始 520×4 条潜在更新顺序，使用 32/32/32/1 行的四个 RAT 数组；物理 RF shadow、
架构快照、延迟及其他 DiffTest 事件仍保留。canonical header 与硬件 S3 一致。
这不是关闭 DiffTest 检查的对照。

产物：`build/xs/behavior_grouped_rat_20261105_v2/`。A 复用 v1 已完成的同配置硬件构建；
B 复用已核验 RTL，仅修正 importer 的文件末尾换行兼容性后重新 emit/compile。
native 编译器与 Chisel 生成源码一致，详细复用审计见 `source-audit.json`，不宣称两个
source manifest 逐文件完全相同。

## 测量口径

- node030，CPU96，单线程，NUMA1 本地分配，固定 ASLR，CoreMark 2-iteration 镜像，100,000 周期上限。
- 每个样本前连续三个 5 秒窗口检查 CPU96–127 和 CPU96 SMT sibling，空闲率均至少 98%。
- 正式运行时 CPU97–127/sibling 的最小空闲率为 99.5678%；16 个样本均通过亲和性、NUMA 和单线程检查。
- 各一次预热，随后 8 对交替 AB/BA；构建已结束，正式计时关闭 trace、footprints 与诊断计数。
- 报告 harness 输出的 Host time，包含完整 SimTop 与 harness/NEMU 工作；外部 walltime 同时保存在 CSV。
- `delta = 100 × (B_host_ms / A_host_ms - 1)`，负值表示 B 更快。
- 区间对配对 delta 进行 10,000 次有放回重采样，固定 seed 20261102，取排序位置 249/9749。
- 全部有效样本保留，没有按耗时删除异常值，也没有重跑某一对来选择结果。

## 逐对数据

| pair | 顺序 | A（秒） | B（秒） | B/A−1 |
|---:|:---:|---:|---:|---:|
| 0 | AB | 101.048 | 100.796 | -0.249386% |
| 1 | BA | 100.819 | 101.395 | +0.571321% |
| 2 | AB | 102.300 | 102.328 | +0.027370% |
| 3 | BA | 100.229 | 100.778 | +0.547746% |
| 4 | AB | 99.991 | 100.166 | +0.175016% |
| 5 | BA | 100.977 | 101.687 | +0.703130% |
| 6 | AB | 101.524 | 101.914 | +0.384146% |
| 7 | BA | 101.801 | 100.993 | -0.793705% |

| 汇总 | A | B |
|---|---:|---:|
| Host time 均值（秒） | 101.086125 | 101.257125 |
| Host time 中位数（秒） | 101.012500 | 101.194000 |

配对变化均值 +0.170705%，中位数 +0.279581%。这里使用各对比值的均值，不是两个总体均值相除。
本轮没有出现值得验收的加速，因此不追加 A/A；不声称该差异超过当前 A/A 噪声。
旧 A/A 未完成的状态保留，没有用历史噪声区间替代本轮测量。

## 功能与产物审计

前置 smoke 与 seed 0/1 的 100,000 周期 NEMU/trace 检查均通过，四份原始 trace 哈希一致，
详见 TNO0441。两个 seed 产生相同 CoreMark 轨迹，不是两个不同程序的覆盖。
正式 16 次运行均观测到 NEMU 已加载，达到周期上限；最终 PC `0x80000c0c`、提交指令数
240,349、DiffTest cycles 99,996、guest cycles 100,001 全部一致。

`measurement-audit.json` 复算统计，验证所有样本身份、原始运行参数、区域空闲记录、二进制、
镜像、NEMU、canonical header、运行脚本及冻结工具的不可变文件。A/B 配置差异仅为
`sim_models` 与 `behavior_state_lowering`。派生的 Python bytecode cache 与源码/动态库身份分开记录。
运行中的二进制与构建时哈希相同，最终 schedule 统计也与构建时 `model_manifest.json` 哈希相符。

审计脚本：`wolvrix/build/artifacts/behavior-state-group-s3/audit_measurement.py`。
主要记录：`comparison/manifest.json`、`pairs.json`、`pairs.csv`、`summary.json`，
各 `A|B/runs/` 原始日志和环境记录，以及汇总 `review.json`。所有失败构建与原始产物继续保留。

## 结构变化与性能含义

| 指标 | A | B | B/A−1 |
|---|---:|---:|---:|
| 最终 GRH operations | 7,204,065 | 6,870,723 | -4.6271% |
| compute supernodes | 63,273 | 63,658 | +0.6085% |
| boundary activation edges | 1,977,816 | 2,003,145 | +1.2807% |
| commit writes | 218,994 | 216,110 | -1.3169% |
| register state bytes | 590,608 | 580,104 | -1.7785% |
| memory payload bytes | 24,181,499 | 24,187,740 | +0.0258% |
| C++ bytes | 1,264,756,867 | 1,262,431,052 | -0.1839% |
| binary bytes | 79,096,928 | 78,676,200 | -0.5319% |

两边 state shadow 都为零，event-edge slots 都为 412。TNO0441 的 B 操作数曾误用
`eligible_ops=6658343`；这里使用最终 `graph_ops=6870723`，已在原记录追加勘误。

本轮支持以下判断：

1. 数组语义可贯通到真实 S3，分组提交和 observer domain 没有要求关闭 NEMU 或减少 canonical 检查字段。
2. 局部 RAT 的有序写入加速没有变成整机加速。IR 总量下降，但调度节点和激活边没有下降，
   生成代码也仅小幅缩小；不能把 operation 数当作运行时间的替代指标。
3. 分组更新只覆盖 RAT，读出、物理 RF shadow、架构 gather、debug delay 和 Gateway 等仍存在。
   它们是否占据主要运行时间，本轮没有独立计时或 profiling，不能把某一项指认为回退原因。
4. TNO0437 的普通模型相对硬件 +5.2677% 属于另一轮环境。当前结果更接近硬件基线，
   但没有同轮 ordinary/grouped 整机配对，不能直接相减并宣称分组节点带来约 5% 整机收益。

因此，本轮没有达到完整 S3 的性能推广门槛。保留高层数组 API、语义描述、实验性分组路径和
证据，默认继续使用 `hardware/ordinary`。要使 S3 接近 S0，后续候选需要减少实际执行的
observer 读出、传播或调度工作；本轮尚未证明具体应优化哪一段，不继续扩大节点种类或追加消融实验。
