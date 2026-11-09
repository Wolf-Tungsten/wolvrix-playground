# TNO0437：语义级 commit/RAT 模型的完整 S3 验证与性能（2026-11-05）

## 实验范围

承接 [TNO0436](./TNO0436_behavior_difftest_semantic_adapter_20261105.md)。A 为原 hardware DiffTest，B 为语义级数组 adapter，仍 lower 到普通 GRH 状态。
两组均完整生成、采集和运行 DiffTest/NEMU；本轮不关闭 S3 功能，不使用 intrinsic。
默认继续为 hardware；未增加 `kBehaviorStateGroup`。

同源码 TLConfig、单核，串行生成新 RTL，冻结同一 Wolvrix Python/tool library，clang 23 `-O3 -march=native`。
固定 node030 CPU96、NUMA1、ASLR 关闭、单线程、CoreMark 100,000 周期。运行前确认 CPU96–127 和 CPU96 SMT sibling 空闲，运行期间检查邻近 CPU 无外部负载；不并行构建。
源码快照、原始日志和数据在 `build/xs/behavior_commit_rat_20261105_v10/`。`source-audit.json` 单独记录快照后 fixture 可见性与刺激函数提取改动；生产生成源码未变。

## 功能结果

- A/B 10,000 周期 smoke 通过 NEMU。
- seed 0、1 各 A/B 100,000 周期通过 NEMU。每组 trace 有 100,000 条记录、每条 6,216 bytes；不仅 validity-gated 比较通过，原始文件 SHA256 也相同。
- 最终 PC `0x80000c0c`，提交指令数 240,349，DiffTest cycle count 99,996，harness guest cycles 100,001。
- checker schema 完全一致。B 移除 3 个物理寄存器与 3 个 RAT snapshot 输入，加入 xrf/frf/vrf 与 8 个 commit_data；其他事件继续原路径。
- 三种子、30,000 周期 fixture 对照原 Preprocess，包含 integer/FP/vector/RAT/commit data、reset、重复目的、skip 和延迟；此项覆盖 CoreMark 不充分触发的 FP/vector 输入组合。
- 仅验证单核完整 DiffTest 配置与本负载；不是所有程序和异常组合的形式证明。

## 完整模型结构

| 指标 | A hardware | B behavior | B/A−1 |
|---|---:|---:|---:|
| 最终 GRH operation | 7,204,065 | 7,037,231 | -2.316% |
| C++ 文件数 | 132 | 129 | -2.273% |
| C++ bytes | 1,264,756,867 | 1,322,684,326 | +4.580% |
| 寄存器 storage slots | 208,964 | 207,725 | -0.593% |
| 寄存器 storage bytes | 590,608 | 580,296 | -1.746% |
| memory objects | 1,921 | 1,922 | +0.052% |
| memory payload bytes | 24,181,499 | 24,187,643 | +0.025% |
| commit writes | 218,994 | 216,237 | -1.259% |
| event-edge slots | 412 | 412 | +0.000% |
| compute supernodes | 63,273 | 65,627 | +3.720% |
| boundary activation edges | 1,977,816 | 2,145,806 | +8.494% |
| binary bytes | 79,101,024 | 82,530,808 | +4.336% |

两组 `kStateShadowCount` 均为 0；当前 emitter 已使用 direct state read、hot clock event 和 commit 优化。
寄存器/storage 与 memory 大小由生成 C++ 的类型/字段统计，不等于动态求值次数。完整图最终 operation 以 activity schedule 产物统计，未重复保存数 GiB 的最终 JSON。
前置 `pre-grh-counts.json` 保留 reg-to-mem 前全部 kind 计数：A/B 分别 5,259,224/5,106,652 operations，286,014/284,680 registers，832/836 memories。

## 局部 fixture 计时

`wolvrix/build/artifacts/behavior-model/adapter-bench-v1/` 保存预热、8 对交替运行、哈希、CSV/JSON。
10,000 周期（含刺激生成和输出哈希），A 平均 2.943445 s，B 0.039692 s，配对 −98.6515%；所有状态哈希一致。
**该 fixture 使用 raw GRH，没有整机 reg-to-mem 和活动调度优化，不能用其百分比预测完整香山。** 它显示高层结构可消除展开成本，但完整图会改变收益。

## 正式整机计时

8 对 AB/BA 与同 binary A/A 控制正在执行；完成后追加全部配对数据和结论。

## 增量更新：8 对 AB/BA 完成

全部正式样本的 NEMU 检查、最终提交签名、CPU/NUMA 和区域负载 gate 通过，未按耗时删样本。

| pair | 顺序 | A 秒 | B 秒 | B/A−1 |
|---:|:---:|---:|---:|---:|
| 0 | AB | 108.209 | 113.046 | +4.4701% |
| 1 | BA | 106.476 | 112.568 | +5.7215% |
| 2 | AB | 105.689 | 112.039 | +6.0082% |
| 3 | BA | 110.439 | 108.647 | -1.6226% |
| 4 | AB | 111.260 | 120.405 | +8.2195% |
| 5 | BA | 105.565 | 115.047 | +8.9821% |
| 6 | AB | 107.184 | 112.949 | +5.3786% |
| 7 | BA | 105.374 | 110.626 | +4.9842% |

