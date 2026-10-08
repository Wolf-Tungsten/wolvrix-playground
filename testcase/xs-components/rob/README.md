# 实际 XiangShan ROB：gsim / GrhSIM IR 微观结构对比

目标实例：`cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rob`。独立顶层为 `Rob`，包含全部子模块。

## 提取与导出

`Rob.fir` 为 SimTop.fir 的依赖闭包，10 个 FIRRTL 模块；`rtl/` 为 12 个生成 SV 模块及原有 assert.v DPI 声明。模块正文按字节复制，来源、偏移及 SHA256 见 manifest.json。

FIRRTL 去掉了全设计 annotation，电路名改为 Rob；gsim 实际输入 `ptmp/xs-components-rob/Rob_resolved.fir` 只将 Rob 顶层抽象 Reset 解析为 UInt<1>，与 SV 同步复位一致。未修改寄存器数据逻辑。

```bash
make -C testcase/xs-components rob-ir
make -C testcase/xs-components rob-compare
```

原始导出与分析文件均在 `ptmp/xs-components-rob/`：

- `gsim/Rob_0InferAllWidth.json`：gsim 推导位宽后、优化前。
- `gsim/Rob_PreCoarsen.json`：gsim 全部语义优化后、分图前，含 assignTree。
- `grhsim/post_lower.json`：独立 GrhSIM IR lower 后。
- `grhsim/pre_partition.json`：GrhSIM 语义优化后、第二轮 CPU mapping 前。
- `grhsim/final.json`：最终 IR；与 roundtrip.json 逐字节一致。

GrhSIM 使用当前 CPU 管线，开启 row-constant-fill、OR-write-merge、migrate-boundary-ops、demonitor-redundant。整机动态 profile 的 ID 不适用于独立模型，因此未使用两个依赖 profile 的调度优化；这两个优化不改寄存器与计算语义。

## 原先 1,537 个未配对项

逐项使用 FIRRTL 寄存器的 bundle/vector 类型恢复路径；只在类型声明给出的合法索引范围内重排，保留原始位宽检查。

| 对应形式 | 原未配对个数 |
|---|---:|
| 字段/数组索引顺序不同的标量寄存器 | 1,447 |
| gsim 拆成多个 bit chunk，连续完整覆盖原寄存器 | 1 |
| gsim 保留数组节点，可定位到具体数组元素 | 89 |

具体例子：`robEntries_351_needFlush` ↔ `robEntries__DOT__needFlush_351`。四个 352 行字段（commitType、needFlush、realDestSize、traceBlockInPipe.itype）共 1,408 个；这部分是匹配器的名称顺序盲点。`robDeqGroup_0_debug_pc` 对应 gsim 的 `robDeqGroup__DOT__debug_pc` 数组元素 0。`robBanksRaddrThisLine[43:0]` 对应 44 个 1 位 chunk。

原整机逐项证据：`analysis/original_1537_reclassified.tsv`；按字段计数：`analysis/original_1537_families.tsv`。这些是来源对应关系，未作逐周期等价证明。

## 独立模型的结构

独立端口未施加整机常量，且保留子模块，因此下列计数不等同于整机中 ROB 本层的 1,596 个 declared state。gsim REG_SRC 的 width 是元素位宽；带 dimension 的数组须乘元素个数。

| 指标 | gsim PreCoarsen | GrhSIM post-lower | GrhSIM final |
|---|---:|---:|---:|
| 节点 / ops | 501,876 nodes | 1,000,950 ops | 680,201 ops |
| REG_SRC / 非事件 logic states | 7,583 | 28,607 | 2,125 |
| REG_SRC 数组 / array states | 105 | 14 | 90 |
| 事件簿记 states | 无对应单独节点 | 35,919 | 23,563 |

REG_SRC 与 GrhSIM logic/array 的拆分策略不同，不能将节点数直接视作存储量或运行代价。gsim 数组 REG_SRC 计入上一行，GrhSIM array 则不计入 logic states。

| 运算类别 | gsim RHS enodes | GrhSIM post-lower ops | GrhSIM final ops |
|---|---:|---:|---:|
| aggregate_concat | 11,311 | 23,776 | 14,389 |
| arithmetic | 12,846 | 12,423 | 7,360 |
| bitwise_logic | 227,856 | 574,256 | 464,220 |
| compare | 35,135 | 44,082 | 31,554 |
| memory | 80 | 1,096 | 26,531 |
| mux_control | 215,608 | 254,259 | 81,911 |
| slice_index | 204,934 | 7,710 | 36,241 |

gsim RHS enodes 只统计每棵赋值树 root 可达节点，排除序列化 lvalue；GrhSIM 按唯一 op 计数。两种表示的共享粒度仍不同，表格描述静态形态，不是执行次数。

