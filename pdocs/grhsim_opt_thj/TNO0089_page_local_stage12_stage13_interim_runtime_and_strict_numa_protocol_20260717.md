# TNO0089 Page-local Stage 12/13 interim runtime and strict NUMA protocol

记录日期：2026-07-17

状态：补齐 Stage 12 cap32768 与 Stage 13 cap8192 的双 node、page-local 50k A/B/A 原始结果，并完成 control 漂移审计。四组共 12 个样本在当时的整 CCD acceptance gate 下全部通过，绑核、`numactl` 内存策略、fixed-ASLR、file page placement、PMU、scheduler 与功能终点均正确；但 N1 两组 control cycles 分别漂移 `-1.519%/-1.056%`，证明“目标 CCD 安静”不足以排除同 socket 其他 CCD 的共享资源干扰。正式协议因此升级为整 NUMA/socket 的 30 秒运行前 gate、运行期整 node monitor，并要求平衡的 AB/BA 重复。Stage 13 cap16384 当前尝试已因全机外部负载被正确拒绝；本文仅记录阶段性观测，不形成 Stage 13 最终性能或默认值结论。

## 1. 测试对象与执行位置

两边继续使用 [TNO0085](./TNO0085_numa_file_page_locality_diagnosis_and_protocol_20260716.md) 建立的独立 `/dev/shm` inode：

```text
/dev/shm/grhsim_page_local_retest_tanghaojin_20260716_v1/n0/
/dev/shm/grhsim_page_local_retest_tanghaojin_20260716_v1/n1/
```

本轮使用 socket-relative offset 75 的镜像 physical core：N0 为 CPU `75`、SMT sibling `267`，N1 为 CPU `171`、SMT sibling `363`。每个 node、每个候选独立执行：

```text
NO0300 same-post control A1 / candidate B / NO0300 same-post control A2
```

workload 的关键命令层级为：

```bash
taskset -c "$CPU" \
    numactl --physcpubind="$CPU" --membind="$NODE" \
    perf stat ... -- \
    setarch x86_64 -R "$NODE_LOCAL_EMU" ... -C 50000
```

12 个样本的 process audit 均满足：

- `Cpus_allowed_list` 精确为 CPU75 或 CPU171，未发生 migration；
- `setarch` personality probe 均为 `00040000`，即 ASLR 关闭；
- `emu` 与 `nemu.so` 映射页全部位于执行 node；control `emu` 为 `21,494` 页，Stage 12 cap32768 为 `21,444` 页，Stage 13 cap8192 为 `21,394` 页，`nemu.so` 均为 `115` 页；
- 五项硬件事件 scheduling 均为 `100%`，task-clock utilization 为 `0.999..1.000`，context-switch rate 为 `1.194..1.695/s`，migration 为 `0`；
- guest/cycleCnt/instrCnt 到达 `50001/49996/73580`，功能门禁全部通过。

因此先前 NUMA 方向反转的 NFS file-page 根因已被排除；下述异常不能再归因于错误的 `numactl` 语法、未关闭 ASLR 或远端 executable page。

## 2. Stage 12 cap32768 原始结果

以下为未做归一化的 `perf stat` 原始计数；A1/A2 是同一个 same-post NO0300 control，B 为 Stage 12 cap32768。

| node | sample | host ms | cycles | instructions | frontend empty | frontend `cmask>=6` | backend stalls |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| N0 | A1 | `77623` | `282,723,154,619` | `172,881,254,713` | `1,291,889,649,801` | `167,310,972,575` | `94,117,779,530` |
| N0 | B | `77672` | `283,681,786,783` | `173,094,865,111` | `1,297,142,063,732` | `168,304,473,799` | `94,120,412,520` |
| N0 | A2 | `77846` | `284,795,237,093` | `172,881,255,777` | `1,303,990,486,004` | `169,329,892,311` | `94,129,348,813` |
| N1 | A1 | `76811` | `280,924,137,250` | `172,881,254,716` | `1,279,784,559,333` | `165,357,520,436` | `95,065,909,927` |
| N1 | B | `77058` | `282,559,832,274` | `173,094,863,979` | `1,289,348,653,343` | `166,965,577,649` | `95,500,120,636` |
| N1 | A2 | `75431` | `276,655,509,514` | `172,881,253,043` | `1,256,763,740,721` | `161,547,798,589` | `92,725,532,221` |

