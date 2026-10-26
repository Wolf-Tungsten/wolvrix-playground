# R8 后 named store 与 General chunk 修复

状态：**两项生成代码问题已修复，源码与文档随本轮提交。** 本次接续中断的
`r79-store-frame-fix-v1` 至 `v5` 工作；最终证据独立保存于
`ptmp/remove-grhsim-ir/r79-resume-20261026/`，不覆盖 R0 或 R7/R8 验证。

## 原因与修复

1. named store 和大型 chunkFrame 共用了索引布局 writer，导致超过 1024 个
   字段的 store 被替换为不透明 `cells_*`。现在 `writeDirectValueLayout`
   专门保留 store 的语义成员和直接访问，`writeValueLayout` 的按完整类型
   分组只用于 emitter 私有 frame。默认构造、字符串、非零初值及重复 init
   的处理保留。
2. General 把活动度扫描、nonsink 计算与全部 writer run 局部值组成单棵
   C++ 树，行数 splitter 由此产生大量 `pGeneral_chunkN` 和全图 frame。
   现在 nonsink 始终生成各自函数，连续 24 个活动度 byte 组成一个扫描
   helper；writer/commit 各按至多 128 个连续 SinkSchedule run 分批。
   `pGeneral` 依次调用活动度和 writer 批次，`pLargeSink` 依次调用 commit
   批次；两个 phase driver 都使用固定大小的有序调用循环。小图也采用
   同一路径，不再按图大小或行数预算切换 inline 实现。
3. function writer 只提取无法单函数容纳的 scope；普通小 guard 可以直接
   批量拆分。无跨块局部值、spill 或 return 控制时，不再创建空 frame 或
   传递空 frame 参数。行数预估也只计入真实 frame；移除参数仅作用于 writer
   自己生成的调用，不改动源语句中的同名实参。

不改变 GRH partition、SinkSchedule、writer 顺序、逐 bit 实时扫描、
后继同轮激活与前驱下轮激活、small current/next 或 large sample/commit
契约；helper 仍受实际函数行数限制。

## 回归与真实模型

所有构建、测试、安装和诊断均通过 Make 入口；隔离候选与普通安装包分别
验证，generation identity 记录实际加载的核心库和 binding。

| 验证 | 本次结果与日志 |
| --- | --- |
| 公共回归 | **64/64**，[public-final.log](../../ptmp/remove-grhsim-ir/r79-resume-20261026/public-final.log) |
| 完整生成 C++ 执行矩阵 | **通过**，包含 named-model-stores、两种预算的 activity-batch-order 与七万字段构造；[cpu-final.log](../../ptmp/remove-grhsim-ir/r79-resume-20261026/cpu-final.log) |
| 大型 named store | 1100 scalar + 1100 memory、读写及重复 init；确保 store 无 `cells_*`，phase 无 `pGeneral_chunk`/`chunkFrame_pGeneral` |
| 跨活动度批次 | 400 级计算链，超过 384 个 nonsink 超节点，覆盖三个活动度批次；预算 16/1024、两次 init、逐状态值及精确固定点轮数均通过 |
| function writer | 2048 guard 批量拆分、无空 frame/参数、保留外部 `accept(chunkFrame)` 源调用；循环、return、初值执行用例保留 |
| 标准安装与重启 | `make py_install` 成功；普通安装包 10 个 checkpoint 模型执行、provenance 3 项、tooling 16 项通过；[installed-flow-tools.log](../../ptmp/remove-grhsim-ir/r79-resume-20261026/installed-flow-tools.log) |
| 原生计数 | **11 项**通过，[execution-counts.log](../../ptmp/remove-grhsim-ir/r79-resume-20261026/execution-counts.log) |
| 冻结逐次观测 | 8 fixture、168 记录、18 项既定批准差异、0 未解决；equal=false、accepted=true；[comparison.json](../../ptmp/remove-grhsim-ir/r79-resume-20261026/observations/comparison.json) |
| ROB 全输出 | 最终 checkpoint 重发、完整 O3 编译和执行；**4,394,996,424 bytes 相同、exclusions=0**，SHA256=`688ac2f6e9c5509eb00dad368ead600a07ec27d956b1ec9a429d8e46309a7df1`；[comparison.json](../../ptmp/remove-grhsim-ir/r79-resume-20261026/rob-final/comparison.json) |
| 生产与模型依赖 | 128 源文件、15 个对象及完整库/ROB 生成库检查，passed=true、issues=[]；[production-audit.json](../../ptmp/remove-grhsim-ir/r79-resume-20261026/production-audit.json) |
| XS C++ 全量编译 | 最终 checkpoint 重发，**2365 TU**，Clang、`-O3 -march=native -fno-strict-aliasing`、24 jobs，静态模型库构建退出 0；[xs-model-build.log](../../ptmp/remove-grhsim-ir/r79-resume-20261026/xs-model-build.log) |

