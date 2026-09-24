# NO00003: 下降沿 eval 消除（falling-edge eval elision）——冻结驱动双相 tick 中纯簿记半周的结构化消除

| 字段 | 值 |
|---|---|
| 父节点 | NO00002（当前最佳，无迂回） |
| 角色 | 优化 |
| 状态 | REJECTED（机制性证伪，双证据；代码保留） |
| 锚定指标 | M-neg（下降沿 eval 时间占比，eval_ns_neg/eval_ns）；辅证 fp_evals 触发率、rounds/evals |
| 指标阈值 | M-neg ≤ 1.5% 且相对基线下降 ≥80%；fp_evals ≥ 99% 的下降沿 eval |
| 回退预算 | 新组 Host 均值 ≤ 旧组均值 ×1.025（≤71.89 s，旧组为同二进制 kill-switch 关闭组） |
| RUN_ID | no00003_gen_20260924 / no00003_build_20260924 / no00003_bench_20260924 / no00003_phase_20260924 / no00003_dyn_20260924 |
| 工作区 | ptmp/no00003_falling_edge_elision_20260924/ |

## 基础选定（BASELINE）

- **父节点**：NO00002（当前最佳指针，wolvrix `4de8c01` + 根仓库 NO00002 提交，Host 70.134 s）。本节点直接在其代码状态上改动，无迂回。
- **基线测量（配置未变，复用父节点归档值，不重跑）**：
  - Host time 100k：**70.134 s**（3 次有效均值 69.849/70.404/70.150，SD 0.278 s）。
  - M1 相位：compute 51.486 s、commit 16.931 s、publish 0.860 s；evals=200102、rounds=401257（rounds/evals=2.0054）。
  - M4 结构量（确定性计数，NO00002 复验与 NO00001 逐键一致；本节点 TESTED 再次复核）：dynOps=99,479,933,605；commit 入口 **33,178,832** 次（per-id 求和 = pos+neg = r0+rN 三口径一致）；port_eval 669,591,914（fire/eval 70.32%）；input.read wr=603,267、**changes 200,104（≈1.000 次/eval）**。
  - 运行日志边沿分裂计数（dynamic-stats 构建，`cpu_dyn_edge` 按输入扫描后 clock 电平分桶；NO00001/NO00002/NO00003 三次 dyn 运行逐键一致）：edge evals pos=100,051 / neg=100,051 / other=0；cm_ent pos=16,593,298 / neg=16,585,534（r0=31,370,604 / rN=1,808,228）；sn_act pos=928,616,078 / neg=64,779,507；**port_eval pos=628,671,054 / neg=40,920,860（fire pos=429,935,144 / neg=40,920,859 = 409×100,051，恰为每 clock 低电平 eval 触发全部 409 个 ICG 锁存写）**；mw_gate pos=3,622,956,150 / **neg=0**；pub_pending pos=27,478,825 / neg=300,188（3.0/eval）；round_hist：199,049 eval 恰 2 轮、1,053 eval 3 轮、无 1 轮或 ≥4 轮。（注：本节点早期草案曾误记 port_eval neg=0、cm_ent 15.99M 等，已按归档 run.log 订正；NO00002 的 `dyn-baseline-no00001.txt` 归档文件因过滤管线未先剥离 ANSI 转义而丢失 `commit 4410` 一行，原始 run.log 完整。）
- **对照设置**：本节点新机制以运行时 kill-switch（env `GRHSIM_IR_DISABLE_FP_ELISION=1`，模型构造时读取一次）在同一二进制内提供"旧语义"对照臂；3+3 交替在同一窗口、同一二进制两臂间进行，另以 NO00002 归档二进制（`ptmp/no00002_disable_text_share_20260924/flow/emu/emu`）同窗口复跑 3 次做绝对锚定。
- **输入核对**（sha256，与 NO00001/NO00002 相同，输入未变）：
  - `testcase/xiangshan/ready-to-run/coremark-2-iteration.bin` = `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`
  - `testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so` = `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`
