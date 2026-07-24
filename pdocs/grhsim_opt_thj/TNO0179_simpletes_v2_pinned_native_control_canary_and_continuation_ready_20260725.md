# TNO0179 SimpleTES v2 pinned native-control canary and continuation readiness

## 1. 状态与结论

本记录关闭
[TNO0177](./TNO0177_simpletes_grhsim_bench_contract_v2_migration_and_continuation_readiness_20260725.md)
中保留的最终提交、pin 更新和 direct-evaluator native-control canary 项。gen24 exact-event 已作为通用
Wolvrix C++ 默认落地；SimpleTES GrhSIM bench 已固定到对应 parent/wolvrix commit，并以 schema-v2
`control` seed 完成一次 fresh native `options={}` 构建、功能 gate 和 quiet whole-CCD 50k ABBA。

最终 accepted ABBA 的四个 `Host time spent` 绝对值为
`61,310 / 61,318 / 61,010 / 61,073 ms`。control 均值为 `61,191.50 ms`，candidate 均值为
`61,164.00 ms`，绝对差 `27.50 ms`，表观改善 `0.044940882%`。control 与 candidate 使用同一原生
默认产物，generated fingerprint、binary/image/NEMU SHA 均相同，因此这 `27.50 ms` 只代表配对
噪声，不是新的优化收益，也不参与默认开关裁决。

默认决定继续采用 [TNO0176](./TNO0176_gen24_four_arm_function_formal_walltime_and_default_decision_20260725.md)
的正式四臂结果：exact-event `targeted-cold-layout` 在通用 C++/Python 流程中 default-on；独立的
`active_mask_gap_pack_policy=targeted-direct` 保持 default-off。canary 没有通过 SimTop wrapper 注入这
两个选项。

本阶段只直接调用 dataset evaluator；没有运行 SimpleTES scheduler/launcher main，没有调用 API 或
模型，也没有启动新的 auto research instance。后续探索现在可以从 pinned schema-v2 control fresh
启动，但本记录本身不授权或启动该探索。

## 2. 最终提交与默认来源

| 仓库 | commit | 提交主题 |
| --- | --- | --- |
| Wolvrix submodule | `8f6ba14397b0c3d00cb909153af1c6464f4f1ed9` | `feat: add native exact-event commit lowering` |
| parent executable snapshot | `fbe4e1cbbfcf45b52960545377020cb761c3ab25` | `feat: adopt native GrhSIM exact-event lowering` |
| SimpleTES | `d17629c03fbcb3d88ef106172b8c68a8d305a086` | `feat: support native-default GrhSIM research` |

SimpleTES `evaluator.py`、bench README 和 init seed 均固定到完整 parent
`fbe4e1cbbfcf45b52960545377020cb761c3ab25` 与 Wolvrix
`8f6ba14397b0c3d00cb909153af1c6464f4f1ed9`。本 TNO 随后的 parent 文档提交只增加记录，不改变
可执行代码或 submodule pointer，因此 bench pin 有意继续指向已经由 canary 验证的
`fbe4e1c...` executable snapshot，不循环改 pin 到文档提交。

fresh control build 日志确认：

```text
active_mask_gap_pack_policy_effective=cpp-default
active_mask_gap_pack_policy_source=cpp-default
commit_exact_event_policy_effective=cpp-default
commit_exact_event_policy_source=cpp-default
[GRHSIM_COMMIT_EXACT_EVENT] policy=targeted-cold-layout selected=1 fallback=none cold_runs=16 cold_guards=44976 lockstep_groups=2089 lockstep_writes=11799
```

命令行没有 exact-event/gap-pack option；控制路径也没有 pre-reg 或 stats resume。production emit
绝对耗时为 `1,442,417 ms`。这与
[TNO0178](./TNO0178_native_no_override_default_path_and_same_session_identity_20260725.md) 的同 Session
逐字节 identity 一起证明默认来源是通用 C++ emitter，而不是 SimTop 专用打开。

## 3. 提交前后回归闭环

最终代码和 pins 上完成的绝对回归结果如下：

| gate | 绝对结果 |
| --- | ---: |
| fresh Wolvrix Release Ninja build | `94/94` steps PASS |
| Wolvrix full CTest | `49/51 PASS` |
| exact-event focused / main emitter | PASS / PASS |
| Python binding | `22/22 PASS` |
| XS wrapper | `32/32 PASS` |
| legacy targeted-direct gap focused | PASS |
| SimpleTES established full test scope | `138/138 PASS` |
| SimpleTES GrhSIM v2 focused scope | `66/66 PASS` |
| init control `--validate-only` | PASS，digest `d321c48a5d12bd27b92219b18afad7a04a6141d8ff52d966b4dc8dcf3f04fb07` |
| launcher `--dry-run` | PASS，仅打印 `gpt-5.6-sol/ultra` 命令，不调用模型 |
| post-pin Python syntax / `git diff --check` | PASS / PASS |

