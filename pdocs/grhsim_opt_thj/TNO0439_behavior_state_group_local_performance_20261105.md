# TNO0439：kBehaviorStateGroup 的生产优化流程局部性能（2026-11-05）

## 结论

520 路 RAT observer 的分组路径 G 通过本轮局部门槛：相对同一语义描述的普通路径 O，
稀疏更新快 24.10%、密集更新快 21.19%，同时比原硬件写法 H 快 16.56%/17.10%。
各比较均为 8/8 对更快，配对置信区间均超过约 5% 门槛。

小型双数组没有通过相对 O 的门槛，不能据此给所有数组默认启用分组。
默认仍为 hardware/ordinary。这里只支持准备下一阶段真实 S3 接入，**没有运行新的整机 NEMU、
trace、walltime 或 A/A**，也未推翻 [TNO0437](./TNO0437_behavior_commit_rat_s3_measurement_20261105.md)
普通模型的完整香山 +5.27% 回退结论。

实现和功能契约见 [TNO0438](./TNO0438_behavior_state_group_contract_20261105.md)。

## 三组定义与工作负载

| 组 | 定义 |
|---|---|
| H | 原 indexed Reg/Vec 硬件写法，经过完整生产优化 |
| O | 数组模型的完整 SV carrier，经普通 GRH 和完整生产优化 |
| G | 与 O 完全相同的 carrier/manifest，绑定为 kBehaviorStateGroup 后完整生产优化 |

H 是局部原写法对照，不是完整 RenameTable 或整芯片。O/G 的 SV 相同，隔离的是后端表示。

小型 fixture 是两个长度为 32 的数组，元素宽度 64/9 位，3 路输入，包含跨数组旧状态 RHS。
RAT fixture 使用当前香山参数：520 个潜在退休微操作保持原始顺序，int/FP/vector 各 32 个
被观察条目和 1 个 v0 条目，共 97 个 8-bit 元素；生成 520×4=2,080 个候选更新，不压成 8 路 RAB。
FP/vector 越过被观察条目的索引不更新，vector 第零项由 v0 单独提供；vector 物理映射含 +22 offset
和两半展开。仅对被观察的数组投影建模，不包含完整 Preprocess 延迟链和 NEMU。

每次运行 10,000 周期、固定 seed 42；两次 eval/周期，复位和输出哈希在计时区间内。
计时包含随机输入准备、所有端口赋值、更新、变化检测、snapshot/动态读及输出哈希。
初始化 model、进程启动和库加载不在内部计时内；外部进程耗时另存，不混入统计。

- RAT sparse：0–16 个前缀 lane 有效，保留周期性的无提交和同地址写回用例。
- RAT dense：各 lane 约 20% 有效，含重复目的与同地址写回。
- idle：所有 update valid 与 payload 清零；仍计算输入生成循环、复位、eval 与输出哈希。
- simple active：3 路随机更新。它不是 RAT 的 520 路 workload。

这些是固定合成刺激，不是从 CoreMark 抽出的退休活动分布；idle 也不是单独测 empty helper。

## 配置和冻结

使用根脚本 `scripts/wolvrix_xs_grhsim.py`，实际核对其完整配置行与 v10 S3 A：
除 `pre_reg_to_mem_json/post_stats_json` 产物路径外无差异。关键配置包括：

- reg-to-mem intent、ordered_writes、decoded_write_storage 开启。
- activity compute node/supernode 上限 108，oversize split 108。
- emitter batch 2048 ops / 8192 estimated lines，target 64，batches/file=1。
- single-thread runtime，waveform/perf 关闭，沿用生产 direct state read/commit 默认。
- clang 23，`-std=c++20 -O3 -march=native`。

H/O/G 均使用同一冻结 native 库：

```text
e69a17390dd2f5f2f06a5ed918532f5fcc422b4b3ac47db821f3455f1449ad93
```

运行在 node030 CPU96、NUMA1、ASLR off。CPU96–127 与 CPU96 SMT sibling 在计时前连续三个
5 秒窗口空闲率至少 98%；监控 Python 位于该区域外。私有 binary/共享库复制并在 CPU96/NUMA1
预触页，运行使用 `taskset 96 + numactl --membind=1 + setarch -R`。每种场景 H/O/G 各预热一次，
然后 8 轮 HOG/GOH 交替，计时期间没有本实验构建，区域负载检查通过。
所有有效样本保留，没有按耗时剔除。

