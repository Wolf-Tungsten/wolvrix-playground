# NO00043：mux 优先选择链折叠——prioritySelect op + 嵌套无表发射

日期：2026-09-18。最终判定：**ACCEPTED（+2.318837%，页帧驱逐协议下 6 次交替秩次判据通过）**。

本节点围绕 `ptmp/cpu_friendly_op_scan_20260918/02_findings_report.md` 的头条候选
**F1：优先选择 mux 链**。节点内先否决了"mask 打包 + TZCNT + 臂表"发射形态
（变体 A，−4.299%），随后以同一 IR 折叠 + **嵌套无表发射**（变体 B）取得真实
收益。冻结 GRH、GRH pass、XiangShan 与测试源码不修改；方案由 mux 链拓扑、位宽、
两态性、引用计数等通用结构特征触发，不含模块名称匹配。

## IDEA（2026-09-18）

### 瓶颈证据

- 普查（同一 IR，md5 已核对与 NO00042 flow-final 全等）：链长 ≥3 的 mux 优先
  选择链 **20,974 条、含 242,529 个 mux（全部 mux 的 41.2%）**；链长 ≥8 且全
  1-bit 条件、窄臂的 6,849 条 / 184,170 mux；计入条件锥覆盖 555,612 op
  （全 IR 14.1%）。典型族：len=25、64 位臂（24 个 state.read 臂 + 常量缺省）
  **2,145 条**——调度器/旁路优先选择器形态。
- 现状发射（NO00037 起）：每个 mux = `grhsim_mux_u64` 掩码选择（≈5 ALU +
  3 load + 1 store），沿链**串行相关**；len=25 链 ≈ 225 uops、~200 拍依赖链。
  中间链节若跨超节点还携带 boundary 写回 + 变化检测（约 5–6 条/值）。
- 生成代码实测（`scan_generated_chains.py`，NO00042 flow-final）：发射后同一
  函数作用域内可见的 ≥3 链只剩 **2,884 条 / 13,646 mux**——分区把 94% 的
  IR 级链节切到不同超节点。**纯发射层局部融合覆盖率太低，必须把链在 IR 层
  变成单个原子 op**（本节点与 F1 报告建议的关键差异/落地方式）。

### 假设与机制

新增 GrhSIM-IR op `core.compute.prioritySelect` 与语义 pass
`grhsim.mux-chain-fold`：

- **链检测**：`mux(c0,a0,mux(c1,a1,…,dflt))` 沿 false 臂的链；链节要求
  结果二态 ≤64 位、条件 1 位二态无符号、结果类型全链一致、链节结果全模型
  单引用（唯一消费者即上一级 mux 的 false 臂）；阈值 ≥3 节；超长链按
  ≤64 节分段（mask 位宽限制），段间经链节结果槽串联。
- **折叠**：根链节原地把 op 换成 `prioritySelect`，操作数
  `[c0..c{n-1}, a0..a{n-1}, dflt]`、结果沿用根链节结果值；内部链节 op 删除
  （compact 自动回收无主值）。依赖边由随后的 CPU 映射重建自动按新操作数
  集合重算——扇出、激活与调度语义不变，中间链节的超节点激活与 boundary
  写回整体消失。
- **发射**（cpu_emit）：条件按优先级打包
  `mask = c0 | c1<<1 | …`，`result = mask ? arms[ctz(mask)] : dflt`；
  与链语义严格相同（首个为真者优先），**无需证明互斥**。条件/臂值本来就被
  计算，打包是纯读侧（消费者侧）工作——不挂任何生产者钩子，避开 NO00042
  变体 B 的写侧成本不对称失败模式。（该发射形态即后来的变体 A，筛选否决后
  改为嵌套无表发射，见阶段记录。）
- 新意：替换对象是**长串行选择链**（m=25 级、每级 ~9 uops），不是散乱布尔锥
  ——NO00040 lut-fold 证伪（−1.5%）不适用于此形态；同时折叠从 IR 删去
  ~221k 个链节 op（其 boundary 槽、变化检测与激活边随之消失），兼具
  "激活精度"收益。

### 预期与证伪标准

- 覆盖上界：242,529 mux（41.2% mux）；动态粗估链上 mux ≈ 6.4k 次/eval。
- 预期收益 +0.5%~2%；单对筛选门 +0.4%（页帧驱逐协议）；正式门为 6 次交替
  秩次判据（max(new) < min(old)）。
