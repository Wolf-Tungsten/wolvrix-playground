# TNO0272: XiangShan RepCut closure-weight N=1 node030 CCD80 runtime diagnostic

日期：2026-09-04

状态：'DIAGNOSTIC COMPLETE; STRICT PERFORMANCE N/A; DEFAULT UNCHANGED'。

## 1. 结论

本轮按要求只在 node030 的物理 CPU '0-95' 范围内扫描完整 CCD，最后选择
CCD80（物理 CPU '80-87'，SMT sibling '272-279'，NUMA0）。同一 clean-v4
baseline/candidate ELF 在该 CCD 完成 N=1 的 AB 与 BA 两个顺序；每个顺序都
通过 C=100 功能门和 C=10000 的 32-part timing/signature gate。

node030 的背景 CI 任务使 continuous runtime audit 的 foreign-task 门没有
通过，因此这不是 strict performance headline。diagnostic policy 只忽略
runtime_foreign_task_load；目标 CPU/完整 CCD guard、affinity、NUMA、PMU、
binary hash 和功能签名仍保留为硬门。

同 CCD 的 AB/BA pooled 结果如下（C=10000，N=1，单位按行标注）：

| 指标 | baseline | closure-aware | 变化 |
| --- | ---: | ---: | ---: |
| Host time AB (s) | 58.778 | 86.540 | +47.232% |
| Host time BA (s) | 59.549 | 87.835 | +47.500% |
| Host time mean (s) | 59.164 | 87.188 | **+47.367%** |
| 32-part eval sum (us/step) | 2447.895 | 3826.762 | **+56.329%** |
| eval max (us/step) | 495.739 | 492.410 | **-0.671%** |
| eval population CV | 1.0353 | 0.6056 | **-41.501%** |
| attributed total sum (us/step) | 2925.866 | 4319.445 | +47.630% |
| attributed total max (us/step) | 553.365 | 518.810 | -6.244% |

因此 node030 再次复现此前的方向：closure-aware 明显降低分区分布的离散度，
并降低最大项相对第二项的长尾比，但最大 eval 本身基本持平；N=1 串行总
工作量增加，Host time 反而上升。[TNO0269](./TNO0269_xiangshan_repcut_closure_weight_n1_partition_runtime_diagnostic_20260902.md)
中的 node033 pooled Host
增幅 '+23.631%'、node038 的单序样本 '+6.199%' 不能与本轮原始时间混池；
跨节点当前只能说方向一致、幅度高度依赖运行窗口和局部性。

runner 的 elapsed-wall 均值为 '61.125 -> 89.645 s'（'+46.659%'）；上表
使用仿真日志的 Host time，二者均指同一 N=1 串行执行，只是计时边界略有不同。

## 2. 实验口径

| 项目 | 值 |
| --- | --- |
| K / N / C | '32 / 1 / 10000'（C=100 作为功能 gate） |
| benchmark | coremark-2-iteration.bin，按 '-C' cycle limit 截止 |
| host / target CPU / NUMA | node030 / CPU80 / NUMA0 |
| full CCD monitor | '80-87,272-279' |
| monitor CPU | '191' |
| AB | baseline -> closure-aware |
| BA | closure-aware -> baseline |
| model affinity | 仅 CPU80；numactl --physcpubind=80 --membind=0 |
| ASLR / locale | setarch x86_64 -R / LC_ALL=C |
| timing contract | schema v1，C=100 '302' steps，C=10000 '20102' steps，36 records |
| admission | 3 x 1 s，mean idle >= 98%，min idle >= 95% |
| runtime policy | diagnostic；仅过滤 runtime_foreign_task_load |

N=1 表示一个 worker 串行执行 32 个 partition model，不是把 RTL 只分成
一个 partition。eval_avg_us 是单个 model 每个内部 timing step 的平均
eval() 时间；total_avg_us 是该 partition 的 input/eval/update 归属和，
都不是 N=32 并行 walltime。

## 3. 0-95 扫描与 CCD 选择

扫描只覆盖 NUMA0 的物理核 '0-95'，但每个候选都按完整 16 个 logical CPU
（8 个物理核及其 sibling）计算。15 秒窗口的前三名为：

