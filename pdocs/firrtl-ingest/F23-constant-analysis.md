# F23.2：普通 GRH ConstantAnalysis

`constant-analysis` 是 F23 在 `grh-to-grhsim` 之前新增的独立 GRH pass，对应
GSIM 的 `ConstantAnalysis` 阶段。它接在 `split-nodes` 后的显式 DCE 之后，
并把结果交给下一次显式 DCE：

```text
dead-code-elim
→ expr-opt → used-bits → split-nodes
→ dead-code-elim
→ constant-analysis
→ dead-code-elim
→ grh-to-grhsim
```

Pass 在一个未分区、未转换的普通 GRH 图上按生产者拓扑序访问操作。对于
`kConstant` 操作数组成的纯逻辑表达式，它复用 GRH 的逻辑求值器，将原操作
原位改写为 `kConstant`，保持原 `OperationId`、结果 `ValueId`、符号和
SemanticTree/source metadata。支持算术、比较、逻辑、移位、MUX、concat、
replicate、静态/动态 slice 和数组构造；共享 evaluator 支持的 pure
`kSystemFunction`（例如 `clog2`）也可折叠，普通 GRH 的 effectful/sampled
system function 保持不折叠。除零和模零也保持不折叠。

ConstantAnalysis 的边界是常量传播。它不调用 DCE，不删除死操作，不执行
`simplify`，也不回收 SemanticTree。默认 `declaredSymbols` 不作为保活根；
端口和有副作用操作仍由 GRH root 规则保留。后续 DCE 由流程显式执行，因而
可以单独测量本 pass 的耗时和图变化。

验证覆盖纯 Add、常量条件 MUX、动态 MUX 保留、声明死锥保持以及
`validateDeclaredSymbols()`；使用：

```sh
source env.sh && make test_grhsim_transforms SKIP_PY_INSTALL=1
```

该目标中的 4 个 CTest 均通过。全图 XiangShan 测试按当前任务要求暂不执行。
