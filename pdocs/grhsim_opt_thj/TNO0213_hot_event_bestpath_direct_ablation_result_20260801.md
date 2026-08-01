# TNO0213 Hot-event best-path direct ablation result

## 1. 结论

[TNO0212](./TNO0212_hot_event_bestpath_ablation_design_and_materialization_20260801.md) 预注册的八组
direct pair 已全部完成。所有正式结果都来自 fixed-ASLR、空闲 whole CCD、ABBA 与 BAAB 复用完全相同
CPU/SMT sibling/CCD/NUMA/helper CPU 的 SimTop 50k；按时间顺序采用首个 order gap `<0.25 pp`
的完整八样本轮次，不从多轮中挑收益最大者。

最终 endpoint `B→TRBS` 为：

- control `51,562.00 ms`；candidate `47,632.25 ms`；
- walltime 绝对减少 `3,929.75 ms`，相对改善 `7.621407%`；
- ABBA `+7.598548%`，BAAB `+7.644232%`，order gap `0.045683 pp`；
- control 四样本 `51,473/51,573/51,481/51,721 ms`，candidate 四样本
  `47,564/47,652/47,777/47,536 ms`；
- 全部样本 personality=`00040000`，affinity、whole-CCD quiet、NUMA、PMU 与功能审计通过。

这个 fresh endpoint 与搜索记录的 `+7.596858%` 一致，确认约 `7.6%` 提升可以在固定默认基线上复现。

## 2. 正式 direct ablation

| pair | 采用轮次 | control wall | candidate wall | 绝对变化 | 改善率 | ABBA | BAAB | gap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `B→T` | 2 | `51,333.75 ms` | `49,923.00 ms` | `−1,410.75 ms` | `+2.748192%` | `+2.827929%` | `+2.668420%` | `0.159508 pp` |
| `T→H` | 3 | `50,085.25 ms` | `48,288.00 ms` | `−1,797.25 ms` | `+3.588382%` | `+3.549717%` | `+3.627052%` | `0.077335 pp` |
| `H→HS` | 2 | `48,226.75 ms` | `47,566.50 ms` | `−660.25 ms` | `+1.369053%` | `+1.348550%` | `+1.389566%` | `0.041016 pp` |
| `HS→TRBS` | 2 | `47,629.25 ms` | `47,494.75 ms` | `−134.50 ms` | `+0.282389%` | `+0.198717%` | `+0.365801%` | `0.167084 pp` |
| `T→TR` | 3 | `49,854.50 ms` | `49,859.00 ms` | `+4.50 ms` | `−0.009026%` | `−0.007023%` | `−0.011029%` | `0.004006 pp` |
| `TR→TRB` | 1 | `50,024.75 ms` | `48,474.75 ms` | `−1,550.00 ms` | `+3.098466%` | `+3.146157%` | `+3.050827%` | `0.095330 pp` |
| `TRB→TRBS` | 1 | `48,449.75 ms` | `47,495.50 ms` | `−954.25 ms` | `+1.969566%` | `+1.942910%` | `+1.996204%` | `0.053293 pp` |
| `B→TRBS` | 1 | `51,562.00 ms` | `47,632.25 ms` | `−3,929.75 ms` | `+7.621407%` | `+7.598548%` | `+7.644232%` | `0.045683 pp` |

前三组因先前轮次 gap 超标而重测；表中只列按预注册规则选中的首个合格轮次，完整 rejected history 仍保留在
`build/grhsim_hot_event_ablation_20260801/direct_pairs_v1/summary.json`。

## 3. 来源解释

最终形态的机械分解给出最清楚的归因：

1. `T→TR` 的 hot input 选择和 typed slot-0 remap 单独为 `−0.009026%`，即运行时中性；它的主要价值是
   给后续专门化提供稳定、通用且不依赖信号名的承载位置。
2. `TR→TRB` 的 exact-posedge bool 预解码贡献 `+3.098466%`，是最终增量中最大的单项。
3. `TRB→TRBS` 的 batch-local bool snapshot 再贡献 `+1.969566%`，说明避免热点对象成员的重复读取仍有
   明确端到端价值。
