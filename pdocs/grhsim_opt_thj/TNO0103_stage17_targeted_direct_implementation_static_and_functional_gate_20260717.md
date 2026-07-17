# TNO0103 Stage 17 targeted-direct implementation, static, and functional gate

记录日期：2026-07-17

状态：targeted-direct 实现、focused/plumbing、production source diff、O3 和 fixed-ASLR 100/10k/50k 功能门禁已完成。current native-hybrid/cap4096 下选中 `15,913` 个 non-table direct group，将这些 group 的 active-mask writes 从 `86,350` 降至 `56,345`，减少 `30,005`；production diff 只涉及 `107` 个 `grhsim_SimTop_sched_*.cpp` 的 active-mask write，O3 `.text` 与 ELF 文件分别减少 `101,551` 和 `102,400` bytes，功能三档全过。严格 SimTop 50k 性能与默认决策见 [TNO0104](./TNO0104_stage17_targeted_direct_n0_strict_runtime_and_default_decision_20260717.md)；完整串行回归尚未完成，完成后按增量规则另立记录。

## 1. 实现范围与唯一默认源

本轮实现 [TNO0102](./TNO0102_stage17_targeted_direct_active_mask_gap_pack_plan_20260717.md) 的 direct-only mutation。`activeMaskGapPackPolicy` 增加第三个值 `targeted-direct`；只有同时满足以下条件才采用 Stage 16 planner 返回的 chunks：

- owner/site 为 generic activation path；
- baseline 判定为 non-table，即 merged entries `<32`；
- 独立 validator 通过；
- candidate writes 严格少于 baseline contiguous writes。

table、deferred direct/aggregate、memory-row、seed、commit-range、unclassified 和 local-only path 均不采用 candidate。direct/table 判定、conditional wrapper/branch 选择和 estimate 继续基于 baseline representation；选中后只把最终 direct active-mask chunks 替换为已验证的 zero-hole plan。validator 或 self-test 失败会使整个 emit 返回失败，不会静默发出未验证 source。

统计新增：

```text
selected_groups
selected_baseline_writes
selected_candidate_writes
selected_savings
```

每个 group 的 planner/validator 在局部执行，统计通过 mutex 聚合；emit parallelism 不参与 candidate 的稳定选择。生成 model 仍沿用单线程 `eval()` 契约，本轮没有把 active RMW helper 扩展为并发或原子语义。

默认配置原则保持统一：

```text
C++ activeMaskGapPackPolicy default = off
Python None                         = omit attribute
XS high-level env unset             = sparse, omit attribute
```

XS 只有显式设置 `WOLVRIX_XS_GRHSIM_ACTIVE_MASK_GAP_PACK_POLICY` 时才覆盖 C++；低层 `WOLVRIX_GRHSIM_ACTIVE_MASK_GAP_PACK_POLICY` 仍由 emitter 自己解析。日志继续区分 `cpp-default`、`cpp-low-env` 和 `xs-override`。通用默认应直接位于 C++，XS 只保留必要的平台稀疏覆盖，避免脚本默认与直接 API 或后续 C++ 默认发生漂移。本阶段没有在 XS 中暗设 `targeted-direct`。

## 2. Focused 与配置门禁

小 fixture 精确选中 `3` 个 group：selected writes `12 -> 6`、savings `6`；加上未选中 group 后，non-table overall writes `16 -> 10`。focused gate 检查了三个 selected group 的精确 mask，并确认：

- native default、explicit `off`、`probe` artifacts byte-exact；
- targeted serial、parallel 和 low-level env 三路 artifacts byte-exact；
- targeted 只改变 schedule active-mask write，冻结 conditional branch；
- `31` entries 仍走 direct，`32` entries 的 table lowering 完全不变；
- selected 统计与实际减少的 write 数精确对账；
- `off|probe|targeted-direct` 在 C++、Python/native 与 XS plumbing 中接受，非法值一致拒绝。

