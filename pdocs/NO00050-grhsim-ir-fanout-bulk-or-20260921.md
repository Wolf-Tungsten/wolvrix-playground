# NO00050: 表达式粗化门槛（否决）+ compute 侧 fanout 发布批量 OR

日期：2026-09-21。节点状态：**FAILED（用户人工判定，2026-09-21）**。

> **判定登记**：本节点机制（fanout 发布批量 OR）已走完整筛选与正式流程并一度
> 判定 ACCEPTED（数据见下，全部保留）；2026-09-21 经**用户人工判定**本节点为
> FAILED（按 goal 协议，FAILED 只能由用户人工判定并登记），ACCEPTED 判定撤回。
> 候选代码全部回退：wolvrix `1f6761a` 经 revert（`7fd134e`）恢复至 `54d6e74`
> 零差异；普查工具保留（`scripts/grhsim_fuse_chain_stats.py`、根 Makefile
> `probe_grhsim_ir_codegen` 探针目标）。当前最佳回退至 NO00049
> （70.419333 s，gsim 的 1.499839×）。四个被否决方向（P4/P3/memWrite arming/
> 粗粒度 256）的否定数据为独立实验结论，不随本判定失效。

## 节点输入与假设

承接 NO00049 移交的 IR 表达形态路线（P 路线）：P1 used-bits 已完成；
本节点首先对 **P4 表达式粗化/树状发射** 执行立项门槛验证，预注册决策规则为：

1. **门槛 1（clang 微实验）**：取热点 supernode 生成体做单用链手工融合改写，
   对比生产编译器（clang 22, `-std=c++20 -O3`）产出的指令数；净回收 <3%
   则不立项，回退 P3（宽值 `_BitInt` 表示）。
2. **门槛 2（普查）**：在 NO00049 checkpoint 上量化 unit 内单用透明链覆盖率。
3. P3 同样先量池再立项；均不达标则回退 NO00048 移交的框架级候选
   **memWrite 端口 arming**（预估 1–3%）。

## BASELINE

- 对照（old）：NO00049 正式二进制 `ptmp/no00049_used_bits_20260920/flow-final/emu/emu`
  （sha256 `10a06e88ca2b97ff15a33005d8df4a732ed7b9dafba3db987ed462ec06c28d93`），
  预注册比较值 **70.419333 s**。
- 基线 commit：wolvrix `54d6e74`；根仓库 `1e9a2e9`。
- 等价门槛：`instrCnt=240349`、`cycleCnt=99996`、IPC 2.403586、末端 PC
  `0x80000c0c`、guest cycles 100001、退出码 0、NEMU 对拍无 mismatch。
- 测量口径：`make benchmark_grhsim_ir`，CPU2 单核、XS_EMU_THREADS=1、100k
  cycles、trace 全关、posix_fadvise 驱逐、预注册 old1/new1/old2/new2/old3/new3；
  仿真止损 1.5×（105.6 s）。
- checkpoint：`ptmp/no00049_used_bits_20260920/flow-final/xiangshan_grhsim_ir.json`。

## 门槛 2：单用透明链普查（scripts/grhsim_fuse_chain_stats.py）

在 NO00049 checkpoint（post used-bits）上，以"producer 为单结果纯 compute op、
值恰有 1 个消费者、非 boundary、producer/consumer 同 leaf partition（supernode）"
为可融合判据：

- compute 任务内 compute op（单结果）共 **3,275,066**；可融合 **2,282,701（69.70%）**。
- 其中 >64 位宽值仅 **16,347（0.72%）**；4 态值 0。
- 链内部（消费者自身亦可融合）**1,627,977（71.32% of fusible）**——链深而非孤对。
- supernode 粒度覆盖率（n=71,832，≥8 op）：中位数 0.909、均值 0.881。
- producer kind 分布：透明数据族（and/or/not/add/sub/xor）55.44%、结构族
  （mux/concat/bitSelect/slice/assign）29.95%、非透明族（eq/logicNot/reduce/
  sliceDynamic 等）其余。

静态上界看似巨大，但它是"语句数"口径，不是机器指令口径——见门槛 1。

## 门槛 1：clang 22 融合微实验（REJECTED）

