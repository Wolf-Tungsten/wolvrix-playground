# Rob 独立模型存储模型对比：gsim vs GrhSIM IR（六阶段/gsim-shape emit 路线）

| 字段 | 值 |
|---|---|
| 日期 | 2026-10-07 |
| wolvrix commit | `6bcf731`（gsim-shape emit） |
| 被测产物 | `ptmp/xs-components-rob/gsim-model/`（`Rob.h` 39,386 行 + `Rob0..15.cpp`）与 `ptmp/xs-components-rob/grhsim-model/`（`grhsim_Rob.hpp` 5.8MB + 100+ TU），均为当日新生成 |
| 配套性能数据 | `pdocs/rob_standalone/rob-trace-replay-bench-20261007.md`（trace 口径 3.18×） |

> 注意：`ptmp/` 产物可能被清理；重建见 `testcase/xs-components/rob/README.md`。
> 两侧模型均被脚本剥离断言上报（语义条件保留），不影响本文的存储/调度结构结论。

## 结论

**类型系统层面已收敛一致，存储/更新结构仍不同构。**

## 已一致的部分

- 标量状态都是**具名成员 + 按位宽选最小原生类型**：`uint8_t/16/32/64`，>64 位均为 C23 `unsigned _BitInt(N)`；同一个 352 位 one-hot 指针两边都是 `_BitInt(384)`（gsim `Rob.h:3256`，grhsim `grhsim_Rob.hpp:7155`）。旧路线的"字节数组 + `cpu_at<T>` 访问器"形态已消失。
- 数组都是 **struct-of-arrays**：按 bundle 字段拆平行列（如 renameBuffer 的 `pdest`/`robIdx` 各自成列）。
- clock/reset 均为普通成员 + 变化检测驱动激活；supernode 内部临时量均为函数内局部变量。

## 仍不一致的部分

| 维度 | gsim | GrhSIM 新路线 |
|---|---|---|
| 寄存器双缓冲 | 每寄存器一个 `$NEXT` 成员，提交分散在 subStep 内逐成员 `reg = reg$NEXT`（`Rob0.cpp:65221`），数组按真实深度定长循环回拷（`Rob0.cpp:137737`） | 整个 `RegLatchStore`（1,819 成员）镜像两份（`regLatchStore`/`regLatchStoreNext`，`grhsim_Rob.hpp:7705`），`pPublish()` 一次 `memcpy` 整表回拷（`grhsim_Rob_tu0.cpp:12125`） |
| 1 位信号 | 每位占完整 `uint8_t`，无位打包 | 379 个 `packed_bits_*` 字位打包，读写走掩码合并/抽取（`grhsim_Rob.hpp:7703`、`grhsim_Rob_tu173.cpp:17752`） |
| 组合中间值 | 跨 supernode 的存类成员 + `$old$` 局部量保存旧值逐成员变化检测（`Rob0.cpp:165362/169010/170303`），supernode 内用块作用域局部量（全模型 ~46 万个） | 同一策略：跨 supernode 值物化为 `BoundaryValueStore` 槽位 + 逐槽变化检测（`cpu_phase_common.hpp:120` `sixPhaseBoundaryValues` 只收跨边界/被 Mem 相位采样的值），supernode 内用 `cpu_v*` 局部量（全模型 ~56 万个）；差异在**数量**（~96k 槽 vs ~28k 组合成员；75.2k 检测块 vs 26.1k `cond_`）与**常量物化**（1,592 个 `cnst_*` 槽 init 预载，gsim 内联立即数） |
| 内存更新 | `$NEXT` 数组双缓冲 + 定长循环整表提交 | 单缓冲 + pending-write 端口（`__w*__data/__enable` + `memEnableBits` 位图），`pMem` 阶段直接应用（`grhsim_Rob_tu173.cpp:18023`） |
| 活动标志 | `uint8_t activeFlags[800]` 字节数组，subStep 开头自检清零、按位分派；XOR 快照变化检测（`Rob0.cpp:65190`、`Rob0.cpp:65202`） | `std::array<uint64_t,93> dataActiveFlag` 位打包 + Next 双缓冲，无分支 `-(u64)chg & mask` 置位（`grhsim_Rob.hpp:104208`、`grhsim_Rob_tu4.cpp:4152`） |
| 数组深度 | 声明填充到 2 的幂（352→512，`reference/gsim/src/cppEmitter.cpp:745`） | `std::array<T,352>` 真实深度 |
| 数组拆分判据 | 动态索引字段保留数组，纯静态字段标量化为 352 个成员 | reg-to-mem 把 76 个高频字段变 `MemStore` 列，残余 1,064 个逐 entry 标量锁存 |
| 每周期结构 | `step()` = 16 个 subStep 一趟，提交与组合按激活图交织（`Rob15.cpp:69712`） | `eval()` = `pInput` + `{pEvent→pGeneral→pMem→pPublish}` 不动点迭代 + `pOutput`（`grhsim_Rob_tu0.cpp:12243`） |

## 与性能差距的对应

1. **边界值数量放大（~5×）**：两侧的跨 supernode 值都是"算 → 比 → 写 → 置活动位"同形模式，但 grhsim 的边界槽约 93k（gsim 组合成员约 19k）、逐值变化检测块 75.2k（gsim 26.1k），且检测位驱动当周期不动点迭代——插桩实测该迭代**深度 ≤2 轮**（见"激活 profile"节），代价是活跃超点每周期 firing ~2 次 + 每次 firing 的边界检测体量，gsim 只驱动 16 个 subStep 间的静态激活——指令数 5.64× 的主要来源之一。放大来源已归因：**reg-to-mem 变换 + Mem 相位采样规则**（写口槽）与 **General 合并 128 op 硬帽**（58k 布尔网），见下两节。
2. **整表 `memcpy` publish**：每 round 全量回拷 1,819 成员的结构体（gsim 只提交被激活成员），叠加 93 字活动位图双缓冲合并，与 L1 miss 13.2× 的恶化方向一致。
3. ~~位打包的反向交换~~ **已被 A/B 实验证伪**（2026-10-07，同机同 trace 背靠背，`--disable-pack-bit-registers` 对照臂）：见下节。

## 边界值数量归因（2026-10-07 补充）

问题：`BoundaryValueStore` 96,442 槽 vs gsim 全部类成员 36,400（其中组合跨 supernode 成员约 19k）。多出来的 ~60k 是什么？

两侧全量成员普查（`ptmp/xs-components-rob/attribute_boundary_gap.py`）：

| grhsim 槽桶 | 槽数 | gsim 对应物 | 归因 |
|---|---:|---|---|
| `__reg_to_mem_*` 写口 data/enable/addr | 16,330 | **0**（`$NEXT[]` 数组 + supernode 内局部 mux 链直写） | reg-to-mem 把列写接口静态解复用成 **352 口/列**（如 `uopNum__23__w0..w351__enable/data`），Mem 相位采样规则强制全部物化 |
| `eq_*` one-hot 译码 + `and_*`/`or_*` 匹配链 | 58k（and 38,925 / or 9,409 / eq 8,590 / logicAnd 729 / not 384） | 同一张网收在 supernode 局部量（gsim 全模型 ~46 万 locals） | `eq` = `readS_X == i`（i=0..351）指针译码，实测 **26 个不同指针源 × 352 个常量**（enq/deq/rab walkPtr/writeback 等）；`and` 操作数对 Top-3：`and&eq` 5,109、`readR&eq` 3,914、`and&readR` 3,184。网的终点是 Mem 相位写口 → 被逐值钉成边界槽 |
| `readM_*`（MemStore 列动态读结果） | 6,944 | 0（使用点内联 `arr[idx]`） | reg-to-mem 列读结果跨边界物化 |
| 位抽取（`slice_` 3,349 + `bitSelect_` 3,927 + `readS_` 1,189 + `sliceDynamic_` 117） | ~8.6k | 使用点内联位抽取 | 部分是 pack-bit-registers 拆位读 |
| `cnst_*` 常量槽 | 1,592 | 0（内联立即数） | init 预载 |
| `io_*` 端口 + clock/reset | 1,509 | 1,904 | 基本对应 |
| 其余（mux/sub/add/lt/gt/xor/reduceOr…） | ~2k | — | 正常组合逻辑 |

gsim 侧普查：36,400 成员 = 7,477 `reg$NEXT` + 770 数组（352/512 深逐 entry 状态）+ 1,902 io + 26,249 标量（含 ~7.5k 寄存器现值，组合跨 supernode 成员 ≈ 19k）。

