# XiangShan direct Verilator single-core/single-thread CoreMark 2-iteration walltime

日期：2026-08-21

## 1. 结论

本轮直接使用 Verilator 构建并运行 XiangShan emu，最终执行口径为 guest 单核、host
模型单线程：`XS_NUM_CORES=1`、`XS_EMU_THREADS=1`。构建使用普通 `-O3`，未开启
PGO/BOLT；C++ 编译并行度为 `-j96`。编译时启用 FST 能力，正式运行没有传入任何
dump-wave 参数，也没有生成 FST/VCD 文件。

CoreMark 2-iteration 完整运行退出码为 `0`，命中 `HIT GOOD TRAP`，emu 日志中唯一的
正数 headline 为：

```text
Host time spent: 738499ms
```

即本次仿真 walltime 为 **`738,499 ms`（`738.499 s`）**；外层
`/usr/bin/time -v` 记录为 `12:18.54`（`738.54 s`），两者相差 `41 ms`。

该样本的功能、单核、单线程、无 PGO 和运行不落波形证据均通过；启动命令固定了 CPU
affinity、NUMA first-touch 和 ASLR，运行中的 live audit 也与之相符。正式启动前
whole-CCD quiet gate 通过，但持续监控显示
运行期间同 CCD 出现外部负载：排除目标 CPU 后的 15 个 logical CPU 平均 idle 仅
`94.209%`，最低单 CPU 全程平均 idle 为 `82.210%`，未满足预设的
`mean>=98% / min>=95% / sibling>=98%`。因此 **`738,499 ms` 只作为 node029 的
单次 raw walltime snapshot，不作为严格 quiet 或跨版本性能基准**。

## 2. 实验边界与输入身份

本轮新建独立 Verilator build root，但没有删除、覆盖工作区已有构建。为避免无必要地
重新 elaboration，RTL 与 Difftest generated-src 复用已有、身份已冻结的单核输入；
本任务并未声称它们是本轮 freshly elaborated。`SimTop.sv` SHA 与
[TNO0233](./TNO0233_clean_rtl_gsim_plain_rebuild_and_correction_20260813.md) 记录的
clean RTL 相同。

| 项目 | 身份 |
| --- | --- |
| parent commit | `e088bdbbddecdc8998e82d4ac5410d977768d5ce` |
| XiangShan commit | `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`，worktree clean |
| host | `node029.bosccluster.com`，Linux `6.8.0-136-generic` |
| CPU | dual-socket AMD EPYC 9684X，`384` logical CPU，SMT2，2 NUMA nodes |
| frequency policy | governor `schedutil`，boost `1` |
| Verilator | `5.048 2026-04-26` |
| C/C++ compiler | Clang/Clang++ `21.1.5` |
| `SimTop.sv` | `1,587,569 bytes`，SHA-256 `15e4d8dc7ef00e729c6e4aef999bc901bd9381dbeb5432ca6b9e8c42f6ea5559` |
| `DifftestMacros.svh` | `CPU_XIANGSHAN`，interface width `79263`，SHA-256 `914e3168bd8de5a08e4ad1ba086e697ba61242d3ae2c49cb21b503c69a4b2faf` |
| `difftest_profile.json` | `cpu=XiangShan`、`numCores=1`，SHA-256 `1e58299e78ef6f5fb343397938b0ea3e2889c3ff039e701a4a7409d73bf94a46` |
| CoreMark image | `16,712 bytes`，SHA-256 `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e` |
| NEMU reference | `567,504 bytes`，SHA-256 `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e` |

CoreMark image 的用途和 2-iteration 口径见
[`ready-to-run/README.md`](../../testcase/xiangshan/ready-to-run/README.md)。walltime
headline 采用 [TNO0110](./TNO0110_walltime_headline_criterion_and_re_evaluation_20260717.md)
的规则：正式样本必须恰有一个正数 `Host time spent: Nms`；外层 time 只作交叉校验。

## 3. 单线程 plain Verilator 构建

最终 build root 为：

```text
build/xiangshan_verilator_single_core_single_thread_nopgo_wave_20260821
```

