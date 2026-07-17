# TNO0116 Stage 20 table encoding implementation and full gate

记录日期：2026-07-17

状态：Stage 20 两个未插桩 table encoding candidate 已完成实现、production emit、静态 source/ELF 对账、fixed-ASLR 功能门禁和完整回归。两者均保持 schedule/active-ID/batch/slot 不变，并进入严格 page-local SimTop 50k walltime；最终性能与默认决定见 [TNO0117](./TNO0117_stage20_table_encoding_strict_walltime_and_default_decision_20260717.md)。

## 1. 实现边界与 native default

在 `active_mask_gap_pack_policy` 中新增两个显式实验值：

```text
targeted-table-contiguous
targeted-table-gap
```

两者只选择 `probeSite=generic` 且 `entries >= 32` 的 table group。contiguous 使用原有无洞 `8/4/2/1` chunk planner；gap 使用已验证的 zero-hole DP planner。被选中的 table group 整体绕过 `kActivationMasks` entry loop，不允许在 chunk 数等于 entry 数时静默退回 loop，也不允许 validator 失败后混用旧表示。memory、deferred、seed/initial、commit-range、unclassified 和小于 32 entries 的 table path 全部冻结。

C++ native default 始终为 `off`；Python binding、native action 和 XS sparse override 仅增加两个可显式指定的枚举值，没有在脚本中新增 XS 专用默认。实现文件为：

```text
wolvrix/lib/emit/grhsim_cpp.cpp
wolvrix/app/pybind/native/actions/emit.cpp
wolvrix/app/pybind/wolvrix/__init__.py
wolvrix/tests/emit/test_emit_grhsim_cpp.cpp
wolvrix/tests/pybind/test_emit_grhsim_cpp_options.py
scripts/test_wolvrix_xs_grhsim_options.py
```

focused fixture 精确包含 32 个稀疏 table bytes：`112..126` 的偶数字节和 `130..176` 的偶数字节。旧 loop 为 32 entries，contiguous control 为 32 个 byte chunks，gap 为 8 个 `uint64` chunks；该用例专门锁定“contiguous 没有 write-count 收益时仍必须整体使用候选表示”。31-entry 与 non-table path 保持原样，serial/parallel/env 生成确定性、无效 policy、Python/native/XS 解析也均有测试覆盖。

## 2. production emit 与结构 identity

三套 fresh emit 目录和日志为：

```text
build/xs_activity_stage20_table_default_20260717/grhsim/grhsim_emit/
build/xs_activity_stage20_table_contiguous_20260717/grhsim/grhsim_emit/
build/xs_activity_stage20_table_gap_20260717/grhsim/grhsim_emit/
build/logs/xs/xs_wolf_grhsim_build_stage20_table_default_20260717.log
build/logs/xs/xs_wolf_grhsim_build_stage20_table_contiguous_20260717.log
build/logs/xs/xs_wolf_grhsim_build_stage20_table_gap_20260717.log
```

三者都从同一份 current default post-stats 恢复：

```text
build/xs_activity_stage8_dp_p050_20260715/grhsim/wolvrix_xs_post_stats.json
```

default 显式不设置 high/low policy 和 runtime profile，日志确认 `active_mask_gap_pack_policy_effective=cpp-default source=cpp-default`。default 与 Stage 18 current sparse-default 的所有共同 emitter artifact byte-exact；本轮仅因当前 Makefile 行为新增 `wolvrix_read_args.txt`，不构成 generated-program 差异。

三套产物的绝对 schedule 指标完全相同：

| metric | default | contiguous | gap |
| --- | ---: | ---: | ---: |
| total supernodes | `63,726` | `63,726` | `63,726` |
| compute supernodes | `63,241` | `63,241` | `63,241` |
| commit supernodes | `485` | `485` | `485` |
| DAG edges | `528,622` | `528,622` | `528,622` |
| boundary activation edges | `1,983,923` | `1,983,923` | `1,983,923` |
| compute-commit value pairs | `262,225` | `262,225` | `262,225` |
| topo edges | `10,150,909` | `10,150,909` | `10,150,909` |

