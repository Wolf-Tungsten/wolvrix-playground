# 011. TRBS：batch-local bool snapshot

这是 TRBS 的第三个机制层，也是最终 `TRBS` 中最后加入的优化。它建立在 typed
event storage 和 `hot_event_posedge_` 预解码之上：每个 schedule/fullpass batch
入口先把对象成员复制到一个 batch-local 的 `const bool`，本 batch 内的 event
predicate 都读取这个局部值。[^0211][^source]

batch-local snapshot 的含义很直接：进入一个 batch 时把对象成员读一次，保存到普通
局部 `const bool`，本 batch 后续都读这个局部变量。历史候选曾用 `non-volatile`
描述它，但生成代码没有使用 C++ `volatile`；删除该词是为了避免把两者混淆。

## 做了什么

对启用了 hot-event specialization 的 batch，emitter 生成类似：

```cpp
void Model::schedule_batch_...() {
    [[maybe_unused]] const bool hot_event_posedge_ = this->hot_event_posedge_;
    // 后续 exact-posedge leaf 使用局部 hot_event_posedge_
}
```

full-pass 变体同样生成 snapshot；full-pass 是无增量活动筛选、直接执行该批完整计算的
调度入口。对象成员仍由输入分类阶段更新、由每轮 clear/init 清零。调度语义保证同一
batch 执行期间该事件分类不变，所以 snapshot 只是缓存一个稳定值，并非忽略中途更新。
negedge/general 的剩余查询继续走完整 enum。[^source]

## 为什么这样做

schedule batch 内可能包含 SystemTask（HDL 系统任务）、DPI-C 调用或其他编译器无法
证明“不修改当前模型对象”的函数。若每个 leaf 都重新读取对象成员，编译器必须保守
假设调用可能通过另一个指针改写它，这就是对象别名依赖。先复制到局部 `const` 后，
后续表达式不再需要跨这些调用重复读取成员，编译器也更有机会把局部值放在 CPU 寄存器
中。这个解释来自生成代码形态和 PMU 归因；是否保留仍以
端到端 walltime 为准。[^0213]

snapshot 只在 selector 已经证明存在足够 `reusableUses` 时启用，且每个 batch
只做一次读取；没有使用模型名称或固定 ValueId 的特判。[^0214]

## 收益（SimTop 50k）

SimpleTES 从最终 gen28 机械构造 `TRB`（有 decoded bool、无 snapshot）和 `TRBS`
（再加 batch snapshot），直接比较：[^0213]

| 对比 | control（ms） | candidate（ms） | walltime 减少（ms） | 相对改善 | ABBA / BAAB |
| --- | ---: | ---: | ---: | ---: | ---: |
| `TRB→TRBS` | 48,449.75 | 47,495.50 | **954.25** | **1.969566%** | 1.942910% / 1.996204% |

order gap 为 `0.053293 pp`，低于 `0.25 pp` 复测线；固定 ASLR、whole-CCD quiet、
NUMA、PMU、功能和迁移检查均通过。[^0213]

在搜索路径的早期实现中，H 是 hot scalar enum，即为热点输入保留标量事件枚举；HS
是在 H 上再加入 enum batch snapshot。`H→HS` 为
`48,226.75→47,566.50 ms`，减少 `660.25 ms`、改善 `1.369053%`；这是完整 enum
快照的历史 arm，不应与最终 bool snapshot 的 `TRB→TRBS` 数字相加。两者属于同一
“批次内缓存事件 predicate”思想的早期替代实现。HS 与 TRBS 处理同一热点，不能叠加。
[^0212][^0213]

最终组合 `B→TRBS` 为 `51,562.00→47,632.25 ms`，减少 `3,929.75 ms`、改善
`7.621407%`；各相邻边际有交互，正式总收益只采用 endpoint。[^0213]

## 落地状态与验证

batch snapshot 随 TRBS 一起进入 Wolvrix 通用默认 C++ emitter（提交
`d3ed9dea975bddf01185dde5c548a69241a09de9`），Python 流程直接继承，不是 SimTop
专用开关。原则化 selector 用 `reusableUses > fixedCost(2)` 作为门禁；这里的
`reusableUses` 是可复用查询次数，`fixedCost(2)` 是前一篇解释的静态成本单位，不是
两条指令。机会不足时 fail closed，保留通用路径；旧
`eventEdgeSlotCount >= 256` raw 阈值已删除。[^0214]

专项测试覆盖 fullpass 与普通 batch、端口改名/注册顺序、event edge 混用、平手稳定性
以及门槛边界；fresh direct-hot、主 emitter、pybind、XS 和 full CTest 均通过（full
CTest 仅保留两项既有 expected failure）。[^0214]

## 与 HS 的关系

HS 是搜索中较早的“完整 enum + batch snapshot”实现，TRBS 则是“typed slot +
hot-event bool + batch bool snapshot”的后继实现。两者针对同一热点事件的分类、
存储和 snapshot，不能把 HS 原样叠加到 TRBS；若要优化残余 negedge/general 查询，
必须另建 hybrid arm 并重新通过 SimTop 50k 门禁。[^0213][^0214]

### 数据来源（尾注）

[^0211]: [`TNO0211`：post-four GPT max 研究完成](../grhsim_opt_thj/TNO0211_simpletes_post_four_gpt_max_research_completion_20260801.md)，记录 HS/TRBS 搜索路径及候选身份。
[^0212]: [`TNO0212`：消融设计与物化](../grhsim_opt_thj/TNO0212_hot_event_bestpath_ablation_design_and_materialization_20260801.md)，定义 `H→HS` 和 `TRB→TRBS` 的机制边界。
[^0213]: [`TNO0213`：direct ablation 结果](../grhsim_opt_thj/TNO0213_hot_event_bestpath_direct_ablation_result_20260801.md)，提供两组 snapshot 的绝对 walltime、相对改善、order gap 和最终 endpoint。
[^0214]: [`TNO0214`：原则化 hot-event landing/native gate](../grhsim_opt_thj/TNO0214_principled_hot_event_landing_and_native_gate_20260801.md)，提供通用默认、门禁公式、测试和旧/新 gate 对比。
[^source]: Wolvrix `lib/emit/grhsim_cpp.cpp`（`d3ed9dea`）约 22801–22839 的 batch/fullpass 局部 snapshot、20554–20566 的 clear、27706–27711 的成员声明、30814–30823 的分类与 bool 更新。
