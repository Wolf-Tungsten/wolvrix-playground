# TNO0397：PopCount 的紧凑布局替换与香山单线程实测

日期：2026-11-03。本文记录在优先编码器实验之后，对 XiangShan 中 `PopCount` 的完整
Chisel → Verilog → GRH → C++ → emu walltime 流程。重点是区分两种输入：原本已经是
紧凑 `UInt` 的输入可以直接交给仿真原语；`Vec[Bool]`、`Seq[Bool]` 等分布式输入保留
Chisel 的硬件实现，避免为了使用原语而先把紧凑位向量拆开。

## 选择规则和源码修改

utility 层新增同名 `utility.PopCount` 重载。它保持 Chisel 的接口和结果宽度：

```text
PopCount(UInt/Bits)       → packed layout；popcount 模式下可用 intrinsic
PopCount(Vec[Bool]/Seq)   → distributed layout；始终保留 chisel3.util.PopCount
```

生成参数仍然是单次 elaboration 的 `--wolvrix-sim-primitives none|popcount`，默认关闭。
PopCount intrinsic 的保留标识是 `wolvrix_popcount_v1_w<N>`；纯组合结果在 Wolvrix 中
落成 `kCountOnes`，机器字以内使用 `std::popcount`，更宽输入使用带尾字掩码的多字扫描。
生成的 native C++ 不保留该 DPI 调用。

为避免把 `UInt` 拆成 `Seq`，对已确认的调用点进行了布局改写：

| 文件 | 处理 |
| --- | --- |
| `frontend/ibuffer/IBuffer.scala` | `io.in.bits.valid.asBools.take(i)` 改为 `io.in.bits.valid(i - 1, 0)`；`validVec.asBools` 改为 `PopCount(validVec)` |
| `frontend/ifu/Ifu.scala` | `dealInstrValid`、`rawInstrEndVec`、`enqVec` 的计数直接作用于 `UInt` slice 或完整 `UInt` |
| `frontend/ifu/IfuPerfAnalysis.scala` | 保持已有打包输入，显式使用 utility 入口 |
| DCache、Sbuffer 及同名导入冲突文件 | 显式消歧；`Vec/Seq` 调用仍由 utility fallback 到硬件实现 |

其余 48 个同时导入 `utility._` 和 `chisel3.util._` 且调用 `PopCount` 的 XiangShan 文件
只增加显式 `import utility.PopCount`，用于保证同名 utility 的解析稳定；这不改变它们的
输入布局。第三方库没有反向依赖 utility。

## 完整覆盖结果

A 为 `none`，B 为 `popcount`；两版都重新从当前 Chisel 源码生成 RTL。

| 记录 | A | B |
| --- | ---: | ---: |
| simulation primitive 总记录 | 8,704 | 8,704 |
| `PopCount.Bits`（packed） | 1,095 | 1,095 |
| 其中进入 intrinsic | 0 | 1,095 |
| `PopCount.Vec`（distributed） | 1,279 | 1,279 |
| `PopCount.Seq`（distributed） | 5,861 | 5,861 |
| distributed 调用保留硬件 | — | 7,140 |

B 的 RTL 生成出 41 种实际宽度的 `WolvrixCountOnes<N>`，包括 1–36、95、128、224、256
和 4096。没有按 16–64 位事后筛选；宽度分布由香山当前配置的真实调用决定。

packed 调用最多的源码模块是：

| 模块 | packed PopCount 记录 |
| --- | ---: |
| `backend.datapath.OldestArbiter` | 276 |
| `backend.issue.IssueQueueImp` | 156 |
| `backend.datapath.IntRFBankReadArbiter` | 156 |
| `backend.issue.AgeDetector` | 84 |
| `backend.Region` | 84 |
| `frontend.ifu.Ifu` | 73 |
| `backend.rename.Rename` | 39 |
| `frontend.ibuffer.IBuffer` | 38 |
| `mem.prefetch.MutiLevelPrefetchFilter` | 38 |

因此这不是只测试 IBuffer/Ifu 的局部候选；主要样本来自后端仲裁、年龄选择、Region 和
prefetch 结构。最常见的 packed 宽度是 1（313 次）、2（265 次）、3（112 次）、16（86 次）
和 8（61 次）。此外有 224、256、4096 位等宽调用。

## GRH 和 native C++ 证据

生成后的 B 图没有保留 `kCountOnes` 以外的 PopCount DPI 依赖。模型中可见：

```cpp
const std::uint8_t next_value = grhsim_popcount_u64(..., width);
const std::uint16_t next_value = grhsim_popcount_words(..., 4096);
```

A/B 的结构指标如下：

| 指标 | A | B | B 相对 A |
| --- | ---: | ---: | ---: |
| native emu | 79,092,832 B | 78,879,128 B | -0.270% |
| model C++ 源码 | 1,264,602,979 B | 1,257,384,369 B | -0.571% |
| C++ 源文件数 | 132 | 130 | -2 |
| compute supernodes | 63,273 | 62,538 | -1.162% |
| common-expression compute nodes | 582,659 | 581,797 | -0.148% |
| `kCountOnes` 操作记录 | 0 | 15 | — |
| 生成 C++ 中的 popcount helper 引用 | 0 | 961 | — |

