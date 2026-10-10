# Stage 07 — preserve-aggregate 端到端与 reg-to-mem 退役

- 日期：2026-10-08（2026-10-08 修订：comb-lane-pack 移除由评估项改为既定项）
- 状态：进行中（2026-10-10 开工；7a/7b 已落地，7c/7d 进行中）
- 依赖：stage-04（ingest 聚合保留）、stage-05（comb-loop-elim）、stage-06（grhsim 承接）
- 对应总目标：#10 终极目标

## 实施记录（2026-10-10，开工即写，验收后收口）

### 7a/7b 落地事实

- `testcase/xiangshan/Makefile`：`PRESERVE_AGGREGATE` 变量化（空=firtool 默认 none，
  aggregate 链路传 all），追加 `--firtool-opt "--preserve-aggregate=$(PRESERVE_AGGREGATE)"`。
- 根 Makefile：`$(XS_SIM_TOP_V)` 与 `xs_gsim_rtl` 的 mill 调用补 `XS_MILL_ENV`
  （`XS_JAVA_HOME ?= /usr/lib/jvm/java-17-openjdk-amd64` 存在检测 + 仓库根 mill launcher
  进 PATH）——原规则依赖操作员手工环境，新机器上 JDK25 必炸（mill 0.12.15 需 JDK17）。
- 新目标族：`xs_rtl_aggregate`（独立目录 `build/xs/rtl-aggr`）、
  `xs_wolf_grhsim_ir_aggregate(+_build_emu/_emu)`、`run_xs_wolf_grhsim_ir_aggregate_emu`
  （全部委托既有目标 + 变量覆盖：XS_RTL_BUILD/XS_GRHSIM_IR_BUILD/XS_WOLF_FILELIST/
  emit dir/XS_PRESERVE_AGGREGATE）。`xs_rtl_aggregate` 实测 375s 产出 2148 个 split
  文件，与探针产物一致。
- `scripts/wolvrix_xs_grhsim_ir.py`：`CPU_SEMANTIC_PIPELINE` 移除 `grhsim.reg-to-mem`，
  4 个 reg-to-mem CLI 参数删除；新增 `--dump-pre-simplify-json` 诊断旋钮；
  GRH_PIPELINE 在 comb-loop-elim 后与 simplify 后各加一步 `grh.verify`
  （加固：几何违例不再一路漏到 const-fold/grhsim 才炸）。
- 探针待补项关闭：mill 全链路复核 → 已正式落地为 `xs_rtl_aggregate`；`=vec` 不采纳
  （`all` 一次通过且保留 struct，`vec` 只小 43% 但丢 struct 无收益）；comb-lane-pack
  残留注册点确认无（源码侧仅 comb_pack.cpp 一行历史注释）。
- xs-components/rob.mk 两处调用同步去除 reg-to-mem 参数。

### 7c reg-to-mem 退役（三步压缩为一次落地）

- 7c-1/7c-2/7c-3 顺序执行、一次验证：wolvrix 侧删 `reg_to_mem.cpp/.hpp`、pass.cpp
  注册点、3 个测试 + 3 个 data 文件（−3234 行）；`docs/grhsim_ir/passes/reg-to-mem.md`
  转 RETIRED 历史记录（负结果知识保留）；overview.md/cpu-st.md 退役注记。
  外层：benchmark/measure/test 目标族与配套脚本删除。
- `test_grhsim_whole_opt.cpp`：删 reg-to-mem 专用段（A3 fixture + transformed=1 断言）；
  移除后 tbl_* 四行译码 mux 暴露给 comb-pack，comb-pack 期望由 groups=1/lanes=4
  修正为 groups=2/lanes=8（注释注明）。
- 门禁即时结果：ctest 57 项 56 过（余 transform-repcut 既有）；hdlbits 162/162；
  xsbug 25/25；**trace 基线 162/162 逐字节一致——reg-to-mem 在 HDLBits 零触发，
  计划中的"重钉"实证为不需要**。
- 负结果知识锚点：pass 退役文档 + `pdocs/perf-optimization/20261007-040954-reg-to-mem-off-negative.md`；
  census 分析脚本（grhsim_bucket_dyn_price.py 等）的 "(reg-to-mem)" 分桶标签保留
  （只匹配历史 artifact，非门禁项）。

