# NO00029 grhsim-ir 六相调度 × latch-ICG 时钟门控：合并超节点激活死锁故障分析

日期：2026-10-03
状态：研判稿（仅分析，不含修复）
关联：M5d-8 首个失败（DCache.sv:2015 @ CoreMark instr 238）；xs-bugcase CASE_025

---

## 1. 结论摘要

XiangShan 全核 grhsim-ir 仿真在 CoreMark 第 238 条指令处触发
`RunAssertion failed at build/xs/rtl/rtl/DCache.sv:2015`（wb 释放地址高 17 位全 0）。
根因不是数值计算错误，而是**六相调度的超节点激活语义与 XiangShan 的锁存式集成时钟门
（latch-ICG）在合并超节点后形成循环自锁**：

- SRAM 宏的门控使能 `E = rckEn | wckEn` 是一个组合输出，由某个超节点发布；
- C2 合并把 E 的生产者与一个"按门控时钟 Q 门控的寄存器写"熔进**同一个 eventGated
  超节点**；
- 该超节点按双重门规则（`eventActive && dataActive`）只在 Q 的 posedge 事件发生时
  才运行；
- 而 Q 要产生 posedge，必须先在低电平窗口看到 E=1 并锁存——E 却永远等不到发布。

四者互为前提，从 eval 0 起恒不成立，**激活死锁**。全芯片所有同形态 SRAM 宏（生成模型
中 189 个 ICG 锁存器实例）批量冻结，表现为：tag/data/meta 阵列写不进、读恒 0、全部
查找 miss、mainPipe 幻影脏 victim、最终 wb 释放出 tag=0 的非法地址触发断言。

1-op 超节点（`--max-op-in-compute-supernode 1`）下环被拆开，一切正常——这证明锁存
器语义、透明读、边沿检测、六相不动点迭代全部正确，**唯一失效的环节是 eventGated
超节点的激活条件**。

本文档只做原理性研判：解释六相调度为什么在原理上处理不了这种情况（§6），评估修复
方向的原理得失（§10），不实施任何修复。

---

## 2. 现象与复现

### 2.1 整核现象

命令：`make run_xs_wolf_grhsim_ir_emu`（coremark-2-iteration.bin + NEMU difftest）。

```
RunAssertion failed at build/xs/rtl/rtl/DCache.sv:2015.
Assertion failed at DCacheWrapper.scala:1688
Core 0: ABORT at pc = 0x800027c6
Core-0 instrCnt = 238, cycleCnt = 9,395
```

确定性复现。断言内容：wb release 地址须满足 `(|addr[47:31]) && addr < 48'h80000000000`；
失败时地址 = `0xe80`（tag=0，高 17 位全 0）。M0 存档 emu 同负载干净；NEMU difftest
在前 237 条指令无任何架构级 mismatch（取值/寄存器/存储全部一致）。

### 2.2 二分矩阵（`ptmp/m5d8_bisect_*`）

| 变体 | 选项 | 结果 |
|---|---|---|
| baseline | 默认全量 | **断言触发**（DCache.sv:2015） |
| no_semopt | 关闭 reg-to-mem/comb-pack/pack-bit-registers/phase-simplify/clone-shared-compute | 断言触发（LoadPipe.sv:308 + BankedDataArray.sv:623） |
| no_regtomem | 仅 `--disable-reg-to-mem` | 断言触发（同 baseline） |
| allmem | 数组全部 mem 类 | 断言触发 |
| nochunk | 关闭块/帧机制 | 断言触发 |
| **sn1** | `--max-op-in-compute-supernode 1` | **干净** |

结论：与语义优化、存储分类、emit 分块均无关；**唯一相关变量是超节点合并粒度**。

### 2.3 最小复现（xs-bugcase CASE_025）

`testcase/xs-bugcase/CASE_025`（约 60 行 RTL）：latch-ICG + `en = read|write` 一身二任
（既做门控使能，又做门控寄存器 `ren_d` 的写数据）：

```
默认（合并）：[MISMATCH] cycle=7 phase=high resp_data ref=0xabcd grhsim=0x0000
--max-op-in-compute-supernode 1：[PASS]
```

xs-bugcase 全量回归 24/25（原 24 例不受影响），CASE_025 在修复落地前为已知失败。

---

## 3. 背景 1：XiangShan 的 latch-ICG 时钟门控

### 3.1 结构

