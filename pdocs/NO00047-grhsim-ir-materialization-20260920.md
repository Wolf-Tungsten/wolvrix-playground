# NO00047：微结构解剖与两条机制证伪（失败节点）

日期：2026-09-20。最终判定：**FAILED（失败节点，用户人工判定）**。

按 2026-09-20 规则，`FAILED` 只能由用户人工判定并登记：本节点两条机制路线
——compute 单元物化门（fanout gate）三变体全部回归证伪，helper ABI 精益化
（lean write）正式复测收益 +0.378% 幅度不足——经用户评估"提升太小"后判定
节点失败。**候选代码已全部回退**：wolvrix 子模块与基线 `ecb8190` 零差异
（`git diff` 为空），根仓库 Makefile/管线脚本回退，仅保留普查工具与本报告。

## 背景与节点方向

承接 NO00046 的移交结论（发射层微优化已低于噪声底；剩余池为框架级），并按
用户建议**强化微结构特性分析**：对 NO00045 正式二进制（sha256 `18964d9b…`）
做新鲜 perf 归因、对生成代码做静态/动态指令形态解剖、对 gsim 参考实现做
执行模型结构对比，据此提出并验证机制。

## 微结构深化分析（2026-09-20）

### A. 新鲜 perf 归因（100k，CPU2 单核，trace 全关，fadvise 驱逐）

`ptmp/no00047_uarch_20260920/rec_grhsim.data`（-F 999，cycles+branch-misses）：

| 类别 | cycles | branch-misses |
|---|---:|---:|
| compute tasks（<4200） | 64.49% | 38.69% |
| compute helper | 4.70% | 6.88% |
| commit tasks（42xx/43xx） | 17.56% | 39.68% |
| eval()（派发+内联 publish） | 4.32% | 6.03% |
| cpu_write_cell | 4.15% | 2.42% |
| cpu_direct_state_changed | 1.08% | 1.81% |
| libc memcmp/memcpy | 0.90% | 0.59% |
| cpu_write_scalar | 0.64% | 0.84% |

perf stat 组 A：cycles 370.198G、instructions 513.953G（IPC 1.388）、
stalled-frontend 163.399G（44.1%）、branch-instr 22.271G、misses 3.887G。
最热 commit 任务 task_4215 反汇编（68,184 条指令）：push 8,940（13%）、
call 4,672、分支 9,363——每次开火调用 10 参数 write_cell 的栈参数/序言
是主要形态开销；commit 侧摊销 **~93 cycles/端口评估**（误预测 ~29 cyc/端口
+ L1 miss + 调用体主导）。

### B. gsim 执行模型结构对比（reference/gsim 源码调查）

- gsim 是**单趟拓扑序扫描**：`step()` 无 round/收敛循环
  （`reference/gsim/src/cppEmitter.cpp:1107-1123`）；活动位 per-supernode
  （84,643 个，max-size=2 极细粒度），扫描即清。
- **寄存器提交不是独立阶段**：`reg = reg$NEXT` 是 supernode 体内一条普通
  赋值，借 dep 边排序骑在 step 边界上（Node.cpp:184-194）；无 pflags 走查、
  无 pending/publish 物化；memory 写直接内联 `mem[addr]=data`。
- 变化检测只对跨 supernode 扇出的 boundary 节点（`$old$` 备份+比较），
  激活传播为无分支批量 OR（同字节前向目标融合为 64 位批量 OR）。
- 每 eval 指令预算：gsim ≈ 925k vs IR 2.57M（2.78×）。结构归因：IR 的
  op 分解更细（~2×）× 物化协议层（commit 走查/publish/pending/轮次，
  gsim 完全没有，约占 IR cycles 的 25%+）。
- gsim IPC 仅 0.775（代码/数据体积巨大，取指/数据 cache 主导）；IR 绝对
  误预测量已低于 gsim（3.89G < 4.72G），差距纯为指令数。

### C. compute 任务体指令形态解剖（`scripts/grhsim_compute_anatomy_stats.py`）

compute 4,199 任务 / 33,616 单元，静态行数 per 单元均值：local_write 78.5、
writeback_tracked 21.9、fanout flags OR 16.4、cached_read 15.8、
changed 声明 10.0、fanout pflags OR 4.0——物化族（写回+扇出+声明）≈
单元体的 40%。

