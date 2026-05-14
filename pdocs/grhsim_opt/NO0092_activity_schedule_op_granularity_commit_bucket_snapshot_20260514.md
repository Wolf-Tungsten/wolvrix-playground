# NO0092 Activity-Schedule Op 粒度重构与 Commit 分桶 50k 快照

> 2026-05-14 记录当前 `activity-schedule` op 粒度主路径、commit supernode 独立分桶修复后的 XiangShan GrhSIM 结构与 CoreMark 50k 速度。该快照用于后续继续优化 boundary value 数和 runtime 的对照基线。

## 1. 配置

当前 GrhSIM emit 关键参数：

| 参数 | value |
| --- | ---: |
| `max-op-in-compute-supernode` | `128` |
| `max-op-in-commit-supernode` | `4096` |
| `enable_coarsen` | `true` |
| `enable_chain_merge` | `true` |
| `waveform` | `off` |

commit supernode 保持独立于 compute coarsen / DP；当前分区策略为按 canonical event key 全局分桶，桶内保持 topo 顺序，再按 `max-op-in-commit-supernode` 切块。

## 2. Supernode 与跨 Supernode Value

统计来源：

```text
build/xs/grhsim/grhsim_emit/activity_schedule_supernode_stats.json
```

| 指标 | value |
| --- | ---: |
| total supernodes | `69,054` |
| compute supernodes | `62,823` |
| commit supernodes | `6,231` |
| dag edges | `1,171,582` |
| boundary values | `1,573,742` |
| boundary activation edges | `2,754,717` |
| compute-compute value pairs | `2,366,673` |
| compute-commit value pairs | `388,044` |
| ops / supernode mean | `104.259` |
| ops / supernode median | `122` |
| ops / supernode p90 | `128` |
| ops / supernode p99 | `128` |
| ops / supernode max | `4096` |

这里 `boundary_values` 是跨 supernode 的唯一 value 数；`boundary_activation_edges` 是跨 supernode 的 value-use 激活边数量。

## 3. CoreMark 50k 速度

运行命令：

```bash
/usr/bin/time -p bash -lc 'cd build/xs/grhsim && ./emu -i /home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/ready-to-run/coremark-2-iteration.bin --diff /home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so -b 0 -e 0 -C 50000'
```

结果：

| 指标 | value |
| --- | ---: |
| guest cycle spent | `50,001` |
| core cycleCnt | `49,996` |
| guest instrCnt | `73,580` |
| guest IPC | `1.471718` |
| host time from emu | `557,266 ms` |
| wall time | `557.28 s` |
| simulation speed | `89.72 cycles/s` |
| instruction speed | `132.0 instr/s` |
| end PC | `0x80001312` |

运行跑满 `-C 50000`，以 cycle limit 正常结束；本轮未观察到 difftest mismatch 或 assert。

## 4. 对比前一版 Commit Run 碎片化状态

commit 分桶修复前，同一套 compute 粒度下曾得到：

| 指标 | 修复前 | 当前 |
| --- | ---: | ---: |
| total supernodes | `94,383` | `69,054` |
| compute supernodes | `62,823` | `62,823` |
| commit supernodes | `31,560` | `6,231` |
| boundary values | `1,573,742` | `1,573,742` |
| boundary activation edges | `2,835,577` | `2,754,717` |
| compute-commit value pairs | `468,904` | `388,044` |
| CoreMark 50k speed | `78.25 cycles/s` | `89.72 cycles/s` |

结论：本轮主要回收了 commit event key 被 topo run 打散造成的 supernode 膨胀。compute supernode 数不变，total supernodes 从 `94,383` 降到 `69,054`，50k 速度从 `78.25 cycles/s` 提升到 `89.72 cycles/s`，约 `+14.7%`。

## 5. 后续观察点

