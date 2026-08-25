# XiangShan direct Verilator 2/4/8/16-thread scaling on node032 (50k-cycle serial runs)

日期：2026-08-21

## 1. 结论

本轮在 node032.bosccluster.com 上为同一份 XiangShan 单核 RTL 并行构建
EMU_THREADS=2、4、8、16 四个独立的直接 Verilator emu，编译使用 -j96，不做
NUMA/CPU 绑定；构建普通 -O3、关闭 PGO/BOLT，编译启用 FST trace 能力。四个
构建均 exit 0，且每个 ELF 的 EMU_THREAD、Verilator --threads 与目标线程数一致。

随后按 2、4、8、16 的顺序串行运行同一 CoreMark 2-iteration image，各次最多
50000 cycles，运行关闭波形。四次都在预期的 EXCEEDING CYCLE/INSTR LIMIT 状态
退出码 0；这是一组 50k-cycle 性能快照，不是完整 CoreMark 2-iteration PASS。

以 /usr/bin/time -v 的外部 walltime 计，矩阵内 t2 为 1.00x 基线：

| host emu threads | runtime walltime | emu Host time | 相对 t2 |
| ---: | ---: | ---: | ---: |
| 2  | 1:29.18 (89.18 s) | 89,127 ms | 1.00x |
| 4  | 0:47.93 (47.93 s) | 47,884 ms | 1.86x |
| 8  | 0:28.94 (28.94 s) | 28,899 ms | 3.08x |
| 16 | 0:22.46 (22.46 s) | 22,420 ms | 3.97x |

node032 当时存在其他用户/CI 仿真和较高 load average；没有建立正式 whole-CCD
quiet gate。因此以上数值保留为受外部负载污染的 raw snapshot，不作为严格的
跨版本性能排名。

## 2. 输入、构建隔离与身份

远程工作区：

~~~
/nfs/home/tanghaojin/wolvrix-SimpleTES-workspace-5/wolvrix-playground-gsim-calibrate-5
~~~

本轮使用的独立 build root：

~~~
build/xiangshan_verilator_single_core_t2_nopgo_wave_node032_20260821
build/xiangshan_verilator_single_core_t4_nopgo_wave_node032_20260821
build/xiangshan_verilator_single_core_t8_nopgo_wave_node032_20260821
build/xiangshan_verilator_single_core_t16_nopgo_wave_node032_20260821
~~~

未删除工作区已有构建；本轮 build root 独立，且共享的 build/xs/rtl 和
testcase/xiangshan/build/generated-src 只读复用。第一次并行启动因未先进入工作区而得到
make: No rule to make target
'xs_ref_emu'，四个失败日志（run id tno0244_parallel_20260821_225144）均保留，
不计入结果。修正为先 cd/source 后重新启动，成功 run id 为
tno0244_parallel_retry_20260821_225444。

固定输入身份：

| 项目 | 值 |
| --- | --- |
| parent commit | e088bdbbddecdc8998e82d4ac5410d977768d5ce |
| XiangShan commit | 4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6 |
| SimTop.sv SHA-256 | 15e4d8dc7ef00e729c6e4aef999bc901bd9381dbeb5432ca6b9e8c42f6ea5559 |
| CoreMark image SHA-256 | c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e |
| NEMU reference SHA-256 | 094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e |
| host | node032.bosccluster.com，384 logical CPU，2 NUMA node |

## 3. 并行编译命令

以下是实际采用的命令骨架。source env.sh 只在父 shell 执行一次，四个 make 在
独立子 shell 后台并行；命令中没有 taskset、numactl 或其他 NUMA 分组绑定：

~~~
ROOT=/nfs/home/tanghaojin/wolvrix-SimpleTES-workspace-5/wolvrix-playground-gsim-calibrate-5
cd "$ROOT"
source env.sh
unset LLVM_PROFILE_FILE PGO_WORKLOAD PGO_CFLAGS PGO_LDFLAGS MAKEFLAGS
RUN_ID=tno0244_parallel_retry_20260821_225444
RTL="$ROOT/build/xs/rtl"
GEN="$ROOT/testcase/xiangshan/build/generated-src"