### D. 分析性证伪清单（未消耗性能运行即排除）

- **同字节 fanout OR 合并**：反汇编证实编译器已合并（task_1000 的
  `flags[2409]` 两 OR → load+shl/or 链+单 store，`(-(u8)ch)&16` → `ch<<4`）。
- **宽 OR 跨字节打包**（`scripts/grhsim_fanout_span_stats.py`）：连续运行
  长度 1 占 94%（412,049/447,430），估算收益 −0.1%。
- **打包写回**：fanout 类大小分布 size=1 占 66%、≤2 占 86%
  （`scripts/grhsim_fanout_structure_stats.py`），小类主导下收益为负。
- **cpu_local 零初始化消除**：反汇编证实编译器 DSE 已完全消除
  （task_1000 全函数 0 条 pxor/movaps/rep-stos）。
- **条件存储写回 / 级别感知 eval / dispatch 位图 / 任务内联**：
  收支核算均 <0.7% 或有结构风险（间接分派误预测、LTO 编译时间），
  低于 3v3 分辨下限。

### E. 动态物化计数（NO00045 dyn-stats 归档复核）

grp_pub=910,196,921/run（每单元激活的扇出块执行），grp_fire=262,486,735
（28.8%）——**71.2% 的扇出物化块执行为零变化空转**（≈648M 块/run ≈
26G 指令池，v1 实测指令 −3.6% 证实池子存在）。

## BASELINE（2026-09-20）

- 对照（old）：NO00045 正式二进制（`ptmp/no00045_uarch_20260919/flow-final/
  emu/emu`，sha256 `18964d9b…`，启动时核对一致），正式三次 new 均值
  74.094333 s。
- 基线 commit：wolvrix 子模块 `ecb8190`；根仓库 `02013c8`。
- 等价门槛：`instrCnt=240349`、`cycleCnt=99996`、IPC 2.403586、末端 PC
  `0x80000c0c`、guest cycles 100001、退出码 0、NEMU 对拍无 mismatch。
- 测量口径：`make benchmark_grhsim_ir`，CPU2 单核、XS_EMU_THREADS=1、
  100k cycles、trace 全关、交替 old/new、posix_fadvise 驱逐；
  预注册 old1/new1/old2/new2/old3/new3；仿真止损 1.5×（111.2 s）。

## 机制一：compute 单元物化门（REJECTED，三变体）

**假设**：扇出块全部语句为 `X |= (-(u8)cpu_changed_i) & mask`，全部 changed
为假时逐条 `|=0` 空操作——包入单条任一变化分支可免除 71.2% 激活的物化块
（预期指令 −5%、Host +2.5~7%）。

- **v1**（`if(__builtin_expect(!!(ch0|...|chk),0))`）：筛选 **−8.21%**
  （old 74.146 / new 80.236）。perf 归因：指令 −3.6%（机制生效）但
  **分支 +34.3%（+7.64G）**、误预测 +14.0%、前端停滞 +22.1%。根因：
  生产编译器 clang 22 把冷路径布尔或链条件展开为**逐 bool 短路分支**
  （实测 ~8.4 分支/门）。
- **v2**（加法链 `__builtin_expect((unsigned)ch0+...!=0u,0)`）：真实二进制
  反汇编显示 clang 把 bool 加法链看穿还原为 truth-OR 继续拆分——静态证伪，
  未消耗性能运行。
- **v3**（加法链、无冷提示、块内联）：筛选 **−12.43%**（old 74.265 /
  new 83.495）。归因：**指令 +4.06%**（门求值全额落在热路径，超过扇出块
  跳过节省）、误预测 +17.6%。
- **家族判定**：在巨型 clang 函数体内，任何新增控制流/求值点的成本
  （拆分分支、寄存器压力、块布局扰动）都超过跳过 ~40–70 条无分支 OR 的
  收益。物化削减只能通过**源头免除**而非运行时跳过实现。候选代码已全部
  回退（发射器/测试/夹具/接线全删）。
- **方法学失误（如实记录）**：门条件形态未先用生产 clang 微实验验证
  （探测误用 g++），导致 v1/v3 两轮无效构建筛选循环。

## 机制二：commit 写助手 ABI 精益化（证据不足，用户判定失败）