| CCD base | full logical CPUs | mean idle | min idle | busy ticks |
| ---: | --- | ---: | ---: | ---: |
| 0 | '0-7,192-199' | 99.230% | 96.667% | 184 |
| 80 | '80-87,272-279' | 99.083% | 96.796% | 220 |
| 8 | '8-15,200-207' | 98.706% | 95.391% | 310 |

随后对前三名各做一次完整 3 x 1 s admission：

| CCD base | aggregate mean/min | interval min | 结果 |
| ---: | ---: | --- | --- |
| 0 | 99.646% / 99.333% | 99.00%, 98.02%, 99.00% | pass |
| 80 | 98.836% / 96.013% | 96.00%, 95.96%, 96.04% | pass |
| 8 | 97.934% / 95.000% | 88.00%, 95.00%, 96.00% | reject |

在随后的即时轮询中 CCD80 的聚合 mean/min 为 '99.354%/96.656%'，三个
interval 的 min 为 '96.04%/96.00%/96.97%'，因此选 CCD80。node030 上有
持续的 CI emu/NEMU 任务；此前 CCD0 和 CCD80 的 strict 入场分别因
runtime_foreign_task_load、admission 波动或目标核运行期干扰而未形成
strict pair。本节扫描值只用于说明选点，不替代运行期 audit。

扫描 stdout 已整理为只读 snapshot（它不是 accepted runtime artifact）：

    build/repcut_closure_runtime_20260902/node030_scan_0_95_snapshot_20260904.json
    SHA-256 090415a880b1dd3fc63d0839c34c029faa67ee34e72860aea361a08797b95eff

本轮是显式的 0-95 自定义筛选；仓库中的 scan_ccds.py 默认仍会遍历更大的
CPU 范围。

## 4. 构建与输入身份

两侧均为 [TNO0268](./TNO0268_xiangshan_repcut_closure_weight_runtime_build_and_function_gate_20260902.md)
记录的 clean-v4 fresh build，排除了 package build/
缓存，compiler marker 为 Clang 21.1.5，Verilator 为 5.048。baseline 与
closure-aware 的 assignment、manifest 和 ELF identity 为：

| mode | assignment SHA-256 | build manifest SHA-256 | ELF SHA-256 | ELF size |
| --- | --- | --- | --- | ---: |
| baseline | c2712f03b0ed58f23db1b49be1f3809d35b4abb290415abc88ed0a3044f308f3 | f52633e1d753b5da2219e96f58f734134a7e750616f8a4e4f65bd0375514d605 | 355a2c7df9faec3e8f56591b53e5e214f7b0a3bf8453549bd3dc4cf55afadd77 | 261,042,608 B |
| closure-aware | ffefbb1d1373cb30290e6725479d339b87e637f3db32132dcbe416fd2c52d589 | c1489ae14dbe564f57598f7093431e9842c5d2187dbeca3a3bc752cd343c90d2 | b5803a654b2f63057f71337ae02137089e8d28177c2b0e41918fefdc6c778b55 | 269,966,456 B |

本轮 accepted header 还固定了：

    runner SHA-256   3f50e79f1f47fbd81ed3f21d4fd71b27709d3ffd692f3853e0e88ee1fe2db9bd
    protocol SHA-256 3bd5681185f0b9d0c6acfd783b67001a86c8441644eef66307314360b8a33a70
    image SHA-256    c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e
    NEMU SHA-256     094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e

运行命令的关键差异只有顺序和 artifact tag。AB 使用：

    .venv/bin/python build/repcut_closure_runtime_20260902/run_n1_pair.py
      --baseline-binary build/repcut_closure_runtime_20260902/clean-v4/baseline/partitioned-emu/verilator-compile/emu
      --candidate-binary build/repcut_closure_runtime_20260902/clean-v4/closure-aware/partitioned-emu/verilator-compile/emu
      --baseline-build-manifest build/repcut_closure_runtime_20260902/clean-v4/baseline/build-manifest.json
      --candidate-build-manifest build/repcut_closure_runtime_20260902/clean-v4/closure-aware/build-manifest.json
      --output-tag node030_ccd80_cleanv4_diagnostic_ab_20260904_1240
      --cpu-base 80 --numa-node 0 --monitor-cpu 191 --policy diagnostic
      --arm-order baseline-first --max-attempts 20

