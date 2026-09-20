# NO00048：schedule 层重构——两波直线化与边沿特化（重启 NO00046 方向）

日期：2026-09-20。最终判定：**ACCEPTED（候选 v1：commit 私有 history 物化
退役，正式 6 次交替 +0.769976%、秩次门通过）**。

## 背景与节点方向

NO00046 拓扑普查（`NO00046-grhsim-ir-topocut-20260919.md`）证明：state 割点后
值图是完美 DAG（leftover=0）、按 commit 穿越分层 k=2 静态精确（wave≥2-only
= 0 任务/0 op）、逃逸舱可枚举；同时五个发射层微优化候选全部证伪，确立
"发射层余量低于噪声底，剩余池都是框架级"。NO00047 进一步钉死约束：任何在
clang 巨型函数体内引入逐单元控制流的机制都被编译器拆分惩罚淹没（−8.21%/
−12.43%），新机制固定成本必须近零。

本节点按用户指示**以 schedule 层重构重启 NO00046 方向**：攻击对象是现行
执行模型（`lib/grhsim/backend/cpu_emit.cpp` 新系统）的 round 协议与派发
结构本身，而非 helper 微优化。

## 现行执行模型精确结构（勘察结论）

生成 `eval()`（`cpu_emit.cpp:3205-3335`）：

1. 输入拷贝 + 逐 input fanout 行影子比较，变化则激活目标（3212-3227）；
2. `for(cpu_round=0;cpu_round<100000;++cpu_round)`（3228）：
   - 每轮开头激活 roundSeeds（3229，system/DPI 属主保守每轮播种）；
   - 静态直线派发序列：逐 task `if(cpu_flags[off]) cpu_task_N();`，相邻
     单字节检查按 8 字节打包 u64 预滤（3243-3298）；compute task 按
     activity 字门控，commit task 按域 arm 字节门控；
   - `cpu_again = cpu_publish()`（3301）：走查 `cpu_pending`，memcmp
     shadow↔objects，真变化则 memcpy + 按 `cpu_targets`/`cpu_memory_readers`
     置 flag/arm，返回 projection 内是否有变化；
   - 域 arm 交接：`cpu_flags[slot]=cpu_next_arms[slot];cpu_next_arms[slot]=0`（3304-3327）；
   - `if(!cpu_again){epilogue;return;}`（3328-3335）——静默判据仅是
     publish 的 projection 变化，不扫活动标志；
3. 100000 轮不收敛则 throw。

关键动态数据（NO00045 dyn 构建，`ptmp/no00045_uarch_20260919/dyn-run3.log`）：

- evals=200,102 / rounds=402,258（≈2.01 轮/eval：每 clock 沿一次 eval，
  每个 eval 基本两轮）；
- pub_calls=402,258（=rounds）、pub_pending=64,225,175（≈160/次）、
  pub_changes=49,004,613（76% 真变化）；
- port_eval=701,474,911、port_fire=487,227,700（点火率 69%）；
- mw_gate=3,622,956,150、mw_fire=664,051,213（memWrite guard 评估 18% 通过）；
- cm_stable=8,654,964、cm_inactive=27,248,530。

微结构锚点（NO00047 解剖，NO00045 二进制）：cycles 370.2G / instr 514.0G /
IPC 1.388 / 前端停滞 44.1%；compute 64.5% / commit 17.6%（39.7% misses，
~93 cyc/端口评估）/ eval() 4.3% / write_cell 4.15%；每 eval 取指流
~15.4MB，L1i/L2 容量失效。

## IDEA

### 机制候选 v1：边沿特化 eval 分裂（edge-specialized dispatch）

**观察**：evals=200,102 = 每周期 2 次（clock 0→1 与 1→0 各一次）。域门控
语义（`cpu_schedule.cpp:228-237`）要求门控 event value 的**任意跳变**都
arm 该域，因此 negedge eval 上 posedge 域的 commit task 照常进入、逐端口
求值 guard 后被 per-op 事件精判拒绝——这是纯调度浪费的嫌疑池。同理
posedge eval 上 negedge/电平敏感逻辑（ICG latch 等）亦然。