- **资源配置**：与 NO00001/NO00002 完全一致：`XS_EMU_CPU=2`、`XS_EMU_THREADS=1`、`XS_NUM_CORES=1`、`XS_SIM_MAX_CYCLE=100000`、waveform/commit/RAM trace 全关；编译 `VM_BUILD_JOBS=32`（=nproc）。flow 配置全默认（文本共享关闭自 NO00002 起即为默认）。
- **计时边界与止损线**：
  - 生成：make 启动 → 完整 C++ 与 Makefile 生成完成，墙钟 <1800 s；超时 `TIMEOUT_KILLED`。
  - 编译：emu 编译启动 → 可执行文件完成，墙钟 <1800 s；超时 `TIMEOUT_KILLED`。
  - 仿真：仅 emu 执行区间。比较基线值预注册为 70.134 s，运行截止 = ×1.5 = **105.201 s**，超时 `REGRESSION_KILLED`。
  - 每次仿真运行前对 emu 二进制 `posix_fadvise(DONTNEED)` 驱逐页缓存（benchmark_grhsim_ir.py 内建）。
- **复现方法**：父节点代码状态 = wolvrix `4de8c01` + 根仓库 NO00002 提交（`6c5f623`）；本节点改 wolvrix 子模块 grhsim-ir 后端 emit 与根仓库 flow 脚本/Makefile，冻结面（GRH IR、GRH pass、XiangShan、测试源码）零改动。

## 假设提出（HYPOTHESIS）

- **假设**：emu 的 evals 恰为 cycles 的 2 倍，源于冻结 difftest 驱动（`testcase/xiangshan/difftest/.../emu.cpp:414-445`，不可改）的 Verilator 式双相 tick：`set_clock(1); step(); … set_clock(0); step();`。其中 **clock 1→0 的下降沿 eval 在本设计（假定纯 posedge 语义；当时的依据为 mw_gate neg=0，port fire neg 的 409×100,051 次 ICG 锁存触发被忽视——该前提即为后被证伪的部分，见 TESTED）不触碰任何体系结构状态**，其全部工作——输入扫描、全量任务分发扫描（≥2 轮 fixed-point）、~160 个 commit 任务进入与历史稳定扫描、~2 条历史记录暂存+publish、roundSeed 单元 prologue——是双相 tick 强加的纯簿记开销。实测计数证据：每 eval 平均恰好 1 个输入变化（200,104/200,102）= clock；neg 侧 commit 入口占全部入口的 49.99%（16.59M/33.18M），neg 侧 compute 激活占 6.5%（64.8M/993.4M）。**若在 emit 时对每个 1-bit 输入端口做结构化资格分析（不依赖任何名称），证明该端口为唯一变化输入且发生 1→0 跳变时不可能有任何状态写、输出变化或系统/DPI 调用被触发，则该 eval 可压缩为：输入扫描（保持原有激活副作用）+ 直接暂存 P 相关事件的 (event 值, hist 态) 置零 + 返回，其开销相对整轮 fixed-point 可忽略。**
- **创新点**：首个针对"冻结驱动双相 tick"结构性浪费的消除；机制完全由通用语义特征触发（事件边沿方向集、操作数锥包含关系、P=0 常量折叠、quiescence 资格），无任何模块/端口名称匹配；kill-switch 同二进制对照臂消除构建间方差。
- **瓶颈证据（本分支实测）**：
  1. 上述边沿分裂计数：neg eval 的 commit 入口与 pos 几乎相等（任务进入+扫描开销），零 memWrite gate、port 发射恰 409 次/eval —— 当时解读为"进入而无发射、纯 overhead 形态"（事后看这 409 次正是 ICG 锁存的设计固有真实工作）。
  2. round 直方图：199,049/200,102 eval 恰为 2 轮，无 1 轮 eval —— 每个 eval（含全部 neg eval）都支付完整 fixed-point；hist 投影态变化强制第二轮。
  3. 先验量级估计：neg 侧 ≈ 16.6M commit 进入 ×（进入+扫描+采样） + 64.8M compute 激活 + 每 eval 分发扫描/发布固定开销，按 commit 相位 16.9 s、compute 51.5 s 的结构分摊，先验估计 **6–12 s（9–17%）**；将由 M-neg 基线实测取代。