for t in 2 4 8 16; do
  B="$ROOT/build/xiangshan_verilator_single_core_t"$t"_nopgo_wave_node032_20260821"
  LOG="$B/logs/xs/parallel_"$RUN_ID"_t"$t".log"
  mkdir -p "$B/logs/xs" "$B/ref"
  (
    /usr/bin/time -v -o "$B/ref/time_"$RUN_ID".log" \
      make -C "$ROOT" -j96 xs_ref_emu \
        RUN_ID="$RUN_ID"_t"$t" \
        BUILD_DIR="$B" \
        XS_RTL_BUILD="$RTL" \
        XS_REF_BUILD="$B/ref" \
        XS_DIFFTEST_GEN_DIR="$GEN" \
        XS_NUM_CORES=1 \
        XS_EMU_THREADS="$t" \
        XS_VM_BUILD_JOBS=96 \
        XS_WAVEFORM=1 XS_WAVEFORM_FULL=0 \
        XS_WITH_CHISELDB=0 XS_WITH_CONSTANTIN=0 \
        EMU_OPTIMIZE=-O3 OPT_FAST=-O3 \
        PGO_WORKLOAD= PGO_CFLAGS= PGO_LDFLAGS= \
        PGO_BOLT=0 LLVM_PROFILE_FILE= \
        >> "$LOG" 2>&1
    rc=$?
    echo "[BUILD_RESULT] thread=$t rc=$rc" >> "$LOG"
  ) &
done
wait
~~~

实际展开的 Verilator/C++ 关键选项为：

~~~
-DNUM_CORES=1
-DEMU_THREAD=2/4/8/16
--threads 2/4/8/16 --threads-dpi all
--exe -O3
-DENABLE_FST --trace-fst
make -s -j96 VM_PARALLEL_BUILDS=1 OPT_SLOW=-O0 OPT_FAST=-O3
PGO_CFLAGS= PGO_LDFLAGS=
~~~

四档构建结果和身份如下：

| threads | outer build wall | Verilator frontend | C++ compile/link | ELF bytes | SHA-256 前缀 |
| ---: | ---: | ---: | ---: | ---: | --- |
| 2  | 13:51.99 | 11:47.22 | 2:03.41 | 294,559,808 | 5c915408ac8e |
| 4  | 17:04.24 | 14:58.46 | 2:04.42 | 294,534,840 | 24f6820b8a79 |
| 8  | 23:30.65 | 21:43.10 | 1:46.22 | 294,728,472 | 6c6fe5ad8f18 |
| 16 | 27:04.93 | 25:10.70 | 1:52.91 | 294,845,632 | f949b1dbb9c3 |

四个 build root 的 profile artifact（profraw/profdata/fdata/perf.data 等）均为
0，build log 没有 Training、llvm-profdata、BOLT 或 perf record；因此本轮不含
PGO/BOLT。编译阶段没有生成 FST/VCD 文件，FST 仅表示 trace 支持代码已编入 ELF。

## 4. 串行 50k 运行命令

运行阶段明确设置 EMU_THREADS 与 XS_EMU_THREADS，并按线程数放宽到 N 个连续
CPU；这是运行绑定，不是编译绑定。所有四次使用 NUMA0、串行执行，避免相互争用：

~~~
ROOT=/nfs/home/tanghaojin/wolvrix-SimpleTES-workspace-5/wolvrix-playground-gsim-calibrate-5
BIN="$ROOT/testcase/xiangshan/ready-to-run/coremark-2-iteration.bin"
DIFF="$ROOT/testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so"
RUN_ID=tno0244_serial50k_node032_20260821_232300

