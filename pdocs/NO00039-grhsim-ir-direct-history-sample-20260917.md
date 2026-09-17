# NO00039：单元私有事件历史的直接采样（修复 firtool 显式时钟降级的发布管道开销）

日期：2026-09-17。最终判定：`ACCEPTED`。

本节点承接 NO00038 的 GrhSIM-IR CoreMark 100k 构建，继续从 grhsim IR 与
gsim IR（FIRRTL 级）在相同设计上的表示差异入手，定位并修复 firtool 在
FIRRTL→SV 过程中引入的、具有动态权重的性能缺陷结构。冻结 GRH、GRH pass、
XiangShan 与测试源码不修改。

## IDEA / 差异证据（2026-09-17 普查）

三个并行普查（脚本与原始日志在 `ptmp/no00039_firtool_census_20260917/`、
`ptmp/no00039_hotunits_20260917/`；gsim 侧为生成代码文本证据）：

### gsim 生成代码执行解剖（build/xs/gsim/gsim-compile/model/，329 个 SimTop*.cpp）

- 每周期**恰好一趟**拓扑序前向扫描：`step()` → 327 个 `subStepN` 顺序调用，
  84,643 个 supernode 按 topo 序排布一次，无 fixpoint/round 结构；寄存器拆分为
  `x`/`x$NEXT`，提交 supernode 位于 topo 前部（`reg = reg$NEXT` + `$old$` 比较 +
  下游置位）。difftest harness 对 GSIM 每周期只调一次 `step()`
  （`testcase/xiangshan/difftest/src/test/csrc/emu/emu.cpp:436-438`）。
- 激活：`uint8_t activeFlags[10584]`，8 supernode/字节；字节组守卫
  `if(unlikely(activeFlags[N]!=0))`（10,550 处）+ 组内逐位测试（84,395 处），
  进入即清零（consume-once，每个 supernode 每周期至多执行一次）。
- `when` 链 → 惰性 `if/else`（35,357 个 `} else {`），未命中臂不求值；
  1-bit/窄 mux → 无分支掩码算术（748,910 个 `-(uintN_t)` 站点，仅 3,977 个三元）。
- 状态为 488,844 个独立命名标量成员，直接访问；临时量全部局部化。
- **always-active 仅 111 个 supernode，全部是 EXTMOD difftest DPI thunk**
  （每个一次外部调用）；断言谓词（OP_ASSERT 6,243）留在普通活动门控图节点中，
  输入不变则不求值。

### firtool SV 缺陷结构普查（build/xs/rtl/rtl/*.sv，2,066 文件 238MB，token 级）

- SV 中 `case/casez/casex` = **0**（firtool 全部降为 if/else-if 链与布尔网）；
  `&&`/`||` = 0；`~` 共 130,180（FIRRTL `not` 仅 16,903，7.7×）。
- `~` 膨胀归因：1-bit const-arm mux 布尔化（`mux(c,0,x)→~c&x` 等）~38%；
  `eq/neq(x,1'0/1)→~x` 折叠 ~33%；显式 not 经扇出内联 ~19%；宽 eq(x,0)→`~(|x)` ~4%；
  断言降级（`~reset`、`~(pred)`、`~a|b` 蕴涵）~5%。**81% 为 firtool 引入，
  但均属机器层面等价或更优的 1-bit 形态，无动态消除价值**（与 NO00038 的
  可消除性普查结论一致，本次补上来源归因）。