候选相对 `(A1+A2)/2` 的阶段性 delta 为：

| node | control cycles spread A2/A1 | host | cycles | instructions | frontend empty | frontend `cmask>=6` | backend stalls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| N0 | `+0.732902%` | `-0.080402%` | `-0.027280%` | `+0.123559%` | `-0.061482%` | `-0.009481%` | `-0.003348%` |
| N1 | `-1.519495%` | `+1.230935%` | `+1.352276%` | `+0.123559%` | `+1.661668%` | `+2.149196%` | `+1.708704%` |

instructions 在两个 node 精确复现 `+0.123559%`，而 cycles/frontend 的方向分裂随 N1 control 的大幅下漂出现。该组只能说明 cap32768 没有稳定跨 node 收益；不能把 N1 的 `+1.35%` 直接归因于代码，也不能用 N0 的近零结果覆盖 N1。

## 3. Stage 13 cap8192 原始结果

A1/A2 仍为 same-post NO0300 control，B 为 canonical commit order/slot-stable 的 Stage 13 cap8192。

| node | sample | host ms | cycles | instructions | frontend empty | frontend `cmask>=6` | backend stalls |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| N0 | A1 | `77657` | `284,519,315,496` | `172,881,255,559` | `1,302,237,560,912` | `169,060,444,001` | `94,469,290,551` |
| N0 | B | `77644` | `283,623,852,743` | `172,761,852,956` | `1,297,090,365,423` | `168,220,244,569` | `94,475,296,145` |
| N0 | A2 | `77837` | `284,078,115,501` | `172,881,254,802` | `1,299,862,839,368` | `168,682,312,648` | `94,191,793,753` |
| N1 | A1 | `76799` | `281,377,554,055` | `172,881,253,907` | `1,282,877,628,452` | `165,878,918,801` | `94,772,123,196` |
| N1 | B | `74839` | `273,506,352,683` | `172,761,850,425` | `1,238,161,117,550` | `158,454,536,635` | `92,784,186,187` |
| N1 | A2 | `76220` | `278,405,169,215` | `172,881,253,785` | `1,268,713,945,074` | `163,509,748,838` | `91,472,436,631` |

阶段性 delta：

| node | control cycles spread A2/A1 | host | cycles | instructions | frontend empty | frontend `cmask>=6` | backend stalls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| N0 | `-0.155069%` | `-0.132481%` | `-0.237378%` | `-0.069066%` | `-0.304357%` | `-0.385580%` | `+0.153454%` |
| N1 | `-1.056369%` | `-2.183389%` | `-2.281245%` | `-0.069067%` | `-2.949898%` | `-3.788714%` | `-0.363064%` |

Stage 13 的 instructions `-0.06907%` 在两个 node 高度一致，但 N1 cycles/frontend 的表观收益远大于 N0，并与 `-1.056%` 的 control 漂移重合。即使线性 A1/A2 均值包夹给出 N1 cycles `-2.28%`，单次 A/B/A 也不足以证明稳定收益；它只能作为后续严格复测需要检验的信号。

## 4. Control 漂移为何推翻“只监控 CCD 足够”的假设

四组运行期的目标 CCD 非 target 线程 mean idle 为 `99.585%..99.978%`、minimum idle 为 `99.060%..99.890%`，远高于当时的 `98%/95%` 门槛；gate-to-run gap 也均只有 `5 ms`。然而 control 自身仍出现：

| 对象 | node | host A2/A1 | cycles A2/A1 | frontend A2/A1 | `cmask>=6` A2/A1 | backend A2/A1 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Stage 12 包夹 | N0 | `+0.287286%` | `+0.732902%` | `+0.936677%` | `+1.206687%` | `+0.012292%` |
| Stage 12 包夹 | N1 | `-1.796618%` | `-1.519495%` | `-1.798804%` | `-2.303930%` | `-2.461847%` |
| Stage 13 cap8192 包夹 | N0 | `+0.231789%` | `-0.155069%` | `-0.182357%` | `-0.223666%` | `-0.293743%` |
| Stage 13 cap8192 包夹 | N1 | `-0.753916%` | `-1.056369%` | `-1.104056%` | `-1.428253%` | `-3.481706%` |