XS 的 SRAM 宏按访问门控时钟以省电。门控单元（`build/xs/rtl/rtl/ClockGate.sv`）：

```systemverilog
module ClockGate (
  input  wire TE,
  input  wire E,
  input  wire CK,
  output wire Q
);
  reg EN;
  always_latch begin
    if(!CK) EN = TE | E;   // CK 低电平期间 EN 透明跟随 E
  end
  assign Q = CK & EN;       // 门控输出时钟
endmodule
```

每个 SRAM 宏实例各持有一套时钟门（`MbistClockGateCell rcg`，内含一个 `ClockGate`
实例）。信号链（每一环都有 RTL 实证，以 dcache tag bank 的 `SRAMTemplate_212` 为例）：

```
ClockGate.Q ── MbistClockGateCell.out_clock ── SRAMTemplate._rcg_out_clock ── array_256x86.RW0_clk
```

```systemverilog
// build/xs/rtl/rtl/SRAMTemplate_212.sv
MbistClockGateCell rcg (
  .clock         (clock),
  .mbist_writeen (wckEn),
  .mbist_readen  (rckEn),
  .mbist_req     (mbistBd_ack),
  .E             (rckEn | wckEn),          // 门控使能（组合）
  .dft_cgen      (io_broadcast_cgen),
  .out_clock     (_rcg_out_clock)          // 门控时钟输出 = 该实例的 Q
);
sram_array_1p256x86m43s1h0l1b_dcsh_tag array (
  ...
  .RW0_clk        (_rcg_out_clock),         // 宏的时钟输入接 Q，不接主 clock
  ...
);
```

宏内部的全部时序元件（读地址/读使能寄存器，以及 Memory 阵列的写操作）都在
`posedge RW0_clk` 上工作——**即由该实例自己的门控时钟驱动，而不是模块主时钟
`clock`**：

```systemverilog
// build/xs/rtl/rtl/array_256x86.sv
always @(posedge RW0_clk) begin          // RW0_clk == 该实例 ClockGate 的 Q
  _RW0_raddr_d0 <= RW0_addr;             // 读地址寄存器（无条件更新）
  _RW0_ren_d0   <= RW0_en;
  _RW0_rmode_d0 <= RW0_wmode;
  if (RW0_en & RW0_wmask[0] & RW0_wmode) Memory[RW0_addr][0  +: 43] <= RW0_wdata[42:0];
  if (RW0_en & RW0_wmask[1] & RW0_wmode) Memory[RW0_addr][43 +: 43] <= RW0_wdata[85:43];
end
assign RW0_rdata = _RW0_ren_d0 & ~_RW0_rmode_d0 ? Memory[_RW0_raddr_d0] : 86'bx;
```

后文凡写"Q"或"门控时钟"，均指**当前实例自己那一套 ClockGate 的输出**
`_rcg_out_clock`——全芯片有 189 个这样的实例，189 条各自独立的 Q，不存在全局
共享的 Q。

### 3.2 三个关键性质

1. **使能是低电平采样的锁存器**。E 必须在 CK 上升**之前**的低电平窗口就绪；高电平
   期间 E 的变化绝不外传（防毛刺）。这是 ICG 的正确性来源，也是后文"环不能自愈"
   的原理性原因（§6.4）。
2. **每个宏实例的 E 独立**：`E = rckEn | wckEn`，由该宏自己的读/写请求算出（按访问
   细粒度门控）。
3. **源码只有一处锁存器描述**（`always_latch` 全 RTL 仅 1 行，在 ClockGate.sv 模块
   定义内），但 FIRRTL elaboration 模块级复用，全芯片 elaborate 出 **189 个独立的
   EN 锁存器寄存器**（生成模型 `grhsim_SimTop.hpp` 中 189 个 `rcg_CG_EN` state）。
   "香山全局只有一个锁存器"的说法只在模块定义层面成立；实例层面是 189 把各自独立
   的门控。

---

## 4. 背景 2：六相调度模型与超节点激活语义

### 4.1 模型骨架

六相 eval（`cpu_phase_emit.cpp` 的 evalBody）：

```
eval():
  pInput()                          # 输入端口 -> boundary
  loop round = 1..100000:           # 不动点迭代直到收敛
    pEvent()                        # 重建 eventAct（edgeDet 求值）
    pGeneral()                      # 按需执行超节点（组合+NBA 求值）
    pMem()                          # 存储写提交
    if pPublish(): break            # regLatchNext -> regLatch，活性前移
  pOutput()                         # 输出锥
```