**结论：放大主因是 reg-to-mem 变换与 `sixPhaseBoundaryValues` 的 Mem 相位采样规则**（`cpu_phase_common.hpp:136-138`：Mem 相位写口的所有 General 产出无条件成为边界值）。ROB 最核心的"352 项 × 76 列"次态网络，在 gsim 里是 supernode 内局部 mux 链 + `$NEXT[i]` 数组直写（成员开销为 0，例：`Rob7.cpp:98678` uopNum 写），在 grhsim 里变成 16.3k 写口槽。注意墙2 只直接钉住写口操作数本身；上游整张译码/匹配网（58k 布尔槽）的物化另有主因——General 相位内部 supernode 合并的 128 op 硬帽，见下节"CAM 匹配网的 gsim 对照"。

优化线索：M5d-6 已把 regLatch 类内存写移入 General supernode（其操作数回归普通跨 supernode 规则，`cpu_phase_common.hpp:116-119`）；reg-to-mem 列写若同样内并入 General 相位，可消掉这一整块边界物化。

证据链：`grhsim_Rob_tu7.cpp:7724`（readM 物化）、`grhsim_Rob_tu33.cpp:1896-1899`（`and = sliceDynamic & slice`）、eq 生产者形态（`readS_X & 0x1ff) == 350`）、`Rob7.cpp:98660-98690`（gsim 逐 entry 直写对照）。

**墙2（Mem 相位采样）槽的变化检测普查**（2026-10-07，`ptmp/xs-components-rob/census_wall2_slots.py`：解析全部 TU 的槽写入块，按是否置 `dataActiveFlag` 区分活变化检测）：

| 槽桶 | 总数 | 带活检测 | 无活检测 |
|---|---:|---:|---:|
| `mem_port:enable` | 6,337 | 352 | 5,985 |
| `mem_port:data` | 9,504 | 704 | 8,800 |
| `mem_port:addr` | 368 | 1 | 367 |
| `cnst_*` | 1,591 | 0 | 1,591 |
| 布尔网（and/eq/or/readM/slice/bitSelect 等） | ~62k | ~59k | ~3k |
| **全部槽** | **94,904** | **69,206** | **25,698** |

结论：墙2 写口槽 94% **无活变化检测**——enable 块里的 `cpu_chg` 比较是死代码（`grhsim_Rob_tu84.cpp:17006`，比较结果无人消费，-O3 删除），实际只有"写槽 + `memEnableBits` 位图 RMW"；data 槽是纯 store。变化检测被推迟到 pMem 的 **cell 级合并比较**（`grhsim_Rob_tu173.cpp:18023` 起：`cpu_cell != cpu_next` 才置 `dataActiveFlagNext`）。所以墙2 槽不承担逐槽检测成本，但仍付：store 本身 + 位图 RMW + pMem 位图门控应用 + 16.3k 槽的 `BoundaryValueStore` 缓存足迹。指令数 5.64× 的主战场是其余 **69,206 个带活检测的槽**（58k 布尔网为主）。

## 边界槽总量普查：96k 槽在哪里（2026-10-07）

ROB 生成 cpp 全量反查（`boundaryValueStore.X` 写/读点按函数归类；cpu_chg 自检行与 dump/init 调试路径不算消费）：

| 读者类别 | 槽数 | 占比 | 位宽构成 |
|---|---:|---:|---|
| 仅 General 超点间交叉（sn） | **76,128** | 77% | **69.0k 1-bit** + 6.2k 2-8b + 其余 <1k |
| 仅 Mem 相位采样 | 8,871 | 9.0% | 2-8b 4,633 + 33-64b 3,886（reg-to-mem enable/data，墙2 相关） |
| 混合读者 | 2,266 | 2.3% | — |
| **写了但无活消费者（死槽）** | **3,185** | 3.3% | 多为 reg-to-mem data（消费侧被优化掉）；仅 501 个带检测，其余纯 store |
| 从未被写（dump 引用已消值） | 2,162 | — | 良性残留，无运行时代价 |
| sink/输出相位（pOutput） | ~15 | ≈0 | 输出方向几乎不产生边界槽 |

检测开销分布（96,442 个有写点的槽）：**带逐值变化检测 74,705（77.5%）**；纯 store 无检测 18,552；死槽 3,185。

**全位宽同口径对照**（gsim 侧 = 成员总数 36,371 扣 $NEXT 7,578 与数组 741；gsim 寄存器与组合交叉混在同一成员区，故 gsim 数字为高估）：

| 位宽档 | gsim | grhsim（sn-only） | 比值 |
|---|---:|---:|---:|
| 1-bit | 19,699 | **68,964** | **grhsim 3.5×（全部差距在此）** |
| 2-8b | 6,216 | 6,158 | 1.0×（持平） |
| 9-16b | 1,143 | 270 | gsim 反而多 4× |
| 17-32b | 4 | 219 | grhsim 多（量小） |
| 33-64b | 1,088 | 517 | gsim 多 2× |

**结论：多出来的槽 100% 是 1-bit 布尔网断口**；宽数据通路跨界量两边持平甚至 gsim 更多。与布尔网算子普查（15,528 vs 58,059，3.7×）互证：gsim 的 per-entry 锥完整（断口只在锥顶），grhsim 的 128-op 窗口把每个 entry 锥拦腰切 2-3 刀，断口沿锥体密布，×352 entry ×26 口滚出 ~69k 个 1-bit 槽。gsim 也非零交叉（6,384 超点、~2 万 1-bit 断口），差距是 3.5 倍而非有无。sink 方向基本无槽。

## 1-bit 槽按名分类与 gsim 语义族对应（2026-10-07）

**命名链路（为什么默认看不到语义名）**：SV always 块内临时（`_fflagsCanWbSeq_T_1`）→ GRH ingest 做 SSA 前递，值只留 `_val_N` + file:line（`emit_flat_grh.json` 里 `{'sym':'_val_1017966','loc':{'line':630592}}`，无 SV 名）；`grh_to_grhsim.cpp:368` 把值名绑在 `keepOrigins` 上，ROB 流程传 `--no-keep-origins` → 值名给空串 → 发射器 `signalNameOf`（`cpu_layout.cpp:200`）回退到 `and_8438` 式算子名。**语义名可找回**：`--keep-origins` 重新生成后值名变回 `_val_N`，经 flat GRH 的 loc 反查 SV 行即得家族。产物：`ptmp/xs-components-rob/grhsim-model-named/`。

**grhsim 76,056 个 1-bit 边界槽按语义族**（slot→flat-GRH loc→SV 行 LHS 名归类）：

| 语义族 | 槽数 | 占比 | gsim 同族 | 倍数 |
|---|---:|---:|---:|---:|
| **DEBUG/PERF 信号**（debug_VecOtherPdest/debug_exuData/perfDebugInfo…） | **21,550** | **28.3%** | **~200** | **~100×** |
| enq 匹配/使能族（enqOH/robIdxMatchSeq/uopCanEnqSeq/instCanEnqSeq） | 11,483 | 15.1% | 11,146 | **1.0× 持平** |
| _GEN（firtool 共享临时，wb 匹配网主体） | 11,347 | 14.9% | 含在下行 | — |
| robEntries 字段写（per-entry 字段写入值） | 9,865 | 13.0% | $NEXT/局部 | — |
| exuWriteback 端口源（wbIdx/valid 等跨界源） | 9,360 | 12.3% | 同量级端口成员 | ~1× |
| wb 写回匹配族（_taken_T/fflagsCanWbSeq 等具名） | 987 | 1.3% | **40**（锥顶） | 25×+ |
| output / 其他 io / robBanks / 杂项 | ~3,500 | 4.6% | — | — |

**三个要点**：

