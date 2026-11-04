# TNO0426 恒零表调查的 source-order 重放门禁

本轮尝试把 C 版的 activity-schedule source 遍历顺序恢复为 E 版，用来检验“同一语义集合的遍历顺序改变了共享归属和后端形态”这条因果链。重放接口使用完整语义 source key、操作数/结果名及属性，拒绝缺失、重复、增加和歧义项；没有按 OperationId 或 batch 编号强行对应。

## 自身一致性检查

两侧默认关闭重放时，阶段导出已经通过一致性 gate：

- `stage-C/export_gate.json`：pre-reg-to-mem 图、生成 C++ 和头文件与 C 冻结参照逐字节一致；
- `stage-E/export_gate.json`：同样与 E 冻结参照逐字节一致；
- 只打开阶段导出不会改变生产生成结果。

小型 `activity_trace_fixture` 的 E/C 自身 source-order 重放也通过，14 个模型文件逐字节一致；因此失败点来自真实 XiangShan 的 `reg-to-mem` 阶段边界，不是重放接口在最小图上的基本错误。

## 重放为什么被拒绝

研究版恢复入口从冻结的 `pre_reg_to_mem.json` 继续生成。该快照位于 `reg-to-mem` 之前，而 source-order 列表来自完整 `reg-to-mem` 之后的 activity-schedule 输入。`reg-to-mem` 会重写寄存器/存储关系并改变内部操作集合；因此不能把后阶段的 source key 安全地套回前阶段快照。

最新 C 版重放在 activity-schedule source clone 阶段停止，严格错误为：

```text
source-order replay missing semantic source key=_op_177475
rank_size=338629 source_size=338629
```

这不是缺少一个输入文件，而是同样数量的 source key 中，前后阶段的语义身份不一致。此前 self3、self4 也在同一重放边界失败；self2 仅因输出目录已存在而没有重新执行。没有任何失败运行被当成 C/E 性能变体，也没有静默回退到普通路径。

## 当前结论

source 顺序与共享归属的结构差异已经被只读阶段记录确认，但本轮没有一个满足“只改变顺序、其余后端约束保持不变”的合法重放，因此不能把顺序恢复对 walltime 的影响称为因果证据。下一步若继续，需要保存 `reg-to-mem` 之后、activity-schedule 之前的完整合法快照，或者在同一阶段直接提供稳定的语义排序；不能从 pre-reg-to-mem 快照拼接后阶段排序。

产物：

- [C 阶段 gate](../../build/xs/decode_constant_investigation_20261104_v1/stage-C/export_gate.json)
- [E 阶段 gate](../../build/xs/decode_constant_investigation_20261104_v1/stage-E/export_gate.json)
- [最新失败日志](../../build/xs/decode_constant_investigation_20261104_v1/self5-C/logs/emit.log)
- [重放生成日志](../../build/xs/decode_constant_investigation_20261104_v1/replay-generation-v4.log)

