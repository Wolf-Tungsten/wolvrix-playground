# TNO0087 Correct page-local Stage 7/8 runtime

记录日期：2026-07-16

状态：按 [TNO0085](./TNO0085_numa_file_page_locality_diagnosis_and_protocol_20260716.md) 的 correct page-local 协议完成 Stage 7 hybrid 与 Stage 8 p050/p200 的双 node 50k 重测。14 个正式样本均通过 file placement、镜像核、全 CCD 持续监控、scheduler、PMU 和功能门禁。hybrid 在 N0/N1 cycles 分别提升 `4.237%/4.353%`，p050 在两边均为中性，p200 在两边均轻微回退；[TNO0060](./TNO0060_stage7_cross_socket_runtime_and_default_decision_20260715.md) 和 [TNO0064](./TNO0064_stage8_cross_numa_runtime_and_default_decision_20260716.md) 的旧 socket 方向反转结论失效。same-post Stage 10/12/13 序列仍在运行，本记录不包含其任何中间结果。

## 1. Node-local staging

正式输入不再直接映射 NFS inode。N0/N1 分别使用：

```text
/dev/shm/grhsim_page_local_retest_tanghaojin_20260716_v1/n0/
/dev/shm/grhsim_page_local_retest_tanghaojin_20260716_v1/n1/
```

staging 对每个 node 创建全新目录，并在对应 node 的 CPU/memory policy 下使用 `cp --reflink=never` 生成独立 inode；已有目录会被脚本拒绝，不能复用旧 page cache。`emu`、`nemu.so` 和 CoreMark image 的 N0/N1 SHA256 逐项一致，也与原始 build 输入一致。Stage 7/8 四个 ELF 为：

| 对象 | N0/N1 SHA256 |
| --- | --- |
| NO0300 rollback control | `cd093aadefee6e84e236d8826558e6bc9beeebaee41f2133bf6dc57c0457fe97` |
| Stage 7 hybrid | `ae6b6df7ab5fff8b003414d9b2e3c80937b9ef30e9fe55bb8c670742e35b281e` |
| Stage 8 p050 | `f716ed8511c6875957dd2d3fad9715f54d9c6c07d738c4bcc395a519b8643dc5` |
| Stage 8 p200 | `adcde341a5aa9659c88b4a36ef8346f89db5702a3651527425e8e6b0cc671c3f` |

同名 N0/N1 文件 inode 不同，因此 byte identity 不再意味着共享 file-backed 物理页。

## 2. 镜像核与正式命令

两个 node 使用 socket-relative offset 15 的镜像 core：

| node | target CPU / SMT sibling | L3/CCD | helper CPU |
| --- | --- | --- | --- |
| N0 | `15 / 207` | socket 0 的对应 CCD | `47` |
| N1 | `111 / 303` | socket 1 的镜像 CCD | `47` |

CPU111 相对 CPU15 偏移一个 socket 的 96 个 physical-core 编号；两边 SMT sibling 也保持相同位置。helper CPU47 位于目标 CCD 之外，runner、`mpstat` 和辅助采样固定在 helper，不与目标 workload 争用执行核。

正式 invocation 的关键嵌套为：

```bash
source /nfs/home/tanghaojin/wolvrix-playground-gsim-calibrate-2/env.sh
taskset -c "$CPU" \
    numactl --physcpubind="$CPU" --membind="$NODE" \
    perf stat ... -- \
    setarch x86_64 -R "$NODE_LOCAL_EMU" ...
```

每个样本的 `/proc/$pid/status` 都确认 `Cpus_allowed_list` 只有目标 CPU，personality probe 为 `00040000`，即 `ADDR_NO_RANDOMIZE` 生效。这里同时保留 `taskset` 和 `numactl --physcpubind`，避免只依赖命令层级推断 affinity。

## 3. Formal acceptance gate

每个 50k 样本执行以下硬门槛：

