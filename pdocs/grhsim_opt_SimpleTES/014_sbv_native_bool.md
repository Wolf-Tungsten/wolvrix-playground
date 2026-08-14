# 014. SBV：materialized value bucket 使用 native bool

这是目前历史上最后一项已落地的 SimpleTES typed-state 增量。它建立在 S8 的 typed
persistent state 和 SB 的 native-bool persistent state 之上，进一步处理 materialized
value bucket（`kBool`）本身；三项增量共同形成 `SBV` endpoint，并于
2026-08-13 作为 Wolvrix 通用默认行为落地。[^design][^landing]

**materialized value** 原本可以直接嵌入某个 C++ 表达式；当它需要跨多个使用点复用时，
emitter 会为它实际分配存储。**value bucket** 是把相同类型/宽度的这些中间值集中放入
一个数组。它不是 RTL 寄存器，不承担跨仿真步骤保存设计状态的职责。`kBool` 是 emitter
内部对一位真假逻辑值的分类名。

## 做了什么

### 先看总结

SBV 把“为了复用而临时保存的组合布尔结果”也改成 C++ `bool` 数组。它和 SB 都在消除
byte 形式的布尔存储，但作用对象不同：SB 管跨仿真步骤存在的持久状态，SBV 管本可内联、
因为有多个使用点才被 emitter 缓存起来的组合中间值。

| 对象 | 修改前 | 修改后 | 目的与边界 |
| --- | --- | --- | --- |
| materialized `kBool` value bucket | byte-like 元素数组 | `std::array<bool, N>` | 让频繁读取的组合布尔缓存直接具有布尔类型 |
| bucket reset | 按旧元素类型清零 | 填入 `bool{}` | 与新的 owning element 类型一致 |
| persistent bool | 已由 SB 改为 native bool | 保持不变 | SBV 不重复修改持久状态 |
| event、memory、schedule | 各自原表示和行为 | 保持不变 | 只改变 materialized bool 的存储类型 |

**只需记住：SBV 是“组合布尔缓存改用 native bool”。相邻消融 `SB→SBV` 为
`44,198.00→43,373.50 ms`，减少 `824.50 ms`、改善 `1.865469%`；三项 typed-state
合起来从实验基线到 SBV 为 `48,054.25→43,335.50 ms`，减少 `4,718.75 ms`、改善
`9.819631%`。这里的实验基线（原实验记作 `B`）已包含此前的原则化 TRBS。**[^ablation]

### 实现与边界

SBV 将生成的 materialized `kBool` bucket 从旧的 byte-like owning element 改为
`std::array<bool, N>`，复位也直接填入 `bool{}`。它只作用于已经 materialize 的组合值
缓存，不改变 persistent state 的分桶规则、event-edge enum、memory staging 或
schedule。换句话说，SBV 和 [013](./013_sb_native_bool.md) 都使用 native bool，但
作用对象不同：SB 处理持久状态，SBV 处理 materialized value bucket。[^source]

## 为什么这样做

materialized 布尔值在热点表达式中被频繁读取。让 owning bucket 的真实 C++ 类型就是
`bool`，可减少 byte 表示与布尔表达式之间的规范化，并向编译器表达准确的值类型；
已有证据并不能证明旧 `uint8_t` 表示造成了“宽加载”，因此不作这个更强的声称。与前
两项的直接 typed member 布局结合后，编译器可能进一步收紧别名/依赖关系并改善热路径
布局。这里的“可能”是
代码形态的解释，实际是否保留只由 SimTop 50k walltime 和功能门禁决定，不由 ELF 大小
或单个 PMU 计数决定。[^ablation]

## 收益（SimTop 50k walltime）

在同一套 fixed-ASLR、空闲 CCD、NUMA、本地页、PMU 和功能审计协议下，SB→SBV 的
相邻直接消融为：[^ablation]

| 对比 | control（ms） | candidate（ms） | 减少（ms） | 相对改善 | ABBA / BAAB | gap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `SB → SBV` | 44,198.00 | 43,373.50 | 824.50 | **1.865469%** | 1.873960% / 1.856983% | 0.016977 pp |

该边际收益与前两项不能机械相加。更重要的总口径是从原始 typed-state baseline 到
最终 endpoint：直接消融 `B→SBV` 为 `48,054.25 → 43,335.50 ms`，减少
`4,718.75 ms`、改善 **9.819631%**；随后 Wolvrix native landing 的独立回归为
`48,162.50 → 43,434.50 ms`，减少 `4,728.00 ms`、改善 **9.816766%**，ABBA/BAAB
分别为 `9.841082%`/`9.792411%`。两轮绝对数值来自不同实验窗口，不能彼此相减；它们
共同确认 endpoint 的端到端收益和默认落地方向。[^ablation][^landing]

名称关系上，`SB` 是“S8 加 persistent native bool”的累计节点；`SBV` 再加本篇的
materialized-value native bool。SBV 是最终 endpoint 名，不是第四项独立优化。真正的
三项相邻增量是 `B→S8`、`S8→SB`、`SB→SBV`。

## 落地、依赖与默认行为

* SBV 依赖 [012](./012_s8_typed_state.md) 和 [013](./013_sb_native_bool.md)，并与
  原则化 TRBS 一起构成当前研究 baseline；它不依赖或打开 `targeted-direct`。
* `79ec2037b00f2d4894d72785277ebe3f5d37782d` 将三项增量作为无新增选项的通用
  GrhSIM C++ emitter 默认行为落地；Python/XS 流程继承同一默认生成配置。功能回归
  （pybind `22/22`、XS wrapper `32/32`）和 node032 的同 CCD 50k 回归均通过。[^landing]
* 后续 SimpleTES 应从 typed-state landing 的精确 parent/source pin 继续；历史上的
  `B` arm 只表示消融基线，不意味着默认关闭 typed-state。

## 可复核身份

SBV 候选来自 checkpoint gen72，patch SHA-256 为
`d7ec315534865641cd3a3cc2f76ca70cbf77c3c6191ce0688135ca3016a45325`，materialized
source SHA-256 为 `88f031189b1b240c2d1f567a60d2c001d9835318094a40abf080ff25002ee164`。
landing 后的 Wolvrix commit 是
`79ec2037b00f2d4894d72785277ebe3f5d37782d`，SimpleTES 继续研究使用的 parent
executable snapshot 为 `b2fd50a4cac034cea8420835c6869d05cdde670c`。[^design][^landing]

### 数据来源（尾注）

[^design]: [`TNO0227`：S8/SB/SBV 的分层定义、候选 SHA 和物化边界](../grhsim_opt_thj/TNO0227_typed_state_bestpath_ablation_design_and_materialization_20260812.md)。
[^ablation]: [`TNO0229`：SBV 相邻消融和 B→SBV endpoint 的绝对 walltime](../grhsim_opt_thj/TNO0229_typed_state_bestpath_ablation_node032_runtime_completion_20260813.md)，含 ABBA/BAAB、gap、PMU 与固定运行门禁。
[^landing]: [`TNO0230`：最终 typed-state landing 回归](../grhsim_opt_thj/TNO0230_typed_state_wolvrix_landing_and_regression_20260813.md)，含 commit、功能测试、native B→SBV walltime 和后续 research pin。
[^source]: Wolvrix `79ec203...` 的 `lib/emit/grhsim_cpp.cpp`：`scalarLogicObjectCppType(kBool)` 及 materialized `value_*` bucket 的 `std::array<bool, N>` 声明/复位；可用 `git show 79ec203... -- lib/emit/grhsim_cpp.cpp` 复核。