1. **最大单一族是调试信号（28%）**：ROB 每 entry 拖大量 debug/perf 元数据（debug_pc/instr/pdest/perfDebugInfo 时间戳…，每 entry ~40 字段中 ~25 个是 debug/perf），其 per-entry 写使能谓词（1-bit）被裁断面物化。**gsim 并非不带 debug/perf**——FIRRTL 里 51,511 处 debug 引用全数进模型，状态数组（`debug_VecOtherPdest[512][8]`、`robEntries__DOT__debug_pc[512]` 等）照常更新，verify 逐位一致；差别只在物化：gsim 的字段写走"写回口超点内动态索引单点写"（`Rob5.cpp:69359`），使能条件零跨界；grhsim 沿 SV 的 per-entry 静态使能形式裁成 21.5k 个 1-bit 槽。若 bench 不需要 debug 可观测性，在 extract/firtool 层剥掉 debug 可直接砍掉 ~28% 的 1-bit 边界质量（对两侧公平减逻辑，但 grhsim 减得特别多——属于减负，不是修结构）。

   **reg-to-mem 增强调查（2026-10-08，部分修复）**：针对"每 entry 一写口"问题做了 DynArrayWrite 迷你复现（`testcase/xs-components/src/main/scala/cases/DynArrayWrite.scala`，E=32×L=8×P=2 的动态数组写，复刻 Rob.scala:1513-1521）逐层定位，写口合并失败是**三层叠加**：
   1. ~~`guard()` 多解码地址（entry eq + lane eq）直接判 ambiguous~~ → **已修**：候选按"行命中 + 真实解码基数"消歧（`reg_to_mem.cpp` guard()，配套把 decodedRows 的 4 顶帽放开到 65536）；reg-to-mem/split_phases/cpu_phases/select_state_stores 单测全过。
   2. **族校验 `row-dependent-guard`**（仍失败）：逐行守卫 key 不统一，差异来自 firtool 的常量特化——0 行用 `~(|x)`（reduceNor）其余用 eq、else-if 优先级取反进入 conflict 项且逐项常量不同。ROB 实测更糟：使能里 CSE 共享了 enq 族的 eq 结果，解码出的"地址"逐行是 `_enqOH_T_*` 等不同值。这意味着合并键需要语义级归一（等价性证明），不只是语法归一——工作量与风险都大，**本轮未做**。
   3. 评测口径注意：report 的 `status` 列在 prepare() 后被覆盖，失败原因要看新加的 `detail`（`write-parse:<reason>` 透传，本次顺带修的）。
   
   当前净效果：guard 修复让 DynArrayWrite 从 ambiguous-address 进到 row-dependent-guard（ parse 能解了，族合不上）；ROB merged 组数 21→21 无变化。要真正收割那 ~16k 写口槽，需要第 2 点的语义归一，或改在 ingest 前对 SV 做展开逆变换。**建议优先级重排**：先做"高变化率槽的无条件激活降级"（无图改动、风险低），再回头啃写口语义归一。

   **debug/perf 结构差异的根因（2026-10-08 钉死）**：同一笔 Chisel 动态数组写 `debug_VecOtherPdest(wb22.robIdx)(vdIdx) := wb22.pdest`（Rob.scala:1520）在两条输入管线形态不同——**FIRRTL（gsim 吃）保留动态聚合写原样**（`connect debug_VecOtherPdest[...动态索引...], payload`，Rob_resolved.fir:1402818），gsim 单数组节点单动态写、零译码；**firtool 展开的 SV（grhsim 吃）铺成 352×8 per-element 静态使能**（`else if (match22_i) debug_VecOtherPdest_0_0 <= ...`），grhsim reg-to-mem 聚成"每 entry 一写口"的 mem（**39 个 reg-to-mem 数组全是 352 写口**），每口 enable+data 物化为边界槽：**写口 staging 共 15,866 槽（enable 6,339 + data 9,516），其中 debug/perf 数组 13,383（84%）**。这与共享 eq 同源——grhsim 吃的是 firtool 完全展平的 SV，聚合写与 CSE 共享两种结构都被摧毁；修复方向是写口聚合（识别"352 个互斥使能+常量地址"逆变换回动态写）或 ingest 层保留数组写形态。
2. **enq 族两侧持平（11.5k vs 11.1k）**：enq 匹配是本质宽扇出（8 口 × 352 entry 的匹配结果要广播到各 entry 锥），两边都物化——证明 grhsim 并非处处差，差的是"本可局部的锥内值"。
3. **gsim 存锥顶、grhsim 存断面的量化证据**：整张 26×352 写回匹配网在 gsim 只剩 40 个具名存储值（`canWbSeq_*` 锥顶），同网在 grhsim 是 eq_* 8,590 + and_* 38,925 的主体。

**算子级对照**（统一普查，全位宽，两侧同规则）：

| op | gsim 跨界存储 | grhsim 边界槽 | 倍数/备注 |
|---|---:|---:|---|
| and | 7,860 | 38,925 | 5.0× |
| or | 4,261 | 9,409 | 2.2× |
| eq | 3,405 | 8,590 | 2.5×（gsim 的 3,405 ≈ enqOH 2,816 + commitCond 352；wb 族 eq 在 gsim 全局部） |
| mux | 1 | 1,531 | grhsim 独有量级 |
| slice | 0 | 8,582 | grhsim 独有（宽值切片入边界库） |
| memrd | 0 | 7,788 | grhsim 独有（mem 读结果槽） |
| memwr | 0 | 16,330 | grhsim 独有（墙2 reg-to-mem 写载荷 staging） |
| move/直拷 | 17,059 | 0 | gsim 独有（寄存器/$NEXT 类） |

## 激活 profile：不动点深度与 supernode 激活量（2026-10-07，插桩实测）

动机：此前文档多处称"grhsim 超点在当周期不动点迭代中被反复唤醒重算"——插桩验证该说法是否成立。

方法：emitter 自带 `WOLVRIX_GRHSIM_PERF` 编译开关（`PerfCounters`：evalCount/round1Count/round2Count/totalRoundCount/computeBatchExecCount/touchedStateShadowCount/touchedWriteCount，`cpu_phase_emit.cpp:3289`），`gen_rob_bench.py` 在 grhsim 臂末尾打印计数器（新增，perf 开关下生效）。对照臂：`ptmp/xs-components-rob/grhsim-model-perf/`（模型源同基线，仅 CXXFLAGS 加 `-DWOLVRIX_GRHSIM_PERF=1`）+ `bench-perf/`；verify 全过、checksum 与基线逐位相同。

Trace 口径（100,050 周期，最后一个 repeat 实例的计数）：

| 计数器 | 值 | 换算 |
|---|---:|---|
| evalCount | 200,100 | 2 eval/周期（`eval_grhsim_trace` 内 clock=0/1 各一次） |
| round1Count / round2Count | 100,099 / 100,001 | negedge eval 1 轮收敛；posedge eval 恰好 2 轮 |
| totalRoundCount | 300,101 | 恰 = 100,099×1 + 100,001×2 → **没有任何 eval 超过 2 轮** |
| computeBatchExecCount | 355,092,712 | supernode firing 总数 → 3,551 次/posedge eval（5,891 超点，即每轮 ~30% 活跃 × 2 轮） |
| touchedStateShadowCount | 7,208,836 | reg latch 实际变化 36 次/eval |
| touchedWriteCount | 6,411,773 | mem 写实际应用 32 次/eval |

随机激励口径（100k 向量，evalCount=400,020）：round1/round2 = 200,017/200,003，totalRoundCount=600,023 同样精确吻合"≤2 轮"；computeBatchExecCount=1,170,397,059 → 5,852 次/posedge eval（**几乎全体超点两轮各 firing 一次**，随机激励活跃度远高于 trace 的 30%）。

结论（修正此前的猜测性说法）：

1. **不动点深度 ≤2，无多轮振荡**。posedge eval 恒 2 轮：round 1 沿提交 + 组合涟漪（同轮内按超点拓扑序传播，派发即清 `dataActiveFlag` 位，同轮内不会二次激活——序数反转边只能等下一轮），round 2 收 pMem 应用结果与迟到边界后收敛。
2. **"反复唤醒重算"的数量上限就是每周期 2 次**（每轮一次），不是失控迭代。活跃超点（每轮 ~1,776 个 ≈ 30%）在 posedge eval 的两轮里各 firing 一次。
3. 成本结构应表述为：**firing 总量 = 活跃超点数 × 轮数（≤2）× 超点体量**，5.64× 指令差来自"边界槽多 3.7× 导致每次 firing 的检测/物化指令多 + 超点切得小导致 firing 次数多"，而非收敛轮数。

## CAM 匹配网的 gsim 对照（2026-10-07，统一口径重测）

问题：grhsim 58k 布尔网边界槽，gsim 有同一张网吗？对应部分多少边界？

口径（两侧完全相同）：每个赋值按 **RHS 顶层运算符**归类产出 op（grhsim 侧先剥 `&UINT64_C(0x1)` 位宽掩码；grhsim 边界槽直接用槽名前缀——即 IR 的产出 op 命名，与解析器在 17,434 个抽样块上互验，布尔类零分歧）。"边界" = gsim 类成员 / grhsim `BoundaryValueStore` 槽（两侧都是跨 supernode 物化值），唯一名计数。脚本：`ptmp/xs-components-rob/census_bool_net_unified.py`。

**1. gsim 有完全相同的网。** 例：26 个 exuWriteback 通道 × 352 项的 one-hot 译码，`Rob6.cpp:103-121`：`_canWbSeq_T_7776 = (io__DOT__exuWriteback__DOT__0__DOT__bits__DOT__robIdx__DOT__value == 0x144)`、`canWbSeq_0_324 = (io__DOT__exuWriteback__DOT__0__DOT__valid & _canWbSeq_T_7776)`——与 grhsim `eq_*`/`and_*` 槽同源。gsim 边界成员同样带 `$old$` 快照 + XOR 变化检测（`robIdxMatchSeq_2_71`：`Rob.h:12003`、`Rob6.cpp:99216/102039/105957`），与 grhsim `cpu_chg` 机制同构——**差异只在数量**。

