# stage-07.1 ingest 表达式层逐字段化（消灭聚合物化逃生口）

- 日期：2026-10-12
- 状态：**已实施**（wolvrix 子模块 `db26c6c` ingest 逐字段化 + 宽度护栏、
  `de30748` mux-tree-fold 数组宽 pad-concat 折叠、`3990ccf` ingest fixture）
- 依赖：stage-07（mux-tree-fold 已就位，本阶段是它的前置补强而非替代）
- 动机事件：aggregate 管线 emit 出 `_BitInt(138240)` 等超宽值，clang 单 TU
  编译 60–90min，违反"单 TU ≤ 15min"硬约束；且整元素装配路径正是
  `{63'b0, data0, 7'b0, tag0}` 错值 bug（stage-07 实施记录 · widthHint 根修）
  的滋生地——逃生口一日不除，功能与编译期风险并存。

## 1. 背景与根因

stage-04 定稿（README §3、stage-04 §3.1-2）：**struct 永远不成为 GRH value**，
声明/net/端口递归拆成叶子字段信号（`c__DOT__a`，DOT 编码），数组维度迁移到
每个字段信号上。但 stage-07 端到端实测发现该纪律只覆盖到**声明侧**，表达式层
存在一条总闸式逃生口：

```text
SV: Rob.sv:7826-7834
  wire struct packed {…864 位…} [159:0] _GEN_1182 = {160{robEntries[9'h0]}};
  wire struct packed {…864 位…} [511:0] _GEN_1183 = {_GEN_1182, robEntries};
  wire struct packed {…864 位…}         _GEN_1184 = _GEN_1183[deqPtrVec[3'h0].value];

ingest（现状）:
  lowerExpression(ReplicationExpression)              ingest.cpp:10960
    └─ lowerExpression(robEntries[9'h0'])  ── struct 类型兜底 ──►
       lowerAggregateValues（逐叶，正确） → flattenAggregateValues（拼回 864 位）
                                                            ingest.cpp:9817-9830
    └─ kReplicate ×160  →  138240 位 GRH value

flat GRH 实证: _op_2649197 kReplicate rep=160 → _val_2218456 w=138240
               （loc = Rob.sv:7827:17；全部使用者为逐位 kSliceStatic）
emit 实证:   build/xs/grhsim-ir-aggr/model/grhsim_SimTop_tu270.cpp:7-9
             unsigned _BitInt(138240) cpu_rep … 160 次循环移位或
```

设计原本的假设是"ingest 暂时物化 → mux-tree-fold 折回动态读 → 死锥清扫"
（stage-07 §图瘦身主修复明写 robEntries 案例）。但该实例**活过了 fold**：
flat GRH（fold 之后）中 replicate 仍在，其消费形态是逐位 kSliceStatic
（同字段位、按 864 步进跨 rep），fold 的元素粒度 pad 读/读树匹配
（mux_tree_fold.cpp:1370 起）认不出来。位-blast 的引入点待归因
（`WOLVRIX_MUXFOLD_DEBUG` 可给组级 bail 原因；嫌疑：`_GEN_1183` 的
320 项内容零扩展到 `[511:0]`，concat 与动态读之间夹了扩展 op）。

**结论：不能把超宽值的消灭寄托在 fold 的逆向识别上——必须在 ingest 表达式层
让 struct/数组整体根本不成为 value。** 这是 stage-04 SoA 定稿在表达式侧的补课。

## 2. 现状盘点（逃生口清单，全部位于 wolvrix/lib/core/ingest.cpp）

