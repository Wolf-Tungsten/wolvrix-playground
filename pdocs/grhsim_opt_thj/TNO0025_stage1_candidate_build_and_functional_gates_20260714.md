# TNO0025 Stage 1 candidate build and functional gates

记录日期：2026-07-14

状态：`strict / balanced / bae-budget` 三组候选均完成同 checkpoint fresh emit、O3 build/link 和 fixed-ASLR 100-cycle、10k、50k 功能门禁，全部 PASS。主机处于高负载时的 50k wall 只作功能诊断；quiet A/B/A 另文记录。

## 1. Default-off identity

Stage 1 core 与 XiangShan 脚本默认 policy 都保持 `off`。同一 fresh checkpoint 上显式 `off` 的 activity schedule stats 与未指定新参数的 current-default stats 完全一致。fresh baseline 与 resume-control 的 `154` 份语义源文件在去除只含 `_op_` / `_val_` 编号的 debug comment 后全部一致；编号差异来自 JSON reload 后的内部 ID 重建，不改变生成语义。

更强的 executable identity 也已闭合：fresh current-default 与 matched resume-control 的 ELF `.text` byte-identical，大小均为 `88,186,297` bytes，SHA256 均为：

```text
b2a030f2b4598c519e6d8812b0b76c6586d9e179c9350f54f1fc2627cbef2e58
```

两者完整 emu SHA 不同来自非 `.text` build metadata，不能据此误判 default-off 语义漂移。

## 2. Fresh build 产物

四组都使用 [TNO0022](./TNO0022_fresh_current_default_no0300_baseline1_20260714.md) 的 pre-reg-to-mem checkpoint，SHA256 为 `55823181a7d73d77f99c3c5e59a09ad3e474051d8eac4c37eb03aaa23db00308`。候选只改变 post-DP refinement policy。

| Metric | current default | strict | balanced | bae-budget |
| --- | ---: | ---: | ---: | ---: |
| generated `.cpp` count | `152` | `154` | `156` | `154` |
| sched `.cpp` count | `117` | `119` | `121` | `119` |
| generated `.cpp` bytes | `1,378,578,889` | `1,374,101,542` | `1,374,327,956` | `1,374,045,126` |
| `.cpp` bytes delta | - | `-4,477,347` | `-4,250,933` | `-4,533,763` |
| emu bytes | `94,768,184` | `94,592,144` | `94,559,136` | `94,567,664` |
| ELF `.text` bytes | `88,186,297` | `88,009,949` | `87,971,429` | `87,980,053` |
| `.text` delta | - | `-176,348` | `-214,868` | `-206,244` |

ELF `.text` SHA256：

| Candidate | SHA256 |
| --- | --- |
| current default | `b2a030f2b4598c519e6d8812b0b76c6586d9e179c9350f54f1fc2627cbef2e58` |
| strict | `6871154274fb68f2fbf3744aa0378c5e78085c62ac6f89e4860ffe8779917207` |
| balanced | `5684fa8f50e5d794e0e3c15f2aebf4f9df84b39bc9430ffeef2e87f38d47f04e` |
| bae-budget | `b49ae9bbc3a4633d93ff25659623f959749a56af8f410034b470622da56343b3` |

候选在相同 supernode 数下多出 `2..4` 个 sched translation unit，是 batch estimated-line 边界随 schedule 变化后的重新切分，不等同于 emitted work 增加。三组的 generated `.cpp` 总量和最终 `.text` 反而都下降；balanced 虽比 strict 多两个 sched cpp，`.text` 仍比 strict 少 `38,520` bytes。

主要产物：

```text
build/xs_activity_stage1_strict_r1_20260714/grhsim/grhsim-compile/emu
build/xs_activity_stage1_balanced_r1_full_20260714/grhsim/grhsim-compile/emu
build/xs_activity_stage1_bae_budget_r1_full_20260714/grhsim/grhsim-compile/emu
build/logs/xs/xs_wolf_grhsim_build_activity_stage1_strict_r1_candidate_20260714.log
build/logs/xs/xs_wolf_grhsim_build_activity_stage1_balanced_r1_candidate_20260714.log
build/logs/xs/xs_wolf_grhsim_build_activity_stage1_bae_budget_r1_candidate_20260714.log
```

## 3. Functional gates

三组 fixed-ASLR 100-cycle 均以 guest cycle `101`、`cycleCnt=96`、`instrCnt=0` 正常退出。10k 均启用 difftest，并以 guest cycle `10001`、`cycleCnt=9996`、`instrCnt=458`、PC `0x800027c6` 正常退出。

三组 50k 终点完全一致：

```text
guest cycle = 50001
cycleCnt    = 49996
instrCnt    = 73580
PC          = 0x80001312
```

日志均无 mismatch、assert、abort、fatal、refill fail 或 `input_fullpass_blocked`。50k 结果：

| Candidate | fixed-ASLR 50k | host wall | 性质 |
| --- | --- | ---: | --- |
| strict | PASS | `78,927 ms` | 高负载 functional diagnostic |
| balanced | PASS | `85,176 ms` | 高负载 functional diagnostic |
| bae-budget | PASS | `79,241 ms` | 高负载 functional diagnostic |

三次 wall 不在相邻 current-default baseline 包夹下，且主机负载明显变化，禁止横向排序。它们只闭合“候选在最终 50k workload 上功能正确”的门禁。

## 4. Test status

本阶段直接相关测试：

```text
emit-grhsim-cpp              PASS  241.65 s（focused run）
transform-activity-schedule  PASS    0.03 s
```

全目标重新 build 后执行完整 48 项 CTest。44 项在完整轮中 PASS；最初因 test executable 未随静态库重链接而触发 stack protector 的 `emit-grhsim-cpp-memory-fill` 与 `ingest-graph-assembly-aggregate-port-slice`，在完整 rebuild 后单独重跑均 PASS。剩余两个失败为：

```text
transform-comb-lane-pack  Expected one packed kAnd for storage frontier rewrite
transform-repcut          expected repcut partition static feature export
```

这两个测试不经过 activity-schedule，修改文件也不涉及对应 pass。更重要的是，它们已在 isolated fresh baseline worktree、未修改的 Wolvrix `84dbd2ca88fdc27a37ce7a3b3a3840fbdd4f4b8d` 二进制上逐项复现相同错误，因此是本阶段开始前已有的 baseline failure，不是 Stage 1 回归。按这一对照，Stage 1 相对基线没有新增 CTest failure。

## 5. 当前结论

三种 refinement 都在保持 graph/SN/cap/commit 语义不变时减少 BAE、DAG、generated C++ 和 ELF `.text`，并通过 SimTop 50k 功能门禁。它们仍不能被称为性能正收益；正式裁决需要等待双 SMT sibling quiet gate，通过同 CPU/NUMA、fixed-ASLR、五事件 PMU 的 `control / candidate / control` 包夹。若主机持续繁忙，本文的功能结果保留，但不能用高负载 wall 代替 A/B/A。
