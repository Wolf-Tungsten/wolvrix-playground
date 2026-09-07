# GrhSIM IR 基础架构实现进展

更新时间：2026-09-06

CPU 后端的新阶段进展见文末；下方基础架构表保留原阶段验收范围。

## 当前边界

- 保留 `scripts/wolvrix_xs_grhsim.py`、`emit_grhsim_cpp` 和现有 GRH pass/session 路线，不修改其行为。
- 新路线只执行约定的九个 GRH pass，然后把扁平 GRH 单向 lowering 到独立 GrhSIM IR。
- 本阶段终点是 GrhSIM JSON 的 verify、store、load 和稳定 round-trip，不生成仿真代码。
- GrhSIM semantic pass 原地修改；emit 预留为 `PassKind::Emit`，但本阶段不实现 emitter。

## 本阶段落地

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 独立数据模型 | 完成 | typed ID、字符串 interner、扁平数据池、identity/revision |
| core 方言与 verifier | 完成 | 独立 `DialectRegistry`，覆盖当前 GRH lowering 所需的 core 类型/op/Init |
| GrhSIM pass 基座 | 完成 | 独立 registry/manager、五种 `PassKind`（含 `Emit`），首个 analysis pass 为 `grhsim.verify` |
| GRH lowering | 完成 | 扁平 top、I/O/S/F/G/Init、event history、DPI、可选 provenance |
| JSON load/store | 完成 | 流式 `wolvrix.grhsim.v1`、声明计数预留、原子 store、load 后完整验证 |
| Python/session API | 完成 | lower/pass/pipeline/load/store，独立 model key 空间和完整 key 生命周期 |
| XiangShan 并行路线 | 完成 | 独立脚本、Make target、flat GRH/GrhSIM/round-trip 三类 checkpoint |
| 本阶段验证 | 完成 | C++、Python、损坏 JSON、小 RTL 九 pass 路线和现有 XiangShan 大 checkpoint |

这里的“完成”只表示当前阶段要求的“能从 flat GRH 构造、verify、store、load 并稳定 round-trip”。
规划文档中的 editor、analysis cache、backend mapping verifier、ArtifactSink 和实际 emit pass 仍属于
后续里程碑，不能从本表推断为已实现。

## 已完成验证

- `grhsim-ir-tests`：小型 flat GRH lowering、register/event-history、registry pass、层次拒绝。
- `grhsim-ir-tests`：稳定 store/load/store、坏 format、坏 table count、坏 TypeId、load 后 fresh
  identity/revision。
- Python smoke：真实 SystemVerilog ingest 后完成 lower/verify/store/load/store，并验证 session
  kind/filter/copy/rename/delete 生命周期。
- 新脚本非 resume 路径：严格按约定顺序执行九个 GRH pass，保存 flat GRH，再完成 GrhSIM
  store/load/store 字节级稳定往返。
- XiangShan 现有 flat GRH 检查点（2.9 GB）规模实测：4,981,305 ops、4,677,017 values、
  10,625,734 operands、695,052 states。输出 GrhSIM JSON 为 444 MB，两次 SHA-256 均为
  `5b2494766fbc12030cd919452835bcfd7443a81b7e1f5314499d61dd0e27075c`；总耗时约 39 秒，峰值
  RSS 约 27.0 GiB（包含旧 GRH JSON load 和 lowering 期间双 IR 共存）。
- 全量 CTest：49 项中 47 项通过，包括新增 GrhSIM IR、全部 ingest 和旧 `emit-grhsim-cpp`。
  两项既有 transform 测试稳定失败：`transform-comb-lane-pack`（storage frontier rewrite 断言）和
  `transform-repcut`（partition static feature export 断言）；本次未改动对应实现。

## 已知限制

- CPU/Corvus backend mapping、emit 和 runtime 不在本阶段范围内。
- `PassKind::Emit` 已作为统一 pass 模型的一部分，但当前没有注册实际 emit pass，也不提供
  `build_grhsim`/`emit_grhsim` 基础 API。
- 首版只接受已经完成 XMR resolve、blackbox guard 和 hierarchy flatten 的单个 top。
- 当前 Python `run_grhsim_pipeline` 是基础便利入口；等 semantic/backend mutation pass 落地时，
  需要下沉成一次 native manager 调用，以统一处理 revision、增量验证和 artifact 提交。

## CPU 后端增量：2026-09-05

目标继续为 [CPU multiclock/activity 计划](./grhsim-ir-cpu-backend-multiclock-activity-plan-20260905.md)
和 `xs_wolf_grhsim_ir` CoreMark 50k 仿真。当前完成了首批代码，尚未形成可执行仿真器。

- 已实现 model-owned `CpuBackendMapping` typed payload、phase/domain 分区及 JSON 持久化。
- 已注册 `cpu.st.split-phase`、`cpu.st.form-event-domains`，由 PassManager 逐 pass 验证。
  `memAssign/memWriteSeq` 也归 commit；task/DPI 留在 compute。mapping 保持 `complete=false`。
- 已实现树覆盖、引用、phase 纯净性、域 key、稳定写口顺序验证，以及 clone/revision 失效。
- XiangShan 脚本在 lowering 后执行这两个 CPU pass；其余 CPU pass、emit/runtime 仍待实现。
- 小型 C++ 测试通过；XiangShan 大 checkpoint 的 mapped JSON 往返逐字节一致。
- 实测 4,690,774 compute ops、290,531 commit ops；事件域为 2 input + 446 derived + 1 general，
  有 132 个多写口状态。草案要求的单 Edge 域计数未满足，原因已有 RTL 和 IR 证据。

独立归档：

- [NO0527 实施计划](../../grhsim_opt/NO0527_grhsim_ir_cpu_phase_domain_plan_20260905.md)
- [NO0528 多域审计](../../grhsim_opt/NO0528_grhsim_ir_xiangshan_event_domain_audit_20260905.md)
- [NO0529 结构门禁](../../grhsim_opt/NO0529_grhsim_ir_cpu_phase_domain_gate_20260905.md)：真实 Make
  入口 exit 0，40.80 秒；C++ 与 Python 四份 checkpoint SHA-256 一致。Python 参数传递已验证。

下一步仍需 compute node/coarsen/DP、active word 和函数打包、layout/schedule、C++ emitter、
Make 仿真构建入口，再做 HDLBits、多时钟 Verilator 对照和 CoreMark 10k/50k difftest/perf。
M5.0 全量 legacy phase parity 与 HDLBits 域统计也尚未验收；不能把结构 gate 当作 50k 通过。

## Compute 分区增量：2026-09-06

已实现并接入 `xs_wolf_grhsim_ir`：

- `cpu.st.build-compute-nodes`：拓扑排序、boundary cone 构造，拒绝组合环，不改写语义 IR。
- `cpu.st.merge-compute-supernodes`：out1/in1/sibling coarsen、quotient DAG 检查、activation-cost DP。
- `cpu.st.pack-active-words`：连续 active ID、每字 8 supernode、显式 helper ranges。
- `cpu.st.pack-emit-functions`：完整 word 和域内 commit supernode 的函数打包。
- verifier 按六个 stage 检查树层次、compute 依赖顺序、活动位及 helper 覆盖；JSON 持久化
  新阶段和活动度标注，仍接受旧 phase/domain checkpoint。

小型 C++ 与 Python 参数测试通过。XiangShan 全图得到 1,501,444 compute nodes、44,686
compute supernodes、5,586 words、62 compute functions 和 452 commit functions；跨 compute
分区 value-target 数由 5,275,884 降到 2,510,273。六阶段完整校验和 JSON 往返通过，真实
Make 入口 exit 0；C++/Make 的四份 mapped JSON hash 一致。

- [NO0530 实施计划](../../grhsim_opt/NO0530_grhsim_ir_cpu_partition_plan_20260906.md)
- [NO0531 结构与入口门禁](../../grhsim_opt/NO0531_grhsim_ir_cpu_partition_gate_20260906.md)

mapping 仍为 `complete=false`。下一步是 `cpu.st.layout-data` 与 `cpu.st.build-schedule`，
再实现 C++ emitter 和仿真构建入口。CoreMark 10k/50k、HDLBits 仿真、多时钟差分和性能门禁
均尚未通过；本轮只验收分区树，不代表 M5.1 或整体目标完成。

## CPU 数据布局增量：2026-09-06

已实现 `cpu.st.layout-data` 并接入独立 `xs_wolf_grhsim_ir` pipeline。新增独立 CPU 类型表、
I/O/S object arena、boundary value arena、supernode/helper 共享 local frame 和分区运行态槽。
verifier 重建 canonical layout，检查类型、覆盖、生命周期、偏移与运行态；JSON 兼容旧分区
checkpoint。DPI 结果保守持久保存，数组及 arena 大小计算拒绝溢出。

- 2/2 定向 CTest 通过；包含位宽/符号/四态、嵌套数组、DPI、helper、跨分区、负向与溢出测试。
- XiangShan 布局：405 CPU types、695,065 对象、1,215,208 boundary values；对象存储
  25,228,032 bytes、boundary 2,741,144 bytes、运行态 6,524 bytes。
- 从分区 checkpoint 仅运行布局与往返用时 22.80 秒；真实 Make lowering + 七阶段用时
  63.47 秒，layout 含 verifier 1,129 ms。四份 C++/Make 输出 SHA-256 全部一致。
- Python editable 包已重建安装，既有用户文档改动保留；未执行提交。

独立归档：