### 编译期攻坚（本阶段最大偏差：aggregate 首轮 simplify 超线性爆炸）

首轮 aggregate 管线在 GRH simplify 跑了 103 分钟并以 `kSliceArray base value must
carry a shape` 失败。逐层归因与修复（全部实证驱动）：

1. **simplifySlices 的 O(n²) 环守卫**（perf 采样 + 分阶段计时定位）：每个
   kSliceStatic-over-kConcat 候选都做一次全新锥 DFS（带按值物化拷贝）。
   聚合设计 18.7M values 下 simplifySlices 单轮 700s。
   修复：新建 `lib/transform/topo_guard.hpp`——每 sweep 一次 Kahn 拓扑分层
   （valueRank 沿 def-use 严格递增，`rank[o] <= rank[r]` 即证明无依赖，跳过 DFS；
   残留组合环区/新建值无 rank → 回退 lean DFS（stamp 数组取代每调用新建
   unordered_set））。清扫循环同步改 lean（Graph 公开 id/span 访问器，不再
   getValue/getOperation 肥拷贝；fat op 仅在采纳重写时物化）。
   效果：simplifySlices 700s → **127s**（守卫计数 fastSafe=88321 / dfsFallback=8044）。
   有效性论证：sweep 内 replaceUsers(r→o) 只加 rank 一致的边（rank[o] ≤ rank[r] <
   rank[user]），擦除只删边，故 sweep 开始时的拓扑序全程有效；S5 comb-loop-elim
   残留真组合环（本设计有 ~18k-op 环区，status=true analysis=incomplete）经
   generation 校验落到 DFS 回退，语义不变。
2. **同款 DFS 在 redundant-elim 的 4 个调用点**：接入 topo_guard（RE sweep 的
   重写同样只加 rank 一致边）。RE 主 sweep 与 CSE 的肥拷贝由子代理 lean 化重写
   （kConstant 排除出 CSE——常量去重本就是 const-fold ConstantPool 职责；
   makeSignature 不再把巨型 constValue 字符串拷进签名）。
3. **shape 根因修复**（S6 遗留"折叠/别名代表元丢 shape"归 S7 复核，实证闭环）：
   - const-fold/redundant-elim 的 `replaceUsers` 包装加回填：被替换值带 shape、
     替换值扁平且同宽同 Logic 型时，把 shape 回填给替换值（packed-first：shape 是
     结构视图）。修复前：simplify 第二轮即报 `kSliceArray base value must carry a
     shape`（基值经别名/CSE 替换丢 shape）；修复后 8 轮迭代全收敛无错误。
   - **verifier 双向放宽**（kRegisterReadPort 整体读）：52 个
     `result shape [..] does not match register shape []`（hier-flatten 引入：
     标量轨寄存器经端口连接继承了对侧 packed 类型的 tiling 视图）+ xs-bugcase
     4 例反向（shape 寄存器 + 扁平结果）。按 packed-first 教义，整体读结果只校验
     位宽一致 + shape 精确铺满位宽，不再要求与声明 shape 严格相等。grh-ir.md
     §6.4 kRegisterReadPort 契约同步。
   - 归因手段（都留在仓库里可复用）：`--dump-pre-simplify-json` 旋钮、
     ptmp 诊断驱动（逐 pass grh.verify 二分定位到 hier-flatten）、per-call
     checkpoint 复现循环、const-fold 分阶段计时与守卫计数
     （`WOLVRIX_SIMPLIFY_PHASE_TIMING` / `WOLVRIX_CONST_FOLD_GUARD_STATS` env 门控）。
4. 修复后隔离测量（pre-simplify checkpoint 起，simplify 全迭代）：
   首轮 ~1335s（const-fold collectConstants 85s / iterativeFolding 96s /
   simplifySlices 127s / RE 537s / DCE 24s 起步，迭代内递减），第 2 轮起 ~32s
   收敛。**残余编译期热点 = RE 首轮 + 常量机器**（17M ops 中 kConstant 560 万、
   kSliceStatic 321 万——firtool 逐元素展开写的字面量机器；达到 <10min 编译
   目标需要图瘦身：ingest 常量 interning/常量表达式预求值 + mux-tree→动态访问
   逆向识别，归 stage-08 候选）。