**方法**：文本级保守融合器（`ptmp/no00050_expr_coarsen_20260921/text_fuse.py`，
仅在顺序语句 run 内、单写单读、RHS 纯白名单）把 `cpu_at<T>(cpu_local,OFF)=RHS;`
单用语句内联进消费点，模拟 IR 层树状发射交给 clang 的输入形态；用根 Makefile
新目标 `probe_grhsim_ir_codegen`（生产编译器+生产参数编译单 TU 到汇编，不链接）
对比原始/融合体的静态指令数（直码控制流不变，静态差=每次激活的动态差）。

**样例覆盖全部体形态**（NO00049 flow-final/model + 当前 emu 反汇编交叉验证）：

| 任务 | 形态 | 融合语句数 | orig→fused 指令 |
|---|---|---:|---|
| task_1000 | 干净 1 位链（0 栈引用，1.65 inst/语句） | 491 | 1561→1561（**0.00%**） |
| task_4027 | 同上 | 134 | 15566→15566（0.00%） |
| task_4046 | 混合 | 2 | 5410→5410（0.00%） |
| task_70 | 寄存器压力溢出（5466 栈引用） | 1 | 23074→23074（0.00%） |
| task_4038 | system/$fwrite 端点 | 280 | 17069→17019（−0.29%） |
| task_4041 | 端点 | 46 | 4100→4081（−0.46%） |
| task_3845/3842/1927/2946 | 溢出重纯 compute | 10/18/14/20 | **全部 0.00%**，栈引用不变 |

**判定：P4 语句融合净回收 ≈ 0%，REJECTED。** 机理：

1. clang 22 对 `cpu_local` 槽位完全 SROA/mem2reg 提升（task_1000 全函数 0 条
   栈数据引用；每 op 语句编译为 1 条逻辑指令 + 操作数 load），逐 op 语句与
   嵌套表达式在 LLVM IR 层面是同一 SSA 图，折叠结果逐指令相同。
2. 同宽 mask 链（`grhsim_trunc_u64`/`static_cast` 包装）被 InstCombine 完全折叠；
   1 位 and/or 链在 bool 上直译，无残余。
3. 溢出重任务（task_3845 等，栈引用 30–50%）的栈流量是 boundary 读取长活跃
   范围的寄存器压力溢出；单用链融合不缩短这些活跃范围，栈引用逐条不变。
4. system/DPI 端点任务（perf 占比 4.16%）的成本在条件求值与边界读取，
   不在表达式形态。

旁证（新鲜 perf，100k，69,377 样本）：compute 任务 64.51%、commit 16.10%、
system 4.16%、eval() 3.77%、cpu_write_cell 族 ≈2.9%。

## P3 宽值池定量（REJECTED）

`scripts/grhsim_used_bits_stats.py` 在 NO00049 checkpoint 上复量：剩余 >64 位
compute op **26,679**，宽值字工作量总计 **98,044** 词（相对 3.27M compute op
可忽略；NO00049 已把可降级主体收窄到 ≤64）；宽字操作调用站点集中在冷任务
（task_1021–1025 各 0.02–0.03%）。**P3 `_BitInt` 表示池 <0.5%，REJECTED。**
P2 位段分裂与 P3 同池，连带否决。

## 机制：单写者数组 memWrite 端口 arming（NO00048 移交候选 v2）

**池证据**（NO00048 测量，当前构建复核结构不变）：mw_gate 3.62B/100k
（每 eval ~36k 个 memWrite 端口边沿 guard 打开，82% enable 为假空转）；
当前 checkpoint 普查：memWrite 族 op 37,800 个、被写 state 53,354 个、
**单写者 state 52,131（97.7%）**。

**语义**：单写者数组的 memWrite 端口，其 enable/address/data/mask 四操作数
自上次求值未变时，重新求值写入相同单元相同数据 = 幂等无操作（单写者下无
写-写序可保）；跳过求值不改变任何可观测行为。端口 history 采样在 armed
路径无条件保留（沿用 NO00018 既有结构）。初始 `cpu_pflags.fill(255)` 保证
每个端口至少求值一次，覆盖初始化/镜像装载后的首边沿。

**实现**（wolvrix/lib/grhsim/backend/cpu_emit.cpp）：

- `armableCommitPort` 扩展接受 `core.state.memWrite`：目标 state 全写族单写者、
  array 元素为 ≤64 位二态标量（writeCell 路径）、前 4 个操作数满足与
  regWrite 相同的 boundary/二态/≤64/非别名/生产者白名单约束。