- 断言/验证代码：6,920 个 `circt_chisel_ifelsefatal` intrinsic + 823 个 printf
  全部降为 `always @(posedge clock) if (~reset & ~(pred)) $fwrite/xs_assert_v2`；
  `` `ifndef SYNTHESIS `` 区域 70,063 行（1.54%），模拟器仍执行。
  巨型 else-if 链（511/520 分支 ×64/32 处）为 difftest 寄存器写端口优先级链
  （RenameTable_1.sv:4039 等），语义上优先级真实（同地址多端口可并发），不可消除。

### grhsim 热点单元溯源（NO00036 动态 profile + flow-b-final IR，双向归因 98.4%）

- 动态 op 模块分布：`core$backend` 69.87%、`frontend` 8.91%、`memBlock` 8.85%、
  **logEndpoint（difftest 计数器基础设施）5.28%**、l2top 2.76%、l3cacheOpt 1.92%。
- `not(and(...))` 132,318 个集中于 rob 26.7% / ctrlBlock 21.3% / rab 7.5%
  （rename/dispatch/rob 控制面真实优先级逻辑，不可消除）。
- **every-round 桶：315 个单元、7.74B 动态 op（6.73%），每轮（402,258 轮）无条件
  执行**，op mix：constant 42.4%（3.28B）、system.task 18.9%（1.46B）、dpi.call
  17.3%（1.34B）、and 5.4%、concat 3.4%、div 3.2%（250M，仿真存储模型地址计算）、
  state.read 2.4%、mux 2.1%。单元内容为断言端点簇（每个 26–48 个 xs_assert_v2）、
  仿真 RAM/MMIO/uart 模型、reset_sync/JTAG/debug-TAP 检查。

### 核心表示差异（本节点假设）

firtool 把 Chisel 验证 intrinsic 降为过程化 always 块后，grhsim ingest 将其变成
**每轮播种的 side-effect 任务单元**：谓词逻辑（及其常量实参）每轮重新求值，
不享受任何活动门控。gsim 的 FIRRTL 级 IR 中，同样的谓词是普通图节点，
由活动传播门控（输入不变则不求值），每周期固定成本只是 111 个薄 EXTMOD 调用。

量级估计：every-round 桶 6.73% 动态 compute op ≈ 运行时间 ~5%（compute 相 ~74%）。
NO00017 明确"仅 system/DPI 保留播种"、NO00020 只静默全边沿守卫单元
（341 个，跳过率 50.26%，残余正是每 posedge eval 的执行与 round-1 重放），
该桶是既有机制的明确残余。

### 假设（候选 A：side-effect 任务的数据输入静默）

对含 system.task/dpi.call 的 compute 单元，按**数据输入指纹**静默：单元体的
副作用决策只依赖其数据输入值与事件门是否触发；在事件门触发的 eval 内，
若数据输入相对上次实际执行逐位不变且上次执行未发火（无副作用），则跳过本体。
断言在未触发时占比压倒性（difftest 通过 ⇒ 全部 assert 通过），仿真服务模型
（ram/uart）空闲周期同理。round-1 重放中状态输入不可能变化（状态只在提交相
改变），只读状态的单元 round-1 必然可静默。

证伪标准：插桩测量 315 个 every-round 单元的激活中数据输入不变的比例，
若 <30% 则预期收益 <1.5%，放弃该机制换方向。

## 阶段记录

### BASELINE（2026-09-17）

- 对照（old）：NO00038 flow-layout2 二进制（`ptmp/no00038_alias_20260917/flow-layout2/emu/emu`，
  sha256 `aaf40bc4…bcbc`，即随 NO00038 提交 `17412f5` 接受的版本）。
  其正式成绩：三次 91.763 / 90.292 / 91.496 s，均值 **91.183667 s**。
- 测量口径：`scripts/benchmark_grhsim_ir.py`，CPU2 单核、XS_EMU_THREADS=1、
  100k cycles、waveform/commit/RAM trace 关闭，交替 old/new，止损 1.5×；
  预注册顺序与二进制哈希写入各次复测目录的 `preregister.json`。
- 等价门槛：`instrCnt=240349`、`cycleCnt=99996`、IPC 2.403586、末端 PC
  `0x80000c0c`、guest cycles 100001、退出码 0、NEMU 对拍无 mismatch。

### 成本解剖（gperftools 200Hz，NO00038 二进制，100k，18,457 样本，
### `ptmp/no00039_profile_20260917/gprof/analysis.txt` 与 `aggregate_profile.py`）

| 组 | 样本 | 占比 |
|---|---:|---:|
| compute_task 本体 | 12,487 | 67.65% |
| commit_task 本体 | 3,368 | 18.25% |
| 写助手（cpu_write_cell/scalar/direct_state_changed 等） | 971 | **5.26%** |
| evaluator（eval() 内发布/扇出走查/分派） | 700 | 3.79% |
| 播种单元 helper（315 个 system/DPI 单元） | 552 | 2.99% |
| 其余（非播种 helper / external / 其他） | ~379 | ~2.06% |

关键证据：

1. `cpu_write_cell<bool,1u>` 单函数 **2.28%**（420 样本；12,317 个调用站点），
   `cpu_write_scalar<bool>` 1.16%（214 样本；1,420 站点），
   `cpu_direct_state_changed` 0.78%。反汇编确认这些是 9 参数、6 寄存器压栈的
   **非内联**函数；未变化（约占 90%，NO00036 实测边界写回真实变化率 6.04%、
   提交端口变化率类似量级）调用仍支付完整调用+序言+合并计算约 25–30 条指令。
2. gsim 对照（生成代码事实）：提交变化检测**全部内联**在 subStep 巨型函数中
   （`cond=(new!=old); activeFlags[i]|=-(uint8_t)cond&mask;` 45,055 处 +
    guarded 变体），每个寄存器提交 4–6 条指令、零调用开销。
3. 播种单元残余（2.99% helper + 分派/写回份额）经分析多为语义强制：
   round-1 重执行的单元其门控时钟/状态输入在 round-0 提交相确实改变
   （如 unit 1078246 事件源为门控时钟，round-1 才稳定）；指纹静默捕获率低、
   语义风险高，**不作为主候选**（记录为已分析未实施方向）。
4. eval() 热点偏移定位为发布扇出走查内循环（`cpu_targets`/`cpu_memory_readers`
   逐目标 `or` 置位），pending 记录 311.88/publish，其中 88% 为真实变化——
   属事件驱动固有工作量，暂不可消。

### 候选 A：提交/采样写路径的就地快速路径内联 —— REJECTED（已撤销）

实现：`stage()`/`writeCell()` 在调用点内联"当前值==下一值"判定（36,299 站点），
慢路径仍调原 helper。聚焦测试通过，ELF text +0.14%。

筛选（`ptmp/no00039_fastwrite_20260917/screen-a/summary.json`，单对，均 NEMU PASS、
端点一致）：old 91.986 s / new **100.124 s，-8.85%**，方向显著为负。

失败原因（候选 A 二进制 gperftools 对照剖视，`gprof-a/`）：机制本身生效
（write_helpers 5.26%→1.31%，write_cell<bool,1> 样本 420→约 60），但被内联的
提交任务函数整体退化——commit_task 18.25%→**26.71%**（3,368→5,436 样本），
task_4490 单函数 +222%（302KB→410KB，+38% 指令数，跳转 +47%），
task_4479/4454/4495 text +4~19%；热点偏移 diffuse，判定为 GCC 在 300KB 级
巨型函数中对新增 36k 内联块（每块 7 个局部量+额外分支）的寄存器分配/块布局
恶化。与既有失败模式一致（NO00036 细粒度 -30.69%、NO00038 publish 内联 -1.06%、
sliceStatic 直译 -0.25%）：**本代码库的巨型函数体对发射形态微扰极度敏感，
纯粹的发射层搬运无法获益**。发射器改动已撤销（`git checkout cpu_emit.cpp`）。

### 候选 B（本节点主机制）：单元私有事件历史状态的直接采样

**表示差异证据**：firtool 把 FIRRTL 的时钟边沿语义降为 SV 显式 `always @(posedge clock)`
过程块，grhsim 为每个边沿守卫 op 物化事件历史状态（195,932 个逻辑
`__event_*`，经 NO00011/15/21 共享后 879 个物理代表元，全部经
`cpu_write_scalar<bool>` 走 shadow→pending→publish→扇出走查管道，每周期翻转两次）。
对照 gsim 生成代码事实：`step()` 单趟拓扑扫描中边沿完全隐式（无历史状态、
无发布回路），断言谓词是普通活动门控图节点，每周期固定成本仅 111 个薄
EXTMOD 调用。

**测量到的可捕获量**：每轮 publish 处理 311.88 条 pending 记录（100k 共
125,456,647 条），其中 compute 侧历史状态翻转贡献约 676 条/周期（338 个物理状态
× 2 次/周期，约占总量的 54%）；写侧每次采样是一次 9 参数非内联 helper 调用
（cpu_write_scalar<bool> 独占 1.16% 样本）。

**机制**：对**单元私有**的事件历史状态，把逐 op 的 staged 采样改为
**compute 单元块末尾（quiescence 守卫内侧）的一次就地比较直写**：
`{const bool cpu_dsample=<event>; if(cpu_at<bool>(cpu_obj_,off)!=cpu_dsample){
cpu_at<bool>(cpu_obj_,off)=cpu_dsample; [若 projected] cpu_direct_again=true; }}`。

**语义等价论证**（保守认证，全部满足才改写路径）：
1. 该状态的全部 objectRef 引用（含别名原像）均为同一 compute 单元内
   system.task/dpi.call op 的尾部历史位（objectRefPool 全量计数相等证明）——
   无任何数据读者；guards（cevent 局部量与 quiescence 守卫）在块首求值，
   读到的是轮初值，与 shadow 语义的轮内可见性一致；
2. 单元每轮至多执行一次（dispatch 消耗式），块尾直写的可见时点不晚于
   原 publish（轮末），且除本单元外无读者；
3. 激活扇出退化为仅自身 ActiveWord 位（调度器 `cpu_schedule.cpp:222-224` 为历史
   状态建的 commit 扇出），而属主单元本就被 roundSeeds 每轮播种
   （`cpu_schedule.cpp:221`），省略该自激活不可观测；
4. projection 语义由变化时 `cpu_direct_again=true` 逐字保持
   （等价于 publish 的 `again|=p.projection` 于变化记录）；
5. 同一单元同一事件值的重复直接采样幂等，去重为一条；
   quiescence 跳过 ⟹ hist==event ⟹ 采样本就是无操作，排流跳过一致。
其余历史（跨单元共享、commit 侧 541 个、事件单元内产出者 27 个）保持原路径。

**实现**（`wolvrix/lib/grhsim/backend/cpu_emit.cpp`，发射层）：
新增 `planDirectSampling()`（plan 期认证，复用 historyAliases_ 原像、
objectRefPool 引用计数、stateRanges_/stateTargets_ 扇出结构、unitProduced
事件不变量检查）；`stage()` 对认证状态跳过；单元块排流发射。
认证统计：338 个 compute 侧物理历史中 **311 个通过**（27 个因事件值非
Boundary/单元内产出拒绝），覆盖 13,763 个逻辑历史引用。

**筛选（单对，`screen-b/summary.json`，双端 NEMU PASS、端点一致）**：
old 92.358 s / new 91.354 s，**+1.087%**。方向为正但幅度处于秩次门边缘，
按既定模式堆叠两个同族机制。

**候选 B 二进制的对照 profile**（`gprof-b/`）：write_helpers 5.26%→4.69%、
seeded_helper 2.99%→2.63%、external（libc memcmp/memcpy）1.12%→0.82%；
evaluator 3.79%→3.87% 未降——扇出走查的残余量来自真实状态变化的必要激活，
历史记录多为单目标廉价记录。

### 堆叠候选 C1：cpu_publish 发布循环的 restrict 卫生 —— REJECTED

设计与动机：发布/扇出走查循环内，`cpu_flags[...] |= ...` 的 uint8_t 存储在
TBAA 下可别名 pending 记录与 targets 表，GCC 被迫逐目标重载记录边界与成员
指针（反汇编实测每迭代两条成员重载）。将 obj/shadow/flags/arms/dirty/
pending/targets/readers/readoffs 全部转为 `__restrict` 局部指针，语义中性。

筛选（`screen-bc1/summary.json`，new = B+C1）：old 90.353 s / new 91.521 s，
**-1.293%**；B 单独 +1.087%，即 C1 净损约 2.4pp，与候选 A 同属发射形态扰动
负收益模式。已撤销（publish 发射恢复原状）。

### 堆叠候选 C3：播种单元 boundary 输入的前层聚簇 —— 已分析未入栈

静态测量（IR 双向归因）：315 个播种单元的全部操作数覆盖 61,711 个值，
≤64 位部分约 **419 KB**，远超 L1D（48 KB）；并入前层会稀释 NO00038 D2 的
提交端口热层，尺寸经济性不成立。实现曾落地并通过聚焦测试，未纳入最终堆叠
（cpu_layout.cpp 改动已撤销）。

### 最终堆叠：候选 B 单独（单元私有事件历史直接采样）

### 工程注记（筛选路径）

- 映射 checkpoint 重发射（`make reemit_grhsim_ir`，~64 s）可用于发射层变更的筛选；
  **布局层变更（C3）会使 checkpoint 的 cpu.layout 校验失败，必须走完整 SV 流程**。
- `XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=1` 路径在本工作区产生退化的任务
  分区（出现 22–31 MB 巨型任务文件，GCC -O3 单文件 >25 min 无法编译），
  与正式 SV 路线的分区不一致，**不能用于筛选对照**（已记录在案，弃用该路径的
  测量）。C3 在入栈前已因尺寸经济性撤销，无需该路径。
- 首次正式全流程因未显式设置 `XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0`
  （NO00038 环境的既有约定），`cpu.st.pack-emit-functions` 走默认无打包路径，
  产生 21–31 MB 巨型任务文件，编译在 task_522 上耗尽 1800 s 被记
  `TIMEOUT_KILLED`；产物已隔离删除。修正后重跑。
- 第二次正式全流程（含 batch-count=0）生成 688.14 s、编译 206.99 s 通过，
  但复核 diff 发现已否决的 C1（publish restrict）仍在工作区——该正式构建
  实为 B+C1 而非纯 B，其预注册复测已终止作废（不计入任何判定）。
  撤销 C1 后第三次重建正式流，预注册数据以最终有效版为准（被终止的
  B+C1 复测目录已删除，不作为任何证据）。

### 最终堆叠：候选 B 单独（单元私有事件历史直接采样）

**门槛**：完整 SV→C++ 生成 **681.43 s**（<1800 s，完整 SV 路线、
`XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0`，非 checkpoint 恢复）；
fresh 编译 **205.45 s**（<1800 s）。被测二进制
`ptmp/no00039_fastwrite_20260917/flow-final/emu/grhsim-compile/emu`
sha256 `8430a89738b3e956a8d495d15c15c997ecfe09acf1d842982368c2b216a1384a`。
ELF text 90,928,600 B（较 NO00038 二进制 −8,432 B）。

**6 次交替复测**（`ptmp/no00039_fastwrite_20260917/formal/summary.json`；
old 为 NO00038 flow-layout2 二进制，预注册顺序 old1/new1/old2/new2/old3/new3；
CPU2、单核、XS_EMU_THREADS=1、100k cycles、waveform/commit/RAM trace 关闭）：

| run | old Host (s) | new Host (s) | 退出 | 端点 |
|---|---:|---:|---|---|
| 1 | 92.147 | 91.312 | 0 | 240349/99996/100001/0x80000c0c |
| 2 | 91.746 | 90.179 | 0 | 同上 |
| 3 | 92.942 | 91.406 | 0 | 同上 |

六次均 NEMU 对拍通过、`instrCnt=240349`、`cycleCnt=99996`、IPC 2.403586、
末端 PC `0x80000c0c`、guest cycles 100001，退出码 0，无 mismatch。

- old 均值 **92.278333 s**（样本 SD 0.608720）、new 均值 **90.965667 s**
  （样本 SD 0.682893），降低 **1.422508%**。
- `max(new) 91.406 < min(old) 91.746`，Mann-Whitney U=0，单侧精确 p=0.05，
  Cohen d=-2.03，Cliff's delta=-1.0，**秩次判据通过**。
- 按新均值计算，GrhSIM-IR 为归档 gsim 46.965 s 的 **1.937093×**
  （上一节点 NO00038 为 1.941042×）。

## 最终判定：ACCEPTED

保留机制：候选 B（单元私有事件历史状态在 compute 单元块末尾的一次就地
比较直写，替代逐 op 的 shadow/pending/publish 采样），311 个物理历史状态
（覆盖 13,763 个逻辑历史引用）经保守认证后改写路径。被否决尝试：
候选 A（写路径快速路径内联，-8.85%，GCC 巨型函数退化）、候选 C1
（publish restrict 卫生，-1.29%）、候选 C3（播种单元 boundary 前层，
419 KB 尺寸经济性不成立未入栈），过程与证据如上，源码均已撤销。

**语义约束**：plan 期认证（单一 compute 单元引用闭包 + 无数据读者 +
纯自激活扇出 + 事件值单元外不变量）保证轮内可见性与投影/收敛语义逐字不变；
IR、分区、调度、提交路径不变；冻结 GRH、GRH pass、XiangShan 与测试源码未改。
触发条件为通用结构特征（op 种类/引用闭包/位宽/两态），不含模块名称匹配。

**后续方向**：commit 侧 541 个历史状态的同类直接采样（需先解 commit task 内
读写在轮内的可见性约束，本节点保守排除）；提交簇残余成本（profile ~19%）
为逐周期提交固有工作量；残余差距主要构成仍是求值量（2 evals × 2 rounds
结构已由既有结论冻结）。

## NO00037–NO00039 三节点复盘

- **当前最佳**：NO00039 90.965667 s（gsim 归档 46.965 s 的 **1.937×**；
  NO00037 93.280 → NO00038 91.184 → NO00039 90.966）。
- **已排除方向**：firtool 布尔网络消除（优先级链/mux 恢复/极性/布尔归约/
  concat 拆分/值守卫，可证上限 <0.5% 动态 op）；sliceStatic 直译（-0.25%）；
  发射层内联微扰家族（写路径快速路径内联 -8.85%、publish 内联 -1.06%、
  publish restrict -1.29%）——巨型函数体对发射形态高度敏感，纯发射搬运
  持续证伪；播种单元指纹静默（round-1 重执行多被门控时钟 settling 与
  提交相强制，捕获率不达标）；细粒度激活（-30.69%，维持否决）；
  播种单元 boundary 前层（419 KB 尺寸不成立）；flat-GRH 恢复路径作筛选
  对照（分区退化，不可比）。
- **剩余主要差距**：compute ~68%（弥漫布尔/mux 求值网络，firtool 形态已证
  不可消）+ commit ~19%（逐周期提交固有工作）+ evaluator ~3.9%；
  2 evals × 2 rounds 轮次结构冻结，残余差距由求值量与逐周期提交构成。
- **低收益微调检查**：三节点收益 6.59% → 1.27% → 1.42%，收益递减但仍持续；
  机制均围绕提交/发布/状态访问路径。下一节点应回到表示差异中的大份额
  机制（commit 侧 541 个历史状态、大状态提交簇 4096 计数器族、求值量
  结构），避免继续边角微调。

## 复现产物

临时生成代码、二进制、日志和 benchmark 结果位于
`ptmp/no00039_firtool_census_20260917/`（firtool SV/FIRRTL 普查）、
`ptmp/no00039_hotunits_20260917/`（热点单元归因与认证原型）、
`ptmp/no00039_profile_20260917/`（old 二进制 profile 与分析脚本）、
`ptmp/no00039_fastwrite_20260917/`（各候选流、筛选与正式复测），均未加入提交。
正式复测预注册与汇总：`ptmp/no00039_fastwrite_20260917/formal/`。

基线 commit：wolvrix 子模块 `17412f5`（NO00038，`feat: tier commit-hot state
layout and restrict task buffer access`）；工作区实验版本差异为本报告随附提交
（`lib/grhsim/backend/cpu_emit.cpp`、`tests/grhsim/test_cpu_emit.cpp`）。
输入：`testcase/xiangshan/ready-to-run/coremark-2-iteration.bin`
（sha256 c764afb8…）、`riscv64-nemu-interpreter-so`（sha256 094c1c4a…）。

聚焦回归：

```text
source ./env.sh
make --no-print-directory py_install
make --no-print-directory test_grhsim_cpu_emit
```

候选 A 筛选：`ptmp/no00039_fastwrite_20260917/screen-a/summary.json`。
候选 B 筛选：`ptmp/no00039_fastwrite_20260917/screen-b/summary.json`。
B+C1 筛选：`ptmp/no00039_fastwrite_20260917/screen-bc1/summary.json`。
正式 6 次复测：`ptmp/no00039_fastwrite_20260917/formal/summary.json`。
