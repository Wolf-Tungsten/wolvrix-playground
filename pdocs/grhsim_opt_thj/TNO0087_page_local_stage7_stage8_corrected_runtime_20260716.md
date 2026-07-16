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