从 parent 根目录执行：

```bash
source env.sh
unset LLVM_PROFILE_FILE PGO_WORKLOAD PGO_CFLAGS PGO_LDFLAGS
make -j96 xs_ref_emu \
  RUN_ID=tno0242_t1_20260821_183400 \
  BUILD_DIR="$PWD/build/xiangshan_verilator_single_core_single_thread_nopgo_wave_20260821" \
  XS_RTL_BUILD="$PWD/build/xs/rtl" \
  XS_REF_BUILD="$PWD/build/xiangshan_verilator_single_core_single_thread_nopgo_wave_20260821/ref" \
  XS_DIFFTEST_GEN_DIR="$PWD/testcase/xiangshan/build/generated-src" \
  XS_NUM_CORES=1 XS_EMU_THREADS=1 XS_VM_BUILD_JOBS=96 \
  XS_WAVEFORM=1 XS_WAVEFORM_FULL=0 \
  XS_WITH_CHISELDB=0 XS_WITH_CONSTANTIN=0 \
  PGO_WORKLOAD= PGO_CFLAGS= PGO_LDFLAGS= PGO_BOLT=0 LLVM_PROFILE_FILE=
```

展开后的 Verilator/C++ build 证据为：

```text
-DNUM_CORES=1
-DEMU_THREAD=1
--threads 1 --threads-dpi all
--exe -O3
-DENABLE_FST --trace-fst
make -s -j 96 VM_PARALLEL_BUILDS=1 OPT_SLOW=-O0 OPT_FAST=-O3
PGO_CFLAGS= PGO_LDFLAGS=
```

其中 guest 核数和 host emu 模型线程数分别由 `NUM_CORES=1` 与 `EMU_THREAD=1` 固定；
不能把 guest 单核误解为允许多个 host 模型线程。生成目录包含 `911` 个 `.o` 和
`208` 个 `VSimTop*Trace*.cpp`，确认 FST trace 代码实际进入编译。

构建阶段 walltime 为：

| 阶段 | walltime | 说明 |
| --- | ---: | --- |
| Verilator frontend | `9:22.28`（`562.28 s`） | exit `0`，max RSS `29,334,748 KiB` |
| C++ compile/link | `1:32.13`（`92.13 s`） | exit `0`，平均 `6863%` CPU，`-j96` |
| 两阶段合计 | `10:54.41`（`654.41 s`） | 不含环境准备 |

最终 emu 位于：

```text
build/xiangshan_verilator_single_core_single_thread_nopgo_wave_20260821/ref/verilator-compile/emu
```

其大小为 `294,444,328 bytes`，SHA-256 为
`2bb9834bdf405507d4e14258e64767b706637665666876cf4e609b4e649d4922`；它是 x86-64
PIE、not stripped，未带 GNU Build ID。`ref/emu` symlink 解析到同一文件。

### 3.1 无 PGO/BOLT 审计

最终 build root 是本轮新建的独立 object 目录，没有从旧 build 目录直接拷贝或链接
`.o`。但 Verilator `verilated.mk` 默认 `OBJCACHE=ccache`，并导出
`CCACHE_SLOPPINESS=pch_defines,time_macros`；`common.o` 中保留的前一日编译日期也证明
本轮存在 compiler-cache hit。因此这里不宣称 `911` 个 object 全部绕过缓存 freshly
compiled；无 PGO 结论建立在实际编译键/最终 ELF 审计上，而不是仅依赖目录新鲜度：

- build 命令显式清空 `PGO_WORKLOAD`、`PGO_CFLAGS`、`PGO_LDFLAGS` 和
  `LLVM_PROFILE_FILE`，并固定 `PGO_BOLT=0`；
- 实际生成 make 命令的 `PGO_CFLAGS=`、`PGO_LDFLAGS=` 为空；ccache 会区分编译
  flags，因而普通 `-O3` cache hit 不等于直接复用带 `fprofile-*` 的 object；
- build log 中 `Building PGO profile`、`Training emu`、`fprofile-generate/use`、
  `llvm-profdata`、`llvm-bolt`、`perf2bolt`、`perf record` 命中数均为 `0`；
