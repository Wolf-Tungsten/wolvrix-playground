# TNO0104 Stage 17 targeted-direct N0 strict runtime and default decision

记录日期：2026-07-17

状态：N0 strict ABBA+BAAB 已完成，8/8 样本通过全部硬门禁；N1 因 CPU104 上的外部 `htop` 负载未运行且未干预。targeted-direct 相对 current C++ native-hybrid default 的 cycles 在 ABBA 为 `+0.253568%`、BAAB 为 `-0.316547%`，合并为 `-0.031601%`；instructions `-0.033009%`，frontend empty `+0.044578%`，frontend `cmask>=6` `+0.046026%`，backend stalls `-0.991009%`。两种相反顺序方向反转，合并 cycles 远小于 control/candidate spread `0.213781%/0.566989%`，判定中性，不启用默认。`activeMaskGapPackPolicy` 保持 C++ native `off`，XS 继续只做稀疏显式覆盖。

## 1. 对象、placement 与绑定

本轮比较：

```text
A/control:   s14_default          current C++ native-hybrid/cap4096 default
B/candidate: s17_targeted_direct  仅替换 selected non-table direct active-mask writes
```

两份 ELF 分别 staging 到 N0 的独立 `/dev/shm` inode：

```text
/dev/shm/grhsim_page_local_retest_tanghaojin_20260716_v1/n0/s14_default
/dev/shm/grhsim_page_local_retest_tanghaojin_20260716_v1/n0/s17_targeted_direct
```

control/candidate 的本地 placement 分别为 `21,264/21,255` 个 `emu` pages，`nemu.so` 均为 `115` pages；8/8 均全部位于 N0，N1 pages 为 `0`。执行核为 N0 CPU43，SMT sibling 为 CPU235，monitor/helper 使用对侧 node CPU191。实际 workload 绑定为：

```bash
taskset -c 43 \
    numactl --physcpubind=43 --membind=0 \
    perf stat ... -- \
    setarch x86_64 -R <node-local-emu> ... -C 50000
```

`taskset` 与 `numactl` 同时固定 logical/physical CPU 和 memory policy，`setarch` 关闭 ASLR；file-backed page locality 再由每个样本的 `numa_maps` placement 审计确认。执行入口为：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/run_balanced_pair.sh
```

顺序分别为：

```text
ABBA: default / targeted / targeted / default
BAAB: targeted / default / default / targeted
```

## 2. 八个有效样本

原始 cycles 为：

| order | sample | binary | cycles |
| --- | --- | --- | ---: |
| ABBA | A1 | default | `272,773,294,335` |
| ABBA | B1 | targeted-direct | `273,660,231,081` |
| ABBA | B2 | targeted-direct | `273,833,040,784` |
| ABBA | A2 | default | `273,335,221,758` |
| BAAB | B1 | targeted-direct | `272,284,734,909` |
| BAAB | A1 | default | `273,179,020,809` |
| BAAB | A2 | default | `273,357,260,762` |
| BAAB | B2 | targeted-direct | `272,521,503,325` |

每个顺序内先分别平均两份 control 与两份 candidate，再计算 `candidate/control - 1`：

| order | targeted-direct cycles delta |
| --- | ---: |
| ABBA | `+0.253568%` |
| BAAB | `-0.316547%` |
| combined four-vs-four | `-0.031601%` |

合并后的五项 PMU headline：

| metric | targeted-direct vs default |
| --- | ---: |
| cycles | `-0.031601%` |
| instructions | `-0.033009%` |
| frontend empty | `+0.044578%` |
| frontend `cmask>=6` | `+0.046026%` |
| backend stalls | `-0.991009%` |

instructions 的小幅下降与静态 write reduction 方向一致，但只有 `0.033%`；frontend 两项轻微回退，backend 计数下降约 `0.99%`，最终 cycles 仍接近零。更关键的是，ABBA 与 BAAB 的 cycles 方向相反；四份 default control 的 `max/min - 1` spread 为 `0.213781%`，四份 targeted candidate 为 `0.566989%`，均大于合并 `0.031601%`。因此不能把静态 source/ELF 缩减解释为可重复 runtime 收益。

## 3. 严格硬门禁

8/8 正式样本全部通过：

- **30 秒 whole-node pre-gate PASS**：192 个 N0 logical CPU mean idle 为 `99.487%..99.561%`、minimum idle 为 `95.43%..97.06%`；CPU43 为 `99.00%..99.97%`，sibling CPU235 为 `99.67%..99.90%`；全部满足 mean `>=99%`、min `>=95%`、target/sibling `>=98%`。
- **gate-to-run PASS**：8 次 gap 均为 `7 ms`，没有在 admission 与启动之间留下长窗口。
- **runtime whole-node monitor PASS**：除 target 外 191 个 logical CPU mean idle 为 `99.514%..99.585%`、minimum idle 为 `96.30%..97.01%`。
- **page placement PASS**：两份独立 inode 与 `nemu.so` 均为 N0-local，8/8 无远端页。
- **PMU/调度 PASS**：五项 headline event scheduling 均为 `100.00%`，8/8 `cpu-migrations=0`，affinity audit 均为 `Cpus_allowed_list=43`。
- **ASLR/功能 PASS**：8/8 personality 与 fixed-ASLR 检查通过，均达到 `Guest cycle spent=50001`、`cycleCnt=49996`、`instrCnt=73580`，无 mismatch/assert/fatal/error。

每个样本的 runner result 均为：

```text
run_status=0 placement_ok=1 monitor_ok=1 perf_ok=1
scheduler_ok=1 function_ok=1 affinity_ok=1
```

原始 artifact：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/groups/n0/stage17_targeted_direct_strict_p0_abba_try1/
build/logs/xs_perf/page_local_retest_stage7plus_20260716/groups/n0/stage17_targeted_direct_strict_p0_baab_try1/
```

