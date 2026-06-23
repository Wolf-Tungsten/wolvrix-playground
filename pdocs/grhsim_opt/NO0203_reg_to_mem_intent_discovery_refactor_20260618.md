# NO0203 Reg-to-Mem Intent Discovery Refactor

记录日期：2026-06-18

## 背景

当前 `reg-to-mem` 已经能在完整 XiangShan 上生效：严格匹配成功的 group 会在 transform 阶段重写成真正的 `kMemory`，严格匹配失败的 group 会打上 `regToMem.intent.*` attrs，并由 `grhsim-cpp` emitter 生成 `state_reg_to_mem_rtm_intent_*` 数组存储与低成本 slice 访问。

问题在于 intent 的发现范围仍然被 true merge 候选形态限制住了。现实现先发现“有希望成为 true group”的读侧 anchor，再把没有通过 true merge 写侧/闭包条件的候选降级成 intent group。这样会漏掉大量本来适合 emit 优化、但不满足 true merge 闭包条件的 `regread -> concat -> slice` 模式。

期望的新行为：

- 只要能匹配 `kRegisterReadPort -> kConcat -> kSliceArray/kSliceDynamic` 的数组读取模式，就先形成 intent group。
- intent group 不要求读取闭包满足 true merge 的唯一用户 / 全读口 ownership 条件。
- emit 阶段基于 intent group 优化物理数据布局，把这一组 scalar register 的 storage 改成 array-like storage。
- 对 intent slice，把原本需要构造 packed concat 再 slice 的路径改成低成本数组 row 访问。
- 那些额外严格满足 true group 条件的候选，仍然在 `reg-to-mem` 阶段直接 rewrite 成真正的 `kMemory` / `kMemoryReadPort` / `kMemoryWritePort` / 可选 `kMemoryFillPort`。

## 当前实现事实

实现入口在 `../../wolvrix/lib/transform/reg_to_mem.cpp`。

`RegToMemPass::run()` 的主流程是：

1. `buildValueUseIndex()`
2. `discoverAnchors()`
3. `groupAnchors()`
4. 如果启用 true merge，则构建 `readsByReg` / `writesByReg`
5. 对每个 group 调 `matchTrueMerge()`
6. true rewrite 成功则跳过 intent
7. true rewrite 失败或 `enableTrueMerge=false` 时，才调用 `annotateGroup()`

也就是说，当前 intent group 的输入集合完全等于 `discoverAnchors()` 发现到的 group，再减去已经 true rewrite 的 group。它不是独立的宽松发现路径。

### Anchor 发现过窄

`matchCommonConcatAnchor()` 当前做了合理的读侧形态检查：

- slice 的 `oper[0]` 必须由 `kConcat` 定义。
- `kConcat` 的每个 operand 必须由 `kRegisterReadPort` 定义。
- 每个 read port 的 `regSymbol` 必须指向 `kRegister`。
- register read result 宽度、signedness、element width 必须一致。
- `kSliceArray.sliceWidth` 或规范化后的 `kSliceDynamic.sliceWidth` 必须等于 element width。

但它还提前要求：

- `kConcat` result 只能被当前 slice 使用。
- 每个 `kRegisterReadPort` result 只能被这个 concat 使用。

这两个 `hasOnlyUser()` 检查本质上是 true merge 的读侧闭包约束，不应该用于宽松 intent discovery。它们会漏掉：

- 同一个 packed concat 同时被多个 slice 使用。
- 同一个 register read 同时供 concat 和其它普通逻辑使用。
- 同一组 register 有多个读视图，但中间 read/concat 节点存在共享。
- 读侧数组选择只是某个更大组合表达式的一部分，无法满足“闭包唯一输出”。

这些情况不适合在 transform 阶段删除 register read / concat / slice，因此不应 true rewrite；但 emit 阶段仍然可以把参与的 register storage 映射到一个数组，并把能识别的 slice 读降成 row access。

### True merge 条件仍然必要

`trueReadClosureEligible()` 会检查：