- build root 中 `profraw/profdata/fdata/perf.data/emu.pre-bolt/emu.instrumented` 文件数
  为 `0`；
- ELF 中 `llvm_prf/bolt` section 和对应 profile marker 命中数为 `0`。

所以该产物是普通 Verilator `-O3`，不是 PGO 或 BOLT 构建。

### 3.2 用户澄清后的构建保留

最初请求只明确“单核”时曾启动一个 `EMU_THREADS=2` 构建；用户随后明确要求
`EMU_THREADS=1`，该任务立即以 Ctrl-C 停止，未产生 emu ELF，也未进入性能运行。
遵循“不删除已有构建”的要求，约 `304 KiB` 的中止目录仍完整保留：

```text
build/xiangshan_verilator_single_core_nopgo_wave_20260821
```

其中只有 build/time 日志和空的 `verilator-compile` 目录。本文所有结果均来自另一个
带 `single_thread` 的最终目录；该中止目录不属于性能样本。

## 4. 运行设置

先用 `-C 10000` 做 launch/difftest canary。它按预期在 10k cycle limit 结束，退出码
为 `0`，未见功能负向签名；由于当时主机负载较高，canary 的 `47,984 ms` 不进入性能
结果。完整 2 iter 正式运行不带 `-C`，日志确认 `max cycles: unlimited`。

启动前动态选择 NUMA0 的 CCD，并通过 3 秒 quiet admission：

```text
CCD: node0:32-39,224-231
target CPU: 33
SMT sibling: 225
NUMA node: 0
pre-gate count/mean/min idle: 16 / 98.624% / 96.000%
pre-gate target/sibling idle: 99.670% / 100.000%
```

以上 admission 数值是启动时的 terminal live observation，未另存为独立日志；运行期
whole-CCD `mpstat` 原始数据则完整保存在本轮 build root。

emu、CoreMark image 和 NEMU 由 CPU33 使用 `cp --reflink=never` first-touch 到
NUMA0 的 fresh `/dev/shm` inode；staging 后三个 SHA-256 均与原文件一致。正式命令为：

```bash
/usr/bin/time -v \
  -o build/xiangshan_verilator_single_core_single_thread_nopgo_wave_20260821/logs/runtime/coremark2_full_external_time.log \
  taskset -c 33 \
  numactl --physcpubind=33 --membind=0 \
  setarch x86_64 -R \
  env XS_WAVEFORM=0 XS_WAVEFORM_FULL=0 \
      EMU_PROGRESS_EVERY_CYCLES=0 EMU_RUNTIME_PROFILE=0 \
  stdbuf -oL -eL \
  /dev/shm/tno0242_xs_verilator_t1_20260821_184500/emu \
    -i /dev/shm/tno0242_xs_verilator_t1_20260821_184500/coremark-2-iteration.bin \
    --diff /dev/shm/tno0242_xs_verilator_t1_20260821_184500/riscv64-nemu-interpreter-so \
    -b 0 -e 0
```

命令没有 `--dump-wave`、`--dump-wave-full`、`--wave-path` 或任何等价的波形输出参数。
运行中的 terminal live `/proc` 审计看到 emu `Tasks=1`、`Cpus_allowed_list=33`、当前
`PSR=33`；emu 映射页为 `N0=30885/N1=0`，NEMU 映射页为 `N0=115/N1=0`。独立
ASLR probe 为 `00040000`，与 `setarch x86_64 -R` 一致。这些 `/proc`/probe 值未另存
为独立文件；持久的 external-time log 保留了完整的 `taskset`、`numactl` 和 `setarch`
启动命令。

## 5. CoreMark 2-iteration 结果

| 项目 | 结果 |
| --- | ---: |
| process exit | `0` |
| emu headline（唯一正数） | **`738499 ms`** |
| `/usr/bin/time` elapsed | `12:18.54`（`738.54 s`） |
| `/usr/bin/time` CPU | `99%`；user `738.36 s`，system `0.06 s` |
| max RSS | `150,528 KiB` |
| voluntary / involuntary context switches | `308 / 3078` |
| CoreMark iterations | `2` |
| CoreMark guest throughput | `834 iterations/s` |
| guest instructions / cycles | `663682 / 296749` |
| guest IPC | `2.236510` |
| reported guest cycle spent | `296754` |
| terminal signature | `HIT GOOD TRAP at pc = 0x80001ca0` |