**2. 统一口径普查**（布尔网 = eq/and/or/xor/not/logic\*）：

| 产出 op | gsim 边界 | gsim 局部 | gsim 边界率 | grhsim 边界槽 | grhsim 局部 | grhsim 边界率 |
|---|---:|---:|---:|---:|---:|---:|
| eq/neq | 3,405 | 30,620 | 10.0% | 8,590 | 23,524 | 26.7% |
| and | 7,860 | 128,420 | 5.8% | 38,925 | 176,496 | 18.1% |
| or | 4,261 | 278,748 | 1.5% | 9,409 | 302,488 | 3.0% |
| **布尔网小计** | **15,528** | 437,939 | **3.4%** | **58,059** | 538,182 | **9.7%** |

- **边界总量比 3.7×**（58,059 vs 15,528）；缺口 42.5k 中 and 行贡献 31k（73%）。
- 布尔网总值数 grhsim 多 31%（596k vs 453k）——GRH 是二叉 op、gsim 表达式树多扇入合一，属编码粒度差异，非逻辑差异。
- 每个 supernode 平均布尔边界输出：grhsim 58,059/5,889 = **9.9**；gsim 15,528/6,384 = **2.4**。
- gsim 边界成员族：eq 侧 `robIdxMatchSeq` 2,944 + `rab walkPtrOH` 352；and/or 侧 `_enqOH_T` 2,816、`commitCandidates_T` 2,816、`instCanEnqSeq` 2,570、`_fflagsRes_T` 1,408 等——这 15.5k 即"gsim 组合跨 supernode 成员 ≈19k"的主体。

**3. 为什么 grhsim 边界多 3.7×：128 op 硬帽削掉了 supernode 尺寸分布的尾部（修正：不是"平均更碎"）。** 证据：这些布尔槽是 General 相位**内部**的跨 supernode 值（如 `and_8438` 在 tu94 产出、被 tu131/tu152 等多个 General TU 消费），不跨相位；墙2 只钉住 16.3k 写口槽（且 94% 无活检测）。

层次对齐（关键，曾混淆）：gsim 是 supernode → node → **enode**（表达式树，enode 才是运算符），装箱上限 `MAX_NODES_PER_SUPER=7000` 卡的是 **node 数**、不管 node 内表达式树多大；grhsim 是 supernode → C1 node → op，**128 帽卡的是运算符数**（`cpu_partition.cpp:330/424`）。按运算符（emitted）口径实测 supernode 尺寸分布：

| ops/supernode（enode/GRH op 口径；gsim node 口径 mean 78 / max 7,001） | n | mean | p50 | p90 | p99 | max | 总 ops |
|---|---:|---:|---:|---:|---:|---:|---:|
| gsim | 6,384 | 159 | 48 | 196 | 1,506 | **21,270** | 1,013,382 |
| grhsim | 5,844 | 106 | 114 | 128 | 144 | 190 | 621,096 |

两侧**平均尺寸相当**，差异全在尾部：grhsim 的分布被 128 硬帽削顶（p90=128、p50=114——帽子几乎贴着每个超点），gsim 是长尾（最大 21,270 ops = fflags 写回合并族整族收在一个超点，Rob.scala:1066-1071，详见"孤立复现 II"节）。2 万 op 的密集锥在 grhsim 里必被切成 ~160 片，每片断口都物化 + 变化检测——这才是 58k vs 15.5k 布尔边界的成因。coarsen 阶段的帽则基本不绑（coarsen∞ 臂：簇数仅 −5.5%，合并模式被宽扇出结构卡死），裁切全部发生在 DP 装箱窗口。

128 帽的原始动机是控制当周期重算浪费，但插桩实测（见"激活 profile"节）不动点深度恒 ≤2 轮、活跃超点每周期 firing 恰 ~2 次——重算因子有界且小，128 帽换来的"重算节省"是否值得由 maxOps 放宽扫描的实测数据回答（见下节）。gsim 的 replicationOpt（仅复制单成员超点、锥 op×fanout<3 的小锥）与 grhsim 的 C2.5 clone-shared-boundaries（本轮只消 10,306 个边界）均为收尾清理，不是差距主力。

（修正记录：① 曾归因"六相位按相位切分、墙2 把匹配网钉成边界"——不成立，墙2 只解释 16.3k 写口槽；58k 布尔网边界由 General 内部 128 帽裁切造成。② 上一版普查两侧分类规则不一致（gsim 按 RHS 子串、grhsim 按槽名前缀），已统一重测：18,566/56,924（旧）→ 15,528/58,059（新）。③ 曾拿 gsim 的 7,000 node 上限直接对比 grhsim 的 128 op 上限——量纲不同（node vs 运算符），正确对比是上表的运算符级分布：均值相当、尾部被削。④ 曾断言 gsim 的 21,270-op 巨超点"≈整张 canWbSeq 网收在一个超点"——**错误**：canWbSeq 网实际散布在许多小超点里（如 `canWbSeq_0_324` 在 members=95 的超点），巨超点装的是**整族合并**（`super=1332981`/Rob7.cpp:109952 = 全部 352 entry 的 fflags 族 eq+and+or+fflagsRes 且零成员输出；`super=1333035` 等同尺寸超点 = `_commitCond_T` 等整族）；孤立案例中"整族合并"未复现（gsim 最大超点仅 357 enode），但 eq 0% vs 100% 的差异复现了——证明物化差异与巨超点无关。⑤ "整族合并未复现"的原因已查明并在 WbMergeArray 复现：CamMatch 的 Vec 寄存器全静态索引被 gsim splitArray 拆成标量，缺少数组单节点这个聚合枢纽；巨超点的真实形成路径是"数组 $NEXT 单节点唯一后继 + mergeOut1 整族吸收"，7,001 为族自然大小而非撞帽（详见"孤立复现 II"节）。）

## maxOps 放宽扫描与 coarsen 机制结论（2026-10-07）

**coarsen 现状**（`cpu_partition.cpp`）：C1 `formNodes`（:244）逆拓扑单 consumer 锥吸收（帽 128）→ C2 `coarsenGeneral`（:315）三模式 union-find 批量合并循环到不动点（mode 0 出度=1 / mode 1 入度=1 / mode 2 同前驱兄弟；mode 0/1 在 union-find 迭代下已是传递闭包）→ `segmentGeneral`（:385）拓扑序一维 DP 装箱（窗口 ≤128 op 硬帽，超大簇为原子 singleton 段不拆）。**注意最终 supernode 由 DP 窗决定，coarsen 之后仍会被再裁切。**

**扫描实测**（`ptmp/xs-components-rob/run_maxop_sweep.sh`，四臂均 resume 自同一 flat_grh checkpoint，verify 全过、checksum 逐位相同，gsim 同臂对照漂移 ±4%）：

| arm | nonsink supernodes | boundary_fields | boundary_value_targets | trace 比值 | random 比值 |
|---|---:|---:|---:|---:|---:|
| 基线 128 | 5,889 | 98,604 | 440,201 | 3.33× | ~3.25× |
| coarsen∞（仅 coarsen 帽 1e9） | 4,792 | 94,936 | 353,833 | 3.52× | 3.38× |
| m256 | 3,331 | 92,872 | 373,533 | 3.26× | 3.66× |
| m512 | 1,506 | 93,445（布尔网 58,057→53,758） | 311,308 | 3.30× | 3.40× |
| m1024 | 707 | 89,897 | 239,954 | 3.27× | 3.25× |

**三个结论**：

1. **coarsen 的帽从来不是约束**：coarsen∞ 臂簇数仅 −5.5%（113,744→107,480）。失效点在模式的结构前提——GRH 全图 CSE 造出大量高扇出共享值（C1 图 828,873 边/162,908 节点 ≈ 5.1 边/节点），出度=1 才可并的规则在 CAM 网这种复用密集区处处撞墙。gsim 的 mergeOut1 能吞 47 万超点，前提是它的图保留了单扇出链形态。
2. **一维 DP 装箱对二维稠密网的 distinct 边界无效**：supernodes 砍到 1/8、边界边 −45%（440k→240k），distinct 边界值只 −9%。值的消费跨度超过任何可行窗口，窗口内放不下全部消费者 → 该值必成边界；且 DP 复杂度 O(簇数×窗口) 使 ≥32k 窗口不可行。
3. **更大超点 ≠ 更快**：在 ≤2 轮 firing 的实测结构下，省下的边界检测被整超点重算抵消，四臂性能全部落在漂移带内（3.26×~3.52× vs 基线 3.33×）。

