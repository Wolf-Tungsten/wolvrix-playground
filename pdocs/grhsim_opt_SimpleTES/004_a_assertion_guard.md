# 004. A：SystemTask/assertion 成对外层 cold guard

A 是 RWA 链的第三项增量，和 R、W 一起合入 Wolvrix 提交
`16a9f493687a21a5428f1e1327a69834ea60c9f5`。它不是“关闭 assertion”，而是只重排
一个满足严格数据接口条件的相邻代码对。两项操作本身仍可能有日志、报错或终止仿真等
可观察副作用；优化不会删除这些副作用。RWA 是最终落地的三个增量简称：R 是
register-write run 筛选，W 是 MemoryWrite 提示，A 是本篇的 assertion 外层 guard。
[^design][^landing]

## 先理解本篇术语

`SystemTask` 是 HDL 的 `$display`、`$fatal` 等系统任务形成的副作用操作；
`xs_assert_v2` 是 XiangShan 用来报告断言的特定 DPI-C 函数，DPI-C 是
SystemVerilog 调用 C/C++ 的接口。**guard** 是决定一段代码是否执行的布尔条件。
`unlikely(cond)` 不会跳过 `cond`，只向 C++ 编译器提示它通常为假，使编译器有机会
把低概率代码放到高频直线路径之外。

这里的 **return** 是 C 函数返回值，**output** 是 DPI-C 输出参数，**IR result** 是
调用后可供 Wolvrix 图中其他操作读取的结果值。“三者都没有”只说明 `xs_assert_v2`
不向后续数据流提供新值，并不表示该调用没有日志、报错或终止等副作用。

## 做了什么

### 先看总结

A 识别一对严格相邻、共享同一条件和 exact event 的 `SystemTask` 与 `xs_assert_v2`
调用，把它们放进同一个标为 `unlikely` 的外层 guard。内层 assertion 的原条件仍会
再次检查，两项操作的先后顺序和副作用都保留；任何结构或接口条件不满足时仍逐条生成。

| 层面 | 旧生成形式 | 新生成形式 | 目的 / 边界 |
|---|---|---|---|
| 代码形态 | 相邻的 SystemTask 与 assertion 分别带条件逐条生成 | 以 SystemTask 的条件形成 cold 外层，`xs_assert_v2` 嵌套其中并保留自己的内层条件 | 让编译器可将符合门禁的整对代码移出高频直线路径，不删除 assertion 或 SystemTask |
| 配对条件 | 通用 emitter 不利用两项已经相同的 guard/event 关系 | 仅配对同 phase、同条件值、同 exact-event 表达式且严格相邻的两项操作 | 只在生成器能够证明共同触发前提时重排；不按 workload 或变量名选择 |
| 接口与回退 | 各 DPI-C/SystemTask 按通用路径生成 | DPI-C 必须恰为无 return、output、IR result 的 `xs_assert_v2`，并排除特殊旁路等情况 | 保留可观察副作用和数据依赖；任一证明失败就完整维持旧形式 |

**只需记住：A 不是关闭断言，而是对可证明共享触发条件的一对副作用操作做 cold
嵌套。该单项实验的 control 已含 R、W 和后来未落地的 MemoryFill hint F；加入 A 后，
合并两种运行顺序的 SimTop 50k walltime 为 `55,485.00→54,050.50 ms`，减少
`1,434.50 ms`、改善 `2.585383%`。**[^ablation]

### 实现与边界

emitter（把 Wolvrix IR 和 schedule 生成 C++ 仿真源码的代码生成器）只在以下条件
全部成立时嵌套相邻操作：

* 当前项不属于仿真收尾时单独执行的 final 过程，也没有“只在初次 eval 执行”或
  “已经完成”状态；下一项紧邻且是同一 phase 中的 DPI-C 调用。compute phase 计算
  组合值，commit phase 执行写状态或其他副作用。两项之间也不能插入生成宽位拼接
  表达式时必须预先声明的 concat-prefix 临时值；
* 两项使用同一个条件值，生成器还原出的 exact-event 表达式也完全相同；exact event
  表示可以明确写成 posedge、negedge 或任意边沿条件的触发事件；
* DPI-C 目标恰好是 `xs_assert_v2`，没有 return、output 或 IR result，也不是
  register-to-memory intent 的特殊旁路操作；后者会把寄存器写入意图转交给存储器
  更新路径，因此保守排除。[^source]

满足这些证明后，生成形态可简化理解为：

