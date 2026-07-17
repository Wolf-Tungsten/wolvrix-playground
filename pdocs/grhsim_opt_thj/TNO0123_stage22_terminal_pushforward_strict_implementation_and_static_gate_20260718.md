# TNO0123 Stage 22 terminal pushforward strict implementation and static gate

记录日期：2026-07-18

状态：terminal common-target pushforward `strict` 已完成实现、focused、production exact validator、generated-C++ 审计、Clang O3/emu 构建和 fixed-ASLR 100/10k/50k 功能门禁。最终代码复核后又从同一 Stage 8 post-stats 完整重跑 production emit；默认 selection 实际移动 `128` 个 1-op compute node，compute/total BAE 与 boundary value 均精确减少 `128`，logical boundary-byte proxy 减少 `183`；DAG、topo、compute-commit 和 batch membership 不变。C++ native default 仍为 `off`。Stage 7+ 在本阶段同时补齐 cap8192 的最后一组 N0 BAAB，并触发 current-default 重新评估，因此本候选不在旧 cap4096 baseline 上形成采用结论；后续须基于更新后的仓库默认重新 emit 和测 SimTop 50k walltime。

## 1. strict 实现边界

`final-terminal-pushforward-policy` 现在接受：

```text
off
probe
strict
```

C++ native default 保持 `off`，XS 仍只做 sparse override，没有脚本专用默认。strict 复用 probe 的 exact candidate 和稳定 selection，但增加以下硬门：

- strict candidate 的 `added_bae`、`added_boundary_values`、`added_logical_bytes` 必须全部为 `0`；也就是 candidate input 在 baseline 已经直接激活 target。该 gate 在排序、touched-SN conflict 和 move/PPM budget selection 之前执行，不能让 non-zero-add 候选先占预算、再到 apply 阶段令整个 pass 失败；probe 仍保留所有满足正净收益 gate 的候选。
- 只支持 `final-topo-policy=level-id`；实际发生 oversize compute-node split 时拒绝。
- 不允许与 `final-fanin-pullback-policy=strict` 同时启用。
- apply 时重新验证 compute-node/source/target owner、source 非空、target capacity、input def 和 output 唯一 fanout，不能只信 probe plan。
- selected source/target supernode 必须两两不相交；实际 applied 数和三项 gain 总和必须与 evaluator 完全一致。

operation layout 使用 stable splice，而不是对整个 source/target 重新 topo-sort：source 只稳定过滤 moved op block；moved block 保留 baseline source 中的相对顺序，插到 target 最早 external-output consumer 之前；两个 supernode 中其它 op 的相对顺序完全不变。另有只验证、不改写的 local dependency order checker，显式覆盖 operand 和 reg-to-mem implicit index dependency。

rebuild derived schedule 后逐项验证：

```text
supernode count/kinds
scheduled-op multiset and uniqueness
compute capacity and non-empty invariant
commit partition
compute-node partition and moved owner
exact stable-splice op/node vectors
DAG and topo order
state-read supernode sets
compute-commit count and full (value, commit-SN) pairs
full value fanout
value source kind and expected moved-result source SN
compute BAE projected/actual gain
total boundary activation-edge projected/actual gain
boundary-value projected/actual gain
logical boundary-byte projected/actual gain
```

logical bytes 按仍有 external fanout 的 Logic value 求 `ceil(width/8)`，只是 value-width proxy，不是 emitter slot、alignment、source 或 ELF bytes。

## 2. focused strict gate

正例包含 `6` 个 compute op，baseline final partition 为：

```text
source = [producer, candidate, delay, barrier]
target = [target_prefix, tail]
```

strict 后精确为：

```text
source = [producer, delay, barrier]
target = [target_prefix, candidate, tail]
```

`target_prefix` 证明插入点是最早 output consumer 前，而不是 target 起始位置；其它 op 顺序不变。absolute summary 为 compute BAE `3 -> 2`、total BAE `3 -> 2`、boundary values `3 -> 2`、logical bytes `3 -> 2`、DAG edges `1 -> 1`；candidate output fanout 从 `{target}` 变为空，candidate input fanout 完全不变。另一个 `non-zero-add` 正净收益用例在 probe 中精确为 removed/added BAE `2/1`、boundary values `2/1`、logical bytes `2/1`，而 strict 在 selection 前将其过滤，得到 exact eligible/selected/applied `0/0/0` 和 schedule identity。default/off/probe session identity、strict deterministic repeat、zero-move strict identity、CLI 两种形式、非法 policy/PPM、non-level topo 和双 strict 冲突均有门禁。

focused 原始日志：

```text
build/logs/xs/stage22_terminal_pushforward_strict_focused_20260718.log
```

通过：