组合逻辑被 C2 合并为几万个**超节点**，每个一段 C++ 函数。为提速，超节点**按需激活**
而非每拍全跑，活性由两面 flag 位图驱动：

- `dataActiveFlag[sn]`：sn 的数据输入（其读取的 boundary/状态）在本轮被改写过；
  由发布者的 fanout 表置位（sticky，直到 sn 运行才清除）。
- `eventActiveFlag[sn]`：sn 内事件携带写所监听的事件簇本轮发生（由 pEvent 按事件
  位图置位）。

### 4.2 双重门规则（关键）

发射时对每个超节点按其内容分类（`cpu_phase_emit.cpp:411-420` 的注释即设计理由）：

- 超节点**自身**的 op 带有非空 `event_acts`（含事件携带写）→ `eventGated_ = true`，
  发射为**双重门**调用点；
- S（事件簇集合）仅经下游影响非空（写操作数生产者、电平敏感 mem 读者、event-free
  副作用汇）→ **数据驱动**；
- S 为空 → 豁免，数据驱动。

生成的调用点（`grhsim_SimTop_tu36.cpp:23655-23669`，XS 实证）：

```cpp
if(dataActiveFlag[12847]){                       // event-free：数据驱动
    dataActiveFlag[12847]=0;
    sn_12847__op_8534985();
}
if(eventActiveFlag[12848]&&dataActiveFlag[12848]){ // eventGated：双重门
    eventActiveFlag[12848]=0;
    dataActiveFlag[12848]=0;
    sn_12848__op_8534937();
}
if(dataActiveFlag[12849]){
    dataActiveFlag[12849]=0;
    sn_12849__op_8535196();
}
```

### 4.3 双重门的设计动机

注释原文："firing clears the sticky data flag, so such a supernode must not fire without
its edge (**a guard-skipped write would lose the pending update**)"。

含义：eventGated 超节点内的寄存器写以"事件发生"为语义条件。若允许它仅凭数据变化
就运行（事件未发生），那次写会把"尚不该生效"的值提交进 regLatchNext——一个
**guard-skipped write**；而 sticky data flag 同时被清除，等事件真正到来时，若数据
不再有新变化，超节点不再运行，这次挂起的更新就**永久丢失**。为防止这种静默丢写，
规则是：eventGated 超节点宁可不跑，也不能抢跑。

---

## 5. 故障机制：循环激活死锁

### 5.1 涉及的对象（以 dcache tag 阵列 bank 0 为例）

故障涉及的全部对象就是一条**使能链**加两类写。按依赖顺序：

1. **`rckEn` / `wckEn`**（读/写时钟使能，组合信号）：由请求侧逻辑产生，在
   sn_12848 内被计算——`wckEn` 发布到 boundary，`rckEn` 只是超节点内局部量。
2. **`rcg_E = rckEn | wckEn`**（门控使能，组合输出）：**由 sn_12848 计算并发布**，
   消费者是下一项的锁存器。这是全案最关键的一个值。
3. **`CG$EN`**（EN 锁存器）：`EN <= rcg_E when ~clock`（条件 NBA）。写它的超节点
   在 tu1003，数据驱动——`clk` 每半拍翻转使其 dataActive 每半拍置位，故实际
   每半拍运行，每半拍采样一次 `rcg_E`。
4. **`Q = clock & EN`**（该实例 ClockGate 的门控时钟输出）：纯组合。消费者是
   第 7 项的宏寄存器和第 5 项的边沿检测。
5. **act 222**（事件簇）：`edgeDet(posedge Q)`，在 pEvent 阶段求值。Q 出现上升
   沿 ⇒ act 222 触发 ⇒ pEvent 按事件位图给监听它的超节点置 `eventActive`。
6. **act-222 门控写（一）**：`packed_bits_2790543 <= {wckEn&wmask, rcg_E}`
   （resp-valid 流水线寄存器组）——写在 **sn_12848**，与第 2 项的 `rcg_E`
   **同处一个超节点。这就是合流点**：使能的生产者与被该使能最终门控的写，
   被合并进了同一个超节点。
7. **act-222 门控写（二）**：宏寄存器（`_RW0_raddr_d0`、`_RW0_ren_d0`、
   `_RW0_rmode_d0`、`Memory` 写），分布在其他 eventGated 超节点。