这说明 page placement 和 target-CCD idle 只是必要条件。迁移到同 socket 其他 CCD 的 CI/firtool/gem5/gsim 等任务仍可能通过 socket 级 fabric、memory controller、I/O、功耗/频率与内核活动影响目标核；只监控 16 个 CCD logical CPUs 会漏掉这种污染。上述 12 个样本在旧门槛定义下是完整、可追溯的有效原始样本，但其单次 delta 不再达到最终采用所需的因果强度。

## 5. Stage 13 cap16384 的正确拒绝

cap16384 启动后，N0 的 A1 在运行前已经找不到整 CCD quiet window，未进入 perf；N1 的 control A1 虽通过，但候选 B 的运行期 CCD monitor 降至：

```text
non_target_threads=15 mean_idle=59.741 min_idle=58.900
monitor_ok=0
```

候选的 placement、PMU、scheduler、affinity、ASLR 和功能均仍为 PASS，但 monitor hard gate 单项失败即使整组无效，脚本没有继续生成 A2，也没有把其 counters 纳入结果。随后 30 秒全机快照显示 N0/N1 的 192 个 logical CPUs mean idle 仅 `62.236%/37.135%`，证明是大范围外部负载而非候选代码造成；本次 cap16384 被正确拒绝。

## 6. 升级后的 strict NUMA/socket 协议

后续 Stage 12/13 及默认选项裁决统一提高到：

1. **整 node 30 秒 pre-run gate**：对执行 node 的 192 个 logical CPUs 连续采样，要求整 node mean idle `>=99%`、任一线程 minimum idle `>=95%`，目标 CPU 与 sibling 各自 `>=98%`；不再以单 CCD 达标代替 socket 安静。
2. **整 node runtime monitor**：workload 全程监控除 target 外的 191 个 logical CPUs，同样要求 mean idle `>=99%`、minimum idle `>=95%`；任一阶段失败即拒绝该样本及其不完整包夹。
3. **保留执行约束**：独立 node-local inode、镜像 physical core、`taskset` 加 `numactl --physcpubind/--membind`、`setarch x86_64 -R`、运行中 `numa_maps`、五项 PMU、scheduler 和功能终点仍全部是硬门槛。
4. **平衡顺序重复**：每个 node 不再只依赖一次 A/B/A；至少完成方向平衡的 AB 与 BA 重复，使候选和 control 在时间顺序上各先各后，再联合审计 control 漂移。任何一组受污染都整体重跑，不用未配对样本补平均。
5. **阶段性结果不晋升**：本文 Stage 12 cap32768 与 Stage 13 cap8192 的 raw counters 保留为诊断证据，但默认值和 Stage 13 最终 runtime 必须由 strict protocol 的完整双 node 重复另行裁决。

## 7. 当前结论

- 绑核、`numactl`、fixed-ASLR 与 page-local staging 均已验证正确，不是本轮剩余不对称的根因。
- Stage 12 cap32768 在现有 raw A/B/A 中表现为 N0 中性、N1 回退，但 control 漂移过大，不追加新的默认值决定。
- Stage 13 cap8192 的 N0 小幅正向与 N1 较大正向尚不可采信为最终收益；稳定的 instructions 小降值得在 strict protocol 下继续验证。
- cap16384 当前尝试因全机外部负载被 gate 正确拒绝，不产生候选结论；cap32768 尚未完成本阶段 strict runtime。
- Stage 13 最终结果、三档相对判断及默认 cap 决策待严格双 node、平衡 AB/BA 重复全部闭合后另立 TNO 补充。

原始产物：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/groups/n0/stage12_cap32768_try1/
build/logs/xs_perf/page_local_retest_stage7plus_20260716/groups/n1/stage12_cap32768_try1/
build/logs/xs_perf/page_local_retest_stage7plus_20260716/groups/n0/stage13_cap8192_try1/
build/logs/xs_perf/page_local_retest_stage7plus_20260716/groups/n1/stage13_cap8192_try1/
build/logs/xs_perf/page_local_retest_stage7plus_20260716/groups/n1/stage13_cap16384_try1/
build/logs/xs_perf/page_local_retest_stage7plus_20260716/whole_machine_30s_after_cap16384_fail_20260717.log
build/logs/xs_perf/page_local_retest_stage7plus_20260716/run_formal.sh
```