1. **Pre-run whole-CCD gate**：连续 3 秒采样目标 CCD 的 16 个逻辑 CPU，要求 mean idle `>=98%`、minimum idle `>=95%`，目标 CPU 与 sibling 各自 `>=98%`；最多等待 60 个窗口。
2. **Continuous whole-CCD monitor**：workload 全程另起 `mpstat`，结束后排除 target 的 15 个线程必须 mean idle `>=98%`、minimum idle `>=95%`。只看运行前快照不算通过。
3. **Placement gate**：运行中读取 `numa_maps`，按实际 `/dev/shm` 路径累计 `emu` 和 `nemu.so` 的 N0/N1 页。
4. **PMU gate**：cycles、instructions、frontend empty、frontend `cmask>=6`、backend stalls 五项事件 scheduling 均须 `>=99.9%`；正式样本实际全部为 `100%`。
5. **Scheduler gate**：同时采集 task-clock、context-switches、cpu-migrations；context rate 必须 `<=20/s`，migration 必须为 `0`。
6. **功能 gate**：全部到达 guest/cycleCnt/instrCnt/PC=`50001/49996/73580/0x80001312`，且无 mismatch/assert/fatal/error。

正式 14 个样本中，`emu` 由于 ELF 大小不同共驻留约 `21,264..21,517` 页，`nemu.so` 固定 `115` 页；每个样本的这些页全部位于 execution node，没有远端残页。持续 monitor 的非 target mean idle 最低 `98.313%`、minimum idle 最低 `96.960%`；context rate 最大 `12.665/s`，所有 migration 为 `0`。

## 4. 污染 pilot 的拒绝

pilot4 证明 pre-run window、placement 和功能正确仍不足以接受样本：

```text
emu/nemu placement     21494 / 115 pages，全 N0
PMU scheduling         100%
functional endpoint    PASS
whole-CCD mean idle     81.125%
whole-CCD minimum idle  77.690%
context switches        46.430/s
cpu migrations          0
```

它因 continuous monitor 和 scheduler gate 失败被明确拒绝，PMU 数字不进入任何候选计算。随后 clean pilot5 达到：

```text
emu/nemu placement     21494 / 115 pages，全 N0
whole-CCD mean idle     98.615%
whole-CCD minimum idle  97.290%
context switches        11.130/s
cpu migrations          0
functional endpoint    PASS
```

clean pilot5 通过正式 acceptance criteria 后才启动双 node 序列。这避免把“运行前碰巧安静、运行中被同 CCD 负载污染”的样本误记成有效 A/B/A。

## 5. 序列与计算

每个 node 独立执行：

```text
control A1 / hybrid / control A2 / p050 / control A3 / p200 / control A4
```

hybrid、p050、p200 分别相对相邻的 `A1/A2`、`A2/A3`、`A3/A4` 算术均值计算 delta。六个包夹的 control cycles spread 绝对值最大为 `0.381049%`；control instructions 近似精确稳定。没有跨 node 平均，也没有使用 rejected pilot 或 same-post partial sample。

## 6. Corrected Stage 7/8 结果

以下正数表示候选回退，负数表示候选提升：

| 候选 | node | cycles | instructions | frontend empty | frontend `cmask>=6` | backend stalls |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| hybrid | N0 | `-4.237162%` | `-4.835541%` | `-4.179816%` | `-4.254670%` | `-5.528546%` |
| hybrid | N1 | `-4.352957%` | `-4.835541%` | `-4.412364%` | `-4.573177%` | `-4.575128%` |
| p050 | N0 | `-0.089541%` | `-0.292803%` | `+0.000176%` | `+0.007982%` | `-1.771969%` |
| p050 | N1 | `+0.079792%` | `-0.292807%` | `+0.106009%` | `+0.137066%` | `-0.206977%` |
| p200 | N0 | `+0.422334%` | `+0.072374%` | `+0.537835%` | `+0.375661%` | `+0.026398%` |
| p200 | N1 | `+0.343269%` | `+0.072459%` | `+0.379627%` | `+0.188124%` | `+0.338002%` |

### Stage 7 hybrid

旧协议得到 NUMA0 cycles `+4.36%..+4.96%`、NUMA1 `-12.23%..-12.48%` 的强反转；correct protocol 下两个 node 改为高度一致的 `-4.24%/-4.35%`。instructions、frontend 两项和 backend 也在两边一致改善，hybrid 是约 `4.3%` 的真实双 node 收益，不再是 socket-specific layout gamble。

