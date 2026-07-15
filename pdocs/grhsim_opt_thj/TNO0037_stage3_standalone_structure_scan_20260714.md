# TNO0037 Stage 3 standalone structure scan

记录日期：2026-07-14

状态：Stage 3 conservative true-clone standalone SimTop structure scan PASS；应用 108 个 clone，BAE/DAG/boundary values 轻微下降，但 graph ops/values 各增加 108、SN 增加 3。结构量级很小，仍按最终口径进入 full build/50k。

## 1. 配置与执行

复用 current-default pre-reg-to-mem checkpoint，Stage 1/2 关闭：

```text
enable_local_shared_compute=true
local_shared_compute_max_fanout=2
local_shared_compute_max_width=64
local_shared_compute_max_clones=4096
local_shared_compute_max_cloned_op_ppm=5000
post_dp_refine_policy=off
kahn_level_pack_policy=off
stop_after_activity_schedule=true
```

candidate stats SHA256：

```text
61f544c3e3b1bd59e01a0d96e40103e1cbde58834fabf498a027e09260600448
```

## 2. Clone discovery

| Metric | Count |
| --- | ---: |
| scanned compute ops | `4,386,595` |
| eligible / planned / applied | `108 / 108 / 108` |
| effective clone limit | `4,096` |
| rejected kind | `24,816` |
| rejected width | `66,883` |
| rejected fanout | `3,379,455` |
| rejected consumer nodes | `194,009` |
| rejected intent | `312` |
| rejected declared/port | `651,670` |
| rejected operand locality | `67,905` |
| rejected aggregate capacity | `1,437` |
| rejected side effect / shape / budget | `0 / 0 / 0` |

clone、refreeze 与完整 rewrite rebuild 合计 `50,840 ms`。首版真正的限制不是 4096 hard budget，而是 exactly-two user、source-already-local 和 pre-existing operand locality；只有 `108` 个候选走到 apply。

## 3. Exact structure

| Metric | current default | Stage 3 candidate | Delta |
| --- | ---: | ---: | ---: |
| graph ops / values | `7,204,108 / 6,833,009` | `7,204,216 / 6,833,117` | `+108 / +108` |
| total / compute / commit SN | `63,726 / 63,241 / 485` | `63,729 / 63,244 / 485` | `+3 / +3 / 0` |
| total BAE | `1,983,923` | `1,983,869` | `-54` (`-0.00272%`) |
| DAG edges | `528,622` | `528,604` | `-18` |
| boundary values | `1,000,463` | `1,000,399` | `-64` |
| compute-node cycle split iterations | `21` | `21` | `0` |
| oversize nodes / split SN | `0 / 0` | `0 / 0` | `0 / 0` |

每个 clone 理论上希望删除一条 shared-result boundary；最终只净减 `54` BAE，说明 downstream compute-node clustering/DP 会抵消约一半局部收益。SN 增加 3 也表明复制不是纯粹删边，必须观察 generated code 和动态工作。

activity schedule 用时 `217,017 ms`，全脚本 `385,729 ms`；wall `6:27.54`，peak RSS `28,326,972 KiB`，exit `0`，没有残留进程。

## 4. Gate 与下一步

结构变化远低于 `1%`，无法预测 runtime；108 个表达式也可能集中在 hot path，因此按用户要求继续 full emit/O3/link、fixed-ASLR 100/10k/50k，而不是仅凭机会量停止。正式性能仍需 quiet A/B/A。

如果 conservative candidate 不产生可信 50k 收益，`194,009` 个 consumer-node reject 是下一轮最明确的扩展入口：允许原 producer 位于独立 common-expression node，但必须同时验证两个 consumer 的 operand locality/cap，并继续用 true clone + full rebuild，不能恢复历史 ownership absorption。

原始产物：

```text
build/logs/xs/xs_wolf_grhsim_build_activity_stage3_local_clone_candidate_20260714.log
build/xs_activity_stage3_local_clone_candidate_20260714/grhsim/grhsim_emit/activity_schedule_supernode_stats.json
```