## 10,000 周期耗时

下表均值单位为毫秒；变化为逐对 `candidate/baseline−1` 的均值，负值表示更快。

| 场景 | H 均值 ms | O 均值 ms | G 均值 ms | G/O−1 | G/H−1 |
|---|---:|---:|---:|---:|---:|
| 双数组 active | 5.090110 | 1.647243 | 1.674339 | +1.6848% | −67.1048% |
| 双数组 idle | 1.445809 | 1.320794 | 1.363424 | +3.2805% | −5.6895% |
| RAT sparse | 91.430723 | 100.518120 | 76.291605 | −24.0979% | −16.5575% |
| RAT dense | 122.381315 | 128.731158 | 101.447484 | −21.1930% | −17.1041% |
| RAT idle | 64.699636 | 72.689237 | 60.705047 | −16.4859% | −6.1711% |

| 场景 | G/O 配对中位数 | G/O bootstrap 95% CI | G 快于 O | G/H bootstrap 95% CI |
|---|---:|---|---:|---|
| 双数组 active | +1.4067% | [−0.0521%, +3.4638%] | 2/8 | [−67.3776%, −66.8200%] |
| 双数组 idle | +2.8332% | [+1.1582%, +5.8870%] | 1/8 | [−6.7932%, −3.9954%] |
| RAT sparse | −23.9786% | [−24.5324%, −23.6494%] | 8/8 | [−16.9790%, −16.0758%] |
| RAT dense | −21.3296% | [−21.4811%, −20.8821%] | 8/8 | [−17.4572%, −16.7750%] |
| RAT idle | −16.4739% | [−16.8145%, −16.1573%] | 8/8 | [−6.6588%, −5.7026%] |

bootstrap 复用既有固定种子 paired 统计；样本很短，尤其小数组只有约 1–5 ms，
不把百分之一的变化当作可外推的稳定性能结论。RAT 的主要对比差距为约 16–24%，但仍只代表此局部程序。
逐轮 H/O/G 时间、顺序、全部哈希和各自耗时中位数保存在 CSV/JSON，没有隐藏采样轮次。

## 结构统计

`graph_ops` 取 activity schedule 报告，不等同于每次 eval 实际执行的 operation 数。
状态 payload 不含 C++ 对象头、对齐、临时值或调度存储。

| 双数组 | H | O | G |
|---|---:|---:|---:|
| GRH ops | 1,882 | 298 | 227 |
| compute supernodes | 20 | 3 | 2 |
| commit writes | 64 | 70 | 1 |
| boundary activation edges | 994 | 82 | 16 |
| persistent state payload bytes | 320 | 320 | 512 |
| C++ files | 15 | 14 | 14 |
| C++ bytes | 503,685 | 122,545 | 53,405 |
| binary bytes | 73,400 | 52,728 | 48,720 |

| RAT | H | O | G |
|---|---:|---:|---:|
| GRH ops | 356,557 | 23,542 | 13,043 |
| compute supernodes | 187 | 205 | 121 |
| commit writes | 1,564 | 2,177 | 1 |
| boundary activation edges | 4,522 | 5,893 | 5,722 |
| persistent state payload bytes | 97 | 97 | 97 |
| C++ files | 32 | 34 | 28 |
| C++ bytes | 2,387,871 | 4,630,013 | 2,680,600 |
| binary bytes | 273,320 | 355,432 | 399,288 |

所有组 `kStateShadowCount=0`、event-edge storage=1 byte；RAT H 有两个 commit event key，O/G 为一个。
G 的双数组混合位宽采用统一 64-bit backing word，导致 storage 从 320 增至 512 bytes。
RAT G 的 ELF 比 H/O 都大，源码也比 H 大，不能把“文件少/节点少”直接当作速度证据。

## 独立诊断

诊断程序 seed 42，10,000 周期，每周期四次 eval（含重复 eval 与同高电平输入变化）。
它与正式计时是分开的 binary，以下次数不能直接当作两次 eval/周期的正式工作量。

| RAT 诊断 | H | O | G |
|---|---:|---:|---:|
| compute batch executions | 710,298 | 828,681 | 578,280 |
| executed scheduled memory read ports | 1,734,592 | 786,809 | 1,203,756 |
| changed write counter | 523,723 | 728,405 | 236,899 |