**机制**：发射期按 commit 域的事件极性把派发序列静态分裂为
`eval_posedge` / `eval_negedge` 两套（task 函数共享，不复制文本——
NO00046 Q3 的 ×1.81 教训）；与当前沿不匹配的域走"history-only"轻量路径
（只补事件历史采样，不求值端口 guard），保持边沿检测语义精确。compute
侧按 fanout 闭包静态裁剪各沿可达子集。

**瓶颈证据**：port_eval 701M（93 cyc/次）中 negedge 份额待量化；若
negedge 占 ~30% 且几乎全部不点火，可消池 ≈ 17.6%×30% ≈ 5%+，外加
compute 派发与 publish 的沿间削减。

**证伪标准**：插桩量化后若 negedge 沿 port_eval 份额 <10%、或 negedge
port_fire 显著非零（真实电平逻辑工作量大）、或静态分裂后语义保持所需的
history 路径成本吃掉池的一半以上，则否决 v1 转 v2。

### 机制候选 v2：固定两波骨架（two-wave unroll + fallback）

普查结论"消灭不动点循环的直接收益池 ~1–2%"——单独做预计低于或贴近噪声底，
**不作为独立候选**，但作为 v1 的配套结构落地：round 循环展开为波 0/波 1
两段直线（中间一次 publish + arm 交接），波 1 后仍有残余（publish 的
again 或兜底条件）时退回原动态循环（语义兜底，任何设计都安全）。其价值
是为后续节点的"活动位跨 eval 持久/物化退役"提供框架。

### 方法学纪律（NO00047 移交，本节点强制执行）

- 代码形态假设先用生产编译器 clang 22 微实验验证，再进构建循环；
- 预估效应 <0.8%（3v3 分辨下限）的机制不进正式复测；
- 前端停滞主导代码上按取指/分支/后端路径分别校准收益模型。

### 池量化先行（本节点第一步）

现状计数器无沿/轮次分辨率。在 `--dynamic-stats` 插桩构建上追加诊断计数
（仅插桩路径，不进性能模型，不进提交）：

- 轮次直方图（eval 收敛轮数分布，动态验证 k=2）；
- publish pending/changes 按 round==0 / round>0 拆分；
- commit task 入口、port_eval/port_fire、mw_gate/mw_fire 按当前 eval 的
  主时钟沿方向拆分（posedge/negedge/other）；
- compute supernode 激活按沿拆分（可选，看日志量）。

数据决定 v1 是否成立及预期量级，再决定实现形态。

## BASELINE

- 对照（old）：NO00045 正式二进制
  （`ptmp/no00045_uarch_20260919/flow-final/emu/emu`，sha256
  `18964d9b6768eb1d635bcb86235e3c8706dfddaeae8d7125c57bce327a1750e2`，
  本节点开档时已核对一致），正式三次 new 均值 **74.094333 s**。
- 基线 commit：wolvrix 子模块 `ecb8190`（NO00045 接受）；根仓库 `ae37f48`
  （NO00047 归档）。开档时两仓库工作区零差异。
- 等价门槛：`instrCnt=240349`、`cycleCnt=99996`、IPC 2.403586、末端 PC
  `0x80000c0c`、guest cycles 100001、退出码 0、NEMU 对拍无 mismatch。
- 测量口径：`make benchmark_grhsim_ir`，CPU2 单核、XS_EMU_THREADS=1、
  100k cycles、trace 全关、交替 old/new、每次运行前 posix_fadvise(DONTNEED)
  驱逐；筛选单对（+0.4% 门需两票一致），正式预注册 old1/new1/old2/new2/
  old3/new3，秩次判据 max(new)<min(old)（U=0、p=0.05）。
