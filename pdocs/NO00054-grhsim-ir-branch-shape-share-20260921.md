# NO00054 GrhSIM-IR 分支体形状共享（P1a）

- 日期：2026-09-21
- 状态：**ACCEPTED**（2026-09-22，正式门 flow-final2：回退 +0.740% ≤3%，model .text −8.50%）
- 基线提交：wolvrix `4828c90` / 根仓 `b227d64`（NO00053 ACCEPTED 状态）
- old 对照：`ptmp/no00053_shape_twin_share_20260921/flow-final`，预注册比较值 **71.408333 s**（goal.md 已登记）
- 验收门（2026-09-21 用户调整门）：100k 行为正确（6/6 NEMU PASS、endpoint 与 old 一致）+ 6 次交替统计回退 ≤3% + 二进制减小/缓解 ICache
- 主目标：减小二进制指令体积（model .text），缓解 ICache 压力；允许 ≤3% 性能回撤

## 机制（一句话）

发射端在 task 文本渲染后（shape-twin 共享之后）追加一道文本管线：把 `if(cpu_active_word&N){...}` 分支体按"形状相同、仅常量不同"分组，每组提取为一个 `__attribute__((noinline))` 共享成员函数 + 每实例块作用域 `static const` 常量表（u32/u64 分表），分支内只留位清除、表声明与调用。

## 设计要点

- **管线位置**：`foldShapeTwins` 之后。此时孪生 task 已是瘦包装（无分支），单例 task 文本中的分支体为纯字面量常量，可直接落静态表；shapes.cpp 共享体内的分支（1,696 个，常量本是运行时槽值）v1 不处理（栈装表开销会吃掉收益）。
- **提取单位**：`if(cpu_active_word&N){` 花括号配对块；剥掉行首 `cpu_active_word&=~N;`（留在调用点）；嵌套守卫不单独提取（随外层一起进 helper）。
- **接口**：`void GrhSIM_SimTop::cpu_blk_<gid>(const std::uint32_t*, const std::uint64_t*)`；分支体引用 `cpu_active_word` 的组（嵌套守卫 / `cpu_helper_` 调用）追加 `std::uint8_t &cpu_active_word` by-ref 参数。helper 自带 `cpu_obj_/cpu_bnd_/cpu_shadow_` 前导声明（成员指针 .get()），分支体自包含（`cpu_local`/`cpu_changed_N`/`cpu_cached_*`/`cpu_value` 均在分支内声明，普查 25,172 分支 undeclared=0）。
- **排除规则**（满足其一则整组不折）：体含 `return`/`goto`/`break`/`continue`（字符串字面量屏蔽后判定）；体含 `cpu_shape_p` 槽引用（shapes.cpp 内分支）；分支词法上位于循环体内（bank-scan 循环化属另一机制，v1 不动）；体使用未在本分支内声明、且不在安全集合（成员 `cpu_flags/cpu_pflags/cpu_read_offsets/cpu_at/cpu_write_cell/cpu_helper_*`、by-ref `cpu_active_word`）内的 `cpu_` 标识符。
- **标记化与校验**：复用 NO00053 形状扫描器（值位置数字/UINT_C → 槽位；`std::array<>`/模板实参/`alignas`/`cpu_local[N]` 声明界/constexpr 行/字符串字面量永不参数化；标识符规范化 `cpu_cached_value_/cpu_cached_state_/cpu_men_` 之外块级追加 `cpu_changed_`）；内置 round-trip 自校验 + 非变异槽位拼写跨实例一致性断言。
- **阈值**：minSourceBytes=1500（普查显示池几乎全在大体上，T=1500 与 T=500 收益差 <0.1%）。
- **产物分片**：helper 定义按累积字节分片为 `<prefix>_blocks_<k>.cpp`（单片 ≤12MB 源文本），避免单 TU 过大威胁 1800s 编译门。
- **开关**：`cpu.st.emit-cpp --branch-shape-share <true|false>`（默认 false），xs 管线 `scripts/wolvrix_xs_grhsim_ir.py` 开启。

## 普查数据（ptmp/no00054_branch_shape_fold_20260921/，脚本 branch_census.py）

输入：NO00053 flow-final/model（4,440 个 task/shapes 源文件）。

- 分支总数 25,172，总源文本 761.4MB；唯一形状 14,634。
- 排除：shapes.cpp 内 1,696（其中 1,687 含槽引用）、`return` 49、`break/continue` 0、引用 `cpu_active_word` 8,976（by-ref 参数后可折）、未声明标识符 0。
- 可折（仅 task 类实例、组内 ≥2 实例）：**2,483 组 / 11,930 实例 / 实例源文本 333.4MB，毛折叠 263.1MB 源文本**。
- 源文本→.text 校准比率 0.08（task 848.1MB→68.33MB，shapes 51.1MB→4.05MB，两处一致）→ 毛收益 ≈ **21.0MB .text**（对 model .text 75.1MB 约 −28%），调用点开销 ~12k×30B 可忽略。
- 阈值扫描：T=500…6000 毛收益 263.0→262.3MB，池集中于大体；取 T=1500。
- 结果文件：`branch_census_v3.json`（v1/v2 为过程稿）。

