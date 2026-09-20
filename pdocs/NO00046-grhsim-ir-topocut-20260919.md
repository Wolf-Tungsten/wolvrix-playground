# NO00046：拓扑割点普查与五次发射层候选证伪（失败节点）

日期：2026-09-19 至 2026-09-20。最终判定：**FAILED（失败节点：全部候选
REJECTED，未取得经统计确认的真实性能收益；候选代码已全部回退，
wolvrix 子模块与基线逐字节一致）**。

## 背景与节点方向

承接 NO00044/45 的微结构普查结论：与 gsim 的剩余差距 = 指令数 2.774×
在前端受限（45.3% 停滞）下的直接体现。本节点按用户提出的框架性方向推进：

> **跨过 write→read port 对 IR 图进行展开；若在固定展开次数下得到不需要
> 不动点的图则切换为单趟求值，否则对不可展开部分退回不动点模型（混合）。**

节点分两步：先做拓扑割点普查判定该方向的可行性与收益上限，再据普查结论
落地机制。普查给出决定性结论后，五个发射层候选在统一判据（单对筛选
+0.4% 门、正式 6 次交替秩次判据）下全部被证伪。本报告如实记录普查
（方向级结论）与全部证伪过程。

## 普查（`analyze_grhsim_topocut`，输入 NO00045 正式 checkpoint）

工具：`scripts/grhsim_topocut_stats.py` + Make 目标 `analyze_grhsim_topocut`；
输入 `ptmp/no00045_uarch_20260919/flow-final/xiangshan_grhsim_ir.json`
（511 MB，3,732,947 ops / 3,571,051 values / 313,107 states）；
完整日志 `ptmp/no00046_topocut_20260919/census2.log`。

### Q1 无环性（决定性）

- 值依赖图（op 为节点、producer→consumer 为边，state.read 为源、写 op 为汇）
  **是完美 DAG**：Kahn 处理 3,732,947/3,732,947，leftover=0，最大深度 536。
- 含义：不动点不是图性质要求的——状态割点后不存在任何组合环；补
  write→read 转发边后的单趟求值在 op 级结构上可行。不动点是
  提交/静默（commit/quiescence）协议的产物。

### Q2 状态深度 / 固定展开次数

任务图按 commit 穿越次数分层（fanout 行格式
`[state, [activate PartitionIds], [arm PartitionIds]]`，4,690 任务、
163,900 条值流边、5,483 条 commit 激活边）：

- wave0（种子=input/system/全部 commit 任务 + 值流闭包）：3,893 任务 /
  3,059,687 ops；
- wave1（commit-fanout 目标 + 值流闭包）：4,689 任务 / 3,731,923 ops；
- **wave≥2-only = 0 任务 / 0 ops**——没有任何任务需要第三次 commit 穿越，
  k=2 在静态上精确，"固定展开次数"成立。

### Q3 波资格与复制成本（反转性结论）

- task 粒度 both（wave0∩wave1）= 3,893 任务 / **80.98% 静态 compute ops**，
  wave0-only = 0——天真按波复制代码会让 compute text ×1.81，在 L1i/L2 已
  完全容量失效（15.4 MB/eval 取指流）下不可行；可行形态是"同一 task 函数
  按波调用两次"（即现行 round 模型已在做的）。
- 动态双波激活完全不同：NO00036 插桩桶数据 every_round 单元仅 315 个 /
  7.74B dyn ops = **6.73%**——活动系统已在动态抑制重复求值；publish
  calls=402,258=rounds，每轮一次 publish（311.88 pending/call、88% 真变化）。
- **结论**：展开前提全部成立，但"消灭不动点循环"的直接收益池只有
  ~1–2%（静默协议成本）；round 结构的真正残余成本在波间机制
  （publish 走查、commit 走查）——这是后面试验的攻击点。

### Q4 逃逸舱清单

- 写 op：109,930 regWrite / 37,208 memWrite / 434 memWriteSeq / 409
  latchWrite / 158 memFill；>1 写 op 的 state 仅 1,223 个。