```text
cmake --build wolvrix/build --target transform-activity-schedule -j2
wolvrix/build/bin/transform-activity-schedule
python3 wolvrix/tests/pybind/test_activity_schedule_options.py   # 5/5
python3 scripts/test_wolvrix_xs_grhsim_options.py                # 17/17
git diff --check
git -C wolvrix diff --check
```

## 3. production strict absolute validators

输入仍从 current post-stats 恢复：

```text
build/xs_activity_stage8_dp_p050_20260715/grhsim/wolvrix_xs_post_stats.json
```

输出和原始日志：

```text
build/xs_activity_stage22_terminal_pushforward_strict_20260718/grhsim/grhsim_emit/
build/logs/xs/xs_wolf_grhsim_build_activity_stage22_terminal_pushforward_strict_20260718.log
```

evaluator 保持 Stage 21 的绝对结果：`1,092,530` scanned、`287,944` pure、`1,054` exact eligible、`128` selected/applied、`128` moved ops、moved-op limit `1,125`。move limit reject `514`、touched-SN conflict reject `412`、budget reject `0`、strict non-zero-add reject `0`。最后一项证明本轮 production 的 `1,054` 个 exact 候选本身全是 zero-add；focused 独立用例负责覆盖该 reject 非零的路径。

strict absolute before/after：

| metric | before | after | delta |
| --- | ---: | ---: | ---: |
| compute supernodes | `63,241` | `63,241` | `0` |
| commit supernodes | `485` | `485` | `0` |
| DAG edges | `528,622` | `528,622` | `0` |
| compute-compute value pairs | `1,721,698` | `1,721,570` | `-128` |
| total boundary activation edges | `1,983,923` | `1,983,795` | `-128` |
| boundary values | `1,000,463` | `1,000,335` | `-128` |
| logical boundary-byte proxy | `2,614,060` | `2,613,877` | `-183` |
| compute-commit value pairs | `262,225` | `262,225` | `0` |

selected kind 为 `kNot:68`、`kSliceStatic:27`、`kLogicNot:22`、`kOr:9`、`kAnd:2`；`128` 个全部为 1-op。所有 validator 均为 `true`：

```text
supernodes kinds scheduled_ops capacity commit compute_partition stable_splice
dag topo state_read compute_commit value_fanout value_source
bae_gain boundary_activation_edge_gain boundary_value_gain
boundary_logical_byte_gain
```

最终 production revalidation 的 activity-schedule pass 用时 `175,302ms`；其中 strict evaluator/apply/rebuild/validator 为 `11,414ms`。write C++ 用时 `59,064ms`，Python flow 总计 `262,995ms`。以上均为当前 raw log 的绝对值；首次实现跑的对应绝对值为 `180,375/11,515/59,676/268,967ms`，仅记录运行时间波动，结构输出相同。

## 4. generated C++ mechanical audit

default 与 strict basename 集合均为 `158` 项，无新增/缺失。排除 strict O3 后生成的 `152 .o + 1 .pch + 1 .a` 编译产物后，`109` 文件 changed、`49` 文件 identical；其中 `104` 个 schedule cpp changed，另五项为 schedule stats、header、state、state-init 和 path-bearing read args。

| source metric | current default | strict | delta |
| --- | ---: | ---: | ---: |
| schedule cpp files | `117` | `117` | `0` |
| schedule cpp bytes | `1,331,059,293` | `1,331,001,589` | `-57,704` |
| schedule cpp lines | `13,383,537` | `13,382,596` | `-941` |
| all 158 files bytes | `1,356,883,524` | `1,356,825,873` | `-57,651` |
| all 158 files lines | `13,685,132` | `13,684,191` | `-941` |

raw diff 的 slot index 连锁压缩很大；把直接 slot index 和 ordered-write base index 归一化后，只剩 `54` 个 compute batch 有语义差异，精确等于 `128` 个 move 的 source batch `42` 个与 target batch `43` 个之并集。`127` 个 move 跨 batch，`1` 个在同 batch；`63,726` 个 SN 的 ID、SN-to-batch、batch 内顺序、`66` 个 compute function和 `51` 个 commit function归属全部不变。

baseline 中 `128` 个 selected output value 各有一处 standalone materialization comment、两处 changed-value reference；strict 中全部为 `0`。standalone op comments 从 `2,128,344` 减到 `2,128,216`，恰少 `128`，目标 op 在 target 内联执行，并非丢失。slot 绝对变化为 bool `651,848 -> 651,747`、u16 `26,316 -> 26,304`、u32 `8,585 -> 8,570`，总计减少 `128` slots；物理 slot bytes 减少 `185`，与 logical proxy `183` 的差别来自类型/padding。

`grhsim_emit_stats.json` 保持 byte-exact：