- **微观指标与总目标的定量关系**：
  - **M-neg** = eval_ns_neg / eval_ns（EMU_RUNTIME_PROFILE 新增边沿分裂计时 `[grhsim-cpu-edge]`，诊断运行，端点 VALID；边沿分类为结构判定：唯一变化输入且 1-bit、方向下/上 → neg/pos，否则 other）。模型求值占 Host 99.5%（M1），eval_ns ≈ Host 内全部可优化时间；**消除下降沿 eval 的工作直接把 M-neg×Host 变为近零：Host 节省 ≈ (M-neg_base − M-neg_after) × Host**。每个 M-neg 百分点 ≈ 0.70 s ≈ 对 gsim 剩余差距（23.2 s）的 3.0%。
  - 辅证：fp_evals（fast path 触发次数，profile 计数）应 ≈ 100k（每周期一次）；rounds/evals 应自 2.005 降至 ≈1.5（neg eval 不再贡献轮次）。
- **预注册**：
  - M-neg 基线：同一二进制 kill-switch 关闭臂（`GRHSIM_IR_DISABLE_FP_ELISION=1` = 父语义 + 每 eval ≤3 次额外寄存器写）profile 诊断运行测得；该开销相对基线可忽略（<0.05%），并以 NO00002 归档二进制同窗口复测交叉验证。
  - M-neg 阈值：**≤1.5% 且相对基线下降 ≥80%**（测量：新构建 profile 诊断运行，端点须 VALID 精确匹配）。
  - fp_evals 阈值：≥ 99% 的下降沿 eval（≈100k；以 `[grhsim-cpu-edge]` 的 evals_neg 与 fp_evals 比对）。
  - 回退预算：新组 Host 均值 ≤ 旧组均值 ×**1.025**。
  - 最终性能提升判据：同一时间窗口 3+3 交替（预注册顺序 old1,new1,old2,new2,old3,new3，old=kill-switch 关闭臂、new=fast path 臂，同一二进制），**全部 3 次新运行均优于全部 3 次旧运行**（等价 Mann-Whitney U 单侧 p≤0.05）方可判定提升真实；无论是否提升均定量登记。
  - 证伪标准：M-neg 基线 **<3%** → 机制性证伪：下降沿 eval 在当前设计点已经不显著，登记机制证伪表（保留边沿分裂计时诊断设施，elision 代码回退）；M-neg 达标而 Host 无改善（秩次判据不通过且变化落入噪声）→ 同为机制性证伪：被消除的时间以他种形式回流（如 icache/分支局部性变化）。
  - 实现瑕疵路线：等价性失败（INVALID/mismatch）→ 回 IMPLEMENTED 排查；资格分析否决 clock 端口 → 分析否决原因，若为过度保守的实现 artifact 则修正后重测，若为设计固有（如存在 clock 锥内输出/锁存域）→ 机制性证伪并记录否决证据。
  - 验收：全流程门槛通过 + 100k 端点精确匹配（`instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`，退出 0，无 mismatch）+ M-neg 与 fp_evals 双达标 + 回退未破预算。

## 代码实施（IMPLEMENTED）