### Stage 8 p050

旧协议的 `+7.21%/-9.58%` 反转消失。correct cycles 为 `-0.090%/+0.080%`，frontend 也在约 `0.14%` 内，判定 runtime 中性；稳定的 instructions `-0.293%` 没有转化为可分辨的 cycles 收益。N0 backend 控制自身存在更大 spread，不用该单项的 `-1.77%` 推翻整体中性结论。

### Stage 8 p200

旧协议的 `+11.69%/-10.01%` 反转同样消失。correct 两边 cycles 均轻微回退 `0.34%..0.42%`，instructions 和 frontend 方向一致，判定为温和负向；幅度不到 1%，但没有正向采用证据。

## 7. 当前决定与后续

- TNO0060/TNO0064 的跨 socket 方向反转不再作为这些候选的代码结论；其旧 raw artifacts 保留为错误控制变量下的历史观测。
- hybrid 的双 node 正收益重新打开采用评估，但本记录只完成历史 ELF 的 correct runtime 复核，不直接修改 current-default NO0300。
- p050 保持实验入口但判中性；p200 判轻微回退，不作为默认候选。
- same-post Stage 10/12/13 序列仍在运行。必须等完整包夹、placement 和所有 gate 闭合后另立新 TNO；本记录不披露或解释其 partial 数据。

原始产物：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/stage_binaries.sh
build/logs/xs_perf/page_local_retest_stage7plus_20260716/run_formal.sh
build/logs/xs_perf/page_local_retest_stage7plus_20260716/run_sequence.sh
build/logs/xs_perf/page_local_retest_stage7plus_20260716/pilot/
build/logs/xs_perf/page_local_retest_stage7plus_20260716/results/n0_rollback/
build/logs/xs_perf/page_local_retest_stage7plus_20260716/results/n1_rollback/
```

## 增量更新 2026-07-17：绝对数值补录/勘误

原文第 6 节只列出了候选相对相邻 control 均值的百分比，缺少 14 个 accepted sample 的绝对 PMU 计数。以下数值直接抄录对应 `*_perf.csv`，不是根据百分比反推。每个 node 各 `7` 个样本，顺序均为：

```text
control A1 / hybrid / control A2 / p050 / control A3 / p200 / control A4
```

包夹关系和样本数为：hybrid 对 `A1/A2` 两个 control 的算术均值，p050 对 `A2/A3` 两个 control 的算术均值，p200 对 `A3/A4` 两个 control 的算术均值；每个 candidate 在每个 node 只有 `1` 个 accepted sample。两个 node 独立计算，不跨 node 合并。

表中五列单位均为 `perf stat` 原始事件计数（count），不是 rate：

```text
cycles:u
instructions:u
de_no_dispatch_per_slot.no_ops_from_frontend:u
cpu/de_no_dispatch_per_slot.no_ops_from_frontend,cmask=0x6/u
de_no_dispatch_per_slot.backend_stalls:u
```

### N0 CPU15：7 个 accepted samples

| 顺序 | sample | cycles | instructions | frontend empty | frontend `cmask>=6` | backend stalls |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | control A1 | `285,702,689,746` | `172,881,422,971` | `1,308,046,177,799` | `170,015,377,218` | `95,021,704,046` |
| 2 | hybrid | `273,546,382,934` | `164,521,671,177` | `1,253,628,027,447` | `162,844,596,479` | `88,963,012,258` |
| 3 | control A2 | `285,596,968,222` | `172,881,422,226` | `1,308,580,047,992` | `170,146,584,180` | `93,316,694,657` |
| 4 | p050 | `285,657,821,032` | `172,375,213,266` | `1,309,425,031,942` | `170,294,005,366` | `92,745,334,934` |
| 5 | control A3 | `286,230,696,715` | `172,881,406,530` | `1,310,265,411,154` | `170,414,244,086` | `95,520,105,369` |
| 6 | p200 | `287,309,129,731` | `173,006,527,742` | `1,317,926,565,626` | `171,144,328,482` | `94,410,708,195` |
| 7 | control A4 | `285,970,957,946` | `172,881,406,597` | `1,311,487,025,236` | `170,593,379,184` | `93,251,479,383` |

原始路径：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/results/n0_rollback/control_a1_perf.csv
build/logs/xs_perf/page_local_retest_stage7plus_20260716/results/n0_rollback/hybrid_perf.csv
build/logs/xs_perf/page_local_retest_stage7plus_20260716/results/n0_rollback/control_a2_perf.csv
build/logs/xs_perf/page_local_retest_stage7plus_20260716/results/n0_rollback/p050_perf.csv
build/logs/xs_perf/page_local_retest_stage7plus_20260716/results/n0_rollback/control_a3_perf.csv
build/logs/xs_perf/page_local_retest_stage7plus_20260716/results/n0_rollback/p200_perf.csv
build/logs/xs_perf/page_local_retest_stage7plus_20260716/results/n0_rollback/control_a4_perf.csv
```

