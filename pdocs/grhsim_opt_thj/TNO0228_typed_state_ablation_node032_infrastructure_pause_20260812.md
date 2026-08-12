# TNO0228：typed-state 最优路径消融在 node032 的负载阻断与暂停

日期：2026-08-12

## 1. 状态与结论

按 [TNO0227](./TNO0227_typed_state_bestpath_ablation_design_and_materialization_20260812.md)
的协议，本轮在 `node032` 只推进了 `B -> S8`（typed persistent-state layout、bool 仍为 byte）这一
第一项相邻消融。用户要求在服务器负载不理想时停止，因此已停止所有本轮运行器、emu 和监控进程。

当前结论是 **暂停，尚无可采纳的性能结果**：

- `B -> S8` 没有完成任何一轮同 CCD 的 ABBA+BAAB 配对，`summary.json` 的 `selected` 全部为
  `null`，`order gap` 没有定义。
- 少数只完成 ABBA 的数值不是结果。它们随后在 BAAB 的 pre-gate 或 workload gate 失败，不能用
  pooled walltime 推断收益，也不用于默认开关裁决。
- `S8 -> SB`、`SB -> SBV` 和 `B -> SBV` 尚未运行；没有修改 Wolvrix 默认，也没有启动或修改
  SimpleTES 研究状态。

后续在更安静的时间窗口恢复时，应直接复用本记录中的 `arms_v2` 产物，不需要重新构建；恢复仍须
source `env.sh`、关闭 ASLR，并按 TNO0227 的同 CCD、ABBA/BAAB、`gap < 0.25 pp` 协议执行。

## 2. 已完成的构建与身份

构建根目录（实验目录被 `.gitignore` 忽略，但保留在工作区）为：

```text
build/grhsim_typed_state_ablation_20260812/
```

共享 control 与三个 candidate 在 node032 的隔离 evaluator repo 中并行完成 fresh emit/O3 link、
focused gate、fixed-ASLR `100/10k` 功能 gate 和 artifact identity gate；并行构建摘要为
`build/grhsim_typed_state_ablation_20260812/arms_v2/parallel_build_summary.json`，其中
`failures=[]`。

| arm | candidate digest | generated fingerprint | binary bytes | binary SHA-256 | build seconds |
| --- | --- | --- | ---: | --- | ---: |
| `typed_state_byte` (`S8`) | `f53f844e0de9672626bea88c8ba789bd8ed3b4de1ca0992cd115e17e1364f707` | `765440c229c1b459df4b08295e3f3b2d6046c821a7318fcbb7ee8f3ea67b1771` | `89,157,696` | `0338bad5bb98a440492e2b13f701af3e2bb476e181a17084b49e3f167985a878` | `1,674.553171` |
| `typed_state_native_bool` (`SB`) | `a189837d04c72cd545072b61b491ee4d6a8dd09974110e2547f461f23ad6cf87` | `0f495ecef5288518226bd4be513c3f6000dd22005e8742cf9ade093d8e1ad9d8` | `87,445,568` | `52d15c0945469aa0cb680505aeefcdda53ac564da1acd037bac406fd0389d7e3` | `1,847.126194` |
| `full_native_bool_values` (`SBV`) | `439a769a676c2bc815423273a2aec5be9b6b250cb656984e6380c8c5062422c2` | `c85ab471f21e856880e7e675c8819e36cbd02988f8873f25cc4c8193fb411ec5` | `83,705,920` | `7eed38e8e005e6a99f81e455265b3227036d8cd121fb71f3724c5df65622873f` | `1,592.474022` |

共享 control 身份：binary SHA-256
`7bd9f35e2354ab38af601366dc333fdfe381d8fc51b222ad1d0d0f629e02a604`，image SHA-256
`c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`，nemu SHA-256
`094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`。这些 identity 与
TNO0227 的 pinned baseline 一致。

## 3. Runtime 尝试与为何不能采纳

运行器先后保留了多个只改变 placement/admission 的输出根，代码和候选二进制没有变化：

