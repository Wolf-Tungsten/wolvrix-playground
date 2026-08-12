# TNO0229：typed-state 最优路径消融在 node032 的完整 runtime 结果

日期：2026-08-13

## 1. 恢复范围与结论

本记录承接 [TNO0228](./TNO0228_typed_state_ablation_node032_infrastructure_pause_20260812.md) 的暂停点，
在 node032 的负载窗口恢复 [TNO0227](./TNO0227_typed_state_bestpath_ablation_design_and_materialization_20260812.md)
中已经完成构建的四个 arm。恢复没有重新构建候选，也没有修改 Wolvrix 或 SimpleTES 源码。

四个预注册 pair 均完成了同 CCD 的 ABBA+BAAB，且每个 pair 的首个完整轮次都满足 order gap 严格小于
`0.25` 个百分点。所有被接受的 `32` 次 SimTop 50k workload invocation 均通过功能、fixed-ASLR、
affinity、NUMA、PMU 和运行时门禁。最终 endpoint `B -> SBV` 的绝对 Host walltime 为
`48,054.25 -> 43,335.50 ms`，减少 `4,718.75 ms`、改善 `9.819631%`。

这是一组可信的性能消融结果，但不是 Wolvrix 默认决策：实验 patch 仍未落地，默认配置保持不变。
后续若要采用，应以这些相邻收益为依据分别整理 patch，再做源码落地、功能回归和 fresh 50k 复测。

## 2. 固定身份与实验产物

本轮沿用 TNO0227 的 pinned baseline：

| identity | value |
| --- | --- |
| parent | `52ba7d9edcd713cd0ee3d8a605f1d4aa31b3c730` |
| Wolvrix | `d3ed9dea975bddf01185dde5c548a69241a09de9` |
| source | `lib/emit/grhsim_cpp.cpp` |
| baseline source SHA-256 | `7102ba7fde4dd72e4dc7419f1553b61d555482c49f79984c591d78e85b5239a8` |
| shared control binary SHA-256 | `7bd9f35e2354ab38af601366dc333fdfe381d8fc51b222ad1d0d0f629e02a604` |
| shared image SHA-256 | `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e` |
| shared nemu SHA-256 | `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e` |

构建与运行输出根目录（实验 artifact，属于被忽略的 `build` 树）为：

```text
build/grhsim_typed_state_ablation_20260812/arms_v2/
build/grhsim_typed_state_ablation_20260812/pairs_gap_lt_0p25_v13_quiet_20260812/
```

四个 arm 的 generated fingerprint 和 binary identity 与 TNO0227/TNO0228 一致：

| arm | generated fingerprint | binary bytes | binary SHA-256 |
| --- | --- | ---: | --- |
| `baseline_control` | `bb906f21d0214e22160f5f5944060724382e86668e473c39a7d0122f37cae5ba` | `91,320,384` | `7bd9f35e2354ab38af601366dc333fdfe381d8fc51b222ad1d0d0f629e02a604` |
| `typed_state_byte` (`S8`) | `765440c229c1b459df4b08295e3f3b2d6046c821a7318fcbb7ee8f3ea67b1771` | `89,157,696` | `0338bad5bb98a440492e2b13f701af3e2bb476e181a17084b49e3f167985a878` |
| `typed_state_native_bool` (`SB`) | `0f495ecef5288518226bd4be513c3f6000dd22005e8742cf9ade093d8e1ad9d8` | `87,445,568` | `52d15c0945469aa0cb680505aeefcdda53ac564da1acd037bac406fd0389d7e3` |
| `full_native_bool_values` (`SBV`) | `c85ab471f21e856880e7e675c8819e36cbd02988f8873f25cc4c8193fb411ec5` | `83,705,920` | `7eed38e8e005e6a99f81e455265b3227036d8cd121fb71f3724c5df65622873f` |

## 3. Runtime protocol

每条命令先 source `wolvrix-playground-gsim-calibrate-5/env.sh`。runtime 使用 `setarch x86_64 -R`，
因此每个进程的 personality 审计值为 `00040000`；同时使用 NUMA first-touch、单 CPU affinity、PMU、
功能签名和 SimTop 50k workload 检查。