- 每个 anchor 的 row order / element shape 与 group 一致。
- 每个 anchor 的 concat 和 slice 不共享。
- 每个 anchor 的 read op 不共享。
- concat result 只被该 anchor slice 使用。
- read result 只被该 anchor concat 使用。
- 目标 register 不存在候选 read set 之外的其它 `kRegisterReadPort`。

这些条件对 true rewrite 是必要的，因为 true merge 会删除原 `kRegister`、`kRegisterReadPort`、`kConcat`、`kSlice*` 和原写口。只要读侧还有外部用户或共享中间节点，直接 rewrite 就有破坏语义或引入环的风险。

因此重构目标不是放宽 true merge，而是把这些闭包检查从 intent discovery 中移走，只保留在 true eligibility 中。

### Emit 已有基础

`../../wolvrix/lib/emit/grhsim_cpp.cpp` 已经有 intent 消费路径：

- `StateDecl::regToMemIntentStorage` 标记 register state 是否落到 intent array。
- `RegToMemIntentStorageDecl` 描述 group 的 array-like storage。
- `stateRef()` 对 intent register 返回 `state_reg_to_mem_<group>_[row]`。
- state discovery 会读取 `regToMem.intent.group/row/elementWidth/elementCount`，并为同 group 建一个 `std::array` storage。
- `regToMemIntentSliceExpr()` 能把带 intent attr 的 `kSliceArray` / `kSliceDynamic` emit 成数组 row access。
- `resolvedRegToMemIntentIndexExpr()` 已处理 source clone / index materialization 断链问题，优先把 index 解析成稳定表达式。

下一阶段重点不是从零实现 emitter，而是扩展 pass 侧 metadata 覆盖范围，并补齐 emitter 在“宽松 intent”下的完整性校验与回退规则。

## 新设计

### 两套候选语义

重构后需要显式区分：

`IntentCandidate`

- 只证明存在可优化的数组读形态。
- 不删除 IR 节点。
- 不要求 read/concat/slice 闭包唯一用户。
- 不要求目标 register 的所有 read 都被本 group 覆盖。
- 不要求写侧可合并。

`TrueMergeCandidate`

- 在 `IntentCandidate` 的基础上增加严格读闭包、完整 register read ownership、写侧 family、reset/fill、init 转换等条件。
- 成功后立即 rewrite 成真正 `kMemory`。
- 失败时不影响该 group 作为 intent group 继续存在。

新主流程：

```text
discoverIntentAnchors()
groupIntentAnchors()
for each intent group:
    if enableTrueMerge and trueEligibility(group):
        rewriteTrueMerge(group)
    else if enableIntent:
        annotateIntentGroup(group)
```

关键区别是 `discoverIntentAnchors()` 不再使用 true closure 的唯一用户约束。

### Intent discovery 规则

intent anchor 的基本模式：

```text
r_i      = kRegisterReadPort(reg_i)
packed   = kConcat(..., r_i, ...)
selected = kSliceArray(packed, index)
```

或：

```text
selected = kSliceDynamic(packed, start)
start    = index * elementWidth
```

基础约束：

- slice op 必须是 `kSliceArray` 或可规范化的 `kSliceDynamic`。
- slice 的 packed operand 必须由 `kConcat` 定义。
- concat operands 必须全部来自 `kRegisterReadPort`。
- 每个 read port 的 `regSymbol` 必须能找到 `kRegister`。
- 所有 row 的 value type 为 `Logic`，位宽相同，signedness 相同。
- `sliceWidth == elementWidth`。
- `concatWidth == elementWidth * elementCount`。
- `elementCount >= minElementCount`。
- concat operand 顺序定义 row 顺序，必须记录 `operand index -> row -> regSymbol`。

不再要求：

- concat result 只有一个 slice user。
- register read result 只有一个 concat user。
- register 的所有 read port 都属于该 group。
- 不同 anchor 的 read op / concat op 完全不共享。

### Grouping 与 ownership

当前 `groupAnchors()` 用 `rowKey(regSymbols)` 分组。宽松 intent 下仍可沿用“同一 row order 的 anchors 合成同 group”的原则，但需要定义冲突：