- 当前 `boundary_values=1,573,742` 仍高于旧 compute-node 主路径，需要继续优化 compute 侧 boundary value 紧密度。
- `boundary_activation_edges=2,754,717` 相比 commit 分桶修复前下降有限，说明 runtime 后续主要空间仍在 compute-compute value 传播和生成代码执行成本。
- commit supernode 数已回到旧路径同量级，后续不应再用 compute 参数间接调 commit 粒度；commit 粒度继续由 `max-op-in-commit-supernode` 独立控制。

## 6. 增量更新 2026-05-14：`max-op=108` 对齐 GSim Supernode 数

为了让 GrhSIM 的 total supernodes 与当前 GSim 结构规模对齐，本轮将 compute 侧 DP 参数调整为：

| 参数 | value |
| --- | ---: |
| `max-op-in-compute-supernode` | `108` |
| `max-op-in-commit-supernode` | `4096` |

GSim 当前 total supernodes 为 `84,714`；GrhSIM 在 `max-op=108` 下为 `84,718`，只多 `4` 个。

### 6.1 结构指标

统计来源：

```text
build/xs/grhsim/grhsim_emit/activity_schedule_supernode_stats.json
```

| 指标 | value |
| --- | ---: |
| total supernodes | `84,718` |
| compute supernodes | `78,487` |
| commit supernodes | `6,231` |
| dag edges | `1,177,552` |
| boundary values | `1,362,927` |
| boundary activation edges | `2,600,941` |
| compute-compute value pairs | `2,212,897` |
| compute-commit value pairs | `388,044` |
| ops / supernode mean | `84.982` |
| ops / supernode median | `97` |
| ops / supernode p90 | `108` |
| ops / supernode p99 | `108` |
| ops / supernode max | `4096` |
| outdeg mean | `13.900` |
| outdeg p99 | `158` |
| outdeg max | `5,372` |

emit 侧耗时：

| 阶段 | time |
| --- | ---: |
| activity-schedule total | `389,927 ms` |
| coarsen | `331,229 ms` |
| write_grhsim_cpp | `42,619 ms` |
| total emit | `455,323 ms` |

### 6.2 CoreMark 50k 速度

运行命令：

```bash
/usr/bin/time -p ./emu -i /home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/ready-to-run/coremark-2-iteration.bin --diff /home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so -b 0 -e 0 -C 50000
```

结果：

| 指标 | value |
| --- | ---: |
| guest cycle spent | `50,001` |
| core cycleCnt | `49,996` |
| guest instrCnt | `73,580` |
| guest IPC | `1.471718` |
| host time from emu | `470,382 ms` |
| wall time | `470.39 s` |
| simulation speed | `106.29 cycles/s` |
| instruction speed | `156.42 instr/s` |
| end PC | `0x80001312` |

运行跑满 `-C 50000`，以 cycle limit 正常结束；本轮未观察到 difftest mismatch 或 assert。

### 6.3 与 `max-op=128` 的直接对比

| 指标 | `max-op=128` | `max-op=108` | 变化 |
| --- | ---: | ---: | ---: |
| total supernodes | `72,226` | `84,718` | `+17.3%` |
| compute supernodes | `65,995` | `78,487` | `+18.9%` |
| commit supernodes | `6,231` | `6,231` | `0.0%` |
| dag edges | `1,065,038` | `1,177,552` | `+10.6%` |
| boundary values | `1,350,816` | `1,362,927` | `+0.9%` |
| boundary activation edges | `2,532,450` | `2,600,941` | `+2.7%` |
| CoreMark 50k wall time | `493.14 s` | `470.39 s` | `-4.6%` |
| CoreMark 50k speed | `101.39 cycles/s` | `106.29 cycles/s` | `+4.8%` |

结论：单纯让 compute supernode 更小会增加 supernode / DAG edge / boundary activation edge，但这次 `max-op=108` 反而比 `128` 更快。当前结果说明 runtime 速度不只由跨 supernode activation 数量决定，单个 supernode 的代码体量、局部代码布局、编译器优化结果和 cache/frontend 压力也会显著影响 50k wall time。
