# 009. T：typed event-edge storage（有类型事件边存储）

这是 SimpleTES 在四项正收益优化之后发现的 TRBS 路线的第一步。历史搜索把它称为
`T`（typed direct event array），最终与后续的 hot-event remap、posedge 预解码和
batch snapshot 一起形成 `TRBS`。本篇只说明“存储表示”这一机制；最终落地提交是
`d3ed9dea975bddf01185dde5c548a69241a09de9`。[^0211][^0214]

`T/TR/TRB/TRBS` 是逐项累积的实验节点：T 是本篇 typed storage；R 是热点事件
重映射；B 是上升沿 bool 预解码；S 是 batch 局部快照。本篇表格沿用原实验的 `B→T`
标签，其中 `B` 是上一阶段 four-positive baseline，不是 TRBS 名字中的 bool 层；该配对
只隔离 T，不包含后三项的收益。`T` 也是历史 arm 标签，不是用户可配置开关。

## 做了什么

### 先看总结

T 只改变“事件边沿分类存在哪里、以什么 C++ 类型存”，不改变事件是什么，也不在这一
步挑选热点。它把原来藏在原始字节区里的事件枚举，改成真正的事件枚举数组，为后面的
热点重映射、bool 预解码和 batch snapshot 提供一个类型明确的承载层。

| 层面 | 修改前 | 修改后 | 目的与边界 |
| --- | --- | --- | --- |
| 事件边存储 | 原始 byte arena，读取时把地址重解释成事件枚举指针 | `grhsim_event_edge_kind` typed array | 减少字节表示和枚举表示之间的中间层，让编译器看到真实对象类型 |
| 保存的信息 | 完整保存 posedge、negedge、general/none | 完整保存同样的分类 | 不改变事件语义、索引和调度 |
| 在 TRBS 中的职责 | 尚无稳定的 typed slot 供热点专门化使用 | 为 R、B、S 三层提供承载位置 | T 本身不选择热点，也不做 bool 预解码 |

**只需记住：T 是“换成有类型的事件边存储”，不是整套 TRBS。从上一阶段
四项优化基线（原实验记作 `B`）到 T 的直接消融为 `51,333.75→49,923.00 ms`，
walltime 减少 `1,410.75 ms`，改善 `2.748192%`。**[^0213]

### 实现与边界

事件边沿是某个 event value 相对前值的分类；这个值既可以来自 input，也可以来自
compute。`posedge` 是 0→1 上升沿，`negedge` 是 1→0 下降沿，general/none 表示其他
或无特定边沿。旧 emitter 为这些分类分配一段
**byte arena**，即没有元素类型的原始连续字节存储；每个事件值占用一个内部 **slot**。
查询时再用 `reinterpret_cast<grhsim_event_edge_kind *>` 把字节地址解释成事件枚举指针。
这里的 enum 是 C++ 中只有有限几个命名取值的类型，`reinterpret_cast` 只改变编译器
看待同一地址的指针类型。T arm 改为：

1. 用按 `grhsim_event_edge_kind` 元素类型生成的固定长度 typed array 直接承载事件边；
2. 保持事件边的 enum 类型和索引关系，避免“byte 存储 → 指针重解释 → enum
   比较”的中间层；
3. 为后续按 input event 统计和重映射保留稳定的 typed slot 表示。

这仍然保存 `posedge`、`negedge` 和 general event 的完整信息，不改变事件分类、
调度顺序或 guard 语义。后续的 TRB/​TRBS 只在此 typed 表上把一个最热的 input event
进一步专门化；因此 T 是承载层，不是针对 SimTop 端口名字的匹配。[^0212][^source]

## 为什么这样做

事件边沿分类会被大量 guard 重复读取。原始字节和重解释指针迫使编译器保守考虑这些
访问是否与其他字节访问指向同一内存，即别名关系；直接 typed array 则明确告诉编译器
“这里是一组事件枚举对象”。这有机会让它更容易合并重复读取、安排 load/store 依赖并
布置代码，也为后续 hot-event 选择、bool 解码和 batch snapshot 提供安全承载位置。
这不是保证编译器一定做某个特定优化，因此仍用 50k walltime 裁决。非热点的
negedge/general 继续保存完整 enum，不会因一个上升沿热点而丢失语义。[^0211][^source]

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
  Python 直接继承同一生成逻辑；没有新增 SimTop wrapper 开关，也不会匹配端口名、
  benchmark 名字或硬编码的 `ValueId` 编号。`ValueId` 仍只作为生成器里的通用值身份。
  [^0214]
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
