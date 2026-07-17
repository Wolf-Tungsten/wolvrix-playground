# TNO0098 Stage 7+ strict NUMA window recheck and retest queue

记录日期：2026-07-17

状态：窗口审计完成，性能复测待安静窗口。按 [TNO0089](./TNO0089_page_local_stage12_stage13_interim_runtime_and_strict_numa_protocol_20260717.md) 的 whole-node strict gate 连续执行两轮 30 秒复查：N0 两轮均通过，N1 两轮虽满足 mean idle 门槛，却因单核 minimum idle 只有 `65.82%/78.79%` 被正确拒绝。污染与 affinity 为 `0-383`、在 N1 物理核间迁移的外部 PID `2816950` 对应；本任务未 kill 该进程、也未修改其 affinity，因此没有启动 control/candidate perf。17 组待测 binary 已完成双 node 独立 inode staging，跨 node 内容 SHA 相同。复测队列继续有效，不判 blocked、不降低 `mean>=99%/min>=95%` gate，也不沿用此前受 page-cache/NUMA 错判影响的默认关闭结论。

## 1. 本轮只审计 admission，不产生性能数字

Stage 7+ 的历史 NUMA 方向反转已由 file-backed page locality 和过窄的 CCD monitor 解释；当前有效协议必须同时满足 node-local inode 与 whole-node quiet window。[TNO0092](./TNO0092_stage14_native_hybrid_default_adoption_decision_20260717.md) 已基于 corrected 双 node 结果采用 native hybrid default，但 strict ABBA/BAAB 仍是待补确认项；[TNO0094](./TNO0094_stage14_native_hybrid_commit_cap_fresh_gate_20260717.md) 的 current cap 矩阵也仍缺同协议下的 runtime 裁决。

本轮目标只是确认现在是否具备启动这些复测的入口条件。两轮 30 秒 whole-node survey 为：

| round | N0 mean idle | N0 min idle | N0 gate | N1 mean idle | N1 min idle | N1 gate |
| ---: | ---: | ---: | --- | ---: | ---: | --- |
| `1` | `99.673%` | `95.28%` | PASS | `99.550%` | `65.82%` | FAIL |
| `2` | `99.727%` | `96.00%` | PASS | `99.600%` | `78.79%` | FAIL |

门槛保持：192 个 logical CPU 的 mean idle `>=99%`、任一 logical CPU minimum idle `>=95%`，且目标 CPU 与 SMT sibling 各自 idle `>=98%`。N1 两轮的 mean 都超过 `99%`，但 minimum 明确失败；大多数核空闲不能掩盖一个持续受扰核。由于 dual-node strict 队列没有形成完整 admission，本轮在 `perf stat` 前停止，没有 control、candidate、cycles、instructions 或 PMU 样本。这里的 FAIL 是环境 gate FAIL，不是任何 Stage 7+ candidate 的性能 FAIL。

## 2. N0/N1 不对称的直接原因

窗口期间观察到 PID `2816950`：

```text
htop instantaneous load: about 38% of one logical CPU
Cpus_allowed_list:        0-383
observed physical pair:   CPU168/360, later CPU176/368
```

`168/360` 与 `176/368` 分别是 N1 上两个 physical core 的 SMT pair。该进程没有被绑到固定 CPU，调度器先后把它迁到这两个核；其负载与 N1 minimum idle 下降的时空位置一致。N0 同期连续两轮通过，说明此刻的不对称来自可迁移的外部工作，而不是两个 NUMA node 的硬件拓扑不对称，也不是 `taskset`/`numactl` 参数写反。

`htop` 的约 `38%` 仅是定位污染源的瞬时旁证，正式 gate 仍以 30 秒 `mpstat` 汇总为准。PID 不属于本任务控制范围，本轮没有 kill、renice 或改变其 affinity；也不通过放松 minimum idle 门槛把污染窗口包装成有效样本。

## 3. 推荐的镜像核与 helper