### N1 CPU111：7 个 accepted samples

| 顺序 | sample | cycles | instructions | frontend empty | frontend `cmask>=6` | backend stalls |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | control A1 | `287,733,376,866` | `172,881,422,339` | `1,319,624,114,439` | `171,984,584,052` | `95,109,875,460` |
| 2 | hybrid | `274,685,122,310` | `164,521,670,666` | `1,259,479,460,955` | `163,781,922,944` | `89,878,395,327` |
| 3 | control A2 | `286,639,055,274` | `172,881,421,848` | `1,315,610,962,051` | `171,277,233,365` | `93,265,322,514` |
| 4 | p050 | `286,868,791,154` | `172,375,212,641` | `1,316,626,506,505` | `171,448,079,393` | `93,423,031,747` |
| 5 | control A3 | `286,641,094,754` | `172,881,421,489` | `1,314,853,528,212` | `171,149,575,048` | `93,968,270,543` |
| 6 | p200 | `288,092,683,912` | `173,006,689,211` | `1,322,445,629,512` | `171,928,334,791` | `94,199,215,946` |
| 7 | control A4 | `287,573,170,881` | `172,881,421,681` | `1,320,034,988,424` | `172,061,432,195` | `93,795,515,703` |

原始路径：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/results/n1_rollback/control_a1_perf.csv
build/logs/xs_perf/page_local_retest_stage7plus_20260716/results/n1_rollback/hybrid_perf.csv
build/logs/xs_perf/page_local_retest_stage7plus_20260716/results/n1_rollback/control_a2_perf.csv
build/logs/xs_perf/page_local_retest_stage7plus_20260716/results/n1_rollback/p050_perf.csv
build/logs/xs_perf/page_local_retest_stage7plus_20260716/results/n1_rollback/control_a3_perf.csv
build/logs/xs_perf/page_local_retest_stage7plus_20260716/results/n1_rollback/p200_perf.csv
build/logs/xs_perf/page_local_retest_stage7plus_20260716/results/n1_rollback/control_a4_perf.csv
```

14 份 CSV 的五个 headline event scheduling 均为 `100.00%`。本补录只补齐原始绝对计数和样本映射，不改变原文 corrected delta、acceptance 或默认决策。

## 增量更新 2026-07-17：walltime headline 绝对值补录

最终性能 headline 采用 host walltime。以下按每个 node 的 `control A1 / hybrid / control A2 / p050 / control A3 / p200 / control A4` 顺序，直接读取对应 `Host time spent`（milliseconds）：

| node | control A1 | hybrid | control A2 | p050 | control A3 | p200 | control A4 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| N0 | `78,802` | `75,504` | `78,702` | `78,749` | `78,426` | `78,473` | `78,195` |
| N1 | `78,497` | `74,868` | `78,129` | `78,185` | `78,126` | `78,587` | `78,382` |

原始来源为同目录 `results/{n0_rollback,n1_rollback}/{control_a1,hybrid,control_a2,p050,control_a3,p200,control_a4}_emu.log`。按相邻 control 均值计算，walltime delta 为：hybrid N0/N1 `-4.124340%/-4.399014%`，p050 `+0.235477%/+0.073598%`，p200 `+0.207507%/+0.425537%`。因此 hybrid 的双 node wall headline 仍支持采用，p050/p200 仍为中性至轻微回退；原文 cycles 只能作为解释指标。