按 emitter-owned/generated artifact 过滤口径，三套均为 `158` 个，其中 `154` 个 `cpp/hpp`，`155` 个 `cpp/hpp/Makefile`，schedule cpp `117` 个。不能把它写成目录当前普通文件总数：O3 build 后 default/contiguous/gap 目录的普通文件总数分别为 `158/312/312`，后两者额外包含 `.o`、archive 等编译产物。三套 name manifest 均为 `8ab07f9511c2fb435c727678915c83792a1645b78c900dda60780b3b907e777a`；non-schedule content manifest 均为 `d293a032a00fba51f997b694bb0faf85c8683b659a8f017a93ba21518f4a725a`；activity stats SHA-256 均为 `e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77`；emit stats SHA-256 均为 `9dd1bdddd01606507b2e3425917f260ca3ac8c5b88c55fa21408bffb17080a8b`；read-args SHA-256 均为 `bd420039afef16f5ba578bf7a3d8e79f1c327b40f921e4d216f5058504de2b9c`。

## 3. table rewrite 与 generated source 绝对值

两个 candidate 都精确选择 `586` 个 generic table groups，原 entries 总数为 `89,903`；contiguous 发出 `19,942` 个 chunks，gap 发出 `17,530` 个 chunks，validator/self-test 均通过，所有 invalid breakdown 均为 `0`。剩余 excluded table loops 为 `23` 个、entries 为 `1,825`，两候选均不改动。

| metric | default | contiguous | gap |
| --- | ---: | ---: | ---: |
| changed schedule files vs default | `0` | `46` | `46` |
| schedule source lines | `13,383,537` | `13,387,907` | `13,385,495` |
| schedule source bytes | `1,331,059,293` | `1,330,387,041` | `1,330,237,815` |
| all generated source lines | `13,684,911` | `13,689,281` | `13,686,869` |
| all generated source bytes | `1,356,877,425` | `1,356,205,173` | `1,356,055,947` |
| table loops | `609` | `23` | `23` |
| table loop entries | `91,728` | `1,825` | `1,825` |
| all schedule numeric writes | `498,773` | `518,715` | `516,303` |

每个 candidate 都有 `586` 个预期 diff hunks，删除 `15,572` 行旧 table-loop 表示；非预期 changed lines 为 `0`。contiguous 与 gap 之间的 generated schedule 差异为 gap 少 `2,412` 行、少 `149,226` bytes。

候选新增 chunk 宽度分布：

| width | contiguous | gap |
| --- | ---: | ---: |
| byte | `7,153` | `4,919` |
| uint16 | `2,659` | `1,139` |
| uint32 | `902` | `979` |
| uint64 | `9,228` | `10,493` |
| total | `19,942` | `17,530` |

上表是从最终 generated source 机械重算的实际插入表示。contiguous emit log 的通用 probe 行仍同时报告 gap planner 的 `candidate_writes=17530` 及 `4,919/1,139/979/10,493` histogram；该行不是 contiguous 实际选择值。contiguous 的实际选择行是 `selected_candidate_writes=19942`，实际宽度以上表 source recount 为准。

包含其它 schedule writes 后的全局宽度分布为：

| width | default | contiguous | gap |
| --- | ---: | ---: | ---: |
| byte | `480,499` | `487,652` | `485,418` |
| uint16 | `15,925` | `18,584` | `17,064` |
| uint32 | `1,688` | `2,590` | `2,667` |
| uint64 | `661` | `9,889` | `11,154` |
| total | `498,773` | `518,715` | `516,303` |

因此 `89,903 -> 19,942/17,530` 是 table lowering 的局部 representation 计数，不能误写为全程序动态 instruction 或全局 write 数。

## 4. O3/ELF gate

两候选的 O3 archive 和 emu link 均通过：

```text
build/logs/xs/stage20_table_contiguous_o3_build_20260717.log
build/logs/xs/stage20_table_gap_o3_build_20260717.log
build/logs/xs/stage20_table_contiguous_emu_build_20260717.log
build/logs/xs/stage20_table_gap_emu_build_20260717.log
```

ELF 绝对值如下；default binary 为 Stage 14 current native-hybrid/cap4096 baseline：

