# NO00049：used-bits 分析——死锥消除 + 宽度收窄（IR 表达形态向 gsim 靠拢）

日期：2026-09-20/21。最终判定：**ACCEPTED（正式 6 次交替 +3.986292%、
秩次门 U=0、p=0.05 通过）**。

## 背景与节点方向

NO00046/47/48 钉死：发射层微优化与调度框架已低于噪声底（真效应 ≤0.3%），
剩余差距的主体是**表达形态**——NO00047 实测每 eval 指令预算 IR 2.57M vs
gsim 0.925M（2.78×），结构归因"op 分解更细（~2×）× 物化协议层"。
本节点是按用户方向立项的 IR 表达形态节点：对照 gsim IR 的
`usedBits`（`reference/gsim/src/usedBits.cpp`，反向"实际使用位"收窄）在
GrhSIM-IR 上建立同款不动点分析，并衍生两种恢复动作：

1. **死锥消除**（used==0）：删除结果完全不可观测的纯计算 op / 读 op，以及
   无活读者的状态的写口与状态本体。
2. **宽度收窄**（0<used<width）：截断透明锥（add/sub/mul/and/or/xor/xnor/
   not/shl/mux/bitSelect/prioritySelect/assign/concat/replicate/sliceStatic/
   constant）在 IR 层重写为窄 op；非透明 op（div/mod/lshr/ashr/比较/归约/
   sliceDynamic 等）保持原宽并在边界插 `sliceStatic`；寄存器状态同步收窄
   （读/写/init 重建）。

## 池量化（普查先行，`scripts/grhsim_used_bits_stats.py`，NO00048 checkpoint）

对 `ptmp/no00048_sched_20260920/flow-final/xiangshan_grhsim_ir.json`
（ops=3,732,947 / values=3,571,051 / states=313,107）运行 Python 版
used-bits 分析（规则与本 pass 一致）：

- 值宽度分布：1 位 2,398,722；2-8 位 722,895；33-64 位 237,764；
  65-128 位 24,462；129-256 位 5,342；>256 位 4,329。
- **可收窄值 32,015**：>64→≤64 降级 7,442 个；最大转移族 17-32→9-16
  （9,890）、65-128→33-64（4,901）、65-128→1（2,092）。
- Case A 收窄 op 27,636 个（concat 11,104 / or 7,603 / mux 4,017 /
  add 2,376 / sliceStatic 1,553 …）；Case B 边界 slice 2,819 个
  （lshr 2,547 为主）。
- 宽（>64）op 32,388 个，字工作量 113,132 → 93,029 字（−17.8%）。
- **死值 140,004 个（3.9%）**，生产者几乎全是纯计算：and 30,846 /
  or 26,468 / mux 20,493 / not 18,584 / bitSelect 16,811 / concat 5,302 /
  sliceStatic 5,285 / eq 4,425 / state.read 4,206 …（既有 canonicalize/
  clone/pack 等 pass 只做重接线不做 DCE，死锥由此积累）。
- 可收窄寄存器状态 1,027 个（>64→≤64 降级 63 个）。
- 生成代码宽 helper 静态站点（NO00048 flow-final）：grhsim_*_words 族
  合计约 79k 处（slice 57.8k / index 7.3k / mux 5.4k / insert 5.0k …），
  约占总文本 1% 量级——收窄池静态上界本身有限，**死锥（3.8% op）与降级
  （7.4k 站点）是主要可转化池**；预估合计指令 −2~4%，Host 收益须实测。

**证伪标准**：若筛选显示指令降幅 <1.5% 或 Host 收益 <0.8%（3v3 分辨下限），
则收窄部分判 REJECTED，仅保留死锥部分复测；两者都低于下限则按 goal 规则
在本节点内改换机制继续。

## 语义保持论证

- 前缀性质：值 v 收窄到 k 时，全部消费者只需要 v 的 [0,k)——消费者对
  operand 的需求按 op kind 反向传播（透明族传 k；比较/归约/逻辑真值/右移/
  动态切片传全宽；concat 按原始布局区间分配；sliceStatic 传 start+k）。
  因此收窄边界处只需**截断**（sliceStatic），永不需要扩展。
- sink 保守策略：output.write / system.* / dpi.call / input.read /
  memory（array）端口 / 事件与条件 operand 全部按全宽使用，不可观测位
  之外的通道不存在（mapping 只引用 op operand 已有的值）。
- 状态收窄：读、写（data/mask 等宽契约）、init（const 文本由 emit 按新
  宽度 resize；random 按宽度取随机数——NO00026/32 已先例证明状态集合
  变更对拍安全）同步重建；event history 引用原样保留。
