# XiangShan node032 direct Verilator 50k-cycle diagnostic run

日期：2026-08-21

## 1. 结论

本轮通过 SSH 在 `node032.bosccluster.com` 上运行 [TNO0242](./TNO0242_xiangshan_direct_verilator_single_core_single_thread_coremark2_walltime_20260821.md)
已经构建好的 Verilator emu，没有重新编译，也没有删除或覆盖已有构建。运行口径保持
guest 单核、host emu 单线程：`XS_NUM_CORES=1`、`XS_EMU_THREADS=1`；运行关闭波形，
并显式设置 `-C 50000`。

仿真在 `cycles=50000` 到达上限后按预期停止：

```text
Core 0: EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80001312
Core-0 instrCnt = 73580, cycleCnt = 49996, IPC = 1.471718
Seed=0 Guest cycle spent: 50001
Host time spent: 181090ms
```

外层 `/usr/bin/time -v` 的 walltime 为 `3:01.24`（`181.24 s`），user/system 为
`180.80/0.10 s`，CPU 使用率 `99%`。emu 进程退出码记录为 `0`；此处的
`EXCEEDING CYCLE/INSTR LIMIT` 是主动的 50k cycle 截止状态，不是异常崩溃。

这不是完整 CoreMark 2-iteration 功能结果：运行尚未到达 `HIT GOOD TRAP`，也没有最终
`Iterations/Sec` 或完整 CRC 输出。因此 `181090 ms` 只作为 node032 的 50k-cycle
诊断快照，不能与 TNO0242 的完整 2-iter walltime 直接比较。

## 2. 运行边界与命令

远程工作区为：

```text
/nfs/home/tanghaojin/wolvrix-SimpleTES-workspace-5/wolvrix-playground-gsim-calibrate-5
```

实际通过 SSH 执行的核心命令如下；CPU0/SMT sibling192 及 NUMA0 是本轮 node032 上的
绑定位置：

```bash
ssh node032 'bash -s' <<'REMOTE'
ROOT=/nfs/home/tanghaojin/wolvrix-SimpleTES-workspace-5/wolvrix-playground-gsim-calibrate-5
BUILD=$ROOT/build/xiangshan_verilator_single_core_single_thread_nopgo_wave_20260821
EMU=$BUILD/ref/verilator-compile/emu
INPUT=$ROOT/testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
DIFF=$ROOT/testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so

/usr/bin/time -v \
  -o "$BUILD/logs/runtime/coremark2_<run-id>.time.log" \
  taskset -c 0 \
  numactl --physcpubind=0 --membind=0 \
  setarch x86_64 -R \
  env XS_NUM_CORES=1 XS_EMU_THREADS=1 \
      XS_WAVEFORM=0 XS_WAVEFORM_FULL=0 \
      EMU_PROGRESS_EVERY_CYCLES=0 EMU_RUNTIME_PROFILE=0 \
  stdbuf -oL -eL \
  "$EMU" -i "$INPUT" --diff "$DIFF" -b 0 -e 0 -C 50000
REMOTE
```

本轮实际 run id 为 `tno0242_node032_50k_20260821_222710`。为了保留完整 stdout/stderr，
实际命令外层还使用 `tee` 写入 run log，并显式记录了 `emu_exit=0`。没有传入
`--dump-wave`、`--dump-wave-full`、`--wave-path` 等波形参数。

## 3. 结果明细

| 项目 | 结果 |
| --- | ---: |
| host | `node032.bosccluster.com` |
| target / sibling / NUMA | `CPU0 / CPU192 / node0` |
| guest cores | `1` |
| emu threads | `1` |
| maximum cycles | `50000` |
| observed cycle report | `50000` |
| model `cycleCnt` / `instrCnt` | `49996 / 73580` |
| guest cycle spent | `50001` |
| terminal state | `EXCEEDING CYCLE/INSTR LIMIT` |
| terminal PC | `0x80001312` |
| IPC | `1.471718` |
| emu headline | `181090 ms` |
| external elapsed | `3:01.24`（`181.24 s`） |
| process exit status | `0` |
| FST/VCD files in build root | `0` |

日志中的初始化信息还确认 emu 编译 commit 为 `4a6e3da8bf`、`dirty: 0`，并且使用了
CoreMark 2-iteration image 和 NEMU difftest reference。`Running CoreMark for 2 iterations`
刚开始后即被 50k 上限截断，故不能据此宣称 CoreMark 完成。

## 4. 产物与身份

本轮直接复用 TNO0242 的 ELF 和 ready-to-run 输入：

| 产物 | 大小 | SHA-256 |
| --- | ---: | --- |
| Verilator emu | `294,444,328 bytes` | `2bb9834bdf405507d4e14258e64767b706637665666876cf4e609b4e649d4922` |
| CoreMark image | `16,712 bytes` | `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e` |
| NEMU reference | `567,504 bytes` | `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e` |

emu 文件编译时间为 `Aug 20 2026, 17:03:34`。node032 内核为
`6.8.0-137-generic`；parent commit 为
`e088bdbbddecdc8998e82d4ac5410d977768d5ce`，XiangShan commit 为
`4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`。

CPU0/192 是启动前短时 idle 抽样选出的空闲 SMT pair，但本轮没有建立持续 whole-CCD
quiet gate，也没有采集多样本 A/B/A。因此本记录不提供 node032 的正式性能排名或跨版本
speedup 结论；它只确认该 emu 能在 node032 上按单线程配置跑到 50k cycles。

## 5. 持久证据

```text
build/xiangshan_verilator_single_core_single_thread_nopgo_wave_20260821/logs/runtime/coremark2_tno0242_node032_50k_20260821_222710.log
build/xiangshan_verilator_single_core_single_thread_nopgo_wave_20260821/logs/runtime/coremark2_tno0242_node032_50k_20260821_222710.time.log
```

run log 中包含完整启动参数、每 10k 的 cycle report、50k limit terminal、model counters、
headline walltime 和退出状态；time log 保留外层 walltime、CPU、RSS、context switch 与
退出状态。完成运行后 build root 内 FST/VCD 文件数仍为 `0`。
