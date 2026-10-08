# Rob 独立模块基准：gsim vs GrhSIM IR（六阶段/gsim-shape emit 路线重测）

| 字段 | 值 |
|---|---|
| 日期 | 2026-10-07 |
| 机器 | AMD Ryzen 9 7950X3D（32 逻辑核，187 GiB） |
| 工具链 | clang++ 22.1.2（`-O3`，无 PGO）、Verilator 5.051（ref emu）、gsim（`--supernode-max-size=15`） |
| wolvrix commit | `6bcf731`（gsim-shape emit：branchless publish、inlined helpers、C23 `_BitInt` 宽值） |
| 被测模块 | XiangShan `Rob`（含内嵌 `RenameBuffer rab`），独立顶层精确提取 |
| 激励 | 整机 Verilator ref emu 跑 `coremark-2-iteration.bin` + nemu difftest，cycle 0 起 100,050 周期完整 I/O trace（当日重新采集） |
| 设施与口径细节 | `testcase/xs-components/rob/README.md` |
| 存储模型结构对比 | `pdocs/rob_standalone/storage-model-gsim-vs-grhsim-20261007.md` |

## 1. 与旧记录的关系

2026-09-29 版记录（trace 口径 2.25×、随机口径 2.53×）基于旧 per-task eval 管线，已删除。
9-30 至 10-06 六阶段模拟模型重构在 wolvrix 全部落地（`9bacb94`→`6bcf731`：SimPhase/edgeDet IR 载体 →
沿/时隙 lowering → 命名存储 → final C-segment mapping → multi-TU emit → sink 感知六阶段调度 →
dataActiveFlag 位打包 → supernode 跨 TU 拆分 → boundary 克隆 C 段化 → P_mem 守卫位图 → gsim-shape emit）。
本次是**架构级对照**，不是单改动 delta。

## 2. 正确性

`rob_bench --trace --verify 100000` 三方比对（gsim vs GrhSIM、各自 vs 真实芯片 trace）**0 失配**。

排除项（均非功能输出，与旧例相同）：

- 2 个 `io_storeDebugInfo_*_pc`（越界动态索引读，FIRRTL 未定义行为）；
- 966 个 `io_diffCommits_info` 行 ≥353（gsim 模型对 RAB 前瞻窗第二次回绕处理与真实芯片不同；GrhSIM 与芯片逐位一致）。

端口配对较旧版收紧：配对 1,501 入 / 4,258 出；17 个 `*_bore` 观测口与 6 个被截断的宽输入口在配对/打包阶段即不纳入（verify 报告 `excluded_bore_ports=0`）。

两模型 bench checksum 均 = `0xd27a5e546e6474cc`，**与 2026-09-29 记录完全相同**——trace 轨迹跨路线逐位稳定。

## 3. 性能（每轮全新模型，3 轮取 min）

### 3.1 trace 全程 100,050 周期（真实激励，稳态为主）

| 模型 | min 耗时 | 吞吐 | 每周期 |
|---|---:|---:|---:|
| gsim | 8,703.3 ms | 11,496 c/s | 87.0 µs |
| GrhSIM IR | 27,699.2 ms | 3,612 c/s | 276.9 µs |

**差距：GrhSIM IR 比 gsim 慢 3.18×**（旧路线 2026-09-29 为 2.25×）。

### 3.2 随机满活动（100k 向量，对照）

| 模型 | min 耗时 | 吞吐 | 每周期 |
|---|---:|---:|---:|
| gsim | 10,951.9 ms | 9,131 vec/s | 109.5 µs |
| GrhSIM IR | 35,556.1 ms | 2,812 vec/s | 355.6 µs |

**差距 3.25×**（旧路线 2.53×）。每轮两模型 checksum 一致。

### 3.3 微观数据（perf stat，trace 全程；进程含 warmup+1 计时轮共 200,100 仿真周期）

| 指标（每仿真周期） | gsim | GrhSIM IR | 比值 |
|---|---:|---:|---:|
| 指令数 | 443k | 2,497k | 5.64× |
| IPC | 0.89 | 1.57 | — |
| 分支数 / 误码率 | 21.0k / 43.0% | 30.5k / 18.6% | 1.45× |
| L1 loads / miss | 263k / 4.2k | 1,471k / 54.9k | 5.6× / 13.2× |
| CPU 周期 | 499k | 1,590k | 3.19× |

