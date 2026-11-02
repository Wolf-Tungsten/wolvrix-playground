# TNO0373：32 分区动态关键路径第一名与 RTL/Chisel 定位

日期：2026-10-29。

## 请求与统计口径

在 [TNO0372 的中文 RTL/Chisel 报告](./TNO0372_grhsim_rtl_to_chisel_path_mapping_20261028.md)
上增加每个分区、每个 clock 的动态第一名。本次对象为 20261028 新默认 clean RTL
流程保留的 seed7 初解，不是恢复版。使用同一份已生成模型及其来源映射。

动态第一名按 batch **实测累计时间**选择，计算和状态提交都参与，不能用静态
工作量、单次最长调用或关联源码数量代替。报告提供两个范围：

- 全局稳定拖尾采样：仅计两次独立 wrapper discovery 都由该分区最后完成的步骤。
- 分区全部采样：计该分区所有采样步骤，包括不拖尾的步骤。

每项记录两次独立批次探针的第一名和合计第一名、采样步数、调用数、平均/最大
单次时间、首轮/提交后/后续传播时间、入口零掩码时间占比。并列与无样本均显式
记录，不用静态第一名填补。占比分母为同分区、同 clock、同范围的所有批次采样
时间；同一输入步骤在两次重复中分别计数，不是两个不同输入。

## 全分区诊断

输出目录：

```text
build/xs/grhsim32_fresh_rtl_20261028/critical-path-dynamic-all32_20261029_v2/
```

- node030，CPU96–127，32 线程，all-spin、preferred NUMA、ASLR off。
- reset 后预热 1,000 cycles，采集 10,000 cycles；每 64 cycles 成对采样两个半周期。
- 2 次 wrapper discovery + 32 × 2 次 batch probe，共 **66 次**，全部功能检查通过。
- discovery 代码页 85,983,232 B、batch-probe 代码页 90,177,536 B，所有运行完整 THP。
- 两份诊断二进制 7,272/7,272 个 compute 入口均 64B 对齐。
- discovery 只替换 4 个 wrapper；batch probe 替换 4 个 wrapper 和 32 个 eval dispatcher。
  compute/commit 对象内容与 archive 成员顺序保持一致。
- 66 个 trace 的身份已与 `runs.json` 核对，结果见 `run_verification.json`。

旧探针只支持单活动字节，全分区预检发现 p20/b97 读取两个活动字节，因此第一
次全分区构建被拒绝；没有产生该批次的错误计时。新增通用多字节入口支持：一个
batch 仍只有一个时间区间，记录各入口掩码的按位或，用 `word=UINT32_MAX`
标明不是单个物理字节，manifest 保留所有字节及 dispatch mask。它只保留入口
全零/非零证据，不声称测得每个 group 的实际执行。修正后在独立 v2 目录完成采集。

已有精确 ASC sidecar 只覆盖 p0/p5/p27，本轮没有为了增加动态排名而重建全设计
ASC。其它分区的原始 ASC 保持未知，动态 batch 到 partition/phase 和 RTL 来源
仍来自完整生成计划，不推断或填造 ASC。

## 结果

32 个分区 × 两个 clock，共 **64 项**全部获得本分区动态第一名；**58/64** 在
两次重复中第一名一致。独立 discovery 的 20,000 个模型 step 中，有 19,263 个
eval step 的最后完成者一致。按 stride 采样后，只有 **16/64** 项实际采到本分区
稳定拖尾步骤；其中 **14/16** 的第一名在两次批次探针中一致。其余 48 项明确写成
“没有稳定拖尾采样”，不能解释为整个窗口内从未拖尾。

下表是全局稳定拖尾采样范围内的几个第一名；各行对应不同的分区/clock，累计时间
还受到各自拖尾样本数影响，不能直接解释为能缩短多少 walltime。