A 均值 107.524500 s，中位数 106.830000 s；B 均值 113.165875 s，中位数 112.758500 s。
配对均值 +5.267686%，配对中位数 +5.550039%，固定种子 bootstrap 95% CI [+2.974774%, +7.104820%]；B 更快 1/8。

本轮候选没有实现完整香山加速。A/A 控制另在 `control-aa/` 执行，完成后追加噪声对照；不能用本轮 raw fixture 的 −98.65% 替代整机结果。

## 增量更新：A/A 环境 gate 中止

首轮 `control-aa/` 两组 trace 验证通过，正式 pair00 的第二次运行期间 CPU111 空闲率为 97.6245%，低于运行前约定的 98%；脚本停止，尚未形成任何完整有效 pair。
两次原始 pair00 日志及所有负载记录保留，不按耗时判断有效性。后续 `control-aa-v2/` 复用已完成的功能验证，驱动重新核对 binary、镜像、NEMU、header 和运行库哈希后跳过 trace，重新预热与采集 8 对控制。

## 增量更新：控制驱动隔离监控进程

`control-aa-v2/` 在 smoke 后因 CPU119 空闲率 94.74% 再次中止，没有有效计时 pair。
驱动审查发现 Python 监控/哈希进程继承全机 CPU affinity，可能自行进入被检查区域，因此以上失败不直接归因于其他用户任务。
`control-aa-v3/` 将监控进程限制在区域与 CPU96 SMT sibling 之外，并要求连续三个 5 秒窗口空闲。仿真器仍由 taskset 固定 CPU96，阈值保持 98%，所有旧日志保留。
这只改变环境 gate 的监控进程位置，没有改变 A binary、harness、NEMU 或测量内容；AB/BA 的原驱动全量环境检查已通过。

`control-aa-v3/` 仍在非计时 smoke 后检测到 CPU124 空闲率 96.49%，该结果表明不能把之前的负载全部解释为监控进程自身。
`control-aa-v4/` 保持正式 pair 的 98% 门槛与 15 秒连续空闲检查，非计时 smoke/预热的瞬时区域负载仅记录而不否定功能结果；正式统计只包含 pair 运行。区域 gate 未用于按耗时选择样本，以上尝试均无有效完整 pair。

## 增量更新：按用户要求停止，当前结论

用户指示“可以了，不用再跑了”后，已终止 `control-aa-v4` driver 及其当前 emu 子进程；没有遗留本实验的运行进程。
A/A 仅完成一对：108.108 s / 108.804 s，差 +0.643801%；第二对中途停止，不计入统计。
**A/A 尚不足以给出环境噪声置信区间**，不得把该单对外推成完整控制结果。中止状态及有效 pair 在 `measurement-status.json` 与 `review.json` 保存。

已完成的 A/B 8 对结论保持不变：本版普通 GRH 语义模型功能通过，但平均慢 5.267686%，未达到整机加速目标。
默认维持 hardware。保留高层数组 API、manifest 及显式开启的实验 adapter 以复现数据，不增加 `kBehaviorStateGroup`。

### 对后续性能工作的含义

1. `array/update/read/snapshot` 已把模型作者的代码提升到数组语义层；这种 API 改善本身不等于 runtime 减少。
2. 把延迟从物理 RF 全表移到架构 gather 后面，保持了完整 DiffTest 可见语义，并略减状态与 commit write 数量。
3. 普通 lowering 仍把有序 RAT 更新展开为每行 last-writer 选择网络；为了保留全部退休微操作，不能把 520 个潜在更新误换成更晚的 8 个 RAB 写口。
   本版完整图的边界激活边增加 8.49%、compute supernode 增加 3.72%、C++ 增加 4.58%。这些结构变化与回退相容，但当前没有逐热点计数，不能把回退百分比完全归因于某个算子。
4. 原硬件路径本身已受 reg-to-mem、direct state read 与 commit 优化影响。raw fixture 的巨大差异不代表整机仍有同等冗余。
5. 下一步若继续，应先证明“保留数组及有序更新语义直到后端”能减少这些选择与调度工作；复制同义的专用 Register/Memory 无法自动产生收益。当前不实施更多 lowering 或性能诊断。

### 收尾验证边界

在冻结 v10 构建之后增加了两项 elaboration-only 拒绝检查：`--reset-gen` 分级复位和 disabled/excluded commit 事件不允许进入 commit-rat 模式。
它们不改变本轮有效单核同步复位配置的 RTL 分支；但用户停止进一步运行时，新增 guard 及其小测试尚未编译/执行。
`source-audit.json` 区分冻结的已验证源码、这两项 guard 和 fixture/driver 整理变更。其余已完成验证详见上文；未跑全量回归。

## 增量更新：后续局部阶段完成收尾检查（2026-11-05）

后续用户批准数组分组局部实验后，已补齐 Scala test compile、excluded commit source 和 reset-tree
两项拒绝检查。修正了测试中的不存在参数：Difftest `enabled` 为内部常量，实际测试的是公开
`excluded` 能力，不能表述为已运行一个独立的 disabled 参数用例。
新实现及验证见 [TNO0438](./TNO0438_behavior_state_group_contract_20261105.md)，局部性能见
[TNO0439](./TNO0439_behavior_state_group_local_performance_20261105.md)。
本篇完整香山结果、A/A 中止状态保持不变；后续没有重新跑整机。