BA 只将 output-tag 改为 node030_ccd80_cleanv4_diagnostic_ba_20260904_1250，
并将 arm-order 改为 candidate-first。

clean-v4 的 build-time source_head 为
054c6a7c09b007a12eb36fdb49fcb659a1bfc590；当前 checkout 后续可能已前进。
build manifest 绑定了 ELF/assignment/toolchain marker，但没有自动绑定完整
source diff、工具 binary 和 compile log hash，故复跑时应以本节 identity 和
[TNO0268](./TNO0268_xiangshan_repcut_closure_weight_runtime_build_and_function_gate_20260902.md)
的 provenance 为准。

## 5. Host、phase 与 PMU

### 5.1 Phase 分解

| 指标 (us/step) | baseline | closure-aware | 变化 |
| --- | ---: | ---: | ---: |
| input_load | 4.800 | 4.851 | +1.063% |
| part_eval | 2453.904 | 3833.317 | +56.213% |
| global_update | 480.397 | 494.831 | +3.005% |
| partition eval sum | 2447.895 | 3826.762 | +56.329% |

Host 增量主要落在 part_eval；input 和 global update 不是主因。按 attributed
per-part total 计算，新增 total 为 1393.580 us/step，其中 eval 增量
1378.868 us/step，占约 98.94%。

### 5.2 PMU pooled mean

| 事件/派生量 | baseline | closure-aware | 变化 |
| --- | ---: | ---: | ---: |
| instructions | 270.367 B | 285.098 B | +5.449% |
| cycles | 215.692 B | 317.782 B | +47.331% |
| task-clock | 59.252 s | 87.262 s | +47.272% |
| average GHz | 3.6402 | 3.6417 | +0.041% |
| IPC | 1.2535 | 0.8972 | -28.427% |
| context-switches | 160.5 | 209.0 | +30.218% |
| page-faults | 11,130 | 11,289.5 | +1.433% |

两侧频率几乎相同，不能用降频解释差值；candidate 的 instructions 只增加
约 5.45%，但 cycles 增加约 47.33%，同时 IPC 下降，说明存在额外 stall/
局部性压力。当前事件集合没有 cache/TLB/branch 计数器，不把该压力唯一
归因到某一类硬件事件。

## 6. 32 个 partition 的实际 eval 时间

下表是 AB/BA 两序逐项均值后的 eval_avg_us（us/step）。不同 mode 的
同名 part_N 不是同一 RTL 片段，不能按编号做逻辑块一一差分。

### 6.1 baseline

| Part | us | Part | us | Part | us | Part | us |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 46.201 | 8 | 65.173 | 16 | 33.094 | 24 | 77.438 |
| 1 | 67.762 | 9 | 40.791 | 17 | 39.002 | 25 | 83.910 |
| 2 | 80.983 | 10 | 56.298 | 18 | 61.010 | 26 | 58.889 |
| 3 | 495.739 | 11 | 58.585 | 19 | 36.620 | 27 | 48.247 |
| 4 | 85.747 | 12 | 121.120 | 20 | 37.780 | 28 | 47.671 |
| 5 | 96.486 | 13 | 73.597 | 21 | 39.240 | 29 | 63.556 |
| 6 | 113.233 | 14 | 39.459 | 22 | 37.763 | 30 | 63.403 |
| 7 | 123.541 | 15 | 51.502 | 23 | 33.234 | 31 | 70.822 |

### 6.2 closure-aware

| Part | us | Part | us | Part | us | Part | us |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 105.806 | 8 | 492.410 | 16 | 107.329 | 24 | 61.221 |
| 1 | 132.223 | 9 | 81.629 | 17 | 101.997 | 25 | 71.168 |
| 2 | 137.266 | 10 | 134.707 | 18 | 140.515 | 26 | 73.537 |
| 3 | 153.809 | 11 | 155.254 | 19 | 128.453 | 27 | 72.642 |
| 4 | 72.204 | 12 | 157.735 | 20 | 99.856 | 28 | 139.990 |
| 5 | 107.326 | 13 | 96.654 | 21 | 100.506 | 29 | 103.118 |
| 6 | 128.265 | 14 | 134.953 | 22 | 74.760 | 30 | 65.421 |
| 7 | 106.443 | 15 | 91.230 | 23 | 107.682 | 31 | 90.654 |

