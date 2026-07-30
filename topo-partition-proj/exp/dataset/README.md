# dataset — topo-partition-proj 实验数据

Phase 0 起，一切实验（采样/打分/搜索/训练）的唯一图输入来自这里。格式说明见
`docs/05-图导出实现记录.md` 与 `wolvrix/docs/grhsim/grhsim-am-pipeline.md` §3.2.4。

## 目录

| 路径 | 内容 | 大小 |
|---|---|---|
| `xs_full_20260730/instruction_graph.jsonl` | 全香山 AM 指令图导出（格式 `wolvrix.am-instruction-graph.v1`） | 1.44 GB，14,954,654 行 |
| `xs_full_20260730/block_assignment.jsonl` | 生产调度 plain 基线解（格式 `wolvrix.am-block-assignment.v1`，header 含对账指标） | 233 MB，4,703,732 行 |
| `xs_full_20260730/lower_json.log` | 导出当次 lower-json 运行日志（统计与耗时，溯源用） | 2.4 KB |
| `examples/tiny_graph.jsonl` | 7 指令手工小程序的导出样例（导出器单测产物），供读图代码做格式冒烟 | 17 行 |

基线锚点（详见 `docs/06-基线解导出与对账.md`）：plain 基线 34,236 blocks
（33,738 compute + 497 commit + 1 input sink），`dag_edges=325,838`，
`compute_compute_value_pairs=3,305,393`，cost（`incoming_copy_cost`）= **6,468,546**。
三项指标已经 `exp/tools/reconcile_baseline.py` 独立复算对账一致；对任意新划分
用同一脚本对账：

```bash
python3 exp/tools/reconcile_baseline.py \
    exp/dataset/xs_full_20260730/instruction_graph.jsonl \
    exp/dataset/xs_full_20260730/block_assignment.jsonl
```

## `xs_full_20260730` 溯源

- 输入：`build/xs/grhsim-am-detgroup/wolvrix_xs_post_stats.json`（top = SimTop）。
- 计数：4,669,495 节点 / 4,803,814 变量 / 8,031,598 def_use 边 / 2,234,514
  external_read / 19,046 order 边；`comb_loop_atoms = 0`。
- 校验：行数与 header 计数一致；抽样 JSON 解析合法；def_use + order 边 Kahn 全排
  成拓扑序（图为 DAG）。
- 重新生成（wolvrix 含导出器，环境变量触发）：

```bash
WOLVRIX_GRHSIM_AM_INSTRUCTION_GRAPH_JSONL=$PWD/instruction_graph.jsonl \
    wolvrix/build/bin/grhsim-am-lower-json \
    build/xs/grhsim-am-detgroup/wolvrix_xs_post_stats.json SimTop --schedule
```

## 版本管理

香山 RTL 或 wolvrix lowering/调度语义改版后，旧导出即过期（风险登记 R6）：重跑上面的
命令，另建 `xs_full_<date>/` 目录存放，不覆盖旧目录；harness 消费时在配置里写死所用
数据目录名。
