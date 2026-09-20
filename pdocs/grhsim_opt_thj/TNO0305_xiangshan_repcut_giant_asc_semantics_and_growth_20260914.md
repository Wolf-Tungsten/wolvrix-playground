# TNO0305: XiangShan RepCut giant ASC semantics and growth

日期：2026-09-14

状态：`READ-ONLY STRUCTURAL DIAGNOSIS; NO ASC SPLIT OR NEW RUNTIME CLAIM`。

## 1. 结论与范围

承接 [TNO0264](./TNO0264_xiangshan_repcut_part3_imbalance_root_cause_20260901.md)
与 [TNO0266](./TNO0266_xiangshan_repcut_closure_weight_k32_static_ab_20260901.md)，
本轮解释最大 ASC 的功能和形成原因。复用冻结 snapshot、原始 GRH、emitted RTL 及 Scala，
没有修改生产代码、重新运行分区或启动性能测试。

最大集合仍是 `ASC 4`，当前 closure-aware assignment 中独占 `part_8`；旧分法 owner 为
`part_3`。它不是一个巨大的乘除法模块，也不是一条有几十万级深度的路径，而是许多 sink
及其上游组合锥在 memory 共置规则下形成的跨模块集合。

功能主要围绕缓存缺失/一致性处理、回填、访存队列、地址翻译和总线事务控制，同时带入
分支预测、ROB difftest 元数据和性能/断言逻辑。RTL 提供复杂依赖，当前 memory-symbol
粒度的传递合并把这些依赖升级为“必须在同一分区”的约束；逐 bit memory write 展开进一步
放大 GRH 操作数量。此约束形成于求解器之前，不是 Mt-KaHyPar 临时装箱产生的大块。

## 2. 冻结证据与计数口径

输入：`build/xs/wolf/wolf_emit/xs_wolf.json`，SHA-256
`82a29e6e2f715c18ffd61ab0106ed5abb6d0fbb6843eea58d8782eb3d30994ba`。

assignment SHA-256：
`ffefbb1d1373cb30290e6725479d339b87e637f3db32132dcbe416fd2c52d589`。

主要 snapshot：
`build/repcut_nk32_opt_20260907/stage4_analysis/frozen-control-v1/control/snapshot/`。
完整重建身份见 [TNO0287](./TNO0287_xiangshan_repcut_nk32_full_control_reproduction_20260907.md)。

| 指标 | ASC 4 |
| --- | ---: |
| full closure 静态 weight | 1,115,421 |
| exclusive weight | 710,271（63.68%） |
| shared incident weight | 405,150（36.32%） |
| 32 分区 nominal unique target | 389,087 |
| full closure / nominal target | 2.867x |
| 第二大 ASC full closure | 175,540；最大值为其 6.354x |
| 涉及 piece | 35,360 |
| 回映到输入 JSON 的原始 operation | 491,444 |
| RegisterWritePort | 21,361 |
| MemoryWritePort | 3,529，涉及 429 个 memory symbol |
| LatchWritePort | 2 |
| DpicCall / SystemTask | 986 / 971 |

membership 恢复方法：用 `piece_asc_offsets.u64` 与 `piece_asc_ids.u32` 选择含 ASC 4 的
piece，再通过 `node_to_piece.u32`、`node_operation_ids.u32` 回映原始 GRH 的 operation。
JSON operation 按加载顺序创建，不能把 `_op_N` symbol 后缀误当内部 OperationId。

phase-B 日志另记 `comb_ops=464601 sinks=26852`，见
`build/repcut_closure_runtime_20260902/logs/build/closure-aware/generate.stderr:358`。
此处 sink 包含 output value，effect result 可同时具有 sink/遍历节点角色；本轮没有将
这些计数逐项对账，因此不能直接把两个数字相加并等同“回映输入 JSON 的实际 operation 数”。
重建后的 `part_8` 则有 608,762 个 graph op，包含 storage/boundary 等额外结构，也不是同一口径。

