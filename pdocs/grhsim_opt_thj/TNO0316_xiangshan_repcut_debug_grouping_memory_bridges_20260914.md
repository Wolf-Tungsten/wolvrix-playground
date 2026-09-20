# TNO0316: XiangShan RepCut debug grouping and memory bridges

日期：2026-09-14

状态：`READ-ONLY CAUSAL AUDIT; NO REMOVAL ABLATION OR RUNTIME CLAIM`。

## 1. 范围与前提澄清

承接 [TNO0305](./TNO0305_xiangshan_repcut_giant_asc_semantics_and_growth_20260914.md)
与 [TNO0315](./TNO0315_xiangshan_repcut_asc_split_ablation_result_20260914.md)，用户追问
为什么 debug/性能计数器集中在大 ASC，以及是否由 Chisel 写法造成。本轮只读分析
Scala、原始 GRH、已冻结 ASC membership，不修改 RTL、生产实现、分区或仿真配置。

首先不是“全部 debug/perf 都在 ASC4”。由 O 臂 `state_sink_to_asc.tsv` 统计：

| 对象 | 全图端点 | 分布 ASC 数 | ASC4 内端点 |
| --- | ---: | ---: | ---: |
| `logEndpoint$...` 寄存器写 | 30,936 | 28,538 | 2,384 |
| SystemTask | 7,236 | 6,266 | 971 |

同一 logEndpoint 内多数寄存器写仍分属其他 ASC；ASC4 的 2,384 个只占该 endpoint
寄存器写的 7.706%。相同模块、时钟、clean/dump 或 logEnable 不是共置规则。

## 2. 特定 Chisel 工具库写法的作用

[`LogUtils.scala`](../../testcase/xiangshan/utility/src/main/scala/utility/LogUtils.scala)
105–110 行通过跨层级 tap 获取日志条件/参数，208 行调用延迟登记的统计生成函数，
因此统计寄存器集中生成在 LogPerfEndpoint 中。209–222 行按条件归组；198–203 行每
1,000 条日志拼成一条 printf。源码注释明确其目的是减少 system task、改善线程调度。
这属于本工程日志工具库的策略，不是 Chisel 语言强制集中所有计数器。

更关键的是
[`PerfCounterUtils.scala`](../../testcase/xiangshan/utility/src/main/scala/utility/PerfCounterUtils.scala)
74–79 行：

```scala
next_counter := counter + perfCnt
counter := Mux(perfClean, 0.U, next_counter)
XSPerfPrint(curMod)(perfDump, p"$perfName, $next_counter\n")
```

打印的是含本拍事件的 next 值，而不是只有历史累计值的寄存器输出；若 perfCnt 来自
memory 的组合读，printf 参数就有直接组合 memory 依赖。两路原本不同事件被同一 printf
观察，便给分区增加跨模块的连接。对比同文件 225–229、255–262 行，histogram 输出当前
sum/bin counter，其打印数据路径在寄存器读处截止；writer 自己仍可因本拍事件进入 giant。

不能简化为“printf 读到了很多 counter，就把所有 counter writer 合并”。寄存器读是
RepCut 的 source，读当前值并不会自动穿过该寄存器回溯其 writer。

## 3. RepCut 如何将这些连接变成不可拆约束

[`repcut.cpp`](../../wolvrix/lib/transform/repcut.cpp)：

- 265–305：每个 SystemTask/DpicCall 是单独的 effect sink，而非统一合并所有打印。
- 320–330、399–415：常量、RegisterRead、LatchRead、输入端口是回溯截断点。
- 382、1700–1734：MemoryRead 可继续回溯，并收集 memSymbol。
- 1784–1789：回溯 sink 的所有输入，不按运行时打印是否触发进行条件剪枝。
- 2103–2128：同一状态 symbol 的多个写口先共置。
- 2161–2176：sink 与其依赖的每块 memory 的写端点合并；传递闭包形成 ASC。

因此，memory A 的事件进入 counterA.next，memory B 的事件进入 counterB.next，两者又
作为同一 printf 的参数时，该 printf 要与 A/B 的 memory writers 共置。counterA/B 的
writer 自身也依赖同一事件，因而通过这些 memory 加入该组件。并不是源模块边界直接决定。

BusPerfMonitor 的 valid/timeStamp/reqType 表也不是因为同属 Vec 就被强制共置：
[`BusPerfMonitor.scala`](../../testcase/xiangshan/src/main/scala/top/BusPerfMonitor.scala)
119、126–147 行的动态索引写和检查依赖本拍总线请求/响应；如果这些信号来自 memory
路径，多个字段 writer 会绑定相同 memory 组件。

## 4. 五个实际 printf 的回溯结果

新增只读脚本 `build/asc_split_20260914/audit_debug_bridges.py`。使用 frozen snapshot 的
piece→ASC 与 node→operation 映射恢复 ASC4 的 491,444 个原始 operation；额外识别全图
source 结果，在寄存器/常量处停止。完整输入扫描 SHA-256 核验为
`82a29e6e2f715c18ffd61ab0106ed5abb6d0fbb6843eea58d8782eb3d30994ba`。
未解析到的非 source/非允许图输入会触发失败，而不是静默省略依赖。

| SystemTask symbol | LogPerfEndpoint.sv 行 | GRH operand 数 | 反向可达 memory symbol |
| --- | ---: | ---: | ---: |
| `_op_10988239` | 64,817 | 2,004 | 21 |
| `_op_10988600` | 69,669 | 2,004 | 10 |
| `_op_10988822` | 70,346 | 2,004 | 4 |
| `_op_10988840` | 70,869 | 2,004 | 21 |
| `_op_10988914` | 71,640 | 2,004 | 31 |

五条合计去重为 **85 个 memory symbol**，它们的 writer 全部在 ASC4；每个 memory 的
完整路径与源位置保存于 `build/asc_split_20260914/debug_bridges_v1.json`。
2,004 是 GRH operand 数，包含条件/时钟/描述符等，不应称为 2,004 个独立计数器。

具体见证：最后一条 printf 同时观察四个 L2 slice 的
`_toTLBundleD_valid_isKeywordNext_T{,_2,_4,_6}`。各自沿当拍 perfCnt 追溯到
`inner_l2cache$slices_{0,1,2,3}$grantBuf$grantQueue$ram_ext$Memory`。
RTL 39447、39732、40017 行可见 counter+event；路径不穿过寄存器写。
这是批量打印包含跨 bank memory 依赖的直接证据，不只是对 Scala 写法的推断。

85 是五条 printf 当前回溯的 memory 集合大小，**不是新增 union 数，也不是移除 printf
后必定分开的 memory 数**。这些 memory 还可能由功能逻辑、其他断言或数据路径连接；
五条打印之间也不全有直接 memory 重叠，整个 429-memory giant 仍有其他桥。

## 5. 判断与后续方向

当前证据支持：特定 Chisel 日志工具库的“同条件大批量 printf + 打印 next_counter”
确实制造了宽组合观测节点；RepCut 的 memory 共置规则将其升级为不可拆约束。
不是 Chisel 写错，也不是所有 debug 都被无条件打包到一个 ASC。

若下一步授权改动，优先做保留打印内容/触发时刻的分组细化消融，再独立评估观察值的
寄存器边界。直接改成打印旧 counter 会改变最后一拍统计口径，不能当作无语义变化。
拆开 printf 也需定义输出顺序，避免多线程交错。运行时静音不能删除静态依赖；按类型
审计性能打印、断言和必要仿真 DPI，不能一并移除。当前未进行移除/拆分消融，未宣称
能够拆开 ASC 或提高 Host 性能。