for t in 2 4 8 16; do
  B="$ROOT/build/xiangshan_verilator_single_core_t"$t"_nopgo_wave_node032_20260821"
  LOG="$B/logs/runtime/coremark2_"$RUN_ID"_t"$t".log"
  TIMELOG="$B/logs/runtime/coremark2_"$RUN_ID"_t"$t".time.log"
  mkdir -p "$B/logs/runtime"
  cd "$B/ref/verilator-compile"
  /usr/bin/time -v -o "$TIMELOG" \
    env XS_NUM_CORES=1 XS_EMU_THREADS="$t" EMU_THREADS="$t" \
        XS_WAVEFORM=0 XS_WAVEFORM_FULL=0 \
        EMU_PROGRESS_EVERY_CYCLES=0 EMU_RUNTIME_PROFILE=0 \
    numactl --physcpubind=0-$((t-1)) --membind=0 \
    stdbuf -oL -eL ./emu \
      -i "$BIN" --diff "$DIFF" -b 0 -e 0 -C 50000 \
      2>&1 | tee "$LOG"
done
~~~

为可靠记录 emu 退出码，实际 supervisor 读取了 pipeline 的 PIPESTATUS[0]；
不能只看 tee 的退出码。运行没有传入 --dump-wave、--dump-wave-full 或 --wave-path。

## 5. 50k 结果明细

四次运行的 model counter 完全一致，均为 50000-cycle limit 截止：

| threads | CPU/NUMA 运行绑定 | instrCnt | cycleCnt | IPC | guest cycles | emu Host time | external wall | rc | FST/VCD |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2  | 0-1 / node0 | 73,580 | 49,996 | 1.471718 | 50,001 | 89,127 ms | 1:29.18 | 0 | 0 |
| 4  | 0-3 / node0 | 73,580 | 49,996 | 1.471718 | 50,001 | 47,884 ms | 0:47.93 | 0 | 0 |
| 8  | 0-7 / node0 | 73,580 | 49,996 | 1.471718 | 50,001 | 28,899 ms | 0:28.94 | 0 | 0 |
| 16 | 0-15 / node0 | 73,580 | 49,996 | 1.471718 | 50,001 | 22,420 ms | 0:22.46 | 0 | 0 |

每次日志均有唯一的 EXCEEDING CYCLE/INSTR LIMIT terminal，且无 BAD TRAP、
mismatch、assert/fatal、segmentation fault 或其他错误。该 terminal 是 emu 将
STATE_LIMIT_EXCEEDED 视作 good trap 后的正常上限退出；因此 rc=0，但不能写成
CoreMark 已完成。完整 2-iteration 结果仍应参见 TNO0242。

node032 在测量期间存在其他 emu/python/java 等任务；当前快照还观察到 load
average 约 19/40/69。本轮运行也没有设置 setarch/固定 ASLR 或执行正式 whole-CCD
admission gate。故这里不做 quiet-CCD、跨版本或正式 scaling gate 的结论，只报告本次
串行 50k walltime。

## 6. 持久证据

编译日志（成功 retry）：

~~~
build/xiangshan_verilator_single_core_t2_nopgo_wave_node032_20260821/logs/xs/parallel_tno0244_parallel_retry_20260821_225444_t2.log
build/xiangshan_verilator_single_core_t4_nopgo_wave_node032_20260821/logs/xs/parallel_tno0244_parallel_retry_20260821_225444_t4.log
build/xiangshan_verilator_single_core_t8_nopgo_wave_node032_20260821/logs/xs/parallel_tno0244_parallel_retry_20260821_225444_t8.log
build/xiangshan_verilator_single_core_t16_nopgo_wave_node032_20260821/logs/xs/parallel_tno0244_parallel_retry_20260821_225444_t16.log
~~~

第一次 cwd 错误的日志仍在同一四个 build root 的
logs/xs/parallel_tno0244_parallel_20260821_225144_tN.log；没有删除这些失败证据。
串行运行日志和 time log 分别位于各 build root 的 logs/runtime 下，文件名模式为：

~~~
coremark2_tno0244_serial50k_node032_20260821_232300_tN.log
coremark2_tno0244_serial50k_node032_20260821_232300_tN.time.log
~~~

相关前置记录：
- [TNO0242](./TNO0242_xiangshan_direct_verilator_single_core_single_thread_coremark2_walltime_20260821.md)：同类直接 Verilator 的单线程完整 CoreMark 2-iteration。
- [TNO0243](./TNO0243_xiangshan_node032_direct_verilator_50k_cycle_diagnostic_20260821.md)：node032 上单线程 50k-cycle 诊断。
