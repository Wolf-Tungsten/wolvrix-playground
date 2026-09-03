# TNO0269: XiangShan RepCut closure-weight N=1 per-partition runtime diagnostic

日期：2026-09-02

状态：`DIAGNOSTIC COMPLETE; STRICT PERFORMANCE N/A; DEFAULT UNCHANGED`。

## 1. 结论

`N=1` 正适合回答本轮问题：K 仍为 32，runtime 用一个 worker 按 phase 串行执行 32 个
Verilator partition model，因此可以直接测到每个 model 的 `eval()` 时间、32 项总工作量和
最大单项。它不是“只分一个区”，也不能单独回答 N=32 的并行 walltime。

在同一 `node033/CPU104/NUMA1` 上做 AB 与 BA 两序后，closure-aware 相对 baseline 的结果为：

- 最慢 partition `eval`：`560.432 -> 449.490 us/step`，降低 **19.796%**；
- 32 个 partition 的 `eval` 总和：`2706.794 -> 3446.704 us/step`，增加 **27.335%**；
- `eval` CV：`1.0622 -> 0.6169`，降低 **41.918%**；
- Host time 均值：`64.296 -> 79.490 s`，增加 **23.631%**；
- 两个顺序的 Host time 代价分别为 `+23.393%/+23.877%`，方向不依赖固定先后顺序。

所以新权重完成了它的第一目标：显著削小最大分区并压低长尾；但 N=1 下的串行总工作量明显
增加，当前不是无条件 runtime 改善。另一个 clean-v4 node038 单序样本也给出“max 降、sum/host
升”，但幅度为 `-33.331%/+6.942%/+6.199%`，与 node033 差异很大。当前可认为**方向稳定，
精确幅度不稳定**；所有性能数值都只能作为 shared-host diagnostic，不能升级为 strict headline。

## 2. 实验口径

两侧 build/function identity 见
[TNO0268](./TNO0268_xiangshan_repcut_closure_weight_runtime_build_and_function_gate_20260902.md)。
本轮固定：

| 项目 | 值 |
| --- | --- |
| K / N / C | `32 / 1 / 10000` |
| benchmark | `coremark-2-iteration.bin`，以 cycle limit 截止 |
| host / CPU / NUMA | `node033 / 104 / 1` |
| order | AB：baseline -> closure-aware；BA：closure-aware -> baseline |
| affinity | model 仅 CPU104；monitor CPU191；`numactl --physcpubind=104 --membind=1` |
| ASLR / locale | `setarch x86_64 -R` / `LC_ALL=C` |
| timing | schema v1，`20102` steps，1 summary + 3 phase + 32 part = 36 records |
| admission policy | `diagnostic`：保留 whole-CCD admission、guard、affinity 和 target-busy 门；只放宽其他 CCD CPU 的 foreign-task ticks |

每个 order 都先执行两侧 C=100 功能门，再执行两侧 C=10000。四个 C=10000 样本均为
`rc=0`，终点完全一致：

```text
terminal_pc=0x800027c6
guest_cycles=10001
instr_count=458
cycle_count=9996
requested_threads=1
effective_threads=1
```

本文的 `eval_avg_us` 是一个 partition model 每个内部 timing step 的平均 `eval()` 时间；
`total_avg_us` 是归属于该 partition 的 `input_apply + eval + update_push`，不是并行运行时该
partition 的独立 walltime。不同分法中的 `part_N` 不代表同一组 RTL，不能按相同编号做逻辑块
的一一差分；只能在各自分法内看分布、sum、max 和已知 giant owner。

## 3. 构建与运行身份

两侧均从排除 package `build/` 缓存的新 staging 目录 fresh build，所有 partition object、外层
runtime object 和 ELF 只包含 Clang 21.1.5 marker：

| mode | assignment SHA-256 | ELF SHA-256 | ELF size |
| --- | --- | --- | ---: |
| baseline | `c2712f03b0ed58f23db1b49be1f3809d35b4abb290415abc88ed0a3044f308f3` | `355a2c7df9faec3e8f56591b53e5e214f7b0a3bf8453549bd3dc4cf55afadd77` | 261,042,608 B |
| closure-aware | `ffefbb1d1373cb30290e6725479d339b87e637f3db32132dcbe416fd2c52d589` | `b5803a654b2f63057f71337ae02137089e8d28177c2b0e41918fefdc6c778b55` | 269,966,456 B |

AB/BA accepted header 记录了完全相同的两个 ELF、两个 build manifest、runner、protocol、image、
NEMU 和 topology；每个样本 launch/finish 的 ELF SHA 均闭合。补充人工审计冻结：

