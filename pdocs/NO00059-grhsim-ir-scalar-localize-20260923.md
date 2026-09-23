# NO00059：compute 单元标量值寄存器化 + 宽常量静态提升（组合攻 per-op 成本）

- 状态：进行中（2026-09-23 设立）。
- 用户附加要求：①解决 per-op 成本问题（NO00058：2.36× 每 op 指令数为差距本质）；
  ②允许修改 emit（NO00057 的 emit 层禁令由用户解除）；③多个优化组合达成 ≥3% 优化。
- 数据版本：基线 NO00055（wolvrix `7b1fd50`），预注册比较值 **71.309667 s**；
  old 对照 `ptmp/no00055_init_zero_elide_20260922/flow-final`。

## IDEA

### 假设

NO00058 确证求值体积仅 1.20×、每 op 指令数 2.36×（3.84 vs 1.63）是差距本质；
代码级解剖（本节点侦察，见下）确证 3.84 的构成 ≈ 1 条逻辑 + ~1.7 条 load/store
物化 + ~1 条 changed 检测/写回（摊薄）+ ~0.8 条扇出/调度（摊薄）。**物化的根源是
存储类别**：GrhSIM-IR 把单元内纯局部值放进 `std::byte cpu_local[N]` 内存帧，
经 `cpu_at<T>(base,off)` 类型双关访问——混合类型单 alloca 形态 LLVM SROA 不可拆，
导致 78% 的动态 op（纯 local op）每条付出 1 存 + 若干取的内存往返；而 gsim 的
`isLocal()` 规则让同类值成为 C++ 局部变量直接驻留寄存器，每 node 逼近 1 条 ALU。

**假设 H1**：把 compute 单元内 PartitionLocal 标量值从内存帧改为类型化 C++ 局部
变量（SSA 直发），可消除其全部 load/store 往返，显著降低每 op 指令数。
**假设 H2**：宽常量（>64bit）每次激活在栈上重新物化 `std::array` 临时量并整体 store
（典型 128 字 = 1KB/次），提升为文件级 `static const` 数组后该物化消失。

### 机制（组合）

- **M1 标量定位化（`--localize-scalars`，纯 emit）**：compute 单元内
  `slot.kind==PartitionLocal` 且类型为标量（非 std::array 宽值、非 string）的值，
  发射为产生点 `T cpu_v<index>{};` 声明 + 赋值；读侧经 `value()` 唯一漏斗返回裸标识符。
  残留宽值/string 继续走 `cpu_local` 帧（发射侧重打包 offset 使帧缩小）。
  含 `cpu_helper_` noinline 调用（整帧逃逸，35 个 task 文件，1.2%）的单元整体保持旧形态。
  changed 检测/扇出与 PartitionLocal 值结构性零耦合（computeEdges 只含跨 owner 依赖），
  不动。
- **M2 宽常量静态提升（`--wide-const-static`，纯 emit）**：PartitionLocal 宽常量值
  登记为文件作用域 `static const std::array<uint64_t,N> cpu_wconst_<n>`，
  `value()` 返回其名，compute 尾部不再发物化 store（扩展 staticScalars_ 跳过逻辑）。
  Boundary 宽常量不动（镜像语义需要写回）。

### 为什么既往关闭证据不适用于本方向（NO00058 §5 硬性指导第 3 条）

| 关闭证据 | 为何不适用 |
|---|---|
| NO00002 移除 cpu_local 零初始化无收益 | 只删 `{}`、保留内存帧形态；本机制删除内存形态本身 |
| NO00047 物化门三变体回归 | 那是加运行时条件跳过（控制流扰动惩罚）；本机制不引入任何新分支，控制流不变 |
| NO00056/57 "删 op/收窄/折叠对 clang 反向" | 那些变换删除值域信息（掩码）或改变 ALU 形态；本机制逐 op 保持计算表达式文本不变，只改结果存储类别（内存→寄存器是单向减指令） |
| NO00057 boundary 写回打包回归 | 本机制完全不触碰 boundary 写回路径 |
| NO00050 fanout 批量 OR 失败 | 本机制不触碰扇出发布 |
| emit 层禁令（NO00057 附加约束） | 用户 2026-09-23 明确解除 |