weight 是静态成本模型，不是时间、指令数或 memory 字节数。shared incident 表示还被其他
ASC 引用的逻辑，不能据此断言该 ASC 内存在重复计算。其 63.68% exclusive weight 也说明
问题不是单纯把公共逻辑重复计数出来的假象。

## 3. 这个集合主要在做什么

按 operation 的原始 RTL 定义文件聚合，部分最大来源如下。同型模块的多个实例会累加；
这不是独占模块 runtime 占比。

| RTL 来源 | 原始 op | 功能解释 |
| --- | ---: | --- |
| MSHR_64.sv | 49,944 | 缓存事务/缺失处理、等待响应及一致性状态控制 |
| MSHR.sv | 17,452 | 另一类缓存事务处理实例 |
| Sbuffer.sv | 19,799 | store buffer：暂存、合并并向缓存发送 store |
| MissEntry.sv | 16,197 | cache miss 请求及回填状态 |
| SQData8Module.sv | 10,800 | store queue 数据存储与选择 |
| TLBFA_1.sv / TLBFA_3.sv | 9,748 / 7,417 | 全相联地址翻译条目查找与选择 |
| RequestBuffer.sv | 8,865 | 请求缓冲及选择 |
| LoadQueueReplay.sv | 8,614 | 暂不能完成的 load 的重放控制 |
| L2TLB.sv | 8,079 | 二级地址翻译与缺失处理 |
| LogPerfEndpoint.sv | 20,572 | 性能计数/观测端点 |
| BusPerfMonitor_2.sv | 13,608 | 总线性能观测 |
| buffer_7x514.sv | 9,256 | L3 回填数据缓冲的细粒度展开 |

从 memory 写目标和 emitted SV 可以进一步识别：外围 AXI/TileLink FIFO、ITTAGE 间接跳转
预测表、ROB 的 `dt_eliminatedMove/dt_isRVC/dt_pcTransType/dt_isXSTrap`、D-cache tag array、
PTW cache，以及 L2/L3 缓冲与目录。ROB 源码明确标注这些 `dt_*` 存储只服务 difftest，见
[`Rob.scala`](../../testcase/xiangshan/src/main/scala/xiangshan/backend/rob/Rob.scala) 的 1536 行附近。

操作类型也支持“广泛控制/选择”而非“少数大算术”的判断：And 109,615、Assign 58,924、
Or 53,644、Mux 49,412、SliceStatic 33,504、Concat 30,496、Eq 27,045、Not 22,507；
Mul 仅 44、Div 仅 1。这仍不是各类型的动态耗时分解。

## 4. 膨胀机制一：memory 依赖被升级为传递共置

实现位于 [`repcut.cpp`](../../wolvrix/lib/transform/repcut.cpp)：

- 320–330：常量、RegisterRead、LatchRead 是回溯截断点，MemoryRead 不是。
- 1700–1742、1784：从 sink 的所有输入追溯 memory symbol，包括数据、地址、条件等依赖。
- 2103–2128：同一状态的写口先合并。
- 2147–2178：读到 memory M 的 sink 与 M 的全部写 sink 做并查集合并。
- 2312–2325：每个最终连通分量变成一个不可拆 ASC。
- 5444–5447、5620：当前明确禁止 MemoryRead 结果跨分区，发现即报错。

例如，A 依赖 M1，B 同时依赖 M1/M2，C 依赖 M2，则 A/B/C 和两块 memory 的写口最终
会属于同一 ASC，即使 A 与 C 没有直接组合数据依赖。规则按整个 memory symbol 而非地址行、
端口、条件互斥关系判断；不同独立 symbol 的 bank 仍能被共同消费者再次粘合。

### 4.1 实际实例：AXI4Deinterleaver pending_count

ASC 4 中的 `cpu$l_soc$socMisc$axi4deint$pending_count` 记录一个事务 ID 已完整接收、
尚未全部送出的 burst 数；更新公式为 `count + inc - dec`。

