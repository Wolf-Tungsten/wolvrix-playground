# NO0002 GrhSIM Default XiangShan CoreMark Baseline（2026-04-18）

> 归档编号：`NO0002`。目录顺序见 [`README.md`](./README.md)。

本文记录一次本地 `grhsim` XiangShan + `coremark` 的实测基线，尽量对齐前一份 `gsim` baseline 的测试口径，并明确记录无法完全对齐的部分。

## 口径

- workload：`tmp/gsim/ready-to-run/bin/coremark-NutShell.bin`
- 选择原因：与 [NO0001 GSim Default XiangShan CoreMark Baseline](./NO0001_gsim_default_xiangshan_coremark_baseline_20260418.md) 保持同一份 `coremark` binary
- CPU 绑定：`taskset 0x1`
- `grhsim` 运行口径：`--no-diff`
- clean emit 目录：`tmp/grhsim_default_xiangshan_coremark_20260418`
- clean `-j16` build 目录：`tmp/grhsim_default_xiangshan_coremark_20260418_j16`
- 注意：
  - `grhsim emu` 在 full-run 下速度过低，无法在合理时间内完成与 `gsim` 相同的 `1900000` cycle 全程测试
  - 因此本文的运行性能和 `perf` 数据使用固定 `30000` cycle 采样窗口
  - 仍然保留同一 workload、同一绑核方式、同一 host 环境，便于做量级对比

## 运行环境

- CPU：`AMD Ryzen 9 9950X 16-Core Processor`，`32` 线程
- OS：`Linux 6.17.0-20-generic`
- 编译器：`clang++ 22.1.2`

## 执行命令

### emit

```bash
/usr/bin/time -v \
  make --no-print-directory xs_wolf_grhsim_emit \
  XS_GRHSIM_BUILD=/home/gaoruihao/wksp/wolvrix-playground/tmp/grhsim_default_xiangshan_coremark_20260418 \
  RUN_ID=20260418_grhsim_coremark
```

### `-j16` 编译 emu

说明：第一次串行编译命令遗漏了 `-j`，未纳入基线；最终记录的是 clean source copy + `-j16` 的结果。

```bash
rsync -a --exclude='*.o' --exclude='*.a' \
  /home/gaoruihao/wksp/wolvrix-playground/tmp/grhsim_default_xiangshan_coremark_20260418/grhsim_emit/ \
  /home/gaoruihao/wksp/wolvrix-playground/tmp/grhsim_default_xiangshan_coremark_20260418_j16/grhsim_emit/

NOOP_HOME=/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan \
/usr/bin/time -v \
  make -j16 -C testcase/xiangshan/difftest emu \
  BUILD_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/grhsim_default_xiangshan_coremark_20260418_j16 \
  GEN_CSRC_DIR=/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/build/generated-src \
  NUM_CORES=1 WITH_CHISELDB=0 WITH_CONSTANTIN=0 \
  GRHSIM=1 \
  GRHSIM_MODEL_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/grhsim_default_xiangshan_coremark_20260418_j16/grhsim_emit \
  WOLVRIX_GRHSIM_WAVEFORM=0
```

### `30000` cycle 采样运行

```bash
/usr/bin/time -v \
  taskset 0x1 \
  /home/gaoruihao/wksp/wolvrix-playground/tmp/grhsim_default_xiangshan_coremark_20260418_j16/grhsim-compile/emu \
  -i /home/gaoruihao/wksp/wolvrix-playground/tmp/gsim/ready-to-run/bin/coremark-NutShell.bin \
  --no-diff -b 0 -e 0 -C 30000
```

### `perf stat`

```bash
perf stat -e \
  instructions,cycles,branches,branch-misses,cache-references,cache-misses,\
L1-dcache-loads,L1-dcache-load-misses,LLC-loads,LLC-load-misses \
  taskset 0x1 \
  /home/gaoruihao/wksp/wolvrix-playground/tmp/grhsim_default_xiangshan_coremark_20260418_j16/grhsim-compile/emu \
  -i /home/gaoruihao/wksp/wolvrix-playground/tmp/gsim/ready-to-run/bin/coremark-NutShell.bin \
  --no-diff -b 0 -e 0 -C 30000
```