## 配对寄存器的更新锥

依据完整 FIRRTL 路径及一致位宽，独立模型严格对应 1,615 对标量寄存器。保留数组的对应项、位宽不同项和 bit chunk 不混入一对一标量更新锥。

更新锥穿过组合别名，在 state/input/memory read 截止。计算节点数排除常量和读取叶。主表的 GrhSIM 更新锥合并 regWrite 的 updateCond、nextValue、mask 三个操作数的反向锥；gsim 取 REG_DST 的全部 RHS 树。两侧均不计时钟/事件检测；TSV 还单列 GrhSIM nextValue 锥，便于区分数据选择与独立写条件。

| 指标 | gsim | GrhSIM |
|---|---:|---:|
| 每对计算节点 median | 113.00 | 121.00 |
| 每对计算节点 p90 | 146.00 | 163.00 |
| 每对计算节点 mean | 157.98 | 170.50 |

| 寄存器样例 | gsim 计算节点 | GrhSIM 计算节点 |
|---|---:|---:|
| `io_rabCommits_REG_info_0_ldest` | 2138 | 2115 |
| `robEntries_0_commitType` | 89 | 111 |
| `robEntries_0_needFlush` | 146 | 171 |
| `robEntries_0_realDestSize` | 113 | 121 |
| `robEntries_0_traceBlockInPipe_itype` | 104 | 132 |

完整逐对计数及 op-kind 分布在 `analysis/paired_update_cones.tsv`。五个样例的解码操作、操作数、state 引用与 gsim 表达树在 `analysis/cone_*.json`；截断表达树在 `analysis/sample_update_trees.json`。

### 具体形态差异

1. **写条件与数据选择分离**：`commitType[0]` 的 gsim 根是带条件的 OP_WHEN，数据为 8 路 `(enqOH_i ? commitType_i : 0)` 的 OR。GrhSIM nextValue 根直接是 OR，写条件在 regWrite.updateCond；全更新锥将其加回统计。

2. **有序条件赋值与掩码合并**：`needFlush[0]` 在 gsim 中是两棵 OP_WHEN 组成的有序赋值序列；GrhSIM 把数据优先级写成单个 bitSelect 的 mask/true/false 计算，再由 regWrite 写回。bitSelect 的三个操作数分别是掩码、选中位的新值、未选中位的值。

3. **条件赋值折叠**：`traceBlockInPipe.itype[0]` 的 gsim 两棵条件树分别写入 enq 数据和常量 5；GrhSIM 用 mux 选择 OR 数据网络或常量 5，再用独立写条件控制更新。

4. **标量数组与恢复后的存储**：`io_rabCommits_REG_info_0_ldest` 两侧都保留了 352 路候选数据选择网络（各 705 mux、703 OR）；GrhSIM 的表数据来自 352 个 memRead，gsim 使用寄存器数组索引叶。该样例的主要差异在叶的存储表示和切片方式，主体选择网络并未消失。

结构签名只用于追踪相同表示；内存读保留为两侧独立叶，且本轮未规范化所有输入 bundle/vector 顺序，因此签名相交比例是保守的表示指标，不是等价率。

静态形态结果不能直接推导整机性能；运行时基准见下节。

## 运行时基准

对独立 `Rob` 顶层做随机激励逐周期仿真，两侧模型先逐周期比对全部配对输出（verify），再分别计时（bench）。testbench 由 `scripts/gen_rob_bench.py` 依据两个生成模型的头文件自动配对端口生成（配对输入 1,501 个、配对输出 4,258 个；仅存在于 gsim 侧的内部暴露信号不驱动、不比对）。每向量 gsim 执行一次 `step()`，GrhSIM 执行低相、高相各一次 `eval()`，两者都构成一个完整时钟周期，采样点暴露相同的 (上周期状态, 本周期输入) 组合结果。

断言处理：随机非法激励下 difftest 断言几乎每周期触发，上报路径的格式化与 I/O（gsim `gAssert` fprintf；GrhSIM `std::string` 构造 + `fwrite`）会主导实测周期耗时，而合法激励的参考口径（整机 CoreMark）中断言从不触发、开销为零。因此 `scripts/strip_rob_asserts.py` 在两侧生成模型中等价剥离断言**上报**（gsim 改写 `gAssert` 宏；GrhSIM 删除 2,162 个纯上报语句块），保留全部断言**条件**求值。剥离后 `[ASSERT] xs_assert_v2_stub_count=0`。

结果（AMD Ryzen 9 7950X3D，clang++ 22.1.2 `-O3`，两侧均未 PGO；100,000 向量 × 3 轮取 min；2026-10-07 于 wolvrix `6bcf731` 六阶段/gsim-shape emit 路线重测）：

