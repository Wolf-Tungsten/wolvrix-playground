# GRH IR 多维数组重构 — 进展跟踪

活账本：README.md 是计划，本文件是进度。规范文档（`wolvrix/docs/grh/grh-ir.md` 等）是承诺。

## 填写规则

1. **每次合入或状态变化必须更新本文件**，并在日志区追加一行（日期 + 内容 + commit/分支）。
2. 阶段状态取值：`未开始` / `进行中` / `已合入` / `阻塞`（阻塞必须在日志写清等什么）。
3. 豁免与破坏的**权威登记在各 stage 文档 §7**（README §5 规则）；本文件只记数量与链接。
   下一阶段开始时清零上一阶段豁免；S7 结束时全部清零。
4. 实施中新冒出来的开放问题先记在本文件对应阶段的"新增问题"行；拍板后回填对应
   stage 文档 §8（~~划线 + 已定 + 日期 + 论证），并从本行删除。
5. 门禁快照口径以 README §6 的基线为准；每次阶段合入时更新一次快照。
6. 实验/测量记录仍按 `YYYYMMDD-hhmmss-<topic>.md` 落在 pdocs 下（README §7），
   日志行里放链接。

## 阶段总览

| 阶段 | 状态 | 合入单元 | 门禁快照 | 豁免 | 下一步 |
|------|------|----------|----------|------|--------|
| S1 IR 数组类型 | 已合入 | 1/1 | 2026-10-09 全绿 | 0 | S2/S3 可开工 |
| S2 kSliceArray 重定义 | 已合入 | 1/1 | 2026-10-09 全绿 | 0 | S3/S5 可开工（S5 等 S2 已满足） |
| S3 kRegister 端口族 | 已合入 | 1/1 | 2026-10-09 全绿 | 0 | S4/S6 可开工 |
| S4 ingest 聚合保留 | 已完成 | 3/3 | 2026-10-09 全绿（含全量设计校验） | 0 | S5/S6/S7 可开工 |
| S5 comb-loop-elim | 已实施 | 1/1 | 2026-10-10 全绿 | 0 | S7 等 S5/S6 |
| S6 grhsim 承接 | 已实施 | 1/1 | 2026-10-10 全绿 | 0 | S7 等 S5/S6 |
| S7 preserve-aggregate 端到端 | 进行中 | 2/3 | 门禁全绿；CoreMark difftest 红（IFU 断言）；单 TU 编译超时待收 | 0 | S7.1 已立项 |
| S7.1 ingest 表达式层逐字段化 | 已实施 | 2/2 | 门禁全绿；XS 护栏 68→0；ingest 190→45s | 0 | emit TU 时长 + CoreMark difftest 待复验 |

依赖图见 README §4：S2∥S3，S5∥S6，S4 是 S7 最大前置。

## 阶段明细

### S1 — IR 数组类型系统（stage-01-ir-array-types.md）

- 状态：已合入
- 合入单元：2026-10-09 shape 全链路 + JSON + grh.verify（工作树未提交，分支 grh/grhsim-ir）
- 门禁快照：2026-10-09 ctest 58 项（55 过，3 例既有失败：transform-comb-lane-pack /
  transform-repcut / ingest-write-back-slice SEGFAULT，stash 对照验证与本次无关）；
  run_all_hdlbits_grhsim_ir_tests 162/162；run_xs_bugcase_grhsim 25/25；
  check_sim_refactor_baseline 162/162
- 豁免/破坏：0（权威登记：stage-01 §8）
- 文档同步：grh-ir.md ☑（§2.3 重写、§6.4 kRegister 属性表） grh-json-spec.md ☑（vals.shape、kRegister attrs）
  python-binding-architecture.md ☑（grh.verify 一句）grh-ir-visualize ☐（不阻塞，顺延）
- 新增问题：无（实施偏差 5 条已记入 stage-01 头部"实施记录"）

### S2 — kSliceArray 重定义（stage-02-slice-array-redefinition.md）

- 状态：已合入
- 合入单元：2026-10-09 kSliceArray 新语义 + ingest 桥接 + 消费端适配 + comb-lane-pack 删除
  （工作树未提交，分支 grh/grhsim-ir）