- **改动**（wolvrix 子模块 + 根仓库；冻结面零改动）：
  1. `wolvrix/lib/grhsim/backend/cpu_emit.cpp`（+828 行净增）：
     - `planFallingEdgeElision()`：对每个 1-bit 输入端口做结构化资格分析——全模型边沿项枚举（commit 域 + compute 侧系统/DPI 守卫的 `event_edges` 参数，(event, history, direction) 三元组）；按端口的值级依赖锥传播（`state.read` 截断、`memRead` 随地址传播）；资格要件：(a) 每个 P 相关边沿项均为 posedge 且事件在 P=0 下经三值常量折叠（`fpFold`，覆盖 and/or/xor/not/mux/concat/slice/eq/add/shl 等 compute 操作）确为 0；(b) 全部 commit op 的非事件操作数 P-free；(c) 全部 output.write 数据 P-free；(d) 全部含 system/DPI op 的单元均为边沿 quiescent（复用 `planComputeQuiescence` 结果）；(e) system/DPI op 的非事件操作数 P-free；(f) P 相关事件的反向锥内每个 P 相关 Boundary 值可暂存（1-bit、非别名、P=0 映像折叠确为 0），锥内出现 P 相关 memRead 结果/宽度≠1/别名/Object 存储即否决；历史态独占性校验（别名共享、非边沿引用即否决）。无任何名称匹配。
     - eval() 发射：输入扫描逐行记录 `cpu_chg_mask/cpu_chg_up`（每输入端口 1 bit，无映射行置毒）；扫描后结构化边沿分类（唯一变化且 1-bit 端口、方向）；随后对合格端口发射 fast path：清零该端口的 event 边界字节、history 态字节、锥暂存字节（静态 `constexpr` 偏移表），镜像正常退出尾（strobe 冲刷、输出写回、profile 记账）后 `return`，跳过 fixed-point 轮循环。运行时 kill-switch：模型构造时读 `GRHSIM_IR_DISABLE_FP_ELISION`（仅当存在合格端口才发射成员与代码）。
     - profile 边沿分裂：`CpuRuntimeProfile` 增加 pos/neg/other 三组桶 + `fp_evals`；原有 `[grhsim-cpu-phase]` 行保持格式输出总量（桶和），新增 `[grhsim-cpu-edge]` 行输出分裂；dynamic-stats 增加 `[grhsim-dyn] fp_evals`。
     - emit 诊断：每 1-bit 输入端口打印 `fp_elision: input <i> eligible events=.. hists=.. cone=..` 或带 16 个否决计数器的 rejected 行。
     - emit 选项 `--falling-edge-elision <true|false>`（默认 true）。
  2. `wolvrix/include/grhsim/backend/cpu_emit.hpp`：`emitCpuCpp` 增加尾部默认参数。
  3. `wolvrix/tests/grhsim/test_cpu_emit.cpp` + 新夹具 `tests/grhsim/data/cpu_fp_cone_main.cpp`、`cpu_fp_cone.mk`：`testFallingEdgeElisionDeepCone` 深锥回归测试。
  4. `scripts/wolvrix_xs_grhsim_ir.py`：`--disable-falling-edge-elision`（默认开启，opt-out）+ emit 诊断 info 级打印；`scripts/wolvrix_hdlbits_grhsim.py`：emit 诊断 info 级打印。
  5. `Makefile`：`XS_WOLF_GRHSIM_IR_DISABLE_FP_ELISION`（默认空=开启）透传。