### 收益上界与证伪标准

- 上界估算：物化 ~1.7 instr/op 中 local op 部分（78% 动态）若消除 ~1.5 条/op，
  指令数可降 ~25%×0.78 ≈ 15-20%；compute 占 75% 时间 → 理论池 ~10% 量级。
  M2 池：宽常量动态物化（endpoint 单元 1.67G 次/run 常量物化的一部分）。
- **筛查门**：1-2 对交替（仅方向证伪）new 不快于 old 即证伪当次变体；
  **验收门**：6 次交替秩次判据 + 组合收益 ≥3%（用户要求）。
- 次级判据：生成代码 model .text 变化、每 op 指令数（perf stat）应向 1.63 方向移动。

### 侦察结论（实施依据，agent 复核自 wolvrix `7b1fd50` + flow-final 生成代码）

- 唯一读漏斗 `Emitter::value()`（`wolvrix/lib/grhsim/backend/cpu_emit.cpp:1625-1636`），
  全文件唯一 `"cpu_local"` 字面量；写点 `compute()` 尾部 `:3056-3094`；
  帧声明点 `:4493`；帧尺寸来自 ctor `:358`（layout 不动，checkpoint 校验零风险）。
- 逃逸普查：2,295/2,842（80.8%）含 cpu_local 的文件无硬逃逸但仍为内存形态
  （反汇编 task_1002.o：33% 栈相对寻址）——SROA 不可拆混合类型 alloca 实锤。
- 类型化局部先例已在生产形态运行（`cpu_cached_state_`/`cpu_cached_value_`）。
- 每槽位写先于读有 NO00002 全量仿真实证；单元体直线发射。
- 共享机制接线：新标识符前缀须加入 `cpu_shape_share.cpp:13 kTaskPrefixes` 与
  `cpu_block_share.cpp:16-17 kBlockPrefixes`；`undeclaredIdFree` 按类型关键字
  识别块内声明，类型化声明安全。分组重排与热度 TSV 失配风险按 NO00056 纪律实测复核。
- flag 管线：`registerCpuEmitPasses`（`:4712-4757`）/`EmitCppPass`（`:4662-4682`）/
  `emitCpuCpp`（`:4684-4707`）/`cpu_emit.hpp:11-15`/ctor `:333-348`；
  pybind 自动转 kebab 无需改；脚本 `scripts/reemit_grhsim_ir.py`、
  `scripts/wolvrix_xs_grhsim_ir.py`；Makefile `reemit_grhsim_ir` env 映射。

## BASELINE

- old：NO00055 flow-final（预注册比较值 **71.309667 s**，wolvrix `7b1fd50`，
  emu 已存在 `ptmp/no00055_init_zero_elide_20260922/flow-final/emu/emu`）。
- 输入：`testcase/xiangshan/ready-to-run/coremark-2-iteration.bin`，100k cycles，
  `XS_NUM_CORES=1 XS_EMU_THREADS=1 XS_EMU_CPU=2`，trace 全关。
- 止损线：仿真达到 71.309667×1.5 ≈ 106.96 s 立即终止记 REGRESSION_KILLED；
  生成/编译各 1800 s TIMEOUT_KILLED。编译并行度 nproc=32（VM_BUILD_JOBS=32）。
- 迭代策略：reemit（读 `ptmp/no00054_branch_shape_fold_20260921/flow-final2/xiangshan_grhsim_ir.json`
  checkpoint，跳过 SV 前端）做筛查；筛查通过后走完整 `xs_wolf_grhsim_ir` 全流程验证。
  reemit flags 与 NO00055 对齐（commit-compact-walk / commit-mem-walk /
  shape-twin-share / branch-shape-share / hotness TSV / budget 5.0）+ 本节点新 flag。