| output root | 固定 placement | 已落盘 wrapper attempts | 结果 |
| --- | --- | ---: | --- |
| `pairs_gap_lt_0p25_v1` | 动态发现 | `7` | 1 次 ABBA 完成，BAAB pre-gate 失败；其余被污染或 pre-gate 拒绝 |
| `pairs_gap_lt_0p25_v2_affinity` | node1 `144-151,336-343` | `12` | 外部污染/无 quiet CCD，未成对 |
| `pairs_gap_lt_0p25_v3_affinity` | node1 `184-191,376-383` | `23` | 1 次 ABBA 完成，BAAB 被污染；后续无 quiet CCD |
| `pairs_gap_lt_0p25_v5_affinity` | node0 `88-95,280-287` | `10` | 外部污染或无 quiet CCD，未成对 |
| `pairs_gap_lt_0p25_v11_affinity` | node0 `88-95,280-287` | `6` | 1 次 ABBA 完成，BAAB pre-gate 失败；后续无 quiet CCD |
| `pairs_gap_lt_0p25_v12_gate20` | node0 `88-95,280-287` | `14` | 放宽 admission 重试次数仍无完整配对；随后停止 |

因此目前共有 `72` 个 wrapper attempt JSON 落盘，但有效的 `ABBA+BAAB` 配对为绝对值 `0`。
`v4`/`v9` 只遇到启动命令路径拼写错误，没有产生 runtime 样本；`v6`--`v10` 的等待/门禁试验
没有产生可采纳样本，也不计入上表。

为便于审计，三次 ABBA-only 的绝对数值如下；它们明确标为 **discarded**：

| output root / attempt | control wall ms | candidate wall ms | candidate 减少 ms | 相对变化 |
| --- | ---: | ---: | ---: | ---: |
| `v1` / round-1 attempt-1 | `48,081.0` | `44,687.0` | `3,394.0` | `7.058921%` |
| `v3` / round-1 attempt-2 | `48,706.5` | `44,897.5` | `3,809.0` | `7.820311%` |
| `v11` / round-1 attempt-3 | `48,090.0` | `44,773.5` | `3,316.5` | `6.896444%` |

这些行没有对应的有效 BAAB，故不满足 TNO0227 的同 CCD 与 `gap < 0.25 pp` 选择规则。它们不能
作为 `S8` 收益、总收益或默认开启依据。

## 4. 外部负载证据

失败原因来自 runtime 的基础设施门禁，而不是代码功能错误：

- 日志反复记录 `external load prevented the fixed CCD pre-gate`、`external load contaminated the
  fixed CCD during the workload` 和 `no dynamically discovered CCD passed the strict quiet-window
  gate`。
- node032 是 `384 CPU` 机器；停止后的现场快照仍为 load average
  `144.98 / 129.39 / 82.98`（1/5/15 分钟）。节点上可见长期运行的 CI/Verilator 与 emu 任务。
- 另一个用户的 `emu` 进程（`wangsangping`）当时使用全机器 affinity `0-383`，因此即使本轮运行器
  固定到一个 CCD，也不能阻止该外部进程在目标 CCD 上运行。固定 affinity 只约束本轮进程，不是
  节点级独占。

这正是本轮门禁应当拒绝样本的情况。没有通过门禁的 walltime 不应通过手工挑选 CCD、ABBA-only
 数值或 pooled 平均“挽救”。

## 5. 停止动作与恢复点

已执行并核验：

1. 终止本轮本地 wrapper 会话及 node032 上属于本轮的 `run_pairs_typed`、`run_single_pair`、
   `emu`、`perf`、`mpstat` 进程。
2. 再次检查 `pgrep`/`ps`，当前没有匹配本轮目录、运行器、emu 或 `mpstat` 的活动进程。
3. 保留所有 `pair_attempt_*.json`、`result.json`、`summary.json`、monitor/audit 日志和 `arms_v2`
   构建目录；没有删除实验数据。

恢复时建议从以下固定入口继续：

```text
build/grhsim_typed_state_ablation_20260812/arms_v2/
```

先确认 node032 在整个待测 CCD 集合上没有全机 CI/emu 任务，再运行 `B -> S8` 的完整 ABBA+BAAB；
只有它通过后才继续 `S8 -> SB -> SBV` 与 `B -> SBV`。本次暂停不改变 baseline、默认配置或
SimpleTES 后续可继续研究的输入。