指向的杠杆曾判断为 **fanout 归一化**（把高扇出共享值按消费者复制后再 out1 吞并，即放大 C2.5 `clone-shared-boundaries`）——**该方向已被随后的 lossy-compare 克隆实验证伪**（eq 槽能消掉但性能反而退化，见"eq 克隆实验"节）：eq 槽的变化检测是有效的激活过滤，不是纯开销。

产物：`ptmp/xs-components-rob/{grhsim-model,bench}-{coarseninf,m256,m512,m1024}/`、`gen_log_*.txt`、`bench_{,trace_}*.log`、`maxop_sweep.log`。

## 孤立复现：CamMatchSynthLarge（2026-10-07）

动机：把"差异结构"从 ROB 整体里孤立出来单测。模块 `testcase/xs-components/src/main/scala/cases/CamMatchSynthLarge.scala`，忠实复刻 `Rob.scala:1024-1087` 的 per-entry 匹配网：26 个写回口 × 352 entry 的 one-hot 译码 + valid gating + Mux1H/OrR 聚合，**三个写回族（exuWBs/exception/fflags 风格）共享同一批 idx 源**（复现 SV 里观察到的跨族 eq CSE 共享），另加 8 口 enq 匹配族；消费方是 per-entry 寄存器写（uopNum/needFlush/fflags/realDestSize），保证网落在 P_general 而非被剥到 P_output。端口走 `tb/xs_component_bench.hpp` 的 in0..in5/ctrl 约定，输入扩展层仅 ~100 个 slice/xor。产物：`ptmp/xs-components/CamMatchSynthLarge/`（fir/sv/两侧模型/bench）。

**结构对比（同一份 SV，两侧各自生成）**：

| | gsim | grhsim |
|---|---|---|
| supernodes | 2,540 | 1,311 |
| ops/supernode（enode/GRH op 口径：生成 cpp 每超点的运算符实例数；gsim node 口径为 mean 64 / max 707） | mean 81，p90 192，**max 357** | mean 101，p90 122，**max 128（帽贴满）** |
| eq 边界 | **0**（31,328 全部局部） | **9,152（=26×352 全阵列 100% 物化）** |
| and 边界 | 3,168 / 52,448（6.0%） | 4,713 |
| or 边界 | 352 / 50,688（0.7%） | 3,241 |
| 布尔网边界合计 | **3,558（2.6%）** | **17,106** |
| 边界总值 | 7,304 成员 / 143k 值（5.1%） | 19,227 槽 / ~21k general nodes（91%） |
| 随机吞吐 | 49,680 vec/s | 33,060 vec/s（**1.50×**） |
| 静态指令数 | 259,061 | 731,442（2.8×） |

**机制定论**：gsim 收这张网**不需要巨超点**——它把"一个 entry 的完整匹配体"（26 eq + 3×26 and + 聚合 ≈ 250-350 ops）装进一个超点即可，eq 全部留在局部。grhsim 的 128 帽恰好比一个 entry 的匹配体小，每个 entry 被腰切成 2+ 片，三族共享的 eq 正好落在切口上 → eq 100% 物化。ROB 上 21,270-op 的巨超点不是成因，只是结果允许的尺寸。

性能含义：孤立案例差距 1.50×（ROB 整体 3.2×）——边界物化+检测机制本身的开销约占一半，ROB 剩余的差距在别处（16.3k 写口槽、publish memcpy、规模效应）。

旁证问题（未修）：`scripts/model_stats.py` 在本案例 emit 的 IR json 上找不到 PhaseSchedule（mappings 无 stage 15 项），`make stat` 最后一步失败；bench/模型生成均正常。疑似脚本与当前 emit json 布局脱节（ROB 流程不走该脚本故未暴露）。

**孤立案例 maxOp 扫描**（`ptmp/xs-components/run_cammatch_sweep.sh`，verify 全过、各臂 gsim 同测对照）：

| arm | nonsink supernodes | boundary_fields | grhsim vec/s | gsim vec/s（同臂） | 比值 |
|---|---:|---:|---:|---:|---:|
| 128（基线） | 1,311 | 19,227 | 33,060 | 49,680 | 1.50× |
| m256 | 663 | 18,489 | 33,884 | 50,217 | 1.48× |
| m512 | 309 | 18,243 | 31,236 | 49,928 | 1.60× |
| m1024 | 181 | 17,902（**eq 槽仍 9,152，100%**） | 33,273 | 50,908 | 1.53× |

**窗口放大到 1024（超点均值 ~730 op，已装得下两个 entry 的匹配体）eq 边界依然 100%**——证伪了"entry 体大于 128 被腰斩"的初步解释。实测真正的机制：entry 255 的 eq 产出于 sn_39、族 A/B 的 and 也在 sn_39（`sn_39__op_212731__c0/c3` 块间走 SnFrame），但**族 C 的 and 在 sn_129**——三族锥在拓扑序上按族聚集、同一 entry 的三族相距数千 op（一族 352 entry × ~50 op ≈ 17k op 的跨度），**任何小于族跨度的窗口都必然把同一 entry 的三族切开**，而共享的 eq 只要有一个消费者出窗就是边界。

**这就是一维 DP 装箱的结构性死穴**：合并顺序由拓扑序决定，拓扑序按族聚集，eq 的消费者分散在多个族段里 → 窗口放大收益为零。gsim 不受此限是因为 mergeOut1 是**图结构驱动**（按超点后继关系递归吞并，与拓扑序线性化无关）。要解只能：① 换图划分合并；② 或让 coarsen/排序按 entry 主序局部化重排（把同一 entry 的多族锥聚到相邻位置），使 DP 窗口能整段吃下。

**更深一层的不对称（2026-10-07 补钉）**：这张网在两侧图里的共享形态根本不同。Chisel 源码里 `wbIdx(p) === e.U` 被三个族各写一遍（CamMatchSynthLarge.scala:67/70/73）；**FIRRTL 里保持三份独立拷贝**（`eq(wbIdx_0, 0)` ×1056 = 3×352，无共享）；**firtool 发射 SV 时做了跨族 CSE**——一个 `_fflagsCanWbSeq_T_1` 同时被族 C and（:17507）、族 C mux（:17526）、族 A Mux1H（:47774）引用，族间相距 3 万行。而 **gsim 读 FIRRTL、grhsim 读 SV**（Makefile: `gsim` 依赖 `$(FIR)`，`grhsim` 依赖 `$(SV)`）——gsim 的图里每族 eq 本来就是 fanout-1 私拷贝（生成 cpp 里 `(_wbIdx_T_4 == 0x63)` 作为三个独立 node 分处三个 per-entry 超点，实测确认），**gsim 从未面对共享 eq**；grhsim 摄入的是 post-CSE 的 SV（且自身再做全图 CSE），共享 eq fanout=3 直接撞上一维装箱死穴。所以"eq 0% vs 100% 物化"的根源有一半在**输入管线的位置差**，不全是分区算法差——把共享 eq 按消费者复制回 fanout-1（fanout 归一化 / 放大 C2.5）正是在补齐这一半。

## 孤立复现 II：WbMergeArray —— 21,270-enode 巨超点的解剖与复现（2026-10-07）

### 21,270-enode 超点是什么逻辑

`super=1332981`（members=7,001，21,270 enode）= **fflags 写回合并族**，对应 `Rob.scala:1066-1071`：

```scala
val fflagsCanWbSeq = fflags_wb.map(wb => wb.valid && wb.bits.robIdx.value === i.U && wb.bits.wflags)
val fflagsRes = fflagsCanWbSeq.zip(fflags_wb).map { case (c, wb) => Mux(c, wb.bits.fflags, 0.U) }.fold(false.B)(_ | _)
when(isFirstEnq) { robEntries(i).fflags := 0.U } .elsewhen(fflagsRes.orR) { robEntries(i).fflags := robEntries(i).fflags | fflagsRes }
```

成员构成（每 entry × 3 个带 fflags 的写回口）：3 eq（`wb.robIdx==i`）+ 3 and(valid) + 3 and(wflags) + 3 mux + 2 or 树 + fflagsRes + 1 neq（`fflagsRes.orR`）+ 1 or（老值合并）+ 2 条 `$NEXT` 写（=0 / =合并值），全 352 entry 共 7,000 节点 + 1 个数组写节点 = 7,001。第二个 7,001 超点（`super=1333035`）= **commitCond 族**（`Rob.scala:980-987`：8 个 deqPtr × 352 entry 的指针匹配 + `robEntries.valid$NEXT` 更新）。另一个 2,001 成员的 `super=1332897` 是同形状的第二处 fflags 族（bank 读回路径，`Rob.scala:1132-1134`，16 行 × 动态 idx）。

### 形成机制（钉死）