- [NO0532 布局计划](../../grhsim_opt/NO0532_grhsim_ir_cpu_layout_plan_20260906.md)
- [NO0533 布局与入口门禁](../../grhsim_opt/NO0533_grhsim_ir_cpu_layout_gate_20260906.md)

mapping 仍不完整。下一阶段为 schedule tasks、稀疏 fanout、按当前语义闭包推导 E 与输入影子；
事件历史采样/消费还需实现及多时钟差分验证。emitter、独立仿真 build/run、HDLBits、CoreMark
10k/50k difftest 和性能门禁均未完成，完整目标继续保持未完成状态。

## CPU 调度增量：2026-09-06

已实现并接入第八个 pass `cpu.st.build-schedule`：单 NUMA/core、三类函数 task、稀疏 input/
compute/state fanout、精确输出/边沿状态闭包 E、roundSeeds 和输入影子偏移。CPU mapping 在
Schedule stage 标记 complete=true，仅表示分区/布局/调度数据齐全，不表示存在已验收仿真器。

- E 穿过所有状态写口；事件历史在闭包内，但不会把无观察写口的数据依赖误纳入 E。
- 派生事件的反向边沿也 arm，以保证历史采样；每轮源覆盖系统调用/DPI 和闭包外状态 reader。
- 3/3 定向 CTest 通过，包括正负向表检查、memory/call history、完整 JSON，以及寄存器链/
  门控时钟的 sparse vs dense G trace。trace 仅为 test-only 两态子集，不是 Verilator gate。
- XiangShan 结果：514 tasks、7 input sources、875,524 compute sources、626,747 E states，
  3,819 round seeds、32-byte input shadows；全图 schedule 与往返 28.67 秒。
- 真实 Make lowering + 八阶段 exit 0，69.32 秒，schedule 含 verifier 2,587 ms。C++/Make
  四份 JSON hash 一致。Python binding 已重建安装。

独立归档：

- [NO0534 调度计划](../../grhsim_opt/NO0534_grhsim_ir_cpu_schedule_plan_20260906.md)
- [NO0535 调度与入口门禁](../../grhsim_opt/NO0535_grhsim_ir_cpu_schedule_gate_20260906.md)

下一阶段是 emitter/生产 runtime、独立 build/run 入口。四态/多写口/系统调用的 emitted-code
验证、HDLBits、多时钟 Verilator 对照、CoreMark 10k/50k difftest 和性能 parity 均未完成。

## CPU emitter 增量：2026-09-06

首版 `cpu.st.emit-cpp` 已生成 runtime/header、task 源文件和 standalone Makefile；双时钟链路
4,104 次 Verilator 采样及 scalar 运算（含 `INT64_MIN / -1`）通过 `grhsim-cpu-emit-tests`。
`scripts/wolvrix_xs_grhsim_ir.py` 新增 `--emit-cpp-dir` 入口。直接加载 XiangShan schedule
checkpoint 的 emitter 审计在能力门禁处报告 4-state 类型和最大 79,263 位 2-state 类型，故
尚未进入 memory/DPI/system task 或独立 XiangShan 仿真；完整目标继续保持未完成。

### 后续编译门禁与宽值回归

初始化拆分后，gate45 已编译 driver、170 个 init 源文件和 tasks 1-6，但 task_7 编译器崩溃。
目前确认 concat 内部嵌套表达式过深；`value()` 本身并不递归内联。已按 legacy 直接写缓冲区
路线改为逐项插入，并修复窄输入误转 uint64_t 指针的越界读取风险。新增 Makefile 定向测试入口；
Verilator/UBSan 宽值 3,072 样本（含 concat 边界传播）通过。完整 gate47 的 lowering/mapping、
fresh-load/round-trip 通过，driver、170 个 init 文件和 tasks 1-9 编译通过；task_10 因宽比较
误用标量 cast、512 位移位量误传 size_t 失败退出，下一步处理这些语义缺口。尚未链接 emu 或运行 50k。
详见 [NO0558](../../grhsim_opt/NO0558_grhsim_ir_cpu_direct_concat_regression_20260906.md)。

宽比较现使用逐字 pointer helper，支持 signed/unsigned 扩展与 padding 屏蔽；宽移位量复用
legacy 饱和转换。扩展后的 Verilator/UBSan 对照通过。gate48 编译通过 driver、170 个 init
文件和 tasks 1-62，在 task_63 因宽内存 `cpu_at` 少 offset、宽寄存器 mask 合并误用标量 cast
退出。下一步补齐宽状态写入语义；emu 链接与 CoreMark 50k 仍未通过。
详见 [NO0559](../../grhsim_opt/NO0559_grhsim_ir_cpu_wide_compare_shift_20260906.md)。

宽状态写入已复用 legacy 原地 masked helper，修正 memory byte offset 调用，并给
memWriteSeq 补齐 event guard。新增 2,048 次 129-bit state Verilator/UBSan 对照通过，含
disjoint-mask 多写口、填充、有序覆盖、无边沿数据变化和锁存器保持。gate49 生成/fresh-load/
round-trip 通过，使用生成 Makefile 定向编译 tasks 63/64/73 通过；这是定向门禁，不是完整
模型链接。下一步复用 gate49 产物完成构建及 emu 链接，随后才进入运行验证。
详见 [NO0560](../../grhsim_opt/NO0560_grhsim_ir_cpu_wide_state_write_20260906.md)。

gate49 已通过完整 O0 模型编译和 difftest emu 链接。根 Makefile 新增 build-only 和 IR run
入口，运行管道补齐 pipefail，避免 emu 崩溃被 tee 掩盖。100-cycle 启动诊断未通过：默认
8 MiB 栈下 init_59 的约 9.4 MiB 栈帧导致早期崩溃；64 MiB 栈对照越过 init 后在 task_61
的 std::string 赋值路径崩溃，raw frame 未构造非平凡对象。接下来修复这两个运行缺口，
再接入 DPI/system task 并验证真实指令推进。CoreMark 50k 仍未完成。
详见 [NO0561](../../grhsim_opt/NO0561_grhsim_ir_cpu_full_link_startup_20260906.md)。

字符串崩溃进一步确认包含布局错误：cpu.str 仅分配 8 字节句柄，旧 emitter 却内嵌整个
std::string。现保留 mapping，句柄指向独立的 RAII 字符串存储；覆盖 object、boundary、
input shadow 和跨 helper 的局部 frame 生命周期。数组零初始化改为直接 memset，消除
O0 聚合临时值。8 MiB 栈下 16 MiB 数组、16 次重初始化、768 字符串样本的 ASan/UBSan
回归通过，原有四组 Verilator 对照不退。LeakSanitizer 在当前受跟踪环境不可用，未计入通过。
接下来生成 gate50 验证完整模型启动；DPI runtime 和数组一般初始化仍未闭合，50k 未完成。
详见 [NO0562](../../grhsim_opt/NO0562_grhsim_ir_cpu_startup_storage_20260906.md)。

gate50 fresh generation 与 round-trip 通过，完整 O0 构建已通过全部 170 个 init 文件。
反汇编确认 init_59 栈帧由 0x96c250 降至 0x2870（10,352 字节），无需提升栈限制；
task 编译和完整启动仍在验证中。
详见 [NO0563](../../grhsim_opt/NO0563_grhsim_ir_cpu_gate50_startup_20260906.md)。

gate50 后续完整 O0 编译、归档和 emu 链接均退出 0。默认 8 MiB 栈下的 100-cycle 检查
正常结束，原 init_59/task_61 两处启动崩溃未复现；host_cycles/model_cycles 均到 100，
耗时约 51.9 秒。日志 instr/commit_pc/trap_pc 始终为 0，这不是 CoreMark 功能通过。
本轮没有运行无意义的 50k；下一步在不改 DPI 事件策略的前提下发射实际 DPI/system task，
补齐数组一般初值，再要求真实指令推进和 NEMU 对照。NO0563 已追加完整结果。

已移除 DPI/system task 的 no-op 发射分支，接入 legacy ABI 的真实调用和 runtime 格式化。
调用保留 compute 分类与可选 event，条件不成立也采样历史；结果在 boundary 保持并按真变化
传播。新增 384 样本 O0 ASan/UBSan 覆盖多事件、void、output/inout、宽值/string/real、
窄 signed 归一化、时钟捕获及系统任务时机，finish/fatal 子进程退出码验证通过。
checkpoint 审计确认 XiangShan 有 6,527 DPI、7,235 fwrite、1 finish。下一步 fresh gate51
验证完整模型真实调用；数组一般初值与 50k/NEMU 功能、性能验收尚未完成。
详见 [NO0564](../../grhsim_opt/NO0564_grhsim_ir_cpu_external_calls_20260906.md)。

gate51 lowering/mapping 通过，但新调用校验错误地把 callCond 限为 1 bit，拒绝了实际
XiangShan 条件；未写出半成品模型。对照 legacy 已修为任意逻辑宽度的非零判真，宽值复用
reduce_or_words。384 样本改用仅高位非零的 32/129-bit 条件后全套测试通过；准备 gate52。
详见 [NO0565](../../grhsim_opt/NO0565_grhsim_ir_cpu_call_condition_20260906.md)。

gate52 fresh emission/round-trip 通过，但 DPI 声明进入公共头文件后与 harness 的原生
signed/unsigned、int64_t/long long 声明冲突。现对齐 legacy，将声明仅写入 compute task
翻译单元，不改 harness。补充 native uint64_t provider 与 signed IR 签名的位模式回归，
全套测试通过。下一步 gate53 完整构建及实际调用运行验证。
详见 [NO0566](../../grhsim_opt/NO0566_grhsim_ir_cpu_dpi_declaration_boundary_20260906.md)。

