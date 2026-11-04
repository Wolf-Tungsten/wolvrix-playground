# TNO0430 译码表恒定折叠后的 source-order 顺序扫描

本轮先固定译码表实验的生产配置，再从 E（CSR 开启、恒定表折叠关闭）的合法 post-reg-to-mem 快照开始探索遍历顺序。恒定折叠和前端图保持不变，顺序只通过 `WOLVRIX_RESEARCH_SOURCE_ORDER` 改变 activity-schedule 的 source clone 遍历。

## 配置提交

`decode-table` 默认同时启用 utility 译码表（包括 CSR 权限表）和可证明恒定输出的 `kDecodeTable` 折叠。单线程 runner 记录 `constant_decode_fold`，CSR-only 消融显式传 `False`；后端支持新的 `WOLVRIX_FOLD_CONSTANT_DECODE`，并兼容旧的 research 变量。utility、XiangShan、Wolvrix 和根仓库已分别提交，根提交为 `cff5267`。

## 结构扫描

输入是 E 的 post-reg-to-mem snapshot，338,629 个 source。四种顺序都通过严格 source-set replay gate：原观察顺序、字典序、逆字典序、固定种子 `0x0429` 随机序。

| 顺序 | compute node | supernode | DAG edge | boundary activation edge | compute→compute value pair |
|---|---:|---:|---:|---:|---:|
| 原观察顺序 | 1,067,570 | 63,083 | 515,084 | 1,932,742 | 1,671,112 |
| 字典序 | 1,065,897 | 63,048 | 511,085 | 1,932,100 | 1,670,473 |
| 逆字典序 | 1,067,644 | 63,014 | 512,571 | 1,932,769 | 1,671,237 |
| 固定随机序 | 1,068,131 | 63,043 | 517,359 | 1,934,320 | 1,672,766 |

四种顺序的 `source_clones_in_compute_nodes=2,040,788`、`graph_ops=7,141,439` 和 `graph_values=6,770,340` 完全相同。因此顺序影响的是后端节点归属、共享合并和 DAG 形态；它没有改变前端操作数量或 clone 总量。字典序目前给出最小 compute node 和 DAG edge，随机序给出较大的 DAG edge，适合作为负面对照。

结构数据在 [`order-scan-E/structural-summary.json`](../../build/xs/decode_constant_investigation_20261104_v1/order-scan-E/structural-summary.json)，每种顺序的 replay keys 和 stage 导出也保存在同一目录。

## 初步 walltime

字典序完整生成并编译后，在 node030 CPU96、NUMA node1、单模型单线程、C100000、Difftest 开启的条件下与原 E 交替运行 4 对。两组独立 100,000 周期 trace 逐字节一致，文件页/匿名页归属、线程数和 SMT sibling 检查通过。

| 指标 | 字典序 X 相对 E |
|---|---:|
| X 更快 | 3/4 |
| 平均配对变化 | -1.080% |
| 中位配对变化 | -1.803% |
| 固定种子 bootstrap 95% 区间 | [-3.163%, +1.378%] |

这说明结构上更少的 compute node/DAG edge 可能值得继续测量，但当前 4 对样本仍跨零。不能据此宣称 source-order 已带来稳定整机加速。下一步优先对字典序做完整 8 对 AB/BA；若方向保持，再对逆字典序或一个结构差异相反的顺序做小样本对照，区分结构收益和运行状态漂移。

产物：

- [结构汇总](../../build/xs/decode_constant_investigation_20261104_v1/order-scan-E/structural-summary.json)
- [字典序 walltime 汇总](../../build/xs/decode_constant_investigation_20261104_v1/order-walltime-lex-v1/summary.json)
- [字典序 walltime 样本](../../build/xs/decode_constant_investigation_20261104_v1/order-walltime-lex-v1/pairs.json)