- 证伪条件：pass 统计覆盖远低于普查（如单引用约束砍掉大半）、筛选 <+0.4%、
  或正式交替无法通过秩次判据——按协议记录 REJECTED 并分析，随后改换机制。

## BASELINE（2026-09-18）

- 对照（old）：NO00042 正式二进制
  （`ptmp/no00042_edge_direction_20260918/flow-final/emu/emu`，sha256
  `d8cdcb69b1bcbd90e6b92d54cc6e3b91fd75a1c1f2c8b397dadd41ba2e09a1e6`），
  正式成绩三次 new 均值 **79.492000 s**。
- 基线 commit：wolvrix 子模块 `43893bc`（NO00042 接受）；根仓库 `66c4cbb`。
- 等价门槛：`instrCnt=240349`、`cycleCnt=99996`、IPC 2.403586、末端 PC
  `0x80000c0c`、guest cycles 100001、退出码 0、NEMU 对拍无 mismatch。
- 测量口径：`make benchmark_grhsim_ir`（scripts/benchmark_grhsim_ir.py），
  CPU2 单核、XS_EMU_THREADS=1、100k cycles、waveform/commit/RAM trace 关闭，
  交替 old/new，每次运行前 posix_fadvise(DONTNEED) 页帧驱逐；止损 1.5×
  （基线 79.5 s → 119.3 s）；预注册顺序与二进制哈希写入 preregister.json。
- 筛选路径：`make reemit_grhsim_ir` 自 NO00042 checkpoint
  （`flow-final/xiangshan_grhsim_ir.json`）加 `--mux-chain-fold`（折叠后重建
  CPU 映射再发射）。
- 资源配置：生成/编译 timeout 1800 s 截止机制；编译并行度
  `XS_VM_BUILD_JOBS=nproc`（本机核数，节点收尾记录实际值）。

## 阶段记录

### IMPLEMENTED（2026-09-18）

实现（wolvrix 子模块工作区差异，基线 `43893bc`）：

- 新 op `core.compute.prioritySelect`：操作数 `[c0..c{N-1}, a0..aN-1, default]`
  （N∈[3,64]），首个为真条件选中对应臂、全假取缺省——与 mux 链语义逐位一致。
  注册于 `lib/grhsim/dialect/core.cpp`；校验规则在 `lib/grhsim/ir/verifier.cpp`
  （条件须 1 位二态无符号，臂/缺省/结果须二态标量 ≤64 位，无 objectRef/参数）。
- 新 pass `grhsim.mux-chain-fold`（`lib/grhsim/pass/mux_chain_fold.cpp`）：
  全模型引用计数 + 唯一消费者映射；链节须为二态 ≤64 位 mux、1 位二态无符号
  条件、结果类型全链一致、链节结果单引用且唯一消费者即上一级 false 臂；
  阈值 ≥3 节；>64 节按段切分（段间经链节结果槽串联，短尾保持 mux）。
  根链节原地 `replaceOperation` 为 prioritySelect，内部链节 compact 回收。
- 发射（`lib/grhsim/backend/cpu_emit.cpp`）：`mask = Σ (u64)c_i << i`，
  `arms[N]` 表，`mask ? arms[__builtin_ctzll(mask)] : default`，臂经与现状
  mux 相同的 `grhsim_cast_u64` 投影；外层 `normalize()` 不变。
- 管线：`scripts/wolvrix_xs_grhsim_ir.py` 在 `grhsim.bitwise-muxes` 后插入
  `grhsim.mux-chain-fold`（随后第二趟 CPU 映射重建，扇出/调度自动按新操作数
  集合重算）；`scripts/reemit_grhsim_ir.py` 增 `--mux-chain-fold`（fold +
  CPU_MAPPING_PIPELINE 重建），Makefile 增 `GRHSIM_REEMIT_MUX_CHAIN_FOLD`
  透传。
- 聚焦测试：`test_grhsim_ir.cpp::runMuxChainFoldTest`（4 链节正例的操作数
  顺序/幂等性、双链节/多消费者/宽条件/类型混合守卫、7 种畸形
  prioritySelect 的 verifier 拒绝）——`grhsim-ir-tests` 通过；
  `test_cpu_emit.cpp::testMuxChainFold`（4 链节折叠 + 双链节不折叠 + 带
  分接点的三段后缀折叠 + 寄存器快照输出，JSON 往返后发射，检查
  `cpu_arms`/`__builtin_ctzll` 形态，ASan/UBSan 下编译运行随机记分板
  24576 次比对）——`grhsim-cpu-emit-tests` 通过（93.1 s）；
  `grhsim-cpu-schedule-tests` 通过。