## 4. N1 blocker

N0 完成后的 N1 survey 发现外部进程：

```text
PID 2816950  CPU104  37.8% CPU  htop
affinity 0-383
Mems_allowed_list 0-1
```

连续十次观测中该进程一直在 CPU104 上运行或可运行，会使 N1 whole-node minimum idle 明显低于 `95%`。因此没有启动 N1 perf，也没有降低 admission gate。该进程不属于本任务，未 kill、未改 affinity、未改 memory policy，避免用干预其他用户进程制造虚假的安静窗口。

证据路径：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/stage17_survey_20260717/n1_after_n0.log
build/logs/xs_perf/page_local_retest_stage7plus_20260716/stage17_survey_20260717/n1_blocker_after_n0.log
```

N1 后续仍应在外部负载消失后，使用镜像 CPU139/sibling331、N1-local 独立 inode、ABBA+BAAB 和同一 whole-node gate 补测；当前不能写成 strict 双 NUMA closure。

## 5. 默认决策

Stage 17 的 N0 数据已经足以否定“现在默认启用”的依据：

1. ABBA `+0.253568%` 与 BAAB `-0.316547%` 方向相反；
2. combined cycles `-0.031601%` 远低于 control/candidate spread；
3. instructions 只减少 `0.033009%`，frontend 两项没有改善；
4. `.text -0.1166%` 和 source 少 `30,005` writes 没有转化为稳定 cycles 收益。

因此：

```text
C++ activeMaskGapPackPolicy default = off
XS default override                 = none / sparse
explicit experiment                = targeted-direct
```

即使后续有效 N1 单边偶然为正，在没有双 node、双顺序一致收益前也不应改默认；若 N1 显示显著且稳定的收益，应先解释 N0 中性与 node 差异并重新复测，而不是在 XS 脚本里单独暗设参数。

默认配置的长期原则是：跨设计通用行为由 C++ 提供唯一 native default，XS 只携带经过明确验证且确属平台差异的稀疏 override。当前 Stage 17 保持 `off` 正符合这一原则，也避免脚本层默认在后续与 C++、Python/direct API 或其它设计产生隐式分叉。

完整回归尚未完成；它只影响 Stage 17 代码提交门禁，不改变本轮“性能中性、保持 off”的 runtime 决策。完成后应新增独立 full-regression TNO。

## 增量更新 2026-07-17：绝对数值补录/勘误

原文的 N0 ABBA/BAAB 表只列了 cycles 原始值，instructions 与三个辅助 PMU 事件未列绝对计数。现从 8 份原始 `perf stat -x,` CSV 补录完整五事件；没有从百分比反推。事件与单位为 `cycles:u`（cycles count）、`instructions:u`（retired-instruction count）、`de_no_dispatch_per_slot.no_ops_from_frontend:u`（frontend-empty slots count）、`cpu/de_no_dispatch_per_slot.no_ops_from_frontend,cmask=0x6/u`（frontend-empty `cmask>=6` cycles count）和 `de_no_dispatch_per_slot.backend_stalls:u`（backend-stall slots count）。

| group | 顺序 | sample | cycles | instructions | frontend empty | frontend `cmask>=6` | backend stalls |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| ABBA | 1 | control A1 | `272,773,294,335` | `164,521,620,167` | `1,247,922,505,564` | `161,883,772,700` | `90,712,444,199` |
| ABBA | 2 | targeted B1 | `273,660,231,081` | `164,467,314,022` | `1,254,382,253,363` | `162,930,715,784` | `89,733,648,232` |
| ABBA | 3 | targeted B2 | `273,833,040,784` | `164,467,313,703` | `1,255,193,204,532` | `163,093,289,745` | `89,794,851,810` |
| ABBA | 4 | control A2 | `273,335,221,758` | `164,521,619,908` | `1,252,171,843,362` | `162,582,356,798` | `89,947,830,123` |
| BAAB | 1 | targeted B1 | `272,284,734,909` | `164,467,312,980` | `1,248,046,190,142` | `161,883,504,236` | `88,110,649,094` |
| BAAB | 2 | control A1 | `273,179,020,809` | `164,521,620,342` | `1,251,093,193,789` | `162,401,802,148` | `90,109,670,653` |
| BAAB | 3 | control A2 | `273,357,260,762` | `164,521,620,138` | `1,251,926,208,339` | `162,556,523,680` | `90,170,020,290` |
| BAAB | 4 | targeted B2 | `272,521,503,325` | `164,467,312,738` | `1,247,722,391,607` | `161,815,848,862` | `89,723,869,415` |

原始路径为：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/groups/n0/stage17_targeted_direct_strict_p0_abba_try1/{a1,b1,b2,a2}_perf.csv
build/logs/xs_perf/page_local_retest_stage7plus_20260716/groups/n0/stage17_targeted_direct_strict_p0_baab_try1/{a1,b1,b2,a2}_perf.csv
```