- 同一组 register 可能存在多个不同 row order 的 concat 视图。不同 row order 不能放入同一个 intent group，否则 row access 会读错。
- 同一 register 不能同时归属于多个被 emitter 接受的 intent storage group。否则一个 scalar state 会被映射到两份 array storage，产生双写一致性问题。

建议增加：

```text
regSymbol -> intentGroup
```

首版保守规则：

- row order 相同：合并 anchors。
- row order 不同：相关冲突 group 不打 intent attr，输出 profile 计数。

### Attr schema

现有 `regToMem.intent.*` 可继续作为 v1 基础，但宽松 intent 建议输出 `version=2`，用于区分 discovery 口径。

在每个 target register 上记录 emitter 分配 state layout 所需信息：

```text
regToMem.intent.version = 2
regToMem.intent.group = group
regToMem.intent.role = "register"
regToMem.intent.mode = "array-index"
regToMem.intent.row = row
regToMem.intent.elementWidth = W
regToMem.intent.elementCount = N
```

在每个 slice anchor 上记录快路径所需信息：

```text
regToMem.intent.version = 2
regToMem.intent.group = group
regToMem.intent.role = "slice"
regToMem.intent.mode = "array-index"
regToMem.intent.sliceKind = "slice-array" | "slice-dynamic"
regToMem.intent.elementWidth = W
regToMem.intent.elementCount = N
```

在每个 concat anchor 上记录 row order：

```text
regToMem.intent.version = 2
regToMem.intent.group = group
regToMem.intent.role = "concat"
regToMem.intent.regSymbols = [row0Reg, row1Reg, ...]
regToMem.intent.operandRows = [...]
```

在 participating read op 上记录：

```text
regToMem.intent.version = 2
regToMem.intent.group = group
regToMem.intent.role = "read"
regToMem.intent.row = row
```

Emitter 可以继续接受 `version=1`，但新 pass 产物建议输出 `version=2`。

## Emit 语义

对于被接受的 intent group，emitter 应保持：

- 不为目标 register 生成独立 scalar state storage。
- 为 group 生成一个 array-like storage。
- 所有目标 register 的普通 read/write 都通过 `stateRef()` 映射到该 array 的 row。
- intent slice 直接从 array row 读，不物化 concat。
- 没被标注的普通 concat 用户仍按普通表达式 emit，但它读取的 register read 也会通过 row storage 取值。

这样即使 concat 有多个用户或 read 有额外用户，语义也能保持一致：普通路径仍可构造 packed concat，只是 concat operands 来自 array rows；被标注的 slice 快路径跳过 packed concat，直接 array index。

关键约束是一份物理 state。只要 register storage 映射到 intent array，普通 read、普通 write、intent slice 都访问同一份数据，不维护 scalar mirror。

## 与 true merge 的关系

true merge 仍然应复用 intent discovery 的结果，但必须额外检查：

- anchor 内部 read/concat/slice 不共享。
- concat result 只被该 anchor slice 使用。
- read result 只被该 anchor concat 使用。
- 目标 register 的所有 read port 都属于该 true group。
- 所有目标 register 的写口能匹配同一 indexed write family。
- reset/fill/init 可等价转换。
- rewrite 后能通过本地图合法性检查。

公式化地说：

```text
IntentCandidate = pattern(regread, concat, slice)
TrueMergeCandidate = IntentCandidate + closure + write-family + init/reset legality
```

`trueReadClosureEligible()` 当前的位置和语义可以保留，但调用对象应来自宽松 intent group。

## 当前缺口

1. Discovery 把 true 闭包条件提前了。

`matchCommonConcatAnchor()` 里的 concat/read `hasOnlyUser()` 检查会直接阻止宽松 intent 候选进入 pipeline。应拆成 `matchIntentConcatAnchor()` 和 `matchTrueAnchorClosure()`。

2. Intent 是 true 失败后的副产物。

