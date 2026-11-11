# F24 正确性 checkpoint：v14 与清理提交

用户先于 **2026-11-11 07:38 UTC 左右** 要求暂停性能工作、清理代码和临时目录，
随后明确“F24先不继续抠性能了，F24判定为完成，把正确性搞对了”。
**按最新验收口径，F24已完成：v14全核100k正确性、生成、完整编译及activation
均通过；性能未达标的事实保留，但移出本阶段完成门。** 本记录保存结果与清理
提交边界，不继续运行性能实验。

## 输入、策略与固定流程

正式输入是原始 `build/xs/rtl/rtl/SimTop.fir`、公共 `SimJTAG.v`，top 为 `SimTop`。
v14 通过 prepared ingest request 显式指定以下既有 FIRRTL 选项：

```json
{
  "invalid_policy": "zero",
  "init_policy": "unknown",
  "lower_threads": 10,
  "node_annotations": true,
  "enabled_layers": [
    "Verification.Assert", "Verification.Assume", "Verification.Cover"
  ],
  "annotation_files": []
}
```

`resource_roots` 指向 `testcase/xiangshan/difftest/src/test/vsrc/common`；混合输入的
SV include 路径和 `DIFFTEST` 定义也在请求中记录。冻结的 `ingest-request.json`
与规范化 `sources.json` 逐字节相同。策略在 `Lowerer::invalid` 建图时生效，
通用 ingest/API 及既有 Make 默认仍为 `unknown`，没有修改 XiangShan RTL。

正式运行从原始 FIRRTL 开始，无 checkpoint/resume，计划、start、done 三份记录
逐项匹配以下 **canonical 22 阶段**：

```text
ingest-firrtl → xmr-resolve → hier-flatten → comb-loop-elim
→ split-static-array → dead-code-elim → expr-opt → used-bits → split-nodes
→ dead-code-elim → constant-analysis → dead-code-elim
→ alias-analysis → pattern-detect → comm-expr → dead-code-elim
→ grhsim-dialect-translate → split-event-and-output → split-nonsink-and-sink
→ partition-nonsink → partition-sink → emit-grhsim-cpp
```

生成硬截止 840s、fresh 完整编译硬截止 330s，128GiB/swap0、24 个共享 jobs，
保持默认 16MiB TU 与 32GiB 单 artifact 上限；完整编译包含 harness 捕获、PCH、
所有模型/harness 对象、archive 和最终链接，无旧编译产物、cache 或 PGO。

## 正确性根因与证据

既有 Verilator 波形和 trace 将 PC `0x80000040` 的失败缩小到 ICache SRAM
写入/读回：RAM DPI 与 refill 数据正确，但 SRAM `RW0.wmode` 恒 0，写入未生效。
原始 FIRRTL 将 DFT 控制 `core_with_l2.io.dft.ram_hold` 标为 `invalidate`。
`unknown` 策略先折叠 `eq(X,0)=X`，随后两态投影为 0；冻结 Verilator SV 将
invalid hold 本身取 0，因而 `eq(0,0)=1`，允许写入。根因是 invalid 策略与
投影时机差异。

原样提取 `SRAMTemplate_4` 及其 256×66 SRAM 后，同一 driver 的 67 次有效读回中：
bare SRAM 和显式 hold0 始终匹配；invalid hold 在 unknown 策略下 67 次均失败，
仅改 ingest 为 zero 后三组全部匹配。literal `1'bx` 的独立 Verilator 对照给出
相同结果。隔离证据解释根因，全核结论由下面的 v14 新生成/编译/运行单独取得。

| v14 质量门 | 已取得的结果 |
| --- | --- |
| 完整生成 | 22/22、exit0；pipeline **825.050s**，受控 service **826.294s < 840s**，emit 281.569s；409 个发布文件、403 TU、57,968 函数，正文 6,713,031,849 B；peak 100.734GiB，swap/OOM 为 0 |
| activation | 新 publication 独立核验，GSIM 240 个 C++ 文件 inventory/stats 复核，census **15.04s**、exit0；V=774531、Sc=0、Sw=189719、P=894，U=964250、U+P=965144，均小于充分上限 **2193888** |
| fresh 完整编译 | payload **305.71s**，service **305.837s < 330s**；403 model / 41 harness、PCH/archive/link 全部完成，emu 119,876,608 B；wrapper/monitor/source verification 均 exit0；peak 13.611GiB，swap/OOM 为 0 |
| 全核 100k / NEMU | CPU2、单线程、seed0、50 reset pulses、同一 CoreMark/NEMU；emu/Make/service 均 exit0，emu **194.96s**、service 195.140s；guest **100001**、core **99996**、instrCnt **238535**、terminal PC **0x80000cde** 与参考一致，NEMU 无差异 |
| 精确提交比较 | **231,568 commits**，cycle 568..99996；原 exporter 的 `commit.trace`、`commit.tsv`、`summary.json` 三项 `cmp` 全部通过；独立 comparer 的架构、时序、inactive writeback、附加 detail 差异均为 0，normalized text 字节相同 |