后续两个 node 分开、顺序执行，使用 socket-relative CCD5 的镜像核：

| node | target CPU | SMT sibling | CCD logical CPU range | helper CPU |
| ---: | ---: | ---: | --- | ---: |
| N0 | `43` | `235` | `40-47,232-239` | `191` |
| N1 | `139` | `331` | `136-143,328-335` | `95` |

target CPU 与 sibling 位于同一 physical core；两个 node 的 target 具有相同 socket-relative offset。helper 放在对侧 node，避免 gate/monitor 自己消耗被测 node 的 minimum-idle 预算。N0 与 N1 workload 不并发运行；测 N0 时使用 helper191，测 N1 时使用 helper95。运行前仍需重新读取 `lscpu -e`/`numactl --hardware`，并在 workload 期间审计 `/proc/$pid/status` 与 `numa_maps`，不能只凭这张静态表假定拓扑和 placement 正确。

## 4. 正确绑定与 fixed-ASLR 命令

每次 shell 命令先执行 `source env.sh`。以参数化形式，pre-run gate 与正式 50k invocation 为：

```bash
source /nfs/home/tanghaojin/wolvrix-playground-gsim-calibrate-2/env.sh

taskset -c "$HELPER_CPU" \
    mpstat -P "$NODE_CPUS" 1 30 > "$WHOLE_NODE_GATE_LOG"

taskset -c "$CPU" \
    numactl --physcpubind="$CPU" --membind="$NODE" \
    perf stat -x, -o "$PERF_CSV" -e "$EVENTS" -- \
    setarch x86_64 -R "$NODE_LOCAL_EMU" \
        -i "$NODE_LOCAL_IMAGE" --diff "$NODE_LOCAL_NEMU" \
        -b 0 -e 0 -C 50000 > "$EMU_LOG" 2>&1
```

其中 N0 的 `NODE_CPUS=0-95,192-287`，N1 为 `96-191,288-383`。`taskset -c` 与 `numactl --physcpubind` 双重限定同一 target CPU，`--membind` 约束新分配页，`setarch x86_64 -R` 对应默认性能基线 NO0300 的 fixed-ASLR。file-backed executable/reference 页不能靠 `membind` 从共享 inode 自动迁移，所以 `$NODE_LOCAL_*` 必须来自该 node 自己的 `/dev/shm` inode。

正式脚本还必须保留：gate-to-run gap、全程 191 个 non-target logical CPU monitor、target affinity/migration、ASLR personality `00040000`、`numa_maps` local-page ratio、PMU scheduling、task-clock/context-switch、功能终点与负向日志扫描。命令写法正确只是必要条件，不替代这些运行期证据。

## 5. 双 node staging 审计

当前复测矩阵的 17 组 experiment binary 均已分别 staging 到 N0/N1 的 node-local 目录。逐组审计满足：

```text
sha256(n0/group) == sha256(n1/group)
inode(n0/group)  != inode(n1/group)
```

跨 node SHA 相同保证两边执行同一 binary 内容；独立 inode 保证 N0/N1 不共享同一 file-backed page-cache identity。CoreMark image 与 `nemu.so` 同样必须按 node 独立 staging 并校验内容。后续可以直接等待 quiet window，不需要为解决污染重新生成 binary；若重建了任一候选，则整组重新 staging 到全新目录并重做 SHA/inode 审计，不复用旧 inode。

## 6. Strict 复测优先队列

安静窗口出现后按以下优先级执行，每个对象都使用 current page-local/whole-node protocol 和平衡 AB/BA 顺序；受污染的 pair 整体作废：