8 份 CSV 的五个事件均为 `100.00%` scheduled。本补录仅补全绝对 raw counters，不改变原文 N1 未测、ABBA/BAAB 方向相反或默认 `off` 的结论。

## 增量更新 2026-07-17：walltime headline 绝对值补录

最终性能 headline 采用 host walltime；按 binary header 映射样本，不按 `a/b` 文件名猜测：ABBA 是 control `s14_default` / targeted / targeted / control，BAAB 是 targeted / control / control / targeted。以下直接读取同组 `Host time spent`（milliseconds）：

| order | binary sequence | wall ms |
| --- | --- | --- |
| ABBA | default A1 / targeted B1 / targeted B2 / default A2 | `74,629 / 74,806 / 74,868 / 74,738` |
| BAAB | targeted B1 / default A1 / default A2 / targeted B2 | `74,430 / 74,668 / 74,732 / 74,494` |

原始来源为 `build/logs/xs_perf/page_local_retest_stage7plus_20260716/groups/n0/stage17_targeted_direct_strict_p0_{abba,baab}_try1/{a1,b1,b2,a2}_emu.log`。walltime targeted-vs-default delta 为 ABBA `+0.205534%`、BAAB `-0.318608%`、合并 `-0.056566%`；default/targeted spreads 为 `0.146056%/0.588472%`。两顺序方向相反且合并幅度低于噪声，walltime headline 仍判 neutral，C++ default 保持 `off`。
