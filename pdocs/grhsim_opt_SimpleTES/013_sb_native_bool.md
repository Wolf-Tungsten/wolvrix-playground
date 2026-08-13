# 013. SB：persistent state 使用 native bool

这是 typed-state 路线的第二项、也是第二个相邻增量。它建立在 S8 的字段/类型分桶
之上，只把 persistent state 中语义为布尔值的 owning storage 从旧的 byte 形态改为
C++ 原生 `bool`。该机制与下一篇的 materialized value bucket 分开消融，最终随三项
组合一起落入 Wolvrix 默认提交 `79ec2037b00f2d4894d72785277ebe3f5d37782d`。[^design][^landing]

这里的 **owning storage** 是真正拥有并长期保存值的 C++ 字段，不是临时引用或访问
表达式；**native bool** 表示该字段的实际 C++ 类型是 `bool`，不是“使用某条原生 CPU
布尔指令”。persistent bool 会跨 batch 和仿真步骤保存设计状态，与下一篇只缓存组合
中间结果的 materialized bool 生命周期不同。

## 做了什么

在 S8 arm 中，按 kind 分桶已经让状态通过直接成员访问，但 bool 状态仍使用 byte
对象；SB 进一步让 persistent bool 字段的 C++ 元素类型为 `bool`，初始化/清零也按
`bool{}` 进行。整数、宽向量、memory staging 和 event-edge storage 不在这项变化内。
memory staging 是 memory 读写在提交前后使用的暂存表示，不属于本项持久 bool 字段。
因此 SB 不是重新设计状态机，而是把已有的“布尔语义”准确传给生成 C++ 的对象类型。
[^source]

## 为什么这样做

原生 `bool` 让生成代码的对象类型与其逻辑取值域一致，避免在 byte 容器与布尔表达式之间
反复规范化；在 S8 已经建立的字段边界上，编译器也有更明确的成员类型和依赖关系可用。
这可能改善别名保守性、store/load 依赖和局部布局，但这些是对代码形态的合理解释，不能
替代端到端测量。没有使用 SimTop 名字匹配或其他 workload 特判。[^ablation]

## 收益（SimTop 50k walltime）

在固定 ASLR-off、空闲 CCD、NUMA/PMU/功能门禁下，S8→SB 的同 CCD ABBA+BAAB
直接消融为：[^ablation]

| 对比 | control（ms） | candidate（ms） | 减少（ms） | 相对改善 | ABBA / BAAB | gap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `S8 → SB` | 44,760.25 | 44,195.25 | 565.00 | **1.262281%** | 1.278002% / 1.246534% | 0.031467 pp |

两种 order 同向且 gap 很小；该数值是 SB 这一项的边际收益，不是从 B 基线重新测出的
总收益。最终三项组合的 landing 回归（B→SBV）另见 [014](./014_sbv_native_bool.md)。

## 落地、依赖与默认行为

* SB 依赖 [012](./012_s8_typed_state.md) 的 field-sensitive state layout；它不依赖
  `targeted-direct`，也不读取 SimTop 负载名称。
* SimpleTES 的直接 arm 是归因实验，不单独发布为一个开关。S8、SB、SBV 的完整
  endpoint 通过功能和 native 默认回归后，以通用 C++/Python 默认行为一起保留；
  Wolvrix commit 为 `79ec2037b00f2d4894d72785277ebe3f5d37782d`。[^landing]
* 若将来只想回退 SB 而保留 S8/SBV，必须重新 materialize（把实验 patch 应用成可构建
  源码）、做功能回归并测 fresh（从固定身份重新生成和构建的）
  50k；本历史整理不声称这种未测组合的性能。

## 可复核身份

SB 候选为 typed-state checkpoint gen68，patch SHA-256 为
`364421e26eb32559f07e0f5bb1327e6872c5f3bb7efd5110808ad3fd0e036da0`，materialized
source SHA-256 为 `26ff41171b4308bbe2f0b70b97cb3551e366c0b7fc28c961f830a5524b42a168`。
最终 landing source SHA-256 为
`88f031189b1b240c2d1f567a60d2c001d9835318094a40abf080ff25002ee164`。[^design][^landing]

### 数据来源（尾注）

[^design]: [`TNO0227`：typed-state 三个预注册 arm 的定义与身份](../grhsim_opt_thj/TNO0227_typed_state_bestpath_ablation_design_and_materialization_20260812.md)。
[^ablation]: [`TNO0229`：SB 相邻消融（表 4）及固定运行门禁](../grhsim_opt_thj/TNO0229_typed_state_bestpath_ablation_node032_runtime_completion_20260813.md)。
[^landing]: [`TNO0230`：三项 typed-state 合并、默认配置与功能回归](../grhsim_opt_thj/TNO0230_typed_state_wolvrix_landing_and_regression_20260813.md)。
[^source]: Wolvrix `79ec203...` 的 `lib/emit/grhsim_cpp.cpp`：`scalarLogicObjectCppType(kBool)` 返回 `bool`，typed state reset 使用对应对象类型；可在子模块中以 `git show 79ec203... -- lib/emit/grhsim_cpp.cpp` 复核。
