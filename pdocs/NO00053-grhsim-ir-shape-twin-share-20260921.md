# NO00053: 跨文件 task 形状孪生共享（减小二进制 / 缓解 ICache）

节点目标（用户 2026-09-21 指定）：以**减小二进制大小、缓解 ICache 压力**为主要目标，允许不超过 **3%** 的性能回撤；100k 行为等价与生成/编译门槛不变。

## IDEA

### 假设

grhsim 生成的 model 中大量 task 函数互为"形状孪生"：数字归一化后全文逐字符相同、仅常量（状态偏移/flag 下标/掩码）不同（来自硬件结构的复制，如同一存储器的多个写口）。将每组孪生折叠为**一份 noinline 共享函数体 + 每实例常量表 + 瘦包装**，可在保持逐 token 语义不变的前提下消去重复 .text，缓解 ICache 压力；调用与常量间接寻址开销由 3% 回撤预算吸收。

### 瓶颈证据（来自 ptmp/cpu_emit_indent_20260921/重复模式梳理_20260921.md，P1b）

- 生成代码指令总量 ~91 MB（task 函数 88.3 MB），emu .text 94.1 MB；中位 task 12 KB。
- 跨文件整 task 孪生（数字归一化整文哈希分组）：cpu_emit_indent 目录 259 组 / 1,569 文件 / .text 14.9 MB、可折叠 ~11.7 MB；no00052 flow-v1 复核 243 组 / 1,461 文件 / 13.8 MB、可折叠 ~10.7 MB。
- 先例：NO00044 描述符共享提交体（490 组/31,360 端口）同族机制已 ACCEPTED，证明"共享体 + 常量描述符"在本代码库可行且对性能友好。

### 机制（通用特征触发，非模块名匹配）

对全部 task 源做 token 级扫描：值位置数字字面量（含 UINTxx_C）归一为槽位，实例私有标识符（cpu_cached_value_N 等）按出现序规范化，字符串/注释掩码；编译期位置字面量（std::array<..N..>、cpu_write_cell<..,N>、grhsim_slice_words、cpu_replicate_words_changed、alignas、cpu_local[N] 声明、constexpr 行）保持字面值并计入形状键。形状键相同的文件成组；组内仅"各实例取值不同"的槽位进入常量表（均匀槽位保留原字面量，减少运行时加载）。含 cpu_helper_ 定义的文件跳过。

### 局部收益目标与验证标准

- 主要指标：model 全量 .text（nm 函数字节和）下降 ≥ 8 MB（OLD=83,395,957 B）。
- 正确性：100k difftest NEMU PASS、endpoint 与预注册一致（instrCnt=240349、cycleCnt=99996、PC=0x80000c0c、guest=100001）。
- 性能门：6 次交替（3 新 + 3 旧）统计，new 相对 old 回退 ≤ 3%；若出现真实提升按原秩次门声明。
- 门槛：完整 SV→C++ <1800 s、fresh 编译 <1800 s（VM_BUILD_JOBS=nproc=32）、HDLBits DUT=001 通过。
- 证伪标准：.text 收益 <2 MB，或参数装载导致回退 >3% 且无法通过提高折叠门槛（按实例字节数过滤）修复。

## BASELINE

- old 对照（预注册）：`ptmp/no00052_concat_slice_fold_20260921/flow-final`，比较值 **70.410333 s**（NO00052 正式 new 均值；goal.md 登记）。
- old model .text（nm --print-size 全部 .o 函数字节和）：**83,395,957 B**；`size --totals` 含 rodata 94,643,584 B。
- 输入：`testcase/xiangshan/ready-to-run/coremark-2-iteration.bin`；`XS_NUM_CORES=1 XS_EMU_THREADS=1 XS_EMU_CPU=2`、waveform/commit/RAM trace 关、100,000 cycles。
- 止损线：仿真超过基线 1.5×（105.6 s）记 REGRESSION_KILLED；生成/编译 1800 s kill-switch。
- 基线 commit：wolvrix 子仓（NO00052 终态）+ 根仓当前 HEAD（记录在 IMPLEMENTED）。
- 筛选流程：复制 flow-final/model → `screen/flow/model`，python 原型 `shape_fold.py`（扫描/分组/重写/自校验一体），直接 `xs_wolf_grhsim_ir_build_emu` 构建筛选 emu，量 .text 与 1+1 交替筛选性能；原型只用于筛选，正式机制将移植进 wolvrix 发射器（C++），再全量 gen/build/formal。