- 筛选/诊断路径：`make reemit_grhsim_ir` 自 NO00045 checkpoint
  （`ptmp/no00045_uarch_20260919/flow-final/xiangshan_grhsim_ir.json`），
  透传 `GRHSIM_REEMIT_COMMIT_COMPACT_WALK=1 GRHSIM_REEMIT_COMMIT_MEM_WALK=1`
  复现 NO00045 发射形态；插桩构建另加 `GRHSIM_REEMIT_DYNAMIC_STATS=1`。
- 资源：生成/编译各 `timeout -s KILL 1800` 截止；编译 `VM_BUILD_JOBS=32`
  （nproc）；仿真止损 = old 预注册比较值 ×1.5。
- 诊断产物目录：`ptmp/no00048_sched_20260920/`（不入提交）。

## 阶段记录

### 勘察补充（2026-09-20，commit 侧已有机制）

- commit task 已有两级提前返回（`cpu_emit.cpp`）：`stableCommitHistories`
  （histories 全稳 → 整任务跳过，dyn 计数 cm_stable=8.65M）与
  `commitEdgePossibility`（边沿不可能 → 只采样 history 后返回，
  cm_inactive=27.25M，**已是 history-only 轻路径**——但它仍逐 op
  `sampleEvents` 走 `stage` 压入 pending，publish 需走查这些记录）。
- commit 入口分布（dyn-run3.log）：有入口的 commit task 490 个，总入口
  63.36M；其中 167 个 ~200k 次（每 eval 一次）、约 41 个 ~400k 次
  （**每轮一次**——被 round 0 写入经 fanout 重 arm）、中部 ~140–193k。
  port_eval=701M / 63.36M 入口 ≈ 11 端口/入口。
- history 采样全部经 pending 暂存（`sampleEvents`→`stage`，
  `sampleHistoryBatch`→`cpu_stage_bytes_overwrite`），publish 逐条
  memcmp 走查——非 firing 沿的 history 暂存是 publish 负载的嫌疑组成。
- compute 侧已有 `quiescence_skip` 与单（event,direction）"inactive level
  跳过"（`cpu_emit.cpp:3872-3885` 一带，注释明确"both clock edges wake
  them, skipping body halves activations"）。

`cpu_emit.cpp` 追加诊断计数（不入性能模型、不入提交基线）：eval 按主时钟
沿分类（cpu_dyn_edge：posedge/negedge/other，以名为 clock 的 1 位 input
的变化方向判定）；轮次直方图 cpu_dyn_round_hist[8]（动态验证 k=2）；
port_eval/port_fire、mw_gate/mw_fire、commit 入口、sn_act 按沿拆分；
port_eval 与 commit 入口另按 round==0/round>0 拆分；publish
pending/changes 按轮与按沿拆分。筛选链
`ptmp/no00048_sched_20260920/dyn_split.sh`（reemit DYNAMIC_STATS → 编译
→ `EMU_RUNTIME_PROFILE=1` 100k 运行 → dyn dump）。

### 池量化结果（2026-09-20，flow-dyn2，100k，等价性不变）

dyn 计数全量（`ptmp/no00048_sched_20260920/dyn-run3.log`）：

- **round_hist `0 198049 2052 1`**：99.0% eval 恰好 2 轮收敛、1.0% 三轮、
  1 个四轮——普查 k=2 动态精确成立。
- evals pos=100,051 / neg=100,051（完全对称，无 other）。
- **port_eval pos=660.55M / neg=40.92M；port_fire pos=446.31M /
  neg=40.92M**——negedge 上每个被评估的端口都点火（电平敏感逻辑的真实
  工作），"negedge 端口空转"假设不成立（commitEdgePossibility 已抑制）；
  negedge 只占 port_eval 的 5.8%。IDEA 原设 v1（整 eval 边沿分裂）据此
  改写为下面的 history 物化退役。
