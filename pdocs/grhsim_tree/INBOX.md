# 用户提示收件箱

用户随时在此追加优化提示 / 方向建议 / 怀疑点。条目只追加不删除。
搜索循环每轮扩展节点前先处理本文件：条目 → 转为候选动作（写入 `TREE.md` 候选池）或标注暂缓原因。

条目格式：

```
### IN-YYYYMMDD-NN 标题
- 日期：YYYY-MM-DD
- 内容：（用户原始提示，尽量保留原话）
- 状态：未处理 / 已纳入 STxxxxx / 暂缓（原因）
```

## 条目

### IN-20260725-01 参考 legacy grhsim 的划分方法
- 日期：2026-07-25
- 内容：参考 grhsim 非 AM 版本的划分方法。AM 当前 69min 远低于 legacy grhsim 的速度（~166s），说明 AM 的调度/划分结构有根本性差距，应对齐 legacy 的 supernode 划分思路。
- 状态：已纳入候选池（见 TREE.md，2026-07-25）

### IN-20260725-02 在 grhsim AM 上做 transform 优化
- 日期：2026-07-25
- 内容：可以在 grhsim AM 管线上做 GRH transform 层面的优化（在调度/emit 之前削减工作量或改善结构）。
- 状态：已纳入候选池（见 TREE.md，2026-07-25）

### IN-20260725-03 AM 必须补 coarsen+dp transform（grhsim-am-activity-schedule）
- 日期：2026-07-25
- 内容：必须在 AM 生成后、emit cpp 之前，做一个 coarsen+dp 的 transform，叫 grhsim-am-activity-schedule，没有讨价还价的余地，必须做。
- 状态：已纳入 ST00008（已实现并评估，2k 门控回归 pruned-regression，工具链保留，2026-07-25）

### IN-20260725-04 AM 运行时原语成本优化对齐 gsim
- 日期：2026-07-25
- 内容：也要做成本优化（激活位图化、分派扁平化等），和原来的 gsim 看齐。
- 状态：已分解并持续推进：ST00003 pruned-regression，ST00004 parked，ST00005 pruned-no-gain；commit 后续转入 ST00011 巨块写槽脚手架稀疏化（见 TREE.md，2026-07-26）

### IN-20260725-05 先对齐 2k 性能再谈 50k
- 日期：2026-07-25
- 内容：写在工作文档里，先对齐 grhsim am 和 legacy 2k 性能，如果不对齐就做50k，会浪费太多时间。
- 状态：已写入 README 目标与测量协议 + TREE.md（2026-07-25）