画成图（`──▶` 为数据/事件依赖）：

```
                ┌─────────────── sn_12848 自己也要等 act 222 才运行 ──────────────┐
                │                                                                │
 [sn_12848] ──rcg_E──▶ EN 锁存器 ──▶ Q ──▶ edgeDet ──▶ act 222 ──eventActive──▶ 门控写超节点
                ▲                                                                （含宏寄存器）
                └──────────────── act 222 永不触发，于是 sn_12848 永不运行 ◄──────┘
```

checkpoint 实证：宏寄存器 `_RW0_raddr_d0` 的 regWrite（op 2455886）
`event_acts=[222]`；act 222 的 edgeDet 事件值 = `rcg$CG$Q.ev`（posedge）。

### 5.2 合并如何造出这个环

合并前，发布 `rcg_E` 的组合 op 与 act-222 门控写分属不同超节点：前者数据驱动，
正常工作。C2 合并器发现 act-222 门控写的写数据里就含着 `rcg_E`
（`packed_bits_2790543` 的 bit0；生产者↔消费者紧相邻，连接度高），将二者熔进
同一超节点 sn_12848。sn_12848 内**含** act-222 门控写 ⇒ 被归类
eventGated_ ⇒ 其**全部**输出（包括 event-free 的 `rcg_E`/`wckEn`）都只能在
`eventActive && dataActive` 时发布。

### 5.3 死锁的依赖方程

时间基准：t 以**半拍 eval** 为单位——difftest harness 每个 guest cycle 先跑
clk=0 eval 再跑 clk=1 eval（FST 中 `clock` 偶数 eval 为高、奇数 eval 为低），
锁存器窗口（CK 低）落在奇数 eval，Q 的上升沿只能落在偶数 eval。

记 R(t) = "sn_12848 在 eval t 运行"，E(t) = "rcg_E 在 eval t 发布为 1"，
L(t) = "锁存器 EN 在 eval t 的低电平窗口锁存到 1"，Q(t) = "Q 在 eval t 出现上升沿"
（= act 222 触发），D(t) = "sn_12848 的任一数据输入变化"（请求期恒真）。

六相语义给出：

```
R(t)   = Q(t) && D(t)              （双重门）
Q(t)   = L(t-1) && CK_high(t)      （ICG：前一低电平窗口锁存的 EN，高电平放行）
L(t)   = E(t) && CK_low(t)         （锁存器透明窗口）
E(t)   = R(t) && (rckEn|wckEn)(t)  （rcg_E 只能由 sn_12848 发布）
```

代入得 `R(t) = R(t-1) && ...`：**R 的自依赖递归，且无上电初值**。初始条件
`E(0)=EN(0)=Q(0)=0`（memset 初始化）是不动点，系统永远停留其上：

- sn_12848 不运行 ⇒ `rcg_E` 恒 0（FST 实证：全程恒 0）；
- 锁存器每拍运行但采到 E=0 ⇒ `CG_EN` 恒 0（FST 实证）；
- Q 恒 0 ⇒ act 222 恒不触发 ⇒ 宏寄存器永不更新（`_RW0_raddr_d0` 恒 0、Memory 永不
  写入、`io_r_resp_data` 恒 0——FST 全部实证）。

注意 `dataActiveFlag[12848]` 其实**一直被 fanout 置位**（生成代码 tu186/tu210/
tu311/tu53 多处 `dataActiveFlag[12848]=1`）——数据侧条件恒满足，缺的是事件侧；
而事件侧又只能由该超节点自己的输出去促成。这不是"条件暂时不满足"，是**结构性
不可达**。

### 5.4 从宏冻结到断言的因果链

1. tag 阵列写不进、读恒 0 ⇒ 所有 dcache 查找 miss（同一地址反复 miss；启动滞后
   88+ 拍；IPC 0.025）。
2. 某 store-miss 走 replace，victim 的 coh 读出 2（dirty；coh 来自另一阵列/路径，
   不在本次冻结环内）⇒ mainPipe 置起 `io_wb_valid`（Verilator 参照全程不置位）。
3. wb 地址 = `{s3_tag, s3_req_vaddr[11:6], 6'h0}`；tag 阵列冻结 ⇒ s3_tag=0 ⇒
   地址 = `0xe80`，高 17 位全 0。
4. 断言 `(|addr[47:31]) && addr < 2^39` 开火（`DCache.sv:2015`）。