- `planPortArms` 增加全写族单写者统计；端口序号按两趟分配
  （先 regWrite/latchWrite 后 memWrite），既有 regWrite 字节组与
  compact walk 64 端口资格在无 memWrite 合格时逐位不变。
- armed 求值区按 op kind 分派：memWrite 体为
  `if(enable && addr<count) writeCell(...)`（guard/enable/bounds 检查不变，
  arm 位只决定是否跳过幂等写）；事件采样在 armed 前置循环无条件执行
  （`sampleEvents(op,1)` 与 commit() 内路径逐语句等价）。

（结果待补：实现计数、筛选与正式复测。）

## 尝试一：memWrite 端口 arming（REJECTED，池覆盖塌陷）

按上述语义与结构实现（wolvrix 侧 `armableCommitPort`/`planPortArms`/armed 求值区
三处扩展，两趟序号分配保持既有 regWrite 字节组逐位不变），聚焦测试
（mapping/schedule/emit）通过，reemit 计数：`port_arm_mem_ports=1192`、
`port_arm_ports=101089`、`mem_guard_hoist_runs=1219 sites=32748`。

**池塌陷分析**（checkpoint 静态普查修正 NO00048 的 state 粒度口径）：37,208 个
memWrite op 中，**31,942（85.8%）失败于多写者**——写 op 集中在 1,223 个多写者
state 上（寄存器堆/多端口 bank，单 state 挂 8–352 个写 op），单写者数组的 op
覆盖率只有 3.2%。NO00048 的">1 写 op 的 state 仅 1,223 个"是 state 粒度，换算到
端口粒度后 1–3% 的池预估不成立。多写者排除是语义必需的（写-写序：跳过时钟沿
上 enable/data 不变的重复写会丢失对其它写者同单元写的覆盖）。

**筛选两票**（old=NO00049 正式，new=flow-v1）：第一票 +0.862%（old 70.287 /
new 69.681），第二票 **+0.013%**（old 70.216 / new 70.207）——两票不一致，
信号不可复现，处于单对噪声带内。**REJECTED**。候选代码已回退（wolvrix 恢复
`54d6e74` 零差异）；实现经构建+聚焦测试+两次等价运行验证为语义正确，仅收益
不足。教训：arming 类机制的池估算必须以**端口/op 粒度**的覆盖率（而非 state
粒度）为准。

## 尝试二：粗粒度 supernode（max-op 128→256，筛选中）

**动机**（新鲜热点加权语句构成解剖，纯 compute 任务）：局部计算语句 38.6%、
**fanout+端口 arm 发布 OR 约 24%**、boundary 写回（changed 比较+存储）16.4%、
缓存读 8.2%、changed 声明约 9%（多被 DSE）、concat 物化/read_offsets/骨架约 3%。
物化发布层（fanout+写回+arm）合计 ~40% 的 compute 侧语句，其数量正比于
boundary 值数与 unit 数。gsim 的方向（更细 supernode，近零固定成本）在
NO00036 已证对我们不成立（固定成本放大 30.69%）；**反方向（更粗粒度）从未
测试**：unit 数减半直接削减固定成本与 boundary 发布点，代价是每次激活的重算量
翻倍（71% 零产出激活的浪费同步放大），净符号未知——正是筛选实验回答的问题。

（结果待补。）

## 尝试二结果：粗粒度 supernode（REJECTED）

`max-op-in-compute-supernode 128→256`（remap 重建映射，emit 选项不变）：
筛选对 old 69.961 / new 76.857 = **−9.857% 显著回退**。每次激活的重算量翻倍
（零产出激活浪费同步放大）压倒 unit/boundary 减半的固定成本节省。结合
NO00036 的更细方向 −30.69%，**粒度旋钮两侧均为负，128 已是局部最优，该方向
永久关闭**。共激活 unit 精确合并且不增重算（理论上零代价）的静态普查：
task 根分区直接孩子层仅 2 组可合并（0.1%），池不存在。

## 机制：compute 侧 fanout 发布批量 OR（gsim 形态对齐）

**来源**（gsim 生成代码对照，`build/xs/gsim/gsim-compile/model/SimTop*.cpp`）：
gsim 的激活发布为 `activeFlags[i] |= cond << k`（单指令位移注入）与
**`*(uint64_t*)&activeFlags[8g] |= -(uint64_t)cond & SPARSE_MASK64`**——一个
变化值对 8 字节窗口内全部前向目标一条批量 OR。我方为逐字节
`cpu_flags[B] |= (-(u8)changed) & M`（热加权语句占比 ~21%，加端口 arm 共 ~24%）。

