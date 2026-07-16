---
id: NO00028
date: 2026-07-16
title: XiangShan executable GRH reset and synchronous memory read alignment
kind: diagnosis
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, grh-json, async-reset, synchronous-memory, xiangshan, coremark, difftest]
parents: [NO00027]
related: [NO00007, NO00025, NO00026]
supersedes: []
---

# NO00028 XiangShan executable GRH reset and synchronous memory read alignment (2026-07-16)

> 归档编号：`NO00028`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## 目标与搜索树

NO00027 已完成 GSim executable GRH 导出、GrhSIM 导入/emit、target-512 model 编译和
XiangShan `emu` 链接，但首次 CoreMark gate 在启动期触发 `MSHR.scala:1472`。本记录从首个
可观察差异向后搜索，并保持以下分支相互独立：

1. async reset 首次 eval 的 event baseline；
2. register/commit 调度和 event identity；
3. synchronous memory read 的地址与 read-under-write 时序；
4. wrapper、DPI 和 difftest ABI。

每次只改变一个语义变量。gate 顺序为 exporter fixture、full export、GrhSIM import/emit、model
compile、XiangShan 短周期 difftest，最后才运行 CoreMark 50k。

## Async reset 首次 event 修复

NO00007 的 executable-GRH contract 把 base clock 放在 register-write event inputs 的首位，后续
inputs 是 async reset event。GrhSIM 原先在首次 eval 统一抑制所有 edge，导致启动时已拉高的
async reset 没有产生 posedge，部分寄存器未初始化，最终立即触发 MSHR assertion。

`wolvrix/lib/emit/grhsim_cpp.cpp` 现在只对带 `gsim.reset_kind=async` 的 reset event inputs 允许
从零初始化 baseline 检测首次 edge；base clock 和其他 event 仍保持原来的首次抑制规则。

使用 NO00026 的同一 JSON 重新 import/emit 后，MSHR assertion 消失。证据目录：

```text
ptmp/gsim_assign_elide_20260716/baseline_async_fix/
```

模型执行到 cycle 8262、完成 36 条指令后发生首个 NEMU mismatch。direct-SV 对照在 cycle 8262
的 `pc=0x80000080` 指令为 `0x0000d117`，exchange 模型却读为 `0x680000ef`。因此 async reset
分支已通过首错迁移验证，新的首错属于取指数据路径。

## Synchronous memory read 地址根因

对 ICache read/write、RAM path 和 pre-commit 数据做逐层 probe 后，强制下一拍 ICache 地址可把
首错从 cycle 8262/36 instructions 推迟到 cycle 8323/40 instructions；随后 refill data 变为全零。
该实验排除了 difftest ABI 和 node-final assign，指向同步 memory read 地址多延迟一拍。

GSim 的 `rlatency=1` memory reader 已包含生成的地址寄存器：当前请求写入该寄存器，memory data
在同一 edge 采样这个 destination。旧 exporter 却使用地址寄存器 source 读取 memory，等价于再
增加一拍延迟。`reference/gsim/src/ExecutableGrhExporter.cpp` 已改为：

- 以生成地址寄存器 destination/current request 作为 `kMemoryReadPort` 地址；
- 仍把 memory data 写入独立 read-data register；
- 保持 `ruw=new` forwarding 使用同一个当前 read address。

定向 fixture `executable-grh-synchronous-memory-address` 已通过。新的 full XiangShan export：

```text
ptmp/gsim_assign_elide_20260716/exporter_sync_mem_fix/gsim/SimTop.exec.json
bytes=2784160317
sha256=a6f363196dd8cc6a999ec62d6793af91a52c9bd3bb2c9113c0f2e5ef48788004
export wall=10:08.93
export maxRSS=99405788 KiB
exit=0
```

JSON envelope counts 与 NO00026 一致；修复只改变同步 reader 的地址引用，不改变图规模。

## 待执行 gate

新 JSON 尚需完成 target-512 GrhSIM import/emit、model compile、XiangShan emu link、短周期
difftest 和最终 CoreMark 50k。产物统一写入：

```text
ptmp/gsim_assign_elide_20260716/sync_mem_fix_target512/
```

## 增量更新

后续在此记录本轮同一 root-cause gate 的结果；若首错迁移到独立语义问题，则创建新的记录。

### 2026-07-16 target-512 import/emit

修复后 JSON 使用当前 `.venv` native binding 完成 LoadJson、activity-schedule 和 GrhSIM C++
emit，exit 0：

```text
read_gsim_executable_grh=18.867 s
activity-schedule=91.941 s
write_grhsim_cpp=48.738 s
wall=2:41.01
maxRSS=26949220 KiB
```

当前工作树 scheduler 使用 `108 * 32 = 3456` 的内部 coarsen 上限；因此这次得到 25,071 个
compute supernodes，而 NO00027 的固定旧 binding 是 84,439。该差异已显式记录，不能把两者当作
仅改变 memory address 的结构 A/B。语义图规模保持稳定：scheduler input 5,268,557 ops、source
clone 后 7,930,766 ops、10,468,927 topo edges。commit bucket 修复生效，为 43 个 commit
supernodes、最大 4,096 ops。

emit 生成 643 个 C++ files，总计 1,065,300,711 bytes，最大 TU 5,940,341 bytes。下一 gate 是
`clang++ -O3 -j32` model archive。

### 2026-07-16 target-512 model archive

修复后模型完成 `clang++ -std=c++20 -O3 -j32` 全量编译和静态归档，exit 0：

