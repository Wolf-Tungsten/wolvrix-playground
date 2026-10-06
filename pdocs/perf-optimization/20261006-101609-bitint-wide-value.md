# 20261006-101609 grhsim 宽值 _BitInt 化（TwoState >64 位存储/运算切换）

## 元信息

- 日期 / 作者：2026-10-06 / grh
- wolvrix commit / 根仓 commit：wolvrix `e356661`（P_mem guards shadow bitmap）+
  工作区 E-flat 未提交改动（`cpu_phase_emit.cpp` 等 5 文件，见
  `ptmp/grhsim-boundary-explore/NOTES.md` "E-flat 发射形状改造" 一节）
- 上游基线记录：`20261004-075148-v3-sixphase-baseline.md`；形状对照数据见
  `ptmp/grhsim-boundary-explore/NOTES.md` "gsim 对照：代码形态与尺寸免疫实验"

## 基线性能

正式同口径数据在 P0 步骤补测（本节先登记已有的结构性证据）：

- 编译时间真凶定位（2026-10-06 晨，-ftime-trace 逐函数归因，详见 NOTES.md）：
  慢 TU `s1n512e tu112` 15.8k 行编 43.5s（SLP 27.2s + inliner 13.8s），热点是
  **宽值词循环链**——`grhsim_insert_scalar_words`/`and_words` 等 15 词（960 位）
  数组 op 在 chunk 函数内成链，inliner 展开词循环后 SLP 超线性
  （`sn_3002__c0` 538 行单函数 SLP 15s）。对照 gsim `SimTop324.cpp` 144k 行仅 8.7s
  （0.061s/千行 vs 我们 2.75s/千行，45×）。
- 宽 helper 调用规模（E-flat 后 s1ce 全模型 1259 TU 静态计数）：`_words` 系
  helper 调用约 43.1 万处，其中 `cpu_shift_words/cpu_compare_words` 3,070、
  `grhsim_index_words` 5,351、`grhsim_trunc_u64`（`cpu_operand_` 物化路径）2,988。
- gsim 宽值机制（`reference/gsim` 调查结论）：>64 位信号 =
  `unsigned _BitInt(ROUNDUP(w,64))` 单标量（`include/common.h:50-66`），运算全部
  生成为单条 C++ 中缀表达式（`instsGenerator.cpp` 各 `insts*`），无 runtime helper、
  无手工词循环，多字展开完全交给 clang；掩码靠 op 点 `& bitMask(w)`
  （`util.cpp:119-134`）；变化检测整体 `!=` + 无分支 `cond<<bit` 置 flag
  （`cppEmitter.cpp:777-825`）。
- 工具链实测（probe）：clang 22.1.2 `-std=c++20` 接受 `unsigned _BitInt`；x86-64
  下 `sizeof(unsigned _BitInt(65))=16`、`alignof=8`，内存布局与小端 u64 字数组
  一致 → FST 裸字节路径、整 store memcpy 提交物理上继续成立。g++ 13 不支持。

## 优化方案

- 动机：编译时间是当前主要成本之一（全模型 -j64 wall 与慢 TU 长尾）；词循环链
  已被逐函数归因确认为 SLP/inliner 热点；同时手工词 helper 的运行时性能也不如
  编译器合法化后的原生多字运算（E-flat 窄值改造已验证该方向）。
- 假设：TwoState 宽 Logic 改用 `_BitInt` 单标量 + 原生表达式后，宽 op 从"词循环
  helper 调用"变成"编译器内部合法化"，SLP/inliner 热点消除，慢 TU 编译时间向
  gsim 形状收敛（gsim 同模型 0.061s/千行）；运行时随 E-flat 已建立的无分支
  publish 扩展到宽值，不劣化。