```text
9dd1bdddd01606507b2e3425917f260ca3ac8c5b88c55fa21408bffb17080a8b
```

最终 revalidation 再次得到 `158` 个生成文件、`117` 个 schedule cpp；schedule cpp 绝对总量仍为 `13,382,596` lines、`1,331,001,589` bytes，和首次审计完全一致。production validator 日志新增并通过 `stable_splice=true`，selection 日志新增 `rejected_strict_non_zero_add=0`；所有结构绝对值和上述 SHA-256 均未改变。

`wolvrix_read_args.txt` 只因 include path 指向 Stage 21 fresh RTL 而改变。Stage 20 的 `build/xs/rtl/rtl` 与本轮 RTL 树各有 `2,100` 文件，其中 `Bpu.sv/Ftq.sv/LogPerfEndpoint.sv/SimTop.fir` 四项内容不同，不能写成 RTL 副本 byte-exact。两轮 activity schedule 都使用 `RESUME_FROM_STATS_JSON=1` 且读取同一 Stage 8 post-stats，故本轮 generated-program 差异仍从相同 graph input 闭合；以后非 resume 实验不能沿用该假设。

## 5. O3, ELF and functional gate

generated Makefile 的 PCH 规则要求 Clang。首次未显式指定 `CXX`，环境默认 `g++` 因不支持该 `-include-pch` 用法立即失败；失败原始日志保留：

```text
build/logs/xs/stage22_terminal_pushforward_strict_o3_build_20260718.log
```

清除本轮失败对象/PCH 后，显式 `CXX=clang++` 的 O3 archive 和 emu link 均通过：

```text
build/logs/xs/stage22_terminal_pushforward_strict_o3_clang_build_20260718.log
build/logs/xs/stage22_terminal_pushforward_strict_emu_build_20260718.log
```

strict archive 为 `99,288,346` bytes。ELF absolute values：

| metric | current default | strict | delta |
| --- | ---: | ---: | ---: |
| file bytes | `93,694,944` | `93,666,272` | `-28,672` |
| `.text` | `87,113,502` | `87,084,574` | `-28,928` |
| `.rodata` | `5,652,584` | `5,652,472` | `-112` |
| `.eh_frame_hdr` | `8,604` | `8,604` | `0` |
| `.eh_frame` | `706,632` | `707,008` | `+376` |
| `.data` | `152` | `152` | `0` |
| `.bss` | `14,688` | `14,688` | `0` |

SHA-256：

```text
current default  51b74981b0a23d93dc860e13f82248a3ec0c21153117df3f7889da55be918788
strict           4b4e8ca2a57b3e9059dbecd09d84db06dc3e98957f9abbd48f0466626c550da4
```

fixed-ASLR 功能运行使用：

```text
taskset -c 43 numactl --physcpubind=43 --membind=0 \
  setarch x86_64 -R <strict-emu> ... -C <window>
```

| window | Host time | instrCnt | cycleCnt | guest |
| ---: | ---: | ---: | ---: | ---: |
| `100` | `192 ms` | `0` | `96` | `101` |
| `10,000` | `9,515 ms` | `458` | `9,996` | `10,001` |
| `50,000` | `74,552 ms` | `73,580` | `49,996` | `50,001` |

三个 raw log 各有且仅有一个正 `Host time spent`，exit 均为 `0`：

```text
build/logs/xs/stage22_terminal_pushforward_strict_function_100_20260718.log
build/logs/xs/stage22_terminal_pushforward_strict_function_10000_20260718.log
build/logs/xs/stage22_terminal_pushforward_strict_function_50000_20260718.log
```

这些是功能门禁，没有 whole-node admission/runtime monitor，不用于性能采用结论。

## 6. regression and next step

完整 build PASS，原始日志：

```text
build/logs/xs/stage22_terminal_pushforward_strict_full_build_20260718.log
```

串行 full CTest 为 `46/48` PASS、总耗时 `386.05s`。唯一失败仍是此前各阶段相同的：

```text
transform-comb-lane-pack
transform-repcut
```

activity-schedule、emitter 长测、memory-fill 和全部 ingest 均通过，无新增失败。原始日志：

```text
build/logs/xs/stage22_terminal_pushforward_strict_full_ctest_20260718.log
```

Stage 7+ 的最后一组 N0 cap8192 BAAB 已在正确 page-local strict protocol 下完成，并使 cap8192 的 N0/N1 四个顺序组全部同向改善。仓库 current default 因此需要先重新裁决。若 commit cap 改为 `8192`，本阶段基于旧 cap4096 的 strict ELF 只保留结构/功能证据；后续必须从新 current-default post-stats/emit 重新生成 off/strict 双方，再用独立 `/dev/shm` inode 和双 NUMA balanced 50k walltime 裁决 terminal pushforward 默认。