## 生成阶段

### emit

- 总耗时：`16:54.81`
- 峰值 RSS：`67.67 GiB`
- `activity-schedule` 结果：
  - `74906` supernodes
  - `5779782` graph ops
  - `5134428` graph values
- supernode 统计：
  - mean `72.934`
  - median `70`
  - p90 `72`
  - p99 `135`
  - max `4096`

### `-j16` 编译 emu

- 总耗时：`6:09.26`
- 峰值 RSS：`1.51 GiB`
- CPU 利用率：`1565%`

### 生成代码体量

### source-only 体量

- `*.cpp` 文件数：`9500`
- `*.hpp` 文件数：`2`
- `sched_*.cpp` 文件数：`9364`
- `state_init_*.cpp` 文件数：`62`
- `state_commit_shadow_*.cpp` 文件数：`70`
- `state_commit_write_*.cpp` 文件数：`2`
- `*.cpp` 总大小：`2587915104 B`，约 `2.41 GiB`
- `*.hpp` 总大小：`644616 B`
- source-only 总大小：`2588559720 B`，约 `2.41 GiB`
- `*.cpp` 总行数：`1374656`
- `*.hpp` 总行数：`12258`
- source-only 总行数：`1386914`
- 单个 `cpp` 平均大小：约 `272412 B`，约 `266 KiB`
- 最大几个源码文件：
  - `grhsim_SimTop_sched_4070.cpp`：`4949057 B`
  - `grhsim_SimTop_state_commit_shadow_67.cpp`：`2979339 B`
  - `grhsim_SimTop_state_commit_shadow_68.cpp`：`2975265 B`
  - `grhsim_SimTop_state_commit_shadow_65.cpp`：`2955205 B`

### 生成目录里的大辅助文件

- `grhsim_SimTop_declared_value_index.txt`：`24016617560 B`，约 `22.37 GiB`
- 这意味着：
  - 如果看 `grhsim_emit/` 整体目录大小，主要是被这个索引文件撑大
  - 如果只想和 `gsim` 比较“生成代码体量”，应优先使用上一节的 source-only 统计

### 构建产物

- `libgrhsim_SimTop.a`：`248 MiB`
- `emu`：`222 MiB`
- `grhsim-compile/`：`222 MiB`
- `grhsim_emit/`：`26 GiB`
- `tmp/grhsim_default_xiangshan_coremark_20260418_j16/`：`26 GiB`

## CoreMark 运行结果

### 运行口径说明

- full-run 目标如果按 `gsim` baseline 的 `1900000` cycles 估算，在当前 `grhsim` 上大约需要 `8h6m23s`
- 因此本文不记录 guest 完整跑完后的 `Iterations/Sec`
- 这里关注的是 host 侧“每秒能跑多少模拟周期”

### `30000` cycle 采样

- 采样上限：`30000` cycles
- 实际 guest cycle：`30001`
- host 侧 wall time：`7:40.82`
- `emu` 打印的 host time：`460800 ms`
- 平均仿真速度：`65.11 cycles/s`
- 峰值 RSS：`251 MiB`
- CPU 利用率：`99%`
- 到 `30000` cycles 时 guest 尚未跑完整个 CoreMark，只到：
  - `pc = 0x80000644`
  - `instrCnt = 29365`
  - `cycleCnt = 29996`

## perf 结果

### 原始计数

- 采样窗口：`30001` simulated cycles
- `instructions`：`369394256495`
- `cycles`：`2480861926069`
- `branches`：`61151436800`
- `branch-misses`：`10921375455`
- `cache-references`：`76581175604`
- `cache-misses`：`39826196906`
- `L1-dcache-loads`：`242693950209`
- `L1-dcache-load-misses`：`9262953213`
- `perf stat` 总耗时：`444.60 s`

### 派生指标

