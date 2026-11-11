# F23.3：AliasAnalysis、PatternDetect 和 CommonExpr

F23.3 在 `grh-to-grhsim` 之前继续对齐 GSIM 的普通 GRH 优化边界：

```text
constant-analysis
→ dead-code-elim
→ alias-analysis
→ pattern-detect
→ common-expr
→ dead-code-elim
→ grh-to-grhsim
```

三个 pass 都作用于未分区、未转换的普通 GRH，默认不把
`declaredSymbols` 当作保活根，也不调用 `simplify` 或隐式 DCE。每个 pass
结束时留下的死操作和值由流程中的下一次显式 `dead-code-elim` 统一回收，
因此可以分别观察其图变化和耗时。

`alias-analysis` 当前实现 GSIM 别名传播的安全 GRH 子集。它识别 scalar
Logic、类型完全一致且无副作用的 `kAssign`，以及覆盖源值完整宽度的
`kSliceStatic`，把所有用户重定向到源值，同时把 FIRRTL node roots、
SemanticTree 和 origin provenance 合并到源值。别名 operation/value 行保留
到显式 DCE；数组、aggregate、类型不一致的 view 和 effectful operation
保持不变。

`pattern-detect` 当前覆盖 GSIM Pattern 2 的普通 GRH 形式：

```text
eq(concat(high, low), constant)
```

它把原地改写为两个窄 equality 的按位 `and`，改写结果和生成的比较继承
原操作的 source location、SemanticTree 及 FIRRTL node metadata；新常量继承
相关 SemanticTree/source identity。原 concat 行仍留在图中，由后续显式 DCE
回收。

`common-expr` 对纯 scalar Logic expression tree 计算包含操作种类、完整类型、
非 provenance 属性和有序 child canonical ID 的浅层结构 key。完整 key 精确
intern，hash 只用于索引；显式后序 stack 避免共享 DAG 的字符串指数展开和深链
调用栈溢出，double 属性按完整 bit pattern 编码。常量、端口、aggregate 和
effectful operation 不参与候选；声明 symbol 不会自动成为保活根。重复次数达到 5、结果宽度大于
256，或某个重复结果有多个不同 consumer operation 时，共享一个 representative，并合并
SemanticTree、origin 和 node metadata；重复 operation/value 行保留到最后的
显式 DCE。声明 symbol 不会成为保活根，但不阻止已证明的纯表达式共享。
Fanout 在任何替换前冻结，单一 consumer 重复引用同一值只计一个用户，
避免把 `add(x, x)` 的两个 operand use 误计为 GSIM 的两个 downstream node。

验证使用：

```sh
source env.sh && make test_grhsim_transforms SKIP_PY_INSTALL=1
source env.sh && make py_install
```

前一命令中的四个 CTest 均通过；流程顺序测试可使用
`make test_grhsim_flow SKIP_PY_INSTALL=1`，其中当前仓库已有 FIRRTL node
metadata 和 emitter 配置断言失败与 F23 pass 无关。按当前任务要求没有运行
XiangShan 全图。
