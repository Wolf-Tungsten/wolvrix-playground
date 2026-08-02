# ir-scale：IR 规模优化（AM vs gsim op 数对齐）

专题目标：解释并缩小 AM（grhsim array/memory 化图）与 gsim 打平图之间的图结构规模差距，主口径为可比 compute-op（定义见 [NO0008](NO0008_t5口径清算表_20260731.md)）。

## 线性记录索引

| 编号 | 记录 | 日期 | 内容 | 原 topo-partition-proj/docs 编号 |
|---|---|---|---|---|
| NO0001 | [am与gsim打平dag规模对比](NO0001_am与gsim打平dag规模对比_20260731.md) | 2026-07-31 | AM 图 vs gsim 打平图同口径规模对比：gsim 节点 0.65x / def_use 0.54x；AM incoming_copy_cost 是 gsim DP 的 4.95 倍 | 15 |
| NO0002 | [同一规范化dp下am与gsim打平cost对比](NO0002_同一规范化dp下am与gsim打平cost对比_20260731.md) | 2026-07-31 | 同一规范化 DP：AM 图 cost 4.55x——差距来自图本身性质 | 16 |
| NO0003 | [am多出op的归因与验证计划](NO0003_am多出op的归因与验证计划_20260731.md) | 2026-07-31 | 图结构优势归因第一刀：节点差 84% 是 logic 族；H1 等假设与 T1–T6 验证计划 | 18 |
| NO0004 | [gsim逐pass算子贡献与am死代码验证](NO0004_gsim逐pass算子贡献与am死代码验证_20260731.md) | 2026-07-31 | T1：gsim 逐阶段 dump——logic 精简主力是 DCE+常量分析；AM 图实测 72.9 万死指令 | 19 |
| NO0005 | [t2两级优化实施文档](NO0005_t2两级优化实施文档_20260731.md) | 2026-07-31 | T2：GRH 层 simplify + AM 层 DCE/fold/CSE——logic 差 +1.37M→+871,433，50k difftest 全过，两级终态收敛 | 20 |
| NO0006 | [t3模块级归因](NO0006_t3模块级归因_20260731.md) | 2026-07-31 | T3：模块×桶差表——87.7 万 logic 差：Rob 一族 31%、阵列/entry 类 26%、验证逻辑 5%；top-20 模块覆盖 77.3% | 21 |
| NO0007 | [t4惯用法采样比对](NO0007_t4惯用法采样比对_20260731.md) | 2026-07-31 | T4：四种惯用法带计数实锤——I1 译码树、I2 SV 布尔表示层（35.2 万 AM-only）、I3 decode or-of-eq、I4 entry×条件 guard 复制 | 22 |
| NO0008 | [t5口径清算表](NO0008_t5口径清算表_20260731.md) | 2026-07-31 | T5：三层清算——可比 compute-op 口径 AM 为 gsim 1.21x（+602,060），logic 差 98% 是惯用法；净 cost 差 4.21x 乘数链 | 23 |
| NO0009 | [i2布尔归一化与i1译码树重写](NO0009_i2布尔归一化与i1译码树重写_20260731.md) | 2026-07-31 | I2/I1：logic-normalize + onehot-to-mux 落地，探针合计 −31,256（0.71%）——便宜重写路线耗尽，剩余 logic 差是阵列形态 | 24 |
| NO0010 | [数组语义路线终局](NO0010_数组语义路线终局_20260731.md) | 2026-07-31 | 数组/向量语义路线终局：consolidated matcher 对香山 guard 语言证伪；诊断资产固化 | 25 |
| NO0011 | [p0数组盘点](NO0011_p0数组盘点_20260801.md) | 2026-08-01 | P0 数组盘点：E1 簇存量、robEntries guard 形态分类、reset 形态；决策门 GO（v4 901,408 ops） | 27 |
| NO0012 | [logperf核查与memory-op语义备忘](NO0012_logperf核查与memory-op语义备忘_20260801.md) | 2026-08-01 | LogPerf"快赢"证伪：gsim 完整保留 LogPerfEndpoint；删模块是行为变更型可选项（默认不做）；备忘 kMemoryWritePort mask/priority 语义 | 28 |
| NO0013 | [路线重锚-爆炸发生在firtool](NO0013_路线重锚-爆炸发生在firtool_20260801.md) | 2026-08-01 | 逐 entry 爆炸发生在 firtool；原 P1 落空，替代路线 R-A/R-B（推荐）/R-C；wflags 同构实证 | 29 |
| NO0014 | [rb-lane重向量化pass设计草案](NO0014_rb-lane重向量化pass设计草案_20260801.md) | 2026-08-01 | R-B lane-aggregate 设计：名字分组+同构签名+常量 lane 参数化+masked 宽写；决策门 v4 可省 901,408 ops | 30 |
| NO0015 | [lane-aggregate实施与验收](NO0015_lane-aggregate实施与验收_20260801.md) | 2026-08-01 | lane-aggregate 落地：合并 275 组/24,364 lane，compute 3,429,884→3,278,538（−151,346，1.1653x），difftest/ctest 双过；≤1.10x 在本路线不可达论证 | 31 |
| NO0016 | [am与gsim剩余差距拆解](NO0016_am与gsim剩余差距拆解_20260801.md) | 2026-08-01 | 1.0x 完全对齐场景：剩余 465,007 compute-op 的正负项结构、logic +75.1 万三分解剖、可消除性分类——结构性地板兜底，1.0x 需数组 value/when 区域级 IR 语义 | —（本专题首篇原生记录） |

## 备注

- NO0001–NO0015 于 2026-08-01 自 `topo-partition-proj/docs/` 迁入（git mv，仅移动未改正文）；正文中的"doc NN"式引用以上表"原编号"列为准。
- 与分区/调度主题相关的文档（原 01–14、17、26）仍留在 `topo-partition-proj/docs/`。
