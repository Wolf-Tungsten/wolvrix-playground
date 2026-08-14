# 005. 通用 cold SystemTask / standalone assertion hints

这是 `fd12d83f5150cc98540ed3e8f2af3b79f8054da0` 中四项正收益热路径改动的第一项。
它发生在 RWA 之后，和 [004](004_a_assertion_guard.md) 的严格成对 outer guard
不同：本项扩大了可以安全标成冷门的**通用** SystemTask/assertion 形状。[^design][^landing]

## 做了什么

### 先看总结

本项把“低概率副作用代码应放到冷区”的原则从 004 的严格相邻配对，扩展到可以单独
证明安全的 SystemTask 和 assertion。它不会关闭任务或断言，只把原 guard 标成
`unlikely`，让 C++ 编译器有机会把很少执行的代码移出热路径。

| 对象 | 旧生成形式 | 新生成形式 | 目的 / 边界 |
|---|---|---|---|
| 常规 SystemTask | 带条件的 task 使用普通 guard | 非 `final`、进入常规 schedule 的完整 guard 使用 `unlikely` | 改善低概率副作用代码的布局；`final` task 仍走原 finalize 路径 |
| standalone `xs_assert_v2` | assertion 使用普通 guard | 无 return、output 和 IR result 时将 guard 标冷 | 保留错误报告和其他副作用；数据接口不满足时不应用 |
| 与 004 的关系 | 004 只处理严格相邻且共享条件/事件的一对操作 | 本项可处理单独出现的合资格操作 | 扩大覆盖面，但不替代 004 的成对嵌套证明 |

**只需记住：005 是“单个低概率副作用操作的 cold hint”。在完整六项候选中先去掉本项、
再恢复本项，合并两种运行顺序后的 walltime 从 `52,365.25` 降到 `51,693.75 ms`，减少
`671.50 ms`、边际改善 `1.282339%`；最终落地四项的整体收益另有独立对比。**[^ablation]

### 实现与边界

`SystemTask` 是 HDL 中 `$display`、`$fatal` 等系统任务形成的副作用操作；
`xs_assert_v2` 是 XiangShan 用来报告断言的特定 DPI-C 调用，DPI-C 是
SystemVerilog 调用 C/C++ 函数的接口。这里的 standalone assertion 指没有与前一篇
所述 SystemTask 组成相邻配对、需要单独生成的 `xs_assert_v2`。

生成器会把进入常规 schedule、非 `final` 且带执行条件的 SystemTask 完整 guard 标为
`unlikely`；`final` SystemTask 在仿真结束的 finalize 路径另行生成，不使用本提示。
对于 standalone `xs_assert_v2`，只有确认它没有 C 返回值、输出参数或供后续节点使用的
IR 结果时，才应用相同提示。这些限制不是所有 SystemTask 的共同前提；SystemTask 也不一定只是
“保护性”操作。优化只改变分支权重和代码布局，原条件、调用顺序、错误/断言触发及
DPI-C 副作用全部保留。[^source]

## 为什么这样做

正常仿真很少触发断言失败；许多 SystemTask 也位于低概率 guard 后。这些代码若与主
schedule 紧邻，会占用热路径的取指和指令缓存空间。把低概率分支移到 cold layout
可以减少这种干扰。与 #004 的差异在于：#004 要求一对相邻操作共享条件，本项直接给
单个 SystemTask 或合资格的 standalone assertion 提示，所以覆盖更广。
[^design]

## 收益（SimTop 50k walltime）

采用 full-gen150 的 `final-minus-one` 配对。完整候选当时有六项改动；control
`final-minus-#005` 移除 #005、保留另外五项，candidate full 恢复全部六项。另两项
后来因复测不能确认正收益而未落地，所以这个数字是在六项研究组合中的边际贡献，不是从 RWA
baseline 单独启用 #005 的收益。最终四项组合另有独立 endpoint 验证。[^ablation]

| 对比 | control（ms） | candidate（ms） | 减少（ms） | 相对改善 | ABBA / BAAB | gap |
|---|---:|---:|---:|---:|---:|---:|
| 去掉 #005 → full | 52,365.25 | 51,693.75 | 671.50 | **1.282339%** | 1.327670% / 1.236974% | 0.090697 pp |

四项一起从 native RWA endpoint `53,749.25 ms` 降到 `51,575.00 ms`，减少
`2,174.25 ms`、改善 `4.045173%`；不要把四个 leave-one-out 百分比相加。[^landing]

## 落地状态与边界

该提示以 generic default 进入 C++ emitter，Python 和 XiangShan（XS）集成流程继承；
没有 SimTop 专用名字表或额外开关。它只负责 SystemTask/assertion 形状，不能替代
#004 的相邻配对证明。[^landing]

### 数据来源（尾注）

[^design]: [`TNO0205`：四项候选的机制边界](../grhsim_opt_thj/TNO0205_simpletes_extended_bestpath_direct_ablation_result_20260731.md)。
[^ablation]: [`TNO0205`：full-gen150 final-minus-one 表（#005）](../grhsim_opt_thj/TNO0205_simpletes_extended_bestpath_direct_ablation_result_20260731.md)，含绝对 walltime、ABBA/BAAB 和 gap。
[^landing]: [`TNO0207`：四项 Wolvrix landing/regression](../grhsim_opt_thj/TNO0207_four_positive_wolvrix_landing_and_regression_20260731.md)、[`TNO0208`：native endpoint](../grhsim_opt_thj/TNO0208_four_positive_simpletes_repin_and_native_50k_20260731.md)。
[^source]: Wolvrix `fd12d83f...` 的 `lib/emit/grhsim_cpp.cpp` 中 SystemTask/standalone assertion cold emission；可用 `git show fd12d83f5150cc98540ed3e8f2af3b79f8054da0 -- lib/emit/grhsim_cpp.cpp` 复核。