### 偏差与顺手修复登记

- 操作教训：多个 Make 目标硬依赖 py_install，并行跑门禁时两个 pip editable
  install 竞争导致 "partially initialized module" 假象失败——重跑前串行化
  py_install。xsbug 首轮 12/25 失败全部为此假象。
- `Design::Design(Design&&)` 等 GRH 容器搬迁成本在聚合设计（19M values）下成为
  显性热点——本次未动（涉及核心 IR 布局，留作后续编译期优化候选）。
- XS 管线新增 grh.verify 两步是行为加固（只读 pass，只报不改）。

### 当前阻塞（2026-10-10 深夜，aggregate 链路最后一里）

门禁全绿、GRH 段全过（含新增 grh.verify 两步）、lowering 与 GrhSIM 语义段全过、
B8 seal 通过；**失败点 = `cpu.st.build-general-nodes`：compute graph 存在组合环**。

实证链（全部可复现，工具在 `ptmp/xs-aggr-diag/`）：

1. aggregate 设计 comb-loop-elim 残留 8 个环（loops=48 true=8，Frontend/TLB/
   MemBlock/DCache 控制区，最大 21086 ops），全部 `analysis=incomplete`；
   基线标量化设计**零环**（当前 comb-loop-elim 跑基线 RTL 复核 loops=0，
   排除 S5 回归；基线 flat GRH Kahn 拓扑残余=0）。
2. 环内容实样（flat GRH 提取，20-op 环）：`replacer$stateBank` 动态读
   `kRegisterReadArrayPort(stateBank[trainReadSetIdx])` 的结果经 wayMask/hit 组合锥
   回馈到 `trainReadSetIdx` 的计算——**读索引组合依赖读结果**，经动态状态数组读
   形成值级环。
3. 基线不存在该环的结构性原因：标量化形态 + reg-to-mem 把这些状态 bank 恢复为
   mem 存储（读为 mem 读口），环结构从未形成；aggregate + 无 reg-to-mem 的形态
   把动态读以单值端口形式保留，值级环出现。**环问题与 reg-to-mem 退役是纠缠的**。
4. comb-loop-elim 的 S5 既定保守分支（含动态读的环不可判定时保留）按设计工作，
   不是 bug。

结论：需要"动态读环断路"能力（S5 扩展或专项 pass），属 stage-08 级设计工作。
候选方向：(a) comb-loop-elim 对含动态读环的片段化扩展；(b) 专项 pass 把环内
动态状态数组读改写为逐元素读口 + 选择树（局部重建元素级无环结构——注意：
读侧展开成 mux 树后"结果→索引→mux 选择→结果"的值级环仍在，需先验证断环
位置在写口/边界侧）；(c) CPU 映射侧把状态读作为合法断环边界（语义风险，
需论证读旧值的 NBA 语义）。决定前先小用例验证（TAGE/replacer 形态，
CASE_021/022 族）。

### 门禁与验收

## 1. 目标

1. 建立 `firtool --preserve-aggregate` 的 XiangShan SV 生成链路，wolvrix 全流程
   （ingest → GRH passes → GrhSIM → CPU emit）直接消费，正确仿真。
2. reg-to-mem 从默认管线**完全退役**（不是默认关闭，是移除），仿真仍然正确。
3. 全部门禁恢复并清零历史豁免；性能不低于现行基线的约定阈值。

## 2. 现状事实

- XiangShan SV 生成：根 Makefile `xs_rtl`（Makefile:1334）→ `testcase/xiangshan/Makefile`，
  firtool 选项固定在 :79（`--firtool-opt "-O=release --disable-annotation-unknown
  --lowering-options=explicitBitcast,disallowLocalVariables,disallowPortDeclSharing,
  locationInfoStyle=none"`），**未开 preserve-aggregate**；`FIRTOOL=` 可指定二进制（:86）。
- `--preserve-aggregate` 在 circt firtool 存在（取值 none/1d/all）；已知限制：含 Clock
  字段的 struct 会报错（circt issue #8931）。XiangShan 当前 firtool 版本对
  `all` 档的兼容性**未实证**——这是本阶段第一个要回答的问题。