## IMPLEMENTED

### 筛选原型（python，仅诊断用）

`ptmp/no00053_shape_twin_share_20260921/shape_fold.py`：token 扫描/分组/重写/自校验一体。在 flow-final 模型副本（`screen/flow/model`）上：
- 候选 **222 组 / 1,046 实例**（实例 .text ≥2048 B；跳过 33 个含 cpu_helper_ 定义的文件），可变槽位 767,335 个；
- 筛选构建（clang++ -O3，194.20 s）通过；model 全量 .text **83,395,957 → 75,133,020 B（−8,262,937 B，−9.91%）**；emu 内 cpu_* 函数 83.28→75.02 MB；
- 注意：u64 常量表使 rodata 增 ~6.1 MB（emu 总 .text 仅 −2.18 MB），正式实现改 u32/u64 双表（u32 覆盖 99%+ 槽位）后 rodata 增量降至 ~3.1 MB；
- 1+1 筛选交替（页缓存驱逐、CPU2、100k）：old 70.531 / new 72.106 s，回退 **−2.23%**（在 3% 预算内，u32 双表后预计更低），endpoint 与 difftest 合法。
- 调试记录：实例私有标识符规范化名首版含非法字符（`@` 被 literal 扫描器截断），改 `cpu_*_Q<字母序>` 后编译通过。

### 证伪的备选参数化

- 槽位值对 task 序号线性/仿射拟合：大组 0/377 拟合（偏移分配非等差，含共享平台），仅小组适用（总体 67.6% 槽位可拟合但集中于小池）；
- 组内相邻槽位差值链化：734→563 基址/实例（仅 −23%），不足以替代常量表。

### 正式实现（wolvrix 发射器，C++）

- 新增 `wolvrix/lib/grhsim/backend/cpu_shape_share.cpp` + `include/grhsim/backend/cpu_shape_share.hpp`：`foldShapeTwins` 纯文本折叠（扫描→分组→改写），内置 round-trip/分组不变量自校验（失败 throw 并由 pass 记 error）。
- `cpu.st.emit-cpp` 新增 `--shape-twin-share <true|false>`（默认 false）；开启时发射器先内存渲染全部 task 文本（与原 `file()` 相同的 IndentBuffer 管线），分组后：头文件追加 `cpu_shape_<gid>` 声明、命中的 task 文件改写为瘦包装（`static const std::uint32_t cpu_shape_params32[]={...}` 按需 + `cpu_shape_params64[]`）、共享体汇总写入 `<prefix>_shapes.cpp`（重复 boilerplate 合法），Makefile 追加该源文件；折叠文件绕过 IndentBuffer 原样落盘（文本已过同一格式化管线）。
- 折叠门槛：组 ≥2 实例且宿主源文本 ≥4000 B（源/文本比普查：源 ≥4000 保留全部 .text ≥2048 文件、仅多收 72 个小文件）；含 cpu_helper_ 定义的文件跳过。
- `scripts/wolvrix_xs_grhsim_ir.py` 发射调用传 `shape_twin_share=True`；`scripts/reemit_grhsim_ir.py` 与根 Makefile `reemit_grhsim_ir` 目标补 `--shape-twin-share` 通道（检查点重发射筛选用）。
- 聚焦测试：`make test_grhsim_cpu_emit` 通过（96 s），含新增 `testShapeTwinFold` 单元测试（孪生分组、常量表内容、模板实参/均匀字面量保护、声明与 noinline、单实例不改写）。
- 基线 commit：wolvrix 子仓 `aa17d7f`（改动前 HEAD）+ 根仓 `4f72f93`；改动文件：上述两新文件、`cpu_emit.cpp`、`cpu_emit.hpp`、`CMakeLists.txt`、`test_cpu_emit.cpp`、`wolvrix_xs_grhsim_ir.py`、`reemit_grhsim_ir.py`、`Makefile`。

### C++ 移植调试记录（检查点重发射快循环）