### 3.4 与旧路线同口径对照（2026-09-29 → 2026-10-07）

| 口径 | gsim | GrhSIM IR | 比值 |
|---|---|---|---|
| trace 吞吐 | 11,252 → 11,496 c/s（+2.2%） | 4,993 → 3,612 c/s（**−27.7%**） | 2.25× → 3.18× |
| 随机吞吐 | 9,590 → 9,131（−4.8%） | 3,785 → 2,812（−25.7%） | 2.53× → 3.25× |
| 指令/周期 | 443k → 443k | 1,661k → 2,497k（+50%） | 3.75× → 5.64× |
| 分支/周期 | 21.0k → 21.0k | 120.2k → 30.5k（−75%，branchless 化生效） | — |
| L1 miss/周期 | 4.2k → 4.2k | 17.8k → 54.9k（3.1×） | — |

gsim 侧两次测量指令级一致（88.61G → 88.59G 条），激励与参照完全稳定；**差距扩大全部来自 GrhSIM 新路线自身**。

解读：

1. 指令口径 3.75× → 5.64× 是墙钟恶化的主因；CPU 周期比（3.19×）与墙钟比（3.18×）精确吻合。
2. IPC 对冲结构不变：gsim 误码率 43% 压 IPC 至 0.89，GrhSIM IPC 1.57，把 5.64× 指令差压缩成 3.2× 时间差。
3. branchless publish 等新形态使 GrhSIM 分支数降 75%，但 L1 miss 同周期 3.1×（54.9k/cyc）提示状态/store 布局的访存局部性变差，是指令外的新瓶颈线索，待定位。

## 4. 复现

```bash
# 模型与随机激励 bench
make -C testcase/xs-components -f rob.mk rob-extract
make -C testcase/xs-components -f rob.mk rob-grhsim-model   # 冷树必须先显式建 grhsim 模型（rob_bench 对 grhsim_Rob.hpp 无规则）
make -C testcase/xs-components -f rob.mk rob-bench ROB_BENCH_VECTORS=100000 ROB_BENCH_VERIFY=2048 ROB_BENCH_REPEAT=3

# 真实激励 trace（需 GSIM_BIN 指向 reference/gsim/build/gsim/gsim）
make -C testcase/xs-components -f rob.mk rob-trace-emu-build ROB_TRACE_JOBS=32
make -C testcase/xs-components -f rob.mk rob-trace-run ROB_TRACE_CYCLES=100000
make -C testcase/xs-components -f rob.mk rob-bench-trace ROB_BENCH_VERIFY=100000 ROB_BENCH_REPEAT=3

# perf 微观数据
perf stat -e cycles,instructions,branches,branch-misses,L1-dcache-loads,L1-dcache-load-misses \
  -o ptmp/xs-components-rob/trace/perf_grhsim_trace_20261007.txt -- \
  ptmp/xs-components-rob/bench/rob_bench --trace ptmp/xs-components-rob/trace/rob_trace.bin \
  --verify 0 --repeat 1 --model grhsim      # --model gsim 同理
```

## 5. 产物

`ptmp/xs-components-rob/` 下：

- `rerun_20261007.log`：本次全链日志（extract → 模型 → 随机 bench → trace emu → 采集 → trace bench）；
- `bench.log` / `bench_trace.log`：随机与 trace 口径 verify + bench 全轮输出；
- `trace/rob_trace.bin`（4.6 GB，100,050 周期，`pack.log`: `reset_cycles=52 first_reset=1 static_nonzero=0`）；
- `trace/perf_{gsim,grhsim}_trace_20261007.txt`：perf 原始计数。

## 6. 已知限制

- boot/steady 分段与双 eval 分相未重测：`probe_trace_phase.cpp` 源码原存于 `ptmp/`，随 ptmp 清理丢失，`rob-trace-phase-probe` 目标暂不可用（需要时按旧探针语义重写）。
- 位宽截断输入同旧例（`io_exuWriteback_{4,16,20}_bits_data`、`io_debugEnqLsq_needAlloc_*`、`io_commits_info_*_ftqOffset`），两模型同样截断且 GrhSIM 与芯片逐位一致。
- perf 计数器 83% 多路复用（缩放估计），比值口径不受影响。