每个 direct pair 的 ABBA 先选择通过 whole-CCD quiet gate 的 placement，BAAB 复用该 pair 的同一 CPU、
SMT sibling、CCD、NUMA node 和 helper CPU。每个 order 接受四个 control/candidate sample；按时间顺序
取第一个完整且 gap `<0.25 pp` 的轮次，不从多轮中挑收益最大的结果。不同 pair 可以使用不同 CCD；“同 CCD”
只约束同一 pair 的两个 order。

本轮实际使用的入口是：

```text
build/grhsim_typed_state_ablation_20260812/run_pairs_typed.py
--retries 8 --gate-attempts 20 --threshold-pp 0.25
```

## 4. 四组绝对 walltime 结果

headline 始终是 SimTop 50k 的 `Host time spent walltime_ms`。表中的 control/candidate 是四个 sample
的 arithmetic mean；百分比为 `(control-candidate)/control`。

| pair | selected attempt | control mean (ms) | candidate mean (ms) | 减少 (ms) | 改善 | ABBA | BAAB | gap (pp) | fixed placement |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `B -> S8` | 1 | `48,023.50` | `44,595.25` | `3,428.25` | `7.138693%` | `7.079028%` | `7.198318%` | `0.119290` | node0 `24-31,216-223`, CPU24, sibling216, NUMA0 |
| `S8 -> SB` | 2 | `44,760.25` | `44,195.25` | `565.00` | `1.262281%` | `1.278002%` | `1.246534%` | `0.031467` | node1 `144-151,336-343`, CPU144, sibling336, NUMA1 |
| `SB -> SBV` | 1 | `44,198.00` | `43,373.50` | `824.50` | `1.865469%` | `1.873960%` | `1.856983%` | `0.016977` | node1 `128-135,320-327`, CPU128, sibling320, NUMA1 |
| `B -> SBV` | 1 | `48,054.25` | `43,335.50` | `4,718.75` | `9.819631%` | `9.839000%` | `9.800270%` | `0.038730` | node1 `176-183,368-375`, CPU176, sibling368, NUMA1 |

各 pair 的 role-specific sample 原值如下，便于复核绝对数值而不依赖 pooled 百分比。每个单元格按实际
运行顺序列出，`C` 表示 control、`K` 表示 candidate；ABBA 为 `C,K,K,C`，BAAB 为 `K,C,C,K`。

| pair | ABBA control / candidate (ms) | BAAB control / candidate (ms) |
| --- | --- | --- |
| `B -> S8` | `C 48,050 / K 44,523 / K 44,696 / C 47,966` | `K 44,567 / C 48,044 / C 48,034 / K 44,595` |
| `S8 -> SB` | `C 44,830 / K 44,207 / K 44,241 / C 44,763` | `K 44,154 / C 44,690 / C 44,758 / K 44,179` |
| `SB -> SBV` | `C 44,146 / K 43,342 / K 43,371 / C 44,223` | `K 43,420 / C 44,195 / C 44,228 / K 43,361` |
| `B -> SBV` | `C 48,093 / K 43,351 / K 43,282 / C 47,994` | `K 43,334 / C 48,095 / C 48,035 / K 43,375` |

上表按每个 order 的实际 ABBA/BAAB 运行顺序展开；同一 pair 的两行使用同一个 fixed placement。四组
候选 sample spread 分别为 `173 ms`、`87 ms`、`78 ms`、`93 ms`，control spread 分别为
`84 ms`、`140 ms`、`82 ms`、`101 ms`。

## 5. 门禁、功能和无效尝试

- 32 个被接受的 workload sample 的 `function_audit.ok`、signature、terminal PC、guest cycle 和 walltime
  计数全部通过，negative match 为空。
- 每个有效 sample 的 process audit 都确认单 CPU affinity、预期 executable 和 ASLR-off personality；
  PMU 的 scheduled percent 为 `100%`，task-clock CPU utilization 为 `0.999`，CPU migration 为零。
- 所有有效 binary/nemu 的 NUMA local ratio 为 `1.0`。control 使用固定协议的 `20,000` 页最低 coverage；
  候选按相同 `89.847260%` coverage 规则分别使用 `19,526`、`19,151` 或 `18,330` 页门槛。
