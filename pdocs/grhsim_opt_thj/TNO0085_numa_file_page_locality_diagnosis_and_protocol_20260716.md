# TNO0085 NUMA file-page locality diagnosis and controlled runtime protocol

记录日期：2026-07-16

状态：完成历史跨 NUMA 反转的绑定审计和双节点 file-page locality 受控矩阵。正式命令的 CPU/NUMA 绑定语法正确，但 `membind` 不会迁移已经存在的 NFS file-backed text/page-cache 页；初始 probe 已观测 CPU59/membind0 的 `emu` text 共 `21,227` 页全部驻留 N1，而 CPU155/membind1 运行同一 inode 时为本地。使用 `/dev/shm` 独立 inode 固定 file-page placement 后，远端 file set 在 N0/N1 分别比本地 A 均值慢 `2.79%/3.48%`，两个节点的 local 均值仅差 `0.18%`。因此历史 socket 方向反转不能直接归因于代码，后续 50k 必须增加 node-local inode、镜像核、全 CCD quiet 和 `numa_maps` placement gate。

## 1. 正式绑定命令审计

正式运行采用以下嵌套关系：

```bash
source /nfs/home/tanghaojin/wolvrix-playground-gsim-calibrate-2/env.sh
numactl --physcpubind="$CPU" --membind="$NODE" \
    setarch x86_64 -R "$EMU" ...
```

`--physcpubind` 将 workload 固定在指定逻辑 CPU，`--membind` 为该进程后续新分配的内存设置 node policy，`setarch -R` 关闭 ASLR。语法、包裹顺序和实际 CPU affinity 均正确；本轮问题不是把 CPU 或 node 参数写反。

但这条命令不能保证已经存在的 executable/file mapping 被重新放到 `$NODE`：

- NFS 上同一路径对应同一个 page-cache inode；
- file-backed 页一旦已经 fault 到某个 node，后续进程映射时可直接复用这些物理页；
- `membind` 约束新分配页，不会因为另一个进程在不同 node 上重新映射该 inode 就迁移已有 page-cache 页；
- `/proc/$pid/status` 的 `Mems_allowed_list` 表示 cpuset 允许范围，不等价于当前 NUMA allocation policy，file placement 必须从 `/proc/$pid/numa_maps` 逐 VMA 验证。

初始交互 probe 的直接证据是：

| execution | policy | `emu` file pages | locality |
| --- | --- | ---: | --- |
| CPU59 / N0 | `--physcpubind=59 --membind=0` | `21,227` | 全部 `N1`，对执行核为远端 |
| CPU155 / N1 | `--physcpubind=155 --membind=1` | 同一 binary/inode | `N1`，对执行核为本地 |

因此“CPU 与 anonymous memory policy 都绑到本地 node”不能推出“`emu` text 也在本地”。同一 NFS inode 的共享 page cache 已经足以让此前所谓 local NUMA A/B/A 混入 file-text locality。

## 2. 受控矩阵设计

为只改变 file-page residence，本轮把同一套 `emu`、`nemu.so` 和 `coremark.bin` 分别复制到：

```text
/dev/shm/grhsim_numa_locality_probe_tanghaojin_20260716/n0/
/dev/shm/grhsim_numa_locality_probe_tanghaojin_20260716/n1/
```

`/dev/shm` 本身不是“自动 node-local”的目录；这里依赖的是两个全新、互不共享的 inode 分别在目标 node first-touch，并在运行中用 `numa_maps` 验证。两份内容 byte-identical，但 inode 不同：`emu` 大小均为 `94,768,184` bytes、SHA256 均为 `453b5dad1b332facbfe1bc229256b08a88a3b304f4a4f60b7a124a843f639976`，N0/N1 inode 分别为 `5289/5292`。

执行核采用 socket-relative 镜像位置：

| node | CPU / SMT sibling | 相对位置 |
| --- | --- | --- |
| N0 | `75/267` | socket 0 core 75，L3/CCD slot 1 |
| N1 | `171/363` | socket 1 对应 core，L3/CCD slot 1 |

每个 execution node 都保持 `--membind` 指向执行核本地 node，只通过选择 N0 或 N1 的独立 file set 构造 `local A1 / remote B / local A2`。所有样本均关闭 ASLR，并得到相同功能终点：`instrCnt=458`、`cycleCnt=9996`、guest cycles `10001`。本矩阵使用 10k 作为低成本 locality 诊断，不替代 activity-schedule 候选的正式 SimTop 50k 裁决。

## 3. Placement gate

运行约 5 秒后读取 `/proc/$pid/numa_maps`，按实际 `emu` 和 `nemu.so` 路径累计 file-backed 页：

| execution / file set | `emu` N0/N1 pages | `nemu.so` N0/N1 pages |
| --- | ---: | ---: |
| N0 local A1/A2 | `21,494 / 0` | `115 / 0` |
| N0 remote B（N1 copy） | `3 / 21,491` | `5 / 110` |
| N1 local A1/A2 | `0 / 21,494` | `0 / 115` |
| N1 remote B（N0 copy） | `21,491 / 3` | `110 / 5` |