1. **数组是单节点**：`robEntries.fflags[352]` 在 gsim 图里是**一个**数组节点（它被 `deqPtrVec(i).value` 动态索引读出，`Rob.scala:1247`，`splitArray` 拆不掉动态索引），其 `$NEXT` 也是**一个节点**（node=171446，704 条写语句 = 352 entry × 2 臂，全部 entry 共用同一 node id，实测确认）。
2. **mergeOut1 沿唯一后继吸收**：每 entry 锥内每个节点 `next.size()==1`，锥的终点都汇聚到这**一个** `$NEXT` 节点 → 逆拓扑一趟把 352 条锥全吸进 `$NEXT` 所在超点。**7,001 是自然大小、不是撞 7,000 帽**（352 个 entry 全部在内，无截断）。
3. **mergeWhenNodes 无关**：`--when-size 100000000` 禁用后巨超点原样存在（coarsen 后仍有两个 members=7001 超点）。
4. **InitPartition 保留**：DP（SuperNodeMaxSize=35）视 coarsen 簇为原子不拆，巨超点直接进入 codegen。

### 孤立复现（受控实验）

模块 `testcase/xs-components/src/main/scala/cases/WbMergeArray.scala`（复刻 fflags 族，P=3 写回口 × E=352 entry × Q=2 enq 口），两个 top 只差**一行动态读**：

| | `WbMergeArrayDyn`（`out0 ^= fflagsReg(dynIdx % 352)`） | `WbMergeArrayStatic`（纯静态索引） |
|---|---|---|
| gsim 数组形态 | `uint8_t fflagsReg[512]` 单节点 | 拆成 `fflagsReg_0..351` 标量 |
| gsim 最大超点 | **members=5,654（6,354 语句）**，含全部 352 entry 的 fflags 族 + 单节点 `fflagsReg$NEXT`（node=66，704 条写语句） | **352 个 17 成员超点**（每 entry 一条链），无巨超点 |
| grhsim 侧 | fflags 数组=mem（352 写口），supernodes=116，boundary_value_targets 10,313→4,150 | — |
| bench（100k vec，min of 3） | gsim 581k vs grhsim 726k vec/s → **grhsim 快 1.25×** | gsim 741k vs grhsim 683k vec/s → **gsim 快 1.08×** |

两臂 verify 均过、checksum 一致（`ptmp/xs-components/WbMergeArray{Dyn,Static}/`）。CamMatchSynthLarge 当初没复现巨超点的原因也由此查明：它的 `RegInit(VecInit(...))` 全静态索引，被 gsim `splitArray` 拆成 352 个标量寄存器，没有聚合枢纽。

### 结论修正

- **巨超点对 gsim 自己是负优化**：同一模块，巨超点臂比拆分臂慢 ~22%（581k vs 741k）——整个 5,654 成员的超点只有一个 activeFlag，任一写回口信号变化就全量重算 352 entry 的匹配网；grhsim 的细粒度超点+边界变化检测在这种结构上反而占优（1.25×）。
- **ROB 整体 3.2× 差距不由 fflags/commitCond 巨超点贡献**（gsim 在这里反而吃亏）；主战场仍是 CamMatch 已孤立复现的共享-eq 型 canWbSeq 网（eq 0% vs 100% 物化）。旧记录④"巨超点装的是整族合并"方向正确，但"来源是 mergeOut1/mergeIn1 撞帽"不准确——真实路径是"数组单节点唯一后继 + mergeOut1 整族吸收，7,001 为自然大小"。

## eq 克隆实验：`--clone-shared-compute-lossy-compare`（2026-10-07，**阴性结果**）

**改动**（wolvrix 子模块 `cpu_clone_shared.cpp`，未 commit，默认关）：`varyingSource` 白名单加 `core.compute.eq/ne`（一操作数为常量、两态 ≤64bit），父操作数判据从 `users>1` 代理收紧为精确判据——父已是边界值（`boundary[parent]`）或为环境可读源（input.read/state.read/无生产者）。python 侧 `--clone-shared-compute-lossy-compare` 透传。既有单测（split_phases/cpu_phases）全过。

**CamMatchSynthLarge（密随机激励）**：

| | 基线 | lossy 臂 |
|---|---:|---:|
| clone 计数器 | candidates=0 | candidates=**9,152**（恰好全 eq 阵列）、cloned=24,287、eliminated=5,983 |
| eq 边界槽（生成代码实测） | 9,152 | **0** |
| boundary fields | 19,228 | 10,076（−47.6%） |
| grhsim 吞吐 | 33,829 vec/s | 31,055 vec/s（**−8%**；同臂 gsim 漂移 +4%，真实退化 ~12%） |

**ROB（trace + 随机）**：candidates=20,479、cloned=30,488、eliminated=16,648、boundary_fields 98,604→90,524（−8.2%）；trace 比值 3.33×→3.20×（grhsim +4%，漂移带边缘），随机 ~持平（−2%，噪声内）。两激励 checksum 均与 gsim 一致。

**结论**：机制上完全可行——eq 边界 100% 消掉了；但**性能上是阴性结果**。eq 槽的变化检测不是白吃饭：它是激活过滤器（`wbIdx==e` 在密随机下 99.6% 时间为 0，槽位检测替下游挡住了 wbIdx 每次翻转的重算）。克隆后族超点的激活挂到 wbIdx（密随机下 ~100%/周期）而非 eq（~0.4%/周期）， firing 率翻倍 → 省 9,152 组槽开销换不来激活翻倍的重算。ROB trace（稀疏激励）下过滤价值小，所以微赚 4%。

**这修正了前文的方向判断**：eq 物化不是可收割的浪费，而是负载均衡的一部分。gsim 在密随机 CAM 网上更快不是因为"eq 不物化所以省了槽"，而是它根本没有逐值检测机制（只有超点级 activeFlags）——逐值检测只有在**低变化率**的值上才有正收益。真正可收割的浪费在**高变化率的边界槽**（检测永不命中、纯开销），而不是 eq 这种低变化率的。fanout 归一化/克隆路线对本问题不成立，后续不应再投入。

产物：`ptmp/xs-components/run_lossy_ab.sh`、`ptmp/xs-components/CamMatchSynthLarge/grhsim-lossy/`、`ptmp/xs-components-rob/{grhsim-model,bench}-lossy/`、`gen_lossy.log`、`bench_{,trace_}lossy.log`。

## mem 写入激活 A/B：`--mem-write-activate on-write`（2026-10-07）

实验：pMem 的 cell 级精确检测改为 **write-occurs 激活**（gsim 语义）——无条件写 cell，读者激活按 enable-word run 并集一次性置位。实现：`cpu.st.emit-cpp` 新选项 `--mem-write-activate <on-change|on-write>`（默认 on-change；`cpu_phase_emit.cpp` `writeCell`/`memChunkFn`），Python 侧 `wolvrix_xs_grhsim_ir.py --mem-write-activate` 透传，复现 `make -f rob.mk rob-grhsim-model ROB_GRHSIM_EXTRA_FLAGS="--mem-write-activate on-write"`（配 `ROB_GRHSIM_MODEL_DIR`/`ROB_BENCH_DIR` override 建对照臂）。

收敛性前提：本模型全部 mem 写都是**事件门控**（pMem 块外层 `eventActStore` 守卫，pEvent 每轮清空重检，沿只在第 1 轮出现 → 写只在第 1 轮应用），write-occurs 不会破坏不动点收敛；event-free 写在 emitter 里强制回退 on-change（本模型 0 处回退标记）。生成代码静态对比：pMem cell 比较 9,608 → 0，pMem 内激活置位 115,592 → 60,615（run 级并集），新增无条件 memStore 直写 9,600 处。

结果（3 组测量：首轮 + 2 轮交错 A/B；每轮两臂 gsim 同步重跑控漂移；verify 全过、checksum 逐位相同）：

| 口径 | 基线 on-change | on-write | Δ |
|---|---:|---:|---:|
| trace grhsim c/s（3 组） | 3,500 / 3,369 / 3,584 | 3,632 / 3,583 / 3,578 | 均值 +3.3%，单组 −0.2%~+6.4% |
| 随机 grhsim vec/s（3 组） | 2,842 / 2,796 / 2,817 | 2,762 / 2,757 / 2,764 | **一致 −1.4%~−2.8%** |

**结论：基本无收益，方向分裂**——trace +0~3%（噪声边缘，R2 基线自身漂到 3,584 说明 R1 的 +6.4% 是基线慢样本），随机稳定小亏 ~2%。解读：随机激励下几乎所有写口每拍都真改 cell（比较本就便宜且分支可预测），on-write 只多付了读者过度激活；trace 稀疏激励下省一点比较但量级微小。**pMem 写路径不是差距瓶颈**——这进一步把 5.64× 指令差距锁定在 General 相位边界网（69k 活检测槽 + 不动点多轮重算），mem 写路径的 cell 检测语义维持现状即可。