| 模型 | min 耗时 | 吞吐 | 每周期耗时 |
|---|---:|---:|---:|
| gsim（`--supernode-max-size=15`，与整机一致） | 10,952 ms | 9,131 cycles/s | 109.5 µs |
| GrhSIM IR（当前 CPU 管线） | 35,556 ms | 2,812 cycles/s | 355.6 µs |

**GrhSIM IR 每周期耗时约为 gsim 的 3.25×。** 每轮两模型 checksum 一致，verify 2,048 向量全部配对输出逐周期一致。

排除比对项（均不影响功能输出结论）：

- 17 个 `*_bore` difftest WiringControl 观测口：自 2026-10 起在端口配对/打包阶段即不纳入（verify 报告 `excluded_bore_ports=0`）；其 payload 此前已验证一致，帧内包装计数器/时间戳的计数约定在两个生成模型间不同。
- `io_storeDebugInfo_{0,1}_pc`：352 项 `debug_pc` 数组经 9 位 `robidx.value` 的动态索引读；随机激励下索引频繁越界（≥352），越界读在 FIRRTL 中属未定义行为——gsim 得 0，GrhSIM 得别名项。索引在界内的向量逐周期一致。

注意：随机激励下两模型执行的是相同但非法的状态轨迹，吞吐不代表现实工作负载；整机 CoreMark 口径的差距（含 gsim PGO）见 `pdocs/perf-optimization/20261007-011318-gsim-vs-grhsim-ir-100k-coremark.md`，不可与本基准直接比较。**真实激励口径见下节"Trace 回放基准"。**

复现与产物：

```bash
make -C testcase/xs-components rob-bench   # 链：rob-gsim-model rob-grhsim-model + TB 生成/剥离
```

中间产物在 `ptmp/xs-components-rob/`：`gsim-model/`、`grhsim-model/`（生成模型）、`bench/rob_bench.cpp`（生成的 testbench）、`port_pairing.tsv`（端口配对与排除清单）、`bench.log`（verify/bench 输出）。gsim 顶层数组端口的标量化访问器由 `scripts/fix_gsim_array_ports.py` 在生成后原地改写为逐元素指针形式，否则生成代码无法编译。

## Trace 回放基准（整机真实激励）

随机激励的法律性无法保证，因此另建一条真实激励口径：在整机 XiangShan 的 Verilator ref emu 上用 `bind Rob RobTap u_rob_tap (.*)` 绑定观测模块（`scripts/gen_rob_tap.py` 生成），从 cycle 0（含 reset 段）逐周期 `$fwrite` Rob 全部 1,507 个输入与 4,275 个输出，经 FIFO 流式打包为二进制（`scripts/pack_rob_trace.py`；6 个截断宽输入与 17 个 `*_bore` 观测口不进入记录，打包后每周期 `flags + 1,500 + 4,258` 个 u64 字），再由 `rob_bench --trace` mmap 回放：每周期把 trace 的 reset/输入同时驱动到两个独立模型，按既有约定求值采样。每个计时轮都从零初始化的新建模型开始，trace 前 52 个周期为 reset，轨迹与真实芯片逐周期对齐。

**Verify（100,000 周期，三方比对）**：GrhSIM 与真实芯片**全部 100k 周期逐位一致**；gsim 仅在 `io_diffCommits_info` 行 ≥353 上发散——那是 RAB difftest 提交前瞻窗（520 行 = diffPtr 起、352 项循环缓冲，行 ≥353 需要指针和回绕**两次**），gsim 模型对第二次回绕的处理与真实芯片不同（失配频率随行号线性增长，正好是 `ptr ≥ 704-N` 区间；真实 trace 中 `row 352 == row 0`、`row 353 == row 1` 证实芯片正确双回绕）。这些是 difftest 观测口、非 ROB 功能输出，按 bore 同例排除（966 口/966 字）后三方比对全过。

**结果**（100,050 周期 CoreMark `coremark-2-iteration`，每轮全新模型，3 轮取 min；2026-10-07 于 wolvrix `6bcf731` 六阶段/gsim-shape emit 路线重测，两模型 checksum 一致 `0xd27a5e546e6474cc`，与 2026-09-29 旧路线记录逐位相同）：

| 口径 | gsim | GrhSIM IR | 比值 |
|---|---:|---:|---:|
| **trace 全程（100k，稳态为主）** | 8,703 ms / 11,496 c/s / 87.0 µs | 27,699 ms / 3,612 c/s / 276.9 µs | **3.18×** |
| 随机满活动（对照） | 9,131 c/s / 109.5 µs | 2,812 c/s / 355.6 µs | 3.25× |