## 结果

### reemit 冒烟（同 checkpoint 快速通道，2026-09-21）

- 生成：`branch_block_groups=2294 branch_block_instances=10645 branch_block_varying_slots=1441092 branch_block_skipped=610 branch_block_folded_source_bytes=297821370`；shape_twin 输出 231/1080/769439 与 NO00053 逐值一致（重构零行为变化）。
- 语义校验：全部 10,645 个折叠实例做"helper 槽位代回 vs 原分支体"全文重建比对，**0 失配**（校验脚本将 `UINT_C` 拼写归一后）。
- 生成源文本：task 848.1→560.4MB，blocks 新增 73.2MB（6 片），总源文本 951.8→737.6MB（−22.5%）。
- **.text（clang++ -O3，与 old 同工具链同 flags）：75,128,469 → 63,827,598，−11,300,871 B（−15.04%）**。
- 教训：快速对比必须用 `make -C model CXX=clang++`（生成 Makefile `CXX ?= c++` 默认落到 g++ 13.3，与 difftest 用的 clang++ 22.1 不可比；g++ 下曾误判 +3.14%）。

### 正式门 v1（全量折叠，2026-09-21）→ REJECTED

- gen 800.99s（<1800）、build 196.32s（<1800）、HDLBits DUT=001 通过；hpp 含 2,294 个 cpu_blk_ 声明（与 reemit 一致）。
- emu 二进制：.text 75,319,937→64,037,809（−11.28MB, −14.97%），rodata +5.95MB（1.44M 槽×4B），Berkeley size −6.01%。
- 行为正确：new1 endpoint `[240349, 99996, 100001, 0x80000c0c]`、IPC 2.403586 与 old 一致。
- **6 次交替：old 70.485s / new 77.218s = +9.55% 回退，超 3% 预算 → REJECTED**。

### 回退归因（2026-09-22，perf 双侧同负载 100k 周期）

- `perf stat`（taskset 同核）：instructions:u 526.1G→610.5G（**+16.0%**），cycles +9.9%（与墙钟一致），L1-icache-misses 持平（1276.0M→1275.6M），iTLB −7.0%，宿主 IPC 1.488→1.571（+5.6%）。
- 结论：**回退几乎全部来自指令数增长；I$ 未变差（.text −15% 没换来 miss 下降，但也没代价）**。增长源 = 每可变常量一次表加载（immediate 原本零开销编码进 ALU 指令）。
- 反汇编验证（cpu_blk_0，875 指令）：219 次 `(%rsi)` 访问 / 218 个不同偏移——clang 已对每槽恰好加载一次，无别名重载，`__restrict` 无收益；加载占体指令 25%（219/875），是该机制的不可约开销。
- 策略建模（`policy_model.py`，nm 实测函数大小校准）：全量折叠模型增长 6.94（↔ 实测 +16%，经验因子 ×2.3）；按 热度×加载膨胀率/节省字节 贪心排除至模型增长 ≤1.0 → 预计真实增长 ~2.3%，保住 ~7.7MB .text（对比全量 11.28MB）。

### 修正机制：热度引导贪心排除（cold outlining，2026-09-22）

- 热度输入：对 old emu（no00053 flow-final，100k 周期同负载）`perf record` → `perf report --no-children` 提取 `cpu_task_*/cpu_shape_*` 自身采样% → TSV（2,064 函数覆盖 85.92%）；两侧 task 函数名集合逐 diff 为零（编号稳定）。
- 发射端（`foldBranchBlocks` 新增 `BlockShareOptions{taskHotness, growthBudget}`）：组热度 = Σ 成员 task 采样%（多块 task 高估，方向保守）；加载膨胀率 = distinct槽/(体指令−distinct槽)，体指令 = 源字节×0.105/4.7（nm/反汇编校准）；按 增长/节省 比降序贪心排除至 Σ增长 ≤ 预算（默认 1.0 模型单位 ≈ 实测 +2.3% 指令）。无热度文件时行为不变（全量折叠）。
- 新接口/选项：`--branch-shape-hotness <tsv>`、`--branch-shape-growth-budget <float>`；`loadTaskHotnessFile()`；`BlockShareResult` 增 `excludedGroups/estimatedGrowth`；接线 cpu_emit（Emitter/emitCpuCpp/EmitCppPass/注册表）、`reemit_grhsim_ir.py`、`wolvrix_xs_grhsim_ir.py`、Makefile（`GRHSIM_REEMIT_BRANCH_SHAPE_HOTNESS`/`XS_WOLF_GRHSIM_IR_BRANCH_SHAPE_HOTNESS` 等）。

