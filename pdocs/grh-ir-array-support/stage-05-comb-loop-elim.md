# Stage 05 — comb-loop-elim：组合环的片段化切断

- 日期：2026-10-08（2026-10-08 修订：Q1 定稿——comb-lane-pack 退役）
- 状态：计划草案
- 依赖：stage-02（数组一等访问；kSliceArray 不再是分析盲区）
- 对应总目标：#7

## 1. 目标

把 comb-loop-elim 从"位段级假环修复 + 真环报警"升级为：**凡组合环上的 value，一律切成
多个片段（fragment），每个片段独立 SSA 定义，使组合依赖图在片段粒度上无环**。数组 value
引入后，大量"跨元素假环"（`a[i] → b[i] → a[j]` 但位段不重叠）在现有分析中直接落入
uncertain 黑洞，本阶段将其系统性修复。

## 2. 现状事实

**参照实现（2026-10-08 确认）**：reference/gsim 的 `splitArray.cpp` 正是"切数组破组合环"
的现成实现——拓扑遍历卡住时 `getSplitArray` 挑选环上（自指/传递自指）的数组节点，
`splitArrayNode` + `dupTreeWithIdx` 逐元素复制赋值树，把环打到元素粒度
（main.cpp:313 管线启用）。本阶段是同一思想在 GRH SSA value 图上的版本。
另注：gsim 的 `mergeRegister`（reg 合并）在 main.cpp:354 被注释停用——gsim 生产管线
不做 reg-to-mem 式合并，数组保持数组/逐元素形态。

- 实现在 `wolvrix/lib/transform/comb_loop_elim.cpp`（约 3600 行），文档
  `wolvrix/docs/transform/comb-loop-elim.md`。
- 值依赖图上跑 Tarjan SCC；`isBoundaryOp`（110-122）把 kConstant/kRegisterReadPort/
  kLatchReadPort/kDpicCall 当边界。
- 假环（位段不重叠）：`fixFalseLoops=true` 默认修复——先做 slice-retarget 快路径，
  不够再走通用 `splitFalseLoop`（1966+）：环上 value 按 bit-range 切段、逐段重建 op。
  **不插寄存器、不剪边**。
- 真环：默认 warning + 可选 session report；`failOnTrueLoop` 时 error
  （`include/transform/comb_loop_elim.hpp:25-44`）。
- **数组盲区**：位段分析遇 kSliceArray 直接置 uncertain 放弃（`comb_loop_elim.cpp:880-882`）。
  多维数组接入后，数组参与的环会大量出现，此盲区必须消除。

## 3. 设计

### 3.1 片段化模型

- **片段（fragment）**：一个 value 被替换为一组片段 value，每个片段覆盖原 value 的一个
  位段（标量 value）或一个元素/子数组（数组 value），每个片段由各自的 op 定义
  （SSA 在片段粒度保持）。
- **片段格点**：
  - 数组 value：优先按 leading 维切（shape=[d0,rest...] → d0 个 shape=[rest...] 片段）；
    依赖仍成环时递归到下一维，直至元素粒度。
  - 标量 value：沿用现有 bit-range 切段（splitFalseLoop 的机制）。
- **环判定**：片段粒度重建依赖边后重跑 SCC；若环消失 → 假环已修复；仍存在 → 真环，
  按既有 failOnTrueLoop 策略报告。
- **定义重建规则**（每个片段的新 def op）：
  | 原 def | 片段 def |
  |--------|----------|
  | kConcat（同形数组拼接） | 第 i 片段 = 操作数 i（直接重定向，零新 op） |
  | kMux | 每片段一个 kMux（cond 共享，两臂取对应片段） |
  | 按位 op | 每片段一个同 kind op（操作数取对应片段） |
  | kSliceArray | 若索引全常量：片段边界已知，重定向到源数组的对应片段；若含动态索引：该 value **不可按元素切**——回退为"整值单片段 + 动态读合并"，环若残留按真环处理 |
  | kConstant | 按位段拆分常量串 |
  | 其他（含 kSliceDynamic 动态位段） | 与现行 splitFalseLoop 的兜底一致；不可切时升级真环 |

### 3.2 kSliceArray 位段分析（消除 880 行盲区）

- 索引全常量：元素位段 = 行主序公式精确可得 → 参与正常位段分析。
- 索引含动态：读侧保守为"可能触碰整个数组"；写侧（经 memory/RMW）按"整个数组被修改"
  处理——与现行 kSliceDynamic 动态路径的保守策略一致，但**粒度从"放弃分析"细化到
  "数组整体一个区间"**。