- 零差异纪律：新 flag 关闭时 reemit 产物须与 NO00055 flow-final model 逐字节一致。
- 判定协议：`make benchmark_grhsim_ir`（GRHSIM_IR_BENCH_PAIRS=3，page-cache 驱逐，
  预注册顺序 old/new 交替），秩次判据（3 新全优于 3 旧，U≤3 即 p≤0.05）。

## IMPLEMENTED

- 改动（wolvrix 工作区，未提交）：`lib/grhsim/backend/cpu_emit.cpp`（+273 行：
  `--localize-scalars`/`--wide-const-static` 解析、Emitter 成员与 ctor 透传、
  `value()` 漏斗定位化支路、写点声明/赋值发射、残留帧 offset 重打包、宽常量
  文件级 static 表）；`lib/grhsim/backend/cpu_shape_share.cpp` / `cpu_block_share.cpp`
  （新前缀 `cpu_v`/`cpu_wconst_` 接入 kTaskPrefixes/kBlockPrefixes 归一化）；
  `include/grhsim/backend/{cpu_emit,cpu_block_share}.hpp`；`tests/grhsim/test_cpu_emit.cpp`
  +178 行新用例（flags on 形态断言）+ `tests/grhsim/data/cpu_localize_{main.cpp,mk}`。
- 单测：wolvrix grhsim 测试 100% 通过（build-test2.log，102.75 s）。
- 零差异校验：flags off + `--no-srcloc-comments` 重发射（flow-zerodiff）与同一代码库
  stash 出的 stock `7b1fd50` 参考（flow-zerodiff-ref）逐字节一致：**4548/4548 源文件
  全等 + checkpoint JSON 全等**（zerodiff-vs-stock.log 为空）。与 NO00055
  flow-reemit/flow-final 对比仅 `grhsim_SimTop_shapes.cpp` 一个文件存在差异，且差异
  仅为共享函数体中 `// cpu_*` 行尾标记注释的保留——这是基线 HEAD 预存提交 7b1fd50
  （srcloc 链路）文档化行为（"shape/block text sharing preserves line comments"），
  与本节点改动无关（stock 对照即铁证）；stats 与 NO00055 reemit.log 逐项一致
  （shape_twin 231/1080/769439/33；branch_block 1515/6866/652357/610/779/
  4.988081/186436882）。注：对比运行统一加 `--no-srcloc-comments` 以中和该预存特性
  （NO00055 产物生成于该特性落地前）。
- flags on 发射统计（reemit-localize.log）：**localize_units=30,083 /
  localize_values=2,501,220**；helper 逃逸单元降级 89 个（6,731 值保持内存形态）；
  单元帧总量 **4,247,256 → 360,616 B（−91.5%）**，28,850 个单元帧整体消失；
  wide_const_statics=58（519 字）。
- 共享分组未崩塌：shape_twin 231→230 组 / 1,080→1,079 实例；branch_block
  1,515→1,484 组 / 6,866→6,768 实例 / 排除热组 779→801（热度 TSV 沿用 NO00054）。
- 生成源文本体量（flow-reemit vs flow-localize，同口径实测）：纯源文本
  （.cpp/.hpp 拼接字节）776.8M → 760.9M（−2.0%）；含 .o 目录体积 874.0M →
  860.7M（−1.5%）；文件数 4548 不变。
- fresh 编译（VM_BUILD_JOBS=32，build-localize.log 尾部 `time` 实测）：
  **real 306.5 s**（user 62m34s）；NO00055 build-final.time 记录 195.30 s。
  +57% 墙钟待排查（疑似 clang 对类型化 SSA 局部值的优化/寄存器分配工作量上升；
  日志在 -j32 共享 fd 下存在回显交错，.o mtime 为单波次，无真实重复编译）。
- 生成形态示例（task_100.cpp）：单元头 `std::uint64_t cpu_v0{};` 类型化声明 +
  产生点赋值；task_117 残留帧缩至 `cpu_local[1]`。

## SCREEN