- 门禁快照：2026-10-09 ctest 58 项 56 过（2 例既有失败：transform-repcut /
  ingest-write-back-slice SEGFAULT）；run_all_hdlbits_grhsim_ir_tests 162/162；
  run_xs_bugcase_grhsim 25/25；check_sim_refactor_baseline 162/162
- 豁免/破坏：0（权威登记：stage-02 §7；旧式 sliceWidth kSliceArray 不再产生也不被接受，
  旧 JSON 产物重新生成即可）
- 文档同步：grh-ir.md §6.2.8 ☑ core.md 映射表 ☑（标注 stage-06 过渡形态）
  grh-ir-visualize 索引展示 ☐（不阻塞，与 stage-01 顺延项一并处理）
- 新增问题：无；stage-02 §8 Q1 被 Verilator 实证推翻并重定稿（emit 保持扁平声明），
  stage-01 §3.1/§3.4 两处相关论断已划线同步
- 顺手修复：const_fold（GRH 侧与 grhsim 侧）sliceArray 索引未乘元素宽度的既有 bug；
  孤儿测试 test_const_fold_pass.cpp 注册进 CMake（新增 transform-const-fold 目标）
- 注意：`make run_all_hdlbits_tests`（Verilator TB 流）在 DUT 042 因 TB 与 Verilator 5.051
  的 VlWide 端口类型不兼容而失败——**既有环境问题，不在门禁清单内**（README §6），
  与本阶段无关（emit 产物本身 Verilation 通过）

### S3 — kRegister 端口族（stage-03-memory-ports.md）

- 状态：已合入
- 合入单元：2026-10-09 kMemory 族 4 OpKind 删除 + kRegister 数组端口族（5 新 kind）
  + 声明顺序优先级 + 全消费端适配（工作树未提交，分支 grh/grhsim-ir）
- 门禁快照：2026-10-09 ctest 58 项 56 过（2 例既有失败：transform-repcut /
  ingest-write-back-slice SEGFAULT）；run_all_hdlbits_grhsim_ir_tests 162/162；
  run_xs_bugcase_grhsim 25/25；check_sim_refactor_baseline 162/162；
  XS CoreMark 轨迹 instrCnt=663,688 / cycleCnt=297,291（与基线逐位一致，
  证明被删的 priority 机制确为无生产者死代码）
- 豁免/破坏：0（权威登记：stage-03 §7；kMemory 族删除为计划内破坏，旧 JSON 产物
  重新生成即可；rank=1 路径行为与现状等价已由门禁证实）
- 文档同步：grh-ir.md §6.4 整体重写 ☑ §6.5 删除 ☑ grh-json-spec.md（端口族 +
  op 顺序语义化条款）☑ grhsim_ir/dialects/core.md 映射表 ☑（标注 stage-06 过渡形态）
  ingest/initial-block-support.md ☑ transform/{memory-init-check,dead-code-elim,
  xmr-resolve}.md ☑ emit/{grhsim-emit-combines,grhsim-scheduling}.md ☑
  grh-ir-visualize 端口族 kind 表 ☑（tsc 通过；vite 构建受 Node 18 环境限制无法验证，
  与 stage-01/02 顺延项同一性质）
- 新增问题：无（实施偏差 7 条已记入 stage-03 头部"实施记录"，含
  firstEventOperandIndex 按 eventEdge 反推、SV emit 用 unpacked 声明、grhsim 过渡映射）
- 顺手修复：repcut isSinkOpKind 补 kRegisterFillPort（旧表遗漏 kMemoryFillPort）

### S4 — ingest 聚合保留（stage-04-ingest-aggregate.md）

- 状态：已完成（2026-10-09，含 XiangShan preserve-aggregate 全量设计校验）
- 合入单元（stage-04 §7 已拆）：(a) kRegister 数组端口族 + 访问路径 ☑（`51f9b5d`：
  状态数组多维化）(b) net/packed 数组 shape 化 ☑（`24fb91e`）(c) struct 字段级拆分 ☑
  （`8026985`：SoA 拆分、聚合表达式子系统、struct 端口逐叶连接、slang 关键字名
  修复分支 wolvrix/keyword-member-names）；收官健壮性 `1426789`（并行 static 池
  thread_local + O(n²) 哈希化）、`e1f0b27`（WriteBackPass 跨递归悬空引用按值拷贝
  ——治愈 HEAD 基线 ingest-write-back-slice SEGFAULT；emitExpr 环守卫；worker
  512MiB 栈）；文档 `a3a2615`（aggregate-types.md 新建 + grh-ir.md §2.3）
