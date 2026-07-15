# TNO0038 Stage 3 full build and functional gate

记录日期：2026-07-14

状态：Stage 3 conservative candidate 完成 full emit、O3/link 与 fixed-ASLR 100/10k/50k 功能门禁，全部 PASS；50k 当时 load 约 22，只作功能记录，正式性能留给 quiet A/B/A。

## 1. Full stats 与静态产物

full build stats 与 [TNO0037](./TNO0037_stage3_standalone_structure_scan_20260714.md) 的 scan 原始 JSON `cmp=0`，SHA256 均为：

```text
61f544c3e3b1bd59e01a0d96e40103e1cbde58834fabf498a027e09260600448
```

| Metric | current default | Stage 3 candidate | Delta |
| --- | ---: | ---: | ---: |
| generated cpp+hpp count | `154` | `154` | `0` |
| generated cpp+hpp bytes | `1,379,126,286` | `1,377,502,621` | `-1,623,665` (`-0.1177%`) |
| sched cpp count | `117` | `117` | `0` |
| sched cpp bytes | `1,353,312,855` | `1,351,689,770` | `-1,623,085` (`-0.1199%`) |
| emu bytes | `94,768,184` | `94,715,496` | `-52,688` (`-0.0556%`) |
| ELF `.text` bytes | `88,186,297` | `88,131,020` | `-55,277` (`-0.06268%`) |

候选哈希：

```text
emu   209ff35eb3a942b9145a7716a948ccb693e6fbf36c479222ee5641aab93e8acf
.text eb20aeab282af5bacc6b65c8ca484b061ee644e5193ad2f624ca52c2042a6a56
```

108 个 true clone 没有造成总 source/ELF 膨胀；反而由于 compute-node/segment 内容重排略微缩小。但 source bytes `-0.118%` 远大于 BAE `-0.0027%`，主要反映布局与分片内容变化，不能直接换算为 runtime。

## 2. Fixed-ASLR functional gates

三轮均使用 `setarch $(uname -m) -R`，CoreMark 2-iteration image 与 NEMU reference 一致：

| Gate | guest cycle | cycleCnt | instrCnt | PC | host wall |
| --- | ---: | ---: | ---: | --- | ---: |
| 100 | `101` | `96` | `0` | `0x0` | `200 ms` |
| 10k | `10,001` | `9,996` | `458` | `0x800027c6` | `10,649 ms` |
| 50k functional | `50,001` | `49,996` | `73,580` | `0x80001312` | `81,460 ms` |

10k/50k 明确打印 `Difftest enabled`；100 在首 commit 前结束，但 reference 初始化正常。三轮 exit `0`，`mismatch/assert/abort/fatal/segfault/refill fail/input_fullpass_blocked` 均为零。

50k 启动前全机 load 约 `22`，没有相邻 current-default control，因此 `81,460 ms` 不参与性能排序。

## 3. 原始产物与下一步

```text
build/xs_activity_stage3_local_clone_full_20260714/grhsim/grhsim-compile/emu
build/logs/xs/xs_wolf_grhsim_build_activity_stage3_local_clone_full_20260714.log
build/logs/xs_activity_stage3_local_clone/candidate_100_fixed_aslr.log
build/logs/xs_activity_stage3_local_clone/candidate_10k_fixed_aslr.log
build/logs/xs_activity_stage3_local_clone/candidate_50k_functional_fixed_aslr.log
```

功能、full rebuild 与静态 code-size gate 均闭合；下一步只使用同 CPU/NUMA、双 sibling quiet gate、fixed-ASLR、五事件 `100% scheduled` 的 current-default/candidate/current-default 50k 包夹裁决。108 个 clone 的结构量级很小，若 cycles 未超过 `1%` 可信线则保持默认关闭，并转向 common-owner no-mutation probe。