G：10,000 次组提交、741,116 次有效更新、239,841 次 touched-row 比较，最终 236,899 行发生净变化。
H/O 的 changed write counter 会包含同边沿中间写入；G 只计最后变化，两者不是完全相同的事件口径。
memory read counter 只统计执行到的调度 read port，不包含所有 inlined/direct state load，
小数组 H 的该计数为零不能解释为没有状态读取。

独立净零用例有 100 次提交，每次先写 1 再写回 0：200 次有效更新、100 次 touched row、
零最终变化、零 reader 重求值。它直接验证了“只传播净变化”的机制，不拿 helper 单独耗时作收益。

## 可得到的 insight 与下一阶段条件

1. 高层 API 简化源码不等于快。RAT O 在完整优化后仍比 H 慢约 5–12%，与上轮整机回退方向相容；
   这不是同一完整模型，也不能据此量化上轮瓶颈。
2. 大量有序更新可以通过一个 commit 单元、地址去重、最终值比较减少通用提交包装。
   RAT G 的 batch 次数与中间写变化减少，和实际加速一致；没有逐指令因果剖析，不能声称某一项独占全部收益。
3. 只减少声明状态数不是本轮的收益来源：三组 RAT 都是 97 bytes，shadow 和 event storage 也没有下降。
4. 小数组的暂存、位图与最终比较有固定成本；它没有通过相对 O 的门槛。应保留 opt-in，而非把所有 array 默认分组。
5. G 仍然接收并检查 2,080 个 valid/input 依赖，没有消除输入准备和检查输出的费用；不能把局部百分比当作整个 S3 的预期收益。

下一阶段建议单独接入真实 S3 RAT observer 的原始 520 路输入，保留 integer/FP/vector/v0
时序、原延迟与 canonical DiffTest bundle。需扩展显式 observer domain 所有权，使合法 debug delay
和 checker 消费者可绑定，同时继续禁止功能反馈；不把 520 路退休序列替换成 8 路 RAB。
完成完整 NEMU/trace 一致性后，才在用户指定空闲窗口做整机 AB/BA 与必要的 A/A。
本轮止于该建议，没有自动启动下一阶段。

## 产物索引与审核

共同根目录为 `wolvrix/build/artifacts/behavior-state-group/`：

- `report.json`：配置差异、功能记录、状态/源码/binary 统计、冻结哈希、运行结果与局部门槛。
- `simple-final/timing-v2/`：双数组 active/idle 的 8 轮 CSV、summary、原始日志、私有 runtime 和空闲记录。
- `rat-final/timing-v1/`：RAT sparse/dense/idle 对应产物。
- `simple-final/tools-frozen/`、`rat-final/tools-frozen/`：同哈希工具与文件身份。
- `simple-v2/diagnostic-summary.json`、`rat-v1/diagnostic-summary.json`：独立诊断。
- `contracts-v2/`：拒绝原因、SV roundtrip、两实例与跨组旧状态检查。
- `source-snapshot/`：计时前快照；`source-snapshot-final/`：收尾代码/文档快照与差异说明。

`simple-final/timing-v1` 因 runtime 父目录未创建，在任何计时样本产生前失败，保留原日志；
修正的是准备脚本目录创建，正式结果使用新目录 timing-v2，没有替换或删除耗时样本。
开发过程的旧 contracts-v1 记录不作为 native-feedback guard 的最终证据，原因见 TNO0438。

复核入口 `python3 scripts/behavior_state_group_report.py` 只读已完成产物，不构建、不仿真；
检查 H/O/G 配置、最终 binary 哈希、每场景 27 次运行（3 warmup + 24 正式）的输出一致性和环境 gate。

## 增量勘误：native 编译器身份（2026-11-05）

下一阶段 ldd 审核发现，本篇所谓冻结 native 哈希 e69a... 实际只覆盖 Python 扩展 `_wolvrix.so`。
它动态链接的 `libwolvrix-lib.so` 未随 Python 包复制，仍来自构建目录。因此不能用该哈希声称
完整 native 编译器已冻结。模型源码、最终 binary、原始样本和本篇统计不改写；新一轮已修正冻结流程，
同时保存两个库并校验实际加载路径，详见 [TNO0440](./TNO0440_grouped_rat_s3_integration_20261105.md)。