### 3.3 保证无环性的终止性论证

- 每次切分严格细化片段格点（leading 维 → 子维 → 元素 → 位段），格点空间有限
  （总位数有限），故终止。
- 切到元素/位段粒度后仍存在的环，在位级依赖上真实存在（或经动态索引不可判定）：
  - 位级真环：按 failOnTrueLoop 报告（语义上无法在不插寄存器的前提下消除，与现状一致，
    本阶段不引入"插寄存器断环"这种改变电路语义的变换）。
  - 动态索引不可判定环：warning + 保守不切（记录到 session report，供 XS 规模审计）。

### 3.4 例子

```systemverilog
logic [7:0] a [0:1];
logic [7:0] b [0:1];
assign a[0] = f(b[1]);
assign b[0] = g(a[1]);
assign a[1] = h(b[0]);
assign b[1] = k(a[0]);
```

value 粒度 SCC = {a, b}（伪环：元素互不依赖）。片段化后：

```
%a0 = f(%b1)   %a1 = h(%b0)    // a 的两个片段
%b0 = g(%a1)   %b1 = k(%a0)    // b 的两个片段
```

片段依赖图：a0←b1←a0？不——b1 = k(a0)，a0 = f(b1) 仍成环！此例恰好说明：必须切到
**元素粒度**后仍成环的才是真环（本例 a0↔b1 是真 2 环）。若源是 `b[1] = k(a[1])` 之类
非交叉依赖，片段化后即无环。pass 的职责是切到能判定为止。

## 4. 文件级改动点

| 文件 | 改动 |
|------|------|
| `wolvrix/lib/transform/comb_loop_elim.cpp` | 片段化框架（§3.1）；kSliceArray 位段分析替换 880 行盲区；SCC 重跑策略；报告格式扩展（片段粒度统计） |
| `wolvrix/include/transform/comb_loop_elim.hpp` | options 增加片段粒度上限（如 `maxFragmentsPerValue`，防爆）、动态索引环策略开关 |
| `wolvrix/docs/transform/comb-loop-elim.md` | 片段化模型与终止性说明 |
| `wolvrix/tests/transform/` | 新增数组假环/真环用例（含 kSliceArray 常量/动态索引混合） |

## 5. 基础设施联动

- diagnostics：真环/不可判定环的 PassDiagnostics 文案带片段粒度信息。
- 与 stage-04 的接口：ingest 不再产出"整数组自环"形态（数组赋值整体化），本 pass 主要
  受益者是 preserve-aggregate 形态下跨数组的交叉依赖。
- 资源防护：`maxFragmentsPerValue` 默认建议 4096，超限按整值处理并记 report
  （防 XS 规模下片段爆炸）。

## 6. 文档更新

- `docs/transform/comb-loop-elim.md`：新增"数组与片段化"章节；明确真环判定标准的变化
  （从 value 粒度变为片段粒度）。
- `grh-ir.md` 无需改动（本阶段不改 IR 语义）。

## 7. 破坏面与回退

- 破坏：组合环报告的内容/计数会变（历史 session report 不可直接对比）；极端情况下
  片段化增加 op 数量，影响下游 simplify 定点时间与编译时间。
- 门禁：HDLBits/xs-bugcase 中触发 comb-loop-elim 的用例输出 IR 形态会变，仿真行为
  不应变（假环修复是等价变换）；trace 基线若 diff 需逐例核对。
- 回退：options 增加 `enableArrayFragmentation` 开关，默认开；关闭即回到现状行为，
  便于 A/B 与紧急回退。

## 8. 开放问题

1. ~~片段化与 comb-lane-pack（反向地把同构 lane 打包成宽位逻辑）的策略冲突：
   数组一等化后 comb-lane-pack 是否直接退役？~~ **已定（2026-10-08 拍板）：退役**。
   依据：默认关即不亏（`pdocs/perf-optimization/20261007-030220-disable-comb-pack.md`）
   加当前测试结果确认可退役；数组一等化后其存在意义进一步下降。移除落点提前到
   stage-02（其 kSliceArray 适配点由"逐一核对"改为直接删除 `comb_lane_pack.cpp`
   及注册点），stage-07 不再单设评估项。
2. ~~动态索引数组写参与的组合环（经 kMemory 异步读回环）~~ **已消解（2026-10-08，
   stage-03 §3.6）**：kMemory 废除后，数组状态读 = kRegisterReadArrayPort = 状态读 =
  边界 op（比现行 kMemoryReadPort 非边界更正确——memory 内容只在时钟边沿变化）。
   组合环不再可能"穿过数组状态"，边界表加入该端口即可。