- 首次全量 gen 在形状扫描自校验拒绝：`decimal literal too large 18446744073709551615`。经 flow-debug2（无折叠重发射）对照证实生成文本干净，定位为扫描器 bug：`line.compare(i, 5, "UINT") == 0` 把 `UINT6`（5 字符）与 `UINT`（4 字符）比较恒不等，UINT64_C 分支永不命中，裸值落入十进制分支溢出。修为 `compare(i, 4, "UINT")`。
- 修复后重发射（NO00052 检查点 + `--shape-twin-share`）：**231 组 / 1,080 实例 / 769,439 可变槽位 / 跳过 33 个 helper 文件**，与 python 原型（222/1,046）一致（差异来自源文本 ≥4000 B 与 .text ≥2048 B 的门槛口径）。
- flow-debug 全量编译 213.70 s 通过；model 全量 .text **75,128,469 B（−8,266,488 B，−9.91%）**，与原型 −8.26 MB 吻合；hpp 231 个 cpu_shape 声明、shapes.cpp 入库。

## VALIDATED

### 全流程门槛（formal.sh，2026-09-21）

| 门槛 | 结果 |
|---|---|
| 完整 SV→C++ 生成 | **784.78 s**（<1800 s；`RUN_ID=no00053_final_gen`，含折叠 pass） |
| fresh 编译 | **204.28 s**（<1800 s；VM_BUILD_JOBS=32=nproc） |
| HDLBits DUT=001 | 通过（`[TB] dut_001 passed: one=1`，与 NO00052 同为已构建复跑） |
| 单测 | `test_grhsim_cpu_emit` 通过（含新 foldShapeTwins 单元测试） |

### 二进制削减（主要目标）

- model 全量 .text（nm 函数字节和）：**83,395,957 → 75,128,469 B（−8,266,488 B，−9.91%）**；
- emu `.text` 段：83,591,516 → 75,319,937 B（−8,271,579 B，−9.90%）；
- emu `.rodata`：8,766,720 → 11,841,896 B（+3,075,176 B，即 u32/u64 常量表，与预估 ~3.1 MB 一致）；
- emu 二进制 text+rodata 净减 **~5.20 MB**；生成 C++ 源文本 1,099.4 → 951.6 MB（−147.8 MB，−13.4%），其中共享体 shapes.cpp 49 MB；
- 折叠规模（发射器 info）：**shape_twin_groups=231、instances=1,080、varying_slots=769,439、skipped_helpers=33**。

### 100k 等价与 6 次交替复测

- 预注册：`formal/preregister.json`，顺序 old1/new1/old2/new2/old3/new3，期望 endpoint `[240349, 99996, 100001, 0x80000c0c]`，CPU 2、页缓存逐次驱逐、止损线 105.6 s（1.5×70.410333）。
- 六次运行全部有效（退出 0、difftest 无 mismatch、endpoint 与预注册完全一致，与 old 相同 → 100k 行为等价）：

| 次序 | old Host(s) | new Host(s) |
|---|---|---|
| 1 | 70.342 | 71.521 |
| 2 | 70.928 | 72.024 |
| 3 | 70.006 | 70.680 |
| 均值 | **70.425333**（SD 0.4666） | **71.408333**（SD 0.6790） |

- 结果：new 相对 old **回退 1.3958%**（improvement_percent=−1.3958；U=8、单侧精确 p=0.95 不支持"new 更快"声明；回退幅度约为 old 组 SD 的 2.1σ，为真实回退而非噪声，但显著低于 3% 预算）。

## ACCEPTED / 最终判定

**ACCEPTED**（按用户 2026-09-21 节点调整门：100k 行为正确 + 回退 ≤3% + 以二进制减小/缓解 ICache 为主要目标）：

1. 100k 行为等价：6/6 运行 difftest 通过、endpoint `[240349, 99996, 100001, 0x80000c0c]` 与 old 完全一致；
2. 回退 **1.3958% ≤ 3%**（6 次交替测量，预注册口径）；
3. 二进制显著减小：model .text **−8.27 MB（−9.91%）**、emu .text −8.27 MB（−9.90%）、常量表 rodata +3.08 MB 后净减 ~5.2 MB、生成源文本 −147.8 MB；折叠机制通用（形状重复触发，非模块名匹配），与 NO00044 描述符共享提交体同族；
4. 生成 784.78 s、编译 204.28 s（32 jobs），均 <1800 s；HDLBits DUT=001 通过。

后续方向：P1a 函数内分支体形状提取（梳理文档估计 20–35 MB 池，需发射层块识别）；init 全零存储区间 memset 合并（~2.5 MB）；rodata 常量表跨组去重（同形状组间常量行常有重复）。移交下一节点：old 对照更新为 `ptmp/no00053_shape_twin_share_20260921/flow-final`（new 均值 **71.408333 s** 作预注册比较值）。