### 筛选构建（2026-09-18）

- reemit 筛选（`flow-screen/`，自 NO00042 checkpoint，fold + 重建 CPU 映射）：
  **mux_chain_folds=18,316、mux_chain_segments=18,916、mux_chain_links=231,301、
  mux_chain_max_links=609**——普查 20,974 条 ≥3 链中 87% 折叠，链节覆盖
  95.4%（单引用/类型一致/1 位条件约束仅排除少量）。
- 映射/发射统计与 NO00042 逐项一致（quiescence 293、edge_direction 293、
  port_arm 109,229、direct_commit 109,235 等），仅 helper_read_cache_values
  408,161→396,101（链节消除减少重复读）；生成的 C++ 总量 1.2 GB→**969 MB**，
  `grhsim_mux_u64` 调用 582,431→**351,130**（−231,301，与折叠链节数精确一致），
  新增 18,916 个 `__builtin_ctzll` 打包选择点。
- 筛选编译：209 s（32 jobs，nproc=32，下同）。
- **单对筛选（screen1，页帧驱逐协议，端点 240349/99996/100001/0x80000c0c
  一致，退出码 0）：old 80.074 / new 83.516 = −4.299%——REJECTED（变体 A：
  mask+TZCNT+臂表发射）。** 单对无统计效力但远超 ±0.4% 噪声门，方向明确。
- 待诊断假设：H1 融合 op 的激活集合是 2N+1 个操作数的并（旧根只看 3 个直接
  输入），深层锥变化现在触发全链重估；H2 臂表的 N 次栈存储 + 索引载入
  （store-forwarding）开销；H3 轮次/代码布局变化。
- 相位诊断（CPU2、100k、EMU_PHASE_TIMING=1 各一次）：old eval 79.25 s
  （compute 56.35 / commit 21.60 / publish 1.17），new eval 83.10 s
  （compute **60.01** / commit 21.71 / publish 1.25），**轮次同为 402,258**。
  回归全部在 compute（+3.66 s），收敛结构不变——H3 排除。
- **变体 B（嵌套无表发射，REJECTED→通过的分水岭）**：prioritySelect 改发为
  单一右嵌套 `grhsim_mux_u64(c0,a0,grhsim_mux_u64(c1,a1,…))` 表达式——消除
  中间链节的槽位写/读，保留逐位掩码选择与 cast，无表无 ctz。单对筛选
  （screen2，同协议）：old 79.703 / new **77.464 = +2.809%**，越过 +0.4% 门。
  对比 A（−4.299%）：**臂表存储 + 索引载入（H2）是回归主因**；嵌套形式下
  union-activation 代价被"231k 链节的写回/存储消除"净反超为正。变体 B 进入
  正式验证。

### 正式门槛（2026-09-18）

- 完整 SV→C++ 生成 **695 s**（<1800 s，完整 SV 路线、
  `XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0`、非 checkpoint 恢复，
  round-trip 校验通过；`timeout -s KILL 1800` 截止机制在位未触发）；
  管线内 `grhsim.mux-chain-fold` 位于 `grhsim.bitwise-muxes` 之后、第二趟
  CPU 映射之前（451 ms）。
- 正式 model 与筛选 model（flow-screen2）全部 **5,052 个源文件 md5 全等**。
- fresh 编译 **199 s**（<1800 s，exit 0，`VM_BUILD_JOBS=nproc=32`——较
  NO00042 的 −19% 代码量进一步缩短编译）。
- HDLBits DUT=001 回归通过（`[TB] dut_001 passed: one=1`）。

### 正式 6 次交替复测：ACCEPTED（2026-09-18）

被测二进制 `ptmp/no00043_mux_chain_fold_20260918/flow-final/emu/emu`
（正式 SV 路线构建）；对照 old 为 NO00042 flow-final sha256 `d8cdcb69…`
（其正式三次 new 均值 79.492000 s）。6 次交替
（`formal/summary.json`；预注册 old1/new1/old2/new2/old3/new3；每次运行前对
old/new emu 均执行 posix_fadvise(DONTNEED) 页帧驱逐；CPU2、单核、
XS_EMU_THREADS=1、100k cycles、waveform/commit/RAM trace 关闭）：