- 门禁快照：ctest 57/58（余 transform-repcut 为 HEAD 既有）、hdlbits 162/162、
  xsbug 25/25、baseline 全过；=all smoke 1190 OK / 925 SKIP / 0 FAIL / 0 CRASH、
  =vec smoke 1320 OK / 766 SKIP / 0 FAIL / 0 CRASH；**XS preserve-aggregate=all
  全量设计（SimTop，2115 文件 + sim 顶层）：read_sv 139.4s + grh.verify 3.8s +
  store_json 14.5s（6.17GB JSON），0 error 诊断**
- 豁免/破坏：0（权威登记：stage-04 §7 与实施记录偏差清单；环境级 scratch 补丁 4 处
  登记在案，S7 接入正式管线时复核）
- 文档同步：wolvrix/docs/ingest/aggregate-types.md ☑ grh-ir.md §2.3 ☑
  stage-04 头部实施记录 ☑ 实施滚动日志 stage-04-implementation-notes.md ☑
- 新增问题（登记，归后续阶段）：emitExpr 迭代化（S5）、WriteBackPass 大 stmt 数组
  二次扫描（S6/S7）、XMR 读数组寄存器（S6）、always 块内 `'{...}` 赋值模式（S7）、
  xs_assert_v2 管线口径（S7 定 -D SYNTHESIS 或 assert_dpi 路线）

### S5 — comb-loop-elim 片段化（stage-05-comb-loop-elim.md）

- 状态：已实施（2026-10-10，工作树，分支 grh/grhsim-ir）
- 合入单元：1/1（`e03e33f`：kSliceArray 位段分析 + 动态读整区间归一化 + 分裂重写
  数组适配 + shape 传播；options/CLI/pybind 接线；6 数组环单测；文档章节）
- 门禁快照：2026-10-10 ctest 57/58（余 transform-repcut 为 HEAD 既有，与 S4 同）；
  run_all_hdlbits_grhsim_ir_tests 162/162；run_xs_bugcase_grhsim 25/25；
  check_sim_refactor_baseline 162/162（trace 无 diff）
- 豁免/破坏：0（权威登记：stage-05 §7 + 实施记录；统计行新增 dyn-array=/frag-capped=
  两键，既有键不变；无脚本依赖这些键）
- 文档同步：comb-loop-elim.md ☑（"Array Values And Fragmentation"章节 + 选项表）
  stage-05 头部实施记录 ☑（偏差 6 条：位段机制扩展而非独立框架、动态读归一化实现、
  终止性论证修正、上限语义、边界表已在 S3 落地、诊断扩展）
- 新增问题：无
- 顺手新增：Makefile `test_transform_comb_loop_elim` 单测目标

### S6 — grhsim 承接（stage-06-grhsim-backend.md）

- 状态：已实施（2026-10-10，工作树，分支 grh/grhsim-ir）
- 合入单元：width+shape 类型化（Type.shape、arrayType/TypeKind::Array 退役）+
  op 族 mem* 退役（read/readArray/write/writeArray/fill/latchWrite，memWriteSeq 删除、
  声明顺序优先级）+ verifier/JSON v3（格式串与 core.v2 指纹）/grh_to_grhsim 1:1 承接 +
  CPU 后端多维化（布局摊平/schedule staticRow 折叠/emit 多索引/FST 逐元素）+
  pass 全适配（含 reg_to_mem 空转闸门）。
- 门禁快照：2026-10-10 ctest 57/58（余 transform-repcut 为 HEAD 既有，与 S4/S5 同）；
  run_all_hdlbits_grhsim_ir_tests 162/162；run_xs_bugcase_grhsim 25/25；
  check_sim_refactor_baseline 162/162（trace 无 diff）；**XS CoreMark 全量 difftest
  `HIT GOOD TRAP`，instrCnt=663,688 / cycleCnt=297,291 与基线逐位一致，主机时间
  285.3s 与基线 281.5s 持平**（首轮实现曾因 sliceArray 打包-切片发射形状退化至 3929s，
  经 rowBackedArrayText 直达行索引修复；日志
  `build/logs/xs/xs_wolf_grhsim_20261010_083619.log` 与复跑日志）。