activation 的结论是充分不等式成立，不能把上界/下界之比称为精确边数比。
100k 是冻结的比较窗口，不表示完整两轮 CoreMark 已执行结束；commit probe 条数
也不要求等于 `instrCnt`。trace 采集耗时不作为关闭观测后的性能成绩。

原 trace 脚本 postflight 的 `[Mm]ismatch` 扫描误命中 45 条合法硬件 PERF 指标，
因此原 `run-trace-returncode.txt=2` 仍保留。独立 `v14-validation/` 仅豁免完整
数值 PERF 记录，8 个正反例通过，继续核验全部身份、资源和 endpoint，
`audit-trace` / `compare` 均 exit0；使用同一 raw log，没有重跑模拟器或改写冻结控制。

## 性能终态与验收口径调整

07:34:54.83 UTC 启动的正式性能运行使用同一原始 v14 exe、CPU2、NEMU 开启，
trace/wave/profile 关闭，保留 **152.190s** emu 硬截止。该截止实际触发 SIGKILL：
emu 状态 137，外层 Make/service 状态 2，service 152.324s。日志最后报告
`[CYCLE_LIMIT] cycles=70000 max_cycles=100000`，没有到达相同的 100k endpoint；
70,000 是最后已报告的周期，不是精确的被杀周期。**性能门失败，不能外推通过。**

随后用户先要求暂停、清理提交，再决定以正确性通过完成F24，将性能移出本阶段
完成门。此决定不改变超时事实，也不把超时判作性能通过；没有继续profiling、
全图运行或性能优化。

## 冻结身份与清理后版本的边界

上面的全图成绩属于 `ptmp/firrtl-ingest/F24/full-native-v14/` 冻结身份，
其中 snapshot 保存 643 个源码文件及内容哈希，而非仅依赖当时的 Git HEAD。
关键 SHA-256 如下：

| 冻结对象 | SHA-256 |
| --- | --- |
| 原始 `SimTop.fir` | `b313a3ecd154cbd9279b14403709806b95fb136cf44b475e9def46a926ecb26b` |
| 生产源码集合 identity | `b68d9113eb7ef61a2d99fab1f61d595a3c08a4591c52b8538b18bfd97b27e667` |
| 根 `Makefile` | `236fcebfcb1963b4d555dfa7469c3c386ccc8f619ef007549e1dc5553d50fc47` |
| `scripts/grhsim_flow.py` | `27a6d4e5e4cfebe5e1bd2a850470791e8962eea589567fff412d57f802ee417e` |
| `scripts/wolvrix_xs_grhsim.py` | `59076e4ebb3e4b71c72d7e3e120820fff7f63259fb42cb447e5ae61104ab1961` |
| 实际加载的 `libwolvrix-lib.so` | `4648e9d77c5e25b24928fc58ffb3ad0c6dc62ad79da7a7a39eae7c599a826d63` |

正式 v14 之后，cleanup 调整了脚本、Make 入口、重复阶段保存和无用统计等；
当前 `grhsim_flow.py` / `wolvrix_xs_grhsim.py` 已与上述冻结哈希不同。
**清理后的版本只做小规模回归，没有重新执行全图生成、fresh 编译或 100k 验收。**
历史v14证据继续保留，不能写成当前清理提交重新跑出的成绩。将来若另立性能
工作，需要建立新的snapshot并按新身份验证；不覆盖v14原控制或状态。

本次版本还包含两个嵌套仓库的改动，必须随提交明确记录：

- `testcase/xiangshan/difftest` 是仿真 harness：`emu.cpp` 的 GRHSIM reset
  分支在首个时钟沿前增加 reset=1/clock=0 的 settle eval，保留原 50 个 reset
  pulses；`grhsim.h` 为 UART、exit/step、perf/log 控制的 10 个端口优先匹配
  FIRRTL 的 `__DOT__` 拼写，兼容旧平坦 SV 名称。这些是 harness 适配，不是 RTL
  修改；上述 v14 snapshot 已包含这份 harness。
- `reference/gsim/src/GraphDumper.cpp` 补齐 JSON 的 `id`、`status`、`width`、
  `sign`、`dimension`、`lineno` 字段，供图结构与状态元素审计使用；改动属于 dump
  元数据，不改变仿真调度算法，也不等于重跑 GSIM 性能基线。

