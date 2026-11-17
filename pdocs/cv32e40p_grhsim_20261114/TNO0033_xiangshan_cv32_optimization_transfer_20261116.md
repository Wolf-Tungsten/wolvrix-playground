# TNO0033：CV32 优化在 XiangShan 上的固定对照

**固定八对结果：CV32 保留优化组合迁移到 XiangShan 后，外部 walltime 增加 7.1702%，95% CI [+6.8035%, +7.5028%]，8/8 对更慢。功能和完整窗口内 DiffTest 轨迹均通过。**

本轮按用户要求，将 CV32 调查前的 GrhSIM 与 TNO0032 保留配置用于同一 XiangShan 模型。测试为 kunminghu-v3 `DefaultConfig`、guest 单核、native 单线程 GrhSIM，性能运行固定 node030 CPU96。没有 RepCut 分区、运行反馈生成、参数搜索或按性能组合候选。

## 计时前冻结的比较定义

- before：Wolvrix `74d80cf`，CV32 优化系列之前。使用该版本的生产库和头文件。
- after：Wolvrix `8523dc1`，启用 TNO0032 的保留组合，包括 event regions/shared regions、conditional mux cones/input cache、shared equality families、covered state views 及 composition/inline。其他默认关闭的实验选项保持关闭。
- 两侧从同一个冻结 `pre_reg_to_mem.json` 开始，执行相同的 two-state simplify（不保留无用声明符号）、ordered reg-to-mem，再 schedule/emit。这样包含本次简化器中的 concat/slice 规则，且不混入重新 elaboration 的 RTL 差异。
- 两侧均使用 max compute node/supernode 108；after 为满足 event-regions 的完整 compute node 要求，关闭原有 oversized-node splitting。此项属于优化后配置的必要变化，不能宣称两侧 schedule 完全相同。
- 模型 Clang 23.1.2、`-std=c++20 -O3 -march=native`；harness O3；完整 DiffTest/NEMU；无 waveform、运行计数插桩、PGO 或 BOLT。

原生产库的归档基于 `2e1d37e` 加当时尚未提交的父规则默认开启补丁；脚本逐字节验证此生产代码差异正好等于 `2e1d37e..74d80cf`。旧、新辅助工具分别使用各自头文件，以避免 `ActivityScheduleOptions` 新字段造成 ABI 不匹配。DiffTest 提交和 generated schema 相同。

“完整 compute node”是新增 event-regions 实现的兼容性约束：其归属表假设每个 node 只属于一个原调度组。它不是硬件语义上的要求，也不禁止多个完整 node 合并。历史 XiangShan 日志虽然开启了 oversized-node splitting，实际却记录 `oversize_compute_nodes=0 split_supernodes=0`；因此需要区别开关差异与真正发生的拆分，不能预先将性能变化归因于关闭该选项。

输入、工具、编译器和配置身份见 [inputs.json](../../build/xs/cv32-transfer-20261116-v3/inputs.json)，完整预先固定规则见 [policy.json](../../build/xs/cv32-transfer-20261116-v3/policy.json)。重放工具：[C++ emitter](../../scripts/xiangshan_cv32_emit.cpp)、[driver](../../scripts/xiangshan_cv32_compare.py)、[report](../../scripts/xiangshan_cv32_report.py)。

## 功能与性能协议

先执行两侧 10k-cycle smoke，再执行 seed 0、1 各一组 100k-cycle DiffTest trace，对比全部有效字段、记录顺序及周期覆盖；任一失败均不进入正式性能统计。性能窗口固定 `-C 100000`，镜像为 `coremark-2-iteration.bin`，不将此固定窗口称为完整 CoreMark 完成。

两侧各预热一次，固定八对 AB/BA 交替；主指标 Host time，并并列报告外部进程 walltime。使用 seed 20261102、10,000 次配对 bootstrap 的 95% CI。CPU96、NUMA1、单线程、关闭 ASLR；为 binary、NEMU 和共享库创建同内容私有副本并在目标 NUMA 节点预置页，持续验证线程、CPU 与页面位置。沿用既有 XiangShan 协议，不以外部 CPU/sibling idle 做准入筛选，仍记录实际 CPU96/288 活动，保留所有正式样本。

## 构建适配记录

初始 v1 在辅助工具编译阶段缺少 Slang include 路径，未发射模型或运行模拟器；日志保留在 `build/xs/cv32-transfer-20261116-v1/`。v2 补齐头文件，并在发射前确认 event-regions 必须关闭 oversized-node splitting。未使用任何仿真结果修正规则。

