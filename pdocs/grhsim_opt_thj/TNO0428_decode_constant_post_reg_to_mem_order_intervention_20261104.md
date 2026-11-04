# TNO0428 恒零表回退的合法顺序干预与 walltime 结果

本轮把 source-order 干预推进到正确的阶段边界。之前的重放失败并不表示 source 集合不兼容，而是旧列表来自另一次完整生成，包含了当次图的 `_op_N` 内部符号；从 JSON 重新读入同一设计后，OperationId 和内部符号会重新编号。直接使用旧列表会把身份错误误判为后端差异。

## 合法快照和自身检查

新增研究入口在 `reg-to-mem` 完成、`activity-schedule` 开始前保存完整 `post_reg_to_mem.json`。C、E 两个快照各约 3.1 GiB，源操作集合都为 338,629 个。

随后从各自的 post-reg-to-mem 快照重新导出当前 source order：

- C：[order-post-C/stages/source-order.keys.txt](../../build/xs/decode_constant_investigation_20261104_v1/order-post-C/stages/source-order.keys.txt)
- E：[order-post-E/stages/source-order.keys.txt](../../build/xs/decode_constant_investigation_20261104_v1/order-post-E/stages/source-order.keys.txt)

使用同一快照导出的顺序可以通过严格 semantic-set gate，且 activity-schedule 的结构统计逐项重现。重新读 JSON 后生成的 C++ 内部文件因局部 ID 和文件分片边界变化而不逐字节相同，因此字节级 C++ gate 不能作为 post-snapshot 自身检查；结构和语义 trace 才是这里的有效 gate。

## C 使用 E 顺序的结构干预

把 E 的合法 source 顺序应用到 C 的 post-reg-to-mem 图，得到交叉变体 X。它只改变 source clone 的遍历顺序，恒零折叠、reg-to-mem、输入图和其它 activity-schedule 选项保持 C 版本。

| 指标 | C | E | X：C 图 + E 顺序 |
| --- | ---: | ---: | ---: |
| compute node | 1,069,057 | 1,067,570 | **1,067,572** |
| supernode | 63,069 | 63,083 | 63,078 |
| DAG edge | 514,414 | 515,084 | 514,869 |
| boundary activation edge | 1,933,203 | 1,932,742 | 1,932,734 |
| compute→compute value pair | 1,671,570 | 1,671,112 | 1,671,104 |
| 生成调度函数数 | 321 | 297 | 290 |
| 调度 C++ 源码字节 | 1,230,631,909 | 1,230,156,718 | 1,228,574,543 |

C 的额外 1,487 个 compute node 在顺序干预后只剩 2 个相对 E 的差异，说明 source 遍历顺序确实是节点膨胀和共享归属扩散的直接结构因素。对 E/X 的 stage diff 中，公共共享决策 691,064 项相同，仅 2 项已可靠对齐的决策不同；X 的结构大部分回到 E 侧。

## 动态计数和功能

X 的独立计数二进制与 E 的两组 100,000 周期 trace 逐字节一致。X 相对 C 的计数变化为：

| 计数 | X 相对 C |
| --- | ---: |
| supernode fire | −0.392% |
| 结果/宽值检查 | −0.429% |
| 变化结果 | −0.015% |
| 活动写入语句 | −1.080% |
| 新增活动位 | −0.357% |
| batch 调用 | −2.104% |
| 空 batch 调用 | −2.598% |

X 与 E 的变化检查次数相差不到 0.025%，活动写入少约 0.054%，但 X 的 supernode fire 仍比 E 多约 0.193%。这解释了为什么结构恢复没有直接转化为同等比例的 walltime 收益：调用/节点数量已经接近 E，剩余执行成本还受 supernode 组成、代码布局和 batch 内部形态影响。

## 单线程 walltime

X 与 E 使用相同 NUMA、CPU96、私有 runtime、smoke/warmup 和交替顺序完成 8 对 C100000；两组 trace、Difftest、线程亲和性和页面归属均通过。

| 指标 | X 相对 E |
| --- | ---: |
| 平均配对变化 | **−0.270%** |
| 中位配对变化 | +0.114% |
| 固定种子配对 bootstrap 95% 区间 | [−1.166%, +0.491%] |
| X 更快 | 3/8 |

因此 source-order 是已确认的结构因果因素，但不是当前整机回退的唯一性能因素。X 的 walltime 区间跨零，不能把这次干预写成稳定加速；诊断计数本身使用了插桩 binary，不用于 walltime。

产物：[结构汇总](../../build/xs/decode_constant_investigation_20261104_v1/cross-structural-summary.json)、[stage diff](../../build/xs/decode_constant_investigation_20261104_v1/cross-stage-diff/stage_diff.json)、[walltime JSON](../../build/xs/decode_constant_investigation_20261104_v1/cross-walltime-summary.json)、[walltime CSV](../../build/xs/decode_constant_investigation_20261104_v1/cross-walltime-results.csv)、[X 动态 trace 检查](../../build/xs/decode_constant_investigation_20261104_v1/cross-counts-trace-summary.json)。

## 下一步定位

当前最有价值的细化是对 E 顺序做分段干预：按 source order 的变化区间二分，只保留一段 E 顺序、其余位置使用 C 顺序；每次只检查 compute-node、shared-owner、动态计数和代码大小。这样可以把 1,487 个额外节点归因到具体的 source 区间，再将该区间映射回 DecodeUnitComp 及其跨模块消费者。随后针对仍多出的 supernode fire 和 batch 内部代码形态做 PMU/IP 对照，区分调度调用数、函数体成本和地址布局的贡献。