产物：`ptmp/xs-components-rob/grhsim-model-onwrite/`（对照臂模型）、`bench-onwrite/`、`bench_onwrite.log`、`bench_trace_onwrite.log`、`ab_onwrite_interleaved.log`、`bench_baseline_20261007b.log`、`bench_trace_baseline_20261007b.log`、`gen_onwrite.log`。

## pack-bit-registers A/B 对照（2026-10-07）

机制：`wolvrix/lib/grhsim/pass/pack_bit_registers.cpp`（流水线 A5，默认开）把共享 enable/mask/event 沿的 1 位二态寄存器按 ≤64 lane 打包成 `packed_bits_*` 字，整字单次 regWrite，读侧 `sliceStatic` 抽位。Rob 实测 379 字 / 3,779 位（358×u8 + 1×u16 + 7×u32 + 13×u64）。

结果（100,050 周期 trace / 100k 随机向量，各 3 轮取 min，两臂 gsim 同步重跑控漂移）：

| 口径 | 打包 ON（默认） | 打包 OFF | 差值 |
|---|---:|---:|---:|
| trace grhsim 吞吐 | 3,612 c/s（27,699 ms） | 3,479 c/s（28,756 ms） | **关 −3.8%** |
| trace 比值 vs gsim | 3.18× | 3.46×（gsim 同轮 12,054 c/s） | — |
| 随机 grhsim 吞吐 | 2,812 vec/s（35,556 ms） | 2,700 vec/s（37,030 ms） | **关 −4.1%** |
| 随机 比值 vs gsim | 3.25× | 3.37×（gsim 同轮 9,099 vec/s，gsim 侧 −0.4% 基本持平） | — |

漂移参照（同日第三臂，恢复 packed 模型后重测 trace）：gsim 11,333 c/s、grhsim 3,342 c/s、比值 3.39×——**会话间机器漂移 ±5%**，与 A/B 效应同量级；但两个激励口径方向一致（关 packing 都更慢），随机臂 gsim 对照几乎零漂移，结论方向可信。

两臂 verify 全过、checksum 逐位相同（trace `0xd27a5e546e6474cc`）。

结论：**打包在 Rob 上是 ~+4% 的净收益，不是回归源**。收益来自 commit 摊薄（整字 RMW + 双比较 + 置位 ≈8-9 条指令覆盖最多 64 信号，非打包 bool 寄存器同形却只覆盖 1 个）；文档预警的"唤醒并集"伪活动在抽查字上未出现（30 位字的读者收敛于同一 supernode）。

产物：`ptmp/xs-components-rob/grhsim-model-nopack/`（对照臂模型）、`bench_nopack.log`、`bench_trace_nopack.log`、`ab_nopack_20261007.log`。复现：`make -f rob.mk rob-grhsim-model ROB_GRHSIM_EXTRA_FLAGS=--disable-pack-bit-registers`（rob.mk 已加 `ROB_GRHSIM_EXTRA_FLAGS` 透传变量）。

## reg-to-mem 写口语义归一（2026-10-08，本轮主线）

**目标**：把 firtool 展开后的 per-entry 静态使能写恢复成数组粒度的动态写口，消掉"352 写口/列"的 P_mem staging。本节是从"21 组合并"到"63 组合并"的完整攻关记录。

### 失败形态分类（全部来自 dump 实测，非猜测）

对 352 行家族逐族 dump 失败点的 guard/data 表达式树（`WOLVRIX_REG2MEM_DEBUG=2`，`reg_to_mem.cpp` 内建 `dumpTree`/`dumpBranch`/`verdict` 打印）后，ROB 的写口合并 blocker 分为：

| 形态 | 成因 | 例 |
|---|---|---|
| row-0 decode 消失 | firtool 把 `eq(ptr,0)` 特化为 `not(reduceOr(ptr))`，`equality()` 不认识 `core.compute.not` | debug_pc/dispatchTime 的 row 0 |
| 对角线双 decode | cell(entry=0,lane=0) 的 else-if 内层同时含 entry 轴与 lane 轴的 `==0`，旧 conflict 转换遇二义回退为普通 term | DynArrayWrite 的 tab |
| 1-bit 布尔 set/clear 树 | canonicalize 把 `mux(d,0,mux(e,1,self))` 折成 `and(not(d), or(e, self))`，decode 与 self 读埋进 data | validArr / robEntries_valid |
| mux 包装的 or-merge | data = `mux(globalEn, orTree, self)`，or-merge 被外层 mux 包住 | perfDebugInfo 时间戳族 |
| or-树 data 的 hold 叶 | `or(mux..., and(self, not(R)))` 或裸 `or(self, parts)`（RMW） | dispatchTime / fflags |
| per-row 表达式树 | guard term / data 是逐行克隆树，仅 decode 叶常量随行变 | fflags 的 `not(valid_i)`、wb 命中链 |
| row-0 与 351 行分裂 | row 0 单独特化 → 352 行读组与 351 行写组互相抢 ownership | debug_pc 等 |
| 中途 fill | 清零写在 else-if 链中间（非最低优先级 fallback） | lqIdx 的 `7'h0` 写 |

### 落地机制（wolvrix/lib/grhsim/pass/reg_to_mem.cpp）

1. `equality()` 新增 `not(reduceOr(x)) → (x, 0)` 识别（row-0 decode 恢复），`core.compute.not`（w=1）同等处理。
2. **conflict 多 decode 按轴消歧**：内层多个 decode 命中 row 时取 decodedRowCount 最大者（entry 轴 > lane 轴），其余降为 conflict term。
3. **bool set/clear 还原**（`boolSetClearBranches`）：识别 `and(not(d_i)…, or(e_j…, self/and(self,W)))` 为 [clear(d_i)→0（高优）, set(e_j)→1, orClear(W)→0] + hold；mux 分支 data 里的同类树也展开（条件与外层 mux 条件合取）；外层 fallback 非 self 时，fill 用**被展开分支原条件的取反**精确门控（否则树的 hold 格会漏进 fill）。
4. **or-树 data 分解**（orSplit）：`data = or_p(mux(cond_p, d_p, 0))` 拆成 per-port 子分支；coverage 校验要求外层条件某个合取项的 disjunction 恰等于 part 条件集（防 part-less 行被静默清零），其余合取项作为 globalTerms 并入每个 part；`and(replicate(reduceOr(X)), X) ≡ X` 恒等折叠（`foldReplicateGuard`）拆掉 bitwise 包装；1-bit 下 `and(cond, dataBit)` 也是 part 形态。
5. **分支条件 or-拆分**：guard 无地址但某 term 是 per-port 命中析取时，拆成每叶一个子分支（各带 decode）。
6. **行相对语义键（skey/remat）**：`skeyValue` 递归生成结构键——decode 叶 `eq(A,row)→REL(A)`、自身行读→SELF、同模式他字段行读→SIB(pattern)、其余递归；全行签名一致即成族。`rematValue` 用第一行的树重建：REL 叶→`eq(A, dynAddr)`，SELF→`memRead(ownTable, dynAddr)`，SIB→`memRead(sibTable, dynAddr)`。SIB 依赖在 prepare() 里做 fixpoint deselect（兄弟族未选中/不对齐则降级）。
7. **ownership 仲裁两阶段**：先让所有组跑 planWrites，可写合并组先于只读组认领行（352 行只读组不再饿死 351 行写组）。
8. **fill 位置化发射**：fill 不进优先级图（消伪环）；排他 fill 置最前（兼容 row-constant-fill 语义），重叠 fill 插回向量槽位；`emitWrites` 按 g.order 位置发射，fill 处 flush 当前序列发 memFill / 逐行静态三元组。
9. **selfBase RMW**：or-树含裸 self 叶 → 数据融合时 `memRead(ownTable, dynAddr) | parts`（P_general 读旧值，P_mem 提交，多口碰撞由既有 collision fusion 累积）。
10. `compute()` 创建的 op 回填 `defs`（修复 parse 期新建值在 dumpTree/skey 里变 no-def 的问题）。

### 关键正确性教训

- **selfBase 必须进 emitWrites**：只记录不使用会把 `fflags := fflags | res` 错成 `fflags := res`——trace 验证稀疏激励测不出，**随机激励 100k 向量 verify 才抓到**（fflags 1864/2048 错）。教训：本类改动必须随机+trace 双臂 verify。
- **orSplit 不查 conflict 会把 else-if 优先级冲突（mode 9 形态）错误 or-merge**；orSplit 的 part 必须 guard 过且 conflict 为空（lqIdx 因此被推到非 orMerge 优先级路径，是对的行为修正）。
- **per-row fallback fill 不能进 memFill**（enable 是 per-row 条件）——只能逐行静态三元组展开。