- 筛查运行（`make benchmark_grhsim_ir`，PAIRS=1，page-cache 驱逐 + taskset CPU2，
  输出 `ptmp/no00059_scalar_localize_20260923/screen2`，日志 screen2.log）：
  **old1=71.315 s / new1=71.420 s（−0.15%，方向持平）**；两组 endpoint 完全一致
  （instrCnt=240349, cycleCnt=99996, guest=100001, pc=0x80000c0c），difftest 无
  mismatch、NEMU 正常终止——功能等价成立。
- 另一组同内容运行（screen1，由并行流程在 14:20-14:22 触发，new1 尾部与
  dynamic-stats 复核 reemit 重叠，计时被污染）：old=71.235 / new=72.196（−1.35%），
  仅作存证，不作判定依据。
- 次级判据（perf stat 全量运行各一次，perf-{old,new}.txt）：总指令数
  **536.18G → 547.37G（+2.09%，未向 1.63 方向移动）**；emu .text
  82.60MB → 83.24MB（+0.77%）。
- dynamic-stats 组合可编译性：`--dynamic-stats` + 两新 flag reemit 成功
  （flow-dynstats），探针编译 task/shapes TU 通过（probe-dyn/）。
- **筛查门结论：new 不快于 old（持平偏负），且指令数不降反升 —— 当次变体
  按筛查门证伪。** 机制本身按预期落地（定位化/静态提升生效、零差异纪律满足、
  单测与等价性全过），性能假设 H1 的指令数削减未在 ISA 层面出现。

## SCREEN 之后：M1 失败根因（全二进制逐函数 diff，2026-09-23 下午）

变体 1 证伪后做了根因复核，方法：新旧 emu 全二进制 `objdump` 逐函数指令分类
（`ptmp/no00059_scalar_localize_20260923/diag/emu-{old,new}.funcs`，各 ~13.0M 指令）。

- **增长主战场是非共享 task 体而非共享体**：2,921 个两侧均为实体的 task 合计
  **+218,776 指令 / +99,393 cmov / +24,157 栈流量**；shape 类 +8,264、blk 类 −27,763
  （shape/blk 编号随分组重排，个体对比无效，仅类别总量有效）。全二进制 cmov
  365,987 → 484,985（**+32.5%**）；rsp 相对 mov 仅 +1.07%（帧≈SSA 全程序成立）。
- **M1 未越界**：热度 top20 中全部 commit 任务（task_3949-3991 段）新旧逐字节
  全等（task_3974/3970/3964… +0、cmov 0）；热 shape 全部 +28~+290。动态 +2.08%
  指令增长来自热 compute 体。
- **共享机制形态**：4,440 个 cpu_task_* 中 1,077 个为 4 指令跳板
  （`lea 参数表; xor %edx; jmp cpu_shape_N`），即 shape 体承载 ~1,080 个 task 的
  全部 compute。
- 结论：M1 失败非"帧存储优秀"，而是 **clang 早已把定址帧槽分配进寄存器**
  （栈流量新旧全等为铁证），SSA 可见性唯一解锁的是更激进的 if-conversion，
  且在 mux 密集的非共享 task 上放大（个别 +200~900%）。H1 彻底证死
  （FAILED 判定后代码随节点一并回退，见判定节）。

### 钉死级实证：shape_0 反汇编取证（2026-09-23 晚，回应"是否 clang 已提升帧槽"之问）

对最热共享体 shape_0 新旧两份 `objdump`（diag/shape0_{old,new}.s）逐指令核查，
"(a) 帧从来不是真流量" vs "(b) SSA 值被 1:1 溢出回栈" 两种解释得到明确裁决：

- **帧对象在机器层根本不存在**：旧 shape_0 序言只有 6 个 push，**无 `sub $N,%rsp`**；
  源中 `alignas(8) std::byte cpu_local[105]` 整个落进 SysV 128 字节 red zone
  （访问全部为 `-0x10(%rsp)`…`-0x6a(%rsp)` 负偏移）。帧连"被分配的栈对象"都不是。
