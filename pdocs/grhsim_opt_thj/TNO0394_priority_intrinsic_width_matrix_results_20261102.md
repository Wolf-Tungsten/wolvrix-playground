# TNO0394：优先编码原语全位宽微基准结果

日期：2026-11-02。31 个位宽、packed/lanes 两种布局的测量已完成。

接续 [TNO0393](./TNO0393_priority_intrinsic_full_xs_ab_gate_20261102.md)。

## 口径

矩阵目录为 `wolvrix/build/artifacts/priority-intrinsic/matrix-v3/`。每个 case 都
完成两组固定种子功能检查；总检查数为 `62,248,366` 个向量。每个分布和路径使用
8 对交替 AB/BA，分布为 random、sparse、dense、toggle1、hold99；同时测完整
`eval` 和提取出的完整 compute group body。运行固定 node030 CPU96，私有二进制页、
匿名页、线程亲和性和 SMT sibling 均通过；失败目录没有被删除。

矩阵宽度为：

```text
1,2,3,4,5,6,7,8,9,10,14,15,16,17,31,32,33,36,38,63,64,65,
127,128,129,255,256,257,511,512,1024
```

每个 case 的 80 个 timing rows 和 8 对样本在各自 `summary.json`；汇总在
`matrix-summary.json/csv` 和 `matrix-summary-by-width.json/csv`。

## 结果概览

按 310 个完整路径行、310 个 compute 行分别统计，负值表示 B 更快：

| 路径 | 中位变化 | 平均变化 | B 更快行数 |
|---|---:|---:|---:|
| 完整 eval | -21.8683% | -26.4478% | 259/310 |
| compute body | -22.6116% | -20.7203% | 252/310 |

这些是局部纯操作/局部模型结果，不能替代整机结论；整机 A/B 在 [TNO0393](./TNO0393_priority_intrinsic_full_xs_ab_gate_20261102.md)
中反而为 +0.439982%。二者差异正是需要保留完整输入 gather、结果物化、活动传播和
状态上下文的原因。

## 结构依赖明显的例子

- **大 packed 输入收益很大。** width=1024 packed 的 compute 中位 A/B 为
  `2451.83 ns / 22.13755 ns`，变化 `-99.0949%`；完整 eval 为
  `2415.185 ns / 41.8738 ns`，变化 `-97.9644%`。width=511/512 packed 也有
  约 `-97%..-98%` 的变化。这里原硬件优先编码树在软件中展开了大量中间操作，
  而 CTZ helper 扫描机器字。
- **非整字 packed 也稳定受益。** width=65 packed compute 中位变化 `-71.6553%`，
  width=129 packed `-88.6363%`；多字实现正确处理尾字有效位。
- **分散 lanes 的 width=65 是明显退化。**完整 eval 中位变化 `+334.1354%`，
  compute 中位变化 `+547.3953%`，5 种分布均为 B 变慢。intrinsic 的完整输入
  依赖需要先物化 65 个 lane 的 packed 数据，原有树形硬件映射在这个小宽度和布局
  下反而更适合当前 GrhSIM 活动/局部表达式。width=14 lanes compute 也约 `+69.98%`。

这说明不能按“位宽越大越应该替换”或只测 packed 输入制定规则。至少需要把输入
布局、gather 成本、结果是否跨组物化和实际活动模式作为成本选择条件。当前接口仍
保持统一完整依赖，尚未偷偷加入按宽度挑选的默认策略。

## 解释边界

微基准使用同一语义接口和独立 Verilator 参考；它证明功能和局部成本差异，不证明
硬件面积、时序或整机收益。`matrix-v3-run.log` 中第一次因 coverage 文件身份
不同而拒绝的启动保留为输入一致性证据，随后使用构建时冻结的 coverage manifest
完成正式测量。