**池普查**（NO00049 flow-final/model 文本）：fanout/arm OR 行 651,033 条，
按 (changed 值, 对齐 8 字节组) 归并后为 348,673 组（组均 1.87 行）；热点加权
成本模型（当前 ≈1.5 链 + 3 载存 每字节 vs 批量 4.5 每 8 字节窗口）估计该族
指令 **−34.8%**，折算全程序预计 2–4%。无分支引入，不触发 NO00047 的 clang
控制流拆分惩罚。

**实现**（wolvrix/lib/grhsim/backend/cpu_emit.cpp）：

- 新增 `emitFlagOrs`：(offset, mask) 目标按对齐 8 字节窗口归并；窗口内 ≥2
  字节时发射 `{u64 tmp; memcpy(&tmp, arena+base, 8); tmp |= (-(u64)cond) &
  MASK64; memcpy(arena+base, &tmp, 8);}`（memcpy 保持 uint8 别名规则内，
  编译为非对齐 u64 载存对，与 gsim 形态一致）；单字节窗口保留原逐字节形式。
- `activate()` 的激活目标与 arm 目标（同 arena 时合并）、`armPorts()` 的
  pflags 目标全部改经 `emitFlagOrs`，全部调用点自动覆盖。
- 计数器 `fanout_bulk_groups/fanout_bulk_bytes` 入 packSummary。

**筛选结果**（old=NO00049 正式 70.419333 s 锚点，new=flow-v3 reemit 构建）：

- emit 计数：`fanout_bulk_groups=58,427`、`fanout_bulk_bytes=181,932`（组均 3.11
  字节），生成代码批量站点 58,405 处；同窗口相邻站点由 clang 进一步合并载存。
- 第一票：old 71.262 / new 70.399 = **+1.211%**；第二票：old 70.803 /
  new 69.737 = **+1.506%**。两票一致且越 +0.4% 门，进入正式门。

**正式门**（驱动 `ptmp/no00050_expr_coarsen_20260921/formal.sh`）：

- 聚焦测试：cpu_mapping / cpu_schedule / cpu_emit 全通过。
- 完整 SV→C++ 生成：**730.83 s**（<1800 门），exit 0。
- md5 对拍：flow-final 与筛选 flow-v3 的 model 4,7xx 文件摘要全等
  （FINAL == screening model）。
- HDLBits DUT=001 回归：通过。
- fresh 编译：**202.05 s**（nproc=32，<1800 门），exit 0。
- 6 次交替复测（预注册 old1/new1/old2/new2/old3/new3）：
  - 正式第一轮：old {70.085, 70.137, 70.611} 均值 70.277667 /
    new {69.675, 70.148, 69.592} 均值 69.805000，+0.6726%；
    **秩次门未过**（max(new) 70.148 > min(old) 70.085，U=2、单侧 p=0.2）——
    该窗口机器偏快（old 全低于 70.419 锚点），均值方向与两票筛选一致但幅度
    被窗口噪声压缩。按协议"交错后仍无法与噪声区分时须加跑"加跑第二轮。
  - 六次全部 NEMU 对拍通过（等价门槛由 benchmark 脚本内置校验）。
  - 第二轮结果见最终判定节。

## 最终判定：FAILED（用户人工判定，2026-09-21）

**判定登记**：本节数据为撤回前 ACCEPTED 流程的完整记录，全部保留。机制曾通过
筛选两票与三轮正式交替（第二、三轮秩次门通过），但 2026-09-21 经用户人工判定
本节点 FAILED，ACCEPTED 撤回；候选代码全部回退（wolvrix `1f6761a` 经
`7fd134e` revert，与 `54d6e74` 零差异），当前最佳回退至 NO00049。

**机制**（已回退）：compute 侧 fanout 发布批量 OR——`activate()`/`armPorts()` 的
(offset, mask) 目标按对齐 8 字节窗口归并为单条 memcpy 形式 u64 OR
（窗口 ≥2 字节时），无分支、与 gsim 的 `*(uint64_t*)&activeFlags[g] |=
-(uint64_t)cond & MASK` 形态对齐。

**筛选**：两票 +1.211% / +1.506%。