- **mux 依赖链中间值全程寄存器直传**：源中 63,64→10→69,70→13→75,76→16 的
  `(D&A)|((D^1)&B)` 链编译为 `and %dil,%r15b; xor $0x1,%dil; and (%rbx,%r14,1),%dil;
  or %r15b,%dil`（结果留 %dil）→ 后续节点 `and %dl,%al` 等**直接寄存器消费前驱
  结果，链节点之间零 store/reload**。red zone 里仅有的流量是长命指针（参数表
  `-0x68(%rsp)` 反复回载）与个别长程值溢出——寄存器分配器的常规 spill，与源码
  存储类别无关，新旧必然一致（rsp-mov 占比 18.78%→18.69% 由此解释）。
- **裁决：(a) 成立**。SROA/mem2reg 对定址（常量下标）字节数组的提升是彻底的，
  M1 的前提"帧槽访问是内存流量、定位化可削减 per-op 成本"**自始无效——没有可
  消除的流量**。我们想交给 clang 的变换，它早已做完。
- **回归机制（为何不止零收益而是 +2.09%）**：源码形态变化扰动 clang 启发式，
  bool mux 代数 `(D&A)|((D^1)&B)` 在旧形态下编为紧致 and/or/xor 字节序列
  （4 条、内存操作数融合），新形态下被 if-conversion 翻成
  `movabs $mask; and; xor %eax,%eax; test; cmove` 链（≥5 条 + cmov 双臂寄存器
  压力）。shape_0 内 and/or/xor 字节运算 60+→4，cmov 117→243；全二进制 cmov
  +32.5% 皆源于此。同一语义、更贵的指令形——纯启发式抖动，非任何真实成本变化。
- **对方向的终局含义**：凡仅重排标量"住在哪里"（帧/局部/成员）的 emit 变换，
  对定址访问在最好情形下是 no-op、在最坏情形下是启发式扰动。**存储类别变换
  方向整体判死**。

## 变体 2（C1+C2 组合）：write_cell 快路径 + 宽常量静态提升

### 设计依据

指令画像（30k cycles perf record，diag/prof-full.txt）：task 59.0% /
shape 18.9% / blk 5.0% / **write_cell 5.84%**（`cpu_write_cell<bool,1>` 单函数
4.53% 为全 binary 第一热点）/ eval 4.31% / helper 3.9%。最热 compute 体
（shape_0）指令构成：纯逻辑 ~1.02/op（已与 gsim 持平），其余为常数表 load
（共享机制固有）+ 栈溢出（寄存器压力，SSA/帧等价）——compute 单元内部已无
emit 侧空间，收益必须来自框架侧。write_cell 调用 131 条体 + 10 参数 ABI，
34,879 个调用点，dominant 情形（no-change）只需 load+cmp 却付完整 call 开销。

### 机制（C1，`--write-cell-fastpath`，纯 emit）

常量 mask 的标量单元格写点（memWrite 常量 mask / memWriteSeq / memFill，
≤64 位无符号）发射内联块：预算 key/offset → 读 current → 与常量折叠后的合并值
比较 → **未变直接结束（无 call）**；变了调新慢路径 helper
`cpu_write_cell_slow<T,W>`（收预算好的 key/offset/merged，Pending 记录与截断
语义与原 helper 逐项一致）。signed 元素保持原路径；慢路径模板仅 flag on 时
发射。详见 `wolvrix/docs/grhsim_ir/backends/cpu.md` "写单元格快路径" 节。

### IMPLEMENTED（变体 2）

- 改动（wolvrix 工作区，未提交）：`lib/grhsim/backend/cpu_emit.cpp`
  （`writeCell()` 快路径支路 + `cpu_write_cell_slow` 慢路径模板 + flag 管线），
  `include/grhsim/backend/cpu_emit.hpp`（emitCpuCpp 第 15 参），
  `lib/grhsim/backend/cpu_block_share.cpp`（kSafe 加 `cpu_dirty`/
  `cpu_write_cell_slow`；scanBranchBlocks 重构去重）、
  `lib/grhsim/backend/cpu_shape_share.cpp`（scanShapeTwins 重构）、
  `include/grhsim/backend/cpu_shape_scan.hpp`（`cpu_write_cell_slow<` 常量槽保护）、
  `tests/grhsim/test_cpu_emit.cpp`（testWriteCellFastpath：on/off 两变体文本断言
  + ASAN/UBSAN 32,768 样本语义全等）+ `tests/grhsim/data/cpu_writecell_{main.cpp,mk}`；
  脚本 `scripts/reemit_grhsim_ir.py` / `scripts/wolvrix_xs_grhsim_ir.py` /
  `Makefile`（reemit + 全流程 env 映射）。