```text
objects=643/643
wall=29:14.06
user=24941.95 s
system=80.22 s
maxRSS=891020 KiB
libgrhsim_SimTop.a=165310212 bytes
```

最后六个长尾 TU 为 `sched_{150,184,208,520,522,523}`；它们持续占用 CPU 并在 30 分钟
timeout 前完成，因此本轮没有采用降优化级别、混合对象或重新 emit 的恢复分支。NO00027 的旧
binding 在 4:57.20 完成 archive，本轮 scheduler coarsen、supernode 数和 TU 划分均已变化，
29:14.06 不能解释为同步 memory 地址修复本身造成的编译回退，也不能作为严格性能 A/B。

证据：

```text
ptmp/gsim_assign_elide_20260716/sync_mem_fix_target512/logs/model_compile.log
ptmp/gsim_assign_elide_20260716/sync_mem_fix_target512/grhsim_emit/libgrhsim_SimTop.a
```

下一 gate 是链接独立 XiangShan difftest `emu`，随后按短周期到 50k 的顺序验证；正确性基准为
10k `pc=0x800027c6, instrCnt=458, cycleCnt=9996`，以及 50k
`pc=0x80001312, instrCnt=73580, cycleCnt=49996`，且全程无 NEMU mismatch、进程 exit 0。

### 2026-07-16 XiangShan difftest emulator link

target-512 archive 接入独立 XiangShan `grhsim-build-emu`，wrapper 编译和链接成功：

```text
wall=7.42 s
user=6.67 s
system=0.75 s
maxRSS=257640 KiB
exit=0
grhsim-compile/emu=126741256 bytes
```

产物是动态链接、未 strip 的 x86-64 PIE ELF；`ldd` 所列 `zlib`、`zstd`、C++ runtime 和 libc
均可解析。下一 gate 是 2k sanity，用于确认启动期 MSHR assertion 和 cycle 8262 的错误取指均未
复现；通过后再运行 10k golden 对齐。

### 2026-07-16 CoreMark 2k sanity

2k NEMU difftest exit 0，启动期 MSHR assertion 未复现：

```text
Difftest enabled
pc=0x0
instrCnt=3
cycleCnt=1996
guest cycles=2001
wall=10.41 s
maxRSS=149864 KiB
exit=0
```

日志中无 `Assertion failed`、`mismatch` 或 `ABORT`。2k 尚未覆盖旧首错 cycle 8262，因此只关闭
启动 sanity 分支，不足以证明同步 memory 地址修复完成；下一步必须运行 10k。

证据：

```text
ptmp/gsim_assign_elide_20260716/sync_mem_fix_target512/logs/coremark_2k.log
```

### 2026-07-16 CoreMark 10k golden alignment

10k NEMU difftest 精确匹配 direct-SV golden，exit 0：

```text
Difftest enabled
pc=0x800027c6
instrCnt=458
cycleCnt=9996
IPC=0.045818
guest cycles=10001
wall=36.66 s
maxRSS=150120 KiB
exit=0
```

日志中无 `Assertion failed`、`mismatch` 或 `ABORT`。该运行已越过旧 executable-GRH 首错
cycle 8262；原模型在该点错误执行 `0x680000ef` 并于 36 instructions 发生 `ra/sp` mismatch，
修复后继续到 10k 且提交 458 instructions，与 direct-SV 的 PC、instruction count 和 cycle count
逐项一致。因此同步 memory read 地址多延迟一拍的诊断通过首错迁移和 golden 对齐双重验证。

证据：

```text
ptmp/gsim_assign_elide_20260716/sync_mem_fix_target512/logs/coremark_10k.log
sha256=c3d171e6b286675accf7770f37d3bc3d072a13a9733a131d2e62d979761fa580
```

最后 gate 是 50k；必须达到既有 golden `pc=0x80001312, instrCnt=73580,
cycleCnt=49996`，全程无 NEMU mismatch 且 exit 0，才能关闭本轮正确性目标。

### 2026-07-16 CoreMark 50k final gate

最终 50k NEMU difftest 依次通过 10k、20k、30k、40k 和 50k checkpoints，精确匹配既有
direct-GrhSIM / direct-SV golden，exit 0：

```text
Difftest enabled
pc=0x80001312
instrCnt=73580
cycleCnt=49996
IPC=1.471718
guest cycles=50001
wall=11:45.19
host time=705182 ms
maxRSS=150732 KiB
exit=0
```

日志中无 `Assertion failed`、`mismatch` 或 `ABORT`。从同步 memory exporter fixture、full
XiangShan export、LoadJson/activity-schedule/emit、643-object archive、emu link、2k sanity、10k
golden 到 50k golden 的完整 gate 均已通过。因此本轮结论是：GSim `rlatency=1` reader 必须用
生成地址寄存器的 destination/current-request 读取 memory；继续使用 source 会额外增加一拍并
破坏 ICache 取指。async-reset 首次 event 和同步 memory read address 两项修复共同恢复了
GSim executable GRH -> GrhSIM 链路的 XiangShan CoreMark 50k 正确性。

本轮树搜索关闭以下分支：

1. async reset baseline：修复后启动期 MSHR assertion 消失；
2. synchronous memory address：10k 首错迁移和 50k golden 均验证修复；
3. difftest ABI / node-final assign：未成为本轮首错根因；
4. model compile 长尾：在原 30 分钟 timeout 内成功，不需要恢复分支。

证据：

```text
ptmp/gsim_assign_elide_20260716/sync_mem_fix_target512/logs/coremark_50k.log
sha256=06f8301d214cca8af4a0de023f69dfcde7876e4e260c3cd44f396253c607bca3
```
