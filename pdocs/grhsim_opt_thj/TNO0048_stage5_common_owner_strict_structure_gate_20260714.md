# TNO0048 Stage 5 common-owner strict structure gate

记录日期：2026-07-14

状态：fixed commit seed 后的第三次 SimTop strict structure scan PASS；555 个 common-owner clone 使 BAE 小幅下降、DAG 轻微增加，结构变化温和，按软门槛继续 full O3 与 fixed-ASLR 50k。

## 1. 配置与门禁

本轮继续使用 current-default NO0300、ASLR 关闭对应的 pre-reg-to-mem checkpoint。实验变量严格隔离为：

```text
enable_local_shared_compute=true
local_shared_compute_max_clones=0
local_shared_compute_common_owner_policy=strict
local_shared_compute_common_owner_max_clones=4096
local_shared_compute_common_owner_max_cloned_op_ppm=5000
post_dp_refine_policy=off
kahn_level_pack_policy=off
```

日志确认 `fixed_commit_partition_seed_adopted=true commit_nodes=485`；local-owner 分支 timing 为 0。candidate rebuild、commit exact equality、graph/metadata/users/owner/topology validators 全部通过，exit `0`。

## 2. Selection 结果

```text
raw eligible             691
selected / applied       555 / 555
clone limit              4096
reject budget            0
reject cumulative cap    136
reject role/dependency   0 / 0
reject stale             0
projected removed pairs  1110
validated localized      1110
```

selection 保留 probe 上界的 `80.318%`；唯一损失来自两个 target 的累计 cap。graph ops 从 `7,204,108` 增至 `7,204,663`（`+555`, `+0.007704%`），values 从 `6,833,009` 增至 `6,833,564`（`+555`, `+0.008122%`）。

## 3. Final structure

| Metric | current default | Stage 5 strict | Delta |
| --- | ---: | ---: | ---: |
| supernodes | `63,726` | `63,721` | `-5` (`-0.007846%`) |
| compute supernodes | `63,241` | `63,236` | `-5` (`-0.007906%`) |
| commit supernodes | `485` | `485` | `0` |
| DAG edges | `528,622` | `528,630` | `+8` (`+0.001513%`) |
| boundary values | `1,000,463` | `1,000,184` | `-279` (`-0.027887%`) |
| total BAE | `1,983,923` | `1,983,356` | `-567` (`-0.028580%`) |
| compute-compute pairs | `1,721,698` | `1,721,131` | `-567` (`-0.032933%`) |
| compute-commit pairs | `262,225` | `262,225` | `0` |

compute nodes `1,092,530 -> 1,091,976`（`-554`）；cycle split iterations 保持 `21`。oversize/split 均为 0，compute p99/max 均保持 108，commit max 保持 42,937，没有结构爆炸或 cap 违规。

`1110` 个 compute-node localized pairs 最终只对应 `567` 个 supernode BAE 减少，说明后续 coarsen/segment 已经吸收部分共享边；因此不能用 probe pair 数代替最终 BAE。

## 4. 耗时与决定

```text
common-owner clone stage  51,232 ms
activity schedule         221,616 ms
script total              406,741 ms
wall                      6:48.67
peak RSS                  28,327,036 KiB
stats SHA256              4bbaf4d67bc439a0cc618f5e33d019dfe081f7a242e9720e64211bb7ecf8e017
```

DAG `+8` 是极小的软指标退化，BAE/boundary/SN 均小幅改善。该量级不能预判 runtime，但也不构成明显失败；按既定口径进入 full emit、O3/link 与 fixed-ASLR 100/10k/50k，最终仍由 quiet atomic A/B/A 决定是否启用。

原始产物：

```text
build/xs_activity_stage5_common_owner_strict_fixed_20260714/grhsim/grhsim_emit/activity_schedule_supernode_stats.json
build/logs/xs/xs_wolf_grhsim_build_activity_stage5_common_owner_strict_fixed_20260714.log
```
