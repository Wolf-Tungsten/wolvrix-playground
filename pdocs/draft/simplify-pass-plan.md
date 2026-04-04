# Simplify Pass 规划（合并 const-fold / redundant-elim / dead-code-elim）

## 目标
- 合并 `const-fold`、`redundant-elim`、`dead-code-elim` 为一个 `simplify` pass。
- 在单个 pass 内部**协同迭代直到不动点**，避免跨 pass 的重复扫描和局部最优。
- **默认保持 4-state 语义**；通过 `-semantics=2state` 允许更激进的 2-state 优化。

## 现有 pass 功能盘点

### const-fold
- 迭代折叠所有**操作数为常量**的表达式（使用 `slang::SVInt`，默认不传播 X）。
- 阶段性流程：
  - 收集并去重 `kConstant`（常量池）
  - 迭代折叠至收敛（上限 `maxIterations`）
  - 简化 slice
  - 删除无用常量
  - 简化部分无符号比较（如 `x >= 0` / `x <= max`）
- 选项：
  - `-max-iter <N>`：迭代上限
  - `-x-fold=<mode>`：X/Z 折叠策略（strict/known/propagate）

### redundant-elim
- 以结构重写与 CSE 为主，清理“临时值”冗余：
  - 直接内联 `assign`（含输出端口 special case）
  - 形如 `concat` 的退化消除
  - `logic_or(a, !a)` -> 常量 1
  - `not(xor)` -> `xnor`
  - CSE（side-effect-free，单结果、临时值）
  - 输出端口常量的符号修复

### dead-code-elim
- 基于 use-count + side-effect 保护的 DCE：
  - 仅保留有副作用 op、端口值、声明符号
  - worklist 删除死 op
  - 清理无用 value
- 受 `keepDeclaredSymbols()` 影响（保持已声明符号）

## 合并后的 simplify pass 规划

### Pass 名称与参数
- 名称：`simplify`
- 选项：
  - `-max-iter <N>`：外层不动点迭代上限（默认 8）
  - `-x-fold=<mode>`：X/Z 折叠策略（4-state 默认 `known`）
  - `-semantics=2state`：启用 2-state 语义（默认 4-state）

### 总体流程（graph 级）
对每个 graph 运行以下流程，直到不动点或达到 `max-iter`：

1. **Const Fold Phase**
   - 复用现有 const-fold 的分阶段逻辑（收集/折叠/slice/死常量/无符号比较）。
   - 默认 4-state；若 `-semantics=2state` 打开，可启用额外 2-state 规则。

2. **Redundant Elim Phase**
   - 保留现有结构化重写与 CSE 逻辑。
   - 由 const-fold 产生的常量/临时值在本阶段被快速内联与合并。

3. **Dead Code Elim Phase**
   - 清理经过前两阶段之后的“悬空值/操作”。
   - 保留端口、声明符号与副作用 op。

4. **收敛判断**
   - 任何阶段发生变更 -> 继续迭代
   - 无变更 -> 不动点结束

### X/Z 折叠策略（-x-fold）
三档语义、互斥清晰（仅在 `-semantics=4state` 下生效）：
- `strict`（默认）：任一操作数含 X/Z => 直接跳过折叠（完全保守）。
- `known`：允许含 X/Z 的输入参与折叠，但**仅当结果不含 X/Z**时替换。
  - 例：`0 & X -> 0`，`1 | X -> 1`。
- `propagate`：允许含 X/Z 的输入折叠，且结果含 X/Z 也可替换。
  - 例：`0 > X -> X`，`1 == X -> X`。

### 2-state 模式范围（-semantics=2state）
- 只影响 const-fold 的“比较/逻辑规则”：
  - 允许将部分“在 2-state 下恒真/恒假”的比较折叠
  - 避免改变其它 pass 的语义（redundant-elim / DCE 维持原逻辑）
- 保持默认 4-state 语义不变，确保可回退与可验证性。
- 优先级规则：`-semantics=2state` **优先级最高**，开启后忽略 `-x-fold`（统一按 2-state 语义执行）。
- 在 `-semantics=4state` 下，`-x-fold` 生效且默认 `known`（中等强度）。

### declaredSymbol 保护要求
- simplify 必须继承现有 DCE/冗余消除对 `declaredSymbols` 的保护语义：
  - `keepDeclaredSymbols()` 打开时，声明符号对应的 value 不允许被删除或替换为无名临时值。
  - 任何替换/内联/折叠步骤都需避免破坏已声明符号的可追踪性与名字稳定性。

### 统计与日志
建议统一输出（与现有 pass 类似）：
- graph 数 / changed graph 数
- 常量折叠次数、CSE 次数、DCE 删除 op/value 数
- 2-state 专用规则触发次数（若开启）

## 落地步骤
1. 新增 `simplify` pass 入口与选项解析。
2. 抽象 const-fold / redundant-elim / dead-code-elim 共享的图遍历与替换工具。
3. 组合为迭代管线，保留每阶段统计与错误处理。
4. 默认 4-state；`-semantics=2state` 显式开启。
5. 回归验证：确保与三 pass 串行执行结果一致或更优。

## 风险与注意事项
- 2-state 优化会改变 X 传播语义，必须通过开关显式开启。
- 三阶段合并后，某些局部重写可能触发更多折叠，需补充回归用例。
