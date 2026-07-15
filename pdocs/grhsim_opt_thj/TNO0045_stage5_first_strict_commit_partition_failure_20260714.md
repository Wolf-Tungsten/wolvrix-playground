# TNO0045 Stage 5 first strict commit-partition failure

记录日期：2026-07-14

状态：Stage 5 首次 SimTop strict structure scan 在 full rewrite validator 的 commit-partition equality 硬门禁失败；已停止，无 final stats、full build或50k结果。

## 1. 配置

```text
enable_local_shared_compute=true
local_shared_compute_max_clones=0
local_shared_compute_common_owner_policy=strict
local_shared_compute_common_owner_max_clones=4096
local_shared_compute_common_owner_max_cloned_op_ppm=5000
local_shared_compute_max_fanout=2
local_shared_compute_max_width=64
post_dp_refine_policy=off
kahn_level_pack_policy=off
stop_after_activity_schedule=true
```

日志确认 strict/common配置正确，Stage 3 local-owner apply 未进入。

## 2. 失败点

baseline rewrite 正常：

```text
compute_nodes=1,092,530
commit_nodes=485
cycle_split_iters=21
```

common-owner apply 与 candidate rewrite 后，shared validator 报：

```text
activity-schedule local shared compute clone changed commit partition
```

pass exit `1`，因此 strict summary、selected/applied counts与final schedule stats都没有写出。脚本 wall `4:55.92`，peak RSS `28,328,464 KiB`。按硬门禁要求，没有继续 emit/build/50k。

## 3. 当前诊断边界

source result本身没有sink/commit user，graph原有sink op与operand ID理论上不应改变；但 clone append和use rewrite会改变重新freeze后的op topo，`buildEventClusteredSinkPartition`按新的sink topo位置重建commit nodes。当前validator只给出generic equality错误，尚不能区分：

- commit ops或input value集合真的改变；
- 相同集合在vector内顺序改变；
- 相同sink被重新分到不同commit node；
- commit node顺序整体变化。

因此当前不能直接放宽为set equality，也不能断言只是无害顺序漂移。下一步只增强错误诊断，报告首个mismatch、order-insensitive集合和normalized partition；用同一配置重跑取证后，再决定是修正候选资格还是在candidate rewrite中显式保留baseline commit partition。

## 4. 原始日志

```text
build/logs/xs/xs_wolf_grhsim_build_activity_stage5_common_owner_strict_20260714.log
```

本次失败属于正确的validator拦截，不产生可比较候选；Stage5仍默认关闭。