已完成的定向结果：

| gate | 结果 |
| --- | --- |
| editable native binding build/install | PASS |
| `emit-grhsim-cpp` active-mask focused fixture | PASS |
| pybind option tests | `7/7 PASS` |
| XS option tests | `10/10 PASS` |

XS 测试同时确认：未设置高层变量时 options 为空，低层环境只用于 source 日志观察而不被脚本归一化或写回；高层显式值才形成 attribute override。完整 build/串行 CTest 不在本文提前宣告，待完成后单独归档。

## 3. Production 对象与结构 identity

fresh production 输出和日志：

```text
build/xs_activity_stage17_active_mask_gap_default_20260717/grhsim/grhsim_emit/
build/xs_activity_stage17_active_mask_gap_targeted_direct_20260717/grhsim/grhsim_emit/

build/logs/xs/xs_wolf_grhsim_build_activity_stage17_active_mask_gap_default_20260717.log
build/logs/xs/xs_wolf_grhsim_build_activity_stage17_active_mask_gap_targeted_direct_20260717.log
```

两路均固定 current C++ native hybrid、commit cap `4096`、DP penalty `1,000,000 PPM`，其它实验 schedule policy 关闭。default source manifest 为：

```text
bfcf0b9d4554b5da76bcc0f08c733a8bb9f9f6b96c50150c51cdded162853cda
```

它与 [TNO0100](./TNO0100_stage16_active_mask_gap_probe_implementation_and_production_result_20260717.md) 的 Stage 16 baseline 全目录 byte-exact。targeted source manifest 为：

```text
d735df82b478d74f96219d9d19d16b063666b37c0c1107299c059e84da3dfcec
```

activity-schedule 与 emitter stats JSON 均不变，结构 identity 为：

| metric | default | targeted-direct |
| --- | ---: | ---: |
| total supernodes | `63,726` | `63,726` |
| compute supernodes | `63,241` | `63,241` |
| commit supernodes | `485` | `485` |
| final DAG edges | `528,622` | `528,622` |
| boundary activation edges | `1,983,923` | `1,983,923` |
| compute-commit value pairs | `262,225` | `262,225` |

本轮是 emitter-local statement encoding，不改变 activity schedule，所以这些指标不应被解释为 BAE 优化。最终 runtime 仍按真实 SimTop 50k 裁决。

## 4. Production selection 与 source diff

targeted production report 为：

```text
validation=pass validator_self_test=pass
selected_groups=15913
selected_baseline_writes=86350
selected_candidate_writes=56345
selected_savings=30005
```

完整 non-table probe totals 与 Stage 16 精确相同：`359,259` groups、`683,621` merged entries、baseline/contiguous `653,299` writes、candidate `623,294` writes、`85,146` hole bytes，invalid groups 和全部 invalid breakdown 均为 `0`。因此 selected savings 与 Stage 16 gap-only opportunity 精确对账：

```text
86,350 - 56,345 = 30,005
653,299 - 623,294 = 30,005
```

table 仍是 baseline lowering。它的 probe-only `19,942 -> 17,530` gap proxy 只观测、不发 source；excluded owner 计数也与 Stage 16 相同。

逐文件 source diff gate 得到：

| metric | default | targeted-direct | delta |
| --- | ---: | ---: | ---: |
| changed schedule files | - | `107` | 仅 `grhsim_SimTop_sched_*.cpp` |
| changed non-schedule files | - | `0` | `0` |
| active-mask write statements | `819,223` | `789,218` | `-30,005` |
| schedule source lines | `13,383,537` | `13,353,532` | `-30,005` |
| schedule source bytes | `1,331,059,293` | `1,329,565,234` | `-1,494,059` |
| all generated source bytes | `1,356,877,425` | `1,355,383,366` | `-1,494,059` |

