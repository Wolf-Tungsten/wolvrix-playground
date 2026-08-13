# 012. S8：按字段类型组织 persistent state

这是原则化 TRBS 之后 SimpleTES 找到的第一项 typed-state 增量。研究在
2026-08-12 完成，随后与后两项 typed-state 增量一起落入 Wolvrix 的通用
GrhSIM C++ emitter；落地提交是 `79ec2037b00f2d4894d72785277ebe3f5d37782d`。
[^design][^landing]

`S8` 只是 SimpleTES 搜索中保留下来的历史 arm 标签；现有记录没有给出足以可靠展开的
全称，因此本文不猜测其含义。特别地，`8` 不表示 8-bit，也不表示八项优化。

## 做了什么

**persistent state（持久状态）**是寄存器、锁存器等跨 schedule batch、并在后续仿真
步骤继续保存的 RTL 状态；本项不包括 memory，也不是临时组合结果。旧 emitter 把这些
非 memory 状态放进按字节/packed 方式管理的 arena，也就是一块通用存储区。

S8 保留旧 `slotIndex` 供排序和元数据使用，另外分配 `logicSlotIndex` 作为状态在其
类型类别内的位置。`scalar kind` 是 bool、不同宽度整数等生成器类型分类；宽值会拆成
若干通常为 64 bit 的 word，`wide word count` 是所需 word 数。生成代码不再用统一
byte arena 的偏移访问，而是访问相应类型的 C++ struct field；宽状态按 word 数分组，
这里的“分桶”只是按表示类型归类，不代表所有状态仍位于同一个数组。
在 S8 这个消融阶段，persistent bool 仍保留旧的 byte 表示，所以它只隔离了“按字段/类型
分桶和直接成员访问”这一变化。[^design][^source]

这不改变 RTL 状态语义，也不按 SimTop 的端口名、变量名或固定 `ValueId` 编号选择。
适用范围由状态的 kind、宽度和 emitter 结构决定；memory、register-to-memory staging
等明确排除的类别继续使用各自原有表示。S8 是通用布局变化，不存在一个对整模型进行
“通过/失败后回退”的运行时 selector。

## 为什么这样做

一个真实类型的成员表达式比“同一个 `std::byte` 数组加动态偏移”提供更窄的类型边界。
编译器可以少做 byte 与逻辑值之间的转换，并更容易判断哪些访问可能别名、哪些写入形成
依赖链；字段顺序和对齐也可能改变热点代码布局。别名分析是编译器判断两个地址是否可能
指向同一内存的过程；更明确的字段类型可以减少某些保守假设，但这里是对生成 C++ 形态
的解释，不是独立证明。PMU 中 backend stall（执行后端等待数据或执行资源的周期）的
下降与 walltime 同向，但最终保留标准仍是
端到端 SimTop 50k walltime。[^ablation]

## 收益（SimTop 50k walltime）

正式消融固定了 ASLR 关闭、空闲 whole CCD、NUMA 本地化、PMU 和功能门禁，并在同一
placement 上完成 ABBA+BAAB。改善定义为 `(control - candidate) / control`：[^ablation]

| 对比 | control（ms） | candidate（ms） | 减少（ms） | 相对改善 | ABBA / BAAB | gap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `B → S8` | 48,023.50 | 44,595.25 | 3,428.25 | **7.138693%** | 7.079028% / 7.198318% | 0.119290 pp |

这是第一项增量的直接端到端收益；不能把它和后两项的百分比简单相加，因为每次改变
生成代码都会改变后续编译器布局。S8 单独不是最终默认开关：它是最终 `SBV` endpoint
的必要前置阶段，三项一起通过 landing 回归后才作为一个默认组合启用。[^landing]

## 落地、依赖与边界

* S8 的研究基线是已经默认启用的原则化 TRBS（Wolvrix `d3ed9de...`），不是更早的
  手工优化基线。[^design]
* S8 依赖 emitter 对 scalar kind / wide word 的现有分类；它不依赖、也不打开
  `targeted-direct`。后者是另一条 event-edge gap-pack 研究开关。
* 最终 landing 使用同一 typed-state family 的三项增量（S8、SB、SBV），没有新增
  SimTop 专用选项；C++/Python 默认流程共同继承该行为。[^landing]
* S8 的 direct arm 在实验中有独立 walltime 证据，但没有作为一个单独 Wolvrix commit
  默认发布；若未来要单独回退，应以相邻消融和完整功能回归重新确认。

## 可复核身份

研究候选来自 typed-state checkpoint 的 gen60，materialized source SHA-256 为
`0de502d84e47bc458e2c3e368dfd41480db934bf2b0acde988ff79d79bf61384`；最终 landing
的源文件 SHA-256 为 `88f031189b1b240c2d1f567a60d2c001d9835318094a40abf080ff25002ee164`。
这些身份用于区分实验 arm 与最终三项合入后的源码，不代表重新运行测试。[^design][^landing]

### 数据来源（尾注）

[^design]: [`TNO0227`：typed-state 消融设计与三个阶段的定义](../grhsim_opt_thj/TNO0227_typed_state_bestpath_ablation_design_and_materialization_20260812.md)。该文档给出 B→S8 的语义边界、候选身份和研究基线。
[^ablation]: [`TNO0229`：node032 完成的直接消融结果](../grhsim_opt_thj/TNO0229_typed_state_bestpath_ablation_node032_runtime_completion_20260813.md)，表 4 给出固定 CCD 的绝对 walltime、ABBA/BAAB 和 gap；表 6 给出 PMU 解释。
[^landing]: [`TNO0230`：typed-state 三项落地与回归](../grhsim_opt_thj/TNO0230_typed_state_wolvrix_landing_and_regression_20260813.md)，记录通用默认、功能回归、Wolvrix commit 和最终 B→SBV endpoint。
[^source]: Wolvrix 子模块提交 `79ec2037b00f2d4894d72785277ebe3f5d37782d` 的 `lib/emit/grhsim_cpp.cpp` diff：`StateDecl.logicSlotIndex`、按 kind/word 分桶的 state ref 以及 typed storage 生成逻辑；可在子模块中用 `git show 79ec203... -- lib/emit/grhsim_cpp.cpp` 复核。