### 6.3 长尾

| mode | top 5 eval_avg_us |
| --- | --- |
| baseline | part_3 495.739; part_7 123.541; part_12 121.120; part_6 113.233; part_5 96.486 |
| closure-aware | part_8 492.410; part_12 157.735; part_11 155.254; part_3 153.809; part_18 140.515 |

CSV 中还保留每个 partition 的 total_avg_us=input_apply+eval+update_push；
其 top 5 分别为 baseline：part_3 553.365、part_7 137.885、part_12
134.997、part_6 133.802、part_4 116.473；closure-aware：part_8
518.810、part_11 194.866、part_12 184.199、part_3 165.337、part_14
164.158（均为 us/step）。

giant owner 从 baseline part_3 移到 closure-aware part_8。最大项与第二
大项的比值约从 4.013x 降到 3.122x，但 candidate 的 giant 仍然明显存在。
baseline 的 giant 在 20102 steps 内累计 eval 约 9.967 s，candidate giant
约 9.899 s；因此 max 几乎不变，而额外时间来自更多中等大小 partition。
对应地，32-part eval median 从 59.949 增至 106.125 us/step
（约 +77.02%）；去掉各自 giant 后的 eval sum 仍从 1952.156 增至
3334.352 us/step（约 +70.80%），说明总量代价不是单一 part_8 造成。

## 7. 静态字段与 runtime 的对应关系

node030 pooled 的 eval_avg_us 相关性如下：

| 静态字段 | baseline Pearson / Spearman | closure-aware Pearson / Spearman |
| --- | ---: | ---: |
| hyper_partition_weight | 0.192 / -0.064 | 0.882 / 0.346 |
| exact_referenced_closure_weight | 0.948 / 0.540 | 0.933 / 0.588 |
| estimated_node_weight_sum | 0.953 / 0.599 | 0.946 / 0.665 |
| pre_rebuild_ops | 0.958 / 0.767 | 0.915 / 0.603 |
| final_graph_ops | 0.970 / 0.811 | 0.945 / 0.688 |
| cross_endpoint_words | 0.467 / 0.257 | 0.349 / 0.191 |

closure-aware 的 solver weight 对 eval 的 Pearson 对齐明显变好，但 Spearman
仍只有 0.346，不能据此认为细粒度排序已经准确。更重要的是，当前 runtime
显示总 eval work 增加约 56%，所以后续应同时优化总量和 locality，不能只追求
最大 partition。

## 8. Runtime audit 与 strict 边界

C=10000 的 accepted 样本在 diagnostic 过滤前的主要审计值为：

| order / arm | foreign ticks / limit | guard mean / min | unexplained target busy (s) | audit |
| --- | ---: | ---: | ---: | --- |
| AB baseline | 586 / 31 | 99.302% / 98.027% | 0.043 / 0.305 | foreign-only fail |
| AB closure-aware | 1227 / 45 | 99.052% / 97.756% | 0.028 / 0.446 | foreign-only fail |
| BA closure-aware | 1449 / 46 | 98.924% / 96.460% | 0.038 / 0.450 | foreign-only fail |
| BA baseline | 793 / 31 | 99.095% / 96.761% | 0.023 / 0.305 | foreign-only fail |

四个样本均 observed_model=true、无 affinity violation、无 audit error，
目标核 unexplained busy 均低于对应上限；runtime_audit.passed=false 仅由
foreign ticks 超过严格的 0.5% 限额。foreign work 主要来自 guard sibling；
其中 3/4 个 C=10000 样本各有 1 tick 的 kworker/80:2-events 出现在目标
CPU80，但没有触发 target-busy 或 affinity 门。这仍不是完全隔离的运行窗口。
C=100 的 audit 同样可能记录 foreign ticks，但 C=100 只用于功能 gate，
不作为性能样本。

本轮还保留了两个未闭合的 strict 尝试：

    runs/node030_ccd0_cleanv4_strict_ab_20260904_1235
    runs/node030_ccd80_cleanv4_strict_ab_20260904_1236

前者在 baseline C=10000 未找到可接受样本，后者在重复
runtime_foreign_task_load 后人工停止；两者都没有 accepted.json，不参与
任何 summary/pooled 数字。它们证明当前 node030 背景负载下 strict headline
无法闭合，而不是证明 candidate 的功能或签名有问题。

