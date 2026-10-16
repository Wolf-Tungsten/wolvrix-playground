# maskedOr：XiangShan CoreMark 100k 整机性能对照

2026-10-16。测试扩展后的 `cpu.st.recover-masked-or` 和 CPU emitter。
匹配实现与静态覆盖见 [匹配扩展报告](20261016-cpu-masked-or-matching.md)。

三对交替运行的平均 Host time 为 **350.391 → 340.013 秒**，耗时下降
**2.962%**，加速比 **1.0305×**。六次 difftest 均通过，执行端点一致。

## 测试口径

- 输入为相同的 `coremark-2-iteration.bin`，运行到 `-C 100000`。
  这是完整香山设计的 100k 周期仿真窗口，在周期上限截断 CoreMark 执行。
- 同一份 5,035,938-op checkpoint：
  `build/xs/grhsim-ir-aggr-global-enhanced/xiangshan_grhsim_ir.json`。
- baseline 对该 checkpoint 运行 `reemit_grhsim_ir GRHSIM_REEMIT_REMAP=1`。
  candidate 使用 `ptmp/masked-or-xs-expanded-final`，恢复 `min_terms=16` 的
  4,217 个区域后做相同 C1–C8 映射。没有使用首版只恢复 220 个区域的模型。
- 同一 Clang 22、模型编译参数
  `-std=c++20 -O3 -fno-strict-aliasing -DWOLVRIX_GRHSIM_PERF=0`；
  `mem_write_activate=on-write`、memory enable bitmap 开启。
- Ryzen 9 7950X3D，固定 CPU 2；单核设计、单 emu 线程，seed=0。
  开启 NEMU difftest；关闭 waveform、commit/RAM trace、runtime profile 和 phase timing。
- 所有构建结束后按 baseline/candidate 交替运行 3 对；每次运行前对该 emu
  执行 `POSIX_FADV_DONTNEED`，使用仓库已有 `benchmark_grhsim_ir` 流程。
  主指标为 emu 报告的 Host time，另保存 `/usr/bin/time` wall time。
- 两个 emu 的 SHA256、输入 SHA256、运行顺序、参数在
  [preregister.json](../../ptmp/masked-or-coremark100k/runs/preregister.json)。
  `baseline_seconds=600` 只用于设置每次运行的 900 秒 watchdog，不作为测量结果。
- 本次复用 checkpoint，不测量从 SV 开始的完整模型生成时间。

## 映射与代码规模

| 指标 | baseline | maskedOr |
| --- | ---: | ---: |
| 恢复区域 / 规约项 | 0 / 0 | 4,217 / 162,574 |
| Event ops | 19,934 | 16,510 |
| General nodes（C1） | 1,294,467 | 1,245,707 |
| Boundary fields | 1,164,602 | 1,102,987 |
| Phase tasks | 4,438 | 4,195 |
| C++ translation units | 1,273 | 1,208 |
| ELF text（bytes，`size`） | 335,865,721 | 327,595,992 |
| Mem writes / mem fields | 141,847 / 2,653 | 141,847 / 2,653 |

baseline 经同样重映射，规模与旧的已编译模型不必完全相同。上表不能代替运行计时。

## 运行结果

| 交替轮次 | baseline Host（s） | maskedOr Host（s） | 耗时下降 |
| --- | ---: | ---: | ---: |
| 1 | 350.688 | 337.859 | 3.658% |
| 2 | 347.902 | 342.660 | 1.507% |
| 3 | 352.583 | 339.520 | 3.705% |
| 平均 | **350.391** | **340.013** | **2.962%** |
| 样本标准差 | 2.355 | 2.438 | |

每 100k 周期平均减少 **10.378 秒**。对应仿真吞吐为 **285.40 → 294.11
cycles/s**，提升 **3.052%**。`/usr/bin/time` wall 平均为
350.437 → 340.047 秒，与 Host time 结论一致。ELF text 减少 **2.462%**。