- 死锥消除：只删结果全死的 `core.compute.*` / `state.read` / `memRead`，
  以及 usedState==0 状态的 regWrite/latchWrite；随后清扫不再被任何存活
  op 引用的 logic 二态状态（含孤儿 event history）。system/dpi/写口按
  副作用保留。
- 发射层风险（逐条对照 cpu_emit 勘察结论）：宽 op 单 N array helper 由
  收窄侧的显式 sliceStatic 保证字数一致；标量 cast 路径不接受宽 operand
  → 宽→窄必过 slice；memRead result==元素类型契约 → v1 不收窄 array；
  output.write 按 operand 类型写槽 → output 全宽保留；DPI 类型精确匹配
  → DPI 相连值全宽；lshr/ashr/div/mod 的 operand0 等宽假设 → 全部归入
  非透明族不收窄。`sliceEnd` 参数同步维护（emit 不读，但 reg_to_mem 读
  sliceStart，文档约定 result.width==sliceEnd-sliceStart+1）。
- PassManager 每个 pass 后跑 `verifyGrhSimModel`；`compact` 对被保留引用
  的被删值/状态抛异常——任何接线错误都会在生成期响亮失败。

## BASELINE

- 对照（old）：NO00048 正式二进制
  （`ptmp/no00048_sched_20260920/flow-final/emu/emu`，sha256
  `1c5514794d870d149e16c8bdaa98d441dc8d3cd9e2d57172ffa2989d88194761`，
  本节点开档时核对一致），正式三次 new 均值 **73.372333 s**。
- 基线 commit：wolvrix 子模块 `1cffa87`（NO00048 接受）；根仓库 `fe00670`。
  开档时两仓库工作区零差异。
- 等价门槛：`instrCnt=240349`、`cycleCnt=99996`、IPC 2.403586、末端 PC
  `0x80000c0c`、guest cycles 100001、退出码 0、NEMU 对拍无 mismatch。
- 测量口径：`make benchmark_grhsim_ir`，CPU2 单核、XS_EMU_THREADS=1、
  100k cycles、trace 全关、交替 old/new、每次运行前 posix_fadvise 驱逐；
  筛选单对（+0.4% 门需两票一致），正式预注册 old1/new1/old2/new2/old3/new3，
  秩次判据 max(new)<min(old)（U=0、p=0.05）。
- 筛选/诊断路径：`make reemit_grhsim_ir` 自 NO00048 checkpoint
  （`ptmp/no00048_sched_20260920/flow-final/xiangshan_grhsim_ir.json`），
  透传 `GRHSIM_REEMIT_COMMIT_COMPACT_WALK=1 GRHSIM_REEMIT_COMMIT_MEM_WALK=1
  GRHSIM_REEMIT_USED_BITS=1` 复现 NO00048 发射形态 + 本节点 pass。
- 资源：生成/编译各 `timeout -s KILL 1800` 截止；编译 `VM_BUILD_JOBS=32`；
  仿真止损 = old 预注册比较值 ×1.5。
- 诊断产物目录：`ptmp/no00049_used_bits_20260920/`（不入提交）。

## 阶段记录

### IMPLEMENTED（2026-09-20/21，含调试记录）

实现：`wolvrix/lib/grhsim/pass/used_bits.cpp`（注册 `grhsim.used-bits` 语义
变换 + `grhsim.used-bits-analyze` 分析），触点：`pass.cpp` 注册、CMakeLists、
`scripts/wolvrix_xs_grhsim_ir.py` CPU_PIPELINE（mux-chain-fold 之后、第二轮
mapping 之前，HDLBits IR 流程共享同一管线）、`scripts/reemit_grhsim_ir.py`
`--used-bits` 筛选路径、Makefile `analyze_grhsim_used_bits` /
`GRHSIM_REEMIT_USED_BITS` 透传；聚焦测试 `runUsedBitsTest`（标量链收窄、
宽降级、lshr 边界 slice、寄存器收窄、死锥消除、concat 跨界、幂等性）随
`grhsim-ir-tests` 通过。文档 `docs/grhsim_ir/passes/used-bits.md` +
cpu-st.md 管线描述同步。

真实模型调试记录（reemit 于 NO00048 checkpoint，compact 前置校验捕获）：

1. **字符串/非 logic 值被误判死锥**：`$display` 字面量等 string 常量无宽度，
  used 恒 0 被死锥删除而其 system.task 消费者存活——死锥规则补
  `widthValue != 0` 前提。
