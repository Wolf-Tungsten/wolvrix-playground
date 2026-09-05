# TNO0273: XiangShan RepCut N=1 frontend NUMA page root cause

日期：2026-09-04

状态：`ROOT CAUSE CONFIRMED; TNO0272 PERFORMANCE INTERPRETATION INVALIDATED; FORMAL RETEST PENDING`。

## 1. 结论

[TNO0272](./TNO0272_xiangshan_repcut_closure_weight_n1_node030_ccd80_runtime_diagnostic_20260904.md)
中“host instructions 只增加约 5.45%，但 Host/cycles 增加约 47%”的主要原因已定位：
两侧原始 executable page-cache 的 NUMA 驻留不对称，而不是 candidate 固有地需要
约 47% 更多执行时间。

node030 的运行中 `numa_maps` 实测为：

| 原始 ELF | text pages N0 | text pages N1 | 相对执行核 |
| --- | ---: | ---: | --- |
| baseline | 60,380 | 640 | 约 98.95% 本地 |
| closure-aware | 460 | 62,701 | 约 99.27% 远端 |

目标 CPU24 位于 NUMA0。将两个 ELF 在 CPU24/NUMA0 上逐字节复制到独占 tmpfs，
并确认 baseline/candidate text 分别为 `N0=61,020`、`N0=63,145` 后，结果从：

| 口径 | baseline | closure-aware | 变化 |
| --- | ---: | ---: | ---: |
| 原始页 timing total (ms) | 58,931.002 | 90,332.499 | +53.285% |
| 原始页 cycles | 218.091 B | 329.763 B | +51.204% |
| 本地页 timing total (ms) | 59,962.794 | 62,402.302 | **+4.068%** |
| 本地页 cycles | 220.301 B | 229.017 B | **+3.956%** |

同时 frontend latency 从原始页的 `51.4% -> 65.7%` 恢复为本地页的
`51.9% -> 51.5%`。这形成因果对照：原约 47% 的异常回退主要来自远端
instruction-page service latency；本地页后剩余约 4% 与 final ops `+4.480%`、
独立样本 instructions `+5.447%` 同量级。

更重要的是，本地页 N=1 per-part timing 显示 closure-aware 的真实 trade-off 为：

- eval sum `2495.852 -> 2606.368 us/step`，`+4.428%`；
- eval max `518.875(part_3) -> 343.444(part_8) us/step`，`-33.810%`；
- total max `576.434 -> 369.853 us/step`，`-35.838%`；
- eval CV `1.06466 -> 0.62727`，降低 `41.083%`。

因此不能再把 closure-aware 判为“对并行加速无效”。当前证据反而重新证明了
“以约 4.4% 串行 eval 总量为代价，将最大 partition 降低约 33.8%”的明确
并行负载 trade-off。它仍是单序、非 strict diagnostic，是否改善 N>1 walltime
必须在页驻留闭合后重新测试。

## 2. 为什么 instructions 少增而 walltime 大增

`instructions` 只统计退休指令；CPU 等待下一段指令代码到达期间，cycles 和 walltime
继续累计，但不会退休新指令。原始 node030 pooled 结果为：

| 指标 | baseline | closure-aware | 变化 |
| --- | ---: | ---: | ---: |
| instructions | 270.367 B | 285.098 B | +5.449% |
| cycles | 215.692 B | 317.782 B | +47.331% |
| CPI | 0.79777 | 1.11464 | +39.719% |
| GHz | 3.64025 | 3.64171 | +0.040% |

按 baseline CPI 做反事实分解，新增 instructions 只能解释约 11.5% 的 extra cycles，
其余约 88.5% 来自每条退休指令的平均等待增加。新增 PMU 进一步定位到 frontend：

| Pipeline 指标 | baseline | closure-aware | 变化方向 |
| --- | ---: | ---: | --- |
| frontend bound | 64.3% | 75.0% | +10.7 pp |
| frontend latency | 51.4% | 65.7% | +14.3 pp |
| frontend bandwidth | 12.9% | 9.3% | 降低 |
| backend bound | 9.3% | 6.6% | 降低 |

所以不是降频、失去 CPU、outer update 或 data-memory backend stall 主导，而是 host
取指前端出现长时间断供。单独的 fetch/TLB pass 还观察到：