- 豁免/破坏：0（权威登记：stage-06 §7；mem* op 退役与 grhsim v2 checkpoint 失效为
  计划内破坏，旧 checkpoint 重新生成即可；单维路径门禁全绿已证实）
- 文档同步：core.md ☑（§2/§5/§8/§10 重写 + 契约翻转）cpu-st.md ☑ cpu.md ☑
  overview.md ☑ passes/ 15 篇 ☑
- 新增问题：无（实施偏差 10 条 + 顺手修复 5 条见 stage-06 头部"实施记录"；
  scripts/ 若干 census 脚本引用旧 op 名未更新，非门禁项）
- 顺手修复：GRH const_fold 常量 shape 传播（CASE_005 实证）；used-bits 非跟踪值
  cone pinning + pinned 单调标记（CASE_003 挂起/CASE_021 死写误删实证）；emit rowOf
  单动态索引补 stride；emit state.read 分派按 state 类型 shape 判定。

### S7 — preserve-aggregate 端到端（stage-07-preserve-aggregate-e2e.md）

- 状态：进行中（7a/7b/7c 已落地并全绿；7d 卡在组合环阻塞，见 stage-07 头部"当前阻塞"节）
- 合入单元：7a（firtool 链路接入）☑ 7b（Makefile/管线接入）☑ 7c（reg-to-mem 退役三步）☑ 7d（验收）☐
- 门禁快照：2026-10-10 ctest 56/57（余 transform-repcut 既有）、hdlbits 162/162、
  xsbug 25/25、trace 基线 162/162 无 diff（reg-to-mem 在 HDLBits 零触发，免重钉）
- 豁免/破坏：0（reg-to-mem 移除为计划内破坏）
- 文档同步：perf-optimization README 门禁改 aggregate 口径 ☑ pass-flow/architecture
  退役注记 ☑ reg-to-mem.md 转 RETIRED ☑ grh-ir.md kRegisterReadPort shape 契约修订 ☑
- 新增问题（实证后登记）：编译期超线性（已修：topo_guard 拓扑守卫 + lean 化）；
  shape 别名根因（已修：核心 guardShapeAlias）；**组合环阻塞**（未决，归 stage-08 候选）
- 顺手修复：mill 调用的 JDK17/PATH 环境自包含（XS_MILL_ENV）；simplify 迭代计时日志

### S7.1 — ingest 表达式层逐字段化（stage-07.1-ingest-expression-fieldwise.md）

- 状态：**已实施**（2026-10-12，wolvrix 子模块 `db26c6c` + `de30748` + `3990ccf`）
- 立项事由：aggregate 管线 emit 出 `_BitInt(138240)`（robEntries 案例：
  `{160{864位struct}}` replicate），clang 单 TU 60–90min 违反 ≤15min 约束；
  根因 = ingest 表达式层聚合→扁平物化逃生口（lowerExpression struct 兜底
  flatten，ingest.cpp:9817-9830 等 6 处），mux-tree-fold 对位-blast 形态失配
- 合入单元：2/2（ingest 逐字段化+护栏 `db26c6c`；fold P2 数组宽 pad-concat
  `de30748`；fixture `3990ccf`）
- 门禁快照：ctest 57/58（transform-repcut 既有失败）、A/B 16/16、HDLBits
  162/162、xsbug 25/25、trace 162/162；XS 护栏告警 68→0、ingest 190→45s、
  flat GRH >4096 位 value 287→238（残余全为既有非聚合形态：测试台大常量/
  endpoint 拼接/整组读口/1 个纯位向量 pad-concat——§3.5 明记残余）
- 豁免/破坏：0（计划内破坏：旧 GRH JSON 产物重生）

## 日志

- 2026-10-12：S7.1 实施完成。`lowerStructRhsFieldWise` 统一 part 降低
  （struct/单元素 concat/replicate 三种 part，逐叶 kReplicate/kConcat，
  ingest.cpp `db26c6c`）；mux-tree-fold 新增 P2 数组宽 pad-concat 读折叠
  （`de30748`，顺手修临时 Operation operands() 悬空 span 崩溃）；fixture
  `ingest-struct-array-fieldwise`（`3990ccf`）。XS 实测：护栏告警 68→0、
  ingest 190.4s→45.2s、flat GRH >4096 位 value 287→238（残余均为既有非聚合
  形态）；门禁 ctest 57/58（repcut 既有）、A/B 16/16、HDLBits 162/162、
  xsbug 25/25、trace 162/162。Q1/Q3/Q4 回填（见 stage-07.1 §9.3）。