gate53 fresh generation/round-trip 通过，harness 已越过 gate52 声明冲突，driver 和全部
170 个 init 文件编译通过。含实际 DPI/system task 的 task 源文件仍在完整 O0 构建中；
后续以默认栈启动、真实断言输出及 difftest 指令/PC 计数为运行证据。
详见 [NO0567](../../grhsim_opt/NO0567_grhsim_ir_cpu_gate53_calls_runtime_20260906.md)。

gate53 后续完整编译/链接退出 0，默认 8 MiB 栈下实际 DPI/system task 的 100-cycle 与
1,000-cycle 运行均正常结束。1k 窗口在 cycle 600 已有第一条指令，最终 instrCnt=3、
cycleCnt=996，NEMU 已启用且未报告不一致。已有 legacy 二进制同配置 1k 核对的十个
采样点（指令数、commit/trap PC）和终态计数完全一致。这是启动段验证，不是完整程序通过。
新路线 O0 耗时约 382 秒，legacy 已有优化二进制约 0.734 秒，不能称为性能对齐；后续需
补齐一般数组初值，并用确实重编译的优化模型完成 10k/50k 及性能门禁。
详见 [NO0568](../../grhsim_opt/NO0568_grhsim_ir_cpu_first_commit_20260907.md)。

数组初始化的全量清零占位已移除：支持 const 序列、范围 fill、逐行 random 和发射期
readmem 静态表，共用 legacy 解析器，直接写目标缓冲区，缺失/越界/未覆盖初值预检拒绝。
首轮 96 样本/12 次初始化及原有 CPU 回归通过，16 MiB 默认栈测试已改为非零填充。
继续补验宽 readmem、JSON fresh-load 和 legacy 全量发射，再生成 fresh gate54。
这尚未替代 XiangShan 10k/50k 功能及性能验证。
详见 [NO0569](../../grhsim_opt/NO0569_grhsim_ir_cpu_array_initialization_20260907.md)。

NO0569 后续扩展回归通过，fixture 经 JSON fresh-load 后验证宽 readmem/局部覆盖，
legacy 全量发射/运行回归亦通过（191.66 秒）。gate54 完整 XiangShan 新初值预检、
C++ 生成、fresh-session round-trip 均通过（88.4 秒）。新输出目录确认无 O0 对象，
正在用生成 Makefile 定向编译 driver/init_59 的 O3 版本；尚非全模型优化链接/运行。
详见 [NO0570](../../grhsim_opt/NO0570_grhsim_ir_cpu_gate54_array_init_20260907.md)。

gate54 的 driver/init_59 O3 定向编译后续退出 0，对象分别约 5.0 MiB/24 KiB；
init_59 未见旧的 MiB 级栈预留。后续继续以相同 O3 配置完成模型 archive/emu 链接。
当前 IR emu 仍指向 gate53 O0 版本，没有运行中的构建/仿真，不能据此报告 gate54 性能。

gate54 已通过根 Makefile 启动完整 O3 构建，全部 170 init 对象编过，compute task
仍在编译。并行补齐 IR HDLBits Makefile 入口，复用全部 162 个现有 GrhTB；首轮
001–015 通过，016 因 GRH 变换留下的 detached value 被带入 IR 而校验失败。
lowering 现只跳过无 producer、无 users、无端口绑定的 value；有效 unused 输入/操作
保留，活跃无驱动值仍报错，定向 IR 单元回归通过。安装后继续全量 HDLBits，未宣称
50k 或性能完成。详见 [NO0571](../../grhsim_opt/NO0571_grhsim_ir_cpu_gate54_full_o3_20260907.md)
和 [NO0572](../../grhsim_opt/NO0572_grhsim_ir_cpu_hdlbits_entry_20260907.md)。

016 修复后通过，HDLBits 第二轮在 032 揭示 cpu_ 端口前缀误拒绝，已改为实际成员名称
检查与 this-> 公开端口访问；CPU 全套回归通过，第三次 HDLBits 全量已越过 032。
gate54 的两个大 compute task 实际 O3 编译完成耗时约 563/670 秒，现通过已有 pass
参数构造 gate55 小函数完整模型以验证编译成本；未更换优化级别、未改调度语义。
详见 [NO0573](../../grhsim_opt/NO0573_grhsim_ir_cpu_port_names_20260907.md) 和
[NO0574](../../grhsim_opt/NO0574_grhsim_ir_cpu_bounded_functions_20260907.md)。

gate55 全模型生成/fresh-load/round-trip 通过，首两个小 task 的 O3 编译合计 0.82 秒。
据实际编译证据停止 gate54 大函数构建（主动退出 130，产物保留），转由既有根 Makefile
以 8-way O3 编译 gate55 全模型；并非降低优化级别或把超时当失败。
HDLBits 第三轮 001–118 通过，119 揭示参数化库名与稳定 GrhTB 库名不匹配，生成
Makefile 已补 LIB 变量复用 legacy 别名路径，第四轮全量验证中。
详见 [NO0575](../../grhsim_opt/NO0575_grhsim_ir_cpu_hdlbits_library_alias_20260907.md)。

IR HDLBits 第四轮完整退出 0，162/162 现有 GrhTB 全部执行并通过，覆盖前述
016/032/119 修复。结构化域统计为 84 个无 commit 域模型、75 input/5 derived/
18 general 域，已按双边沿、位选时钟与 latch RTL 抽查；不是全量波形覆盖率证明。
legacy 119 独立运行有异步复位断言失败，未计入通过；legacy 001 正常。
XiangShan gate55 O3 编译继续，10k/50k 和性能要求保持未完成。
详见 [NO0576](../../grhsim_opt/NO0576_grhsim_ir_cpu_hdlbits_full_gate_20260907.md)。

gate55 全模型 O3 编译、archive 和 emu 链接后续退出 0，6255 个模型对象全部完成，
wall 11:58.60。默认 8 MiB 栈的 1k 运行也已退出 0，首次提交在 cycle 600 前出现，
终态 instrCnt=3、cycleCnt=996，NEMU 已启用且未报告不一致；采样指令/PC 与已有
legacy 启动段记录一致。host time 57958 ms，稳定段仍约 55 ms/cycle，不能报告
性能达标或 CoreMark 程序完成。只读发现整数组暂存/发布和部分宽值无条件 fanout
激活的性能疑点，尚无 profile 归因，本次不据猜测修改代码或启动新构建。
按用户讨论保留 DPI compute + 可选 event + 实际调用策略，不移除 void call。
10k/50k、多时钟 DUT 扩展和性能门禁继续未完成。
详见 [NO0577](../../grhsim_opt/NO0577_grhsim_ir_cpu_gate55_full_o3_build_20260907.md) 和
[NO0578](../../grhsim_opt/NO0578_grhsim_ir_cpu_gate55_o3_runtime_20260907.md)。

gate55 通过临时 driver 探针完成相同 1k 观测：compute 17.9s、commit 34.9s、publish
6.1s，累计 17.5 亿次 pending 中约 64.5% 最终未变化，主要是小状态而非大数组。
探针已撤去并恢复原 O3 链接。现新增 cpu_store，event history 和标量写在有效的
shadow/visible 值变化时才入队；保留 NBA 发布和 DPI 策略。新增同拍写回原值与
32 次重复 eval 回归，全套 CPU 测试通过，cpu_chain/Verilator 增至 4136 样本。
独立 gate56 fresh generation 正在运行，性能收益及 10k/50k 尚待完整模型验证。
详见 [NO0579](../../grhsim_opt/NO0579_grhsim_ir_cpu_gate55_phase_profile_20260907.md) 和
[NO0580](../../grhsim_opt/NO0580_grhsim_ir_cpu_unchanged_state_staging_20260907.md)。

gate56 fresh generation/load/round-trip 后续退出 0，86.382 秒，完整 O3 构建已启动。
与此同时新增两个独立多时钟 DUT：CDC 计数/两级采样 10756 样本、双时钟 masked RAM
9731 样本，均逐步通过 CPU/Verilator/独立记分板对照，覆盖同时边沿、异步 reset、
读旧写新和空闲域；连同 cpu_chain 已有三个独立多时钟 DUT。IR fixture 为手工构造，
不是 ingest 自动等价证明。全套 CPU 回归 28.16 秒通过，HDLBits 全量复跑中。
详见 [NO0581](../../grhsim_opt/NO0581_grhsim_ir_cpu_multiclock_extended_gate_20260907.md)。

不变状态入队修复后的 HDLBits 全量复跑已退出 0，162/162 既有 GrhTB 通过，产物
保存在新的 ptmp/hdlbits-grhsim-ir-ExFf6s。gate55/gate56 完整 IR checkpoint 经 cmp
确认逐字节相同，完整模型对照仅改变 emit 实现。gate56 O3 编译仍在进行，运行性能
尚未测得。详见 [NO0582](../../grhsim_opt/NO0582_grhsim_ir_cpu_unchanged_state_hdlbits_gate_20260907.md)。