2. **无结果消费者通道漏改**：写口（无 result）不在存活者重接线覆盖范围内；
  不可收窄状态的写口仍引用已收窄的 data——分析改为**资格感知**：结构性收窄
  资格（init 形态、引用者身份、data/mask 等宽契约）在不动点前计算，不可收窄
  状态的写口 data/mask 一律按全宽使用。
3. **跨状态重接线顺序**：状态按 id 升序重建时，写口重建可能引用尚未重建的
  他状态读值——状态收窄拆两阶段（先建全部新状态+读、设全 rewire，再重建
  写口）。

### VALIDATED 筛选（2026-09-21，flow-v1）

reemit（NO00048 checkpoint + used-bits + remap，compact-walk/mem-walk 发射
形态一致）pass 统计：**dead_ops_removed=149,567、dead_states_removed=20,429、
narrowed_values=32,015、downgraded_values=7,442、rebuilt_ops=28,169、
boundary_slices=204、adapt_slices=6,522、narrowed_states=1,027、
wide_words 118,626→97,902（−17.5%）**。fresh 编译 199.34 s（nproc=32）。

筛选第一票（screen-v1，等价端点 old/new 均 `240349/99996/100001/
0x80000c0c`、退出码 0、DIFFTEST 无 mismatch）：old 72.993 / new 69.944，
**+4.177%**，过 +0.4% 门。第二票（screen-v1b，同二进制）：old 73.213 /
new 69.733，**+4.7533%**——两票一致。

### ACCEPTED（2026-09-21，正式门全绿）

- 测试：`grhsim-ir-tests`（含新 `runUsedBitsTest` 六组场景）、
  `grhsim-cpu-mapping-tests`、`grhsim-cpu-schedule-tests`、
  `grhsim-cpu-emit-tests` 全部通过；`test_grhsim_reg_to_mem_rtl`（共享
  CPU_PIPELINE 的 RTL 夹具管线）通过；HDLBits DUT=001 通过。
- 完整 SV→C++ 生成 **720.04 s**（used-bits pass 本体 28.43 s；<1800 截止）；
  fresh 编译 **198.51 s**（VM_BUILD_JOBS=32）；正式 model 与筛选 model
  **md5 全等**；生成 C++ 文本 264.9 MB → **239.8 MB（−9.5%）**。
- 正式 6 次交替（预注册 old1/new1/old2/new2/old3/new3，posix_fadvise 驱逐）：
  old {73.139, 73.592, 73.298}（均值 **73.343000**、SD 0.229828），
  new {70.341, 71.253, 69.664}（均值 **70.419333**、SD 0.797391）。
  **max(new)=71.253 < min(old)=73.139，U=0、单侧精确 p=0.05、
  Cohen d=−4.982——秩次门通过，+3.986292% 为真实收益。**
- 六次端点全部 `instrCnt=240349、cycleCnt=99996、guest cycles 100001、
  末端 PC 0x80000c0c`、退出码 0、DIFFTEST 无 mismatch（benchmark 脚本内置
  expected_endpoint 校验）。
- 正式二进制 sha256
  `10a06e88ca2b97ff15a33005d8df4a732ed7b9dafba3db987ed462ec06c28d93`
  （`ptmp/no00049_used_bits_20260920/flow-final/emu/emu`）。
- 新性能锚点：**70.419333 s** = gsim 归档 46.965 s 的 **1.499839×**
  （较 NO00048 的 73.372333 s 降 2.953 s）。
- 结构效果（正式生成口径同筛选）：死锥消除 op 149,567、状态 20,429；
  收窄值 32,015（>64→≤64 降级 7,442）、收窄状态 1,027；
  宽值字工作量 118,626→97,902 字（−17.5%）。

### 后续方向（移交下一节点）

- 普查/实现工具保留：`scripts/grhsim_used_bits_stats.py`（Python 版分析）与
  `grhsim.used-bits-analyze`（管线内分析变体）。
- 已确认不做的子机制：常数偏移 lshr→sliceStatic 转化（普查实测常数偏移
  lshr 为 0 处）。
- 剩余表达形态差距（对照上一轮方案）：memory/array 元素的 used-bits 收窄
  未做（v1 全宽保守）；`_BitInt` 宽值表示切换、位段分裂（splitNodes 形态）、
  表达式粗化仍待各自普查与立项。死锥消除后模型 op 数 3.73M→约 3.58M，
  compute 惰性激活池仍是最大框架级残余（受 NO00047 控制流惩罚约束）。