| priority | matrix | 目的 |
| ---: | --- | --- |
| `1` | `s14_off` / `s14_default` | 先闭合 Stage 7+ corrected hybrid 与 Stage 14 C++ native-default 的 strict 确认；同时验证 explicit `0/0` NO0300 回滚。 |
| `2` | current default cap4096 / cap8192，再 cap16384 / cap32768 | 先裁决 [TNO0094](./TNO0094_stage14_native_hybrid_commit_cap_fresh_gate_20260717.md) 的最接近候选；若 8192 无信号，再完成 16384/32768 次序，不按 raw BAE 预判。 |
| `3` | Stage 10 same-post off / strict | 重测 fanin pullback，替换旧 page-cache/whole-node 不充分样本。 |
| `4` | Stage 13 candidates；必要时 Stage 12 controls | 优先看 canonical slot-stable Stage 13；只有归因或历史对照需要时再补 Stage 12，避免无目的扩矩阵。 |
| `5` | Stage 8 p050 / p200 | 最后复核 penalty 候选；已知 corrected 信号较小，不抢占更高价值 quiet window。 |

每完成一个 matrix 都另立结果 TNO，并据最新双 node 证据重新判断此前因 NUMA 错判而关闭的选项是否应成为 C++ native default。旧的“默认关闭”不是不可推翻的结论，但也不能仅凭 N0 admission PASS 或历史单 node/perf 数字改默认。

## 7. Gate 与决策边界

- 当前状态不是 blocked：binary/staging/命令和队列都已就绪，可以继续 Stage 16 的独立工作并等待下一次安静窗口。
- 不把 N0 两轮 PASS 外推成 N1 可测，也不只跑 N0 后宣称跨 NUMA 结论；默认采用需要有效的双 node strict 证据。
- 不把 N1 minimum gate 从 `95%` 降到 `65%..79%`，不删除 whole-node monitor，也不以目标 CCD 安静代替整 node 安静。
- 不生成空的 perf 结果或引用功能 50k wall time；本轮唯一结论是“环境污染已定位，perf 未启动”。
- 默认配置继续以 current C++ native defaults 为唯一来源；XS/脚本只提供显式 sparse override，不为单一平台暗设另一套默认。

下一次 gate 通过后，先运行 priority 1 的 `s14_off/default` 平衡对照。只有其 pre-run、runtime、placement、PMU、scheduler 和功能 gate 全部通过，才进入 cycles/instructions/前后端事件的性能裁决，并继续下一个队列项。

## 8. 增量更新 2026-07-17：N1 P0 retry admission 仍被拒绝

Stage 14 P0 的 N1 strict balanced run 启动前再次执行 30 秒 whole-node gate。对 N1 的 `96-191,288-383` 共 `192` 个 logical CPU 逐项重算 `mpstat` average：

| metric | result | threshold | gate |
| --- | ---: | ---: | --- |
| logical CPU count | `192` | `192` | PASS |
| whole-node mean idle | `99.652%` | `>=99%` | PASS |
| whole-node minimum idle | `81.49% @ CPU104` | `>=95%` | **FAIL** |
| target CPU139 idle | `99.83%` | `>=98%` | PASS |
| sibling CPU331 idle | `100.00%` | `>=98%` | PASS |

target 与 sibling 均安静，whole-node mean 也通过，但 CPU104 的 `81.49%` 明确低于 minimum gate；不能用目标 CCD 安静或全 node 高平均值掩盖单核污染。因此本次 N1 retry 按既定协议在 admission 阶段停止，没有启动 `perf stat` 或 emu，没有形成 control/candidate、cycles、instructions 或功能样本。

本任务仍未 kill、renice 或修改任何外部进程的 affinity，也没有降低 `min>=95%` 门槛。该结果只说明当前 N1 quiet window 仍不合格，不改变 [TNO0099](./TNO0099_stage14_native_hybrid_n0_strict_balanced_runtime_20260717.md) 的 N0 有效结果，也不是 native-hybrid candidate 的性能失败。P0 N1 ABBA+BAAB 与其后的 Stage 7+ 队列继续等待满足全部 hard gates 的窗口。

原始 30 秒 gate：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/window_recheck_20260717_n1_p0_retry/n1.log
```