full CTest 唯一失败仍是既有 `transform-comb-lane-pack` 与 `transform-repcut`，与 TNO0175 之前的历史
失败集合一致，没有新增回归。SimpleTES full scope 有 `17` 条既有 `datetime.utcnow()` deprecation
warning，没有 test failure。一次误用过宽 pytest discovery 时额外收集了需要可选 openproblems
依赖的 dataset tests，因环境没有该可选依赖而失败；随后使用仓库既定 `tests/` scope 重跑得到上述
`138/138 PASS`，该次是调用范围错误，不是实现回归。

## 4. fresh native-control 构建与轻量功能 gate

canary 根目录为：

```text
/tmp/simpletes-grhsim-native-control.341s20
```

slot 为：

```text
/tmp/simpletes-grhsim-native-control.341s20/slots/0395ffde6780036f/slot-0
```

输入是 schema-v2 `candidate_mode=control`，patch file 数 `0`、option 数 `0`、proof ID
`control`、proof SHA-256 为 64 个零。direct evaluator fresh clone pinned parent/submodule 后只建立一份
native-default control artifact；candidate-control 运行复用该同一份产物。runtime 前的 gate 为：

| gate | 绝对结果 |
| --- | ---: |
| focused semantic tests | `29 tests PASS`，`0.003 s` |
| SimTop function 100 | PASS，`Host time spent: 211 ms` |
| SimTop function 10k | PASS，`Host time spent: 6,841 ms` |
| generated files fingerprint | `9ad3a09d170442b2ea4d2cc1610eede86611ebddf6d49127b4fbee9eba3af989` |
| build config fingerprint | `920b5c7f1e32e61e7ad363145521736e9a10a68d0e0d112ce7b4406f00e820b3` |
| toolchain fingerprint | `3139fef644317380a048f6d32551a70f2e960fe73558188951636856f4617038` |

control artifact marker 的 parent/wolvrix、三项 artifact SHA、generated/build/toolchain fingerprint 与当前
文件均重新校验通过。

## 5. 首次基础设施拒绝与 runtime-only 重试

第一次完整 evaluator 已完成上述 clone/build/focused/function gate，但 50k 阶段最终因外部负载未能
通过 fixed-CCD pre-gate，结果被正确标记为：

```text
valid_candidate=0
validity=0.0
infrastructure_retry=1
error=external load prevented the fixed CCD pre-gate
last_gate mean_idle=97.53125%, min_idle=84.28%
```

该次 `eval_time=3,089.027365810 s`，attempt ID 为
`01784933068753882506-3326613-d1c48cf8eb0f4078b7c8a37a4a03ccb8`。此前出现的 provisional
50k 数值属于被丢弃的基础设施 attempt，不能混入最终性能均值。

随后使用 contract-v2 runtime-only retry，在同一 slot 上把基础设施 retry budget 提高到 `8`，没有
放宽 quiet-CCD、ASLR、NUMA、perf 或功能门槛。重试不 clone、不 emit、不 build：

```text
CONTROL_ARTIFACT_REUSED=PASS
CONTROL_MARKER_SHA_SNAPSHOT=PASS
CONTROL_EMU_STAT_SNAPSHOT=PASS
```

重试前后 `control_artifacts.json` SHA snapshot 与 emu stat snapshot 完全相同。运行器在若干不满足
门禁的 provisional group 后丢弃整组，最终只发布下节同一个 accepted ABBA attempt。

## 6. accepted 50k ABBA 绝对 walltime

accepted attempt 固定在一颗完整空闲 CCD：`node0:32-39,224-231`，target CPU `38`、SMT sibling
`230`、helper CPU `96`。四个样本均使用同一 CPU、同一 CCD、同一 NUMA node，顺序为正式
`A-B-B-A`：

| 顺序 | role | `Host time spent` | pre-gate mean/min idle | monitor mean/min idle |
| ---: | --- | ---: | ---: | ---: |
| 1 | control A | `61,310 ms` | `99.374375% / 97.34%` | `99.280000% / 98.33%` |
| 2 | candidate B | `61,318 ms` | `99.543125% / 97.67%` | `99.400000% / 97.80%` |
| 3 | candidate B | `61,010 ms` | `99.460000% / 98.34%` | `99.444000% / 98.64%` |
| 4 | control A | `61,073 ms` | `99.542500% / 98.00%` | `99.426667% / 98.56%` |

绝对聚合为：

| 字段 | 值 |
| --- | ---: |
| control arithmetic mean | `61,191.50 ms` |
| candidate arithmetic mean | `61,164.00 ms` |
| absolute difference | `27.50 ms` |
| relative difference | `0.044940882%` |
| control range / spread | `61,073..61,310 ms` / `237 ms` |
| candidate range / spread | `61,010..61,318 ms` / `308 ms` |
| `combined_score` | `1.0004496108822183` |
| retry evaluator elapsed | `632.431491830 s` |

每个样本均满足以下硬 gate：