v2 在生成源码对照时发现，旧 emitter 的 `storage_ref_aliases` 只读取环境变量，属性表中的同名值不会生效，导致两侧都使用了默认开启。v2 在任何仿真运行前撤回，保留日志和撤回记录。v3 将两侧公共环境显式设为 `WOLVRIX_GRHSIM_STORAGE_REF_ALIASES=0`，恢复既有 XiangShan 配置；优化规则、预算和候选集合均未调整。

现有比较/NUMA/功能门的 39 项 Python 回归通过，[日志](../../build/xs/cv32-transfer-20261116-v3/runner-tests.log)。

## 静态结果

优化前的 140 个生成文件（C++/header/Makefile）与历史基线在仅规范化 `// op`、`// value` 中的自动符号名后完全相同。numeric value ID、实际代码、header 和 Makefile 均保留；用于编译的文件没有做规范化改写。[源码复现检查](../../build/xs/cv32-transfer-20261116-v3/baseline-source-reproduction.json)。137 个模型目标文件也与历史基线逐字节相同，[object 检查](../../build/xs/cv32-transfer-20261116-v3/baseline-object-reproduction.json)。harness 在当前相同环境下为两侧重新编译；最终 ELF 含构建时间／路径差异，不声称整个历史二进制逐字节相同。

| 静态结构 | before | after |
| --- | ---: | ---: |
| 调度组 | 77,387 | 97,550 |
| commit 组 | 346 | 346 |
| 生成 batch 函数 | 97 | 97 |
| 有 scalar change check 的不同值 | 762,833 | 727,582 |
| scalar change check 源码位置 | 762,833 | 738,086 |
| scheduler C++ bytes | 1,532,843,041 | 1,511,648,589 |
| conditional mux cones | 0 | 11,563 |
| conditional mux input caches | 0 | 215 |
| shared equality families | 0 | 117 |
| covered state views（含复合） | 0 | 2,870 |
| 复合表达式 inline / notify | 0 / 0 | 1,446 / 10 |

条件锥的不同分支可能重复同一个结果的判变位置，因此 after 的源码检查位置数大于不同值数量。这里只报告静态数量，没有当作每周期运行次数。

单终点规则构建 13 个区域、覆盖 20,425 个操作，8 个超规模区域回退。共享规则构建 6,542 个区域、覆盖 1,078,464 个操作；48 个超规模集合回退，771 个节点超过 endpoint 上限。它还细分 10,388 个原混合组，因而最终组数增加；边界减少不能保证净时间收益。两侧实际 oversized-node split 均为零，commit 顺序检查通过。

[完整结构统计](../../build/xs/cv32-transfer-20261116-v3/structure.json)。

最终 ELF `.text` 为 before 91,922,786 B、after 90,877,282 B（约 −1.14%）。中间值槽位数 1,261,860 → 1,211,198，按声明类型计算的数据载荷为 2,927,960 → 2,837,764 B；不包括 state、缓存、metadata 和对齐。静态大小不作为运行性能的代用品。[ELF sections](../../build/xs/cv32-transfer-20261116-v3/elf-evidence/sections.json)、[storage](../../build/xs/cv32-transfer-20261116-v3/storage-summary.json)。

## 执行状态

两侧构建、功能门、固定八对性能测量和离线分析均完成。没有修改 Wolvrix、XiangShan 或 DiffTest 生产代码／默认配置。

## 功能门结果

两侧 10k smoke 通过；seed 0、1 各 100k 周期的 99,999 条有效 DiffTest 记录全部一致。完整 NEMU 检查、UART、cycle 覆盖和终点签名均通过：PC `0x80000c1a`，`instrCnt=250838`，`cycleCnt=99995`，`Guest cycle spent=100001`。实际停止原因是周期上限，不是 CoreMark GOOD TRAP。见 [功能门](../../build/xs/cv32-transfer-20261116-v3/functional-gate.json)。

## 正式性能结果

所有正式样本均在 node030 CPU96、NUMA1、单线程、ASLR 关闭下完成，完整 DiffTest 开启，trace／诊断插桩关闭。16 个样本全部通过功能和 placement/locality 门，没有重试、删除或新增轮次。378 个正式 NUMA 快照通过检查；CPU288 sibling 的整段空闲率为 99.9917%–100%。