| # | 位置 | 形态 | 现状行为 | 产物宽度 |
|---|------|------|----------|----------|
| E1 | `lowerExpression` struct 兜底 9817-9830 | 一切 struct 类型表达式的通用入口 | `lowerAggregateValues` 逐叶后**立即** `flattenAggregateValues` 拼回单扁平值（注释自述 "flatten to the packed layout at this boundary"） | 元素宽 × 数组维（无上限） |
| E2 | ReplicationExpression lowering 10960-10980 | `{N{s}}`，s 为 struct（元素/整数组） | `lowerExpression(repl->concat())` 经 E1 打平后 kReplicate | N × 操作数宽（robEntries 案例 160×864=138240） |
| E3 | ConcatenationExpression lowering 10920-10959 | 含 struct/数组操作数的 concat | 每个操作数直接 `lowerExpression` 经 E1 打平 | Σ 操作数宽（`{_GEN_1182, robEntries}` → 276480，零扩后 442368） |
| E4 | `lowerArrayPatternValue::fillFromComponent` 8727-8742 | struct 元素的赋值 pattern `'{…}` | `values.size()>1` 时逐元素 `flattenAggregateValues`，再逐元素 concat | 整个数组一根宽值 |
| E5 | `lowerStructRhsValues` 扁平 RHS 分支 3246-3300 | `arr <= '0` / `arr <= {…}`（flat RHS 驱动 struct 数组 LHS） | 先 `lowerExpression` 成**整宽** flat 值，再 `collectSvLeafSegments` 逐叶 gather | 整数组宽（138240 级） |
| E6 | `flattenAggregateValues` 8585-8670 | 装配器本体（含 `collectSvLeafSegments` 元素主序 scatter 布局） | 合法存在，但调用面必须收缩到"元素级" | 见各调用方 |

已就位的正确基础设施（本阶段复用，不新造）：
`lowerAggregateValues`（9232，已覆盖 NamedValue/MemberAccess/ElementSelect/
Conditional/隐式 Conversion 的逐叶降低）、`elementSelectOnLeaf`（8503）、
`collectSvLeafSegments`/`svLeafSegmentsTrivial`（1258-1467）、写侧 scatter
（3180-3300 前半）、连接侧 `elementSelectOnLeafConn`（23405）。

## 3. 设计

### 3.1 总原则

**AggregateExpr 是 struct 表达式在表达式层的标准表示，flatten 只准发生在
"确证位向量边界"且宽度 ≤ 单元素宽的场合。** 具体地：

- `lowerExpression` 的 struct 兜底（E1）不再是"逐叶后立刻 flatten"；
  消费 struct 表达式的上下文必须改为聚合感知（逐字段处理）。
- 引入**宽度护栏**：任何 flatten/装配产物的宽度 > `kAggregateFlattenWarnWidth`
  （默认 4096，env `WOLVRIX_AGGREGATE_FLATTEN_WARN_WIDTH` 可调）时发 warn 级
  ConvertDiagnostics（含 loc）。XS 全量跑必须零新增——护栏即回归测试。
- 数组维度的乘法（N × 元素宽）在任何装配路径中被禁止；装配只允许到
  单元素宽度为止。

### 3.2 逐形态规则

| 形态 | 现行为 | 目标行为 |
|------|--------|----------|
| `{N{s}}`（s 为 struct，单元素或整数组；数组性也可来自 N 次复制本身） | kReplicate(N × structWidth) | 逐叶：`{N{s.f}}` 每叶一个 kReplicate（N × leafWidth），结果 AggregateExpr |
| 同构 concat（`{rep, arr}` 等数组合并） | 整宽 kConcat | 逐叶 kConcat（`{rep_f, arr_f}`），pad 拼接读形态在字段粒度上照旧被 mux-tree-fold 折叠 |
| 异构混合 concat（struct 与标量混排） | 整宽 kConcat | 允许 struct 操作数**元素级**打平（≤ 元素宽）参与 concat；禁止带数组维打平 |
| 动态读 `arr[idx]`（struct 元素） | 逐叶 elementSelectOnLeaf（已正确，E1 之后才打平） | 逐叶 kSliceArray 直接进 AggregateExpr，不过 E1 |
| 整数组引用（NamedValue）作操作数 | 逐叶后 E1 打平成整宽值 | 禁止 flatten；消费方必须聚合感知，否则 reportUnsupported |
| 扁平 RHS 写 struct 数组（E5） | 整宽 flat 值 + gather | 常量快路径：全 0/全 1 直接逐叶生成常量（不建宽常量）；非常量 concat RHS 按叶段直接从其组成操作数取（concat-切片对消），不先拼整宽 |
| 聚合比较/归约（`arr == '0` 等） | 打平后比较 | 逐叶比较 + and/or 归约 |
| struct → 扁平 logic cast / $bits / 非聚合边界 | 打平 | 合法残余：仅元素级宽度允许 flatten |