### reemit2（预算 1.0，2026-09-22）

- 摘要：`branch_block_groups=1084 instances=4768 varying_slots=466497 skipped=610 excluded_groups=1210 est_growth=0.971 folded_source_bytes=128819597`（对比 v1：2294/10645/1.44M/297.8MB）。
- rodata 常量表同步从 5.9MB 降至 ~1.9MB。
- **model .text（clang++ -O3）：75,128,469 → 70,866,707，−4,261,762 B（−5.67%）**；emu text 段（含 rodata）：88,809,498 → 86,518,970（−2.29MB）。
- **6 次交替基准：old 70.767s / new 70.841s = +0.105%（≤3% 预算内，统计上中性）**；6/6 emu_exit=0、endpoint `[240349, 99996, 100001, 0x80000c0c]` 全一致。结果：`bench-reemit2/summary.json`。
- 经验校准修正：模型 est 0.97 ↔ 实测 +0.105%（v1 全量 est 6.94 ↔ 实测 +16%），贪心排除把热组的调用开销与溢出一并消除后，保守方向偏差更大；预算 1.0 留有余量，可上探。
- 聚焦单测：`testBranchBlockFold` 加入 `test_cpu_emit.cpp`（全量折叠默认行为、by-ref active word、嵌套守卫保留、热度排除零预算不改写、宽预算照折、TSV 加载容错）；`make test_grhsim_cpu_emit` 通过（95s）。教训：测试文本必须复刻真实 task 的包装结构——`extractBlocks` 从 funcMarker 之后的第一个 `{` 起扫，合成文本若把守卫直接写成函数首个 `{` 会被跳过（真实文本恒有 `if(cpu_active_word){...}` 外层包装）。

### reemit3（预算 2.5，2026-09-22）

- 摘要：`branch_block_groups=1278 instances=5764 varying_slots=553479 excluded_groups=1016 est_growth=2.482 folded_source_bytes=158120511`。
- **model .text：69,687,147（−5,441,322 B，−7.24%）**；6 次交替 old 70.672 / new 70.945 = **+0.387%**，仍在预算内且统计中性（SD≈0.2s）。较 reemit2 多省 1.18MB。

### 预算扫描与最终选择（2026-09-22）

| 预算（模型单位） | 组数 | model .text 节省 | 6 次交替回退 |
|---|---|---|---|
| 1.0 | 1084 | −4.26MB（−5.67%） | +0.105% |
| 2.5 | 1278 | −5.44MB（−7.24%） | +0.387% |
| **5.0（选定）** | **1515** | **−6.39MB（−8.50%）** | **+0.966%** |

- reemit4（5.0）摘要：`branch_block_groups=1515 instances=6866 varying_slots=652357 excluded_groups=779 est_growth=4.988 folded_source_bytes=186436882`；基准 old 70.541 / new 71.223。
- 选择理由：三档均远低于 3% 预算；2.5→5.0 边际 +0.95MB 对 +0.58pp，5.0 距预算上限仍有 ~3× 余量，正式门复测漂移（±0.5%）后仍安全。默认 `--branch-shape-growth-budget` 在脚本侧取 1.0（保守），XiangShan 流程显式传 5.0。


## 决策记录

### 正式门 final（预算 5.0，flow-final2，2026-09-22）→ ACCEPTED

- gen **794.51s**、build **200.48s**（均 <1800）；HDLBits DUT=001 通过；hpp 含 1,515 个 cpu_blk_ 声明（与 reemit4 逐值一致，发射确定性）。
- **model .text：75,128,469 → 68,740,331，−6,388,138 B（−8.50%）**；emu text 段 88,809,498 → 85,181,862（−3.63MB，−4.09%）；rodata 表 ~2.6MB（65.2 万槽×4B）。
- **正式 6 次交替：old 70.521 / new 71.043 = +0.740%（≤3%）**；三次正式 new Host 70.973/71.193/70.963，均值 **71.043000 s**，SD 0.13；6/6 emu_exit=0、endpoint `[240349, 99996, 100001, 0x80000c0c]` 全一致。
- 对照 v1（全量折叠）：.text −11.30MB 但 +9.55% REJECTED → 热度引导排除用 43% 的 .text 收益换来预算内回退；冷热分离（cold outlining）是该机制成立的关键。


- 2026-09-21：管线位置定为 twin 共享之后（而非之前）——若在之前，静态表名将进入孪生分组的规范化文本，破坏跨文件折叠或要求两机制表布局耦合；之后则单例文件静态表天然可行，共享体内分支 v1 放弃（栈装表 ~7B/槽吃掉收益）。
- 2026-09-21：引用 `cpu_active_word` 的分支不排除，改走 by-ref 参数（与既有 `cpu_helper_` 约定一致），可多覆盖 8,976 个分支、毛收益从 14.6 提升到 21.0MB .text 估值。