- L1 I-cache miss 总数 `+15.209%`，按 instruction 归一后 `+9.257%`；
- L2 instruction fill miss 总数 `+5.019%`，按 instruction 归一后 `-0.406%`；
- L2 iTLB miss/page walk 总数约 `+4.70%`，按 instruction 归一后下降。

因此 miss 次数或 iTLB miss rate 本身不是 40% 级 CPI 增量的解释。真正变化的是同类
instruction miss 的服务位置与延迟：candidate 的绝大多数 executable 页在远端 NUMA1，
而执行核在 NUMA0。两个 ELF 的 `.text` 分别约 241.227/249.718 MiB，均远大于该 CCD
的 96 MiB L3，远端页服务延迟会在反复执行大代码工作集时被持续暴露。

## 3. 时间落点

TNO0272 pooled Host 增量为约 28.024 s。phase timing 中：

- `part_eval` 增加约 27.729 s，占 98.961%；
- `global_update` 只增加约 0.290 s，占 1.036%；
- `input_load` 增量约 0.001 s。

本地页之后，`part_eval` 只从 `2501.952` 增到 `2612.804 us/step`，增加
`4.430%`；`global_update` 从 `476.328` 增到 `486.552 us/step`，增加
`2.147%`。这说明 static communication KM1 `+56.822%` 不能直接解释成 outer
communication time；原异常明确发生在各 partition model 的 `eval()` 取指路径。

## 4. 页驻留问题如何进入实验

runner 的顺序存在以下缺口：

1. `run_n1_pair.py:323` 在 runner 尚未固定 affinity 时通过 build manifest 对两个数百 MiB
   ELF 做第一次完整 SHA；
2. `run_n1_pair.py:345` 才将 runner 固定到 monitor CPU191，CPU191 位于 NUMA1；
3. `run_n1_pair.py:359` 再次读取两份完整 ELF 构造 header；
4. 每次 launch 前后又在 `run_n1_pair.py:159/194` 完整读取对应 ELF；
5. model 虽以 `--physcpubind=24 --membind=0` 启动，但 Linux 不会因该 mempolicy
   自动迁移已经存在的 file-backed page-cache 页；
6. `run_matrix_v6.py:526-543` 只读取 `/proc/PID/status` 的 `Mems_allowed_list`，该字段
   是允许集合，不是实际 page residency。

原始页最初由 build、首次 SHA 或其他读取中的哪一次分配，现有记录不能追溯，故不把
“runner 在 CPU191 上 hash”单独写成已证 first-touch 原因。已经证实的是：协议没有控制或
验证 executable 页驻留，且后续 hash/AB/BA 反序不会自动消除已存在的不对称 page cache。
这也解释了为什么 TNO0272 的 AB 与 BA 都稳定复现同一回退。

## 5. 本地页对照方法与身份

在 node030 上选择 CPU24/NUMA0，建立独占目录：

```text
/dev/shm/thj_repcut_frontend_20260904_1340
```

两臂分别使用如下等价命令复制；`MODE` 与源/目标文件名按 arm 替换：

```bash
taskset --cpu-list 24 \
  /nfs/home/tanghaojin/bin/numactl --physcpubind=24 --membind=0 \
  cp --reflink=never --preserve=mode SOURCE /dev/shm/thj_repcut_frontend_20260904_1340/MODE-emu
```

copy 后 SHA 与源 ELF 逐字节相同：

| arm | size | SHA-256 |
| --- | ---: | --- |
| baseline | 261,042,608 B | `355a2c7df9faec3e8f56591b53e5e214f7b0a3bf8453549bd3dc4cf55afadd77` |
| closure-aware | 269,966,456 B | `b5803a654b2f63057f71337ae02137089e8d28177c2b0e41918fefdc6c778b55` |

运行固定 CPU24/NUMA0、`setarch x86_64 -R`、`XS_EMU_THREADS=1`、C=10000，
并以 100% scheduled 的 AMD Pipeline 指标计数。运行中的 `numa_maps` 为：

| arm/path | text mapping |
| --- | --- |
| original baseline | `mapped=61020 N0=60380 N1=640` |
| original closure-aware | `mapped=63161 N0=460 N1=62701` |
| tmpfs baseline | `dirty=61020 N0=61020` |
| tmpfs closure-aware | `dirty=63145 N0=63145` |