### 3.3 例子（robEntries 案例改造前后）

```text
前：{160{robEntries[9'h0]}}
    → kReplicate(864) = 138240 位 value
    → {_GEN_1182, robEntries} kConcat = 276480 位（零扩 442368）
    → [idx] 动态读 864 位 → fold 失配（位-blast）→ _BitInt(138240) 活到 emit

后：对 robEntries 的 ~40 个叶 f（宽 1..64）：
    叶 f: {160{robEntries__DOT__f[9'h0]}}        kReplicate(w_f)   ≤ 160×64=10240 位
    叶 f: {rep_f, robEntries__DOT__f}             kConcat          ≤ 2×10240 位
    叶 f: [idx]                                  逐叶动态读
    → mux-tree-fold 按 pad 拼接读折成钳位动态读口（字段粒度，模式不变）
    → 宽值在 fold 后死亡清扫；残余宽度上限从 138240 压到 ≤ 10240，
      且全部是可折形态
```

### 3.4 与 mux-tree-fold 的关系

fold 不退役、不弱依赖：逐字段化后 fold 的输入从"一个 864 位元素的 pad 拼接"
变成"~40 个窄 pad 拼接"，匹配逻辑不变（元素宽变小而已）。位-blast pad 读的
fold 补强（逐位叶 + 零扩展夹层识别）记为**待评估项**——ingest 改完后复测，
若该形态不再产生则不做（§8 Q1）。

### 3.5 与 stage-08（emit 宽状态词阵列化）的关系

本阶段把"struct/数组整体"从 value 空间挤出后，残余超宽值只剩两类：
纯位向量数组的整体操作（如 `logic [159:0][63:0]` 的整数组 replicate，
10240 位级）与 memory 行。emit 侧词数组/按词发射改造（stage-08）的范围随之
收窄，两阶段顺序执行、各自验收。

## 4. 改动点（文件级清单）

| 文件 | 内容 |
|------|------|
| `wolvrix/lib/core/ingest.cpp` | E1 兜底拆除：struct 表达式上下文逐字段化（replicate 10960、concat 10920、数组 pattern 8727、扁平 RHS 写 3246、比较/归约各入口）；flatten 调用面收缩到元素级；宽度护栏诊断 |
| `wolvrix/lib/transform/mux_tree_fold.cpp` | 无计划内改动；位-blast pad 读补强为待评估项（§8 Q1） |
| `wolvrix/tests/ingest/` | 新增 fixture：struct 数组 replicate / pad 拼接读 / 扁平 RHS 写 / 聚合比较，断言 GRH 无 > 阈值非 memory value |
| `scripts/`（新小工具或既有扫描器扩展） | flat GRH / grhsim IR 的"超宽非 memory value"扫描，接入 XS 管线日志 |

## 5. 基础设施联动

- 诊断：新增 warn 级 `aggregate flatten width guard`（ConvertDiagnostics，含 loc）。
- 持久化/可视化/Python 绑定：无格式变更（只改变 op 构成，不改 schema）。
- mux-tree-fold 的 `WOLVRIX_MUXFOLD_DEBUG` 归因输出保留，用于 §8 Q1 评估。

## 6. 验证门禁（DoD）

