# NO0003 转换方向修正：GRH IR → AM Graph → AM Program

日期：2026-08-06
状态：已完成并验收（三份产物字节级不变，AM 10/10）

## 1. 问题

当前转换路径的方向与用户要求相反：

```text
GRH IR --lowering--> LinearProgramArtifact --fromLinearProgram--> AmGraph
      --toLinearProgram--> 回到线性 --> optimize(线性) --> scheduler(内部再进图)
```

线性程序是主载体，图是从它派生、用完即弃的中间形态（pipeline 往返 + 调度器入口各
转一次）。用户明确要求的方向是：

```text
GRH IR --lowering--> GRHSIM AM Graph --（图 pass / 分图 / 分区）--> 物化生成 AM Program
```

即：**AM Graph 是一等 IR**，由 lowering 直接从 GRH IR 构建；线性 AM Program 只在最终
物化（scheduler finalize）时从图生成，不再是阶段间的流通货币。

## 2. 现状盘点（代码核实）

- `pipeline.cpp:943-956`：lower 先产出 `LinearProgramArtifact`，做 AmGraph 无损往返 +
  校验，随后 optimize 仍在线性形式上跑；
- `production_activity_schedule.cpp:1183`：调度器入口 `fromLinearProgram` 进图，分析
  全程读图，finalize（1060 行）`toLinearProgram` 物化——这一段方向本来就是对的；
- `AmGraph::Impl` 直接持有 `ProgramStorage` + interface + valueFacts + effects +
  orderedEffects，容器能力齐备；构建侧尚缺 `reserve/undefInit/zeroInit/addActionsInit/
  addStringLiteral`（对照 `LinearProgramBuilder`）；
- `optimize.cpp`（1517 行）只接受 `LinearProgramArtifact&`，是线性残留的最大一块；
- validate 以 `LinearProgram`/`LinearProgramArtifact` 为入口（内部只读 view，可平移到
  图存储）。

## 3. 修正方案

1. **AmGraph 构建平价**：补齐 init 系列构建器与 reserve，使 lowering 可以原生建图；
2. **lowering 直出 AmGraph**：`builder_` 由 `LinearProgramBuilder` 换成 `AmGraph`，
   变量分类（AmValueKind/AmStateKind）在 addVariable 处直接给出（lowering 掌握全部
   信息，无需事后推导）；`finish()` 改为返回图；
3. **optimize 移植到图**：pass 语义不变，输入改 `AmGraph&`，改写走图变更 API
   （setInstructionOperand/removeInstruction/addInstruction/…）；
4. **pipeline/调度器接线**：阶段间货币改为 `AmGraph`——`lower() -> AmGraph`，
   `optimize(AmGraph&)`，`schedule(AmGraph&&)`（删掉入口的 fromLinearProgram；
   finalize 维持 toLinearProgram 物化）；validate 增加图存储入口；
5. **验证**：香山指令图导出 / block assignment / C++ 发射三份产物与 NO0002 基线
   字节级一致；AM 套件 10/10；difftest 以既有字节结论兜底（字节不变则不重跑）。

## 4. 验收标准

- pipeline 中不存在 linear→graph 的往返转换；`fromLinearProgram` 仅剩测试/兼容用途；
- 香山三份产物字节级不变；AM 10/10；
- 文档（pipeline.md 流水线图、2.4 节、进展注记）同步为新方向。

## 5. 落地记录（2026-08-06）

按方案全部完成：

- **AmGraph 构建平价**：`reserve/undefInit/zeroInit/addStringLiteral/addActionsInit`
  补齐（graph.hpp/cpp），与 `LinearProgramBuilder` 对齐；
- **头文件结构**：新增 `grhsim/am/artifact.hpp` 承接 ProgramInterface/VariableRole/
  SchedulingFacts/LinearProgramArtifact/ExecutableModel 等共享类型，graph.hpp 改依赖
  artifact.hpp，pipeline.hpp 转而包含 graph.hpp——循环包含解开，阶段接口全部改以
  `AmGraph` 为货币（`lower() -> optional<AmGraph>`、`schedule(AmGraph&&)`、
  `run(AmGraph&&)`、`optimizeAmGraph(AmGraph&)`）；
- **lowering 原生建图**：`builder_`（LinearProgramBuilder）换为 `AmGraph amGraph_`；
  变量分类在 addVariable 处直接给出（State/Input/Constant/Comb + Array→Memory），
  latch 等 stateKind 在写发射收口 `recordWriteEffect` 按写 opcode 细化——与
  fromLinearProgram 的推导逐点对应；侧表（roles/effects/orderedEffects）全部由图
  自持；
- **optimize 移植**：alias 表 pass 只读 `graph.program()` 视图；compact 直接重建一张
  新图再整体 move 替换。移植中带出一个真 bug 并当场修复：fold 新增的常量变量在
  旧代码里经 variableRoles 向量继承接口可见性 role 的搬运，图版初版漏了给新常量
  赋 roles，被 validate（external-output roles 对不上 interface）抓住；
- **validate 图入口**：validate.cpp 增加 `validate(ProgramView)`（linear 级检查），
  pipeline.cpp 增加 `validate(const AmGraph&)`（与 LinearProgramArtifact 版同套
  interface/facts 对齐检查）；
- **scheduler**：删掉入口的 `fromLinearProgram`，直接消费图；finalize 维持
  `toLinearProgram()` 物化。

**验收数据**：香山（3,209,648 指令）`instruction_graph.jsonl` /
`block_assignment.jsonl` / C++ 发射源文件三份产物与 NO0002 基线**逐字节一致**；
AM 套件 10/10；全量 ctest 无新增失败（仍只 3 个既有无关项）。发射字节与两次
difftest 通过的基线（73,580/49,996，324.4s/325.8s）相同，不再重复 difftest。

**测试/驱动适配**：9 个文件由子代理并行完成（机械映射：artifact.program.view()→
graph.program()、schedulingFacts→图自持 facts、schedule/runs 调用点、mock 替身签名
等），未改任何测试语义与期望。