## 清理与提交验证

删除21个退役脚本/辅助Makefile/专属测试，移除旧migration baseline、frozen
binding/compiler、ROB实验、phase probe与用户点名的M0 golden baseline/diff
harness入口；HDLBits子模块同步移除M0 trace目标。保留canonical生成、现行测试、
通用reemit/census和选项拒绝守卫。删除无生产调用的ingest包装，converted
checkpoint只通知一次，两个显式dump仍保留；修正FIRRTL inspector的旧临时目录变量。
F21一次性all-registers脚本归档到`ptmp/firrtl-ingest/F21/retired-tools/`。

历史产物按精确allowlist和文件metadata检查清理，结果`status=complete`：
删除 **14,174个文件 / 685,327,848,637 apparent bytes（638.261GiB）**，
另移除旧language2005构建的悬空emu软链。`du -h ptmp`由约680GiB降至约43GiB；
apparent字节含hardlink路径重复，不当成精确释放空间。所有目录保留删除记录，
小日志、报告、identity、source archive及四项旧模型metadata保留；旧大图需重建。
本轮v14完整模型、exe、trace、原始状态和补充校验、GSIM/Verilator基准、FST与
SRAM隔离证据全部保留，清理后再次核对publication/runtime/参考哈希和三个精确cmp。

清理后通过现有Make目标完成 **136项脚本测试**，包括85项FIRRTL workflow、
5项flow（含实际模型生成/编译/执行及restart）、8项XS workflow、12项选项守卫、
2项provenance、6项benchmark、6项activation、11项资源控制、1项reset。
另23项F21分析测试和DCE、SplitStaticArray、SemanticTree/JSON、GrhSIM转换/
分区/调度、FIRRTL aggregate的native CTest suites通过；三仓库diff检查通过。
最初组合命令末尾误写不存在的`test_analyze_f24_activation_edges`，当次Make2；
此前各suite已通过，随后用实际`test_f24_activation_edges`及完整最终命令exit0
确认，不把错误命令计为通过。

提交关联版本：

| 仓库 | 提交 |
| --- | --- |
| Wolvrix核心/语义/优化与回归 | `d8d2e22` |
| Wolvrix退役入口文档清理（最终指针） | `7ddc456` |
| Difftest GrhSIM harness | `43d37af3d` |
| XiangShan测试仓库仅pin Difftest指针 | `77e01e763` |
| GSIM图导出诊断字段 | `9e9cbdf` |
| HDLBits移除M0 trace harness | `7069f31` |

根仓库提交包含本记录、F21–F24实现入口/文档、清理及上述子模块指针；
精确根提交ID由Git记录及交付回复给出，不在文件内自引用。

## 证据入口

- [F24 主记录](F24-xs-firrtl-grhsim.md)与[activation 口径](F24-activation-edge-audit.md)。
- [SRAM 隔离复现](../../ptmp/firrtl-ingest/F24/icache-sram-isolated/README.md)和[根因记录](../../ptmp/firrtl-ingest/F24/icache-sram-root-cause.md)。
- [正式 v14 snapshot](../../ptmp/firrtl-ingest/F24/full-native-v14/snapshot.json)、[producer identity](../../ptmp/firrtl-ingest/F24/full-native-v14/xiangshan_grhsim.generation-identity.json)与同目录 `generation-*`、`compile-*`、`activation-*`。
- [精确比较结果](../../ptmp/firrtl-ingest/F24/full-native-v14/trace-comparison/comparison.json)和[补充验收日志](../../ptmp/firrtl-ingest/F24/v14-validation/compare.log)。
- [性能原始日志](../../ptmp/firrtl-ingest/F24/full-native-v14/logs/xs_grhsim_full-native-v14-perf-100k.log)、[硬截止计时](../../ptmp/firrtl-ingest/F24/full-native-v14/run-perf-time.txt)与[资源终态](../../ptmp/firrtl-ingest/F24/full-native-v14/run-perf-resources.json)。
- [清理清单](../../ptmp/firrtl-ingest/housekeeping/cleanup-plan.json)、[删除终态](../../ptmp/firrtl-ingest/housekeeping/cleanup-result.json)与[保留证据复核](../../ptmp/firrtl-ingest/housekeeping/verify-retained.log)。
- [最终脚本回归](../../ptmp/firrtl-ingest/F24/commit-validation-final.log)、[native回归](../../ptmp/firrtl-ingest/F24/commit-validation-native-tests.log)和[F21/activation分析回归](../../ptmp/firrtl-ingest/F24/commit-validation-analysis-tests.log)。