- **语义约束**：只改发射的 C++ 形态与 eval 调度捷径；不改 GrhSIM IR、mapping、分区、调度、fanout 表与任何 op 语义；fast path 的输入扫描副作用（影子更新、激活置位）与暂存（事件/历史/锥字节置零）精确复刻被跳过 eval 的全部可观察效应；资格要件不满足时逐端口放弃且不发射任何 fast-path 代码。
- **与父节点差异**：eval() 新增变化掩码跟踪（每 eval ≤3 条 ALU）、边沿分类与桶选择（每 eval 一次）、合格端口 fast path 块；`CpuRuntimeProfile` 字段增加（打印格式向后兼容）；其余（IR JSON、mapping、调度、任务体、init、driver）逐字节一致为预期。
- **实施期缺陷回路（实现瑕疵，同节点内修正，两轮）**：
  1. 初版仅暂存 event/hist 字节。聚焦测试构造深锥模型（`clk→combined=and(clk,a)→event=and(combined,b)→regWrite`）时实跑复现：孤下降沿后紧接着的 posedge 因 `combined` 重算值等于陈旧字节而 change 检测断链，event 生产者不被激活，posedge 丢失、寄存器状态错误（elision 开 q=1 错 / 关 q=0 对）。→ 修正 R2：暂存集扩展至 P 相关事件全反向锥的 P 相关 Boundary 中间值（清零使 k+1 change 检测与被跳过 eval 逐字节一致），复现序列固化为回归测试（验证 pre-R2 红 / R2 绿 / kill-switch 绿）。
  2. R2 评审再发现反例：经反相器的恒 1 中间值（`h2=not(and(P,d))`，P=0 映像为 1）清零后同样断链。→ 收紧：仅暂存 P=0 映像折叠确为 0 的锥值，否则否决端口（`cone_image` 计数）；并补 sys_operand 检查封堵 system/DPI 数据操作数同类陈旧窗口。
- **聚焦测试**：
  - `make build`：通过，无告警。
  - `make test_grhsim_cpu_emit`：通过（含强化深锥回归，97–102 s）；`make test_grhsim_cpu_mapping`、`make test_grhsim_cpu_schedule`：通过。
  - `make test_benchmark_grhsim_ir`：通过。
  - `make run_hdlbits_grhsim_ir DUT=001/097/103`：全部通过；dut_097/103 日志 `fp_elision: input 0 eligible events=1 hists=1 cone=0`（clk 合格），reset/enable 端口被 `commit_operand`/`output_data` 计数否决（结构性否决证据）。

## 结果测试（TESTED）

### 全流程门槛与端点

- 生成 **806.78 s**、编译 **191.49 s**（均 <1800 s 门槛，exit 0）。
- 端点精确匹配（全部 15 次 100k 运行：phase 双臂 2 次 + 同二进制 3+3 共 6 次 + 锚定 3+3 共 6 次 + dyn 1 次）：`instrCnt=240,349、cycleCnt=99,996、guest=100,001、PC=0x80000c0c`，退出 0，无 mismatch → **VALID**。仿真单次均 <105.201 s 截止线。

### XS 资格分析结果：假设的结构前提被否决（无一端口合格）

生成期 `fp_elision` 诊断（ptmp/no00003_falling_edge_elision_20260924/gen.log），4 个 1-bit 输入全部被否决：

| 输入 | 身份 | 主要否决计数 |
|---|---|---|
| 0 | clock | negedge=2、commit_operand=418、system_units=1 |
| 1 | reset | not_zero=6、commit_operand=54,751、system_units=1、sys_operand=1,044 |
| 2 | difftest_perfCtrl_clean | commit_operand=51,158、system_units=1 |
| 3 | difftest_perfCtrl_dump | system_units=1、sys_operand=35 |

- 全端口共性否决项 `system_units=1`：资格要件要求**全部**含 system/DPI op 的单元边沿 quiescent，设计中存在 21 个非 quiescent 系统单元即否决一切端口。
- 后果：该二进制不含任何 fast-path 代码，`fp_evals=0` 恒成立；M-neg ≤1.5% 与 fp_evals ≥99% 两项验收指标在结构上不可能达到，验收路径让位于预注册证伪路径。

### 否决原因取证：下降沿 eval 做真实工作（设计固有，非实现 artifact）

env 门控取证（`WOLVRIX_FP_ELISION_DEBUG=1` reemit，ptmp 下 `reemit_dbg_offenders.txt` / `reemit_dbg_sysunits.txt` / `reemit_dbg_split.txt`）定位三类不可消除的下降沿工作：