初次新测试置于 `testModels` 之前，其执行 Makefile 条目被后者重新生成时
覆盖；已移至初始化 Makefile 之后，最终日志确认实际编译执行。新增活动度
测试最初错误地要求写状态的 eval 也只执行一轮；现依据已有 publish 契约，
检查无写一轮、有效写两轮，未修改调度来迎合测试。

## 最终生成代码独立扫描

扫描实际 `.cpp` 定义行数并逐项比对 manifest，重载函数按名字及行数的
multiset 比较；不是仅信任 emitter 自报的最大值。

| 指标 | ROB | XS |
| --- | ---: | ---: |
| named store 类别，均直接成员 | 16 | 16 |
| 空 chunkFrame | 0 | 0 |
| `pGeneral_chunk` / `pLargeSink_chunk` | 0 / 0 | 0 / 0 |
| phase driver 实际行数 General / LargeSink | 7 / 6 | 7 / 6 |
| 活动度 / writer / commit 批次 | 21 / 118 / 54 | 203 / 1415 / 993 |
| 全部函数 | 7835 | 66913 |
| 最大实际函数行数 / 预算 | 1021 / 1024 | 1023 / 1024 |
| TU | 318 | 2365 |

XS 的 `smallSinkStoreType` 为 108,991 个直接字段，
`nonSinkBoundaryStoreType` 为 753,800 个直接字段，
`largeSinkPayloadBoundaryStoreType` 为 428,623 个直接字段。
仅确实跨 helper 的局部值允许保留 frame；不是删除全部 frame。

证据：[ROB layout audit](../../ptmp/remove-grhsim-ir/r79-resume-20261026/rob-final/generated-layout-audit.json)、
[XS layout audit](../../ptmp/remove-grhsim-ir/r79-resume-20261026/xs-final/generated-layout-audit.json)。
诊断脚本及其 Makefile 与证据同目录保存。

本轮 ROB/XS 为 R7/R8 最终普通 GRH checkpoint 的重新发射，没有重做
原始 SV 完整生成计时，因此不沿用先前 1954.081s 为本次完整构建性能。
XS 的当前 emu 已补充完成以下 100k difftest；ROB 另有全部输出行为证据。

## 当前版本 CoreMark 100k 重测

通过 `make xs_grhsim_build_emu` 复用已编译的最终模型库，构建/链接 harness
用时 18.35s、退出 0；该时间不计入运行性能。随后通过
`make run_xs_grhsim_emu` 执行 `coremark-2-iteration.bin` 的 100,000 周期窗口，
固定 CPU 2、seed=0、NEMU difftest，关闭波形、commit trace、PERF 和
SN_TIMING，每 10,000 周期记录一次进度。模型仍为 O3/march=native。

| 指标 | 当前 store/phase 修复版 | 前次 R7/R8 记录 |
| --- | ---: | ---: |
| Host 时间 | **1019.552s（16 分 59.552 秒）** | 965.162s |
| wall | 16:59.63 | 16:05.20 |
| 运行最大 RSS | 201,236 KiB | 197,036 KiB |
| 退出码 | 0 | 0 |
| 提交指令数 | 238,535 | 238,535 |
| cycleCnt / Guest cycles | 99,996 / 100,001 | 99,996 / 100,001 |
| 终点 PC | 0x80000cde | 0x80000cde |

当前吞吐约 98.08 host cycles/s。相对前次记录 Host 增加 54.390s
（**+5.64%**）；这是当前一次实测与历史记录的比较，没有交替 A/B 或
重复采样，不能据此将全部差异归因于某一处改动。
十个进度点的指令数、model cycles、commit/trap PC 及最终终点均与前次一致，
difftest 已启用、未出现 mismatch。100k 是周期窗口，不代表完整 CoreMark
两次迭代结束。运行前后 emu、模型库、CoreMark 和 NEMU 的 SHA256 核对通过。