- 2026-10-12：S7.1 立项。S7 进展补记：mux-tree-fold pass（fold 7.2s，simplify
  1335s+→368s）、ingest 元素读 widthHint 根修、CLE 零拷贝（672s→83s）、fanout
  合写 + 连接隐式转换根修均已落地，门禁全绿（ctest 57/58、hdlbits 162/162、
  xsbug 25/25、trace 162/162）；未收口：CoreMark difftest 红（IFU 断言，
  前端潜伏 bug 待波形定位）、尾部 TU 编译超时（根因即 S7.1 要消灭的超宽物化）。
- 2026-10-09：进展跟踪格式约定建立。设计已全部定稿（stage-01~07 共 17 条开放问题清零）；
  探针完成（`20261008-preserve-aggregate-probe.md`：preserve-aggregate=all 产物
  100% packed 聚合、维度普查、保真度普查、gsim 对照）。S1 可开工。
- 2026-10-09：S1 实施完成并合入（工作树）：Value/GraphView/GraphBuilder shape 一等化
  （构造期硬校验）、JSON vals.shape 读写、`grh.verify` 校验 pass、grh-ir.md/grh-json-spec.md/
  python-binding 文档同步。门禁：ctest 55/58（3 例既有失败，stash 对照与本次无关）、
  hdlbits 162/162、xs-bugcase 25/25、sim-refactor 基线 162/162。实施偏差 5 条见 stage-01 头部。
  同日修正：~~kRegister shape/init 族属性常量~~——shape 是声明类型契约（与 width 同级，
  裸字符串键），不定义常量；见 stage-01 实施记录 #6。
- 2026-10-09：S2 实施完成并合入（工作树）：kSliceArray 新语义（无 sliceWidth、1..N 索引、
  shape 承载几何）、ingest 桥接（新增 setValueShape 回填 API）、const_fold/slice_index_const/
  SV emit/grh_to_grhsim 适配、comb-lane-pack pass 整体删除（含 pybind 适配器与脚本管线）。
  实证推翻 stage-02 §8 Q1（packed 声明下扁平位选择语义错误），emit 保持扁平声明 +
  行主序线性化。门禁：ctest 56/58（2 例既有失败）、hdlbits 162/162、xs-bugcase 25/25、
  基线 162/162。详见 stage-02 实施记录。
- 2026-10-09：S3 实施完成并合入（工作树）：kMemory 族 4 OpKind 删除，数组状态统一为
  kRegister+shape；端口族 kRegisterReadArrayPort/WriteMaskPort/WriteArrayPort/
  WriteArrayMaskPort/FillPort 落地（多索引、部分索引=子数组，与 kSliceArray 对齐）；
  写端口优先级改为同 regSymbol 唯一组+声明顺序（priority 属性与 activity_schedule/emit
  两侧死代码机制整段删除）；firstEventOperandIndex/arrayPortIndexCount helper 进 grh 核心
  （按 eventEdge 反推事件边界）；ingest 最小适配 + 双写路径声明去重；grh.verify 端口族
  校验；SV emit 全端口族（unpacked 声明，rank=1 文本零差异）；grh_to_grhsim 过渡映射到
  既有 mem*/regWrite（无 mask 形态合成全 1 mask，mem* 退役归 S6）。门禁全绿：
  ctest 56/58（2 例既有失败）、hdlbits 162/162、xs-bugcase 25/25、基线 162/162、
  XS CoreMark 663,688/297,291 与基线逐位一致。详见 stage-03 实施记录（7 条偏差）。