local A 的两轮均为 exact local placement；remote B 的 `emu` 有 `21,491/21,494` 页位于 copy node，只有 3 页残留在执行 node，file-set 方向仍是明确且近乎完整的远端。`nemu.so` 只有 115 页，即使保留 5 页残差也远小于约 21.5k 页的 `emu` 主体。后续正式 gate 应保留这些 exact counts，不用“执行了 `membind`”替代实测。

## 4. 10k A/B/A 结果

| execution | local A1 | remote B | local A2 | local 均值 | remote 相对 local 均值 |
| --- | ---: | ---: | ---: | ---: | ---: |
| CPU75 / N0 | `10,246 ms` | `10,466 ms` | `10,117 ms` | `10,181.5 ms` | `+2.79%` |
| CPU171 / N1 | `10,170 ms` | `10,517 ms` | `10,156 ms` | `10,163.0 ms` | `+3.48%` |

两个 remote B 都比各自两侧的 local 样本更慢，方向不依赖 A 均值算法。N0 与 N1 的 local 均值只差 `18.5 ms`，相对两者均值约 `0.18%`；在 file placement、镜像核和同一功能终点受控后，本轮没有复现历史上约 `8%..12%` 的 node 固有速度差。

这不能证明全部历史反转都只来自 page cache：node 空闲内存明显不对称，外部负载会在 CCD 间迁移，历史 runtime 也并非总使用 socket-relative 镜像核心。当前矩阵证明的是 file-page locality 单独就能制造约 `3%` 的稳定差异，幅度已经足以污染小优化并改变接近中性的符号。

原始诊断产物位于被 git 忽略的目录：

```text
build/logs/xs_perf/numa_page_probe_n0_20260716.log
build/logs/xs_perf/numa_page_probe_n1_20260716.log
build/logs/xs_perf/run_numa_locality_probe.sh
build/logs/xs_perf/numa_locality_probe_20260716/
```

## 5. 对历史跨 NUMA 结论的修正

[TNO0060](./TNO0060_stage7_cross_socket_runtime_and_default_decision_20260715.md)、[TNO0064](./TNO0064_stage8_cross_numa_runtime_and_default_decision_20260716.md)、[TNO0074](./TNO0074_stage10_same_poststats_corrected_runtime_20260716.md) 和 [TNO0081](./TNO0081_stage12_commit_guard_merge_cap_cross_numa_runtime_20260716.md) 都记录过明显 socket 方向反转。它们对“不能把单 socket 收益直接晋升默认”的保守决策仍然成立，但因果标签需要降级：

- 当时验证了 CPU affinity、`membind`、ASLR、功能终点和局部 sibling quiet；
- 没有逐样本验证 NFS-backed `emu` text 的实际 node；
- 没有隔离全 CCD 负载、node memory 状态和非镜像核心位置；
- 因而不能把反转直接写成 activity schedule、native code layout 或 socket frontend 的代码因果。

历史数字仍可作为“旧协议下的整机观测”和风险旁证，但若要判断某个候选的真实性能符号，必须按下节的新协议重测，不能继续对两个 socket 的旧结果做平均或挑选有利 node。

## 6. 后续 SimTop 正式协议

1. **Fresh per-node inode**：A/B 每个 binary、`nemu.so` 和 image 都在 `/dev/shm` 为 N0/N1 创建独立 inode；先校验 SHA/size，再在目标 node first-touch。禁止两个 node 复用同一 NFS inode，也禁止两个 node 复用同一 `/dev/shm` inode。
2. **镜像核心**：跨 node 使用 socket-relative 相同 core/CCD slot，并同时记录 SMT sibling、socket、core 和 L3 ID；A/B 在同一 node 内不得换核。
3. **全 CCD quiet gate**：quiet 检查覆盖与目标核共享 L3/CCD 的全部逻辑 CPU，而不只检查目标核及其一个 sibling；若有外部 `emu`、编译或持续负载进入该 CCD，整组拒绝或重跑。
4. **正式 invocation**：每条命令先 `source env.sh`，再使用 `numactl --physcpubind=CPU --membind=node` 包裹 `setarch x86_64 -R` 和 perf/workload；保存完整命令或环境快照。
5. **逐样本 placement gate**：workload 存活期间读取 `numa_maps`，至少分别累计 `emu`、`nemu.so` 和主要 image 的 N0/N1 页；预期 local file pages 不在目标 node 的样本直接拒绝。`Mems_allowed_list` 只能作为 cpuset 辅助信息。
6. **包夹顺序**：单候选使用 A/B/A；两个候选或需要抵消线性时间漂移时使用 ABBA，并在每个 node 独立形成完整包夹。控制 spread、gate-to-run gap、PMU scheduling 和功能终点继续按既有规则审计。
7. **反转诊断**：若两个 node 的候选 delta 仍反向，增加 `execution node × file-page node` 的 2x2 矩阵。只有 placement gate 通过后，才继续讨论 CPU/frontend、CCD 或代码布局交互。

后续 Stage 13 以及新的 activity-schedule 候选仍以 current-default NO0300、ASLR 关闭的 SimTop 50k 为最终口径；本轮只修正 runtime 实验的控制变量，不改变默认生成配置。