| 分区 | clock | 第一名 | 累计时间 | 本分区批次时间占比 | 采样步数 | 重复第一名 |
|---|---:|---|---:|---:|---:|---:|
| p0 | 1 | commit 345 | 475.595 µs | 5.28% | 280 | 2/2 |
| p0 | 0 | compute 7 | 90.527 µs | 2.05% | 258 | 1/2 |
| p27 | 0 | compute 215 | 68.491 µs | 20.62% | 10 | 2/2 |
| p5 | 1 | commit 308 | 54.439 µs | 7.82% | 16 | 2/2 |

关联 RTL/Chisel 示例：

- p0/clock=1/b345 包含 `LogPerfEndpoint`、`MSHR_64`、`Directory_Anon`、`MissEntry`
  等状态提交。代表位置包括 `MSHR_64.sv:722` 的 `req_isBop`、
  `Directory_Anon.sv:806` 的 `tagAll_s2_1`。MSHR 存在多个 Chisel 实现，保留候选。
- p27/clock=0/b215 的静态来源主要为 `Sbuffer`、`TLBFA_3/2/1`。例如
  `Sbuffer.sv:19947` 的 `flow_1/isVSLine_1`，`TLBFA_3.sv:5162` 的 `hitVecReg_1_24`；
  Chisel 候选为 `xiangshan.mem.Sbuffer`（`Sbuffer.scala:190`）和
  `xiangshan.cache.mmu.TLBFA`（`TLBStorage.scala:86`）。
- p5/clock=1/b308 包含 `LogPerfEndpoint`、`OthersEntry_6/24/18`，可查看
  `OthersEntry_6.sv:1252` 的 `entryReg_status_srcStatus_0_srcState` 与
  `:1514` 的 `entryReg_status_issueTimer`。Chisel 对应候选在 `OthersEntry.scala`。

以上是同一个实测 batch 的源码关联集合，**不是已测得的逐信号路径**。代表信号
按静态来源量较大的模块选择；不能把 batch 时间按来源量分摊，也不能据此认定
其中某个模块消耗了多数时间。Chisel 匹配仍是源码证据，不是 elaboration 实例追踪。

## 入口与产物

可复用命令：

```bash
make xs_grhsim_critical_path XS_GRHSIM_CRITICAL_ARGS='--output build/xs/critical-all32 --part-limit 32'
```

只重新生成已采集数据的报告：

```bash
python3 scripts/grhsim_critical_path.py report --output build/xs/grhsim32/critical-path-dynamic-all32_20261029_v2
```

- [中文交互报告](../../build/xs/grhsim32_fresh_rtl_20261028/critical-path-dynamic-all32_20261029_v2/report.html)
- [动态第一名清单](../../build/xs/grhsim32_fresh_rtl_20261028/critical-path-dynamic-all32_20261029_v2/dynamic_top1.md)
- [动态 CSV](../../build/xs/grhsim32_fresh_rtl_20261028/critical-path-dynamic-all32_20261029_v2/dynamic_top1.csv)
- [动态 JSON](../../build/xs/grhsim32_fresh_rtl_20261028/critical-path-dynamic-all32_20261029_v2/dynamic_top1.json)

HTML 首先显示可切换范围的动态第一名表，点击后展开 RTL 行、Chisel 候选、两次
重复结果和分轮次时间；静态第一名仍独立保留，完整覆盖 64 个分区/clock 组合。
JSON/CSV 中包含每次重复结果及排名状态，Markdown 提供紧凑清单。

验证：25 项 Python/小型 C++ 探针测试通过，包括按累计时间排序、两个 clock 与
两个统计范围隔离、重复排名不一致、并列、无样本、入口零掩码、最大值不误累加、
多活动字节调用一次且保留计算语义；实际浏览器通过范围/clock 切换、RTL/Chisel
展开和缺失样本显示检查。Python 编译及 `git diff --check` 通过。

本次是诊断报告交付，没有进行 RTL 改写或新的性能优化，不据诊断进程时间宣称
普通 walltime 收益。