这说明原语确实进入了 Wolvrix 的普通组合数据流，并且静态模型规模、二进制大小和
compute supernode 数量都下降；但这些静态下降没有直接转化为运行时收益。

## 单线程功能和 walltime

使用 Wolvrix 专用 native single-model 流程。A/B 在 node030 上编译，正式测量固定
CPU96，`C100000`，8 对交替 AB/BA；没有使用 N=K=1 的多线程流程。每版先做 smoke、两组
独立 100,000 周期 Difftest trace 和 warmup。

功能和运行环境检查全部通过：

- 两组 trace 各 100,000 条记录，A/B trace SHA256 完全一致；
- `pc=0x80000c0c`，`instr_count=240349`，`cycle_count=99996`，`guest_cycles=100001`；
- 所有正式样本为单线程，CPU96 亲和性和 SMT sibling 检查通过；
- native binary、依赖库和 NEMU 页面 locality 检查通过。

正式 walltime：

| 指标 | 数值 |
| --- | ---: |
| A 平均 Host time | 115.380 s |
| B 平均 Host time | 116.14725 s |
| B 相对 A 的配对均值 | **+0.665717%** |
| 配对中位数 | +0.683076% |
| 固定种子 paired bootstrap 95% CI | **[+0.421713%, +0.925537%]** |
| B 更快的配对数 | 0 / 8 |

8 个配对的 Host time（秒）如下：

```text
pair 0: A 116.141  B 116.882  (+0.6380%)
pair 1: A 116.158  B 116.576  (+0.3599%)
pair 2: A 116.050  B 116.895  (+0.7281%)
pair 3: A 115.563  B 116.903  (+1.1595%)
pair 4: A 115.255  B 115.605  (+0.3037%)
pair 5: A 114.379  B 115.810  (+1.2511%)
pair 6: A 114.226  B 115.059  (+0.7293%)
pair 7: A 115.268  B 115.448  (+0.1562%)
```

本轮 B 在 8 对中均慢，区间没有跨过零。这是当前 PopCount 全 packed 替换策略的可靠
回退证据，但还不能把回退归因到某一个 Chisel 模块或单个 `std::popcount` 指令。

## 对回退原因的判断

目前直接证据支持以下判断：

1. 回退不是因为把 `Vec/Seq` 误替换成了 intrinsic；7,140 个分布式调用仍保留硬件，
   `asBools.take` 的紧凑布局问题也已经在 IBuffer/Ifu 中改写。
2. B 的静态图和代码体积更小，说明“代码变大”不是主因。
3. B 将大量 1–3 位的小型 packed PopCount 变成 `kCountOnes`，其中 OldestArbiter、
   IssueQueue 和 IntRFBankReadArbiter 合计 588 次。对这种小宽度，helper 的输入截断、
   结果宽度处理和活动/变化检测成本可能超过原有硬件归约树在 GrhSIM 中的成本。
4. `kCountOnes` 是后端可识别的新操作，替换后会改变 common-expression、activation edge、
   supernode 边界和调度形态；compute supernode 虽减少 735 个，运行时固定点活动的形状
   可能因此变差。

第 3、4 点是待验证的机制假设，不是由本轮 walltime 单独证明的因果结论。下一步应做
独立消融，而不是凭 walltime 选择位宽：

- 保留 1–3 位硬件、只替换 4 位以上；
- 只替换 `Ifu/IBuffer/BusyTable/BloomFilter` 等明确的宽 packed 调用；
- 分别测量 `std::popcount` helper、输入打包、结果写回和活动传播；
- 对 OldestArbiter、IssueQueue、IntRFBankReadArbiter 做源级局部 A/B，确认小宽度和高
  重复调用是否是回退主要来源。

在这些消融完成前，不把 PopCount intrinsic 设为默认开启；当前应保留“布局先于函数名”
的替换门，并把本轮全 packed 结果作为回退基线。

## 复现产物

- [A/B 生成目录](../../build/xs/popcount_20261103_v1/)
- [单线程 comparison summary](../../build/xs/popcount_20261103_v1/comparison-v1/summary.json)
- [8 对配对 CSV](../../build/xs/popcount_20261103_v1/comparison-v1/pairs.csv)
- [primitive coverage A](../../build/xs/popcount_20261103_v1/A/chisel-home/build/simulation_primitives.json)
- [primitive coverage B](../../build/xs/popcount_20261103_v1/B/chisel-home/build/simulation_primitives.json)
- [机器可读汇总](../../wolvrix/build/artifacts/priority-intrinsic/priority-intrinsic-popcount-report.json)

生成和比较命令：

```bash
python3 wolvrix/build/artifacts/priority-intrinsic/xs_generate_popcount_v1.py
python3 wolvrix/build/artifacts/priority-intrinsic/xs_finish_popcount_v1.py
python3 wolvrix/build/artifacts/priority-intrinsic/xs_compare_popcount_v1_wait.py
```