1. **ICG 时钟门控锁存域**：clock 的 `commit_operand=418` 中 **409 个为 `latchWrite @build/xs/rtl/rtl/ClockGate.sv:11:13`，enable = `logicNot(clock)`（同文件 :11:8）**——下降沿更新使能锁存，k+1 周期的 gated clock 依赖其新值；其余为 8 个 DPI-helper regWrite + 1 个 SDCardHelper regWrite。纯 posedge 语义的标准例外，预注册证伪路线中明确点名的"锁存域"情形。
2. **negedge 边沿项 = 2**：clock 自身 `input.read` 上存在 2 个 negedge 方向边沿项（histories 247981/247983），要件 (a) 直接否决。
3. **非 quiescent 系统单元 21 个（188 个 op）**：difftest 相关 DPI/system 调用（`MainBtbAlignBank.sv:783`、`TageTable*.sv:4491`、`NewCSR.sv:6007/6009`、`MStatusModule.sv:169` 等），每个 eval（含全部下降沿）均执行。

→ "整体消除、视为纯簿记"的假设在结构上不成立：**第一重机制性证伪（设计固有）**。

### M-neg 基线实测（`[grhsim-cpu-edge]` 边沿分裂计时，诊断运行，端点 VALID）

同一无二进制 fast-path 二进制、双臂（kill-switch 开/关）各一次 100k：

| 臂 | eval_ns (s) | pos (s) | neg (s) | other (s) | **M-neg** | evals p/n/o | rounds p/n/o | fp_evals |
|---|---|---|---|---|---|---|---|---|
| baseline（kill） | 69.329 | 67.247 | 1.988 | 0.093 | **2.868%** | 100,048/100,051/3 | 201,146/200,102/9 | 0 |
| elision | 69.627 | 67.508 | 2.026 | 0.092 | 2.911% | 同上 | 同上 | 0 |

- 仪表 sanity：两臂 M-neg 差 0.043 pp（同一二进制的重复测量，读数应一致 ✓）；四相位桶 pos+neg+other 与 `[grhsim-cpu-phase]` 总量逐桶精确相等（向后兼容 ✓）。
- neg eval 单价 **19.9 µs/eval**，仅为 pos eval（672.5 µs/eval）的 **1/34**；neg 侧相位分解 compute 1.272 s / commit 0.660 s / publish 0.018 s。
- **M-neg 基线 2.868% < 3% 预注册证伪阈值 → 第二重机制性证伪**：即使存在能消除全部下降沿 eval 时间的机制，收益上限 ≈ 2.0 s（2.868%×70.134 s），低于显著性门槛。先验估计 6–12 s 被实测推翻（详见复盘）。

### dyn 计数核验（dynamic-stats 构建，诊断运行，端点 VALID）

- 本节点 dyn 运行与 NO00002 归档 dyn 运行 **32,144 个 dyn 键逐键一致**（`dyn.diff` 为空；比较前先剥离 ANSI 转义），传递性与 NO00001 原始 run.log 一致 → 新增簿记/仪表不改变任何动态行为。
- `[grhsim-dyn] fp_evals=0`（与 profile 侧一致）。
- **静态取证 ↔ 动态计数交叉验证**：取证清单中 409 个 ICG `latchWrite`（ClockGate.sv:11）与 dyn 计数 `port fire neg=40,920,859 = 409×100,051` 精确吻合——每个 clock 低电平 eval 恰好触发全部 409 个 ICG 锁存写，且为 neg 侧全部 port 发射（port_eval neg=40,920,860，每次进入均发射）；neg 侧 memWrite 门控恒为 0。下降沿"真实工作"的静态身份与动态规模闭环互证。

### 性能对照（3+3 交替，taskset -c 2，fadvise，截止 105.201 s，全部 VALID）