```cpp
if (unlikely(system_task_cond && exact_event)) {
    run_system_task();
    if (assert_cond && exact_event) { // assert_cond 与外层条件来自同一 IR 值，仍独立复核
        xs_assert_v2(...);
    }
}
```

如果事件已经由更外层的 commit dispatch 检查，实际生成代码会省去相应的重复事件
表达式。关键是 `xs_assert_v2` 自己的条件复核仍在，所以这不是把两个判断机械合并成
一次。若任一证明不成立，就保持旧的逐条生成；assertion 的触发语义、SystemTask
顺序和 DPI-C 可观察副作用都不改变。[^source]

## 为什么这样做

这类检查通常位于低概率错误路径，但逐条放在热 schedule（高频执行的调度代码）中会
让编译器把相关代码和主计算混在一起。外层 cold guard 复用两项操作已经证明相同的
触发前提，把整对低概率代码移出正常直线路径；进入外层后仍执行原有内部检查。门禁
依赖相邻结构、同条件/同事件和数据接口证明，而不是 SimTop 的名字或固定 workload。
[^design]

## 收益（SimTop 50k walltime）

A 的单项消融是 direct `RWF→RWFA`。字母表示累计启用的机制：R 是 register
cold-layout refinement，W 是 MemoryWrite hint，F 是当时仍在候选中的独立
`MemoryFillPort` cold hint，A 是本篇机制。因此 control `RWF` 包含 R、W 和 F，
candidate `RWFA` 只比它多 A；direct 表示两侧只相差当前被测机制，而不是单纯在 RW
上测量。ABBA 表示按 control-candidate-candidate-control 运行，BAAB 是反向顺序；
pooled 数值合并两个顺序的有效样本后分别取均值。绝对值是 SimTop 50k 日志中的
`Host time spent` walltime：[^ablation]

| 对比 | control（ms） | candidate（ms） | 减少（ms） | 相对改善 | ABBA / BAAB |
|---|---:|---:|---:|---:|---:|
| `RWF→RWFA` | 55,485.00 | 54,050.50 | 1,434.50 | **2.585383%** | 2.380091% / 2.789407% |

F 的重复收益不稳定，最终没有合入。为了验证去掉 F 后的实际默认组合，随后直接测试
no-F 的 `B→RWA`；B 是落地前的 exact-event baseline，RWA 是同时启用最终三项。其
pooled 结果为
`60,583.50→53,992.75 ms`，减少 `6,590.75 ms`、改善 `10.878787%`；随后 native
landing（实际合入通用默认源码）复测的完整 RWA endpoint 为
`60,881.50→54,088.00 ms`，改善 `11.158562%`。这些是不同测量窗口和 baseline 的
端点，不应当与 A 的 `2.585383%` 单项数字相加。[^landing]

## 落地状态与边界

A 与 R/W 同提交进入通用 C++ emitter 默认路径，Python 流程继承；没有为 SimTop 单独
开启。后续四项热路径中的 #005 是更通用的 standalone（不要求严格相邻配对）
assertion/SystemTask hint，它扩展覆盖面但不等同于本篇严格的“成对外层 guard”。
[^landing][^later]

### 数据来源（尾注）

[^design]: [`TNO0183`：A 的结构定义和 direct ablation 设计](../grhsim_opt_thj/TNO0183_simpletes_v2_direct_ablation_final_attribution_and_retention_decision_20260727.md)。
[^ablation]: [`TNO0183`：RWF→RWFA 绝对 walltime、ABBA/BAAB 和 PMU](../grhsim_opt_thj/TNO0183_simpletes_v2_direct_ablation_final_attribution_and_retention_decision_20260727.md)。
[^landing]: [`TNO0185`：RWA endpoint/f-repeat](../grhsim_opt_thj/TNO0185_simpletes_v2_f_repeat_and_rwa_endpoint_decision_20260727.md) 与 [`TNO0188`：native landing/default](../grhsim_opt_thj/TNO0188_rwa_landing_native_50k_performance_and_default_decision_20260727.md)。
[^later]: [README 总目录](README.md)中的“四个正收益热路径”阶段及 [005](005_cold_systemtask_assert_hints.md)。
[^source]: Wolvrix `16a9f493...` 的 `lib/emit/grhsim_cpp.cpp` 中 `isNestableAssertionSideEffectPair` 和 SystemTask/DPIC nested guard；历史源码对应约 17734–17770、22079–22329，可用 `git show 16a9f493687a21a5428f1e1327a69834ea60c9f5:lib/emit/grhsim_cpp.cpp` 复核。