- 2026-10-09（晚）：S4 完成。XS preserve-aggregate=all 全量设计（SimTop）编译链路
  read_sv + grh.verify + store_json 全过（6.17GB JSON、0 error）；全量校验驱动四轮
  健壮性修复合入（并行 static 池 thread_local、O(n²) 哈希化、WriteBackPass 跨递归
  悬空引用按值拷贝——顺带治愈基线 ingest-write-back-slice SEGFAULT、emitExpr 环
  守卫、worker 512MiB 栈）。门禁 ctest 57/58（余 transform-repcut 基线）、其余全绿；
  =all/=vec smoke 双 0 FAIL 0 CRASH。S5/S6 可开工。
- 2026-10-10：S5 实施完成（工作树，分支 grh/grhsim-ir）：comb-loop-elim 数组感知化——
  kSliceArray 位段分析替换 880 行盲区（常量索引行主序精确位段；动态/越界索引把基数组
  归一化为整值单区间并补索引依赖边；含动态读的环要求位段图完全无环才认假环，否则
  不可判定报警带 dynamic-array-read 注释）；分裂重写数组适配（常量索引逐段复制、动态
  读整值单片段+全视图重定向、整值片段与重组视图传播 shape 保 verifier 合法性、
  maxFragmentsPerValue=4096 超限放弃切分）；options/CLI/pybind 三开关接线；6 数组环
  单测全过（含 grh.verify 复检）；comb-loop-elim.md 新增数组章节。门禁：ctest 57/58
  （余 transform-repcut 为 HEAD 既有）、hdlbits 162/162、xs-bugcase 25/25、基线
  162/162。探针实证：dyn_loop 假环从 analysis=incomplete 黑洞变为修复。详见
  stage-05 实施记录（6 条偏差，含终止性论证修正）。S6/S7 可开工（S5 依赖已清）。
- 2026-10-10（深夜）：S7 开工。7a/7b/7c 落地并全绿（`xs_rtl_aggregate` 375s/2148 文件；
  reg-to-mem 全退役：wolvrix −3234 行 + 外层管线/Makefile/脚本清理；trace 基线实证
  免重钉）。编译期攻坚：GRH simplify 在聚合设计（18.7M values）超线性爆炸，实证修复
  topo_guard 拓扑守卫（simplifySlices 700s→127s）+ 三 pass lean 化；shape 根因闭环
  （Graph::replaceAllUses/replaceResult 核心守卫 + verifier tiling 放宽 + RE/CSE 别名
  预检）。门禁：ctest 56/57（余 repcut 既有）、hdlbits 162/162、xsbug 25/25、trace
  162/162。**7d 卡在 cpu.st.build-general-nodes 组合环**——aggregate 独有的 8 个
  值级假环（struct 端口束 pack/slice 往返 + 动态状态数组读回馈；基线标量化零环已复核，
  排除 S5 回归）；逐边证据与方向见 stage-07 头部"当前阻塞"节。三仓库已提交中间态。
- 2026-10-10：S6 实施完成（工作树，分支 grh/grhsim-ir）：GrhSIM 类型系统 width+shape 化
  （arrayType/TypeKind::Array/DeclProvenance.shape 退役，logicType 带 shape intern）；
  state 访问 op 族统一 read/readArray/write/writeArray/fill（mem* 六名整体退役，
  memWriteSeq 改为声明顺序多 write op）；verifier 全族几何校验（state 边界按总位宽契约，
  实证 GRH 扁平/shape 混合形态）；JSON `wolvrix.grhsim.v3` + 指纹 `wolvrix.grhsim.core.v2`；
  grh_to_grhsim 1:1 承接（过渡线性化/展开代码删除）；CPU 后端布局/schedule/emit/FST 多维化
  （物理平坦行数组 + 发射端行主序线性化 + FST 逐元素 512B 阈值）；pass 全适配。门禁：
  ctest 57/58（余 transform-repcut 为 HEAD 既有）、hdlbits 162/162、xs-bugcase 25/25、
  baseline 162/162（trace 无 diff）、**XS CoreMark 全量 difftest HIT GOOD TRAP、
  instrCnt=663,688 / cycleCnt=297,291 与基线逐位一致**。实证修复：GRH const_fold 常量
  shape 传播、used-bits 非跟踪值 cone pinning（pinned 单调标记）、emit rowOf 动态单索引
  stride、state.read 按 state shape 分派、kSliceArray 扁平基值转换层兜底（单索引
  1-D 视图）。详见 stage-06 实施记录（偏差 11 条）。S7 可开工（S5/S6 依赖已清）。
