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
| S4 ingest 聚合保留 | 未开始 | 0/3 | — | 0 | 等 S1/S2/S3 |
| S5 comb-loop-elim | 未开始 | 0/? | — | 0 | 等 S2 |
| S6 grhsim 承接 | 未开始 | 0/? | — | 0 | 等 S1/S3 |
| S7 preserve-aggregate 端到端 | 未开始 | 0/3 | — | 0 | 等 S4/S5/S6 |

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

- 状态：进行中
- 合入单元（stage-04 §7 已拆）：(a) kRegister 数组端口族 + 访问路径 ☑（2026-10-09，
  状态数组多维化：声明 shape、多索引端口、whole 读写直连、合并机制退役、grhsim 过渡承接）
  (b) net/packed 数组 shape 化 ☐ (c) struct 字段级拆分 ☐
- 门禁快照：2026-10-09 S4-a 合入点 ctest 56/58（基线 2 例持平）、hdlbits 162/162、
  xsbug 25/25、baseline 162/162；=vec split 2119 文件 smoke 1237 OK/766 依赖 SKIP/
  真失败 2（1 属 S4-b、1 为 HEAD 既有崩溃）
- 豁免/破坏：0（权威登记：stage-04 §7；同地址写合并退役为计划内破坏，xsbug 25/25 证明
  声明顺序优先级语义等价）
- 文档同步：wolvrix/docs/ingest/ ☐ grh-ir.md §2.3 ☐（S4 全部合入后统一落）
  实施记录：stage-04-implementation-notes.md（随实施滚动）
- 新增问题：无（开放登记：`'{...}` assignment pattern 表达式既有不支持——S7 关键路径
  待评估；Phr emitExpr 组合环栈溢出为 HEAD 既有）

### S5 — comb-loop-elim 片段化（stage-05-comb-loop-elim.md）

- 状态：未开始
- 合入单元：—（`enableArrayFragmentation` 开关默认开，stage-05 §7）
- 门禁快照：—
- 豁免/破坏：—（权威登记：stage-05 §7；trace 基线 diff 逐例核对）
- 文档同步：comb-loop-elim 文档 ☐
- 新增问题：无

### S6 — grhsim 承接（stage-06-grhsim-backend.md）

- 状态：未开始
- 合入单元：—（width+shape 类型化 / op 族 mem* 退役 / CPU 后端 / JSON，建议按此拆）
- 门禁快照：—
- 豁免/破坏：—（权威登记：stage-06 §7；单维路径必须保持全绿）
- 文档同步：core.md ☐ cpu.md ☐ cpu-st.md ☐ overview.md ☐
- 新增问题：无

### S7 — preserve-aggregate 端到端（stage-07-preserve-aggregate-e2e.md）

- 状态：未开始
- 合入单元：7a（firtool 链路接入）☐ 7b（Makefile/管线接入）☐ 7c（reg-to-mem 退役三步）☐
- 门禁快照：—（终极验收：全部豁免清零 + CoreMark 轨迹钉死 + 性能不回退）
- 豁免/破坏：—
- 文档同步：README §6 门禁表更新 ☐
- 新增问题：无

## 日志

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