- 混合 mem 数组（memRead+写）2,863 个、31,646 个 memRead op（wave1
  21,588 / both 10,058）——波内写→读序由"波 0 写、波 1 读"的展开序自然
  保持，不构成单趟化障碍。
- 副作用 op：7,236 system.task / 6,527 dpi.call / 5 output.write；四态值
  13,647（0.38%）；8 个 input.read；写 op 全部带 `event_edges` 参数。

## BASELINE

- 对照（old）：NO00045 正式二进制
  （`ptmp/no00045_uarch_20260919/flow-final/emu/emu`，sha256
  `18964d9b6768eb1d635bcb86235e3c8706dfddaeae8d7125c57bce327a1750e2`，
  已核对一致），正式三次 new 均值 **74.094333 s**。
- 基线 commit：wolvrix 子模块 `ecb8190`（NO00045 接受）；根仓库 `2cbfd97`。
- 等价门槛：`instrCnt=240349`、`cycleCnt=99996`、IPC 2.403586、末端 PC
  `0x80000c0c`、guest cycles 100001、退出码 0、NEMU 对拍无 mismatch。
- 测量口径：`make benchmark_grhsim_ir`，CPU2 单核、XS_EMU_THREADS=1、
  100k cycles、trace 全关、交替 old/new、每次运行前 posix_fadvise(DONTNEED)
  驱逐；筛选单对、正式 old1/new1/old2/new2/old3/new3。

## 候选 v1：publish pending 双环拆分（REJECTED）

**机制**：memory 记录（`cpu_write_cell`/`cpu_stage_cell`）改入
`cpu_pending_mem`，publish 拆双环，消除 per-i `p.memory` 数据相关分支。
依据：perf record 定位 eval() 内联 publish 走查 4.16% cycles + 6.19%
branch-misses（NO00045）。

- 可复现性：关态重发射与 NO00045 正式 model **4,799 源文件 md5 全等**；
  开态仅 `grhsim_SimTop.cpp/.hpp` 预期三处差异。
- 筛选：screen1 **−0.564%**、screen2 **−0.026%**（真效应 ≈ 0±0.3%）。
- perf 归因：new 较 old **instructions −0.35%**（513.955G→512.171G）、
  **branch-instructions −5.77%**（22.272G→20.987G）、branch-misses
  −0.77%，但 **cycles +0.32%**——砍掉的是预测良好的廉价分支，在前端
  受限代码上换不成 cycles。
- **判定：REJECTED（standalone 中性）。**

## 候选 v2：窄端口族（≤8 位）全字紧凑走查（REJECTED）

**机制**：NO00044 紧凑 ctz 走查从 u64 全掩码推广到宽度 ≤8 位全掩码
（bool/u8，1 字节存储，组内元素字节数同构）。覆盖 +59 组 / +3,776 lane
（总 549 组 / 35,136）。

- 筛选：screen4 **+0.387%**、screen6 **+1.399%**（两票为正进正式门）。
- **正式 6 次：old {74.112, 73.935, 73.687}（均值 73.911333，SD 0.213486）、
  new {73.960, 74.485, 73.883}（均值 74.109333，SD 0.327607），
  −0.267888%，U=6、p=0.8——秩次门未过，REJECTED。** 筛选两票为噪声；
  窄族链已短且预测良好，消除几乎无收益。生成 698.19 s、编译/对拍/
  HDLBits 均通过；正式 model 与筛选 model md5 全等。

## 候选 v3：部分字掩码紧凑走查（REJECTED）

**机制**：非全 64 lane 同构的字按字节类（1/2/4/8）拆子走查（编译期
lane 掩码 + popcount 下标映射），逐 lane 资格池实测 **62,693**
（b1=21,813 / b2=4,532 / b4=1,855 / b8=34,493），部分字消费 **26,269
lane / 1,506 子走查**，紧凑覆盖名义翻倍至 61,405。

- **筛选 screen3：old 73.965 / new 77.057 = −4.180%——REJECTED。**
- perf 归因：**instructions +1.36%**（513.96G→520.96G）、branch-misses
  **+6.29%**（3.8888G→4.1332G）、cycles +2.84%。描述符 + popcount 的
  逐 lane 开销全面超过逐位内联常量链，ctz 循环/enable 标志分派引入
  新的误预测。**结论（与 NO00044-v1 同族、更大规模复证）：逐位内联
  常量链已是指令最优，描述符走查只在全 64 口同构深链 + 大函数 text
  场景盈利。**