## 9. Artifact 与复核路径

### 9.1 Accepted runtime

| artifact | SHA-256 |
| --- | --- |
| node030 AB accepted | b1504f8d8694a413b3badf5dc362ee3af0179999951333a3265b1fcc36b92807 |
| node030 BA accepted | 5613c1d73fe2f43993abc124881030ef1d5b32df8e031864fe3a35975e21fecb |
| AB summary | 8e79706ef665ff0de1ec35d55af7e267e7cfbea7bc2a60229312fbc6c5bf8374 |
| AB per-part CSV | 430198aa667d751d80c300f775fc2ec07eb145d8421fced0ad4b913f7c650113 |
| BA summary | cc883210b064aecfec8c0bcc8ce34aafdc48438d27e7f3364e21b71cbcaeae34 |
| BA per-part CSV | 36463593054f4a0bb3b8fe5ef0a65ed30d9c9a4745795e57cebbaa1949c54346 |
| pooled summary | ee8c4451edac3f3c74be370cfd361a9b2e50a42c218b52a04d60d310e3c076ed |
| pooled per-part CSV | 5ccab608cceb64ae8cb6c0bd8961483eac8cad537f724a0b2a4d50e61a098dc3 |
| 0-95 scan snapshot | 090415a880b1dd3fc63d0839c34c029faa67ee34e72860aea361a08797b95eff |

主要路径：

    build/repcut_closure_runtime_20260902/runs/
      node030_ccd80_cleanv4_diagnostic_ab_20260904_1240/accepted.json
      node030_ccd80_cleanv4_diagnostic_ba_20260904_1250/accepted.json
    build/repcut_closure_runtime_20260902/results-clean-v4-node030-ab/
    build/repcut_closure_runtime_20260902/results-clean-v4-node030-ba/
    build/repcut_closure_runtime_20260902/results-clean-v4-node030-pooled/

### 9.2 复核规则

pooled CSV 由 AB/BA 对相同 mode/part 的 static fields 做 equality check 后，
只对 timing fields 取均值；64 行完整、每行 20102 steps，AB/BA order spread
的 eval 最大值为 baseline 4.108%、closure-aware 3.459%。因此本轮可
用于 node030 内部的 per-part work/max/CV 诊断；不跨 node 混合 raw time，也
不把 diagnostic 数字写成 strict headline。

## 10. 决策

- closure-aware 继续保持实验开关，baseline 默认不变。
- 本轮不拆大 ASC；node030 结果只补充 runtime 量级和 per-part 证据。
- 下一步若要判断并行收益，应在同一 build/protocol 上测 N=8 或完整线程缩放；
  N=1 的 +47.367% Host time 不能外推为 N=32 结论。
- 形成 strict 性能结论前，需要真正安静的 whole-CCD 窗口，或具备等价的
  隔离资源；diagnostic 结果仅用于定位 max/work/locality trade-off。

## 11. 勘误：ELF page-cache NUMA 驻留未闭合（2026-09-04）

后续 [TNO0273](./TNO0273_xiangshan_repcut_n1_frontend_numa_page_root_cause_20260904.md)
在 node030 直接抓取运行中 `/proc/PID/numa_maps`，确认本篇比较的原始 ELF
存在严重非对称驻留：baseline text 约 98.95% 位于执行核所在 NUMA0，
closure-aware text 约 99.27% 位于远端 NUMA1。`--membind=0` 不会迁移已经
存在的 file-backed page-cache 页，原 runtime audit 也只检查
`Mems_allowed_list`，没有检查实际页驻留。

将两个逐字节相同的 ELF 分别复制到 NUMA0 本地 tmpfs 并确认 text 页均位于
NUMA0 后，单序 N=1/C=10000 diagnostic 变为：step-timing total `+4.068%`、
eval sum `+4.428%`、eval max `-33.810%`。因此本篇的 `+47.367%` Host、
`+56.329%` eval sum 与 `-0.671%` eval max 只能保留为“非对称页驻留下实际
观察到的原始值”，不得继续解释为 closure-aware 算法的固有 runtime 代价，
也不得据此判定该 weight 方法对并行加速无效。正式性能结论仍为 N/A，默认不变。