| metric | default | contiguous | gap |
| --- | ---: | ---: | ---: |
| file bytes | `93,694,944` | `93,624,192` | `93,620,096` |
| `.text` bytes | `87,113,502` | `87,244,238` | `87,238,238` |
| `.rodata` bytes | `5,652,584` | `5,465,624` | `5,466,648` |
| `.eh_frame_hdr` bytes | `8,604` | `8,604` | `8,604` |
| `.eh_frame` bytes | `706,632` | `706,592` | `706,592` |
| `.data` bytes | `152` | `152` | `152` |
| `.bss` bytes | `14,688` | `14,688` | `14,688` |

SHA-256：

```text
default     51b74981b0a23d93dc860e13f82248a3ec0c21153117df3f7889da55be918788
contiguous  ceacf895c38f441571301242ff17d89e071330bed598b8ac80e47b74edd944ac
gap         320055d3562cae1855b964ee7755d6a2cf78064bdc58d9889653c97803fa904b
```

相对 default，contiguous `.text` 增加 `130,736` bytes（`+0.150075%`），gap 增加 `124,736` bytes（`+0.143188%`）；gap 比 contiguous 少 `6,000` `.text` bytes（`-0.006877%`）。完整 ELF file size 则分别减少 `70,752` 和 `74,848` bytes，主要来自 `.rodata` 分别减少 `186,960` 和 `185,936` bytes。该结果没有灾难性膨胀，但说明 static chunk-count 减少并不保证 O3 `.text` 减少。

## 5. fixed-ASLR 功能门禁

诊断功能运行绑定 CPU43/NUMA0，使用 `numactl --physcpubind=43 --membind=0`、`taskset -c 43` 和 `setarch x86_64 -R`；它们只作功能门禁，不作 performance 样本。原始日志位于：

```text
build/logs/xs/stage20_table_function_20260717/
```

| candidate | window | Host time | instrCnt | cycleCnt | guest |
| --- | ---: | ---: | ---: | ---: | ---: |
| contiguous | `100` | `225 ms` | `0` | `96` | `101` |
| contiguous | `10,000` | `9,493 ms` | `458` | `9,996` | `10,001` |
| contiguous | `50,000` | `74,576 ms` | `73,580` | `49,996` | `50,001` |
| gap | `100` | `145 ms` | `0` | `96` | `101` |
| gap | `10,000` | `9,521 ms` | `458` | `9,996` | `10,001` |
| gap | `50,000` | `74,695 ms` | `73,580` | `49,996` | `50,001` |

每个 raw log 都恰有一个正 `Host time spent`，六项功能签名全部 PASS。这里没有 whole-node admission/runtime monitor，故上述 walltime 不用于采用决定。

该目录中的功能 raw log 只保存 emu 输出，没有把完整 shell invocation 写入 log；因此绑定命令来自本轮执行记录，不能仅凭这些 raw emu log 独立证明。正式性能样本另有包含 affinity、page placement 和 monitor 的 strict raw 目录，见 TNO0117。

## 6. focused 与完整回归

已通过：

```text
cmake --build wolvrix/build --target emit-grhsim-cpp -j2
WOLVRIX_TEST_ACTIVE_MASK_GAP_PACK=1 wolvrix/build/bin/emit-grhsim-cpp
python3 wolvrix/tests/pybind/test_emit_grhsim_cpp_options.py       # 8/8
python3 scripts/test_wolvrix_xs_grhsim_options.py                  # 16/16
ctest --test-dir wolvrix/build -R '^emit-grhsim-cpp$' --output-on-failure
```

专用 emitter 长测 `1/1` PASS，用时 `294.63s`。完整 build PASS；串行 CTest 绝对结果为 `46/48` PASS、总耗时 `390.52s`。唯一失败仍是历史既有的 `transform-comb-lane-pack` 与 `transform-repcut`，本阶段无新增失败。

本阶段没有把 focused/full CTest stdout 另外保存到 `build/logs`；上述 `294.63s`、`46/48` 和 `390.52s` 来自本轮命令执行记录。该缺失明确保留，不能把 production/runtime log 冒充为 CTest raw log。
