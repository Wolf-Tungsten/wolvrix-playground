# TNO0322: XiangShan counter-print fresh-ingest control gate

日期：2026-09-15

状态：`CONTROL REPRODUCES FROZEN ASC EXACTLY`。

## 1. 范围和身份

按 [TNO0318](./TNO0318_xiangshan_counter_print_regeneration_plan_20260915.md)，仅将原始
`build/xs/rtl/rtl` 重新导入，尚不是旧 Scala 的新 elaboration control。
完整结果在 `build/asc_counter_print_20260915/control_ingest_v1/`。

执行相同 `scripts/wolvrix_xs_emit.py` 与 pass 顺序；安装库 SHA：
`a97bb01351df3ed0a4b84a657435eb07c6cda9624ee202ce2b0258ae6aa65ac7`。
ASC 使用冻结 overlay_v1，SHA：`44e8f043137f5711bc34bdc6c1033482771cdabc07c19f4f76ba96768e816a48`。
arm O，无 selector/write-pack 改写；phase A/B/C 全部 guard 通过，在 solver/phase E 前返回。

新 control GRH SHA：`5de21ed7ea9fabe1c457608cc05de6f9be0ba4bb5f8f48c8ddc0c8a87bfa751a`，
3,427,741,408 bytes。它不与冻结 GRH 字节相同；下列结构一致性直接由完整 TSV 核验，
不依赖相同文件 SHA 的假设。

## 2. 冻结基线复现

| 指标 | 原冻结 O | 本轮 fresh ingest control |
| --- | ---: | ---: |
| nodes | 5,826,569 | 5,826,569 |
| pieces | 1,327,211 | 1,327,211 |
| hyperedges | 303,108 | 303,108 |
| sinks | 329,697 | 329,697 |
| ASCs | 301,172 | 301,172 |
| max sinks | 26,852 | 26,852 |
| max comb entries | 464,601 | 464,601 |
| max full closure weight | 1,115,421 | 1,115,421 |
| referenced unique weight | 12,450,769 | 12,450,769 |

双方完整 `asc_table.tsv`、`memory_symbol_to_asc.tsv`、`state_sink_to_asc.tsv` 均经 cmp
逐字节相同，包含全部844个memory symbol及其归属，而不只是 giant 的429个成员。
最大 ASC4 的端点种类、logEndpoint 中2,384个寄存器 writer 等也完全复现。

比较脚本 `build/asc_counter_print_20260915/compare_asc.py`；O 对自身 selftest 全零差；
本轮与冻结结果在 `control_vs_frozen_v1.json`。显式 `--expect-xs-baseline` gate 通过，
两个 run.json 均 status pass。

## 3. 资源与结论边界

node029，nice10，初始CPU160–167。12:08按1秒CPU快照扩展自身统计线程的affinity至
`160-170,172-173,175-178,181-182,186,188-189,191`；未调整其他作业。
这是生成/统计任务，不是性能实验。导入约1753s，含全图 stats；总流程约1959.5s。

该结果排除了“当前 ingest/RepCut 不能重现旧输入”的疑问；不能替代 elaboration 差异审计，
后者见 [TNO0321](./TNO0321_xiangshan_counter_print_rtl_semantic_audit_20260915.md)。
候选的 memory 组件拆分和最大 closure 结果应另文记录，不由控制组先行推断。