- 改动点（文件级）：
  - `wolvrix/lib/grhsim/backend/cpu_layout.cpp`：`namedStorePhysicalType`（:170）
    TwoState 宽 Logic 映射 `Array(UInt64,ceil(w/64))` → `UInt(w)`（方案 A：复用
    UInt kind，width>64 即 `_BitInt`，JSON 零格式变更；方言文档
    `dialects/cpu.md` §1.2 本就按 `cpu.uint<w>` 描述）；verify 镜像同步。
  - `wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp`（主战场）：`cppType`（:1238）→
    `unsigned _BitInt(ROUNDUP64(w))`；`cppStoreType`/`storageBytes` 宽分支；
    掩码基础设施 `bitMask`（仿 gsim，padding 恒零不变式）；`literal`/`randomInit`；
    `expression()` 宽分支（:1685-1738）与 `scalarExpression`（:1432-1470）全家族
    原生表达式；移位 UB 防护；**删除 emitCompute 宽分支（:1930-2114，pointer
    ABI + `cpu_operand_` 物化）与生成头融合模板 `cpu_*_words_changed`
    （:3224-3364）**；publish/状态写/边沿检测/FST/dump/task/DPI 适配。
  - `wolvrix/lib/emit/grhsim_runtime.cpp`：TwoState 宽专用 helper 清单化裁剪
    （4-state、task、FST 支撑保留）。
  - 构建兜底：模型 Makefile 模板（`cpu_phase_emit.cpp:4446`）与
    `testcase/hdlbits/Makefile:4` 的 `CXX ?= c++` 改 clang 优先。
  - 测试断言：`tests/grhsim/test_cpu_stores.cpp:552-555,1062-1065` 等。
  - 开发期临时 knob `--cpu-wide-storage=array|bitint` 保证中间态 ctest 绿，
    收尾移除。
- 范围边界：只动 TwoState 宽 Logic；4-state 宽值保持 array + 词 helper；
  宽 mul/div/mod 维持现状（六相本来就 throw）；partition/schedule/TU-plan 不动；
  DPI 为项目自定义 ABI，宽参数签名随之变为 `_BitInt`（实施时确认无宽 DPI import）。
- 风险与回退：
  - sizeof/对齐平台依赖 → 生成头 `#ifndef __BITINT_MAXWIDTH__ #error` +
    static_assert 校准（sizeof==8*ceil(w/64)、alignof==8）；
  - 移位 ≥ 位宽是 UB → 移位量饱和防护（shl/lshr `amount>=w?0:`，ashr 钳 w-1，
    宽移位量高字非零饱和 cap）；
  - 掩码不变式（每宽结果收口到语义宽度）是 publish `!=`、FST memcmp、dumpState
    fnv1a 正确性前提；
  - 旧 checkpoint 被 verify 拒绝属预期（项目惯例），重新生成；
  - 回退 = git revert + 重新 emit（词 helper 保留在树内）。

## 结果性能

### 编译时间（生产配置，-j32，同机干净测量）

| 模型 | TUs | 总行数 | wall | user CPU |
|---|---|---|---|---|
| p1（pre-E-flat parity，10-05 存档） | 1082 | 14.13M | **497s** | 13,564s |
| _BitInt（estimator ×8） | 1229 | 13.13M | 1213s | 35,298s |
| **_BitInt（estimator words 校准，采纳）** | 1084 | 13.12M | **773s** | 22,162s |

- **每行编译成本仍高于 pre-E-flat（1.63× user CPU）**：pre-E-flat 的"helper 调用 +
  条件 publish"形状在平均 TU 上反而最便宜——helper 调用对编译器是单个不透明节点，
  E-flat 展开式与 _BitInt 原生表达式则把代价摊开在每个站点。E-flat/_BitInt 的价值
  在消除**病态 TU**（s1c 配置下单词循环链使 clang 后端超线性，tu62 E-flat 实测
  781s；见 NOTES"gsim 对照"），不在平均 TU 提速。wall 773s 满足 ≤30 min
  CPP→binary 硬闸（占 43%）。
- **estimator 宽权重 ×8→words 校准（采纳）**：×8 是词循环时代的止痛片（把宽 op
  链切碎防 SLP 超线性），_BitInt 后只剩切碎代价（TU +13%、边界外溢与 publish
  代码增多）。回退到 words 后 TU 1229→1084（与 p1 的 1082 基本持平），
  wall -36%、user CPU -37%。
