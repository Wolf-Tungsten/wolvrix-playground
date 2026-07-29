# SimpleTES K3/GPT post-RWA research completion

## 1. 阶段结论

[`TNO0193`](./TNO0193_simpletes_k3_grounded_fresh_research_launch_20260728.md)
启动的 post-RWA auto-research 已于 `2026-07-29 14:37:02 +0800` 自然结束。
最终 GPT launcher 返回 `0`，停止原因是累计 `64` 次 generation attempt 达到上限，
不是 `32` 个 valid candidate 已满。

最终状态为：

| 项目 | 绝对值 |
| --- | ---: |
| completed evaluations（含 initial control） | `20` |
| generated candidate evaluations | `19` |
| valid candidates | `15 / 32` |
| generation attempts | `64` |
| generation failures | `33` |
| generation cancellations | `3` |
| evaluation failures | `0` |
| best node | `f6ab710e65034a3db2bdd9a097242af2` |
| best score | `1.042845084360962` |

15 个 valid candidate 的正式 SimTop 50k walltime 均为正收益；相对提升范围为
`0.981940%..4.108480%`，中位数为 `3.304558%`。最终 best 的同批 pooled
绝对值为 control `53,742.50 ms`、candidate `51,534.50 ms`，减少
`2,208.00 ms/4.108480%`。这是对已默认落地 R/W/A 的当前 Wolvrix 基线的新增收益，
不是相对更早 pre-RWA 基线的总收益。

## 2. K3 与 GPT 两阶段

K3 首条 generation 曾因错误的 `272000` context 上限运行 `4,053 s` 后人工停止；
[`TNO0195`](./TNO0195_simpletes_k3_context_window_correction_and_resume_20260728.md)
完成 `1M` 更正，
[`TNO0196`](./TNO0196_simpletes_k3_parallel_generation_subagents_and_context_catalog_20260728.md)
随后启用 K3-only 4 路 generation、最多 3 个 subagent 和 `10800 s` timeout。

切换 GPT 前的 `db_state_153501` 有 `18` attempts、`6` completed evaluations、
`3` valid。K3 最好节点 `b227fe4e` 的 walltime 为
`54,304.75→53,367.25 ms`，减少 `937.50 ms/1.726368%`。其主要机制为
standalone SystemTask/`xs_assert_v2` 冷路径提示及一组小规模宽值 helper
`always_inline`。

[`TNO0198`](./TNO0198_simpletes_gpt56sol_thj_switch_and_resume_preflight_20260728.md)
从该 exact checkpoint 切换到 `gpt-5.6-sol/ultra`。GPT 阶段新增 `12` 个 valid
candidate，将 best 从 `1.726368%` 推进至 `4.108480%`，增加
`2.382112` 个百分点。该差值只描述连续探索结果；GPT 继承了 K3 搜索树，不能据此
视作受控的模型能力 A/B。

## 3. 主要正向方向

以下百分比都是各完整候选相对其同批 control 的总收益，不是可直接相加的独立边际值。

| 方向 | 代表节点 | control→candidate | 绝对/相对收益 |
| --- | --- | ---: | ---: |
| assertion/SystemTask 冷路径与宽值 helper 内联 | `b227fe4e` | `54,304.75→53,367.25 ms` | `937.50 ms/1.726368%` |
| 常量 MemoryRead row 证明并移除 always-in-range 临时清零 | `baea6aed` | `53,599.50→51,791.75 ms` | `1,807.75 ms/3.372699%` |
| MemoryRead OOB 冷分支布局 | `c54b88f5` | `53,782.25→52,139.00 ms` | `1,643.25 ms/3.055376%` |
| lockstep commit reader activation union/dedup | `82707d99` | `53,648.25→51,657.75 ms` | `1,990.50 ms/3.710279%` |
| shift/index OOB 冷分支布局 | `96504988` | `53,721.25→51,946.00 ms` | `1,775.25 ms/3.304558%` |
| 小内存 physical zero-tail | `79163a2b` | `53,702.75→51,734.50 ms` | `1,968.25 ms/3.665082%` |
| 常量 MemoryRead 加 shift/index 冷路径最终组合 | `f6ab710e` | `53,742.50→51,534.50 ms` | `2,208.00 ms/4.108480%` |

静态/动态诊断还给出以下支持证据：

- lockstep activation union 将预计 reader-mask RMW 从 `13,893` 降至 `5,257`，
  减少 `8,636/62.161%`；
- physical zero-tail 增加 `4,024 B` 状态，预计消除 `8,875` 个检查和
  `6,186,420` 次动态执行；
- 常量 row 证明预计移除 `4,487` 个 statement guard、`35,643` 个 scalar
  ternary 和 `33,767` 个 zero-before-load 序列；
- 五处 shift/index cold annotation 覆盖 `14,165` 个静态生成位置，归档计数投影
  至少执行 `111,922,959` 次。

最终 best 只包含 assertion/helper、常量 MemoryRead、redundant-zero 消除与五处
shift/index cold annotation。lockstep activation union 和 physical zero-tail 是独立
正向旁支，不属于最终 `4.108480%`，后续仍需分别消融并尝试组合。

## 4. 门禁与失败审计

所有 valid candidate 都走默认生成路径、`enable_options=[]`，仅修改
`wolvrix/lib/emit/grhsim_cpp.cpp`，并通过 build、功能、fixed-ASLR、quiet CCD、
CPU affinity、NUMA、PMU 和 ABBA/BAAB 双 order evaluator 门禁。最终
`evaluation_failures=0`。19 个已评估生成候选中另有 4 个因 malformed 或不能应用的
patch 被确定性拒绝，没有进入 walltime 结论。

generation 侧累计 `33` 次失败和 `3` 次取消。最终 `failure.json` 持久化了 `31` 条
详细记录，主要可确认的原因包括 websocket `401 Unauthorized` burst、Codex
collaboration thread/agent 错误和一次 `5400 s` timeout；其余部分记录只保留了有界
process tail，不能把 PATH alias warning 一概视为根因。计数与详细记录相差 2 条，来自
跨强制中断恢复和错误持久化功能启用时点，不影响 node/score 或 evaluator 结果。

## 5. 可复现状态与保留边界

最终 exact state 为：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
k3_rwa_grounded_fresh_20260728_032742/2026-07-28/
instance-7291c6c2/db_state_143702
```

`best_program.txt` 的本次实际 SHA-256 为
`40bd190a5ccc4e97cdb3d7ff39c819a08c4114bb264756f1dcae4beca5c43c12`。
本阶段结果仍是 SimpleTES research candidate，尚未提取、消融、应用到 Wolvrix 或决定
默认启用。后续落地必须继续以 fresh SimTop 50k walltime 和功能回归为最终裁决，不能仅凭
该搜索内的 stacked best 直接保留全部修改。