gate56 全模型 O3 构建退出 0，6255 个对象，wall 13:48.87。1k 实测虽仍提交 3 条
指令且没有 NEMU 不一致，耗时却为 68502 ms，劣于 gate55 的 57958 ms。故已完整
撤回逐写口不变检查，不以减少 pending 数量替代真实收益；新增覆盖顺序和多时钟测试
保留，恢复版全套测试 24.89 秒通过。gate56 产物保留为负结果证据，不作为推荐基线。
现经原 Makefile 在 ptmp/xs_gate55_baseline 独立编译 harness 并链接已有 gate55 O3
模型，避免误运行默认目录里的 gate56；下一步用显式入口推进 10k NEMU 窗口。
详见 [NO0583](../../grhsim_opt/NO0583_grhsim_ir_cpu_gate56_full_o3_build_20260907.md) 和
[NO0584](../../grhsim_opt/NO0584_grhsim_ir_cpu_unchanged_state_runtime_rejection_20260907.md)。

独立 gate55 harness 的真实 IR 10k 运行已退出 0，NEMU 启用且未报告不一致，最终
instrCnt=458、cycleCnt=9996。每千周期的十个采样及终态计数与同配置 legacy 10k
完全一致；两路都是前 8k 仅 3 条指令，9k 才推进至 238 条，10k 为 458 条。
IR 报告 host 556818 ms；期间并行核对 legacy 功能轨迹，不用于正式性能 A/B。
另完成既有 legacy 50k 参考：73580 条指令、cycleCnt=49996，未报告 NEMU 不一致，
50 个每千周期样本保留。IR 50k 尚未执行，性能验收仍未达标，不能宣布目标完成。
恢复版包安装与全部运行进程均已终态结束；后续私有 history 批量暂存候选只记录了
安全条件，尚未实现，不把设计意图计入完成项。
详见 [NO0585](../../grhsim_opt/NO0585_grhsim_ir_cpu_history_batch_design_20260907.md)、
[NO0586](../../grhsim_opt/NO0586_grhsim_ir_cpu_gate55_10k_functional_gate_20260907.md) 和
[NO0587](../../grhsim_opt/NO0587_grhsim_legacy_50k_functional_reference_20260907.md)。

已实现更窄的同 commit 函数 history 批量暂存：仅处理私有、连续、同类型且发布目标
相同的历史，guard 仍读各自旧值，复用原 shadow/pending/publish；DPI 路径不变。
专门反例 4624 样本覆盖不同初值、共享、被读取/普通写入和重新初始化；完整 CPU
回归及多事件 pattern 命中断言通过，26.60 秒。独立 gate57 从相同 GRH/batch 配置
生成中，覆盖量及运行收益尚待测量，不凭减少 pending 宣告性能完成。
详见 [NO0588](../../grhsim_opt/NO0588_grhsim_ir_cpu_history_batch_implementation_20260907.md)。

gate57 完整生成及 fresh-session round-trip 已退出 0，86.608 秒。与 gate55 的
完整 IR JSON 和公开模型头文件逐字节相同，实际覆盖 391659 histories、3240 批，
最大批次 8030 字节。O3 全模型构建与 HDLBits 全量回归仍在运行；DPI 维持现状，
不更改可选 event 或 compute 归属。IR 50k 与性能验收仍未完成。
详见 [NO0589](../../grhsim_opt/NO0589_grhsim_ir_cpu_gate57_generation_20260907.md)。

history 批量暂存版 HDLBits 全量复跑已退出 0，162/162 用例通过，独立产物位于
ptmp/hdlbits-grhsim-ir-sGo6Dl。全模型 O3 构建仍在运行，真实运行及性能待验证。
详见 [NO0590](../../grhsim_opt/NO0590_grhsim_ir_cpu_history_batch_hdlbits_gate_20260907.md)。

gate57 全模型 O3 构建已退出 0，6255 模型对象及 harness 链接完成，wall 11:43.31。
默认 build/xs/grhsim-ir/emu/emu 已更新为 gate57，不再是 gate56；独立 gate55 基线
保留。此次仅收齐交接中的构建与回归，没有启动新仿真。DPI 按讨论保持现状，
gate57 实际运行、IR 50k 和配套性能门禁仍未验证。
详见 [NO0591](../../grhsim_opt/NO0591_grhsim_ir_cpu_gate57_full_o3_build_20260907.md)。

gate57 实际 1k 已退出 0，NEMU 启用且无不一致，3 条指令和 PC 与基线相同。
host 40631 ms，较 gate55 的 57958 ms 下降约 29.9%，仅作单次短窗口对照。
随后通过 run-only Makefile 入口启动真实 IR 50k，日志 ptmp/grhsim_gate57_o3_50000.log；
不并行构建或其他仿真。50k 终态与配套 legacy 性能比较仍待验证。
详见 [NO0592](../../grhsim_opt/NO0592_grhsim_ir_cpu_gate57_1k_runtime_20260907.md)。

同一 gate57 50k 进程已越过 20k，14121 条指令，前 20 个每千周期采样全部匹配
legacy。10k 检查点为 458 条指令、host 388608 ms。NEMU 尚无不一致，进程确认
存活并继续向 50k 推进；这里不是终态 gate，也没有缩短目标窗口。
详见 [NO0593](../../grhsim_opt/NO0593_grhsim_ir_cpu_gate57_20k_checkpoint_20260907.md)。

gate57 的真实 IR 50k 已退出 0，NEMU 启用且无不一致。最终 instrCnt=73580、
cycleCnt=49996、guest cycles=50001；50 个严格连续的每千周期采样和退出原因、
终态计数/IPC、seed/guest-cycle 三项均与 legacy 完全一致。实际 IR 50k 功能窗口
现已补齐，不代表整个 CoreMark 程序完成。host 2073729 ms，性能仍明显不达标；
IR 结束后已串行启动 legacy 50k 配套测量，目标保持未完成。
详见 [NO0594](../../grhsim_opt/NO0594_grhsim_ir_cpu_gate57_50k_functional_gate_20260907.md)。

配套串行 legacy 50k 后续退出 0，153356 ms；本次两路全部 50 个连续进度采样及
三项终态再次完全相同。IR/legacy 耗时比 13.522321，明确未达到不差于 legacy 5%
的要求。功能 50k 已通过，但整体目标不完成；下一步需重新测 gate57 的阶段成本，
不能直接沿用 gate55 的 profile 归因。全部运行进程现已终态结束。
详见 [NO0595](../../grhsim_opt/NO0595_grhsim_ir_cpu_gate57_50k_serial_performance_20260907.md)。

gate57 新 1k profile 已通过并完整撤去探针、恢复普通 driver/二进制：compute
17.98s、commit 21.05s、publish 1.19s，pending 为 159871274，轮次仍 4278。
下一候选限定为唯一写者且无 commit/history 观察者的标量原地提交，保留 E 的最终
比较与 next-arm；先完成资格证明和反例测试，不据 pending 降低宣称性能达标。
详见 [NO0596](../../grhsim_opt/NO0596_grhsim_ir_cpu_gate57_phase_profile_20260907.md) 和
[NO0597](../../grhsim_opt/NO0597_grhsim_ir_cpu_private_scalar_commit_design_20260907.md)。

已实现唯一写者、无 commit/history 观察者的标量 direct commit，只有 E 的真变化
进入延续归约，next-arm/多写者/非候选 shadow 发布不变。全套 CPU 回归 27.84s
通过；新非 E fixture 4612 次 eval 恰 4612 次真实 DPI 调用且均观察旧值，4 次 init。
多写者/history 回退和三个多时钟 DUT 保持通过。完整模型将使用独立 gate58/新 ABI，
尚未证明收益；gate57 的 50k 通过不能替代新实现的完整模型验证。
详见 [NO0598](../../grhsim_opt/NO0598_grhsim_ir_cpu_private_scalar_commit_implementation_20260907.md)。

gate58 独立生成/fresh-session round-trip 已退出 0，88.785s，完整 IR 与 gate57
逐字节相同。284775 个状态进入 direct commit，history batching 覆盖量不变。
task_5570 源码变长，不能据此猜测运行收益。独立 ptmp/xs_gate58 harness 的完整
O3 构建及 HDLBits 全量正在运行，gate57 基线保留；真实性能等待构建结束后测量。
详见 [NO0599](../../grhsim_opt/NO0599_grhsim_ir_cpu_gate58_generation_20260907.md)。

direct commit 的 HDLBits 全量已退出 0，162/162 通过。完整模型静态 direct 覆盖
拆分为 E 内 216523、E 外 68252 个状态；后者不产生延续条件。gate58 O3 构建仍在
进行，真实性能与完整模型功能尚未验证。
详见 [NO0600](../../grhsim_opt/NO0600_grhsim_ir_cpu_private_commit_hdlbits_gate_20260907.md)。

gate58 完整 O3 构建已退出 0，6255 个模型对象及独立 harness 完成，wall 16:46.94，
比 gate57 编译更慢，archive 为 182872038 字节。新入口 ptmp/xs_gate58/emu/emu
与旧基线分开。首轮 1k 为 36990 ms、3 条指令/PC 一致；收益较小，正在串行 A/B
复测，不据单次短窗口宣告优化或完整性能门禁完成。
详见 [NO0601](../../grhsim_opt/NO0601_grhsim_ir_cpu_gate58_full_o3_build_20260907.md)。

gate58 首轮 1k 36990 ms 后进行了串行复测：gate57 40412 ms、gate58 37784 ms，
配对改善约 6.5%，均为 3 条指令/PC 一致、NEMU 无不一致、退出 0。暂留为小幅改善
候选，不忽略编译时间增加或宣称性能达标。独立 gate58 10k 已启动，日志
ptmp/grhsim_gate58_o3_10000.log；新实现的 50k 仍未验证。
详见 [NO0602](../../grhsim_opt/NO0602_grhsim_ir_cpu_gate58_1k_serial_pair_20260907.md)。