4. `B→T` 的 typed direct event storage 本身贡献 `+2.748192%`；最终四段存在交互，不能把百分比机械相加，
   因此以 `B→TRBS +7.621407%` 为总收益口径。

搜索历史的 `HS` 与最终 `TRBS` 属于同一热点事件思想的两代实现，而不是可以直接叠加的独立 feature：

- `HS` 把完整 edge enum 放在 near scalar，并在 batch 内快照完整 enum；
- `TRBS` 把选中的 input event 重映射到 typed slot 0，把占主导的 exact-posedge 查询预解码为 bool，再在
  batch 内快照 bool。

因此完整 `HS` 原样叠加到 `TRBS` 会重复分类、存储和快照同一事件。理论上可以另做只服务残余
`negedge/general` 查询的 enum-cache hybrid，但它不是机械叠加，而且 SimTop 残余用途极少；若后续探索该
方向，必须作为独立 arm 重新做端到端门禁。`HS→TRBS` 仅 `+0.282389%` 也说明两者大部分收益重叠。

## 4. Endpoint PMU

`B→TRBS` 四样本均值：

| 指标 | control | candidate | 相对变化 |
| --- | ---: | ---: | ---: |
| cycles | `189,172,755,825.75` | `174,708,795,913.25` | `−7.645900%` |
| instructions | `158,921,695,764.50` | `160,551,927,660.00` | `+1.025808%` |
| frontend no-dispatch | `831,560,309,539.75` | `758,921,934,078.50` | `−8.735190%` |
| frontend no-dispatch cmask=6 | `105,781,766,249.50` | `96,295,035,675.75` | `−8.968210%` |
| backend stalls | `75,193,964,516.25` | `76,785,773,481.75` | `+2.116937%` |

walltime/cycles/frontend 同向改善，而 instructions 与 backend stalls 小幅增加；收益不是减少总指令数，而是
改善热点事件访问与前端供给。最终默认裁决仍只以 walltime 为 headline。

## 5. Build、功能与 artifact identity

六个 candidate 均完成隔离 fresh emit/O3 link，parallel build `6/6 PASS`；每个 arm 的 trusted emitter
focused、fixed-ASLR 100/10k、image/NEMU/config/toolchain/生成 fingerprint/ELF proof 均通过。final ELF 为
`91,094,720 B`、SHA-256 `afd73b8c100c89844f68930f40d8aee577dde08ed7ae4c81f504f05ca960724e`。

关键证据 SHA-256：

| artifact | SHA-256 |
| --- | --- |
| `candidates_v1/materialization_report.json` | `6aedc174073f783cd37243b88e569f9241b4e316574814577b0b18eef4bdd59d` |
| `arms_v1/parallel_build_summary.json` | `6e0515f18d30a45f76bcd688e6a4a450ab52cde8598e2a78d7afe3d1e44f513a` |
| `materialize_candidates.py` | `f32128c00e35e36466de6c492e9b202ee71d16ebe7a201dbdab474be50677962` |
| `build_parallel.py` | `e4ecc77b6fb44aa1457ff4384c7ab84a1914ad9602dc594059b02ef601805553` |
| `run_pairs_until_gap.py` | `63e6e9424b82180d18415ff8c7c69ff0b055682bb31172863c103f04ebacfa02` |

## 6. 决策与下一步

`T`、`B`、`S` 对 SimTop 50k 均有明确正收益，组合 endpoint 可信，因此进入 Wolvrix 通用默认落地。
`R` 不作为独立性能优化宣传，但作为 bool 专门化的表示依赖保留。落地时不保留搜索 patch 中
`eventEdgeSlotCount >= 256` 的裸规模阈值，而改为按每个 input event 的 exact-posedge uses 与其覆盖的最终
schedule batches 估算可复用工作；只在复用收益超过一次分类/store/clear 固定成本时启用。该 gate 不读取
端口名、ValueId、SimTop 类型或 benchmark 特征，旧/新 gate 还需 fresh 功能和 50k direct 对比。