- 现有手写最小复现：`testcase/xs-bugcase/CASE_021`（Tage t2_setIdx preserve-aggregate
  形态）、`CASE_022`（indexed write）、`CASE_009`——可作为早期冒烟输入。
- `testcase/xs-components/Makefile:274-279` 已有 mill + firtool 的合成隔离用例流程
  （`DynArrayWrite.scala`、`CamMatchSynthLarge.scala` 等正是数组/聚合形态）。
- reg-to-mem 在 `CPU_SEMANTIC_PIPELINE`（`scripts/wolvrix_xs_grhsim_ir.py:170-185`）中，
  位于 canonicalize-compute 之后；它是现行性能的承重墙（关闭 +41%，
  `pdocs/perf-optimization/20261007-040954-reg-to-mem-off-negative.md`）——但那是
  "前端标量化"前提下的结论；数组保留后该前提消失，需重新测量。
- 验收门禁（继承 perf-optimization/README）：test_wolvrix、HDLBits IR 162、xs-bugcase 25、
  黄金 trace 161、XS CoreMark difftest（instrCnt=663,688 / cycleCnt=297,291）。

## 3. 执行计划

### 3.1 子阶段 7a — firtool 链路实证（纯调查，不改 wolvrix）

**已完成首轮（2026-10-08），结论与形态清单见
[20261008-preserve-aggregate-probe.md](20261008-preserve-aggregate-probe.md)。要点：**

1. ~~确认 `--preserve-aggregate` 支持矩阵~~ → 取值为 `none|1d-vec|vec|all`
   （firtool 1.135.0/1.144.0 一致；注意是 `1d-vec` 不是 `1d`）。
2. ~~XiangShan 全量 `all` 档可行性~~ → **一次通过**，未触发 Clock-struct（#8931）类错误；
   设计逻辑 100% packed 聚合 + unpacked Memory + 仿真 _RANDOM，无 unpacked 数组。
3. 形态清单（ingest 必须承接的全集）与对 stage-01/stage-04 的回灌结论：见探针报告
   §3/§4（packed 维全量进 shape、部分索引返回子数组、结构体字段路径等；
   注意报告 §4.1 的"分流"解释已被 §6 补充取代，以 stage-01/04 当前文本为准）。
4. ~~待补：mill 全链路（MFC_ARGS 注入）复核；xs-components 合成用例变体；
   `=vec` 中间档的收益评估~~ → 2026-10-10 全部关闭：mill 全链路正式落地为
   根 Makefile `xs_rtl_aggregate`（`PRESERVE_AGGREGATE=all` 变量化注入，
   375s 产出 2148 个 split 文件，与探针产物形态一致）；`=vec` 不采纳——
   `all` 档一次通过且保留 struct，`vec` 仅小约 43% 但丢 struct 无收益；
   xs-components 变体以 rob.mk 去除 reg-to-mem 参数后的冒烟运行代替。

### 3.2 子阶段 7b — Makefile 与管线接入

- `testcase/xiangshan/Makefile`：`--firtool-opt` 增加 preserve-aggregate 选项
  （建议做成变量如 `PRESERVE_AGGREGATE=all`，默认关，避免冲击现有 `xs_rtl` 用户）。
- 根 Makefile 新增目标族（遵循"一切走 Makefile"约束，先在 Makefile 加 target 再使用）：
  - `xs_rtl_aggregate`：生成 preserve-aggregate 版 SimTop.sv（独立 BUILD_DIR）。
  - `xs_wolf_grhsim_ir_aggregate(+_build_emu/_emu)`：复用 `scripts/wolvrix_xs_grhsim_ir.py`，
    通过参数切换 RTL 来源与管线。
- 管线变化（`scripts/wolvrix_xs_grhsim_ir.py`）：
  - `CPU_SEMANTIC_PIPELINE` 中 **移除 reg-to-mem**（aggregate 模式）。
  - ~~评估 comb-lane-pack 在 aggregate 模式下是否直接移除~~ **已定移除
    （2026-10-08）**：comb-lane-pack 退役（当前测试结果确认，见 stage-05 §8 Q1），
    代码删除执行于 stage-02；本阶段仅确认管线无残留注册点。
  - GRH 段管线（xmr-resolve → … → comb-loop-elim → simplify）不变，但 stage-05 的
    片段化默认开启。