```text
clang/clang++ binary SHA-256 = 20b172bbe08040e4926a535b77bc08ee4eb479540f5edf9543230b3d54d1d357
verilator script SHA-256      = 1acb1eccaa423c175b22f5ee1e4402508a9bf8273d2fea6f15870c03afd0e8bb
difftest HEAD                 = 5d20df0547758922d9f4fc8aa24b803af4ffbb6a
difftest diff SHA-256         = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

build manifest 本身尚未自动绑定上述工具 binary、Difftest 源码、linker/ar/system header 和
compile log hash；runner 也只 fail-close 复验 manifest mode 及 ELF path/size/SHA。当前人工
审计闭合了本次关键身份，但这是后续 formal protocol 应补的 provenance，不在本文中冒充已实现。

## 4. Host 与 phase 结果

### 4.1 两序 Host time

| order | baseline | closure-aware | 变化 |
| --- | ---: | ---: | ---: |
| AB | 65.251 s | 80.515 s | +23.393% |
| BA | 63.341 s | 78.465 s | +23.877% |
| mean | **64.296 s** | **79.490 s** | **+23.631%** |

baseline 的 AB/BA spread 为 `2.971%`，closure-aware 为 `2.579%`。candidate 的 32 个
partition 均为 AB 慢于 BA，baseline 为 28/32，说明存在约 2.6%-3.0% 的批次漂移；但相对
A/B penalty 只差 `0.484 pp`，没有改变方向。

### 4.2 phase 和 per-part aggregate

| 指标，`us/step` | baseline | closure-aware | 变化 |
| --- | ---: | ---: | ---: |
| phase `input_load` | 4.9135 | 4.9155 | +0.041% |
| phase `part_eval` | 2712.7975 | 3453.2345 | +27.294% |
| phase `global_update` | 476.6320 | 491.2480 | +3.067% |
| part `eval` sum | 2706.7940 | 3446.7035 | +27.335% |
| part `eval` max | 560.4315 | 449.4895 | -19.796% |
| part `eval` CV | 1.0622 | 0.6169 | -41.918% |
| attributed `total` sum | 3180.9270 | 3935.7125 | +23.728% |
| attributed `total` max | 618.1370 | 475.7325 | -23.038% |
| attributed `total` CV | 0.9863 | 0.5670 | -42.510% |

Host time 增量主要发生在 `part_eval`，而不是 global input/update。candidate 的 partition
object 数量只增加 `2.597%`，ELF 大小增加 `3.419%`；静态 final ops total 增加 `4.480%`，
但 runtime eval sum 增加 `27.335%`，说明简单 op 数量不能线性解释当前串行成本。

### 4.3 PMU

| pooled mean | baseline | closure-aware | 变化 |
| --- | ---: | ---: | ---: |
| instructions | 270.400 B | 285.040 B | +5.414% |
| cycles | 234.654 B | 290.018 B | +23.594% |
| task-clock | 64.376 s | 79.553 s | +23.577% |
| average GHz | 3.6451 | 3.6456 | +0.014% |
| IPC | 1.1523 | 0.9828 | -14.709% |

两侧平均频率相同，不能用降频解释 node033 的差值。instructions 的增幅接近 ELF/final-op
增幅，但 cycles 增幅更大，表明 candidate 还增加了 stall。TNO0266 的 compute/communication
KM1 分别增加 `60.414%/56.822%`，更大的复制/边界工作和代码/数据局部性下降都是合理候选；
当前 PMU 没有 cache/TLB/branch 事件，不能把 stall 唯一归因到其中某一项。

## 5. 32 个 partition 的实际 eval 时间

下表为 node033 AB/BA 的 pooled `eval_avg_us`，单位 `us/step`。完整 AB、BA、pooled
input/eval/update/total 和静态字段保存在第 9 节 CSV。

### 5.1 baseline

| Part | us | Part | us | Part | us | Part | us |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 36.331 | 8 | 86.117 | 16 | 37.164 | 24 | 95.733 |
| 1 | 70.692 | 9 | 42.555 | 17 | 44.018 | 25 | 93.961 |
| 2 | 84.674 | 10 | 59.010 | 18 | 67.739 | 26 | 62.674 |
| 3 | 560.432 | 11 | 74.490 | 19 | 37.507 | 27 | 55.977 |
| 4 | 104.514 | 12 | 126.847 | 20 | 40.768 | 28 | 56.520 |
| 5 | 102.753 | 13 | 80.548 | 21 | 41.343 | 29 | 66.111 |
| 6 | 130.747 | 14 | 40.799 | 22 | 37.999 | 30 | 63.016 |
| 7 | 127.999 | 15 | 53.902 | 23 | 40.153 | 31 | 83.703 |

### 5.2 closure-aware

| Part | us | Part | us | Part | us | Part | us |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 96.908 | 8 | 449.490 | 16 | 99.045 | 24 | 52.094 |
| 1 | 115.513 | 9 | 73.507 | 17 | 92.193 | 25 | 63.418 |
| 2 | 123.672 | 10 | 121.199 | 18 | 127.975 | 26 | 66.645 |
| 3 | 142.168 | 11 | 141.393 | 19 | 116.718 | 27 | 66.374 |
| 4 | 65.656 | 12 | 140.749 | 20 | 86.477 | 28 | 126.168 |
| 5 | 96.093 | 13 | 87.332 | 21 | 93.301 | 29 | 87.214 |
| 6 | 115.068 | 14 | 122.108 | 22 | 66.836 | 30 | 56.963 |
| 7 | 96.762 | 15 | 79.306 | 23 | 98.354 | 31 | 80.012 |

### 5.3 最慢项和 giant owner

| mode | top 5 `eval_avg_us` |
| --- | --- |
| baseline | `part_3 560.432`; `part_6 130.747`; `part_7 127.999`; `part_12 126.847`; `part_4 104.514` |
| closure-aware | `part_8 449.490`; `part_3 142.168`; `part_11 141.393`; `part_12 140.749`; `part_18 127.975` |

giant ASC owner 从 baseline `part_3` 移到 closure-aware `part_8`。其 AB/BA/mean eval 分别为
`573.120/547.743/560.432 us` 和 `455.738/443.241/449.490 us`；20102 steps 内累计 eval
约为 `11.266 -> 9.036 s`。但 candidate giant 仍是次慢 partition 的 `3.162x`，baseline
原为 `4.286x`：长尾被削弱，没有消失。

## 6. 静态权重与 runtime 的对应关系

| 与 `eval_avg_us` 的相关性 | baseline Pearson / Spearman | closure-aware Pearson / Spearman |
| --- | ---: | ---: |
| `hyper_partition_weight` | 0.208 / 0.006 | 0.880 / 0.341 |
| exact closure weight | 0.946 / 0.567 | 0.933 / 0.589 |
| final graph ops | 0.969 / 0.824 | 0.947 / 0.697 |
| cross-endpoint words | 0.469 / 0.312 | 0.351 / 0.212 |

closure-aware solver weight 与 runtime giant 的 Pearson 对齐明显改善，说明优先修
`hyper_partition_weight` 的方向正确；但其 Spearman 仅 0.341，细粒度 partition 排序仍不准，
且 Pearson 受 giant outlier 强烈影响。当前 weight 更适合解决最大项，不足以同时最小化串行
总量或通信/locality 成本。

## 7. node038 补充样本与幅度边界

在 node033 正反序前，clean-v4 同一对 ELF 曾在 `node038/CPU152/NUMA1` 完成单次 AB：

| 指标 | baseline | closure-aware | 变化 |
| --- | ---: | ---: | ---: |
| Host time | 65.805 s | 69.884 s | +6.199% |
| eval sum | 2729.490 | 2918.970 us/step | +6.942% |
| eval max | 568.780 | 379.198 us/step | -33.331% |
| eval CV | 1.0662 | 0.6150 | -42.318% |

随后 BA candidate 在运行中遭遇外部任务，guard mean/min 降到 `96.807%/57.684%`，被门禁
拒绝；后续 admission 也未恢复。因此 node038 没有完整反序，不与 node033 pooled 混算。

node038 和 node033 的 baseline eval sum 接近，而 node033 candidate 的各 partition 普遍比
node038 慢 12%-32%；两节点硬件型号相同、同为 AMD EPYC 9684X。candidate 显示出更强的
shared-cache/批次环境敏感性，但当前没有 cache PMU 和 strict quiet 样本，不能确定根因。这正是
本文把方向与幅度分开、拒绝 formal headline 的原因。

## 8. 对并行测试点的含义

仅用当前 attributed per-part total 做理想化下界
`max(sum/N, max_partition)`，忽略依赖、worker 调度、global phase 和通信开销：

| N | baseline lower bound | closure-aware lower bound | 变化 |
| ---: | ---: | ---: | ---: |
| 1 | 3180.927 | 3935.713 | +23.728% |
| 4 | 795.232 | 983.928 | +23.728% |
| 6 | 618.137 | 655.952 | +6.118% |
| 7 | 618.137 | 562.245 | -9.042% |
| 8 | 618.137 | 491.964 | -20.412% |
| 9+ | 618.137 | 475.733 | -23.038% |

这不是预测值，只说明 work/max tradeoff 的理想交叉点约在 N=7；N=4 即使理想调度也难抵消
总工作量增加。若继续 runtime gate，N=8 比 N=4 更有判别力：它是第一个既接近交叉点、又能
验证 max 改善是否转化为 walltime 的既有线程档。K=N=32 是否最好仍需实际调度和通信数据，
不能从这个下界直接推出。

## 9. 运行期审计和证据边界

node033 四个 C=10000 样本都通过启动前 full-CCD admission、CPU104 affinity、NUMA、功能
签名、guard `mean>=98%/min>=95%` 和 target unexplained-busy 门；但 continuous audit 均因
其他 CCD CPU 的 foreign ticks 超过严格 `0.5%` 门限而失败：

| order / mode | foreign ticks / limit | guard mean / min |
| --- | ---: | ---: |
| AB baseline | 674 / 34 | 99.453% / 98.349% |
| AB closure-aware | 791 / 42 | 99.418% / 97.565% |
| BA closure-aware | 439 / 41 | 99.606% / 97.414% |
| BA baseline | 399 / 33 | 99.610% / 97.129% |

runner 的 diagnostic policy 只忽略 `runtime_foreign_task_load` 后才接受这些样本；原始
`runtime_audit.passed` 都是 `false`。因此本文可以回答 per-part cost、sum/max tradeoff 和
方向一致性，不能提供 strict performance headline 或默认落地依据。

关键 artifact：

| artifact | SHA-256 |
| --- | --- |
| node033 AB accepted | `62679f5626efca31eca81361deef46a2e0f1a259e75a0bcbc737f946f76cb7ee` |
| node033 BA accepted | `7ab263ad1b052b7b86a86ffab70f561bd3ac8660c280a6216adc272840922f2f` |
| AB summary | `7ed5d93c7e99e3beda8d49a6180aaa865f900571b3e2d975534b18426a3f0f2e` |
| BA summary | `4288c9a7f0cf5eb43e362ba5aeacee22457544a6f0bf311189b9ac46839c0f71` |
| pooled summary | `70ca2f948f2981195c9cf5b9340e009655637d5d6e141bc0eef306308d83cb65` |
| pooled per-part CSV | `dbfaa547dc73f0281cad71bf6281bbd6d1f73add7ef3cbfe56058213d8d531bc` |
| node038 AB summary | `3a6f6f7ac253524792ae3d9b53f24f2b441f07c4f8cc0c65bf23b11b4a9d5710` |

主要路径：

```text
build/repcut_closure_runtime_20260902/results-clean-v4-node033-pooled/summary.json
build/repcut_closure_runtime_20260902/results-clean-v4-node033-pooled/per_partition_pooled.csv
build/repcut_closure_runtime_20260902/runs/node033_ccd104_cleanv4_diagnostic_ab_20260902_1450/accepted.json
build/repcut_closure_runtime_20260902/runs/node033_ccd104_cleanv4_diagnostic_ba_20260902_1456/accepted.json
```

旧 `results/`、`results-v2/` 的混工具链 A/B 已由 TNO0268 明确标记为 INVALID，不参与本文
任何表格或结论。

## 10. 决策

- closure-aware mode 继续保持实验开关，baseline 默认不变；
- 不在本轮拆大 ASC；
- N=1 已完成 per-part 诊断：保留“max 明显改善、serial work 增加”的结论；
- 精确幅度等待 strict quiet 复测，下一项有判别力的并行 canary 是 N=8/C=10000；
- 在 N=8 或更高并行度证明 walltime 收益前，不建议仅凭静态 max 改善落地为默认。

## 11. 独立复核补充（2026-09-02）

三路只读复核分别检查了 build/runtime identity、phase/partition/PMU 算术和 64 行 pooled CSV。
所有 pooled 字段均严格等于 AB/BA 均值，32/32 partition 均为 20102 steps；未发现缺项、重复、
NaN、hash 漂移或把 `pre_rebuild_ops` 误标为 final ops 的问题。

跨 node033/node038 最稳健的结论进一步收敛为：

- max/CV 在两节点都明显下降；
- instructions 在两节点都增加约 `5.4%`，这是当前最稳定的额外串行工作证据；
- Host penalty 的观测范围为约 `+6%..+24%`，eval-sum penalty 为约 `+7%..+27%`，不能把
  node033 的 `+23.631%` 当作环境无关常数；
- node033 attributed total 增量 `754.786 us/step` 中，eval 增量 `739.910 us/step`，占
  `98.029%`；问题不在 update phase；
- `eval sum/max` 从 `4.830` 提高到 `7.668`，量化了“串行工作更多、并行潜力更高”的取舍。

node033/node038 的 CPU model 和 microcode 都是 EPYC 9684X / `0xa101248`，但 kernel 分别为
`6.8.0-124-generic` 和 `6.8.0-136-generic`，且使用不同 CCD 位点；这些因素与 foreign load
一起构成跨节点幅度差的未消除变量。

最后，C=10000 终点只有 guest `instr_count=458`，是按 host cycle limit 截断的早期诊断，
不是完整 CoreMark 执行。下一步可以先用 N=8 验证理想交叉点；若要形成线程缩放结论，应覆盖
N=2/4/8/16/32，并至少包含 N=32，而不是用 N=1 外推。
