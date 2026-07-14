# TNO0022 Fresh current-default NO0300 baseline1

记录日期：2026-07-14

状态：PASS；完成当前仓库默认 GrhSIM 配置的 fresh generate/build、100-cycle、10k 和 quiet fixed-ASLR 50k。本文结果固定为后续 activity-schedule 候选 A/B/A 的 `baseline1`，单独一轮不构成候选性能结论。

## 1. 基线身份

本轮落实 [TNO0021](./TNO0021_current_default_baseline_and_stage1_refinement_plan_20260714.md) 的唯一基线要求：从当前仓库与 `wolvrix` 子模块 HEAD fresh 执行 frontend、pre-schedule pipeline、activity schedule、C++ emit、O3 编译和链接，未恢复旧 checkpoint，也未使用跨工作区的默认 GSim symlink。配置就是当前默认 NO0300，即 ordered memory-write affine-loop、plain activity schedule、ASLR 关闭的口径；不是历史 emu 的复用。

| Repository / artifact | SHA |
| --- | --- |
| parent | `2eb5ea7460f583207e6773042a2a6ac7c2118cc7` |
| `wolvrix` | `84dbd2ca88fdc27a37ce7a3b3a3840fbdd4f4b8d` |
| `xiangshan` | `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6` |
| `slang` | `301723fe5993f8b08ddb933de501b17531d875a5` |
| `libfst` | `2188498e74e044f6e4371eee78051389f4bdd304` |
| `mt-kahypar` | `d22e61437568c151d1d2e04d2d7eced052c41042` |
| isolated Python `_wolvrix.so` | `13d0737bfc852c5682c8f7974ed60080a218a4b6fd757ac2d3af5656af18364e` |
| isolated Python `libwolvrix-lib.so` | `635ef29a68d7a9b6cd1d4bbdb56ab3a2955b2f2b200e2e424dd78fcc0726b09a` |
| `xs_wolf.f` | `9784d4b0de5d7f0015efc6cda7a89fd9483e109fde59bc5c11690b7cdbff7970` |
| `SimTop.fir` | `7f81e642034ed6f37100865a7fda7ba348e8f880f8a009d8241f3cf2884a4527` |
| pre-reg checkpoint | `55823181a7d73d77f99c3c5e59a09ad3e474051d8eac4c37eb03aaa23db00308` |
| generated C++/header manifest | `c607bd19c097f2faaabd38f110aaa709ec526a33fba0b68bc06b18758c481f73` |
| final `emu` | `bb04da578790a064cb8d54d782c6b946cf5cc347ff8f8e2cb37476d66884e265` |

pre-reg checkpoint 为 `3,059,941,953` bytes；generated source 共 `154` 个 C++/header 文件、`1,379,126,286` bytes。最终 PIE `emu` 为 `94,768,184` bytes，`.text` 为 `88,186,297` bytes。

隔离 worktree 与日志保留在：

```text
build/worktrees/activity_baseline_20260714
build/worktrees/activity_baseline_20260714/build/logs/xs_activity_baseline
```

## 2. 当前默认生成配置

生成日志确认没有混入 direct state-read、full active-word、pure-event 或 profile 开关：

| Setting | Current default |
| --- | --- |
| compute supernode / compute node cap | `108 / 108` |
| split oversize compute nodes | `true` |
| commit cap / guard event buckets | `4096 / true` |
| schedule batch max ops / estimated lines | `2048 / 8192` |
| schedule batch target count / batches per C++ | `64 / 1` |
| emit parallelism | `4` |
| storage ref aliases | `0 (xs_default)` |
| reg-to-mem intent / ordered writes / decoded-write storage | `true / true / true` |
| declared-value compute boundary | `false` |
| full active-word consume | `false` |
| final topology | `level-id` |
| simplify keep declared symbols / skip comb lane pack | `false / false` |
| export compute DAG / schedule stats | `off / off` |
| waveform / perf instrumentation | `off / off` |

本轮显式 `XS_WOLF_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON=0`；因此 checkpoint 是 fresh 产物，而不是输入。

## 3. Activity-schedule 结构

| Metric | Fresh current default |
| --- | ---: |
| graph ops / values | `7,204,108 / 6,833,009` |
| supernodes | `63,726` |
| compute / commit supernodes | `63,241 / 485` |
| DAG edges | `528,622` |
| boundary values | `1,000,463` |
| boundary activation edges | `1,983,923` |
| compute-compute value pairs | `1,721,698` |
| compute-commit value pairs | `262,225` |
| compute ops max / p99 | `108 / 108` |
| commit ops max | `42,937` |
| source clones | `2,045,861` |
| local shared-compute clones | `0` |

