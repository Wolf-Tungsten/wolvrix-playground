# 009. TRBS：typed event-edge storage（有类型事件边存储）

这是 SimpleTES 在四项正收益优化之后发现的 TRBS 路线的第一步。历史搜索把它称为
`T`（typed direct event array），最终与后续的 hot-event remap、posedge 预解码和
batch snapshot 一起形成 `TRBS`。本篇只说明“存储表示”这一机制；最终落地提交是
`d3ed9dea975bddf01185dde5c548a69241a09de9`。[^0211][^0214]

## 做了什么

旧 emitter 为事件边分配一段 byte arena，然后在每次查询时通过
`reinterpret_cast<grhsim_event_edge_kind *>` 访问它。T arm 改为：

1. 用按 `grhsim_event_edge_kind` 元素类型生成的 fixed typed array 直接承载事件边（而不是 byte arena）；
2. 保持事件边的 enum 类型和索引关系，避免“byte 存储 → 指针重解释 → enum
   比较”的中间层；
3. 为后续按 input event 统计和重映射保留稳定的 typed slot 表示。

这仍然保存 `posedge`、`negedge` 和 general event 的完整信息，不改变事件分类、
调度顺序或 guard 语义。后续的 TRB/​TRBS 只在此 typed 表上把一个最热的 input event
进一步专门化；因此 T 是承载层，不是针对 SimTop 端口名字的匹配。[^0212][^source]

## 为什么这样做

事件边是高频 predicate 的输入。byte arena 和重解释指针让生成代码跨越一层别名
边界，编译器难以稳定地证明相邻查询读取的是同一类对象。直接的 typed array
提供明确的元素类型、连续布局和可分析的索引，使后续 hot-event 选择、bool 解码
和 batch-local snapshot 能在 emitter 层安全实现。它还让非热点的 negedge/general
事件继续保留完整 enum，避免为了一个热点而牺牲其他 edge 语义。[^0211][^source]

这里的“更好的别名分析/依赖链/代码布局”是编译器层面的合理解释，而不是额外的
性能测量结论：文档中的端到端裁决仍只采用 SimTop 50k walltime。[^0213]

## 收益（SimTop 50k）

在 landed four-positive baseline `B` 上，直接比较 `B→T` 的同 CCD、固定 ASLR、
ABBA+BAAB 结果为：[^0213]

| 对比 | control（ms） | candidate（ms） | walltime 减少（ms） | 相对改善 | ABBA / BAAB |
| --- | ---: | ---: | ---: | ---: | ---: |
| `B→T` typed storage | 51,333.75 | 49,923.00 | 1,410.75 | **2.748192%** | 2.827929% / 2.668420% |

该轮 order gap 为 `0.159508 pp`，低于 `0.25 pp` 复测线；功能、PMU、NUMA、CCD、
ASLR 和迁移检查均通过。[^0213]

注意：最终 TRBS 不是把各项百分比相加。完整 endpoint `B→TRBS` 为
`51,562.00→47,632.25 ms`，减少 `3,929.75 ms`、改善 `7.621407%`；T 的
`2.748192%` 是在 B→T 这个相邻 pair 中测出的边际，不是对最终 endpoint 的独立
可加份额。[^0213]

## 落地状态与边界

* Wolvrix 提交 `d3ed9dea...` 将 typed storage 放入通用 C++ emitter 默认路径，
  Python 直接继承同一生成逻辑；没有新增 SimTop wrapper 开关，也没有读取端口名、
  ValueId 或 benchmark 名字。[^0214]
* 原始搜索曾使用 `eventEdgeSlotCount >= 256` 作为候选门槛；落地时删除了这个
  raw model-size 门禁，改由基于 exact-posedge 复用机会的原则化选择器决定是否
  启用整套热点表示。小模型或复用不足时 fail-closed，保持旧生成结果。[^0214]
* typed storage 本身给后续 bool 专门化提供承载位置；不能把旧 HS 的完整 enum
  snapshot 再机械叠加到 TRBS，因为会重复处理同一热点事件。[^0213][^0214]

### 数据来源（尾注）

[^0211]: [`TNO0211`：SimpleTES post-four 研究完成](../grhsim_opt_thj/TNO0211_simpletes_post_four_gpt_max_research_completion_20260801.md)，记录 T 路线的搜索历史、候选语义和最终 TRBS endpoint。
[^0212]: [`TNO0212`：hot-event 消融设计与候选物化](../grhsim_opt_thj/TNO0212_hot_event_bestpath_ablation_design_and_materialization_20260801.md)，定义 `B/T/H/HS/TR/TRB/TRBS` 各 arm 及 direct-pair 协议。
[^0213]: [`TNO0213`：hot-event direct ablation 结果](../grhsim_opt_thj/TNO0213_hot_event_bestpath_direct_ablation_result_20260801.md)，提供 `B→T` 与总 endpoint 的绝对 walltime、相对改善和 gate 结果。
[^0214]: [`TNO0214`：原则化 hot-event 门禁落地](../grhsim_opt_thj/TNO0214_principled_hot_event_landing_and_native_gate_20260801.md)，记录通用默认、raw slot-count 门禁移除和 landing commit。
[^source]: Wolvrix `lib/emit/grhsim_cpp.cpp`（`d3ed9dea`）中的 `eventEdgeStorageType`、`event_edge_storage_`、构造函数绑定和 event clear/classify 代码；可用 `git show d3ed9dea:lib/emit/grhsim_cpp.cpp` 复核。