gate58 独立真实 10k 后续退出 0，458 条指令、cycleCnt=9996、guest=10001，NEMU
无不一致；十个连续进度采样及三项终态全部匹配 legacy。host 358864 ms，新实现
已越过启动段，但实际 50k 与最终性能仍未验证；旧 gate57 50k 基线保留。本轮
全部进程均已终态结束。下一步继续依据 compute/commit 成本推进优化，不以约 6.5%
短窗口收益缩减整体目标或宣布完成。
详见 [NO0603](../../grhsim_opt/NO0603_grhsim_ir_cpu_gate58_10k_functional_gate_20260907.md)。

在实现 inactive-edge 性能候选前，新跨域共享 history 回归先发现现有 gate58 的调度
反例：A=1/B=0/H=0 时仅改变 data，A 的 guard 仍成立但域未 arm。性能分支暂缓，
先将 history 不同源采样或有普通写者的相关边沿域物化为 AlwaysScanCommit；同源共享
仍门控，保留任务顺序和逐 op guard/采样，私有 history batching 仍适用。调度、运行时
回归与完整 XiangShan mapping 兼容性待核验，DPI 策略不变。
详见 [NO0604](../../grhsim_opt/NO0604_grhsim_ir_cpu_shared_history_schedule_design_20260907.md)。

共享 history 修复已通过调度套件（0.01s）与完整 CPU 发射回归（28.01s）。新增独立
G scoreboard 完成 4636 次 eval、四次 init；同源共享不回退，不同源共享/普通写者
回退及 JSON/verifier 负例均通过。私有 batching 仍为 12 个状态/2 批，三类多时钟
回归和 4612 次真实 void DPI 观察旧值均保持通过。完整 gate58 XiangShan checkpoint
经新 verifier 成功载入，证明现有 schedule 不受本次修复影响；没有重新构建或运行
完整模型，也未重跑 HDLBits。下一步继续 inactive-edge 性能候选，完整目标保持未完成。
详见 [NO0605](../../grhsim_opt/NO0605_grhsim_ir_cpu_shared_history_schedule_gate_20260907.md)。

开始 inactive-edge sampling-only 候选：DomainGatedCommit 中所有 posedge event=0、
negedge event=1 时跳过 payload，仅按原序 stage history 并执行原私有 batching。
其余走原完整 body；general/冲突回退域不参与，真实 event 项去重并以 8 项为上限。
不改 DPI、ingest、mapping 或运行时 helper ABI；收益与完整模型验证尚待实测。
详见 [NO0606](../../grhsim_opt/NO0606_grhsim_ir_cpu_inactive_edge_sampling_design_20260907.md)。

sampling-only 实现及 CPU 完整回归已通过（补齐 8/9 项 emission 边界后 28.10s）；
三个 edge domain 的生成分支和 general/冲突回退域无分支均有检查，原多时钟/共享
history/非 E 真实 void DPI 测试保持通过。项目内 make py_install 完成后，已启动
独立 gate59 生成/fresh roundtrip 和 HDLBits 全量；旧基线未修改，真实性能待验证。
详见 [NO0607](../../grhsim_opt/NO0607_grhsim_ir_cpu_inactive_edge_sampling_implementation_20260907.md)。

gate59 独立生成/fresh roundtrip 已退出 0（90.843s），完整 IR/mapping 与 gate58
逐字节相同。生成目录排除对象/archive 后恰有 514 个 commit task 源码变化，恰有
514 个 sampling-only 分支；header/runtime/driver/其余源码不变。task_5570 源码略
增长，不能推断运行收益。独立 O3 构建已启动，HDLBits 仍进行中，性能运行等待二者结束。
详见 [NO0608](../../grhsim_opt/NO0608_grhsim_ir_cpu_gate59_generation_20260907.md)。

当前代码 HDLBits 全量已退出 0，162/162，独立目录 ptmp/hdlbits-grhsim-ir-1FWZUs。
本次同时覆盖共享 history 调度修复和 sampling-only 发射。gate59 O3 全模型构建仍在
进行，没有并行启动性能仿真；新模型的 10k/50k 与性能结果仍待验证。
详见 [NO0609](../../grhsim_opt/NO0609_grhsim_ir_cpu_inactive_edge_hdlbits_gate_20260907.md)。

gate59 完整 O3 构建已退出 0，6255 个对象及独立 harness 完成，wall 16:51.93，
archive 182956358 字节，均比 gate58 略增。最后的三个大函数通过同一存活会话等待
完成，没有重启。全部构建/HDLBits 终态后，开始 gate58 再 gate59 的串行 1k A/B；
这不是实际 10k/50k 或最终性能门禁。
详见 [NO0610](../../grhsim_opt/NO0610_grhsim_ir_cpu_gate59_full_o3_build_20260907.md)。

gate58/gate59 正反序串行 1k 配对均退出 0：37301->26071 ms，37937->26333 ms，
改善 30.1%/30.6%。四次均 3 条指令、commit PC=0x10000008，终态一致且 NEMU 无
不一致；保留两组数字，不宣称完整窗口性能达标。随后启动 gate59 独立真实 10k，
日志 ptmp/grhsim_gate59_o3_10000.log；其 50k 与整体性能仍未验证。
详见 [NO0611](../../grhsim_opt/NO0611_grhsim_ir_cpu_gate59_1k_serial_pairs_20260907.md)。

gate59 独立真实 10k 已退出 0，458 条指令、cycleCnt=9996、guest=10001，host
248674 ms，Difftest 无不一致。十个严格有序的采样全部匹配 legacy 前十项；三项
终态与已验证 gate58 10k 一致。日志提取允许 UART 文本前缀，未漏计非行首进度。
本阶段所有会话已终态；gate59 实际 50k 与最终 legacy+5% 门禁尚未验证，不能继承
gate57 的 50k 证明或按 1k 的约 30% 改善宣告完整目标完成。
详见 [NO0612](../../grhsim_opt/NO0612_grhsim_ir_cpu_gate59_10k_functional_gate_20260907.md)。

已核对 gate59 二进制及实现指纹，启动独立真实 50k，日志
ptmp/grhsim_gate59_o3_50000.log。运行期不改代码、不并行构建或其他仿真；逐千周期
对照已有完整 legacy 采样，IR 终态后再串行测 legacy 配套耗时。这里仅为 runbook，
尚无 gate59 50k 终态或性能结论，整体目标保持未完成。
详见 [NO0613](../../grhsim_opt/NO0613_grhsim_ir_cpu_gate59_50k_runbook_20260907.md)。

同一 gate59 50k 进程已越过 20k 检查点：14121 条指令、host 524172 ms，前二十个
连续采样全部匹配 legacy；随后到 21k/14987 条指令仍一致。进程持续存活，未改
50000-cycle 上限、不并行构建/仿真；这只是中途证据，50k 终态与串行性能仍待验证。
详见 [NO0614](../../grhsim_opt/NO0614_grhsim_ir_cpu_gate59_20k_checkpoint_20260907.md)。

gate59 真实 IR 50k 已退出 0，73580 条指令、cycleCnt=49996、guest=50001，NEMU
无不一致。全部 50 个严格有序采样及三项终态匹配 legacy，host 1371764 ms；实现和
二进制指纹前后一致。当前候选已补齐自身 50k 功能证据，但不是整个 CoreMark 程序
完成。IR 终态后已启动配套串行 legacy 50k，性能门禁尚待新分母，整体目标不完成。
详见 [NO0615](../../grhsim_opt/NO0615_grhsim_ir_cpu_gate59_50k_functional_gate_20260907.md)。

配套串行 legacy 50k 已退出 0，155030 ms；与本次 gate59 的全部 50 个有序采样及
三项终态完全相同。IR/legacy=8.848378，明确未达到不差于 legacy 5% 的门禁。当前
候选实际 50k 功能已通过，但整体目标不完成。所有进程已终态；保留 gate59 基线，
下一步测其新的 compute/commit/publish 阶段成本，不能套用 gate57 的旧 profile。
详见 [NO0616](../../grhsim_opt/NO0616_grhsim_ir_cpu_gate59_50k_serial_performance_20260907.md)。

gate59 新阶段 profile 已退出 0：2102 eval/4278 轮，compute 15423.304 ms、commit
10047.332 ms、publish 957.586 ms；commit 低/高电平为 520.795/9526.537 ms。
pending 为 80605800，direct E helper 调用 792762 次。compute 已是最大项，但
commit 仍显著；不能从总量直接判定具体 helper 根因。已保留实际 50k 普通二进制，
正在仅通过 driver 调用点做任务级定位，结束后撤去全部探针并恢复普通构建。
详见 [NO0617](../../grhsim_opt/NO0617_grhsim_ir_cpu_gate59_phase_profile_20260907.md)。

任务级 profile 已完成，compute/commit 任务计时为 15935.722/10023.501 ms，
高成本 compute 函数中确认存在调用 guard 之前的常量字符串构造。全部 driver
探针已撤去并通过现有 make 恢复，普通二进制与实际 50k 验证备份 SHA-256 相同。
下一候选参考 legacy 在使用点引用常量，保留动态字符串、真实 void 调用、event
和 history 采样；这不是已证实的性能收益，也不改变 DPI 分类或 ingest 规则。
详见 [NO0618](../../grhsim_opt/NO0618_grhsim_ir_cpu_gate59_task_profile_20260907.md)。