整条链上没有任何一处数值算错：mainPipe 请求流与 Verilator 参照逐拍一致（约 88 拍
滞后对齐），拼接/packed-bits 位序/slice 位选逐项验证吻合。失败**纯粹**由"该算的
没算"（激活缺失）造成。

---

## 6. 为什么六相调度在原理上处理不了这种情况

本节是核心研判：这不是某个判据的实现 bug，而是六相激活模型的一个**隐含前提被
latch-ICG 违反**。

### 6.1 双重门的隐含前提：事件源与被门控者之间无组合回路

双重门规则（§4.3）防止的是"guard-skipped write 丢失 pending update"。它隐含假设：

> 事件簇的边沿产生，不依赖于被该事件门控的超节点的组合输出。

即：事件源（某个网络的跳变）的求值锥与被门控超节点的输出之间不存在组合回路。
在此前提下，"等边沿"永远是有穷等待：边沿由外部世界（其他超节点）独立产生，本
超节点只需等待。

latch-ICG 恰恰违反该前提：事件源 Q 的求值锥为 `Q = CK & EN`，而 `EN` 的更新锥
是 `EN <= E when ~CK`，`E` 又由被门控超节点发布。**事件的产生条件包含了被门控
者自己的输出**——前提不成立，"等待"变成"死等"。

### 6.2 eventGated_ 分类是语法判定，感知不到语义回路

`eventGated_` 的判定是结构性的："本超节点的任一 op 的 `event_acts` 非空"
（`cpu_phase_emit.cpp:421-428`）。它回答的是"含不含事件写"，不回答"本超节点的
组合输出是否参与产生这些事件"。后者需要沿事件网络反向做组合锥分析（edgeDet 事
件值 ← 门控逻辑 ← 锁存器 ← 使能锥 ← 本超节点输出），这不在现有分类的视野内。
于是 sn_12848 被"合法地"归入双重门，环在分类层面不可见。

### 6.3 超节点函数的原子性：组合输出与事件写共命运

六相模型把超节点函数作为激活的最小原子：要么整体运行（所有输出刷新），要么整体
跳过。eventGated 超节点里的 **event-free 组合输出没有独立的发布通道**——它们与
事件携带写共享同一个双重门。语义上，`rcg_E` 是"输入变化即应刷新"的组合信号；
模型上，它被迫与"等边沿"的写同生共死。**粒度错配**：激活粒度（超节点）粗于语义
粒度（op/输出级）。

### 6.4 eval 不动点迭代为何不能自救

一个自然的疑问：eval 内有多轮收敛（round 1..N），能不能在同一 eval 内"先试探性
发布 E → 锁存 → Q 沿 → 再正式运行"？不能，原因在 ICG 的相位语义：

- `Q = CK & EN`：CK 高电平期间，EN 的锁存窗口**关闭**（`if(!CK)`），E 渗不进 Q；
- Q 的 posedge 只能由"上一个低电平窗口已锁存的 EN"在 CK 拉高时产生；
- 因此第一个 Q posedge **最早**也只能出现在 E 首次发布**之后**的下一个高电平
  eval——即必须存在一次"既往的 E 发布"；
- 而不动点迭代的各轮共享同一套活性规则：act 222 从未触发过 ⇒ 任何一轮里
  sn_12848 都不会运行 ⇒ E 的"既往发布"不存在。

换言之，ICG 防毛刺的本质（使能只在低电平采样）决定了这个环**没有同 eval 内的
自举路径**；点火必须跨 eval，而跨 eval 的第一次点火又被激活规则禁止。死锁是
**跨 eval 的激活顺序不可达**，不是 eval 内收敛问题。

### 6.5 edgeDet 语义：无初始化脉冲、无组合旁路

事件的产生只有一条通道：edgeDet 检测到网络实际跳变。六相模型没有以下任何机制：

- 事件簇的上电/复位初始化脉冲（让 act 222 在 eval 0 强制触发一次）；
- 组合输出绕过活性门直接发布的旁路（bypass publish）；
- 对时钟门控的特判（把 `Q = CK & EN` 的 EN 当作组合时钟使能而非锁存状态处理）。

这些机制任何一个都能打破环，但都不在现有模型里——因为模型此前的所有验证对象
（§7）从未需要它们。

---

## 7. 为什么既有验证手段全部漏检

