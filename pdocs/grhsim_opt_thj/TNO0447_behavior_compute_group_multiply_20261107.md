# TNO0447：`kBehaviorComputeGroup` 与乘法行为模型（2026-11-07）

## 范围

本轮把无状态乘法行为模型与有状态 `kBehaviorStateGroup` 分开，新增通用
`kBehaviorComputeGroup`。模型作者仍通过 YunSuan wrapper 使用直接乘法，流水寄存器、valid/fire、
flush 和握手留在外围普通 GRH；分组节点只表示经过认证的纯组合 carrier。默认路径仍是硬件，
`--wolvrix-behavior-compute-lowering` 默认 `ordinary`。

四类 carrier 均使用稳定版本、端口顺序、位宽和 SHA-256 绑定：标量整数 133→64、向量整数
238→72、标量/向量浮点 108→107。Wolvrix 新增 `kBehaviorComputeGroup`、契约校验和四类
精确 C++ helper；浮点 helper 仍使用整数有效数乘法，不使用宿主浮点。SystemVerilog carrier
保留合法算术回退。

## 功能与绑定检查

ordinary 与 grouped 四类 fixture 各通过 30,000 周期随机逐拍比较，覆盖复位、气泡、连续输入、
重复 eval、整数高/低半、MULW/MULW7、向量 SEW/加宽/MAC/vxrm/vxsat 以及 SoftFloat 浮点边界。
grouped carrier 的版本、端口、宽度、模型名和语义哈希错误均被针对性拒绝。

`behavior_compute_group_check.py` 和 `multiply_behavior_check.py` 的结果保存在机器可读产物中。

## 局部性能

测试在 node030 CPU96、NUMA node1、ASLR 关闭、单线程、8 对 AB/BA 下进行，计时包含输入准备、
完整流水、输出读取和变化检测。硬件/ordinary 与硬件/grouped 的完整三场景结果，以及 ordinary/
grouped 的直接比较，保存在 `compute-group-v1-local-report.json`。

ordinary 相对硬件 fixture 在四类模型均显著更快；但 `kBehaviorComputeGroup` 相对 ordinary
的直接结果分化：

| 模型 | active | sparse | idle | 判定 |
|---|---:|---:|---:|---|
| `int-mul` | 约 -30.3% | 约 -25.8% | 约 -16.0% | 达到局部门槛 |
| `vec-int-mul` | 约 +78.6% | 约 +50.2% | 约 +25.7% | 回退 |
| `fp-mul` | 约 +1.4% | 约 +0.3% | 约 +1.7% | 无稳定收益 |
| `vec-fp-mul` | 约 -4.0% | 约 -3.3% | 约 -3.0% | 未达到 5% 门槛 |

因此本轮只把标量 `int-mul` 带入完整 XiangShan 候选；其他三类只保留局部结果，不进入整机
性能配置。局部测量期间曾有 CPU 区域被外部任务占用，受影响的 direct 比较场景保留原始日志，
并用后续空闲窗口补齐；不按异常耗时删样本。

## 完整 S3

A 为全硬件乘法，B 仅启用 `int-mul` 与 `--wolvrix-behavior-compute-lowering grouped`；
两组保留完整 DiffTest/NEMU，使用同一份 RTL、CoreMark 镜像、CPU96、NUMA node1、ASLR
关闭和单线程运行。B 的两个标量乘法器实例都完成了 carrier 绑定；重复 RawModule 实例在
firtool 中出现的 `_1` 模块后缀由严格的同签名别名规则处理。

结构统计如下：

| 指标 | A 硬件 | B `int-mul` grouped |
|---|---:|---:|
| GRH graph ops | 7,203,931 | 7,198,784 |
| GRH graph values | 6,832,832 | 6,827,721 |
| compute supernodes | 63,276 | 63,279 |
| commit supernodes | 468 | 468 |
| native binary | 79,101,448 B | 79,133,560 B |
| C++ 源码总量 | 1,264,856,947 B | 1,264,156,889 B |

两组均通过 10,000 周期 smoke；两组各做 100,000 周期 NEMU/DiffTest trace，PC、提交指令数、
周期数和 100,000 条 trace 记录完全一致。trace comparator 的两组输出哈希均为
`c27730f8e92fb2bd2144632b8922271436ea55cb4bceec598525fc559ee921`。

正式 8 对 AB/BA walltime（CoreMark，关闭 trace 和诊断）为：

| 项目 | 数值 |
|---|---:|
| A 均值 | 114.93125 s |
| B 均值 | 115.490375 s |
| 配对变化 `B/A−1` | **+0.486457%** |
| B 更快 | 0/8 对 |
| 中位数变化 | +0.553336% |
| 固定种子 bootstrap 95% CI | **[+0.348429%, +0.622474%]** |

因此，在这次完整 S3 负载中，分组节点虽然删除了约 5.1k 个 GRH op，仍然带来约 0.49%
的稳定回退；收益没有转化为整机加速，且不满足进入默认路径的条件。当前默认配置继续使用
硬件乘法，grouped lowering 只保留为显式实验选项。

## 产物

- 局部报告：`wolvrix/build/artifacts/multiply-behavior/compute-group-v1-local-report.json`
- carrier 契约检查：`wolvrix/build/artifacts/multiply-behavior/compute-group-v1-contract-check.json`
- 局部 study、逐对 CSV/JSON 和原始日志：`build/multiply_compute_group_20261107/`
- 完整 S3 产物：`build/xs/multiply_behavior_compute_group_20261107_int_v1/`
- 完整 S3 功能门：`build/xs/multiply_behavior_compute_group_20261107_int_v1/functional-v1/verification-complete.json`
- 完整 S3 性能汇总：`build/xs/multiply_behavior_compute_group_20261107_int_v1/performance-v1/summary.json`
- 完整 S3 配对 CSV：`build/xs/multiply_behavior_compute_group_20261107_int_v1/performance-v1/pairs.csv`
