# Current-machine GSIM / GrhSIM CoreMark 50k comparison

日期：2026-07-10

## 目的

在同一台机器上重新构建当前 GSIM 与 GrhSIM emu，并以相同的 XiangShan
CoreMark 50k difftest 口径测量 runtime，消除跨机器绝对时间不可比的问题。

## 测试时间与机器

测试窗口：`2026-07-10 14:58-15:41 CST`。

| 项目 | 值 |
| --- | --- |
| hostname | `corvus01` |
| OS / kernel | Ubuntu Linux `6.17.0-35-generic` |
| CPU | AMD Ryzen 9 9950X 16-Core Processor |
| 可见 logical CPUs | `32` (`0-31`) |
| CPU binding | `taskset -c 0` |

运行前确认没有残留 `clang++`、`make`、`mill`、`java`、`emu` 或 `gsim` 进程。

## 构建口径

GrhSIM 使用当前 `wolvrix` HEAD `fb12316`，其中包含 `NO0256` 的 full-mask
register commit direct-update 优化。其 emu 在 `2026-07-10 14:58:09 CST`
链接完成。

GSIM 不复用旧的 `build/xs/gsim` 产物，而是在独立目录重新从当前
`build/xs/rtl/rtl/SimTop.fir` 生成模型：

```text
build/xs/gsim_current_head_50k/gsim-compile/emu
```

该 fresh GSIM emit 生成 `331` 个 C++ 文件、`84714` 个 supernode，并在
`2026-07-10 15:39:27 CST` 链接完成。两边均使用 `clang++`，优化级别为 `-O3`。

## 运行口径

两边均执行：

```text
taskset -c 0 ./emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000
```

运行时关闭 waveform、runtime profile、commit trace 与 progress 输出。每个 simulator
连续运行两次；构建、emit 与编译时间均不计入 runtime。

## 结果

| simulator | host time run 1 | host time run 2 | mean host time | throughput |
| --- | ---: | ---: | ---: | ---: |
| GSIM | `31771 ms` | `31959 ms` | `31865.0 ms` | `1569.15 cycles/s` |
| GrhSIM | `263413 ms` | `264666 ms` | `264039.5 ms` | `189.37 cycles/s` |

两边所有运行均通过 difftest 并停在 cycle limit：

| simulator | guest cycle spent | instrCnt | cycleCnt |
| --- | ---: | ---: | ---: |
| GSIM | `50001` | `73584` | `49998` |
| GrhSIM | `50001` | `73580` | `49996` |

重复性：GSIM 两次差异为 `0.59%`，GrhSIM 两次差异为 `0.48%`。因此本轮差异不符合由
瞬时本机负载造成的特征。

```text
GrhSIM / GSIM = 264039.5 / 31865.0 = 8.2862x
```

当前同机、同 workload、同 CPU binding 口径下，GrhSIM host time 约为 GSIM 的
`8.29x`。

## 结论

本记录只固化当前机器上的可比 runtime 基线；不得将其绝对毫秒数与不同机器的历史
文档直接比较。后续性能改动应复用本记录的 emu、CPU binding 和 50k 命令口径，或在
同一轮中对两边重新构建并交错运行。