### 3.3 子阶段 7c — reg-to-mem 退役

退役分三步，每步可独立验证：

1. **默认关**：aggregate 管线不含 reg-to-mem；legacy 管线保留（对照组）。
2. **移除出全部默认管线**：legacy 输入（标量化 SV）不再支持 XS 规模仿真——
   文档明确"legacy 链路降级为 HDLBits/小用例维护模式"。
3. **代码移除**：删除 `lib/grhsim/pass/reg_to_mem.cpp`、注册点、文档
   `docs/grhsim_ir/passes/reg-to-mem.md` 转为历史记录（划线保留结论，按
   perf-optimization 惯例"被推翻的结论划线不删"）；`benchmark_grhsim_reg_to_mem.py`
   等配套脚本归档或删除。

注意保留 reg-to-mem 文档中的**负结果知识**（为什么标量化前端必须配 reg-to-mem），
防止未来有人重造轮子。

### 3.4 子阶段 7d — 验收

- 正确性（全绿才算完成，不接受豁免）：
  - `make test_wolvrix`
  - `make run_all_hdlbits_grhsim_ir_tests`（162/162）
  - `make run_xs_bugcase_grhsim`（25/25；CASE_009/021/022 在 aggregate 链路上的表现
    单独核对）
  - `make check_sim_refactor_baseline`：trace 基线**重钉**（数组形态改变 op 序列是预期
    行为，逐条核对后 `capture_sim_refactor_baseline` 重新捕获，提交说明引用本计划）
  - XS CoreMark difftest：aggregate RTL + 无 reg-to-mem 管线，轨迹钉死
    instrCnt=663,688 / cycleCnt=297,291（与现行基线相同数值才算"正确仿真"）
- 性能：`make benchmark_grhsim_ir` A/B（旧链路 vs aggregate 链路）。
  目标：不劣于现行基线的 105%（容许 5% 内波动）；若显著更优，更新基线文档。
- 编译时间：记录 emit C++ 的 clang 编译时长（参照 bitint 经验的 30min 闸意识），
  数组保留预期减少 P_general 体积，若编译时间恶化需归因（发射形状问题回 stage-06）。

## 4. 文件级改动点

| 文件 | 改动 |
|------|------|
| `testcase/xiangshan/Makefile` | preserve-aggregate 选项变量化 |
| 根 `Makefile` | `xs_rtl_aggregate`、`xs_wolf_grhsim_ir_aggregate*` 目标族 |
| `scripts/wolvrix_xs_grhsim_ir.py` | aggregate 模式参数；CPU_SEMANTIC_PIPELINE 去 reg-to-mem |
| `wolvrix/lib/grhsim/pass/reg_to_mem.cpp` 等 | 7c-3 移除 |
| `wolvrix/docs/grhsim_ir/passes/reg-to-mem.md` | 转历史记录 |
| `pdocs/perf-optimization/README.md` | 门禁清单更新（aggregate 口径） |

## 5. 风险与缓解（本阶段特有）

| 风险 | 缓解 |
|------|------|
| firtool `all` 档对 XiangShan 不可用 | 7a 先实证；`1d` 档过渡方案；必要时给 circt 提 issue/绕行（struct 字段重排） |
| difftest 数值不一致且难以归因 | 保留 legacy 链路作为对照；按模块二分（`scripts/grhsim_gsim_module_compare.py` 可复用） |
| 性能回退超阈值 | 归因顺序：P_general 体积（数组 op 是否被逐元素展开）→ P_mem 激活率 → 变化检测次数；参照 perf-optimization 既有测量工具链 |
| reg-to-mem 移除后才发现某些 legacy 输入依赖它 | 7c-2 的文档声明 + 移除前全仓 grep 确认无默认管线残留 |

## 6. 完成定义（DoD）

- aggregate XiangShan 链路从 `make xs_rtl_aggregate` 到 difftest 全绿，无 reg-to-mem。
- 本目录各阶段文档的"开放问题"全部有结论（采纳/否决+理由）。
- `wolvrix/docs/` 规范文档与实现一致（grh-ir.md、grh-json-spec.md、grhsim_ir/*）。
- 豁免清单清零；perf-optimization README 门禁更新完毕。
