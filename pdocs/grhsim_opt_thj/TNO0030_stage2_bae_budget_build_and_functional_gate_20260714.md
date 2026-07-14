# TNO0030 Stage 2 bae-budget build and functional gate

记录日期：2026-07-14

状态：Stage 2 standalone `bae-budget` 完成 fresh emit、O3 build/link 和 fixed-ASLR 100-cycle、10k、50k 功能门禁，全部 PASS；本文不使用高负载 50k wall 下性能结论。

## 1. Candidate 配置与最终结构

候选复用 [TNO0022](./TNO0022_fresh_current_default_no0300_baseline1_20260714.md) 的 fresh pre-reg-to-mem checkpoint，read args 与 baseline `cmp=0`。显式配置：

```text
kahn_level_pack_policy=bae-budget
kahn_level_pack_max_moves=4096
kahn_level_pack_max_moved_op_ppm=10000
kahn_level_pack_max_regression_ppm=10000
post_dp_refine_policy=off
```

exact whole-candidate gate 采用结果：

| Metric | current default | Stage 2 candidate | Delta |
| --- | ---: | ---: | ---: |
| total / compute / commit SN | `63726 / 63241 / 485` | `63651 / 63166 / 485` | `-75 / -75 / 0` |
| compute BAE | `1,721,698` | `1,721,423` | `-275` (`-0.0160%`) |
| compute-commit pairs | `262,225` | `262,225` | `0` |
| total BAE | `1,983,923` | `1,983,648` | `-275` (`-0.0139%`) |
| DAG edges | `528,622` | `529,261` | `+639` (`+0.1209%`) |
| boundary values | `1,000,463` | `1,000,457` | `-6` |
| compute ops p99 / max | `108 / 108` | `108 / 108` | `0 / 0` |

pack 日志为 `candidate_built=true / final_topo_valid=true / adopted=true`；`420` swaps、`840` moved clusters、`56,251` moved ops，耗时 `3,713 ms`。final actual recount 精确复现 candidate BAE/DAG，commit base 随 `63,166` 个 compute SN 重映射正确。

## 2. Generated code 与 ELF

| Metric | current default | Stage 2 candidate | Delta |
| --- | ---: | ---: | ---: |
| generated cpp+hpp count | `154` | `155` | `+1` |
| generated cpp+hpp bytes | `1,379,126,286` | `1,377,376,198` | `-1,750,088` |
| sched cpp count | `117` | `118` | `+1` |
| sched cpp bytes | `1,353,312,855` | `1,351,566,423` | `-1,746,432` |
| emu bytes | `94,768,184` | `94,755,560` | `-12,624` |
| ELF `.text` bytes | `88,186,297` | `88,168,018` | `-18,279` (`-0.0207%`) |

候选 emu SHA256：

```text
8140d7f146fb26d30df0d70668ad8110a4c2877424b56bc2488dab0580f75862
```

候选 `.text` SHA256：

```text
6b00f6ab7d37d5adf751f8568c5a8b925e4e43653fed881ba62dd4371c3eed0f
```

SN 减少并没有转化成同量级 code-size 收益；`.text` 仅下降 `0.0207%`，说明大部分变化是相同工作在略少的 dispatch 单元中重排。新增一个 sched translation unit 也可能抵消部分调度收益。

主要产物：

```text
build/xs_activity_stage2_kahn_bae_budget_20260714/grhsim/grhsim-compile/emu
build/logs/xs/xs_wolf_grhsim_build_activity_stage2_kahn_bae_budget_candidate_20260714.log
```

## 3. Fixed-ASLR functional gates

三轮均使用 `setarch $(uname -m) -R`，difftest 正常启用，负向关键词扫描为零：

| Gate | guest cycle | cycleCnt | instrCnt | PC | host wall |
| --- | ---: | ---: | ---: | --- | ---: |
| 100 | `101` | `96` | `0` | `0x0` | `228 ms` |
| 10k | `10,001` | `9,996` | `458` | `0x800027c6` | `10,359 ms` |
| 50k | `50,001` | `49,996` | `73,580` | `0x80001312` | `79,337 ms` |

50k 当时全机 load 约 `42`，且没有相邻 current-default control，因此 `79,337 ms` 只闭合最终 workload 功能，不参与性能排序。原始日志：

```text
build/logs/xs_activity_stage2_kahn_bae_budget/candidate_100_fixed_aslr.log
build/logs/xs_activity_stage2_kahn_bae_budget/candidate_10k_fixed_aslr.log
build/logs/xs_activity_stage2_kahn_bae_budget/candidate_50k_functional_fixed_aslr.log
```

## 4. 当前结论

Stage 2 mixed candidate 在功能与 exact invariants 上成立，结构变化温和：SN 减少 `75`，BAE 基本不变，DAG 增加 `0.121%`，`.text` 减少 `0.021%`。它符合用户要求的“轻微退化也跑 50k”，但静态量级不足以推断正收益；正式判断留给同 CPU/NUMA、fixed-ASLR、五事件 PMU 的 quiet A/B/A。
