# TNO0441：分组 RAT 的完整 S3 构建与 NEMU/trace 验收（2026-11-05）

## 配置与产物

承接 [TNO0440](./TNO0440_grouped_rat_s3_integration_20261105.md)。
完整产物根目录 `build/xs/behavior_grouped_rat_20261105_v2/`；A 指向 v1 已完成的硬件基线，B 复用
v1 的已核验 RTL，在修正 split-Verilog 文件末尾换行匹配后重新 emit/compile。正文哈希校验仍然有效。
native 编译器、编译参数和全部 Chisel 生成源码一致；A 不执行分组 importer。该单文件兼容修正的
差异和复用依据保存在 `source-audit.json`，不将两个源码清单表述为逐文件完全相同。

| 项目 | A | B |
|---|---|---|
| Chisel 模型 | 原 hardware S3 | commit-rat |
| 状态 lowering | ordinary | grouped，仅 RAT |
| 生成/采集/编译/运行 DiffTest | 全开 | 全开 |
| harness | NO_DIFF=0 | NO_DIFF=0 |
| NEMU | 开启 | 开启 |
| intrinsic | none | none |
| 配置 | 单核 TLConfig | 单核 TLConfig |

B 保留 520×4 条潜在退休更新顺序，不构造逐行 last-writer 网络。四个 RAT 数组是
32/32/32/1 行、元素均 8 位。物理 RF shadow、gather 后的架构快照与延迟继续使用普通状态，
其他 DiffTest 事件继续原路径。

两组生成相同的 canonical `difftest-state.h`：7,972 bytes，SHA256
`0b988bfcd6f8d55117d40f592d6ff59e9f1de87cc63fa774cb992c155805ec65`。

## 构建与结构

两组均通过完整 frontend、XMR、hier-flatten、reg-to-mem、activity schedule、C++ emitter 和链接。
B 的 flatten 后 Python ownership 检查及 emitter 内 native 检查均通过，组合环为零。

| 指标 | A | B |
|---|---:|---:|
| 最终 GRH operations | 7,204,065 | 6,658,343 |
| compute supernodes | 63,273 | 63,658 |
| boundary activation edges | 1,977,816 | 2,003,145 |
| commit writes | 218,994 | 216,110 |
| register state storage bytes | 590,608 | 580,104 |
| memory payload bytes | 24,181,499 | 24,187,740 |
| state shadows | 0 | 0 |
| event-edge slots | 412 | 412 |
| C++ files | 132 | 130 |
| C++ bytes | 1,264,756,867 | 1,262,431,052 |
| emu bytes | 79,096,928 | 78,676,200 |

A emit 1,480.726 秒，B 的成功 emit 2,307.611 秒。B 在 Python sidecar 导入中额外保存和校验完整图，
层次图约 4 GiB、flatten 后检查图约 6.4 GiB；当前实现有明显的构建时间/内存成本。
这些时间不计入仿真 walltime。A 的主要静态结构与 TNO0437 的原硬件基线一致。

binary SHA256：

```text
A 66cc0e7af86dedf6b4ac111dceda40a50a39129a3bf26390f72572835bd86039
B 0bd7bfabd553d0fc650bcb9f9d6812d56d81a34a9726a934c5675fd35669e59d
```

## 完整 S3 功能门

node030 CPU96、NUMA1、ASLR off、单线程，运行前检查 CPU96–127 与 SMT sibling 的空闲状态。

- A/B 各 10,000 周期 smoke 正常达到周期上限，PC `0x800027c6`、提交 458 条指令、DiffTest cycles 9,996。
- A/B 各 seed 0、1 的 100,000 周期均通过 NEMU。
- 每组 trace 100,000 条记录，每条 6,216 bytes；有效字段比较通过，原始文件哈希也相同。
- 四份 trace 的 SHA256 都为 `fab40cec7bebe25138496f603a31cd12dbe66363bef7e98e35c500bfe1d76acd`。
- 最终 PC `0x80000c0c`，提交指令数 240,349，DiffTest cycles 99,996，harness guest cycles 100,001。
- 四次长验证都观察到 NEMU 已映射，CPU affinity、单线程及 NUMA locality 均通过。

镜像为 `coremark-2-iteration.bin`，SHA256
`c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`；NEMU SHA256
`094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`。

验证覆盖本次单核配置和 CoreMark；两个 seed 产生了相同轨迹，不能把它们当成两个不同的程序覆盖。
FP/vector/重复写/flush/skip/延迟的随机局部参考检查见 TNO0440，不等同于所有 RVV 指令和配置的整机证明。

## 记录与下一步

`comparison/manifest.json` 保存 binary、镜像、NEMU、header 和运行模式身份；
`comparison/trace-s0.json`、`trace-s1.json` 保存逐文件比较；各 `A|B/runs/` 保留原始日志、
trace、NUMA/CPU 与运行库记录。`review.json` 保存完整结构统计。

功能门通过后，开始独立的预热和 8 对 AB/BA，关闭 trace、footprints 和诊断计数；
正式性能结论另行归档。默认 hardware/ordinary 保持不变。

## 勘误：最终 GRH 操作数

上表 B 的 6,658,343 是 activity-schedule 的 `eligible_ops`，误写为最终 GRH operations。
最终 `activity_schedule_supernode_stats.json` 和日志 `graph_ops` 均为 **6,870,723**；
相对 A 的 7,204,065 减少 **4.6271%**，不是约 7.6%。该统计文件与构建时 manifest 哈希一致，
模型和 binary 没有发生变化。其余表项不变，性能测量见
[TNO0442](./TNO0442_grouped_rat_s3_performance_20261105.md)。