- **s1c 配置双侧同慢（配置固有）**：s1ce（E-flat）与 s1ce-bitint 均出现 10-30 min
  级单 TU（tu62：E-flat 实测 781s）——S1 无帽语义节点产生的巨型函数对两种发射形状
  都病态，与 S1S2 探索"违反 30 min 闸"结论一致，不是本项回归。
- **emit 耗时**：E-flat 901s vs _BitInt 934s（SV→CPP 全流，同机先后）——发射速度平价。
- 后续项：runtime 词 helper 裁剪（_BitInt XS 模型中 `*_words` 引用已为 0，头文件
  文本减量可再省每 TU 解析时间）；PCH（10-05 已测 wall 中性）。

### 运行时间（`make benchmark_grhsim_ir` 标准口径：100k CoreMark、3+3 交替、
页缓存逐出、taskset CPU 2、固定 randSeed、端点校验全过）

- **_BitInt emu：110.91 ± 0.82s**（110.0 / 111.2 / 111.5）。
- 同日对照 legacy grhsim（build/xs/grhsim，9-3 构建）：115.01 ± 0.08s
  （115.0 / 115.0 / 115.1）——**+3.57%（rank gate 通过）**。
- 对项目既有口径的意义：E-flat 时代 grhsim-ir 生产 emu 为 178.9s（NOTES E0 口径），
  对 M0 存档（85.9s）差距 2.08×；本项后 110.9s，**对 M0 差距收敛到 1.29×，
  相对 E-flat 时代运行时间 -38%**（注：该 -38% 为 E-flat 与 _BitInt 的合并效应，
  无 E-flat-only emu 可分离；同日 M0 复测为 115.0s 慢于其 10-04 的 85.9s 记录，
  机器状态差异，比值以 10-04 记录为准）。

## 正确性验证

- [x] `make test_wolvrix`（54/57，恰基线三项，无新增失败）
- [x] `make run_all_hdlbits_grhsim_tests` 162/162
- [x] `make run_xs_bugcase_grhsim` 25/25（CASE_003 曾暴露 signed compare bug，修复后过）
- [x] `make check_sim_refactor_baseline` 161/161（trace shim `_BitInt` 适配后）
- [x] XS 完整 CoreMark + NEMU difftest：HIT GOOD TRAP / exit 0 /
      逐拍轨迹 **instrCnt=663,688 / cycleCnt=297,291** 与黄金一致
- 日志路径：基线与复测日志在 `ptmp/bitint-*`；benchmark 输出
  `ptmp/bitint-bench-out/`；模型构建产物走默认路径（`build/xs/grhsim-ir/`、
  `build/hdlbits-grhsim/`）。

### 实施过程发现（2026-10-06 午）

- **E-flat signed compare bug（既存，本项调查中定位并修复，CASE_003 根因）**：
  xs-bugcase CASE_003 的 grhsim 行为发散（ref==wolf 于 cycle 2514 失配，HEAD(e356661)
  对照通过），经双侧模型 dumpState 逐 cycle 二分 + 超节点局部量插桩定位到一条
  signed 3-bit 比较 `sext(v,3) < 0` 在 E-flat 模型中算成 `(7 < 0)`。根因：E-flat 的
  `scalarExpression` signed 比较路径 `(int64)(cast(lhs)) OP (int64)(cast(rhs))`——
  `cast()` 对 `srcWidth == compareWidth` 的 signed 操作数只 trunc 不 sign-extend
  （其注释"窄化时 sign-extend 不可观测"对**比较**不成立，helper 语义要求比较前
  从 compareWidth 做符号扩展）。修复：signed 比较路径改为
  `sextRaw(cast(lhs,cmpW),cmpW) OP sextRaw(cast(rhs,cmpW),cmpW)`
  （`cpu_phase_emit.cpp` scalarExpression compares）。宽比较路径（本项新增）无此
  问题（按 source.width 显式 sext）。教训：E-flat 晨间仅验证了 hdlbits 162 +
  test_wolvrix，**xs-bugcase 的行为级用例（signed 窄比较遍布控制逻辑）正是缺口**；
  本项把 `run_xs_bugcase_grhsim` 纳入了发射形状改动的必跑门槛。