三次 candidate 的最大值 342.660 秒仍小于 baseline 最小值 347.902 秒，
通过预先设定的 `max(new) < min(old)` gate。脚本给出的单侧精确置换
p=0.05。样本量为每组 3 次，结论限于本机、该输入、seed 和 100k 周期窗口。

六次均正常退出（Make 和 emu exit=0）、difftest 无错误，全部满足相同端点：
`instrCnt=225471 / cycleCnt=99996 / guestCycles=100001 / pc=0x800010e2`；
IPC 均为 2.254800。每次都成功执行 binary page-cache eviction。

因此本轮测得约 **3% 的整机收益**。这是恢复 op、专用发射及其 CPU
重映射/调度变化的整体效果；本次未采集 profile，不能进一步分摊各部分的贡献。
100k 窗口没有执行到 CoreMark 两次迭代的完成 trap。

原始数据：
[results.json](../../ptmp/masked-or-coremark100k/runs/results.json)、
[summary.json](../../ptmp/masked-or-coremark100k/runs/summary.json)、
[benchmark.log](../../ptmp/masked-or-coremark100k/benchmark.log)。

## 复现与产物

先 source `env.sh`，本机 Python 使用 `.venv/bin/python`。所有命令经项目 Make target。

```sh
mkdir -p ptmp/cpu_emit_test_tmp ptmp/cpu_emit_ccache ptmp/pip-cache
export TMPDIR="$PWD/ptmp/cpu_emit_test_tmp"
export CCACHE_DIR="$PWD/ptmp/cpu_emit_ccache"
export PIP_CACHE_DIR="$PWD/ptmp/pip-cache"

make reemit_grhsim_ir PYTHON=.venv/bin/python \
  GRHSIM_REEMIT_MODEL=build/xs/grhsim-ir-aggr-global-enhanced/xiangshan_grhsim_ir.json \
  GRHSIM_REEMIT_FLOW=ptmp/masked-or-coremark100k-baseline GRHSIM_REEMIT_REMAP=1

make -j16 xs_wolf_grhsim_ir_build_emu \
  XS_GRHSIM_IR_BUILD=ptmp/masked-or-coremark100k-baseline \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/masked-or-coremark100k-baseline/model \
  XS_VM_BUILD_JOBS=16 XS_EMU_THREADS=1 WOLVRIX_GRHSIM_PERF=0

make -j16 xs_wolf_grhsim_ir_build_emu \
  XS_GRHSIM_IR_BUILD=ptmp/masked-or-xs-expanded-final \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/masked-or-xs-expanded-final/model \
  XS_VM_BUILD_JOBS=16 XS_EMU_THREADS=1 WOLVRIX_GRHSIM_PERF=0

make benchmark_grhsim_ir PYTHON=.venv/bin/python \
  GRHSIM_IR_BENCH_OLD=ptmp/masked-or-coremark100k-baseline \
  GRHSIM_IR_BENCH_NEW=ptmp/masked-or-xs-expanded-final \
  GRHSIM_IR_BENCH_OUTPUT=ptmp/masked-or-coremark100k/runs \
  GRHSIM_IR_BENCH_CPU=2 GRHSIM_IR_BENCH_PAIRS=3 \
  GRHSIM_IR_BENCH_BASELINE_SECONDS=600 \
  GRHSIM_IR_BENCH_EXPECTED_ENDPOINT=225471,99996,100001,0x800010e2
```

以上记录本次使用的目录。重新生成 baseline 时选择新的 flow 目录；
重新计时时 `GRHSIM_IR_BENCH_OUTPUT` 必须为尚不存在的目录。
candidate 的恢复命令见匹配扩展报告。

构建、重映射日志与 time 文件、输入 hash、ELF size 均在
[`ptmp/masked-or-coremark100k/`](../../ptmp/masked-or-coremark100k/)。
六次运行各自的命令、完整 stdout/stderr、退出码、端点与计时在 `runs/` 下；
最终汇总为 `runs/results.json` 和 `runs/summary.json`。