- `S8 -> SB` 的 attempt 1 因外部编译负载被 pre-gate 拒绝（`mean_idle=67.978%`、`min_idle=0%`、
  sibling idle `36.12%`），没有产生 workload sample；attempt 2 在 node1 `144-151,336-343` 完成
  ABBA+BAAB 并被选中。该无效尝试没有计入性能均值，也没有消耗代码/候选身份。
- 其余三组的 selected attempt 都是第 1 次。所有 invalid/retry 记录均保留在对应的
  `pair_attempt_*.json` 和 runtime audit 日志中，没有手工挽救或挑选单 order 数据。

## 6. PMU 解释性结果

PMU 只用于解释，不替代 walltime headline。以下为每个 pair 的 control mean → candidate mean：

| pair | cycles:u | instructions:u | backend stalls |
| --- | --- | --- | --- |
| `B -> S8` | `175,964,994,337.50 -> 163,435,569,636.75` (`-7.120407%`) | `160,743,730,103.50 -> 160,995,839,502.25` (`+0.156839%`) | `79,070,217,043.25 -> 61,418,224,998.00` (`-22.324451%`) |
| `S8 -> SB` | `163,857,538,138.25 -> 161,796,863,138.25` (`-1.257602%`) | `160,995,738,959.75 -> 157,769,757,835.75` (`-2.003768%`) | `63,789,149,420.50 -> 62,702,185,707.75` (`-1.703995%`) |
| `SB -> SBV` | `161,776,538,241.00 -> 158,745,228,094.75` (`-1.873764%`) | `157,769,753,892.75 -> 149,144,854,200.25` (`-5.466764%`) | `62,476,725,773.00 -> 55,862,791,333.25` (`-10.586237%`) |
| `B -> SBV` | `175,873,828,075.25 -> 158,615,058,083.50` (`-9.813154%`) | `160,743,730,212.75 -> 149,144,854,283.50` (`-7.215756%`) | `78,093,638,465.25 -> 55,728,920,641.25` (`-28.638335%`) |

`B -> S8` 的 walltime 下降伴随 backend stalls 大幅下降，而 instructions 近似不变；后两个 native-bool
阶段则同时减少 instructions/cycles。这个方向与“更窄的真实类型边界、较少的 byte/bool normalization 和更
直接的成员访问”机制一致，但不把 PMU 相关性当作单独的因果证明。

## 7. 消融解释与默认决策

相邻 pair 给出的边际信号是：

1. `B -> S8`：typed persistent-state layout（bool 仍为 byte）是本轮最大单项，`3,428.25 ms/7.138693%`。
2. `S8 -> SB`：persistent-state native bool 继续减少 `565.00 ms/1.262281%`。
3. `SB -> SBV`：materialized `kBool` value bucket 使用 native bool 再减少 `824.50 ms/1.865469%`。
4. `B -> SBV`：端点总收益为 `4,718.75 ms/9.819631%`。

三项相邻减少量的简单相加为 `4,817.75 ms`，比 endpoint 多 `99.00 ms`；因此不能把百分比相加，生成
代码布局和编译器优化存在交互。四个 patch 都是 zero-option、单一 emitter 源文件变化，没有 SimTop 名称、
端口或 workload 特判；但在正式 landing 前仍需检查源码 diff 的原则性边界，并完成独立功能/性能回归。

本记录不改变 Wolvrix C++/Python 默认选项，不打开 targeted-direct，也不改变 SimpleTES 的研究 baseline。
SimpleTES 的 checkpoint、候选物化和后续 research 能力均未被本轮运行改写；后续继续探索时仍可从原有
principled-TRBS baseline 或显式选择的最新 best 重新建立 checkpoint。

## 8. 可复现路径

每组的权威结果为：

```text
build/grhsim_typed_state_ablation_20260812/pairs_gap_lt_0p25_v13_quiet_20260812/
  B_to_S8/round-1/result.json
  S8_to_SB/round-1/result.json
  SB_to_SBV/round-1/result.json
  B_to_SBV/round-1/result.json
```

总 runner 日志为：

```text
build/grhsim_typed_state_ablation_20260812/pairs_gap_lt_0p25_v13_quiet_20260812.log
```

所有 `pair_attempt_*.json`、每次 workload 的 `audit.txt`、`emu.log`、`perf.csv` 和 monitor 日志均保留。
本记录形成时 parent worktree 仍只有预先存在的 dirty `wolvrix` 子模块状态；该状态没有被本轮修改。
