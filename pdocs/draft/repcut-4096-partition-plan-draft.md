# Repcut 4096 分区支持改造计划（草案）

## 背景

当前 `repcut` 的分区归属使用 `uint64_t` 位掩码（`PartMask`）表示，导致分区数上限被限制在 `<= 63`。这与大规模切分需求（如 4096 分区）不兼容。

## 目标

- 将 `repcut` 分区能力从 `<= 63` 扩展到 `>= 4096`。
- 保持现有功能语义一致（结果正确、诊断一致、统计可用）。
- 避免在常见小分区场景出现明显性能退化。

## 现状与根因

- 关键数据结构为固定 64-bit 位掩码，无法表达 64+ 分区。
- `partition_count > 63` 在入口被硬拒绝。
- 多处逻辑依赖位掩码操作（contains / iterate / first owner）。

## 方案总览

核心思路：用可扩展的 `PartitionSet` 替代固定 `PartMask`，并保留单 owner 快路径。

- 抽象统一接口：`add(partId)`、`contains(partId)`、`forEach(...)`、`first()`、`empty()`。
- 采用小集合优化：低分区密度时使用轻量存储，超出阈值再转动态结构。
- 现有 `opPartition`（单 owner 映射）保留，用于热路径减少开销。

## 分阶段计划

### P0: 结构抽象与落地

- 引入 `PartitionSet` 类型及最小可用接口。
- 将 `partMaskBit / partMaskHas / forEachPartInMask` 替换为 `PartitionSet` API。
- 编译通过且行为与当前版本一致（在 `<=63` 范围）。

### P1: 全链路替换与语义对齐

- 替换 `opPartitionMask`、`valueDefPartMask` 等关键容器类型。
- 修复所有依赖位运算的分区遍历、owner 选择、cross-value 计算逻辑。
- 保证 phase-e rebuild 的 mapping/diagnostic 行为不变。

### P2: 放开上限到 4096

- 将参数校验由 `<=63` 调整为 `<=4096`。
- 更新错误信息与 CLI 帮助文案。
- 确认 mt-kahypar 参数传递、分区结果解析在 4096 下可正常运行。

### P3: 测试与回归

- 新增 `PartitionSet` 单元测试：去重、遍历顺序、first owner、稀疏/稠密场景。
- 新增 transform 测试：`partition_count=64/512/4096` 小图可跑通。
- 回归现有 `transform-repcut`、xs-repcut 主流程。

### P4: 性能与观测

- 扩展统计项：多归属比例、平均归属分区数、分区集合峰值大小。
- 对比改造前后在 xs 场景的 phase-e 时间与内存占用。
- 若出现退化，迭代优化容器实现（内存池/压缩表示）。

## 风险与缓解

- **风险：** 动态集合带来内存增长与遍历开销。  
  **缓解：** 小集合优化 + 单 owner 快路径 + 分阶段压测。

- **风险：** 替换范围大，易引入边界回归。  
  **缓解：** 先抽象再替换，逐阶段补测试并保持诊断一致性。

## 验收标准

- `partition_count=4096` 在 repcut 参数校验层面可通过。
- 至少 1 个 4096 分区测试用例稳定通过。
- 现有 repcut 回归测试全部通过。
- 最终日志统计与诊断完整，且分区输出结构正确。

## 备注

本草案先聚焦“功能正确 + 可扩展性”；性能优化视压测结果在后续迭代完成。