对照 2026-09-29 旧 per-task eval 路线（trace 2.25×、随机 2.53×）：gsim 侧两次测量一致（11,252 → 11,496 c/s，指令数逐条吻合），**差距扩大全部来自 GrhSIM 新路线自身**（4,993 → 3,612 c/s，−28%）。boot/steady 分段本次未重测（分相探针源码原存于 `ptmp/`、随清理丢失）。

**微观数据（perf stat，trace 全程，每仿真周期）**：

| 指标 | gsim | GrhSIM IR | 比值 |
|---|---:|---:|---:|
| 指令数 | 443k | 2,497k | 5.64× |
| IPC | 0.89 | 1.57 | — |
| 分支数 / 误码率 | 21.0k / 43.0% | 30.5k / 18.6% | 1.45× |
| L1 loads / miss | 263k / 4.2k | 1,471k / 54.9k | 5.6× / 13.2× |
| CPU 周期 | 499k | 1,590k | 3.19× |

旧路线（2026-09-29）同口径：指令 443k vs 1,661k（3.75×）、IPC 0.92/1.49、误码率 43.0%/11.9%、CPU 周期比 2.32×。新路线 GrhSIM 指令量 +50%、L1 miss 3.1×，分支数 −75%（branchless publish 生效）但未能抵消；gsim 的 IPC 依旧被高误码率拖住，把 5.64× 指令差压缩成 3.2× 时间差。

**工程发现（已修）**：gsim 生成模型的 `init()` 在未定义 `RANDOMIZE_INIT` 时不初始化任何数据成员（参考 emu 依赖"reset + X 无关"语义），堆残余使同一进程内重复构造的模型行为不确定。回放要求 Verilator 式零初始化，故 testbench 以"清零内存 + placement new"构造 gsim 模型（`make_gsim_zeroed`），此后每轮轨迹与 checksum 完全收敛。

复现：

```bash
make -C testcase/xs-components -f rob.mk rob-trace-emu-build   # 整机 Verilator emu + RobTap bind
make -C testcase/xs-components -f rob.mk rob-trace-run ROB_TRACE_CYCLES=100000
make -C testcase/xs-components -f rob.mk rob-bench-trace ROB_BENCH_VERIFY=100000 ROB_BENCH_REPEAT=3
```

产物在 `ptmp/xs-components-rob/trace/`：`rob_tap.sv`/`tap_ports.json`（tap 与端口清单）、`layout.json`（记录布局）、`verilator-ref-emu/`（整机构建）、`rob_trace.bin`（4.6GB 打包 trace）、`pack.log`/`emu_run.log`、`perf_{gsim,grhsim}_trace_20261007.txt`（perf 原始计数）。difftest 的参数解析器拒绝未知 `+plusarg`，因此 tap 固定写 emu 工作目录下的 `rob_trace.txt`（该路径即 FIFO）。本次重测数据记录见 `pdocs/rob_standalone/rob-trace-replay-bench-20261007.md`。

## 微观性能分析（2026-10-07，六阶段路线口径）

测量手段：`perf stat`（trace 全程，进程含 warmup+1 计时轮共 200,100 仿真周期；计数器 83% 多路复用，比值口径不受影响）。原始数据：`ptmp/xs-components-rob/trace/perf_{gsim,grhsim}_trace_20261007.txt`。旧 per-task eval 路线的分相/热点分析随旧路线作废；分相探针源码随 ptmp 清理丢失，boot/steady 分段本次未重测。

结构结论：

1. **指令口径差距 5.64× 是主因**（旧路线 3.75×）：六阶段路线 GrhSIM 单周期指令量 +50%；CPU 周期比（3.19×）与墙钟比（3.18×）精确吻合。
2. **IPC 对冲结构不变**：gsim 分支误码率 43.0%（mux 选择难预测）压 IPC 至 0.89；GrhSIM 误码率 18.6%、IPC 1.57。约 1.8× 的 IPC 差把 5.64× 指令差压缩成 3.2× 时间差。
3. **访存是新瓶颈线索**：GrhSIM L1 miss 从旧路线 17.8k/周期涨到 54.9k/周期（对 gsim 13.2×），涨幅远超指令量；状态/store 布局的访存局部性待定位。
4. branchless publish 等新形态使 GrhSIM 分支数较旧路线 −75%（120.2k → 30.5k/周期），但被指令与访存增长淹没。

### 公平性附注

- TB 驱动开销不对称（旧路线实测 gsim `set_` 访问器 + 位宽掩码约 8 µs/周期，GrhSIM 直接成员写约 1 µs/周期），剔除驱动后纯模型墙钟比更高。
- 两侧均未 PGO；整机 CoreMark 口径见 `pdocs/perf-optimization/20261007-011318-gsim-vs-grhsim-ir-100k-coremark.md`。