- port_eval r0=681.32M / rN=20.16M（round≥1 仅 2.9%）。
- mw_gate pos=3,622.96M / **neg=0**；mw_fire=664.05M 全在 posedge。
  每 posedge eval ~36k 个 memWrite 端口边沿 guard 打开、82% enable 为假
  ——commit 侧最大惰性池（memWrite 被 armableCommitPort 排除，逐 eval
  无条件评估），列为候选 v2。
- **cm_ent pos=31.79M / neg=31.77M；r0=31.77M / rN=31.78M**——round≥1
  的 commit 入口与 round 0 一样多，但 port_eval_rN 仅 20M：round-1 入口
  几乎全部经 cm_stable/cm_inactive 早退，纯簿记浪费。
- **pub_pending pos=48.24M / neg=15.99M；changes pos=33.02M /
  neg=15.99M**——negedge pending 100% 是真变化且全是 history 采样
  （hist 1→0）；posedge 侧 history 采样（0→1）同样占 ~16M。history 暂存
  合计 ~32M ≈ 全部 pending 流量的一半。
- sn_act pos=973.57M / neg=64.62M（negedge compute 激活为 posedge 的
  6.2%，ICG 等真实工作，不可整批跳过）。

### 候选 v1：commit 私有 history 物化退役（IMPLEMENTED 进行中）

**机制**：commit task 写口的 1 位私有事件 history（references==1、非别名、
非 batched、fanout 仅自域 arm）不再走 stage→pending→publish 往返，改为
**任务末尾延迟直写**（deferred direct store）。连带效果：history 不再产生
pending 记录（免去 push_back + shadow memcpy + publish memcmp/memcpy/
fanout 走查）、不再 re-arm 自域（round-1 commit 入口 31.78M 的成因消失）、
不再贡献 projection（无真实提交的 negedge eval 可一轮收敛）。

**语义论证**：边沿 guard 形如 `hist==old && event==new`，history 变化永远
不会使任何 guard 新变真；域的进入由门控值跳变 arm（value fanout）保证，
与 history 自 arm 无关；任务每轮至多进入一次，私有 history 的唯一读者是
本 op 的 guard（读可见态），延迟到任务末尾直写与 publish 在轮末提交对
下一轮的可见性时刻相同。与既有 compute 侧 `planDirectSampling`
（system/dpi history 直采，同构认证）互为印证。

**实现**（`cpu_emit.cpp`）：`planCommitDirectHistories()` 认证 + 位图；
`stage()` 单点分流（所有 commit 侧 history 采样——inactive 路径、armed
端口、regWrite/memWrite/memFill/memWriteSeq 本体、guard-hoist 补采——都
汇于此）；flush 点在 inactive 早退块内与任务末尾（historyBatches 之后）。
统计 `commit_direct_histories=` 入 historyBatchSummary。

**预期量级**：~32M pending 往返退役 + 31.8M round-1 入口消失 + negedge
一轮收敛，估 0.5–2%（处于分辨下限边缘，筛选定夺；若不足则与 v2 堆叠
进正式门）。

### VALIDATED（2026-09-20，候选 v1）

- 筛选两票：screen-v1 **+1.434%**（old 74.633 / new 73.563）、
  screen-v1b **+0.870%**（old 74.461 / new 73.813），均过 +0.4% 门。
- 结构效果（dyn 构建对照，`dyn-run3.log`→`dyn-run4.log`，等价不变）：
  pub_pending 64.2M→**32.6M**（−49%）、pub_changes 49.0M→17.4M（−64%）、
  negedge pending 15.99M→**0.20M**（−98.8%）、**cm_ent_rN 31.78M→0.21M**
  （−99.3%，round-1 commit 入口消失）、cm_stable 8.65M→50。round_hist
  仍 ~2 轮/eval（negedge 上残留的 latch/非适格 history pending 仍置
  projection），未达成 negedge 一轮收敛——不影响收益成立。
