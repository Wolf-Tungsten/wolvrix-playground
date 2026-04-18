# GSim Default XiangShan CoreMark Baseline（2026-04-18）

本文记录一次本地 `gsim` `default-xiangshan` + `coremark` 的实测基线，作为后续 `grhsim` 优化的对照参考。

## 口径

- `gsim` 目录：`tmp/gsim`
- `gsim` commit：`e9d9386798373b2293b19294da7e8a912c02e352`（`chore: add a bug report template (#105)`）
- workload：`ready-to-run/bin/coremark-NutShell.bin`
- 选择原因：`tmp/gsim/scripts/perf_l3.py` 对 `xiangshan-default` 使用的就是这份 `coremark` binary
- 独立构建目录：`tmp/gsim_default_xiangshan_coremark_20260418`
- 绑定 CPU：`taskset 0x1`

## 运行环境

- CPU：`AMD Ryzen 9 9950X 16-Core Processor`，`32` 线程
- L3：`64 MiB`
- OS：`Linux 6.17.0-20-generic`
- 编译器：`clang++ 22.1.2`
- 注意：`gsim` 的 Makefile 明确提示更推荐 `clang-19`，本次结果应视为“本机 clang-22 口径”

## 执行命令

```bash
cd tmp/gsim

make compile \
  dutName=default-xiangshan \
  BUILD_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/gsim_default_xiangshan_coremark_20260418 \
  mainargs=ready-to-run/bin/coremark-NutShell.bin

make build-emu \
  dutName=default-xiangshan \
  BUILD_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/gsim_default_xiangshan_coremark_20260418 \
  mainargs=ready-to-run/bin/coremark-NutShell.bin \
  -j 16

/usr/bin/time -v \
  taskset 0x1 \
  /home/gaoruihao/wksp/wolvrix-playground/tmp/gsim_default_xiangshan_coremark_20260418/default-xiangshan/SSimTop \
  ready-to-run/bin/coremark-NutShell.bin

perf stat -e \
  instructions,cycles,branches,branch-misses,cache-references,cache-misses,\
L1-dcache-loads,L1-dcache-load-misses,LLC-loads,LLC-load-misses \
  taskset 0x1 \
  /home/gaoruihao/wksp/wolvrix-playground/tmp/gsim_default_xiangshan_coremark_20260418/default-xiangshan/SSimTop \
  /home/gaoruihao/wksp/wolvrix-playground/tmp/gsim/ready-to-run/bin/coremark-NutShell.bin
```

## 生成阶段

### `gsim compile`

- 总耗时：`9:07.36`
- 峰值 RSS：`68 GiB`
- 最终图规模：
  - `131580` supernodes
  - `333758` defined nodes
- 输出文件：
  - `167` 个 `*.cpp`
  - `1` 个 `SimTop.h`

### 生成代码体量

- `model/` 总大小：`1668022994 B`，约 `1.6 GiB`
- `*.cpp` 总行数：`10289632`
- `SimTop.h` 行数：`333995`
- 生成代码总行数：`10623627`
- `SimTop.h` 大小：`43284678 B`，约 `42 MiB`
- 单个 `cpp` 平均大小：约 `9728972 B`，约 `9.3 MiB`
- 最大 `cpp`：`SimTop0.cpp`，`30599189 B`，约 `30 MiB`
- 最大几个 `cpp`：
  - `SimTop0.cpp`：`30599189 B`
  - `SimTop99.cpp`：`17489713 B`
  - `SimTop102.cpp`：`16814730 B`
  - `SimTop157.cpp`：`16050565 B`

### 构建产物

- `SSimTop` 可执行文件大小：`33 MiB`
- `emu/*.o` 总大小：`36999512 B`，约 `36 MiB`
- `default-xiangshan/` 整体目录大小：`1.7 GiB`

## CoreMark 运行结果

### Host 侧仿真性能