| 验证 | 覆盖 | 漏检原因 |
|---|---|---|
| HDLBits 162 + 黄金差分 161/161 | 小型教学 DUT | 无 latch-ICG + 细粒度门控 SRAM 结构，合并器造不出环 |
| xs-bugcase 24 例 | XS 子模块 | 同样无该结构（现已由 CASE_025 补上） |
| test_wolvrix 57 | 单元/小集成 | 测试夹具无 ICG；latchRingTest 覆盖的是 latch 语义而非激活环 |
| M0 存档 emu | 旧调度器 | 无 eventGated 双重门这套激活模型 |
| Verilator | 参照 | 标准事件驱动，无超节点激活概念 |

故障形态需要三个要素同时出现：**latch-ICG（锁存器时钟门）× 按访问细粒度使能
（E 为组合信号且参与门控写数据）× 超节点合并（把使能锥与门控写熔为一炉）**。
此前没有任何测试平台同时具备前两条，第三条自然无从暴露。

---

## 8. 影响面评估

- **实例规模**：生成模型中 189 个 `rcg_CG_EN` 锁存器（icache metaArray、dcache
  tag/data、L2、BPU 等各 SRAM 宏）。tag 阵列 4 bank 已实证全部冻结；同形态宏的
  冻结面原则上遍及全片（V1 no_semopt 变体在 LoadPipe/BankedDataArray 的别处断言，
  正是冻结面随变体移动的表现）。
- **可观察表象**：全 miss（同地址反复 miss）、IPC 0.025（参照 0.09 的约 1/4）、
  启动滞后 88+ 拍、最终幻影写回。difftest 前 237 条指令架构级干净——miss 与
  慢都是微架构透明的，只有最后的非法写回地址越界。
- **对 M5d-8 其余验收的影响**：黄金差分、HDLBits、xs-bugcase（除 CASE_025）、
  big-comb/xs-components 均不受影响（无该结构）；**完整 CoreMark 验收被此项阻塞**。

---

## 9. 与 latch-transparent-read 的关系

`latch-transparent-read`（A 段 pass，`scripts/wolvrix_xs_grhsim_ir.py:19`）把锁存器
读端改写为 `EN_read = (!CK) ? (TE|E) : EN`，解决的是**读端穿透（陈旧读）**问题。
它在本故障中正常工作但无关：

1. 环断在"E 的生产"而非"EN 的读取"，穿透改写制造不出 E 的首次发布；
2. 代入得 `Q = CK & (!CK ? E : EN)`：CK=1 时透明项关闭（Q=EN_stored），CK=0 时
   Q=0——**E 在任何 eval 都无法穿透到 Q 的边沿检测**（这正是 ICG 防毛刺的本意）；
3. eval 不动点迭代作为第二层穿透机制（同 eval 内多轮可见性）同样受 §6.4 的相位
   约束。

sn1 下全链路正确已反证：锁存器语义、透明读、边沿检测、不动点迭代均无缺陷。

---

## 10. 修复方向的原理性研判（不实施）

### 方向 A：emitter 双重门拆分（op 级门控）

**原理**：恢复语义粒度与激活粒度的一致——eventGated 超节点内，event-free 组合
输出按数据驱动照常发布；仅 event-carrying 写保持"等边沿"。环从根上断开：
`rcg_E` 不再依赖 act 222，ICG 正常点火。

**须论证/小心的点**：
1. **guard-skipped write 不变式**（§4.3 的设计动机）必须保持：事件写在事件未
   发生时不得提交。拆分的边界必须精确落在"写"而非"超节点"上。
2. **sticky data flag 的所有权**：组合部分数据驱动运行会清除/消耗 flag 吗？若
   事件写随后到来时需要"数据曾变化"这一记忆，flag 的清除时机必须改为"事件写
   实际提交时"，否则重新引入 pending-update 丢失。
3. **幂等性前提**：event-free 部分数据驱动重算必须是幂等的（§4.2 注释对豁免类
   超节点已有同性质要求）——组合求值天然幂等，理论无碍。
4. **事件写的操作数新鲜度**：拆分后组合部分先行刷新，事件写在边沿拍采样到的是
   最新组合值——与原语义一致。

**评估**：语义层面的正解；改动集中在 emitter 的 per-op 门控生成与 flag 管理，
不动 C2 合并（保性能）。风险在 2 的工程细节。

### 方向 B：C2 合并约束（禁止成环）

