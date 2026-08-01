# 15 GrhSIM AM 与 GSim（打平）DAG 规模对比（2026-07-31）


基于两份 topo-proj 导出的同口径对比。图导出与映射见
[`14-gsim打平图与两段assignment导出`](14-gsim打平图与两段assignment导出.md)；
打平实验见 [`12-gsim-node打平实验设计与实现`](12-gsim-node打平实验设计与实现.md)
/ [`13-gsim-node打平coremark50k对比`](13-gsim-node打平coremark50k对比.md)。

## 数据集

- grhsim AM：`topo-partition-proj/exp/dataset/xs_full_20260730/`
  （`grhsim-am-lower-json` 输入 SimTop post-stats JSON，2026-07-30）。
- gsim 打平：`topo-partition-proj/exp/dataset/xs_gsim_flatten_20260731/`
  （`--flatten-nodes --supernode-max-size=16`，输入 2026-07-03 的 SimTop.fir）。

## 对比表

| 指标 | grhsim AM | gsim 打平 | gsim / AM |
| --- | ---: | ---: | ---: |
| instructions（图节点/指令） | 4,669,495 | 3,043,902 | 0.65 |
| variables | 4,803,814 | 3,046,176（含 2,274 mem 合成变量） | 0.63 |
| def_use 边 | 8,031,598 | 4,340,605 | 0.54 |
| external_read | 2,234,514 | 918,456 | 0.41 |
| order 边 | 19,046 | 5,719,920 | ~300x |
| state_write 节点 | 218,990 | 151,190 | 0.69 |
| 节点 width 总和 / 均值 | 57,320,592 / 12.3 bit | 32,094,103 / 10.5 bit | 0.56 |
| def_use 边 / 节点 | 1.72 | 1.43 | — |
| comb_loop_atoms | 0 | 0 | — |
| blocks（最终划分） | 34,236（33,738 compute + 497 commit + 1 sink） | 286,748（coarsen）→ 84,901（DP） | 2.48x |
| dag_edges（def_use 跨块去重） | 325,838 | 641,213（coarsen）→ 436,787（DP） | 1.34 |
| compute_compute_value_pairs | 3,305,393 | 1,460,695（coarsen）→ 1,295,427（DP） | 0.39 |
| incoming_copy_cost | 6,468,546 | 1,472,037（coarsen）→ 1,306,149（DP） | 0.20 |

## 解读

1. **图规模**：gsim 打平后的图仍比 AM 小一圈（节点 0.65x、def_use 边
   0.54x、width 总量 0.56x）。AM 的指令粒度比"每节点一个算子"的打平
   gsim 更细，且 external_read 多 2.4 倍。两条 IR 路线（SV ingest vs
   FIR）产生的图不同构，规模差异不全是粒度能解释的。
2. **划分规模**：gsim DP 后 84,901 blocks vs AM 34,236 blocks——gsim
   块数多 2.5 倍、每块更小（约 36 vs 136 节点/块）。
3. **划分质量**：AM 的 `incoming_copy_cost` 是 gsim DP 的 **4.95 倍**
   （6,468,546 vs 1,306,149），value pairs 2.55 倍。即使把 gsim 打到
   单算子粒度，其 coarsen+DP 产出的划分在该 activity 成本上仍远优于
   AM plain 基线——再次印证 [`13`](13-gsim-node打平coremark50k对比.md) 结论：差距不来自 node 层次。
4. **dag_edges**：gsim DP 436,787 vs AM 325,838（1.34x）：gsim 块数多
   2.5 倍而块间边只多 34%，块间耦合更低。
5. **order 边**：gsim 5.72M（异步复位 dep 扇出 + 存储端口顺序）vs AM
   19,046，语义不同，不可比。

## 备注

- DP assignment 的 84,901 比最终发射的 84,754 多 147，是发射端丢弃
  insts 为空的 super 所致。
- 两份输入同为 XiangShan SimTop，但 IR 路径与生成日期不同
  （post-stats JSON 2026-07-30 vs SimTop.fir 2026-07-03），
  节点级一一对应不可预期；本表只用于规模与划分质量的同口径对比。