- IPC：`0.15`
- 分支失效率：`17.86%`
- cache reference miss rate：`52.01%`
- L1D load miss rate：`3.82%`
- `perf` 运行下平均仿真速度：`67.48 cycles/s`
- 每个模拟周期约消耗：
  - `82692641` host cycles
  - `12312731` host instructions
  - `2038313` branches
  - `2552621` cache references

### 读数注意事项

- 本次 `perf stat` 事件组仍然出现了约 `62.5%` 的 multiplex 比例，因此 miss rate 应视为近似值
- `LLC-loads` / `LLC-load-misses` 在本机不可用

## 与 `gsim` baseline 的直接对照

- workload 已对齐：同一份 `coremark-NutShell.bin`
- 绑核已对齐：同为 `taskset 0x1`
- 但运行窗口未完全对齐：
  - `gsim` 能直接跑完整个 `1900000` cycle workload
  - `grhsim` 在当前版本下 full-run 不现实，因此只能使用 `30000` cycle 采样

### 能直接比较的量级

- host 侧速度：
  - `gsim`：`3843.82 cycles/s`
  - `grhsim`：`65.11 cycles/s`
  - 当前 `grhsim` 约慢 `59.0x`
- 生成源码文件数：
  - `gsim`：`167` 个 `*.cpp`
  - `grhsim`：`9500` 个 `*.cpp`
  - 当前 `grhsim` 约多 `56.9x`
- 生成代码 source-only 体量：
  - `gsim model/`：约 `1.6 GiB`
  - `grhsim source-only`：约 `2.41 GiB`
  - 当前 `grhsim` 约大 `1.55x`
- 最终可执行文件：
  - `gsim SSimTop`：`33 MiB`
  - `grhsim emu`：`222 MiB`
  - 当前 `grhsim` 约大 `6.7x`
- host IPC：
  - `gsim`：`0.58`
  - `grhsim`：`0.15`

## 对 `grhsim` 优化最有价值的结论

### 1. 当前最大问题已经不是“能不能编出来”，而是运行速度低到无法做 full-run 基线

- 即使去掉 difftest，只跑纯 `grhsim emu`
- `30000` cycles 仍然需要约 `7.7` 分钟
- 如果按 `gsim` 的 `1900000` cycle workload 外推，约要 `8.1` 小时

### 2. `grhsim` 的 emitted 形态和 `gsim` 完全不同，文件碎片化非常严重

- `gsim` 是 `167` 个大 `cpp`
- `grhsim` 是 `9500` 个 `cpp`，其中 `9364` 个是 `sched_*.cpp`
- 这已经不是简单的“单文件太大”问题，而是 file packing 过细

### 3. `grhsim_emit` 目录体量被辅助索引文件严重放大

- `grhsim_SimTop_declared_value_index.txt` 单文件就约 `22.37 GiB`
- 后续如果做“生成体量”对比，建议把：
  - source-only 代码体量
  - 辅助索引 / 调试文件体量
  - 编译产物体量
  分开统计

### 4. host 侧 perf 特征比 `gsim` 更差，尤其是 IPC

- `grhsim` IPC 只有 `0.15`
- 远低于 `gsim` 的 `0.58`
- 分支失配和 cache miss 也不低，但最醒目的差异仍然是：
  - 每个模拟周期消耗的 host 指令数和 host cycles 都极高
  - 当前热路径的前端/调度/访存综合效率明显更差

## 产物位置

- clean emit：`tmp/grhsim_default_xiangshan_coremark_20260418/grhsim_emit`
- clean `-j16` build：`tmp/grhsim_default_xiangshan_coremark_20260418_j16`
- `emu`：`tmp/grhsim_default_xiangshan_coremark_20260418_j16/grhsim-compile/emu`
- `30000` cycle 时间日志：`tmp/grhsim_default_xiangshan_coremark_20260418_j16/logs/coremark_nutshell_30k_time.log`
- `perf` 日志：`tmp/grhsim_default_xiangshan_coremark_20260418_j16/logs/coremark_nutshell_30k_perf.log`