**原理**：合并时检测"候选节点的输出是否落在本超节点任一 event act 的 edgeDet
事件值的组合锥内"，是则拒绝合并。环不再被造出来。

**须论证/小心的点**：
1. **检测成本**：需对每个事件簇维护其事件网络的组合锥（edgeDet 值 ← 门控 ←
   锁存器 ← 使能锥），并与合并候选求交；XS 规模下每次合并决策都付费。
2. **合并粒度损失**：所有 SRAM 使能锥都被迫与门控写分家，局部超节点数增加，
   性能回退（向 sn1 方向退让）。
3. **覆盖局限**：只防"自己喂自己的事件"这一种回路；若未来出现其他跨超节点的
   激活回路形态（A 经 B 再回到 A 的长环），约束需逐个形态枚举，不如 A 治本。

**评估**：可作为 A 的补充防线（防御性约束），不宜作为唯一修复。

### 方向 C：其他候选及否决理由

- **edgeDet 初始化脉冲**（事件簇 eval-0 强制触发一次）：能点火，但为故障形态
  引入全局特殊语义，且"点火一次"并不保证后续维持（E 的持续发布仍依赖超节点
  运行），治标且语义可疑。
- **ICG 特判为组合时钟**（把 `Q = CK & EN` 的 EN 当组合使能处理）：改变 latch
  语义（EN 是真实状态元件，其保持行为在门控关闭期间可观察），特判会破坏
  latch-transparent-read 建立的正确语义。
- **锁存器锥拆分 pass**（把 ICG 的 EN 锁存器与 E 的组合锥在 GRH 层预先拆到
  不同超节点域）：等价于把 B 的约束前移到语义层，同样是治形。

### 研判结论

**A 为正解**（语义粒度对齐，治本，保性能），B 可作防御性补充。实施 A 前需要
先以文档形式固化"event-free 输出数据驱动 / event-carrying 写双重门"的精确规则
（尤其 sticky flag 的所有权与清除时机），并用 CASE_025 + XS 整核双验证。

---

## 附录 A：关键证据索引

| 证据 | 位置 |
|---|---|
| 断言现场（wb entry 0: state=1 remain=1 paddr=0xe80） | `ptmp/m5d8_wave/run.log`、探针模型 dump |
| grhsim FST（8.1MB，eval 边界全量） | `ptmp/m5d8_wave/wave.fst` |
| Verilator 参照 FST（全窗口 -b 0 -e 12000） | `build/logs/xs/xs_ref_m5d8_ref2.fst` |
| tag bank 冻结（resp/raddr_d0/rcg_E/CG_EN 恒 0） | `fst_diff get ptmp/m5d8_wave/wave.fst 'tag_arrays_0$...'` |
| 双重门调用点（sn_12848 vs 邻居数据驱动） | `ptmp/m5d8_wave/model/grhsim_SimTop_tu36.cpp:23655-23669` |
| `rcg_E = rckEn \| wckEn` 发布点 | `ptmp/m5d8_wave/model/grhsim_SimTop_tu311.cpp:3672-3677` |
| 锁存器 `EN <= E when ~CK` 条件 NBA | `ptmp/m5d8_wave/model/grhsim_SimTop_tu1003.cpp:5239-5248` |
| act 222 = posedge(`rcg$CG$Q.ev`) | checkpoint op 2455886（`event_acts=[222]`）→ edgeDet |
| sn1 对照（raddr_d0=0xbb，门控工作） | `ptmp/m5d8_bisect/sn1/probe-emu/grhsim-compile/state_dump.txt` |
| 最小复现 | `testcase/xs-bugcase/CASE_025`（合并 MISMATCH / sn1 PASS） |
| 189 个 ICG 锁存器实例 | `grhsim_SimTop.hpp` 中 189 个 `rcg_CG_EN` state |

## 附录 B：设计规则速查（现状）

- 双重门：`eventGated_ sn 仅在 eventActive && dataActive 时运行，运行后清双旗`
  （`cpu_phase_emit.cpp:411-428`）。
- eventGated_ 判定：超节点任一 op 的 `event_acts` 非空（语法判定）。
- 豁免：S 仅经下游影响非空 / S 为空 → 数据驱动（§112 豁免，幂等重算）。
- ICG：`EN <= E when ~CK`（锁存器条件 NBA，数据驱动；clk 每半拍翻转故每半拍运行）
  + `Q = CK & EN`（组合）+ `edgeDet(posedge Q)` → act。