- 附带修复：初版窄族资格允许任意字节数，3/5/6/7 字节 lane 会错误降级
  为 uint8_t 加载——作为 bug 排除（该形态从未进入运行）。

## 候选 v5：全掩码 write_cell 精简写体（REJECTED）

**机制**：mask 为 `UINT64_MAX` 或状态宽度全 1 常量时 merge 恒等
（next==data），发射精简变体 `cpu_write_cell_full`（少一个 mask 实参
建立、无 merge ALU），覆盖 write_cell_full_sites=34,527。write_cell
为 commit 侧最热 helper（664M 次调用/run、4.21% cycles）。

- 筛选：screen7 **+0.619%**、screen8 **−1.126%**（不一致，正式门仲裁）。
- **正式 6 次：old {73.948, 74.003, 74.350}（均值 74.100333，SD 0.217959）、
  new {74.085, 74.001, 74.038}（均值 74.041333，SD 0.042099），
  +0.079622%，U=5、p=0.65——秩次门未过，REJECTED。** 生成 679.59 s、
  编译/对拍/HDLBits 均通过；正式 model 与筛选 model md5 全等。
- 堆叠 v1+v2（screen5）**−0.970%**，反协同，一并否决。

## 总结论

1. **普查（方向级成果）**：单趟拓扑求值的前提全部成立——值图是完美
   DAG（leftover=0）、k=2 静态精确（wave≥2 残余 0）、逃逸舱（混合
   mem 数组/副作用/多事件）可枚举。混合模型路径明确：无环核心直线化
   + 事件化边缘兜底。
2. **发射层空间低于噪声底**：五个候选 + 一个堆叠在统一判据下全部
   证伪，且后验数据显示真效应均 ≤0.3%（本机单对噪声 ±0.5–1%、
   6 次秩次门分辨下限 ~0.8%）。可复现的统一教训：**移除预测良好的
   廉价指令/分支不转化为 cycles；描述符化走查在散碎端口上净亏损**。
   这与 NO00040–45 逐节点收窄的余量一致——发射层微优化已尽。
3. **剩余可转化池都是框架级**：compute 64% cycles 的 70% 惰性激活
   （需"近零固定成本"前提下的激活精度机制，即单趟模型配套的细粒度）、
   物化机制（boundary/pending/publish 只保留外部观察者）。两者都是
   多节点工程，入口即本普查确立的两波直线化路线。

## 保留与回退

- **保留**：普查脚本 `scripts/grhsim_topocut_stats.py` + Make 目标
  `analyze_grhsim_topocut`（根仓库）；本报告与索引登记。
- **全部回退**：v1 双环、v2 窄族、v3 部分字、v5 精简写体的发射器
  代码、测试与夹具全部撤销；wolvrix 子模块工作区与 `ecb8190` **零
  差异**（git diff 为空）；根仓库仅新增普查工具与报告。
- 回退后 `grhsim-cpu-emit-tests`、`grhsim-ir-tests`、
  `grhsim-cpu-mapping-tests`、`grhsim-cpu-schedule-tests` 全部通过。
- 诊断构建、探针日志、筛选/正式数据保留在
  `ptmp/no00046_topocut_20260919/`（不入提交）。

## 后续方向（移交下一节点）

- 两波直线化执行模型（普查已证可行）：波 0 直线求值 + 边沿赋值 +
  波 1 直线求值，round 协议整体退役；task 函数按波共享（不复制
  text），活动位跨 eval 持久；不可直线化构造（混合 mem 数组波内序、
  DPI/system 副作用、多时钟）保留事件化边缘。预期同时消灭 round-1
  派发、commit 走查、publish 内部部分——这是唯一能触及
  compute 惰性激活与物化机制两大剩余池的路线。
- 该路线为多节点工程，建议以"波资格静态分析 + 单波原型（先 wave0-only
  子集）"作为下一节点入口。