- 单测：`make test_grhsim_cpu_emit` 100% 通过（build-test8.log，104.68 s）。
- reemit（NO00054 checkpoint + NO00055 对齐 flags + C1+C2，reemit-c1.log）：
  **write_cell_fastpaths=34,879**；shape_twin 231/1080 与 branch_block
  1515/6866/779/4.988081/186436882 **与 NO00055 基线逐项全等**（共享分组零扰动）。
- 零差异校验：flags off + `--no-srcloc-comments` 重发射（flow-zerodiff3）与
  stock `7b1fd50` 参考（flow-zerodiff-ref）**4547/4547 源文件 + checkpoint JSON
  逐字节全等**（zerodiff3-vs-stock.log 为空）。
- emu 构建（build-c1.log，VM_BUILD_JOBS=32）：~200 s；.text 82.60MB → 83.19MB
  （+0.72%）。

### SCREEN（变体 2）

- 筛查运行（`make benchmark_grhsim_ir`，PAIRS=1，输出 screen-c1，日志
  screen-c1.log）：**old1=71.442 s / new1=79.658 s（−11.50%，严重反向）**；
  两组运行 endpoint 有效（脚本校验通过，exit=0）。
- 次级判据（perf stat 100k 全量各一次，diag/{old,c1}.stat）：

  | 指标 | old | C1 | delta |
  |---|---|---|---|
  | instructions | 536.23G | 510.59G | **−4.78%** |
  | ex_ret_ops | 575.41G | 549.27G | −4.54% |
  | L1-dcache-loads | 294.56G | 300.34G | +1.96% |
  | branches | 20.69G | 19.36G | −6.43% |
  | **branch-misses** | **3.22G** | **5.04G** | **+56.55%（+1.82G 次）** |

- **筛查门结论：按门证伪。** 指令数按设计下降 4.78%（内联确实删了指令），但
  分支误预测 +1.82G 次（≈31G cycle 惩罚 @~17 cycles/次）反超，净 −11.50%。

### C1 失败根因：helper 的分支预测器共享红利（结构性，不可挽救）

- helper 形态下 `if(current==next)return;` 全程序只有**一份分支实例**，34,879
  个调用点共享；TAGE 类预测器以全局聚合历史（绝大多数 no-change）把它预测得
  极好。内联后每站点一个**独立分支实例**：热站点数千个稀释 BTB/预测器容量，
  局部历史噪声远大于聚合历史，近半变更的站点等同抛硬币。
- 推论：**任何"把 no-change 检查挪到调用点"的变体同病**（bool,1 子集、
  `__builtin_expect`、always_inline 前置检查均不能恢复共享分支实例）。
  保留 call 形态下的收益上限只剩参数装载压缩（~0.3-0.6% 指令），对 ≥3%
  目标无意义。C1 方向证死（FAILED 判定后代码随节点一并回退，见判定节）。
- 同族教训（第三次撞上同一堵墙）：NO00047 物化门（运行时条件跳过的控制流
  扰动惩罚）、commit walk 停顿池（18% 为误预测+L1 非指令）、本节点 C1。
  **热点路径上新增独立分支实例 = 预测器容量税，指令数收益不能抵扣。**

### 剩余方向天花板定量评估（2026-09-23 晚，old emu 实测）

C1 证伪后对全部剩余候选做了量级测算（数据：diag/brmiss-old-report.txt
30k cycles 分支误预测归因 836M 次采样；diag/old-icache.stat 100k 全量
icache/iTLB 基线）：