- **正确性门槛（已实现态）**：`make test_wolvrix` 54/57（恰基线三项：
  transform-comb-lane-pack / transform-repcut / ingest-write-back-slice SEGFAULT）✓；
  `make run_all_hdlbits_grhsim_tests` **162/162** ✓（14 个宽端口 grhtb 测试台同步
  适配 `_BitInt` ABI：041/042/043/060/062/064/065/071/039/040/108/116/117/118）。
- **发射器落地中修复的两个自身 bug**：(1) `shl` 未先把被移值拓宽到结果容器
  （窄值左移 >= 自身位宽是 UB，XS 上 180 处 `-Wshift-count-overflow` 警告暴露）；
  (2) 大 concat 的左嵌套表达式树在 511 个 `<<` 时耗尽 clang 解析栈
  （XS bloomFilter，tu64 编译段错误）——>8 操作数的 concat 改发语句式 lambda
  （`cpu_cat` 累加，语义与链式等价）。
- **runtime 引用普查**（_BitInt XS 模型静态计数）：词 helper 引用为 **0**——
  词 helper 家族（and/add/shift/slice/concat/mux/compare/reduce/insert/merge/index
  等全部 `*_words`）在发射代码中已无调用点；仍被引用的仅 dump/task/FST 支撑与
  窄值 `grhsim_udiv_umod_u64`（by design）、`grhsim_event_*`、`grhsim_random_u64`。
  → runtime 裁剪列为独立后续步骤（含头文件文本减量的编译时间收益）。
- **E-flat 宽 `indexRaw` 括号 bug（既存，随本项消除）**：E-flat 把宽值移位量的
  `grhsim_index_words` 展开为 `((high)!=0?cap:(((low)>=cap?cap:(low)))` —— 少一个右
  括号，凡宽值作移位量的站点即生成不可编译代码（s1ce 模型 12 个 TU、64 处；
  hdlbits 162 未覆盖该形状故晨间全绿）。_BitInt 改造整体替换了该路径
  （`wideIndexRaw`/原生移位形状），bug 随提交消除。为获得 E-flat 编译基线，s1ce
  模型中的 64 处展开已机械回改为 `grhsim_index_words(array,cap)` 调用（语义=
  被内联的 helper 本体，`ptmp/repair_s1ce_eflat_indexraw.py`）。
- **基线口径**：E-flat 基线 = 修复后的 s1ce 模型（S1+coarsen 1e9 配置，E-flat
  发射器生成于 2026-10-06 08:46），_BitInt 侧用同配置（
  `XS_WOLF_GRHSIM_IR_SEMANTIC_NODES=1 XS_WOLF_GRHSIM_IR_COARSEN_MAX_OP=1000000000`）
  emit 到 `build/xs/grhsim-ir/s1ce-bitint/model`。生产配置模型另走
  `build/xs/grhsim-ir/model`（默认路径）用于 difftest 与运行时对照。
- **emit 耗时对照**：E-flat 基线 901s、_BitInt 934s（+3.7%，同机先后运行，
  均在 SV→CPP 全流口径）——发射速度无回归。

## 正确性验证

- [ ] `make test_wolvrix`（恰基线三项，无新增失败）
- [ ] `make run_all_hdlbits_grhsim_ir_tests` 162/162
- [ ] `make run_xs_bugcase_grhsim` 25/25
- [ ] `make check_sim_refactor_baseline` 161/161
- [ ] XS 完整 CoreMark + NEMU difftest：HIT GOOD TRAP / exit 0 /
      逐拍轨迹 instrCnt=663,688 / cycleCnt=297,291（或有意重钉并说明）
- 日志路径：基线与复测日志在 `ptmp/bitint-*`；模型构建产物走默认路径
  （`build/xs/grhsim-ir/`、`build/hdlbits-grhsim/`）。

## 后续

- 可选：宽 mul/div/mod 原生实现（`_BitInt` 后近乎免费，含除零语义对齐）；
  gsim 式 splitNodes（按 used-bits 拆超宽信号）；`_BitInt` 化后重新评估
  `estimatedCpuOpLines` 全部权重而不仅是宽值项。