- 资格规模：history_candidates=182,485 中 commit_direct_histories=**541**
  （181,628 个为跨任务共享 history——共享 history 的可见性须轮末原子
  生效，不能直写，直写范围本质上限于私有者）。

### ACCEPTED（2026-09-20，候选 v1）

正式门全绿（驱动 `ptmp/no00048_sched_20260920/formal.sh`）：

- 测试：`grhsim-cpu-emit-tests`、`grhsim-cpu-mapping-tests`、
  `grhsim-cpu-schedule-tests` 全部通过；HDLBits DUT=001 通过。
- 完整 SV→C++ 生成 **710.50 s**（<1800 截止）；fresh 编译 **200.23 s**
  （VM_BUILD_JOBS=32）；正式 model 与筛选 model **4,799 文件 md5 全等**。
- 正式 6 次交替（预注册 old1/new1/old2/new2/old3/new3，每次运行前
  posix_fadvise 驱逐）：old {74.101, 73.978, 73.746}（均值 **73.941667**，
  SD 0.180267），new {73.598, 73.139, 73.380}（均值 **73.372333**，
  SD 0.229596）。**max(new)=73.598 < min(old)=73.746，U=0、单侧精确
  p=0.05、Cohen d=−2.758——秩次门通过，+0.769976% 为真实收益。**
- 六次端点全部 `instrCnt=240349、cycleCnt=99996、guest cycles 100001、
  末端 PC 0x80000c0c`、退出码 0、DIFFTEST 无 mismatch（benchmark 脚本
  内置 expected_endpoint 校验）。
- 正式二进制 sha256
  `1c5514794d870d149e16c8bdaa98d441dc8d3cd9e2d57172ffa2989d88194761`
  （`ptmp/no00048_sched_20260920/flow-final/emu/emu`）。
- 新性能锚点：**73.372333 s** = gsim 归档 46.965 s 的 **1.562117×**
  （较 NO00045 的 74.094333 s 再降 0.722000 s）。
- 实现保留：wolvrix 子模块 `lib/grhsim/backend/cpu_emit.cpp` 的
  planCommitDirectHistories/stage 分流/deferred flush（无条件生效，由
  通用结构特征触发），以及 `--dynamic-stats` 下沿/轮次分辨诊断计数
  （仅插桩路径）。诊断产物与筛选/正式驱动脚本在
  `ptmp/no00048_sched_20260920/`（不入提交）。

### 后续方向（移交下一节点）

- **候选 v2：memWrite 端口 arming**（本节点池量化定位的最大 schedule 级
  残余池）：mw_gate=3.62B/100k（每 posedge eval ~36k 个 memWrite 端口
  边沿 guard 打开，82% enable 为假空转）；memWrite 被 armableCommitPort
  排除（直写端口仅 regWrite/latchWrite）。安全扩展形态：**单写者数组**
  （census：>1 写 op 的 state 仅 1,223 个）的 memWrite 端口纳入
  pflags arming（enable/addr/data/mask 四操作数变化驱动 arm 位；操作数
  不变时跳过 = 幂等无操作；端口 history 采样已在 armed 路径无条件保留）。
  预估池 1–3%。注意多写者数组跳过旧写是**错误**的（写-写序），必须
  严格单写者。
- ~~两波骨架（固定两趟 + 兜底循环）~~ **已放弃（2026-09-20 用户决定）**：
  本节点数据确认其单独收益 <0.5%（round 协议残余已被 v1 大幅削减），
  低于测量分辨下限；其作为载体要承载的 compute 惰性激活池受 clang
  控制流拆分惩罚封锁（NO00047），骨架无货可载。后续节点不要再以
  两波/不动点退役为方向立项。
- compute 64.5% 的 70% 惰性激活池依然最大但受 clang 控制流拆分惩罚
  封锁（NO00047）；任何新跳过机制须满足"近零固定成本"。