1. `make test_wolvrix` 全绿（新增 ingest fixture 必过）。
2. `ptmp/mux-fold-repro/` 全部 A/B 回归逐位一致。
3. HDLBits GrhSIM 162/162、xsbug 25/25、黄金 trace 162/162。
4. XS aggregate 管线：flat GRH 与 grhsim IR 中**无 > 4096 位非 memory value**
   （扫描器输出前后对比：138240/79296/65536/75008 全部消失）。
5. emit model 无 `_BitInt(>4096)`（memory 行/helper 内部除外）。
6. **clang 单 TU ≤ 15min**（硬指标，记录最慢 5 个 TU 的前后对比）。
7. CoreMark difftest：HIT GOOD TRAP 且 instrCnt=663,688 / cycleCnt=297,291。
8. mux-tree-fold 计数不显著退化（padReads/writeGroups 前后对比记录）。

## 7. 破坏面与回退

- 旧 GRH JSON 产物全部重生（格式不变，内容构成变化）。
- flatten 护栏可能暴露此前静默的 unsupported 形态：一律先 warn 登记，
  逐条评估是转逐字段还是维持元素级 flatten。
- 回退：单 commit 一个形态（先 replicate+concat，再 pattern，再写 RHS，
  再比较/归约），任一形态回归可独立 revert。

## 8. 开放问题

- Q1：位-blast pad 读是否仍需 fold 补强？（ingest 逐字段化后复测决定；
  若消失则不动 fold。）
- Q2：护栏阈值 4096 是否合适？待 XS 全量的宽度分布直方图出来后定稿。
- Q3：异构混合 concat 的"元素级打平"是否会被真实设计击穿（存在
  >4096 位的单元素 struct）？robEntries 元素 864 位，余量充足；
  若出现超限元素，升级为逐叶段 concat（collectSvLeafSegments 逆向 scatter）。
- Q4：位-blast 的引入点（fold 之前哪一步把 864 位读拆成逐位）尚未归因；
  不影响本阶段设计，但结果要回填本节（顺手用 `WOLVRIX_MUXFOLD_DEBUG`）。

## 9. 实施记录（2026-10-12）

### 9.1 落地改动

1. **`lowerStructRhsValues` 逐字段快路径**（`lowerStructRhsFieldWise`，
   ingest.cpp，commit `db26c6c`）：flat 兜底之前先按叶降低
   replicate/concat RHS。所有 part 经统一的 `lowerOnePart`：
   struct 表达式走 `lowerAggregateValues`；单元素 concat（slang 把 `{e}`
   规范成 1 操作数 ConcatenationExpression，类型是扁平位向量——实测
   操作数 kind=15=`Concatenation`）循环解包；`{K{u}}`（u 为 struct）
   逐叶生成 kReplicate。逐叶宽度检查（`structLeafElementWidth` 对齐
   LHS 叶序），产物逐叶 `resizeValueToWidth` 到叶平铺宽——与旧的
   "先整宽物化再逐段 gather" 在位布局上逐位等价（元素主序下逐叶
   MSB 侧零扩/截断 ≡ 整宽 MSB 侧零扩/截断）。
2. **宽度护栏**（同 commit）：`flattenAggregateValues` 与 flat RHS 兜底
   在 >4096 位（env `WOLVRIX_AGGREGATE_FLATTEN_WARN_WIDTH`）时发 warn 级
   ConvertDiagnostics；`WOLVRIX_FIELDWISE_DEBUG=1` 打印逐字段 bail 原因。
3. **mux-tree-fold P2 数组宽 pad-concat 读折叠**（`tryFoldArrayPadConcat`，
   commit `de30748`）：逐字段化后 pad 拼接读的新形态是
   `kSliceArray(kConcat(kReplicate(K, elem), regReadPort), idx, w)`——
   concat 输入是**数组宽**段而非元素宽段，原 pattern P 认不出。
   P2 要求 LSB 输入为 rank-1 寄存器的整数组读、MSB 各段为统一 pad 游程
   （单元素宽值的 kReplicate 或全零常量），折成与 P 相同的钳位/旁路读。
   顺带修了一个悬空 span 崩溃：嵌套 concat 展平循环遍历了
   `graph_.getOperation(def).operands()` 临时对象的 span（Operation 按值
   返回，operands() 指向其自有存储）。
