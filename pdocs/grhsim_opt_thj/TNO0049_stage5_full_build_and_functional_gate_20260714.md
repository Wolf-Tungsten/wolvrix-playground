# TNO0049 Stage 5 full build and functional gate

记录日期：2026-07-14

状态：Stage 5 common-owner strict 完成 full emit、O3/link、fixed-ASLR 100/10k/50k 功能门禁及 Wolvrix 全量回归；功能全部 PASS，静态 code size 无膨胀，进入 quiet A/B/A。

## 1. Full build identity

full build 使用与 [TNO0048](./TNO0048_stage5_common_owner_strict_structure_gate_20260714.md) 相同配置和独立目录：

```text
build/xs_activity_stage5_common_owner_strict_full_20260714/grhsim
```

full stats SHA256 为：

```text
4bbaf4d67bc439a0cc618f5e33d019dfe081f7a242e9720e64211bb7ecf8e017
```

与 structure scan 原始 JSON `cmp=0`，确认 full 产物仍是同一组 555 个 clone、SN `-5`、BAE `-567`、DAG `+8` 的 schedule。full emit+O3/link exit `0`，wall `9:59.51`，peak RSS `28,326,424 KiB`。

## 2. Generated code 与 ELF

| Metric | current default | Stage 5 strict | Delta |
| --- | ---: | ---: | ---: |
| generated cpp+hpp count | `154` | `154` | `0` |
| generated cpp+hpp bytes | `1,379,126,286` | `1,377,433,588` | `-1,692,698` (`-0.122737%`) |
| sched cpp count | `117` | `117` | `0` |
| sched cpp bytes | `1,353,312,855` | `1,351,621,837` | `-1,691,018` (`-0.124954%`) |
| emu bytes | `94,768,184` | `94,718,752` | `-49,432` (`-0.052161%`) |
| ELF `.text` bytes | `88,186,297` | `88,133,332` | `-52,965` (`-0.060060%`) |

Stage 5 hashes：

```text
emu   2e22eb65a0e0d923911bc5b329108436df5bd81400a5d46f4567630d3829fdaf
.text 330ea839f28a31693023ace88caa105b9d885e466a5774a293217f4d7dd1fbaf
```

相对 [TNO0038](./TNO0038_stage3_full_build_and_functional_gate_20260714.md) 的 108-clone candidate，Stage 5 source/sched 又分别减少 `69,033/67,933` bytes，但 emu/`.text` 增加 `3,256/2,312` bytes，均小于 `0.006%`。555 个 common-owner clone 没有造成 source、binary 或单批次数量膨胀；这些微小 layout 差异仍不能替代 runtime 测量。

## 3. Fixed-ASLR functional gates

三轮均使用 `setarch x86_64 -R`，CoreMark 2-iteration image 与 NEMU reference：

| Gate | guest/cycleCnt/instrCnt | PC | Difftest | host wall |
| --- | --- | --- | --- | ---: |
| 100 | `101/96/0` | `0x0` | first commit 前 | `462 ms` |
| 10k | `10001/9996/458` | `0x800027c6` | enabled | `10,115 ms` |
| 50k | `50001/49996/73580` | `0x80001312` | enabled | `82,339 ms` |

三轮 exit `0`；`mismatch/assert/abort/fatal/segfault/refill fail/input_fullpass_blocked` 均为 0。功能测试与全量 CTest 并发，host wall 只记录功能，不参与性能排序。

## 4. Wolvrix 回归

最终增量 build exit `0`。CTest 为 `46/48 PASS`，`transform-activity-schedule` PASS（`0.03 s`），`emit-grhsim-cpp` PASS（`231.03 s`）。仅有两项既有 baseline 失败：

```text
transform-comb-lane-pack: Expected one packed kAnd for storage frontier rewrite
transform-repcut: expected repcut partition static feature export
```

签名与 [TNO0025](./TNO0025_stage1_candidate_build_and_functional_gates_20260714.md) 和 [TNO0035](./TNO0035_stage3_true_clone_implementation_and_correctness_20260714.md) 一致，无新增失败。

## 5. 原始产物与下一步

```text
build/logs/xs/xs_wolf_grhsim_build_activity_stage5_common_owner_strict_full_20260714.log
build/logs/xs_activity_stage5_common_owner_strict/candidate_100_fixed_aslr.log
build/logs/xs_activity_stage5_common_owner_strict/candidate_10k_fixed_aslr.log
build/logs/xs_activity_stage5_common_owner_strict/candidate_50k_fixed_aslr.log
build/xs_activity_stage5_common_owner_strict_full_20260714/grhsim/grhsim-compile/emu
```

下一步使用 current-default/candidate/current-default、同 CPU/NUMA、fixed-ASLR、五 PMU events 和 atomic quiet gate 做正式 50k 包夹。只有该结果用于默认配置决策。

## 6. 勘误：emu SHA

§2 初始记录的 emu SHA `2e22...` 是并发静态取证过程中的过渡观测值，不是后续功能/性能使用的正式 artifact。正式 ELF 的 authoritative SHA 为：

```text
8e752d94d1813f0860b6757004717c71f39732f0a8291e0994e024c39bb53c34
```

size 与 `.text` size/SHA 均不变；详细时间线与运行前后校验见 [TNO0050](./TNO0050_stage5_quiet_aba_and_default_decision_20260714.md)。