这些数值逐项复现 [TNO0021](./TNO0021_current_default_baseline_and_stage1_refinement_plan_20260714.md) 引用的历史 [NO0300](../grhsim_opt/NO0300_ordered_memory_write_affine_loop_fresh_gate_20260712.md) 锚点。由此确认当前 HEAD 的默认生成配置仍是本阶段约定的 NO0300 结构基线，无需恢复历史开关来对齐。

## 4. 功能门禁

所有运行均使用 CoreMark 2-iteration image、NEMU difftest、`-b 0 -e 0` 和：

```text
numactl --physcpubind=<CPU> --membind=<NODE> perf stat <five events> -- \
  setarch $(uname -m) -R ./emu ... -C <limit>
```

| Run | CPU / sibling / NUMA | Pre-run idle | guest / cycleCnt / instr / PC | Host | PMU |
| --- | --- | --- | --- | ---: | --- |
| 100 | `144 / 336 / 1` | `98.33% / 98.34%`，未过 quiet gate | `101 / 96 / 0 / 0x0` | `214 ms` | five events `100%` |
| 10k | `175 / 367 / 1` | `99.67% / 99.00%` | `10,001 / 9,996 / 458 / 0x800027c6` | `10,169 ms` | five events `100%` |
| 50k `baseline1` | **`106 / 298 / 1`** | **`100% / 100%`** | `50,001 / 49,996 / 73,580 / 0x80001312` | `77,594 ms` | five events `100%` |

100-cycle 的实际运行前 gate 未满足 `>=99%`，所以其 host time 只作功能记录；随后对相同 CPU 的补测 survey 达到 `99.34% / 99.67%`，但它发生在该次运行之后，不能倒算为通过。10k 和 50k 均在通过对应 pre-run gate 后执行。三次 fixed-ASLR 运行的 `DIFFTEST` state 地址均为 `0x55555afa4d30`，证明关闭 ASLR 的 load base 一致。

日志扫描未发现 mismatch、assertion、abort、fatal、segmentation fault 或 `input_fullpass_blocked`。100、10k 与 50k 功能终点均符合既定门禁。

## 5. Quiet fixed-ASLR 50k PMU

`baseline1` 在 CPU **106**、SMT sibling **298**、NUMA node 1 上运行；三秒 pre-run survey 的两条硬件线程每秒均为 `100% idle`，五个 PMU 事件均为 `100.00% scheduled`。

| PMU metric | Count |
| --- | ---: |
| cycles | `283,839,654,657` |
| instructions | `172,881,401,671` |
| IPC | `0.609081` |
| frontend empty slots | `1,296,103,823,537` |
| frontend cmask6 cycles | `168,185,429,546` |
| backend stalls | `95,952,783,783` |

`perf` time-enabled 为 `77.579016950 s`，与 emu 报告的 `77,594 ms` 一致。该轮同时满足功能、quiet、fixed-ASLR 和 PMU 调度条件，因此可作为正式夹测的第一条 baseline；但只有在同一 CPU **106/298** 上完成候选和 `baseline2`，并满足两次 baseline cycles spread `<=1%` 后，才能裁决候选收益。当前不得用 `baseline1` 与其他日期、CPU 或随机 ASLR 的历史数值直接下性能结论。

## 6. 后续使用约束

- schedule-only 候选可复用本轮 pre-reg checkpoint，但必须归档候选 schedule stats、generated manifest 和 emu SHA。
- 候选若不是明显结构爆炸或功能失败，仍进入 SimTop 50k；BAE、DAG 与 value-pair 是软指标，最终以 50k 为准。
- 正式 runtime 顺序固定为 `baseline1 / candidate / baseline2`，优先保持 CPU106、sibling298、NUMA1 和 fixed-ASLR 不变。
- 当前 worktree 中的 checkpoint 和 baseline emu 在本阶段夹测结束前不得清理或覆盖。

关键原始文件为 `baseline_metadata.txt`、`xs_wolf_grhsim_build_activity_baseline_fresh_20260714.log`、`baseline_50k_{quiet_gate_attempt2,perf.csv,emu.log}`；它们均位于上面的隔离日志目录。