| run | old Host (s) | new Host (s) | 退出 | 端点 |
|---|---:|---:|---|---|
| 1 | 79.789 | 78.028 | 0 | 240349/99996/100001/0x80000c0c |
| 2 | 80.021 | 78.142 | 0 | 同上 |
| 3 | 79.491 | 77.582 | 0 | 同上 |

六次均 NEMU 对拍通过、`instrCnt=240349`、`cycleCnt=99996`、IPC 2.403586、
末端 PC `0x80000c0c`、guest cycles 100001，退出码 0，无 mismatch。

- old 均值 **79.767000 s**（样本 SD 0.265684）、new 均值 **77.917333 s**
  （样本 SD 0.295948），降低 **2.318837%**。
- `max(new) 78.142 < min(old) 79.491`，Mann-Whitney U=0、单侧精确 p=0.05、
  Cohen d=−6.58、Cliff's delta=−1.0，**秩次判据通过**。

**最终判定：ACCEPTED（变体 B：mux 优先选择链 IR 折叠 + 嵌套无表发射，
+2.318837%，秩次判据通过，生成/编译门槛通过，100k 等价确认，HDLBits 回归
通过）。** 按新均值计算，GrhSIM-IR 为归档 gsim 46.965 s 的 **1.659065×**
（上一节点 NO00042 为 1.692622×）。

**语义约束**：折叠仅作用于结果类型全链一致、1 位二态无符号条件、链节结果
全模型单引用（唯一消费者即上一级 false 臂）的二态 ≤64 位 mux 链，阈值 ≥3 节、
分段 ≤64 节；prioritySelect 语义 = 首个为真条件选臂、全假取缺省，与链逐位
一致；发射保持逐链接同样的掩码选择与 cast/规范化，仅消除中间链节的槽位
写/读。冻结 GRH、GRH pass、XiangShan 与测试源码未改；IR、映射、调度由管线
自动重建，轮次结构实测不变（402,258）。

**保留实现**：wolvrix 子模块 commit `52dd805`（新增
`include/grhsim/pass/mux_chain_fold.hpp`、`lib/grhsim/pass/mux_chain_fold.cpp`
（pass 本体）、`lib/grhsim/dialect/core.cpp` 与 `lib/grhsim/ir/verifier.cpp`
（op 注册与校验）、`lib/grhsim/backend/cpu_emit.cpp`（嵌套发射）、
`lib/grhsim/pass/pass.cpp`（注册）、`CMakeLists.txt`、
`tests/grhsim/test_grhsim_ir.cpp` 与 `tests/grhsim/test_cpu_emit.cpp` +
`data/cpu_mux_chain.{mk,_main.cpp}`（聚焦测试））；根仓库随本报告一并归档的
提交（`scripts/wolvrix_xs_grhsim_ir.py` 管线插入、`scripts/reemit_grhsim_ir.py`
`--mux-chain-fold`、`Makefile` `GRHSIM_REEMIT_MUX_CHAIN_FOLD` 透传、报告与
索引）。被测 emu sha256 `9550498a5f5a499eb5a4daa8f8aa3f74d844f780e2e85ffb2bf1a47af0ae6585`。

**被否决尝试**：变体 A（mask 打包 + `__builtin_ctzll` + 栈上臂表）筛选
−4.299% 否决，相位诊断把回归定位于 compute（+3.66 s）、轮次不变；变体 B 仅
改发射形态即转正，确认臂表存储/索引载入开销为主因。A 的模型/日志保留在
`ptmp/no00043_mux_chain_fold_20260918/`（flow-screen、screen1、diag_*）。

**后续方向**：(a) 普查中 F1 的"条件锥"部分（and/or/eq minterm 生产者）未动，
其打包/共享仍开放；(b) 变体 A 的教训（表存储代价）提示更长链可考虑分段
嵌套而非单表；(c) 本节点删除的 231k 链节带走的 boundary 写回约 6.4k 次/eval，
剩余 compute 主体仍是平坦热点与 4454+ 族真实写回；(d) F2 宽 op 双字内联经
动态权重估计仅 ~0.07%（391/575k 写/eval），不建议单独成节点。


