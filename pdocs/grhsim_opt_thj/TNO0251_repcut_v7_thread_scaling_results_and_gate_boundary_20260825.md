# TNO0251: RepCut v7 线程缩放结果与正式性能门禁边界

日期：2026-08-25

状态：`FUNCTIONAL/CANARY SNAPSHOT AVAILABLE; FORMAL 32-SAMPLE HEADLINE N/A`。

本记录对应 [TNO0238](./TNO0238_repcut_thread_scaling_experiment_protocol_20260819.md) 预注册的映射：

| 协议名称 | 本轮 runner backend |
| --- | --- |
| `run_xs_repcut` | `native`，每个 N 使用对应 `--threads N` ELF |
| `run_xs_repcut_verilator` | `partitioned`，同一 partitioned ELF，运行时 `XS_EMU_THREADS=N` |

## 1. 证据身份

正式 runner 使用：

```text
manifest: build/repcut_fix_20260825/build-manifest-v7-final2.json
manifest sha256: e92779e48e76874898c62a3bd841e3e808a585a0653f15f41c6d2bdb1bdf7352
CCD: physical 152-159, SMT siblings 344-351, NUMA node 1
monitor CPU: 320
```

正式前置 canary 的完整 accepted 文件：

```text
build/repcut_fix_20260825/results/canary_v7_final2_ccd152/accepted_samples.jsonl
sha256=a93042dd719c358f89331bc4d51038561ed9bfe2a471271fe6e0774db705172f
records=16 (2 backend x 4 thread counts x 2 cycle counts)
```

canary runner 对 PMU event set（task-clock、cycles、instructions、context-switches、cpu-migrations、page-faults）和 output/timing/signature 做了严格解析；但 canary 阶段明确跳过了 formal quiet/foreign-load gate。因此下面的 C=10000 数值是“功能通过的单样本 snapshot”，不是 32 样本正式 headline。

## 2. 功能 canary 的 1/2/4/8 对比

所有 16 条 canary 均 `accepted`。C=100 的共同签名为 `EXCEEDING CYCLE/INSTR LIMIT @0x0, instr=0, cycle=96, guest=101`；C=10000 的共同签名为：

```text
EXCEEDING CYCLE/INSTR LIMIT @0x800027c6
instr=458, cycle=9996, guest=10001
```

partitioned C=100 的 timing steps 为 `302`，C=10000 为 `20102`；native 没有 partition timing JSONL。

### 2.1 C=10000 host time

单位：ms；每格是同一 `accepted_samples.jsonl` 中的一个样本，不能解释为均值/置信区间。

| backend / 协议 | N=1 | N=2 | N=4 | N=8 |
| --- | ---: | ---: | ---: | ---: |
| `run_xs_repcut` / native | 27699 | 14358 | 8751 | 5870 |
| `run_xs_repcut_verilator` / partitioned | 59355 | 38710 | 26434 | 16633 |

由该单样本 snapshot 计算的同 backend 相对 N=1 speedup：

| backend | N=1 | N=2 | N=4 | N=8 |
| --- | ---: | ---: | ---: | ---: |
| native speedup | 1.000x | 1.929x | 3.165x | 4.719x |
| native efficiency | 100.0% | 96.5% | 79.1% | 59.0% |
| partitioned speedup | 1.000x | 1.533x | 2.245x | 3.569x |
| partitioned efficiency | 100.0% | 76.7% | 56.1% | 44.6% |

同 N 的 partitioned/native 比值为 `2.143x / 2.696x / 3.021x / 2.834x`（N=1/2/4/8）。这说明当前 v7 partitioned 路径在此 C=10000 snapshot 上明显更慢，不能据此宣称正式线程缩放收益或跨后端最终结论。

### 2.2 C=100 smoke 对比

| backend / 协议 | N=1 | N=2 | N=4 | N=8 |
| --- | ---: | ---: | ---: | ---: |
| `run_xs_repcut` / native | 426 | 260 | 174 | 133 |
| `run_xs_repcut_verilator` / partitioned | 947 | 690 | 420 | 271 |

该表只用于确认短路径和签名，不能替代 C=10000/C=30000 的吞吐量实验。

## 3. 独立 v7 functional gate 交叉检查

不纳入 canary 统计的独立脚本输出位于：

```text
build/repcut_fix_20260825/logs/functional-v7/
```

八个 C=10000 gate 也都通过同一签名。其 wall（受脚本启动时间和当时负载影响）为：

| backend | N=1 | N=2 | N=4 | N=8 |
| --- | ---: | ---: | ---: | ---: |
| native | 24.36 s | 14.38 s | 8.82 s | 5.90 s |
| partitioned | 59.70 s | 38.02 s | 25.95 s | 16.27 s |

这组 wall 与 canary Host time 的差异是不同运行时刻/封装的正常现象；headline 只允许从单一 accepted JSONL 来源计算，不能拼接两组数据。

## 4. 为什么没有正式 32 样本表

formal runner 要求每个 C=30000 样本同时满足：

1. 端点 signature `EXCEEDING ... @0x80000442, instr=27809, cycle=29996, guest=30001`；
2. native/partitioned 的 binary、manifest、generated-source identity 不变；
3. admission、连续 CCD guard、CPU/NUMA affinity 和 foreign task load 全通过；
4. PMU event set 完整且每个 event `run_percent >= 99.99`；
5. 16 槽 canary 已被当前 manifest 接受。

在这台共享机器上，正式尝试均在首槽或其重试阶段被外部任务拒绝，没有一个 accepted C=30000 sample：

| output tag | raw attempts | accepted | 主要拒绝 | 证据 SHA-256 |
| --- | ---: | ---: | --- | --- |
| `formal_v7_final2` (ccd56) | 7 | 0 | `runtime_foreign_task_load`, admission idle | `93c63bbf8d555f3b978e9af45d2c63348aa3566b0b2d8237ef2f342ccfef4109` |
| `formal_v7_final2_ccd152` | 4 | 0 | `runtime_guard_mean_idle`, foreign load | `ee000c180dc505e8c18ba05f6e1419860cb55b17ae887b21618dce7f1fac1cb1` |
| `formal_v7_final2_ccd176` | 1 | 0 | `runtime_foreign_task_load` | `6d21068ac4a1228922db7be1073968ef0c648fd97311c39724b199b8b79ceb27` |

典型 ccd176 长样本的连续审计为 `foreign_cpu_ticks=1347`，对应允许上限 `37`；记录中的外部任务是长期 `hapi/GC/HeapHelper`，不是 emu。若把这些样本放进均值，会把共享主机负载误报成仿真性能，因此正式 headline、median、spread、ABBA/BAAB gap 均记为 `N/A`。

## 5. 可发布结论与后续入口

- 可以发布：v7 修复后 native/partitioned 在 C=100/C=10000 的功能签名一致；上表给出一组可追溯的 1/2/4/8 单样本 timing snapshot。
- 不能发布：`run_xs_repcut` 与 `run_xs_repcut_verilator` 的正式 C=30000 32 样本均值、置信区间、ABBA/BAAB 稳定性或最终 speedup。当前正式结果是 `N/A — host quiet/foreign gate blocked`，不是功能失败。
- 继续实验时，应在整段 CCD quiet 且无长期 hapi/GC worker 的机器窗口执行同一命令；不要复用 `formal_v7_final2*` 的半成品目录，也不要把 accidental `canary_probe_manifest` 纳入统计。
