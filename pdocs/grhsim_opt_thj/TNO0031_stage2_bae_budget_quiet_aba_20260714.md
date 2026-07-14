# TNO0031 Stage 2 bae-budget quiet A/B/A

记录日期：2026-07-14

状态：Stage 2 standalone `bae-budget` 完成有效 quiet fixed-ASLR A/B/A；cycles 略降 `0.324%`，未超过 `1%` 可信门槛，判定为接近中性，不晋升默认。

## 1. 测量口径与有效 control

CPU106/298 中 CPU106 持续被外部 GSIM 占用，因此本轮通过全核 survey 自动选择同属 NUMA1 的物理核 CPU113/305。三轮均使用：

```text
numactl --physcpubind=113 --membind=1
setarch $(uname -m) -R
cycles:u
instructions:u
de_no_dispatch_per_slot.no_ops_from_frontend:u
cpu/de_no_dispatch_per_slot.no_ops_from_frontend,cmask=0x6/u
de_no_dispatch_per_slot.backend_stalls:u
```

正式三轮前置 gate：

| Run | CPU113 idle | CPU305 idle | PMU five events |
| --- | ---: | ---: | ---: |
| control1 | `99.67%` | `99.67%` | `100%` |
| candidate | `100.00%` | `100.00%` | `100%` |
| control3 | `99.67%` | `100.00%` | `100%` |

首次后置 `control2` 虽有合格 pre-gate，但运行中受到外部干扰，cycles 为 `324,619,492,503`，相对 control1 漂移 `8.15%`，明确排除。随后在同 CPU/NUMA 重新 gate 并运行 control3；control1/control3 cycles spread 仅 `0.024662%`，构成有效包夹。

三轮 guest endpoint 均为 `50001 / 49996 / 73580 / 0x80001312`，无 mismatch/assert/fatal。

## 2. 五事件结果

| Metric | control1 | candidate | control3 | Candidate vs control mean |
| --- | ---: | ---: | ---: | ---: |
| cycles | `300,161,083,005` | `299,225,752,200` | `300,235,117,650` | `-0.323902%` |
| instructions | `172,881,293,222` | `172,515,105,329` | `172,881,293,098` | `-0.211815%` |
| frontend empty slots | `1,394,267,263,390` | `1,387,347,330,201` | `1,393,255,958,761` | `-0.460214%` |
| frontend cmask6 | `184,318,753,857` | `183,157,225,383` | `184,128,202,939` | `-0.578782%` |
| backend stalls | `96,231,207,691` | `97,243,062,515` | `97,305,536,806` | `+0.490543%` |
| host wall | `82,521 ms` | `82,277 ms` | `82,629 ms` | `-0.360884%` |

instructions 与前端空泡小幅下降，说明 SN/BAE 重排确实删掉了一点动态工作；backend stalls 反向增加约 `0.49%`，抵消了部分收益。最终 cycles 只改善 `0.324%`。

本阶段正收益阈值为 `max(1%, baseline cycles spread)`；本轮为 `max(1%, 0.024662%) = 1%`。candidate 没有越过阈值，不能称为可信性能正收益，也没有出现超过阈值的稳定回退。

## 3. 原始产物

正式数据位于：

```text
build/logs/xs_perf/activity_stage2_kahn_bae_budget_20260714/auto_control1_*.log
build/logs/xs_perf/activity_stage2_kahn_bae_budget_20260714/auto_control1_perf.csv
build/logs/xs_perf/activity_stage2_kahn_bae_budget_20260714/auto_candidate_*.log
build/logs/xs_perf/activity_stage2_kahn_bae_budget_20260714/auto_candidate_perf.csv
build/logs/xs_perf/activity_stage2_kahn_bae_budget_20260714/auto_control3_*.log
build/logs/xs_perf/activity_stage2_kahn_bae_budget_20260714/auto_control3_perf.csv
```

`auto_control2` 保留为被 baseline-spread gate 排除的诊断运行，不得混入有效均值。

## 4. Default decision 与下一步

Stage 2 standalone 是可重复的轻微正向信号，但只有 `0.324%` cycles，低于可信门槛；current-default 继续保持：

```text
kahn_level_pack_policy=off
post_dp_refine_policy=off
```

实现、显式 options、exact evaluator 和测试可以默认关闭保留。由于 candidate 同时减少 `75` 个 SN 和 `0.212%` host instructions，本轮按 [TNO0028](./TNO0028_stage2_same_kahn_level_packing_plan_20260714.md) 继续检查与 Stage 1 strict post-DP refinement 的组合；只有组合越过 1% 才考虑默认晋升。