常量字符串使用点发射已实现；layout 槽保留但不再绑定常量字符串对象或逐轮赋值，
动态字符串与 DPI/event/history 语义不变。共享长字符串/转义、真实 void 调用计数、
inout 副本修改及 hold、local/boundary 对象结构检查均通过；最终 CPU 全套 28.26s。
正在通过项目 make 安装到本地环境，下一步生成独立 gate60 并测性能，尚无 XS 新候选
运行结论，整体性能门禁仍未完成。
详见 [NO0619](../../grhsim_opt/NO0619_grhsim_ir_cpu_string_use_site_implementation_20260907.md)。

项目内 make 安装和独立 gate60 生成/fresh roundtrip 均已退出 0（93.734s）；与 gate59
完整 IR/mapping 逐字节相同，仅 48 个 compute 源码变化，header/driver/runtime/commit
均未变。task5527 的 512 处独立字符串赋值归零。独立 O3 make 构建已启动，HDLBits
仍进行中；待两者终态后串行比较普通二进制，不把代码形态当成性能结果。
详见 [NO0620](../../grhsim_opt/NO0620_grhsim_ir_cpu_gate60_generation_20260907.md)。

gate60 当前字符串优化实现的 HDLBits 全量已退出 0，162/162，独立目录
ptmp/hdlbits-grhsim-ir-Wr1pJe，日志 ptmp/grhsim_gate60_hdlbits.log。O3 构建仍在
同一会话进行，尚未启动候选性能运行；不将 HDLBits 通过等同于 XS 50k 或性能达标。
详见 [NO0621](../../grhsim_opt/NO0621_grhsim_ir_cpu_string_use_site_hdlbits_20260907.md)。

gate60 独立 O3 构建已退出 0，6255 对象，wall 16:44.10，archive 179022346 字节，
实际 executable 160998512 字节；入口 symlink 指向候选自身产物。基线保持不变，
全部构建/HDLBits 会话终态后开始普通二进制的正反序串行 1k 对比，尚无新性能结论。
详见 [NO0622](../../grhsim_opt/NO0622_grhsim_ir_cpu_gate60_full_o3_build_20260907.md)。

gate59/gate60 正反序串行 1k 配对全部退出 0：26283→21547 ms、26187→21899 ms，
改善 18.0%/16.4%；四次均 3 条指令，采样和三项终态完全相同、NEMU 无不一致。
常量字符串使用点优化有可重复短窗口收益，但不代表 50k 或 legacy+5% 达标。
已启动 gate60 自身真实 10k，日志 ptmp/grhsim_gate60_o3_10000.log，尚待终态。
详见 [NO0623](../../grhsim_opt/NO0623_grhsim_ir_cpu_gate60_1k_serial_pairs_20260907.md)。

gate60 自身真实 10k 已退出 0，host 205321 ms，458 条指令、cycleCnt=9996、
guest=10001；十个严格有序采样全部匹配 legacy，三项终态与 gate59 10k 相同，NEMU
无不一致，实现和二进制指纹未变。所有会话已终态；保留字符串优化与两套普通基线，
下一步基于新候选重测剩余成本，不套用旧阶段比例。gate60 实际 50k 与最终 legacy+5%
仍未验证，整体目标不完成。
详见 [NO0624](../../grhsim_opt/NO0624_grhsim_ir_cpu_gate60_10k_functional_gate_20260907.md)。

gate60 新阶段 profile 已完成：compute 10831.274 ms、commit 9761.305 ms、publish
908.257 ms；4278 轮及所有 pending/搬运计数与 gate59 相同。commit 高电平仍占
9286.151 ms。全部探针撤去并 make 恢复，普通二进制与 10k 验证备份逐字节一致。
详见 [NO0625](../../grhsim_opt/NO0625_grhsim_ir_cpu_gate60_phase_profile_20260907.md)。

下一候选设计为只读扫描连续 history 区间，拒绝已经采样过的边沿并复用原 sampling-only
分支；不共享或抹掉 history，不改各 op guard、采样顺序、DPI 或 schedule。需要独立
实现和测试，尚无此候选运行收益结论。
详见 [NO0626](../../grhsim_opt/NO0626_grhsim_ir_cpu_history_scan_design_20260907.md)。

history 区间只读扫描已实现；单区间用 memchr，多区间用 constexpr offset/size 表，
小组及稀疏组回退原电平必要条件。四种新增运行各通过 4632 样本/四次 init，完整 CPU
回归 35.15s，schedule 测试通过。模型、mapping、DPI、原 guard/采样均未改；正在
make 安装本地包，下一步独立 gate61 生成与 HDLBits，尚无 XS 运行收益结论。
详见 [NO0627](../../grhsim_opt/NO0627_grhsim_ir_cpu_history_scan_implementation_20260907.md)。

独立 gate61 生成/fresh roundtrip 已退出 0（94.386s），完整 IR/mapping 与 gate60
逐字节相同。仅 95 个 commit 源码变化，扫描 95 组/184371 个 history 成员/2078 段，
header/driver/runtime/compute 未变。独立 O3 make 构建已启动，HDLBits 仍在运行；
这些是静态覆盖证据，尚不能宣称实际收益。
详见 [NO0628](../../grhsim_opt/NO0628_grhsim_ir_cpu_gate61_generation_20260907.md)。

history scan 当前实现的 HDLBits 全量已退出 0，162/162，产物目录
ptmp/hdlbits-grhsim-ir-IajCyN，日志 ptmp/grhsim_gate61_hdlbits.log。独立 O3 构建
仍在原会话进行，尚未并行启动性能仿真；XS 新候选运行结果仍待验证。
详见 [NO0629](../../grhsim_opt/NO0629_grhsim_ir_cpu_history_scan_hdlbits_20260907.md)。

gate61 独立 O3 构建已退出 0，6255 对象及 harness，wall 16:35.72，archive
179181250 字节、实际 executable 161143136 字节。另确认 95 个差异文件在入口条件
之后逐字节一致。全部构建/HDLBits 终态后开始 gate60/gate61 正反序串行 1k 对比，
尚无本候选运行收益结论。
详见 [NO0630](../../grhsim_opt/NO0630_grhsim_ir_cpu_gate61_full_o3_build_20260907.md)。

gate60/gate61 两组正反序串行 1k 全部退出 0：21910→18958 ms、21643→19153 ms，
改善 13.5%/11.5%。四次采样和终态完全一致、NEMU 无不一致，候选扫描有可重复短
窗口收益，但不代表最终性能达标。已启动 gate61 独立真实 10k，日志
ptmp/grhsim_gate61_o3_10000.log，尚待终态。
详见 [NO0631](../../grhsim_opt/NO0631_grhsim_ir_cpu_gate61_1k_serial_pairs_20260907.md)。

gate61 自身真实 10k 已退出 0，host 178709 ms，458 条指令、cycleCnt=9996、
guest=10001；十个严格有序采样全部匹配 legacy，三项终态与 gate60 相同，NEMU
无不一致，实现和二进制指纹未变。保留 history scan 及三套参考产物，全部会话已
终态。新候选实际 50k 和最终 legacy+5% 仍未验证，整体目标不完成；下一步重测
剩余阶段成本后再选择独立优化，不沿用旧比例。
详见 [NO0632](../../grhsim_opt/NO0632_grhsim_ir_cpu_gate61_10k_functional_gate_20260907.md)。

gate61 阶段 profile 完成：compute/commit/publish 为 10355.885/7313.079/890.905 ms，
4278 轮和全部搬运计数与 gate60 一致。探针撤去并 make 恢复后，普通二进制与 10k
备份逐字节一致。详见 [NO0633](../../grhsim_opt/NO0633_grhsim_ir_cpu_gate61_phase_profile_20260907.md)。

下一阶段处理宽 and/or/xor/not 的真变化激活，按 legacy 指针输出策略逐字比较并写回；
加减和移位的无条件激活仍是待处理项。DPI/event 和 mapping 不变，尚无候选性能结论。
设计见 [NO0634](../../grhsim_opt/NO0634_grhsim_ir_cpu_wide_bitwise_activity_design_20260907.md)。

宽位运算真变化激活已实现，tracked/local 两种生成模型各通过 1792 helper case 和
8192 eval/四次 init，完整 CPU 回归最终 37.47s，schedule 测试通过。make 安装候选
进行中，随后生成独立 gate62 并验证 HDLBits；尚无 XS 候选性能结论。
详见 [NO0635](../../grhsim_opt/NO0635_grhsim_ir_cpu_wide_bitwise_activity_implementation_20260907.md)。

独立 gate62 生成/fresh roundtrip 已退出 0（95.817s），IR/mapping 与 gate61 逐字节
相同。仅 header 及 271 个 compute 文件变化，852 处 tracked 位运算使用真变化门控，
27408 处 local 位运算保留 legacy 指针 helper。HDLBits 仍在运行，XS O3 构建尚未启动。
详见 [NO0636](../../grhsim_opt/NO0636_grhsim_ir_cpu_gate62_generation_20260907.md)。

gate62 当前实现的 HDLBits 全量已退出 0，162/162，产物目录
ptmp/hdlbits-grhsim-ir-Ajkt8b，日志 ptmp/grhsim_gate62_hdlbits.log。所有会话终态，
源码和已安装包为 gate62；gate61 普通参考保持原指纹。下一步通过现有 Makefile
构建独立 gate62 O3 XS，再串行比较；尚无新候选 1k/10k/50k 或性能达标证据。
宽加减/移位真变化门控和最终 legacy+5% 仍未完成，目标继续保持。
详见 [NO0637](../../grhsim_opt/NO0637_grhsim_ir_cpu_wide_bitwise_hdlbits_gate_20260907.md)。