| 指标 | before `74d80cf` | after `8523dc1` 保留组合 | after/before 配对变化 | 95% CI |
| --- | ---: | ---: | ---: | --- |
| Host time 均值 | 112.184500 s | 120.233625 s | +7.1770% | [+6.8101%, +7.5094%] |
| 外部 walltime 均值 | 112.245367 s | 120.291183 s | **+7.1702%** | **[+6.8035%, +7.5028%]** |

| 对次 | 顺序 | before 外部秒 | after 外部秒 | 配对变化 |
| --- | --- | ---: | ---: | ---: |
| 1 | AB | 113.264407 | 121.243100 | +7.0443% |
| 2 | BA | 112.929653 | 121.344473 | +7.4514% |
| 3 | AB | 112.988612 | 120.121664 | +6.3131% |
| 4 | BA | 110.944369 | 119.359526 | +7.5850% |
| 5 | AB | 111.546320 | 120.178931 | +7.7390% |
| 6 | BA | 112.253233 | 120.211621 | +7.0897% |
| 7 | AB | 111.631521 | 120.205452 | +7.6806% |
| 8 | BA | 112.404823 | 119.664694 | +6.4587% |

A=before，B=after。变化是逐对比值的均值，不把历史绝对时间作为分母，也不将均值之比误当配对统计。该结果仅限这份 DefaultConfig、CoreMark 100k 周期窗口和冻结组合，不代表每条新增规则单独都会退化，也不是所有 XiangShan 工作负载的结论。

## 结构解释与范围

详细离线证据单列为 [TNO0034](./TNO0034_xiangshan_transfer_cpp_elf_analysis_20261116.md)：compute 活动字检查 +25.88%、组入口检查 +27.08%、活动数组更新源码位置 +9.28%；最终 compute 静态条件跳转 +12.52%，而全部指令仅 −1.39%、带内存地址操作数的指令仅 −1.74%。入口栈减法中位数 1,304→2,048 B，最大值 6,008→20,728 B。

这支持优先调查区域细分、通知维护与条件控制流的叠加成本；尚没有动态频率／PMU 归因，不能把 7.17% 按这些项目精确分摊。空组体仅由 456 增至 613，是明确的组合缺口，但不是单独解释退化的充分依据。现有生产默认配置保持不变。

## 构建成本、身份与复现

| 单次构建记录 | before | after |
| --- | ---: | ---: |
| 读图／简化／调度／发射合计 | 607.074 s | 817.303 s |
| 模型及 harness 编译／链接 | 276.420 s | 278.392 s |
| ELF bytes | 99,860,520 | 98,937,744 |

构建期间两侧任务并发，数字仅是本次记录，不能当作严格配对的构建性能结论。

- before ELF SHA256：`638c464fe763f24001e5950b885321f6fbd8fab42e1c7996dfe8d6e4f9b02b22`
- after ELF SHA256：`9ce5816e9be2b774e69deda53b1343ee18f293b2475bd85a9a99ac5f26408da5`
- [最终机器可读报告](../../build/xs/cv32-transfer-20261116-v3/report.json)
- [配对汇总](../../build/xs/cv32-transfer-20261116-v3/paired/summary.json)、[CSV](../../build/xs/cv32-transfer-20261116-v3/paired/pairs.csv)、[原始日志与监控](../../build/xs/cv32-transfer-20261116-v3/paired/)

使用新目录复现，prepare 在工作区执行，两个 build 和 measure 在 node030 执行；measure 内部先验证两组 trace 再计时：

```sh
python3 scripts/xiangshan_cv32_compare.py prepare --output build/xs/cv32-transfer-reproduce
python3 scripts/xiangshan_cv32_compare.py build-before --output build/xs/cv32-transfer-reproduce
python3 scripts/xiangshan_cv32_compare.py build-after --output build/xs/cv32-transfer-reproduce
python3 scripts/xiangshan_cv32_compare.py measure --output build/xs/cv32-transfer-reproduce
python3 scripts/xiangshan_cv32_report.py --output build/xs/cv32-transfer-reproduce
```

所有 frozen input、生成源文件和 binary 在正式测量前后重新校验；报告脚本只读取产物。此次没有做新的优化默认值决策或运行反馈选优。

最终统计、文件身份、功能签名、运行位置与文档链接的复核见 [validation.json](../../build/xs/cv32-transfer-20261116-v3/validation.json)。