local 两臂的 `numastat -p` 还分别给出总进程内存 N0/N1 为
`266.27/3.04 MiB` 与 `274.73/3.04 MiB`；剩余约 3 MiB 的 N1 映射不是两臂 ELF text。

## 6. 本地页 per-part 结果

| 指标 | baseline | closure-aware | 变化 |
| --- | ---: | ---: | ---: |
| eval sum (us/step) | 2495.852 | 2606.368 | +4.428% |
| eval max (us/step) | 518.875 | 343.444 | -33.810% |
| eval median (us/step) | 62.557 | 70.340 | +12.441% |
| eval population CV | 1.06466 | 0.62727 | -41.083% |
| attributed total sum (us/step) | 2969.586 | 3090.865 | +4.084% |
| attributed total max (us/step) | 576.434 | 369.853 | -35.838% |

各自去掉 giant 后，eval sum 为 `1976.977 -> 2262.924 us/step`，增加
`14.464%`。giant 单项每 step 减少 `175.431 us`，其余 31 项合计增加
`285.947 us`，净 eval 增加 `110.516 us/step`。这仍说明 closure-aware 有真实的
复制/布局代价，但量级是约 4.4% 的总量 trade-off，不是 TNO0272 中被远端页放大的 56%。

## 7. 静态与 runtime 对应

两臂 runtime wrapper、N=1 dispatch 顺序和 toolchain 相同。静态变化为：

| 指标 | 变化 |
| --- | ---: |
| exact closure sum | +3.012% |
| pre-rebuild ops sum | +4.047% |
| final graph ops sum | +4.480% |
| compiled active ico+nba text | +5.93% |
| ELF text | +3.52% |
| root state size sum | +0.603% |
| compute KM1 | +60.414% |
| communication proxy KM1 | +56.822% |

本地页的 total/eval/cycles `+3.96%..+4.43%` 与静态总工作量增幅相符。
KM1 仍说明重分区大幅改变 code/state grouping，并使模型更容易暴露 locality 问题，
但它不是原始 47% wall 增量的直接运行时间换算。

## 8. 证据边界与决策

本篇新增 PMU/local-page 对照是 node030 CPU24 上的单序 diagnostic：

- 每臂 timing 均有 20102 steps，perf events 均 100% scheduled，进程 rc=0；
- tmpfs/source ELF size、mode 与 SHA 闭合；
- 已现场读取两侧 original/local 运行中的 `numa_maps`；
- 但没有 `accepted.json`、continuous foreign-load audit 或完整 stdout endpoint 归档；
- 三种 PMU event pass 的绝对 counts 不能跨 pass 当作同一时刻样本相除。

因此它足以否定 TNO0272 的性能归因并确认 NUMA page root cause，但仍不是新的 formal
性能 headline。当前决策为：

1. baseline 默认不变，closure-aware 保持实验模式；
2. 撤销“closure-aware 对并行速度无用”的判断，重新开放 page-local N>1 runtime gate；
3. runner 在下一次正式测试前必须 stage 两侧独占 local tmpfs inode、校验 copy SHA，
   并记录/门禁 executable `numa_maps` local ratio；
4. 先做 page-local N=1 AB/BA 复现，再测 N=8 与 N=32；不能复用 TNO0272 的原始页
   per-part 数据做 worker makespan 预测；
5. giant ASC 拆分仍是后续独立议题，不与本次实验协议修正混合。

## 9. Artifact

PMU 与 timing：

```text
build/repcut_closure_runtime_20260902/runs/node030_ccd24_frontend_pmu_20260904/
  baseline_fetch.perf.csv
  candidate_fetch.perf.csv
  baseline_itlb.perf.csv
  candidate_itlb.perf.csv
  baseline_pipeline.perf.csv
  candidate_pipeline.perf.csv
  baseline_local_pipeline.perf.csv
  candidate_local_pipeline.perf.csv
  baseline_original_branch.perf.csv
  *.timing.jsonl
```

本地 ELF 临时路径：

```text
/dev/shm/thj_repcut_frontend_20260904_1340/
```

该 tmpfs 路径是 node030 临时诊断产物，不是持久 build identity；持久身份仍以
[TNO0268](./TNO0268_xiangshan_repcut_closure_weight_runtime_build_and_function_gate_20260902.md)
的 clean-v4 manifest 与本篇 copy SHA 为准。