gate62 独立 O3 构建已退出 0，6255 模型对象及 harness，wall 16:38.06，archive
179388298 字节、实际 executable 161315168 字节。原构建会话确认终态后开始普通
gate61/gate62 串行 1k 配对；候选自身 XS 运行和性能结论仍待验证。
详见 [NO0638](../../grhsim_opt/NO0638_grhsim_ir_cpu_gate62_full_o3_build_20260907.md)。

gate61/gate62 正反序串行 1k 配对全部退出 0：18655→18632 ms、18951→18880 ms，
四次功能采样和终态一致，NEMU 无不一致。差异仅 0.12%/0.37%，不足以宣称明显加速；
保留真变化门控以补齐计划约束，实际收益仍未证实。已启动 gate62 自身 10k，日志
ptmp/grhsim_gate62_o3_10000.log，终态和候选 50k 仍待验证。
详见 [NO0639](../../grhsim_opt/NO0639_grhsim_ir_cpu_gate62_1k_serial_pairs_20260907.md)。

gate62 自身真实 10k 已退出 0：175061 ms，458 指令，cycleCnt=9996、guest=10001，
十个有序采样及三项终态匹配参考，NEMU 无不一致，源码和二进制指纹保持不变。
详见 [NO0640](../../grhsim_opt/NO0640_grhsim_ir_cpu_gate62_10k_functional_gate_20260907.md)。

已用同一 gate62 普通 O3 二进制启动真实 50k，日志 ptmp/grhsim_gate62_o3_50000.log；
无并行构建或其他仿真，终态后再串行重测 legacy 分母。50k 终态和性能门禁仍待验证，
不把 10k 通过或旧候选 50k 当作当前候选证明。
运行约束见 [NO0641](../../grhsim_opt/NO0641_grhsim_ir_cpu_gate62_50k_runbook_20260907.md)。

同一 gate62 50k 进程已到 20k：14121 指令、host 385179 ms；前二十个连续采样
均匹配 legacy，NEMU 未报告不一致。原进程确认仍活跃并继续向 50k 推进，未缩短
上限、未并行构建或其他仿真；终态和串行性能分母仍待验证。
详见 [NO0642](../../grhsim_opt/NO0642_grhsim_ir_cpu_gate62_20k_checkpoint_20260907.md)。

gate62 真实 IR 50k 已退出 0：73580 指令，cycleCnt=49996、guest=50001，host
1024849 ms；50 个连续采样和三项终态全部匹配 legacy，NEMU 无不一致，二进制
及源码指纹保持不变。IR 终态后已串行启动 legacy 50k 配套测量，实际分母仍待终态。
当前候选的 50k 功能窗口通过，但不代表整个 CoreMark 程序完成或最终性能门禁达标。
详见 [NO0643](../../grhsim_opt/NO0643_grhsim_ir_cpu_gate62_50k_functional_gate_20260907.md)。

配套串行 legacy 50k 已退出 0，155179 ms；本次两路 50 个有序采样和三项终态全部
一致。IR/legacy=6.604302，未达到 legacy+5% 的性能门禁，仍需约 84.1% 的 IR 降幅。
保留 gate62 为新的真实 50k 普通参考，源码/二进制指纹未变，所有会话终态。下一步
重测当前阶段成本后再选择优化；宽加减/移位真变化门控及完整计划验收仍有待完成。
详见 [NO0644](../../grhsim_opt/NO0644_grhsim_ir_cpu_gate62_50k_serial_performance_20260907.md)。

gate62 阶段/task profile 完成，compute/commit/publish 为 11158.037/7532.509/923.530 ms，
所有轮数及搬运计数与 gate61 一致。热点 commit 包含稀疏 history 任务；联合探针有计时
开销，仅用于归因。探针已撤去并 make 恢复，普通二进制与 50k 备份逐字节相同。
详见 [NO0645](../../grhsim_opt/NO0645_grhsim_ir_cpu_gate62_phase_task_profile_20260907.md)。

下一候选检查完整 task 的私有 bool history 是否全部等于当前事件值，若是则 payload
和采样均无变化，可以直接返回；任一不同或共享/观察/其他写者均保留原路径。
不改变 DPI/event、schedule 或历史值，尚未验证收益。
设计见 [NO0646](../../grhsim_opt/NO0646_grhsim_ir_cpu_stable_history_skip_design_20260907.md)。

私有 stable-history task skip 已实现：连续字节 memchr、稀疏精确 offset 表，原 guard/
采样/批量历史路径保留。七种有效寄存器/内存变体及 signed 回退各通过 4632 样本/四次
init；14/16 history 和 8/9 ValueId 阈值、共享/观察/其他写者回退通过，最终完整 CPU
回归 51.82s，schedule 通过。正在 make 安装候选，随后独立 gate63 生成及 HDLBits；
尚无 XS 实际收益结论。
详见 [NO0647](../../grhsim_opt/NO0647_grhsim_ir_cpu_stable_history_skip_implementation_20260907.md)。

gate63 安装已成功，独立 XS 生成/fresh roundtrip 已退出 0（94.704s）；IR/mapping
与 gate62 逐字节一致。仅 130 个 commit 文件各增加一行入口检查，删去该行后原函数体
逐字节一致；覆盖 392009 history，热点 task5636 为 8192 history/两个当前值组。
gate62 参考二进制指纹不变。HDLBits 全量仍在运行，候选 O3 构建及实际收益尚未验证。
详见 [NO0648](../../grhsim_opt/NO0648_grhsim_ir_cpu_gate63_generation_20260907.md)。

gate63 当前候选 HDLBits 全量已退出 0，001–162 有序全部通过，产物目录
ptmp/hdlbits-grhsim-ir-BVXt5e，日志 ptmp/grhsim_gate63_hdlbits.log。生成和回归会话
均已终态，源码指纹未变。独立候选 O3 尚未构建，下一步走既有 Makefile build-only
入口，再作 gate62/gate63 串行普通二进制比较及真实运行门禁；最终 legacy+5% 仍未完成。
详见 [NO0649](../../grhsim_opt/NO0649_grhsim_ir_cpu_stable_history_skip_hdlbits_20260907.md)。

gate63 独立 O3 构建已退出 0：6255 模型对象及 harness，wall 16:38.27，archive
181565350 字节，实际 executable 163291768 字节。gate62 指纹保持不变，原构建会话
终态后才开始 gate62/gate63 普通二进制串行 1k 配对；候选实际收益及 10k/50k 仍待验证。
详见 [NO0650](../../grhsim_opt/NO0650_grhsim_ir_cpu_gate63_full_o3_build_20260907.md)。

gate62/gate63 正反序串行 1k 全部退出 0，18487→15075 ms、18094→14553 ms，
短窗口下降 18.456%/19.570%。四次单采样和三项终态一致，NEMU 无不一致；仅三条退休
指令，不能外推最终性能。相同普通候选已启动真实 10k，日志 ptmp/grhsim_gate63_o3_10000.log，
终态及候选 50k 待验证，gate62 保持不变。
详见 [NO0651](../../grhsim_opt/NO0651_grhsim_ir_cpu_gate63_1k_serial_pairs_20260907.md)。

同一 gate63 普通 O3 候选真实 10k 已退出 0：143683 ms、458 指令，cycleCnt=9996、
guest=10001；十个有序采样和三项终态均匹配 gate62，NEMU 无不一致，源码及两路二进制
指纹保持不变。所有会话终态，下一步是候选真实 50k 后串行重测 legacy；尚无候选 50k
或最终 legacy+5% 结论，宽加减/移位真变化门控及完整计划验收仍待完成。
详见 [NO0652](../../grhsim_opt/NO0652_grhsim_ir_cpu_gate63_10k_functional_gate_20260907.md)。

已核验原指纹并启动同一 gate63 普通 O3 候选的真实 50k，日志
ptmp/grhsim_gate63_o3_50000.log；不重建、不加探针、不并行仿真，原进程终态后才串行
重测 legacy。完整 50k 功能及最终性能仍待验证，不能从 10k 或 1k 配对外推。
运行约束见 [NO0653](../../grhsim_opt/NO0653_grhsim_ir_cpu_gate63_50k_runbook_20260907.md)。

gate63 原 50k 进程已通过 20k：14121 指令、322929 ms，前二十个采样匹配 legacy，
后续 21k 也一致，原进程仍运行。用户明确要求本次测量后暂停：完成当前 IR 50k 与
配套串行 legacy 50k、报告实际速度差距后停下，不启动后续优化、profile、构建或仿真。
详见 [NO0654](../../grhsim_opt/NO0654_grhsim_ir_cpu_gate63_20k_checkpoint_20260907.md)。

gate63 原 50k 进程已退出 0：879581 ms、73580 指令，cycleCnt=49996、guest=50001，
全部五十个有序采样和三项终态匹配 legacy，NEMU 无不一致，源码/二进制指纹不变。
IR 终态后仅启动配套串行 legacy 50k，日志 ptmp/grhsim_legacy_50000_serial_gate63.log；
分母及最终比值待终态，完成后按用户要求暂停，不启动后续优化、profile 或构建。
详见 [NO0655](../../grhsim_opt/NO0655_grhsim_ir_cpu_gate63_50k_functional_gate_20260907.md)。