CoreMark 输出还给出 `CoreMark Size=666`、`Total time (ms)=2396`、
`Finished in 2396 ms`，以及 CRC：`seedcrc=0xe9f5`、`crclist=0xe714`、
`crcmatrix=0x1fd7`、`crcstate=0x8e3a`、`crcfinal=0x72be`。这里的 `2396 ms` 是
guest benchmark timer，**不是 host 仿真 walltime**。

日志恰有一个 `Host time spent`；`Errors detected`、`ERROR!`、`HIT BAD TRAP`、
`ABORT`、`mismatch`、assert/fatal、segmentation fault 和终止性 cycle-limit 命中数均为
`0`。因此功能结果为 PASS。

### 5.1 运行时波形审计

编译含 FST 能力不代表运行一定落波形。本次 canary 和完整运行均未传 dump-wave 参数；
正式 run log 与 external-time log 中波形参数/path 命中为 `0`。完成两次运行后：

```text
workspace build root FST/VCD count: 0
/dev/shm staging root FST/VCD count: 0
```

所以本次 walltime 没有波形文件写出开销。

### 5.2 运行期 quiet gate 失败与解释边界

入场采样通过后，完整运行期间由 helper CPU 监控整个 16-logical-CPU CCD。目标 CPU33
为 emu 独占且全程接近 100% busy；排除它后，其余 15 个 logical CPU 的全程平均 idle
为 `94.209%`。逐 CPU 全程平均 idle 中，最低为 CPU32 的 `82.210%`；SMT sibling
CPU225 为 `97.770%`。三项均未完全达到正式阈值：

| 连续负载 gate | 阈值 | 实测 | 状态 |
| --- | ---: | ---: | --- |
| other-15 mean idle | `>=98%` | `94.209%` | FAIL |
| other-15 minimum per-CPU mean idle | `>=95%` | `82.210%` | FAIL |
| SMT sibling idle | `>=98%` | `97.770%` | FAIL |

因此本轮完成了用户要求的单线程仿真和 walltime 测量，但性能数字的证据等级限定为单次
raw snapshot。若要把它升级为可比较基准，应在持续 quiet 的 CCD 上复跑，并至少保留
多样本 order-balanced 测量；不能用本次受污染的单点推导版本间百分比或稳定吞吐。

## 6. 证据文件

工作区内的持久证据均保留，未清理已有或本轮构建：

```text
build/xiangshan_verilator_single_core_single_thread_nopgo_wave_20260821/logs/xs/xs_ref_build_tno0242_t1_20260821_183400.log
build/xiangshan_verilator_single_core_single_thread_nopgo_wave_20260821/ref/time.log
build/xiangshan_verilator_single_core_single_thread_nopgo_wave_20260821/logs/runtime/coremark2_canary_c10000.log
build/xiangshan_verilator_single_core_single_thread_nopgo_wave_20260821/logs/runtime/coremark2_full.log
build/xiangshan_verilator_single_core_single_thread_nopgo_wave_20260821/logs/runtime/coremark2_full_external_time.log
build/xiangshan_verilator_single_core_single_thread_nopgo_wave_20260821/logs/runtime/coremark2_full_ccd_monitor.log
build/xiangshan_verilator_single_core_single_thread_nopgo_wave_20260821/logs/runtime/coremark2_full_staged_sha256.log
```

本轮没有修改 XiangShan、Wolvrix、Verilator 或仿真默认配置；增量落盘内容仅为本文和
`README.md` 索引。此前工作区已有的 dirty/untracked 文档与 `wolvrix` submodule 状态
均保持不动。第 4 节已明确标出的 admission 和 live `/proc` 数值没有独立原始日志，
不得把它们误写成可离线复查的持久 gate artifact。