- **同二进制双臂**（噪声地板核验；XS 无合格端口时 kill-switch env 不改变发射代码，两臂等价于同码重复测量）：old 均值 **69.946 s**（SD 0.139）、new 均值 **70.081 s**（SD 0.268），差 +0.134 s（+0.19%）；秩次判据不通过（U=6，p=0.8）→ 与 NO00001 噪声底（0.22%）一致，登记为本节点运行噪声地板。
- **锚定**（NO00002 归档二进制 old vs 本节点二进制 new，跨构建 parity）：old 均值 **70.371 s**（SD 0.215）、new 均值 **70.231 s**（SD 0.229），new 名义快 0.140 s（+0.20%）；秩次判据不通过（U=2，p=0.2）→ **parity 成立**：新增的变化跟踪簿记 + 边沿分裂仪表对当前最佳点无可测开销。回退预算核验：70.231 s ≤ min(70.134, 70.371)×1.025 ✓，未破预算。

### 判定：**REJECTED**（机制性证伪，双证据均落在预注册证伪路线上）

1. **结构证伪**：下降沿 eval 含设计固有真实工作（409 个 ICG 使能锁存 + 2 个 negedge 边沿项 + 21 个非 quiescent 系统单元），"整体消除"假设不成立——对应预注册路线"资格分析否决 clock 端口且为设计固有"。
2. **量级证伪**：M-neg 基线实测 2.868% < 3% 门槛——对应预注册路线"M-neg 基线 <3% → 机制性证伪"。即便细化机制（保留真实 negedge 工作、仅消除可证惰性部分），其收益上限亦 ≤2.0 s；此类细化假设（原拟 NO00004 方向）须在该上限约束下重新评估。

### 代码处置：保留（不回退）

- fast-path 机制本身经深锥回归验证可靠（聚焦测试红/绿闭环），仅在 XS 上无合格端口而不激活（`fp_evals=0`、默认开启、锚定 bench 证明零回退）。
- 边沿分裂计时（`[grhsim-cpu-edge]`）是本节点交付的锚定测量设施；资格分析器与 16 个否决计数器、env 门控取证（`WOLVRIX_FP_ELISION_DEBUG`）是后续机制分析的直接基础；`--old-env` bench 支持与同二进制 kill-switch 协议并入标准测量协议。

## 定量复盘

- **先验 vs 实测：6–12 s（9–17%） vs 上限 2.0 s（2.87%），高估 3–6 倍**。错误来源：以结构计数（neg 侧 commit 入口 16.6M，与 pos 持平）直接推断时间开销，未标定单次进入单价。实测表明 neg eval 虽确含发射（每 eval 恰 409 次 ICG 锁存 port 写，fire=eval），但 commit 任务的"进入+扫描"本身极廉价、memWrite 门控为零、compute 激活仅为 pos 的 6.6%，合计单价仅 19.9 µs/eval。**教训：由结构计数推断时间必须先以单价实测标定；计数持平 ≠ 时间持平。**
- **假设的结构性前提未经直接检验即进入实现**。"纯 posedge 设计"系由聚合计数断言（且早期记录还误把 neg port fire 当作 0——实测 40.9M 次 ICG 锁存触发就存在于当时的归档 dyn 日志中），而 ICG 使能锁存（enable=¬clock）是纯 posedge 语义的标准例外，quiescence 资格与锁存域检验在 HYPOTHESIS 阶段即可由资格分析器先行扫描证伪（成本为一次 reemit，约分钟级）。**教训：资格/可行性扫描应先于机制实现运行（analyzer-first）；本节点实际顺序为分析器与实现同建、XS 扫描在实现完成后才执行，导致实现成本沉没于一个可被预先证伪的假设。**
- **节点净产出**（尽管 REJECTED）：M-neg 锚定基线 2.868%（neg 单价 19.9 µs vs pos 672.5 µs）；XS 下降沿真实工作的完整身份清单（ICG/negedge 项/系统单元的 SV 定位）；边沿分裂计时与资格分析诊断设施并入主线；同二进制噪声地板 0.19% 复测确认。总目标差距维持在 23.2 s（NO00002 为当前最佳指针，不动）。
