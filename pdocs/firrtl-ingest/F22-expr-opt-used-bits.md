# F22：GrhSIM ExprOpt/UsedBits 与 GSIM 对齐

F22 将 GSIM 首次 DCE 后的两个阶段接入 GrhSIM 流程，DCE 保持为外部可见的独立
pass：

```text
dead-code-elim → expr-opt → used-bits → grh-to-grhsim → ...
```

`expr-opt` 是独立的表达式树清理 pass，直接对应外部 DCE 后的 GSIM
`ExprOpt`，覆盖普通 GRH 上的同臂 `kMux`；两个独立但结构等价的分支会
递归合并 SemanticTree 身份。`used-bits` 复用 GrhSIM 的反向位需求
分析和状态收窄，不隐藏 DCE。两个 pass 都要求转换前的 unpartitioned
ordinary GRH，并通过 `-top=<graph>` 选择顶层图。

两者默认不把 `declaredSymbols` 或 generate-group 成员作为保活根，和 GSIM
Node 的可达性语义一致；端口、状态读写、memory 读口和 effectful 操作仍由
GRH root 规则保活。FIRRTL node 的来源身份存放在 SemanticTree，而不是
作为 liveness root。

别名和窄化重建路径都会转移对应 operation/value SemanticIds；两个 pass
不执行 DCE，也不回收 SemanticTree。死锥和语义树清理由外部 DCE 负责。

默认生产流程在转换前显式执行一次 DCE，再执行这两个阶段；DCE 是调用者可见的
独立 pass。F22 本身不添加或调用 `simplify`。GSIM 的冻结 XiangShan
参考日志中，首次 `ExprOpt` 为约 25.8 秒，
`UsedBits` 为约 9.0 秒。GrhSIM 的全图基准通过
`make benchmark_f22_xiangshan SKIP_PY_INSTALL=1` 运行，输入默认为
`ptmp/firrtl-ingest/F21/current-lowering/post-dce.json`；它只执行
`expr-opt → used-bits`，记录独立 wall/CPU/RSS、操作和值
数量、总位宽及 SemanticTree 统计，并检查两阶段没有减少 operation/value 行。
2026-11-10 在 XiangShan 全图 `current-lowering/post-dce.json` 的单轮结果为：

| 阶段 | wall time | 结果 |
| --- | ---: | --- |
| ExprOpt | 2.059 s | 11,142 个同臂 MUX；16,434,183 个 operation、15,916,853 个 value 行保持不变 |
| UsedBits | 15.312 s | operation/value 增至 16,534,676/16,017,346（新增窄化节点）；总位宽 335,793,233 → 329,531,694 |
| F22 合计 | 17.371 s | 两个 pass 均未删除 operation/value 行；SemanticTree 校验通过；报告见 `ptmp/firrtl-ingest/F22/xiangshan-run3/summary.json` |

该输入已由外部 `dead-code-elim` 生成；本轮没有运行 `dead-code-elim` 或任何
`simplify`。作为参照，GSIM 冻结日志中对应首次 ExprOpt/UsedBits 约为
25.8/9.0 s，具体机器和构建配置不同，不能直接视为等价性能结论。
已有
`grhsim-transform-tests` 覆盖同臂 mux 的语义转移、声明符号默认不保活以及
状态位宽收窄；端到端 Python flow 会在 converted checkpoint 之前执行这两个
阶段。
