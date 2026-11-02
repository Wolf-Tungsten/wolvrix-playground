# TNO0370：GrhSIM RTL 关键路径首版实现与香山诊断

## 范围

新增独立入口 `make xs_grhsim_critical_path`，读取已完成的 clean 32 线程产物，
生成来源映射、静态组合路径、运行时 phase/batch 追踪和 JSON/CSV/HTML 报告。
沿用保留阶段的完整生成配置、编译器和原计算对象；默认生产构建不启用诊断。
本轮没有更换划分、改写香山 RTL、更新性能最佳线或报告新增 walltime 收益。

使用对象是 [TNO0368](./TNO0368_grhsim_fresh_rtl_full_flow_result_20261028.md)
已经完成的 fresh RTL clean 产物，不是重新执行一遍全量 clean build。
本轮另外在小型 RTL fixture 上实际运行了 Slang → GRH 与 Verilator 构建。

## 实现

- `scripts/grhsim_critical_path.py`：独立 orchestrator；自动选择诊断分区；核验生成计划、
  输入身份、archive 成员、64 字节对齐、功能与实际页面模式。
- `scripts/grhsim_source_export.hpp`：在既有 execution-plan 工具中显式打开的静态导出。
  组合路径在 register/latch/memory/DPI/system-task 边界处截断。
- `scripts/grhsim_source_map.py`：规范化路径和 source span ID；操作、value、group、
  active ID、phase、batch、RTL 关联；实际跨分区 copy 与 input-bit targets。
- `tools/grhsim32/source_asc.cpp`：复用原始 ASC builder，用 symbol、kind、result symbols
  和 assignment 精确回查诊断分区的原始 ASC。未匹配操作保持未知。
- `scripts/grhsim_path_trace.hpp`、`grhsim_path_instrument.py`：只替换 wrapper 和所选分区
  eval dispatcher；原始 compute/commit 对象保持逐字节不变。
- `scripts/grhsim_path_report.py`：绝对完成时间、最长函数体、exclusive margin 分开统计；
  用两个 discovery run 一致的标签分析 batch，避免让插桩本身选择热点。
- `tools/grhsim32/rtl_rewrite.cpp`、`scripts/grhsim_rtl_rewrite.py`：Slang AST allowlist、
  热点门控、独立 RTL patch、固定输入逐周期差分验证。首个规则仅处理安全的无符号全宽静态 slice。

通用使用说明见 [关键路径与改写指南](../../wolvrix/docs/emit/grhsim-critical-path.md)。

## 正式诊断产物

```text
build/xs/grhsim32_fresh_rtl_20261028/critical-path-thp-v1/
  report.html
  report.json
  critical_steps.jsonl
  mapping/source_map.json
  mapping/batch_map.csv
  mapping/mapping_summary.json
  mapping/operation_map.jsonl
  mapping/operation_asc_map.jsonl
  discovery/
  batch-probe/
  runs.json
```

配置：node030 CPU 96–127、32 lanes、all-spin、preferred NUMA、ASLR off；
Clang 23.1.2/O3/native，原模型编译选项及 SLP 保持原状。预热 reset 后 1,000 cycles，
采集 10,000 cycles，两个独立重复；batch 每 64 cycles 采样一对半周期。

自动选中 p0、p27、p5，两个 discovery run 加每个分区两个 batch run，共 **8 次运行**。
8 次均通过 NEMU、周期数、32-lane 和完整代码 THP 检查（每次 85,983,232 B）。
两个诊断 binary 都有 **7,272/7,272 个 compute 入口 64 字节对齐**。
discovery 改了 4 个 wrapper 对象，batch probe 另改 3 个 eval dispatcher；
archive 顺序、其余成员和 compute/commit 正文对象未变。

较早 `critical-path-v1` 中的自动页面模式曾在 discovery 使用小页、batch probe 使用 THP。
这批混合页面结果不用于最终报告。工具现已固定首次 discovery 的有效页面模式，后续必须一致；
最终整组在 `critical-path-thp-v1` 重新采集，通过完整 THP 核验。

## 覆盖与结果

| 项目 | 结果 |
| --- | ---: |
| 计划与生成包精确对应的 batches | 7,412 |
| 已调度操作 | 7,519,299 |
| 有可靠 RTL 点位置的操作 | 7,381,257（98.164%） |
| 未映射操作 | 138,042 |
| 结构工作量来源覆盖 | 92.278% |
| 缺失 RTL 文件 | 0 |
| 查询原始 ASC 的操作 | 956,180 |
| 精确映射到 ASC 的操作 | 660,965（查询范围内约 69.13%） |
| 实际跨分区 copy sites | 6,000 |
| 没有导出位级 targets 的 copy sites | 4,781，保留未知而不猜测 |

两次 discovery 的 **16,227/20,000 个 eval step** 对最后完成分区给出相同结果。
上升沿 p0 最后完成 17,633/20,000 次；下降沿 p0 为 9,466 次、p27 为 8,579 次。
这些是两个重复合计的计数。p27 在下降沿的 8,579 次最后完成中，有 7,350 次不是最长
eval 函数体，因此后续必须区分线程开始时间与必要计算量，不能把“最后完成”直接等同于
“计算正文最长”。

关键样本中较大的 batch 包括 p0 commit 345/342/346/344/343 和 compute 302。
其中 commit 345 的 5,986 个操作均精确映射到 ASC 5；commit 344 的 5,379 个匹配操作
也属于 ASC 5。p27 compute 215 的 7,274 个匹配操作涉及 466 个 ASC。
这是进一步检查大 ASC 与多个共同活跃锥的依据，还不是任何 RTL 改写的性能结论。

## 语义与限制

- 当前完整图的来源均只有起始点，没有结束范围。报告明确写 `precision=point`；
  不从相邻代码或名称推断表达式范围。新 span 支持真实范围，fixture 覆盖范围往返。
- 既有 `origin/pass/note` 与 clone 来源被保存，但历史图没有完整的有序 pass 链；
  不将最后一条 annotation 冒充完整变换历史。
- 测得的是整个 batch 的时间。RTL span 和 ASC 是关联集合，时间不按操作数拆给源码行。
  广泛共享的 clock/输入位置可能关联很多 batch，关联总量不等于该行自身耗时。
- 只对自动选中的三个分区做 batch 和 ASC 细化；其它分区有完整 phase 追踪与静态信息。
- batch 入口 mask 不能说明内部后续激活的所有组；零入口 mask 的调度成本单独列出。
- 只实现严格周期目标下的一条 AST 规范化规则，CSE、通用 guard/alias 和行为等价没有启用。
  本轮不生成或采用未经香山全流程验证的 RTL 性能候选。

## 验证

37 项 Python/native 集成与默认流程回归测试通过，包含：

- source ID 路径迁移、未知范围、batch/ASC 精确映射和通信 targets；
- GRH clone/JSON 来源保持、实际 Slang ingest 和 memory 边界；
- trace 版本、截断、重复/缺失样本、时钟、阶段、轮次和实际页面模式；
- AST 对 signed、部分/动态 slice、memory、event、delay、macro 和多参数实例的拒绝；
- **实际 Verilator** baseline/candidate 构建，两组不同输入各 **100,000 cycles**，逐拍输出、
  reset 和寄存器状态一致；不是仅用字符串或假 verifier 检查。

真实 Chromium 检查覆盖报告加载、phase/clock 筛选、batch → RTL 展开、ASC 信息、
静态路径切换和页面截图。有限轨迹差分不等于形式等价证明，也不产生 walltime 收益结论。