配套串行 legacy 50k 已退出 0，154286 ms；本次两路全部 50 个采样及终态一致。
gate63/legacy=879581/154286=5.700977，门槛 162000.30 ms，仍需减少 81.5821% IR
耗时；性能门禁未通过。全部测量会话终态，二进制指纹不变。已先向用户报告完整结果，
用户最新要求覆盖此前暂停：接着按分区分块规模、生成 C++ 整体结构、helper 实现质量
三个方向核查并修复，保留 gate63 普通参考及 DPI/event 语义。
详见 [NO0656](../../grhsim_opt/NO0656_grhsim_ir_cpu_gate63_50k_serial_performance_20260907.md)。

三方向审计：compute supernode 44686/63241、最大块 128/108，分区规模相近；
函数打包 5569/66 明显不同，gate63 显式 target_batch_count=0 禁用了默认调整。
结构上 local activeWordFlags 与全局 cpu_flags、表达式物化和提交缓冲仍有差异；
83 处宽加减/移位确实无条件激活下游，待按 pointer/out-buffer 单遍变化检测修复。
详见 [NO0657](../../grhsim_opt/NO0657_grhsim_ir_cpu_legacy_three_direction_audit_20260907.md)。

gate64 单变量恢复 target_batch_count=64，生成和 fresh roundtrip 退出 0（92.929s），
62 compute/452 commit；去 mappings 后语义模型哈希与 gate63 一致。独立 O3 原会话
95253 仍构建中；未宣称编译通过或性能收益，不改 DPI，不覆盖 gate63。
详见 [NO0658](../../grhsim_opt/NO0658_grhsim_ir_cpu_gate64_packing_generation_20260907.md)。

宽加减/移位已补 pointer/out-buffer 单遍真变化检测，不创建整块快照；无 fanout
保持原 legacy helper，DPI/event 与 mapping 不变。完整 CPU 回归 66.14s、schedule
通过；tracked/local 各 4480 helper 样本、8192 eval、四次 init，含 ASan/UBSan。
gate64 仍仅改变打包，不包含这次修复；新 helper 的 XS 收益与 HDLBits 待验证。
详见 [NO0659](../../grhsim_opt/NO0659_grhsim_ir_cpu_wide_arithmetic_shift_activity_20260907.md)。

gate65 helper-only 安装、XS 生成/fresh roundtrip 退出 0（152.975s），IR/mapping
与 gate63 逐字节一致；只变 header 和 38 compute 文件，43 加减/40 移位激活。
HDLBits 001-162 全通过，产物 ptmp/hdlbits-grhsim-ir-bzsu1p。尚无 XS 二进制或收益。
详见 [NO0660](../../grhsim_opt/NO0660_grhsim_ir_cpu_gate65_generation_hdlbits_20260907.md)。

结构方向单独对齐 legacy activeWordFlags：同 word 后续位更新局部字节，当前/先前位
与其他 word 保留全局队列，word 退出 OR 回未消费位；helper chunk 共享引用，激活按
offset 合并，不改 mapping、DPI/event 或 commit。inline/helper 两模式回归正在运行。
详见 [NO0661](../../grhsim_opt/NO0661_grhsim_ir_cpu_local_activity_word_design_20260907.md)。

局部 activity word 完整 CPU 回归已退出 0（72.28s），inline/helper × tracked/local
四变体各通过 4480 helper 样本、8192 eval、四次 init，含 ASan/UBSan；文档补充
前向/回向位及写回语义。后续 gate66 验证 helper+局部活动字节组合，不能归因为单项收益；
gate65 保留 helper-only 生成产物，gate64 原打包构建仍进行中。
详见 [NO0662](../../grhsim_opt/NO0662_grhsim_ir_cpu_local_activity_word_gate_20260907.md)。

进一步确认内存结构差异：IR memWrite/memWriteSeq 仍按整个数组暂存/发布，4116
生成调用涉及 832 个数组，最大 1 MiB；legacy 比较/写 addressed cell 并按 row 激活。
静态字节数不代表每周期拷贝量。需要先测动态贡献，再设计保留 NBA/多写口/fill 优先级
的 cell 粒度方案，本次不混入 gate65/gate66，也不改 DPI。
详见 [NO0663](../../grhsim_opt/NO0663_grhsim_ir_cpu_memory_structure_audit_20260907.md)。

gate66 安装、XS 生成/fresh roundtrip 退出 0（208.053s），IR/mapping 与 gate63
逐字节一致。相对 gate65 只变 5569 compute 文件、driver、header；静态激活写为
155414 局部/1701385 全局，不代表动态收益。HDLBits 001-162 全通过，独立 O3 会话
5934 进行中；gate64 原打包构建 95253 也未结束，不并行测速、不因观察超时重启。
详见 [NO0664](../../grhsim_opt/NO0664_grhsim_ir_cpu_gate66_generation_hdlbits_20260907.md)。

gate66 原 O3 会话 5934 已退出 0：6255 模型对象及 harness 链接通过，wall 23:27.59，
实际 executable 163201984 字节，SHA256 5e1c7db9a41bb09ae452b0427bd61b00ab71e5cb38bb3650ec080909ee2721d5。
gate63 指纹不变。gate64 仍构建中，先启动 gate66 10k 功能检查（会话 44439），明确
不将构建重叠下的 host time 用于性能比较；正式配对仍等待全部构建结束后串行执行。
详见 [NO0665](../../grhsim_opt/NO0665_grhsim_ir_cpu_gate66_full_o3_build_20260907.md)。

gate66 原 10k 功能会话 44439 已退出 0：458 指令，cycleCnt=9996、guest=10001，
十个有序采样及三项终态匹配 gate63，NEMU 无不一致，指纹未变。host 233638 ms 与
gate64 构建重叠，不能用于判断提速或回退。当前仅 gate64 原构建 95253 在运行，已到
task22、未报错；正式串行性能对比及打包运行结果仍待完成。
详见 [NO0666](../../grhsim_opt/NO0666_grhsim_ir_cpu_gate66_10k_functional_gate_20260907.md)。

用户最新要求先杀掉不可接受的 21h/56min 编译：gate64 原会话 Ctrl-C 后退出 130；
宿主机发现遗留 gate26 进程组 2925931，clang PID 2926826 已运行 77620s/99.9% CPU，
已整组 SIGTERM。随后宿主机编译进程查询及显式 PID 查询均为空，产物/源码未删除。
此前只核对已知会话，漏查宿主机遗留构建，NO0656 等“无并行构建”前提不成立；
879581/154286 ms 比值仅为观测，不能当作干净环境基准。功能验证仍有效。
本轮不再启动构建、仿真或测速；用户停止要求覆盖此前继续等待/自动测速安排。
详见 [NO0667](../../grhsim_opt/NO0667_grhsim_ir_cpu_stop_long_builds_20260907.md)。

停止后仅静态核查：packFunctions 的 max(maxOps,totalOps/targetCount) 会在默认
target=64 时把 XS 的 2048-op 阈值放大到 77832；生成 Makefile 没有单文件编译超时。
应区分函数数软目标和编译规模硬限制，并验证超时/取消的整进程组清理；本轮不选新数值、
不改实现、不启动构建/测试/仿真，宿主机复查仍无编译进程。
详见 [NO0668](../../grhsim_opt/NO0668_grhsim_ir_cpu_compile_limits_static_audit_20260907.md)。

用户重新授权修复三个 emit 结构问题并重测 CoreMark 50k。gate67 已实现 compute-only
state-read 别名、块内相同 fanout 的 changed 合并，以及保留写口顺序的 cell staging/
row-reader 激活；不改 DPI 或 packing。旧 CPU 回归 52.20s、新增快照/混合内存写回归
58.43s 通过，宽位分组后的最终回归进行中；尚无新性能结果。旧 gate26/gate64 不恢复。
详见 [NO0669](../../grhsim_opt/NO0669_grhsim_ir_cpu_emit_shape_repairs_20260907.md)。

gate67 最终 CPU 回归 58.52s、schedule 0.01s、HDLBits 162/162 通过。生成/roundtrip
87075ms，IR 与 gate63 逐字节一致。task if 数由 1515742 降到 640218，global activation
写由 1701385 降到 757628；源码字节略增，不能据此声称运行提速。新 O3 全量链接
16:13.07 通过，真实 executable 155763776 字节。宿主机 ps 确认无编译/仿真残留后，
已启动正式 gate67 50k 会话 28552；随后 legacy 同参串行运行，当前尚无完整性能结果。
详见 [NO0670](../../grhsim_opt/NO0670_grhsim_ir_cpu_gate67_build_and_50k_start_20260907.md)。

gate67/legacy 新串行 50k 均退出 0：IR 659545ms，legacy 119091ms，耗时比
5.538159895，吞吐为 legacy 的 18.0565%。50 个有序采样及 3 项终态完全一致，
instrCnt=73580、cycleCnt=49996、IPC=1.471718、guest=50001。三处结构修复已验证，
但性能仍未接近 legacy，legacy+5% 验收仍开放；不能用受旧并行编译影响的数据宣称提速幅度。
两路测量结束后补跑 IR/mapping 回归通过。按用户要求形成完整 CPU 后端检查点提交，
包含必要子仓库依赖、Makefile 路径和进展记录，不包含 ptmp/build、vrt/ 或无关草稿改动。
详见 [NO0671](../../grhsim_opt/NO0671_grhsim_ir_cpu_gate67_50k_serial_result_20260907.md)。

验证后已创建子仓库检查点：wolvrix `dda0ce3`（完整 CPU 后端及 emit 修复），
testcase/hdlbits `e9221bb`（IR backend 入口）。主仓库将同步记录两者版本与 NO0671；
本轮仅本地提交，不推送。