- 仿真总周期：`1900000`
- host 侧总耗时：`8:14.30`
- 平均仿真速度：`3843.82 cycles/s`
- 峰值 RSS：`554 MiB`
- CPU 利用率：`99%`

### Guest 侧 CoreMark 输出

- `Iterations = 10`
- `Finished in 13 ms`
- `CoreMark Iterations/Sec = 769230`

这里的 `13 ms` / `769230 Iterations/Sec` 是 guest 程序在模拟机器里看到的结果，不是 host 侧仿真吞吐；做 `grhsim` / `gsim` 对比时，应使用上一节的 host 侧 wall time / cycles per second。

## perf 结果

### 原始计数

- `instructions`：`1624914845425`
- `cycles`：`2804299799895`
- `branches`：`103241971266`
- `branch-misses`：`23351084090`
- `cache-references`：`363436546633`
- `cache-misses`：`216880302278`
- `L1-dcache-loads`：`894566615641`
- `L1-dcache-load-misses`：`18854602711`
- `perf stat` 总耗时：`502.50 s`

### 派生指标

- IPC：`0.58`
- 分支失效率：`22.62%`
- cache reference miss rate：`59.67%`
- L1D load miss rate：`2.11%`
- `perf` 运行下平均仿真速度：`3781.09 cycles/s`
- 每个模拟周期约消耗：
  - `1475947` host cycles
  - `855218` host instructions
  - `54338` branches
  - `191282` cache references

### 读数注意事项

- 本次 `perf stat` 事件组出现了约 `62.5%` 的 multiplex 比例，因此 miss rate 应视为近似值
- `LLC-loads` / `LLC-load-misses` 在本机不可用，没有拿到有效数据

## 对 `grhsim` 优化最有价值的结论

### 1. `gsim` 的编译阶段非常重，但运行阶段内存占用并不高

- `gsim compile` 需要约 `68 GiB` 峰值内存
- 但最终运行 `coremark` 时，`SSimTop` 峰值 RSS 只有约 `554 MiB`
- 这说明 `gsim` 的“生成期重、运行期相对收敛”的形态很明显

### 2. `gsim` 生成代码非常大，但最终可执行文件不大

- emitted model 约 `1.6 GiB`
- 最终 `SSimTop` 只有 `33 MiB`
- 对 `grhsim` 来说，这说明“源码体量大”本身不是决定性问题，关键还是热路径最终被编译器收敛成什么形态

### 3. 这份 baseline 更像“低 IPC + 高分支失配 + 深层缓存压力”，不是简单 L1D miss 问题

- IPC 只有 `0.58`
- 分支 miss 已经达到 `22.62%`
- `cache-references` miss rate 很高，但 `L1D load miss` 只有 `2.11%`
- 更合理的解释是：
  - 热路径分支非常多且可预测性差
  - 访存压力更多体现在更深层级或更零散的访问形态上
  - 不是单纯的 L1 数据缓存打爆

### 4. 后续拿 `grhsim` 对比时，建议至少对齐这几项

- host 侧总 wall time
- 仿真速度：`cycles/s`
- 峰值 RSS
- emitted cpp 总大小 / 总行数 / 文件数
- IPC
- branch miss rate
- cache reference miss rate

## 产物位置

- `gsim` 输出目录：`tmp/gsim_default_xiangshan_coremark_20260418/default-xiangshan`
- emitted model：`tmp/gsim_default_xiangshan_coremark_20260418/default-xiangshan/model`
- 可执行文件：`tmp/gsim_default_xiangshan_coremark_20260418/default-xiangshan/SSimTop`
- `gsim` 日志：`tmp/gsim_default_xiangshan_coremark_20260418/gsim.log`

## 附注

- 本次 `gsim` 运行出现两类 warning：
  - external clock signal 被当作 constant clock
  - `==` 驱动的 clock signal 被当作 constant clock
- 本文只记录性能基线，不讨论这些 warning 对功能正确性的影响