- function signature、guest cycle、terminal PC 和唯一 walltime 全部 PASS；
- `Cpus_allowed_list=[38]`、resolved emu 路径正确、CPU migration 为 `0`；
- `/proc/<pid>/personality=00040000`，地址随机化确实关闭；
- binary `20,980/20,980` pages 位于 NUMA node 0，local ratio `1.0`；
- NEMU `115/115` pages 位于 NUMA node 0，local ratio `1.0`；
- perf 五项事件和 task-clock scheduling 均 PASS，scheduled percent `100.0%`；
- whole-CCD pre-gate 与排除 target CPU 的 runtime monitor 均 PASS。

最终 JSON 为 `valid_candidate=1`、`validity=1.0`、`infrastructure_retry=0`、
`retryable_infra=0`，而且 control/candidate generated fingerprint 都是
`9ad3a09d170442b2`。这关闭 native-control canary，不产生新默认决策。

## 7. artifact 与 immutable attempt 身份

| artifact | bytes | SHA-256 |
| --- | ---: | --- |
| `control_artifacts.json` | `1,445` | `54b33d67b04c17cacf891dec97403145dd00f2c5065c5ebf14d9b0ca216b1f30` |
| control emu | `91,673,112` | `fc224010283fa16b166f9822230dbf58ec90216084db70dac4191f3eec94ca53` |
| CoreMark image | `16,712` | `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e` |
| NEMU shared object | `567,504` | `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e` |

accepted immutable attempt：

```text
candidate digest: d321c48a5d12bd27b92219b18afad7a04a6141d8ff52d966b4dc8dcf3f04fb07
attempt id: 01784933781239601687-3587480-bdffea213013482ba2570a58b89b788b
candidate mode/proof: control / control
candidate proof SHA-256: 0000000000000000000000000000000000000000000000000000000000000000
evaluation SHA-256: e6bebd106c06acc733ebda30e1dbad1f781a336902cc3e374488e45d865e26e9
runtime result SHA-256: 050fab1625511fd2fa6a4facd532e48b43177fb09c13ba93ba5a41d23ee2a34c
```

`complete.json` 中的两个 payload SHA 与实际文件 `sha256sum` 完全一致；其自身 SHA 为
`11b3dd0747e835b2b34c3d29ff6281335b7485a1308eee8bc5c1230304b406ed`。外层 accepted result JSON
为 `21,218 B`，SHA-256
`ffec18b88e56dbd7618c885b7e3985bbd68bd3b676294d38f59d2085a09bad41`。首次 infra-retry result
为 `1,474 B`，SHA-256
`c5f2d73957691d188ebb2b7c848c2245611b1a3ecf395de09bcd14f86015e533`。

## 8. 源码隔离与 continuation 边界

canary 前后分别保存 parent、Wolvrix 和 SimpleTES 的完整 porcelain status；三组 before/after 逐字节
相同，结束后再与当前工作区状态比较也全部一致。runtime-only retry 没有污染 source checkout。
保留的既有工作区状态仍只有 parent 的 submodule dirt，以及 Wolvrix 中用户已有的
`external/mt-kahypar` dirt 和未跟踪 `build-simpletes-landing/`；SimpleTES 工作区 clean。本阶段没有
删除、覆盖或提交这些无关文件。

continuation readiness 现为 `PASS`，但边界如下：

1. 新探索必须从 schema-v2 pinned `control` fresh 启动；历史 schema-v1 checkpoint 和旧
   parent/wolvrix pin 仍被 launcher 拒绝，不能静默 resume；
2. 修改已默认 exact-event 路径使用 `default-path`，保持 native `options={}`；研究显式功能使用
   `explicit-options` 并经过三重归因；
3. `targeted-direct` 只控制 active-mask gap-pack，不能再次被借作 exact-event 的开关；
4. 后续每个正式候选仍需 fixed-ASLR、完整空闲 CCD、功能/perf/NUMA gate 和 50k absolute
   `Host time spent`；只有端到端 walltime 有可信提升的修改才可默认开启；
5. 本次 direct canary 完成后没有自动启动 scheduler。是否开始下一轮 auto research 仍由用户另行
   指示。

## 9. 权威结果路径

| 结果 | 路径 |
| --- | --- |
| 首次 infra-retry result | `/tmp/simpletes-grhsim-native-control.341s20/result.json` |
| accepted retry result | `/tmp/simpletes-grhsim-native-control.341s20/result_retry1.json` |
| control artifact marker | `/tmp/simpletes-grhsim-native-control.341s20/slots/0395ffde6780036f/slot-0/results/control_artifacts.json` |
| accepted immutable attempt | `/tmp/simpletes-grhsim-native-control.341s20/slots/0395ffde6780036f/slot-0/results/attempts/d321c48a5d12bd27b92219b18afad7a04a6141d8ff52d966b4dc8dcf3f04fb07/01784933781239601687-3587480-bdffea213013482ba2570a58b89b788b` |
| runtime sample directory | `/tmp/simpletes-grhsim-native-control.341s20/slots/0395ffde6780036f/slot-0/results/runtime_d321c48a5d12bd27` |

这些 `/tmp` 路径是本机实验产物位置，不作为 Markdown 链接；关键身份和绝对数据已经完整抄录到本
记录，后续即使临时目录清理也不会丢失默认裁决和 canary 结论。