两边 artifact set 完全相同；去掉 active-mask write lines 后，`107` 个 changed schedule file 的剩余内容 mismatch 为 `0`。没有 missing/extra file，没有 table loop、函数签名、batch/file order 或 non-schedule artifact 漂移。实际 source write reduction 与 production selected savings 精确相等。

## 5. O3/ELF gate

candidate O3 build 日志和 ELF：

```text
build/logs/xs/stage17_active_mask_gap_targeted_direct_o3_build_20260717.log
build/xs_activity_stage17_active_mask_gap_targeted_direct_20260717/grhsim/grhsim-compile/emu
```

Stage17 default source 与 Stage14 current native-hybrid baseline byte-exact，所以静态对照复用同一 current-default ELF：

```text
build/xs_activity_stage14_native_hybrid_default_20260717/grhsim/grhsim-compile/emu
```

ELF 对照结果：

| section/file | current default | targeted-direct | delta |
| --- | ---: | ---: | ---: |
| `.text` | `87,113,502` | `87,011,951` | `-101,551` (`-0.1166%`) |
| `.rodata` | `5,652,584` | `5,653,400` | `+816` |
| `.eh_frame_hdr` | `8,604` | `8,604` | `0` |
| `.eh_frame` | `706,632` | `706,712` | `+80` |
| `.data` | `152` | `152` | `0` |
| `.bss` | `14,688` | `14,688` | `0` |
| ELF file bytes | `93,694,944` | `93,592,544` | `-102,400` |

schedule object `.text` aggregate 从 `91,726,390` 降至 `91,626,454`，减少 `99,936`；`107` 个 source-changed file 对应 `107` 个 changed object。schedule object file aggregate 与 archive 各减少 `29,832` bytes。两边 schedule objects 中未解析的 `memcpy/memmove` 行数均为 `17`，没有因 wider RMW 新增 helper call site。

ELF SHA256 为：

```text
current default  51b74981b0a23d93dc860e13f82248a3ec0c21153117df3f7889da55be918788
targeted-direct  2160ed0646f2ee032ed5e4ab49a980200e71b93846e5a6f852e34b5797e65f0c
```

静态结果温和正向，但 `.text -0.1166%` 远不能替代动态结论；更宽 RMW 的 load/store 代价仍须由 strict 50k 测量。

## 6. Fixed-ASLR 功能门禁

candidate 使用 `setarch x86_64 -R` 完成三档功能运行，日志为：

```text
build/logs/xs/stage17_active_mask_gap_targeted_direct_function_20260717/targeted_direct_100.log
build/logs/xs/stage17_active_mask_gap_targeted_direct_function_20260717/targeted_direct_10000.log
build/logs/xs/stage17_active_mask_gap_targeted_direct_function_20260717/targeted_direct_50000.log
```

| limit | instrCnt | cycleCnt | Guest cycle spent | 结果 |
| ---: | ---: | ---: | ---: | --- |
| `100` | `0` | `96` | `101` | PASS |
| `10,000` | `458` | `9,996` | `10,001` | PASS |
| `50,000` | `73,580` | `49,996` | `50,001` | PASS |

三档均正常到达 cycle limit，无 mismatch/assert/fatal/error；50k host wall 为 `74,561 ms`，但该次未经过 quiet/perf gate，只作功能结果，不作性能 headline。

## 7. 阶段边界

实现、source/O3 和功能门禁均证明 mutation 被严格限制在已选择的 non-table direct active-mask writes，且未引入结构或功能回归。它仍不证明性能收益：静态少 `30,005` 个 statement 与 `.text -0.1166%` 可能被更宽 RMW 或 layout 波动抵消。

因此默认保持 C++ native `off`，XS 保持 sparse override；严格 N0 ABBA+BAAB 与默认决策另见 [TNO0104](./TNO0104_stage17_targeted_direct_n0_strict_runtime_and_default_decision_20260717.md)。N1 和完整串行回归若后续完成，分别新增记录，不回填或提前猜测结果。