- **存量分支误预测归因**（总 3.22G 次/run ≈ 55G cycle ≈ 25% 运行时间）：
  eval() 7.72%、commit/memWrite 任务族合计 ~40%（task_3964 5.79 / 3974 4.46 /
  3991 3.43 / 3990 3.30 / 3965 2.67…）、write_cell<bool,1> 2.49%、
  direct_state_changed 1.58%，其余平摊数百函数。**顶部无支配性单点，且
  commit 族分支是 guest 数据依赖的 per-port enable/guard 判断，本质不可预测**
  ——治理需重构求值模型（架构级），emit 侧无可行切口。
- **C3 热 shape 取消共享**（移除参数表 load，shape_0 的 377/2791≈13.5% 指令）：
  指令池上限 ~2%；但 old icache miss 基线已达 1.196G/run（热区远超 L1i），
  顶级组 ~10 实例 × ~11KB/份复制将加 ~0.5-1% icache 税——净收益预期 ≤+1.5%，
  不够 3% 且带回归风险。
- **eval() 内部优化**：4.31% 指令 + 7.72% 误预测，可动部分上限 ~1%。
- **write_cell 参数打包 / C2 宽常量**：各 ~0.3-0.5%。
- **结论：emit 侧全部候选最优叠加 ~3%（四个机制全中且零反噬的理论上限），
  不构成可靠路径。** ≥3% 需架构级方向（减少动态求值次数 / NBA 重构 /
  commit 族数据依赖分支治理），属多日工程，或需重定目标/人工判定节点。

## VALIDATED（变体 2）

（变体 2 已于筛查门证伪，未进入验收；本节留空。）

## 判定

**FAILED（用户人工判定，2026-09-23）。**

- 附加要求（①解决 per-op 成本、②可改 emit、③多优化组合 ≥3%）下两波组合均于
  筛查门证伪，未进入正式验收：变体 1（M1 标量定位化 + M2 宽常量静态提升）
  −0.15% 且指令 +2.09%；变体 2（C1 write_cell 快路径 + C2）−11.50%。
  剩余候选经定量评估最优叠加仅 ~3% 理论上限（四机制全中且零反噬），不构成
  可靠路径；连续三轮无路径后提请人工判定。
- **代码处置**：按失败节点惯例全部回退——wolvrix 恢复与 `7b1fd50` 零差异
  （`--localize-scalars` / `--wide-const-static` / `--write-cell-fastpath`
  实现、单测与文档小节一并移除）；根仓库 `Makefile` 与
  `scripts/{reemit_grhsim_ir,wolvrix_xs_grhsim_ir}.py` 的 flag 接线一并回退。
  诊断证据归档 `ptmp/no00059_scalar_localize_20260923/diag/`（新旧 emu 全二进制
  逐函数 diff、shape_0 新旧反汇编、perf stat/record 全套）。
- **方向关闭**：
  1. **存储类别变换整体判死**——标量"住在哪里"（帧/局部/成员）对定址访问
     最好情形 no-op（clang SROA/mem2reg 早已提升，帧甚至不进栈、整个落 red
     zone），最坏情形扰动 if-conversion 启发式触发 cmov 回归（本节点 +2.09%
     指令即此机制）。
  2. **no-change 检查内联/调用点前置判死**——helper 共享分支实例的预测器
     红利结构性无法在内联形态下保留（NO00047 物化门、commit walk 停顿池之后
     第三次独立复证"热点路径新增独立分支实例 = 预测器容量税"）。
- **移交**：≥3% 在 emit 侧已无可行切口；剩余方向唯架构级（减少动态求值次数 /
  NBA 重构 / commit 族 guest 数据依赖分支治理，存量误预测 3.22G 次/run≈25%
  运行时间的主要载体），属多日工程，宜经 NO00058 画像基线评估后单独立项。
- 当前最佳仍为 NO00055（71.309667 s，对 gsim 1.518363×）；下一节点 old 对照
  不变（`ptmp/no00055_init_zero_elide_20260922/flow-final`）。
