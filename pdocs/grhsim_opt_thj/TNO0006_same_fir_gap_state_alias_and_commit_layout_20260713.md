# TNO0006 Same-FIR gap, state alias, and commit layout

记录日期：2026-07-13

来源范围：`NO0281..NO0290`，原始记录见 [NO0281](../grhsim_opt/NO0281_same_fir_gsim_grhsim_frontend_counter_compare_20260711.md) 至 [NO0290](../grhsim_opt/NO0290_rename_table_write_only_fresh_regression_20260711.md)。

状态：state-read alias 与 commit branch layout 取得小幅收益；RenameTable write-only true-merge 语义正确但结构爆炸，未进入 runtime 保留。

## 1. Same-FIR 剩余差距

在当时同 FIR 50k 口径下：

```text
GrhSIM / GSim cycles        2.672x
GrhSIM / GSim instructions  2.378x
extra instructions 对 excess cycles 的解释比例 82.43%
```

GrhSIM frontend stall density并未更差，backend stall slots/cycle 为 GSim 的 `1.639x`。instruction profile 将 87.32% host instructions 归到 compute，compute8 的 timer/logEndpoint state-read fanout 占其 samples 74.69%。

## 2. State-read slot alias

同一 compute supernode、同一 state 的 scalar read results 共用物化槽，共合并 35,745 个 slots，其中 sched8 占 29,197。

```text
instructions  -0.86%
cycles        -0.73%
Host time     -0.72%
```

进一步把 alias fanout 合并到 canonical 的 probe 虽大幅缩短源码，但 object 几乎不变且 cycles `+0.52%`，因此撤回，只保留 slot alias。

## 3. Commit changed-path layout

cycles profile 显示部分 commit batch 的热点落在“state 相等则跳过”的 `je`。给 register/latch changed 条件增加 `unlikely` 后，无变化路径成为 fall-through：

```text
Host time / cycles  -1.67% / -1.60%
instructions        +0.026%
commit cycle samples -4.42%
```

尽管 `.text +0.97%`，runtime 收益稳定，因此保留。

## 4. RenameTable write-only recovery 的失败

RAT shadow tables 在 GrhSIM 中保留 48,313 个 `wen && addr == row` 判断，而 GSim 使用 3 组 next array 与 1,560 indexed writes。新增 write-side discovery 后成功恢复 fp/int/vecRat 95 rows 为 3 个 memory groups，10k/50k 功能正确。

但显式 pairwise priority-conflict lowering 造成近二次网络：

```text
generated C++       +13.30%
emu text            +17.55%
compute supernodes  +21.90%
reg-to-mem build     54s -> 152s
```

## 5. 阶段结论

state alias 与 branch hint 是可保留的小优化；RenameTable 证明 write-only array recovery 的方向正确，但 pairwise conflict 表达不具备可扩展性。下一阶段必须引入线性 ordered-write contract。

## 6. 规则审计与关键数据

记录类型：same-FIR 下一层 root-cause 总结。单一议题边界是“array true-merge 后，剩余指令差距能否由 state-read alias、commit layout 和 write-only RAT 恢复解释”。三项依次来自 profile 热点收敛；新的恢复机制不得继续追加到本篇。

### 6.1 Same-FIR 锚点

CPU138、CoreMark `-C 50000` 对照均完成 `50001` guest cycles：

| Simulator | `instrCnt/cycleCnt` | Host ms | Host cycles | Host instructions |
| --- | ---: | ---: | ---: | ---: |
| GSim | `73584/49998` | 31,137 | 113,989,494,480 | 80,071,216,791 |
| GrhSIM | `73580/49996` | 83,237 | 304,592,107,755 | 190,436,311,216 |
| GrhSIM/GSim | - | `2.673x` | `2.672x` | `2.378x` |

额外 instructions 按 GSim CPI 折算可解释 `82.43%` excess cycles；两边 terminal PC 分别为 `0x8000131e/0x80001312`。该轮尚未固定 PIE load base，后续 fixed-ASLR 校准见 [TNO0010](./TNO0010_code_layout_aslr_and_fixed_profile_20260713.md)。

### 6.2 两个可保留小优化

| Gate | Baseline A/B/A host ms | Candidate host ms | Baseline mean cycles | Candidate cycles | Result |
| --- | --- | ---: | ---: | ---: | --- |
| state-read slot alias | `83,233 / 83,159` | 82,597 | 304,529,003,767 | 302,315,977,644 | cycles `-0.73%`, instr `-0.86%` |
| commit changed `unlikely` | `82,325 / 82,290` | 80,934 | 301,732,809,376 | 296,899,700,806 | cycles `-1.60%`, instr `+0.026%` |

两轮都达到 GrhSIM 50k 功能终点。slot alias 合并 `35,745` 个物化槽；changed hint 的 baseline host-time spread 仅 `0.043%`，且 commit fixed-period samples aggregate 下降 `4.42%`。RAT write-only fresh 10k/50k 虽功能正确，但 source/text/supernodes 分别增加 `13.30%/17.55%/21.90%`，因此没有进入 runtime gate。详见 [NO0283](../grhsim_opt/NO0283_same_supernode_state_read_slot_alias_20260711.md)、[NO0287](../grhsim_opt/NO0287_commit_state_change_unlikely_50k_gate_20260711.md) 和 [NO0290](../grhsim_opt/NO0290_rename_table_write_only_fresh_regression_20260711.md)。