[`Deinterleaver.scala`](../../testcase/xiangshan/rocket-chip/src/main/scala/amba/axi4/Deinterleaver.scala)
64–68 行为每个使用中的 ID 创建返回数据 FIFO，89–98 行更新 count，113–116 行动态选择
`qs(deq_id)` 的输出。

```text
64 个返回 FIFO 的 memory read ── 动态选择 last ── dec ─┐
上一级返回缓冲的 memory read ── incoming last ── inc ─┼─ pending_count 写入
                                                    └─ 当前规则将关联 memory 写口共置
```

实际 RTL `build/xs/rtl/rtl/AXI4Deinterleaver.sv:2164` 汇集 64 个 `last`，2229 行动态选择，
622 行用于 `pending_dec`，2431 行提交 count。原 GRH 中对应 write op 在 6409420 行，
内部 OperationId 为 19862，已核验在 ASC 4。

有限范围反向追踪已确认至少 65 个 memory read 来源：64 个该模块 FIFO 加 1 个上游
`axi4buf_2$nodeIn_r_deq_q`。对应 65 个 memory 写端点均在 ASC 4。由于追踪只加载前
60,001 个原始 operation，且一个上游 value 定义在范围外，65 是已证实的下界，非完整上限。
这个例子证明了真实的合并桥，但尚不是整个 429-memory 组件的完整合并树。

还需区分“图中可达依赖”和“条件成立时真正有效的依赖”。该模块中
`deq_OH = 1 << deq_id`，对第 i 个 count，减计数条件为：

```text
dec_i = (deq_id == i) && fire && last[deq_id]
```

在二态布尔语义下它等价于 `(deq_id == i) && fire && last[i]`。因此这个单独 count 的
减计数数据依赖本可只涉及 FIFO i；当前 operand 可达性遍历不利用这种选择条件相关性，
会把 64 路都收进来。这是明确的保守建模放大示例，不代表一个周期需要读取全部 FIFO。
此推导没有作为四态语义变换实现或测试；`locked/deq_id` 等其他 sink 仍可能连接全部
FIFO，所以即使精化这一 sink 的依赖，也不能直接推断整个组件就会拆成 64 个分区。

### 4.2 同步 SRAM 的 RTL 形态也影响边界

例如 `build/xs/rtl/rtl/array_128x76.sv:70`、`array_4096x137.sv:69` 保存读地址寄存器，
输出仍是 `Memory[registered_address]` 的组合读（分别 254、103 行）。硬件意义上的同步
SRAM，不一定在当前 IR 中表现为“读数据寄存器”截断点；MemoryRead 仍被上述规则遍历和合并。

## 5. 膨胀机制二：宽写操作逐 bit 展开

每个 L3 slice 的 `refillBuffer$buffer_ext$Memory` 是一个 `7×514` 的存储，
却有 514 个 MemoryWritePort；四个 slice 共 2,056 个，占 ASC 4 的 memory write op
约 58.3%。这不是 2,056 块独立 memory。

[`RefillBuffer.scala`](../../testcase/xiangshan/huancun/src/main/scala/huancun/RefillBuffer.scala)
24–27 行说明：让外层回填数据直接 bypass 到内层缓存，减少经过 SRAM 的延迟。
34 行创建按 beat 组织的 Mem，44 行读 beat，68 行写 beat。

`build/xs/rtl/rtl/RefillBuffer.sv:279` 实例化 `buffer_7x514`，287–288 行写数据和 mask
事实上只有两个 257-bit beat 组；`buffer_7x514.sv:74` 起却展开为 514 条逐 bit 条件写，
产生大量 mask、slice、拼接和 write 端点。它是明确的表示粒度放大，但本轮未测其独占
weight 或 Verilator runtime 成本；不能把 58.3% write-op 占比当成可兑现加速空间。

## 6. DPI/观测逻辑的角色与责任边界