4. **ingest fixture**（commit `3990ccf`）：`tests/ingest/ingest_struct_array_fieldwise`
   断言三种形态下无超过"最大叶宽 × 最大维数"的 value（整数组扁平
   36864/11520 不得出现），且存在逐叶 replicate（160×64）。

### 9.2 实测结果

- repro（robEntries 同形态 72 位 struct × 160/352/512）：flat GRH
  >4096 位 value 6 → **0**（P2 折叠 + 死锥清扫连 22528 的整组读口也消掉）。
- **XS 全量**（`ptmp/stage071-repro/xs_scan.py`，ingest + GRH 管线 +
  flat GRH 扫描）：
  - 护栏告警 **68 → 0**（68 条全部是 replicate/concat 形态，全部被
    commit-2 的 part 统一降低覆盖：`_robBanks_WIRE` 单元素 concat 链、
    `{{8{uop[0]}}, uop}` / `{{56{vecReplay[0]}}, vecReplay}` 嵌 replicate
    part、`{4{reqs[0]}}, reqs}` 等）。
  - **ingest 190.4s → 45.2s**（4.2×，不再物化整数组宽中间值）。
  - flat GRH >4096 位 value 287 → 238：消失项含 138240 kReplicate、
    75152 kReplicate（LoadQueueReplay `{{56{vecReplay[0]}}, vecReplay}`）、
    全部 rob pad-concat 叶（32768/25600/24576，被 P2 折叠）；
    残余全部是**既有非聚合形态**：LogPerfEndpoint 测试台大常量
    （~200 个、最大 1.4M 位，两块管线共有）、endpoint harness 端口拼接
    （endpoint$in 79263 等）、整组寄存器读口（22528，stage-08 范畴）、
    以及 1 个**纯位向量数组** pad-concat（`_GEN_15717` = `{160{pdest[0]}},
    pdest`，元素 `[7:0][7:0]` 非 struct，读结果是 shaped value 被 fold
    候选过滤跳过——§3.5 明记的两类残余之一）。
- 门禁：ctest 57/58（唯一失败 transform-repcut 为既有失败）、
  mux-fold-repro A/B 16/16、HDLBits GrhSIM 162/162、xsbug 25/25、
  黄金 trace 162/162。

### 9.3 开放问题回填

- Q1：**不需要**原设想的逐位叶 fold 补强；实际需要且已落地的是 P2
  数组宽 pad-concat 匹配（§3.4 的"模式不变"假设不成立——逐字段化把
  concat 输入从元素宽段变成了数组宽游程，匹配器必须新增而非复用）。
- Q2：阈值 4096 维持。XS 残余 >4096 全部是既有非聚合形态，护栏对
  struct 聚合路径零误报。
- Q3：未被击穿——XS 最大单元素 struct 1245 位（`{valid, bits}`），
  元素级 flatten 余量充足。
- Q4：位-blast 引入点 = **E5 flat 兜底的 `sliceLeafFromFlatValue` 段
  gather**：1 位叶在 160 元素数组里的布局是 160 个 1 位段（元素主序
  scatter），逐段切出来再 concat——这就是 864 步进逐位 kSliceStatic 的
  来源。逐字段化后该路径对这些形态不再执行。

### 9.4 未做的逃生口（护栏静默即不实施）

E4（数组 pattern 逐元素 flatten）、E5 常量快路径、聚合比较/归约逐字段化、
E1 兜底拆除在 XS 全量上护栏**零告警**，说明这些路径不产生超宽物化——
按 §7 的回退粒度原则不预先实施。护栏（warn 级、含 loc）留在代码里，
任何新设计触发即显形。