当前 `intent_groups` 实际含义是“通过窄 discovery、但 true merge 失败的 groups”。重构后统计应拆成 `intent_candidate_groups`、`true_groups`、`intent_annotated_groups`、`intent_conflict_groups`、`intent_rejected_groups`。

3. 多视图 / 多 row order 冲突没有定义。

宽松 discovery 后，同一 register 进入多个 row order group 的概率会升高。首版应通过 `regSymbol -> group` ownership 表保守拒绝冲突 group。

4. Attr version 与完整性诊断不足。

建议引入 `version=2`，并在 pass/emitter 侧明确诊断 missing rows、duplicate row、width/count mismatch、register assigned to multiple intent groups。

5. Emitter 回退策略需要重新审视。

当前 emitter 对 register 上不完整 intent attr 会 fail-fast。宽松 intent 下更理想的是 group preflight：通过的 group 才改 state layout，失败 group 整组回退普通 scalar emit。首版也可以继续 fail-fast，但 pass 必须保证不会给冲突组打 attr。

6. 单测缺少宽松 intent 正例。

需要补：

- concat result 有两个 slice users，两个 slice 都应成为同一 intent group。
- register read result 除 concat 外还有普通 user，仍应形成 intent group。
- 同一 group 共享 concat/read，中间节点不满足 true closure，但 intent 应保留。
- 同一 row order 多 anchor 合并。
- row order 不一致时拒绝 intent storage 或拆组回退。

7. 集成指标需要重新定义。

当前完整 XiangShan 日志中的 `true_groups=280 intent_groups=262` 只是窄 discovery 统计。重构后 intent group 数量理论上应上升，但 true group 数量不一定变化。

建议验收指标：

- `intent_candidate_groups` 大于旧 `groups=542`，或能解释新增/拒绝分布。
- `true_groups` 与旧行为保持相近，不因为宽松 discovery 误 rewrite。
- `state_reg_to_mem_rtm_intent_*` 覆盖 rows 增加。
- 生成 C++ 中被标注 slice 不再出现对应 packed concat materialization。
- CoreMark 50k difftest 跑满 cycle limit。

## 实施顺序

1. 重构 pass 内部数据结构：`AnchorCandidate` 拆为 intent anchor + true closure metadata；`discoverAnchors()` 改为宽松 intent discovery；唯一用户检查移动到 `trueReadClosureEligible()`。
2. 增加 intent ownership / conflict pass：按 row order group anchors，检查 register 是否被多个 group 竞争，冲突 group 不打 attr 并输出 profile。
3. 保持 true merge 行为不变：true eligibility 继续调用闭包、写侧、reset/fill/init 检查；true rewrite 成功后不打 intent attr；true rewrite 失败才对该宽松 group 打 intent attr。
4. 补 emitter preflight 或至少补完整性诊断：确认宽松 intent 下普通 read/write 都通过 array row storage，未被 slice 快路径消费的 concat 仍能普通 emit，不能接受的 group 不会生成半套 state。
5. 补测试：transform 单测验证宽松 discovery，emit 单测验证共享 concat / extra read user 下的数组 storage 与 slice 快路径，完整 XiangShan coremark 50k 作为最终 correctness gate。

## 非目标

- 不放宽 true merge 的写侧条件。
- 不在 transform 阶段删除不满足 true closure 的 read/concat/slice。
- 不允许同一 register 同时生成 scalar storage 和 intent array storage。
- 不用名称启发匹配 register family。
- 不把普通 concat 用户强行改写；只有被明确标注的 slice 走 row access 快路径。

## 结论

这次重构的核心是把 `intent` 从“true merge 失败后的标记”提升为独立的一等候选层。`reg-to-mem` pass 负责发现宽松的 `regread-concat-slice` 数组读意图，并只在严格合法时执行 true memory rewrite；`grhsim-cpp` emitter 负责把未 true rewrite 的 intent group 落成 array-like state layout，并对被标注的 slice 发射低成本 row access。

当前实现已经有 true rewrite 和 intent emit 的大部分基础，主要缺口集中在 pass 侧 discovery 过窄、group ownership 冲突未定义、统计口径和测试覆盖不足。