当前全图日志汇总：memory-cone DSU 有效合并 25,180 次，effect-result 规则额外合并 5 次。
此计数属于全图且不是两个机制的消融比例，不能直接换算性能贡献；结合 DPI 修复前已经存在
同量级 giant ASC，可排除“新 DPI 修复才制造了全部 giant”的说法。

无返回 DPI/SystemTask 仍是 sink，其条件和输入可能依赖多个 memory，因而可通过 memory
规则成为连接桥；不能因为 effect-result 合并只有 5 次就宣称观测逻辑无关。986 个 DPI /
971 个 SystemTask 的存在证明观测逻辑被纳入，但本轮尚未量化移除观测 sink 后的组件变化。

最终归因：RTL 的宽状态、请求关联和多路选择是真实工作；“整个 memory 的所有相关 sink
必须共置”是当前实现策略；逐 bit lowering 是额外表示膨胀。它们不是互斥原因。求解器
权重修正已能减少 giant owner 的附加工作，却不能突破这个已形成的原子粒度。

后续若要拆分，应先审计实际 memory 合并桥和读边界，保留同周期读写、写优先级及 side-effect
执行语义。不能直接关闭检查或把 MemoryRead 当普通寄存器结果。已有
[`test_memory_read_retime.cpp`](../../wolvrix/tests/transform/test_memory_read_retime.cpp)
232–269 行也显示：RAM read retime 需要 shadow address 与 write-hit refresh，且多写口例
会跳过。本轮不实施这些变换，不改变既有 runtime gate 的结论。

## 7. 增量解释：514 个写端点不等于 514 拍或物理写端口（2026-09-14）

用户追问第 4/5 节细节后进一步只读核验：`Common.scala` 的 DSData 为 data 加 corrupt；
本配置一 beat 为 256 位数据加 1 位 corrupt，一行含两个 beat，共 514 位，memory 有 7 行。
`RefillBuffer.sv` 的 W0_mask 是 `{257{beat},257{~beat}}` 两组：一次有效写只选一个
257 位组，不是一次写入 514 个独立地址，也不是需要 514 个仿真周期。当前实例写入的
corrupt 为常量 0。514 指覆盖所有写场景的静态逐 bit 端点数，不是物理独立端口数。

沿现有 clean-v4 closure-aware 产物继续检查，逐 bit 结构没有在生成 C++ 阶段完全消失：

- `build/repcut_closure_runtime_20260902/clean-v4/closure-aware/package/build/verilated/part_8/`
  下 `VWolviRepCutUnit_part_8___024root__32.cpp:23554` 起，slice_2 refill buffer 的
  v0/v1/v2 各有独立 `__VdlyVal`（数据）、`__VdlyDim0`（地址）、`__VdlySet`（待写标记）。
- 同目录 `VWolviRepCutUnit_part_8___024root__37.cpp:15898` 起，提交阶段逐项判断标记，
  对同一 memory word 用 `0xfffffffe/0xfffffffd/0xfffffffb` 掩码更新 bit 0/1/2。

这是现有生成 C++ 保留细粒度暂存和 read-modify-write 的直接证据，不只是 GRH op 计数
膨胀。但未检查对应最终汇编或做独占 profile，不能声称 CPU 最终必然执行 514 次 store，
也不能据此量化加速。非阻塞写的暂存/统一提交有正确性目的，潜在优化是共享地址、掩码和
宽数据提交，而不是随意改成即时状态写入。

GRH 原生 MemoryWritePort 已包含全行宽 data 和 mask，见
[`grh-ir.md`](../../wolvrix/docs/grh/grh-ir.md) 的 kMemoryWritePort。
对同 clock/address 且掩码不冲突的逐 bit 写，存在重新聚合成宽 masked write 的表示空间；
仍需证明边沿、优先级、使能和未知值语义。即使完成此聚合，四块 memory 的 symbol 和
消费者关系仍可完全相同，所以“压缩写操作”不等于“解开 429-memory ASC”。