当前 emu SHA256：`3886820c286d17ce5d5dea5cdb8b8bc544461705219401f344046e94f4fe8182`。
证据：[运行日志](../../ptmp/remove-grhsim-ir/r79-resume-20261026/logs/xs_grhsim_r79_store_phase_100k.log)、
[Make 驱动命令](../../ptmp/remove-grhsim-ir/r79-resume-20261026/xs-100k-driver.log)、
[wall/RSS/退出状态](../../ptmp/remove-grhsim-ir/r79-resume-20261026/xs-100k.time)、
[自动核对与比较结果](../../ptmp/remove-grhsim-ir/r79-resume-20261026/xs-100k-result.json)、
[构建日志](../../ptmp/remove-grhsim-ir/r79-resume-20261026/xs-emu-build.log)。
核对使用同目录 `benchmark.mk` 的 `summarize` Make 目标。

## plain SV Verilator 行为对照

当前修复版与 plain SV Verilator 已分别重跑完整 100k 提交 trace。参考为
`build/xs/ref/verilator-compile/emu`，复用 2026-10-02 从 plain/scalar SV
构建的二进制，没有把当前 aggregate SV 送入 Verilator。参考 SHA256 为
`9369d7e4f95d913e68801b32b964e43e8817d8e1ea358efaba5f545931a2cfb0`，
与此前保存的 plain 来源记录一致；原始 Makefile 未传 preserve-aggregate，
Verilator 输入记录及 `VSimTop.h` 的 scalar 端口均保留在本次证据目录。
参考报告的设计提交为 `4a6e3da8bf, dirty: 0`；当前 XiangShan 为
`2193b15d3518c3c1b76b04df41370f67837fbe67`，比较两者的 `src/` 与
`build.sc`（含工作树修改）差异为空。CoreMark、NEMU 和参考二进制摘要
在运行前后均验证通过。

两侧均通过 Make 运行入口，seed=0、NEMU difftest、100,000 周期，
`XS_COMMIT_TRACE=1 XS_LOG_BEGIN=0 XS_LOG_END=-1`，关闭波形。
plain 在独立工作目录运行（指向已验证参考二进制），CPU 4/5；当前
GrhSIM 仍使用本次性能测试的同一二进制，CPU 2。两侧同时运行且开启
trace，因此本轮时间不用于替代前述无 trace 性能数据或计算性能比。

| 比较指标 | plain Verilator | 当前 GrhSIM |
| --- | ---: | ---: |
| 完整提交 trace 记录数 | 231,568 | 231,568 |
| instrCnt | 238,535 | 238,535 |
| cycleCnt / Guest cycles | 99,996 / 100,001 | 99,996 / 100,001 |
| 终点 PC | 0x80000cde | 0x80000cde |
| 退出码 | 0 | 0 |
| NEMU mismatch / RTL 断言失败 | 无 | 无 |

逐条比较 cycle、PC、instruction、wen、有效 dst/data、index、slot，
**differing_records=0、differing_payloads_excluding_cycle=0，提交周期差
最小/最大均为 0**。仅在 wen=0 时忽略无效 dst/data，不排除任何提交记录。
规范化 trace 的两侧 SHA256 都是
`51e749f5475729dc3adcbdd8a29dd9e649a18c00db18dbf7a739db69ac004e26`。
该结论覆盖此 100k 窗口的逐周期提交行为，不是全部内部波形或完整 CoreMark
程序的等价证明。trace 记录数与 instrCnt 的计数口径不同，分别保存。

证据：[完整比较结果](../../ptmp/remove-grhsim-ir/r79-resume-20261026/behavior/comparison.json)、
[Make 比较日志](../../ptmp/remove-grhsim-ir/r79-resume-20261026/behavior/compare.log)、
[plain 运行日志](../../ptmp/remove-grhsim-ir/r79-resume-20261026/behavior/logs/xs_ref_plain_trace100k.log)、
[当前 GrhSIM 运行日志](../../ptmp/remove-grhsim-ir/r79-resume-20261026/behavior/logs/xs_grhsim_r79_trace100k.log)、
[plain 来源摘要](../../ptmp/remove-grhsim-ir/r79-resume-20261026/behavior/plain/provenance.sha256)、
[RTL 源差异](../../ptmp/remove-grhsim-ir/r79-resume-20261026/behavior/plain/current-rtl-source.diff)。
重复核对使用 `make -C ptmp/remove-grhsim-ir/r79-resume-20261026/behavior compare`。