**假设**：write_cell<bool,1> 10 参数 ABI（this+9，4 栈参数 + 7 条序言）
的调用骨架可精益化：无符号两态全宽 mask 单元格改发 6 寄存器成员模板
`cpu_write_lean<T,Width>`（恒等 merge、begin/count/projection 打包 u32），
窄常量 mask 走 `cpu_write_leanm`（mask 装入描述符高 32 位）；publish 的
size==1 记录内联比较/写回跳过 libc PLT 往返。

- 实现与聚焦测试（`testLeanBitWrite` 记分板 + ASan/UBSan）通过；调试记录：
  mask 资格截位比较修复、bcp 位域 count/projection 碰撞致 publish 越界
  （ASan 拦截）修复。
- 覆盖：全宽 lean 34,527 站点 + 窄 mask 292 站点；40 个 out-of-line 实例
  符号（未内联，规避 NO00036-B 体积病理）。
- 筛选：bool-only +0.604%、广义 +0.831%、叠加 publish 内联 **+1.428%**。
- **正式三轮（lean2，cell-only）均未分离**：+0.500%（U=2,p=0.2）、
  +0.188%（U=3,p=0.35）、+0.042%——指令 −1.48% 为真（506.48G vs
  514.07G），但 Host 兑现率 ~0.3%/instr%：lean 后 `cpu_write_lean<bool,1>`
  残余 2.80% cycles（原 3.06%），调用成本大头是 call/ret+数据分支+L1，
  不在被消除的参数搬运；前端停滞主导下非取指路径指令节省兑现率低。
- write_scalar/stage_cell lean 变体筛选 −0.063%（噪声内），已回退。
- **lean5（叠加 publish 内联）正式 6 次交替**：old {74.131, 74.095, 73.978}
  / new {73.741, 73.803, 73.820}，均值 74.068/73.788 s，**+0.378%**，
  max(new) 73.820 < min(old) 73.978、U=0、p=0.05 秩次通过；六次端点
  240349/99996/100001/0x80000c0c 全等价、NEMU PASS；生成 685.09 s、
  编译 203.05 s（nproc=32）、HDLBits DUT=001 通过、关态重发射与 NO00045
  全 4,799 文件 md5 全等、开态与筛选模型全等。
- **用户判定**：收益幅度不足，节点 FAILED；候选代码全部回退（子模块与
  `ecb8190` 零差异，根仓库管线/Makefile/reemit 回退）。

## 总结论

1. **发射层确已到顶**：NO00046 五候选 + 本节点物化门三变体 + 两个分析性
   证伪族（宽 OR、打包写回）+ lean ABI 的低兑现率，共同钉死结论——剩余
   可转化池不在发射层。
2. **两处真实但不可提取的池**：fanout 物化 5% 指令池（运行时跳过被
   clang 控制流惩罚淹没，源头免除需要框架级激活精度）；commit 端口评估的
   误预测主导成本（数据依赖分支，本质不可预测）。
3. **唯一有实证支撑的大杠杆**仍是 NO00046 移交的两波直线化路线
   （波 0 直线求值 + 边沿赋值 + 波 1 直线求值、round 协议退役）：gsim
   结构对比显示它同时触及 commit 物化层级（~24% cycles）与轮次机制，
   量级 10%+；代价是多节点工程，入口为波资格静态分析 + 单波原型。
4. **方法学修正移交**：(a) 代码生成假设先用生产编译器（clang 22）微实验
   验证再进构建循环；(b) 效应预估 <0.8%（3v3 分辨下限）的机制不进正式
   复测；(c) 前端停滞主导代码上"减指令 ≠ 减时间"，收益模型须按路径
   （取指/分支/后端）分别校准。

## 保留与回退

- **保留**：普查/解剖工具 `scripts/grhsim_compute_anatomy_stats.py`、
  `scripts/grhsim_fanout_structure_stats.py`、
  `scripts/grhsim_fanout_span_stats.py`（根仓库，随本报告提交）；
  本报告与索引登记。
- **全部回退**：fanout-gate 与 lean-write 的发射器代码、选项、聚焦测试、
  夹具、管线/Makefile/reemit 接线全部撤销；wolvrix 子模块与 `ecb8190`
  **零差异**，根仓库无代码改动残留（回退后 `grhsim-cpu-emit-tests` 等
  测试在基线代码上复跑通过）。
- 诊断构建、探针日志、筛选/正式数据保留在 `ptmp/no00047_uarch_20260920/`
  （不入提交）。
