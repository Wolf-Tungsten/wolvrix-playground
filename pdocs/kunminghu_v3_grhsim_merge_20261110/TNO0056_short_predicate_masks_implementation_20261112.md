# TNO0056：短字段 Boolean 条件共享输入词

日期：2026-11-12（America/Los_Angeles）。承接 [TNO0055](./TNO0055_after_current_hotspots_20261112.md) 对 part_18 的当前热点定位：短 concat→AND 条件及外围 Boolean 组合仍反复展开。

## 实现边界

新增通用 emitter 选项 `short_concat_reduction_masks`，环境变量 `WOLVRIX_GRHSIM_SHORT_CONCAT_REDUCTION_MASKS`。实验初始显式开启，默认策略待完整功能和跨图性能验证后决定。父规则仍为 `scalar_concat_reduction`；原长字段共享掩码和宽 concat 归约独立保留。

短规则接受 4–15 个单 bit 字段的局部 concat，所有使用者必须是同一 compute 范围内、位于 concat 之后的 AND/NAND 或 OR/NOR 归约，不能混合类别或含数值用途。输入必须是 port 或持久 Boolean slot，不能在该范围内被 canonical value 或物理 slot 写入；局部定义、direct-state view、事件及未知副作用之后的候选均排除。

收益门至少包含 16 个不同的 `(mask, family)` 谓词，最多 64 个不同输入。不同谓词的输入引用总数还需达到不同输入数的 4 倍。重复字段、重排及重复相同谓词不能虚增该计数。没有为匹配更多节点而简单放宽原长规则的门槛。

输入词在原活动 guard 内捕获。短 concat 本身不再形成数值临时量；消费者从不可变输入词形成 mask compare，允许继续内联到其 Boolean 使用者。AND 比较 masked word 是否等于 mask，OR 比较是否非零，NAND/NOR 保留反相。实际输出、变化检测、状态、调度及模型布局不变。

静态 execution-plan 增加短条件 pack、input bits、elided concat 和 masked consumer 分类；不新增 GRH operation。规则不匹配 XiangShan 层级名、opcode 或分区编号。

## 验证范围

新增注册测试 `emit-grhsim-cpp-short-concat-reduction-masks`。复用已验证的 Boolean 条件 fixture，扩展以下边界：

- stable input、外部已物化 bool；局部写入、未知 effects、numeric/mixed-family uses 回退；
- 64/65 输入、15/16 不同谓词、复用不足、重复字段；
- 3/16 字段不进入短规则，4/15 字段可进入；
- 两类归约及其反相、全零/全一、walking bits、12,000 组固定随机输入与重复 eval；
- attribute/environment 优先级、默认/关闭、父规则关闭隔离；
- Clang 23 的 O0/O3、ASan/UBSan。

首轮 focused 功能检查和原长字段规则回归已通过，补充字段边界的完整检查继续运行。最终检查和性能结果将独立记录。

## 固定性能对象

基线为已启用长字段共享掩码与宽归约的 after seed7，binary SHA256：

```text
999c1f42a6bc3090a2801168f936432dd15777caaab4136705835dc7933be51a
```

候选重新发射同一 frozen partitioned GRH 与 assignment，Clang 23/O3/native、harness 和其余参数相同。只编译变化对象；完整 DiffTest、10k smoke、100k 验证、预热通过后，node030/CPU96–127、NUMA1 bind、ASLR off，执行 8 对 AB/BA。正式计时不混入额外插桩，仍不检查外部 CPU 空闲。

- [选项与安全条件](../../wolvrix/docs/emit/grhsim-short-reduction-masks.md)
- [起始源码身份](../../build/artifacts/repcut-short-reduction-20261112/start.json)、[生成工具身份](../../build/artifacts/repcut-short-reduction-20261112/emitter.json)
- [冻结图构建脚本](../../build/artifacts/repcut-short-reduction-20261112/build.py)、[配对脚本](../../build/artifacts/repcut-short-reduction-20261112/measure.py)