### 结果（trace 100,050 周期 ×3 + 随机 100k ×3，双臂含 gsim 对照）

| 状态 | merged 组 | boundary_fields | grhsim trace vec/s | 比值 vs gsim |
|---|---:|---:|---:|---:|
| 本轮前（2026-10-07 基线） | 21 | 82,485 | ~3,450 | ~3.25× |
| conflict+orSplit+仲裁（36 组） | 36 | — | 3,663 | 3.10× |
| +skey/remat+bool+fill（48 组） | 48 | 80,253 | 4,291 | 2.68× |
| +and-part+条件拆分（64 组） | 64 | 64,374 | 4,997 | 2.28× |
| +selfBase RMW 修复（63 组，当前） | 63 | 62,213 | 5,129 | **2.33×** |

随机臂与 trace 臂 verify 全过（含 fflags 修复后）。最终口径（r6 模型，三臂取 min）：trace grhsim 5,129 vec/s vs gsim 11,960（2.33×）；随机 grhsim 3,848 vec/s vs gsim 8,919（2.32×）。grhsim 侧吞吐 trace 3,450→5,129（+49%）、随机 2,812→3,848（+37%）。

当前边界构成（r6，62,213 槽 vs 基线 82,485）：bool 匹配网 36.4k（原 ~58k）、readM 读结果 9.2k、位抽取 5.4k、reg_to_mem 写口 5.1k（原 16.3k，**-69%**）、cnst 1.5k、io 1.5k、其余 3.0k。

### 剩余未合并家族（≥64 行）与原因

| 家族 | 原因 | 可否救 |
|---|---|---|
| robEntries_valid | flush 是 firtool 逐行特化的**环绕区间检查**（`begin<=i<end` wrap），逐行结构发散，非 decode 叶差异 | 难（需区间写/memAssign 语义） |
| robEntries_uopNum | data=`sub(self, wbCnt)` 宽值 RMW 且 guard 无 decode（广播式逐行更新） | 需 memUpdate 语义，未见收益 |
| mmio / lsTopdown_*_valid / dt_isMMIO/isNCIO/isPerfCnt | 每行无条件计算赋值（memAssign 形态：enable 全局、data 逐行），merge 只是把 352 个标量写换个形式 | 收益可疑，未做 |
| debug_exuData | firtool 逐行特化端口映射（不同行用不同输入端口做地址） | 难 |
| vtypeBuffer 4 个 64 行字段 | row-dependent-data（小组） | 可做，优先级低 |

### P_output 活动门控（2026-10-08，继 reg-to-mem 之后最大的单笔收益）

**实测定位**：reg-to-mem 落地后 `perf record` 显示热点移到 **pOutput ~44%**（pGeneral 已不热）。决定性对照实验：把生成模型的 `pOutput()` 掏空（只建帧不跑 chunk）后 grhsim 冲到 9,798 vec/s——**vs gsim 仅差 1.18×**——证明计算侧已被 reg-to-mem 压到接近对齐，剩余差距几乎全是 pOutput 的无条件重算。

**探针实测活动率**（生成模型 pOutput 末尾加 OutputFrame 逐字段 diff 计数）：ROB trace 下 **~60% 周期输出完全无变化**（dirty_cycles≈40%），pOutput 白跑——这就是整体门控的收益空间。

**机制**（`cpu_phase_emit.cpp`）：新增成员 `cpu_anyOutChange_`（输出门控脏标志），在所有"输出锥读到的值真实变化"的发射点置位——**发射期按 outputOps 的操作数集合（outputReadStates_/Values_/Inputs_）条件发射，非输出相关的写零运行时开销**。`pOutput()` 变为：读标志→复位→标志为真才跑 chunk 扫描；staged latchWrite 提交始终执行。守卫：输出相位含 system.task/dpi.call 或有 staged latchWrite 时回退无条件（`outputGate_`）；$urandom 源在采样点自维持置标志。

**踩坑**：(1) 第一版把"任何状态变化"都置位——trace 下每周期都有变化 → 门控从不跳 + 纯标志开销 → 反慢 9%；改成"输出锥读到才置位"才对。(2) on-write burst 路径走 collectReaders 绕过 activateReaders，漏标志 → mem_onwrite 单测抓到。(3) 门体读刚被复位的标志（`cpu_anyChange_` 而非保存的 `_run`）→ 全错——typo 级 bug，verify 首轮即抓。

**结果**（r8 模型，三臂取 min，verify 双臂全过）：

| 口径 | r6（无门控） | r8（门控） | Δ |
|---|---:|---:|---:|
| trace grhsim vec/s | 5,129 | **6,245** | **+22%** |
| trace 比值 vs gsim | 2.33× | **1.84×** | — |
| 随机 grhsim vec/s | 3,848 | 3,711 | −3.6%（噪声边缘，同臂 gsim 漂 +8.5%） |

累计：trace 3.18× → **1.84×**，随机 3.25× → 2.61×。

### 剩余差距在哪（当前 1.84×，perf record 实测）

**reg-to-mem 压缩写口后，热点相位从 General 转移到了 pOutput。** 对 r6 模型 `perf record`（grhsim 单臂 trace 100,050 周期）：pOutput 各 chunk 合计 ~44%（pOutput_c52..c79 各 1.4-3.2%），pMem ~12%，pGeneral/pInput/pPublish 合计 <5%。gsim 对照无独立输出相位——其输出锥织在活动驱动的 subStep 网里（subStep0-13 均匀分布）。

**当前最终状态（r8 模型）**：trace grhsim 6,245 vec/s vs gsim 11,503 = **1.84×**；随机 3,711 vs 9,668 = 2.61×。累计 trace 3.18×→1.84×（+81% 吞吐）、随机 3.25×→2.61×（+32%）。热点已均衡（pOutput 34.7% / pMem 5.8% / pGeneral 3.7%），安全增量高原。

**机制差异**：grhsim 的 `pOutput()` 每周期串行跑 ~100 个 chunk（`grhsim_Rob_tu0.cpp:12022`），每个 chunk 从 `OutputFrame cpu_f{}`（栈上 4,258 词临时帧）读出中间值、算出输出写回。gsim 的输出锥只是 subStep 网的普通节点，输入没变就不重算。**整体门控已落地（见上节，trace +22%）**；~~剩余空间是活动周期内的 per-chunk 门控~~ **per-chunk 门控已实测否决**（2026-10-08，逐 chunk 脏率探针 `grhsim-model-r8-pf`）：73 个输出 chunk 的逐周期脏率 ~35%（中位 95 字段/chunk），即 per-chunk 门控比整体门控仅多省 ~5%——整体门控已拿走全闲周期的大头，per-chunk 只多收活动周期内的部分跳过，不值 OutputFrame 持久化 + 逐 chunk 掩码的复杂度。

### 剩余差距在哪（写口视角，已被上条取代的主分析）

（保留 perf 计数器数据作参照。）

perf 插桩（`-DWOLVRIX_GRHSIM_PERF=1`，trace 10 万周期）：`computeBatchExecCount=2.19 亿`（≈2,196 次 supernode 执行/周期），`touchedWriteCount=642 万`，不动点深度仍 ≤2 轮（round1+round2 各一次/周期）。写口 staging 压缩后，**主战场回到 General 相位的布尔网边界槽**（boundary_fields 仍有 64k，gsim 对应约 19-28k）——即上一轮已定位的"CAM 匹配网 + 128-op 合并帽"问题，与 reg-to-mem 正交。

产物：`ptmp/xs-components-rob/grhsim-model-r2..r6/`、`bench_r*.log`、`r2m_fast.tsv`（报告）、`gen_fast.log`（含失败点 dump）。复现：`make -f rob.mk rob-grhsim-model ROB_GRHSIM_EXTRA_FLAGS="--reg-to-mem-report <tsv>"`。

## 补充事实（备查）

- gsim 状态区由 `_var_start`/`_var_end` 夹住，`init()` 末尾一次 memset 清零（`Rob0.cpp:36577`）；`activateAll()` 为 `memset(activeFlags, 0xff, …)`（`Rob0.cpp:36580`）。
- gsim 复位同时写 reg 与 `$NEXT` 并 `activateAll()`（`Rob0.cpp:51350` 起）。
- grhsim 每周期 = `pInput` 一次 + 不动点迭代（上限 10 万轮）+ `pOutput`；时钟沿提交批由 `eventActStore` 门控且仅首轮执行，后续轮只传播组合涟漪。
- grhsim 运行时头里存在字节式 active-flag 助手（`grhsim_or_active_u16/u32/u64` 等，`grhsim_Rob_runtime.hpp:2146-2215`），但本模型 0 处引用。