**正式 6 次交替复测**（均预注册 old1/new1/old2/new2/old3/new3，posix_fadvise
驱逐，100k cycles，CPU2 单核；每次运行 endpoint 均为 instrCnt=240349、
cycleCnt=99996、guest cycles 100001、末端 PC 0x80000c0c、退出码 0、
NEMU 无 mismatch）：

| 轮次 | old（3 次） | new（3 次） | 提升 | 秩次门 |
|---|---|---|---|---|
| 1 | 70.085/70.137/70.611（均值 70.277667） | 69.675/70.148/69.592（均值 69.805000） | +0.6726% | 未过（max(new)>min(old)，U=2，p=0.2；该窗口机器整体偏快压缩幅度） |
| 2 | 70.022/69.751/69.911（均值 69.894667） | 69.544/69.341/69.234（均值 **69.373000**） | +0.7464% | **过**（max(new) 69.544 < min(old) 69.751，U=0，p=0.05） |
| 3（确认） | 70.371/70.090/69.995（均值 70.152000） | 69.666/69.440/69.449（均值 **69.518333**） | +0.9033% | **过**（max(new) 69.666 < min(old) 69.995，U=0，p=0.05） |

第一轮秩次门未过后按协议加跑，第二、三轮连续通过且方向与两票筛选一致
（四轮均值效应量 +0.7%~+1.5%）——据此曾判定收益真实，该判定已于 2026-09-21
被用户人工判定 FAILED 撤回。生成代码侧佐证：fanout 热点
task_70 静态指令 23,074→18,661（−19.1%）。

- 完整生成 730.83 s、fresh 编译 202.05 s（nproc=32）均 <1800 s 门；
  md5 对拍（flow-final == 筛选 flow-v3）、HDLBits DUT=001 回归通过。
- 距 gsim（撤回前口径）：以第三轮 new 均值 69.518 s 对归档 46.965 s =
  1.480239×；判定撤回后该锚点作废，当前最佳回到 NO00049 的 **1.499839×**。
- 提交与回退：wolvrix `1f6761a`（cpu_emit.cpp +59/−7）与根仓库 `143ef17`
  （Makefile probe 目标、普查脚本、本报告、索引）；FAILED 判定后 wolvrix
  经 `7fd134e` revert 恢复 `54d6e74` 零差异，根仓库普查工具（
  `scripts/grhsim_fuse_chain_stats.py`、`probe_grhsim_ir_codegen`）保留。

## 节点复盘与移交

- 本节点否决四个方向（均留数据）：P4 表达式树状发射（clang 22 已完全回收，
  六种体形态融合净差 0.00%–−0.46%）；P3 `_BitInt` 宽值（NO00049 后剩余
  26,679 op / 98k 词，<0.5%）；memWrite 端口 arming（单写者 op 覆盖仅 3.2%，
  两票 +0.86%/+0.01% 不一致）；粗粒度 supernode 256（−9.86%，与 NO00036
  的更细 −30.69% 共同关闭粒度旋钮）。
- **方法学确认**：(a) NO00047 移交的"先生产编译器微实验"再次避免一次空
  实现（P4 普查静态上界 69.7% 看似巨大，微实验 10 分钟内证伪）；(b) 池估算
  必须按 op/端口粒度而非 state 粒度（memWrite arming 教训）；(c) gsim 生成
  代码（`build/xs/gsim/gsim-compile/model/`）是最直接的形态对照源——本节点
  机制直接来自逐行读 gsim 输出。
- **剩余池**：compute 任务体 hotness 加权语句构成——局部计算 38.6%、
  fanout+arm 发布 ~24%（本节点批量 OR 曾回收其约 1/3 成本，已随 FAILED 回退）、
  boundary 写回 16.4%、缓存读 8.2%；71% 零产出激活池仍受 clang 控制流惩罚封锁。
- 后续候选：写回层（changed 比较+存储 16.4%）的批量/位打包（按 u64 窗口批量
  比较与回写）；提交侧 commit 任务体 16.1% 中 write_cell 调用形态
  （~93 cyc/端口评估，NO00047 归因）。
- 下一节点 old 对照（FAILED 回退后）：`ptmp/no00049_used_bits_20260920/flow-final`；
  预注册比较值 **70.419333 s**（NO00049 正式 new 均值）；checkpoint：
  `ptmp/no00049_used_bits_20260920/flow-final/xiangshan_grhsim_ir.json`。
