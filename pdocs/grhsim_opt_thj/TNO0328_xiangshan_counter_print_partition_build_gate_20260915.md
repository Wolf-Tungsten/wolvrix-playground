# TNO0328: XiangShan counter-print partition build gate

日期：2026-09-15

状态：`PASS; BOTH FRESH K32 BUILDS READY FOR HOST CAPTURE`。

## 1. 构建结果

接 [TNO0325计划](./TNO0325_xiangshan_counter_print_host_ab_ba_plan_20260915.md)、
[TNO0326源码补充gate](./TNO0326_xiangshan_counter_print_build_provenance_supplement_20260915.md)、
[TNO0327资源诊断](./TNO0327_xiangshan_counter_print_build_resource_diagnosis_20260915.md)。
本轮根目录`build/asc_counter_host_20260915/`。A/B分别为原next_counter打印与counter打印，
均为fresh ingest、K32同参数重新分区、空缓存全部模型编译。

| 项目 | A_v1 | B_v1 |
| --- | ---: | ---: |
| 构建节点 | node031 | node039 |
| 完成时间（北京时间） | 13:45:55 | 13:30:41 |
| native构建时间（s，非Host） | 338.5211 | 332.6132 |
| partition object数 | 1,422 | 1,384 |
| archive数 | 32 | 32 |
| reused partition objects | 0 | 0 |
| ELF字节 | 270,067,520 | 257,047,840 |

两臂均`status=pass`、legacy/push、identity mapping；工具链对象完全相同、Clang21.1.5，
wrapper无新增优化flag，生成端口存储匹配SV，stage与上游输入身份未改变。
同一冻结stage4 builder与runtime-v1模板，未使用历史模型archive。

ELF SHA256：

- A：`61d82303cda24decbc36d6c76a0b5558fdc11dff7247cdedb0436f4c3e84593e`
- B：`12bef2ec48ea8469e6c4f26ae2922da2ae8fc4b708650c3636d518cc716158a1`

`build/build-manifest.json` SHA256：

- A：`1f73e7dcf0ae6bc04200f5cdbc6636e34421da5f5e68619a605af19875407ee3`
- B：`cefb73ab287bc8052d31cfd15932a8eacf15ef30110357f837d9a9e5a2ac9bd7`

两次构建完成后、启动测量前，`source_gate.py --verify`及`--verilator`均通过，
保留`native-source-premeasure.json`（117份）和`verilator-source-premeasure.json`（64份）。
冻结builder单元测试13项、measurement单元测试35项通过。

## 2. 重建图与通信copy

可复核输入为两臂`emit.json`及`build/build-plan.json`；汇总
`structure-comparison-v2.json`保留输入SHA和每个partition的明细。

| 指标 | A | B | B/A−1 |
| --- | ---: | ---: | ---: |
| 重建全部partition ops | 6,506,503 | 6,188,556 | −4.8866% |
| 最大partition ops | 608,762（part_8） | 447,447（part_7） | −26.4989% |
| exact closure load总和 | 13,498,964 | 13,052,827 | −3.3050% |
| exact closure load最大值 | 1,115,421 | 883,100 | −20.8281% |
| 重复计算权重compute km1 | 1,048,195 | 611,369 | −41.6741% |
| communication proxy km1 | 22,306,433 | 14,727,190 | −33.9778% |
| endpoint复制项 | 5,137 | 4,836 | −5.8595% |
| 每次update存储复制字节 | 449,729 | 441,866 | −1.7484% |

`op_partition_stats`和`partition_graph_stats`都是最终重建图operation计数，源码
`repcut.cpp`直接取`part.graph->operations().size()`；phase-E日志`source_ops`仅为
克隆来源集合，未包括新建边界操作，不能混合两个口径比较。
初版`structure-comparison.json`数值无误，但附注曾错误称前者为重建前估计；v2仅纠正
此附注并加入两处统计一致性assert，保留初版不覆盖。跨臂partition编号不表示相同逻辑。

复制字节是生成C++中一次完整update的静态存储量，不是实测总线流量；proxy下降33.98%
也不能解释成通信时间下降33.98%。Host结果单独归档，不由本节静态比例推断。

## 3. 测量输入冻结

`spec.json` SHA256：`f8e6f49601cc8471eb1c8d7571d4279da8c961e6fcf8a6a44eabd93a0772c40e`。
N=K=32、legacy/push、C100 canary后C10000、AB后BA；runtime-config必须存在。
不改变测量门槛，也不将本次breaking打印行为或分区模型设为生产默认。
