# TNO0050 Stage 5 quiet A/B/A and default decision

记录日期：2026-07-14

状态：Stage 5 common-owner strict 完成有效 atomic quiet fixed-ASLR A/B/A；cycles `+0.688%`，低于 1% 可信线但各 stall 指标偏负，判 neutral-to-mild-regression，默认保持关闭。

## 1. 正式口径

三轮顺序为 current-default / Stage 5 / current-default，统一使用：

```text
CPU142 / sibling334 / NUMA1
taskset -c 0 mpstat -P 142,334 1 3
numactl --physcpubind=142 --membind=1
setarch x86_64 -R
```

quiet gate 与 `perf stat` 位于同一 shell helper；双 sibling 三秒平均 idle 均 `>=99%` 才立即启动。candidate attempt1 因 sibling334 idle `97.32%` 被正确拒绝，attempt2 才进入正式运行。

| Run | Gate idle | gate-to-run | PMU | Endpoint |
| --- | --- | ---: | --- | --- |
| control1 | `100.00% / 100.00%` | `7 ms` | 5 events `100%` | `50001/49996/73580/0x80001312` |
| candidate | `99.00% / 99.00%` | `6 ms` | 5 events `100%` | `50001/49996/73580/0x80001312` |
| control2 | `100.00% / 99.67%` | `7 ms` | 5 events `100%` | `50001/49996/73580/0x80001312` |

三轮 difftest 正常，负向关键词均为 0。两侧 control cycles spread 为 `0.424113%`，小于 1%，构成有效包夹。

## 2. 五事件结果

| Metric | control1 | candidate | control2 | Candidate vs control mean |
| --- | ---: | ---: | ---: | ---: |
| cycles | `285,530,260,848` | `286,885,612,756` | `284,321,852,734` | `+0.687742%` |
| instructions | `172,881,406,831` | `172,857,778,374` | `172,881,405,843` | `-0.013667%` |
| frontend empty slots | `1,308,100,954,995` | `1,315,518,467,407` | `1,302,724,291,892` | `+0.774149%` |
| frontend cmask6 | `170,197,400,934` | `171,048,737,235` | `169,241,411,679` | `+0.783252%` |
| backend stalls | `94,523,770,947` | `94,866,945,606` | `93,326,883,019` | `+1.002518%` |
| host wall | `78,006 ms` | `78,547 ms` | `77,659 ms` | `+0.917997%` |

可信阈值为：

```text
max(1%, control spread 0.424113%) = 1%
```

候选少执行约 `0.014%` instructions，但 frontend empty/cmask6 和 backend stalls 同时增加，cycles 回退 `0.688%`。cycles 没有越过 1% 线，不能声明显著退化；方向也没有任何正收益信号，因此分类为 neutral-to-mild-regression，而不是优化成功。

## 3. Artifact hash 勘误

正式 candidate 使用的 ELF 在运行前后均为：

```text
size  94,718,752 bytes
SHA   8e752d94d1813f0860b6757004717c71f39732f0a8291e0994e024c39bb53c34
.text size 88,133,332 bytes
.text SHA  330ea839f28a31693023ace88caa105b9d885e466a5774a293217f4d7dd1fbaf
```

[TNO0049](./TNO0049_stage5_full_build_and_functional_gate_20260714.md) 初始记录的 emu SHA `2e22...` 是并发静态取证期间观测到的过渡值，不是正式 artifact；`.text` 数据不受影响。candidate PMU 于该文件最终 mtime 之后启动，运行前后 SHA 都是 `8e752...`，样本可保留。

## 4. Default decision

Stage 5 的 final structure 为 graph ops/values 各 `+555`、BAE `-567`、boundary values `-279`、SN `-5`、DAG `+8`。结构收益不足 `0.03%`，runtime 又呈轻微负向，common-owner strict 不晋升默认：

```text
enable_local_shared_compute=false
local_shared_compute_common_owner_policy=off
post_dp_refine_policy=off
kahn_level_pack_policy=off
```

实现、probe、hard budgets、fixed commit seed 与验证器作为默认关闭的实验入口保留。本阶段不继续扩大 clone allowlist 或 budget；691 个 raw opportunity 已被当前 strict/cap 基本穷尽，继续放宽更可能增加 graph/code-layout 扰动而不是获得足够 BAE。

## 5. 原始数据

```text
build/logs/xs_perf/activity_stage5_common_owner_strict_20260714/formal_control1_*
build/logs/xs_perf/activity_stage5_common_owner_strict_20260714/formal_candidate_*
build/logs/xs_perf/activity_stage5_common_owner_strict_20260714/formal_control2_*
build/logs/xs_perf/activity_stage5_common_owner_strict_20260714/run_formal_atomic.sh
```
